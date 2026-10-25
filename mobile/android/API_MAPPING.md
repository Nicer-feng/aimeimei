# 原生客户端接口盘点

依据当前 `app.py`、`ai_platform/handlers/auth.py`、`chat.py` 与 `presenters.py` 检查。

| 模块 | 现有接口 | 当前 Android 状态 |
|---|---|---|
| 密码验证码 | GET /api/captcha | 已适配 SVG 与 captcha_id，不绕过验证码 |
| 密码登录 | POST /api/login | 已适配 username/password/captcha_id/captcha |
| 会话恢复 | GET /api/me | 已适配 authenticated/user，不能只看 HTTP 200 |
| 退出 | POST /api/logout | 已适配，清除服务端及本地会话 |
| 模型列表 | GET /api/models | 已适配读取，不暴露管理 API |
| 会话列表 | GET /api/conversations | 已适配读取；当前后端最多返回 200 条 |
| 单段会话 | GET /api/conversations/{id} | 0.6.3 新增只读接口，返回 conversation；仅当前账号、未归档会话，缺失及越权返回 404，未登录返回 401；不更新时间戳，不返回模型密钥 |
| 会话管理 | PATCH /api/conversations/{id}；POST /api/conversations/{id}/pin、/unpin；DELETE /api/conversations/{id} | 原生重命名、置顶、取消置顶、删除；服务端按账号隔离 |
| 历史消息 | GET /api/conversations/{id}/messages | 已适配读取；message.id 是整数，客户端转为稳定字符串键 |
| 短信 | GET /api/sms-login/config；POST /api/sms-login/send、/verify | 已接入原生密码/短信切换、显式发送、冷却与验证码核验 |
| 新建/配置会话 | POST /api/conversations；PATCH /api/conversations/{id} | 已接入 model_id/reasoning_mode；档位以真实能力字段为准 |
| 流式发送 | POST /api/conversations/{id}/messages | 已接入；OkHttp SSE，发送 content/web_search/use_profile，不直接调用上游模型 |
| 图片 | POST /api/chat-images/upload-policy；POST /api/chat-images | 已接入系统相册、拍照、OSS 上传、附件发送和原生缩放预览 |
| 办公文件 | POST /api/documents/upload-policy；POST /api/documents；GET /api/documents/{id} | 已接入系统文件选择、OSS 上传、解析轮询和附件发送 |
| 语音 | POST /api/messages/{id}/tts | 已接入音色/语速选择、主动生成、原生播放/暂停/进度；GET /api/tts/config 与受保护音频下载 |

认证是服务端 `Set-Cookie: ap_session=...`，不是响应中的 Bearer token。使用应用私有 CookieJar，在 Android Keystore 生成 AES-GCM 密钥加密存储 cookie；不保存登录密码、不记录 Cookie 日志，不开启备份，不允许明文 HTTP。

流式协议已适配 `choices[].delta.content`、reasoning/reasoning_content/thinking、`search_status`、`message_saved`、`message.failed` 与 `[DONE]`。`message_saved` 的正整数 ID 确认保存，generation_status 决定是否完整，不能将断流当作完成。停止通过取消连接复用服务器现有断连逻辑，不新增 stop API。恢复仅 GET，不自动重放消息。

现有 Web 的 HTML/CSS、浏览器 DOM 与事件不能直接用于 Compose；原生页面与状态单独实现。后端的账号隔离、模型配置、搜索、Token、费用与材料解析可以复用，无需因 APK 重写。

复杂功能通过同源 WebView 复用现有 Web 页面，原生会话使用 fragment 定位，Cookie 由系统 CookieManager 设置，不传管理密钥。返回时 GET /api/me 和会话列表，校验账号并刷新历史。

## 原生后台（0.5.1）

沿用登录 Cookie 和服务端管理员校验，不使用管理密钥替代账号。

| 模块 | 现有接口 | 原生页面 |
|---|---|---|
| 概览 | GET /api/admin/overview | 账号、模型、用量与服务状态 |
| 账号 | GET/POST /api/admin/users；PUT /api/admin/users/{id} | 新增、编辑、角色、状态、手机号确认 |
| 模型及密钥 | GET/POST /api/admin/models；PUT/DELETE /api/admin/models/{id} | 模型配置、价格、能力、密钥替换/清空 |
| 联网搜索 | GET/POST /api/admin/search | 搜索服务、策略、深度、数量、密钥 |
| 语音 | GET/POST /api/admin/tts | 服务参数、默认音色、可用音色及资源 ID |
| 插件 | POST /api/admin/features | 引用、侧边讨论、长文本检测开关 |
| Token | GET /api/admin/token-stats；GET /api/admin/token-stats/daily；各自 /details | 账号/模型/每日维度、排序、搜索、7/30 天趋势及调用明细 |
| 成本 | GET /api/admin/cost-stats；POST /api/admin/cost-recalculate | 时间范围、费用排行、趋势与确认回算 |
| 有效时长 | GET /api/usage-time/admin；GET /api/usage-time/admin/user | 日期范围、搜索排序及账号每日明细；沿用已有网页账本 |
| 短信配置 | GET/POST /api/admin/sms-auth | 签名、模板、有效期和重发间隔 |
| 系统 | GET /api/version；POST /api/admin/password | 服务版本信息及确认修改家用密码 |

凭证只在表单内存及 HTTPS 请求体中传递，不拼入 URL、不输出日志、不写入界面保存状态。

## 原生消息工具（0.6.0）

| 模块 | 现有接口 | 原生页面 |
|---|---|---|
| 收藏 | GET/POST /api/favorites；DELETE /api/favorites/message/{id}、/api/favorites/{id} | 回答收藏与取消、收藏列表搜索与全文、返回最近会话原消息 |
| 引用 | GET /api/features；沿用 POST 消息的 content | 正文选区/整条引用、最多 3 段、与 Web 相同的引用格式 |
| 公开分享 | POST /api/conversations/{id}/shares；DELETE /api/conversation-shares/{id} | 明确确认范围、有效期、创建/复制/系统分享与撤销当前链接 |
| 文字分享 | Android ACTION_SEND | 用户打开系统分享菜单，不自动发送给联系人 |
| 图片/音频预览 | GET /api/chat-images/{id}/view；GET /api/messages/{id}/tts/audio | 登录请求与 OSS 跳转下载分开，不向对象存储转发 Cookie |

历史文件接口没有原始文档下载地址，客户端仅承诺元数据、解析状态与本次缓存原件的系统打开；不虚构下载接口。

## 图片体验与会话信息（0.6.1）

| 模块 | 现有接口 | 原生页面 |
|---|---|---|
| 图片缩略图 | GET /api/chat-images/{id}/view | 选择后、上传中和历史缩略图，全屏缩放与重试，按账号缓存 |
| 会话统计 | GET /api/conversations/{id}/stats | 累计 Token、轮数、消息、联网回答和历史图片数 |
| 回答用量 | GET 消息的 usage | 输入/输出、缓存 Token、估算费用；不虚构未返回的用量 |
| 模型能力 | GET /api/models | 图片、思考强度和原生联网标识，图片能力筛选 |
| 共享提示词 | GET/POST /api/prompts；PUT/DELETE /api/prompts/{id} | 搜索、全文、新增编辑、确认删除，确认追加或替换草稿 |

复用现有后端及权限，无服务器或数据库变更。提示词按 Web 的全站共享语义展示。图片下载在鉴权后保留 OSS 签名查询参数，跨站不转发 Cookie；同一图片共享下载，最多同时下载三张。

## 全文搜索、联网来源与 AI 档案（0.6.3）

| 模块 | 接口 | 原生页面 |
|---|---|---|
| 聊天全文搜索 | GET /api/search?q=关键词 | 标题、提问、回答和收藏；关键词高亮、提问/回答筛选；复用服务器最多 60 条综合结果，音视频结果不混作聊天 |
| 搜索定位 | GET /api/conversations/{id}；GET /api/conversations/{id}/messages | 读取真实模型和思考配置后定位原消息；支持最近 200 条列表之外的会话，回到前台继续保留该会话；删除后的收藏可进入原生收藏页 |
| 联网来源 | 历史消息 sources | 按 position 展示标题、链接、摘要，复制链接、用户主动打开外部浏览器；不发起额外模型调用，不在 WebView 注入账号 Cookie |
| AI 档案 | GET/POST /api/profiles；PUT/DELETE /api/profiles/{id}；POST /api/profiles/reorder | 当前账号私有档案，原生全文编辑、类型、启停、排序、确认删除；与 Web 同步，聊天继续沿用 use_profile=true |

档案名称最多 80 字、内容最多 12000 字，enabled 使用布尔值、sort_order 使用整数；失败保留编辑内容。搜索请求取消并屏蔽过期响应，账号变化清空搜索和档案内存。新增的单段会话 GET 需先部署 app.py 和 ai_platform/handlers/chat.py，不修改数据库结构。

## 编辑、OCR、个人用量与短信登录（0.6.5）

| 模块 | 接口 | 原生行为 |
|---|---|---|
| 全屏编辑 | 本地聊天草稿 | 实时保存、字数、复制、确认清空；仅由聊天发送按钮发起模型请求 |
| 手写图片上传 | POST /api/ocr/upload-policy；OSS multipart POST | 相册/拍照/图片文件，先私有缓存预览；确认识别后才请求策略，独立无 Cookie 客户端上传，遵守策略大小和格式限制 |
| 识别与记录 | POST/GET /api/ocr/tasks；DELETE /api/ocr/tasks/{id} | 识别最长等待 180 秒，禁止自动重发；查看原始结果、编辑用于复制/草稿、明确确认再次识别或删除；切账号取消请求并清缓存 |
| 个人用量 | GET /api/token-activity | summary 为累计统计、days 为近一年日统计；7/30/365 天由客户端选取，day_models 展示每日模型，累计排行保留其累计口径 |
| 短信配置 | GET /api/sms-login/config | 解析 sms_auth.enabled/configured/valid_seconds/resend_seconds；未开放时仍可密码登录 |
| 获取验证码 | POST /api/sms-login/send | 显式 phone，接收 challenge_id 和 resend_after；单调时钟倒计时，手机号修改会清除挑战但保留冷却，网络失败不自动重发 |
| 短信核验 | POST /api/sms-login/verify | phone/code/challenge_id，6 位验证码，读取返回 user 和已有 Set-Cookie；401 映射验证码错误，成功才进入工作区 |

全部复用现有后端与账号权限，本次无服务端、数据库或部署配置变更；云端验证仅调用本地 HTTP/TLS 测试服务，不发送真实短信、不调用真实 OCR 或付费模型。
