# TAIFEX Tick — Canonical Layer

Normalized, columnar (parquet) tick store for TAIFEX TX index futures, built from
the local raw archive at `~/Dropbox/TAIFEXDATA/` (read-only source; nothing under
Dropbox is ever written). All numbers below come from an actual scan of the
archive on 2026-07-15, not from prior memory.

Producers:
- `scripts/taifex_tick_inventory.py` → `data/intraday/taifex_tick_manifest.json`
  (read-only inventory: sync status, per-contract dates/gaps, measured eras).
- `scripts/taifex_tick_to_canonical.py` → `data/intraday/taifex_tick/<contract>/<yyyymm>.parquet`
  (raw daily CSV → canonical schema, with validation).

Both reuse the header-based era-normalization in `scripts/collect_taifex_tick.py`
(`map_semantic_columns`, `SOURCE_ENCODINGS`, session constants) rather than
re-implementing a parallel parser, so this layer and the 5-minute RV series
(`data/intraday/taifex_5min_rv.csv`) cannot drift apart.

## Canonical layout

```
data/intraday/taifex_tick/
  TX/   <yyyymm>.parquet   # merged all-contracts file (TX)
  TX1/  <yyyymm>.parquet   # front-month (near) — strategy use
  TX2/  <yyyymm>.parquet   # second month (next)
```

`<contract>` is the source **file variant** (TX = merged, TX1 = front month,
TX2 = second month). Each monthly parquet accumulates every trading day of that
month for that variant; days merge idempotently (de-duplicated on
trade_date+symbol+contract_month+trade_time+price+volume+timestamp).

## Schema (one row per tick)

| column           | type    | source (Chinese header) | notes |
|------------------|---------|-------------------------|-------|
| `trade_date`     | Int64   | 成交日期 (YYYYMMDD)      | night ticks carry the **evening's** calendar date |
| `symbol`         | str     | 商品代號                | e.g. `TX` |
| `contract_month` | str     | 到期月份(週別)          | delivery month/week, e.g. `201705` |
| `trade_time`     | Int64   | 成交時間 (HHMMSS)        | raw; leading zeros dropped pre-2017 and for AM night |
| `price`          | float64 | 成交價格                | > 0 |
| `volume`         | Int64   | 成交數量(B+S)           | both-sides count |
| `near_price`     | float64 | 近月價格                | spread quote; usually `-` → NaN for monthly TX |
| `far_price`      | float64 | 遠月價格                | spread quote; usually `-` → NaN for monthly TX |
| `is_auction`     | bool    | 開盤集合競價 (`*`)       | `False` throughout the 9-column 2012 era (no such column) |
| `is_night`       | bool    | derived from `trade_time` | night = 15:00:00–05:00:00; only exists 2017-05-16 onward |
| `timestamp`      | str     | 時間戳記                | raw exchange timestamp |

Sessions: day 08:45–13:45 (`DAY_START..DAY_END`); night 15:00–05:00 next day
(`NIGHT_PM_START` / `NIGHT_AM_END`), 2017-05-16 onward.

## Format eras (MEASURED, not assumed)

The raw CSV layout changed twice. Boundaries were detected by scanning every TX
header's column count and by sampling representative days — the exact dates
differ from older notes, so trust the measured values here:

| Era | Date range (measured)        | Cols | Auction col | Night | Time digits (measured) |
|-----|------------------------------|------|-------------|-------|------------------------|
| A   | 2012-01-02 … 2012-06-13      | 9    | no          | no    | 5–6 |
| B   | 2012-06-14 … 2017-05-15      | 10   | yes (`開盤集合競價`) | no | 5–6 |
| C   | 2017-05-16 … present         | 10   | yes         | yes   | 1–6 (AM night times drop leading zeros; not strictly "unified 6-digit") |

The 9→10 column transition is **2012-06-14** (first 10-column day), not 2013/2014.
The night session first appears **2017-05-16** (0 night rows on 05-15, 1,337+ on
05-16). Era is decided by header/column shape, never by a hard-coded column index.

## Sync / coverage gaps (from the scan)

| subtree | status | files (nonzero/total) | bytes |
|---------|--------|-----------------------|-------|
| `TAIFEXDATA/python` (futures tick) | **synced** | 10,644 / 10,644 | ~33.5 GB |
| `TAIFEXDATA/{year}/csv` (raw tick) | **placeholder** (cloud-only) | 0 / 4,046 | 0 |
| `OPTIONDATA` (options tick) | **partial** | 1,024 / 13,093 | ~41 GB |
| `vix` | **synced** | 4,313 / 4,313 | ~63 MB |
| `證交所` (TWSE) | **partial** | 1 / 5,381 | ~27 KB |

- The only locally-synced futures tick is `TAIFEXDATA/python/`. The raw
  `{year}/csv/` tick tree is entirely Dropbox 0-byte placeholders (not downloaded);
  treat as a gap until pulled from the cloud.
- `OPTIONDATA` and `證交所` are only partially downloaded; out of scope for the
  futures tick layer but recorded for completeness.

### Trading-day gaps (per contract TX / TX1 / TX2, identical)
- 3,548 trading days each, **2012-01-02 … 2026-07-14**.
- **258 missing weekdays** inside that range. These are Mon–Fri calendar days
  with no file and **include all TW public holidays** — they are not necessarily
  archive holes. 17 "long runs" (≥3 consecutive missing weekdays) are all
  Lunar New Year closures (Jan/Feb each year).
- **Cross-contract inconsistencies = 0**: every date present for one of
  TX/TX1/TX2 is present for all three, so there are **no true internal data
  holes** in the synced futures tick. See `taifex_tick_manifest.json` for the
  full missing-weekday list.

## Sample validation (real output, 2026-07-15)

`python scripts/taifex_tick_to_canonical.py --sample` — 9/9 days passed across
all three eras plus TX1:

| file | rows | day | night | auction | out-of-session |
|------|------|-----|-------|---------|----------------|
| Daily_2012_01_02TX (era A)   | 53,391  | 53,391  | 0       | 0 | 0 |
| Daily_2012_06_14TX (era B ▶) | 51,910  | 51,910  | 0       | 3 | 0 |
| Daily_2014_01_02TX (era B)   | 38,373  | 38,373  | 0       | 4 | 0 |
| Daily_2017_05_15TX (era B ◀) | 47,454  | 47,454  | 0       | 3 | 0 |
| Daily_2017_05_16TX (era C ▶) | 63,258  | 61,691  | 1,567   | 5 | 0 |
| Daily_2020_03_16TX (era C)   | 321,356 | 174,840 | 146,489 | 7 | 0 |
| Daily_2026_07_14TX (era C)   | 142,264 | 103,223 | 39,034  | 4 | 0 |
| Daily_2017_05_16TX1 (TX1)    | 48,075  | 46,674  | 1,401   | 2 | 0 |
| Daily_2026_07_14TX1 (TX1)    | 108,083 | 73,026  | 35,050  | 2 | 0 |

Checks per day: rows > 0; all prices positive; `< 1%` ticks outside a legal
session; night flag only where night exists; auction share sane. `other = 0`
everywhere confirms every tick falls in a recognized session.

## Full rebuild (heavy — do NOT run inline)

Converting the whole 33 GB archive is a heavy job and must go through the
compute queue, not an interactive turn:

```
uv run python scripts/compute_queue.py enqueue \
    --script scripts/taifex_tick_to_canonical.py \
    --title "TAIFEX tick canonical full rebuild" -- --full-rebuild
```

## Consuming this layer (`research_taifex_intraday_rv_line`)

1. Read `data/intraday/taifex_tick/TX1/*.parquet` (front month) for strategy /
   intraday RV; use `TX/*.parquet` if you need the merged all-contracts view.
2. Filter to one `contract_month` (or use TX1 which is already front-month) and
   drop `is_auction` ticks before computing returns.
3. Split sessions with `is_night`: build the homogeneous **day-session** RV for
   the full 2012→ history; treat `is_night` RV as an explicit opt-in that only
   exists from 2017-05-16 (mirror `collect_taifex_tick.py`'s day/night split so
   the roll gap and the two closed-market gaps are not counted as variance).
4. Bar on `trade_time` (fold the 13:45 / 05:00 endpoints into the prior 5-min
   bar, as the RV collector does).
5. For calendar gaps, see the manifest: missing weekdays are holidays, not holes.
