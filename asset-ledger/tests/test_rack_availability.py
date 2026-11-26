import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlencode

from ledger.data import ApiError, connect, initialize, rack_availability, save_device, validate_rack_position


class RackAvailabilityTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = Path(directory.name)
        initialize(data_dir)
        self.conn = connect(data_dir)
        self.addCleanup(self.conn.close)
        self.admin = {"role": "admin"}
        self.reader = {"role": "reader", "unit_id": 2}
        with self.conn:
            self.rack = self.conn.execute(
                "INSERT INTO racks(room_id, name, height) VALUES (1, '上架验收柜', 12)"
            ).lastrowid
            self.small_rack = self.conn.execute(
                "INSERT INTO racks(room_id, name, height) VALUES (1, '矮柜', 1)"
            ).lastrowid
            self.private_rack = self.conn.execute(
                "INSERT INTO racks(room_id, name, height) VALUES (2, '其他辖区柜', 12)"
            ).lastrowid
        self.add_device("TEST-FULL", "front", 1, depth="full", height=2)
        self.add_device("TEST-UNKNOWN", "rear", 4, depth="unknown")
        self.add_device("TEST-REAR-HALF", "rear", 6)
        self.add_device("TEST-FRONT-HALF", "front", 8)
        self.legacy = self.add_device("TEST-LEGACY-FRONT", "front", 10, height=2)
        legacy_rear = self.add_device("TEST-LEGACY-REAR", "rear", 10)
        with self.conn:
            # 模拟启用深度校验前已经重叠的记录。
            self.conn.execute("UPDATE devices SET mount_depth = 'unknown' WHERE id IN (?, ?)",
                              (self.legacy["id"], legacy_rear["id"]))
        self.legacy = self.conn.execute("SELECT * FROM devices WHERE id = ?", (self.legacy["id"],)).fetchone()

    def add_device(self, code, face, start, depth="half", height=1):
        return save_device(self.conn, self.admin, {
            "code": code, "name": code, "type": "测试设备", "room_id": 1, "rack_id": self.rack,
            "face": face, "u_start": start, "u_height": height, "mount_depth": depth,
        })

    def availability(self, user=None, **options):
        query = urlencode({"height": 1, "depth": "half", "face": "any", **options})
        return rack_availability(self.conn, user or self.admin, query)["racks"]

    def accepted_by_writer(self, face, start, height, depth, previous=None):
        position = {"room_id": 1, "rack_id": self.rack, "face": face, "u_start": start,
                    "u_height": height, "mount_depth": depth}
        try:
            validate_rack_position(self.conn, position, previous["id"] if previous else None, previous)
        except ApiError:
            return False
        return True

    def test_slots_describe_both_faces_without_mutation(self):
        changes = self.conn.total_changes
        [rack] = self.availability(rack_id=self.rack)
        self.assertEqual((rack["id"], rack["room_id"], rack["height"]), (self.rack, 1, 12))
        front = {slot["u"]: slot["state"] for slot in rack["faces"]["front"]["slots"]}
        rear = {slot["u"]: slot["state"] for slot in rack["faces"]["rear"]["slots"]}
        self.assertEqual(front, {
            1: "occupied", 2: "occupied", 3: "free", 4: "unknown", 5: "free", 6: "half",
            7: "free", 8: "occupied", 9: "free", 10: "occupied", 11: "occupied", 12: "free",
        })
        self.assertEqual(rear, {
            1: "full", 2: "full", 3: "free", 4: "occupied", 5: "free", 6: "occupied",
            7: "free", 8: "half", 9: "free", 10: "occupied", 11: "unknown", 12: "free",
        })
        self.assertEqual(rack["faces"]["front"]["starts"], [3, 5, 6, 7, 9, 12])
        self.assertEqual(rack["faces"]["rear"]["starts"], [3, 5, 7, 8, 9, 12])
        self.assertEqual(self.conn.total_changes, changes)

    def test_each_available_start_also_passes_write_validation(self):
        for height in (1, 2, 3, 12, 13):
            for depth in ("full", "half", "unknown"):
                for previous_device in (None, self.legacy):
                    extra = {"exclude_device_id": previous_device["id"]} if previous_device else {}
                    with self.subTest(height=height, depth=depth, excluded=extra):
                        [rack] = self.availability(rack_id=self.rack, height=height, depth=depth, **extra)
                        for face in ("front", "rear"):
                            expected = [start for start in range(1, 13) if self.accepted_by_writer(
                                face, start, height, depth, previous_device,
                            )]
                            self.assertEqual(rack["faces"][face]["starts"], expected)

    def test_exclusion_keeps_exact_legacy_position_without_allowing_a_move(self):
        [rack] = self.availability(rack_id=self.rack, height=2, exclude_device_id=self.legacy["id"])
        self.assertIn(10, rack["faces"]["front"]["starts"])
        self.assertNotIn(9, rack["faces"]["front"]["starts"])
        self.assertNotIn(10, rack["faces"]["rear"]["starts"])
        [changed_height] = self.availability(rack_id=self.rack, height=1, exclude_device_id=self.legacy["id"])
        self.assertNotIn(10, changed_height["faces"]["front"]["starts"])
        self.assertIn(11, changed_height["faces"]["front"]["starts"])

    def test_reader_only_sees_racks_in_their_jurisdiction_including_empty_results(self):
        visible = {rack["id"]: rack for rack in self.availability(self.reader, height=2, depth="full")}
        self.assertIn(self.rack, visible)
        self.assertNotIn(self.private_rack, visible)
        self.assertTrue(all(rack["room_id"] == 1 for rack in visible.values()))
        for face in ("front", "rear"):
            self.assertEqual(visible[self.small_rack]["faces"][face]["starts"], [])
            self.assertNotIn("slots", visible[self.small_rack]["faces"][face])
        self.assertEqual(self.availability(room_id=2, rack_id=self.private_rack)[0]["id"], self.private_rack)

        private_device = self.conn.execute("SELECT id FROM devices WHERE room_id = 2 LIMIT 1").fetchone()["id"]
        for selector in ({"room_id": 2}, {"rack_id": self.private_rack}, {"exclude_device_id": private_device}):
            with self.subTest(selector=selector), self.assertRaises(ApiError) as forbidden:
                self.availability(self.reader, **selector)
            self.assertEqual(forbidden.exception.status, 404)

    def test_single_face_limits_candidates_and_rejects_invalid_query(self):
        [rack] = self.availability(rack_id=self.rack, face="rear")
        self.assertEqual(rack["faces"]["front"]["starts"], [])
        self.assertEqual(rack["faces"]["rear"]["starts"], [3, 5, 7, 8, 9, 12])
        self.assertEqual(len(rack["faces"]["front"]["slots"]), 12)

        for query in ("height=0", "height=256", "height=1&height=2", "height=1&face=side",
                      "height=1&depth=long", "height=1&scope=all", "depth=half"):
            with self.subTest(query=query), self.assertRaises(ApiError) as invalid:
                rack_availability(self.conn, self.admin, query)
            self.assertEqual(invalid.exception.status, 400)
