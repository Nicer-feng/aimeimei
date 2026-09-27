#!/usr/bin/env python3
"""Offline backup/recovery checks against temporary AI and file-share databases."""
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai_platform import backup, database
from file_share.database import init_share_db


class BackupRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="backup-recovery-test-")
        self.root = Path(self.directory.name)
        self.source = self.root / "source.db"
        self.key = self.root / "backup.key"
        self.key.write_bytes(os.urandom(32).hex().encode("ascii") + b"\n")
        self.key.chmod(0o600)
        with patch.multiple(database, DATA_DIR=self.root, DB_PATH=self.source,
                            SECRETS_PATH=self.root / "absent-secrets.json", LEGACY_CONFIG_PATH=self.root / "absent-config.json"):
            database.init_db({"family_password_hash": "test-only-password-hash"})
            init_share_db()
        # Keep a WAL connection open: committed rows must be included even before checkpointing.
        self.writer = sqlite3.connect(self.source)
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.executescript("""
            UPDATE users SET password_hash='test-only-password-hash',phone='test-phone';
            INSERT INTO models(id,name,base_url,api_key,model,created_at,updated_at)
              VALUES('m','Fixture','https://invalid.example','test-only-model-key','fixture',1,1);
            INSERT INTO conversations(id,user_id,title,model_id,created_at,updated_at)
              VALUES('c','default','Fixture conversation','m',1,1);
            INSERT INTO messages(user_id,conversation_id,role,content,generation_status,created_at)
              VALUES('default','c','assistant','fixture answer','interrupted',1);
            INSERT INTO document_files(id,user_id,filename,oss_key,created_at,updated_at)
              VALUES('d','default','fixture.txt','documents/fixture',1,1);
            INSERT INTO cat_users(id,username,password_hash,nickname,created_at,updated_at)
              VALUES('cat-user','cat-fixture','test-only-cat-hash','Fixture',1,1);
            INSERT INTO cats(id,owner_user_id,name,created_at,updated_at)
              VALUES('cat','cat-user','Fixture',1,1);
            INSERT INTO share_files(id,user_id,filename,original_filename,object_key,bucket,mime_type,file_type,size,sha256,status,upload_id,created_at,updated_at)
              VALUES('f','default','fixture.pdf','fixture.pdf','share/fixture','fixture','application/pdf','PDF',1,'fixture-sha','READY','fixture-upload',1,1);
            INSERT INTO shares(id,user_id,share_code,title,password_hash,created_at,updated_at)
              VALUES('s','default','fixturesharecode','Fixture','test-only-share-hash',1,1);
            INSERT INTO share_files_relation(share_id,file_id,sort_order) VALUES('s','f',0);
            INSERT INTO share_office_versions(id,file_id,version_no,object_key,size,sha256,created_by,published_at,created_at)
              VALUES('v','f',1,'share/version-1',1,'fixture-sha','default',1,1);
            INSERT INTO share_sessions(token_hash,share_id,auth_version,expires_at) VALUES('test-only-token-hash','s',1,999999);
            CREATE TABLE future_product(id TEXT PRIMARY KEY, value BLOB NOT NULL);
            INSERT INTO future_product VALUES('future',X'0001FFFF');
        """)
        self.writer.commit()
        self.archive = self.root / "full.auth.enc"
        self.target = self.root / "restored.db"

    def tearDown(self):
        self.writer.close()
        self.directory.cleanup()

    def full(self):
        return backup.create_local_backup(self.source, self.archive, self.key, mode="full")

    def database_content(self, filename):
        with closing(sqlite3.connect(filename)) as connection:
            schema = connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master WHERE name!='backup_manifest' ORDER BY name").fetchall()
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name!='backup_manifest'").fetchall()
            rows = {name: connection.execute('SELECT * FROM "{}"'.format(name)).fetchall() for name, in tables}
            return schema, rows

    def test_full_roundtrip_preserves_all_products_credentials_and_wal(self):
        before = self.database_content(self.source)
        meta = self.full()
        self.assertEqual(meta["mode"], "full")
        self.assertNotIn(b"test-only-model-key", self.archive.read_bytes())
        result = backup.restore_local_backup(self.archive, self.target, self.key)
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(self.database_content(self.target), before)
        self.assertEqual(self.database_content(self.source), before)
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertFalse(self.target.with_name(self.target.name + "-wal").exists())

    def test_default_sanitization_remains_compatible(self):
        snapshot = self.root / "sanitized.db"
        backup.create_sanitized_snapshot(self.source, snapshot)
        with closing(sqlite3.connect(snapshot)) as connection:
            self.assertEqual(connection.execute("SELECT api_key FROM models").fetchone()[0], "")
            self.assertEqual(connection.execute("SELECT password_hash,phone FROM users").fetchone(), ("", ""))
            self.assertEqual(connection.execute("SELECT password_hash FROM cat_users").fetchone()[0], "")
            self.assertEqual(connection.execute("SELECT count(*) FROM shares").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM share_files_relation").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT count(*) FROM share_sessions").fetchone()[0], 0)
            self.assertIsNone(connection.execute("SELECT upload_id FROM share_files").fetchone()[0])
            self.assertEqual(connection.execute("SELECT content FROM messages").fetchone()[0], "fixture answer")
            self.assertEqual(connection.execute("SELECT sanitized FROM backup_manifest").fetchone()[0], 1)

    def test_sanitized_archive_is_not_accepted_as_full(self):
        backup.create_local_backup(self.source, self.archive, self.key)
        with self.assertRaisesRegex(ValueError, "mode mismatch"):
            backup.restore_local_backup(self.archive, self.target, self.key)
        self.assertFalse(self.target.exists())
        result = backup.restore_local_backup(self.archive, self.target, self.key, expected_mode="sanitized")
        self.assertEqual(result["mode"], "sanitized")

    def test_wrong_key_and_modified_or_truncated_archive_leave_no_plaintext(self):
        self.full()
        wrong = self.root / "wrong.key"
        wrong.write_bytes(b"another-fixture-key-" * 4)
        with self.assertRaisesRegex(ValueError, "authentication failed"):
            backup.restore_local_backup(self.archive, self.target, wrong)
        original = self.archive.read_bytes()
        for label, data in (("truncated", original[:-17]),
                            ("tampered", original[:-80] + bytes([original[-80] ^ 1]) + original[-79:])):
            broken = self.root / (label + ".enc")
            broken.write_bytes(data)
            with self.assertRaises(ValueError):
                backup.restore_local_backup(broken, self.target, self.key)
            self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob("database-restore-*")), [])

    def test_existing_database_and_symlinks_cannot_be_replaced(self):
        self.full()
        self.target.write_bytes(b"existing-database-sentinel")
        with self.assertRaises(FileExistsError):
            backup.restore_local_backup(self.archive, self.target, self.key)
        self.assertEqual(self.target.read_bytes(), b"existing-database-sentinel")
        for destination in (self.root / "linked.db", self.root / "dangling.db"):
            destination.symlink_to(self.target if destination.name == "linked.db" else self.root / "missing.db")
            with self.assertRaises(FileExistsError):
                backup.restore_local_backup(self.archive, destination, self.key)
            self.assertTrue(destination.is_symlink())
        with self.assertRaises(FileExistsError):
            backup.create_local_backup(self.source, self.archive, self.key, mode="full")
        before = backup.file_sha256(self.source)
        with self.assertRaises(FileExistsError):
            backup.create_database_snapshot(self.source, self.source, mode="full")
        self.assertEqual(backup.file_sha256(self.source), before)

    def test_atomic_publish_does_not_overwrite_a_racing_creator(self):
        self.full()
        link = os.link
        def race(source, destination):
            if Path(destination) == self.target:
                self.target.write_bytes(b"racing-writer")
            return link(source, destination)
        with patch.object(backup.os, "link", side_effect=race):
            with self.assertRaises(FileExistsError):
                backup.restore_local_backup(self.archive, self.target, self.key)
        self.assertEqual(self.target.read_bytes(), b"racing-writer")

    def test_decompression_limit_and_corrupt_payload_leave_no_target(self):
        self.full()
        with self.assertRaisesRegex(ValueError, "size limit"):
            backup.restore_local_backup(self.archive, self.target, self.key, max_bytes=128)
        self.assertFalse(self.target.exists())
        bad_database = self.root / "bad.db"
        bad_database.write_bytes(b"not SQLite")
        zipped = self.root / "bad.gz"
        broken = self.root / "bad.auth.enc"
        backup.gzip_snapshot(bad_database, zipped)
        backup.encrypt_authenticated_archive(zipped, broken, self.key)
        with self.assertRaisesRegex(ValueError, "not SQLite"):
            backup.restore_local_backup(broken, self.target, self.key)
        self.assertFalse(self.target.exists())

    def test_snapshot_failure_closes_source_and_destination(self):
        source, destination = Mock(), Mock()
        source.backup.side_effect = sqlite3.OperationalError("fixture copy failure")
        with patch.object(backup.sqlite3, "connect", side_effect=[source, destination]):
            with self.assertRaises(sqlite3.OperationalError):
                backup.create_database_snapshot(self.source, self.target, mode="full")
        source.close.assert_called_once()
        destination.close.assert_called_once()
        self.assertFalse(self.target.exists())
        source = Mock()
        with patch.object(backup.sqlite3, "connect", side_effect=[source, sqlite3.OperationalError("fixture open failure")]):
            with self.assertRaises(sqlite3.OperationalError):
                backup.create_database_snapshot(self.source, self.target, mode="full")
        source.close.assert_called_once()
        self.assertFalse(self.target.exists())

    def test_daily_default_is_legacy_and_full_is_separate_using_fake_oss(self):
        uploads = []
        def upload(config, key, data, **kwargs):
            uploads.append((key, data, kwargs))
        with patch.multiple(backup, DB_PATH=self.source, SECRETS_PATH=self.root / "absent-secrets.json"), \
             patch.object(backup, "cat_oss_config", return_value={"configured": True}), \
             patch.object(backup, "oss_put_bytes", side_effect=upload), \
             patch.object(backup, "verify_uploaded_backup", return_value=False), \
             patch.object(backup, "purge_old_backups", return_value=0) as purge, \
             patch.dict(os.environ, {"AI_PLATFORM_BACKUP_KEY_FILE": str(self.key), "AI_PLATFORM_BACKUP_PREFIX": "fixture/backups"}):
            default = backup.run_daily_backup()
            full = backup.run_daily_backup(mode="full")
        self.assertTrue(default["sanitized"])
        self.assertTrue(uploads[0][1].startswith(b"Salted__"))
        self.assertFalse(full["sanitized"])
        self.assertIn("/full/", uploads[1][0])
        self.assertTrue(uploads[1][1].startswith(backup.AUTHENTICATED_MAGIC))
        self.assertIs(purge.call_args.kwargs["name_pattern"], backup.FULL_BACKUP_NAME_RE)
        self.archive.write_bytes(uploads[1][1])
        self.assertEqual(backup.restore_local_backup(self.archive, self.target, self.key)["mode"], "full")

    def test_full_backup_rejects_short_effective_openssl_password(self):
        bad_key = self.root / "short-first-line.key"
        bad_key.write_bytes(b"short\n" + b"padding-after-first-line" * 4)
        with self.assertRaisesRegex(RuntimeError, "first line"):
            backup.create_local_backup(self.source, self.archive, bad_key, mode="full")
        self.assertFalse(self.archive.exists())
        self.assertEqual(list(self.root.glob("database-backup-*")), [])

    def test_plaintext_temporary_paths_are_private(self):
        original = backup.gzip_snapshot
        inspected = []
        def check(snapshot, archive):
            self.assertEqual(snapshot.parent.stat().st_mode & 0o777, 0o700)
            self.assertEqual(snapshot.stat().st_mode & 0o777, 0o600)
            original(snapshot, archive)
            self.assertEqual(archive.stat().st_mode & 0o777, 0o600)
            inspected.append(True)
        with patch.object(backup, "gzip_snapshot", side_effect=check):
            self.full()
        self.assertTrue(inspected)
        self.assertEqual(list(self.root.glob("database-backup-*")), [])

    def test_full_public_access_failure_skips_retention_cleanup(self):
        with patch.multiple(backup, DB_PATH=self.source, SECRETS_PATH=self.root / "absent-secrets.json"), \
             patch.object(backup, "cat_oss_config", return_value={"configured": True}), \
             patch.object(backup, "oss_put_bytes"), \
             patch.object(backup, "verify_uploaded_backup", return_value=True), \
             patch.object(backup, "purge_old_backups") as purge, \
             patch.dict(os.environ, {"AI_PLATFORM_BACKUP_KEY_FILE": str(self.key)}):
            with self.assertRaisesRegex(RuntimeError, "anonymous access"):
                backup.run_daily_backup(mode="full")
        purge.assert_not_called()

    def test_cli_verify_restores_only_temporary_files(self):
        self.full()
        command = [sys.executable, str(Path(__file__).with_name("backup_database.py")), "verify",
                   "--archive", str(self.archive), "--key-file", str(self.key)]
        result = subprocess.run(command, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["mode"], "full")
        self.assertFalse(self.target.exists())
        self.assertNotIn("test-only", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
