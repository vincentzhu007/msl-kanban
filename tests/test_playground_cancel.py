import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/playground'))
from cancellation import Generations, GenerationStopped

class CancellationTests(unittest.TestCase):
    def test_stop_before_start_prevents_execution(self):
        registry = Generations()
        registry.cancel('a' * 32)
        with self.assertRaises(GenerationStopped):
            with registry.track('a' * 32, 'phone'):
                self.fail('Cancelled request must not start')

    @patch('cancellation.subprocess.run')
    @patch('cancellation.subprocess.Popen')
    def test_only_matching_live_request_stops_phone(self, popen, run):
        run.return_value = Mock(returncode=0, stdout=b'force stop process successfully.')
        process = popen.return_value
        process.poll.return_value = None
        registry = Generations()
        with registry.track('a' * 32, 'phone-a') as generation:
            generation.launch(['runner'])
            registry.cancel('b' * 32)
            run.assert_not_called()
            registry.cancel('a' * 32)
            self.assertTrue(generation.stopped)
            self.assertEqual(run.call_args_list[0].args[0][2], 'phone-a')
            process.terminate.assert_called_once()
            registry.cancel('a' * 32)
            self.assertEqual(run.call_count, 2)
        registry.cancel('a' * 32)
        self.assertEqual(run.call_count, 2)

    @patch('cancellation.subprocess.run')
    @patch('cancellation.subprocess.Popen')
    def test_failed_phone_stop_is_retryable(self, popen, run):
        popen.return_value.poll.return_value = None
        run.return_value = Mock(returncode=1, stdout=b'failed')
        registry = Generations()
        with registry.track('a' * 32, 'phone') as generation:
            generation.launch(['runner'])
            with self.assertRaises(OSError):
                registry.cancel('a' * 32)
            self.assertFalse(generation.stopped)
            popen.return_value.terminate.assert_not_called()

if __name__ == '__main__':
    unittest.main()
