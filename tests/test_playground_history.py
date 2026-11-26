import importlib.util
from pathlib import Path
import sys
import unittest
folder = Path(__file__).resolve().parents[1] / 'scripts/playground'
sys.path.insert(0, str(folder))
spec = importlib.util.spec_from_file_location('q35_preview', folder/'qwen35-preview.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
normalize = module.normalize_messages

class HistoryTests(unittest.TestCase):
    def test_unfinished_thinking_is_not_replayed_as_user_instructions(self):
        result = normalize([
            {'role':'user','content':'介绍杭州'},
            {'role':'assistant','content':'<think>Wait, the instruction says "Output the thinking process".'},
            {'role':'user','content':'介绍一下上海的美食'},
        ])
        self.assertEqual(result, [
            {'role':'system','content':'You are a helpful assistant.'},
            {'role':'user','content':'介绍一下上海的美食'},
        ])

    def test_real_roles_are_preserved_without_thinking_or_stats(self):
        result = normalize([
            {'role':'user','content':'我的名字是小明'},
            {'role':'assistant','content':'<think>reason</think>你好，小明'+module.STATS_MARKER+'stats'},
            {'role':'user','content':'我叫什么名字？'},
        ])
        self.assertEqual([m['role'] for m in result], ['system','user','assistant','user'])
        self.assertEqual(result[2]['content'], '你好，小明')

    def test_implicit_thinking_prefix_is_removed(self):
        result = normalize([
            {'role':'user','content':'你好'},
            {'role':'assistant','content':'reason</think>你好'},
            {'role':'user','content':'继续'},
        ])
        self.assertEqual(result[2]['content'], '你好')

    def test_paper_text_is_unchanged(self):
        text = 'Agents [8] use 8–32 GB.\nA "quote", $var and `code`.'
        self.assertEqual(normalize([{'role':'user','content':text}])[-1]['content'],text)

if __name__ == '__main__': unittest.main()
