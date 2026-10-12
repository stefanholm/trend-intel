"""Temu trending products — homepage embeds goodsName titles (escaped JSON)."""
import codecs
import re
import time
import random
import urllib.request
import logging

log = logging.getLogger("trend_intel.temu")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
     "Accept-Language": "en-US,en;q=0.9"}


def _clean(t):
    t = codecs.decode(t, "unicode_escape").encode("latin-1", errors="ignore").decode("utf-8", errors="replace")
    t = re.sub(r"\s+", " ", t).strip(" ,.-")
    return t[:90]


def harvest(db, verbose=False):
    count = 0
    try:
        req = urllib.request.Request("https://www.temu.com/", headers=UA)
        body = urllib.request.urlopen(req, timeout=20).read().decode(
            "utf-8", errors="replace")
        names = re.findall(r'goodsName\\?":\\?"([^"\\]{6,120})', body)
        seen = set()
        for n in names:
            t = _clean(n)
            if not t or t.lower() in seen or any(
                    x in t for x in ("Phone Case", "Charger", "Cable")):
                continue
            seen.add(t.lower())
            db.upsert_raw(source="temu", title=t,
                          external_id=t.lower()[:200])
            count += 1
    except Exception as e:  # noqa: BLE001
        log.warning("temu failed: %s", e)
    if verbose:
        print(f"[temu] {count} items")
    return count
