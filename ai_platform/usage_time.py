"""Short-lived deduplication intervals and permanent Beijing-day usage totals."""
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))
IDLE_MS = 120000
MAX_SEGMENT_MS = 35000


def init_usage_time_tables(conn):
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS usage_time_events (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          event_id TEXT NOT NULL, start_ms INTEGER NOT NULL, end_ms INTEGER NOT NULL,
          mode TEXT NOT NULL, PRIMARY KEY(user_id,event_id)
        );
        CREATE INDEX IF NOT EXISTS usage_time_event_end ON usage_time_events(user_id,end_ms);
        CREATE INDEX IF NOT EXISTS usage_time_cleanup ON usage_time_events(end_ms);
        CREATE TABLE IF NOT EXISTS usage_time_daily (
          user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          date TEXT NOT NULL, work_ms INTEGER NOT NULL DEFAULT 0,
          reading_ms INTEGER NOT NULL DEFAULT 0, last_active INTEGER NOT NULL,
          PRIMARY KEY(user_id,date)
        );
        CREATE INDEX IF NOT EXISTS usage_time_day ON usage_time_daily(date,user_id);
    ''')


def record_segments(conn, uid, segments, now_ms):
    if not isinstance(segments, list) or not 1 <= len(segments) <= 8:
        raise ValueError('每次最多提交 8 个时间段')
    checked = []
    for item in segments:
        if not isinstance(item, dict):
            raise ValueError('时间段格式错误')
        start, end, mode, eid = (item.get(k) for k in ('start_ms', 'end_ms', 'mode', 'id'))
        if (type(start) is not int or type(end) is not int or not 0 < end-start <= MAX_SEGMENT_MS
                or start < now_ms-120000 or end > now_ms+5000
                or mode not in ('work', 'reading') or not isinstance(eid, str)
                or not 8 <= len(eid) <= 80 or not all(c.isascii() and (c.isalnum() or c in '-_') for c in eid)):
            raise ValueError('时间段已过期或参数不合法，请重新同步时间')
        checked.append((start, end, mode, eid))
    credited = 0
    conn.execute('BEGIN IMMEDIATE')
    # Only recent reports are accepted, so old deduplication events can expire.
    conn.execute('DELETE FROM usage_time_events WHERE end_ms<?', (now_ms-180000,))
    for start, end, mode, eid in sorted(checked):
        if conn.execute('SELECT 1 FROM usage_time_events WHERE user_id=? AND event_id=?', (uid,eid)).fetchone():
            continue
        overlaps = conn.execute('SELECT start_ms,end_ms FROM usage_time_events WHERE user_id=? AND end_ms>? AND start_ms<? ORDER BY start_ms', (uid,start,end)).fetchall()
        cursor = start
        uncovered = []
        for row in overlaps:
            if row['start_ms'] > cursor:
                uncovered.append((cursor,min(end,row['start_ms'])))
            cursor = max(cursor,row['end_ms'])
        if cursor < end:
            uncovered.append((cursor,end))
        conn.execute('INSERT INTO usage_time_events VALUES(?,?,?,?,?)', (uid,eid,start,end,mode))
        for left,right in uncovered:
            while left < right:
                day = datetime.fromtimestamp(left/1000,TZ)
                midnight = (day + timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
                stop = min(right,int(midnight.timestamp()*1000))
                work, reading = (stop-left,0) if mode == 'work' else (0,stop-left)
                conn.execute('''INSERT INTO usage_time_daily VALUES(?,?,?,?,?)
                    ON CONFLICT(user_id,date) DO UPDATE SET
                    work_ms=work_ms+excluded.work_ms,reading_ms=reading_ms+excluded.reading_ms,
                    last_active=MAX(last_active,excluded.last_active)''', (uid,day.date().isoformat(),work,reading,stop))
                credited += stop-left
                left = stop
    return credited


def date_range(query):
    today = datetime.now(TZ).date()
    try:
        start = datetime.strptime(query.get('start',[today.isoformat()])[0], '%Y-%m-%d').date()
        end = datetime.strptime(query.get('end',[today.isoformat()])[0], '%Y-%m-%d').date()
        if end < start or (end-start).days > 365 or end > today:
            raise ValueError()
    except (ValueError,TypeError):
        raise ValueError('请选择不超过 366 天且不晚于今天的日期范围')
    return start.isoformat(),end.isoformat()


def daily_rows(conn, uid, start, end):
    return [dict(r) for r in conn.execute('SELECT date,work_ms,reading_ms,last_active FROM usage_time_daily WHERE user_id=? AND date BETWEEN ? AND ? ORDER BY date DESC',(uid,start,end))]


def totals(rows):
    work = sum(r['work_ms'] for r in rows)
    reading = sum(r['reading_ms'] for r in rows)
    return {'work_ms':work,'reading_ms':reading,'total_ms':work+reading}
