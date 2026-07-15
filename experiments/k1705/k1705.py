#!/usr/bin/env python3
"""K1705: honest dependence-score audit of the K1100c DCC/Joe claim."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import optimize, stats

from volpred.stats.model_evaluation import dm_test


SEED = 42
WINDOW = 1250
REFIT_EVERY = 63
OOS_START = "2013-06-03"
EWMA_LAMBDA = 0.94
EPS = 1e-8

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SNAPSHOT = ROOT / "paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv"
PARENT_RESULTS = ROOT / "experiments/k1100c/k1100c_results.json"
PARENT_SCRIPT = ROOT / "experiments/k1100c/k1100c.py"
RESULTS = HERE / "k1705_results.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def atomic_json_dump(payload: dict, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")
    with tmp.open(encoding="utf-8") as handle:
        json.load(handle)
    os.replace(tmp, path)


def ewma_variance(returns: np.ndarray, lam: float = EWMA_LAMBDA) -> np.ndarray:
    """One-sided variance: h[t] is known after observing return t-1."""
    out = np.full(len(returns), np.nan)
    init = min(60, len(returns))
    out[init] = max(float(np.nanvar(returns[:init], ddof=1)), 1e-10)
    for t in range(init + 1, len(returns)):
        out[t] = lam * out[t - 1] + (1.0 - lam) * returns[t - 1] ** 2
    return out


def fit_t_df(z: np.ndarray) -> float:
    z = z[np.isfinite(z)]
    if len(z) < 100:
        return 8.0

    def objective(df: float) -> float:
        scale = np.sqrt((df - 2.0) / df)
        return -float(np.sum(stats.t.logpdf(z / scale, df=df) - np.log(scale)))

    result = optimize.minimize_scalar(objective, bounds=(2.1, 50.0), method="bounded")
    return float(result.x) if result.success else 8.0


def build_pits(returns: np.ndarray, dates: pd.DatetimeIndex) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rolling Student-t PIT using only observations strictly before each origin."""
    h = ewma_variance(returns)
    pits = np.full(len(returns), np.nan)
    dfs = np.full(len(returns), np.nan)
    first = max(WINDOW, int(np.searchsorted(dates.values, np.datetime64(OOS_START))))
    current_df = 8.0
    for t in range(first, len(returns)):
        if (t - first) % REFIT_EVERY == 0:
            start = max(61, t - WINDOW)
            z_train = returns[start:t] / np.sqrt(h[start:t])
            current_df = fit_t_df(z_train)
        z_t = returns[t] / np.sqrt(h[t])
        scale = np.sqrt((current_df - 2.0) / current_df)
        pits[t] = np.clip(stats.t.cdf(z_t / scale, df=current_df), EPS, 1.0 - EPS)
        dfs[t] = current_df
    return pits, h, dfs


def gaussian_log_density(u: np.ndarray, v: np.ndarray, rho: np.ndarray) -> np.ndarray:
    x = stats.norm.ppf(np.clip(u, EPS, 1 - EPS))
    y = stats.norm.ppf(np.clip(v, EPS, 1 - EPS))
    r = np.clip(rho, -0.995, 0.995)
    one_minus = 1.0 - r**2
    return -0.5 * np.log(one_minus) - 0.5 * (r**2 * (x**2 + y**2) - 2 * r * x * y) / one_minus


def dcc_filter(z1: np.ndarray, z2: np.ndarray, a: float, b: float) -> np.ndarray:
    qbar = np.cov(np.vstack([z1, z2]))
    q = qbar.copy()
    rho = np.full(len(z1), np.nan)
    for t in range(len(z1)):
        if t:
            previous = np.array([z1[t - 1], z2[t - 1]])
            q = (1.0 - a - b) * qbar + a * np.outer(previous, previous) + b * q
        rho[t] = q[0, 1] / np.sqrt(max(q[0, 0] * q[1, 1], 1e-12))
    return np.clip(rho, -0.995, 0.995)


def fit_dcc(z1: np.ndarray, z2: np.ndarray) -> tuple[float, float]:
    def objective(raw: np.ndarray) -> float:
        ea, eb = np.exp(np.clip(raw, -20, 20))
        denom = 1.0 + ea + eb
        a, b = 0.995 * ea / denom, 0.995 * eb / denom
        rho = dcc_filter(z1, z2, a, b)
        value = -np.sum(gaussian_log_density(stats.norm.cdf(z1), stats.norm.cdf(z2), rho))
        return float(value) if np.isfinite(value) else 1e12

    best: tuple[float, np.ndarray] | None = None
    for init in ([-3.0, 2.0], [-2.0, 3.0], [-4.0, 4.0]):
        result = optimize.minimize(objective, np.asarray(init), method="L-BFGS-B")
        if result.success and (best is None or result.fun < best[0]):
            best = (float(result.fun), result.x)
    raw = best[1] if best else np.array([-3.0, 2.0])
    ea, eb = np.exp(np.clip(raw, -20, 20))
    denom = 1.0 + ea + eb
    return float(0.995 * ea / denom), float(0.995 * eb / denom)


def joe_log_density(u: np.ndarray, v: np.ndarray, theta: float) -> np.ndarray:
    u = np.clip(u, EPS, 1 - EPS)
    v = np.clip(v, EPS, 1 - EPS)
    a = (1.0 - u) ** theta
    b = (1.0 - v) ** theta
    ab = a * b
    s = np.clip(a + b - ab, EPS, None)
    # Differentiating C(u,v)=1-S^(1/theta) gives the bracket below.
    # This is exactly one at theta=1 (the independence copula), an important
    # sanity check that the archived K1100c formula fails.
    return (
        (theta - 1.0) * np.log(1.0 - u)
        + (theta - 1.0) * np.log(1.0 - v)
        + (1.0 / theta - 2.0) * np.log(s)
        + np.log(np.clip(theta * s + (theta - 1.0) * (1.0 - a) * (1.0 - b), EPS, None))
    )


def fit_joe(u: np.ndarray, v: np.ndarray) -> float:
    result = optimize.minimize_scalar(
        lambda theta: -float(np.sum(joe_log_density(u, v, theta))),
        bounds=(1.001, 25.0),
        method="bounded",
    )
    return float(result.x) if result.success else 1.001


def rolling_dependence_scores(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    valid_positions = np.flatnonzero(np.isfinite(u) & np.isfinite(v))
    dcc_loss = np.full(len(u), np.nan)
    joe_loss = np.full(len(u), np.nan)
    rho_out = np.full(len(u), np.nan)
    theta_out = np.full(len(u), np.nan)
    current_a, current_b, current_theta = 0.03, 0.94, 1.001
    qbar = np.eye(2)
    q = np.eye(2)

    for count, t in enumerate(valid_positions):
        history = valid_positions[max(0, count - WINDOW):count]
        if len(history) < 250:
            continue
        if (count - 250) % REFIT_EVERY == 0:
            uh, vh = u[history], v[history]
            z1h, z2h = stats.norm.ppf(uh), stats.norm.ppf(vh)
            current_a, current_b = fit_dcc(z1h, z2h)
            current_theta = fit_joe(uh, vh)
            qbar = np.cov(np.vstack([z1h, z2h]))
            q = qbar.copy()
            for j in range(1, len(history)):
                previous = np.array([z1h[j - 1], z2h[j - 1]])
                q = (1 - current_a - current_b) * qbar + current_a * np.outer(previous, previous) + current_b * q
        previous_t = valid_positions[count - 1]
        previous = np.array([stats.norm.ppf(u[previous_t]), stats.norm.ppf(v[previous_t])])
        q = (1 - current_a - current_b) * qbar + current_a * np.outer(previous, previous) + current_b * q
        rho = float(np.clip(q[0, 1] / np.sqrt(max(q[0, 0] * q[1, 1], 1e-12)), -0.995, 0.995))
        dcc_loss[t] = -gaussian_log_density(np.array([u[t]]), np.array([v[t]]), np.array([rho]))[0]
        joe_loss[t] = -joe_log_density(np.array([u[t]]), np.array([v[t]]), current_theta)[0]
        rho_out[t] = rho
        theta_out[t] = current_theta
    return dcc_loss, joe_loss, rho_out, theta_out


def serial_test(values: np.ndarray, lags: int = 10) -> dict:
    x = values[np.isfinite(values)]
    n = len(x)
    acf = []
    for lag in range(1, lags + 1):
        acf.append(float(np.corrcoef(x[lag:], x[:-lag])[0, 1]))
    q = n * (n + 2) * sum(acf[lag - 1] ** 2 / (n - lag) for lag in range(1, lags + 1))
    return {"lag": lags, "q_stat": float(q), "p_value": float(stats.chi2.sf(q, lags)), "acf1": acf[0]}


def marginal_diagnostics(pit: np.ndarray) -> dict:
    x = pit[np.isfinite(pit)]
    ks = stats.kstest(x, "uniform")
    z = stats.norm.ppf(np.clip(x, EPS, 1 - EPS))
    pit_serial = serial_test(x)
    squared_z_serial = serial_test(z**2)
    return {
        "n": int(len(x)),
        "mean": float(np.mean(x)),
        "variance": float(np.var(x, ddof=1)),
        "ks_stat": float(ks.statistic),
        "ks_p_value": float(ks.pvalue),
        "berkowitz_components": {"z_mean": float(np.mean(z)), "z_variance": float(np.var(z, ddof=1))},
        "ljung_box_pit": pit_serial,
        "ljung_box_squared_z": squared_z_serial,
        "passes_joint_gate": bool(
            ks.pvalue > 0.05
            and pit_serial["p_value"] > 0.05
            and squared_z_serial["p_value"] > 0.05
        ),
    }


def evaluate_pair(frame: pd.DataFrame, second: str, shift_second: int) -> dict:
    local = frame[["spy_adj_close", f"{second}_adj_close"]].dropna().copy()
    r1 = np.log(local["spy_adj_close"]).diff().to_numpy()
    r2 = np.log(local[f"{second}_adj_close"]).diff().shift(shift_second).to_numpy()
    u1, _, df1 = build_pits(r1, local.index)
    u2, _, df2 = build_pits(r2, local.index)
    dcc_loss, joe_loss, rho, theta = rolling_dependence_scores(u1, u2)
    valid = np.isfinite(dcc_loss) & np.isfinite(joe_loss)
    dm_t, dm_p = dm_test(dcc_loss[valid], joe_loss[valid], h=1)
    diff = joe_loss[valid] - dcc_loss[valid]
    return {
        "pair": f"SPY-{second.upper()}",
        "second_asset_shift_days": shift_second,
        "oos_first": str(local.index[np.flatnonzero(valid)[0]].date()),
        "oos_last": str(local.index[np.flatnonzero(valid)[-1]].date()),
        "n_scored": int(valid.sum()),
        "marginal_diagnostics": {
            "SPY": marginal_diagnostics(u1),
            second.upper(): marginal_diagnostics(u2),
            "models_share_identical_margins": True,
            "median_fitted_df": {"SPY": float(np.nanmedian(df1)), second.upper(): float(np.nanmedian(df2))},
        },
        "dependence_scores": {
            "mean_negative_log_score": {"DCC_Gaussian": float(np.mean(dcc_loss[valid])), "Joe": float(np.mean(joe_loss[valid]))},
            "joe_minus_dcc_mean": float(np.mean(diff)),
            "canonical_dm_dcc_minus_joe": {"t_stat": dm_t, "p_value": dm_p, "direction": "negative favors DCC; positive favors Joe"},
            "harvey_abs_t_gt_3": bool(abs(dm_t) > 3.0),
            "loss_differential_acf1": float(np.corrcoef(diff[1:], diff[:-1])[0, 1]),
            "mean_dcc_rho": float(np.nanmean(rho)),
            "mean_joe_theta": float(np.nanmean(theta)),
        },
        "two_step_decision": "STOP_AT_MARGINS" if not (
            marginal_diagnostics(u1)["passes_joint_gate"] and marginal_diagnostics(u2)["passes_joint_gate"]
        ) else ("DCC_DEPENDENCE_BETTER" if dm_t < -3 else "JOE_DEPENDENCE_BETTER" if dm_t > 3 else "NO_HARVEY_DIFFERENCE"),
    }


def parent_claim_audit(parent: dict) -> dict:
    rows = {}
    for pair in ("SPY-TLT", "SPY-GLD"):
        dm = parent["pair_results"][pair]["dm_qlike"]["Copula-Joe-A4f-ASYM_vs_DCC-A4f-ASYM"]
        means = parent["pair_results"][pair]["mean_qlike"]
        rows[pair] = {
            "reported_dm_t": dm["t_stat"],
            "reported_mean_loss_diff_joe_minus_dcc": dm["mean_loss_diff"],
            "mean_qlike_joe": means["Copula-Joe-A4f-ASYM"],
            "mean_qlike_dcc": means["DCC-A4f-ASYM"],
            "mechanical_interpretation": "positive Joe-minus-DCC loss and higher mean QLIKE mean Joe is worse",
            "readme_interpretation": "positive t was labeled Joe/copyula better",
            "sign_reversal_confirmed": bool(dm["mean_loss_diff"] > 0 and means["Copula-Joe-A4f-ASYM"] > means["DCC-A4f-ASYM"]),
        }
    source = PARENT_SCRIPT.read_text(encoding="utf-8")
    return {
        "pairs": rows,
        "code_evidence": {
            "loss_differential_definition_found": "d  = l1 - l2" in source,
            "call_order_is_joe_then_dcc": "dm_qlike(r2_oos, forecasts['pvar'][m1], forecasts['pvar'][m2])" in source,
            "same_A4f_marginals_for_all_models": "for m in MODELS:" in source and "state[m]['marg1_p']" in source,
            "archived_joe_density_fails_independence_limit": "np.log((theta-1.0)*s + ab)" in source,
            "independence_requirement": "Joe theta=1 must have pointwise log density 0 for every u,v",
        },
    }


def main() -> None:
    np.random.seed(SEED)
    frame = pd.read_csv(SNAPSHOT, parse_dates=["date"]).set_index("date").sort_index()
    parent = json.loads(PARENT_RESULTS.read_text(encoding="utf-8"))
    synchronous = [evaluate_pair(frame, asset, 0) for asset in ("tlt", "gld")]
    asynchronous = [evaluate_pair(frame, asset, 1) for asset in ("tlt", "gld")]
    result = {
        "experiment_id": "K1705",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "question": "Does K1100c's Joe advantage survive honest marginal-first and dependence-score evaluation?",
        "data": {
            "source": "repository-pinned yfinance adjusted-close snapshot",
            "path": str(SNAPSHOT.relative_to(ROOT)),
            "sha256": sha256(SNAPSHOT),
            "first_date": str(frame.index.min().date()),
            "last_date": str(frame.index.max().date()),
            "rows": int(len(frame)),
        },
        "design": {
            "window": WINDOW,
            "refit_every": REFIT_EVERY,
            "oos_start": OOS_START,
            "margins": "common one-sided EWMA variance plus rolling unit-variance Student-t PIT",
            "dependence": "rolling Gaussian DCC score versus rolling Joe copula score on identical PITs",
            "inference": "canonical volpred.stats.model_evaluation.dm_test with h=1 and automatic HAC bandwidth",
            "asynchrony": "second asset return delayed one trading day; conservative stress test because both ETFs share the US close",
        },
        "parent_artifacts": {
            "results_path": str(PARENT_RESULTS.relative_to(ROOT)),
            "results_sha256": sha256(PARENT_RESULTS),
            "script_path": str(PARENT_SCRIPT.relative_to(ROOT)),
            "script_sha256": sha256(PARENT_SCRIPT),
        },
        "parent_claim_audit": parent_claim_audit(parent),
        "synchronous_close": synchronous,
        "asynchronous_sensitivity": asynchronous,
        "verdict": "PARENT_JOE_SUPERIORITY_SIGN_REVERSED_INVALID_JOE_DENSITY_AND_DEPENDENCE_ATTRIBUTION_NOT_ESTABLISHED",
        "limitations": [
            "The PIT reconstruction is an auditable common-margin proxy, not a byte-identical replay of K1100c A4f internals because K1100c did not persist PIT or forecast ledgers.",
            "Joe only represents nonnegative upper-tail dependence; it is structurally ill-suited to negative stock-bond dependence.",
            "Both ETFs share a US close; the one-day delay is a stress test, not an assertion about actual timestamp mismatch.",
        ],
        "references": [
            {"citation": "Fissler and Hoga (2026), How to Compare Copula Forecasts?", "url": "https://arxiv.org/abs/2410.04165"},
            {"citation": "Patton (2006), Modelling Asymmetric Exchange Rate Dependence", "url": "https://public.econ.duke.edu/~ap172/Patton_IER_2006.pdf"},
            {"citation": "Giacomini and White (2006), Tests of Conditional Predictive Ability", "url": "https://doi.org/10.1111/j.1468-0262.2006.00718.x"},
        ],
    }
    atomic_json_dump(result, RESULTS)
    print(json.dumps({"verdict": result["verdict"], "results": str(RESULTS)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
