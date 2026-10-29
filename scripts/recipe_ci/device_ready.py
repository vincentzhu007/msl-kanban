"""Prepare the test app through normal device UI; never bypass authentication."""
from contextlib import contextmanager
import re
import subprocess
import time
import threading


def focused_window(dump):
    match = re.search(r'^Focus window:\s*(\d+)', dump, re.M)
    if not match:
        return ''
    for line in dump.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[3] == match[1]:
            return line
    return ''


@contextmanager
def awake_device(serial):
    def shell(*args):
        return subprocess.run(['hdc', '-t', serial, 'shell', *args], check=True,
                              capture_output=True, text=True, timeout=20).stdout
    def window():
        return focused_window(shell('hidumper', '-s', 'WindowManagerService', '-a', '-a'))
    stop = threading.Event()
    errors = []
    def keep_awake():
        while not stop.wait(10):
            try:
                shell('power-shell', 'wakeup')
            except Exception as error:
                errors.append(error)
                return
    keeper = threading.Thread(target=keep_awake, daemon=True)
    try:
        shell('power-shell', 'wakeup')
        time.sleep(2)
        shell('power-shell', 'timeout', '-o', '1800000')
        keeper.start()
        focus = window()
        if focus.startswith('SCBScreenLock'):
            bounds = re.search(r'\[\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*\]', focus)
            if not bounds:
                raise RuntimeError('Cannot determine lock-screen dimensions')
            x, y, width, height = map(int, bounds.groups())
            shell('uitest', 'uiInput', 'swipe', str(x + width // 2),
                  str(y + height * 85 // 100), str(x + width // 2),
                  str(y + height * 18 // 100), '600')
            time.sleep(1)
        shell('aa', 'start', '-b', 'com.example.binrunner', '-a', 'EntryAbility')
        stable = 0
        for _ in range(10):
            stable = stable + 1 if window_name_is_binrunner(window()) else 0
            if stable >= 3:
                break
            time.sleep(1)
        else:
            raise RuntimeError('BinRunner is not foreground; device may require manual authentication')
        yield
        if errors:
            raise RuntimeError('Device screen keepalive failed; discard measurement') from errors[0]
    finally:
        stop.set()
        if keeper.is_alive():
            keeper.join()
        shell('power-shell', 'timeout', '-r')


def window_name_is_binrunner(line):
    return bool(line.split()) and line.split()[0].lower().startswith('binrunner')
