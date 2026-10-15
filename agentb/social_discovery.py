"""Social-media discovery — Reddit community signal, exception-safe.

Reddit's JSON API blocks bots, but the RSS feeds work. Top weekly posts
from high-signal beauty/intimates communities carry real trend language
('glazed donut nails', 'silk slip dress') weeks before autocomplete
catches up.

NSFW-friendly subs contribute pose/wardrobe/lighting vocabulary — the
discovery gate + stripper in beauty_intel_agent keep only visual nouns
and reject usernames/handles/onlyfans/celebrity content, so what
survives is render language, not profile promotion.

Never raises; each subreddit is isolated. Titles only, low volume.
"""
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0"}

SUBREDDITS = {
    "beauty": [
        "MakeupAddiction", "SkincareAddiction", "AsianBeauty",
        "RedditLaqueristas", "beauty", "HolyMolyBeauty",
    ],
    "adult": [
        "lingerie", "LingerieFashion", "bralette", "stockings",
        "bodysuit", "loungewear", "gonewildcurvy",
    ],
}


def _titles(sub, timeframe="week", limit=15, timeout=8):
    url = f"https://www.reddit.com/r/{sub}/top.rss?t={timeframe}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        root = ET.fromstring(resp.read().decode("utf-8", errors="replace"))
    out = []
    for entry in root.iter():
        tag = entry.tag.split("}")[-1]
        if tag == "title" and entry.text:
            t = re.sub(r"\s+", " ", entry.text).strip()
            if t and not t.lower().startswith(("r/", "[", "mod post")):
                out.append(t)
    return out[:limit]


def harvest(which, max_items=30, run_all=False):
    """Yield trend phrases from top community posts. Never raises."""
    titles = []
    for sub in SUBREDDITS.get(which, [])[:6]:
        try:
            titles.extend(_titles(sub))
        except Exception:  # noqa: BLE001
            continue
        time.sleep(1.2)
    return titles[:max_items]


if __name__ == "__main__":
    print(harvest("beauty")[:5], harvest("adult")[:5])
