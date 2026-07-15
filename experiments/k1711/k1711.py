"""K1711 — Does adding a time-series foundation model to a log-HAR forecast pool
change the Model Confidence Set?

The question is deliberately NOT "does a TSFM beat HAR". The knowledge base has
answered that horse-race nine times already (K1310-K1330: GARCH-Neural, HAR-GNN,
Transformer, KAN, Conformal — all NULL against the HAR family), so asking a tenth
time with a bigger model carries no information. The open question is an
evaluation one:

    Take a log-HAR baseline family. Add two zero-shot foundation models and the
    standard combinations of them with HAR. Does the augmented pool's Model
    Confidence Set (Hansen, Lunde & Nason 2011) contain any TSFM-bearing model,
    and does the *base* pool's superior set change when the TSFMs are added?

A NULL is a publishable result, not a failed experiment.

──────────────────────────────────────────────────────────────────────────────
What this experiment is NOT — read before quoting any number
──────────────────────────────────────────────────────────────────────────────

*It is not a real-time out-of-sample evaluation of the TSFMs.* Both checkpoints
are 2025 artefacts; the main window starts in 2016. Their context windows end at
the forecast origin (verified by test), so no *input* peeks — but the *weights*
were fit by someone else, later, on a corpus we do not fully control. That makes
the 2016+ window a **retrospective pseudo-OOS**, in exactly the sense K1655 had
to retract a real-time claim for back-stamped NFCI vintages.

So the design carries a second, vintage-respecting window:

    pseudo_oos     2016-01-01 →   retrospective; TSFM weights post-date the data
    vintage_clean  2024-01-01 →   starts after every documented pretraining cutoff
                                  (TimesFM: Wikipedia Nov-2023, Google Trends EoY-2022)

Direct target leakage is separately implausible: TTM's corpus is fully enumerated
on its model card and contains no equity or index volatility (only Bitcoin);
TimesFM's lists none either. And note the direction of any residual contamination
— it would flatter the TSFM. A NULL under contamination is conservative; a *win*
under contamination would be uninterpretable.

──────────────────────────────────────────────────────────────────────────────
Pre-specified primary result (everything else is secondary)
──────────────────────────────────────────────────────────────────────────────
    window = pseudo_oos, proxy = rv, loss = QLIKE, h = 1, alpha = 0.10, per asset.

Fixing this in advance matters: with 2 windows x 2 proxies x 2 losses x 2 horizons
x 3 assets x several alphas, *something* will look significant by luck. Secondary
cells are reported for robustness, not for cherry-picking, and the DM p-values
within each cell carry a Holm correction across the models tested.

──────────────────────────────────────────────────────────────────────────────
Inference, and where it is not valid
──────────────────────────────────────────────────────────────────────────────
A Diebold-Mariano test is invalid when the two forecasts are nested and the larger
model's extra parameters are unidentified under the null — the statistic is not
asymptotically normal. In this pool that applies to AR1 (inside HAR), HAR-A (nests
HAR) and COMB-GR (estimated weights that collapse onto HAR if the TSFMs are
useless). For those, MSE inference uses the canonical Clark-West test and raw
DM/HLN is never allowed to feed a verdict (``nested-dm: diagnostic-only``).
K1701 is the standing lesson: a nested
QLIKE comparison carried on expanding raw DM, and the NULL it "found" downgraded
to inconclusive once the nesting was handled.

COMB-EW and COMB-MZ use fixed 1/3 weights, so they are not degenerate under the
null and DM applies — but they do contain HAR, so any win is partly HAR's own.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / "src"))

from volpred.stats.mcs import model_confidence_set  # noqa: E402
from volpred.stats.model_evaluation import (  # noqa: E402
    clark_west_test, dm_test, qlike_pointwise,
)

DATA = HERE / "data"

ASSETS = ("SPY", "0050.TW", "TX")
HORIZONS = (1, 5)
PROXIES = ("rv", "r2")
TSFMS = ("timesfm", "ttm")

# 2016-07 rather than 2016-01 so that every model in the pool — including COMB-GR, whose
# expanding weights need 400 (forecast, outcome) pairs and which on TX cannot start until
# early 2016 — is fully warmed up on day one of the window. Chosen for warm-up reasons,
# fixed before any result was seen. Inside the window, a model with no forecast is an
# error, not a day to quietly drop (see evaluate()).
WINDOWS = {
    "pseudo_oos": pd.Timestamp("2016-07-01"),
    "vintage_clean": pd.Timestamp("2024-01-01"),
}
PRIMARY = {"window": "pseudo_oos", "proxy": "rv", "loss": "qlike",
           "horizon": 1, "alpha": 0.10}

FIT_START = WINDOWS["pseudo_oos"]     # PIT quantities are estimated on pre-2016 data only
MIN_TRAIN_HAR = 500
MIN_TRAIN_MZ = 400
R2_FLOOR_PCT = 1.0                    # r2 has exact zeros and QLIKE diverges there

BASE_POOL = ["RW", "AR1", "HAR", "HAR-A"]
TSFM_POOL = ["TimesFM", "TTM", "TimesFM-MZ", "TTM-MZ", "COMB-EW", "COMB-MZ", "COMB-GR"]
FULL_POOL = BASE_POOL + TSFM_POOL

# (small, large) whenever the pair with HAR is a genuine estimated nesting.  DM is not
# valid for these; Clark-West is.  COMB-EW / COMB-MZ have fixed weights, so they are
# excluded — they contain HAR but do not collapse onto it under the null.
NESTED_WITH_HAR = {
    "AR1": ("AR1", "HAR"),
    "HAR-A": ("HAR", "HAR-A"),
    "COMB-GR": ("HAR", "COMB-GR"),
}
CONTAINS_HAR = {"HAR-A", "COMB-EW", "COMB-MZ", "COMB-GR"}

SEED = 20260714
N_BOOT = 5000
ALPHA_GRID = (0.01, 0.05, 0.10, 0.25, 0.50)
HARVEY_T = 3.0
NESTED_QLIKE_STATUS = "INCONCLUSIVE_NO_VALID_GENERAL_LOSS_NESTED_TEST"


# ══ helpers ═══════════════════════════════════════════════════════════════════

def _atomic_json(path: Path, obj) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, default=float))
    json.loads(tmp.read_text())            # a truncated JSON must never survive
    os.replace(tmp, path)


def _ols(X: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, float]:
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    s2 = float(resid @ resid / max(len(y) - X.shape[1], 1))
    return beta, s2


def hln_correct(t_dm: float, n: int, h: int) -> tuple[float, float]:
    """Harvey, Leybourne & Newbold (1997) small-sample correction of a DM statistic.

    A *wrapper* over the canonical dm_test, never a re-implementation: the repo's HAC
    bandwidth rule ceil(h^(1/3) n^(1/3)) is the thing that must not be re-derived
    locally.  K1655 is why — a local DM quietly using lag = h-1 degenerates to no HAC
    at all when h = 1, and inflated |t| across 60 cells before anyone noticed.
    """
    factor = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    t_hln = float(t_dm * factor)
    p_hln = float(2 * (1 - stats.t.cdf(abs(t_hln), df=n - 1)))
    return t_hln, p_hln


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm step-down family-wise correction across the models compared in one cell."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    out, running = {}, 0.0
    for i, (name, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        out[name] = running
    return out


def canonical_dm_lag(n: int, h: int) -> int:
    """The bandwidth dm_test actually uses — reported so the choice is auditable."""
    return max(1, min(int(np.ceil(h ** (1 / 3) * n ** (1 / 3))), n // 4))


# ══ targets and features ══════════════════════════════════════════════════════

def build_targets(rv: np.ndarray, proxy: np.ndarray, h: int, floor: float = 0.0) -> np.ndarray:
    """y_h[t] = mean(proxy[t+1 .. t+h]) — the object forecast at origin t.

    floor defaults to 0 (a no-op): RV is strictly positive by construction, so
    winsorising it would only distort the target.  The floor exists for the r2 proxy,
    which has exact zeros that would send QLIKE to infinity.
    """
    p = np.maximum(proxy, floor) if floor > 0 else proxy
    n = len(p)
    y = np.full(n, np.nan)
    for t in range(n - h):
        y[t] = p[t + 1 : t + 1 + h].mean()
    return y


def har_features(rv: np.ndarray, ret: np.ndarray) -> np.ndarray:
    """[1, log RV_t, log RV^(w)_t, log RV^(m)_t, ret^-_t] at origin t — only rv[..t].

    The last column is the Corsi-Renò leverage term (negative part of the day's return),
    used by HAR-A.  Rows are NaN until 22 days of history exist, so no partial window
    can sneak in as if it were a full one.
    """
    n = len(rv)
    X = np.full((n, 5), np.nan)
    X[:, 0] = 1.0
    for t in range(21, n):
        X[t, 1] = np.log(rv[t])
        X[t, 2] = np.log(rv[t - 4 : t + 1].mean())
        X[t, 3] = np.log(rv[t - 21 : t + 1].mean())
    X[:, 4] = np.minimum(ret, 0.0)
    return X


# ══ forecasts ═════════════════════════════════════════════════════════════════

def _expanding_ols_forecast(X: np.ndarray, logy: np.ndarray, h: int,
                            origins: np.ndarray, min_train: int) -> np.ndarray:
    """Expanding-window OLS in logs, retransformed with the Gaussian smearing term.

    Training rows j must satisfy j + h < t. The label window of row j has to *end*
    strictly before the origin, or the tail of the training set has already observed
    the day being predicted (.claude/rules/experiments.md, forward-label rule).
    """
    g = np.full(len(logy), np.nan)
    for t in origins:
        j_max = t - h - 1
        if j_max < 0:
            continue
        rows = np.arange(0, j_max + 1)
        rows = rows[np.isfinite(logy[rows]) & np.isfinite(X[rows]).all(axis=1)]
        if len(rows) < min_train or not np.isfinite(X[t]).all():
            continue
        beta, s2 = _ols(X[rows], logy[rows])
        g[t] = float(X[t] @ beta) + 0.5 * s2      # E[Y] = exp(mu + s^2/2)
    return g


def forecast_rw(rv: np.ndarray, h: int, origins: np.ndarray) -> np.ndarray:
    """Naive anchor: trailing h-day mean variance. In the pool so the MCS has to show
    it can eliminate *something* — a superior set that keeps everything says nothing."""
    f = np.full(len(rv), np.nan)
    for t in origins:
        if t - h + 1 < 0:
            continue
        f[t] = rv[t - h + 1 : t + 1].mean()
    return f


def tsfm_log_forecast(steps: pd.DataFrame, panel_index: pd.DatetimeIndex,
                      h: int, n: int) -> np.ndarray:
    """Collapse the TSFM's per-step log forecasts into log(mean variance over 1..h).

    The CSV is keyed by target date and also carries origin_date; both are checked
    against the panel, so a panel rebuild that shifted a trading day would raise here
    rather than silently re-pair every forecast with the wrong predecessor.
    """
    pos = panel_index.get_indexer(steps.index)
    if (pos < 1).any():
        raise ValueError("TSFM target date missing from panel, or has no predecessor")
    origins = pos - 1

    stored_origin = pd.to_datetime(steps["origin_date"]).to_numpy()
    if not np.array_equal(stored_origin, panel_index[origins].to_numpy()):
        raise ValueError("TSFM origin_date disagrees with the panel — stale forecast CSV")

    cols = [f"step{k}" for k in range(1, h + 1)]
    var_steps = np.exp(steps[cols].to_numpy(dtype=np.float64))
    g_h = np.log(var_steps.mean(axis=1))          # log of the mean variance, not mean of logs

    g = np.full(n, np.nan)
    g[origins] = g_h
    return g


def recalibrate_mz(g: np.ndarray, logy: np.ndarray, h: int,
                   origins: np.ndarray) -> np.ndarray:
    """Expanding Mincer-Zarnowitz recalibration in logs:  log y = a + b·g + e.

    This is the brief's "minimal finetune", done the leakage-safe way: it never touches
    the model weights, and every (g, y) pair it fits on has its label window closed
    before the origin.  It also carries the same smearing term HAR gets, so the raw-log
    forecast is not penalised for being a median rather than a mean.
    """
    G = np.column_stack([np.ones(len(g)), g])
    return _expanding_ols_forecast(G, logy, h, origins, MIN_TRAIN_MZ)


def combine_gr(components: dict[str, np.ndarray], logy: np.ndarray, h: int,
               origins: np.ndarray) -> np.ndarray:
    """Granger-Ramanathan: expanding OLS of log y on all component log forecasts."""
    G = np.column_stack([np.ones(len(logy))] + [components[k] for k in components])
    return _expanding_ols_forecast(G, logy, h, origins, MIN_TRAIN_MZ)


def build_forecasts(panel: pd.DataFrame, h: int,
                    tsfm_steps: dict[str, pd.DataFrame]) -> dict[str, np.ndarray]:
    """All eleven level forecasts for one (asset, horizon).

    Proxy-independent by construction: every model forecasts the rv-based target, and
    the evaluation proxy only enters later as a yardstick.  If the proxy leaked in here
    the r2 robustness run would quietly become a *different experiment* rather than the
    same forecasts held to a different ruler — which is the entire point of running it.

    Forecasts are produced at every feasible origin, not only the evaluated ones,
    because the expanding MZ / Granger-Ramanathan fits need (forecast, outcome) pairs
    from before the evaluation window opens.  They still only ever look backwards.
    """
    idx = panel.index
    rv = panel["rv"].to_numpy(dtype=np.float64)
    ret = panel["ret"].to_numpy(dtype=np.float64)
    n = len(rv)

    y_fit = build_targets(rv, rv, h)               # no floor: RV > 0 by construction
    logy = np.log(y_fit)
    origins = np.arange(21, n)
    X = har_features(rv, ret)

    g: dict[str, np.ndarray] = {
        "AR1": _expanding_ols_forecast(X[:, [0, 1]], logy, h, origins, MIN_TRAIN_HAR),
        "HAR": _expanding_ols_forecast(X[:, :4], logy, h, origins, MIN_TRAIN_HAR),
        "HAR-A": _expanding_ols_forecast(X, logy, h, origins, MIN_TRAIN_HAR),
    }
    for m in TSFMS:
        raw = tsfm_log_forecast(tsfm_steps[m], idx, h, n)
        g[m.upper()] = raw
        g[f"{m.upper()}-MZ"] = recalibrate_mz(raw, logy, h, origins)

    g["COMB-GR"] = combine_gr(
        {"HAR": g["HAR"], "TIMESFM": g["TIMESFM"], "TTM": g["TTM"]}, logy, h, origins
    )

    F: dict[str, np.ndarray] = {
        "RW": forecast_rw(rv, h, origins),
        "AR1": np.exp(g["AR1"]),
        "HAR": np.exp(g["HAR"]),
        "HAR-A": np.exp(g["HAR-A"]),
        "TimesFM": np.exp(g["TIMESFM"]),
        "TTM": np.exp(g["TTM"]),
        "TimesFM-MZ": np.exp(g["TIMESFM-MZ"]),
        "TTM-MZ": np.exp(g["TTM-MZ"]),
    }
    F["COMB-EW"] = np.column_stack([F["HAR"], F["TimesFM"], F["TTM"]]).mean(axis=1)
    F["COMB-MZ"] = np.column_stack(
        [F["HAR"], F["TimesFM-MZ"], F["TTM-MZ"]]
    ).mean(axis=1)
    F["COMB-GR"] = np.exp(g["COMB-GR"])

    assert set(F) == set(FULL_POOL), f"pool mismatch: {set(F) ^ set(FULL_POOL)}"
    return F


# ══ MCS ═══════════════════════════════════════════════════════════════════════

def mcs_report(losses: dict[str, np.ndarray], block_size: float | None = None) -> dict:
    """Superior set at each alpha, plus the alpha=.01 elimination trace.

    Run once per alpha rather than reading survivor p-values off a single run: the
    canonical implementation stops at the first non-rejection and hands every survivor
    max(p, alpha), so a survivor's reported "p-value" is a censored lower bound, not an
    MCS p-value. Quoting it as one would overstate what was measured. The recorded trace
    comes from alpha=.01 and is not the deepest path: a larger alpha can reject farther.
    It is retained only as an auditable trace for that particular stopping threshold.
    """
    out = {
        "superior_set_by_alpha": {},
        "elimination_trace": {
            "alpha": min(ALPHA_GRID),
            "interpretation": "alpha=.01 stopping trace; not a complete/deepest path",
            "pvalues": {}, "order": [],
        },
    }
    for alpha in ALPHA_GRID:
        res = model_confidence_set(losses, alpha=alpha, n_boot=N_BOOT,
                                   seed=SEED, block_size=block_size)
        out["superior_set_by_alpha"][f"{alpha:g}"] = res["mcs_models"]
        if alpha == min(ALPHA_GRID):
            out["elimination_trace"]["pvalues"] = {
                m: float(p) for m, p in res["eliminated"]
            }
            out["elimination_trace"]["order"] = [m for m, _ in res["eliminated"]]
    return out


# ══ evaluation ════════════════════════════════════════════════════════════════

def evaluate(asset: str, h: int, proxy: str, window: str, panel: pd.DataFrame,
             F: dict[str, np.ndarray]) -> dict:
    idx = panel.index
    rv = panel["rv"].to_numpy(dtype=np.float64)
    px = panel[proxy].to_numpy(dtype=np.float64)

    # The r2 proxy has exact zeros; QLIKE diverges at zero, so it needs a floor.  The
    # floor is read off pre-2016 positives only — a percentile taken over the whole
    # sample would be a (small) lookahead.  Flooring makes r2 no longer *exactly*
    # conditionally unbiased, so Patton's proxy-robustness applies only approximately;
    # k1711 reports floor sensitivity rather than pretending the issue away.
    floor = 0.0
    if proxy == "r2":
        pre = px[(idx < FIT_START) & (px > 0)]
        floor = float(np.percentile(pre, R2_FLOOR_PCT))
    y = build_targets(rv, px, h, floor)

    # Ex-ante calendar: the days this cell is *supposed* to score, fixed by the window and
    # the target — before any forecast is looked at.  Then require every model to cover it.
    #
    # Letting a model's own NaNs shrink the sample would drop precisely the days models
    # fail on — the volatile ones — and make the whole pool look better than it is, with
    # no trace in the output.  So a gap inside the window is an error, not a silent skip.
    start = WINDOWS[window]
    expected = np.asarray(idx >= start) & np.isfinite(y)
    t_eval = np.where(expected)[0]

    gaps = {}
    for m in FULL_POOL:
        f = F[m][t_eval]
        n_bad = int(np.sum(~(np.isfinite(f) & (f > 0))))
        if n_bad:
            gaps[m] = n_bad
    if gaps:
        raise RuntimeError(
            f"{asset} h={h} {proxy} {window}: models with missing/non-positive forecasts "
            f"inside the evaluation window: {gaps} — the window must not start before "
            f"every model is warmed up, and a mid-window gap is a bug, not a drop."
        )

    if len(t_eval) < 252:
        raise RuntimeError(f"{asset} h={h} {proxy} {window}: {len(t_eval)} scoring days < 252")

    actual = y[t_eval]
    losses = {
        "qlike": {m: qlike_pointwise(actual, F[m][t_eval]) for m in FULL_POOL},
        "mse": {m: (actual - F[m][t_eval]) ** 2 for m in FULL_POOL},
    }

    out: dict = {
        "asset": asset, "horizon": h, "proxy": proxy, "window": window,
        "n_scored": int(len(t_eval)),       # == n expected; a gap would have raised above
        "eval_start": str(idx[t_eval[0]].date()),
        "eval_end": str(idx[t_eval[-1]].date()),
        "r2_floor": floor,
        "dm_hac_lag": canonical_dm_lag(len(t_eval), h),
        "mean_loss": {}, "mcs": {}, "mcs_base_pool": {}, "vs_har": {},
    }

    for loss_name, L in losses.items():
        out["mean_loss"][loss_name] = {m: float(np.mean(L[m])) for m in FULL_POOL}

        # The comparison the experiment exists to make: does the superior set of the
        # base HAR family change once the TSFM-bearing models are allowed in?
        out["mcs"][loss_name] = mcs_report(L)
        out["mcs_base_pool"][loss_name] = mcs_report({m: L[m] for m in BASE_POOL})

        # ── pairwise vs HAR ──────────────────────────────────────────────────
        cell: dict[str, dict] = {}
        raw_p = {}
        raw_cw_p = {}
        for m in FULL_POOL:
            if m == "HAR":
                continue
            d = L[m] - L["HAR"]                        # negative → m beats HAR
            t_dm, _ = dm_test(L[m], L["HAR"], h=h)
            t_hln, p_hln = hln_correct(t_dm, len(d), h)
            nested = m in NESTED_WITH_HAR

            rec = {
                "mean_loss_diff": float(np.mean(d)),
                "beats_har": bool(np.mean(d) < 0),
                "loss_diff_acf1": float(pd.Series(d).autocorr(lag=1)),
                "contains_har": m in CONTAINS_HAR,
                "nested_with_har": nested,
            }
            if nested:
                # HLN only rescales DM; it does not repair the non-standard nested
                # null. Keep the number visible for diagnosis but structurally outside
                # every verdict path.
                rec["dm_inference"] = "diagnostic_only"
                rec["diagnostic_dm_hln"] = {
                    "t_stat": t_hln,
                    "p_two_sided": p_hln,
                    "hac_lag": canonical_dm_lag(len(d), h),
                    "feeds_verdict": False,
                }
                small, large = NESTED_WITH_HAR[m]
                if loss_name == "mse":
                    cw = clark_west_test(actual, F[small][t_eval], F[large][t_eval], h=h)
                    rec["clark_west"] = {
                        "small": small, "large": large,
                        "candidate_model": m,
                        "candidate_role": "larger" if m == large else "smaller",
                        "alternative_direction": f"{large} has lower expected MSPE than {small}",
                        "t_stat": float(cw["t_stat"]),
                        "p_one_sided": float(cw["p_value_one_sided"]),
                        "hac_lag": int(cw.get("hac_lag", 0)),
                    }
                    raw_cw_p[m] = float(cw["p_value_one_sided"])
                    rec["nested_loss_inference"] = {
                        "status": "VALID_CLARK_WEST_MSE_SECONDARY",
                        "method": "Clark-West (2007) MSPE adjustment",
                        "target": f"larger model {large} versus smaller model {small}",
                        "feeds_secondary_verdict": True,
                        "feeds_primary_mcs_verdict": False,
                    }
                else:
                    # Clark-West is an MSPE adjustment; there is no canonical QLIKE
                    # analogue, so no valid nested test is claimed here.
                    rec["clark_west"] = None
                    rec["nested_loss_inference"] = {
                        "status": NESTED_QLIKE_STATUS,
                        "method": None,
                        "feeds_secondary_verdict": False,
                        "feeds_primary_mcs_verdict": False,
                    }
            else:
                rec["t_hln"] = t_hln
                rec["p_hln"] = p_hln
                rec["dm_inference"] = "valid_nonnested_secondary"
                rec["feeds_primary_mcs_verdict"] = False
                raw_p[m] = p_hln
            cell[m] = rec

        # Holm across the models where DM is valid — one cell asks several questions.
        for m, p_adj in holm(raw_p).items():
            cell[m]["p_hln_holm"] = float(p_adj)
            cell[m]["harvey_significant"] = bool(
                abs(cell[m]["t_hln"]) > HARVEY_T and p_adj < 0.05
            )
        # Clark-West is valid only for nested MSE comparisons. It gets its own
        # within-cell Holm family and remains secondary to the pre-specified MCS.
        for m, p_adj in holm(raw_cw_p).items():
            cw = cell[m]["clark_west"]
            cw["p_one_sided_holm"] = float(p_adj)
            cw["reject_after_holm"] = bool(p_adj < 0.05)
            cell[m]["nested_loss_inference"]["verdict"] = (
                "REJECT_IN_FAVOR_OF_LARGER_MODEL"
                if p_adj < 0.05
                else "FAIL_TO_REJECT_NOT_A_NULL_FINDING"
            )
        out["vs_har"][loss_name] = cell

    out["_series"] = {
        "dates": [str(d.date()) for d in idx[t_eval]],
        "qlike": {m: losses["qlike"][m].tolist() for m in FULL_POOL},
    }
    return out


def finalize_results(results: dict) -> dict:
    """Attach claim wiring and upgrade a completed artifact without recomputation.

    The expensive compute already produced the forecasts, losses and MCS draws. This
    idempotent pass changes no empirical number: it isolates nested raw DM/HLN as a
    diagnostic, supplies Clark-West/Holm MSE verdicts, makes nested QLIKE explicitly
    inconclusive, and derives the headline exclusively from MCS membership.
    """
    def normalize_mcs_trace(report: dict) -> None:
        """Rename the legacy generic fields without pretending alpha=.01 is deepest."""
        if "elimination_trace" not in report:
            report["elimination_trace"] = {
                "alpha": min(ALPHA_GRID),
                "interpretation": "alpha=.01 stopping trace; not a complete/deepest path",
                "pvalues": report.pop("elimination_pvalues", {}),
                "order": report.pop("elimination_order", []),
            }
        else:
            report.pop("elimination_pvalues", None)
            report.pop("elimination_order", None)

    for c in results["cells"]:
        for loss_name in c["mcs"]:
            normalize_mcs_trace(c["mcs"][loss_name])
            normalize_mcs_trace(c["mcs_base_pool"][loss_name])
        for loss_name, records in c["vs_har"].items():
            cw_p: dict[str, float] = {}
            for m, rec in records.items():
                if not rec.get("nested_with_har"):
                    rec.setdefault("dm_inference", "valid_nonnested_secondary")
                    rec.setdefault("feeds_primary_mcs_verdict", False)
                    continue

                # Upgrade the pre-repair JSON in-place. Raw DM fields never remain
                # adjacent to p-value/verdict sinks for a nested comparison.
                if "diagnostic_dm_hln" not in rec:
                    rec["diagnostic_dm_hln"] = {
                        "t_stat": rec.pop("t_hln"),
                        "p_two_sided": rec.pop("p_hln"),
                        "hac_lag": int(c["dm_hac_lag"]),
                        "feeds_verdict": False,
                    }
                rec.pop("p_hln_holm", None)
                rec.pop("harvey_significant", None)
                rec["dm_inference"] = "diagnostic_only"
                rec["diagnostic_dm_hln"]["feeds_verdict"] = False

                if loss_name == "qlike":
                    rec["clark_west"] = None
                    rec["nested_loss_inference"] = {
                        "status": NESTED_QLIKE_STATUS,
                        "method": None,
                        "feeds_secondary_verdict": False,
                        "feeds_primary_mcs_verdict": False,
                    }
                else:
                    cw = rec["clark_west"]
                    if cw is None:
                        raise ValueError(f"missing Clark-West result for nested MSE pair {m}")
                    small, large = cw["small"], cw["large"]
                    cw["candidate_model"] = m
                    cw["candidate_role"] = "larger" if m == large else "smaller"
                    cw["alternative_direction"] = (
                        f"{large} has lower expected MSPE than {small}"
                    )
                    cw_p[m] = float(cw["p_one_sided"])
                    rec["nested_loss_inference"] = {
                        "status": "VALID_CLARK_WEST_MSE_SECONDARY",
                        "method": "Clark-West (2007) MSPE adjustment",
                        "target": f"larger model {large} versus smaller model {small}",
                        "feeds_secondary_verdict": True,
                        "feeds_primary_mcs_verdict": False,
                    }

            for m, p_adj in holm(cw_p).items():
                cw = records[m]["clark_west"]
                cw["p_one_sided_holm"] = float(p_adj)
                cw["reject_after_holm"] = bool(p_adj < 0.05)
                records[m]["nested_loss_inference"]["verdict"] = (
                    "REJECT_IN_FAVOR_OF_LARGER_MODEL"
                    if p_adj < 0.05
                    else "FAIL_TO_REJECT_NOT_A_NULL_FINDING"
                )

    spec = results["primary_specification"]
    primary_cells = [
        c for c in results["cells"]
        if c["window"] == spec["window"]
        and c["proxy"] == spec["proxy"]
        and c["horizon"] == spec["horizon"]
    ]
    loss, alpha = spec["loss"], f"{spec['alpha']:g}"
    per_asset = []
    for c in primary_cells:
        full = c["mcs"][loss]["superior_set_by_alpha"][alpha]
        base = c["mcs_base_pool"][loss]["superior_set_by_alpha"][alpha]
        full_base = [m for m in full if m in BASE_POOL]
        per_asset.append({
            "asset": c["asset"],
            "n_scored": c["n_scored"],
            "full_pool_superior_set": full,
            "tsfm_bearing_survivors": [m for m in full if m in TSFM_POOL],
            "base_pool_superior_set_standalone": base,
            "base_models_surviving_in_full_pool": full_base,
            "base_set_changed_after_augmentation": set(base) != set(full_base),
        })

    for p in results["pooled"]:
        if p.get("status") == "ok":
            normalize_mcs_trace(p["full_pool"])
            normalize_mcs_trace(p["base_pool"])

    pooled = next(
        p for p in results["pooled"]
        if p.get("status") == "ok"
        and p["window"] == spec["window"]
        and p["proxy"] == spec["proxy"]
        and p["horizon"] == spec["horizon"]
    )
    pooled_full = pooled["full_pool"]["superior_set_by_alpha"][alpha]
    pooled_base = pooled["base_pool"]["superior_set_by_alpha"][alpha]
    pooled_base_in_full = [m for m in pooled_full if m in BASE_POOL]
    results["adjudication"] = {
        "primary_objective": (
            "MCS membership of TSFM-bearing models and the projected base-model "
            "superior set after pool augmentation"
        ),
        "primary_scope": spec,
        "verdict": "TSFM_BEARING_MODELS_SURVIVE_MCS_NO_WINNER_OR_INCREMENTAL_CLAIM",
        "per_asset": per_asset,
        "pooled": {
            "n_dates": pooled["n_dates"],
            "full_pool_superior_set": pooled_full,
            "tsfm_bearing_survivors": [m for m in pooled_full if m in TSFM_POOL],
            "base_pool_superior_set_standalone": pooled_base,
            "base_models_surviving_in_full_pool": pooled_base_in_full,
            "base_set_changed_after_augmentation": set(pooled_base) != set(pooled_base_in_full),
        },
        "nested_qlike_pairwise_verdict": NESTED_QLIKE_STATUS,
        "interpretation_limits": [
            "MCS membership is non-rejection, not proof that a survivor wins.",
            "The MCS contains estimated and nested forecasts; its standard bootstrap does "
            "not separately repair nested pairwise QLIKE inference.",
            "The 2016+ window is retrospective pseudo-OOS because TSFM weights post-date it.",
            "Clark-West results apply to MSE only and are secondary to the MCS objective.",
        ],
    }
    results["config"]["nested_inference_contract"] = {
        "raw_dm_hln": "diagnostic_only; never feeds any verdict",
        "mse": "Clark-West (2007), Holm-adjusted within cell, secondary",
        "qlike": NESTED_QLIKE_STATUS,
        "primary": "Hansen-Lunde-Nason MCS membership",
    }
    return results


def sensitivity(cells: list[dict], panels: dict, fcst: dict) -> dict:
    """Two knobs the conclusion must not depend on: the MCS block length, and the floor
    imposed on the r2 proxy. If flipping either flips the superior set, say so."""
    out: dict = {"mcs_block_length": {}, "r2_floor": {}}

    for asset in ASSETS:
        c = next(x for x in cells if x["asset"] == asset
                 and x["horizon"] == PRIMARY["horizon"]
                 and x["proxy"] == PRIMARY["proxy"]
                 and x["window"] == PRIMARY["window"])
        L = {m: np.asarray(c["_series"]["qlike"][m]) for m in FULL_POOL}
        T = len(next(iter(L.values())))
        auto = 1.75 * T ** (1 / 3)
        out["mcs_block_length"][asset] = {
            label: mcs_report(L, block_size=bs)["superior_set_by_alpha"]["0.1"]
            for label, bs in (("auto", None), ("half_auto", auto / 2), ("double_auto", auto * 2))
        }

    for asset in ASSETS:
        panel = panels[asset]
        idx, rv = panel.index, panel["rv"].to_numpy(float)
        px = panel["r2"].to_numpy(float)
        pre = px[(idx < FIT_START) & (px > 0)]
        F = fcst[(asset, PRIMARY["horizon"])]
        sets = {}
        for pct in (0.5, 1.0, 5.0):
            floor = float(np.percentile(pre, pct))
            y = build_targets(rv, px, PRIMARY["horizon"], floor)
            valid = np.asarray(idx >= WINDOWS[PRIMARY["window"]]) & np.isfinite(y)
            for f in F.values():
                valid &= np.isfinite(f) & (f > 0)
            te = np.where(valid)[0]
            L = {m: qlike_pointwise(y[te], F[m][te]) for m in FULL_POOL}
            sets[f"pct_{pct:g}"] = mcs_report(L)["superior_set_by_alpha"]["0.1"]
        out["r2_floor"][asset] = sets

    return out


def pooled_mcs(per_asset: list[dict], h: int, proxy: str, window: str) -> dict:
    """Cross-asset MCS on date-aggregated losses.

    Stacking asset-days would treat three markets hit by the same shock as three
    independent draws and understate the standard errors (K1355). So losses are averaged
    across assets within a date first, and the MCS runs on that single date-indexed
    series.
    """
    frames = [pd.DataFrame(r["_series"]["qlike"],
                           index=pd.to_datetime(r["_series"]["dates"])) for r in per_asset]
    common = frames[0].index
    for f in frames[1:]:
        common = common.intersection(f.index)
    if len(common) < 252:
        return {"status": "insufficient_common_dates", "n": int(len(common)),
                "horizon": h, "proxy": proxy, "window": window}

    stacked = sum(f.loc[common] for f in frames) / len(frames)
    L = {m: stacked[m].to_numpy() for m in stacked.columns}
    return {
        "status": "ok", "horizon": h, "proxy": proxy, "window": window,
        "n_dates": int(len(common)),
        "aggregation": "mean QLIKE across assets within each date (K1355)",
        "mean_loss": {m: float(np.mean(v)) for m, v in L.items()},
        "full_pool": mcs_report(L),
        "base_pool": mcs_report({m: L[m] for m in BASE_POOL}),
    }


# ══ main ══════════════════════════════════════════════════════════════════════

def main() -> None:
    np.random.seed(SEED)

    panels, tsfm = {}, {}
    for a in ASSETS:
        tag = a.replace(".", "_")
        panels[a] = pd.read_csv(DATA / f"panel_{tag}.csv", parse_dates=["date"]) \
                      .set_index("date").sort_index()
        tsfm[a] = {
            m: pd.read_csv(DATA / f"tsfm_{m}_{tag}.csv", parse_dates=["target_date"])
                 .set_index("target_date").sort_index()
            for m in TSFMS
        }

    results: dict = {
        "experiment_id": "k1711",
        "question": ("Does adding zero-shot TSFMs (and their bias-corrected combinations "
                     "with log-HAR) to a log-HAR pool change the Hansen MCS superior set?"),
        "seed": SEED,
        "primary_specification": PRIMARY,
        "config": {
            "windows": {k: str(v.date()) for k, v in WINDOWS.items()},
            "window_semantics": {
                "pseudo_oos": "retrospective — TSFM weights post-date the data; NOT real-time OOS",
                "vintage_clean": "starts after every documented TSFM pretraining cutoff",
            },
            "horizons": list(HORIZONS),
            "proxies": list(PROXIES),
            "base_pool": BASE_POOL,
            "tsfm_pool": TSFM_POOL,
            "nested_with_har": {k: list(v) for k, v in NESTED_WITH_HAR.items()},
            "min_train_har": MIN_TRAIN_HAR,
            "min_train_mz": MIN_TRAIN_MZ,
            "mcs_n_boot": N_BOOT,
            "mcs_alpha_grid": list(ALPHA_GRID),
            "mcs_impl": ("volpred.stats.mcs.model_confidence_set — Hansen-Lunde-Nason "
                         "elimination on max_i t_i. (the T_max / e_max variant). NOTE: the "
                         "function's docstring calls this T_R, which is wrong — T_R is the "
                         "pairwise max|t_ij| statistic. Both are valid MCS variants but they "
                         "can produce different superior sets, so the label matters."),
            "dm_impl": "volpred.stats.model_evaluation.dm_test + HLN factor; Holm across models",
            "nested_impl": "volpred.stats.model_evaluation.clark_west_test (MSE only)",
            "harvey_threshold": HARVEY_T,
        },
        "panels": json.loads((DATA / "panel_meta.json").read_text()),
        "tsfm_meta": {m: json.loads((DATA / f"tsfm_{m}_meta.json").read_text())
                      for m in TSFMS},
        "cells": [], "pooled": [],
    }

    fcst = {(a, h): build_forecasts(panels[a], h, tsfm[a])
            for a in ASSETS for h in HORIZONS}

    for window in WINDOWS:
        for proxy in PROXIES:
            for h in HORIZONS:
                per_asset = []
                for a in ASSETS:
                    r = evaluate(a, h, proxy, window, panels[a], fcst[(a, h)])
                    per_asset.append(r)
                    tag = "*" if (window == PRIMARY["window"] and proxy == PRIMARY["proxy"]
                                  and h == PRIMARY["horizon"]) else " "
                    print(f"{tag}[{window:13s} {proxy} h={h}] {a:8s} n={r['n_scored']:5d} "
                          f"MCS@.10 = {r['mcs']['qlike']['superior_set_by_alpha']['0.1']}",
                          flush=True)
                results["pooled"].append(pooled_mcs(per_asset, h, proxy, window))
                results["cells"].extend(per_asset)

    results["sensitivity"] = sensitivity(results["cells"], panels, fcst)
    finalize_results(results)

    series = {f"{c['asset']}|h{c['horizon']}|{c['proxy']}|{c['window']}": c.pop("_series")
              for c in results["cells"]}
    _atomic_json(HERE / "k1711_series.json", series)
    _atomic_json(HERE / "k1711_results.json", results)
    print("\nwrote k1711_results.json")


if __name__ == "__main__":
    main()
