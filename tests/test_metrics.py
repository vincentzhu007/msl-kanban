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
from bench_common.metrics import validate_rows, read_memory, summarize, initialization

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

    def test_optional_stage_timings(self):
        self.assertIsNone(initialization('BUILD ms=123'))
        self.assertEqual(initialization('INIT {"model_init_ms": 123}')['samples'], 1)
        for log in ['INIT {"model_init_ms": -1}', 'INIT {"model_init_ms": true}',
                    'INIT {"model_init_ms": 1}\nINIT {"model_init_ms": 2}']:
            with self.assertRaises(ValueError):
                initialization(log)
        rows = [dict(prefill_ms=i, ttft_ms=i+1, decode_ms=2, total_ms=i+3, decode_tps=10)
                for i in range(1, 11)]
        memory = [dict(stable_decode=True, fully_in_inference=True, graph_kib=1,
                       total_pss_kib=2, start_epoch_ms=i) for i in (1, 2)]
        self.assertEqual(summarize(rows, memory)[0]['prefill_ms']['p90'], 9)
        rows[0]['prefill_ms'] = 100
        with self.assertRaises(ValueError):
            summarize(rows, memory)
        rows[0].pop('prefill_ms')
        with self.assertRaises(ValueError):
            summarize(rows, memory)

    def test_requires_device_clock_alignment(self):
        with self.assertRaisesRegex(ValueError, "clock alignment"):
            read_memory(Path("."), "", [])


if __name__ == "__main__":
    unittest.main()

class BaselinePssTests(unittest.TestCase):
    def samples(self):
        return [dict(stable_decode=i>=3, fully_in_inference=i>=3,
                     graph_kib=0 if i<3 else 50, total_pss_kib=v,
                     start_epoch_ms=i*1000, baseline_sample=i<3, pid=12,
                     baseline_scope='before_model_create')
                for i,v in enumerate([100,102,98,200,220])]

    def test_subtracts_median_and_preserves_raw(self):
        _, stats=summarize([dict(ttft_ms=1,decode_ms=1,total_ms=2,decode_tps=1)],self.samples())
        self.assertEqual(stats['baseline_pss_kib']['median'],100)
        self.assertEqual(stats['total_pss_kib']['stable_median'],210)
        self.assertEqual(stats['net_pss_kib']['stable_median'],110)
        self.assertEqual(stats['net_pss_kib']['sampled_peak'],120)

    def test_requires_enough_baseline_samples(self):
        samples=self.samples();samples[0]['baseline_sample']=False
        with self.assertRaisesRegex(ValueError,'three complete'):
            summarize([dict(ttft_ms=1,decode_ms=1,total_ms=2,decode_tps=1)],samples)

    def test_rejects_negative_net_values(self):
        samples=self.samples()
        for s in samples[3:]:s['total_pss_kib']=90
        with self.assertRaisesRegex(ValueError,'Negative'):
            summarize([dict(ttft_ms=1,decode_ms=1,total_ms=2,decode_tps=1)],samples)

    def test_baseline_scope_describes_model_create(self):
        _, stats=summarize([dict(ttft_ms=1,decode_ms=1,total_ms=2,decode_tps=1)],self.samples())
        self.assertIn('MSLLMCreateModel', stats['baseline_pss_kib']['scope'])
        self.assertNotIn('dlopen', stats['baseline_pss_kib']['scope'])

    def test_reads_before_model_create_baseline_from_log(self):
        wall = 1700000000000.0
        log = (
            f"WALL_MS {wall} MONOTONIC_MS 0\n"
            "MEMORY_BASELINE scope=before_model_create pid=42\n"
            "PHASE baseline_start monotonic_ms=0\n"
            "PHASE baseline_end monotonic_ms=20000\n"
            "PHASE inference run=1 monotonic_ms=21000\n"
            "PHASE end run=1 monotonic_ms=22000\n"
            "PHASE inference run=2 monotonic_ms=23000\n"
            "PHASE end run=2 monotonic_ms=25000\n"
        )
        rows = [dict(run=1, ttft_ms=100), dict(run=2, ttft_ms=200)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # three baseline samples inside (start+2s, end] = (2000, 20000] wall-aligned
            for i, (start, total) in enumerate([(3000, 100), (8000, 102), (15000, 98)]):
                (root / f'memory-{i:04d}.txt').write_text(
                    f"PID 42\n{int((wall+start)*1e6)}\n  Total  {total}\n{int((wall+start+10)*1e6)}\n")
            # one stable decode sample in run 2 decode window: start>=23000+200 and end<=25000
            (root / 'memory-0003.txt').write_text(
                f"PID 42\n{int((wall+23250)*1e6)}\n  Graph  50\n  Total  210\n{int((wall+23260)*1e6)}\n")
            memory = read_memory(root, log, rows)
            self.assertTrue(any(s.get('baseline_sample') for s in memory))
            self.assertEqual(sum(1 for s in memory if s.get('baseline_sample')), 3)

    def write_log(self, root, scope):
        wall = 1700000000000.0
        log = (f"WALL_MS {wall} MONOTONIC_MS 0\n"
               f"MEMORY_BASELINE scope={scope} pid=42\n"
               "PHASE baseline_start monotonic_ms=0\nPHASE baseline_end monotonic_ms=20000\n"
               "PHASE inference run=1 monotonic_ms=21000\nPHASE end run=1 monotonic_ms=22000\n"
               "PHASE inference run=2 monotonic_ms=23000\nPHASE end run=2 monotonic_ms=25000\n")
        for i, (start, total) in enumerate([(3000, 100), (8000, 102), (15000, 98)]):
            (root / f'memory-{i:04d}.txt').write_text(
                f"PID 42\n{int((wall+start)*1e6)}\n  Total  {total}\n{int((wall+start+10)*1e6)}\n")
        (root / 'memory-0003.txt').write_text(
            f"PID 42\n{int((wall+21100)*1e6)}\n  Graph  50\n  Total  200\n{int((wall+21200)*1e6)}\n")
        (root / 'memory-0004.txt').write_text(
            f"PID 42\n{int((wall+23250)*1e6)}\n  Graph  50\n  Total  210\n{int((wall+23260)*1e6)}\n")
        return log

    def stats_for(self, scope):
        rows = [dict(run=1, ttft_ms=100, decode_ms=1, total_ms=2, decode_tps=1),
                dict(run=2, ttft_ms=200, decode_ms=1, total_ms=2, decode_tps=1)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            return summarize(rows, read_memory(root, self.write_log(root, scope), rows))[1]

    def test_methods_are_versioned_per_scope(self):
        new = self.stats_for('before_model_create')
        old = self.stats_for('before_runtime_load')
        self.assertEqual(new['ram_method'], 'pre-model-create-pss-v1')
        # Legacy logs keep their baseline under the old method id.
        self.assertEqual(old['ram_method'], 'pre-runtime-pss-v1')
        self.assertEqual(old['net_pss_kib']['stable_median'], 110)
        self.assertIn('dlopen', old['baseline_pss_kib']['scope'])

    def test_declared_baseline_is_enforced_without_marker(self):
        from recipe_ci.results import require_declared_baseline
        lock = {'ram_baseline': 'pre-model-create-pss-v1', 'environment': {'artifacts': {}}}
        with self.assertRaisesRegex(Exception, 'missing from probe log'):
            require_declared_baseline(lock, {})
        with self.assertRaisesRegex(Exception, 'method mismatch'):
            require_declared_baseline(lock, {'net_pss_kib': {}, 'ram_method': 'pre-runtime-pss-v1'})
        require_declared_baseline(lock, self.stats_for('before_model_create'))
        legacy = {'environment': {'artifacts': {'runtime_so': {}}}}
        with self.assertRaisesRegex(Exception, 'missing from probe log'):
            require_declared_baseline(legacy, {})
        require_declared_baseline({'environment': {'artifacts': {}}}, {})
