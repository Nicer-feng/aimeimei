"""Generate public update metadata from the actual signed APK, never from secrets."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def prepare(folder, sdk):
    files = list(Path(folder).glob("*.apk"))
    if len(files) != 1:
        raise ValueError("expected exactly one release APK")
    apk = files[0]
    tools = Path(sdk) / "build-tools" / "36.0.0"
    badging = subprocess.check_output([str(tools / "aapt"), "dump", "badging", str(apk)], text=True)
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    if not package or package[1] != "asia.feng.aimeimei":
        raise ValueError("release package mismatch")
    version = package[3]
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("invalid release version")
    signature = subprocess.check_output([str(tools / "apksigner"), "verify", "--verbose", "--print-certs", str(apk)], text=True)
    certificates = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})", signature)
    if len(certificates) != 1:
        raise ValueError("expected one verified APK signer")
    target = apk.with_name(f"aimeimei-{version}.apk")
    if apk != target:
        apk.rename(target)
    with target.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    metadata = {"schema": 1, "versionCode": int(package[2]), "versionName": version,
                "packageName": package[1], "apkName": target.name,
                "sha256": digest,
                "certificateSha256": certificates[0].lower(), "size": target.stat().st_size}
    target.with_name("update.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared Android {version}; APK signature verified")


if __name__ == "__main__":
    prepare(sys.argv[1], os.environ.get("ANDROID_HOME") or os.environ["ANDROID_SDK_ROOT"])
