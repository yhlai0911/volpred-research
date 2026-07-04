"""
K1626: TSM ADR (NYSE:TSM) vs 2330.TW (TSMC Taiwan) — ADR premium, price discovery,
       and volatility transmission across two time zones.

RESEARCH QUESTION
-----------------
TSM ADR and 2330.TW are the same company trading in two markets in two time zones:
  - 2330.TW  session: 09:00-13:30 Taiwan time.  yfinance date label t -> close at TW t 13:30.
  - TSM  ADR session: 09:30-16:00 ET = ~21:30-04:00 Taiwan time (NEXT calendar morning).
                       yfinance date label t -> close at TW t+1 ~04:00-05:00.
Three sub-questions:
  (Q1) ADR premium series: TSM-implied per-share TWD vs 2330.TW close. Record high in AI era?
  (Q2) Price discovery: which market leads (daily lead-lag)?
  (Q3) Volatility transmission: does overnight ADR |return| foreshadow next-day TW vol?
       Directional (US->TW vs TW->US)?

TIMING MODEL (THE critical part — lookahead is the highest risk here; see K1108b lesson)
----------------------------------------------------------------------------------------
For a single calendar date label t the *information* order is:
      2330.TW close(t)  [TW t 13:30]   <--- happens FIRST
   -> TSM ADR close(t)  [TW t+1 ~04:00, US session t reacts to TW t close + global news]
   -> 2330.TW(t+1)      [TW t+1 09:00-13:30, can incorporate ADR close(t)]

Consequences for regressions:
  * r_2330(t) = log(loc_close(t)/loc_close(t-1))  spans [TW t-1 13:30, TW t 13:30].
  * r_ADR(t)  = log(adr_close(t)/adr_close(t-1))  spans [TW t 04:00,  TW t+1 04:00];
    its dominant (US-session) part [TW t 21:30 -> t+1 04:00] is ENTIRELY AFTER 2330(t) close.

  LEGITIMATE directional tests (no lookahead):
    (A) US -> TW overnight:   r_2330(t)  ~  r_ADR(t-1)     # ADR(t-1) ends TW t 04:00  < TW t 13:30  OK
    (B) TW -> US same-day:    r_ADR(t)   ~  r_2330(t)      # 2330(t) at TW t 13:30 < ADR(t) TW t+1 04:00  OK

  FORBIDDEN (lookahead) — used ONLY as a labelled diagnostic to expose the confound:
    (C) r_2330(t) ~ r_ADR(t)  same date  # ADR(t) is FUTURE vs 2330(t). This is exactly the
        K1108b trap (extended pool + TSM ADR gave spurious reversed t=-2.28). We DO NOT
        interpret (C) as predictive; we report it to show why same-date mixing is wrong.

DATA (all free via yfinance)
  TSM (ADR, USD), 2330.TW (TWD), TWD=X (TWD per USD). Overlapping trading days via inner join.

SEED = 42 for all bootstrap. No lookahead by construction (explicit .shift()).
"""
from __future__ import annotations

import json
import math
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import statsmodels.api as sm
from statsmodels.tsa.stattools import grangercausalitytests

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.simplefilter("ignore")

SEED = 42
np.random.seed(SEED)

# 1 TSM ADR = 5 common shares of 2330.TW.
# Source: TSMC ADR program (depositary Citibank N.A.), NYSE:TSM prospectus / TSMC IR.
# Verified empirically below: median(adr_usd * TWD_per_USD / loc_twd) should cluster ~5.
ADR_RATIO = 5.0

START = "2003-01-01"          # TWD=X history begins ~2003 on yfinance
HERE = Path(__file__).resolve().parent
GRANGER_MAXLAG = 5
BOOT_REPS = 1000
BLOCK = 20                    # moving-block length for block bootstrap


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def fetch(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=START, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)  # drop ticker level -> Open/High/Low/Close/Adj Close/Volume
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df


def newey_west_lag(n: int) -> int:
    return int(math.floor(4 * (n / 100.0) ** (2.0 / 9.0)))


def ols_hac(y: pd.Series, X: pd.DataFrame) -> dict:
    """OLS with Newey-West HAC covariance. X should NOT include const (added here)."""
    d = pd.concat([y.rename("y"), X], axis=1).dropna()
    yv = d["y"]
    Xv = sm.add_constant(d.drop(columns="y"))
    L = max(1, newey_west_lag(len(d)))
    res = sm.OLS(yv, Xv).fit(cov_type="HAC", cov_kwds={"maxlags": L})
    out = {
        "n": int(len(d)),
        "r2": float(res.rsquared),
        "hac_maxlags": int(L),
        "params": {k: float(v) for k, v in res.params.items()},
        "hac_t": {k: float(v) for k, v in res.tvalues.items()},
        "hac_p": {k: float(v) for k, v in res.pvalues.items()},
    }
    return out


def block_bootstrap_slope(y: pd.Series, x: pd.Series, reps: int, block: int, seed: int) -> dict:
    """Moving-block bootstrap 95% CI for the univariate OLS slope of y on x."""
    d = pd.concat([y.rename("y"), x.rename("x")], axis=1).dropna()
    yv = d["y"].to_numpy()
    xv = d["x"].to_numpy()
    n = len(yv)
    rng = np.random.default_rng(seed)
    nblocks = int(math.ceil(n / block))
    slopes = np.empty(reps)
    for r in range(reps):
        starts = rng.integers(0, n - block + 1, size=nblocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        yb, xb = yv[idx], xv[idx]
        xb_c = xb - xb.mean()
        denom = (xb_c ** 2).sum()
        slopes[r] = ((yb - yb.mean()) * xb_c).sum() / denom if denom > 0 else np.nan
    slopes = slopes[~np.isnan(slopes)]
    return {
        "ci95_low": float(np.percentile(slopes, 2.5)),
        "ci95_high": float(np.percentile(slopes, 97.5)),
        "mean": float(np.mean(slopes)),
        "reps": int(len(slopes)),
        "crosses_zero": bool(np.percentile(slopes, 2.5) < 0 < np.percentile(slopes, 97.5)),
    }


def granger_pvals(df2: pd.DataFrame, maxlag: int) -> dict:
    """grangercausalitytests: does col[1] Granger-cause col[0]? Return ssr_ftest p per lag."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = grangercausalitytests(df2.dropna(), maxlag=maxlag, verbose=False)
    return {str(lag): float(res[lag][0]["ssr_ftest"][1]) for lag in range(1, maxlag + 1)}


# --------------------------------------------------------------------------- #
# 1. fetch + align
# --------------------------------------------------------------------------- #
print("[K1626] downloading TSM, 2330.TW, TWD=X ...")
adr = fetch("TSM")
loc = fetch("2330.TW")
fx = fetch("TWD=X")

# FX is near-continuous; forward-fill small gaps, then use its Close (TWD per USD).
fx_close = fx["Close"].reindex(
    pd.date_range(fx.index.min(), max(adr.index.max(), loc.index.max()), freq="D")
).ffill()

# raw Close for PRICE-LEVEL premium (actual traded prices, not dividend-adjusted)
adr_close = adr["Close"]
loc_close = loc["Close"]
# Adj Close for RETURNS (removes each instrument's own dividend/split drops)
adr_adj = adr["Adj Close"]
loc_adj = loc["Adj Close"]

# overlapping trading days (inner join on the two equities)
common = adr_close.index.intersection(loc_close.index)
n_adr_only = len(adr_close.index.difference(loc_close.index))
n_loc_only = len(loc_close.index.difference(adr_close.index))
print(f"[K1626] overlap={len(common)}  ADR-only dropped={n_adr_only}  2330-only dropped={n_loc_only}")

fx_on_common = fx_close.reindex(common).ffill()

# --------------------------------------------------------------------------- #
# 2. ADR premium series (Q1)   —  same-date-label convention (ADR ~14.5h fresher)
# --------------------------------------------------------------------------- #
# empirical implied ratio = adr_usd * TWD_per_USD / loc_twd  (should cluster ~5)
implied_ratio_raw = (adr_close.reindex(common) * fx_on_common / loc_close.reindex(common)).dropna()
# DATA-QUALITY FILTER: yfinance TWD=X has occasional bad prints (e.g. 2011-10-25 Close=1.801
# instead of ~30 -> spurious -93.9% premium). The two same-company prices can never diverge to
# an implied ratio far from ADR_RATIO=5 (real premium range keeps ratio ~4.5-6.7). Drop any obs
# whose implied ratio falls outside [3, 9] as a price/FX data error. Returns & vol do NOT use FX.
VALID_LO, VALID_HI = 3.0, 9.0
ratio_valid = implied_ratio_raw.between(VALID_LO, VALID_HI)
n_premium_glitch = int((~ratio_valid).sum())
implied_ratio = implied_ratio_raw[ratio_valid]

implied_per_share_twd = adr_close.reindex(common) * fx_on_common / ADR_RATIO
premium = (implied_per_share_twd / loc_close.reindex(common) - 1.0).dropna()
premium = premium[premium.index.isin(implied_ratio.index)]  # drop data-error dates

prem_pct = premium * 100.0
roll_pctile = premium.rolling(252, min_periods=60).apply(
    lambda w: (w.rank(pct=True).iloc[-1]), raw=False
)
# rolling percentile over FULL-sample expanding as well for "record" framing
expand_pctile = premium.expanding(min_periods=60).apply(lambda w: (w <= w.iloc[-1]).mean(), raw=False)

ai_era = premium.loc[premium.index >= "2023-01-01"]
premium_stats = {
    "n": int(len(premium)),
    "period": [str(premium.index.min().date()), str(premium.index.max().date())],
    "mean_pct": float(prem_pct.mean()),
    "median_pct": float(prem_pct.median()),
    "std_pct": float(prem_pct.std()),
    "min_pct": float(prem_pct.min()),
    "min_date": str(prem_pct.idxmin().date()),
    "max_pct": float(prem_pct.max()),
    "max_date": str(prem_pct.idxmax().date()),
    "last_pct": float(prem_pct.iloc[-1]),
    "last_date": str(prem_pct.index[-1].date()),
    "last_expanding_percentile": float(expand_pctile.iloc[-1]),
    "ai_era_mean_pct": float((ai_era * 100).mean()),
    "ai_era_max_pct": float((ai_era * 100).max()),
    "ai_era_max_date": str((ai_era * 100).idxmax().date()),
    "pre_ai_mean_pct": float((premium.loc[premium.index < "2023-01-01"] * 100).mean()),
    "implied_ratio_median": float(implied_ratio.median()),
    "adr_ratio_assumed": ADR_RATIO,
    "premium_glitch_dropped": n_premium_glitch,
    "note": "premium uses same-date-label; ADR close is ~14.5h fresher than 2330 close. "
            "FX=TWD=X Close (TWD per USD), ffilled. Raw Close (not adj) for price-level parity.",
}

# --------------------------------------------------------------------------- #
# 3. returns + price discovery lead-lag (Q2)
# --------------------------------------------------------------------------- #
r_loc = np.log(loc_adj.reindex(common)).diff()
r_adr = np.log(adr_adj.reindex(common)).diff()
D = pd.DataFrame({"r_loc": r_loc, "r_adr": r_adr}).dropna()
# winsor-free; clip only obvious data errors (>50% daily = bad print) to avoid single-point leverage
mask = (D["r_loc"].abs() < 0.5) & (D["r_adr"].abs() < 0.5)
n_clip = int((~mask).sum())
D = D[mask]

# (A) US -> TW overnight (LEGIT):  r_loc(t) ~ r_adr(t-1)
regA = ols_hac(D["r_loc"], D["r_adr"].shift(1).rename("r_adr_lag1").to_frame())
# (A') with own AR(1) control
regA_ctrl = ols_hac(
    D["r_loc"],
    pd.concat([D["r_adr"].shift(1).rename("r_adr_lag1"), D["r_loc"].shift(1).rename("r_loc_lag1")], axis=1),
)
# (B) TW -> US same-day (LEGIT):   r_adr(t) ~ r_loc(t)
regB = ols_hac(D["r_adr"], D["r_loc"].rename("r_loc").to_frame())
# (B') control for prior US move
regB_ctrl = ols_hac(
    D["r_adr"],
    pd.concat([D["r_loc"].rename("r_loc"), D["r_adr"].shift(1).rename("r_adr_lag1")], axis=1),
)
# (C) DIAGNOSTIC — FORBIDDEN as predictive (lookahead/confound): r_loc(t) ~ r_adr(t) same date
regC_diagnostic = ols_hac(D["r_loc"], D["r_adr"].rename("r_adr_same_date").to_frame())

# bootstrap CI for the two legit slopes
bootA = block_bootstrap_slope(D["r_loc"], D["r_adr"].shift(1), BOOT_REPS, BLOCK, SEED)
bootB = block_bootstrap_slope(D["r_adr"], D["r_loc"], BOOT_REPS, BLOCK, SEED + 1)

# Granger causality (corroborating; caveat: daily returns conflate same-day ordering)
gc_adr_to_loc = granger_pvals(D[["r_loc", "r_adr"]], GRANGER_MAXLAG)   # r_adr -> r_loc  (US->TW)
gc_loc_to_adr = granger_pvals(D[["r_adr", "r_loc"]], GRANGER_MAXLAG)   # r_loc -> r_adr  (TW->US)

# cross-correlation function corr(r_loc(t), r_adr(t+k)); k>0 => ADR leads
ccf = {}
for k in range(-5, 6):
    ccf[str(k)] = float(D["r_loc"].corr(D["r_adr"].shift(-k)))

# --------------------------------------------------------------------------- #
# 4. volatility transmission (Q3) — Parkinson range as intraday-vol proxy
# --------------------------------------------------------------------------- #
def parkinson(df: pd.DataFrame) -> pd.Series:
    hl = np.log(df["High"] / df["Low"])
    return (hl ** 2) / (4.0 * math.log(2.0))

park_loc = parkinson(loc).reindex(common)
park_adr = parkinson(adr).reindex(common)
V = pd.DataFrame({"rv_loc": park_loc, "rv_adr": park_adr}).replace([np.inf, -np.inf], np.nan).dropna()
V = V[(V["rv_loc"] > 0) & (V["rv_adr"] > 0)]

# (V-A) US -> TW vol (LEGIT): rv_loc(t) ~ rv_adr(t-1) + rv_loc(t-1)
# rv_adr(t-1) = US session ending TW t 04:00, before 2330(t) close TW t 13:30. OK.
regVA = ols_hac(
    V["rv_loc"],
    pd.concat([V["rv_adr"].shift(1).rename("rv_adr_lag1"), V["rv_loc"].shift(1).rename("rv_loc_lag1")], axis=1),
)
# (V-B) TW -> US vol (LEGIT): rv_adr(t) ~ rv_loc(t) + rv_adr(t-1)
# rv_loc(t) ends TW t 13:30, before US session t (TW t 21:30->t+1 04:00). OK.
regVB = ols_hac(
    V["rv_adr"],
    pd.concat([V["rv_loc"].rename("rv_loc"), V["rv_adr"].shift(1).rename("rv_adr_lag1")], axis=1),
)

# log-Parkinson for Granger (more Gaussian)
lV = np.log(V)
gc_rvadr_to_rvloc = granger_pvals(lV[["rv_loc", "rv_adr"]], GRANGER_MAXLAG)  # US->TW vol
gc_rvloc_to_rvadr = granger_pvals(lV[["rv_adr", "rv_loc"]], GRANGER_MAXLAG)  # TW->US vol

# --------------------------------------------------------------------------- #
# 5. assemble results
# --------------------------------------------------------------------------- #
results = {
    "experiment_id": "K1626",
    "title": "TSM ADR vs 2330.TW — premium, price discovery, volatility transmission (two-timezone, lookahead-safe)",
    "seed": SEED,
    "data": {
        "tickers": ["TSM", "2330.TW", "TWD=X"],
        "source": "yfinance 1.2.0",
        "start": START,
        "overlap_trading_days": int(len(common)),
        "adr_only_days_dropped": n_adr_only,
        "loc_only_days_dropped": n_loc_only,
        "return_rows_used": int(len(D)),
        "return_rows_clipped_gt50pct": n_clip,
        "premium_rows_dropped_dataerror": n_premium_glitch,
        "vol_rows_used": int(len(V)),
        "adr_ratio_assumed": ADR_RATIO,
        "auto_adjust": False,
        "premium_uses": "raw Close",
        "returns_use": "Adj Close (log)",
    },
    "Q1_premium": premium_stats,
    "Q2_price_discovery": {
        "eqA_US_to_TW_overnight": {"spec": "r_loc(t) ~ const + r_adr(t-1)", "legit": True, **regA},
        "eqA_ctrl": {"spec": "r_loc(t) ~ const + r_adr(t-1) + r_loc(t-1)", "legit": True, **regA_ctrl},
        "eqB_TW_to_US_sameday": {"spec": "r_adr(t) ~ const + r_loc(t)", "legit": True, **regB},
        "eqB_ctrl": {"spec": "r_adr(t) ~ const + r_loc(t) + r_adr(t-1)", "legit": True, **regB_ctrl},
        "eqC_DIAGNOSTIC_lookahead": {
            "spec": "r_loc(t) ~ const + r_adr(t) [SAME DATE — FORBIDDEN as predictive]",
            "legit": False,
            "warning": "ADR(t) closes ~14.5h AFTER 2330(t). This is the K1108b confound; "
                       "reported only to expose spurious same-date mixing. NOT a finding.",
            **regC_diagnostic,
        },
        "bootstrap_eqA_slope_r_adr_lag1": bootA,
        "bootstrap_eqB_slope_r_loc": bootB,
        "granger_US_to_TW_r_adr_causes_r_loc_pvals": gc_adr_to_loc,
        "granger_TW_to_US_r_loc_causes_r_adr_pvals": gc_loc_to_adr,
        "granger_caveat": "daily returns conflate same-day ordering; HAC directional regressions "
                          "with explicit timing (eqA/eqB) are the primary evidence, Granger corroborates.",
        "ccf_corr_rloc_t_vs_radr_t_plus_k": ccf,
        "ccf_interpretation": "k<0 = past ADR return vs current 2330 return => ADR(US) leads TW; "
                              "k>0 = future ADR vs current 2330 => TW leads ADR. Peak at k=-1 => US leads.",
    },
    "Q3_vol_transmission": {
        "proxy": "Parkinson range = (ln(H/L))^2 / (4 ln2); no 5-min RV available (limitation)",
        "eqVA_US_to_TW": {"spec": "rv_loc(t) ~ const + rv_adr(t-1) + rv_loc(t-1)", "legit": True, **regVA},
        "eqVB_TW_to_US": {"spec": "rv_adr(t) ~ const + rv_loc(t) + rv_adr(t-1)", "legit": True, **regVB},
        "granger_US_to_TW_vol_pvals": gc_rvadr_to_rvloc,
        "granger_TW_to_US_vol_pvals": gc_rvloc_to_rvadr,
    },
}

out_json = HERE / "k1626_results.json"
out_json.write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(f"[K1626] wrote {out_json}")

# --------------------------------------------------------------------------- #
# 6. charts
# --------------------------------------------------------------------------- #
plt.rcParams.update({"figure.dpi": 110, "font.size": 10})

# (a) premium series + rolling percentile
fig, ax1 = plt.subplots(figsize=(11, 5))
ax1.plot(prem_pct.index, prem_pct.values, color="#1f77b4", lw=0.9, label="ADR premium (%)")
ax1.axhline(0, color="grey", lw=0.8, ls="--")
ax1.axhline(prem_pct.mean(), color="#1f77b4", lw=0.8, ls=":", label=f"mean {prem_pct.mean():.1f}%")
ax1.scatter([prem_pct.idxmax()], [prem_pct.max()], color="red", zorder=5,
            label=f"max {prem_pct.max():.1f}% @ {prem_pct.idxmax().date()}")
ax1.set_ylabel("ADR premium over 2330.TW (%)")
ax1.set_title("K1626 (a) TSM ADR premium vs 2330.TW  [ratio=5, same-date-label]")
ax2 = ax1.twinx()
ax2.plot(roll_pctile.index, roll_pctile.values, color="#ff7f0e", lw=0.7, alpha=0.6,
         label="rolling-252 percentile")
ax2.set_ylabel("rolling-252 percentile", color="#ff7f0e")
ax2.set_ylim(0, 1)
lines1, lab1 = ax1.get_legend_handles_labels()
lines2, lab2 = ax2.get_legend_handles_labels()
ax1.legend(lines1 + lines2, lab1 + lab2, loc="upper left", fontsize=8)
fig.tight_layout()
fig.savefig(HERE / "k1626_premium.png")
plt.close(fig)

# (b) cross-correlation function
fig, ax = plt.subplots(figsize=(9, 4.5))
ks = list(range(-5, 6))
vals = [ccf[str(k)] for k in ks]
# ccf[k] = corr(r_2330(t), r_TSM(t+k)).  k<0 -> past ADR vs current TW = ADR(US) leads;
# k>0 -> future ADR vs current TW = TW leads.  Colour the ADR-leads side (k<0) red.
colors = ["#d62728" if k < 0 else ("#1f77b4" if k > 0 else "grey") for k in ks]
ax.bar(ks, vals, color=colors)
ax.axhline(0, color="black", lw=0.8)
ax.set_xlabel("k  (corr[r_2330(t), r_TSM(t+k)];  k<0 = ADR/US leads TW,  k>0 = TW leads ADR)")
ax.set_ylabel("cross-correlation")
ax.set_title("K1626 (b) Return cross-correlation (lead-lag asymmetry)")
ax.set_xticks(ks)
fig.tight_layout()
fig.savefig(HERE / "k1626_ccf.png")
plt.close(fig)

# (c) price-discovery slope comparison (legit A vs B, + flagged diagnostic C)
fig, ax = plt.subplots(figsize=(8.5, 4.8))
names = ["US->TW\novernight\n(eqA: r_adr[t-1])", "TW->US\nsame-day\n(eqB: r_loc[t])",
         "DIAGNOSTIC\nlookahead\n(eqC same-date)"]
betas = [regA["params"]["r_adr_lag1"], regB["params"]["r_loc"], regC_diagnostic["params"]["r_adr_same_date"]]
tstats = [regA["hac_t"]["r_adr_lag1"], regB["hac_t"]["r_loc"], regC_diagnostic["hac_t"]["r_adr_same_date"]]
bar_colors = ["#2ca02c", "#1f77b4", "#bbbbbb"]
bars = ax.bar(names, betas, color=bar_colors)
for b, t in zip(bars, tstats):
    ax.text(b.get_x() + b.get_width() / 2, b.get_height(),
            f"β={b.get_height():.3f}\nHAC t={t:.1f}", ha="center",
            va="bottom" if b.get_height() >= 0 else "top", fontsize=8)
ax.axhline(0, color="black", lw=0.8)
ax.set_ylabel("slope β")
ax.set_title("K1626 (c) Price-discovery lead-lag slopes (grey = forbidden diagnostic)")
fig.tight_layout()
fig.savefig(HERE / "k1626_leadlag.png")
plt.close(fig)

# (d) vol-transmission Granger evidence (-log10 p) both directions
fig, ax = plt.subplots(figsize=(9, 4.5))
lags = list(range(1, GRANGER_MAXLAG + 1))
us_tw = [-math.log10(max(gc_rvadr_to_rvloc[str(l)], 1e-300)) for l in lags]
tw_us = [-math.log10(max(gc_rvloc_to_rvadr[str(l)], 1e-300)) for l in lags]
w = 0.38
ax.bar([l - w / 2 for l in lags], us_tw, width=w, color="#2ca02c", label="US->TW vol")
ax.bar([l + w / 2 for l in lags], tw_us, width=w, color="#1f77b4", label="TW->US vol")
ax.axhline(-math.log10(0.05), color="red", ls="--", lw=0.9, label="p=0.05")
ax.set_xlabel("Granger lag (days)")
ax.set_ylabel("-log10(p)")
ax.set_title("K1626 (d) Volatility transmission — Granger causality (Parkinson range)")
ax.set_xticks(lags)
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(HERE / "k1626_vol_transmission.png")
plt.close(fig)

print("[K1626] charts written: premium, ccf, leadlag, vol_transmission")
print("[K1626] DONE")
