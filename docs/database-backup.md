# 数据库备份与离线恢复

现有每日任务默认继续生成 `sanitized` 脱敏备份。它保留聊天等资料，但清空账号密码哈希、手机号、模型密钥，并删除登录会话、分享链接及文件关联等记录，不能作为完整业务恢复文件。

本批新增显式 `full` 完整数据库模式，保留当前共享 SQLite 中所有产品的表、数据、索引和关联；包括 AI槑槑、槑槑云、Office/PDF 版本关系及小猫书。归档内的 `backup_manifest` 记录时间、执行备份时的代码版本、构建和是否脱敏，恢复默认要求 `full`，不会误把脱敏库当完整库。

## 范围与兼容

| 入口 | 默认模式 | 加密格式 | 用途 |
|---|---|---|---|
| 现有 `scripts/backup_chat_to_oss.py` | sanitized | 原 `.sqlite.gz.enc` 格式，保持兼容 | 每日聊天资料备份 |
| 上述脚本显式 `--mode full` | full | 新 `.sqlite.gz.auth.enc` 格式 | 完整数据库备份；本批未启用生产定时任务 |
| 新 `scripts/backup_database.py create` | sanitized，可显式 full | 新认证格式 | 本地备份和恢复演练，不访问 OSS |

新格式使用 AES-256-CBC + PBKDF2 加密，并以独立派生密钥做 HMAC-SHA256，覆盖格式头和全部密文。恢复时先认证，再解密、解压、检查 SQLite 完整性及备份模式；full 另检查外键。错误密钥、截断、篡改、用途不符都不能输出目标数据库。

仍使用已有 `AI_PLATFORM_BACKUP_KEY_FILE` 指向的独立密钥，无需新依赖或新账号。只依赖 Python 标准库和现有 OpenSSL。密钥首行必须至少 32 字节且不含 NUL 字符（OpenSSL 只读取口令文件首行），单独安全保管，不能放进 Git 或与归档一起存放。完整归档包含数据库内的账号密码哈希、模型密钥和令牌；切换到完整模式应明确备份保管人和密钥的独立留存方式。

数据库归档**不包含** `secrets.json`、systemd 环境变量、代码、证书或 OSS 对象文件。文件分享、图片、音视频和文档版本恢复后依赖原 OSS 对象仍然存在，以及独立恢复所需的服务配置。它是完整数据库恢复能力，不等于整站所有资源备份。

## 本地演练

以下命令只操作显式传入的本地路径。示例中的 `./recovery` 需要先创建。恢复目标必须是不存在的新文件；已有数据库、软链接或同名文件都会拒绝覆盖。

```bash
python3 scripts/backup_database.py create \
  --source /path/to/offline-source.db \
  --output ./recovery/full.sqlite.gz.auth.enc \
  --key-file /path/to/backup.key \
  --mode full

python3 scripts/backup_database.py verify \
  --archive ./recovery/full.sqlite.gz.auth.enc \
  --key-file /path/to/backup.key

python3 scripts/backup_database.py restore \
  --archive ./recovery/full.sqlite.gz.auth.enc \
  --output ./recovery/restored.db \
  --key-file /path/to/backup.key
```

默认解压上限为 2048 MB；需要更大数据库时显式增加 `--max-size-mb`。若校验本地新格式的脱敏归档，必须传 `--expected-mode sanitized`。命令只输出版本、模式、大小、表数量和校验状态，不输出业务数据或密钥。

`verify` 完成与恢复相同的认证、解压和数据库检查，随后删除自身临时目录。`restore` 先在目标目录内完成验证，再以不可覆盖的方式一次性发布离线数据库文件；不会停止服务、迁移数据库或替换正在使用的数据库。

版本与构建读取自执行工具所在仓库；若输入的是旧离线库，它们不代表自动识别了旧库的应用版本。校验通过后，应使用与源库匹配的代码在隔离环境验收账号、聊天、文件关系和版本记录。切换生产数据库仍是单独的人工操作，需要先停写、保留当前库与配置备份，并明确批准。本脚本不提供覆盖生产的开关。

## 旧归档

原每日任务的 `.sqlite.gz.enc` 仍按原 OpenSSL 解密和 gzip 解压方式处理，不被新恢复工具自动接受。旧格式没有本批新增的 HMAC 认证，SQLite 的 `integrity_check` 只检查结构，不能替代归档来源和字节完整性校验。旧归档内 `backup_manifest.sanitized=1`，恢复登录、模型密钥、分享链接等需要另行重建。

## 完整模式的 OSS 入口

`python3 scripts/backup_chat_to_oss.py --mode full` 会读取现有备份配置和密钥，并访问 OSS。本批只实现此入口，未运行真实上传、清理、恢复或修改生产 service/timer。

完整归档默认放在原 `AI_PLATFORM_BACKUP_PREFIX` 下的 `/full/YYYY/MM/`，文件名为 `full-backup-时间.sqlite.gz.auth.enc`；可通过 `AI_PLATFORM_FULL_BACKUP_PREFIX` 单独指定。原脱敏任务仅匹配 `chat-backup-*.sqlite.gz.enc`，完整任务仅匹配新格式，避免两种保留策略互相清理。现有保留天数配置继续适用；完整模式发现匿名访问可用时失败并跳过保留清理，不自动删除对象。

要上线完整备份，需要另外决定是否保留脱敏任务，以及完整任务的运行时间、前缀和保留期限，再修改生产配置。当前每日任务默认行为保持兼容。

## 验证

```bash
python3 scripts/test_backup_recovery.py
```

测试使用临时数据库、假凭据、假 OSS 适配器和临时密钥，覆盖实际 AI/文件分享建表结构、WAL 数据、完整恢复、原脱敏兼容、模式混淆、错误密钥、篡改/截断、解压上限、现有文件保护以及数据库连接失败清理；不连接真实 OSS。
