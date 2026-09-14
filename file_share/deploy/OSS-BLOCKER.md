# OSS配置阻塞已解决

用户完成配置后，私有ACL、匿名403、V4签名、Range206和跨域PUT均通过。临时对象已清理，产品已上线。以下为历史记录，不需要重复操作。

# OSS 配置待调整（2026-09-14 更新）

RAM 补充策略已生效。之前 Bucket 查询 403 的具体错误为 `V1 url signature is forbidden`，不能仅凭状态码归因于 RAM。文件分享签名已切换官方 oss2 2.19.1 的 V4，实现与本地回归通过。

实际查到 Bucket `feng-asia`（北京）的 ACL 是 private，但 Bucket Policy 最后一条允许 Principal=* 读取全部对象，覆盖对象私有权限。此前 4 字节验收对象已成功删除。

## 两处具体调整

1. 在 OSS → feng-asia → 权限控制 → Bucket 授权策略，将当前 Bucket Policy 替换为本目录 `oss-bucket-policy-private-share.json`。**这是 OSS Bucket Policy，不是 RAM 策略**。
   - 两条现有 RAM 主体授权保持原样。
   - 最后一条匿名 Allow 的资源由整个 Bucket 缩小到当前既有前缀：backups/、cat/、chat-images/、documents/、ocr/、tingwu/、tts/。
   - 新的 share/ 不再包含在匿名 Allow 中，其 private ACL 生效。
   - 不改变上述现有前缀的访问方式。以后新增其它需要公开的顶层目录，要显式加入规则。
2. 在 OSS → feng-asia → 数据管理 → 跨域设置，编辑现有规则：
   - 来源保持原样（feng.asia/www 的 http/https）。
   - Allowed Methods 从 GET、POST、HEAD 改为 GET、POST、HEAD、PUT。
   - Allowed Headers 保留 `*`。
   - Expose Headers 保留 ETag、x-oss-request-id，并添加 Content-Length、Content-Range、Accept-Ranges。

暂未执行 Bucket Policy/CORS 写操作。当前 RAM 补充策略仅授予配置读取，不授予修改整个 Bucket 配置。

部署备份 `/opt/ai-platform-release-backups/file-share-before-20260914-145550/` 保留；代码在暂存目录，Argon2 和 OSS SDK 已安装到独立虚拟环境。尚未切换服务或重启。

配置调整后：先验证私有对象匿名 403、V4 签名 200、视频 Range 206、跨域 PUT，然后部署并执行 PNG/MP4/PDF 浏览器验收。
