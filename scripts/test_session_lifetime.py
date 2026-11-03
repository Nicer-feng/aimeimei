"""临时数据库及回环 HTTP 的登录期限回归，不读取真实会话或调用短信/APNs。"""
import json
import unittest
import urllib.error
import urllib.request
from http.cookies import SimpleCookie
from unittest.mock import patch

from test_reading import ReadingTests
from ai_platform.database import db
from ai_platform.handlers.auth import captcha_answer_hash
from ai_platform.runtime import b64_token, now, password_hash, token_hash


class SessionLifetimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ReadingTests.setUpClass()
        with db() as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id='reader-b'", (password_hash('test-only-password'),))

    @classmethod
    def tearDownClass(cls):
        ReadingTests.tearDownClass()

    def req(self, path, body=None, token=None, agent='Mozilla/5.0'):
        headers = {'User-Agent': agent}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(ReadingTests.url + path,
            data=json.dumps(body).encode() if body is not None else None, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.load(response), response.headers.get('Set-Cookie', '')
        except urllib.error.HTTPError as error:
            return error.code, json.load(error), ''

    def login(self, client=None, agent='Mozilla/5.0'):
        captcha = b64_token(12)
        with db() as conn:
            conn.execute('INSERT INTO login_captchas VALUES(?,?,?,?,0)',
                (captcha, captcha_answer_hash(captcha, 'AB23'), now(), now()+300))
        return self.req('/api/login', {'username': 'reader-b', 'password': 'test-only-password',
            'captcha_id': captcha, 'captcha': 'AB23', 'client': client}, agent=agent)

    def assert_lifetime(self, result, days):
        code, data, header = result
        self.assertEqual(code, 200)
        cookie = SimpleCookie(header)['ap_session']
        token = cookie.value
        seconds = days * 86400
        self.assertEqual(int(cookie['max-age']), seconds)
        self.assertTrue(cookie['httponly'])
        self.assertEqual(cookie['samesite'], 'Lax')
        with db() as conn:
            session = conn.execute('SELECT created_at,expires_at FROM sessions WHERE token_hash=?',
                (token_hash(token),)).fetchone()
            history = conn.execute('SELECT created_at,expires_at FROM auth_session_history WHERE token_hash=?',
                (token_hash(token),)).fetchone()
        self.assertEqual(session['expires_at']-session['created_at'], seconds)
        self.assertEqual(data['expires_at'], session['expires_at'])
        self.assertEqual(tuple(history), tuple(session))
        return token

    def test_native_password_sessions_use_90_days(self):
        for platform in ('ios', 'android'):
            with self.subTest(platform=platform):
                self.assert_lifetime(self.login({'platform': platform}), 90)

    def test_web_mobile_web_and_legacy_clients_stay_14_days(self):
        for client, agent in (({'platform': 'web'}, 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0) Mobile'),
                              ({'platform': 'web'}, 'Mozilla/5.0 (Linux; Android 15) Mobile'),
                              (None, 'Meimei/16 CFNetwork/1568 Darwin/24'),
                              (None, 'okhttp/4.12.0'), (None, 'Mozilla/5.0'),
                              ({}, ''), ([], ''), ({'platform': ['ios']}, ''),
                              ({'platform': 'unknown'}, ''), ({'platform': 'IOS'}, '')):
            with self.subTest(client=client, agent=agent):
                self.assert_lifetime(self.login(client, agent), 14)

    def test_new_login_keeps_other_devices_and_does_not_extend_existing_sessions(self):
        old = self.assert_lifetime(self.login(), 14)
        with db() as conn:
            expiry = conn.execute('SELECT expires_at FROM sessions WHERE token_hash=?', (token_hash(old),)).fetchone()[0]
        iphone = self.assert_lifetime(self.login({'platform': 'ios'}), 90)
        android = self.assert_lifetime(self.login({'platform': 'android'}), 90)
        for token in (old, iphone, android):
            self.assertTrue(self.req('/api/me', token=token)[1]['authenticated'])
        self.assertEqual(self.req('/api/session/device-info',
            {'installation_id': 'test-current-session-1234', 'platform': 'ios'}, token=old)[0], 200)
        with db() as conn:
            self.assertEqual(conn.execute('SELECT expires_at FROM sessions WHERE token_hash=?',
                (token_hash(old),)).fetchone()[0], expiry)
        self.assertEqual(self.req('/api/logout', {}, token=iphone)[0], 200)
        self.assertFalse(self.req('/api/me', token=iphone)[1]['authenticated'])
        self.assertTrue(self.req('/api/me', token=android)[1]['authenticated'])
        self.assertTrue(self.req('/api/me', token=old)[1]['authenticated'])

    def test_sms_login_uses_the_same_platform_policy(self):
        phone = '13800000000'
        with db() as conn:
            conn.execute("UPDATE users SET phone=?,phone_verified_at=? WHERE id='reader-b'", (phone, now()))
        for platform, days in (('ios', 90), ('android', 90), ('web', 14)):
            challenge = b64_token(12)
            with db() as conn:
                conn.execute('INSERT INTO sms_login_challenges(id,phone_hash,out_id,created_at,expires_at) VALUES(?,?,?,?,?)',
                    (challenge, token_hash(phone), 'test-out-id', now(), now()+300))
            with patch('ai_platform.handlers.auth.sms_auth_config', return_value={}), \
                 patch('ai_platform.handlers.auth.sms_auth_configured', return_value=True), \
                 patch('ai_platform.handlers.auth.check_verify_code', return_value=True) as provider:
                result = self.req('/api/sms-login/verify', {'phone': phone, 'code': '123456',
                    'challenge_id': challenge, 'client': {'platform': platform}})
            with self.subTest(platform=platform):
                provider.assert_called_once()
                self.assert_lifetime(result, days)


if __name__ == '__main__':
    unittest.main(defaultTest='SessionLifetimeTests')
