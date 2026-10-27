#!/usr/bin/env python3
"""Chat stream failure regression: temporary SQLite and fake transport only."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEMP = tempfile.TemporaryDirectory(prefix="aimeimei-stream-test-")
os.environ["AI_PLATFORM_DATA"] = TEMP.name
from app import AppHandler
from ai_platform.database import db, init_db
from ai_platform.handlers.chat import sse_payloads


def event_bytes(event):
    return ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode()


def delta(text, finish=None, **fields):
    return {"choices": [{"delta": {"content": text}, "finish_reason": finish}], **fields}


def extractor_failure(**fields):
    return {
        "type": "response.failed",
        "response": {
            "status": "failed",
            "error": {"code": "InvalidParameter", "message": "<400> The current model does not support the web_extractor tool."},
            **fields,
        },
    }


class Response:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.closed = False
        self.read_count = 0

    def read(self, size):
        self.read_count += 1
        item = next(self.chunks, b"")
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        self.closed = True


class Sink(io.BytesIO):
    def __init__(self, fail=False):
        super().__init__()
        self.fail = fail

    def write(self, data):
        if self.fail and b'"choices"' in data:
            raise BrokenPipeError("simulated browser cancellation")
        return super().write(data)


class Handler(AppHandler):
    def __init__(self, cid, fail=False):
        self.path = "/api/conversations/" + cid + "/messages"
        self.server = SimpleNamespace(secrets={})
        self.wfile = Sink(fail)
        self.status = None
        self.result = None

    def current_user(self):
        return {"id": "default", "role": "admin"}

    def read_body(self, **kwargs):
        return {"content": "请回答一个问题"}

    def send_response(self, status):
        self.status = status

    def send_header(self, *args):
        pass

    def end_headers(self):
        pass

    def log_message(self, *args):
        pass

    def json(self, data, status=200):
        self.result, self.status = data, status


class ChatStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        init_db({"family_password_hash": "test-only"})
        init_db({"family_password_hash": "test-only"})
        with db() as conn:
            conn.execute("INSERT INTO models(id,name,provider,base_url,api_key,model,created_at,updated_at) VALUES ('mock','test','mock','https://mock.invalid','fake','mock',0,0)")

    @classmethod
    def tearDownClass(cls):
        TEMP.cleanup()

    def run_stream(self, chunks, fail=False, native=False, model="mock", retry=None):
        cid = self.id().split('.')[-1]
        with db() as conn:
            conn.execute("UPDATE models SET supports_native_web_search=?,model=? WHERE id='mock'", (int(native), model))
            conn.execute("INSERT INTO conversations(id,user_id,title,model_id,created_at,updated_at) VALUES (?,'default','test','mock',0,0)", (cid,))
        handler, response = Handler(cid, fail), Response(chunks)
        responses = [response]
        if retry is not None:
            responses.append(retry if isinstance(retry, Exception) else Response(retry))
        with patch("ai_platform.handlers.chat.urllib.request.urlopen", side_effect=responses) as upstream, patch("ai_platform.handlers.chat.should_use_web_search", return_value=native), patch("ai_platform.handlers.chat.enrich_search_result_snippets", side_effect=lambda results, *args: results):
            handler.handle_send_message()
        response.requests = [json.loads(call.args[0].data) for call in upstream.call_args_list]
        for item in responses:
            if isinstance(item, Response):
                self.assertTrue(item.closed)
        self.assertEqual(handler.status, 200)
        self.assertTrue(response.closed)
        with db() as conn:
            rows = conn.execute("SELECT * FROM messages WHERE conversation_id=? AND role='assistant'", (cid,)).fetchall()
        self.assertEqual(len(rows), 1)
        history = Handler(cid)
        history.handle_messages()
        self.assertEqual(history.result['messages'][-1]['generation_status'], rows[0]['generation_status'])
        return dict(rows[0]), handler.wfile.getvalue().decode(), response

    def test_complete_utf8_and_usage(self):
        raw = event_bytes(delta("回答🚗", "stop", usage={"prompt_tokens": 4, "completion_tokens": 3, "total_tokens": 7})) + b'data: [DONE]\n\n'
        row, stream, _ = self.run_stream([raw[n:n + 1] for n in range(len(raw))])
        self.assertEqual((row['content'], row['generation_status'], row['total_tokens']), ('回答🚗', 'completed', 7))
        self.assertIn('message_saved', stream)
        self.assertNotIn('message.failed', stream)

    def test_browser_disconnect_saves_received_text_and_closes_upstream(self):
        row, _, response = self.run_stream([event_bytes(delta('已经收到的部分')), event_bytes(delta('不应继续读取', 'stop'))], fail=True)
        self.assertEqual((row['content'], row['generation_status']), ('已经收到的部分', 'interrupted'))
        self.assertEqual(response.read_count, 1)

    def test_upstream_read_error_saves_partial_reply(self):
        row, stream, _ = self.run_stream([event_bytes(delta('部分回复')), TimeoutError('mock timeout')])
        self.assertEqual((row['content'], row['generation_status']), ('部分回复', 'failed'))
        self.assertIn('message.failed', stream)
        self.assertNotIn('mock timeout', stream)

    def test_premature_eof_is_interrupted(self):
        row, stream, _ = self.run_stream([event_bytes(delta('尚未结束'))])
        self.assertEqual(row['generation_status'], 'interrupted')
        self.assertIn('message.failed', stream)

    def test_error_before_text_leaves_visible_failure_marker(self):
        row, stream, _ = self.run_stream([event_bytes({'error': {'message': 'private upstream details'}})])
        self.assertEqual((row['content'], row['generation_status']), ('', 'failed'))
        self.assertIn('message.failed', stream)
        self.assertNotIn('private upstream details', stream)

    def test_reasoning_only_disconnect_is_saved(self):
        chunk = event_bytes({'choices': [{'delta': {'reasoning_content': '思考片段'}}]})
        row, _, _ = self.run_stream([chunk], fail=True)
        self.assertEqual((row['reasoning_content'], row['generation_status']), ('思考片段', 'interrupted'))

    def test_native_failure_preserves_text(self):
        row, stream, _ = self.run_stream([
            event_bytes({'type': 'response.output_text.delta', 'delta': '原生回复'}),
            event_bytes({'type': 'response.failed', 'response': {'status': 'failed'}})
        ], native=True)
        self.assertEqual((row['content'], row['generation_status']), ('原生回复', 'failed'))
        self.assertIn('message.failed', stream)

    def test_native_client_disconnect_stops_reading(self):
        row, _, response = self.run_stream([
            event_bytes({'type': 'response.output_text.delta', 'delta': '原生片段'}),
            event_bytes({'type': 'response.completed', 'response': {'status': 'completed'}})
        ], native=True, fail=True)
        self.assertEqual(row['generation_status'], 'interrupted')
        self.assertEqual(response.read_count, 1)

    def test_native_completion(self):
        row, stream, _ = self.run_stream([
            event_bytes({'type': 'response.output_text.delta', 'delta': '原生完整回复'}),
            event_bytes({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 5, 'output_tokens': 2, 'total_tokens': 7}}}),
            TimeoutError('must not read after response.completed')
        ], native=True)
        self.assertEqual((row['generation_status'], row['total_tokens']), ('completed', 7))
        self.assertNotIn('message.failed', stream)

    def test_omni_only_requests_supported_search_tool(self):
        row, _, response = self.run_stream([
            event_bytes({'type': 'response.output_text.delta', 'delta': 'Omni 联网回复'}),
            event_bytes({'type': 'response.completed', 'response': {'status': 'completed'}}),
        ], native=True, model='qwen3.8-omni-flash')
        self.assertEqual(row['generation_status'], 'completed')
        self.assertEqual(response.requests[0]['tools'], [{'type': 'web_search'}])
        self.assertNotIn('web_extractor', json.dumps(response.requests[0]['input']))

    def test_other_models_keep_existing_search_tools(self):
        _, _, response = self.run_stream([
            event_bytes({'type': 'response.output_text.delta', 'delta': '正常回复'}),
            event_bytes({'type': 'response.completed', 'response': {'status': 'completed'}}),
        ], native=True, model='qwen3.8-max')
        self.assertEqual(response.requests[0]['tools'], [{'type': 'web_search'}, {'type': 'web_extractor'}])
        self.assertIn('web_extractor', json.dumps(response.requests[0]['input']))

    def test_stream_extractor_rejection_retries_once_and_saves_only_success(self):
        row, stream, response = self.run_stream([
            event_bytes({'type': 'response.created', 'response': {'status': 'in_progress'}}),
            event_bytes(extractor_failure()),
            TimeoutError('must close rejected response without reading again'),
        ], native=True, retry=[
            event_bytes({'type': 'response.output_text.delta', 'delta': '降级后正常联网'}),
            event_bytes({'type': 'response.completed', 'response': {'status': 'completed', 'usage': {'input_tokens': 5, 'output_tokens': 2, 'total_tokens': 7}}}),
        ])
        self.assertEqual((row['content'], row['generation_status'], row['total_tokens']), ('降级后正常联网', 'completed', 7))
        self.assertEqual(len(response.requests), 2)
        self.assertEqual(response.read_count, 2)
        self.assertEqual(response.requests[1]['tools'], [{'type': 'web_search'}])
        self.assertNotIn('web_extractor', json.dumps(response.requests[1]['input']))
        self.assertEqual(stream.count('"type": "message_saved"'), 1)
        self.assertNotIn('message.failed', stream)

    def test_repeated_stream_rejection_does_not_retry_again(self):
        row, stream, response = self.run_stream([event_bytes(extractor_failure())], native=True,
                                                retry=[event_bytes(extractor_failure())])
        self.assertEqual((row['generation_status'], row['total_tokens']), ('failed', 0))
        self.assertEqual(len(response.requests), 2)
        self.assertIn('当前模型不支持网页正文抽取', stream)
        self.assertNotIn('InvalidParameter', stream)

    def test_extractor_rejection_after_answer_does_not_replay(self):
        row, _, response = self.run_stream([
            event_bytes({'type': 'response.output_text.delta', 'delta': '保留已收到的正文'}),
            event_bytes(extractor_failure()),
        ], native=True)
        self.assertEqual((row['content'], row['generation_status']), ('保留已收到的正文', 'failed'))
        self.assertEqual(len(response.requests), 1)

    def test_extractor_rejection_after_reasoning_does_not_replay(self):
        row, _, response = self.run_stream([
            event_bytes({'type': 'response.reasoning_text.delta', 'delta': '保留已有思考'}),
            event_bytes(extractor_failure()),
        ], native=True)
        self.assertEqual((row['reasoning_content'], row['generation_status']), ('保留已有思考', 'failed'))
        self.assertEqual(len(response.requests), 1)

    def test_extractor_rejection_after_tool_started_does_not_replay(self):
        row, _, response = self.run_stream([
            event_bytes({'type': 'response.output_item.added', 'item': {'type': 'web_search_call'}}),
            event_bytes(extractor_failure()),
        ], native=True)
        self.assertEqual(row['generation_status'], 'failed')
        self.assertEqual(len(response.requests), 1)

    def test_extractor_rejection_with_usage_does_not_replay(self):
        row, _, response = self.run_stream([
            event_bytes(extractor_failure(usage={'input_tokens': 5, 'output_tokens': 2, 'total_tokens': 7})),
        ], native=True)
        self.assertEqual((row['generation_status'], row['total_tokens']), ('failed', 7))
        self.assertEqual(len(response.requests), 1)

    def test_stream_error_event_is_safe_and_does_not_retry_arbitrary_errors(self):
        row, stream, response = self.run_stream([
            event_bytes({'type': 'error', 'code': 'RateLimit', 'message': 'rate_limit private credential sk-test-secret'}),
        ], native=True)
        self.assertEqual(row['generation_status'], 'failed')
        self.assertEqual(len(response.requests), 1)
        self.assertIn('请求过于频繁', stream)
        self.assertNotIn('private credential', stream)
        self.assertNotIn('sk-test-secret', stream)

    def test_stream_fallback_http_error_is_saved_and_sanitized(self):
        error = urllib.error.HTTPError('https://mock.invalid', 503, 'mock', {}, io.BytesIO(b'private credential'))
        row, stream, response = self.run_stream([event_bytes(extractor_failure())], native=True, retry=error)
        self.assertEqual((row['generation_status'], row['total_tokens']), ('failed', 0))
        self.assertEqual(len(response.requests), 2)
        self.assertIn('模型服务返回错误', stream)
        self.assertNotIn('private credential', stream)

    def test_sse_multiline_and_unterminated_final_record(self):
        raw = b'data: {"a":\r\ndata: 1}\r\n\r\ndata: [DONE]'
        self.assertEqual(list(sse_payloads(Response([raw[n:n+1] for n in range(len(raw))]))), ['{"a":\n1}', '[DONE]'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
