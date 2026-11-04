# OpenAI 专用出站代理

此组件不设置系统代理，不创建 TUN，不修改系统 DNS、路由、防火墙或安全组。仅 `https://api.openai.com/v1/*` 经本机 HTTP CONNECT 代理；关闭总开关后拒绝新的官方 OpenAI 请求，不静默回落直连。其它模型、OSS、听悟、短信等保持原路径。改变端口不能规避云厂商监测或替代服务使用许可。

## 安装

本轮固定内核为官方 `v1.19.33`，Linux amd64 v1 gzip 资产 SHA256：`8ec92e7b2fdc6b853ba00156bab7e4e965c8b0d843b8c4ac8ab98795f02ad524`（从同一官方 release asset digest 核对）。内核二进制不提交到业务仓库；其许可证见官方仓库。

先发布包含本模块的服务端代码，再从 [Mihomo 官方发布页](https://github.com/MetaCubeX/mihomo/releases)下载与 CPU 匹配的固定版本 Linux amd64 v1 gzip 资产。取得同一官方 release asset 的 SHA256 digest；不要使用第三方镜像、滚动 latest 文件或未校验二进制。

```sh
cd /opt/ai-platform
python3 deploy/openai-egress/install.py --archive /tmp/mihomo-linux-amd64-v1-VERSION.gz --version vVERSION --sha256 OFFICIAL_ARCHIVE_SHA256
```

安装器只安装独立低权限服务，监听 `127.0.0.1:17891`（HTTP 代理）、`127.0.0.1:17892`（带随机认证的控制接口）。端口需未被占用。系统单元有内存、CPU、文件系统权限限制，无网络管理 capability。内核日志不输出订阅凭证；systemd 保留生命周期记录。初次安装默认关闭、无订阅、无 OpenAI Key，不发任何外网测试。

已有客户端凭证时安装器拒绝覆盖。升级内核需先备份二进制、运行配置和 unit，然后校验新版本，等待 OpenAI 请求空闲后再单独重启 `ai-platform-egress`。不要重新生成已有认证文件。

## 用户配置顺序

1. 后台管理 → OpenAI 代理，填写 **HTTPS Clash/Mihomo 格式**订阅，点“更新订阅”。普通 V2Ray base64 订阅需在供应商后台选择 Clash 格式；不使用第三方订阅转换站。
2. 选择节点，勾选启用，点“保存开关与节点”。更换订阅后总开关会先关闭，需重新选择节点再启用。
3. 点“测试代理”。使用无认证的官方模型目录请求，收到正常 HTTPS 的 401 也证明通道可达，不发送聊天。
4. 模型管理新增所需官方模型，Base URL 为 `https://api.openai.com/v1`，Model 填账号实际可访问且兼容现有 Chat Completions 的模型 ID；密钥管理填写官方 API Key。不要将 OpenAI 模型勾选为“百炼原生联网”。仅支持 Responses 的模型需要另外适配，本功能不改写主聊天协议。
5. 在密钥管理点“测试连接”，或 OpenAI 代理页选择模型点“测试 API”。认证 GET `/v1/models/{model}`，不生成内容、不验证生成额度，404 可能表示不存在或无权限。

模型状态：灰色未检查/关闭，琥珀色检查中，绿色最近接口及模型权限检查通过，红色最近检查失败。悬停查看文字原因。选中模型或聚焦输入区时才按需检查，前后端缓存 90 秒、同模型合并并发，全局最多同时两项自动检查；无定时测速、无轮询、无伪造聊天。缓存过期后再次交互才更新，灯是最近状态而不是实时在线保证。

## 数据与安全

- `/opt/ai-platform/openai-egress.json`：总开关、订阅凭证、节点；`0600`，仅服务端可读写。
- `/opt/ai-platform/openai-egress-client.json`：本机代理和控制认证；`0600`，不返回浏览器。
- `/var/lib/ai-platform-egress/config.json`、`subscription.yaml`：受限服务目录和文件权限。订阅由应用按需获取，校验每次跳转、固定已验证公网 IP 并执行 TLS 主机名验证，20 秒总预算、单连接 8 秒、最大 2MB。只作为 file provider 导入节点，绝不加载订阅中的系统路由/DNS/TUN 配置。
- 不缓存 API Key 到浏览器存储，不回显订阅链接，不输出敏感请求/响应日志。
- 更新订阅、切换节点时如有官方 OpenAI 请求进行中则返回冲突；总开关关闭不强杀已经建立的请求。
- 正式使用前需自行确认服务商及 OpenAI 地区/账号使用资格。代理连接成功不改变资格限制。

## 回退

后台关闭总开关即可阻止新的官方 OpenAI 请求。需要卸载服务时先关闭开关、等待请求空闲，再 `systemctl disable --now ai-platform-egress`，保留配置备份。其它业务不依赖此 systemd 服务。禁止将本机代理端口开放到公网。

## 验证边界

本地 TLS CONNECT/控制接口模拟测试验证路由、认证、失败关闭、缓存、并发和错误隔离；网页自动化验证状态灯与后台入口。无用户订阅和真实官方 Key 时，不能声称已完成实际节点、账号或模型生成验收。
