import sys
import time
import unittest
from pathlib import Path
from unittest.mock import Mock
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
        r.stop = Mock()
        return r

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
        self.assertIn('断开', state['error'])
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
