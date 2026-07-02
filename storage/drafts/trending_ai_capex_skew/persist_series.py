"""Append today's mega-cap skew snapshot to a persistent time-series.

Idempotent by snapshot date. Seeds the 06-03 archive point (from mile_49616ac2)
so the series has a >=2-point baseline. Re-run weekly to accumulate the series;
once >=3-4 dates exist the single-name-skew-migration finding becomes provable
and publishable (see FINDINGS.md).
"""
import json
import os

SERIES = "storage/data/skew_series/mega_cap_skew_series.json"
SNAP = "storage/drafts/trending_ai_capex_skew/skew_results.json"

# Archive baseline from mile_49616ac2 (2026-06-03, same 90-110 methodology).
ARCHIVE_2026_06_03 = {
    "date": "2026-06-03", "source": "mile_49616ac2 (archived)",
    "skew_90_110": {"META": -0.053, "GOOGL": -0.015, "MSFT": -0.007,
                    "AMZN": -0.006, "NVDA": -0.010, "SPY": 0.095},
}


def load_series():
    if os.path.exists(SERIES):
        with open(SERIES) as f:
            return json.load(f)
    return {"metric": "skew_90_110 = IV(90% put) - IV(110% call), ~30D",
            "snapshots": [ARCHIVE_2026_06_03]}


def main():
    os.makedirs(os.path.dirname(SERIES), exist_ok=True)
    series = load_series()

    with open(SNAP) as f:
        snap = json.load(f)
    date = snap["generated_at"][:10]
    skew = {r["ticker"]: r["skew_90_110"] for r in snap["results"]}

    existing = {s["date"] for s in series["snapshots"]}
    if date in existing:
        print(f"snapshot {date} already in series — no-op")
    else:
        series["snapshots"].append(
            {"date": date, "source": SNAP, "skew_90_110": skew})
        series["snapshots"].sort(key=lambda s: s["date"])
        print(f"appended {date}: {len(skew)} tickers")

    with open(SERIES, "w") as f:
        json.dump(series, f, indent=2, ensure_ascii=False)
    print(f"series now has {len(series['snapshots'])} snapshots -> {SERIES}")


if __name__ == "__main__":
    main()
