import os, sys, json, threading, hashlib, uuid, re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
from urllib.error import HTTPError
if not os.environ.get('AI_PLATFORM_DATA'):
 raise RuntimeError('Set AI_PLATFORM_DATA to a disposable test directory')
os.environ['SHARE_PUBLIC_ORIGIN']='http://127.0.0.1:18765'
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from app import AIPlatformServer,AppHandler
from ai_platform.database import init_db,db
from ai_platform.runtime import password_hash
from file_share.database import init_share_db
from file_share.handlers import FileShareHandlersMixin
secrets_data={'admin_key':'test-key','family_password_hash':password_hash('test-password')}
init_db(secrets_data);init_share_db()
with db() as conn:
 conn.execute("UPDATE users SET password_hash=? WHERE username='admin'",(password_hash('test-password'),))
 for uid,role in [('other-admin','admin'),('member','family')]:
  conn.execute('INSERT OR IGNORE INTO users(id,username,display_name,password_hash,role,is_active,created_at,updated_at) VALUES(?,?,?,?,?,1,0,0)',(uid,uid,uid,password_hash('test-password'),role))
objects={}; uploads={};parts={}
class FakeOSS:
 config={'bucket':'test-private-bucket'}
 def begin(self,key,content_type="application/octet-stream"):
  uid=uuid.uuid4().hex;uploads[uid]=key;return uid
 def signed(self,method,key,query=None,headers=None,ttl=300):
  return 'http://127.0.0.1:18766/object/'+key+'?'+__import__('urllib.parse',fromlist=['urlencode']).urlencode(query or {})
 def complete(self,key,upload_id,items):
  objects[key]=b''.join(parts[(upload_id,n)] for n,_ in items)
 def head(self,key):
  if key not in objects:raise HTTPError('',404,'not found',{},None)
  return {'Content-Length':str(len(objects[key]))}
 def sample(self,key):return objects[key][:4096]
 def verify_private(self,key):pass
 def delete(self,key):objects.pop(key,None)
 def abort(self,key,upload_id):uploads.pop(upload_id,None)
 def access_url(self,key,filename,mime,download=False):
  return self.signed('GET',key,{'mime':mime,'download':int(download)})
FileShareHandlersMixin.fs_oss=lambda self,row=None:FakeOSS()
class Storage(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def cors(self):
  self.send_header('Access-Control-Allow-Origin','http://127.0.0.1:18765');self.send_header('Access-Control-Allow-Headers','Content-Type,Content-MD5,Range');self.send_header('Access-Control-Allow-Methods','GET,PUT,HEAD,OPTIONS');self.send_header('Access-Control-Expose-Headers','ETag,Content-Length,Content-Range');self.send_header('Accept-Ranges','bytes')
 def do_OPTIONS(self):self.send_response(204);self.cors();self.end_headers()
 def do_PUT(self):
  q=parse_qs(urlparse(self.path).query);body=self.rfile.read(int(self.headers['Content-Length']));parts[(q['uploadId'][0],int(q['partNumber'][0]))]=body;self.send_response(200);self.cors();self.send_header('ETag','"'+hashlib.md5(body).hexdigest()+'"');self.send_header('Content-Length','0');self.end_headers()
 def do_GET(self):
  p=urlparse(self.path);key=p.path.removeprefix('/object/');body=objects.get(key,b'');q=parse_qs(p.query);start,end=0,len(body)-1
  if self.headers.get('Range'):
   bounds=self.headers['Range'].split('=')[1].split('-');start=int(bounds[0]);end=min(end,int(bounds[1])) if bounds[1] else end;self.send_response(206);self.send_header('Content-Range',f'bytes {start}-{end}/{len(body)}')
  else:self.send_response(200)
  self.cors();self.send_header('Content-Type',q.get('mime',['application/octet-stream'])[0]);self.send_header('Content-Length',str(max(0,end-start+1)))
  if q.get('download')==['1']:self.send_header('Content-Disposition','attachment; filename=test-file')
  self.end_headers();self.wfile.write(body[start:end+1])
threading.Thread(target=ThreadingHTTPServer(('127.0.0.1',18766),Storage).serve_forever,daemon=True).start()
server=AIPlatformServer(('127.0.0.1',18765),AppHandler,secrets_data)
print('TEST SERVER READY',flush=True)
server.serve_forever()
