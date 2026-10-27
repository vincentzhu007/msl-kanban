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
from bench_common.metrics import validate_rows, read_memory

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

    def test_requires_device_clock_alignment(self):
        with self.assertRaisesRegex(ValueError, "clock alignment"):
            read_memory(Path("."), "", [])


if __name__ == "__main__":
    unittest.main()
