"""Bounded XLSX parser, including WPS cell images; no spreadsheet dependencies."""
import hashlib
import io
import json
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from .database import connection,ensure_categories
from .services import GiftError,owned,uid,ts
from .assets import upload

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main','r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
def xml(raw):
    if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise GiftError('Excel XML 格式不支持')
    return ET.fromstring(raw)

def parse(raw):
    try:z=zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:raise GiftError('请上传有效的 xlsx 文件')
    if len(z.infolist())>2000 or sum(i.file_size for i in z.infolist())>40*1024*1024:raise GiftError('Excel 解压内容超过限制')
    names=set(z.namelist())
    strings=[]
    if 'xl/sharedStrings.xml' in names:
        strings=[''.join(n.itertext()) for n in xml(z.read('xl/sharedStrings.xml')).findall('s:si',NS)]
    rels={r.attrib['Id']:r.attrib['Target'] for r in xml(z.read('xl/_rels/workbook.xml.rels'))}
    sheets={s.attrib['name']:rels[s.attrib['{'+NS['r']+'}id']] for s in xml(z.read('xl/workbook.xml')).findall('s:sheets/s:sheet',NS)}
    def cells(title):
        target=sheets.get(title)
        if not target:raise GiftError('Excel 需包含“已购总表”和“已购明细”')
        path=target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/'+target)
        values={}
        for c in xml(z.read(path)).findall('.//s:sheetData/s:row/s:c',NS):
            v=c.find('s:v',NS);f=c.find('s:f',NS);inline=c.find('s:is',NS)
            value=v.text if v is not None else ''
            if c.get('t')=='s':value=strings[int(value)]
            elif c.get('t')=='inlineStr':value=''.join(inline.itertext()) if inline is not None else ''
            values[c.attrib['r']]={'value':value or '', 'formula':f.text if f is not None else ''}
        return values
    from datetime import datetime,timedelta
    def excel_month(value):
        if re.match(r'^20\d\d-\d\d',str(value)):return str(value)[:7]
        try:return (datetime(1899,12,30)+timedelta(days=float(value))).strftime('%Y-%m')
        except (ValueError,OverflowError):raise GiftError('无法识别 Excel 月份')
    total=cells('已购总表');paths=[];marks=[]
    rownums=sorted({int(re.sub(r'\D','',k)) for k in total})
    for row in rownums:
        if row<3:continue
        path=[total.get(f'{col}{row}',{}).get('value','').strip() for col in 'ABC']
        if not any(path):continue
        if not all(path):raise GiftError(f'第 {row} 行分类不完整')
        paths.append(path)
        for cell,val in total.items():
            if int(re.sub(r'\D','',cell))!=row or re.sub(r'\d','',cell) in ('A','B','C') or not val['value']:continue
            if val['value'] not in ('✅','✓','√','✔','1'):raise GiftError(f'{cell} 购买标记不支持，请检查')
            col=re.sub(r'\d','',cell);m=excel_month(total.get(col+'2',{}).get('value'))
            marks.append({'path':path,'month':m,'cell':cell})
    if not paths or len(paths)>2000:raise GiftError('分类数量不正确')
    mapping={}
    if 'xl/cellimages.xml' in names:
        images={r.attrib['Id']:posixpath.normpath('xl/'+r.attrib['Target']) for r in xml(z.read('xl/_rels/cellimages.xml.rels'))}
        for pic in xml(z.read('xl/cellimages.xml')).iter():
            if pic.tag.endswith('}pic'):
                nv=next((x for x in pic.iter() if x.tag.endswith('}cNvPr')),None)
                blip=next((x for x in pic.iter() if x.tag.endswith('}blip')),None)
                if nv is not None and blip is not None:mapping[nv.get('name')]=images.get(blip.get('{'+NS['r']+'}embed'))
    details=cells('已购明细');screens=[];current=None
    for cell,value in sorted(details.items(),key=lambda x:(int(re.sub(r'\D','',x[0])),x[0])):
        formula=value['formula'];match=re.search(r'DISPIMG\("([^"]+)"',formula)
        if match:
            name=mapping.get(match.group(1))
            if not current or not name or name not in names:raise GiftError('WPS 截图关系缺失')
            screens.append({'cell':cell,'month':current,'image_id':match.group(1),'bytes':z.read(name),'filename':name.rsplit('/',1)[-1]})
        elif cell.startswith('A') and value['value']:current=excel_month(value['value'])
    return {'paths':paths,'marks':marks,'screens':screens,'profile_note':total.get('A1',{}).get('value','')}

def preview(user,recipient,raw,secrets):
    digest=hashlib.sha256(raw).hexdigest()
    with connection() as conn:
        owned(conn,'gift_recipients',recipient,user)
        previous=conn.execute('SELECT * FROM gift_import_batches WHERE user_id=? AND recipient_id=? AND file_hash=?',(user,recipient,digest)).fetchone()
        if previous:return {'id':previous['id'],'status':previous['status'],**json.loads(previous['payload'])}
    payload=parse(raw)
    for screen in payload['screens']:
        asset=upload(user,screen.pop('bytes'),screen['filename'],'legacy',secrets);screen['asset_id']=asset['id']
    ident=uid()
    with connection(True) as conn:
        conn.execute('INSERT INTO gift_import_batches VALUES(?,?,?,?,?,?,?)',(ident,user,recipient,digest,json.dumps(payload,ensure_ascii=False),'preview',ts()))
    return {'id':ident,'status':'preview',**payload}

def confirm(user,ident,import_marks=True):
    with connection(True) as conn:
        batch=owned(conn,'gift_import_batches',ident,user);payload=json.loads(batch['payload'])
        if batch['status']=='confirmed':return {'status':'confirmed','already_imported':True}
        mapping=ensure_categories(conn,payload['paths'],user)
        if import_marks:
            for mark in payload['marks']:
                conn.execute('INSERT OR IGNORE INTO gift_purchase_marks VALUES(?,?,?,?,?,?)',(uid(),user,batch['recipient_id'],mapping[tuple(mark['path'])],mark['month'],ident))
        payload['import_marks']=bool(import_marks)
        conn.execute('UPDATE gift_import_batches SET status="confirmed",payload=? WHERE id=? AND user_id=?',(json.dumps(payload,ensure_ascii=False),ident,user))
        return {'status':'confirmed','categories':len(mapping),'marks':len(payload['marks']) if import_marks else 0,'screens':len(payload['screens'])}
