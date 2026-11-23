"""Exclusive, time-limited display access for a dedicated lab handset."""
import base64
import re
import secrets
import struct
import subprocess
import tempfile
import threading
import time
from pathlib import Path


class ScreenError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Screen:
    def __init__(self, device, bundle, ability):
        self.prefix = ['hdc', '-t', device]
        self.bundle, self.ability = bundle, ability
        self.lock = threading.Lock()
        self.session = None
        self.expires = 0
        self.size = None
        for name in (bundle, ability):
            if not re.fullmatch(r'[A-Za-z0-9_.]+', name):
                raise ValueError('Invalid app identifier')

    def run(self, *args):
        result = subprocess.run(self.prefix + list(args), capture_output=True, timeout=10)
        if result.returncode or b'[Fail]' in result.stdout or b'Error:' in result.stdout:
            raise ScreenError(503, 'Device command failed.')

    def request(self, action, body, token):
        with self.lock:
            if action == 'start':
                if self.expires > time.monotonic():
                    raise ScreenError(429, 'Device session is occupied.')
                self.run('shell', 'aa', 'start', '-b', self.bundle, '-a', self.ability)
                self.session = secrets.token_urlsafe(24)
                self.size = None
                self.expires = time.monotonic() + 60
                return {'session': self.session}
            if self.expires <= time.monotonic() or token != self.session:
                raise ScreenError(403, 'Device session expired.')
            if action == 'end':
                self.expires = 0
                self.session = None
                return {}
            if action == 'frame':
                remote = '/data/local/tmp/mslite-' + self.session + '.png'
                with tempfile.TemporaryDirectory() as tmp:
                    local = Path(tmp) / 'frame.png'
                    try:
                        self.run('shell', 'uitest', 'screenCap', '-p', remote)
                        self.run('file', 'recv', remote, str(local))
                        data = local.read_bytes()
                    finally:
                        self.run('shell', 'rm', '-f', remote)
                if not data.startswith(b'\x89PNG\r\n\x1a\n') or len(data) < 24:
                    raise ScreenError(503, 'Invalid device frame.')
                self.size = struct.unpack('>II', data[16:24])
                result = {'png': base64.b64encode(data).decode()}
            elif action == 'input':
                gesture = body.get('gesture')
                points = body.get('points')
                count = {'click': 2, 'swipe': 4}.get(gesture) if isinstance(gesture, str) else None
                if not self.size or not count or not isinstance(points, list) or len(points) != count:
                    raise ScreenError(400, 'Invalid gesture.')
                if any(type(v) is not int or not 0 <= v < self.size[i % 2] for i, v in enumerate(points)):
                    raise ScreenError(400, 'Coordinates exceed frame.')
                self.run('shell', 'uitest', 'uiInput', gesture, *map(str, points))
                result = {}
            else:
                raise ScreenError(404, 'Unknown screen operation.')
            self.expires = time.monotonic() + 60
            return result
