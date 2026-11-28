"""按线标或机柜位置查找已登记的物理端口。"""

import re
from unicodedata import normalize

from .data import string, visible_sites
from .ports import natural_order


MAX_RESULTS = 75
SEPARATORS = r"[\s\-–—]+"
LOCATION = re.compile(
    rf"(?P<rack>.+?){SEPARATORS}(?:(?P<face>正面|背面|front|rear){SEPARATORS})?"
    rf"(?:u\s*(?P<leading>[0-9]{{1,3}})|(?P<trailing>[0-9]{{1,3}})\s*u)"
    rf"(?:{SEPARATORS}(?P<port>.+))?"
)
PORT_NUMBER = re.compile(r"([0-9]{1,4})\s*(?:口)?")
PORT_TAIL = re.compile(r"([0-9]+)\s*(?:口)?$")
FACES = {"正面": "front", "背面": "rear", "front": "front", "rear": "rear"}
ENDPOINT_FIELDS = (
    "device_id", "device_name", "device_code", "port_id", "port_name", "rack_id", "rack_name",
    "room_id", "room_name", "site_name", "face", "u_start", "u_height", "archived_at",
)


def search_text(value):
    return normalize("NFKC", value or "").strip().casefold()


def match_position(port, query, location):
    name = search_text(port["port_name"])
    if location is None:
        return name == query

    rack = search_text(location["rack"])
    if (not port["rack_id"] or port["u_start"] is None or port["u_height"] is None
            or search_text(port["rack_name"]) != rack):
        return False
    face = FACES.get(location["face"])
    if face is not None and port["face"] != face:
        return False
    slot = int(location["leading"] or location["trailing"])
    if not port["u_start"] <= slot < port["u_start"] + port["u_height"]:
        return False
    requested = search_text(location["port"])
    if not requested or requested == name:
        return True
    number = PORT_NUMBER.fullmatch(requested)
    if number is None:
        return False
    tail = PORT_TAIL.search(name)
    return tail is not None and int(tail[1]) == int(number[1])


def endpoint(row, *, redact=False):
    return {**{key: row[key] for key in ENDPOINT_FIELDS}, "label": "" if redact else (row["label"] or "")}


def state_for(row, peer):
    if row["cable_id"] is None:
        return row["base_state"]
    if row["peer_port_id"] is None:
        return "pending"
    return "connected" if peer is not None else "restricted"


def match_rank(row, peer, state, query, location):
    if state != "restricted":
        labels = [search_text(row["label"])]
        if state == "pending":
            labels.append(search_text(row["pending_peer_label"]))
        elif peer is not None and peer["archived_at"]:
            # 仍可用已归档对端的可见线标找回当前在册端，且跳转落在在册设备。
            labels.append(search_text(peer["label"]))
        if query in labels:
            return 0, "label"
        if any(query in label for label in labels):
            label_rank = 2
        else:
            label_rank = None
    else:
        label_rank = None
    if match_position(row, query, location):
        return 1, "position"
    return (label_rank, "label") if label_rank is not None else (None, "")


def search_order(row, rank, preferred_room_id):
    return (
        rank, row["room_id"] != preferred_room_id,
        natural_order(row["site_name"]), natural_order(row["room_name"]), natural_order(row["rack_name"] or ""),
        -(row["u_start"] or 0), natural_order(row["device_code"]), natural_order(row["port_name"]), row["port_id"],
    )


def visible_ports(conn, sites):
    visible = {}
    site_ids = sorted(sites)
    # 分批绑定站点，兼容旧 SQLite 的参数上限。
    for offset in range(0, len(site_ids), 500):
        batch = site_ids[offset:offset + 500]
        placeholders = ", ".join("?" for _ in batch)
        visible.update((row["port_id"], row) for row in conn.execute(
            f"""SELECT p.id AS port_id, p.name AS port_name, p.base_state,
                       d.id AS device_id, d.name AS device_name, d.code AS device_code, d.archived_at,
                       d.rack_id, d.room_id, d.face, d.u_start, d.u_height,
                       rack.name AS rack_name, room.name AS room_name, site.name AS site_name,
                       own.cable_id, own.label, far.port_id AS peer_port_id, c.pending_peer_label
                FROM physical_ports p JOIN devices d ON d.id = p.device_id
                JOIN rooms room ON room.id = d.room_id JOIN sites site ON site.id = room.site_id
                LEFT JOIN racks rack ON rack.id = d.rack_id
                LEFT JOIN physical_cable_ends own ON own.port_id = p.id
                LEFT JOIN physical_cables c ON c.id = own.cable_id
                LEFT JOIN physical_cable_ends far ON far.cable_id = own.cable_id AND far.side <> own.side
                WHERE site.id IN ({placeholders})""",
            batch,
        ))
    return visible


def search_cables(conn, user, query, preferred_room_id=None):
    query = search_text(string({"query": query}, "query", "搜索词", maximum=180))
    if not query:
        return {"results": [], "total": 0}
    sites = visible_sites(conn, user)
    if not sites:
        return {"results": [], "total": 0}
    location = LOCATION.fullmatch(query)
    visible = visible_ports(conn, sites)
    matches = {}
    for row in visible.values():
        if row["archived_at"]:
            continue
        peer = visible.get(row["peer_port_id"])
        state = state_for(row, peer)
        rank, match = match_rank(row, peer, state, query, location)
        if rank is None:
            continue
        key = ("cable", row["cable_id"]) if state == "connected" else ("port", row["port_id"])
        order = search_order(row, rank, preferred_room_id)
        if key not in matches or order < matches[key][0]:
            matches[key] = order, row, peer, state, match

    results = []
    for _, row, peer, state, match in sorted(matches.values(), key=lambda value: value[0])[:MAX_RESULTS]:
        peer_label = ""
        if state == "pending":
            peer_label = row["pending_peer_label"]
        elif peer is not None:
            peer_label = peer["label"] or ""
        results.append({
            "local": endpoint(row, redact=state == "restricted"), "peer": endpoint(peer) if peer is not None else None,
            "state": state, "peer_label": peer_label, "match": match,
        })
    return {"results": results, "total": len(matches)}
