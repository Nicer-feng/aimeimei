# AI槑槑 iOS 原生客户端

独立版本 **0.1.0**，SwiftUI，最低 **iOS 17.0**，当前面向 iPhone。
代码与 Android 共仓，使用 `mobile/ios/` 和独立 iOS 工作流，不修改 Android、网页、后端、数据库或生产部署。

## 首版范围

- 用户名、密码和原生图形验证码登录；Keychain 保存服务端 `ap_session`，不保存密码。
- 正常冷启动展示新聊天，点击新聊天不创建空会话；第一次发送时才创建。
- 历史列表、标题搜索、切换、重命名、置顶、确认删除。
- 原有聊天接口的 SSE 流式回答、思考展示、停止接收、模型切换、能力控制的思考档位和联网开关。
- 常用 Markdown 标题、段落、列表、引用、代码块及横向滚动表格，复制、分享；不执行 HTML。
- 草稿按账号和会话隔离，写入应用私有且排除备份的目录；登录 Cookie 使用本机不可迁移钥匙串。
- 跟随系统、浅色、深色，系统字体、键盘安全区及横屏适配。

未纳入首版：短信登录、图片/文件上传和预览、TTS、推送、网页工具、Mermaid、完整嵌套 Markdown 兼容。旧历史附件只显示文件名。

服务器为固定 `https://feng.asia/`，复用现有账号和云端历史。普通用户 API 不需要管理员密钥或模型 API Key。
联网开关沿用服务器现有搜索策略，关闭不等于禁止服务器已配置的自动搜索。

## 先用 GitHub 云端构建，不需要本机 Xcode 或开发者账号

进入仓库 **Actions → iOS 原生客户端 → Run workflow**，选择包含本工程的分支。
默认分支尚未包含工作流时，可先查看 iOS PR 对应的运行记录。
只修改 `mobile/ios/**` 或 iOS workflow 才会触发 iOS 构建；与 Android 使用不同并发组，互不取消。

构建机为 GitHub 标准 **macos-15 + Xcode 26.3**，部署目标仍是 iOS 17。
固定 XcodeGen **2.46.0**，下载后核对 SHA-256。工程由 `project.yml` 生成，不手工维护 pbxproj。
不使用任何 Apple/GitHub Secrets，不上传 TestFlight、不创建公开 Release、不访问生产服务器。

流水线依次运行：

1. 原生协议核心测试（验证码登录参数、Cookie、SSE、待核对恢复、草稿隔离等）。
2. 生成工程，先编译应用和测试，再选择当前 Xcode SDK 对应的稳定 iPhone 模拟器；启动最多等待 4 分钟。
3. 编译 SwiftUI 应用，运行离线 UI 验收并保存截图；测试只使用 Debug 注入的合成数据。
4. Release 构建真机架构应用，打包**未签名 IPA**。

绿色运行的 Artifacts：

| 产物 | 用途 |
|---|---|
| `aimeimei-ios-simulator-运行编号` | 模拟器 `.app` 压缩包，仅供 Mac 的 iOS 模拟器运行 |
| `aimeimei-ios-unsigned-运行编号` | 未签名真机 IPA、校验和及说明；不能直接安装 |
| `aimeimei-ios-screenshots-运行编号` | 离线 UI 测试截图及测试结果汇总 |

产物保留 7 天；失败时保留诊断日志和 xcresult 3 天。模拟器 app 为 Debug，只有显式 `--ui-testing` 才启用离线数据；普通打开仍连接真实后端。真机 Release 包不编译离线登录实现。

## 免费 Apple 账号在自己手机上测试

**云端打包不需要本机安装 Xcode，但免费账号签名安装是另外一步。未签名 IPA 不能直接点开安装，也不能直接上传 TestFlight。**

官方临时真机测试方式：

1. 在 Mac 安装完整 Xcode 及必要设备支持组件。在 Xcode Settings → Accounts 登录自己的 Apple 账号。
2. 拉取代码，运行 `bash mobile/ios/scripts/generate-project.sh`，打开 `mobile/ios/Meimei.xcodeproj`。
3. 选 Meimei target → Signing & Capabilities → Automatically manage signing → 选择自己的 Personal Team。
4. 若包名被其它 Team 占用，将**本机工程** Bundle Identifier 改成自己的唯一值，例如 `asia.feng.aimeimei.personal.自定义后缀`，不必修改共用包名或提交个人配置。
5. 连接 iPhone、信任电脑，按设备提示启用 Developer Mode，选择该设备运行。

免费 Personal Team 的设备安装描述文件通常 **7 天到期**，需要重新构建安装。
如果手机运行 iOS 27 或更新系统，真机调试需使用支持该设备系统的 Xcode；当前云端使用稳定 SDK 不等于已完成这些手机的真机验收。
如果暂时不想装完整 Xcode，也可以先尝试 **GitHub 未签名 IPA → 本机 Sideloadly 重签 → USB 安装**：从 [Sideloadly 官网](https://sideloadly.io/) 下载 Mac 版本，连接并信任 iPhone，导入构建产物中的 `aimeimei-ios-unsigned.ipa`，在本机工具内填写自己的免费 Apple 账号，按提示签名安装和开启 Developer Mode。该工具官方说明支持免费账号和 7 天续签；当前未在你的 iOS 27 设备上验证兼容性，不能把签名工具的支持说明当成真机成功证明。

第三方本机签名工具不由本项目维护，本次不自动安装或替你登录。Apple 密码和验证码只在你本机输入，不提供给 Codex、不放进 GitHub；如果遇到新系统签名兼容问题，再使用支持设备系统的 Xcode，或后续接入同事的付费账号与 TestFlight。

## 后续再接 TestFlight

到首次上传时，请付费账号持有人配合：

1. 确认个人或组织账号及应用归属；个人账号的 App Store Connect 邀请不提供 Certificates, Identifiers & Profiles 权限。
2. 注册最终 Bundle ID，建立 App Store Connect 应用记录。
3. 准备含私钥的发行证书 `.p12`、密码及匹配的分发描述文件。
4. 准备 App Store Connect API Key（`.p8`、Key ID、Issuer ID），配置仓库 Secrets。
5. 再增加签名和上传工作流，按构建递增 build number；不会将未签名流程偷偷切换为自动发布。
6. 外部测试准备测试说明、联系邮箱及供审核使用的独立账号，完成测试审核。TestFlight 每个构建最长可测试 90 天。

现在不需要同事的 Apple 账号密码、付费会员、设备 UDID 或任何真实凭据。

## 连接和恢复边界

- 只有点击发送才创建模型请求，POST 没有自动重试；恢复只 GET 查询。
- `message_saved` 的正整数 `message_id` 及对应历史记录确认保存；`[DONE]`、`finish_reason`、EOF 不代表完成。
- `completed`、`interrupted`、`failed` 分开展示，不能将部分回答标为完成。
- 点击停止取消接收；iOS 进入后台也结束接收并保留待核对标记，不承诺锁屏后持续生成。
- 返回前台或重开 App 核对原会话，有限重查仍未确认时保留问题、预览并锁定再次发送。用户明确确认“恢复问题草稿”才解锁，不自动发送。
- 当前服务器生成依赖现有请求生命周期，没有新增独立后台任务或可重连生成接口。
- 确认匹配的是本次问题之后的相邻回答；其它轮次或同一问题多次出现时保守保留待核对。
- 生成中以约 80ms 节流更新当前纯文本预览，已保存历史按稳定消息 ID 渲染，不随 token 重新解析 Markdown；上滚阅读时不强制跟随。
- 所有网络请求限定 HTTPS，禁用重定向和普通 Cookie 缓存，不绕过证书校验。

## 真机验收清单

云端编译、离线 UI 截图和合成接口测试不代替下面的真实手机验收：

1. 验证码、登录、重启恢复账号、退出和换账号不串数据。
2. 中文键盘、长输入、横屏、深浅色、大字体、安全区。
3. 第一次发送才创建会话；标题搜索、重命名、置顶和删除。
4. 模型切换、思考档位、联网开关，确认与网页同会话同步。
5. 长回答滚动、上滚不抢位置、复制、代码块与宽表格。
6. 停止、断网、切后台、锁屏、强制关闭，再回到原会话核对保存；不能自动重发。

## 本地命令与资料

```sh
swift test --package-path mobile/ios
bash mobile/ios/scripts/generate-project.sh
open mobile/ios/Meimei.xcodeproj
```

完整 XCTest 与 iOS 编译需要 Xcode；只有 Command Line Tools 的机器可编译核心库，但可能缺少 XCTest 和模拟器。云端已经提供完整工具链，本机无需为云端构建安装这些工具。

接口契约见 `API_MAPPING.md`。独立版本和更新记录在 `project.yml`、`CHANGELOG.md`，不抬升网页或 Android 版本。

参考：[免费账号限制](https://developer.apple.com/help/account/basics/about-your-developer-account)、[GitHub Apple 签名](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications)、[TestFlight](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/)。
