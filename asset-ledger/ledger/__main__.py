"""命令行入口。"""

import argparse
import getpass
from pathlib import Path
import sqlite3
import sys

from .data import database, initialize, reset_password
from .edge import PublicSite
from .http import LedgerServer


def data_path(raw):
    return Path(raw).expanduser().resolve()


def ensure_initialized(data_dir):
    if not (data_dir / "ledger.sqlite3").is_file():
        raise ValueError("数据目录尚未初始化，请先运行 init。")
    with database(data_dir) as conn:
        if conn.execute("SELECT 1 FROM metadata WHERE key = 'samples'").fetchone() is None:
            raise ValueError("数据目录尚未初始化，请先运行 init。")


def set_password(data_dir, username, from_stdin):
    ensure_initialized(data_dir)
    if from_stdin:
        password = sys.stdin.readline(258).rstrip("\r\n")
    else:
        password = getpass.getpass("新密码：")
        if getpass.getpass("再次输入：") != password:
            raise ValueError("两次输入的密码不一致。")
    if "\x00" in password or any(0xD800 <= ord(char) <= 0xDFFF for char in password):
        raise ValueError("密码含有无效字符。")
    with database(data_dir) as conn:
        reset_password(conn, username, password)


def serve(data_dir, port, public_site=None):
    ensure_initialized(data_dir)
    with database(data_dir) as conn:
        if conn.execute("SELECT 1 FROM users WHERE password_hash IS NULL").fetchone():
            raise ValueError("请先为 admin 和 region-reader 设置密码。")
    with LedgerServer(port, data_dir, public_site) as server:
        print(f"台账已监听 http://127.0.0.1:{server.server_port}/", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


def main():
    parser = argparse.ArgumentParser(description="机房与联网设备台账")
    actions = parser.add_subparsers(dest="command", required=True)
    init = actions.add_parser("init", help="建库并导入模拟数据")
    init.add_argument("--data-dir", required=True, type=data_path)
    passwd = actions.add_parser("passwd", help="设置本地台账账号密码")
    passwd.add_argument("--data-dir", required=True, type=data_path)
    passwd.add_argument("--stdin", action="store_true", help="从标准输入读取一行密码")
    passwd.add_argument("username", choices=("admin", "region-reader"))
    run = actions.add_parser("serve", help="启动仅本机监听的服务")
    run.add_argument("--data-dir", required=True, type=data_path)
    run.add_argument("--port", type=int, default=18754)
    run.add_argument("--public-url", help="Caddy HTTPS 转发地址，包含以斜杠结尾的路径")
    args = parser.parse_args()
    try:
        if args.command == "init":
            initialize(args.data_dir)
            print(f"台账已初始化：{args.data_dir}")
        elif args.command == "passwd":
            set_password(args.data_dir, args.username, args.stdin)
            print(f"密码已更新：{args.username}")
        else:
            if not 1 <= args.port <= 65535:
                raise ValueError("端口须在 1 至 65535 之间。")
            serve(args.data_dir, args.port, PublicSite.parse(args.public_url) if args.public_url else None)
    except (OSError, ValueError, sqlite3.Error, EOFError) as error:
        print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
