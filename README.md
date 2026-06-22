# AI槑槑

AI槑槑 是一个自用轻量 AI 平台，使用 Python 标准库和 SQLite 实现。项目保持单文件应用形态，无 Docker、无前端框架、无外部 Python 依赖。

当前版本：`2.3.2`

## 目录说明

- `app.py`：主应用文件，包含后端接口、SQLite 迁移逻辑和前端页面。
- `index.html`：槑槑小记个人首页，当前可通过 `/xiaoji` 预览，备案通过后可作为主域名首页。
- `cat.html`：槑槑相册前端页面，当前挂载在 `/cat`。
- `app.server.py`：服务器旧版/备份应用文件，保留用于对照。
- `ai-platform.service`：systemd 服务配置示例。
- `deploy/nginx/aimeimei.conf`：域名访问用的 Nginx 配置示例，`feng.asia` 和 `www.feng.asia` 首页指向槑槑小记，AI 平台挂载在 `/ai`，槑槑相册挂载在 `/cat`。
- `verify.sh`：线上健康检查和基础接口验证脚本。
- `res/`：项目资源文件，包括无文字槑槑头像、登录插画、空状态插画、favicon 和原始猫咪照片。
- `VERSION`：当前项目版本号。
- `CHANGELOG.md`：版本变更记录。

## 本地运行

```bash
AI_PLATFORM_DATA=/tmp/ai-platform AI_PLATFORM_LISTEN=127.0.0.1:8080 python3 app.py
```

然后访问：

```text
http://127.0.0.1:8080
```

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

槑槑相册 OSS 上传配置通过环境变量或 `secrets.json` 的 `cat_oss` 节点提供：

```text
CAT_OSS_BUCKET
CAT_OSS_REGION
CAT_OSS_ENDPOINT
CAT_OSS_ACCESS_KEY_ID
CAT_OSS_ACCESS_KEY_SECRET
CAT_OSS_PUBLIC_BASE
CAT_OSS_DIR
```

常用部署流程：

```bash
python3 -m py_compile app.py
scp app.py aliyun_3129:/tmp/ai-platform-build/app.py
ssh aliyun_3129 'sudo install -o ai-platform -g ai-platform -m 0644 /tmp/ai-platform-build/app.py /opt/ai-platform/app.py && sudo systemctl restart ai-platform && systemctl is-active ai-platform'
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
