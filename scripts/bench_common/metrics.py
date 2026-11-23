"""Device-clock aligned statistics. All memory values are KiB."""
import csv
import math
import re
import statistics
import warnings


def validate_rows(rows, backend="msl", count=5, input_tokens=1024, output_tokens=128):
    if len(rows) != count or [r.get("run") for r in rows] != list(range(1, count + 1)):
        raise ValueError(f"Expected {count} ordered, unique runs")
    for row in rows:
        valid = row.get("status") == 0 and row.get("output_callbacks") == output_tokens
        if backend == "llama":
            valid &= row.get("input_tokens") == input_tokens and row.get("eog_tokens") == 0
        else:
            valid &= row.get("finish_reason") == 3
            valid &= row.get("hello_repetitions", input_tokens) == input_tokens
        if not valid:
            raise ValueError(f"Invalid generation result: {row}")
        for key in ("ttft_ms", "decode_ms", "total_ms", "decode_tps"):
            if not math.isfinite(row[key]) or row[key] < 0:
                raise ValueError(f"Invalid {key} in run {row['run']}")


def initialization(log):
    """Once per process; never label a single model initialization as P90."""
    import json
    events = [json.loads(line[5:]) for line in log.splitlines() if line.startswith('INIT ')]
    if not events:
        return None
    if len(events) != 1:
        raise ValueError('Expected exactly one initialization event')
    value = events[0].get('model_init_ms')
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        raise ValueError('Invalid model initialization duration')
    return {'model_init_ms': value, 'samples': 1,
            'scope': 'Backend/model/context/sampler or generation config ready; excludes process startup; filesystem cache uncontrolled'}


# Log scope -> (ram_method, description). Methods are not comparable with each other.
BASELINE_METHODS = {
    'before_runtime_load': ('pre-runtime-pss-v1', 'same PID before Lite LLM runtime dlopen; first 2 seconds excluded'),
    'before_model_create': ('pre-model-create-pss-v1', 'same PID before MSLLMCreateModel; first 2 seconds excluded'),
}


def read_memory(directory, log, rows, pattern="memory-*.txt", skip_invalid=False):
    clock = re.search(r"WALL_MS ([\d.]+) MONOTONIC_MS ([\d.]+)", log)
    if not clock:
        raise ValueError("Missing device wall/monotonic clock alignment")
    wall, monotonic = map(float, clock.groups())
    offset = wall - monotonic
    # before_runtime_load: legacy dynamic-loading probe (5f242f2); before_model_create: static probe.
    baseline = re.search(r"MEMORY_BASELINE scope=(before_model_create|before_runtime_load) pid=(\d+)", log)
    bounds = None
    if baseline:
        begin = re.findall(r"PHASE baseline_start monotonic_ms=([\d.]+)", log)
        finish = re.findall(r"PHASE baseline_end monotonic_ms=([\d.]+)", log)
        if len(begin) != 1 or len(finish) != 1 or float(finish[0]) <= float(begin[0]) + 2000:
            raise ValueError("Missing or invalid PSS baseline phase")
        bounds = (float(begin[0]) + offset + 2000, float(finish[0]) + offset)

    starts = {int(n): float(t) + offset for n, t in re.findall(
        r"PHASE inference run=(\d+) monotonic_ms=([\d.]+)", log)}
    ends = {int(n): float(t) + offset for n, t in re.findall(
        r"PHASE end run=(\d+) monotonic_ms=([\d.]+)", log)}
    for row in rows:
        run = row["run"]
        if run not in starts or run not in ends or ends[run] < starts[run]:
            raise ValueError(f"Missing or invalid phase boundaries for run {run}")
    memory = []
    for file in sorted(directory.glob(pattern)):
        text = file.read_text()
        timestamps = re.findall(r"^\d{18,20}$", text, re.M)
        values = {key: re.search(r"^\s*" + key + r"\s+(\d+)", text, re.M)
                  for key in ("Graph", "Total")}
        # ps and hidumper are separate calls: the completed worker can exit between them.
        # Only exclude explicit process-exit evidence wholly after the final inference.
        pid = re.search(r"^PID (\d+)$", text, re.M)
        exited = pid and re.search(r"^hidumper: No such process: " + pid[1] + r"$", text, re.M)
        if (exited and len(timestamps) == 2 and not any(values.values())
                and int(timestamps[1]) >= int(timestamps[0])
                and int(timestamps[0]) / 1e6 >= ends[len(rows)]):
            warnings.warn(f"Worker exited after final inference; excluded terminal sample: {file}")
            continue
        if baseline and (not pid or pid[1] != baseline[2]):
            raise ValueError("Baseline and inference samples must belong to the same PID")
        # Graph can be absent before loading the NPU runtime; Total PSS is still mandatory.
        if len(timestamps) != 2 or not values['Total'] or (not baseline and not values['Graph']):
            if skip_invalid:
                warnings.warn(f"Skipping incomplete memory sample: {file}")
                continue
            raise ValueError(f"Incomplete memory sample: {file}")
        total_pss = int(values["Total"][1])
        if total_pss <= 0:
            raise ValueError(f"Non-positive PSS Total: {file}")
        start, end = (int(n) / 1e6 for n in timestamps)
        if end < start:
            raise ValueError(f"Reversed memory sample interval: {file}")
        stable = any(start >= starts[r["run"]] + r["ttft_ms"] and
                     end <= ends[r["run"]] for r in rows if r["run"] >= 2)
        memory.append({"file": file.name, "start_epoch_ms": start, "end_epoch_ms": end,
                       "graph_kib": int(values["Graph"][1]) if values["Graph"] else 0,
                       "total_pss_kib": total_pss,
                       "stable_decode": stable,
                       "fully_in_inference": start >= starts[1] and end <= ends[len(rows)]})
        if baseline:
            memory[-1]['baseline_sample'] = start >= bounds[0] and end <= bounds[1]
            memory[-1]['pid'] = int(pid[1])
            memory[-1]['baseline_scope'] = baseline[1]
    return memory


def _finite_kib(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def summarize(rows, memory):
    for sample in memory:
        if 'total_pss_kib' in sample and _finite_kib(sample['total_pss_kib']) and sample['total_pss_kib'] <= 0:
            raise ValueError("Non-positive PSS Total")
    stable = [sample for sample in memory if sample["stable_decode"]]
    inference = [sample for sample in memory if sample["fully_in_inference"]]
    if len(memory) < 2 or not stable or not inference:
        raise ValueError("Insufficient memory samples for interval, stable or inference statistics")
    timing = {}
    for key in ("ttft_ms", "decode_ms", "total_ms", "decode_tps"):
        values = [row[key] for row in rows]
        timing[key] = {"p90": sorted(values)[math.ceil(.9 * len(values)) - 1],
                       "median": statistics.median(values), "min": min(values), "max": max(values)}
    if any('prefill_ms' in row for row in rows):
        values = [row.get('prefill_ms') for row in rows]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
               or v < 0 or v > row['ttft_ms'] for v, row in zip(values, rows)):
            raise ValueError('Incomplete or invalid Prefill timings')
        timing['prefill_ms'] = {'p90': sorted(values)[math.ceil(.9 * len(values)) - 1],
                                'median': statistics.median(values), 'min': min(values), 'max': max(values)}
    result = {}
    for key in ("graph_kib", "total_pss_kib"):
        values = [sample[key] for sample in stable]
        result[key] = {"sampled_peak": max(r[key] for r in memory),
                       "inference_sampled_peak": max(r[key] for r in inference),
                       "stable_median": statistics.median(values),
                       "stable_min": min(values), "stable_max": max(values)}
    result.update(samples=len(memory), stable_samples=len(stable),
                  sample_interval_median_ms=statistics.median([
                      b["start_epoch_ms"] - a["start_epoch_ms"] for a, b in zip(memory, memory[1:])]),
                  total_includes_graph=True)
    if any('baseline_sample' in sample for sample in memory):
        scope = next((s['baseline_scope'] for s in memory if 'baseline_scope' in s), 'before_model_create')
        floor = [sample['total_pss_kib'] for sample in memory if sample['baseline_sample']]
        if len(floor) < 3:
            raise ValueError("At least three complete PSS baseline samples required")
        if any(not _finite_kib(value) for value in floor):
            raise ValueError("PSS baseline sample is not finite")
        baseline = statistics.median(floor)
        spread = max(floor) - min(floor)
        limit = max(2048, baseline * .1)
        unstable = spread > limit
        total = result['total_pss_kib']
        keys = ('sampled_peak', 'inference_sampled_peak', 'stable_median', 'stable_min', 'stable_max')
        if any(not _finite_kib(total[key]) for key in keys):
            raise ValueError("PSS observation is not finite")
        net = {key: total[key] - baseline for key in keys}
        if any(value < 0 for value in net.values()):
            raise ValueError("Negative baseline-subtracted PSS; measurement cannot be accepted")
        result['baseline_pss_kib'] = {'median': baseline, 'min': min(floor), 'max': max(floor),
                                      'samples': len(floor), 'scope': BASELINE_METHODS[scope][1]}
        if not unstable:
            result['net_pss_kib'] = net
            result['ram_method'] = BASELINE_METHODS[scope][0]
        else:
            warnings.warn("PSS baseline is unstable")
            observed = list(floor)
            result['baseline_pss_kib'].update(sample_kib=observed, range_kib=spread,
                                              stability_limit_kib=limit, accepted=False)
            result['quality'] = {'warnings': [{
                'code': 'pss_baseline_unstable',
                'message': 'PSS baseline is unstable',
                'sample_kib': observed,
                'median_kib': baseline,
                'min_kib': min(floor),
                'max_kib': max(floor),
                'samples': len(floor),
                'range_kib': spread,
                'stability_limit_kib': limit,
                'observed_method': BASELINE_METHODS[scope][0],
                'net_pss_kib': 'not_calculated',
            }]}
    return timing, result


def write_csv(directory, rows, memory):
    for name, data in (("samples.csv", rows), ("memory.csv", memory)):
        with (directory / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
