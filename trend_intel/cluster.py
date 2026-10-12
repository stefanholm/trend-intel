"""Variant clustering: collapse near-duplicate trends into one entry.

"hair color trends 2026", "hair color trends fall 2026", "hair color trends
2026 female" are ONE trend with variants. The report shows the cluster
headline once, with variant_count and the variant titles, so lists stay
diverse instead of being padded by one query's autocomplete family.
"""
import re

_FILLER = re.compile(
    r"\b(2026|2027|2025|trends?|trend|now|new|ideas?|style|styles|for women|"
    r"for men|for girls|female|male|fall|autumn|summer|winter|spring|"
    r"women|men|girl|girls|outfit|look)\b", re.I)


def _key_terms(title):
    """Content words of a title, filler stripped — the cluster identity."""
    words = [w for w in re.split(r"[^a-z0-9]+", title.lower()) if w]
    core = [w for w in words if not _FILLER.match(w)]
    return set(core) if core else set(words)


def cluster_titles(entries):
    """Group entries into clusters by shared core terms.

    Two entries cluster when their core-term sets overlap >= 60% of the
    smaller set. Returns [{head, variants, variant_count, entry}].
    """
    clusters = []
    for e in entries:
        terms = _key_terms(e["title"])
        placed = False
        for c in clusters:
            inter = len(terms & c["terms"])
            smaller = min(len(terms), len(c["terms"]))
            if smaller and inter / smaller >= 0.6:
                c["variants"].append(e)
                # head = most specific title among near-equal hotness:
                # prefer the entry with more concrete core terms
                if (e["hotness"], len(_key_terms(e["title"]))) > \
                        (c["entry"]["hotness"], len(c["terms"])):
                    c["entry"] = e
                placed = True
                break
        if not placed:
            clusters.append({"terms": terms, "entry": e, "variants": [e]})
    out = []
    for c in clusters:
        head = c["entry"]
        variants = sorted({v["title"] for v in c["variants"]} - {head["title"]})
        out.append({
            "title": head["title"],
            "hotness": head["hotness"],
            "score": head.get("score"),
            "demand": head.get("demand"),
            "approx_traffic": head.get("approx_traffic"),
            "state": head["state"],
            "slope": head.get("slope"),
            "sources": head["sources"],
            "source_count": head.get("source_count", len(set(head["sources"]))),
            "verified_by_google_trends": head.get("verified_by_google_trends", False),
            "seen_count": head.get("seen_count", 1),
            "first_seen": head.get("first_seen"),
            "variant_count": len(c["variants"]),
            "variants": variants[:5],
        })
    out.sort(key=lambda x: -x["hotness"])
    return out
