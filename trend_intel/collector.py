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
from . import scoring, pacing
from .sources import trends_rss, pinterest, google_queries, marketplaces, autocomplete, temu, verticals, gmail_newsletters

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
    cfg = pacing.load_config()
    gentle = cfg["mode"] == "gentle"

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

    # 1. Google Trends RSS (geos rotate in gentle mode)
    geos = None
    if gentle:
        geos = pacing.rotate(trends_rss.GEOS, cfg["rss_geos_per_cycle"],
                             "rss_geo_pos", db)
    n = trends_rss.harvest(db, geos=geos, run_all=verbose)
    results["trends_rss"] = n
    total += n
    pacing.gentle_sleep(cfg["sleep_between_sources"])

    # 2. Pinterest trends
    n = pinterest.harvest(db, run_all=verbose)
    results["pinterest"] = n
    total += n
    pacing.gentle_sleep(cfg["sleep_between_sources"])

    # 3. marketplace sources (rotate in gentle mode)
    msrcs = ["exploding_topics", "ebay_deals", "shein_home"]
    if gentle:
        msrcs = pacing.rotate(msrcs, cfg["source_group_size"], "market_pos", db)
    n = marketplaces.harvest(db, which=msrcs, verbose=verbose)
    results["marketplaces"] = n
    total += n
    pacing.gentle_sleep(cfg["sleep_between_sources"])

    # 3b. temu trending products
    n = temu.harvest(db, verbose=verbose)
    results["temu"] = n
    total += n
    pacing.gentle_sleep(cfg["sleep_between_sources"])

    # 3c-dedicated. vertical harvests: beauty + adult (lexicon-gated,
    # evergreen fallback, never toplist-fed)
    nb = verticals.harvest_beauty(db, verbose=verbose)
    results["beauty_vertical"] = nb
    total += nb
    pacing.gentle_sleep(cfg["sleep_between_requests"])
    na = verticals.harvest_adult(db, verbose=verbose)
    results["adult_vertical"] = na
    total += na
    pacing.gentle_sleep(cfg["sleep_between_requests"])

    # 3c-bis. gmail newsletter intel (optional; no-op without credentials)
    ng = gmail_newsletters.harvest(db, verbose=verbose)
    results["gmail_newsletters"] = ng
    total += ng
    pacing.gentle_sleep(cfg["sleep_between_requests"])

    # 3c. google autocomplete — seeds rotate in gentle mode
    from .areas import area_seeds, seasonal_seeds
    all_seeds = area_seeds() + seasonal_seeds()
    if gentle:
        all_seeds = pacing.rotate(all_seeds, cfg["autocomplete_per_cycle"],
                                  "ac_seed_pos", db)
    n = autocomplete.harvest(db, all_seeds, verbose=verbose)
    results["autocomplete"] = n
    total += n
    pacing.gentle_sleep(cfg["sleep_between_requests"])

    # 4. pytrends related queries (fewer batches in gentle mode)
    seeds = load_seeds()
    if seeds:
        n = google_queries.harvest(
            db, seeds[:cfg["pytrends_batches"] * 5] if gentle else seeds[:10],
            run_all=verbose)
        results["pytrends"] = n
        total += n

    # 5. Build nuggets from everything collected
    stats = scoring.build_nuggets(db)
    results["nuggets"] = stats

    # 6. Manifest shortlist (gate + rank + enrich for the scene layer)
    try:
        from .manifest_gate import export_shortlist
        sl = export_shortlist()
        results["shortlist"] = len(sl["shortlist"])
    except Exception as e:  # noqa: BLE001
        results["shortlist"] = f"error: {e}"

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
