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
    try:
        from agentb.beauty_intel_agent import run as beauty_intel_run
        bi = beauty_intel_run()
        print(f"[agentB] beauty-intel: {len(bi['beauty'])} beauty + "
              f"{len(bi['adult'])} adult deep profiles")
    except Exception as e:  # noqa: BLE001
        print(f"[agentB] beauty-intel failed (isolated): {e}")
    try:
        from trend_intel import style_genome
        style_genome.ensure_dropzone()   # operator channel always present
        pruned = style_genome.prune_genome()
        bred = style_genome.breed_genome()
        print(f"[agentB] genome: pruned {len(pruned)} weak style genes, "
              f"bred {len(bred)} mutations")
    except Exception as e:  # noqa: BLE001
        print(f"[agentB] genome prune failed (isolated): {e}")
    try:
        seeds = calendar_seeds(cal)
        print(f"[agentB] calendar-intent: {len(seeds)} window keywords "
              f"injected into Agent A seeds")
    except Exception as e:  # noqa: BLE001
        print(f"[agentB] calendar-intent failed (isolated): {e}")
    print(f"[agentB] done in {time.time() - t0:.0f}s — process exits (no resident memory)")


def calendar_seeds(cal, max_seeds=6, min_lead_days=21, max_lead_days=75):
    """Inject buyer-window keywords into Agent A's auto-managed seeds.

    The calendar knows WHAT buyers will need in 2-8 weeks; the seeds tell
    Agent A WHAT TO COLLECT next cycle. Closes the loop: window opens ->
    collection aims at it -> gate licenses it while the window is open.
    Writes into config/seeds.txt (auto-managed by agent.py, anchors are
    never touched — refresh_seeds re-adds anchors on top).
    """
    keywords = []
    for w in cal.get("need_windows", []):
        d = w.get("days_until", 99)
        # commercial horizon: buyers license 21-75 days out; <21d is a dead
        # window (render+upload+moderation+indexing eats the remaining time)
        if d > max_lead_days or d < min_lead_days:
            continue
        for kw in (w.get("keywords") or w.get("need_title") or "").split(","):
            kw = kw.strip()
            if kw and len(kw.split()) <= 4 and kw.lower() not in \
                    {k.lower() for k in keywords}:
                keywords.append(kw)
    keywords = keywords[:max_seeds]
    if not keywords:
        return []
    # own protected file: agent.py's refresh_seeds merges these like anchors
    # (writing into seeds.txt directly would get wiped on the next rebuild)
    cal_path = BASE / "config" / "calendar_seeds.txt"
    cal_path.parent.mkdir(parents=True, exist_ok=True)
    cal_path.write_text(
        "# AUTO-MANAGED by agentb/night_runner.py — buyer-window keywords\n"
        + "\n".join(keywords) + "\n")
    return keywords


if __name__ == "__main__":
    main()
