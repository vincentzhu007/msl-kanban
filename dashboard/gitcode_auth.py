"""GitCode authorization-code login; opaque, server-side sessions and ID allowlist."""
from dataclasses import dataclass, field
import hashlib
from http.cookies import SimpleCookie, CookieError
import json
import os
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

AUTHORIZE_URL = 'https://gitcode.com/oauth/authorize'
TOKEN_URL = 'https://gitcode.com/oauth/token'
USER_URL = 'https://api.gitcode.com/api/v5/user'
SESSION_COOKIE = '__Host-msllm_session'
FLOW_COOKIE = '__Host-msllm_oauth'


class AuthenticationError(Exception):
    """Safe error text only: never include upstream responses or token URLs."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch_json(request):
    # Do not forward credentials through an unexpected upstream redirect.
    try:
        with build_opener(NoRedirect).open(request, timeout=15) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError('Response too large')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError('Expected object')
        return result
    except Exception:
        raise AuthenticationError('GitCode 授权服务暂不可用，请重新登录。') from None


@dataclass(frozen=True)
class Config:
    public_url: str
    client_id: str
    client_secret: str = field(repr=False)
    allowlist_file: Path
    scope: str = ''

    def __post_init__(self):
        parsed = urlsplit(self.public_url)
        if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or parsed.path not in ('', '/')):
            raise ValueError('DASHBOARD_PUBLIC_URL must be an HTTPS origin without path/query/credentials')
        if not self.client_id or not self.client_secret:
            raise ValueError('GitCode client ID and secret are required')
        read_allowlist(self.allowlist_file)

    @property
    def origin(self):
        return self.public_url.rstrip('/')

    @property
    def callback(self):
        return self.origin + '/auth/callback'

    @classmethod
    def from_env(cls):
        secret_file = Path(os.environ.get('GITCODE_CLIENT_SECRET_FILE', '/run/auth/client_secret'))
        return cls(os.environ['DASHBOARD_PUBLIC_URL'], os.environ['GITCODE_CLIENT_ID'],
                   secret_file.read_text().strip(),
                   Path(os.environ.get('GITCODE_ALLOWLIST_FILE', '/run/auth/allowlist.json')),
                   os.environ.get('GITCODE_SCOPE', ''))


def read_allowlist(path):
    data = json.loads(Path(path).read_text())
    if not isinstance(data, dict) or set(data) != {'user_ids'} or not isinstance(data['user_ids'], list):
        raise ValueError('Allowlist must contain a user_ids array')
    if any(not isinstance(value, str) or not value or len(value) > 128 for value in data['user_ids']):
        raise ValueError('Allowlist entries must be non-empty GitCode user ID strings')
    return set(data['user_ids'])


def cookie_value(header, name):
    try:
        cookie = SimpleCookie()
        cookie.load(header or '')
        return cookie[name].value if name in cookie else ''
    except CookieError:
        return ''


def cookie(name, value, max_age):
    return f'{name}={value}; Path=/; Max-Age={max_age}; Secure; HttpOnly; SameSite=Lax'


class GitCodeAuth:
    FLOW_TTL = 600
    SESSION_TTL = 8 * 60 * 60
    MAX_ENTRIES = 4096

    def __init__(self, config, *, fetch=fetch_json, clock=time.monotonic):
        self.config = config
        self.fetch = fetch
        self.clock = clock
        self.pending = {}
        self.sessions = {}
        self.lock = threading.Lock()

    def allowed(self, user_id):
        try:
            return user_id in read_allowlist(self.config.allowlist_file)
        except (OSError, ValueError):
            return False

    def purge(self):
        now = self.clock()
        for entries in (self.pending, self.sessions):
            for key in list(entries):
                if entries[key]['expires'] <= now:
                    del entries[key]

    def begin(self):
        state = secrets.token_urlsafe(32)
        browser = secrets.token_urlsafe(32)
        with self.lock:
            self.purge()
            if len(self.pending) >= self.MAX_ENTRIES:
                raise AuthenticationError('登录请求较多，请稍后重试。')
            self.pending[state] = {'browser': hashlib.sha256(browser.encode()).hexdigest(),
                                   'expires': self.clock() + self.FLOW_TTL}
        query = {'client_id': self.config.client_id, 'redirect_uri': self.config.callback,
                 'response_type': 'code', 'state': state}
        if self.config.scope:
            query['scope'] = self.config.scope
        return AUTHORIZE_URL + '?' + urlencode(query), cookie(FLOW_COOKIE, browser, self.FLOW_TTL)

    def complete(self, code, state, cookie_header):
        browser = cookie_value(cookie_header, FLOW_COOKIE)
        with self.lock:
            self.purge()
            flow = self.pending.pop(state, None)  # Consume before contacting the provider.
        if (not flow or not browser or not code or len(code) > 4096 or
                not secrets.compare_digest(flow['browser'], hashlib.sha256(browser.encode()).hexdigest())):
            raise AuthenticationError('授权状态无效或已过期，请重新登录。')
        # Official API: code/client_id in query, client_secret in multipart form-data.
        boundary = 'msllm-' + secrets.token_hex(24)
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="client_secret"\r\n\r\n'
                f'{self.config.client_secret}\r\n--{boundary}--\r\n').encode()
        token_url = TOKEN_URL + '?' + urlencode({'grant_type': 'authorization_code',
                                                'code': code, 'client_id': self.config.client_id})
        token_data = self.fetch(Request(token_url, data=body, headers={
            'Content-Type': 'multipart/form-data; boundary=' + boundary, 'Accept': 'application/json'}))
        token = token_data.get('access_token')
        if not isinstance(token, str) or not token or '\r' in token or '\n' in token:
            raise AuthenticationError('GitCode 未返回有效授权令牌。')
        user = self.fetch(Request(USER_URL, headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}))
        user_id = user.get('id')
        if not isinstance(user_id, str) or not self.allowed(user_id):
            raise AuthenticationError('此 GitCode 账号不在访问白名单中。')
        # Do not retain access_token/refresh_token; only minimal identity is stored.
        session = {'id': user_id, 'login': str(user.get('login', '')), 'csrf': secrets.token_urlsafe(32),
                   'expires': self.clock() + self.SESSION_TTL}
        sid = secrets.token_urlsafe(32)
        with self.lock:
            self.purge()
            if len(self.sessions) >= self.MAX_ENTRIES:
                raise AuthenticationError('登录会话已满，请稍后重试。')
            self.sessions[sid] = session
        return sid

    def current(self, cookie_header):
        sid = cookie_value(cookie_header, SESSION_COOKIE)
        with self.lock:
            self.purge()
            session = self.sessions.get(sid)
        if session and self.allowed(session['id']):
            return dict(session)
        with self.lock:
            self.sessions.pop(sid, None)
        return None

    def logout(self, cookie_header, csrf):
        session = self.current(cookie_header)
        if not session or not secrets.compare_digest(session['csrf'], csrf):
            raise AuthenticationError('退出请求无效。')
        with self.lock:
            self.sessions.pop(cookie_value(cookie_header, SESSION_COOKIE), None)
