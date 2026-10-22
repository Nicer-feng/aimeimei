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
