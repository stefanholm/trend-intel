"""Background collector: polls sources politely on a schedule, builds nuggets,
exports a JSON snapshot for the downstream trend-search app.

Run:  python -m trend_intel.collector          (foreground)
      python -m trend_intel.collector --daemon (loop forever, sleep between cycles)
"""
import argparse
import json
import logging
import random
import signal
import sys
import time
from pathlib import Path

from .db import DB, DEFAULT_DB
from . import scoring
from .sources import trends_rss, pinterest, google_queries, marketplaces, autocomplete, temu

PKG_DIR = Path(__file__).resolve().parent
EXPORT_PATH = PKG_DIR.parent / "data" / "intel_snapshot.json"
SEEDS_PATH = PKG_DIR.parent / "config" / "seeds.txt"

log = logging.getLogger("trend_intel")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True
    log.info("signal %s received; finishing current cycle then stopping", signum)


def load_seeds():
    p = Path(SEEDS_PATH)
    if not p.exists():
        return []
    return [l.strip() for l in p.read_text().splitlines()
            if l.strip() and not l.startswith("#")]


def jittered_sleep(base, spread=0.3):
    time.sleep(base * random.uniform(1 - spread, 1 + spread))


def run_cycle(db, verbose=False):
    results = {}

    rid = db.start_run("cycle")
    total = 0

    # re-gate existing nuggets first (gate improvements clean old data)
    from . import scoring as _scoring
    for n in db.active_nuggets(limit=5000):
        reason = _scoring.looks_like_junk(n["title"])
        if reason:
            db.set_nugget_status(n["title"], "rejected", reason)

    # re-gate existing nuggets first (gate improvements clean old data)
    from . import scoring as _scoring
    for n in db.active_nuggets(limit=5000):
        reason = _scoring.looks_like_junk(n["title"])
        if reason:
            db.set_nugget_status(n["title"], "rejected", reason)

    # re-gate existing nuggets first (gate improvements clean old data)
    from . import scoring as _scoring
    for n in db.active_nuggets(limit=5000):
        reason = _scoring.looks_like_junk(n["title"])
        if reason:
            db.set_nugget_status(n["title"], "rejected", reason)

    # 1. Google Trends RSS (many geos, no auth, tolerant)
    n = trends_rss.harvest(db, run_all=verbose)
    results["trends_rss"] = n
    total += n
    jittered_sleep(5)

    # 2. Pinterest trends (lifestyle-rich)
    n = pinterest.harvest(db, run_all=verbose)
    results["pinterest"] = n
    total += n
    jittered_sleep(5)

    # 3. marketplace & trend-site intel (exploding topics, ebay, shein, temu)
    n = marketplaces.harvest(db, which=["exploding_topics", "ebay_deals", "shein_home"], verbose=verbose)
    results["marketplaces"] = n
    total += n
    jittered_sleep(4)

    # 3b. temu trending products
    n = temu.harvest(db, verbose=verbose)
    results["temu"] = n
    total += n
    jittered_sleep(4)

    # 3c. google autocomplete — area + seasonal seeds (leading indicator)
    from .areas import area_seeds, seasonal_seeds
    n = autocomplete.harvest(db, area_seeds() + seasonal_seeds(), verbose=verbose)
    results["autocomplete"] = n
    total += n
    jittered_sleep(2)

    # 4. pytrends related queries (optional, seed-driven)
    seeds = load_seeds()
    if seeds:
        n = google_queries.harvest(db, seeds[:10], run_all=verbose)
        results["pytrends"] = n
        total += n

    # 5. Build nuggets from everything collected
    stats = scoring.build_nuggets(db)
    results["nuggets"] = stats

    db.finish_run(rid, "ok", items=total)
    return results


def export_snapshot(db, path=EXPORT_PATH):
    nuggets = db.active_nuggets()
    snapshot = {
        "exported_at": int(time.time()),
        "count": len(nuggets),
        "nuggets": [
            {
                "title": n["title"],
                "score": n["score"],
                "demand": n["demand"],
                "freshness": n["freshness"],
                "sources": n["sources"],
                "keywords": n["keywords"],
            } for n in nuggets
        ],
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(snapshot, indent=2))
    tmp.replace(path)
    return snapshot


def main():
    ap = argparse.ArgumentParser(description="Trend intel background collector")
    ap.add_argument("--daemon", action="store_true", help="run forever with sleep between cycles")
    ap.add_argument("--interval", type=float, default=4 * 3600, help="cycle interval seconds (default 4h)")
    ap.add_argument("--db", default=str(DEFAULT_DB))
    ap.add_argument("--export", default=str(EXPORT_PATH))
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s")
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    db = DB(args.db)
    log.info("collector started (db=%s)", args.db)

    while True:
        t0 = time.time()
        try:
            results = run_cycle(db, verbose=args.verbose)
            log.info("cycle done: %s", json.dumps(results)[:400])
            snap = export_snapshot(db, args.export)
            log.info("snapshot exported: %d nuggets -> %s", snap["count"], args.export)
        except Exception:  # noqa: BLE001
            log.exception("cycle failed")
        if not args.daemon:
            break
        elapsed = time.time() - t0
        wait = max(60, args.interval - elapsed)
        end = time.time() + wait
        while not _shutdown and time.time() < end:
            time.sleep(min(5, end - time.time()))
        if _shutdown:
            log.info("collector stopped cleanly")
            return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
