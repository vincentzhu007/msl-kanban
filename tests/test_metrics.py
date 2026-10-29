"""Regression coverage against original device evidence, without phone access."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from bench_common.metrics import validate_rows, read_memory, summarize

CASES = [
    ("scripts/edge_slm_bench/summarize_2k.py", "reports/edge-slm/20261026-qwen25-05b-w4a16-9020/context2048-input1024-output128"),
    ("scripts/edge_slm_bench/summarize_qwen3.py", "reports/qwen3-9030-daily-20261026/pr-validation/results-aligned"),
    ("scripts/edge_llama_bench/summarize.py", "reports/edge-slm/20261026-llama-q40-cpu9020"),
]


class MeasurementTests(unittest.TestCase):
    def test_archived_results_are_unchanged(self):
        for script, fixture in CASES:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "results"
                shutil.copytree(ROOT / fixture, target)
                expected = json.loads((target / "benchmark.json").read_text())
                subprocess.run([sys.executable, str(ROOT / script), str(target)], check=True, stdout=subprocess.DEVNULL)
                actual = json.loads((target / "benchmark.json").read_text())
                self.assertEqual(expected, actual)

    def test_rejects_duplicate_or_failed_runs_even_under_optimization(self):
        rows = json.loads((ROOT / CASES[1][1] / "samples.json").read_text())
        for field, value in (("run", 1), ("status", 1), ("output_callbacks", 127), ("ttft_ms", float('nan'))):
            invalid = copy.deepcopy(rows)
            invalid[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_rows(invalid)

    def test_only_excludes_process_exit_after_final_inference(self):
        wall = 1700000000000
        log = f"WALL_MS {wall} MONOTONIC_MS 0\nPHASE inference run=1 monotonic_ms=0\nPHASE end run=1 monotonic_ms=1000"
        rows = [{'run': 1, 'ttft_ms': 100}]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'memory-0001.txt'
            def write_sample(start):
                path.write_text(f"PID 123\n{start * 1000000}\nhidumper: No such process: 123\n{(start + 10) * 1000000}\n")
            write_sample(wall + 1001)
            with self.assertWarnsRegex(UserWarning, 'exited after final'):
                self.assertEqual(read_memory(Path(tmp), log, rows), [])
            write_sample(wall + 999)
            with self.assertRaisesRegex(ValueError, 'Incomplete memory'):
                read_memory(Path(tmp), log, rows)
            path.write_text(f"PID 123\n{(wall + 1001) * 1000000}\nother error\n{(wall + 1011) * 1000000}\n")
            with self.assertRaisesRegex(ValueError, 'Incomplete memory'):
                read_memory(Path(tmp), log, rows)

    def test_ten_runs_p90_and_count_validation(self):
        rows = [dict(run=i, status=0, output_callbacks=128, input_tokens=1024,
                     eog_tokens=0, ttft_ms=i, decode_ms=i, total_ms=i*2, decode_tps=i)
                for i in range(1, 11)]
        validate_rows(rows, backend="llama", count=10)
        with self.assertRaises(ValueError):
            validate_rows(rows[:5], backend="llama", count=10)
        memory = [dict(stable_decode=True, fully_in_inference=True,
                       graph_kib=10, total_pss_kib=20, start_epoch_ms=i) for i in (1, 2)]
        timing, _ = summarize(rows, memory)
        self.assertEqual(timing['decode_ms']['p90'], 9)

    def test_requires_device_clock_alignment(self):
        with self.assertRaisesRegex(ValueError, "clock alignment"):
            read_memory(Path("."), "", [])


if __name__ == "__main__":
    unittest.main()
