# 有效使用时长

工作模式指普通界面的有效使用，不代表实际工作产出；摸鱼模式指阅读正文时的有效使用。只记录时间段和模式，不采集键盘内容、鼠标轨迹、聊天或小说正文。管理员可看全部账号，普通账号只看自己。此指标是客户端估算，不能用作防作弊考勤。

## 计时

- 前台、窗口焦点与 `document.hasFocus()` 同时成立，且最近 120 秒有可信点击、键盘、滚轮或触摸操作。
- 不监听 mousemove 或 scroll：程序自动滚动、模型输出、动画不能续期。
- 阅读状态打开书架、后台等弹窗时归入工作模式；关闭后恢复阅读计时。
- 单调时钟每 5 秒结算；间隔超过 10 秒视为挂起，丢弃该间隔并等待新操作。
- 约每 30 秒提交，失焦、切后台、切阅读模式时补交。关闭页面只能尽力提交，可能少计最后一小段，不反补离线时间。
- 每条报告最多 35 秒，服务端只接受近 120 秒数据，最多 5 秒时钟偏差。同账号的重叠区间取并集，重叠部分按先接受的模式归类；不同标签页、设备不重复增加总时长。
- 服务端先验证整个请求，再在 SQLite 写事务内扣除已接收的重叠区间、按北京时间跨日拆分并增加每日累计。同一个事件 ID 重试不重复入账。
- `usage_time_events` 仅作短期去重，新报告到达时清理超过 180 秒的事件；`usage_time_daily` 持久保存日累计。无历史回填。

## 接口

全部要求当前用户登录，返回 JSON；常规错误 `400/401/403/404/409`。

- `GET /api/usage-time/config`：`server_now_ms`、`idle_ms`、`heartbeat_ms`。
- `POST /api/usage-time/heartbeat`：`{account_id, segments:[{id,start_ms,end_ms,mode}]}`；mode 为 `work` / `reading`，最多 8 段。account_id 必须匹配认证用户，防止切账号时迟到请求误记。返回 `credited_ms`，不信任用户提交的总量。
- `GET /api/usage-time/self?start=YYYY-MM-DD&end=YYYY-MM-DD`：当前账号 `summary` 与 `days`。忽略 user_id 等筛选账号的参数。
- `GET /api/usage-time/admin?start=...&end=...&q=...&sort=total`：管理员专用；返回 `summary` 与 `users`，不带逐日详情。sort 为 total / work / reading / last。
- `GET /api/usage-time/admin/user?user_id=...&start=...&end=...`：管理员专用，点击详情才请求，返回该账号 summary 与 days。

日期默认北京时间今天，最多 366 天，不能选未来。时长以毫秒保存/返回，界面显示小时/分钟。summary 字段为 work_ms、reading_ms、total_ms，管理员汇总另有 active_users；列表按用户名或昵称过滤时，汇总采用同一过滤条件。

## 回归

- `node scripts/test_usage_clock.js`：有效输入、失焦、闲置、休眠、模式边界和过期报告。
- `python3 scripts/test_usage_time.py`：临时 SQLite 的鉴权、区间去重、重试、乱序、跨日和查询隔离，含阅读模块回归。
- `python3 scripts/test_usage_time.py --serve` 启动本地浏览器环境；以输出的地址设置 USAGE_TEST_URL，运行 `node scripts/test_usage_time_ui.js`（Playwright）。焦点丢失通过 blur 事件模拟，因为 headless Chrome 的多个标签页可能均报告有焦点；其余 UI 点击、采样与 HTTP 使用实际浏览器和隔离后端。
- `node scripts/test_chat_state.js`：原聊天状态回归。无外部模型调用。
