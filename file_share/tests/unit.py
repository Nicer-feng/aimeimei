"""Security and compatibility checks without external services."""
import base64
import hashlib
import hmac
from pathlib import Path
import sqlite3
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import urllib.request

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from infrastructure.storage import PrivateOSS
from file_share.security import classify
from ai_platform.backup import create_sanitized_snapshot
from ai_platform.settings import DATA_DIR, DB_PATH

config=dict(region='cn-hangzhou',bucket='example',endpoint='https://example.oss-cn-hangzhou.aliyuncs.com',access_key_id='test-id',access_key_secret='test-secret',configured=True)
url=PrivateOSS(config).signed('PUT','share/user/a.bin',{'uploadId':'test-upload','partNumber':1},{'Content-Type':'application/octet-stream','Content-MD5':'abc'})
query=parse_qs(urlparse(url).query)
assert query['x-oss-signature-version']==['OSS4-HMAC-SHA256']
assert query['x-oss-expires']==['300']
assert '/cn-hangzhou/oss/aliyun_v4_request' in query['x-oss-credential'][0]
assert len(query['x-oss-signature'][0])==64
assert 'test-secret' not in url and 'OSSAccessKeyId' not in query
for name,mime,data in [('evil.svg','image/svg+xml',b'<svg/>'),('evil.html','text/html',b'<html/>'),('evil.png','image/png',b'<svg/>')]:
    assert classify(name,mime,data)==('OTHER','application/octet-stream')
assert classify('hello.txt','text/plain',b'<script>alert(1)</script>')==('TEXT','text/plain')

snapshot=DATA_DIR/'sanitized-test.db'
create_sanitized_snapshot(DB_PATH,snapshot)
with sqlite3.connect(snapshot) as conn:
    for name in ('shares','share_sessions','share_files_relation','share_access_logs'):
        assert conn.execute('SELECT count(*) FROM '+name).fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM share_files WHERE upload_id IS NOT NULL').fetchone()[0]==0
snapshot.unlink()

opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for path,expected in [('/admin/share','文件分享中心'),('/share/abcdefghijklmnop','文件分享中心'),('/share/'+'a'*43,'对话分享'),('/ai/share/'+'a'*43,'对话分享'),('/cat','小猫书'),('/xiaoji','槑槑小记'),('/','AI槑槑')]:
    with opener.open('http://127.0.0.1:18765'+path) as response:
        assert expected in response.read().decode(),path
print('PASS: canonical OSS signature, HTML/SVG safety, backup sanitization, legacy AI/cat/home routes')

from io import BytesIO
from urllib.error import HTTPError
from infrastructure.storage import StorageSecurityError
oss=PrivateOSS(config)
with patch.object(oss,'request',return_value=BytesIO(b'<AccessControlPolicy><AccessControlList><Grant>private</Grant></AccessControlList></AccessControlPolicy>')), patch('infrastructure.storage.urllib.request.urlopen',side_effect=HTTPError('',403,'Forbidden',{},None)):
    oss.verify_private('share/test')
with patch.object(oss,'request',return_value=BytesIO(b'<AccessControlPolicy><AccessControlList><Grant>private</Grant></AccessControlList></AccessControlPolicy>')), patch('infrastructure.storage.urllib.request.urlopen',return_value=BytesIO(b'x')):
    try:
        oss.verify_private('share/test')
        raise AssertionError('Anonymous access was accepted')
    except StorageSecurityError:
        pass
print('PASS: object ACL and anonymous-access fail-closed verification')
