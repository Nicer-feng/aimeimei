CREATE TABLE IF NOT EXISTS share_files (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, filename TEXT NOT NULL,
 original_filename TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, bucket TEXT NOT NULL,
 mime_type TEXT NOT NULL, file_type TEXT NOT NULL, size INTEGER NOT NULL,
 sha256 TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'UPLOADING', upload_id TEXT,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL, deleted_at INTEGER
);
CREATE INDEX IF NOT EXISTS sf_owner ON share_files(user_id,status,created_at);
CREATE TABLE IF NOT EXISTS shares (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, share_code TEXT NOT NULL UNIQUE,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', password_hash TEXT,
 expires_at INTEGER, max_views INTEGER, max_downloads INTEGER,
 allow_preview INTEGER NOT NULL DEFAULT 1, allow_download INTEGER NOT NULL DEFAULT 1,
 status TEXT NOT NULL DEFAULT 'ACTIVE', view_count INTEGER NOT NULL DEFAULT 0,
 download_count INTEGER NOT NULL DEFAULT 0, auth_version INTEGER NOT NULL DEFAULT 1,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS shares_owner ON shares(user_id,created_at);
CREATE TABLE IF NOT EXISTS share_files_relation (
 share_id TEXT NOT NULL REFERENCES shares(id), file_id TEXT NOT NULL REFERENCES share_files(id),
 sort_order INTEGER NOT NULL, PRIMARY KEY(share_id,file_id)
);
CREATE TABLE IF NOT EXISTS share_access_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, share_id TEXT REFERENCES shares(id), file_id TEXT,
 action TEXT NOT NULL, ip TEXT NOT NULL, user_agent TEXT NOT NULL, browser TEXT NOT NULL,
 os TEXT NOT NULL, device TEXT NOT NULL, referer TEXT NOT NULL, country TEXT DEFAULT '',
 province TEXT DEFAULT '', city TEXT DEFAULT '', success INTEGER NOT NULL,
 visitor_hash TEXT NOT NULL, unique_visit INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sal_share ON share_access_logs(share_id,created_at);
CREATE INDEX IF NOT EXISTS sal_visitor ON share_access_logs(share_id,visitor_hash,action,success,created_at);
CREATE TABLE IF NOT EXISTS share_sessions (
 token_hash TEXT PRIMARY KEY, share_id TEXT NOT NULL REFERENCES shares(id),
 auth_version INTEGER NOT NULL, expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS share_rate_limits (
 rate_key TEXT PRIMARY KEY, window_start INTEGER NOT NULL, count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS share_settings (
 user_id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', max_upload_bytes INTEGER NOT NULL DEFAULT 524288000
);
CREATE TABLE IF NOT EXISTS share_audit_logs (
 id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, action TEXT NOT NULL,
 target_id TEXT NOT NULL, ip TEXT NOT NULL, created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS share_office_versions (
 id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES share_files(id),
 version_no INTEGER NOT NULL, object_key TEXT NOT NULL UNIQUE,
 size INTEGER NOT NULL, sha256 TEXT NOT NULL, etag TEXT,
 source_session_id TEXT, created_by TEXT NOT NULL,
 published_at INTEGER, created_at INTEGER NOT NULL,
 UNIQUE(file_id, version_no)
);
CREATE INDEX IF NOT EXISTS sov_file ON share_office_versions(file_id, version_no DESC);

CREATE TABLE IF NOT EXISTS share_office_sessions (
 id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES share_files(id),
 user_id TEXT NOT NULL, draft_key TEXT NOT NULL UNIQUE,
 source_key TEXT NOT NULL, source_etag TEXT,
 status TEXT NOT NULL, recoverable INTEGER NOT NULL DEFAULT 1,
 draft_etag_at_publish TEXT, access_token_hash TEXT, refresh_token_hash TEXT,
 last_snapshot_etag TEXT, expires_at INTEGER NOT NULL, refresh_expires_at INTEGER NOT NULL,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS sos_one_editor ON share_office_sessions(file_id)
 WHERE status IN ('PREPARING', 'ACTIVE');
CREATE INDEX IF NOT EXISTS sos_file_history ON share_office_sessions(file_id, created_at DESC);

-- Short-lived browser-to-OSS PDF uploads. Completed PDFs use the common
-- immutable version table, while unfinished multipart uploads stay separate.
CREATE TABLE IF NOT EXISTS share_pdf_uploads (
 id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES share_files(id),
 user_id TEXT NOT NULL, object_key TEXT NOT NULL UNIQUE, upload_id TEXT,
 size INTEGER NOT NULL, sha256 TEXT NOT NULL, base_revision TEXT NOT NULL,
 source_key TEXT NOT NULL, status TEXT NOT NULL, version_id TEXT,
 expires_at INTEGER NOT NULL, lease_until INTEGER NOT NULL DEFAULT 0,
 created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS spu_one_active ON share_pdf_uploads(file_id)
 WHERE status IN ('PREPARING', 'UPLOADING', 'COMPLETING');
CREATE INDEX IF NOT EXISTS spu_expiry ON share_pdf_uploads(status,expires_at);

CREATE TABLE IF NOT EXISTS infrastructure_ip_locations (
 ip TEXT PRIMARY KEY, country TEXT NOT NULL DEFAULT '', province TEXT NOT NULL DEFAULT '',
 city TEXT NOT NULL DEFAULT '', status TEXT NOT NULL, expires_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ip_locations_expiry ON infrastructure_ip_locations(expires_at);

-- Preserve stricter per-user limits; clamp legacy settings to the platform cap.
UPDATE share_settings SET max_upload_bytes=524288000 WHERE max_upload_bytes>524288000;

CREATE TABLE IF NOT EXISTS share_members (
 user_id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0,
 last_login_at INTEGER, last_visit_at INTEGER
);
CREATE INDEX IF NOT EXISTS sal_time ON share_access_logs(created_at);
CREATE INDEX IF NOT EXISTS share_audit_action_time ON share_audit_logs(action,created_at);
