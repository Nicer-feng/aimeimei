from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledger.data import ApiError, connect, delete_record, initialize, migrate_schema, set_device_archive
from ledger.ports import create_ports, delete_port, device_ports, edit_port, link_port, patrol_port_counts, unlink_port


class PhysicalPortsTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.data_dir = Path(directory.name)
        initialize(self.data_dir)
        self.conn = connect(self.data_dir)
        self.addCleanup(self.conn.close)
        self.admin = {"role": "admin"}
        self.reader = {"role": "reader", "unit_id": 2}

    def expect_error(self, status, operation, *args):
        with self.assertRaises(ApiError) as caught:
            operation(self.conn, *args)
        self.assertEqual(caught.exception.status, status)
        return str(caught.exception)

    def add(self, device, name, **values):
        rows = create_ports(self.conn, self.admin, device, {"name": name, **values})["ports"]
        return next(port["id"] for port in rows if port["name"] == name)

    def port(self, device, ident, user=None):
        rows = device_ports(self.conn, user or self.admin, device)["ports"]
        return next(port for port in rows if port["id"] == ident)

    def test_one_cable_is_symmetric_and_labels_follow_each_endpoint(self):
        left = self.add(3, "GE1", kind="copper", state="free")
        right = self.add(8, "GE2", kind="copper")
        spare = self.add(8, "GE3", kind="copper", state="free")
        link_port(self.conn, self.admin, left, {"peer_label": "待核目标", "label": "甲"})
        self.assertEqual(self.port(3, left)["state"], "pending")
        self.assertEqual(patrol_port_counts(self.conn, [3, 4]), {3: {"registered": 1, "unknown_peer": 1}})
        link_port(self.conn, self.admin, left, {"peer_port_id": right, "label": "甲", "peer_label": "乙"})
        from_left, from_right = self.port(3, left), self.port(8, right)
        self.assertEqual(from_left["cable"]["id"], from_right["cable"]["id"])
        self.assertEqual((from_right["cable"]["label"], from_right["cable"]["peer_label"]), ("乙", "甲"))
        self.assertEqual(from_left["cable"]["peer"]["rack_name"], "A02")
        self.assertEqual(from_right["cable"]["peer"]["rack_name"], "A01")
        self.assertEqual(patrol_port_counts(self.conn, [3, 8])[3]["unknown_peer"], 0)
        self.expect_error(409, link_port, self.admin, spare, {"peer_port_id": left})
        self.expect_error(400, link_port, self.admin, spare, {"peer_port_id": spare})
        self.expect_error(409, edit_port, self.admin, left, {"state": "free"})
        edit_port(self.conn, self.admin, left, {"group": "板 2"})
        self.assertEqual(self.port(3, left)["group"], "板 2")
        self.assertIn("物理线缆", self.expect_error(409, delete_record, "devices", 8))
        self.expect_error(409, delete_port, self.admin, right)
        set_device_archive(self.conn, self.admin, 3, True)
        self.assertTrue(self.port(8, right)["cable"]["peer"]["archived_at"])
        self.expect_error(409, link_port, self.admin, left, {"peer_port_id": right})
        unlink_port(self.conn, self.admin, right)
        self.assertEqual(self.port(8, right)["state"], "unknown")
        self.assertEqual(self.port(3, left)["state"], "unknown")
        delete_record(self.conn, "devices", 8)
        self.assertFalse(self.conn.execute("SELECT 1 FROM physical_ports WHERE device_id = 8").fetchone())
        self.assertFalse(self.conn.execute(
            "SELECT 1 FROM physical_cables WHERE id = ?", (from_left["cable"]["id"],),
        ).fetchone())

    def test_scope_redacts_entire_cross_site_cable_and_denies_writes(self):
        left = self.add(3, "GE1")
        right = self.add(5, "SECRET-PORT")
        link_port(self.conn, self.admin, left, {
            "peer_port_id": right, "label": "SECRET-LABEL-A", "peer_label": "SECRET-LABEL-B",
            "note": "SECRET-NOTE", "verified_on": "2026-11-25",
        })
        visible = self.port(3, left, self.reader)
        self.assertEqual(visible["state"], "connected")
        self.assertEqual(visible["cable"], {
            "id": None, "label": "", "peer_label": "", "note": "", "verified_on": None,
            "peer": None, "restricted": True,
        })
        self.expect_error(404, device_ports, self.reader, 5)
        self.expect_error(403, edit_port, self.reader, left, {"name": "GE2"})
        self.expect_error(403, link_port, self.reader, left, {"peer_port_id": right})
        self.expect_error(403, unlink_port, self.reader, left)
        self.assertEqual(self.port(3, left)["cable"]["peer"]["port_id"], right)

    def test_bulk_ingest_rolls_back_on_conflict_and_retains_idle_states(self):
        payload = {"ports": [
            {"name": "Gi10", "label": "本端旧签", "peer_label": "待核对端"},
            {"name": "Gi2", "state": "free"}, {"name": "Gi1"},
        ]}
        created = create_ports(self.conn, self.admin, 3, payload)["ports"]
        self.assertEqual([(p["name"], p["state"]) for p in created],
                         [("Gi1", "unknown"), ("Gi2", "free"), ("Gi10", "pending")])
        self.assertEqual(created[-1]["cable"]["peer_label"], "待核对端")
        self.expect_error(409, create_ports, self.admin, 3, {
            "ports": [{"name": "Gi3", "peer_label": "待核"}, {"name": "gI2"}],
        })
        self.assertEqual(device_ports(self.conn, self.admin, 3)["ports"], created)
        self.expect_error(400, create_ports, self.admin, 3, {"name": "Gi4", "state": "free", "peer_label": "冲突"})

    def test_qinglan_demo_upgrades_once_and_stays_in_sample_room(self):
        source = device_ports(self.conn, self.admin, 2)["ports"]
        self.assertEqual(len(source), 24)
        self.assertTrue(all(port["demo"] for port in source))
        self.assertEqual({port["state"] for port in source}, {"unknown", "free", "pending", "connected"})
        self.assertEqual(source[0]["name"], "GE1/0/01")
        self.assertEqual(source[0]["cable"]["peer"]["rack_name"], "A02")
        self.assertEqual(source[0]["cable"]["peer"]["port_name"], "GE0/1")
        self.assertEqual(device_ports(self.conn, self.admin, 5)["ports"], [])
        unlink_port(self.conn, self.admin, source[0]["id"])
        delete_port(self.conn, self.admin, source[0]["id"])
        migrate_schema(self.conn)
        initialize(self.data_dir)
        self.assertEqual(len(device_ports(self.conn, self.admin, 2)["ports"]), 23)
