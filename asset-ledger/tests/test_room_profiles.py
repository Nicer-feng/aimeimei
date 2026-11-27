import base64
from pathlib import Path
import tempfile
import unittest

from ledger.data import ApiError, connect, initialize
from ledger.room_profiles import read_room_profile, read_room_profile_image, save_room_profile


PNG_PIXEL = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4//8/AAX+Av4N70a4AAAAAElFTkSuQmCC"


class RoomProfileTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        initialize(root)
        self.conn = connect(root)
        self.addCleanup(self.conn.close)
        self.admin = {"role": "admin"}
        self.reader = {"role": "reader", "unit_id": 2}
        self.other = {"role": "reader", "unit_id": 9999}
        self.profile = {
            "revision": 0,
            "width_m": 5.6,
            "depth_m": 4.0,
            "features": [{"kind": "entrance", "label": "西门", "from": [0.05, 0.7], "to": [0.05, 0.9]}],
            "racks": [{"rack_id": 1, "x": 0.23, "y": 0.4}],
            "calibration": {"from": [0.25, 0.5], "to": [0.75, 0.5], "length_m": 2.8},
        }

    def expect_error(self, code, action, *args):
        with self.assertRaises(ApiError) as context:
            action(*args)
        self.assertEqual(context.exception.status, code)

    def test_profile_scope_and_illustrative_default(self):
        demo = read_room_profile(self.conn, self.reader, 1)
        self.assertTrue(demo["illustrative"])
        self.assertEqual(demo["revision"], 0)
        self.expect_error(404, read_room_profile, self.conn, self.other, 1)
        self.expect_error(403, save_room_profile, self.conn, self.reader, 1, self.profile)
        self.expect_error(404, read_room_profile_image, self.conn, self.reader, 1)

    def test_profile_revision_and_scoped_private_raster(self):
        saved = save_room_profile(self.conn, self.admin, 1, {
            **self.profile, "reference": {"name": "西门图纸.pdf", "data": PNG_PIXEL},
        })
        self.assertFalse(saved["illustrative"])
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(saved["calibration"]["length_m"], 2.8)
        self.assertEqual(saved["reference"], {"name": "西门图纸.pdf"})
        self.assertEqual(read_room_profile(self.conn, self.reader, 1), saved)
        mime, image = read_room_profile_image(self.conn, self.reader, 1)
        self.assertEqual((mime, image), ("image/png", base64.b64decode(PNG_PIXEL)))
        self.expect_error(404, read_room_profile_image, self.conn, self.other, 1)
        self.expect_error(409, save_room_profile, self.conn, self.admin, 1, self.profile)
        save_room_profile(self.conn, self.admin, 1, {**self.profile, "revision": 1, "width_m": 6})
        self.assertEqual(read_room_profile_image(self.conn, self.reader, 1)[1], image)
        save_room_profile(self.conn, self.admin, 1, {**self.profile, "revision": 2, "reference": None})
        self.expect_error(404, read_room_profile_image, self.conn, self.reader, 1)

    def test_validator_rejects_invalid_geometry_foreign_racks_and_non_image(self):
        for replacement in (
            {"width_m": float("nan")},
            {"racks": [{"rack_id": 9999, "x": 0.3, "y": 0.7}]},
            {"features": [{"kind": "equipment", "from": [0.5, 0.4], "to": [0.5, 0.8]}]},
            {"reference": {"name": "底图.jpg", "data": base64.b64encode(b"<svg/>").decode()}},
        ):
            with self.subTest(replacement=replacement):
                self.expect_error(400, save_room_profile, self.conn, self.admin, 1, {**self.profile, **replacement})
                self.assertEqual(read_room_profile(self.conn, self.reader, 1)["revision"], 0)
