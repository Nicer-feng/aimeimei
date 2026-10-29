import threading
from test_reading import ReadingTests
from ai_platform.database import db
from ai_platform.runtime import now, token_hash
from ai_platform.login_history import record_login

ReadingTests.setUpClass()
with db() as conn:
    conn.execute("UPDATE users SET role='admin' WHERE id='reader-a'")
    for i in range(58):
        uid='reader-b' if i%2 else 'reader-a'; session='history-local-'+str(i)
        ts=now()-i*60
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token_hash(session),uid,ts,now()+3600))
        meta={'installation_id':'history-installation-'+str(i%4),'platform':'ios','manufacturer':'Apple','model':'iPhone99,9',
              'os_version':'18.0','app_version':'0.8.3','app_build':'1.16.1','notification_authorization':'authorized'}
        if i in (1,2,3): meta['installation_id']='history-special-installation-'+str(i)
        if i==1: meta.update(platform='android',manufacturer='OPPO',model='internal-model',os_version='15',app_version='0.6.8',app_build='16')
        ua=''
        if i in (2,3):
            meta.update(platform='web')
            ua='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36' if i==2 else 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1'
        record_login(conn,uid,token_hash(session),ts,now()+3600,meta,ua,'198.51.100.7','trusted_forwarded')
print('FIXTURE_URL='+ReadingTests.url,flush=True)
try: threading.Event().wait()
except KeyboardInterrupt: pass
finally: ReadingTests.tearDownClass()
