"""Exercise the HTTP handler over a socket pair, with device I/O replaced."""
import json
from pathlib import Path
import runpy
import socket
import struct
import sys
import threading
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts/playground'))
gateway = runpy.run_path(str(ROOT / 'scripts/playground/mslite-serve'))


class PlaygroundTests(unittest.TestCase):
    def setUp(self):
        self.server = SimpleNamespace(authorization=None, slot=threading.Lock(), screen=None,
            settings=SimpleNamespace(phone_type='mate80-pro', model_id='qwen', model_path='@/bin/model.msl', context=2048,
                                     device='phone', port='18940', binrunner='/dog'))

    def call(self, path, body=None, key=None, phone=None):
        client, server_end = socket.socketpair()
        with client, server_end:
            data = b'' if body is None else json.dumps(body).encode()
            verb = 'GET' if body is None else 'POST'
            authorization = f'Authorization: Bearer {key}\r\n' if key else ''
            phone_header = f'X-Phone-Type: {phone}\r\n' if phone else ''
            client.sendall((f'{verb} {path} HTTP/1.0\r\n{authorization}{phone_header}'
                            f'Content-Length: {len(data)}\r\n\r\n').encode() + data)
            gateway['Handler'](server_end, ('local', 1), self.server, data_dir=ROOT / 'kanban/data')
            server_end.shutdown(socket.SHUT_WR)
            with client.makefile('rb') as stream:
                head, payload = stream.read().split(b'\r\n\r\n', 1)
            return int(head.split()[1]), json.loads(payload)

    def test_auth_and_registered_model(self):
        self.assertEqual(self.call('/v1/models')[1]['data'][0]['id'], 'qwen')

    def test_phone_selection(self):
        self.assertEqual(self.call('/v1/models', phone='mate80-pro')[0], 200)
        self.assertEqual(self.call('/v1/models', phone='mate70-pro')[0], 503)
        self.server.settings.phone_type = 'mate70-pro'
        self.assertEqual(self.call('/v1/models', phone='mate70-pro')[0], 200)

    def test_explicit_gateway_key(self):
        self.server.authorization = b'Bearer test'
        self.assertEqual(self.call('/v1/models')[0], 401)
        self.assertEqual(self.call('/v1/models', key='test')[0], 200)

    def test_chat_roundtrip(self):
        body = {'messages': [{'role': 'user', 'content': '你好'}], 'model': 'qwen'}
        result = SimpleNamespace(returncode=0, stdout=b'exit=0 timedOut=false\nMSL_REPLY stop e5a5bd\n')
        with patch('subprocess.run', return_value=result) as run:
            status, data = self.call('/v1/chat/completions', body)
            self.assertEqual(status, 200)
            command = run.call_args.args[0]
            self.assertIn('你好'.encode().hex(), command[command.index('run')+1])
            self.assertEqual(data['choices'][0]['message']['content'], '好')
            self.assertEqual(self.call('/v1/chat/completions', dict(body, stream='yes'))[0], 400)
            self.server.slot.acquire()
            self.assertEqual(self.call('/v1/chat/completions', body)[0], 429)

    def test_output_limit_and_context_budget(self):
        prepare = gateway['prepare']
        body = {'model': 'qwen', 'messages': [{'role': 'user', 'content': 'hi'}]}
        self.assertIn('1024', prepare(self.server.settings, body)[-3])
        self.assertIn('1024', prepare(self.server.settings, dict(body, max_tokens=1024))[-3])
        with self.assertRaises(gateway['Problem']):
            prepare(self.server.settings, dict(body, max_tokens=1025))
        with self.assertRaises(gateway['Problem']):
            prepare(self.server.settings, dict(body, messages=[{'role':'user', 'content':'a' * 2100}]))

    def test_shared_device_lease_rejects_simultaneous_daily_job(self):
        with tempfile.TemporaryDirectory() as root:
            with gateway['device_lease'](root, 'phone'):
                with self.assertRaises(gateway['Problem']) as error:
                    with gateway['device_lease'](root, 'phone'):
                        pass
                self.assertEqual(error.exception.code, 429)
            with gateway['device_lease'](root, 'phone'):
                pass

    def test_token_budget_counts_tokens_and_adapts_output(self):
        class Tokenizer:
            def encode(self, text, add_special_tokens=False):
                return SimpleNamespace(ids=[1] * 1200)
        self.server.settings.tokenizer = Tokenizer()
        body = {'model':'qwen', 'messages':[{'role':'user', 'content':'长文本' * 600}], 'max_tokens':1024}
        command = gateway['prepare'](self.server.settings, body)
        self.assertIn(' 848 ', command[-3])
        self.server.settings.tokenizer = SimpleNamespace(encode=lambda *a, **k: SimpleNamespace(ids=[1] * 2048))
        with self.assertRaises(gateway['Problem']):
            gateway['prepare'](self.server.settings, body)

    def test_device_sessions(self):
        screen = gateway['Screen']('phone', 'example.app', 'EntryAbility')
        def device(*args):
            if args[:2] == ('file', 'recv'):
                Path(args[-1]).write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(8) + struct.pack('>II', 1080, 1920))
        with patch.object(screen, 'run', side_effect=device) as run:
            session = screen.request('start', {}, None)['session']
            with self.assertRaises(gateway['ScreenError']):
                screen.request('start', {}, None)
            with self.assertRaises(gateway['ScreenError']):
                screen.request('frame', {}, 'wrong')
            self.assertIn('png', screen.request('frame', {}, session))
            screen.request('input', {'gesture':'click', 'points':[100, 200]}, session)
            run.assert_called_with('shell', 'uitest', 'uiInput', 'click', '100', '200')
            screen.request('end', {}, session)
            with self.assertRaises(gateway['ScreenError']):
                screen.request('frame', {}, session)
