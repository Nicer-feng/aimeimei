from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledger.cable_search import MAX_RESULTS, search_cables
from ledger.data import connect, initialize, save_device, save_rack, save_room, set_device_archive
from ledger.ports import create_ports, device_ports, link_port


class CableSearchTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = Path(directory.name)
        initialize(data_dir)
        self.conn = connect(data_dir)
        self.addCleanup(self.conn.close)
        self.admin = {"role": "admin"}
        self.reader = {"role": "reader", "unit_id": 2}

    def search(self, query, *, user=None, preferred_room_id=None):
        return search_cables(self.conn, user or self.admin, query, preferred_room_id)

    def port(self, device_id, name, **fields):
        result = create_ports(self.conn, self.admin, device_id, {"name": name, **fields})
        return next(port["id"] for port in result["ports"] if port["name"] == name)

    def connect_ports(self, port, peer, label, peer_label):
        link_port(self.conn, self.admin, port, {
            "peer_port_id": peer, "label": label, "peer_label": peer_label,
        })

    def test_complete_and_partial_labels_keep_matching_side_and_deduplicate(self):
        source = device_ports(self.conn, self.admin, 2)["ports"][0]["id"]
        left = self.search("演示-QL-C01-A")["results"][0]
        right = self.search("演示-ql-c01-b")["results"][0]
        self.assertEqual((left["local"]["port_id"], right["peer"]["port_id"]), (source, source))
        self.assertEqual(left["peer"]["port_id"], right["local"]["port_id"])
        self.assertNotEqual(right["local"]["port_id"], source)
        self.assertEqual((left["local"]["rack_name"], right["local"]["rack_name"]), ("A01", "A02"))
        partial = self.search("QL-C01")
        self.assertEqual((partial["total"], partial["results"][0]["match"]), (1, "label"))
        self.assertEqual(self.search("QL-C01%")["total"], 0)
        pending = self.search("A03-旧标签-11")["results"][0]
        self.assertIsNone(pending["peer"])
        self.assertEqual((pending["state"], pending["peer_label"]), ("pending", "演示-A03-旧标签-11"))

    def test_coordinates_use_mounted_span_face_and_full_port_name(self):
        room = save_room(self.conn, self.admin, {"site_id": 1, "name": "端口验证机房"})
        rack = save_rack(self.conn, self.admin, {"room_id": room["id"], "name": "A01", "height": 42})
        device = {
            "code": "PORT-TEST", "name": "端口验证设备", "type": "交换机", "room_id": room["id"], "rack_id": rack["id"],
            "face": "front", "u_start": 32, "u_height": 3, "mount_depth": "half",
        }
        front = save_device(self.conn, self.admin, device)["id"]
        rear = save_device(self.conn, self.admin, {**device, "code": "PORT-REAR", "face": "rear"})["id"]
        first_card = self.port(front, "GE1/0/20", group="1号卡", state="free")
        second_card = self.port(front, "GE2/0/20", group="2号卡", state="free")
        rear_port = self.port(rear, "Ethernet 1/20")
        self.port(front, "GE3/0/21", group="3号卡", position=20)
        self.port(front, "UPLINK", group="光口", position=20)
        for query in ("A01-33U-20口", "A01 U33 20", "Ａ０１—３３Ｕ—２０口"):
            with self.subTest(query=query):
                results = self.search(query)["results"]
                self.assertEqual({r["local"]["port_id"] for r in results}, {first_card, second_card, rear_port})
                self.assertTrue(all(r["match"] == "position" for r in results))
        front_results = self.search("A01 正面 U33 20口")["results"]
        self.assertEqual({r["local"]["port_id"] for r in front_results}, {first_card, second_card})
        self.assertTrue(all(r["state"] == "free" and r["peer"] is None for r in front_results))
        self.assertEqual(self.search("A01 背面 U33 Ethernet 1/20")["results"][0]["local"]["port_id"], rear_port)
        self.assertEqual(self.search("GE1/0/20", preferred_room_id=room["id"])["results"][0]["local"]["port_id"], first_card)
        self.assertEqual(self.search("A01 正面 U35 20口")["total"], 0)

    def test_exact_labels_first_and_current_room_breaks_ties(self):
        one = self.port(4, "P1", peer_label="留档", label="柜间专线")
        two = self.port(5, "P2", peer_label="留档", label="柜间专线")
        self.port(5, "P3", peer_label="留档", label="柜间专线新编号")
        results = self.search("柜间专线", preferred_room_id=2)["results"]
        self.assertEqual([r["local"]["port_id"] for r in results[:2]], [two, one])
        self.assertEqual(len(results), 3)

    def test_hidden_labels_cannot_match_and_restricted_position_is_redacted(self):
        one = self.port(3, "EXAMPLE-GE1")
        two = self.port(5, "HIDDEN-GE2")
        self.connect_ports(one, two, "LOCAL-LABEL-1", "HIDDEN-FAR-LABEL")
        for query in ("LOCAL-LABEL", "HIDDEN-FAR-LABEL", "HIDDEN-GE2"):
            self.assertEqual(self.search(query, user=self.reader), {"results": [], "total": 0})
        visible = self.search("EXAMPLE-GE1", user=self.reader)["results"][0]
        self.assertEqual((visible["state"], visible["local"]["port_id"]), ("restricted", one))
        self.assertEqual((visible["local"]["label"], visible["peer_label"], visible["peer"]), ("", "", None))
        self.assertEqual(self.search("HIDDEN-FAR-LABEL")["results"][0]["peer"]["port_id"], one)

    def test_archived_port_never_leads_but_can_appear_as_visible_peer(self):
        one = self.port(3, "LOCAL-GE1")
        two = self.port(4, "OLD-GE2")
        self.connect_ports(one, two, "当前线标", "旧线标")
        set_device_archive(self.conn, self.admin, 4, True)
        self.assertEqual(self.search("OLD-GE2")["total"], 0)
        result = self.search("旧线标")["results"][0]
        self.assertEqual((result["local"]["port_id"], result["peer"]["port_id"]), (one, two))
        self.assertTrue(result["peer"]["archived_at"])

    def test_result_limit_does_not_reduce_unique_total(self):
        count = MAX_RESULTS + 1
        create_ports(self.conn, self.admin, 4, {
            "ports": [{"name": f"Port-{index}", "peer_label": "候选线标"} for index in range(count)],
        })
        result = self.search("候选线标")
        self.assertEqual(len(result["results"]), MAX_RESULTS)
        self.assertEqual(result["total"], count)
