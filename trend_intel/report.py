"""Continuous on-disk REPORT for the consumer trend-search app.

Writes data/intel_report.json — atomically, updated after every pipeline
stage (collect / verify / breakout), so the consuming app always finds a
fresh, consistent document. Schema:

{
  "updated_at": ts,
  "areas": {area_key: {label, why, nugget_count, useful}},
  "verified":   [ {title, state, slope, hotness, score, sources, area} ],   # Google Trends-backed
  "provisional":[ {title, hotness, sources, area, growth, volume} ],        # not yet verified
  "fallen":     [ {title, last_state, slope} ],                             # trends to drop
  "track_record": {"calls": n, "hits": n, "detail": {...}},
  "sources": {source_name: items_collected}
}
"""
import json
import time
from pathlib import Path

from .db import DB
from .areas import AREAS, match_area, CATEGORY_OF_AREA
from . import emerging as emerging_mod
from .cluster import cluster_titles

DATA = Path(__file__).resolve().parent.parent / "data"
REPORT = DATA / "intel_report.json"


def _failure_learning_block():
    """Learned bans/fixes from the render app's QC reports — same report as
    everything else so consumers read one file."""
    try:
        from . import failure_learning
        return failure_learning.report_block()
    except Exception:  # noqa: BLE001
        return {"n_rows": 0, "note": "failure-learning unavailable"}


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def write_report(db, path=REPORT):
    nuggets = db.active_nuggets(limit=2000)

    # last known trajectory per title
    hist = {}
    for r in db._conn().execute(
            "SELECT title, state, slope FROM interest_history "
            "ORDER BY ts ASC").fetchall():
        hist[r["title"]] = (r["state"], r["slope"])

    from .trajectory import hotness, STATE_WEIGHT
    verified, provisional, fallen = [], [], []
    for n in nuggets:
        title = n["title"]
        state, slope = hist.get(title, ("unknown", 0.0))
        srcs = n.get("sources", [])
        is_google = any("trends_rss" in s or "pytrends" in s for s in srcs)
        area = match_area(title)
        # demand proxy: approx traffic (RSS) or pytrends value, from raw rows
        extra = {}
        for r in db.recent_raw(since=int(time.time()) - 14 * 86400, limit=3000):
            if r["title"].lower() == title.lower():
                extra = r
                break
        approx = extra.get("approx_traffic")
        src_count = len(set(srcs))
        is_verified = bool(is_google or state in ("rising", "steady", "peaked", "falling"))
        entry = {
            "title": title,
            "hotness": hotness(n["score"], state, slope, n.get("seen_count", 1)),
            "score": n["score"],
            "demand": n.get("demand"),
            "freshness": n.get("freshness"),
            "approx_traffic": approx,
            "sources": srcs,
            "source_count": src_count,
            "verified_by_google_trends": is_verified,
            "verification_state": state,
            "slope": slope,
            "seen_count": n.get("seen_count", 1),
            "first_seen": n.get("created_at"),
            "area": area,
            "state": state,
        }
        # gate-classify every entry: shot directives travel with the report so
        # consumers never see a raw lead without a shot class (V68.5)
        try:
            from .manifest_gate import (image_need, prop_hero, setting_hint,
                                      people_hands)
            t_clean = entry["title"]
            entry["image_need"] = image_need(t_clean)
            entry["prop_hero"] = prop_hero(t_clean)
            entry["setting_hint"] = setting_hint(t_clean)
            entry["people_hands"] = people_hands(t_clean)
            entry["buyer_use"] = {
                "Macro drink": "cafe menus / delivery app hero",
                "Beauty detail": "cosmetics campaign / tutorial",
                "SFW intimates": "apparel lookbook / brand campaign",
                "Environment worn apparel": "fashion lookbook / autumn editorial",
                "Environment interior": "furniture retail / home staging",
                "Product still-life": "ecommerce / craft brand",
            }.get(entry["image_need"], "lifestyle campaign")
        except Exception:  # noqa: BLE001
            pass
        if state == "falling":
            fallen.append(entry)
        elif is_google or state in ("rising", "steady", "peaked"):
            verified.append(entry)
        else:
            provisional.append(entry)

    verified.sort(key=lambda x: -x["hotness"])
    provisional.sort(key=lambda x: -x["hotness"])

    # areas summary with usefulness flags AND the actual trends inside each
    per_area = {}
    area_items = {}
    for e in verified + provisional:
        a = e.get("area")
        if a:
            per_area[a] = per_area.get(a, 0) + 1
            area_items.setdefault(a, []).append(e)
    areas = {}
    for k, v in AREAS.items():
        items = cluster_titles(area_items.get(k, []))
        areas[k] = {
            "label": v["label"],
            "why": v["why"],
            "nugget_count": per_area.get(k, 0),
            "useful": per_area.get(k, 0) > 0,
            "trends": items[:15],
        }
        # keep provenance fields on clustered heads
        for i, item in enumerate(areas[k]["trends"]):
            src_entry = next((e for e in area_items.get(k, [])
                              if e["title"] == item["title"]), {})
            for fld in ("demand", "approx_traffic", "source_count",
                        "verified_by_google_trends", "seen_count", "first_seen"):
                if fld in src_entry:
                    item[fld] = src_entry[fld]

    # track record from breakout snapshot
    bo = _load(DATA / "breakout_snapshot.json")
    tr = bo.get("prediction_track_record", {"calls": 0, "hits": 0, "detail": {}})

    # early-emerging candidates + missed-peak diagnostics (improvement layer)
    emerging = emerging_mod.detect_early(db)
    missed = emerging_mod.diagnose_missed_peaks(db)

    # category sections: verified+provisional grouped per report category
    categories = {}
    for cat, area_keys in CATEGORY_OF_AREA.items():
        entries = [v for v in verified if v.get("area") in area_keys]
        prov = [p for p in provisional if p.get("area") in area_keys]
        categories[cat] = {
            "trends": cluster_titles(entries)[:15],
            "provisional": prov[:10],
            "area_yields": {a: per_area.get(a, 0) for a in area_keys},
        }

    # source counts from last run window
    sources = {}
    for r in db._conn().execute(
            "SELECT source, COUNT(*) c FROM raw_items WHERE last_seen > ? "
            "GROUP BY source", (int(time.time()) - 86400,)).fetchall():
        sources[r["source"]] = r["c"]

    # explicit data-quality block: what is GT-validated vs provisional
    total = len(verified) + len(provisional)
    v = sum(1 for e in verified if e.get("verified_by_google_trends"))
    gt_ok = True
    try:
        from .trajectory import google_available
        gt_ok = google_available()
    except Exception:  # noqa: BLE001
        pass
    data_quality = {
        "google_trends_available": gt_ok,
        "note": "verified_by_google_trends=false entries are source-signal "
                "only (autocomplete/marketplace). They carry hotness but NOT "
                "a Google-measured trajectory. Treat as provisional.",
        "total_trends": total,
        "gt_verified_count": v,
        "provisional_count": len(provisional),
        "fallen_count": len(fallen),
    }

    report = {
        "updated_at": int(time.time()),
        "data_quality": data_quality,
        "failure_learning": _failure_learning_block(),
        "legend": {
            "hotness": "0-1 composite: base score x trajectory weight (rising 1.0, steady 0.4, peaked 0.1, falling 0.0) x momentum x stickiness. USE THIS for ranking.",
            "score": "0-1 intake score: 0.6*demand + 0.3*freshness + 0.1*multi-source corroboration. Demand-dominated.",
            "demand": "0-1 demand proxy component (search volume / pytrends value).",
            "freshness": "0-1 recency: 1.0 first seen <24h, decays to 0 over 14 days.",
            "approx_traffic": "Raw search-volume estimate from Google Trends RSS when present (e.g. 200000 = 200K+/mo), else null.",
            "state": "Trajectory from Google Trends interest-over-time: rising (at/near max NOW, climbing) | steady (evergreen) | peaked (past max, tail dropped >30%) | falling (sustained decline >=15%) | unknown (not yet verified).",
            "slope": "Relative interest change: (recent_third - earlier_third) / earlier_third. +0.5 = 50% hotter recently.",
            "verified_by_google_trends": "true = interest-over-time fetched and state measured. false = provisional (source signal only, awaiting verification).",
            "source_count": "How many independent sources carry this trend. 2+ = corroboration.",
            "seen_count": "Times this trend reappeared across harvest cycles. Higher = persistent.",
            "first_seen": "Unix timestamp when first collected.",
            "variant_count": "Near-duplicate queries clustered under this head (same core terms). Indicates how many ways people search it.",
            "areas": "Visual categories with sell rationale; useful=false means no clean nuggets yet.",
            "categories": "Same trends grouped: fashion, beauty, interiors, food_drinks, lifestyle.",
            "emerging_early": "Twin-signal early candidates (autocomplete + exploding topics) BEFORE Google volume appears.",
            "track_record": "Hits/misses of previous 'rising' calls — the agent's prediction follow-up.",
        },
        "areas": areas,
        "categories": categories,
        "emerging_early": emerging,
        "verified": verified,
        "provisional": provisional,
        "fallen": fallen,
        "track_record": tr,
        "sources": sources,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2))
    tmp.replace(path)
    return report
