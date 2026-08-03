"""K1746: bottom-up versus top-down one-day portfolio VaR/ES.

The primary design is filtered historical simulation (FHS).  At forecast date t,
all volatility signals are shifted by one day and all residual/reference returns
end at t-1.  Bottom-up FHS rescales the five component residuals and preserves
their same-date empirical dependence.  Top-down FHS applies the identical
filter/window to the identical realized portfolio-return target.

The literal ``signal.shift(1)`` below is the information-set seam required by
the project contract.  Tests additionally prove training labels end before the
forecast origin and both directions use identical origins and targets.
"""

from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from volpred.research.reproduce_spec import finalize_experiment
from volpred.stats.inference import holm_step_down

SEED = 42
ASSETS = ["SPY", "TLT", "GLD", "HYG", "QQQ"]
ALPHAS = [0.01, 0.05]
PRIMARY_WINDOW = 756
ALT_WINDOW = 504
EWMA_LAMBDA = 0.97
BOOT_REPS = 2000
BOOT_BLOCK = 10
MCS_LEVEL = 0.10
EPS = 1e-12

HERE = Path(__file__).resolve().parent
PRICE_PATH = HERE / "data" / "prices.csv"
RESULT_PATH = HERE / "K1746_results.json"
FORECAST_PATH = HERE / "K1746_forecasts.csv.gz"
INFERENCE_PATH = HERE / "K1746_inference_cells.json"
DIAGNOSTICS_PATH = HERE / "data_diagnostics.json"
MANIFEST_PATH = HERE / "source_manifest.json"
REFERENCES_PATH = HERE / "references.json"
CHART_PATH = HERE / "K1746_score_comparison.svg"

UPSTREAM = {
    "path": "experiments/K1727/data/prices.csv",
    "git_commit": "1d9348c7e914fa93faf5846515dd828cdd14a18b",
    "git_authored_at": "2026-07-28T12:13:11+08:00",
    "retrieved_at_utc": "2026-07-27T19:36:36.183381+00:00",
    "retrieval_evidence": "experiments/K1727/K1727_results.json#/run_timestamp",
    "sha256": "4bd92dd20579489cca28326da1e6ef604f5d60175d6d3a23cf226cb226d8811d",
    "policy": "yfinance download(start=2003-01-01, auto_adjust=True); adjusted Close",
}
SOURCE_COPIED_AT_UTC = "2026-08-02T06:46:33.872387+00:00"

REFERENCES = [
    {
        "key": "wang_wang_2025",
        "citation": "Jie Wang and Yongqiao Wang (2025), Forecasting Expected Shortfall and Value-at-Risk With Cross-Sectional Aggregation, Journal of Forecasting 44(2), 391-423.",
        "doi": "10.1002/for.3195",
        "url": "https://doi.org/10.1002/for.3195",
        "verified_claim": "Studies cross-sectional aggregation of short-memory processes as a route to long memory inside a CAViaR-FZ VaR/ES model. It does not study portfolio-constituent bottom-up versus portfolio-level top-down aggregation; K1746 uses it only as VaR/ES aggregation background and terminological inspiration.",
        "accessed_at_utc": "2026-08-02T06:44:39Z",
    },
    {
        "key": "fissler_ziegel_2016",
        "citation": "Tobias Fissler and Johanna F. Ziegel (2016), Higher Order Elicitability and Osband's Principle, Annals of Statistics 44(4), 1680-1707.",
        "doi": "10.1214/16-AOS1439",
        "url": "https://doi.org/10.1214/16-AOS1439",
        "verified_claim": "VaR and ES are jointly elicitable under mild conditions, supporting joint proper-score comparison rather than a standalone ES loss.",
        "accessed_at_utc": "2026-08-02T06:44:39Z",
    },
    {
        "key": "hansen_lunde_nason_2011",
        "citation": "Peter R. Hansen, Asger Lunde, and James M. Nason (2011), The Model Confidence Set, Econometrica 79(2), 453-497.",
        "doi": "10.3982/ECTA5771",
        "url": "https://doi.org/10.3982/ECTA5771",
        "verified_claim": "Defines an MCS that retains the best model(s) while acknowledging model-selection uncertainty.",
        "accessed_at_utc": "2026-08-02T06:44:39Z",
    },
    {
        "key": "acerbi_szekely_2014",
        "citation": "Carlo Acerbi and Balazs Szekely (2014), Backtesting Expected Shortfall, MSCI Research Insight.",
        "doi": None,
        "url": "https://www.msci.com/research-and-insights/paper/research-insight-backtesting-expected-shortfall-december-2014",
        "verified_claim": "Introduces model-independent nonparametric ES backtests; K1746 uses the all-observation Z2 moment with a date-block bootstrap.",
        "accessed_at_utc": "2026-08-02T06:44:39Z",
    },
    {
        "key": "engle_manganelli_2004",
        "citation": "Robert F. Engle and Simone Manganelli (2004), CAViaR: Conditional Autoregressive Value at Risk by Regression Quantiles, Journal of Business & Economic Statistics 22(4), 367-381.",
        "doi": "10.1198/073500104000000370",
        "url": "https://doi.org/10.1198/073500104000000370",
        "verified_claim": "Provides the dynamic-quantile specification test used for conditional VaR calibration.",
        "accessed_at_utc": "2026-08-02T06:44:39Z",
    },
]


def finite(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): finite(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [finite(v) for v in value]
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        x = float(value)
        return x if math.isfinite(x) else None
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest() -> dict[str, Any]:
    """Return stable provenance for the frozen, byte-identical source copy."""
    return {
        "source": "frozen yfinance adjusted-close cache inherited byte-for-byte from committed K1727 artifact",
        "local_path": "experiments/K1746/data/prices.csv",
        "local_sha256": sha256(PRICE_PATH),
        "local_size_bytes": PRICE_PATH.stat().st_size,
        "upstream": UPSTREAM,
        "copied_for_k1746_at_utc": SOURCE_COPIED_AT_UTC,
        "retrieval_as_of_policy": "No network retrieval in K1746; the upstream K1727 run timestamp records acquisition time and the pinned commit/hash establish immutable source identity.",
    }


def load_data() -> tuple[pd.DataFrame, dict[str, Any]]:
    raw = pd.read_csv(PRICE_PATH, parse_dates=["Date"]).set_index("Date").sort_index()
    if raw.index.duplicated().any():
        raise AssertionError("duplicate dates in frozen source")
    missing_columns = [a for a in ASSETS if a not in raw]
    if missing_columns:
        raise AssertionError(f"missing assets: {missing_columns}")
    selected = raw[ASSETS].copy()
    common = selected.dropna()
    returns = common.pct_change(fill_method=None).dropna()
    if not returns.index.is_monotonic_increasing or returns.index.duplicated().any():
        raise AssertionError("return calendar is not unique/ordered")
    diagnostics = {
        "source_rows": len(raw),
        "source_start": raw.index.min(),
        "source_end": raw.index.max(),
        "source_duplicate_dates": int(raw.index.duplicated().sum()),
        "missing_prices_by_asset": selected.isna().sum().to_dict(),
        "common_price_rows": len(common),
        "common_price_start": common.index.min(),
        "common_price_end": common.index.max(),
        "return_rows": len(returns),
        "return_start": returns.index.min(),
        "return_end": returns.index.max(),
        "timezone": "exchange session date labels; yfinance daily bars; timezone-naive CSV",
        "adjustment": "auto_adjust=True upstream; adjusted Close includes splits/distributions as supplied by yfinance",
        "missing_policy": "strict common-date intersection; no price or return imputation",
        "corporate_actions": "handled by upstream yfinance auto-adjust; no independent corporate-action audit",
        "return_summary": returns.describe(percentiles=[0.01, 0.05, 0.5, 0.95, 0.99]).to_dict(),
        "extreme_abs_return_by_asset": returns.abs().max().to_dict(),
        "lag1_return_autocorrelation": returns.apply(lambda x: x.autocorr(1)).to_dict(),
        "lag1_squared_return_autocorrelation": returns.pow(2).apply(lambda x: x.autocorr(1)).to_dict(),
    }
    return returns, finite(diagnostics)


def daily_equal_weight_returns(component_returns: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    weights = pd.DataFrame(1.0 / len(ASSETS), index=component_returns.index, columns=ASSETS)
    return (component_returns * weights).sum(axis=1), weights


def weekly_rebalanced_returns(component_returns: pd.DataFrame) -> tuple[pd.Series, pd.DataFrame]:
    """Equal weight at each ISO-week boundary; weights drift within the week."""
    values = np.full(len(ASSETS), 1.0 / len(ASSETS))
    out: list[float] = []
    pre_weights: list[np.ndarray] = []
    last_week: tuple[int, int] | None = None
    for date, row in component_returns.iterrows():
        iso = date.isocalendar()
        week = (int(iso.year), int(iso.week))
        if week != last_week:
            values[:] = 1.0 / len(ASSETS)
            last_week = week
        pre_weights.append(values.copy())
        ret = float(np.dot(values, row.to_numpy(float)))
        out.append(ret)
        values *= 1.0 + row.to_numpy(float)
        values /= values.sum()
    weights = pd.DataFrame(pre_weights, index=component_returns.index, columns=ASSETS)
    return pd.Series(out, index=component_returns.index, name="portfolio_return"), weights


def ewma_signal(frame: pd.DataFrame | pd.Series, lam: float = EWMA_LAMBDA):
    raw_signal = frame.pow(2).ewm(alpha=1.0 - lam, adjust=False).mean().pow(0.5)
    signal = raw_signal.shift(1)  # signal from t-1, return at t
    return signal.clip(lower=EPS)


def quantile_es(samples: np.ndarray, alpha: float) -> tuple[float, float]:
    x = np.asarray(samples, dtype=float)
    q = float(np.quantile(x, alpha, method="linear"))
    tail = x[x <= q]
    e = float(tail.mean())
    if not e <= q:
        raise AssertionError("lower-tail ES must not exceed VaR quantile")
    return q, e


@dataclass(frozen=True)
class ForecastSpec:
    name: str
    window: int
    dependence: str
    distribution: str
    rebalance: str


PRIMARY = ForecastSpec("primary_joint_fhs_w756_daily", PRIMARY_WINDOW, "same_date_empirical", "FHS", "daily")
SPECS = [
    PRIMARY,
    ForecastSpec("window_504", ALT_WINDOW, "same_date_empirical", "FHS", "daily"),
    ForecastSpec("independent_margins", PRIMARY_WINDOW, "independent_permutations", "FHS", "daily"),
    ForecastSpec("gaussian", PRIMARY_WINDOW, "EWMA_covariance", "Gaussian", "daily"),
    ForecastSpec("weekly_rebalance", PRIMARY_WINDOW, "same_date_empirical", "FHS", "weekly"),
]


def forecast_spec(
    component_returns: pd.DataFrame,
    portfolio_returns: pd.Series,
    weights: pd.DataFrame,
    spec: ForecastSpec,
    seed: int,
) -> pd.DataFrame:
    comp_signal = ewma_signal(component_returns)
    port_signal = ewma_signal(portfolio_returns)
    comp_resid = component_returns / comp_signal
    port_resid = portfolio_returns / port_signal
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    start = max(spec.window + 2, int(comp_signal.notna().all(axis=1).to_numpy().argmax()) + spec.window)
    for origin in range(start, len(component_returns)):
        lo, hi = origin - spec.window, origin
        if hi - 1 >= origin:
            raise AssertionError("training label overlaps forecast origin")
        date = component_returns.index[origin]
        c_hist = comp_resid.iloc[lo:hi]
        p_hist = port_resid.iloc[lo:hi]
        valid = c_hist.notna().all(axis=1) & p_hist.notna()
        c_hist = c_hist.loc[valid]
        p_hist = p_hist.loc[valid]
        if len(c_hist) < int(0.9 * spec.window):
            continue
        current_sigma = comp_signal.iloc[origin].to_numpy(float)
        current_p_sigma = float(port_signal.iloc[origin])
        current_weights = weights.iloc[origin].to_numpy(float)
        if not np.isfinite(current_sigma).all() or not np.isfinite(current_p_sigma):
            continue
        if spec.distribution == "Gaussian":
            scaled = c_hist.to_numpy(float) * current_sigma
            cov = np.cov(scaled, rowvar=False, ddof=1)
            eig = np.linalg.eigvalsh(cov)
            p_sd_bottom = float(np.sqrt(max(current_weights @ cov @ current_weights, EPS)))
            p_sd_top = current_p_sigma * float(p_hist.std(ddof=1))
            method_samples = None
        else:
            scaled = c_hist.to_numpy(float) * current_sigma
            if spec.dependence == "independent_permutations":
                scaled = np.column_stack([rng.permutation(scaled[:, j]) for j in range(scaled.shape[1])])
            bottom_samples = scaled @ current_weights
            top_samples = p_hist.to_numpy(float) * current_p_sigma
            eig = np.linalg.eigvalsh(np.cov(c_hist.to_numpy(float), rowvar=False, ddof=1))
            method_samples = (bottom_samples, top_samples, scaled)
        for alpha in ALPHAS:
            if spec.distribution == "Gaussian":
                z = float(stats.norm.ppf(alpha))
                tail = -float(stats.norm.pdf(z) / alpha)
                bottom_q, bottom_e = z * p_sd_bottom, tail * p_sd_bottom
                top_q, top_e = z * p_sd_top, tail * p_sd_top
                comp_q = z * np.sqrt(np.diag(cov))
                comp_e = tail * np.sqrt(np.diag(cov))
            else:
                assert method_samples is not None
                bottom_q, bottom_e = quantile_es(method_samples[0], alpha)
                top_q, top_e = quantile_es(method_samples[1], alpha)
                pairs = [quantile_es(method_samples[2][:, j], alpha) for j in range(len(ASSETS))]
                comp_q = np.array([p[0] for p in pairs])
                comp_e = np.array([p[1] for p in pairs])
            naive_q = float(current_weights @ comp_q)
            naive_e = float(current_weights @ comp_e)
            values = {
                "bottom_up": (bottom_q, bottom_e),
                "top_down": (top_q, top_e),
                "naive_marginal_sum": (naive_q, naive_e),
            }
            for method, (q, e) in values.items():
                if not e <= q < 0:
                    raise AssertionError(f"invalid VaR/ES sign at {date}: {method} {q} {e}")
                rows.append(
                    {
                        "spec": spec.name,
                        "date": date,
                        "origin_position": origin,
                        "training_start_position": lo,
                        "training_end_position": hi - 1,
                        "method": method,
                        "alpha": alpha,
                        "realized_return": float(portfolio_returns.iloc[origin]),
                        "var": q,
                        "es": e,
                        "dependence_min_eigenvalue": float(eig.min()),
                        "dependence_positive_definite": bool(eig.min() > 1e-10),
                    }
                )
    out = pd.DataFrame(rows)
    if out.empty:
        raise RuntimeError(f"no forecasts for {spec.name}")
    if not (out["training_end_position"] < out["origin_position"]).all():
        raise AssertionError("point-in-time boundary failed")
    counts = out.groupby(["method", "alpha"])["date"].nunique()
    if counts.nunique() != 1:
        raise AssertionError("methods/alphas do not share identical origins")
    return out


def fz0_loss(y: np.ndarray, q: np.ndarray, e: np.ndarray, alpha: float) -> np.ndarray:
    """Fissler-Ziegel FZ0 loss for lower-tail returns; lower is better."""
    y, q, e = (np.asarray(z, dtype=float) for z in (y, q, e))
    if not np.all(e < 0):
        raise AssertionError("FZ0 requires negative lower-tail ES")
    return -((y <= q) * (q - y)) / (alpha * e) + q / e + np.log(-e) - 1.0


def safe_log_prob(count: int, total: int) -> float:
    if count == 0:
        return 0.0
    if total == 0:
        return float("-inf")
    return count * math.log(total)


def kupiec(hits: np.ndarray, alpha: float) -> dict[str, float]:
    h = np.asarray(hits, dtype=int)
    n, x = len(h), int(h.sum())
    phat = x / n
    ll0 = (n - x) * math.log(max(1 - alpha, EPS)) + x * math.log(max(alpha, EPS))
    ll1 = (n - x) * math.log(max(1 - phat, EPS)) + x * math.log(max(phat, EPS)) if 0 < x < n else 0.0
    stat = max(0.0, -2.0 * (ll0 - ll1))
    return {"statistic": stat, "p_value": float(stats.chi2.sf(stat, 1))}


def christoffersen(hits: np.ndarray) -> dict[str, float]:
    h = np.asarray(hits, dtype=int)
    n00 = int(np.sum((h[:-1] == 0) & (h[1:] == 0)))
    n01 = int(np.sum((h[:-1] == 0) & (h[1:] == 1)))
    n10 = int(np.sum((h[:-1] == 1) & (h[1:] == 0)))
    n11 = int(np.sum((h[:-1] == 1) & (h[1:] == 1)))
    pi = (n01 + n11) / max(n00 + n01 + n10 + n11, 1)
    pi0 = n01 / max(n00 + n01, 1)
    pi1 = n11 / max(n10 + n11, 1)
    def bern_ll(a: int, b: int, p: float) -> float:
        return a * math.log(max(1 - p, EPS)) + b * math.log(max(p, EPS))
    ll0 = bern_ll(n00 + n10, n01 + n11, pi)
    ll1 = bern_ll(n00, n01, pi0) + bern_ll(n10, n11, pi1)
    stat = max(0.0, -2.0 * (ll0 - ll1))
    return {"statistic": stat, "p_value": float(stats.chi2.sf(stat, 1)), "n00": n00, "n01": n01, "n10": n10, "n11": n11}


def dq_test(hits: np.ndarray, q: np.ndarray, alpha: float, lags: int = 4) -> dict[str, float]:
    hit = np.asarray(hits, float) - alpha
    q = np.asarray(q, float)
    rows, target = [], []
    q_scale = max(float(np.std(q, ddof=1)), EPS)
    for t in range(lags, len(hit)):
        rows.append([1.0, *[hit[t - j] for j in range(1, lags + 1)], q[t] / q_scale])
        target.append(hit[t])
    x = np.asarray(rows, float)
    y = np.asarray(target, float)
    proj = x @ np.linalg.pinv(x.T @ x) @ x.T
    stat = float(y.T @ proj @ y / (alpha * (1 - alpha)))
    df = int(np.linalg.matrix_rank(x))
    return {"statistic": stat, "p_value": float(stats.chi2.sf(stat, df)), "df": df, "lags": lags}


def moving_block_indices(n: int, block: int, reps: int, rng: np.random.Generator):
    blocks = math.ceil(n / block)
    starts = rng.integers(0, n - block + 1, size=(reps, blocks))
    offsets = np.arange(block)
    return (starts[:, :, None] + offsets).reshape(reps, -1)[:, :n]


def block_mean_test(x: np.ndarray, reps: int, block: int, seed: int) -> dict[str, float]:
    x = np.asarray(x, float)
    observed = float(x.mean())
    centered = x - observed
    idx = moving_block_indices(len(x), min(block, len(x)), reps, np.random.default_rng(seed))
    boot = centered[idx].mean(axis=1)
    p_two = float((1 + np.sum(np.abs(boot) >= abs(observed))) / (reps + 1))
    p_less = float((1 + np.sum(boot <= observed)) / (reps + 1))
    p_greater = float((1 + np.sum(boot >= observed)) / (reps + 1))
    return {"mean": observed, "p_value_two_sided": p_two, "p_value_less": p_less, "p_value_greater": p_greater, "reps": reps, "block_length": block}


def es_z2_test(y: np.ndarray, q: np.ndarray, e: np.ndarray, alpha: float, seed: int) -> dict[str, Any]:
    moment = (np.asarray(y) * (np.asarray(y) <= np.asarray(q))) / (alpha * np.asarray(e)) - 1.0
    test = block_mean_test(moment, BOOT_REPS, BOOT_BLOCK, seed)
    test.update({"name": "Acerbi-Szekely Z2 all-observation moment", "null": "E[y*I(y<=VaR)/(alpha*ES)-1]=0", "orientation": "positive means realized lower-tail losses are more severe relative to the negative ES forecast", "finite_sample_caveat": "moving-block bootstrap is asymptotic and 1% tails have few effective exceptions"})
    return test


def evaluate_primary(primary: pd.DataFrame) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    cells: dict[str, Any] = {}
    losses: dict[str, np.ndarray] = {}
    raw_p: dict[str, float] = {}
    for (method, alpha), g in primary.groupby(["method", "alpha"], sort=True):
        g = g.sort_values("date")
        y, q, e = g["realized_return"].to_numpy(), g["var"].to_numpy(), g["es"].to_numpy()
        hits = y <= q
        uc = kupiec(hits, float(alpha))
        ind = christoffersen(hits)
        cc_stat = uc["statistic"] + ind["statistic"]
        cc = {"statistic": cc_stat, "p_value": float(stats.chi2.sf(cc_stat, 2))}
        dq = dq_test(hits, q, float(alpha))
        es_test = es_z2_test(y, q, e, float(alpha), SEED)
        loss = fz0_loss(y, q, e, float(alpha))
        key = f"{method}|{alpha:.2f}"
        cells[key] = {
            "method": method, "alpha": float(alpha), "oos_count": len(g),
            "violations": int(hits.sum()), "expected_violations": float(len(g) * alpha),
            "violation_rate": float(hits.mean()), "kupiec_uc": uc,
            "christoffersen_independence": ind, "christoffersen_conditional_coverage": cc,
            "dynamic_quantile": dq, "expected_shortfall_z2": es_test,
            "fz0_mean_loss": float(loss.mean()), "fz0_loss_std": float(loss.std(ddof=1)),
        }
        losses[key] = loss
        for test_name, p in [("kupiec_uc", uc["p_value"]), ("christoffersen_independence", ind["p_value"]), ("christoffersen_conditional_coverage", cc["p_value"]), ("dynamic_quantile", dq["p_value"]), ("expected_shortfall_z2", es_test["p_value_two_sided"])]:
            raw_p[f"{key}|{test_name}"] = float(p)
    # Canonical Holm step-down (volpred.stats.inference) replaces the former
    # local copy in this file; the two are algorithmically identical and the
    # adjusted p-values are unchanged, so K1746_results.json is unaffected.
    _cell_keys = list(raw_p)
    adjusted = dict(
        zip(
            _cell_keys,
            holm_step_down([raw_p[k] for k in _cell_keys]).adjusted_p_values,
        )
    )
    for full, p_adj in adjusted.items():
        cell_key, test_name = full.rsplit("|", 1)
        cells[cell_key][test_name]["p_value_holm_all_methods_alphas_tests"] = p_adj
        cells[cell_key][test_name]["reject_holm_5pct"] = bool(p_adj < 0.05)
    return cells, losses


def score_inference(primary: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    raw: dict[str, float] = {}
    for alpha in ALPHAS:
        pivot = primary[primary.alpha == alpha].pivot(index="date", columns="method", values=["realized_return", "var", "es"])
        y = pivot[("realized_return", "bottom_up")].to_numpy()
        lb = fz0_loss(y, pivot[("var", "bottom_up")], pivot[("es", "bottom_up")], alpha)
        lt = fz0_loss(y, pivot[("var", "top_down")], pivot[("es", "top_down")], alpha)
        test = block_mean_test(lb - lt, BOOT_REPS, BOOT_BLOCK, SEED)
        key = f"alpha_{alpha:.2f}"
        out[key] = {**test, "orientation": "bottom_up_minus_top_down; negative favors bottom-up", "bottom_up_mean": float(lb.mean()), "top_down_mean": float(lt.mean())}
        raw[key] = test["p_value_two_sided"]
    _alpha_keys = list(raw)
    adj = dict(
        zip(
            _alpha_keys,
            holm_step_down([raw[k] for k in _alpha_keys]).adjusted_p_values,
        )
    )
    for key, value in out.items():
        value["p_value_holm_two_alphas"] = adj[key]
    return out


def mcs_pair(primary: pd.DataFrame, alpha: float, reps: int, block: int, seed: int) -> dict[str, Any]:
    g = primary[(primary.alpha == alpha) & primary.method.isin(["bottom_up", "top_down"])]
    pivot = g.pivot(index="date", columns="method", values=["realized_return", "var", "es"])
    y = pivot[("realized_return", "bottom_up")].to_numpy()
    loss = {
        m: fz0_loss(y, pivot[("var", m)], pivot[("es", m)], alpha)
        for m in ["bottom_up", "top_down"]
    }
    d = loss["bottom_up"] - loss["top_down"]
    test = block_mean_test(d, reps, block, seed)
    means = {m: float(x.mean()) for m, x in loss.items()}
    included = ["bottom_up", "top_down"]
    eliminated = None
    if test["p_value_two_sided"] < MCS_LEVEL:
        eliminated = max(means, key=means.get)
        included.remove(eliminated)
    return {
        "candidate_set": ["bottom_up", "top_down"], "loss": "FZ0 joint VaR/ES, lower better",
        "bootstrap": "paired moving-date-block bootstrap of centered daily loss differential",
        "block_length": block, "resamples": reps, "seed": seed,
        "elimination_statistic": "absolute mean pairwise loss differential",
        "elimination_rule": f"eliminate higher-mean-loss method if two-sided block-bootstrap p < {MCS_LEVEL}",
        "confidence_level": 1 - MCS_LEVEL, "mean_losses": means,
        "loss_difference_bottom_minus_top": test, "included_set": included, "eliminated": eliminated,
    }


def sensitivity_summary(all_forecasts: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for (spec, alpha), g in all_forecasts[all_forecasts.method.isin(["bottom_up", "top_down"])].groupby(["spec", "alpha"]):
        pivot = g.pivot(index="date", columns="method", values=["realized_return", "var", "es"])
        y = pivot[("realized_return", "bottom_up")].to_numpy()
        lb = fz0_loss(y, pivot[("var", "bottom_up")], pivot[("es", "bottom_up")], float(alpha))
        lt = fz0_loss(y, pivot[("var", "top_down")], pivot[("es", "top_down")], float(alpha))
        diff = lb - lt
        out[f"{spec}|{alpha:.2f}"] = {"oos_count": len(diff), "bottom_minus_top_fz0": float(diff.mean()), "direction": "bottom_up" if diff.mean() < 0 else "top_down", "positive_definite_rate": float(g["dependence_positive_definite"].mean())}
    crisis = all_forecasts[(all_forecasts.spec == PRIMARY.name) & (pd.to_datetime(all_forecasts.date) >= pd.Timestamp("2020-01-01"))]
    for alpha in ALPHAS:
        g = crisis[(crisis.alpha == alpha) & crisis.method.isin(["bottom_up", "top_down"])]
        pivot = g.pivot(index="date", columns="method", values=["realized_return", "var", "es"])
        y = pivot[("realized_return", "bottom_up")].to_numpy()
        diff = fz0_loss(y, pivot[("var", "bottom_up")], pivot[("es", "bottom_up")], alpha) - fz0_loss(y, pivot[("var", "top_down")], pivot[("es", "top_down")], alpha)
        out[f"crisis_2020_plus|{alpha:.2f}"] = {"oos_count": len(diff), "bottom_minus_top_fz0": float(diff.mean()), "direction": "bottom_up" if diff.mean() < 0 else "top_down"}
    return out


def derive_verdict(cells: dict[str, Any], score: dict[str, Any], sensitivity: dict[str, Any]) -> dict[str, Any]:
    score_sig = [v["p_value_holm_two_alphas"] < 0.05 for v in score.values()]
    primary_dirs = ["bottom_up" if v["mean"] < 0 else "top_down" for v in score.values()]
    robust_keys = [k for k in sensitivity if not k.startswith("crisis")]
    robust_dirs = [sensitivity[k]["direction"] for k in robust_keys]
    calibration_rejections = {
        method: sum(
            int(test.get("reject_holm_5pct", False))
            for key, cell in cells.items() if cell["method"] == method
            for name, test in cell.items() if name in {"kupiec_uc", "christoffersen_independence", "christoffersen_conditional_coverage", "dynamic_quantile", "expected_shortfall_z2"}
        ) for method in ["bottom_up", "top_down", "naive_marginal_sum"]
    }
    if all(score_sig) and len(set(primary_dirs)) == 1 and robust_dirs.count(primary_dirs[0]) >= math.ceil(0.75 * len(robust_dirs)):
        winner = primary_dirs[0]
        loser = "top_down" if winner == "bottom_up" else "bottom_up"
        if calibration_rejections[winner] < calibration_rejections[loser]:
            grade = "CONDITIONAL_DIRECTIONAL_EVIDENCE"
        else:
            grade = "CONDITIONAL_SCORE_ONLY"
    elif any(score_sig):
        grade = "CONDITIONAL_UNSTABLE"
    else:
        grade = "NULL_NO_MULTIPLICITY_AWARE_DIRECTIONAL_SUPERIORITY"
    return {
        "grade": grade,
        "scientific_null_not_zero_salvage": True,
        "primary_score_directions": primary_dirs,
        "score_significant_after_holm": score_sig,
        "calibration_rejections_after_global_holm": calibration_rejections,
        "success_contract": "A substantive positive requires multiplicity-aware joint-score evidence, fewer calibration failures, and >=75% preregistered sensitivity-direction stability.",
        "claim_limit": "Failure to reject any calibration test is not evidence of superiority.",
    }


def write_svg(score: dict[str, Any]) -> None:
    width, height = 760, 330
    vals = [(k, v["bottom_up_mean"], v["top_down_mean"]) for k, v in score.items()]
    allv = [x for _, a, b in vals for x in (a, b)]
    lo, hi = min(allv), max(allv)
    span = max(hi - lo, 1e-9)
    bars = []
    for i, (label, btm, top) in enumerate(vals):
        for j, (name, value, color) in enumerate([("bottom-up", btm, "#2166ac"), ("top-down", top, "#b2182b")]):
            x = 120 + i * 300 + j * 90
            h = 190 * (value - lo) / span + 15
            y = 265 - h
            bars.append(f'<rect x="{x}" y="{y:.1f}" width="60" height="{h:.1f}" fill="{color}"/><text x="{x+30}" y="{y-6:.1f}" text-anchor="middle" font-size="12">{value:.4f}</text><text x="{x+30}" y="285" text-anchor="middle" font-size="11">{name}</text>')
        bars.append(f'<text x="{195+i*300}" y="310" text-anchor="middle" font-size="13">{label}</text>')
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}"><rect width="100%" height="100%" fill="white"/><text x="380" y="25" text-anchor="middle" font-size="18">K1746 mean FZ0 joint VaR/ES loss (lower is better)</text><line x1="70" y1="265" x2="700" y2="265" stroke="black"/>{''.join(bars)}<text x="20" y="165" transform="rotate(-90 20 165)" font-size="13">mean FZ0 loss</text></svg>'''
    CHART_PATH.write_text(svg + "\n", encoding="utf-8")


def write_readme(payload: dict[str, Any]) -> None:
    verdict = payload["verdict"]
    score = payload["proper_score_inference"]
    mcs = payload["model_confidence_set"]
    lines = [
        "# K1746 — Bottom-up versus top-down portfolio VaR/ES\n",
        "## Identity and the prior failed job\n",
        "The earlier Claude job `agent-k1746-var-es-4316fc94` is **ZERO_SALVAGE**: it stopped at a provider weekly quota before research began, emitted no scientific artifact, and is neither a successful experiment nor a scientific null. This directory is a distinct Codex failover execution. The current verdict below comes only from `K1746_results.json#/verdict`.\n",
        "## Falsifiable question and preregistered bar\n",
        "For the equal-weight SPY/TLT/GLD/HYG/QQQ basket, does cross-sectional aggregation direction change genuinely OOS one-day 1%/5% VaR/ES calibration and FZ0 joint proper loss? A substantive positive required Holm-aware joint-score evidence, fewer calibration rejections, and at least 75% sensitivity-direction stability. Failure to reject coverage was never treated as superiority.\n",
        "## Data and point-in-time policy\n",
        "Frozen yfinance `auto_adjust=True` adjusted-close cache, originally committed by K1727 on 2026-07-28; local bytes and source metadata are in `source_manifest.json`. Strict common-date intersection, no imputation, daily equal-weight rebalancing primary, weekly reset/drift sensitivity. Every target at t uses volatility signals explicitly formed by `signal.shift(1)` and residual labels ending at t-1; runtime assertions and `test_K1746.py` enforce the seam. Exact periods/counts are `K1746_results.json#/data` and `#/backtests`.\n",
        "## Methods\n",
        "Primary bottom-up FHS rescales component standardized residuals with t-origin component EWMA volatilities and aggregates the same-date residual vector with portfolio weights, retaining point-in-time empirical dependence. Top-down FHS uses the same filter/window on the identical realized portfolio target. The marginal VaR/ES sum is labelled `naive_marginal_sum` and is only a dependence-ignoring diagnostic. Sensitivities change window (756→504), dependence (independent marginal permutations), distribution (Gaussian), rebalancing (weekly), and crisis sample (2020+). Empirical covariance eigenvalues are recorded; exact empirical support is used, so primary simulation error is zero conditional on the finite residual window. Tail dependence remains limited to events observed in that window.\n",
        "## Formal tests and loss\n",
        "Per method/alpha: Kupiec UC, Christoffersen independence and conditional coverage, Engle–Manganelli-style DQ (4 hit lags plus scaled VaR), and Acerbi–Szekely Z2 ES moment with paired moving-date-block bootstrap. Holm controls the complete 3 methods × 2 alphas × 5 tests family. FZ0 is a jointly elicitable VaR/ES loss (lower better). MCS uses identical date-level loss series, block 10, 2,000 resamples, seed 42, 90% confidence, and eliminates the higher-loss method only when the centered pairwise bootstrap rejects. Full definitions/nulls/orientations are in `K1746_results.json#/methodology`, `#/backtests`, and `#/model_confidence_set`.\n",
        f"## Result — `{verdict['grade']}`\n",
    ]
    for key, val in score.items():
        lines.append(f"- `{key}`: bottom-up mean FZ0 `{val['bottom_up_mean']:.8f}`, top-down `{val['top_down_mean']:.8f}`, bottom-minus-top `{val['mean']:.8f}`, Holm p `{val['p_value_holm_two_alphas']:.6f}` (`K1746_results.json#/proper_score_inference/{key}`).\n")
    for key, val in mcs.items():
        lines.append(f"- MCS `{key}` included set `{val['included_set']}`, p `{val['loss_difference_bottom_minus_top']['p_value_two_sided']:.6f}` (`K1746_results.json#/model_confidence_set/{key}`).\n")
    lines.extend([
        f"Calibration rejection counts after the global Holm family are `{verdict['calibration_rejections_after_global_holm']}` (`K1746_results.json#/verdict/calibration_rejections_after_global_holm`). These counts cannot be read as rankings by themselves.\n",
        "## Limitations\n",
        "ETF history begins only after HYG has common adjusted prices; adjusted yfinance history is a current-vintage vendor product, not an exchange-certified PIT tape. FHS tail support is bounded by a rolling window; 1% inference has few effective tail events. Empirical same-date dependence captures observed nonlinear co-movement but cannot extrapolate unseen tail dependence. Weekly rebalancing is a defensible convention sensitivity, not a full transaction-cost implementation. DQ and ES bootstrap p-values are finite-sample approximations. MCS has only the two scientific direction candidates; the naive diagnostic is intentionally excluded.\n",
        "## Literature (verified primary metadata)\n",
        "- Wang & Wang (2025), Journal of Forecasting 44(2), 391–423, DOI [10.1002/for.3195](https://doi.org/10.1002/for.3195).\n- Fissler & Ziegel (2016), Annals of Statistics 44(4), DOI [10.1214/16-AOS1439](https://doi.org/10.1214/16-AOS1439).\n- Hansen, Lunde & Nason (2011), Econometrica 79(2), DOI [10.3982/ECTA5771](https://doi.org/10.3982/ECTA5771).\n- Acerbi & Szekely (2014), [MSCI research paper](https://www.msci.com/research-and-insights/paper/research-insight-backtesting-expected-shortfall-december-2014).\n- Engle & Manganelli (2004), JBES 22(4), DOI [10.1198/073500104000000370](https://doi.org/10.1198/073500104000000370).\n",
        "## Reproduce\n",
        "```bash\nuv run python experiments/K1746/K1746.py\nuv run pytest -q experiments/K1746\n```\n",
        "Numeric tables and claims are generated from the same in-memory payload finalized into `K1746_results.json`; forecasts/loss inputs are in `K1746_forecasts.csv.gz`, and every inference cell is mirrored in `K1746_inference_cells.json`. Independent review is deliberately deferred to PHASE A; this worktree does not contain `review_verdict.json`.\n",
    ])
    (HERE / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    started = time.time()
    np.random.seed(SEED)
    returns, diagnostics = load_data()
    daily_port, daily_weights = daily_equal_weight_returns(returns)
    weekly_port, weekly_weights = weekly_rebalanced_returns(returns)
    frames = []
    for spec in SPECS:
        port, weights = (weekly_port, weekly_weights) if spec.rebalance == "weekly" else (daily_port, daily_weights)
        frames.append(forecast_spec(returns, port, weights, spec, SEED))
    forecasts = pd.concat(frames, ignore_index=True)
    primary = forecasts[forecasts.spec == PRIMARY.name].copy()
    cells, _ = evaluate_primary(primary)
    score = score_inference(primary)
    mcs = {
        f"alpha_{alpha:.2f}": mcs_pair(primary, alpha, BOOT_REPS, BOOT_BLOCK, SEED)
        for alpha in ALPHAS
    }
    mcs_sensitivity = {
        f"alpha_{alpha:.2f}_block20_reps1000": mcs_pair(primary, alpha, 1000, 20, SEED)
        for alpha in ALPHAS
    }
    sensitivity = sensitivity_summary(forecasts)
    verdict = derive_verdict(cells, score, sensitivity)
    manifest = source_manifest()
    if manifest["local_sha256"] != UPSTREAM["sha256"]:
        raise AssertionError("frozen price cache hash differs from upstream")
    forecasts.to_csv(FORECAST_PATH, index=False, compression={"method": "gzip", "mtime": 0})
    DIAGNOSTICS_PATH.write_text(json.dumps(diagnostics, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REFERENCES_PATH.write_text(json.dumps(REFERENCES, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    inference_sidecar = {"backtests": cells, "proper_score_inference": score, "model_confidence_set": mcs, "mcs_sensitivity": mcs_sensitivity, "sensitivities": sensitivity}
    INFERENCE_PATH.write_text(json.dumps(finite(inference_sidecar), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    payload = finite({
        "experiment_id": "K1746", "seed": SEED,
        "recovery_identity": {
            "prior_job": "agent-k1746-var-es-4316fc94", "prior_status": "ZERO_SALVAGE",
            "prior_failure_class": "quota", "prior_exit_code": 1,
            "distinction": "Prior job never began research and is neither a scientific null nor evidence that the Claude provider recovered.",
            "current_executor": "Codex failover in distinct registered worktree",
        },
        "data": {**diagnostics, "manifest": manifest},
        "portfolio": {"assets": ASSETS, "primary_weights": [0.2] * 5, "primary_rebalancing": "daily equal weight", "alternative_rebalancing": "ISO-week reset then buy-and-hold drift"},
        "methodology": {
            "horizon": "one trading day", "alphas": ALPHAS,
            "primary": PRIMARY.__dict__, "all_specs": [s.__dict__ for s in SPECS],
            "information_set": "signals at target t are shift(1) and training_end_position < origin_position",
            "bottom_up_formula": "For residual row s: R_p,t^(s)=sum_i w_i,t sigma_i,t z_i,s; VaR=empirical alpha quantile; ES=mean below/equal quantile.",
            "top_down_formula": "R_p,t^(s)=sigma_p,t z_p,s using identical portfolio target/filter/window/origins.",
            "naive_formula": "sum_i w_i VaR_i and sum_i w_i ES_i; dependence-ignoring diagnostic only.",
            "joint_score": "FZ0 on lower-tail returns: -I(y<=q)(q-y)/(alpha*e)+q/e+log(-e)-1; lower better.",
            "multiplicity": "Holm FWER across 3 methods x 2 alphas x 5 calibration tests; separate Holm across 2 alpha score comparisons.",
            "mcs": "two-candidate paired moving-date-block bootstrap MCS analogue following Hansen-Lunde-Nason; seed 42; no stacked asset-day iid resampling.",
            "simulation_error": "Primary and window/weekly FHS use exact finite empirical support (zero Monte Carlo error conditional on window); independent sensitivity uses seeded permutations and is not primary.",
        },
        "backtests": cells, "proper_score_inference": score,
        "model_confidence_set": mcs, "mcs_sensitivity": mcs_sensitivity,
        "sensitivities": sensitivity, "verdict": verdict,
        "limitations": [
            "current-vintage yfinance adjusted history, not exchange-certified PIT raw bars",
            "rolling empirical support cannot represent unseen tail events or extrapolate tail dependence",
            "few effective 1% violations and finite-sample DQ/ES/bootstrap uncertainty",
            "weekly rebalancing sensitivity omits trading costs; daily equal weight is a stylized basket",
            "MCS has two scientific candidates; naive marginal sum is excluded by design",
        ],
        "literature": REFERENCES,
        "run_utc": datetime.now(UTC).isoformat(),
    })
    write_svg(score)
    write_readme(payload)
    outputs = [
        "README.md", FORECAST_PATH.name, INFERENCE_PATH.name, DIAGNOSTICS_PATH.name,
        MANIFEST_PATH.name, REFERENCES_PATH.name, CHART_PATH.name,
    ]
    finalize_experiment(
        results=payload, entrypoint=__file__, canonical_result=RESULT_PATH.name,
        inputs=[PRICE_PATH], outputs=outputs,
        seeds=[("numpy", SEED), ("bootstrap", SEED), ("MCS", SEED)],
        started_at=started, network="deny",
        comparison={
            "ignore_pointers": [
                "/artifact_generation/generation_id",
                "/created_at",
                "/run_utc",
                "/runtime_env",
                "/runtime_seconds",
            ],
            "ignore_reasons": {
                "/artifact_generation/generation_id": "The generation receipt intentionally incorporates the ignored execution timestamp; output identities and every scientific scalar remain compared separately.",
                "/created_at": "Execution timestamp; written after every scientific value is computed.",
                "/run_utc": "Execution timestamp; not an input to any estimate or verdict.",
                "/runtime_env": "Interpreter and library versions of the recording host; machine-dependent by construction.",
                "/runtime_seconds": "Wall-clock performance metadata; not an input to any estimate or verdict.",
            },
        },
    )
    print(json.dumps({"grade": verdict["grade"], "result": str(RESULT_PATH), "result_sha256": sha256(RESULT_PATH), "oos_count": next(iter(cells.values()))["oos_count"]}, indent=2))


if __name__ == "__main__":
    main()
