#!/usr/bin/env python3
"""
K903 extension: verify GLD rolling gamma subwindow claim for 2025-2026.

Uses local paper CSV and K903's unconstrained GJR fit to avoid network drift.
"""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = OUT_DIR / "k903_extension_gld_2025_2026_subwindow_results.json"
DATA_PATH = ROOT / "paper" / "leverage-direction" / "data" / "spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv"
K903_PATH = ROOT / "experiments" / "k903" / "k903.py"

WINDOW = 504
STEP = 63
SUBWINDOW_START = pd.Timestamp("2025-01-01")
SUBWINDOW_END = pd.Timestamp("2026-04-16")
FULL_START = pd.Timestamp("2010-01-01")
REQUESTED_HAC_LAGS = 8


def load_k903_module():
    spec = importlib.util.spec_from_file_location("k903_module", K903_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def hac_tstat(values, requested_lags=8):
    arr = np.asarray(values, dtype=np.float64)
    n = len(arr)
    if n < 2:
        return {"t_stat": 0.0, "effective_lags": 0}
    mean = float(arr.mean())
    d = arr - mean
    gamma0 = float(np.mean(d ** 2))
    effective_lags = max(1, min(requested_lags, n // 4))
    var = gamma0
    for lag in range(1, effective_lags + 1):
        weight = 1 - lag / (effective_lags + 1)
        gamma_l = float(np.mean(d[lag:] * d[:-lag]))
        var += 2 * weight * gamma_l
    var = max(var, 1e-20)
    se = np.sqrt(var / n)
    t_stat = mean / se if se > 1e-12 else 0.0
    return {"t_stat": float(t_stat), "effective_lags": int(effective_lags)}


def build_rolling_windows(returns, fit_gjr_unconstrained):
    r = returns.to_numpy(dtype=np.float64)
    dates = returns.index
    rows = []
    for start in range(0, len(r) - WINDOW, STEP):
        end = start + WINDOW
        chunk = r[start:end]
        params = fit_gjr_unconstrained(chunk, n_starts=3)
        if params is None:
            continue
        rows.append(
            {
                "window_start": str(dates[start].date()),
                "window_end": str(dates[end - 1].date()),
                "gamma": float(params["gamma"]),
                "alpha": float(params["alpha"]),
                "beta": float(params["beta"]),
                "persistence": float(params["persistence"]),
            }
        )
    return rows


def summarize(rows):
    gammas = np.asarray([row["gamma"] for row in rows], dtype=np.float64)
    hac = hac_tstat(gammas, REQUESTED_HAC_LAGS)
    return {
        "n_windows": int(len(rows)),
        "mean_gamma": float(gammas.mean()) if len(gammas) else None,
        "std_gamma": float(gammas.std()) if len(gammas) else None,
        "pct_negative": float(100 * np.mean(gammas < 0)) if len(gammas) else None,
        "min_gamma": float(gammas.min()) if len(gammas) else None,
        "max_gamma": float(gammas.max()) if len(gammas) else None,
        "hac_tstat": hac["t_stat"],
        "hac_requested_lags": REQUESTED_HAC_LAGS,
        "hac_effective_lags": hac["effective_lags"],
    }


def main():
    k903 = load_k903_module()
    df = pd.read_csv(DATA_PATH, parse_dates=["date"])
    df = df.set_index("date").sort_index()
    prices = df["gld_adj_close"].dropna()
    returns = prices.pct_change().dropna()
    returns = returns[(returns.index >= FULL_START) & (returns.index <= SUBWINDOW_END)]

    rolling_rows = build_rolling_windows(returns, k903.fit_gjr_unconstrained)
    subwindow_rows = [
        row for row in rolling_rows
        if SUBWINDOW_START <= pd.Timestamp(row["window_end"]) <= SUBWINDOW_END
    ]

    full_summary = summarize(rolling_rows)
    subwindow_summary = summarize(subwindow_rows)

    paper_claim = {"mean_gamma": -0.089, "pct_negative": 100.0}
    verdict = "reproduced"
    if not subwindow_rows:
        verdict = "no_windows"
    else:
        mean_close = abs(subwindow_summary["mean_gamma"] - paper_claim["mean_gamma"]) <= 0.01
        pct_close = abs(subwindow_summary["pct_negative"] - paper_claim["pct_negative"]) <= 1.0
        if not (mean_close and pct_close):
            verdict = "not_reproduced"

    results = {
        "experiment_id": "k903_extension_gld_2025_2026_subwindow",
        "title": "K903 extension: GLD 2025-2026 rolling gamma subwindow verification",
        "data_source": str(DATA_PATH.relative_to(ROOT)),
        "asset": "GLD",
        "methodology": {
            "returns": "gld_adj_close.pct_change()",
            "rolling_window": WINDOW,
            "rolling_step": STEP,
            "full_start": str(FULL_START.date()),
            "subwindow_start": str(SUBWINDOW_START.date()),
            "subwindow_end": str(SUBWINDOW_END.date()),
            "model": "GJR-GARCH unconstrained gamma (imported from experiments/k903/k903.py)",
        },
        "paper_claim": paper_claim,
        "full_sample_summary": full_summary,
        "subwindow_summary": subwindow_summary,
        "subwindow_windows": subwindow_rows,
        "verdict": verdict,
        "conclusion": (
            "Paper subwindow claim reproduced."
            if verdict == "reproduced"
            else "Paper subwindow claim not reproduced."
        ),
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps(results["subwindow_summary"], indent=2, ensure_ascii=False))
    print(f"verdict={verdict}")


if __name__ == "__main__":
    main()
