"""Recompute a benchmark from archived measurements; publishing is explicit."""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from bench_common.metrics import read_memory, summarize, validate_rows, write_csv

BASE = pathlib.Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", nargs="?", type=pathlib.Path, default=BASE / 'reports/edge-slm/20261026-qwen25-05b-w4a16-9020/context2048-input1024-output128')
    parser.add_argument("--publish", type=pathlib.Path, help="Optional dashboard JSON destination")
    options = parser.parse_args()
    P = options.results
    rows = json.loads((P / 'five-aligned-samples.json').read_text())
    log = (P / 'five-aligned.log').read_text()
    validate_rows(rows, backend='msl')
    mem = read_memory(P, log, rows, pattern='five-aligned-memory-*.txt', skip_invalid=False)
    summary = {
        'spec': {
            'model': 'Qwen2.5-0.5B',
            'quantization': 'W4A16/Q4_0 group32',
            'soc': 'Kirin9020',
            'context': 2048,
            'input_tokens': 1024,
            'output_tokens': 128,
            'consecutive_runs': 5,
            'between_runs_wait_seconds': 0,
            'warmup_in_this_process': 0,
        },
        'build_commit': '5501731a356ffb4ec017a4dc37c3f5631be79489',
        'latency_p90_method': 'nearest-rank: sorted[ceil(0.9*5)-1]; maximum for n=5',
        'timing': {},
        'memory': {},
        'model': json.loads((P / 'model-provenance.json').read_text()),
    }
    summary["timing"], summary["memory"] = summarize(rows, mem)
    summary["memory"].update(stable_definition="Samples entirely within decode of runs 2 through 5, aligned using device wall time and monotonic time", peak_scope="Observed from first sample during build until destruction; discrete samples may miss short peaks", dma_duplicates_graph=True)
    payload = json.dumps(summary, indent=2, ensure_ascii=False)
    (P / "benchmark.json").write_text(payload)
    write_csv(P, rows, mem)
    if options.publish:
        if "id" not in summary:
            parser.error("MSL summary requires dashboard identity fields before publishing")
        options.publish.write_text(payload)
    print(payload)


if __name__ == "__main__":
    main()
