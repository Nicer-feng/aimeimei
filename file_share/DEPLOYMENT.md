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
