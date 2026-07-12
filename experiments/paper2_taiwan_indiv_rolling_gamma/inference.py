"""
inference.py -- the inference the rolling block actually needs.

WHY THIS EXISTS
---------------
The point estimates in paper2_taiwan_indiv_rolling_gamma.py are sound. The
CONCLUSIONS drawn from them were not, and an independent review (review_notes.md)
identified two ship-blockers. This script settles both with computation instead of
prose.

BLOCKER 1 -- the amplification ratio is statistically ill-posed.
  The ratio is gamma_TWII / mean(gamma_9stock). Not one of the nine stock gammas is
  significant (max |t| = 1.56; 2412's is negative), and the numerator itself carries
  t = 1.86. When the denominator's confidence interval covers zero, the Fieller
  confidence set for the ratio is UNBOUNDED. Reporting "6.12x" as a point estimate,
  with the end-date sweep passed off as its uncertainty, is indefensible in a journal
  table. Fixes computed here:
    (a) the DIFFERENCE  D = gamma_TWII - mean(gamma_9stock), which is well behaved
        regardless of a near-zero denominator, with a moving-block bootstrap interval
        that respects the cross-sectional dependence among nine stocks trading the
        same sessions (a naive sqrt(sum var_i)/9 does not);
    (b) the bootstrap distribution of the RATIO itself, to show what it does; and
    (c) a sign / Wilcoxon test on the nine (index - stock) gaps -- assumption-light,
        and the statement the paper actually wants to make.

BLOCKER 2 -- "the estimates are imprecise, not regime-unstable" is backwards.
  Consecutive end dates share ~99% of their observations. Under a constant-parameter
  null the sampling errors of two overlapping estimates are strongly POSITIVELY
  correlated: SD(g1 - g2) ~= sigma * sqrt(2(1 - rho)), which for rho = 0.99 is about
  a SEVENTH of sigma. Scoring the observed movement against the marginal SE therefore
  UNDERSTATES it by that factor -- the overlap does not blur the inference, it
  reverses it. Settled here by a parametric bootstrap under the constant-gamma null:
  simulate GJR paths with gamma FIXED, run the identical rolling sweep on each, and
  ask how often the sweep's max-min range is as large as the one observed. This
  handles the overlap dependence AND the max-min multiplicity exactly, with no
  asymptotic hand-waving.

Also settles an attribution the main script asserted but did not identify: whether
the 2025-04 tariff cluster and the 2018-02-06 session actually MOVE gamma, tested by
ablating them from a fixed window rather than by comparing two windows that differ
at both ends.

All bootstraps are seeded. Offline: reads only data/.
"""
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from arch import arch_model
from arch.univariate import ConstantMean, GARCH, Normal
from scipy import stats

from volpred.ops.diagnostics import warn

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "inference_results.json")

WINDOW = 2000
SAMPLE_START = "2008-01-01"
SEED = 20260713
B_BLOCK = 999          # moving-block bootstrap replications
B_NULL = 999           # constant-gamma parametric bootstrap replications
BLOCK_LEN = 252        # ~1 trading year; long enough to keep volatility clustering

NINE_STOCKS = {
    "2317.TW": "2317_tw", "2454.TW": "2454_tw", "2383.TW": "2383_tw",
    "2886.TW": "2886_tw", "2412.TW": "2412_tw", "2881.TW": "2881_tw",
    "2882.TW": "2882_tw", "2885.TW": "2885_tw", "2891.TW": "2891_tw",
}
TWII = "twii"

# The two attributions the main script asserted from a two-ended window comparison.
TARIFF_CLUSTER = ("2025-04-07", "2025-04-09")   # -10.20% limit-down + follow-through
VIXMAGEDDON = ("2018-02-06", "2018-02-06")      # -5.08%; inside the 2026-04-17 window only


def load_returns(base: str) -> pd.Series:
    s = pd.read_csv(os.path.join(DATA, f"{base}.csv"), parse_dates=["date"]).set_index(
        "date"
    )["adj_close"]
    s = s.dropna().astype(float).sort_index()
    r = np.log(s / s.shift(1)).dropna()
    return r[r.index >= pd.Timestamp(SAMPLE_START)]


def fit_gamma(r: pd.Series | np.ndarray) -> float | None:
    """GJR gamma on a return series (already in decimal units). None on failure."""
    x = np.asarray(r, dtype=float) * 100.0
    try:
        res = arch_model(
            x, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant"
        ).fit(disp="off", options={"maxiter": 5000})
    except Exception as exc:
        warn("rolling-gamma-inference", f"GJR fit raised {type(exc).__name__}: {exc}")
        return None
    if res.convergence_flag != 0:
        return None
    return float(res.params.get("gamma[1]", np.nan))


def window_ending(r: pd.Series, end: pd.Timestamp) -> pd.Series:
    w = r[r.index <= end]
    return w.iloc[-WINDOW:]


# --------------------------------------------------------------------------
# A. Sign / Wilcoxon on the nine (index - stock) gaps
# --------------------------------------------------------------------------
def part_a(gap: dict) -> dict:
    gaps = np.array(list(gap.values()))
    n_pos = int((gaps > 0).sum())
    # one-sided sign test: P(all nine gaps positive | median gap = 0)
    sign_p = float(stats.binomtest(n_pos, len(gaps), 0.5, alternative="greater").pvalue)
    w = stats.wilcoxon(gaps, alternative="greater", zero_method="wilcox")
    return {
        "test": "index gamma exceeds each individual stock's gamma",
        "gaps_index_minus_stock": {k: float(v) for k, v in gap.items()},
        "n_positive": n_pos,
        "n_stocks": len(gaps),
        "sign_test_p_one_sided": sign_p,
        "wilcoxon_stat": float(w.statistic),
        "wilcoxon_p_one_sided": float(w.pvalue),
        "caveat": (
            "Treats the nine stock gamma POINT ESTIMATES as the sample. It therefore "
            "ignores (i) each estimate's own sampling error and (ii) the cross-sectional "
            "dependence among nine stocks trading the same sessions, which makes the "
            "effective sample size smaller than nine. It is a test of the ORDERING claim "
            "('the index gamma sits above the cross-section'), which is what the paper "
            "actually wants to assert, and it is assumption-light -- but it is not a test "
            "of the ratio's magnitude. Read it alongside the block bootstrap in part D."
        ),
    }


# --------------------------------------------------------------------------
# B. Event ablation -- identify the drivers instead of asserting them
# --------------------------------------------------------------------------
def ablate(r: pd.Series, end: pd.Timestamp, lo: str, hi: str) -> tuple[float | None, int]:
    """Gamma on the window ending `end`, with [lo, hi] removed AFTER the window is cut.

    Cutting first and ablating inside keeps the calendar span fixed, so the only thing
    that changes is the ablated sessions. (Dropping them from the series first would
    make the slice reach further back and import fresh observations -- confounding the
    ablation with a window-start shift.)
    """
    w = window_ending(r, end)
    lo_ts, hi_ts = pd.Timestamp(lo), pd.Timestamp(hi)
    kept = w[(w.index < lo_ts) | (w.index > hi_ts)]
    return fit_gamma(kept), int(len(w) - len(kept))


def part_b(rets: dict[str, pd.Series], primary_end: pd.Timestamp) -> dict:
    out: dict = {}

    # B1: the 2025-04 tariff cluster, on the PRIMARY window (it is inside it).
    g_full = fit_gamma(window_ending(rets[TWII], primary_end))
    g_abl, n_abl = ablate(rets[TWII], primary_end, *TARIFF_CLUSTER)
    stock_full, stock_abl = [], []
    for tk, base in NINE_STOCKS.items():
        stock_full.append(fit_gamma(window_ending(rets[tk], primary_end)))
        a, _ = ablate(rets[tk], primary_end, *TARIFF_CLUSTER)
        stock_abl.append(a)
    sf = [g for g in stock_full if g is not None]
    sa = [g for g in stock_abl if g is not None]
    out["tariff_cluster_2025_04"] = {
        "ablated_range": list(TARIFF_CLUSTER),
        "sessions_removed": n_abl,
        "window_end": str(primary_end.date()),
        "twii_gamma_with": g_full,
        "twii_gamma_without": g_abl,
        "twii_delta": (g_abl - g_full) if (g_abl is not None and g_full is not None) else None,
        "gamma_mean_9stock_with": float(np.mean(sf)),
        "gamma_mean_9stock_without": float(np.mean(sa)),
        "gamma_mean_9stock_delta": float(np.mean(sa) - np.mean(sf)),
        "reads_as": (
            "Removing three sessions from a 2000-session window and watching gamma move "
            "is a DIRECT measure of their influence -- unlike comparing two windows that "
            "differ at both ends, which cannot attribute the change to the entering days."
        ),
    }

    # B2: 2018-02-06, on the 2026-04-17 window (the only one containing it).
    end_0417 = pd.Timestamp("2026-04-17")
    g2_full = fit_gamma(window_ending(rets[TWII], end_0417))
    g2_abl, n2 = ablate(rets[TWII], end_0417, *VIXMAGEDDON)
    in_primary = bool(
        (window_ending(rets[TWII], primary_end).index == pd.Timestamp(VIXMAGEDDON[0])).any()
    )
    out["vixmageddon_2018_02_06"] = {
        "ablated_range": list(VIXMAGEDDON),
        "sessions_removed": n2,
        "window_end": str(end_0417.date()),
        "note": (
            "Tested on the 2026-04-17 window because that is the one whose span contains "
            "2018-02-06. It is OUTSIDE the primary (2026-07-09) window -- which is exactly "
            "the mechanism claimed: the session drops out as the end date advances."
        ),
        "present_in_primary_window": in_primary,
        "twii_gamma_with": g2_full,
        "twii_gamma_without": g2_abl,
        "twii_delta": (g2_abl - g2_full) if (g2_abl is not None and g2_full is not None) else None,
    }
    return out


# --------------------------------------------------------------------------
# C. Constant-gamma null: is the sweep's movement bigger than sampling noise?
# --------------------------------------------------------------------------
def part_c(r_twii: pd.Series, end_dates: list[pd.Timestamp], observed_range: float) -> dict:
    """Parametric bootstrap under a CONSTANT-gamma DGP.

    Fit GJR on the full TWII sample -> theta_hat. Simulate paths from it (gamma is
    constant by construction), run the IDENTICAL rolling sweep on each, and record the
    max-min range of the swept gammas. The null distribution of that range answers the
    question the marginal standard error cannot: how much can this sweep wander when
    the true parameter never moves? Handles both the ~99% window overlap and the
    max-min selection exactly.
    """
    full = arch_model(
        r_twii * 100.0, vol="GARCH", p=1, o=1, q=1, dist="normal", mean="Constant"
    ).fit(disp="off", options={"maxiter": 5000})
    theta = full.params
    if full.convergence_flag != 0:
        raise RuntimeError("full-sample TWII GJR did not converge; cannot build the null")

    # Positions of each sweep window inside the real series, reused on simulated paths.
    pos_end = []
    for d in end_dates:
        sub = r_twii[r_twii.index <= d]
        pos_end.append(len(sub))          # window = returns[pos-WINDOW : pos]
    first_start = min(p - WINDOW for p in pos_end)
    last_end = max(pos_end)
    span = last_end - first_start
    rel_end = [p - first_start for p in pos_end]

    sim_model = ConstantMean(None)
    sim_model.volatility = GARCH(p=1, o=1, q=1)
    sim_model.distribution = Normal(seed=np.random.default_rng(SEED))
    params = np.array(
        [theta["mu"], theta["omega"], theta["alpha[1]"], theta["gamma[1]"], theta["beta[1]"]]
    )

    ranges, failed = [], 0
    for b in range(B_NULL):
        sim = sim_model.simulate(params, nobs=span, burn=1000)["data"].to_numpy()
        gs = []
        for re_ in rel_end:
            g = fit_gamma(sim[re_ - WINDOW : re_] / 100.0)
            if g is not None:
                gs.append(g)
        if len(gs) < len(rel_end):
            failed += 1
            if len(gs) < 2:
                continue
        ranges.append(max(gs) - min(gs))
    if failed:
        warn(
            "rolling-gamma-inference",
            f"{failed}/{B_NULL} null replications had >=1 non-converged sweep fit "
            "(range computed from the converged subset)",
        )

    ranges_arr = np.array(ranges)
    p = float((1 + (ranges_arr >= observed_range).sum()) / (len(ranges_arr) + 1))
    return {
        "null_dgp": "GJR-GARCH(1,1) fitted to the FULL TWII sample; gamma constant by construction",
        "null_params": {k: float(v) for k, v in theta.items()},
        "B": B_NULL,
        "replications_used": int(len(ranges_arr)),
        "replications_with_a_failed_fit": failed,
        "sweep_end_dates": [str(d.date()) for d in end_dates],
        "observed_sweep_range_max_minus_min": float(observed_range),
        "null_range_mean": float(ranges_arr.mean()),
        "null_range_p50": float(np.percentile(ranges_arr, 50)),
        "null_range_p95": float(np.percentile(ranges_arr, 95)),
        "null_range_p99": float(np.percentile(ranges_arr, 99)),
        "p_value_one_sided": p,
        "reject_constant_gamma_at_5pct": bool(p < 0.05),
        "reads_as": (
            "p = P(sweep range >= observed | gamma truly constant). A small p means the "
            "movement across end dates is LARGER than a constant-parameter DGP produces, "
            "i.e. it is not sampling noise. It does NOT identify the cause: genuine "
            "time-variation in gamma and finite-sample sensitivity of the GJR MLE to a few "
            "influential negative returns both produce it. Both imply the same policy -- no "
            "single end date's rolling estimate is a structural quantity."
        ),
    }


# --------------------------------------------------------------------------
# D. Moving-block bootstrap of the difference (and what the ratio does)
# --------------------------------------------------------------------------
def part_d(rets: dict[str, pd.Series], primary_end: pd.Timestamp) -> dict:
    tickers = list(NINE_STOCKS) + [TWII]
    windows = {tk: window_ending(rets[tk], primary_end) for tk in tickers}
    common = windows[tickers[0]].index
    for tk in tickers[1:]:
        common = common.intersection(windows[tk].index)
    panel = pd.DataFrame({tk: rets[tk].reindex(common) for tk in tickers}).dropna()
    n = len(panel)

    rng = np.random.default_rng(SEED)
    n_blocks = int(np.ceil(n / BLOCK_LEN))
    max_start = n - BLOCK_LEN

    ds, ratios, means9, twiis, failed = [], [], [], [], 0
    for b in range(B_BLOCK):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + BLOCK_LEN) for s in starts])[:n]
        boot = panel.iloc[idx]
        g = {tk: fit_gamma(boot[tk].to_numpy()) for tk in tickers}
        if any(v is None for v in g.values()):
            failed += 1
            continue
        m9 = float(np.mean([g[tk] for tk in NINE_STOCKS]))
        ds.append(g[TWII] - m9)
        means9.append(m9)
        twiis.append(g[TWII])
        ratios.append(g[TWII] / m9 if m9 != 0 else np.nan)
    if failed:
        warn(
            "rolling-gamma-inference",
            f"{failed}/{B_BLOCK} block-bootstrap replications dropped (>=1 fit failed to converge)",
        )

    ds_a, m9_a = np.array(ds), np.array(means9)
    ratios_a = np.array(ratios, dtype=float)
    finite = ratios_a[np.isfinite(ratios_a)]
    denom_le_zero = int((m9_a <= 0).sum())

    return {
        "method": (
            f"Moving-block bootstrap, block length {BLOCK_LEN} sessions (~1 trading year), "
            f"B={B_BLOCK}. Date blocks are resampled ONCE and applied to all ten securities "
            "jointly, so the cross-sectional dependence among nine stocks trading the same "
            "sessions is preserved -- a naive sqrt(sum var_i)/9 assumes it away."
        ),
        "caveat": (
            "Block resampling breaks the GARCH volatility recursion at block boundaries, "
            "which attenuates measured persistence. A 252-session block leaves only ~8 "
            "boundaries in a 2000-session window, so the distortion is small, but this is an "
            "APPROXIMATE interval, not an exact one. The sign test (part A) is the "
            "assumption-light backstop for the ordering claim."
        ),
        "n_obs_common_panel": int(n),
        "B": B_BLOCK,
        "replications_used": int(len(ds_a)),
        "replications_dropped": failed,
        "difference_D_twii_minus_mean9": {
            "point": float(ds_a.mean()),
            "se": float(ds_a.std(ddof=1)),
            "ci95_percentile": [float(np.percentile(ds_a, 2.5)), float(np.percentile(ds_a, 97.5))],
            "p_D_le_zero": float((ds_a <= 0).mean()),
        },
        "denominator_mean9": {
            "point": float(m9_a.mean()),
            "se": float(m9_a.std(ddof=1)),
            "ci95_percentile": [float(np.percentile(m9_a, 2.5)), float(np.percentile(m9_a, 97.5))],
            "replications_with_denominator_le_zero": denom_le_zero,
            "fraction_le_zero": float(denom_le_zero / max(len(m9_a), 1)),
        },
        "ratio_twii_over_mean9": {
            "ci95_percentile": [
                float(np.percentile(finite, 2.5)),
                float(np.percentile(finite, 97.5)),
            ],
            "ci80_percentile": [
                float(np.percentile(finite, 10)),
                float(np.percentile(finite, 90)),
            ],
            "min": float(finite.min()),
            "max": float(finite.max()),
            "verdict": (
                "Reported to demonstrate that the ratio is NOT a usable statistic, not to be "
                "quoted. Its denominator is a mean of nine individually insignificant gammas "
                "and its bootstrap distribution is correspondingly wild. Whenever the "
                "denominator's interval covers zero the Fieller confidence set for the ratio "
                "is UNBOUNDED, and a percentile interval merely hides that. Report the "
                "DIFFERENCE, or the sign test on the ordering -- never a bare point ratio."
            ),
        },
    }


def main() -> None:
    rets = {tk: load_returns(base) for tk, base in NINE_STOCKS.items()}
    rets[TWII] = load_returns(TWII)

    with open(os.path.join(HERE, "paper2_taiwan_indiv_rolling_gamma_results.json")) as f:
        main_res = json.load(f)
    primary_end = pd.Timestamp(main_res["headline"]["common_end"])
    sweep = main_res["end_date_sensitivity"]["rows"]
    end_dates = [pd.Timestamp(r["common_end"]) for r in sweep]
    tw_sweep = [r["twii_gamma"] for r in sweep]
    observed_range = max(tw_sweep) - min(tw_sweep)

    prim = main_res["variants"]["primary_2026"]
    g_tw = prim["index_rows"]["TWII"]["gamma"]
    gap = {tk: g_tw - prim["per_stock"][tk]["gamma"] for tk in NINE_STOCKS}

    print("A. sign / Wilcoxon on the nine (index - stock) gaps ...")
    a = part_a(gap)
    print(f"   {a['n_positive']}/9 positive; sign p={a['sign_test_p_one_sided']:.4f}  "
          f"wilcoxon p={a['wilcoxon_p_one_sided']:.4f}")

    print("B. event ablation (identify the drivers, don't assert them) ...")
    b = part_b(rets, primary_end)
    t = b["tariff_cluster_2025_04"]
    v = b["vixmageddon_2018_02_06"]
    print(f"   tariff 2025-04-07..09 removed: TWII {t['twii_gamma_with']:.4f} -> "
          f"{t['twii_gamma_without']:.4f} (D={t['twii_delta']:+.4f}); "
          f"9-stock mean {t['gamma_mean_9stock_with']:.4f} -> {t['gamma_mean_9stock_without']:.4f} "
          f"(D={t['gamma_mean_9stock_delta']:+.4f})")
    print(f"   2018-02-06 removed (2026-04-17 window): TWII {v['twii_gamma_with']:.4f} -> "
          f"{v['twii_gamma_without']:.4f} (D={v['twii_delta']:+.4f})")

    print(f"C. constant-gamma null, B={B_NULL} (this is the one that settles 'noise or not') ...")
    c = part_c(rets[TWII], end_dates, observed_range)
    print(f"   observed sweep range={c['observed_sweep_range_max_minus_min']:.4f}  "
          f"null p95={c['null_range_p95']:.4f}  p={c['p_value_one_sided']:.4f}  "
          f"reject constant gamma: {c['reject_constant_gamma_at_5pct']}")

    print(f"D. moving-block bootstrap of the difference, B={B_BLOCK} ...")
    d = part_d(rets, primary_end)
    dd = d["difference_D_twii_minus_mean9"]
    dn = d["denominator_mean9"]
    rr = d["ratio_twii_over_mean9"]
    print(f"   D = {dd['point']:.4f}  95% CI [{dd['ci95_percentile'][0]:.4f}, "
          f"{dd['ci95_percentile'][1]:.4f}]  P(D<=0)={dd['p_D_le_zero']:.4f}")
    print(f"   denominator mean9 95% CI [{dn['ci95_percentile'][0]:.4f}, "
          f"{dn['ci95_percentile'][1]:.4f}]  covers zero: "
          f"{dn['ci95_percentile'][0] <= 0 <= dn['ci95_percentile'][1]}")
    print(f"   ratio 95% CI [{rr['ci95_percentile'][0]:.2f}x, {rr['ci95_percentile'][1]:.2f}x]  "
          f"(range {rr['min']:.1f}x .. {rr['max']:.1f}x) -- NOT a usable statistic")

    result = {
        "experiment_id": "paper2_taiwan_indiv_rolling_gamma",
        "component": "inference",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "purpose": (
            "Settle the two ship-blockers raised in review_notes.md: (1) the amplification "
            "ratio is ill-posed because its denominator is not distinguishable from zero; "
            "(2) the end-date movement was mis-diagnosed as sampling noise when the ~99% "
            "window overlap means the correct null SD is several times SMALLER than the "
            "marginal SE, not larger."
        ),
        "seed": SEED,
        "primary_window_end": str(primary_end.date()),
        "a_ordering_sign_test": a,
        "b_event_ablation": b,
        "c_constant_gamma_null": c,
        "d_block_bootstrap_difference": d,
        "lookahead_free_certification": (
            "All quantities are in-sample descriptive MLEs and resampling functionals of "
            "them. No forecast, no OOS split, no signal. Bootstraps are seeded (SEED above)."
        ),
    }
    with open(OUT, "w") as f:
        json.dump(result, f, indent=2)
    print(f"\nwritten: {OUT}")


if __name__ == "__main__":
    main()
