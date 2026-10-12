"""Google autocomplete — free, fast, no auth, area-aware.

For every area seed + top nugget, autocomplete returns the queries people
actually type, ranked by popularity. This is a leading indicator: new
phrases appear here BEFORE they show volume in Google Trends.

Used as the "early emerging" harvester: the improvement layer compares
autocomplete suggestions against known nuggets to catch brand-new phrases.
"""
import json
import re
import time
import random
import urllib.parse
import urllib.request
import logging

log = logging.getLogger("trend_intel.autocomplete")

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}


def suggest(query, timeout=10):
    url = ("https://suggestqueries.google.com/complete/search?client=firefox&q="
           + urllib.parse.quote(query))
    try:
        req = urllib.request.Request(url, headers=UA)
        body = urllib.request.urlopen(req, timeout=timeout).read().decode(
            "utf-8", errors="replace")
        data = json.loads(body)
        return [s for s in data[1] if isinstance(s, str)][:8]
    except Exception as e:  # noqa: BLE001
        log.warning("autocomplete failed for %r: %s", query, e)
        return []


def harvest(db, queries, verbose=False):
    """Collect autocomplete suggestions for a list of seed queries."""
    count = 0
    for q in queries:
        for s in suggest(q):
            s = re.sub(r"\s+", " ", s).strip()[:80]
            if not s:
                continue
            db.upsert_raw(
                source="google_autocomplete",
                title=s,
                external_id=s.lower(),
                extra={"seed": q},
            )
            count += 1
        time.sleep(random.uniform(1.0, 2.5))
    if verbose:
        print(f"[autocomplete] {count} suggestions from {len(queries)} seeds")
    return count
