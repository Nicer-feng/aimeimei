import hashlib
import sqlite3
import threading
import time
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from ..database import db
from ..runtime import b64_token, now
from ..reading import (MAX_BYTES, MAX_BOOKS, MAX_USER_BYTES, decode_book, split_pages,
                       public_book, delete_book_object, put_book_object)
from infrastructure.storage import shared_storage_config

_uploads = threading.BoundedSemaphore(2)


class ReadingHandlersMixin:
    def handle_reading(self):
        user_id = self.current_user()['id']
        parsed = urlparse(self.path)
        parts = parsed.path.rstrip('/').split('/')[3:]
        query = parse_qs(parsed.query)
        if parts == ['books']:
            if self.command == 'GET':
                with db() as conn:
                    rows = conn.execute('SELECT * FROM reading_books WHERE user_id=? ORDER BY created_at DESC', (user_id,)).fetchall()
                return self.json({'books': [public_book(row) for row in rows]})
            if self.command == 'POST':
                if not _uploads.acquire(blocking=False):
                    return self.error(HTTPStatus.TOO_MANY_REQUESTS, '正在处理上传，请稍后重试')
                try:
                    return self.upload_reading_book(user_id, query)
                finally:
                    _uploads.release()
        if len(parts) not in (2, 3) or parts[0] != 'books':
            return self.error(HTTPStatus.NOT_FOUND, 'not found')
        book_id = parts[1]
        action = parts[2] if len(parts) == 3 else ''
        with db() as conn:
            row = conn.execute('SELECT * FROM reading_books WHERE id=? AND user_id=?', (book_id, user_id)).fetchone()
            if not row:
                return self.error(HTTPStatus.NOT_FOUND, '小说不存在')
            if self.command == 'GET' and action == 'pages':
                try:
                    if 'offset' in query:
                        offset = max(0, min(int(query['offset'][0]), row['total_chars'] - 1))
                        center = conn.execute('SELECT page FROM reading_pages WHERE book_id=? AND start_offset<=? ORDER BY start_offset DESC LIMIT 1', (book_id, offset)).fetchone()['page']
                    else:
                        center = max(0, min(int(query.get('page', ['0'])[0]), row['page_count'] - 1))
                    radius = max(0, min(int(query.get('radius', ['2'])[0]), 3))
                except (ValueError, TypeError):
                    return self.error(HTTPStatus.BAD_REQUEST, '页码不合法')
                pages = conn.execute('SELECT page,start_offset,content FROM reading_pages WHERE book_id=? AND page BETWEEN ? AND ? ORDER BY page', (book_id, max(0, center-radius), center+radius)).fetchall()
                return self.json({'book': public_book(row), 'page': center, 'pages': [dict(p) for p in pages]})
        if self.command == 'POST' and action in ('active', 'progress'):
            try:
                data = self.read_body(limit=4096)
                if not isinstance(data, dict):
                    raise ValueError()
                position = max(0, min(int(data.get('position', row['position'])), row['total_chars']))
                mode = data.get('mode', row['mode'])
                if mode not in ('scroll', 'page'):
                    raise ValueError()
                stamp = min(int(data.get('saved_at', time.time()*1000)), int(time.time()*1000)+60000)
            except (ValueError, TypeError):
                return self.error(HTTPStatus.BAD_REQUEST, '阅读进度参数不合法')
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                if not conn.execute('SELECT id FROM reading_books WHERE id=? AND user_id=?', (book_id, user_id)).fetchone():
                    return self.error(HTTPStatus.NOT_FOUND, '小说不存在')
                if action == 'active':
                    conn.execute('UPDATE reading_books SET active=0 WHERE user_id=?', (user_id,))
                    conn.execute('UPDATE reading_books SET active=1 WHERE id=? AND user_id=?', (book_id, user_id))
                else:
                    conn.execute('UPDATE reading_books SET position=?,mode=?,progress_at=? WHERE id=? AND user_id=? AND progress_at<=?', (position, mode, stamp, book_id, user_id, stamp))
            return self.json({'ok': True})
        if self.command == 'DELETE' and not action:
            config = shared_storage_config(self.server.secrets)
            try:
                delete_book_object(config, row['oss_key'])
            except Exception:
                return self.error(HTTPStatus.BAD_GATEWAY, 'OSS 文件删除失败，请稍后重试；阅读记录已保留')
            with db() as conn:
                conn.execute('DELETE FROM reading_books WHERE id=? AND user_id=?', (book_id, user_id))
            return self.json({'ok': True})
        return self.error(HTTPStatus.NOT_FOUND, 'not found')

    def upload_reading_book(self, user_id, query):
        filename = Path(query.get('filename', [''])[0]).name[:180]
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            length = 0
        if not filename.lower().endswith('.txt') or not 0 < length <= MAX_BYTES:
            return self.error(HTTPStatus.BAD_REQUEST, '请选择 20MB 以内的 TXT 文件')
        with db() as conn:
            usage = conn.execute('SELECT COUNT(*) AS count,COALESCE(SUM(file_size),0) AS size FROM reading_books WHERE user_id=?', (user_id,)).fetchone()
        if usage['count'] >= MAX_BOOKS or usage['size'] + length > MAX_USER_BYTES:
            return self.error(HTTPStatus.BAD_REQUEST, '书架最多 30 本、合计 100MB，请先删除不再阅读的小说')
        config = shared_storage_config(self.server.secrets)
        if not config['configured']:
            return self.error(HTTPStatus.BAD_REQUEST, '小说存储暂未配置，请联系管理员检查 OSS')
        old_timeout = self.connection.gettimeout()
        try:
            self.connection.settimeout(45)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ValueError('文件上传不完整，请重试')
            text, encoding = decode_book(raw)
        except (ValueError, TimeoutError) as exc:
            return self.error(HTTPStatus.BAD_REQUEST, str(exc))
        finally:
            self.connection.settimeout(old_timeout)
        digest = hashlib.sha256(raw).hexdigest()
        with db() as conn:
            duplicate = conn.execute('SELECT * FROM reading_books WHERE user_id=? AND content_hash=?', (user_id, digest)).fetchone()
        if duplicate:
            return self.json({'book': public_book(duplicate), 'duplicate': True})
        book_id = b64_token(18)
        key = f"{config['directory']}/reading/{user_id}/{book_id}.txt"
        pages = list(split_pages(text))
        try:
            put_book_object(config, key, raw)
        except Exception:
            return self.error(HTTPStatus.BAD_GATEWAY, '小说上传 OSS 失败，请稍后重试')
        try:
            with db() as conn:
                conn.execute('BEGIN IMMEDIATE')
                usage = conn.execute('SELECT COUNT(*) AS count,COALESCE(SUM(file_size),0) AS size FROM reading_books WHERE user_id=?', (user_id,)).fetchone()
                if usage['count'] >= MAX_BOOKS or usage['size'] + length > MAX_USER_BYTES:
                    raise ValueError('书架容量已满，请删除不再阅读的小说')
                active = not conn.execute('SELECT id FROM reading_books WHERE user_id=? AND active=1', (user_id,)).fetchone()
                conn.execute('''INSERT INTO reading_books(id,user_id,title,oss_key,file_size,content_hash,encoding,total_chars,page_count,active,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (book_id,user_id,filename[:-4],key,length,digest,encoding,len(text),len(pages),int(active),now()))
                conn.executemany('INSERT INTO reading_pages(book_id,page,start_offset,content) VALUES (?,?,?,?)', [(book_id,i,start,content) for i,(start,content) in enumerate(pages)])
                row = conn.execute('SELECT * FROM reading_books WHERE id=?', (book_id,)).fetchone()
        except (ValueError, sqlite3.Error):
            try:
                delete_book_object(config, key)
            except Exception:
                pass
            return self.error(HTTPStatus.CONFLICT, '保存失败或重复上传，请刷新书架后重试')
        return self.json({'book': public_book(row)}, HTTPStatus.CREATED)
