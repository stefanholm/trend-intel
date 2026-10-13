import sqlite3
import json
import threading
import time
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "intel.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,           -- trends_rss_us, pytrends, ...
    external_id TEXT,               -- source-stable id (title hash, url)
    title TEXT NOT NULL,
    url TEXT,
    geo TEXT,
    traffic TEXT,                   -- e.g. "500K+ searches" or interest value
    approx_traffic INTEGER,         -- normalized numeric if parseable
    extra_json TEXT,               -- related queries, topics, news snippets
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    seen_count INTEGER NOT NULL DEFAULT 1,
    UNIQUE(source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_raw_last_seen ON raw_items(last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_raw_source ON raw_items(source);

CREATE TABLE IF NOT EXISTS nuggets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    source_ids TEXT NOT NULL,       -- json list of raw item ids
    sources TEXT NOT NULL,          -- json list of source names
    score REAL NOT NULL DEFAULT 0,  -- demand proxy composite
    demand REAL,                    -- interest / traffic component
    freshness REAL,                 -- recency component
    ad_presence REAL,               -- tiebreaker only
    keywords TEXT,                  -- json list
    created_at INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',  -- active | rejected | used
    reject_reason TEXT,
    burned_at INTEGER,
    UNIQUE(title)
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at INTEGER NOT NULL,
    finished_at INTEGER,
    status TEXT NOT NULL,           -- running | ok | error
    source TEXT NOT NULL,
    items_collected INTEGER NOT NULL DEFAULT 0,
    error TEXT
);

CREATE TABLE IF NOT EXISTS interest_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    ts INTEGER NOT NULL,
    state TEXT,               -- rising | steady | peaked | falling | unknown
    slope REAL,
    recent_mean REAL,
    prev_mean REAL,
    series_tail_json TEXT,    -- last few values for cheap re-check
    UNIQUE(title, ts)
);
CREATE INDEX IF NOT EXISTS idx_ih_title ON interest_history(title, ts DESC);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def parse_traffic(s):
    """'500K+' -> 500000, '2M+' -> 2000000, '2000' -> 2000, None on failure."""
    if not s:
        return None
    s = str(s).strip().replace(",", "").replace("+", "").replace(" searches", "")
    mult = 1
    if s and s[-1].upper() in ("K", "M"):
        mult = {"K": 1_000, "M": 1_000_000}[s[-1].upper()]
        s = s[:-1]
    try:
        return int(float(s) * mult)
    except ValueError:
        return None


class DB:
    def __init__(self, path=DEFAULT_DB):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_schema()

    def _conn(self):
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(str(self.path), timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    def _init_schema(self):
        with self._lock():
            self._conn().executescript(SCHEMA)
            cols = {r["name"] for r in self._conn().execute(
                "PRAGMA table_info(nuggets)")}
            if "burned_at" not in cols:
                self._conn().execute(
                    "ALTER TABLE nuggets ADD COLUMN burned_at INTEGER")
            self._conn().commit()

    def _lock(self):
        if not hasattr(self._local, "lock"):
            self._local.lock = threading.Lock()
        return self._local.lock

    # -- raw items ----------------------------------------------------
    def upsert_raw(self, source, title, external_id=None, url=None, geo=None,
                   traffic=None, extra=None, ts=None):
        ts = ts or int(time.time())
        external_id = external_id or title.lower().strip()[:200]
        approx = parse_traffic(traffic)
        with self._lock():
            cur = self._conn().execute(
                """
                INSERT INTO raw_items
                    (source, external_id, title, url, geo, traffic, approx_traffic,
                     extra_json, first_seen, last_seen, seen_count)
                VALUES (?,?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(source, external_id) DO UPDATE SET
                    last_seen=excluded.last_seen,
                    seen_count=seen_count+1,
                    traffic=COALESCE(excluded.traffic, traffic),
                    approx_traffic=COALESCE(excluded.approx_traffic, approx_traffic),
                    extra_json=COALESCE(excluded.extra_json, extra_json)
                """,
                (source, external_id, title, url, geo, traffic, approx,
                 json.dumps(extra) if extra else None, ts, ts),
            )
            self._conn().commit()
            return cur.lastrowid

    def recent_raw(self, since=None, source=None, limit=1000):
        q = "SELECT * FROM raw_items WHERE 1=1"
        args = []
        if since:
            q += " AND last_seen >= ?"
            args.append(since)
        if source:
            q += " AND source = ?"
            args.append(source)
        q += " ORDER BY last_seen DESC LIMIT ?"
        args.append(limit)
        return [dict(r) for r in self._conn().execute(q, args)]

    # -- nuggets -------------------------------------------------------
    def upsert_nugget(self, title, source_ids, sources, score=0, demand=0,
                      freshness=0, ad_presence=0, keywords=None, status="active"):
        now = int(time.time())
        with self._lock():
            self._conn().execute(
                """
                INSERT INTO nuggets
                    (title, source_ids, sources, score, demand, freshness,
                     ad_presence, keywords, created_at, status)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(title) DO UPDATE SET
                    score=MAX(score, excluded.score),
                    demand=MAX(demand, excluded.demand)
                """,
                (title, json.dumps(source_ids), json.dumps(sources), score, demand,
                 freshness, ad_presence, json.dumps(keywords or []),
                 now, status),
            )
            self._conn().commit()

    def active_nuggets(self, limit=500):
        rows = self._conn().execute(
            "SELECT * FROM nuggets WHERE status='active' ORDER BY score DESC LIMIT ?",
            (limit,))
        out = []
        for r in rows:
            d = dict(r)
            for k in ("source_ids", "sources", "keywords"):
                d[k] = json.loads(d[k] or "[]")
            out.append(d)
        return out

    def mark_burned(self, titles, reason="render_qc_failed"):
        """Bulk-mark titles as burned (from the render app's QC failures).
        Temporary failure-learning bans can be lifted later via expire_burned."""
        burned = 0
        now = int(time.time())
        with self._lock():
            for t in titles:
                cur = self._conn().execute(
                    "UPDATE nuggets SET status='burned', reject_reason=?, burned_at=? "
                    "WHERE title=? AND status IN ('active','used')",
                    (reason, now, t))
                burned += cur.rowcount
            self._conn().commit()
        return burned

    def expire_burned(self, reason, older_than_s):
        """Lift temporary bans: nuggets burned with `reason` before the window
        ends become active again (seasonal trends get a new season)."""
        with self._lock():
            cur = self._conn().execute(
                """UPDATE nuggets SET status='active', reject_reason=NULL,
                                     burned_at=NULL
                   WHERE status='burned' AND reject_reason=?
                   AND burned_at IS NOT NULL AND burned_at < ?""",
                (reason, int(time.time()) - older_than_s))
            self._conn().commit()
            return cur.rowcount

    def set_nugget_status(self, title, status, reason=None):
        with self._lock():
            self._conn().execute(
                "UPDATE nuggets SET status=?, reject_reason=? WHERE title=?",
                (status, reason, title))
            self._conn().commit()

    # -- runs / meta ----------------------------------------------------
    def start_run(self, source):
        with self._lock():
            cur = self._conn().execute(
                "INSERT INTO runs (started_at, status, source) VALUES (?, 'running', ?)",
                (int(time.time()), source))
            self._conn().commit()
            return cur.lastrowid

    def finish_run(self, run_id, status, items=0, error=None):
        with self._lock():
            self._conn().execute(
                "UPDATE runs SET finished_at=?, status=?, items_collected=?, error=? WHERE id=?",
                (int(time.time()), status, items, error, run_id))
            self._conn().commit()

    def recent_runs(self, limit=50):
        return [dict(r) for r in self._conn().execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,))]

    def get_meta(self, key, default=None):
        r = self._conn().execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def set_meta(self, key, value):
        with self._lock():
            self._conn().execute(
                "INSERT INTO meta (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))
            self._conn().commit()
