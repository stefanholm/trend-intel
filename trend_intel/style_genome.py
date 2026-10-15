"""Style Genome: modifiers become spliced genes, not standalone nuggets.

Fixes two structural problems:
- colors/hairstyles/accessories/gadgets/styles areas yield nothing as
  standalone subjects — buyers search "woman in sunlit cafe", not
  "yellow_color". These buckets become Style Genes, spliced onto verified
  Core Subjects in the shortlist.
- failure_learning only punishes (bans). This adds a positive loop:
  genes carry Thompson-sampling alpha/beta updated from render QC, so
  styles that render cleanly get selected more without burning subjects.

Verification oracle for visual/style terms: Google autocomplete
(web + shopping ds) — stateless, zero cooldown, and it actually covers
aesthetic vocabulary that Wikipedia pageviews never will.
('butter yellow' -> 10 shopping expansions; nonsense -> 0.)
Used as a THIRD oracle alongside Google Trends (macro demand) and
Wikipedia (big-concept trajectories), not a replacement.
"""
import json
import random
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
GENOME_PATH = DATA / "style_genome.json"

# Buckets that become genes instead of standalone render subjects
GENE_AREAS = {"colors", "hairstyles", "accessories", "gadgets",
              "styles", "yellow_color", "costume_cosplay"}

# banned in render batch rules (Portra etc.) — never seed into the genome
BANNED_TOKENS = ["portra", "nostalgic", "halation", "milky ambient",
                 "sepia", "1970s"]

DEFAULT_GENOME = {
    "colors": {
        "butter_yellow_ochre": {
            "prompt": "muted butter-yellow organic linen and warm ochre tonal accents",
            "alpha": 3.0, "beta": 1.0},
        "espresso_terracotta": {
            "prompt": "deep espresso brown, raw terracotta, unbleached oat palette",
            "alpha": 2.0, "beta": 1.0},
        "mineral_sage_slate": {
            "prompt": "mineral sage green and brushed architectural slate harmony",
            "alpha": 2.0, "beta": 1.0},
        "cherry_red_accent": {
            "prompt": "one saturated cherry-red accent against neutral wardrobe",
            "alpha": 2.0, "beta": 1.0},
    },
    "hairstyles": {
        "textured_clavicle_bob": {
            "prompt": "wind-tousled clavicle bob with flyaway strands catching rim light",
            "alpha": 2.5, "beta": 1.0},
        "silver_fox_taper": {
            "prompt": "salt-and-pepper textured crop, natural temple recession",
            "alpha": 2.5, "beta": 1.0},
        "claw_clip_updo": {
            "prompt": "tortoiseshell claw-clip updo with loose face-framing wisps",
            "alpha": 2.0, "beta": 1.0},
    },
    "accessories": {
        "acetate_editorial_frames": {
            "prompt": "translucent warm-amber acetate glasses, genuine lens refraction",
            "alpha": 2.5, "beta": 1.0},
        "woven_market_tote": {
            "prompt": "natural woven-canvas market tote with leather handles",
            "alpha": 2.0, "beta": 1.0},
    },
    "gadgets": {
        "e_ink_notepad": {
            "prompt": "ultra-thin matte e-ink notepad flat on table, zero glare, no logos",
            "alpha": 2.0, "beta": 1.0},
        "brushed_steel_espresso": {
            "prompt": "unbranded brushed-stainless manual espresso lever, micro-scratches, steam",
            "alpha": 2.5, "beta": 1.0},
    },
    "styles": {
        "sunlit_editorial_microcontrast": {
            "prompt": "85mm editorial photography, hard morning window sidelight, "
                      "3D pore micro-topography, fine vellus hair, full-focal-plane "
                      "micro-contrast",
            "alpha": 4.0, "beta": 1.0},
        "intimate_tungsten_grain": {
            "prompt": "35mm environmental lifestyle frame, warm 2700K practical lamp, "
                      "subtle film grain, tactile fabric weave",
            "alpha": 3.0, "beta": 1.0},
    },
}


def load_genome():
    try:
        return json.loads(GENOME_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return json.loads(json.dumps(DEFAULT_GENOME))


def save_genome(genome):
    GENOME_PATH.parent.mkdir(parents=True, exist_ok=True)
    GENOME_PATH.write_text(json.dumps(genome, indent=2, ensure_ascii=False),
                           encoding="utf-8")


# ---------------------------------------------------------------- oracle

def autocomplete_velocity(phrase):
    """Google autocomplete (web + shopping) as a zero-cooldown visual-trend
    oracle. Returns (verified, velocity_score, expansions)."""
    q = urllib.parse.quote_plus(phrase)
    urls = [
        f"https://suggestqueries.google.com/complete/search?client=firefox&q={q}",
        f"https://suggestqueries.google.com/complete/search?client=firefox&ds=sh&q={q}",
    ]
    suggestions = set()
    for url in urls:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if len(data) > 1 and isinstance(data[1], list):
                    suggestions.update(data[1])
        except Exception:  # noqa: BLE001
            pass
    n = len(suggestions)
    return n >= 3, min(100, n * 8), sorted(suggestions)[:6]


# ---------------------------------------------------------------- splicing

COOLDOWN_HOURS = 24.0

VIBE_KEYWORDS = {
    "warm_artisan": ["crochet", "knit", "wool", "ceramic", "pottery", "linen",
                     "craft", "bakery", "wooden", "hygge", "autumn", "cozy",
                     "boucle", "merino", "pumpkin", "candle"],
    "festive_seasonal": ["christmas", "advent", "holiday", "candle", "winter",
                         "lucia", "feast", "velvet", "celebration", "new year",
                         "gift", "gingerbread", "glögg", "sparkler"],
    "modern_b2b": ["office", "remote", "laptop", "fintech", "energy", "battery",
                   "startup", "architect", "studio", "meeting", "data",
                   "monitor", "e-ink", "smart home"],
    "sunlit_wellness": ["travel", "spa", "skincare", "yoga", "longevity",
                        "morning", "kitchen", "mediterranean", "hotel",
                        "bath", "matcha", "wellness", "pilates"],
    "editorial_allure": ["lingerie", "satin", "silk", "boudoir", "robe",
                         "intimates", "loungewear", "slip dress", "mesh"],
}


def detect_vibe(text):
    """Scene vibe from subject/gene text. editorial_allure wins when present
    (intimates subjects must never get tech gadgets spliced in)."""
    t = (text or "").lower()
    if any(k in t for k in VIBE_KEYWORDS["editorial_allure"]):
        return "editorial_allure"
    scores = {v: sum(1 for k in kws if k in t)
              for v, kws in VIBE_KEYWORDS.items()}
    best = max(scores, key=lambda v: scores[v])
    return best if scores[best] > 0 else "sunlit_wellness"


def _gene_vibe(gid, st):
    return st.setdefault("vibe", detect_vibe(gid.replace("_", " ") + " " + st["prompt"]))


def _recency_factor(st, now):
    """Anti echo-chamber: a gene used in the last 24h is scaled down to
    min 5%, forcing visual variety across batches (Adobe spam guard).
    Winners still dominate over time; they just can't monopolize."""
    last = st.get("last_used_ts") or 0
    if not last:
        return 1.0
    hours = max(0.0, (now - last) / 3600.0)
    return min(1.0, max(0.05, hours / COOLDOWN_HOURS))


def sample_genes(genome, banned_tokens=None, now=None, subject=None):
    """Thompson sampling with 24h recency cooldown + vibe locking: when a
    subject is given, each bucket is filtered to genes whose vibe matches the
    subject's (fallback: whole bucket) — no air-quality monitors in crochet
    scenes, no technical vests on advent tables. Franken-prompt prevention."""
    now = now or time.time()
    banned = [b.lower() for b in (banned_tokens or []) + BANNED_TOKENS]
    vibe = detect_vibe(subject) if subject else None
    selected = {}
    for bucket, genes in genome.items():
        if vibe:
            locked = {k: v for k, v in genes.items()
                      if _gene_vibe(k, v) == vibe}
            genes = locked or genes      # empty bucket -> fall back, never starve
        best_key, best = None, -1.0
        for key, st in genes.items():
            if any(b in st["prompt"].lower() for b in banned):
                continue
            draw = random.betavariate(max(0.5, st["alpha"]),
                                      max(0.5, st["beta"]))
            draw *= _recency_factor(st, now)
            if draw > best:
                best, best_key = draw, key
        if best_key:
            st = genome[bucket][best_key]
            st["last_used_ts"] = round(now, 2)
            now += 900.0          # stagger: same-batch entries diversify
            selected[bucket] = {
                "gene_id": best_key,
                "prompt_fragment": st["prompt"],
                "expected_win_rate": round(
                    st["alpha"] / (st["alpha"] + st["beta"]), 3),
            }
    save_genome(genome)
    return selected


SHOT_1_SAFE_BUCKETS = {"colors", "hairstyles", "accessories", "styles",
                       "yellow_color"}
SHOT_2_3_ONLY_BUCKETS = {"gadgets", "costume_cosplay"}


def shot_ladder(genes):
    """Split selected genes for NFE's 3-shot ladder: tight beauty headshot
    (shot 1) never gets gadgets/cosplay crammed next to a macro face."""
    return {
        "shot_1_beauty": {b: g for b, g in genes.items()
                          if b in SHOT_1_SAFE_BUCKETS},
        "shot_2_waist_up": {b: g for b, g in genes.items()
                            if b not in ("costume_cosplay",)},
        "shot_3_full_lifestyle": dict(genes),
    }


def splice(subject, genes):
    """Core Subject x Style Genes -> one render prompt."""
    parts = [subject.strip().rstrip(".")]
    for b in ("colors", "hairstyles", "accessories", "gadgets", "styles"):
        frag = genes.get(b, {}).get("prompt_fragment")
        if frag:
            parts.append(frag)
    return ", ".join(parts) + "."


def is_gene_area(area):
    return (area or "") in GENE_AREAS


# ---------------------------------------------------------------- render loop

STOPWORDS = {"with", "from", "that", "into", "this", "light", "natural",
            "warm", "soft", "subtle", "clean", "modern", "style", "editorial",
            "lifestyle", "portrait", "background", "high", "full", "deep",
            "real", "authentic", "color"}


def infer_used_genes(text, genome):
    """Zero-touch telemetry: detect which genes a render used from its
    prompt/report text. SAFER than the memo version: only ever called on
    QC'd render rows (known verdict), never free-form file scans, so a
    gene can never be rewarded just for being mentioned somewhere."""
    tokens = {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
              if len(w) >= 4 and w not in STOPWORDS}
    detected = {}
    for bucket, genes in genome.items():
        best, best_ratio = None, 0.0
        for gid, st in genes.items():
            slug = gid.lower().replace("_", " ")
            g_tokens = {w for w in re.findall(r"[a-z0-9]+", slug + " " + st["prompt"].lower())
                        if len(w) >= 4 and w not in STOPWORDS}
            overlap = tokens & g_tokens
            ratio = len(overlap) / max(1, min(len(g_tokens), 6))
            if len(overlap) >= 2 and ratio > best_ratio:
                best, best_ratio = gid, ratio
        if best and best_ratio >= 0.34:
            detected[bucket] = best
    return detected


def update_from_qc(gene_ids_by_bucket, passed):
    """Reward/penalize genes from a render's QC outcome. `passed` = the
    render's verdict was GOOD (or AES>=6). Positive loop: never bans the
    subject, only re-weights its style genes."""
    genome = load_genome()
    for bucket, gid in (gene_ids_by_bucket or {}).items():
        g = genome.get(bucket, {}).get(gid)
        if not g:
            continue
        if passed:
            g["alpha"] = round(g["alpha"] + 1.0, 2)
        else:
            g["beta"] = round(g["beta"] + 1.2, 2)
    save_genome(genome)
    return genome


def prune_genome(min_renders=10, min_win_rate=0.25):
    """Nightly: drop genes that got 10+ chances and stay under 25% wins.
    Keeps the genome honest without over-pruning young genes."""
    genome = load_genome()
    pruned = []
    for bucket in list(genome):
        for gid in list(genome[bucket]):
            g = genome[bucket][gid]
            n = g["alpha"] + g["beta"]
            if n >= min_renders and g["alpha"] / n < min_win_rate:
                pruned.append(f"{bucket}/{gid}")
                del genome[bucket][gid]
    if pruned:
        save_genome(genome)
    return pruned


MUTATION_POOL = {
    "colors": [
        "sun-washed saffron linen with travertine neutrals",
        "muted pistachio green and raw unbleached silk",
        "warm oat milk, smoked espresso, brushed bronze accents",
    ],
    "hairstyles": [
        "chin-length French bob with sunlit flyaway wisps",
        "low textured bun with matte acetate pin",
        "silver-streaked wavy lob with realistic scalp parting",
    ],
    "accessories": [
        "champagne-acetate optical frames with subtle lens refraction",
        "sculptural matte recycled-silver ear cuff with patina",
        "unbranded ceramic chronograph with worn suede strap",
    ],
    "gadgets": [
        "anodized-aluminum air quality monitor with soft LED glow",
        "brushed-steel pour-over coffee scale with condensation",
        "fabric-wrapped smart home energy display, no logos",
    ],
    "styles": [
        "50mm f/2.8 editorial lifestyle, warm tungsten bounce, "
        "crisp fabric weave, natural skin subsurface scattering",
        "35mm f/4 environmental storytelling, dappled courtyard "
        "sunlight through olive leaves, deep focal-plane clarity",
    ],
}


def breed_genome(champion_alpha=4.5, max_per_bucket=10):
    """Nightly after prune: champion genes (alpha >= 4.5, win >= 0.65)
    spawn one mutated sibling at alpha 2 / beta 1 — the pool evolves
    instead of shrinking to a static list. Never exceeds max per bucket."""
    genome = load_genome()
    bred = []
    for bucket, genes in genome.items():
        if len(genes) >= max_per_bucket:
            continue
        champions = [k for k, g in genes.items()
                     if g["alpha"] >= champion_alpha
                     and g["alpha"] / (g["alpha"] + g["beta"]) >= 0.65]
        pool = [m for m in MUTATION_POOL.get(bucket, [])
                if m.lower() not in {g["prompt"].lower() for g in genes.values()}
                and not any(b in m.lower() for b in BANNED_TOKENS)]
        if (champions or len(genes) < 4) and pool:
            prompt = random.choice(pool)
            key = "_".join(re.findall(r"[a-z]+", prompt.lower())[:3])[:40]
            if key not in genes:
                genome[bucket][key] = {
                    "prompt": prompt, "alpha": 2.0, "beta": 1.0,
                    "parent": champions[0] if champions else "seed_pool"}
                bred.append(f"{bucket}/{key}")
    if bred:
        save_genome(genome)
    return bred


SALES_DROPZONE = DATA / "sales_dropzone.txt"


def process_sales_dropzone(boost=5.0):
    """Zero-OAuth sales reflex: paste sold Adobe Stock titles (one per line)
    into data/sales_dropzone.txt. Each line matches genes via the same
    inference used on QC rows and gives a commercial-sale super-boost.
    Returns boosted gene list; file is consumed (cleared) after processing."""
    if not SALES_DROPZONE.exists():
        return []
    lines = [ln.strip() for ln in SALES_DROPZONE.read_text().splitlines()
             if ln.strip() and not ln.startswith("#")]
    if not lines:
        return []
    genome = load_genome()
    boosted = []
    for line in lines:
        used = infer_used_genes(line, genome)
        for bucket, gid in used.items():
            g = genome[bucket][gid]
            g["alpha"] = round(g["alpha"] + boost, 2)
            g["adobe_sales"] = int(g.get("adobe_sales", 0)) + 1
            boosted.append(f"{bucket}/{gid}")
    save_genome(genome)
    SALES_DROPZONE.write_text(
        "# Paste sold Adobe Stock image titles below (one per line) "
        "for +5.0 alpha boost:\n")
    return boosted


def seed_from_harvest(nuggets, area):
    """Add a harvested modifier as a new gene candidate in its bucket
    (starts optimistic: alpha 2, beta 1 — gets ~10 renders to prove itself)."""
    if not is_gene_area(area):
        return False
    genome = load_genome()
    bucket = "colors" if area == "yellow_color" else area
    for n in nuggets:
        key = re.sub(r"[^a-z0-9]+", "_", n["title"].lower()).strip("_")[:40]
        if not key or key in genome.get(bucket, {}):
            continue
        prompt = n["title"].lower().strip()
        if any(b in prompt for b in BANNED_TOKENS):
            continue
        genome.setdefault(bucket, {})[key] = {
            "prompt": prompt, "alpha": 2.0, "beta": 1.0,
            "seeded_from": n["title"], "seeded_at": int(time.time())}
    save_genome(genome)
    return True


if __name__ == "__main__":
    g = load_genome()
    save_genome(g)
    genes = sample_genes(g)
    print("sampled genes:", {k: v["gene_id"] for k, v in genes.items()})
    print()
    print(splice("Couple reviewing home energy monitor in sunlit kitchen", genes))
    print()
    for p in ["butter yellow", "clavicle bob hairstyle", "xyzzy nonsense"]:
        v, s, e = autocomplete_velocity(p)
        print(f"oracle {p!r}: verified={v} velocity={s} {e[:3]}")
