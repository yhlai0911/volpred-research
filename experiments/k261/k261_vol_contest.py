"""
K261: The Ultimate Vol Forecasting Contest — Every Model Head-to-Head on 5 Assets
==================================================================================
[提出: 用戶, 執行: Claude]

Background:
  We have tested many models individually across experiments K1-K260.
  This experiment puts ALL major models in a single head-to-head comparison
  on 5 assets, creating a definitive ranking table.

Data:
  SPY, QQQ, GLD, TLT, BTC-USD daily from yfinance
  In-sample: rolling w=2000
  OOS: 2023-01-01 to 2024-12-31

Models:
  1. GJR-GARCH(1,1,1)
  2. EWMA(lambda=0.94)
  3. EWMA(lambda=0.97)
  4. Simple 22d rolling variance
  5. VIX²/252 (SPY only)
  6. Parkinson range estimator (22d rolling)
  7. Combined InvQLIKE (K216 winner: 70% GJR + 30% EWMA)
  8. Equal-weight ensemble (avg of all applicable models)

Evaluation:
  A. QLIKE + MSE scores per model × asset
  B. Pairwise Diebold-Mariano test matrix
  C. Model Confidence Set (MCS) at alpha=0.1
  D. Summary ranking table

Output: Console results + JSON to storage/results/k261_vol_contest.json
"""

import sys
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from datetime import datetime
import json
import itertools

np.random.seed(42)

# ============================================================
# CONFIG
# ============================================================
WINDOW = 2000
OOS_START = "2023-01-01"
OOS_END = "2025-01-01"
DATA_START = "2010-01-01"  # enough lookback for w=2000 before OOS

ASSETS = {
    "SPY": {"ticker": "SPY", "has_vix": True, "has_range": True},
    "QQQ": {"ticker": "QQQ", "has_vix": False, "has_range": True},
    "GLD": {"ticker": "GLD", "has_vix": False, "has_range": True},
    "TLT": {"ticker": "TLT", "has_vix": False, "has_range": True},
    "BTC": {"ticker": "BTC-USD", "has_vix": False, "has_range": True},
}

EWMA_LAMBDAS = [0.94, 0.97]
MCS_ALPHA = 0.10
N_BOOTSTRAP_MCS = 5000

print("=" * 80)
print("K261: THE ULTIMATE VOL FORECASTING CONTEST")
print("=" * 80)
print(f"  Assets: {list(ASSETS.keys())}")
print(f"  OOS period: {OOS_START} to {OOS_END}")
print(f"  Rolling window: {WINDOW}")
print(f"  MCS alpha: {MCS_ALPHA}")
print(f"  Bootstrap reps: {N_BOOTSTRAP_MCS}")

# ============================================================
# 1. Download Data
# ============================================================
print("\n" + "=" * 80)
print("[1/6] DOWNLOADING DATA")
print("=" * 80)

price_data = {}
range_data = {}  # for Parkinson

for name, cfg in ASSETS.items():
    raw = yf.download(cfg["ticker"], start=DATA_START, end=OOS_END, progress=False, auto_adjust=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    col = "Adj Close" if "Adj Close" in raw.columns else "Close"
    close = raw[col].copy()
    close.name = name

    # Log returns (percentage for arch)
    ret = np.log(close / close.shift(1)).dropna() * 100
    price_data[name] = ret

    # High/Low for Parkinson
    if cfg["has_range"] and "High" in raw.columns and "Low" in raw.columns:
        high = raw["High"].copy()
        low = raw["Low"].copy()
        range_data[name] = pd.DataFrame({"high": high, "low": low}, index=raw.index).dropna()

    print(f"  {name}: {ret.index[0].strftime('%Y-%m-%d')} to {ret.index[-1].strftime('%Y-%m-%d')} ({len(ret)} obs)")

# VIX for SPY
vix_raw = yf.download("^VIX", start=DATA_START, end=OOS_END, progress=False, auto_adjust=False)
if isinstance(vix_raw.columns, pd.MultiIndex):
    vix_raw.columns = vix_raw.columns.get_level_values(0)
vix_close = vix_raw["Close"].copy()
vix_close.name = "VIX"
print(f"  VIX: {vix_close.index[0].strftime('%Y-%m-%d')} to {vix_close.index[-1].strftime('%Y-%m-%d')} ({len(vix_close)} obs)")

# ============================================================
# 2. Model Definitions
# ============================================================
print("\n" + "=" * 80)
print("[2/6] DEFINING MODELS")
print("=" * 80)


def fit_gjr_oos(returns, window=WINDOW):
    """GJR-GARCH(1,1,1) rolling OOS one-step-ahead variance forecast."""
    n = len(returns)
    sigma2_oos = np.full(n, np.nan)

    for t in range(window, n):
        train = returns.iloc[t - window:t]
        try:
            am = arch_model(train, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Zero")
            res = am.fit(disp="off", show_warning=False)
            fc = res.forecast(horizon=1)
            sigma2_oos[t] = fc.variance.values[-1, 0] / 10000  # pct^2 -> decimal^2
        except Exception:
            if t > window:
                sigma2_oos[t] = sigma2_oos[t - 1]
            else:
                sigma2_oos[t] = np.var(train.values) / 10000

    return pd.Series(sigma2_oos, index=returns.index)


def ewma_variance(returns_pct, lam):
    """EWMA variance (exponentially weighted), returns decimal variance."""
    ret_dec = returns_pct.values / 100.0
    n = len(ret_dec)
    var = np.full(n, np.nan)
    var[0] = ret_dec[0] ** 2
    for t in range(1, n):
        var[t] = lam * var[t - 1] + (1 - lam) * ret_dec[t - 1] ** 2
    # Shift by 1 for OOS (forecast for t using info up to t-1)
    var_oos = np.full(n, np.nan)
    var_oos[1:] = var[:-1]
    return pd.Series(var_oos, index=returns_pct.index)


def rolling_variance_22d(returns_pct, window=22):
    """Simple 22d rolling variance, returns decimal variance."""
    ret_dec = returns_pct / 100.0
    var = ret_dec.rolling(window=window).var()
    # Shift by 1 for OOS
    return var.shift(1)


def vix_implied_variance(vix_series, returns_index):
    """VIX^2/252 as daily variance forecast. Already a forecast for next day."""
    vix_aligned = vix_series.reindex(returns_index).ffill()
    # VIX is annualized %, convert to daily decimal variance
    daily_var = (vix_aligned / 100) ** 2 / 252
    # Shift by 1: VIX(t) forecasts var(t+1)
    return daily_var.shift(1)


def parkinson_variance(range_df, returns_index, window=22):
    """Parkinson (1980) range-based variance estimator, 22d rolling."""
    # Parkinson: sigma^2 = (1/(4*n*ln2)) * sum(ln(H/L))^2
    if range_df is None or len(range_df) == 0:
        return pd.Series(np.nan, index=returns_index)

    log_hl = np.log(range_df["high"] / range_df["low"])
    log_hl_sq = log_hl ** 2
    factor = 1.0 / (4 * np.log(2))
    park_var = factor * log_hl_sq.rolling(window=window).mean()
    park_var = park_var.reindex(returns_index).ffill()
    # Shift by 1 for OOS
    return park_var.shift(1)


def combined_invqlike(gjr_var, ewma_var, w_gjr=0.70, w_ewma=0.30):
    """Combined forecast: 70% GJR + 30% EWMA (K216 winner)."""
    return w_gjr * gjr_var + w_ewma * ewma_var


# ============================================================
# 3. Generate All Forecasts
# ============================================================
print("\n" + "=" * 80)
print("[3/6] GENERATING FORECASTS FOR ALL MODEL x ASSET COMBINATIONS")
print("=" * 80)

# Store all forecasts: {asset: {model: Series}}
all_forecasts = {}
# Store realized variance (proxy): r^2 in decimal
all_realized = {}

MODEL_NAMES = [
    "GJR-GARCH",
    "EWMA(0.94)",
    "EWMA(0.97)",
    "RollVar22d",
    "VIX²/252",
    "Parkinson22d",
    "Combined70/30",
    "EqualEnsemble",
]

for asset_name, cfg in ASSETS.items():
    print(f"\n  --- {asset_name} ---")
    ret = price_data[asset_name]

    # Realized variance proxy: r^2 (decimal)
    r2 = (ret / 100.0) ** 2
    all_realized[asset_name] = r2

    forecasts = {}

    # 1. GJR-GARCH
    print(f"    GJR-GARCH(1,1,1)...", end="", flush=True)
    gjr_var = fit_gjr_oos(ret, window=WINDOW)
    forecasts["GJR-GARCH"] = gjr_var
    n_valid = gjr_var.notna().sum()
    print(f" done ({n_valid} valid OOS points)")

    # 2. EWMA(0.94)
    ewma94 = ewma_variance(ret, 0.94)
    forecasts["EWMA(0.94)"] = ewma94
    print(f"    EWMA(0.94)... done")

    # 3. EWMA(0.97)
    ewma97 = ewma_variance(ret, 0.97)
    forecasts["EWMA(0.97)"] = ewma97
    print(f"    EWMA(0.97)... done")

    # 4. Rolling 22d variance
    rv22 = rolling_variance_22d(ret)
    forecasts["RollVar22d"] = rv22
    print(f"    RollVar22d... done")

    # 5. VIX²/252 (SPY only)
    if cfg["has_vix"]:
        vix_var = vix_implied_variance(vix_close, ret.index)
        forecasts["VIX²/252"] = vix_var
        print(f"    VIX²/252... done")

    # 6. Parkinson range
    if asset_name in range_data:
        park_var = parkinson_variance(range_data[asset_name], ret.index)
        forecasts["Parkinson22d"] = park_var
        print(f"    Parkinson22d... done")

    # 7. Combined InvQLIKE (70% GJR + 30% EWMA97)
    comb = combined_invqlike(gjr_var, ewma97)
    forecasts["Combined70/30"] = comb
    print(f"    Combined70/30... done")

    # 8. Equal-weight ensemble (average of all available models except ensemble itself)
    available = [v for k, v in forecasts.items() if k != "EqualEnsemble"]
    ensemble = pd.DataFrame(available).mean(axis=0)
    ensemble.index = ret.index
    forecasts["EqualEnsemble"] = ensemble
    print(f"    EqualEnsemble ({len(available)} models)... done")

    all_forecasts[asset_name] = forecasts

# ============================================================
# 4. Compute Loss Functions (OOS only)
# ============================================================
print("\n" + "=" * 80)
print("[4/6] COMPUTING LOSS FUNCTIONS (OOS PERIOD)")
print("=" * 80)


def qlike_loss(sigma2, r2):
    """QLIKE loss: log(sigma2) + r2/sigma2. Lower is better."""
    mask = (sigma2 > 0) & (r2.notna()) & (sigma2.notna())
    s2 = sigma2[mask]
    rv = r2[mask]
    return np.log(s2) + rv / s2


def mse_loss(sigma2, r2):
    """MSE loss: (sigma2 - r2)^2. Lower is better."""
    mask = (sigma2 > 0) & (r2.notna()) & (sigma2.notna())
    s2 = sigma2[mask]
    rv = r2[mask]
    return (s2 - rv) ** 2


# Collect results
results_qlike = {}  # {asset: {model: mean_qlike}}
results_mse = {}
loss_series_qlike = {}  # {asset: {model: Series of daily losses}} for DM test

for asset_name in ASSETS:
    r2 = all_realized[asset_name]

    # Filter to OOS period
    oos_mask = (r2.index >= OOS_START) & (r2.index < OOS_END)
    r2_oos = r2[oos_mask]

    results_qlike[asset_name] = {}
    results_mse[asset_name] = {}
    loss_series_qlike[asset_name] = {}

    for model_name, forecast in all_forecasts[asset_name].items():
        f_oos = forecast[oos_mask]

        # Compute QLIKE
        ql = qlike_loss(f_oos, r2_oos)
        mean_ql = ql.mean()
        results_qlike[asset_name][model_name] = mean_ql

        # Compute MSE
        ml = mse_loss(f_oos, r2_oos)
        mean_ml = ml.mean()
        results_mse[asset_name][model_name] = mean_ml

        # Store daily loss series for DM test
        loss_series_qlike[asset_name][model_name] = ql

    n_oos = oos_mask.sum()
    print(f"  {asset_name}: {n_oos} OOS days, {len(all_forecasts[asset_name])} models evaluated")

# ============================================================
# Print QLIKE table
# ============================================================
print("\n" + "-" * 80)
print("QLIKE SCORES (lower is better)")
print("-" * 80)

# Build table
all_models_used = set()
for asset_name in ASSETS:
    all_models_used.update(all_forecasts[asset_name].keys())
all_models_ordered = [m for m in MODEL_NAMES if m in all_models_used]

header = f"{'Model':<18}"
for asset in ASSETS:
    header += f" | {asset:>10}"
header += " | {'Avg Rank':>10}"
print(header)
print("-" * len(header))

# Calculate ranks per asset
ranks_qlike = {}
for asset_name in ASSETS:
    scores = results_qlike[asset_name]
    sorted_models = sorted(scores.items(), key=lambda x: x[1])
    for rank, (model, _) in enumerate(sorted_models, 1):
        if model not in ranks_qlike:
            ranks_qlike[model] = {}
        ranks_qlike[model][asset_name] = rank

for model in all_models_ordered:
    row = f"{model:<18}"
    rank_values = []
    for asset in ASSETS:
        if model in results_qlike[asset]:
            score = results_qlike[asset][model]
            row += f" | {score:10.4f}"
            rank_values.append(ranks_qlike[model].get(asset, np.nan))
        else:
            row += f" | {'N/A':>10}"
    avg_rank = np.nanmean(rank_values) if rank_values else np.nan
    row += f" | {avg_rank:10.2f}"
    print(row)

# ============================================================
# Print MSE table
# ============================================================
print("\n" + "-" * 80)
print("MSE SCORES (lower is better, ×10^8)")
print("-" * 80)

ranks_mse = {}
for asset_name in ASSETS:
    scores = results_mse[asset_name]
    sorted_models = sorted(scores.items(), key=lambda x: x[1])
    for rank, (model, _) in enumerate(sorted_models, 1):
        if model not in ranks_mse:
            ranks_mse[model] = {}
        ranks_mse[model][asset_name] = rank

header = f"{'Model':<18}"
for asset in ASSETS:
    header += f" | {asset:>10}"
header += f" | {'Avg Rank':>10}"
print(header)
print("-" * len(header))

for model in all_models_ordered:
    row = f"{model:<18}"
    rank_values = []
    for asset in ASSETS:
        if model in results_mse[asset]:
            score = results_mse[asset][model] * 1e8
            row += f" | {score:10.4f}"
            rank_values.append(ranks_mse[model].get(asset, np.nan))
        else:
            row += f" | {'N/A':>10}"
    avg_rank = np.nanmean(rank_values) if rank_values else np.nan
    row += f" | {avg_rank:10.2f}"
    print(row)

# ============================================================
# Print Rank Summary
# ============================================================
print("\n" + "-" * 80)
print("RANK SUMMARY (QLIKE)")
print("-" * 80)

header = f"{'Model':<18}"
for asset in ASSETS:
    header += f" | {asset:>5}"
header += f" | {'Avg':>5} | {'Median':>6}"
print(header)
print("-" * len(header))

for model in all_models_ordered:
    row = f"{model:<18}"
    rank_values = []
    for asset in ASSETS:
        r = ranks_qlike.get(model, {}).get(asset, None)
        if r is not None:
            row += f" | {r:5d}"
            rank_values.append(r)
        else:
            row += f" | {'N/A':>5}"
    avg_r = np.nanmean(rank_values)
    med_r = np.nanmedian(rank_values)
    row += f" | {avg_r:5.2f} | {med_r:6.1f}"
    print(row)

# ============================================================
# 5. Pairwise Diebold-Mariano Tests
# ============================================================
print("\n" + "=" * 80)
print("[5/6] PAIRWISE DIEBOLD-MARIANO TESTS (QLIKE loss)")
print("=" * 80)


def dm_test(loss1, loss2, h=1):
    """
    Diebold-Mariano test.
    H0: E[d_t] = 0 where d_t = loss1_t - loss2_t
    Returns (t_stat, p_value_two_sided).
    Positive t_stat => model 1 has higher loss (worse).
    """
    # Align indices
    common = loss1.index.intersection(loss2.index)
    d = loss1.loc[common].values - loss2.loc[common].values
    d = d[~np.isnan(d)]
    n = len(d)
    if n < 30:
        return np.nan, np.nan

    d_bar = np.mean(d)

    # HAC variance (Newey-West with h-1 lags)
    gamma_0 = np.var(d, ddof=1)
    gamma_sum = 0
    for k in range(1, h):
        gamma_k = np.sum((d[k:] - d_bar) * (d[:-k] - d_bar)) / n
        gamma_sum += 2 * gamma_k
    var_d = (gamma_0 + gamma_sum) / n

    if var_d <= 0:
        return np.nan, np.nan

    t_stat = d_bar / np.sqrt(var_d)
    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return t_stat, p_value


# Run DM tests per asset
dm_results = {}
for asset_name in ASSETS:
    models_here = list(all_forecasts[asset_name].keys())
    dm_matrix = pd.DataFrame(np.nan, index=models_here, columns=models_here)
    pval_matrix = pd.DataFrame(np.nan, index=models_here, columns=models_here)

    for m1, m2 in itertools.combinations(models_here, 2):
        l1 = loss_series_qlike[asset_name][m1]
        l2 = loss_series_qlike[asset_name][m2]
        t_stat, p_val = dm_test(l1, l2)
        dm_matrix.loc[m1, m2] = t_stat
        dm_matrix.loc[m2, m1] = -t_stat
        pval_matrix.loc[m1, m2] = p_val
        pval_matrix.loc[m2, m1] = p_val

    dm_results[asset_name] = {"t_stat": dm_matrix, "p_value": pval_matrix}

    print(f"\n  --- {asset_name}: DM t-statistics (row - col, positive = row worse) ---")
    # Print compact version
    models_short = [m[:10] for m in models_here]
    header = f"{'':>12}"
    for ms in models_short:
        header += f" {ms:>10}"
    print(header)

    for i, m1 in enumerate(models_here):
        row = f"{models_short[i]:>12}"
        for j, m2 in enumerate(models_here):
            if i == j:
                row += f" {'---':>10}"
            else:
                t = dm_matrix.loc[m1, m2]
                if np.isnan(t):
                    row += f" {'N/A':>10}"
                else:
                    p = pval_matrix.loc[m1, m2]
                    sig = "***" if p < 0.01 else "**" if p < 0.05 else "*" if p < 0.10 else ""
                    row += f" {t:7.2f}{sig:>3}"
        print(row)

# Count significant wins per model across assets
print("\n" + "-" * 80)
print("DM TEST SUMMARY: Significant wins at p<0.05 (row beats column)")
print("-" * 80)

win_counts = {}
loss_counts = {}
for model in all_models_ordered:
    win_counts[model] = 0
    loss_counts[model] = 0

for asset_name in ASSETS:
    pval_matrix = dm_results[asset_name]["p_value"]
    tstat_matrix = dm_results[asset_name]["t_stat"]
    models_here = list(all_forecasts[asset_name].keys())

    for m1, m2 in itertools.combinations(models_here, 2):
        p = pval_matrix.loc[m1, m2]
        t = tstat_matrix.loc[m1, m2]
        if not np.isnan(p) and p < 0.05:
            if t > 0:
                # m1 worse, m2 wins
                win_counts[m2] = win_counts.get(m2, 0) + 1
                loss_counts[m1] = loss_counts.get(m1, 0) + 1
            else:
                # m1 wins
                win_counts[m1] = win_counts.get(m1, 0) + 1
                loss_counts[m2] = loss_counts.get(m2, 0) + 1

print(f"{'Model':<18} | {'Wins':>6} | {'Losses':>6} | {'Net':>6}")
print("-" * 50)
for model in all_models_ordered:
    w = win_counts.get(model, 0)
    l = loss_counts.get(model, 0)
    print(f"{model:<18} | {w:6d} | {l:6d} | {w-l:6d}")

# ============================================================
# 6. Model Confidence Set (MCS)
# ============================================================
print("\n" + "=" * 80)
print("[6/6] MODEL CONFIDENCE SET (Hansen et al. 2011, alpha=0.10)")
print("=" * 80)


def mcs_procedure(loss_dict, alpha=0.10, n_boot=5000):
    """
    Model Confidence Set using the range statistic T_R.
    loss_dict: {model_name: pd.Series of daily losses}
    Returns: list of models in the MCS, and p-values for each elimination.
    """
    models = list(loss_dict.keys())

    # Align all loss series to common index
    common_idx = loss_dict[models[0]].dropna().index
    for m in models[1:]:
        common_idx = common_idx.intersection(loss_dict[m].dropna().index)

    losses = pd.DataFrame({m: loss_dict[m].loc[common_idx] for m in models})
    n = len(losses)

    if n < 50:
        return models, {m: 1.0 for m in models}

    surviving = list(models)
    elimination_order = []
    p_values = {}

    while len(surviving) > 1:
        k = len(surviving)
        L = losses[surviving].values  # n x k

        # Compute pairwise loss differentials
        d_bar = np.zeros((k, k))
        for i in range(k):
            for j in range(k):
                if i != j:
                    d_bar[i, j] = np.mean(L[:, i] - L[:, j])

        # t-statistics for each pair (using bootstrap variance)
        d_all = np.zeros((n, k, k))
        for i in range(k):
            for j in range(k):
                d_all[:, i, j] = L[:, i] - L[:, j]

        # Bootstrap for variance
        t_stats = np.zeros((k, k))
        for i in range(k):
            for j in range(k):
                if i != j:
                    d_ij = d_all[:, i, j]
                    se = np.std(d_ij, ddof=1) / np.sqrt(n)
                    if se > 0:
                        t_stats[i, j] = d_bar[i, j] / se

        # Range statistic: T_R = max_i (max_j t_ij - min_j t_ij)
        # Simplified: use max absolute t_ij for each model
        model_max_t = np.zeros(k)
        for i in range(k):
            t_row = [t_stats[i, j] for j in range(k) if i != j]
            model_max_t[i] = np.max(t_row) if t_row else 0

        T_R_observed = np.max(model_max_t)

        # Bootstrap T_R under H0
        boot_T_R = np.zeros(n_boot)
        for b in range(n_boot):
            idx = np.random.randint(0, n, size=n)
            L_boot = L[idx, :]

            d_bar_boot = np.zeros((k, k))
            for i in range(k):
                for j in range(k):
                    if i != j:
                        d_ij_boot = L_boot[:, i] - L_boot[:, j]
                        d_bar_boot[i, j] = np.mean(d_ij_boot)

            # Recenter: d_bar_boot - d_bar (under H0 of equal performance)
            d_bar_centered = d_bar_boot - d_bar

            t_boot = np.zeros((k, k))
            for i in range(k):
                for j in range(k):
                    if i != j:
                        d_ij_boot = L_boot[:, i] - L_boot[:, j]
                        se = np.std(d_ij_boot, ddof=1) / np.sqrt(n)
                        if se > 0:
                            t_boot[i, j] = d_bar_centered[i, j] / se

            model_max_t_boot = np.zeros(k)
            for i in range(k):
                t_row = [t_boot[i, j] for j in range(k) if i != j]
                model_max_t_boot[i] = np.max(t_row) if t_row else 0
            boot_T_R[b] = np.max(model_max_t_boot)

        p_value = np.mean(boot_T_R >= T_R_observed)

        if p_value < alpha:
            # Eliminate the worst model (highest average loss)
            avg_losses = np.mean(L, axis=0)
            worst_idx = np.argmax(avg_losses)
            worst_model = surviving[worst_idx]
            p_values[worst_model] = p_value
            elimination_order.append(worst_model)
            surviving.pop(worst_idx)
        else:
            # Cannot reject H0: all remaining models are in MCS
            for m in surviving:
                p_values[m] = p_value
            break

    # If only 1 model left, it's in MCS by default
    if len(surviving) == 1 and surviving[0] not in p_values:
        p_values[surviving[0]] = 1.0

    return surviving, p_values, elimination_order


mcs_results = {}
for asset_name in ASSETS:
    print(f"\n  --- {asset_name} ---")
    loss_dict = loss_series_qlike[asset_name]

    surviving, p_values, elim_order = mcs_procedure(loss_dict, alpha=MCS_ALPHA, n_boot=N_BOOTSTRAP_MCS)

    mcs_results[asset_name] = {
        "surviving": surviving,
        "p_values": p_values,
        "elimination_order": elim_order,
    }

    print(f"    MCS survivors (alpha={MCS_ALPHA}): {surviving}")
    print(f"    Elimination order: {elim_order}")
    for m, p in sorted(p_values.items(), key=lambda x: x[1]):
        in_mcs = "IN MCS" if m in surviving else "ELIMINATED"
        print(f"      {m:<18}: p={p:.4f} [{in_mcs}]")

# ============================================================
# SUMMARY
# ============================================================
print("\n" + "=" * 80)
print("FINAL SUMMARY: THE DEFINITIVE VOL FORECASTING RANKING")
print("=" * 80)

# Count MCS membership across assets
mcs_membership = {}
for model in all_models_ordered:
    count = 0
    for asset_name in ASSETS:
        if model in mcs_results[asset_name]["surviving"]:
            count += 1
    mcs_membership[model] = count

# Overall ranking: average QLIKE rank + MCS membership
print(f"\n{'Model':<18} | {'QLIKE Rank':>10} | {'MSE Rank':>10} | {'MCS Count':>10} | {'DM Wins':>8} | {'DM Net':>7}")
print("-" * 80)

# Compute average QLIKE rank
avg_qlike_ranks = {}
avg_mse_ranks = {}
for model in all_models_ordered:
    qr = [ranks_qlike.get(model, {}).get(a, np.nan) for a in ASSETS]
    mr = [ranks_mse.get(model, {}).get(a, np.nan) for a in ASSETS]
    avg_qlike_ranks[model] = np.nanmean(qr)
    avg_mse_ranks[model] = np.nanmean(mr)

# Sort by average QLIKE rank
sorted_models = sorted(all_models_ordered, key=lambda m: avg_qlike_ranks.get(m, 99))

for model in sorted_models:
    qr = avg_qlike_ranks.get(model, np.nan)
    mr = avg_mse_ranks.get(model, np.nan)
    mc = mcs_membership.get(model, 0)
    w = win_counts.get(model, 0)
    net = w - loss_counts.get(model, 0)
    total_assets = sum(1 for a in ASSETS if model in all_forecasts[a])
    print(f"{model:<18} | {qr:10.2f} | {mr:10.2f} | {mc:5d}/{total_assets:<4d} | {w:8d} | {net:+7d}")

# Key finding
print("\n" + "-" * 80)
print("KEY FINDINGS:")
print("-" * 80)

best_qlike = sorted_models[0]
print(f"  1. Best avg QLIKE rank: {best_qlike} ({avg_qlike_ranks[best_qlike]:.2f})")

best_mcs = max(all_models_ordered, key=lambda m: mcs_membership[m])
print(f"  2. Most MCS memberships: {best_mcs} ({mcs_membership[best_mcs]}/{len(ASSETS)})")

best_dm = max(all_models_ordered, key=lambda m: win_counts.get(m, 0) - loss_counts.get(m, 0))
net_best = win_counts.get(best_dm, 0) - loss_counts.get(best_dm, 0)
print(f"  3. Best DM net record: {best_dm} (net {net_best:+d})")

# Is GJR really the best? Or just "not significantly worse"?
gjr_rank = avg_qlike_ranks.get("GJR-GARCH", np.nan)
gjr_mcs = mcs_membership.get("GJR-GARCH", 0)
print(f"\n  GJR-GARCH status: avg rank={gjr_rank:.2f}, MCS membership={gjr_mcs}/{len(ASSETS)}")

if gjr_mcs == len(ASSETS):
    print("  => GJR-GARCH is ALWAYS in the MCS (never significantly worse)")
elif gjr_mcs > len(ASSETS) / 2:
    print("  => GJR-GARCH is in MCS for majority of assets")
else:
    print("  => GJR-GARCH is NOT universally in MCS — simpler models may suffice")

# Check if any simple model matches GJR
for simple in ["EWMA(0.94)", "EWMA(0.97)", "RollVar22d"]:
    s_rank = avg_qlike_ranks.get(simple, np.nan)
    s_mcs = mcs_membership.get(simple, 0)
    if not np.isnan(s_rank) and s_rank <= gjr_rank + 0.5:
        print(f"  => {simple} is competitive: avg rank={s_rank:.2f}, MCS={s_mcs}/{len(ASSETS)}")

# ============================================================
# Save Results
# ============================================================
print("\n" + "=" * 80)
print("SAVING RESULTS")
print("=" * 80)

# Build serializable results
save_results = {
    "experiment": "K261",
    "title": "The Ultimate Vol Forecasting Contest",
    "timestamp": datetime.now().isoformat(),
    "config": {
        "assets": list(ASSETS.keys()),
        "oos_start": OOS_START,
        "oos_end": OOS_END,
        "window": WINDOW,
        "mcs_alpha": MCS_ALPHA,
        "n_bootstrap": N_BOOTSTRAP_MCS,
    },
    "qlike_scores": {
        asset: {model: float(score) for model, score in scores.items()}
        for asset, scores in results_qlike.items()
    },
    "mse_scores": {
        asset: {model: float(score) for model, score in scores.items()}
        for asset, scores in results_mse.items()
    },
    "qlike_ranks": {
        model: {asset: int(r) for asset, r in ranks.items()}
        for model, ranks in ranks_qlike.items()
    },
    "avg_qlike_rank": {model: float(avg_qlike_ranks[model]) for model in all_models_ordered},
    "avg_mse_rank": {model: float(avg_mse_ranks[model]) for model in all_models_ordered},
    "dm_test_summary": {
        model: {
            "wins": int(win_counts.get(model, 0)),
            "losses": int(loss_counts.get(model, 0)),
            "net": int(win_counts.get(model, 0) - loss_counts.get(model, 0)),
        }
        for model in all_models_ordered
    },
    "dm_pairwise": {},
    "mcs_results": {
        asset: {
            "surviving_models": data["surviving"],
            "elimination_order": data["elimination_order"],
            "p_values": {m: float(p) for m, p in data["p_values"].items()},
        }
        for asset, data in mcs_results.items()
    },
    "mcs_membership_count": {model: int(mcs_membership[model]) for model in all_models_ordered},
    "overall_ranking": [
        {
            "rank": i + 1,
            "model": m,
            "avg_qlike_rank": float(avg_qlike_ranks[m]),
            "avg_mse_rank": float(avg_mse_ranks[m]),
            "mcs_count": int(mcs_membership[m]),
            "dm_net": int(win_counts.get(m, 0) - loss_counts.get(m, 0)),
        }
        for i, m in enumerate(sorted_models)
    ],
    "key_findings": {
        "best_qlike": best_qlike,
        "best_mcs": best_mcs,
        "best_dm": best_dm,
        "gjr_avg_rank": float(gjr_rank) if not np.isnan(gjr_rank) else None,
        "gjr_mcs_count": int(gjr_mcs),
    },
}

# Add pairwise DM t-stats per asset
for asset_name in ASSETS:
    t_mat = dm_results[asset_name]["t_stat"]
    p_mat = dm_results[asset_name]["p_value"]
    save_results["dm_pairwise"][asset_name] = {
        "t_statistics": {
            m1: {m2: float(t_mat.loc[m1, m2]) if not np.isnan(t_mat.loc[m1, m2]) else None
                 for m2 in t_mat.columns if m1 != m2}
            for m1 in t_mat.index
        },
        "p_values": {
            m1: {m2: float(p_mat.loc[m1, m2]) if not np.isnan(p_mat.loc[m1, m2]) else None
                 for m2 in p_mat.columns if m1 != m2}
            for m1 in p_mat.index
        },
    }

import os
results_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "storage", "results")
os.makedirs(results_dir, exist_ok=True)
output_path = os.path.join(results_dir, "k261_vol_contest.json")

with open(output_path, "w") as f:
    json.dump(save_results, f, indent=2, ensure_ascii=False)

print(f"\n  Results saved to: {output_path}")

print("\n" + "=" * 80)
print("K261 EXPERIMENT COMPLETE")
print("=" * 80)
