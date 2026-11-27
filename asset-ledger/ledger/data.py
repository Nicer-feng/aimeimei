"""SQLite 持久化、录入校验和辖区访问控制。"""

import base64
import binascii
from collections import defaultdict, deque
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import json
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import parse_qsl, urlsplit

from .attachment_formats import FORMATS, extension, valid_attachment
from .samples import seed, seed_physical_port_demo


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ATTACHMENT_LIMIT = 8 * 1024 * 1024
SESSION_SECONDS = 8 * 60 * 60
HASH_ROUNDS = 600_000
MOUNT_DEPTHS = ("unknown", "half", "full")
OPERATING_STATUSES = ("unknown", "running", "disabled", "unpowered")
LAYOUT_MAX_ROWS = 12
LAYOUT_MAX_COLUMNS = 20
LAYOUT_ROTATIONS = (0, 90, 180, 270)
MAX_RACK_HEIGHT = 255
RACK_FACES = ("front", "rear")
DELETABLE_RECORDS = ("devices", "projects", "systems", "documents")


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def invalid(message):
    return ApiError(400, message)


def connect(data_dir):
    conn = sqlite3.connect(str(data_dir / "ledger.sqlite3"), timeout=8)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def database(data_dir):
    conn = connect(data_dir)
    try:
        yield conn
    finally:
        conn.close()


def initialize(data_dir):
    data_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
    with database(data_dir) as conn:
        (data_dir / "ledger.sqlite3").chmod(0o600)
        conn.execute("PRAGMA journal_mode = WAL")
        migrate_schema(conn)
        with conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM metadata WHERE key = 'samples'").fetchone() is None:
                seed(conn, PROJECT_ROOT / "samples")
                conn.execute("INSERT INTO metadata VALUES ('samples', '1')")
            seed_physical_port_demo(conn)


def migrate_schema(conn):
    conn.executescript((Path(__file__).parent / "schema.sql").read_text(encoding="utf-8"))
    migrate_mount_depth(conn)
    migrate_operating_status(conn)
    migrate_device_catalog(conn)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        seed_physical_port_demo(conn)


def migrate_mount_depth(conn):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if any(column["name"] == "mount_depth" for column in conn.execute("PRAGMA table_info(devices)")):
            return
        conn.execute("""ALTER TABLE devices ADD COLUMN mount_depth TEXT NOT NULL DEFAULT 'unknown' CHECK (
            mount_depth IN ('unknown', 'half', 'full') AND (rack_id IS NOT NULL OR mount_depth = 'unknown')
        )""")


def migrate_operating_status(conn):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if any(column["name"] == "operating_status" for column in conn.execute("PRAGMA table_info(devices)")):
            return
        conn.execute("""ALTER TABLE devices ADD COLUMN operating_status TEXT NOT NULL DEFAULT 'unknown' CHECK (
            operating_status IN ('unknown', 'running', 'disabled', 'unpowered')
        )""")


def migrate_device_catalog(conn):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        for table, columns in (
            ("devices", {"archived_at": "TEXT", "archived_location": "TEXT"}),
            ("service_entries", {
                "source_document_id": "INTEGER REFERENCES documents(id) ON DELETE SET NULL",
                "source_page": "INTEGER CHECK (source_page > 0)",
            }),
        ):
            existing = {column["name"] for column in conn.execute(f"PRAGMA table_info({table})")}
            for name, definition in columns.items():
                if name not in existing:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def password_hash(password, salt):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, HASH_ROUNDS).hex()


def reset_password(conn, username, password):
    if len(password) < 12 or len(password) > 256:
        raise ValueError("密码长度须为 12 至 256 个字符。")
    salt = secrets.token_bytes(24)
    value = salt.hex() + "$" + password_hash(password, salt)
    with conn:
        result = conn.execute("UPDATE users SET password_hash = ? WHERE username = ?", (value, username))
        if result.rowcount != 1:
            raise ValueError("账号不存在。")
        conn.execute("DELETE FROM sessions WHERE username = ?", (username,))


def digest_token(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def log_in(conn, username, password):
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    stored = row["password_hash"] if row else None
    salt, expected_hash = stored.split("$", 1) if stored else ("00" * 24, "00" * 32)
    verified = hmac.compare_digest(expected_hash, password_hash(password, bytes.fromhex(salt)))
    if not stored or not verified:
        raise ApiError(401, "账号或密码不正确。")
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with conn:
        conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
        conn.execute("INSERT INTO sessions VALUES (?, ?, ?)", (digest_token(token), username, now + SESSION_SECONDS))
    return row, token


def session_user(conn, token):
    if token is None:
        return None
    return conn.execute(
        """SELECT users.* FROM sessions JOIN users USING (username)
           WHERE token_digest = ? AND expires_at > ?""",
        (digest_token(token), int(time.time())),
    ).fetchone()


def log_out(conn, token):
    if token is not None:
        with conn:
            conn.execute("DELETE FROM sessions WHERE token_digest = ?", (digest_token(token),))


def profile(conn, user):
    scope_name = "全部站点"
    if user["role"] == "reader":
        scope_name = conn.execute("SELECT name FROM units WHERE id = ?", (user["unit_id"],)).fetchone()["name"]
    return {"username": user["username"], "role": user["role"], "scope_name": scope_name}


def visible_sites(conn, user):
    if user["role"] == "admin":
        return {row["id"] for row in conn.execute("SELECT id FROM sites")}
    return {
        row["id"] for row in conn.execute(
            """WITH RECURSIVE jurisdiction(id) AS (
                   SELECT ? UNION SELECT units.id FROM units JOIN jurisdiction ON units.parent_id = jurisdiction.id
               ) SELECT sites.id FROM sites JOIN jurisdiction ON sites.unit_id = jurisdiction.id""",
            (user["unit_id"],),
        )
    }


def project_lists(conn, site_ids, is_admin):
    projects = {
        row["id"]: dict(row, device_ids=[]) for row in conn.execute("SELECT * FROM projects ORDER BY id")
        if row["site_id"] in site_ids
    }
    hidden_projects = set()
    for link in conn.execute(
        """SELECT pd.project_id, pd.device_id, r.site_id
           FROM project_devices AS pd JOIN devices AS d ON d.id = pd.device_id
           JOIN rooms AS r ON r.id = d.room_id ORDER BY pd.project_id, pd.device_id"""
    ):
        project_id = link["project_id"]
        if project_id not in projects:
            continue
        if not is_admin and link["site_id"] not in site_ids:
            hidden_projects.add(project_id)
        else:
            projects[project_id]["device_ids"].append(link["device_id"])
    for project_id in hidden_projects:
        del projects[project_id]
    return projects


def room_layout_record(room_id, rows, columns, positions, illustrative=False):
    return {"room_id": room_id, "rows": rows, "columns": columns,
            "positions": sorted(positions, key=lambda position: (position["row"], position["slot"])),
            "illustrative": illustrative}


def illustrative_room_layout(rooms, sites, units, racks):
    room = rooms.get(1)
    site = next((site for site in sites if site["id"] == 1), None)
    unit = units.get(2)
    if (not room or room["site_id"] != 1 or room["name"] != "综合机房" or not site or
            site["unit_id"] != 2 or site["name"] != "青岚站" or not unit or unit["name"] != "演示东区"):
        return None
    rack_names = {rack["id"]: rack["name"] for rack in racks if rack["room_id"] == room["id"]}
    positions = []
    for number in range(1, 10):
        rack_id = 1 if number == 1 else number + 1
        if rack_names.get(rack_id) == f"A{number:02d}":
            row, offset = divmod(number - 1, 5)
            # 第一排位于正 Z 方向，两排柜的正面都朝向中央通道。
            positions.append({"rack_id": rack_id, "row": row + 1, "slot": offset + 1, "rotation": 180 if row == 0 else 0})
    return room_layout_record(room["id"], 2, 5, positions, illustrative=True)


def room_layouts(conn, rooms, sites, units, racks):
    rack_rooms = {rack["id"]: rack["room_id"] for rack in racks}
    layouts = {}
    for layout in conn.execute("SELECT * FROM room_layouts ORDER BY room_id"):
        room_id = layout["room_id"]
        if room_id in rooms:
            positions = [position for position in json.loads(layout["positions_json"])
                         if rack_rooms.get(position["rack_id"]) == room_id]
            layouts[room_id] = room_layout_record(room_id, layout["row_count"], layout["column_count"], positions)
    demo = illustrative_room_layout(rooms, sites, units, racks)
    if demo:
        layouts.setdefault(demo["room_id"], demo)
    return [layouts[room_id] for room_id in sorted(layouts)]


def entry_source(row, documents):
    document = documents.get(row["source_document_id"])
    return {"source_document_id": document["id"] if document else None,
            "source_page": row["source_page"] if document else None}


def catalog(conn, user):
    is_admin = user["role"] == "admin"
    site_ids = visible_sites(conn, user)
    sites = [dict(row) for row in conn.execute("SELECT * FROM sites ORDER BY id") if row["id"] in site_ids]
    units = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM units ORDER BY id")}
    if not is_admin:
        visible_unit_ids = {user["unit_id"]}
        for site in sites:
            unit_id = site["unit_id"]
            while unit_id is not None and unit_id not in visible_unit_ids:
                visible_unit_ids.add(unit_id)
                unit_id = units[unit_id]["parent_id"]
        units = {
            ident: dict(unit, parent_id=unit["parent_id"] if unit["parent_id"] in visible_unit_ids else None)
            for ident, unit in units.items() if ident in visible_unit_ids
        }
    rooms = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM rooms ORDER BY id") if row["site_id"] in site_ids}
    racks = [dict(row) for row in conn.execute("SELECT * FROM racks ORDER BY id") if row["room_id"] in rooms]
    devices = {
        row["id"]: dict(row, project_ids=[], addresses=[], archived_location=json.loads(row["archived_location"] or "null"))
        for row in conn.execute("SELECT * FROM devices ORDER BY id") if row["room_id"] in rooms
    }
    projects = project_lists(conn, site_ids, is_admin)
    for project in projects.values():
        for device_id in project["device_ids"]:
            devices[device_id]["project_ids"].append(project["id"])
    documents = {
        row["id"]: dict(row) for row in conn.execute(
            "SELECT id, title, category, project_id, device_id, page, note, filename FROM documents ORDER BY id"
        ) if row["project_id"] in projects or row["device_id"] in devices
    }
    for row in conn.execute("SELECT * FROM device_addresses ORDER BY id"):
        device = devices.get(row["device_id"])
        if device:
            device["addresses"].append({"host": row["host"], "note": row["note"], **entry_source(row, documents)})
    systems = {row["id"]: dict(row, deployments=[]) for row in conn.execute("SELECT * FROM systems ORDER BY id")}
    deployments = {}
    for row in conn.execute("SELECT * FROM deployments ORDER BY id"):
        if row["device_id"] in devices:
            deployment = {"id": row["id"], "device_id": row["device_id"], "note": row["note"], "entries": []}
            deployments[row["id"]] = deployment
            systems[row["system_id"]]["deployments"].append(deployment)
    for row in conn.execute("SELECT * FROM service_entries ORDER BY id"):
        deployment = deployments.get(row["deployment_id"])
        if deployment:
            fields = {key: row[key] for key in ("id", "host", "protocol", "port", "purpose", "url")}
            fields.update(entry_source(row, documents))
            deployment["entries"].append(fields)
    return {
        "units": list(units.values()), "sites": sites, "rooms": list(rooms.values()), "racks": racks,
        "devices": list(devices.values()), "systems": [system for system in systems.values() if is_admin or system["deployments"]],
        "projects": list(projects.values()), "documents": list(documents.values()),
        "room_layouts": room_layouts(conn, rooms, sites, units, racks),
    }


def document_file(conn, user, ident):
    row = conn.execute(
        """SELECT documents.*, rooms.site_id AS device_site_id FROM documents
           LEFT JOIN devices ON devices.id = documents.device_id
           LEFT JOIN rooms ON rooms.id = devices.room_id WHERE documents.id = ?""",
        (ident,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "档案不存在。")
    if user["role"] != "admin":
        site_ids = visible_sites(conn, user)
        if row["device_site_id"] not in site_ids and row["project_id"] not in project_lists(conn, site_ids, False):
            raise ApiError(404, "档案不存在。")
    content = conn.execute("SELECT content FROM files WHERE digest = ?", (row["file_digest"],)).fetchone()["content"]
    return row["filename"], content


def string(payload, key, label, maximum=200, required=False, trim=True):
    value = payload.get(key)
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise invalid(f"{label}应为文本。")
    if trim:
        value = value.strip()
    if len(value) > maximum or (required and not value):
        raise invalid(f"请填写有效的{label}，最多 {maximum} 个字符。")
    if any(0xD800 <= ord(char) <= 0xDFFF or char == "\x00" for char in value):
        raise invalid(f"{label}含有无效字符。")
    return value


def integer(payload, key, label, required=False, maximum=2 ** 31 - 1):
    value = payload.get(key)
    if value is None and not required:
        return None
    if type(value) is not int or not 1 <= value <= maximum:
        raise invalid(f"{label}应为 1 至 {maximum} 的整数。")
    return value


def items(payload, key, label, maximum=200):
    value = payload.get(key, [])
    if not isinstance(value, list) or len(value) > maximum:
        raise invalid(f"{label}应为列表，最多 {maximum} 项。")
    return value


def id_list(payload, key, label):
    values = items(payload, key, label)
    return list(dict.fromkeys(integer({"value": value}, "value", label, required=True) for value in values))


def iso_date(payload, key, label):
    value = string(payload, key, label, 10)
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value).isoformat()
    except ValueError:
        raise invalid(f"{label}应为有效的 YYYY-MM-DD 日期。") from None
    if parsed != value:
        raise invalid(f"{label}应为有效的 YYYY-MM-DD 日期。")
    return parsed


def asset_price(payload):
    value = payload.get("price")
    if value is None or value == "":
        return None
    if type(value) not in (int, float, str) or len(str(value)) > 30:
        raise invalid("购置价格应为非负数，最多保留两位小数。")
    try:
        price = Decimal(str(value))
        if price.is_finite() and 0 <= price <= Decimal("999999999999.99") and price == price.quantize(Decimal("0.01")):
            return float(price)
    except InvalidOperation:
        pass
    raise invalid("购置价格应为非负数，最多保留两位小数。")


def ensure_record(conn, table, ident, label, status=400):
    if conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (ident,)).fetchone() is None:
        raise ApiError(status, f"{label}不存在。")


def save_room_layout(conn, payload, room_id):
    rows = integer(payload, "rows", "排数", required=True, maximum=LAYOUT_MAX_ROWS)
    columns = integer(payload, "columns", "每排格数", required=True, maximum=LAYOUT_MAX_COLUMNS)
    if "positions" not in payload:
        raise invalid("请提供机柜摆位列表。")
    positions = []
    assigned_racks = set()
    occupied_slots = set()
    for position in items(payload, "positions", "机柜摆位", maximum=rows * columns):
        if not isinstance(position, dict):
            raise invalid("机柜摆位应为对象。")
        rack_id = integer(position, "rack_id", "机柜", required=True)
        row = integer(position, "row", "所在排", required=True, maximum=rows)
        slot = integer(position, "slot", "所在格", required=True, maximum=columns)
        rotation = position.get("rotation")
        if type(rotation) is not int or rotation not in LAYOUT_ROTATIONS:
            raise invalid("机柜朝向须为 0、90、180 或 270 度。")
        if rack_id in assigned_racks or (row, slot) in occupied_slots:
            raise invalid("同一机柜或格位不能重复摆放。")
        assigned_racks.add(rack_id)
        occupied_slots.add((row, slot))
        positions.append({"rack_id": rack_id, "row": row, "slot": slot, "rotation": rotation})

    layout = room_layout_record(room_id, rows, columns, positions)
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        ensure_record(conn, "rooms", room_id, "机房", 404)
        available = {row["id"] for row in conn.execute("SELECT id FROM racks WHERE room_id = ?", (room_id,))}
        if not assigned_racks <= available:
            raise invalid("布局中的机柜须属于当前机房。")
        conn.execute(
            """INSERT INTO room_layouts(room_id, row_count, column_count, positions_json) VALUES (?, ?, ?, ?)
               ON CONFLICT(room_id) DO UPDATE SET row_count = excluded.row_count,
               column_count = excluded.column_count, positions_json = excluded.positions_json""",
            (room_id, rows, columns, json.dumps(layout["positions"], separators=(",", ":"))),
        )
    return layout


def write_record(conn, table, ident, values):
    # 表名、字段名来自本模块的固定字面量，录入值统一使用 SQL 参数。
    if ident is None and table in DELETABLE_RECORDS:
        # 旧的书签或确认窗口不能在删除记录后指向另一条新记录。
        floor = conn.execute("SELECT value FROM metadata WHERE key = ?", (f"deleted-id:{table}",)).fetchone()
        if floor:
            largest = conn.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}").fetchone()[0]
            values = {"id": max(largest, int(floor["value"])) + 1, **values}
    keys = list(values)
    args = tuple(values.values())
    if ident is None:
        placeholders = ", ".join("?" for key in keys)
        return conn.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({placeholders})", args).lastrowid
    columns = ", ".join(f"{key} = ?" for key in keys)
    conn.execute(f"UPDATE {table} SET {columns} WHERE id = ?", (*args, ident))
    return ident


def save_room(conn, user, payload, ident=None):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM rooms WHERE id = ?", (ident,)).fetchone() if ident is not None else None
        if ident is not None and previous is None:
            raise ApiError(404, "机房不存在。")
        site_id = previous["site_id"] if previous and "site_id" not in payload else integer(
            payload, "site_id", "站点", required=True,
        )
        if previous and site_id != previous["site_id"]:
            raise invalid("已登记机房不可更换所属站点。")
        ensure_record(conn, "sites", site_id, "站点")
        name = previous["name"] if previous and "name" not in payload else string(
            payload, "name", "机房名称", 160, required=True,
        )
        if conn.execute("SELECT 1 FROM rooms WHERE site_id = ? AND name = ? COLLATE NOCASE AND id != ?",
                        (site_id, name, ident or 0)).fetchone():
            raise ApiError(409, "该站点已有同名机房。")
        saved_id = write_record(conn, "rooms", ident, {"site_id": site_id, "name": name})
    return {"id": saved_id, "site_id": site_id, "name": name}


def save_rack(conn, user, payload, ident=None):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM racks WHERE id = ?", (ident,)).fetchone() if ident is not None else None
        if ident is not None and previous is None:
            raise ApiError(404, "机柜不存在。")
        room_id = previous["room_id"] if previous and "room_id" not in payload else integer(
            payload, "room_id", "机房", required=True,
        )
        if previous and room_id != previous["room_id"]:
            raise invalid("已登记机柜不可更换所属机房。")
        ensure_record(conn, "rooms", room_id, "机房")
        name = previous["name"] if previous and "name" not in payload else string(
            payload, "name", "柜号", 80, required=True,
        )
        height = previous["height"] if previous and "height" not in payload else integer(
            payload, "height", "柜高", required=True, maximum=MAX_RACK_HEIGHT,
        )
        if conn.execute("SELECT 1 FROM racks WHERE room_id = ? AND name = ? COLLATE NOCASE AND id != ?",
                        (room_id, name, ident or 0)).fetchone():
            raise ApiError(409, "该机房已有相同柜号。")
        if previous and height < previous["height"]:
            blocker = conn.execute(
                """SELECT code, u_start + u_height - 1 AS end_u FROM devices WHERE rack_id = ?
                   AND u_start + u_height - 1 > ? ORDER BY end_u DESC LIMIT 1""",
                (ident, height),
            ).fetchone()
            if blocker:
                raise ApiError(409, f"设备 {blocker['code']} 占用至 U{blocker['end_u']}，不能降低柜高。")
        saved_id = write_record(conn, "racks", ident, {"room_id": room_id, "name": name, "height": height})
    return {"id": saved_id, "room_id": room_id, "name": name, "height": height}


def save_device(conn, user, payload, ident=None):
    mount_depth = payload.get("mount_depth", "unknown")
    if mount_depth not in MOUNT_DEPTHS:
        raise invalid("设备深度应为待核、半深或全深。")
    operating_status = payload.get("operating_status", "unknown")
    if operating_status not in OPERATING_STATUSES:
        raise invalid("运行状态应为待核实、运行中、已停用或未通电。")
    values = {
        "code": string(payload, "code", "设备编号", 80, required=True),
        "name": string(payload, "name", "设备名称", required=True),
        "type": string(payload, "type", "设备类型", 80, required=True),
        "model": string(payload, "model", "品牌型号"),
        "serial": string(payload, "serial", "序列号"),
        "room_id": integer(payload, "room_id", "机房", required=True),
        "rack_id": integer(payload, "rack_id", "机柜"),
        "face": None, "u_start": None, "u_height": None, "mount_depth": "unknown",
        "operating_status": operating_status,
        "workstation": string(payload, "workstation", "工位"),
        "purpose": string(payload, "purpose", "用途", 500),
        "ownership": string(payload, "ownership", "归属"),
        "reporter": string(payload, "reporter", "填报人"),
        "maintainer": string(payload, "maintainer", "维护人"),
        "verified_on": iso_date(payload, "verified_on", "最近核实时间"),
        "purchased_on": iso_date(payload, "purchased_on", "购置时间"),
        "price": asset_price(payload),
    }
    if values["rack_id"] is not None:
        values["face"] = string(payload, "face", "机柜面", 5, required=True)
        if values["face"] not in ("front", "rear"):
            raise invalid("机柜面应为正面或背面。")
        values["u_start"] = integer(payload, "u_start", "起始 U 位", required=True)
        values["u_height"] = integer(payload, "u_height", "占用 U 数", required=True)
    project_ids = id_list(payload, "project_ids", "项目") if "project_ids" in payload else None
    addresses = device_addresses(payload) if "addresses" in payload else None
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        previous = conn.execute("SELECT * FROM devices WHERE id = ?", (ident,)).fetchone() if ident is not None else None
        if ident is not None and previous is None:
            raise ApiError(404, "设备不存在。")
        if previous is not None and previous["archived_at"]:
            raise ApiError(409, "设备已下架归档，恢复后再编辑。")
        if previous is not None and "operating_status" not in payload:
            values["operating_status"] = previous["operating_status"]
        ensure_record(conn, "rooms", values["room_id"], "机房")
        if values["rack_id"] is not None:
            values["mount_depth"] = previous["mount_depth"] if previous is not None and "mount_depth" not in payload else mount_depth
            validate_rack_position(conn, values, ident, previous)
        if conn.execute(
            "SELECT 1 FROM devices WHERE code = ? AND id != ?", (values["code"], ident or 0)
        ).fetchone():
            raise ApiError(409, "设备编号已存在。")
        for project_id in project_ids or []:
            ensure_record(conn, "projects", project_id, "项目")
        saved_id = write_record(conn, "devices", ident, values)
        if project_ids is not None:
            conn.execute("DELETE FROM project_devices WHERE device_id = ?", (saved_id,))
            conn.executemany("INSERT INTO project_devices VALUES (?, ?)", [(pid, saved_id) for pid in project_ids])
        if addresses is not None:
            previous_sources = {(row["host"], row["source_document_id"]) for row in conn.execute(
                "SELECT host, source_document_id FROM device_addresses WHERE device_id = ?", (saved_id,),
            )}
            for host, _, document_id, _ in addresses:
                if (host, document_id) not in previous_sources:
                    ensure_device_source(conn, saved_id, document_id)
            conn.execute("DELETE FROM device_addresses WHERE device_id = ?", (saved_id,))
            conn.executemany(
                """INSERT INTO device_addresses(device_id, host, note, source_document_id, source_page)
                   VALUES (?, ?, ?, ?, ?)""", [(saved_id, *address) for address in addresses],
            )
        return next(device for device in catalog(conn, user)["devices"] if device["id"] == saved_id)


def set_device_archive(conn, user, ident, archived):
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        device = conn.execute(
            """SELECT d.*, room.name AS room_name, rack.name AS rack_name FROM devices d
               JOIN rooms room ON room.id = d.room_id LEFT JOIN racks rack ON rack.id = d.rack_id
               WHERE d.id = ?""", (ident,),
        ).fetchone()
        if device is None:
            raise ApiError(404, "设备不存在。")
        if archived and not device["archived_at"]:
            location = {key: device[key] for key in (
                "room_id", "room_name", "rack_id", "rack_name", "face", "u_start", "u_height", "mount_depth", "workstation",
            )}
            conn.execute(
                """UPDATE devices SET archived_at = ?, archived_location = ?, rack_id = NULL,
                   face = NULL, u_start = NULL, u_height = NULL, mount_depth = 'unknown', workstation = '' WHERE id = ?""",
                (datetime.now(timezone.utc).isoformat(timespec="seconds"), json.dumps(location, ensure_ascii=False), ident),
            )
        if not archived and device["archived_at"]:
            location = json.loads(device["archived_location"] or "{}")
            conn.execute(
                "UPDATE devices SET archived_at = NULL, archived_location = NULL, workstation = ? WHERE id = ?",
                (location.get("workstation", ""), ident),
            )
        return next(item for item in catalog(conn, user)["devices"] if item["id"] == ident)


def delete_record(conn, resource, ident):
    references = {
        "devices": ("设备", (("project_devices", "device_id", "项目关联"),
                               ("deployments", "device_id", "业务部署"), ("documents", "device_id", "档案"))),
        "projects": ("项目", (("project_devices", "project_id", "设备关联"), ("documents", "project_id", "档案"))),
        "systems": ("业务系统", (("deployments", "system_id", "业务部署"),)),
    }
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if resource == "documents":
            document = conn.execute("SELECT file_digest FROM documents WHERE id = ?", (ident,)).fetchone()
            if document is None:
                raise ApiError(404, "档案不存在。")
            for table in ("device_addresses", "service_entries"):
                conn.execute(f"UPDATE {table} SET source_document_id = NULL, source_page = NULL WHERE source_document_id = ?",
                             (ident,))
            conn.execute("DELETE FROM documents WHERE id = ?", (ident,))
            conn.execute(
                "DELETE FROM files WHERE digest = ? AND NOT EXISTS (SELECT 1 FROM documents WHERE file_digest = ?)",
                (document["file_digest"], document["file_digest"]),
            )
        else:
            label, dependencies = references[resource]
            ensure_record(conn, resource, ident, label, 404)
            associated = [kind for table, column, kind in dependencies if conn.execute(
                f"SELECT 1 FROM {table} WHERE {column} = ? LIMIT 1", (ident,),
            ).fetchone()]
            if resource == "devices" and conn.execute(
                """SELECT 1 FROM physical_ports p JOIN physical_cable_ends e ON e.port_id = p.id
                   WHERE p.device_id = ? LIMIT 1""", (ident,),
            ).fetchone():
                associated.append("物理线缆")
            if associated:
                raise ApiError(409, f"{label}仍有关联记录（{'、'.join(associated)}），请先解除关联。")
            conn.execute(f"DELETE FROM {resource} WHERE id = ?", (ident,))
        conn.execute(
            """INSERT INTO metadata(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE
               SET value = MAX(CAST(value AS INTEGER), CAST(excluded.value AS INTEGER))""",
            (f"deleted-id:{resource}", ident),
        )


def preserves_rack_position(values, previous):
    return (
        previous is not None
        and all(previous[key] == values[key] for key in ("rack_id", "face", "u_start", "u_height"))
        and (previous["mount_depth"] == values["mount_depth"]
             or (previous["mount_depth"] == "unknown" and values["mount_depth"] == "half"))
    )


def placement_conflict(face, depth, preserve, blocker):
    if blocker["face"] == face:
        return f"同一安装面的 U 位与设备 {blocker['code']} 重叠。"
    if depth == "full" or blocker["mount_depth"] == "full":
        return f"全深设备同时占用正背面 U 位，与对面设备 {blocker['code']} 冲突。"
    if not preserve and (depth == "unknown" or blocker["mount_depth"] == "unknown"):
        return f"与对面设备 {blocker['code']} 共用 U 位前，需核实两台设备均为半深。"
    return None


def validate_rack_position(conn, values, ident, previous=None):
    rack = conn.execute("SELECT room_id, height FROM racks WHERE id = ?", (values["rack_id"],)).fetchone()
    if rack is None or rack["room_id"] != values["room_id"]:
        raise invalid("所选机柜须属于所选机房。")
    start = values["u_start"]
    end = start + values["u_height"] - 1
    if end > rack["height"]:
        raise invalid(f"设备超出机柜的 {rack['height']}U 范围。")
    # 旧记录可能在前后面共享 U 位。可就地保留或补核半深，改位置时按新规则核对。
    legacy_position = preserves_rack_position(values, previous)
    blockers = conn.execute(
        """SELECT code, face, mount_depth FROM devices WHERE rack_id = ? AND id != ?
           AND u_start <= ? AND u_start + u_height - 1 >= ?
           ORDER BY face = ? DESC, mount_depth = 'full' DESC, id""",
        (values["rack_id"], ident or 0, end, start, values["face"]),
    )
    for blocker in blockers:
        conflict = placement_conflict(values["face"], values["mount_depth"], legacy_position, blocker)
        if conflict:
            raise ApiError(409, conflict)


def rack_availability(conn, user, query):
    keys = {"height", "depth", "face", "room_id", "rack_id", "exclude_device_id"}
    try:
        values = parse_qsl(query, keep_blank_values=True, strict_parsing=True, max_num_fields=len(keys))
    except ValueError:
        raise invalid("柜位查询参数格式不正确。") from None
    params = dict(values)
    if len(params) != len(values) or params.keys() - keys:
        raise invalid("柜位查询含未知或重复参数。")

    for key in ("height", "room_id", "rack_id", "exclude_device_id"):
        if key in params:
            value = params[key]
            if not value.isascii() or not value.isdecimal() or len(value) > 10:
                raise invalid("柜位筛选的高度和编号应为正整数。")
            params[key] = int(value)
    height = integer(params, "height", "占用 U 数", required=True, maximum=MAX_RACK_HEIGHT)
    room_id = integer(params, "room_id", "机房")
    rack_id = integer(params, "rack_id", "机柜")
    excluded_id = integer(params, "exclude_device_id", "排除设备")
    depth = params.get("depth", "unknown")
    face = params.get("face", "any")
    if depth not in MOUNT_DEPTHS or face not in (*RACK_FACES, "any"):
        raise invalid("请选择有效的机柜面与设备深度。")

    site_ids = visible_sites(conn, user)
    rooms = {row["id"] for row in conn.execute("SELECT id, site_id FROM rooms") if row["site_id"] in site_ids}
    if room_id is not None and room_id not in rooms:
        raise ApiError(404, "机房不存在。")
    if excluded_id is not None:
        previous = conn.execute("SELECT * FROM devices WHERE id = ?", (excluded_id,)).fetchone()
        if previous is None or previous["room_id"] not in rooms:
            raise ApiError(404, "设备不存在。")
    else:
        previous = None
    racks = {
        row["id"]: dict(row, faces={})
        for row in conn.execute("SELECT * FROM racks ORDER BY room_id, name, id")
        if row["room_id"] in rooms and (room_id is None or row["room_id"] == room_id)
        and (rack_id is None or row["id"] == rack_id)
    }
    if rack_id is not None and rack_id not in racks:
        raise ApiError(404, "机柜不存在。")
    placements = {ident: [] for ident in racks}
    for device in conn.execute(
        "SELECT id, rack_id, face, u_start, u_height, mount_depth, code FROM devices WHERE rack_id IS NOT NULL ORDER BY id"
    ):
        if device["id"] != excluded_id and device["rack_id"] in placements:
            placements[device["rack_id"]].append(device)

    for rack in racks.values():
        occupied = placements[rack["id"]]
        for side in RACK_FACES:
            result = {"starts": []}
            rack["faces"][side] = result
            position = {"rack_id": rack["id"], "face": side, "u_height": height, "mount_depth": depth}
            if face in ("any", side):
                for start in range(1, rack["height"] - height + 2):
                    position["u_start"] = start
                    preserve = preserves_rack_position(position, previous)
                    if not any(
                        device["u_start"] < start + height and start < device["u_start"] + device["u_height"]
                        and placement_conflict(side, depth, preserve, device)
                        for device in occupied
                    ):
                        result["starts"].append(start)
            if rack_id is not None:
                slots = [{"u": number, "state": "free"} for number in range(1, rack["height"] + 1)]
                priority = {"free": 0, "half": 1, "unknown": 2, "full": 3, "occupied": 4}
                for device in occupied:
                    state = "occupied" if side == device["face"] else device["mount_depth"]
                    end = min(rack["height"], device["u_start"] + device["u_height"] - 1)
                    for number in range(device["u_start"], end + 1):
                        slot = slots[number - 1]
                        if priority[state] > priority[slot["state"]]:
                            slot.update(state=state, code=device["code"], device_id=device["id"])
                result["slots"] = slots
    return {"racks": list(racks.values())}


def save_project(conn, user, payload, ident=None):
    values = {
        "name": string(payload, "name", "项目名称", required=True),
        "code": string(payload, "code", "项目编号", 80, required=True),
        "description": string(payload, "description", "项目说明", 1500),
        "site_id": integer(payload, "site_id", "站点", required=True),
    }
    device_ids = id_list(payload, "device_ids", "采购设备") if "device_ids" in payload else None
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if ident is not None:
            ensure_record(conn, "projects", ident, "项目", 404)
        ensure_record(conn, "sites", values["site_id"], "站点")
        linked = {row["device_id"] for row in conn.execute(
            "SELECT device_id FROM project_devices WHERE project_id = ?", (ident,),
        )} if ident is not None and device_ids is not None else set()
        for device_id in device_ids or []:
            ensure_linkable_device(conn, device_id, "设备", linked)
        if conn.execute(
            "SELECT 1 FROM projects WHERE code = ? AND id != ?", (values["code"], ident or 0)
        ).fetchone():
            raise ApiError(409, "项目编号已存在。")
        saved_id = write_record(conn, "projects", ident, values)
        if device_ids is not None:
            conn.execute("DELETE FROM project_devices WHERE project_id = ?", (saved_id,))
            conn.executemany("INSERT INTO project_devices VALUES (?, ?)", [(saved_id, did) for did in device_ids])
        return next(project for project in catalog(conn, user)["projects"] if project["id"] == saved_id)


def ensure_linkable_device(conn, device_id, label, previous):
    device = conn.execute("SELECT archived_at FROM devices WHERE id = ?", (device_id,)).fetchone()
    if device is None:
        raise invalid(f"{label}不存在。")
    if device["archived_at"] and device_id not in previous:
        raise ApiError(409, "已归档设备不能新增关联。")


def source_fields(payload):
    document_id = integer(payload, "source_document_id", "依据档案")
    page = integer(payload, "source_page", "依据页码", maximum=9999)
    if page is not None and document_id is None:
        raise invalid("填写依据页码时须选择档案。")
    return document_id, page


def ensure_device_source(conn, device_id, document_id):
    if document_id is not None and conn.execute(
        """SELECT 1 FROM documents d WHERE d.id = ? AND (d.device_id = ? OR EXISTS (
           SELECT 1 FROM project_devices pd WHERE pd.device_id = ? AND pd.project_id = d.project_id))""",
        (document_id, device_id, device_id),
    ).fetchone() is None:
        raise invalid("依据档案须与设备或设备所属项目关联。")


def check_host(host):
    if not host or any(char.isspace() or ord(char) < 32 or char in "/\\@?#" for char in host):
        raise invalid("请填写有效的 IP 或域名，端口请单独填写。")


def device_addresses(payload):
    addresses = []
    for address in items(payload, "addresses", "管理地址", maximum=100):
        if not isinstance(address, dict):
            raise invalid("管理地址应为对象。")
        host = string(address, "host", "管理地址", 253, required=True)
        check_host(host)
        addresses.append((host, string(address, "note", "地址备注", 300), *source_fields(address)))
    return addresses


def service_entry(payload):
    if not isinstance(payload, dict):
        raise invalid("服务入口应为对象。")
    url = string(payload, "url", "网页访问地址", 1000)
    host = string(payload, "host", "IP 或域名", 253)
    if url:
        if any(char.isspace() or ord(char) < 32 for char in url) or "\\" in url:
            raise invalid("网页访问地址格式不正确。")
        try:
            parsed = urlsplit(url)
            port = parsed.port
            if (parsed.scheme not in ("http", "https") or not parsed.hostname or
                    parsed.username is not None or parsed.password is not None or port == 0):
                raise ValueError
        except ValueError:
            raise invalid("网页访问地址须为 HTTP 或 HTTPS 且不能含登录凭据。") from None
        host = host or parsed.hostname
    check_host(host)
    fields = (
        host, string(payload, "protocol", "协议", 60, required=True),
        integer(payload, "port", "端口", maximum=65535),
        string(payload, "purpose", "入口用途", 300), url,
    )
    source = source_fields(payload) if {"source_document_id", "source_page"} & payload.keys() else None
    return fields, source


def save_system(conn, user, payload, ident=None):
    values = {
        "name": string(payload, "name", "系统名称", required=True),
        "description": string(payload, "description", "系统说明", 1500),
    }
    deployments = {}
    for deployment in items(payload, "deployments", "部署记录"):
        if not isinstance(deployment, dict):
            raise invalid("部署记录应为对象。")
        device_id = integer(deployment, "device_id", "部署设备", required=True)
        if device_id in deployments:
            raise invalid("同一设备只需登记一条部署，可在该部署下添加多个入口。")
        deployments[device_id] = (
            string(deployment, "note", "部署说明", 500),
            [service_entry(entry) for entry in items(deployment, "entries", "服务入口", 100)],
        )
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if ident is not None:
            ensure_record(conn, "systems", ident, "业务系统", 404)
        linked = {row["device_id"] for row in conn.execute(
            "SELECT device_id FROM deployments WHERE system_id = ?", (ident,),
        )} if ident is not None and "deployments" in payload else set()
        for device_id in deployments:
            ensure_linkable_device(conn, device_id, "部署设备", linked)
        saved_id = write_record(conn, "systems", ident, values)
        if "deployments" in payload:
            sources = defaultdict(deque)
            for row in conn.execute(
                """SELECT d.device_id, e.* FROM service_entries e JOIN deployments d ON e.deployment_id = d.id
                   WHERE d.system_id = ? ORDER BY e.id""", (saved_id,),
            ):
                key = tuple(row[field] for field in ("device_id", "host", "protocol", "port", "purpose", "url"))
                sources[key].append((row["source_document_id"], row["source_page"]))
            conn.execute("DELETE FROM deployments WHERE system_id = ?", (saved_id,))
            for device_id, (note, entries) in deployments.items():
                deployed_id = conn.execute(
                    "INSERT INTO deployments(system_id, device_id, note) VALUES (?, ?, ?)",
                    (saved_id, device_id, note),
                ).lastrowid
                values = []
                for fields, source in entries:
                    matches = sources.get((device_id, *fields))
                    previous = matches.popleft() if matches else (None, None)
                    if source is None:
                        source = previous
                    if source[0] != previous[0]:
                        ensure_device_source(conn, device_id, source[0])
                    values.append((deployed_id, *fields, *source))
                conn.executemany(
                    """INSERT INTO service_entries(deployment_id, host, protocol, port, purpose, url, source_document_id, source_page)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", values,
                )
        return next(system for system in catalog(conn, user)["systems"] if system["id"] == saved_id)


def save_document(conn, payload):
    values = {
        "title": string(payload, "title", "档案名称", required=True),
        "category": string(payload, "category", "档案类型", 100, required=True),
        "project_id": integer(payload, "project_id", "关联项目"),
        "device_id": integer(payload, "device_id", "关联设备"),
        "page": integer(payload, "page", "参考页码", maximum=9999),
        "note": string(payload, "note", "档案备注", 1000),
        "filename": string(payload, "filename", "原文件名", 240, required=True),
    }
    if (values["project_id"] is None) == (values["device_id"] is None):
        raise invalid("档案需关联一个项目或一台设备。")
    filename = values["filename"]
    suffix = extension(filename)
    if suffix not in FORMATS or any(ord(char) < 32 or char in "/\\" for char in filename):
        raise invalid("请选择 PDF、图片、Word 或 Excel 文件。")
    if values["page"] is not None and suffix != ".pdf":
        raise invalid("参考页码只适用于 PDF 档案。")
    encoded = payload.get("content_base64")
    if not isinstance(encoded, str) or len(encoded) > ((ATTACHMENT_LIMIT + 2) // 3) * 4:
        raise invalid("请选择不超过 8 MiB 的文件。")
    try:
        content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise invalid("无法读取文件内容。") from None
    if len(content) > ATTACHMENT_LIMIT:
        raise invalid("请选择不超过 8 MiB 的文件。")
    if not valid_attachment(content, suffix):
        raise invalid("文件内容无效或与扩展名不一致，请检查原件。")
    digest = hashlib.sha256(content).hexdigest()
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        if values["project_id"] is not None:
            ensure_record(conn, "projects", values["project_id"], "项目")
        else:
            ensure_record(conn, "devices", values["device_id"], "设备")
        conn.execute("INSERT OR IGNORE INTO files VALUES (?, ?)", (digest, content))
        ident = write_record(conn, "documents", None, dict(values, file_digest=digest))
    return dict(values, id=ident)
