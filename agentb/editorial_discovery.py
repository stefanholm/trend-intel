"""Editorial/magazine/retail discovery — Google News RSS site-filtered feeds.

Beauty: Allure, Byrdie, Into The Gloss + retailers Sephora, Ulta, Lyko,
Kicks. Lingerie/intimates: Vogue, Harper's Bazaar, Elle, Cosmopolitan,
trade press (Lingerie Insight) + retailers Hunkemöller, Intimissimi,
Lindex, Change, H&M, Skims, Victoria's Secret, Agent Provocateur,
Coco de Mer, Lounge Underwear.

Retail campaign headlines carry the newest product vocabulary (sheer
lace balconette, mesh bodysuit) before search demand shows it. The
brand filter in beauty_intel_agent strips the retailer name itself —
only the visual language survives to the manifest.

Never raises; each feed is isolated. Titles only.
"""
import re
import time
import urllib.request
import xml.etree.ElementTree as ET

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0"}

FEEDS = {
    "beauty": [
        ("allure", "site:allure.com makeup OR skincare"),
        ("byrdie", "site:byrdie.com makeup OR nails"),
        ("intothegloss", "site:intothegloss.com beauty"),
        ("sephora", "site:sephora.com new beauty"),
        ("ulta", "site:ulta.com beauty trend"),
        ("vogue", "site:vogue.com beauty trend"),
        ("pinterest", "site:pinterest.com beauty OR makeup ideas"),
    ],
    "adult": [
        ("lingerieinsight", "site:lingerieinsight.com"),
        ("hunkemoller", "site:hunkemoller.com lingerie"),
        ("intimissimi", "site:intimissimi.com collection"),
        ("lindex", "site:lindex.com lingerie"),
        ("vs", "site:victoriassecret.com lingerie"),
        ("agentprovocateur", "site:agentprovocateur.com"),
        ("cocodemer", "site:cocodem.com"),
        ("loungeunderwear", "site:loungeunderwear.com"),
        ("vogue", "site:vogue.com lingerie OR boudoir trend"),
        ("harpersbazaar", "site:harpersbazaar.com lingerie"),
        ("elle", "site:elle.com lingerie OR sleepwear"),
        ("cosmopolitan", "site:cosmopolitan.com lingerie"),
        ("pinterest", "site:pinterest.com lingerie OR boudoir ideas"),
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


def harvest(which, max_items=40, run_all=False):
    """Yield trend phrases from magazine/retail coverage. Never raises."""
    titles = []
    for _name, query in FEEDS.get(which, []):
        try:
            titles.extend(_headlines(query))
        except Exception:  # noqa: BLE001
            continue
        time.sleep(1.2)
    return titles[:max_items]


if __name__ == "__main__":
    print(harvest("beauty")[:5], harvest("adult")[:5])
