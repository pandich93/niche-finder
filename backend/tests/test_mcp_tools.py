"""Tests for the MCP tool layer (interfaces/mcp/server.py) and the search-quota
accounting it depends on. Run with pytest, or directly: python3 tests/test_mcp_tools.py

Same throwaway-schema setup as test_smoke.py -- no YouTube API key and no
network required (comment_threads is monkeypatched).
"""
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
os.environ.setdefault("NICHE_DB_SCHEMA", f"nichetest_{uuid.uuid4().hex[:8]}")

import infrastructure.postgres as db              # noqa: E402
import infrastructure.youtube.client as yt         # noqa: E402
from domain import periods as P                    # noqa: E402
from infrastructure.categories import repository as C  # noqa: E402
from application import collecting as collector    # noqa: E402
from application import discovery as trends        # noqa: E402
from application import search as query            # noqa: E402
from application import worker_cycle as worker     # noqa: E402
import interfaces.mcp.server as srv                # noqa: E402


def setup_module(_=None):
    db.init_db()
    C.seed_fallback()
    srv.API_KEY = "test-key"


# --------------------------------------------------- persistent search quota

def test_search_calls_accumulate_across_calls_same_day():
    conn = db.get_conn()
    before = collector.search_calls_today(conn)
    collector._record_search_calls(conn, 3)
    collector._record_search_calls(conn, 2)
    conn.commit()
    after = collector.search_calls_today(conn)
    conn.close()
    assert after == before + 5


def test_quota_reports_daily_total_not_just_this_call():
    conn = db.get_conn()
    collector._record_search_calls(conn, 10)
    conn.commit()
    calls_today = collector.search_calls_today(conn)
    conn.close()
    q = collector._quota(search_calls=1, n_videos=0, n_channels=0, calls_today=calls_today)
    assert q["search_calls"] == 1
    assert q["search_calls_today"] == calls_today
    assert q["search_calls_left_today"] == max(0, yt.SEARCH_DAILY_CALL_LIMIT - calls_today)


def test_db_stats_exposes_search_quota_and_worker_flag():
    s = query.db_stats()
    assert "search_quota" in s
    assert s["search_quota"]["search_calls_left_today"] <= yt.SEARCH_DAILY_CALL_LIMIT
    assert "worker_quota_blocked_until" in s


def test_data_coverage_exposes_search_quota():
    cov = trends.coverage(period="30d")
    assert "searchCallsToday" in cov
    assert "searchCallsLeftToday" in cov


# --------------------------------------------------- worker quota backoff

def test_worker_blocked_flag_is_read_not_just_written():
    conn = db.get_conn()
    db.set_meta(conn, "worker_quota_blocked_until", P.pacific_date_key())
    conn.commit()
    conn.close()
    assert worker._search_quota_blocked_today() is True

    conn = db.get_conn()
    db.set_meta(conn, "worker_quota_blocked_until", "2000-01-01")
    conn.commit()
    conn.close()
    assert worker._search_quota_blocked_today() is False


# --------------------------------------------------- video_comments MCP tool

def test_video_comments_tool_shapes_raw_comments(monkeypatch):
    fake_items = [
        {
            "snippet": {
                "totalReplyCount": 2,
                "topLevelComment": {"snippet": {
                    "authorDisplayName": "@viewer1",
                    "textDisplay": "great video",
                    "likeCount": 5,
                    "publishedAt": "2026-01-01T00:00:00Z",
                }},
            }
        },
    ]
    monkeypatch.setattr(yt, "comment_threads", lambda *a, **k: fake_items)
    out = srv.video_comments("vid123")
    assert out["video_id"] == "vid123"
    assert out["count"] == 1
    c = out["comments"][0]
    assert c == {
        "author": "@viewer1", "text": "great video", "likeCount": 5,
        "publishedAt": "2026-01-01T00:00:00Z", "replyCount": 2,
    }


# --------------------------------------------------- similar_channels

def test_similar_channels_without_embeddings_gives_a_hint():
    conn = db.get_conn()
    db.upsert_channel(conn, {
        "channel_id": "UCnoembed00000000000000", "title": "No Embeddings Channel",
        "custom_url": None, "country": None, "description": "", "default_language": None,
        "subscriber_count": 1000, "video_count": 10, "view_count": 100000,
        "thumbnail": None, "published_at": None, "topic_categories": None,
        "keywords": None, "uploads_playlist": None, "hidden_subs": 0,
    })
    conn.commit()
    conn.close()
    out = srv.similar_channels("UCnoembed00000000000000")
    assert out["similar"] == []
    assert "hint" in out


def test_similar_channels_ranks_by_cosine_similarity():
    import infrastructure.embeddings.fastembed_provider as emb

    conn = db.get_conn()
    for cid in ("UCtarget0000000000000000", "UCclose00000000000000000",
                "UCfar000000000000000000"):
        db.upsert_channel(conn, {
            "channel_id": cid, "title": cid, "custom_url": None, "country": None,
            "description": "", "default_language": None, "subscriber_count": 1000,
            "video_count": 1, "view_count": 1000, "thumbnail": None,
            "published_at": None, "topic_categories": None, "keywords": None,
            "uploads_playlist": None, "hidden_subs": 0,
        })

    def video_row(video_id, channel_id, text):
        return {
            "video_id": video_id, "channel_id": channel_id, "title": text,
            "description": "", "published_at": "2026-01-01T00:00:00Z",
            "duration_seconds": 600, "view_count": 1000, "like_count": 10,
            "comment_count": 1, "thumbnail": None, "tags": "[]",
            "default_language": "en", "embedding": emb.to_blob(emb.embed(text)),
            "updated_at": "2026-01-01T00:00:00Z", "category_id": None,
            "region": None, "is_short": 0, "topic_categories": None,
            "live_content": None,
        }

    db.upsert_video(conn, video_row("vtarget1", "UCtarget0000000000000000",
                                    "faceless space exploration documentary"))
    db.upsert_video(conn, video_row("vclose1", "UCclose00000000000000000",
                                    "faceless space exploration documentary"))
    db.upsert_video(conn, video_row("vfar1", "UCfar000000000000000000",
                                    "recipe for chocolate chip cookies"))
    conn.commit()
    conn.close()

    out = srv.similar_channels("UCtarget0000000000000000", limit=5)
    ids = [c["channelId"] for c in out["similar"]]
    assert ids[0] == "UCclose00000000000000000"
    assert ids.index("UCclose00000000000000000") < ids.index("UCfar000000000000000000")


def test_video_comments_requires_api_key(monkeypatch):
    monkeypatch.setattr(srv, "API_KEY", None)
    try:
        srv.video_comments("vid123")
    except RuntimeError as e:
        assert "YOUTUBE_API_KEY" in str(e)
    else:
        raise AssertionError("expected RuntimeError without an API key")


if __name__ == "__main__":
    setup_module()

    class _Monkeypatch:
        def __init__(self):
            self._undo = []

        def setattr(self, obj, name, value):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, value)

        def undo(self):
            for obj, name, value in reversed(self._undo):
                setattr(obj, name, value)

    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for fn in fns:
        mp = _Monkeypatch()
        try:
            if "monkeypatch" in fn.__code__.co_varnames[:fn.__code__.co_argcount]:
                fn(mp)
            else:
                fn()
            print(f"  PASS  {fn.__name__}")
        except Exception as e:
            failed += 1
            import traceback
            print(f"  FAIL  {fn.__name__}: {e}")
            traceback.print_exc()
        finally:
            mp.undo()
    print(f"\n{len(fns) - failed}/{len(fns)} passed")
