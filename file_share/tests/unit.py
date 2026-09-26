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
from file_share.imm_office import _utc_expiry
from file_share.office_service import OfficeService, expiry_epoch
from types import SimpleNamespace
import os
from file_share.security import classify
from ai_platform.backup import create_sanitized_snapshot
from ai_platform.settings import DATA_DIR, DB_PATH

assert _utc_expiry('2035-08-30T13:13:11.347146982Z') == '2035-08-30T13:13:11.347146Z'
assert expiry_epoch('2035-08-30T13:13:11.347146982Z') > 0
dummy=SimpleNamespace(server=SimpleNamespace(secrets={}))
with patch('file_share.office_service.shared_storage_config',return_value={'configured':True,'region':'cn-hangzhou'}):
    with patch.dict(os.environ, {'IMM_OFFICE_ENABLED':'0','IMM_PROJECT_NAME':'trial','IMM_REGION':'cn-hangzhou'}):
        assert OfficeService(dummy,'admin')._settings()['enabled'] is False
    with patch.dict(os.environ, {'IMM_OFFICE_ENABLED':'1','IMM_PROJECT_NAME':'trial','IMM_REGION':'cn-hangzhou'}):
        assert OfficeService(dummy,'admin')._settings()['enabled'] is True
    with patch.dict(os.environ, {'IMM_OFFICE_ENABLED':'1','IMM_PROJECT_NAME':'trial','IMM_REGION':'cn-shanghai'}):
        assert OfficeService(dummy,'admin')._settings()['enabled'] is False

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
    for name in ('shares','share_sessions','share_office_sessions','share_pdf_uploads','share_files_relation','share_access_logs'):
        assert conn.execute('SELECT count(*) FROM '+name).fetchone()[0]==0
    assert conn.execute('SELECT count(*) FROM share_files WHERE upload_id IS NOT NULL').fetchone()[0]==0
snapshot.unlink()

opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
for path,expected in [('/admin/share','槑槑云'),('/share/abcdefghijklmnop','槑槑云'),('/share/'+'a'*43,'对话分享'),('/ai/share/'+'a'*43,'对话分享'),('/cat','小猫书'),('/xiaoji','槑槑小记'),('/','AI槑槑')]:
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

# IP geolocation enrichment is asynchronous, cached and never uses real keys.
import time
from contextlib import closing
from unittest.mock import Mock
from urllib.error import HTTPError
from infrastructure import ip_geolocation as geo
from ai_platform.database import db
assert geo.public_ip('127.0.0.1') is None
assert geo.public_ip('192.168.1.1') is None
assert geo.public_ip('::1') is None
assert geo.public_ip('not-an-ip') is None
assert geo.public_ip('::ffff:114.114.114.114') == '114.114.114.114'
assert geo.public_ip('2001:4860:4860::8888')
with closing(db()) as conn, conn:
    conn.execute('DELETE FROM infrastructure_ip_locations')
rows=[{'ip':'114.114.114.114'}, {'ip':'114.114.114.114'}, {'ip':'127.0.0.1'}]
with patch.object(geo,'api_key',return_value='test-key'), patch.object(geo,'lookup',return_value={'country':'China','province':'Jiangsu','city':'Nanjing'}) as lookup:
    with closing(db()) as conn:
        started=time.monotonic()
        result=geo.enrich_logs(conn,rows,{})
        assert time.monotonic()-started<1
        assert result[0]['geolocation_status']=='pending' and result[2]['geolocation_status']=='private'
    geo._jobs.join()
    assert lookup.call_count==1
    with closing(db()) as conn:
        result=geo.enrich_logs(conn,[{'ip':'114.114.114.114'}],{})
        assert result[0]['city']=='Nanjing' and result[0]['geolocation_status']=='ready'
    assert lookup.call_count==1
with patch.object(geo,'lookup',side_effect=HTTPError('',429,'limited',{},None)):
    geo._resolve('8.8.8.8','test-key')
assert not geo.schedule('1.1.1.1','test-key')
with closing(db()) as conn:
    assert conn.execute("SELECT status FROM infrastructure_ip_locations WHERE ip='8.8.8.8'").fetchone()[0]=='unavailable'
geo._blocked_until=0
with patch.object(geo,'api_key',return_value=''):
    with closing(db()) as conn:
        assert geo.enrich_logs(conn,[{'ip':'1.1.1.1'}],{})[0]['geolocation_status']=='unconfigured'
with patch.object(geo,'urlopen') as fetch:
    fetch.return_value.__enter__.return_value.read.return_value=b'{"ip":"114.114.114.114","country_name":"China","region_name":"Jiangsu","city_name":"Nanjing"}'
    assert geo.lookup('114.114.114.114','test-key')['city']=='Nanjing'
    request=fetch.call_args.args[0]
    assert 'test-key' not in request.full_url
    assert request.get_header('Authorization')=='Bearer test-key'
    assert fetch.call_args.kwargs['timeout']==4
snapshot=DATA_DIR/'geo-sanitized.db'
create_sanitized_snapshot(DB_PATH,snapshot)
with sqlite3.connect(snapshot) as conn:
    assert conn.execute('SELECT count(*) FROM infrastructure_ip_locations').fetchone()[0]==0
print('PASS: geolocation async enrichment, duplicate IP dedup, cache, private IPv4/IPv6, quota backoff, key isolation, sanitized backup')
