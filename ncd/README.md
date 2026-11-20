# 题库速查

入口 `/ncd/`，与主站账号独立。原生 HTML/CSS/JS 和 Python 标准库实现，无模型调用和新运行依赖。

## 数据来源

`questions.json` 由 `2026星级收费员单选多选复习题1102(更新版).xlsx` 导入。只使用当前可见的 `2026单选` 和 `2026多选`，分别为 1,597 和 963 条原始记录；不混入隐藏的旧版、地区表或尾随空格旧表。

完整相同记录可合并来源，同题干但选项不同的记录保留。答案使用原表的字母和对应内容，不推测补齐。单选原表第 1345 行声明 4 个选项，但实际只有 A/B，保留原始已有选项，导入诊断记录此差异。

导入器使用标准库，具体命令见 `python3 -m ncd.import_questions --help`。更新后运行 `python3 -m unittest ncd.test_bank` 与接口测试，核对诊断及版本。

导入时读取 `styles.xml` 和工作簿日期基准，按原表格式转换数值。中文内置格式 31/57/58 分别显示完整日期、年月、月日；百分比保留原有小数位。只根据单元格格式转换，不能把普通五位重量数字猜成日期，也不能把普通小数猜成百分比。未知非空数字格式、无缓存公式和公式错误会中止导入并指出位置，避免再次把底层数值误当显示文本。

2026-11-20 全量核对发现并修复 65 个日期选项、118 个百分比选项，涉及 48 题及 46 条答案文本。其余字段与原始题库逐项核对，没有发现额外格式丢失。原表还存在 5 题选项文字重复（单选原表行 943/1474/1486，多选原表行 250/800）；单选第 948 行含“9月31日”“6月31日”等可能有意设置的错误日期选项，均按原文保留，不擅改题意或标准答案。

## 口令和会话

运行目录默认是 `$AI_PLATFORM_DATA/ncd-data`（主站默认 `/opt/ai-platform/ncd-data`），可通过 `NCD_DATA_DIR` 指定。支持 1 至 10 个统一访问密码，口令配置只保存 PBKDF2 哈希至 `secrets.json`，会话存放于 `sessions.db`；均不进入 Git 或公开静态目录。

```sh
python3 -m ncd.configure --data-dir /受保护的运行目录/ncd-data --count 3
```

命令按数量分别隐藏输入密码，并替换全部现有密码；`--count` 默认值为 2，设置三个密码时须明确传入 `--count 3`。修改口令配置后旧会话自动失效。生产目录应仅允许服务用户读写。登录有效期为 12 小时；同一来源地址 15 分钟内最多连续尝试 10 次。Cookie 为 `ncd_session`，限定 `/ncd/`，设置 HttpOnly、SameSite=Lax；线上域名同时设置 Secure。

## 接口

| 接口 | 请求 | 结果 |
| --- | --- | --- |
| `GET /ncd/` | 独立会话 Cookie | 未登录显示密码页，已登录显示搜索页 |
| `POST /ncd/api/login` | JSON `{"password":"本地填写"}` | 成功 200 `{"ok":true}` 并设置 Cookie；错误密码 401，限流 429 |
| `GET /ncd/api/search?q=片段&page=1` | 必须已登录；q 最长 1000 字，page 为正整数 | `query,total,page,page_size,has_more,items`，每页 20 条 |
| `POST /ncd/api/logout` | 独立会话 Cookie | 删除服务端会话并清除 Cookie |

每题返回 `id,type,category,question,options,answer,answer_text,sources`；`type` 为 `single` 或 `multiple`，`options` 为 `{key,text}` 列表，`answer` 和 `answer_text` 为数组，`sources` 包含原工作表、行号和题号。

精确题干、片段和多关键词优先；只有没有直接命中时才返回满足阈值的相似题。相似检索不用于推断答案。同题干的不同选项并列，粘贴选项可辅助排序。前端输入或粘贴后 300 毫秒查询，中文输入法组合期间不查询，旧查询响应不能覆盖新题目。

## 验证与发布

```sh
python3 scripts/test_ncd.py
python3 -m unittest ncd.test_bank
node ncd/tests/test_ui.js
```

测试使用虚构口令、临时数据库和本机 HTTP 服务，不读取实际运行凭证。前端测试需要本机已有 Playwright/Chrome，生产无此依赖。

按 `REPOSITORY.md` 清单发布，仅上传 `app.py`、`ncd/` 的运行文件及 Caddy 路由变更。题库和配置不能复制到 `/var/www/aimeimei` 或 `/res/`。备份旧入口与代理配置后验证 Caddy、编译 Python，再重启共享服务并检查主站、AI、小猫书、分享及题库。根目录 AI 产品版本不随本模块变更。
