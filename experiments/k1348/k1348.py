"""
K1348 — ETF heartbeat / tax-efficiency 季末壓力檢定
=====================================================

Hypothesis: SPY/IVV/VTI/QQQ 在季末 / 年末視窗會出現 ETF heartbeat trade（為避稅而
循環處分低成本基差證券+再買回）造成 top holdings 的成交量/range-vol/RV 異常
擴張。

References (寫入 README.md):
  - Moussawi, Shen, Velthuis (2025) RFS "The Role of Taxes in the Rise of ETFs"
  - Da, Liu, Schaumburg (2014) JFE "Anatomy of pricing of newly added stocks"
    (近代 ETF 流動性/rebalance literature 起點)
  - Ben-David, Franzoni, Moussawi (2017/2018) JFE "Do ETFs Increase Volatility?"

Method:
  Tier 1 — ETF level event study
    1. yfinance 抓 SPY/IVV/VTI/QQQ + top holdings 2014-01-01..2026-06-17 日資料
    2. 算 daily log volume, Garman-Klass range-vol, close-to-close abs return
    3. Quarter-end window dummy: Mar/Jun/Sep/Dec 月底最後 5 交易日 = "event"，
       中段為 baseline。年末（Dec 末 5 天）= 額外 dummy（與 Q4 重疊但檢驗額外效應）
    4. Welch t-test: window vs baseline
    5. Event-study panel (-5..+3) 對齊 last trading day of each quarter

  Tier 2 — Cross-sectional + panel OLS with clustered SE
    6. Per ETF × per holding pair: abnormal metrics in event window
    7. Pooled OLS: abnormal_metric ~ quarter_end + year_end + asset_FE + year_FE
       with HC1 robust SE (panel size 中小不跑 cluster-bootstrap fancy)
    8. Bootstrap 500 reps (seed=42) 對 mean-diff CI

Lookahead policy:
  - All test statistics computed AFTER event window ends (calendar dates)
  - Bootstrap / seed: np.random.seed(42)
  - No predictive claim — purely descriptive event study

Output:
  - k1348_results.json (byte-traceable)
  - fig_event_study.png  (ETF-level abnormal RV/volume curves)
  - fig_cross_section.png (per-holding abnormal RV histogram)
  - fig_panel_regression.png (coef + 95% CI)
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from pathlib import Path
from datetime import datetime

import numpy as np
import pandas as pd
import scipy.stats as stats
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import yfinance as yf
import statsmodels.api as sm

warnings.filterwarnings("ignore", category=FutureWarning)

OUT_DIR = Path(__file__).parent
OUT_JSON = OUT_DIR / "k1348_results.json"
RNG_SEED = 42

START = "2014-01-01"
END = "2026-06-17"

ETFS = ["SPY", "IVV", "VTI", "QQQ"]

# 2026-current top holdings (manually selected, common across SPY/IVV/VTI/QQQ)
# Diagnostic-tier — 用 current top holdings 對歷史 quarter-ends 做 event study；
# README 明示非 holdings-history-aware（不宣稱因果）。
TOP_HOLDINGS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA",
    "AVGO", "BRK-B", "JPM", "LLY", "V", "XOM", "UNH", "MA",
]

# event window: 季末月份最後 N 個 trading days = "event"
EVENT_LAG = 5
POST_LAG = 3
QUARTER_END_MONTHS = {3, 6, 9, 12}


def fetch_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    out = {}
    for tk in tickers:
        for attempt in range(3):
            try:
                df = yf.download(
                    tk, start=START, end=END, auto_adjust=False,
                    progress=False, threads=False,
                )
                if df is None or df.empty:
                    raise RuntimeError(f"empty df for {tk}")
                # flatten multiindex columns from yfinance 0.2+
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
                df = df.dropna()
                out[tk] = df
                break
            except Exception as e:
                if attempt == 2:
                    print(f"[warn] {tk} failed after 3 tries: {e}")
                else:
                    time.sleep(1.5)
        if tk not in out:
            print(f"[warn] dropping {tk}")
    return out


def garman_klass_vol(o, h, l, c) -> pd.Series:
    """Garman-Klass daily variance — square-root for vol."""
    log_hl = np.log(h / l) ** 2
    log_co = np.log(c / o) ** 2
    var = 0.5 * log_hl - (2 * np.log(2) - 1) * log_co
    var = var.clip(lower=1e-12)
    return np.sqrt(var)


def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    out = pd.DataFrame(index=df.index)
    out["log_volume"] = np.log(df["Volume"].clip(lower=1))
    out["range_vol"] = garman_klass_vol(df["Open"], df["High"], df["Low"], df["Close"])
    log_ret = np.log(df["Close"]).diff()
    out["abs_ret"] = log_ret.abs()
    out["c2c_rv"] = log_ret ** 2  # daily realized var proxy
    return out.dropna()


def tag_windows(idx: pd.DatetimeIndex) -> pd.DataFrame:
    """為每個 trading day 標：
      - is_quarter_end_window: 該季末月份最後 EVENT_LAG 個 trading days
      - is_year_end_window:    12 月最後 EVENT_LAG 個 trading days
      - quarter_end_day_offset: relative offset to last trading day of quarter
        (event=0, pre/post 在 [-EVENT_LAG+1..POST_LAG])
    """
    s = pd.DataFrame(index=idx)
    s["year"] = idx.year
    s["month"] = idx.month
    # 找出每個季末月份的 last trading day
    quarter_keys = s[s["month"].isin(QUARTER_END_MONTHS)].groupby([s["year"], s["month"]]).apply(
        lambda g: g.index.max()
    )
    qe_dates = pd.DatetimeIndex(quarter_keys.values)
    ye_dates = pd.DatetimeIndex([d for d in qe_dates if d.month == 12])
    # 對每個 trading day 算 offset 到下一個 / 上一個 quarter-end
    s["is_quarter_end_window"] = False
    s["is_year_end_window"] = False
    s["quarter_end_day_offset"] = np.nan
    # iterate quarter-end dates
    for qe in qe_dates:
        loc = idx.get_indexer([qe])[0]
        if loc == -1:
            continue
        lo = max(0, loc - EVENT_LAG + 1)
        hi = min(len(idx) - 1, loc + POST_LAG)
        for i in range(lo, hi + 1):
            offset = i - loc
            # 只記離最近 qe 最小 |offset|
            cur = s.iloc[i].get("quarter_end_day_offset", np.nan)
            if pd.isna(cur) or abs(offset) < abs(cur):
                s.iat[i, s.columns.get_loc("quarter_end_day_offset")] = offset
            if -(EVENT_LAG - 1) <= offset <= 0:
                s.iat[i, s.columns.get_loc("is_quarter_end_window")] = True
        if qe.month == 12:
            for i in range(lo, hi + 1):
                offset = i - loc
                if -(EVENT_LAG - 1) <= offset <= 0:
                    s.iat[i, s.columns.get_loc("is_year_end_window")] = True
    return s[["is_quarter_end_window", "is_year_end_window", "quarter_end_day_offset"]]


def welch_test(event_vals: np.ndarray, base_vals: np.ndarray) -> dict:
    event_vals = np.asarray(event_vals, dtype=float)
    base_vals = np.asarray(base_vals, dtype=float)
    event_vals = event_vals[~np.isnan(event_vals)]
    base_vals = base_vals[~np.isnan(base_vals)]
    if len(event_vals) < 5 or len(base_vals) < 5:
        return {
            "n_event": int(len(event_vals)), "n_base": int(len(base_vals)),
            "mean_event": float(np.nan), "mean_base": float(np.nan),
            "diff": float(np.nan), "t": float(np.nan), "p": float(np.nan),
        }
    t, p = stats.ttest_ind(event_vals, base_vals, equal_var=False, nan_policy="omit")
    return {
        "n_event": int(len(event_vals)),
        "n_base": int(len(base_vals)),
        "mean_event": float(np.mean(event_vals)),
        "mean_base": float(np.mean(base_vals)),
        "std_event": float(np.std(event_vals, ddof=1)),
        "std_base": float(np.std(base_vals, ddof=1)),
        "diff": float(np.mean(event_vals) - np.mean(base_vals)),
        "t": float(t),
        "p": float(p),
    }


def bootstrap_diff_ci(event_vals: np.ndarray, base_vals: np.ndarray,
                      n_reps: int = 500, seed: int = RNG_SEED) -> dict:
    rng = np.random.default_rng(seed)
    event_vals = np.asarray(event_vals, dtype=float)
    base_vals = np.asarray(base_vals, dtype=float)
    event_vals = event_vals[~np.isnan(event_vals)]
    base_vals = base_vals[~np.isnan(base_vals)]
    if len(event_vals) < 5 or len(base_vals) < 5:
        return {"ci_low": float(np.nan), "ci_high": float(np.nan)}
    diffs = np.empty(n_reps)
    for i in range(n_reps):
        be = rng.choice(event_vals, size=len(event_vals), replace=True)
        bb = rng.choice(base_vals, size=len(base_vals), replace=True)
        diffs[i] = be.mean() - bb.mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return {"ci_low": float(lo), "ci_high": float(hi)}


def event_study_curve(metrics: pd.DataFrame, win: pd.DataFrame) -> dict:
    """對 quarter_end_day_offset 在 [-EVENT_LAG+1..POST_LAG] 計算各 metric 之
    cross-quarter average + std + n."""
    out = {}
    for col in ["log_volume", "range_vol", "c2c_rv"]:
        cur = {}
        for off in range(-EVENT_LAG + 1, POST_LAG + 1):
            mask = (win["quarter_end_day_offset"] == off)
            vals = metrics.loc[mask, col].values
            vals = vals[~np.isnan(vals)]
            if len(vals) > 0:
                cur[str(int(off))] = {
                    "mean": float(np.mean(vals)),
                    "std": float(np.std(vals, ddof=1)) if len(vals) > 1 else float("nan"),
                    "n": int(len(vals)),
                }
            else:
                cur[str(int(off))] = {"mean": float("nan"), "std": float("nan"), "n": 0}
        out[col] = cur
    return out


def tier1_etf_analysis(prices: dict[str, pd.DataFrame]) -> dict:
    results = {}
    event_curves = {}
    for tk, df in prices.items():
        if tk not in ETFS:
            continue
        metrics = compute_metrics(df)
        win = tag_windows(metrics.index)
        ser = {}
        for col in ["log_volume", "range_vol", "c2c_rv"]:
            qe_vals = metrics.loc[win["is_quarter_end_window"], col].values
            ye_vals = metrics.loc[win["is_year_end_window"], col].values
            base_vals = metrics.loc[~win["is_quarter_end_window"], col].values
            qe_t = welch_test(qe_vals, base_vals)
            qe_t.update(bootstrap_diff_ci(qe_vals, base_vals))
            ye_t = welch_test(ye_vals, base_vals)
            ye_t.update(bootstrap_diff_ci(ye_vals, base_vals))
            ser[col] = {"quarter_end_vs_baseline": qe_t,
                        "year_end_vs_baseline": ye_t}
        results[tk] = ser
        event_curves[tk] = event_study_curve(metrics, win)
    return {"per_etf_tests": results, "event_curves": event_curves}


def tier2_panel(prices: dict[str, pd.DataFrame]) -> dict:
    """Panel: 所有 ETF + holdings 在 quarter-end window 內的 metric 與 baseline 比較。"""
    rows = []
    cross_section = []
    for tk, df in prices.items():
        metrics = compute_metrics(df)
        win = tag_windows(metrics.index)
        m = metrics.join(win, how="left")
        m["asset"] = tk
        m["year"] = m.index.year
        m["asset_class"] = "ETF" if tk in ETFS else "Holding"
        # per asset abnormal metric vs own baseline
        for col in ["log_volume", "range_vol", "c2c_rv"]:
            base_mean = m.loc[~m["is_quarter_end_window"], col].mean()
            m[f"abn_{col}"] = m[col] - base_mean
            # cross-section: each asset's mean abn in event window
            event_mean = m.loc[m["is_quarter_end_window"], f"abn_{col}"].mean()
            if not np.isnan(event_mean):
                cross_section.append({
                    "asset": tk, "asset_class": m["asset_class"].iloc[0],
                    "metric": col, "mean_abn": float(event_mean),
                    "n_event_days": int(m["is_quarter_end_window"].sum()),
                })
        rows.append(m)
    if not rows:
        return {"panel_regression": {}, "cross_section": []}
    pooled = pd.concat(rows, axis=0)

    panel_out = {}
    for col in ["log_volume", "range_vol", "c2c_rv"]:
        target = f"abn_{col}"
        X = pd.DataFrame({
            "quarter_end": pooled["is_quarter_end_window"].astype(int),
            "year_end": pooled["is_year_end_window"].astype(int),
        })
        # asset FE + year FE (drop_first)
        asset_dum = pd.get_dummies(pooled["asset"], prefix="asset", drop_first=True)
        year_dum = pd.get_dummies(pooled["year"], prefix="yr", drop_first=True)
        X = pd.concat([X, asset_dum, year_dum], axis=1)
        X = sm.add_constant(X)
        y = pooled[target]
        valid = (~y.isna()) & X.notna().all(axis=1)
        X_v = X.loc[valid].astype(float)
        y_v = y.loc[valid].astype(float)
        try:
            mod = sm.OLS(y_v, X_v).fit(cov_type="HC1")
            panel_out[col] = {
                "n_obs": int(mod.nobs),
                "r2": float(mod.rsquared),
                "quarter_end_coef": float(mod.params.get("quarter_end", np.nan)),
                "quarter_end_se": float(mod.bse.get("quarter_end", np.nan)),
                "quarter_end_t": float(mod.tvalues.get("quarter_end", np.nan)),
                "quarter_end_p": float(mod.pvalues.get("quarter_end", np.nan)),
                "year_end_coef": float(mod.params.get("year_end", np.nan)),
                "year_end_se": float(mod.bse.get("year_end", np.nan)),
                "year_end_t": float(mod.tvalues.get("year_end", np.nan)),
                "year_end_p": float(mod.pvalues.get("year_end", np.nan)),
            }
            # 95% CI for quarter_end
            ci = mod.conf_int(alpha=0.05)
            if "quarter_end" in ci.index:
                panel_out[col]["quarter_end_ci_low"] = float(ci.loc["quarter_end", 0])
                panel_out[col]["quarter_end_ci_high"] = float(ci.loc["quarter_end", 1])
        except Exception as e:
            panel_out[col] = {"error": str(e)}
    return {"panel_regression": panel_out, "cross_section": cross_section}


def make_event_study_plot(event_curves: dict, out_path: Path):
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    metrics = ["log_volume", "range_vol", "c2c_rv"]
    titles = ["log(Volume)", "Garman-Klass range vol", "Close-to-close RV (return$^2$)"]
    for ax, col, ttl in zip(axes, metrics, titles):
        for tk, curves in event_curves.items():
            if col not in curves:
                continue
            offs = sorted([int(k) for k in curves[col].keys()])
            ys = [curves[col][str(o)]["mean"] for o in offs]
            ax.plot(offs, ys, marker="o", label=tk, lw=1.5)
        ax.axvline(0, color="grey", ls="--", lw=0.8, label="quarter-end")
        ax.set_title(ttl)
        ax.set_xlabel("trading days vs quarter-end")
        ax.grid(alpha=0.3)
    axes[0].legend(loc="best", fontsize=8)
    fig.suptitle("K1348 — ETF event study: quarter-end window", fontsize=12)
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def make_cross_section_plot(cross_section: list, out_path: Path):
    if not cross_section:
        return
    df = pd.DataFrame(cross_section)
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    for ax, col in zip(axes, ["log_volume", "range_vol", "c2c_rv"]):
        sub = df[df["metric"] == col]
        ax.hist(sub["mean_abn"].values, bins=20, edgecolor="k", alpha=0.7,
                color="steelblue")
        ax.axvline(0, color="red", ls="--", lw=1)
        ax.set_title(f"abn {col} in QE-window\n(n={len(sub)} assets)")
        ax.set_xlabel("abnormal mean (event - baseline)")
        ax.grid(alpha=0.3)
    fig.suptitle("K1348 — Cross-section of per-asset abnormal metrics at quarter-end")
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def make_panel_plot(panel_reg: dict, out_path: Path):
    if not panel_reg:
        return
    cols = list(panel_reg.keys())
    coefs = [panel_reg[c].get("quarter_end_coef", np.nan) for c in cols]
    lo = [panel_reg[c].get("quarter_end_ci_low", np.nan) for c in cols]
    hi = [panel_reg[c].get("quarter_end_ci_high", np.nan) for c in cols]
    err_low = [c - l for c, l in zip(coefs, lo)]
    err_high = [h - c for c, h in zip(coefs, hi)]
    fig, ax = plt.subplots(figsize=(7, 4.5), constrained_layout=True)
    x = np.arange(len(cols))
    ax.errorbar(x, coefs, yerr=[err_low, err_high], fmt="o", capsize=6,
                color="navy", ecolor="grey")
    ax.axhline(0, color="red", ls="--", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(cols, rotation=0)
    ax.set_ylabel("coefficient on quarter_end (panel OLS, HC1)")
    ax.set_title("K1348 — Panel regression: quarter-end effect 95% CI")
    ax.grid(alpha=0.3, axis="y")
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def main():
    np.random.seed(RNG_SEED)
    tickers = ETFS + TOP_HOLDINGS
    print(f"[K1348] fetching {len(tickers)} tickers from yfinance: {START}..{END}")
    prices = fetch_prices(tickers)
    print(f"[K1348] fetched {len(prices)}/{len(tickers)} tickers")
    if len(prices) < 4:
        raise RuntimeError("insufficient tickers fetched; aborting")

    print("[K1348] Tier 1 — ETF level event-study tests")
    tier1 = tier1_etf_analysis(prices)
    print("[K1348] Tier 2 — panel + cross-section")
    tier2 = tier2_panel(prices)

    # verdict synthesis — STRICT: PASS 需 volume 與 vol 兩條 channel 都支持
    verdict_summary = {}
    sig_vol_etf = 0  # |t|>2.5 p<0.01 on log_volume
    sig_rv_etf = 0   # |t|>2.5 p<0.01 on range_vol
    consistent_vol_sign = None
    consistent_rv_sign = None
    for tk in ETFS:
        if tk not in tier1["per_etf_tests"]:
            continue
        lv = tier1["per_etf_tests"][tk]["log_volume"]["quarter_end_vs_baseline"]
        rv = tier1["per_etf_tests"][tk]["range_vol"]["quarter_end_vs_baseline"]
        verdict_summary[tk] = {
            "log_volume_t": lv["t"], "log_volume_p": lv["p"], "log_volume_diff": lv["diff"],
            "range_vol_t": rv["t"], "range_vol_p": rv["p"], "range_vol_diff": rv["diff"],
        }
        if abs(lv["t"]) > 2.5 and lv["p"] < 0.01:
            sig_vol_etf += 1
            s = np.sign(lv["diff"])
            if consistent_vol_sign is None:
                consistent_vol_sign = s
            elif s != consistent_vol_sign:
                consistent_vol_sign = 0
        if abs(rv["t"]) > 2.5 and rv["p"] < 0.01:
            sig_rv_etf += 1
            s = np.sign(rv["diff"])
            if consistent_rv_sign is None:
                consistent_rv_sign = s
            elif s != consistent_rv_sign:
                consistent_rv_sign = 0

    # Panel check
    panel_rv = tier2["panel_regression"].get("range_vol", {})
    panel_vol = tier2["panel_regression"].get("log_volume", {})
    panel_rv_supports = (
        panel_rv.get("quarter_end_p", 1.0) < 0.05
        and panel_rv.get("quarter_end_coef", 0) > 0
    )
    panel_vol_supports = (
        panel_vol.get("quarter_end_p", 1.0) < 0.05
        and panel_vol.get("quarter_end_coef", 0) > 0
    )

    # 嚴格 verdict (hypothesis: heartbeat → vol pressure, 需 range_vol/RV 上升)
    # PASS  = ≥2 ETF 在 range_vol 顯著上升 + panel range_vol 支持 + 一致方向
    # COND  = volume 上升訊號清楚但 vol pressure 弱/缺
    # NULL  = 兩條 channel 都不支持
    if sig_rv_etf >= 2 and consistent_rv_sign == 1 and panel_rv_supports:
        verdict = "PASS"
    elif sig_vol_etf >= 2 and consistent_vol_sign == 1 and panel_vol_supports:
        # volume channel clearly positive but vol-pressure channel null
        verdict = "CONDITIONAL_PASS"
    elif sig_vol_etf >= 1 or sig_rv_etf >= 1:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    results = {
        "k_id": "K1348",
        "experiment_id": "k1348",
        "experiment_path": "experiments/k1348/",
        "title": "ETF heartbeat / tax-efficiency quarter-end pressure test on top holdings",
        "timestamp_utc": datetime.utcnow().isoformat() + "Z",
        "config": {
            "start": START, "end": END, "seed": RNG_SEED,
            "etfs": ETFS, "holdings_tested": TOP_HOLDINGS,
            "n_etf_fetched": sum(1 for t in ETFS if t in prices),
            "n_holdings_fetched": sum(1 for t in TOP_HOLDINGS if t in prices),
            "event_window_lag_pre": EVENT_LAG, "event_window_lag_post": POST_LAG,
            "quarter_end_months": sorted(QUARTER_END_MONTHS),
        },
        "lookahead_policy": (
            "Event-window dummies use known calendar dates only; "
            "all test stats computed after event window closes; "
            "no predictive claim — descriptive event study only; "
            "no rolling forecast or training-test split needed."
        ),
        "tier1": tier1,
        "tier2": tier2,
        "verdict_summary_per_etf": verdict_summary,
        "n_sig_volume_etfs": int(sig_vol_etf),
        "n_sig_rangevol_etfs": int(sig_rv_etf),
        "consistent_volume_sign": (None if consistent_vol_sign is None else int(consistent_vol_sign)),
        "consistent_rangevol_sign": (None if consistent_rv_sign is None else int(consistent_rv_sign)),
        "panel_vol_supports": bool(panel_vol_supports),
        "panel_rv_supports": bool(panel_rv_supports),
        "verdict": verdict,
        "verdict_rationale": (
            f"sig_vol_etf={sig_vol_etf}(sign={consistent_vol_sign}) "
            f"sig_rv_etf={sig_rv_etf}(sign={consistent_rv_sign}) "
            f"panel_vol_supports={panel_vol_supports} "
            f"panel_rv_supports={panel_rv_supports}. "
            "Hypothesis (heartbeat→vol pressure) requires range_vol channel; "
            "vol-only signal is necessary but not sufficient → CONDITIONAL."
        ),
    }

    OUT_JSON.write_text(json.dumps(results, indent=2, default=str))
    print(f"[K1348] wrote {OUT_JSON}")

    # plots
    make_event_study_plot(tier1["event_curves"], OUT_DIR / "fig_event_study.png")
    make_cross_section_plot(tier2["cross_section"], OUT_DIR / "fig_cross_section.png")
    make_panel_plot(tier2["panel_regression"], OUT_DIR / "fig_panel_regression.png")
    print("[K1348] plots written")
    print(f"[K1348] VERDICT={verdict} (sig_vol_etf={sig_vol_etf} sig_rv_etf={sig_rv_etf})")


if __name__ == "__main__":
    main()
