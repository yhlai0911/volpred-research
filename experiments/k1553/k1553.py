#!/usr/bin/env python3
"""K1553: Coherent VaR/ES estimator guardrail.

Forecast convention:
    estimate at index t uses returns[t-window:t] and is evaluated on return[t].

VT/DRP convention:
    raw leverage is generated from the risk forecast, then explicitly lagged via
    raw_leverage.shift(1) before multiplying by returns. This intentionally adds
    one extra day of operational delay and makes the no-lookahead policy visible
    in code.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1553"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

TICKERS = ["SPY", "QQQ", "IWM", "TLT", "HYG"]
DATA_START = "2007-01-01"
DATA_END = "2026-06-28"
WINDOW = 500
EWMA_LAMBDA = 0.97
ALPHAS = [0.01, 0.05]
TARGET_DAILY_ES = 0.01
TURNOVER_COST = 0.0005


@dataclass(frozen=True)
class RiskEstimate:
    var_loss: float
    es_loss: float
    invalid: bool = False


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, tuple):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        v = float(obj)
        return None if not math.isfinite(v) else v
    if isinstance(obj, (pd.Timestamp,)):
        return obj.date().isoformat()
    return obj


def download_prices() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=DATA_START,
        end=DATA_END,
        auto_adjust=True,
        progress=False,
        threads=False,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty data")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"].copy()
        elif "Close" in raw.columns.get_level_values(-1):
            close = raw.xs("Close", axis=1, level=-1).copy()
        else:
            raise RuntimeError(f"Cannot locate Close columns: {raw.columns}")
    else:
        close = raw[["Close"]].copy()
        close.columns = TICKERS[:1]
    close = close.reindex(columns=TICKERS).dropna(how="any")
    close.index = pd.to_datetime(close.index).tz_localize(None)
    if len(close) <= WINDOW + 252:
        raise RuntimeError(f"Insufficient data after alignment: n={len(close)}")
    close.to_csv(DATA_DIR / "adjusted_close.csv")
    return close


def build_returns(close: pd.DataFrame) -> pd.DataFrame:
    returns = close.pct_change().dropna(how="any")
    returns.to_csv(DATA_DIR / "daily_returns.csv")
    return returns


def _hist_estimate(losses: np.ndarray, alpha: float) -> RiskEstimate:
    losses = np.asarray(losses, dtype=float)
    var_loss = float(np.quantile(losses, 1.0 - alpha, method="higher"))
    tail = losses[losses >= var_loss]
    es_loss = float(np.mean(tail)) if len(tail) else var_loss
    return RiskEstimate(max(var_loss, 0.0), max(es_loss, 0.0))


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float:
    order = np.argsort(values)
    x = values[order]
    w = weights[order]
    cdf = np.cumsum(w) / np.sum(w)
    return float(x[min(np.searchsorted(cdf, q, side="left"), len(x) - 1)])


def _ewma_estimate(losses: np.ndarray, alpha: float) -> RiskEstimate:
    losses = np.asarray(losses, dtype=float)
    n = len(losses)
    # Oldest observation gets the smallest weight, most recent the largest.
    weights = (1.0 - EWMA_LAMBDA) * EWMA_LAMBDA ** np.arange(n - 1, -1, -1)
    weights = weights / np.sum(weights)
    var_loss = _weighted_quantile(losses, weights, 1.0 - alpha)
    mask = losses >= var_loss
    if not np.any(mask):
        es_loss = var_loss
    else:
        es_loss = float(np.sum(weights[mask] * losses[mask]) / np.sum(weights[mask]))
    return RiskEstimate(max(var_loss, 0.0), max(es_loss, 0.0))


def _cornish_fisher_quantile(z: np.ndarray, skew: float, ex_kurt: float) -> np.ndarray:
    return (
        z
        + (z**2 - 1.0) * skew / 6.0
        + (z**3 - 3.0 * z) * ex_kurt / 24.0
        - (2.0 * z**3 - 5.0 * z) * (skew**2) / 36.0
    )


def _cornish_fisher_estimate(losses: np.ndarray, alpha: float) -> RiskEstimate:
    # Estimate the left tail of returns, then report positive loss capital.
    returns = -np.asarray(losses, dtype=float)
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=1))
    if sigma <= 1e-12 or not np.isfinite(sigma):
        return _hist_estimate(losses, alpha)
    skew = float(stats.skew(returns, bias=False))
    ex_kurt = float(stats.kurtosis(returns, fisher=True, bias=False))
    skew = float(np.clip(skew, -5.0, 5.0))
    ex_kurt = float(np.clip(ex_kurt, -5.0, 25.0))

    z_alpha = stats.norm.ppf(alpha)
    z_cf = float(_cornish_fisher_quantile(np.array([z_alpha]), skew, ex_kurt)[0])
    var_return = mu + sigma * z_cf

    grid = np.linspace(max(alpha / 500.0, 1e-5), alpha, 500)
    z_grid = stats.norm.ppf(grid)
    cf_grid = _cornish_fisher_quantile(z_grid, skew, ex_kurt)
    es_return = float(np.mean(mu + sigma * cf_grid))

    var_loss = -var_return
    es_loss = -es_return
    invalid = bool(var_loss < 0 or es_loss < 0 or es_loss + 1e-12 < var_loss)
    # Capital systems cannot use negative risk. Clipping is deliberately tracked
    # as invalid because it can break estimator coherence.
    var_loss = max(float(var_loss), 0.0)
    es_loss = max(float(es_loss), var_loss, 0.0)
    return RiskEstimate(var_loss, es_loss, invalid=invalid)


def _spectral_l_estimate(losses: np.ndarray, alpha: float) -> RiskEstimate:
    losses = np.sort(np.asarray(losses, dtype=float))
    n = len(losses)
    k = max(1, int(math.ceil(alpha * n)))
    tail = losses[-k:]
    weights = np.linspace(1.0, 2.0, k)
    weights = weights / weights.sum()
    var_loss = float(tail[0])
    es_loss = float(np.sum(weights * tail))
    return RiskEstimate(max(var_loss, 0.0), max(es_loss, 0.0))


METHODS = {
    "hist": _hist_estimate,
    "ewma": _ewma_estimate,
    "cornish_fisher": _cornish_fisher_estimate,
    "spectral_l": _spectral_l_estimate,
}


def estimate_risk_series(returns: pd.Series, alpha: float) -> dict[str, pd.DataFrame]:
    out: dict[str, list[dict[str, Any]]] = {m: [] for m in METHODS}
    idx = returns.index
    values = returns.to_numpy(dtype=float)
    for t in range(WINDOW, len(values)):
        window_returns = values[t - WINDOW : t]
        losses = -window_returns
        for method, fn in METHODS.items():
            est = fn(losses, alpha)
            out[method].append(
                {
                    "date": idx[t],
                    "var_loss": est.var_loss,
                    "es_loss": est.es_loss,
                    "invalid": est.invalid,
                }
            )
    frames = {}
    for method, rows in out.items():
        df = pd.DataFrame(rows).set_index("date")
        frames[method] = df
    return frames


def kupiec_test(violations: np.ndarray, alpha: float) -> dict[str, Any]:
    v = np.asarray(violations, dtype=int)
    n = len(v)
    n1 = int(v.sum())
    n0 = n - n1
    if n == 0:
        return {"stat": None, "p_value": None, "pass": False}
    phat = n1 / n
    if n1 == 0 or n1 == n:
        # Boundary is not a perfect pass; exact binomial p-value is more honest.
        p_val = float(stats.binomtest(n1, n, alpha).pvalue)
        return {"stat": None, "p_value": p_val, "pass": p_val > 0.05}
    lr = -2.0 * (
        n1 * np.log(alpha)
        + n0 * np.log(1.0 - alpha)
        - n1 * np.log(phat)
        - n0 * np.log(1.0 - phat)
    )
    return {"stat": float(lr), "p_value": float(1 - stats.chi2.cdf(lr, 1)), "pass": bool(1 - stats.chi2.cdf(lr, 1) > 0.05)}


def christoffersen_test(violations: np.ndarray) -> dict[str, Any]:
    v = np.asarray(violations, dtype=int)
    if len(v) < 2:
        return {"stat": None, "p_value": None, "pass": False, "computed": False}
    t00 = int(np.sum((v[:-1] == 0) & (v[1:] == 0)))
    t01 = int(np.sum((v[:-1] == 0) & (v[1:] == 1)))
    t10 = int(np.sum((v[:-1] == 1) & (v[1:] == 0)))
    t11 = int(np.sum((v[:-1] == 1) & (v[1:] == 1)))
    pi01 = t01 / (t00 + t01) if (t00 + t01) else 0.0
    pi11 = t11 / (t10 + t11) if (t10 + t11) else 0.0
    pi = (t01 + t11) / (t00 + t01 + t10 + t11)
    if min(pi01, pi11, pi) <= 0.0 or max(pi01, pi11, pi) >= 1.0:
        return {
            "stat": None,
            "p_value": None,
            "pass": False,
            "computed": False,
            "warning": "boundary transition probabilities; not counted as pass",
            "transitions": {"t00": t00, "t01": t01, "t10": t10, "t11": t11},
        }
    ll_ind = (t00 + t10) * np.log(1 - pi) + (t01 + t11) * np.log(pi)
    ll_dep = t00 * np.log(1 - pi01) + t01 * np.log(pi01) + t10 * np.log(1 - pi11) + t11 * np.log(pi11)
    lr = -2.0 * (ll_ind - ll_dep)
    p_val = float(1 - stats.chi2.cdf(lr, 1))
    return {
        "stat": float(lr),
        "p_value": p_val,
        "pass": bool(p_val > 0.05),
        "computed": True,
        "transitions": {"t00": t00, "t01": t01, "t10": t10, "t11": t11},
    }


def basel_traffic_light(violations: np.ndarray) -> dict[str, Any]:
    v = np.asarray(violations, dtype=int)
    last = v[-250:] if len(v) >= 250 else v
    count = int(last.sum())
    if count <= 4:
        color = "green"
    elif count <= 9:
        color = "yellow"
    else:
        color = "red"
    return {"color": color, "violations_250d": count, "pass": color == "green"}


def acerbi_szekely_z1(returns: np.ndarray, var_loss: np.ndarray, es_loss: np.ndarray, alpha: float) -> dict[str, Any]:
    r = np.asarray(returns, dtype=float)
    var_series = -np.asarray(var_loss, dtype=float)
    es_series = -np.asarray(es_loss, dtype=float)
    violations = r < var_series
    n = len(r)
    if not np.any(violations):
        return {"z1": None, "z_stat": None, "p_value": None, "pass": False, "n_violations": 0, "warning": "no violations"}
    z1 = 0.0
    for i in range(n):
        if violations[i] and abs(es_series[i]) > 1e-12:
            z1 += r[i] / es_series[i]
    z1 = z1 / n / alpha + 1.0
    se = 1.0 / np.sqrt(n * alpha)
    z_stat = z1 / se
    p_val = float(2 * (1 - stats.norm.cdf(abs(z_stat))))
    return {
        "z1": float(z1),
        "z_stat": float(z_stat),
        "p_value": p_val,
        "pass": bool(p_val > 0.05),
        "n_violations": int(violations.sum()),
    }


def backtest_asset(returns: pd.Series, forecasts: dict[str, pd.DataFrame], alpha: float) -> dict[str, Any]:
    result = {}
    for method, f in forecasts.items():
        aligned_returns = returns.reindex(f.index).to_numpy(dtype=float)
        var_loss = f["var_loss"].to_numpy(dtype=float)
        es_loss = f["es_loss"].to_numpy(dtype=float)
        violations = aligned_returns < -var_loss
        kup = kupiec_test(violations, alpha)
        cc = christoffersen_test(violations)
        basel = basel_traffic_light(violations)
        es = acerbi_szekely_z1(aligned_returns, var_loss, es_loss, alpha)
        result[method] = {
            "n": int(len(aligned_returns)),
            "violation_rate": float(np.mean(violations)),
            "n_violations": int(np.sum(violations)),
            "mean_var_loss": float(np.mean(var_loss)),
            "mean_es_loss": float(np.mean(es_loss)),
            "invalid_forecasts": int(f["invalid"].sum()),
            "kupiec": kup,
            "christoffersen": cc,
            "basel": basel,
            "trinity_pass": bool(kup["pass"] and cc["pass"] and basel["pass"]),
            "es_z1": es,
        }
    return result


def coherence_diagnostics(returns: pd.DataFrame, alpha: float) -> dict[str, Any]:
    pairs = []
    values = returns.to_numpy(dtype=float)
    dates = returns.index
    for i, a in enumerate(TICKERS):
        for j in range(i + 1, len(TICKERS)):
            b = TICKERS[j]
            pair_ret = 0.5 * values[:, i] + 0.5 * values[:, j]
            rows = {m: [] for m in METHODS}
            for t in range(WINDOW, len(values)):
                la = -values[t - WINDOW : t, i]
                lb = -values[t - WINDOW : t, j]
                lp = -pair_ret[t - WINDOW : t]
                for method, fn in METHODS.items():
                    ra = fn(la, alpha).es_loss
                    rb = fn(lb, alpha).es_loss
                    rp = fn(lp, alpha).es_loss
                    rhs = 0.5 * ra + 0.5 * rb
                    rows[method].append(
                        {
                            "date": dates[t],
                            "lhs_pair_es": rp,
                            "rhs_weighted_component_es": rhs,
                            "gap": rp - rhs,
                            "violation": rp > rhs + 1e-12,
                        }
                    )
            for method, method_rows in rows.items():
                df = pd.DataFrame(method_rows)
                violation_count = int(df["violation"].sum())
                max_gap = float(df["gap"].max())
                p95_gap = float(df["gap"].quantile(0.95))
                pairs.append(
                    {
                        "pair": f"{a}_{b}",
                        "method": method,
                        "n": int(len(df)),
                        "violation_count": violation_count,
                        "violation_rate": float(violation_count / len(df)),
                        "max_gap": max_gap,
                        "p95_gap": p95_gap,
                    }
                )
    summary = {}
    for method in METHODS:
        subset = [p for p in pairs if p["method"] == method]
        summary[method] = {
            "pairs": len(subset),
            "total_tests": int(sum(p["n"] for p in subset)),
            "total_violations": int(sum(p["violation_count"] for p in subset)),
            "violation_rate": float(sum(p["violation_count"] for p in subset) / sum(p["n"] for p in subset)),
            "worst_pair": max(subset, key=lambda x: x["violation_rate"])["pair"],
            "max_gap": float(max(p["max_gap"] for p in subset)),
        }
    return {"summary": summary, "pairs": pairs}


def capital_ranking(returns: pd.DataFrame, all_forecasts: dict[str, dict[str, dict[str, pd.DataFrame]]]) -> dict[str, Any]:
    realized = {}
    oos_returns = returns.iloc[WINDOW:]
    for ticker in TICKERS:
        losses = -oos_returns[ticker].to_numpy(dtype=float)
        realized[ticker] = _hist_estimate(losses, 0.05).es_loss
    realized_order = sorted(realized, key=realized.get, reverse=True)
    result: dict[str, Any] = {
        "realized_oos_es_5pct": realized,
        "realized_order_high_to_low": realized_order,
        "methods": {},
    }
    realized_rank = pd.Series(realized).rank(ascending=False)
    for method in METHODS:
        avg_capital = {}
        for ticker in TICKERS:
            f = all_forecasts[ticker][0.05][method]
            avg_capital[ticker] = float(f["es_loss"].mean())
        method_rank = pd.Series(avg_capital).rank(ascending=False)
        rho = float(method_rank.corr(realized_rank, method="spearman"))
        order = sorted(avg_capital, key=avg_capital.get, reverse=True)
        inversions = 0
        for i, a in enumerate(TICKERS):
            for b in TICKERS[i + 1 :]:
                if (method_rank[a] - method_rank[b]) * (realized_rank[a] - realized_rank[b]) < 0:
                    inversions += 1
        result["methods"][method] = {
            "avg_es_5pct": avg_capital,
            "order_high_to_low": order,
            "spearman_vs_realized": rho,
            "pairwise_rank_inversions_vs_realized": int(inversions),
            "top_risk_matches_realized": bool(order[0] == realized_order[0]),
        }
    return result


def de_risking_triggers(portfolio_returns: pd.Series, forecasts: dict[str, pd.DataFrame]) -> dict[str, Any]:
    result = {}
    returns_oos = portfolio_returns.iloc[WINDOW:]
    for method, f in forecasts.items():
        es = f["es_loss"].replace(0, np.nan)
        raw_leverage = (TARGET_DAILY_ES / es).clip(lower=0.0, upper=2.0)
        raw_leverage = raw_leverage.reindex(returns_oos.index).ffill()
        # Required no-lookahead guard: signal from t-1, return at t.
        applied_leverage = raw_leverage.shift(1).fillna(1.0)
        turnover = applied_leverage.diff().abs().fillna(0.0)
        net_returns = applied_leverage * returns_oos - TURNOVER_COST * turnover
        result[method] = {
            "raw_deleverage_trigger_days_lt_0_75": int((raw_leverage < 0.75).sum()),
            "raw_big_cut_days_delta_lt_minus_0_25": int((raw_leverage.diff() < -0.25).sum()),
            "applied_low_exposure_days_lt_0_75": int((applied_leverage < 0.75).sum()),
            "mean_raw_leverage": float(raw_leverage.mean()),
            "mean_applied_leverage": float(applied_leverage.mean()),
            "annual_turnover": float(turnover.mean() * 252),
            "net_ann_return": float(net_returns.mean() * 252),
            "net_ann_vol": float(net_returns.std(ddof=1) * np.sqrt(252)),
            "net_sharpe": float((net_returns.mean() * 252) / (net_returns.std(ddof=1) * np.sqrt(252))),
            "max_drawdown": float((1.0 + net_returns).cumprod().div((1.0 + net_returns).cumprod().cummax()).sub(1.0).min()),
        }
    return result


def plot_capital_rank(capital: dict[str, Any]) -> None:
    methods = list(METHODS)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    realized = pd.Series(capital["realized_oos_es_5pct"]).sort_values(ascending=False)
    axes[0].bar(realized.index, realized.values * 100, color="#334155")
    axes[0].set_title("Realized OOS 5% ES by asset")
    axes[0].set_ylabel("Daily loss (%)")
    width = 0.18
    x = np.arange(len(TICKERS))
    for k, method in enumerate(methods):
        vals = pd.Series(capital["methods"][method]["avg_es_5pct"]).reindex(TICKERS)
        axes[1].bar(x + (k - 1.5) * width, vals.values * 100, width=width, label=method)
    axes[1].set_xticks(x)
    axes[1].set_xticklabels(TICKERS)
    axes[1].set_title("Average forecast 5% ES capital")
    axes[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(ROOT / "k1553_capital_rank.png", dpi=160)
    plt.close(fig)


def verdict_from_results(coherence: dict[str, Any], capital: dict[str, Any], triggers: dict[str, Any]) -> dict[str, Any]:
    violation_rates = {method: row["violation_rate"] for method, row in coherence["summary"].items()}
    worst_method = max(violation_rates, key=violation_rates.get)
    worst_vrate = violation_rates[worst_method]
    cf_vrate = coherence["summary"]["cornish_fisher"]["violation_rate"]
    spectral_vrate = coherence["summary"]["spectral_l"]["violation_rate"]
    max_trigger = max(v["raw_deleverage_trigger_days_lt_0_75"] for v in triggers.values())
    min_trigger = min(v["raw_deleverage_trigger_days_lt_0_75"] for v in triggers.values())
    trigger_spread = max_trigger - min_trigger
    cf_rank_inv = capital["methods"]["cornish_fisher"]["pairwise_rank_inversions_vs_realized"]
    if worst_vrate > spectral_vrate + 0.001 and (worst_vrate > 0.0 or cf_rank_inv > 0 or trigger_spread >= 20):
        label = "PASS"
        conclusion = (
            "Estimator choice materially changes coherence diagnostics, capital ranking, "
            f"or de-risking triggers; {worst_method} has the largest observed subadditivity failure rate."
        )
    elif trigger_spread >= 10 or cf_rank_inv > 0:
        label = "CONDITIONAL_PASS"
        conclusion = "Estimator choice matters, but evidence is concentrated in ranking/trigger drift rather than broad subadditivity failures."
    else:
        label = "NULL"
        conclusion = "Estimator choice did not materially change the tested guardrail outcomes."
    return {
        "label": label,
        "conclusion": conclusion,
        "subadditivity_violation_rates": violation_rates,
        "worst_subadditivity_method": worst_method,
        "cornish_fisher_subadditivity_violation_rate": cf_vrate,
        "spectral_l_subadditivity_violation_rate": spectral_vrate,
        "deleveraging_trigger_spread_days": int(trigger_spread),
        "cornish_fisher_rank_inversions_vs_realized": int(cf_rank_inv),
    }


def main() -> None:
    warnings.filterwarnings("ignore", category=RuntimeWarning)
    close = download_prices()
    returns = build_returns(close)
    portfolio_returns = returns[TICKERS].mean(axis=1)

    all_forecasts: dict[str, dict[float, dict[str, pd.DataFrame]]] = {}
    backtests: dict[str, Any] = {}
    for ticker in TICKERS:
        all_forecasts[ticker] = {}
        backtests[ticker] = {}
        for alpha in ALPHAS:
            forecasts = estimate_risk_series(returns[ticker], alpha)
            all_forecasts[ticker][alpha] = forecasts
            backtests[ticker][str(alpha)] = backtest_asset(returns[ticker], forecasts, alpha)

    portfolio_forecasts_5 = estimate_risk_series(portfolio_returns, 0.05)
    portfolio_backtest_5 = backtest_asset(portfolio_returns, portfolio_forecasts_5, 0.05)
    coherence = coherence_diagnostics(returns[TICKERS], 0.05)
    capital = capital_ranking(returns[TICKERS], all_forecasts)
    triggers = de_risking_triggers(portfolio_returns, portfolio_forecasts_5)
    plot_capital_rank(capital)
    verdict = verdict_from_results(coherence, capital, triggers)

    results = {
        "experiment_id": EXPERIMENT_ID,
        "seed": SEED,
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "data": {
            "source": "yfinance adjusted close",
            "tickers": TICKERS,
            "requested_start": DATA_START,
            "requested_end": DATA_END,
            "actual_start": close.index[0].date().isoformat(),
            "actual_end": close.index[-1].date().isoformat(),
            "n_price_rows": int(len(close)),
            "n_return_rows": int(len(returns)),
            "rolling_window": WINDOW,
            "oos_rows": int(len(returns) - WINDOW),
        },
        "methods": {
            "hist": "Unweighted historical simulation VaR and tail-mean ES.",
            "ewma": f"Calendar-weighted historical VaR/ES, lambda={EWMA_LAMBDA}.",
            "cornish_fisher": "Moment-adjusted Cornish-Fisher VaR with numerical CF ES.",
            "spectral_l": "Monotone tail-weight L-estimator over worst alpha losses.",
        },
        "backtests": backtests,
        "portfolio_backtest_5pct": portfolio_backtest_5,
        "coherence_subadditivity_5pct_es": coherence,
        "capital_ranking_5pct_es": capital,
        "de_risking_triggers_portfolio_5pct_es": triggers,
        "verdict": verdict,
        "limitations": [
            "Daily ETF close-to-close returns only; no intraday liquidity or execution model.",
            "Cornish-Fisher ES is numerically approximated from the CF-transformed normal tail.",
            "Subadditivity is tested on equal-weight two-asset portfolios, not every possible weight vector.",
            "yfinance vendor snapshots can drift; CSV snapshots are stored for this run.",
        ],
        "literature": [
            {
                "key": "Aichele_Cialenco_Jelito_Pitera_2026",
                "title": "Coherent Estimation of Risk Measures",
                "venue": "Journal of Financial Econometrics",
                "doi": "10.1093/jjfinec/nbag012",
            },
            {"key": "Artzner_Delbaen_Eber_Heath_1999", "title": "Coherent Measures of Risk"},
            {"key": "Acerbi_Szekely_2014", "title": "Backtesting Expected Shortfall"},
            {"key": "Fissler_Ziegel_2016", "title": "Expected Shortfall is jointly elicitable with Value at Risk"},
        ],
    }
    (ROOT / "k1553_results.json").write_text(
        json.dumps(_json_safe(results), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(_json_safe({"verdict": verdict, "data": results["data"]}), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
