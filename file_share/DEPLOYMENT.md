# 文件分享中心 v0.1.0 部署记录

已于2026-09-14 16:57上线：https://feng.asia/admin/share 。

- 代码：/opt/ai-platform/file_share、infrastructure、res/file-share；app.py仅接入路由和幂等建表。
- Caddy新增/admin/share和/share/*路由，validate和reload通过。
- systemd通过90-file-share-python.conf使用/opt/ai-platform/.venv/bin/python。
- 依赖：argon2-cffi==25.1.0、oss2==2.19.1，分享使用V4签名。
- 备份：/opt/ai-platform-release-backups/file-share-deploy-20260914-165716/，含代码、配置和一致性SQLite快照。
- 新增数据表，不覆盖原库；AI版本保持2.24.2。
- OSS配置由用户在控制台调整，现有公开资源规则保留，share/单独私有。
- 真实OSS与浏览器验收通过，详见ACCEPTANCE.md。
- 两条验收分享已撤回，三个样例文件保留。

后续回退必须先确认，只恢复本次代码/服务/代理配置；新增表保留，不删表、不覆盖SQLite。

## v0.1.1 - 2026-09-14

- 构建：20260914-193510；下拉框统一、版本信息弹窗、文件重命名。
- 只更新文件分享中心代码与静态资源，不调整数据库结构、OSS 或代理配置。
- 发布前备份：/opt/ai-platform-release-backups/file-share-0.1.1-20260914-193510/。
- 隔离接口回归与桌面/手机尺寸浏览器验收通过。

## v0.1.2 - 已上线

构建 20260914-200058。更新提示及上传刷新保护已完成本地验证。用户明确确认部署后已上线。备份：/opt/ai-platform-release-backups/file-share-0.1.2-20260914-200058/。服务运行正常，公网构建号和资源哈希一致，主页、AI槑槑和小猫书基础访问通过。

## v0.1.3 - 已上线

新增IP归属地查询及日志列。需要发布infrastructure/ip_geolocation.py、file_share/schema.sql及相关界面/版本文件、ai_platform/backup.py；新增缓存表幂等创建。Key单独配置在生产数据目录ip2location.key，权限0600、归ai-platform账号；不通过Git或前端分发。用户明确授权后已部署，服务正常。备份：/opt/ai-platform-release-backups/file-share-0.1.3-20260914-202421/。生产服务账号真实IP查询及缓存验证通过，Key权限0600；公网页面、资源哈希和其它产品基础访问检查通过。

## v0.1.4 - 已上线

登录页、全部后台页面和外部分享页新增备案页脚，直接复用AI槑槑号码、查询链接及/res/public-security-badge.png。仅页面、样式与版本改动，无数据库或配置变更。

构建20260914-205334已部署。备份：/opt/ai-platform-release-backups/file-share-0.1.4-20260914-205334/。公网页面备案文字、链接和图标检查通过，服务正常。

## v0.1.5 - 已上线

构建20260914-210513。单文件上限500 MB（524288000字节），新上传与后续分片/合并请求统一校验，旧设置上限自动收紧，新账号默认500 MB。已有READY文件不受影响。备份：/opt/ai-platform-release-backups/file-share-0.1.5-20260914-210513/。生产只读核对通过。

## v0.1.6 - 已上线

构建20260915-085959。网页品牌名称统一为槑槑云。仅静态页面、JS文字及版本更新，不重启服务，不更改路由、分享码、数据库或OSS对象。备份：/opt/ai-platform-release-backups/file-share-0.1.6-20260915-085959/。公网文案及JS校验值一致。

## v0.1.7 - 已上线

构建20260921-180051。新增短信登录界面，全部复用AI槑槑现有短信API和配置。仅静态文件与版本发布，无配置/数据库结构变更，无服务重启。备份：/opt/ai-platform-release-backups/file-share-0.1.7-20260921-180051/。公网配置已启用，AI版本仍为2.26.0。

## v0.1.8 - 待发布

构建20260921-181430。短信登录去除图形验证码；账号密码登录保留图形验证码。需同时发布AI槑槑后端、槑槑云静态页面与JS；AI服务重启后生效。

## 2026-09-23 v0.1.9

文件管理新增三种视图、右键菜单、整区拖放上传和刷新。构建 20260923-091510，静态部署无需重启。备份：`/opt/ai-platform-release-backups/file-share-0.1.9-20260923-091510/`。公网后台构建号和 JS/CSS SHA256 验证通过，各产品基础路由正常，AI槑槑仍为 v2.26.1。

## 2026-09-23 v0.2.0

构建20260923-093032。新增云独立权限表与平台统计，备份代码及数据库后重启共享服务，服务正常。备份 `/opt/ai-platform-release-backups/file-share-0.2.0-20260923-093032/`。AI版本仍为v2.26.1。公网新页面和三份JS/CSS哈希、匿名平台接口拒绝及权限表迁移已验证。
