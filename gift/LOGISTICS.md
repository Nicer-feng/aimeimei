# 订单与物流接口约定

供应商：[阿里云市场物流详情查询 cmapi00072369](https://market.aliyun.com/detail/cmapi00072369)。
接口文档通过商品页“接口文档”获取；服务端固定调用 `GET https://logistics.market.alicloudapi.com/api/LogisticsDetail`。
鉴权头为 `Authorization: APPCODE <服务端凭证>`。只需 AppCode，不需要把 AppKey / AppSecret 发给浏览器。

Query 参数 `logistics_interface` 是 JSON 字符串：`{"arg0":{"cpCode":"SF","mailNo":"TEST00000001","receiverPhone":"1234","isTb":"N","appCode":"aliyun_public"}}`。
其中 `appCode: aliyun_public` 是供应商固定业务标记，不是用户购买的鉴权凭证。字段名、GET 方法和嵌套 JSON 响应均依官方示例实现。顺丰 SF 已真实验收；CN 为文档示例代码。其他公司代码依供应商支持范围填写，不把商城订单号当运单号。

## 本系统接口

所有业务接口复用当前账号及 `user_id` 隔离；写入使用 JSON 与 `X-Gift-Request: 1`，并沿用现有来源检查。金额保持原商品记录的元制 API / 分制存储。

| 方法 / 路径（前缀 `/api/gifts`） | 请求与结果 |
| --- | --- |
| GET `/orders?recipient_id=...&month=YYYY-MM&item_id=...` | month、item_id 可选。返回 `orders`、`has_more`；订单包含 items、shipments、已知 amount/units/unknown_amount。最多100笔，超出时用月份筛选。 |
| GET `/orders/candidates?recipient_id=...&month=YYYY-MM` | 当前月份及无日期商品，带 linked_order_id。最多200条；历史单件入口补充目标商品。 |
| POST `/orders` | recipient_id、purchase_month、title 必填；order_number、source、notes、item_ids 可选。返回 `{order}`，201。 |
| GET / PATCH / DELETE `/orders/:id` | 读取 / 修改 / 删除订单。PATCH item_ids 若省略保留关联，空数组表示解除全部关联。删除不删除商品和图片。 |
| POST `/orders/:id/shipments` | carrier_code、tracking_number 必填；carrier_name、receiver_phone、sender_phone、sender_address、delivery_address、is_tb 可选。返回 `{shipment}`，201。 |
| PATCH / DELETE `/shipments/:id` | 修改或删除单个包裹；查询参数变化后清空旧缓存，防止将旧单轨迹展示给新运单。 |
| POST `/shipments/:id/refresh` | 空 JSON 即可。返回 `{shipment,cached}`。5分钟内复用缓存；30秒内未成功的重复尝试返回429。读取订单不自动调用供应商。 |

一个商品只能归属一笔订单。关联必须属于同一账号、收礼对象及月份，无日期商品可明确手动关联。订单金额从已关联商品汇总，不会改变花费统计口径。
包裹 `tracking` 包含 `state`、`state_label`、`events[{time,message,location}]`、`notice`。供应商 `result.data` 可为 JSON 字符串，标准化后按轨迹时间倒序展示。未知状态不会当成已签收。

错误：400 参数不正确；401 未登录；403 来源检查失败；404 不存在或无权访问；409 关联冲突/查询期间修改；422 供应商业务拒绝；429 查询过快/限流；502 上游不可用、鉴权失败或返回异常；503 未配置；504 上游超时。错误不会包含凭证或完整上游 URL；查询失败保留已缓存轨迹。外部请求不持有 SQLite 写事务。

## 服务端配置

优先环境变量 `GIFT_LOGISTICS_APPCODE`，否则读取运行数据目录下的 `gift-logistics.secret.json` 中 `appcode` 字段。该文件权限应为600，不进 Git、静态资源或发布包。修改配置后下一次查询即可读取，不需要重启。`GIFT_LOGISTICS_ENDPOINT` 仅用于运维/本地模拟覆盖；允许 HTTPS 或本机回环 HTTP，不接受客户端传入端点。禁止携带鉴权跟随重定向。

## 可复用本地供应商模拟

Postman CLI 1.70+：

```sh
postman simulation run gift/testing/logistics.sim.yaml --port 4900 --no-history --output ndjson
```

将待测应用的 `GIFT_LOGISTICS_ENDPOINT` 设置为 `http://127.0.0.1:4900/provider/api/LogisticsDetail`、`GIFT_LOGISTICS_APPCODE` 设置为 `synthetic-test-code`，使用临时数据库和虚构运单。模拟基于公开契约，不涉及真实快递或凭证，不需要发布云工作区。
这是供应商响应模拟，必须运行真实本应用客户端，不能把本应用本身当作模拟成员。验收时同时检查 simulation 输出中的 request 事件。生产凭证和私人轨迹不得写入模拟文件或日志。
