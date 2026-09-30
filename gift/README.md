# 槑槑送礼

独立模块 `/gifts`，复用平台账号会话、SQLite连接、本地 Tailwind/Lucide 与私有 OSS。版本独立于 AI槑槑和槑槑云。

## 初始化与隔离

`app.main()` 调用 `init_gift_db()`，仅创建 gift_ 表及索引，播种从附件提取的560条公开分类路径，不导入私人购买标记、尺码或图片。使用现有 SQLite WAL。不存在对旧表的修改。每个 service 必须显式传入鉴权所得 user_id；对象和图片的关联均检查同账号所有权。修改请求需要 `X-Gift-Request: 1`、JSON，以及同源检查。

金额底层为整数分，接口以元表示；空金额不等于零元。日期可精确到日、仅月份或未知，未知日期不自动归入本月。预算按收礼对象默认值展示。年龄不存实际年龄；生日缺失时保存估算月龄及记录日期。成长变化自动留档。

## 接口

- GET/POST `/api/gifts/recipients`，PATCH `/recipients/:id`，GET `/recipients/:id/history`
- GET/POST `/api/gifts/categories`（新增参数 paths 为1—3级路径列表）
- GET/POST `/api/gifts/items`，PATCH/DELETE `/items/:id`，POST `/items/batch`
- GET `/api/gifts/dashboard`、`/duplicates`、`/recommendations`（recipient_id 参数）
- POST `/api/gifts/assets`（filename、purpose、base64），GET `/assets/:id/view`
- POST `/api/gifts/ai/recognize`（asset_id，可选 model_id），GET `/ai/tasks`
- POST `/api/gifts/imports/preview`（recipient_id、xlsx base64），POST `/imports/:id/confirm`，GET `/imports`

商品创建校验与事务在 `services.create_item`，供HTTP、导入及后续 Agent 共用。批量保存携带 request_key，相同标识和内容重复提交返回原结果，变化内容返回409。所有选中商品在一个短事务中保存。

## 截图录入

读取现有 `ocr_config`（OCR_* 环境变量 / secrets.ocr / CAT_OSS AK回退）。调用阿里云 `RecognizeGeneral`，再使用已启用的视觉模型处理图片及带坐标的OCR参考，优先阿里云模型。模型只能返回草稿，分类校验对照现有分类路径。不执行图片/OCR中的指令，不从订单号推算日期，不将包装规格、限购数量当作购买数量，不分摊订单优惠。保留订单合计及完整性标识用于核对。

识别任务的token用量单独记录在 `usage_json`，不写会话/messages，不改变现有对话Token统计口径。每账号每日最多50次识别，同时最多2个识别调用；所有外部调用均在SQLite写事务之外。OCR失败时视觉模型仍可生成草稿并显式提示核对。失败任务保留可查询。

图片10MB上限、账号已登记图片500MB上限；OSS share/gifts/独立子前缀（沿用现有私有对象权限范围）、私有ACL及匿名可读检查，禁止注册任意外部URL。上传接口以base64传输小图片；不使用槑槑云的分享表或公开URL。当前版本不自动裁切商品缩略图；保存原始截图并可点击查看。截图、购物车勾选和识别结果均需用户确认实际购买后才写入商品。

## 旧Excel导入

兼容附件格式“已购总表＋已购明细”，解析ZIP/XML和 WPS DISPIMG/cellimages.xml关系，不依赖WPS或Excel安装。xlsx限制8MB、解压总计40MB/2000成员，拒绝XML实体定义。图片在预览阶段保存到私有OSS；确认前不写分类购买记录。文件摘要＋账号＋对象防重复导入。分类按完整路径复用系统节点，新增路径归当前账号。

45个月份标记保存在 gift_purchase_marks，参与重复提醒与规则推荐，不计入商品数量或金额。13张截图保留原月份和来源单元格；历史页可逐张识别整理。顶部尺码备注展示给用户，不覆盖现有档案。分类源包含孕产内容，儿童规则推荐排除孕产大类，推荐仅表示分类覆盖方向。

## 发布和验证

需增加代理 `/gifts` 页面路由；API和资源复用现有 `/api/`、`/res/`。后端与既有产品同进程，发布涉及短暂重启。上线前备份变更代码、代理配置和SQLite，核对压缩包清单与checksum。回退代码不覆盖数据库，新表保留。

本地临时数据库和浏览器检查覆盖账号隔离、金额日期边界、重复提示、原子批量保存/幂等、搜索、成长记录、旧表解析，以及PC/移动端布局、匿名401和写入来源403。外部模型真实调用与用户浏览器真实上传验收必须单独报告，不能用本地检查替代。

## 本次验收证据

虚构订单真实调用：阿里云 RecognizeGeneral 返回19个文字块约0.6秒；现有 qwen3.7-plus 提取3件商品，单价27.50、33.30、20.00，数量1、1、2，合计100.80与订单总价一致（约47秒）。私有OSS上传、匿名拒绝访问、签名URL OCR读取及share/gifts测试对象删除验证通过。用户随后明确授权真实截图测试：订单图识别5件，完整订单合计114.10；拼图15件，区分10个勾选/5个未勾选，灭蚊灯数量2。模型分类仍需用户核对。

现有模块回归在服务器临时目录使用已有依赖、模拟OSS和临时SQLite运行：分享登录/权限隔离、分片上传、额度边界、并发计数、Office/PDF版本保存发布、备份脱敏、旧页面路由及私有存储检查通过。本机浏览器验证PC/390px移动布局、商品增改搜索、档案、规则推荐、识别草稿恢复/批量确认防重复和自定义分类通过。

用户已明确授权提交、推送及备份后部署。针对结构化字段抽取复用模型支持的快速模式，订单图约21秒、拼图约53秒完成；未修改现有模型配置。
