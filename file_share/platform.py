"""Cloud-only operational aggregates. Never expose credentials or object URLs."""
import time
from datetime import datetime, timedelta, timezone

TZ = timezone(timedelta(hours=8))


def platform_report(conn, days, page, search='', user_id=''):
    now = int(time.time())
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    start = int((today-timedelta(days=days-1)).timestamp())
    where, args = ('user_id=?', [user_id]) if user_id else ('1=1', [])
    totals = dict(conn.execute(f"""SELECT
        sum(status='READY') file_count,
        coalesce(sum(CASE WHEN status IN ('READY','TRASHED','PURGING') THEN size ELSE 0 END),0) storage_bytes,
        coalesce(sum(CASE WHEN status IN ('TRASHED','PURGING') THEN size ELSE 0 END),0) trash_bytes,
        sum(status='UPLOADING') pending_uploads
        FROM share_files WHERE {where}""", args).fetchone())
    totals = {k:v or 0 for k,v in totals.items()}
    totals['user_count'] = conn.execute("SELECT count(*) FROM users u LEFT JOIN share_members m ON m.user_id=u.id WHERE u.is_active=1 AND (u.role='admin' OR m.enabled=1)").fetchone()[0]
    totals['active_shares'] = conn.execute(f"""SELECT count(*) FROM shares WHERE {where} AND status='ACTIVE'
        AND (expires_at IS NULL OR expires_at>?) AND (max_views IS NULL OR view_count<max_views)
        AND (max_downloads IS NULL OR download_count<max_downloads)""", (*args,now)).fetchone()[0]
    owner = ' AND s.user_id=?' if user_id else ''
    daily = {(today-timedelta(days=n)).strftime('%Y-%m-%d'):{'day':(today-timedelta(days=n)).strftime('%Y-%m-%d'),'upload_bytes':0,'uploads':0,'downloads':0,'download_bytes':0,'previews':0,'views':0,'failures':0} for n in range(days)}
    for r in conn.execute(f"""SELECT date(a.created_at,'unixepoch','+8 hours') day,count(*) uploads,sum(f.size) upload_bytes
        FROM share_audit_logs a JOIN share_files f ON f.id=a.target_id
        WHERE a.action='COMPLETE_UPLOAD' AND a.created_at>=? AND a.created_at<=? {'AND a.user_id=?' if user_id else ''} GROUP BY day""", (start,now,*args)):
        if r['day'] in daily:daily[r['day']].update(dict(r))
    for r in conn.execute(f"""SELECT date(l.created_at,'unixepoch','+8 hours') day,
        sum(l.action='DOWNLOAD_FILE' AND l.success=1) downloads,
        coalesce(sum(CASE WHEN l.action='DOWNLOAD_FILE' AND l.success=1 THEN f.size ELSE 0 END),0) download_bytes,
        sum(l.action='PREVIEW_FILE' AND l.success=1) previews,
        sum(l.action='VIEW_SHARE' AND l.success=1) views,sum(l.success=0) failures
        FROM share_access_logs l JOIN shares s ON s.id=l.share_id LEFT JOIN share_files f ON f.id=l.file_id
        WHERE l.created_at>=? AND l.created_at<=? {owner} GROUP BY day""", (start,now,*args)):
        if r['day'] in daily:daily[r['day']].update(dict(r))
    period = {key:sum(d[key] for d in daily.values()) for key in ('uploads','upload_bytes','downloads','download_bytes','previews','views','failures')}
    conditions = 'WHERE (u.username LIKE ? OR u.display_name LIKE ?)'
    pattern = '%'+search+'%'
    total = conn.execute('SELECT count(*) FROM users u '+conditions,(pattern,pattern)).fetchone()[0]
    users = []
    for row in conn.execute('''SELECT u.id,u.username,u.display_name,u.role,u.is_active,
        coalesce(m.enabled,0) cloud_enabled,m.last_login_at,m.last_visit_at FROM users u
        LEFT JOIN share_members m ON m.user_id=u.id '''+conditions+' ORDER BY u.created_at,u.id LIMIT 20 OFFSET ?', (pattern,pattern,(page-1)*20)):
        u = dict(row)
        u['cloud_enabled'] = bool(u['cloud_enabled'] or u['role']=='admin')
        u.update(dict(conn.execute("""SELECT count(*) file_count,coalesce(sum(size),0) storage_bytes FROM share_files
            WHERE user_id=? AND status IN ('READY','TRASHED','PURGING')""",(u['id'],)).fetchone()))
        u['share_count'] = conn.execute('SELECT count(*) FROM shares WHERE user_id=?',(u['id'],)).fetchone()[0]
        u['upload_bytes'] = conn.execute("SELECT coalesce(sum(f.size),0) FROM share_audit_logs a JOIN share_files f ON f.id=a.target_id WHERE a.action='COMPLETE_UPLOAD' AND a.user_id=? AND a.created_at>=? AND a.created_at<=?",(u['id'],start,now)).fetchone()[0]
        u.update(dict(conn.execute("""SELECT count(*) downloads,coalesce(sum(f.size),0) download_bytes
            FROM share_access_logs l JOIN shares s ON s.id=l.share_id JOIN share_files f ON f.id=l.file_id
            WHERE s.user_id=? AND l.action='DOWNLOAD_FILE' AND l.success=1 AND l.created_at>=? AND l.created_at<=?""",(u['id'],start,now)).fetchone()))
        users.append(u)
    return dict(totals=totals,period=period,today=daily[today.strftime('%Y-%m-%d')],daily=list(daily.values()),users=users,total=total,page=page,days=days,timezone='Asia/Shanghai')
