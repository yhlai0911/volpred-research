"""Add the missing return-regression benchmark to the K1426 OOS comparison.

Motivation
----------
`oos.py` estimates the OLS/EG hedge ratio by regressing log PRICE LEVELS
(the cointegrating beta) and then applies that beta to hedge daily RETURNS.
A levels beta does not minimise return variance, so "PCH beats OLS" in
k1426_oos_results.json is measured against a benchmark that was never fit for
the loss it is scored on. The natural benchmark for return hedging is beta
from a regression of returns on returns.

This script re-runs the same OOS protocol (expanding window, min_train=756,
refit_every=63, beta from [:i] applied to the return spanning i-1 -> i, so the
lag discipline of oos.py is preserved exactly) and adds `beta_ret`. If the
return-OLS benchmark matches or beats PCH, the reported PCH advantage is an
artifact of the levels-beta straw man rather than evidence for partial
cointegration.

No PCH refit happens here (that MLE multistart is what made the parent job
time out); PCH numbers are read back from the merged results file.

Usage: uv run python experiments/k1426/oos_return_benchmark.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from k1426 import fetch_pair, fit_ols_hedge  # noqa: E402
from oos import (  # noqa: E402
    bootstrap_he_diff_ci,
    hedge_effectiveness_from_returns,
)
from volpred.stats.model_evaluation import dm_test  # noqa: E402

START, END = "2015-01-01", "2024-12-31"
MIN_TRAIN, REFIT_EVERY = 756, 63
MERGED = HERE / "k1426_oos_results.json"
OUT = HERE / "k1426_oos_return_benchmark.json"


def he(unhedged: np.ndarray, hedged: np.ndarray) -> float:
    """Hedge effectiveness = 1 - Var(hedged)/Var(unhedged); matches oos.py (ddof=1)."""
    var_unhedged = np.var(unhedged, ddof=1)
    if not np.isfinite(var_unhedged) or var_unhedged <= 1e-18:
        return float("nan")
    return float(1.0 - np.var(hedged, ddof=1) / var_unhedged)


def fit_return_beta(ret_x: np.ndarray, ret_y: np.ndarray) -> float:
    """Variance-minimising hedge ratio: OLS of x-returns on y-returns."""
    X = np.column_stack([np.ones_like(ret_y), ret_y])
    coef, *_ = np.linalg.lstsq(X, ret_x, rcond=None)
    return float(coef[1])


def analyze(sym_x: str, sym_y: str) -> dict:
    df = fetch_pair(sym_x, sym_y, START, END)
    log_x = df["log_x"].to_numpy()
    log_y = df["log_y"].to_numpy()

    dates = df.index if hasattr(df, "index") else None
    unhedged, hedged_lvl, hedged_ret = [], [], []
    oos_dates = []
    beta_lvl_snaps, beta_ret_snaps = [], []
    current = None
    last_refit = -1

    for i in range(MIN_TRAIN, len(df)):
        if current is None or (i - last_refit) >= REFIT_EVERY:
            # Train strictly on [:i] — same slice oos.py uses.
            train_x, train_y = log_x[:i], log_y[:i]
            _, beta_lvl, _ = fit_ols_hedge(train_x, train_y)
            # Returns within the training window only.
            beta_ret = fit_return_beta(np.diff(train_x), np.diff(train_y))
            current = {"lvl": beta_lvl, "ret": beta_ret}
            beta_lvl_snaps.append(beta_lvl)
            beta_ret_snaps.append(beta_ret)
            last_refit = i

        rx = float(log_x[i] - log_x[i - 1])
        ry = float(log_y[i] - log_y[i - 1])
        unhedged.append(rx)
        hedged_lvl.append(rx - current["lvl"] * ry)
        hedged_ret.append(rx - current["ret"] * ry)
        oos_dates.append(str(dates[i].date()) if dates is not None else str(i))

    unhedged = np.asarray(unhedged)
    hedged_lvl = np.asarray(hedged_lvl)
    hedged_ret = np.asarray(hedged_ret)
    t_stat, p_value = dm_test(hedged_ret**2, hedged_lvl**2, h=1)

    return {
        "symbols": {"x": sym_x, "y": sym_y},
        "n_obs_oos": int(len(unhedged)),
        "n_refits": len(beta_lvl_snaps),
        "hedge_effectiveness": {
            "ols_levels_beta": he(unhedged, hedged_lvl),
            "ols_return_beta": he(unhedged, hedged_ret),
        },
        "mean_beta": {
            "levels": float(np.mean(beta_lvl_snaps)),
            "returns": float(np.mean(beta_ret_snaps)),
        },
        "dm_return_beta_vs_levels_beta": {"t_stat": float(t_stat), "p_value": float(p_value)},
        # Kept in-memory (not serialised) for the paired return-OLS vs PCH test
        # in main(); stripped before writing OUT.
        "_series": {
            "oos_dates": oos_dates,
            "unhedged": unhedged,
            "hedged_ret": hedged_ret,
        },
    }


def paired_return_ols_vs_pch(res_series: dict, pch_series: dict, seed: int = 42) -> dict:
    """Paired DM + block-bootstrap of return-OLS vs PCH on date-aligned series.

    ``res_series`` carries the freshly recomputed return-OLS hedged returns and
    their OOS dates; ``pch_series`` is the persisted daily PCH hedged-return
    series from k1426_oos_results.json. Aligns on the date intersection so the
    two hedges are compared on exactly the same days.
    """
    ret_by_date = dict(zip(res_series["oos_dates"], res_series["hedged_ret"]))
    un_by_date = dict(zip(res_series["oos_dates"], res_series["unhedged"]))
    pch_by_date = dict(zip(pch_series["oos_dates"], pch_series["hedged_pch"]))
    common = [d for d in res_series["oos_dates"] if d in pch_by_date]
    if len(common) < 100:
        return {
            "error": (
                f"only {len(common)} overlapping OOS dates between fresh return-OLS "
                "run and persisted PCH series; paired test not run"
            ),
            "n_common": len(common),
        }
    unhedged = np.asarray([un_by_date[d] for d in common])
    hedged_ret = np.asarray([ret_by_date[d] for d in common])
    hedged_pch = np.asarray([pch_by_date[d] for d in common])
    dm_t, dm_p = dm_test(hedged_ret**2, hedged_pch**2, h=1)
    # bootstrap_he_diff_ci returns HE(first) - HE(second); pass (ret, pch) so a
    # positive diff means return-OLS hedges better than PCH.
    ci = bootstrap_he_diff_ci(
        unhedged, hedged_ret, hedged_pch, block_len=20, n_boot=1000, seed=seed
    )
    return {
        "n_common": len(common),
        "he_return_ols": hedge_effectiveness_from_returns(unhedged, hedged_ret),
        "he_pch": hedge_effectiveness_from_returns(unhedged, hedged_pch),
        "dm_return_ols_vs_pch": {
            "t_stat": float(dm_t),
            "p_value": float(dm_p),
            "note": "squared-hedged-return loss; positive t => return-OLS higher variance than PCH.",
            "harvey_threshold_note": "Use |t| > 3.0 for a strong claim under multiple testing.",
        },
        "bootstrap_he_diff_return_ols_minus_pch": ci,
    }


def main() -> None:
    merged = json.loads(MERGED.read_text())
    results = {}
    for name, payload in merged["pairs"].items():
        if "error" in payload:
            results[name] = {"error": f"skipped; merged results carry: {payload['error']}"}
            print(f"{name}: SKIP ({payload['error']})")
            continue
        sym_x, sym_y = payload["symbols"]["x"], payload["symbols"]["y"]
        try:
            res = analyze(sym_x, sym_y)
        except Exception as exc:  # data fetch is the usual failure here
            results[name] = {"error": str(exc)}
            print(f"{name}: ERROR {exc}")
            continue
        res["hedge_effectiveness"]["pch_from_merged"] = payload["hedge_effectiveness"]["pch"]
        hh = res["hedge_effectiveness"]
        # The PCH figure is a stored scalar from an earlier run over freshly
        # downloaded data. If the OOS sample no longer lines up, the two HE
        # numbers are not comparable at all — flag rather than quietly compare.
        res["sample_matches_merged"] = res["n_obs_oos"] == payload["n_obs_oos"]
        res["levels_beta_replicates_merged"] = bool(
            np.isclose(hh["ols_levels_beta"], payload["hedge_effectiveness"]["ols"], atol=1e-6)
        )
        res["return_beta_beats_pch_point_estimate_only"] = (
            hh["ols_return_beta"] > hh["pch_from_merged"]
        )
        # If the merged run persisted the daily PCH hedged-return series (added
        # 2026-07-27 for K1426 OOS residual item 2), run a genuine paired
        # DM/block-bootstrap of return-OLS vs PCH instead of the point-estimate
        # comparison above.
        pch_series = payload.get("daily_hedged_returns")
        if pch_series and pch_series.get("hedged_pch"):
            res["paired_return_ols_vs_pch"] = paired_return_ols_vs_pch(
                res.pop("_series"), pch_series
            )
        else:
            res.pop("_series", None)
            res["paired_test_note"] = (
                "merged results carry no daily PCH series; paired test skipped "
                "(re-run oos.py after the daily-series persistence patch)."
            )
        results[name] = res
        print(
            f"{name}: HE levels-OLS={hh['ols_levels_beta']:.4f} "
            f"return-OLS={hh['ols_return_beta']:.4f} PCH={hh['pch_from_merged']:.4f} "
            f"| beta lvl={res['mean_beta']['levels']:.3f} ret={res['mean_beta']['returns']:.3f} "
            f"| sample_match={res['sample_matches_merged']} "
            f"lvl_replicates={res['levels_beta_replicates_merged']}"
        )

    OUT.write_text(
        json.dumps(
            {
                "experiment_id": "k1426_oos_return_benchmark",
                "title": "K1426 OOS — return-regression hedge benchmark vs levels beta and PCH",
                "data_range": {"start": START, "end": END},
                "spec": {
                    "min_train": MIN_TRAIN,
                    "refit_every": REFIT_EVERY,
                    "lookahead_rule": "Train on [:i], apply beta to return spanning i-1 -> i.",
                },
                "caveats": [
                    "The return-OLS vs levels-beta DM (dm_return_beta_vs_levels_beta) is always "
                    "computed here. The return-OLS vs PCH comparison is a paired DM / block-"
                    "bootstrap (paired_return_ols_vs_pch) ONLY when k1426_oos_results.json carries "
                    "the persisted daily PCH hedged-return series; otherwise it degrades to a "
                    "point-estimate flag (return_beta_beats_pch_point_estimate_only) because the "
                    "PCH MLE would have to be re-run to recover the series.",
                    "The DM test reported here compares return-beta vs levels-beta only, and "
                    "uses squared hedged returns (second moment) while HE uses de-meaned "
                    "variance; when the two hedges differ in mean these are not the same "
                    "estimand. Same convention as oos.py, kept for comparability.",
                    "PCH HE is read from the earlier run while levels/return HE are recomputed "
                    "from a fresh yfinance download; sample_matches_merged and "
                    "levels_beta_replicates_merged record whether that comparison is valid.",
                ],
                "pairs": results,
            },
            indent=2,
        )
        + "\n"
    )
    print(f"\nwrote {OUT.name}")


if __name__ == "__main__":
    main()
