"""
paper2_taiwan_indiv_rolling_gamma
=================================
Calendar-aligned rolling-window (w=2000) GJR-GARCH gamma estimates for the
Taiwan-VT Table 2 (`tab:gamma`) rolling block.

WHAT CHANGED (2026-07-13) AND WHY THE PREVIOUS "RESOLVED" WAS FALSE
-------------------------------------------------------------------
The 2026-07-07 run answered Codex's calendar-alignment CONDITIONAL_PASS caveat
by truncating all ten securities to a common terminal date of 2025-01-22, and
stamped the results JSON `codex_caveat_calendar_alignment: "RESOLVED"`.

That resolution was cosmetic. 2025-01-22 was not a market fact: it was the last
row of two stale offline snapshots (experiments/k1302/data/{2383,2886}_tw.csv).
The other eight securities had data running well into 2026 and were discarded to
match two expired files. Calendar alignment was achieved by throwing away a year
of data -- so the paper claimed a sample through 2026 while Table 2's rolling
rows actually ended in January 2025. Alignment was real; the sample period was
not. That is a research-honesty defect, not merely a precision one.

The stated reason for truncating rather than re-fetching was to preserve the
"fully reproducible, no network" guarantee. Both are obtainable at once: this
experiment re-fetches every series ONCE into its own data/ directory
(fetch_snapshots.py) and then estimates purely offline from those committed
snapshots. Reproducibility is preserved; the sample is honest.

SPEC (unchanged from the previous run -- only the data window moves)
--------------------------------------------------------------------
- GJR-GARCH(1,1), Constant mean, Normal innovations, `arch` package MLE.
- Returns in percentage points (r*100) for numerical stability.
- Rolling window w = 2000; reported row = the LAST window ending on/before the
  variant's common end date (K892 `rolling_w2000.last_window` convention).
- Persistence = alpha + 0.5*gamma + beta.
- t-values are the arch-package robust (Bollerslev-Wooldridge sandwich) MLE
  t-statistics. NOTE: body_v3.tex's table note calls these "Newey-West HAC" --
  that wording is wrong and should be corrected to Bollerslev-Wooldridge robust
  (see `provenance_note`). We report what we actually compute.

DATA (offline snapshots, committed under data/; see data/MANIFEST.json)
-----------------------------------------------------------------------
All 12 series are a single uniform yfinance pull (auto_adjust=False, `Adj Close`
column), fetched 2026-07-13. Each series' log returns were verified to reproduce
the previous canonical snapshots (paper CSV / k1302 / k1302b) to <1e-6 over the
overlapping sample, so this refresh changes the SAMPLE WINDOW, not the data
convention.

The old results JSON claimed the package mixed adjusted and raw closes ("Mixed
adj/close is inherited from the canonical K1302/K1302b data package"). That
caveat was FALSE: the k1302b `Close` column came from an auto_adjust=True
download, i.e. it is already dividend-adjusted. Verified empirically -- k1302b
log returns match fresh Adj-Close log returns to ~1e-6. There is no mixed
convention anywhere in the package.

VARIANTS
--------
primary_2026        : common end = latest trading day on which ALL 12 series
                      have data (2026-07-09; bound by ^TWII). THE HEADLINE.
paper_csv_terminal  : common end = 2026-04-17, the terminal date of the paper's
                      canonical CSV for the Taiwan single stocks. Offered so the
                      main thread can keep Table 2's window flush with the rest
                      of the paper's tables if it prefers.
legacy_2025_01_22   : common end = the previous run's stale terminal date, but
                      estimated on the FRESH data. Holding the data fixed and
                      moving only the window (and vice versa) decomposes how much
                      of the change comes from the refresh versus the window.

DATA-QUALITY SENSITIVITY (2317)
-------------------------------
yfinance's 2317.TW series is corrupted around its 2018-10-18 capital reduction
(split factor 0.8): the close is frozen at 85.125 for six consecutive sessions
(2018-10-18..10-25, six spurious zero returns) and then "catches up" with a
-10.49% move on 2018-10-26 -- beyond Taiwan's +/-10% daily limit, so it cannot be
a genuine close-to-close move. This block sits INSIDE the rolling window, and the
catch-up day is a large negative shock, exactly what gamma loads on. The defect is
inherited (the previous snapshots carry it identically), so the primary estimate
keeps the data as-fetched for consistency with the rest of the paper's data
handling; a sensitivity that excludes the block is reported alongside so the
reader can see whether 2317's gamma depends on it.

No lookahead: gamma is an in-sample descriptive MLE on the last window, not a
forecast, signal, or OOS split. MLE is deterministic; the seeded RNG below is
used only for perturbed restarts if a fit fails to converge.
"""
import json
import os
from datetime import datetime, timezone

import arch
import numpy as np
import pandas as pd
from arch import arch_model

from volpred.ops.diagnostics import warn

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "paper2_taiwan_indiv_rolling_gamma_results.json")

WINDOW = 2000
SAMPLE_START = "2008-01-01"
SEED = 20260713

# --- Row sets -------------------------------------------------------------
# Canonical 9-stock cross-section (excludes TSMC 2330 and the 0056 ETF).
NINE_STOCKS = {
    "2317.TW": ("Hon Hai", "2317_tw"),
    "2454.TW": ("MediaTek", "2454_tw"),
    "2383.TW": ("Elite Material", "2383_tw"),
    "2886.TW": ("Mega Financial", "2886_tw"),
    "2412.TW": ("Chunghwa Telecom", "2412_tw"),
    "2881.TW": ("Fubon", "2881_tw"),
    "2882.TW": ("Cathay Financial", "2882_tw"),
    "2885.TW": ("Yuanta", "2885_tw"),
    "2891.TW": ("CTBC", "2891_tw"),
}
DISPLAYED = ["2317.TW", "2454.TW", "2886.TW"]  # rows rendered in the paper table
ETF_0056 = ("0056.TW", "Yuanta High Div. ETF", "0056_tw")
INDEX_ROWS = {
    "TWII": ("Taiwan Weighted Index", "twii"),
    "0050.TW": ("Yuanta Taiwan 50 ETF", "0050_tw"),
}

# --- Legacy values, retained for the comparison table ----------------------
# (a) N121: the untraceable values currently rendered in body_v3.tex tab:gamma.
LEGACY_N121 = {
    "2317.TW": {"gamma": 0.052, "gamma_t": 1.14},
    "2454.TW": {"gamma": 0.044, "gamma_t": 0.96},
    "2886.TW": {"gamma": 0.179, "gamma_t": 2.42},
    "0056.TW": {"gamma": 0.112, "gamma_t": 1.87},
}
LEGACY_N121_AVG = {
    "gamma_mean_9stock": 0.054,
    "gamma_mean_10security": 0.060,
    "twii_rolling_gamma": 0.272,
    "ratio_9stock": 5.0,
    "ratio_10security": 4.5,
}
# (b) The 2026-07-07 run: same spec, but truncated to the stale 2025-01-22 end.
PRIOR_RUN_20260707 = {
    "common_end": "2025-01-22",
    "gamma_mean_9stock": 0.0241,
    "gamma_mean_10security": 0.0419,
    "twii_rolling_gamma": 0.1575,
    "ratio_9stock": 6.53,
    "ratio_10security": 3.75,
    "gamma_0056": 0.2023,
    "note": (
        "Calendar-aligned but to a terminal date dictated by two expired snapshots; "
        "the JSON's 'RESOLVED' stamp was false. Superseded by primary_2026."
    ),
}

# --- Known data defects ----------------------------------------------------
# 0050.TW 4:1 split on 2014-01-02 leaves a spurious split-date return even under
# auto_adjust=False; body_v3.tex L33 documents excluding it in the canonical
# replication. It falls outside every window used here, but we apply the paper's
# rule anyway so the script stays correct if the window is ever moved back.
SPLIT_EXCLUSIONS = {"0050.TW": ["2014-01-02"]}

# 2317.TW capital-reduction corruption (see module docstring). Excluded only in
# the sensitivity variant, never in the primary.
CORRUPT_2317 = ("2018-10-18", "2018-10-26")

VARIANTS = {
    "primary_2026": None,          # filled in from the data itself (common end)
    "paper_csv_terminal": "2026-04-17",
    "legacy_2025_01_22": "2025-01-22",
}

# Every fit in the run, including the ~230 in the sweep, so the honesty ledger's
# "all converged, no restarts needed" is backed by a counter rather than by a spot
# check on three variants.
_FIT_DIAGNOSTICS = {"fits": 0, "max_restarts": 0, "nonzero_convergence": 0}


def load_returns(base: str, ticker: str) -> pd.Series:
    """Log returns from the committed offline snapshot. No exclusions applied here.

    Every exclusion -- the 0050 split date and the 2317 corruption alike -- is routed
    through `last_window(ablate=...)` so it happens AFTER the window is cut. Dropping
    rows from the series first would let the last-2000 slice reach further back to
    refill itself, silently shifting that row's window start away from the other
    eleven and de-aligning the very calendar we are trying to align.
    """
    path = os.path.join(DATA, f"{base}.csv")
    s = pd.read_csv(path, parse_dates=["date"]).set_index("date")["adj_close"]
    s = s.dropna().astype(float).sort_index()
    if s.index.duplicated().any():
        raise RuntimeError(f"{ticker}: duplicate dates in snapshot")
    r = np.log(s / s.shift(1)).dropna()
    return r[r.index >= pd.Timestamp(SAMPLE_START)]


def estimate_gjr(returns: pd.Series) -> dict:
    """GJR-GARCH(1,1) MLE via arch (K892 spec).

    A non-zero convergence flag is a numerical failure of the optimizer, not
    evidence against the model (CLAUDE.md methodology rule). On failure we retry
    from seeded perturbed starting values and keep the best log-likelihood.
    """
    ret_pct = returns * 100.0
    am = arch_model(ret_pct, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant")
    res = am.fit(disp="off", options={"maxiter": 5000})
    restarts = 0
    restart_failures: list[str] = []
    if res.convergence_flag != 0:
        warn(
            "rolling-gamma",
            f"default start failed to converge (flag={res.convergence_flag}) on "
            f"{returns.index[0].date()}..{returns.index[-1].date()}; entering seeded multistart",
        )
        rng = np.random.default_rng(SEED)
        # `best` tracks the best CONVERGED candidate only. Seeding it with the failed
        # incumbent would be a trap: an optimizer that stopped at maxiter while still
        # climbing, or parked at a non-stationary point, can carry a HIGHER
        # log-likelihood than a legitimate converged optimum -- which would cause every
        # good restart to be rejected and the whole multistart to fall through to the
        # raise below. Compare converged candidates against each other, never against a
        # failure.
        best = None
        for restarts in range(1, 51):
            sv = pd.Series(
                {
                    "mu": float(ret_pct.mean()) * rng.uniform(0.5, 1.5),
                    "omega": float(ret_pct.var()) * rng.uniform(0.02, 0.2),
                    "alpha[1]": rng.uniform(0.01, 0.12),
                    "gamma[1]": rng.uniform(0.0, 0.20),
                    "beta[1]": rng.uniform(0.70, 0.92),
                }
            )
            try:
                cand = am.fit(disp="off", starting_values=sv, options={"maxiter": 5000})
            except Exception as exc:  # a bad random start, not a bad model -- but log it
                restart_failures.append(f"start {restarts}: {type(exc).__name__}: {exc}")
                warn("rolling-gamma", f"multistart {restarts} raised {type(exc).__name__}: {exc}")
                continue
            if cand.convergence_flag == 0 and (
                best is None or cand.loglikelihood > best.loglikelihood
            ):
                best = cand  # keep going: we want the best basin of 50, not the first
        if best is not None:
            res = best
        if res.convergence_flag != 0:
            # Do NOT quietly report the parameters of a failed optimisation as if they
            # were estimates. A package that will not converge is a numerical failure,
            # not evidence about the model -- but it must be visible, not swallowed.
            raise RuntimeError(
                f"GJR MLE failed to converge after 50 seeded restarts on window "
                f"{returns.index[0].date()}..{returns.index[-1].date()} "
                f"(flag={res.convergence_flag}); {len(restart_failures)} restarts raised. "
                "Do not report these parameters -- rescale, change the parameterisation, or "
                "hand-roll the MLE (CLAUDE.md: package failure != model invalid)."
            )
    p, t = res.params, res.tvalues
    alpha, gamma, beta = (
        float(p.get("alpha[1]", np.nan)),
        float(p.get("gamma[1]", np.nan)),
        float(p.get("beta[1]", np.nan)),
    )
    return {
        "omega": float(p.get("omega", np.nan)),
        "alpha": alpha,
        "gamma": gamma,
        "beta": beta,
        "gamma_t": float(t.get("gamma[1]", np.nan)),
        "alpha_t": float(t.get("alpha[1]", np.nan)),
        "beta_t": float(t.get("beta[1]", np.nan)),
        "persistence": alpha + 0.5 * gamma + beta,
        "n_obs": int(len(returns)),
        "convergence": int(res.convergence_flag),
        "restarts_used": restarts,
        "restart_failures": restart_failures,
        "log_likelihood": float(res.loglikelihood),
    }


def last_window(
    returns: pd.Series,
    end_cutoff: pd.Timestamp,
    ablate: list[tuple[str, str]] | None = None,
) -> dict:
    """Estimate on the last WINDOW observations ending on/before `end_cutoff`.

    `ablate` removes date ranges AFTER the window is cut, never before. That ordering
    is the whole point. Excluding rows from the series first would leave the slice
    reaching further back to refill its 2000 observations -- for the 2317 block that
    means pulling in ~7 extra sessions from April 2018, right beside the 2018-Q1
    volatility spike we independently show moves gamma, so the "sensitivity" would
    confound *removed the corrupt days* with *added days from a high-asymmetry period*.
    The same trap applies to the 0050 split date under any window that reaches back to
    2014. Cutting the window first and ablating inside it holds the calendar span fixed,
    so the ablated sample is a strict SUBSET of the primary one and the only thing that
    changes is the observations we meant to remove.

    Cost: n < WINDOW (recorded in n_obs and ablated_obs). That is fine -- gamma is a
    descriptive MLE, not a forecast needing a fixed training size, and 1993 vs 2000
    observations moves the SE by ~0.2%. Sample COMPOSITION dominates sample SIZE.

    Note (disclosed rather than hidden): deleting mid-series rows splices the GARCH
    recursion, so the session after an ablated block is treated as if it followed the
    session before it. That is unavoidable for any ablation and is standard, but it is
    why the ablation is a diagnostic, not the primary estimate.
    """
    r = returns[returns.index <= end_cutoff]
    if len(r) < WINDOW:
        raise ValueError(f"only {len(r)} obs before {end_cutoff.date()} < window {WINDOW}")
    w = r.iloc[-WINDOW:]
    span_start, span_end = w.index[0], w.index[-1]
    if ablate:
        for lo_s, hi_s in ablate:
            lo, hi = pd.Timestamp(lo_s), pd.Timestamp(hi_s)
            w = w[(w.index < lo) | (w.index > hi)]
    est = estimate_gjr(w)
    est["window"] = WINDOW
    # The calendar span of the window, which the ablation deliberately does NOT move.
    est["window_start"] = str(span_start.date())
    est["window_end"] = str(span_end.date())
    if ablate:
        est["ablated_ranges"] = [list(a) for a in ablate]
        est["ablated_obs"] = WINDOW - len(w)
    return est


def _ablations(ticker: str, drop_corrupt_2317: bool) -> list[tuple[str, str]]:
    """Every exclusion for a row, as post-slice ablation ranges (see last_window)."""
    out = [(d, d) for d in SPLIT_EXCLUSIONS.get(ticker, [])]
    if drop_corrupt_2317 and ticker == "2317.TW":
        out.append(CORRUPT_2317)
    return out


def run_variant(end_cutoff: pd.Timestamp, drop_corrupt_2317: bool = False) -> dict:
    per_stock = {}
    for ticker, (name, base) in NINE_STOCKS.items():
        est = last_window(
            load_returns(base, ticker), end_cutoff,
            ablate=_ablations(ticker, drop_corrupt_2317),
        )
        est.update({"name": name, "ticker": ticker, "price_source": f"data/{base}.csv"})
        if ticker in LEGACY_N121:
            est["legacy_n121"] = LEGACY_N121[ticker]
        per_stock[ticker] = est

    et_ticker, et_name, et_base = ETF_0056
    etf = last_window(
        load_returns(et_base, et_ticker), end_cutoff,
        ablate=_ablations(et_ticker, drop_corrupt_2317),
    )
    etf.update(
        {
            "name": et_name,
            "ticker": et_ticker,
            "price_source": f"data/{et_base}.csv",
            "legacy_n121": LEGACY_N121[et_ticker],
        }
    )

    index_rows = {}
    for key, (name, base) in INDEX_ROWS.items():
        est = last_window(
            load_returns(base, key), end_cutoff,
            ablate=_ablations(key, drop_corrupt_2317),
        )
        est.update({"name": name, "ticker": key, "price_source": f"data/{base}.csv"})
        index_rows[key] = est

    gammas = [per_stock[t]["gamma"] for t in NINE_STOCKS]
    g9 = float(np.mean(gammas))
    g10 = float(np.mean(gammas + [etf["gamma"]]))
    twii_g = float(index_rows["TWII"]["gamma"])

    # gamma ranking across the 12 rows -- the 0056 narrative turns on where the
    # ETF lands relative to the individual stocks and the index.
    ranking = sorted(
        [(t, per_stock[t]["gamma"]) for t in NINE_STOCKS]
        + [(et_ticker, etf["gamma"])]
        + [(k, v["gamma"]) for k, v in index_rows.items()],
        key=lambda kv: -kv[1],
    )

    all_rows = list(per_stock.values()) + [etf] + list(index_rows.values())

    # The central claim of this experiment is that the rows are calendar-aligned. Assert
    # it, do not merely record it. The 12 series do NOT share a trading calendar (the
    # stocks' windows start 2018-04-18, the index/ETF rows 2018-04-19 -- the index rows
    # contain a session the stocks lack), so at some cutoffs it is possible for one class
    # of security to land on a different terminal date than another. That would be a
    # silent regression to exactly the defect this run exists to fix.
    window_ends = sorted({e["window_end"] for e in all_rows})
    if len(window_ends) != 1:
        raise RuntimeError(
            f"CALENDAR MISALIGNMENT at cutoff {end_cutoff.date()}: rows ended on "
            f"{window_ends}. Every row must share one window_end -- that is the whole point."
        )
    _FIT_DIAGNOSTICS["fits"] += len(all_rows)
    _FIT_DIAGNOSTICS["max_restarts"] = max(
        _FIT_DIAGNOSTICS["max_restarts"], *(e["restarts_used"] for e in all_rows)
    )
    _FIT_DIAGNOSTICS["nonzero_convergence"] += sum(1 for e in all_rows if e["convergence"] != 0)

    return {
        "common_end": str(end_cutoff.date()),
        "window_end_all_rows": window_ends,
        "per_stock": per_stock,
        "etf_0056": etf,
        "index_rows": index_rows,
        "averages_and_ratio": {
            "gamma_mean_9stock": g9,
            "alpha_mean_9stock": float(np.mean([per_stock[t]["alpha"] for t in NINE_STOCKS])),
            "beta_mean_9stock": float(np.mean([per_stock[t]["beta"] for t in NINE_STOCKS])),
            "gamma_mean_10security_incl_0056": g10,
            "twii_rolling_gamma": twii_g,
            "amplification_ratio_9stock": twii_g / g9,
            "amplification_ratio_10security": twii_g / g10,
            "ratio_base": "rolling-w2000 TWII gamma on the same calendar-aligned window",
        },
        "gamma_ranking_desc": [{"ticker": t, "gamma": g} for t, g in ranking],
        "gamma_0056_rank_of_12": 1 + [t for t, _ in ranking].index(et_ticker),
        "convergence_all_zero": all(
            e["convergence"] == 0
            for e in list(per_stock.values()) + [etf] + list(index_rows.values())
        ),
    }


def end_date_sensitivity(first: str, last: pd.Timestamp) -> list[dict]:
    """Roll the common end date monthly and re-estimate the headline aggregates.

    The three named variants differ by only a few months of terminal date, yet the
    9-stock average gamma moves by ~40%. That has to be characterised rather than
    hidden behind whichever end date we happen to pick: either the rolling
    estimates are regime-sensitive, or they are simply imprecise. This sweep plus
    the implied standard errors settles which.
    """
    ends = sorted({*pd.date_range(first, last, freq="ME"), last})  # dedupe if last is a month end
    rows = []
    for end in ends:
        v = run_variant(end)  # raises if the rows are not calendar-aligned at this cutoff
        a = v["averages_and_ratio"]
        twii = v["index_rows"]["TWII"]
        etf = v["etf_0056"]
        t = twii["gamma_t"]
        rows.append(
            {
                "common_end": str(end.date()),
                # carried so the alignment invariant is auditable for the sweep too,
                # not just for the three named variants
                "window_end_all_rows": v["window_end_all_rows"],
                "gamma_mean_9stock": a["gamma_mean_9stock"],
                "gamma_mean_10security": a["gamma_mean_10security_incl_0056"],
                "twii_gamma": twii["gamma"],
                "twii_gamma_t": t,
                "twii_gamma_se": (abs(twii["gamma"] / t) if t else float("nan")),
                "gamma_0056": etf["gamma"],
                "gamma_0056_t": etf["gamma_t"],
                "gamma_0056_rank_of_12": v["gamma_0056_rank_of_12"],
                "amplification_ratio_9stock": a["amplification_ratio_9stock"],
            }
        )
        print(
            f"  [sens] end={end.date()}  g9={a['gamma_mean_9stock']:.4f}  "
            f"TWII={twii['gamma']:.4f} (t={twii['gamma_t']:.2f})  "
            f"0056={etf['gamma']:.4f} (rank {v['gamma_0056_rank_of_12']})  "
            f"ratio={a['amplification_ratio_9stock']:.2f}x"
        )
    return rows


def event_attribution(sens_rows: list[dict]) -> dict:
    """Which observations actually drive the end-date sensitivity.

    Pure data description (no estimation): the segments that enter and leave the
    2000-day window as the terminal date moves, and the extreme TWII returns they
    contain. This turns "the estimates move around" into a statement about WHICH
    days move them.
    """
    tw = pd.read_csv(os.path.join(DATA, "twii.csv"), parse_dates=["date"]).set_index("date")[
        "adj_close"
    ]
    r = np.log(tw / tw.shift(1)).dropna()

    def worst(a: str, b: str, k: int = 3) -> list[str]:
        seg = r[a:b]
        return [f"{d.date()}: {v * 100:.2f}%" for d, v in seg.nsmallest(k).items()]

    def seg_stats(a: str, b: str) -> dict:
        seg = r[a:b]
        return {
            "n": int(len(seg)),
            "std_pct": float(seg.std() * 100),
            "skew": float(seg.skew()),
            "worst_days": worst(a, b),
        }

    # Read the swept aggregates rather than hardcoding them: these numbers live inside a
    # results JSON and would silently go stale on the next data pull.
    by_end = {r["common_end"]: r for r in sens_rows}

    def g9_at(d: str) -> float | None:
        r = by_end.get(d)
        return None if r is None else float(r["gamma_mean_9stock"])

    g9_mar25, g9_apr25 = g9_at("2025-03-31"), g9_at("2025-04-30")
    g9_mar26 = g9_at("2026-03-31")
    g9_last = float(sens_rows[-1]["gamma_mean_9stock"])
    last_end = sens_rows[-1]["common_end"]

    def fmt(x: float | None) -> str:
        return "n/a" if x is None else f"{x:.3f}"

    return {
        "caveat_on_causal_language": (
            "The month-to-month contrasts below compare two windows that differ at BOTH ends "
            "(observations enter at the back AND leave at the front), so on their own they cannot "
            "attribute a move to the entering segment. The clean, identified test holds one window "
            "fixed and ABLATES the candidate sessions from inside it -- that is run in inference.py "
            "(.b_event_ablation), and it is what these attributions rest on. Read the segment "
            "statistics here as description; read the ablation for the causal claim."
        ),
        "entered_2025_04_tariff_shock": {
            **seg_stats("2025-04-01", "2025-04-30"),
            "effect": (
                "Enters the window between the 2025-03-31 and 2025-04-30 end dates, across which "
                f"the 9-stock mean gamma moves {fmt(g9_mar25)} -> {fmt(g9_apr25)} (it roughly "
                "doubles). The segment contains a -10.20% limit-down TAIEX session (2025-04-07) "
                "plus -5.96% and -4.10% follow-through -- the largest cluster of negative shocks "
                "in the sample. Ablation-identified in inference.py."
            ),
        },
        "left_2018_q1_vol_spike": {
            **seg_stats("2018-01-16", "2018-04-18"),
            "effect": (
                "Leaves the window as the end date moves 2026-04-17 -> 2026-07-09 (the window "
                "start slides 2018-01-16 -> 2018-04-19). It contains 2018-02-06 (-5.08%, the "
                "'VIXmageddon' session). Dropping a large negative shock lowers gamma."
            ),
        },
        "entered_2026_q2": {
            **seg_stats("2026-04-01", "2026-07-09"),
            "effect": (
                "High volatility but roughly SYMMETRIC (skew ~0; the largest moves include "
                "+4.51%, +4.47%, +4.47% sessions alongside the drawdowns). Volatility that is NOT "
                "driven by negative shocks DILUTES the measured asymmetry. Together with the 2018 "
                "spike leaving, this is the decay in the 9-stock mean gamma from "
                f"{fmt(g9_mar26)} (2026-03) to {g9_last:.3f} ({last_end})."
            ),
        },
        "conclusion": (
            "The rolling-w2000 last-window gamma is an event-driven statistic, not a stable "
            "structural parameter: it is dominated by a handful of extreme sessions moving in and "
            "out of an 8-year window whose boundaries are set by the arbitrary date of the data "
            "pull. Note this conclusion is INCOMPATIBLE with reading the end-date movement as mere "
            "sampling noise -- noise is not attributable to nameable sessions. The formal test is "
            "in inference.py (.c_constant_gamma_null). Practical consequence: keep the FULL-SAMPLE "
            "Bollerslev-Wooldridge spec as the paper's primary evidence (as body_v3.tex already "
            "does), and never report a rolling point estimate as a structural quantity."
        ),
    }


def plot_sensitivity(rows: list[dict], path: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x = [pd.Timestamp(r["common_end"]) for r in rows]
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True)

    ax = axes[0]
    tw = np.array([r["twii_gamma"] for r in rows])
    se = np.array([r["twii_gamma_se"] for r in rows], dtype=float)
    ax.plot(x, tw, "o-", color="#1f4e79", label="TWII (index)")
    ax.fill_between(x, tw - se, tw + se, color="#1f4e79", alpha=0.15, label="TWII ±1 SE")
    ax.plot(x, [r["gamma_0056"] for r in rows], "s-", color="#c0504d", label="0056.TW (ETF)")
    ax.plot(x, [r["gamma_mean_9stock"] for r in rows], "^-", color="#4f6228",
            label="9-stock average")
    ax.axhline(0.272, ls="--", lw=1, color="grey")
    ax.annotate(
        "body_v3 rendered TWII 0.272 (N121, untraceable)",
        xy=(x[-1], 0.272), xytext=(-6, 6), textcoords="offset points",
        ha="right", fontsize=8, color="grey",
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85),
    )
    ax.set_ylabel(r"GJR $\gamma$  (rolling $w=2000$, last window)")
    ax.set_title(
        "Table 2 rolling block: sensitivity of the leverage parameter to the common end date\n"
        "0056.TW sits ABOVE the index and every individual stock at every end date",
        fontsize=11,
    )
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)

    ax = axes[1]
    ax.plot(x, [r["amplification_ratio_9stock"] for r in rows], "o-", color="#7030a0")
    ax.axhline(5.0, ls="--", lw=1, color="grey")
    ax.annotate(
        "body_v3 rendered ratio 5.0x (N121, untraceable)",
        xy=(x[len(x) // 2], 5.0), xytext=(0, 6), textcoords="offset points",
        ha="center", fontsize=8, color="grey",
        bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85),
    )
    ax.set_ylabel("Amplification ratio\n(TWII γ / 9-stock mean γ)")
    ax.set_xlabel("Common end date of the rolling window")
    ax.grid(alpha=0.3)

    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    with open(os.path.join(DATA, "MANIFEST.json")) as f:
        manifest = json.load(f)
    common_end = pd.Timestamp(manifest["common_end_all_series"])
    VARIANTS["primary_2026"] = str(common_end.date())

    variants = {}
    for key, end in VARIANTS.items():
        end_ts = pd.Timestamp(end)
        variants[key] = run_variant(end_ts)
        a = variants[key]["averages_and_ratio"]
        print(
            f"[{key:20s}] end={end_ts.date()}  g9={a['gamma_mean_9stock']:.4f}  "
            f"g10={a['gamma_mean_10security_incl_0056']:.4f}  "
            f"TWII={a['twii_rolling_gamma']:.4f}  ratio9={a['amplification_ratio_9stock']:.2f}x  "
            f"0056={variants[key]['etf_0056']['gamma']:.4f} (rank {variants[key]['gamma_0056_rank_of_12']}/12)"
        )

    primary = variants["primary_2026"]

    # 2317 data-quality sensitivity, on the primary window.
    sens = run_variant(common_end, drop_corrupt_2317=True)
    s_2317 = sens["per_stock"]["2317.TW"]
    p_2317 = primary["per_stock"]["2317.TW"]
    sensitivity_2317 = {
        "what": (
            "Excludes the corrupted 2018-10-18..2018-10-26 block in yfinance's 2317.TW "
            "series (six frozen closes around the 0.8 capital-reduction factor, then a "
            "-10.49% catch-up move that exceeds Taiwan's +/-10% daily limit and therefore "
            "cannot be a real close-to-close return)."
        ),
        "primary_2317_gamma": p_2317["gamma"],
        "primary_2317_gamma_t": p_2317["gamma_t"],
        "excl_2317_gamma": s_2317["gamma"],
        "excl_2317_gamma_t": s_2317["gamma_t"],
        "gamma_shift": s_2317["gamma"] - p_2317["gamma"],
        "primary_gamma_mean_9stock": primary["averages_and_ratio"]["gamma_mean_9stock"],
        "excl_gamma_mean_9stock": sens["averages_and_ratio"]["gamma_mean_9stock"],
        "primary_ratio_9stock": primary["averages_and_ratio"]["amplification_ratio_9stock"],
        "excl_ratio_9stock": sens["averages_and_ratio"]["amplification_ratio_9stock"],
    }
    print(
        f"\n[2317 data-quality sens] gamma {p_2317['gamma']:.4f} -> {s_2317['gamma']:.4f}  "
        f"| 9-stock avg {sensitivity_2317['primary_gamma_mean_9stock']:.4f} -> "
        f"{sensitivity_2317['excl_gamma_mean_9stock']:.4f}  "
        f"| ratio {sensitivity_2317['primary_ratio_9stock']:.2f}x -> "
        f"{sensitivity_2317['excl_ratio_9stock']:.2f}x"
    )

    # End-date sensitivity sweep (monthly), + figure.
    print("\nend-date sensitivity sweep:")
    sens_rows = end_date_sensitivity("2025-01-31", common_end)
    fig_path = os.path.join(HERE, "end_date_sensitivity.png")
    plot_sensitivity(sens_rows, fig_path)
    g9s = [r["gamma_mean_9stock"] for r in sens_rows]
    tws = [r["twii_gamma"] for r in sens_rows]
    ratios = [r["amplification_ratio_9stock"] for r in sens_rows]
    se_med = float(np.nanmedian([r["twii_gamma_se"] for r in sens_rows]))
    ratio_factor = max(ratios) / min(ratios)
    sensitivity_block = {
        "rows": sens_rows,
        "figure": "end_date_sensitivity.png",
        "range_gamma_mean_9stock": [float(min(g9s)), float(max(g9s))],
        "range_twii_gamma": [float(min(tws)), float(max(tws))],
        "range_amplification_ratio_9stock": [float(min(ratios)), float(max(ratios))],
        "amplification_ratio_spread_factor": float(ratio_factor),
        "twii_gamma_median_implied_se": se_med,
        "gamma_0056_always_rank_1": all(r["gamma_0056_rank_of_12"] == 1 for r in sens_rows),
        "what_this_sweep_is_NOT": (
            "NOT a sampling distribution, and NOT to be compared against a marginal standard error. "
            "Adjacent end dates share ~99% of their observations (the extremes ~85%), so under a "
            "constant-parameter null the sampling errors are strongly POSITIVELY correlated: "
            "SD(g1 - g2) ~= sigma*sqrt(2*(1-rho)), which at rho=0.99 is about a SEVENTH of sigma. "
            "Scoring the observed movement against sigma therefore UNDERSTATES it several-fold -- the "
            "overlap does not blur the comparison, it REVERSES it. An earlier draft concluded 'the "
            "spread is about one SE wide, so these estimates are imprecise rather than regime-unstable'. "
            "That is WITHDRAWN: it was not merely un-rigorous, it pointed the wrong way. The correct "
            "null is computed in inference.py (constant-gamma parametric bootstrap) -- see "
            "inference_results.json .c_constant_gamma_null."
        ),
        "interpretation": (
            f"Across every monthly end date from 2025-01 to {common_end.date()}, the TWII rolling gamma "
            f"spans [{min(tws):.3f}, {max(tws):.3f}], the 9-stock mean gamma spans "
            f"[{min(g9s):.3f}, {max(g9s):.3f}], and the amplification ratio spans "
            f"[{min(ratios):.2f}x, {max(ratios):.2f}x] -- a factor of {ratio_factor:.2f}, i.e. the "
            "ratio's FIRST significant digit is not identified. That the paper's rendered 5.0x 'sits "
            "inside' this interval is not validation: so would almost any number one might have written "
            "down. Do not report a point ratio. What the sweep establishes: the reported number is "
            "materially determined by an arbitrary choice -- the date of the data pull -- and the "
            "movement is traceable to a handful of extreme sessions (see event_attribution), i.e. it is "
            "larger than, and different in kind from, sampling noise (formally tested in inference.py). "
            "This design cannot separate genuine time-variation in gamma from the GJR MLE's "
            "finite-sample sensitivity to a few influential shocks; both imply the same policy. 0056.TW "
            "ranks first of twelve at EVERY end date -- that ORDERING, unlike the levels, is robust."
        ),
    }

    pa = primary["averages_and_ratio"]
    result = {
        "experiment_id": "paper2_taiwan_indiv_rolling_gamma",
        "title": (
            "Calendar-aligned rolling-w2000 GJR gamma for Taiwan-VT Table 2 "
            "(refreshed snapshots; common end 2026)"
        ),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Rebuild body_v3.tex tab:gamma's rolling block on snapshots that are BOTH "
            "calendar-aligned AND current. Supersedes the 2026-07-07 run, whose common "
            "end (2025-01-22) was an artifact of two expired offline snapshots rather "
            "than a market fact, and whose 'RESOLVED' stamp on the Codex caveat was "
            "therefore false."
        ),
        "method": (
            "GJR-GARCH(1,1) MLE (arch pkg), Constant mean, Normal innovations, returns*100; "
            "rolling w=2000 last window ending on/before the variant's common end date; "
            "Bollerslev-Wooldridge robust t-values; persistence = alpha + 0.5*gamma + beta"
        ),
        "data": {
            "snapshot_dir": "data/",
            "manifest": "data/MANIFEST.json",
            "fetched_at_utc": manifest["fetched_at_utc"],
            "convention": manifest["convention"],
            "regression_check": (
                "Every refreshed series' log returns reproduce the previous canonical "
                "snapshots (paper CSV / k1302 / k1302b) to <1e-6 over the overlapping "
                "sample; see data/MANIFEST.json .series[*].regression_vs_old_snapshot. "
                "The refresh therefore moves the SAMPLE WINDOW, not the data convention."
            ),
            "sample_window_start": SAMPLE_START,
            "window": WINDOW,
        },
        "arch_version": arch.__version__,
        "seed": SEED,
        "codex_caveat_calendar_alignment": (
            "RESOLVED FOR REAL (2026-07-13). All 12 series share a common terminal date "
            f"of {common_end.date()}, the latest trading day on which every series has "
            "data (bound by ^TWII, which posts one session behind the single stocks). "
            "The prior 'RESOLVED (2026-07-07)' stamp was FALSE: it aligned the windows by "
            "truncating eight up-to-date securities back to 2025-01-22 to match two "
            "expired snapshots, so the paper claimed a 2026 sample while the table rows "
            "ended in 2025-01. Alignment is now achieved WITHOUT discarding a year of "
            "data: the snapshots were re-fetched once into data/ and the estimation runs "
            "fully offline from them."
        ),
        "primary_variant": "primary_2026",
        "headline": {
            "common_end": primary["common_end"],
            "gamma_mean_9stock": pa["gamma_mean_9stock"],
            "gamma_mean_10security_incl_0056": pa["gamma_mean_10security_incl_0056"],
            "twii_rolling_gamma": pa["twii_rolling_gamma"],
            "amplification_ratio_9stock": pa["amplification_ratio_9stock"],
            "amplification_ratio_10security": pa["amplification_ratio_10security"],
            "gamma_0056": primary["etf_0056"]["gamma"],
            "gamma_0056_t": primary["etf_0056"]["gamma_t"],
            "gamma_0056_rank_of_12": primary["gamma_0056_rank_of_12"],
        },
        "variants": variants,
        "end_date_sensitivity": sensitivity_block,
        "event_attribution": event_attribution(sens_rows),
        "fit_diagnostics": {
            **_FIT_DIAGNOSTICS,
            "covers": (
                "EVERY GJR fit in this run -- the 3 named variants, the 2317 ablation variant, and "
                "all rows of the end-date sweep. The honesty ledger's 'all converged, no restarts "
                "needed' is backed by these counters, not by a spot check on three variants."
            ),
            "all_converged": _FIT_DIAGNOSTICS["nonzero_convergence"] == 0,
            "no_restarts_needed": _FIT_DIAGNOSTICS["max_restarts"] == 0,
        },
        "inference": (
            "The point estimates here are descriptive. The INFERENCE that the paper needs -- the "
            "ordering sign test, the ablation-identified event attribution, the constant-gamma null "
            "for the end-date movement, and the block-bootstrap interval for the TWII-minus-stocks "
            "DIFFERENCE (the ratio is ill-posed: its denominator is not distinguishable from zero) "
            "-- is in inference.py / inference_results.json. Do not quote a point ratio from this "
            "file without reading that one."
        ),
        "narrative_implication_0056": {
            "paper_currently_argues": (
                "body_v3.tex section 3.2 ('Sensitivity to 0056.TW inclusion') rests on 0056 "
                "having the SECOND-highest gamma (rendered 0.112), so that including this "
                "diversified ETF in the stock average biases the amplification ratio DOWNWARD "
                "-- i.e. excluding it is the conservative choice."
            ),
            "what_the_data_says": (
                f"0056.TW's rolling gamma is {primary['etf_0056']['gamma']:.3f} "
                f"(t={primary['etf_0056']['gamma_t']:.2f}) on the primary window -- the HIGHEST "
                "of all twelve rows, above every individual stock AND above the TAIEX itself. "
                "It ranks first at every end date in the sensitivity sweep, so this is not an "
                "artifact of the window choice."
            ),
            "consequence": (
                "The 'conservative bias' argument inverts. Including 0056 RAISES the stock-side "
                f"average (9-stock {pa['gamma_mean_9stock']:.3f} -> 10-security "
                f"{pa['gamma_mean_10security_incl_0056']:.3f}) and therefore LOWERS the "
                f"amplification ratio ({pa['amplification_ratio_9stock']:.2f}x -> "
                f"{pa['amplification_ratio_10security']:.2f}x). Excluding 0056 is the choice that "
                "FLATTERS the headline ratio, not the one that guards against it. The section 3.2 "
                "narrative must be rewritten, and the exclusion must be justified on the stated "
                "grounds (0056 is an ETF, not an individual stock) rather than on a conservatism "
                "claim that the data contradicts."
            ),
            "why_0056_is_high_hypothesis": (
                "NOT verified here -- offered only as a direction for the main thread. 0056 is a "
                "high-dividend basket whose holdings tilt to value/financial names; a diversified "
                "basket's returns are dominated by the common factor, and the leverage effect is "
                "largely a factor-level phenomenon (which is the paper's own diversification-"
                "amplification thesis). On that reading a 0056 gamma above the single-stock "
                "average is CONSISTENT with the paper's mechanism, and 0056 belongs with the "
                "index-like rows rather than the stock cross-section. Testing that would need a "
                "decomposition the present experiment does not run."
            ),
        },
        "data_quality_sensitivity_2317": sensitivity_2317,
        "legacy_comparison": {
            "n121_rendered_in_body_v3": LEGACY_N121_AVG,
            "n121_per_row": LEGACY_N121,
            "prior_run_2026_07_07": PRIOR_RUN_20260707,
            "decomposition_note": (
                "legacy_2025_01_22 re-estimates the OLD window on the NEW data. Comparing "
                "it with prior_run_2026_07_07 isolates the effect of the data refresh "
                "(near-zero: the series reproduce to <1e-6, so any gap is optimizer noise); "
                "comparing it with primary_2026 isolates the effect of moving the window "
                "forward by ~18 months, which is where the real change lives."
            ),
        },
        "known_data_defects": {
            "2317_capital_reduction_block": sensitivity_2317["what"],
            "0050_split_2014_01_02": (
                "4:1 split leaves a spurious split-date return even under auto_adjust=False; "
                "excluded per body_v3.tex L33's canonical rule. Falls outside every window "
                "used here, so it does not affect these estimates."
            ),
            "paper_csv_duplicate_rows": (
                "paper/taiwan-vt/data/0050_tw_twii_..._2008-2026.csv carries 10 exactly-"
                "duplicated date rows (2026-05-04..2026-05-15). This experiment does not read "
                "that file for estimation, but any experiment that differences its twii/spy/vix "
                "columns without de-duplicating will inject spurious jump returns. Reported for "
                "the main thread; not edited here."
            ),
        },
        "lookahead_free_certification": (
            "gamma is an in-sample descriptive MLE on the last 2000-observation window. There "
            "is no forecast, no OOS split, no train/test boundary and no signal construction, "
            "so no lookahead channel exists. The MLE is deterministic; the seeded RNG is used "
            "only for perturbed restarts on non-convergence (SEED=20260713), and no restart "
            "was needed in this run."
        ),
        "provenance_note": (
            "body_v3.tex's tab:gamma note labels the rolling-window t-statistics 'Newey-West "
            "HAC'. That label is incorrect for a GARCH MLE and does not describe what is "
            "computed here (or in K892): these are Bollerslev-Wooldridge robust sandwich MLE "
            "t-values. The table note should be corrected. Reported t-values are BW-robust."
        ),
    }
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()
