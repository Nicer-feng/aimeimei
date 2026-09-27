#!/usr/bin/env python3
"""Create, verify or recover an authenticated database archive using only local files."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ai_platform.backup import create_local_backup, restore_local_backup


def main():
    parser = argparse.ArgumentParser(description="离线数据库备份与恢复校验；不联网，不覆盖现有文件")
    subcommands = parser.add_subparsers(dest="command", required=True)
    create = subcommands.add_parser("create", help="创建加密归档；默认仍为脱敏模式")
    create.add_argument("--source", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    create.add_argument("--key-file", type=Path, required=True)
    create.add_argument("--mode", choices=("sanitized", "full"), default="sanitized")
    for command in ("verify", "restore"):
        sub = subcommands.add_parser(command, help="校验归档" if command == "verify" else "恢复到全新的离线数据库文件")
        sub.add_argument("--archive", type=Path, required=True)
        sub.add_argument("--key-file", type=Path, required=True)
        sub.add_argument("--expected-mode", choices=("sanitized", "full"), default="full")
        sub.add_argument("--max-size-mb", type=int, default=2048)
        if command == "restore":
            sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "create":
            result = create_local_backup(args.source, args.output, args.key_file, mode=args.mode)
        elif args.command == "restore":
            result = restore_local_backup(args.archive, args.output, args.key_file,
                                          expected_mode=args.expected_mode, max_bytes=args.max_size_mb * 1024**2)
        else:
            with tempfile.TemporaryDirectory(prefix="backup-verify-") as directory:
                result = restore_local_backup(args.archive, Path(directory) / "verified.db", args.key_file,
                                              expected_mode=args.expected_mode, max_bytes=args.max_size_mb * 1024**2)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as error:
        print("备份操作失败：{}".format(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
