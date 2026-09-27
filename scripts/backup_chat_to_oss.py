#!/usr/bin/env python3
import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_platform.backup import run_daily_backup


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="加密数据库备份到 OSS；默认保留现有脱敏备份行为")
    parser.add_argument("--mode", choices=("sanitized", "full"), default="sanitized",
                        help="full 保留账号、密钥和共享产品关系；需单独保管加密密钥")
    run_daily_backup(mode=parser.parse_args().mode)
