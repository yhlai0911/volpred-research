"""K1586 — Stablecoin reserves → short-end T-bill realized vol.

Lookahead policy (HARD RULE):
- All predictors are stablecoin Δlog(mcap) lagged by k>=1 business days via
  pandas `.shift(k)` — no contemporaneous regression, no forward label.
- Realized vol is 22-day TRAILING rolling std of daily Δyield(bps) / daily
  log-return(bps) — uses observations [t-21, t] only (pandas .rolling default
  is trailing inclusive of t). As response variable (placed at t), this is
  legitimate; we DO NOT use it as a predictor.
- Random seed=42 enforced for the only randomized routine (block bootstrap on
  H2 |return| with block_size=5, n_boot=5000) via numpy default_rng(SEED).
- Data fetch fails fast (no silent fallback). All raw downloads cached to
  experiments/K1586/data/ for byte-traceable reproducibility.

Run:
    uv run python experiments/K1586/K1586.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from io import StringIO
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import matplotlib

matplotlib.use("Agg")  # non-interactive
import matplotlib.pyplot as plt

from scipy.stats import ttest_ind
from statsmodels.regression.linear_model import OLS
from statsmodels.tools.tools import add_constant
from statsmodels.tsa.stattools import grangercausalitytests

import yfinance as yf

# ---------------- config ----------------
SEED = 42
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

SAMPLE_START = "2020-01-01"
SAMPLE_END = "2026-06-29"
RV_WINDOW = 22  # business days
MAX_LAG = 5

USDC_SVB_EVENT = pd.Timestamp("2023-03-10")
GENIUS_ACT_EVENT = pd.Timestamp("2025-07-18")  # Public Law announcement
EVENT_WIN = 5      # ED ± 5
CONTROL_WIN = 30   # ED ± 30 excluding ±5

DEFI_LLAMA_ALL = "https://stablecoins.llama.fi/stablecoincharts/all"
DEFI_LLAMA_COIN = "https://stablecoins.llama.fi/stablecoin/{}"  # USDT=1, USDC=2, DAI=3
FRED_CSV = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={}"


# ---------------- fetchers (fail-fast) ----------------

def fetch_defillama_all() -> pd.DataFrame:
    """Total stablecoin mcap (USD-pegged), daily, all chains."""
    cache = DATA_DIR / "defillama_all.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if len(df) > 100:
            return df
    r = requests.get(DEFI_LLAMA_ALL, timeout=30)
    r.raise_for_status()
    data = r.json()
    rows = []
    for d in data:
        ts = int(d["date"])
        total = d.get("totalCirculatingUSD", {}).get("peggedUSD", 0.0)
        rows.append({"date": pd.to_datetime(ts, unit="s"), "total_mcap_usd": float(total)})
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def fetch_defillama_coin(coin_id: int, name: str) -> pd.DataFrame:
    cache = DATA_DIR / f"defillama_{name}.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if len(df) > 100:
            return df
    r = requests.get(DEFI_LLAMA_COIN.format(coin_id), timeout=30)
    r.raise_for_status()
    data = r.json()
    tokens = data.get("tokens", [])
    if not tokens:
        raise RuntimeError(f"DefiLlama coin {name} returned no tokens series")
    rows = []
    for d in tokens:
        ts = int(d["date"])
        circ = d.get("circulating", {})
        v = circ.get("peggedUSD", 0.0) if isinstance(circ, dict) else 0.0
        rows.append({"date": pd.to_datetime(ts, unit="s"), f"{name}_mcap_usd": float(v)})
    df = pd.DataFrame(rows).sort_values("date").reset_index(drop=True)
    df.to_csv(cache, index=False)
    return df


def fetch_fred(series: str) -> pd.DataFrame:
    cache = DATA_DIR / f"fred_{series}.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if len(df) > 100:
            return df
    r = requests.get(FRED_CSV.format(series), timeout=30)
    r.raise_for_status()
    # FRED returns CSV with observation_date,SERIES columns
    df = pd.read_csv(StringIO(r.text))
    cols = list(df.columns)
    if "observation_date" in cols:
        df = df.rename(columns={"observation_date": "date"})
    elif "DATE" in cols:
        df = df.rename(columns={"DATE": "date"})
    else:
        df = df.rename(columns={cols[0]: "date"})
    df["date"] = pd.to_datetime(df["date"])
    # series column may equal `series` literal
    val_col = series if series in df.columns else df.columns[1]
    df = df.rename(columns={val_col: series})
    df[series] = pd.to_numeric(df[series], errors="coerce")
    df = df.dropna(subset=[series]).reset_index(drop=True)
    df[["date", series]].to_csv(cache, index=False)
    return df[["date", series]]


def fetch_etf_yf(symbols: list[str], start: str, end: str) -> pd.DataFrame:
    cache = DATA_DIR / f"etf_{'_'.join(symbols)}.csv"
    if cache.exists():
        df = pd.read_csv(cache, parse_dates=["date"])
        if len(df) > 100:
            return df
    df = yf.download(symbols, start=start, end=end, auto_adjust=True, progress=False)
    if df.empty:
        raise RuntimeError(f"yfinance returned empty for {symbols}")
    close = df["Close"].copy()
    close = close.reset_index().rename(columns={"Date": "date"})
    close.to_csv(cache, index=False)
    return close


# ---------------- core ----------------

def main() -> dict:
    np.random.seed(SEED)
    t0 = time.time()
    print("[K1586] fetching data...")

    sb_all = fetch_defillama_all()
    sb_usdt = fetch_defillama_coin(1, "USDT")
    sb_usdc = fetch_defillama_coin(2, "USDC")
    sb_dai = fetch_defillama_coin(3, "DAI")

    # build stablecoin daily panel (USDT+USDC+DAI)
    sb = sb_usdt.merge(sb_usdc, on="date", how="outer").merge(sb_dai, on="date", how="outer")
    sb = sb.sort_values("date").reset_index(drop=True)
    sb["big3_mcap_usd"] = (
        sb[["USDT_mcap_usd", "USDC_mcap_usd", "DAI_mcap_usd"]].fillna(0).sum(axis=1)
    )

    # restrict to sample window
    sb = sb[(sb["date"] >= SAMPLE_START) & (sb["date"] <= SAMPLE_END)].reset_index(drop=True)

    # only keep dates where mcap meaningful (>= 5B); pre that, stablecoin universe too small
    sb = sb[sb["big3_mcap_usd"] >= 5e9].reset_index(drop=True)

    # normalize datetime dtype across sources (FRED CSV cache vs DefiLlama vs yfinance differ)
    sb["date"] = pd.to_datetime(sb["date"]).astype("datetime64[ns]")

    # FRED
    dgs1mo = fetch_fred("DGS1MO")
    dgs3mo = fetch_fred("DGS3MO")
    fred_df = dgs1mo.merge(dgs3mo, on="date", how="outer").sort_values("date").reset_index(drop=True)
    fred_df = fred_df[(fred_df["date"] >= SAMPLE_START) & (fred_df["date"] <= SAMPLE_END)].reset_index(drop=True)
    fred_df["date"] = pd.to_datetime(fred_df["date"]).astype("datetime64[ns]")

    # ETF
    etf = fetch_etf_yf(["SHY", "BIL"], SAMPLE_START, SAMPLE_END)
    etf["date"] = pd.to_datetime(etf["date"]).astype("datetime64[ns]")
    etf = etf[(etf["date"] >= SAMPLE_START) & (etf["date"] <= SAMPLE_END)].reset_index(drop=True)

    print(f"[K1586] sb rows={len(sb)}, fred rows={len(fred_df)}, etf rows={len(etf)}")

    # ---------------- build daily features ----------------
    # business-day calendar via fred (DGS series only on business days)
    cal = fred_df[["date"]].copy()

    sb_b = pd.merge_asof(cal, sb[["date", "big3_mcap_usd"]], on="date", direction="backward")
    sb_b["sb_dlog"] = np.log(sb_b["big3_mcap_usd"]).diff()
    sb_b["sb_dmcap_bn"] = sb_b["big3_mcap_usd"].diff() / 1e9

    fred_b = cal.merge(fred_df, on="date", how="left")
    fred_b["DGS1MO_dbps"] = fred_b["DGS1MO"].diff() * 100.0  # bps
    fred_b["DGS3MO_dbps"] = fred_b["DGS3MO"].diff() * 100.0
    fred_b["DGS1MO_RV"] = fred_b["DGS1MO_dbps"].rolling(RV_WINDOW).std()  # trailing 22d
    fred_b["DGS3MO_RV"] = fred_b["DGS3MO_dbps"].rolling(RV_WINDOW).std()

    etf_b = cal.merge(etf, on="date", how="left")
    etf_b["SHY_ret_bps"] = np.log(etf_b["SHY"] / etf_b["SHY"].shift(1)) * 1e4
    etf_b["BIL_ret_bps"] = np.log(etf_b["BIL"] / etf_b["BIL"].shift(1)) * 1e4
    etf_b["SHY_absret"] = etf_b["SHY_ret_bps"].abs()
    etf_b["BIL_absret"] = etf_b["BIL_ret_bps"].abs()
    etf_b["SHY_RV"] = etf_b["SHY_ret_bps"].rolling(RV_WINDOW).std()
    etf_b["BIL_RV"] = etf_b["BIL_ret_bps"].rolling(RV_WINDOW).std()

    panel = cal.merge(sb_b[["date", "sb_dlog", "sb_dmcap_bn"]], on="date") \
        .merge(fred_b[["date", "DGS1MO_RV", "DGS3MO_RV", "DGS1MO_dbps", "DGS3MO_dbps"]], on="date") \
        .merge(etf_b[["date", "SHY_RV", "BIL_RV", "SHY_absret", "BIL_absret"]], on="date")

    panel = panel.dropna(subset=["sb_dlog", "DGS1MO_RV", "DGS3MO_RV"]).reset_index(drop=True)
    print(f"[K1586] panel rows after dropna: {len(panel)}; range {panel['date'].min().date()} -> {panel['date'].max().date()}")

    results: dict = {
        "experiment_id": "K1586",
        "title": "Stablecoin reserves -> short-end T-bill realized vol",
        "run_timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "sample": {
            "start": panel["date"].min().date().isoformat(),
            "end": panel["date"].max().date().isoformat(),
            "n_business_days": int(len(panel)),
        },
        "data_sources": {
            "stablecoin": "DefiLlama free (https://stablecoins.llama.fi)",
            "fred": "FRED CSV (https://fred.stlouisfed.org)",
            "etf": "yfinance (SHY, BIL)",
        },
        "lookahead_policy": {
            "stablecoin_predictor_lag": "shift(k>=1) enforced in H1; no contemporaneous regression",
            "rv_window": f"trailing {RV_WINDOW}-day rolling std (pandas default)",
            "forward_label": False,
        },
        "hypotheses": {},
    }

    # ---------------- H1: lead-lag ----------------
    print("[K1586] H1 lead-lag analysis...")
    h1 = {"target": "DGS1MO_RV / DGS3MO_RV", "predictor": "sb_dlog (USDT+USDC+DAI)"}
    for target in ["DGS1MO_RV", "DGS3MO_RV"]:
        tgt = panel[target].astype(float).values
        target_block = {"pearson_corr_by_lag": {}, "ols_hac": {}}
        for k in range(1, MAX_LAG + 1):
            pred = panel["sb_dlog"].shift(k).astype(float).values  # NB: shift(k) is t-k -> t
            mask = ~(np.isnan(pred) | np.isnan(tgt))
            x = pred[mask]
            y = tgt[mask]
            if len(x) < 60:
                continue
            corr = float(np.corrcoef(x, y)[0, 1])
            # OLS w/ HAC
            X = add_constant(x)
            ols_res = OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 10})
            target_block["pearson_corr_by_lag"][f"lag_{k}"] = {
                "corr": corr,
                "n": int(mask.sum()),
            }
            target_block["ols_hac"][f"lag_{k}"] = {
                "beta": float(ols_res.params[1]),
                "se_hac": float(ols_res.bse[1]),
                "t_stat": float(ols_res.tvalues[1]),
                "p_value": float(ols_res.pvalues[1]),
                "r_squared": float(ols_res.rsquared),
            }
        # Granger F-test: does sb_dlog Granger-cause target? statsmodels expects
        # 2-column [y, x] where it tests whether x Granger-causes y.
        gdf = pd.DataFrame({"y": panel[target].astype(float), "x": panel["sb_dlog"].astype(float)}).dropna()
        try:
            g = grangercausalitytests(gdf[["y", "x"]], maxlag=MAX_LAG, verbose=False)
            # statsmodels ssr_ftest returns (F, p_value, df_denom, df_num); labels fixed per Codex review
            target_block["granger"] = {
                f"lag_{k}": {
                    "F": float(g[k][0]["ssr_ftest"][0]),
                    "p_value": float(g[k][0]["ssr_ftest"][1]),
                    "df_denom": float(g[k][0]["ssr_ftest"][2]),
                    "df_num": int(g[k][0]["ssr_ftest"][3]),
                }
                for k in range(1, MAX_LAG + 1)
            }
        except Exception as e:
            target_block["granger"] = {"error": str(e)}
        h1[target] = target_block
    results["hypotheses"]["H1_lead_lag"] = h1

    # ---------------- H2: USDC-SVB event study ----------------
    print("[K1586] H2 USDC-SVB event study...")
    # build absolute log return series for SHY/BIL aligned to business calendar
    h2 = {"event_date": USDC_SVB_EVENT.date().isoformat(), "event_window_days": EVENT_WIN, "control_window_days": CONTROL_WIN}
    etf_panel = etf_b.dropna(subset=["SHY_absret", "BIL_absret"]).reset_index(drop=True)
    etf_panel["date"] = pd.to_datetime(etf_panel["date"])
    # business-day order index of event date
    event_idx = etf_panel["date"].searchsorted(USDC_SVB_EVENT)
    if event_idx >= len(etf_panel):
        h2["status"] = "event_out_of_sample"
    else:
        # locate nearest business day on/after event
        ed = etf_panel.iloc[event_idx]["date"]
        h2["event_date_aligned"] = ed.date().isoformat()
        ev_lo = max(0, event_idx - EVENT_WIN)
        ev_hi = min(len(etf_panel), event_idx + EVENT_WIN + 1)
        ctrl_lo_a = max(0, event_idx - CONTROL_WIN)
        ctrl_hi_a = ev_lo
        ctrl_lo_b = ev_hi
        ctrl_hi_b = min(len(etf_panel), event_idx + CONTROL_WIN + 1)
        ev_slice = etf_panel.iloc[ev_lo:ev_hi]
        ctrl_slice = pd.concat([etf_panel.iloc[ctrl_lo_a:ctrl_hi_a], etf_panel.iloc[ctrl_lo_b:ctrl_hi_b]])

        rng = np.random.default_rng(SEED)
        for etf_name in ["SHY", "BIL"]:
            col = f"{etf_name}_absret"
            ev_vals = ev_slice[col].dropna().values
            ctrl_vals = ctrl_slice[col].dropna().values
            t_stat, p_val = ttest_ind(ev_vals, ctrl_vals, equal_var=False)
            p_bonf = float(min(1.0, p_val * 2))  # N=2 ETFs

            # Block bootstrap (block size = 5 business days) for vol-clustering robustness
            # H0: event window draws come from same distribution as control window
            n_boot = 5000
            block_size = 5
            pooled = np.concatenate([ev_vals, ctrl_vals])
            obs_diff = np.mean(ev_vals) - np.mean(ctrl_vals)
            boot_diffs = np.empty(n_boot)
            n_ev = len(ev_vals)
            n_total = len(pooled)
            for b in range(n_boot):
                # block bootstrap: sample blocks of consecutive indices then truncate
                idx = []
                while len(idx) < n_total:
                    start = rng.integers(0, max(1, n_total - block_size + 1))
                    idx.extend(range(start, min(start + block_size, n_total)))
                idx = np.array(idx[:n_total])
                resampled = pooled[idx]
                boot_diffs[b] = np.mean(resampled[:n_ev]) - np.mean(resampled[n_ev:])
            # two-sided p-value
            p_boot = float(np.mean(np.abs(boot_diffs) >= np.abs(obs_diff)))

            h2[etf_name] = {
                "event_n": int(len(ev_vals)),
                "control_n": int(len(ctrl_vals)),
                "event_mean_abs_bps": float(np.mean(ev_vals)),
                "control_mean_abs_bps": float(np.mean(ctrl_vals)),
                "ratio": float(np.mean(ev_vals) / np.mean(ctrl_vals)) if np.mean(ctrl_vals) > 0 else None,
                "welch_t_stat": float(t_stat),
                "p_value": float(p_val),
                "p_value_bonf_n2": p_bonf,
                "block_bootstrap": {
                    "n_boot": n_boot,
                    "block_size": block_size,
                    "p_value_two_sided": p_boot,
                    "p_bonf_n2": float(min(1.0, p_boot * 2)),
                },
            }
    results["hypotheses"]["H2_USDC_SVB_event"] = h2

    # ---------------- H3: GENIUS Act event check ----------------
    print("[K1586] H3 GENIUS Act event check...")
    h3 = {"event_date": GENIUS_ACT_EVENT.date().isoformat()}
    if GENIUS_ACT_EVENT > pd.Timestamp(panel["date"].max()):
        h3["status"] = "future_event_out_of_sample"
        h3["note"] = f"Event {GENIUS_ACT_EVENT.date()} > sample end {panel['date'].max().date()}; placeholder per honesty rule."
    else:
        # locate event in panel
        idx = panel["date"].searchsorted(GENIUS_ACT_EVENT)
        if idx >= len(panel):
            h3["status"] = "future_event_out_of_sample"
        else:
            ev = panel.iloc[max(0, idx - EVENT_WIN):min(len(panel), idx + EVENT_WIN + 1)]
            ctrl_a = panel.iloc[max(0, idx - CONTROL_WIN):max(0, idx - EVENT_WIN)]
            ctrl_b = panel.iloc[min(len(panel), idx + EVENT_WIN + 1):min(len(panel), idx + CONTROL_WIN + 1)]
            ctrl = pd.concat([ctrl_a, ctrl_b])
            for tgt in ["DGS1MO_RV", "DGS3MO_RV"]:
                ev_vals = ev[tgt].dropna().values
                c_vals = ctrl[tgt].dropna().values
                if len(ev_vals) < 3 or len(c_vals) < 3:
                    continue
                t_stat, p_val = ttest_ind(ev_vals, c_vals, equal_var=False)
                h3[tgt] = {
                    "event_n": int(len(ev_vals)),
                    "control_n": int(len(c_vals)),
                    "event_mean_rv": float(np.mean(ev_vals)),
                    "control_mean_rv": float(np.mean(c_vals)),
                    "welch_t_stat": float(t_stat),
                    "p_value": float(p_val),
                }
            h3["status"] = "in_sample"
    results["hypotheses"]["H3_GENIUS_Act_event"] = h3

    # ---------------- Verdict ----------------
    # H1 PASS: any lag Granger p<0.05 AND |t_stat HAC| > 2 at same lag
    h1_pass = False
    h1_passing_lags = []
    for tgt in ["DGS1MO_RV", "DGS3MO_RV"]:
        granger = h1[tgt].get("granger", {})
        ols = h1[tgt].get("ols_hac", {})
        for k in range(1, MAX_LAG + 1):
            gkey = f"lag_{k}"
            g_p = granger.get(gkey, {}).get("p_value", 1.0) if isinstance(granger, dict) else 1.0
            t_stat = abs(ols.get(gkey, {}).get("t_stat", 0.0))
            if g_p < 0.05 and t_stat > 2.0:
                h1_pass = True
                h1_passing_lags.append(f"{tgt}_lag{k} (g_p={g_p:.4f}, |t|={t_stat:.2f})")

    # H2 PASS: at least one ETF |t|>2 AND Welch p_bonf<0.05 AND block-bootstrap p_bonf<0.05
    # (block bootstrap accounts for vol clustering per Codex review)
    h2_pass = False
    h2_passing = []
    if "SHY" in h2:
        for etf_name in ["SHY", "BIL"]:
            r = h2.get(etf_name, {})
            boot = r.get("block_bootstrap", {})
            if (
                abs(r.get("welch_t_stat", 0.0)) > 2.0
                and r.get("p_value_bonf_n2", 1.0) < 0.05
                and boot.get("p_bonf_n2", 1.0) < 0.05
            ):
                h2_pass = True
                h2_passing.append(
                    f"{etf_name} (t={r['welch_t_stat']:.2f}, p_bonf_welch={r['p_value_bonf_n2']:.4f}, p_bonf_boot={boot.get('p_bonf_n2'):.4f})"
                )

    # Per Codex review (NEEDS_REVISION): a hypothesis cannot count itself as marginal
    # to upgrade its own NULL. Marginal = "the OTHER hypothesis is borderline".
    marginal_h1 = any(
        (h1[t].get("granger", {}).get(f"lag_{k}", {}).get("p_value", 1.0) < 0.10)
        for t in ["DGS1MO_RV", "DGS3MO_RV"]
        for k in range(1, MAX_LAG + 1)
    )
    marginal_h2 = False
    if "SHY" in h2:
        marginal_h2 = any(
            (h2.get(e, {}).get("p_value_bonf_n2", 1.0) < 0.10)
            for e in ["SHY", "BIL"]
        )

    if h1_pass and h2_pass:
        verdict = "PASS"
    elif h1_pass and marginal_h2 and not h2_pass:
        verdict = "CONDITIONAL_PASS"
    elif h2_pass and marginal_h1 and not h1_pass:
        verdict = "CONDITIONAL_PASS"
    elif h1_pass or h2_pass:
        # one passes but the other is not even marginal → NULL_PARTIAL
        verdict = "NULL_PARTIAL"
    else:
        verdict = "NULL"

    results["verdict"] = verdict
    results["verdict_detail"] = {
        "H1_pass": h1_pass,
        "H1_passing_lags": h1_passing_lags,
        "H2_pass": h2_pass,
        "H2_passing": h2_passing,
    }

    # ---------------- Figures ----------------
    print("[K1586] generating figures...")
    # Fig 1: lead-lag correlation bar
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    for ax, target in zip(axes, ["DGS1MO_RV", "DGS3MO_RV"]):
        corrs = []
        lags = []
        for k in range(1, MAX_LAG + 1):
            c = h1[target]["pearson_corr_by_lag"].get(f"lag_{k}", {}).get("corr")
            if c is not None:
                corrs.append(c)
                lags.append(k)
        ax.bar(lags, corrs, color=["#2E86AB" if c >= 0 else "#A23B72" for c in corrs])
        ax.axhline(0, color="k", lw=0.5)
        ax.set_title(f"Pearson corr: sb_dlog(t-k) vs {target}(t)")
        ax.set_xlabel("Lag k (business days)")
        ax.set_ylabel("Correlation")
        ax.set_xticks(lags)
    plt.tight_layout()
    plt.savefig(FIG_DIR / "leadlag_corr.png", dpi=120)
    plt.close()

    # Fig 2: USDC-SVB event study
    if "SHY" in h2:
        fig, axes = plt.subplots(1, 2, figsize=(11, 4))
        for ax, etf_name in zip(axes, ["SHY", "BIL"]):
            r = h2[etf_name]
            ax.bar(
                ["Event\n±5d", "Control\n[±6,±30]"],
                [r["event_mean_abs_bps"], r["control_mean_abs_bps"]],
                color=["#D62828", "#003049"],
            )
            ax.set_title(
                f"{etf_name} |return| around USDC-SVB depeg 2023-03-10\n"
                f"t={r['welch_t_stat']:.2f}, p_bonf={r['p_value_bonf_n2']:.4f}, ratio={r['ratio']:.2f}"
            )
            ax.set_ylabel("Mean |log-return| (bps)")
        plt.tight_layout()
        plt.savefig(FIG_DIR / "svb_event_study.png", dpi=120)
        plt.close()

    # ---------------- Persist panel (small) ----------------
    panel_out = panel.copy()
    panel_out["date"] = panel_out["date"].dt.date
    panel_out.to_csv(DATA_DIR / "panel.csv", index=False)

    results["runtime_seconds"] = round(time.time() - t0, 2)

    out = EXP_DIR / "K1586_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str))
    print(f"[K1586] verdict={verdict} -> {out}")
    return results


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"[K1586] FATAL: {exc}", file=sys.stderr)
        raise
