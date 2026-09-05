"""PostgreSQL storage layer for the niche-finder project.

Schema v2 adds everything needed for *time-window* analytics (24h / 7d / 30d):
history snapshots of video and channel stats, a tracked-channel watchlist,
chart snapshots, and title/thumbnail change detection.

Connection is configured with either a single NICHE_DATABASE_URL (a full
postgresql:// DSN) or the individual POSTGRES_HOST / POSTGRES_PORT /
POSTGRES_DB / POSTGRES_USER / POSTGRES_PASSWORD variables (used by the
Docker image, which talks to the `postgres` compose service). An optional
NICHE_DB_SCHEMA (default "public") lets tests and multiple deployments share
one Postgres instance without colliding.

Everything above this module (collector.py, trends.py, tracking.py, query.py,
categories.py, worker.py) was written against sqlite3's connection API:
`conn.execute(sql, params)` with '?' placeholders, rows that support both
`row["col"]` and `row[0]`, and `dict(row)`. Rather than touch every call site,
`get_conn()` returns a thin wrapper that provides exactly that surface on top
of psycopg2, translating '?' -> '%s' and wrapping rows in a small sqlite3.Row
lookalike. This is the one file that knows it is talking to Postgres.
"""
import os
import re
from pathlib import Path
from datetime import datetime, timezone

import psycopg2
import psycopg2.extensions
import psycopg2.pool

SCHEMA_VERSION = 2

_SCHEMA_NAME_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _dsn() -> str:
    url = os.environ.get("NICHE_DATABASE_URL")
    if url:
        return url
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    dbname = os.environ.get("POSTGRES_DB", "niches")
    user = os.environ.get("POSTGRES_USER", "niches")
    password = os.environ.get("POSTGRES_PASSWORD", "niches")
    return f"postgresql://{user}:{password}@{host}:{port}/{dbname}"


def _schema() -> str:
    name = os.environ.get("NICHE_DB_SCHEMA", "public")
    if not _SCHEMA_NAME_RE.match(name):
        raise ValueError(f"bad NICHE_DB_SCHEMA {name!r}: must be a plain identifier")
    return name


def display_dsn() -> str:
    """Connection info safe to print/return from an API -- no password."""
    dsn = _dsn()
    try:
        parsed = psycopg2.extensions.parse_dsn(dsn)
        return (f"postgresql://{parsed.get('user')}@{parsed.get('host')}:"
                f"{parsed.get('port', 5432)}/{parsed.get('dbname')}"
                f"?schema={_schema()}")
    except Exception:
        return f"postgres (schema={_schema()})"


SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    channel_id TEXT PRIMARY KEY,
    title TEXT,
    custom_url TEXT,
    country TEXT,
    description TEXT,
    default_language TEXT,
    subscriber_count BIGINT,
    video_count BIGINT,
    view_count BIGINT,
    thumbnail TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS videos (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT,
    title TEXT,
    description TEXT,
    published_at TEXT,
    duration_seconds INTEGER,
    view_count BIGINT,
    like_count BIGINT,
    comment_count BIGINT,
    thumbnail TEXT,
    tags TEXT,
    default_language TEXT,
    embedding BYTEA,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS niches (
    slug TEXT PRIMARY KEY,
    query TEXT,
    label TEXT,
    created_at TEXT,
    last_collected_at TEXT
);

CREATE TABLE IF NOT EXISTS video_niches (
    video_id TEXT,
    niche_slug TEXT,
    PRIMARY KEY (video_id, niche_slug)
);

-- ---------- v2: history / tracking ----------

CREATE TABLE IF NOT EXISTS video_stats_history (
    video_id TEXT,
    captured_at TEXT,
    view_count BIGINT,
    like_count BIGINT,
    comment_count BIGINT,
    title TEXT,
    thumbnail TEXT,
    PRIMARY KEY (video_id, captured_at)
);

CREATE TABLE IF NOT EXISTS channel_stats_history (
    channel_id TEXT,
    captured_at TEXT,
    subscriber_count BIGINT,
    video_count BIGINT,
    view_count BIGINT,
    PRIMARY KEY (channel_id, captured_at)
);

CREATE TABLE IF NOT EXISTS tracked_channels (
    channel_id TEXT PRIMARY KEY,
    note TEXT,
    added_at TEXT,
    last_refreshed_at TEXT,
    active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS chart_snapshots (
    snapshot_id BIGSERIAL PRIMARY KEY,
    captured_at TEXT,
    region TEXT,
    category_id TEXT,
    source TEXT
);

CREATE TABLE IF NOT EXISTS chart_entries (
    snapshot_id BIGINT,
    video_id TEXT,
    rank INTEGER,
    view_count BIGINT,
    PRIMARY KEY (snapshot_id, video_id)
);

CREATE TABLE IF NOT EXISTS video_changes (
    video_id TEXT,
    changed_at TEXT,
    field TEXT,
    old_value TEXT,
    new_value TEXT,
    PRIMARY KEY (video_id, changed_at, field)
);

CREATE TABLE IF NOT EXISTS video_categories (
    category_id TEXT,
    region TEXT,
    title TEXT,
    assignable INTEGER,
    updated_at TEXT,
    PRIMARY KEY (category_id, region)
);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_videos_channel ON videos(channel_id);
CREATE INDEX IF NOT EXISTS idx_videos_published ON videos(published_at);
CREATE INDEX IF NOT EXISTS idx_video_niches_slug ON video_niches(niche_slug);
CREATE INDEX IF NOT EXISTS idx_vsh_video ON video_stats_history(video_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_csh_channel ON channel_stats_history(channel_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_chart_snap ON chart_snapshots(captured_at, region, category_id);
"""

# columns added to pre-existing tables (name -> DDL type)
MIGRATIONS = {
    "videos": {
        "category_id": "TEXT",
        "region": "TEXT",
        "is_short": "INTEGER",
        "topic_categories": "TEXT",
        "first_seen_at": "TEXT",
        "live_content": "TEXT",
    },
    "channels": {
        "published_at": "TEXT",
        "topic_categories": "TEXT",
        "keywords": "TEXT",
        "uploads_playlist": "TEXT",
        "first_seen_at": "TEXT",
        "hidden_subs": "INTEGER",
    },
}


# ------------------------------------------------------ sqlite3-lookalike shim

class Row:
    """Stand-in for sqlite3.Row: supports row[0], row["col"], dict(row), iteration."""
    __slots__ = ("_values", "_index")

    def __init__(self, values, index):
        self._values = values
        self._index = index  # dict: col_name -> position

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._values[self._index[key]]
        return self._values[key]

    def keys(self):
        return list(self._index.keys())

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __repr__(self):
        return repr(dict(zip(self._index.keys(), self._values)))


class _CursorResult:
    """Wraps a real psycopg2 cursor; fetch* return Row objects instead of tuples."""
    __slots__ = ("_cur", "_index")

    def __init__(self, cur):
        self._cur = cur
        self._index = ({d[0]: i for i, d in enumerate(cur.description)}
                       if cur.description else None)

    def fetchone(self):
        row = self._cur.fetchone()
        return Row(row, self._index) if row is not None else None

    def fetchall(self):
        return [Row(r, self._index) for r in self._cur.fetchall()]

    def fetchmany(self, size=None):
        rows = self._cur.fetchmany(size) if size is not None else self._cur.fetchmany()
        return [Row(r, self._index) for r in rows]

    @property
    def rowcount(self):
        return self._cur.rowcount

    @property
    def lastrowid(self):
        # Postgres has no rowid; call sites that need a new id use
        # "RETURNING <col>" and read it with .fetchone() instead.
        raise AttributeError(
            "Postgres has no lastrowid -- use INSERT ... RETURNING <col> and fetchone()")


_POOL = None


def _pool():
    global _POOL
    if _POOL is None:
        _POOL = psycopg2.pool.ThreadedConnectionPool(1, 20, _dsn())
    return _POOL


class _PGConn:
    """Sqlite3.Connection-lookalike backed by a pooled psycopg2 connection."""
    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        cur = self._conn.cursor()
        cur.execute(sql.replace("?", "%s"), params if params else None)
        return _CursorResult(cur)

    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        cur.close()

    def executemany(self, sql, seq_of_params):
        cur = self._conn.cursor()
        cur.executemany(sql.replace("?", "%s"), list(seq_of_params))
        cur.close()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        # Hand the real connection back to the pool instead of closing the
        # socket -- every call site treats get_conn()/close() as cheap, the
        # way it was with sqlite3, so the pooling stays invisible to them.
        try:
            if self._conn.closed == 0:
                self._conn.rollback()  # drop any uncommitted work, matches
                                       # sqlite3's per-call-site discipline
        except Exception:
            pass
        _pool().putconn(self._conn)


def get_conn() -> _PGConn:
    raw = _pool().getconn()
    schema = _schema()
    cur = raw.cursor()
    cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
    cur.execute(f'SET search_path TO "{schema}", public')
    cur.close()
    raw.commit()
    return _PGConn(raw)


def _existing_columns(conn, table):
    return {r["column_name"] for r in conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = ?", (table,)
    ).fetchall()}


def migrate(conn):
    """Add any v2 columns missing from a v1 database. Safe to run every start."""
    added = []
    for table, cols in MIGRATIONS.items():
        have = _existing_columns(conn, table)
        if not have:
            continue
        for col, ddl in cols.items():
            if col not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")
                added.append(f"{table}.{col}")
    conn.execute(
        "INSERT INTO meta (key, value) VALUES ('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (str(SCHEMA_VERSION),),
    )
    return added


def init_db():
    conn = get_conn()
    conn.executescript(SCHEMA)
    migrate(conn)
    conn.commit()
    conn.close()


def now_iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- upserts

_CHANNEL_COLS = [
    "channel_id", "title", "custom_url", "country", "description", "default_language",
    "subscriber_count", "video_count", "view_count", "thumbnail", "updated_at",
    "published_at", "topic_categories", "keywords", "uploads_playlist", "hidden_subs",
]

_VIDEO_COLS = [
    "video_id", "channel_id", "title", "description", "published_at", "duration_seconds",
    "view_count", "like_count", "comment_count", "thumbnail", "tags", "default_language",
    "embedding", "updated_at", "category_id", "region", "is_short", "topic_categories",
    "live_content",
]


def _upsert(conn, table, pk, cols, row, coalesce=()):
    """Generic upsert keeping NULLs in `coalesce` columns from overwriting data."""
    data = {c: row.get(c) for c in cols}
    placeholders = ",".join(f"%({c})s" for c in cols)
    updates = []
    for c in cols:
        if c == pk:
            continue
        if c in coalesce:
            updates.append(f"{c}=COALESCE(excluded.{c}, {table}.{c})")
        else:
            updates.append(f"{c}=excluded.{c}")
    sql = (
        f"INSERT INTO {table} ({','.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT({pk}) DO UPDATE SET {','.join(updates)}"
    )
    cur = conn._conn.cursor()
    cur.execute(sql, data)
    cur.close()


def upsert_channel(conn, ch: dict):
    ch.setdefault("first_seen_at", ch.get("updated_at") or now_iso())
    conn.execute(
        "INSERT INTO channels (channel_id, first_seen_at) VALUES (?,?) "
        "ON CONFLICT (channel_id) DO NOTHING",
        (ch["channel_id"], ch["first_seen_at"]),
    )
    _upsert(conn, "channels", "channel_id", _CHANNEL_COLS, ch,
            coalesce=("published_at", "topic_categories", "keywords", "uploads_playlist"))


def upsert_video(conn, v: dict):
    v.setdefault("first_seen_at", v.get("updated_at") or now_iso())
    conn.execute(
        "INSERT INTO videos (video_id, first_seen_at) VALUES (?,?) "
        "ON CONFLICT (video_id) DO NOTHING",
        (v["video_id"], v["first_seen_at"]),
    )
    _upsert(conn, "videos", "video_id", _VIDEO_COLS, v,
            coalesce=("embedding", "category_id", "region", "topic_categories", "tags"))


def record_video_stats(conn, video_id, view_count, like_count, comment_count,
                       title=None, thumbnail=None, captured_at=None):
    """Append a stats snapshot and log title/thumbnail changes (1of10-style)."""
    captured_at = captured_at or now_iso()
    prev = conn.execute(
        "SELECT title, thumbnail FROM video_stats_history WHERE video_id=? "
        "ORDER BY captured_at DESC LIMIT 1",
        (video_id,),
    ).fetchone()
    conn.execute(
        "INSERT INTO video_stats_history "
        "(video_id, captured_at, view_count, like_count, comment_count, title, thumbnail) "
        "VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT (video_id, captured_at) DO UPDATE SET "
        "view_count=excluded.view_count, like_count=excluded.like_count, "
        "comment_count=excluded.comment_count, title=excluded.title, "
        "thumbnail=excluded.thumbnail",
        (video_id, captured_at, view_count, like_count, comment_count, title, thumbnail),
    )
    if prev:
        for field, old, new in (("title", prev["title"], title),
                                ("thumbnail", prev["thumbnail"], thumbnail)):
            if old and new and old != new:
                conn.execute(
                    "INSERT INTO video_changes "
                    "(video_id, changed_at, field, old_value, new_value) VALUES (?,?,?,?,?) "
                    "ON CONFLICT (video_id, changed_at, field) DO NOTHING",
                    (video_id, captured_at, field, old, new),
                )


def record_channel_stats(conn, channel_id, subscriber_count, video_count, view_count,
                         captured_at=None):
    conn.execute(
        "INSERT INTO channel_stats_history "
        "(channel_id, captured_at, subscriber_count, video_count, view_count) "
        "VALUES (?,?,?,?,?) "
        "ON CONFLICT (channel_id, captured_at) DO UPDATE SET "
        "subscriber_count=excluded.subscriber_count, video_count=excluded.video_count, "
        "view_count=excluded.view_count",
        (channel_id, captured_at or now_iso(), subscriber_count, video_count, view_count),
    )


def link_video_niche(conn, video_id: str, niche_slug: str):
    conn.execute(
        "INSERT INTO video_niches (video_id, niche_slug) VALUES (?, ?) "
        "ON CONFLICT (video_id, niche_slug) DO NOTHING",
        (video_id, niche_slug),
    )


def upsert_niche(conn, slug: str, query: str, label: str):
    ts = now_iso()
    conn.execute(
        """
        INSERT INTO niches (slug, query, label, created_at, last_collected_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET last_collected_at=excluded.last_collected_at
        """,
        (slug, query, label, ts, ts),
    )


def track_channel(conn, channel_id: str, note: str = None):
    conn.execute(
        "INSERT INTO tracked_channels (channel_id, note, added_at, active) VALUES (?,?,?,1) "
        "ON CONFLICT(channel_id) DO UPDATE SET active=1, note=COALESCE(excluded.note, tracked_channels.note)",
        (channel_id, note, now_iso()),
    )


def untrack_channel(conn, channel_id: str):
    conn.execute("UPDATE tracked_channels SET active=0 WHERE channel_id=?", (channel_id,))


def new_chart_snapshot(conn, region: str, category_id: str, source: str) -> int:
    row = conn.execute(
        "INSERT INTO chart_snapshots (captured_at, region, category_id, source) "
        "VALUES (?,?,?,?) RETURNING snapshot_id",
        (now_iso(), region, category_id, source),
    ).fetchone()
    return row["snapshot_id"]


def add_chart_entry(conn, snapshot_id: int, video_id: str, rank: int, view_count: int):
    conn.execute(
        "INSERT INTO chart_entries (snapshot_id, video_id, rank, view_count) VALUES (?,?,?,?) "
        "ON CONFLICT (snapshot_id, video_id) DO UPDATE SET "
        "rank=excluded.rank, view_count=excluded.view_count",
        (snapshot_id, video_id, rank, view_count),
    )


def upsert_category(conn, category_id, region, title, assignable):
    conn.execute(
        "INSERT INTO video_categories (category_id, region, title, assignable, updated_at) "
        "VALUES (?,?,?,?,?) ON CONFLICT(category_id, region) DO UPDATE SET "
        "title=excluded.title, assignable=excluded.assignable, updated_at=excluded.updated_at",
        (str(category_id), region, title, 1 if assignable else 0, now_iso()),
    )
