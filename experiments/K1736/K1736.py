#!/usr/bin/env python3
"""K1736 - Skewness risk premium TERM STRUCTURE as a long-horizon tail signal.

Research question
-----------------
Seven prior experiments (K181, K184, K210, K258, K447, K535, K979) tested the CBOE
SKEW index as a *level* predictor at *short* horizons and all returned NULL.  This
experiment deliberately moves to the other cell of that 2x2: a *term-structure slope*
signal against *long* (6-12 month) horizons, following the JFQA-2025-vintage
crash-risk-premium / skewness-swap literature in which the skew premium is reported
to be stronger at longer maturities.

The differentiation claim is therefore falsifiable in two independent ways, and both
are tested explicitly here:

  D1  Does the slope carry information the LEVEL does not?
      (corr(slope, level) and the multivariate incremental t on slope.)
  D2  Is the signal stronger at long horizons than at short ones?
      (|t| at H=252 vs |t| at H=21 for the same signal/target.)

If D1 fails the construction has degenerated back into a level bet and the experiment
must be reported as such, not dressed up as a new finding.

Data limitation that shapes the whole design
--------------------------------------------
^SKEW is a 30-DAY risk-neutral skewness index.  CBOE publishes no free SKEW3M /
SKEW6M, and yfinance carries no historical option chains, so a genuine risk-neutral
skew term structure CANNOT be observed with free data.  Every construction below
obtains its horizon variation from somewhere else, and each is labelled with exactly
where:

  (a) physical leg only   - realized skewness at several windows; the risk-neutral
                            leg CANCELS out of the slope (proved in the README).
  (c) model-extrapolated  - risk-neutral skewness extrapolated to horizon T under a
                            constant-jump-intensity (linear third cumulant) assumption,
                            using the OBSERVABLE implied-variance term structure
                            (^VIX / ^VIX3M / ^VIX6M) as the horizon carrier.

Lookahead policy
----------------
Every regressor enters as ``signal.shift(1)``: the value observed at the close of t-1
is used to predict a target whose window starts at the close of t.  A full trading day
separates information set from target window.  The forward targets are labelled at
their ORIGIN date t and use prices t..t+H, so no target row can be read off before its
regressor.  The OOS loop additionally enforces ``target_end <= forecast_origin`` on
every training row.

Overlapping observations
------------------------
Daily-frequency rolling H-day targets are massively overlapping.  All of the following
are reported for every cell: Newey-West HAC with lag = max(H, canonical repo bandwidth)
plus 1.5H/2H sensitivity, Hodrick (1992) 1B standard errors (return targets only - the
estimator is defined for sums of one-period returns and does NOT apply to drawdown),
all H non-overlapping phase subsamples, and the effective sample size T/H.

Seeds: numpy 42 (bootstrap).
"""

from __future__ import annotations

import json
import os
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from volpred.research.reproduce_spec import finalize_experiment  # noqa: E402
from volpred.stats.model_evaluation import clark_west_test  # noqa: E402

warnings.filterwarnings("ignore")

T0 = time.time()
SEED = 42
np.random.seed(SEED)
RNG = np.random.default_rng(SEED)

EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

FETCH_START = "1985-01-01"
FETCH_END = "2026-07-30"

# Trading-day horizons.  21 ~ 1 month, 63 ~ 1 quarter, 126 ~ 6 months, 252 ~ 12 months.
HORIZONS = [21, 63, 126, 252]
# Calendar-day maturities of the CBOE implied-vol indices, used by the cumulant scaling.
CAL_DAYS = {"VIX": 30.0, "VIX3M": 93.0, "VIX6M": 180.0}
# Trading-day windows matched to those maturities for the physical (realized) leg.
TRADING_MATCH = {"VIX": 21, "VIX3M": 63, "VIX6M": 126}

HARVEY_T = 3.0
DEGENERACY_CORR = 0.90
N_BOOT = 2000
# Out-of-sample loop: minimum training rows, and the spacing between forecast origins.
MIN_TRAIN = 1000
STEP = 21


# ======================================================================================
# 1. Data
# ======================================================================================
def fetch_series(ticker: str, name: str) -> pd.DataFrame:
    """Download once, then always read the frozen CSV with round-trip float parsing.

    ``float_precision='round_trip'`` is mandatory here: the repo hit a cross-platform
    1-ULP hash drift on frozen slices parsed with the default C parser (K1386, 2026-07-16).
    """
    path = DATA_DIR / f"{name}.csv"
    if not path.exists():
        import yfinance as yf

        raw = yf.download(
            ticker, start=FETCH_START, end=FETCH_END, progress=False, auto_adjust=False
        )
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        if raw.empty:
            raise RuntimeError(f"yfinance returned no rows for {ticker}")
        raw.to_csv(path)
    return pd.read_csv(path, index_col=0, parse_dates=True, float_precision="round_trip")


print("=" * 78)
print("K1736  Skew-premium TERM STRUCTURE as a long-horizon tail signal")
print("=" * 78)
print("\n[1] Loading data ...")

SOURCES = {
    "SKEW": ("^SKEW", "Close"),
    "VIX": ("^VIX", "Close"),
    "VIX3M": ("^VIX3M", "Close"),
    "VIX6M": ("^VIX6M", "Close"),
    "SPY": ("SPY", "Adj Close"),
    "GSPC": ("^GSPC", "Close"),
}

raw_frames = {name: fetch_series(tk, name) for name, (tk, _) in SOURCES.items()}
series = {name: raw_frames[name][col].dropna() for name, (_, col) in SOURCES.items()}

# The trading-day reference calendar is SPY's own index (NYSE sessions).
calendar = series["SPY"].index

data_diagnostics: dict[str, object] = {
    "fetch_window": {"start": FETCH_START, "end": FETCH_END},
    "source": "yfinance (Yahoo Finance) daily closes; SPY uses split/dividend adjusted close",
    "frozen_csv_dir": "experiments/K1736/data",
    "trading_day_reference": "SPY session calendar (NYSE)",
    "series": {},
}

for name, s in series.items():
    on_cal = s.reindex(calendar)
    dup = int(s.index.duplicated().sum())
    overlap = calendar[(calendar >= s.index[0]) & (calendar <= s.index[-1])]
    missing_within = int(on_cal.reindex(overlap).isna().sum())
    data_diagnostics["series"][name] = {
        "yahoo_ticker": SOURCES[name][0],
        "column": SOURCES[name][1],
        "start": str(s.index[0].date()),
        "end": str(s.index[-1].date()),
        "n_obs": int(len(s)),
        "duplicate_dates": dup,
        "n_nyse_sessions_within_span": int(len(overlap)),
        "missing_within_span": missing_within,
        "missing_rate_within_span": round(missing_within / max(1, len(overlap)), 6),
        "min": float(s.min()),
        "max": float(s.max()),
        "mean": float(s.mean()),
    }
    print(
        f"    {name:6s} {s.index[0].date()} -> {s.index[-1].date()}  n={len(s):5d}  "
        f"missing_within_span={missing_within} ({missing_within / max(1, len(overlap)):.3%})"
    )

df = pd.DataFrame({k: v for k, v in series.items()}).sort_index()
df = df.reindex(calendar)  # restrict to NYSE sessions; SPY defines the tradable grid

joint_skew = df[["SKEW", "SPY"]].dropna()
joint_v6 = df[["SKEW", "VIX", "VIX6M", "SPY"]].dropna()
joint_v3 = df[["SKEW", "VIX", "VIX3M", "SPY"]].dropna()
data_diagnostics["joint_samples"] = {
    "long_SKEW_SPY": {
        "start": str(joint_skew.index[0].date()),
        "end": str(joint_skew.index[-1].date()),
        "n": int(len(joint_skew)),
    },
    "mid_SKEW_VIX3M_SPY": {
        "start": str(joint_v3.index[0].date()),
        "end": str(joint_v3.index[-1].date()),
        "n": int(len(joint_v3)),
    },
    "short_SKEW_VIX6M_SPY": {
        "start": str(joint_v6.index[0].date()),
        "end": str(joint_v6.index[-1].date()),
        "n": int(len(joint_v6)),
    },
}
data_diagnostics["risk_neutral_skew_term_structure_available"] = False
data_diagnostics["risk_neutral_skew_term_structure_note"] = (
    "CBOE publishes ^SKEW at the 30-day maturity only; there is no free SKEW3M/SKEW6M "
    "and yfinance carries no historical option chains. A directly OBSERVED risk-neutral "
    "skew term structure cannot be built from the free data available to this project. "
    "Every horizon-varying construction below is either physical-leg-only (a) or "
    "model-extrapolated from the observable implied-VARIANCE term structure (c)."
)

# ======================================================================================
# 2. Signal construction
# ======================================================================================
print("\n[2] Constructing signals ...")

# CBOE definition: SKEW = 100 - 10 * zeta, where zeta is the risk-neutral skewness of
# the 30-day S&P 500 log return.  zeta is normally negative (crash-fear).
zeta30 = (100.0 - df["SKEW"]) / 10.0
ret1 = np.log(df["SPY"]).diff()


def realized_skew(window: int) -> pd.Series:
    """Skewness of the ``window``-day cumulative return, estimated from daily returns.

    The trailing-``window`` sample skewness of DAILY returns is divided by sqrt(window):
    under iid increments skew(sum of n) = skew(daily)/sqrt(n).  Using a window-specific
    daily sample is what gives this object genuine horizon variation - a single global
    daily skewness rescaled by 1/sqrt(n) would be a deterministic function of one number
    and could not constitute a term structure at all.
    """
    return ret1.rolling(window, min_periods=window).skew() / np.sqrt(window)


rs = {w: realized_skew(w) for w in sorted(set(list(TRADING_MATCH.values()) + HORIZONS))}


def zeta_at(vol_index: str) -> pd.Series:
    """Risk-neutral skewness extrapolated from 30 days to the maturity of ``vol_index``.

    Derivation (constant jump intensity / Levy-type third cumulant, stochastic variance):
        kappa3(T) = (T/30) * kappa3(30)                      [third cumulant linear in T]
        kappa2(T) = VIX_T^2 * T / 365                        [observed, annualised]
        zeta(T)   = kappa3(T) / kappa2(T)^{3/2}
                  = zeta(30) * sqrt(30/T) * (VIX_30 / VIX_T)^3
    With a flat implied-variance term structure this collapses to the pure iid scaling
    sqrt(30/T); all horizon information beyond that comes from the OBSERVED VIX ratio.
    This is an assumption, not a measurement - see README section "What this is not".
    """
    T = CAL_DAYS[vol_index]
    return zeta30 * np.sqrt(CAL_DAYS["VIX"] / T) * (df["VIX"] / df[vol_index]) ** 3


zeta93 = zeta_at("VIX3M")
zeta180 = zeta_at("VIX6M")

signals = pd.DataFrame(index=df.index)
# --- level benchmarks (what the seven prior NULLs already tested) -----------------
signals["skew_level"] = zeta30
signals["srp_30d"] = zeta30 - rs[TRADING_MATCH["VIX"]]
# --- construction (a): realized-skewness term structure ---------------------------
# premium_h = zeta30 - RS_h, so premium_252 - premium_21 = RS_21 - RS_252: the
# risk-neutral leg cancels identically.  Kept because the brief lists it, and reported
# with that cancellation stated in the open.
signals["ts_realized"] = rs[21] - rs[252]
# --- construction (c): model-extrapolated risk-neutral slope ----------------------
signals["rn_slope_3m"] = zeta93 - zeta30
signals["rn_slope_6m"] = zeta180 - zeta30
signals["srp_slope_6m"] = (zeta180 - rs[TRADING_MATCH["VIX6M"]]) - (
    zeta30 - rs[TRADING_MATCH["VIX"]]
)
# --- pure implied-VARIANCE term structure (control: contains no skew at all) ------
# Each model-extrapolated skew slope gets the variance term structure of ITS OWN
# maturity as a control. Controlling the 6M slope against vts_6m while leaving the 3M
# slope with only a level control would be an asymmetric-refinement artifact (K1216b).
signals["vts_3m"] = np.log(df["VIX3M"] / df["VIX"])
signals["vts_6m"] = np.log(df["VIX6M"] / df["VIX"])

SIGNAL_FAMILY = {
    "skew_level": "A_long",
    "srp_30d": "A_long",
    "ts_realized": "A_long",
    "rn_slope_3m": "C_mid",
    "vts_3m": "C_mid",
    "rn_slope_6m": "B_short",
    "srp_slope_6m": "B_short",
    "vts_6m": "B_short",
}
SIGNAL_KIND = {
    "skew_level": "level",
    "srp_30d": "level",
    "ts_realized": "slope_physical_only",
    "rn_slope_3m": "slope_model_extrapolated",
    "rn_slope_6m": "slope_model_extrapolated",
    "srp_slope_6m": "slope_model_extrapolated",
    "vts_3m": "variance_term_structure_control",
    "vts_6m": "variance_term_structure_control",
}
# Maturity-matched variance-term-structure control for each model-extrapolated slope.
SLOPE_CONTROLS = {
    "ts_realized": ["skew_level"],
    "rn_slope_3m": ["skew_level", "vts_3m"],
    "rn_slope_6m": ["skew_level", "vts_6m"],
    "srp_slope_6m": ["skew_level", "vts_6m"],
}
SLOPE_SIGNALS = [s for s, k in SIGNAL_KIND.items() if k.startswith("slope")]

# ======================================================================================
# 3. Degeneracy diagnostics  (differentiation test D1, part 1)
# ======================================================================================
print("\n[3] Degeneracy diagnostics ...")

corr_common = signals.dropna()
corr_matrix = corr_common.corr()

degeneracy = {
    "common_sample": {
        "start": str(corr_common.index[0].date()),
        "end": str(corr_common.index[-1].date()),
        "n": int(len(corr_common)),
    },
    "correlation_matrix": {
        a: {b: round(float(corr_matrix.loc[a, b]), 4) for b in corr_matrix.columns}
        for a in corr_matrix.index
    },
    "threshold_abs_corr_vs_level": DEGENERACY_CORR,
    "per_signal": {},
}
for sig in SLOPE_SIGNALS + ["ts_realized"]:
    pair = signals[[sig, "skew_level"]].dropna()
    c = float(pair.corr().iloc[0, 1])
    degeneracy["per_signal"][sig] = {
        "corr_with_skew_level": round(c, 4),
        "r2_explained_by_level": round(c**2, 4),
        "residual_variance_share": round(1 - c**2, 4),
        "n": int(len(pair)),
        "degenerate": bool(abs(c) > DEGENERACY_CORR),
    }
    print(
        f"    {sig:16s} corr(level) = {c:+.3f}  R2 = {c**2:.3f}  "
        f"{'DEGENERATE' if abs(c) > DEGENERACY_CORR else 'ok'}"
    )

# The pure-iid variant is analytically degenerate: zeta30*(sqrt(30/T)-1) is a constant
# multiple of the level, so |corr| = 1 by construction.  Recorded so the reader can see
# that the VIX-ratio term is the ONLY thing keeping construction (c) off that boundary.
#
# The correlation is COMPUTED, not asserted (2026-07-30 collection audit ISSUE-1): the
# constant sqrt(30/T)-1 is NEGATIVE for every T > 30, and skew_level is zeta30 itself
# (L265), so the sign is -1.0, not +1.0.  A hardcoded +1.0 sat here and was wrong; the
# |corr| = 1 degeneracy conclusion it supports is unaffected, but a number nobody computed
# is exactly how a wrong number survives review.  Build the series and measure it.
_iid_only_slope_3m = zeta30 * (np.sqrt(CAL_DAYS["VIX"] / CAL_DAYS["VIX3M"]) - 1.0)
_iid_pair = pd.concat(
    [_iid_only_slope_3m.rename("iid_slope"), signals["skew_level"].rename("level")], axis=1
).dropna()
_iid_corr = float(_iid_pair.corr().iloc[0, 1])
degeneracy["analytic_note_iid_only_slope"] = {
    "formula": "zeta_T_iid - zeta_30 = zeta_30 * (sqrt(30/T) - 1)",
    "multiplier_at_T_93": round(float(np.sqrt(CAL_DAYS["VIX"] / CAL_DAYS["VIX3M"]) - 1.0), 6),
    "corr_with_skew_level": round(_iid_corr, 4),
    "corr_source": "computed on the constructed iid-only slope at T=93, not asserted",
    "n": int(len(_iid_pair)),
    "degenerate": bool(abs(_iid_corr) > DEGENERACY_CORR),
    "comment": "A slope built from iid sqrt-scaling alone carries exactly zero information "
    "beyond the SKEW level: the multiplier is a negative constant, so the correlation is "
    "-1 exactly. Only the observed VIX/VIX_T ratio breaks that identity.",
}
degeneracy["analytic_note_ts_realized"] = {
    "formula": "(zeta_30 - RS_252) - (zeta_30 - RS_21) = RS_21 - RS_252",
    "comment": "Under a common 30-day risk-neutral leg the slope of the premium across "
    "horizons is identically the negative slope of realized skewness: the option-implied "
    "leg cancels and construction (a) contains no risk-neutral information whatsoever.",
    "corr_ts_realized_with_RS21": round(
        float(pd.concat([signals["ts_realized"], rs[21]], axis=1).dropna().corr().iloc[0, 1]), 4
    ),
}

# ======================================================================================
# 4. Targets
# ======================================================================================
print("\n[4] Building forward targets ...")

px = df["SPY"].copy()


def forward_drawdown(prices: pd.Series, horizon: int) -> pd.Series:
    """Worst peak-to-trough decline of ONE price path over [t, t+horizon].

    Single series, no benchmark, no differencing against a second path: this is a
    dependent VARIABLE, not a strategy-vs-benchmark risk comparison, so the exposure
    matching rule for cross-strategy drawdown claims does not apply here.
    """
    values = prices.to_numpy(dtype=np.float64)
    n = len(values)
    out = np.full(n, np.nan)
    for i in range(n - horizon):
        window = values[i : i + horizon + 1]
        if not np.all(np.isfinite(window)):
            continue
        running_peak = np.maximum.accumulate(window)
        out[i] = float(np.max(1.0 - window / running_peak))
    return pd.Series(out, index=prices.index)


targets: dict[str, pd.Series] = {}
for H in HORIZONS:
    targets[f"fwd_ret_{H}"] = np.log(px.shift(-H) / px)
    targets[f"fwd_mdd_{H}"] = forward_drawdown(px, H)
TARGET_KINDS = {"fwd_ret": "sum_of_one_period_returns", "fwd_mdd": "path_functional"}

def run_lookahead_audit(n_probe: int = 200) -> dict:
    """Verify the lag mechanically instead of only asserting it in prose.

    Independently re-derives, on randomly drawn rows: (1) that the regressor used at
    row t really is the raw signal at t-1, and (2) that each forward target stamped at
    t reads only prices t..t+H. Raises if any check fails, so a broken alignment cannot
    reach the results file.
    """
    rng = np.random.default_rng(SEED)
    checks = []

    # (1) Every signal, not just one: the lagged regressor at session t must be the raw
    # signal at the PREVIOUS NYSE session, identified by date rather than by position.
    per_signal_ok = {}
    for sig in signals.columns:
        lagged = signals[sig].shift(1)
        valid = np.flatnonzero(lagged.notna().to_numpy())
        probe = rng.choice(valid[valid > 5], size=min(n_probe, len(valid) - 1), replace=False)
        ok = True
        for i in probe:
            prev_date = signals.index[i - 1]
            if float(lagged.iloc[i]) != float(signals.loc[prev_date, sig]):
                ok = False
            if (signals.index[i] - prev_date).days > 10:
                ok = False  # a gap this large would mean the "previous session" is stale
        per_signal_ok[sig] = bool(ok)
    checks.append(
        {
            "name": "regressor_at_t_equals_raw_signal_at_previous_session_all_signals",
            "n_signals": len(per_signal_ok),
            "n_rows_probed_each": int(n_probe),
            "per_signal": per_signal_ok,
            "passed": bool(all(per_signal_ok.values())),
        }
    )

    # (2) The regression frames themselves: for a sample of assembled (y, x) frames, the
    # x column must equal the raw signal one session earlier.  (2026-07-30 collection audit
    # ISSUE-3: this docstring used to also claim it verified "the target must never be
    # observable before its own origin date" — it never did; that property is check (5)'s
    # independent recomputation of fwd_ret_252 / fwd_mdd_252.  A dead no-op `continue`
    # guard that suggested otherwise has been removed.)
    frame_ok = True
    for sig in ["skew_level", "rn_slope_6m", "ts_realized"]:
        for H in (21, 252):
            fr = pd.concat(
                [targets[f"fwd_ret_{H}"].rename("y"), signals[sig].shift(1).rename("x")],
                axis=1,
            ).dropna()
            rows = rng.choice(np.arange(len(fr)), size=min(50, len(fr)), replace=False)
            for k in rows:
                date = fr.index[k]
                pos = signals.index.get_loc(date)
                if float(fr["x"].iloc[k]) != float(signals[sig].iloc[pos - 1]):
                    frame_ok = False
    checks.append(
        {
            "name": "assembled_regression_frames_carry_the_t_minus_1_regressor",
            "n_frames_probed": 6,
            "passed": bool(frame_ok),
        }
    )

    # (3) The OOS training cut: for every origin the loop would use, the last training row
    # must have its whole target window closed at or before the forecast origin.
    #
    # 2026-07-30 collection audit ISSUE-2: the previous version of this check restated the
    # loop's own algebra (`j_max = i - H; if (j_max - 1) + H > i`), which reduces to
    # `i - 1 > i` and can never fire.  It passed unconditionally and had ZERO power to
    # detect an OOS lookahead.  A check that cannot fail is not evidence.  This version
    # measures the thing itself: it walks the SESSION CALENDAR forward H sessions from the
    # last training row's own date and asserts that window closes on or before the origin
    # date.  It is independent of the index arithmetic it is auditing, so a sign error or
    # an off-by-one in the loop would now surface here.
    oos_ok = True
    oos_probed = 0
    oos_min_gap_sessions = None
    session_index = px.index
    for H in (126, 252):
        frame_probe = pd.concat(
            [
                targets[f"fwd_ret_{H}"].rename("y"),
                signals["skew_level"].shift(1).rename("x"),
            ],
            axis=1,
        ).dropna()
        n_rows = len(frame_probe)
        for i in range(MIN_TRAIN + H, n_rows, STEP):
            j_max = i - H  # rows [0, j_max) are the training set
            if j_max < MIN_TRAIN:
                continue
            last_train_date = frame_probe.index[j_max - 1]
            origin_date = frame_probe.index[i]
            pos = session_index.get_loc(last_train_date)
            if pos + H >= len(session_index):
                continue
            window_close_date = session_index[pos + H]
            gap = session_index.get_loc(origin_date) - (pos + H)
            oos_min_gap_sessions = (
                gap if oos_min_gap_sessions is None else min(oos_min_gap_sessions, gap)
            )
            oos_probed += 1
            if window_close_date > origin_date:
                oos_ok = False
    checks.append(
        {
            "name": "oos_training_rows_have_target_window_closed_before_origin",
            "rule": "the H-th session after the last training row's date is <= the origin date",
            "measured_on": "SPY session calendar, independent of the loop's row arithmetic",
            "n_origins_probed": int(oos_probed),
            "min_gap_sessions_between_window_close_and_origin": (
                int(oos_min_gap_sessions) if oos_min_gap_sessions is not None else None
            ),
            "passed": bool(oos_ok),
        }
    )

    ret_ok, path_ok = True, True
    values = px.to_numpy(dtype=np.float64)
    finite = np.flatnonzero(np.isfinite(values))
    rows = rng.choice(
        finite[(finite > 300) & (finite < len(values) - 300)], size=100, replace=False
    )
    for i in rows:
        if not np.isclose(
            targets["fwd_ret_252"].iloc[i], np.log(values[i + 252] / values[i]), atol=1e-12
        ):
            ret_ok = False
        path = values[i : i + 253]
        recomputed = float(np.max(1.0 - path / np.maximum.accumulate(path)))
        if not np.isclose(targets["fwd_mdd_252"].iloc[i], recomputed, atol=1e-12):
            path_ok = False
    checks.append(
        {
            "name": "fwd_ret_252_at_t_uses_prices_t_to_t_plus_252_only",
            "n_rows_probed": int(len(rows)),
            "passed": bool(ret_ok),
        }
    )
    checks.append(
        {
            "name": "fwd_mdd_252_at_t_is_the_worst_decline_of_the_path_t_to_t_plus_252",
            "n_rows_probed": int(len(rows)),
            "passed": bool(path_ok),
        }
    )

    audit = {"checks": checks, "all_passed": all(c["passed"] for c in checks)}
    if not audit["all_passed"]:
        raise AssertionError(f"lookahead audit failed: {audit}")
    return audit


lookahead_audit = run_lookahead_audit()
print(f"    lookahead audit: {len(lookahead_audit['checks'])} checks passed")

# ======================================================================================
# 5. Inference machinery
# ======================================================================================


def canonical_hac_lag(h: int, n: int) -> int:
    """Repo canonical Bartlett bandwidth, floored at the overlap length h.

    ``lag = h - 1`` alone is banned (.claude/rules/experiments.md): it only covers the
    MA(h-1) induced by optimal-forecast overlap and degenerates to zero at h=1.  The
    repo canonical is ceil(h^(1/3) n^(1/3)); with H-day overlapping targets the induced
    MA order is H, so the binding rule is the max of the two.
    """
    canon = int(np.ceil(h ** (1 / 3) * n ** (1 / 3)))
    return int(max(h, canon, 1))


def nw_ols(y: np.ndarray, X: np.ndarray, lag: int) -> dict:
    """OLS with a Newey-West HAC covariance.  ``X`` excludes the intercept."""
    X = np.atleast_2d(X)
    if X.shape[0] != len(y):
        X = X.T
    Z = np.column_stack([np.ones(len(y)), X])
    k = Z.shape[1]
    n = len(y)
    XtX_inv = np.linalg.pinv(Z.T @ Z)
    beta = XtX_inv @ (Z.T @ y)
    resid = y - Z @ beta
    lag = int(min(max(lag, 0), max(n // 4, 1)))

    S = (Z * resid[:, None]).T @ (Z * resid[:, None])
    for L in range(1, lag + 1):
        w = 1.0 - L / (lag + 1.0)
        u1 = (Z[L:] * resid[L:, None]).T @ (Z[:-L] * resid[:-L, None])
        S += w * (u1 + u1.T)
    V = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(V), 0.0))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(se > 0, beta / se, 0.0)
    tss = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid**2)) / tss if tss > 0 else np.nan
    return {
        "beta": beta,
        "se": se,
        "t": t,
        "p": 2.0 * stats.norm.sf(np.abs(t)),
        "r2": r2,
        "n": n,
        "k": k,
        "hac_lag": lag,
    }


def hodrick_1b(
    x_cal: pd.Series, r_next_cal: pd.Series, horizon: int, sample_index: pd.Index
) -> dict | None:
    """Hodrick (1992) '1B' standard error for a long-horizon predictive regression.

    Instead of summing the LHS (which is what creates the overlap), the estimator sums
    the RHS regressor and imposes the null of no predictability, so the one-period
    residual is the demeaned one-period return:

        w_t   = sum_{j=0}^{H-1} Z_{t-j},   Z_t = [1, x_t]'
        Omega = (1/T) sum_t e_{t+1}^2 w_t w_t',   e_{t+1} = r_{t+1} - mean(r)
        Var(b)= (1/T) Sxx^{-1} Omega Sxx^{-1}

    ``w_t`` MUST be summed over ``horizon`` consecutive TRADING SESSIONS, so this
    function takes calendar-indexed series rather than the post-``dropna`` arrays used
    for the point estimate. Summing the last ``horizon`` *available* rows of a compressed
    frame would silently reach further back than H sessions whenever the regressor has an
    interior gap (^SKEW misses 0.878% of NYSE sessions), and would break the alignment
    between ``w_t`` and ``e_{t+1}``.

    Because ^SKEW's gaps are frequent enough that almost no 252-session window is free of
    one, the regressor is forward-filled up to ``FFILL_LIMIT`` sessions purely for the w_t
    sum: on a day CBOE published no SKEW value, the last published value is the
    information an investor actually had. Rows entering the estimator are still only rows
    of ``sample_index`` (the regression sample); the forward fill never creates a
    regression observation.

    Defined for targets that are SUMS OF ONE-PERIOD RETURNS. It is not defined for a
    path functional such as a maximum drawdown, and is therefore not reported for those.
    """
    FFILL_LIMIT = 10
    x_filled = x_cal.ffill(limit=FFILL_LIMIT)
    # min_periods=horizon => any window still holding a NaN yields NaN, so w_t is only
    # defined where all `horizon` consecutive sessions are present.
    w_x = x_filled.rolling(horizon, min_periods=horizon).sum()

    valid = x_cal.notna() & w_x.notna() & r_next_cal.notna()
    valid &= pd.Series(x_cal.index.isin(sample_index), index=x_cal.index)
    n_valid = int(valid.sum())
    if n_valid <= horizon + 5:
        return None

    xv = x_cal[valid].to_numpy(dtype=np.float64)
    wv = w_x[valid].to_numpy(dtype=np.float64)
    ev = r_next_cal[valid].to_numpy(dtype=np.float64)
    ev = ev - ev.mean()

    Ti = len(xv)
    Z = np.column_stack([np.ones(Ti), xv])
    W = np.column_stack([np.full(Ti, float(horizon)), wv])
    Sxx = Z.T @ Z / Ti
    Omega = (W * (ev**2)[:, None]).T @ W / Ti
    Sxx_inv = np.linalg.pinv(Sxx)
    V = Sxx_inv @ Omega @ Sxx_inv / Ti
    se = float(np.sqrt(max(V[1, 1], 0.0)))
    return {
        "se": se,
        "n_used": int(Ti),
        "n_sample_rows": int(len(sample_index)),
        "n_rows_dropped_for_calendar_gaps": int(len(sample_index) - Ti),
        "ffill_limit_sessions": FFILL_LIMIT,
    }


def nonoverlapping_phases(y: np.ndarray, x: np.ndarray, horizon: int) -> dict:
    """Run the regression on every one of the H disjoint non-overlapping subsamples."""
    ts, betas, ns = [], [], []
    for phase in range(horizon):
        idx = np.arange(phase, len(y), horizon)
        yy, xx = y[idx], x[idx]
        ok = np.isfinite(yy) & np.isfinite(xx)
        if ok.sum() < 12:
            continue
        yy, xx = yy[ok], xx[ok]
        Z = np.column_stack([np.ones(len(yy)), xx])
        beta, *_ = np.linalg.lstsq(Z, yy, rcond=None)
        resid = yy - Z @ beta
        dof = len(yy) - 2
        s2 = float(resid @ resid) / dof
        cov = s2 * np.linalg.pinv(Z.T @ Z)
        se = float(np.sqrt(max(cov[1, 1], 0.0)))
        if se <= 0:
            continue
        ts.append(float(beta[1] / se))
        betas.append(float(beta[1]))
        ns.append(int(len(yy)))
    if not ts:
        return {"status": "insufficient"}
    ts_arr = np.array(ts)
    return {
        "status": "ok",
        "n_phases": len(ts),
        "obs_per_phase_median": int(np.median(ns)),
        "t_mean": round(float(ts_arr.mean()), 4),
        "t_median": round(float(np.median(ts_arr)), 4),
        "t_min": round(float(ts_arr.min()), 4),
        "t_max": round(float(ts_arr.max()), 4),
        "beta_mean": float(np.mean(betas)),
        "share_abs_t_gt_1_96": round(float(np.mean(np.abs(ts_arr) > 1.96)), 4),
        "share_abs_t_gt_3": round(float(np.mean(np.abs(ts_arr) > HARVEY_T)), 4),
        "sign_agreement_with_full_sample": None,
    }


def holm(pvals: list[float]) -> list[float]:
    m = len(pvals)
    order = np.argsort(pvals)
    adj = np.empty(m)
    running = 0.0
    for rank, i in enumerate(order):
        val = (m - rank) * pvals[i]
        running = max(running, val)
        adj[i] = min(1.0, running)
    return [float(v) for v in adj]


def circular_block_indices(n: int, block: int, rng: np.random.Generator) -> np.ndarray:
    """Circular block bootstrap row indices preserving within-block serial dependence."""
    n_blocks = int(np.ceil(n / block))
    starts = rng.integers(0, n, size=n_blocks)
    idx = (starts[:, None] + np.arange(block)[None, :]) % n
    return idx.reshape(-1)[:n]


def univariate_beta(y: np.ndarray, x: np.ndarray) -> float:
    ok = np.isfinite(y) & np.isfinite(x)
    if ok.sum() < 30:
        return np.nan
    yy, xx = y[ok], x[ok]
    xc = xx - xx.mean()
    denom = float(xc @ xc)
    if denom <= 0:
        return np.nan
    return float(xc @ (yy - yy.mean()) / denom)


# ======================================================================================
# 6. Univariate predictive regressions
# ======================================================================================
print("\n[5] Univariate predictive regressions (HAC + Hodrick + non-overlapping) ...")

cells: list[dict] = []
# One-period return stamped at row t = r_{t+1}, on the full NYSE calendar. Hodrick's
# null-imposed residual needs this aligned to sessions, not to compressed frame rows.
ret_next = ret1.shift(-1)

for sig in signals.columns:
    for base in ["fwd_ret", "fwd_mdd"]:
        for H in HORIZONS:
            tgt = f"{base}_{H}"
            # ---- LOOKAHEAD CONTROL: signal from t-1, target window starts at t -----
            x_full = signals[sig].shift(1)
            frame = pd.concat([targets[tgt].rename("y"), x_full.rename("x")], axis=1).dropna()
            if len(frame) < 250:
                continue
            y = frame["y"].to_numpy()
            x = frame["x"].to_numpy()
            n = len(y)

            lag = canonical_hac_lag(H, n)
            fit = nw_ols(y, x, lag)
            sens = {}
            for mult, label in [(1.5, "1.5H"), (2.0, "2H")]:
                alt = nw_ols(y, x, int(np.ceil(H * mult)))
                sens[label] = {
                    "hac_lag": int(alt["hac_lag"]),
                    "t": round(float(alt["t"][1]), 4),
                    "p": round(float(alt["p"][1]), 6),
                }

            hod = None
            if base == "fwd_ret":
                h1b = hodrick_1b(x_full, ret_next, H, frame.index)
                if h1b and h1b["se"] > 0:
                    t_h = float(fit["beta"][1] / h1b["se"])
                    hod = {
                        "se": h1b["se"],
                        "t": round(t_h, 4),
                        "p": round(float(2.0 * stats.norm.sf(abs(t_h))), 6),
                        **{k: v for k, v in h1b.items() if k != "se"},
                    }

            nonov = nonoverlapping_phases(y, x, H)
            if nonov.get("status") == "ok":
                nonov["sign_agreement_with_full_sample"] = bool(
                    np.sign(nonov["beta_mean"]) == np.sign(fit["beta"][1])
                )

            span_years = (frame.index[-1] - frame.index[0]).days / 365.25
            cells.append(
                {
                    "signal": sig,
                    "signal_kind": SIGNAL_KIND[sig],
                    "family": SIGNAL_FAMILY[sig],
                    "target": base,
                    "target_kind": TARGET_KINDS[base],
                    "horizon_days": H,
                    "sample_start": str(frame.index[0].date()),
                    "sample_end": str(frame.index[-1].date()),
                    "n_overlapping_obs": int(n),
                    "span_years": round(span_years, 2),
                    "effective_sample_size": round(span_years / (H / 252.0), 1),
                    "beta": float(fit["beta"][1]),
                    "se_hac": float(fit["se"][1]),
                    "r2": round(float(fit["r2"]), 6),
                    "hac_lag": int(fit["hac_lag"]),
                    "t_hac": round(float(fit["t"][1]), 4),
                    "p_hac": round(float(fit["p"][1]), 6),
                    "hac_lag_sensitivity": sens,
                    "hodrick_1b": hod,
                    "nonoverlapping": nonov,
                    "_y": y,
                    "_x": x,
                    "_index": frame.index,
                }
            )

print(f"    {len(cells)} cells estimated")

# ======================================================================================
# 7. Multivariate incremental test  (differentiation test D1, part 2)
# ======================================================================================
print("\n[6] Multivariate incremental tests (slope | level, variance term structure) ...")

multivariate: list[dict] = []
for sig in SLOPE_SIGNALS:
    controls = SLOPE_CONTROLS[sig]
    for base in ["fwd_ret", "fwd_mdd"]:
        for H in HORIZONS:
            tgt = f"{base}_{H}"
            cols = {c: signals[c].shift(1) for c in controls}
            cols[sig] = signals[sig].shift(1)
            frame = pd.concat(
                [targets[tgt].rename("y")] + [v.rename(k) for k, v in cols.items()], axis=1
            ).dropna()
            if len(frame) < 250:
                continue
            names = controls + [sig]
            X = frame[names].to_numpy()
            y = frame["y"].to_numpy()
            lag = canonical_hac_lag(H, len(y))
            fit = nw_ols(y, X, lag)
            # variance inflation for the slope column
            others = X[:, :-1]
            Zo = np.column_stack([np.ones(len(y)), others])
            b, *_ = np.linalg.lstsq(Zo, X[:, -1], rcond=None)
            resid_slope = X[:, -1] - Zo @ b
            ss_tot = float(np.sum((X[:, -1] - X[:, -1].mean()) ** 2))
            r2_slope_on_controls = 1.0 - float(resid_slope @ resid_slope) / ss_tot
            multivariate.append(
                {
                    "signal": sig,
                    "controls": controls,
                    "target": base,
                    "horizon_days": H,
                    "n": int(len(y)),
                    "hac_lag": int(fit["hac_lag"]),
                    "coefficients": {
                        nm: {
                            "beta": float(fit["beta"][i + 1]),
                            "t_hac": round(float(fit["t"][i + 1]), 4),
                            "p_hac": round(float(fit["p"][i + 1]), 6),
                        }
                        for i, nm in enumerate(names)
                    },
                    "incremental_t_on_slope": round(float(fit["t"][-1]), 4),
                    "incremental_p_on_slope": round(float(fit["p"][-1]), 6),
                    "r2_slope_explained_by_controls": round(r2_slope_on_controls, 4),
                    "variance_inflation_factor": round(
                        float(1.0 / max(1e-12, 1.0 - r2_slope_on_controls)), 3
                    ),
                    "r2_full": round(float(fit["r2"]), 6),
                }
            )

# ======================================================================================
# 8. Multiple-testing correction
# ======================================================================================
print("\n[7] Multiple-testing correction (Romano-Wolf + Holm) ...")

multiple_testing: dict[str, object] = {
    "families": {},
    "family_definition": "One family per data-availability group, so the bootstrap can "
    "resample a single common row index across all cells in the family. Cells = signals "
    "x {fwd_ret, fwd_mdd} x {21,63,126,252}.",
    "romano_wolf": {
        "B": N_BOOT,
        "seed": SEED,
        "resampling": "circular block bootstrap, block length = max horizon in family (252)",
        "studentisation": "(beta_b - beta_hat) / se_HAC(original sample); the same constant "
        "divides observed and bootstrap statistics, which is what makes the stepdown valid",
    },
}

for fam in sorted({c["family"] for c in cells}):
    fam_cells = [c for c in cells if c["family"] == fam]
    common = fam_cells[0]["_index"]
    for c in fam_cells:
        common = common.union(c["_index"])
    common = common.sort_values()
    pos = pd.Series(np.arange(len(common)), index=common)

    Y = np.full((len(common), len(fam_cells)), np.nan)
    Xm = np.full((len(common), len(fam_cells)), np.nan)
    for j, c in enumerate(fam_cells):
        rows = pos.reindex(c["_index"]).to_numpy()
        Y[rows, j] = c["_y"]
        Xm[rows, j] = c["_x"]

    beta_hat = np.array([c["beta"] for c in fam_cells])
    se_hat = np.array([c["se_hac"] for c in fam_cells])
    t_obs = np.array([c["t_hac"] for c in fam_cells])

    block = max(HORIZONS)
    rng = np.random.default_rng(SEED)
    boot_t = np.full((N_BOOT, len(fam_cells)), np.nan)
    for b in range(N_BOOT):
        idx = circular_block_indices(len(common), block, rng)
        for j in range(len(fam_cells)):
            bb = univariate_beta(Y[idx, j], Xm[idx, j])
            if np.isfinite(bb) and np.isfinite(se_hat[j]) and se_hat[j] > 0:
                boot_t[b, j] = (bb - beta_hat[j]) / se_hat[j]

    abs_obs = np.abs(t_obs)
    order = np.argsort(-abs_obs)
    p_rw = np.ones(len(fam_cells))
    running = 0.0
    for rank, j in enumerate(order):
        remaining = order[rank:]
        sub = np.abs(boot_t[:, remaining])
        maxdist = np.nanmax(sub, axis=1)
        maxdist = maxdist[np.isfinite(maxdist)]
        raw = float(np.mean(maxdist >= abs_obs[j])) if len(maxdist) else 1.0
        running = max(running, raw)
        p_rw[j] = min(1.0, running)

    p_unadj = [c["p_hac"] for c in fam_cells]
    p_holm = holm(p_unadj)
    for j, c in enumerate(fam_cells):
        c["p_romano_wolf"] = round(float(p_rw[j]), 4)
        c["p_holm_within_family"] = round(float(p_holm[j]), 6)

    multiple_testing["families"][fam] = {
        "n_cells": len(fam_cells),
        "common_sample_start": str(common[0].date()),
        "common_sample_end": str(common[-1].date()),
        "n_rows": int(len(common)),
        "bootstrap_block_length": int(block),
        "n_blocks_per_replicate": int(np.ceil(len(common) / block)),
        "n_cells_unadjusted_p_lt_05": int(sum(p < 0.05 for p in p_unadj)),
        "n_cells_romano_wolf_p_lt_05": int(np.sum(p_rw < 0.05)),
        "n_cells_holm_p_lt_05": int(sum(p < 0.05 for p in p_holm)),
    }
    print(
        f"    family {fam}: {len(fam_cells)} cells, "
        f"{multiple_testing['families'][fam]['n_cells_unadjusted_p_lt_05']} unadj < .05 -> "
        f"{multiple_testing['families'][fam]['n_cells_romano_wolf_p_lt_05']} RW < .05 "
        f"({multiple_testing['families'][fam]['n_blocks_per_replicate']} bootstrap blocks)"
    )

global_holm = holm([c["p_hac"] for c in cells])
for c, ph in zip(cells, global_holm):
    c["p_holm_global"] = round(float(ph), 6)
multiple_testing["global_holm"] = {
    "n_cells": len(cells),
    "n_p_lt_05": int(sum(p < 0.05 for p in global_holm)),
    "note": "Holm across ALL cells regardless of family; the most conservative view.",
}

# ======================================================================================
# 9. Sub-period stability
# ======================================================================================
print("\n[8] Sub-period stability ...")

SUBPERIODS = [
    ("1993-2002_dotcom", "1993-01-01", "2002-12-31"),
    ("2003-2012_GFC", "2003-01-01", "2012-12-31"),
    ("2013-2019_postGFC", "2013-01-01", "2019-12-31"),
    ("2020-2026_covid_and_after", "2020-01-01", "2026-12-31"),
]

subperiods: list[dict] = []
HEADLINE = [(s, b, H) for s in SLOPE_SIGNALS for b in ["fwd_ret", "fwd_mdd"] for H in [126, 252]]
for sig, base, H in HEADLINE:
    tgt = f"{base}_{H}"
    x_full = signals[sig].shift(1)
    frame = pd.concat([targets[tgt].rename("y"), x_full.rename("x")], axis=1).dropna()
    for label, lo, hi in SUBPERIODS:
        sub = frame.loc[lo:hi]
        if len(sub) < 200:
            subperiods.append(
                {
                    "signal": sig,
                    "target": base,
                    "horizon_days": H,
                    "subperiod": label,
                    "status": "insufficient_data",
                    "n": int(len(sub)),
                }
            )
            continue
        lag = canonical_hac_lag(H, len(sub))
        fit = nw_ols(sub["y"].to_numpy(), sub["x"].to_numpy(), lag)
        span = (sub.index[-1] - sub.index[0]).days / 365.25
        subperiods.append(
            {
                "signal": sig,
                "target": base,
                "horizon_days": H,
                "subperiod": label,
                "status": "ok",
                "n": int(len(sub)),
                "effective_sample_size": round(span / (H / 252.0), 1),
                "beta": float(fit["beta"][1]),
                "t_hac": round(float(fit["t"][1]), 4),
                "p_hac": round(float(fit["p"][1]), 6),
                "r2": round(float(fit["r2"]), 6),
            }
        )

stability_summary = {}
for sig, base, H in HEADLINE:
    rows = [
        r
        for r in subperiods
        if r["signal"] == sig
        and r["target"] == base
        and r["horizon_days"] == H
        and r["status"] == "ok"
    ]
    if not rows:
        continue
    betas = [r["beta"] for r in rows]
    stability_summary[f"{sig}|{base}|{H}"] = {
        "n_subperiods_estimable": len(rows),
        "sign_flips": bool(len({np.sign(b) for b in betas}) > 1),
        "n_subperiods_abs_t_gt_3": int(sum(abs(r["t_hac"]) > HARVEY_T for r in rows)),
        "t_values": {r["subperiod"]: r["t_hac"] for r in rows},
    }

# ======================================================================================
# 10. Out-of-sample: expanding window vs historical mean, Clark-West
# ======================================================================================
print("\n[9] Out-of-sample expanding-window evaluation ...")

oos_results: list[dict] = []

# Long horizons are the hypothesis; fwd_mdd at H=21 is included because that is where
# the only in-sample survivors sit, and an in-sample survivor that is never checked
# out of sample is exactly the kind of claim this repo does not accept.
# Every long-horizon cell that the POSITIVE gate can consider must have an OOS
# counterpart, otherwise a missing cell could let an in-sample survivor through unchecked.
OOS_GRID = [
    (sig, base, H)
    for sig in SLOPE_SIGNALS + ["skew_level", "vts_3m", "vts_6m"]
    for base, H in [
        ("fwd_ret", 126),
        ("fwd_ret", 252),
        ("fwd_mdd", 126),
        ("fwd_mdd", 252),
        ("fwd_mdd", 21),
    ]
]

for sig, base, H in OOS_GRID:
    tgt = f"{base}_{H}"
    x_full = signals[sig].shift(1)
    frame = pd.concat([targets[tgt].rename("y"), x_full.rename("x")], axis=1).dropna()
    y = frame["y"].to_numpy()
    x = frame["x"].to_numpy()
    n = len(y)
    actual, f_small, f_large, origins = [], [], [], []
    for i in range(MIN_TRAIN + H, n, STEP):
        # LOOKAHEAD CONTROL: a training row j may only be used when its whole target
        # window has closed at or before the forecast origin i, i.e. j + H <= i.
        j_max = i - H
        if j_max < MIN_TRAIN:
            continue
        ytr, xtr = y[:j_max], x[:j_max]
        ok = np.isfinite(ytr) & np.isfinite(xtr)
        if ok.sum() < MIN_TRAIN:
            continue
        ytr, xtr = ytr[ok], xtr[ok]
        Z = np.column_stack([np.ones(len(ytr)), xtr])
        beta, *_ = np.linalg.lstsq(Z, ytr, rcond=None)
        actual.append(y[i])
        f_large.append(float(beta[0] + beta[1] * x[i]))
        f_small.append(float(ytr.mean()))
        origins.append(frame.index[i])

    if len(actual) < 30:
        oos_results.append(
            {
                "signal": sig,
                "target": base,
                "horizon_days": H,
                "status": "insufficient_origins",
                "n_origins": len(actual),
            }
        )
        continue

    a = np.array(actual)
    fs = np.array(f_small)
    fl = np.array(f_large)
    # Consecutive origins are STEP days apart while targets span H days, so successive
    # forecast errors overlap for ceil(H/STEP) origins. That, not 1, is the DM horizon.
    h_origin = max(1, int(np.ceil(H / STEP)))
    lag = canonical_hac_lag(h_origin, len(a))
    cw = clark_west_test(a, fs, fl, h=h_origin, max_lag=lag)
    mse_small = float(np.mean((a - fs) ** 2))
    mse_large = float(np.mean((a - fl) ** 2))
    span = (origins[-1] - origins[0]).days / 365.25
    oos_results.append(
        {
            "signal": sig,
            "target": base,
            "horizon_days": H,
            "status": "ok",
            "n_origins": len(a),
            "origin_step_trading_days": STEP,
            "overlap_in_origin_units": h_origin,
            "oos_start": str(origins[0].date()),
            "oos_end": str(origins[-1].date()),
            "oos_span_years": round(span, 2),
            "effective_independent_oos_obs": round(span / (H / 252.0), 1),
            "mse_historical_mean": mse_small,
            "mse_predictive": mse_large,
            "oos_r2_campbell_thompson": round(1.0 - mse_large / mse_small, 6),
            "clark_west": {
                k: (round(v, 6) if isinstance(v, float) else v) for k, v in cw.items()
            },
        }
    )
    print(
        f"    {sig:14s} {base:8s} H={H:3d}  OOS R2 = {1.0 - mse_large / mse_small:+.4f}  "
        f"CW t = {cw['t_stat']:+.3f} (p1 = {cw['p_value_one_sided']:.3f}), "
        f"eff. indep. obs = {span / (H / 252.0):.0f}"
    )

# ======================================================================================
# 11. Differentiation tests D1 / D2
# ======================================================================================
print("\n[10] Differentiation tests ...")


def cell_lookup(sig: str, base: str, H: int) -> dict | None:
    for c in cells:
        if c["signal"] == sig and c["target"] == base and c["horizon_days"] == H:
            return c
    return None


d1 = {
    "question": "Does the term-structure slope carry information the SKEW LEVEL does not?",
    "evidence_correlation": {
        s: degeneracy["per_signal"][s]["corr_with_skew_level"] for s in SLOPE_SIGNALS
    },
    "evidence_incremental_t": {},
    "verdict": None,
}
for m in multivariate:
    if m["horizon_days"] in (126, 252):
        d1["evidence_incremental_t"][
            f"{m['signal']}|{m['target']}|{m['horizon_days']}"
        ] = m["incremental_t_on_slope"]
n_incr_sig = sum(abs(v) > HARVEY_T for v in d1["evidence_incremental_t"].values())
model_slopes = [s for s in SLOPE_SIGNALS if SIGNAL_KIND[s] == "slope_model_extrapolated"]
model_slopes_degenerate = all(degeneracy["per_signal"][s]["degenerate"] for s in model_slopes)
d1["n_incremental_abs_t_gt_3"] = int(n_incr_sig)
d1["n_incremental_tests"] = len(d1["evidence_incremental_t"])
d1["model_extrapolated_slopes_degenerate_vs_level"] = bool(model_slopes_degenerate)
d1["physical_only_slope_carries_no_risk_neutral_information"] = True
d1["degeneracy_detail"] = {
    "model_extrapolated": {
        s: degeneracy["per_signal"][s] for s in model_slopes
    },
    "physical_only": {
        "ts_realized": degeneracy["per_signal"]["ts_realized"],
        "why_it_is_not_a_skew_premium_slope": degeneracy["analytic_note_ts_realized"]["comment"],
    },
}
d1["verdict"] = (
    "PASS"
    if n_incr_sig > 0
    else ("FAIL_degenerate" if model_slopes_degenerate else "FAIL_no_increment")
)

d2 = {
    "question": "Is the slope signal stronger at long horizons than at short ones?",
    "abs_t_by_horizon": {},
    "verdict": None,
}
long_beats_short = 0
comparisons = 0
for sig in SLOPE_SIGNALS:
    for base in ["fwd_ret", "fwd_mdd"]:
        row = {}
        for H in HORIZONS:
            c = cell_lookup(sig, base, H)
            if c:
                row[str(H)] = abs(c["t_hac"])
        if len(row) == len(HORIZONS):
            d2["abs_t_by_horizon"][f"{sig}|{base}"] = {k: round(v, 3) for k, v in row.items()}
            comparisons += 1
            if row["252"] > row["21"]:
                long_beats_short += 1
d2["n_cases_long_gt_short"] = long_beats_short
d2["n_cases"] = comparisons
d2["verdict"] = "PASS" if comparisons and long_beats_short >= comparisons - 1 else "MIXED_OR_FAIL"

# ======================================================================================
# 12. Verdict
# ======================================================================================
survivors = [
    {
        "signal": c["signal"],
        "target": c["target"],
        "horizon_days": c["horizon_days"],
        "t_hac": c["t_hac"],
        "p_romano_wolf": c.get("p_romano_wolf"),
        "hodrick_t": (c["hodrick_1b"] or {}).get("t"),
    }
    for c in cells
    if abs(c["t_hac"]) > HARVEY_T
    and c.get("p_romano_wolf", 1.0) < 0.05
    and (c["hodrick_1b"] is None or abs(c["hodrick_1b"]["t"]) > HARVEY_T)
]
slope_survivors = [s for s in survivors if SIGNAL_KIND[s["signal"]].startswith("slope")]
oos_positive = [
    r
    for r in oos_results
    if r.get("status") == "ok"
    and r["oos_r2_campbell_thompson"] > 0
    and r["clark_west"]["p_value_one_sided"] < 0.05
    and SIGNAL_KIND[r["signal"]].startswith("slope")
]
# The hypothesis under test is specifically about 6-12 month horizons. A slope signal
# that only works at H=21 does not support it, however clean that short-horizon cell is.
LONG_H = {126, 252}
slope_survivors_long = [s for s in slope_survivors if s["horizon_days"] in LONG_H]
oos_positive_long = [r for r in oos_positive if r["horizon_days"] in LONG_H]

# A POSITIVE verdict requires ONE SINGLE (signal, target, horizon) specification to clear
# in-sample, out-of-sample and incremental-vs-level testing *together*. Letting three
# different cells each supply one leg is how a search over 64 cells manufactures a finding.
oos_by_cell = {
    (r["signal"], r["target"], r["horizon_days"]): r
    for r in oos_results
    if r.get("status") == "ok"
}
mv_by_cell = {(m["signal"], m["target"], m["horizon_days"]): m for m in multivariate}

joint_survivors = []
for s in slope_survivors_long:
    key = (s["signal"], s["target"], s["horizon_days"])
    oos_cell = oos_by_cell.get(key)
    mv_cell = mv_by_cell.get(key)
    # Fail closed: a missing OOS or multivariate counterpart is never a pass.
    passes_oos = bool(
        oos_cell
        and oos_cell["oos_r2_campbell_thompson"] > 0
        and oos_cell["clark_west"]["p_value_one_sided"] < 0.05
    )
    passes_incremental = bool(
        mv_cell and abs(mv_cell["incremental_t_on_slope"]) > HARVEY_T
    )
    if passes_oos and passes_incremental:
        joint_survivors.append(
            {
                **s,
                "oos_r2": oos_cell["oos_r2_campbell_thompson"],
                "cw_p_one_sided": oos_cell["clark_west"]["p_value_one_sided"],
                "incremental_t": mv_cell["incremental_t_on_slope"],
            }
        )

if joint_survivors:
    verdict = "POSITIVE"
elif d1["verdict"].startswith("FAIL") and not slope_survivors_long:
    verdict = "NULL_DEGENERATE"
else:
    verdict = "NULL"

verdict_block = {
    "verdict": verdict,
    "harvey_threshold": HARVEY_T,
    "n_cells_tested": len(cells),
    "n_cells_abs_t_hac_gt_3": int(sum(abs(c["t_hac"]) > HARVEY_T for c in cells)),
    "n_cells_surviving_romano_wolf_and_hodrick": len(survivors),
    "n_slope_cells_surviving": len(slope_survivors),
    "n_slope_cells_surviving_at_6_to_12_month_horizons": len(slope_survivors_long),
    "surviving_cells": survivors,
    "n_slope_oos_cells_with_positive_r2_and_cw_p_lt_05": len(oos_positive),
    "n_slope_oos_cells_positive_at_6_to_12_month_horizons": len(oos_positive_long),
    "positive_verdict_rule": (
        "POSITIVE requires >=1 single (signal, target, horizon) cell at H in {126,252} "
        "that simultaneously (a) survives Romano-Wolf and Hodrick in sample, (b) has "
        "OOS R2 > 0 with Clark-West one-sided p < 0.05, and (c) has |incremental t| > 3 "
        "against the level and the maturity-matched variance term structure. Evidence "
        "from different cells is never combined; a missing OOS or multivariate "
        "counterpart fails closed."
    ),
    "n_joint_survivors": len(joint_survivors),
    "joint_survivors": joint_survivors,
    "differentiation_D1_slope_vs_level": d1["verdict"],
    "differentiation_D2_long_vs_short_horizon": d2["verdict"],
    "headline_long_horizon_evidence": {
        "max_abs_t_hac_over_slope_cells_at_H_126_252": round(
            max(
                (
                    abs(c["t_hac"])
                    for c in cells
                    if SIGNAL_KIND[c["signal"]].startswith("slope")
                    and c["horizon_days"] in LONG_H
                ),
                default=float("nan"),
            ),
            4,
        ),
        "max_abs_incremental_t_at_H_126_252": round(
            max((abs(v) for v in d1["evidence_incremental_t"].values()), default=float("nan")), 4
        ),
        "best_oos_r2_over_slope_cells_at_H_126_252": round(
            max(
                (
                    r["oos_r2_campbell_thompson"]
                    for r in oos_results
                    if r.get("status") == "ok"
                    and SIGNAL_KIND[r["signal"]].startswith("slope")
                    and r["horizon_days"] in LONG_H
                ),
                default=float("nan"),
            ),
            6,
        ),
    },
}

# ======================================================================================
# 13. Figures
# ======================================================================================
print("\n[11] Figures ...")

fig, axes = plt.subplots(3, 1, figsize=(13, 11), sharex=True)
ax = axes[0]
ax.plot(df.index, df["SPY"], color="#1f4e79", lw=0.9)
ax.set_yscale("log")
ax.set_ylabel("SPY (log, adj close)")
ax.set_title("K1736  Skew-premium term structure vs long-horizon SPY outcomes")
ax.grid(alpha=0.25)

ax = axes[1]
ax.plot(signals.index, signals["skew_level"], color="#b03a2e", lw=0.7,
        label=r"level: $\zeta_{30}$ = (100 - SKEW)/10")
ax.plot(signals.index, signals["rn_slope_6m"], color="#1e8449", lw=0.7,
        label=r"slope: $\zeta_{180} - \zeta_{30}$ (VIX6M-carried)")
corr_txt = degeneracy["per_signal"]["rn_slope_6m"]["corr_with_skew_level"]
ax.set_ylabel("risk-neutral skewness")
ax.legend(loc="lower left", fontsize=9)
ax.grid(alpha=0.25)
ax.set_title(f"Level and slope move as one series: corr = {corr_txt:+.3f}", fontsize=10)

ax = axes[2]
ax.plot(targets["fwd_mdd_252"].index, 100 * targets["fwd_mdd_252"], color="#7d3c98", lw=0.8,
        label="forward 252d max drawdown of SPY (%)")
ax2 = ax.twinx()
ax2.plot(targets["fwd_ret_252"].index, 100 * targets["fwd_ret_252"], color="#d68910", lw=0.6,
         alpha=0.8, label="forward 252d log return (%)")
ax.set_ylabel("fwd 252d MDD (%)")
ax2.set_ylabel("fwd 252d return (%)")
ax.grid(alpha=0.25)
lines = ax.get_lines() + ax2.get_lines()
ax.legend(lines, [ln.get_label() for ln in lines], loc="upper left", fontsize=9)
ax.set_xlabel("date (targets are stamped at their ORIGIN date t, covering t..t+252)")
fig.tight_layout()
fig.savefig(FIG_DIR / "K1736_slope_level_and_targets.png", dpi=130)
plt.close(fig)

fig, axes = plt.subplots(1, 2, figsize=(13, 5))
pair = signals[["skew_level", "rn_slope_6m"]].dropna()
axes[0].scatter(pair["skew_level"], pair["rn_slope_6m"], s=3, alpha=0.25, color="#1e8449")
axes[0].set_xlabel(r"level  $\zeta_{30}$")
axes[0].set_ylabel(r"slope  $\zeta_{180}-\zeta_{30}$")
axes[0].set_title(f"D1 degeneracy check: corr = {corr_txt:+.3f}, "
                  f"$R^2$ = {corr_txt ** 2:.3f}")
axes[0].grid(alpha=0.25)

ax = axes[1]
width = 0.35
labels, t_ret, t_mdd = [], [], []
for sig in SLOPE_SIGNALS:
    for H in HORIZONS:
        cr = cell_lookup(sig, "fwd_ret", H)
        cm = cell_lookup(sig, "fwd_mdd", H)
        if cr and cm:
            labels.append(f"{sig.replace('_', ' ')}\nH={H}")
            t_ret.append(abs(cr["t_hac"]))
            t_mdd.append(abs(cm["t_hac"]))
pos = np.arange(len(labels))
ax.bar(pos - width / 2, t_ret, width, label="|t| fwd return", color="#d68910")
ax.bar(pos + width / 2, t_mdd, width, label="|t| fwd MDD", color="#7d3c98")
ax.axhline(HARVEY_T, color="#b03a2e", ls="--", lw=1.2, label="Harvey |t| = 3")
ax.axhline(1.96, color="grey", ls=":", lw=1.0, label="|t| = 1.96")
ax.set_xticks(pos)
ax.set_xticklabels(labels, rotation=90, fontsize=6.5)
ax.set_ylabel("|t| (Newey-West, lag = max(H, canonical))")
ax.set_title("Slope signals: HAC |t| across horizons and targets")
ax.legend(fontsize=8)
ax.grid(alpha=0.25, axis="y")
fig.tight_layout()
fig.savefig(FIG_DIR / "K1736_degeneracy_and_tstats.png", dpi=130)
plt.close(fig)

# ======================================================================================
# 14. Assemble and finalise
# ======================================================================================
for c in cells:
    for k in ["_y", "_x", "_index"]:
        c.pop(k, None)

payload = {
    "experiment_id": "K1736",
    "title": "Skewness risk premium term structure as a long-horizon tail signal",
    "research_question": (
        "Does the TERM-STRUCTURE SLOPE of the skewness risk premium predict 6-12 month "
        "SPY returns and drawdowns better than the SKEW LEVEL that seven prior "
        "experiments already rejected at short horizons?"
    ),
    "differentiation_from_prior_nulls": {
        "prior_null_experiments": ["K181", "K184", "K210", "K258", "K447", "K535", "K979", "K43"],
        "prior_design_cell": "SKEW LEVEL -> short-horizon realized volatility",
        "this_design_cell": "skew-premium term-structure SLOPE -> 6-12 month return / drawdown",
        "D1_slope_vs_level": d1,
        "D2_long_vs_short_horizon": d2,
    },
    "data_diagnostics": data_diagnostics,
    "construction": {
        "zeta30": "(100 - SKEW)/10, the CBOE-defined 30-day risk-neutral skewness",
        "realized_skew_h": "trailing h-day sample skewness of daily log returns / sqrt(h)",
        "zeta_T": "zeta30 * sqrt(30/T) * (VIX/VIX_T)^3  [constant jump intensity assumption]",
        "signals": SIGNAL_KIND,
        "signal_families": SIGNAL_FAMILY,
        "why_construction_a_is_degenerate": degeneracy["analytic_note_ts_realized"]["comment"],
    },
    "methodology": {
        "lookahead_policy": (
            "Every regressor is signals[sig].shift(1): value observed at the close of t-1 "
            "predicts a target window that opens at the close of t. Forward targets are "
            "stamped at origin t and read prices t..t+H. In the OOS loop a training row j "
            "enters only when j + H <= forecast origin i, so no training label overlaps "
            "the forecast date."
        ),
        "overlap_handling": (
            "Newey-West HAC with lag = max(H, ceil(H^(1/3) n^(1/3))) - the repo canonical "
            "bandwidth floored at the overlap length, never h-1; sensitivity at 1.5H and 2H; "
            "Hodrick (1992) 1B standard errors for return targets; all H non-overlapping "
            "phase subsamples; effective sample size = span_years / (H/252) reported per cell."
        ),
        "hodrick_scope": (
            "Hodrick 1B is defined for targets that are sums of one-period returns. Forward "
            "maximum drawdown is a path functional, not such a sum, so Hodrick SEs are "
            "deliberately NOT reported for fwd_mdd cells."
        ),
        "multiple_testing": "Romano-Wolf stepdown (circular block bootstrap) within each "
        "data-availability family, plus Holm within family and Holm across all cells.",
        "oos": "Expanding-window, monthly origins, predictive regression vs expanding "
        "historical mean, Clark-West (2007) nested MSPE-adjusted test (canonical repo "
        "implementation) with HAC lag floored at the overlap length.",
        "seeds": {"numpy": SEED, "bootstrap_replicates": N_BOOT},
        "lookahead_audit": lookahead_audit,
    },
    "degeneracy_diagnostics": degeneracy,
    "univariate_cells": cells,
    "multivariate_incremental": multivariate,
    "multiple_testing": multiple_testing,
    "subperiods": subperiods,
    "subperiod_stability_summary": stability_summary,
    "out_of_sample": oos_results,
    "verdict_block": verdict_block,
}

print("\n" + "=" * 78)
print(f"VERDICT: {verdict}")
print(f"  D1 (slope carries information beyond level): {d1['verdict']}")
print(f"  D2 (long horizon stronger than short):       {d2['verdict']}")
print(f"  cells with |t_HAC| > 3: {verdict_block['n_cells_abs_t_hac_gt_3']}/{len(cells)}")
print(f"  cells surviving Romano-Wolf + Hodrick: {len(survivors)}")
print("=" * 78)

results_path, spec = finalize_experiment(
    results=payload,
    entrypoint=__file__,
    canonical_result="K1736_results.json",
    inputs=[
        "experiments/K1736/data/SKEW.csv",
        "experiments/K1736/data/VIX.csv",
        "experiments/K1736/data/VIX3M.csv",
        "experiments/K1736/data/VIX6M.csv",
        "experiments/K1736/data/SPY.csv",
        "experiments/K1736/data/GSPC.csv",
    ],
    outputs=[
        "figures/K1736_slope_level_and_targets.png",
        "figures/K1736_degeneracy_and_tstats.png",
    ],
    seeds=[("numpy", SEED)],
    started_at=T0,
)
print(f"\nwrote {results_path}")
print(f"runtime {time.time() - T0:.1f}s")
