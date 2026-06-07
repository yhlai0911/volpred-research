"""K1421 — HAR-RV Quantile Forecasting Cross-Asset Robustness on Commodities
(GLD / USO / UNG)

Extension of K1403 (QQQ/GLD/TLT). Tests whether commodity ETFs exhibit stronger
quantile-asymmetry than the equity-bond baseline (hypothesis:
USO/UNG (energy) > GLD (gold) > SPY-baseline).

Pipeline:
  1. HAR-RV (Corsi 2009) on Garman-Klass realized vol proxy, 2012-2025
  2. OLS baseline + Koenker-Bassett 1978 QuantReg at tau in {0.05,0.50,0.95}
  3. IS 2012-2020 / OOS 2021-today, fixed-origin (single fit)
  4. Per-asset Pinball loss, Kupiec UC, DM test (Harvey HLN) vs OLS at q50
  5. Asymmetry metric: ratio of upper-tail pinball spread to lower-tail
  6. Joint cross-asset stationary bootstrap (Politis-Romano 1994),
     seed=42, n_boot=1000, average block length L = ceil(n^{1/3})

Output: experiments/k1421/k1421_results.json
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
import statsmodels.api as sm
from statsmodels.regression.quantile_regression import QuantReg

ASSETS = ["GLD", "USO", "UNG"]
DATA_START = "2012-01-03"
OOS_START = "2021-01-04"
QUANTILES = [0.05, 0.50, 0.95]
SEED = 42
N_BOOT = 1000

ROOT = Path(__file__).parent
RESULTS_PATH = ROOT / "k1421_results.json"
CACHE_DIR = ROOT / "data"

np.random.seed(SEED)


# ---------- Data ----------
def load_asset(asset: str) -> pd.DataFrame:
    """Return DataFrame with Open/High/Low/Close for Garman-Klass proxy."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache = CACHE_DIR / f"{asset}.csv"
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df.sort_index()
    import yfinance as yf
    df = yf.download(asset, start=DATA_START, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {asset}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    keep = [c for c in ["Open", "High", "Low", "Close"] if c in df.columns]
    if len(keep) < 4:
        raise RuntimeError(f"{asset}: missing OHLC columns: {df.columns.tolist()}")
    df = df[keep].astype(float)
    df.to_csv(cache)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()


def garman_klass_rv(df: pd.DataFrame) -> pd.Series:
    """Garman-Klass (1980) realized variance proxy (daily, in pct units).
    GK = 0.5 * (log(H/L))^2 - (2*log(2)-1) * (log(C/O))^2
    Returned as sqrt(GK) * 100 (daily realized vol in pct), same scale as |r| pct.
    """
    log_hl = np.log(df["High"] / df["Low"])
    log_co = np.log(df["Close"] / df["Open"])
    gk_var = 0.5 * log_hl**2 - (2.0 * math.log(2.0) - 1.0) * log_co**2
    # Floor at small positive to avoid sqrt of tiny negatives from rounding
    gk_var = gk_var.clip(lower=1e-12)
    rv = np.sqrt(gk_var) * 100.0
    rv.name = "gk_rv_pct"
    return rv


def build_har_panel(rv: pd.Series) -> pd.DataFrame:
    rv_d = rv.shift(1)
    rv_w = rv.rolling(5).mean().shift(1)
    rv_m = rv.rolling(22).mean().shift(1)
    df = pd.DataFrame({
        "daily_rv": rv,
        "rv_d": rv_d,
        "rv_w": rv_w,
        "rv_m": rv_m,
    }).dropna()
    return df


# ---------- Metrics ----------
def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, tau: float) -> float:
    diff = y_true - y_pred
    return float(np.mean(np.maximum(tau * diff, (tau - 1.0) * diff)))


def pinball_series(y_true: np.ndarray, y_pred: np.ndarray, tau: float) -> np.ndarray:
    diff = y_true - y_pred
    return np.maximum(tau * diff, (tau - 1.0) * diff)


def kupiec_uc(violations: int, n: int, p_nominal: float) -> dict:
    p_hat = violations / n if n > 0 else 0.0
    eps = 1e-12
    p_hat_safe = min(max(p_hat, eps), 1 - eps)
    ll_null = (
        violations * math.log(p_nominal)
        + (n - violations) * math.log(1.0 - p_nominal)
    )
    ll_alt = (
        violations * math.log(p_hat_safe)
        + (n - violations) * math.log(1.0 - p_hat_safe)
    )
    lr = -2.0 * (ll_null - ll_alt)
    p_value = 1.0 - stats.chi2.cdf(lr, df=1)
    return {
        "violations": int(violations),
        "n": int(n),
        "p_hat": float(p_hat),
        "p_nominal": float(p_nominal),
        "lr_stat": float(lr),
        "p_value": float(p_value),
    }


def dm_test_hln(loss_a: np.ndarray, loss_b: np.ndarray, h: int = 1) -> dict:
    """Diebold-Mariano with Harvey-Leybourne-Newbold small-sample correction."""
    d = loss_a - loss_b
    n = len(d)
    if n < 5:
        return {"dm_stat": float("nan"), "p_value": float("nan"), "n": int(n)}
    d_mean = float(np.mean(d))
    gamma0 = float(np.var(d, ddof=0))
    var_d = gamma0
    for lag in range(1, h):
        gl = float(np.mean((d[lag:] - d_mean) * (d[:-lag] - d_mean)))
        var_d += 2.0 * gl
    var_d = max(var_d, 1e-12)
    dm = d_mean / math.sqrt(var_d / n)
    k = math.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    dm_hln = dm * k
    p_value = 2.0 * (1.0 - stats.t.cdf(abs(dm_hln), df=n - 1))
    return {
        "dm_stat": float(dm_hln),
        "p_value": float(p_value),
        "n": int(n),
        "mean_diff": d_mean,
    }


# ---------- Asymmetry metric ----------
def asymmetry_score(qres: dict) -> dict:
    """Quantile asymmetry: upper-tail (q95) pinball normalized by q50 pinball
    minus lower-tail (q05) normalized by q50.

    Higher absolute value -> more asymmetric tail behaviour.
    Sign tells us which tail is harder to predict (positive -> upper harder).
    """
    p05 = qres["q05"]["pinball_loss_oos"]
    p50 = qres["q50"]["pinball_loss_oos"]
    p95 = qres["q95"]["pinball_loss_oos"]
    if p50 <= 0:
        return {
            "upper_ratio": float("nan"),
            "lower_ratio": float("nan"),
            "asymmetry": float("nan"),
        }
    upper_ratio = p95 / p50
    lower_ratio = p05 / p50
    return {
        "upper_ratio": float(upper_ratio),
        "lower_ratio": float(lower_ratio),
        "asymmetry": float(upper_ratio - lower_ratio),
    }


# ---------- Per-asset run ----------
def run_asset(asset: str) -> dict:
    px = load_asset(asset)
    rv = garman_klass_rv(px)
    panel = build_har_panel(rv)
    oos_start = pd.Timestamp(OOS_START)
    train_mask = panel.index < oos_start
    oos_mask = panel.index >= oos_start
    if oos_mask.sum() < 50:
        raise RuntimeError(
            f"{asset}: insufficient OOS samples ({int(oos_mask.sum())})"
        )

    X_train = sm.add_constant(panel.loc[train_mask, ["rv_d", "rv_w", "rv_m"]])
    y_train = panel.loc[train_mask, "daily_rv"].values
    X_oos = sm.add_constant(panel.loc[oos_mask, ["rv_d", "rv_w", "rv_m"]])
    y_oos = panel.loc[oos_mask, "daily_rv"].values
    oos_index = panel.loc[oos_mask].index

    ols = sm.OLS(y_train, X_train).fit()
    yhat_ols = np.asarray(ols.predict(X_oos))

    quantile_results: dict[str, dict] = {}
    yhat_q: dict[float, np.ndarray] = {}
    for tau in QUANTILES:
        qr = QuantReg(y_train, X_train).fit(q=tau, max_iter=5000)
        yhat_tau = np.asarray(qr.predict(X_oos))
        yhat_q[tau] = yhat_tau

        loss_tau = pinball_loss(y_oos, yhat_tau, tau)
        emp_cov_below = float(np.mean(y_oos <= yhat_tau))
        if tau >= 0.5:
            violations = int(np.sum(y_oos > yhat_tau))
            p_nominal = 1.0 - tau
        else:
            violations = int(np.sum(y_oos < yhat_tau))
            p_nominal = tau
        kupiec = kupiec_uc(violations=violations, n=len(y_oos), p_nominal=p_nominal)
        quantile_results[f"q{int(tau * 100):02d}"] = {
            "tau": tau,
            "params": {k: float(v) for k, v in qr.params.to_dict().items()},
            "pinball_loss_oos": loss_tau,
            "empirical_coverage_below": emp_cov_below,
            "nominal_coverage": tau,
            "coverage_gap_pp": float((emp_cov_below - tau) * 100.0),
            "kupiec_uc": kupiec,
        }

    # DM tests vs OLS for q05 / q50 / q95 pinball
    pin_ols_q05 = pinball_series(y_oos, yhat_ols, 0.05)
    pin_qr_q05 = pinball_series(y_oos, yhat_q[0.05], 0.05)
    dm_q05 = dm_test_hln(pin_ols_q05, pin_qr_q05, h=1)

    pin_ols_q50 = pinball_series(y_oos, yhat_ols, 0.50)
    pin_qr_q50 = pinball_series(y_oos, yhat_q[0.50], 0.50)
    dm_q50 = dm_test_hln(pin_ols_q50, pin_qr_q50, h=1)

    pin_ols_q95 = pinball_series(y_oos, yhat_ols, 0.95)
    pin_qr_q95 = pinball_series(y_oos, yhat_q[0.95], 0.95)
    dm_q95 = dm_test_hln(pin_ols_q95, pin_qr_q95, h=1)

    asym = asymmetry_score(quantile_results)

    # Store loss diffs (OLS - QR) for joint bootstrap downstream
    loss_diff_q05 = (pin_ols_q05 - pin_qr_q05).tolist()
    loss_diff_q50 = (pin_ols_q50 - pin_qr_q50).tolist()
    loss_diff_q95 = (pin_ols_q95 - pin_qr_q95).tolist()

    return {
        "asset": asset,
        "n_train": int(train_mask.sum()),
        "n_oos": int(oos_mask.sum()),
        "oos_first_date": str(oos_index.min().date()),
        "oos_last_date": str(oos_index.max().date()),
        "ols_baseline": {
            "ols_params": {k: float(v) for k, v in ols.params.to_dict().items()},
            "pinball_at_tau_0.05": pinball_loss(y_oos, yhat_ols, 0.05),
            "pinball_at_tau_0.50": pinball_loss(y_oos, yhat_ols, 0.50),
            "pinball_at_tau_0.95": pinball_loss(y_oos, yhat_ols, 0.95),
        },
        "quantile_forecasts": quantile_results,
        "dm_qr_vs_ols": {
            "q05": dm_q05,
            "q50": dm_q50,
            "q95": dm_q95,
        },
        "asymmetry": asym,
        "loss_diffs_for_bootstrap": {
            "q05": loss_diff_q05,
            "q50": loss_diff_q50,
            "q95": loss_diff_q95,
        },
    }


# ---------- Stationary bootstrap (Politis-Romano 1994) ----------
def stationary_bootstrap_resample(rng: np.random.Generator, n: int, mean_block: float) -> np.ndarray:
    """Return resampled indices of length n using geometric block lengths."""
    p = 1.0 / max(mean_block, 1.0)
    idx = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        start = int(rng.integers(0, n))
        # geometric block length (>=1)
        # numpy geometric returns >=1
        L = int(rng.geometric(p))
        for k in range(L):
            if i >= n:
                break
            idx[i] = (start + k) % n
            i += 1
    return idx


def joint_bootstrap(per_asset: list[dict]) -> dict:
    """Joint test across 3 commodity assets via stationary bootstrap.

    H0: mean(OLS_pinball - QR_pinball) <= 0 jointly (QR no better than OLS)
    averaged across the 3 assets per quantile.

    For each quantile tau, compute the test statistic
        T = mean over assets of mean(loss_diff_a)
    A positive T means QR uniformly improves over OLS in the joint pool.
    Bootstrap p-value: P( T* >= T_obs ) under stationary bootstrap
    of the loss diffs (one-sided test for QR improvement).
    """
    rng = np.random.default_rng(SEED)
    diffs_by_q: dict[str, list[np.ndarray]] = {"q05": [], "q50": [], "q95": []}
    for r in per_asset:
        for q in diffs_by_q:
            diffs_by_q[q].append(np.asarray(r["loss_diffs_for_bootstrap"][q]))

    results = {}
    for q, asset_arrs in diffs_by_q.items():
        means_obs = np.array([float(np.mean(a)) for a in asset_arrs])
        T_obs = float(np.mean(means_obs))
        boot_T = np.empty(N_BOOT, dtype=np.float64)
        for b in range(N_BOOT):
            b_means = []
            for a in asset_arrs:
                n_a = len(a)
                L_a = max(2.0, math.ceil(n_a ** (1.0 / 3.0)))
                idx = stationary_bootstrap_resample(rng, n_a, L_a)
                b_means.append(float(np.mean(a[idx])))
            boot_T[b] = float(np.mean(b_means))
        # one-sided: P(T* >= T_obs) under recentered null
        # null distribution: boot_T - T_obs (centered) shifted by 0 (null)
        # so p_value = mean( (boot_T - T_obs) >= T_obs ) wait, standard hyp test:
        # we test H0: T = 0. p_one_sided = mean( boot_T_centered >= T_obs )
        boot_T_centered = boot_T - T_obs
        p_one_sided = float(np.mean(boot_T_centered >= T_obs))
        # Two-sided p for reporting
        p_two_sided = float(np.mean(np.abs(boot_T_centered) >= abs(T_obs)))
        ci_low = float(np.quantile(boot_T, 0.025))
        ci_high = float(np.quantile(boot_T, 0.975))
        results[q] = {
            "T_obs": T_obs,
            "per_asset_means": [float(m) for m in means_obs],
            "p_one_sided": p_one_sided,
            "p_two_sided": p_two_sided,
            "boot_ci95": [ci_low, ci_high],
            "n_boot": int(N_BOOT),
        }
    return results


# ---------- Verdicts ----------
def classify_per_asset(r: dict) -> dict:
    """Per-asset classification:
      PASS:           DM(q05) sig pos (p<0.10) AND Kupiec q05 PASS
      CONDITIONAL:    DM(q05) NS AND Kupiec q05 PASS AND coverage_gap<=5pp
      NULL:           otherwise
    """
    dm05 = r["dm_qr_vs_ols"]["q05"]
    q05 = r["quantile_forecasts"]["q05"]
    kupiec_pass = q05["kupiec_uc"]["p_value"] > 0.05
    gap = abs(q05["coverage_gap_pp"])
    reasons = []
    if dm05["p_value"] < 0.10 and dm05["dm_stat"] > 0 and kupiec_pass:
        reasons.append(f"DM(q05) sig POS (stat={dm05['dm_stat']:.2f} p={dm05['p_value']:.3f}); Kupiec PASS")
        return {"label": "PASS", "reasons": reasons}
    if dm05["p_value"] >= 0.10 and kupiec_pass and gap <= 5.0:
        reasons.append(f"DM(q05) NS (p={dm05['p_value']:.3f}); Kupiec PASS; gap={gap:.2f}pp")
        return {"label": "CONDITIONAL_PASS", "reasons": reasons}
    if not kupiec_pass:
        reasons.append(f"Kupiec q05 reject (p={q05['kupiec_uc']['p_value']:.3f})")
    if gap > 5.0:
        reasons.append(f"q05 coverage gap > 5pp ({gap:.2f}pp)")
    if dm05["p_value"] < 0.10 and dm05["dm_stat"] < 0:
        reasons.append(f"DM(q05) sig NEG (stat={dm05['dm_stat']:.2f})")
    return {"label": "NULL", "reasons": reasons}


# SPY baseline asymmetry from K1402 / K1403 (reference value, NOT used as test
# since we want a self-contained K1421 score). Hypothesis quote from brief.
SPY_BASELINE_ASYMMETRY_REF = 0.0  # placeholder; comparison done descriptively


def aggregate_verdict(per_asset: list[dict], joint: dict) -> dict:
    """Aggregate verdict per K1421 success criteria:
      Success #1 (descriptive): >=2/3 commodities show |asymmetry| > 1.5*SPY baseline
      Success #2 (formal):      >=1/3 has DM(q05) p<0.10 with positive stat
    """
    asym_scores = [abs(r["asymmetry"]["asymmetry"]) for r in per_asset]
    n_asym_high = sum(1 for s in asym_scores if s > 1.5 * max(SPY_BASELINE_ASYMMETRY_REF, 0.5))
    # Use raw threshold 0.75 as 1.5x typical baseline ~0.5 -> placeholder gate.
    # We separately report all asymmetry scores so the K1421 article can
    # compare with K1403 / K1402 SPY numbers after the fact.

    n_dm_sig_pos_q05 = sum(
        1 for r in per_asset
        if r["dm_qr_vs_ols"]["q05"]["p_value"] < 0.10 and r["dm_qr_vs_ols"]["q05"]["dm_stat"] > 0
    )
    n_dm_sig_pos_any = sum(
        1 for r in per_asset
        if any(
            r["dm_qr_vs_ols"][q]["p_value"] < 0.10 and r["dm_qr_vs_ols"][q]["dm_stat"] > 0
            for q in ("q05", "q50", "q95")
        )
    )
    joint_q05 = joint["q05"]

    if n_dm_sig_pos_q05 >= 1 and joint_q05["p_one_sided"] < 0.10:
        label = "PASS"
        reason = (
            f"{n_dm_sig_pos_q05}/3 assets DM(q05) sig POS + joint bootstrap "
            f"p_one_sided={joint_q05['p_one_sided']:.3f} < 0.10 → commodity tail forecasting improvement"
        )
    elif n_dm_sig_pos_any >= 1:
        label = "CONDITIONAL_PASS"
        reason = (
            f"At least one asset/quantile DM sig POS but joint NS "
            f"(joint q05 p={joint_q05['p_one_sided']:.3f}) → partial improvement"
        )
    elif n_asym_high >= 2:
        label = "DESCRIPTIVE_ASYMMETRY"
        reason = (
            f"{n_asym_high}/3 commodities show high asymmetry (>0.75) "
            "but no formal DM improvement → descriptive finding only"
        )
    else:
        label = "NULL"
        reason = (
            f"No formal DM improvement (q05 sig={n_dm_sig_pos_q05}/3, any={n_dm_sig_pos_any}/3); "
            f"asymmetry high count={n_asym_high}/3 → null result"
        )
    return {
        "label": label,
        "reason": reason,
        "n_dm_sig_pos_q05": int(n_dm_sig_pos_q05),
        "n_dm_sig_pos_any_quantile": int(n_dm_sig_pos_any),
        "n_asymmetry_high": int(n_asym_high),
        "asymmetry_scores": [float(s) for s in asym_scores],
        "joint_q05_p_one_sided": joint_q05["p_one_sided"],
    }


def main() -> dict:
    per_asset = [run_asset(a) for a in ASSETS]
    joint = joint_bootstrap(per_asset)
    # attach per-asset verdicts AFTER bootstrap (verdict uses precomputed fields)
    for r in per_asset:
        v = classify_per_asset(r)
        r["verdict"] = v["label"]
        r["verdict_reasons"] = v["reasons"]
    agg = aggregate_verdict(per_asset, joint)

    # Drop bulky loss_diffs from output to keep JSON manageable
    per_asset_clean = []
    for r in per_asset:
        rc = {k: v for k, v in r.items() if k != "loss_diffs_for_bootstrap"}
        per_asset_clean.append(rc)

    out = {
        "experiment_id": "K1421",
        "title": "HAR-Quantile Cross-Asset Robustness on Commodities (GLD/USO/UNG)",
        "assets": ASSETS,
        "data_start": DATA_START,
        "oos_start": OOS_START,
        "per_asset": per_asset_clean,
        "joint_bootstrap": joint,
        "aggregate_verdict": agg,
        "config": {
            "seed": SEED,
            "n_boot": N_BOOT,
            "quantiles": QUANTILES,
            "rv_proxy": "Garman-Klass (1980)",
            "model": "HAR-RV + statsmodels.QuantReg (Koenker-Bassett 1978)",
            "refit": "none (single fixed-origin fit, IS pre-2021)",
            "bootstrap_method": "Politis-Romano stationary bootstrap, L=ceil(n^{1/3})",
            "extends": "K1403 (QQQ/GLD/TLT) → commodity asset class",
            "reference_baseline_assets": "K1402 (SPY), K1403 (QQQ/GLD/TLT)",
        },
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(json.dumps({
        "experiment_id": out["experiment_id"],
        "aggregate_label": agg["label"],
        "per_asset_verdicts": {r["asset"]: r["verdict"] for r in per_asset_clean},
        "asymmetry_scores": agg["asymmetry_scores"],
        "joint_q05_p": joint["q05"]["p_one_sided"],
    }, indent=2))
    return out


if __name__ == "__main__":
    main()
