"""
K189: Attention-Weighted Volatility (Cross-Asset Information Aggregation)
=========================================================================
[提出: 用戶, 修正重跑: Codex]

This rerun fixes four review blockers from 2026-06-11:
1. All forecasts are strictly past-only for date t.
2. Attention weights for date t use data no later than t-1.
3. Alpha is selected ex ante using a rolling 500-day training window.
4. DM test output includes Bonferroni and BH-FDR adjustments.
"""

import warnings

warnings.filterwarnings("ignore")

import json
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats

print("=" * 70)
print("K189: Attention-Weighted Volatility (Corrected Re-Run)")
print("=" * 70)

ASSETS = ["SPY", "QQQ", "GLD", "TLT", "EEM", "IWM"]
VIX_TICKER = "^VIX"
OOS_START = "2023-01-01"
OOS_END = "2025-01-01"
TRAIN_WINDOW = 500
ATTN_WINDOW = 252
RV_LAG = 1
RV_WINDOW = 22
EWMA_LAMBDA = 0.94
ALPHA_GRID = [0.3, 0.5, 0.7, 0.9]
MIN_DM_OBS = 60


def qlike_loss(forecast_var: pd.Series, realized_var: pd.Series) -> float:
    mask = (
        (forecast_var > 0)
        & (realized_var > 0)
        & ~forecast_var.isna()
        & ~realized_var.isna()
    )
    if mask.sum() == 0:
        return np.nan
    h = forecast_var[mask].to_numpy()
    rv_vals = realized_var[mask].to_numpy()
    return float(np.mean(np.log(h) + rv_vals / h))


def qlike_pointwise(forecast_var: pd.Series, realized_var: pd.Series) -> pd.Series:
    mask = (
        (forecast_var > 0)
        & (realized_var > 0)
        & ~forecast_var.isna()
        & ~realized_var.isna()
    )
    if mask.sum() == 0:
        return pd.Series(dtype=float)
    h = forecast_var[mask]
    rv_vals = realized_var[mask]
    return pd.Series(np.log(h) + rv_vals / h, index=h.index)


def dm_test_qlike(loss_model: pd.Series, loss_baseline: pd.Series) -> tuple[float, float, int]:
    d = (loss_model - loss_baseline).dropna()
    n = len(d)
    if n < MIN_DM_OBS:
        return np.nan, np.nan, n

    d_mean = d.mean()
    nw_lags = int(np.floor(n ** (1 / 3)))
    gamma0 = d.var(ddof=1)
    gamma_sum = 0.0

    for k in range(1, nw_lags + 1):
        gamma_k = d.iloc[k:].reset_index(drop=True).cov(
            d.iloc[:-k].reset_index(drop=True)
        )
        gamma_sum += 2 * (1 - k / (nw_lags + 1)) * gamma_k

    var_d = (gamma0 + gamma_sum) / n
    if not np.isfinite(var_d) or var_d <= 0:
        return np.nan, np.nan, n

    t_stat = d_mean / np.sqrt(var_d)
    p_val = 2 * stats.t.sf(abs(t_stat), df=n - 1)
    return float(t_stat), float(p_val), n


def adjust_pvalues(p_values: list[float]) -> tuple[list[float], list[float]]:
    valid = [(i, p) for i, p in enumerate(p_values) if np.isfinite(p)]
    bonf = [np.nan] * len(p_values)
    bh = [np.nan] * len(p_values)

    m = len(valid)
    if m == 0:
        return bonf, bh

    for i, p in valid:
        bonf[i] = min(p * m, 1.0)

    order = sorted(valid, key=lambda x: x[1])
    ranked = [0.0] * m
    running = 1.0
    for rank in range(m - 1, -1, -1):
        _, p = order[rank]
        adj = p * m / (rank + 1)
        running = min(running, adj)
        ranked[rank] = min(running, 1.0)

    for rank, (i, _) in enumerate(order):
        bh[i] = ranked[rank]

    return bonf, bh


def ewma_variance_forecast(ret_series: pd.Series, lam: float = EWMA_LAMBDA) -> pd.Series:
    values = ret_series.to_numpy()
    n = len(values)
    out = np.full(n, np.nan)
    if n < 2:
        return pd.Series(out, index=ret_series.index)

    out[1] = values[0] ** 2
    for i in range(2, n):
        out[i] = lam * out[i - 1] + (1 - lam) * values[i - 1] ** 2

    return pd.Series(out * 252, index=ret_series.index)


def compute_attention_weights(
    rv_df: pd.DataFrame, target_asset: str, other_assets: list[str], window: int = ATTN_WINDOW
) -> pd.DataFrame:
    """
    Weight for forecast date t uses only information available up to t-1.
    Each rolling correlation uses pairs (RV_j,s-1, RV_i,s) for s in [t-window, t-1].
    """
    n = len(rv_df)
    weight_series = {a: np.full(n, np.nan) for a in other_assets}
    rv_target = rv_df[target_asset].to_numpy()
    rv_others = {a: rv_df[a].to_numpy() for a in other_assets}

    for t in range(window + RV_LAG, n):
        target_hist = rv_target[t - window : t]
        corrs = {}
        for a in other_assets:
            other_hist = rv_others[a][t - window - RV_LAG : t - RV_LAG]
            if (
                len(target_hist) == len(other_hist)
                and np.std(target_hist) > 0
                and np.std(other_hist) > 0
            ):
                corr = np.corrcoef(other_hist, target_hist)[0, 1]
                corrs[a] = 0.0 if np.isnan(corr) else float(corr)
            else:
                corrs[a] = 0.0

        vals = np.array([corrs[a] for a in other_assets], dtype=float)
        vals = np.clip(vals, -5, 5)
        exp_vals = np.exp(vals - vals.max())
        softmax_vals = exp_vals / exp_vals.sum()

        for k, a in enumerate(other_assets):
            weight_series[a][t] = softmax_vals[k]

    return pd.DataFrame(weight_series, index=rv_df.index)


def attention_forecast_series(
    target: str, alpha: float, ewma_df: pd.DataFrame, attn_weights: dict[str, pd.DataFrame]
) -> pd.Series:
    others = [a for a in ASSETS if a != target]
    forecasts = []
    idx = []

    for t in ewma_df.index:
        own_ewma = ewma_df.loc[t, target]
        w = attn_weights[target].loc[t]
        if np.isnan(own_ewma) or w.isna().all():
            continue

        cross_signal = 0.0
        w_sum = 0.0
        for a in others:
            other_ewma = ewma_df.loc[t, a]
            if not np.isnan(w[a]) and not np.isnan(other_ewma):
                cross_signal += w[a] * other_ewma
                w_sum += w[a]

        if w_sum <= 0:
            continue

        cross_signal /= w_sum
        forecasts.append(alpha * own_ewma + (1 - alpha) * cross_signal)
        idx.append(t)

    return pd.Series(forecasts, index=idx, dtype=float)


print("\n[1] Loading data from yfinance ...")
t0 = time.time()

raw = {}
for ticker in ASSETS + [VIX_TICKER]:
    df_raw = yf.download(ticker, start="2005-01-01", end=OOS_END, progress=False)
    if isinstance(df_raw.columns, pd.MultiIndex):
        df_raw.columns = df_raw.columns.get_level_values(0)
    raw[ticker] = df_raw["Close"]

prices = pd.DataFrame({t: raw[t] for t in ASSETS})
prices["VIX"] = raw[VIX_TICKER]
prices = prices.dropna()

returns = np.log(prices[ASSETS] / prices[ASSETS].shift(1)).dropna()
vix = prices["VIX"].reindex(returns.index)
rv = returns.rolling(RV_WINDOW).var() * 252
rv = rv.dropna()

common_idx = rv.index.intersection(returns.index).intersection(vix.index)
returns = returns.loc[common_idx]
rv = rv.loc[common_idx]
vix = vix.loc[common_idx]
oos_dates = rv.index[(rv.index >= OOS_START) & (rv.index < OOS_END)]

print(
    f"  Observations: {len(rv)} | OOS: {len(oos_dates)} "
    f"({oos_dates[0].strftime('%Y-%m-%d')} to {oos_dates[-1].strftime('%Y-%m-%d')})"
)

print("\n[2] Computing past-only EWMA and rolling GJR forecasts ...")
ewma_df = pd.DataFrame({asset: ewma_variance_forecast(returns[asset]) for asset in ASSETS})

gjr_forecasts = {}
for asset in ASSETS:
    ret_full = returns[asset] * 100
    forecasts = []
    dates_out = []
    for t in oos_dates:
        t_loc = ret_full.index.get_loc(t)
        if t_loc < TRAIN_WINDOW:
            continue
        train = ret_full.iloc[t_loc - TRAIN_WINDOW : t_loc]
        try:
            model = arch_model(train, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Zero")
            res = model.fit(disp="off", show_warning=False)
            fcast = res.forecast(horizon=1)
            forecasts.append(float(fcast.variance.iloc[-1, 0] / 10000 * 252))
            dates_out.append(t)
        except Exception:
            forecasts.append(np.nan)
            dates_out.append(t)
    gjr_forecasts[asset] = pd.Series(forecasts, index=dates_out, dtype=float)
gjr_df = pd.DataFrame(gjr_forecasts)

print("\n[3] Computing lagged attention weights and alpha-specific forecasts ...")
attention_weights = {}
for target in ASSETS:
    others = [a for a in ASSETS if a != target]
    attention_weights[target] = compute_attention_weights(rv, target, others)

attn_raw = {}
for alpha in ALPHA_GRID:
    attn_raw[alpha] = {}
    for target in ASSETS:
        attn_raw[alpha][target] = attention_forecast_series(target, alpha, ewma_df, attention_weights)

print("\n[4] Rolling ex-ante alpha selection within 500-day training window ...")
selected_attn = {}
alpha_choice_records = []

for target in ASSETS:
    realized = rv[target]
    forecasts = []
    forecast_idx = []
    chosen_alphas = []

    for t in oos_dates:
        t_loc = realized.index.get_loc(t)
        if t_loc < TRAIN_WINDOW:
            continue

        train_idx = realized.index[t_loc - TRAIN_WINDOW : t_loc]
        alpha_losses = {}
        for alpha in ALPHA_GRID:
            train_forecast = attn_raw[alpha][target].reindex(train_idx)
            train_realized = realized.reindex(train_idx)
            alpha_losses[alpha] = qlike_loss(train_forecast, train_realized)

        valid = {a: q for a, q in alpha_losses.items() if np.isfinite(q)}
        if not valid:
            continue

        best_alpha = min(valid, key=valid.get)
        forecast_value = attn_raw[best_alpha][target].get(t, np.nan)
        if not np.isfinite(forecast_value):
            continue

        forecasts.append(float(forecast_value))
        forecast_idx.append(t)
        chosen_alphas.append(best_alpha)
        alpha_choice_records.append(
            {
                "asset": target,
                "date": t.strftime("%Y-%m-%d"),
                "selected_alpha": best_alpha,
                "training_window_start": train_idx[0].strftime("%Y-%m-%d"),
                "training_window_end": train_idx[-1].strftime("%Y-%m-%d"),
            }
        )

    selected_attn[target] = pd.Series(forecasts, index=forecast_idx, dtype=float)
    counts = pd.Series(chosen_alphas).value_counts().sort_index().to_dict() if chosen_alphas else {}
    print(f"  {target}: selected alpha counts {counts}")

print("\n[5] Evaluating corrected forecasts with QLIKE ...")
results_table = []
dm_records = []
raw_p_registry = []

for target in ASSETS:
    rv_oos = rv[target].reindex(oos_dates).dropna()
    ewma_oos = ewma_df[target].reindex(rv_oos.index)
    gjr_oos = gjr_df[target].reindex(rv_oos.index)
    attn_oos = selected_attn[target].reindex(rv_oos.index)

    ql_ewma = qlike_loss(ewma_oos, rv_oos)
    ql_gjr = qlike_loss(gjr_oos, rv_oos)
    ql_attn = qlike_loss(attn_oos, rv_oos)

    common = rv_oos.index.intersection(attn_oos.dropna().index)
    chosen_alphas = [
        rec["selected_alpha"] for rec in alpha_choice_records if rec["asset"] == target and rec["date"] in set(common.strftime("%Y-%m-%d"))
    ]
    mode_alpha = float(pd.Series(chosen_alphas).mode().iloc[0]) if chosen_alphas else np.nan

    results_table.append(
        {
            "asset": target,
            "oos_n": int(len(common)),
            "qlike_ewma": ql_ewma,
            "qlike_gjr": ql_gjr,
            "qlike_attn_selected": ql_attn,
            "modal_selected_alpha": mode_alpha,
            "pct_change_vs_ewma": (ql_attn - ql_ewma) / abs(ql_ewma) * 100 if np.isfinite(ql_ewma) and np.isfinite(ql_attn) else np.nan,
            "pct_change_vs_gjr": (ql_attn - ql_gjr) / abs(ql_gjr) * 100 if np.isfinite(ql_gjr) and np.isfinite(ql_attn) else np.nan,
        }
    )

    loss_attn = qlike_pointwise(attn_oos, rv_oos)
    loss_ewma = qlike_pointwise(ewma_oos, rv_oos)
    loss_gjr = qlike_pointwise(gjr_oos, rv_oos)

    t_ewma, p_ewma, n_ewma = dm_test_qlike(loss_attn, loss_ewma)
    t_gjr, p_gjr, n_gjr = dm_test_qlike(loss_attn, loss_gjr)

    dm_records.extend(
        [
            {
                "asset": target,
                "baseline": "EWMA",
                "dm_t": t_ewma,
                "dm_p_raw": p_ewma,
                "n_obs": n_ewma,
                "winner": "Attention" if np.isfinite(t_ewma) and t_ewma < 0 else "Baseline",
            },
            {
                "asset": target,
                "baseline": "GJR",
                "dm_t": t_gjr,
                "dm_p_raw": p_gjr,
                "n_obs": n_gjr,
                "winner": "Attention" if np.isfinite(t_gjr) and t_gjr < 0 else "Baseline",
            },
        ]
    )
    raw_p_registry.extend([p_ewma, p_gjr])

bonf, bh = adjust_pvalues(raw_p_registry)
for rec, bonf_p, bh_p in zip(dm_records, bonf, bh):
    rec["dm_p_bonferroni_12"] = bonf_p
    rec["dm_p_bh_fdr_12"] = bh_p
    rec["sig_raw_5pct"] = bool(np.isfinite(rec["dm_p_raw"]) and rec["dm_p_raw"] < 0.05)
    rec["sig_bonf_5pct"] = bool(np.isfinite(bonf_p) and bonf_p < 0.05)
    rec["sig_bh_5pct"] = bool(np.isfinite(bh_p) and bh_p < 0.05)

print("\n[6] Summary tables ...")
for row in results_table:
    print(
        f"  {row['asset']}: attn={row['qlike_attn_selected']:.4f}, "
        f"ewma={row['qlike_ewma']:.4f}, gjr={row['qlike_gjr']:.4f}, "
        f"modal_alpha={row['modal_selected_alpha']}"
    )

print("\n[7] Harvey threshold check ...")
harvey = []
for rec in dm_records:
    pass_harvey = bool(np.isfinite(rec["dm_t"]) and abs(rec["dm_t"]) > 3.0)
    harvey.append(
        {
            "asset": rec["asset"],
            "baseline": rec["baseline"],
            "abs_dm_t": abs(rec["dm_t"]) if np.isfinite(rec["dm_t"]) else np.nan,
            "pass_harvey_abs_t_gt_3": pass_harvey,
        }
    )

improvements = []
for row in results_table:
    improvements.append(
        {
            "asset": row["asset"],
            "qlike_ewma": round(row["qlike_ewma"], 6) if np.isfinite(row["qlike_ewma"]) else np.nan,
            "qlike_attn_selected": round(row["qlike_attn_selected"], 6) if np.isfinite(row["qlike_attn_selected"]) else np.nan,
            "pct_change_vs_ewma": round(row["pct_change_vs_ewma"], 4) if np.isfinite(row["pct_change_vs_ewma"]) else np.nan,
            "improved_vs_ewma": "YES" if row["qlike_attn_selected"] < row["qlike_ewma"] else "NO",
        }
    )

alpha_counts = {}
for asset in ASSETS:
    values = [rec["selected_alpha"] for rec in alpha_choice_records if rec["asset"] == asset]
    alpha_counts[asset] = {str(k): int(v) for k, v in pd.Series(values).value_counts().sort_index().to_dict().items()} if values else {}

summary = {
    "oos_start_effective": oos_dates[0].strftime("%Y-%m-%d"),
    "oos_end_effective": oos_dates[-1].strftime("%Y-%m-%d"),
    "oos_n_calendar_days": int(len(oos_dates)),
    "n_improved_vs_ewma": int(sum(r["improved_vs_ewma"] == "YES" for r in improvements)),
    "avg_pct_change_vs_ewma": float(np.nanmean([r["pct_change_vs_ewma"] for r in improvements])),
    "raw_sig_count_5pct": int(sum(rec["sig_raw_5pct"] for rec in dm_records)),
    "bonf_sig_count_5pct": int(sum(rec["sig_bonf_5pct"] for rec in dm_records)),
    "bh_sig_count_5pct": int(sum(rec["sig_bh_5pct"] for rec in dm_records)),
    "harvey_pass_count": int(sum(h["pass_harvey_abs_t_gt_3"] for h in harvey)),
}

elapsed = time.time() - t0
print(f"\nRuntime: {elapsed:.1f}s")

output = {
    "experiment": "K189",
    "title": "Attention-Weighted Volatility (Cross-Asset Information Aggregation) — corrected rerun",
    "attribution": "[提出: 用戶, 修正重跑: Codex]",
    "timestamp": datetime.now().isoformat(),
    "data_source": "yfinance daily (SPY/QQQ/GLD/TLT/EEM/IWM/^VIX)",
    "oos_period": f"{OOS_START} to {OOS_END}",
    "oos_effective_dates": {
        "start": oos_dates[0].strftime("%Y-%m-%d"),
        "end": oos_dates[-1].strftime("%Y-%m-%d"),
        "n_days": int(len(oos_dates)),
    },
    "train_window": TRAIN_WINDOW,
    "attention_window": ATTN_WINDOW,
    "rv_window": RV_WINDOW,
    "rv_lag": RV_LAG,
    "ewma_lambda": EWMA_LAMBDA,
    "alpha_grid": ALPHA_GRID,
    "method_changes": [
        "EWMA forecast for date t uses returns through t-1 only.",
        "Attention weights for date t use rolling correlations estimated with data through t-1 only.",
        "Alpha is chosen separately for each asset/date using the prior 500 trading days.",
        "DM tests report Bonferroni and BH-FDR corrections over the 12 asset-baseline comparisons.",
    ],
    "qlike_table": results_table,
    "dm_tests": dm_records,
    "harvey_checks": harvey,
    "improvements": improvements,
    "alpha_selection_counts": alpha_counts,
    "alpha_selection_history_head": alpha_choice_records[:30],
    "summary": summary,
    "runtime_seconds": round(elapsed, 1),
}

results_path = Path(__file__).resolve().parent / "k189_attention_vol_results.json"
with open(results_path, "w") as f:
    json.dump(output, f, indent=2, default=str)

print(f"Results saved to {results_path}")
