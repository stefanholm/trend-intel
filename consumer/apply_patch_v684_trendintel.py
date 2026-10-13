#!/usr/bin/env python3
"""
apply_patch_v684_trendintel.py — V68.4: make NFE main.py digest
/Applications/trend-intel/data/

Corrected revision: reads the ACTUAL trend-intel file formats
(shortlist[].key = "shortlist" not "entries"; intel_report keys
"verified"/"provisional" not "verified_trends"; ban LEDGER includes
hard_ban_roots + permanent_ban_roots, not just titles).

Two edits, both anchored on known stable markers (aborts cleanly if not
found):
  1. Inject `fetch_trend_intel_block()` helper right after the
     `REPORT_PATH = ...` definition. Reads the 6 intel files, enforces
     the 5 consumer rules (docs/consumer-integration.md):
       - rank by hotness (0-1), never raw score
       - ban ledger: titles AND roots, normalized (lowercase/punct-
         stripped), hard_ban (60d) + permanent (never)
       - setting_hint '| DIFFERENTIATE:' surfaced as mandatory guidance
       - priority_slot entries first
       - data_quality.google_trends_available (wiki-verified trusted
         when false)
  2. After the line where `learnings.get("feedback_block")` is appended
     to the feedback string, append the TREND INTEL block to the SAME
     variable — so it lands in every new manifest automatically.

Run from /Applications/NeuralForesightEngine.
Backup: main.py.bak_v68_4. Idempotent: refuses to apply twice.
"""
import json
import os
import re
import shutil
import sys

TARGET = "main.py"
BACKUP = "main.py.bak_v68_4"
INTEL_DIR = "/Applications/trend-intel/data"
MARK_DONE = "# V68.4 TREND INTEL DIGEST"

HELPER = r'''
# V68.4 TREND INTEL DIGEST — consumer integration (docs/consumer-integration.md)
TREND_INTEL_DIR = "/Applications/trend-intel/data"

def _ti_normalize(text):
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower()).strip()

def _ti_load(name, default):
    path = os.path.join(TREND_INTEL_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def _ti_banned(norm_title, ban_titles, ban_roots):
    """Exact-title match first, then root containment (bans pivots too)."""
    if norm_title in ban_titles:
        return ban_titles[norm_title]
    for root, kind in ban_roots.items():
        if root and root in norm_title:
            return kind
    return None

def fetch_trend_intel_block():
    """Read the trend-intel data feed and render a TREND INTEL block for
    the manifest. Degrades gracefully to '' when the feed is absent."""
    intel = _ti_load("intel_report.json", {})
    shortlist = _ti_load("manifest_shortlist.json", {})
    demand = _ti_load("demand_context.json", {})
    calendar = _ti_load("buyer_calendar.json", {})
    fl = _ti_load("failure_learning.json", {}) or intel.get("failure_learning") or {}
    sl_entries = shortlist.get("shortlist") or []
    if not intel and not sl_entries:
        return ""
    # rule 5: data quality
    dq = intel.get("data_quality", {})
    google_ok = bool(dq.get("google_trends_available"))
    # rule 2: ban ledger — titles exact, roots containment (roots ban pivots)
    ban_titles, ban_roots = {}, {}
    def _add(items, dest, kind):
        for item in items or []:
            t = (item.get("title") or item.get("root") or "") if isinstance(item, dict) else str(item or "")
            n = _ti_normalize(t)
            if n:
                dest[n] = kind
    _add(fl.get("hard_ban_titles"), ban_titles, "60DAY")
    _add(fl.get("permanent_ban_titles"), ban_titles, "PERMANENT")
    _add(fl.get("hard_ban_roots"), ban_roots, "60DAY")
    _add(fl.get("permanent_ban_roots"), ban_roots, "PERMANENT")
    # candidates: shortlist (gate-approved) + verified + provisional, deduped
    entries, seen, banned_count = [], set(), 0
    raw = list(sl_entries) + intel.get("verified", []) + intel.get("provisional", [])
    for e in raw:
        if not isinstance(e, dict):
            continue
        title = (e.get("title") or "").strip()
        if not title:
            continue
        key = _ti_normalize(title)
        if key in seen:
            continue
        seen.add(key)
        if _ti_banned(key, ban_titles, ban_roots):
            banned_count += 1
            continue
        entries.append(e)
    # rule 4 + rule 1: priority first, then hotness desc
    entries.sort(key=lambda e: (not bool(e.get("priority_slot")),
                                -(float(e.get("hotness") or 0.0))))
    lines = ["", "=== TREND INTEL (live feed from trend-intel agent — rank by hotness, obey slots/hints) ==="]
    if not google_ok:
        lines.append("DATA QUALITY: Google Trends unavailable — Wikipedia-verified trends remain trustworthy; higher provisional counts this cycle are EXPECTED, not a bug.")
    for q in (demand.get("queries") or [])[:6]:
        lines.append("DEMAND: %-34s supply=%s action=%s%s" % (
            (q.get("phrase") or "")[:34], q.get("supply_bucket"),
            q.get("action"),
            (" | " + q["gap_hint"]) if q.get("gap_hint") else ""))
    for w in (calendar.get("need_windows") or [])[:6]:
        lines.append("CALENDAR: %-38s %s (in %sd)" % (
            (w.get("need_title") or w.get("label") or "")[:38],
            w.get("window_status"), w.get("days_until")))
    if entries:
        lines.append("INTEL SHORTLIST (priority slots first, then hotness):")
    for e in entries[:20]:
        flags = []
        if e.get("priority_slot"):
            flags.append("PRIORITY-RENDER-FIRST")
        hint = e.get("setting_hint") or ""
        if "| DIFFERENTIATE:" in hint:
            flags.append("DIFFERENTIATE MANDATORY")
        if e.get("verified_by_google_trends") is False and e.get("state"):
            flags.append("wiki-verified")
        if e.get("provisional_gt_cooldown"):
            flags.append("provisional(GT-cooldown)")
        elif not e.get("verified_by_google_trends") and not e.get("state"):
            flags.append("provisional")
        tag = (" [" + "; ".join(flags) + "]") if flags else ""
        lines.append("- %s | hotness %.2f | image_need %s%s" % (
            e.get("title"), float(e.get("hotness") or 0.0),
            e.get("image_need") or "n/a", tag))
        if hint:
            lines.append("    setting_hint: " + hint[:300])
    if ban_titles or ban_roots:
        lines.append("INTEL BAN LEDGER: %d banned candidates filtered; ledger = %d titles + %d roots (normalized comparison; roots ban pivots too) — do not render these" % (
            banned_count, len(ban_titles), len(ban_roots)))
    for d in (fl.get("fix_directives") or [])[:4]:
        lines.append("INTEL FIX: " + d)
    lines.append("=== END TREND INTEL ===")
    return "\n".join(lines)
'''


def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)) or ".")
    if not os.path.exists(TARGET):
        sys.exit(f"ABORT: {TARGET} not found in {os.getcwd()}")
    src = open(TARGET, encoding="utf-8").read()
    if MARK_DONE in src:
        sys.exit("Already patched (V68.4 marker present). Nothing to do.")

    # --- Edit 1: helper after REPORT_PATH definition ---
    m = re.search(r'^REPORT_PATH\s*=.*$', src, re.M)
    if not m:
        sys.exit("ABORT: REPORT_PATH anchor not found — no changes written.")
    src = src[:m.end()] + "\n" + HELPER + src[m.end():]

    # --- Edit 2: append intel block after feedback_block append ---
    fb = re.search(
        r'^([ \t]*)([A-Za-z_]\w*)\s*(?:\+=|=)([^\n]*learnings\.get\(["\']feedback_block["\'][^\n]*)$',
        src, re.M)
    if not fb:
        shutil.copy(TARGET, BACKUP + ".partial")
        sys.exit("ABORT: feedback_block anchor not found. main.py untouched "
                 "(backup at " + BACKUP + ".partial). Paste the ~10 lines "
                 "around the feedback_block line for an exact-anchored fix.")
    indent = fb.group(1)
    var = fb.group(2).strip()
    inject = f'\n{indent}{var} = {var} + fetch_trend_intel_block()  {MARK_DONE}'
    src = src[:fb.end()] + inject + src[fb.end():]

    # guard imports
    if not re.search(r'^\s*import\s+json\b', src, re.M):
        src = "import json\n" + src
    if not re.search(r'^\s*import\s+re\b', src, re.M):
        src = "import re\n" + src
    if not re.search(r'^\s*import\s+os\b', src, re.M):
        src = "import os\n" + src

    shutil.copy(TARGET, BACKUP)
    open(TARGET, "w", encoding="utf-8").write(src)
    print("OK: V68.4 applied (corrected revision).")
    print("  1. fetch_trend_intel_block() helper injected after REPORT_PATH.")
    print(f"  2. TREND INTEL block appended to `{var}` after feedback_block.")
    print(f"Backup: {BACKUP}")
    print("Verify: python3 -c \"from main import fetch_trend_intel_block; "
          "print(fetch_trend_intel_block()[:400])\"")


if __name__ == "__main__":
    main()
