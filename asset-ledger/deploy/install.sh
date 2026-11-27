#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    printf '%s\n' '请使用 sudo bash deploy/install.sh 安装。' >&2
    exit 1
fi

source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
app_dir=/opt/asset-ledger
state_dir=/var/lib/asset-ledger
service_user=asset-ledger

/usr/bin/python3 -c 'import sqlite3, sys; sys.exit("需要 Python 3.9 或更新版本。") if sys.version_info < (3, 9) else None'
for path in ledger/__main__.py ledger/schema.sql ledger/_vendor/olefile.py ledger/_vendor/olefile.LICENSE \
    static/rack-planner.js static/rack-planner.css \
    ledger/patrol.py static/room-patrol.js static/room-patrol.css \
    static/index.html static/room-overview.js static/room-overview-3d.js static/room-overview.css \
    static/rack-geometry.js static/rack-textures.js static/rack-3d-model.js static/rack-3d.js \
    ledger/ports.py static/device-locator.js static/device-ports.js static/device-ports.css static/pdf-preview.js static/pdf-preview.css deploy/asset-ledger.service \
    samples/site-a-quantity.pdf samples/site-a-design.pdf samples/site-a-contract.pdf \
    samples/site-a-acceptance.pdf samples/site-a-device.pdf samples/site-b-acceptance.pdf; do
    if [[ ! -f "$source_dir/$path" ]]; then
        printf '部署包缺少文件 %s\n' "$path" >&2
        exit 1
    fi
done

if ! id "$service_user" >/dev/null 2>&1; then
    if ! getent group "$service_user" >/dev/null; then
        groupadd --system "$service_user"
    fi
    useradd --system --gid "$service_user" --home-dir "$state_dir" \
        --no-create-home --shell "$(command -v nologin)" "$service_user"
fi

install -d -o root -g root -m 0755 "$app_dir/ledger" "$app_dir/ledger/_vendor" \
    "$app_dir/static/vendor/three" "$app_dir/samples"
install -d -o "$service_user" -g "$service_user" -m 0750 "$state_dir"
install -m 0644 "$source_dir"/ledger/*.py "$source_dir"/ledger/*.sql "$app_dir/ledger/"
install -m 0644 "$source_dir"/ledger/_vendor/olefile.py "$source_dir"/ledger/_vendor/olefile.LICENSE "$app_dir/ledger/_vendor/"
install -m 0644 "$source_dir"/static/*.html "$source_dir"/static/*.css "$source_dir"/static/*.js "$app_dir/static/"
install -m 0644 "$source_dir"/static/vendor/three/*.js \
    "$source_dir/static/vendor/three/LICENSE" "$app_dir/static/vendor/three/"
pdf_vendor="$source_dir/static/vendor/pdfjs"
find "$pdf_vendor" -type f ! -name '._*' ! -name '.DS_Store' -print0 |
    while IFS= read -r -d '' file; do
        install -D -m 0644 "$file" "$app_dir/static/vendor/pdfjs/${file#"$pdf_vendor"/}"
    done
install -m 0644 "$source_dir"/samples/*.pdf "$app_dir/samples/"
install -m 0644 "$source_dir/deploy/asset-ledger.service" /etc/systemd/system/asset-ledger.service
systemctl daemon-reload

printf '%s\n' '运行文件已安装。首次启动前按 README 初始化数据并设置账号密码。'
