import threading
from test_reading import ReadingTests
from ai_platform.database import db

ReadingTests.setUpClass()
with db() as conn:
    conn.execute("UPDATE users SET role='admin' WHERE id='reader-a'")
print('FIXTURE_URL=' + ReadingTests.url, flush=True)
try:
    threading.Event().wait()
except KeyboardInterrupt:
    pass
finally:
    ReadingTests.tearDownClass()
