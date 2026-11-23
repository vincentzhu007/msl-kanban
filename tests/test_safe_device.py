import hashlib
import json
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from daily_ci.pipeline import deploy_files, run
from daily_ci.safe_br_io import (
    RESUME_MAGIC, SafeStop, SafeTransportError, probe_connect, pull_file, push_file, validate_host_port,
)
from daily_ci.safe_transport import (
    DETACHED_WORKER_NOTE, SafeSession, aa_start_shell, choose_host_port, decode_hilog_stream,
    open_safe_session, parse_forwards, plan_host_port, refuse_serial, requires_safe_norestart,
)
from daily_ci.workflow_tasks import ORIGINAL_FIVE, SCHEDULED, select_tasks
from recipe_ci.execution import execute
from recipe_ci.planner import resolve
from recipe_ci.recipe import load

SERIAL = '127.0.0.1:2000'
HISTORICAL_HASHES = (
    '6868d15f1805e036c2ab2f4a4ca15a24189a7475741f78f78f0de5aeab602d5b',
    '44ee68d8d34ea39ac21d6a23209a3b8c96899aba79e90ed207ccbab4833205e8',
    '05c304249884d7674a415442eb437042844a53745e3a73f9d66f2c4f6ee438a1',
    '29e904924e12e4bc351f9b99569602f1fd2bb7b2a8cf4ea3c160866ca795b046',
)


class ListingHdc:
    def __init__(self, rows):
        self.rows = list(rows)
        self.calls = []

    def __call__(self, serial, args, timeout):
        self.calls.append((serial, list(args)))
        if args == ['fport', 'ls']:
            text = ''.join(f'{a} {b} {c} [Forward]\n' for a, b, c in self.rows)
            return subprocess.CompletedProcess(args, 0, text, '')
        if args[:1] == ['fport'] and args[1:2] != ['rm'] and 'ls' not in args:
            self.rows.append((serial, args[1], args[2]))
            return subprocess.CompletedProcess(args, 0, 'OK\n', '')
        if args[:2] == ['fport', 'rm']:
            self.rows = [row for row in self.rows if row[1:] != tuple(args[2:4])]
            return subprocess.CompletedProcess(args, 0, 'OK\n', '')
        if args[:1] == ['shell']:
            return subprocess.CompletedProcess(args, 0, '', '')
        raise AssertionError(args)


def config_for(task_id, port):
    return {
        'task_id': task_id,
        'device_transport': {'mode': 'safe_norestart', 'preferred_host_port': port, 'device_port': 8888},
        'environment': {'device': {'serial': SERIAL}},
    }


class PortPolicyTests(unittest.TestCase):
    def test_library_rejects_reserved_ports_before_connecting(self):
        def explode(*_args, **_kwargs):
            raise AssertionError('socket was opened')
        with patch('daily_ci.safe_br_io.socket.create_connection', side_effect=explode):
            for port in (8888, 18888, 19005, 19146, 19160):
                with self.assertRaises(SafeTransportError):
                    validate_host_port(port)
                with self.assertRaises(SafeTransportError):
                    push_file(port, __file__, 'name.txt')
                with self.assertRaises(SafeTransportError):
                    pull_file(port, 'name.txt', 'out.bin')
                with self.assertRaises(SafeTransportError):
                    probe_connect(port)

    def test_refused_and_timed_out_connections_do_not_retry_or_restart(self):
        with patch('daily_ci.safe_br_io.socket.create_connection',
                   side_effect=ConnectionRefusedError('connection refused')):
            with self.assertRaises(SafeStop) as refused:
                push_file(19147, __file__, 'safe.txt', backoff=0, attempts=3)
        self.assertIn('not restarting', str(refused.exception))
        with patch('daily_ci.safe_br_io.socket.create_connection',
                   side_effect=TimeoutError('timed out')):
            with self.assertRaises(SafeStop):
                probe_connect(19148, connect_timeout=0.01)
        self.assertNotIn('force-stop', Path(ROOT / 'scripts/daily_ci/safe_br_io.py').read_text().split('"""', 2)[2])
        self.assertNotIn('subprocess', Path(ROOT / 'scripts/daily_ci/safe_br_io.py').read_text())

    def test_unknown_forward_survives_create_and_only_our_tuple_is_removed(self):
        hdc = ListingHdc([(SERIAL, 'tcp:19005', 'tcp:8888')])
        env = {'device': {'serial': SERIAL}}
        config = config_for('qwen25-15b-msl-w4a16-kirin9020', 19147)
        with tempfile.TemporaryDirectory() as tmp:
            with open_safe_session(env, config, Path(tmp), 19147, hdc=hdc) as session:
                self.assertEqual(session.port, 19147)
                self.assertFalse(session.worker_observed_exited)
            note = json.loads((Path(tmp) / 'safe-transport.json').read_text())
        self.assertFalse(note['worker_observed_exited'])
        self.assertIn('does not mean the worker exited', note['note'])
        self.assertEqual(hdc.rows, [(SERIAL, 'tcp:19005', 'tcp:8888')])
        removed = [args for _serial, args in hdc.calls if args[:2] == ['fport', 'rm']]
        self.assertEqual(removed, [['fport', 'rm', 'tcp:19147', 'tcp:8888']])

    def test_port_race_and_wrong_rm_do_not_edit_other_forwards(self):
        hdc = ListingHdc([(SERIAL, 'tcp:19005', 'tcp:8888')])

        class Raced:
            def __init__(self):
                self.listings = 0

            def __call__(self, serial, args, timeout):
                if args == ['fport', 'ls']:
                    self.listings += 1
                    if self.listings >= 2:
                        hdc.rows = [(SERIAL, 'tcp:19005', 'tcp:8888'), (SERIAL, 'tcp:19147', 'tcp:8888')]
                return hdc(serial, args, timeout)

        env = {'device': {'serial': SERIAL}}
        config = config_for('qwen25-15b-msl-w4a16-kirin9020', 19147)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SafeTransportError):
                with open_safe_session(env, config, Path(tmp), 19147, hdc=Raced()):
                    pass
        self.assertFalse(any(args[:2] == ['fport', 'rm'] for _s, args in hdc.calls))
        self.assertIn((SERIAL, 'tcp:19005', 'tcp:8888'), hdc.rows)
        session = SafeSession(SERIAL, 19147, hdc, None)
        with self.assertRaises(SafeTransportError):
            session.hdc(['fport', 'rm', 'tcp:19005', 'tcp:8888'])
        with self.assertRaises(SafeTransportError):
            session.hdc(['shell', 'aa', 'force-stop', 'com.example.binrunner'])

    def test_tts_serial_is_refused_before_hdc(self):
        calls = []
        with self.assertRaises(SafeTransportError):
            refuse_serial('127.0.0.1:3000')
        with self.assertRaises(SafeTransportError):
            plan_host_port(
                {'device': {'serial': '127.0.0.1:3000'}},
                config_for('qwen25-15b-msl-w4a16-kirin9020', 19147),
                listing_text='', listeners=set())
        self.assertEqual(calls, [])
        listing = '127.0.0.1:3000 tcp:19005 tcp:8888 [Forward]\n'
        with self.assertRaises(SafeTransportError):
            plan_host_port(
                {'device': {'serial': SERIAL}},
                config_for('qwen25-15b-msl-w4a16-kirin9020', 19147),
                listing_text=listing, listeners=set())

    def test_preferred_port_skips_a_busy_candidate_inside_the_range(self):
        rows = parse_forwards(f'{SERIAL} tcp:19147 tcp:8888 [Forward]\n{SERIAL} tcp:19005 tcp:8888 [Forward]\n')
        self.assertEqual(choose_host_port(rows, {19148}, 19147), 19149)


class TransferTests(unittest.TestCase):
    def test_partial_push_resumes_without_a_restart_command(self):
        payload = b'A' * (4 * 1024 * 1024)
        stored = bytearray()
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', 19149))
        server.listen(2)
        server.settimeout(5)

        def read_exact(conn, size):
            buf = b''
            while len(buf) < size:
                chunk = conn.recv(size - len(buf))
                if not chunk:
                    raise RuntimeError('short read')
                buf += chunk
            return buf

        def read_header(conn):
            magic = read_exact(conn, 4)
            if magic == struct.pack('<I', RESUME_MAGIC):
                flags, name_len = struct.unpack('<II', read_exact(conn, 8))
                read_exact(conn, name_len)
                size, = struct.unpack('<Q', read_exact(conn, 8))
                if flags & 1:
                    probe_len, = struct.unpack('<I', read_exact(conn, 4))
                    read_exact(conn, probe_len)
                return size
            name_len, = struct.unpack('<I', magic)
            read_exact(conn, name_len)
            size, = struct.unpack('<Q', read_exact(conn, 8))
            return size

        def serve():
            for round_number in (1, 2):
                conn, _addr = server.accept()
                try:
                    size = read_header(conn)
                    if round_number == 1:
                        conn.sendall(struct.pack('<Q', 0))
                        stored.extend(read_exact(conn, 1024 * 1024))
                    else:
                        conn.sendall(struct.pack('<Q', len(stored)))
                        stored.extend(read_exact(conn, size - len(stored)))
                        conn.sendall(struct.pack('<Q', size))
                finally:
                    conn.close()

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                local = Path(tmp) / 'model.msl'
                local.write_bytes(payload)
                result = push_file(19149, str(local), 'model.msl', backoff=0, ack_timeout=2, connect_timeout=2)
            self.assertEqual(result['bytes'], len(payload))
            self.assertEqual(bytes(stored), payload)
        finally:
            thread.join(5)
            server.close()

    def test_pull_byte_count_is_not_identity_and_a_bad_hash_is_rejected(self):
        body = b'not-the-model'
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', 19150))
        server.listen(1)
        server.settimeout(5)

        def serve_once():
            conn, _addr = server.accept()
            try:
                conn.recv(256)
                conn.sendall(struct.pack('<Q', len(body)) + body)
            finally:
                conn.close()

        threading.Thread(target=serve_once).start()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'pulled.bin'
            result = pull_file(19150, 'note.log', str(target), transfer_timeout=2)
            self.assertEqual(result['bytes'], len(body))
            self.assertFalse(result['identity'])
            digest = hashlib.sha256(body).hexdigest()
            self.assertEqual(result['sha256'], digest)
        server.close()
        server = socket.socket()
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(('127.0.0.1', 19152))
        server.listen(1)
        server.settimeout(5)
        threading.Thread(target=serve_once).start()
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'pulled.bin'
            with self.assertRaises(SafeTransportError):
                pull_file(19152, 'note.log', str(target), expected_sha256='ab' * 32, transfer_timeout=2)
            self.assertFalse(target.exists())
        server.close()

    def test_probe_reports_reachability_without_device_identity(self):
        server = socket.socket()
        server.bind(('127.0.0.1', 19153))
        server.listen(1)
        server.settimeout(2)

        def accept_once():
            try:
                conn, _addr = server.accept()
                conn.close()
            except OSError:
                pass

        thread = threading.Thread(target=accept_once)
        thread.start()
        try:
            result = probe_connect(19153, connect_timeout=2)
            thread.join(2)
        finally:
            server.close()
        self.assertEqual(set(result), {'reachable', 'host', 'port'})


class OfficialPathTests(unittest.TestCase):
    def test_only_the_two_15b_tasks_select_safe_transport(self):
        for task_id in ORIGINAL_FIVE:
            task = json.loads((ROOT / 'config/daily' / (task_id + '.json')).read_text())
            self.assertNotIn('device_transport', task)
            self.assertNotIn('export_environment', json.dumps(task))
            self.assertFalse(requires_safe_norestart(task, task_id))
        for task_id, port in (('qwen25-15b-msl-w4a16-kirin9020', 19147),
                              ('qwen25-15b-msl-q30-kirin9020', 19151)):
            task = json.loads((ROOT / 'config/daily' / (task_id + '.json')).read_text())
            self.assertTrue(requires_safe_norestart(task, task_id))
            self.assertEqual(task['device_transport']['preferred_host_port'], port)
            self.assertNotIn('blocked', task)
        borrowed = {'task_id': ORIGINAL_FIVE[0], 'device_transport': {'mode': 'safe_norestart'}}
        with self.assertRaises(SafeTransportError):
            requires_safe_norestart(borrowed, ORIGINAL_FIVE[0])

    def test_safe_deploy_does_not_call_br_or_ensure_forward(self):
        pushed = []

        class Transport:
            def probe(self):
                return {'reachable': True, 'host': '127.0.0.1', 'port': 19147}

            def push_host(self, path, log):
                pushed.append(Path(path).name)

        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / 'recipe-msl'
            probe.write_bytes(b'probe')
            model = Path(tmp) / 'model.msl'
            model.write_bytes(b'model')
            env = {'device': {'serial': SERIAL, 'port': '19147'}, 'binrunner': '/assets/binrunner',
                   'artifacts': {'model': {'host_path': str(model), 'device_path': '@/bin/daily-model.msl'}}}
            with patch('daily_ci.pipeline.ensure_forward', side_effect=AssertionError('ensure_forward')), \
                 patch('daily_ci.pipeline.run_command', side_effect=AssertionError('br')), \
                 patch('daily_ci.pipeline.push_with_resume', side_effect=AssertionError('br retry')):
                deploy_files(env, {}, Path(tmp), probe, True, Transport())
            self.assertEqual(pushed, ['recipe-msl', 'daily-model.msl'])

    def test_existing_deploy_still_uses_br(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            probe = Path(tmp) / 'recipe-msl'
            probe.write_bytes(b'probe')
            env = {'device': {'serial': SERIAL, 'port': '18888'}, 'binrunner': tmp}
            with patch('daily_ci.pipeline.ensure_forward', side_effect=lambda *args: calls.append(('forward', args))), \
                 patch('daily_ci.pipeline.run_command', side_effect=lambda cmd, *_a, **_k: calls.append(cmd)):
                deploy_files(env, {'binrunner_device_port': 8888}, Path(tmp), probe, False, None)
        self.assertEqual(calls[0][0], 'forward')
        self.assertEqual(calls[1][:4], ['python3', '-m', 'binrunner', '-t'])

    def test_public_15b_config_without_environment_refuses_before_br(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            config = json.loads((ROOT / 'config/daily/qwen25-15b-msl-w4a16-kirin9020.json').read_text())
            with patch('daily_ci.pipeline.discover', side_effect=AssertionError('discover')):
                with self.assertRaises(SafeTransportError):
                    run(repo, ROOT / 'recipes/qwen25-15b-msl-w4a16-kirin9020.json', config, '20261123')

    def test_bad_sandbox_hash_and_existing_worker_do_not_call_binrunner(self):
        recipe = load(ROOT / 'recipes/qwen3-4b-msl-s16s4-kirin9030.json')
        env = json.loads((ROOT / 'config/dog-kirin9030.example.json').read_text())
        env['output_root'] = '/tmp'
        lock = resolve(recipe, env, verify_files=False)
        lock['host_artifacts_verified'] = True
        invocations = []

        class Transport:
            closed = False

            def invoke(self, args, timeout):
                invocations.append(args)
                return subprocess.CompletedProcess(args, 0, 'deadbeef\n', '')

        def hdc(command, **_kwargs):
            self.assertNotIn('binrunner', command)
            self.assertNotIn('force-stop', command)
            return subprocess.CompletedProcess(command, 0, '1 init\n', '')

        with tempfile.TemporaryDirectory() as tmp:
            env['output_root'] = tmp
            lock['environment'] = dict(lock['environment'], output_root=tmp)
            with patch('recipe_ci.execution.device_lease', return_value=nullcontext()), \
                 patch('recipe_ci.execution.awake_device', return_value=nullcontext()), \
                 patch('recipe_ci.execution.resolve', return_value=lock), \
                 patch('recipe_ci.execution.subprocess.run', side_effect=hdc):
                with self.assertRaises(Exception) as caught:
                    execute(lock, transport=Transport())
            self.assertIn('SHA256', str(caught.exception))
            self.assertTrue(invocations)
            invocations.clear()

            def busy(command, **_kwargs):
                return subprocess.CompletedProcess(command, 0, '9 recipe-msl\n', '')

            with patch('recipe_ci.execution.device_lease', return_value=nullcontext()), \
                 patch('recipe_ci.execution.awake_device', return_value=nullcontext()), \
                 patch('recipe_ci.execution.resolve', return_value=lock), \
                 patch('recipe_ci.execution.subprocess.run', side_effect=busy):
                with self.assertRaises(Exception) as caught:
                    execute(lock, transport=Transport())
            self.assertIn('Existing worker', str(caught.exception))
            self.assertEqual(invocations, [])

    def test_launch_failure_keeps_the_detached_worker_note(self):
        recipe = load(ROOT / 'recipes/qwen3-4b-msl-s16s4-kirin9030.json')
        env = json.loads((ROOT / 'config/dog-kirin9030.example.json').read_text())
        lock = resolve(recipe, env, verify_files=False)
        lock['host_artifacts_verified'] = True
        class Transport:
            def invoke(self, args, timeout):
                if args[0] == 'run' and 'sha256sum' in args[1]:
                    for artifact in lock['environment']['artifacts'].values():
                        device_path = artifact.get('device_path', '')
                        if device_path and device_path in args[1]:
                            return subprocess.CompletedProcess(args, 0, artifact['sha256'] + '  file\n', '')
                return subprocess.CompletedProcess(args, 1, 'no worker line\n', '')

        def hdc(command, **_kwargs):
            self.assertNotIn('binrunner', command)
            self.assertNotIn('force-stop', command)
            text = '1 init\n' if str(command[-1]).startswith('ps ') else 'memory\n'
            return subprocess.CompletedProcess(command, 0, text, '')

        with tempfile.TemporaryDirectory() as tmp:
            env['output_root'] = tmp
            lock = resolve(recipe, env, verify_files=False)
            lock['host_artifacts_verified'] = True
            lock['environment']['output_root'] = tmp
            with patch('recipe_ci.execution.device_lease', return_value=nullcontext()), \
                 patch('recipe_ci.execution.awake_device', return_value=nullcontext()), \
                 patch('recipe_ci.execution.resolve', return_value=lock), \
                 patch('recipe_ci.execution.subprocess.run', side_effect=hdc), \
                 patch('bench_common.runner.subprocess.run', side_effect=hdc):
                with self.assertRaises(RuntimeError):
                    execute(lock, transport=Transport())
            notes = list(Path(tmp).rglob('failure.json'))
            self.assertTrue(notes)
            self.assertIn('Detached worker may still be running', notes[0].read_text())
            self.assertIn('Detached worker may still be running', DETACHED_WORKER_NOTE)

    def test_ability_launch_uses_run_id_and_not_force_stop(self):
        shell = aa_start_shell('ab' * 4, 45, '@/bin/recipe-msl @/bin/model.msl 10 @/bin/run.log 2048 1024 128')
        self.assertNotIn('force-stop', shell)
        self.assertIn('--ps run_id abababab', shell)
        with self.assertRaises(SafeTransportError):
            aa_start_shell('abababab', 45, "echo 'x'")
        text = '[abababab] STREAM 1 stdout ' + b'WORKER_PID 9\n'.hex() + '\n[abababab] <<< exit=0'
        # The marker includes the run id; the line above has it only as a prefix of STREAM.
        text = 'I hilog [abababab] STREAM 1 stdout ' + b'WORKER_PID 9\n'.hex() + '\nI hilog [abababab] <<< exit=0'
        stdout, _stderr, code = decode_hilog_stream(text, 'abababab')
        self.assertEqual(stdout, 'WORKER_PID 9\n')
        self.assertEqual(code, '0')

    def test_dispatch_selects_one_task_and_keeps_the_original_five_first(self):
        self.assertEqual(select_tasks('schedule', ''), list(SCHEDULED))
        self.assertEqual(select_tasks('workflow_dispatch', 'all'), list(SCHEDULED))
        self.assertEqual(select_tasks('workflow_dispatch', ''), list(SCHEDULED))
        self.assertEqual(select_tasks('workflow_dispatch', 'qwen25-15b-msl-q30-kirin9020'),
                         ['qwen25-15b-msl-q30-kirin9020'])
        self.assertEqual(SCHEDULED[:5], ORIGINAL_FIVE)
        with self.assertRaises(ValueError):
            select_tasks('workflow_dispatch', 'not-a-task')

    def test_deploy_templates_match_the_public_policy_and_drop_old_paths(self):
        for name in ('qwen25-15b-msl-w4a16-kirin9020', 'qwen25-15b-msl-q30-kirin9020'):
            public = json.loads((ROOT / 'config/daily' / (name + '.json')).read_text())
            private = json.loads((ROOT / 'config/deploy' / (name + '.json')).read_text())
            self.assertEqual(private['model_generation'], public['model_generation'])
            self.assertEqual(private['device_transport'], public['device_transport'])
            self.assertNotIn('blocked', private)
            self.assertNotEqual(private['environment']['device']['port'], '18888')
            self.assertNotIn('binrunner_device_port', private)
            self.assertEqual(private['environment']['binrunner'], '/assets/binrunner')
            blob = json.dumps(private)
            for banned in HISTORICAL_HASHES + ('/home/', 'binrunner-1.4.1'):
                self.assertNotIn(banned, blob)
            self.assertEqual(private['environment']['device']['serial'], '127.0.0.1:2000')
            self.assertNotEqual(private['environment']['device']['serial'], '127.0.0.1:3000')


if __name__ == '__main__':
    unittest.main()
