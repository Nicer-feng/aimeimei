# 文件分享中心 v0.1.3

当前为本地待部署版本；线上版本为0.1.2。

2026-09-14 16:57 已上线：https://feng.asia/admin/share 。真实 OSS 和浏览器闭环通过。

管理员上传私有文件，设置分享规则，通过链接或二维码向无需登录的接收者分发文件。

## 产品与发布边界

- 独立页面：`/admin/share`、`/share/{16位随机短码}`。
- 独立接口：`/api/file-share/admin/*`、`/api/file-share/public/*`。
- 独立后端：`file_share/`；静态资源：`res/file-share/`。
- 独立数据表：`share_files`、`shares`、`share_files_relation`、`share_access_logs`、`share_sessions`、`share_settings`、`share_rate_limits`、`share_audit_logs`。
- 独立版本和更新记录：本目录 `VERSION`、`CHANGELOG.md`，Git 标签建议 `file-share/v0.1.3`。
- 不进入 AI槑槑后台菜单；共享已有管理员登录 Session、SQLite 连接以及 OSS 配置。
- 第一版仍由现有 Python 进程承载，更新后端需要重启该进程，因此暂时不是独立部署单元。后续可以在保持接口和产品目录不变的前提下拆进程。
- AI 对话分享仍使用 `/ai/share/{43位令牌}`，原 `/share/{43位令牌}` 兼容保留。

## 功能

后台含概览、文件、分享、访问记录、回收站和设置。支持多文件选择/拖拽、分片进度、搜索、分类、排序、分页、多文件分享、二维码 PNG、密码重设、有效期/次数限制、暂停/恢复、撤回、回收站恢复与永久删除。设置页可清理未完成上传。

外部分享支持图片缩放/原图、HTML5 视频/音频、PDF 浏览器预览及文本前 1 MB 预览。视频使用 OSS 原生 Range，可拖动进度；5 分钟后再次请求 Range 可能需要关闭并重新打开预览。Office 和压缩包仅提供文件信息及下载。手机浏览器 PDF 内嵌支持不一致，提供“在浏览器中打开 PDF”链接。

图片列表目前使用对应类型图标，不自动拉取全尺寸文件作为缩略图；视频使用图标。

## 运行

现有运行环境新增 Argon2 密码依赖及官方 OSS SDK（V4 签名）：

```sh
python3 -m pip install -r file_share/requirements.txt
AI_PLATFORM_DATA=/tmp/share-dev AI_PLATFORM_LISTEN=127.0.0.1:8080 python3 app.py
```

建议使用虚拟环境。启动时幂等执行 `schema.sql`，只新增产品数据表。该项目是 Python/SQLite，不涉及 xonion 的 MySQL 或 AutoMigrate。

登录复用 `/api/captcha`、`/api/login`、`/api/me` 和 `/api/logout`。分享后台要求有效管理员用户 Session，不接受无用户归属的 `X-Admin-Key` 作为文件所有者。

## OSS

`infrastructure/storage.py` 复用现有 `media_oss_config`（MEDIA 配置优先，回退 CAT 通用配置），没有新增密钥表单，不修改现有 AI/小猫书存储行为。文件对象为 `share/{user_id}/{yyyy}/{mm}/{uuid}.{ext}`。

- 浏览器分块计算 SHA256，数据库保存该哈希，供将来重复文件提示使用；目前不做秒传。
- 全部文件使用 OSS MultipartUpload，分片 8 MB，浏览器同一时间顺序上传。分片失败自动重试最多 3 次。
- 后端签发绑定 object key、upload ID、分片序号和 Content-MD5 的 10 分钟 PUT URL。浏览器不获得 AccessKey Secret，也不获得能自行签名的长期凭据。
- OSS V4 签名协议会在 URL 的 x-oss-credential 中携带 AccessKeyId 标识符及有限期签名；该标识符不是 Secret，不能单独用于上传或访问其它对象。
- 初始化/合并由服务器明确指定对象 ACL `private`。登记文件前验证大小、对象 ACL，并检查匿名请求确实返回 403；公开对象不会登记为可分享文件。
- 服务端只读取头部 4 KB 检测格式，不代理大文件流量。HTML/SVG 默认普通文件，禁止内联预览；内容与声明类型不匹配的上传拒绝登记。
- MIME 采用扩展名白名单、客户端 MIME 和服务端文件头检查。正确类型在上传初始化时写入 OSS，不通过 URL 覆盖 Content-Type。TXT 以 `textContent` 呈现；下载使用 attachment 和安全 Content-Disposition。
- SHA256 来自管理员浏览器增量计算；分片 Content-MD5 由 OSS 校验，不以 MD5 存储密码。
- 默认单文件上限 5 GB，可在设置调整，最高 20 GB；最大 30 个未完成上传。
- 预览和下载都校验有效分享、验证 Session、文件关联、回收站状态和权限，然后签发 300 秒 GET URL。
- 不改变整个共享 Bucket 的 ACL，避免破坏小猫书已有图片；分享对象必须单独私有。真实 Bucket Policy/CORS 仍需上线前检查。

CORS 应保留现有规则，并允许 `https://feng.asia`（如使用 www，则也允许 `https://www.feng.asia`）的 `PUT/GET/HEAD`，请求头 `Content-Type`、`Content-MD5`、`Range`，暴露 `ETag`、`Content-Length`、`Content-Range`、`Accept-Ranges`。OSS 自动处理预检 OPTIONS。不要为此移除现有 POST 规则。为 `share/` 配置未完成分片生命周期清理是额外的兜底措施，不能改成自动删除已完成文件。

## 权限、计数与状态

密码使用 Argon2id，历史明文不保存。生成/重设时返回一次密码；修改规则会增加 auth_version，使旧的 30 分钟 HttpOnly 验证 Cookie 失效。密码错误每 IP、每分享 10 分钟最多尝试 10 次。

POST 接口要求 JSON、`X-Share-Request: 1` 并检查 Origin / Sec-Fetch-Site；所有管理员资源查询绑定当前 user_id。

- PV：通过验证并获准打开一次页面，计 1。仅显示密码输入页不计成功 PV。
- UV：同分享下 IP + UA 的连续访问，距离上次成功访问不足 30 分钟不重复计；另列真实的独立 IP 数。
- 下载：仅点击下载接口后计数，统计的是下载请求，不承诺浏览器已完整保存文件。
- SQLite `BEGIN IMMEDIATE` + 条件 UPDATE 原子控制访问/下载上限，失败请求不会增加成功计数。
- 达到访问上限后拒绝新页面访问；已获准的最后一次访问凭证仍可以预览/下载。
- 达到下载上限后拒绝下载，预览不因此关闭。概览中的有效分享排除任一限额已达的分享。
- 状态 `ACTIVE / EXPIRED / REVOKED / LIMIT_REACHED`，另加 `PAUSED` 表达管理员暂时暂停。
- 暂停可以恢复；撤回不可恢复，但可以用原文件新建分享。延长/编辑不会清零历史计数。
- 撤回后页面/接口立即拒绝；已经签发的 OSS URL 最多仍可访问 5 分钟。
- 关闭下载无法防止接收者保存已经在线预览的内容。
- 回收站中的文件立即不能通过分享取得新 URL，恢复后未失效的分享可重新访问。永久删除保留元数据墓碑，删除 OSS 原文件。中断的永久删除可以从回收站重试。

访问日志区分成功/失败，记录 IP、UA、浏览器、系统、设备、Referer、行为和时间。IP归属地使用IP2Location.io，返回英文国家、省份、城市；失败或内网IP显示横线，原始IP始终保留。默认只信任环回代理地址的 X-Forwarded-For 最后一跳，可通过 `SHARE_TRUSTED_PROXIES` 配置受信代理 IP，不能随意信任公网请求头。

## API 概要

管理员前缀 `/api/file-share/admin`：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/version` | 当前版本、构建和更新记录 |
| GET | `/overview` | 总量和最近记录 |
| GET/POST | `/settings` | 查看/保存独立设置 |
| GET | `/files?search=&type=&sort=newest&page=1&trash=0` | 文件分页 |
| GET/POST | `/uploads` | 未完成上传 / 申请分片上传 |
| POST | `/uploads/{id}/part` | 取得一个分片的短期 PUT URL |
| POST | `/uploads/{id}/complete` | 校验并登记文件 |
| POST | `/uploads/{id}/abort` | 清理未完成任务 |
| POST | `/files/{id}/preview|rename|trash|restore|purge` | 管理员文件操作 |
| GET/POST | `/shares` | 分页 / 创建分享 |
| GET | `/shares/{id}` | 详情与最近访问记录 |
| POST | `/shares/{id}/edit|pause|resume|revoke` | 分享规则与状态 |
| GET | `/logs?page=1&share_id=` | 访问记录分页 |

外部前缀 `/api/file-share/public/{code}`：

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | 空路径 | 有效性与是否需要密码，不返回文件元数据 |
| POST | `/open` | 验证已有 Cookie / 无密码分享，计 PV，返回文件列表 |
| POST | `/password` | 验证密码并打开分享，计 PV |
| POST | `/preview`、`/download` | 按 file_id 申请受限签名 URL |

## 测试与备份

```sh
python3 file_share/tests/run.py
```

测试使用临时 SQLite、测试账号和模拟 OSS，监听本机 18765/18766，结束自动清理。不会读取生产密钥。覆盖并发限额、越权、密码、权限、回收站、MIME、分片、签名、备份脱敏和旧产品路由。浏览器与真实 OSS 验收状态见 `ACCEPTANCE.md`。

现有聊天脱敏备份排除文件分享密码、分享码、验证 Session、访问日志和 upload ID，保留文件元数据。恢复此类备份后必须重新创建分享；若要完整灾备，需另行设计安全的全库备份，不能把脱敏聊天快照当完整恢复方案。

技术参考：[OSS 签名直传](https://www.alibabacloud.com/help/en/oss/user-guide/upload-files-using-presigned-urls)、[Argon2 PasswordHasher](https://argon2-cffi.readthedocs.io/en/stable/api.html)。

## IP归属地配置

服务端读取 IP2LOCATION_API_KEY 环境变量、secrets.json中的ip2location_api_key，或数据目录AI_PLATFORM_DATA下的ip2location.key（权限0600，归服务账号）。Key禁止入Git及前端。当前本地Key已保存到Git忽略的ip2location.key，部署时需单独安全配置，不能放进代码发布包。

当前页日志按IP去重，后台2个工作线程、64个排队任务；公网IP结果缓存7天，失败缓存1小时；401/403/429暂停新查询1小时，网络异常暂停30秒。无Key不调用接口，内网IP不发送给第三方。只查询当前查看的日志，不扫描整库。成功结果不覆写原访问记录，仅关联缓存；缓存最多10000条，并从脱敏备份排除。

日志接口保留country、province、city字段，新增geolocation_status：pending、ready、unavailable、private、unconfigured。列表最多自动重查20次，也可以手动刷新。页面保留IP2Location来源标注。
