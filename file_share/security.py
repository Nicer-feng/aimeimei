import hashlib
import ipaddress
import os
import re


def hash_password(password):
    from argon2 import PasswordHasher
    return PasswordHasher().hash(password)


def verify_password(encoded, password):
    from argon2 import PasswordHasher
    from argon2.exceptions import VerificationError, InvalidHashError
    try:
        return PasswordHasher().verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def client_info(handler):
    ip = handler.client_address[0]
    # Only explicitly trusted proxy peers can supply a client IP.
    trusted = os.environ.get("SHARE_TRUSTED_PROXIES", "127.0.0.1,::1").split(",")
    if ip in trusted:
        forwarded = handler.headers.get("X-Forwarded-For", "").split(",")[-1].strip()
        try:
            ip = str(ipaddress.ip_address(forwarded))
        except ValueError:
            pass
    ua = handler.headers.get("User-Agent", "")[:512]
    browser = next((name for key, name in [("Edg/", "Edge"), ("OPR/", "Opera"), ("Firefox/", "Firefox"), ("Chrome/", "Chrome"), ("Safari/", "Safari")] if key in ua), "Other")
    system = next((name for key, name in [("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iOS"), ("Windows", "Windows"), ("Macintosh", "macOS"), ("Linux", "Linux")] if key in ua), "Other")
    return dict(ip=ip, user_agent=ua, browser=browser, os=system,
        device="Mobile" if re.search("Mobile|Android|iPad", ua) else "Desktop",
        referer=handler.headers.get("Referer", "")[:512],
        visitor_hash=hashlib.sha256((ip + "\0" + ua).encode()).hexdigest())


def classify(filename, claimed_mime, sample=None):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    groups = {"IMAGE": "jpg jpeg png gif webp bmp", "VIDEO": "mp4 webm mov m4v", "AUDIO": "mp3 wav ogg m4a flac", "PDF": "pdf", "WORD": "doc docx", "EXCEL": "xls xlsx csv", "PPT": "ppt pptx", "ARCHIVE": "zip rar 7z tar gz", "TEXT": "txt log md"}
    kind = next((k for k, extensions in groups.items() if ext in extensions.split()), "OTHER")
    mimes = {"jpg":"image/jpeg", "jpeg":"image/jpeg", "png":"image/png", "gif":"image/gif", "webp":"image/webp", "bmp":"image/bmp", "mp4":"video/mp4", "m4v":"video/mp4", "mov":"video/quicktime", "webm":"video/webm", "mp3":"audio/mpeg", "wav":"audio/wav", "ogg":"audio/ogg", "m4a":"audio/mp4", "flac":"audio/flac", "pdf":"application/pdf", "txt":"text/plain", "log":"text/plain", "md":"text/plain"}
    mime = mimes.get(ext, "application/octet-stream")
    if sample is not None:
        signatures = {"image/jpeg": sample.startswith(b'\xff\xd8\xff'), "image/png": sample.startswith(b'\x89PNG\r\n\x1a\n'), "image/gif": sample.startswith((b'GIF87a', b'GIF89a')), "image/webp": sample[:4]==b'RIFF' and sample[8:12]==b'WEBP', "image/bmp": sample.startswith(b'BM'), "application/pdf": sample.startswith(b'%PDF-'), "video/mp4": sample[4:8]==b'ftyp', "video/quicktime": sample[4:8]==b'ftyp', "video/webm": sample.startswith(b'\x1aE\xdf\xa3'), "audio/mp4": sample[4:8]==b'ftyp', "audio/mpeg": sample.startswith(b'ID3') or sample[:2] in (b'\xff\xfb', b'\xff\xf3', b'\xff\xf2'), "audio/wav": sample[:4]==b'RIFF' and sample[8:12]==b'WAVE', "audio/ogg": sample.startswith(b'OggS'), "audio/flac": sample.startswith(b'fLaC')}
        if mime in signatures and not signatures[mime]:
            kind, mime = "OTHER", "application/octet-stream"
        if kind == "TEXT" and b'\0' in sample:
            kind, mime = "OTHER", "application/octet-stream"
    if claimed_mime and kind in {"IMAGE", "VIDEO", "AUDIO"} and not claimed_mime.startswith(mime.split('/')[0] + '/'):
        kind, mime = "OTHER", "application/octet-stream"
    return kind, mime
