"""Prepare the test app through normal device UI; never bypass authentication."""
from contextlib import contextmanager
import re
import subprocess
import time


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
    try:
        shell('power-shell', 'timeout', '-o', '1800000')
        shell('power-shell', 'wakeup')
        time.sleep(1)
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
        for _ in range(10):
            if window_name_is_binrunner(window()):
                break
            time.sleep(.5)
        else:
            raise RuntimeError('BinRunner is not foreground; device may require manual authentication')
        yield
    finally:
        shell('power-shell', 'timeout', '-r')


def window_name_is_binrunner(line):
    return bool(line.split()) and line.split()[0].lower().startswith('binrunner')
