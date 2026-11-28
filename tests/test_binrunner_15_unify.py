"""Unit tests for BinRunner 1.5.0 Daily path, version guard, and sha256sum hash pin."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from daily_ci.safe_transport import SafeTransportError, sandbox_basename
from recipe_ci.binrunner_compat import major_minor, parse_version_output, require_cli_hap_aligned
from recipe_ci.planner import _ok_device_path
from recipe_ci.sha256sum_deploy import OFFICIAL_SHA256SUM_SHA256, sha256_file


class PathTests(unittest.TestCase):
    def test_planner_accepts_files_root_and_legacy_bin(self):
        self.assertTrue(_ok_device_path("@/recipe-msl"))
        self.assertTrue(_ok_device_path("@/daily-qwen3-4b-msl-s16s4-kirin9030.msl"))
        self.assertTrue(_ok_device_path("@/bin/recipe-msl"))
        self.assertFalse(_ok_device_path("@/bin/sub/x"))
        self.assertFalse(_ok_device_path("@/sub/x"))
        self.assertFalse(_ok_device_path("/tmp/x"))

    def test_sandbox_basename_files_root(self):
        self.assertEqual(sandbox_basename("@/daily-model.msl"), "daily-model.msl")
        self.assertEqual(sandbox_basename("@/bin/daily-model.msl"), "daily-model.msl")
        with self.assertRaises(SafeTransportError):
            sandbox_basename("daily-model.msl")


class VersionGuardTests(unittest.TestCase):
    def test_parse_and_mismatch(self):
        cli, hap = parse_version_output(
            "BinRunner CLI 1.5.0\nDevice HAP   1.5.0 (com.example.binrunner)\n"
        )
        self.assertEqual((cli, hap), ("1.5.0", "1.5.0"))
        self.assertEqual(major_minor("1.5.0"), (1, 5))
        mixed = "BinRunner CLI 1.4.1\nDevice HAP   1.5.0 (com.example.binrunner)\n"
        with mock.patch("recipe_ci.binrunner_compat.subprocess.run") as run:
            run.return_value = mock.Mock(returncode=0, stdout=mixed, stderr="")
            with self.assertRaises(RuntimeError) as caught:
                require_cli_hap_aligned("/unused", "127.0.0.1:3000", "19173")
        self.assertIn("mismatch", str(caught.exception))
        self.assertIn("1.4.1", str(caught.exception))


class Sha256sumPinTests(unittest.TestCase):
    def test_official_hash_constant(self):
        self.assertEqual(
            OFFICIAL_SHA256SUM_SHA256,
            "ef94b21be2a1ca8420dff2be681d8ad3730bedae629c95ec05aaf8ee0d24ee4c",
        )

    def test_sha256_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "x"
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )


if __name__ == "__main__":
    unittest.main()
