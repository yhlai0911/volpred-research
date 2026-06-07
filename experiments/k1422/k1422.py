"""K1422 — HAR-Quantile commodity rerun with fair baselines.

Fixes the two blocking issues from K1421:
1. Replace unfair OLS-point-vs-QR tail comparison with fair quantile baselines
   that use the same HAR features but produce valid conditional quantiles.
2. Replace the joint bootstrap p-value with a centered-null bootstrap test.

Assets: GLD / USO / UNG
IS: 2012-01-03 to 2020-12-31
OOS: 2021-01-04 onward
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
TAILS = ["q05", "q95"]
SEED = 42
N_BOOT = 1000
P_SIG = 0.10

ROOT = Path(__file__).parent
RESULTS_PATH = ROOT / "k1422_results.json"
CACHE_DIR = ROOT / "data"
K1421_CACHE_DIR = ROOT.parent / "k1421" / "data"


def load_asset(asset: str) -> pd.DataFrame:
    """Load cached OHLC data, falling back to K1421 cache or yfinance."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_cache = CACHE_DIR / f"{asset}.csv"
    prior_cache = K1421_CACHE_DIR / f"{asset}.csv"
    cache = local_cache if local_cache.exists() else prior_cache
    if cache.exists():
        df = pd.read_csv(cache, index_col=0, parse_dates=True)
        df.index = pd.to_datetime(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        if cache != local_cache:
            df.to_csv(local_cache)
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
    df.to_csv(local_cache)
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.sort_index()


def garman_klass_rv(df: pd.DataFrame) -> pd.Series:
    log_hl = np.log(df["High"] / df["Low"])
    log_co = np.log(df["Close"] / df["Open"])
    gk_var = 0.5 * log_hl**2 - (2.0 * math.log(2.0) - 1.0) * log_co**2
    gk_var = gk_var.clip(lower=1e-12)
    rv = np.sqrt(gk_var) * 100.0
    rv.name = "gk_rv_pct"
    return rv


def build_har_panel(rv: pd.Series) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "daily_rv": rv,
            "rv_d": rv.shift(1),
            "rv_w": rv.rolling(5).mean().shift(1),
            "rv_m": rv.rolling(22).mean().shift(1),
        }
    ).dropna()
    return df


def pinball_series(y_true: np.ndarray, y_pred: np.ndarray, tau: float) -> np.ndarray:
    diff = y_true - y_pred
    return np.maximum(tau * diff, (tau - 1.0) * diff)


def pinball_loss(y_true: np.ndarray, y_pred: np.ndarray, tau: float) -> float:
    return float(np.mean(pinball_series(y_true, y_pred, tau)))


def kupiec_uc(violations: int, n: int, p_nominal: float) -> dict:
    p_hat = violations / n if n > 0 else 0.0
    eps = 1e-12
    p_hat_safe = min(max(p_hat, eps), 1 - eps)
    ll_null = violations * math.log(p_nominal) + (n - violations) * math.log(1.0 - p_nominal)
    ll_alt = violations * math.log(p_hat_safe) + (n - violations) * math.log(1.0 - p_hat_safe)
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


def stationary_bootstrap_resample(
    rng: np.random.Generator,
    n: int,
    mean_block: float,
) -> np.ndarray:
    p = 1.0 / max(mean_block, 1.0)
    idx = np.empty(n, dtype=np.int64)
    i = 0
    while i < n:
        start = int(rng.integers(0, n))
        block_len = int(rng.geometric(p))
        for k in range(block_len):
            if i >= n:
                break
            idx[i] = (start + k) % n
            i += 1
    return idx


def centered_joint_bootstrap(diff_series_by_asset: list[np.ndarray]) -> dict:
    """Centered-null stationary bootstrap for H0: mean(diff) <= 0 vs H1 > 0."""
    rng = np.random.default_rng(SEED)
    per_asset_means = np.array([float(np.mean(a)) for a in diff_series_by_asset])
    t_obs = float(np.mean(per_asset_means))

    boot_t = np.empty(N_BOOT, dtype=np.float64)
    boot_t_null = np.empty(N_BOOT, dtype=np.float64)
    centered_assets = [a - float(np.mean(a)) for a in diff_series_by_asset]

    for b in range(N_BOOT):
        raw_means = []
        null_means = []
        for raw_a, centered_a in zip(diff_series_by_asset, centered_assets, strict=True):
            n_a = len(raw_a)
            block = max(2.0, math.ceil(n_a ** (1.0 / 3.0)))
            idx = stationary_bootstrap_resample(rng, n_a, block)
            raw_means.append(float(np.mean(raw_a[idx])))
            null_means.append(float(np.mean(centered_a[idx])))
        boot_t[b] = float(np.mean(raw_means))
        boot_t_null[b] = float(np.mean(null_means))

    p_one_sided = float(np.mean(boot_t_null >= t_obs))
    p_two_sided = float(np.mean(np.abs(boot_t_null) >= abs(t_obs)))
    ci_low = float(np.quantile(boot_t, 0.025))
    ci_high = float(np.quantile(boot_t, 0.975))
    return {
        "T_obs": t_obs,
        "per_asset_means": [float(x) for x in per_asset_means],
        "p_one_sided": p_one_sided,
        "p_two_sided": p_two_sided,
        "boot_ci95": [ci_low, ci_high],
        "n_boot": int(N_BOOT),
    }


def format_tau_key(tau: float) -> str:
    return f"q{int(round(tau * 100)):02d}"


def empirical_quantile_baseline(mu: np.ndarray, resid: np.ndarray, tau: float) -> np.ndarray:
    q = float(np.quantile(resid, tau))
    return mu + q


def gaussian_quantile_baseline(mu: np.ndarray, sigma: np.ndarray, tau: float) -> np.ndarray:
    z = float(stats.norm.ppf(tau))
    return mu + z * sigma


def run_asset(asset: str) -> dict:
    px = load_asset(asset)
    rv = garman_klass_rv(px)
    panel = build_har_panel(rv)
    oos_start = pd.Timestamp(OOS_START)
    train_mask = panel.index < oos_start
    oos_mask = panel.index >= oos_start
    if oos_mask.sum() < 50:
        raise RuntimeError(f"{asset}: insufficient OOS samples ({int(oos_mask.sum())})")

    x_cols = ["rv_d", "rv_w", "rv_m"]
    x_train = sm.add_constant(panel.loc[train_mask, x_cols])
    y_train = panel.loc[train_mask, "daily_rv"].to_numpy()
    x_oos = sm.add_constant(panel.loc[oos_mask, x_cols])
    y_oos = panel.loc[oos_mask, "daily_rv"].to_numpy()
    oos_index = panel.loc[oos_mask].index

    ols = sm.OLS(y_train, x_train).fit()
    mu_train = np.asarray(ols.predict(x_train))
    mu_oos = np.asarray(ols.predict(x_oos))
    resid_train = y_train - mu_train

    sigma_const = np.full_like(mu_oos, fill_value=float(np.std(resid_train, ddof=1)))
    sigma_const = np.clip(sigma_const, 1e-6, None)

    abs_resid_train = np.abs(resid_train)
    scale_model = sm.OLS(abs_resid_train, x_train).fit()
    abs_pred_oos = np.asarray(scale_model.predict(x_oos))
    sigma_ls = np.clip(abs_pred_oos * math.sqrt(math.pi / 2.0), 1e-6, None)

    qr_preds: dict[str, np.ndarray] = {}
    qr_summary: dict[str, dict] = {}
    baseline_preds: dict[str, dict[str, np.ndarray]] = {
        "har_gaussian_const_sigma": {},
        "har_empirical_residual_quantile": {},
        "har_location_scale_gaussian": {},
    }

    for tau in QUANTILES:
        tau_key = format_tau_key(tau)
        qr = QuantReg(y_train, x_train).fit(q=tau, max_iter=5000)
        qr_pred = np.asarray(qr.predict(x_oos))
        qr_preds[tau_key] = qr_pred

        empirical_coverage = float(np.mean(y_oos <= qr_pred))
        if tau >= 0.5:
            violations = int(np.sum(y_oos > qr_pred))
            p_nominal = 1.0 - tau
        else:
            violations = int(np.sum(y_oos < qr_pred))
            p_nominal = tau

        qr_summary[tau_key] = {
            "tau": tau,
            "params": {k: float(v) for k, v in qr.params.to_dict().items()},
            "pinball_loss_oos": pinball_loss(y_oos, qr_pred, tau),
            "empirical_coverage_below": empirical_coverage,
            "nominal_coverage": tau,
            "coverage_gap_pp": float((empirical_coverage - tau) * 100.0),
            "kupiec_uc": kupiec_uc(violations=violations, n=len(y_oos), p_nominal=p_nominal),
        }

        baseline_preds["har_gaussian_const_sigma"][tau_key] = gaussian_quantile_baseline(
            mu_oos, sigma_const, tau
        )
        baseline_preds["har_empirical_residual_quantile"][tau_key] = empirical_quantile_baseline(
            mu_oos, resid_train, tau
        )
        baseline_preds["har_location_scale_gaussian"][tau_key] = gaussian_quantile_baseline(
            mu_oos, sigma_ls, tau
        )

    baseline_results: dict[str, dict] = {}
    for baseline_name, pred_by_tau in baseline_preds.items():
        dm_by_tau = {}
        loss_diffs = {}
        baseline_summary = {}
        for tau in QUANTILES:
            tau_key = format_tau_key(tau)
            baseline_pred = pred_by_tau[tau_key]
            qr_pred = qr_preds[tau_key]
            base_loss_series = pinball_series(y_oos, baseline_pred, tau)
            qr_loss_series = pinball_series(y_oos, qr_pred, tau)
            dm_by_tau[tau_key] = dm_test_hln(base_loss_series, qr_loss_series, h=1)
            loss_diffs[tau_key] = (base_loss_series - qr_loss_series).tolist()
            baseline_summary[tau_key] = {
                "pinball_loss_oos": pinball_loss(y_oos, baseline_pred, tau),
            }
        baseline_results[baseline_name] = {
            "baseline_pinball": baseline_summary,
            "dm_qr_vs_baseline": dm_by_tau,
            "loss_diffs_for_bootstrap": loss_diffs,
        }

    return {
        "asset": asset,
        "n_train": int(train_mask.sum()),
        "n_oos": int(oos_mask.sum()),
        "oos_first_date": str(oos_index.min().date()),
        "oos_last_date": str(oos_index.max().date()),
        "har_mean_model": {
            "params": {k: float(v) for k, v in ols.params.to_dict().items()},
            "train_resid_std": float(np.std(resid_train, ddof=1)),
        },
        "har_scale_model_abs_resid": {
            "params": {k: float(v) for k, v in scale_model.params.to_dict().items()},
        },
        "quantile_forecasts": qr_summary,
        "fair_baseline_comparisons": baseline_results,
    }


def aggregate_results(per_asset: list[dict]) -> dict:
    baseline_names = list(per_asset[0]["fair_baseline_comparisons"].keys())
    baseline_summary = {}

    for baseline_name in baseline_names:
        tail_counts = {}
        joint_bootstrap = {}
        tail_passes = []
        tail_conditionals = []
        for tail in TAILS:
            series_list = [
                np.asarray(r["fair_baseline_comparisons"][baseline_name]["loss_diffs_for_bootstrap"][tail])
                for r in per_asset
            ]
            joint = centered_joint_bootstrap(series_list)
            joint_bootstrap[tail] = joint
            sig_pos_assets = sum(
                1
                for r in per_asset
                if (
                    r["fair_baseline_comparisons"][baseline_name]["dm_qr_vs_baseline"][tail]["p_value"] < P_SIG
                    and r["fair_baseline_comparisons"][baseline_name]["dm_qr_vs_baseline"][tail]["dm_stat"] > 0
                )
            )
            tail_counts[tail] = int(sig_pos_assets)
            formal = sig_pos_assets >= 1 and joint["p_one_sided"] < P_SIG
            conditional = sig_pos_assets >= 1
            if formal:
                tail_passes.append(tail)
            elif conditional:
                tail_conditionals.append(tail)

        if len(tail_passes) >= 1:
            label = "PASS"
            reason = (
                f"Formal tail improvement on {', '.join(tail_passes)} "
                f"with fair baseline {baseline_name}"
            )
        elif len(tail_conditionals) >= 1:
            label = "CONDITIONAL_PASS"
            reason = (
                f"Per-asset tail gains on {', '.join(tail_conditionals)} "
                f"but no joint bootstrap confirmation for {baseline_name}"
            )
        else:
            label = "NULL"
            reason = f"No formal tail improvement vs fair baseline {baseline_name}"

        baseline_summary[baseline_name] = {
            "label": label,
            "reason": reason,
            "tail_sig_pos_counts": tail_counts,
            "joint_bootstrap": joint_bootstrap,
        }

    pass_baselines = [
        name for name, s in baseline_summary.items() if s["label"] == "PASS"
    ]
    conditional_baselines = [
        name for name, s in baseline_summary.items() if s["label"] == "CONDITIONAL_PASS"
    ]

    if len(pass_baselines) >= 2:
        overall_label = "PASS"
        overall_reason = (
            f"Formal tail improvement survives in {len(pass_baselines)}/3 fair baselines: "
            + ", ".join(pass_baselines)
        )
    elif len(pass_baselines) == 1 or len(conditional_baselines) >= 1:
        overall_label = "CONDITIONAL_PASS"
        names = pass_baselines + conditional_baselines
        overall_reason = (
            "Some fair-baseline evidence remains, but robustness is incomplete: "
            + ", ".join(names)
        )
    else:
        overall_label = "NULL"
        overall_reason = (
            "All three fair baselines fail to show formal tail improvement; "
            "commodity tail-forecasting claim is not supported."
        )

    return {
        "label": overall_label,
        "reason": overall_reason,
        "baseline_verdicts": baseline_summary,
        "n_pass_baselines": int(len(pass_baselines)),
        "n_conditional_baselines": int(len(conditional_baselines)),
    }


def main() -> dict:
    per_asset = [run_asset(asset) for asset in ASSETS]
    aggregate = aggregate_results(per_asset)
    out = {
        "experiment_id": "K1422",
        "title": "HAR-Quantile commodity rerun with fair baselines + corrected bootstrap",
        "lineage_fix_for": ["K1402", "K1403", "K1421"],
        "assets": ASSETS,
        "data_start": DATA_START,
        "oos_start": OOS_START,
        "per_asset": per_asset,
        "aggregate_verdict": aggregate,
        "config": {
            "seed": SEED,
            "n_boot": N_BOOT,
            "quantiles": QUANTILES,
            "rv_proxy": "Garman-Klass (1980)",
            "mean_model": "HAR OLS",
            "quantile_model": "statsmodels QuantReg (Koenker-Bassett 1978)",
            "fair_baselines": [
                "HAR Gaussian constant sigma",
                "HAR empirical residual quantile",
                "HAR location-scale Gaussian via abs-residual HAR",
            ],
            "bootstrap_method": "Centered-null stationary bootstrap, L=ceil(n^{1/3})",
            "refit": "none (single fixed-origin fit, IS pre-2021)",
        },
    }
    RESULTS_PATH.write_text(json.dumps(out, indent=2, ensure_ascii=False))
    print(
        json.dumps(
            {
                "experiment_id": out["experiment_id"],
                "aggregate_label": aggregate["label"],
                "n_pass_baselines": aggregate["n_pass_baselines"],
                "n_conditional_baselines": aggregate["n_conditional_baselines"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return out


if __name__ == "__main__":
    main()
