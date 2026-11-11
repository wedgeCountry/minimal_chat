-- LeanChat SQL-Schema pro User (eine verschluesselte SQLite-Datei pro User)

CREATE TABLE IF NOT EXISTS sessions (
    id   TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    ts   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions (id) ON DELETE CASCADE,
    role        TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    type        TEXT NOT NULL DEFAULT 'message' CHECK (type IN ('message', 'toolcall', 'reasoning')),
    text        TEXT NOT NULL DEFAULT '',
    in_context  INTEGER NOT NULL DEFAULT 1,
    attachments TEXT NOT NULL DEFAULT '[]',
    created_at  INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages (session_id, id);

CREATE TABLE IF NOT EXISTS user_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
