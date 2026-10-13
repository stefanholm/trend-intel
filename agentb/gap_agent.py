"""Agent B — Commercial Demand Context (gap / saturation intelligence).

Runs at NIGHT while Agent A sleeps: licenses Agent A's candidates with
supply knowledge ("is stock already flooded?") and failure knowledge.

NOT another trend scrape. It answers: will this image be BOUGHT?
  - supply_bucket: flooded | competitive | thin | unknown
  - action: keep | expand_or_differentiate | drop
  - gap_hint: what formula the niche is missing

Memory-light by design:
  - runs as its own short-lived process (launched by launchd at night)
  - caps phrases per run (8-12), caches probes 24h, streams results to disk
  - no thumbnails, no VLM, no pixels — metadata only (copyright-safe)

Probes (in order, first that works):
  1. Adobe Stock search page (result count + titles) — usually OK from
     residential IPs; 403 from datacenter IPs
  2. DuckDuckGo site: SERP — fallback density signal
  3. unknown bucket — degrade gracefully, never block
"""
import json
import re
import time
import random
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from collections import Counter

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"
CACHE = DATA / "gap_cache.json"
OUT = DATA / "demand_context.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [gap] %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler(DATA / "gap_agent.log")])
log = logging.getLogger("gap")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}


def _get(url, timeout=15):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=timeout).read().decode(
        "utf-8", errors="replace")


# ---------------------------------------------------------------- probing
def probe_adobe(phrase):
    """Direct Adobe Stock search: hit count + top titles."""
    url = ("https://stock.adobe.com/search?k="
           + urllib.parse.quote(phrase) + "&filters%5Bcontent_type%3Aphoto%5D=1")
    body = _get(url)
    m = re.search(r"(\d[\d,\.\s]{2,15}?)\s*(?:results|resultaten|treffer|risultati)",
                  body, re.I)
    hits = int(m.group(1).replace(",", "").replace(".", "").strip()) if m else None
    titles = [re.sub(r"<[^>]+>", "", t).strip()
              for t in re.findall(r'title="([^"]{8,90})"', body)][:20]
    if hits is None and not titles:
        return None
    return {"hits": hits, "titles": titles}


def probe_ddg(phrase):
    """DuckDuckGo site: SERP fallback: result count as density proxy."""
    q = urllib.parse.quote(f"site:stock.adobe.com {phrase}")
    body = _get(f"https://html.duckduckgo.com/html/?q={q}")
    if "challenge" in body.lower() or "anomaly" in body.lower():
        return None
    m = re.search(r"(\d[\d,]*)\s*(?:results)", body, re.I)
    links = len(re.findall(r'stock\.adobe\.com/\S+', body))
    if m is None and links == 0:
        return None
    return {"hits": (int(m.group(1).replace(",", "")) if m else links * 5000),
            "titles": []}


_run_state = {"adobe_blocked": False}


def probe_shutterstock(phrase):
    """Shutterstock search: density proxy via result count."""
    slug = phrase.lower().replace(" ", "-")
    body = _get(f"https://www.shutterstock.com/search/{slug}")
    m = re.search(r"(\d[\d,\.\s]{2,15}?)\s*(?:results|matches|stock images)",
                  body, re.I)
    hits = int(m.group(1).replace(",", "").replace(".", "").strip()) if m else None
    return {"hits": hits, "titles": []} if hits else None


def probe_bing(phrase):
    """Bing Images count: broad web-image density (less stock-specific)."""
    import urllib.parse
    q = urllib.parse.quote(f'"{phrase}"')
    body = _get(f"https://www.bing.com/images/search?q={q}")
    m = re.search(r"(\d[\d,\.\s]{2,15}?)\s*(?:ERGEBNISSE|RESULTS|results)",
                  body, re.I)
    hits = int(m.group(1).replace(",", "").replace(".", "").strip()) if m else None
    return {"hits": hits, "titles": []} if hits else None


def probe_openverse(phrase):
    """Openverse API (CC image aggregator): clean result_count, no auth,
    reliable from any IP. Counts are ~1000x smaller than Adobe — classified
    with its own thresholds."""
    import urllib.parse
    body = _get("https://api.openverse.org/v1/images/?q="
                + urllib.parse.quote(phrase) + "&page_size=1")
    m = re.search(r'"result_count"\s*:\s*(\d+)', body)
    if not m:
        return None
    return {"hits": int(m.group(1)), "titles": [],
            "scale": "openverse"}  # marker: different thresholds


def probe(phrase, max_age_h=24):
    """Cached probe: never re-hit the same phrase within 24h. If Adobe 403s,
    it's IP-blocked for this run — skip to DDG immediately (saves minutes)."""
    cache = _load_json(CACHE, {})
    key = phrase.lower()
    entry = cache.get(key)
    if entry and time.time() - entry.get("ts", 0) < max_age_h * 3600:
        return entry
    result = None
    ladder = (probe_adobe, probe_shutterstock, probe_openverse, probe_bing, probe_ddg)
    fns = tuple(f for i, f in enumerate(ladder)
                if not (_run_state["adobe_blocked"] and i == 0))
    for fn in fns:
        try:
            result = fn(phrase)
            if result:
                result["probe"] = fn.__name__
                break
        except Exception as e:  # noqa: BLE001
            if fn is probe_adobe and "403" in str(e):
                _run_state["adobe_blocked"] = True
                log.info("adobe 403 for this IP — switching to SERP fallback")
                continue
            log.info("probe %s failed for %r: %s", fn.__name__, phrase, str(e)[:60])
        time.sleep(random.uniform(6, 12))  # gentle between probes
    if result is None:
        result = {"hits": None, "titles": [], "probe": "unavailable"}
    result["ts"] = int(time.time())
    cache[key] = result
    CACHE.write_text(json.dumps(cache))
    return result


# ------------------------------------------------------------- analysis
def classify_supply(hits, scale="adobe"):
    if hits is None:
        return "unknown"
    if scale == "openverse":
        # CC-aggregator counts: ~1000x smaller than Adobe
        if hits >= 1000:
            return "flooded"
        if hits >= 150:
            return "competitive"
        return "thin"
    if hits >= 100_000:
        return "flooded"
    if hits >= 20_000:
        return "competitive"
    return "thin"


TITLE_NOUN_RE = re.compile(
    r"\b(glass|hand|hands|table|counter|cafe|macro|closeup|close-up|"
    r"woman|women|man|men|pour|pouring|holding|kitchen|bedroom|bathroom|"
    r"outdoor|indoor|studio|still life|flat lay|top view|copy space)\b", re.I)


def build_formula(titles):
    """Dominant visual formula from competitor titles."""
    if not titles:
        return None, None
    nouns = Counter()
    for t in titles:
        for n in TITLE_NOUN_RE.findall(t):
            nouns[n.lower()] += 1
    formula = ", ".join(f"{n}" for n, _ in nouns.most_common(4)) or None
    # gap hint: titles dominated by still/flat vocabulary but no action nouns
    action = sum(v for n, v in nouns.items()
                 if n in ("pour", "pouring", "holding", "hand", "hands"))
    gap = None
    if nouns and action < len(titles) * 0.3:
        gap = "living-frame differentiation: add hands/pour/usage — competitor titles are static"
    return formula, gap


def action_for(bucket, hotness):
    if bucket == "flooded":
        return "expand_or_differentiate"
    if bucket == "thin" and hotness and hotness >= 0.12:
        return "keep"          # demand + thin supply = best slot
    if bucket == "thin":
        return "keep_watch"
    if bucket == "competitive":
        return "keep"
    return "keep"              # unknown: don't block on missing data


# ---------------------------------------------------------------- runner
def _load_json(path, default):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


def top_candidates(limit=10):
    """Best verified candidates from Agent A's shortlist. Falls back to
    top-hotness entries when nothing is verified (GT rate-limited cycles) —
    Agent B always has something to probe."""
    sl = _load_json(DATA / "manifest_shortlist.json", {})
    all_c = []
    verified = []
    for c in sl.get("shortlist", []):
        entry = {"phrase": c["title"],
                 "hotness": c.get("hotness", 0),
                 "area": c.get("area"),
                 "image_need": c.get("image_need")}
        all_c.append(entry)
        if c.get("verified_by_google_trends") or c.get("source_count", 0) >= 2:
            verified.append(entry)
    return (verified or all_c)[:limit]


def false_demand_from_report(report_path, limit=8):
    """Titles your render pipeline already burned (QC failures) — candidate
    ban roots: if supply is ALSO flooded, the root should be dropped."""
    burned = _load_json(report_path, {})
    return [b for b in burned.get("burned", [])][:limit]


def run(max_phrases=10):
    candidates = top_candidates(max_phrases)
    queries = []
    for c in candidates:
        queries.append(c)
    log.info("gap run: %d candidates", len(queries))
    results = []
    for c in queries:
        p = probe(c["phrase"])
        bucket = classify_supply(p.get("hits"), p.get("scale", "adobe"))
        formula, gap = build_formula(p.get("titles") or [])
        results.append({
            "phrase": c["phrase"],
            "area": c.get("area"),
            "image_need": c.get("image_need"),
            "hotness": c.get("hotness"),
            "adobe_approx_hits": p.get("hits"),
            "supply_bucket": bucket,
            "probe_source": p.get("probe"),
            "top_formula": formula,
            "gap_hint": gap,
            "action": action_for(bucket, c.get("hotness")),
        })
        log.info("%-38s %s (%s) -> %s", c["phrase"][:38], bucket,
                 p.get("hits") or "?", results[-1]["action"])
    out = {
        "updated_at": int(time.time()),
        "legend": {
            "supply_bucket": "flooded (>=100k Adobe hits) | competitive (20-100k) | thin (<20k) | unknown (probe blocked)",
            "action": "keep | expand_or_differentiate (flooded: force specific angle) | keep_watch",
            "gap_hint": "formula competitors are NOT doing — your differentiation",
            "top_formula": "dominant nouns in competitor titles",
        },
        "queries": results,
    }
    OUT.write_text(json.dumps(out, indent=2))
    log.info("wrote %s (%d queries)", OUT, len(results))
    return out


if __name__ == "__main__":
    run()
