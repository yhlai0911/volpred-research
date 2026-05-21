#!/usr/bin/env python3
"""
tsmc_vt_strategy.py — Paper 2 (taiwan-vt) Sec 4.5 backfill

Reproduces the two unbacked numbers in body.tex L440-444:

  (A) "TSMC VT achieves a Sharpe ratio of 1.121"           (Sec 4.5 L440)
  (B) "TSMC explains 52.5% of 0050.TW return variance"      (Sec 4.5 L444)

Lookahead discipline (per CLAUDE.md L46, .claude/rules/experiments.md):
  - VT signal: σ_t_hat = f(returns_{≤t-1})
  - Portfolio weight w_t = (target_vol / σ_t_hat).clip(0,1).shift(1)
  - PnL_t = w_t × return_t  → three-stage lag explicit
  - All GARCH fits use train_data ending at i-1 then forecast h_i
  - Variance share regression is in-sample OLS R² (no lookahead concern;
    full-sample contemporaneous OLS by design)

Spec alignment with K1175 (Paper 2 Table 4 canonical VT):
  - target_vol = 10% annualized
  - GARCH(1,1) and GJR-GARCH(1,1): vol="Garch", mean="Zero", dist="normal"
  - Rolling window = 2000, refit_every = 21 trading days (~1 month)
  - OOS start for GARCH/GJR = 2020-01-01 (per paper Table 3 note)
  - EWMA: λ=0.94 (RiskMetrics)
  - Transaction cost = 5 bps per turnover unit
  - Annualization = sqrt(252)
  - Returns: close-to-close log returns from `2330_tw_close` (TSMC) and
    `0050_tw_close` (0050.TW), pinned snapshot 2008-2026

Sensitivity sweep (no cherry-pick — all specs reported):
  - estimator: GARCH(1,1), GJR-GARCH(1,1), EWMA(λ=0.94), realized 21d
  - target_vol: 10%, 15%, 20%
  - sample: GARCH OOS 2020-2026, full 2008-2026 (EWMA only)
  - bootstrap 95% CI on Sharpe (B=500, seed=42, block=21)

Variance share (Number B):
  - OLS: r_0050,t = α + β × r_TSMC,t + ε_t
  - R² is reported on multiple sample windows: full 2008-2026, 2010-2026,
    2014-2024, 2020-2026
  - Also report R² under: (a) intercept on/off, (b) raw vs log returns

Data source rule (per .claude/rules/paper-workflow.md hard rule #1):
  - Reads PINNED snapshot CSV only:
      paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
  - NO live yfinance call.

Outputs:
  tsmc_vt_strategy_results.json  — primary + sweep + verdict per number
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd

try:
    from arch import arch_model
except ImportError:
    print("ERROR: `arch` package required (pip install arch)", file=sys.stderr)
    sys.exit(2)

# K1175 spec alignment: 0050.TW snapshot has 2014-01-02 1:4 split artifact that
# manifests as a fake -75% return on that day. K1175 uses src/volpred/utils.py
# clean_tw50_data to repair. TSMC (2330.TW) has NO split artifact in the same
# snapshot (verified empirically: 2013-12-31/2014-01-02 ratio=1.01).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
from volpred.utils import clean_tw50_data  # noqa: E402

SEED = 42
rng = np.random.default_rng(SEED)

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
PAPER_DATA_DIR = REPO_ROOT / "paper" / "taiwan-vt" / "data"
MAIN_CSV = PAPER_DATA_DIR / "0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
RESULT_JSON = SCRIPT_DIR / "tsmc_vt_strategy_results.json"

# Paper Sec 4.5 targets
PAPER_TSMC_SHARPE = 1.121
PAPER_VAR_SHARE = 0.525
PAPER_0050_VT_SHARPE = 0.936  # contextual: also reported in L440

# Tolerances
TOL_SHARPE_PASS = 0.05      # ±0.05 → byte_match
TOL_SHARPE_SMALL = 0.10
TOL_VARSHARE_PASS = 0.02    # ±2 percentage points
TOL_VARSHARE_SMALL = 0.05

# Strategy spec (mirrors K1175)
TARGET_VOL = 0.10
GARCH_WINDOW = 2000
REFIT_EVERY = 21
OOS_START_GARCH = "2020-01-01"
OOS_START_BH_EWMA = "2010-01-01"  # K1175 BH window
EWMA_LAMBDA = 0.94
TX_COST = 0.0005  # 5 bps

# Bootstrap
BOOTSTRAP_B = 500
BOOTSTRAP_BLOCK = 21


def load_snapshot() -> pd.DataFrame:
    if not MAIN_CSV.exists():
        raise FileNotFoundError(f"Pinned snapshot missing: {MAIN_CSV}")
    df = pd.read_csv(MAIN_CSV, parse_dates=["date"])
    df = df.drop_duplicates(subset=["date"], keep="first")
    df = df.set_index("date").sort_index()
    return df


def compute_log_returns(close: pd.Series) -> pd.Series:
    """Close-to-close log returns (raw, not percent). USED FOR VARIANCE-SHARE OLS."""
    return np.log(close / close.shift(1)).dropna()


def compute_simple_returns(close: pd.Series) -> pd.Series:
    """Close-to-close simple returns. K1175 uses pct_change for VT backtest engine."""
    return close.pct_change().dropna()


def compute_ewma_vol(returns: pd.Series, lam: float = EWMA_LAMBDA) -> pd.Series:
    """EWMA annualized volatility. Identical recursion to K1175.

    σ²_t = λ × σ²_{t-1} + (1-λ) × r²_{t-1}
    All inputs strictly before t.
    """
    r = returns.dropna()
    var = pd.Series(index=r.index, dtype=float)
    var.iloc[0] = float(r.iloc[0] ** 2)
    for i in range(1, len(r)):
        var.iloc[i] = lam * var.iloc[i - 1] + (1 - lam) * (r.iloc[i - 1] ** 2)
    vol_ann = np.sqrt(var) * np.sqrt(252)
    return vol_ann


def garch_oos_forecast(
    returns: pd.Series,
    oos_start: str,
    window: int = GARCH_WINDOW,
    refit_every: int = REFIT_EVERY,
    gjr: bool = False,
) -> pd.Series:
    """Day-by-day OOS GARCH(1,1) or GJR-GARCH(1,1) forecast.

    Strict lookahead discipline: at date t, the forecast uses train_data ending
    at returns.iloc[i-1] (i.e., t_{-1}). The h_t formula uses last_r and last_h
    from the trained period; we never feed returns[t] into the recursion before
    forecasting h_t.

    Identical to K1175's gjr_garch_oos_forecast(); copied for self-containment.
    """
    returns = returns.dropna()
    oos_dates = returns.index[returns.index >= oos_start]
    forecasts = pd.Series(index=oos_dates, dtype=float)

    last_fit_idx = -refit_every - 1
    last_h = None
    last_r = None
    omega = alpha = gamma_gjr = beta = 0.0

    for date in oos_dates:
        date_loc = returns.index.get_loc(date)
        train_end = date_loc  # exclusive: uses data strictly before date
        train_start = max(0, train_end - window)
        train_data = returns.iloc[train_start:train_end]

        if (date_loc - last_fit_idx) >= refit_every or last_h is None:
            try:
                am = arch_model(
                    train_data * 100, vol="Garch", p=1,
                    o=1 if gjr else 0, q=1, mean="Zero", dist="normal",
                )
                res = am.fit(disp="off", show_warning=False)
                omega = float(res.params.get("omega", 0))
                alpha = float(res.params.get("alpha[1]", 0))
                gamma_gjr = float(res.params.get("gamma[1]", 0)) if gjr else 0.0
                beta = float(res.params.get("beta[1]", 0))
                last_h = float(res.conditional_volatility.iloc[-1]) ** 2
                last_r = float(train_data.iloc[-1] * 100)
                last_fit_idx = date_loc
            except Exception:
                forecasts.loc[date] = np.nan
                continue

        if last_h is not None and last_r is not None:
            if gjr:
                indicator = 1.0 if last_r < 0 else 0.0
                h_t = omega + alpha * last_r ** 2 + gamma_gjr * indicator * last_r ** 2 + beta * last_h
            else:
                h_t = omega + alpha * last_r ** 2 + beta * last_h
            vol_daily = np.sqrt(max(h_t, 1e-10)) / 100
            vol_ann = vol_daily * np.sqrt(252)
            forecasts.loc[date] = vol_ann
            last_h = h_t
            # Advance last_r to current observation for next iteration's recursion
            last_r = float(returns.iloc[date_loc] * 100) if date_loc < len(returns) else last_r

    return forecasts.dropna()


def backtest_strategy(
    returns: pd.Series, weights: pd.Series, name: str, tx_cost: float = TX_COST
) -> dict:
    """VT backtest. weights MUST be already shift(1)-lagged before calling.

    Identical to K1175's backtest_strategy().
    """
    idx = returns.index.intersection(weights.dropna().index)
    r = returns.loc[idx]
    w = weights.loc[idx]

    w_change = w.diff().abs().fillna(0)
    tc = w_change * tx_cost
    port_ret = (w * r - tc).dropna()

    if len(port_ret) < 100:
        return {"name": name, "error": "insufficient data", "n_days": int(len(port_ret))}

    n_years = len(port_ret) / 252
    ann_ret = (1 + port_ret).prod() ** (1 / n_years) - 1
    ann_vol = port_ret.std() * np.sqrt(252)
    sharpe = float(ann_ret / ann_vol) if ann_vol > 0 else 0.0

    cum = (1 + port_ret).cumprod()
    drawdown = cum / cum.cummax() - 1
    mdd = float(drawdown.min())

    return {
        "name": name,
        "n_days": int(len(port_ret)),
        "period": f"{port_ret.index[0].date()} to {port_ret.index[-1].date()}",
        "ann_return_pct": round(float(ann_ret) * 100, 4),
        "ann_vol_pct": round(float(ann_vol) * 100, 4),
        "sharpe": round(sharpe, 4),
        "mdd_pct": round(mdd * 100, 4),
        "_port_ret": port_ret,  # private — stripped before JSON dump
    }


def block_bootstrap_sharpe(
    port_ret: pd.Series, B: int = BOOTSTRAP_B, block: int = BOOTSTRAP_BLOCK
) -> dict:
    """Stationary block bootstrap on daily returns; report 95% CI for Sharpe."""
    n = len(port_ret)
    r = port_ret.to_numpy()
    sharpes = np.empty(B)
    n_blocks = int(np.ceil(n / block))
    for b in range(B):
        starts = rng.integers(0, n, size=n_blocks)
        idx = np.concatenate([np.arange(s, s + block) % n for s in starts])[:n]
        sample = r[idx]
        # Use geometric annualized return to match backtest_strategy() headline Sharpe
        n_s = len(sample)
        n_years_b = n_s / 252
        ann_ret_b = (1 + sample).prod() ** (1 / n_years_b) - 1
        ann_vol_b = sample.std() * np.sqrt(252)
        sharpes[b] = float(ann_ret_b / ann_vol_b) if ann_vol_b > 0 else 0.0
    return {
        "boot_B": B,
        "boot_block": block,
        "boot_seed": SEED,
        "sharpe_mean": float(np.mean(sharpes)),
        "sharpe_ci95_low": float(np.percentile(sharpes, 2.5)),
        "sharpe_ci95_high": float(np.percentile(sharpes, 97.5)),
    }


def verdict_sharpe(observed: float, target: float) -> tuple[str, float]:
    delta = observed - target
    if abs(delta) <= TOL_SHARPE_PASS:
        return "PASS", delta
    if abs(delta) <= TOL_SHARPE_SMALL:
        return "DRIFT_SMALL", delta
    return "DRIFT_LARGE", delta


def verdict_varshare(observed: float, target: float) -> tuple[str, float]:
    delta = observed - target
    if abs(delta) <= TOL_VARSHARE_PASS:
        return "PASS", delta
    if abs(delta) <= TOL_VARSHARE_SMALL:
        return "DRIFT_SMALL", delta
    return "DRIFT_LARGE", delta


# ─────────────────────────────────────────────────────────────────────────────
# Variance share (Number B)
# ─────────────────────────────────────────────────────────────────────────────

def ols_r_squared(y: np.ndarray, x: np.ndarray, intercept: bool = True) -> dict:
    """OLS R² of y on x. Returns r2, beta, alpha, n."""
    mask = np.isfinite(y) & np.isfinite(x)
    y = y[mask]
    x = x[mask]
    if intercept:
        X = np.column_stack([np.ones(len(x)), x])
    else:
        X = x.reshape(-1, 1)
    coefs, _, _, _ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ coefs
    ss_res = float(np.sum((y - y_hat) ** 2))
    if intercept:
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        alpha = float(coefs[0])
        beta = float(coefs[1])
    else:
        ss_tot = float(np.sum(y ** 2))
        alpha = 0.0
        beta = float(coefs[0])
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return {"r_squared": float(r2), "beta": beta, "alpha": alpha, "n": int(len(y))}


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main() -> int:
    print("=" * 72)
    print("Paper 2 Sec 4.5 TSMC VT + variance share backfill")
    print("=" * 72)

    df = load_snapshot()
    print(f"Snapshot rows: {len(df)}  ({df.index[0].date()} .. {df.index[-1].date()})")

    # ─── Returns ────────────────────────────────────────────────────────────
    tsmc_close_raw = df["2330_tw_close"].dropna()
    tw50_close_raw = df["0050_tw_close"].dropna()
    print(f"TSMC close obs: {len(tsmc_close_raw)}  ({tsmc_close_raw.index[0].date()} .. {tsmc_close_raw.index[-1].date()})")
    print(f"0050 close obs: {len(tw50_close_raw)}  ({tw50_close_raw.index[0].date()} .. {tw50_close_raw.index[-1].date()})")

    # K1175 spec: clean 0050 split artifact; TSMC has no artifact (verified).
    tw50_close, _ = clean_tw50_data(tw50_close_raw)
    tsmc_close = tsmc_close_raw  # no cleaning needed
    print(f"  0050.TW: cleaned 2014-01-02 split artifact via clean_tw50_data")

    # K1175 VT engine uses simple (pct_change) returns; variance-share OLS uses log returns.
    tsmc_ret = compute_simple_returns(tsmc_close)
    tw50_ret = compute_simple_returns(tw50_close)
    tsmc_log_ret = compute_log_returns(tsmc_close)
    tw50_log_ret = compute_log_returns(tw50_close)

    # ─── Number A: TSMC VT Sharpe sweep ─────────────────────────────────────
    print("\n" + "─" * 72)
    print("[A] TSMC VT Sharpe sweep")
    print("─" * 72)

    sweep_a: dict = {}

    # Spec 1: GARCH(1,1) VT 10% on TSMC, OOS 2020-2026 (mirrors K1175 GARCH VT)
    print("\n  Spec 1: GARCH(1,1) VT 10% OOS 2020-2026 ...")
    garch_vol = garch_oos_forecast(tsmc_ret, OOS_START_GARCH, gjr=False)
    print(f"    GARCH forecasts: {len(garch_vol)} days "
          f"({garch_vol.index[0].date()} to {garch_vol.index[-1].date()})")
    garch_w = (TARGET_VOL / garch_vol).clip(0, 1).shift(1).dropna()
    r_garch = backtest_strategy(tsmc_ret, garch_w, "TSMC GARCH VT 10% OOS2020")
    print(f"    Sharpe = {r_garch.get('sharpe')}, n_days = {r_garch.get('n_days')}")
    sweep_a["garch_vt_10_oos2020"] = {k: v for k, v in r_garch.items() if k != "_port_ret"}

    # Spec 2: GJR-GARCH VT 10% on TSMC, OOS 2020-2026
    print("\n  Spec 2: GJR-GARCH VT 10% OOS 2020-2026 ...")
    gjr_vol = garch_oos_forecast(tsmc_ret, OOS_START_GARCH, gjr=True)
    print(f"    GJR forecasts: {len(gjr_vol)} days")
    gjr_w = (TARGET_VOL / gjr_vol).clip(0, 1).shift(1).dropna()
    r_gjr = backtest_strategy(tsmc_ret, gjr_w, "TSMC GJR VT 10% OOS2020")
    print(f"    Sharpe = {r_gjr.get('sharpe')}")
    sweep_a["gjr_vt_10_oos2020"] = {k: v for k, v in r_gjr.items() if k != "_port_ret"}

    # Spec 3: EWMA VT 10% on TSMC, sample 2010-2026
    print("\n  Spec 3: EWMA(λ=0.94) VT 10% 2010-2026 ...")
    ewma_vol = compute_ewma_vol(tsmc_ret)
    ewma_w_all = (TARGET_VOL / ewma_vol).clip(0, 1).shift(1).dropna()
    ewma_w = ewma_w_all[ewma_w_all.index >= OOS_START_BH_EWMA]
    r_ewma = backtest_strategy(tsmc_ret, ewma_w, "TSMC EWMA VT 10% 2010-2026")
    print(f"    Sharpe = {r_ewma.get('sharpe')}")
    sweep_a["ewma_vt_10_2010_2026"] = {k: v for k, v in r_ewma.items() if k != "_port_ret"}

    # Spec 4: EWMA VT 10% on TSMC, full 2008-2026
    ewma_w_full = ewma_w_all
    r_ewma_full = backtest_strategy(tsmc_ret, ewma_w_full, "TSMC EWMA VT 10% full")
    print(f"\n  Spec 4: EWMA VT 10% full 2008-2026: Sharpe = {r_ewma_full.get('sharpe')}")
    sweep_a["ewma_vt_10_full"] = {k: v for k, v in r_ewma_full.items() if k != "_port_ret"}

    # Spec 5-6: GARCH VT with target_vol 15%, 20%
    for tv in (0.15, 0.20):
        w_tv = (tv / garch_vol).clip(0, 1).shift(1).dropna()
        r_tv = backtest_strategy(tsmc_ret, w_tv, f"TSMC GARCH VT {int(tv*100)}% OOS2020")
        print(f"  Spec GARCH VT {int(tv*100)}% OOS2020: Sharpe = {r_tv.get('sharpe')}")
        sweep_a[f"garch_vt_{int(tv*100)}_oos2020"] = {k: v for k, v in r_tv.items() if k != "_port_ret"}

    # Spec 7: Realized 21d vol VT on TSMC
    rv21 = tsmc_ret.rolling(21).std() * np.sqrt(252)
    rv21_w = (TARGET_VOL / rv21).clip(0, 1).shift(1).dropna()
    rv21_w_2010 = rv21_w[rv21_w.index >= OOS_START_BH_EWMA]
    r_rv = backtest_strategy(tsmc_ret, rv21_w_2010, "TSMC RV21 VT 10% 2010-2026")
    print(f"  Spec RV21 VT 10% 2010-2026: Sharpe = {r_rv.get('sharpe')}")
    sweep_a["rv21_vt_10_2010_2026"] = {k: v for k, v in r_rv.items() if k != "_port_ret"}

    # 0050 GARCH VT contextual baseline (paper says 0050 VT = 0.936; K1175 reports 0.950)
    print("\n  Context: 0050 GARCH VT 10% OOS 2020-2026 (paper says 0.936; K1175 says 0.950) ...")
    tw50_garch_vol = garch_oos_forecast(tw50_ret, OOS_START_GARCH, gjr=False)
    tw50_garch_w = (TARGET_VOL / tw50_garch_vol).clip(0, 1).shift(1).dropna()
    r_tw50 = backtest_strategy(tw50_ret, tw50_garch_w, "0050 GARCH VT 10% OOS2020")
    print(f"    0050 Sharpe = {r_tw50.get('sharpe')}")
    sweep_a["context_0050_garch_vt_10_oos2020"] = {k: v for k, v in r_tw50.items() if k != "_port_ret"}

    # Select primary spec — pick whichever is closest to 1.121 (transparent — all
    # spec results are reported; not cherry-pick by hiding).
    candidate_keys = [
        "garch_vt_10_oos2020", "gjr_vt_10_oos2020",
        "ewma_vt_10_2010_2026", "ewma_vt_10_full",
        "garch_vt_15_oos2020", "garch_vt_20_oos2020",
        "rv21_vt_10_2010_2026",
    ]
    closest_key = min(
        candidate_keys,
        key=lambda k: abs(sweep_a[k].get("sharpe", -999) - PAPER_TSMC_SHARPE)
        if "sharpe" in sweep_a[k] else 999,
    )
    closest_sharpe = sweep_a[closest_key]["sharpe"]
    print(f"\n  Closest to paper's 1.121: {closest_key} (Sharpe={closest_sharpe})")

    # Primary verdict: use GARCH(1,1) VT 10% OOS2020 as canonical (K1175 spec match);
    # also report the closest-spec for transparency.
    primary_sharpe = sweep_a["garch_vt_10_oos2020"].get("sharpe")
    primary_v, primary_delta = verdict_sharpe(primary_sharpe, PAPER_TSMC_SHARPE)
    print(f"  PRIMARY (GARCH VT 10% OOS2020): Sharpe={primary_sharpe} → "
          f"delta={primary_delta:+.4f} → {primary_v}")

    # Bootstrap CI on primary
    primary_port = r_garch.get("_port_ret")
    boot_primary = block_bootstrap_sharpe(primary_port) if primary_port is not None else {}
    print(f"  Bootstrap 95% CI on Sharpe: "
          f"[{boot_primary.get('sharpe_ci95_low', 'n/a'):.3f}, "
          f"{boot_primary.get('sharpe_ci95_high', 'n/a'):.3f}]")

    # Also bootstrap closest if different from primary
    boot_closest: dict = {}
    if closest_key != "garch_vt_10_oos2020":
        # We need the daily returns of closest; re-run lightweight to grab them
        closest_label_to_port_ret = {
            "garch_vt_10_oos2020": r_garch,
            "gjr_vt_10_oos2020": r_gjr,
            "ewma_vt_10_2010_2026": r_ewma,
            "ewma_vt_10_full": r_ewma_full,
            "rv21_vt_10_2010_2026": r_rv,
        }
        if closest_key in closest_label_to_port_ret:
            cport = closest_label_to_port_ret[closest_key].get("_port_ret")
            if cport is not None:
                boot_closest = block_bootstrap_sharpe(cport)

    # ─── Number B: Variance share OLS R² sweep ──────────────────────────────
    print("\n" + "─" * 72)
    print("[B] Variance share — OLS R² of 0050 returns on TSMC returns")
    print("─" * 72)

    sweep_b: dict = {}

    # Align returns — use LOG returns for variance-share R² (canonical for
    # "explains X% of return variance" interpretation; equivalent to simple
    # returns at small daily magnitudes but cleaner with intercept).
    common = tsmc_log_ret.index.intersection(tw50_log_ret.index)
    tsmc_c = tsmc_log_ret.loc[common]
    tw50_c = tw50_log_ret.loc[common]

    windows = [
        ("full_2008_2026", common[0].date().isoformat(), common[-1].date().isoformat()),
        ("2010_2026", "2010-01-01", "2026-12-31"),
        ("2014_2024", "2014-01-01", "2024-12-31"),
        ("2020_2026", "2020-01-01", "2026-12-31"),
        ("paper_canonical_2008_2024", "2008-01-01", "2024-12-31"),
    ]
    for label, ws, we in windows:
        mask = (common >= pd.Timestamp(ws)) & (common <= pd.Timestamp(we))
        y = tw50_c[mask].to_numpy()
        x = tsmc_c[mask].to_numpy()
        # With intercept (canonical)
        res = ols_r_squared(y, x, intercept=True)
        # Without intercept
        res_noint = ols_r_squared(y, x, intercept=False)
        sweep_b[label] = {
            "window_start": ws,
            "window_end": we,
            "n": res["n"],
            "with_intercept": {
                "r_squared": res["r_squared"],
                "alpha": res["alpha"],
                "beta": res["beta"],
            },
            "no_intercept": {
                "r_squared": res_noint["r_squared"],
                "beta": res_noint["beta"],
            },
        }
        print(f"  {label:<28} n={res['n']:>5}  R²(int)={res['r_squared']:.4f}  "
              f"β={res['beta']:.4f}  R²(noint)={res_noint['r_squared']:.4f}")

    # Also check raw (simple) returns — log vs raw can differ slightly
    tsmc_raw = tsmc_close.pct_change().dropna()
    tw50_raw = tw50_close.pct_change().dropna()
    common_raw = tsmc_raw.index.intersection(tw50_raw.index)
    y_raw = tw50_raw.loc[common_raw].to_numpy()
    x_raw = tsmc_raw.loc[common_raw].to_numpy()
    res_raw_full = ols_r_squared(y_raw, x_raw, intercept=True)
    sweep_b["full_raw_returns"] = {
        "window_start": common_raw[0].date().isoformat(),
        "window_end": common_raw[-1].date().isoformat(),
        "n": res_raw_full["n"],
        "with_intercept": {
            "r_squared": res_raw_full["r_squared"],
            "alpha": res_raw_full["alpha"],
            "beta": res_raw_full["beta"],
        },
    }
    print(f"  {'full_raw_returns':<28} n={res_raw_full['n']:>5}  "
          f"R²(int)={res_raw_full['r_squared']:.4f}  β={res_raw_full['beta']:.4f}")

    # Primary verdict: use full sample log returns with intercept (canonical for
    # "explains X% of return variance" claim).
    primary_r2 = sweep_b["full_2008_2026"]["with_intercept"]["r_squared"]
    primary_b_v, primary_b_delta = verdict_varshare(primary_r2, PAPER_VAR_SHARE)
    print(f"\n  PRIMARY (full 2008-2026 log returns + intercept): R²={primary_r2:.4f} → "
          f"delta={primary_b_delta:+.4f} → {primary_b_v}")

    # Closest spec to 52.5%
    flat_r2 = {label: spec["with_intercept"]["r_squared"]
               for label, spec in sweep_b.items()
               if "with_intercept" in spec}
    closest_b_key = min(flat_r2.keys(), key=lambda k: abs(flat_r2[k] - PAPER_VAR_SHARE))
    print(f"  Closest to paper's 0.525: {closest_b_key} (R²={flat_r2[closest_b_key]:.4f})")

    # ─── Assemble result JSON ───────────────────────────────────────────────
    result = {
        "experiment_id": "paper2_sec45_tsmc_vt",
        "title": "Paper 2 Sec 4.5 TSMC VT Sharpe + 0050 variance share reproduction",
        "paper_id": "taiwan-vt",
        "paper_claim_locs": [
            {"loc": "body.tex L440", "claim": "TSMC VT Sharpe = 1.121"},
            {"loc": "body.tex L444", "claim": "TSMC explains 52.5% of 0050 return variance"},
        ],
        "data_source": {
            "snapshot": str(MAIN_CSV.relative_to(REPO_ROOT)),
            "live_fetch": False,
            "tsmc_ticker": "2330.TW",
            "etf_ticker": "0050.TW",
            "returns": "Number A (VT Sharpe): simple pct_change() returns; Number B (variance share OLS): log returns (np.log(p_t / p_{t-1}))",
        },
        "spec_alignment": {
            "K1175_canonical": "target_vol=10%, GARCH(1,1) mean='Zero' dist='normal', "
                               "window=2000 refit=21, OOS=2020-01-01, tx_cost=5bps",
            "annualization": "sqrt(252)",
            "lookahead_guard": "weights = (target_vol/sigma_hat).clip(0,1).shift(1); "
                               "GARCH train_data ends at i-1 before forecasting h_i",
        },
        "seed": SEED,
        # ── Number A ─────────────────────────────────────────────────────────
        "number_a_tsmc_vt_sharpe": {
            "paper_target": PAPER_TSMC_SHARPE,
            "paper_loc": "body.tex L440",
            "primary_spec": "garch_vt_10_oos2020",
            "primary_sharpe": primary_sharpe,
            "primary_delta": primary_delta,
            "primary_verdict": primary_v,
            "tolerance_pass": TOL_SHARPE_PASS,
            "tolerance_drift_small": TOL_SHARPE_SMALL,
            "closest_spec": closest_key,
            "closest_sharpe": closest_sharpe,
            "closest_delta": closest_sharpe - PAPER_TSMC_SHARPE,
            "bootstrap_primary": boot_primary,
            "bootstrap_closest": boot_closest,
            "sensitivity_sweep": sweep_a,
            "context_0050_paper_says": PAPER_0050_VT_SHARPE,
        },
        # ── Number B ─────────────────────────────────────────────────────────
        "number_b_variance_share": {
            "paper_target": PAPER_VAR_SHARE,
            "paper_loc": "body.tex L444",
            "primary_spec": "full_2008_2026_log_intercept",
            "primary_r_squared": primary_r2,
            "primary_delta": primary_b_delta,
            "primary_verdict": primary_b_v,
            "tolerance_pass": TOL_VARSHARE_PASS,
            "tolerance_drift_small": TOL_VARSHARE_SMALL,
            "closest_spec": closest_b_key,
            "closest_r_squared": flat_r2[closest_b_key],
            "sensitivity_sweep": sweep_b,
        },
        # ── Convenience top-level byte_match_paper for reproduce.py ──────────
        "byte_match_paper": {
            "tsmc_vt_sharpe": {
                "target": PAPER_TSMC_SHARPE,
                "observed": primary_sharpe,
                "delta": primary_delta,
                "verdict": primary_v,
            },
            "tsmc_variance_share": {
                "target": PAPER_VAR_SHARE,
                "observed": primary_r2,
                "delta": primary_b_delta,
                "verdict": primary_b_v,
            },
        },
        "produced_at_utc": datetime.now(timezone.utc).isoformat(),
    }

    with open(RESULT_JSON, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\nWrote {RESULT_JSON.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
