import gzip
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from daily_ci.model_export import (
    extract_zip, source_manifest, export_model, run_export, restore_ddk_header_link,
    listener_path_length, prepare_export_environment, wrap_export_command,
    cleanup_task_workdir,
)


class ModelExportTests(unittest.TestCase):
    def test_ddk_rejects_escape_and_symlink(self):
        for name, mode in [('../escape', 0o100644), ('link', 0o120777)]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with zipfile.ZipFile(root/'bad.zip','w') as z:
                    info = zipfile.ZipInfo(name); info.external_attr = mode << 16
                    z.writestr(info, 'outside')
                with self.assertRaises(ValueError): extract_zip(root/'bad.zip',root/'out')

    def test_ddk_preserves_safe_sibling_library_alias(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with zipfile.ZipFile(root/'ddk.zip','w') as z:
                lib=zipfile.ZipInfo('lib/real.so');lib.external_attr=0o100755 << 16;z.writestr(lib,b'library')
                link=zipfile.ZipInfo('lib/alias.so');link.external_attr=0o120777 << 16;z.writestr(link,'real.so')
            extract_zip(root/'ddk.zip',root/'out')
            self.assertTrue((root/'out/lib/alias.so').is_symlink())
            self.assertEqual((root/'out/lib/alias.so').read_bytes(),b'library')

    def test_export_missing_header_and_timeout_stop_process(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            command=[sys.executable, '-u', '-c', "import time; print(\"single op compile failed; fatal error: 'missing.h' file not found\"); time.sleep(60)"]
            with self.assertRaisesRegex(RuntimeError, 'missing header'):
                run_export(command,env=os.environ.copy(),task=root,timeout=5,poll_seconds=.02)
            with self.assertRaises(TimeoutError):
                run_export([sys.executable,'-c','import time; time.sleep(60)'],env=os.environ.copy(),task=root,timeout=.05,poll_seconds=.02)

    def test_ddk_materialized_header_alias_restores_relative_include(self):
        with tempfile.TemporaryDirectory() as tmp:
            ddk=Path(tmp)
            root=ddk/'tools/tools_ascendc/include/tikcpp'
            for folder in ['tikcfw/lib/std','api/lib/std','api/impl/std/tuple']:
                (root/folder).mkdir(parents=True)
            header='#include "../../impl/std/tuple/tuple_impl.h"'
            for folder in ['tikcfw/lib/std','api/lib/std']:
                (root/folder/'tuple.h').write_text(header)
            (root/'api/impl/std/tuple/tuple_impl.h').write_text('// vendor implementation')
            self.assertFalse((root/'tikcfw/impl/std/tuple/tuple_impl.h').exists())
            restore_ddk_header_link(ddk)
            self.assertEqual((root/'tikcfw/lib/std/tuple.h').resolve(),(root/'api/lib/std/tuple.h').resolve())
            self.assertEqual((root/'tikcfw/lib.ddk-6.1.1.0-materialized.bak/std/tuple.h').read_text(),header)
            restore_ddk_header_link(ddk)

    def test_manifest_tracks_weights_and_tokenizer_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'config.json').write_text('{}')
            (root/'model.safetensors').write_bytes(b'weights')
            (root/'tokenizer.json').write_text('{}')
            before=source_manifest(root)
            (root/'tokenizer.json').write_text('{"changed":true}')
            self.assertNotEqual(source_manifest(root),before)
            (root/'model.safetensors').unlink()
            with self.assertRaises(ValueError):source_manifest(root)

    def test_missing_daily_tools_fails_without_frozen_model_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'source';source.mkdir()
            (source/'config.json').write_text('{}');(source/'model.safetensors').write_bytes(b'weights')
            settings={'model_generation':{'mode':'master_daily','source_model':str(source),'minimum_free_bytes':0}}
            recipe={'model':{'sha256':'old-model'}}
            with self.assertRaisesRegex(ValueError,'Expected one daily component'):
                export_model(root,recipe,{},settings,root,{},lambda *a,**k:None,lambda *a:None)
            self.assertEqual(recipe['model']['sha256'],'old-model')

    def test_export_command_stays_unchanged_without_task_env(self):
        command = wrap_export_command('set.sh', ['python3', 'export_entry.py'])
        self.assertEqual(command, ['bash', '-c', 'source "$1"; shift; exec "$@"', 'daily-ddk-env', 'set.sh',
                                   'python3', 'export_entry.py'])
        self.assertNotIn('TMPDIR', command[2])

    def test_opt_in_export_env_uses_short_tmpdir_and_bisheng_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            compiler = Path(tmp) / 'bisheng'
            compiler.write_text('#!/bin/sh\nexit 0\n')
            compiler.chmod(0o755)
            managed = prepare_export_environment({'export_environment': {
                'tmpdir_root': '/tmp', 'tmpdir_prefix': 'e15.', 'tmpdir_minimum_free_bytes': 0,
                'prepend_path': [tmp]}})
            try:
                self.assertTrue(managed.tmpdir.startswith('/tmp/e15.'))
                self.assertLess(listener_path_length(managed.tmpdir), 107)
                env = managed.apply({'PATH': '/usr/bin', 'TMPDIR': '/long/private/task/tmp'})
                self.assertEqual(env['TMPDIR'], managed.tmpdir)
                self.assertTrue(env['PATH'].startswith(tmp + ':'))
                self.assertIn('/usr/bin', env['PATH'])
                wrapped = wrap_export_command('set.sh', ['python3'], {
                    'tmpdir': managed.tmpdir, 'prepend_path': [tmp]})
                self.assertIn('export TMPDIR="$2"', wrapped[2])
                self.assertIn('export PATH="$3${PATH:+:}$PATH"', wrapped[2])
                self.assertEqual(wrapped[4], 'set.sh')
                self.assertEqual(wrapped[5], managed.tmpdir)
            finally:
                managed.cleanup()
            self.assertFalse(Path(managed.tmpdir).exists())

    def test_export_command_still_asks_the_exporter_to_keep_artifacts(self):
        self.assertIn("'--keep-artifacts'", inspect.getsource(export_model))

    def test_cleanup_keeps_validated_model_and_drops_export_worktrees(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'source-models'
            outside.mkdir()
            (outside / 'model.safetensors').write_bytes(b'weights')
            task = root / 'tasks' / 'daily-20261128-qwen3-4b-msl-s16s4-kirin9030-1-1'
            task.mkdir(parents=True)
            sibling = root / 'tasks' / 'daily-20261127-qwen3-4b-msl-s16s4-kirin9030-9-1'
            sibling.mkdir()
            (sibling / '.msl_export_historical').mkdir()
            (sibling / 'model.msl').write_bytes(b'.MSL' + b'historical-model')
            (root / 'packages' / 'abc').mkdir(parents=True)
            (root / 'packages' / 'abc' / 'package.tar.gz').write_bytes(b'cached')
            (root / 'runs' / 'old').mkdir(parents=True)
            (root / 'runs' / 'old' / 'sample.csv').write_text('ok\n')
            work = task / '.msl_export_lljk7il0'
            work.mkdir()
            (work / 'blob').write_bytes(b'x' * 128)
            (work / 'weights').symlink_to(outside / 'model.safetensors')
            (work / 'source').symlink_to(outside, target_is_directory=True)
            (task / 'ddk').mkdir()
            (task / 'ddk' / 'tools').write_text('compiler')
            (task / 'ddk-source').mkdir()
            (task / 'python').mkdir()
            (task / 'package').mkdir()
            # Not the ddk worktree. A nearby symlink must stay, and its target too.
            linked = task / 'ddk-link'
            linked.symlink_to(outside, target_is_directory=True)
            model = task / 'model.msl'
            payload = b'.MSL' + b'complete-model-bytes!!'
            model.write_bytes(payload)
            os.link(model, task / 'daily-qwen3-4b-msl-s16s4-kirin9030.msl')
            (task / 'extra.msl').write_bytes(b'.MSL' + b'different-copy-of-model')
            (task / 'export.log').write_text('export finished\n')
            (task / 'status.json').write_text('{"status":"SUCCEEDED"}\n')
            (task / 'generated-model.json').write_text('{}\n')
            (task / 'source.tar.gz').write_bytes(b'snapshot')
            summary = cleanup_task_workdir(task, retain_model=True)
            self.assertTrue(summary['model_kept'])
            self.assertEqual(model.read_bytes(), payload)
            self.assertEqual((task / 'daily-qwen3-4b-msl-s16s4-kirin9030.msl').stat().st_ino, model.stat().st_ino)
            self.assertFalse((task / 'extra.msl').exists())
            for name in ['.msl_export_lljk7il0', 'ddk', 'ddk-source', 'python', 'package', 'export.log']:
                self.assertFalse((task / name).exists(), name)
            self.assertEqual(gzip.open(task / 'export.log.gz', 'rt').read(), 'export finished\n')
            self.assertEqual((task / 'status.json').read_text(), '{"status":"SUCCEEDED"}\n')
            self.assertTrue((task / 'generated-model.json').is_file())
            self.assertEqual((task / 'source.tar.gz').read_bytes(), b'snapshot')
            self.assertEqual((outside / 'model.safetensors').read_bytes(), b'weights')
            self.assertTrue(outside.is_dir())
            self.assertTrue(linked.is_symlink())
            self.assertTrue((sibling / '.msl_export_historical').is_dir())
            self.assertTrue((sibling / 'model.msl').is_file())
            self.assertEqual((root / 'packages' / 'abc' / 'package.tar.gz').read_bytes(), b'cached')
            self.assertEqual((root / 'runs' / 'old' / 'sample.csv').read_text(), 'ok\n')
            recorded = json.loads((task / 'cleanup.json').read_text())
            self.assertTrue(recorded['retain_requested'])
            self.assertTrue(recorded['model_kept'])
            self.assertEqual(recorded['errors'], [])
            again = cleanup_task_workdir(task, retain_model=True)
            self.assertTrue(again['model_kept'])
            self.assertEqual(model.read_bytes(), payload)

    def test_cleanup_drops_partial_model_when_export_did_not_succeed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outside = root / 'outside'
            outside.mkdir()
            (outside / 'precious').write_text('keep')
            task = root / 'tasks' / 'daily-20261128-qwen3-4b-msl-s16s4-kirin9030-46094530629-1'
            task.mkdir(parents=True)
            (task / 'ddk').symlink_to(outside, target_is_directory=True)
            work = task / '.msl_export_lljk7il0'
            work.mkdir()
            (work / 'partial.bin').write_bytes(b'y' * 64)
            # Pack wrote the header and then died with ENOSPC. Magic is not completeness.
            (task / 'model.msl').write_bytes(b'.MSL' + b'\x00' * 4096)
            (task / 'export.log').symlink_to(outside / 'precious')
            (task / 'error.txt').write_text('No space left on device\n')
            (task / 'status.json').write_text('{"status":"FAILED"}\n')
            summary = cleanup_task_workdir(task, retain_model=False)
            self.assertFalse(summary['model_kept'])
            self.assertFalse(summary['retain_requested'])
            self.assertFalse((task / 'model.msl').exists())
            self.assertFalse(work.exists())
            self.assertFalse((task / 'ddk').exists())
            self.assertFalse((task / 'export.log').exists())
            self.assertEqual((outside / 'precious').read_text(), 'keep')
            self.assertEqual((task / 'error.txt').read_text(), 'No space left on device\n')
            self.assertEqual((task / 'status.json').read_text(), '{"status":"FAILED"}\n')
            self.assertEqual(summary['errors'], [])

    def test_cleanup_refuses_directories_that_are_not_this_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in ['tasks/not-a-run', 'other/daily-20261128-qwen3-4b-1-1']:
                directory = root / relative
                directory.mkdir(parents=True)
                (directory / 'ddk').mkdir()
                (directory / '.msl_export_nope').mkdir()
                (directory / 'model.msl').write_bytes(b'.MSL' + b'leave-this-file-alone')
                summary = cleanup_task_workdir(directory, retain_model=False)
                self.assertEqual(summary['errors'][0]['error'], 'refusing-non-task-directory')
                self.assertTrue((directory / 'ddk').is_dir())
                self.assertTrue((directory / '.msl_export_nope').is_dir())
                self.assertTrue((directory / 'model.msl').is_file())

    def test_cleanup_does_not_keep_a_short_magic_file_just_because_retention_was_requested(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = Path(tmp) / 'tasks' / 'daily-20261128-qwen3-06b-msl-s16s4-kirin9030-2-1'
            task.mkdir(parents=True)
            (task / 'model.msl').write_bytes(b'.MSL')
            summary = cleanup_task_workdir(task, retain_model=True)
            self.assertTrue(summary['retain_requested'])
            self.assertFalse(summary['model_kept'])
            self.assertFalse((task / 'model.msl').exists())
