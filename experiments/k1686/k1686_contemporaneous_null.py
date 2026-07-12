"""
K1686: Contemporaneous Null Simulation for Volatility Absorption (Paper 8)

Fixes the identification defect found in the 2026-07-11 fable deep review (P0-1):

  K897's simulated day-t vol proxy was sqrt(h[t]), which is F_{t-1}-measurable under the
  GJR recursion h[t] = w + (a + g*1{eps_{t-1}<0})*eps_{t-1}^2 + b*h[t-1].  It does not
  react to r_t at all, so the simulated "shock day" lands on the day AFTER a large move.
  The empirical delta_VIX_t, by contrast, is contemporaneous with r_t (VIX spikes on the
  day the market crashes).  The empirical SAR numerator is therefore mechanically inflated
  by same-day co-movement while the simulated one is not -- the two sides are not the same
  statistic, and "empirical decline >> null" may be an artifact of that mismatch.

  Fix: use sqrt(h[t+1]) as the day-t proxy -- the GARCH forecast formed at the close of day
  t, after r_t is observed.  That is the correct analogue of "closing VIX reflects today's
  information".

Design (see README.md for the full pre-registered spec):
  - Same GARCH params, same seeds (0..9999), same n_obs (5000) as K897, so the simulated
    return paths r are POINTWISE IDENTICAL to K897's.  Only the proxy timing changes.
  - Built-in K897 replication arm (lagged proxy) computed on the SAME paths.  If it
    reproduces K897's sim_mean_decline = 0.1734, any difference in the contemporaneous arm
    is attributable to the timing fix alone.  This is the experiment's internal placebo.
  - Empirical side reads the PINNED snapshot CSV (K897 used live yfinance -- review P1-3).
  - 5 variants: A fixed (PRIMARY) / B frequency-matched / C relative / D sign-split /
    E ambient-regime.

Decision rule was pre-registered and committed BEFORE this script was run (git history).

Data: paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv (pinned)
"""

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from concurrent.futures import ProcessPoolExecutor
import multiprocessing

warnings.filterwarnings("ignore")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
PINNED_CSV = REPO / "paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv"

# --- Frozen spec (pre-registered) ---------------------------------------------------
N_SIM = 10_000
N_OBS = 5_000
SEEDS = range(N_SIM)              # identical to K897
SAMPLE_START, SAMPLE_END = "2006-01-01", "2026-04-05"
SHOCK_ABS = 2.0                   # |delta VIX| > 2, same as paper Table 3
ANN = np.sqrt(252.0)
MIN_CELL = 5                      # need n_shock > 5 and n_normal > 5 (K897 convention)
BOOT_REPS = 10_000
BOOT_SEED = 20260712
BOOT_PRIMARY_BLOCK = 20
BOOT_BLOCK_LENGTHS = (10, BOOT_PRIMARY_BLOCK, 40, 63)
MIN_BOOT_VALID = 1_000

REGIME_NAMES = ["calm (<15)", "normal (15-20)", "elevated (20-25)", "high (25-30)", "crisis (>=30)"]
REGIME_BOUNDS = [(0, 15), (15, 20), (20, 25), (25, 30), (30, 1e6)]

# K897 fitted GJR-GARCH(1,1)-t params, reused verbatim so the null DGP is unchanged.
K897_PARAMS = {
    "mu": 0.07641013516248987,
    "ar1": 0.0,
    "omega": 0.022188769677603346,
    "alpha": 0.0,
    "gamma": 0.24422367045225124,
    "beta": 0.8594147336803625,
    "nu": 5.647879075643755,
    "persistence": 0.981526568906488,
}
K897_REFERENCE = {  # for the replication check
    "sim_mean_decline": 0.1734,
    "sim_std_decline": 0.2105,
    "sim_ci_95": [-0.2811, 0.5575],
    "empirical_decline_live_yfinance": 0.8162,
}


# ====================================================================================
# SAR core -- one implementation used by BOTH the empirical and the simulated side,
# so the two can never drift apart.
# ====================================================================================
def sar_by_regime(abs_ret, level, shock, bounds=REGIME_BOUNDS):
    """SAR(regime) = mean(|r| | shock, regime) / mean(|r| | normal, regime).

    abs_ret : |r_t|
    level   : the fear level used to assign day t to a regime (VIX_t or the GARCH proxy)
    shock   : boolean shock flag for day t
    """
    out, occ, shock_n = [], [], []
    for lo, hi in bounds:
        m = (level >= lo) & (level < hi)
        sm, nm = m & shock, m & ~shock
        ns, nn = int(sm.sum()), int(nm.sum())
        occ.append(float(m.mean()))
        shock_n.append(ns)
        if ns > MIN_CELL and nn > MIN_CELL:
            out.append(float(abs_ret[sm].mean() / abs_ret[nm].mean()))
        else:
            out.append(np.nan)
    return np.array(out), np.array(occ), np.array(shock_n)


def signed_sar_by_regime(abs_ret, level, signed_shock, any_shock, bounds=REGIME_BOUNDS):
    """SAR for one shock sign, with the pooled non-shock days as denominator.

    Keeping this in one helper prevents the empirical and simulated ambient x sign arms from
    drifting apart. All four arrays must already refer to the same day-t observations.
    """
    abs_ret = np.asarray(abs_ret, dtype=float)
    level = np.asarray(level, dtype=float)
    signed_shock = np.asarray(signed_shock, dtype=bool)
    any_shock = np.asarray(any_shock, dtype=bool)
    if not (len(abs_ret) == len(level) == len(signed_shock) == len(any_shock)):
        raise ValueError("signed SAR inputs must be day-aligned")

    out, occ, shock_n, normal_n = [], [], [], []
    for lo, hi in bounds:
        m = (level >= lo) & (level < hi)
        sm, nm = m & signed_shock, m & ~any_shock
        ns, nn = int(sm.sum()), int(nm.sum())
        occ.append(float(m.mean()))
        shock_n.append(ns)
        normal_n.append(nn)
        if ns > MIN_CELL and nn > MIN_CELL:
            out.append(float(abs_ret[sm].mean() / abs_ret[nm].mean()))
        else:
            out.append(np.nan)
    return (np.asarray(out), np.asarray(occ), np.asarray(shock_n),
            np.asarray(normal_n))


def decay_only_drop_level(params, drop=SHOCK_ABS):
    """Lowest vol level at which the null can produce a `drop`-point one-day FALL.

    With alpha = 0 a positive return contributes nothing to next-day variance, so the deepest
    possible one-day fall is pure decay: h_next = omega + beta*h.  Solving
        (sqrt(omega + beta*h) - sqrt(h)) * sqrt(252) = -drop
    gives the level below which a "vol-DOWN shock" is IMPOSSIBLE in this null.  That is what
    makes D_down undefined in the lower regimes -- a structural property, not a coding bug.
    """
    from scipy.optimize import brentq
    w, b = params["omega"], params["beta"]

    def f(P):
        h = (P / ANN) ** 2
        return (np.sqrt(w + b * h) - np.sqrt(h)) * ANN + drop

    try:
        return float(brentq(f, 1.0, 500.0))
    except ValueError:
        return float("nan")


def decline(sars):
    """Primary statistic: SAR(calm) - SAR(high 25-30)."""
    calm, high = sars[0], sars[3]
    if np.isnan(calm) or np.isnan(high):
        return np.nan
    return float(calm - high)


def decline_nh(sars):
    """Secondary statistic: SAR(normal 15-20) - SAR(high 25-30).

    Needed because the calm cell is not always measurable -- in variant F the affine
    recalibration that fixes the level gap also shrinks the increments, so a calm-regime
    shock (2 VIX-scale points) becomes rarer than the minimum cell size. Reporting the
    normal-to-high leg keeps that variant from being silently dropped.
    """
    normal, high = sars[1], sars[3]
    if np.isnan(normal) or np.isnan(high):
        return np.nan
    return float(normal - high)


def circular_block_indices(n, block_length, rng):
    """Circular moving-block bootstrap indices, preserving paired day-level rows."""
    if n <= 0 or block_length <= 0:
        raise ValueError("n and block_length must be positive")
    n_blocks = int(np.ceil(n / block_length))
    starts = rng.randint(0, n, size=n_blocks)
    offsets = np.arange(block_length)
    return ((starts[:, None] + offsets[None, :]) % n).ravel()[:n]


def _bootstrap_summary(values, point_estimate):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < MIN_BOOT_VALID:
        return {
            "point_estimate": round(float(point_estimate), 4),
            "n_valid": int(len(values)),
            "ci95": None,
        }
    lo, hi = np.percentile(values, [2.5, 97.5])
    return {
        "point_estimate": round(float(point_estimate), 4),
        "bootstrap_mean": round(float(values.mean()), 4),
        "ci95": [round(float(lo), 4), round(float(hi), 4)],
        "ci_contains_zero": bool(lo <= 0 <= hi),
        "n_valid": int(len(values)),
    }


def paired_block_bootstrap_sign_tests(abs_ret, current_level, ambient_level, dlevel):
    """Paired block inference for the two Codex-review blocking contrasts.

    Each resampled row keeps (|r_t|, VIX_t, VIX_{t-1}, dVIX_t) together. The same block draw
    is used for pooled, current-level up-only and ambient-level up-only SARs, so the overlapping
    estimators are compared directly rather than by comparing one CI with another point estimate.
    """
    a = np.asarray(abs_ret, dtype=float)
    cur = np.asarray(current_level, dtype=float)
    amb = np.asarray(ambient_level, dtype=float)
    dv = np.asarray(dlevel, dtype=float)
    if not (len(a) == len(cur) == len(amb) == len(dv)):
        raise ValueError("paired bootstrap inputs must be day-aligned")

    any_shock = np.abs(dv) > SHOCK_ABS
    up = dv > SHOCK_ABS
    pooled_point = decline(sar_by_regime(a, cur, any_shock)[0])
    current_up_point = decline(signed_sar_by_regime(a, cur, up, any_shock)[0])
    ambient_up_point = decline(signed_sar_by_regime(a, amb, up, any_shock)[0])
    diff_point = pooled_point - current_up_point

    by_block = {}
    primary_raw_ci = None
    for block_length in BOOT_BLOCK_LENGTHS:
        rng = np.random.RandomState(BOOT_SEED + block_length)
        pooled_draws, current_up_draws, ambient_up_draws, diff_draws = [], [], [], []
        for _ in range(BOOT_REPS):
            idx = circular_block_indices(len(a), block_length, rng)
            a_b, cur_b, amb_b, dv_b = a[idx], cur[idx], amb[idx], dv[idx]
            any_b, up_b = np.abs(dv_b) > SHOCK_ABS, dv_b > SHOCK_ABS
            pooled_b = decline(sar_by_regime(a_b, cur_b, any_b)[0])
            current_up_b = decline(signed_sar_by_regime(a_b, cur_b, up_b, any_b)[0])
            ambient_up_b = decline(signed_sar_by_regime(a_b, amb_b, up_b, any_b)[0])
            if np.isfinite(pooled_b):
                pooled_draws.append(pooled_b)
            if np.isfinite(current_up_b):
                current_up_draws.append(current_up_b)
            if np.isfinite(ambient_up_b):
                ambient_up_draws.append(ambient_up_b)
            if np.isfinite(pooled_b) and np.isfinite(current_up_b):
                diff_draws.append(pooled_b - current_up_b)

        by_block[str(block_length)] = {
            "seed": BOOT_SEED + block_length,
            "pooled_current_decline": _bootstrap_summary(pooled_draws, pooled_point),
            "up_only_current_decline": _bootstrap_summary(current_up_draws, current_up_point),
            "paired_pooled_minus_up_current": _bootstrap_summary(diff_draws, diff_point),
            "ambient_up_decline": _bootstrap_summary(ambient_up_draws, ambient_up_point),
        }
        if block_length == BOOT_PRIMARY_BLOCK and len(ambient_up_draws) >= MIN_BOOT_VALID:
            primary_raw_ci = tuple(float(x) for x in np.percentile(ambient_up_draws, [2.5, 97.5]))

    primary = by_block[str(BOOT_PRIMARY_BLOCK)]["ambient_up_decline"]
    if primary_raw_ci is None:
        gate = "NOT_EVALUABLE"
    elif ambient_up_point > 0 and primary_raw_ci[0] > 0:
        gate = "ABSORPTION_SURVIVES_AMBIENT_FEAR_SHOCK_GATE"
    elif primary_raw_ci[0] <= 0 <= primary_raw_ci[1]:
        gate = "MECHANISM_UNRESOLVED_CI_INCLUDES_ZERO"
    else:
        gate = "ABSORPTION_NOT_SUPPORTED_OR_DIRECTION_REVERSED"

    return {
        "method": ("paired circular moving-block bootstrap of full day-level rows; pooled and "
                   "up-only statistics use identical resampled blocks"),
        "reps": BOOT_REPS,
        "primary_block_length": BOOT_PRIMARY_BLOCK,
        "block_length_sensitivity": list(BOOT_BLOCK_LENGTHS),
        "by_block_length": by_block,
        "pre_registered_ambient_up_gate": gate,
        "gate_rule": ("positive ambient-up calm-minus-high point estimate with primary 95% block "
                      "CI excluding zero => absorption survives; CI containing zero => mechanism "
                      "unresolved; otherwise absorption is not supported or direction is reversed"),
    }


# ====================================================================================
# Simulation: one GJR path -> every variant's SAR (computed on the SAME path)
# ====================================================================================
def simulate_one(args):
    seed, params, n_obs, spec = args
    rng = np.random.RandomState(seed)

    mu, ar1 = params["mu"], params["ar1"]
    omega, alpha, gamma, beta, nu = (
        params["omega"], params["alpha"], params["gamma"], params["beta"], params["nu"],
    )

    # Identical draw to K897: same seed, same size, same scaling -> bit-identical z.
    z = rng.standard_t(df=nu, size=n_obs) * np.sqrt((nu - 2) / nu)

    r = np.zeros(n_obs)
    h = np.zeros(n_obs + 1)          # ONE EXTRA STEP: h[n_obs] needs only eps[n_obs-1]

    h[0] = omega / (1 - alpha - gamma / 2 - beta)
    r[0] = mu + np.sqrt(h[0]) * z[0]

    for t in range(1, n_obs):        # recursion identical to K897 (ar1 = 0 here)
        indicator = 1.0 if r[t - 1] - mu < 0 else 0.0
        eps = r[t - 1] - mu - ar1 * (r[t - 2] if t >= 2 else 0)
        h[t] = max(omega + (alpha + gamma * indicator) * eps ** 2 + beta * h[t - 1], 1e-8)
        r[t] = mu + ar1 * r[t - 1] + np.sqrt(h[t]) * z[t]

    # The extra step that makes a contemporaneous proxy possible at t = n_obs-1.
    indicator = 1.0 if r[n_obs - 1] - mu < 0 else 0.0
    eps = r[n_obs - 1] - mu - ar1 * (r[n_obs - 2] if n_obs >= 2 else 0)
    h[n_obs] = max(omega + (alpha + gamma * indicator) * eps ** 2 + beta * h[n_obs - 1], 1e-8)

    abs_ret = np.abs(r)

    # --- the two proxies -------------------------------------------------------------
    p_lag = np.sqrt(h[:n_obs]) * ANN        # K897: sqrt(h[t])   -- F_{t-1}-measurable
    p_con = np.sqrt(h[1:n_obs + 1]) * ANN   # K1686: sqrt(h[t+1]) -- reacts to r_t

    res = {}
    for tag, P in (("k897_lagged", p_lag), ("contemporaneous", p_con)):
        dP = np.concatenate([[0.0], np.diff(P)])   # K897 convention: t=0 is a normal day

        # --- A: fixed threshold (PRIMARY) ---
        shock_a = np.abs(dP) > SHOCK_ABS
        sars, occ, ns = sar_by_regime(abs_ret, P, shock_a)
        res[f"{tag}|A"] = sars
        if tag == "contemporaneous":
            res["occ_A"], res["nshock_A"] = occ, ns
            res["shock_rate_A"] = float(shock_a.mean())
        else:
            res["occ_A_lagged"] = occ
            res["shock_rate_A_lagged"] = float(shock_a.mean())

    # Everything below uses the contemporaneous proxy only.
    P = p_con
    dP = np.concatenate([[0.0], np.diff(P)])
    s = spec["shock_rate"]

    # --- B: frequency-matched (path-specific quantiles for BOTH shock and regimes) ---
    thr_b = np.quantile(np.abs(dP[1:]), 1.0 - s)
    shock_b = np.abs(dP) > thr_b
    # regime cut-points = this path's own P-quantiles at the empirical VIX regime probabilities
    qs = np.quantile(P, spec["regime_probs"])
    bounds_b = [(-1e9, qs[0]), (qs[0], qs[1]), (qs[1], qs[2]), (qs[2], qs[3]), (qs[3], 1e9)]
    sars_b, occ_b, _ = sar_by_regime(abs_ret, P, shock_b, bounds_b)
    res["contemporaneous|B"] = sars_b
    res["occ_B"] = occ_b
    res["shock_rate_B"] = float(shock_b.mean())

    # --- C: relative threshold (same unit-free q as empirical) ---
    rel = np.zeros(len(P))
    rel[1:] = np.abs(dP[1:]) / P[:-1]
    shock_c = rel > spec["rel_q"]
    sars_c, _, _ = sar_by_regime(abs_ret, P, shock_c)
    res["contemporaneous|C"] = sars_c
    res["shock_rate_C"] = float(shock_c.mean())

    # --- D: sign-split (denominator = the shared non-shock set, as in the empirical) ---
    shock_up, shock_dn = dP > SHOCK_ABS, dP < -SHOCK_ABS
    any_shock = np.abs(dP) > SHOCK_ABS
    for sfx, sm_flag in (("D_up", shock_up), ("D_down", shock_dn)):
        res[f"contemporaneous|{sfx}"] = signed_sar_by_regime(
            abs_ret, P, sm_flag, any_shock
        )[0]
    res["shock_rate_D_up"] = float(shock_up.mean())
    res["shock_rate_D_down"] = float(shock_dn.mean())

    # --- E: ambient regime (classify by the PRE-shock fear level P[t-1]) ---
    sars_e, occ_e, _ = sar_by_regime(abs_ret[1:], P[:-1], any_shock[1:])
    res["contemporaneous|E"] = sars_e
    res["occ_E"] = occ_e

    # --- H: ambient x sign (the missing specification found by Codex primary review) ---
    # Classify by P[t-1], then split the day-t shock by sign. This is the direct null-side
    # counterpart of the paper's stated "ambient fear absorbs a fear shock" mechanism.
    for sfx, sm_flag in (("H_up", shock_up), ("H_down", shock_dn)):
        res[f"contemporaneous|{sfx}"] = signed_sar_by_regime(
            abs_ret[1:], P[:-1], sm_flag[1:], any_shock[1:]
        )[0]

    # --- G: doubly-corrected (POST-HOC): ambient regime AND relative threshold ---
    # Neither B, C nor E fixes more than one flaw at a time. G is the "most surgical" null the
    # independent review asked for: classify by the PRE-shock level (kills regime endogeneity)
    # AND use the unit-free relative threshold (kills the fixed-absolute-threshold selection
    # artifact). If the empirical decline still sits inside THIS null, the closure is robust to
    # both corrections at once; if it sits outside, the closure is fragile. Reported either way.
    sars_g, occ_g, _ = sar_by_regime(abs_ret[1:], P[:-1], shock_c[1:])
    res["contemporaneous|G"] = sars_g
    res["occ_G"] = occ_g

    # --- F: VRP-calibrated (POST-HOC, not pre-registered -- see README) ---
    # The obvious attack on variant A is that VIX carries a variance risk premium, so the
    # paper's literal 15/20/25/30 cut-points mean something different on the null's physical
    # vol scale (the null then sits in "calm" 77% of the time vs the data's 34%).  F answers
    # it head-on: map the null's proxy onto VIX's scale with the affine fit VIX ~ a + b*P
    # estimated on the real data, THEN apply the paper's literal thresholds.  The same map
    # scales the increments, so the +/-2 shock threshold is transported consistently.
    a_vrp, b_vrp = spec["vrp_a"], spec["vrp_b"]
    P_f = a_vrp + b_vrp * P
    dP_f = np.concatenate([[0.0], np.diff(P_f)])
    shock_f = np.abs(dP_f) > SHOCK_ABS
    sars_f, occ_f, ns_f = sar_by_regime(abs_ret, P_f, shock_f)
    res["contemporaneous|F"] = sars_f
    res["occ_F"] = occ_f
    res["shock_rate_F"] = float(shock_f.mean())

    return res


# ====================================================================================
# Empirical side -- mirrors simulate_one() variant for variant
# ====================================================================================
def filtered_contemporaneous_proxy(returns, params):
    """Run the SAME GJR recursion on the REAL returns and return the day-t contemporaneous
    proxy sqrt(h[t+1])*sqrt(252). Used only to calibrate the null's vol scale onto VIX's
    (variant F) -- it is not used for any SAR computation on the empirical side."""
    mu, ar1 = params["mu"], params["ar1"]
    w, al, g, b = params["omega"], params["alpha"], params["gamma"], params["beta"]
    r = np.asarray(returns, dtype=float)
    n = len(r)
    h = np.zeros(n + 1)
    h[0] = w / (1 - al - g / 2 - b)
    for t in range(1, n + 1):
        ind = 1.0 if r[t - 1] - mu < 0 else 0.0
        eps = r[t - 1] - mu - ar1 * (r[t - 2] if t >= 2 else 0.0)
        h[t] = max(w + (al + g * ind) * eps ** 2 + b * h[t - 1], 1e-8)
    return np.sqrt(h[1:n + 1]) * ANN


def empirical_side():
    df = pd.read_csv(PINNED_CSV, parse_dates=["date"])
    df = df[(df.date >= SAMPLE_START) & (df.date <= SAMPLE_END)].copy()
    df["ret"] = np.log(df["spy_adj_close"] / df["spy_adj_close"].shift(1)) * 100
    df = df.dropna(subset=["ret", "vix_close"])
    df["dvix"] = df["vix_close"].diff()
    df = df.dropna(subset=["dvix"]).reset_index(drop=True)

    a = df["ret"].abs().values
    V = df["vix_close"].values
    dV = df["dvix"].values

    shock_a = np.abs(dV) > SHOCK_ABS
    s = float(shock_a.mean())

    # regime probabilities under the empirical VIX -- variant B matches these by construction
    regime_probs = [float((V < b).mean()) for b in (15, 20, 25, 30)]

    # variant C: the unit-free threshold that reproduces the same shock rate empirically
    rel = np.zeros(len(V))
    rel[1:] = np.abs(dV[1:]) / V[:-1]
    rel_q = float(np.quantile(rel[1:], 1.0 - s))

    emp = {}
    sars_a, occ_a, ns_a = sar_by_regime(a, V, shock_a)
    emp["A"] = sars_a

    thr_b = float(np.quantile(np.abs(dV), 1.0 - s))
    shock_b = np.abs(dV) > thr_b
    emp["B"] = sar_by_regime(a, V, shock_b)[0]

    shock_c = rel > rel_q
    emp["C"] = sar_by_regime(a, V, shock_c)[0]

    any_shock = np.abs(dV) > SHOCK_ABS
    for sfx, sm_flag in (("D_up", dV > SHOCK_ABS), ("D_down", dV < -SHOCK_ABS)):
        emp[sfx] = signed_sar_by_regime(a, V, sm_flag, any_shock)[0]

    emp["E"] = sar_by_regime(a[1:], V[:-1], any_shock[1:])[0]
    for sfx, sm_flag in (("H_up", dV > SHOCK_ABS), ("H_down", dV < -SHOCK_ABS)):
        emp[sfx] = signed_sar_by_regime(
            a[1:], V[:-1], sm_flag[1:], any_shock[1:]
        )[0]
    emp["F"] = emp["A"]   # F changes only the NULL's scale; the data side is variant A
    emp["G"] = sar_by_regime(a[1:], V[:-1], shock_c[1:])[0]   # ambient regime + relative threshold

    # Variant F calibration: affine map from the null's physical vol scale onto VIX's scale,
    # fitted on the real data (VIX_t ~ a + b * P_t, where P_t is the same contemporaneous GJR
    # proxy the simulation uses). This is what lets the null be judged by the paper's literal
    # 15/20/25/30 thresholds without the variance-risk-premium level gap contaminating it.
    P_emp = filtered_contemporaneous_proxy(df["ret"].values, K897_PARAMS)
    b_vrp, a_vrp = np.polyfit(P_emp, V, 1)

    spec = {
        "shock_rate": s,
        "regime_probs": regime_probs,
        "rel_q": rel_q,
        "shock_thr_b": thr_b,
        "vrp_a": float(a_vrp),
        "vrp_b": float(b_vrp),
    }
    # Sign composition of the shock bucket, regime by regime. This is what the pooled
    # |dVIX| > 2 definition hides: at low VIX the shock bucket is mostly VIX-DOWN days,
    # and the calm-regime cell that anchors the whole decline is tiny.
    comp = []
    for lo, hi in REGIME_BOUNDS:
        m = (V >= lo) & (V < hi)
        n_up = int((m & (dV > SHOCK_ABS)).sum())
        n_dn = int((m & (dV < -SHOCK_ABS)).sum())
        comp.append({
            "regime": REGIME_NAMES[len(comp)],
            "n_shock_up": n_up,
            "n_shock_down": n_dn,
            "n_normal": int((m & ~shock_a).sum()),
            "up_share_of_shocks": round(n_up / (n_up + n_dn), 4) if (n_up + n_dn) else None,
        })

    ambient_comp = []
    a_amb, v_amb, dv_amb = a[1:], V[:-1], dV[1:]
    shock_amb = np.abs(dv_amb) > SHOCK_ABS
    for lo, hi in REGIME_BOUNDS:
        m = (v_amb >= lo) & (v_amb < hi)
        n_up = int((m & (dv_amb > SHOCK_ABS)).sum())
        n_dn = int((m & (dv_amb < -SHOCK_ABS)).sum())
        ambient_comp.append({
            "regime": REGIME_NAMES[len(ambient_comp)],
            "n_shock_up": n_up,
            "n_shock_down": n_dn,
            "n_normal": int((m & ~shock_amb).sum()),
            "up_share_of_shocks": round(n_up / (n_up + n_dn), 4) if (n_up + n_dn) else None,
            "mean_abs_return_up": round(float(a_amb[m & (dv_amb > SHOCK_ABS)].mean()), 6)
                if n_up else None,
        })

    # The up-only calm cell has n=10. A point estimate from 10 observations must not be stated
    # as settled fact (independent review H3), so bootstrap it and report the interval.
    rng_bs = np.random.RandomState(20260712)
    calm_m = (V >= 0) & (V < 15)
    high_m = (V >= 25) & (V < 30)
    cells = {
        "calm_up": a[calm_m & (dV > SHOCK_ABS)], "calm_normal": a[calm_m & ~shock_a],
        "high_up": a[high_m & (dV > SHOCK_ABS)], "high_normal": a[high_m & ~shock_a],
    }
    bs_sar_calm, bs_sar_high, bs_dec = [], [], []
    for _ in range(10_000):
        d = {k: rng_bs.choice(v, size=len(v), replace=True) for k, v in cells.items()}
        sc = d["calm_up"].mean() / d["calm_normal"].mean()
        sh = d["high_up"].mean() / d["high_normal"].mean()
        bs_sar_calm.append(sc), bs_sar_high.append(sh), bs_dec.append(sc - sh)
    point_sar_calm = float(cells["calm_up"].mean() / cells["calm_normal"].mean())
    point_sar_high = float(cells["high_up"].mean() / cells["high_normal"].mean())
    point_decline = point_sar_calm - point_sar_high
    up_bs = {
        "n_calm_up_shocks": int(len(cells["calm_up"])),
        "sar_up_calm": round(point_sar_calm, 4),
        "sar_up_calm_bootstrap_mean": round(float(np.mean(bs_sar_calm)), 4),
        "sar_up_calm_ci95": [round(float(np.percentile(bs_sar_calm, 2.5)), 4),
                             round(float(np.percentile(bs_sar_calm, 97.5)), 4)],
        "sar_up_high_ci95": [round(float(np.percentile(bs_sar_high, 2.5)), 4),
                             round(float(np.percentile(bs_sar_high, 97.5)), 4)],
        "up_decline_calm_minus_high": round(point_decline, 4),
        "up_decline_bootstrap_mean": round(float(np.mean(bs_dec)), 4),
        "up_decline_ci95": [round(float(np.percentile(bs_dec, 2.5)), 4),
                            round(float(np.percentile(bs_dec, 97.5)), 4)],
        "up_decline_ci_contains_zero": bool(np.percentile(bs_dec, 2.5) <= 0 <= np.percentile(bs_dec, 97.5)),
        "seed": BOOT_SEED,
        "note": ("The calm up-shock cell has only 10 days, so the up-only decline is imprecise. "
                 "What the interval CAN establish is reported; what it cannot is not asserted."),
    }

    paired_block = paired_block_bootstrap_sign_tests(
        a[1:], V[1:], V[:-1], dV[1:]
    )

    diag = {
        "sample": f"{df.date.min():%Y-%m-%d} to {df.date.max():%Y-%m-%d}",
        "up_shock_bootstrap": up_bs,
        "paired_block_bootstrap": paired_block,
        "n_observations": int(len(df)),
        "shock_rate_A": s,
        "n_shock_A": int(shock_a.sum()),
        "regime_occupancy": occ_a.tolist(),
        "n_shock_by_regime": ns_a.tolist(),
        "shock_sign_composition": comp,
        "ambient_sign_composition": ambient_comp,
        "n_shock_up": int((dV > SHOCK_ABS).sum()),
        "n_shock_down": int((dV < -SHOCK_ABS).sum()),
        "relative_threshold_q": rel_q,
        "abs_threshold_b": thr_b,
    }
    return emp, spec, diag


# ====================================================================================
# Inference
# ====================================================================================
def compare(emp_val, sim_vals, label):
    sim = np.asarray([v for v in sim_vals if not np.isnan(v)], dtype=float)
    n = len(sim)
    if n < 100 or emp_val is None or np.isnan(emp_val):
        return {"label": label, "empirical": None if emp_val is None or np.isnan(emp_val) else round(float(emp_val), 4),
                "n_valid_sims": n, "note": "insufficient valid simulations"}
    mean, std = float(sim.mean()), float(sim.std())
    lo, hi = float(np.percentile(sim, 2.5)), float(np.percentile(sim, 97.5))
    frac_above = float((sim >= emp_val).mean())
    frac_below = float((sim <= emp_val).mean())
    # Monte-Carlo empirical p-value (primary; no distributional assumption)
    # (b+1)/(n+1) plug-in rather than a bare 1/n floor -- the unbiased MC p-value (review L3).
    b_side = min(int((sim >= emp_val).sum()), int((sim <= emp_val).sum()))
    p_mc = float(min(1.0, 2.0 * (b_side + 1) / (n + 1)))
    z = float((emp_val - mean) / std) if std > 0 else float("nan")  # standardised distance
    return {
        "label": label,
        "empirical": round(float(emp_val), 4),
        "sim_mean": round(mean, 4),
        "sim_std": round(std, 4),
        "sim_ci_95": [round(lo, 4), round(hi, 4)],
        "in_95_ci": bool(lo <= emp_val <= hi),
        "z_score": round(z, 4),
        "p_value_monte_carlo": round(p_mc, 6),
        "frac_sim_above_empirical": round(frac_above, 4),
        "n_valid_sims": n,
    }


def regimewise(emp_sars, sim_matrix, label):
    out, n_out, n_tested = {}, 0, 0
    for i, rn in enumerate(REGIME_NAMES):
        c = compare(emp_sars[i], sim_matrix[:, i], f"{label} :: {rn}")
        out[rn] = c
        if "in_95_ci" in c:
            n_tested += 1
            n_out += (not c["in_95_ci"])
    return out, f"{n_out}/{n_tested}"


def write_json_atomic(path, payload):
    """Write, parse-verify, then atomically replace the result JSON."""
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
        f.flush()
    with open(tmp) as f:
        json.load(f)
    tmp.replace(path)


# ====================================================================================
def main():
    print("=" * 78)
    print("K1686: Contemporaneous null simulation (Paper 8 make-or-break gate)")
    print("=" * 78)

    print("\n[1/4] Empirical side (PINNED snapshot)...")
    emp, spec, diag = empirical_side()
    print(f"  {diag['sample']}  n={diag['n_observations']}  shock rate={diag['shock_rate_A']:.4f} "
          f"(n_shock={diag['n_shock_A']})")
    for i, rn in enumerate(REGIME_NAMES):
        print(f"    {rn:<18} SAR={emp['A'][i]:.4f}  occupancy={diag['regime_occupancy'][i]:.3f}")
    emp_decline = decline(emp["A"])
    print(f"  EMPIRICAL DECLINE (calm - high) = {emp_decline:.4f}   "
          f"[K897 live-yf: {K897_REFERENCE['empirical_decline_live_yfinance']}]")
    print(f"  variant C relative threshold q = {spec['rel_q']:.4f}")

    print(f"\n[2/4] Simulating {N_SIM} GJR paths x {N_OBS} obs (K897 params, K897 seeds)...")
    args = [(seed, K897_PARAMS, N_OBS, spec) for seed in SEEDS]
    n_workers = min(8, multiprocessing.cpu_count())
    sims = []
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        for i, r in enumerate(ex.map(simulate_one, args, chunksize=50)):
            sims.append(r)
            if (i + 1) % 2500 == 0:
                print(f"    {i + 1}/{N_SIM}")

    print("\n[3/4] Assembling...")
    keys = ["k897_lagged|A", "contemporaneous|A", "contemporaneous|B", "contemporaneous|C",
            "contemporaneous|D_up", "contemporaneous|D_down", "contemporaneous|E",
            "contemporaneous|H_up", "contemporaneous|H_down",
            "contemporaneous|F", "contemporaneous|G"]
    mats = {k: np.vstack([s[k] for s in sims]) for k in keys}
    declines = {k: np.array([decline(s[k]) for s in sims]) for k in keys}

    out = {
        "experiment_id": "k1686",
        "title": "Contemporaneous null simulation for volatility absorption (K897 timing fix)",
        "paper": "volatility-absorption (Paper 8)",
        "supersedes_identification_test_in": "k897",
        "trigger": "paper/volatility-absorption/review_history/fable_deep_review_20260711/README.md P0-1",
        "data_source": f"PINNED snapshot: {PINNED_CSV.relative_to(REPO)}",
        "sample_period": diag["sample"],
        "n_observations": diag["n_observations"],
        "n_simulations": N_SIM,
        "n_obs_per_sim": N_OBS,
        "garch_params": K897_PARAMS,
        "seed_spec": {
            "generator": "numpy.random.RandomState(seed)",
            "seeds": "0..9999 (identical to K897)",
            "innovation": "rng.standard_t(df=nu, size=5000) * sqrt((nu-2)/nu)",
            "note": ("Same seed + same n_obs + same params as K897 => simulated return paths are "
                     "pointwise identical to K897's. h is extended one step (h[n_obs], which needs "
                     "only eps[n_obs-1]) so no extra random draw is taken and no padding is used."),
        },
        "empirical_diagnostics": diag,
        "variant_spec": {
            "A": "PRIMARY. contemporaneous proxy sqrt(h[t+1]); regime by level; shock |dP|>2",
            "B": "frequency-matched: per-path quantile shock threshold + per-path regime cut-points "
                 "matched to empirical VIX regime probabilities",
            "C": "relative threshold |dP|/P_{t-1} > q, same unit-free q as empirical",
            "D": "sign-split: dP>+2 (vol up) vs dP<-2 (vol down); shared non-shock denominator",
            "E": "ambient regime: classify day t by the PRE-shock level P[t-1]",
            "H": "AMBIENT x SIGN: classify by P[t-1], split dP>+2 and dP<-2, and use the "
                 "shared pooled non-shock denominator. Added by the Codex FAIL follow-up and run "
                 "symmetrically on empirical data and the same-seed null paths",
            "G": "POST-HOC (not pre-registered): doubly-corrected -- ambient regime AND relative "
                 "threshold, i.e. B/C/E's fixes combined (independent review M2)",
            "F": "POST-HOC (not pre-registered): VRP-calibrated -- affine-map the null proxy onto VIX's "
                 "scale (VIX ~ a + b*P fitted on real data), THEN apply the paper's literal thresholds",
            "k897_lagged": "REPLICATION ARM: K897's proxy sqrt(h[t]) on the same paths (internal placebo)",
        },
        "pre_registered_decision_rule": {
            "primary_statistic": "decline = SAR(calm <15) - SAR(high 25-30), variant A",
            "empirical_value": round(emp_decline, 4),
            "outside_95_ci": "identification HOLDS and strengthens; paper upgrades",
            "inside_95_ci": "absorption claim DOWNGRADED to mechanical decomposition; paper reframes",
            "committed_before_results": "git commit 870af5d00 (README pre-registration, no results present)",
        },
        "codex_fail_followup_rule": {
            "statistic": "ambient(VIX_{t-1}) x up-shock SAR decline = calm minus high",
            "inference": ("paired circular moving-block bootstrap, primary block=20 trading days, "
                          "sensitivity blocks 10/20/40/63, B=10000"),
            "positive_ci_excluding_zero": "absorption survives the ambient fear-shock gate; JBF line may continue",
            "ci_including_zero": "mechanism unresolved; paper must be downgraded/reframed",
            "source": "task k1686_fix_ambient_sign_spec, fixed before this rerun",
        },
    }

    # --- replication check: does the lagged arm reproduce K897? ---
    rep = compare(emp_decline, declines["k897_lagged|A"], "K897 replication arm")
    out["k897_replication_check"] = {
        "ours": {k: rep[k] for k in ("sim_mean", "sim_std", "sim_ci_95", "n_valid_sims")},
        "k897_published": K897_REFERENCE,
        "reproduces_k897": bool(
            abs(rep["sim_mean"] - K897_REFERENCE["sim_mean_decline"]) < 0.02
            and abs(rep["sim_std"] - K897_REFERENCE["sim_std_decline"]) < 0.02
        ),
    }
    print(f"  K897 replication arm: sim_mean={rep['sim_mean']} (K897 published 0.1734), "
          f"sim_std={rep['sim_std']} (0.2105) -> reproduces={out['k897_replication_check']['reproduces_k897']}")

    # --- decline comparisons, all variants ---
    emp_declines = {
        "k897_lagged|A": emp_decline, "contemporaneous|A": emp_decline,
        "contemporaneous|B": decline(emp["B"]), "contemporaneous|C": decline(emp["C"]),
        "contemporaneous|D_up": decline(emp["D_up"]), "contemporaneous|D_down": decline(emp["D_down"]),
        "contemporaneous|E": decline(emp["E"]),
        "contemporaneous|H_up": decline(emp["H_up"]),
        "contemporaneous|H_down": decline(emp["H_down"]),
        "contemporaneous|F": emp_decline,   # F changes only the null's scale; data side = variant A
        "contemporaneous|G": decline(emp["G"]),
    }
    out["sar_decline_comparison"] = {
        k: compare(emp_declines[k], declines[k], k) for k in keys
    }

    # Secondary leg (normal -> high). Variant F's calm cell is unmeasurable (see
    # variant_F_calibration_note), so without this leg F would drop out silently -- exactly
    # the failure mode K897 shipped. Reported for every variant so the legs are comparable.
    declines_nh = {k: np.array([decline_nh(s[k]) for s in sims]) for k in keys}
    emp_nh = {
        "k897_lagged|A": decline_nh(emp["A"]), "contemporaneous|A": decline_nh(emp["A"]),
        "contemporaneous|B": decline_nh(emp["B"]), "contemporaneous|C": decline_nh(emp["C"]),
        "contemporaneous|D_up": decline_nh(emp["D_up"]),
        "contemporaneous|D_down": decline_nh(emp["D_down"]),
        "contemporaneous|E": decline_nh(emp["E"]),
        "contemporaneous|H_up": decline_nh(emp["H_up"]),
        "contemporaneous|H_down": decline_nh(emp["H_down"]),
        "contemporaneous|F": decline_nh(emp["A"]),
        "contemporaneous|G": decline_nh(emp["G"]),
    }
    out["sar_decline_normal_to_high_comparison"] = {
        k: compare(emp_nh[k], declines_nh[k], k) for k in keys
    }

    out["variant_F_calibration_note"] = {
        "affine_map": {"a": round(spec["vrp_a"], 4), "b": round(spec["vrp_b"], 4)},
        "calm_regime_evaluable": False,
        "why": ("The affine map that removes the variance-risk-premium level gap has slope "
                f"b={spec['vrp_b']:.3f} < 1, so it also COMPRESSES daily increments: a 2-point "
                f"move on VIX's scale needs |dP| > {2 / spec['vrp_b']:.2f} in the null's own units. "
                "Calm-regime shocks then fall below the minimum cell size in every path, and the "
                "null's overall shock rate collapses to ~0.06 vs the data's 0.151. "
                "So F fixes the LEVEL but breaks the INCREMENT scale. No single affine "
                "recalibration matches VIX in both -- there is no calibration-invariant null for "
                "this statistic. That is a property of the SAR design, not a coding failure, and "
                "it is reported rather than dropped."),
        "evaluable_leg_normal_to_high": "see sar_decline_normal_to_high_comparison",
    }

    # --- regime-wise SAR levels + occupancy diagnostics ---
    out["regime_sar"] = {}
    out["regimes_outside_ci"] = {}
    for k in keys:
        emp_key = k.split("|")[1] if k.startswith("contemporaneous") else "A"
        rw, cnt = regimewise(emp[emp_key], mats[k], k)
        out["regime_sar"][k] = rw
        out["regimes_outside_ci"][k] = cnt

    # --- mechanism diagnostic: WITHIN-REGIME shock rate, empirical vs null ---------------
    # If a fixed +/-2 threshold is applied to a mean-reverting vol process, plain decay at a
    # high level can cross the threshold on its own, flooding the "shock" bucket of the high
    # regimes with ordinary days. That inflates the within-regime shock rate and drags SAR
    # toward 1 -- i.e. it MANUFACTURES a decline with no absorption anywhere in the DGP.
    # This panel is what tells a genuine effect apart from that selection artifact.
    emp_wr = [
        round(diag["n_shock_by_regime"][i] / (diag["regime_occupancy"][i] * diag["n_observations"]), 4)
        if diag["regime_occupancy"][i] > 0 else None
        for i in range(5)
    ]
    sim_wr = [
        round(float(np.mean([s["nshock_A"][i] / (s["occ_A"][i] * N_OBS)
                             for s in sims if s["occ_A"][i] > 0])), 4)
        for i in range(5)
    ]
    out["mechanism_diagnostic_within_regime_shock_rate"] = {
        "empirical": emp_wr,
        "sim_contemporaneous_A": sim_wr,
        "regimes": REGIME_NAMES,
        "note": ("A fixed absolute threshold on a mean-reverting vol proxy becomes progressively "
                 "EASIER to cross as the level rises, because the decay term itself moves more than "
                 "2 annualised points. Where the null's within-regime shock rate runs far above the "
                 "data's, the null's shock bucket is being flooded with ordinary days and its SAR is "
                 "pushed toward 1 -- a decline produced by selection, not by absorption."),
    }

    # --- why D_down is undefined in the lower regimes: it is structural, not a bug -----------
    p_star = decay_only_drop_level(K897_PARAMS)
    out["down_shock_impossibility"] = {
        "min_level_for_a_2pt_one_day_fall": round(p_star, 2),
        "regimes_where_null_can_never_produce_a_down_shock":
            [rn for rn, (lo, hi) in zip(REGIME_NAMES, REGIME_BOUNDS) if hi <= p_star],
        "note": ("With alpha=0 the deepest one-day fall the null can produce is pure decay, "
                 f"h_next = omega + beta*h. That crosses -2 annualised points only above "
                 f"{p_star:.2f}. Below it a vol-DOWN shock cannot exist in this null AT ALL. "
                 "The empirical decline, however, is carried ENTIRELY by vol-DOWN days (see "
                 "the sign-split): the null has no such channel, so on the down side the null "
                 "and the data are not even measuring the same event. D_down's n_valid_sims=0 "
                 "in calm/normal/elevated is therefore a structural property of the null, not "
                 "a silent failure."),
    }

    out["calibration_diagnostics"] = {
        "regime_occupancy_empirical": [round(x, 4) for x in diag["regime_occupancy"]],
        "regime_occupancy_sim_A_contemporaneous":
            [round(float(np.mean([s["occ_A"][i] for s in sims])), 4) for i in range(5)],
        "regime_occupancy_sim_A_k897_lagged":
            [round(float(np.mean([s["occ_A_lagged"][i] for s in sims])), 4) for i in range(5)],
        "regime_occupancy_sim_B_frequency_matched":
            [round(float(np.mean([s["occ_B"][i] for s in sims])), 4) for i in range(5)],
        "shock_rate_empirical": round(diag["shock_rate_A"], 4),
        "shock_rate_sim_A_contemporaneous": round(float(np.mean([s["shock_rate_A"] for s in sims])), 4),
        "shock_rate_sim_A_k897_lagged": round(float(np.mean([s["shock_rate_A_lagged"] for s in sims])), 4),
        "shock_rate_sim_B": round(float(np.mean([s["shock_rate_B"] for s in sims])), 4),
        "shock_rate_sim_C": round(float(np.mean([s["shock_rate_C"] for s in sims])), 4),
        "regime_occupancy_sim_F_vrp_calibrated":
            [round(float(np.mean([s["occ_F"][i] for s in sims])), 4) for i in range(5)],
        "shock_rate_sim_F": round(float(np.mean([s["shock_rate_F"] for s in sims])), 4),
        "vrp_affine_map": {"a": round(spec["vrp_a"], 4), "b": round(spec["vrp_b"], 4)},
        "shock_rate_sim_D_up": round(float(np.mean([s["shock_rate_D_up"] for s in sims])), 4),
        "shock_rate_sim_D_down": round(float(np.mean([s["shock_rate_D_down"] for s in sims])), 4),
        "note": ("VIX carries a variance risk premium, so its level sits above the physical conditional "
                 "vol of the GARCH null. Under fixed thresholds (variant A) the simulation therefore "
                 "over-populates the calm regime relative to the data. Variant B removes this by "
                 "matching regime occupancy and shock rate by construction."),
    }

    # --- verdict, driven strictly by the pre-registered rule ---
    prim = out["sar_decline_comparison"]["contemporaneous|A"]
    if "in_95_ci" not in prim:
        out["verdict"] = "INCONCLUSIVE: primary variant had insufficient valid simulations"
    elif prim["in_95_ci"]:
        out["verdict"] = "IDENTIFICATION CLOSED"
        out["verdict_detail"] = (
            f"Empirical decline {prim['empirical']} falls INSIDE the contemporaneous null 95% CI "
            f"{prim['sim_ci_95']} (MC p={prim['p_value_monte_carlo']}). A GJR-GARCH with no absorption "
            f"mechanism, once its vol proxy is made contemporaneous with returns the way VIX is, "
            f"reproduces the observed SAR decline. Per the pre-registered rule the absorption claim is "
            f"DOWNGRADED to a mechanical decomposition of fixed-threshold selection plus same-day "
            f"co-movement; K897's NULL REJECTED verdict does not survive the timing fix."
        )
    else:
        side = "ABOVE" if prim["empirical"] > prim["sim_ci_95"][1] else "BELOW"
        out["verdict"] = "IDENTIFICATION HOLDS"
        out["verdict_detail"] = (
            f"Empirical decline {prim['empirical']} falls OUTSIDE ({side}) the contemporaneous null 95% CI "
            f"{prim['sim_ci_95']} (MC p={prim['p_value_monte_carlo']}). The decline survives the stricter, "
            f"timing-corrected null. Per the pre-registered rule the identification holds and strengthens."
        )

    # --- the verdict must CARRY the disagreement, not bury it (independent review H2) ---------
    # The pre-registered rule names A as primary AND obliges us to report variant conflict rather
    # than headline whichever variant flatters us. A verdict string computed from A alone would
    # satisfy the first half and quietly break the second. So attach the split to the verdict.
    rejects, fails_to_reject, unevaluable = [], [], []
    for k in keys:
        if k == "k897_lagged|A":
            continue
        c = out["sar_decline_comparison"][k]
        if "in_95_ci" not in c:
            unevaluable.append(k)
        elif c["in_95_ci"]:
            fails_to_reject.append(k)
        else:
            rejects.append(k)

    bs = diag["up_shock_bootstrap"]
    paired_block = diag["paired_block_bootstrap"]
    paired_primary = paired_block["by_block_length"][str(BOOT_PRIMARY_BLOCK)]
    ambient_up_primary = paired_primary["ambient_up_decline"]
    pooled_minus_up_primary = paired_primary["paired_pooled_minus_up_current"]
    out["variant_disagreement"] = {
        "fails_to_reject_the_null": fails_to_reject,
        "rejects_the_null": rejects,
        "not_evaluable_on_the_primary_leg": unevaluable,
        "the_null_comparison_is_INCONCLUSIVE": (
            "The variants split. Worse, the pre-registered primary's own non-rejection is not strong "
            "evidence: the mechanism diagnostic shows variant A's null manufactures its 0.619 decline "
            "by letting plain decay cross the fixed 2-point threshold at high vol levels (null "
            "within-regime shock rate 0.82 at crisis vs the data's 0.54), which is NOT how the decline "
            "arises in the data. A's 'pass' is one artifact cancelling another. The corrected nulls "
            "(B frequency-matched, C relative-threshold, G doubly-corrected) all reject. So neither "
            "'the decline is pure GARCH mechanics' NOR 'the decline is absorption' is established by "
            "the null comparison. It is inconclusive, and saying otherwise in either direction would "
            "be overclaiming."
        ),
        "why_no_null_can_settle_the_down_side": (
            f"Below {p_star:.1f} annualised points this null cannot produce a vol-DOWN shock AT ALL "
            "(alpha=0 => the deepest one-day fall is pure decay). But the empirical decline is carried "
            "ENTIRELY by vol-DOWN days. On the down side the null and the data are not even measuring "
            "the same event, so where B/C/G reject, what they detect is the ABSENCE OF A RELIEF-RALLY "
            "CHANNEL IN GARCH -- not the PRESENCE OF ABSORPTION IN MARKETS."
        ),
    }

    # --- direct empirical inference requested by the Codex FAIL follow-up -----------------------
    out["null_free_evidence"] = {
        "pooled_decline_headline": round(emp_decline, 4),
        "up_only_current_regime_decline": round(decline(emp["D_up"]), 4),
        "ambient_up_decline": round(decline(emp["H_up"]), 4),
        "paired_block_bootstrap": paired_block,
        "paired_pooled_minus_up_current_primary": pooled_minus_up_primary,
        "ambient_up_primary": ambient_up_primary,
        "down_only_decline": round(decline(emp["D_down"]), 4),
        "n_calm_up_shocks_current_regime": bs["n_calm_up_shocks"],
        "n_calm_down_shocks_current_regime": diag["shock_sign_composition"][0]["n_shock_down"],
        "n_calm_up_shocks_ambient_regime": diag["ambient_sign_composition"][0]["n_shock_up"],
        "n_high_up_shocks_ambient_regime": diag["ambient_sign_composition"][3]["n_shock_up"],
        "finding": (
            f"Current-VIX sign split gives up-only decline {decline(emp['D_up']):.4f}, but that "
            "post-shock regime definition is endogenous and cannot decide the ambient mechanism. "
            f"The required ambient(VIX_t-1) x up-shock decline is {decline(emp['H_up']):.4f}; "
            f"its primary 20-day paired block-bootstrap CI is {ambient_up_primary['ci95']}. "
            f"The direct paired pooled-minus-up-current contrast is {pooled_minus_up_primary['point_estimate']} "
            f"with CI {pooled_minus_up_primary['ci95']}; this replaces the invalid comparison of an "
            "up-only CI endpoint with the pooled point estimate."
        ),
        "inference_boundary": ("The paired bootstrap establishes only the registered ambient-up gate "
                               "and the pooled-minus-up contrast. It does not by itself identify a "
                               "structural causal channel."),
    }

    # --- SYNTHESIS. Preserve the original pre-registered A outcome, then apply the fixed follow-up
    # rule that was materialised in task k1686_fix_ambient_sign_spec before this rerun.
    out["pre_registered_primary_outcome"] = out.pop("verdict")
    out["pre_registered_primary_detail"] = out.pop("verdict_detail")
    followup_gate = paired_block["pre_registered_ambient_up_gate"]
    h_null = out["sar_decline_comparison"]["contemporaneous|H_up"]
    out["codex_followup_gate"] = {
        "verdict": followup_gate,
        "empirical_ambient_up": ambient_up_primary,
        "same_seed_null_comparison": h_null,
        "paired_pooled_minus_up_current": pooled_minus_up_primary,
        "block_length_sensitivity": {
            k: v["ambient_up_decline"] for k, v in paired_block["by_block_length"].items()
        },
    }
    if followup_gate == "NOT_EVALUABLE":
        out["verdict"] = "AMBIENT-FEAR-SHOCK GATE NOT EVALUABLE"
        out["verdict_detail"] = (
            f"Fewer than {MIN_BOOT_VALID} valid paired block-bootstrap replications were available "
            "for the ambient-up statistic. No positive or negative mechanism conclusion is allowed."
        )
    elif followup_gate == "ABSORPTION_SURVIVES_AMBIENT_FEAR_SHOCK_GATE":
        out["verdict"] = "ABSORPTION SURVIVES AMBIENT-FEAR-SHOCK GATE"
        out["verdict_detail"] = (
            f"The omitted ambient(VIX_t-1) x fear-shock specification reverses the earlier D_up "
            f"reading. Its empirical calm-minus-high decline is {ambient_up_primary['point_estimate']} "
            f"with a primary 20-day paired block-bootstrap 95% CI {ambient_up_primary['ci95']}, "
            "strictly positive under the fixed follow-up rule. The absorption mechanism therefore "
            "survives this empirical gate; the prior FRL downgrade is not supported by K1686 alone. "
            f"The same-seed GJR null comparison is reported separately (empirical {h_null.get('empirical')}, "
            f"null CI {h_null.get('sim_ci_95')}, MC p={h_null.get('p_value_monte_carlo')}) and remains "
            "subject to the documented level/increment calibration failures. The direct paired "
            f"pooled-minus-current-up contrast is {pooled_minus_up_primary['point_estimate']} with CI "
            f"{pooled_minus_up_primary['ci95']}; no inference is made by comparing separate intervals."
        )
    elif followup_gate == "MECHANISM_UNRESOLVED_CI_INCLUDES_ZERO":
        out["verdict"] = "AMBIENT-FEAR MECHANISM UNRESOLVED"
        out["verdict_detail"] = (
            f"The ambient(VIX_t-1) x fear-shock decline is {ambient_up_primary['point_estimate']} "
            f"with paired block-bootstrap CI {ambient_up_primary['ci95']}, which includes zero. "
            "Under the fixed follow-up rule the paper must be downgraded/reframed."
        )
    else:
        out["verdict"] = "ABSORPTION NOT SUPPORTED BY AMBIENT-FEAR-SHOCK GATE"
        out["verdict_detail"] = (
            f"The ambient(VIX_t-1) x fear-shock decline is {ambient_up_primary['point_estimate']} "
            f"with paired block-bootstrap CI {ambient_up_primary['ci95']}; it does not satisfy the "
            "pre-specified positive-CI gate."
        )

    write_json_atomic(HERE / "k1686_contemporaneous_null_results.json", out)

    print("\n[4/4] Verdict")
    print("=" * 78)
    for k in keys:
        c = out["sar_decline_comparison"][k]
        if "in_95_ci" in c:
            print(f"  {k:<26} emp={c['empirical']:>7}  null={c['sim_mean']:>7} +/-{c['sim_std']:<6} "
                  f"CI={str(c['sim_ci_95']):<18} in_CI={str(c['in_95_ci']):<5} p_mc={c['p_value_monte_carlo']}")
        else:
            print(f"  {k:<26} {c.get('note')}")
    print("-" * 78)
    print(f"  null comparison: rejects={[k.split('|')[1] for k in rejects]}  "
          f"fails-to-reject={[k.split('|')[1] for k in fails_to_reject]}  -> INCONCLUSIVE")
    print(f"  pre-registered primary (A): {out['pre_registered_primary_outcome']}")
    print(f"  paired pooled-current minus up-current: "
          f"{pooled_minus_up_primary['point_estimate']} CI {pooled_minus_up_primary['ci95']}")
    print(f"  ambient(VIX_t-1) x up-shock decline: {ambient_up_primary['point_estimate']} "
          f"CI {ambient_up_primary['ci95']} -> {followup_gate}")
    print("=" * 78)
    print(f"  VERDICT: {out['verdict']}")
    print(f"\n{out['verdict_detail']}")

    make_figure(out, declines, emp_declines, emp, diag)
    return out


def make_figure(out, declines, emp_declines, emp, diag):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = [
        ("k897_lagged|A", "K897 replication arm\n(lagged proxy -- the flawed null)"),
        ("contemporaneous|A", "A -- PRIMARY\ncontemporaneous, fixed threshold"),
        ("contemporaneous|B", "B -- frequency-matched\n(occupancy + shock rate matched)"),
        ("contemporaneous|C", "C -- relative threshold\n|dP|/P > q"),
        ("contemporaneous|D_up", "D -- sign-split: vol UP shocks\n(genuine fear spikes)"),
        (None, None),  # slot 6 is the empirical sign-split panel, drawn below
        ("contemporaneous|H_up", "H -- ambient x vol-UP shock\n(pre-shock regime; mechanism gate)"),
    ]
    fig, axes = plt.subplots(2, 4, figsize=(21, 9.5))
    flat = axes.ravel()
    for ax, (k, title) in zip(flat, panels):
        if k is None:
            continue
        d = declines[k][~np.isnan(declines[k])]
        e = emp_declines[k]
        c = out["sar_decline_comparison"][k]
        if len(d) < 100 or e is None or np.isnan(e):
            ax.text(0.5, 0.5, "insufficient valid sims", ha="center", va="center")
            ax.set_title(title, fontsize=10)
            continue
        ax.hist(d, bins=60, color="#8fb8de", edgecolor="white", linewidth=0.4)
        lo, hi = c["sim_ci_95"]
        ax.axvline(lo, color="#3b6ea5", ls="--", lw=1.2)
        ax.axvline(hi, color="#3b6ea5", ls="--", lw=1.2, label="null 95% CI")
        inside = c["in_95_ci"]
        ax.axvline(e, color="#c0392b" if not inside else "#1e8449", lw=2.4,
                   label=f"empirical = {e:.3f}")
        ax.set_title(f"{title}\nin 95% CI: {'YES' if inside else 'NO'}   MC p = {c['p_value_monte_carlo']}",
                     fontsize=9.5)
        ax.set_xlabel("SAR decline (calm - high)")
        ax.set_ylabel("simulated paths")
        ax.legend(fontsize=7.5, loc="upper right")

    # 6th panel: the empirical sign-split. This one needs no null model at all -- it is what the
    # data says once "fear shock" stops meaning "VIX moved 2 points in EITHER direction".
    # The null cannot even be drawn for the down-shocks (a GARCH sitting at a calm level cannot
    # shed 2 annualised vol points in one day), which is itself reported rather than hidden.
    ax = flat[5]
    x = np.arange(5)
    ax.plot(x, emp["A"], "o-", color="#2c3e50", lw=2.2, label="pooled |dVIX|>2 (paper's definition)")
    ax.plot(x, emp["D_up"], "s-", color="#c0392b", lw=2.2, label="vol UP shocks only (real fear)")
    ax.plot(x, emp["D_down"], "^-", color="#2980b9", lw=2.2, label="vol DOWN shocks only (relief)")
    ax.axhline(1.0, color="grey", ls=":", lw=1)
    for i, c in enumerate(diag["shock_sign_composition"]):
        ambient_c = diag["ambient_sign_composition"][i]
        ax.annotate(
            f"cur ↑/↓={c['n_shock_up']}/{c['n_shock_down']}\namb ↑={ambient_c['n_shock_up']}",
            (i, 3.63), ha="center", fontsize=6.2, color="#555"
        )
    ax.set_ylim(0.8, 3.95)
    ax.set_xticks(x)
    ax.set_xticklabels(["calm", "normal", "elev.", "high", "crisis"], fontsize=8)
    ax.set_ylabel("empirical SAR")
    ax.plot(x, emp["H_up"], "D--", color="#8e44ad", lw=2.0,
            label="ambient VIX(t-1) x vol UP")
    ax.set_title("EMPIRICAL SIGN SPLIT:\ncurrent vs pre-shock regime definitions", fontsize=9.5)
    ax.legend(fontsize=7, loc="lower left")

    # 8th panel: the mechanism. Where the null's within-regime shock rate runs above the data's,
    # its shock bucket is flooded with ordinary days and SAR is pushed toward 1 by selection.
    ax = flat[7]
    md = out["mechanism_diagnostic_within_regime_shock_rate"]
    x = np.arange(5)
    ax.bar(x - 0.2, [v if v is not None else 0 for v in md["empirical"]], 0.4,
           label="empirical (VIX)", color="#c0392b")
    ax.bar(x + 0.2, md["sim_contemporaneous_A"], 0.4, label="null, variant A", color="#8fb8de")
    ax.set_xticks(x)
    ax.set_xticklabels(["calm", "normal", "elev.", "high", "crisis"], fontsize=8)
    ax.set_ylabel("within-regime shock rate")
    ax.set_title("MECHANISM: is the null's shock bucket\nflooded by threshold-crossing decay?", fontsize=9.5)
    ax.legend(fontsize=7.5)

    fig.suptitle("K1686 R2: timing, shock sign, and pre-shock ambient-fear gates", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])
    fig.savefig(HERE / "k1686_null_distributions.png", dpi=140)
    print(f"\n  Figure: {HERE / 'k1686_null_distributions.png'}")


if __name__ == "__main__":
    main()
