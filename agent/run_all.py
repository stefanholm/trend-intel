#!/usr/bin/env python3
"""Run everything once, in dependency order — get the whole system "on par".

Order matters:
  1. failure-learning  — read render reports, apply bans (DB changes first)
  2. agentb           — demand context + buyer calendar (probes live)
  3. agent A cycle    — collect, verify, breakout, gate, report
                        (gate consumes demand_context + bans apply to it)

Every step is isolated: a failure logs and the next step still runs.
Exit is always 0 unless --strict is passed.
"""
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"


def run_step(name, args, timeout_s):
    print(f"\n=== {name} ===")
    t0 = time.time()
    try:
        r = subprocess.run(args, cwd=str(BASE), timeout=timeout_s,
                           capture_output=True, text=True)
        tail = (r.stdout or r.stderr).strip().splitlines()[-12:]
        print("\n".join(tail) if tail else "(no output)")
        if r.returncode != 0:
            print(f"!!! {name} exited {r.returncode}")
            return False
        print(f"--- ok ({time.time() - t0:.0f}s)")
        return True
    except subprocess.TimeoutExpired:
        print(f"!!! {name} timed out after {timeout_s}s")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"!!! {name} failed: {e}")
        return False


def main():
    strict = "--strict" in sys.argv
    py = sys.executable
    ok = True

    ok &= run_step("1/3 failure-learning + sales dropzone",
                   [py, "-c",
                    "import sys; sys.path.insert(0, '.'); "
                    "from trend_intel.db import DB; "
                    "from trend_intel import failure_learning as fl; "
                    "ctx = fl.run(db=DB('data/intel.db')); "
                    "from trend_intel import style_genome as sg; "
                    "res = sg.process_sales_dropzone(); "
                    "print('sales:', res.get('boosted', []) or '[]', "
                    "'| consumed', res.get('consumed', 0), 'lines', "
                    "'| unmatched', len(res.get('unmatched', []))); "
                    f"print('rows:', ctx['n_rows'], "
                    f"'bans:', len(ctx['hard_ban_titles']) + "
                    f"len(ctx['permanent_ban_titles']))"],
                   300)

    # A BEFORE B: the fresh shortlist gets probed immediately instead of
    # the stale cached one (fixes the 0-phrases gap on manual runall runs)
    ok &= run_step("2/3 agent A full cycle (collect -> verify -> report)",
                   [py, "-c",
                    "import sys; sys.path.insert(0, '.'); "
                    "import agent.agent as a; "
                    "a.run_cycle()"],
                   2700)

    ok &= run_step("3/3 agent B (demand context + genome + calendar)",
                   [py, str(BASE / "agentb" / "night_runner.py")],
                   1200)

    print("\n================ SUMMARY ================")
    for f in ("intel_report.json", "manifest_shortlist.json",
              "demand_context.json", "buyer_calendar.json",
              "failure_learning.json"):
        p = DATA / f
        if p.exists():
            age = (time.time() - p.stat().st_mtime) / 60
            print(f"  {f:28s} fresh ({age:.0f} min ago)")
        else:
            print(f"  {f:28s} MISSING")
    print("========================================")

    if strict and not ok:
        sys.exit(1)
    print("\nAll steps attempted. Launchd keeps the normal schedule "
          "(A: 6h cycles, B: 00:30 nightly, WatchPaths: instant fail-read).")


if __name__ == "__main__":
    main()
