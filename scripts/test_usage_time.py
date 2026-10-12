"""Local HTTP and aggregation tests; no production data or upstream calls."""
import json
import time
import unittest
import urllib.request
import urllib.error
from datetime import datetime
from test_reading import ReadingTests
from ai_platform.database import db
from ai_platform.runtime import now, token_hash
from ai_platform.usage_time import record_segments, TZ


class UsageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ReadingTests.setUpClass()
        cls.url=ReadingTests.url
        with db() as conn:
            conn.execute("INSERT INTO users(id,username,display_name,password_hash,role,created_at,updated_at) VALUES ('usage-admin','usage-admin','admin','x','admin',?,?)",(now(),now()))
            conn.execute('INSERT INTO sessions(token_hash,user_id,created_at,expires_at) VALUES(?,?,?,?)',(token_hash('usage-admin'),'usage-admin',now(),now()+3600))

    @classmethod
    def tearDownClass(cls):
        ReadingTests.tearDownClass()

    def setUp(self):
        with db() as conn:
            conn.execute('DELETE FROM usage_time_events');conn.execute('DELETE FROM usage_time_daily')

    def req(self,path,user='reader-a',body=None):
        headers={'Authorization':'Bearer '+user} if user else {}
        if body is not None:headers['Content-Type']='application/json'
        request=urllib.request.Request(self.url+'/api/usage-time/'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urllib.request.urlopen(request) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)

    def event(self,start,end,mode='work',eid='event-001'):
        return dict(start_ms=start,end_ms=end,mode=mode,id=eid)

    def test_union_retries_and_mode(self):
        t=int(time.time()*1000)
        events=[self.event(t-30000,t-10000),self.event(t-20000,t,'reading','event-002')]
        body={'account_id':'reader-a','segments':events}
        self.assertEqual(self.req('heartbeat',body=body)[1]['credited_ms'],30000)
        self.assertEqual(self.req('heartbeat',body=body)[1]['credited_ms'],0)
        summary=self.req('self')[1]['summary']
        self.assertEqual(summary,dict(work_ms=20000,reading_ms=10000,total_ms=30000))
        # A late interval preceding the previous one still gets its uncovered part.
        self.req('heartbeat',body={'account_id':'reader-a','segments':[self.event(t-35000,t-25000,eid='event-003')]})
        self.assertEqual(self.req('self')[1]['summary']['total_ms'],35000)

    def test_auth_and_bad_reports(self):
        self.assertEqual(self.req('self',user='')[0],401)
        self.assertEqual(self.req('admin')[0],403)
        self.assertEqual(self.req('admin/user?user_id=reader-b')[0],403)
        t=int(time.time()*1000)
        for start,end in [(t-36000,t),(t-200000,t-190000),(t,t+9000)]:
            self.assertEqual(self.req('heartbeat',body={'account_id':'reader-a','segments':[self.event(start,end)]})[0],400)
        self.assertEqual(self.req('heartbeat',body={'account_id':'reader-b','segments':[self.event(t-1000,t)]})[0],409)
        self.assertEqual(self.req('self?start=2020-01-01&end=2026-01-01')[0],400)

    def test_own_data_admin_summary_and_details(self):
        t=int(time.time()*1000)
        self.req('heartbeat',body={'account_id':'reader-a','segments':[self.event(t-10000,t)]})
        self.assertEqual(self.req('self?user_id=reader-a',user='reader-b')[1]['summary']['total_ms'],0)
        data=self.req('admin',user='usage-admin')[1]
        self.assertEqual(data['summary']['active_users'],1)
        self.assertEqual(data['users'][0]['id'],'reader-a')
        self.assertNotIn('days',data['users'][0])
        self.assertEqual(len(self.req('admin/user?user_id=reader-a',user='usage-admin')[1]['days']),1)
        self.assertEqual(self.req('admin?q=not-found',user='usage-admin')[1]['users'],[])

    def test_midnight_and_transaction_rollback(self):
        midnight=int(datetime(2026,10,12,tzinfo=TZ).timestamp()*1000)
        with db() as conn:
            record_segments(conn,'reader-a',[self.event(midnight-5000,midnight+5000)],midnight+6000)
        with db() as conn:
            rows=conn.execute('SELECT * FROM usage_time_daily ORDER BY date').fetchall()
            self.assertEqual([(r['date'],r['work_ms']) for r in rows],[('2026-10-11',5000),('2026-10-12',5000)])

    def test_random_overlap_and_concurrent_retry(self):
        import random
        from concurrent.futures import ThreadPoolExecutor
        t=int(time.time()*1000)
        rng=random.Random(27);covered=set()
        for i in range(80):
            start=rng.randrange(0,80);length=rng.randrange(1,30)
            covered.update(range(start,start+length))
            with db() as conn:
                record_segments(conn,'reader-a',[self.event(t-110000+start*1000,t-110000+(start+length)*1000,eid=f'random-{i:04}')],t)
        with db() as conn:
            total=conn.execute('SELECT SUM(work_ms+reading_ms) FROM usage_time_daily WHERE user_id=?',('reader-a',)).fetchone()[0]
        self.assertEqual(total,len(covered)*1000)
        def submit(_):
            with db() as conn:
                return record_segments(conn,'reader-b',[self.event(t-1000,t,eid='concurrent-001')],t)
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(submit,range(4))),1000)


if __name__ == '__main__':
    import sys
    if '--serve' in sys.argv:
        UsageTests.setUpClass()
        print('FIXTURE_URL='+UsageTests.url,flush=True)
        try: __import__('threading').Event().wait()
        except KeyboardInterrupt: pass
        finally: UsageTests.tearDownClass()
    else:unittest.main()
