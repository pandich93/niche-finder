"""One-time data migration: the old SQLite niches.db -> the new Postgres schema.

Safe to run more than once: every insert uses ON CONFLICT DO NOTHING, so a
second run just skips rows that already made it across. Run it once after
switching db.py over to Postgres and before deleting the old niches.db file.

    python3 migrate_sqlite_to_postgres.py /path/to/niches.db
    python3 migrate_sqlite_to_postgres.py            # defaults to ./niches.db

Postgres connection comes from the same env vars as db.py (NICHE_DATABASE_URL,
or POSTGRES_HOST/PORT/DB/USER/PASSWORD, and NICHE_DB_SCHEMA).
"""
import sys
import sqlite3

import infrastructure.postgres as pgdb

# (table, columns-in-insert-order, conflict-target-columns)
TABLES = [
    ("channels", [
        "channel_id", "title", "custom_url", "country", "description",
        "default_language", "subscriber_count", "video_count", "view_count",
        "thumbnail", "updated_at", "published_at", "topic_categories", "keywords",
        "uploads_playlist", "hidden_subs", "first_seen_at",
    ], ["channel_id"]),
    ("videos", [
        "video_id", "channel_id", "title", "description", "published_at",
        "duration_seconds", "view_count", "like_count", "comment_count",
        "thumbnail", "tags", "default_language", "embedding", "updated_at",
        "category_id", "region", "is_short", "topic_categories", "first_seen_at",
        "live_content",
    ], ["video_id"]),
    ("niches", ["slug", "query", "label", "created_at", "last_collected_at"], ["slug"]),
    ("video_niches", ["video_id", "niche_slug"], ["video_id", "niche_slug"]),
    ("video_stats_history", [
        "video_id", "captured_at", "view_count", "like_count", "comment_count",
        "title", "thumbnail",
    ], ["video_id", "captured_at"]),
    ("channel_stats_history", [
        "channel_id", "captured_at", "subscriber_count", "video_count", "view_count",
    ], ["channel_id", "captured_at"]),
    ("tracked_channels", [
        "channel_id", "note", "added_at", "last_refreshed_at", "active",
    ], ["channel_id"]),
    # chart_snapshots is skipped: its id is a Postgres-side BIGSERIAL, and
    # chart_entries references it by that id, so the pair is migrated together
    # below instead of through the generic loop.
    ("video_changes", [
        "video_id", "changed_at", "field", "old_value", "new_value",
    ], ["video_id", "changed_at", "field"]),
    ("video_categories", [
        "category_id", "region", "title", "assignable", "updated_at",
    ], ["category_id", "region"]),
    ("meta", ["key", "value"], ["key"]),
]


def _existing_sqlite_columns(sconn, table):
    return {r[1] for r in sconn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_table(sconn, pconn, table, cols, conflict_cols):
    have = _existing_sqlite_columns(sconn, table)
    if not have:
        return 0  # table doesn't exist in this sqlite file (old schema version)
    use_cols = [c for c in cols if c in have]
    rows = sconn.execute(f"SELECT {','.join(use_cols)} FROM {table}").fetchall()
    if not rows:
        return 0
    placeholders = ",".join("%s" for _ in use_cols)
    conflict = ",".join(conflict_cols)
    sql = (f"INSERT INTO {table} ({','.join(use_cols)}) VALUES ({placeholders}) "
           f"ON CONFLICT ({conflict}) DO NOTHING")
    cur = pconn._conn.cursor()
    cur.executemany(sql, [tuple(r) for r in rows])
    cur.close()
    return len(rows)


def _migrate_charts(sconn, pconn):
    have = _existing_sqlite_columns(sconn, "chart_snapshots")
    if not have:
        return 0, 0
    snaps = sconn.execute(
        "SELECT snapshot_id, captured_at, region, category_id, source "
        "FROM chart_snapshots"
    ).fetchall()
    n_snaps, n_entries = 0, 0
    for old_id, captured_at, region, category_id, source in snaps:
        # chart_snapshots has no natural unique key of its own (its id is a
        # fresh BIGSERIAL on the Postgres side), so re-running this script
        # would otherwise insert a duplicate snapshot every time -- look for
        # one already migrated with the same (captured_at, region,
        # category_id, source) before creating a new one.
        existing = pconn.execute(
            "SELECT snapshot_id FROM chart_snapshots WHERE captured_at=? "
            "AND region=? AND category_id=? AND source=?",
            (captured_at, region, category_id, source),
        ).fetchone()
        if existing:
            new_id = existing["snapshot_id"]
        else:
            new_id = pconn.execute(
                "INSERT INTO chart_snapshots (captured_at, region, category_id, source) "
                "VALUES (?,?,?,?) RETURNING snapshot_id",
                (captured_at, region, category_id, source),
            ).fetchone()["snapshot_id"]
            n_snaps += 1
        entries = sconn.execute(
            "SELECT video_id, rank, view_count FROM chart_entries WHERE snapshot_id=?",
            (old_id,),
        ).fetchall()
        for video_id, rank, view_count in entries:
            pconn.execute(
                "INSERT INTO chart_entries (snapshot_id, video_id, rank, view_count) "
                "VALUES (?,?,?,?) ON CONFLICT (snapshot_id, video_id) DO NOTHING",
                (new_id, video_id, rank, view_count),
            )
            n_entries += 1
    return n_snaps, n_entries


def migrate(sqlite_path: str):
    sconn = sqlite3.connect(sqlite_path)
    pgdb.init_db()
    pconn = pgdb.get_conn()

    counts = {}
    for table, cols, conflict_cols in TABLES:
        counts[table] = _migrate_table(sconn, pconn, table, cols, conflict_cols)
    counts["chart_snapshots"], counts["chart_entries"] = _migrate_charts(sconn, pconn)

    pconn.commit()
    pconn.close()
    sconn.close()
    return counts


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "niches.db"
    print(f"Migrating {path} -> {pgdb.display_dsn()}")
    result = migrate(path)
    total = sum(result.values())
    for table, n in result.items():
        print(f"  {table:24s} {n}")
    print(f"Done. {total} rows migrated (re-run safely -- ON CONFLICT DO NOTHING).")
