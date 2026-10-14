"""Bounded OSS diagnostics: never expose URLs, response messages or credentials."""
import base64
import logging
import re
import uuid
import xml.etree.ElementTree as ET
from functools import wraps
from urllib.error import HTTPError, URLError

from infrastructure.storage import PrivateOSS


def step(label):
    def decorate(function):
        @wraps(function)
        def run(self, *args, **kwargs):
            try:
                return function(self, *args, **kwargs)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                exc.share_storage_step = label
                raise
        return run
    return decorate


class DiagnosticOSS(PrivateOSS):
    begin = step('初始化分片上传')(PrivateOSS.begin)
    head = step('检查文件状态')(PrivateOSS.head)
    complete = step('合并上传分片')(PrivateOSS.complete)
    verify_private = step('校验私有访问权限')(PrivateOSS.verify_private)
    sample = step('读取文件类型样本')(PrivateOSS.sample)
    abort = step('取消分片上传')(PrivateOSS.abort)
    delete = step('清理文件')(PrivateOSS.delete)


def safe_token(value):
    return value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,96}', value) else ''


def storage_failure(exc, detailed=False):
    trace = uuid.uuid4().hex[:12]
    stage = getattr(exc, 'share_storage_step', '访问对象存储')
    code, request_id, status = '', '', None
    if isinstance(exc, HTTPError):
        status = exc.code
        request_id = safe_token((exc.headers or {}).get('x-oss-request-id', ''))
        payloads = []
        try:
            payloads.append(exc.read(8192))
        except Exception:
            pass
        # HEAD errors carry their XML in a base64 header, without a body.
        encoded = (exc.headers or {}).get('x-oss-err', '')
        if isinstance(encoded, str) and len(encoded) <= 12000:
            try:
                payloads.append(base64.b64decode(encoded, validate=True))
            except (ValueError, TypeError):
                pass
        for payload in payloads:
            try:
                if len(payload) > 8192 or b'<!DOCTYPE' in payload.upper() or b'<!ENTITY' in payload.upper():
                    continue
                root = ET.fromstring(payload)
                code = code or safe_token(root.findtext('Code'))
                request_id = request_id or safe_token(root.findtext('RequestId'))
            except ET.ParseError:
                pass
        category = 'HTTP' + str(status)
    elif isinstance(exc, TimeoutError) or (isinstance(exc, URLError) and isinstance(exc.reason, TimeoutError)):
        category = 'Timeout'
    else:
        category = 'NetworkError'
    logging.getLogger(__name__).warning(
        'share_storage_failure trace=%s stage=%s category=%s code=%s request_id=%s',
        trace, stage, category, code or '-', request_id or '-')
    if detailed:
        return f'{stage}失败（{category}{" / " + code if code else ""}；诊断编号：{trace}），请保留此提示'
    return f'存储操作失败，请稍后重试（诊断编号：{trace}）'
