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
| 会话管理 | PATCH /api/conversations/{id}；POST /api/conversations/{id}/pin、/unpin；DELETE /api/conversations/{id} | 原生重命名、置顶、取消置顶、删除；服务端按账号隔离 |
| 历史消息 | GET /api/conversations/{id}/messages | 已适配读取；message.id 是整数，客户端转为稳定字符串键 |
| 短信 | GET /api/sms-login/config；POST /api/sms-login/send、/verify | 待原生 UI 接入 |
| 新建/配置会话 | POST /api/conversations；PATCH /api/conversations/{id} | 已接入 model_id/reasoning_mode；档位以真实能力字段为准 |
| 流式发送 | POST /api/conversations/{id}/messages | 已接入；OkHttp SSE，发送 content/web_search/use_profile，不直接调用上游模型 |
| 图片 | POST /api/chat-images/upload-policy；POST /api/chat-images | 待接入系统相册及 OSS 上传 |
| 办公文件 | POST /api/documents/upload-policy；POST /api/documents；GET /api/documents/{id} | 待接入系统文件选择与解析轮询 |
| 语音 | POST /api/messages/{id}/tts | 待接入主动生成和播放 |

认证是服务端 `Set-Cookie: ap_session=...`，不是响应中的 Bearer token。使用应用私有 CookieJar，在 Android Keystore 生成 AES-GCM 密钥加密存储 cookie；不保存登录密码、不记录 Cookie 日志，不开启备份，不允许明文 HTTP。

流式协议已适配 `choices[].delta.content`、reasoning/reasoning_content/thinking、`search_status`、`message_saved`、`message.failed` 与 `[DONE]`。`message_saved` 的正整数 ID 确认保存，generation_status 决定是否完整，不能将断流当作完成。停止通过取消连接复用服务器现有断连逻辑，不新增 stop API。恢复仅 GET，不自动重放消息。

现有 Web 的 HTML/CSS、浏览器 DOM 与事件不能直接用于 Compose；原生页面与状态单独实现。后端的账号隔离、模型配置、搜索、Token、费用与材料解析可以复用，无需因 APK 重写。

复杂功能通过同源 WebView 复用现有 Web 页面，原生会话使用 fragment 定位，Cookie 由系统 CookieManager 设置，不传管理密钥。返回时 GET /api/me 和会话列表，校验账号并刷新历史。
