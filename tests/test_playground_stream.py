import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
folder = Path(__file__).resolve().parents[1] / 'scripts/playground'
sys.path.insert(0, str(folder))
spec = importlib.util.spec_from_file_location('q35_preview_stream', folder/'qwen35-preview.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ResidentStreamTests(unittest.TestCase):
    def decode(self, pieces, reason='stop'):
        events = [{'content_hex': piece.hex()} for piece in pieces]
        events.append({'done': True, 'finish_reason': reason, 'decode_tokens': len(pieces)})
        source = io.BytesIO(b''.join(json.dumps(event).encode() + b'\n' for event in events))
        return list(module.resident_events(source))

    def test_chinese_and_emoji_at_every_byte_boundary(self):
        text = '西湖醋鱼：草鱼或鲈鱼。杭州美食🍜\n"好吃"'
        raw = text.encode()
        for cut in range(1,len(raw)):
            with self.subTest(cut=cut):
                events = self.decode([raw[:cut],raw[cut:]])
                self.assertEqual(''.join(e.get('content','') for e in events),text)
                self.assertEqual(events[-1]['decode_tokens'],2)
                self.assertTrue(events[-1]['done'])

    def test_one_byte_chunks_are_reassembled_without_replacement(self):
        raw = '鲈鱼🍜'.encode()
        events = self.decode([bytes([b]) for b in raw])
        self.assertEqual(''.join(e.get('content','') for e in events),'鲈鱼🍜')

    def test_cancel_at_partial_character_finishes_without_decode_error(self):
        events = self.decode([b'hello\xe9\xb2'],reason='cancelled')
        self.assertEqual(''.join(e.get('content','') for e in events),'hello\ufffd')
        self.assertEqual(events[-1]['finish_reason'],'cancelled')

if __name__ == '__main__': unittest.main()
