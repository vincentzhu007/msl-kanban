"""Own a 19147-19159 fport and run upload, sandbox exec, and pull without br.

The session never calls python -m binrunner, ensure_forward, aa force-stop,
or kill. It removes only the forward tuple it created, and only while that
tuple still belongs to this serial. Removing the tuple does not mean a
detached worker has exited.
"""
from __future__ import annotations

import contextlib
import json
import random
import re
import subprocess
import time
from pathlib import Path

from .safe_br_io import (
    FORBIDDEN_HOST_PORTS,
    HOST_PORT_MAX,
    HOST_PORT_MIN,
    SafeStop,
    SafeTransportError,
    probe_connect,
    pull_file,
    push_file,
    validate_host_port,
)

DEVICE_PORT = 8888
SAFE_TASKS = frozenset({
    'qwen25-15b-msl-w4a16-kirin9020',
    'qwen25-15b-msl-q30-kirin9020',
})
WORKER_NAMES = frozenset({'recipe-msl', 'recipe-llama', 'edge-llama'})
BUNDLE = 'com.example.binrunner'
ABILITY = 'EntryAbility'
HILOG_TAG = 'BinRunner'
STREAM_RE = re.compile(r'STREAM (\d+) (stdout|stderr) ([0-9a-f]+)')
DETACHED_WORKER_NOTE = 'Detached worker may still be running; next run checks for it. Removing this task fport does not mean the worker exited.'


def requires_safe_norestart(config, recipe_id):
    mode = (config.get('device_transport') or {}).get('mode')
    identified = recipe_id in SAFE_TASKS or config.get('task_id') in SAFE_TASKS
    if identified:
        if config.get('task_id') not in (None, recipe_id):
            raise SafeTransportError('task_id does not match the 1.5B recipe')
        if mode != 'safe_norestart':
            raise SafeTransportError('Qwen2.5-1.5B Kirin9020 tasks cannot use br push')
        return True
    if mode:
        raise SafeTransportError('safe_norestart is only valid for the two Qwen2.5-1.5B Kirin9020 tasks')
    return False


def refuse_serial(serial):
    if not isinstance(serial, str) or not serial or any(c in serial for c in ' \t\r\n'):
        raise SafeTransportError('device serial is empty or unsafe')
    if serial in {'3000', '3001'} or serial.endswith((':3000', ':3001')):
        raise SafeTransportError('refusing TTS device 3000/3001')
    return serial


def conflicting_workers(ps_text):
    found = []
    for line in (ps_text or '').splitlines():
        fields = line.split()
        if not fields:
            continue
        name = fields[-1].strip('[]')
        if name in WORKER_NAMES:
            found.append(name)
    return found


def parse_forwards(text):
    """Parse `hdc -t SERIAL fport ls`. Unparsed text fails closed."""
    if text is None:
        raise SafeTransportError('missing fport listing')
    stripped = text.lstrip()
    if stripped.startswith('[Fail]'):
        raise SafeTransportError('hdc fport ls failed; not editing forwards')
    rows = []
    for line in text.splitlines():
        if not line.strip():
            continue
        fields = line.split()
        if (len(fields) not in (3, 4) or (len(fields) == 4 and fields[3] != '[Forward]') or
                not re.fullmatch(r'[A-Za-z0-9_.:-]+', fields[0]) or
                not fields[1].startswith('tcp:') or not fields[2].startswith('tcp:')):
            raise SafeTransportError('unparsed fport line; not editing forwards')
        local_port = fields[1][4:]
        remote_port = fields[2][4:]
        if (not local_port.isascii() or not local_port.isdigit() or
                not remote_port.isascii() or not remote_port.isdigit() or
                not 1 <= int(local_port) <= 65535 or not 1 <= int(remote_port) <= 65535):
            raise SafeTransportError('unparsed fport ports; not editing forwards')
        rows.append((fields[0], fields[1], fields[2]))
    return tuple(rows)


def choose_host_port(rows, listeners, preferred):
    """Pick one free host port in 19147-19159. Never reuse or delete a listed tuple."""
    if isinstance(listeners, (str, bytes)) or not isinstance(listeners, (set, frozenset, list, tuple)):
        raise SafeTransportError('host listener set is required')
    used = set()
    for _serial, local, _remote in rows:
        used.add(int(local[4:]))
    candidates = []
    if preferred is not None:
        preferred = validate_host_port(preferred)
        candidates.append(preferred)
    candidates.extend(port for port in range(HOST_PORT_MIN, HOST_PORT_MAX + 1) if port != preferred)
    for port in candidates:
        if port in FORBIDDEN_HOST_PORTS:
            continue
        if port in used or port in set(listeners):
            continue
        return port
    raise SafeTransportError('no free host port in 19147-19159')


def sandbox_basename(device_path):
    if not isinstance(device_path, str):
        raise SafeTransportError('device path must be @/name (HAP 1.5.x) or @/bin/name (HAP 1.4.x)')
    name = None
    for prefix in ('@/bin/', '@/'):
        if device_path.startswith(prefix):
            name = device_path[len(prefix):]
            break
    if name is None:
        raise SafeTransportError('device path must be @/name (HAP 1.5.x) or @/bin/name (HAP 1.4.x)')
    if not name or '/' in name or name in ('.', '..') or '\\' in name:
        raise SafeTransportError('unsafe sandbox name')
    return name


def hashes_from_output(stdout):
    return re.findall(r'(?m)^([a-f0-9]{64})\s+', stdout or '')


def aa_start_shell(run_id, timeout_sec, cmdline):
    if not re.fullmatch(r'[0-9a-f]{8}', run_id):
        raise SafeTransportError('run id must be 8 hex chars')
    if isinstance(timeout_sec, bool) or not isinstance(timeout_sec, int) or timeout_sec < 1 or timeout_sec > 7200:
        raise SafeTransportError('aa timeout must be an int from 1 to 7200')
    if not isinstance(cmdline, str) or not cmdline or "'" in cmdline or '\n' in cmdline or '\r' in cmdline:
        raise SafeTransportError('refusing shell metacharacters in the ability command')
    lowered = cmdline.lower()
    if 'force-stop' in lowered or 'force_stop' in lowered:
        raise SafeTransportError('refusing force-stop in the ability command')
    return (
        f'aa start -b {BUNDLE} -a {ABILITY} '
        f'--ps run_id {run_id} --ps stream 1 --ps timeout_sec {timeout_sec} '
        f"--ps cmd '{cmdline}'"
    )


def decode_hilog_stream(text, run_id):
    stdout_parts = []
    stderr_parts = []
    exit_code = None
    marker = f'[{run_id}] '
    for line in (text or '').splitlines():
        if marker not in line:
            continue
        body = line.split(marker, 1)[1]
        chunk = STREAM_RE.search(body)
        if chunk:
            try:
                payload = bytes.fromhex(chunk.group(3))
            except ValueError:
                continue
            (stdout_parts if chunk.group(2) == 'stdout' else stderr_parts).append(payload)
        matched = re.search(r'<<< exit=(-?\d+)', body)
        if matched:
            exit_code = matched.group(1)
    stdout = b''.join(stdout_parts).decode('utf-8', 'replace')
    stderr = b''.join(stderr_parts).decode('utf-8', 'replace')
    return stdout, stderr, exit_code


def _command_text(args):
    return ' '.join(args).lower()


class SafeSession:
    """One task's fport. `closed` is the tuple, not the worker."""

    def __init__(self, serial, port, hdc, task_dir):
        self.serial = refuse_serial(serial)
        self.port = validate_host_port(port)
        self._hdc = hdc
        self.task_dir = None if task_dir is None else Path(task_dir)
        self.created = False
        self._create_sent = False
        self.closed = False
        self._closing = False
        self.worker_observed_exited = False
        self.calls = []

    def hdc(self, args, timeout=20):
        if not isinstance(args, (list, tuple)) or not all(isinstance(part, str) for part in args):
            raise SafeTransportError('hdc argv must be strings')
        flat = _command_text(args)
        if 'force-stop' in flat or 'force_stop' in flat or 'kill' in args:
            raise SafeTransportError('refusing kill or force-stop')
        if args[:1] == ['fport'] and 'rm' in args:
            expected = ['fport', 'rm', f'tcp:{self.port}', f'tcp:{DEVICE_PORT}']
            if list(args) != expected or not self._closing:
                raise SafeTransportError('refusing to remove a forward this session does not own')
        if args[:1] == ['fport'] and 'rm' not in args and 'ls' not in args:
            expected = ['fport', f'tcp:{self.port}', f'tcp:{DEVICE_PORT}']
            if list(args) != expected:
                raise SafeTransportError('refusing to create any forward except this session tuple')
        self.calls.append(list(args))
        completed = self._hdc(self.serial, list(args), timeout)
        text = (getattr(completed, 'stdout', '') or '') + (getattr(completed, 'stderr', '') or '')
        if text.lstrip().startswith('[Fail]'):
            raise SafeTransportError('hdc command failed; not restarting the app')
        return completed

    def _listing(self):
        completed = self.hdc(['fport', 'ls'], timeout=15)
        return parse_forwards((completed.stdout or '') + (completed.stderr or ''))

    def create(self, before):
        if self.created:
            raise SafeTransportError('session already created a forward')
        again = self._listing()
        if again != tuple(before):
            raise SafeTransportError('fport list changed before create; not replacing it')
        ours = (self.serial, f'tcp:{self.port}', f'tcp:{DEVICE_PORT}')
        if any(row[1] == ours[1] for row in again):
            raise SafeTransportError('host port appeared before create; not reusing it')
        self._closing = False
        self.hdc(['fport', f'tcp:{self.port}', f'tcp:{DEVICE_PORT}'], timeout=15)
        # The command was accepted. Close must look again even if this listing misses the row.
        self._create_sent = True
        after = self._listing()
        if ours not in after:
            raise SafeTransportError('own fport did not appear')
        missing = [row for row in before if row not in after]
        if missing:
            self._remove_if_exact(ours)
            raise SafeTransportError('an existing forward disappeared while creating ours')
        self.created = True
        self._write_note('created')
        return ours

    def _remove_if_exact(self, ours):
        if (ours != (self.serial, f'tcp:{self.port}', f'tcp:{DEVICE_PORT}') or
                not (self.created or self._create_sent)):
            raise SafeTransportError('refusing to remove a tuple not created by this session')
        current = self._listing()
        if ours not in current:
            return False
        others = [row for row in current if row != ours]
        if any(row[1] == ours[1] for row in others):
            raise SafeTransportError('host port has another owner; not removing any forward')
        self._closing = True
        try:
            self.hdc(['fport', 'rm', f'tcp:{self.port}', f'tcp:{DEVICE_PORT}'], timeout=15)
        finally:
            self._closing = False
        after = self._listing()
        if ours in after:
            raise SafeTransportError('own fport was still listed after rm')
        missing = [row for row in others if row not in after]
        if missing:
            raise SafeTransportError('another forward disappeared while removing ours')
        return True

    def close(self):
        """Drop only our tuple. This does not observe or stop a device worker.

        A create command that was already sent is checked again here. The row
        is removed only when a fresh listing still shows this serial and the
        same tcp:<port> tcp:8888 tuple. A failed listing removes nothing.
        """
        if self.closed:
            return
        self.closed = True
        self.worker_observed_exited = False
        if not self.created and not self._create_sent:
            self._write_note('not-created')
            return
        ours = (self.serial, f'tcp:{self.port}', f'tcp:{DEVICE_PORT}')
        try:
            current = self._listing()
        except SafeTransportError:
            self._write_note('listing-failed-not-removed')
            return
        if ours not in current:
            self._write_note('own-tuple-not-listed')
            return
        try:
            removed = self._remove_if_exact(ours)
        except SafeTransportError:
            self._write_note('listing-failed-not-removed')
            return
        # removed-own-fport means an rm was sent and the following list no longer has this tuple.
        self._write_note('removed-own-fport' if removed else 'own-tuple-not-listed')

    def _write_note(self, state):
        if self.task_dir is None:
            return
        self.task_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            'mode': 'safe_norestart',
            'host_port': self.port,
            'device_port': DEVICE_PORT,
            'state': state,
            'worker_observed_exited': False,
            'note': DETACHED_WORKER_NOTE,
        }
        path = self.task_dir / 'safe-transport.json'
        path.write_text(json.dumps(payload, indent=2) + '\n')

    def probe(self):
        """TCP reachability only. The return value has no device identity."""
        result = probe_connect(self.port)
        if set(result) - {'reachable', 'host', 'port'}:
            raise SafeTransportError('probe returned more than reachability')
        return result

    def push_host(self, local_path, log_path):
        local_path = Path(local_path)
        remote = local_path.name
        started = time.monotonic()
        try:
            result = push_file(self.port, str(local_path), remote)
        except (SafeStop, SafeTransportError) as error:
            self._log_push(log_path, remote, local_path, error=error, started=started)
            raise
        self._log_push(log_path, remote, local_path, result=result, started=started)
        return result

    def _log_push(self, log_path, remote, local_path, result=None, error=None, started=0):
        record = {
            'mode': 'safe_norestart',
            'op': 'push',
            'host_port': self.port,
            'device_port': DEVICE_PORT,
            'remote': remote,
            'bytes': local_path.stat().st_size if local_path.exists() else None,
            'seconds': round(time.monotonic() - started, 3),
            'br_cli': False,
            'force_stop': False,
        }
        if result is not None:
            record['sha256'] = result['sha256']
        if error is not None:
            record['error_type'] = type(error).__name__
            record['safe_stop'] = isinstance(error, SafeStop)
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('a') as handle:
            handle.write(json.dumps(record) + '\n')

    def invoke(self, args, timeout):
        """Serve run/pull for the official executor. `timeout` bounds this call only."""
        if self.closed:
            raise SafeTransportError('session fport is already closed')
        if not args or args[0] not in {'run', 'pull'}:
            raise SafeTransportError('safe session only runs or pulls')
        if args[0] == 'pull':
            if len(args) != 3:
                raise SafeTransportError('pull expects the remote name and a local path')
            try:
                result = pull_file(self.port, args[1], args[2], transfer_timeout=timeout)
            except TimeoutError as error:
                raise subprocess.TimeoutExpired(args, timeout) from error
            except SafeStop as error:
                # The worker can still be running. Keep the fport and let the sampler continue.
                return subprocess.CompletedProcess(args, 2, '', str(error))
            except SafeTransportError as error:
                return subprocess.CompletedProcess(args, 1, '', str(error))
            completed = subprocess.CompletedProcess(args, 0, '', '')
            completed.identity = False if not result['identity'] else True
            completed.pulled_bytes = result['bytes']
            return completed
        command = args[1]
        return self.run_ability(command, timeout)

    def run_ability(self, cmdline, timeout):
        timeout_sec = max(1, min(7200, int(timeout)))
        run_id = ''.join(random.choice('0123456789abcdef') for _ in range(8))
        shell = aa_start_shell(run_id, timeout_sec, cmdline)
        start = self.hdc(['shell', shell], timeout=30)
        (self._capture(start, f'aa-start-{run_id}.txt'))
        deadline = time.monotonic() + timeout
        chunks = []
        stdout, stderr, exit_code = '', '', None
        time.sleep(0.05)
        while time.monotonic() < deadline:
            try:
                dump = self.hdc(['shell', f"hilog -x -T {HILOG_TAG} -e '\\[{run_id}\\]'"], timeout=8)
            except SafeTransportError as error:
                chunks.append(f'hilog-read-failed {type(error).__name__}')
                time.sleep(0.05)
                continue
            text = (dump.stdout or '') + (dump.stderr or '')
            if text:
                chunks.append(text)
            stdout, stderr, exit_code = decode_hilog_stream('\n'.join(chunks), run_id)
            joined = '\n'.join(chunks)
            if f'[{run_id}]' in joined and ('<<< END' in joined or '<<< exit=' in joined or 'streamChunks=' in joined):
                break
            time.sleep(0.05)
        self._capture_text('\n'.join(chunks), f'hilog-{run_id}.txt')
        output = stdout if stdout else stderr
        returncode = 0 if 'WORKER_PID' in output or exit_code == '0' else 1
        completed = subprocess.CompletedProcess(['aa', 'start', run_id], returncode, output, stderr)
        completed.run_id = run_id
        completed.exit_code = exit_code
        return completed

    def _capture(self, completed, name):
        text = f"rc={completed.returncode}\n{(completed.stdout or '')}\n{(completed.stderr or '')}\n"
        self._capture_text(text, name)

    def _capture_text(self, text, name):
        if self.task_dir is None:
            return
        directory = self.task_dir / 'safe-io'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / name).write_text(text)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False


_PROC_TCP = ('/proc/net/tcp', '/proc/net/tcp6')
_PROC_TCP_HEADER = ('sl', 'local_address', 'rem_address', 'st')
_TCP_LISTEN = '0A'
# /proc/net/tcp address is 8 hex digits; tcp6 is 32. Port is 4 hex digits, state is 2.
_IPV4_ADDR_HEX = 8
_IPV6_ADDR_HEX = 32
_PORT_HEX = 4
_STATE_HEX = 2
_PORT_MAX = 65535


def parse_proc_net_tcp(text, *, ipv6):
    """Return listening ports from one /proc/net/tcp or tcp6 table.

    A missing header, a short record, or a non-hex field fails closed.
    Established and other states are ignored. An empty table is valid.
    """
    if not isinstance(text, str) or not text.strip():
        raise SafeTransportError('proc net tcp is empty; not creating a forward')
    lines = text.splitlines()
    header = lines[0].split()
    # tcp uses rem_address; tcp6 uses remote_address. Both are the kernel's own labels.
    if (len(header) < 4 or tuple(header[:2]) != _PROC_TCP_HEADER[:2]
            or header[2] not in ('rem_address', 'remote_address') or header[3] != _PROC_TCP_HEADER[3]):
        raise SafeTransportError('proc net tcp header is not recognized; not creating a forward')
    address_length = _IPV6_ADDR_HEX if ipv6 else _IPV4_ADDR_HEX
    ports = set()
    for line in lines[1:]:
        if not line.strip():
            raise SafeTransportError('proc net tcp has a blank record; not creating a forward')
        fields = line.split()
        if len(fields) < 4 or not fields[0].endswith(':'):
            raise SafeTransportError('proc net tcp record is truncated; not creating a forward')
        local, state = fields[1], fields[3]
        if local.count(':') != 1:
            raise SafeTransportError('proc net tcp local address is malformed; not creating a forward')
        address, port_hex = local.split(':')
        if len(address) != address_length or len(port_hex) != _PORT_HEX or len(state) != _STATE_HEX:
            raise SafeTransportError('proc net tcp field width is unexpected; not creating a forward')
        try:
            int(address, 16)
            port = int(port_hex, 16)
            int(state, 16)
        except ValueError as error:
            raise SafeTransportError('proc net tcp field is not hex; not creating a forward') from error
        if port > _PORT_MAX:
            raise SafeTransportError('proc net tcp port is out of range; not creating a forward')
        if state.upper() == _TCP_LISTEN:
            ports.add(port)
    return ports


def listening_tcp_ports(paths=None):
    """Read listening TCP ports from procfs. This does not invoke ss.

    The official runner image has no ss. Both IPv4 and IPv6 tables are
    required. A missing, unreadable, or corrupt table refuses the forward.
    """
    selected = _PROC_TCP if paths is None else tuple(paths)
    if len(selected) != 2:
        raise SafeTransportError('listener check needs both tcp and tcp6 tables')
    ports = set()
    for index, path in enumerate(selected):
        try:
            text = Path(path).read_text(encoding='ascii')
        except (OSError, UnicodeError) as error:
            raise SafeTransportError('cannot list host listeners; not creating a forward') from error
        ports.update(parse_proc_net_tcp(text, ipv6=index == 1))
    return ports


def default_hdc(serial, args, timeout):
    refuse_serial(serial)
    return subprocess.run(
        ['hdc', '-t', serial, *args], capture_output=True, text=True, timeout=timeout, check=False)


@contextlib.contextmanager
def open_safe_session(env, config, task_dir, port, *, hdc=None):
    """Create exactly `port`, yield the session, then remove only that tuple.

    A port race or a failed probe removes nothing that this session did not
    create, and never removes 19005 or another serial's forwards.
    """
    serial = refuse_serial(env['device']['serial'])
    if config['device_transport'].get('device_port') != DEVICE_PORT:
        raise SafeTransportError('safe_norestart only forwards to device port 8888')
    port = validate_host_port(int(port))
    session = SafeSession(serial, port, hdc or default_hdc, task_dir)
    try:
        before = session._listing()
        session.create(before)
        yield session
    finally:
        session.close()


def read_fport_listing(serial, hdc=None):
    """Read one device's forwards. The command is targeted, so device 3000 is not queried."""
    serial = refuse_serial(serial)
    completed = (hdc or default_hdc)(serial, ['fport', 'ls'], 15)
    text = (completed.stdout or '') + (completed.stderr or '')
    if text.lstrip().startswith('[Fail]') or completed.returncode not in (0, None):
        raise SafeTransportError('hdc fport ls failed; not editing forwards')
    parse_forwards(text)
    return text


def plan_host_port(env, config, *, listing_text, listeners):
    """Read-only choice used before the dedup key. Does not create a forward."""
    serial = refuse_serial(env['device']['serial'])
    transport = config['device_transport']
    if transport.get('device_port') != DEVICE_PORT:
        raise SafeTransportError('safe_norestart only forwards to device port 8888')
    preferred = transport.get('preferred_host_port')
    rows = parse_forwards(listing_text)
    port = choose_host_port(rows, listeners, None if preferred is None else int(preferred))
    return {'serial': serial, 'host_port': port, 'device_port': DEVICE_PORT, 'rows': rows,
            'editable_rows': tuple(row for row in rows if row[0] == serial)}
