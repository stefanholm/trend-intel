"""Breakout pipeline: rank nuggets by trajectory, track predictions for follow-up.

Each cycle:
1. take active nuggets, group them into pytrends batches (max 5 terms)
2. fetch interest_over_time per batch (polite delays)
3. classify rising/steady/peaked/falling, compute hotness
4. store interest_history rows (the prediction record)
5. VERIFY last cycle's 'rising' calls: did interest actually go up?
6. export breakout_snapshot.json for the consumer app

Fallen trends stay in the DB (state=falling, hotness low) so your app can
see the full picture and evaluate our hit-rate.
"""
import json
import random
import time
import logging
from pathlib import Path

from .db import DB
from . import trajectory

log = logging.getLogger("trend_intel.breakout")

DATA = Path(__file__).resolve().parent.parent / "data"


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def record_history(db, title, series):
    state, slope = trajectory.classify(series)
    n = len(series)
    third = max(2, n // 3)
    prev = series[:third]
    recent = series[-third:]
    db._conn().execute(
        "INSERT OR REPLACE INTO interest_history (title, ts, state, slope, recent_mean, prev_mean, series_tail_json) VALUES (?,?,?,?,?,?,?)",
        (title, int(time.time()), state, slope,
         sum(recent) / len(recent), sum(prev) / len(prev),
         json.dumps(series[-6:])))
    db._conn().commit()
    return state, slope


def verify_predictions(db):
    """Check 'rising' calls from the previous cycle against current data.

    Returns {title: {'called': prev_state, 'now': cur_state, 'verdict': hit|miss}}.
    A hit = still rising or steady at high level; a miss = peaked/falling."""
    rows = db._conn().execute(
        "SELECT title, MAX(ts) as last_ts, state FROM interest_history GROUP BY title").fetchall()
    verdicts = {}
    for r in rows:
        cur = db._conn().execute(
            "SELECT state FROM interest_history WHERE title=? ORDER BY ts DESC LIMIT 1",
            (r["title"],)).fetchone()
        # previous state (second-newest entry)
        prev = db._conn().execute(
            "SELECT state FROM interest_history WHERE title=? AND ts < ? ORDER BY ts DESC LIMIT 1",
            (r["title"], r["last_ts"])).fetchone()
        if not prev or not cur:
            continue
        if prev["state"] == "rising":
            verdict = "hit" if cur["state"] in ("rising", "steady") else "miss"
            verdicts[r["title"]] = {
                "called": "rising", "now": cur["state"], "verdict": verdict}
    return verdicts


def run(db, max_batches=8, min_gap=6.0, verbose=False):
    """Returns the breakout list (sorted by hotness desc)."""
    nuggets = db.active_nuggets(limit=200)
    # prioritize: score desc, short titles first (better pytrends subjects)
    nuggets = sorted(nuggets, key=lambda n: -n["score"])[:max_batches * 5]
    terms = [n["title"] for n in nuggets]

    states = {}
    for batch in _chunks(terms, 5):
        if not trajectory.google_available():
            log.warning("google cooling down — skipping remaining batches")
            break
        data = trajectory.fetch_interest(batch)
        for t, series in data.items():
            if len(series) < 4:
                continue
            state, slope = record_history(db, t, series)
            trajectory.record_prediction(db, t, state)
            states[t] = (state, slope)
        time.sleep(random.uniform(min_gap, min_gap * 2))

    verdicts = verify_predictions(db)
    real_track = trajectory.score_track_record(db)

    out = []
    for n in nuggets:
        t = n["title"]
        state, slope = states.get(t, ("unknown", 0.0))
        h = trajectory.hotness(n["score"], state, slope, n.get("seen_count", 1))
        if h is None:
            continue
        out.append({
            "title": t,
            "area_hint": n.get("sources"),
            "state": state,
            "slope": slope,
            "hotness": h,
            "score": n["score"],
            "keywords": n["keywords"],
            "verdict": verdicts.get(t, {}).get("verdict"),
        })
    out.sort(key=lambda x: -x["hotness"])
    return out


def export(out, path=None, verdicts=None):
    path = Path(path or DATA / "breakout_snapshot.json")
    snap = {
        "exported_at": int(time.time()),
        "count": len(out),
        "nuggets": out,
        "prediction_track_record": {
            "calls": real_track["calls"],
            "hits": real_track["hits"],
            "detail": real_track["detail"],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snap, indent=2))
    tmp.replace(path)
    return snap
