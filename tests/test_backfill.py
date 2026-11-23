"""Backfill locks and global fport snapshots; no device or upstream connection."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from daily_ci.pipeline import PACKAGE, prepare_msl, run, select_msl_build
from daily_ci.safe_transport import SafeSession, SafeTransportError, open_safe_session, parse_forwards, plan_host_port
from recipe_ci.recipe import RecipeError
from test_safe_device import ListingHdc, SERIAL, config_for

TASK = 'qwen25-15b-msl-w4a16-kirin9020'
EXAMPLE = ROOT / 'config/backfills/qwen25-15b-20261123.package-lock.json'
SCHEDULED_RUN_DAY = '20261124'


class PackageLockTests(unittest.TestCase):
    def fixture(self, root):
        body = b'cached backfill bytes'
        lock = json.loads(EXAMPLE.read_text())['package_lock']
        lock['sha256'] = hashlib.sha256(body).hexdigest()
        archive = root / lock['sha256'] / PACKAGE
        archive.parent.mkdir()
        archive.write_bytes(body)
        return {'package_lock': lock}, archive

    def test_lock_selects_cached_identity_on_any_run_date_without_discovery(self):
        with tempfile.TemporaryDirectory() as tmp, patch('daily_ci.pipeline.discover') as discover, \
             patch('daily_ci.pipeline.urlopen', side_effect=AssertionError('network forbidden')):
            config, archive = self.fixture(Path(tmp))
            for run_day in (SCHEDULED_RUN_DAY, '20261123', '20270101'):
                with self.subTest(run_day=run_day):
                    build = select_msl_build(config, TASK, run_day, Path(tmp))
                    self.assertEqual(build, {k: config['package_lock'][k] for k in ('commit', 'source_url', 'sha256')})
                    self.assertEqual(config['package_lock']['day'], '20261123')
            self.assertEqual(archive.read_bytes(), b'cached backfill bytes')
            discover.assert_not_called()

    def test_bad_missing_and_revoked_locks_do_not_fall_back(self):
        with tempfile.TemporaryDirectory() as tmp, patch('daily_ci.pipeline.discover') as discover, \
             patch('daily_ci.pipeline.urlopen', side_effect=AssertionError('network forbidden')):
            root = Path(tmp)
            config, archive = self.fixture(root)
            archive.write_bytes(b'corrupt')
            with self.assertRaisesRegex(RecipeError, 'SHA256 mismatch'):
                select_msl_build(config, TASK, SCHEDULED_RUN_DAY, root)
            archive.unlink()
            with self.assertRaisesRegex(RecipeError, 'missing'):
                select_msl_build(config, TASK, SCHEDULED_RUN_DAY, root)
            discover.assert_not_called()
            discover.return_value = {'regular': True}
            self.assertEqual(select_msl_build({}, TASK, SCHEDULED_RUN_DAY, root), {'regular': True})
            discover.assert_called_once_with(SCHEDULED_RUN_DAY)

    def test_lock_schema_url_commit_and_task_are_checked_without_run_date_equality(self):
        with tempfile.TemporaryDirectory() as tmp, patch('daily_ci.pipeline.discover') as discover, \
             patch('daily_ci.pipeline.urlopen', side_effect=AssertionError('network forbidden')):
            root = Path(tmp)
            config, _ = self.fixture(root)
            source = (ROOT / 'scripts/daily_ci/pipeline.py').read_text()
            self.assertNotIn("lock['day'] == day", source)
            self.assertNotIn('lock["day"] == day', source)
            for field, value in [('day', SCHEDULED_RUN_DAY), ('sha256', '../bad'), ('sha256', 'f' * 64),
                                 ('commit', 'f' * 40), ('source_url', 'https://example.invalid/package'),
                                 ('extra', True)]:
                changed = copy.deepcopy(config)
                changed['package_lock'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(RecipeError):
                    select_msl_build(changed, TASK, '20261123', root)
            for lock in [None, {}, [], {'day': '20261123'}]:
                with self.subTest(lock=lock), self.assertRaises(RecipeError):
                    select_msl_build({'package_lock': lock}, TASK, SCHEDULED_RUN_DAY, root)
            with self.assertRaises(RecipeError):
                select_msl_build(config, 'qwen25-05b-msl-w4a16-kirin9020', SCHEDULED_RUN_DAY, root)
            discover.assert_not_called()

    def test_original_msl_tasks_without_lock_still_discover_requested_day(self):
        for task in ('qwen25-05b-msl-w4a16-kirin9020', 'qwen25-05b-msl-q30-kirin9020',
                     'qwen3-4b-msl-s16s4-kirin9030', 'qwen3-06b-msl-s16s4-kirin9030', TASK):
            with self.subTest(task=task), patch('daily_ci.pipeline.discover', return_value=None) as discover:
                self.assertIsNone(select_msl_build({}, task, SCHEDULED_RUN_DAY, Path('/not-used')))
                discover.assert_called_once_with(SCHEDULED_RUN_DAY)

    def test_prepare_rechecks_locked_cache_and_never_downloads_corrupt_bytes(self):
        with tempfile.TemporaryDirectory() as tmp, patch('daily_ci.pipeline.safe_extract') as extract, \
             patch('daily_ci.pipeline.urlopen', side_effect=AssertionError('network forbidden')):
            root = Path(tmp)
            config, archive = self.fixture(root)
            build = select_msl_build(config, TASK, SCHEDULED_RUN_DAY, root)
            archive.write_bytes(b'changed after selection')
            with self.assertRaisesRegex(RecipeError, 'SHA256 mismatch'):
                prepare_msl(ROOT, config, build, root / 'task', root)
            extract.assert_not_called()

    def test_failed_lock_in_formal_run_records_failure_before_device_or_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            config = json.loads((ROOT / 'config/deploy' / (TASK + '.json')).read_text())
            config['archive_root'] = str(repo / 'archive')
            config.update(json.loads(EXAMPLE.read_text()))
            with patch('daily_ci.pipeline.run_command'), \
                 patch('daily_ci.pipeline.subprocess.check_output', return_value='c' * 40), \
                 patch('daily_ci.pipeline.discover') as discover, \
                 patch('daily_ci.pipeline.device_lease', side_effect=AssertionError('device forbidden')) as lease, \
                 patch('daily_ci.pipeline.urlopen', side_effect=AssertionError('network forbidden')) as network:
                self.assertEqual(run(repo, ROOT / 'recipes' / (TASK + '.json'), config, SCHEDULED_RUN_DAY), 1)
            discover.assert_not_called()
            lease.assert_not_called()
            network.assert_not_called()
            task = next((repo / 'archive/tasks').iterdir())
            status = json.loads((task / 'status.json').read_text())
            self.assertEqual(status['date'], SCHEDULED_RUN_DAY)
            self.assertEqual(status['error_type'], 'RecipeError')
            self.assertEqual((task / 'error.txt').read_text(), 'Locked package is missing from cache')
            self.assertEqual((status['status'], status['stage']), ('FAILED', 'DISCOVER'))
            self.assertFalse((repo / 'kanban/data').exists())

    def test_valid_lock_formal_run_archives_identity_on_scheduled_run_date(self):
        for task_id in (TASK, 'qwen25-15b-msl-q30-kirin9020'):
            with self.subTest(task_id=task_id), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                root = repo / 'archive'
                (root / 'packages').mkdir(parents=True)
                lock_config, _ = self.fixture(root / 'packages')
                config = json.loads((ROOT / 'config/deploy' / (task_id + '.json')).read_text())
                config['archive_root'] = str(root)
                config.update(lock_config)
                with patch('daily_ci.pipeline.run_command'), \
                     patch('daily_ci.pipeline.subprocess.check_output', return_value='c' * 40), \
                     patch('daily_ci.pipeline.discover') as discover, \
                     patch('daily_ci.pipeline.device_lease', side_effect=RuntimeError('test stop before device')) as lease, \
                     patch('daily_ci.pipeline.urlopen', side_effect=AssertionError('network forbidden')):
                    self.assertEqual(run(repo, ROOT / 'recipes' / (task_id + '.json'), config, SCHEDULED_RUN_DAY), 1)
                discover.assert_not_called()
                lease.assert_called_once_with(root / 'leases', SERIAL)
                task = next((root / 'tasks').iterdir())
                saved = json.loads((task / 'package-lock.json').read_text())
                self.assertEqual(saved, config['package_lock'])
                self.assertEqual(saved['day'], '20261123')
                status = json.loads((task / 'status.json').read_text())
                self.assertEqual(status['date'], SCHEDULED_RUN_DAY)
                self.assertEqual(json.loads((task / 'build.json').read_text()),
                                 {k: config['package_lock'][k] for k in ('commit', 'source_url', 'sha256')})
                self.assertEqual((task / 'error.txt').read_text(), 'test stop before device')
                self.assertFalse((repo / 'kanban/data').exists())

    def test_example_matches_authorized_identity_and_default_configs_do_not_enable_lock(self):
        lock = json.loads(EXAMPLE.read_text())['package_lock']
        self.assertEqual(lock['sha256'], '05c304249884d7674a415442eb437042844a53745e3a73f9d66f2c4f6ee438a1')
        self.assertEqual(lock['commit'], '415fad80e2f936f73400477d92ac063bcbdd40b2')
        self.assertIn('/20261123/master_20261123010014_' + lock['commit'] + '_newest/', lock['source_url'])
        for directory in ('config/daily', 'config/deploy'):
            for path in (ROOT / directory).glob('*.json'):
                self.assertNotIn('package_lock', json.loads(path.read_text()))


class GlobalForwardTests(unittest.TestCase):
    def test_real_global_fixtures_keep_foreign_rows_and_only_remove_own_tuple(self):
        for fixture in sorted((ROOT / 'tests/fixtures/fport').glob('*.txt')):
            with self.subTest(fixture=fixture.name), patch('daily_ci.safe_transport.subprocess.run',
                                                         side_effect=AssertionError('real command forbidden')):
                listing = fixture.read_text()
                rows = parse_forwards(listing)
                config = config_for(TASK, 19147)
                selected = plan_host_port(config['environment'], config, listing_text=listing, listeners=set())
                self.assertEqual(selected['host_port'], 19147)
                self.assertEqual(selected['editable_rows'], tuple(r for r in rows if r[0] == SERIAL))
                hdc = ListingHdc(rows)
                with open_safe_session(config['environment'], config, None, selected['host_port'], hdc=hdc):
                    pass
                self.assertEqual(tuple(hdc.rows), rows)
                writes = [(s, a) for s, a in hdc.calls if a != ['fport', 'ls']]
                self.assertEqual(writes, [(SERIAL, ['fport', 'tcp:19147', 'tcp:8888']),
                                          (SERIAL, ['fport', 'rm', 'tcp:19147', 'tcp:8888'])])

    def test_all_serials_including_3001_reserve_host_ports(self):
        config = config_for(TASK, 19147)
        listing = '127.0.0.1:3001 tcp:19147 tcp:8888 [Forward]\n127.0.0.1:5000 tcp:19148 tcp:8888 [Forward]\n'
        plan = plan_host_port(config['environment'], config, listing_text=listing, listeners={19149})
        self.assertEqual(plan['host_port'], 19150)
        self.assertEqual(plan['editable_rows'], ())

    def test_close_does_not_remove_foreign_replacement_of_own_tuple(self):
        config = config_for(TASK, 19147)
        hdc = ListingHdc([])
        foreign = ('127.0.0.1:3001', 'tcp:19147', 'tcp:8888')
        with open_safe_session(config['environment'], config, None, 19147, hdc=hdc):
            hdc.rows = [foreign]
        self.assertEqual(hdc.rows, [foreign])
        self.assertFalse(any(args[:2] == ['fport', 'rm'] for _, args in hdc.calls))

    def test_cleanup_refuses_ambiguous_host_port_without_removing_either_serial(self):
        config = config_for(TASK, 19147)
        hdc = ListingHdc([])
        foreign = ('127.0.0.1:3001', 'tcp:19147', 'tcp:8888')
        with open_safe_session(config['environment'], config, None, 19147, hdc=hdc) as session:
            hdc.rows.append(foreign)
            with self.assertRaisesRegex(SafeTransportError, 'another owner'):
                session._remove_if_exact((SERIAL, 'tcp:19147', 'tcp:8888'))
        self.assertIn(foreign, hdc.rows)
        self.assertIn((SERIAL, 'tcp:19147', 'tcp:8888'), hdc.rows)
        self.assertFalse(any(args[:2] == ['fport', 'rm'] for _, args in hdc.calls))

    def test_unknown_lines_and_wrong_tuple_fail_before_any_mutation(self):
        config = config_for(TASK, 19147)
        for line in ['unknown', '[Fail] unavailable', '127.0.0.1:3001 tcp:2 tcp:8888 UNKNOWN',
                     '127.0.0.1:3001 tcp:65536 tcp:8888 [Forward]']:
            with self.subTest(line=line), self.assertRaises(SafeTransportError):
                plan_host_port(config['environment'], config, listing_text=line, listeners=set())
        hdc = ListingHdc([('127.0.0.1:3001', 'tcp:19147', 'tcp:8888')])
        session = SafeSession(SERIAL, 19147, hdc, None)
        with self.assertRaises(SafeTransportError):
            session._remove_if_exact(('127.0.0.1:3001', 'tcp:19147', 'tcp:8888'))
        self.assertEqual(hdc.calls, [])


if __name__ == '__main__':
    unittest.main()
