import base64
import hashlib
import re
from infrastructure.storage import PrivateOSS,shared_storage_config
from .database import connection
from .services import GiftError,uid,ts,owned,text

def storage(secrets): return PrivateOSS({**shared_storage_config(secrets),'directory':'share/gifts'})
def decode(value,limit=10*1024*1024):
    if not isinstance(value,str) or len(value)>limit*4//3+8:raise GiftError('文件超过大小限制')
    try:raw=base64.b64decode(value,validate=True)
    except Exception:raise GiftError('文件内容不正确')
    if not 0<len(raw)<=limit:raise GiftError('文件为空或超过大小限制')
    return raw

def upload(user,raw,filename,purpose,secrets):
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
    elif raw.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
    elif raw.startswith(b'RIFF') and raw[8:12]==b'WEBP':mime='image/webp'
    else:raise GiftError('仅支持 JPG、PNG、WebP 图片')
    if len(raw)>10*1024*1024:raise GiftError('图片不能超过 10MB')
    digest=hashlib.sha256(raw).hexdigest()
    with connection() as conn:
        existing=conn.execute('SELECT * FROM gift_assets WHERE user_id=? AND sha256=?',(user,digest)).fetchone()
        if existing:return dict(existing)
        used=conn.execute('SELECT COALESCE(SUM(file_size),0) FROM gift_assets WHERE user_id=?',(user,)).fetchone()[0]
        if used+len(raw)>500*1024*1024:raise GiftError('图片空间已达 500MB，请清理不需要的截图')
    ident=uid();key='share/gifts/'+hashlib.sha256(user.encode()).hexdigest()[:24]+'/'+ident
    store=storage(secrets)
    with store.request('PUT',key,headers={'Content-Type':mime,'x-oss-object-acl':'private','Cache-Control':'private, no-store'},body=raw):pass
    try:
        store.verify_private(key)
    except Exception:
        try:store.delete(key)
        except Exception:pass
        raise
    values=(ident,user,text(filename,180) or '商品截图',mime,len(raw),key,digest,text(purpose,30),ts())
    try:
        with connection(True) as conn:conn.execute('INSERT INTO gift_assets VALUES(?,?,?,?,?,?,?,?,?)',values)
    except Exception:
        store.delete(key);raise
    return dict(zip(('id','user_id','filename','mime_type','file_size','oss_key','sha256','purpose','created_at'),values))
