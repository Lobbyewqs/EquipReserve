PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS app_user (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('USER','ADMIN')), enabled INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS device (
 id INTEGER PRIMARY KEY, asset_code TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
 category TEXT NOT NULL, description TEXT NOT NULL DEFAULT '', enabled INTEGER NOT NULL DEFAULT 1,
 current_loan_id INTEGER REFERENCES reservation(id)
);
CREATE TABLE IF NOT EXISTS reservation (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES app_user(id),
 device_id INTEGER NOT NULL REFERENCES device(id), slot_start TEXT NOT NULL, slot_end TEXT NOT NULL,
 pickup_deadline TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('CONFIRMED','CANCELLED','EXPIRED','BORROWED','RETURNED')),
 borrowed_at TEXT, returned_at TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS reservation_user_created ON reservation(user_id,created_at);
CREATE INDEX IF NOT EXISTS reservation_expiry ON reservation(status,pickup_deadline);
CREATE INDEX IF NOT EXISTS reservation_device_start ON reservation(device_id,slot_start);
CREATE UNIQUE INDEX IF NOT EXISTS one_physical_loan ON reservation(device_id) WHERE status='BORROWED';
CREATE TABLE IF NOT EXISTS slot_occupancy (
 device_id INTEGER NOT NULL REFERENCES device(id), slot_start TEXT NOT NULL,
 reservation_id INTEGER NOT NULL UNIQUE REFERENCES reservation(id), PRIMARY KEY(device_id,slot_start)
);
CREATE TABLE IF NOT EXISTS idempotency_record (
 user_id INTEGER NOT NULL REFERENCES app_user(id), operation TEXT NOT NULL, request_key TEXT NOT NULL,
 request_hash TEXT NOT NULL, response_json TEXT NOT NULL, response_code INTEGER NOT NULL,
 PRIMARY KEY(user_id,operation,request_key)
);
CREATE TABLE IF NOT EXISTS audit_event (
 id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES app_user(id), action TEXT NOT NULL,
 target_id INTEGER, before_state TEXT, after_state TEXT, reason TEXT,
 request_id TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_target_created ON audit_event(target_id,created_at);
CREATE TABLE IF NOT EXISTS session (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES app_user(id), csrf TEXT NOT NULL, expires_at TEXT NOT NULL
);
PRAGMA user_version=1;
