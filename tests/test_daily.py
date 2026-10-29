import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from daily_ci.pipeline import select_build, safe_extract, download, public_result, run, ensure_forward, record_blocked, prepare_llama


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

if __name__ == '__main__': unittest.main()
