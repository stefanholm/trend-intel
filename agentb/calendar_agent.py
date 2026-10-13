"""Calendar-of-need: which images will buyers need in +14 to +60 days?

Buyer-side seasons, not keyword trends: retail/stock buyers license
BEFORE the consumer keyword peaks. Fixed calendar (no scrape needed) +
optional Nager.date holidays. Lightweight, runs with the gap agent.
"""
import json
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DATA = BASE / "data"

# (month, day, offset_days_before, lead_title, vertical)
# buyers license this content N days before the date
FIXED_NEEDS = [
    (11, 1, 60, "christmas tree lot, holiday lights installation", "interiors"),
    (11, 14, 45, "advent calendar, hygge candle decor", "interiors"),
    (12, 1, 40, "christmas baking, gingerbread, glögg table", "food_drinks"),
    (12, 24, 30, "christmas morning gift opening, family pajamas", "fashion"),
    (12, 31, 25, "new year sparkler, champagne pour", "food_drinks"),
    (2, 14, 35, "valentine dinner, red roses table, chocolate", "food_drinks"),
    (2, 10, 30, "sportlov ski week, snow play, thermos", "fashion"),
    (3, 8, 20, "womens day, spring flowers, mimosa", "interiors"),
    (3, 20, 30, "easter egg hunt, pastel table, birch twigs", "food_drinks"),
    (4, 15, 25, "spring cleaning, open windows, tulips", "interiors"),
    (5, 1, 30, "valborg bonfire, spring picnic blanket", "lifestyle"),
    (5, 10, 25, "mothers day brunch, gift wrap flowers", "food_drinks"),
    (6, 6, 30, "swedish midsummer, maypole, flower crown, herring table", "food_drinks"),
    (6, 21, 30, "summer solstice beach sunset, swimwear boardwalk", "adult_lingerie"),
    (8, 10, 40, "back to school supplies, kids backpack, autumn jackets", "fashion"),
    (9, 1, 30, "autumn leaves walk, knitted scarf, pumpkin spice latte", "food_drinks"),
    (10, 31, 35, "halloween decor, carved pumpkin, candlelight", "interiors"),
    (11, 28, 25, "black friday shopping bags, sale tags, gift boxes", "lifestyle"),
    (1, 16, 20, "new year wellness, gym resolution, green smoothie", "food_drinks"),
    (3, 1, 25, "sustainability march, recycling hands, green office", "lifestyle"),
]

SWEDISH_HOLIDAYS = {  # approximate fixed dates (good enough for lead times)
    "midsommar": (6, 20), "lucia": (12, 13), "valborg": (4, 30),
    "kungliga": (6, 6),
}


def _need_windows(now=None, horizon=60):
    """Active need windows: buyer should license NOW for these."""
    import datetime
    now = now or datetime.datetime.now()
    out = []
    for m, d, lead, title, vert in FIXED_NEEDS:
        target = datetime.datetime(now.year, m, d)
        if target < now:
            target = datetime.datetime(now.year + 1, m, d)
        days_until = (target - now).days
        if days_until <= horizon and days_until >= -5:
            status = ("license NOW (peak buyer window)"
                      if days_until <= lead else "upcoming — prepare")
            out.append({
                "need_title": title,
                "vertical": vert,
                "event_date": target.date().isoformat(),
                "days_until": days_until,
                "buyer_lead_days": lead,
                "window_status": status,
            })
    out.sort(key=lambda w: w["days_until"])
    return out


def run():
    windows = _need_windows()
    out = {
        "updated_at": int(time.time()),
        "legend": {
            "window_status": "license NOW = buyers search currently; upcoming = prepare renders ahead of the wave",
            "buyer_lead_days": "how early buyers license before the event date",
        },
        "need_windows": windows,
    }
    (DATA / "buyer_calendar.json").write_text(json.dumps(out, indent=2))
    return out


if __name__ == "__main__":
    r = run()
    print(f"{len(r['need_windows'])} active need windows")
    for w in r["need_windows"][:5]:
        print(f"  {w['days_until']:>4}d  {w['window_status'][:28]:<30} {w['need_title'][:45]}")
