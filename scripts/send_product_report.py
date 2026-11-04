#!/usr/bin/env python3
"""本机通过固定 SSH 发布产品推送，或查询状态与近期选题。"""
import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report",type=Path,nargs="?")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--status",action="store_true")
    action.add_argument("--history",action="store_true")
    args = parser.parse_args()
    if bool(args.report) == bool(args.status or args.history):
        parser.error("提供正文文件，或选择 --status / --history")
    raw = b""
    option = " --status" if args.status else " --history" if args.history else ""
    if args.report:
        raw = args.report.read_bytes()
        if len(raw)>131072:
            parser.error("产品推送文件超过 128KB")
        data = json.loads(raw)
        if not isinstance(data,dict) or set(data)-{"date","content","simulation"}:
            parser.error("仅接受 date、content、simulation")
    command = ["ssh","-T","-o","BatchMode=yes","-o","ConnectTimeout=20","aliyun_3129",
        "sudo -u ai-platform env AI_PLATFORM_DATA=/opt/ai-platform /opt/ai-platform/.venv/bin/python /opt/ai-platform/scripts/publish_product_report.py" + option]
    result = subprocess.run(command,input=raw,timeout=180)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
