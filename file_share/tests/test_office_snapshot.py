"""Concurrent Office saves use isolated SQLite and in-memory OSS objects."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from file_share.office_service import OfficeService, OfficeServiceError


class MemoryOSS:
    def __init__(self):
        self.objects = {}
        self.copies = {}
        self.lock = threading.Lock()
        self.block_source = None
        self.first_copy = threading.Event()
        self.second_copy = threading.Event()
        self.release = threading.Event()
        self.blocked = False
        self.fail_checksum = False

    def head(self, key):
        with self.lock:
            data = self.objects[key]
        return {'Content-Length': str(len(data)), 'ETag': hashlib.md5(data).hexdigest()}

    def copy_object(self, source, target, etag):
        with self.lock:
            data = self.objects[source]
            assert hashlib.md5(data).hexdigest() == etag
            assert target not in self.objects
            self.objects[target] = data
            self.copies[target] = source
            if source == self.block_source and list(self.copies.values()).count(source) > 1:
                self.second_copy.set()

    def verify_private(self, key):
        assert key in self.objects

    def sha256(self, key):
        with self.lock:
            if self.fail_checksum:
                self.fail_checksum = False
                raise OSError('temporary checksum read failure')
            block = self.copies.get(key) == self.block_source and not self.blocked
            if block:
                self.blocked = True
            data = self.objects[key]
        if block:
            self.first_copy.set()
            if not self.release.wait(5):
                raise TimeoutError('test did not release the in-memory OSS read')
        return hashlib.sha256(data).hexdigest(), len(data)

    def delete(self, key):
        with self.lock:
            self.objects.pop(key, None)


class OfficeSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='office-snapshot-test-')
        self.path = Path(self.directory.name) / 'test.db'
        self.oss = MemoryOSS()
        self.handler = SimpleNamespace(
            fs_oss=lambda row: self.oss,
            fs_owned_file=self.owned_file,
            fs_audit=lambda conn, user, action, target: conn.execute(
                'INSERT INTO share_audit_logs(user_id,action,target_id,ip,created_at) VALUES(?,?,?,?,?)',
                (user, action, target, '127.0.0.1', int(time.time()))),
        )
        self.service = OfficeService(self.handler, 'owner')
        with closing(self.connect()) as conn:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.executescript(Path(__file__).resolve().parents[1].joinpath('schema.sql').read_text())
        self.db_patch = patch('file_share.database.db', side_effect=self.connect)
        self.config_patch = patch.object(OfficeService, '_enabled', return_value={})
        self.db_patch.start()
        self.config_patch.start()
        self.create_file('one')

    def tearDown(self):
        self.oss.release.set()
        self.config_patch.stop()
        self.db_patch.stop()
        self.directory.cleanup()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=.25)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def owned_file(self, conn, file_id, user_id):
        row = conn.execute('SELECT * FROM share_files WHERE id=? AND user_id=?',
                           (file_id, user_id)).fetchone()
        assert row is not None
        return row

    def create_file(self, file_id):
        source, draft = 'source-' + file_id, 'draft-' + file_id
        original, edited = b'original office file', b'edited office file'
        self.oss.objects.update({source: original, draft: edited})
        stamp = int(time.time())
        digest = hashlib.sha256(original).hexdigest()
        with closing(self.connect()) as conn, conn:
            conn.execute("INSERT INTO share_files(id,user_id,filename,original_filename,object_key,bucket,mime_type,file_type,size,sha256,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,'READY',?,?)",
                         (file_id, 'owner', 'file.docx', 'file.docx', source, 'test', 'application/octet-stream', 'WORD', len(original), digest, stamp, stamp))
            conn.execute('INSERT INTO share_office_versions(id,file_id,version_no,object_key,size,sha256,created_by,published_at,created_at) VALUES(?,?,1,?,?,?,?,?,?)',
                         ('baseline-' + file_id, file_id, source, len(original), digest, 'owner', stamp, stamp))
            conn.execute("INSERT INTO share_office_sessions(id,file_id,user_id,draft_key,source_key,status,expires_at,refresh_expires_at,created_at,updated_at) VALUES(?,?,?,?,?,'ACTIVE',?,?,?,?)",
                         ('session-' + file_id, file_id, 'owner', draft, source, stamp + 600, stamp + 1200, stamp, stamp))

    def query(self, sql, params=()):
        with closing(self.connect()) as conn:
            return conn.execute(sql, params).fetchone()[0]

    def test_overlapping_retries_create_one_unpublished_version(self):
        self.oss.block_source = 'draft-one'
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.service.snapshot, 'session-one')
            try:
                self.assertTrue(self.oss.first_copy.wait(2))
                second = pool.submit(self.service.snapshot, 'session-one')
                # Old code reaches a second copy while the first save is suspended.
                # Fixed code waits outside SQLite until the first result is registered.
                self.oss.second_copy.wait(.5)
            finally:
                self.oss.release.set()
            saved, repeated = first.result(timeout=3), second.result(timeout=3)
        self.assertEqual(saved['version']['id'], repeated['version']['id'])
        self.assertEqual(len(self.oss.copies), 1)
        self.assertEqual(self.query('SELECT count(*) FROM share_office_versions'), 2)
        self.assertEqual(self.query("SELECT count(*) FROM share_audit_logs WHERE action='SAVE_OFFICE_VERSION'"), 1)
        self.assertEqual(self.query("SELECT object_key FROM share_files WHERE id='one'"), 'source-one')
        self.assertFalse(saved['version']['published'])
        self.assertEqual(self.service.snapshot('session-one')['version']['id'], saved['version']['id'])

    def test_slow_save_does_not_hold_database_writer_or_another_editor(self):
        self.create_file('two')
        self.oss.block_source = 'draft-one'
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.service.snapshot, 'session-one')
            try:
                self.assertTrue(self.oss.first_copy.wait(2))
                with closing(self.connect()) as conn, conn:
                    conn.execute('BEGIN IMMEDIATE')
                    conn.execute("INSERT INTO share_settings(user_id) VALUES('unrelated-user')")
                other = pool.submit(self.service.snapshot, 'session-two').result(timeout=2)
                self.assertEqual(other['version']['number'], 2)
            finally:
                self.oss.release.set()
            first.result(timeout=3)

    def test_failed_save_releases_guard_and_can_be_retried(self):
        self.oss.fail_checksum = True
        with self.assertRaisesRegex(OSError, 'temporary checksum'):
            self.service.snapshot('session-one')
        self.assertEqual(self.query('SELECT count(*) FROM share_office_versions'), 1)
        self.assertEqual(set(self.oss.objects), {'source-one', 'draft-one'})
        saved = self.service.snapshot('session-one')
        self.assertEqual(saved['version']['number'], 2)
        self.assertEqual(self.query("SELECT object_key FROM share_files WHERE id='one'"), 'source-one')

    def test_closing_editor_during_save_rejects_result_and_cleans_copy(self):
        self.oss.block_source = 'draft-one'
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(self.service.snapshot, 'session-one')
            try:
                self.assertTrue(self.oss.first_copy.wait(2))
                self.service.close('session-one')
            finally:
                self.oss.release.set()
            with self.assertRaises(OfficeServiceError) as failure:
                pending.result(timeout=3)
        self.assertEqual(failure.exception.status, 409)
        self.assertEqual(self.query('SELECT count(*) FROM share_office_versions'), 1)
        self.assertEqual(set(self.oss.objects), {'source-one', 'draft-one'})
        self.assertEqual(self.query("SELECT object_key FROM share_files WHERE id='one'"), 'source-one')


if __name__ == '__main__':
    unittest.main()
