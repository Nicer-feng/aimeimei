# AI槑槑

AI槑槑 是一个自用轻量 AI 平台，使用 Python 标准库和 SQLite 实现。项目保持轻量模块化形态，无 Docker、无前端框架；文件分享产品使用 Argon2 和官方 OSS SDK。

AI槑槑当前版本：`2.25.0`

## 写稿模式

输入区点击“写稿”启用，再像平时一样提供材料和客户反馈。模式按会话保存，新对话沿用当前浏览器中该账号的开关偏好。不同客户项目建议新建对话，避免材料混用。

“本单要求”可查看、修正自动整理的受众、风格、事实和检查词，并选择聊天消息或历史稿件作为底稿。保存并锁定正文后，转分镜会校验台词；发现改写则恢复原文分段，画面和花字标为待补。明确的单段修改自动合并；无法准确定位的局部回复不会覆盖完整底稿。字数、检查词和待补数据结果显示在回复下方，不代表事实已核实或客户已验收。

每轮写稿会增加一次非流式要求整理调用，用量和费用纳入统计；失败时提示并沿用保存要求。普通聊天关闭模式后不调用整理流程。没有批量学习历史对话、按客户自动检索案例或多账号结构查重。

本地验证：`python3 scripts/test_writing.py` 使用临时数据库、模拟模型和回环端口，不访问真实模型。

## 独立产品：槑槑云

槑槑云独立版本为 `0.1.6`，后台 `/admin/share`，外部分享 `/share/{shareCode}`。与 AI槑槑共仓库，页面、业务、数据表和版本记录独立，复用现有登录、SQLite 和 OSS。已上线并完成真实 OSS 与浏览器验收。详见 [产品说明](file_share/README.md)、[验收记录](file_share/ACCEPTANCE.md) 和 [部署清单](file_share/DEPLOYMENT.md)。

## 多产品共仓管理

主页、AI槑槑、小猫书和槑槑云继续使用本仓库，分别维护产品版本和发布标签。现有目录无需搬迁，管理规则见 [共仓管理约定](REPOSITORY.md)。

## 目录说明

- `app.py`：后端入口，包含 HTTP 接口、SQLite 迁移和第三方模型调用。
- `ai_platform/`：后端模块，包含运行配置、数据库、数据转换、用量统计、OSS、听悟和联网搜索能力。
- `ai_platform/handlers/`：按账号、小猫书、后台、资料库、音视频和聊天划分的 HTTP Handler。
- `ai.html`：AI槑槑聊天页结构。
- `res/ai.css`：AI槑槑聊天页设计系统与组件样式。
- `res/ai.js`：AI槑槑聊天页状态、交互和接口调用。
- `index.html`：槑槑小记个人首页，当前可通过 `/xiaoji` 预览，备案通过后可作为主域名首页。
- `cat.html`：小猫书前端页面，当前挂载在 `/cat`。
- `app.server.py`：服务器旧版/备份应用文件，保留用于对照。
- `ai-platform.service`：systemd 服务配置示例。
- `deploy/nginx/aimeimei.conf`：域名访问用的 Nginx 配置示例，`feng.asia` 和 `www.feng.asia` 首页指向槑槑小记，AI 平台挂载在 `/ai`，小猫书挂载在 `/cat`。
- `deploy/caddy/Caddyfile`：Caddy HTTPS 配置示例，自动申请证书并将 `/cat/` 反向代理到本机应用。
- `scripts/backup_chat_to_oss.py`：生成脱敏 SQLite 快照并备份到 OSS。
- `scripts/check_release_version.py`：发布前校验页面版本号和静态资源缓存参数是否与 `VERSION` 一致。
- `deploy/systemd/ai-platform-backup.*`：每日 OSS 备份的 systemd service 与 timer。
- `verify.sh`：线上健康检查和基础接口验证脚本。
- `res/`：项目资源文件，包括无文字槑槑头像、登录插画、空状态插画、favicon 和原始猫咪照片。
- `res/markdown-renderer.js`、`res/markdown.css`：聊天、收藏和音视频分析共用的 Markdown 渲染与视觉层。
- `markdown-test.html`：Markdown 兼容性回归页，仅在开发模式下开放。
- `VERSION`：当前项目版本号。
- `BUILD_ID`：当前部署构建编号，发布新版本时必须更新，用于已打开页面的更新检测。
- `CHANGELOG.md`：版本变更记录。

## 本地运行

```bash
AI_PLATFORM_DATA=/tmp/ai-platform AI_PLATFORM_LISTEN=127.0.0.1:8080 python3 app.py
```

然后访问：

```text
http://127.0.0.1:8080
```

需要回归 Markdown 时启用开发模式：

```bash
AI_PLATFORM_DATA=/tmp/ai-platform AI_PLATFORM_LISTEN=127.0.0.1:8080 AI_PLATFORM_DEV_MODE=1 python3 app.py
```

然后访问 `http://127.0.0.1:8080/dev/markdown`。未启用开发模式时该路径返回 404。

## 线上部署

当前线上服务路径：

```text
/opt/ai-platform/app.py
```

systemd 服务名：

```text
ai-platform
```

域名访问当前使用 Nginx：

```text
/etc/nginx/conf.d/aimeimei.conf
```

首页静态文件托管目录：

```text
/var/www/aimeimei
```

小猫书 OSS 上传配置通过环境变量或 `secrets.json` 的 `cat_oss` 节点提供：

```text
CAT_OSS_BUCKET
CAT_OSS_REGION
CAT_OSS_ENDPOINT
CAT_OSS_ACCESS_KEY_ID
CAT_OSS_ACCESS_KEY_SECRET
CAT_OSS_PUBLIC_BASE
CAT_OSS_DIR
```

AI槑槑音视频分析可复用小猫书 OSS，默认上传到 `tingwu/` 目录；通义听悟配置通过环境变量或 `secrets.json` 的 `tingwu` / `media_oss` 节点提供：

```text
TINGWU_APP_KEY
TINGWU_REGION
TINGWU_ENDPOINT
TINGWU_ACCESS_KEY_ID
TINGWU_ACCESS_KEY_SECRET

MEDIA_OSS_BUCKET
MEDIA_OSS_REGION
MEDIA_OSS_ENDPOINT
MEDIA_OSS_ACCESS_KEY_ID
MEDIA_OSS_ACCESS_KEY_SECRET
MEDIA_OSS_PUBLIC_BASE
MEDIA_OSS_DIR
MEDIA_MAX_UPLOAD_MB
```

如果不单独设置 `MEDIA_OSS_*`，会优先复用 `CAT_OSS_*`，仅目录默认改为 `tingwu`。

### 每日聊天备份

备份任务复用现有 `CAT_OSS_*` 配置，不需要在 OSS 控制台预先创建目录。OSS 会在首次上传时自动形成 `backups/ai-platform/YYYY/MM/` 前缀。

备份内容是全部账号共用数据库的脱敏在线快照，保留会话、消息、收藏、AI 档案、Token 统计和音视频分析结果；密码哈希、模型密钥、登录会话、分享令牌、临时文件 URL 不进入备份。备份文件上传前使用独立密钥执行 AES-256-CBC + PBKDF2 加密，同时请求 OSS 私有 ACL 与服务端 AES256 加密，默认保留 90 天。

加密密钥保存在服务器 `/etc/ai-platform/backup.key`，不进入 Git 和 OSS。应将该文件单独保存到安全位置；服务器完全丢失且没有密钥时，OSS 中的备份无法解密。

恢复时先下载 `.sqlite.gz.enc` 文件，再执行：

```bash
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -md sha256 \
  -pass file:/etc/ai-platform/backup.key \
  -in chat-backup.sqlite.gz.enc -out chat-backup.sqlite.gz
gunzip chat-backup.sqlite.gz
sqlite3 chat-backup.sqlite "PRAGMA integrity_check;"
```

```bash
sudo systemctl enable --now ai-platform-backup.timer
sudo systemctl start ai-platform-backup.service
sudo systemctl status ai-platform-backup.service
sudo systemctl list-timers ai-platform-backup.timer
```

百炼 Qwen 原生联网不需要单独的搜索 Key。模型管理中将“联网能力”设为“百炼原生联网”，并确保该模型的 Base URL、Model 和百炼 API Key 可正常调用；后台联网搜索仍需保持启用，用于控制自动、手动或强制联网策略。非原生联网模型继续使用 Tavily 或 Brave 的搜索 Key。

常用部署流程：

```bash
python3 scripts/check_release_version.py
python3 -m py_compile app.py
node --check res/ai.js
scp app.py ai.html VERSION BUILD_ID CHANGELOG.md aliyun_3129:/tmp/ai-platform-build/
scp -r ai_platform aliyun_3129:/tmp/ai-platform-build/
scp res/ai.css res/ai.js aliyun_3129:/tmp/ai-platform-build/res/
ssh aliyun_3129 'sudo install -o ai-platform -g ai-platform -m 0644 /tmp/ai-platform-build/app.py /opt/ai-platform/app.py && sudo install -o ai-platform -g ai-platform -m 0644 /tmp/ai-platform-build/ai.html /opt/ai-platform/ai.html && sudo install -o ai-platform -g ai-platform -m 0644 /tmp/ai-platform-build/res/ai.css /opt/ai-platform/res/ai.css && sudo install -o ai-platform -g ai-platform -m 0644 /tmp/ai-platform-build/res/ai.js /opt/ai-platform/res/ai.js && sudo systemctl restart ai-platform && systemctl is-active ai-platform'
```

## 敏感文件

以下文件只保存在服务器或本地运行目录，不应提交到 Git：

- `admin.key`
- `family_password.txt`
- `secrets.json`
- `config.json`
- `ai-platform.db`
- 模型 API key、搜索 API key 等任何密钥

`.gitignore` 已排除这些文件和 SQLite 运行数据。
