"""账号隔离的订单、商品关联与包裹查询服务。"""
import json
import re
from .database import connection
from .services import GiftError,owned,public,uid,ts,text,month
from . import logistics


def serialized_shipment(row):
    value=dict(row)
    value['tracking']=json.loads(value.pop('tracking_result') or '{}')
    return value


def order_detail(conn,user,ident):
    result=dict(owned(conn,'gift_orders',ident,user))
    result['items']=[public(row) for row in conn.execute('SELECT i.* FROM gift_items i JOIN gift_order_items l ON l.item_id=i.id AND l.user_id=i.user_id WHERE l.order_id=? AND l.user_id=? ORDER BY i.created_at',(ident,user))]
    result['shipments']=[serialized_shipment(row) for row in conn.execute('SELECT * FROM gift_shipments WHERE order_id=? AND user_id=? ORDER BY created_at',(ident,user))]
    result['amount']=sum(i['total_price'] or 0 for i in result['items'])
    result['units']=sum(i['quantity'] or 0 for i in result['items'])
    result['unknown_amount']=sum(i['total_price'] is None for i in result['items'])
    return result


def list_orders(user,params):
    recipient=params.get('recipient_id');m=month(params.get('month'))
    with connection() as conn:
        owned(conn,'gift_recipients',recipient,user)
        where='user_id=? AND recipient_id=?';args=[user,recipient]
        if m:where+=' AND purchase_month=?';args.append(m)
        item=params.get('item_id')
        if item:
            owned(conn,'gift_items',item,user);where+=' AND id IN (SELECT order_id FROM gift_order_items WHERE user_id=? AND item_id=?)';args.extend([user,item])
        rows=conn.execute('SELECT id FROM gift_orders WHERE '+where+' ORDER BY purchase_month DESC,created_at DESC LIMIT 101',args).fetchall()
        return {'orders':[order_detail(conn,user,row['id']) for row in rows[:100]],'has_more':len(rows)>100}


def candidates(user,params):
    recipient=params.get('recipient_id');m=month(params.get('month'))
    with connection() as conn:
        owned(conn,'gift_recipients',recipient,user)
        where='i.user_id=? AND i.recipient_id=?';args=[user,recipient]
        if m:where+=" AND (i.purchase_month=? OR i.purchase_month IS NULL OR i.purchase_month='')";args.append(m)
        rows=conn.execute('SELECT i.*,l.order_id linked_order_id FROM gift_items i LEFT JOIN gift_order_items l ON i.id=l.item_id AND i.user_id=l.user_id WHERE '+where+' ORDER BY i.created_at DESC LIMIT 201',args).fetchall()
        return {'items':[public(row) for row in rows[:200]],'has_more':len(rows)>200}


def save_order(user,data,ident=None):
    with connection(True) as conn:
        previous=dict(owned(conn,'gift_orders',ident,user)) if ident else {}
        value={**previous,**data};recipient=value.get('recipient_id');owned(conn,'gift_recipients',recipient,user)
        m=month(value.get('purchase_month'))
        if not m:raise GiftError('请选择订单所属月份')
        title=text(value.get('title'),150)
        if not title:raise GiftError('请填写订单名称')
        ids=data.get('item_ids')
        if ids is None:
            ids=[row['item_id'] for row in conn.execute('SELECT item_id FROM gift_order_items WHERE order_id=? AND user_id=?',(ident,user))] if ident else []
        if not isinstance(ids,list) or len(ids)>200 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise GiftError('商品关联参数不正确')
        ident=ident or uid()
        for item_id in ids:
            item=owned(conn,'gift_items',item_id,user)
            if item['recipient_id']!=recipient:raise GiftError('订单只能关联当前收礼对象的商品')
            if item['purchase_month'] and item['purchase_month']!=m:raise GiftError('商品月份与订单月份不一致，请先修改商品日期')
            link=conn.execute('SELECT order_id FROM gift_order_items WHERE user_id=? AND item_id=?',(user,item_id)).fetchone()
            if link and link['order_id']!=ident:raise GiftError('商品已关联其他订单，请先在原订单取消关联',409)
        values=(ident,user,recipient,m,title,text(value.get('order_number'),120),text(value.get('source'),150),text(value.get('notes')),previous.get('created_at',ts()),ts())
        conn.execute('INSERT INTO gift_orders VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET recipient_id=excluded.recipient_id,purchase_month=excluded.purchase_month,title=excluded.title,order_number=excluded.order_number,source=excluded.source,notes=excluded.notes,updated_at=excluded.updated_at',values)
        conn.execute('DELETE FROM gift_order_items WHERE order_id=? AND user_id=?',(ident,user))
        conn.executemany('INSERT INTO gift_order_items VALUES(?,?,?)',[(user,ident,item) for item in ids])
        return order_detail(conn,user,ident)


def delete_order(user,ident):
    with connection(True) as conn:
        owned(conn,'gift_orders',ident,user)
        conn.execute('DELETE FROM gift_orders WHERE id=? AND user_id=?',(ident,user))
    return {'ok':True}


def save_shipment(user,order,data,ident=None):
    with connection(True) as conn:
        owned(conn,'gift_orders',order,user)
        previous=dict(owned(conn,'gift_shipments',ident,user)) if ident else {}
        if previous and previous['order_id']!=order:raise GiftError('包裹不属于当前订单',404)
        value={**previous,**data}
        code=text(value.get('carrier_code'),30).upper();tracking=text(value.get('tracking_number'),80)
        if not re.fullmatch(r'[A-Z0-9_-]{1,30}',code):raise GiftError('请填写快递公司代码，可在提示中选择或手动填写')
        if not re.fullmatch(r'[A-Za-z0-9-]{5,80}',tracking):raise GiftError('请填写有效的快递运单号，不是商城订单号')
        is_tb=value.get('is_tb',False)
        if is_tb not in (True,False,0,1):raise GiftError('淘宝包裹参数不正确')
        fields={k:text(value.get(k),300 if 'address' in k else 30) for k in ['receiver_phone','sender_phone','sender_address','delivery_address','carrier_name']}
        for k in ['receiver_phone','sender_phone']:
            if fields[k] and not re.fullmatch(r'[0-9+ -]{4,30}',fields[k]):raise GiftError('验证手机号格式不正确')
        changed=any(previous.get(k)!=v for k,v in {**fields,'carrier_code':code,'tracking_number':tracking,'is_tb':int(is_tb)}.items())
        ident=ident or uid();now=ts()
        try:
            conn.execute('''INSERT INTO gift_shipments VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
             ON CONFLICT(id) DO UPDATE SET carrier_code=excluded.carrier_code,carrier_name=excluded.carrier_name,tracking_number=excluded.tracking_number,
             receiver_phone=excluded.receiver_phone,sender_phone=excluded.sender_phone,sender_address=excluded.sender_address,delivery_address=excluded.delivery_address,is_tb=excluded.is_tb,
             tracking_result=excluded.tracking_result,checked_at=excluded.checked_at,last_attempt_at=excluded.last_attempt_at,last_error=excluded.last_error,updated_at=excluded.updated_at''',
             (ident,user,order,code,fields['carrier_name'],tracking,fields['receiver_phone'],fields['sender_phone'],fields['sender_address'],fields['delivery_address'],int(is_tb),
              '{}' if changed else previous.get('tracking_result','{}'),None if changed else previous.get('checked_at'),None if changed else previous.get('last_attempt_at'),'' if changed else previous.get('last_error',''),previous.get('created_at',now),now))
        except Exception as exc:
            import sqlite3
            if isinstance(exc,sqlite3.IntegrityError):raise GiftError('这个运单已关联当前订单',409)
            raise
        return serialized_shipment(owned(conn,'gift_shipments',ident,user))


def refresh(user,ident):
    with connection(True) as conn:
        row=dict(owned(conn,'gift_shipments',ident,user));now=ts()
        if row['checked_at'] and now-row['checked_at']<300:
            return {'shipment':serialized_shipment(row),'cached':True}
        code,_=logistics.configuration()
        if not code:raise GiftError('物流服务尚未配置',503)
        if row['last_attempt_at'] and now-row['last_attempt_at']<30:raise GiftError('刚刚查询过这个包裹，请稍后再试',429)
        conn.execute('UPDATE gift_shipments SET last_attempt_at=? WHERE id=? AND user_id=?',(now,ident,user))
    try:result=logistics.query(row)
    except GiftError as exc:
        with connection(True) as conn:
            conn.execute('UPDATE gift_shipments SET last_error=? WHERE id=? AND user_id=? AND updated_at=?',(str(exc),ident,user,row['updated_at']))
        raise
    with connection(True) as conn:
        current=owned(conn,'gift_shipments',ident,user)
        if any(current[k]!=row[k] for k in ('updated_at','carrier_code','tracking_number','receiver_phone','sender_phone','sender_address','delivery_address','is_tb')):raise GiftError('包裹信息已修改，请重新查询',409)
        conn.execute('UPDATE gift_shipments SET tracking_result=?,checked_at=?,last_error="" WHERE id=? AND user_id=?',(json.dumps(result,ensure_ascii=False),ts(),ident,user))
        return {'shipment':serialized_shipment(owned(conn,'gift_shipments',ident,user)),'cached':False}
