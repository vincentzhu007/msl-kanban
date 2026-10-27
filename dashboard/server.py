"""Read-only dashboard protected by GitCode OAuth and a stable user-ID allowlist."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from html import escape
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from gitcode_auth import (Config, GitCodeAuth, AuthenticationError, SESSION_COOKIE,
                          FLOW_COOKIE, cookie)

BASE = Path(__file__).resolve().parent
LOGGER = logging.getLogger(__name__)


def load_runs(directory):
    runs = []
    for path in sorted(directory.glob('*.json')):
        try:
            data = json.loads(path.read_text())
            if not isinstance(data, dict) or not isinstance(data.get('spec'), dict) or not isinstance(data.get('samples'), list):
                raise ValueError('Expected object with spec object and samples list')
            runs.append(data)
        except (ValueError, OSError) as error:
            LOGGER.warning('Skipping invalid result %s: %s', path.name, type(error).__name__)
    return runs


def page(title, content):
    return ('<!doctype html><html lang="zh-CN"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{escape(title)}</title><body><main><h1>{escape(title)}</h1>'
            f'{content}</main></body></html>').encode()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, data_dir, auth, **kwargs):
        self.data_dir = data_dir
        self.auth = auth
        super().__init__(*args, directory=str(BASE / 'static'), **kwargs)

    def log_request(self, code='-', size='-'):
        # OAuth authorization codes are query parameters; never log request URLs.
        LOGGER.info('%s %s %s', self.command, urlsplit(self.path).path, code)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        super().end_headers()

    def send_payload(self, payload, content_type='text/html; charset=utf-8', status=200, cookies=()):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(payload)))
        for value in cookies:
            self.send_header('Set-Cookie', value)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(payload)

    def redirect(self, location, cookies=()):
        self.send_response(302)
        self.send_header('Location', location)
        self.send_header('Content-Length', '0')
        for value in cookies:
            self.send_header('Set-Cookie', value)
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        header = self.headers.get('Cookie', '')
        if path == '/health':
            self.send_payload(b'ok', 'text/plain; charset=utf-8')
            return
        if self.auth and path == '/login':
            self.send_payload(page('登录性能看板', '<p>使用 GitCode 账号登录，仅白名单用户可访问。</p>'
                                   '<p><a href="/auth/login">使用 GitCode 登录</a></p>'))
            return
        if self.auth and path in ('/auth/login', '/auth/callback'):
            if self.command != 'GET':
                self.send_payload(b'', status=405)
                return
            try:
                if path == '/auth/login':
                    location, flow_cookie = self.auth.begin()
                    self.redirect(location, (flow_cookie,))
                else:
                    query = parse_qs(parsed.query, max_num_fields=10)
                    if (len(query.get('state', [])) != 1 or len(query.get('code', [])) != 1 or 'error' in query):
                        raise AuthenticationError('授权未完成，请重新登录。')
                    sid = self.auth.complete(query['code'][0], query['state'][0], header)
                    # Invalidate any prior session cookie in this browser by logging it out.
                    old = self.auth.current(header)
                    if old:
                        self.auth.logout(header, old['csrf'])
                    self.redirect('/', (cookie(SESSION_COOKIE, sid, self.auth.SESSION_TTL), cookie(FLOW_COOKIE, '', 0)))
            except (AuthenticationError, ValueError) as error:
                message = str(error) if isinstance(error, AuthenticationError) else '授权参数无效。'
                self.send_payload(page('无法登录', f'<p>{escape(message)}</p><a href="/login">返回登录</a>'),
                                  status=403, cookies=(cookie(FLOW_COOKIE, '', 0),))
            return
        session = self.auth.current(header) if self.auth else None
        if self.auth and not session:
            if path.startswith('/api/') or path == '/auth/me':
                self.send_payload(b'{"error":"authentication_required"}', 'application/json', 401)
            else:
                self.redirect('/login')
            return
        if path == '/auth/me':
            user = {'id': session['id'], 'login': session['login']} if session else {'mode': 'local-development'}
            self.send_payload(json.dumps(user).encode(), 'application/json')
        elif path == '/auth/account' and session:
            self.send_payload(page('登录账号', f'<p>{escape(session["login"])} · {escape(session["id"])}</p>'
                                   '<form method="post" action="/auth/logout">'
                                   f'<input type="hidden" name="csrf" value="{escape(session["csrf"], quote=True)}">'
                                   '<button type="submit">退出登录</button></form><p><a href="/">返回看板</a></p>'))
        elif path == '/api/runs':
            self.send_payload(json.dumps(load_runs(self.data_dir), ensure_ascii=False).encode(), 'application/json; charset=utf-8')
        elif path in ('/', '/index.html', '/app.js', '/style.css'):
            if self.command == 'HEAD':
                super().do_HEAD()
            else:
                super().do_GET()
        else:
            self.send_payload(page('未找到', '<p>页面不存在。</p>'), status=404)

    def do_POST(self):
        if urlsplit(self.path).path != '/auth/logout' or not self.auth:
            self.send_payload(b'', status=404)
            return
        try:
            if self.headers.get('Origin') != self.auth.config.origin:
                raise AuthenticationError('退出请求来源无效。')
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096 or self.headers.get('Transfer-Encoding'):
                raise AuthenticationError('退出请求无效。')
            body = parse_qs(self.rfile.read(length).decode(), max_num_fields=5)
            if len(body.get('csrf', [])) != 1:
                raise AuthenticationError('退出请求无效。')
            self.auth.logout(self.headers.get('Cookie', ''), body['csrf'][0])
            self.redirect('/login', (cookie(SESSION_COOKIE, '', 0),))
        except (AuthenticationError, ValueError, UnicodeError):
            self.send_payload(page('请求无效', '<p>请重新打开账号页面后退出。</p>'), status=403)


def create_server(host, port, data_dir, *, auth):
    if auth is None and host not in ('127.0.0.1', '::1', 'localhost'):
        raise ValueError('Unauthenticated development server must bind to loopback')
    return ThreadingHTTPServer((host, port), partial(Handler, data_dir=Path(data_dir), auth=auth))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8080)
    parser.add_argument('--data-dir', type=Path, default=Path(os.environ.get('DATA_DIR', BASE / 'data')))
    parser.add_argument('--dev-no-auth', action='store_true', help='Explicit local-only development; requires --host 127.0.0.1')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    try:
        auth = None if args.dev_no_auth else GitCodeAuth(Config.from_env())
        server = create_server(args.host, args.port, args.data_dir, auth=auth)
    except (KeyError, OSError, ValueError):
        parser.exit(2, 'Invalid or missing OAuth configuration. See docs/GITCODE_AUTH.md; refusing to serve data.\n')
    with server:
        server.serve_forever()


if __name__ == '__main__':
    main()
