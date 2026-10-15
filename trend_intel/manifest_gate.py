"""Manifest gate: select which intel nuggets reach the scene-manifest layer.

Implements the keep/drop analysis:
- KEEP: verified_by_google_trends OR source_count >= 2, state rising/steady
  (or peaked+evergreen), hotness above area threshold, stock-safe title
- DROP: falling, teen junk, gadget noise, games/coloring/funeral/simulator,
  brand+SKU, pure news
- RANK: hotness first, then verified, then corroboration
- ENRICH: image_need, prop_hero, setting_hint, saturation_flag, buyer_use
"""
import re
import json
import time
from pathlib import Path

from .db import DB
from .areas import AREAS, match_area

DATA = Path(__file__).resolve().parent.parent / "data"

BRAND_PREFIX_RE = re.compile(
    r"^(dunkin|starbucks|nike|adidas|xiaomi|shokz|pact|hobbs|app?le|"
    r"samsung|sony|lego|ninja|philips|dyson|bosch)\b\s*", re.I)


def strip_brand(title):
    """Remove leading brand tokens for the manifest; brand stays in source
    metadata only."""
    t = BRAND_PREFIX_RE.sub("", title).strip()
    return t or title


STOCK_UNSAFE_RE = re.compile(
    r"\b(game|games|gaming|coloring|colouring|printable|template|funeral|"
    r"simulator|roblox|minecraft|fortnite|sketch|drawing|pixel|"
    r"for mac|for pc|windows|app|software|pdf|svg|vector pack|"
    r"sku|model no|part number|refurbished)\b", re.I)

EVERGREEN_VERTICALS = {"linen_summer", "autumn_fashion", "warm_kitchen",
                      "interiors", "crochet_craft"}

AREA_MIN_HOTNESS = {k: 0.10 for k in AREAS}
AREA_MIN_HOTNESS.update({"beauty_makeup": 0.12, "matcha_drinks": 0.12})


def stock_safe(title):
    return not STOCK_UNSAFE_RE.search(title)


def _gt_cooldown_active():
    """True while the Google Trends 429 circuit-breaker is cooling down.
    During cooldown the gate relaxes provenance rules instead of starving
    the shortlist — provisional entries pass, clearly marked."""
    try:
        from .trajectory import google_available
        return not google_available()
    except Exception:  # noqa: BLE001
        return False


def keep_rule(nug, gt_down=False):
    """Return (keep: bool, reason)."""
    t = nug["title"]
    verified = nug.get("verified_by_google_trends", False)
    src_count = nug.get("source_count", len(set(nug.get("sources", []))))
    state = nug.get("state", "unknown")
    hot = nug.get("hotness", 0)
    area = nug.get("area") or match_area(t)

    if not stock_safe(t):
        return False, "stock_unsafe"
    if "gmail_newsletter" in (nug.get("sources") or []):
        pass  # trusted newsletter = quality provenance on its own
    elif src_count < 2 and not verified:
        if gt_down and hot >= 0.5 * AREA_MIN_HOTNESS.get(area or "", 0.10) \
                and state != "falling":
            pass  # GT cooldown: hot provisional entries pass, marked below
        else:
            return False, "weak_provenance"
    if state == "falling":
        return False, "falling"
    if state == "peaked" and (area or "") not in EVERGREEN_VERTICALS:
        return False, "peaked_non_evergreen"
    min_h = AREA_MIN_HOTNESS.get(area or "", 0.10)
    if hot < min_h:
        return False, "low_hotness"
    if area in ("teen_fashion", "gadgets") and src_count < 2:
        return False, "area_noise"
    return True, "ok"


def load_area_health():
    """Agent C's per-area reject rates from real render reports. Missing or
    stale (>7d) knowledge -> empty dict: quotas stay at default."""
    try:
        data = json.loads((DATA / "failure_learning.json").read_text())
    except (OSError, ValueError):
        return {}
    if time.time() - data.get("updated_at", 0) > 7 * 24 * 3600:
        return {}
    return data.get("area_health") or {}


def health_quotas(base=3):
    """Area quotas from render-outcome health (vertical feedback loop):
    reject_rate <= 0.35 or avg_aes >= 5.0 -> healthy -> base cap
    cold (reject_rate >= 0.55 or avg_aes < 3.5) -> cap 1
    middling -> cap 2
    A healthy area keeps its slots; a cold one shrinks but never to zero —
    the shortlist always keeps vertical diversity."""
    out = {}
    for area, st in load_area_health().items():
        rr, aes = st.get("reject_rate", 0), st.get("avg_aes", 0)
        if rr >= 0.55 or aes < 3.5:
            out[area] = 1
        elif rr >= 0.45 or aes < 4.0:
            out[area] = 2
        else:
            out[area] = base
    return out


def rank(db, limit=20, area_quota=None):
    """Shortlist: hotness-ranked, trajectory-aware, vertical-diverse.

    Burned titles (render-QC failures reported by the consumer app) never
    appear — active_nuggets already excludes non-active statuses.
    Area caps shrink automatically for verticals whose renders keep
    failing (Agent C health feedback) — cold areas get fewer slots."""
    report = json.loads((DATA / "intel_report.json").read_text()) \
        if (DATA / "intel_report.json").exists() else {"areas": {}}
    if area_quota is None:
        hq = health_quotas()
        area_quota = hq if hq else None

    candidates = []
    gt_down = _gt_cooldown_active()
    for key, a in report.get("areas", {}).items():
        for t in a.get("trends", []):
            t = dict(t)
            t["area"] = t.get("area") or key
            keep, reason = keep_rule(t, gt_down=gt_down)
            if gt_down and keep and not t.get("verified_by_google_trends") \
                    and t.get("source_count", 1) < 2:
                t["provisional_gt_cooldown"] = True
            t["keep"] = keep
            t["drop_reason"] = reason
            candidates.append(t)

    demand_map = load_demand_context()
    kept = [c for c in candidates if c["keep"]]
    kept.sort(key=lambda c: (-c.get("hotness", 0),
                             -int(bool(c.get("verified_by_google_trends"))),
                             -c.get("source_count", 1)))

    # gene areas (colors/hairstyles/gadgets/styles...) are not render subjects:
    # they become spliced style genes on the kept Core Subjects instead
    from . import style_genome
    gene_candidates = [c for c in kept if style_genome.is_gene_area(c.get("area"))]
    kept = [c for c in kept if not style_genome.is_gene_area(c.get("area"))]
    if gene_candidates:
        style_genome.seed_from_harvest(gene_candidates,
                                       gene_candidates[0].get("area"))
    genes = style_genome.sample_genes(style_genome.load_genome())
    from .style_genome import shot_ladder
    gene_block = {"selected_genes": genes,
                  "shot_ladder": shot_ladder(genes),
                  "splice_formula": "Core Subject x (color | hairstyle | "
                                    "accessory | gadget | style) genes"}
    globals()["_last_gene_block"] = gene_block

    # vertical diversity: max 3 per area unless quota given
    per_area = {}
    out = []
    for c in kept:
        a = c["area"]
        cap = (area_quota or {}).get(a, 3)
        if per_area.get(a, 0) >= cap:
            continue
        per_area[a] = per_area.get(a, 0) + 1
        out.append(enrich(c, demand_map))
        if genes:
            out[-1]["style_genes"] = {b: g["prompt_fragment"]
                                      for b, g in genes.items()}
        if len(out) >= limit:
            break
    return out, candidates


IMAGE_NEED_RE = [
    (re.compile(r"matcha|latte|drink|cocktail|mocktail|coffee|tea\b", re.I),
     "Macro drink"),
    (re.compile(r"nail|manicure|lip|brow|lash|makeup|blush|serum", re.I),
     "Beauty detail"),
    (re.compile(r"lingerie|bralette|bodysuit|slip dress|sleepwear|corset", re.I),
     "SFW intimates"),
    (re.compile(r"pants|jacket|coat|cardigan|knit|sweater|outfit|dress|corduroy", re.I),
     "Environment worn apparel"),
    (re.compile(r"entryway|console|table|shelf|decor|kitchen|lamp|vase|cushion", re.I),
     "Environment interior"),
    (re.compile(r"bag|tote|crochet|craft", re.I), "Product still-life"),
]


def image_need(title):
    for rx, need in IMAGE_NEED_RE:
        if rx.search(title):
            return need
    return "Environment lifestyle"


SETTING_MAP = [
    (re.compile(r"matcha|latte|iced .*(drink|tea|coffee)|espresso", re.I),
     "cafe marble counter, filled glass with condensation, soft daylight"),
    (re.compile(r"entryway|console|foyer", re.I),
     "home entryway with console table + mirror + hooks, candle"),
    (re.compile(r"corduroy|cardigan|knit|sweater", re.I),
     "autumn interior or tree-lined street, worn apparel, warm light"),
    (re.compile(r"lingerie|bralette|slip|sleepwear", re.I),
     "sunlit bedroom, linen bedding, private boudoir"),
    (re.compile(r"nail|lip|brow|lash|makeup", re.I),
     "vanity top with mirror soft light, hands in frame"),
    (re.compile(r"table|tablescape|dining|kitchen", re.I),
     "oak dining table, morning window light, styled with intent"),
]


def setting_hint(title):
    for rx, hint in SETTING_MAP:
        if rx.search(title):
            return hint
    return "quiet interior corner, single window light"


PROP_HINT_RE = re.compile(r"[a-z][a-z ]{3,40}", re.I)


def prop_hero(title):
    """The most concrete noun phrase from the title itself."""
    m = re.search(r"(iced|matte|silk|lace|corduroy|cable[- ]knit|butter yellow|"
                  r"cherry|burgundy|mocha|sage|copper|"
                  r"[a-z]+)?\s*([a-z]+(?:\s+[a-z]+)?)", title, re.I)
    return title.strip()[:60]


def load_demand_context():
    """Agent B's night output: supply buckets + gap hints per phrase.
    Missing/stale file -> empty map; the gate never blocks on Agent B."""
    path = DATA / "demand_context.json"
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if time.time() - data.get("updated_at", 0) > 48 * 3600:
        return {}
    return {q["phrase"].strip().lower(): q for q in data.get("queries", [])}


def demand_context(c, demand_map):
    """Attach Agent B's supply knowledge to a shortlist candidate and
    force a differentiation angle when supply is flooded (merge rule)."""
    q = demand_map.get(c["title"].strip().lower())
    if not q:
        return c
    c["supply_bucket"] = q.get("supply_bucket", "unknown")
    c["adobe_approx_hits"] = q.get("adobe_approx_hits")
    if q.get("supply_bucket") == "flooded":
        c["demand_action"] = "expand_or_differentiate"
        angle = q.get("gap_hint") or \
            "living-frame differentiation: add hands/pour/usage context"
        c["differentiation_angle"] = angle
        c["setting_hint"] = (c.get("setting_hint", "") +
                             " | DIFFERENTIATE: " + angle).strip(" |")
    elif q.get("supply_bucket") == "thin" and c.get("hotness", 0) >= 0.12:
        c["demand_action"] = "keep"
        c["priority_slot"] = True
    elif q.get("gap_hint"):
        c["gap_hint"] = q["gap_hint"]
    return c


FRAMING_HINTS = {
    "Macro drink": ("tight on hero allowed; keep full vessel rim + pour point "
                    "in frame; hands enter from edge, crop mid-forearm never "
                    "at the wrist"),
    "Beauty detail": ("face/hands may fill the frame but eyes+lips fully "
                      "inside with 5% headroom; crop at mid-forearm, never "
                      "at joints; face >= 1/3 frame height for inpaint density"),
    "SFW intimates": ("waist-up minimum, full head in frame with 8% headroom; "
                      "crop at torso, never at neck/joints; face >= 1/4 frame "
                      "for face inpaint"),
    "Environment worn apparel": ("full headroom, garment hero fully visible; "
                                 "crop mid-body at most, never at ankles/"
                                 "wrists; subject inside inner 90% of frame"),
    "Environment interior": ("no crop on the hero object; hero inside inner "
                             "90% of frame; leave 15% negative space for "
                             "campaign text"),
    "Product still-life": ("hero fully inside frame with 10% margin all "
                           "sides; hands enter from frame edge only"),
    "Environment lifestyle": ("full head + mid-action body inside frame; "
                              "subject never overlaps background life; "
                              "foreground occlusion must not cover the face"),
}


def framing_hint(image_need_class):
    return FRAMING_HINTS.get(image_need_class,
                             "full subject inside frame, no limb/face crops, "
                             "8% headroom")


def people_hands(image_need_class):
    return ("1 hand holding / pouring" if "drink" in image_need_class.lower()
            else "none, hands-only on product" if "Product" in image_need_class
            else "1 person mid-motion")


def enrich(c, demand_map=None):
    c["title"] = strip_brand(c["title"])
    t = c["title"]
    c["image_need"] = image_need(t)
    c["prop_hero"] = prop_hero(t)
    c["setting_hint"] = setting_hint(t)
    c["trajectory"] = {"state": c.get("state", "unknown"),
                        "hotness": c.get("hotness", 0),
                        "sources": c.get("source_count", 1),
                        "gt_verified": bool(c.get("verified_by_google_trends"))}
    c["people_hands"] = people_hands(c["image_need"])
    c["framing_hint"] = framing_hint(c["image_need"])
    c["buyer_use"] = {"Macro drink": "cafe menus / delivery app hero",
                      "Beauty detail": "cosmetics campaign / tutorial",
                      "SFW intimates": "apparel lookbook / brand campaign",
                      "Environment worn apparel": "fashion lookbook / autumn editorial",
                      "Environment interior": "furniture retail / home staging",
                      "Product still-life": "ecommerce / craft brand"}.get(c["image_need"], "lifestyle campaign")
    if demand_map is not None:
        c = demand_context(c, demand_map)
    return c


def adult_slot(shortlist, evergreen_pool=None):
    """P3 adult lock: the adult slot must be intimates/swimwear per the
    lexicon gate. Non-intimates adult themes are rewritten pre-manifest."""
    from .sources.verticals import gate_adult, ADULT_EVERGREEN
    pool = evergreen_pool or ADULT_EVERGREEN
    rewritten = 0
    for c in shortlist:
        if c.get("area") == "adult_lingerie" and not gate_adult(c["title"]):
            old_t = c["title"]
            c["title"] = pool[rewritten % len(pool)]
            c["adult_theme_rewritten"] = old_t
            c["image_need"] = "SFW intimates"
            c["setting_hint"] = "sunlit bedroom, linen bedding, private boudoir"
            c["people_hands"] = "1 person mid-motion, tasteful SFW framing"
            rewritten += 1
    return shortlist, rewritten


def export_shortlist(limit=20, path=None):
    path = Path(path or DATA / "manifest_shortlist.json")
    db = DB(DATA / "intel.db")
    shortlist, all_candidates = rank(db, limit=limit)
    shortlist, adult_rewritten = adult_slot(shortlist)
    if adult_rewritten:
        # log shortfall per P3 spec
        out_extra = {"shortfall": {"adult_theme_rewritten": adult_rewritten}}
    else:
        out_extra = {}
    out = {
        "generated_at": int(time.time()),
        **out_extra,
        "style_genes": globals().get("_last_gene_block", {}),
        "shortlist": shortlist,
        "rejected_summary": _reject_summary(all_candidates),
        "legend": {
            "image_need": "who licenses this: Macro drink / Beauty detail / Environment ...",
            "prop_hero": "concrete hero object for the frame (from the title)",
            "setting_hint": "coherent micro-setting mapped from the title",
            "trajectory": "state + hotness + source count + GT verification",
            "people_hands": "hands/usage mandate (filled vessels, no empty)",
            "buyer_use": "one-line buyer use case",
            "supply_bucket": "Agent B supply: flooded | competitive | thin | unknown",
            "demand_action": "expand_or_differentiate = flooded: use differentiation_angle",
            "priority_slot": "thin supply + hot demand — best licensing slot",
        },
    }
    path.write_text(json.dumps(out, indent=2))
    return out


def _reject_summary(candidates):
    from collections import Counter
    return dict(Counter(c["drop_reason"] for c in candidates if not c["keep"]))
