# Trend Intel Collector

Background collector that harvests trend "nuggets" from free sources, applies an
intake gate (kills celebrity headlines, promo junk, spec numbers, non-visual
terms), scores demand/freshness, and exports a JSON snapshot for a downstream
trend-search app.

## Sources
- **Google Trends RSS** (`trends.google.com/trending/rss`) — up to 14 geos, no auth
- **Pinterest trends** — lifestyle-flavored terms
- **pytrends** (optional) — related queries for seed terms in `config/seeds.txt`

## Run
```bash
# one harvest cycle + export
python -m trend_intel.collector

# background daemon, one cycle every 4 hours
nohup python -m trend_intel.collector --daemon --interval 14400 &
```

## Consume from your app
```python
from trend_intel.api import IntelAPI

api = IntelAPI()
for n in api.top(20):
    print(n["score"], n["title"], n["sources"])

api.search("scarf")
api.mark_used("Rust Orange Scarf")   # anti-flood bookkeeping
```

Or read the exported snapshot file directly (atomic writes):
`data/intel_snapshot.json`

## Data model
- `raw_items` — everything collected, deduped with `seen_count` + first/last seen
- `nuggets` — scored terms that passed the intake gate (`active`/`rejected`/`used`)
- `runs` — cycle audit log

## Polite use
Jittered delays, small payloads, exponential backoff on 429, caching via SQLite
upsert. One cycle per few hours is plenty; trends data refreshes hourly at most.
