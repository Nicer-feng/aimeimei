"""Isolated HTTP workflow: IMM drafts, private versions, and explicit publication."""
import base64
import hashlib
import http.cookiejar
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ai_platform.settings import DB_PATH
from ai_platform.backup import create_sanitized_snapshot
from file_share.handlers import FileShareHandlersMixin

BASE = 'http://127.0.0.1:18765'

def client():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

def req(opener, path, data=None):
    request = urllib.request.Request(BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json', 'X-Share-Request': '1', 'User-Agent': 'Office-Test/1'})
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)

def login(opener, username='admin'):
    _, captcha = req(opener, '/api/captcha')
    answer = ''.join(re.findall(r'<text[^>]*>(.*?)</text>', captcha['image_svg']))
    status, response = req(opener, '/api/login', {'username': username, 'password': 'test-password',
        'captcha_id': captcha['captcha_id'], 'captcha': answer})
    assert status == 200, (status, response)

def scalar(statement, params=()):
    with sqlite3.connect(DB_PATH) as connection:
        row = connection.execute(statement, params).fetchone()
        return row[0] if row else None

def fake_object_bytes(opener, key):
    url = 'http://127.0.0.1:18766/object/' + urllib.parse.quote(key)
    with opener.open(url) as response:
        assert response.status == 200
        return response.read()

admin, other, member, anon = client(), client(), client(), client()
login(admin)
login(other, 'other-admin')
login(member, 'member')
route = '/api/file-share/admin/office'
assert req(admin, route + '/config')[1] == {'enabled': True, 'max_bytes': 20 * 1024 * 1024,
                                            'formats': ['docx', 'xlsx']}
assert req(anon, route + '/config')[0] == 401
assert req(member, route + '/config')[0] in (401, 403)

original = b'PK\x03\x04original office data'
updated = b'PK\x03\x04edited office data'
unsaved = b'PK\x03\x04another synced draft'
status, upload = req(admin, '/api/file-share/admin/uploads', {'filename': 'report.docx',
    'size': len(original), 'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'sha256': hashlib.sha256(original).hexdigest()})
assert status == 200, (status, upload)
file_id = upload['id']
_, permit = req(admin, f'/api/file-share/admin/uploads/{file_id}/part', {'part_number': 1,
    'content_md5': base64.b64encode(hashlib.md5(original).digest()).decode()})
with admin.open(urllib.request.Request(permit['url'], data=original, headers=permit['headers'], method='PUT')) as response:
    etag = response.headers['ETag']
assert req(admin, f'/api/file-share/admin/uploads/{file_id}/complete',
           {'parts': [{'part_number': 1, 'etag': etag}]})[0] == 200
source_key = scalar('SELECT object_key FROM share_files WHERE id=?', (file_id,))
status, share = req(admin, '/api/file-share/admin/shares', {'title': 'Office test', 'file_ids': [file_id]})
assert status == 201, (status, share)
public = '/api/file-share/public/' + share['share_code']
assert req(anon, public + '/open', {})[0] == 200
assert req(other, f'{route}/files/{file_id}/start', {})[0] == 404

status, started = req(admin, f'{route}/files/{file_id}/start', {})
assert status == 200, (status, started)
session_id = started['session_id']
draft_key = scalar('SELECT draft_key FROM share_office_sessions WHERE id=?', (session_id,))
assert draft_key != source_key and draft_key.startswith('share/office-drafts/')
assert scalar('SELECT access_token_hash FROM share_office_sessions WHERE id=?', (session_id,)) != started['access_token']
snapshot_path = DB_PATH.with_name('office-sanitized-test.db')
create_sanitized_snapshot(DB_PATH, snapshot_path)
with sqlite3.connect(snapshot_path) as connection:
    assert connection.execute('SELECT COUNT(*) FROM share_office_sessions').fetchone()[0] == 0
snapshot_path.unlink()
assert req(admin, f'{route}/files/{file_id}/start', {})[0] == 409
assert req(admin, f'/api/file-share/admin/files/{file_id}/trash', {})[0] == 409
assert req(other, f'{route}/sessions/{session_id}/snapshot', {})[0] == 404
initial_versions = req(admin, f'{route}/files/{file_id}/versions')[1]['items']
assert len(initial_versions) == 1 and initial_versions[0]['published'] and initial_versions[0]['number'] == 1
assert req(admin, f'{route}/files/{file_id}/publish', {'version_id': initial_versions[0]['id']})[0] == 409

old_token = started['access_token']
with sqlite3.connect(DB_PATH) as connection:
    connection.execute('UPDATE share_office_sessions SET expires_at=0 WHERE id=?', (session_id,))
status, refreshed = req(admin, f'{route}/sessions/{session_id}/refresh',
    {'access_token': old_token, 'refresh_token': started['refresh_token']})
assert status == 200 and refreshed['url'] is None and refreshed['access_token'] != old_token, (status, refreshed)
assert req(admin, f'{route}/sessions/{session_id}/refresh',
    {'access_token': old_token, 'refresh_token': started['refresh_token']})[0] == 409

write_url = 'http://127.0.0.1:18766/object/' + urllib.parse.quote(draft_key) + '?testWrite=1'
with admin.open(urllib.request.Request(write_url, data=updated, method='PUT')) as response:
    assert response.status == 200
status, saved = req(admin, f'{route}/sessions/{session_id}/snapshot', {})
assert status == 200, (status, saved)
assert saved['version']['number'] == 2 and not saved['version']['published']
assert req(admin, f'{route}/sessions/{session_id}/snapshot', {})[1]['version']['id'] == saved['version']['id']
version_key = scalar('SELECT object_key FROM share_office_versions WHERE id=?', (saved['version']['id'],))
assert version_key != draft_key and version_key != source_key
assert scalar('SELECT object_key FROM share_files WHERE id=?', (file_id,)) == source_key
assert scalar('SELECT sha256 FROM share_office_versions WHERE id=?', (saved['version']['id'],)) == hashlib.sha256(updated).hexdigest()
status, old_download = req(anon, public + '/download', {'file_id': file_id})
assert status == 200 and source_key in old_download['url'], (status, old_download)
assert req(other, f'{route}/files/{file_id}/publish', {'version_id': saved['version']['id']})[0] == 404
status, published = req(admin, f'{route}/files/{file_id}/publish', {'version_id': saved['version']['id']})
assert status == 200 and published['version']['published'], (status, published)
assert scalar('SELECT object_key FROM share_files WHERE id=?', (file_id,)) == version_key
assert scalar('SELECT sha256 FROM share_files WHERE id=?', (file_id,)) == hashlib.sha256(updated).hexdigest()
status, new_download = req(anon, public + '/download', {'file_id': file_id})
assert status == 200 and version_key in new_download['url'], (status, new_download)
with anon.open(new_download['url']) as response:
    assert response.read() == updated
versions = req(admin, f'{route}/files/{file_id}/versions')[1]['items']
assert [(v['number'], v['published']) for v in versions] == [(2, True), (1, False)]
# Expiring only AccessToken must not release the single-editor lock or permit rollback.
with sqlite3.connect(DB_PATH) as connection:
    connection.execute('UPDATE share_office_sessions SET expires_at=0 WHERE id=?', (session_id,))
assert req(admin, f'{route}/files/{file_id}/start', {})[0] == 409
assert req(admin, f'/api/file-share/admin/files/{file_id}/trash', {})[0] == 409
assert req(admin, f'{route}/files/{file_id}/publish',
           {'version_id': initial_versions[0]['id']})[0] == 409
status, renewed = req(admin, f'{route}/sessions/{session_id}/refresh',
    {'access_token': refreshed['access_token'], 'refresh_token': refreshed['refresh_token']})
assert status == 200 and renewed['access_token'] != refreshed['access_token'], (status, renewed)
with admin.open(urllib.request.Request(write_url, data=unsaved, method='PUT')) as response:
    assert response.status == 200
assert req(admin, f'{route}/sessions/{session_id}/close', {})[0] == 200
assert req(admin, f'{route}/sessions/{session_id}/snapshot', {})[0] == 409
status, reopened = req(admin, f'{route}/files/{file_id}/start', {})
assert status == 200 and reopened['recovered'] is True, (status, reopened)
status, recovered_version = req(admin, f"{route}/sessions/{reopened['session_id']}/snapshot", {})
assert status == 200 and recovered_version['version']['number'] == 3, (status, recovered_version)
assert scalar('SELECT sha256 FROM share_office_versions WHERE id=?', (recovered_version['version']['id'],)) == hashlib.sha256(unsaved).hexdigest()
assert scalar('SELECT object_key FROM share_files WHERE id=?', (file_id,)) == version_key
assert req(admin, f"{route}/sessions/{reopened['session_id']}/close", {})[0] == 200
# Rollback to v1 must discard recovery eligibility from both earlier drafts.
status, rollback = req(admin, f'{route}/files/{file_id}/publish',
    {'version_id': initial_versions[0]['id']})
assert status == 200 and rollback['version']['number'] == 1, (status, rollback)
assert scalar('SELECT object_key FROM share_files WHERE id=?', (file_id,)) == source_key
status, after_rollback = req(admin, f'{route}/files/{file_id}/start', {})
assert status == 200 and after_rollback['recovered'] is False, (status, after_rollback)
rollback_draft_key = scalar('SELECT draft_key FROM share_office_sessions WHERE id=?',
                            (after_rollback['session_id'],))
assert fake_object_bytes(admin, rollback_draft_key) == original
# A later unpublished draft must also be discarded when publishing an older version.
rollback_write_url = 'http://127.0.0.1:18766/object/' + urllib.parse.quote(rollback_draft_key) + '?testWrite=1'
with admin.open(urllib.request.Request(rollback_write_url, data=unsaved, method='PUT')) as response:
    assert response.status == 200
assert req(admin, f"{route}/sessions/{after_rollback['session_id']}/close", {})[0] == 200
status, republished = req(admin, f'{route}/files/{file_id}/publish',
    {'version_id': saved['version']['id']})
assert status == 200 and republished['version']['number'] == 2, (status, republished)
status, after_older_publish = req(admin, f'{route}/files/{file_id}/start', {})
assert status == 200 and after_older_publish['recovered'] is False, (status, after_older_publish)
older_draft_key = scalar('SELECT draft_key FROM share_office_sessions WHERE id=?',
                         (after_older_publish['session_id'],))
assert fake_object_bytes(admin, older_draft_key) == updated
assert req(admin, f"{route}/sessions/{after_older_publish['session_id']}/close", {})[0] == 200
assert req(admin, f'/api/file-share/admin/files/{file_id}/trash', {})[0] == 200
assert req(admin, f'/api/file-share/admin/files/{file_id}/purge', {})[0] == 409
with sqlite3.connect(DB_PATH) as connection:
    connection.execute('UPDATE share_office_sessions SET expires_at=0,refresh_expires_at=0 WHERE file_id=?', (file_id,))
assert req(admin, f'/api/file-share/admin/files/{file_id}/purge', {})[0] == 200
assert scalar('SELECT COUNT(*) FROM share_office_versions WHERE file_id=?', (file_id,)) == 0
assert scalar('SELECT COUNT(*) FROM share_office_sessions WHERE file_id=?', (file_id,)) == 0
print('PASS: private draft, owner isolation, refresh-token lock, version recovery, rollback isolation, explicit publish, existing share, purge')

# Two snapshots from one live editor: publishing v2 while the draft still holds v3
# must make v2 the baseline when the editor closes without further changes.
second_original = b'PK\x03\x04second original'
second_v2 = b'PK\x03\x04second version two'
second_v3 = b'PK\x03\x04second version three'
status, second_upload = req(admin, '/api/file-share/admin/uploads', {'filename': 'second.docx',
    'size': len(second_original),
    'mime_type': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'sha256': hashlib.sha256(second_original).hexdigest()})
assert status == 200, (status, second_upload)
second_id = second_upload['id']
_, second_permit = req(admin, f'/api/file-share/admin/uploads/{second_id}/part', {'part_number': 1,
    'content_md5': base64.b64encode(hashlib.md5(second_original).digest()).decode()})
with admin.open(urllib.request.Request(second_permit['url'], data=second_original,
                                       headers=second_permit['headers'], method='PUT')) as response:
    second_etag = response.headers['ETag']
assert req(admin, f'/api/file-share/admin/uploads/{second_id}/complete',
           {'parts': [{'part_number': 1, 'etag': second_etag}]})[0] == 200
status, second_started = req(admin, f'{route}/files/{second_id}/start', {})
assert status == 200, (status, second_started)
second_session_id = second_started['session_id']
second_draft_key = scalar('SELECT draft_key FROM share_office_sessions WHERE id=?', (second_session_id,))
second_write_url = 'http://127.0.0.1:18766/object/' + urllib.parse.quote(second_draft_key) + '?testWrite=1'
with admin.open(urllib.request.Request(second_write_url, data=second_v2, method='PUT')) as response:
    assert response.status == 200
status, second_saved_v2 = req(admin, f'{route}/sessions/{second_session_id}/snapshot', {})
assert status == 200 and second_saved_v2['version']['number'] == 2, (status, second_saved_v2)
with admin.open(urllib.request.Request(second_write_url, data=second_v3, method='PUT')) as response:
    assert response.status == 200
status, second_saved_v3 = req(admin, f'{route}/sessions/{second_session_id}/snapshot', {})
assert status == 200 and second_saved_v3['version']['number'] == 3, (status, second_saved_v3)
assert second_saved_v3['version']['id'] != second_saved_v2['version']['id']
status, second_published = req(admin, f'{route}/files/{second_id}/publish',
                               {'version_id': second_saved_v2['version']['id']})
assert status == 200 and second_published['version']['number'] == 2, (status, second_published)
assert req(admin, f'{route}/sessions/{second_session_id}/close', {})[0] == 200
status, second_reopened = req(admin, f'{route}/files/{second_id}/start', {})
assert status == 200 and second_reopened['recovered'] is False, (status, second_reopened)
second_reopened_key = scalar('SELECT draft_key FROM share_office_sessions WHERE id=?',
                             (second_reopened['session_id'],))
assert fake_object_bytes(admin, second_reopened_key) == second_v2
assert req(admin, f"{route}/sessions/{second_reopened['session_id']}/close", {})[0] == 200
print('PASS: publishing older v2 during one active v2/v3 session resets recovery to v2')

# Inject a failure on the second OSS delete. The first deletion is irreversible,
# so the file must remain PURGING and a later retry must finish safely.
assert req(admin, f'/api/file-share/admin/files/{second_id}/trash', {})[0] == 200
with sqlite3.connect(DB_PATH) as connection:
    connection.execute('UPDATE share_office_sessions SET expires_at=0,refresh_expires_at=0 WHERE file_id=?',
                       (second_id,))
    purge_keys = {row[0] for row in connection.execute(
        'SELECT object_key FROM share_office_versions WHERE file_id=?', (second_id,))}
    purge_keys.update(row[0] for row in connection.execute(
        'SELECT draft_key FROM share_office_sessions WHERE file_id=?', (second_id,)))
    purge_keys.add(connection.execute('SELECT object_key FROM share_files WHERE id=?', (second_id,)).fetchone()[0])
assert len(purge_keys) > 2

class FaultOSS:
    def __init__(self, keys):
        self.remaining = set(keys)
        self.calls = 0
        self.fail_on_call = 2

    def delete(self, key):
        self.calls += 1
        if self.calls == self.fail_on_call:
            raise OSError('injected OSS delete failure')
        self.remaining.discard(key)

class PurgeHandler(FileShareHandlersMixin):
    command = 'POST'

    def __init__(self, file_id, oss):
        self.path = f'/api/file-share/admin/files/{file_id}/purge'
        self.oss = oss

    def fs_oss(self, row=None):
        return self.oss

    def fs_audit(self, conn, user_id, action, target):
        pass

    def json(self, payload, status=200):
        return payload

fault_oss = FaultOSS(purge_keys)
purge_handler = PurgeHandler(second_id, fault_oss)
owner_id = scalar('SELECT user_id FROM share_files WHERE id=?', (second_id,))
try:
    purge_handler.fs_admin(f'/files/{second_id}/purge', {}, owner_id)
except OSError as error:
    assert str(error) == 'injected OSS delete failure'
else:
    raise AssertionError('purge unexpectedly succeeded despite injected OSS failure')
assert 0 < len(fault_oss.remaining) < len(purge_keys)
assert scalar('SELECT status FROM share_files WHERE id=?', (second_id,)) == 'PURGING'
assert req(admin, f'/api/file-share/admin/files/{second_id}/restore', {})[0] == 409
fault_oss.fail_on_call = None
assert purge_handler.fs_admin(f'/files/{second_id}/purge', {}, owner_id) == {'ok': True}
assert not fault_oss.remaining
assert scalar('SELECT status FROM share_files WHERE id=?', (second_id,)) == 'DELETED'
assert scalar('SELECT COUNT(*) FROM share_office_versions WHERE file_id=?', (second_id,)) == 0
assert scalar('SELECT COUNT(*) FROM share_office_sessions WHERE file_id=?', (second_id,)) == 0
print('PASS: partial OSS deletion leaves PURGING, blocks restore, and retry completes')
