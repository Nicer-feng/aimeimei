from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledger.data import ApiError, connect, initialize
from ledger.patrol import initialize_patrol, record_patrol, room_patrol
from ledger.ports import create_ports, link_port


class RoomPatrolTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = Path(directory.name)
        initialize(data_dir)
        self.conn = connect(data_dir)
        self.addCleanup(self.conn.close)
        initialize_patrol(self.conn)
        self.admin = {"role": "admin", "username": "admin"}
        self.reader = {"role": "reader", "unit_id": 2, "username": "巡检查阅"}

    def device(self, device_id):
        return next(device for device in room_patrol(self.conn, self.reader, 1)["devices"] if device["id"] == device_id)

    def record(self, device_id, kind="device", note="", **extra):
        return record_patrol(self.conn, self.admin, {"room_id": 1, "device_id": device_id, "kind": kind,
                                                    "note": note, **extra})

    def assert_status(self, status, callback, *args, **kwargs):
        with self.assertRaises(ApiError) as caught:
            callback(*args, **kwargs)
        self.assertEqual(caught.exception.status, status)

    def test_record_persists_and_keeps_manual_operating_status_separate(self):
        device_before = self.device(1)
        self.assertTrue(device_before["verified_on"])
        self.assertTrue(device_before["pending"])
        self.record(1, note="第一次核实")
        record = self.record(1, note="  已核对设备铭牌\n记录现场  ", checked_by="另一个人")
        initialize_patrol(self.conn)
        self.assertEqual(record["checked_by"], "admin")
        self.assertIsNotNone(datetime.fromisoformat(record["checked_at"]).tzinfo)
        self.assertEqual(record["note"], "已核对设备铭牌\n记录现场")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM device_patrol_checks").fetchone()[0], 2)
        device_after = self.device(1)
        self.assertEqual(device_after["checks"]["device"], record)
        self.assertFalse(device_after["pending"])
        self.assertEqual(device_after["operating_status"], device_before["operating_status"])
        self.assertEqual(device_after["verified_on"], device_before["verified_on"])

    def test_missing_positions_and_peers_stay_pending_until_ledger_updates(self):
        self.assertFalse(self.device(4)["missing_u"])  # 已登记为值班台设备。
        with self.conn:
            self.conn.execute("UPDATE devices SET workstation = '' WHERE id = 4")
        self.assertTrue(self.device(4)["missing_u"])
        self.assert_status(400, self.record, 4, "placement")
        note = self.record(4, "placement", "已找到设备，等待登记柜位")
        self.assertEqual(self.device(4)["checks"]["placement"], note)
        self.assertTrue(self.device(4)["missing_u"])
        with self.conn:
            self.conn.execute("UPDATE devices SET rack_id = 1, face = 'front', u_start = 1, u_height = 1 WHERE id = 4")
        self.assertFalse(self.device(4)["missing_u"])
        self.assert_status(409, self.record, 4, "placement", "位置已登记")

        self.assertEqual(self.device(3)["port_count"], 0)
        port_id = create_ports(self.conn, self.admin, 3, {"name": "P1", "peer_label": "配电管理"})["ports"][0]["id"]
        peer_id = create_ports(self.conn, self.admin, 7, {"name": "P1"})["ports"][0]["id"]
        self.assertEqual(self.device(3)["missing_peers"], 1)
        note = self.record(3, "ports", "对端标签需现场复核")
        self.assertEqual(self.device(3)["checks"]["ports"], note)
        self.assertEqual(self.device(3)["missing_peers"], 1)
        link_port(self.conn, self.admin, port_id, {"peer_port_id": peer_id})
        self.assertEqual(self.device(3)["missing_peers"], 0)
        self.assert_status(409, self.record, 3, "ports", "已看到对端")

    def test_scope_and_stale_targets(self):
        self.assert_status(404, room_patrol, self.conn, self.reader, 2)
        self.assert_status(403, record_patrol, self.conn, self.reader,
                           {"room_id": 1, "device_id": 1, "kind": "device", "note": ""})
        self.assert_status(409, self.record, 5)
        self.assert_status(400, self.record, 1, "unsupported")
        with self.conn:
            self.conn.execute("UPDATE devices SET archived_at = ? WHERE id = 1", ("2026-12-01",))
        self.assert_status(404, self.record, 1)
        self.assertNotIn(1, {device["id"] for device in room_patrol(self.conn, self.reader, 1)["devices"]})
