import io
import json
import os
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from daily_ci.pipeline import DeviceOfflineError, device_output, select_build, safe_extract, download, public_result, run, ensure_forward, record_blocked, prepare_llama
from recipe_ci.recipe import comparison_key, load


class DailyTests(unittest.TestCase):
    def test_discovery_only_accepts_requested_day_master(self):
        day = '20261028'
        early = 'master_' + day + '010015_' + 'a' * 40 + '_newest/'
        late = 'master_' + day + '160013_' + 'b' * 40 + '_newest/'
        html = ''.join(f'<a href="{x}">build</a>' for x in [early, late, '../', 'https://evil/' + late])
        self.assertEqual(select_build(html, day)[1], 'b' * 40)
        self.assertIsNone(select_build(html, '20261029'))

    def test_archive_rejects_traversal_and_symlinks(self):
        for name, kind in [('../outside', tarfile.REGTYPE), ('pkg/link', tarfile.SYMTYPE)]:
            with tempfile.TemporaryDirectory() as tmp:
                archive = Path(tmp) / 'package.tar.gz'
                with tarfile.open(archive, 'w:gz') as bundle:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    bundle.addfile(member)
                with self.assertRaises(ValueError):
                    safe_extract(archive, Path(tmp) / 'out')

    def test_checksum_failure_does_not_cache_package(self):
        with tempfile.TemporaryDirectory() as tmp, patch('daily_ci.pipeline.urlopen', return_value=io.BytesIO(b'corrupt')):
            with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
                download({'source_url':'https://example.invalid/package', 'sha256':'a'*64}, Path(tmp))
            self.assertFalse(list(Path(tmp).rglob('*.tar.gz')))

    def test_no_build_and_failure_write_status_but_no_results(self):
        for found in [None, RuntimeError('private path details')]:
            with tempfile.TemporaryDirectory() as tmp:
                repo=Path(tmp)/'repo'; repo.mkdir()
                config=json.loads((ROOT/'config/daily-qwen25-9020.example.json').read_text())
                config['archive_root']=str(Path(tmp)/'archive')
                with patch('daily_ci.pipeline.run_command'), patch('daily_ci.pipeline.subprocess.check_output', return_value='c'*40), patch('daily_ci.pipeline.discover') as discover:
                    if isinstance(found, Exception): discover.side_effect=found
                    else: discover.return_value=found
                    code=run(repo,ROOT/'recipes/qwen25-05b-msl-w4a16-kirin9020.json',config,'20261028')
                status=json.loads(next((repo/'kanban/jobs').glob('*.json')).read_text())
                self.assertEqual(status['status'], 'NO_BUILD' if found is None else 'FAILED')
                self.assertEqual(code, 0 if found is None else 1)
                self.assertNotIn('private path details', json.dumps(status))
                self.assertFalse((repo/'kanban/data').exists())

    def test_forward_replaces_wrong_device_port_with_separate_arguments(self):
        env = {'device': {'serial': 'phone', 'port': '18888'}}
        with patch('daily_ci.pipeline.subprocess.check_output', side_effect=[
                'phone tcp:18888 tcp:18888 [Forward]',
                'phone tcp:18888 tcp:8888 [Forward]']), \
             patch('daily_ci.pipeline.subprocess.run') as remove, \
             patch('daily_ci.pipeline.subprocess.Popen') as create:
            ensure_forward(env, 8888)
        self.assertEqual(remove.call_args.args[0][-3:], ['rm', 'tcp:18888', 'tcp:18888'])
        self.assertEqual(create.call_args.args[0][-2:], ['tcp:18888', 'tcp:8888'])

    def test_forward_preserves_other_device_mapping(self):
        with patch('daily_ci.pipeline.subprocess.check_output', return_value='other tcp:18888 tcp:8888'), \
             patch('daily_ci.pipeline.subprocess.run') as remove:
            with self.assertRaisesRegex(ValueError, 'another device'):
                ensure_forward({'device': {'serial': 'phone', 'port': '18888'}}, 8888)
        remove.assert_not_called()

    def test_blocked_task_records_status_without_performance(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/'repo'; repo.mkdir()
            config={'task_id':'cann-kit-llm-kirin9020', 'archive_root':str(Path(tmp)/'archive'), 'blocked':'Missing SDK'}
            with patch('daily_ci.pipeline.subprocess.check_output', return_value='c'*40):
                self.assertEqual(record_blocked(repo,config,'20261029'),0)
            status=json.loads(next((repo/'kanban/jobs').glob('*.json')).read_text())
            self.assertEqual(status['status'],'BLOCKED')
            self.assertEqual(status['reason'],'Missing SDK')
            self.assertFalse((repo/'kanban/data').exists())

    def test_task_ids_do_not_collide_across_models_in_same_workflow(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo=Path(tmp)/'repo'; repo.mkdir()
            config=json.loads((ROOT/'config/daily-qwen25-9020.example.json').read_text())
            config['archive_root']=str(Path(tmp)/'archive')
            with patch.dict('os.environ', {'GITHUB_RUN_ID':'123','GITHUB_RUN_ATTEMPT':'1'}), \
                 patch('daily_ci.pipeline.run_command'), \
                 patch('daily_ci.pipeline.subprocess.check_output', return_value='c'*40), \
                 patch('daily_ci.pipeline.discover', return_value=None):
                for name in ['qwen25-05b-msl-w4a16-kirin9020','qwen3-4b-msl-s16s4-kirin9030']:
                    self.assertEqual(run(repo,ROOT/'recipes'/ (name+'.json'),config,'20261029'),0)
            self.assertEqual(len(list((repo/'kanban/jobs').glob('*.json'))),2)

    def test_llama_source_checksum_checked_before_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive=Path(tmp)/'source'; archive.write_bytes(b'bad')
            config={'environment':{'artifacts':{'runtime':{'host_path':str(archive)}}}}
            with patch('daily_ci.pipeline.run_command') as command, self.assertRaisesRegex(ValueError,'checksum mismatch'):
                prepare_llama(ROOT,config,{'sha256':'0'*64},Path(tmp))
            command.assert_not_called()

    def test_daily_display_date_uses_beijing_measurement_day(self):
        from datetime import datetime, timezone
        epoch=datetime(2026,10,28,19,0,tzinfo=timezone.utc).timestamp()*1000
        result={'model':{}, 'memory_samples':[{'start_epoch_ms':epoch}], 'date':'2026-10-28'}
        public=public_result(result,'run',{},'c'*40,'device',None)
        self.assertEqual(public['date'],'2026-10-29')

    def test_public_result_omits_private_model_paths(self):
        result={'model':{'name':'Qwen','provenance':{'source':'/private/path'}}, 'device':'serial'}
        public=public_result(result,'run',{'commit':'a'*40},'b'*40,'dog-kirin9020',None)
        self.assertNotIn('provenance',public['model'])
        self.assertEqual(public['device'],'dog-kirin9020')
        self.assertIn('provenance',result['model'])

    def _drive_until_export(self, tmp, export_side_effect, discover_result=None):
        repo = Path(tmp) / 'repo'
        repo.mkdir()
        source = Path(tmp) / 'source'
        source.mkdir()
        (source / 'config.json').write_text('{}')
        (source / 'model.safetensors').write_bytes(b'weights')
        config = json.loads((ROOT / 'config/daily-qwen25-9020.example.json').read_text())
        root = Path(tmp) / 'archive'
        config['archive_root'] = str(root)
        config['model_generation'] = {
            'mode': 'master_daily', 'source_model': str(source), 'quant_type': 'q4_0'}
        historical = root / 'tasks' / 'daily-20261127-qwen3-4b-msl-s16s4-kirin9030-45932557883-1'
        historical.mkdir(parents=True)
        (historical / '.msl_export_historical').mkdir()
        (historical / 'model.msl').write_bytes(b'.MSL' + b'historical')
        (root / 'packages' / 'abc').mkdir(parents=True)
        (root / 'packages' / 'abc' / 'package.tar.gz').write_bytes(b'cached')
        (root / 'runs' / 'old').mkdir(parents=True)
        (root / 'runs' / 'old' / 'sample.csv').write_text('ok\n')

        def check_output(command, **kwargs):
            if command[0] == 'git':
                return 'c' * 40 + '\n'
            raise RuntimeError('toolchain failed')

        def prepare(repo, config, build, task, cache):
            probe = task / 'recipe-msl'
            probe.write_bytes(b'probe')
            return root / 'packages' / 'abc' / 'package.tar.gz', probe

        found = discover_result
        if found is None:
            found = {'commit': 'a' * 40, 'source_url': 'https://example.invalid/package', 'sha256': 'b' * 64}
        with patch('daily_ci.pipeline.run_command'), \
             patch('daily_ci.pipeline.subprocess.check_output', side_effect=check_output), \
             patch('daily_ci.pipeline.discover', return_value=found), \
             patch('daily_ci.pipeline.device_output', return_value='OpenHarmony-6.1.1.120'), \
             patch('daily_ci.pipeline.prepare_msl', side_effect=prepare), \
             patch('daily_ci.pipeline.export_model', side_effect=export_side_effect):
            code = run(repo, ROOT / 'recipes/qwen25-05b-msl-w4a16-kirin9020.json', config, '20261128')
        tasks = [path for path in (root / 'tasks').iterdir() if path != historical]
        self.assertEqual(len(tasks), 1)
        return code, tasks[0], historical, root

    def test_failed_export_drops_partial_model_before_the_next_recipe(self):
        with tempfile.TemporaryDirectory() as tmp:
            outside = Path(tmp) / 'assets'
            outside.mkdir()
            (outside / 'model.safetensors').write_bytes(b'weights')

            def explode(repo, recipe, env, config, task, build, run_command, write_json):
                work = task / '.msl_export_lljk7il0'
                work.mkdir()
                (work / 'weights').symlink_to(outside / 'model.safetensors')
                (task / 'ddk').mkdir()
                (task / 'ddk-source').mkdir()
                (task / 'python').mkdir()
                (task / 'package').mkdir()
                (task / 'model.msl').write_bytes(b'.MSL' + b'\x00' * 4096)
                (task / 'export.log').write_text('OSError: [Errno 28] No space left on device\n')
                (task / 'generated-model.json').write_text('{}\n')
                raise RuntimeError('No space left on device')

            code, task, historical, root = self._drive_until_export(tmp, explode)
            self.assertEqual(code, 1)
            self.assertFalse((task / 'model.msl').exists())
            self.assertFalse((task / '.msl_export_lljk7il0').exists())
            for name in ['ddk', 'ddk-source', 'python', 'package']:
                self.assertFalse((task / name).exists(), name)
            self.assertTrue((task / 'error.txt').is_file())
            self.assertIn('No space left on device', (task / 'error.txt').read_text())
            self.assertEqual((task / 'generated-model.json').read_text(), '{}\n')
            record = json.loads((task / 'cleanup.json').read_text())
            self.assertFalse(record['retain_requested'])
            self.assertFalse(record['model_kept'])
            self.assertEqual((outside / 'model.safetensors').read_bytes(), b'weights')
            self.assertTrue((historical / '.msl_export_historical').is_dir())
            self.assertTrue((historical / 'model.msl').is_file())
            self.assertEqual((root / 'packages' / 'abc' / 'package.tar.gz').read_bytes(), b'cached')
            self.assertEqual((root / 'runs' / 'old' / 'sample.csv').read_text(), 'ok\n')
            status = json.loads(next((Path(tmp) / 'repo' / 'kanban' / 'jobs').glob('*.json')).read_text())
            self.assertEqual((status['status'], status['stage']), ('FAILED', 'EXPORT_MODEL'))

    def test_later_failure_keeps_the_model_export_already_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            def accepted(repo, recipe, env, config, task, build, run_command, write_json):
                (task / '.msl_export_ok').mkdir()
                (task / 'ddk').mkdir()
                (task / 'package').mkdir()
                model = task / 'model.msl'
                model.write_bytes(b'.MSL' + b'accepted-model-payload')
                os.link(model, task / 'daily-qwen25-05b-msl-w4a16-kirin9020.msl')
                (task / 'extra.msl').write_bytes(b'.MSL' + b'not-the-result-file')
                (task / 'export.log').write_text('export finished\n')
                return recipe, {'exporter': {'filename': 'wheel', 'sha256': 'd' * 64}}

            code, task, historical, root = self._drive_until_export(tmp, accepted)
            self.assertEqual(code, 1)
            self.assertEqual((task / 'model.msl').read_bytes(), b'.MSL' + b'accepted-model-payload')
            self.assertTrue((task / 'daily-qwen25-05b-msl-w4a16-kirin9020.msl').is_file())
            self.assertFalse((task / 'extra.msl').exists())
            self.assertFalse((task / '.msl_export_ok').exists())
            self.assertFalse((task / 'ddk').exists())
            self.assertFalse((task / 'package').exists())
            self.assertFalse((task / 'export.log').exists())
            self.assertTrue((task / 'export.log.gz').is_file())
            self.assertTrue((task / 'recipe-msl').is_file())
            record = json.loads((task / 'cleanup.json').read_text())
            self.assertTrue(record['retain_requested'])
            self.assertTrue(record['model_kept'])
            self.assertTrue((historical / 'model.msl').is_file())
            status = json.loads(next((Path(tmp) / 'repo' / 'kanban' / 'jobs').glob('*.json')).read_text())
            self.assertEqual(status['status'], 'FAILED')
            self.assertNotIn('private', json.dumps(status))


class DeviceOutputTests(unittest.TestCase):
    ENV = {'device': {'serial': 'device'}}

    def completed(self, stdout, stderr=''):
        import subprocess
        return subprocess.CompletedProcess(['hdc'], 0, stdout, stderr)

    def test_hdc_fail_on_stdout_is_device_offline_not_os_mismatch(self):
        with patch('daily_ci.pipeline.subprocess.run',
                   return_value=self.completed('[Fail][E001005] Device not found or connected\n')):
            with self.assertRaisesRegex(DeviceOfflineError, 'E001005'):
                device_output(self.ENV, ['param', 'get', 'const.ohos.fullname'])

    def test_hdc_fail_on_stderr_is_device_offline(self):
        with patch('daily_ci.pipeline.subprocess.run',
                   return_value=self.completed('', '[Fail]Connect failed\n')):
            with self.assertRaises(DeviceOfflineError):
                device_output(self.ENV, ['ps', '-A'])

    def test_normal_output_is_returned_stripped(self):
        with patch('daily_ci.pipeline.subprocess.run',
                   return_value=self.completed('OpenHarmony-6.1.1.120\n')):
            self.assertEqual(device_output(self.ENV, ['param', 'get', 'const.ohos.fullname']),
                             'OpenHarmony-6.1.1.120')


class Qwen2515BDailyTests(unittest.TestCase):
    TASKS = {
        'qwen25-15b-msl-w4a16-kirin9020': {
            'quant': 'q4_0',
            'source': '/assets/source-models/Qwen2.5-1.5B-Instruct',
            'mode': 'master_daily',
            'reference': 'qwen25-05b-msl-w4a16-kirin9020',
        },
        'qwen25-15b-msl-q30-kirin9020': {
            'quant': 'q3_0',
            'source': '/assets/source-models/Qwen2.5-1.5B-Instruct',
            'mode': 'master_daily',
            'reference': 'qwen25-05b-msl-q30-kirin9020',
        },
    }
    SENTINEL_SHA = '0' * 64
    SENTINEL_COMMIT = '0' * 40

    def test_recipes_keep_separate_quant_and_source(self):
        loaded = {}
        for task_id, expect in self.TASKS.items():
            recipe = load(ROOT / 'recipes' / (task_id + '.json'))
            reference = load(ROOT / 'recipes' / (expect['reference'] + '.json'))
            task = json.loads((ROOT / 'config/daily' / (task_id + '.json')).read_text())
            self.assertEqual(recipe['model']['quantization'], reference['model']['quantization'])
            self.assertEqual(recipe['model']['quantization']['format'], expect['quant'])
            self.assertEqual(task['model_generation']['quant_type'], expect['quant'])
            self.assertEqual(task['model_generation']['mode'], expect['mode'])
            self.assertEqual(task['model_generation']['source_model'], expect['source'])
            work = recipe['workload']
            self.assertEqual((work['context_tokens'], work['input_tokens'], work['output_tokens'], work['repetitions']),
                             (2048, 1024, 128, 10))
            self.assertEqual(recipe['model']['sha256'], self.SENTINEL_SHA)
            self.assertEqual(recipe['build']['commit'], self.SENTINEL_COMMIT)
            loaded[task_id] = (recipe, task)
        w4, q3 = loaded['qwen25-15b-msl-w4a16-kirin9020'], loaded['qwen25-15b-msl-q30-kirin9020']
        self.assertNotEqual(w4[0]['model']['quantization']['format'], q3[0]['model']['quantization']['format'])
        self.assertNotEqual(comparison_key(w4[0]), comparison_key(q3[0]))
        self.assertEqual(w4[1]['model_generation']['source_model'], q3[1]['model_generation']['source_model'])
        self.assertEqual(w4[1]['model_generation']['mode'], 'master_daily')
        self.assertEqual(q3[1]['model_generation']['mode'], 'master_daily')
        self.assertNotEqual(w4[1]['model_generation']['quant_type'], q3[1]['model_generation']['quant_type'])

    def listed_tasks(self, workflow, header):
        lines = workflow.splitlines()
        start = lines.index(header)
        items = []
        for line in lines[start + 1:]:
            if line.startswith('          - '):
                items.append(line[12:])
            elif line.strip():
                break
        return items

    def test_schedule_matches_blocked_or_enabled_contract(self):
        from daily_ci.workflow_tasks import ORIGINAL_FIVE, SCHEDULED
        workflow = (ROOT / '.github/workflows/daily-qwen25-9020.yml').read_text()
        options = self.listed_tasks(workflow, '        options:')
        declared = workflow.split('DAILY_SCHEDULED_TASKS:', 1)[1].splitlines()[0].strip().split()
        self.assertEqual(tuple(declared), SCHEDULED)
        self.assertEqual(SCHEDULED[:5], ORIGINAL_FIVE)
        self.assertIn("cron: '0 19 * * *'", workflow)
        self.assertIn('fromJSON(needs.select.outputs.tasks)', workflow)
        states = []
        public = []
        for task_id, expect in self.TASKS.items():
            task = json.loads((ROOT / 'config/daily' / (task_id + '.json')).read_text())
            listed = task_id in options and task_id in SCHEDULED
            withheld = task_id not in options and task_id not in SCHEDULED
            prepared = 'blocked' in task and bool(task['blocked']) and withheld
            enabled = 'blocked' not in task and listed
            self.assertTrue(prepared or enabled)
            self.assertEqual(task_id in options, task_id in SCHEDULED)
            self.assertEqual(task['model_generation']['quant_type'], expect['quant'])
            self.assertEqual(task['model_generation']['source_model'], expect['source'])
            for absent in ('activation', 'device_alias', 'environment', 'required_build_commit'):
                self.assertNotIn(absent, task)
            states.append(prepared)
            public.append((ROOT / 'config/daily' / (task_id + '.json')).read_text())
            public.append((ROOT / 'recipes' / (task_id + '.json')).read_text())
        self.assertEqual(len(set(states)), 1)
        self.assertFalse(states[0])
        blob = '\n'.join(public)
        self.assertNotRegex(blob, r'(?i)dog|/home/|\d{1,3}(?:\.\d{1,3}){3}')
        for forbidden in ('external_gguf', 'e4a9c657', '711013248', 'e464a610',
                          '6868d15f1805e036c2ab2f4a4ca15a24189a7475741f78f78f0de5aeab602d5b',
                          '44ee68d8d34ea39ac21d6a23209a3b8c96899aba79e90ed207ccbab4833205e8',
                          '05c304249884d7674a415442eb437042844a53745e3a73f9d66f2c4f6ee438a1',
                          '29e904924e12e4bc351f9b99569602f1fd2bb7b2a8cf4ea3c160866ca795b046'):
            self.assertNotIn(forbidden, blob)

    def test_synthetic_blocked_config_records_status_without_performance(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            config = {'archive_root': str(Path(tmp) / 'archive'),
                      'task_id': 'synthetic-blocked-task',
                      'blocked': 'synthetic prerequisite'}
            with patch('daily_ci.pipeline.subprocess.check_output', return_value='c' * 40):
                self.assertEqual(record_blocked(repo, config, '20261116'), 0)
            status = json.loads(next((repo / 'kanban/jobs').glob('*.json')).read_text())
            self.assertEqual(status['status'], 'BLOCKED')
            self.assertEqual(status['recipe_id'], 'synthetic-blocked-task')
            self.assertEqual(status['reason'], 'synthetic prerequisite')
            self.assertFalse((repo / 'kanban/data').exists())


if __name__ == '__main__': unittest.main()
