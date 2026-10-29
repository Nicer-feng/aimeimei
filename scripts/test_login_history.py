"""临时数据库和回环 HTTP 的全客户端登录记录回归，不读真实会话或发送通知。"""
import json
import sqlite3
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from test_reading import ReadingTests
from ai_platform.database import db
from ai_platform.runtime import now, b64_token, token_hash, password_hash
from ai_platform.handlers.auth import captcha_answer_hash
from ai_platform.login_history import resolve_client_ip, cleanup_history, RETENTION_SECONDS

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
CLIENT = {'installation_id':'test-installation-1000','platform':'ios','manufacturer':'Apple','model':'iPhone99,9',
          'os_version':'18.0','app_version':'0.8.3','app_build':'1.16.1','notification_authorization':'authorized'}


class ClientIPTests(unittest.TestCase):
    def test_untrusted_forwarded_header_is_ignored(self):
        self.assertEqual(resolve_client_ip('198.51.100.2','203.0.113.1','127.0.0.1/32'), ('198.51.100.2','direct'))
        self.assertEqual(resolve_client_ip('2001:db8::7','203.0.113.1',''), ('2001:db8::7','direct'))

    def test_trusted_chain_ipv4_ipv6_and_malformed_input(self):
        trusted = '127.0.0.1/32,::1/128,10.0.0.0/24'
        self.assertEqual(resolve_client_ip('127.0.0.1','198.51.100.8, 10.0.0.2',trusted)[0], '198.51.100.8')
        self.assertEqual(resolve_client_ip('::1','2001:db8::99',trusted)[0], '2001:db8::99')
        for forwarded in (None,'','bad','198.51.100.1, bad',','*30):
            self.assertIsNone(resolve_client_ip('127.0.0.1',forwarded,trusted)[0])


class LoginHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ReadingTests.setUpClass()
        cls.env = patch.dict('os.environ', {'AI_PLATFORM_TRUSTED_PROXIES':'127.0.0.1/32,::1/128'})
        cls.env.start()
        with db() as conn:
            conn.execute("UPDATE users SET password_hash=? WHERE id IN ('reader-a','reader-b')", (password_hash('test-only-password'),))
            conn.execute("UPDATE users SET role='admin' WHERE id='reader-a'")

    @classmethod
    def tearDownClass(cls):
        cls.env.stop(); ReadingTests.tearDownClass()

    def setUp(self):
        with db() as conn:
            conn.execute('DELETE FROM auth_login_events'); conn.execute('DELETE FROM auth_session_history'); conn.execute('DELETE FROM auth_devices')
            conn.execute('UPDATE auth_history_maintenance SET cleaned_at=0')
            conn.execute("UPDATE users SET is_active=1 WHERE id IN ('reader-a','reader-b')")
            for uid in ('reader-a','reader-b'):
                conn.execute('INSERT OR REPLACE INTO sessions VALUES(?,?,?,?)', (token_hash(uid),uid,now()-1000,now()+3600))

    def req(self, path, body=None, user='reader-a', ip='198.51.100.7', method=None, ua=UA):
        headers = {'User-Agent':ua}
        if user: headers['Authorization']='Bearer '+user
        if ip is not None: headers['X-Forwarded-For']=ip
        if body is not None: headers['Content-Type']='application/json'
        request=urllib.request.Request(ReadingTests.url+path, data=json.dumps(body).encode() if body is not None else None, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request,timeout=10) as response:
                cookie=response.headers.get('Set-Cookie','')
                return response.status,json.load(response),cookie
        except urllib.error.HTTPError as error:
            return error.code,json.load(error),''

    def login(self, client=CLIENT, username='reader-b', password='test-only-password', ip='198.51.100.7', ua=UA):
        captcha=b64_token(12)
        with db() as conn:
            conn.execute('INSERT INTO login_captchas VALUES(?,?,?,?,0)', (captcha,captcha_answer_hash(captcha,'AB23'),now(),now()+300))
        code,data,cookie=self.req('/api/login',{'username':username,'password':password,'captcha_id':captcha,'captcha':'AB23','client':client},user=None,ip=ip,ua=ua)
        token=cookie.split(';')[0].partition('=')[2] if cookie else ''
        return code,data,token

    def events(self, query=''):
        code,data,_=self.req('/api/admin/login-records'+query)
        self.assertEqual(code,200)
        return data

    def devices(self, uid='reader-b', query=''):
        code,data,_=self.req('/api/admin/users/'+uid+'/devices'+query)
        self.assertEqual(code,200)
        return data

    def test_success_only_and_old_login_compatibility(self):
        self.assertEqual(self.login(password='wrong')[0],401)
        self.assertEqual(self.events()['records'],[])
        code,data,token=self.login(client=None)
        self.assertEqual(code,200); self.assertTrue(token)
        row=self.events()['records'][0]
        self.assertEqual(row['source_ip'],'198.51.100.7')
        self.assertEqual(row['client']['browser'],'Chrome')
        self.assertEqual(row['client']['browser_version'],'131.0.0.0')
        self.assertEqual(row['client']['os_name'],'Windows')
        self.assertEqual(row['client']['model'],'')
        self.assertEqual(self.login(client=['bad'])[0],200)
        self.assertEqual(len(self.events()['records']),2)

    def test_only_admin_can_read_and_no_credentials_are_returned(self):
        _,_,token=self.login()
        for path in ('/api/admin/login-records','/api/admin/users/reader-b/devices'):
            self.assertEqual(self.req(path,user=token)[0],401)
            self.assertEqual(self.req(path,user=None)[0],401)
        self.assertEqual(self.req('/api/session/device-info',CLIENT,user=None)[0],401)
        self.assertEqual(self.req('/api/me',user=token)[1]['user'].get('devices'),None)
        forbidden={'token','token_hash','session_hash','session_id','password','password_hash','installation_id','push_token'}
        def check(value):
            if isinstance(value,dict):
                self.assertFalse(set(value)&forbidden)
                for item in value.values(): check(item)
            elif isinstance(value,list):
                for item in value: check(item)
        check(self.events()); check(self.devices())

    def test_repeated_login_same_installation_and_account_switch(self):
        self.login(); self.login(); self.login(username='reader-a')
        self.assertEqual(len(self.events()['records']),3)
        self.assertEqual(len(self.devices()['devices']),1)
        self.assertEqual(len(self.devices('reader-a')['devices']),1)
        self.assertEqual(self.devices()['devices'][0]['sessions']['valid'],2)

    def test_out_of_order_device_observations_do_not_reverse_login_times(self):
        from ai_platform.login_history import record_login
        ts=now()
        with db() as conn:
            record_login(conn,'reader-b',token_hash('newer-observation'),ts-100,ts+3600,CLIENT,UA,'198.51.100.7','direct')
            record_login(conn,'reader-b',token_hash('older-observation'),ts-200,ts+3600,CLIENT,UA,'198.51.100.7','direct')
        item=self.devices()['devices'][0]
        self.assertEqual(item['first_login_at'],ts-200)
        self.assertEqual(item['last_login_at'],ts-100)
        self.assertEqual(item['last_active_at'],ts-100)

    def test_logout_and_expiry_survive_session_cleanup(self):
        _,_,token=self.login()
        self.req('/api/logout',{},user=token)
        self.assertEqual(self.events()['records'][0]['session_state'],'logged_out')
        _,_,token=self.login()
        with db() as conn:
            conn.execute('UPDATE auth_session_history SET expires_at=? WHERE token_hash=?', (now()-1,token_hash(token)))
            conn.execute('DELETE FROM sessions WHERE token_hash=?', (token_hash(token),))
        states={r['session_state'] for r in self.events()['records']}
        self.assertEqual(states,{'logged_out','expired'})

    def test_legacy_session_supplement_is_not_a_login_or_past_model(self):
        self.assertEqual(self.req('/api/session/device-info',CLIENT,user='reader-b')[0],200)
        self.assertEqual(self.events()['records'],[])
        device=self.devices()['devices'][0]
        self.assertEqual(device['first_login_at'],0)
        self.assertEqual(device['last_login_at'],0)
        self.assertGreaterEqual(device['first_reported_at'],now()-5)
        self.assertEqual(device['client']['model'],'iPhone99,9')
        self.req('/api/session/device-info',CLIENT,user='reader-b')
        self.assertEqual(len(self.devices()['devices']),1)
        self.assertEqual(self.events()['records'],[])

    def test_historical_ip_and_metadata_are_immutable_activity_is_throttled(self):
        _,_,token=self.login(ip='2001:db8::44')
        original=self.events()['records'][0]
        changed={**CLIENT,'model':'iPhone99,10'}
        self.req('/api/session/device-info',changed,user=token,ip='198.51.100.9')
        after=self.events()['records'][0]
        self.assertEqual(original,after)
        self.assertEqual(self.devices()['devices'][0]['last_active_ip'],'198.51.100.9')
        with db() as conn:
            before=conn.execute('SELECT last_active_at,last_active_ip FROM auth_session_history WHERE token_hash=?',(token_hash(token),)).fetchone()
        self.req('/api/me',user=token,ip='198.51.100.10')
        with db() as conn:
            untouched=conn.execute('SELECT last_active_at,last_active_ip FROM auth_session_history WHERE token_hash=?',(token_hash(token),)).fetchone()
            self.assertEqual(tuple(before),tuple(untouched))
            conn.execute('UPDATE auth_session_history SET last_active_at=? WHERE token_hash=?',(now()-61,token_hash(token)))
        self.req('/api/me',user=token,ip='198.51.100.10')
        self.assertEqual(self.devices()['devices'][0]['last_active_ip'],'198.51.100.10')

    def test_auth_lookup_remains_read_only_inside_another_transaction(self):
        from app import AppHandler
        from email.message import Message
        handler=object.__new__(AppHandler)
        handler.headers=Message(); handler.headers['Authorization']='Bearer reader-a'
        with db() as conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute("UPDATE users SET updated_at=? WHERE id='reader-a'",(now(),))
            self.assertEqual(handler.current_user()['id'],'reader-a')

    def test_native_webview_does_not_replace_native_device(self):
        _,_,token=self.login()
        web={'installation_id':'browser-installation-1234','platform':'web'}
        self.req('/api/session/device-info',web,user=token)
        devices=self.devices()['devices']
        self.assertEqual(len(devices),1)
        self.assertEqual(devices[0]['client']['platform'],'ios')

    def test_notification_state_is_separate_and_android_is_not_integrated(self):
        android={**CLIENT,'platform':'android','manufacturer':'OPPO','model':'internal-model'}
        self.login(client=android)
        row=self.devices()['devices'][0]
        self.assertEqual(row['notification']['authorization'],'authorized')
        self.assertEqual(row['notification']['capability'],'not_integrated')
        self.assertEqual(row['notification']['registration'],'not_registered')
        self.assertFalse(row['notification']['binding_session_valid'])
        self.assertNotIn('received',json.dumps(row['notification']))

    def test_mobile_web_and_claimed_fields_do_not_become_hardware_identity(self):
        ua='Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
        self.login(client={'installation_id':'browser-installation-1000','platform':'web','model':'do not trust','source_ip':'203.0.113.77','token':'not stored'},ua=ua,ip=None)
        row=self.events()['records'][0]
        self.assertEqual(row['client']['platform'],'web_mobile')
        self.assertEqual(row['client']['model'],'')
        self.assertIsNone(row['source_ip'])
        self.assertEqual(row['ip_source'],'unavailable_forwarded')

    def test_sms_success_also_creates_one_event_without_sending_sms(self):
        phone='13800000000'; challenge='local-sms-challenge'
        with db() as conn:
            conn.execute("UPDATE users SET phone=?,phone_verified_at=? WHERE id='reader-b'",(phone,now()))
            conn.execute('INSERT INTO sms_login_challenges(id,phone_hash,out_id,created_at,expires_at) VALUES(?,?,?,?,?)',(challenge,token_hash(phone),'local-only',now(),now()+300))
        with patch('ai_platform.handlers.auth.sms_auth_config',return_value={}), patch('ai_platform.handlers.auth.sms_auth_configured',return_value=True), patch('ai_platform.handlers.auth.check_verify_code',return_value=True):
            code,_,_=self.req('/api/sms-login/verify', {'phone':phone,'code':'123456','challenge_id':challenge,'client':CLIENT},user=None)
        self.assertEqual(code,200)
        self.assertEqual(len(self.events()['records']),1)
        self.assertEqual(self.events()['records'][0]['client']['platform'],'ios')

    def test_deactivation_invalidates_session_without_erasing_history(self):
        _,_,token=self.login()
        self.assertEqual(self.req('/api/admin/users/reader-b',{'is_active':False},method='PUT')[0],200)
        self.assertEqual(self.events()['records'][0]['session_state'],'account_disabled')
        self.assertEqual(self.req('/api/session/device-info',CLIENT,user=token)[0],401)

    def test_beijing_day_filter_is_not_utc_day(self):
        self.login()
        tz=timezone(timedelta(hours=8)); day=datetime.now(tz).date()
        boundary=datetime.combine(day,datetime.min.time(),tz)+timedelta(minutes=30)
        with db() as conn: conn.execute('UPDATE auth_login_events SET logged_at=?',(int(boundary.timestamp()),))
        self.assertEqual(len(self.events('?from='+str(day)+'&to='+str(day))['records']),1)
        previous=day-timedelta(days=1)
        self.assertEqual(len(self.events('?from='+str(previous)+'&to='+str(previous))['records']),0)

    def test_history_cleanup_is_bounded_for_devices_and_sessions(self):
        for i in range(4): self.login(client={**CLIENT,'installation_id':'old-installation-'+str(1000+i)})
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE user_id='reader-b'")
            conn.execute("UPDATE auth_session_history SET last_active_at=? WHERE user_id='reader-b'", (now()-RETENTION_SECONDS-1,))
            conn.execute("UPDATE auth_devices SET last_active_at=? WHERE user_id='reader-b'", (now()-RETENTION_SECONDS-1,))
            counts=cleanup_history(conn,limit=2)
            self.assertEqual(counts['sessions'],2)
            self.assertEqual(counts['devices'],2)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM auth_session_history WHERE user_id='reader-b'").fetchone()[0],2)

    def test_pagination_filters_and_validation(self):
        for i in range(4): self.login(client={**CLIENT,'installation_id':'test-installation-'+str(1000+i)})
        first=self.events('?limit=2&user_id=reader-b&platform=ios')
        self.assertEqual(len(first['records']),2)
        second=self.events('?limit=2&before='+str(first['next_before']))
        self.assertFalse({r['id'] for r in first['records']}&{r['id'] for r in second['records']})
        self.assertEqual(len(self.events('?platform=android')['records']),0)
        d=self.devices(query='?limit=2'); self.assertEqual(len(d['devices']),2)
        self.assertEqual(len(self.devices(query='?limit=2&before='+str(d['next_before']))['devices']),2)
        for query in ('?limit=0','?limit=101','?before=-1','?platform=not-real','?from=2026-99-99','?from=2026-10-30&to=2026-10-29'):
            self.assertEqual(self.req('/api/admin/login-records'+query)[0],400)

    def test_retention_is_bounded_and_does_not_delete_business_logs(self):
        for i in range(4): self.login(client={**CLIENT,'installation_id':'test-installation-'+str(1000+i)})
        with db() as conn:
            conn.execute('UPDATE auth_login_events SET logged_at=?',(now()-RETENTION_SECONDS-1,))
            before=conn.execute('SELECT COUNT(*) FROM login_captchas').fetchone()[0]
            result=cleanup_history(conn,limit=2)
            self.assertEqual(result['events'],2)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM auth_login_events').fetchone()[0],2)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM login_captchas').fetchone()[0],before)
            self.assertEqual(cleanup_history(conn,limit=2),{})
        self.assertEqual(self.events()['records'],[])

    def test_full_backup_redacts_ip_and_sanitized_backup_removes_history(self):
        self.login()
        from ai_platform.backup import create_database_snapshot
        for mode in ('full','sanitized'):
            target=Path(ReadingTests.temp.name)/(mode+'-history.sqlite')
            create_database_snapshot(Path(ReadingTests.temp.name)/'test.db',target,mode)
            with sqlite3.connect(target) as conn:
                count=conn.execute('SELECT COUNT(*) FROM auth_login_events').fetchone()[0]
                self.assertEqual(count,1 if mode=='full' else 0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM auth_login_events WHERE source_ip IS NOT NULL').fetchone()[0],0)
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM auth_session_history WHERE last_active_ip IS NOT NULL').fetchone()[0],0)
            self.assertNotIn(b'198.51.100.7', target.read_bytes())


if __name__=='__main__':
    unittest.main()
