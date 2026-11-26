import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts/playground'))
from qwen35_resident import Resident

class ResidentStatusTests(unittest.TestCase):
    def resident(self, loading=False, exit_code=None):
        r = Resident()
        r.process = Mock()
        r.process.poll.return_value = exit_code
        r.started = time.monotonic() - 600
        r.loading_id = 'a' * 32 if loading else None
        r.rpc = Mock(side_effect=OSError('disconnected'))
        r.wake = Mock()
        r.forward = Mock()
        r.phone_listening = Mock(return_value=True)
        r.stop = Mock()
        return r

    def test_missing_phone_service_releases_stale_live_bridge(self):
        r = self.resident()
        process = r.process
        r.lease = Mock()
        lease = r.lease
        r.phone_listening.return_value = False
        state = r.status()
        self.assertEqual(state['state'], 'unloaded')
        self.assertIn('重新加载', state['error'])
        process.terminate.assert_called_once()
        lease.close.assert_called_once()
        self.assertIsNone(r.process)
        r.stop.assert_not_called()

    def test_unknown_phone_status_does_not_destroy_model(self):
        r = self.resident()
        process = r.process
        r.phone_listening.return_value = None
        self.assertEqual(r.status()['state'], 'unavailable')
        process.terminate.assert_not_called()
        r.stop.assert_not_called()

    def test_phone_probe_distinguishes_missing_listener_from_failed_probe(self):
        header = b'Proto Recv-Q Send-Q Local Address Foreign Address State\n'
        cases = [
            (header + b'tcp 0 0 127.0.0.1:18947 0.0.0.0:* LISTEN\n', True),
            (header + b'tcp 0 0 0.0.0.0:8888 0.0.0.0:* LISTEN\n', False),
            (b'[Fail] device disconnected', None),
        ]
        for output, expected in cases:
            with self.subTest(output=output), patch('qwen35_resident.subprocess.run', return_value=Mock(returncode=0, stdout=output)):
                self.assertIs(Resident().phone_listening(), expected)

    def test_loaded_model_is_not_destroyed_as_loading_timeout(self):
        r = self.resident()
        state = r.status()
        self.assertEqual(state['state'], 'unavailable')
        self.assertNotIn('加载超时', state.get('error', ''))
        r.stop.assert_not_called()

    def test_exited_loaded_model_is_reported_as_disconnected(self):
        r = self.resident(exit_code=1)
        state = r.status()
        self.assertEqual(state['state'], 'unloaded')
        self.assertIn('退出', state['error'])
        r.stop.assert_not_called()
        self.assertIsNone(r.process)

    def test_initial_load_still_has_timeout(self):
        r = self.resident(loading=True)
        state = r.status()
        self.assertEqual(state['state'], 'unloaded')
        self.assertIn('加载超时', state['error'])
        r.stop.assert_called_once()

    def test_recovery_keeps_ready_model_and_hides_cancellation_id(self):
        r = self.resident()
        r.rpc.side_effect = [OSError('sleeping'), {'state':'ready','request_id':'secret','load_ms':1200}]
        self.assertEqual(r.status(), {'state':'ready','load_ms':1200})
        r.stop.assert_not_called()

if __name__ == '__main__': unittest.main()
