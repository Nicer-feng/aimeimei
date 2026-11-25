CREATE TABLE IF NOT EXISTS units (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, parent_id INTEGER REFERENCES units(id)
);
CREATE TABLE IF NOT EXISTS sites (
    id INTEGER PRIMARY KEY, unit_id INTEGER NOT NULL REFERENCES units(id), name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rooms (
    id INTEGER PRIMARY KEY, site_id INTEGER NOT NULL REFERENCES sites(id), name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS racks (
    id INTEGER PRIMARY KEY, room_id INTEGER NOT NULL REFERENCES rooms(id), name TEXT NOT NULL,
    height INTEGER NOT NULL CHECK (height > 0)
);
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE COLLATE NOCASE, name TEXT NOT NULL,
    type TEXT NOT NULL, model TEXT NOT NULL, serial TEXT NOT NULL,
    room_id INTEGER NOT NULL REFERENCES rooms(id), rack_id INTEGER REFERENCES racks(id),
    face TEXT, u_start INTEGER, u_height INTEGER, workstation TEXT NOT NULL,
    purpose TEXT NOT NULL, ownership TEXT NOT NULL, reporter TEXT NOT NULL,
    maintainer TEXT NOT NULL, verified_on TEXT, purchased_on TEXT,
    price REAL CHECK (price >= 0),
    mount_depth TEXT NOT NULL DEFAULT 'unknown' CHECK (
        mount_depth IN ('unknown', 'half', 'full') AND (rack_id IS NOT NULL OR mount_depth = 'unknown')
    ),
    CHECK ((rack_id IS NULL AND face IS NULL AND u_start IS NULL AND u_height IS NULL) OR
           (rack_id IS NOT NULL AND face IS NOT NULL AND face IN ('front', 'rear') AND
            u_start IS NOT NULL AND u_start > 0 AND u_height IS NOT NULL AND u_height > 0))
);
CREATE INDEX IF NOT EXISTS devices_rack_face ON devices(rack_id, face, u_start);
CREATE TABLE IF NOT EXISTS systems (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS deployments (
    id INTEGER PRIMARY KEY, system_id INTEGER NOT NULL REFERENCES systems(id),
    device_id INTEGER NOT NULL REFERENCES devices(id), note TEXT NOT NULL,
    UNIQUE (system_id, device_id)
);
CREATE TABLE IF NOT EXISTS service_entries (
    id INTEGER PRIMARY KEY, deployment_id INTEGER NOT NULL REFERENCES deployments(id) ON DELETE CASCADE,
    host TEXT NOT NULL, protocol TEXT NOT NULL, port INTEGER CHECK (port BETWEEN 1 AND 65535),
    purpose TEXT NOT NULL, url TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL, code TEXT NOT NULL UNIQUE COLLATE NOCASE,
    description TEXT NOT NULL, site_id INTEGER NOT NULL REFERENCES sites(id)
);
CREATE TABLE IF NOT EXISTS project_devices (
    project_id INTEGER NOT NULL REFERENCES projects(id), device_id INTEGER NOT NULL REFERENCES devices(id),
    PRIMARY KEY (project_id, device_id)
);
CREATE TABLE IF NOT EXISTS files (
    digest TEXT PRIMARY KEY, content BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL,
    project_id INTEGER REFERENCES projects(id), device_id INTEGER REFERENCES devices(id),
    page INTEGER CHECK (page > 0), note TEXT NOT NULL, filename TEXT NOT NULL,
    file_digest TEXT NOT NULL REFERENCES files(digest),
    CHECK ((project_id IS NULL) <> (device_id IS NULL))
);
CREATE TABLE IF NOT EXISTS users (
    username TEXT PRIMARY KEY, role TEXT NOT NULL CHECK(role IN ('admin', 'reader')),
    unit_id INTEGER REFERENCES units(id), password_hash TEXT,
    CHECK ((role = 'admin' AND unit_id IS NULL) OR (role = 'reader' AND unit_id IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS sessions (
    token_digest TEXT PRIMARY KEY, username TEXT NOT NULL REFERENCES users(username),
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
