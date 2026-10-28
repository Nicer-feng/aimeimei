# 前端研发日报与 iOS 推送

## 边界

- 仅启用的 `feng` 账号可读取日报或注册通知设备；管理员身份不能越过账号隔离。
- 日报使用独立表，不创建普通聊天、不关联模型、不消耗 Token。客户端没有输入、续写、重生成或追问入口；服务端没有公网写正文接口。
- iOS 0.8.0 起，历史列表固定置顶“前端研发日报”，点击普通 APNs alert 后打开对应日报。未登录时先登录；其他账号不会展示正文。
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
设备注册 token 不在响应或日志中返回，脱敏备份会移除设备和投递表；退出或登录 Session 到期后不再向旧绑定投递。每个账号最多 10 个安装实例，同一 token 去重。

## 本机日报投递

定时任务仍在 Mac 上工作日北京时间 18:30 拉取三库：`sunwoo-turborepo`、`sunwoosoft-mono`、`sunwoo_flutter`；只有前者更新桌面 `Sunwoo产品总览.md`。区分当日代码、版本提交、合入旧功能与补同步旧提交。

准备 UTF-8 JSON 文件，字段为 `date`（北京时间 YYYY-MM-DD）、`content`（Markdown，最多 30000 字）、`simulation`（可选布尔，默认 false）。不含源码、私钥、业务凭据和客户数据。

运行：`python3 scripts/send_frontend_report.py /absolute/path/report.json`。

本机通过已有 SSH 别名 `aliyun_3129`，以服务账号执行 `scripts/publish_frontend_report.py`，正文仅经 stdin 传输，不出现在 shell 参数中。服务器没有额外公网发布密钥。
同账号、同日期、同模拟标记唯一；相同正文重复提交只重试未确认投递，正文不同则拒绝覆盖。模拟日报不占用当日正式日报。

## 服务端配置

- 安装 `deploy/apns-requirements.txt` 的 HTTP/2、ES256 JWT 依赖。
- APNs 私钥：`/etc/ai-platform/apns/key.p8`，目录 0700、文件 0600、仅服务账号可读，不加入 Git、App 或构建产物。
- `/opt/ai-platform/apns.json`：`key_id`、`team_id`、`key_path`；文件同样 0600。Topic 固定 `asia.feng.aimeimei`，端点固定 `https://api.push.apple.com`。
- 此 APNs 密钥与 `ASC_P8_BASE64` 的上传密钥不同，不改后者。
- `ai-platform-reports.timer` 每五分钟重试最近 24 小时内的 pending 投递；正常保存和设备注册也触发投递。发送租约避免多个进程同时发送。
- `accepted` 仅表示 APNs 接受，不等于手机已显示；网络中断时可能重试，collapse ID 帮助合并。`Unregistered` 等无效设备错误停止重试。正文先入库，通知失败不丢内容。

## 验证

隔离服务：`python3 scripts/test_daily_reports.py`，使用临时数据库、合成 EC 密钥和真实本机 HTTP APNs 模拟服务；覆盖摘要格式/截断、中文与 emoji 的 4KB 载荷限制、完整正文保留，以及鉴权、只读、幂等、分页、失败重试、token 去重、过期 Session 和备份脱敏。
iOS 核心 API、原生状态和 UI 回归由 GitHub macOS 流水线运行，截图包括置顶入口和无输入框的日报正文。
签名流水线拒绝缺少 production 推送权限的描述文件。最终必须安装 TestFlight 0.8.0，以 feng 登录并授权通知，核对设备注册及真实通知点击跳转；不能以上传成功或 APNs accepted 代替手机验收。

2026-10-28 摘要预览变更已通过 13 项隔离回归，并纳入 v2.29.3 发布；生产部署、APNs 接受与真机展开结果仍须分别核验。新逻辑只影响后续待投递的通知，不会重新发送已 accepted 的旧通知，也无需修改 iOS 客户端。
