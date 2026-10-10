"""Private TXT books and bounded reading pages, independent of chat context."""
from infrastructure.storage import PrivateOSS

MAX_BYTES = 20 * 1024 * 1024
MAX_BOOKS = 30
MAX_USER_BYTES = 100 * 1024 * 1024
PAGE_CHARS = 2000


def init_reading_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS reading_books (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
          title TEXT NOT NULL, oss_key TEXT NOT NULL, file_size INTEGER NOT NULL,
          content_hash TEXT NOT NULL, encoding TEXT NOT NULL, total_chars INTEGER NOT NULL,
          page_count INTEGER NOT NULL, active INTEGER NOT NULL DEFAULT 0,
          position INTEGER NOT NULL DEFAULT 0, mode TEXT NOT NULL DEFAULT 'scroll',
          progress_at INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL,
          UNIQUE(user_id, content_hash)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS reading_one_active ON reading_books(user_id) WHERE active=1;
        CREATE INDEX IF NOT EXISTS reading_owner ON reading_books(user_id, created_at);
        CREATE TABLE IF NOT EXISTS reading_pages (
          book_id TEXT NOT NULL REFERENCES reading_books(id) ON DELETE CASCADE,
          page INTEGER NOT NULL, start_offset INTEGER NOT NULL, content TEXT NOT NULL,
          PRIMARY KEY(book_id, page)
        );
        CREATE INDEX IF NOT EXISTS reading_page_offset ON reading_pages(book_id, start_offset);
    """)


def decode_book(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('TXT 文件需在 20MB 以内且不能为空')
    encodings = ['utf-16'] if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError('无法识别文字编码，请将 TXT 另存为 UTF-8 后上传')
    if '\x00' in text or sum(ord(c) < 32 and c not in '\r\n\t' for c in text) > max(2, len(text) // 1000):
        raise ValueError('文件不是可阅读的纯文本 TXT')
    text = text.replace('\r\n', '\n').replace('\r', '\n').lstrip('\ufeff')
    if not text.strip():
        raise ValueError('TXT 没有正文内容')
    return text, encoding


def split_pages(text):
    offset = 0
    while offset < len(text):
        end = min(len(text), offset + PAGE_CHARS)
        if end < len(text):
            boundary = max(text.rfind(mark, offset + PAGE_CHARS // 2, end) for mark in ('\n', '。', '！', '？'))
            if boundary >= 0:
                end = boundary + 1
        yield offset, text[offset:end]
        offset = end


def delete_book_object(config, key):
    PrivateOSS(config).delete(key)


def put_book_object(config, key, raw):
    oss = PrivateOSS(config)
    try:
        with oss.request('PUT', key, headers={'Content-Type': 'text/plain',
                'x-oss-object-acl': 'private', 'Cache-Control': 'private, no-store'}, body=raw):
            pass
        # A bucket policy can override object ACLs; never register a public book.
        oss.verify_private(key)
    except Exception:
        try:
            oss.delete(key)
        except Exception:
            pass
        raise


def public_book(row):
    return {key: row[key] for key in ('id', 'title', 'file_size', 'encoding', 'total_chars',
        'page_count', 'active', 'position', 'mode', 'progress_at', 'created_at')}
