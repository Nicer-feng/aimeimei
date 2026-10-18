"""Isolated HTTP workflow: IMM drafts, private versions, and explicit publication."""
import base64
from concurrent.futures import ThreadPoolExecutor
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
login(admin);login(other,'other-admin');login(member,'member')
route='/api/file-share/admin/office/collaboration'
req(admin,'/api/file-share/admin/platform/access',{'user_id':'member','enabled':True})
assert req(member,route+'/config')[0]==200
assert req(anon,route+'/shared')[0]==401
body=b'PK\x03\x04shared original'
s,u=req(admin,'/api/file-share/admin/uploads',{'filename':'collaborate.docx','size':len(body),'mime_type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','sha256':hashlib.sha256(body).hexdigest()});assert s==200,(s,u)
fid=u['id']
_,permit=req(admin,f'/api/file-share/admin/uploads/{fid}/part',{'part_number':1,'content_md5':base64.b64encode(hashlib.md5(body).digest()).decode()})
with admin.open(urllib.request.Request(permit['url'],data=body,headers=permit['headers'],method='PUT')) as response:etag=response.headers['ETag']
assert req(admin,f'/api/file-share/admin/uploads/{fid}/complete',{'parts':[{'part_number':1,'etag':etag}]})[0]==200
m=f'{route}/files/{fid}/members';start=f'{route}/files/{fid}/start'
assert req(other,start,{})[0]==404
assert req(other,m)[0]==404
assert req(admin,m,{'action':'invite','username':'not-an-account'})[0]==404
assert req(admin,m,{'action':'invite','username':'other-admin'})[0]==200
assert req(admin,m,{'action':'invite','username':'member'})[0]==200
assert req(member,route+'/shared')[1]['items'][0]['id']==fid
assert not req(member,'/api/file-share/admin/files')[1]['items']
assert req(member,m,{'action':'invite','username':'admin'})[0]==403
sa,a=req(admin,start,{});sb,b=req(other,start,{});sc,c=req(member,start,{})
assert sa==sb==sc==200,(sa,a,sb,b,sc,c)
assert len({a['access_token'],b['access_token'],c['access_token']})==3
room=scalar('SELECT room_id FROM share_office_participants WHERE id=?',(a['session_id'],))
assert scalar('SELECT room_id FROM share_office_participants WHERE id=?',(b['session_id'],))==room
assert scalar('SELECT count(*) FROM share_office_sessions WHERE file_id=?',(fid,))==1
assert req(admin,f'/api/file-share/admin/office/sessions/{room}/close',{})[0]==409
key=scalar('SELECT draft_key FROM share_office_sessions WHERE id=?',(room,))
assert req(admin,f"{route}/sessions/{a['session_id']}/snapshot",{})[0]==200
assert scalar('SELECT count(*) FROM share_office_versions WHERE file_id=?',(fid,))==1
updated=b'PK\x03\x04shared edits from A and B'
url='http://127.0.0.1:18766/object/'+key+'?testWrite=1'
with admin.open(urllib.request.Request(url,data=updated,method='PUT')):pass
paths=[f"{route}/sessions/{x['session_id']}/snapshot" for x in [a,b]]
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda pair:req(*pair),[(admin,paths[0],{}),(other,paths[1],{})]))
assert all(x[0]==200 for x in results),results
assert results[0][1]['version']['id']==results[1][1]['version']['id']
version=results[0][1]['version']['id']
assert not req(member,f'{route}/files/{fid}/versions')[1]['can_publish']
assert req(member,f'{route}/files/{fid}/publish',{'version_id':version})[0]==403
_,share=req(admin,'/api/file-share/admin/shares',{'title':'collab readonly','file_ids':[fid]})
public='/api/file-share/public/'+share['share_code']
assert req(anon,public+'/open',{})[0]==200
status,data=req(anon,public+'/download',{'file_id':fid});assert status==200
with anon.open(data['url']) as response:assert response.read()==body
assert req(admin,f'{route}/files/{fid}/publish',{'version_id':version})[0]==200
status,data=req(anon,public+'/download',{'file_id':fid})
with anon.open(data['url']) as response:assert response.read()==updated
assert req(admin,f"{route}/sessions/{a['session_id']}/close",{})[0]==200
assert req(admin,f"{route}/sessions/{a['session_id']}/close",{})[0]==200
assert req(member,f"{route}/sessions/{c['session_id']}/status",{})[0]==200
assert scalar('SELECT status FROM share_office_sessions WHERE id=?',(room,))=='ACTIVE'
assert req(other,f"{route}/sessions/{c['session_id']}/refresh",{'access_token':c['access_token'],'refresh_token':c['refresh_token']})[0]==404
old={'access_token':c['access_token'],'refresh_token':c['refresh_token']}
assert req(member,f"{route}/sessions/{c['session_id']}/refresh",old)[0]==200
assert req(member,f"{route}/sessions/{c['session_id']}/refresh",old)[0]==409
s,removed=req(admin,m,{'action':'remove','user_id':'member'});assert s==200,(s,removed)
assert removed['restart_required']
assert req(member,start,{})[0]==404
assert not req(member,route+'/shared')[1]['items']
assert req(other,f"{route}/sessions/{b['session_id']}/snapshot",{})[0]==409
status,rejoined=req(other,start,{});assert status==200,(status,rejoined)
newroom=scalar('SELECT room_id FROM share_office_participants WHERE id=?',(rejoined['session_id'],))
newkey=scalar('SELECT draft_key FROM share_office_sessions WHERE id=?',(newroom,))
assert newroom!=room and newkey!=key
# Late writes from revoked credentials cannot alter the new round.
with admin.open(urllib.request.Request(url,data=b'PK\x03\x04late write',method='PUT')):pass
assert fake_object_bytes(admin,newkey)==updated
assert req(other,f"{route}/sessions/{rejoined['session_id']}/close",{})[0]==200
# Same account on two devices receives independent tokens; leaving one keeps the other.
_,d1=req(admin,start,{});_,d2=req(admin,start,{})
assert d1['session_id']!=d2['session_id'] and d1['access_token']!=d2['access_token']
assert req(admin,f"{route}/sessions/{d1['session_id']}/close",{})[0]==200
assert req(admin,f"{route}/sessions/{d2['session_id']}/status",{})[0]==200
assert req(admin,f"{route}/sessions/{d2['session_id']}/close",{})[0]==200
# A non-admin owns the file; an invited user can create the room first.
s,u=req(member,'/api/file-share/admin/uploads',{'filename':'member-owned.xlsx','size':len(body),'mime_type':'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet','sha256':hashlib.sha256(body).hexdigest()});assert s==200
own=u['id']
_,permit=req(member,f'/api/file-share/admin/uploads/{own}/part',{'part_number':1,'content_md5':base64.b64encode(hashlib.md5(body).digest()).decode()})
with member.open(urllib.request.Request(permit['url'],data=body,headers=permit['headers'],method='PUT')) as response:etag=response.headers['ETag']
assert req(member,f'/api/file-share/admin/uploads/{own}/complete',{'parts':[{'part_number':1,'etag':etag}]})[0]==200
assert req(member,f'{route}/files/{own}/members',{'action':'invite','username':'other-admin'})[0]==200
_,first=req(other,f'{route}/files/{own}/start',{});_,second=req(member,f'{route}/files/{own}/start',{})
assert req(member,f"{route}/sessions/{second['session_id']}/snapshot",{})[0]==200
assert req(other,f'{route}/files/{own}/members')[0]==403
assert req(member,f'{route}/files/{own}/versions')[1]['can_publish']
assert req(other,f'/api/file-share/admin/files/{own}/rename',{'filename':'stolen.xlsx'})[0]==404
assert req(other,f"{route}/sessions/{first['session_id']}/close",{})[0]==200
assert req(member,f"{route}/sessions/{second['session_id']}/close",{})[0]==200
# Automatic checkpoints stop at the version cap; manual save remains available.
_,cap=req(member,f'{route}/files/{own}/start',{})
caproom=scalar('SELECT room_id FROM share_office_participants WHERE id=?',(cap['session_id'],))
capkey=scalar('SELECT draft_key FROM share_office_sessions WHERE id=?',(caproom,))
with member.open(urllib.request.Request('http://127.0.0.1:18766/object/'+capkey+'?testWrite=1',data=b'PK\x03\x04capped new draft',method='PUT')):pass
with sqlite3.connect(DB_PATH) as conn:
 for i in range(30):
  conn.execute('INSERT INTO share_office_versions(id,file_id,version_no,object_key,size,sha256,created_by,created_at) VALUES(?,?,?,?,?,?,?,?)',
               ('cap'+str(i),own,100+i,'test-cap-'+str(i),1,'0'*64,'member',0))
count=scalar('SELECT count(*) FROM share_office_versions WHERE file_id=?',(own,))
assert req(member,f"{route}/sessions/{cap['session_id']}/snapshot",{'automatic':True})[1]['automatic_paused']
assert scalar('SELECT count(*) FROM share_office_versions WHERE file_id=?',(own,))==count
assert req(member,f"{route}/sessions/{cap['session_id']}/snapshot",{})[0]==200
assert scalar('SELECT count(*) FROM share_office_versions WHERE file_id=?',(own,))==count+1
assert req(member,f"{route}/sessions/{cap['session_id']}/close",{})[0]==200
snapshot=DB_PATH.with_name('collab-sanitized.db');create_sanitized_snapshot(DB_PATH,snapshot)
with sqlite3.connect(snapshot) as conn:
 for t in ['share_office_participants','share_office_rooms','share_office_collaborators']:assert conn.execute('SELECT count(*) FROM '+t).fetchone()[0]==0
snapshot.unlink()
req(admin,'/api/file-share/admin/platform/access',{'user_id':'member','enabled':False})
assert req(member,route+'/config')[0]==401
print('PASS: invitations, cloud access, owner isolation, independent tokens, one shared draft, concurrent snapshots, owner-only publication, share isolation, independent close, token rotation, revocation fencing, same-account devices, sanitized backup')
