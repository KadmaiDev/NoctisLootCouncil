import pathlib
import sqlite3

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- The official item list. `dirty` is a change counter: anything that changes what an item's
-- Discord posts show bumps it, and the poster clears it only if it hasn't moved since it rendered.
CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY,           -- the game's item ID
    name          TEXT NOT NULL,
    link          TEXT,
    quality       INTEGER,
    slot          TEXT,                          -- free text from /loot add, e.g. "Waist · Cloth"
    source        TEXT,                          -- free text from /loot add, e.g. "Molten Core, Gehennas"
    inst          INTEGER,                       -- instance ID, from uploads
    first_at      INTEGER,
    last_at       INTEGER,
    seen          INTEGER NOT NULL DEFAULT 0,    -- the largest `seen` any upload reported
    added_by      TEXT,                          -- who used /loot add (NULL: it came from an upload)
    created_at    INTEGER NOT NULL,
    new_in_raid   INTEGER NOT NULL DEFAULT 0,    -- first reached the bot through an upload, already dropped
    decision      TEXT,                          -- 'council' / 'roll' from the officers' votes
    decided_at    INTEGER,
    cleared_at    INTEGER,                       -- decisions `at` that took the decision back ("none"); NULL once decided again
    priority      TEXT,
    priority_by   TEXT,
    game_handling TEXT,                          -- decision set in game, used only without a Discord one
    game_note     TEXT,
    game_by       TEXT,
    dirty         INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS item_sources (
    item_id INTEGER NOT NULL REFERENCES items(id),
    src     TEXT NOT NULL,                       -- e663 boss, n1234 trash, o5678 chest
    count   INTEGER NOT NULL,
    PRIMARY KEY (item_id, src)
);

CREATE TABLE IF NOT EXISTS votes (
    item_id   INTEGER NOT NULL REFERENCES items(id),
    user_id   INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    choice    TEXT NOT NULL,
    at        INTEGER NOT NULL,
    PRIMARY KEY (item_id, user_id)
);

CREATE TABLE IF NOT EXISTS suggestions (
    item_id INTEGER NOT NULL REFERENCES items(id),
    user_id INTEGER NOT NULL,
    at      INTEGER NOT NULL,
    PRIMARY KEY (item_id, user_id)
);

CREATE TABLE IF NOT EXISTS encounters (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    inst INTEGER
);

CREATE TABLE IF NOT EXISTS instances (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);

-- One row per sighting, de-duplicated across officers: reports of the same item and source
-- within 15 minutes of each other are one row (rules.same_drop).
CREATE TABLE IF NOT EXISTS drops (
    id      INTEGER PRIMARY KEY,
    item_id INTEGER NOT NULL,
    src     TEXT NOT NULL,
    at      INTEGER NOT NULL,
    inst    INTEGER,
    n       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS drops_item ON drops(item_id, src, at);

CREATE TABLE IF NOT EXISTS awards (
    who_key     TEXT NOT NULL,
    item_id     INTEGER NOT NULL,
    at          INTEGER NOT NULL,
    who         TEXT NOT NULL,
    class       TEXT,
    how         TEXT NOT NULL,
    roll        INTEGER,
    note        TEXT,
    inst        TEXT,
    boss        TEXT,
    nms         INTEGER,
    nos         INTEGER,
    tags        TEXT,                            -- council awards: the winner's bid tags
    link        TEXT,
    night       TEXT NOT NULL,                   -- raid night, ISO date in the guild's time zone
    uploader    TEXT,
    received_at INTEGER NOT NULL,
    PRIMARY KEY (who_key, item_id, at)
);

-- One #loot-log post per (raid, night); dirty works as for items.
CREATE TABLE IF NOT EXISTS log_groups (
    inst  TEXT NOT NULL,
    night TEXT NOT NULL,
    dirty INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (inst, night)
);

-- Every message the bot owns, so restarts edit instead of reposting.
CREATE TABLE IF NOT EXISTS posts (
    kind       TEXT NOT NULL,                    -- officer, items, log
    key        TEXT NOT NULL,
    channel_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    thread_id  INTEGER,
    digest     TEXT NOT NULL,                    -- hash of what was last sent, to skip no-op edits
    PRIMARY KEY (kind, key)
);

CREATE TABLE IF NOT EXISTS tokens (
    owner        TEXT PRIMARY KEY,               -- 'discord:<user id>' or 'cli:<name>'
    owner_name   TEXT NOT NULL,
    token_hash   TEXT NOT NULL UNIQUE,
    created_at   INTEGER NOT NULL,
    last_used_at INTEGER
);

CREATE TABLE IF NOT EXISTS uploads (
    id         INTEGER PRIMARY KEY,
    at         INTEGER NOT NULL,
    owner      TEXT NOT NULL,
    uploader   TEXT,
    new_items  INTEGER NOT NULL,
    new_awards INTEGER NOT NULL
);
"""


def connect(path: pathlib.Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
