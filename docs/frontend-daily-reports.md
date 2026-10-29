# 研发日报与 iOS 推送

## 边界

- 后台“账号管理”提供独立的 `daily_reports_enabled`（开放研发日报）、`daily_push_enabled`（日报推送通知）布尔开关。其他账号默认关闭；迁移时只为已有 feng、czq 初始化开启一次，之后由管理员配置，不按用户名授权。账号必须启用才能生效。
- 开放日报的账号只读自己的记录，所有接收人使用同一正文但记录 ID、已读状态与设备独立；管理员身份不能越过账号隔离，也没有代读接口。普通账号不能修改这两个权限。
- 日报使用独立表，不创建普通聊天、不关联模型、不消耗 Token。客户端没有输入、续写、重生成或追问入口；服务端没有公网写正文接口。
- iOS 0.8.2 起从登录与当前账号接口获取上述权限，不含接收人名单；开放后显示固定置顶入口。前台每 30 秒及返回应用时刷新权限，撤销、退出、切换账号清理旧状态；服务端立即拒绝无权读取。新增接收人无需再发包，旧版需先升级到支持动态权限的版本。
- 日报详情的 Markdown 复用原生渲染器。通知携带标题、前三条纯文本摘要和记录 ID：每条最多 90 字，去除标题、代码块和常见 Markdown 标记，空摘要回退通用提醒；完整正文仍只在已鉴权的详情中读取。
- iOS 使用系统自带的折叠/长按展开显示，点击仍按记录 ID 打开只读详情，不新增通知扩展或修改客户端。摘要也可能直接显示在锁屏上，并非只有长按后才可见；通知中不应放源码、密钥或客户数据。
- TestFlight 使用生产 APNs。`aps-environment=production` 必须同时存在于应用签名和发行描述文件中。

## 接口

所有接口使用现有登录 Cookie/Bearer Session，目标账号以服务端用户为准，不接受 `user_id` 参数。

| 请求 | 用途 |
| --- | --- |
| `GET /api/daily-reports?before=0` | 最新 30 条，返回 `reports`、`unread`、`next_before`；按 `before` 向前分页 |
| `GET /api/daily-reports/{id}` | 打开指定日报，按账号校验 |
| `POST /api/daily-reports/{id}/read` | 标记已读，不修改正文 |
| `POST /api/daily-reports/device` | JSON：`installation_id`、APNs `token`；绑定当前登录 Session |
| `DELETE /api/daily-reports/device` | JSON：`installation_id`；只移除本人设备 |

未登录 401，其他账号 404；不支持的写正文、聊天、修改、删除请求为 405。
`GET/POST /api/admin/daily-report-settings` 仅管理员可用，正文 `{"paused":true}` 控制全局暂停通知。暂停只影响通知，不影响日报保存、查看、历史。账号接口返回权限但不接受普通用户修改。
设备注册 token 不在响应或日志中返回，脱敏备份会移除设备和投递表；退出或登录 Session 到期后不再向旧绑定投递。每个账号最多 10 个安装实例，同一 token 跨账号去重，只绑定最近注册的登录账号；不会仅根据安装 ID 删除别人的设备。首次注册不为已有日报补建通知；同正文重复发布也只重试原有未确认投递，新设备仅参与后续新日报。

## 本机日报投递

定时任务仍在 Mac 上工作日北京时间 18:30 同步桌面五库：`sunwoo-turborepo`、`sunwoosoft-mono`、`sunwoo_flutter`、`xonion-backend`、`sunwoosoft`（官网）；只有前者更新桌面 `Sunwoo产品总览.md`。按北京时间当日提交与实际源码区分功能、修复、版本配置、合入旧功能与补同步旧提交。不根据无提交推断工作情况，不把源码实现或远程分支称为已上线。

保留本地改动，不切分支、stash、reset、commit；无法快进时记录并继续其他仓库。后端和官网只读审阅 Git 变更，不执行部署、数据库、配置或重启操作。电脑与 Codex 需要保持运行。

准备 UTF-8 JSON 文件，字段为 `date`（北京时间 YYYY-MM-DD）、`content`（Markdown，最多 30000 字）、`simulation`（可选布尔，默认 false）。不含源码、私钥、业务凭据和客户数据。

运行：`python3 scripts/send_frontend_report.py /absolute/path/report.json`。

本机通过已有 SSH 别名 `aliyun_3129`，以服务账号执行 `scripts/publish_frontend_report.py`，正文仅经 stdin 传输，不出现在 shell 参数中。服务器没有额外公网发布密钥。
同账号、同日期、同模拟标记唯一；一次事务向所有启用且开放日报的账号保存相同正文，任一既有正文不同时整批回滚，绝不覆盖。已发布日期固定原接收人，不给后来启用者补写；`skipped_new_recipients` 明确报告跳过。模拟日报不占用正式日报。

CLI `ok=true` 表示本次处理完成，需检查 `recipient_count`；为 0 时没有接收人记录被保存。`reports` 逐人返回 `username`、`report_id`、`created`、`registered_devices`、`push_enabled`、`push_paused`、本次 `delivery` 和累计 `delivery_totals`。顶层为合计，不能代替逐人核对；设备 0 不表示已通知，accepted 只表示苹果接受，pending 等待重试，invalid 需新版重新注册。

关闭账号通知、撤销日报或停用账号会取消 pending/sending；全局暂停也取消未确认投递。恢复时以当前最大日报 ID 为起点，设备注册和重复发布都不能补发此前通知。已交给 APNs 的在途通知无法撤回；系统通知授权始终独立于后台开关。注册接口在无日报权限时 404、通知关闭时 403；全局暂停期间允许保存设备绑定，但不排队发送。

## 服务端配置

- 安装 `deploy/apns-requirements.txt` 的 HTTP/2、ES256 JWT 依赖。
- APNs 私钥：`/etc/ai-platform/apns/key.p8`，目录 0700、文件 0600、仅服务账号可读，不加入 Git、App 或构建产物。
- `/opt/ai-platform/apns.json`：`key_id`、`team_id`、`key_path`；文件同样 0600。Topic 固定 `asia.feng.aimeimei`，端点固定 `https://api.push.apple.com`。
- 此 APNs 密钥与 `ASC_P8_BASE64` 的上传密钥不同，不改后者。
- `ai-platform-reports.timer` 每五分钟重试最近 24 小时内的 pending 投递；正常保存和设备注册也触发投递。发送租约避免多个进程同时发送。
- `accepted` 仅表示 APNs 接受，不等于手机已显示；网络中断时可能重试，collapse ID 帮助合并。`Unregistered` 等无效设备错误停止重试。正文先入库，通知失败不丢内容。

## 验证

隔离服务：`python3 scripts/test_daily_reports.py`，使用临时数据库、合成 EC 密钥和真实本机 HTTP APNs 模拟服务；覆盖摘要格式/截断、中文与 emoji 的 4KB 载荷限制、完整正文保留，以及多账号隔离、独立已读、原子拒绝冲突、动态接收人、开关组合、停用跳过、只重试失败账号、首次设备注册不补推、token 账号切换、鉴权、只读、幂等、分页、过期 Session 和备份脱敏。
iOS 核心 API、原生状态和 UI 回归由 GitHub macOS 流水线运行，截图包括置顶入口和无输入框的日报正文。
签名流水线拒绝缺少 production 推送权限的描述文件。真机验收需安装 TestFlight 0.8.3 或后续版本，使用后台已启用的账号登录并授权通知，核对设备注册及后续真实通知点击跳转；不能以上传成功或 APNs accepted 代替手机验收。自动化测试不向真实手机推送，也不因验收向新设备补推历史日报。

2026-10-28 摘要预览变更已通过 13 项隔离回归，并纳入 v2.29.3 发布；生产部署、APNs 接受与真机展开结果仍须分别核验。新逻辑只影响后续待投递的通知，不会重新发送已 accepted 的旧通知，也无需修改 iOS 客户端。
