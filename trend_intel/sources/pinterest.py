"""Pinterest trends — free browser-facing JSON endpoints, polled politely.

Uses the same endpoints the trends.pinterest.com web page loads. If Pinterest
changes them, this source silently yields zero (harvest is exception-safe).
"""
import json
import re
import urllib.request

URL = "https://trends.pinterest.com/?stream={stream}"

STREAMS = ["top", "living", "style", "beauty", "food", "travel", "weddings"]


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; TrendIntelBot/1.0; +polite)",
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def harvest(db, streams=None, run_all=False, **_):
    streams = streams or STREAMS[:4]
    count = 0
    for stream in streams:
        try:
            body = _fetch(URL.format(stream=stream))
            # Pinterest embeds trending data in a script/JSON blob; extract titles.
            candidates = re.findall(r'"term"\s*:\s*"([^"]+)"', body)
            if not candidates:
                candidates = re.findall(r'"display"\s*:\s*"([^"]+)"', body)
            items = []
            seen = set()
            for c in candidates:
                c = c.strip()
                if not c or len(c) > 80 or c.lower() in seen:
                    continue
                seen.add(c.lower())
                items.append(c)
        except Exception as e:  # noqa: BLE001
            if run_all:
                print(f"[pinterest] {stream}: error {e}")
            continue
        for term in items[:20]:
            db.upsert_raw(
                source="pinterest_trends",
                title=term,
                external_id=term.lower(),
                extra={"stream": stream},
            )
            count += 1
        if run_all:
            print(f"[pinterest] {stream}: {len(items)} items")
    return count


if __name__ == "__main__":
    print(json.dumps({"note": "module; run collector.py instead"}))
