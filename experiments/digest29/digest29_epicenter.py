"""Digest #29 evidence: locating the epicenter of the July 2026 semiconductor drawdown.

Question: is the SOX -20% a market-wide volatility regime shift, or a narrow
sector event? Three coordinates: depth (vol regime), radius (breadth /
correlation spillover), aftershock (vol persistence).

Data source: yfinance, as-of 2026-07-17 close. Reproduce: uv run python
experiments/digest29/digest29_epicenter.py
"""
import json
import numpy as np
import yfinance as yf

END = "2026-07-19"   # exclusive-ish; last trading close available = 2026-07-17
TICKERS = ["^SOX", "^GSPC", "SPY", "^VIX", "XLF", "XLI", "XLE"]

px = {}
for t in TICKERS:
    h = yf.Ticker(t).history(start="2025-01-01", end=END)
    if not h.empty:
        px[t] = h["Close"].tz_localize(None)

out = {"as_of": "2026-07-17", "source": "yfinance", "series": {}}

def rv20(s):
    r = np.log(s).diff().dropna()
    return float(r.tail(20).std() * np.sqrt(252) * 100)

def rv20_asof(s, back):
    r = np.log(s).diff().dropna()
    return float(r.iloc[-(20 + back):-back].std() * np.sqrt(252) * 100)

for t, s in px.items():
    peak = float(s.max())
    peak_2026 = float(s[s.index >= "2026-01-01"].max())
    idx_peak = s[s.index >= "2026-01-01"].idxmax()
    last = float(s.iloc[-1])
    e = {
        "last": round(last, 2),
        "last_date": str(s.index[-1].date()),
        "peak_2026": round(peak_2026, 2),
        "peak_2026_date": str(idx_peak.date()),
        "drawdown_from_peak_pct": round((last / peak_2026 - 1) * 100, 2),
        "ytd_pct": round((last / float(s[s.index >= "2026-01-01"].iloc[0]) - 1) * 100, 2),
    }
    if t != "^VIX":
        e["rv20_ann_pct"] = round(rv20(s), 2)
        e["rv20_ann_pct_60d_ago"] = round(rv20_asof(s, 60), 2)
    out["series"][t] = e

# Correlation: has the shock spread? SOX vs SPY daily-return correlation.
r_sox = np.log(px["^SOX"]).diff().dropna()
r_spy = np.log(px["SPY"]).diff().dropna()
j = r_sox.to_frame("sox").join(r_spy.to_frame("spy"), how="inner").dropna()
out["correlation"] = {
    "sox_spy_corr_last40d": round(float(j.tail(40)["sox"].corr(j.tail(40)["spy"])), 3),
    "sox_spy_corr_prior_2025": round(float(j[j.index < "2026-01-01"]["sox"].corr(j[j.index < "2026-01-01"]["spy"])), 3),
}

# Breadth: drawdown dispersion between the epicenter and rotation destinations.
out["breadth"] = {
    "sox_minus_spx_drawdown_gap_pp": round(
        out["series"]["^SOX"]["drawdown_from_peak_pct"] - out["series"]["^GSPC"]["drawdown_from_peak_pct"], 2
    ),
}

# Aftershock: vol persistence — how much did SOX vol actually move?
out["aftershock"] = {
    "sox_rv20_ratio_vs_60d_ago": round(
        out["series"]["^SOX"]["rv20_ann_pct"] / out["series"]["^SOX"]["rv20_ann_pct_60d_ago"], 2
    ),
    "spy_rv20_ratio_vs_60d_ago": round(
        out["series"]["SPY"]["rv20_ann_pct"] / out["series"]["SPY"]["rv20_ann_pct_60d_ago"], 2
    ),
}

with open("experiments/digest29/digest29_results.json", "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False, indent=2))
