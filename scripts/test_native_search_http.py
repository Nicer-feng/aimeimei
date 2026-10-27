#!/usr/bin/env python3
"""Verify native search compatibility over loopback HTTP, never a paid service."""
import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import test_chat_stream as transport
from ai_platform.database import db, init_db


class NativeSearchHTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({"family_password_hash": "test-only"})

    @classmethod
    def tearDownClass(cls):
        transport.TEMP.cleanup()

    def run_case(self, model, scenario):
        requests = []

        class Upstream(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                requests.append((self.path, payload))
                tools = [tool['type'] for tool in payload['tools']]
                if scenario == 'http_rejection' and 'web_extractor' in tools:
                    body = json.dumps(transport.extractor_failure()['response']['error']).encode()
                    self.send_response(400)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
                self.end_headers()
                if scenario == 'partial':
                    events = [
                        {'type': 'response.output_text.delta', 'delta': '保留已收到的部分'},
                        transport.extractor_failure(),
                    ]
                elif scenario == 'retry_failed' and len(requests) > 1:
                    events = [{'type': 'error', 'code': 'InvalidApiKey', 'message': 'private sk-test-credential'}]
                elif 'web_extractor' in tools:
                    events = [transport.extractor_failure()]
                else:
                    events = [
                        {'type': 'response.web_search_call.in_progress'},
                        {'type': 'response.output_item.done', 'item': {
                            'type': 'web_search_call', 'action': {'sources': [
                                {'title': '测试来源', 'url': 'https://example.com', 'snippet': '测试摘要'},
                            ]},
                        }},
                        {'type': 'response.reasoning_text.delta', 'delta': '正在核对来源'},
                        {'type': 'response.output_text.delta', 'delta': '正常联网回答'},
                        {'type': 'response.completed', 'response': {
                            'status': 'completed', 'usage': {'input_tokens': 5, 'output_tokens': 2, 'total_tokens': 7},
                        }},
                    ]
                for event in events:
                    raw = transport.event_bytes(event)
                    for offset in range(0, len(raw), 7):
                        self.wfile.write(raw[offset:offset + 7])
                        self.wfile.flush()

        server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        cid = self.id().split('.')[-1]
        endpoint = 'http://127.0.0.1:' + str(server.server_port) + '/compatible-mode/v1'
        try:
            with db() as conn:
                conn.execute('''INSERT INTO models
                    (id,name,provider,base_url,api_key,model,supports_native_web_search,created_at,updated_at)
                    VALUES (?,?,'mock',?,'fake-only',?,1,0,0)''', (cid, 'test', endpoint, model))
                conn.execute("INSERT INTO conversations(id,user_id,title,model_id,created_at,updated_at) VALUES (?,'default','test',?,0,0)", (cid, cid))
            handler = transport.Handler(cid)
            handler.server.secrets = {'web_search': {'enabled': True, 'mode': 'manual'}}
            original_read_body = handler.read_body
            handler.read_body = lambda **kwargs: {**original_read_body(**kwargs), 'web_search': True}
            with transport.patch('ai_platform.handlers.chat.enrich_search_result_snippets', side_effect=lambda results, *args: results):
                handler.handle_send_message()
            self.assertEqual(handler.status, 200)
            with db() as conn:
                rows = conn.execute("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'", (cid,)).fetchall()
                sources = conn.execute('SELECT * FROM message_sources WHERE message_id=?', (rows[0]['id'],)).fetchall() if rows else []
            self.assertEqual(len(rows), 1)
            self.assertTrue(all(path == '/compatible-mode/v1/responses' for path, _ in requests))
            return dict(rows[0]), handler.wfile.getvalue().decode(), [body for _, body in requests], sources
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

    def assert_success(self, row, stream, sources):
        self.assertEqual((row['content'], row['reasoning_content'], row['generation_status'], row['total_tokens']),
                         ('正常联网回答', '正在核对来源', 'completed', 7))
        self.assertEqual(len(sources), 1)
        self.assertEqual(stream.count('"type": "message_saved"'), 1)
        self.assertNotIn('message.failed', stream)

    def test_omni_uses_only_web_search(self):
        row, stream, requests, sources = self.run_case('qwen3.8-omni-flash', 'normal')
        self.assert_success(row, stream, sources)
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]['tools'], [{'type': 'web_search'}])

    def test_http_200_stream_error_falls_back_once(self):
        row, stream, requests, sources = self.run_case('qwen3.8-max', 'normal')
        self.assert_success(row, stream, sources)
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1]['tools'], [{'type': 'web_search'}])

    def test_existing_http_400_fallback_still_works(self):
        row, stream, requests, sources = self.run_case('qwen3.8-max', 'http_rejection')
        self.assert_success(row, stream, sources)
        self.assertEqual(len(requests), 2)

    def test_failed_retry_stops_and_redacts_error(self):
        row, stream, requests, _ = self.run_case('qwen3.8-max', 'retry_failed')
        self.assertEqual((row['generation_status'], row['total_tokens']), ('failed', 0))
        self.assertEqual(len(requests), 2)
        self.assertIn('授权失败', stream)
        self.assertNotIn('sk-test-credential', stream)

    def test_partial_answer_is_not_replayed(self):
        row, _, requests, _ = self.run_case('qwen3.8-max', 'partial')
        self.assertEqual((row['content'], row['generation_status']), ('保留已收到的部分', 'failed'))
        self.assertEqual(len(requests), 1)


if __name__ == '__main__':
    unittest.main(verbosity=2)
