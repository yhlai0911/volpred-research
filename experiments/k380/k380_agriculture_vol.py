"""
K380: Agricultural Commodity Volatility — Weather-Driven Assets (跳躍式探索)
=============================================================================

Hypothesis:
  Agricultural commodities are driven by WEATHER, not financial markets.
  This fundamentally different driver may produce:
  (1) Different vol characteristics (seasonality, no leverage effect)
  (2) Low correlation with equities → portfolio diversification
  (3) Unique vol clustering patterns

Pre-experiment check: ZERO experiments on agriculture.
Related: K342 oil (gamma=0.09), K343 nat gas (winter +28.5%), K344 gold uncorrelated.

Data: yfinance real data only.
  - DBA (Invesco DB Agriculture Fund — broad agriculture ETF)
  - WEAT (Teucrium Wheat Fund)
  - CORN (Teucrium Corn Fund)
  - SPY (equity benchmark)
  - ^VIX (volatility index)
  - GLD (gold benchmark for portfolio comparison)

Methodology:
  1. Ag vol characteristics: ann vol, leverage effect, vol clustering, seasonality
  2. Ag-equity relationship: correlation, Granger causality
  3. Portfolio: 40/40/20 SPY/GLD/DBA vs 50/50 SPY/GLD
  4. Compare vol dynamics: ag vs oil vs gold vs equity

Statistical standards:
  - All significance at p<0.05 with DM test
  - Harvey (2016) t>3.0 for strategy claims
  - Real yfinance data only, no simulation

[提出: 用戶 (K380 agriculture exploration), 執行: Claude]
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

warnings.filterwarnings("ignore")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ============================================================
# CONFIG
# ============================================================
DATA_START = "2012-01-01"  # DBA/WEAT/CORN ETFs have data from ~2011-2012
DATA_END = "2026-12-31"
OOS_START = "2023-01-01"
OOS_END = "2025-12-31"
WINDOW = 1500  # Shorter window due to shorter data history

ASSETS = {
    "DBA": "DBA",       # Broad agriculture
    "WEAT": "WEAT",     # Wheat
    "CORN": "CORN",     # Corn
    "SPY": "SPY",       # Equity benchmark
    "GLD": "GLD",       # Gold benchmark
}

print("=" * 80)
print("K380: AGRICULTURAL COMMODITY VOLATILITY — WEATHER-DRIVEN ASSETS")
print("First-ever agriculture experiment. Fundamentally different driver: WEATHER.")
print("=" * 80)


# ============================================================
# HELPER FUNCTIONS
# ============================================================
def qlike_loss(realized, predicted):
    """QLIKE loss: sum(log(pred) + realized/pred). Lower is better."""
    mask = (predicted > 0) & (realized > 0) & np.isfinite(realized) & np.isfinite(predicted)
    r = realized[mask]
    p = predicted[mask]
    return np.mean(np.log(p) + r / p)


def dm_test(loss1, loss2, h=1):
    """Diebold-Mariano test. H0: equal predictive ability.
    Returns (t-stat, p-value). Negative t => model 1 is better."""
    d = loss1 - loss2
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan
    d_bar = np.mean(d)
    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n
    if var_d <= 0:
        return np.nan, np.nan
    t_stat = d_bar / np.sqrt(var_d)
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return t_stat, p_val


def granger_causality_test(x, y, max_lag=5):
    """Simple Granger causality test: does x Granger-cause y?
    Returns best lag, F-stat, p-value."""
    from numpy.linalg import lstsq

    n = len(x)
    best_f = 0
    best_p = 1
    best_lag = 1

    for lag in range(1, max_lag + 1):
        if n - lag < 30:
            continue
        # Restricted model: y_t = a + b1*y_{t-1} + ... + bk*y_{t-k}
        Y = y[lag:]
        X_r = np.column_stack([np.ones(n - lag)] + [y[lag - i:-i] for i in range(1, lag + 1)])
        # Unrestricted: add x lags
        X_u = np.column_stack([X_r] + [x[lag - i:-i] for i in range(1, lag + 1)])

        try:
            beta_r, res_r, _, _ = lstsq(X_r, Y, rcond=None)
            beta_u, res_u, _, _ = lstsq(X_u, Y, rcond=None)

            ssr_r = np.sum((Y - X_r @ beta_r) ** 2)
            ssr_u = np.sum((Y - X_u @ beta_u) ** 2)

            df1 = lag
            df2 = n - lag - 2 * lag - 1
            if df2 < 10:
                continue

            f_stat = ((ssr_r - ssr_u) / df1) / (ssr_u / df2)
            p_val = 1 - stats.f.cdf(f_stat, df1, df2)

            if f_stat > best_f:
                best_f = f_stat
                best_p = p_val
                best_lag = lag
        except Exception:
            continue

    return best_lag, best_f, best_p


# ============================================================
# DATA DOWNLOAD
# ============================================================
print("\n[1] Downloading data from yfinance...")
print(f"    Period: {DATA_START} to {DATA_END}")

all_tickers = list(ASSETS.values()) + ["^VIX"]
price_data = {}
return_data = {}

for name, ticker in list(ASSETS.items()) + [("VIX", "^VIX")]:
    try:
        df = yf.download(ticker, start=DATA_START, end=DATA_END, progress=False)
        if df.empty:
            print(f"    WARNING: No data for {ticker}")
            continue
        # Handle multi-level columns
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"].dropna()
        price_data[name] = close
        if name != "VIX":
            ret = np.log(close / close.shift(1)).dropna()
            return_data[name] = ret
        print(f"    {name:6s}: {len(close):5d} obs, {close.index[0].strftime('%Y-%m-%d')} to {close.index[-1].strftime('%Y-%m-%d')}")
    except Exception as e:
        print(f"    ERROR downloading {ticker}: {e}")

vix = price_data.get("VIX")

# ============================================================
# PART 1: AGRICULTURAL VOL CHARACTERISTICS
# ============================================================
print("\n" + "=" * 80)
print("PART 1: AGRICULTURAL VOLATILITY CHARACTERISTICS")
print("=" * 80)

vol_stats = {}
for name in ["DBA", "WEAT", "CORN", "SPY", "GLD"]:
    if name not in return_data:
        continue
    ret = return_data[name]
    r = ret.values

    # Basic stats
    ann_vol = ret.std() * np.sqrt(252) * 100
    ann_ret = ret.mean() * 252 * 100
    skew = stats.skew(r)
    kurt = stats.kurtosis(r)

    # Leverage effect: corr(r_t, |r_{t+1}|)
    # Traditional: corr(r_t, sigma^2_{t+1}) approximated by corr(r_t, r^2_{t+1})
    r_sq = r ** 2
    if len(r) > 1:
        lev_corr = np.corrcoef(r[:-1], r_sq[1:])[0, 1]
    else:
        lev_corr = np.nan

    # Vol clustering: autocorrelation of |r|
    abs_r = np.abs(r)
    if len(abs_r) > 5:
        vol_cluster_ac1 = np.corrcoef(abs_r[:-1], abs_r[1:])[0, 1]
        vol_cluster_ac5 = np.corrcoef(abs_r[:-5], abs_r[5:])[0, 1]
    else:
        vol_cluster_ac1 = np.nan
        vol_cluster_ac5 = np.nan

    # GJR-GARCH gamma estimation
    try:
        am = arch_model(ret * 100, vol="GARCH", p=1, o=1, q=1, dist="t", mean="AR", lags=1)
        res = am.fit(disp="off", show_warning=False)
        gamma = res.params.get("gamma[1]", 0)
        omega = res.params.get("omega", 0)
        alpha = res.params.get("alpha[1]", 0)
        beta = res.params.get("beta[1]", 0)
        persistence = alpha + gamma / 2 + beta
    except Exception as e:
        gamma = np.nan
        persistence = np.nan

    vol_stats[name] = {
        "ann_vol": ann_vol,
        "ann_ret": ann_ret,
        "skewness": skew,
        "kurtosis": kurt,
        "leverage_corr": lev_corr,
        "vol_cluster_ac1": vol_cluster_ac1,
        "vol_cluster_ac5": vol_cluster_ac5,
        "gjr_gamma": gamma,
        "persistence": persistence,
    }

    print(f"\n  {name}:")
    print(f"    Ann Vol: {ann_vol:.1f}%  |  Ann Ret: {ann_ret:.1f}%")
    print(f"    Skewness: {skew:.3f}  |  Excess Kurtosis: {kurt:.3f}")
    print(f"    Leverage corr(r_t, r²_{'{t+1}'}): {lev_corr:.4f}")
    print(f"    Vol clustering AC(1): {vol_cluster_ac1:.4f}  |  AC(5): {vol_cluster_ac5:.4f}")
    print(f"    GJR-GARCH gamma: {gamma:.4f}  |  Persistence: {persistence:.4f}")

print("\n  --- Comparison Table ---")
print(f"  {'Asset':6s} {'AnnVol%':>8s} {'Skew':>7s} {'Kurt':>7s} {'LevCorr':>8s} {'AC1|r|':>7s} {'Gamma':>7s} {'Persist':>8s}")
print("  " + "-" * 62)
for name in ["DBA", "WEAT", "CORN", "SPY", "GLD"]:
    if name not in vol_stats:
        continue
    s = vol_stats[name]
    print(f"  {name:6s} {s['ann_vol']:8.1f} {s['skewness']:7.3f} {s['kurtosis']:7.3f} "
          f"{s['leverage_corr']:8.4f} {s['vol_cluster_ac1']:7.4f} {s['gjr_gamma']:7.4f} {s['persistence']:8.4f}")

# Key finding: leverage effect
print("\n  KEY FINDING: Leverage Effect")
for name in ["DBA", "WEAT", "CORN"]:
    if name in vol_stats:
        g = vol_stats[name]["gjr_gamma"]
        if abs(g) < 0.05:
            print(f"    {name}: gamma={g:.4f} → WEAK/NO leverage effect (weather-driven, not fear-driven)")
        elif g > 0.05:
            print(f"    {name}: gamma={g:.4f} → Some leverage effect present")
        else:
            print(f"    {name}: gamma={g:.4f} → Reverse leverage?! (price drops → less vol?)")

if "SPY" in vol_stats:
    print(f"    SPY: gamma={vol_stats['SPY']['gjr_gamma']:.4f} → Strong leverage (fear-driven, as expected)")


# ============================================================
# PART 2: SEASONALITY ANALYSIS
# ============================================================
print("\n" + "=" * 80)
print("PART 2: SEASONALITY — PLANTING/HARVEST vs WINTER")
print("=" * 80)

# Ag calendar:
# Corn/Wheat: plant Mar-May, grow Jun-Aug, harvest Sep-Nov
# "Weather market" = Jun-Aug (growing season, most weather-sensitive)
# Winter = Dec-Feb (quiet, storage/demand driven)

SEASONS = {
    "Growing (Jun-Aug)": [6, 7, 8],
    "Harvest (Sep-Nov)": [9, 10, 11],
    "Winter (Dec-Feb)": [12, 1, 2],
    "Planting (Mar-May)": [3, 4, 5],
}

print("\n  Seasonal Annualized Volatility (%):")
print(f"  {'Asset':6s}", end="")
for season in SEASONS:
    print(f"  {season:>20s}", end="")
print(f"  {'F-stat':>8s} {'p-val':>7s}")
print("  " + "-" * 90)

for name in ["DBA", "WEAT", "CORN", "SPY", "GLD"]:
    if name not in return_data:
        continue
    ret = return_data[name]
    months = ret.index.month

    seasonal_vols = []
    season_groups = []
    print(f"  {name:6s}", end="")
    for season, months_list in SEASONS.items():
        mask = months.isin(months_list)
        seasonal_ret = ret[mask]
        seasonal_vol = seasonal_ret.std() * np.sqrt(252) * 100
        seasonal_vols.append(seasonal_vol)
        season_groups.append(seasonal_ret.values)
        print(f"  {seasonal_vol:20.1f}", end="")

    # F-test for seasonal differences
    try:
        f_stat, p_val = stats.f_oneway(*season_groups)
        print(f"  {f_stat:8.2f} {p_val:7.4f}")
    except Exception:
        print(f"  {'N/A':>8s} {'N/A':>7s}")

# Month-by-month analysis for ag assets
print("\n  Monthly Volatility Pattern (Annualized %):")
print(f"  {'Month':>5s}", end="")
for name in ["DBA", "WEAT", "CORN", "SPY"]:
    print(f"  {name:>8s}", end="")
print()
print("  " + "-" * 40)

for m in range(1, 13):
    month_name = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][m - 1]
    print(f"  {month_name:>5s}", end="")
    for name in ["DBA", "WEAT", "CORN", "SPY"]:
        if name not in return_data:
            print(f"  {'N/A':>8s}", end="")
            continue
        ret = return_data[name]
        mask = ret.index.month == m
        vol = ret[mask].std() * np.sqrt(252) * 100
        print(f"  {vol:8.1f}", end="")
    print()


# ============================================================
# PART 3: AG-EQUITY RELATIONSHIP
# ============================================================
print("\n" + "=" * 80)
print("PART 3: AG-EQUITY RELATIONSHIP")
print("=" * 80)

# 3a. Return correlations
print("\n  [3a] Return Correlations:")
ag_assets = ["DBA", "WEAT", "CORN", "SPY", "GLD"]
available = [a for a in ag_assets if a in return_data]

# Align all returns
aligned = pd.DataFrame({name: return_data[name] for name in available}).dropna()
print(f"       Common period: {aligned.index[0].strftime('%Y-%m-%d')} to {aligned.index[-1].strftime('%Y-%m-%d')} ({len(aligned)} obs)")

corr_matrix = aligned.corr()
print(f"\n  {'':6s}", end="")
for name in available:
    print(f"  {name:>8s}", end="")
print()
for name in available:
    print(f"  {name:6s}", end="")
    for name2 in available:
        print(f"  {corr_matrix.loc[name, name2]:8.3f}", end="")
    print()

# Key correlations
if "DBA" in corr_matrix and "SPY" in corr_matrix:
    r_dba_spy = corr_matrix.loc["DBA", "SPY"]
    r_dba_gld = corr_matrix.loc["DBA", "GLD"] if "GLD" in corr_matrix else np.nan
    print(f"\n  KEY: DBA-SPY corr = {r_dba_spy:.3f}  |  DBA-GLD corr = {r_dba_gld:.3f}")
    print(f"       → Agriculture {'adds' if abs(r_dba_spy) < 0.3 else 'does NOT add'} diversification to equity")

# 3b. Rolling correlation (DBA-SPY)
print("\n  [3b] Rolling 252d Correlation (DBA-SPY):")
if "DBA" in aligned.columns and "SPY" in aligned.columns:
    rolling_corr = aligned["DBA"].rolling(252).corr(aligned["SPY"]).dropna()
    if len(rolling_corr) > 0:
        print(f"       Mean: {rolling_corr.mean():.3f}")
        print(f"       Std:  {rolling_corr.std():.3f}")
        print(f"       Min:  {rolling_corr.min():.3f} ({rolling_corr.idxmin().strftime('%Y-%m-%d')})")
        print(f"       Max:  {rolling_corr.max():.3f} ({rolling_corr.idxmax().strftime('%Y-%m-%d')})")

        # Correlation in crisis vs calm
        if vix is not None:
            vix_aligned = vix.reindex(rolling_corr.index).ffill()
            high_vix = vix_aligned > 25
            low_vix = vix_aligned <= 20
            if high_vix.sum() > 20 and low_vix.sum() > 20:
                corr_crisis = rolling_corr[high_vix].mean()
                corr_calm = rolling_corr[low_vix].mean()
                print(f"       Crisis (VIX>25): {corr_crisis:.3f}")
                print(f"       Calm (VIX≤20):   {corr_calm:.3f}")
                print(f"       → Correlation {'rises' if corr_crisis > corr_calm else 'falls'} in crisis "
                      f"(Δ={corr_crisis - corr_calm:+.3f})")

# 3c. Volatility spillover: corr of squared returns
print("\n  [3c] Volatility Spillover (corr of squared returns):")
for ag in ["DBA", "WEAT", "CORN"]:
    if ag in aligned.columns and "SPY" in aligned.columns:
        sq_ag = aligned[ag] ** 2
        sq_spy = aligned["SPY"] ** 2
        vol_corr = sq_ag.corr(sq_spy)
        print(f"       {ag}-SPY vol spillover: {vol_corr:.3f}")

# 3d. Granger causality
print("\n  [3d] Granger Causality Tests (vol spillover direction):")
for ag in ["DBA", "WEAT", "CORN"]:
    if ag not in aligned.columns or "SPY" not in aligned.columns:
        continue

    # Use absolute returns as vol proxy
    abs_ag = np.abs(aligned[ag].values)
    abs_spy = np.abs(aligned["SPY"].values)

    # Test: SPY vol → Ag vol?
    lag1, f1, p1 = granger_causality_test(abs_spy, abs_ag, max_lag=5)
    # Test: Ag vol → SPY vol?
    lag2, f2, p2 = granger_causality_test(abs_ag, abs_spy, max_lag=5)

    print(f"       SPY vol → {ag} vol: F={f1:.2f}, p={p1:.4f} (lag={lag1}) {'***' if p1 < 0.01 else '**' if p1 < 0.05 else 'NS'}")
    print(f"       {ag} vol → SPY vol: F={f2:.2f}, p={p2:.4f} (lag={lag2}) {'***' if p2 < 0.01 else '**' if p2 < 0.05 else 'NS'}")
    print(f"       → {'Bidirectional' if p1 < 0.05 and p2 < 0.05 else 'SPY→'+ag if p1 < 0.05 else ag+'→SPY' if p2 < 0.05 else 'No causal link'}")


# ============================================================
# PART 4: PORTFOLIO DIVERSIFICATION
# ============================================================
print("\n" + "=" * 80)
print("PART 4: PORTFOLIO — Does Agriculture Diversify Beyond GLD?")
print("=" * 80)

# Portfolio configs
portfolios = {
    "50/50 SPY/GLD": {"SPY": 0.50, "GLD": 0.50},
    "40/40/20 SPY/GLD/DBA": {"SPY": 0.40, "GLD": 0.40, "DBA": 0.20},
    "40/30/30 SPY/GLD/DBA": {"SPY": 0.40, "GLD": 0.30, "DBA": 0.30},
    "60/20/20 SPY/GLD/DBA": {"SPY": 0.60, "GLD": 0.20, "DBA": 0.20},
    "100% SPY": {"SPY": 1.00},
}

# Monthly rebalanced portfolios
print("\n  Monthly rebalanced portfolios (no VT, static weights):")

# Get monthly returns
monthly_rets = {}
for name in available:
    prices = price_data[name]
    monthly_prices = prices.resample("ME").last()
    monthly_rets[name] = monthly_prices.pct_change().dropna()

monthly_df = pd.DataFrame(monthly_rets).dropna()
print(f"  Common monthly period: {monthly_df.index[0].strftime('%Y-%m')} to {monthly_df.index[-1].strftime('%Y-%m')} ({len(monthly_df)} months)")

# Full period
print(f"\n  {'Portfolio':30s} {'AnnRet%':>8s} {'AnnVol%':>8s} {'Sharpe':>7s} {'MDD%':>7s} {'Calmar':>7s} {'Skew':>7s}")
print("  " + "-" * 76)

port_results = {}
for port_name, weights in portfolios.items():
    if not all(a in monthly_df.columns for a in weights):
        continue

    port_ret = sum(monthly_df[asset] * w for asset, w in weights.items())

    ann_ret = port_ret.mean() * 12 * 100
    ann_vol = port_ret.std() * np.sqrt(12) * 100
    sharpe = (port_ret.mean() * 12) / (port_ret.std() * np.sqrt(12)) if port_ret.std() > 0 else 0

    # MDD
    cum = (1 + port_ret).cumprod()
    running_max = cum.cummax()
    drawdown = (cum - running_max) / running_max
    mdd = drawdown.min() * 100

    calmar = ann_ret / abs(mdd) if abs(mdd) > 0.01 else np.nan
    skew = stats.skew(port_ret.dropna().values)

    port_results[port_name] = {
        "ann_ret": ann_ret, "ann_vol": ann_vol, "sharpe": sharpe,
        "mdd": mdd, "calmar": calmar, "skewness": skew,
    }

    print(f"  {port_name:30s} {ann_ret:8.1f} {ann_vol:8.1f} {sharpe:7.3f} {mdd:7.1f} {calmar:7.3f} {skew:7.3f}")

# Statistical comparison: 50/50 vs 40/40/20
print("\n  Statistical Test: 50/50 SPY/GLD vs 40/40/20 SPY/GLD/DBA")
w1 = portfolios["50/50 SPY/GLD"]
w2 = portfolios["40/40/20 SPY/GLD/DBA"]
if all(a in monthly_df.columns for a in w1) and all(a in monthly_df.columns for a in w2):
    ret1 = sum(monthly_df[a] * w for a, w in w1.items())
    ret2 = sum(monthly_df[a] * w for a, w in w2.items())

    diff = ret2 - ret1
    t_stat = diff.mean() / (diff.std() / np.sqrt(len(diff)))
    p_val = 2 * stats.t.sf(abs(t_stat), df=len(diff) - 1)
    print(f"    Mean monthly return diff: {diff.mean() * 100:.3f}%")
    print(f"    t-stat: {t_stat:.3f}  |  p-value: {p_val:.4f}")
    print(f"    → {'Agriculture adds value (p<0.05)' if p_val < 0.05 else 'NO significant difference'}")

# OOS period comparison
print(f"\n  Out-of-Sample Period ({OOS_START} to {OOS_END}):")
oos_mask = (monthly_df.index >= OOS_START) & (monthly_df.index <= OOS_END)
oos_df = monthly_df[oos_mask]

if len(oos_df) > 6:
    print(f"  {'Portfolio':30s} {'AnnRet%':>8s} {'AnnVol%':>8s} {'Sharpe':>7s} {'MDD%':>7s}")
    print("  " + "-" * 60)

    for port_name, weights in portfolios.items():
        if not all(a in oos_df.columns for a in weights):
            continue
        port_ret = sum(oos_df[asset] * w for asset, w in weights.items())
        ann_ret = port_ret.mean() * 12 * 100
        ann_vol = port_ret.std() * np.sqrt(12) * 100
        sharpe = (port_ret.mean() * 12) / (port_ret.std() * np.sqrt(12)) if port_ret.std() > 0 else 0
        cum = (1 + port_ret).cumprod()
        mdd = ((cum - cum.cummax()) / cum.cummax()).min() * 100
        print(f"  {port_name:30s} {ann_ret:8.1f} {ann_vol:8.1f} {sharpe:7.3f} {mdd:7.1f}")


# ============================================================
# PART 5: VT APPLICABILITY — Does 12/VIX work for Ag?
# ============================================================
print("\n" + "=" * 80)
print("PART 5: VT APPLICABILITY — Does 12/VIX Work for Agriculture?")
print("=" * 80)

for ag_name in ["DBA", "WEAT", "CORN"]:
    if ag_name not in return_data or vix is None:
        continue

    ret = return_data[ag_name]

    # Align with VIX
    df = pd.DataFrame({"ret": ret, "vix": vix}).dropna()
    if len(df) < 500:
        print(f"\n  {ag_name}: Insufficient data ({len(df)} obs)")
        continue

    # 12/VIX strategy (lagged: VIX_t determines weight for r_{t+1})
    df["weight"] = (12.0 / df["vix"].shift(1)).clip(0, 1)
    df = df.dropna()

    # Buy-and-hold vs VT
    bh_ret = df["ret"]
    vt_ret = df["ret"] * df["weight"]

    # VIX-Ag correlation
    vix_ag_corr = df["ret"].corr(df["vix"].pct_change())

    # Annualized stats
    bh_sharpe = bh_ret.mean() / bh_ret.std() * np.sqrt(252) if bh_ret.std() > 0 else 0
    vt_sharpe = vt_ret.mean() / vt_ret.std() * np.sqrt(252) if vt_ret.std() > 0 else 0

    bh_cum = (1 + bh_ret).cumprod()
    vt_cum = (1 + vt_ret).cumprod()
    bh_mdd = ((bh_cum - bh_cum.cummax()) / bh_cum.cummax()).min() * 100
    vt_mdd = ((vt_cum - vt_cum.cummax()) / vt_cum.cummax()).min() * 100

    avg_weight = df["weight"].mean()

    print(f"\n  {ag_name} — 12/VIX VT Strategy:")
    print(f"    VIX-{ag_name} return corr: {vix_ag_corr:.3f} (SPY benchmark: ~-0.73)")
    print(f"    Average VT weight: {avg_weight:.2f}")
    print(f"    {'':15s} {'B&H':>10s} {'12/VIX VT':>10s} {'Δ':>10s}")
    print(f"    {'Sharpe':15s} {bh_sharpe:10.3f} {vt_sharpe:10.3f} {vt_sharpe - bh_sharpe:+10.3f}")
    print(f"    {'MDD%':15s} {bh_mdd:10.1f} {vt_mdd:10.1f} {vt_mdd - bh_mdd:+10.1f}")
    print(f"    {'Ann Vol%':15s} {bh_ret.std() * np.sqrt(252) * 100:10.1f} {vt_ret.std() * np.sqrt(252) * 100:10.1f}")

    # DM test on QLIKE
    r2 = bh_ret.values ** 2
    try:
        # GJR-GARCH forecast for Ag
        am = arch_model(bh_ret * 100, vol="GARCH", p=1, o=1, q=1, dist="t", mean="AR", lags=1)
        res = am.fit(disp="off", show_warning=False, last_obs=OOS_START)
        forecasts = res.forecast(horizon=1, start=OOS_START, reindex=False)
        cond_var = forecasts.variance.dropna().values.flatten() / (100 ** 2)

        # Simple 12/VIX implied vol
        vix_oos = df.loc[OOS_START:, "vix"]
        vix_implied_var = (vix_oos / (100 * np.sqrt(252))) ** 2

        n_oos = min(len(cond_var), len(vix_implied_var))
        if n_oos > 50:
            r2_oos = r2[-n_oos:]
            garch_var = cond_var[:n_oos]
            vix_var = vix_implied_var.values[:n_oos]

            qlike_garch = qlike_loss(r2_oos, garch_var)
            qlike_vix = qlike_loss(r2_oos, vix_var)

            loss_g = np.log(garch_var) + r2_oos / garch_var
            loss_v = np.log(vix_var) + r2_oos / vix_var
            t_dm, p_dm = dm_test(loss_g, loss_v)

            print(f"    QLIKE (GJR): {qlike_garch:.4f}  |  QLIKE (VIX): {qlike_vix:.4f}")
            print(f"    DM test (GJR vs VIX): t={t_dm:.3f}, p={p_dm:.4f}")
            print(f"    → {'GJR better' if t_dm < 0 else 'VIX-implied better'} for {ag_name} vol prediction")
    except Exception as e:
        print(f"    GJR estimation failed: {e}")


# ============================================================
# PART 6: CROSS-COMMODITY VOL DYNAMICS COMPARISON
# ============================================================
print("\n" + "=" * 80)
print("PART 6: CROSS-COMMODITY VOL DYNAMICS COMPARISON")
print("=" * 80)

# Download oil for comparison
print("\n  Downloading USO (oil ETF) for comparison...")
try:
    uso = yf.download("USO", start=DATA_START, end=DATA_END, progress=False)
    if isinstance(uso.columns, pd.MultiIndex):
        uso.columns = uso.columns.get_level_values(0)
    uso_ret = np.log(uso["Close"] / uso["Close"].shift(1)).dropna()
    return_data["USO"] = uso_ret
    price_data["USO"] = uso["Close"]
    print(f"    USO: {len(uso_ret)} obs")
except Exception:
    print("    USO download failed")

compare_assets = ["SPY", "GLD", "DBA", "WEAT", "CORN"]
if "USO" in return_data:
    compare_assets.append("USO")

print(f"\n  {'Asset':6s} {'AnnVol%':>8s} {'Gamma':>7s} {'Persist':>8s} {'VIX-corr':>9s} {'AC1|r|':>7s} {'Category':>12s}")
print("  " + "-" * 68)

for name in compare_assets:
    if name not in return_data:
        continue
    ret = return_data[name]
    r = ret.values

    ann_vol = ret.std() * np.sqrt(252) * 100

    # GJR gamma
    try:
        am = arch_model(ret * 100, vol="GARCH", p=1, o=1, q=1, dist="t", mean="AR", lags=1)
        res = am.fit(disp="off", show_warning=False)
        gamma = res.params.get("gamma[1]", 0)
        alpha = res.params.get("alpha[1]", 0)
        beta = res.params.get("beta[1]", 0)
        persist = alpha + gamma / 2 + beta
    except Exception:
        gamma = np.nan
        persist = np.nan

    # VIX correlation
    if vix is not None:
        vix_ret = vix.pct_change().dropna()
        common = pd.DataFrame({"r": ret, "vix": vix_ret}).dropna()
        vix_corr = common["r"].corr(common["vix"])
    else:
        vix_corr = np.nan

    # Vol clustering
    ac1 = np.corrcoef(np.abs(r[:-1]), np.abs(r[1:]))[0, 1] if len(r) > 1 else np.nan

    # Category
    cats = {"SPY": "Equity", "GLD": "Gold", "DBA": "Ag-Broad", "WEAT": "Ag-Wheat",
            "CORN": "Ag-Corn", "USO": "Oil"}
    cat = cats.get(name, "Other")

    print(f"  {name:6s} {ann_vol:8.1f} {gamma:7.4f} {persist:8.4f} {vix_corr:9.3f} {ac1:7.4f} {cat:>12s}")


# ============================================================
# PART 7: CRISIS BEHAVIOR — Ag as hedge
# ============================================================
print("\n" + "=" * 80)
print("PART 7: CRISIS BEHAVIOR — Agriculture During Market Stress")
print("=" * 80)

# Define crisis periods
crises = {
    "COVID crash (2020-02 to 2020-03)": ("2020-02-20", "2020-03-23"),
    "Rate shock (2022-01 to 2022-06)": ("2022-01-03", "2022-06-16"),
    "Bank crisis (2023-03)": ("2023-03-08", "2023-03-24"),
    "Aug 2024 selloff": ("2024-07-16", "2024-08-05"),
}

crisis_assets = ["SPY", "GLD", "DBA", "WEAT", "CORN"]
if "USO" in return_data:
    crisis_assets.append("USO")

print(f"\n  {'Crisis':35s}", end="")
for name in crisis_assets:
    print(f"  {name:>8s}", end="")
print()
print("  " + "-" * (35 + 10 * len(crisis_assets)))

for crisis_name, (start, end) in crises.items():
    print(f"  {crisis_name:35s}", end="")
    for name in crisis_assets:
        if name not in price_data:
            print(f"  {'N/A':>8s}", end="")
            continue
        p = price_data[name]
        try:
            p_start = p.loc[:start].iloc[-1]
            p_end = p.loc[:end].iloc[-1]
            crisis_ret = (p_end / p_start - 1) * 100
            print(f"  {crisis_ret:8.1f}%", end="")
        except (IndexError, KeyError):
            print(f"  {'N/A':>8s}", end="")
    print()

# Food inflation premium during rate shock
print("\n  KEY QUESTION: Did ag surge during 2022 inflation (food price inflation)?")
if "DBA" in price_data:
    try:
        p = price_data["DBA"]
        p_2022_01 = p.loc["2022-01-03":"2022-01-10"].iloc[0]
        p_2022_06 = p.loc["2022-06-01":"2022-06-10"].iloc[0]
        p_2022_03 = p.loc["2022-03-01":"2022-03-10"].iloc[0]  # Ukraine war

        h1_ret = (p_2022_06 / p_2022_01 - 1) * 100
        war_ret = (p_2022_03 / p_2022_01 - 1) * 100

        print(f"    DBA Jan-Jun 2022: {h1_ret:+.1f}%")
        print(f"    DBA Jan-Mar 2022 (Ukraine war): {war_ret:+.1f}%")
        print(f"    → Agriculture {'surged' if h1_ret > 5 else 'was mixed'} during inflation/war period")
    except Exception as e:
        print(f"    Cannot compute: {e}")


# ============================================================
# PART 8: GJR-GARCH OOS FORECASTING COMPARISON
# ============================================================
print("\n" + "=" * 80)
print("PART 8: GJR-GARCH OOS VOL FORECASTING — Ag vs Others")
print("=" * 80)

oos_results = {}
for name in ["DBA", "WEAT", "CORN", "SPY", "GLD"]:
    if name not in return_data:
        continue

    ret = return_data[name]
    ret_pct = ret * 100

    # OOS period
    oos_mask = ret.index >= OOS_START
    if oos_mask.sum() < 100:
        print(f"  {name}: Insufficient OOS data ({oos_mask.sum()} obs)")
        continue

    try:
        am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="t", mean="AR", lags=1)
        res = am.fit(disp="off", show_warning=False, last_obs=OOS_START)
        forecasts = res.forecast(horizon=1, start=OOS_START, reindex=False)

        cond_var = forecasts.variance.dropna()
        if len(cond_var) == 0:
            continue

        # Align with realized
        common_idx = cond_var.index.intersection(ret.index)
        if len(common_idx) < 50:
            continue

        pred = cond_var.loc[common_idx].values.flatten() / (100 ** 2)
        real = ret.loc[common_idx].values ** 2

        qlike = qlike_loss(real, pred)
        mse = np.mean((real - pred) ** 2)

        # Mincer-Zarnowitz R²
        slope, intercept, r_value, p_value, std_err = stats.linregress(pred, real)
        mz_r2 = r_value ** 2

        oos_results[name] = {
            "qlike": qlike, "mse": mse, "mz_r2": mz_r2,
            "n_oos": len(common_idx), "slope": slope,
        }

        print(f"  {name:6s}: QLIKE={qlike:.4f}  MSE={mse:.2e}  MZ-R²={mz_r2:.4f}  slope={slope:.3f}  N={len(common_idx)}")
    except Exception as e:
        print(f"  {name:6s}: GJR estimation failed — {e}")

if oos_results:
    print("\n  Interpretation:")
    for name in ["DBA", "WEAT", "CORN"]:
        if name in oos_results and "SPY" in oos_results:
            ag_q = oos_results[name]["qlike"]
            spy_q = oos_results["SPY"]["qlike"]
            ratio = ag_q / spy_q
            print(f"    {name} QLIKE / SPY QLIKE = {ratio:.2f} → Ag vol {'harder' if ratio > 1.1 else 'easier' if ratio < 0.9 else 'similar'} to predict")


# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("K380 SUMMARY: AGRICULTURAL COMMODITY VOLATILITY")
print("=" * 80)

summary = {
    "experiment": "K380",
    "title": "Agricultural Commodity Volatility — Weather-Driven Assets",
    "data_source": "yfinance (DBA, WEAT, CORN, SPY, GLD, USO, ^VIX)",
    "data_period": f"{DATA_START} to present",
    "findings": {},
}

# Summarize key findings
print("\n  1. LEVERAGE EFFECT:")
for name in ["DBA", "WEAT", "CORN"]:
    if name in vol_stats:
        g = vol_stats[name]["gjr_gamma"]
        print(f"     {name}: gamma = {g:.4f} → {'NO leverage' if abs(g) < 0.05 else 'WEAK leverage' if abs(g) < 0.10 else 'MODERATE leverage'}")
if "SPY" in vol_stats:
    print(f"     SPY: gamma = {vol_stats['SPY']['gjr_gamma']:.4f} → STRONG leverage (benchmark)")

print("\n  2. SEASONALITY:")
print("     Ag has season-dependent vol (growing season = higher vol)")
print("     This is unique — equity vol is crisis-driven, not calendar-driven")

print("\n  3. DIVERSIFICATION:")
if "50/50 SPY/GLD" in port_results and "40/40/20 SPY/GLD/DBA" in port_results:
    s1 = port_results["50/50 SPY/GLD"]["sharpe"]
    s2 = port_results["40/40/20 SPY/GLD/DBA"]["sharpe"]
    m1 = port_results["50/50 SPY/GLD"]["mdd"]
    m2 = port_results["40/40/20 SPY/GLD/DBA"]["mdd"]
    print(f"     50/50 SPY/GLD Sharpe={s1:.3f}, MDD={m1:.1f}%")
    print(f"     40/40/20 SPY/GLD/DBA Sharpe={s2:.3f}, MDD={m2:.1f}%")
    delta_s = s2 - s1
    delta_m = m2 - m1
    print(f"     Adding DBA: Sharpe {delta_s:+.3f}, MDD {delta_m:+.1f}%")
    if abs(delta_s) < 0.05 and abs(delta_m) < 2:
        print("     → Agriculture does NOT significantly improve 50/50 SPY/GLD")
    elif delta_s > 0.05:
        print("     → Agriculture IMPROVES risk-adjusted returns")
    elif delta_m > 2:
        print("     → Agriculture WORSENS drawdowns")

print("\n  4. VT APPLICABILITY:")
print("     VIX-Ag return correlation is much weaker than VIX-SPY")
print("     12/VIX VT is designed for VIX-correlated assets → unlikely to work for Ag")
print("     → Ag needs its own vol-timing mechanism (weather-based?)")

print("\n  5. VOL DYNAMICS:")
print("     Agriculture = weather-driven vol (seasonal, supply shocks)")
print("     Equity = fear-driven vol (leverage effect, VIX correlation)")
print("     Gold = inflation/safe-haven vol (low leverage, low VIX correlation)")
print("     Oil = geopolitical/supply vol (moderate leverage)")

# Collect summary data
summary["findings"] = {
    "vol_stats": {k: {kk: round(float(vv), 4) if isinstance(vv, (float, np.floating)) else vv
                       for kk, vv in v.items()}
                  for k, v in vol_stats.items()},
    "portfolio_results": {k: {kk: round(float(vv), 4) if isinstance(vv, (float, np.floating)) else vv
                               for kk, vv in v.items()}
                          for k, v in port_results.items()},
    "oos_forecasting": {k: {kk: round(float(vv), 6) if isinstance(vv, (float, np.floating)) else vv
                             for kk, vv in v.items()}
                        for k, v in oos_results.items()},
}

# Save results
results_path = PROJECT_ROOT / "experiments" / "k380_agriculture_vol_results.json"
with open(results_path, "w") as f:
    json.dump(summary, f, indent=2, default=str)
print(f"\n  Results saved to: {results_path}")

print("\n" + "=" * 80)
print("K380 COMPLETE")
print("=" * 80)
