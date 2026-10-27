"""Run the daily-library probe on dog through its existing BinRunner installation."""
import hashlib
import json
import pathlib
import statistics
import subprocess
import time
from datetime import datetime, timezone

ROOT = pathlib.Path('/home/zhugd/llm_validation/20261026-qwen25-05b-w4a16-9020')
BR = pathlib.Path('/home/zhugd/code/ohos/BinRunner')
CMD = ['python3', '-m', 'binrunner', '-t', '127.0.0.1:2000', '-p', '18888',
       'run', 'daily-20261026-bench @/bin/st3_qwen25.msl 1', '--timeout', '90']

def main():
    all_rows = []
    cycles = []
    for cycle in range(1, 6):
        started = datetime.now(timezone.utc).isoformat()
        result = subprocess.run(CMD, cwd=BR, capture_output=True, text=True, timeout=110)
        output = result.stdout + '\n' + result.stderr
        (ROOT / f'cycle-{cycle}.log').write_text(output)
        rows = []
        for line in output.splitlines():
            if line.startswith('RESULT '):
                row = json.loads(line[len('RESULT '):])
                row['cycle'] = cycle
                row['started_at_utc'] = started
                rows.append(row)
        good = result.returncode == 0 and 'DESTROY status=0' in output and len(rows) == 4
        good = good and all(r['status'] == 0 and r['output_callbacks'] == 128 and r['finish_reason'] == 3 for r in rows)
        cycles.append({'cycle': cycle, 'returncode': result.returncode, 'valid': good})
        all_rows.extend(rows)
        (ROOT / 'samples.json').write_text(json.dumps({'cycles': cycles, 'samples': all_rows}, indent=2))
        print(json.dumps(cycles[-1]), flush=True)
        if not good:
            raise RuntimeError(f'Incomplete cycle {cycle}; inspect raw log')
        if cycle < 5:
            time.sleep(15)
    summaries = []
    for n in (64, 512):
        selected = [r for r in all_rows if r['hello_repetitions'] == n and not r['warmup']]
        item = {'input_tokens_hf_verified': n, 'output_tokens': 128, 'measured_runs': len(selected)}
        for metric in ('ttft_ms', 'decode_tps', 'total_ms', 'rss_after_kib', 'process_hwm_kib'):
            values = [r[metric] for r in selected]
            item[metric] = {'median': statistics.median(values), 'min': min(values), 'max': max(values)}
        item['input_tokens_per_second_including_ttft'] = n * 1000 / item['ttft_ms']['median']
        summaries.append(item)
    result = {'schema_version': 1, 'status': 'complete', 'device': 'dog:127.0.0.1:2000',
              'phone': 'HUAWEI Mate 70 Pro / PLR-AL00', 'soc': 'Kirin 9020',
              'os': '6.1.0.135(SP8C00E120R4P5)',
              'build_commit': '5501731a356ffb4ec017a4dc37c3f5631be79489',
              'archive_sha256': hashlib.sha256((ROOT / 'mindspore-lite-llm-linux-x64-0.2.0.tar.gz').read_bytes()).hexdigest(),
              'model': {'device_path': '@/bin/st3_qwen25.msl', 'architecture': 'qwen2.5-0.5b',
                        'bytes': 288692736, 'sha256': 'f86dd4a7f4b2b6a0794f965cae91b11a4b444dbd304d931ffa900c1228e3f9a2',
                        'quant': 'W4A16 / Q4_0', 'group_size': 32, 'context_length': 1024, 'prefill_chunk': 64,
                        'provenance': 'Existing deployed compiled model; not re-exported with the daily compiler/operator package'},
              'protocol': {'prompt': 'Raw string: space + hello, repeated 64 or 512 times; no chat template',
                           'input_count': 'Verified using existing Hugging Face tokenizer.json; runtime public API has no input-count export',
                           'generation': 'greedy, max_new_tokens=128, repetition_penalty=1',
                           'cycles': 5, 'warmup': 'One generation before the measured generation per input length in each process',
                           'pause_seconds': 3, 'between_processes_seconds': 15,
                           'timing': 'Device steady_clock at public API callback; TTFT includes tokenization/prefill/first sample and excludes model build',
                           'memory': 'Process VmRSS and getrusage ru_maxrss, includes inherited BinRunner process footprint; not full device/NPU memory',
                           'thermal': 'Ambient temperature, battery state and clocks not controlled; NPU runtime selects EXTREME'},
              'summary': summaries, 'cycles': cycles}
    (ROOT / 'benchmark.json').write_text(json.dumps(result, indent=2, ensure_ascii=False))
    print(json.dumps(summaries, indent=2), flush=True)

if __name__ == '__main__':
    main()
