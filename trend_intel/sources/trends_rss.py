import re
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

GEOS = ["US", "GB", "SE", "DE", "FR", "CA", "AU", "ES", "IT", "NL", "BR", "JP", "IN", "KR"]

RSS_URL = "https://trends.google.com/trending/rss?geo={geo}"


def fetch(url, timeout=15):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; TrendIntelBot/1.0; +polite; rss-only)",
            "Accept": "application/rss+xml, application/xml, text/xml, */*",
        })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _text(node, tag):
    el = node.find(tag)
    return el.text if el is not None and el.text else None


def _item_id(title, geo):
    return re.sub(r"\s+", " ", (title or "").strip()).lower() + "|" + (geo or "")


def parse_rss(xml_text):
    """Yield dicts: title, url, traffic, approx_traffic, news list."""
    root = ET.fromstring(xml_text)
    ns = {"ht": "https://trends.google.com/trending/rss"}
    out = []
    for item in root.iter("item"):
        title = _text(item, "title")
        if not title:
            continue
        traffic = _text(item, "ht:approx_traffic")
        news = []
        for ni in item.findall("ht:news_item", ns):
            ntitle = _text(ni, "ht:news_item_title")
            nurl = _text(ni, "ht:news_item_url")
            if ntitle:
                news.append({"title": ntitle, "url": nurl})
        out.append({
            "title": title,
            "url": _text(item, "link"),
            "traffic": traffic,
            "news": news[:5],
        })
    return out


def harvest(db, geos=None, run_all=False, **_):
    """Pull Google Trends RSS for each geo. Returns count of items stored."""
    geos = geos or GEOS[:6]
    count = 0
    for geo in geos:
        try:
            xml_text = fetch(RSS_URL.format(geo=geo))
            items = parse_rss(xml_text)
        except Exception as e:  # noqa: BLE001
            if run_all:
                print(f"[rss] {geo}: error {e}")
            continue
        for it in items:
            db.upsert_raw(
                source=f"trends_rss_{geo}",
                title=it["title"],
                external_id=_item_id(it["title"], geo),
                url=it["url"],
                geo=geo,
                traffic=it["traffic"],
                extra={"news": it["news"]},
            )
            count += 1
        if run_all:
            print(f"[rss] {geo}: {len(items)} items")
    return count
