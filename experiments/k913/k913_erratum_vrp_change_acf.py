"""
K913 erratum verification — VRP level ACF vs VRP change (innovation) ACF.

Purpose: content_erratum task. mile_8fc743b5 line78 claims "VRP 日自相關係數只有 0.20，
幾乎是隨機遊走"; but K913 reports level ACF(1)=0.9267 (very persistent). Test the
hypothesis that 0.20 refers to the autocorrelation of VRP *changes* (Δvrp = vrp_t - vrp_{t-1}),
which can coexist with a persistent level.

Reproduces K913's exact VRP construction (variance-space, iv - rv_22d).
Seed-free (deterministic), no lookahead (pure descriptive ACF).
"""
import os
import json
import numpy as np
import pandas as pd
import yfinance as yf

OUT = os.path.dirname(os.path.abspath(__file__))

spy = yf.download("SPY", start="2005-11-01", end="2026-04-01", auto_adjust=True, progress=False)
vix = yf.download("^VIX", start="2005-11-01", end="2026-04-01", auto_adjust=True, progress=False)
for d in (spy, vix):
    if isinstance(d.columns, pd.MultiIndex):
        d.columns = d.columns.get_level_values(0)

df = pd.DataFrame({"spy_close": spy["Close"], "vix_close": vix["Close"]}).dropna()
df["ret"] = np.log(df["spy_close"]).diff()
df["ret_sq"] = df["ret"] ** 2
df["rv_22d"] = df["ret_sq"].rolling(22).sum() * 252 / 22
df["iv"] = (df["vix_close"] / 100) ** 2
df["vrp"] = df["iv"] - df["rv_22d"]
df = df.dropna(subset=["vrp"])

vrp = df["vrp"]
dvrp = vrp.diff().dropna()

res = {
    "N": int(len(vrp)),
    "level_acf": {f"lag_{k}": float(vrp.autocorr(k)) for k in (1, 5, 22)},
    "change_acf": {f"lag_{k}": float(dvrp.autocorr(k)) for k in (1, 5, 22)},
    "level_mean": float(vrp.mean()),
    "change_std": float(dvrp.std()),
    "note": "level ACF should reproduce K913 acf_1=0.9267; change ACF tests the 0.20 hypothesis",
}
print(json.dumps(res, indent=2))
with open(os.path.join(OUT, "k913_erratum_vrp_change_acf_results.json"), "w") as f:
    json.dump(res, f, indent=2)
