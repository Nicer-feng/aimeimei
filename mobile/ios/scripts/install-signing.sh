#!/bin/bash
set -euo pipefail
umask 077

python3 mobile/ios/scripts/signing-config.py prepare
signing_dir="$RUNNER_TEMP/meimei-signing"
keychain_path="$RUNNER_TEMP/meimei-signing.keychain-db"
keychain_password="$(openssl rand -hex 32)"

# 临时钥匙串只存在于 GitHub 托管运行机，不使用用户本机钥匙串密码。
security create-keychain -p "$keychain_password" "$keychain_path"
security set-keychain-settings -lut 21600 "$keychain_path"
security unlock-keychain -p "$keychain_password" "$keychain_path"
security import "$signing_dir/distribution.p12" -P "$IOS_P12_PASSWORD" \
  -A -t cert -f pkcs12 -k "$keychain_path" >/dev/null
security set-key-partition-list -S apple-tool:,apple:,codesign: -k "$keychain_password" "$keychain_path" >/dev/null
security list-keychains -d user -s "$keychain_path" "$HOME/Library/Keychains/login.keychain-db"

python3 - <<'PY'
import os, pathlib, plistlib, shutil, subprocess, sys
root = pathlib.Path(os.environ['RUNNER_TEMP']) / 'meimei-signing'
options = plistlib.loads((root / 'ExportOptions.plist').read_bytes())
identities = subprocess.check_output(['security', 'find-identity', '-v', '-p', 'codesigning',
                                     str(pathlib.Path(os.environ['RUNNER_TEMP']) / 'meimei-signing.keychain-db')], text=True)
if options['signingCertificate'] not in identities:
    sys.exit('::error::.p12 没有包含描述文件指定的有效签名私钥；请重新导出匹配的 Apple Distribution 证书和私钥')
profile_uuid = next(iter(options['provisioningProfiles'].values()))
for suffix in ['Library/MobileDevice/Provisioning Profiles', 'Library/Developer/Xcode/UserData/Provisioning Profiles']:
    folder = pathlib.Path.home() / suffix
    folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(root / 'app.mobileprovision', folder / (profile_uuid + '.mobileprovision'))
print('发行证书私钥与描述文件匹配，已导入临时钥匙串')
PY
