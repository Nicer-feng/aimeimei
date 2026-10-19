import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("prepare_release", Path(__file__).parents[1] / "prepare-release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTest(unittest.TestCase):
    def test_metadata_uses_actual_apk_bytes_and_verified_certificate(self):
        with tempfile.TemporaryDirectory() as folder:
            payload = b"test fixture, not a real APK"
            Path(folder, "app-release.apk").write_bytes(payload)
            with patch.object(release.subprocess, "check_output", side_effect=[
                "package: name='asia.feng.aimeimei' versionCode='3' versionName='0.3.0'",
                "Signer #1 certificate SHA-256 digest: " + "ab" * 32,
            ]) as command:
                release.prepare(folder, "/test-sdk")
                self.assertIn("verify", command.call_args.args[0])
            meta = json.loads(Path(folder, "update.json").read_text())
            self.assertEqual(meta["sha256"], hashlib.sha256(payload).hexdigest())
            self.assertEqual(meta["certificateSha256"], "ab" * 32)
            self.assertEqual(meta["size"], len(payload))
            self.assertEqual(meta["versionCode"], 3)
            self.assertEqual(meta["apkName"], "aimeimei-0.3.0.apk")

    def test_rejects_debug_package(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "app.apk").write_bytes(b"fixture")
            with patch.object(release.subprocess, "check_output", return_value="package: name='asia.feng.aimeimei.dev' versionCode='3' versionName='0.3.0'"):
                with self.assertRaises(ValueError):
                    release.prepare(folder, "/test-sdk")
            self.assertFalse(Path(folder, "update.json").exists())

    def test_signature_failure_cannot_publish_manifest(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "app.apk").write_bytes(b"fixture")
            with patch.object(release.subprocess, "check_output", side_effect=[
                "package: name='asia.feng.aimeimei' versionCode='3' versionName='0.3.0'",
                subprocess.CalledProcessError(1, "apksigner"),
            ]):
                with self.assertRaises(subprocess.CalledProcessError):
                    release.prepare(folder, "/test-sdk")
            self.assertFalse(Path(folder, "update.json").exists())


if __name__ == "__main__":
    unittest.main()
