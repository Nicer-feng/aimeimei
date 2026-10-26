#!/usr/bin/env python3
"""校验云端签名材料，只向日志输出可操作的错误，不输出凭据。"""

import argparse
import base64
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import uuid
import zipfile

BUNDLE_ID = "asia.feng.aimeimei"


def build_number(sequence, attempt):
    # CFBundleVersion 使用三段整数：首段最多 4 位，其余每段最多 2 位。
    if not 1 <= sequence < 999900 or not 1 <= attempt <= 99:
        raise ValueError("工作流编号或重试次数超出构建编号范围")
    return f"{1 + sequence // 100}.{sequence % 100}.{attempt}"


def require_environment(upload=False):
    names = ["IOS_TEAM_ID", "IOS_P12_BASE64", "IOS_P12_PASSWORD", "IOS_PROFILE_BASE64"]
    if upload:
        names += ["ASC_KEY_ID", "ASC_P8_BASE64"]
    missing = [name for name in names if not os.environ.get(name, "").strip()]
    if missing:
        raise ValueError("请在仓库或 testflight Environment 中配置 Secrets：" + ", ".join(missing))
    if not re.fullmatch(r"[A-Z0-9]{10}", os.environ["IOS_TEAM_ID"]):
        raise ValueError("IOS_TEAM_ID 应为开发者团队的 10 位标识，不是应用数字 Apple ID 或 Issuer ID")


def decode_secret(name):
    try:
        return base64.b64decode("".join(os.environ[name].split()), validate=True)
    except (KeyError, ValueError):
        raise ValueError(name + " 不是有效的 Base64 文件内容") from None


def validate_profile(profile, team_id, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    entitlements = profile.get("Entitlements", {})
    if entitlements.get("aps-environment") != "production":
        raise ValueError("描述文件缺少 production 推送权限，请启用 Push Notifications 后重新生成并更新 IOS_PROFILE_BASE64")
    if profile.get("TeamIdentifier") != [team_id] or entitlements.get("com.apple.developer.team-identifier") != team_id:
        raise ValueError("描述文件的 Team 与 IOS_TEAM_ID 不一致")
    prefixes = profile.get("ApplicationIdentifierPrefix", [])
    app_identifier = entitlements.get("application-identifier")
    if not any(app_identifier == prefix + "." + BUNDLE_ID for prefix in prefixes):
        raise ValueError("描述文件必须精确匹配 " + BUNDLE_ID + "，不能使用通配符")
    if "iOS" not in profile.get("Platform", []):
        raise ValueError("描述文件不是 iOS 平台")
    if (entitlements.get("get-task-allow", False) or "ProvisionedDevices" in profile
            or profile.get("ProvisionsAllDevices", False) or entitlements.get("beta-reports-active") is not True):
        raise ValueError("请选择 App Store Connect 描述文件，不能使用 Development、Ad Hoc 或 Enterprise")
    expires = profile.get("ExpirationDate")
    if not isinstance(expires, dt.datetime) or expires.replace(tzinfo=dt.timezone.utc) <= now:
        raise ValueError("描述文件缺少有效到期时间或已经过期，请重新生成")
    profile_uuid = str(profile.get("UUID", ""))
    try:
        if str(uuid.UUID(profile_uuid)).upper() != profile_uuid.upper():
            raise ValueError()
    except ValueError:
        raise ValueError("描述文件 UUID 无效") from None
    certificates = profile.get("DeveloperCertificates", [])
    if len(certificates) != 1 or not isinstance(certificates[0], bytes) or not certificates[0]:
        raise ValueError("描述文件必须包含一个有效发行证书")
    fingerprint = hashlib.sha1(certificates[0]).hexdigest().upper()
    options = {
        "method": "app-store-connect",
        "destination": "export",
        "signingStyle": "manual",
        "teamID": team_id,
        "signingCertificate": fingerprint,
        "provisioningProfiles": {BUNDLE_ID: profile_uuid},
        "manageAppVersionAndBuildNumber": False,
        "stripSwiftSymbols": True,
        "uploadSymbols": True,
    }
    return profile_uuid, fingerprint, options


def prepare():
    require_environment()
    signing_dir = Path(os.environ["RUNNER_TEMP"]) / "meimei-signing"
    signing_dir.mkdir(mode=0o700, exist_ok=True)
    for secret_name, filename in [("IOS_P12_BASE64", "distribution.p12"), ("IOS_PROFILE_BASE64", "app.mobileprovision")]:
        file_path = signing_dir / filename
        file_path.write_bytes(decode_secret(secret_name))
        file_path.chmod(0o600)
    result = subprocess.run(["security", "cms", "-D", "-i", str(signing_dir / "app.mobileprovision")],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode:
        raise ValueError("无法解码描述文件，请确认 IOS_PROFILE_BASE64 来自 .mobileprovision 文件")
    try:
        profile = plistlib.loads(result.stdout)
    except plistlib.InvalidFileException:
        raise ValueError("描述文件不是有效 plist") from None
    profile_uuid, fingerprint, options = validate_profile(profile, os.environ["IOS_TEAM_ID"])
    (signing_dir / "ExportOptions.plist").write_bytes(plistlib.dumps(options))
    with open(os.environ["GITHUB_ENV"], "a") as out:
        out.write("IOS_PROFILE_UUID=" + profile_uuid + "\n")
        out.write("IOS_CERT_SHA1=" + fingerprint + "\n")
    print("描述文件的用途、有效期、Team 和 Bundle ID 校验通过")


def verify_ipa():
    output = Path(os.environ["RUNNER_TEMP"]) / "meimei-signed-export"
    files = list(output.glob("*.ipa"))
    if len(files) != 1:
        raise ValueError("导出目录应当只有一份 IPA")
    ipa = files[0]
    with zipfile.ZipFile(ipa) as archive:
        info_path = "Payload/Meimei.app/Info.plist"
        info = plistlib.loads(archive.read(info_path))
        if info.get("CFBundleIdentifier") != BUNDLE_ID or str(info.get("CFBundleVersion")) != os.environ["IOS_BUILD_NUMBER"]:
            raise ValueError("导出的 IPA 包名或构建编号不一致")
        if info.get("UIDeviceFamily") != [1]:
            raise ValueError("首版仅支持 iPhone，导出 IPA 的 UIDeviceFamily 必须为 [1]")
        if not {"Payload/Meimei.app/embedded.mobileprovision", "Payload/Meimei.app/_CodeSignature/CodeResources"}.issubset(archive.namelist()):
            raise ValueError("导出的 IPA 缺少描述文件或代码签名")
    metadata = {
        "bundle_id": BUNDLE_ID, "version": info["CFBundleShortVersionString"],
        "build": info["CFBundleVersion"], "commit": os.environ["GITHUB_SHA"],
        "sha256": hashlib.sha256(ipa.read_bytes()).hexdigest(), "signed": True,
        "distribution": "app-store-connect", "directly_installable": False,
        "device_families": info["UIDeviceFamily"],
        "uploaded_to_app_store_connect": False,
    }
    (output / "build.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")
    print("正式签名 IPA 的包名、构建编号与签名文件校验通过")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "build-number", "prepare", "verify-ipa"])
    args = parser.parse_args()
    try:
        if args.command == "check":
            require_environment(os.environ.get("SHOULD_UPLOAD") == "true")
            print("所需 Secrets 已配置")
        elif args.command == "build-number":
            number = build_number(int(os.environ["GITHUB_RUN_NUMBER"]), int(os.environ["GITHUB_RUN_ATTEMPT"]))
            with open(os.environ["GITHUB_ENV"], "a") as out:
                out.write("IOS_BUILD_NUMBER=" + number + "\n")
            print("TestFlight 构建编号：" + number)
        elif args.command == "prepare":
            prepare()
        else:
            verify_ipa()
    except (ValueError, KeyError, zipfile.BadZipFile) as exc:
        print("::error::" + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
