#!/usr/bin/env python3
"""在 Mac 上选择签名文件，将 Base64 复制到剪贴板，不在终端显示凭据。"""

import argparse
import base64
from pathlib import Path
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=["p12", "profile", "p8"])
    args = parser.parse_args()
    extension, name = {
        "p12": (".p12", "IOS_P12_BASE64"),
        "profile": (".mobileprovision", "IOS_PROFILE_BASE64"),
        "p8": (".p8", "ASC_P8_BASE64"),
    }[args.kind]
    selected = subprocess.run(["osascript", "-e", 'POSIX path of (choose file with prompt "请选择 ' + extension + ' 文件")'],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if selected.returncode:
        print("已取消，未修改剪贴板")
        return 1
    source = Path(selected.stdout.strip())
    if source.suffix.lower() != extension:
        print("文件类型不符，请选择 " + extension, file=sys.stderr)
        return 1
    subprocess.run(["pbcopy"], input=base64.b64encode(source.read_bytes()), check=True)
    print("已复制。请在 GitHub Secret 的 Value 中粘贴，Name 填 " + name + "；不要粘贴到聊天或命令行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
