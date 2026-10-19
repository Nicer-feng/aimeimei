#!/usr/bin/env bash
set -euo pipefail
umask 077

if ! command -v keytool >/dev/null 2>&1; then
  printf '%s\n' '请在已安装 JDK 的云端终端运行，例如 GitHub Codespaces。无需在 Mac 安装 JDK。' >&2
  exit 1
fi
directory="$HOME/aimeimei-android-signing"
keystore="$directory/aimeimei-release.jks"
if [ -e "$keystore" ]; then
  printf '%s\n' '签名文件已经存在，已停止，避免覆盖已有长期签名。' >&2
  exit 1
fi
mkdir -p "$directory"
chmod 700 "$directory"
printf '%s\n' '即将由 keytool 交互询问密码。密码不会被本脚本打印。密钥别名固定为 aimeimei。'
keytool -genkeypair -storetype JKS -keystore "$keystore" -alias aimeimei \
  -keyalg RSA -keysize 3072 -validity 10000 -dname 'CN=Aimeimei Family,O=Personal,C=CN'
base64 < "$keystore" | tr -d '\n' > "$directory/signing-keystore.base64"
printf '%s\n' "签名文件与 Base64 文件已写入：$directory" \
  '请单独下载备份签名文件、保管密码；Base64 内容填入 GitHub Actions Secret，不要提交仓库或发送聊天。'
