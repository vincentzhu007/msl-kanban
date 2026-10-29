import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from daily_ci.model_export import extract_zip, source_manifest, export_model


class ModelExportTests(unittest.TestCase):
    def test_ddk_rejects_escape_and_symlink(self):
        for name, mode in [('../escape', 0o100644), ('link', 0o120777)]:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                with zipfile.ZipFile(root/'bad.zip','w') as z:
                    info = zipfile.ZipInfo(name); info.external_attr = mode << 16
                    z.writestr(info, 'outside')
                with self.assertRaises(ValueError): extract_zip(root/'bad.zip',root/'out')

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
