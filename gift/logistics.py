"""菜鸟云市场物流客户端：服务端鉴权、固定供应商地址、显式查询。"""
import json
import os
import socket
import urllib.request
from pathlib import Path
from urllib.error import HTTPError,URLError
from urllib.parse import urlencode,urlparse
from ai_platform.settings import DATA_DIR
from .services import GiftError,text

ENDPOINT='https://logistics.market.alicloudapi.com/api/LogisticsDetail'

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def configuration():
    code=os.environ.get('GIFT_LOGISTICS_APPCODE','').strip()
    path=DATA_DIR/'gift-logistics.secret.json'
    if not code and path.exists():
        try:code=str(json.loads(path.read_text()).get('appcode') or '').strip()
        except (ValueError,OSError):raise GiftError('物流服务配置不可用',503)
    endpoint=os.environ.get('GIFT_LOGISTICS_ENDPOINT',ENDPOINT)
    parsed=urlparse(endpoint)
    if parsed.scheme!='https' and not (parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost')):
        raise GiftError('物流服务地址配置无效',503)
    return code,endpoint

def unpack(value):
    for _ in range(3):
        if not isinstance(value,str):return value
        try:value=json.loads(value)
        except (ValueError,TypeError):return None
    return value

def normalize(raw):
    raw=unpack(raw)
    if not isinstance(raw,dict):raise GiftError('物流服务返回格式异常，请稍后重试',502)
    if str(raw.get('success')).lower()!='true' or str(raw.get('errorCode','0')) not in ('0','200'):
        raise GiftError('未查到物流信息，请核对运单号、快递公司和验证手机号',422)
    result=unpack(raw.get('result'))
    if not isinstance(result,dict) or str(result.get('code'))!='0':
        raise GiftError('物流查询未成功，请核对运单信息后重试',422)
    data=unpack(result.get('data'))
    if not isinstance(data,dict):raise GiftError('物流服务返回格式异常，请稍后重试',502)
    details=data.get('detail',[])
    if not isinstance(details,list):raise GiftError('物流轨迹格式异常，请稍后重试',502)
    events=[]
    for item in details[:200]:
        if not isinstance(item,dict):continue
        message=text(item.get('opMessage') or item.get('opDesc'),2000)
        if not message:continue
        events.append({'time':text(item.get('opTime'),80),'message':message,'location':text(item.get('addressText') or item.get('cityName'),300)})
    events.sort(key=lambda e:e['time'],reverse=True)
    state=text(data.get('lastState'),60)
    labels={'SIGN':'已签收','SIGNED':'已签收','ACCEPT':'已揽收','TRANSPORT':'运输中','DELIVERY':'派送中','DELIVERING':'派送中','FAILED':'物流异常','RETURN':'退回中'}
    return {'state':state,'state_label':labels.get(state,'物流有更新' if events else '暂无轨迹'),'events':events,
            'notice':'' if events else '接口调用成功，暂未返回运输轨迹；请核对公司、单号或稍后刷新。'}

def query(shipment):
    code,endpoint=configuration()
    if not code:raise GiftError('物流服务尚未配置',503)
    arg={'cpCode':shipment['carrier_code'],'mailNo':shipment['tracking_number'],'isTb':'Y' if shipment['is_tb'] else 'N','appCode':'aliyun_public'}
    for local,remote in [('receiver_phone','receiverPhone'),('sender_phone','senderPhone'),('sender_address','senderAddress'),('delivery_address','deliveryAddress')]:
        if shipment.get(local):arg[remote]=shipment[local]
    url=endpoint+'?'+urlencode({'logistics_interface':json.dumps({'arg0':arg},ensure_ascii=False,separators=(',',':'))})
    request=urllib.request.Request(url,headers={'Authorization':'APPCODE '+code,'Accept':'application/json'},method='GET')
    try:
        with urllib.request.build_opener(NoRedirect).open(request,timeout=12) as response:
            payload=response.read(2*1024*1024+1)
            if len(payload)>2*1024*1024:raise GiftError('物流服务返回内容过大',502)
            return normalize(json.loads(payload))
    except HTTPError as exc:
        if exc.code in (401,403):raise GiftError('物流接口鉴权或额度异常，请联系管理员检查已购买服务',502)
        if exc.code==429:raise GiftError('物流服务繁忙，请稍后重试',429)
        raise GiftError('物流服务暂不可用，已保存的订单与轨迹不受影响',502)
    except (socket.timeout,TimeoutError):raise GiftError('物流查询超时，请稍后重试；原有轨迹已保留',504)
    except (URLError,OSError):raise GiftError('暂时无法连接物流服务，请稍后重试',502)
    except (ValueError,TypeError):raise GiftError('物流服务返回格式异常，请稍后重试',502)
