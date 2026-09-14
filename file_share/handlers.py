"""Independent file distribution API; no AI admin menu or conversation coupling."""
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
import threading
from http.cookies import SimpleCookie
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
import uuid

from infrastructure.storage import PrivateOSS, StorageSecurityError, shared_storage_config
from .database import transaction
from .security import classify, client_info, hash_password, verify_password

ROOT = Path(__file__).resolve().parent
PART_SIZE = 8 * 1024 * 1024
UPLOAD_LOCKS = [threading.Lock() for _ in range(64)]
INVALID = "该分享已失效或已被取消。"


class ShareError(Exception):
    def __init__(self, message, status=400):
        self.message, self.status = message, status


def require(condition, message, status=400):
    if not condition:
        raise ShareError(message, status)


def timestamp():
    return int(time.time())


def state(row):
    if row['status'] != 'ACTIVE':
        return row['status']
    if row['expires_at'] and row['expires_at'] <= timestamp():
        return 'EXPIRED'
    if ((row['max_views'] is not None and row['view_count'] >= row['max_views']) or
        (row['max_downloads'] is not None and row['download_count'] >= row['max_downloads'])):
        return 'LIMIT_REACHED'
    return 'ACTIVE'


def available(row):
    return row and row['status'] == 'ACTIVE' and (not row['expires_at'] or row['expires_at'] > timestamp())


def public_file(row):
    return {key: row[key] for key in ('id', 'filename', 'mime_type', 'file_type', 'size', 'created_at')}


def public_share(row):
    data = {key: row[key] for key in ('id', 'share_code', 'title', 'description', 'expires_at', 'max_views', 'max_downloads', 'allow_preview', 'allow_download', 'view_count', 'download_count', 'created_at', 'updated_at')}
    data.update(status=state(row), stored_status=row['status'], password_required=bool(row['password_hash']), url=os.environ.get('SHARE_PUBLIC_ORIGIN', 'https://feng.asia').rstrip('/') + '/share/' + row['share_code'])
    return data


class FileShareHandlersMixin:
    def file_share_page(self, admin=False):
        page = (ROOT / ('admin.html' if admin else 'public.html')).read_text()
        return self.html(page.replace('__FILE_SHARE_BUILD__', html.escape((ROOT / 'BUILD_ID').read_text().strip(), quote=True)))

    def fs_body(self):
        require(self.headers.get('X-Share-Request') == '1', '请求来源无效', 403)
        require(self.headers.get('Sec-Fetch-Site', '') != 'cross-site', '请求来源无效', 403)
        origin = self.headers.get('Origin')
        if origin:
            require(urlparse(origin).netloc == self.headers.get('Host'), '请求来源无效', 403)
        require(self.headers.get('Content-Type', '').startswith('application/json'), '仅支持 JSON 请求', 415)
        data = self.read_body(limit=512 * 1024)
        require(isinstance(data, dict), '请求格式不正确')
        return data

    def fs_dispatch(self):
        try:
            path = urlparse(self.path).path.rstrip('/')
            data = self.fs_body() if self.command == 'POST' else {}
            if path.startswith('/api/file-share/admin'):
                user = self.current_user()
                require(user and user['role'] == 'admin', '请使用管理员账号登录', 401)
                return self.fs_admin(path.removeprefix('/api/file-share/admin'), data, user['id'])
            return self.fs_public(path.removeprefix('/api/file-share/public/'), data)
        except StorageSecurityError as exc:
            return self.error(503, str(exc))
        except ShareError as exc:
            return self.error(exc.status, exc.message)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError):
            return self.error(400, '参数不正确，请检查输入')
        except sqlite3.Error:
            return self.error(503, '数据库繁忙，请稍后重试')
        except ImportError:
            return self.error(503, '文件分享依赖未安装，请安装 file_share/requirements.txt')
        except (HTTPError, URLError, TimeoutError, OSError):
            # Never return upstream URLs (which may contain signatures) or credentials.
            return self.error(502, '存储操作失败，请检查 OSS 配置、权限和网络后重试')

    def fs_oss(self, row=None):
        config = shared_storage_config(self.server.secrets)
        require(config['configured'], '现有 OSS 尚未配置', 503)
        if row:
            require(row['bucket'] == config['bucket'], '文件所属存储与当前配置不一致，请联系管理员', 409)
        return PrivateOSS(config)

    def fs_audit(self, conn, user_id, action, target):
        conn.execute('INSERT INTO share_audit_logs(user_id,action,target_id,ip,created_at) VALUES(?,?,?,?,?)',
            (user_id, action, target, client_info(self)['ip'], timestamp()))

    def fs_log(self, conn, row, action, success, file_id=None):
        info = client_info(self)
        unique = 0
        if action == 'VIEW_SHARE' and success:
            last = conn.execute("SELECT created_at FROM share_access_logs WHERE share_id=? AND visitor_hash=? AND action='VIEW_SHARE' AND success=1 ORDER BY created_at DESC LIMIT 1", (row['id'], info['visitor_hash'])).fetchone()
            unique = int(not last or last['created_at'] <= timestamp() - 1800)
        conn.execute('INSERT INTO share_access_logs(share_id,file_id,action,ip,user_agent,browser,os,device,referer,success,visitor_hash,unique_visit,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (row['id'], file_id, action, info['ip'], info['user_agent'], info['browser'], info['os'], info['device'], info['referer'], int(success), info['visitor_hash'], unique, timestamp()))

    def fs_rate(self, conn, key, limit, window):
        ts = timestamp()
        conn.execute('DELETE FROM share_rate_limits WHERE window_start<?', (ts - 86400,))
        conn.execute('INSERT INTO share_rate_limits(rate_key,window_start,count) VALUES(?,?,1) ON CONFLICT(rate_key) DO UPDATE SET count=CASE WHEN window_start<=? THEN 1 ELSE count+1 END, window_start=CASE WHEN window_start<=? THEN excluded.window_start ELSE window_start END', (key, ts, ts-window, ts-window))
        return conn.execute('SELECT count FROM share_rate_limits WHERE rate_key=?', (key,)).fetchone()['count'] <= limit

    def fs_owned_file(self, conn, file_id, user_id):
        row = conn.execute('SELECT * FROM share_files WHERE id=? AND user_id=?', (file_id, user_id)).fetchone()
        require(row is not None, '文件不存在', 404)
        return row

    def fs_admin(self, path, data, user_id):
        method = self.command
        parts = path.strip('/').split('/')
        qs = parse_qs(urlparse(self.path).query)
        page = max(1, min(100000, int(qs.get('page', ['1'])[0])))
        offset, limit = (page - 1) * 20, 20
        if path == '/version' and method == 'GET':
            return self.json({'version': (ROOT / 'VERSION').read_text().strip(),
                              'build_id': (ROOT / 'BUILD_ID').read_text().strip(),
                              'changelog': (ROOT / 'CHANGELOG.md').read_text()})
        if path == '/settings':
            with transaction() as conn:
                conn.execute('INSERT OR IGNORE INTO share_settings(user_id) VALUES(?)', (user_id,))
                if method == 'POST':
                    maximum = int(data.get('max_upload_bytes', 5368709120))
                    require(1 <= maximum <= 20 * 1024**3, '单文件上限为 1 字节至 20 GB')
                    conn.execute('UPDATE share_settings SET display_name=?,max_upload_bytes=? WHERE user_id=?', (str(data.get('display_name', ''))[:80], maximum, user_id))
                    self.fs_audit(conn, user_id, 'UPDATE_SETTINGS', user_id)
                row = dict(conn.execute('SELECT * FROM share_settings WHERE user_id=?', (user_id,)).fetchone())
            config = shared_storage_config(self.server.secrets)
            row.update(oss_configured=config['configured'], bucket=config['bucket'], signed_url_seconds=300, version=(ROOT / 'VERSION').read_text().strip())
            return self.json(row)
        if path == '/overview' and method == 'GET':
            with transaction() as conn:
                totals = dict(conn.execute("SELECT count(*) file_count,coalesce(sum(size),0) total_size FROM share_files WHERE user_id=? AND status='READY'", (user_id,)).fetchone())
                totals['active_shares'] = conn.execute("SELECT count(*) FROM shares WHERE user_id=? AND status='ACTIVE' AND (expires_at IS NULL OR expires_at>?) AND (max_views IS NULL OR view_count<max_views) AND (max_downloads IS NULL OR download_count<max_downloads)", (user_id,timestamp())).fetchone()[0]
                midnight = int(time.mktime(time.localtime()[:3] + (0,0,0,0,0,-1)))
                totals['today_views'], totals['today_downloads'] = conn.execute("SELECT coalesce(sum(l.action='VIEW_SHARE'),0),coalesce(sum(l.action='DOWNLOAD_FILE'),0) FROM share_access_logs l JOIN shares s ON s.id=l.share_id WHERE s.user_id=? AND l.success=1 AND l.created_at>=?", (user_id,midnight)).fetchone()
                totals['recent_shares'] = [public_share(r) for r in conn.execute('SELECT * FROM shares WHERE user_id=? ORDER BY created_at DESC LIMIT 5', (user_id,))]
                totals['recent_logs'] = self.fs_logs(conn, user_id, 0, 6)[0]
            return self.json(totals)
        if path == '/logs' and method == 'GET':
            with transaction() as conn:
                rows, total = self.fs_logs(conn, user_id, offset, limit, qs.get('share_id', [''])[0])
            return self.json(dict(items=rows,total=total,page=page))
        if path == '/files' and method == 'GET':
            status = 'TRASHED' if qs.get('trash', [''])[0] == '1' else 'READY'
            where, values = 'f.user_id=? AND f.status=?', [user_id, status]
            if status == 'TRASHED':
                where, values = "f.user_id=? AND f.status IN ('TRASHED','PURGING')", [user_id]
            search = qs.get('search', [''])[0][:120]
            if search:
                where += ' AND f.filename LIKE ?'
                values.append('%' + search + '%')
            kind = qs.get('type', [''])[0]
            if kind:
                where += ' AND f.file_type=?'
                values.append(kind)
            order = 'ASC' if qs.get('sort',[''])[0] == 'oldest' else 'DESC'
            with transaction() as conn:
                total = conn.execute('SELECT count(*) FROM share_files f WHERE ' + where, values).fetchone()[0]
                rows = conn.execute('SELECT f.* FROM share_files f WHERE ' + where + ' ORDER BY f.created_at ' + order + ' LIMIT ? OFFSET ?', (*values,limit,offset)).fetchall()
                result = []
                for row in rows:
                    item = public_file(row)
                    item.update(status=row['status'], sha256=row['sha256'])
                    item['share_count'] = conn.execute('SELECT count(*) FROM share_files_relation WHERE file_id=?',(row['id'],)).fetchone()[0]
                    item['active_share_count'] = conn.execute("SELECT count(*) FROM share_files_relation r JOIN shares s ON s.id=r.share_id WHERE r.file_id=? AND s.status='ACTIVE' AND (s.expires_at IS NULL OR s.expires_at>?) AND (s.max_views IS NULL OR s.view_count<s.max_views) AND (s.max_downloads IS NULL OR s.download_count<s.max_downloads)",(row['id'],timestamp())).fetchone()[0]
                    item['view_count'] = conn.execute("SELECT count(*) FROM share_access_logs l WHERE l.success=1 AND l.action='VIEW_SHARE' AND EXISTS(SELECT 1 FROM share_files_relation r WHERE r.share_id=l.share_id AND r.file_id=?)",(row['id'],)).fetchone()[0]
                    item['download_count'] = conn.execute("SELECT count(*) FROM share_access_logs WHERE file_id=? AND action='DOWNLOAD_FILE' AND success=1",(row['id'],)).fetchone()[0]
                    result.append(item)
            return self.json(dict(items=result,total=total,page=page))
        if path == '/uploads' and method == 'GET':
            with transaction() as conn:
                rows = conn.execute("SELECT id,filename,size,created_at FROM share_files WHERE user_id=? AND status='UPLOADING' ORDER BY created_at DESC LIMIT 30", (user_id,)).fetchall()
            return self.json({'items':[dict(r) for r in rows]})
        if path == '/uploads' and method == 'POST':
            return self.fs_upload_start(data, user_id)
        if len(parts) == 3 and parts[0] == 'uploads' and method == 'POST':
            return self.fs_upload_action(parts[1], parts[2], data, user_id)
        if len(parts) == 3 and parts[0] == 'files' and method == 'POST':
            file_id, action = parts[1:]
            with transaction() as conn:
                row = self.fs_owned_file(conn, file_id, user_id)
                if action == 'preview':
                    require(row['status'] == 'READY', '文件不可用', 404)
                    require(row['file_type'] in {'IMAGE','VIDEO','AUDIO','PDF','TEXT'}, '暂不支持在线预览，请下载查看')
                    return self.json({'url': self.fs_oss(row).access_url(row['object_key'], row['filename'], row['mime_type'])})
                if action == 'rename':
                    require(row['status'] == 'READY', '只有正常文件可以重命名', 409)
                    filename = data.get('filename')
                    require(isinstance(filename, str), '文件名不合法')
                    filename = filename.strip()
                    require(1 <= len(filename) <= 240 and not re.search(r'[\x00-\x1f\x7f/\\]', filename) and filename not in {'.', '..'}, '文件名不合法')
                    require(Path(filename).suffix == Path(row['original_filename']).suffix, '请保留原文件扩展名')
                    require(bool(filename[:-len(Path(filename).suffix)].strip()) if Path(filename).suffix else bool(filename), '请输入文件名称')
                    conn.execute('UPDATE share_files SET filename=?,updated_at=? WHERE id=? AND user_id=?',
                                 (filename, timestamp(), file_id, user_id))
                elif action == 'trash':
                    require(row['status'] == 'READY', '文件状态不可操作', 409)
                    conn.execute("UPDATE share_files SET status='TRASHED',deleted_at=?,updated_at=? WHERE id=?", (timestamp(),timestamp(),file_id))
                elif action == 'restore':
                    require(row['status'] == 'TRASHED', '文件不在回收站', 409)
                    conn.execute("UPDATE share_files SET status='READY',deleted_at=NULL,updated_at=? WHERE id=?", (timestamp(),file_id))
                elif action == 'purge':
                    require(row['status'] in {'TRASHED','PURGING'}, '请先将文件移入回收站', 409)
                    # Reserve deletion, then release SQLite while OSS performs I/O.
                    conn.execute("UPDATE share_files SET status='PURGING' WHERE id=?", (file_id,))
                    conn.commit()
                    try:
                        self.fs_oss(row).delete(row['object_key'])
                    except Exception:
                        conn.execute("UPDATE share_files SET status='TRASHED' WHERE id=? AND status='PURGING'", (file_id,))
                        conn.commit()
                        raise
                    conn.execute("UPDATE share_files SET status='DELETED',updated_at=? WHERE id=?", (timestamp(),file_id))
                else:
                    raise ShareError('操作不存在',404)
                self.fs_audit(conn,user_id,action.upper() + '_FILE',file_id)
            return self.json({'ok':True})
        if path == '/shares':
            if method == 'GET':
                with transaction() as conn:
                    rows = [public_share(r) for r in conn.execute('SELECT * FROM shares WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?', (user_id,limit,offset))]
                    total = conn.execute('SELECT count(*) FROM shares WHERE user_id=?',(user_id,)).fetchone()[0]
                return self.json(dict(items=rows,total=total,page=page))
            if method == 'POST':
                values, password = self.fs_share_values(data)
                ids = data.get('file_ids')
                require(isinstance(ids,list) and 1 <= len(ids) <= 100 and all(isinstance(i,str) for i in ids), '请选择 1–100 个文件')
                require(len(set(ids)) == len(ids), '文件不能重复')
                share_id, code = uuid.uuid4().hex, secrets.token_urlsafe(12)
                with transaction() as conn:
                    for file_id in ids:
                        require(self.fs_owned_file(conn,file_id,user_id)['status'] == 'READY', '文件不可分享')
                    conn.execute('INSERT INTO shares(id,user_id,share_code,title,description,password_hash,expires_at,max_views,max_downloads,allow_preview,allow_download,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)', (share_id,user_id,code,*values,timestamp(),timestamp()))
                    conn.executemany('INSERT INTO share_files_relation VALUES(?,?,?)', [(share_id,i,n) for n,i in enumerate(ids)])
                    self.fs_audit(conn,user_id,'CREATE_SHARE',share_id)
                    result = public_share(conn.execute('SELECT * FROM shares WHERE id=?',(share_id,)).fetchone())
                result['generated_password'] = password
                return self.json(result,201)
        if len(parts) in (2,3) and parts[0] == 'shares':
            share_id = parts[1]
            with transaction() as conn:
                row = conn.execute('SELECT * FROM shares WHERE id=? AND user_id=?',(share_id,user_id)).fetchone()
                require(row, '分享不存在',404)
                if method == 'GET' and len(parts) == 2:
                    result = public_share(row)
                    result['files'] = [dict(**public_file(r),status=r['status']) for r in conn.execute('SELECT f.* FROM share_files f JOIN share_files_relation r ON r.file_id=f.id WHERE r.share_id=? ORDER BY r.sort_order',(share_id,))]
                    result['logs'] = self.fs_logs(conn,user_id,0,20,share_id)[0]
                    result['stats'] = dict(conn.execute("SELECT count(DISTINCT CASE WHEN action='VIEW_SHARE' AND success=1 THEN ip END) unique_ips,coalesce(sum(CASE WHEN action='VIEW_SHARE' AND success=1 THEN unique_visit ELSE 0 END),0) uv,coalesce(sum(action='PREVIEW_FILE' AND success=1),0) previews FROM share_access_logs WHERE share_id=?",(share_id,)).fetchone())
                    return self.json(result)
                require(method == 'POST' and len(parts) == 3, '接口不存在',404)
                action = parts[2]
                if action == 'edit':
                    require(row['status'] != 'REVOKED','已撤回分享不能恢复，请重新创建',409)
                    values, password = self.fs_share_values(data,row)
                    conn.execute('UPDATE shares SET title=?,description=?,password_hash=?,expires_at=?,max_views=?,max_downloads=?,allow_preview=?,allow_download=?,auth_version=auth_version+1,updated_at=? WHERE id=?',(*values,timestamp(),share_id))
                else:
                    targets = {'pause':'PAUSED','resume':'ACTIVE','revoke':'REVOKED'}
                    require(action in targets,'操作不存在',404)
                    require(row['status'] != 'REVOKED','已撤回分享不能恢复，请重新创建',409)
                    conn.execute('UPDATE shares SET status=?,auth_version=auth_version+1,updated_at=? WHERE id=?',(targets[action],timestamp(),share_id))
                conn.execute('DELETE FROM share_sessions WHERE share_id=?',(share_id,))
                self.fs_audit(conn,user_id,action.upper() + '_SHARE',share_id)
            return self.json({'ok':True, 'generated_password':password if action == 'edit' else None})
        raise ShareError('接口不存在',404)

    def fs_share_values(self, data, previous=None):
        def val(key, default):
            return data[key] if key in data else (previous[key] if previous is not None else default)
        title, description = str(val('title','')).strip(), str(val('description','')).strip()
        require(1 <= len(title) <= 120 and len(description) <= 2000,'标题应为 1–120 字，说明不超过 2000 字')
        expires = val('expires_at',timestamp()+604800)
        expires = int(expires) if expires else None
        require(expires is None or expires > timestamp(),'有效期必须晚于当前时间')
        limits=[]
        for key in ('max_views','max_downloads'):
            value = val(key,None)
            value = int(value) if value not in (None,'') else None
            require(value is None or 1 <= value <= 1000000000,'次数限制必须是正整数')
            limits.append(value)
        password = None
        encoded = previous['password_hash'] if previous else None
        if data.get('password_mode') == 'off':
            encoded = None
        elif data.get('password_mode') == 'set':
            password = str(data.get('password') or secrets.token_urlsafe(6))
            require(4 <= len(password) <= 128,'分享密码应为 4–128 位')
            encoded = hash_password(password)
        allow_preview, allow_download = val('allow_preview',True),val('allow_download',True)
        require(allow_preview in (True,False,0,1) and allow_download in (True,False,0,1),'权限值不正确')
        return (title,description,encoded,expires,*limits,int(allow_preview),int(allow_download)),password

    def fs_logs(self, conn, user_id, offset, limit, share_id=''):
        where, values = 's.user_id=?',[user_id]
        if share_id:
            where += ' AND s.id=?'
            values.append(share_id)
        total = conn.execute('SELECT count(*) FROM share_access_logs l JOIN shares s ON s.id=l.share_id WHERE ' + where, values).fetchone()[0]
        rows = conn.execute('SELECT l.*,s.title,f.filename FROM share_access_logs l JOIN shares s ON s.id=l.share_id LEFT JOIN share_files f ON f.id=l.file_id WHERE ' + where + ' ORDER BY l.id DESC LIMIT ? OFFSET ?',(*values,limit,offset)).fetchall()
        return [dict(r) for r in rows],total

    def fs_upload_start(self, data, user_id):
        file_id = uuid.uuid4().hex
        lock = UPLOAD_LOCKS[int(hashlib.sha256(file_id.encode()).hexdigest(), 16) % len(UPLOAD_LOCKS)]
        with lock:
            return self.fs_upload_start_locked(data, user_id, file_id)

    def fs_upload_start_locked(self, data, user_id, file_id):
        filename = str(data.get('filename','')).strip()
        require(1 <= len(filename) <= 240 and not re.search(r'[\x00-\x1f/\\]',filename) and filename not in {'.','..'},'文件名不合法')
        size = int(data.get('size',0))
        digest = str(data.get('sha256',''))
        require(re.fullmatch('[a-f0-9]{64}',digest),'缺少 SHA256 校验值')
        kind,mime = classify(filename,str(data.get('mime_type','')))
        ext = filename.rsplit('.',1)[-1].lower() if '.' in filename else ''
        ext = '.' + ext if re.fullmatch('[a-z0-9]{1,10}',ext) else ''
        key = 'share/' + str(user_id) + '/' + time.strftime('%Y/%m') + '/' + str(uuid.uuid4()) + ext
        oss = self.fs_oss()
        with transaction() as conn:
            settings = conn.execute('SELECT * FROM share_settings WHERE user_id=?',(user_id,)).fetchone()
            require(0 < size <= (settings['max_upload_bytes'] if settings else 5*1024**3),'文件为空或超过上传大小限制')
            pending = conn.execute("SELECT count(*) FROM share_files WHERE user_id=? AND status='UPLOADING'",(user_id,)).fetchone()[0]
            require(pending < 30,'未完成上传过多，请先清理失败上传',429)
            upload_id = None
            conn.execute('INSERT INTO share_files(id,user_id,filename,original_filename,object_key,bucket,mime_type,file_type,size,sha256,upload_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(file_id,user_id,filename,filename,key,oss.config['bucket'],mime,kind,size,digest,upload_id,timestamp(),timestamp()))
            self.fs_audit(conn,user_id,'BEGIN_UPLOAD',file_id)
        try:
            upload_id = oss.begin(key, mime)
            require(upload_id,'OSS 未返回上传标识',502)
            with transaction() as conn:
                conn.execute('UPDATE share_files SET upload_id=? WHERE id=?',(upload_id,file_id))
        except Exception:
            with transaction() as conn:
                conn.execute("UPDATE share_files SET status='DELETED' WHERE id=?",(file_id,))
            raise
        return self.json({'id':file_id,'part_size':PART_SIZE,'part_count':math.ceil(size/PART_SIZE)})

    def fs_upload_action(self, file_id, action, data, user_id):
        lock = UPLOAD_LOCKS[int(hashlib.sha256(file_id.encode()).hexdigest(), 16) % len(UPLOAD_LOCKS)]
        with lock:
            return self.fs_upload_action_locked(file_id, action, data, user_id)

    def fs_upload_action_locked(self, file_id, action, data, user_id):
        with transaction() as conn:
            row = self.fs_owned_file(conn,file_id,user_id)
            if action == 'complete' and row['status'] == 'READY':
                return self.json(public_file(row))
            require(row['status']=='UPLOADING','上传任务不可用',409)
            oss = self.fs_oss(row)
            if action == 'part':
                part = int(data.get('part_number',0))
                require(1 <= part <= math.ceil(row['size']/PART_SIZE),'分片序号不正确')
                # Content-MD5 is bound into the signature; browser cannot replace a part silently.
                md5 = str(data.get('content_md5',''))
                require(re.fullmatch('[A-Za-z0-9+/]{22}==',md5),'分片校验值不正确')
                headers = {'Content-Type':'application/octet-stream','Content-MD5':md5}
                return self.json({'url':oss.signed('PUT',row['object_key'],{'uploadId':row['upload_id'],'partNumber':part},headers,ttl=600),'headers':headers})
            if action == 'abort':
                conn.commit()
                try:
                    if row['upload_id']:
                        oss.abort(row['object_key'],row['upload_id'])
                except HTTPError as exc:
                    if exc.code != 404:
                        raise
                # Also remove an object whose merge succeeded before registration failed.
                oss.delete(row['object_key'])
                conn.execute("UPDATE share_files SET status='DELETED',updated_at=? WHERE id=?",(timestamp(),file_id))
                self.fs_audit(conn,user_id,'ABORT_UPLOAD',file_id)
                return self.json({'ok':True})
            require(action=='complete','操作不存在',404)
            parts = data.get('parts')
            require(isinstance(parts,list) and len(parts)==math.ceil(row['size']/PART_SIZE),'上传分片不完整')
            verified=[]
            for i, part in enumerate(parts,1):
                require(part.get('part_number')==i and re.fullmatch('"?[a-fA-F0-9]{32}"?',str(part.get('etag',''))),'分片校验不正确')
                verified.append((i,part['etag']))
            # Network I/O must not hold the shared SQLite writer lock.
            conn.commit()
            # Completion can be retried after a lost response: HEAD before retrying the merge.
            try:
                head = oss.head(row['object_key'])
            except HTTPError as exc:
                if exc.code != 404:
                    raise
                oss.complete(row['object_key'],row['upload_id'],verified)
                head = oss.head(row['object_key'])
            head = {k.lower():v for k,v in head.items()}
            require(int(head.get('content-length',-1)) == row['size'],'OSS 文件大小校验失败',409)
            oss.verify_private(row['object_key'])
            kind,mime = classify(row['filename'],row['mime_type'],oss.sample(row['object_key']))
            require(kind == row['file_type'] and mime == row['mime_type'], '文件内容与声明类型不匹配，请使用正确的扩展名重新上传', 415)
            conn.execute("UPDATE share_files SET status='READY',file_type=?,mime_type=?,updated_at=? WHERE id=?",(kind,mime,timestamp(),file_id))
            self.fs_audit(conn,user_id,'COMPLETE_UPLOAD',file_id)
            result = public_file(conn.execute('SELECT * FROM share_files WHERE id=?',(file_id,)).fetchone())
        return self.json(result)

    def fs_public(self, path, data):
        parts = path.split('/')
        code = parts[0]
        require(re.fullmatch('[A-Za-z0-9_-]{16}',code),INVALID,404)
        action = parts[1] if len(parts)>1 else ''
        with transaction() as conn:
            row = conn.execute('SELECT * FROM shares WHERE share_code=?',(code,)).fetchone()
            require(row,INVALID,404)
            if not available(row):
                if self.command == 'POST':
                    self.fs_log(conn,row,{'open':'VIEW_SHARE','password':'PASSWORD_FAIL','download':'DOWNLOAD_FILE','preview':'PREVIEW_FILE'}.get(action,'VIEW_SHARE'),False)
                return self.error(410,INVALID)
            if self.command == 'GET' and len(parts)==1:
                # Challenge response deliberately contains no title, filename or owner metadata.
                return self.json({'password_required':bool(row['password_hash'])})
            require(self.command == 'POST' and len(parts)==2,'接口不存在',404)
            cookie_name = 'fs_' + code
            cookies = SimpleCookie(self.headers.get('Cookie',''))
            token = cookies[cookie_name].value if cookie_name in cookies else ''
            session = conn.execute('SELECT 1 FROM share_sessions WHERE token_hash=? AND share_id=? AND auth_version=? AND expires_at>?',(hashlib.sha256(token.encode()).hexdigest(),row['id'],row['auth_version'],timestamp())).fetchone() if token else None
            if action == 'password':
                allowed = self.fs_rate(conn,'password:' + row['id'] + ':' + client_info(self)['ip'],10,600)
                if not allowed:
                    self.fs_log(conn,row,'PASSWORD_FAIL',False)
                    return self.error(429,'尝试过于频繁，请 10 分钟后重试')
                password = str(data.get('password',''))
                if len(password)>128 or not row['password_hash'] or not verify_password(row['password_hash'],password):
                    self.fs_log(conn,row,'PASSWORD_FAIL',False)
                    return self.error(403,'分享密码不正确')
                self.fs_log(conn,row,'PASSWORD_SUCCESS',True)
                action='open'
                session=True
            if action == 'open':
                if row['password_hash'] and not session:
                    return self.error(401,'请输入分享密码')
                if not self.fs_rate(conn,'open:' + row['id'] + ':' + client_info(self)['ip'],120,60):
                    return self.error(429,'访问过于频繁，请稍后重试')
                changed = conn.execute('UPDATE shares SET view_count=view_count+1 WHERE id=? AND (max_views IS NULL OR view_count<max_views)',(row['id'],)).rowcount
                if not changed:
                    self.fs_log(conn,row,'VIEW_SHARE',False)
                    return self.error(410,'该分享已达到最大访问次数。')
                self.fs_log(conn,row,'VIEW_SHARE',True)
                token=secrets.token_urlsafe(32)
                conn.execute('DELETE FROM share_sessions WHERE expires_at<=?',(timestamp(),))
                conn.execute('INSERT INTO share_sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),row['id'],row['auth_version'],timestamp()+1800))
                files = [public_file(f) for f in conn.execute("SELECT f.* FROM share_files f JOIN share_files_relation r ON r.file_id=f.id WHERE r.share_id=? AND f.status='READY' ORDER BY r.sort_order",(row['id'],))]
                settings = conn.execute('SELECT display_name FROM share_settings WHERE user_id=?',(row['user_id'],)).fetchone()
                result = {key:row[key] for key in ('title','description','expires_at','allow_preview','allow_download')}
                result.update(files=files,display_name=settings['display_name'] if settings else '')
                conn.commit()
                raw=json.dumps(result,ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type','application/json; charset=utf-8')
                self.send_header('Content-Length',str(len(raw)))
                self.send_header('Cache-Control','no-store')
                secure = '; Secure' if self.headers.get('X-Forwarded-Proto')=='https' or self.headers.get('Origin','').startswith('https://') else ''
                self.send_header('Set-Cookie',f'{cookie_name}={token}; Path=/api/file-share/public/{code}; HttpOnly; SameSite=Strict; Max-Age=1800{secure}')
                self.end_headers()
                self.wfile.write(raw)
                return
            require(action in {'preview','download'},'接口不存在',404)
            log_action = 'DOWNLOAD_FILE' if action=='download' else 'PREVIEW_FILE'
            file_id=str(data.get('file_id',''))
            file = conn.execute("SELECT f.* FROM share_files f JOIN share_files_relation r ON r.file_id=f.id WHERE r.share_id=? AND f.id=? AND f.status='READY'",(row['id'],file_id)).fetchone()
            if not session or not file or not row['allow_' + action]:
                self.fs_log(conn,row,log_action,False,file_id if file else None)
                return self.error(403,'当前分享不允许此操作，或访问验证已过期')
            if action=='preview' and file['file_type'] not in {'IMAGE','VIDEO','AUDIO','PDF','TEXT'}:
                self.fs_log(conn,row,log_action,False,file_id)
                return self.error(415,'暂不支持在线预览，请下载查看')
            url = self.fs_oss(file).access_url(file['object_key'],file['filename'],file['mime_type'],action=='download')
            if action=='download':
                changed=conn.execute('UPDATE shares SET download_count=download_count+1 WHERE id=? AND (max_downloads IS NULL OR download_count<max_downloads)',(row['id'],)).rowcount
                if not changed:
                    self.fs_log(conn,row,log_action,False,file_id)
                    return self.error(410,'该分享已达到最大下载次数。')
            self.fs_log(conn,row,log_action,True,file_id)
        return self.json({'url':url,'expires_in':300})
