"""Read-side search over the local database. Spends zero YouTube quota.

search_outliers() keeps its original signature so existing calls and configs do
not break, but every row now carries the richer metric set from metrics.py:
median-baseline outlier, age-adjusted outlier, views-per-subscriber, velocity
from our own snapshots, and NexLev's own score for comparison.
"""
import statistics as st

import db
import metrics as M
import trends
import categories as C


def search_outliers(query: str = None, niche: str = None, languages: list = None,
                    max_subscribers: int = None, max_channel_video_count: int = None,
                    min_upload_date: str = None, min_outlier_score: float = 0.0,
                    period: str = "all", region: str = None, category_id: str = None,
                    exclude_shorts: bool = False, sort_by: str = "outlier",
                    limit: int = 25) -> list:
    rows = trends.load_window(
        period=period, niche=niche, languages=languages, region=region,
        category_id=category_id, max_subscribers=max_subscribers,
        exclude_shorts=exclude_shorts,
    )
    if min_upload_date:
        rows = [r for r in rows if (r["published_at"] or "") >= min_upload_date]
    if max_channel_video_count is not None:
        rows = [r for r in rows if (r["ch_video_count"] or 0) <= max_channel_video_count]
    if min_outlier_score:
        rows = [r for r in rows
                if (r["outlierScore"] or r["outlierScoreNexlev"] or 0) >= min_outlier_score]

    q_vec = None
    if query:
        import embeddings as emb
        q_vec = emb.embed(query)
        conn = db.get_conn()
        ids = [r["video_id"] for r in rows]
        vecs = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            sql = ("SELECT video_id, embedding FROM videos WHERE video_id IN (%s)"
                   % ",".join("?" * len(chunk)))
            for rec in conn.execute(sql, chunk).fetchall():
                if rec["embedding"]:
                    vecs[rec["video_id"]] = emb.from_blob(rec["embedding"])
        conn.close()
        for r in rows:
            v = vecs.get(r["video_id"])
            r["semanticScore"] = round(emb.cosine(q_vec, v), 4) if v is not None else None

    if q_vec is not None:
        rows.sort(key=lambda r: (r.get("semanticScore") is not None,
                                 r.get("semanticScore") or 0), reverse=True)
    else:
        key = trends.SORTS.get(sort_by, "outlierScore")
        rows.sort(key=lambda r: (r.get(key) is not None, r.get(key) or 0), reverse=True)

    out = []
    for r in rows[:limit]:
        item = trends._video_out(r)
        item["semanticScore"] = r.get("semanticScore")
        out.append(item)
    return out


def niche_overview(niche: str, period: str = "all") -> dict:
    conn = db.get_conn()
    row_niche = conn.execute("SELECT * FROM niches WHERE slug = ?", (niche,)).fetchone()
    conn.close()
    rows = trends.load_window(period=period, niche=niche)
    if not rows:
        return {"niche": niche, "found": False,
                "hint": "nothing collected under this slug yet -- run collect_niche"}

    channels = {}
    for r in rows:
        channels.setdefault(r["channel_id"], r)
    buckets = {"<1k": 0, "1k-10k": 0, "10k-50k": 0, "50k-200k": 0, "200k+": 0}
    for ch in channels.values():
        s = ch["subs"] or 0
        key = ("<1k" if s < 1_000 else "1k-10k" if s < 10_000 else
               "10k-50k" if s < 50_000 else "50k-200k" if s < 200_000 else "200k+")
        buckets[key] += 1

    outliers = [r["outlierScore"] for r in rows if r["outlierScore"]]
    subs = [r["subs"] for r in rows if r["subs"] is not None]
    views = [r["view_count"] or 0 for r in rows]
    cats = {}
    for r in rows:
        cid = str(r["category_id"]) if r["category_id"] else "unknown"
        cats[cid] = cats.get(cid, 0) + 1
    top_cats = sorted(cats.items(), key=lambda kv: -kv[1])[:5]

    small_breakouts = [r for r in rows
                       if (r["subs"] or 0) <= 10000 and r["viewsPerSubscriber"] >= 5]

    return {
        "niche": niche,
        "found": True,
        "period": period,
        "query": row_niche["query"] if row_niche else None,
        "last_collected_at": row_niche["last_collected_at"] if row_niche else None,
        "video_count": len(rows),
        "channel_count": len(channels),
        "median_outlier_score": round(st.median(outliers), 2) if outliers else None,
        "median_subscribers": int(st.median(subs)) if subs else None,
        "median_views_per_video": int(st.median(views)) if views else None,
        "avg_views_per_video": int(st.mean(views)) if views else None,
        "viral_skew": M.skew(views),
        "shorts_share_percent": round(
            sum(1 for r in rows if r["isShort"]) / len(rows) * 100, 1),
        "channel_size_distribution": buckets,
        "saturation_hint": (
            "dominated by big channels -- hard to break in"
            if buckets["200k+"] > len(channels) * 0.4 else
            "plenty of small channels performing -- room to enter"
            if (buckets["<1k"] + buckets["1k-10k"]) > len(channels) * 0.4 else
            "mixed field"),
        "top_categories": [{"categoryId": c, "category": C.title_for(c), "videos": n}
                           for c, n in top_cats],
        "small_channel_breakouts": len(small_breakouts),
        "top_videos_by_outlier_score": [
            {"videoId": r["video_id"], "title": r["title"], "views": r["view_count"],
             "channel": r["channel_title"], "subscribers": r["subs"],
             "outlierScore": r["outlierScore"],
             "viewsPerSubscriber": r["viewsPerSubscriber"]}
            for r in sorted(rows, key=lambda r: r["outlierScore"] or 0, reverse=True)[:5]
        ],
    }


def list_niches() -> list:
    conn = db.get_conn()
    rows = conn.execute(
        """
        SELECT n.*, COUNT(DISTINCT vn.video_id) AS video_count
        FROM niches n LEFT JOIN video_niches vn ON vn.niche_slug = n.slug
        GROUP BY n.slug ORDER BY n.last_collected_at DESC
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def db_stats() -> dict:
    conn = db.get_conn()
    def one(sql):
        return conn.execute(sql).fetchone()[0]
    out = {
        "channels": one("SELECT COUNT(*) FROM channels"),
        "videos": one("SELECT COUNT(*) FROM videos"),
        "niches": one("SELECT COUNT(*) FROM niches"),
        "tracked_channels": one("SELECT COUNT(*) FROM tracked_channels WHERE active=1"),
        "video_stat_snapshots": one("SELECT COUNT(*) FROM video_stats_history"),
        "channel_stat_snapshots": one("SELECT COUNT(*) FROM channel_stats_history"),
        "chart_snapshots": one("SELECT COUNT(*) FROM chart_snapshots"),
        "title_thumbnail_changes": one("SELECT COUNT(*) FROM video_changes"),
        "oldest_video": one("SELECT MIN(published_at) FROM videos"),
        "newest_video": one("SELECT MAX(published_at) FROM videos"),
        "history_since": one("SELECT MIN(captured_at) FROM video_stats_history"),
        "db_path": db.display_dsn(),
    }
    conn.close()
    return out
