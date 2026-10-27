"""Device profile; use --help to override deployment configuration."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bench_common.runner import run_profile

PROFILE = {'device': '5JV0226127000651',
 'port': '18940',
 'binrunner': '/home/zhugd/code/ohos/BinRunner',
 'binary': 'daily-qwen3',
 'model': '@/bin/qwen3-4b-daily-s16s4-9030-2048.msl',
 'process': 'daily-qwen3',
 'backend': 'msl',
 'completion': 'DESTROY status=0',
 'output': '/home/zhugd/llm_validation/20261026-qwen3-4b-s16s4-9030/pr-validation/results-aligned',
 'log': 'qwen3-pr62-20261026.log',
 'initial_wait': 70}


if __name__ == "__main__":
    run_profile(PROFILE)
