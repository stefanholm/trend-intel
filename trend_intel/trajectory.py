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


_cooldown_until = 0


def google_available():
    """False while the 429 circuit-breaker cooldown is active."""
    return time.time() >= _cooldown_until


def fetch_interest(terms, timeframe="today 3-m"):
    """terms: up to 5. Returns {term: [values...]} or {} on failure.
    On a 429, opens a 1-hour cooldown so the whole cycle stops hammering."""
    global _cooldown_until
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
        return {t: [float(v) for v in df[t].tolist()] for t in df.columns if t != "isPartial"}
    except Exception as e:  # noqa: BLE001
        if "429" in str(e):
            _cooldown_until = time.time() + 3600
            log.warning("google trends 429 — cooling down 1h")
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
