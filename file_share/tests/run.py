"""Run isolated HTTP integration tests. Uses mock OSS, never real credentials."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

root = Path(__file__).resolve().parent
with tempfile.TemporaryDirectory(prefix='file-share-test-') as data:
    environment = {**os.environ, 'AI_PLATFORM_DATA':data, 'PYTHONDONTWRITEBYTECODE':'1'}
    with tempfile.TemporaryFile(mode='w+') as logs:
        server = subprocess.Popen([sys.executable,str(root/'server.py')],env=environment,stdout=logs,stderr=logs)
        try:
            opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for attempt in range(50):
                if server.poll() is not None:
                    logs.seek(0)
                    raise RuntimeError(logs.read())
                try:
                    with opener.open('http://127.0.0.1:18765/api/health',timeout=1):
                        break
                except OSError:
                    time.sleep(.1)
            subprocess.run([sys.executable,str(root/'smoke.py')],env=environment,check=True)
            subprocess.run([sys.executable,str(root/'unit.py')],env=environment,check=True)
        finally:
            server.terminate()
            server.wait(timeout=10)
