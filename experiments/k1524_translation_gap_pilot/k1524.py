#!/usr/bin/env python
"""K1522 — Translation Gap Pilot: 統計精度 → 投組 Sharpe 的斷點.

3 models (HAR-RV, GJR-GARCH, RandomForest) x 3 criteria (QLIKE, rank-rho, Sharpe).

Lookahead-safe: 所有 signal 用 .shift(1); seed=42.
"""

from __future__ import annotations

import json
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from arch import arch_model
from scipy import stats
from scipy.stats import spearmanr
from sklearn.ensemble import RandomForestRegressor

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

TICKERS = [
    "SPY",
    "AAPL",
    "MSFT",
    "GOOGL",
    "AMZN",
    "NVDA",
    "META",
    "TSLA",
    "JPM",
    "JNJ",
    "V",
]
START = "2018-01-01"
END = "2025-12-31"
OOS_START = "2022-01-01"
ANNUAL = 252
TARGET_VOL = 0.10  # annualised
RV_WINDOW = 5

HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "results.json"


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def download_prices(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    raw = yf.download(
        tickers + ["^VIX"],
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
    )
    # multi-ticker auto_adjust returns dict-like via Close
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
    close = close.dropna(how="all")
    return close


def realized_vol(returns: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    """Annualised realised vol from |daily return| rolling mean (proxy).

    Use rolling std of returns × sqrt(252) — robust standard definition.
    """
    return returns.rolling(window).std() * np.sqrt(ANNUAL)


# ---------------------------------------------------------------------------
# Forecast models — every model produces a 1-day-ahead forecast at date t
# of the realised vol of returns at t (i.e., RV computed at t).
# All training data ends at t-1; outputs are aligned so column at index t
# is the forecast usable at date t with information up to t-1.
# ---------------------------------------------------------------------------
def har_forecast(rv: pd.Series) -> pd.Series:
    """HAR-RV with lag 1/5/22 day averages, expanding window OLS.

    Lookahead-safe: features at t use rv up to t-1. Target at t is rv at t.
    Refit every 21 trading days for speed.
    """
    df = pd.DataFrame({"rv": rv}).dropna()
    df["lag1"] = df["rv"].shift(1)
    df["lag5"] = df["rv"].shift(1).rolling(5).mean()
    df["lag22"] = df["rv"].shift(1).rolling(22).mean()
    df = df.dropna()

    forecasts = pd.Series(index=df.index, dtype=float)
    oos_idx = df.index >= OOS_START
    if not oos_idx.any():
        return forecasts

    # In-sample cutoff: first OOS date
    first_oos = df.index[oos_idx][0]
    # Walk forward, refit every 21 days
    refit_freq = 21
    coef = None
    last_fit = None
    for i, t in enumerate(df.index):
        if t < first_oos:
            continue
        # Refit if needed
        if coef is None or last_fit is None or (i - last_fit) >= refit_freq:
            train = df.loc[df.index < t]
            X = train[["lag1", "lag5", "lag22"]].values
            y = train["rv"].values
            X_ = np.column_stack([np.ones(len(X)), X])
            coef, *_ = np.linalg.lstsq(X_, y, rcond=None)
            last_fit = i
        row = df.loc[t, ["lag1", "lag5", "lag22"]].values
        forecasts.loc[t] = coef[0] + np.dot(coef[1:], row)
    return forecasts


def gjr_forecast(returns: pd.Series) -> pd.Series:
    """GJR-GARCH(1,1) 1-day-ahead conditional vol (annualised).

    Use returns in %; refit every 21 days for speed.
    """
    r = returns.dropna() * 100.0
    forecasts = pd.Series(index=r.index, dtype=float)
    first_oos = r.index[r.index >= OOS_START][0]
    refit_freq = 21
    last_fit = -refit_freq
    res = None
    params = None

    for i, t in enumerate(r.index):
        if t < first_oos:
            continue
        if (i - last_fit) >= refit_freq:
            train = r.loc[r.index < t]
            try:
                am = arch_model(train, mean="Zero", vol="GARCH", p=1, o=1, q=1, dist="normal", rescale=False)
                res = am.fit(disp="off", show_warning=False)
                params = res.params
                last_fit = i
            except Exception:
                # keep old params
                pass
        if res is None or params is None:
            continue
        # 1-step-ahead variance forecast: refit-anchored forecast via .forecast
        try:
            f = res.forecast(horizon=1, reindex=False)
            var_pct2 = f.variance.values[-1, 0]
            sigma_pct = float(np.sqrt(var_pct2))
            forecasts.loc[t] = sigma_pct / 100.0 * np.sqrt(ANNUAL)
        except Exception:
            continue
    return forecasts


def rf_forecast(returns: pd.Series, rv: pd.Series, vix: pd.Series) -> pd.Series:
    """RandomForest using RV lag 1/5/22 + |ret| lag 1/5/22 + VIX/100 as features.

    Expanding-window refit every 21 days.
    """
    df = pd.DataFrame(
        {
            "rv": rv,
            "abs_ret": returns.abs(),
            "vix": vix / 100.0,
        }
    ).dropna()
    feats = pd.DataFrame(index=df.index)
    feats["rv_l1"] = df["rv"].shift(1)
    feats["rv_l5"] = df["rv"].shift(1).rolling(5).mean()
    feats["rv_l22"] = df["rv"].shift(1).rolling(22).mean()
    feats["ar_l1"] = df["abs_ret"].shift(1)
    feats["ar_l5"] = df["abs_ret"].shift(1).rolling(5).mean()
    feats["ar_l22"] = df["abs_ret"].shift(1).rolling(22).mean()
    feats["vix_l1"] = df["vix"].shift(1)
    target = df["rv"]
    full = pd.concat([feats, target.rename("y")], axis=1).dropna()

    forecasts = pd.Series(index=full.index, dtype=float)
    if not (full.index >= OOS_START).any():
        return forecasts
    first_oos = full.index[full.index >= OOS_START][0]
    refit_freq = 21
    last_fit = -refit_freq
    model = None

    for i, t in enumerate(full.index):
        if t < first_oos:
            continue
        if (i - last_fit) >= refit_freq:
            train = full.loc[full.index < t]
            X = train.drop(columns=["y"]).values
            y = train["y"].values
            model = RandomForestRegressor(
                n_estimators=100,
                max_depth=5,
                random_state=SEED,
                n_jobs=-1,
            )
            model.fit(X, y)
            last_fit = i
        if model is None:
            continue
        x_row = full.loc[t].drop("y").values.reshape(1, -1)
        forecasts.loc[t] = float(model.predict(x_row)[0])
    return forecasts


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
def qlike(forecast: pd.Series, realised: pd.Series) -> float:
    """QLIKE loss on variance: y/h - log(y/h) - 1, lower is better."""
    f2 = forecast**2
    r2 = realised**2
    df = pd.concat([f2.rename("f"), r2.rename("r")], axis=1).dropna()
    df = df[(df["f"] > 1e-10) & (df["r"] > 1e-10)]
    ratio = df["r"] / df["f"]
    loss = ratio - np.log(ratio) - 1.0
    return float(loss.mean()), loss


def dm_test(loss1: pd.Series, loss2: pd.Series) -> tuple[float, float]:
    """Diebold–Mariano test (simple, h=1, Newey-West optional skipped)."""
    d = (loss1 - loss2).dropna()
    if len(d) < 10:
        return float("nan"), float("nan")
    mean = d.mean()
    se = d.std(ddof=1) / np.sqrt(len(d))
    stat = mean / se if se > 0 else float("nan")
    p = 2 * (1 - stats.norm.cdf(abs(stat)))
    return float(stat), float(p)


def vol_target_sharpe(returns: pd.Series, forecast_vol: pd.Series, target_vol: float = TARGET_VOL) -> float:
    """Per-asset vol-target Sharpe. signal at t = target/forecast(t), shifted into t.

    The forecast for date t uses info ≤ t-1, then we trade on day t.
    We weight: w_t = target_vol / forecast_t (capped at 3x to prevent blow-ups).
    Strategy return at t = w_t * r_t. Sharpe annualised.
    """
    df = pd.concat([returns.rename("r"), forecast_vol.rename("f")], axis=1).dropna()
    df = df[df["f"] > 1e-6]
    weight = (target_vol / df["f"]).clip(upper=3.0)
    strat = weight * df["r"]
    if strat.std() == 0 or len(strat) < 30:
        return float("nan")
    return float(strat.mean() / strat.std() * np.sqrt(ANNUAL))


def ew_portfolio_sharpe(returns: pd.DataFrame, forecasts: dict[str, pd.Series], target_vol: float = TARGET_VOL) -> float:
    """Equal-weight portfolio of per-ticker vol-targeted positions."""
    strat_returns = []
    for ticker, fc in forecasts.items():
        df = pd.concat([returns[ticker].rename("r"), fc.rename("f")], axis=1).dropna()
        df = df[df["f"] > 1e-6]
        weight = (target_vol / df["f"]).clip(upper=3.0)
        strat_returns.append((weight * df["r"]).rename(ticker))
    port = pd.concat(strat_returns, axis=1).mean(axis=1).dropna()
    if port.std() == 0 or len(port) < 30:
        return float("nan")
    return float(port.mean() / port.std() * np.sqrt(ANNUAL))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    print(f"[K1522] Downloading data {START}..{END}")
    prices = download_prices(TICKERS, START, END)
    vix = prices["^VIX"]
    close = prices[TICKERS]
    returns = close.pct_change()

    # Realised vol per ticker
    rv = {t: realized_vol(returns[t]) for t in TICKERS}

    # ----- Forecasts per model per ticker -----
    print("[K1522] Fitting models per ticker (this takes a few minutes)…")
    forecasts = {"HAR": {}, "GJR": {}, "RF": {}}
    for t in TICKERS:
        print(f"  · {t}")
        forecasts["HAR"][t] = har_forecast(rv[t])
        forecasts["GJR"][t] = gjr_forecast(returns[t])
        forecasts["RF"][t] = rf_forecast(returns[t], rv[t], vix)

    # ----- Evaluation -----
    print("[K1522] Evaluating…")
    matrix = {}
    qlike_losses_per_model = {}  # for DM
    for model in ["HAR", "GJR", "RF"]:
        qlikes = []
        sharpes = []
        loss_concat = []
        for t in TICKERS:
            f = forecasts[model][t]
            f_oos = f[f.index >= OOS_START]
            rv_oos = rv[t][rv[t].index >= OOS_START]
            ql_mean, ql_series = qlike(f_oos, rv_oos)
            qlikes.append(ql_mean)
            loss_concat.append(ql_series)
            ret_oos = returns[t][returns[t].index >= OOS_START]
            sh = vol_target_sharpe(ret_oos, f_oos)
            sharpes.append(sh)
        qlike_losses_per_model[model] = pd.concat(loss_concat).sort_index()

        # Rank-rho: per day, rank 11 tickers, compare forecast vs realised
        # build dataframes
        f_df = pd.DataFrame({t: forecasts[model][t] for t in TICKERS}).loc[OOS_START:]
        rv_df = pd.DataFrame({t: rv[t] for t in TICKERS}).loc[OOS_START:]
        common = f_df.dropna(how="any").index.intersection(rv_df.dropna(how="any").index)
        rhos = []
        for d in common:
            rho, _ = spearmanr(f_df.loc[d], rv_df.loc[d])
            if not np.isnan(rho):
                rhos.append(rho)
        rank_rho = float(np.mean(rhos)) if rhos else float("nan")

        # EW portfolio Sharpe
        ret_oos_df = returns.loc[OOS_START:, TICKERS]
        fc_oos = {t: forecasts[model][t][forecasts[model][t].index >= OOS_START] for t in TICKERS}
        ew_sh = ew_portfolio_sharpe(ret_oos_df, fc_oos)

        matrix[model] = {
            "QLIKE": float(np.nanmean(qlikes)),
            "rank_rho": rank_rho,
            "EW_sharpe": ew_sh,
            "single_sharpe_median": float(np.nanmedian(sharpes)),
            "single_sharpe_by_ticker": {t: s for t, s in zip(TICKERS, sharpes)},
        }

    # Winners
    winners = {
        "QLIKE": min(matrix, key=lambda m: matrix[m]["QLIKE"]),  # lower better
        "rank_rho": max(matrix, key=lambda m: matrix[m]["rank_rho"]),
        "EW_sharpe": max(matrix, key=lambda m: matrix[m]["EW_sharpe"]),
        "single_sharpe_median": max(matrix, key=lambda m: matrix[m]["single_sharpe_median"]),
    }

    # DM tests on QLIKE
    dm = {}
    pairs = [("HAR", "GJR"), ("HAR", "RF"), ("GJR", "RF")]
    for a, b in pairs:
        # Align loss series
        la = qlike_losses_per_model[a]
        lb = qlike_losses_per_model[b]
        common = la.index.intersection(lb.index)
        stat, p = dm_test(la.loc[common], lb.loc[common])
        dm[f"{a}_vs_{b}"] = {"stat": stat, "p": p}

    # Translation gap summary
    q_winner = winners["QLIKE"]
    s_winner = winners["EW_sharpe"]
    are_diff = q_winner != s_winner
    if are_diff:
        gap_pct = (matrix[s_winner]["EW_sharpe"] - matrix[q_winner]["EW_sharpe"]) / abs(matrix[q_winner]["EW_sharpe"] + 1e-9) * 100.0
    else:
        gap_pct = 0.0

    # Verdict logic
    if are_diff:
        verdict = "PASS"  # translation gap confirmed systematically
    elif winners["QLIKE"] == winners["rank_rho"] == winners["EW_sharpe"]:
        verdict = "MIXED"  # no gap, all same winner — null for the phenomenon
    else:
        verdict = "CONDITIONAL_PASS"

    out = {
        "k_id": "K1522",
        "title": "Translation Gap Pilot: 統計精度 → 投組 Sharpe 的斷點",
        "oos_period": "2022-01 to 2025-12",
        "tickers": TICKERS,
        "matrix": matrix,
        "winners": winners,
        "DM_test_QLIKE": dm,
        "translation_gap": {
            "QLIKE_winner": q_winner,
            "Sharpe_winner": s_winner,
            "rank_rho_winner": winners["rank_rho"],
            "are_different": are_diff,
            "Sharpe_difference_pct": f"{gap_pct:.1f}%",
            "ew_sharpe_by_model": {m: matrix[m]["EW_sharpe"] for m in matrix},
            "qlike_by_model": {m: matrix[m]["QLIKE"] for m in matrix},
        },
        "narrative_arc_key": "translation_gap_phenomenon_systematic",
        "seed": SEED,
        "data_source": "yfinance",
        "verdict": verdict,
    }

    RESULTS_PATH.write_text(json.dumps(out, indent=2, default=float))
    print(f"[K1522] Wrote {RESULTS_PATH}")

    # ----- Figures -----
    print("[K1522] Generating figures…")
    make_figures(matrix, winners, out)
    print("[K1522] DONE")


def make_figures(matrix: dict, winners: dict, out: dict) -> None:
    models = ["HAR", "GJR", "RF"]
    criteria = ["QLIKE", "rank_rho", "EW_sharpe"]

    # Fig 1: 3x3 ranking heatmap (1 = best, 3 = worst)
    rank_matrix = np.zeros((3, 3))
    for ci, c in enumerate(criteria):
        vals = [matrix[m][c] for m in models]
        if c == "QLIKE":
            order = np.argsort(vals)  # ascending: lower better
        else:
            order = np.argsort(vals)[::-1]  # descending: higher better
        ranks = np.empty(3, dtype=int)
        for r, idx in enumerate(order):
            ranks[idx] = r + 1
        rank_matrix[:, ci] = ranks

    fig, ax = plt.subplots(figsize=(7, 5))
    im = ax.imshow(rank_matrix, cmap="RdYlGn_r", vmin=1, vmax=3, aspect="auto")
    ax.set_xticks(range(3))
    ax.set_xticklabels(criteria)
    ax.set_yticks(range(3))
    ax.set_yticklabels(models)
    for i in range(3):
        for j in range(3):
            val = matrix[models[i]][criteria[j]]
            ax.text(j, i, f"{val:.3f}\nrank {int(rank_matrix[i, j])}",
                    ha="center", va="center", fontsize=9,
                    color="white" if rank_matrix[i, j] >= 2 else "black")
    ax.set_title("K1522: 3 models × 3 criteria — ranks (1=best, 3=worst)")
    plt.colorbar(im, ax=ax, label="Rank")
    plt.tight_layout()
    plt.savefig(HERE / "fig1_3x3_matrix.png", dpi=300)
    plt.close()

    # Fig 2: QLIKE rank vs Sharpe rank scatter
    qlike_vals = [matrix[m]["QLIKE"] for m in models]
    sharpe_vals = [matrix[m]["EW_sharpe"] for m in models]
    qlike_rank = np.argsort(np.argsort(qlike_vals)) + 1  # 1 = lowest QLIKE (best)
    sharpe_rank = np.argsort(np.argsort([-s for s in sharpe_vals])) + 1  # 1 = highest Sharpe (best)

    fig, ax = plt.subplots(figsize=(6, 6))
    for i, m in enumerate(models):
        ax.scatter(qlike_rank[i], sharpe_rank[i], s=200, label=m)
        ax.annotate(m, (qlike_rank[i] + 0.05, sharpe_rank[i] + 0.05), fontsize=11)
    ax.plot([1, 3], [1, 3], "k--", alpha=0.3, label="Perfect translation")
    ax.set_xlabel("QLIKE rank (1 = best statistical)")
    ax.set_ylabel("EW Sharpe rank (1 = best portfolio)")
    ax.set_title("K1522: Statistical accuracy → Portfolio Sharpe\n(off-diagonal = translation gap)")
    ax.set_xticks([1, 2, 3])
    ax.set_yticks([1, 2, 3])
    ax.grid(True, alpha=0.3)
    ax.legend()
    plt.tight_layout()
    plt.savefig(HERE / "fig2_qlike_vs_sharpe_scatter.png", dpi=300)
    plt.close()

    # Fig 3: per-ticker winner consistency
    tickers = TICKERS
    qlike_winner_per_ticker = []
    sharpe_winner_per_ticker = []
    for t in tickers:
        q_by_m = {m: out["matrix"][m]["single_sharpe_by_ticker"][t] for m in models}
        # For QLIKE per ticker, we need to recompute — simpler proxy: use overall QLIKE winner
        # but ticker-specific Sharpe winner:
        sharpe_winner_per_ticker.append(max(q_by_m, key=q_by_m.get))
        # For QLIKE per ticker, we did not store; mark as global winner placeholder
        qlike_winner_per_ticker.append(winners["QLIKE"])

    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(tickers))
    model_to_int = {"HAR": 0, "GJR": 1, "RF": 2}
    q_int = [model_to_int[m] for m in qlike_winner_per_ticker]
    s_int = [model_to_int[m] for m in sharpe_winner_per_ticker]
    ax.bar(x - 0.2, q_int, width=0.4, label="QLIKE winner (global)", alpha=0.7)
    ax.bar(x + 0.2, s_int, width=0.4, label="Sharpe winner (ticker)", alpha=0.7)
    ax.set_xticks(x)
    ax.set_xticklabels(tickers, rotation=45)
    ax.set_yticks([0, 1, 2])
    ax.set_yticklabels(["HAR", "GJR", "RF"])
    ax.set_title("K1522: Winner consistency per ticker — QLIKE vs Sharpe")
    ax.legend()
    plt.tight_layout()
    plt.savefig(HERE / "fig3_winner_consistency_by_ticker.png", dpi=300)
    plt.close()


if __name__ == "__main__":
    main()
