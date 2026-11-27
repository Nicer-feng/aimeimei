"""样例数据只使用虚构站点、文档和保留地址。"""

import hashlib


def seed_physical_port_demo(conn):
    if conn.execute("SELECT 1 FROM metadata WHERE key = 'samples' AND value = '1'").fetchone() is None:
        return
    key = "qinglan-physical-ports-v1"
    if conn.execute("SELECT 1 FROM metadata WHERE key = ?", (key,)).fetchone():
        return
    records = {
        row["code"]: row["id"] for row in conn.execute(
            """SELECT d.id, d.code FROM devices d
               JOIN rooms r ON r.id = d.room_id JOIN sites s ON s.id = r.site_id JOIN units u ON u.id = s.unit_id
               JOIN racks rack ON rack.id = d.rack_id AND rack.room_id = r.id
               WHERE u.name = '演示东区' AND s.name = '青岚站' AND r.name = '综合机房' AND d.archived_at IS NULL
                 AND ((d.code = 'QL-SW-001' AND d.serial = 'DEMO-QL-002' AND rack.name = 'A01')
                   OR (d.code = 'QL-NET-001' AND d.serial = 'DEMO-QL-005' AND rack.name = 'A02'))"""
        )
    }
    if len(records) != 2:
        return
    source, peer = records["QL-SW-001"], records["QL-NET-001"]
    conn.execute("INSERT INTO metadata(key, value) VALUES (?, '1')", (key,))
    if conn.execute("SELECT 1 FROM physical_ports WHERE device_id IN (?, ?) LIMIT 1", (source, peer)).fetchone():
        # 已手工录入端口的样例也保留原样。
        return

    def demo_port(device, name, kind, group, position, state="unknown"):
        return conn.execute(
            """INSERT INTO physical_ports(device_id, name, kind, port_group, position, base_state, is_demo)
               VALUES (?, ?, ?, ?, ?, ?, 1)""", (device, name, kind, group, position, state),
        ).lastrowid

    for position in range(1, 25):
        fiber = position >= 23
        kind = "fiber" if fiber else "copper"
        name = f"{'SFP' if fiber else 'GE'}1/0/{position:02d}"
        state = "free" if 17 <= position <= 21 or position == 24 else "unknown"
        port = demo_port(source, name, kind, "成员 1", position, state)
        linked = position <= 10 or position == 23
        if not linked and not 11 <= position <= 16:
            continue
        prefix = "F" if fiber else "C"
        label = f"演示-QL-{prefix}{position:02d}"
        pending = "" if linked else f"演示-A03-旧标签-{position:02d}"
        cable = conn.execute(
            """INSERT INTO physical_cables(pending_peer_label, note, verified_on) VALUES (?, ?, ?)""",
            (pending, "演示数据 · 跨柜跳线" if linked else "演示数据 · 按现场标签记录，待核对端",
             "2026-11-18" if linked else None),
        ).lastrowid
        ends = [(port, cable, 0, f"{label}-A")]
        if linked:
            peer_position = 11 if fiber else position
            peer_name = f"{'SFP' if fiber else 'GE'}0/{peer_position}"
            far = demo_port(peer, peer_name, kind, "成员 1", peer_position)
            ends.append((far, cable, 1, f"{label}-B"))
        conn.executemany("INSERT INTO physical_cable_ends(port_id, cable_id, side, label) VALUES (?, ?, ?, ?)", ends)
    demo_port(peer, "SFP0/12", "fiber", "成员 1", 12, "free")


def seed(conn, directory):
    conn.executemany(
        "INSERT INTO units VALUES (?, ?, ?)",
        [(1, "演示集团", None), (2, "演示东区", 1), (3, "演示西区", 1)],
    )
    conn.executemany(
        "INSERT INTO sites VALUES (?, ?, ?)",
        [(1, 2, "青岚站"), (2, 3, "松泉站")],
    )
    conn.executemany(
        "INSERT INTO rooms VALUES (?, ?, ?)",
        [(1, 1, "综合机房"), (2, 2, "通信机房")],
    )
    conn.executemany(
        "INSERT INTO racks VALUES (?, ?, ?, ?)",
        [(1, 1, "A01", 12), (2, 2, "B01", 12)] + [
            (index + 1, 1, f"A{index:02d}", 42 if index in (2, 3, 4) else 24)
            for index in range(2, 10)
        ],
    )
    conn.executemany(
        """INSERT INTO devices (
            id, code, name, type, model, serial, room_id, rack_id, face, u_start, u_height,
            workstation, purpose, ownership, reporter, maintainer, verified_on, purchased_on, price
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )""",
        [
            (1, "QL-SRV-001", "综合应用服务器", "服务器", "示例 SR-2U", "DEMO-QL-001",
             1, 1, "front", 4, 2, "", "承载站点应用服务", "青岚站", "演示填报员甲",
             "演示维护组甲", "2026-11-18", "2026-09-16", None),
            (2, "QL-SW-001", "汇聚交换机", "交换机", "示例 SW-24", "DEMO-QL-002",
             1, 1, "front", 10, 1, "", "机房有线网络汇聚", "青岚站", "演示填报员甲",
             "演示维护组甲", "2026-11-18", "2026-09-16", None),
            (3, "QL-PDU-001", "机柜配电单元", "配电设备", "示例 PDU-8", "DEMO-QL-003",
             1, 1, "rear", 1, 1, "", "用途待查", "青岚站", "演示填报员甲",
             "责任人未确认", None, None, None),
            (4, "QL-PRN-001", "机房标签打印机", "打印机", "示例 LP-20", "DEMO-QL-004",
             1, None, None, None, None, "值班台 02", "机柜标签打印", "青岚站", "演示填报员乙",
             "责任人未确认", "2026-11-17", None, None),
            (5, "SQ-SRV-001", "松泉应用服务器", "服务器", "示例 SR-2U", "DEMO-SQ-001",
             2, 2, "front", 6, 2, "", "承载站点应用副本", "松泉站", "演示填报员丙",
             "演示维护组乙", "2026-11-15", None, None),
            (6, "QL-NET-001", "网络接入设备", "网络设备", "示例 NW-12", "DEMO-QL-005",
             1, 3, "front", 39, 1, "", "有线终端接入", "青岚站", "演示填报员甲",
             "演示维护组甲", "2026-11-18", None, None),
            (7, "QL-STO-001", "数据存储设备", "存储设备", "示例 ST-4U", "DEMO-QL-006",
             1, 3, "front", 21, 4, "", "保存离线备份", "青岚站", "演示填报员乙",
             "演示维护组甲", "2026-11-18", None, None),
            (8, "QL-PDU-002", "配电设备乙", "配电设备", "示例 PDU-6", "DEMO-QL-007",
             1, 3, "rear", 1, 2, "", "机柜配电", "青岚站", "演示填报员甲",
             "演示维护组甲", "2026-11-17", None, None),
            (9, "QL-SRV-002", "备用计算设备", "服务器", "示例 SR-2U", "DEMO-QL-008",
             1, 4, "front", 30, 2, "", "用途待查", "青岚站", "演示填报员乙",
             "责任人未确认", None, None, None),
            (10, "QL-NET-002", "备用接入交换机", "交换机", "示例 SW-16", "DEMO-QL-009",
             1, 7, "front", 13, 1, "", "备用有线接入", "青岚站", "演示填报员甲",
             "责任人未确认", None, None, None),
        ],
    )
    conn.executemany(
        "INSERT INTO systems VALUES (?, ?, ?)",
        [
            (1, "站点业务管理系统", "用于登记站点业务。"),
            (2, "资料归档系统", "在青岚站登记应用入口与数据库入口。"),
        ],
    )
    conn.executemany(
        "INSERT INTO deployments VALUES (?, ?, ?, ?)",
        [(1, 1, 1, "青岚站实例"), (2, 1, 5, "松泉站实例"), (3, 2, 1, "资料归档实例")],
    )
    conn.executemany(
        "INSERT INTO service_entries(id, deployment_id, host, protocol, port, purpose, url) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (1, 1, "portal.ql.example", "HTTPS", 443, "业务门户", "https://portal.ql.example/"),
            (2, 1, "192.0.2.31", "PostgreSQL", 5432, "业务数据库", ""),
            (3, 2, "portal.sq.example", "HTTPS", 443, "松泉站业务门户", "https://portal.sq.example/"),
            (4, 3, "archive.ql.example", "HTTPS", 443, "档案查阅", "https://archive.ql.example/"),
            (5, 3, "198.51.100.17", "PostgreSQL", 5432, "归档数据库", ""),
        ],
    )
    conn.executemany(
        "INSERT INTO projects VALUES (?, ?, ?, ?, ?)",
        [
            (1, "青岚站机房基础设施更新", "QL-2026-01", "购置服务器、汇聚交换机及机柜配电单元。", 1),
            (2, "松泉站业务设备采购", "SQ-2026-01", "购置松泉站应用服务器。", 2),
        ],
    )
    conn.executemany("INSERT INTO project_devices VALUES (?, ?)", [(1, 1), (1, 2), (1, 3), (2, 5)])
    documents = [
        (1, "青岚站样例工程量清单", "工程量清单", 1, None, None, "共用清单。", "site-a-quantity.pdf"),
        (2, "青岚站样例施工设计图", "施工设计图", 1, None, 1, "机柜布置图。", "site-a-design.pdf"),
        (3, "青岚站样例采购合同", "合同", 1, None, None, "设备价格未单列。", "site-a-contract.pdf"),
        (4, "青岚站样例验收报告", "验收报告", 1, None, 2, "第 2 页为设备与资料核对记录。", "site-a-acceptance.pdf"),
        (5, "设备专属交接记录", "设备档案", None, 1, None, "设备专属记录。", "site-a-device.pdf"),
        (6, "松泉站样例验收报告", "验收报告", 2, None, None, "松泉站验收资料。", "site-b-acceptance.pdf"),
    ]
    for document in documents:
        content = (directory / document[-1]).read_bytes()
        if not content.startswith(b"%PDF-"):
            raise ValueError("样例文件不是 PDF：" + document[-1])
        digest = hashlib.sha256(content).hexdigest()
        conn.execute("INSERT OR IGNORE INTO files VALUES (?, ?)", (digest, content))
        conn.execute("INSERT INTO documents VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (*document, digest))
    conn.executemany(
        "INSERT INTO users(username, role, unit_id) VALUES (?, ?, ?)",
        [("admin", "admin", None), ("region-reader", "reader", 2)],
    )
