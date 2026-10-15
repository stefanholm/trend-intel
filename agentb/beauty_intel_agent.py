"""Beauty / Adult / Lingerie deep-intelligence agent.

The generic pipeline treats vertical trends like any other keyword. But
beauty/adult renders fail at 77%+ because the intel is shallow: a title
with no shade vocabulary, no texture detail, no styling guidance. This
agent goes deep on exactly those verticals:

  1. EXPAND   — multi-seed autocomplete fan-out per vertical (long-tail
                discovery: 'latte makeup' -> glazed lips, brown liner...)
  2. VERIFY   — commercial autocomplete oracle (zero-cooldown) confirms
                the trend has real search expansion
  3. PROFILE  — deep detail per surviving trend: shade/colorway tokens,
                texture vocabulary, application verbs, vanity/boudoir
                setting architecture, demographic suggestion
  4. SUPPLY   — thin-supply check via the existing gap probe ladder
  5. EMIT     — data/beauty_intel.json: verified deep profiles the gate
                and NFE consume (image_need, style genes by vibe, and a
                render recipe per trend)

Runs nightly with Agent B and on demand. Never blocks the pipeline.
"""
import json
import re
import time
import logging
import urllib.parse
import urllib.request
from pathlib import Path

from trend_intel.style_genome import detect_vibe
from trend_intel.db import DB

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
OUT = DATA / "beauty_intel.json"

log = logging.getLogger("beauty_intel")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0"}

BEAUTY_LEXICON = re.compile(
    r"\b(lip|lips|lipstick|liner|eyeliner|mascara|blush|highlighter|"
    r"manicure|nails?|perfume|fragrance|serum|makeup|brows?|lashes|"
    r"gloss|foundation|contour|bronzer|vanity|eyeshadow|palette|"
    r"lash|cluster|brow|cream|glaze|stain)\b", re.I)
ADULT_LEXICON = re.compile(
    r"\b(slip|bra|bralette|briefs?|robe|lounge|loungewear|bodysuit|"
    r"lingerie|sleepwear|nightdress|pyjama|pajama|camisole|corset|"
    r"balconette|intimates|swimsuit|swimwear|bikini|tankini|"
    r"satin|lace|sheer|silk|mesh|"
    # bold mainstream lingerie vocabulary — restaged SFW downstream
    r"bodystocking|strappy|cage|halter|plunge|deep v|open back|"
    r"backless|garter|suspender|thigh.?high|stockings?|chemise|"
    r"babydoll|teddy|bustier|basque|garter belt|harness|"
    r"seductive|sensual|allure|provocative|daring|bold|"
    r"strapless|wireless|push.?up|cut.?out|low.?cut|skimpy)\b", re.I)
# boldness vocabulary — signals for downstream SFW restaging priority
BOLD_RE = re.compile(
    r"\b(sheer|strappy|cage|harness|cut.?out|plunge|deep v|open back|"
    r"backless|garter|thigh.?high|bodystocking|seductive|sensual|"
    r"provocative|daring|skimpy|barely there)\b", re.I)
# explicit wall: hard-rejected at discovery (not restageable — Adobe ban)
EXPLICIT_RE = re.compile(
    r"\b(porn|xxx|nude|naked|nsfw|hardcore|explicit sex|"
    r"topless|bottomless|crotchless|nipple|erotic)\b", re.I)

BRAND_RE = re.compile(
    r"\b(loop|huda|rhode|rare beauty|fenty|skims|by mario|dedendorff|"
    r"hailey|bieber|kylie|jenner|victoria.?s secret|zara|h&m)\b", re.I)
# medical/aesthetic PROCEDURES are not licensable makeup-still-life subjects
PROCEDURE_RE = re.compile(
    r"\b(botox|filler|laser|microneedling|peel|surgery|surgical|"
    r"injection|clinique?\b|dermatolog\w+|med ?spa|before and after|"
    r"cost|price|near me|procedure|treatment|"
    r"lip flip|lip filler|fat dissolv\w+|thread lift|prp|"
    r"b[aä]st i test)\b", re.I)

# deep-detail vocabulary for profiling
SHADES = {
    "beauty": ["plum", "berry", "espresso", "mocha", "rose", "cherry red",
               "terracotta", "nude", "caramel", "mauve", "cinnamon",
               "peach", "rust", "burgundy", "brown"],
    "adult": ["ivory", "espresso", "emerald", "burgundy", "champagne",
              "sage", "plum", "black", "pearl", "blush pink", "cobalt"],
}
TEXTURES = {
    "beauty": ["glazed", "matte", "glossy", "creamy", "sheer", "satin",
               "velvet", "dewy", "balmy", "shimmer"],
    "adult": ["bias-cut", "floral lace", "chantilly", "mesh", "silk charmeuse",
              "ribbed knit", "scalloped", "eyelash lace", "micro-modal"],
}
VERBS = {
    "beauty": ["applying", "swatching", "blending", "painting", "dabbing",
               "lining", "curling", "layering"],
    "adult": ["fastening", "tying", "adjusting", "smoothing", "stepping into",
              "draping", "clipping"],
}
SETTINGS = {
    "beauty": [
        "honed travertine vanity counter with pivoting brass mirror",
        "marble bathroom vanity, soft window light, hands in frame",
        "backlit vanity with fluted glass sconce and zellige tiles",
        "dressing table with oak frame mirror and ceramic brush tray",
    ],
    "adult": [
        "sunlit bedroom with linen bedding and limewash walls",
        "private boudoir with arched brass mirror and terrazzo floor",
        "morning bedroom, sheer curtains, warm practical lamp glow",
        "dressing room with walnut console and velvet bench",
    ],
}

SEEDS = {
    "beauty": [
        "lip", "lipstick", "lip liner", "lip gloss", "lip oil",
        "eyeliner", "mascara", "lashes", "brow", "blush",
        "makeup", "serum", "skincare", "nails", "manicure",
        "perfume", "foundation", "cream blush", "stain lip",
    ],
    "adult": [
        "silk slip", "lace bodysuit", "satin robe", "bralette",
        "lingerie", "pyjama set", "sleepwear", "camisole", "loungewear",
        "bridal lingerie", "honeymoon", "boudoir", "corset",
        "balconette", "swimsuit", "bikini",
        # bold discovery: sensual mainstream demand vocabulary
        "sheer bodystocking", "strappy lingerie", "plunge bodysuit",
        "garter set", "cage bra", "open back lingerie", "chemise",
        "seductive lingerie", "bridal corset", "boudoir lace",
    ],
}


def _ac(query, ds=None, timeout=3):
    url = ("https://suggestqueries.google.com/complete/search"
           "?client=firefox")
    if ds:
        url += f"&ds={ds}"
    url += "&q=" + urllib.parse.quote_plus(query)
    try:
        req = urllib.request.Request(url, headers=UA)
        data = json.loads(urllib.request.urlopen(req, timeout=timeout)
                          .read().decode("utf-8"))
        return data[1] if len(data) > 1 and isinstance(data[1], list) else []
    except Exception:  # noqa: BLE001
        return []


def gate(which, title):
    lex = BEAUTY_LEXICON if which == "beauty" else ADULT_LEXICON
    return (bool(lex.search(title))
            and not BRAND_RE.search(title)
            and not PROCEDURE_RE.search(title)
            and not EXPLICIT_RE.search(title))


def _root(t):
    """First two significant words — variant clustering key."""
    words = [w for w in re.findall(r"[a-z]+", t.lower()) if len(w) > 2]
    return " ".join(words[:2])


JUNK_RE = re.compile(
    r"\b(today|yesterday|tomorrow|show|offers?|sales?|deals?|shop|shopping|"
    r"best|worst|top|new|my|me|you|your|i|we|the|a|to|of|in|on|for|"
    r"review|reviews|guide|tips?|how|why|what|when|is|are|this|that|"
    r"week|month|year|fall|winter|spring|summer)\b", re.I)


def _phrases(text):
    """Extract short trend phrases from social/editorial headlines.
    A Reddit title like 'Finally nailed the glazed donut look' becomes
    candidate phrases; long journalistic sentences are not trends, the
    lexicon-ngrams inside them are. Junk-bearing ngrams (shop/best/
    today/reviews) are commerce or filler, not trends."""
    text = text.lower()
    text = re.sub(r"[^a-z\s]", " ", text)
    words = [w for w in text.split() if len(w) > 1]
    phrases = []
    for n in (3, 2, 4):
        for i in range(len(words) - n + 1):
            p = " ".join(words[i:i + n])
            if 5 <= len(p) <= 42 and not JUNK_RE.search(p):
                phrases.append(p)
    return phrases


def _social_discover(which, seen_roots, seen, max_total):
    """Social-media + magazine harvesting through the same gate/root
    clustering. Social titles carry community trend language; editorial
    headlines carry magazine trend language. Both arrive as long titles,
    so we mine lexicon-bearing phrases instead of using raw titles."""
    found = []
    try:
        from agentb import social_discovery
        raw_titles = social_discovery.harvest(which, max_items=25)
    except Exception:  # noqa: BLE001
        raw_titles = []
    try:
        from agentb import editorial_discovery
        raw_titles += editorial_discovery.harvest(which, max_items=25)
    except Exception:  # noqa: BLE001
        pass
    for title in raw_titles:
        for s in _phrases(title):
            root = _root(s)
            if (not s or s.lower() in seen or not gate(which, s)
                    or root in seen_roots):
                continue
            seen.add(s.lower())
            seen_roots.add(root)
            found.append({"trend": s, "via": "social/editorial"})
            break
        if len(found) >= max_total:
            break
    return found


def discover(which, max_seeds=6, max_total=60, per_seed=2, per_root=1):
    """Fan out per seed; cluster variants by 2-word root so one concept
    (silk slip dress / silk slip mini / silk slip nightgown) consumes ONE
    discovery slot, leaving room for bold/other concepts. Social media
    and magazine headlines join the same candidate pool."""
    found, seen_roots, seen = [], set(), set()
    found += _social_discover(which, seen_roots, seen, max_total // 3)
    for seed in SEEDS[which][:max_seeds]:
        got = 0
        for sug in _ac(seed) + _ac(seed, ds="sh"):
            s = sug.strip()[:80]
            root = _root(s)
            if (not s or s.lower() in seen or not gate(which, s)
                    or root in seen_roots):
                continue
            seen.add(s.lower())
            seen_roots.add(root)
            found.append({"trend": s, "via": seed})
            got += 1
            if got >= per_seed or len(found) >= max_total:
                break
        if len(found) >= max_total:
            return found
        time.sleep(0.4)
    return found


def verify(trend):
    """Commercial velocity: rich autocomplete tree = real search demand.
    Trends whose expansion tree is dominated by procedure/shop queries
    (botox, before-and-after, bäst-i-test, cost) are not visual subjects."""
    sugg = set(_ac(trend)) | set(_ac(trend, ds="sh"))
    clean = [x for x in sugg if not PROCEDURE_RE.search(x)]
    ok = len(sugg) >= 3 and len(clean) >= max(2, len(sugg) // 2)
    return ok, min(100, len(clean) * 8), sorted(clean)[:5]


def profile(which, trend, expansions):
    """Deep render-ready profile for one vertical trend."""
    kind = "beauty" if which == "beauty" else "adult"
    text = " ".join([trend] + expansions).lower()
    shade = next((s for s in SHADES[kind] if s in text), None)
    texture = next((t for t in TEXTURES[kind] if t in text), None)
    verb = next((v for v in VERBS[kind] if v in text), None)
    setting = SETTINGS[kind][hash(trend) % len(SETTINGS[kind])]
    img_need = ("Beauty detail" if kind == "beauty" else "SFW intimates")
    bold = bool(BOLD_RE.search(text))
    return {
        "boldness": ("high" if bold else "classic"),
        "restage_note": ("downstream MUST restage to tasteful SFW boudoir "
                         "per adult-intimates lock: lingerie/silk/lace "
                         "wardrobe, private setting, no explicit framing"
                         if bold else ""),
        "trend": trend,
        "vertical": kind,
        "image_need": img_need,
        "vibe": detect_vibe(trend),
        "shade_or_colorway": shade or (SHADES[kind][hash(trend)
                                                  % len(SHADES[kind])]),
        "texture_tokens": [texture] if texture else TEXTURES[kind][:2],
        "action_verb": verb or VERBS[kind][hash(trend) % len(VERBS[kind])],
        "setting_architecture": setting,
        "framing_hint": ("eyes+lips fully in frame, 5% headroom, face >= 1/3 "
                         "frame for inpaint density" if kind == "beauty"
                         else "waist-up minimum, full head + 8% headroom, "
                              "crop at torso never at joints"),
        "expansion_evidence": expansions[:5],
        "micro_detail_hint": (
            "razor-sharp vermilion lip border, individually separated "
            "lashes, 3D cheek pores under raking light"
            if kind == "beauty" else
            "floral lace cordonnet thread relief, silk charmeuse slub "
            "weave, scalloped eyelash trim, 3D skin pore topography"),
    }


def run(db=None, max_trends=12):
    """Full deep-intel pass. Writes data/beauty_intel.json. Never raises."""
    db = db or DB(DATA / "intel.db")
    out = {"updated_at": int(time.time()), "beauty": [], "adult": []}
    try:
        for which in ("beauty", "adult"):
            found = discover(which, max_seeds=10)
            verified = []
            for f in found:
                ok, velocity, expansions = verify(f["trend"])
                if not ok:
                    continue
                p = profile(which, f["trend"], expansions)
                p["velocity"] = velocity
                p["discovered_via"] = f.get("via", "seed")
                # store as nugget so the normal pipeline also sees it
                db.upsert_raw(source=f"deep_{which}",
                              title=f["trend"][:80],
                              external_id=f["trend"].lower()[:200],
                              extra={"deep_intel": True,
                                     "velocity": velocity})
                verified.append(p)
                if len(verified) >= max_trends // 2:
                    break
            verified.sort(key=lambda p: -p["velocity"])
            out[which] = verified
            log.info("deep %s: %d/%d verified trends", which,
                     len(verified), len(found))
    except Exception:  # noqa: BLE001
        log.exception("beauty-intel failed (isolated)")
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    r = run()
    print(json.dumps(r, indent=2, ensure_ascii=False)[:1500])
