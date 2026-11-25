# 机房与联网设备台账

独立的中文台账应用，使用 Python 3.9+ 标准库、SQLite 和浏览器原生前端。随项目提供的青岚站和松泉站是演示站点，站内设备、地址和 PDF 均为模拟数据。实际导入的设备归入独立单位和站点，按账号权限显示。

## 访问服务器

公网 HTTPS 入口为 [机房与联网设备台账登录页](https://feng.asia/sroom/)。使用已开通机房权限的 AI 槑槑账号登录。AI 槑槑管理员可在「账号管理」的「机房权限」中开通、调整或撤销授权。现有槑槑 `admin` 和 `feng` 开通全站管理。台账、档案和录入操作都校验当前会话及机房授权。应用端口监听服务器的 `127.0.0.1:18761`。

使用默认回环配置时，在本机终端建立 SSH 转发并保持终端开启。

```bash
ssh -o ExitOnForwardFailure=yes -N -L 127.0.0.1:18761:127.0.0.1:18761 aliyun_3129
```

打开 [本机转发入口](http://127.0.0.1:18761/)。结束转发时在本机终端按 `Ctrl+C`。

以下账号仅用于运行未启用 `--ai-sso` 的本机演示环境。

| 账号 | 权限 |
| --- | --- |
| `admin` | 查看全站范围，编辑机房布局，登记和编辑设备、业务系统和项目，添加档案 |
| `region-reader` | 查看演示东区所辖的青岚站，包括授权范围内的设备和档案 |

两个账号的密码由安装者单独设置，长度为 12 至 256 个字符。

## 服务管理

以下命令在服务器上执行。

```bash
sudo systemctl start asset-ledger.service
sudo systemctl stop asset-ledger.service
sudo systemctl status asset-ledger.service
sudo journalctl -u asset-ledger.service -n 100 --no-pager
```

在本机演示环境的项目目录运行对应命令，按提示输入新密码。

```bash
python3 -m ledger passwd --data-dir ./data admin
python3 -m ledger passwd --data-dir ./data region-reader
```

## 首次部署和本机运行

在项目根目录打包，通过现有 SSH 连接上传。服务安装在 `/opt/asset-ledger`，SQLite 状态独立保存在 `/var/lib/asset-ledger`。

```bash
package_dir=$(mktemp -d)
COPYFILE_DISABLE=1 tar --exclude='__pycache__' --exclude='.DS_Store' --exclude='._*' \
  -czf "$package_dir/asset-ledger.tar.gz" ledger static samples/*.pdf deploy README.md
scp "$package_dir/asset-ledger.tar.gz" aliyun_3129:asset-ledger.tar.gz
```

在服务器上解包和安装，再以服务账号初始化并设置密码。

```bash
stage_dir=$(mktemp -d)
tar -xzf ~/asset-ledger.tar.gz -C "$stage_dir"
cd "$stage_dir"
sudo bash deploy/install.sh
cd /opt/asset-ledger
sudo -u asset-ledger /usr/bin/python3 -m ledger init --data-dir /var/lib/asset-ledger
sudo -u asset-ledger /usr/bin/python3 -m ledger passwd --data-dir /var/lib/asset-ledger admin
sudo -u asset-ledger /usr/bin/python3 -m ledger passwd --data-dir /var/lib/asset-ledger region-reader
sudo systemctl enable --now asset-ledger.service
```

更新运行文件时，先停止 `asset-ledger.service`，再解包、执行 `deploy/install.sh` 并启动该服务。安装脚本只写专用应用目录、专用服务单元和状态目录的权限。已有 SQLite 数据会保留。备份时停止台账服务并备份 `/var/lib/asset-ledger`。

也可以直接在本机的项目根目录运行。

```bash
python3 -m ledger init --data-dir ./data
python3 -m ledger passwd --data-dir ./data admin
python3 -m ledger passwd --data-dir ./data region-reader
python3 -m ledger serve --data-dir ./data --port 18761
```

### 启用 HTTPS 入口

默认服务单元使用回环访问。安装覆盖文件后，公网入口使用 AI 槑槑统一登录。AI 槑槑服务需在 `127.0.0.1:8000` 提供机房授权查询，并通过同一 HTTPS 域名提供验证码、登录和退出接口。将 [Caddy 路由片段](deploy/caddy-route.caddy) 加入 `feng.asia, www.feng.asia` 站点块。

在 AI 槑槑服务的 `AI_PLATFORM_SROOM_SCOPES` 环境变量中设置可选辖区的 JSON 对照表，例如 `{"2":"演示东区"}`。JSON 键对应台账数据库的 `units.id`，值是账号管理中显示的名称。部署后在 AI 槑槑后台给需要访问的账号开通机房权限。

```bash
sudo install -d -m 0755 /etc/systemd/system/asset-ledger.service.d
sudo install -m 0644 deploy/public.conf.example /etc/systemd/system/asset-ledger.service.d/public.conf
sudo systemctl daemon-reload
sudo systemctl restart asset-ledger.service
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy.service
```

Caddy 将 `feng.asia` 下以 `/sroom/` 开头的请求路径和原始 `Host` 转发到 `127.0.0.1:18761`。代理设置 `X-Forwarded-Proto` 为 `https`，并以 `{http.request.remote.host}` 覆盖 `X-Ledger-Client-IP`。`/sroom`、旧 `/asset-ledger/` 路径和 `www.feng.asia` 的对应入口跳转到 `feng.asia` 下的新地址。

## 功能和手动验收

### 机房总览

从首页登录后进入权限范围内的 3D 机房总览，优先打开已摆放机柜的实际机房。管理员当前默认进入南昌东中心机房的单排九柜总览。可按单位、站点和机房切换，也可通过书签直接打开指定机房或单柜。总览提供 3D 斜俯视、正俯视和可点击的 2D 平面图。青岚站综合机房的示意布局为两排各五个柜位，包含九台示例柜和一个预留位。点任一机柜进入单柜视图，返回机房总览可继续使用原机房和视角。

3D 总览使用单柜的机架和设备模型。设备按台账中的安装面、起始 U 位、占用高度和深度摆放。拉近镜头时，网口、盘位等细节会出现在画面中的近处机柜上。

管理员可以指定房间的排数、每排柜位数、每个柜的排序和正面朝向。未登记位置的柜在「待摆放」中列出，也能打开单柜视图。行和柜位表示相对位置，起始方向以总览图为准。一次保存整间机房的布局，可以直接交换两个柜的位置。

验收时确认 3D 和 2D 中点同一柜号会打开相同单柜、机房无布局时能从「待摆放」进入机柜、重复柜位会阻止保存，辖区只读账号仅能查看授权范围内的布局。

### 台账与单柜

「运行状态」由管理员手动登记，可选待核实、运行中、已停用和未通电。已有记录和未指定状态的新设备默认为待核实。设备列表、详情与 3D 悬停提示显示状态文字。只有运行中的设备显示绿灯，整间机房远景低亮常亮，放大后和单柜近景缓慢呼吸。

1. 用 `admin` 登录，在机房总览选青岚站综合机房，点击 A01。正面 `U4-U5` 显示为连续两格的综合应用服务器，背面 `U1` 为配电单元。点服务器打开侧栏，再进入详情，核对两个业务系统、服务入口、采购合同与验收 PDF。验收报告第 2 页有设备核对表。
2. 打开业务系统页的「站点业务管理系统」，查看两站的设备、机柜编号和 U 位。可从部署记录查看同一部署下的网页与数据库入口。
3. 打开「青岚站机房基础设施更新」，核对采购设备及四份项目级档案。从任一采购设备进入项目，均引用同一份项目档案。综合应用服务器还有独立的设备交接 PDF。
4. 新增设备或把 A01 服务器移动到空的两个连续 U 位，保存后核对立面。尝试让设备占据正面已使用的 U 位、跨越柜高或设置无效 U 位，保存应被拒绝。登记打印机等非上架设备时，选择机房并填写工位。
5. 在设备台账里搜索编号、设备名称或系统名，再用单位、机房和机柜筛选。核对用途待查、责任人未确认和购置价格未单列等样例状态。
6. 在 2D 和 3D 分别点同一台设备，核对侧栏的设备编号及「打开设备详情」的链接是否指向同一个设备 ID。WebGL 不可用时可继续使用 2D 立面。
7. 用 `admin` 分别复制一份青岚站和松泉站 PDF 的预览或下载地址。在无痕窗口直接打开应被拒绝。在本机用演示账号 `region-reader` 登录，或在公网用仅开通演示东区只读的 AI 槑槑账号登录。青岚档案可读，松泉档案以及新增、编辑请求均应被后端拒绝。

附件由登录后接口按辖区鉴权并按内容去重存入 SQLite。管理员可为项目和设备添加 PDF、JPG/JPEG、PNG、GIF、WebP、DOC/DOCX 和 XLS/XLSX，单个原件最多 8 MiB。图片和 PDF 可在台账内预览，Word 和 Excel 可下载原件。填写 PDF 的参考页码后，预览从对应页开始，可向上或向下连续滚动。备注对各格式均可选。

### 机柜深度占位验收

使用空的 12U 测试柜，设备深度由录入人员明确选择。原有记录的深度初始为「深度待核」，核实后可在设备编辑中更新。

| 操作 | 通过条件 |
| --- | --- |
| 将一台全深 2U 服务器装在正面 U8–U9。尝试在背面 U9 增加一台半深 1U 设备 | 服务端拒绝保存，提示全深服务器占用背面 U9。2D 的背面 U8–U9 显示为已占用，3D 只显示一台贯穿柜深的服务器。 |
| 在背面 U10 安装半深 1U 设备 | 可以保存。 |
| 在同一柜的正面和背面 U5 各安装一台半深 1U 设备 | 两条都能保存，2D 和 3D 分别点前后的设备时，各自打开对应的设备 ID。 |
| 在已有半深设备的同面 U5 再装一台，或将 U5 的任意一台改为全深 | 服务端拒绝保存，已有两条设备记录保留原位置和深度。 |

在项目根目录运行 `python3 -B -m unittest discover -s tests -v` 可复跑后端占位检查。

## 3D 依赖

2D 立面由本项目的 SVG 渲染。3D 本地内置 [Three.js r180 及其 MIT 许可证](https://github.com/mrdoob/three.js/blob/r180/LICENSE)，包括 Three.js 模块及 OrbitControls。OrbitControls 的模块导入改为本地相对路径。两种视图读取同一份机柜设备数据，点击回到同一个详情侧栏。

[net3d 的机柜视图](https://github.com/hervehildenbrand/net3d/blob/main/packages/web/src/scene/RackLevel.tsx) 可以用本台账提供的机柜数据驱动。原组件依赖 React、React Three Fiber、Drei 和项目内的状态及场景组件，拆用时需要独立前端入口和数据适配。对于当前原生 Three.js 视图，更适合参考 [U 位与深度变换](https://github.com/hervehildenbrand/net3d/blob/main/packages/shared/src/devices.ts) 和设备拾取，继续用台账设备 ID 打开详情。 [net3d MIT 许可证](https://github.com/hervehildenbrand/net3d/blob/main/LICENSE)
