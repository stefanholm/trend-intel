"""Failure-learning agent: reads the render app's QC reports and turns
scores into bans + fix directives for the next manifest run.

It is NOT a trend finder. It is memory of what already failed or falsely
looked "in demand".

Inputs  (drop into data/, or NFE_REPORT_DIR env var):
  latest_report.json / report_*.json with renders[] rows:
    title, market_score, aesthetic_score (AES), clip_score, verdict,
    optional qc_plastic_skin / qc_focus_global / face_inpaint_status

Outputs:
  data/failure_learning.json            — the knowledge file
  DB bans: hard-ban titles/roots -> status='burned'
  report: failure_learning block in intel_report.json (same report
          as everything else, top-level alongside data_quality)
"""
import json
import re
import time
import logging
from pathlib import Path
from collections import Counter

log = logging.getLogger("failure_learning")

DATA = Path(__file__).resolve().parent.parent / "data"
OUT_PATH = DATA / "failure_learning.json"

BRAND_SKU_RE = re.compile(
    r"\b(OEAK|Eichholtz|panache|Nike|Adidas|H&M|Zara|Apple|Samsung|"
    r"Full HD|\d+\.\d+\s*\w*|Wireless|SKU)\b", re.I)
INTIMATES_RE = re.compile(
    r"\b(lingerie|intimates|bralette|bra\b|slip|robe|bodysuit|lounge|"
    r"nightwear|sleepwear|thong|bikini|underkläd|bh\b)\b", re.I)
ADULT_LEAK_RE = re.compile(
    r"\b(turtleneck|riding hood|sequin|red carpet|celebrity|"
    r"sparkles in|goes pantsless|steps out)\b", re.I)

MAX_AGE_S = 14 * 24 * 3600   # render reports older than this are ignored
SEASONAL_BAN_DAYS = 60      # failed trends re-eligible next season
PERM_BAN_REASON = "failure_learning_permanent"
TEMP_BAN_REASON = "failure_learning_ban"


def _norm(t):
    t = re.sub(r"[^a-z0-9\s]", " ", (t or "").lower())
    return re.sub(r"\s+", " ", t).strip()


def _root(t):
    parts = _norm(t).split()
    return " ".join(parts[:3]) if parts else ""


def _report_dirs(data_dir=None):
    import os
    dirs = [Path(data_dir) if data_dir else DATA]
    env = os.environ.get("NFE_REPORT_DIR")
    if env:
        dirs.append(Path(env))
    return dirs


def load_renders(data_dir=None, max_files=4, max_renders=400):
    """Newest N render reports; renders[] rows with title + scores."""
    files = []
    for d in _report_dirs(data_dir):
        if not d.is_dir():
            continue
        files += list(d.glob("latest_report*.json"))
        files += list(d.glob("report_*.json"))
    files = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)
    files = files[:max_files]
    rows = []
    for path in files:
        try:
            if time.time() - path.stat().st_mtime > MAX_AGE_S:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        shots = (data.get("renders")
                 or data.get("PER_SHOT_CARDS")
                 or data.get("analyzed_shots")
                 or [])
        for s in shots:
            title = (s.get("title") or s.get("trend_title") or "").strip()
            if not title:
                continue
            from .areas import match_area
            rows.append({
                "title": title,
                "norm": _norm(title),
                "root": _root(title),
                "area": match_area(title),
                "market": float(s.get("market_score") or s.get("Market") or 0),
                "aes": float(s.get("aesthetic_score") or s.get("AES") or 0),
                "clip": float(s.get("clip_score") or s.get("rendered_CLIP") or 0),
                "verdict": str(s.get("verdict") or s.get("final_verdict") or ""),
                "src": path.name,
            })
            if len(rows) >= max_renders:
                return rows, files
        # newer pre-render format: shots[] with tt + human_qc (1-5 scale)
        for s in data.get("shots") or []:
            hq = s.get("human_qc") or {}
            if not s.get("tt") or not hq:
                continue
            title = s["tt"].strip()
            visual = float(hq.get("visual_score") or 0)
            market = float(hq.get("market_score") or 0)
            adult = float(hq.get("adult_score") or 0)
            killed = bool(hq.get("kill_repetitive"))
            # map 1-5 human scale onto the classifier's scales:
            # visual 2 -> aes 3.0 (reject), 3 -> 5.0, 4+ -> winner range
            aes = visual * 2.0 - 1.0 if visual else 0.0
            market_scaled = market * 20.0            # 1-5 -> 20-100
            if killed or (visual and visual <= 2) or adult >= 4:
                verdict = "REJECT"
            elif visual >= 4:
                verdict = "GOOD"
            else:
                verdict = "MARGINAL"
            from .areas import match_area
            rows.append({
                "title": title,
                "norm": _norm(title),
                "root": _root(title),
                "area": match_area(title),
                "market": market_scaled,
                "aes": aes,
                "clip": 99.0,                        # no CLIP in this format
                "verdict": verdict,
                "src": path.name,
            })
            if len(rows) >= max_renders:
                return rows, files
    return rows, files


def classify(rows):
    ban_titles, ban_roots = set(), set()
    perm_titles, perm_roots = set(), set()          # brand/SKU + adult leaks: never expire
    false_demand, adult_leaks, brand_hits, fix_directives = [], [], [], []
    winners, failures = [], []
    root_fail = Counter()
    plastic_skin = focus_issues = 0

    for r in rows:
        v = r["verdict"].upper()
        is_reject = "REJECT" in v or r["aes"] < 4.0
        is_good = "GOOD" in v or (r["aes"] >= 6.0 and r["clip"] >= 28)

        if BRAND_SKU_RE.search(r["title"]):
            brand_hits.append(r["title"])
            perm_titles.add(r["norm"])
            perm_roots.add(r["root"])

        # adult leak: banned regardless of verdict (never adult slot), permanent
        if ADULT_LEAK_RE.search(r["title"]) and not INTIMATES_RE.search(r["title"]):
            adult_leaks.append(r["title"])
            perm_titles.add(r["norm"])

        if is_reject:
            failures.append(r)
            ban_titles.add(r["norm"])
            if r["root"]:
                root_fail[r["root"]] += 1
            if r["market"] >= 70 and (r["aes"] < 4.0 or r["clip"] < 25):
                false_demand.append(r)
                ban_roots.add(r["root"])
        elif is_good:
            winners.append(r)

    # winners rehabilitate: a title that later GOODs is not banned again,
    # and its root's failure count is forgiven
    win_norms = {r["norm"] for r in winners}
    win_roots = {r["root"] for r in winners}
    ban_titles -= win_norms
    for root in win_roots:
        root_fail.pop(root, None)

    for root, n in root_fail.items():
        if n >= 2 and root:
            ban_roots.add(root)

    ban_titles -= perm_titles
    ban_roots = {r for r in ban_roots if r} - perm_roots
    # a winner forgives its whole root: the theme CAN render well, so a
    # differentiated retry is allowed next season/manifest
    ban_roots -= win_roots
    ban_titles = {t for t in ban_titles
                  if not any(t.startswith(r) for r in win_roots)}

    if plastic_skin:
        fix_directives.append("beauty renders: pores/texture pass BEFORE "
                              "face inpaint, milder inpaint strength")
    if adult_leaks:
        fix_directives.append("adult slot = intimates nouns only; "
                              "turtleneck/red-carpet/celebrity themes never adult")
    if brand_hits:
        fix_directives.append("no brand/SKU titles (OEAK, Eichholtz, Full HD...)")

    # per-area health: reject rate + avg AES from the render reports
    area_stats = {}
    for r in rows:
        a = r.get("area")
        if not a:
            continue
        st = area_stats.setdefault(a, {"shots": 0, "rejects": 0, "aes_sum": 0.0})
        st["shots"] += 1
        v = r["verdict"].upper()
        if "REJECT" in v or r["aes"] < 4.0:
            st["rejects"] += 1
        st["aes_sum"] += r["aes"]
    area_health = {}
    for a, st in area_stats.items():
        if st["shots"] >= 5:
            area_health[a] = {
                "shots": st["shots"],
                "rejects": st["rejects"],
                "reject_rate": round(st["rejects"] / st["shots"], 2),
                "avg_aes": round(st["aes_sum"] / st["shots"], 2),
            }

    return {
        "updated_at": int(time.time()),
        "area_health": area_health,
        "n_rows": len(rows),
        "hard_ban_titles": sorted(ban_titles)[:80],
        "hard_ban_roots": sorted(x for x in ban_roots if x)[:60],
        "permanent_ban_titles": sorted(perm_titles)[:80],
        "permanent_ban_roots": sorted(x for x in perm_roots if x)[:60],
        "false_demand": [{"title": x["title"], "market": x["market"],
                          "aes": x["aes"], "clip": x["clip"]}
                         for x in false_demand[:30]],
        "adult_leaks": sorted(set(adult_leaks))[:20],
        "brand_sku_hits": sorted(set(brand_hits))[:20],
        "fix_directives": fix_directives,
        "winners": [{"title": x["title"], "aes": x["aes"],
                     "clip": x["clip"], "market": x["market"]}
                    for x in winners[:15]],
        "failure_sample": [{"title": x["title"], "aes": x["aes"],
                            "clip": x["clip"], "verdict": x["verdict"][:60]}
                           for x in failures[:25]],
    }


def _empty():
    return {"updated_at": int(time.time()), "n_rows": 0, "area_health": {},
            "hard_ban_titles": [], "hard_ban_roots": [],
            "permanent_ban_titles": [], "permanent_ban_roots": [],
            "false_demand": [], "adult_leaks": [], "brand_sku_hits": [],
            "fix_directives": [], "winners": [], "failure_sample": []}


def run(db=None, data_dir=None):
    """Read render reports -> classify -> write knowledge file -> ban in DB.
    Never raises; missing reports just produce an empty knowledge file."""
    try:
        rows, files = load_renders(data_dir)
        if not rows:
            log.info("failure-learning: no render reports found")
            ctx = _empty()
        else:
            ctx = classify(rows)
            log.info("failure-learning: %d shots from %d files: "
                     "%d ban titles, %d ban roots, %d false_demand",
                     ctx["n_rows"], len(files),
                     len(ctx["hard_ban_titles"]),
                     len(ctx["hard_ban_roots"]),
                     len(ctx["false_demand"]))
        OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUT_PATH.write_text(json.dumps(ctx, indent=2, ensure_ascii=False))
        if db is not None:
            expired = db.expire_burned(TEMP_BAN_REASON,
                                       SEASONAL_BAN_DAYS * 24 * 3600)
            if expired:
                log.info("failure-learning: %d seasonal bans expired "
                         "(re-eligible)", expired)
            if ctx["hard_ban_titles"]:
                banned = db.mark_burned(
                    [t for t in ctx["hard_ban_titles"] if t],
                    reason=TEMP_BAN_REASON)
                log.info("failure-learning: %d nuggets burned (60d expiry)",
                         banned)
            if ctx["permanent_ban_titles"]:
                perm = db.mark_burned(
                    [t for t in ctx["permanent_ban_titles"] if t],
                    reason=PERM_BAN_REASON)
                log.info("failure-learning: %d nuggets burned permanently",
                         perm)
    except Exception:  # noqa: BLE001
        log.exception("failure-learning failed (isolated)")
        ctx = _empty()
    return ctx


def report_block(ctx=None):
    """Compact block for intel_report.json — lands in the same report as
    everything else."""
    if ctx is None:
        try:
            ctx = json.loads(OUT_PATH.read_text())
        except (OSError, ValueError):
            return {"n_rows": 0, "updated_at": 0,
                    "note": "no render reports ingested yet"}
    if not ctx or not ctx.get("n_rows"):
        return {"n_rows": 0, "updated_at": ctx.get("updated_at", 0),
                "note": "no render reports ingested yet"}
    return {
        "updated_at": ctx["updated_at"],
        "n_rows": ctx["n_rows"],
        "hard_ban_roots": ctx["hard_ban_roots"][:25],
        "hard_ban_titles": ctx["hard_ban_titles"][:40],
        "false_demand": [{"title": x["title"], "market": x["market"],
                          "aes": x["aes"], "clip": x["clip"]}
                         for x in ctx["false_demand"][:8]],
        "adult_leaks": ctx["adult_leaks"][:10],
        "brand_sku_hits": ctx["brand_sku_hits"][:10],
        "fix_directives": ctx["fix_directives"],
        "winner_patterns": [
            {"title": x["title"], "aes": x["aes"], "clip": x["clip"]}
            for x in ctx.get("winners", [])[:8]],
        "legend": {
            "hard_ban_roots": "2-3 word roots that failed render QC — never regenerate",
            "false_demand": "market_score >=70 but AES<4 or CLIP<25 — demand proxy was wrong",
            "adult_leaks": "adult-ish titles without intimates nouns — never adult slot",
            "fix_directives": "render/Gemini fixes derived from failures",
            "winner_patterns": "AES>=6 & CLIP>=28 — pattern priors only, not copy licenses",
        },
    }


def manifest_prep_text(ctx=None):
    """Plain-text block to paste into the render app's manifest prep."""
    if ctx is None:
        try:
            ctx = json.loads(OUT_PATH.read_text())
        except (OSError, ValueError):
            ctx = _empty()
    if not ctx.get("n_rows"):
        return "• No failure-learning data yet.\n"
    lines = ["--- LEARNED FROM RENDER REPORTS (failure-learning agent) ---"]
    if ctx.get("hard_ban_roots"):
        lines.append("BANNED ROOTS (do not regenerate/pivot): "
                     + ", ".join(ctx["hard_ban_roots"][:25]))
    if ctx.get("false_demand"):
        fd = [f"{x['title']} (mkt {x['market']}, AES {x['aes']}, CLIP {x['clip']})"
              for x in ctx["false_demand"][:8]]
        lines.append("FALSE DEMAND (high market, weak image — expand or drop): "
                     + " | ".join(fd))
    if ctx.get("adult_leaks"):
        lines.append("ADULT LEAKS (not intimates — never adult slot): "
                     + ", ".join(ctx["adult_leaks"][:10]))
    if ctx.get("brand_sku_hits"):
        lines.append("BRAND/SKU BANS (permanent): "
                     + ", ".join(ctx["brand_sku_hits"][:10]))
    if ctx.get("fix_directives"):
        lines.append("FIXES: " + "; ".join(ctx["fix_directives"]))
    if ctx.get("winners"):
        w = [f"{x['title']} (AES {x['aes']}, CLIP {x['clip']})"
             for x in ctx["winners"][:8]]
        lines.append("WINNER PATTERNS: " + " | ".join(w))
    return "\n".join(lines) + "\n"
