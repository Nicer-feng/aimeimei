"""使用合成描述文件校验误配、过期和错误分发类型，不读取真实凭据。"""

import base64
import copy
import datetime as dt
import importlib.util
import os
from pathlib import Path
import plistlib
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("signing_config", Path(__file__).parents[1] / "signing-config.py")
config = importlib.util.module_from_spec(spec)
spec.loader.exec_module(config)


class SigningConfigTests(unittest.TestCase):
    def setUp(self):
        self.team = "TESTTEAM01"
        self.now = dt.datetime(2026, 10, 20, tzinfo=dt.timezone.utc)
        self.profile = {
            "TeamIdentifier": [self.team], "ApplicationIdentifierPrefix": ["LEGACYPFX1"],
            "Platform": ["iOS"], "UUID": "00000000-0000-4000-8000-000000000001",
            "ExpirationDate": dt.datetime(2027, 1, 1), "DeveloperCertificates": [b"synthetic certificate"],
            "Entitlements": {
                "application-identifier": "LEGACYPFX1.asia.feng.aimeimei",
                "com.apple.developer.team-identifier": self.team,
                "get-task-allow": False, "beta-reports-active": True,
                "aps-environment": "production",
            },
        }

    def validate(self, profile=None):
        return config.validate_profile(profile or self.profile, self.team, self.now)

    def test_valid_profile_supports_legacy_application_prefix(self):
        profile_uuid, fingerprint, options = self.validate()
        self.assertEqual(len(fingerprint), 40)
        self.assertEqual(options["provisioningProfiles"], {config.BUNDLE_ID: profile_uuid})
        self.assertEqual(options["method"], "app-store-connect")
        self.assertFalse(options["manageAppVersionAndBuildNumber"])

    def test_rejects_wrong_team(self):
        self.profile["TeamIdentifier"] = ["OTHERTEAM1"]
        with self.assertRaisesRegex(ValueError, "Team"):
            self.validate()

    def test_rejects_missing_or_sandbox_push_permission(self):
        for value in (None, "development"):
            self.profile["Entitlements"]["aps-environment"] = value
            with self.assertRaisesRegex(ValueError, "推送权限"):
                self.validate()

    def test_rejects_wrong_entitlement_team(self):
        self.profile["Entitlements"]["com.apple.developer.team-identifier"] = "OTHERTEAM1"
        with self.assertRaisesRegex(ValueError, "Team"):
            self.validate()

    def test_rejects_other_bundle_and_wildcard(self):
        for suffix in ("other.app", "*"):
            with self.subTest(suffix=suffix):
                self.profile["Entitlements"]["application-identifier"] = "LEGACYPFX1." + suffix
                with self.assertRaisesRegex(ValueError, "精确匹配"):
                    self.validate()

    def test_rejects_development_adhoc_enterprise_and_non_store(self):
        for location, name, value in [
            ("Entitlements", "get-task-allow", True),
            (None, "ProvisionedDevices", ["synthetic-device"]),
            (None, "ProvisionsAllDevices", True),
            ("Entitlements", "beta-reports-active", False),
        ]:
            with self.subTest(name=name):
                profile = copy.deepcopy(self.profile)
                target = profile[location] if location else profile
                target[name] = value
                with self.assertRaisesRegex(ValueError, "App Store Connect"):
                    self.validate(profile)

    def test_rejects_expired_and_missing_expiry(self):
        for expiry in (dt.datetime(2026, 1, 1), None):
            self.profile["ExpirationDate"] = expiry
            with self.assertRaisesRegex(ValueError, "过期"):
                self.validate()

    def test_rejects_wrong_platform(self):
        self.profile["Platform"] = ["OSX"]
        with self.assertRaisesRegex(ValueError, "平台"):
            self.validate()

    def test_rejects_missing_or_ambiguous_certificate(self):
        for certificates in ([], [b"one", b"two"], [""]):
            self.profile["DeveloperCertificates"] = certificates
            with self.assertRaisesRegex(ValueError, "发行证书"):
                self.validate()

    def test_rejects_unsafe_uuid(self):
        self.profile["UUID"] = "../unexpected\nKEY=value"
        with self.assertRaisesRegex(ValueError, "UUID"):
            self.validate()

    def test_decode_accepts_wrapped_base64(self):
        encoded = base64.b64encode(b"synthetic").decode()
        with patch.dict(os.environ, {"TEST_SECRET": "\n" + encoded + "\n"}):
            self.assertEqual(config.decode_secret("TEST_SECRET"), b"synthetic")

    def test_decode_error_does_not_echo_secret(self):
        with patch.dict(os.environ, {"TEST_SECRET": "sensitive-invalid!"}):
            with self.assertRaises(ValueError) as error:
                config.decode_secret("TEST_SECRET")
            self.assertNotIn("sensitive-invalid", str(error.exception))

    def test_upload_secrets_are_only_required_for_upload(self):
        values = {"IOS_TEAM_ID": self.team, "IOS_P12_BASE64": "synthetic", "IOS_P12_PASSWORD": "synthetic", "IOS_PROFILE_BASE64": "synthetic"}
        with patch.dict(os.environ, values, clear=True):
            config.require_environment(upload=False)
            with self.assertRaisesRegex(ValueError, "ASC_KEY_ID, ASC_P8_BASE64"):
                config.require_environment(upload=True)

    def test_team_id_is_not_numeric_app_id_or_issuer(self):
        values = {"IOS_TEAM_ID": "12345", "IOS_P12_BASE64": "synthetic", "IOS_P12_PASSWORD": "synthetic", "IOS_PROFILE_BASE64": "synthetic"}
        with patch.dict(os.environ, values, clear=True):
            with self.assertRaisesRegex(ValueError, "10 位"):
                config.require_environment()

    def test_build_number_rollover_and_retry(self):
        self.assertEqual(config.build_number(1, 1), "1.1.1")
        self.assertEqual(config.build_number(99, 2), "1.99.2")
        self.assertEqual(config.build_number(100, 1), "2.0.1")
        for sequence, attempt in [(0, 1), (1, 0), (1, 100), (999900, 1)]:
            with self.assertRaises(ValueError):
                config.build_number(sequence, attempt)

    def test_export_rejects_unintended_ipad_support(self):
        for families in ([1, 2], [2], None):
            with self.subTest(families=families), tempfile.TemporaryDirectory() as directory:
                self.make_ipa(directory, families)
                with patch.dict(os.environ, {"RUNNER_TEMP": directory, "IOS_BUILD_NUMBER": "1.1.1"}):
                    with self.assertRaisesRegex(ValueError, "仅支持 iPhone"):
                        config.verify_ipa()

    def test_export_records_iphone_only_family(self):
        with tempfile.TemporaryDirectory() as directory:
            self.make_ipa(directory, [1])
            with patch.dict(os.environ, {"RUNNER_TEMP": directory, "IOS_BUILD_NUMBER": "1.1.1", "GITHUB_SHA": "synthetic"}):
                config.verify_ipa()
            import json
            metadata = json.loads((Path(directory) / "meimei-signed-export/build.json").read_text())
            self.assertEqual(metadata["device_families"], [1])
            self.assertFalse(metadata["uploaded_to_app_store_connect"])

    @staticmethod
    def make_ipa(directory, families):
        folder = Path(directory) / "meimei-signed-export"
        folder.mkdir()
        info = {"CFBundleIdentifier": config.BUNDLE_ID, "CFBundleVersion": "1.1.1", "CFBundleShortVersionString": "0.1.0"}
        if families is not None:
            info["UIDeviceFamily"] = families
        with zipfile.ZipFile(folder / "Meimei.ipa", "w") as archive:
            archive.writestr("Payload/Meimei.app/Info.plist", plistlib.dumps(info))
            archive.writestr("Payload/Meimei.app/embedded.mobileprovision", b"synthetic")
            archive.writestr("Payload/Meimei.app/_CodeSignature/CodeResources", b"synthetic")


if __name__ == "__main__":
    unittest.main()
