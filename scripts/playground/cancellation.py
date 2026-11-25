"""Request-scoped cancellation while the caller retains its device lease."""
from contextlib import contextmanager
import re
import subprocess
import threading
import time


class GenerationStopped(Exception):
    pass


class Generation:
    def __init__(self, device, on_cancel=None):
        self.device = device
        self.on_cancel = on_cancel
        self.lock = threading.Lock()
        self.stopped = False
        self.process = None
        self.finished = False

    def launch(self, *args, **kwargs):
        with self.lock:
            if self.stopped:
                raise GenerationStopped()
            self.process = subprocess.Popen(*args, **kwargs)
            return self.process

    def submit(self, operation):
        with self.lock:
            if self.stopped:
                raise GenerationStopped()
            return operation()

    def cancel(self):
        with self.lock:
            if self.finished or self.stopped:
                return
            if self.on_cancel is not None:
                self.on_cancel()
                self.stopped = True
                return
            if self.process is not None and self.process.poll() is None:
                prefix = ['hdc', '-t', self.device, 'shell', 'aa']
                result = subprocess.run(prefix + ['force-stop', 'com.example.binrunner'],
                                        capture_output=True, timeout=12)
                if result.returncode or b'successfully' not in result.stdout:
                    raise OSError('Phone did not confirm cancellation')
                self.process.terminate()
                self.process.wait(timeout=5)
                self.stopped = True
                subprocess.run(prefix + ['start', '-b', 'com.example.binrunner', '-a', 'EntryAbility'],
                               capture_output=True, timeout=12, check=True)
            else:
                self.stopped = True


class Generations:
    def __init__(self):
        self.lock = threading.Lock()
        self.active = {}
        self.recent = {}

    def validate(self, key):
        if key is not None and (not isinstance(key, str) or not re.fullmatch(r'[a-f0-9]{32}', key)):
            raise ValueError('Invalid request_id')

    def prune(self):
        now = time.monotonic()
        self.recent = {key: value for key, value in self.recent.items() if value[1] > now}
        if len(self.recent) >= 4096:
            self.recent.pop(next(iter(self.recent)))

    @contextmanager
    def track(self, key, device, on_cancel=None):
        self.validate(key)
        generation = Generation(device, on_cancel)
        with self.lock:
            self.prune()
            if key and (key in self.active or key in self.recent):
                raise GenerationStopped()
            if key:
                self.active[key] = generation
        try:
            yield generation
        finally:
            with generation.lock:
                generation.finished = True
            with self.lock:
                if key:
                    self.active.pop(key, None)
                    self.recent[key] = ('finished', time.monotonic() + 600)

    def cancel(self, key):
        self.validate(key)
        if key is None:
            raise ValueError('Missing request_id')
        with self.lock:
            self.prune()
            generation = self.active.get(key)
            if generation is None:
                # A stop can arrive before its generation request.
                self.recent.setdefault(key, ('cancelled', time.monotonic() + 600))
        if generation:
            generation.cancel()
        return {'status': 'stopped', 'request_id': key}
