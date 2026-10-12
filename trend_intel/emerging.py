"""Improvement layer: catch trends EARLY, and diagnose why peaks were missed.

Two mechanisms:

1. EARLY EMERGING detection (leading indicators, before Google Trends volume):
   - Google autocomplete suggestions that are NEW (not in our nuggets) — new
     phrases appear in autocomplete before they show measurable volume
   - Exploding Topics low-volume/high-growth entries (pre-peak by definition)
   - a phrase that appears in BOTH is a strong early signal ("twin signal")

2. MISSED-PEAK diagnosis ("why did I not find this before"):
   - For every NEW verified nugget, examine its interest series for an EARLIER
     acceleration point — the cycle where slope first turned positive
   - If the peak emerged while we weren't tracking it, we record how many
     weeks of lead time existed (lost_lead_weeks) — the improvement metric
   - REBOUND detection: a series that peaked, dipped, and is now re-accelerating
     ("second wave") gets flagged rising_2nd — historically how missed
     breakouts are caught late but still early enough to license
"""
import time
import logging
from .db import DB
from . import trajectory

log = logging.getLogger("trend_intel.emerging")


def detect_early(db):
    """Find twin-signal early-emerging candidates.

    Returns [{title, signals: [..], growth, volume}] sorted by signal count."""
    since = time.time() - 3 * 86400
    recent = db.recent_raw(since=since, limit=5000)
    known = {n["title"].lower() for n in db.active_nuggets(limit=5000)}

    et = {}          # exploding topics items
    ac = {}          # autocomplete suggestions
    for r in recent:
        t = r["title"].strip()
        tl = t.lower()
        if tl in known:
            continue
        if r["source"] == "exploding_topics" and r.get("extra_json"):
            extra = r.get("extra_json") or "{}"
            try:
                import json as _json
                e = _json.loads(extra) if isinstance(extra, str) else extra
            except Exception:  # noqa: BLE001
                e = {}
            et[tl] = {"title": t, "growth": e.get("growth"),
                      "volume": e.get("volume"), "series": e.get("series")}
        elif r["source"] == "google_autocomplete":
            ac[tl] = t

    candidates = []
    for tl, info in et.items():
        signals = ["exploding_topics"]
        if tl in ac:
            signals.append("autocomplete_twin")
        g = info.get("growth")
        v = info.get("volume")
        # early = low absolute volume, high growth (pre-peak breakout)
        if isinstance(g, (int, float)) and isinstance(v, (int, float)):
            if g >= 50 and v <= 50000:
                signals.append("lowvol_highgrowth")
        candidates.append({"title": info["title"], "signals": signals,
                           "growth": g, "volume": v})
    # autocomplete-only new phrases: weaker, single signal
    for tl, t in ac.items():
        if tl not in et:
            candidates.append({"title": t, "signals": ["autocomplete_new"],
                               "growth": None, "volume": None})
    candidates.sort(key=lambda c: -len(c["signals"]))
    return candidates[:40]


def diagnose_missed_peaks(db):
    """For newly verified nuggets, measure lost lead time vs the peak."""
    hist = {}
    for r in db._conn().execute(
            "SELECT title, ts, recent_mean FROM interest_history ORDER BY ts").fetchall():
        hist.setdefault(r["title"], []).append((r["ts"], r["recent_mean"]))
    out = []
    for title, points in hist.items():
        if len(points) < 3:
            continue
        series = [p[1] or 0 for p in points]
        peak = max(series)
        peak_i = series.index(peak)
        first_tracked = points[0][0]
        peak_ts = points[peak_i][0]
        lost_weeks = max(0, (peak_ts - first_tracked) / (7 * 86400))
        out.append({"title": title, "peak_seen_after_weeks": round(lost_weeks, 1),
                    "had_lead_time": lost_weeks > 1})
    return out


def detect_second_wave(series):
    """A series that peaked, dipped >=20%, and is now re-accelerating."""
    if not series or len(series) < 8:
        return False
    mx = max(series)
    mx_i = series.index(mx)
    tail = series[-3:]
    after = series[mx_i:]
    if not after:
        return False
    dip = min(after)
    tail_mean = sum(tail) / len(tail)
    return dip < 0.8 * mx and tail_mean >= 1.1 * dip
