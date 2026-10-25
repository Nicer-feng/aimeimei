# iOS 接口契约

已对照当前 `app.py`、`handlers/auth.py`、`handlers/chat.py` 与 `presenters.py`，不新增或修改服务端接口。

| 功能 | 方法和路径 | 关键字段 |
|---|---|---|
| 验证码 | GET `/api/captcha` | `captcha_id`、`image_svg`；原生绘制，不绕过校验 |
| 登录 | POST `/api/login` | `username`、`password`、`captcha_id`、`captcha`；从 Set-Cookie 保存 `ap_session` |
| 短信配置 | GET `/api/sms-login/config` | `sms_auth.enabled/configured`、`country_code`、`code_length`；不可用时仍可密码登录 |
| 发送短信 | POST `/api/sms-login/send` | 仅传 `phone`；保存内存中的 `challenge_id`、`expires_at`、`resend_after`，不自动重试 |
| 短信登录 | POST `/api/sms-login/verify` | `phone`、`code`、`challenge_id`；复用相同 Cookie 和 Keychain；无需图形验证码 |
| 恢复账号 | GET `/api/me` | 检查 `authenticated` 和 `user`，不能只判断 HTTP 200 |
| 退出 | POST `/api/logout` | 清除服务端及本机登录状态 |
| 模型 | GET `/api/models` | `id`、`name`、`supports_reasoning_control` |
| 会话 | GET/POST `/api/conversations` | 新建使用 `model_id`、`reasoning_mode` |
| 修改会话 | PATCH `/api/conversations/{id}` | 配置只传模型和档位；重命名只传 `title` |
| 置顶 | POST `/api/conversations/{id}/pin`、`/unpin` | 不修改模型配置 |
| 删除 | DELETE `/api/conversations/{id}` | 服务端现有归档行为 |
| 消息历史 | GET `/api/conversations/{id}/messages` | 数字消息 ID、`reasoning_content`、`generation_status`、附件文件名 |
| 收藏列表 | GET `/api/favorites` | `message_id`、`conversation_id`、`conversation_title`、`content`；保留删除会话的快照 |
| 收藏回答 | POST `/api/favorites` | 数字 `message_id`，不自动重试；成功后同步本机星标 |
| 取消收藏 | DELETE `/api/favorites/message/{id}` | 当前用户内幂等删除，允许移除旧会话的收藏 |
| 提示词库 | GET `/api/prompts` | 仅读取 `id`、`title`、`content`，不调用公共模板编辑接口 |
| 全文搜索 | GET `/api/search?q=...` | URL 编码关键词，保留字面加号；支持 `conversation/message/favorite`，用 `session_id/message_id` 定位 |
| 流式发送 | POST `/api/conversations/{id}/messages` | `content`、布尔 `web_search`、布尔 `use_profile: true` |

思考档位为 `fast`、`balanced`、`deep`。所有私有接口由现有后端按账号校验权限。
短信登录仅限后台已绑定、已启用且未停用的中国大陆手机号，不注册新账号。换号会作废本机旧挑战，切换登录方式不会清零重发倒计时。验证码和挑战不写本地存储或日志。
模型提供者密钥不进入 App；客户端不使用 Bearer token、不请求 `X-Admin-Key`。
搜索包含 250ms 防抖及请求版本隔离；过时、已取消或退出账号后的响应不写回界面。服务端音视频分析结果不属于本版原生搜索范围。收藏列表沿用服务端最多 300 项、搜索沿用最多 60 项返回限制。

SSE 解析标准 `data:` 事件及空行，支持多行数据、CRLF、UTF-8、reasoning 三种字段和搜索状态。
只有有效 `message_saved.message_id` 及历史核对可确认保存；客户端不把 `[DONE]` 当成成功凭证。

## 图片提问与引用（0.3.0）

- 模型 `supports_vision` 控制选图及发送；缺失时按不支持图片处理。
- POST `/api/chat-images/upload-policy` 获取签名表单；按 `max_size/expires_at/key_prefix` 校验，独立无 Cookie 会话直传 OSS，不跟随重定向。
- POST `/api/chat-images` 登记 `filename/mime_type/file_size/oss_key`，返回 `image.id/filename`。
- 发送接口增加 `image_ids`，不重试模型 POST；待核对标记同时匹配文字和图片 ID，支持只有图片的消息。
- GET `/api/chat-images/{id}/view` 使用平台 Cookie 获取 302 地址，再用无 Cookie 会话读取 HTTPS 签名图像；预览数据仅存内存。
- 历史消息 `images` 显示图片，`sources` 展示 `title/url/snippet/position`；原文仅允许不含用户名密码的 HTTP/HTTPS 地址。
- 草稿保存已登记图片的 ID/文件名，不保存原相册数据、上传授权或 OSS 签名 URL。用户恢复待核对的问题时需重新选择图片，避免复用已经绑定的图片。

## 文件问答与朗读（0.4.0）

- GET `/api/documents` 读取当前用户的材料；POST `/api/documents/upload-policy` 获取 OSS 表单，独立无 Cookie 会话上传后 POST `/api/documents` 登记 `filename/mime_type/file_size/oss_key`。
- POST `/api/documents/{id}/refresh` 查询已有解析任务，保留 `submitted/processing/failed/completed` 与 `error_message`。前台有限轮询，不自动重传、重新提交解析或删除文件。
- 草稿 `documents` 只存材料元数据；发送增加 `document_ids`，最多 5 份，全部 `completed` 才发送，不修改 `/api/conversations/{id}/documents` 持续材料配置。
- GET `/api/tts/config` 读取 `tts.enabled/configured/voices/default_voice/default_speed`。POST `/api/messages/{id}/tts` 只准备播放，检查 `cached/long_text` 后再按用户确认 GET `/api/messages/{id}/tts/audio?voice=...&speed=...`。
- 音频接口可返回 200 `audio/*` 或 302 OSS HTTPS 签名地址；OSS 不携带平台 Cookie，不跟随进一步重定向。客户端自行构造固定消息路径，不使用任意返回的 `audio_url`。
- 音频不落盘，暂停/继续不请求后端；取消、页面关闭、会话切换、后台和退出使过时响应失效。无自动生成/下载重试，缓存由现有后端管理。

## 档案与分享（0.5.0）

- GET/POST `/api/profiles`，PATCH/DELETE `/api/profiles/{id}`；字段 title/content/type/sort_order/enabled，布尔启用与数字排序保持类型。客户端同服务端限制标题80字、正文12000字。
- 草稿 `useProfile` 缺省 true，按账号和会话保存；发送时显式传布尔 `use_profile`，只影响后续提问。
- GET/POST `/api/conversations/{id}/shares`；创建 scope=assistant/turn/conversation，单回答或轮次传 message_id，expires_in=3600/21600/86400/604800。
- DELETE `/api/conversation-shares/{id}` 撤销。只有创建响应有相对 url；只接受本站 `/ai/share/` 后跟安全令牌的链接，历史列表不恢复令牌。分享令牌仅存当前页面内存。
- 保存和分享写入不自动重试；退出账号丢弃过时响应并清空工具状态。
