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

def sample_genes(genome, banned_tokens=None):
    """Thompson sampling: draw Beta(alpha, beta) per gene, pick the winner
    per bucket. Styles that render cleanly get chosen more; failing ones
    decay — without banning the underlying subject."""
    banned = [b.lower() for b in (banned_tokens or []) + BANNED_TOKENS]
    selected = {}
    for bucket, genes in genome.items():
        best_key, best = None, -1.0
        for key, st in genes.items():
            if any(b in st["prompt"].lower() for b in banned):
                continue
            draw = random.betavariate(max(0.5, st["alpha"]),
                                      max(0.5, st["beta"]))
            if draw > best:
                best, best_key = draw, key
        if best_key:
            st = genome[bucket][best_key]
            selected[bucket] = {
                "gene_id": best_key,
                "prompt_fragment": st["prompt"],
                "expected_win_rate": round(
                    st["alpha"] / (st["alpha"] + st["beta"]), 3),
            }
    return selected


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
