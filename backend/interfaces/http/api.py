"""HTTP API для дашборда. Тонкая обёртка над теми же модулями, что и MCP-сервер --
никакой логики здесь нет, только маршруты и раздача статики фронта.

    uvicorn api:app --host 127.0.0.1 --port 8080
    docker compose up -d web

Разделение по методам осмысленное, а не косметическое: GET ничего не стоит и
читает локальную базу, POST тратит квоту YouTube. Сервис слушает только
127.0.0.1 -- внутри лежит ваш API-ключ, наружу его выставлять незачем.
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Body
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:  # pragma: no cover
    pass

import infrastructure.postgres as db
import infrastructure.youtube.client as yt
from infrastructure.categories import repository as C
from application import collecting as collector
from application import search as Q
from application import discovery as trends
from application import channel_tracking as T

API_KEY = os.environ.get("YOUTUBE_API_KEY", "").strip()
FRONTEND_DIR = Path(os.environ.get("FRONTEND_DIR")
                    or (Path(__file__).parent.parent.parent.parent / "frontend"))
# NOTE: this module now lives two directories deeper than the old flat
# api.py (backend/interfaces/http/ vs backend/), so the fallback path -- only
# used when FRONTEND_DIR is not set, e.g. `make local-run` -- climbs two extra
# levels to keep resolving to <project root>/frontend. Docker always sets
# FRONTEND_DIR=/frontend explicitly, so this only matters for local runs.

db.init_db()
C.seed_fallback()

app = FastAPI(title="niche-finder", docs_url="/api/docs", openapi_url="/api/openapi.json")


def _need_key():
    if not API_KEY:
        raise HTTPException(
            status_code=428,
            detail="YOUTUBE_API_KEY не задан. Впишите его в .env рядом с "
                   "docker-compose.yml и перезапустите: docker compose up -d web",
        )


@app.exception_handler(yt.QuotaExceeded)
async def _quota_exceeded(request, exc):
    return JSONResponse(status_code=429, content={"error": "QuotaExceeded",
                                                  "detail": str(exc)[:800]})


@app.exception_handler(Exception)
async def _unhandled(request, exc):  # pragma: no cover
    msg = str(exc)
    if API_KEY:
        msg = msg.replace(API_KEY, "<KEY>")
    return JSONResponse(status_code=500, content={"error": type(exc).__name__,
                                                  "detail": msg[:800]})


# ------------------------------------------------------------------ статус

@app.get("/api/health")
def health():
    s = Q.db_stats()
    conn = db.get_conn()
    try:
        calls_today = collector.search_calls_today(conn)
    finally:
        conn.close()
    return {
        "ok": True,
        "hasApiKey": bool(API_KEY),
        "db": s,
        "historyAvailable": bool(s["history_since"]),
        "searchQuota": {
            "callsToday": calls_today,
            "dailyLimit": yt.SEARCH_DAILY_CALL_LIMIT,
            "callsLeft": max(0, yt.SEARCH_DAILY_CALL_LIMIT - calls_today),
        },
    }


@app.get("/api/stats")
def stats():
    return Q.db_stats()


@app.get("/api/coverage")
def coverage(period: str = "24h"):
    return trends.coverage(period)


# ------------------------------------------------------------------ разделы

@app.get("/api/viral")
def viral(period: str = "7d", period_by: str = "published",
          max_subscribers: int = 10000, min_views: int = 10000,
          min_views_per_subscriber: float = 1.0,
          min_outlier_score: float = None, niche: str = None,
          region: str = None, category_id: str = None,
          exclude_shorts: bool = True, only_shorts: bool = False,
          sort_by: str = "viral", limit: int = 24):
    return trends.viral_videos_small_channels(
        period=period, period_by=period_by, max_subscribers=max_subscribers,
        min_views=min_views, min_views_per_subscriber=min_views_per_subscriber,
        min_outlier_score=min_outlier_score, niche=niche, region=region,
        category_id=category_id, exclude_shorts=exclude_shorts,
        only_shorts=only_shorts, sort_by=sort_by, limit=limit)


@app.get("/api/categories")
def categories(period: str = "7d", period_by: str = "published", niche: str = None,
               region: str = None, rank_by: str = "views",
               exclude_shorts: bool = False, min_videos: int = 1, limit: int = 25):
    return trends.most_popular_categories(
        period=period, period_by=period_by, niche=niche, region=region,
        rank_by=rank_by, exclude_shorts=exclude_shorts, min_videos=min_videos,
        limit=limit)


@app.get("/api/keywords")
def keywords(period: str = "24h", period_by: str = "published", niche: str = None,
             region: str = None, category_id: str = None, source: str = "both",
             sort_by: str = "momentum", min_videos: int = 2, top_n: int = 30):
    return trends.trending_keywords(
        period=period, period_by=period_by, niche=niche, region=region,
        category_id=category_id, source=source, sort_by=sort_by,
        min_videos=min_videos, top_n=top_n)


@app.get("/api/outlier-channels")
def outlier_channels(period: str = "24h", period_by: str = "discovered",
                     min_multiplier: float = 2.0, max_subscribers: int = None,
                     niche: str = None, limit: int = 25):
    return T.recently_added_outlier_channels(
        period=period, period_by=period_by, min_multiplier=min_multiplier,
        max_subscribers=max_subscribers, niche=niche, limit=limit)


@app.get("/api/competition")
def competition(period: str = "30d", niche: str = None, limit: int = 15):
    return T.high_future_competition(period=period, niche=niche, limit=limit)


@app.get("/api/search")
def search(query: str = None, niche: str = None, period: str = "all",
           min_outlier_score: float = 0.0, max_subscribers: int = None,
           sort_by: str = "outlier", limit: int = 30):
    return {"results": Q.search_outliers(
        query=query or None, niche=niche, period=period,
        min_outlier_score=min_outlier_score, max_subscribers=max_subscribers,
        sort_by=sort_by, limit=limit)}


@app.get("/api/overview")
def overview(period: str = "24h", niche: str = None):
    """Всё для главной одним запросом -- иначе страница делает шесть.

    Периоды разные намеренно: 24h для того, что действительно обновляется за
    сутки, и более широкие окна для срезов, которым нужна статистика.
    """
    wide = "30d" if period in ("1h", "6h", "24h", "48h") else period
    return {
        "period": period,
        "widePeriod": wide,
        "coverage": trends.coverage(period),
        "stats": Q.db_stats(),
        "outlierChannels": T.recently_added_outlier_channels(
            period=period, period_by="discovered", min_multiplier=1.5,
            niche=niche, limit=6),
        "competition": T.high_future_competition(period=wide, niche=niche, limit=6),
        "keywords": trends.trending_keywords(
            period=period, niche=niche, min_videos=2, top_n=12, sort_by="trend"),
        "categories": trends.most_popular_categories(
            period=period, niche=niche, rank_by="channels", min_videos=1, limit=8),
        "viral": trends.viral_videos_small_channels(
            period=period, period_by="discovered", niche=niche,
            max_subscribers=100000, min_views=1000,
            min_views_per_subscriber=0.5, limit=8),
    }


# ------------------------------------------------------------------ каналы

@app.get("/api/niches")
def niches():
    return {"niches": Q.list_niches()}


@app.get("/api/niches/{slug}")
def niche_detail(slug: str, period: str = "all"):
    return Q.niche_overview(slug, period=period)


@app.get("/api/channels/tracked")
def tracked():
    return {"channels": T.list_tracked()}


@app.get("/api/channels/{channel_id}")
def channel(channel_id: str, period: str = "30d"):
    res = T.channel_analytics(channel_id, period=period)
    if not res.get("found"):
        raise HTTPException(status_code=404, detail=res.get("hint", "канал не найден"))
    return res


@app.get("/api/channels/{channel_id}/velocity")
def channel_velocity(channel_id: str, period: str = "30d", limit: int = 25):
    return T.channel_velocity(channel_id, period=period, limit=limit)


@app.get("/api/channels/{channel_id}/history")
def channel_history(channel_id: str, limit: int = 400):
    return T.channel_history(channel_id, limit=limit)


@app.get("/api/channels/{channel_id}/similar")
def similar_channels(channel_id: str, niche: str = None, limit: int = 10):
    return Q.similar_channels(channel_id, niche=niche, limit=limit)


@app.get("/api/title-changes")
def title_changes(period: str = "7d", channel_id: str = None, limit: int = 50):
    return T.title_changes(period=period, channel_id=channel_id, limit=limit)


@app.get("/api/best-time")
def best_time(niche: str = None, channel_id: str = None, period: str = "90d",
              min_samples: int = 2, timezone_offset_hours: int = 0):
    return T.best_time_to_publish(niche=niche, channel_id=channel_id, period=period,
                                  min_samples=min_samples,
                                  timezone_offset_hours=timezone_offset_hours)


@app.get("/api/title-patterns")
def title_patterns(niche: str = None, channel_id: str = None, period: str = "90d",
                   min_videos: int = 3, top_n: int = 20):
    return T.title_patterns(niche=niche, channel_id=channel_id, period=period,
                            min_videos=min_videos, top_n=top_n)


# ------------------------------------------- операции, которые тратят квоту

@app.post("/api/collect/channel")
def collect_channel(payload: dict = Body(...)):
    _need_key()
    ref = (payload.get("channel") or "").strip()
    if not ref:
        raise HTTPException(status_code=400, detail="нужно поле channel")
    res = collector.collect_channel(API_KEY, ref,
                                    max_videos=int(payload.get("max_videos", 100)),
                                    niche=payload.get("niche") or None)
    if res.get("error"):
        raise HTTPException(status_code=404, detail=res["error"])
    if payload.get("track"):
        T.track(res["channelId"], payload.get("note"))
        res["tracked"] = True
    return res


@app.post("/api/collect/niche")
def collect_niche(payload: dict = Body(...)):
    _need_key()
    q = (payload.get("query") or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="нужно поле query")
    return collector.collect_niche(
        API_KEY, q, label=payload.get("label") or None,
        language=payload.get("language") or None,
        period=payload.get("period") or None,
        region=payload.get("region") or None,
        pages=int(payload.get("pages", 1)))


@app.post("/api/refresh")
def refresh(payload: dict = Body(default={})):
    _need_key()
    stats_res = collector.refresh_stats(API_KEY, scope=payload.get("scope", "recent"),
                                        period=payload.get("period", "30d"),
                                        limit=int(payload.get("limit", 1000)))
    chan_res = collector.refresh_channels(API_KEY, only_tracked=True)
    return {"videos": stats_res, "channels": chan_res}


@app.post("/api/videos/{video_id}/comments")
def video_comments(video_id: str, payload: dict = Body(default={})):
    _need_key()
    return collector.video_comments(
        API_KEY, video_id, max_results=int(payload.get("max_results", 100)),
        order=payload.get("order", "relevance"))


@app.post("/api/channels/track")
def track(payload: dict = Body(...)):
    cid = (payload.get("channel_id") or "").strip()
    if not cid:
        raise HTTPException(status_code=400, detail="нужно поле channel_id")
    return T.track(cid, payload.get("note"))


@app.delete("/api/channels/tracked/{channel_id}")
def untrack(channel_id: str):
    return T.untrack(channel_id)


# ---------------------------------------------------------------- статика

@app.middleware("http")
async def _no_cache_static(request, call_next):
    """Локальный дашборд правят на живую, поэтому кэш браузера тут только мешает:
    поправил styles.css — перезагрузил страницу и сразу видишь результат."""
    response = await call_next(request)
    if not request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
else:  # pragma: no cover
    @app.get("/")
    def _no_frontend():
        return {"error": f"Папка фронта не найдена: {FRONTEND_DIR}",
                "hint": "Задайте FRONTEND_DIR или смонтируйте ./frontend в контейнер"}
