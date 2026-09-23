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
