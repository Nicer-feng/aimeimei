"""原生搜索、来源和档案的真实 HTTP 与临时数据库验收，不访问模型服务。"""
import json
import unittest
import urllib.error
import urllib.parse
import urllib.request

import test_reading as fixtures
from ai_platform.database import db


class NativeKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ReadingTests.setUpClass()
        cls.fixture = fixtures.ReadingTests
        with db() as conn:
            conn.execute("""INSERT INTO models(id,name,provider,base_url,api_key,model,created_at,updated_at)
                VALUES ('knowledge-model','测试模型','mock','https://mock.invalid','test-only','test',0,0)""")

    @classmethod
    def tearDownClass(cls):
        cls.fixture.tearDownClass()

    def request(self, path, method='GET', body=None, user='reader-a'):
        headers = {'Authorization': 'Bearer ' + user} if user else {}
        raw = None
        if body is not None:
            raw = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.fixture.url + path, data=raw, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as error:
            return error.code, json.load(error)

    def conversation(self, cid, archived=0):
        with db() as conn:
            conn.execute("""INSERT INTO conversations(id,user_id,title,model_id,archived,reasoning_mode,created_at,updated_at)
                VALUES (?,'reader-a','预算讨论','knowledge-model',?,'deep',1,2)""", (cid, archived))
            cursor = conn.execute("INSERT INTO messages(user_id,conversation_id,role,content,created_at) VALUES ('reader-a',?,'assistant','预算原文回答',1)", (cid,))
            return cursor.lastrowid

    def test_detail_reads_old_conversation_without_mutating_timestamp_or_permissions(self):
        self.conversation('old-detail')
        code, body = self.request('/api/conversations/old-detail')
        self.assertEqual(code, 200)
        row = body['conversation']
        self.assertEqual((row['id'], row['model_id'], row['reasoning_mode'], row['updated_at']), ('old-detail', 'knowledge-model', 'deep', 2))
        self.assertNotIn('api_key', row)
        self.assertEqual(self.request('/api/conversations/old-detail', user='reader-b')[0], 404)
        self.assertEqual(self.request('/api/conversations/old-detail', user=None)[0], 401)
        self.conversation('archived-detail', 1)
        self.assertEqual(self.request('/api/conversations/archived-detail')[0], 404)
        self.assertEqual(self.request('/api/conversations/missing-detail')[0], 404)
        with db() as conn:
            self.assertEqual(conn.execute("SELECT updated_at FROM conversations WHERE id='old-detail'").fetchone()[0], 2)

    def test_search_returns_message_location_and_cannot_find_other_accounts_content(self):
        message = self.conversation('old-search')
        path = '/api/search?' + urllib.parse.urlencode({'q': '预算原文'})
        code, body = self.request(path)
        self.assertEqual(code, 200)
        match = next(row for row in body['results'] if row['type'] == 'message')
        self.assertEqual((match['session_id'], match['message_id']), ('old-search', message))
        self.assertEqual(self.request(path, user='reader-b')[1]['results'], [])

    def test_sources_are_saved_per_message_and_private(self):
        message = self.conversation('source-history')
        with db() as conn:
            conn.execute("INSERT INTO message_sources(message_id,title,url,snippet,position,created_at) VALUES (?,'官方资料','https://example.com/source','来源摘要',1,0)", (message,))
        code, body = self.request('/api/conversations/source-history/messages')
        self.assertEqual(code, 200)
        self.assertEqual(body['messages'][0]['sources'][0]['snippet'], '来源摘要')
        self.assertEqual(self.request('/api/conversations/source-history/messages', user='reader-b')[0], 404)

    def test_profiles_crud_enable_and_reorder_are_private(self):
        payload = {'title': '表达偏好', 'content': '请用中文简洁回答', 'type': 'style', 'enabled': True, 'sort_order': 10}
        code, body = self.request('/api/profiles', 'POST', payload)
        self.assertEqual(code, 201); pid = body['profile']['id']
        second = self.request('/api/profiles', 'POST', {**payload, 'title': '项目背景'})[1]['profile']['id']
        self.assertEqual(self.request('/api/profiles', user='reader-b')[1]['profiles'], [])
        self.assertEqual(self.request('/api/profiles/' + pid, 'PUT', {'enabled': False}, user='reader-b')[0], 404)
        self.assertEqual(self.request('/api/profiles/' + pid, 'PUT', {'enabled': False})[1]['profile']['enabled'], False)
        code, body = self.request('/api/profiles/reorder', 'POST', {'ids': [second, pid]})
        self.assertEqual(code, 200); self.assertEqual([row['id'] for row in body['profiles']], [second, pid])
        self.assertEqual(self.request('/api/profiles/' + pid, 'DELETE', {}, user='reader-b')[0], 404)
        self.assertEqual(self.request('/api/profiles/' + pid, 'DELETE', {})[0], 200)
        self.assertEqual(self.request('/api/profiles/' + second, 'DELETE', {})[0], 200)


if __name__ == '__main__':
    unittest.main()
