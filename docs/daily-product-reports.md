# 每日产品推送

与研发日报平级的只读频道，推荐近期有新意、值得体验的开源项目和产品工具。正文不进入聊天、不调用平台模型；选题由 Mac 上的 Codex 定时任务完成，再沿用现有 SSH 发布链路保存并发送 iOS 通知。

## 时间与选题

- 每天北京时间 09:00（含周末）运行，准备完成后投递；电脑与 Codex 需要保持运行。
- 通常精选 1 至 4 项，不设最低条数。没有有价值的新内容、来源无法核实或近期已经介绍且没有实质更新时，当天跳过，不创建空记录、不发送凑数通知，不补发错过日期。
- 优先最近 7 天的新发布、显著增长或实用更新，可参考 GitHub、其他开源平台、Hacker News 等发现候选，最终核对官方仓库、README、发布记录和演示。
- 每项简要说明解决什么问题、点子在哪里、适合谁、使用门槛和一项必要局限，附仓库或演示链接。关注应用和实际体验，避免全是智能体框架、提示词合集或资料清单。
- Star 总量、近 7 天增长、下载次数、用户数分别标注，附统计日期；无法核验周增时省略，不用总量代替周增，不将下载量称为独立用户数。
- 先读取最近 30 个正式发布日期的摘要与链接去重，通常 14 天内不重复同一项目；确有重要新版本或功能时说明变化。

## 权限与设备

- 仅 `feng`、`czq` 可用，管理员也不能为其他用户名开启。首次迁移为已有目标账号初始化开启一次，之后保留后台选择。
- 后台账号管理提供独立的 `product_reports_enabled`（开放每日产品推送）与 `product_push_enabled`（产品推送通知）；系统设置提供独立全局暂停。通知关闭或暂停不影响保存和查看。
- iOS 0.8.4 增加与研发日报平级的固定入口、分页历史、独立未读与只读详情；点击 `product_daily` 通知打开本频道记录。撤权、退出或切号清除本机旧状态。
- 仅已上报 iOS 元数据且会话有效的设备可以订阅。复用 APNs token，但必须由支持本频道的客户端主动注册产品订阅；旧版不会收到无法识别的通知。
- 产品订阅、日报订阅分别管理，关闭或退出一个频道不能取消另一个频道。首次订阅、权限恢复和全局恢复不补推历史。APNs accepted 仅表示苹果接受，不代表手机已显示。

## 接口与发布

鉴权、分页与返回字段沿用研发日报，记录和已读状态按账号隔离。

| 请求 | 用途 |
| --- | --- |
| `GET /api/product-reports?before=0` | 最新 30 条，返回 reports、unread、next_before |
| `GET /api/product-reports/{id}` | 本人记录详情 |
| `POST /api/product-reports/{id}/read` | 标记本人记录已读 |
| `POST /api/product-reports/device` | 已登记 iOS 会话订阅，提交 installation_id、token |
| `DELETE /api/product-reports/device` | 仅退出本人安装实例的产品频道 |
| `GET/POST /api/admin/product-report-settings` | 管理员查询或设置 `{"paused":true}` |

服务器没有公网写正文接口。固定 SSH 脚本：

```bash
python3 scripts/send_product_report.py --status
python3 scripts/send_product_report.py --history
python3 scripts/send_product_report.py /absolute/path/report.json
```

正文 JSON：`date` 为北京时间 YYYY-MM-DD，`content` 为 Markdown，`simulation` 可省略或 false。正文经 stdin 传输，不放 shell 参数，不读取或输出私钥、token、服务器 secrets。

同账号、日期、模拟标记唯一；一次事务为所有启用接收人保存同正文。当日存在不同正文时整批拒绝，不覆盖、不改日期绕过。同正文重试不重复保存或重发已 accepted 通知；新启用者不补写已发布日期。`--history` 只返回最近正式内容的摘要和公开链接，`--status` 不包含设备 token 或会话凭据。

发布后检查退出码和 `ok`，再逐账号检查 `report_id`、`created`、`registered_devices`、`push_enabled`、`push_paused`、`delivery`、`delivery_totals`。设备为 0 时只能说已保存，不能说已通知。pending 由现有 `ai-platform-reports.timer` 每五分钟重试，超出 24 小时不重试；invalid 需重新打开新版 App 注册。

## 验证

`python3 scripts/test_product_reports.py` 使用临时 SQLite、合成密钥与真实本机 HTTP APNs 模拟服务，验证账号/iOS限制、双频道隔离、幂等与原子性、暂停/恢复不补推、会话失效与失败重试、通知类型和载荷限制。`node scripts/test_product_reports_ui.js` 验证后台开关、账号范围与手机布局。iOS API、状态和 UI 回归使用现有 macOS 流水线。

上线验证不制造空日报、模拟日报或额外真实通知；手机展示与点击由安装新版后的实际内容验收。
