"""Alerts orchestration (plan item 8.9): the worker calls scan() on a
schedule; it reads whatever collect_*/refresh_stats already stored (zero
YouTube quota), runs the pure detectors in domain/alerts.py, and writes any
NEW events to the `events` table -- "new" meaning no row with the same
(kind, ref_id) exists yet, which is what makes repeated cycles idempotent
without needing a separate "already processed" cursor.
"""
import json

import infrastructure.postgres as db
from application import discovery as trends
from application import channel_tracking as T
from domain import alerts as A

DEFAULT_SILENCE_DAYS = A.SILENCE_DAYS_DEFAULT
DEFAULT_PERIOD = "30d"


def _already_emitted(conn, kind, ref_id) -> bool:
    row = conn.execute(
        "SELECT 1 FROM events WHERE kind=? AND ref_id=? LIMIT 1", (kind, ref_id)
    ).fetchone()
    return row is not None


def _emit(conn, kind, ref_id, payload) -> bool:
    """Insert one event unless (kind, ref_id) already exists. Returns whether
    a new row was written -- the caller uses this to report counts, not to
    make decisions, so a race between two workers double-inserting the same
    (kind, ref_id) is a harmless duplicate row, not a correctness bug."""
    if _already_emitted(conn, kind, ref_id):
        return False
    conn.execute(
        "INSERT INTO events (kind, ref_id, payload, created_at) VALUES (?,?,?,?)",
        (kind, ref_id, json.dumps(payload, ensure_ascii=False), db.now_iso()),
    )
    return True


def _latest_snapshot_at(conn, video_ids: list) -> dict:
    """video_id -> most recent video_stats_history.captured_at, for folding
    into acceleration's dedupe key (see domain/alerts.py docstring)."""
    if not video_ids:
        return {}
    out = {}
    for i in range(0, len(video_ids), 400):
        chunk = video_ids[i:i + 400]
        q = ("SELECT video_id, MAX(captured_at) AS captured_at FROM video_stats_history "
             "WHERE video_id IN (%s) GROUP BY video_id" % ",".join("?" * len(chunk)))
        for r in conn.execute(q, chunk).fetchall():
            out[r["video_id"]] = r["captured_at"]
    return out


def scan(outlier_threshold: float = A.OUTLIER_THRESHOLD_DEFAULT,
        acceleration_threshold: float = A.ACCELERATION_THRESHOLD_DEFAULT,
        silence_days: float = DEFAULT_SILENCE_DAYS, period: str = DEFAULT_PERIOD) -> dict:
    """Run every detector against TRACKED channels only -- alerts are about
    channels you asked to watch, not the whole database. Safe to call every
    worker cycle: see _emit for why repeats never duplicate."""
    tracked = T.list_tracked()
    channel_ids = [c["channel_id"] for c in tracked]
    empty_counts = {"outlier": 0, "acceleration": 0, "title_change": 0, "silence_break": 0}
    if not channel_ids:
        return {"channelsScanned": 0, "videosScanned": 0, "emitted": empty_counts,
                "hint": "no tracked channels -- track_channel first"}

    rows = trends.load_window(period=period, channel_ids=channel_ids)
    conn = db.get_conn()

    snap_at = _latest_snapshot_at(conn, [r["video_id"] for r in rows])
    outlier_rows = [{"video_id": r["video_id"], "title": r["title"],
                     "channel_id": r["channel_id"], "view_count": r["view_count"],
                     "outlier_score": (r.get("outlierScoreAgeAdjusted")
                                       or r.get("outlierScore") or r.get("outlierScoreNexlev"))}
                    for r in rows]
    accel_rows = [{"video_id": r["video_id"], "title": r["title"],
                   "channel_id": r["channel_id"], "acceleration": r.get("acceleration"),
                   "vph24h": r.get("vph24h"), "captured_at": snap_at.get(r["video_id"])}
                  for r in rows if r.get("acceleration") is not None]

    placeholders = ",".join("?" * len(channel_ids))
    tc_rows = [dict(r) for r in conn.execute(
        "SELECT ch.video_id, ch.changed_at, ch.old_value, ch.new_value, v.channel_id "
        "FROM video_changes ch JOIN videos v ON v.video_id = ch.video_id "
        f"WHERE ch.field='title' AND v.channel_id IN ({placeholders})",
        channel_ids).fetchall()]

    upload_rows = conn.execute(
        "SELECT channel_id, video_id, title, published_at FROM videos "
        f"WHERE channel_id IN ({placeholders}) AND published_at IS NOT NULL",
        channel_ids).fetchall()
    channel_uploads = {}
    for r in upload_rows:
        channel_uploads.setdefault(r["channel_id"], []).append(
            (r["published_at"], r["video_id"], r["title"]))

    candidates = {
        "outlier": A.detect_outliers(outlier_rows, threshold=outlier_threshold),
        "acceleration": A.detect_acceleration(accel_rows, threshold=acceleration_threshold),
        "title_change": A.detect_title_changes(tc_rows),
        "silence_break": A.detect_silence_breaks(channel_uploads, silence_days=silence_days),
    }
    emitted = dict(empty_counts)
    for kind, evs in candidates.items():
        for ev in evs:
            if _emit(conn, ev["kind"], ev["refId"], ev["payload"]):
                emitted[kind] += 1
    conn.commit()
    conn.close()
    return {"channelsScanned": len(channel_ids), "videosScanned": len(rows), "emitted": emitted}


def _shape_event(r) -> dict:
    try:
        payload = json.loads(r["payload"]) if r["payload"] else {}
    except (TypeError, ValueError):
        payload = {}
    return {"id": r["id"], "kind": r["kind"], "refId": r["ref_id"], "payload": payload,
           "createdAt": r["created_at"], "seenAt": r["seen_at"]}


def list_events(unseen_only: bool = False, kind: str = None, limit: int = 100) -> list:
    where, params = [], []
    if unseen_only:
        where.append("seen_at IS NULL")
    if kind:
        where.append("kind = ?")
        params.append(kind)
    sql = "SELECT * FROM events"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    conn = db.get_conn()
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [_shape_event(r) for r in rows]


def unseen_count() -> int:
    conn = db.get_conn()
    row = conn.execute("SELECT COUNT(*) AS n FROM events WHERE seen_at IS NULL").fetchone()
    conn.close()
    return (row["n"] if row else 0) or 0


def mark_seen(ids: list = None, all_unseen: bool = False) -> dict:
    conn = db.get_conn()
    now = db.now_iso()
    if all_unseen:
        conn.execute("UPDATE events SET seen_at=? WHERE seen_at IS NULL", (now,))
    elif ids:
        placeholders = ",".join("?" * len(ids))
        conn.execute(f"UPDATE events SET seen_at=? WHERE id IN ({placeholders})", [now, *ids])
    conn.commit()
    conn.close()
    return {"ok": True}
