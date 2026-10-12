"""Marketplace & trend-site intel sources (all free, all polite).

- explodingtopics.com — embedded trend data with growth %, volume, and full
  search history (best free breakout signal available)
- ebay.com/deals — deal titles (fast-moving consumer products)
- shein.com — homepage-embedded trending product names
- amazon movers-and-shakers — currently bot-blocked; kept as a graceful no-op
  so it starts working if the block lifts
Each source yields dicts: {title, traffic, series, extra} where series is an
optional interest series (Exploding Topics provides one).
"""
import json
import re
import time
import random
import urllib.request
import logging

log = logging.getLogger("trend_intel.marketplaces")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode(
        "utf-8", errors="replace")


def _clean_name(t):
    t = re.sub(r"\s+", " ", t).strip(" ,.-|")
    return t[:80]


# ---------------------------------------------------------------- exploding
def explodingtopics(pages=1):
    """Returns [{title, growth, volume, series}] from embedded page data."""
    out = []
    for page in range(1, pages + 1):
        url = "https://explodingtopics.com/" + (f"?page={page}" if page > 1 else "")
        try:
            body = _get(url)
            i = body.find('__ = {"props"')
            if i < 0:
                continue
            data, _ = json.JSONDecoder().raw_decode(
                body[i + 4:].strip().rstrip(";"))
            pp = data["props"]["pageProps"]
            trends = list(pp.get("trendingDesktopData", {}).get("trends", []))
            trends += list(pp.get("data", {}).get("trends", []))
            seen = set()
            for t in trends:
                kw = t.get("keyword")
                if not kw or kw.lower() in seen:
                    continue
                seen.add(kw.lower())
                hist = t.get("searchHistory") or []
                series = [p.get("value", 0) for p in hist][-24:]
                out.append({
                    "title": kw,
                    "growth": t.get("growth", {}).get("24"),
                    "volume": (t.get("keywordDataGlobal") or {}).get("vol"),
                    "series": series,
                })
        except Exception as e:  # noqa: BLE001
            log.warning("explodingtopics page %s failed: %s", page, e)
        time.sleep(random.uniform(3, 6))
    return out


# ---------------------------------------------------------------- ebay
def ebay_deals():
    out = []
    try:
        body = _get("https://www.ebay.com/deals")
        titles = re.findall(r'"title"\s*:\s*"([^"]{8,90})"', body)
        for t in titles:
            t = _clean_name(t)
            if t and "http" not in t:
                out.append({"title": t, "growth": None, "volume": None,
                            "series": None})
    except Exception as e:  # noqa: BLE001
        log.warning("ebay failed: %s", e)
    return out


# ---------------------------------------------------------------- shein
def shein_home():
    out = []
    try:
        body = _get("https://www.shein.com/")
        names = re.findall(r'"goods_name"\s*:\s*"([^"]{8,90})"', body)
        for t in names:
            t = _clean_name(t)
            if t:
                out.append({"title": t, "growth": None, "volume": None,
                            "series": None})
    except Exception as e:  # noqa: BLE001
        log.warning("shein failed: %s", e)
    return out


# ---------------------------------------------------------------- amazon
def amazon_movers():
    """Amazon bot-blocks plain requests; graceful no-op so the slot exists."""
    try:
        body = _get("https://www.amazon.com/gp/movers-and-shakers")
        if "Oops" in body[:5000]:
            return []
        titles = re.findall(r'p13n-sc-truncate[^>]*>\s*([^<]{5,90})', body)
        return [{"title": _clean_name(t), "growth": None, "volume": None,
                 "series": None} for t in titles if _clean_name(t)]
    except Exception as e:  # noqa: BLE001
        log.warning("amazon failed: %s", e)
    return []


SOURCES = {
    "exploding_topics": explodingtopics,
    "ebay_deals": ebay_deals,
    "shein_home": shein_home,
}


def harvest(db, which=None, verbose=False):
    """Collect from all marketplace sources into raw_items. Returns count."""
    which = which or list(SOURCES)
    count = 0
    for name in which:
        fn = SOURCES[name]
        items = fn() if callable(fn) else []
        for it in items:
            db.upsert_raw(
                source=name,
                title=it["title"],
                external_id=it["title"].lower()[:200],
                traffic=str(it["volume"]) if it.get("volume") else None,
                extra={
                    "growth": it.get("growth"),
                    "series": it.get("series"),
                })
            count += 1
        if verbose:
            print(f"[{name}] {len(items)} items")
        time.sleep(random.uniform(2, 5))
    return count
