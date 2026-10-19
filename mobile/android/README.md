# AI槑槑 Android 原生客户端

独立版本：0.1.0 基础验证版。Kotlin + Jetpack Compose，最低 Android 8.0（API 26）。
继续使用当前仓库和现有 https://feng.asia 服务器，不启动新后端、不更改网页和数据库。

## 当前交付边界

已准备：独立工程、原生密码/图形验证码登录、Android Keystore 加密会话、已有会话列表、历史消息原生 Markdown 阅读、模型列表接口、退出登录、云端构建和正式签名入口。

本阶段用于先打通 APK 构建与真机连接。不是完整聊天客户端：尚无发送/新建会话、短信登录、附件上传与预览、TTS、搜索、收藏、思考预览、引用、Mermaid 和完整 Markdown 兼容。这些功能在后续按模块接入。历史附件目前仅展示文件名。

当前 App 只调用认证与读取接口，不自动发送聊天消息，不自动消耗模型 Token。历史会话可能包含复杂 Markdown 和引用包装，完整展示兼容性属于下一阶段真机回归范围。

## 你需要操作的顺序

### 第一步：先拿验证包，不填任何 Secrets

1. 本工程及 `.github/workflows/android-build.yml` 推送 main 后，会自动触发 debug 构建。
2. 打开仓库 Actions → **Android 原生客户端** → 最新一次运行。
3. 等待测试、Lint 和 APK 编译完成，运行记录应显示绿色。
4. 在页面底部 Artifacts 下载 `aimeimei-android-debug-运行编号`，解压后取得 APK。
5. 安卓手机允许对应下载/文件应用安装此 APK；登录自己的现有槑槑账号，验证登录和历史读取。

若没有自动运行，进入同名工作流 → Run workflow → main → build_type 选 debug。
若 GitHub 提示 Actions 被禁用或依赖 Action 被限制，在 Settings → Actions → General 中按提示允许本工作流所需 Action；不要为此开启写入整个仓库的默认令牌权限。

debug 包名称为“AI槑槑·验证”，包名 `asia.feng.aimeimei.dev`，与正式包分离。它使用云端临时调试签名；不同次构建可能不能直接覆盖安装，需要卸载旧验证包后再安装。本包不能当家庭长期分发版本。

### 第二步：验证通过后准备长期签名

先确认最终包名 `asia.feng.aimeimei` 和 App 名称“AI槑槑”。再在带 JDK 的云端终端（如 GitHub Codespaces）运行：

```sh
bash mobile/android/scripts/create-signing-key.sh
```

它会交互要求 keystore 密码和 key 密码；key 别名固定为 `aimeimei`。可以在 keytool 提示时选择复用同一密码。文件保存在云端用户主目录的 `aimeimei-android-signing/`，不会写到仓库。

下载 `aimeimei-release.jks` 离线备份，并单独保管两种密码。后续每次正式构建必须复用同一份文件和别名，不能重新生成。不要将签名文件、Base64 内容和密码放入 Git、Issue、聊天或构建日志。

### 第三步：配置四项 Actions Secrets

仓库 Settings → Secrets and variables → Actions → New repository secret：

| Name | Value |
|---|---|
| ANDROID_KEYSTORE_BASE64 | 云端生成的 signing-keystore.base64 文件完整内容 |
| ANDROID_KEYSTORE_PASSWORD | 创建 keystore 时设置的密码 |
| ANDROID_KEY_ALIAS | aimeimei |
| ANDROID_KEY_PASSWORD | 创建 key 时设置的密码；如选择复用，填同一密码 |

这些是 GitHub Actions Secrets，与 Postman 的普通环境变量约定无关。网页使用的模型/OSS/SMS 密钥不需要也不能放进 App。

### 第四步：构建正式 APK

Actions → Android 原生客户端 → Run workflow → main → build_type 选 release。
下载对应 `aimeimei-android-release-运行编号` 中的 APK，再按各手机的安装规则安装。此流程不自动上传应用商店。

当前仓库为公开仓库，APK 与不含凭证的测试报告按 GitHub 仓库权限可见；工作流只上传 APK 和测试报告，绝不上传签名文件。正式包仍要求现有账号登录才能访问聊天数据。

## 可选配置

默认服务器是 `https://feng.asia/`，无需配置。仅在开发者明确需要其它 HTTPS 服务器时，在同一 Actions 页的 Variables 中新增 `ANDROID_API_BASE_URL`。要求只有 HTTPS origin，不能包含用户名、密码、路径、query 或 fragment。

## 构建环境

- 云端：Ubuntu 24.04、Temurin JDK 17、Gradle 8.13、Android SDK 36、Build Tools 36.0.0。
- 固定 AGP 8.13.0、Kotlin 2.2.20、Compose BOM 2025.09.01，避免动态依赖版本。
- 初期由 setup-gradle 安装固定版本 Gradle，使用 `gradle -p mobile/android ...`；当前不要求本机 Gradle 或 Wrapper。
- push 只匹配 `mobile/android/**` 和 Android workflow；普通网站改动不触发构建。也可手动运行。
- 默认 GITHUB_TOKEN 仅 contents:read，无服务器 SSH 权限，也无生产部署步骤。
- 测试和 Lint 先于 APK 交付；产物保留 7 天。缺少正式签名时 release 明确失败，不能降级为未签名 APK。

## 后续实施顺序

1. 验证工程在云端成功编译，并在真实安卓设备确认中文、键盘、安全区、验证码及登录会话。
2. 原生聊天核心：新建/切换会话、模型和档位、独立消息状态、SSE 解析、停止生成、后台返回恢复；保留 `message_saved` 完成语义，EOF 不能当成功。
3. 图像与文档：系统文件选择、现有 OSS 上传许可、解析状态和附件发送，避免把 AccessKey 写进客户端。
4. Markdown、长表格、引用、思考、来源、TTS、收藏等逐项适配。管理后台继续使用网页；PC 专属阅读/并行讨论无需机械搬到手机。

## 接口盘点

见 [API_MAPPING.md](API_MAPPING.md)。所有接口来自现有实现；客户端接口兼容性不等于已经完成各功能 UI。服务器保持按账号隔离，客户端不能传管理员密钥替代登录。
