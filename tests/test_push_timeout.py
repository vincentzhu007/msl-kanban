import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import daily_ci.pipeline as pipeline


class PushTimeoutTests(unittest.TestCase):
    def test_floor_for_small_and_empty_packages(self):
        self.assertEqual(pipeline.push_timeout_seconds(0), 600)
        self.assertEqual(pipeline.push_timeout_seconds(281 * 1024 * 1024), 600)

    def test_volume_formula_for_4b_sized_package(self):
        size = 2285402624  # archived Qwen3-4B s16s4 package
        expected = max(600, int(__import__('math').ceil(size / (2 * 1024 * 1024) * 1.3)))
        self.assertEqual(pipeline.push_timeout_seconds(size), expected)
        self.assertEqual(expected, 1417)

    def test_measured_qwen3_4b_package_exceeds_old_cap(self):
        # 1999.315 MiB package that reached 92% when the 600s cap fired.
        size = round(1999.315 * 1024 * 1024)
        self.assertEqual(pipeline.push_timeout_seconds(size), 1300)

    def test_rejects_invalid_size(self):
        with self.assertRaises(ValueError):
            pipeline.push_timeout_seconds(-1)
        with self.assertRaises(ValueError):
            pipeline.push_timeout_seconds(True)

    def test_retries_once_after_timeout_and_then_succeeds(self):
        calls = []

        def fake_run(*args, **kwargs):
            calls.append(kwargs['timeout'])
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(args[0], kwargs['timeout'])

        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'push-model.log'
            command = ['python3', '-m', 'binrunner', 'push', 'model.msl']
            with patch('daily_ci.pipeline.subprocess.run', side_effect=fake_run):
                pipeline.push_with_resume(command, log, cwd=tmp, size_bytes=2285402624)
            text = log.read_text()
            self.assertEqual(calls, [1417, 1417])
            self.assertEqual(text.splitlines()[0], json.dumps(command))
            self.assertIn('"push_attempt": 1', text)
            self.assertIn('"push_attempt": 2', text)
            self.assertIn('timed out after 1417s (attempt 1/2)', text)
            self.assertIn('resume is the default in 1.4.1', text)

    def test_raises_after_final_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'push-model.log'
            with patch('daily_ci.pipeline.subprocess.run',
                       side_effect=subprocess.TimeoutExpired(['push'], 600)):
                with self.assertRaises(subprocess.TimeoutExpired):
                    pipeline.push_with_resume(['push', 'm.msl'], log, cwd=tmp, size_bytes=1024)
            self.assertIn('attempt 2/2', log.read_text())

    def test_does_not_retry_non_timeout_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / 'push-model.log'
            error = subprocess.CalledProcessError(1, ['push'])
            with patch('daily_ci.pipeline.subprocess.run', side_effect=error) as run:
                with self.assertRaises(subprocess.CalledProcessError):
                    pipeline.push_with_resume(['push', 'm.msl'], log, cwd=tmp, size_bytes=1024)
            self.assertEqual(run.call_count, 1)
            text = log.read_text()
            self.assertIn('"push_attempt": 1', text)
            self.assertNotIn('push_attempt": 2', text)
            self.assertNotIn('Retrying', text)


if __name__ == '__main__':
    unittest.main()
