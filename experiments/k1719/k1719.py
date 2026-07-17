#!/usr/bin/env python3
"""K1719: Does self-owned TAIFEX tick (5-min RV) beat daily-only information
for next-day TX day-session volatility forecasting?

Economic question (owner ruling 2026-07-14): the platform replaced a paid US
intraday data line with self-owned TAIFEX tick. If an intraday-RV regressor set
does not beat a daily-only regressor set on the same target, same ledger and
same loss, the marginal forecasting value of the tick line is zero and the
cheaper daily-only path is defensible. A NULL here is a cost decision, not a
failure.

Design (deliberately symmetric -- no tuning advantage for either side):

  HAR-RV5    :  y_t ~ b0 + bd*RV5_{t-1} + bw*mean(RV5_{t-5..t-1}) + bm*mean(RV5_{t-22..t-1})
  HAR-DAILY  :  y_t ~ b0 + bd*r2_{t-1}  + bw*mean(r2_{t-5..t-1})  + bm*mean(r2_{t-22..t-1})

Identical HAR(d/w/m) spec, identical rolling window, identical refit cadence,
identical insanity filter, identical evaluation ledger. The ONLY difference is
whether the regressors are built from 5-min intraday RV or from the daily
open-to-close squared return.

Two targets, because the target choice itself is biased:
  A) rv_5min   -- shares measurement error with the HAR-RV5 regressors (favours HAR-RV5)
  B) r2        -- shares measurement error with the HAR-DAILY regressors (favours HAR-DAILY)
Patton (2011) shows QLIKE gives a consistent ranking under any conditionally
unbiased proxy, so agreement across A and B is the robust result; disagreement
localises the win to a same-source artifact. Neither target is treated as truth.

Sample is day-session only (rv_5min == rv_day for every row), which is
homogeneous across the 2017-05-16 night-session launch -- the night regime
change cannot contaminate this design, so no regime split is needed.

Lag discipline: every regressor entering the forecast for day t is built from
data at t-1 or earlier (explicit .shift(1)); the training set for origin t only
contains pairs (X_s, y_s) with s <= t-1. No future bar is used.

FORECAST ORIGIN (stated explicitly, because it is what makes the design legal):
the forecast for day t is formed **just before the day session opens at 08:45
on day t**, and predicts that day's 08:45-13:45 realized variance. This matters
because the upstream collector picks the active contract with
``pick_active_contract()`` using each file's TOTAL volume, and a TAIFEX daily
file carries both the day session and that evening's night session (night ticks
are stamped with the evening's calendar date). So day t-1's contract choice
embeds volume traded up to 05:00 on day t. Under an 08:45 origin every one of
those ticks is already realized and observable, so the selection is legitimately
in the information set. Under a "13:45 on t-1" origin it would NOT be -- that
would be an economic-clock lookahead. The 08:45 origin is also the operationally
natural one: a desk forms today's variance forecast before today's open.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

def _main_repo() -> Path:
    """Resolve the main checkout, which owns canonical data/ and src/.

    Inside a git worktree the code lives here but data/ does not, so derive the
    main repo from the shared git dir instead of hard-coding a path. Read-only:
    this experiment never writes outside its own directory.
    """
    here = Path(__file__).resolve()
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=here.parent, capture_output=True, text=True, check=True,
    ).stdout.strip()
    return Path(common).resolve().parent


REPO = _main_repo()
sys.path.insert(0, str(REPO / "src"))

from volpred.evaluation.metrics import qlike  # noqa: E402
from volpred.stats.model_evaluation import dm_test  # noqa: E402

SEED = 42
WINDOW = 1000           # rolling in-sample rows (not necessarily 1000 valid obs)
HARVEY_T = 3.0          # Harvey (2016) significance bar
DATA = REPO / "data" / "intraday" / "taifex_5min_rv.csv"
OUT = Path(__file__).resolve().parent / "k1719_results.json"

np.random.seed(SEED)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def har_features(x: pd.Series) -> pd.DataFrame:
    """HAR daily/weekly/monthly regressors, all lagged one day.

    Column d is x_{t-1}; w is mean(x_{t-5..t-1}); m is mean(x_{t-22..t-1}).
    The .shift(1) is what makes the forecast for day t use only <= t-1.
    """
    lagged = x.shift(1)
    return pd.DataFrame({
        "d": lagged,
        "w": lagged.rolling(5).mean(),
        "m": lagged.rolling(22).mean(),
    })


def rolling_oos(X: np.ndarray, y: np.ndarray, valid: np.ndarray) -> tuple[np.ndarray, dict]:
    """Rolling-window OLS with a BPQ(2016)-style insanity filter.

    For origin t the fit uses rows [t-WINDOW, t-1] only. A forecast that lands
    outside the in-sample support (or non-positive) is replaced by the in-sample
    mean -- applied identically to both models so neither is advantaged. The
    filter fires at different rates across models (that is model behaviour, not
    asymmetric code), so the trigger count is reported rather than hidden.
    """
    n = len(y)
    fc = np.full(n, np.nan)
    n_filtered = 0
    n_forecast = 0
    n_train_obs = []
    for t in range(WINDOW, n):
        lo = t - WINDOW
        tr = valid[lo:t]
        if tr.sum() < WINDOW // 2:
            continue
        Xtr = X[lo:t][tr]
        ytr = y[lo:t][tr]
        if not np.isfinite(X[t]).all():
            continue
        A = np.column_stack([np.ones(len(Xtr)), Xtr])
        beta, *_ = np.linalg.lstsq(A, ytr, rcond=None)
        pred = float(beta[0] + beta[1:] @ X[t])
        lo_b, hi_b, mu = ytr.min(), ytr.max(), ytr.mean()
        if not np.isfinite(pred) or pred <= 0 or pred < lo_b or pred > hi_b:
            pred = float(mu)          # insanity filter
            n_filtered += 1
        fc[t] = pred
        n_forecast += 1
        n_train_obs.append(int(tr.sum()))
    diag = {
        "n_forecasts": n_forecast,
        "n_insanity_filtered": n_filtered,
        "insanity_filter_rate_pct": (100.0 * n_filtered / n_forecast) if n_forecast else 0.0,
        "train_obs_min": int(min(n_train_obs)) if n_train_obs else 0,
        "train_obs_max": int(max(n_train_obs)) if n_train_obs else 0,
    }
    return fc, diag


def evaluate(actual: np.ndarray, f_rv5: np.ndarray, f_daily: np.ndarray,
             dates: pd.Series, target_valid: np.ndarray, label: str) -> dict:
    """Common-ledger comparison: both models scored on identical days."""
    ledger = target_valid & np.isfinite(f_rv5) & np.isfinite(f_daily) & (actual > 0)
    a = actual[ledger]
    p1 = f_rv5[ledger]
    p2 = f_daily[ledger]
    n = int(ledger.sum())

    q_rv5 = float(qlike(a, p1))
    q_daily = float(qlike(a, p2))
    # per-day loss for DM (canonical qlike() returns the mean)
    l_rv5 = a / p1 - np.log(a / p1) - 1.0
    l_daily = a / p2 - np.log(a / p2) - 1.0
    t_stat, p_val = dm_test(l_rv5, l_daily, h=1)   # negative t -> HAR-RV5 better
    # Record the HAC bandwidth dm_test() actually used (it floors at 1, so it
    # never degenerates to the no-correction h=1 case of the K1655 bug class).
    hac_lag = max(1, min(int(np.ceil(1 ** (1 / 3) * n ** (1 / 3))), n // 4))
    d = l_rv5 - l_daily
    acf1 = float(np.corrcoef(d[:-1], d[1:])[0, 1]) if n > 2 else float("nan")

    if abs(t_stat) > HARVEY_T:
        verdict = "HAR_RV5_WINS" if t_stat < 0 else "HAR_DAILY_WINS"
    else:
        verdict = "NULL"

    return {
        "target": label,
        "n_test": n,
        "ledger_start": str(dates[ledger].iloc[0]),
        "ledger_end": str(dates[ledger].iloc[-1]),
        "qlike_har_rv5": q_rv5,
        "qlike_har_daily": q_daily,
        "qlike_diff_rv5_minus_daily": q_rv5 - q_daily,
        "qlike_pct_improvement_rv5_vs_daily": float((q_daily - q_rv5) / q_daily * 100.0),
        "dm_t": float(t_stat),
        "dm_p": float(p_val),
        "dm_sign_convention": "negative t => HAR-RV5 lower QLIKE => intraday helps",
        "dm_hac_bandwidth": int(hac_lag),
        "dm_impl": "volpred.stats.model_evaluation.dm_test (Newey-West, bandwidth floored at 1)",
        "loss_diff_acf1": acf1,
        "harvey_significant": bool(abs(t_stat) > HARVEY_T),
        "verdict": verdict,
    }


def main() -> None:
    df = pd.read_csv(DATA).sort_values("date").reset_index(drop=True)

    # shift(1) means "previous row"; it only means "previous trading day" if the
    # date index is unique and strictly increasing. Assert rather than assume.
    assert df["date"].is_unique, "duplicate dates -- shift(1) would not be a day lag"
    assert df["date"].is_monotonic_increasing, "dates not sorted ascending"

    # --- construct the two information sets -------------------------------
    # rv_5min is the day-session (08:45-13:45) 5-min realized variance.
    # r2 is the day-session open-to-close squared return: the ONLY variance
    # signal obtainable without any intraday data.
    df["r2"] = df["day_return"] ** 2

    # Day-session homogeneity check: rv_5min must equal rv_day everywhere, else
    # the night-session regime change (2017-05-16) would leak in.
    assert np.allclose(df["rv_5min"], df["rv_day"], equal_nan=True), \
        "rv_5min != rv_day -- sample is not day-session-only"

    f_rv5_feat = har_features(df["rv_5min"])
    f_r2_feat = har_features(df["r2"])

    X_rv5 = f_rv5_feat.to_numpy(dtype=float)
    X_r2 = f_r2_feat.to_numpy(dtype=float)
    feat_ok = np.isfinite(X_rv5).all(axis=1) & np.isfinite(X_r2).all(axis=1)

    y_rv = df["rv_5min"].to_numpy(dtype=float)
    y_r2 = df["r2"].to_numpy(dtype=float)

    # Training rows need a positive target and finite features. Non-positive
    # actuals are dropped, never clipped to a small positive number (K1704).
    tr_rv = feat_ok & np.isfinite(y_rv) & (y_rv > 0)
    tr_r2 = feat_ok & np.isfinite(y_r2) & (y_r2 > 0)

    results = {}
    for tgt_label, y, tr_valid in [("rv_5min", y_rv, tr_rv), ("daily_r2", y_r2, tr_r2)]:
        f_rv5, diag_rv5 = rolling_oos(X_rv5, y, tr_valid)
        f_daily, diag_daily = rolling_oos(X_r2, y, tr_valid)
        results[tgt_label] = {
            "diagnostics": {"HAR_RV5": diag_rv5, "HAR_DAILY": diag_daily},
            "full": evaluate(y, f_rv5, f_daily, df["date"], tr_valid, tgt_label),
            # 2017-05-16+ subsample: comparable to the K1301/K1303/K1309 TX1 ledger
            "sub_2017on": evaluate(
                y, f_rv5, f_daily, df["date"],
                tr_valid & (df["date"] >= "2017-05-16").to_numpy(),
                tgt_label + "@2017on",
            ),
        }

    # --- excluded-day audit ----------------------------------------------
    zero_rv = df.loc[df["rv_5min"] <= 0, ["date", "day_n_ticks", "day_open", "day_close"]]
    zero_r2 = df.loc[df["r2"] <= 0, "date"]

    agree = (results["rv_5min"]["full"]["verdict"] == results["daily_r2"]["full"]["verdict"])
    both_null = (results["rv_5min"]["full"]["verdict"] == "NULL"
                 and results["daily_r2"]["full"]["verdict"] == "NULL")
    if both_null:
        overall = "NULL"
    elif agree:
        overall = results["rv_5min"]["full"]["verdict"] + "_ROBUST_ACROSS_PROXIES"
    else:
        overall = "PROXY_DEPENDENT_INCONCLUSIVE"

    payload = {
        "experiment_id": "K1719",
        "title": "Self-owned TAIFEX tick (5-min RV) vs daily-only information for next-day TX day-session RV",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "verdict": overall,
        "hypothesis": {
            "H0": "E[QLIKE(HAR-DAILY)] - E[QLIKE(HAR-RV5)] = 0 (intraday RV adds nothing over daily-only info)",
            "H1": "HAR-RV5 attains strictly lower QLIKE on a common ledger",
            "decision_rule": "Harvey (2016) |DM t| > 3.0 on BOTH proxy targets for a robust claim",
        },
        "data": {
            "source_csv": str(DATA.relative_to(REPO)),
            "source_sha256": sha256(DATA),
            "contract": "TX active monthly (same_day_max_total_volume rule, per collector)",
            "session": "day session 08:45-13:45 only (rv_5min == rv_day verified)",
            "n_rows_total": int(len(df)),
            "date_min": str(df["date"].min()),
            "date_max": str(df["date"].max()),
            "night_session_note": (
                "Night session exists only from 2017-05-16, but this design uses the "
                "day session exclusively, so the regime change does not enter the sample."
            ),
        },
        "models": {
            "HAR_RV5": "HAR(d/w/m) on 5-min intraday RV regressors",
            "HAR_DAILY": "HAR(d/w/m) on daily open-to-close squared-return regressors",
            "symmetry": (
                "Identical spec, rolling window, refit cadence, insanity filter and ledger. "
                "No hyperparameter was tuned for either model."
            ),
            "estimation": "level-space OLS, rolling window, refit every origin",
            "window": WINDOW,
            "insanity_filter": "forecast outside in-sample [min,max] or <=0 -> in-sample mean (BPQ 2016)",
            "lag": "all regressors .shift(1); training pairs for origin t end at t-1",
        },
        "results": results,
        "exclusions": {
            "zero_rv_days": {
                "n": int(len(zero_rv)),
                "dates": zero_rv["date"].tolist(),
                "detail": zero_rv.to_dict("records"),
                "reason": (
                    "Price frozen for the entire session (open == close, a few hundred ticks "
                    "vs ~30k typical), i.e. limit-lock. RV=0 is a true market outcome, not a "
                    "data hole, but QLIKE is undefined at actual=0, so these days are dropped "
                    "from the ledger rather than clipped to a small positive value."
                ),
            },
            "zero_r2_days": {
                "n": int(len(zero_r2)),
                "dates": zero_r2.tolist(),
                "reason": "day_return == 0 exactly -> r2 = 0 -> QLIKE undefined on the daily_r2 target.",
            },
            "warmup": "first 22 rows lack HAR monthly features; first OOS origin at row %d." % WINDOW,
        },
        "forecast_origin": (
            "08:45 on day t, immediately before the day session opens; predicts day t's "
            "08:45-13:45 realized variance. All t-1 information (including the t-1 evening "
            "night session, which ends 05:00 on day t) is realized and observable by then."
        ),
        "caveats": [
            "Neither target is the latent integrated variance; both are noisy proxies.",
            "No neutral third proxy (e.g. Parkinson range) was used: the canonical 5-min RV "
            "layer stores no session high/low, and TWII spot OHLC is a different asset (basis).",
            "Result speaks to the day session only; it does not test the night session or "
            "any options-tick signal.",
            "SCOPE LIMIT ON THE COST CLAIM (Codex review): the HAR-DAILY baseline's day_return "
            "is itself computed from tick by the collector. The baseline's INFORMATION SET is "
            "daily-only (day-session open and close are published in TAIFEX's free daily "
            "settlement data), but this experiment did not source it end-to-end from an "
            "external daily feed. It therefore establishes whether 5-min RV beats "
            "daily-compressed information -- not that an external cheap daily feed could "
            "replace the tick pipeline byte-for-byte.",
            "Active-contract selection uses each day's TOTAL (day+night) volume, so the choice "
            "for day t-1 is only in the information set under the stated 08:45-on-t origin. "
            "A 13:45-on-t-1 origin would make it an economic-clock lookahead.",
        ],
        "code_sha256": sha256(Path(__file__)),
    }

    tmp = OUT.with_suffix(".json.tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    with open(tmp) as f:
        json.load(f)          # re-parse before publishing
    os.replace(tmp, OUT)

    for tl in ("rv_5min", "daily_r2"):
        r = results[tl]["full"]
        print(f"[{tl:9s}] n={r['n_test']:5d}  QLIKE rv5={r['qlike_har_rv5']:.6f} "
              f"daily={r['qlike_har_daily']:.6f}  DM t={r['dm_t']:+.3f} p={r['dm_p']:.4f}  -> {r['verdict']}")
    print("OVERALL:", overall)


if __name__ == "__main__":
    main()
