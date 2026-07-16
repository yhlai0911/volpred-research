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

    unhedged, hedged_lvl, hedged_ret = [], [], []
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
        # Point estimate only: the merged artifact stores no PCH hedged-return
        # series and truncates refit snapshots, so a paired DM/bootstrap of
        # return-OLS vs PCH is impossible without re-running the PCH MLE.
        res["return_beta_beats_pch_point_estimate_only"] = (
            hh["ols_return_beta"] > hh["pch_from_merged"]
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
                    "The return-OLS vs PCH comparison is a POINT ESTIMATE, not a test. "
                    "k1426_oos_results.json stores no PCH hedged-return series and truncates "
                    "refit snapshots to the head, so a paired DM / block-bootstrap of "
                    "return-OLS vs PCH requires re-running the PCH MLE and is out of scope here.",
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
