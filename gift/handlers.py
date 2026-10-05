import json
import sqlite3
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from urllib.error import HTTPError,URLError
from . import services as s
from .database import connection,ensure_categories
from .assets import storage,upload,decode
from .recognition import recognize
from .import_service import preview,confirm

class GiftHandlersMixin:
    def gift_page(self):
        page=Path(__file__).with_name('index.html').read_text()
        return self.html(page.replace('__GIFT_VERSION__',Path(__file__).with_name('VERSION').read_text().strip()).replace('__GIFT_BUILD__',Path(__file__).with_name('BUILD_ID').read_text().strip()))

    def gift_dispatch(self):
        try:
            path=urlparse(self.path).path.removeprefix('/api/gifts').strip('/')
            if self.command=='GET' and path=='version':
                return self.json({'version':Path(__file__).with_name('VERSION').read_text().strip(),'build_id':Path(__file__).with_name('BUILD_ID').read_text().strip(),'releases':json.loads(Path(__file__).with_name('releases.json').read_text())})
            user=self.current_user()
            if not user:raise s.GiftError('请先登录槑槑',401)
            actor=user['id'];path=urlparse(self.path).path.removeprefix('/api/gifts').strip('/')
            params={k:v[0] for k,v in parse_qs(urlparse(self.path).query).items()};data={}
            if self.command!='GET':
                if self.headers.get('X-Gift-Request')!='1' or self.headers.get('Sec-Fetch-Site')=='cross-site':raise s.GiftError('请求来源无效',403)
                origin=self.headers.get('Origin')
                if origin and urlparse(origin).netloc!=self.headers.get('Host'):raise s.GiftError('请求来源无效',403)
                if not self.headers.get('Content-Type','').startswith('application/json'):raise s.GiftError('仅支持 JSON 请求',415)
                data=self.read_body(limit=15*1024*1024)
                if not isinstance(data,dict):raise s.GiftError('参数不正确')
            method=self.command
            if path=='recipients':
                if method=='GET':return self.json({'recipients':s.recipients(actor)})
                if method=='POST':return self.json({'recipient':s.save_recipient(actor,data)},201)
            if path.startswith('recipients/'):
                parts=path.split('/');ident=parts[1]
                if len(parts)==3 and parts[2]=='history' and method=='GET':
                    with connection() as conn:
                        s.owned(conn,'gift_recipients',ident,actor)
                        rows=conn.execute('SELECT * FROM gift_recipient_profiles_history WHERE user_id=? AND recipient_id=? ORDER BY recorded_at DESC,rowid DESC LIMIT 100',(actor,ident)).fetchall()
                    return self.json({'history':[dict(r) for r in rows]})
                if len(parts)==2 and method=='PATCH':return self.json({'recipient':s.save_recipient(actor,data,ident)})
            if path=='categories':
                if method=='GET':return self.json({'categories':s.categories(actor)})
                if method=='POST':
                    paths=data.get('paths')
                    if not isinstance(paths,list) or not 1<=len(paths)<=100 or any(not isinstance(p,list) or not 1<=len(p)<=3 or any(not isinstance(n,str) or not n.strip() or len(n)>100 for n in p) for p in paths):raise s.GiftError('请填写 1—100 个分类路径')
                    with connection(True) as conn:ensure_categories(conn,paths,actor)
                    return self.json({'categories':s.categories(actor)},201)
            if path=='items':
                if method=='GET':return self.json(s.list_items(actor,params))
                if method=='POST':return self.json({'item':s.save_item(actor,data)},201)
            if path=='items/batch' and method=='POST':return self.json({'items':s.batch_items(actor,data)},201)
            if path.startswith('items/') and len(path.split('/'))==2:
                ident=path.split('/')[1]
                if method=='PATCH':return self.json({'item':s.save_item(actor,data,ident)})
                if method=='DELETE':
                    with connection(True) as conn:
                        s.owned(conn,'gift_items',ident,actor);conn.execute('DELETE FROM gift_items WHERE id=? AND user_id=?',(ident,actor))
                    return self.json({'ok':True})
            if path=='duplicates' and method=='GET':return self.json(s.duplicates(actor,params))
            if path=='dashboard' and method=='GET':return self.json(s.dashboard(actor,params.get('recipient_id')))
            if path=='recommendations' and method=='GET':return self.json(s.recommendations(actor,params.get('recipient_id')))
            if path=='assets' and method=='POST':
                asset=upload(actor,decode(data.get('base64')),data.get('filename'),data.get('purpose','product'),self.server.secrets)
                return self.json({'asset':{'id':asset['id'],'view_url':'/api/gifts/assets/'+asset['id']+'/view'}},201)
            if path.startswith('assets/') and path.endswith('/view') and method=='GET':
                with connection() as conn:asset=dict(s.owned(conn,'gift_assets',path.split('/')[1],actor))
                url=storage(self.server.secrets).access_url(asset['oss_key'],asset['filename'],asset['mime_type'])
                self.send_response(302);self.send_header('Location',url);self.send_header('Cache-Control','private, no-store');self.end_headers();return
            if path=='ai/recognize' and method=='POST':return self.json(recognize(actor,data.get('asset_id'),self.server.secrets,storage(self.server.secrets),data.get('model_id')))
            if path=='ai/tasks' and method=='GET':
                with connection() as conn:rows=conn.execute('SELECT id,asset_id,status,result,error_message,created_at FROM gift_recognition_tasks WHERE user_id=? ORDER BY created_at DESC LIMIT 30',(actor,)).fetchall()
                return self.json({'tasks':[{**dict(r),'result':json.loads(r['result'])} for r in rows]})
            if path=='imports/preview' and method=='POST':return self.json(preview(actor,data.get('recipient_id'),decode(data.get('base64'),8*1024*1024),self.server.secrets))
            if path.startswith('imports/') and path.endswith('/confirm') and method=='POST':return self.json(confirm(actor,path.split('/')[1],data.get('import_marks',True)))
            if path=='imports' and method=='GET':
                with connection() as conn:
                    rows=conn.execute('SELECT * FROM gift_import_batches WHERE user_id=? AND recipient_id=? ORDER BY created_at DESC',(actor,params.get('recipient_id'))).fetchall()
                return self.json({'batches':[{'id':r['id'],'status':r['status'],**json.loads(r['payload'])} for r in rows]})
            raise s.GiftError('接口不存在',404)
        except s.GiftError as exc:return self.error(exc.status,str(exc))
        except sqlite3.Error:return self.error(503,'数据库繁忙，请稍后重试')
        except (HTTPError,URLError,TimeoutError,OSError):return self.error(502,'存储或识别服务暂不可用，请稍后重试')
        except ImportError:return self.error(503,'存储依赖未安装')
        except (ValueError,TypeError,KeyError,AttributeError,ET.ParseError,zipfile.BadZipFile):return self.error(400,'参数不正确，请检查输入')
