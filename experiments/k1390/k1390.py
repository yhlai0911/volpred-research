"""
K1390: Regime-Weighted Conformal VaR (RWC)

Compares three daily VaR calibrations on SPY log returns:
1. HS-252 rolling historical simulation
2. CU conformal-unconditional fixed VaR from IS data
3. CR conformal-regime fixed VaR from IS regime buckets
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy import stats


np.random.seed(42)

EXPERIMENT_ID = "K1390"
ALPHAS = [0.05, 0.01]
REGIME_THRESHOLD = 20.0
ROLLING_WINDOW = 252

ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT.parent.parent / "paper" / "leverage-direction" / "data" / "spy_vix_2004-2026.csv"
RESULTS_PATH = ROOT / "k1390_results.json"
FIGURE_PATH = ROOT / "k1390_var_backtest.png"


def kupiec_lr(n_exceed, n_obs, alpha):
    p_hat = n_exceed / n_obs
    if p_hat == 0 or p_hat == 1:
        return float("nan"), float("nan")
    lr = -2 * (
        n_exceed * np.log(alpha / p_hat)
        + (n_obs - n_exceed) * np.log((1 - alpha) / (1 - p_hat))
    )
    p_value = 1 - stats.chi2.cdf(lr, df=1)
    return lr, p_value


def christoffersen_independence(exceedances: np.ndarray) -> Tuple[float, float]:
    # LR_ind test for first-order Markov independence of exceedance hits
    e = exceedances.astype(int)
    if e.size < 2:
        return float("nan"), float("nan")
    n00 = int(((e[:-1] == 0) & (e[1:] == 0)).sum())
    n01 = int(((e[:-1] == 0) & (e[1:] == 1)).sum())
    n10 = int(((e[:-1] == 1) & (e[1:] == 0)).sum())
    n11 = int(((e[:-1] == 1) & (e[1:] == 1)).sum())
    n0 = n00 + n01
    n1 = n10 + n11
    n_total = n0 + n1
    if n0 == 0 or n1 == 0 or n_total == 0:
        return float("nan"), float("nan")
    pi = (n01 + n11) / n_total
    pi0 = n01 / n0 if n0 > 0 else 0.0
    pi1 = n11 / n1 if n1 > 0 else 0.0
    if pi in (0.0, 1.0) or (pi0 in (0.0,) and pi1 in (0.0,)):
        return float("nan"), float("nan")
    eps = 1e-300
    ll_null = (n00 + n10) * np.log(max(1 - pi, eps)) + (n01 + n11) * np.log(max(pi, eps))
    ll_alt = (
        n00 * np.log(max(1 - pi0, eps))
        + n01 * np.log(max(pi0, eps))
        + n10 * np.log(max(1 - pi1, eps))
        + n11 * np.log(max(pi1, eps))
    )
    lr = -2 * (ll_null - ll_alt)
    if lr < 0:
        lr = 0.0
    p_value = 1 - stats.chi2.cdf(lr, df=1)
    return float(lr), float(p_value)


def _pick_column(names: Tuple[str, ...], candidates: List[str]) -> str:
    lower_map = {name.lower(): name for name in names}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    raise KeyError(f"Missing required columns. Available columns: {list(names)}")


def load_data() -> Dict[str, np.ndarray]:
    raw = np.genfromtxt(
        DATA_PATH,
        delimiter=",",
        names=True,
        dtype=None,
        encoding="utf-8",
    )
    names = raw.dtype.names or ()
    date_col = _pick_column(names, ["date"])
    spy_col = _pick_column(names, ["spy_adj_close", "spy_close", "adj_close", "close"])
    vix_col = _pick_column(names, ["vix_close", "vix_adj_close", "vix"])

    dates = raw[date_col].astype("datetime64[D]")
    spy = np.asarray(raw[spy_col], dtype=float)
    vix = np.asarray(raw[vix_col], dtype=float)

    valid = np.isfinite(spy) & np.isfinite(vix)
    dates = dates[valid]
    spy = spy[valid]
    vix = vix[valid]

    # Defensive dedup: upstream CSV may contain duplicate trading days
    # (observed 10 dups in 2026-05; pipeline fix tracked separately).
    # Keep first occurrence of each date so results stay reproducible.
    _, first_idx = np.unique(dates, return_index=True)
    first_idx.sort()
    dates = dates[first_idx]
    spy = spy[first_idx]
    vix = vix[first_idx]

    returns = np.full_like(spy, fill_value=np.nan, dtype=float)
    returns[1:] = np.log(spy[1:] / spy[:-1])

    high_vol = np.zeros_like(vix, dtype=bool)
    high_vol[1:] = vix[:-1] > REGIME_THRESHOLD

    return {
        "dates": dates,
        "spy": spy,
        "vix": vix,
        "returns": returns,
        "high_vol": high_vol,
    }


def safe_var_from_returns(sample_returns: np.ndarray, alpha: float) -> float:
    clean = sample_returns[np.isfinite(sample_returns)]
    if clean.size == 0:
        return float("nan")
    return float(-np.quantile(clean, alpha))


def rolling_exceedance_rate(exceedances: np.ndarray, window: int) -> np.ndarray:
    out = np.full(exceedances.shape[0], np.nan, dtype=float)
    if exceedances.shape[0] < window:
        return out
    series = exceedances.astype(float)
    csum = np.cumsum(np.insert(series, 0, 0.0))
    for idx in range(window - 1, exceedances.shape[0]):
        total = csum[idx + 1] - csum[idx + 1 - window]
        out[idx] = total / window
    return out


def evaluate_var_methods(data: Dict[str, np.ndarray]) -> Tuple[Dict[Tuple[str, float], Dict[str, np.ndarray]], Dict]:
    dates = data["dates"]
    returns = data["returns"]
    high_vol = data["high_vol"]

    is_mask = (dates >= np.datetime64("2004-01-01")) & (dates <= np.datetime64("2014-12-31"))
    oos_mask = (dates >= np.datetime64("2015-01-01")) & (dates <= np.datetime64("2026-12-31"))
    valid_mask = np.isfinite(returns)

    is_mask &= valid_mask
    oos_mask &= valid_mask

    is_returns = returns[is_mask]
    is_regimes = high_vol[is_mask]
    oos_idx = np.where(oos_mask)[0]
    oos_dates = dates[oos_idx]
    oos_returns = returns[oos_idx]
    oos_regimes = high_vol[oos_idx]

    regime_notes: List[str] = []
    if is_returns.size == 0 or oos_returns.size == 0:
        raise ValueError("IS or OOS sample is empty after filtering.")

    is_high_returns = is_returns[is_regimes]
    is_low_returns = is_returns[~is_regimes]

    if is_high_returns.size == 0:
        regime_notes.append("CR high-vol IS bucket empty; fallback to CU quantile.")
    if is_low_returns.size == 0:
        regime_notes.append("CR low-vol IS bucket empty; fallback to CU quantile.")

    outputs: Dict[Tuple[str, float], Dict[str, np.ndarray]] = {}
    summary_rows = []
    per_regime_var: Dict[float, Dict[str, float]] = {}

    for alpha in ALPHAS:
        cu_var = safe_var_from_returns(is_returns, alpha)
        cr_high_var = safe_var_from_returns(is_high_returns, alpha) if is_high_returns.size else cu_var
        cr_low_var = safe_var_from_returns(is_low_returns, alpha) if is_low_returns.size else cu_var
        per_regime_var[alpha] = {
            "cu_var": float(cu_var),
            "cr_high_var": float(cr_high_var),
            "cr_low_var": float(cr_low_var),
        }

        hs_vars = np.full(oos_idx.shape[0], np.nan, dtype=float)
        cu_vars = np.full(oos_idx.shape[0], cu_var, dtype=float)
        cr_vars = np.where(oos_regimes, cr_high_var, cr_low_var).astype(float)

        for j, global_idx in enumerate(oos_idx):
            start = global_idx - ROLLING_WINDOW
            end = global_idx
            if start < 0:
                continue
            hs_vars[j] = safe_var_from_returns(returns[start:end], alpha)

        method_vars = {
            "HS-252": hs_vars,
            "CU": cu_vars,
            "CR": cr_vars,
        }

        for method, var_series in method_vars.items():
            eval_mask = np.isfinite(var_series) & np.isfinite(oos_returns)
            method_returns = oos_returns[eval_mask]
            method_vars_clean = var_series[eval_mask]
            exceedances = method_returns < (-method_vars_clean)
            n_obs = int(exceedances.size)
            n_exceed = int(exceedances.sum())
            actual_rate = float(n_exceed / n_obs) if n_obs else float("nan")
            lr, p_value = (float("nan"), float("nan"))
            ind_lr, ind_p = (float("nan"), float("nan"))
            if n_obs > 0:
                lr, p_value = kupiec_lr(n_exceed, n_obs, alpha)
                ind_lr, ind_p = christoffersen_independence(exceedances)
            cc_lr = lr + ind_lr if np.isfinite(lr) and np.isfinite(ind_lr) else float("nan")
            cc_p = (
                float(1 - stats.chi2.cdf(cc_lr, df=2))
                if np.isfinite(cc_lr)
                else float("nan")
            )

            outputs[(method, alpha)] = {
                "dates": oos_dates[eval_mask],
                "returns": method_returns,
                "vars": method_vars_clean,
                "exceedances": exceedances,
            }
            summary_rows.append(
                {
                    "method": method,
                    "alpha": alpha,
                    "n_obs": n_obs,
                    "n_exceed": n_exceed,
                    "actual_rate": actual_rate,
                    "nominal_alpha": alpha,
                    "kupiec_lr": None if not np.isfinite(lr) else float(lr),
                    "kupiec_p_value": None if not np.isfinite(p_value) else float(p_value),
                    "christoffersen_ind_lr": None if not np.isfinite(ind_lr) else float(ind_lr),
                    "christoffersen_ind_p_value": None if not np.isfinite(ind_p) else float(ind_p),
                    "christoffersen_cc_lr": None if not np.isfinite(cc_lr) else float(cc_lr),
                    "christoffersen_cc_p_value": None if not np.isfinite(cc_p) else float(cc_p),
                }
            )

    summary = {
        "var_results": summary_rows,
        "oos_dates": oos_dates,
        "oos_returns": oos_returns,
        "oos_regimes": oos_regimes,
        "notes": regime_notes,
        "per_regime_var": {f"{a:.2f}": per_regime_var[a] for a in ALPHAS},
    }
    return outputs, summary


def create_figure(summary: Dict, outputs: Dict[Tuple[str, float], Dict[str, np.ndarray]]) -> None:
    oos_dates = summary["oos_dates"]
    oos_returns = summary["oos_returns"]
    cum_log_return = np.cumsum(oos_returns)

    try:
        plt.style.use("seaborn-v0_8-whitegrid")
    except OSError:
        plt.style.use("default")

    fig = plt.figure(figsize=(14, 10), constrained_layout=True)
    gs = fig.add_gridspec(3, 2, height_ratios=[1.1, 1, 1], hspace=0.35, wspace=0.22)

    ax_top = fig.add_subplot(gs[0, :])
    ax_top.plot(oos_dates, cum_log_return, color="#1f3b73", linewidth=1.5)
    ax_top.set_title("K1390 OOS Cumulative Log-Return of SPY")
    ax_top.set_ylabel("Cumulative log-return")

    panel_map = [
        ("HS-252", 0.05, gs[1, 0], "HS-252 95%"),
        ("CR", 0.05, gs[1, 1], "CR 95%"),
        ("HS-252", 0.01, gs[2, 0], "HS-252 99%"),
        ("CR", 0.01, gs[2, 1], "CR 99%"),
    ]

    for method, alpha, grid_slot, title in panel_map:
        ax = fig.add_subplot(grid_slot)
        data = outputs[(method, alpha)]
        rolling_rate = rolling_exceedance_rate(data["exceedances"], ROLLING_WINDOW)
        ax.plot(data["dates"], rolling_rate, color="#b03a2e", linewidth=1.2)
        ax.axhline(alpha, color="#222222", linestyle="--", linewidth=1.0)
        ax.set_title(title)
        ax.set_ylim(bottom=0)
        ax.set_ylabel("252d exceedance rate")

    for ax in fig.axes[-2:]:
        ax.set_xlabel("Date")

    fig.savefig(FIGURE_PATH, dpi=150, bbox_inches="tight")
    plt.close(fig)


def write_results(summary: Dict) -> Dict:
    result_rows = summary["var_results"]
    p_lookup = {
        (row["method"], row["alpha"]): (
            -np.inf if row["kupiec_p_value"] is None else row["kupiec_p_value"]
        )
        for row in result_rows
    }
    cc_lookup = {
        (row["method"], row["alpha"]): (
            -np.inf
            if row.get("christoffersen_cc_p_value") is None
            else row["christoffersen_cc_p_value"]
        )
        for row in result_rows
    }
    # Stricter verdict: REGIME_EFFECT requires CR to beat CU on BOTH alphas
    # under Kupiec, AND CR's conditional coverage (Christoffersen CC) p-value
    # is not significantly worse than CU on either alpha.
    cr_kupiec_wins_all = all(
        p_lookup.get(("CR", a), -np.inf) > p_lookup.get(("CU", a), -np.inf)
        for a in ALPHAS
    )
    cr_cc_not_worse = all(
        cc_lookup.get(("CR", a), -np.inf) >= cc_lookup.get(("CU", a), -np.inf) - 0.05
        for a in ALPHAS
    )
    if cr_kupiec_wins_all and cr_cc_not_worse:
        verdict = "REGIME_EFFECT"
    elif any(
        p_lookup.get(("CR", a), -np.inf) > p_lookup.get(("CU", a), -np.inf)
        for a in ALPHAS
    ):
        verdict = "PARTIAL_REGIME_EFFECT"
    else:
        verdict = "NO_REGIME_EFFECT"

    oos_regimes = summary["oos_regimes"]
    notes = list(summary["notes"])
    for row in result_rows:
        if row["n_obs"] == 0:
            notes.append(f"{row['method']} alpha={row['alpha']:.2f}: no valid OOS observations.")
        elif row["kupiec_p_value"] is None:
            notes.append(
                f"{row['method']} alpha={row['alpha']:.2f}: Kupiec undefined because exceedance rate is 0 or 1."
            )

    payload = {
        "experiment_id": EXPERIMENT_ID,
        "data_source": str(DATA_PATH.relative_to(ROOT.parent.parent)),
        "is_period": "2004-01-01 to 2014-12-31",
        "oos_period": "2015-01-01 to 2026-12-31",
        "regime_threshold": "VIX_{t-1} > 20",
        "var_results": result_rows,
        "regime_obs": {
            "high_vol_count": int(oos_regimes.sum()),
            "low_vol_count": int((~oos_regimes).sum()),
        },
        "per_regime_var": summary.get("per_regime_var", {}),
        "verdict": verdict,
        "notes": notes,
        "caveats": [
            "IS/OOS cutoff at 2014-12-31 is canonical; cutoff sensitivity (±1y) not tested.",
            "VIX>20 regime threshold is fixed ex-ante per literature; threshold sensitivity not swept.",
            "Conformal calibration is single-shot from full IS sample (no rolling re-calibration).",
        ],
    }

    with RESULTS_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2)
    return payload


def main() -> None:
    data = load_data()
    outputs, summary = evaluate_var_methods(data)
    create_figure(summary, outputs)
    payload = write_results(summary)

    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {FIGURE_PATH}")
    print(f"Verdict: {payload['verdict']}")


if __name__ == "__main__":
    main()
