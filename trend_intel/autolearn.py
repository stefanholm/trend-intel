"""Auto-learning: the gate improves itself from its own rejects.

When re-gate rejects an item, the offending token pattern is extracted and
appended to config/learned_bans.json. The file loads at gate time and is
checked BEFORE the hardcoded rules — so the agent's own observations become
new bans without code changes. One-run validation per skill §7b: a learned
ban records when it was added and how many rejects it has caused; bans that
never fire again can be pruned.
"""
import json
import re
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
BANS_FILE = BASE / "config" / "learned_bans.json"

_cache = None
_dirty = False

# tokens that look like learnable junk (not common words)
_LEARNABLE = re.compile(r"^[a-z][a-z '-]{4,30}$", re.I)
_STOP = {"trend", "trends", "style", "fashion", "outfit", "makeup", "nail",
         "nails", "hair", "dress", "bag", "color", "colour", "home", "decor"}


def load():
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(BANS_FILE.read_text())
        except (OSError, ValueError):
            _cache = {"banned_tokens": {}}
        if "banned_tokens" not in _cache:
            _cache = {"banned_tokens": {}}
    return _cache


def is_banned(title):
    """Check title against learned bans. Returns ban token or None."""
    bans = load()["banned_tokens"]
    tl = title.lower()
    for tok in bans:
        if tok in tl:
            return tok
    return None


def record_reject(title, reason):
    """Extract a learnable token from a rejected title and add to bans.

    Only learns from specific reject classes where a single junk token is
    the cause (person names, brands, junk tokens). Stores first_seen +
    reject_count so ineffective bans can be pruned later."""
    if reason not in ("person_name", "brand_token", "junk_token",
                      "placename_token", "meta_query"):
        return None
    # learn the FULL distinguishing phrase, not single tokens that could
    # be ambiguous (e.g. 'sydney' is also a city). For person names, learn
    # the two-token name; for brand/junk tokens, learn the token.
    if reason == "person_name":
        m = re.search(r"([A-Za-z]+\s+[A-Za-z]+)", title)
        if m and not _trend_safe(m.group(1).lower()):
            tok = m.group(1).lower()
            if tok not in load()["banned_tokens"]:
                bans = load()["banned_tokens"]
                bans[tok] = {"reason": reason, "first_seen": int(time.time()),
                             "reject_count": 0, "source": "auto-learned"}
                _mark_dirty()
                return tok
        return None
    tokens = [t for t in re.split(r"[^A-Za-z']+", title.lower()) if t]
    for tok in tokens:
        if not _LEARNABLE.match(tok) or tok in _STOP:
            continue
        if len(tok) >= 5 and tok not in load()["banned_tokens"]:
            if _trend_safe(tok):
                continue
            bans = load()["banned_tokens"]
            bans[tok] = {"reason": reason, "first_seen": int(time.time()),
                         "reject_count": 0, "source": "auto-learned"}
            _mark_dirty()
            return tok
    return None


def note_reject_hit(token):
    bans = load()["banned_tokens"]
    if token in bans:
        bans[token]["reject_count"] = bans[token].get("reject_count", 0) + 1
        _mark_dirty()


def _trend_safe(tok):
    """Don't learn bans on words that appear in area vocab or visual hints."""
    try:
        from .areas import AREAS
        for a in AREAS.values():
            for m in a["match"]:
                if tok in m.lower():
                    return True
        from .scoring import VISUAL_HINTS
        if tok in VISUAL_HINTS.pattern.lower():
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _mark_dirty():
    global _dirty
    _dirty = True


def save():
    global _dirty
    if _dirty:
        BANS_FILE.parent.mkdir(parents=True, exist_ok=True)
        BANS_FILE.write_text(json.dumps(_cache, indent=2))
        _dirty = False


def prune_never_fired(max_age_days=30):
    """One-run validation: drop learned bans that never fired (skill §7b)."""
    bans = load()["banned_tokens"]
    cutoff = time.time() - max_age_days * 86400
    dead = [t for t, b in bans.items()
            if b.get("reject_count", 0) == 0 and b.get("first_seen", 0) < cutoff]
    for t in dead:
        del bans[t]
    if dead:
        _mark_dirty()
    return dead
