"""台账物理端口及双端线缆记录。"""

import re

from .data import ApiError, integer, invalid, iso_date, items, string, visible_sites, write_record


PORT_KINDS = ("copper", "fiber", "other")
UNLINKED_STATES = ("unknown", "free")
MAX_PORTS_PER_DEVICE = 512
NATURAL_PARTS = re.compile(r"([0-9]+)")


def scoped_device(conn, site_ids, device_id):
    device = conn.execute(
        """SELECT d.id, d.archived_at, room.site_id FROM devices d
           JOIN rooms room ON room.id = d.room_id WHERE d.id = ?""",
        (device_id,),
    ).fetchone()
    if device is None or device["site_id"] not in site_ids:
        raise ApiError(404, "设备不存在。")
    return device


def scoped_port(conn, site_ids, port_id):
    port = conn.execute(
        """SELECT p.*, d.archived_at, room.site_id, e.cable_id, e.side
           FROM physical_ports p JOIN devices d ON d.id = p.device_id
           JOIN rooms room ON room.id = d.room_id
           LEFT JOIN physical_cable_ends e ON e.port_id = p.id WHERE p.id = ?""",
        (port_id,),
    ).fetchone()
    if port is None or port["site_id"] not in site_ids:
        raise ApiError(404, "物理端口不存在。")
    return port


def require_active(record):
    if record["archived_at"]:
        raise ApiError(409, "设备已归档，恢复设备后才能登记端口或连接。")


def write_sites(conn, user):
    if user["role"] != "admin":
        raise ApiError(403, "当前账号只有辖区内的查阅权限。")
    return visible_sites(conn, user)


def natural_order(value):
    return tuple(int(part) if index % 2 else part for index, part in enumerate(NATURAL_PARTS.split(value.casefold())))


def port_order(port):
    return natural_order(port["group"]), port["position"] or 4097, natural_order(port["name"]), port["id"]


def device_ports(conn, user, device_id):
    site_ids = visible_sites(conn, user)
    scoped_device(conn, site_ids, device_id)
    ports = []
    for row in conn.execute(
        """SELECT local.*, own.cable_id, own.label, c.pending_peer_label, c.note, c.verified_on,
                  far.port_id AS peer_port_id, far.label AS peer_label, p.name AS port_name,
                  d.id AS peer_device_id, d.name AS device_name, d.code AS device_code, d.archived_at,
                  d.room_id, d.rack_id, r.name AS rack_name, d.face, d.u_start, d.u_height,
                  room.site_id AS peer_site_id
           FROM physical_ports local
           LEFT JOIN physical_cable_ends own ON own.port_id = local.id
           LEFT JOIN physical_cables c ON c.id = own.cable_id
           LEFT JOIN physical_cable_ends far ON far.cable_id = own.cable_id AND far.side <> own.side
           LEFT JOIN physical_ports p ON p.id = far.port_id
           LEFT JOIN devices d ON d.id = p.device_id
           LEFT JOIN rooms room ON room.id = d.room_id
           LEFT JOIN racks r ON r.id = d.rack_id
           WHERE local.device_id = ?""",
        (device_id,),
    ):
        state = row["base_state"]
        cable = None
        if row["cable_id"] is not None:
            state = "connected" if row["peer_port_id"] is not None else "pending"
            restricted = state == "connected" and row["peer_site_id"] not in site_ids
            peer = None
            if state == "connected" and not restricted:
                peer = {key: row[key] for key in ("port_name", "device_name", "device_code", "rack_id", "rack_name",
                                                  "room_id", "face", "u_start", "u_height", "archived_at")}
                peer.update(port_id=row["peer_port_id"], device_id=row["peer_device_id"])
            cable = {
                "id": None if restricted else row["cable_id"],
                "label": "" if restricted else row["label"],
                "peer_label": "" if restricted else (row["peer_label"] if peer else row["pending_peer_label"]),
                "note": "" if restricted else row["note"],
                "verified_on": None if restricted else row["verified_on"],
                "restricted": restricted,
                "peer": peer,
            }
        ports.append({
            "id": row["id"], "name": row["name"], "kind": row["kind"], "group": row["port_group"],
            "position": row["position"], "state": state, "demo": bool(row["is_demo"]), "cable": cable,
        })
    return {"device_id": device_id, "ports": sorted(ports, key=port_order)}


def port_values(payload, previous=None):
    defaults = {"name": "", "kind": "other", "group": "", "position": None, "state": "unknown"}
    if previous is not None:
        defaults.update(name=previous["name"], kind=previous["kind"], group=previous["port_group"],
                        position=previous["position"], state=previous["base_state"])
    values = {**defaults, **payload}
    kind = string(values, "kind", "介质", 12, required=True)
    state = string(values, "state", "端口状态", 12, required=True)
    if kind not in PORT_KINDS:
        raise invalid("请从网口、光口和其他介质中选择。")
    if state not in UNLINKED_STATES:
        raise invalid("端口状态应为待核实或空闲，连接状态须在线缆中登记。")
    return {
        "name": string(values, "name", "端口名称", 80, required=True),
        "kind": kind,
        "port_group": string(values, "group", "端口分组", 80),
        "position": integer(values, "position", "端口排序位置", maximum=4096),
        "base_state": state,
    }


def cable_values(payload):
    return {
        "label": string(payload, "label", "本端标签", 180),
        "peer_label": string(payload, "peer_label", "对端标签", 180),
        "peer_port_id": integer(payload, "peer_port_id", "对端端口"),
        "note": string(payload, "note", "线缆备注", 500),
        "verified_on": iso_date(payload, "verified_on", "核实日期"),
    }


def save_port_record(conn, device_id, values, port_id=None):
    duplicate = conn.execute(
        "SELECT 1 FROM physical_ports WHERE device_id = ? AND name = ? AND id <> COALESCE(?, 0)",
        (device_id, values["name"], port_id),
    ).fetchone()
    if duplicate:
        raise ApiError(409, f"此设备已有端口 {values['name']}。")
    return write_record(conn, "physical_ports", port_id, {"device_id": device_id, **values})


def save_cable_record(conn, port_id, cable_values, *, cable_id=None, side=0):
    peer_id = cable_values["peer_port_id"]
    wire = {
        "pending_peer_label": "" if peer_id is not None else cable_values["peer_label"],
        "note": cable_values["note"],
        "verified_on": cable_values["verified_on"],
    }
    cable_id = write_record(conn, "physical_cables", cable_id, wire)
    # 事务外只会看到完整的线缆记录。两个方向的标签随本端一起保存。
    conn.execute("DELETE FROM physical_cable_ends WHERE cable_id = ?", (cable_id,))
    ends = [(port_id, cable_id, side, cable_values["label"])]
    if peer_id is not None:
        ends.append((peer_id, cable_id, 1 - side, cable_values["peer_label"]))
    conn.executemany("INSERT INTO physical_cable_ends(port_id, cable_id, side, label) VALUES (?, ?, ?, ?)", ends)
    conn.executemany("UPDATE physical_ports SET base_state = 'unknown' WHERE id = ?", [(end[0],) for end in ends])
    return cable_id


def create_ports(conn, user, device_id, payload):
    batch = items(payload, "ports", "端口清单", maximum=128) if "ports" in payload else [payload]
    if not batch or any(not isinstance(entry, dict) for entry in batch):
        raise invalid("端口清单至少应包含一条有效记录。")
    records = []
    for entry in batch:
        values = port_values(entry)
        wire = cable_values(entry)
        if wire["peer_port_id"] is not None:
            raise invalid("请先登记端口，再绑定已登记的对端。")
        pending = any(wire.values())
        if pending and not wire["peer_label"]:
            raise invalid("登记待核线缆时请填写对端标签。")
        if pending and values["base_state"] == "free":
            raise invalid("空闲端口不能同时登记线缆。")
        records.append((values, wire if pending else None))
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        require_active(scoped_device(conn, write_sites(conn, user), device_id))
        count = conn.execute("SELECT COUNT(*) FROM physical_ports WHERE device_id = ?", (device_id,)).fetchone()[0]
        if count + len(records) > MAX_PORTS_PER_DEVICE:
            raise invalid(f"每台设备最多登记 {MAX_PORTS_PER_DEVICE} 个物理端口。")
        for values, wire in records:
            port_id = save_port_record(conn, device_id, values)
            if wire is not None:
                save_cable_record(conn, port_id, wire)
        return device_ports(conn, user, device_id)


def edit_port(conn, user, port_id, payload):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        site_ids = write_sites(conn, user)
        port = scoped_port(conn, site_ids, port_id)
        require_active(port)
        require_peer_scope(conn, site_ids, port)
        if port["cable_id"] is not None and "state" in payload:
            raise ApiError(409, "此端口已有线缆记录，请先解除关联。")
        values = port_values(payload, port)
        save_port_record(conn, port["device_id"], values, port_id)
        return device_ports(conn, user, port["device_id"])


def delete_port(conn, user, port_id):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        port = scoped_port(conn, write_sites(conn, user), port_id)
        if port["cable_id"] is not None:
            raise ApiError(409, "此端口已有线缆记录，请先解除关联。")
        conn.execute("DELETE FROM physical_ports WHERE id = ?", (port_id,))
        return device_ports(conn, user, port["device_id"])


def require_peer_scope(conn, site_ids, port):
    if port["cable_id"] is None:
        return
    end = conn.execute(
        "SELECT port_id FROM physical_cable_ends WHERE cable_id = ? AND side <> ?",
        (port["cable_id"], port["side"]),
    ).fetchone()
    if end is not None:
        scoped_port(conn, site_ids, end["port_id"])


def link_port(conn, user, port_id, payload):
    wire = cable_values(payload)
    peer_id = wire["peer_port_id"]
    if peer_id == port_id:
        raise invalid("物理端口不能连接自身。")
    if peer_id is None and not wire["peer_label"]:
        raise invalid("请选择对端端口，或填写待核对端的原始标签。")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        site_ids = write_sites(conn, user)
        port = scoped_port(conn, site_ids, port_id)
        require_active(port)
        require_peer_scope(conn, site_ids, port)
        if peer_id is not None:
            peer = scoped_port(conn, site_ids, peer_id)
            require_active(peer)
            if peer["cable_id"] is not None and peer["cable_id"] != port["cable_id"]:
                raise ApiError(409, "对端端口已有线缆记录，请先解除关联。")
        save_cable_record(conn, port_id, wire, cable_id=port["cable_id"], side=port["side"] or 0)
        return device_ports(conn, user, port["device_id"])


def unlink_port(conn, user, port_id):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        site_ids = write_sites(conn, user)
        port = scoped_port(conn, site_ids, port_id)
        require_peer_scope(conn, site_ids, port)
        if port["cable_id"] is not None:
            conn.execute("DELETE FROM physical_cables WHERE id = ?", (port["cable_id"],))
        return device_ports(conn, user, port["device_id"])


def patrol_port_counts(conn, device_ids):
    ids = set(device_ids)
    return {row["device_id"]: {"registered": row["registered"], "unknown_peer": row["unknown_peer"]}
            for row in conn.execute(
                """SELECT p.device_id, COUNT(*) AS registered,
                          SUM(own.cable_id IS NOT NULL AND peer.port_id IS NULL) AS unknown_peer
                   FROM physical_ports p
                   LEFT JOIN physical_cable_ends own ON own.port_id = p.id
                   LEFT JOIN physical_cable_ends peer ON peer.cable_id = own.cable_id AND peer.side <> own.side
                   GROUP BY p.device_id"""
            ) if row["device_id"] in ids}
