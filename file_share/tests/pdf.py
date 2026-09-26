"""Real PDF bytes through isolated admin, OSS, version and public-share routes."""
import base64
from io import BytesIO
import hashlib
import http.cookiejar
import json
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
import sys

from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, NameObject, NumberObject

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ai_platform.backup import create_sanitized_snapshot
from ai_platform.settings import DB_PATH

BASE = 'http://127.0.0.1:18765'
API = '/api/file-share/admin'
PDF = API + '/pdf'


def client():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                       urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def req(opener, path, data=None):
    request = urllib.request.Request(BASE + path,
        data=json.dumps(data).encode() if data is not None else None,
        headers={'Content-Type': 'application/json', 'X-Share-Request': '1', 'User-Agent': 'PDF-Test/1'})
    try:
        with opener.open(request, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)


def login(opener, username='admin'):
    _, captcha = req(opener, '/api/captcha')
    answer = ''.join(re.findall(r'<text[^>]*>(.*?)</text>', captcha['image_svg']))
    status, response = req(opener, '/api/login', {'username': username, 'password': 'test-password',
        'captcha_id': captcha['captcha_id'], 'captcha': answer})
    assert status == 200, (status, response)


def pdf_bytes(pages=1, *, encrypted=False, outline=False, userunit=False, automatic_action=False):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    if outline:
        writer.add_outline_item('First page', 0)
    if userunit:
        writer.pages[0][NameObject('/UserUnit')] = NumberObject(2)
    if automatic_action:
        writer._root_object[NameObject('/AA')] = DictionaryObject()
    if encrypted:
        writer.encrypt('password')
    stream = BytesIO()
    writer.write(stream)
    return stream.getvalue()


def upload_file(opener, body, name='pages.pdf'):
    status, job = req(opener, API + '/uploads', {'filename': name, 'size': len(body),
        'mime_type': 'application/pdf', 'sha256': hashlib.sha256(body).hexdigest()})
    assert status == 200, (status, job)
    etags = []
    for number, start in enumerate(range(0, len(body), job['part_size']), 1):
        chunk = body[start:start + job['part_size']]
        status, permit = req(opener, API + '/uploads/' + job['id'] + '/part',
                             {'part_number': number, 'content_md5': base64.b64encode(hashlib.md5(chunk).digest()).decode()})
        assert status == 200, (status, permit)
        with opener.open(urllib.request.Request(permit['url'], data=chunk,
                                                headers=permit['headers'], method='PUT')) as response:
            etags.append({'part_number': number, 'etag': response.headers['ETag']})
    status, file = req(opener, API + '/uploads/' + job['id'] + '/complete', {'parts': etags})
    assert status == 200, (status, file)
    return file['id']


def start_version(opener, file_id, revision, body):
    return req(opener, PDF + '/files/' + file_id + '/start',
               {'size': len(body), 'sha256': hashlib.sha256(body).hexdigest(), 'revision': revision})


def send_version(opener, job, body):
    etags = []
    for number, start in enumerate(range(0, len(body), job['part_size']), 1):
        chunk = body[start:start + job['part_size']]
        status, permit = req(opener, PDF + '/uploads/' + job['id'] + '/part',
                             {'part_number': number, 'content_md5': base64.b64encode(hashlib.md5(chunk).digest()).decode()})
        assert status == 200, (status, permit)
        with opener.open(urllib.request.Request(permit['url'], data=chunk,
                                                headers=permit['headers'], method='PUT')) as response:
            etags.append({'part_number': number, 'etag': response.headers['ETag']})
    return etags


def file_scalar(sql, args=()):
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(sql, args).fetchone()
        return row[0] if row else None


def raw_download(opener, url):
    with opener.open(url, timeout=20) as response:
        return response.read()


admin, other, member, anon = client(), client(), client(), client()
login(admin)
login(other, 'other-admin')
login(member, 'member')
original = pdf_bytes(1)
changed = pdf_bytes(2)
assert len(PdfReader(BytesIO(original)).pages) == 1
assert len(PdfReader(BytesIO(changed)).pages) == 2
file_id = upload_file(admin, original)
assert req(anon, PDF + '/files/' + file_id + '/context')[0] == 401
assert req(member, PDF + '/files/' + file_id + '/context')[0] in (401, 403)
assert req(other, PDF + '/files/' + file_id + '/context')[0] == 404
status, ctx = req(admin, PDF + '/files/' + file_id + '/context')
assert status == 200 and ctx['max_bytes'] == 20 * 1024 * 1024 and ctx['max_pages'] == 100, (status, ctx)
assert raw_download(admin, ctx['url']) == original
baseline = req(admin, PDF + '/files/' + file_id + '/versions')[1]['items']
assert len(baseline) == 1 and baseline[0]['published'] and baseline[0]['number'] == 1
assert file_scalar('SELECT source_session_id FROM share_office_versions WHERE id=?', (baseline[0]['id'],)) is None
assert next(item for item in req(admin, API + '/files')[1]['items'] if item['id'] == file_id)['last_edited_at'] is None
assert req(other, PDF + '/files/' + file_id + '/versions')[0] == 404
assert req(other, PDF + '/files/' + file_id + '/start',
           {'size': len(changed), 'sha256': hashlib.sha256(changed).hexdigest(), 'revision': ctx['revision']})[0] == 404
status, share = req(admin, API + '/shares', {'title': 'PDF version test', 'file_ids': [file_id]})
assert status == 201, (status, share)
public = '/api/file-share/public/' + share['share_code']
assert req(anon, public + '/open', {})[0] == 200
status, link = req(anon, public + '/download', {'file_id': file_id})
assert status == 200 and raw_download(anon, link['url']) == original

# A pending multipart job blocks a second save and trash; abort is idempotent.
status, abandoned = start_version(admin, file_id, ctx['revision'], changed)
assert status == 200 and abandoned['part_count'] == 1, (status, abandoned)
assert start_version(admin, file_id, ctx['revision'], changed)[0] == 409
assert req(admin, API + '/files/' + file_id + '/trash', {})[0] == 409
snapshot_path = DB_PATH.with_name('pdf-sanitized-test.db')
create_sanitized_snapshot(DB_PATH, snapshot_path)
with sqlite3.connect(snapshot_path) as conn:
    assert conn.execute('SELECT COUNT(*) FROM share_pdf_uploads').fetchone()[0] == 0
snapshot_path.unlink()
assert req(admin, PDF + '/uploads/' + abandoned['id'] + '/abort', {})[0] == 200
assert req(admin, PDF + '/uploads/' + abandoned['id'] + '/abort', {})[0] == 200
assert file_scalar('SELECT status FROM share_pdf_uploads WHERE id=?', (abandoned['id'],)) == 'ABORTED'
status, expired = start_version(admin, file_id, ctx['revision'], changed)
assert status == 200, (status, expired)
with sqlite3.connect(DB_PATH) as conn:
    conn.execute('UPDATE share_pdf_uploads SET expires_at=0 WHERE id=?', (expired['id'],))
assert req(admin, PDF + '/files/' + file_id + '/context')[0] == 200
assert file_scalar('SELECT status FROM share_pdf_uploads WHERE id=?', (expired['id'],)) == 'ABORTED'
status, orphan = start_version(admin, file_id, ctx['revision'], changed)
assert status == 200, (status, orphan)
with sqlite3.connect(DB_PATH) as conn:
    conn.execute("UPDATE share_pdf_uploads SET status='CLEANUP',updated_at=0 WHERE id=?", (orphan['id'],))
assert req(admin, PDF + '/files/' + file_id + '/context')[0] == 200
assert file_scalar('SELECT status FROM share_pdf_uploads WHERE id=?', (orphan['id'],)) == 'ABORTED'

status, job = start_version(admin, file_id, ctx['revision'], changed)
assert status == 200, (status, job)
parts = send_version(admin, job, changed)
status, saved = req(admin, PDF + '/uploads/' + job['id'] + '/complete', {'parts': parts})
assert status == 200 and saved['version']['number'] == 2 and saved['version']['pages'] == 2, (status, saved)
assert not saved['version']['published'] and saved['revision'] != ctx['revision']
status, repeated = req(admin, PDF + '/uploads/' + job['id'] + '/complete', {'parts': parts})
assert status == 200 and repeated['version']['id'] == saved['version']['id'], (status, repeated)
assert start_version(admin, file_id, ctx['revision'], changed)[0] == 409  # second tab's stale source
assert file_scalar('SELECT object_key FROM share_files WHERE id=?', (file_id,)) != file_scalar(
    'SELECT object_key FROM share_office_versions WHERE id=?', (saved['version']['id'],))
assert next(item for item in req(admin, API + '/files')[1]['items'] if item['id'] == file_id)['last_edited_at'] == saved['version']['created_at']
assert req(admin, API + '/files/' + file_id + '/rename', {'filename': 'renamed-pages.pdf'})[0] == 200
assert next(item for item in req(admin, API + '/files')[1]['items'] if item['id'] == file_id)['last_edited_at'] == saved['version']['created_at']
status, old_link = req(anon, public + '/download', {'file_id': file_id})
assert status == 200 and raw_download(anon, old_link['url']) == original
status, pub = req(admin, PDF + '/files/' + file_id + '/publish', {'version_id': saved['version']['id']})
assert status == 200 and pub['version']['published'], (status, pub)
status, new_link = req(anon, public + '/download', {'file_id': file_id})
assert status == 200 and raw_download(anon, new_link['url']) == changed
assert req(admin, PDF + '/files/' + file_id + '/publish', {'version_id': baseline[0]['id']})[0] == 200
status, restored_link = req(anon, public + '/download', {'file_id': file_id})
assert status == 200 and raw_download(anon, restored_link['url']) == original
assert next(item for item in req(admin, API + '/files')[1]['items'] if item['id'] == file_id)['last_edited_at'] == saved['version']['created_at']
print('PASS: PDF page-version save, source conflict, OSS bytes, publication, rollback, permissions, backup redaction')

# Valid PDF bytes with unsupported structures and malformed output are denied.
for name, body in [('encrypted.pdf', pdf_bytes(encrypted=True)),
                   ('outline.pdf', pdf_bytes(outline=True)),
                   ('userunit.pdf', pdf_bytes(userunit=True)),
                   ('automatic-action.pdf', pdf_bytes(automatic_action=True)),
                   ('many-pages.pdf', pdf_bytes(101)),
                   ('signed.pdf', original + b'\n/ByteRange [0 1 2 3]\n')]:
    candidate = upload_file(admin, body, name)
    assert req(admin, PDF + '/files/' + candidate + '/context')[0] == 422, name
    # An API caller that constructs a revision without using context is refused too.
    with sqlite3.connect(DB_PATH) as conn:
        source = conn.execute('SELECT id,object_key,sha256,size FROM share_files WHERE id=?',
                              (candidate,)).fetchone()
        latest = conn.execute('SELECT MAX(version_no) FROM share_office_versions WHERE file_id=?',
                              (candidate,)).fetchone()[0]
    forged_revision = hashlib.sha256('\0'.join((source[0], source[1], source[2],
                                                  str(source[3]), str(latest))).encode()).hexdigest()
    assert start_version(admin, candidate, forged_revision, changed)[0] == 422, name
malformed = b'%PDF-1.7\n1 0 obj << >> endobj\n%%EOF\n'
status, latest_context = req(admin, PDF + '/files/' + file_id + '/context')
assert status == 200, (status, latest_context)
status, invalid_job = start_version(admin, file_id, latest_context['revision'], malformed)
assert status == 200, (status, invalid_job)
parts = send_version(admin, invalid_job, malformed)
assert req(admin, PDF + '/uploads/' + invalid_job['id'] + '/complete', {'parts': parts})[0] == 422
assert file_scalar('SELECT status FROM share_pdf_uploads WHERE id=?', (invalid_job['id'],)) == 'ABORTED'
assert req(admin, API + '/files/' + file_id + '/trash', {})[0] == 200
assert req(admin, API + '/files/' + file_id + '/purge', {})[0] == 200
assert file_scalar('SELECT COUNT(*) FROM share_office_versions WHERE file_id=?', (file_id,)) == 0
assert file_scalar('SELECT COUNT(*) FROM share_pdf_uploads WHERE file_id=?', (file_id,)) == 0
print('PASS: encrypted/bookmarked/signed PDF refusal, malformed result cleanup, trash and purge')
