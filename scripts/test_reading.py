"""Isolated HTTP regression. OSS is mocked; --serve starts a browser fixture on loopback."""
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ai_platform.database as database
from ai_platform.reading import decode_book, split_pages, put_book_object
from ai_platform.runtime import now, token_hash
from app import AIPlatformServer, AppHandler


class ReadingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='aimeimei-reading-')
        cls.patches = [patch.object(database, 'DATA_DIR', Path(cls.temp.name)),
            patch.object(database, 'DB_PATH', Path(cls.temp.name) / 'test.db')]
        cls.objects = {}
        def put(config, key, raw):
            cls.objects[key] = raw
        cls.patches += [patch('ai_platform.handlers.reading.shared_storage_config', return_value={'configured': True, 'directory': 'test'}),
            patch('ai_platform.handlers.reading.put_book_object', side_effect=put),
            patch('ai_platform.handlers.reading.delete_book_object', side_effect=lambda config, key: cls.objects.pop(key, None))]
        for item in cls.patches: item.start()
        database.init_db({})
        database.init_db({})
        with database.db() as conn:
            for uid in ('reader-a', 'reader-b'):
                conn.execute("INSERT INTO users(id,username,display_name,password_hash,role,created_at,updated_at) VALUES (?,?,?,'x','family',?,?)", (uid,uid,uid,now(),now()))
                conn.execute('INSERT INTO sessions VALUES (?,?,?,?)', (token_hash(uid),uid,now(),now()+3600))
        cls.server = AIPlatformServer(('127.0.0.1', 0), AppHandler, {'admin_key': 'test-only'})
        cls.url = 'http://127.0.0.1:' + str(cls.server.server_port)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()
        for item in reversed(cls.patches): item.stop()
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, method='GET', body=None, user='reader-a'):
        headers = {'Authorization': 'Bearer ' + user} if user else {}
        if isinstance(body, dict):
            body = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
        elif body is not None: headers['Content-Type'] = 'application/octet-stream'
        req = urllib.request.Request(cls.url + '/api/reading/' + path, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=20) as response: return response.status, json.load(response)
        except urllib.error.HTTPError as error: return error.code, json.load(error)

    def test_private_roundtrip_and_bounds(self):
        text = '第一章 <script>alert(1)</script>\n正文内容与表情😀。\n' * 2000
        code, data = self.request('books?filename=long.txt', 'POST', text.encode())
        self.assertEqual(code, 201)
        book = data['book']; bid = book['id']
        self.assertNotIn('oss_key', book)
        self.assertEqual(self.request('books', user=None)[0], 401)
        self.assertEqual(self.request(f'books/{bid}/pages', user='reader-b')[0], 404)
        self.assertEqual(self.request(f'books/{bid}/progress', 'POST', {'position': 10}, user='reader-b')[0], 404)
        self.assertEqual(self.request(f'books/{bid}', 'DELETE', user='reader-b')[0], 404)
        _, window = self.request(f'books/{bid}/pages?offset=30000&radius=999')
        self.assertLessEqual(len(window['pages']), 7)
        self.assertTrue(all(len(p['content']) <= 2000 for p in window['pages']))
        self.assertLessEqual(window['pages'][3]['start_offset'], 30000)
        stamp = int(time.time()*1000)
        self.request(f'books/{bid}/progress', 'POST', {'position': 34567, 'mode': 'page', 'saved_at': stamp})
        self.request(f'books/{bid}/progress', 'POST', {'position': 1, 'saved_at': stamp-1})
        stored = next(b for b in self.request('books')[1]['books'] if b['id'] == bid)
        self.assertEqual(stored['position'], 34567)
        self.assertEqual(stored['mode'], 'page')
        self.assertEqual(self.request(f'books/{bid}/progress', 'POST', {'mode': 'invalid'})[0], 400)
        self.assertTrue(self.request('books?filename=again.txt', 'POST', text.encode())[1]['duplicate'])
        self.assertEqual(self.request(f'books/{bid}', 'DELETE')[0], 200)
        self.assertEqual(self.request(f'books/{bid}/pages')[0], 404)
        with database.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM reading_pages WHERE book_id=?', (bid,)).fetchone()[0], 0)

    def test_encoding_and_active_book(self):
        for encoding in ('utf-8-sig', 'gb18030', 'utf-16'):
            text, _ = decode_book('中文测试\r\n第二段'.encode(encoding))
            self.assertEqual(text, '中文测试\n第二段')
        with self.assertRaises(ValueError): decode_book(b'\0binary')
        self.assertEqual(self.request('books?filename=bad.pdf', 'POST', b'hello')[0], 400)
        text = ('甲😀乙\n' * 3000)
        self.assertEqual(''.join(content for _, content in split_pages(text)), text)
        a = self.request('books?filename=a.txt', 'POST', '甲书'.encode())[1]['book']
        b = self.request('books?filename=b.txt', 'POST', '乙书'.encode())[1]['book']
        self.request(f"books/{b['id']}/active", 'POST', {})
        self.assertEqual([r['id'] for r in self.request('books')[1]['books'] if r['active']], [b['id']])
        for book in (a,b): self.request(f"books/{book['id']}", 'DELETE')

    def test_public_storage_is_rejected_and_cleaned(self):
        with patch('ai_platform.reading.PrivateOSS') as factory:
            oss = factory.return_value
            oss.verify_private.side_effect = RuntimeError('public object')
            with self.assertRaises(RuntimeError):
                put_book_object({}, 'share/reading/test.txt', b'test')
            self.assertEqual(oss.request.call_args.kwargs['headers']['x-oss-object-acl'], 'private')
            oss.verify_private.assert_called_once_with('share/reading/test.txt')
            oss.delete.assert_called_once_with('share/reading/test.txt')


if __name__ == '__main__':
    if '--serve' in sys.argv:
        ReadingTests.setUpClass()
        print('FIXTURE_URL=' + ReadingTests.url, flush=True)
        try: threading.Event().wait()
        except KeyboardInterrupt: pass
        finally: ReadingTests.tearDownClass()
    else:
        unittest.main()
