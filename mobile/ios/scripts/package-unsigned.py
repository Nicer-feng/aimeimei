#!/usr/bin/env python3
"""只打包未签名应用，禁止把它标为可安装或已完成 TestFlight 分发。"""
import argparse
import hashlib
import json
import plistlib
import shutil
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

parser = argparse.ArgumentParser()
parser.add_argument("--archive", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--commit", required=True)
args = parser.parse_args()
app = args.archive / "Products/Applications/Meimei.app"
if not (app / "Meimei").is_file():
    raise SystemExit("归档缺少真机应用可执行文件")
if (app / "embedded.mobileprovision").exists() or (app / "_CodeSignature").exists():
    raise SystemExit("当前流程只允许未签名应用，请先核对归档配置")
if b"offline-user" in (app / "Meimei").read_bytes():
    raise SystemExit("正式真机包意外包含离线测试账号，拒绝交付")
with (app / "Info.plist").open("rb") as handle:
    info = plistlib.load(handle)
if info.get("CFBundleIdentifier") != "asia.feng.aimeimei" or info.get("MinimumOSVersion") != "17.0":
    raise SystemExit("包名或最低系统版本不符合首版约定")
if info.get("UIDeviceFamily") != [1]:
    raise SystemExit("首版仅支持 iPhone，归档的 UIDeviceFamily 必须为 [1]；请检查应用目标的 TARGETED_DEVICE_FAMILY")
args.output.mkdir(parents=True, exist_ok=True)
ipa = args.output / "aimeimei-ios-unsigned.ipa"
with tempfile.TemporaryDirectory(prefix="meimei-unsigned-") as directory:
    payload = Path(directory) / "Payload"
    payload.mkdir()
    shutil.copytree(app, payload / app.name)
    with ZipFile(ipa, "w", ZIP_DEFLATED) as archive:
        for file in sorted(payload.rglob("*")):
            if file.is_file():
                archive.write(file, file.relative_to(directory))
(args.output / "README.txt").write_text(
    "这是未签名的 iPhone 应用，仅供后续签名输入，不能直接安装、不能直接上传 TestFlight。\n"
    "免费 Apple 账号真机测试仍需在本机完成有效签名和安装，通常每 7 天续签。\n"
    "请勿将 Apple 账号密码或验证码提交到 GitHub。详见仓库 mobile/ios/README.md。\n",
    encoding="utf-8",
)
(args.output / "build.json").write_text(json.dumps({
    "product": "AI槑槑 iOS", "bundle_id": info["CFBundleIdentifier"],
    "version": info["CFBundleShortVersionString"], "build": info["CFBundleVersion"],
    "minimum_ios": info["MinimumOSVersion"], "commit": args.commit,
    "device_families": info["UIDeviceFamily"],
    "signed": False, "directly_installable": False, "testflight_uploaded": False,
    "sha256": hashlib.sha256(ipa.read_bytes()).hexdigest(),
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
