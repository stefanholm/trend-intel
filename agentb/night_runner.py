"""Agent B night runner — runs the demand-context agents once, then exits.

Memory-light by design: launchd starts it at 00:30, it does its work
(gap probes + buyer calendar, capped phrases, cached), writes its outputs,
and the process ENDS. No daemon, no resident memory.

Runs while Agent A sleeps (Agent A cycles 06:xx / 12:xx / 18:xx / 00:xx
boundaries — 00:30 lands in Agent A's quiet window).
"""
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))
sys.path.insert(0, str(BASE / "agentb"))

from agentb import gap_agent, calendar_agent  # noqa: E402


def main():
    t0 = time.time()
    print(f"[agentB] night run starting {time.strftime('%H:%M:%S')}")
    cal = calendar_agent.run()
    print(f"[agentB] calendar: {len(cal['need_windows'])} need windows "
          f"({sum(1 for w in cal['need_windows'] if 'NOW' in w['window_status'])} license-now)")
    try:
        gap = gap_agent.run(max_phrases=10)
        buckets = {}
        for q in gap["queries"]:
            buckets[q["supply_bucket"]] = buckets.get(q["supply_bucket"], 0) + 1
        print(f"[agentB] gap: {len(gap['queries'])} phrases probed, buckets: {buckets}")
    except Exception as e:  # noqa: BLE001
        print(f"[agentB] gap run failed (isolated): {e}")
    print(f"[agentB] done in {time.time() - t0:.0f}s — process exits (no resident memory)")


if __name__ == "__main__":
    main()
