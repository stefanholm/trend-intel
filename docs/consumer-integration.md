# Trend-Intel Consumer Integration Spec

What your search/render app (NFE) should read from trend-intel, what each
field means, and what it should do with it. All files live in
`/Applications/trend-intel/data/` and are rewritten by the agents.

## Files, in order of importance

| File | Written by | When |
|---|---|---|
| `intel_report.json` | Agent A | every 6h cycle (and instantly via failread) |
| `manifest_shortlist.json` | Agent A (gate) | every cycle |
| `demand_context.json` | Agent B | 00:30 nightly (24h cache per phrase) |
| `buyer_calendar.json` | Agent B | 00:30 nightly |
| `failure_learning.json` | Agent C | cycle start + **instantly when a render report arrives** |
| `status.json` | Agent A | on every state change |

---

## 1. `intel_report.json` — the main report

Top-level blocks:

- `updated_at` (unix ts) — always check this for freshness.
- `data_quality` — trust block:
  - `google_trends_available` (bool) — false = GT in 429 cooldown; trajectories
    may come from Wikipedia fallback (`verifier: "wikipedia"`) or be missing.
  - `gt_verified_count` / `provisional_count` / `fallen_count` (ints)
- `verified[]` — GT (or Wikipedia) verified trends, ranked by hotness:
  - `title`, `state` (rising|steady|peaked|falling), `slope` (recent vs earlier,
    +0.5 = 50% hotter), `hotness` (0-1 — **use this for ranking**), `score`,
    `demand`, `approx_traffic` (raw search-volume estimate or null),
    `sources[]`, `source_count`, `seen_count`, `first_seen`, `area`,
    `verified_by_google_trends` (bool — if false, verifier was Wikipedia),
    `variant_count`
- `provisional[]` — source signal only, NO trajectory yet. Same fields minus
  state/slope. Treat as leads, not facts.
- `fallen[]` — declining trends, do not render.
- `areas{}` — same trends grouped by visual vertical (`matcha_drinks`,
  `autumn_fashion`, ...) with `useful` flag.
- `emerging_early[]` — twin-signal candidates BEFORE Google volume appears.
- `track_record` — the agent's own past rising-call hit rate.
- `failure_learning{}` — Agent C's block, **same report as everything else**:
  - `hard_ban_roots[]` — 2-3 word roots, banned 60 days, do not render/pivot
  - `permanent_ban_titles[]` — brand/SKU + adult leaks, never expire
  - `false_demand[]` — high market_score but weak image: `{title, market, aes, clip}`
  - `adult_leaks[]` — never for the adult slot
  - `fix_directives[]` — short render fixes (strings)
  - `winner_patterns[]` — AES>=6 & CLIP>=28 priors: reuse the PATTERN
    (setting/prop class), not the exact title
  - `n_rows` — 0 means no render reports ingested yet
- `sources{}` — items per source in the last 24h.
- `legend{}` — field explanations, keep for reference.

### Consumer rules for intel_report.json

1. Rank by `hotness`, never by raw `score`.
2. Never render anything whose title/root matches `failure_learning.hard_ban_*`
   or `permanent_ban_*` (roots are normalized: lowercase, no punctuation).
3. `data_quality.google_trends_available: false` does NOT mean the report is
   bad — it means verify Wikipedia-verified entries with slightly less trust
   (`verified_by_google_trends: false`) and expect provisional counts to be
   high that cycle.
4. `provisional` entries pass during GT cooldown only when marked
   `provisional_gt_cooldown: true` in the shortlist — those are gate-approved
   despite single sourcing.

## 2. `manifest_shortlist.json` — what to render

`shortlist[]` entries carry render-ready directives:

- `title` — brand-stripped, ready for prompt build
- `image_need` — shot class: `Macro drink | Beauty detail | SFW intimates |
  Environment worn apparel | Environment interior | Product still-life |
  Environment lifestyle`
- `prop_hero` — concrete hero object from the title
- `setting_hint` — coherent micro-setting. If it contains
  `| DIFFERENTIATE: <text>`, that text is MANDATORY (supply is flooded;
  the differentiation angle came from Agent B's gap analysis)
- `people_hands` — hands/usage mandate (filled vessels, no empty)
- `buyer_use` — who licenses this image
- `trajectory{}` — state + hotness + source count + gt_verified
- `supply_bucket` (when Agent B has data) — `flooded | competitive | thin | unknown`
- `demand_action` (when flooded) — `expand_or_differentiate`
- `differentiation_angle` (when flooded) — the forced angle
- `priority_slot: true` (when thin + hot) — best licensing slot, render first
- `provisional_gt_cooldown: true` — passed the gate during GT cooldown

### Consumer rules for manifest_shortlist.json

1. Render `priority_slot` entries first.
2. A `DIFFERENTIATE:` suffix in `setting_hint` is not a suggestion.
3. `rejected_summary{}` at the top level tells you why the rest were dropped
   (useful for debugging coverage, not for rendering).
4. The adult slot must be `image_need: SFW intimates` — non-intimates adult
   themes are rewritten pre-manifest; respect `adult_theme_rewritten` if present.

## 3. `demand_context.json` — supply intelligence (Agent B)

`queries[]`: `{phrase, supply_bucket, adobe_approx_hits, probe_source,
top_formula, gap_hint, action}`

- `action: expand_or_differentiate` → flooded, must differentiate
- `action: keep` → safe to render as-is
- `action: keep_watch` → thin supply but lukewarm demand
- `probe_source: unknown` → all probes blocked, no data (treat as keep)
- `gap_hint` — e.g. "competitor titles are static, add hands/pour/usage" =
  your differentiation instruction

## 4. `buyer_calendar.json` — buyer timing (Agent B)

`need_windows[]`: `{label, keywords[], days_until, window_status}`

- `window_status: license NOW` — buyers are licensing NOW, render immediately
- `window_status: upcoming` — queue next
- Lead times are buyer-side: they license BEFORE consumer keywords peak.
  Includes Swedish seasons (sportlov, midsommar, Lucia, Valborg).

## 5. `failure_learning.json` — full detail (Agent C)

The report block is a summary; this file has full lists (up to 80 ban titles,
30 false-demand cases, winner samples). Use it if you need the complete ban
set rather than the top-40 shown in the report.

## 6. `status.json`

`{state: idle|collecting|error|stopped, cycle, error, updated_at}` — for
health dashboards only.

---

## What your app should WRITE back

| File | Where | When |
|---|---|---|
| `burned.json` | `/Applications/trend-intel/data/burned.json` | after QC failures: `{"burned": ["title", ...], "reason": "clip<28"}` |
| `latest_report.json` / `report_*.json` | your NFE reports dir (WatchPaths watches it) | every render session, with per-shot scores |

Per-shot fields Agent C reads (old format): `title, market_score,
aesthetic_score, clip_score, verdict (GOOD/MARGINAL/REJECT)`.
New format (`shots[]` + `human_qc`) works too: `tt` + `visual_score /
tech_score / market_score / adult_score (1-5), kill_repetitive`.

## Timing guarantees

- Report refreshes at worst every 6h (Agent A cycle).
- Fail-read fires within ~seconds of a new render report (launchd WatchPaths,
  throttled to 1 per 2 min).
- Demand context is at most 24h stale (nightly + 24h cache).
- Everything degrades: GT down → Wikipedia fallback; Adobe blocked → probe
  ladder; no reports → empty learning block. Nothing ever blocks the pipeline.

## TL;DR for the app developer

Read `intel_report.json` for what's trending (rank by hotness, respect bans),
read `manifest_shortlist.json` for how to shoot it (image_need, setting_hint,
priority first, DIFFERENTIATE is mandatory), write your QC scores back as
report files and the system learns from them automatically.
