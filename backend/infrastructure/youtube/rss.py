"""RSS feed for a channel's recent uploads -- no API key, no quota.

YouTube publishes an Atom feed per channel at a fixed URL. It carries only the
~15 most recent uploads and no view/like counts, so it is a *novelty
detector*, not a stats source: the worker reads it first, diffs against what
is already stored, and only spends YouTube Data API quota on videos it has
never seen before. A channel that publishes more than ~15 videos between two
worker cycles falls back to the existing playlist-based path
(application.collecting.collect_channel) for anything the feed missed --
this module never claims to be a complete replacement for it.
"""
import xml.etree.ElementTree as ET

import requests

FEED_URL = "https://www.youtube.com/feeds/videos.xml"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
}


def fetch_channel_feed(channel_id: str, timeout: float = 10.0) -> str:
    """Raw XML. Kept separate from parse_feed() so tests can feed in a fixture
    without touching the network."""
    resp = requests.get(FEED_URL, params={"channel_id": channel_id}, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_feed(xml_text: str) -> list:
    """-> [{videoId, channelId, title, publishedAt}], newest first (YouTube's
    own feed order). Returns [] for anything malformed instead of raising --
    a feed hiccup for one channel should never take down a worker cycle."""
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    out = []
    for entry in root.findall("atom:entry", _NS):
        video_id_el = entry.find("yt:videoId", _NS)
        video_id = video_id_el.text if video_id_el is not None else None
        if not video_id:
            continue
        channel_id_el = entry.find("yt:channelId", _NS)
        title_el = entry.find("atom:title", _NS)
        published_el = entry.find("atom:published", _NS)
        out.append({
            "videoId": video_id,
            "channelId": channel_id_el.text if channel_id_el is not None else None,
            "title": title_el.text if title_el is not None else None,
            "publishedAt": published_el.text if published_el is not None else None,
        })
    return out


def new_video_ids(channel_id: str, known_ids, timeout: float = 10.0) -> list:
    """Video ids present in the channel's feed but not in `known_ids`, oldest
    first -- so a caller that stores them one at a time ends up with a sane
    order in the database."""
    known_ids = set(known_ids or ())
    xml_text = fetch_channel_feed(channel_id, timeout=timeout)
    entries = parse_feed(xml_text)
    fresh = [e["videoId"] for e in entries if e["videoId"] not in known_ids]
    return list(reversed(fresh))
