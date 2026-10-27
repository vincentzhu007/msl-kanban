"""Offline OAuth protocol and HTTP access-control tests; no GitCode credentials."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from urllib.parse import parse_qs, urlsplit, urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'dashboard'))
from gitcode_auth import Config, GitCodeAuth, AuthenticationError, SESSION_COOKIE, FLOW_COOKIE
from server import create_server


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.allowlist = self.root / 'allowlist.json'
        self.allowlist.write_text('{"user_ids":["user-123"]}')
        self.config = Config('https://dashboard.example', 'test-client', 'secret-value', self.allowlist)
        self.now = 100
        self.requests = []
        self.user = {'id': 'user-123', 'login': 'alice'}
        def fetch(request):
            self.requests.append(request)
            return {'access_token': 'provider-token'} if len(self.requests) % 2 else self.user
        self.auth = GitCodeAuth(self.config, fetch=fetch, clock=lambda: self.now)

    def flow(self):
        url, cookie = self.auth.begin()
        state = parse_qs(urlsplit(url).query)['state'][0]
        return state, cookie.split(';')[0]

    def login(self):
        state, cookie = self.flow()
        sid = self.auth.complete('test-code', state, cookie)
        return f'{SESSION_COOKIE}={sid}'

    def test_secret_transport_and_session(self):
        cookie = self.login()
        token_request, user_request = self.requests
        self.assertNotIn('secret-value', token_request.full_url)
        self.assertIn(b'secret-value', token_request.data)
        self.assertTrue(token_request.get_header('Content-type').startswith('multipart/form-data;'))
        self.assertEqual(user_request.get_header('Authorization'), 'Bearer provider-token')
        self.assertEqual(self.auth.current(cookie)['id'], 'user-123')
        self.assertNotIn('provider-token', repr(self.auth.sessions))
        self.assertNotIn('secret-value', repr(self.config))

    def test_state_binding_expiry_and_replay(self):
        state, cookie = self.flow()
        with self.assertRaises(AuthenticationError):
            self.auth.complete('code', state, FLOW_COOKIE + '=other-browser')
        self.assertEqual(self.requests, [])
        state, cookie = self.flow()
        self.now += 601
        with self.assertRaises(AuthenticationError):
            self.auth.complete('code', state, cookie)
        state, cookie = self.flow()
        self.auth.complete('code', state, cookie)
        with self.assertRaises(AuthenticationError):
            self.auth.complete('code', state, cookie)

    def test_whitelist_id_not_login_and_revocation(self):
        self.user = {'id': 'intruder', 'login': 'user-123'}
        with self.assertRaises(AuthenticationError):
            self.login()
        self.user = {'id': 'user-123', 'login': 'renamed'}
        cookie = self.login()
        self.assertEqual(self.auth.current(cookie)['login'], 'renamed')
        self.allowlist.write_text('{"user_ids":[]}')
        self.assertIsNone(self.auth.current(cookie))

    def test_session_expiry_and_logout(self):
        cookie = self.login()
        with self.assertRaises(AuthenticationError):
            self.auth.logout(cookie, 'incorrect')
        self.auth.logout(cookie, self.auth.current(cookie)['csrf'])
        self.assertIsNone(self.auth.current(cookie))
        cookie = self.login()
        self.now += self.auth.SESSION_TTL
        self.assertIsNone(self.auth.current(cookie))

    def test_bad_configuration_fails_closed(self):
        with self.assertRaises(ValueError):
            Config('http://dashboard.example', 'client', 'secret', self.allowlist)
        with self.assertRaises(ValueError):
            create_server('0.0.0.0', 0, self.root, auth=None)
        cookie = self.login()
        self.allowlist.write_text('invalid json')
        self.assertIsNone(self.auth.current(cookie))

    def test_http_access_callback_and_logout(self):
        (self.root / 'result.json').write_text('{"spec":{},"samples":[]}')
        service = create_server('127.0.0.1', 0, self.root, auth=self.auth)
        thread = threading.Thread(target=service.serve_forever)
        thread.start()
        self.addCleanup(service.server_close)
        self.addCleanup(thread.join)
        self.addCleanup(service.shutdown)

        def request(method, path, headers=None, body=None):
            connection = http.client.HTTPConnection('127.0.0.1', service.server_port, timeout=5)
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            status, reply_headers, payload = response.status, response.getheaders(), response.read()
            connection.close()
            return status, dict(reply_headers), payload, reply_headers

        for method in ['GET', 'HEAD']:
            self.assertEqual(request(method, '/api/runs')[0], 401)
            for path in ['/', '/index.html', '/app.js', '/style.css', '/%69ndex.html']:
                self.assertEqual(request(method, path)[0], 302)
        self.assertEqual(request('GET', '/health')[0], 200)
        state, flow_cookie = self.flow()
        status, headers, _, raw = request('GET', '/auth/callback?' + urlencode({'code': 'code', 'state': state}), {'Cookie': flow_cookie})
        self.assertEqual(status, 302)
        self.assertEqual(headers['Location'], '/')
        session_cookie = next(v for k, v in raw if k == 'Set-Cookie' and v.startswith(SESSION_COOKIE + '='))
        self.assertIn('Secure; HttpOnly; SameSite=Lax', session_cookie)
        cookie = session_cookie.split(';')[0]
        self.assertEqual(request('GET', '/api/runs', {'Cookie': cookie})[0], 200)
        self.assertEqual(request('GET', '/app.js', {'Cookie': cookie})[0], 200)
        self.assertEqual(request('GET', '/../server.py', {'Cookie': cookie})[0], 404)
        self.assertEqual(request('POST', '/auth/logout', {'Cookie': cookie}, 'csrf=wrong')[0], 403)
        csrf = self.auth.current(cookie)['csrf']
        self.assertEqual(request('POST', '/auth/logout', {'Cookie': cookie, 'Origin': self.config.origin}, urlencode({'csrf': csrf}))[0], 302)
        self.assertEqual(request('GET', '/api/runs', {'Cookie': cookie})[0], 401)
