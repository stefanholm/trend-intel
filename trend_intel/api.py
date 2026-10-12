"""Reader API for the downstream trend-search app.

Usage from your app:
    from trend_intel.api import IntelAPI
    api = IntelAPI()            # or IntelAPI(path_to_db)
    api.top(n=20)               # scored nuggets
    api.search("scarf")         # keyword search
    api.mark_used(title)        # anti-flood: record consumption
    api.reject(title, reason)   # intake gate reject
"""
import json
import json
import time
from pathlib import Path

from .db import DB, DEFAULT_DB


class IntelAPI:
    def __init__(self, db_path=DEFAULT_DB, snapshot_path=None):
        self.db = DB(db_path)
        self.snapshot_path = Path(snapshot_path) if snapshot_path else (
            Path(db_path).parent / "intel_snapshot.json")

    def top(self, n=50, min_score=0.0):
        return [x for x in self.db.active_nuggets(limit=n * 2)
                if x["score"] >= min_score][:n]

    def search(self, query, n=50):
        q = query.lower().strip()
        out = []
        for x in self.db.active_nuggets(limit=1000):
            hay = (x["title"] + " " + " ".join(x["keywords"])).lower()
            if q in hay:
                out.append(x)
        return out[:n]

    def mark_used(self, title):
        self.db.set_nugget_status(title, "used")

    def ingest_burned(self, path=None):
        """Intake burned.json from the render app (titles that failed QC).

        Your render app writes a simple JSON file:
            {"burned": ["gold hoop earrings", "snow linen flat lay"], "reason": "clip<28"}
        Call this after each render run; burned titles never re-enter
        the shortlist."""
        path = Path(path or Path(self.db.path).parent / "burned.json")
        if not path.exists():
            return 0
        try:
            data = json.loads(path.read_text())
        except (ValueError, OSError):
            return 0
        titles = data.get("burned", [])
        n = self.db.mark_burned(titles, data.get("reason", "render_qc_failed"))
        if n:
            path.unlink()  # consumed — avoid reprocessing
        return n

    def reject(self, title, reason):
        self.db.set_nugget_status(title, "rejected", reason)

    def snapshot(self):
        """Return exported JSON snapshot (read-only, safe for other processes)."""
        if self.snapshot_path.exists():
            return json.loads(self.snapshot_path.read_text())
        return {"exported_at": 0, "count": 0, "nuggets": []}

    def stats(self):
        runs = self.db.recent_runs(5)
        return {
            "active_nuggets": len(self.db.active_nuggets(limit=5000)),
            "recent_runs": runs,
            "time": int(time.time()),
        }
