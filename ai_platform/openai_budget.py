"""平台级 OpenAI 月度估算额度；账本独立于可删除的聊天记录。"""
import codecs
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
import json
import logging
import os
import sqlite3
import time
import urllib.error
from urllib.parse import urlparse
import uuid

MICRO = 1000000
BEIJING = timezone(timedelta(hours=8))


class BudgetError(urllib.error.URLError):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


def _db():
    from .database import db
    return db()


def _decimal(value):
    try:
        result = Decimal(str(value))
        if result.is_finite() and result >= 0:
            return result
    except (InvalidOperation, ValueError, TypeError):
        pass
    raise ValueError("金额或汇率格式不正确")


def _micro(value):
    return int((_decimal(value) * MICRO).to_integral_value(rounding=ROUND_CEILING))


def period(timestamp=None):
    date = datetime.fromtimestamp(time.time() if timestamp is None else timestamp, BEIJING)
    start = date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start.strftime("%Y-%m"), int(start.timestamp()), int(end.timestamp())


def _official(url):
    try:
        return urlparse(str(url)).hostname == "api.openai.com"
    except ValueError:
        return False


def _cost(prompt, completion, ip, op):
    # 单价单位为美元/百万 Token，计算结果直接是微美元。
    return int((Decimal(prompt) * _decimal(ip) + Decimal(completion) * _decimal(op)).to_integral_value(rounding=ROUND_CEILING))


def init_tables(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS openai_budget_settings (
        id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL,
        limit_micro INTEGER NOT NULL, cny_per_usd TEXT NOT NULL, initialized_at INTEGER NOT NULL,
        updated_at INTEGER NOT NULL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS openai_budget_events (
        id TEXT PRIMARY KEY, period TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL,
        reserved_micro INTEGER NOT NULL DEFAULT 0, cost_micro INTEGER NOT NULL DEFAULT 0,
        input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0,
        input_price_usd TEXT NOT NULL DEFAULT '0', output_price_usd TEXT NOT NULL DEFAULT '0',
        owner_pid INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_openai_budget_period ON openai_budget_events(period,status)")
    ts = int(time.time())
    new = conn.execute("INSERT OR IGNORE INTO openai_budget_settings VALUES(1,1,50000000,'6.718',?,?)", (ts, ts)).rowcount
    if new:
        _seed_history(conn, ts)
    # 仅回收已退出进程的预留；其他维护进程初始化不能干扰活跃生成。
    for row in conn.execute("SELECT DISTINCT owner_pid FROM openai_budget_events WHERE status='pending'").fetchall():
        pid = row["owner_pid"]
        try:
            if pid > 0:
                os.kill(pid, 0)
                continue
        except PermissionError:
            continue
        except ProcessLookupError:
            pass
        conn.execute("UPDATE openai_budget_events SET status='uncertain',cost_micro=reserved_micro,updated_at=? WHERE status='pending' AND owner_pid=?", (ts, pid))


def _seed_history(conn, ts):
    month, start, _ = period(ts)
    models = {row["id"]: dict(row) for row in conn.execute("SELECT * FROM models").fetchall() if _official(row["base_url"])}
    rows = conn.execute("""SELECT m.id,m.prompt_tokens,m.completion_tokens,m.cost_input_price,m.cost_output_price,
        m.cost_model_id,m.actual_model,m.created_at,c.model_id FROM messages m
        LEFT JOIN conversations c ON c.id=m.conversation_id
        WHERE m.created_at>=? AND m.created_at<=? AND m.role IN ('assistant','system')
        AND (m.prompt_tokens>0 OR m.completion_tokens>0)""", (start, ts)).fetchall()
    entries = []
    for row in rows:
        model = models.get(row["cost_model_id"] or row["model_id"])
        if not model or (not row["cost_model_id"] and row["actual_model"] and row["actual_model"] != model["model"]):
            continue
        entries.append(("legacy:main:" + str(row["id"]), model, row["prompt_tokens"], row["completion_tokens"],
                        row["cost_input_price"], row["cost_output_price"], row["created_at"]))
    rows = conn.execute("""SELECT m.id,m.input_tokens,m.output_tokens,m.actual_model,m.created_at,d.model_id
        FROM side_discussion_messages m JOIN side_discussions d ON d.id=m.discussion_id
        WHERE m.created_at>=? AND m.created_at<=? AND m.role='assistant'
        AND (m.input_tokens>0 OR m.output_tokens>0)""", (start, ts)).fetchall()
    for row in rows:
        model = models.get(row["model_id"])
        if model and (not row["actual_model"] or row["actual_model"] == model["model"]):
            entries.append(("legacy:side:" + str(row["id"]), model, row["input_tokens"], row["output_tokens"], 0, 0, row["created_at"]))
    for key, model, pt, ct, ip, op, created in entries:
        ip = str(_decimal(ip or model["input_price_per_million"]) / Decimal('6.718'))
        op = str(_decimal(op or model["output_price_per_million"]) / Decimal('6.718'))
        status = 'unpriced' if _decimal(ip) == _decimal(op) == 0 else 'legacy'
        conn.execute("""INSERT OR IGNORE INTO openai_budget_events
            (id,period,model,status,cost_micro,input_tokens,output_tokens,input_price_usd,output_price_usd,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (key, month, model["model"], status, _cost(pt, ct, ip, op), pt, ct, ip, op, created, ts))


def _snapshot(conn):
    config = conn.execute("SELECT * FROM openai_budget_settings WHERE id=1").fetchone()
    if not config:
        raise BudgetError("budget_unavailable", "OpenAI 额度服务尚未初始化，请联系管理员")
    month, start, end = period()
    row = conn.execute("""SELECT COALESCE(SUM(cost_micro),0) AS spent,
        COALESCE(SUM(CASE WHEN status='pending' THEN reserved_micro ELSE 0 END),0) AS reserved,
        COALESCE(SUM(CASE WHEN status='uncertain' THEN 1 ELSE 0 END),0) AS uncertain,
        COALESCE(SUM(CASE WHEN status='unpriced' THEN 1 ELSE 0 END),0) AS unpriced,
        COUNT(*) AS requests FROM openai_budget_events WHERE period=?""", (month,)).fetchone()
    return dict(config), dict(row), month, start, end


def summary():
    with _db() as conn:
        cfg, totals, month, start, end = _snapshot(conn)
    spent, pending, limit = totals["spent"], totals["reserved"], cfg["limit_micro"]
    return {"enabled": bool(cfg["enabled"]), "limit_usd": limit / MICRO, "cny_per_usd": float(cfg["cny_per_usd"]),
            "period": month, "timezone": "Asia/Shanghai", "resets_at": end, "spent_usd": spent / MICRO,
            "reserved_usd": pending / MICRO, "remaining_usd": max(0, limit - spent - pending) / MICRO,
            "exhausted": bool(cfg["enabled"] and spent >= limit),
            "pending_limit": bool(cfg["enabled"] and spent < limit and spent + pending >= limit),
            "warning": bool(cfg["enabled"] and spent >= limit * .8), "uncertain_requests": totals["uncertain"],
            "unpriced_requests": totals["unpriced"],
            "request_count": totals["requests"], "initialized_at": cfg["initialized_at"], "updated_at": cfg["updated_at"]}


def configure(data):
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
        raise ValueError("请设置额度保护开关")
    limit, rate = _decimal(data.get("limit_usd")), _decimal(data.get("cny_per_usd"))
    if not Decimal('.01') <= limit <= 1000000 or not Decimal('.01') <= rate <= 1000:
        raise ValueError("月度额度须为 0.01～1000000 美元，汇率须为 0.01～1000")
    with _db() as conn:
        conn.execute("UPDATE openai_budget_settings SET enabled=?,limit_micro=?,cny_per_usd=?,updated_at=? WHERE id=1",
                     (int(data["enabled"]), _micro(limit), str(rate), int(time.time())))
    return summary()


def _limit_error(cfg, totals):
    if cfg["enabled"] and totals["spent"] >= cfg["limit_micro"]:
        return BudgetError("monthly_budget_exhausted", "本月 OpenAI 额度已用完，请选择其它模型；下月自动恢复")
    if cfg["enabled"] and totals["spent"] + totals["reserved"] >= cfg["limit_micro"]:
        return BudgetError("monthly_budget_reserved", "本月 OpenAI 剩余额度已预留给进行中的请求，请稍后重试或选择其它模型")
    return None


def check():
    try:
        with _db() as conn:
            cfg, totals, *_ = _snapshot(conn)
    except sqlite3.Error:
        raise BudgetError("budget_unavailable", "OpenAI 额度检查暂不可用，请稍后重试或选择其它模型") from None
    error = _limit_error(cfg, totals)
    if error:
        raise error


def begin(request):
    if request.get_method() != "POST" or urlparse(request.full_url).path.rstrip('/') not in ('/v1/chat/completions', '/v1/responses'):
        return None
    try:
        payload = json.loads(request.data or b'{}')
        name = str(payload.get("model") or "")
        with _db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            cfg, totals, month, *_ = _snapshot(conn)
            error = _limit_error(cfg, totals)
            if error:
                raise error
            models = [row for row in conn.execute("SELECT base_url,input_price_per_million,output_price_per_million FROM models WHERE model=?", (name,)).fetchall() if _official(row["base_url"])]
            ip = max((_decimal(row["input_price_per_million"]) for row in models), default=Decimal(0)) / _decimal(cfg["cny_per_usd"])
            op = max((_decimal(row["output_price_per_million"]) for row in models), default=Decimal(0)) / _decimal(cfg["cny_per_usd"])
            if cfg["enabled"] and ip == op == 0:
                raise BudgetError("budget_missing_price", "该 OpenAI 模型未配置计费价格，无法核算额度，请联系管理员")
            # 预留不是实际账单；输出默认预留 8192 Token，已发送请求仍允许完成。
            output = payload.get("max_completion_tokens") or payload.get("max_output_tokens") or payload.get("max_tokens") or 8192
            reserve = max(1, _cost(len(request.data or b''), min(10000000, max(1, int(output))), ip, op))
            if cfg["enabled"]:
                reserve = min(reserve, cfg["limit_micro"] - totals["spent"] - totals["reserved"])
            ts, key = int(time.time()), uuid.uuid4().hex
            conn.execute("""INSERT INTO openai_budget_events
                (id,period,model,status,reserved_micro,input_price_usd,output_price_usd,owner_pid,created_at,updated_at)
                VALUES (?,?,?,'pending',?,?,?,?,?,?)""", (key, month, name, reserve, str(ip), str(op), os.getpid(), ts, ts))
        return {"id": key, "stream": bool(payload.get("stream"))}
    except BudgetError:
        raise
    except (sqlite3.Error, ValueError, TypeError, OverflowError):
        raise BudgetError("budget_unavailable", "OpenAI 额度检查暂不可用，请稍后重试或选择其它模型") from None


def settle(ticket, usage=None, rejected=False):
    if not ticket:
        return
    try:
        with _db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM openai_budget_events WHERE id=? AND status='pending'", (ticket["id"],)).fetchone()
            if not row:
                return
            if rejected:
                status, amount, pt, ct = 'rejected', 0, 0, 0
            elif _decimal(row['input_price_usd']) == _decimal(row['output_price_usd']) == 0:
                status, amount = 'unpriced', 0
                pt, ct = usage or (0, 0)
            elif usage is not None:
                pt, ct = usage
                status, amount = 'charged', _cost(pt, ct, row['input_price_usd'], row['output_price_usd'])
            else:
                status, amount, pt, ct = 'uncertain', row['reserved_micro'], 0, 0
            conn.execute("UPDATE openai_budget_events SET status=?,cost_micro=?,input_tokens=?,output_tokens=?,updated_at=? WHERE id=? AND status='pending'",
                         (status, amount, pt, ct, int(time.time()), ticket['id']))
    except sqlite3.Error:
        # 保留预留，不让计费故障覆盖已经收到的聊天结果，也不输出内容或凭据。
        logging.error("OpenAI budget settlement unavailable; reservation retained")


class BudgetResponse:
    def __init__(self, response, ticket):
        self.response, self.ticket, self.closed = response, ticket, False
        self.decoder = codecs.getincrementaldecoder('utf-8')('replace')
        self.buffer, self.lines, self.usage = '', [], None
        self.event_size, self.dropped_event = 0, False

    def __getattr__(self, name):
        return getattr(self.response, name)

    def _event(self, text):
        try:
            event = json.loads(text)
            if not isinstance(event, dict):
                return
            usage = event.get('usage')
            if not isinstance(usage, dict) and isinstance(event.get('response'), dict):
                usage = event['response'].get('usage')
            if not isinstance(usage, dict):
                return
            pt = usage.get('prompt_tokens', usage.get('input_tokens'))
            ct = usage.get('completion_tokens', usage.get('output_tokens'))
            if pt is None or ct is None:
                return
            values = min(1000000000, max(0, int(pt))), min(1000000000, max(0, int(ct)))
            self.usage = tuple(max(a, b) for a, b in zip(self.usage or (0, 0), values))
        except (ValueError, TypeError, OverflowError):
            pass

    def _feed(self, chunk, final=False):
        self.buffer += self.decoder.decode(chunk, final=final)
        if len(self.buffer) > 2 * 1024 * 1024:
            self.buffer = ''
            self.lines = []
            return
        if not self.ticket['stream']:
            if final:
                self._event(self.buffer)
            return
        if final and self.buffer and not self.buffer.endswith('\n'):
            self.buffer += '\n'
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            line = line.rstrip('\r')
            if line.startswith('data:'):
                self.event_size += len(line)
                if self.event_size > 2 * 1024 * 1024:
                    self.lines = []
                    self.dropped_event = True
                elif not self.dropped_event:
                    self.lines.append(line[5:].lstrip(' '))
            elif not line and self.lines:
                self._event('\n'.join(self.lines))
                self.lines = []
            if not line:
                self.event_size, self.dropped_event = 0, False
        if final and self.lines:
            self._event('\n'.join(self.lines))
            self.lines = []

    def read(self, size=None):
        chunk = self.response.read() if size is None or size < 0 else self.response.read(size)
        self._feed(chunk)
        return chunk

    def read1(self, size=-1):
        reader = getattr(self.response, 'read1', None)
        chunk = reader(size) if reader else (self.response.read() if size < 0 else self.response.read(size))
        self._feed(chunk)
        return chunk

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self._feed(b'', final=True)
            self.response.close()
        finally:
            settle(self.ticket, self.usage)
