import sys,sqlite3,tempfile,json,threading,time,os
from pathlib import Path
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse,parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from gift import database,services,orders,logistics
root=Path(tempfile.mkdtemp(prefix='gift-orders-test-'));dbfile=root/'test.db'
def db():
    c=sqlite3.connect(dbfile);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON');return c
database.db=db
with db() as c:
    c.execute('CREATE TABLE users(id TEXT PRIMARY KEY)');c.executemany('INSERT INTO users VALUES(?)',[('a',),('b',)]);c.executescript(Path('gift/schema.sql').read_text())
r=services.save_recipient('a',{'name':'宝宝'})['id'];other=services.save_recipient('b',{'name':'其他宝宝'})['id']
i=services.save_item('a',{'recipient_id':r,'product_name':'绘本','purchase_month':'2026-10','quantity':2,'total_price':25})
j=services.save_item('a',{'recipient_id':r,'product_name':'湿巾','purchase_month':'2026-10'})
k=services.save_item('b',{'recipient_id':other,'product_name':'他人商品'})
def rejected(fn,status=None):
    try:fn();raise AssertionError('expected rejection')
    except services.GiftError as e:
        if status:assert e.status==status,(status,e.status)
o=orders.save_order('a',{'recipient_id':r,'purchase_month':'2026-10','title':'本月订单','item_ids':[i['id'],j['id']]})
assert o['amount']==25 and o['units']==2 and o['unknown_amount']==1
rejected(lambda:orders.save_order('a',{'recipient_id':r,'purchase_month':'2026-10','title':'重复关联','item_ids':[i['id']]}),409)
rejected(lambda:orders.save_order('a',{'recipient_id':r,'purchase_month':'2026-10','title':'越权','item_ids':[k['id']]}),404)
rejected(lambda:orders.list_orders('b',{'recipient_id':r}),404)
rejected(lambda:services.save_item('a',{'purchase_month':'2026-09'},i['id']),409)
assert orders.list_orders('a',{'recipient_id':r,'item_id':i['id']})['orders'][0]['id']==o['id']
s=orders.save_shipment('a',o['id'],{'carrier_code':'SF','tracking_number':'TEST00000001','receiver_phone':'1234'})
rejected(lambda:orders.save_shipment('a',o['id'],{'carrier_code':'SF','tracking_number':'TEST00000001'}),409)
rejected(lambda:orders.refresh('b',s['id']),404)
class Upstream(BaseHTTPRequestHandler):
    calls=0;mode='ok'
    def log_message(self,*args):pass
    def do_GET(self):
        type(self).calls+=1
        assert self.headers['Authorization']=='APPCODE synthetic-test-code'
        arg=json.loads(parse_qs(urlparse(self.path).query)['logistics_interface'][0])['arg0']
        assert arg['mailNo']=='TEST00000001' and arg['receiverPhone']=='1234' and arg['appCode']=='aliyun_public'
        if self.mode=='html':self.send_response(500);self.end_headers();self.wfile.write(b'<html>failure</html>');return
        if self.mode=='bad':self.send_response(200);self.end_headers();self.wfile.write(b'not-json');return
        if self.mode=='reject':payload={'success':'false','errorCode':'400'}
        else:payload={'success':'true','errorCode':'0','result':{'code':'0','data':json.dumps({'lastState':'TRANSPORT','detail':[{'opTime':'2026-10-22 12:00:00','opMessage':'已揽收'},{'opTime':'2026-10-22 13:00:00','opMessage':'运输中'}]})}}
        self.send_response(200);self.end_headers();self.wfile.write(json.dumps(payload).encode())
server=ThreadingHTTPServer(('127.0.0.1',0),Upstream);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
os.environ['GIFT_LOGISTICS_APPCODE']='synthetic-test-code';os.environ['GIFT_LOGISTICS_ENDPOINT']='http://127.0.0.1:'+str(server.server_port)+'/api/LogisticsDetail'
result=orders.refresh('a',s['id']);assert not result['cached'] and result['shipment']['tracking']['state_label']=='运输中'
assert result['shipment']['tracking']['events'][0]['time']=='2026-10-22 13:00:00'
assert orders.refresh('a',s['id'])['cached'] and Upstream.calls==1
for mode in ['html','bad','reject']:
    with db() as c:c.execute('UPDATE gift_shipments SET checked_at=?,last_attempt_at=NULL WHERE id=?',(services.ts()-400,s['id']))
    Upstream.mode=mode;rejected(lambda:orders.refresh('a',s['id']))
    with db() as c:
        row=c.execute('SELECT * FROM gift_shipments WHERE id=?',(s['id'],)).fetchone();assert json.loads(row['tracking_result'])['events'] and row['last_error']
with db() as c:c.execute('UPDATE gift_shipments SET last_attempt_at=NULL WHERE id=?',(s['id'],))
os.environ['GIFT_LOGISTICS_ENDPOINT']='http://127.0.0.1:1/api/LogisticsDetail';rejected(lambda:orders.refresh('a',s['id']),502)
orders.delete_order('a',o['id'])
with db() as c:
    assert c.execute('SELECT COUNT(*) FROM gift_shipments').fetchone()[0]==0
    assert c.execute('SELECT COUNT(*) FROM gift_order_items').fetchone()[0]==0
    assert c.execute('SELECT COUNT(*) FROM gift_items').fetchone()[0]==3
server.shutdown();server.server_close()
print('PASS order/package CRUD, isolation, association conflict, no expense double count; real HTTP client/auth/nested JSON/caching/HTML errors/malformed JSON/provider reject/unreachable; cached events and purchases preserved')
