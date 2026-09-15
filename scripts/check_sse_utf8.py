#!/usr/bin/env python3
"""Regression check for UTF-8 safe SSE chunk decoding."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_platform.handlers.chat import sse_text_decoder


def decode_in_chunks(payload, boundaries):
    decoder = sse_text_decoder()
    decoded = []
    start = 0
    for width in boundaries:
        if start >= len(payload):
            break
        decoded.append(decoder.decode(payload[start:start + width]))
        start += width
    if start < len(payload):
        decoded.append(decoder.decode(payload[start:]))
    decoded.append(decoder.decode(b"", final=True))
    return "".join(decoded)


def main():
    text = "第八组：UNI-V蓝鲸超擎混动实测给出了答案。🚗"
    event = "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False) + "\n\n"
    payload = event.encode("utf-8")
    for boundaries in ([1] * len(payload), [2, 3, 1, 5, 4, 2], [7, 11, 13, 17, 19]):
        decoded = decode_in_chunks(payload, boundaries)
        assert decoded == event, (boundaries, decoded, event)
        parsed = json.loads(decoded.splitlines()[0][5:].strip())
        assert parsed["choices"][0]["delta"]["content"] == text
    print("sse utf-8 chunk regression check: ok")


if __name__ == "__main__":
    main()
