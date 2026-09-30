"""Reusable services: every entry point supplies the authenticated account."""
import calendar
import hashlib
import json
import re
import time
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from .database import connection

class GiftError(ValueError):
    def __init__(self,message,status=400):
        super().__init__(message)
        self.status=status

def uid(): return uuid.uuid4().hex
def ts(): return int(time.time())
def today(): return date.today().isoformat()
def text(value,limit=2000): return str(value or '').strip()[:limit]
def money(value):
    if value is None or value=='': return None
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number<0 or number>10000000 or number.as_tuple().exponent < -2:
            raise ValueError()
        return int(number*100)
    except (ValueError,InvalidOperation,TypeError): raise GiftError('金额需为非负数，最多两位小数')

def integer(value,minimum=0,maximum=1200):
    if value is None or value=='': return None
    try:
        number=Decimal(str(value))
        if not number.is_finite() or number!=int(number) or not minimum<=number<=maximum: raise ValueError()
        return int(number)
    except (ValueError,InvalidOperation,TypeError,OverflowError): raise GiftError('数量或月龄不正确')

def day(value):
    if not value: return None
    try: return date.fromisoformat(str(value)).isoformat()
    except ValueError: raise GiftError('日期不正确')

def month(value):
    if not value: return None
    if not re.fullmatch(r'\d{4}-\d{2}',str(value)): raise GiftError('月份不正确')
    day(str(value)+'-01')
    return str(value)

def months_ago(n):
    current=date.today(); total=current.year*12+current.month-1-n
    return f'{total//12:04d}-{total%12+1:02d}'

def owned(conn,table,ident,user):
    # Table names are supplied only by service code, never request input.
    row=conn.execute(f'SELECT * FROM {table} WHERE id=? AND user_id=?',(ident,user)).fetchone()
    if not row: raise GiftError('记录不存在或无权访问',404)
    return row

def public(row):
    data=dict(row)
    for key in ('price','total_price','monthly_budget'):
        if key in data and data[key] is not None: data[key]=data[key]/100
    for key in ('product_image','order_image','avatar'):
        if data.get(key): data[key+'_url']='/api/gifts/assets/'+data[key]+'/view'
    return data

def category_path(conn,ident,user):
    if not ident: return ['','','']
    names=['','','']; seen=set()
    while ident:
        if ident in seen: raise GiftError('分类层级不正确')
        seen.add(ident)
        row=conn.execute('SELECT * FROM gift_categories WHERE id=? AND (user_id IS NULL OR user_id=?)',(ident,user)).fetchone()
        if not row: raise GiftError('分类不存在或无权访问')
        names[row['level']-1]=row['name'];ident=row['parent_id']
    return names

def recipients(user):
    with connection() as conn:
        return [public(r) for r in conn.execute('SELECT * FROM gift_recipients WHERE user_id=? ORDER BY created_at',(user,))]

def save_recipient(user,data,ident=None):
    with connection(True) as conn:
        previous=dict(owned(conn,'gift_recipients',ident,user)) if ident else {}
        merged={**public(previous),**data}
        name=text(merged.get('name'),80)
        if not name: raise GiftError('请填写收礼对象姓名')
        birthday=day(merged.get('birthday'))
        if birthday and birthday>today(): raise GiftError('出生日期不能晚于今天')
        avatar=merged.get('avatar') or None
        if avatar: owned(conn,'gift_assets',avatar,user)
        values={k:text(merged.get(k),80 if k in ('nickname','gender','clothing_size','shoe_size') else 2000) for k in ('nickname','gender','relationship','clothing_size','shoe_size','allergies','food_preferences','notes')}
        approximate=integer(merged.get('approximate_age_months'))
        recorded=day(merged.get('age_recorded_at')) or today()
        if not ident: ident=uid()
        values.update(id=ident,user_id=user,name=name,birthday=birthday,approximate_age_months=approximate,
                      age_recorded_at=recorded,avatar=avatar,monthly_budget=money(merged.get('monthly_budget')),
                      created_at=previous.get('created_at',ts()),updated_at=ts())
        cols=','.join(values)
        updates=','.join(k+'=excluded.'+k for k in values if k not in ('id','user_id','created_at'))
        conn.execute(f'INSERT INTO gift_recipients({cols}) VALUES({",".join("?" for _ in values)}) ON CONFLICT(id) DO UPDATE SET {updates}',tuple(values.values()))
        note=text(data.get('growth_note'))
        if not previous or note or any(previous.get(k)!=values[k] for k in ('clothing_size','shoe_size')):
            conn.execute('INSERT INTO gift_recipient_profiles_history VALUES(?,?,?,?,?,?,?)',(uid(),user,ident,values['clothing_size'],values['shoe_size'],note,today()))
        return public(owned(conn,'gift_recipients',ident,user))

def categories(user):
    with connection() as conn:
        return [{**dict(row),'path':category_path(conn,row['id'],user)} for row in conn.execute('SELECT * FROM gift_categories WHERE user_id IS NULL OR user_id=? ORDER BY sort_order,name',(user,))]

def create_item(conn,user,data,ident=None):
    previous=public(owned(conn,'gift_items',ident,user)) if ident else {}
    data={**previous,**data}
    recipient=text(data.get('recipient_id')); owned(conn,'gift_recipients',recipient,user)
    task=data.get('recognition_task_id') or None
    candidate=integer(data.get('recognition_item_index'),0,99)
    if task:
        recognized=owned(conn,'gift_recognition_tasks',task,user)
        if recognized['status']!='completed' or candidate is None or candidate>=len(json.loads(recognized['result']).get('items',[])):
            raise GiftError('识别草稿不存在，请重新识别')
        saved=conn.execute('SELECT * FROM gift_items WHERE user_id=? AND recognition_task_id=? AND recognition_item_index=?',(user,task,candidate)).fetchone()
        if saved and not ident:
            if saved['recipient_id']!=recipient:raise GiftError('该截图商品已记录给其他对象，请在历史页编辑归属',409)
            return public(saved)
    name=text(data.get('product_name'),300)
    if not name: raise GiftError('请填写商品名称')
    cat=data.get('category_id') or None;path=category_path(conn,cat,user)
    images={k:data.get(k) or None for k in ('product_image','order_image')}
    for image in images.values():
        if image: owned(conn,'gift_assets',image,user)
    purchase=day(data.get('purchase_date'));purchase_month=purchase[:7] if purchase else month(data.get('purchase_month'))
    quantity=integer(data.get('quantity'),1,100000); price=money(data.get('price'));total=money(data.get('total_price'))
    if total is None and price is not None and quantity is not None: total=price*quantity
    url=text(data.get('product_url'),2000)
    if url and not re.match(r'^https?://',url): raise GiftError('商品链接需以 http 或 https 开头')
    values=dict(id=ident or uid(),user_id=user,recipient_id=recipient,product_name=name,
                brand=text(data.get('brand'),80),specification=text(data.get('specification'),500),category_id=cat,
                category_level1=path[0],category_level2=path[1],category_level3=path[2],price=price,quantity=quantity,total_price=total,
                purchase_date=purchase,purchase_month=purchase_month,source=text(data.get('source'),150),**images,product_url=url,
                notes=text(data.get('notes')),ai_generated=int(bool(data.get('ai_generated'))),import_entry_id=text(data.get('import_entry_id')) or None,
                recognition_task_id=task,recognition_item_index=candidate if task else None,
                created_at=previous.get('created_at',ts()),updated_at=ts())
    updates=','.join(k+'=excluded.'+k for k in values if k not in ('id','user_id','created_at'))
    conn.execute(f'INSERT INTO gift_items({",".join(values)}) VALUES({",".join("?" for _ in values)}) ON CONFLICT(id) DO UPDATE SET {updates}',tuple(values.values()))
    return public(owned(conn,'gift_items',values['id'],user))

def save_item(user,data,ident=None):
    with connection(True) as conn: return create_item(conn,user,data,ident)

def batch_items(user,data):
    key=text(data.get('request_key'),100)
    items=data.get('items')
    if not key or not isinstance(items,list) or not 1<=len(items)<=100: raise GiftError('请勾选 1—100 件商品并提供确认标识')
    digest=hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    with connection(True) as conn:
        previous=conn.execute('SELECT * FROM gift_confirmation_batches WHERE user_id=? AND request_key=?',(user,key)).fetchone()
        if previous:
            if previous['payload_hash']!=digest: raise GiftError('该批次已保存，请刷新后重新提交',409)
            return json.loads(previous['result'])
        result=[create_item(conn,user,item) for item in items if isinstance(item,dict)]
        if len(result)!=len(items): raise GiftError('商品格式不正确')
        conn.execute('INSERT INTO gift_confirmation_batches VALUES(?,?,?,?,?,?)',(uid(),user,key,digest,json.dumps(result,ensure_ascii=False),ts()))
        return result

def list_items(user,params):
    where=['user_id=?'];args=[user]
    with connection() as conn:
        if params.get('recipient_id'):
            owned(conn,'gift_recipients',params['recipient_id'],user);where.append('recipient_id=?');args.append(params['recipient_id'])
        if params.get('month'): where.append('purchase_month=?');args.append(month(params['month']))
        if params.get('q'):
            where.append('(product_name LIKE ? ESCAPE "\\" OR brand LIKE ? ESCAPE "\\")')
            query='%'+text(params['q'],100).replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%';args.extend([query,query])
        if params.get('category_id'):
            path=category_path(conn,params['category_id'],user)
            for n,name in enumerate(path,1):
                if name: where.append(f'category_level{n}=?');args.append(name)
        offset=integer(params.get('offset',0),0,1000000)
        rows=conn.execute('SELECT * FROM gift_items WHERE '+' AND '.join(where)+' ORDER BY purchase_month DESC,purchase_date DESC,created_at DESC LIMIT 101 OFFSET ?',(*args,offset)).fetchall()
        return {'items':[public(r) for r in rows[:100]],'has_more':len(rows)>100}

def duplicates(user,params):
    with connection() as conn:
        owned(conn,'gift_recipients',params.get('recipient_id'),user)
        path=category_path(conn,params.get('category_id'),user)
        if not path[1]: return {'items':[],'marks':[],'exact_count':0,'related_count':0}
        rows=conn.execute('SELECT * FROM gift_items WHERE user_id=? AND recipient_id=? AND purchase_month>=? AND purchase_month<=? AND category_level1=? AND category_level2=? AND id<>? ORDER BY purchase_month DESC,purchase_date DESC',
                          (user,params['recipient_id'],months_ago(6),today()[:7],path[0],path[1],params.get('exclude_id',''))).fetchall()
        marks=conn.execute('SELECT m.*,c.name FROM gift_purchase_marks m JOIN gift_categories c ON c.id=m.category_id WHERE m.user_id=? AND m.recipient_id=? AND m.purchase_month BETWEEN ? AND ? AND (c.id=? OR c.parent_id=(SELECT parent_id FROM gift_categories WHERE id=?)) ORDER BY purchase_month DESC',
                           (user,params['recipient_id'],months_ago(6),today()[:7],params.get('category_id'),params.get('category_id'))).fetchall()
        exact=sum(r['category_level3']==path[2] for r in rows) if path[2] else 0
        return {'items':[public(r) for r in rows[:5]],'marks':[dict(r) for r in marks[:5]],'exact_count':exact,'related_count':len(rows)-exact}

def dashboard(user,recipient):
    with connection() as conn:
        profile=public(owned(conn,'gift_recipients',recipient,user));m=today()[:7]
        summary=dict(conn.execute('SELECT COUNT(*) records,COALESCE(SUM(quantity),0) units,SUM(quantity IS NULL) unknown_quantity,COALESCE(SUM(total_price),0) amount,SUM(total_price IS NULL) unknown_amount,COUNT(DISTINCT NULLIF(category_level1,"")) categories FROM gift_items WHERE user_id=? AND recipient_id=? AND purchase_month=?',(user,recipient,m)).fetchone())
        summary['amount']/=100
        counts=[dict(r) for r in conn.execute('SELECT category_level1 name,COUNT(*) count FROM gift_items WHERE user_id=? AND recipient_id=? AND category_level1<>"" GROUP BY category_level1 ORDER BY count DESC',(user,recipient))]
        recent=[public(r) for r in conn.execute('SELECT * FROM gift_items WHERE user_id=? AND recipient_id=? ORDER BY COALESCE(purchase_month,"0000-00") DESC,created_at DESC LIMIT 6',(user,recipient))]
        return {'recipient':profile,'month':m,'summary':summary,'counts':counts,'recent':recent}

def recommendations(user,recipient):
    with connection() as conn:
        profile=public(owned(conn,'gift_recipients',recipient,user))
        rows=conn.execute('SELECT category_id,purchase_month FROM gift_items WHERE user_id=? AND recipient_id=? AND purchase_month BETWEEN ? AND ? UNION ALL SELECT category_id,purchase_month FROM gift_purchase_marks WHERE user_id=? AND recipient_id=? AND purchase_month BETWEEN ? AND ?',
                          (user,recipient,months_ago(6),today()[:7],user,recipient,months_ago(6),today()[:7])).fetchall()
        recent={};roots=set()
        for r in rows:
            if not r['category_id']:continue
            path=category_path(conn,r['category_id'],user);roots.add(path[0])
            if r['purchase_month']>=months_ago(3):recent[r['category_id']]=recent.get(r['category_id'],0)+1
        candidates=[]
        for r in conn.execute('SELECT * FROM gift_categories WHERE level=3 AND (user_id IS NULL OR user_id=?)',(user,)):
            path=category_path(conn,r['id'],user)
            if path[0].startswith('孕产') or not any(k in path[2] for k in ('绘本','积木','拼图','户外','形状认知','儿童袜')): continue
            score=(3 if path[0] not in roots else 1)-recent.get(r['id'],0)*3
            candidates.append({'category_id':r['id'],'name':path[2],'path':path,'score':score,'reason':'近半年尚未记录这个大类' if path[0] not in roots else '近期记录较少，可结合年龄和需要考虑'})
        candidates.sort(key=lambda x:x['score'],reverse=True)
        avoid=[{'name':category_path(conn,k,user)[2],'count':v} for k,v in sorted(recent.items(),key=lambda x:x[1],reverse=True)[:5]]
        return {'recipient':profile,'suggestions':[x for x in candidates if x['score']>0][:5],'reduce':avoid,'note':'这是分类覆盖规则推荐，请结合年龄、过敏信息和实际需要选择。旧表标记表示该月买过，不代表购买次数。'}
