"""
K1546: Term-structure of variance risk premium (1M vs 3M vs 6M VRP slope)
Predicting SPY forward drawdown / left-tail.

Hypothesis: VRP slope (longer-horizon VRP minus shorter-horizon VRP) captures
the curvature of the "fear gauge" term structure. A flatter / inverted slope
(VRP_6M - VRP_1M shrinking or going negative) signals heightened near-term
tail risk and should predict larger forward drawdowns.

Differentiation from prior K:
- K429: VIX term structure slope (IV only) -> null. Here we test VRP-based slope.
- K430: Single-horizon VRP predictability of returns (OOS null). Here we predict
  forward DRAWDOWN (not return) using term-structure slope (not single VRP).
- K438/K450: Single-horizon VRP + GARCH/semivariance. We orthogonal — slope.

Methodology guardrails (per .claude/rules/experiments.md):
- Strict lookahead: signal at t uses data <= t-1; forward DD over [t+1, t+N].
- Newey-West HAC SE with lag = N (overlapping horizon).
- Block bootstrap CI with block=N, B=1000, seed=42.
- VRP in variance scale: VRP_h = IV_h^2 - RV_h^2 (Bollerslev/Tauchen/Zhou 2009).
- ROC AUC for tail event classification (max_dd_fwd <= -5%).
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy import stats

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)
OUT = Path(__file__).parent
TRADING_DAYS = 252


# ----------------------------- Data fetch --------------------------------- #
def fetch_data(start: str = "2008-01-01", end: str = "2026-06-24") -> pd.DataFrame:
    tickers = ["SPY", "^VIX", "^VIX3M", "^VIX6M"]
    raw = {}
    for t in tickers:
        try:
            df = yf.download(t, start=start, end=end, progress=False, auto_adjust=True)
            if df is None or len(df) == 0:
                print(f"WARN: {t} empty, trying ^VXV as fallback")
                continue
            # yfinance may return MultiIndex columns
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            raw[t] = df["Close"]
        except Exception as e:
            print(f"WARN: {t} fetch failed: {e}")
    # Fallback for VIX6M
    if "^VIX6M" not in raw:
        try:
            df = yf.download("^VXV", start=start, end=end, progress=False, auto_adjust=True)
            if df is not None and len(df) > 0:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                raw["^VXV"] = df["Close"]
                print("Using ^VXV as 3M alt; will skip VIX6M slope.")
        except Exception:
            pass
    data = pd.concat(raw, axis=1).dropna(how="all")
    data.columns = [c.replace("^", "") for c in data.columns]
    return data


# ----------------------------- VRP construction --------------------------- #
def build_vrp(df: pd.DataFrame) -> pd.DataFrame:
    """Construct VRP = IV^2 - RV^2 in variance scale (percent^2).
    IV from VIX (already annualized %).
    RV from rolling SPY return std * sqrt(252) (annualized %).
    """
    out = pd.DataFrame(index=df.index)
    spy_ret = np.log(df["SPY"]).diff()
    # Realized vol over lookback windows (NO lookahead — std uses past)
    for h, win in [("1M", 21), ("3M", 63), ("6M", 126)]:
        rv = spy_ret.rolling(win).std() * np.sqrt(TRADING_DAYS) * 100.0  # %
        out[f"RV_{h}"] = rv
    # IV
    if "VIX" in df.columns:
        out["IV_1M"] = df["VIX"]
    if "VIX3M" in df.columns:
        out["IV_3M"] = df["VIX3M"]
    if "VIX6M" in df.columns:
        out["IV_6M"] = df["VIX6M"]
    # VRP (variance scale = IV^2 - RV^2)
    for h in ["1M", "3M", "6M"]:
        if f"IV_{h}" in out.columns and f"RV_{h}" in out.columns:
            out[f"VRP_{h}"] = out[f"IV_{h}"] ** 2 - out[f"RV_{h}"] ** 2
    # Slopes
    if "VRP_3M" in out.columns and "VRP_1M" in out.columns:
        out["VRP_slope_3M_1M"] = out["VRP_3M"] - out["VRP_1M"]
    if "VRP_6M" in out.columns and "VRP_1M" in out.columns:
        out["VRP_slope_6M_1M"] = out["VRP_6M"] - out["VRP_1M"]
    # Naive IV slopes for benchmark (K429 redo)
    if "IV_3M" in out.columns:
        out["IV_slope_3M_1M"] = out["IV_3M"] - out["IV_1M"]
    if "IV_6M" in out.columns:
        out["IV_slope_6M_1M"] = out["IV_6M"] - out["IV_1M"]
    out["VIX_level"] = out.get("IV_1M")
    return out


# ----------------------------- Forward drawdown --------------------------- #
def forward_max_drawdown(spy: pd.Series, N: int) -> pd.Series:
    """Compute forward N-day max drawdown over [t+1, t+N] (strict).
    Returns most-negative cumulative return relative to running peak after t.
    """
    out = pd.Series(index=spy.index, dtype=float)
    prices = spy.values
    n = len(prices)
    for i in range(n):
        end = min(i + 1 + N, n)
        if end - (i + 1) < N // 2:  # need enough forward data
            continue
        future = prices[i + 1 : end]
        if len(future) == 0:
            continue
        running_peak = np.maximum.accumulate(future)
        dd = (future - running_peak) / running_peak
        out.iloc[i] = dd.min()
    return out


# ----------------------------- Newey-West HAC ----------------------------- #
def newey_west_se(x: np.ndarray, y: np.ndarray, lag: int) -> tuple[float, float, float]:
    """OLS slope of y ~ const + x; return (beta, t_stat, p_value) with NW HAC SE."""
    x = np.asarray(x)
    y = np.asarray(y)
    mask = ~(np.isnan(x) | np.isnan(y))
    x = x[mask]
    y = y[mask]
    n = len(x)
    if n < 50:
        return np.nan, np.nan, np.nan
    X = np.column_stack([np.ones(n), x])
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ X.T @ y
    resid = y - X @ beta
    # NW HAC
    S = (X * resid[:, None]).T @ (X * resid[:, None])
    for L in range(1, lag + 1):
        w = 1.0 - L / (lag + 1)
        Gamma = (X[L:] * resid[L:, None]).T @ (X[:-L] * resid[:-L, None])
        S = S + w * (Gamma + Gamma.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.diag(cov))
    t_stat = beta[1] / se[1]
    p_val = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return float(beta[1]), float(t_stat), float(p_val)


# ----------------------------- Block bootstrap CI ------------------------- #
def block_bootstrap_spearman(x: np.ndarray, y: np.ndarray, block: int, B: int = 1000, seed: int = 42):
    rng = np.random.default_rng(seed)
    mask = ~(np.isnan(x) | np.isnan(y))
    x = x[mask]
    y = y[mask]
    n = len(x)
    if n < 50:
        return np.nan, (np.nan, np.nan)
    rho_full = stats.spearmanr(x, y).statistic
    n_blocks = n // block + 1
    rhos = []
    for _ in range(B):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) for s in starts])[:n]
        try:
            rho_b = stats.spearmanr(x[idx], y[idx]).statistic
            rhos.append(rho_b)
        except Exception:
            continue
    rhos = np.array(rhos)
    lo, hi = np.percentile(rhos, [2.5, 97.5])
    return float(rho_full), (float(lo), float(hi))


# ----------------------------- Quantile portfolios ------------------------ #
def quantile_portfolio(signal: pd.Series, target: pd.Series, q: int = 5):
    df = pd.concat([signal, target], axis=1).dropna()
    df.columns = ["sig", "tgt"]
    df["bucket"] = pd.qcut(df["sig"], q=q, labels=False, duplicates="drop")
    grouped = df.groupby("bucket")["tgt"].agg(["mean", "std", "count"])
    # top vs bottom HAC t-test (approximate, since not time-aligned panel)
    bot = df[df["bucket"] == 0]["tgt"].values
    top = df[df["bucket"] == grouped.index.max()]["tgt"].values
    if len(bot) > 30 and len(top) > 30:
        # Welch t-test (independent samples; conservative)
        t_test = stats.ttest_ind(top, bot, equal_var=False)
        diff_t, diff_p = float(t_test.statistic), float(t_test.pvalue)
    else:
        diff_t, diff_p = np.nan, np.nan
    return grouped, (float(np.nanmean(top) - np.nanmean(bot)), diff_t, diff_p)


# ----------------------------- ROC AUC + DeLong CI ------------------------ #
def roc_auc_with_ci(signal: pd.Series, target: pd.Series, threshold: float = -0.05):
    df = pd.concat([signal, target], axis=1).dropna()
    df.columns = ["sig", "tgt"]
    y = (df["tgt"] <= threshold).astype(int).values
    s = df["sig"].values
    if y.sum() < 10 or (1 - y).sum() < 10:
        return np.nan, (np.nan, np.nan), int(y.sum())
    # AUC: lower slope predicts tail event -> use -signal for "higher score = more event"
    # We compute AUC for direction: hypothesis = lower VRP_slope -> more drawdown -> use -s
    score = -s
    # Mann-Whitney based AUC
    pos = score[y == 1]
    neg = score[y == 0]
    # AUC = P(score_pos > score_neg)
    u_stat, _ = stats.mannwhitneyu(pos, neg, alternative="greater")
    auc = u_stat / (len(pos) * len(neg))
    # Hanley-McNeil SE approximation
    q1 = auc / (2 - auc)
    q2 = 2 * auc**2 / (1 + auc)
    var = (auc * (1 - auc) + (len(pos) - 1) * (q1 - auc**2) + (len(neg) - 1) * (q2 - auc**2)) / (
        len(pos) * len(neg)
    )
    se = np.sqrt(max(var, 1e-12))
    lo = auc - 1.96 * se
    hi = auc + 1.96 * se
    return float(auc), (float(lo), float(hi)), int(y.sum())


# ----------------------------- Main pipeline ------------------------------ #
def run() -> dict:
    print("Fetching data...")
    raw = fetch_data()
    print(f"Raw data shape: {raw.shape}, columns: {list(raw.columns)}")
    print(f"Date range: {raw.index.min()} -> {raw.index.max()}")

    feat = build_vrp(raw)
    spy = raw["SPY"].dropna()

    # Forward drawdowns
    for N in [5, 21, 63]:
        feat[f"fwd_dd_{N}"] = forward_max_drawdown(spy, N)

    # STRICT lookahead defense: shift signal to use t-1 info for t -> [t+1, t+N]
    # Since fwd_dd uses [t+1, t+N], and VRP_slope_t uses data <= t (including IV_t and RV_t
    # which is past-looking std), we additionally shift signals by 1 day for safety.
    signal_cols = [c for c in feat.columns if c.startswith("VRP_slope") or c.startswith("IV_slope") or c == "VIX_level"]
    for c in signal_cols:
        feat[f"{c}_lag1"] = feat[c].shift(1)

    full_data = feat.dropna(subset=[c for c in feat.columns if c.endswith("_lag1")], how="all").copy()
    full_data.to_csv(OUT / "k1546_data.csv")
    print(f"Feature matrix shape: {full_data.shape}")

    results: dict = {
        "experiment_id": "K1546",
        "data": {
            "source": "yfinance",
            "tickers": list(raw.columns),
            "start": str(raw.index.min().date()),
            "end": str(raw.index.max().date()),
            "n_obs": int(len(raw)),
        },
        "tests": {},
    }

    horizons = [5, 21, 63]
    signals_to_test = []
    for s in ["VRP_slope_3M_1M_lag1", "VRP_slope_6M_1M_lag1", "IV_slope_3M_1M_lag1", "IV_slope_6M_1M_lag1", "VIX_level_lag1"]:
        if s in full_data.columns:
            signals_to_test.append(s)

    print(f"Signals to test: {signals_to_test}")

    # ============= Main tests per (signal, horizon) ============= #
    for sig in signals_to_test:
        results["tests"][sig] = {}
        for N in horizons:
            tgt = f"fwd_dd_{N}"
            sub = full_data[[sig, tgt]].dropna()
            if len(sub) < 100:
                results["tests"][sig][f"N{N}"] = {"error": "insufficient data"}
                continue
            x = sub[sig].values
            y = sub[tgt].values
            # Spearman
            rho_full, (lo, hi) = block_bootstrap_spearman(x, y, block=N, B=1000)
            # NW HAC OLS
            beta, t_nw, p_nw = newey_west_se(x, y, lag=N)
            # ROC AUC for tail event (only meaningful for N>=21)
            if N >= 21:
                auc, (auc_lo, auc_hi), n_pos = roc_auc_with_ci(sub[sig], sub[tgt], threshold=-0.05)
            else:
                auc, (auc_lo, auc_hi), n_pos = np.nan, (np.nan, np.nan), 0
            # Quantile portfolio
            grouped, (top_bot_diff, q_t, q_p) = quantile_portfolio(sub[sig], sub[tgt], q=5)
            results["tests"][sig][f"N{N}"] = {
                "n": int(len(sub)),
                "spearman_rho": rho_full,
                "spearman_ci95": [lo, hi],
                "nw_beta": beta,
                "nw_t_stat": t_nw,
                "nw_p_value": p_nw,
                "auc_tail_5pct": auc,
                "auc_ci95": [auc_lo, auc_hi],
                "n_tail_events": n_pos,
                "quantile_portfolio": {
                    "means": grouped["mean"].to_dict(),
                    "counts": grouped["count"].to_dict(),
                    "top_minus_bottom": top_bot_diff,
                    "t_stat": q_t,
                    "p_value": q_p,
                },
            }

    # ============= Subsample stability ============= #
    print("Subsample stability tests...")
    results["subsamples"] = {}
    splits = {
        "2010-2019": ("2010-01-01", "2019-12-31"),
        "2020-2026": ("2020-01-01", "2026-12-31"),
    }
    for name, (s, e) in splits.items():
        sub_data = full_data.loc[s:e]
        results["subsamples"][name] = {}
        for sig in signals_to_test:
            if "VRP_slope_6M" in sig:  # focus on headline signal
                key_sig = sig
                tgt = "fwd_dd_21"
                if sig not in sub_data.columns or tgt not in sub_data.columns:
                    continue
                ssub = sub_data[[sig, tgt]].dropna()
                if len(ssub) < 50:
                    continue
                beta, t_nw, p_nw = newey_west_se(ssub[sig].values, ssub[tgt].values, lag=21)
                rho_full, (lo, hi) = block_bootstrap_spearman(ssub[sig].values, ssub[tgt].values, block=21, B=500)
                results["subsamples"][name][sig] = {
                    "n": int(len(ssub)),
                    "spearman_rho": rho_full,
                    "spearman_ci95": [lo, hi],
                    "nw_t_stat": t_nw,
                    "nw_p_value": p_nw,
                }

    # ============= Encompassing test: VRP_slope vs VIX_level ============= #
    # Joint regression: fwd_dd_21 ~ const + VIX_level + VRP_slope_6M_1M (both lag1)
    print("Encompassing test...")
    if "VRP_slope_6M_1M_lag1" in full_data.columns:
        sig1 = "VIX_level_lag1"
        sig2 = "VRP_slope_6M_1M_lag1"
        tgt = "fwd_dd_21"
        sub = full_data[[sig1, sig2, tgt]].dropna()
        if len(sub) > 100:
            x = sub[[sig1, sig2]].values
            y = sub[tgt].values
            n = len(x)
            X = np.column_stack([np.ones(n), x])
            XtX_inv = np.linalg.inv(X.T @ X)
            beta = XtX_inv @ X.T @ y
            resid = y - X @ beta
            S = (X * resid[:, None]).T @ (X * resid[:, None])
            lag = 21
            for L in range(1, lag + 1):
                w = 1.0 - L / (lag + 1)
                Gamma = (X[L:] * resid[L:, None]).T @ (X[:-L] * resid[:-L, None])
                S = S + w * (Gamma + Gamma.T)
            cov = XtX_inv @ S @ XtX_inv
            se = np.sqrt(np.diag(cov))
            t_stats = beta / se
            results["encompassing_fwd_dd_21"] = {
                "betas": {"const": float(beta[0]), "VIX_level": float(beta[1]), "VRP_slope_6M_1M": float(beta[2])},
                "nw_t_stats": {"const": float(t_stats[0]), "VIX_level": float(t_stats[1]), "VRP_slope_6M_1M": float(t_stats[2])},
                "n": int(n),
            }

    # ============= VERDICT ============= #
    headline_sig = "VRP_slope_6M_1M_lag1" if "VRP_slope_6M_1M_lag1" in full_data.columns else "VRP_slope_3M_1M_lag1"
    headline_N = 21
    head = results["tests"].get(headline_sig, {}).get(f"N{headline_N}", {})
    head_t = abs(head.get("nw_t_stat", 0) or 0)
    head_auc = head.get("auc_tail_5pct", 0) or 0
    sub_sig_same_dir = True
    sub_sig_both = True
    if results.get("subsamples"):
        ts = []
        for name in results["subsamples"]:
            entry = results["subsamples"][name].get(headline_sig, {})
            t = entry.get("nw_t_stat")
            if t is None or np.isnan(t):
                sub_sig_both = False
                continue
            ts.append(t)
            if abs(t) < 2:
                sub_sig_both = False
        if len(ts) >= 2:
            sub_sig_same_dir = (np.sign(ts[0]) == np.sign(ts[1]))
    if head_t > 2 and head_auc > 0.6 and sub_sig_both and sub_sig_same_dir:
        verdict = "PASS"
    elif head_t > 2 and (not sub_sig_both or not sub_sig_same_dir):
        verdict = "MIXED"
    elif head_t < 2 or head_auc < 0.55:
        verdict = "NULL"
    else:
        verdict = "MIXED"
    results["verdict"] = verdict
    results["headline"] = {
        "signal": headline_sig,
        "horizon": headline_N,
        "nw_t_stat": head.get("nw_t_stat"),
        "auc": head_auc,
        "spearman_rho": head.get("spearman_rho"),
    }

    # ============= Save results ============= #
    with open(OUT / "k1546_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)

    # ============= Figures ============= #
    print("Generating figures...")
    plt.style.use("default")

    # Fig 1: VRP term structure time series
    fig, ax = plt.subplots(figsize=(11, 5))
    for col, color in [("VRP_1M", "tab:blue"), ("VRP_3M", "tab:orange"), ("VRP_6M", "tab:green")]:
        if col in full_data.columns:
            ax.plot(full_data.index, full_data[col], label=col, color=color, alpha=0.7, lw=0.9)
    ax.axhline(0, color="black", lw=0.5, linestyle="--")
    ax.set_title("K1546 Fig 1: VRP term structure (IV^2 - RV^2, variance scale)")
    ax.set_ylabel("VRP (%^2)")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "fig1_vrp_term_structure.png", dpi=120)
    plt.close()

    # Fig 2: VRP_slope vs forward max DD scatter
    fig, ax = plt.subplots(figsize=(8, 6))
    sig_col = headline_sig
    tgt_col = "fwd_dd_21"
    sub = full_data[[sig_col, tgt_col]].dropna()
    ax.scatter(sub[sig_col], sub[tgt_col], s=6, alpha=0.4, color="tab:purple")
    ax.set_xlabel(sig_col)
    ax.set_ylabel("Forward 21-day max drawdown")
    ax.set_title(f"K1546 Fig 2: {sig_col} vs fwd 21d max DD  (rho={head.get('spearman_rho', 'NA'):.3f}, t={head.get('nw_t_stat', 'NA'):.2f})")
    ax.axhline(-0.05, color="red", lw=0.7, linestyle="--", label="tail = -5%")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "fig2_scatter_slope_vs_dd.png", dpi=120)
    plt.close()

    # Fig 3: Quantile portfolio bar
    fig, ax = plt.subplots(figsize=(8, 5))
    qp = head.get("quantile_portfolio", {}).get("means", {})
    if qp:
        keys = sorted([int(k) for k in qp.keys()])
        vals = [qp[str(k)] if str(k) in qp else qp[k] for k in keys]
        labels = [f"Q{k+1}\n{'low' if k == keys[0] else 'high' if k == keys[-1] else ''}" for k in keys]
        bars = ax.bar(labels, vals, color="teal", edgecolor="black")
        for b, v in zip(bars, vals):
            ax.text(b.get_x() + b.get_width() / 2, v, f"{v:.3f}", ha="center", va="top" if v < 0 else "bottom", fontsize=9)
    ax.axhline(0, color="black", lw=0.5)
    ax.set_ylabel("Mean fwd 21-day max DD")
    ax.set_title(f"K1546 Fig 3: Quantile portfolio of {headline_sig}")
    ax.grid(alpha=0.3, axis="y")
    plt.tight_layout()
    plt.savefig(OUT / "fig3_quantile_portfolio.png", dpi=120)
    plt.close()

    # Fig 4: ROC curve
    fig, ax = plt.subplots(figsize=(7, 6))
    sub_roc = full_data[[headline_sig, "fwd_dd_21"]].dropna()
    if len(sub_roc) > 100:
        y_true = (sub_roc["fwd_dd_21"] <= -0.05).astype(int).values
        score = -sub_roc[headline_sig].values  # invert: lower slope -> higher score
        if y_true.sum() > 5 and (1 - y_true).sum() > 5:
            thresholds = np.unique(score)
            tpr = []
            fpr = []
            for t in thresholds[::max(1, len(thresholds) // 200)]:
                pred = (score >= t).astype(int)
                tp = ((pred == 1) & (y_true == 1)).sum()
                fn = ((pred == 0) & (y_true == 1)).sum()
                fp = ((pred == 1) & (y_true == 0)).sum()
                tn = ((pred == 0) & (y_true == 0)).sum()
                tpr.append(tp / (tp + fn) if (tp + fn) > 0 else 0)
                fpr.append(fp / (fp + tn) if (fp + tn) > 0 else 0)
            # sort
            order = np.argsort(fpr)
            ax.plot(np.array(fpr)[order], np.array(tpr)[order], color="tab:red", lw=1.5, label=f"AUC={head_auc:.3f}")
            ax.plot([0, 1], [0, 1], "k--", lw=0.7, label="random")
    ax.set_xlabel("False Positive Rate")
    ax.set_ylabel("True Positive Rate")
    ax.set_title(f"K1546 Fig 4: ROC for tail event (fwd 21d DD <= -5%) using {headline_sig}")
    ax.legend()
    ax.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(OUT / "fig4_roc.png", dpi=120)
    plt.close()

    print(f"Verdict: {verdict}")
    print(f"Headline: t={head.get('nw_t_stat')}, AUC={head_auc}, rho={head.get('spearman_rho')}")
    return results


if __name__ == "__main__":
    res = run()
    print(json.dumps(res.get("headline", {}), indent=2))
    print(f"VERDICT: {res['verdict']}")
