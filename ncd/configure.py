"""通过隐藏输入配置两个访问口令，只写入独立运行目录。"""

import argparse
import getpass
import os
from pathlib import Path

from .auth import configure_passwords


def main():
    parser = argparse.ArgumentParser(description="设置题库的两个统一访问密码")
    parser.add_argument("--data-dir", default=os.environ.get("NCD_DATA_DIR", str(Path(os.environ.get("AI_PLATFORM_DATA", "/opt/ai-platform")) / "ncd-data")))
    args = parser.parse_args()
    first = getpass.getpass("第一个访问密码：")
    second = getpass.getpass("第二个访问密码：")
    configure_passwords(args.data_dir, [first, second])
    print("两个密码已配置；文件仅保存哈希，原有登录将自动失效。")


if __name__ == "__main__":
    main()
