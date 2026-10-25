# AI槑槑 iOS 原生客户端

独立版本 **0.2.0**，SwiftUI，最低 **iOS 17.0**，当前面向 iPhone。
代码与 Android 共仓，使用 `mobile/ios/` 和独立 iOS 工作流，不修改 Android、网页、后端、数据库或生产部署。

## 首版范围

- 用户名、密码和原生图形验证码登录，或使用已绑定并启用的手机号短信登录；支持验证码自动填充、服务端重发倒计时与过期校验。Keychain 保存服务端 `ap_session`，不保存密码和短信验证码。
- 正常冷启动展示新聊天，点击新聊天不创建空会话；第一次发送时才创建。
- 历史列表、标题搜索、切换、重命名、置顶、确认删除。
- 资料库：收藏回答、取消收藏、查看快照和返回原对话；与 Web 使用同一收藏数据。
- 全文搜索会话标题、历史消息及收藏，打开结果定位并标记消息；原会话已删除的收藏可继续查看。
- 读取 Web 提示词库，预览后填入当前草稿；覆盖草稿需确认，不自动发送，不在客户端编辑公共模板。
- 原有聊天接口的 SSE 流式回答、思考展示、停止接收、模型切换、能力控制的思考档位和联网开关。
- 常用 Markdown 标题、段落、列表、引用、代码块及横向滚动表格，复制、分享；不执行 HTML。
- 草稿按账号和会话隔离，写入应用私有且排除备份的目录；登录 Cookie 使用本机不可迁移钥匙串。
- 跟随系统、浅色、深色，系统字体、键盘安全区及横屏适配。

当前支持图片上传、拍照提问、历史图片预览、联网来源查看、文件问答和回答朗读。暂未纳入：原生办公文档预览、推送、网页工具、Mermaid、完整嵌套 Markdown 兼容；历史文档附件显示文件名。

服务器为固定 `https://feng.asia/`，复用现有账号和云端历史。普通用户 API 不需要管理员密钥或模型 API Key。
联网开关沿用服务器现有搜索策略，关闭不等于禁止服务器已配置的自动搜索。

## 先用 GitHub 云端构建，不需要本机 Xcode 或开发者账号

进入仓库 **Actions → iOS 原生客户端 → Run workflow**，选择包含本工程的分支。
默认分支尚未包含工作流时，可先查看 iOS PR 对应的运行记录。
只修改 `mobile/ios/**` 或 iOS workflow 才会触发 iOS 构建；与 Android 使用不同并发组，互不取消。

构建机为 GitHub 标准 **macos-15 + Xcode 26.3**，部署目标仍是 iOS 17。
固定 XcodeGen **2.46.0**，下载后核对 SHA-256。工程由 `project.yml` 生成，不手工维护 pbxproj。
这条未签名流水线不使用任何 Apple/GitHub Secrets，不上传 TestFlight、不创建公开 Release、不访问生产服务器。

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

## TestFlight 签名和上传

另有工作流 **iOS TestFlight**，允许从 main 手动运行，或推送 `ios/testflight/*` 专用发行标签。发行提交必须已合入 main。先复用上述测试，再校验 Team、包名、描述文件类型和有效期、证书私钥匹配关系，导出正式签名 IPA；手动勾选上传或推送发行标签后传到 App Store Connect。
兼容个人和团队 API Key，不使用 Apple 账号密码或验证码。不会随普通代码 push 自动发布，不自动提交外部测试审核或邀请测试者。

配置所需 Secrets、在 Mac 复制文件内容、运行及审核步骤见 **[TestFlight 配置指南](TESTFLIGHT.md)**。

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

1. 验证码、登录、重启恢复账号、退出和换账号不串数据；退出清空收藏、提示词和搜索结果。
2. 中文键盘、长输入、横屏、深浅色、大字体、安全区。
3. 第一次发送才创建会话；标题搜索、重命名、置顶和删除。
4. 模型切换、思考档位、联网开关，确认与网页同会话同步。
5. 长回答滚动、上滚不抢位置、复制、代码块与宽表格。
6. 停止、断网、切后台、锁屏、强制关闭，再回到原会话核对保存；不能自动重发。
7. 收藏与 Web 同步、取消收藏、已删除会话的收藏快照；搜索正文和收藏、快速改词、定位原消息。
8. 提示词预览、已有草稿确认替换或取消、填入后编辑及手动发送。

## 本地命令与资料

```sh
swift test --package-path mobile/ios
bash mobile/ios/scripts/generate-project.sh
open mobile/ios/Meimei.xcodeproj
```

完整 XCTest 与 iOS 编译需要 Xcode；只有 Command Line Tools 的机器可编译核心库，但可能缺少 XCTest 和模拟器。云端已经提供完整工具链，本机无需为云端构建安装这些工具。

接口契约见 `API_MAPPING.md`。独立版本和更新记录在 `project.yml`、`CHANGELOG.md`，不抬升网页或 Android 版本。

参考：[免费账号限制](https://developer.apple.com/help/account/basics/about-your-developer-account)、[GitHub Apple 签名](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications)、[TestFlight](https://developer.apple.com/help/app-store-connect/test-a-beta-version/testflight-overview/)。

### 0.3.0 图片与来源验收

选择支持图片的模型，通过输入区“图片”选择相册照片或拍照。检查上传进度、移除、失败后手动重试，以及不输入文字直接发送图片。点击缩略图可预览并放大；切换不支持图片的模型后应阻止带图发送。退出重进会话后，应能读取服务器保存的图片。

打开联网搜索后发送问题，回答存在来源时点击“联网来源”，核对标题、摘要并打开原文；没有来源的回答不显示入口。相册、相机权限及真实 OSS/模型链路需要在真机验收；离线 UI 测试使用 Debug 数据，不调用收费模型。

### 0.4.0 文件问答与回答朗读验收

输入区“文件”可从系统文件选择最多 5 份材料，也可复用 Web 已上传的材料。单份最多 50MB，图片材料最多 20MB。上传后解析中不能发送，前台最多自动查询约一分钟，可手动刷新；查询失败保留材料，解析终态失败可移除并重新上传。材料仅绑定本条问题；移除不删除 Web 文件，不开启持续引用。支持不输入文字直接发送文件，断线核对同时校验材料 ID。文件数据仅在读取/上传及显式重试期间保留内存，不写入聊天草稿文件。

回答右上角的扬声器打开朗读设置，读取后台开关、音色与默认语速，点击播放才请求语音。长文本无缓存时先确认，取消不请求音频。暂停/继续使用已加载音频；修改音色或语速会停止，需要重新点击播放。关闭朗读页、切换会话、退出账号或进入后台停止播放。耳机断开和音频中断会暂停，不自动恢复。

云端离线测试使用合成材料与模拟音频输出，验证接口、状态与界面，不调用真实解析/语音服务。真实 Files/iCloud 文件选择、文档解析供应商和真机音频路由仍需手机验收；无需增加 GitHub Secrets 或在本机安装 Xcode。

0.5.0 新增 AI 档案编辑、会话加载开关和限时对话分享，沿用现有后端；分享范围和撤销与 Web 一致。

0.6.0 新增手写识别；0.7.0 新增写稿版本与定稿管理、音视频分析。均使用现有账号与服务端接口，真实文件/iCloud、OCR/听悟服务和手机权限仍需 TestFlight 验证。
