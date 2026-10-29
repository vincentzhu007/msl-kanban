import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from daily_ci.model_export import extract_zip, source_manifest, export_model, run_export, restore_ddk_header_link


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
