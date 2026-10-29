# 客户端设备与登录历史

仅 AI槑槑管理员可查询；所有账号及 PC Web、手机浏览器、iOS、Android 都参与记录。设备资料为客户端声明，不是认证凭据，不采集硬件唯一标识，不发送到模型、第三方统计或 IP 定位服务。

## 数据与权限

- `auth_devices` 按账号和随机安装实例聚合最近资料；重装或实例 ID 改变可产生新记录，不识别物理手机。
- `auth_login_events` 仅成功密码/短信登录创建，固定当次服务端时间、来源 IP 与客户端快照。失败登录、普通请求、旧会话补报均不创建事件。
- `auth_session_history` 独立于可清理的 sessions，保留退出、过期、停用/失效状态。有效会话不等于在线。
- 最近活跃是最近已认证请求，含应用刷新，最多约每 60 秒写入；最近活跃 IP 单独保存，不覆盖登录 IP。
- 旧会话补报只保存当前声明资料和真实上报时间，不回填过去的型号或登录事件；未记录的首次登录显示“未记录”。内嵌网页沿用原生会话时不覆盖原生资料。

| 接口 | 权限与作用 |
| --- | --- |
| `POST /api/session/device-info` | 已登录账号，仅更新当前会话；返回 ok，不回传设备或 IP |
| `GET /api/admin/login-records` | 管理员，全局成功登录记录 |
| `GET /api/admin/users/{id}/devices` | 管理员，指定账号设备记录 |

查询参数 `before`、`limit`（1–100，默认50）；登录记录另支持 `user_id`、`platform`、`from`、`to`（北京时间 YYYY-MM-DD）。响应以 `next_before` 游标分页，不返回 Session、token、安装实例 ID 或其他凭据。

登录 JSON 可选 `client` 对象；补报接口直接接收该对象。字段为 `installation_id`、`platform`（ios/android/web）、`manufacturer`、`model`、`os_version`、`app_version`、`app_build`、`notification_authorization`。缺失或损坏的可选登录资料不影响旧版登录；服务端只保存白名单字段。

## 来源与保留

实际 Caddy 上游为 127.0.0.1:8000，无额外可信上游或 header_up 覆写。应用通过 `AI_PLATFORM_TRUSTED_PROXIES` 明确配置可信 CIDR，生产只信任本机 Caddy。非可信连接忽略 X-Forwarded-For；可信链从右向左解析 IPv4/IPv6，缺失或损坏时显示未记录，不用代理地址冒充来源。Caddy 默认丢弃不可信传入的转发值：[官方说明](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy#headers)。IP 是服务端观测来源，不推断住址或身份。

UA 解析使用固定版本本地 ua-parser，浏览器硬件型号不猜测；iOS 未映射时显示 uname 硬件标识，Android 保留厂商内部型号。

登录事件保留90天。过期/退出会话及无近期活动的设备也按90天清理；当前有效会话保留，活跃安装实例保留聚合信息。服务每五分钟检查，每表最多清理500条，查询不展示过期登录事件。不清理其他业务日志。脱敏备份移除本功能私有表；完整备份同样去掉新增登录/活跃 IP，不把它们发送到第三方备份存储。

通知授权显示客户端最近上报时间；推送注册、绑定会话是否有效、后台通知策略分别展示。Android/Web 推送显示未接入，APNs accepted 只表示苹果接受，不是手机送达。
