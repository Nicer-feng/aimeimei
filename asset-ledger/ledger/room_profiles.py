"""机房平面、比例和可选底图。"""

import base64
import binascii
import json
import math
import struct

from .attachment_formats import JPEG_FRAME_MARKERS, valid_attachment
from .data import ApiError, invalid, string, visible_sites


KINDS = {"wall", "entrance", "aisle", "equipment"}
MAX_FEATURES = 100
MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_SIDE = 1600
DEMO_FEATURES = [
    {"kind": "wall", "label": "", "from": [0.06, 0.08], "to": [0.94, 0.08]},
    {"kind": "wall", "label": "", "from": [0.94, 0.08], "to": [0.94, 0.92]},
    {"kind": "wall", "label": "", "from": [0.06, 0.08], "to": [0.06, 0.68]},
    {"kind": "entrance", "label": "演示入口", "from": [0.06, 0.70], "to": [0.06, 0.88]},
    {"kind": "aisle", "label": "中央走道", "from": [0.14, 0.43], "to": [0.86, 0.57]},
    {"kind": "equipment", "label": "演示空调区", "from": [0.83, 0.14], "to": [0.91, 0.27]},
]


def migrate_room_profiles(conn):
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_floor_profiles (
                room_id INTEGER PRIMARY KEY REFERENCES rooms(id) ON DELETE CASCADE,
                revision INTEGER NOT NULL CHECK (revision > 0),
                data_json TEXT NOT NULL,
                image_name TEXT,
                image_mime TEXT,
                image BLOB,
                CHECK ((image_name IS NULL) = (image IS NULL) AND (image_mime IS NULL) = (image IS NULL))
            )
        """)


def _room(conn, user, room_id):
    row = conn.execute("""
        SELECT rooms.site_id, rooms.name, sites.name AS site_name, units.name AS unit_name
        FROM rooms JOIN sites ON sites.id = rooms.site_id JOIN units ON units.id = sites.unit_id
        WHERE rooms.id = ?
    """, (room_id,)).fetchone()
    if row is None or row["site_id"] not in visible_sites(conn, user):
        raise ApiError(404, "机房不存在。")
    return row


def _floor(conn, room_id):
    return conn.execute("""
        SELECT revision, data_json, image_name FROM room_floor_profiles WHERE room_id = ?
    """, (room_id,)).fetchone()


def _record(row):
    return {
        **json.loads(row["data_json"]),
        "revision": row["revision"],
        "illustrative": False,
        "reference": {"name": row["image_name"]} if row["image_name"] else None,
    }


def read_room_profile(conn, user, room_id):
    room = _room(conn, user, room_id)
    row = _floor(conn, room_id)
    if row:
        return _record(row)
    if (room["name"], room["site_name"], room["unit_name"]) == ("综合机房", "青岚站", "演示东区"):
        return {"width_m": 5.6, "depth_m": 3.5, "features": DEMO_FEATURES, "racks": [],
                "calibration": None, "revision": 0, "illustrative": True, "reference": None}
    return None


def read_room_profile_image(conn, user, room_id):
    _room(conn, user, room_id)
    row = conn.execute("SELECT image_mime, image FROM room_floor_profiles WHERE room_id = ?", (room_id,)).fetchone()
    if row is None or row["image"] is None:
        raise ApiError(404, "该机房暂无底图。")
    return row["image_mime"], row["image"]


def _number(value, lower, upper, label):
    if type(value) not in (int, float) or not lower <= value <= upper:
        raise invalid(f"{label}超出允许范围。")
    return round(value, 5)


def _point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise invalid("定位点无效。")
    return [_number(axis, 0, 1, "定位点") for axis in value]


def _segment(raw, *, area=False):
    start, end = _point(raw.get("from")), _point(raw.get("to"))
    if math.dist(start, end) < 0.003 or (area and min(abs(a - b) for a, b in zip(start, end)) < 0.003):
        raise invalid("请为线段选取不同的端点，为区域选取两个对角。")
    return {"from": start, "to": end}


def _features(payload):
    raw = payload.get("features")
    if not isinstance(raw, list) or len(raw) > MAX_FEATURES:
        raise invalid("平面标记最多支持 100 项。")
    result = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("kind"), str) or item["kind"] not in KINDS:
            raise invalid("平面标记类型无效。")
        kind = item["kind"]
        result.append({"kind": kind, "label": string(item, "label", "标记名称", 40),
                       **_segment(item, area=kind in ("aisle", "equipment"))})
    return result


def _rack_points(conn, room_id, payload):
    raw = payload.get("racks", [])
    if not isinstance(raw, list) or len(raw) > 240:
        raise invalid("机柜定位列表无效。")
    available = {row["id"] for row in conn.execute("SELECT id FROM racks WHERE room_id = ?", (room_id,))}
    result = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or type(item.get("rack_id")) is not int:
            raise invalid("机柜定位无效。")
        rack_id = item["rack_id"]
        if rack_id not in available or rack_id in seen:
            raise invalid("自定义机柜定位须属于当前机房且不能重复。")
        x, y = _point([item.get("x"), item.get("y")])
        result.append({"rack_id": rack_id, "x": x, "y": y})
        seen.add(rack_id)
    return result


def _calibration(payload):
    raw = payload.get("calibration")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise invalid("比例校准无效。")
    return {**_segment(raw), "length_m": _number(raw.get("length_m"), 0.1, 100, "校准距离")}


def _image_dimensions(content, suffix):
    if suffix == ".png":
        return struct.unpack_from(">II", content, 16)
    offset = 2
    while offset + 4 <= len(content):
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        marker = content[offset]
        if marker in JPEG_FRAME_MARKERS:
            return struct.unpack_from(">HH", content, offset + 4)
        offset += 1 + int.from_bytes(content[offset + 1:offset + 3], "big")
    return 0, 0


def _reference(raw):
    if raw is None:
        return None, None, None
    if not isinstance(raw, dict):
        raise invalid("底图信息无效。")
    name = string(raw, "name", "底图文件名", 180, required=True)
    encoded = raw.get("data")
    if not isinstance(encoded, str) or len(encoded) > 4 * math.ceil(MAX_IMAGE_BYTES / 3):
        raise invalid("底图超过 2 MB。")
    try:
        image = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        raise invalid("底图编码无效。") from None
    suffix, mime = (".png", "image/png") if image.startswith(b"\x89PNG") else (".jpg", "image/jpeg")
    if len(image) > MAX_IMAGE_BYTES or not valid_attachment(image, suffix):
        raise invalid("请提供有效的 JPEG 或 PNG 底图。")
    try:
        width, height = _image_dimensions(image, suffix)
    except (IndexError, struct.error):
        raise invalid("底图尺寸无效。") from None
    if not all(1 <= axis <= MAX_IMAGE_SIDE for axis in (width, height)):
        raise invalid("底图长边不能超过 1600 像素。")
    return name, mime, image


def save_room_profile(conn, user, room_id, payload):
    if user["role"] != "admin":
        raise ApiError(403, "当前账号只有辖区内的查阅权限。")
    revision = payload.get("revision")
    if type(revision) is not int or revision < 0:
        raise invalid("请先读取当前机房平面。")
    reference = _reference(payload["reference"]) if "reference" in payload else None
    width = _number(payload.get("width_m"), 2, 100, "机房宽度")
    depth = _number(payload.get("depth_m"), 2, 100, "机房进深")
    with conn:
        conn.execute("BEGIN IMMEDIATE")
        _room(conn, user, room_id)
        row = _floor(conn, room_id)
        if revision != (row["revision"] if row else 0):
            raise ApiError(409, "机房平面已被更新，请重新打开后再编辑。")
        data = {"width_m": width, "depth_m": depth, "features": _features(payload),
                "racks": _rack_points(conn, room_id, payload), "calibration": _calibration(payload)}
        blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        if row:
            conn.execute("UPDATE room_floor_profiles SET revision = revision + 1, data_json = ? WHERE room_id = ?",
                         (blob, room_id))
        else:
            conn.execute("INSERT INTO room_floor_profiles(room_id, revision, data_json) VALUES (?, 1, ?)",
                         (room_id, blob))
        if reference is not None:
            conn.execute("UPDATE room_floor_profiles SET image_name = ?, image_mime = ?, image = ? WHERE room_id = ?",
                         (*reference, room_id))
        return _record(_floor(conn, room_id))
