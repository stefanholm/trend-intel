"""Editorial/magazine discovery \u2014 Google News RSS site-filtered feeds.

 Vogue, Allure, Harper's Bazaar, Elle, Cosmopolitan, GQ, Byrdie,
 Refinery29 and the mainstream adult-intimates press release their
 trend coverage via RSS. Headlines carry shade/texture/style language
 ('cherry red lips', 'sheer lace slip') long before search demand shows
 it \u2014 editorial leads, autocomplete follows.

Never raises; each feed is isolated. Titles only.
"""
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0"}

MAGAZINES = {
    "beauty": [
        ("vogue", "site:vogue.com beauty trend"),
        ("allure", "site:allure.com makeup OR skincare"),
        ("harpersbazaar", "site:harpersbazaar.com beauty"),
        ("byrdie", "site:byrdie.com makeup OR nails"),
        ("refinery29", "site:refinery29.com beauty trends"),
        ("elle", "site:elle.com beauty"),
    ],
    "adult": [
        ("vogue", "site:vogue.com lingerie OR boudoir trend"),
        ("harpersbazaar", "site:harpersbazaar.com lingerie"),
        ("elle", "site:elle.com lingerie OR sleepwear"),
        ("cosmopolitan", "site:cosmopolitan.com lingerie"),
    ],
}


def _headlines(query, limit=15, timeout=10):
    url = ("https://news.google.com/rss/search?q="
           + re.sub(r"\s+", "+", query)
           + "&hl=en-US&gl=US&ceid=US:en")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        root = ET.fromstring(resp.read().decode("utf-8", errors="replace"))
    out = []
    for item in root.iter("item"):
        t = item.findtext("title") or ""
        t = re.sub(r"\s+", " ", t).strip()
        if t:
            out.append(t)
    return out[:limit]


def harvest(which, max_items=30, run_all=False):
    """Yield trend phrases from magazine coverage. Never raises."""
    titles = []
    for _name, query in MAGAZINES.get(which, [])[:5]:
        try:
            titles.extend(_headlines(query))
        except Exception:  # noqa: BLE001
            continue
        time.sleep(1.2)
    return titles[:max_items]


if __name__ == "__main__":
    print(harvest("beauty")[:5], harvest("adult")[:5])
