#!/bin/bash
set -euo pipefail

ios_root="$(cd "$(dirname "$0")/.." && pwd)"
tool_dir="${RUNNER_TEMP:-${TMPDIR:-/tmp}}/aimeimei-xcodegen-2.46.0"
tool_zip="$tool_dir/xcodegen.zip"
mkdir -p "$tool_dir"
if [ ! -x "$tool_dir/xcodegen/bin/xcodegen" ]; then
  curl --fail --location --retry 3 --max-time 180 \
    https://github.com/yonaskolb/XcodeGen/releases/download/2.46.0/xcodegen.zip -o "$tool_zip"
  printf '%s  %s\n' 4d9e34b62172d645eed6457cac13fc222569974098ef4ee9c3368bedf0196806 "$tool_zip" | shasum -a 256 --check
  unzip -q -o "$tool_zip" -d "$tool_dir"
fi
"$tool_dir/xcodegen/bin/xcodegen" generate --spec "$ios_root/project.yml" --project "$ios_root"
