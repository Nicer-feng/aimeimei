#!/usr/bin/env python3
"""从本机将已审核的日报经已有 SSH 连接投递，stdout 仅含保存/投递状态。"""
import argparse
import json
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    raw = args.report.read_bytes()
    if len(raw)>131072:
        parser.error("日报文件超过 128KB")
    data = json.loads(raw)
    if not isinstance(data,dict) or set(data)-{"date","content","simulation"}:
        parser.error("日报仅接受 date、content、simulation")
    command = ["ssh", "-T", "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", "aliyun_3129",
        "sudo -u ai-platform env AI_PLATFORM_DATA=/opt/ai-platform /opt/ai-platform/.venv/bin/python /opt/ai-platform/scripts/publish_frontend_report.py"]
    result = subprocess.run(command, input=raw, timeout=180)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
