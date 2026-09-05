"""Pure YouTube-category catalog: id -> title/assignable lookup tables and
the small pure helpers built on them. Zero external deps, no DB, no HTTP --
this is the part of the old categories.py that is genuinely domain logic.

`assignable` matters: videoCategories.list returns legacy ids (18, 21, 30-44)
that can no longer be attached to an upload, so they should never appear in a
"most popular categories" ranking built from real uploads.
"""

# id -> (title, assignable). Stable across regions; titles get localised by hl.
FALLBACK = {
    "1": ("Film & Animation", True),
    "2": ("Autos & Vehicles", True),
    "10": ("Music", True),
    "15": ("Pets & Animals", True),
    "17": ("Sports", True),
    "18": ("Short Movies", False),
    "19": ("Travel & Events", True),
    "20": ("Gaming", True),
    "21": ("Videoblogging", False),
    "22": ("People & Blogs", True),
    "23": ("Comedy", True),
    "24": ("Entertainment", True),
    "25": ("News & Politics", True),
    "26": ("Howto & Style", True),
    "27": ("Education", True),
    "28": ("Science & Technology", True),
    "29": ("Nonprofits & Activism", True),
    "30": ("Movies", False),
    "31": ("Anime/Animation", False),
    "32": ("Action/Adventure", False),
    "33": ("Classics", False),
    "34": ("Comedy", False),
    "35": ("Documentary", False),
    "36": ("Drama", False),
    "37": ("Family", False),
    "38": ("Foreign", False),
    "39": ("Horror", False),
    "40": ("Sci-Fi/Fantasy", False),
    "41": ("Thriller", False),
    "42": ("Shorts", False),
    "43": ("Shows", False),
    "44": ("Trailers", False),
}

# Which categories the mostPopular chart still covers after the July 2025 change.
CHARTED_CATEGORY_IDS = {"10": "Music", "20": "Gaming", "1": "Film & Animation"}

# Rough RPM bucket per category, for metrics.revenue_niche().
CATEGORY_RPM_NICHE = {
    "1": "entertainment", "2": "tech", "10": "music", "15": "entertainment",
    "17": "sports", "19": "travel", "20": "gaming", "22": "entertainment",
    "23": "entertainment", "24": "entertainment", "25": "news", "26": "health",
    "27": "education", "28": "tech", "29": "news",
}


def is_assignable(category_id) -> bool:
    return FALLBACK.get(str(category_id), ("", True))[1]


def rpm_niche(category_id) -> str:
    return CATEGORY_RPM_NICHE.get(str(category_id), "default")


def fallback_title(category_id) -> str:
    """Offline title lookup -- used when there's no DB-cached title yet."""
    if category_id is None:
        return "Unknown"
    cid = str(category_id)
    return FALLBACK.get(cid, (f"Category {cid}", True))[0]
