"""Nugget extraction & scoring from collected raw items.

Score model (demand dominates; freshness & ad-presence are tiebreakers only):
    demand    = log10(traffic or 1000) normalized, plus multi-source corroboration
    freshness = 1.0 when first seen < 24h ago, decaying to 0 over 14 days
    score     = 0.6*demand + 0.3*freshness + 0.1*corroboration
"""
import json
import math
import re
import time
from pathlib import Path
from datetime import datetime

# --- intake gate filters (§1a-style junk kill, adapted to trend intel) ---
CELEB_NAME_RE = re.compile(
    r"\b(hailey bieber|kylie jenner|selena gomez|taylor swift|rihanna|"
    r"huda beauty|by mario|matte lip mud|dedendorff|balenciaga|prada|"
    r"gucci|chanel|dior|mugler|loewe|khaite|the row|skims|fenty|rare beauty|"
    r"ghostrunner|rhode|ellen\b|oprah|beyonce|billie eilish|sabrina carpenter|"
    r"\bloop earplugs\b|\bloop\b.{0,20}earplug)",
    re.I)

CELEB_RE = re.compile(
    r"\b(goes|goes pantsless|steps out|spotted|strips off|flashes|"
    r"deaths?|dies|killed|arrested|charged|lawsuit|verdict|"
    r"dating|breaks? up|engaged|pregnant|divorce)\b", re.I)
NAME_RE = re.compile(r"^[A-Z][a-z]+([ -][A-Z][a-z'-]+)+$")
JUNK_TOKENS = re.compile(r"\b(looks gross|looks oily|looks bad|tanguy|soccer field|"
                         r"for the elderly|for ps5|not kindle|e-reader cards|"
                         r"vogue|usa|2025|meaning|list|to sell|owala|over the years)\b", re.I)
SPEC_RE = re.compile(r"\d+(\.\d+)?\s*(HD|FHD|4K|inch|\")", re.I)
PROMO_RE = re.compile(r"\b(promo|code|sale|discount|coupon|save \d+%|deal)\b", re.I)

# a trend needs at least one visual noun to be image-search shaped
VISUAL_HINTS = re.compile(
    r"\b(dress|coat|scarf|skirt|bag|shoe|boot|hat|knit|sweater|jeans|denim|"
    r"kitchen|lamp|table|chair|sofa|rug|nail|manicure|hair|makeup|lipstick|"
    r"coffee|tea|matcha|cake|pasta|salad|drink|cocktail|garden|beach|"
    r"interior|bedroom|living room|wedding|birthday|party|autumn|summer|"
    r"winter|spring|outfit|style|trend|color|colour|home|decor|"
    r"jacket|pajamas|pyjamas|robe|swimsuit|bikini|sweater|hoodie|blazer|"
    r"vest|cardigan|bodysuit|bralette|lingerie|corset|stockings|sleepwear|"
    r"loungewear|leggings|sandals|sneakers|heels|loafers|pumps|flats|"
    r"lash|brow|serum|balm|shampoo|conditioner|soap|candle|diffuser|"
    r"mirror|vase|frame|basket|blanket|pillow|cushion|curtain|towel|"
    r"duvet|quilt|sheets|organizer|holder|stand|rack|shelf|crate|bin|"
    r"gum|bitters|supplement|pickleball|paddle|racket|earplugs|"
    r"earrings|necklace|bracelet|ring|watch|sunglasses|headband|"
    r"backpack|tote|clutch|wallet|belt|hat|cap|gloves|scarf wrap|"
    r"set|kit|tool|brush|comb|sponge|loofah|razor|trimmer|"
    r"mat|block|band|strap|case|pouch|sleeve|dock|mount|"
    r"filament|printer|paddle board|yoga|pilates|kettle|bottle|"
    r"mug|tumbler|cup|glass|plate|bowl|tray|board|coaster|"
    r"lamp|light|bulb|fixture|chandelier|pendant|sconce|"
    r"plant|pot|planter|wreath|garland|ornament|decal|sticker|"
    r"racket|grip|tape|bandage|sleeve|sock|shaper|cushion)\b", re.I)





NON_VISUAL_TOPIC_RE = re.compile(
    r"\b(vs|match|score|final|semi|league|cup|championship|olympic|match|transfer|\n\\b\\b"
    r"election|parliament|minister|president|senate|government|policy|tax|court|judge|\n"
    r"police|gendarmerie|fire|accident|crash|storm|earthquake|hurricane|flood|\n"
    r"royale|royal|famille|prince|princess|king|queen|\n"
    r"stock|shares|market|billion|million dollar|merger|acquisition|earnings|\n"
    r"series|episode|season|netflix|streaming|trailer|review|box office|\n"
    r"city|town|commune|province|region|airport|station|gare|"
    r"price|deal|cheap|discount|black friday|cyber|nz|australia|reviews|restaurant|menu|near me|nearby|recipe|lyrics|song|album|spotify|concert|"
    r"OEM|fender|flares|slip-on|refurbished|certified|bundle|pack of|"
        r"buffet|work from home|jobs?|how to|diy|tutorial|tiktok shop|inspo|"
    r"vendor|trendz|blush trend it up|games? online|games? free|"
            r"decorating ideas|home interior trending|games? offline|games? online|"
    r"tiktok|current makeup|teen outfit ideas|autumn 2026|summer 2026|"
    r"reddit|best buy|insurance|moon rover|lego|opera mens|from uk|"
    r"map|maps|break from|gifts for dad|gifts for mom|black girl|black woman|for dark skin|before and after|club monaco|mac plac|maybelline)\b", re.I)

BRAND_RE = re.compile(
    r"\b(kmart|target|walmart|shein|zara|hm|h&m|uniqlo|nike|adidas|puma|"
    r"meshki|aje|forever new|forever 21|asos|revolve|nordstrom|zalando|boohoo|"
    r"showpo|levis|levi|wrangler|carhartt|amazon|temu|tiktok shop|"
        r"lululemon|aritzia|reformation|free people|urban outfitters|beginning boutique|"
    r"victoria secret|victorias secret|calvin klein|skims|savage x|fenty|"
    r"kali uchis|doja cat|sabrina carpenter|taylor swift|billie eilish|"
    r"olivia rodrigo|selena gomez|kim kardashian|kylie jenner|rihanna)\b", re.I)


_DICT = None


def _wordlist():
    """System english wordlist (macOS ships /usr/share/dict/words)."""
    global _DICT
    if _DICT is None:
        _DICT = set()
        paths = [
            "/usr/share/dict/words",
            str(Path(__file__).resolve().parent.parent / "config" / "wordlist.txt"),
        ]
        for p in paths:
            try:
                with open(p, errors="ignore") as f:
                    _DICT |= {w.strip().lower() for w in f if w.strip().isalpha()}
            except OSError:
                continue
    return _DICT


def _area_vocab_hit(title):
    """True when any area's match vocabulary appears in the title
    (word-boundary match — 'bob' must not match 'bobby')."""
    try:
        from .areas import AREAS
        tl = " " + re.sub(r"[^a-z0-9]+", " ", title.lower()).strip() + " "
        for a in AREAS.values():
            for m in a["match"]:
                m = re.sub(r"[^a-z0-9]+", " ", m.strip().lower()).strip()
                if m and " " + m + " " in tl:
                    return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _looks_like_placename(title):
    """Heuristic: long alphabetic token that is neither an english word nor a
    known visual/fashion term is almost always a locality (vadapalani)."""
    words = _wordlist()
    if not words:
        return False
    known_visual = set(VISUAL_HINTS.pattern.lower().replace("\\", " ").split("|"))
    try:
        from .areas import AREAS
        for a in AREAS.values():
            known_visual |= {m.strip().lower() for m in a["match"]}
    except Exception:  # noqa: BLE001
        pass
    for tok in re.split(r"[^a-zA-Z]+", title.lower()):
        tok = tok.strip()
        if len(tok) < 7:
            continue
        if tok in words or tok in known_visual or BRAND_RE.search(tok):
            continue
        # tolerate english derivation (prefixes/suffixes) wordlists miss
        bases = {tok}
        for pre in ("re", "un", "de", "pre", "over", "anti"):
            if tok.startswith(pre):
                bases.add(tok[len(pre):])
        for b in list(bases):
            for suf in ("ing", "ings", "ize", "ization", "ment", "able",
                        "ify", "ly", "er", "ers"):
                if b.endswith(suf):
                    bases.add(b[:-len(suf)])
                    bases.add(b[:-len(suf) - 1])
        if any(b in words for b in bases):
            return False
        return True
    return False




GENERIC_NOUNS = {
    "hair", "color", "colour", "nails", "nail", "makeup", "outfit", "dress",
    "style", "fashion", "decor", "beauty", "food", "travel", "gadget",
    "tech", "bag", "bags", "accessory", "accessories", "jewelry", "home",
    "interior", "kitchen", "hairstyle", "look", "design", "room", "drink",
    "drinks", "cocktail", "shoes", "clothes", "clothing", "wedding",
    "aesthetic", "style", "trend", "trends", "lip", "blush", "liner",
    "dresses", "makeup looks", "haircuts", "nails",
    "decorating", "apartments", "inspo", "vendor", "trendz",
}
META_FILLER = re.compile(
    r"^(\d{4}|20\d\d|trends?|trend|trendz|ideas?|idea|now|right now|new|latest|"
    r"looks?|styles?|for|women|men|women's|men's|girl|girls|female|male|"
    r"fall|autumn|summer|winter|spring|inspiration|guide|tips?|names?|"
    r"meaning|wheel|quiz|quizzes|games?|free|news|august|september|"
    r"october|november|december|january|february|march|april|may|june|"
    r"july)$", re.I)


QUESTION_RE = re.compile(
    r"^(why|what|how|when|where|who|which|is|are|do|does|did|can|could|should)\b",
    re.I)


def is_meta_query(title):
    """True for queries that SEARCH FOR trend lists, not trends themselves:
    "hair color trends fall 2026", "autumn outfit ideas". After stripping
    filler (years, seasons, 'trends', 'ideas', demographic qualifiers) and
    generic category nouns (hair, dress, nails...), nothing concrete remains."""
    words = [w for w in re.split(r"[^a-zA-Z0-9']+", title.lower()) if w]
    remaining = [w for w in words
                 if not META_FILLER.match(w) and w not in GENERIC_NOUNS]
    return len(remaining) == 0




BASIC_DESCRIPTORS = {
    "white", "black", "blue", "green", "pink", "grey", "gray", "beige",
    "long", "short", "mini", "midi", "maxi", "summer", "winter", "fall",
    "autumn", "spring", "simple", "basic", "classic", "plain", "solid",
    "set", "sets", "piece", "women", "men", "girl", "kids", "home",
    "linen", "cotton", "silk", "wool", "leather", "denim", "satin",
    "shirt", "top", "skirt", "gown", "candle", "vase", "mug", "lamp",
    "tote", "handbag", "purse", "sneakers", "heels", "boots", "coat",
    "jacket", "cardigan", "blazer", "sweater", "hoodie", "scarf", "hat",
    "belt", "watch", "earrings", "necklace", "bracelet", "ring",
    "backpack", "clutch", "wallet", "case", "cover", "stand",
    "yellow", "red", "purple", "orange", "brown", "navy", "cream",
    "dresser", "nightstand", "sideboard", "cabinet", "stool", "bench",
    "gimbal", "tripod", "laptop", "monitor", "keyboard", "mouse",
}


def is_baseline(title):
    """Evergreen baseline subject, not a trend: every content word is a
    generic noun or basic descriptor (white/long/midi/linen...) with no
    distinctive trend token (butter yellow, crochet donut, wolf cut...)."""
    words = [w for w in re.split(r"[^a-zA-Z0-9']+", title.lower()) if w]
    content = [w for w in words
               if not META_FILLER.match(w)]
    if not content:
        return False
    return all(w in GENERIC_NOUNS or w in BASIC_DESCRIPTORS for w in content)


def looks_like_junk(title, extra=None):
    """Return a reject reason string or None if clean (v2: stricter topic gate)."""
    t = title.strip()
    if not t or len(t) < 4:
        return "too_short"
    if CELEB_RE.search(t):
        return "headline_fragment"
    if JUNK_TOKENS.search(t):
        return "junk_token"
    try:
        from . import autolearn
        hit = autolearn.is_banned(t)
        if hit:
            autolearn.note_reject_hit(hit)
            return "learned_ban"
    except Exception:  # noqa: BLE001
        pass
    if NAME_RE.match(t) and not VISUAL_HINTS.search(t) and not _area_vocab_hit(t):
        return "person_name"
    words = t.lower().split()
    if (len(words) == 2 and all(w.isalpha() for w in words)
            and not VISUAL_HINTS.search(t) and not _area_vocab_hit(t)
            and " " in t.strip()):
        return "person_name"
    words = t.lower().split()
    if (len(words) == 2 and all(w.isalpha() for w in words)
            and not VISUAL_HINTS.search(t) and not _area_vocab_hit(t)
            and " " in t.strip()):
        return "person_name"
    words = t.lower().split()
    if (len(words) == 2 and all(w.isalpha() for w in words)
            and not VISUAL_HINTS.search(t) and not _area_vocab_hit(t)
            and " " in t.strip()):
        return "person_name"
    if SPEC_RE.search(t):
        return "spec_number"
    if PROMO_RE.search(t):
        return "promo"
    if BRAND_RE.search(t):
        return "brand_token"
    if CELEB_NAME_RE.search(t):
        return "celebrity_name"
    if is_meta_query(t):
        return "meta_query"
    if QUESTION_RE.match(t):
        return "question_query"
    if is_baseline(t):
        return "baseline"
    if len(t.split()) > 9:
        return "listing_junk"
    # junk news/event/place/topic terms — never image-search shaped
    if NON_VISUAL_TOPIC_RE.search(t):
        return "non_visual_topic"
    # everything must carry at least one concrete visual hint to be a nugget;
    # area vocabulary counts as visual (destinations, gadgets are subjects)
    if not VISUAL_HINTS.search(t) and not _area_vocab_hit(t):
        return "non_visual"
    if _looks_like_placename(t):
        return "placename_token"
    return None


def normalize_title(title):
    t = re.sub(r"\s+", " ", title.strip().lower())
    return t


def freshness_score(first_seen, now=None):
    now = now or time.time()
    age_days = max(0, (now - first_seen) / 86400)
    if age_days <= 1:
        return 1.0
    return max(0.0, 1.0 - (age_days - 1) / 14.0)


def demand_score(item):
    """Approx traffic from RSS ('500K+') or pytrends value (0-100)."""
    approx = item.get("approx_traffic")
    if approx:
        return min(1.0, math.log10(max(10, approx)) / 7.0)
    extra = item.get("extra_json")
    if extra:
        try:
            e = json.loads(extra)
            v = e.get("value")
            if v is not None:  # pytrends 0-100
                return min(1.0, float(v) / 100.0)
        except (ValueError, TypeError):
            pass
    if item.get("seen_count", 1) > 1:  # seen on multiple polls -> some stickiness
        return 0.4
    return 0.25


def build_nuggets(db, min_score=0.3, window_days=7, dry_run=False):
    """Group raw items by normalized title, apply the intake gate, score, store."""
    since = time.time() - window_days * 86400
    items = db.recent_raw(since=since, limit=5000)

    groups = {}
    for it in items:
        key = normalize_title(it["title"])
        groups.setdefault(key, []).append(it)

    accepted, rejected = 0, 0
    now = time.time()
    for key, rows in groups.items():
        display_title = max(rows, key=lambda r: len(r["title"]))["title"].strip()
        reason = looks_like_junk(display_title)
        if reason:
            rejected += 1
            if not dry_run:
                for r in rows:
                    db.set_nugget_status(display_title, "rejected", reason)
            continue

        # corroboration: multiple sources carrying the same term
        sources = {r["source"] for r in rows}
        corroboration = min(1.0, len(sources) / 3.0)

        demand = max(demand_score(r) for r in rows)
        fresh = freshness_score(min(r["first_seen"] for r in rows), now)
        score = 0.6 * demand + 0.3 * fresh + 0.1 * corroboration

        if score < min_score:
            continue
        if not dry_run:
            db.upsert_nugget(
                title=display_title,
                source_ids=[r["id"] for r in rows][:10],
                sources=sorted(sources),
                score=round(score, 3),
                demand=round(demand, 3),
                freshness=round(fresh, 3),
                ad_presence=0.0,
                keywords=[w for w in key.split() if len(w) > 2][:8],
            )
        accepted += 1

    return {"accepted": accepted, "rejected": rejected,
            "considered": len(groups), "since": datetime.utcfromtimestamp(since).isoformat()}
