import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from bench_common.runner import run_profile


class RunnerTests(unittest.TestCase):
    def test_pull_timeout_does_not_abort_collection(self):
        fixture = ROOT / 'reports/qwen3-9030-daily-20261026/pr-validation/results-aligned'
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'run'
            pulls = []
            profile = dict(device='test', port='1', binrunner=tmp, output=str(out),
                           binary='test', model='@/bin/model', log='result.log',
                           process='worker', backend='msl', completion='DESTROY status=0')

            def execute(command, **kwargs):
                if command[0] == 'hdc':
                    result = '123 worker\n' if command[-1].startswith('ps ') else 'memory sample\n'
                elif 'pull' in command:
                    pulls.append(1)
                    if len(pulls) == 1:
                        raise subprocess.TimeoutExpired(command, 30)
                    (out / 'inference.log').write_text((fixture / 'inference.log').read_text())
                    result = ''
                else:
                    result = 'WORKER_PID 123'
                return subprocess.CompletedProcess(command, 0, result, '')

            with patch.object(sys, 'argv', ['run', '--initial-wait', '.05', '--poll-interval', '.01']), patch('bench_common.runner.subprocess.run', side_effect=execute):
                run_profile(profile)
            self.assertEqual(len(pulls), 2)
            self.assertEqual(len(json.loads((out / 'samples.json').read_text())), 5)
            self.assertTrue(list(out.glob('memory-*.txt')))

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'existing.log'
            marker.write_text('keep')
            profile = dict(device='test', port='1', binrunner=tmp, output=tmp,
                           binary='test', model='model', log='result.log')
            with patch.object(sys, 'argv', ['run']), self.assertRaises(SystemExit):
                run_profile(profile)
            self.assertEqual(marker.read_text(), 'keep')
