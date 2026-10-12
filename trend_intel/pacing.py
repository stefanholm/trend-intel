"""Gentle-mode pacing: low RAM, low intensity, long cycles.

Instead of firing every source every cycle, sources rotate in small groups
with long jittered sleeps. The collector picks up GENTLE env var or
config/gentle.json to decide pacing.
"""
import json
import os
import random
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GENTLE_CONF = BASE / "config" / "gentle.json"

DEFAULTS = {
    "mode": "gentle",            # gentle | normal
    "source_group_size": 2,      # sources per cycle (rotating)
    "autocomplete_per_cycle": 8, # seed queries per cycle (rotating)
    "pytrends_batches": 2,       # 5-term batches per cycle
    "verify_terms": 8,
    "sleep_between_sources": (15, 35),   # jittered seconds
    "sleep_between_requests": (4, 10),
    "cycle_interval_hours": 6,
    "rss_geos_per_cycle": 3,
}


def load_config():
    cfg = dict(DEFAULTS)
    if os.environ.get("TRENDEL_GENTLE") == "0":
        cfg["mode"] = "normal"
    if GENTLE_CONF.exists():
        try:
            cfg.update(json.loads(GENTLE_CONF.read_text()))
        except (ValueError, OSError):
            pass
    return cfg


def gentle_sleep(pair, spread=0.3):
    lo, hi = pair
    time.sleep(random.uniform(lo, hi) * random.uniform(1 - spread, 1 + spread))


def rotate(items, n, state_key, db):
    """Deterministically rotate a list so each cycle takes the next n items.
    Uses meta table to remember position — no RAM growth across cycles."""
    pos = int(db.get_meta(state_key, "0") or 0)
    if not items:
        return []
    start = pos % len(items)
    picked = [items[(start + i) % len(items)] for i in range(min(n, len(items)))]
    db.set_meta(state_key, str((start + n) % max(1, len(items))))
    return picked
