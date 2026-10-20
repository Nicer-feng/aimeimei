# GitHub Actions 接入 TestFlight

本机无需安装 Xcode、Transporter 或 fastlane。签名和上传在 GitHub macOS 运行机完成。
现有「iOS 原生客户端」仍只运行测试并生成未签名产物；「iOS TestFlight」单独手动运行，只允许选择 main。

## 1. 确认 Apple 后台材料

- App Store Connect 已创建 iOS 应用，Bundle ID 为 `asia.feng.aimeimei`。
- 付费开发者团队的 Team ID（10 位字母数字），不是应用数字 Apple ID，也不是 API Issuer ID。
- Apple Distribution 发行证书 `.p12`，含私钥，已设置非空导出密码。
- 同一团队、同一 Bundle ID、同一发行证书对应的 App Store Connect 类型 `.mobileprovision`，不是 Development、Ad Hoc 或 Enterprise。
- 上传 API Key 的 `.p8` 和 Key ID。个人密钥不填 Issuer ID；团队密钥还需要 Issuer ID。

描述文件下载入口：Apple Developer → Certificates, Identifiers & Profiles → Profiles → ＋ → Distribution / App Store Connect → 选择应用和证书 → Generate → Download。
`.p12` 文件和 API Key 不在本聊天中交付，也不要提交到 Git。

## 2. 在 GitHub 创建 Secrets

打开 [仓库 Actions Secrets](https://github.com/Nicer-feng/aimeimei/settings/secrets/actions)，点击 **New repository secret**，逐项填写：

| Name | Value | 何时需要 |
|---|---|---|
| `IOS_TEAM_ID` | 10 位 Team ID，直接粘贴 | 签名构建 |
| `IOS_P12_BASE64` | `.p12` 整个文件的 Base64 | 签名构建 |
| `IOS_P12_PASSWORD` | `.p12` 导出密码，直接粘贴，不做 Base64 | 签名构建 |
| `IOS_PROFILE_BASE64` | `.mobileprovision` 整个文件的 Base64 | 签名构建 |
| `ASC_KEY_ID` | `.p8` 对应的 Key ID，直接粘贴 | 上传 |
| `ASC_P8_BASE64` | `.p8` 整个文件的 Base64 | 上传 |
| `ASC_ISSUER_ID` | 团队 API Key 的 Issuer ID | 仅团队密钥；个人密钥不要创建此项 |

如仓库已有同名 Secret，先确认是不是本应用的配置，再更新。Environment `testflight` 内的同名 Secret 会优先于 Repository Secret。

### Mac 上复制文件内容

在终端进入本仓库，依次运行下面的命令。每条命令会弹出文件选择框，把结果复制到剪贴板，不会在终端打印密钥。每运行一条，立刻去 GitHub 对应 Secret 的 Value 粘贴并保存，再执行下一条。

```sh
python3 mobile/ios/scripts/copy-signing-secret.py p12
python3 mobile/ios/scripts/copy-signing-secret.py profile
python3 mobile/ios/scripts/copy-signing-secret.py p8
```

只使用 Mac 自带的 Python、文件选择框和剪贴板。也可以使用 GitHub 官方示例的 `base64 -i 文件路径 | pbcopy`，同样不会显示内容。
Base64 只是文件转成文本，仍属于完整凭据，不要截图、发群或提交。

## 3. 第一次运行

1. 确认本变更已经合并到 main。
2. 打开 **Actions → iOS TestFlight → Run workflow**，分支选择 **main**。
3. 第一次可以不勾选「上传到 App Store Connect」，先验证四项签名配置。也可准备好全部材料后直接勾选上传。
4. 流水线先复用原 iOS 流程，完成核心、原生状态、UI 测试和未签名构建；之后才读取签名 Secrets，校验并导出正式签名 IPA。
5. 勾选上传时，fastlane 将构建上传到已有 App Store Connect 应用；不等待 Apple 的异步处理，不自动邀请测试者或提交外部测试审核。
6. 运行摘要明确显示「仅签名验证」或「已上传，等待 Apple 处理」。上传成功不等于 Apple 处理完成或外部测试审核通过。

TestFlight 使用独立工作流的运行编号和重试次数生成三段构建编号，例如 `1.1.1`，第 100 次运行为 `2.0.1`。同一运行的重试会递增第三段。
已上传成功后需要再发一版时，请重新点击 Run workflow，不要重跑较旧的运行；不要从其它工具上传更高或冲突的构建编号。

Artifacts 中的 `aimeimei-ios-signed-*` 保留正式签名 IPA 与校验信息 3 天。它采用 App Store 分发签名，**不能直接发给朋友点开安装**，应通过 TestFlight 下载。
证书、描述文件、API 私钥不会作为单独 Artifact 保存；任务结束时清理临时钥匙串和签名材料。IPA 自身包含 Apple 要求的嵌入描述文件和签名。

## 4. 在 TestFlight 中启用测试

到 App Store Connect → AI槑槑 → TestFlight，等待上传构建完成处理。如果提示出口合规信息，按应用实际使用的加密情况回答；当前聊天客户端使用系统 HTTPS 和钥匙串，不应直接勾选不符合事实的自定义加密声明。

- 自己和团队成员：创建内部测试组，添加具有应用访问权限的团队用户，选择构建，在 iPhone 的 TestFlight 中接受邀请。
- 朋友或家人：创建外部测试组，补齐测试说明、联系信息和审核演示账号，提交首次外部测试审核；通过后再邀请测试者或启用公开链接。
- 每个构建最多测试 90 天。TestFlight 安装不依赖 Sideloadly，也不需要开发者模式。

## 常见失败

- **缺少 Secrets**：检查 Name 拼写，以及是否在正确仓库设置；个人 API Key 不需要 `ASC_ISSUER_ID`。
- **描述文件与 Team、包名或证书不匹配**：在同一团队重新生成匹配的 App Store Connect 描述文件，更新 `IOS_PROFILE_BASE64`。
- **找不到有效签名私钥**：`.p12` 不是仅含证书的 `.cer`；从持有原私钥的 Mac 导出证书和私钥，不要撤销其它应用正在使用的证书。
- **上传认证失败**：检查 Key ID、密钥种类、Issuer ID（只填团队密钥的值）、用户的应用访问和上传权限。个人 API Key 不能代替签名证书来生成描述文件。
- **GitHub 找不到工作流**：合并到默认分支 main 后刷新 Actions。
- **Apple 处理失败或缺少合规信息**：查看 App Store Connect 的具体提示；GitHub 上传成功后 Apple 仍可能拒绝处理构建。

参考：[GitHub 签名](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications)、[个人与团队 API Key](https://developer.apple.com/documentation/appstoreconnectapi/creating-api-keys-for-app-store-connect-api)、[fastlane 个人密钥](https://docs.fastlane.tools/actions/app_store_connect_api_key/)、[TestFlight](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/)。
