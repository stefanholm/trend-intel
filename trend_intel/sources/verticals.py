"""Dedicated beauty & adult harvest paths (P0).

Retailer sites (Kicks, Hunkemöller, H&M, Lindex, ASOS) block scraping, so
their vocabulary lives here as curated seed pools. Harvest = fixed seeds +
Google autocomplete (reliable, no 429) + pytrends on those seeds only.

Lexicon gates enforce vertical purity:
- adult: intimates nouns ONLY (slip, bralette, robe, bodysuit, lace...)
- beauty: makeup/beauty nouns ONLY (lip, liner, mascara, blush, serum...)

No global toplist fallback ever lands in these verticals; if the harvest is
empty, a fixed EVERGREEN list is used instead (never turtleneck/noir).
"""
import re
import logging
import time
import random

log = logging.getLogger("trend_intel.verticals")

# --- curated retailer-derived seed pools (vocabulary from Kicks/Lyko/Sephora
#     beauty edits + Hunkemöller/H&M/Lindex/ASOS lingerie campaigns) ---
BEAUTY_SEEDS = [
    "berry stain lip", "plum matte liquid lipstick", "glazed lip oil",
    "brown lip liner", "cream blush stick", "liquid blush",
    "latte makeup look", "espresso makeup", "strawberry makeup",
    "soft goth makeup", "cold girl makeup", "clean girl makeup",
    "siren eyes", "doe eyes", "smoked liner", "white eyeliner look",
    "soap brows", "laminated brows", "microblading",
    "mascara trend", "flutter lashes", "glazed donut skin",
    "glass skin routine", "dewy skin serum", "perfume layering",
    "vanilla perfume", "gel manicure", "chrome nails", "french tip nails",
    "vanity mirror lights", "makeup brush set", "beauty sponge",
]

ADULT_SEEDS = [
    "silk slip dress", "lace slip nightdress", "satin pyjama set",
    "lace balconette bra", "seamless bralette", "sports bra trend",
    "lace bodysuit", "mesh bodysuit", "satin robe set",
    "silk robe morning", "lace trim camisole", "bridal lingerie",
    "honeymoon lingerie", "bodysuit lace detail", "high waist briefs",
    "lounge set satin", "velvet loungewear", "corset top outfit",
    "sheer robe", "lace nightdress", "sleep set lace", "silk cami set",
    "one piece swimsuit", "high waisted bikini", "retro swimsuit",
    "tankini trend", "swimsuit cut out trend",
]

# --- lexicon gates (vertical purity) ---
ADULT_LEXICON = re.compile(
    r"\b(slip|bra|bralette|briefs?|robe|lounge|loungewear|bodysuit|"
    r"lingerie|sleepwear|nightdress|pyjama|pajama|camisole|camis|"
    r"corset|balconette|intimates|swimsuit|swimwear|bikini|tankini|"
    r"satin|lace|sheer|silk|mesh)\b", re.I)

BEAUTY_LEXICON = re.compile(
    r"\b(lip|lips|lipstick|liner|eyeliner|mascara|blush|highlighter|"
    r"manicure|nails?|nail|perfume|fragrance|serum|skin|makeup|"
    r"brows?|lashes|gloss|foundation|contour|bronzer|vanity|"
    r"beauty sponge|brush(es)?|eyeshadow|palette)\b", re.I)

# hard bans for these verticals
ADULT_BAN = re.compile(
    r"\b(noir|fairy|tale|ridding|riding hood|turtleneck|sweater|"
    r"costume|halloween|cosplay|print|poster|man|men|male|"
    r"1800s|1880s|1900s|victorian|vintage|renaissance|medieval|"
    r"history|historical)\b", re.I)

BEAUTY_BAN = re.compile(
    r"\b(games?|poki|coloring|printable|does .{1,20} look good|"
    r"for mac|for pc|wallpaper)\b", re.I)


def gate_adult(title):
    """True if title is a clean intimates/swimwear subject."""
    t = title.strip()
    return bool(ADULT_LEXICON.search(t)) and not ADULT_BAN.search(t)


def gate_beauty(title):
    """True if title is a clean beauty/makeup subject."""
    t = title.strip()
    return bool(BEAUTY_LEXICON.search(t)) and not BEAUTY_BAN.search(t)


# --- evergreen fallbacks (used ONLY when harvest yields nothing) ---
ADULT_EVERGREEN = [
    "silk slip dress bedroom morning",
    "lace bodysuit boudoir soft light",
    "satin pyjama set linen bedding",
    "seamless bralette lounge editorial",
    "bridal lingerie suite window light",
]

BEAUTY_EVERGREEN = [
    "berry stain lip macro",
    "gel manicure hands daylight",
    "latte makeup vanity mirror",
    "cream blush application close up",
    "perfume bottle vanity still life",
]


def harvest_vertical(db, which, verbose=False, seeds=None, evergreen=None,
                     gate=None, source_tag=None):
    """Harvest one vertical via autocomplete on curated seeds, gated by
    its lexicon. Falls back to fixed evergreen list if yield is zero."""
    from . import autocomplete
    count = 0
    for s in (seeds or []):
        for sug in autocomplete.suggest(s):
            if not gate or gate(sug):
                db.upsert_raw(
                    source=source_tag,
                    title=sug.strip()[:80],
                    external_id=sug.strip().lower()[:200],
                    extra={"seed": s, "vertical_gated": True},
                )
                count += 1
        time.sleep(random.uniform(1.0, 2.5))
    if count == 0 and evergreen:
        for e in evergreen:
            db.upsert_raw(
                source=source_tag + "_evergreen",
                title=e,
                external_id=e.lower(),
                extra={"evergreen": True},
            )
        count = len(evergreen)
    if verbose:
        print(f"[{source_tag}] {count} gated items")
    return count


def harvest_beauty(db, verbose=False):
    return harvest_vertical(db, "beauty", verbose=verbose,
                            seeds=BEAUTY_SEEDS[:10],  # gentle: rotate subset
                            evergreen=BEAUTY_EVERGREEN,
                            gate=gate_beauty,
                            source_tag="beauty_rss")


def harvest_adult(db, verbose=False):
    return harvest_vertical(db, "adult", verbose=verbose,
                            seeds=ADULT_SEEDS[:10],
                            evergreen=ADULT_EVERGREEN,
                            gate=gate_adult,
                            source_tag="adult_rss")


def rotate_vertical_seeds(db, pool, n, meta_key):
    """Rotate through the curated pool in gentle mode."""
    from ..pacing import rotate
    return rotate(pool, n, meta_key, db)
