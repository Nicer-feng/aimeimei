import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledger.data import ApiError, catalog, connect, initialize, migrate_schema, save_device


class OperatingStatusTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = Path(directory.name)
        initialize(data_dir)
        self.conn = connect(data_dir)
        self.addCleanup(self.conn.close)
        self.admin = {"role": "admin"}
        self.payload = {"code": "TEST-STATUS", "name": "状态验收设备", "type": "测试", "room_id": 1}

    def test_fresh_default_and_legacy_migration(self):
        self.assertTrue(all(device["operating_status"] == "unknown" for device in catalog(self.conn, self.admin)["devices"]))
        legacy = sqlite3.connect(":memory:")
        self.addCleanup(legacy.close)
        legacy.row_factory = sqlite3.Row
        legacy.executescript("""
            CREATE TABLE devices (
                id INTEGER PRIMARY KEY, rack_id INTEGER, face TEXT, u_start INTEGER,
                mount_depth TEXT NOT NULL, verified_on TEXT
            );
            INSERT INTO devices VALUES (1, 1, 'front', 2, 'full', '2025-01-01');
        """)
        migrate_schema(legacy)
        self.assertEqual(tuple(legacy.execute("SELECT mount_depth, verified_on, operating_status FROM devices").fetchone()),
                         ("full", "2025-01-01", "unknown"))
        with legacy:
            legacy.execute("UPDATE devices SET operating_status = 'running' WHERE id = 1")
        migrate_schema(legacy)
        self.assertEqual(legacy.execute("SELECT operating_status FROM devices").fetchone()[0], "running")
        with self.assertRaises(sqlite3.IntegrityError), legacy:
            legacy.execute("UPDATE devices SET operating_status = 'invalid' WHERE id = 1")

    def test_manual_status_and_omitted_patch(self):
        item = save_device(self.conn, self.admin, self.payload)
        self.assertEqual(item["operating_status"], "unknown")
        for status in ("running", "disabled", "unpowered", "unknown"):
            changed = save_device(self.conn, self.admin, {**self.payload, "operating_status": status}, item["id"])
            self.assertEqual(changed["operating_status"], status)
            patched = save_device(self.conn, self.admin, {**self.payload, "name": "编辑设备名称"}, item["id"])
            self.assertEqual(patched["operating_status"], status)
        reader = {"role": "reader", "unit_id": 2}
        reader_item = next(device for device in catalog(self.conn, reader)["devices"] if device["id"] == item["id"])
        self.assertEqual(reader_item["operating_status"], "unknown")

    def test_invalid_status_rejected_without_overwriting(self):
        item = save_device(self.conn, self.admin, {**self.payload, "operating_status": "running"})
        for invalid in (None, "offline", "", False, ["running"]):
            with self.subTest(invalid=invalid), self.assertRaises(ApiError) as error:
                save_device(self.conn, self.admin, {**self.payload, "operating_status": invalid}, item["id"])
            self.assertEqual(error.exception.status, 400)
        self.assertEqual(self.conn.execute("SELECT operating_status FROM devices WHERE id = ?", (item["id"],)).fetchone()[0],
                         "running")
