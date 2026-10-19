#!/usr/bin/env python3
"""从当前 Xcode 实际可用的 iPhone 模拟器中选择设备，不硬编码运行时 UUID。"""
import json
import subprocess

value = json.loads(subprocess.check_output(["xcrun", "simctl", "list", "devices", "available", "--json"]))
sdk_version = tuple(int(part) for part in subprocess.check_output(
    ["xcrun", "--sdk", "iphonesimulator", "--show-sdk-version"], text=True).strip().split("."))
choices = []
for runtime, devices in value["devices"].items():
    if ".iOS-" not in runtime:
        continue
    version = tuple(int(part) for part in runtime.rsplit("iOS-", 1)[1].split("-"))
    # 镜像可能同时装有下一代预览运行时，只选当前固定 Xcode 对应的稳定系统。
    if version > sdk_version:
        continue
    for device in devices:
        if device.get("isAvailable") and device["name"].startswith("iPhone"):
            choices.append((version, "Pro Max" in device["name"], device["name"], device["udid"]))
if not choices:
    raise SystemExit("当前 Xcode 没有可用 iPhone 模拟器，请检查构建机镜像。")
print(max(choices)[-1])
