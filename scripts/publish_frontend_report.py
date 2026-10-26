#!/usr/bin/env python3
"""经已有 SSH 权限投递日报，正文从 stdin 读取，不创建公开写入接口。"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform.daily_reports import publish_report, deliver_pending


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--retry", action="store_true")
    args = parser.parse_args()
    try:
        if args.retry:
            result = {"delivery": deliver_pending()}
        else:
            raw = sys.stdin.buffer.read(131073)
            if len(raw)>131072:
                raise ValueError("正文超长")
            result = publish_report(json.loads(raw))
        print(json.dumps({"ok": True, **result}, ensure_ascii=False))
    except (ValueError, TypeError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False))
        return 1
    except Exception:
        print(json.dumps({"ok": False, "error": "日报保存失败，请检查服务配置"}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
