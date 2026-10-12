import time
from urllib.parse import parse_qs, urlparse

from ..database import db
from ..usage_time import IDLE_MS, record_segments, date_range, daily_rows, totals


class UsageTimeHandlersMixin:
    def handle_usage_time(self):
        user = self.current_user()
        parsed = urlparse(self.path)
        path = parsed.path.removeprefix('/api/usage-time/')
        query = parse_qs(parsed.query)
        if path == 'config' and self.command == 'GET':
            return self.json({'server_now_ms':int(time.time()*1000),'idle_ms':IDLE_MS,'heartbeat_ms':30000})
        if path == 'heartbeat' and self.command == 'POST':
            try:
                data = self.read_body(limit=8192)
                if not isinstance(data,dict):
                    raise ValueError('请求格式错误')
                if data.get('account_id') != user['id']:
                    return self.error(409,'账号已变化，请重新加载')
                with db() as conn:
                    credited = record_segments(conn,user['id'],data.get('segments'),int(time.time()*1000))
                return self.json({'credited_ms':credited})
            except ValueError as exc:
                return self.error(400,str(exc))
        if self.command != 'GET' or path not in ('self','admin','admin/user'):
            return self.error(404,'not found')
        if path.startswith('admin') and user['role'] != 'admin':
            return self.error(403,'仅管理员可查看所有账号')
        try:
            start,end = date_range(query)
        except ValueError as exc:
            return self.error(400,str(exc))
        with db() as conn:
            if path in ('self','admin/user'):
                uid = user['id'] if path == 'self' else query.get('user_id',[''])[0]
                if not conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():
                    return self.error(404,'账号不存在')
                rows = daily_rows(conn,uid,start,end)
                return self.json({'days':rows,'summary':totals(rows),'start':start,'end':end})
            term = query.get('q',[''])[0][:80].strip()
            sort = query.get('sort',['total'])[0]
            order = {'work':'work_ms','reading':'reading_ms','total':'total_ms','last':'last_active'}.get(sort,'total_ms')
            rows = [dict(r) for r in conn.execute(f'''SELECT u.id,u.username,u.display_name,
                COALESCE(t.work_ms,0) work_ms,COALESCE(t.reading_ms,0) reading_ms,
                COALESCE(t.work_ms,0)+COALESCE(t.reading_ms,0) total_ms,t.last_active
                FROM users u LEFT JOIN (
                  SELECT user_id,SUM(work_ms) work_ms,SUM(reading_ms) reading_ms,MAX(last_active) last_active
                  FROM usage_time_daily WHERE date BETWEEN ? AND ? GROUP BY user_id
                ) t ON t.user_id=u.id
                WHERE instr(lower(u.username),lower(?))>0 OR instr(lower(COALESCE(u.display_name,'')),lower(?))>0
                ORDER BY {order} DESC,u.username''',(start,end,term,term))]
            summary = totals(rows)
            summary['active_users'] = sum(r['total_ms'] > 0 for r in rows)
            return self.json({'users':rows,'summary':summary,'start':start,'end':end})
