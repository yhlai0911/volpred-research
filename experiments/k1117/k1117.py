"""
K1117: Daily-frequency alt-data matched-pair test on VIX jump days.

Motivation (K1116 derived direction #1):
  K1116/K1117b NULL for alt-data at weekly/monthly frequency, but a remaining
  conjecture: alt-data may only be informative during VIX JUMP events — the
  rare-but-high-information moments. A matched-pair design controls for the
  VIX regime itself, isolating the incremental value of alt-data conditional
  on a jump vs a non-jump regime-matched control.

Design (matched-pair, 2σ VIX jump events):
  1. Events T_jump = { t : |ΔVIX_t| > 2σ }, where σ = rolling 252d stdev of ΔVIX.
     Two-sided (up + down jumps). Robustness: 2.5σ and |VIX| > 30 absolute.
  2. For each jump day t, find matched control t' from NON-JUMP days s.t.
      - same month-of-year
      - VIX_t' within ±2 of VIX_t
      - day-of-week match (best-effort)
      - NOT in T_jump ± 5 days
     If <80% match, loosen VIX proximity to ±3.
  3. Baseline (M0): GARCH(1,1) on SPY, fit on expanding window ending at t-1.
     Alt (M_x): GARCH(1,1) + external regressor x_t (alt-data), lagged-published.
  4. Evaluate |ε_{t+1}|² using QLIKE (Patton 2011 proxy-robust).
  5. Tests:
     H1: paired DM on jump days: QLIKE(M_x) - QLIKE(M0) < 0, |t| > 2, p < 0.05.
     H2: paired DM on matched control days (non-jump).
     H3: bootstrap interaction test: ΔQLIKE(jump) - ΔQLIKE(nonjump) ≠ 0.

FRED publication delay rules (per error_log 2026-04-13, K1121 lesson):
  - NFCI: weekly (Fri) → published Wed → shift by 5 calendar days.
  - ANFCI: weekly (Fri) → shift 5 days.
  - STLFSI4: weekly (Fri) → shift 5 days.
  - USEPU (USEPUINDXD): daily → shift 2 days (T+1 release + 1 safety day).
  - WLEMU (WLEMUINDXD): daily → shift 2 days.
  - VVIX: same-day (closing; available real-time on CBOE).

Random seed: 42.

Author: Yi-Hao Lai + VolPred Research System.
Date: 2026-04-17.
"""
import json
import os
import time
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

OUT_DIR = Path(__file__).parent
SEED = 42
np.random.seed(SEED)

RESULTS = {
    "experiment_id": "K1117",
    "title": "Daily alt-data matched-pair test on VIX jump days (K1116 derivative)",
    "started_utc": datetime.utcnow().isoformat() + "Z",
    "data_source": "yfinance (SPY, ^VIX, ^VVIX) + FRED (USEPU, WLEMU, NFCI, ANFCI, STLFSI4)",
    "period_requested": "2010-01-01 to 2025-12-31",
    "seed": SEED,
    "design": "Matched-pair on VIX 2σ jump days",
    "publication_delays_used": {
        "NFCI": "+5 calendar days",
        "ANFCI": "+5 calendar days",
        "STLFSI4": "+5 calendar days",
        "USEPU": "+2 calendar days",
        "WLEMU": "+2 calendar days",
        "VVIX": "same-day (real-time close)",
    },
    "prior_related": {
        "K1116": "weekly alt-data NULL for SPY vol",
        "K1117b": "monthly alt-data H2_ROBUST_NULL",
        "K1121": "daily step alt-data allocation NULL + publication-delay bug lesson",
    },
    "references": [
        "Baker, Bloom, Davis (2016) QJE - EPU",
        "Brave, Butters (2011) - NFCI",
        "Kliesen, Smith (2010) - STLFSI",
        "Patton (2011) JoE 160 - QLIKE proxy-robust",
        "Harvey, Leybourne, Newbold (1997) IJF - HLN DM correction",
        "Harvey, Liu, Zhu (2016) RFS - |t|>3 multiple-test threshold",
    ],
}


def log(msg):
    ts = datetime.utcnow().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


# -----------------------------------------------------------------------------
# Step 1: data
# -----------------------------------------------------------------------------

def fetch_daily_market(cache_path=None):
    import yfinance as yf

    if cache_path and cache_path.exists():
        log(f"Loading market cache {cache_path.name}")
        df = pd.read_parquet(cache_path)
        return df

    log("Fetching SPY + VIX + VVIX 2010-2025 from yfinance...")
    spy = yf.download("SPY", start="2010-01-01", end="2025-12-31",
                      progress=False, auto_adjust=True)
    vix = yf.download("^VIX", start="2010-01-01", end="2025-12-31",
                      progress=False, auto_adjust=False)
    vvix = yf.download("^VVIX", start="2010-01-01", end="2025-12-31",
                       progress=False, auto_adjust=False)

    for d in (spy, vix, vvix):
        if isinstance(d.columns, pd.MultiIndex):
            d.columns = d.columns.get_level_values(0)

    df = pd.DataFrame(index=spy.index)
    df["spy_close"] = spy["Close"]
    df["r"] = np.log(df["spy_close"]).diff()
    df["r2"] = df["r"] ** 2
    df["vix"] = vix["Close"]
    df["vvix"] = vvix["Close"]
    df = df.dropna(subset=["r", "vix"]).copy()

    log(f"Daily panel: {len(df)} days, {df.index.min().date()} -> {df.index.max().date()}")
    if cache_path:
        df.to_parquet(cache_path)
    return df


def fetch_fred_altdata_daily(cache_path=None):
    """Fetch FRED alt-data at its native frequency then align daily with
    publication-delay shift (per error_log 2026-04-13).
    """
    if cache_path and cache_path.exists():
        log(f"Loading FRED cache {cache_path.name}")
        return pd.read_parquet(cache_path)

    import urllib.request
    from io import StringIO

    codes = {
        "USEPU": "USEPUINDXD",
        "WLEMU": "WLEMUINDXD",
        "NFCI": "NFCI",
        "ANFCI": "ANFCI",
        "STLFSI": "STLFSI4",
    }
    pub_delay = {
        "USEPU": 2,
        "WLEMU": 2,
        "NFCI": 5,
        "ANFCI": 5,
        "STLFSI": 5,
    }
    log(f"Fetching FRED alt-data via fredgraph {list(codes.values())} 2010-2025...")
    import subprocess
    frames = {}
    for name, code in codes.items():
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={code}"
        text = None
        for attempt in range(3):
            try:
                result = subprocess.run(
                    ["curl", "-s", "-m", "60", url],
                    capture_output=True, text=True, timeout=70,
                )
                if result.returncode == 0 and result.stdout and "," in result.stdout:
                    text = result.stdout
                    break
            except Exception as e:
                log(f"  {code}: attempt {attempt+1}: {str(e)[:50]}")
                time.sleep(2)
        if text is None:
            log(f"  {code}: ALL ATTEMPTS FAILED")
            continue
        try:
            s = pd.read_csv(StringIO(text))
            # columns: observation_date or DATE, and series code
            date_col = [c for c in s.columns if c.upper() in ("DATE", "OBSERVATION_DATE")][0]
            val_col = [c for c in s.columns if c != date_col][0]
            s[date_col] = pd.to_datetime(s[date_col])
            s = s.set_index(date_col)
            s[val_col] = pd.to_numeric(s[val_col], errors="coerce")
            s = s.rename(columns={val_col: name}).dropna()
            # restrict to 2009- for warm-up, upper 2025-12-31
            s = s.loc["2009-01-01":"2025-12-31"]
            # shift by publication delay (calendar days)
            s.index = s.index + pd.Timedelta(days=pub_delay[name])
            frames[name] = s
            log(f"  {code}: {s.shape}, last available-to-use={s.index[-1].date()}, delay={pub_delay[name]}d")
        except Exception as e:
            log(f"  {code}: FAIL {str(e)[:80]}")

    # Build daily index from 2010-01-01 to 2025-12-31
    idx = pd.date_range("2010-01-01", "2025-12-31", freq="B")
    out = pd.DataFrame(index=idx)
    out.index.name = "date"
    for name, s in frames.items():
        # daily asof forward-fill from published date to today
        r = s.reindex(out.index.union(s.index)).sort_index()
        r[name] = r[name].ffill(limit=10)  # up to 10 bdays ffill for weekly series
        out[name] = r.reindex(out.index)[name]

    log(f"FRED daily aligned: {out.shape}; nan %:")
    for c in out.columns:
        log(f"  {c}: {out[c].isna().mean():.2%}")
    if cache_path:
        out.to_parquet(cache_path)
    return out


# -----------------------------------------------------------------------------
# Step 2: VIX jump event definition
# -----------------------------------------------------------------------------

def compute_vix_jumps(df, sigma_thresh=2.0, window=252):
    """Return boolean Series of jump days and the 252-day rolling stdev of ΔVIX.

    Note: thresholds computed from *past* data only — σ_t uses ΔVIX[t-window:t-1]
    (rolling with min_periods=window). No lookahead.
    """
    dvix = df["vix"].diff()
    # rolling stdev LAGGED by 1 (so σ_t uses only data up to t-1)
    sigma = dvix.shift(1).rolling(window, min_periods=window).std()
    df = df.copy()
    df["dvix"] = dvix
    df["sigma_dvix"] = sigma
    df["abs_dvix_z"] = dvix.abs() / sigma
    df["is_jump"] = df["abs_dvix_z"] > sigma_thresh
    df["is_up_jump"] = (dvix > 0) & df["is_jump"]
    df["is_down_jump"] = (dvix < 0) & df["is_jump"]
    return df


# -----------------------------------------------------------------------------
# Step 3: Matched-pair construction
# -----------------------------------------------------------------------------

def find_matched_controls(df, jump_dates, exclude_buffer=5,
                          vix_tol=2.0, vix_tol_loose=3.0,
                          match_dow=True):
    """For each jump day, find a non-jump matched control.

    Criteria (in order of relaxation):
      1. VIX_t' within ±vix_tol of VIX_t
      2. same month-of-year
      3. (optional) same day-of-week
      4. NOT in T_jump ± exclude_buffer days
      5. If no match at ±vix_tol, expand to ±vix_tol_loose

    Each control used at most once.
    """
    # non-eligible dates: jump days + their ±buffer window
    jump_set = set(jump_dates)
    excluded = set()
    for d in jump_dates:
        for k in range(-exclude_buffer, exclude_buffer + 1):
            excluded.add(d + pd.Timedelta(days=k))

    non_jump = df.index.difference(pd.DatetimeIndex(list(jump_set)))
    eligible = non_jump.difference(pd.DatetimeIndex(list(excluded)))
    eligible_df = df.loc[eligible].copy()
    eligible_df["month"] = eligible_df.index.month
    eligible_df["dow"] = eligible_df.index.dayofweek

    used = set()
    pairs = []  # (jump_date, control_date)
    match_quality = {"exact_tol": 0, "loose_tol": 0, "no_match": 0}

    rng = np.random.default_rng(SEED)  # tie-breaker deterministic

    for jd in jump_dates:
        if jd not in df.index:
            match_quality["no_match"] += 1
            continue
        vix_j = df.loc[jd, "vix"]
        mo = jd.month
        dow = jd.dayofweek

        def filter_controls(tol, require_dow):
            mask = eligible_df["month"] == mo
            mask &= (eligible_df["vix"] - vix_j).abs() <= tol
            if require_dow:
                mask &= eligible_df["dow"] == dow
            cand = eligible_df[mask].index
            cand = cand.difference(pd.DatetimeIndex(list(used)))
            return cand

        # Try tight tolerance with DOW
        cand = filter_controls(vix_tol, require_dow=match_dow) if match_dow else filter_controls(vix_tol, False)
        used_tol = "exact_tol"
        if len(cand) == 0 and match_dow:
            cand = filter_controls(vix_tol, require_dow=False)
        if len(cand) == 0:
            cand = filter_controls(vix_tol_loose, require_dow=False)
            used_tol = "loose_tol"
        if len(cand) == 0:
            match_quality["no_match"] += 1
            continue

        # pick the one closest in VIX (tie-broken by proximity to same DOW then randomly)
        diffs = (eligible_df.loc[cand, "vix"] - vix_j).abs()
        min_diff = diffs.min()
        best = diffs[diffs == min_diff].index
        if len(best) > 1:
            best_dow_diff = ((eligible_df.loc[best, "dow"] - dow) % 7).abs()
            pick_set = best[best_dow_diff == best_dow_diff.min()]
            chosen = pick_set[rng.integers(0, len(pick_set))]
        else:
            chosen = best[0]

        pairs.append((jd, chosen))
        used.add(chosen)
        match_quality[used_tol] += 1

    return pairs, match_quality


# -----------------------------------------------------------------------------
# Step 4: GARCH(1,1) + external regressor forecasts
# -----------------------------------------------------------------------------

def fit_garch_forecast(returns_pct, ex_regressor=None):
    """Fit GARCH(1,1); return 1-step-ahead σ² forecast.

    If ex_regressor provided (array aligned with returns_pct, last value is the
    regressor available at time T), include as a variance regressor via GJR+X
    approximation: we add the regressor as a constant shift in ω using the
    scaling Var(r) × exp(γ * x).

    Implementation: use the `arch` package with GARCH(1,1) + optional ex variable
    in mean; but for simplicity and to avoid refit cost, we fit GARCH(1,1) on
    returns and add the ex-regressor's OLS-estimated contribution to σ²
    additively (simple HAR-style extension): σ²_pred = σ²_GARCH + β * x_T.
    β estimated jointly via MLE by regressing actual r² on (σ²_GARCH, x).

    Returns: sigma2_pred (float) — 1-step-ahead variance in % scale.
    """
    from arch import arch_model

    am = arch_model(returns_pct, mean="Zero", vol="GARCH", p=1, q=1, dist="normal",
                    rescale=False)
    try:
        res = am.fit(disp="off", show_warning=False, update_freq=0)
    except Exception:
        return np.nan
    fc = res.forecast(horizon=1, reindex=False)
    sigma2 = float(fc.variance.iloc[-1, 0])

    if ex_regressor is None:
        return sigma2

    # Estimate β from r²[t+1] ~ σ²_fitted[t] + x[t]
    try:
        cond_var = res.conditional_volatility ** 2  # fitted σ² (% scale)
        r2_next = (returns_pct[1:] ** 2)
        cv_t = cond_var[:-1].values
        x_t = np.asarray(ex_regressor[:-1], dtype=float)
        valid = np.isfinite(cv_t) & np.isfinite(x_t) & np.isfinite(r2_next)
        if valid.sum() < 50:
            return sigma2
        cv_t = cv_t[valid]; x_t = x_t[valid]; r2_next = r2_next[valid]
        # OLS: r2 = a*cv + b*x + c (let OLS absorb intercept)
        X = np.column_stack([cv_t, x_t, np.ones_like(cv_t)])
        coef, *_ = np.linalg.lstsq(X, r2_next, rcond=None)
        a, b, c = coef
        x_T = float(ex_regressor[-1])
        if not np.isfinite(x_T):
            return sigma2
        augmented = a * sigma2 + b * x_T + c
        # guard: require positive; if augmented <= 0, fall back
        if augmented <= 0:
            return sigma2
        return float(augmented)
    except Exception:
        return sigma2


# -----------------------------------------------------------------------------
# Step 5: QLIKE + DM
# -----------------------------------------------------------------------------

def qlike_loss(actual, pred):
    """Per-observation QLIKE loss (Patton 2011). Returns array, not mean.
    actual, pred in same scale (both are variance; % or decimal consistent).
    """
    eps = 1e-10
    actual = np.maximum(np.asarray(actual, dtype=float), eps)
    pred = np.maximum(np.asarray(pred, dtype=float), eps)
    return np.log(pred) + actual / pred


def paired_dm(loss_a, loss_b, h=1):
    """Paired DM-HLN for matched-pair differences.
    Returns (t, p). t>0 means loss_a > loss_b (B wins).
    """
    from scipy import stats as st
    d = np.asarray(loss_a, dtype=float) - np.asarray(loss_b, dtype=float)
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 10:
        return np.nan, np.nan
    dbar = d.mean()
    gamma0 = np.var(d, ddof=1)
    if gamma0 <= 0:
        return np.nan, np.nan
    hln = np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n)
    se = np.sqrt(gamma0 / n)
    t = (dbar / se) * hln
    p = 2 * (1 - st.t.cdf(abs(t), df=n - 1))
    return float(t), float(p)


def benjamini_hochberg(p_values):
    p = np.asarray(p_values, dtype=float)
    n = len(p)
    order = np.argsort(p)
    ranked = p[order]
    adjusted = np.minimum.accumulate((ranked * n / np.arange(1, n + 1))[::-1])[::-1]
    adjusted = np.minimum(adjusted, 1.0)
    out = np.empty_like(adjusted)
    out[order] = adjusted
    return out


def bootstrap_interaction_test(delta_jump, delta_nonjump, B=2000, seed=42):
    """Bootstrap H3: whether ΔQLIKE is more negative on jumps vs non-jumps.
    Returns (mean_diff, se, p).
    """
    rng = np.random.default_rng(seed)
    dj = np.asarray(delta_jump, dtype=float)
    dn = np.asarray(delta_nonjump, dtype=float)
    dj = dj[np.isfinite(dj)]
    dn = dn[np.isfinite(dn)]
    if len(dj) < 10 or len(dn) < 10:
        return np.nan, np.nan, np.nan
    observed = dj.mean() - dn.mean()
    nb_j = len(dj); nb_n = len(dn)
    stats = np.empty(B)
    for b in range(B):
        bj = rng.choice(dj, nb_j, replace=True)
        bn = rng.choice(dn, nb_n, replace=True)
        stats[b] = bj.mean() - bn.mean()
    # two-sided p via percentile reflection
    p = 2 * min((stats >= 0).mean(), (stats <= 0).mean())
    return float(observed), float(stats.std(ddof=1)), float(p)


# -----------------------------------------------------------------------------
# Step 6: Main experiment
# -----------------------------------------------------------------------------

def run_experiment():
    t0 = time.time()
    data_dir = OUT_DIR / "data"
    data_dir.mkdir(exist_ok=True)

    market_cache = data_dir / "market_daily.parquet"
    fred_cache = data_dir / "fred_daily_pubshift.parquet"

    df_m = fetch_daily_market(market_cache)
    df_f = fetch_fred_altdata_daily(fred_cache)

    # merge
    df = df_m.join(df_f, how="left")
    df = df.dropna(subset=["r", "vix"])
    # Warm-up: keep only rows where at least USEPU, NFCI available (expected from 2010)
    log(f"Merged: {len(df)} days, {df.index.min().date()} -> {df.index.max().date()}")
    RESULTS["n_merged"] = len(df)
    RESULTS["period"] = [str(df.index.min().date()), str(df.index.max().date())]

    # Step 2: identify jumps
    jump_variants = {
        "primary_2sigma": 2.0,
        "robust_2p5sigma": 2.5,
    }
    jump_events = {}
    for name, thr in jump_variants.items():
        df_j = compute_vix_jumps(df, sigma_thresh=thr)
        jumps = df_j.index[df_j["is_jump"].fillna(False)].tolist()
        # remove any jumps in first 300 days (warmup)
        jumps = [d for d in jumps if d > df.index[300]]
        # remove any jumps in last 5 days (no t+1 available)
        jumps = [d for d in jumps if d < df.index[-5]]
        jump_events[name] = jumps
        log(f"Jumps ({name}, thr={thr}σ): N={len(jumps)}")

    # Additional absolute threshold
    df_abs = df.copy()
    abs_jumps = df_abs.index[df_abs["vix"] > 30].tolist()
    abs_jumps = [d for d in abs_jumps if d > df.index[300] and d < df.index[-5]]
    jump_events["robust_absVIX30"] = abs_jumps
    log(f"Jumps (robust_absVIX30): N={len(abs_jumps)}")

    RESULTS["jump_counts"] = {k: len(v) for k, v in jump_events.items()}

    # For the main test, use primary_2sigma
    primary_jumps = jump_events["primary_2sigma"]
    if len(primary_jumps) < 30:
        raise RuntimeError(f"Too few primary jumps: {len(primary_jumps)}")

    # Step 3: matched controls
    pairs, match_q = find_matched_controls(df, primary_jumps,
                                           exclude_buffer=5,
                                           vix_tol=2.0, vix_tol_loose=3.0,
                                           match_dow=True)
    match_rate = len(pairs) / len(primary_jumps)
    log(f"Matched {len(pairs)} / {len(primary_jumps)} jumps ({match_rate:.1%}) "
        f"exact_tol={match_q['exact_tol']} loose_tol={match_q['loose_tol']} "
        f"no_match={match_q['no_match']}")
    RESULTS["match_quality"] = {
        "n_jumps": len(primary_jumps),
        "n_matched": len(pairs),
        "match_rate": match_rate,
        **match_q,
    }
    if match_rate < 0.80:
        log(f"WARNING: match_rate {match_rate:.1%} < 80%. Fallback to ±3 VIX.")

    # Step 4: fit GARCH + alt-data models for each pair, save per-event loss
    alt_vars = ["vvix", "USEPU", "NFCI", "ANFCI", "STLFSI", "WLEMU"]
    # Keep only alt-vars available in enough rows
    alt_vars = [a for a in alt_vars if a in df.columns and df[a].notna().mean() > 0.5]
    RESULTS["alt_vars_tested"] = alt_vars

    # Pre-compute r_pct series (GARCH in % scale)
    r_pct = df["r"].values * 100.0  # % scale

    # GARCH refit: bucket by 60-day windows for efficiency. Within a bucket,
    # reuse the fit but use the fit's one-step-ahead forecast *series* at the
    # correct index (ji - fit_end_idx) via conditional variance recursion.
    event_records = []
    n_pairs = len(pairs)
    log(f"Fitting GARCH(1,1) × {alt_vars} for {n_pairs} matched pairs...")

    fit_cache = {}

    def get_garch_fit(end_idx):
        """Fit GARCH on r_pct[:end_idx+1] and return a dict with:
          - params (ω, α, β)
          - cond_var: full series of conditional variance up to t=end_idx
          - coefs: dict {alt: [a,b,c]} for r2[t+1] ~ a*cv[t] + b*x[t] + c on fit sample
        We refit every 60 days (bucket). Within a bucket we can extend σ² forward
        via the standard GARCH recursion using ω,α,β — this is valid because
        within a 60-day window at daily frequency the parameter update is small.
        """
        key = end_idx // 60
        if key in fit_cache:
            return fit_cache[key]
        from arch import arch_model
        r_sub = r_pct[:end_idx + 1]
        if len(r_sub) < 500:
            return None
        am = arch_model(r_sub, mean="Zero", vol="GARCH", p=1, q=1,
                        dist="normal", rescale=False)
        try:
            res = am.fit(disp="off", show_warning=False, update_freq=0)
        except Exception:
            return None
        p = res.params
        omega = float(p["omega"])
        alpha = float(p["alpha[1]"])
        beta = float(p["beta[1]"])
        cv_fitted = np.asarray(res.conditional_volatility ** 2)
        # extend cv forward via recursion using actual returns
        # cv[t+1] = omega + alpha*r[t]² + beta*cv[t]
        full_len = len(r_pct)
        cv_full = np.empty(full_len)
        cv_full[:len(cv_fitted)] = cv_fitted
        for t in range(len(cv_fitted), full_len):
            cv_full[t] = omega + alpha * (r_pct[t - 1] ** 2) + beta * cv_full[t - 1]
        # one-step forecast σ²_{t+1} given info up to t: use current r_pct[t] and cv_full[t]
        # σ²_{t+1} = omega + alpha*r[t]² + beta*cv[t]
        sigma2_next = np.empty(full_len)
        sigma2_next[:] = np.nan
        for t in range(full_len - 1):
            sigma2_next[t] = omega + alpha * (r_pct[t] ** 2) + beta * cv_full[t]
        coef_map = {
            "__params__": (omega, alpha, beta),
            "__cond_var__": cv_full,
            "__sigma2_next__": sigma2_next,
            "__fit_end__": end_idx,
        }
        # Estimate alt-var coefficients using in-sample (fit window) data only
        r2 = r_pct ** 2
        for a in alt_vars:
            x_series = df[a].values
            cv_t = cv_full[:end_idx]
            r2_next = r2[1:end_idx + 1]
            x_t = x_series[:end_idx]
            m = min(len(cv_t), len(r2_next), len(x_t))
            cv_t = cv_t[:m]; r2_next = r2_next[:m]; x_t = x_t[:m]
            valid = np.isfinite(cv_t) & np.isfinite(x_t) & np.isfinite(r2_next)
            if valid.sum() < 200:
                coef_map[a] = None
                continue
            X = np.column_stack([cv_t[valid], x_t[valid], np.ones(valid.sum())])
            try:
                c_est, *_ = np.linalg.lstsq(X, r2_next[valid], rcond=None)
                coef_map[a] = c_est
            except Exception:
                coef_map[a] = None
        fit_cache[key] = coef_map
        return coef_map

    # Gather per-pair losses
    pair_records = []
    idx_map = {d: i for i, d in enumerate(df.index)}

    for jd, cd in pairs:
        ji = idx_map[jd]
        ci = idx_map[cd]
        if ji >= len(df) - 1 or ci >= len(df) - 1:
            continue
        # realized r²[t+1] both (in % scale to match GARCH σ²)
        r2_j = (r_pct[ji + 1]) ** 2
        r2_c = (r_pct[ci + 1]) ** 2
        if not (np.isfinite(r2_j) and np.isfinite(r2_c)):
            continue

        # GARCH fits conditioned on data up to t-1 (use end_idx = ji for jump, ci for control)
        fit_j = get_garch_fit(ji)
        fit_c = get_garch_fit(ci)
        if fit_j is None or fit_c is None:
            continue

        # 1-step-ahead σ² from GARCH for jump day and control day
        sigma2_base_j = float(fit_j["__sigma2_next__"][ji])
        sigma2_base_c = float(fit_c["__sigma2_next__"][ci])
        if not (np.isfinite(sigma2_base_j) and sigma2_base_j > 0 and
                np.isfinite(sigma2_base_c) and sigma2_base_c > 0):
            continue

        # For each alt-var, augmented σ²
        aug_j = {}
        aug_c = {}
        for a in alt_vars:
            coef_j = fit_j.get(a)
            coef_c = fit_c.get(a)
            x_j = df[a].iloc[ji]
            x_c = df[a].iloc[ci]
            if coef_j is None or not np.isfinite(x_j):
                aug_j[a] = sigma2_base_j
            else:
                a1, b1, c1 = coef_j
                v = a1 * sigma2_base_j + b1 * x_j + c1
                aug_j[a] = float(v) if v > 0 else sigma2_base_j
            if coef_c is None or not np.isfinite(x_c):
                aug_c[a] = sigma2_base_c
            else:
                a2, b2, c2 = coef_c
                v = a2 * sigma2_base_c + b2 * x_c + c2
                aug_c[a] = float(v) if v > 0 else sigma2_base_c

        # QLIKE per observation
        loss_j_base = float(qlike_loss(r2_j, sigma2_base_j))
        loss_c_base = float(qlike_loss(r2_c, sigma2_base_c))
        rec = {
            "jump_date": str(jd.date()),
            "control_date": str(cd.date()),
            "vix_jump": float(df.loc[jd, "vix"]),
            "vix_control": float(df.loc[cd, "vix"]),
            "dvix_jump": float(df.loc[jd, "dvix"]) if "dvix" in df.columns else np.nan,
            "abs_dvix_z_jump": float(df.loc[jd, "abs_dvix_z"]) if "abs_dvix_z" in df.columns else np.nan,
            "r2_next_jump": float(r2_j),
            "r2_next_control": float(r2_c),
            "sigma2_base_jump": sigma2_base_j,
            "sigma2_base_control": sigma2_base_c,
            "loss_base_jump": loss_j_base,
            "loss_base_control": loss_c_base,
        }
        for a in alt_vars:
            rec[f"sigma2_{a}_jump"] = aug_j[a]
            rec[f"sigma2_{a}_control"] = aug_c[a]
            rec[f"loss_{a}_jump"] = float(qlike_loss(r2_j, aug_j[a]))
            rec[f"loss_{a}_control"] = float(qlike_loss(r2_c, aug_c[a]))
        pair_records.append(rec)

    log(f"Pairs with valid losses: {len(pair_records)}")
    if len(pair_records) < 30:
        raise RuntimeError("Too few valid pair records")

    pair_df = pd.DataFrame(pair_records)
    pair_df.to_csv(OUT_DIR / "k1117_matched_pair_losses.csv", index=False)

    # Step 5: Hypothesis tests per alt-var
    test_results = {}
    h1_pvalues = []
    h2_pvalues = []
    h3_pvalues = []
    for a in alt_vars:
        # H1: paired DM on jump-day losses
        la_j = pair_df[f"loss_{a}_jump"].values
        lb_j = pair_df["loss_base_jump"].values
        t1, p1 = paired_dm(lb_j, la_j)  # t>0 means alt beats baseline
        # H2: paired DM on matched control losses
        la_c = pair_df[f"loss_{a}_control"].values
        lb_c = pair_df["loss_base_control"].values
        t2, p2 = paired_dm(lb_c, la_c)
        # H3: interaction — ΔQLIKE(jump) vs ΔQLIKE(nonjump)
        delta_j = la_j - lb_j  # negative = alt wins jump
        delta_c = la_c - lb_c
        mean_diff, se, p3 = bootstrap_interaction_test(delta_j, delta_c,
                                                      B=2000, seed=SEED)
        test_results[a] = {
            "H1_DM_t": t1, "H1_DM_p": p1,
            "H1_mean_loss_base_jump": float(np.nanmean(lb_j)),
            "H1_mean_loss_alt_jump": float(np.nanmean(la_j)),
            "H2_DM_t": t2, "H2_DM_p": p2,
            "H2_mean_loss_base_ctrl": float(np.nanmean(lb_c)),
            "H2_mean_loss_alt_ctrl": float(np.nanmean(la_c)),
            "H3_interaction_diff": mean_diff,
            "H3_interaction_se": se,
            "H3_interaction_p": p3,
            "H1_delta_mean": float(np.nanmean(delta_j)),
            "H2_delta_mean": float(np.nanmean(delta_c)),
        }
        h1_pvalues.append(p1)
        h2_pvalues.append(p2)
        h3_pvalues.append(p3)

    # BH correction
    bh_h1 = benjamini_hochberg(h1_pvalues)
    bh_h2 = benjamini_hochberg(h2_pvalues)
    bh_h3 = benjamini_hochberg(h3_pvalues)
    for i, a in enumerate(alt_vars):
        test_results[a]["H1_DM_p_BH"] = float(bh_h1[i])
        test_results[a]["H2_DM_p_BH"] = float(bh_h2[i])
        test_results[a]["H3_interaction_p_BH"] = float(bh_h3[i])

    RESULTS["tests"] = test_results

    # Print summary
    log("\n=== Test results (BH-adj) ===")
    log(f"{'var':<10} {'H1 t':>7} {'H1 p_BH':>9} {'H2 t':>7} {'H2 p_BH':>9} {'H3 p_BH':>9}")
    for a in alt_vars:
        r = test_results[a]
        log(f"{a:<10} {r['H1_DM_t']:>7.3f} {r['H1_DM_p_BH']:>9.3f} "
            f"{r['H2_DM_t']:>7.3f} {r['H2_DM_p_BH']:>9.3f} "
            f"{r['H3_interaction_p_BH']:>9.3f}")

    # Verdict
    h1_passes = [a for a in alt_vars
                 if test_results[a]["H1_DM_t"] is not None
                 and np.isfinite(test_results[a]["H1_DM_t"])
                 and test_results[a]["H1_DM_t"] > 2.0
                 and test_results[a]["H1_DM_p_BH"] < 0.05]
    h2_passes = [a for a in alt_vars
                 if test_results[a]["H2_DM_t"] is not None
                 and np.isfinite(test_results[a]["H2_DM_t"])
                 and test_results[a]["H2_DM_t"] > 2.0
                 and test_results[a]["H2_DM_p_BH"] < 0.05]
    jump_conditional = [a for a in h1_passes if a not in h2_passes]

    if len(h1_passes) == 0 and len(h2_passes) == 0:
        verdict = "FULL_NULL"
    elif len(jump_conditional) > 0:
        verdict = "JUMP_CONDITIONAL_VALUE"
    elif len(h1_passes) > 0 and len(h2_passes) > 0:
        verdict = "REGIME_INDEPENDENT_VALUE"
    else:
        verdict = "MIXED"
    RESULTS["verdict"] = verdict
    RESULTS["h1_passes"] = h1_passes
    RESULTS["h2_passes"] = h2_passes
    RESULTS["jump_conditional"] = jump_conditional
    log(f"\nVERDICT: {verdict}")
    log(f"H1 passes (jump regime edge): {h1_passes}")
    log(f"H2 passes (non-jump regime edge): {h2_passes}")
    log(f"Jump-conditional (H1 PASS ∧ H2 FAIL): {jump_conditional}")

    # -----------------------------------------------------------------------
    # Robustness: repeat with 2.5σ and |VIX|>30 jump definitions.
    # Quick version: reuse GARCH fits (cache) and only redo matching + tests.
    # -----------------------------------------------------------------------
    log("\n=== Robustness: 2.5σ jumps ===")
    robustness_summary = {}
    for var_name, jumps_var in [
        ("robust_2p5sigma", jump_events["robust_2p5sigma"]),
        ("robust_absVIX30", jump_events["robust_absVIX30"]),
    ]:
        if len(jumps_var) < 30:
            robustness_summary[var_name] = {"skip": True, "n_jumps": len(jumps_var)}
            continue
        pairs_r, mq_r = find_matched_controls(df, jumps_var,
                                              exclude_buffer=5,
                                              vix_tol=2.0, vix_tol_loose=3.0,
                                              match_dow=True)
        log(f"  {var_name}: matched {len(pairs_r)}/{len(jumps_var)} "
            f"({len(pairs_r)/len(jumps_var):.1%})")
        pair_recs_r = []
        for jd, cd in pairs_r:
            ji = idx_map[jd]; ci = idx_map[cd]
            if ji >= len(df) - 1 or ci >= len(df) - 1:
                continue
            r2_j = (r_pct[ji + 1]) ** 2
            r2_c = (r_pct[ci + 1]) ** 2
            if not (np.isfinite(r2_j) and np.isfinite(r2_c)):
                continue
            fit_j = get_garch_fit(ji); fit_c = get_garch_fit(ci)
            if fit_j is None or fit_c is None: continue
            s_j = float(fit_j["__sigma2_next__"][ji])
            s_c = float(fit_c["__sigma2_next__"][ci])
            if not (np.isfinite(s_j) and s_j > 0 and np.isfinite(s_c) and s_c > 0):
                continue
            rec = {"loss_base_jump": float(qlike_loss(r2_j, s_j)),
                   "loss_base_control": float(qlike_loss(r2_c, s_c))}
            for a in alt_vars:
                coef_j = fit_j.get(a); coef_c = fit_c.get(a)
                x_j = df[a].iloc[ji]; x_c = df[a].iloc[ci]
                if coef_j is None or not np.isfinite(x_j):
                    aj = s_j
                else:
                    a1, b1, c1 = coef_j
                    v = a1 * s_j + b1 * x_j + c1
                    aj = float(v) if v > 0 else s_j
                if coef_c is None or not np.isfinite(x_c):
                    ac = s_c
                else:
                    a2, b2, c2 = coef_c
                    v = a2 * s_c + b2 * x_c + c2
                    ac = float(v) if v > 0 else s_c
                rec[f"loss_{a}_jump"] = float(qlike_loss(r2_j, aj))
                rec[f"loss_{a}_control"] = float(qlike_loss(r2_c, ac))
            pair_recs_r.append(rec)
        if len(pair_recs_r) < 20:
            robustness_summary[var_name] = {"skip": True,
                                            "n_pairs": len(pair_recs_r)}
            continue
        pdf_r = pd.DataFrame(pair_recs_r)
        tres = {}
        for a in alt_vars:
            t1, p1 = paired_dm(pdf_r["loss_base_jump"].values,
                               pdf_r[f"loss_{a}_jump"].values)
            t2, p2 = paired_dm(pdf_r["loss_base_control"].values,
                               pdf_r[f"loss_{a}_control"].values)
            tres[a] = {"H1_t": t1, "H1_p": p1, "H2_t": t2, "H2_p": p2,
                       "H1_delta_mean": float(np.nanmean(
                           pdf_r[f"loss_{a}_jump"].values -
                           pdf_r["loss_base_jump"].values))}
        robustness_summary[var_name] = {
            "n_jumps": len(jumps_var),
            "n_pairs": len(pair_recs_r),
            "match_rate": len(pairs_r) / len(jumps_var),
            "tests": tres,
        }
        log(f"  {var_name} H1 t-stats: " + ", ".join(
            f"{a}={tres[a]['H1_t']:+.2f}" for a in alt_vars))

    RESULTS["robustness"] = robustness_summary

    RESULTS["runtime_sec"] = time.time() - t0
    RESULTS["ended_utc"] = datetime.utcnow().isoformat() + "Z"
    return RESULTS


if __name__ == "__main__":
    results = run_experiment()
    out_json = OUT_DIR / "k1117_results.json"
    with open(out_json, "w") as f:
        json.dump(results, f, indent=2, default=str)
    log(f"Results saved -> {out_json}")
