import base64
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from ledger.data import (
    ApiError, catalog, connect, delete_record, document_file, initialize, migrate_schema, save_device, save_document,
    save_project, save_rack, save_room, save_system, set_device_archive,
)


class InventoryManagementTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        data_dir = Path(directory.name)
        initialize(data_dir)
        self.conn = connect(data_dir)
        self.addCleanup(self.conn.close)
        self.admin = {"role": "admin"}
        self.reader = {"role": "reader", "unit_id": 2}

    def device(self, ident=1, user=None):
        return next(device for device in catalog(self.conn, user or self.admin)["devices"] if device["id"] == ident)

    def expect_error(self, status, callback, *args):
        with self.assertRaises(ApiError) as caught:
            callback(*args)
        self.assertEqual(caught.exception.status, status)

    @staticmethod
    def endpoint(**details):
        return {"host": "gateway.example.test", "protocol": "HTTPS", "port": 443, **details}

    def test_room_and_rack_changes_are_scoped_and_resizing_checks_slots(self):
        room = save_room(self.conn, self.admin, {"site_id": 1, "name": "验收房"})
        self.expect_error(409, save_room, self.conn, self.admin, {"site_id": 1, "name": "验收房"})
        self.assertEqual(save_room(self.conn, self.admin, {"name": "验收新房"}, room["id"])["site_id"], 1)
        rack = save_rack(self.conn, self.admin, {"room_id": room["id"], "name": "T-01", "height": 42})
        self.expect_error(409, save_rack, self.conn, self.admin, {"room_id": room["id"], "name": "t-01", "height": 42})
        previous = self.device()
        self.expect_error(409, save_rack, self.conn, self.admin, {"height": previous["u_start"]}, previous["rack_id"])
        updated = save_rack(self.conn, self.admin, {"height": 42, "name": "新柜号"}, previous["rack_id"])
        self.assertEqual((updated["height"], updated["name"]), (42, "新柜号"))
        self.assertEqual(self.device(), previous)
        self.expect_error(400, save_rack, self.conn, self.admin, {"room_id": 2}, rack["id"])

    def test_archive_releases_u_but_keeps_history_and_relationships(self):
        original = self.device()
        archived = set_device_archive(self.conn, self.admin, 1, True)
        self.assertTrue(archived["archived_at"])
        self.assertIsNone(archived["rack_id"])
        self.assertEqual(archived["archived_location"]["rack_id"], original["rack_id"])
        self.assertEqual(archived["archived_location"]["u_start"], original["u_start"])
        self.assertEqual(archived["project_ids"], original["project_ids"])
        self.assertEqual(document_file(self.conn, self.reader, 5)[0], "site-a-device.pdf")
        self.assertEqual(set_device_archive(self.conn, self.admin, 1, True), archived)
        self.expect_error(409, save_device, self.conn, self.admin, archived, 1)
        self.expect_error(409, delete_record, self.conn, "devices", 1)
        claimed = save_device(self.conn, self.admin, {**original, "code": "POST-ARCHIVE", "project_ids": []})
        self.assertEqual(claimed["u_start"], original["u_start"])
        restored = set_device_archive(self.conn, self.admin, 1, False)
        self.assertIsNone(restored["archived_at"])
        self.assertIsNone(restored["archived_location"])
        self.assertIsNone(restored["rack_id"])

    def test_archive_keeps_old_links_when_editing_but_rejects_new_links(self):
        set_device_archive(self.conn, self.admin, 1, True)
        body = {"name": "验收用途", "code": "QL-2026-01", "site_id": 1, "device_ids": [1, 2]}
        self.assertEqual(save_project(self.conn, self.admin, body, 1)["device_ids"], [1, 2])
        self.expect_error(409, save_project, self.conn, self.admin, {**body, "code": "N-001"})
        body = {"name": "原系统改名", "deployments": [{"device_id": 1, "entries": []}]}
        self.assertEqual(save_system(self.conn, self.admin, body, 1)["deployments"][0]["device_id"], 1)
        self.expect_error(409, save_system, self.conn, self.admin, body)

    def test_addresses_and_entry_sources_follow_document_visibility(self):
        address = {"host": "192.0.2.77", "note": "管理口", "source_document_id": 4, "source_page": 2}
        saved = save_device(self.conn, self.admin, {**self.device(), "addresses": [address]}, 1)
        self.assertEqual(saved["addresses"], [address])
        self.assertEqual(save_device(self.conn, self.admin, {key: value for key, value in saved.items() if key != "addresses"}, 1)
                         ["addresses"], [address])
        self.expect_error(400, save_device, self.conn, self.admin, {**saved, "addresses": [{**address, "source_document_id": 6}]}, 1)
        update = {"name": "地址依据", "deployments": [{"device_id": 1, "entries": [
            self.endpoint(source_document_id=4, source_page=2),
        ]}]}
        system = save_system(self.conn, self.admin, update, 1)
        self.assertEqual(system["deployments"][0]["entries"][0]["source_page"], 2)
        update["deployments"][0]["entries"] = [self.endpoint()]
        system = save_system(self.conn, self.admin, update, 1)
        self.assertEqual(system["deployments"][0]["entries"][0]["source_document_id"], 4)
        with self.conn:
            self.conn.execute("INSERT INTO project_devices(project_id, device_id) VALUES (1, 5)")
        self.assertEqual(self.device(user=self.reader)["addresses"][0]["source_document_id"], None)
        reader_system = next(system for system in catalog(self.conn, self.reader)["systems"] if system["id"] == 1)
        self.assertEqual(reader_system["deployments"][0]["entries"][0]["source_document_id"], None)

    def test_delete_document_preserves_shared_blob_until_last_reference(self):
        unchanged = "SELECT COUNT(*) FROM files WHERE digest = ?"
        digest = self.conn.execute("SELECT file_digest FROM documents WHERE id = 5").fetchone()[0]
        with self.conn:
            self.conn.execute("""INSERT INTO documents(title, category, device_id, note, filename, file_digest)
                                 VALUES ('同一档案', '验收', 1, '', 'copy.pdf', ?)""", (digest,))
        address = {"host": "192.0.2.11", "source_document_id": 5, "source_page": 1}
        save_device(self.conn, self.admin, {**self.device(), "addresses": [address]}, 1)
        system_update = {"name": "地址依据", "deployments": [{"device_id": 1, "entries": [
            self.endpoint(source_document_id=5, source_page=1),
        ]}]}
        save_system(self.conn, self.admin, system_update, 1)
        delete_record(self.conn, "documents", 5)
        self.assertEqual(self.conn.execute(unchanged, (digest,)).fetchone()[0], 1)
        self.expect_error(404, document_file, self.conn, self.admin, 5)
        self.assertEqual(self.device()["addresses"][0]["source_page"], None)
        entry = next(system for system in catalog(self.conn, self.admin)["systems"] if system["id"] == 1)["deployments"][0]["entries"][0]
        self.assertEqual((entry["source_document_id"], entry["source_page"]), (None, None))
        copy_id = self.conn.execute("SELECT id FROM documents WHERE filename = 'copy.pdf'").fetchone()[0]
        delete_record(self.conn, "documents", copy_id)
        self.assertEqual(self.conn.execute(unchanged, (digest,)).fetchone()[0], 0)
        self.expect_error(409, delete_record, self.conn, "systems", 1)
        self.expect_error(409, delete_record, self.conn, "projects", 1)

    def test_migration_repeats_on_current_database(self):
        migrate_schema(self.conn)
        migrate_schema(self.conn)
        self.assertEqual(self.conn.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_deleted_ids_are_not_reused(self):
        device = {"code": "TEST-ID", "name": "ID 验收", "type": "测试", "room_id": 1}
        payload = {"devices": device, "systems": {"name": "ID 验收"},
                   "projects": {"code": "TEST-ID", "name": "ID 验收", "site_id": 1}}
        for resource, writer in (("devices", save_device), ("systems", save_system), ("projects", save_project)):
            with self.subTest(resource=resource):
                old_id = writer(self.conn, self.admin, payload[resource])["id"]
                delete_record(self.conn, resource, old_id)
                self.assertGreater(writer(self.conn, self.admin, payload[resource])["id"], old_id)
        filename, content = document_file(self.conn, self.admin, 6)
        fields = {"title": "ID 验收", "category": "测试", "project_id": 2, "filename": filename,
                  "content_base64": base64.b64encode(content).decode()}
        delete_record(self.conn, "documents", 6)
        self.assertGreater(save_document(self.conn, fields)["id"], 6)
        self.expect_error(404, document_file, self.conn, self.admin, 6)
