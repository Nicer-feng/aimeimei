import gzip
import hashlib
import json
import struct
from contextlib import closing, contextmanager
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
AUTHENTICATED_MAGIC = b"AI-PLATFORM-BACKUP-V2\n"
AUTHENTICATED_FORMAT = "ai-platform-sqlite-gzip-aes256cbc-hmacsha256-v2"
FULL_BACKUP_NAME_RE = re.compile(r"full-backup-(\d{8})-(\d{6})\.sqlite\.gz\.auth\.enc$")
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


@contextmanager
def _snapshot_connection(source_path, snapshot_path):
    """Own both connections on every failure path and never overwrite an existing file."""
    source_path, snapshot_path = Path(source_path), Path(snapshot_path)
    source_uri = "file:{}?mode=ro".format(quote(str(source_path.resolve()), safe="/"))
    created = False
    try:
        with closing(sqlite3.connect(source_uri, uri=True, timeout=30)) as source:
            descriptor = os.open(snapshot_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(descriptor)
            created = True
            with closing(sqlite3.connect(str(snapshot_path), timeout=30)) as destination:
                source.backup(destination, pages=256, sleep=0.01)
                # A portable snapshot must be one SQLite file, including when the source uses WAL.
                destination.execute("PRAGMA journal_mode=DELETE")
                yield destination
    except BaseException:
        if created:
            snapshot_path.unlink(missing_ok=True)
        raise


def create_sanitized_snapshot(source_path, snapshot_path):
    return create_database_snapshot(source_path, snapshot_path, mode="sanitized")


def create_database_snapshot(source_path, snapshot_path, mode="sanitized"):
    """Full keeps all shared-product tables; sanitized retains the legacy redaction contract."""
    if mode not in {"sanitized", "full"}:
        raise ValueError("backup mode must be sanitized or full")
    source_path = Path(source_path)
    sanitized = mode == "sanitized"
    with _snapshot_connection(source_path, snapshot_path) as destination:
        if sanitized:
            destination.execute("PRAGMA foreign_keys=OFF")
            destination.execute("PRAGMA secure_delete=ON")

            _execute_if_column(destination, "models", "api_key", "UPDATE models SET api_key='' ")
            _execute_if_column(destination, "users", "password_hash", "UPDATE users SET password_hash='' ")
            _execute_if_column(destination, "users", "phone", "UPDATE users SET phone='' ")
            _execute_if_column(destination, "users", "phone_verified_at", "UPDATE users SET phone_verified_at=0 ")
            _execute_if_column(destination, "cat_users", "password_hash", "UPDATE cat_users SET password_hash='' ")
            _execute_if_column(destination, "media_analysis_tasks", "file_url", "UPDATE media_analysis_tasks SET file_url='' ")
            _execute_if_column(destination, "media_analysis_tasks", "file_url_expires_at", "UPDATE media_analysis_tasks SET file_url_expires_at=0")
            _execute_if_column(destination, "media_analysis_tasks", "raw_result_json", "UPDATE media_analysis_tasks SET raw_result_json='' ")
            _execute_if_column(destination, "chat_message_images", "oss_url", "UPDATE chat_message_images SET oss_url='' ")
            _execute_if_column(destination, "message_tts", "error_message", "UPDATE message_tts SET error_message='' ")

            for table_name in ("sessions", "cat_sessions", "conversation_shares", "login_captchas",
                               "sms_login_challenges", "share_sessions", "share_office_sessions", "share_pdf_uploads", "share_files_relation", "share_access_logs",
                               "shares", "share_rate_limits", "infrastructure_ip_locations"):
                if _table_exists(destination, table_name):
                    destination.execute('DELETE FROM "{}"'.format(table_name))

            _execute_if_column(destination, "share_files", "upload_id", "UPDATE share_files SET upload_id=NULL")

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
            "INSERT INTO backup_manifest (created_at, source_version, source_build_id, sanitized, source_db_size) VALUES (?, ?, ?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                VERSION_PATH.read_text(encoding="utf-8").strip(),
                BUILD_ID_PATH.read_text(encoding="utf-8").strip(),
                int(sanitized),
                source_path.stat().st_size,
            ),
        )
        destination.commit()
        destination.execute("VACUUM")
        integrity = destination.execute("PRAGMA integrity_check").fetchone()
        if not integrity or integrity[0] != "ok":
            raise RuntimeError("SQLite snapshot failed integrity check")
        return counts


def gzip_snapshot(snapshot_path, archive_path):
    with snapshot_path.open("rb") as source, open(
        archive_path, "wb", opener=lambda name, flags: os.open(name, flags, 0o600)
    ) as target:
        os.fchmod(target.fileno(), 0o600)
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
        umask=0o077,
    )
    if result.returncode != 0:
        raise RuntimeError("backup archive encryption failed")
    os.chmod(encrypted_path, 0o600)


def _mac_key(key_path, salt):
    key_path = Path(key_path)
    if not key_path.is_file() or key_path.stat().st_size < 32:
        raise RuntimeError("backup encryption key is missing or invalid")
    material = key_path.read_bytes()
    # OpenSSL's file: passphrase source uses its first line; do not accept a short effective password.
    first_line = material.split(b"\n", 1)[0].rstrip(b"\r")
    if len(first_line) < 32 or b"\0" in first_line:
        raise RuntimeError("backup key must have at least 32 non-NUL bytes on its first line")
    return hashlib.pbkdf2_hmac(
        "sha256", material, b"ai-platform-backup-v2/mac\0" + salt,
        200000, dklen=32,
    )


def encrypt_authenticated_archive(source_path, encrypted_path, key_path):
    """Encrypt then authenticate the complete header and ciphertext before publishing."""
    source_path, encrypted_path, key_path = map(Path, (source_path, encrypted_path, key_path))
    salt = os.urandom(16)
    mac_key = _mac_key(key_path, salt)
    header = json.dumps({"format": AUTHENTICATED_FORMAT,
                         "mac_salt": base64.b64encode(salt).decode("ascii")},
                        sort_keys=True, separators=(",", ":")).encode("ascii")
    prefix = AUTHENTICATED_MAGIC + struct.pack(">I", len(header)) + header
    with tempfile.TemporaryDirectory(prefix="backup-encrypt-", dir=encrypted_path.parent) as directory:
        ciphertext = Path(directory) / "ciphertext.enc"
        envelope = Path(directory) / "archive.auth.enc"
        encrypt_archive(source_path, ciphertext, key_path)
        digest = hmac.new(mac_key, prefix, hashlib.sha256)
        with ciphertext.open("rb") as source, envelope.open("xb") as target:
            os.chmod(envelope, 0o600)
            target.write(prefix)
            while chunk := source.read(1024 * 1024):
                target.write(chunk)
                digest.update(chunk)
            target.write(digest.digest())
            target.flush()
            os.fsync(target.fileno())
        # Same-filesystem link provides atomic no-clobber publication, even if another writer races us.
        os.link(envelope, encrypted_path)


def decrypt_authenticated_archive(encrypted_path, archive_path, key_path):
    """Reject wrong keys or modified bytes before invoking the CBC decryptor."""
    encrypted_path, archive_path, key_path = map(Path, (encrypted_path, archive_path, key_path))
    with tempfile.TemporaryDirectory(prefix="backup-decrypt-", dir=archive_path.parent) as directory:
        ciphertext = Path(directory) / "ciphertext.enc"
        plaintext = Path(directory) / "archive.gz"
        with encrypted_path.open("rb") as source:
            magic = source.read(len(AUTHENTICATED_MAGIC))
            length_bytes = source.read(4)
            if magic != AUTHENTICATED_MAGIC or len(length_bytes) != 4:
                raise ValueError("not an authenticated v2 backup; legacy archives require the legacy recovery procedure")
            header_size = struct.unpack(">I", length_bytes)[0]
            if not 1 <= header_size <= 4096:
                raise ValueError("invalid backup header")
            header = source.read(header_size)
            try:
                info = json.loads(header)
                salt = base64.b64decode(info["mac_salt"], validate=True)
                if info["format"] != AUTHENTICATED_FORMAT or len(salt) != 16:
                    raise ValueError()
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError("invalid backup header") from error
            digest = hmac.new(_mac_key(key_path, salt), magic + length_bytes + header, hashlib.sha256)
            remaining = os.fstat(source.fileno()).st_size - source.tell() - 32
            if remaining < 32:
                raise ValueError("truncated backup archive")
            with ciphertext.open("xb") as target:
                os.chmod(ciphertext, 0o600)
                while remaining:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise ValueError("truncated backup archive")
                    remaining -= len(chunk)
                    digest.update(chunk)
                    target.write(chunk)
            tag = source.read(32)
            if source.read(1) or not hmac.compare_digest(tag, digest.digest()):
                raise ValueError("backup authentication failed: wrong key or modified archive")
        result = subprocess.run(
            ["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000",
             "-md", "sha256", "-pass", "file:{}".format(key_path),
             "-in", str(ciphertext), "-out", str(plaintext)],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False, umask=0o077,
        )
        if result.returncode:
            raise RuntimeError("backup archive decryption failed")
        os.chmod(plaintext, 0o600)
        os.link(plaintext, archive_path)


def validate_backup_database(snapshot_path, expected_mode="full"):
    """Validate an isolated restored file; never open or migrate the application's live database."""
    if expected_mode not in {"full", "sanitized", None}:
        raise ValueError("expected backup mode must be full or sanitized")
    snapshot_path = Path(snapshot_path)
    with snapshot_path.open("rb") as handle:
        if handle.read(16) != b"SQLite format 3\0":
            raise ValueError("backup payload is not SQLite")
    uri = "file:{}?mode=ro&immutable=1".format(quote(str(snapshot_path.resolve()), safe="/"))
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        connection.execute("PRAGMA trusted_schema=OFF")
        if connection.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
            raise ValueError("restored SQLite failed integrity check")
        rows = connection.execute(
            "SELECT created_at, source_version, source_build_id, sanitized, source_db_size FROM backup_manifest"
        ).fetchall()
        if len(rows) != 1 or rows[0][3] not in (0, 1):
            raise ValueError("backup manifest is missing or invalid")
        mode = "sanitized" if rows[0][3] else "full"
        if expected_mode is not None and mode != expected_mode:
            raise ValueError("backup mode mismatch: expected {}, received {}".format(expected_mode, mode))
        if mode == "full" and connection.execute("PRAGMA foreign_key_check").fetchone():
            raise ValueError("restored SQLite has broken foreign-key references")
        table_count = connection.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
        return {"mode": mode, "created_at": rows[0][0], "version": rows[0][1],
                "build_id": rows[0][2], "table_count": table_count,
                "database_size": snapshot_path.stat().st_size, "integrity": "ok"}


def create_local_backup(source_path, output_path, key_path, mode="sanitized"):
    output_path = Path(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError("backup output already exists")
    with tempfile.TemporaryDirectory(prefix="database-backup-", dir=output_path.parent) as directory:
        snapshot = Path(directory) / "snapshot.db"
        archive = Path(directory) / "snapshot.db.gz"
        create_database_snapshot(source_path, snapshot, mode=mode)
        metadata = validate_backup_database(snapshot, expected_mode=mode)
        gzip_snapshot(snapshot, archive)
        encrypt_authenticated_archive(archive, output_path, key_path)
        return {**metadata, "format": AUTHENTICATED_FORMAT, "sha256": file_sha256(output_path),
                "encrypted_size": output_path.stat().st_size}


def restore_local_backup(encrypted_path, output_path, key_path, expected_mode="full", max_bytes=2 * 1024**3):
    """Verify and restore to a new offline file. Existing files and symlinks are never replaced."""
    output_path = Path(output_path)
    if output_path.exists() or output_path.is_symlink():
        raise FileExistsError("restore output already exists; choose a new offline path")
    if max_bytes <= 0:
        raise ValueError("restore size limit must be positive")
    with tempfile.TemporaryDirectory(prefix="database-restore-", dir=output_path.parent) as directory:
        archive = Path(directory) / "snapshot.db.gz"
        snapshot = Path(directory) / "restored.db"
        decrypt_authenticated_archive(encrypted_path, archive, key_path)
        size = 0
        with gzip.open(archive, "rb") as source, snapshot.open("xb") as target:
            os.chmod(snapshot, 0o600)
            while chunk := source.read(1024 * 1024):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("restored database exceeds the configured size limit")
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        metadata = validate_backup_database(snapshot, expected_mode=expected_mode)
        os.link(snapshot, output_path)
        return metadata


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


def purge_old_backups(config, prefix, retention_days, name_pattern=BACKUP_NAME_RE):
    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    removed = 0
    for oss_key, modified in list_oss_objects(config, prefix):
        match = name_pattern.search(oss_key)
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


def run_daily_backup(mode="sanitized"):
    if mode not in {"sanitized", "full"}:
        raise ValueError("backup mode must be sanitized or full")
    os.umask(0o077)
    if not DB_PATH.exists():
        raise RuntimeError("SQLite database does not exist")

    secrets_data = read_json(SECRETS_PATH, {})
    config = cat_oss_config(secrets_data)
    if not config["configured"]:
        raise RuntimeError("OSS backup is not configured")

    prefix = os.environ.get("AI_PLATFORM_BACKUP_PREFIX", BACKUP_PREFIX).strip("/")
    if mode == "full":
        prefix = os.environ.get("AI_PLATFORM_FULL_BACKUP_PREFIX", prefix + "/full").strip("/")
    retention_days = max(
        1,
        int(os.environ.get("AI_PLATFORM_BACKUP_RETENTION_DAYS", BACKUP_RETENTION_DAYS)),
    )
    timestamp = datetime.now().astimezone()
    basename = "chat-backup-{}.sqlite.gz.enc".format(
        timestamp.strftime("%Y%m%d-%H%M%S")
    )
    if mode == "full":
        basename = "full-backup-{}.sqlite.gz.auth.enc".format(timestamp.strftime("%Y%m%d-%H%M%S"))
    oss_key = "{}/{}/{}/{}".format(
        prefix,
        timestamp.strftime("%Y"),
        timestamp.strftime("%m"),
        basename,
    )

    with tempfile.TemporaryDirectory(prefix="ai-platform-backup-") as temp_dir:
        temp_path = Path(temp_dir)
        snapshot_path = temp_path / ("ai-platform." + mode + ".db")
        archive_path = temp_path / basename[:-4]
        encrypted_path = temp_path / basename
        key_path = Path(
            os.environ.get(
                "AI_PLATFORM_BACKUP_KEY_FILE",
                "/etc/ai-platform/backup.key",
            )
        )
        counts = create_database_snapshot(DB_PATH, snapshot_path, mode=mode)
        if mode == "full":
            validate_backup_database(snapshot_path, expected_mode="full")
        os.chmod(snapshot_path, 0o600)
        gzip_snapshot(snapshot_path, archive_path)
        plaintext_sha256 = file_sha256(archive_path)
        if mode == "full":
            encrypt_authenticated_archive(archive_path, encrypted_path, key_path)
        else:
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
            "x-oss-meta-backup-format": "aes-256-cbc-hmac-sha256-v2" if mode == "full" else "aes-256-cbc-pbkdf2",
        }
        oss_put_bytes(
            config,
            oss_key,
            archive_data,
            content_type="application/octet-stream",
            oss_headers=private_headers,
        )

        manifest = {
            "format": AUTHENTICATED_FORMAT if mode == "full" else "ai-platform-sanitized-sqlite-gzip-aes256-v1",
            "mode": mode,
            "created_at": timestamp.isoformat(),
            "version": VERSION_PATH.read_text(encoding="utf-8").strip(),
            "build_id": BUILD_ID_PATH.read_text(encoding="utf-8").strip(),
            "object_key": oss_key,
            "compressed_size": len(archive_data),
            "sha256": archive_sha256,
            "plaintext_sha256": plaintext_sha256,
            "sanitized": mode == "sanitized",
            "encrypted": True,
            "counts": counts,
        }
        publicly_readable = verify_uploaded_backup(config, oss_key, archive_sha256)
        if mode == "full" and publicly_readable:
            raise RuntimeError("full backup uploaded but anonymous access is enabled; retention cleanup was skipped")

    try:
        removed = purge_old_backups(config, prefix, retention_days,
                                    name_pattern=FULL_BACKUP_NAME_RE if mode == "full" else BACKUP_NAME_RE)
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
