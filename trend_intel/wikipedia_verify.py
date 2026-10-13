"""Wikipedia pageviews fallback verification.

When Google Trends is rate-limited (429 cooldown), provisional nuggets can
still get a REAL trajectory from Wikipedia pageviews — actual human
interest data, free, no auth, no bot-blocking, works from any IP.

Scale: Wikipedia views are encyclopedia interest, not purchase intent —
so the trajectory (rising/steady/peaked/falling) is trustworthy, the
absolute magnitude is NOT comparable to Google Trends volume.

Used as fallback only: trajectory.verify_batch tries Google first;
when google_available() is False, entries are verified here instead.
"""
import json
import re
import time
import logging
import urllib.request
import urllib.parse

log = logging.getLogger("trend_intel.wikipedia_verify")

UA = {"User-Agent": "trend-intel/1.0 (trend verification fallback)"}
MIN_MONTHLY_VIEWS = 1500        # below this the page is too small to trust
MIN_GAP = 1.0                   # seconds between API calls (gentle)

MONTHS = ["january", "february", "march", "april", "may", "june", "july",
          "august", "september", "october", "november", "december"]
SEASONAL_WORDS = re.compile(
    r"\b(christmas|halloween|advent|lucia|midsummer|midsommar|valentine|"
    r"easter|summer|winter|autumn|spring|fall|jul|snow|cozy|hygge)\b", re.I)


def _wiki_title(phrase):
    """Best-guess Wikipedia article title from a trend phrase."""
    t = re.sub(r"[^a-zA-Z0-9 ]", " ", phrase).strip()
    t = re.sub(r"\s+(drink|latte|decor|makeup|nails?|fashion|outfit|style|"
               r"trend|aesthetic|table|styling|look|vibes?|core)\b", "", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip()
    return t.title() if t else None


def fetch_monthly(phrase, months=6):
    """Monthly pageview totals for the phrase's best-guess article.
    Tries the cleaned title first, then progressively drops trailing
    words ("corduroy pants" -> "Corduroy") until a real article is found.
    Returns list of (YYYYMM, views) oldest-first, or None."""
    title = _wiki_title(phrase)
    if not title:
        return None
    words = title.split()
    # casing variants (Wikipedia titles are case-sensitive; opensearch is
    # rate-limit-prone, so we try: title-case, sentence-case, lower)
    def variants(t):
        v = [t, t.lower(), t[0].upper() + t[1:].lower()]
        for i in range(len(t.split()), 0, -1):
            head = " ".join(t.split()[:i])
            v += [head, head.lower(), head[0].upper() + head[1:].lower()]
        return list(dict.fromkeys(v))
    for cand in variants(title):
        got = _fetch_article_monthly(cand, months)
        if got:
            return got
    return None


def _fetch_article_monthly(title, months=6):
    """Raw pageview fetch for one exact article title, or None."""
    if not title:
        return None
    now = time.gmtime()
    start = time.strftime("%Y%m0100", time.gmtime(time.mktime(
        (now.tm_year, max(1, now.tm_mon - months), 1, 0, 0, 0, 0, 0, 0))))
    end = time.strftime("%Y%m%d00", now)
    url = (f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/"
           f"en.wikipedia/all-access/user/{urllib.parse.quote(title, safe='')}"
           f"/daily/{start}/{end}")
    try:
        req = urllib.request.Request(url, headers=UA)
        items = json.loads(urllib.request.urlopen(req, timeout=15).read())["items"]
    except Exception:  # noqa: BLE001  (404 = no such article is normal)
        return None
    if not items:
        return None
    monthly = {}
    for i in items:
        monthly[i["timestamp"][:6]] = monthly.get(i["timestamp"][:6], 0) + i["views"]
    # drop the in-progress month: a partial month skews the last-third mean
    cur = time.strftime("%Y%m")
    monthly.pop(cur, None)
    return sorted(monthly.items()) or None


def classify(monthly):
    """Trajectory classification from monthly totals. Same state vocabulary
    as Google Trends verification so the gate/report treat it identically."""
    if not monthly or len(monthly) < 2:
        return None
    views = [v for _, v in monthly]
    if max(views) < MIN_MONTHLY_VIEWS:
        return None
    third = max(1, len(views) // 3)
    prev = sum(views[:third]) / third
    recent = sum(views[-third:]) / third
    if prev <= 0:
        return None
    slope = (recent - prev) / prev
    peak_i = views.index(max(views))
    if slope >= 0.10:
        return "rising", slope
    if slope <= -0.15:
        # peaked = past max with a tail drop
        if peak_i < len(views) - third:
            return "peaked", slope
        return "falling", slope
    return "steady", slope


def verify_batch(titles, min_gap=MIN_GAP):
    """Wikipedia fallback for a list of titles. Returns {title: result}
    with the same result shape as trajectory verification."""
    out = {}
    for i, t in enumerate(titles):
        monthly = fetch_monthly(t)
        res = classify(monthly)
        if res:
            state, slope = res
            out[t] = {"title": t, "state": state, "slope": slope,
                      "verified": True, "verifier": "wikipedia",
                      "monthly_views": monthly}
        else:
            out[t] = {"title": t, "verified": False, "verifier": "wikipedia"}
        if i < len(titles) - 1:
            time.sleep(min_gap)
    return out


if __name__ == "__main__":
    for phrase in ["matcha", "corduroy", "butter yellow", "nonexistent xyzzy"]:
        monthly = fetch_monthly(phrase)
        print(f"{phrase!r}: {classify(monthly)}  {monthly}")
