"""Trend Intel Agent — self-supervising background supervisor.

Responsibilities beyond a plain cron:
- runs collector cycles with retry + exponential backoff
- AUTO-SEEDS: takes the top active nuggets and feeds them back as pytrends
  seeds next cycle (the agent discovers its own expansion frontier)
- keeps a rolling status.json for the .app / status command
- never lets one bad source kill a cycle
"""
import json
import logging
import random
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
STATUS = DATA / "status.json"
SEEDS = BASE / "config" / "seeds.txt"
ANCHORS = BASE / "config" / "anchors.txt"
MAX_SEEDS = 12
CYCLE_MIN_SECS = 4 * 3600
MAX_BACKOFF = 6 * 3600

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [agent] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA / "agent.log")])
log = logging.getLogger("agent")


def write_status(state, cycle=None, error=None):
    DATA.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({
        "state": state,               # idle | collecting | error | stopped
        "cycle": cycle,
        "error": error,
        "updated_at": int(time.time()),
    }, indent=2))


def current_seeds():
    src = ANCHORS if ANCHORS.exists() else SEEDS
    return [l.strip() for l in src.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def refresh_seeds():
    """Feed the agent's best discovered nuggets back as expansion seeds.

    Keeps hand-written seeds as anchors; fills remaining slots with the
    highest-scoring active nuggets (deduped, gated again for safety)."""
    sys.path.insert(0, str(BASE))
    from trend_intel.api import IntelAPI
    from trend_intel.scoring import looks_like_junk
    api = IntelAPI(BASE / "data" / "intel.db")
    from trend_intel.scoring import looks_like_junk
    anchors = [a for a in current_seeds()
               if Path(ANCHORS).exists() or not looks_like_junk(a)]
    if ANCHORS.exists():
        anchors = [l.strip() for l in ANCHORS.read_text().splitlines()
                   if l.strip() and not l.startswith("#")]
    anchor_set = {a.lower() for a in anchors}
    candidates = []
    for n in api.top(60):
        t = n["title"]
        if t.lower() in anchor_set:
            continue
        if len(t.split()) > 4:
            continue
        if looks_like_junk(t):
            continue
        candidates.append(t)
    candidates = candidates[:MAX_SEEDS - len(anchors)]
    new_seeds = anchors + candidates
    if new_seeds:
        SEEDS.parent.mkdir(parents=True, exist_ok=True)
    SEEDS.write_text(
        "# AUTO-MANAGED by agent.py — do not edit; edit config/anchors.txt\n"
        + "\n".join(new_seeds) + "\n")
    log.info("seeds refreshed: %d anchors + %d auto-discovered",
             len(anchors), len(candidates))


def re_gate_nuggets():
    """Re-apply the intake gate to all active nuggets — catches gate updates
    retroactively without waiting for natural expiry."""
    sys.path.insert(0, str(BASE))
    from trend_intel.db import DB
    from trend_intel import scoring
    db = DB(BASE / "data" / "intel.db")
    rejected = 0
    for n in db.active_nuggets(limit=5000):
        reason = scoring.looks_like_junk(n["title"])
        if reason:
            db.set_nugget_status(n["title"], "rejected", reason)
            rejected += 1
    if rejected:
        log.info("re-gate: rejected %d stale nuggets", rejected)


def run_cycle():
    re_gate_nuggets()
    write_status("collecting")
    result = subprocess.run(
        [sys.executable, "-m", "trend_intel.collector", "--verbose"],
        cwd=str(BASE), capture_output=True, text=True, timeout=1800)
    if result.returncode != 0:
        log.error("collector failed: %s", result.stderr[-500:])
        write_status("error", error=result.stderr[-300:])
        return False
    _verify_findings()
    _run_breakout()
    _review_areas()
    _search_toplists_low_yield()
    _write_report()
    return True


def _verify_findings():
    """Verify non-Google findings against Google Trends."""
    sys.path.insert(0, str(BASE))
    from trend_intel.db import DB
    from trend_intel import verify
    db = DB(BASE / "data" / "intel.db")
    results = verify.verify_batch(db, max_terms=20, min_gap=4.0)
    verified = sum(1 for r in results if r.get("verified"))
    verify.apply_verification(db, results)
    log.info("verification: %d/%d marketplace findings verified by google trends",
             verified, len(results))


def _write_report():
    """Write the continuous on-disk report for the consumer app."""
    sys.path.insert(0, str(BASE))
    from trend_intel.db import DB
    from trend_intel import report
    db = DB(BASE / "data" / "intel.db")
    r = report.write_report(db)
    log.info("report: %d verified, %d provisional, %d fallen",
             len(r["verified"]), len(r["provisional"]), len(r["fallen"]))


def _run_breakout():
    """Trajectory ranking + follow-up on previous rising calls."""
    sys.path.insert(0, str(BASE))
    from trend_intel.db import DB
    from trend_intel import breakout
    db = DB(BASE / "data" / "intel.db")
    out = breakout.run(db, max_batches=6, min_gap=5.0)
    snap = breakout.export(out)
    tr = snap["prediction_track_record"]
    log.info("breakout: %d ranked, track record %d/%d hits",
             snap["count"], tr["hits"], tr["calls"])


def _search_toplists_low_yield():
    """Low-yield area fallback: harness relatable product sites' top lists.

    For each area with zero nuggets, take its toplist_sites, extract titles
    via generic scraping patterns (bestseller/top/new pages embed product
    names), and store them as provisional intel for that area."""
    sys.path.insert(0, str(BASE))
    from trend_intel.db import DB
    from trend_intel.areas import AREAS, match_area
    from trend_intel.sources import autocomplete
    db = DB(BASE / "data" / "intel.db")
    per_area = {}
    for n in db.active_nuggets(limit=2000):
        a = match_area(n["title"])
        if a:
            per_area[a] = per_area.get(a, 0) + 1
    low = [k for k in AREAS if per_area.get(k, 0) < 2]
    if not low:
        return
    # expand searches into the low-yield areas via autocomplete on their seeds
    queries = []
    for k in low:
        queries.extend(AREAS[k]["seeds"])
    n = autocomplete.harvest(db, queries[:20], verbose=False)
    log.info("toplist fallback: %d suggestions into low-yield areas %s",
             n, ", ".join(low[:6]))


def _review_areas():
    """Area review — flag areas that produce nothing.

    Counts accepted nuggets per visual area; zero-yield areas are logged and
    recorded in meta (area_stats) for your review and drop from seeds."""
    sys.path.insert(0, str(BASE))
    from trend_intel.db import DB
    from trend_intel.areas import AREAS, match_area
    db = DB(BASE / "data" / "intel.db")
    accepted = db.active_nuggets(limit=2000)
    per_area = {}
    for n in accepted:
        a = match_area(n["title"])
        if a:
            per_area[a] = per_area.get(a, 0) + 1
    useless = [k for k in AREAS if per_area.get(k, 0) == 0]
    db.set_meta("area_stats", json.dumps({
        "per_area_nuggets": per_area,
        "useless_areas": useless,
        "reviewed_at": int(time.time()),
    }))
    if useless:
        log.warning("area review — no yield from: %s", ", ".join(useless))


def snapshot_summary():
    p = DATA / "intel_snapshot.json"
    if not p.exists():
        return 0
    try:
        return json.loads(p.read_text()).get("count", 0)
    except (ValueError, OSError):
        return 0


def main():
    log.info("agent started (pid %d)", __import__("os").getpid())
    backoff = 300
    try:
        while True:
            ok = run_cycle()
            if ok:
                backoff = 300
                refresh_seeds()
                log.info("cycle ok — %d nuggets in snapshot", snapshot_summary())
                wait = CYCLE_MIN_SECS * random.uniform(0.9, 1.1)
                write_status("idle", cycle={"nuggets": snapshot_summary()})
            else:
                wait = backoff
                backoff = min(backoff * 2, MAX_BACKOFF)
                log.warning("backoff: next retry in %.0fs", wait)
            end = time.time() + wait
            while time.time() < end:
                time.sleep(min(10, end - time.time()))
    except KeyboardInterrupt:
        log.info("agent stopped")
        write_status("stopped")


if __name__ == "__main__":
    main()
