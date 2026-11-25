import tempfile
import unittest
from pathlib import Path

from ledger.data import ApiError, connect, initialize, save_device


class RackDepthTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name)
        initialize(path)
        self.conn = connect(path)
        self.addCleanup(self.conn.close)
        self.user = {'role': 'admin'}
        with self.conn:
            self.rack = self.conn.execute(
                "INSERT INTO racks(room_id, name, height) VALUES (1, '深度验收柜', 12)"
            ).lastrowid

    def device(self, code, face, start, height=1, depth='half', ident=None):
        return save_device(self.conn, self.user, {
            'code': code, 'name': code, 'type': '测试设备', 'room_id': 1, 'rack_id': self.rack,
            'face': face, 'u_start': start, 'u_height': height, 'mount_depth': depth,
        }, ident)

    def test_full_depth_blocks_opposite_u_but_allows_neighbor(self):
        full = self.device('全深服务器', 'front', 8, height=2, depth='full')
        self.assertEqual((full['u_start'], full['u_height'], full['mount_depth']), (8, 2, 'full'))
        with self.assertRaises(ApiError) as blocked:
            self.device('背面冲突', 'rear', 9)
        self.assertEqual(blocked.exception.status, 409)
        self.assertIn('全深服务器', str(blocked.exception))
        self.assertEqual(self.device('背面相邻', 'rear', 10)['u_start'], 10)

    def test_half_depth_can_share_u_on_opposite_faces(self):
        front = self.device('正面半深设备', 'front', 5)
        rear = self.device('背面半深设备', 'rear', 5)
        self.assertNotEqual(front['id'], rear['id'])
        with self.assertRaises(ApiError) as duplicate:
            self.device('同面冲突', 'front', 5)
        self.assertEqual(duplicate.exception.status, 409)
        with self.assertRaises(ApiError) as changed:
            self.device(rear['code'], 'rear', 5, depth='full', ident=rear['id'])
        self.assertEqual(changed.exception.status, 409)
        self.assertEqual(self.conn.execute(
            'SELECT mount_depth FROM devices WHERE id = ?', (rear['id'],)
        ).fetchone()[0], 'half')

    def test_new_cross_face_pair_requires_confirmed_half_depth(self):
        self.device('深度待核设备', 'rear', 6, depth='unknown')
        with self.assertRaises(ApiError) as blocked:
            self.device('正面半深', 'front', 6)
        self.assertEqual(blocked.exception.status, 409)
        self.assertIn('核实', str(blocked.exception))


if __name__ == '__main__':
    unittest.main()
