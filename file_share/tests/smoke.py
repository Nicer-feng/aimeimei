import urllib.request,urllib.error,http.cookiejar,json,re,concurrent.futures,hashlib,base64,sys
BASE='http://127.0.0.1:18765'
def client():return urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def req(c,path,data=None):
 request=urllib.request.Request(BASE+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json','X-Share-Request':'1','User-Agent':'FileShare-Test/1'})
 try:
  with c.open(request,timeout=30) as r:return r.status,json.load(r)
 except urllib.error.HTTPError as e:return e.code,json.load(e)
def login(c,username='admin'):
 _,d=req(c,'/api/captcha');answer=''.join(re.findall(r'<text[^>]*>(.*?)</text>',d['image_svg']))
 status,d=req(c,'/api/login',{'username':username,'password':'test-password','captcha_id':d['captcha_id'],'captcha':answer});assert status==200,(status,d)
a=client();login(a);other=client();login(other,'other-admin');member=client();login(member,'member');anon=client()
assert req(anon,'/api/file-share/admin/files')[0]==401
assert req(member,'/api/file-share/admin/files')[0]==401
payload=b'\x89PNG\r\n\x1a\n'+b'hello test'
status,upload=req(a,'/api/file-share/admin/uploads',{'filename':'test.png','size':len(payload),'mime_type':'image/png','sha256':hashlib.sha256(payload).hexdigest()});assert status==200,(status,upload)
fid=upload['id']
_,permit=req(a,f'/api/file-share/admin/uploads/{fid}/part',{'part_number':1,'content_md5':base64.b64encode(hashlib.md5(payload).digest()).decode()})
with a.open(urllib.request.Request(permit['url'],data=payload,headers=permit['headers'],method='PUT')) as response:etag=response.headers['ETag']
status,d=req(a,f'/api/file-share/admin/uploads/{fid}/complete',{'parts':[{'part_number':1,'etag':etag}]});assert status==200,(status,d)
assert req(other,f'/api/file-share/admin/files/{fid}/trash',{})[0]==404
status,d=req(a,'/api/file-share/admin/shares',{'title':'Test share','file_ids':[fid],'password_mode':'set','password':'abcd','max_views':10,'max_downloads':3});assert status==201,(status,d)
sid,code=d['id'],d['share_code'];base=f'/api/file-share/public/{code}'
assert len(code)==16
assert req(anon,base)[1]=={'password_required':True}
assert req(anon,base+'/open',{})[0]==401
assert req(anon,base+'/password',{'password':'bad!'})[0]==403
status,d=req(anon,base+'/password',{'password':'abcd'});assert status==200,(status,d)
assert len(d['files'])==1

rename=f'/api/file-share/admin/files/{fid}/rename'
assert req(other,rename,{'filename':'other.png'})[0]==404
assert req(anon,rename,{'filename':'other.png'})[0]==401
for invalid in ['../bad.png','bad/hi.png','bad\\hi.png','bad\n.png','new.html','', 'x'*241+'.png']:
 assert req(a,rename,{'filename':invalid})[0]==400,invalid
assert req(a,rename,{'filename':'新名称.png'})[0]==200
assert req(anon,base+'/open',{})[1]['files'][0]['filename']=='新名称.png'
assert req(a,f'/api/file-share/admin/shares/{sid}')[1]['files'][0]['filename']=='新名称.png'
assert req(a,'/api/file-share/admin/files?search='+urllib.parse.quote('新名称'))[1]['total']==1
assert req(a,'/api/file-share/admin/version')[1]['version']==__import__('pathlib').Path(__file__).resolve().parents[1].joinpath('VERSION').read_text().strip()
assert req(anon,'/api/file-share/admin/version')[0]==401
assert req(a,rename,{'filename':'test.png'})[0]==200
print('PASS: rename authorization, unsafe names, immutable extension, existing share and search, version endpoint')

assert req(anon,base+'/preview',{'file_id':fid})[0]==200
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:results=list(pool.map(lambda _:req(anon,base+'/download',{'file_id':fid})[0],range(8)))
assert results.count(200)==3 and results.count(410)==5,results
stats=req(a,f'/api/file-share/admin/shares/{sid}')[1]
assert stats['download_count']==3 and stats['view_count']==2 and stats['stats']['unique_ips']==1,stats
assert stats['stats']['uv']==1
assert req(a,f'/api/file-share/admin/shares/{sid}/edit',{'password_mode':'set','password':'newpass','max_downloads':9})[0]==200
assert req(anon,base+'/preview',{'file_id':fid})[0]==403
assert req(anon,base+'/password',{'password':'abcd'})[0]==403
assert req(anon,base+'/password',{'password':'newpass'})[0]==200
assert req(a,f'/api/file-share/admin/files/{fid}/trash',{})[0]==200
assert req(a,rename,{'filename':'trash.png'})[0]==409
assert req(anon,base+'/preview',{'file_id':fid})[0]==403
assert req(a,f'/api/file-share/admin/files/{fid}/restore',{})[0]==200
assert req(anon,base+'/preview',{'file_id':fid})[0]==200
assert req(a,f'/api/file-share/admin/shares/{sid}/pause',{})[0]==200
assert req(anon,base)[0]==410
assert req(a,f'/api/file-share/admin/shares/{sid}/resume',{})[0]==200
assert req(anon,base+'/password',{'password':'newpass'})[0]==200
assert req(a,f'/api/file-share/admin/shares/{sid}/revoke',{})[0]==200
assert req(anon,base)[0]==410
assert req(anon,base+'/download',{'file_id':fid})[0]==410
assert req(a,f'/api/file-share/admin/shares/{sid}/resume',{})[0]==409
_,d=req(a,'/api/file-share/admin/shares',{'title':'View cap','file_ids':[fid],'max_views':10})
base='/api/file-share/public/'+d['share_code']
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:results=list(pool.map(lambda _:req(client(),base+'/open',{})[0],range(16)))
assert results.count(200)==10 and results.count(410)==6,results
stats=req(a,f"/api/file-share/admin/shares/{d['id']}")[1]
assert stats['view_count']==10 and stats['stats']['uv']==1,stats
assert req(a,'/api/file-share/admin/uploads',{'filename':'../evil.html','size':1,'sha256':'a'*64})[0]==400
assert req(a,'/api/file-share/admin/overview')[0]==200
assert req(a,'/api/file-share/admin/logs')[0]==200
print('PASS: login, admin isolation, multipart, password, preview, atomic downloads 3/8, atomic views 10/16, UV, password invalidation, trash/restore, pause/resume/revoke, traversal')

# Restricted preview types, permission flags, expiration, sessionless access and CSRF.
for allow_preview,allow_download in [(False,True),(True,False)]:
 _,d=req(a,'/api/file-share/admin/shares',{'title':'Permission test','file_ids':[fid],'allow_preview':allow_preview,'allow_download':allow_download})
 target='/api/file-share/public/'+d['share_code']; visitor=client()
 assert req(visitor,target+'/download',{'file_id':fid})[0]==403
 assert req(visitor,target+'/open',{})[0]==200
 assert req(visitor,target+'/preview',{'file_id':fid})[0]==(200 if allow_preview else 403)
 assert req(visitor,target+'/download',{'file_id':fid})[0]==(200 if allow_download else 403)
assert req(a,'/api/file-share/admin/shares',{'title':'Expired','file_ids':[fid],'expires_at':1})[0]==400
request=urllib.request.Request(BASE+'/api/file-share/admin/shares',data=b'{}',headers={'Content-Type':'application/json'})
try:
 a.open(request);raise AssertionError('CSRF accepted')
except urllib.error.HTTPError as e:
 assert e.code==403
assert req(a,f'/api/file-share/admin/files/{fid}/purge',{})[0]==409
print('PASS: per-share permissions, session requirement, expiration validation, CSRF, purge guard')
# Multi-part object, file-content sniffing and generated password reset.
payload=b'<!doctype html><script>alert(1)</script>'+b'x'*(8*1024*1024)
_,upload=req(a,'/api/file-share/admin/uploads',{'filename':'disguised.png','size':len(payload),'mime_type':'image/png','sha256':hashlib.sha256(payload).hexdigest()})
assert upload['part_count']==2
new_id=upload['id'];items=[]
for index,start in enumerate(range(0,len(payload),upload['part_size']),1):
 chunk=payload[start:start+upload['part_size']]
 _,permit=req(a,f'/api/file-share/admin/uploads/{new_id}/part',{'part_number':index,'content_md5':base64.b64encode(hashlib.md5(chunk).digest()).decode()})
 with a.open(urllib.request.Request(permit['url'],data=chunk,headers=permit['headers'],method='PUT')) as response:
  items.append({'part_number':index,'etag':response.headers['ETag']})
status,file=req(a,f'/api/file-share/admin/uploads/{new_id}/complete',{'parts':items})
assert status==415,file
assert req(a,f'/api/file-share/admin/uploads/{new_id}/abort',{})[0]==200
new_id=fid
_,new_share=req(a,'/api/file-share/admin/shares',{'title':'Generated reset','file_ids':[new_id]})
_,reset=req(a,f"/api/file-share/admin/shares/{new_share['id']}/edit",{'password_mode':'set'})
assert len(reset['generated_password'])>=4
assert req(a,f'/api/file-share/admin/files/{new_id}/trash',{})[0]==200
assert req(a,f'/api/file-share/admin/files/{new_id}/purge',{})[0]==200
print('PASS: two-part upload, MIME spoof denied, generated password reset, permanent deletion')

# Upload cap boundary checks do not allocate or transfer a large file.
cap=500*1024*1024
assert req(a,'/api/file-share/admin/settings')[1]['max_upload_bytes']==cap
assert req(a,'/api/file-share/admin/settings',{'max_upload_bytes':cap+1})[0]==400
assert req(a,'/api/file-share/admin/uploads',{'filename':'large.bin','size':cap+1,'sha256':'a'*64})[0]==413
status,limit_upload=req(a,'/api/file-share/admin/uploads',{'filename':'boundary.bin','size':cap,'sha256':'a'*64})
assert status==200,(status,limit_upload)
assert req(a,f"/api/file-share/admin/uploads/{limit_upload['id']}/abort",{})[0]==200
assert req(a,'/api/file-share/admin/settings',{'max_upload_bytes':1})[0]==200
assert req(a,'/api/file-share/admin/uploads',{'filename':'small.bin','size':2,'sha256':'a'*64})[0]==413
assert req(a,'/api/file-share/admin/settings',{'max_upload_bytes':cap})[0]==200
print('PASS: 500 MB boundary, oversized upload denied, settings cannot exceed cap, stricter user limit preserved')
