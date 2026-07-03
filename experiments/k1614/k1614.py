#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1614 — Descriptive Volatility-Structure Diagnostic of Natural-Resource Real Assets

誠實的描述性 / 截面波動率結構診斷（NON-tradable，不做策略回測、不宣稱可交易訊號）。

核心問題：
  1. 農地 / 林地 / 水資源這一籃「實質資產」的已實現波動率(RV)是否形成一致 vol cluster？
  2. 市場高波動 regime 下，它們的 vol 是放大還是相對穩定（避風港特性）？
  3. 各檔對大盤(SPY) 的 vol beta 為何（<1 = vol 較大盤鈍）？

方法論誠實原則:
  - RV = rolling std of daily log returns, annualized (× sqrt(252))。純描述性。
  - 沒有預測性 / 可交易宣稱；因此沒有 signal→return 的 lookahead 風險。
    唯一涉及「時序方向」的是 vol beta 的 contemporaneous OLS（RV_asset_t ~ RV_SPY_t），
    這是描述性同期關係，不是預測。若要做任何 predictive lag，會明確 shift(1)（本實驗未做預測）。
  - 重疊窗口(rolling)自相關會膨脹樣本量 → Welch t-test p-value 被高估。
    因此: (a) 報標準 Welch t/p 但明確 caveat, (b) 報 Cohen's d 效果量（對 n 不敏感）,
    (c) 補非重疊(每 21 日)子樣本 Welch t-test 作 robustness。
  - RV level 相關天然偏高（共同市場趨勢）→ 額外報 ΔRV 差分相關作更嚴格共動指標。
  - Seed 固定 = 42（本描述性實驗無隨機程序，仍固定以符合規範）。

Run: uv run python experiments/k1614/k1614.py
Output: k1614_results.json + figures/*.png
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)  # 固定 seed（本實驗無隨機程序，仍依規範固定）

HERE = Path(__file__).resolve().parent
FIG_DIR = HERE / "figures"
FIG_DIR.mkdir(exist_ok=True)

START = "2015-01-01"
END = "2026-07-01"

# 實質資產籃 (7) 三子群
FARMLAND = ["LAND", "FPI"]        # 農地 REIT
TIMBER = ["WY", "RYN"]            # 林地 REIT
WATER = ["PHO", "CGW", "FIW"]     # 水資源 ETF
REAL_ASSETS = FARMLAND + TIMBER + WATER  # 7

# 對照 proxy (3)
CONTROLS = ["SPY", "TIP", "DBC"]  # 大盤 / 通膨連結債 / 商品
ALL_TICKERS = REAL_ASSETS + CONTROLS

SUBGROUPS = {"farmland": FARMLAND, "timber": TIMBER, "water": WATER}

TRADING_DAYS = 252
RV_WINDOWS = {"rv21": 21, "rv63": 63}
PRIMARY = "rv21"  # 主分析用 21d RV


# ----------------------------------------------------------------------------
# 資料抓取
# ----------------------------------------------------------------------------
def fetch_prices():
    """抓 adjusted close（auto_adjust=True，一致用於 log-return RV）。"""
    import yfinance as yf

    raw = yf.download(
        ALL_TICKERS,
        start=START,
        end=END,
        auto_adjust=True,     # adjusted close：一致口徑，純描述性 RV 適用
        progress=False,
        group_by="column",
    )
    # 多 ticker → MultiIndex columns，取 'Close' 層
    if isinstance(raw.columns, pd.MultiIndex):
        px = raw["Close"].copy()
    else:
        px = raw[["Close"]].copy()
        px.columns = ALL_TICKERS[:1]
    px = px[[t for t in ALL_TICKERS if t in px.columns]]
    px.index = pd.to_datetime(px.index)
    px = px.sort_index()
    return px


# ----------------------------------------------------------------------------
# RV 計算
# ----------------------------------------------------------------------------
def compute_rv(px):
    """log return + annualized rolling std RV（21d, 63d）。"""
    logret = np.log(px / px.shift(1))
    rv = {}
    for name, w in RV_WINDOWS.items():
        rv[name] = logret.rolling(w).std() * np.sqrt(TRADING_DAYS)
    return logret, rv


# ----------------------------------------------------------------------------
# (a) 描述統計表
# ----------------------------------------------------------------------------
def descriptive_stats(rv21):
    out = {}
    for t in ALL_TICKERS:
        s = rv21[t].dropna()
        if s.empty:
            out[t] = {"n": 0}
            continue
        current = float(s.iloc[-1])
        pct = float((s < current).mean() * 100.0)  # 當前值歷史百分位
        out[t] = {
            "n": int(s.shape[0]),
            "mean": float(s.mean()),
            "median": float(s.median()),
            "std": float(s.std()),
            "min": float(s.min()),
            "max": float(s.max()),
            "current": current,
            "current_date": str(s.index[-1].date()),
            "current_percentile": round(pct, 2),
        }
    return out


# ----------------------------------------------------------------------------
# (b) Vol cluster 一致性：7 檔實質資產 21d RV 相關矩陣
# ----------------------------------------------------------------------------
def cluster_consistency(rv21):
    sub = rv21[REAL_ASSETS].dropna()
    n_common = int(sub.shape[0])
    corr = sub.corr(method="pearson")

    # 平均 pairwise corr（off-diagonal）
    def avg_offdiag(cmat, cols):
        m = cmat.loc[cols, cols].values
        iu = np.triu_indices(len(cols), k=1)
        return float(np.mean(m[iu])) if len(iu[0]) else float("nan")

    overall_avg = avg_offdiag(corr, REAL_ASSETS)

    # 子群內平均 corr
    within = {g: (avg_offdiag(corr, cols) if len(cols) > 1 else None)
              for g, cols in SUBGROUPS.items()}

    # 子群間平均 corr（跨群 pair 平均）
    between = {}
    gkeys = list(SUBGROUPS.keys())
    for i in range(len(gkeys)):
        for j in range(i + 1, len(gkeys)):
            ga, gb = gkeys[i], gkeys[j]
            vals = [corr.loc[a, b] for a in SUBGROUPS[ga] for b in SUBGROUPS[gb]]
            between[f"{ga}_vs_{gb}"] = float(np.mean(vals))

    # robustness: ΔRV 差分相關（去共同趨勢後的短期 vol 衝擊共動）
    dsub = sub.diff().dropna()
    dcorr = dsub.corr(method="pearson")
    davg = avg_offdiag(dcorr, REAL_ASSETS)

    return {
        "n_common_obs": n_common,
        "corr_matrix": {a: {b: round(float(corr.loc[a, b]), 4) for b in REAL_ASSETS}
                        for a in REAL_ASSETS},
        "avg_pairwise_corr": round(overall_avg, 4),
        "within_subgroup_avg_corr": {k: (round(v, 4) if v is not None else None)
                                     for k, v in within.items()},
        "between_subgroup_avg_corr": {k: round(v, 4) for k, v in between.items()},
        "diff_rv_avg_pairwise_corr": round(davg, 4),
        "diff_rv_note": ("ΔRV(一階差分)相關去除共同 vol 趨勢，反映短期波動衝擊的真實共動；"
                         "遠低於 level 相關代表 level 相關多來自共同市場趨勢而非同步 shock。"),
    }, corr


# ----------------------------------------------------------------------------
# (c) 市場 regime 對照：SPY 21d RV 三分位
# ----------------------------------------------------------------------------
def cohens_d(a, b):
    na, nb = len(a), len(b)
    va, vb = np.var(a, ddof=1), np.var(b, ddof=1)
    sp = np.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2))
    return float((np.mean(a) - np.mean(b)) / sp) if sp > 0 else float("nan")


def regime_analysis(rv21):
    from scipy import stats

    aligned = rv21[[*REAL_ASSETS, "SPY"]].dropna()
    spy = aligned["SPY"]
    q1, q2 = spy.quantile([1 / 3, 2 / 3])
    regime = pd.Series(index=aligned.index, dtype=object)
    regime[spy <= q1] = "low"
    regime[(spy > q1) & (spy <= q2)] = "mid"
    regime[spy > q2] = "high"

    counts = regime.value_counts().to_dict()
    # assert 各分位非空（K1128 教訓：degenerate tertile 防呆）
    for r in ("low", "mid", "high"):
        assert counts.get(r, 0) > 0, f"regime {r} empty — tertile degenerate"

    # 非重疊子樣本（每 21 列取一）供 robustness t-test
    idx_nonoverlap = np.arange(0, len(aligned), RV_WINDOWS["rv21"])
    nonoverlap_mask = np.zeros(len(aligned), dtype=bool)
    nonoverlap_mask[idx_nonoverlap] = True

    per_asset = {}
    for t in REAL_ASSETS:
        s = aligned[t]
        full_mean = float(s.mean())
        by_regime = {}
        for r in ("low", "mid", "high"):
            m = regime == r
            vals = s[m]
            by_regime[r] = {
                "mean_rv": round(float(vals.mean()), 4),
                "ratio_to_own_full_mean": round(float(vals.mean()) / full_mean, 4),
                "n": int(vals.shape[0]),
            }
        low_vals = s[regime == "low"].values
        high_vals = s[regime == "high"].values
        # 標準 Welch（p 因重疊窗口自相關被高估 — 見 caveat）
        tt = stats.ttest_ind(high_vals, low_vals, equal_var=False)
        d = cohens_d(high_vals, low_vals)
        # 非重疊 robustness Welch
        s_no = s[nonoverlap_mask]
        r_no = regime[nonoverlap_mask]
        low_no = s_no[r_no == "low"].values
        high_no = s_no[r_no == "high"].values
        if len(low_no) >= 3 and len(high_no) >= 3:
            tt_no = stats.ttest_ind(high_no, low_no, equal_var=False)
            no_res = {"t": round(float(tt_no.statistic), 4),
                      "p": round(float(tt_no.pvalue), 6),
                      "n_high": int(len(high_no)), "n_low": int(len(low_no))}
        else:
            no_res = None
        per_asset[t] = {
            "full_mean_rv": round(full_mean, 4),
            "by_regime": by_regime,
            "high_vs_low_welch_t": round(float(tt.statistic), 4),
            "high_vs_low_welch_p": float(tt.pvalue),
            "cohens_d_high_vs_low": round(d, 4),
            "high_low_ratio": round(by_regime["high"]["mean_rv"] / by_regime["low"]["mean_rv"], 4),
            "nonoverlap_robustness_welch": no_res,
        }

    return {
        "regime_definition": "SPY 21d RV full-sample tertiles (low/mid/high)",
        "spy_rv_tertile_cutoffs": {"q33": round(float(q1), 4), "q67": round(float(q2), 4)},
        "regime_counts": {k: int(v) for k, v in counts.items()},
        "n_aligned_obs": int(aligned.shape[0]),
        "caveat_overlapping_windows": (
            "21d rolling RV 每日值高度自相關 → 標準 Welch t-test 的有效樣本量遠小於 n，"
            "p-value 被系統性高估。請以 Cohen's d 效果量與非重疊子樣本 robustness t-test 為準。"),
        "per_asset": per_asset,
    }, regime, aligned


# ----------------------------------------------------------------------------
# (d) Vol beta：每檔實質資產 21d RV 對 SPY 21d RV 的 OLS
# ----------------------------------------------------------------------------
def vol_beta(rv21):
    aligned = rv21[[*REAL_ASSETS, "SPY"]].dropna()
    x = aligned["SPY"].values
    out = {}
    for t in REAL_ASSETS:
        y = aligned[t].values
        X = np.column_stack([np.ones_like(x), x])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        yhat = X @ beta
        resid = y - yhat
        ss_res = float(np.sum(resid ** 2))
        ss_tot = float(np.sum((y - y.mean()) ** 2))
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
        n, k = len(y), 2

        # HAC (Newey-West) SE — 重疊窗口 residual 高度自相關，OLS SE 會低估
        L = int(np.floor(4 * (n / 100.0) ** (2 / 9)))  # Newey-West rule of thumb
        Xres = X * resid[:, None]
        S = Xres.T @ Xres
        for lag in range(1, L + 1):
            w = 1 - lag / (L + 1)
            G = Xres[lag:].T @ Xres[:-lag]
            S += w * (G + G.T)
        XtX_inv = np.linalg.inv(X.T @ X)
        cov_hac = XtX_inv @ S @ XtX_inv
        se_slope_hac = float(np.sqrt(cov_hac[1, 1]))
        t_slope_hac = float(beta[1] / se_slope_hac) if se_slope_hac > 0 else float("nan")

        _slope = float(beta[1])
        if _slope < 1.0:
            _interp = "beta<1 = vol 對市場 vol 反應弱（較大盤鈍）"
        else:
            _interp = "beta>1 = vol 對市場 vol 反應強（放大大盤 vol 變動）"
        out[t] = {
            "vol_beta_slope": round(_slope, 4),
            "intercept": round(float(beta[0]), 4),
            "r_squared": round(float(r2), 4),
            "hac_se_slope": round(se_slope_hac, 4),
            "hac_t_slope": round(t_slope_hac, 2),
            "hac_lag": int(L),
            "n": int(n),
            "interpretation": _interp,
        }
    return {
        "spec": "OLS: RV_asset_t ~ 1 + RV_SPY_t (contemporaneous 21d RV, 描述性非預測)",
        "hac_note": "Newey-West HAC SE 校正重疊窗口 residual 自相關（OLS SE 會低估）",
        "per_asset": out,
    }, aligned


# ----------------------------------------------------------------------------
# 圖表
# ----------------------------------------------------------------------------
def make_figures(rv21, corr, regime_res, regime, aligned):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Fig 1: 10 檔 21d RV 時序
    fig, ax = plt.subplots(figsize=(13, 7))
    cmap = plt.get_cmap("tab10")
    for i, t in enumerate(ALL_TICKERS):
        s = rv21[t].dropna()
        lw = 2.2 if t == "SPY" else 1.1
        alpha = 1.0 if t in REAL_ASSETS or t == "SPY" else 0.6
        ax.plot(s.index, s.values, label=t, color=cmap(i % 10), lw=lw, alpha=alpha)
    ax.set_title("K1614 — 21-Day Annualized Realized Volatility (2015–2026)\n"
                 "Natural-Resource Real Assets (7) vs Market/Inflation/Commodity Proxies (3)",
                 fontsize=12)
    ax.set_xlabel("Date"); ax.set_ylabel("Annualized RV")
    ax.legend(ncol=5, fontsize=8, loc="upper right")
    ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(FIG_DIR / "fig1_rv_timeseries.png", dpi=130)
    plt.close(fig)

    # Fig 2: 7 檔實質資產 RV 相關熱圖
    fig, ax = plt.subplots(figsize=(8, 7))
    m = corr.loc[REAL_ASSETS, REAL_ASSETS].values
    im = ax.imshow(m, cmap="RdYlGn_r", vmin=0, vmax=1)
    ax.set_xticks(range(len(REAL_ASSETS))); ax.set_xticklabels(REAL_ASSETS, rotation=45, ha="right")
    ax.set_yticks(range(len(REAL_ASSETS))); ax.set_yticklabels(REAL_ASSETS)
    for i in range(len(REAL_ASSETS)):
        for j in range(len(REAL_ASSETS)):
            ax.text(j, i, f"{m[i, j]:.2f}", ha="center", va="center",
                    color="black", fontsize=9)
    ax.set_title("K1614 — 21d RV Pearson Correlation\n"
                 "Real-Asset Basket (Farmland/Timber/Water)", fontsize=12)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    fig.tight_layout(); fig.savefig(FIG_DIR / "fig2_rv_corr_heatmap.png", dpi=130)
    plt.close(fig)

    # Fig 3: 各 regime 下實質資產平均 RV bar chart
    fig, ax = plt.subplots(figsize=(13, 7))
    regimes = ["low", "mid", "high"]
    x = np.arange(len(REAL_ASSETS))
    width = 0.26
    colors = {"low": "#2ca02c", "mid": "#ff7f0e", "high": "#d62728"}
    for k, r in enumerate(regimes):
        vals = [regime_res["per_asset"][t]["by_regime"][r]["mean_rv"] for t in REAL_ASSETS]
        ax.bar(x + (k - 1) * width, vals, width, label=f"{r} market-vol regime",
               color=colors[r])
    ax.set_xticks(x); ax.set_xticklabels(REAL_ASSETS)
    ax.set_ylabel("Mean 21d Annualized RV")
    ax.set_title("K1614 — Real-Asset Mean RV by SPY Volatility Regime\n"
                 "(SPY 21d RV full-sample tertiles)", fontsize=12)
    ax.legend(); ax.grid(axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(FIG_DIR / "fig3_regime_bar.png", dpi=130)
    plt.close(fig)


# ----------------------------------------------------------------------------
# main
# ----------------------------------------------------------------------------
def main():
    print("[K1614] fetching prices ...")
    px = fetch_prices()
    n_by_asset = {t: int(px[t].dropna().shape[0]) for t in ALL_TICKERS}
    print(f"[K1614] price obs per asset: {n_by_asset}")

    logret, rv = compute_rv(px)
    rv21 = rv[PRIMARY]

    print("[K1614] (a) descriptive stats ...")
    desc = descriptive_stats(rv21)

    print("[K1614] (b) cluster consistency ...")
    cluster, corr = cluster_consistency(rv21)

    print("[K1614] (c) regime analysis ...")
    regime_res, regime, aligned = regime_analysis(rv21)

    print("[K1614] (d) vol beta ...")
    beta_res, _ = vol_beta(rv21)

    print("[K1614] figures ...")
    make_figures(rv21, corr, regime_res, regime, aligned)

    results = {
        "experiment_id": "k1614",
        "title": "Descriptive Volatility-Structure Diagnostic of Natural-Resource Real Assets",
        "claim_type": "DESCRIPTIVE / CROSS-SECTIONAL — non-tradable, no signal claim",
        "metadata": {
            "data_source": "yfinance (auto_adjust=True, adjusted close)",
            "period": {"start": START, "end": END},
            "generated_by": "experiments/k1614/k1614.py",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "seed": SEED,
            "trading_days_per_year": TRADING_DAYS,
            "rv_windows": RV_WINDOWS,
            "primary_rv_window": PRIMARY,
            "n_obs_per_asset": n_by_asset,
            "real_asset_basket": REAL_ASSETS,
            "subgroups": SUBGROUPS,
            "control_proxies": CONTROLS,
        },
        "data_provenance_notes": {
            "FPI_2018_short_attack": (
                "FPI 最大單日 log-return = 2018-07-11 −0.4936 (~−39%)，為 Rota Fortunae "
                "做空報告攻擊之真實公司特定事件（非資料 artifact），驅動 FPI RV max≈1.87、"
                "低 regime 敏感度與低 vol-beta R²，強化 farmland idiosyncratic 之發現。"),
        },
        "a_descriptive_stats_rv21": desc,
        "b_cluster_consistency": cluster,
        "c_regime_analysis": regime_res,
        "d_vol_beta": beta_res,
    }

    out_path = HERE / "k1614_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    print(f"[K1614] wrote {out_path}")
    print(f"[K1614] avg pairwise corr (7 real assets, level) = {cluster['avg_pairwise_corr']}")
    print(f"[K1614] avg pairwise corr (ΔRV diff) = {cluster['diff_rv_avg_pairwise_corr']}")
    for t in REAL_ASSETS:
        b = beta_res["per_asset"][t]
        print(f"[K1614]   {t}: vol_beta={b['vol_beta_slope']}, R2={b['r_squared']}, "
              f"HAC_t={b['hac_t_slope']}")


if __name__ == "__main__":
    main()
