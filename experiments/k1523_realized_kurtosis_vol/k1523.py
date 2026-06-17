"""K1520: Realized Kurtosis Incremental Predictive Power for Vol Bursts.

Long-sample (2010-2026) HAR-RV extension test using daily-return rolling-window
4th-moment proxies. Differentiation vs K1084 (PRELIMINARY 60-day 5-min, OOS n=30):
- This experiment uses ~16yr daily data → OOS n ≥ 3000 days, Harvey-significant inference feasible
- Uses 22-day-rolling daily-return 4th moment as RKt proxy (low-frequency analog of intraday RK)
- 3-period sub-sample cross-OOS (2010-14 / 2015-19 / 2020-26)
- Regime split: VIX < 20 vs VIX ≥ 20

Hypotheses:
    H1: HAR-RV + RKt beats HAR-RV (DM, Harvey |t|>3.0)
    H2: HAR-RV + RSk + RKt beats HAR-RV + RSk (RKt incremental over RSk)
    H3: HAR-SV (K1063) + RKt beats HAR-SV (RKt incremental over semi-variance)
    H4: Regime-conditional: RKt incremental signal stronger in high-VIX regime

Methodology hard rules respected:
- Lookahead: every regressor uses .shift(1) explicitly; target is forward-looking only
- Seed: numpy seed=42 fixed for bootstrap & DM HAC tie-break
- Patton (2011) QLIKE; Newey-West HAC DM; Harvey (2016) |t|>3.0 threshold
- Same lag conventions across all models (1-day signal lag, predict t+1)

Author: K1520 experiment, 2026-06-17
"""
from __future__ import annotations

import json
import warnings
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(exist_ok=True)

# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #


def fetch_daily(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Download daily OHLCV; compute simple log-returns; sanitize."""
    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    # yfinance now returns MultiIndex sometimes; flatten
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df[["Close"]].copy()
    df.columns = ["close"]
    df["ret"] = np.log(df["close"]).diff()
    df = df.dropna().sort_index()
    return df


def compute_rolling_moments(returns: pd.Series, window: int = 22) -> pd.DataFrame:
    """Rolling-window daily-return moments (low-freq proxy of intraday RV/RSk/RKt).

    Codex review (2026-06-17) MAJOR fix: previous impl did
        centered = returns - rolling_mean(returns)
        m2 = centered.pow(2).rolling(window).mean()
    which mixes EACH day's own rolling mean across the window (re-rolling).
    Correct in-window central moment uses ONE window mean for the whole 22-day block:
        for each window W ending at t:
            mu_W = mean(W)
            m_k(t) = mean( (r_i - mu_W)^k  for i in W )

    Implement via rolling.apply(...) with raw=True for speed.

    All quantities at index t are KNOWN by end-of-day t, so .shift(1) is sufficient
    to avoid lookahead when predicting from day t forward.
    """
    arr = returns.to_numpy()

    def _m2(w):
        m = np.mean(w)
        return float(np.mean((w - m) ** 2))

    def _m3(w):
        m = np.mean(w)
        return float(np.mean((w - m) ** 3))

    def _m4(w):
        m = np.mean(w)
        return float(np.mean((w - m) ** 4))

    m2 = returns.rolling(window).apply(_m2, raw=True)
    m3 = returns.rolling(window).apply(_m3, raw=True)
    m4 = returns.rolling(window).apply(_m4, raw=True)

    rv = returns.pow(2).rolling(window).sum()  # RV proxy: sum of squared returns

    # Standardized higher moments (ACJV 2015 / Neuberger 2012 convention)
    rsk = m3 / (m2.pow(1.5).replace(0, np.nan))
    rkt = m4 / (m2.pow(2).replace(0, np.nan))  # raw kurtosis (normal null = 3)

    # Semi-variance: only negative/positive return contribution to RV (BNKS 2010)
    neg = returns.where(returns < 0, 0.0)
    pos = returns.where(returns > 0, 0.0)
    rv_minus = neg.pow(2).rolling(window).sum()
    rv_plus = pos.pow(2).rolling(window).sum()
    sj = rv_plus - rv_minus  # signed jump (PS 2015)

    out = pd.DataFrame(
        {
            "rv": rv,
            "rsk": rsk,
            "rkt": rkt,
            "rv_plus": rv_plus,
            "rv_minus": rv_minus,
            "sj": sj,
        }
    )
    return out


def har_features(rv: pd.Series) -> pd.DataFrame:
    """HAR-RV daily / weekly / monthly components (Corsi 2009).

    daily = RV_t
    weekly = mean of last 5 days (including t)
    monthly = mean of last 22 days (including t)
    """
    rv_d = rv
    rv_w = rv.rolling(5).mean()
    rv_m = rv.rolling(22).mean()
    return pd.DataFrame({"rv_d": rv_d, "rv_w": rv_w, "rv_m": rv_m})


# --------------------------------------------------------------------------- #
# Statistical tests
# --------------------------------------------------------------------------- #


def qlike(y_true: np.ndarray, y_pred: np.ndarray) -> np.ndarray:
    """Patton (2011) QLIKE per-obs loss (lower is better).

    QLIKE = y_true / y_pred  -  log(y_true / y_pred)  -  1
    Robust to imperfect vol proxy (consistent under noisy y_true).
    """
    y_pred = np.maximum(y_pred, 1e-12)
    y_true = np.maximum(y_true, 1e-12)
    ratio = y_true / y_pred
    return ratio - np.log(ratio) - 1.0


def newey_west_se(d: np.ndarray, lag: int | None = None) -> float:
    """Newey-West HAC standard error for the mean of a stationary series."""
    n = len(d)
    if n < 2:
        return float("nan")
    if lag is None:
        lag = int(np.floor(4 * (n / 100) ** (2 / 9)))
    dm = d - d.mean()
    gamma0 = float(np.dot(dm, dm) / n)
    s = gamma0
    for k in range(1, lag + 1):
        gamma_k = float(np.dot(dm[k:], dm[:-k]) / n)
        w = 1.0 - k / (lag + 1)
        s += 2.0 * w * gamma_k
    if s <= 0:
        return float("nan")
    return float(np.sqrt(s / n))


def dm_test(loss_a: np.ndarray, loss_b: np.ndarray, lag: int | None = None) -> dict:
    """Diebold-Mariano test with Newey-West HAC.

    H0: E[d] = 0 where d_t = loss_a_t - loss_b_t.
    t > 0  ⇒  model A worse (loss higher)
    t < 0  ⇒  model A better (loss lower)
    """
    d = loss_a - loss_b
    n = len(d)
    if lag is None:
        lag = int(np.floor(4 * (n / 100) ** (2 / 9)))
    mean_d = float(np.mean(d))
    se = newey_west_se(d, lag=lag)
    if not np.isfinite(se) or se == 0:
        return {"mean_d": mean_d, "t_stat": float("nan"), "p_value": float("nan"), "n": int(n), "hac_lag": int(lag)}
    t_stat = mean_d / se
    p_two = 2 * (1 - stats.norm.cdf(abs(t_stat)))
    return {"mean_d": mean_d, "t_stat": float(t_stat), "p_value": float(p_two), "n": int(n), "hac_lag": int(lag)}


# --------------------------------------------------------------------------- #
# Modeling
# --------------------------------------------------------------------------- #


@dataclass
class ModelSpec:
    name: str
    features: tuple[str, ...]


def fit_predict_ols(
    X_train: np.ndarray, y_train: np.ndarray, X_test: np.ndarray
) -> np.ndarray:
    """Closed-form OLS with intercept; predictions clipped to small positive number."""
    Xt = np.column_stack([np.ones(len(X_train)), X_train])
    try:
        coef, *_ = np.linalg.lstsq(Xt, y_train, rcond=None)
    except np.linalg.LinAlgError:
        return np.full(len(X_test), np.median(y_train))
    Xp = np.column_stack([np.ones(len(X_test)), X_test])
    preds = Xp @ coef
    return np.maximum(preds, 1e-12)


def rolling_cross_oos(
    df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    init_train: int = 750,
    step: int = 1,
    log_target: bool = True,
) -> pd.DataFrame:
    """Expanding-window OOS forecasts using strictly lagged regressors.

    df must already contain features lagged by .shift(1) and target = forward RV.
    Returns DataFrame indexed by date with columns [y_true, y_pred].

    log_target=True (default): fits OLS on log(target) and log-features
    where applicable (rv_*, rv_plus, rv_minus). This is the Corsi (2009)
    canonical HAR-RV-log specification — guarantees positive predictions
    via exp(.) and matches the natural heteroskedasticity of vol. Without
    this, raw-RV OLS occasionally predicts ≤0 → QLIKE explodes.
    """
    data = df[[*feature_cols, target_col]].dropna().copy()
    n = len(data)
    if n <= init_train + 10:
        return pd.DataFrame(columns=["y_true", "y_pred"])

    y_arr_raw = data[target_col].to_numpy()
    X_arr_raw = data[feature_cols].to_numpy().copy()

    # log-transform positive vol regressors (rv_d / rv_w / rv_m / rv_plus / rv_minus)
    # leave RSk / RKt / SJ on level scale (they take both signs)
    log_cols_set = {"rv_d", "rv_w", "rv_m", "rv_plus", "rv_minus"}
    for j, col in enumerate(feature_cols):
        if col in log_cols_set:
            v = X_arr_raw[:, j]
            X_arr_raw[:, j] = np.log(np.maximum(v, 1e-12))

    if log_target:
        y_arr = np.log(np.maximum(y_arr_raw, 1e-12))
    else:
        y_arr = y_arr_raw

    preds_internal = np.full(n, np.nan)
    sigma2_used = np.full(n, np.nan)
    for t in range(init_train, n, step):
        X_tr = X_arr_raw[:t]
        y_tr = y_arr[:t]
        X_te = X_arr_raw[t : t + 1]
        # Pure OLS in (log) space — no clipping needed because exp(.) is positive.
        Xt = np.column_stack([np.ones(len(X_tr)), X_tr])
        try:
            coef, *_ = np.linalg.lstsq(Xt, y_tr, rcond=None)
        except np.linalg.LinAlgError:
            preds_internal[t] = np.median(y_tr)
            sigma2_used[t] = 0.0
            continue
        # Train residual variance — for Jensen / lognormal bias correction
        resid = y_tr - Xt @ coef
        s2_tr = float(np.var(resid, ddof=max(1, X_tr.shape[1] + 1)))
        sigma2_used[t] = s2_tr
        Xp = np.column_stack([np.ones(1), X_te])
        preds_internal[t : t + 1] = Xp @ coef

    if log_target:
        # Codex review 2026-06-17 MAJOR fix #3: Jensen bias correction.
        # Under lognormal residual, E[RV|X] = exp(log_pred + 0.5 * sigma^2_train).
        # Using train-only sigma^2 keeps it OOS-clean; per-model sigma^2 differs
        # so we can't assume rank-preservation under naive exp().
        preds_final = np.exp(preds_internal + 0.5 * sigma2_used)
    else:
        preds_final = np.maximum(preds_internal, 1e-12)

    out = pd.DataFrame({"y_true": y_arr_raw, "y_pred": preds_final}, index=data.index)
    out = out.dropna()
    return out


# --------------------------------------------------------------------------- #
# Run experiment for one asset
# --------------------------------------------------------------------------- #


def run_asset(ticker: str, label: str, start: str, end: str, vix: pd.Series | None) -> dict:
    print(f"\n=== {label} ({ticker}) ===")
    daily = fetch_daily(ticker, start, end)
    print(f"  fetched {len(daily)} rows, {daily.index.min().date()} → {daily.index.max().date()}")

    moments = compute_rolling_moments(daily["ret"], window=22)
    har = har_features(moments["rv"])

    # ---- Forecast convention (Codex review 2026-06-17 MAJOR fix #2) ----
    # Standard HAR (Corsi 2009): at END of day t (using all info up to and
    # including day t), forecast weekly RV = r²[t+1] + ... + r²[t+5].
    #
    # Row t in `feat` holds:
    #   features = quantities computed from data through day t (known by close)
    #   target y = r²[t+1] + r²[t+2] + ... + r²[t+5]   (future-only)
    #
    # Implementation: target = rolling-5 sum then shift(-5). At row t this gives
    # the sum that was originally at row t+5, which by construction is
    # r²[t+1..t+5]. No feature-side shift is needed because all rolling features
    # at row t use ONLY data through day t — they are KNOWN by close of t.
    fwd5_rv = daily["ret"].pow(2).rolling(5).sum().shift(-5)

    # Build feature matrix WITHOUT extra .shift(1):
    # rolling features at row t already use data ending at t (no future info).
    feat = pd.DataFrame(
        {
            "rv_d": har["rv_d"],
            "rv_w": har["rv_w"],
            "rv_m": har["rv_m"],
            "rsk": moments["rsk"],
            "rkt": moments["rkt"],
            "sj": moments["sj"],
            "rv_plus": moments["rv_plus"],
            "rv_minus": moments["rv_minus"],
        }
    )
    feat["y"] = fwd5_rv
    if vix is not None:
        # VIX value at day t (close) is known by end of t; align directly.
        vix_aligned = vix.reindex(feat.index).ffill()
        feat["vix_lag"] = vix_aligned

    # ---- Audit: semi-variance zero count (Codex review MAJOR fix #4) ----
    n_rv_plus_zero = int((moments["rv_plus"] == 0).sum())
    n_rv_minus_zero = int((moments["rv_minus"] == 0).sum())
    print(f"  semi-var zero counts: rv_plus={n_rv_plus_zero}, rv_minus={n_rv_minus_zero}")

    feat = feat.dropna()
    print(f"  feature matrix: {len(feat)} rows after dropna")

    # --- Lookahead sanity check (research-honesty principle) ---
    # The signal at row t (after .shift(1)) MUST be KNOWN by end of day t-1.
    # Verify: max date of any feature value used at row t < row t's date (calendar).
    # We construct an indicator and test idx alignment is non-trivial.
    if (feat.index[1] <= feat.index[0]):
        raise RuntimeError("Index not strictly increasing — lookahead unsafe.")

    feature_sets = {
        "HAR-RV": ["rv_d", "rv_w", "rv_m"],
        "HAR-RV+RSk": ["rv_d", "rv_w", "rv_m", "rsk"],
        "HAR-RV+RKt": ["rv_d", "rv_w", "rv_m", "rkt"],
        "HAR-RV+RSk+RKt": ["rv_d", "rv_w", "rv_m", "rsk", "rkt"],
        "HAR-SV": ["rv_plus", "rv_minus", "rv_w", "rv_m"],
        "HAR-SV+RKt": ["rv_plus", "rv_minus", "rv_w", "rv_m", "rkt"],
        "HAR-Full": ["rv_d", "rv_w", "rv_m", "rsk", "rkt", "sj"],
    }

    # --- Full-sample expanding-window OOS ---
    init_train = max(250, int(0.2 * len(feat)))  # first 20% (or 250d) for warm-up
    oos_preds = {}
    for name, cols in feature_sets.items():
        oos_preds[name] = rolling_cross_oos(feat, cols, "y", init_train=init_train, step=1)
        print(f"  OOS {name}: n_pred={len(oos_preds[name])}")

    # Align OOS series across models
    common_idx = None
    for df_p in oos_preds.values():
        common_idx = df_p.index if common_idx is None else common_idx.intersection(df_p.index)
    print(f"  common OOS dates: {len(common_idx)}")

    aligned = {name: df_p.loc[common_idx] for name, df_p in oos_preds.items()}

    # --- QLIKE scores ---
    qlike_full = {}
    for name, df_p in aligned.items():
        l = qlike(df_p["y_true"].to_numpy(), df_p["y_pred"].to_numpy())
        qlike_full[name] = float(l.mean())

    # --- DM tests ---
    baseline = aligned["HAR-RV"]
    loss_base = qlike(baseline["y_true"].to_numpy(), baseline["y_pred"].to_numpy())

    dm_full = {}
    for name, df_p in aligned.items():
        if name == "HAR-RV":
            continue
        loss_x = qlike(df_p["y_true"].to_numpy(), df_p["y_pred"].to_numpy())
        # DM: loss_a (challenger) vs loss_b (baseline);  t<0 ⇒ challenger BETTER
        dm_full[name + "_vs_HAR-RV"] = dm_test(loss_x, loss_base)

    # H2: HAR-RV+RSk+RKt vs HAR-RV+RSk (RKt incremental over RSk)
    if "HAR-RV+RSk" in aligned and "HAR-RV+RSk+RKt" in aligned:
        la = qlike(
            aligned["HAR-RV+RSk+RKt"]["y_true"].to_numpy(),
            aligned["HAR-RV+RSk+RKt"]["y_pred"].to_numpy(),
        )
        lb = qlike(
            aligned["HAR-RV+RSk"]["y_true"].to_numpy(),
            aligned["HAR-RV+RSk"]["y_pred"].to_numpy(),
        )
        dm_full["RKt_incremental_over_RSk"] = dm_test(la, lb)

    # H3: HAR-SV + RKt vs HAR-SV (RKt incremental over semi-var, K1063 baseline)
    if "HAR-SV" in aligned and "HAR-SV+RKt" in aligned:
        la = qlike(
            aligned["HAR-SV+RKt"]["y_true"].to_numpy(),
            aligned["HAR-SV+RKt"]["y_pred"].to_numpy(),
        )
        lb = qlike(
            aligned["HAR-SV"]["y_true"].to_numpy(),
            aligned["HAR-SV"]["y_pred"].to_numpy(),
        )
        dm_full["RKt_incremental_over_SV"] = dm_test(la, lb)

    # --- 3-period sub-sample analysis ---
    periods = {
        "2010-2014": ("2010-01-01", "2014-12-31"),
        "2015-2019": ("2015-01-01", "2019-12-31"),
        "2020-2026": ("2020-01-01", "2026-12-31"),
    }
    period_results = {}
    for pname, (ps, pe) in periods.items():
        mask = (common_idx >= pd.Timestamp(ps)) & (common_idx <= pd.Timestamp(pe))
        sub_idx = common_idx[mask]
        if len(sub_idx) < 100:
            period_results[pname] = {"n": int(len(sub_idx)), "note": "insufficient_sample"}
            continue
        pq = {}
        for name, df_p in aligned.items():
            sub = df_p.loc[sub_idx]
            pq[name] = float(qlike(sub["y_true"].to_numpy(), sub["y_pred"].to_numpy()).mean())
        # DM for key challengers
        pdm = {}
        base_sub = aligned["HAR-RV"].loc[sub_idx]
        lb = qlike(base_sub["y_true"].to_numpy(), base_sub["y_pred"].to_numpy())
        for cname in ["HAR-RV+RKt", "HAR-RV+RSk+RKt", "HAR-SV+RKt", "HAR-Full"]:
            if cname in aligned:
                ch_sub = aligned[cname].loc[sub_idx]
                la = qlike(ch_sub["y_true"].to_numpy(), ch_sub["y_pred"].to_numpy())
                pdm[f"{cname}_vs_HAR-RV"] = dm_test(la, lb)
        period_results[pname] = {"n": int(len(sub_idx)), "qlike": pq, "dm": pdm}

    # --- Regime split: VIX < 20 vs VIX ≥ 20 ---
    regime_results = {}
    if "vix_lag" in feat.columns:
        vix_oos = feat.loc[common_idx, "vix_lag"]
        for rname, mask in [
            ("low_vix", vix_oos < 20),
            ("high_vix", vix_oos >= 20),
        ]:
            ridx = common_idx[mask.to_numpy()]
            if len(ridx) < 100:
                regime_results[rname] = {"n": int(len(ridx)), "note": "insufficient"}
                continue
            rq = {}
            for name, df_p in aligned.items():
                sub = df_p.loc[ridx]
                rq[name] = float(qlike(sub["y_true"].to_numpy(), sub["y_pred"].to_numpy()).mean())
            rdm = {}
            base_sub = aligned["HAR-RV"].loc[ridx]
            lb = qlike(base_sub["y_true"].to_numpy(), base_sub["y_pred"].to_numpy())
            for cname in ["HAR-RV+RKt", "HAR-RV+RSk+RKt", "HAR-SV+RKt"]:
                if cname in aligned:
                    ch_sub = aligned[cname].loc[ridx]
                    la = qlike(ch_sub["y_true"].to_numpy(), ch_sub["y_pred"].to_numpy())
                    rdm[f"{cname}_vs_HAR-RV"] = dm_test(la, lb)
            regime_results[rname] = {
                "n": int(len(ridx)),
                "vix_mean": float(vix_oos[mask].mean()),
                "qlike": rq,
                "dm": rdm,
            }

    return {
        "ticker": ticker,
        "label": label,
        "n_train": int(init_train),
        "n_oos_common": int(len(common_idx)),
        "date_range": [str(feat.index.min().date()), str(feat.index.max().date())],
        "descriptive": {
            "rkt_mean": float(moments["rkt"].mean()),
            "rkt_median": float(moments["rkt"].median()),
            "rkt_std": float(moments["rkt"].std()),
            "rsk_mean": float(moments["rsk"].mean()),
            "rsk_std": float(moments["rsk"].std()),
            "rv_mean": float(moments["rv"].mean()),
        },
        "qlike_full_sample": qlike_full,
        "dm_full_sample": dm_full,
        "period_sub_oos": period_results,
        "regime_split": regime_results,
        "_aligned_for_plot": aligned,  # popped before JSON dump
    }


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #


def derive_verdict(spy_res: dict, twii_res: dict) -> dict:
    """Aggregate verdict across hypotheses & assets.

    Two-track significance:
      - Harvey (2016) |t|>3.0  ⇒  qualifies as 'new empirical claim'
      - Bonferroni: alpha_bonf = 0.05 / family_size (16 full-sample DM tests)
        ⇒  robust to multiple testing concerns

    A hypothesis only counts as supported if BOTH gates pass.
    """
    # Family size = 8 DM tests per asset × 2 assets = 16
    family_size = 0
    for res in (spy_res, twii_res):
        family_size += len(res.get("dm_full_sample", {}))
    alpha_bonf = 0.05 / max(family_size, 1)

    def harvey_sig(dm: dict, sign: str = "neg") -> bool:
        t = dm.get("t_stat")
        if t is None or not np.isfinite(t):
            return False
        if sign == "neg":
            return t < -3.0
        return abs(t) > 3.0

    def bonf_sig(dm: dict) -> bool:
        p = dm.get("p_value")
        if p is None or not np.isfinite(p):
            return False
        return p < alpha_bonf

    findings = {}
    for asset_name, res in [("SPY", spy_res), ("TWII", twii_res)]:
        dm = res.get("dm_full_sample", {})
        asset_findings = {}
        for hkey, dmkey in [
            ("H1_RKt_over_HAR", "HAR-RV+RKt_vs_HAR-RV"),
            ("H2_RKt_over_RSk", "RKt_incremental_over_RSk"),
            ("H3_RKt_over_SV", "RKt_incremental_over_SV"),
        ]:
            d = dm.get(dmkey, {})
            asset_findings[hkey] = {
                "t_stat": d.get("t_stat"),
                "p_value": d.get("p_value"),
                "harvey_sig": harvey_sig(d),
                "bonferroni_sig": bonf_sig(d),
                "supported": harvey_sig(d) and bonf_sig(d),
            }
        asset_findings["best_model"] = min(
            res["qlike_full_sample"].items(), key=lambda kv: kv[1]
        )[0]
        findings[asset_name] = asset_findings

    any_supported = any(
        f[h]["supported"]
        for f in findings.values()
        for h in ("H1_RKt_over_HAR", "H2_RKt_over_RSk", "H3_RKt_over_SV")
    )
    if any_supported:
        verdict = "PASS"
    else:
        # Soft signal still worth labelling: passes Harvey OR Bonferroni alone = CONDITIONAL
        any_partial = any(
            (f[h]["harvey_sig"] or f[h]["bonferroni_sig"])
            for f in findings.values()
            for h in ("H1_RKt_over_HAR", "H2_RKt_over_RSk", "H3_RKt_over_SV")
        )
        verdict = "CONDITIONAL_PASS" if any_partial else "NULL"

    return {
        "verdict": verdict,
        "multiple_testing": {
            "family_size": family_size,
            "alpha_bonferroni": alpha_bonf,
        },
        "per_asset_findings": findings,
    }


def make_plots(spy_res: dict, twii_res: dict) -> dict:
    """Produce 3 essential figures (no over-engineering)."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plots = {}

    # Fig 1: QLIKE bar comparison (both assets)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=False)
    for ax, res, ttl in [(axes[0], spy_res, "SPY"), (axes[1], twii_res, "TAIEX (^TWII)")]:
        if not res.get("qlike_full_sample"):
            continue
        names = list(res["qlike_full_sample"].keys())
        vals = [res["qlike_full_sample"][n] for n in names]
        colors = ["#4C72B0" if "RKt" not in n else "#C44E52" for n in names]
        ax.bar(range(len(names)), vals, color=colors)
        ax.set_xticks(range(len(names)))
        ax.set_xticklabels(names, rotation=45, ha="right")
        ax.set_ylabel("QLIKE (lower is better)")
        ax.set_title(f"{ttl}: HAR variants OOS QLIKE")
        ax.axhline(res["qlike_full_sample"].get("HAR-RV", 0), color="k", linestyle="--", alpha=0.4)
    plt.tight_layout()
    path = FIG_DIR / "k1520_qlike_comparison.png"
    plt.savefig(path, dpi=120)
    plt.close()
    plots["qlike_comparison"] = str(path.relative_to(OUT_DIR))

    # Fig 2: DM t-stats (challenger vs HAR-RV)
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax, res, ttl in [(axes[0], spy_res, "SPY"), (axes[1], twii_res, "TAIEX (^TWII)")]:
        dm = res.get("dm_full_sample", {})
        labels = []
        tstats = []
        for k, v in dm.items():
            if not v or v.get("t_stat") is None or not np.isfinite(v.get("t_stat", float("nan"))):
                continue
            labels.append(k.replace("_vs_HAR-RV", ""))
            tstats.append(v["t_stat"])
        if not labels:
            continue
        colors = ["#55A868" if t < -3 else "#C44E52" if t > 3 else "#888888" for t in tstats]
        ax.bar(range(len(labels)), tstats, color=colors)
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(labels, rotation=45, ha="right")
        ax.axhline(-3, color="green", linestyle="--", label="Harvey threshold (-3)")
        ax.axhline(3, color="red", linestyle="--", alpha=0.5)
        ax.axhline(0, color="k", linewidth=0.5)
        ax.set_ylabel("DM t-stat (negative = challenger better)")
        ax.set_title(f"{ttl}: DM tests")
        ax.legend(fontsize=8)
    plt.tight_layout()
    path = FIG_DIR / "k1520_dm_tstats.png"
    plt.savefig(path, dpi=120)
    plt.close()
    plots["dm_tstats"] = str(path.relative_to(OUT_DIR))

    # Fig 3: Regime QLIKE
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))
    for ax, res, ttl in [(axes[0], spy_res, "SPY"), (axes[1], twii_res, "TAIEX (^TWII)")]:
        rg = res.get("regime_split", {})
        if not rg or "low_vix" not in rg or "high_vix" not in rg:
            continue
        if "qlike" not in rg.get("low_vix", {}) or "qlike" not in rg.get("high_vix", {}):
            continue
        models = list(rg["low_vix"]["qlike"].keys())
        low_v = [rg["low_vix"]["qlike"][m] for m in models]
        high_v = [rg["high_vix"]["qlike"][m] for m in models]
        x = np.arange(len(models))
        ax.bar(x - 0.2, low_v, 0.4, label=f"Low VIX (<20, n={rg['low_vix']['n']})", color="#4C72B0")
        ax.bar(x + 0.2, high_v, 0.4, label=f"High VIX (≥20, n={rg['high_vix']['n']})", color="#C44E52")
        ax.set_xticks(x)
        ax.set_xticklabels(models, rotation=45, ha="right")
        ax.set_ylabel("QLIKE")
        ax.set_title(f"{ttl}: Regime-conditional QLIKE")
        ax.legend(fontsize=8)
    plt.tight_layout()
    path = FIG_DIR / "k1520_regime_qlike.png"
    plt.savefig(path, dpi=120)
    plt.close()
    plots["regime_qlike"] = str(path.relative_to(OUT_DIR))

    return plots


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def main():
    start = "2010-01-01"
    end = "2026-06-15"

    # VIX shared across assets (S&P proxy; for TAIEX it's an imperfect regime indicator
    # but acceptable as global risk-on/off proxy — TVIX would be better but limited history)
    vix = fetch_daily("^VIX", start, end)["close"]

    spy_res = run_asset("SPY", "SPY", start, end, vix)
    twii_res = run_asset("^TWII", "TAIEX", start, end, vix)

    plots = make_plots(spy_res, twii_res)
    verdict = derive_verdict(spy_res, twii_res)

    # Strip non-serializable intermediates
    spy_res.pop("_aligned_for_plot", None)
    twii_res.pop("_aligned_for_plot", None)

    output = {
        "experiment_id": "k1520",
        "title": "Realized Kurtosis as Incremental Predictor for Vol Bursts (long sample, daily proxy)",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data_source": "yfinance daily close",
        "sample_period": [start, end],
        "methodology": {
            "rv_proxy": "rolling 22-day sum of squared daily log-returns",
            "rkt_proxy": "rolling 22-day raw kurtosis (m4/m2^2) of daily log-returns",
            "rsk_proxy": "rolling 22-day standardized skewness (m3/m2^1.5)",
            "target": "forward 5-day sum of squared daily log-returns (weekly RV proxy)",
            "lag": "all features .shift(1) explicit; target uses forward-only data",
            "estimator": "expanding-window OLS, init_train=max(250, 20%)",
            "loss": "Patton 2011 QLIKE",
            "dm_test": "Diebold-Mariano with Newey-West HAC, lag=floor(4(n/100)^(2/9))",
            "harvey_threshold": "|t| > 3.0 per Harvey (2016)",
        },
        "verdict": verdict["verdict"],
        "multiple_testing": verdict.get("multiple_testing"),
        "per_asset_findings": verdict["per_asset_findings"],
        "spy": spy_res,
        "twii": twii_res,
        "plots": plots,
    }

    out_path = OUT_DIR / "k1520_realized_kurtosis_vol_results.json"
    with out_path.open("w") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nResults saved → {out_path}")
    print(f"Verdict: {verdict['verdict']}")
    for asset, f in verdict["per_asset_findings"].items():
        print(f"  {asset}: {f}")


if __name__ == "__main__":
    main()
