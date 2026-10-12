"""Google Trends related-queries via pytrends (optional; needs `pip install pytrends`).

Polite-use: small keyword batches (<=5 per payload, the API max), jittered delays,
exponential backoff on 429, session reuse. Only run every few hours.
"""
import random
import time
import logging

log = logging.getLogger("trend_intel.pytrends")


def _patch_urllib3_retry():
    """pytrends <4.9.2 uses Retry(method_whitelist=...), removed in urllib3 v2."""
    try:
        from urllib3.util.retry import Retry
        if "method_whitelist" not in Retry.__init__.__code__.co_varnames:
            import inspect
            sig = inspect.signature(Retry.__init__)
            if "allowed_methods" in sig.parameters:
                def _init(self, *a, **kw):
                    if "method_whitelist" in kw:
                        kw["allowed_methods"] = kw.pop("method_whitelist")
                    sig_bind_original(self, *a, **kw)
                _orig = Retry.__init__
                def _init_patched(self, *a, **kw):
                    kw.pop("method_whitelist", None)
                    if "method_whitelist" in kw:
                        kw["allowed_methods"] = kw["method_whitelist"]
                    _orig(self, *a, **kw)
                Retry.__init__ = _init_patched
    except Exception:  # noqa: BLE001
        pass


def harvest(db, seed_terms, run_all=False, min_delay=8.0, max_delay=16.0, **_):
    try:
        _patch_urllib3_retry()
        from pytrends.request import TrendReq
    except ImportError:
        if run_all:
            print("[pytrends] pytrends not installed; skipping")
        return 0

    count = 0
    try:
        pt = TrendReq(hl="en-US", tz=0, timeout=(10, 30), retries=2)
    except Exception as e:  # noqa: BLE001
        if run_all:
            print(f"[pytrends] init failed: {e}")
        return 0

    for batch in _chunks(seed_terms, 5):
        try:
            pt.build_payload(batch, timeframe="now 7-d")
            related = pt.related_queries() or {}
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) or "code 429" in str(e).lower():
                wait = 180 + random.uniform(0, 120)
                if run_all:
                    print(f"[pytrends] 429 rate-limited; backing off {wait:.0f}s")
                time.sleep(wait)
                continue
            if run_all:
                print(f"[pytrends] batch {batch}: error {e}")
            time.sleep(30)
            continue

        for term, data in related.items():
            for kind in ("rising", "top"):
                df = data.get(kind) if isinstance(data, dict) else None
                if df is None or df.empty:
                    continue
                for _, row in df.head(15).iterrows():
                    q = str(row.get("query", "")).strip()
                    if not q:
                        continue
                    val = row.get("value")
                    db.upsert_raw(
                        source=f"pytrends_{kind}",
                        title=q,
                        external_id=q.lower()[:200],
                        extra={"seed": term, "kind": kind, "value": None if val is None else float(val)},
                    )
                    count += 1
        time.sleep(random.uniform(min_delay, max_delay))
    return count


def _chunks(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]
