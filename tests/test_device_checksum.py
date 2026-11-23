"""Cross-check the device checksum source with Python's independent SHA-256."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ChecksumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prefer g++. On this image `c++` is clang and does not see libstdc++ unless
        # CPLUS_INCLUDE_PATH and LIBRARY_PATH are set. The compile line is the baseline.
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / 'checksum'
        source = str(ROOT / 'scripts/device_tools/sha256sum.cc')
        flags = ['-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror', source, '-o', str(cls.binary)]
        errors = []
        for name in ('g++', 'c++'):
            compiler = shutil.which(name)
            if not compiler:
                errors.append(name + ' not on PATH')
                continue
            completed = subprocess.run([compiler, *flags], capture_output=True, text=True)
            if completed.returncode == 0:
                cls.compiler = compiler
                return
            errors.append(compiler + '\n' + (completed.stderr or completed.stdout))
        raise unittest.SkipTest(
            'sha256sum.cc did not compile. Baseline: g++ -std=c++17 -O2 -Wall -Wextra -Werror. '
            + ' '.join(errors))

    def test_vectors_padding_and_stream_boundaries(self):
        for data in [b'', b'abc', b'a' * 1000000] + [bytes(i % 251 for i in range(n)) for n in [55, 56, 63, 64, 65, 65535, 65536, 65537]]:
            with self.subTest(length=len(data)):
                file = Path(self.directory.name) / 'input'
                file.write_bytes(data)
                # BinRunner can replace argv[0]; unlike Toybox, this must still work.
                result = subprocess.run(['@13', str(file)], executable=str(self.binary), capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, hashlib.sha256(data).hexdigest() + '  ' + str(file) + '\n')

    def test_unreadable_file_does_not_emit_a_digest(self):
        result = subprocess.run([str(self.binary), str(Path(self.directory.name) / 'missing')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
