"""Device profile; use --help to override deployment configuration."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_common.runner import run_profile

PROFILE = {'device': '127.0.0.1:2000',
 'port': '18888',
 'binrunner': '/home/zhugd/code/ohos/BinRunner',
 'binary': 'edge-llama',
 'model': '@/bin/qwen2.5-0.5b-instruct-q4_0.gguf',
 'process': 'edge-llama',
 'backend': 'llama',
 'completion': 'DONE status=0',
 'output': '/home/zhugd/llm_validation/20261026-llama-q40-cpu9020/results-aligned',
 'log': 'llama-cpu-20261026.log'}


if __name__ == "__main__":
    run_profile(PROFILE)
