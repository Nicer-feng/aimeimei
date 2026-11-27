"""机房巡检的待办和留痕，独立于设备的运行状态和配置。"""

from datetime import datetime, timezone

from .data import ApiError, integer, invalid, string, visible_sites


KINDS = ("device", "placement", "ports")


def initialize_patrol(conn):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""CREATE TABLE IF NOT EXISTS device_patrol_checks (
            id INTEGER PRIMARY KEY,
            room_id INTEGER NOT NULL REFERENCES rooms(id) ON DELETE CASCADE,
            device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('device', 'placement', 'ports')),
            note TEXT NOT NULL,
            checked_at TEXT NOT NULL,
            checked_by TEXT NOT NULL
        )""")
        conn.execute("""CREATE INDEX IF NOT EXISTS device_patrol_checks_latest
            ON device_patrol_checks(room_id, device_id, kind, id DESC)""")


def missing_placement(device):
    return device["u_start"] is None and not device["workstation"].strip()


def room_patrol(conn, user, room_id):
    from .ports import patrol_port_counts

    room = conn.execute("SELECT id, name, site_id FROM rooms WHERE id = ?", (room_id,)).fetchone()
    if room is None or room["site_id"] not in visible_sites(conn, user):
        raise ApiError(404, "机房不存在或不在当前辖区内。")
    racks = conn.execute("SELECT id, name FROM racks WHERE room_id = ? ORDER BY name, id", (room_id,))
    devices = [
        dict(row, checks={}) for row in conn.execute(
            """SELECT id, code, name, rack_id, face, u_start, u_height, workstation, verified_on, operating_status
               FROM devices WHERE room_id = ? AND archived_at IS NULL
               ORDER BY rack_id, face, u_start DESC, code""",
            (room_id,),
        )
    ]
    by_id = {device["id"]: device for device in devices}
    for row in conn.execute(
        """SELECT check_record.device_id, check_record.kind, check_record.note,
                  check_record.checked_at, check_record.checked_by
           FROM device_patrol_checks AS check_record
           JOIN (SELECT MAX(id) AS id FROM device_patrol_checks WHERE room_id = ? GROUP BY device_id, kind)
               AS latest USING (id)""",
        (room_id,),
    ):
        if row["device_id"] in by_id:
            by_id[row["device_id"]]["checks"][row["kind"]] = dict(row)

    port_counts = patrol_port_counts(conn, by_id)
    for device in devices:
        counts = port_counts.get(device["id"], {})
        device.update(
            pending="device" not in device["checks"] and (not device["verified_on"] or
                                                         device["operating_status"] == "unknown"),
            missing_u=missing_placement(device),
            port_count=counts.get("registered", 0),
            missing_peers=counts.get("unknown_peer", 0),
        )
    return {"room": {"id": room["id"], "name": room["name"]},
            "racks": [dict(rack) for rack in racks], "devices": devices}


def record_patrol(conn, user, payload):
    from .ports import patrol_port_counts

    if user["role"] != "admin":
        raise ApiError(403, "当前账号只有辖区内的查阅权限。")
    room_id = integer(payload, "room_id", "机房", required=True)
    device_id = integer(payload, "device_id", "设备", required=True)
    kind = string(payload, "kind", "巡检类别", 20, required=True)
    if kind not in KINDS:
        raise invalid("巡检类别不受支持。")
    note = string(payload, "note", "巡检备注", 500, required=kind != "device")

    with conn:
        conn.execute("BEGIN IMMEDIATE")
        device = conn.execute(
            "SELECT room_id, workstation, u_start, archived_at FROM devices WHERE id = ?", (device_id,),
        ).fetchone()
        if device is None or device["archived_at"]:
            raise ApiError(404, "设备不存在或已下架。")
        if device["room_id"] != room_id:
            raise ApiError(409, "设备所属机房已变更，请重新打开巡检。")
        if kind == "placement" and not missing_placement(device):
            raise ApiError(409, "设备已有安装位置，请重新打开巡检。")
        if kind == "ports" and not patrol_port_counts(conn, [device_id]).get(device_id, {}).get("unknown_peer", 0):
            raise ApiError(409, "设备没有待补的对端，请重新打开巡检。")
        checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        checked_by = user["username"]
        conn.execute(
            """INSERT INTO device_patrol_checks(room_id, device_id, kind, note, checked_at, checked_by)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (room_id, device_id, kind, note, checked_at, checked_by),
        )
    return {"device_id": device_id, "kind": kind, "note": note, "checked_at": checked_at, "checked_by": checked_by}
