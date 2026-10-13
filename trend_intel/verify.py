"""Cross-source verification: non-Google findings get verified by Google Trends.

A finding from a marketplace/trend site (Exploding Topics, eBay, Shein) starts
provisional: it has a provisional hotness and its origin is recorded.
Provisional findings are queued for Google Trends verification (interest_over_time):
  - VERIFIED: gets a real trajectory (rising/steady/peaked/falling) + real score,
    and the verification is recorded so the consumer app can trust it.
  - UNVERIFIABLE (no Google data): keeps provisional hotness + source; the report
    shows it as unverified so your app weighs it accordingly.
"""
import json
import random
import time
import logging

from . import trajectory

log = logging.getLogger("trend_intel.verify")


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


PRIORITY_AREAS = ["matcha_drinks", "autumn_fashion", "beauty_makeup",
                  "adult_lingerie", "linen_summer", "hairstyles"]


def verify_batch(db, batch_size=5, max_terms=30, min_gap=5.0):
    """Verify provisional nuggets against Google Trends.

    Priority areas verified first (food/fashion/beauty/adult before
    gadgets/travel) so a rate-limit degrades the least important areas."""
    from .areas import match_area
    provisional = [n for n in db.active_nuggets(limit=2000)
                   if any(s != "pytrends_rising" and "trends_rss" not in s
                          for s in n.get("sources", []))]
    prio = [n for n in provisional
            if match_area(n["title"]) in PRIORITY_AREAS]
    rest = [n for n in provisional if n not in prio]
    provisional = (prio + rest)[:max_terms]
    results = []
    for batch in _chunks([p["title"] for p in provisional], batch_size):
        if not trajectory.google_available():
            log.warning("google cooling down — falling back to wikipedia "
                         "pageviews verification for this batch")
            from . import wikipedia_verify
            for t, r in wikipedia_verify.verify_batch(batch).items():
                if r.get("verified"):
                    views = r.get("monthly_views") or []
                    third = max(1, len(views) // 3)
                    r["recent_mean"] = sum(v for _, v in views[-third:]) / third
                    r["prev_mean"] = sum(v for _, v in views[:third]) / third
                results.append(r)
            continue
        data = trajectory.fetch_interest(batch, timeframe="today 3-m")
        for t, series in data.items():
            state, slope = trajectory.classify(series)
            third = max(2, len(series) // 3)
            results.append({
                "title": t, "state": state, "slope": slope,
                "recent_mean": sum(series[-third:]) / third,
                "prev_mean": sum(series[:third]) / third,
                "verified": True,
            })
        for t in batch:
            if t not in data:
                results.append({"title": t, "verified": False})
        time.sleep(random.uniform(min_gap, min_gap * 1.6))
    return results


def apply_verification(db, results):
    """Store verification outcomes into interest_history (state + score basis)."""
    now = int(time.time())
    for r in results:
        if not r.get("verified"):
            continue
        db._conn().execute(
            "INSERT OR REPLACE INTO interest_history "
            "(title, ts, state, slope, recent_mean, prev_mean, series_tail_json) "
            "VALUES (?,?,?,?,?,?,?)",
            (r["title"], now, r["state"], r["slope"],
             r.get("recent_mean"), r.get("prev_mean"), None))
        db._conn().commit()


def provisional_hotness(growth, volume):
    """Hotness for unverified marketplace findings.

    Exploding Topics gives growth % (24-month) + monthly volume — both map to
    a provisional demand proxy so the report can rank them before verification.
    """
    g = growth if isinstance(growth, (int, float)) else 0
    v = volume if isinstance(volume, (int, float)) else 0
    demand = min(1.0, (g / 500.0) * 0.7 + (v / 100000.0) * 0.3 + 0.2)
    momentum = max(0.5, min(1.5, 1 + g / 300.0))
    return round(demand * momentum, 3)
