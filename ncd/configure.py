"""通过隐藏输入配置访问口令，只写入独立运行目录。"""

import argparse
import getpass
import os
from pathlib import Path

from .auth import MAX_PASSWORDS, configure_passwords


def main():
    parser = argparse.ArgumentParser(description="设置题库的统一访问密码（替换全部现有密码）")
    parser.add_argument("--count", type=int, choices=range(1, MAX_PASSWORDS + 1), default=2, help="要配置的密码数量，默认 2；将替换全部现有密码")
    parser.add_argument("--data-dir", default=os.environ.get("NCD_DATA_DIR", str(Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform")) / "ncd-data")))
    args = parser.parse_args()
    passwords = [getpass.getpass(f"第 {index + 1} 个访问密码：") for index in range(args.count)]
    configure_passwords(args.data_dir, passwords)
    print(f"{args.count} 个密码已配置；文件仅保存哈希，原有登录将自动失效。")


if __name__ == "__main__":
    main()
