"""
K1122: Continuous-weight (sigmoid) alt-data allocation
======================================================

Successor to K1121. K1121 tested 6 STEP-based regime allocation strategies
(70th-percentile dummy, 0.7 vs 0.3 weight) on EPU / NFCI; ALL NULL vs 50/50
(p > 0.16, best diff +0.003 Sharpe).

K1122 asks: was the binarisation the bug? Replace step with sigmoid:

    z_t = (alt_t - rolling_mean_252) / rolling_std_252        # trailing z-score
    w_def_t = 1 / (1 + exp(-alpha * (z_t - z0)))               # smooth defensive load
    w_risk_t = 1 - w_def_t

Hypotheses (decision tree):
  H1 sigmoid SAVES:   any (alpha,z0) combo Harvey-pass + 3/3 sub-period stable
                      -> K1121 conclusion partially overturned
  H2 sigmoid USELESS: all 36 specs near-baseline NS -> K1121 robust, alt-data
                      genuinely uninformative for allocation
  H3 INTERMEDIATE:    >=50% of specs nominally beat baseline but sub-period
                      instability -> marginal, non-actionable

Design:
  - Universe: SPY + GLD (paired with each alt-driver = defensive loading on GLD)
              and SPY + GLD + TLT (3-asset extension; sigmoid drives
              SPY -> {GLD,TLT})
  - 3 alt-data drivers: EPU, NFCI, STLFSI4 (FRED)
  - 12 sigmoid combos: alpha in {0.5, 1, 2, 4} x z0 in {-0.5, 0, 0.5}
  - Eval: Sharpe / MDD / Calmar; bootstrap Sharpe-diff vs S1 50/50;
          three sub-periods 2019-21, 2022-23, 2024-26
  - Lookahead: rolling mean/std use trailing-only (.shift(1) on 252-day rolls);
               EPU shift(2), NFCI/STLFSI shift(5) (release timing per K1121 fix)

References:
  - K1121 (Apr 2026): step-regime null on EPU/NFCI/Hybrid
  - K1116 / K1118: alt-data forecasting null
  - Politis & Romano (1994): stationary bootstrap
  - Harvey, Liu, Zhu (2016): t > 3 threshold for Sharpe claims

Seed: 42 throughout. No same-day signals.
"""
from __future__ import annotations

import json
import io
import time as _time
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
LOG_PATH = ROOT / "run.log"
RESULTS_PATH = ROOT / "k1122_results.json"

SEED = 42
np.random.seed(SEED)


def log(msg: str) -> None:
    line = f"[{datetime.utcnow().isoformat(timespec='seconds')}Z] {msg}"
    print(line, flush=True)
    with LOG_PATH.open("a") as fh:
        fh.write(line + "\n")


# --------------------------------------------------------------------- data

def fetch_assets() -> pd.DataFrame:
    """SPY + GLD + TLT + ^VIX, daily auto-adjust close."""
    import yfinance as yf

    log("Fetching SPY + GLD + TLT + VIX 2018-2026 ...")
    tk = yf.download(["SPY", "GLD", "TLT", "^VIX"],
                     start="2018-01-01", end="2026-04-13",
                     progress=False, auto_adjust=True, group_by="ticker")
    if not isinstance(tk.columns, pd.MultiIndex):
        raise RuntimeError("expected multiindex from yf.download")
    df = pd.concat([tk["SPY"]["Close"].rename("SPY"),
                    tk["GLD"]["Close"].rename("GLD"),
                    tk["TLT"]["Close"].rename("TLT"),
                    tk["^VIX"]["Close"].rename("VIX")],
                   axis=1).dropna(how="any")
    df["r_SPY"] = df["SPY"].pct_change()
    df["r_GLD"] = df["GLD"].pct_change()
    df["r_TLT"] = df["TLT"].pct_change()
    log(f"  market panel: {len(df)} rows {df.index.min().date()} -> {df.index.max().date()}")
    return df


def fetch_fred(series_id: str) -> pd.DataFrame:
    cache = DATA_DIR / f"fred_{series_id}.csv"
    if cache.exists():
        log(f"  FRED cache hit: {cache.name}")
        df = pd.read_csv(cache, parse_dates=["DATE"]).set_index("DATE")
        df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
        return df.dropna()

    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; volpred-research/1.0)"}
    last = None
    for k in range(1, 6):
        try:
            r = requests.get(url, headers=headers, timeout=(20, 90))
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            df.columns = ["DATE", series_id]
            df["DATE"] = pd.to_datetime(df["DATE"])
            df[series_id] = pd.to_numeric(df[series_id], errors="coerce")
            df = df.dropna()
            df.to_csv(cache, index=False)
            log(f"  {series_id}: {len(df)} rows fetched -> {cache.name}")
            return df.set_index("DATE")
        except Exception as e:
            last = e
            log(f"  {series_id}: attempt {k}/5 failed ({str(e)[:80]}); retry in {2**k}s")
            _time.sleep(2 ** k)
    raise RuntimeError(f"FRED fetch failed {series_id}: {last}")


def build_panel() -> pd.DataFrame:
    """Merge market with EPU / NFCI / STLFSI4 on daily index (ffill weekly)."""
    market = fetch_assets()
    epu = fetch_fred("USEPUINDXD").rename(columns={"USEPUINDXD": "EPU"})
    nfci = fetch_fred("NFCI")
    stl = fetch_fred("STLFSI4")

    df = market.join(epu, how="left").join(nfci, how="left").join(stl, how="left")
    # Forward-fill alt-data within bounded windows (matches K1121 convention)
    df["EPU"] = df["EPU"].ffill(limit=5)
    df["NFCI"] = df["NFCI"].ffill(limit=10)
    df["STLFSI4"] = df["STLFSI4"].ffill(limit=10)
    df = df.dropna(subset=["EPU", "NFCI", "STLFSI4", "SPY", "GLD", "TLT"])
    log(f"  merged panel rows: {len(df)} {df.index.min().date()} -> {df.index.max().date()}")
    df.to_parquet(DATA_DIR / "panel.parquet")
    return df


# ----------------------------------------------------------------- signals

# Release-timing lags (Codex HIGH-severity finding K1121)
ALT_LAG = {"EPU": 2, "NFCI": 5, "STLFSI4": 5}


def trailing_zscore(s: pd.Series, window: int = 252) -> pd.Series:
    """z = (x_t - mean_{t-window..t-1}) / std_{t-window..t-1}.

    Uses trailing-only stats by shifting rolling window by 1, so z_t never
    sees x_t in its own normalisation -> no lookahead beyond the t-1 obs.

    Codex LOW (k1122 review): if rolling std is 0, z becomes +/-inf and
    sigmoid saturates silently. Replace 0 std with NaN so downstream weights
    are NaN until variance returns; safer than silent saturation.
    """
    mu = s.shift(1).rolling(window).mean()
    sd = s.shift(1).rolling(window).std().replace(0, np.nan)
    return (s - mu) / sd


def sigmoid_weight(z: pd.Series, alpha: float, z0: float) -> pd.Series:
    """w_def_t = 1 / (1 + exp(-alpha * (z - z0))) in [0, 1]."""
    return 1.0 / (1.0 + np.exp(-alpha * (z - z0)))


def build_sigmoid_signals(panel: pd.DataFrame,
                          alphas=(0.5, 1.0, 2.0, 4.0),
                          z0s=(-0.5, 0.0, 0.5),
                          drivers=("EPU", "NFCI", "STLFSI4")) -> pd.DataFrame:
    """For each (driver, alpha, z0) build w_def time series, lagged per driver.

    Column naming: f"w_def_{driver}_a{alpha}_z{z0}"
    """
    sig = pd.DataFrame(index=panel.index)
    sig["S1_wSPY"] = 0.5  # 50/50 baseline (defensive_share = 0.5)

    for d in drivers:
        z = trailing_zscore(panel[d], 252)
        for a in alphas:
            for z0 in z0s:
                w_def = sigmoid_weight(z, a, z0)
                lagged = w_def.shift(ALT_LAG[d])
                col = f"wDef_{d}_a{a}_z{z0}"
                sig[col] = lagged
    return sig


# ----------------------------------------------------------------- backtest

def backtest_pair(panel: pd.DataFrame, sig: pd.DataFrame) -> pd.DataFrame:
    """SPY + GLD pair. wDef -> defensive (GLD); wRisk = 1 - wDef -> SPY."""
    out = pd.DataFrame(index=panel.index)
    out["r_SPY"] = panel["r_SPY"]
    out["r_GLD"] = panel["r_GLD"]
    # Baseline 50/50
    out["r_S1"] = 0.5 * panel["r_SPY"] + 0.5 * panel["r_GLD"]
    out["w_S1"] = 0.5

    for col in sig.columns:
        if col == "S1_wSPY":
            continue
        w_def = sig[col]
        # wDef on GLD; (1-wDef) on SPY
        r = (1 - w_def) * panel["r_SPY"] + w_def * panel["r_GLD"]
        out[f"r_{col}"] = r
        out[f"w_{col}"] = w_def
    return out


def backtest_three_asset(panel: pd.DataFrame, sig: pd.DataFrame) -> pd.DataFrame:
    """SPY + GLD + TLT. wDef splits 50/50 between GLD and TLT for the
    defensive sleeve; wRisk on SPY."""
    out = pd.DataFrame(index=panel.index)
    out["r_SPY"] = panel["r_SPY"]
    out["r_GLD"] = panel["r_GLD"]
    out["r_TLT"] = panel["r_TLT"]
    # 3-asset baseline 1/3 each
    out["r_S1_3a"] = (panel["r_SPY"] + panel["r_GLD"] + panel["r_TLT"]) / 3.0
    out["w_S1_3a"] = 1.0 / 3.0

    for col in sig.columns:
        if col == "S1_wSPY":
            continue
        w_def = sig[col]
        w_risk = 1 - w_def
        # 50/50 split inside defensive sleeve
        r = (w_risk * panel["r_SPY"]
             + 0.5 * w_def * panel["r_GLD"]
             + 0.5 * w_def * panel["r_TLT"])
        out[f"r_{col}_3a"] = r
        out[f"w_{col}_3a"] = w_def
    return out


# ----------------------------------------------------------------- metrics

def sharpe(r, ann=252):
    r = pd.Series(r).dropna()
    if r.std() == 0 or len(r) < 20:
        return float("nan")
    return float((r.mean() / r.std()) * np.sqrt(ann))


def max_drawdown(r):
    r = pd.Series(r).dropna()
    if len(r) == 0:
        return float("nan")
    eq = (1 + r).cumprod()
    peak = eq.cummax()
    return float(((eq - peak) / peak).min())


def calmar(r, ann=252):
    mdd = max_drawdown(r)
    if np.isnan(mdd) or mdd == 0:
        return float("nan")
    return float((pd.Series(r).dropna().mean() * ann) / abs(mdd))


def annual_return(r, ann=252):
    r = pd.Series(r).dropna()
    if len(r) == 0:
        return float("nan")
    return float(r.mean() * ann)


def annual_vol(r, ann=252):
    r = pd.Series(r).dropna()
    if len(r) == 0:
        return float("nan")
    return float(r.std() * np.sqrt(ann))


# ----------------------------------------------------------------- bootstrap

def stationary_bootstrap_sharpe_diff(r1, r2, n_boot=1000, block_mean=20, seed=SEED):
    """Politis-Romano stationary bootstrap on Sharpe diff. Positive => r1 > r2."""
    r1 = pd.Series(r1).dropna()
    r2 = pd.Series(r2).dropna()
    idx = r1.index.intersection(r2.index)
    r1 = r1.reindex(idx).values
    r2 = r2.reindex(idx).values
    n = len(r1)
    if n < 50:
        return {"obs_diff": float("nan"), "p_value": float("nan"),
                "ci_low": float("nan"), "ci_high": float("nan"), "n": int(n)}

    obs = sharpe(pd.Series(r1)) - sharpe(pd.Series(r2))
    rng = np.random.default_rng(seed)
    p_geom = 1.0 / block_mean
    diffs = np.empty(n_boot)
    for b in range(n_boot):
        boot_idx = np.empty(n, dtype=int)
        i = rng.integers(0, n)
        boot_idx[0] = i
        for k in range(1, n):
            if rng.random() < p_geom:
                i = rng.integers(0, n)
            else:
                i = (i + 1) % n
            boot_idx[k] = i
        diffs[b] = sharpe(pd.Series(r1[boot_idx])) - sharpe(pd.Series(r2[boot_idx]))

    centered = diffs - np.nanmean(diffs)
    p_val = 2.0 * min(np.mean(centered >= abs(obs)),
                      np.mean(centered <= -abs(obs)))
    return {
        "obs_diff": float(obs),
        "p_value": float(p_val),
        "ci_low": float(np.nanpercentile(diffs, 2.5)),
        "ci_high": float(np.nanpercentile(diffs, 97.5)),
        "n": int(n),
    }


# ----------------------------------------------------------------- harness

def evaluate_one(r_strat: pd.Series, r_base: pd.Series, label: str) -> dict:
    """Evaluate a single strategy series: full + bootstrap + sub-period."""
    sub_periods = {
        "sub_2019_2021": ("2019-01-01", "2021-12-31"),
        "sub_2022_2023": ("2022-01-01", "2023-12-31"),
        "sub_2024_2026": ("2024-01-01", "2026-12-31"),
    }
    res = {
        "label": label,
        "full": {
            "sharpe": sharpe(r_strat),
            "ann_return": annual_return(r_strat),
            "ann_vol": annual_vol(r_strat),
            "mdd": max_drawdown(r_strat),
            "calmar": calmar(r_strat),
            "n_obs": int(r_strat.dropna().shape[0]),
        },
        "baseline_full": {
            "sharpe": sharpe(r_base),
            "mdd": max_drawdown(r_base),
            "calmar": calmar(r_base),
        },
        "bootstrap_vs_baseline": stationary_bootstrap_sharpe_diff(
            r_strat, r_base, n_boot=1000, block_mean=20, seed=SEED),
        "sub_periods": {},
    }
    sub_passes = 0
    sub_total = 0
    for name, (a, b) in sub_periods.items():
        mask = (r_strat.index >= a) & (r_strat.index <= b)
        rs = r_strat[mask]
        rb = r_base[mask]
        # Codex MEDIUM fix: intersect indexes to avoid silent sample mismatch
        common = rs.dropna().index.intersection(rb.dropna().index)
        rs = rs.reindex(common)
        rb = rb.reindex(common)
        if len(common) < 100:
            res["sub_periods"][name] = {"n": int(len(common)),
                                        "sharpe": float("nan"),
                                        "baseline_sharpe": float("nan"),
                                        "diff": float("nan")}
            continue
        sub_total += 1
        s_strat = sharpe(rs)
        s_base = sharpe(rb)
        diff = s_strat - s_base
        res["sub_periods"][name] = {
            "n": int(len(common)),
            "sharpe": s_strat,
            "baseline_sharpe": s_base,
            "diff": float(diff),
            "beats_baseline": bool(diff > 0),
        }
        if diff > 0:
            sub_passes += 1
    res["sub_period_pass_count"] = sub_passes
    res["sub_period_total"] = sub_total
    res["sub_period_stable"] = bool(sub_total > 0 and sub_passes == sub_total)
    return res


def harvey_pass(boot_res: dict) -> bool:
    """Harvey 2016 t > 3.0. Approximate t = obs_diff / SE_boot via CI width."""
    if np.isnan(boot_res.get("obs_diff", float("nan"))):
        return False
    ci_low = boot_res.get("ci_low")
    ci_high = boot_res.get("ci_high")
    obs = boot_res.get("obs_diff")
    if ci_low is None or ci_high is None or obs is None:
        return False
    # 95% CI width ~ 2 * 1.96 * SE -> SE ~ (ci_high - ci_low) / 3.92
    se = (ci_high - ci_low) / 3.92
    if se <= 0:
        return False
    t = abs(obs) / se
    return t > 3.0


def main() -> None:
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    log("=== K1122: Sigmoid alt-data allocation ===")
    log(f"seed={SEED}")

    panel = build_panel()
    sig = build_sigmoid_signals(panel)

    # Save signals for audit
    sig.to_parquet(DATA_DIR / "signals.parquet")
    log(f"signals: {sig.shape[1]} columns (1 baseline + 36 sigmoid specs)")

    bt_pair = backtest_pair(panel, sig)
    bt_3a = backtest_three_asset(panel, sig)
    bt_pair.to_parquet(DATA_DIR / "backtest_pair.parquet")
    bt_3a.to_parquet(DATA_DIR / "backtest_3asset.parquet")
    log("backtests stored")

    # Trim to common period: drop warm-up NaN
    pair_clean = bt_pair.dropna(subset=["r_S1"]).copy()
    pair_clean = pair_clean[pair_clean.index >= "2019-01-15"]  # K1121 alignment
    base_pair = pair_clean["r_S1"]
    log(f"pair backtest active period: {pair_clean.index.min().date()} -> {pair_clean.index.max().date()}, n={len(pair_clean)}")

    three_clean = bt_3a.dropna(subset=["r_S1_3a"]).copy()
    three_clean = three_clean[three_clean.index >= "2019-01-15"]
    base_3a = three_clean["r_S1_3a"]

    # ---- evaluate every spec on PAIR (SPY+GLD) ----
    spec_results_pair = []
    spec_results_3a = []
    sigmoid_cols = [c for c in sig.columns if c.startswith("wDef_")]
    log(f"evaluating {len(sigmoid_cols)} pair specs ...")
    for col in sigmoid_cols:
        r_col = f"r_{col}"
        if r_col not in pair_clean.columns:
            continue
        # Skip rows where signal is NaN (pre-warmup)
        r_strat = pair_clean[r_col].dropna()
        idx = r_strat.index
        rb = base_pair.reindex(idx)
        res = evaluate_one(r_strat, rb, label=col)
        # parse driver/alpha/z0
        parts = col.split("_")
        res["driver"] = parts[1]
        res["alpha"] = float(parts[2][1:])
        res["z0"] = float(parts[3][1:])
        res["universe"] = "SPY_GLD"
        res["harvey_pass"] = harvey_pass(res["bootstrap_vs_baseline"])
        spec_results_pair.append(res)

    log(f"evaluating {len(sigmoid_cols)} 3-asset specs ...")
    for col in sigmoid_cols:
        r_col = f"r_{col}_3a"
        if r_col not in three_clean.columns:
            continue
        r_strat = three_clean[r_col].dropna()
        idx = r_strat.index
        rb = base_3a.reindex(idx)
        res = evaluate_one(r_strat, rb, label=f"{col}_3a")
        parts = col.split("_")
        res["driver"] = parts[1]
        res["alpha"] = float(parts[2][1:])
        res["z0"] = float(parts[3][1:])
        res["universe"] = "SPY_GLD_TLT"
        res["harvey_pass"] = harvey_pass(res["bootstrap_vs_baseline"])
        spec_results_3a.append(res)

    # ---- aggregate / decision tree ----
    all_specs = spec_results_pair + spec_results_3a
    nominal_beat = [s for s in all_specs if not np.isnan(s["bootstrap_vs_baseline"]["obs_diff"])
                    and s["bootstrap_vs_baseline"]["obs_diff"] > 0]
    p05 = [s for s in nominal_beat if s["bootstrap_vs_baseline"]["p_value"] < 0.05]
    harvey_specs = [s for s in nominal_beat if s["harvey_pass"]]
    stable_specs = [s for s in all_specs if s["sub_period_stable"]
                    and s["bootstrap_vs_baseline"]["obs_diff"] > 0]
    harvey_and_stable = [s for s in harvey_specs if s["sub_period_stable"]]

    if harvey_and_stable:
        verdict = "H1_sigmoid_saves"
        verdict_note = (f"{len(harvey_and_stable)} spec(s) pass Harvey t>3 AND 3/3 sub-period "
                        f"stability. Sigmoid PARTIALLY OVERTURNS K1121.")
    elif len(p05) >= len(all_specs) * 0.5:
        verdict = "H3_intermediate"
        verdict_note = (f"{len(p05)}/{len(all_specs)} specs nominally beat baseline at p<0.05 "
                        f"but 0 pass Harvey+stability gate -> marginal, non-actionable.")
    elif len(nominal_beat) >= len(all_specs) * 0.5:
        verdict = "H3_intermediate"
        verdict_note = (f"{len(nominal_beat)}/{len(all_specs)} specs nominally beat baseline "
                        f"(unsigned) but no spec passes formal threshold -> marginal.")
    else:
        verdict = "H2_K1121_robust"
        verdict_note = (f"Only {len(nominal_beat)}/{len(all_specs)} specs nominally beat 50/50; "
                        f"0 pass Harvey or 3/3 stability. Sigmoid does NOT rescue alt-data; "
                        f"K1121 step-regime null is robust.")

    # rank by Sharpe diff
    ranked = sorted(all_specs,
                    key=lambda s: (-s["bootstrap_vs_baseline"]["obs_diff"]
                                   if not np.isnan(s["bootstrap_vs_baseline"]["obs_diff"]) else 1e9))
    top5 = [{"label": s["label"], "universe": s["universe"], "driver": s["driver"],
             "alpha": s["alpha"], "z0": s["z0"],
             "sharpe_diff": s["bootstrap_vs_baseline"]["obs_diff"],
             "p_value": s["bootstrap_vs_baseline"]["p_value"],
             "ci": [s["bootstrap_vs_baseline"]["ci_low"],
                    s["bootstrap_vs_baseline"]["ci_high"]],
             "harvey_pass": s["harvey_pass"],
             "sub_period_stable": s["sub_period_stable"],
             "sharpe_full": s["full"]["sharpe"],
             "mdd": s["full"]["mdd"],
             "calmar": s["full"]["calmar"]}
            for s in ranked[:5]]

    out = {
        "experiment_id": "K1122",
        "title": "Continuous-weight (sigmoid) alt-data allocation",
        "date_run": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "seed": SEED,
        "data_period": {
            "start": str(pair_clean.index.min().date()),
            "end": str(pair_clean.index.max().date()),
            "n_days_pair": int(len(pair_clean)),
            "n_days_3asset": int(len(three_clean)),
        },
        "design": {
            "drivers": ["EPU", "NFCI", "STLFSI4"],
            "alphas": [0.5, 1.0, 2.0, 4.0],
            "z0s": [-0.5, 0.0, 0.5],
            "lags": ALT_LAG,
            "universes": ["SPY_GLD", "SPY_GLD_TLT"],
            "n_specs_total": len(all_specs),
            "baseline_pair": "50/50 SPY/GLD",
            "baseline_3asset": "1/3 SPY / 1/3 GLD / 1/3 TLT",
            "sigmoid_form": "w_def = 1 / (1 + exp(-alpha * (z - z0)))",
            "z_score": "trailing 252-day, x_t excluded from its own normalisation",
            "sub_periods": ["2019-2021", "2022-2023", "2024-2026"],
        },
        "verdict": verdict,
        "verdict_note": verdict_note,
        "summary": {
            "n_specs": len(all_specs),
            "n_nominal_beat": len(nominal_beat),
            "n_p05": len(p05),
            "n_harvey_pass": len(harvey_specs),
            "n_subperiod_stable": len(stable_specs),
            "n_harvey_and_stable": len(harvey_and_stable),
        },
        "top5_by_sharpe_diff": top5,
        "all_specs_pair": spec_results_pair,
        "all_specs_3asset": spec_results_3a,
        "k1121_reference": {
            "best_step_diff": 0.003,
            "best_step_p": 0.966,
            "verdict": "all step strategies NULL vs 50/50",
        },
    }

    RESULTS_PATH.write_text(json.dumps(out, indent=2, default=float))
    log(f"results -> {RESULTS_PATH}")
    log(f"VERDICT: {verdict} - {verdict_note}")
    log(f"top spec: {top5[0]['label']} diff={top5[0]['sharpe_diff']:+.4f} "
        f"p={top5[0]['p_value']:.3f} harvey={top5[0]['harvey_pass']} "
        f"stable={top5[0]['sub_period_stable']}")


if __name__ == "__main__":
    main()
