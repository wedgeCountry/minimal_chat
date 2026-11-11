-- User Registry: eigene Datenbank (data/user_registry.db.enc) fuer die
-- Login-Credentials, damit das Login-System spaeter austauschbar ist.

CREATE TABLE IF NOT EXISTS users (
    uid        TEXT PRIMARY KEY,
    username   TEXT NOT NULL UNIQUE,
    salt       TEXT NOT NULL,
    verifier   TEXT NOT NULL,
    key        TEXT NOT NULL,
    created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);
