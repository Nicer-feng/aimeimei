"""Bounded private Office preview cache and isolated converter orchestration."""
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time
from ai_platform.settings import DATA_DIR

LOCK=threading.Lock()
MAX_BYTES=20*1024**2

class PreviewError(Exception):pass


def sandbox_command(work):
    cmd=['/usr/bin/bwrap','--unshare-all','--die-with-parent','--new-session','--cap-drop','ALL',
         '--ro-bind','/usr','/usr','--symlink','usr/lib','/lib','--symlink','usr/lib64','/lib64',
         '--symlink','usr/bin','/bin','--symlink','usr/sbin','/sbin','--proc','/proc','--dev','/dev',
         '--tmpfs','/tmp','--dir','/etc','--ro-bind','/etc/fonts','/etc/fonts',
         '--ro-bind','/etc/ld.so.cache','/etc/ld.so.cache',
         '--ro-bind','/opt/cloud-preview-venv','/runtime',
         '--ro-bind',str(Path(__file__).with_name('preview_worker.py')),'/worker.py',
         '--bind',str(work),'/work','--chdir','/work','--setenv','HOME','/tmp',
         '--setenv','LANG','C.UTF-8','--setenv','SAL_USE_VCLPLUGIN','svp',
         '/runtime/bin/python','-I','/worker.py']
    return cmd


def office_preview(row,oss):
    ext=Path(row['original_filename']).suffix.lower()
    if ext not in ('.doc','.docx','.xls','.xlsx','.csv'):raise PreviewError('暂不支持此文档格式')
    if row['size']>MAX_BYTES:raise PreviewError('Office 在线预览暂支持 20 MB 以内文件，请下载查看')
    if not LOCK.acquire(blocking=False):raise PreviewError('正在处理其他文档，请稍后重试')
    try:
        cache=DATA_DIR/'share-preview-cache';cache.mkdir(mode=0o700,exist_ok=True)
        key=hashlib.sha256(('v1:'+row['id']+':'+row['object_key']).encode()).hexdigest()
        suffix='.pdf' if ext in ('.doc','.docx') else '.json'
        target=cache/(key+suffix)
        # Keep only bounded, short-lived derivative files, never originals.
        entries=sorted((p for p in cache.iterdir() if p.is_file()),key=lambda p:p.stat().st_mtime,reverse=True)
        total=0
        for p in entries:
            total+=p.stat().st_size
            if time.time()-p.stat().st_mtime>86400 or total>100*1024**2:p.unlink(missing_ok=True)
        if not target.exists():
            with tempfile.TemporaryDirectory(prefix='cloud-preview-') as directory:
                work=Path(directory);source=work/('input'+ext)
                with oss.request('GET',row['object_key']) as response,source.open('wb') as dest:
                    count=0
                    while True:
                        part=response.read(65536)
                        if not part:break
                        count+=len(part)
                        if count>MAX_BYTES:raise PreviewError('文件超过预览大小限制')
                        dest.write(part)
                if count!=row['size']:raise PreviewError('文件大小校验失败，请重新上传')
                process=subprocess.Popen(sandbox_command(work)+['/work/'+source.name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True,env={'PATH':'/usr/bin:/bin','LANG':'C.UTF-8'})
                try:process.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGKILL);process.wait();raise PreviewError('文档转换超时，请下载查看')
                result=work/('result'+suffix)
                if process.returncode or not result.is_file() or result.stat().st_size>MAX_BYTES:
                    raise PreviewError('文档无法预览，可能已加密、损坏或过于复杂，请下载查看')
                data=result.read_bytes()
                if suffix=='.pdf' and not data.startswith(b'%PDF-'):raise PreviewError('PDF 转换失败')
                temporary=target.with_suffix(target.suffix+'.tmp')
                with temporary.open('wb') as f:os.chmod(temporary,0o600);f.write(data)
                os.replace(temporary,target)
        data=target.read_bytes()
        return {'kind':'pdf','data':base64.b64encode(data).decode()} if suffix=='.pdf' else json.loads(data)
    except (OSError,ValueError,subprocess.SubprocessError) as exc:
        raise PreviewError('文档预览暂不可用，请稍后重试或下载查看') from exc
    finally:LOCK.release()
