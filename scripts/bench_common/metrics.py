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


def read_memory(directory, log, rows, pattern="memory-*.txt", skip_invalid=False):
    clock = re.search(r"WALL_MS ([\d.]+) MONOTONIC_MS ([\d.]+)", log)
    if not clock:
        raise ValueError("Missing device wall/monotonic clock alignment")
    wall, monotonic = map(float, clock.groups())
    offset = wall - monotonic
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
        if len(timestamps) != 2 or not all(values.values()):
            if skip_invalid:
                warnings.warn(f"Skipping incomplete memory sample: {file}")
                continue
            raise ValueError(f"Incomplete memory sample: {file}")
        start, end = (int(n) / 1e6 for n in timestamps)
        if end < start:
            raise ValueError(f"Reversed memory sample interval: {file}")
        stable = any(start >= starts[r["run"]] + r["ttft_ms"] and
                     end <= ends[r["run"]] for r in rows if r["run"] >= 2)
        memory.append({"file": file.name, "start_epoch_ms": start, "end_epoch_ms": end,
                       "graph_kib": int(values["Graph"][1]),
                       "total_pss_kib": int(values["Total"][1]),
                       "stable_decode": stable,
                       "fully_in_inference": start >= starts[1] and end <= ends[len(rows)]})
    return memory


def summarize(rows, memory):
    stable = [sample for sample in memory if sample["stable_decode"]]
    inference = [sample for sample in memory if sample["fully_in_inference"]]
    if len(memory) < 2 or not stable or not inference:
        raise ValueError("Insufficient memory samples for interval, stable or inference statistics")
    timing = {}
    for key in ("ttft_ms", "decode_ms", "total_ms", "decode_tps"):
        values = [row[key] for row in rows]
        timing[key] = {"p90": sorted(values)[math.ceil(.9 * len(values)) - 1],
                       "median": statistics.median(values), "min": min(values), "max": max(values)}
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
    return timing, result


def write_csv(directory, rows, memory):
    for name, data in (("samples.csv", rows), ("memory.csv", memory)):
        with (directory / name).open("w", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]))
            writer.writeheader()
            writer.writerows(data)
