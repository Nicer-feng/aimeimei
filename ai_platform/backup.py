import gzip
import hashlib
import os
import re
import sqlite3
import subprocess
import tempfile
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import formatdate
from pathlib import Path
from urllib.parse import quote, urlencode

import base64
import hmac

from .runtime import read_json
from .settings import BUILD_ID_PATH, DB_PATH, SECRETS_PATH, VERSION_PATH
from .storage import cat_oss_config, oss_put_bytes, oss_signed_get_url


BACKUP_PREFIX = "backups/ai-platform"
BACKUP_RETENTION_DAYS = 90
BACKUP_NAME_RE = re.compile(r"chat-backup-(\d{8})-(\d{6})\.sqlite\.gz\.enc$")


def _table_exists(conn, table_name):
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone() is not None


def _column_exists(conn, table_name, column_name):
    if not _table_exists(conn, table_name):
        return False
    return any(
        row[1] == column_name
        for row in conn.execute('PRAGMA table_info("{}")'.format(table_name))
    )


def _execute_if_column(conn, table_name, column_name, statement):
    if _column_exists(conn, table_name, column_name):
        conn.execute(statement)


def _scalar(conn, statement):
    try:
        row = conn.execute(statement).fetchone()
        return int(row[0] or 0) if row else 0
    except sqlite3.Error:
        return 0


def create_sanitized_snapshot(source_path, snapshot_path):
    source_uri = "file:{}?mode=ro".format(quote(str(source_path), safe="/"))
    source = sqlite3.connect(source_uri, uri=True, timeout=30)
    destination = sqlite3.connect(str(snapshot_path), timeout=30)
    try:
        source.backup(destination, pages=256, sleep=0.01)
    finally:
        source.close()

    try:
        destination.execute("PRAGMA foreign_keys=OFF")
        destination.execute("PRAGMA secure_delete=ON")

        _execute_if_column(destination, "models", "api_key", "UPDATE models SET api_key='' ")
        _execute_if_column(destination, "users", "password_hash", "UPDATE users SET password_hash='' ")
        _execute_if_column(destination, "cat_users", "password_hash", "UPDATE cat_users SET password_hash='' ")
        _execute_if_column(destination, "media_analysis_tasks", "file_url", "UPDATE media_analysis_tasks SET file_url='' ")
        _execute_if_column(destination, "media_analysis_tasks", "file_url_expires_at", "UPDATE media_analysis_tasks SET file_url_expires_at=0")
        _execute_if_column(destination, "media_analysis_tasks", "raw_result_json", "UPDATE media_analysis_tasks SET raw_result_json='' ")
        _execute_if_column(destination, "chat_message_images", "oss_url", "UPDATE chat_message_images SET oss_url='' ")
        _execute_if_column(destination, "message_tts", "error_message", "UPDATE message_tts SET error_message='' ")

        for table_name in ("sessions", "cat_sessions", "conversation_shares"):
            if _table_exists(destination, table_name):
                destination.execute('DELETE FROM "{}"'.format(table_name))

        counts = {
            "users": _scalar(destination, "SELECT COUNT(*) FROM users"),
            "conversations": _scalar(destination, "SELECT COUNT(*) FROM conversations"),
            "messages": _scalar(destination, "SELECT COUNT(*) FROM messages"),
            "favorites": _scalar(destination, "SELECT COUNT(*) FROM favorite_messages"),
            "side_discussions": _scalar(destination, "SELECT COUNT(*) FROM side_discussions"),
            "media_tasks": _scalar(destination, "SELECT COUNT(*) FROM media_analysis_tasks"),
        }
        destination.execute(
            """
            CREATE TABLE IF NOT EXISTS backup_manifest (
              created_at TEXT NOT NULL,
              source_version TEXT NOT NULL,
              source_build_id TEXT NOT NULL,
              sanitized INTEGER NOT NULL,
              source_db_size INTEGER NOT NULL
            )
            """
        )
        destination.execute("DELETE FROM backup_manifest")
        destination.execute(
            "INSERT INTO backup_manifest VALUES (?, ?, ?, 1, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                VERSION_PATH.read_text(encoding="utf-8").strip(),
                BUILD_ID_PATH.read_text(encoding="utf-8").strip(),
                source_path.stat().st_size,
            ),
        )
        destination.commit()
        destination.execute("VACUUM")
        integrity = destination.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("sanitized SQLite snapshot failed integrity check")
        return counts
    finally:
        destination.close()


def gzip_snapshot(snapshot_path, archive_path):
    with snapshot_path.open("rb") as source, archive_path.open("wb") as target:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=target,
            mtime=0,
        ) as compressed:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                compressed.write(chunk)
    os.chmod(archive_path, 0o600)


def encrypt_archive(source_path, encrypted_path, key_path):
    if not key_path.is_file() or key_path.stat().st_size < 32:
        raise RuntimeError("backup encryption key is missing or invalid")
    command = [
        "openssl",
        "enc",
        "-aes-256-cbc",
        "-salt",
        "-pbkdf2",
        "-iter",
        "200000",
        "-md",
        "sha256",
        "-pass",
        "file:{}".format(key_path),
        "-in",
        str(source_path),
        "-out",
        str(encrypted_path),
    ]
    result = subprocess.run(
        command,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("backup archive encryption failed")
    os.chmod(encrypted_path, 0o600)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _oss_authorization(config, method, canonical_resource, date_value):
    string_to_sign = "{}\n\n\n{}\n{}".format(
        method,
        date_value,
        canonical_resource,
    )
    signature = base64.b64encode(
        hmac.new(
            config["access_key_secret"].encode(),
            string_to_sign.encode(),
            hashlib.sha1,
        ).digest()
    ).decode()
    return "OSS {}:{}".format(config["access_key_id"], signature)


def list_oss_objects(config, prefix):
    date_value = formatdate(timeval=None, localtime=False, usegmt=True)
    canonical_resource = "/{}/".format(config["bucket"])
    query = urlencode({"prefix": prefix.rstrip("/") + "/", "max-keys": "1000"})
    request = urllib.request.Request(
        config["endpoint"].rstrip("/") + "/?" + query,
        headers={
            "Date": date_value,
            "Authorization": _oss_authorization(
                config, "GET", canonical_resource, date_value
            ),
        },
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        root = ET.fromstring(response.read())
    objects = []
    for content in root.findall(".//{*}Contents"):
        key = content.findtext("{*}Key") or ""
        modified = content.findtext("{*}LastModified") or ""
        if key:
            objects.append((key, modified))
    return objects


def delete_oss_object(config, oss_key):
    date_value = formatdate(timeval=None, localtime=False, usegmt=True)
    canonical_resource = "/{}/{}".format(config["bucket"], oss_key)
    request = urllib.request.Request(
        config["endpoint"].rstrip("/")
        + "/"
        + quote(oss_key, safe="/-_.~"),
        headers={
            "Date": date_value,
            "Authorization": _oss_authorization(
                config, "DELETE", canonical_resource, date_value
            ),
        },
        method="DELETE",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status not in (200, 204):
            raise RuntimeError("OSS backup retention delete failed")


def purge_old_backups(config, prefix, retention_days):
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    removed = 0
    for oss_key, modified in list_oss_objects(config, prefix):
        match = BACKUP_NAME_RE.search(oss_key)
        if not match:
            continue
        timestamp = None
        try:
            timestamp = datetime.fromisoformat(modified.replace("Z", "+00:00")).timestamp()
        except (TypeError, ValueError):
            timestamp = datetime.strptime(
                "{}{}".format(match.group(1), match.group(2)), "%Y%m%d%H%M%S"
            ).replace(tzinfo=timezone.utc).timestamp()
        if timestamp < cutoff:
            delete_oss_object(config, oss_key)
            removed += 1
    return removed


def verify_uploaded_backup(config, oss_key, expected_sha256):
    public_url = config["public_base"].rstrip("/") + "/" + quote(
        oss_key, safe="/-_.~"
    )
    publicly_readable = False
    try:
        with urllib.request.urlopen(public_url, timeout=15) as response:
            response.read(1)
            publicly_readable = True
    except urllib.error.HTTPError as exc:
        if exc.code != 403:
            raise RuntimeError("backup privacy check returned HTTP {}".format(exc.code))

    signed_url, _ = oss_signed_get_url(config, oss_key, expires_seconds=600)
    digest = hashlib.sha256()
    with urllib.request.urlopen(signed_url, timeout=90) as response:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise RuntimeError("uploaded backup checksum mismatch")
    return publicly_readable


def run_daily_backup():
    os.umask(0o077)
    if not DB_PATH.exists():
        raise RuntimeError("SQLite database does not exist")

    secrets_data = read_json(SECRETS_PATH, {})
    config = cat_oss_config(secrets_data)
    if not config["configured"]:
        raise RuntimeError("OSS backup is not configured")

    prefix = os.environ.get("AI_PLATFORM_BACKUP_PREFIX", BACKUP_PREFIX).strip("/")
    retention_days = max(
        1,
        int(os.environ.get("AI_PLATFORM_BACKUP_RETENTION_DAYS", BACKUP_RETENTION_DAYS)),
    )
    timestamp = datetime.now().astimezone()
    basename = "chat-backup-{}.sqlite.gz.enc".format(
        timestamp.strftime("%Y%m%d-%H%M%S")
    )
    oss_key = "{}/{}/{}/{}".format(
        prefix,
        timestamp.strftime("%Y"),
        timestamp.strftime("%m"),
        basename,
    )

    with tempfile.TemporaryDirectory(prefix="ai-platform-backup-") as temp_dir:
        temp_path = Path(temp_dir)
        snapshot_path = temp_path / "ai-platform.sanitized.db"
        archive_path = temp_path / basename[:-4]
        encrypted_path = temp_path / basename
        key_path = Path(
            os.environ.get(
                "AI_PLATFORM_BACKUP_KEY_FILE",
                "/etc/ai-platform/backup.key",
            )
        )
        counts = create_sanitized_snapshot(DB_PATH, snapshot_path)
        os.chmod(snapshot_path, 0o600)
        gzip_snapshot(snapshot_path, archive_path)
        plaintext_sha256 = file_sha256(archive_path)
        encrypt_archive(archive_path, encrypted_path, key_path)
        archive_sha256 = file_sha256(encrypted_path)
        archive_data = encrypted_path.read_bytes()

        private_headers = {
            "x-oss-object-acl": "private",
            "x-oss-server-side-encryption": "AES256",
            "x-oss-meta-sha256": archive_sha256,
            "x-oss-meta-backup-version": VERSION_PATH.read_text(
                encoding="utf-8"
            ).strip(),
            "x-oss-meta-backup-format": "aes-256-cbc-pbkdf2",
        }
        oss_put_bytes(
            config,
            oss_key,
            archive_data,
            content_type="application/octet-stream",
            oss_headers=private_headers,
        )

        manifest = {
            "format": "ai-platform-sanitized-sqlite-gzip-aes256-v1",
            "created_at": timestamp.isoformat(),
            "version": VERSION_PATH.read_text(encoding="utf-8").strip(),
            "build_id": BUILD_ID_PATH.read_text(encoding="utf-8").strip(),
            "object_key": oss_key,
            "compressed_size": len(archive_data),
            "sha256": archive_sha256,
            "plaintext_sha256": plaintext_sha256,
            "sanitized": True,
            "encrypted": True,
            "counts": counts,
        }
        publicly_readable = verify_uploaded_backup(config, oss_key, archive_sha256)

    try:
        removed = purge_old_backups(config, prefix, retention_days)
    except Exception as exc:
        print("backup uploaded; retention cleanup warning: {}".format(type(exc).__name__))
        removed = 0

    print(
        "backup uploaded: key={} size={} sha256={} encrypted=yes public_endpoint={} users={} conversations={} messages={} removed={}".format(
            oss_key,
            manifest["compressed_size"],
            archive_sha256[:12],
            "yes" if publicly_readable else "no",
            counts["users"],
            counts["conversations"],
            counts["messages"],
            removed,
        )
    )
    return manifest
