"""Inventory every day clean_tw50_data() flags as an extreme return.

Deliverable (1) of task clean_tw50_extreme_return_zeroing_20260719: before
2026-07-21 this function silently zeroed any |daily return| > 50% and rebuilt
the whole price series by cumprod, so "no complaints" was indistinguishable
from "quietly corrupted". This scans every real 0050.TW series in the repo and
prints the dates the threshold actually fires on.

Result on 2026-07-21: 0 flagged days across 19 series (2009-01-02..2026-07-10).
The split repair inside the function already removes the only break that
produced one, which is why replacing the zeroing with a warning was proven
byte-identical on all of them.

Re-run this after adding any new 0050 snapshot, or adapt the glob to audit
another asset a caller is passing in.

    uv run python scripts/audit_tw50_extreme_returns.py
"""
import glob, sys
import pandas as pd
sys.path.insert(0, "src")
from volpred.utils import clean_tw50_data, _TW50_SPLIT_DATE, _TW50_SPLIT_RATIO

files = sorted(set(glob.glob("experiments/**/*0050*snapshot*.csv", recursive=True)
                   + glob.glob("data/cache/**/*0050*.csv", recursive=True)
                   + glob.glob("**/0050*.csv", recursive=True)))
print(f"candidate files: {len(files)}")
seen = {}
for f in files:
    if "5min" in f or "intraday" in f:
        continue
    try:
        df = pd.read_csv(f)
    except Exception as e:
        print(f"  SKIP {f}: {e}"); continue
    dcol = next((c for c in df.columns if c.lower() in ("date", "datetime", "index")), df.columns[0])
    pcol = next((c for c in df.columns if c.lower() in ("close", "adj close", "adj_close", "price")), None)
    if pcol is None:
        continue
    idx = pd.to_datetime(df[dcol], errors="coerce", utc=True)
    idx = pd.DatetimeIndex(idx).tz_convert(None)
    s = pd.Series(pd.to_numeric(df[pcol], errors="coerce").values, index=idx)
    s = s[~s.index.isna()]
    s = s.dropna()
    if len(s) < 50:
        continue
    # replicate the function's internal state up to the safety net
    cp = s.copy()
    sd = pd.Timestamp(_TW50_SPLIT_DATE)
    if sd in cp.index:
        pre = cp.index < sd
        if pre.any():
            ratio = cp[pre].iloc[-1] / cp.loc[sd]
            if 3.5 < ratio < 4.5:
                cp[pre] = cp[pre] / _TW50_SPLIT_RATIO
    r = cp.pct_change()
    hit = r[r.abs() > 0.50]
    key = (str(s.index.min().date()), str(s.index.max().date()), len(s))
    print(f"\n{f}\n  span={key[0]}..{key[1]} n={key[2]}  ZEROED={len(hit)}")
    for d, v in hit.items():
        print(f"    {d.date()}  ret={v:+.4f}")
    seen[f] = len(hit)
print("\n=== TOTAL files with zeroing:", sum(1 for v in seen.values() if v), "/", len(seen))
