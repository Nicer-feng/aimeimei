"""Cached, bounded background IP2Location lookups; never block access logging."""
import ipaddress
import json
import os
import queue
import threading
import time
from contextlib import closing
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from ai_platform.database import db
from ai_platform.settings import DATA_DIR

_jobs = queue.Queue(maxsize=64)
_pending = set()
_lock = threading.Lock()
_started = False
_blocked_until = 0


def api_key(secrets_data):
    key = os.environ.get('IP2LOCATION_API_KEY') or secrets_data.get('ip2location_api_key')
    if key:
        return str(key).strip()
    try:
        return (DATA_DIR / 'ip2location.key').read_text().strip()
    except OSError:
        return ''


def public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        return str(ip) if ip.is_global else None
    except ValueError:
        return None


def lookup(ip, key):
    request = Request('https://api.ip2location.io/?ip=' + ip,
                      headers={'Authorization': 'Bearer ' + key,
                               'Accept': 'application/json',
                               'User-Agent': 'FengShare/1.0'})
    with urlopen(request, timeout=4) as response:
        raw = response.read(16385)
    if len(raw) > 16384:
        raise ValueError('Oversized response')
    data = json.loads(raw)
    if not isinstance(data, dict) or data.get('error') or public_ip(data.get('ip', '')) != ip:
        raise ValueError('Invalid lookup response')
    return {field: str(data.get(source) or '')[:120]
            for field, source in [('country', 'country_name'), ('province', 'region_name'), ('city', 'city_name')]}


def _resolve(ip, key):
    global _blocked_until
    now = int(time.time())
    if now < _blocked_until:
        return
    status, ttl, result = 'ready', 7 * 86400, {}
    try:
        result = lookup(ip, key)
        if not any(result.values()):
            status, ttl = 'unavailable', 3600
    except HTTPError as exc:
        status, ttl = 'unavailable', 3600
        if exc.code in (401, 403, 429):
            with _lock:
                _blocked_until = time.time() + 3600
    except Exception:
        # Do not log exception text: URLs/headers can contain credentials.
        status, ttl = 'unavailable', 3600
        with _lock:
            _blocked_until = time.time() + 30
    with closing(db()) as conn, conn:
        conn.execute('DELETE FROM infrastructure_ip_locations WHERE expires_at<=?', (now,))
        conn.execute('INSERT OR REPLACE INTO infrastructure_ip_locations(ip,country,province,city,status,expires_at) VALUES(?,?,?,?,?,?)',
                     (ip, result.get('country', ''), result.get('province', ''), result.get('city', ''), status, now + ttl))
        conn.execute('DELETE FROM infrastructure_ip_locations WHERE ip IN (SELECT ip FROM infrastructure_ip_locations ORDER BY expires_at DESC LIMIT -1 OFFSET 10000)')


def _worker():
    while True:
        ip, key = _jobs.get()
        try:
            _resolve(ip, key)
        except Exception:
            pass
        finally:
            with _lock:
                _pending.discard(ip)
            _jobs.task_done()


def schedule(ip, key):
    global _started
    with _lock:
        if time.time() < _blocked_until:
            return False
        if ip in _pending:
            return True
        if not _started:
            for index in range(2):
                threading.Thread(target=_worker, name='ip-location-' + str(index), daemon=True).start()
            _started = True
        try:
            _pending.add(ip)
            _jobs.put_nowait((ip, key))
            return True
        except queue.Full:
            _pending.discard(ip)
            return False


def enrich_logs(conn, rows, secrets_data):
    key = api_key(secrets_data)
    now = int(time.time())
    cache = {}
    for row in rows:
        ip = public_ip(row['ip'])
        if not ip:
            row['geolocation_status'] = 'private'
            continue
        if ip not in cache:
            cached = conn.execute('SELECT * FROM infrastructure_ip_locations WHERE ip=? AND expires_at>?', (ip, now)).fetchone()
            cache[ip] = dict(cached) if cached else None
        cached = cache[ip]
        if cached:
            row.update({field: cached[field] for field in ('country', 'province', 'city')})
            row['geolocation_status'] = cached['status']
        elif key:
            row['geolocation_status'] = 'pending' if schedule(ip, key) else 'unavailable'
        else:
            row['geolocation_status'] = 'unconfigured'
    return rows
