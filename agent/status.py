#!/usr/bin/env python3
"""Quick status/inspection CLI.

    python agent/status.py            # agent state + top nuggets
    python agent/status.py --top 30
"""
import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    status = BASE / "data" / "status.json"
    if status.exists():
        s = json.loads(status.read_text())
        print(f"agent: {s['state']}  (updated {s['updated_at']})")
        if s.get("cycle"):
            print(f"last cycle: {s['cycle']}")
        if s.get("error"):
            print(f"error: {s['error'][:200]}")
    else:
        print("agent: no status yet (not started?)")

    from trend_intel.api import IntelAPI
    api = IntelAPI(BASE / "data" / "intel.db")
    st = api.stats()
    print(f"active nuggets: {st['active_nuggets']}")
    for n in api.top(args.top):
        print(f"  {n['score']:.2f}  {n['title']}  {','.join(n['sources'][:2])}")


if __name__ == "__main__":
    main()
