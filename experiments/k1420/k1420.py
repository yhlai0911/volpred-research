"""
K1420: Regime-Weighted Conformal VaR (RWC)

Offline local replication using SPY and 0050.TW daily close data already in repo.
Forecast target is next-day 5% VaR/ES. Every forecast at date t uses only data
through t-1:
  - GJR variance forecast updates on realized return_{t-1}
  - HMM regime probability predicts state_t from filtered posterior_{t-1}
  - conformal calibration window uses standardized losses observed through t-1

Models:
  1. GJR-Normal
  2. GJR-Student-t
  3. Plain conformal on GJR-N standardized losses
  4. Regime-weighted conformal (3-state HMM on |returns|)
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model
from arch.univariate import StudentsT
from hmmlearn.hmm import GaussianHMM
from scipy.stats import chi2, norm


np.random.seed(42)
logging.getLogger("hmmlearn").setLevel(logging.ERROR)

EXPERIMENT_ID = "K1420"
ALPHA = 0.05
TRAIN_START = "2012-01-01"
TRAIN_END = "2022-12-31"
TEST_END = "2025-12-31"
ROLLING_WINDOW = 2000
CAL_WINDOW = 500
REFIT_EVERY = 63
HMM_STATES = 3
HMM_MULTISTART = 20
MIN_STATE_CAL_SAMPLES = 20

ROOT = Path(__file__).resolve().parent
RESULTS_PATH = ROOT / "k1420_results.json"

ASSET_CONFIG = {
    "SPY": ROOT.parent / "k1206" / "data" / "SPY.csv",
    "0050.TW": ROOT.parent / "k1411" / "data" / "T0050.csv",
}


@dataclass
class GJRFit:
    omega: float
    alpha: float
    gamma: float
    beta: float
    nu: float | None
    sigma_is: np.ndarray
    sigma_next: float


def load_asset(asset: str, path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").drop_duplicates("Date")
    df = df.loc[(df["Date"] >= TRAIN_START) & (df["Date"] <= TEST_END), ["Date", "Close"]].copy()
    df["ret"] = np.log(df["Close"] / df["Close"].shift(1))
    df = df.replace([np.inf, -np.inf], np.nan).dropna().reset_index(drop=True)
    df["ret"] = df["ret"].clip(-0.20, 0.20)
    df["asset"] = asset
    return df


def fit_gjr(returns: np.ndarray, dist: str) -> GJRFit:
    am = arch_model(
        returns * 100.0,
        mean="Zero",
        vol="GARCH",
        p=1,
        o=1,
        q=1,
        dist=dist,
        rescale=False,
    )
    fit = am.fit(disp="off", show_warning=False)
    sigma_is = np.asarray(fit.conditional_volatility, dtype=float) / 100.0
    params = fit.params
    nu = float(params.get("nu")) if "nu" in params.index else None
    h_last = sigma_is[-1] ** 2
    ret_last = returns[-1]
    omega = float(params["omega"]) / 10000.0
    alpha = float(params["alpha[1]"])
    gamma = float(params["gamma[1]"])
    beta = float(params["beta[1]"])
    sigma_next = np.sqrt(
        max(
            omega
            + alpha * ret_last**2
            + gamma * ret_last**2 * float(ret_last < 0)
            + beta * h_last,
            1e-12,
        )
    )
    return GJRFit(
        omega=omega,
        alpha=alpha,
        gamma=gamma,
        beta=beta,
        nu=nu,
        sigma_is=sigma_is,
        sigma_next=float(sigma_next),
    )


def update_sigma_next(fit: GJRFit, realized_ret: float, prev_sigma_next: float) -> float:
    h_prev = prev_sigma_next**2
    h_next = (
        fit.omega
        + fit.alpha * realized_ret**2
        + fit.gamma * realized_ret**2 * float(realized_ret < 0)
        + fit.beta * h_prev
    )
    return float(np.sqrt(max(h_next, 1e-12)))


def fit_hmm(abs_returns: np.ndarray) -> tuple[GaussianHMM, np.ndarray]:
    x = abs_returns.reshape(-1, 1)
    best_model = None
    best_score = -np.inf
    for seed in range(HMM_MULTISTART):
        model = GaussianHMM(
            n_components=HMM_STATES,
            covariance_type="diag",
            n_iter=300,
            random_state=42 + seed,
        )
        try:
            model.fit(x)
            score = model.score(x)
            if np.isfinite(score) and score > best_score:
                best_score = score
                best_model = model
        except Exception:
            continue
    if best_model is None:
        raise RuntimeError("HMM fit failed for all multistarts.")

    means = best_model.means_.ravel()
    order = np.argsort(means)
    remap = np.empty_like(order)
    remap[order] = np.arange(HMM_STATES)
    return best_model, remap


def remap_probs(probs: np.ndarray, remap: np.ndarray) -> np.ndarray:
    return probs[:, remap]


def predicted_next_regime_probs(model: GaussianHMM, remap: np.ndarray, history_abs: np.ndarray) -> tuple[np.ndarray, int]:
    probs = model.predict_proba(history_abs.reshape(-1, 1))
    probs = remap_probs(probs, remap)
    trans = model.transmat_[remap][:, remap]
    next_probs = probs[-1] @ trans
    next_probs = np.clip(next_probs, 1e-12, None)
    next_probs = next_probs / next_probs.sum()
    return next_probs, int(np.argmax(probs[-1]))


def one_sided_loss_scores(returns: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    return -returns / np.maximum(sigma, 1e-12)


def weighted_tail_estimate(scores: np.ndarray, weights: np.ndarray, alpha: float) -> tuple[float, float]:
    mask = np.isfinite(scores) & np.isfinite(weights) & (weights > 0)
    s = scores[mask]
    w = weights[mask]
    if s.size == 0:
        return np.nan, np.nan
    order = np.argsort(s)
    s = s[order]
    w = w[order]
    w = w / w.sum()
    cdf = np.cumsum(w)
    q = float(np.interp(1 - alpha, cdf, s))
    tail_mask = s >= q
    tail_mean = float(np.average(s[tail_mask], weights=w[tail_mask])) if tail_mask.any() else q
    return q, tail_mean


def normal_var_es(sigma: float, alpha: float) -> tuple[float, float]:
    z = norm.ppf(alpha)
    var = sigma * z
    es = -sigma * norm.pdf(z) / alpha
    return float(var), float(es)


def student_t_var_es(sigma: float, nu: float, alpha: float) -> tuple[float, float]:
    dist = StudentsT()
    q = float(dist.ppf(alpha, [nu]))
    pm1 = float(dist.partial_moment(1, z=q, parameters=[nu]))
    var = sigma * q
    es = sigma * pm1 / alpha
    return float(var), float(es)


def kupiec_test(violations: np.ndarray, alpha: float) -> dict:
    n = len(violations)
    n1 = int(np.sum(violations))
    n0 = n - n1
    p_hat = n1 / n if n else np.nan
    if n == 0 or p_hat in (0, 1):
        return {"stat": 0.0, "p_value": 1.0, "rate": float(p_hat) if n else np.nan, "pass": True}
    stat = 2 * (n1 * np.log(p_hat / alpha) + n0 * np.log((1 - p_hat) / (1 - alpha)))
    p_value = 1 - chi2.cdf(stat, 1)
    return {"stat": float(stat), "p_value": float(p_value), "rate": float(p_hat), "pass": bool(p_value > 0.05)}


def christoffersen_test(violations: np.ndarray) -> dict:
    if len(violations) < 2:
        return {"stat": 0.0, "p_value": 1.0, "pass": True}
    n00 = n01 = n10 = n11 = 0
    for t in range(1, len(violations)):
        a, b = int(violations[t - 1]), int(violations[t])
        if a == 0 and b == 0:
            n00 += 1
        elif a == 0 and b == 1:
            n01 += 1
        elif a == 1 and b == 0:
            n10 += 1
        else:
            n11 += 1
    if (n00 + n01) == 0 or (n10 + n11) == 0:
        return {"stat": 0.0, "p_value": 1.0, "pass": True}
    pi01 = n01 / (n00 + n01)
    pi11 = n11 / (n10 + n11)
    pi = (n01 + n11) / (n00 + n01 + n10 + n11)
    if pi in (0, 1) or pi01 in (0, 1) or pi11 in (0, 1):
        return {"stat": 0.0, "p_value": 1.0, "pass": True}
    stat = 2 * (
        n00 * np.log((1 - pi01) / (1 - pi))
        + n01 * np.log(pi01 / pi)
        + n10 * np.log((1 - pi11) / (1 - pi))
        + n11 * np.log(pi11 / pi)
    )
    p_value = 1 - chi2.cdf(stat, 1)
    return {"stat": float(stat), "p_value": float(p_value), "pass": bool(p_value > 0.05)}


def dq_test(violations: np.ndarray, alpha: float, sigma: np.ndarray) -> dict:
    if len(violations) < 10:
        return {"stat": 0.0, "p_value": 1.0, "pass": True}
    hit = violations.astype(float) - alpha
    x = np.column_stack([np.ones(len(hit) - 1), hit[:-1], sigma[1:]])
    y = hit[1:]
    try:
        beta = np.linalg.inv(x.T @ x) @ x.T @ y
        stat = (beta.T @ x.T @ x @ beta) / (alpha * (1 - alpha))
        p_value = 1 - chi2.cdf(stat, x.shape[1])
        return {"stat": float(stat), "p_value": float(p_value), "pass": bool(p_value > 0.05)}
    except np.linalg.LinAlgError:
        return {"stat": 0.0, "p_value": 1.0, "pass": True}


def fz_score_series(returns: np.ndarray, var: np.ndarray, es: np.ndarray, alpha: float) -> np.ndarray:
    valid = np.isfinite(returns) & np.isfinite(var) & np.isfinite(es) & (var < 0) & (es < 0)
    r = returns[valid]
    v = var[valid]
    e = es[valid]
    indicator = (r <= v).astype(float)
    score = (1.0 / alpha) * indicator * (v - r) / (-e) - v / e + np.log(-e) - 1.0
    out = np.full_like(returns, np.nan, dtype=float)
    out[np.where(valid)[0]] = score
    return out


def dm_test(loss_1: np.ndarray, loss_2: np.ndarray) -> dict:
    valid = np.isfinite(loss_1) & np.isfinite(loss_2)
    d = loss_1[valid] - loss_2[valid]
    n = len(d)
    if n < 10:
        return {"t_stat": 0.0, "p_value": 1.0, "n": n, "significant_harvey": False, "mean_loss_diff": 0.0}
    d_bar = np.mean(d)
    max_lag = max(1, int(n ** (1 / 3)))
    nw_var = np.var(d, ddof=1)
    for k in range(1, max_lag + 1):
        weight = 1 - k / (max_lag + 1)
        gamma_k = np.cov(d[k:], d[:-k])[0, 1]
        nw_var += 2 * weight * gamma_k
    se = np.sqrt(max(nw_var / n, 1e-12))
    t_stat = d_bar / se
    p_value = 2 * norm.cdf(-abs(t_stat))
    return {
        "t_stat": float(t_stat),
        "p_value": float(p_value),
        "n": n,
        "significant_harvey": bool(abs(t_stat) > 3.0),
        "mean_loss_diff": float(d_bar),
    }


def evaluate_method(returns: np.ndarray, sigma: np.ndarray, var: np.ndarray, es: np.ndarray) -> dict:
    valid = np.isfinite(returns) & np.isfinite(var) & np.isfinite(es)
    r = returns[valid]
    s = sigma[valid]
    v = var[valid]
    e = es[valid]
    violations = r < v
    kup = kupiec_test(violations, ALPHA)
    cc = christoffersen_test(violations)
    dq = dq_test(violations, ALPHA, s)
    fz = fz_score_series(r, v, e, ALPHA)
    return {
        "n_oos": int(len(r)),
        "violations": int(violations.sum()),
        "violation_rate": float(np.mean(violations)),
        "kupiec": kup,
        "christoffersen": cc,
        "dq": dq,
        "mean_abs_var": float(np.mean(np.abs(v))),
        "mean_abs_es": float(np.mean(np.abs(e))),
        "mean_fz": float(np.nanmean(fz)),
        "fz_series": fz.tolist(),
    }


def run_asset(asset: str, df: pd.DataFrame) -> dict:
    split_date = pd.Timestamp(TRAIN_END)
    oos_idx = np.where(df["Date"] > split_date)[0]
    if len(oos_idx) == 0:
        raise ValueError(f"{asset}: empty OOS sample.")

    methods = ["gjr_normal", "gjr_t", "plain_conformal", "rwc"]
    ret_oos = df.loc[oos_idx, "ret"].to_numpy()
    date_oos = df.loc[oos_idx, "Date"].dt.strftime("%Y-%m-%d").to_list()
    store = {
        m: {
            "sigma": np.full(len(oos_idx), np.nan),
            "var": np.full(len(oos_idx), np.nan),
            "es": np.full(len(oos_idx), np.nan),
        }
        for m in methods
    }
    pred_regime = np.full(len(oos_idx), np.nan)
    pred_regime_probs = np.full((len(oos_idx), HMM_STATES), np.nan)

    cached = None
    for j, global_idx in enumerate(oos_idx):
        train_end_idx = global_idx - 1
        train_start_idx = max(0, train_end_idx - ROLLING_WINDOW + 1)
        train_returns = df.loc[train_start_idx:train_end_idx, "ret"].to_numpy()
        train_abs = np.abs(train_returns)

        if len(train_returns) < 252:
            continue

        if cached is None or j % REFIT_EVERY == 0:
            gjr_normal = fit_gjr(train_returns, "normal")
            gjr_t = fit_gjr(train_returns, "t")
            hmm_model, remap = fit_hmm(train_abs)

            sigma_n_next = gjr_normal.sigma_next
            sigma_t_next = gjr_t.sigma_next
            score_hist = list(one_sided_loss_scores(train_returns, gjr_normal.sigma_is))

            probs_train = remap_probs(hmm_model.predict_proba(train_abs.reshape(-1, 1)), remap)
            state_hist = list(np.argmax(probs_train, axis=1))
            cached = {
                "gjr_normal": gjr_normal,
                "gjr_t": gjr_t,
                "hmm_model": hmm_model,
                "remap": remap,
                "sigma_n_next": sigma_n_next,
                "sigma_t_next": sigma_t_next,
                "score_hist": score_hist,
                "state_hist": state_hist,
                "history_abs": list(train_abs),
            }

        next_probs, last_state = predicted_next_regime_probs(
            cached["hmm_model"],
            cached["remap"],
            np.asarray(cached["history_abs"], dtype=float),
        )
        pred_regime[j] = int(np.argmax(next_probs))
        pred_regime_probs[j] = next_probs

        score_arr = np.asarray(cached["score_hist"], dtype=float)
        state_arr = np.asarray(cached["state_hist"], dtype=int)
        hist_slice = slice(max(0, len(score_arr) - CAL_WINDOW), len(score_arr))
        score_recent = score_arr[hist_slice]
        state_recent = state_arr[hist_slice]
        plain_q, plain_tail = weighted_tail_estimate(score_recent, np.ones_like(score_recent), ALPHA)

        state_q = np.full(HMM_STATES, np.nan)
        state_tail = np.full(HMM_STATES, np.nan)
        for state in range(HMM_STATES):
            mask = state_recent == state
            if mask.sum() >= MIN_STATE_CAL_SAMPLES:
                q_s, es_s = weighted_tail_estimate(score_recent[mask], np.ones(mask.sum()), ALPHA)
                state_q[state] = q_s
                state_tail[state] = es_s
            else:
                state_q[state] = plain_q
                state_tail[state] = plain_tail
        rwc_q = float(np.sum(next_probs * state_q))
        rwc_tail = float(np.sum(next_probs * state_tail))

        sigma_n = cached["sigma_n_next"]
        sigma_t = cached["sigma_t_next"]

        var_n, es_n = normal_var_es(sigma_n, ALPHA)
        var_t, es_t = student_t_var_es(sigma_t, cached["gjr_t"].nu, ALPHA)
        var_plain, es_plain = -sigma_n * plain_q, -sigma_n * plain_tail
        var_rwc, es_rwc = -sigma_n * rwc_q, -sigma_n * rwc_tail

        store["gjr_normal"]["sigma"][j] = sigma_n
        store["gjr_normal"]["var"][j] = var_n
        store["gjr_normal"]["es"][j] = es_n
        store["gjr_t"]["sigma"][j] = sigma_t
        store["gjr_t"]["var"][j] = var_t
        store["gjr_t"]["es"][j] = es_t
        store["plain_conformal"]["sigma"][j] = sigma_n
        store["plain_conformal"]["var"][j] = var_plain
        store["plain_conformal"]["es"][j] = es_plain
        store["rwc"]["sigma"][j] = sigma_n
        store["rwc"]["var"][j] = var_rwc
        store["rwc"]["es"][j] = es_rwc

        realized_ret = ret_oos[j]
        realized_abs = abs(realized_ret)
        realized_state = predicted_next_regime_probs(
            cached["hmm_model"],
            cached["remap"],
            np.asarray(cached["history_abs"] + [realized_abs], dtype=float),
        )[1]
        cached["history_abs"].append(realized_abs)
        cached["score_hist"].append(-realized_ret / max(sigma_n, 1e-12))
        cached["state_hist"].append(realized_state)
        cached["sigma_n_next"] = update_sigma_next(cached["gjr_normal"], realized_ret, sigma_n)
        cached["sigma_t_next"] = update_sigma_next(cached["gjr_t"], realized_ret, sigma_t)

    evaluations = {}
    for method in methods:
        evaluations[method] = evaluate_method(
            ret_oos,
            store[method]["sigma"],
            store[method]["var"],
            store[method]["es"],
        )

    fz_base = np.asarray(evaluations["gjr_normal"]["fz_series"], dtype=float)
    dm_vs_base = {}
    for method in ["gjr_t", "plain_conformal", "rwc"]:
        dm_vs_base[method] = dm_test(
            fz_base,
            np.asarray(evaluations[method]["fz_series"], dtype=float),
        )

    regime_rates = {}
    for method in methods:
        valid = np.isfinite(store[method]["var"])
        viol = ret_oos[valid] < store[method]["var"][valid]
        regime = pred_regime[valid].astype(int)
        regime_rates[method] = {}
        for state in range(HMM_STATES):
            mask = regime == state
            regime_rates[method][f"state_{state}"] = {
                "n": int(mask.sum()),
                "violation_rate": float(np.mean(viol[mask])) if mask.any() else np.nan,
            }

    summary = {
        "asset": asset,
        "sample": {
            "n_total": int(len(df)),
            "n_oos": int(len(oos_idx)),
            "train_start": TRAIN_START,
            "train_end": TRAIN_END,
            "test_end": TEST_END,
            "first_oos_date": date_oos[0],
            "last_oos_date": date_oos[-1],
        },
        "config": {
            "alpha": ALPHA,
            "rolling_window": ROLLING_WINDOW,
            "cal_window": CAL_WINDOW,
            "refit_every": REFIT_EVERY,
            "hmm_states": HMM_STATES,
            "hmm_multistart": HMM_MULTISTART,
            "lookahead_policy": "all forecasts use information through t-1 only",
        },
        "methods": evaluations,
        "dm_vs_gjr_normal_fz": dm_vs_base,
        "predicted_regime_violation_rates": regime_rates,
    }
    return summary


def build_verdict(results: dict) -> dict:
    passes = []
    notes = []
    for asset, res in results["assets"].items():
        base = res["methods"]["plain_conformal"]
        rwc = res["methods"]["rwc"]
        better_cc = rwc["christoffersen"]["p_value"] >= base["christoffersen"]["p_value"]
        close_uc = abs(rwc["violation_rate"] - ALPHA) <= 0.015
        harvey = res["dm_vs_gjr_normal_fz"]["rwc"]["significant_harvey"]
        passes.append(bool(better_cc and close_uc))
        notes.append(
            {
                "asset": asset,
                "rwc_close_to_nominal": close_uc,
                "rwc_cc_not_worse_than_plain": better_cc,
                "rwc_dm_harvey_vs_gjr_normal": harvey,
            }
        )
    success = sum(passes) >= 1
    return {
        "success_rule": "RWC improves or matches CC vs plain conformal and keeps |violation_rate-0.05|<=0.015 in at least 1 asset",
        "pass_count": int(sum(passes)),
        "n_assets": len(passes),
        "verdict": "PARTIAL_PASS" if success else "NULL_RESULT",
        "asset_checks": notes,
    }


def main() -> None:
    assets = {asset: load_asset(asset, path) for asset, path in ASSET_CONFIG.items()}
    asset_results = {asset: run_asset(asset, df) for asset, df in assets.items()}
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "seed": 42,
        "references": [
            "Regime-Weighted Conformal VaR (arXiv:2602.03903)",
            "Kupiec (1995)",
            "Christoffersen (1998)",
            "Engle and Manganelli (2004)",
            "Fissler and Ziegel (2016)",
        ],
        "assets": asset_results,
        "verdict": {},
        "caveats": [
            "Uses local close-only daily data already stored in repo; no live yfinance refresh.",
            "Regime weighting is based on 3-state Gaussian HMM over |returns|, not on VIX.",
            "Conformal overlays use GJR-N volatility as the sigma backbone for standardized losses.",
            "No multiple-alpha sweep in this first pass; only alpha=5%.",
        ],
    }
    payload["verdict"] = build_verdict(payload)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2))
    print(json.dumps(payload["verdict"], indent=2))


if __name__ == "__main__":
    main()
