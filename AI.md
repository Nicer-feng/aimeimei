# AI槑槑项目接手手册

> 本文件是给后续 AI/Codex 的项目上下文。开始任何修改前，先完整阅读本文件，再查看 `git status`、`VERSION`、`BUILD_ID`、`CHANGELOG.md` 和相关源码。不要只凭历史对话或 README 中的旧描述操作。

## 1. 项目身份与当前状态

- 项目名称：AI槑槑。
- GitHub：`git@github.com:Nicer-feng/aimeimei.git`。
- 主分支：`main`。
- 当前基线版本：`2.21.11`。
- 当前基线构建：`20260907-002318`。
- 当前基线提交：`cc93a79 feat(search):增强联网来源摘要提取`。
- 本地实际仓库：`/Users/feng/Documents/文稿 - Unknown/aliyun3129`。
- SSH 别名：`aliyun_3129`。
- 线上代码：`/opt/ai-platform`。
- systemd 服务：`ai-platform`。
- 后端监听：`127.0.0.1:8000`。
- 公网入口：`https://feng.asia/ai/`。
- 小猫书：`https://feng.asia/cat/`。
- 主站：首页由 Caddy 从 `/var/www/aimeimei` 提供。
- HTTPS：Caddy 自动签发和续期，线上 `caddy` 为 active，`nginx` 为 inactive。
- 数据库：`/opt/ai-platform/ai-platform.db`，SQLite，当前约 43 MB。

`VERSION`、`BUILD_ID`、线上接口 `/api/version` 才是版本事实来源。本文件中的版本只表示编写本手册时的基线，未来发布后应同步更新本节。

## 2. 产品范围

AI槑槑已经不是最初的家庭密码单页，而是一个多账号轻量 AI 平台，主要能力包括：

- 用户名和密码登录、图形验证码、服务端 Cookie Session、多账号数据隔离。
- 多模型管理、API Key 管理、模型价格、视觉能力、推理能力、原生联网能力。
- 会话新建、重命名、删除、置顶、统计、全局搜索、临时分享链接。
- 流式回答、reasoning 实时预览、Markdown/GFM、代码高亮、Mermaid、移动端表格滚动。
- 图片直传 OSS、Vision 消息、缩略图与上传进度。
- AI 档案、提示词库、收藏、个人 Token Activity。
- 通义听悟音视频分析、AI 二次加工和创建分析会话。
- 火山引擎/豆包 TTS，按用户点击生成、OSS 缓存、多音色。
- 选区引用和右侧并行讨论；管理员可全局关闭这两个功能。
- Qwen 百炼原生联网，以及 Tavily/Brave 兼容搜索。
- 联网回答的 favicon 聚合入口、右侧参考来源面板和来源摘要。
- Admin Workspace：概览、账号、模型、密钥、联网、TTS、插件、Token、费用和系统设置。
- `/cat/` 小猫书：独立猫咪照片分享、账号、猫咪档案、动态、点赞、评论和 OSS 图片。
- 每日将全部账号聊天数据做脱敏、加密后备份到 OSS。

原则：继续保持轻量，不引入 Flask、FastAPI、React、Vue、Redis、MQ 或复杂中间件，除非用户明确决定迁移架构。

## 3. 技术架构

### 后端

- Python 标准库 `ThreadingHTTPServer`。
- SQLite 单数据库。
- `app.py` 是 HTTP 入口和路由分发，不再承载全部业务。
- Handler 通过 Mixin 组合进 `AppHandler`。
- 数据库迁移在 `ai_platform/database.py:init_db()` 中幂等执行，启动时自动迁移，禁止删除旧数据。
- 第三方 API 调用以标准库 `urllib` 为主。

### 前端

- 原生 HTML、CSS、JavaScript，无 React/Vue。
- 聊天页：`ai.html` + `res/ai.js` + `res/ai.css`。
- Markdown：`res/markdown-renderer.js` + `res/markdown.css`。
- 依赖存放在 `res/vendor/`，包括 Lucide、TailwindCSS、markdown-it、DOMPurify、highlight.js、Mermaid。
- UI 维持奶油白、浅粉、毛玻璃、Lucide 图标风格。
- 保留既有 DOM `id`、`data-*` 与事件选择器；前端改造优先局部完成，避免重写状态管理。
- `res/ai.js` 和 `res/ai.css` 仍然很大，后续可以继续按功能渐进拆分，但每一版都必须保持静态资源加载顺序和全局函数兼容。

## 4. 目录职责

| 路径 | 职责 |
|---|---|
| `app.py` | HTTP 服务入口、静态页与 API 路由分发 |
| `ai_platform/settings.py` | 路径、监听地址、上传限制、Cookie 名等常量 |
| `ai_platform/runtime.py` | 时间、版本、密钥文件读取、Session/Token 等运行时工具 |
| `ai_platform/database.py` | SQLite 连接、建表、旧数据迁移和索引 |
| `ai_platform/handlers/auth.py` | 登录、退出、验证码、当前用户 |
| `ai_platform/handlers/chat.py` | 主聊天、会话、统计、置顶、侧边讨论、模型流式调用 |
| `ai_platform/handlers/admin.py` | 模型、用户、联网配置、功能开关、Token/费用统计 |
| `ai_platform/handlers/library.py` | AI 档案、提示词、收藏 |
| `ai_platform/handlers/media.py` | 聊天图片、OSS 上传、听悟任务、AI 增强 |
| `ai_platform/handlers/tts.py` | TTS 管理接口、生成与音频读取 |
| `ai_platform/handlers/share.py` | 会话临时分享和公开分享页接口 |
| `ai_platform/handlers/cats.py` | 小猫书全部业务 |
| `ai_platform/web_search.py` | Tavily/Brave、Qwen 原生搜索结果、网页摘要抓取与缓存 |
| `ai_platform/storage.py` | OSS 配置、签名上传/下载、图片和音频存储 |
| `ai_platform/tingwu.py` | 通义听悟创建任务、查询和结果解析 |
| `ai_platform/tts.py` | TTS Provider 配置与火山语音请求 |
| `ai_platform/usage.py` | Token 解析、费用计算、daily usage 累计 |
| `ai_platform/backup.py` | 脱敏 SQLite 快照、压缩、加密、OSS 上传和保留策略 |
| `ai_platform/presenters.py` | 数据库行到前端 JSON 的转换、Profile 上下文 |
| `ai_platform/content.py` | 搜索摘要、媒体上下文、Mermaid 文本等内容工具 |
| `ai.html` / `res/ai.*` | AI槑槑主前端 |
| `share.html` / `res/share.*` | 公开临时分享页 |
| `cat.html` | 小猫书前端，仍为单文件页面 |
| `index.html` | feng.asia 主站首页 |
| `markdown-test.html` | 仅开发模式开放的 Markdown 回归页 |
| `scripts/check_release_version.py` | 校验版本号、可见版本和静态资源缓存参数 |
| `scripts/backup_chat_to_oss.py` | systemd 每日备份入口 |
| `deploy/` | Caddy、Nginx 和 systemd 示例配置；线上配置仍需以服务器实况为准 |
| `app.server.py` | 旧版/历史对照，不是当前入口，不要在这里实现新功能 |

## 5. 关键数据库表

数据库由 `ai_platform/database.py` 管理。核心表包括：

- `users`：AI槑槑账号。
- `sessions`：登录 Session。
- `conversations`：会话，含 `user_id`、置顶状态和模型。
- `messages`：用户/AI 消息、reasoning、Token、费用、实际模型等。
- `message_sources`：回答对应的参考来源和摘要。
- `source_snippet_cache`：按 URL 缓存来源摘要，避免重复抓取。
- `chat_message_images`：聊天图片 OSS 元数据。
- `message_tts`：消息 TTS 缓存。
- `favorite_messages`：收藏。
- `prompt_templates`：默认/个人提示词预留。
- `user_profiles`：AI 档案。
- `side_discussions`、`side_discussion_messages`：并行讨论。
- `conversation_shares`：限时分享令牌。
- `media_analysis_tasks`：通义听悟及 AI 增强结果。
- `daily_usage`：个人 Token 热力图日统计。
- `models`：模型、能力与价格配置。
- `login_captchas`：登录验证码。
- `cat_*`、`cats`：小猫书账号、猫咪、动态、图片、点赞和评论。

所有用户私有查询必须按当前登录用户的 `user_id` 过滤。任何新接口都要检查横向越权，不能相信前端传来的 `user_id`。

## 6. 线上路由与进程

线上由 Caddy 接收公网流量：

- `feng.asia`、`www.feng.asia`：静态首页 `/var/www/aimeimei/index.html`。
- `/ai`：rewrite 到后端 `/`。
- `/ai/*`：`handle_path` 去除 `/ai` 前缀后代理到 `127.0.0.1:8000`。
- `/api/*`、`/res/*`、`/favicon.ico`：直接代理到后端。
- `/cat`、`/cat/*`：保留 `/cat` 路径代理到后端。
- `:8080` 和服务器 HTTP IP 入口仅为旧地址兼容。

线上 systemd 进程：

```text
User=ai-platform
Group=ai-platform
WorkingDirectory=/opt/ai-platform
AI_PLATFORM_LISTEN=127.0.0.1:8000
AI_PLATFORM_DATA=/opt/ai-platform
ExecStart=/usr/bin/python3 /opt/ai-platform/app.py
```

代码文件可由 `root:root 0644` 持有，运行数据必须允许 `ai-platform` 用户写入。数据库当前为 `ai-platform:ai-platform 0644`，`secrets.json` 为 `ai-platform:ai-platform 0600`。

## 7. 敏感配置

绝对不要把真实密钥写入 Git、本文档、前端、日志或回答。只记录配置名称。

敏感数据可能来自：

- `/opt/ai-platform/secrets.json`
- `/opt/ai-platform/admin.key`
- `/opt/ai-platform/family_password.txt`（旧兼容）
- `/etc/systemd/system/ai-platform.service.d/*.conf`
- `/etc/ai-platform/backup-oss.env`
- `/etc/ai-platform/backup.key`

主要配置组：

- 小猫书/通用 OSS：`CAT_OSS_*`。
- 聊天图片：可复用 `CAT_OSS_*`，目录为 `chat-images`。
- 听悟媒体：`TINGWU_*`、`MEDIA_OSS_*`，未单配时复用 CAT OSS。
- TTS：`AI_TTS_*`、`VOLC_TTS_*`，音频目录为 `tts`。
- 联网：后台保存的 Tavily/Brave 配置；Qwen 百炼原生联网复用模型 API Key。
- 备份：`AI_PLATFORM_BACKUP_*`，OSS 凭据位于独立 EnvironmentFile。

安全提醒：历史上 OSS/听悟 AccessKey 曾直接出现在聊天和 systemd drop-in 中。后续应安排轮换，并把服务环境统一迁移到权限为 `0600` 的 EnvironmentFile；执行排查时不要使用会打印完整 Environment 的命令，也不要输出 `systemctl cat ai-platform` 的敏感 drop-in 内容。

## 8. 本地开发流程

先确认工作树，不能覆盖用户未提交的修改：

```bash
cd '/Users/feng/Documents/文稿 - Unknown/aliyun3129'
git status --short
git log -5 --oneline
```

当前已知有三个未跟踪图片，视为用户文件，除非用户明确要求，否则不要删除、覆盖、加入提交或清理：

```text
res/2cfdd130-5661-4e76-85d1-fc915d79c363.png
res/meimei-empty-state-cropped1.png
res/meimei-empty-state1.png
```

本地启动建议使用临时数据目录，避免碰线上或真实本地库：

```bash
AI_PLATFORM_DATA=/tmp/ai-platform-test \
AI_PLATFORM_LISTEN=127.0.0.1:8080 \
AI_PLATFORM_DEV_MODE=1 \
python3 app.py
```

访问：

- `http://127.0.0.1:8080/`
- `http://127.0.0.1:8080/dev/markdown`

不要把真实 `secrets.json` 复制到测试目录。需要第三方连通性测试时，应先说明可能产生费用，并只打印状态、字段名和脱敏错误。

## 9. 修改原则

1. 先阅读相关模块，再编辑；不要把已经拆出的后端重新塞回 `app.py`。
2. 优先沿用现有标准库、SQLite 和原生 JS 实现。
3. 不删除旧数据；数据库升级必须幂等，兼容已有表和列。
4. 新的用户数据必须加 `user_id` 并在所有 CRUD 中隔离。
5. 管理员全局配置可共享，个人会话、消息、收藏、档案、设置、媒体任务不能共享。
6. 不改无关文件，不格式化整个巨型 CSS/JS，不覆盖用户改动。
7. 前端功能要兼顾桌面、iPhone Safari 和 Android；PC 专属功能必须在触控设备隐藏。
8. 流式输出只更新当前 assistant 节点，不重新渲染全部历史 Markdown、Sidebar 或 Composer。
9. 高频交互使用节流、`requestAnimationFrame` 或 CSS 动画，避免 JS 定时器驱动全局 UI。
10. Markdown 表格外层横向滚动，单元格允许中文换行，禁止全局 `white-space: nowrap`。
11. 图片/网页内容属于不可信输入；展示前净化，不能执行第三方脚本或 HTML 指令。
12. 图标统一使用 Lucide。视觉保持克制，不把每块内容都做成厚重卡片。

## 10. 联网搜索现状

当前联网有两条路径：

- Qwen 百炼原生联网：模型后台开启 `supports_native_web_search`，使用 Responses API 的 `web_search`。从 v2.21.11 起同时尝试百炼官方 `web_extractor`；若上游不支持该工具，则自动退回只有 `web_search` 的请求。
- 其它模型：Tavily 或 Brave，由后台联网设置控制自动/手动/强制策略。

来源展示：最终回答只显示 favicon 聚合入口和 `N 个网页`，点击后打开右侧 Reference Sources Panel。来源保存在 `message_sources`，历史会话可恢复。

摘要优先级：Provider highlight/passage -> Provider snippet -> 百炼 `web_extractor` -> 本地轻量网页抓取与关键词相关段落 -> meta/JSON-LD description -> 空状态。本地抓取不会绕过验证码、登录、付费墙或访问控制；单站失败不能导致主回答失败。

v2.21.11 只改善新生成的回答，旧历史中已经保存为空的来源没有批量回填。需要回填时必须先设计限量、限速、可中断脚本，并得到用户确认，不能启动时扫描全部历史 URL。

## 11. 备份与恢复

备份 timer：`ai-platform-backup.timer`，每天 `03:30`，启用且 active。编写本文档时最近一次执行结果为 success。

备份流程：

1. 使用 SQLite Backup API 创建一致性快照。
2. 清除密码哈希、模型 Key、Session、分享 Token、临时 URL 等敏感字段。
3. gzip 压缩。
4. 使用 `/etc/ai-platform/backup.key` 做 AES-256-CBC + PBKDF2 加密。
5. 上传到 OSS `backups/ai-platform/YYYY/MM/`。
6. 默认保留 90 天。

OSS 不需要提前创建“文件夹”，对象 Key 前缀会自动形成目录视图。

检查：

```bash
ssh aliyun_3129 'systemctl status ai-platform-backup.timer --no-pager'
ssh aliyun_3129 'systemctl status ai-platform-backup.service --no-pager'
```

恢复命令见 `README.md`。真正恢复前必须停止写入、备份当前数据库并获得用户明确确认。不要直接覆盖线上数据库。

## 12. 发布版本规则

每次用户可见发布都要同时完成：

1. 更新 `VERSION`，使用三段版本号，不带前缀 `v`。
2. 更新 `BUILD_ID`，推荐 `YYYYMMDD-HHMMSS`，每次部署必须变化。
3. 在 `CHANGELOG.md` 顶部增加版本、日期和关键变化。
4. 更新 `ai.html`、`share.html`、`res/ai.js` 内可见版本和 `?v=` 静态资源缓存参数。
5. 必要时同步其它页面版本展示；运行脚本确认没有漏项。

发布前最低验证：

```bash
python3 scripts/check_release_version.py
PYTHONPYCACHEPREFIX=/private/tmp/aimeimei-pycache \
  python3 -m py_compile app.py ai_platform/*.py ai_platform/handlers/*.py
node --check res/ai.js
git diff --check
```

涉及 `res/share.js`、独立脚本或内嵌 `<script>` 时也要分别做 JS 语法检查。涉及页面布局时使用浏览器或 Playwright 验证桌面和移动端；不能只看代码。

Git commit 必须使用中文 Conventional Commit，例如：

```text
feat(search):增强联网来源摘要提取
fix(chat):修复移动端回复内容溢出
perf(admin):按需加载Token统计详情
```

提交前只 `git add` 本次文件，绝对不要用 `git add .` 把未知文件带进去。推送目标：

```bash
git push origin main
```

用户通常希望功能完成后直接推送和部署；若当前请求已经明确包含“动手、部署、重启”或已有当次确认，可继续执行。涉及生产数据库覆盖、回滚、删除、配置变更等高风险操作仍需单独明确确认，并遵守工具的权限审批。

## 13. 安全部署流程

推荐只打包本次变更文件，不整目录覆盖。示例中的文件列表必须替换成当次实际文件：

```bash
COPYFILE_DISABLE=1 tar -czf /private/tmp/aimeimei-release.tgz \
  VERSION BUILD_ID CHANGELOG.md app.py ai.html res/ai.js \
  ai_platform/handlers/chat.py

tar -tzf /private/tmp/aimeimei-release.tgz
scp /private/tmp/aimeimei-release.tgz aliyun_3129:/tmp/aimeimei-release.tgz
```

服务器端：

1. 校验压缩包成员与预期 allowlist 完全一致，拒绝绝对路径和 `..`。
2. 在 `/opt/ai-platform-release-backups/` 备份即将覆盖的线上文件。
3. 解压到 `/opt/ai-platform`。
4. 代码文件设为 `root:root 0644`；目录按现状保留。不要改变数据库和密钥权限。
5. 在线上执行完整 Python 编译检查。
6. `systemctl restart ai-platform`。
7. 等待端口就绪，不要因重启后一瞬间 connection refused 就误判失败。

验证：

```bash
ssh aliyun_3129 'systemctl is-active ai-platform'
ssh aliyun_3129 'curl -fsS http://127.0.0.1:8000/api/health'
ssh aliyun_3129 'curl -fsS http://127.0.0.1:8000/api/version'
curl -fsS -H 'Cache-Control: no-cache' \
  'https://feng.asia/api/version?check=BUILD_ID'
curl -fsS -H 'Cache-Control: no-cache' \
  'https://feng.asia/ai/?check=BUILD_ID'
```

确认公网 `/api/version` 的 `version` 和 `build_id` 与本地完全一致，并检查 HTML 引用的新 `?v=` 参数。不要只相信 `systemctl is-active`。

## 14. 回滚

发布前备份位于：

```text
/opt/ai-platform-release-backups/before-vX.Y.Z-BUILD_ID.tgz
```

回滚前必须：

1. 明确本次故障和目标备份。
2. 得到用户确认。
3. 备份当前故障版本，避免丢失现场。
4. 只恢复该发布实际覆盖的代码/静态文件。
5. 除非确认是数据库迁移问题，否则不要回滚 SQLite。
6. 编译、重启并验证本机和公网版本。

禁止使用 `git reset --hard`、`git checkout --` 或删除工作树来“回滚”用户文件。

## 15. 故障排查顺序

### 页面白屏或一直转圈

1. 查 `/api/version` 和 `/api/health`。
2. 查 `systemctl is-active ai-platform`。
3. 查最近服务日志，但过滤密钥：`journalctl -u ai-platform --since '-10 min' --no-pager`。
4. 查看浏览器 Network 中真正失败的第一条同域请求。
5. 浏览器扩展常产生 `message port closed`，若同域请求正常，不要把扩展报错误判成站点 JS 错误。
6. 检查 HTML 的 `?v=` 是否更新，以及 Caddy 是否返回新 HTML。

### 发送后空白、历史顶部大块留白

- 检查消息的 `content`、`reasoning_content` 和前端渲染条件。
- 检查是否把 reasoning 占位高度留在最终消息前。
- 检查空消息、隐藏消息、引用提示词是否仍占 DOM 高度。
- 分享页与主聊天页有独立渲染代码，两边都要回归。

### 流式输出卡顿

- 不要把上游大 chunk 原样一次性刷入 DOM。
- 使用已有平滑输出队列；最终事件到达时应加速清空而不是继续数秒播放。
- reasoning preview 与 answer 分开节流。
- 用户已上滚时不能强制滚到底。
- 不重新解析历史 Markdown，不让 Sidebar 跟随 token 更新。

### 模型 403

- 核对 Base URL、实际 model 名、Key 所属服务/地域、模型是否已开通、兼容接口类型。
- 不要因为相似模型名就假设端点相同。
- 返回给用户脱敏后的上游错误，不打印 Key。

### 来源摘要为空

- 先检查 `message_sources` 是否在保存前已有 snippet。
- Qwen 原生搜索必须走主聊天中的 `web_extractor` 合并逻辑，不要只改侧边讨论路径。
- 检查 `source_snippet_cache` 是否缓存了 empty/error。
- 站点 403、验证码或登录墙应降级，不绕过反爬。
- 旧历史空摘要不会自动获得新逻辑，需要单独回填任务。

### Token 统计打开很慢

- 汇总页与详情分开请求；只有点“详情”才查最近调用。
- 保留并检查 `messages` 的 user/model/created 索引。
- 不在打开 Admin Workspace 时预加载全部 Token 详情。

## 16. 必测回归

根据改动范围选择，但正式发布至少覆盖受影响功能和以下基础路径：

- 登录、验证码、刷新登录状态、退出。
- 新建、切换、重命名、置顶、删除会话。
- 普通流式回答和 reasoning 模型。
- 模型切换后上下文保持。
- 联网开关、Qwen 原生联网、参考来源历史恢复。
- Markdown 标题、列表、代码块、表格和移动端宽表。
- 图片选择、OSS 上传进度、Vision 发送和历史图片。
- AI 档案加载/关闭、提示词、收藏。
- 音视频任务、听悟刷新、AI 增强、创建会话。
- TTS 首次生成、暂停/继续、缓存复用和跨账号权限。
- 全局搜索、引用卡片、侧边讨论功能开关。
- 分享单段/整个会话、到期失效、分享页无顶部空白。
- Admin 各模块保存、Token/费用汇总和按需详情。
- PC 和手机 Composer 不遮挡最后一条消息。
- `/cat/` 浏览、登录、发布、猫咪档案、点赞、评论。

不要使用真实账号批量创建垃圾数据。必须调用真实计费模型时，使用最短提示，并提前说明会产生一次调用费用。

## 17. 当前已知事项与后续方向

- `README.md` 的“当前版本”可能落后于 `VERSION`，后续发布应顺手同步，但不能以 README 判断线上版本。
- `res/ai.js` 约 9000 行、`res/ai.css` 约 8400 行，前端仍可继续按模块渐进拆分；不能一次性重写。
- `admin.py` 和 `chat.py` 仍较大，可以继续按功能拆分 Handler，但必须保持路由、Mixin 顺序和接口行为。
- 历史来源空摘要尚未回填。
- 部分网页会拒绝服务器抓取，这是正常降级场景，不能通过绕过访问控制解决。
- systemd 历史 drop-in 中存在直接环境变量密钥，应优先安排密钥轮换和 EnvironmentFile 收敛。
- 本文档不替代 `CHANGELOG.md`；具体版本变化看 changelog 和 Git 历史。

## 18. 新 AI 接手时的第一组命令

```bash
cd '/Users/feng/Documents/文稿 - Unknown/aliyun3129'
sed -n '1,260p' AI.md
git status --short
git log -8 --oneline
cat VERSION
cat BUILD_ID
sed -n '1,160p' CHANGELOG.md
```

然后按用户本次需求用 `rg` 定位相关模块。先理解，后修改；完成实现、测试、版本、提交、推送、部署和公网验证的完整闭环。
