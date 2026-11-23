"""Cross-check the device checksum source with Python's independent SHA-256."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
_CXX_NAMES = ('g++', 'c++')
_CXX_FLAGS = ('-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror')


def compile_with_available_cxx(source, output, names=_CXX_NAMES):
    """Compile with the first working compiler. Probe order is g++ then c++.

    SkipTest only when none of the names is on PATH. A compiler that is present
    and exits non-zero is a test error; its stderr is kept. This does not set
    CPLUS_INCLUDE_PATH or LIBRARY_PATH.
    """
    found = []
    errors = []
    for name in names:
        compiler = shutil.which(name)
        if not compiler:
            continue
        found.append(compiler)
        completed = subprocess.run(
            [compiler, *_CXX_FLAGS, str(source), '-o', str(output)],
            capture_output=True, text=True)
        if completed.returncode == 0:
            return compiler
        errors.append(
            f'{compiler}\nexit {completed.returncode}\n{completed.stderr}{completed.stdout}')
    if not found:
        raise unittest.SkipTest('no C++ compiler on PATH: ' + ', '.join(names))
    detail = '\n'.join(errors)
    raise AssertionError(
        'C++ source did not compile. Baseline: g++ ' + ' '.join(_CXX_FLAGS) + '.\n' + detail)


class ChecksumTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Prefer g++. On this image `c++` is clang and misses <array> unless include
        # paths are set. Those paths are not the success path here.
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        cls.binary = Path(cls.directory.name) / 'checksum'
        cls.compiler = compile_with_available_cxx(
            ROOT / 'scripts/device_tools/sha256sum.cc', cls.binary)

    def test_vectors_padding_and_stream_boundaries(self):
        for data in [b'', b'abc', b'a' * 1000000] + [bytes(i % 251 for i in range(n)) for n in [55, 56, 63, 64, 65, 65535, 65536, 65537]]:
            with self.subTest(length=len(data)):
                file = Path(self.directory.name) / 'input'
                file.write_bytes(data)
                # BinRunner can replace argv[0]; unlike Toybox, this must still work.
                result = subprocess.run(['@13', str(file)], executable=str(self.binary), capture_output=True, text=True, check=True)
                self.assertEqual(result.stdout, hashlib.sha256(data).hexdigest() + '  ' + str(file) + '\n')

    def test_uncompilable_source_fails_instead_of_skipping(self):
        bad = Path(self.directory.name) / 'bad.cc'
        bad.write_text('int this is not compilable;\n')
        with self.assertRaises(AssertionError) as caught:
            compile_with_available_cxx(bad, Path(self.directory.name) / 'bad-bin')
        message = str(caught.exception)
        self.assertNotIsInstance(caught.exception, unittest.SkipTest)
        for name in _CXX_NAMES:
            compiler = shutil.which(name)
            if compiler:
                self.assertIn(compiler, message)
                self.assertIn('not compilable', message)

    def test_skip_only_when_no_compiler_is_on_path(self):
        with self.assertRaises(unittest.SkipTest):
            compile_with_available_cxx(
                ROOT / 'scripts/device_tools/sha256sum.cc',
                Path(self.directory.name) / 'unused',
                names=('no-such-cxx-gxx', 'no-such-cxx-cxx'))

    def test_unreadable_file_does_not_emit_a_digest(self):
        result = subprocess.run([str(self.binary), str(Path(self.directory.name) / 'missing')], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
