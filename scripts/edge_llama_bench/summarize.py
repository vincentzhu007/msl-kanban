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
    parser.add_argument("results", nargs="?", type=pathlib.Path, default=BASE / 'reports/edge-slm/20261026-llama-q40-cpu9020')
    parser.add_argument("--publish", type=pathlib.Path, help="Optional dashboard JSON destination")
    options = parser.parse_args()
    P = options.results
    rows = json.loads((P / 'samples.json').read_text())
    log = (P / 'inference.log').read_text()
    validate_rows(rows, backend='llama')
    mem = read_memory(P, log, rows, pattern='memory-*.txt', skip_invalid=True)
    summary = {
        'id': '20261026-llama-q40-cpu9020',
        'date': '2026-10-26',
        'framework': 'llama.cpp · CPU 4线程',
        'device': 'HUAWEI Mate 70 Pro',
        'source': '实测 · dog',
        'build_commit': '07822bddf80d73f1168e592c52e69caaff820f9c',
        'spec': {
            'model': 'Qwen2.5-0.5B-Instruct',
            'quantization': 'GGUF Q4_0 (mixed tensor types)',
            'soc': 'Kirin9020',
            'context': 2048,
            'input_tokens': 1024,
            'output_tokens': 128,
            'consecutive_runs': 5,
            'between_runs_wait_seconds': 0,
            'threads': 4,
            'n_batch': 64,
            'n_ubatch': 64,
            'gpu_layers': 0,
        },
        'model': {
            'bytes': 428730208,
            'sha256': (P / 'model.sha256').read_text().split()[0],
        },
        'timing': {},
        'memory': {},
        'samples': rows,
        'memory_samples': mem,
        'protocol_note': '纯 CPU、4 线程、无绑核，GPU layers=0；2K 上下文，batch/ubatch=64，FP16 KV，关闭 Flash Attention。原始 hello 合成输入1024 token，无模板、无BOS；greedy连续5次输出128 token，无EOS。hidumper同步采样，温度和频率未锁定。GGUF与MSL的逐tensor量化/权重一致性未验证，属于部署方案对比。',
        'p90_method': 'nearest-rank (n=5 => max)',
        'build_options': {
            'arch': 'armv8.2-a+dotprod',
            'cpu_repack': True,
            'openmp': False,
            'shared_libs': False,
            'ohos_compat': 'pthread_setaffinity_np mapped to sched_setaffinity for current thread',
        },
    }
    # Keep annotations added after measurement, but never carry forward computed metrics.
    previous_path = P / "benchmark.json"
    if previous_path.exists():
        previous = json.loads(previous_path.read_text())
        if previous.get("model", {}).get("sha256") == summary["model"]["sha256"]:
            summary["model"] = previous.get("model", {}) | summary["model"]
            for key in ("protocol_note", "archive_path"):
                if key in previous:
                    summary[key] = previous[key]
    summary["timing"], summary["memory"] = summarize(rows, mem)
    summary["memory"].update(stable_definition="Entire dump interval within decode runs 2-5")
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
