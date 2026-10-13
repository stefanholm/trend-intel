"""Trajectory engine: is a trend RISING, PEAKED, or FALLING?

Uses pytrends interest_over_time (0-100 weekly/daily index) per nugget.
Classifies with slope of recent window vs previous window:
    rising  : last-window mean > 1.15 x previous, or series at/near max at the end
    peaked  : max inside series but recent mean dropped > 30% from max
    falling : sustained decline across both windows
    steady  : flat (evergreen — still sellable, not breakout)

Also stores interest history so the agent can VERIFY past predictions
(follow-up): a nugget called 'rising' last cycle should show higher
interest now; if not, the call was wrong and the hit-rate drops.
"""
import time
import logging

log = logging.getLogger("trend_intel.trajectory")

STATE_WEIGHT = {"rising": 1.0, "steady": 0.4, "peaked": 0.1, "falling": 0.0}


# Persistent cooldown: stored in the DB meta table so restarts do NOT reset
# it (launchd KeepAlive restarts the agent; an in-memory timer would be
# wiped every restart and Google would get hammered again).
_COOLDOWN_KEY = "gt_cooldown_until"
_COOLDOUN_COUNT_KEY = "gt_cooldown_count"


def _get_meta(key, default=None):
    try:
        from .db import DEFAULT_DB
        db = DEFAULT_DB.parent.parent / "data" / "intel.db"
        import sqlite3
        c = sqlite3.connect(str(db), timeout=10)
        row = c.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        c.close()
        return row[0] if row else default
    except Exception:  # noqa: BLE001
        return default


def _set_meta(key, value):
    try:
        from .db import DEFAULT_DB
        db = DEFAULT_DB.parent.parent / "data" / "intel.db"
        import sqlite3
        c = sqlite3.connect(str(db), timeout=10)
        c.execute("INSERT INTO meta (key, value) VALUES (?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, str(value)))
        c.commit()
        c.close()
    except Exception:  # noqa: BLE001
        pass


def google_available():
    """False while the 429 circuit-breaker cooldown is active (persistent)."""
    until = float(_get_meta(_COOLDOWN_KEY, "0") or 0)
    return time.time() >= until


def open_cooldown():
    """Escalating cooldown: 1h, 2h, 4h, 8h ... max 24h. Persistent in DB."""
    count = int(_get_meta(_COOLDOUN_COUNT_KEY, "0") or 0)
    hours = min(24, 2 ** count)
    _set_meta(_COOLDOWN_KEY, time.time() + hours * 3600)
    _set_meta(_COOLDOUN_COUNT_KEY, count + 1)
    return hours


def clear_cooldown():
    """Successful fetches reset the escalation counter."""
    _set_meta(_COOLDOWN_KEY, "0")
    _set_meta(_COOLDOUN_COUNT_KEY, "0")


def fetch_interest(terms, timeframe="today 3-m"):
    """terms: up to 5. Returns {term: [values...]} or {} on failure.
    429 / DNS / connection failures open a persistent escalating cooldown."""
    if not google_available():
        return {}
    try:
        from pytrends.request import TrendReq
        from .sources.google_queries import _patch_urllib3_retry
        _patch_urllib3_retry()
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30), retries=2)
        pt.build_payload(terms, timeframe=timeframe)
        df = pt.interest_over_time()
        if df is None or df.empty:
            return {}
        clear_cooldown()
        return {t: [float(v) for v in df[t].tolist()] for t in df.columns if t != "isPartial"}
    except Exception as e:  # noqa: BLE001
        estr = str(e)
        if "429" in estr:
            hours = open_cooldown()
            log.warning("google trends 429 — cooling down %dh (persistent)", hours)
            return {}
        if ("NameResolution" in estr or "Failed to resolve" in estr
                or "gaierror" in estr or "nodename nor servname" in estr):
            hours = open_cooldown()
            log.warning("google trends DNS failure — cooling down %dh (persistent)", hours)
            return {}
        log.warning("interest fetch failed for %s: %s", terms[:2], e)
        return {}


def classify(series):
    """Classify one interest series (list of 0-100 values)."""
    if not series or len(series) < 6:
        return "unknown", 0.0
    n = len(series)
    third = max(2, n // 3)
    prev = series[:third]
    recent = series[-third:]
    p = sum(prev) / len(prev)
    r = sum(recent) / len(recent)
    mx = max(series)
    tail = series[-2:]
    tail_mean = sum(tail) / len(tail)

    if mx > 0 and tail_mean >= 0.85 * mx and r >= p * 1.05:
        return "rising", round((r - p) / max(p, 1), 3)
    if r < 0.85 * p:
        return "falling", round((r - p) / max(p, 1), 3)
    if mx > 0 and tail_mean < 0.7 * mx:
        return "peaked", round((r - p) / max(p, 1), 3)
    return "steady", round((r - p) / max(p, 1), 3)


def hotness(nugget_score, state, slope, seen_count=1):
    """Composite hotness for ranking: base score x trajectory weight x momentum.
    Rising + pre-peak = highest; peaked/falling sink fast so your app can drop them."""
    w = STATE_WEIGHT.get(state, 0.2)
    momentum = max(0.0, min(1.5, 1 + (slope or 0)))
    stickiness = min(1.2, 1 + 0.05 * (seen_count - 1))
    return round(nugget_score * w * momentum * stickiness, 3)


# ---- track record: rising-call predictions stored & scored ----

def record_prediction(db, title, state):
    """Store a trajectory prediction so it can be verified later."""
    import json, time as _t
    try:
        raw = db.get_meta("gt_predictions", "{}")
        preds = json.loads(raw)
    except (ValueError, TypeError):
        preds = {}
    if state == "rising":
        preds.setdefault(title, {"first_called": int(_t.time()),
                                  "calls": 0})
        preds[title]["calls"] += 1
        preds[title]["last_called"] = int(_t.time())
        db.set_meta("gt_predictions", json.dumps(preds))


def score_track_record(db, min_age_days=3):
    """Check stored rising calls against current states: hit = still
    rising/steady after min_age_days, miss = peaked/falling."""
    import json, time as _t
    try:
        preds = json.loads(db.get_meta("gt_predictions", "{}"))
    except (ValueError, TypeError):
        return {"calls": 0, "hits": 0, "detail": {}}
    now = _t.time()
    detail, hits, calls = {}, 0, 0
    for title, p in preds.items():
        age = (now - p.get("first_called", now)) / 86400
        if age < min_age_days:
            continue
        calls += 1
        row = db._conn().execute(
            "SELECT state FROM interest_history WHERE title=? "
            "ORDER BY ts DESC LIMIT 1", (title,)).fetchone()
        cur = row["state"] if row else "unknown"
        ok = cur in ("rising", "steady")
        hits += int(ok)
        detail[title] = {"called": "rising", "now": cur,
                         "verdict": "hit" if ok else "miss",
                         "age_days": round(age, 1)}
    return {"calls": calls, "hits": hits, "detail": detail}
