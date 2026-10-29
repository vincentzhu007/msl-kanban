import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from recipe_ci.recipe import load, validate, RecipeError, comparison_key
from recipe_ci.planner import resolve, load_lock, write_new
from recipe_ci.results import summarize_recipe, validate_spec
from recipe_ci.execution import execute, device_lease

RECIPE = ROOT / 'recipes/qwen3-4b-msl-s16s4-kirin9030.json'


class RecipeTests(unittest.TestCase):
    def test_all_recipes_validate(self):
        for path in (ROOT / 'recipes').glob('*.json'):
            self.assertEqual(load(path)['schema_version'], 1)

    def test_invalid_specs_fail_closed(self):
        for mutation in [
            lambda r: r['workload'].update(output_tokens=2000),
            lambda r: r['workload'].update(input_tokens=512),
            lambda r: r['backend'].update(name='unknown'),
            lambda r: r['build'].update(commit='daily'),
            lambda r: r.update(preparation='rebuild_model'),
            lambda r: r['workload'].update(repetitons=10),
        ]:
            recipe = load(RECIPE)
            mutation(recipe)
            with self.assertRaises(RecipeError):
                validate(recipe)

    def test_build_changes_do_not_change_comparison_key(self):
        recipe = load(RECIPE)
        changed = copy.deepcopy(recipe)
        changed['build']['commit'] = 'a' * 40
        self.assertEqual(comparison_key(recipe), comparison_key(changed))
        changed['model']['variant'] = 'instruct'
        self.assertNotEqual(comparison_key(recipe), comparison_key(changed))

    def test_preview_cannot_execute_and_tampering_is_detected(self):
        env = json.loads((ROOT / 'config/dog-kirin9030.example.json').read_text())
        lock = resolve(load(RECIPE), env, verify_files=False)
        with self.assertRaisesRegex(RecipeError, 'preview lock'):
            execute(lock)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'lock.json'
            write_new(path, lock)
            self.assertEqual(load_lock(path), lock)
            with self.assertRaises(FileExistsError):
                write_new(path, lock)
            lock['command_template'][0] = 'changed'
            path.write_text(json.dumps(lock))
            with self.assertRaisesRegex(RecipeError, 'changed'):
                load_lock(path)

    def test_actual_probe_spec_must_match(self):
        recipe = load(RECIPE)
        event = {'protocol_version': 1, **{k: recipe['workload'][k] for k in
                 ['context_tokens', 'input_tokens', 'output_tokens', 'repetitions']}}
        validate_spec('SPEC ' + json.dumps(event), recipe['workload'], {})
        event['output_tokens'] = 127
        with self.assertRaisesRegex(RecipeError, 'output_tokens'):
            validate_spec('SPEC ' + json.dumps(event), recipe['workload'], {})

    def test_device_lease_excludes_second_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            with device_lease(Path(tmp), 'test'):
                with self.assertRaises(RuntimeError):
                    with device_lease(Path(tmp), 'test'):
                        pass
            with device_lease(Path(tmp), 'test'):
                pass

    def test_legacy_import_matches_all_existing_metrics(self):
        cases = [
            ('qwen25-05b-msl-w4a16-kirin9020', 'reports/edge-slm/20261026-qwen25-05b-w4a16-9020/context2048-input1024-output128',
             {'log_name': 'five-aligned.log', 'samples_name': 'five-aligned-samples.json', 'memory_pattern': 'five-aligned-memory-*.txt'}),
            ('qwen25-05b-llama-q40-kirin9020', 'reports/edge-slm/20261026-llama-q40-cpu9020', {}),
            ('qwen3-4b-msl-s16s4-kirin9030', 'reports/qwen3-9030-daily-20261026/pr-validation/results-aligned', {}),
        ]
        for name, fixture, options in cases:
            with self.subTest(recipe=name), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / 'data'
                shutil.copytree(ROOT / fixture, target)
                old = json.loads((target / 'benchmark.json').read_text())
                recipe = load(ROOT / 'recipes' / (name + '.json'))
                # Preserve the archived five-run protocol for legacy evidence.
                recipe['workload']['repetitions'] = 5
                recipe['measurement']['stable_runs'] = list(range(2, 6))
                result = summarize_recipe(recipe, target, legacy=True, **options)
                self.assertEqual(result['timing'], old['timing'])
                for key in ['graph_kib', 'total_pss_kib', 'samples', 'stable_samples', 'sample_interval_median_ms']:
                    self.assertEqual(result['memory'][key], old['memory'][key])
                self.assertFalse(result['baseline_eligible'])
