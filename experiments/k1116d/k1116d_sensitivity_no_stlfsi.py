"""K1116d sensitivity: re-run finstress + all specs WITHOUT STLFSI signal.

Codex 2026-05-11 review MINOR: STLFSI vintage chain (STLFSI->STLFSI2->STLFSI3->STLFSI4)
vs revised STLFSI4 fredgraph backfill is not a pure revision-to-revision comparator
(corr=0.41). Sensitivity: drop STLFSI signal from finstress and all specs, re-test
H2_ROBUST_NULL. If verdict holds without STLFSI, the chain comparator concern is
not driving the NULL.

Author: VolPred Research System
Date: 2026-05-11
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

import sys
sys.path.insert(0, str(Path(__file__).parent))
from k1116d import (  # type: ignore
    fetch_spy_vix_weekly,
    load_vintage_two_views,
    load_revised_two_views,
    build_variant_panel,
    dm_hln,
    dm_bootstrap_ci,
)

np.random.seed(42)

HERE = Path(__file__).parent


def make_X_no_stlfsi(df_sub: pd.DataFrame, spec: str) -> pd.DataFrame:
    """Same as make_X in k1116d.py but STLFSI_signal removed from finstress / all."""
    X = pd.DataFrame(index=df_sub.index)
    X["y_lag1"] = df_sub["rv"].shift(1)
    if spec == "base":
        pass
    elif spec == "vix":
        X["vix_lag1"] = df_sub["vix_mean"].shift(1)
    elif spec == "epu":
        for c in ["USEPU_signal", "WLEMU_signal"]:
            if c in df_sub.columns:
                X[c] = df_sub[c]
    elif spec == "finstress":
        # NO STLFSI
        for c in ["NFCI_signal", "ANFCI_signal"]:
            if c in df_sub.columns:
                X[c] = df_sub[c]
    elif spec == "all":
        # NO STLFSI
        X["vix_lag1"] = df_sub["vix_mean"].shift(1)
        for c in ["USEPU_signal", "WLEMU_signal", "NFCI_signal", "ANFCI_signal"]:
            if c in df_sub.columns:
                X[c] = df_sub[c]
    else:
        raise ValueError(spec)
    return X


def fit_predict(panel, is_end, oos_start):
    df_is = panel.loc[:is_end].copy()
    df_oos = panel.loc[oos_start:].copy()
    out = {}
    for spec in ["base", "vix", "epu", "finstress", "all"]:
        X_is = make_X_no_stlfsi(df_is, spec)
        y_is = df_is["rv"].loc[X_is.index]
        mask = X_is.notna().all(axis=1) & y_is.notna()
        X_is, y_is = X_is[mask], y_is[mask]
        X_is_sm = sm.add_constant(X_is)
        model = sm.OLS(y_is, X_is_sm).fit()

        X_oos = make_X_no_stlfsi(df_oos, spec)
        mask_oos = X_oos.notna().all(axis=1)
        X_oos = X_oos[mask_oos]
        X_oos_sm = sm.add_constant(X_oos)[X_is_sm.columns]
        y_oos = df_oos["rv"].loc[X_oos.index]
        pred_oos = model.predict(X_oos_sm)
        valid = y_oos.notna() & pred_oos.notna()
        y_oos, pred_oos = y_oos[valid], pred_oos[valid]
        pred_clipped = np.maximum(pred_oos.values, 1e-6)
        actual = y_oos.values
        loss = np.log(pred_clipped) + actual / pred_clipped
        out[spec] = {
            "n_oos": int(len(y_oos)),
            "oos_qlike": float(np.mean(loss)),
            "loss_series": pd.Series(loss, index=y_oos.index),
        }
    return out


def run_no_stlfsi(market, alt_weekly, alt_pit, label):
    variants = ["orig_shift1", "corrected_shift2", "conservative_shift2",
                "pit_shift0", "pit_shift1", "multi_lag_3"]
    is_end, oos_start = "2022-12-31", "2023-01-01"
    results = {}
    all_loss = {}
    for v in variants:
        panel = build_variant_panel(market, alt_weekly, alt_pit, v)
        fit = fit_predict(panel, is_end, oos_start)
        for spec, r in fit.items():
            all_loss[(v, spec)] = r["loss_series"]
        results[v] = {s: {k: vv for k, vv in r.items() if k != "loss_series"}
                      for s, r in fit.items()}

    dm_table = {}
    for v in variants:
        dm_table[v] = {}
        bl = all_loss.get((v, "vix"))
        if bl is None:
            continue
        for spec in ["base", "epu", "finstress", "all"]:
            ch = all_loss.get((v, spec))
            if ch is None:
                continue
            idx = bl.index.intersection(ch.index)
            t, p, n = dm_hln(bl.loc[idx].values, ch.loc[idx].values, h=1)
            verdict = ("CHAL_WINS" if (t is not None and not np.isnan(t) and t > 3)
                       else "BASELINE_WINS" if (t is not None and not np.isnan(t) and t < -3)
                       else "NS")
            dm_table[v][spec] = {"t": t, "p": p, "n": n, "verdict": verdict}

    passing = [(v, s) for v in variants for s in ["epu", "finstress", "all"]
               if dm_table.get(v, {}).get(s, {}).get("verdict") == "CHAL_WINS"]
    return {"label": label, "dm_table": dm_table, "passing": passing,
            "verdict": "H2_ROBUST_NULL" if not passing else "OVERTURNED"}


def main():
    print("K1116d sensitivity: drop STLFSI from finstress + all")
    market = fetch_spy_vix_weekly()
    vintage = load_vintage_two_views()
    revised = load_revised_two_views()

    v_cycle = run_no_stlfsi(market, vintage["weekly_mean"], vintage["pit"],
                            "vintage no_stlfsi")
    r_cycle = run_no_stlfsi(market, revised["weekly_mean"], revised["pit"],
                            "revised no_stlfsi")

    print(f"\nvintage no_stlfsi: {v_cycle['verdict']}  passing={v_cycle['passing']}")
    print(f"revised no_stlfsi: {r_cycle['verdict']}  passing={r_cycle['passing']}")

    # print DM t-stat table
    for cyc in [v_cycle, r_cycle]:
        print(f"\n--- {cyc['label']} ---")
        print(f"{'Variant':25s} {'base':>8s} {'epu':>8s} {'finstress':>10s} {'all':>8s}")
        for v in ["orig_shift1", "corrected_shift2", "conservative_shift2",
                  "pit_shift0", "pit_shift1", "multi_lag_3"]:
            row = f"{v:25s}"
            for spec in ["base", "epu", "finstress", "all"]:
                t = cyc["dm_table"].get(v, {}).get(spec, {}).get("t")
                width = 10 if spec == "finstress" else 8
                row += f" {t:+{width}.3f}" if t is not None and not (
                    isinstance(t, float) and np.isnan(t)) else f" {'n/a':>{width}s}"
            print(row)

    out = {
        "vintage_no_stlfsi": v_cycle,
        "revised_no_stlfsi": r_cycle,
        "interpretation": (
            "If both verdicts remain H2_ROBUST_NULL after dropping STLFSI, "
            "the chain-vs-backfill comparator concern (Codex MINOR) does not "
            "drive the NULL — it is robust to STLFSI exclusion."
        ),
    }
    with open(HERE / "k1116d_sensitivity_no_stlfsi.json", "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {HERE / 'k1116d_sensitivity_no_stlfsi.json'}")


if __name__ == "__main__":
    main()
