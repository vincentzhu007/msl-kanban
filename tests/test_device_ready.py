import sys
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from recipe_ci.device_ready import awake_device

LOCK = 'SCBScreenLock12 0 3448 18 2110 [ 0 0 1280 2832 ]\nFocus window: 18\n'
APP = 'binrunner0 0 50180 35 1 [ 0 0 1280 2832 ]\nFocus window: 35\n'

class DeviceReadyTests(unittest.TestCase):
    def run_case(self, locked):
        calls=[]
        dumps=iter([LOCK]+[LOCK if locked else APP]*10)
        def execute(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd,0,next(dumps) if 'hidumper' in cmd else '', '')
        with patch('recipe_ci.device_ready.subprocess.run', side_effect=execute), patch('recipe_ci.device_ready.time.sleep'):
            if locked:
                with self.assertRaisesRegex(RuntimeError, 'authentication'):
                    with awake_device('device'): self.fail('must not measure a locked device')
            else:
                with awake_device('device'): pass
        self.assertIn(['hdc','-t','device','shell','power-shell','timeout','-r'], calls)
        self.assertEqual(sum('swipe' in c for c in calls),1)
    def test_normal_swipe_then_foreground_and_restore(self): self.run_case(False)
    def test_locked_device_fails_closed_and_restores(self): self.run_case(True)
