#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K_TAIEX_60K_SCENARIO — Rotation / Big-Rally Preparation study
================================================================
研究問題：台股「大漲段」（滾動 126 交易日報酬 >= +20%）之後，
          (1) 風險面：波動率、後續 63 日最大回撤、報酬 5% 尾部 —— 創高/急漲後是否更安全？
          (2) 產業輪動：大漲段中各產業相對 ^TWII 的超額報酬與波動，誰領漲誰落後？

資料來源：yfinance（auto_adjust=True，含息調整收盤）
期間：2012-01-01 ~ 最新可得交易日（2026-06-18 為止）
誠實規則：
  - 只用真實數據；每個數字標來源/期間/樣本數
  - 任何隨機程序固定 seed=42（block bootstrap 尾部 CI）
  - 無 lookahead：大漲段標記用「截至 t 的過去 126 日報酬」；
    forward-looking 指標（後續 63 日 MDD）明確標為 forward 並只用於「大漲段 t 之後實際發生了什麼」的條件統計，
    不作為任何可交易訊號（純歷史條件規律描述）。

輸出：rotation_results.json + chart PNG（存於同目錄）
"""
import json
import warnings
from datetime import datetime, timezone, timedelta

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

START = "2012-01-01"
END = "2026-06-19"          # yfinance end is exclusive of future; last trading day ~2026-06-18
RALLY_WINDOW = 126          # 滾動視窗 ~半年（交易日）
RALLY_THRESHOLD = 0.20      # 大漲段門檻：過去 126 日報酬 >= +20%
FORWARD_WINDOW = 63         # 後續 ~一季（交易日）最大回撤視窗
VOL_WINDOW = 21             # 已實現波動率視窗（~一個月）
ANNUALIZE = np.sqrt(252)
TAIL_Q = 0.05               # 報酬尾部分位
N_BOOT = 2000               # block bootstrap reps（尾部 CI）
BLOCK = 21                  # bootstrap block 長度（吸收自相關）

# 產業代表（個股 + ETF 交叉驗證），全來自 yfinance .TW
SECTORS = {
    "semiconductor_2330": "2330.TW",   # 台積電 — 半導體龍頭
    "electronics_2317":   "2317.TW",   # 鴻海 — 電子代工
    "shipping_2603":      "2603.TW",   # 長榮 — 航運
    "financial_2882":     "2882.TW",   # 國泰金 — 金融
    "traditional_1301":   "1301.TW",   # 台塑 — 傳產/塑化
    "tech_etf_0052":      "0052.TW",   # 富邦科技 ETF（電子科技）
    "fin_etf_0055":       "0055.TW",   # 元大MSCI金融 ETF
}
SECTOR_LABELS_ZH = {
    "semiconductor_2330": "半導體(台積電2330)",
    "electronics_2317":   "電子代工(鴻海2317)",
    "shipping_2603":      "航運(長榮2603)",
    "financial_2882":     "金融(國泰金2882)",
    "traditional_1301":   "傳產塑化(台塑1301)",
    "tech_etf_0052":      "電子科技ETF(0052)",
    "fin_etf_0055":       "金融ETF(0055)",
}


# TWSE/OTC have a hard daily price limit (+/-10% since 2015-06; +/-7% before).
# Any single-day return beyond this buffer is a data/adjustment ARTIFACT
# (e.g. yfinance mis-adjusted dividend/capital-reduction bar), NOT a tradable
# daily return. We clip such bars to the structural limit and log them, so a
# single bad bar (e.g. 0052.TW -85.7% on 2025-11-17) cannot poison vol/excess stats.
DAILY_LIMIT = 0.11
_DATA_FLAGS = []


def fetch(ticker, clip_limit=True):
    import yfinance as yf
    df = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise RuntimeError(f"empty download {ticker}")
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s.name = ticker
    s = s.dropna()
    if clip_limit and ticker != "^TWII":  # index has no single-stock limit but stays well within anyway
        r = s.pct_change()
        bad = r[r.abs() > DAILY_LIMIT]
        for d, v in bad.items():
            _DATA_FLAGS.append({"ticker": ticker, "date": str(d.date()), "raw_return": float(v),
                                "action": f"clipped to +/-{DAILY_LIMIT}", "reason": "exceeds TWSE daily price limit -> adjustment artifact"})
        if len(bad):
            # rebuild a clipped price series so the artifact bar does not enter return stats
            r_clipped = r.clip(lower=-DAILY_LIMIT, upper=DAILY_LIMIT)
            base0 = s.iloc[0]
            s = base0 * (1 + r_clipped.fillna(0)).cumprod()
            s.name = ticker
    return s.dropna()


def max_drawdown(price_path):
    """price_path: array of prices over a forward window. Returns MDD as negative fraction."""
    if len(price_path) < 2:
        return 0.0
    arr = np.asarray(price_path, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = arr / peak - 1.0
    return float(dd.min())


def block_bootstrap_quantile(returns, q, n_boot, block, seed):
    """Block bootstrap CI for the q-quantile of a return series. Fixed seed."""
    rng = np.random.default_rng(seed)
    r = np.asarray(returns, dtype=float)
    r = r[~np.isnan(r)]
    n = len(r)
    if n < block * 2:
        return (np.nan, np.nan, np.nan)
    n_blocks = int(np.ceil(n / block))
    out = []
    max_start = n - block
    for _ in range(n_boot):
        starts = rng.integers(0, max_start + 1, size=n_blocks)
        sample = np.concatenate([r[s:s + block] for s in starts])[:n]
        out.append(np.quantile(sample, q))
    out = np.array(out)
    return (float(np.quantile(out, 0.025)), float(np.median(out)), float(np.quantile(out, 0.975)))


def main():
    print("=== fetching data ===")
    twii = fetch("^TWII")
    sector_prices = {}
    for k, tk in SECTORS.items():
        sector_prices[k] = fetch(tk)
        print(f"  {k:22s} {tk:9s} rows={len(sector_prices[k])}")

    px = twii.copy()
    px.name = "TWII"
    ret = px.pct_change()
    logret = np.log(px / px.shift(1))

    # ---- 大漲段標記（無 lookahead：截至 t 的過去 126 日報酬）----
    roll_126 = px / px.shift(RALLY_WINDOW) - 1.0
    in_rally = (roll_126 >= RALLY_THRESHOLD)

    # ---- 已實現波動率（截至 t 的過去 21 日，annualized）----
    rv = ret.rolling(VOL_WINDOW).std() * ANNUALIZE

    # ---- 後續 63 日最大回撤（forward；僅描述性，非訊號）----
    fwd_mdd = pd.Series(index=px.index, dtype=float)
    pxv = px.values
    idx = px.index
    for i in range(len(pxv) - 1):
        end_i = min(i + FORWARD_WINDOW + 1, len(pxv))
        fwd_mdd.iloc[i] = max_drawdown(pxv[i:end_i])

    # 對齊有效樣本
    base = pd.DataFrame({
        "px": px,
        "ret": ret,
        "rv": rv,
        "roll_126": roll_126,
        "in_rally": in_rally,
        "fwd_mdd": fwd_mdd,
    }).dropna(subset=["rv", "roll_126"])

    rally_mask = base["in_rally"] == True
    other_mask = base["in_rally"] == False

    n_rally = int(rally_mask.sum())
    n_other = int(other_mask.sum())
    n_total = len(base)

    print(f"\n=== rally regime sample ===")
    print(f"  total days={n_total}  rally days={n_rally} ({n_rally/n_total*100:.1f}%)  other={n_other}")

    # ---- 1. 已實現波動率：rally vs other ----
    rv_rally = base.loc[rally_mask, "rv"].dropna()
    rv_other = base.loc[other_mask, "rv"].dropna()

    # ---- 2. 後續 63 日 MDD 分佈：rally vs other（forward，有效樣本需 forward window 完整）----
    valid_fwd = base.dropna(subset=["fwd_mdd"])
    # 只保留有完整 forward window 的點：距離資料末端 >= FORWARD_WINDOW
    cutoff_date = base.index[-1]
    # forward window 完整性：i 必須 <= len-FORWARD_WINDOW-1
    full_fwd_idx = base.index[: max(0, len(base) - FORWARD_WINDOW)]
    vf = base.loc[base.index.isin(full_fwd_idx)].dropna(subset=["fwd_mdd"])
    mdd_rally = vf.loc[vf["in_rally"] == True, "fwd_mdd"]
    mdd_other = vf.loc[vf["in_rally"] == False, "fwd_mdd"]

    # ---- 3. 報酬 5% 尾部：rally vs other（block bootstrap CI）----
    ret_rally = base.loc[rally_mask, "ret"].dropna()
    ret_other = base.loc[other_mask, "ret"].dropna()
    tail_rally = block_bootstrap_quantile(ret_rally.values, TAIL_Q, N_BOOT, BLOCK, SEED)
    tail_other = block_bootstrap_quantile(ret_other.values, TAIL_Q, N_BOOT, BLOCK, SEED + 1)

    # Welch t-test on RV difference (informational)
    from scipy import stats as sstats
    t_rv, p_rv = sstats.ttest_ind(rv_rally, rv_other, equal_var=False)
    t_mdd, p_mdd = sstats.ttest_ind(mdd_rally, mdd_other, equal_var=False)

    risk_block = {
        "realized_vol_annualized": {
            "rally_mean": float(rv_rally.mean()),
            "rally_median": float(rv_rally.median()),
            "rally_p90": float(rv_rally.quantile(0.90)),
            "other_mean": float(rv_other.mean()),
            "other_median": float(rv_other.median()),
            "other_p90": float(rv_other.quantile(0.90)),
            "welch_t": float(t_rv),
            "welch_p": float(p_rv),
            "n_rally": int(len(rv_rally)),
            "n_other": int(len(rv_other)),
        },
        "forward_63d_max_drawdown": {
            "note": "forward-looking conditional stat: what happened in the 63d AFTER each day; descriptive only, not a tradable signal",
            "rally_mean": float(mdd_rally.mean()),
            "rally_median": float(mdd_rally.median()),
            "rally_p10_worst": float(mdd_rally.quantile(0.10)),
            "rally_worst": float(mdd_rally.min()),
            "other_mean": float(mdd_other.mean()),
            "other_median": float(mdd_other.median()),
            "other_p10_worst": float(mdd_other.quantile(0.10)),
            "other_worst": float(mdd_other.min()),
            "welch_t": float(t_mdd),
            "welch_p": float(p_mdd),
            "n_rally": int(len(mdd_rally)),
            "n_other": int(len(mdd_other)),
        },
        "daily_return_5pct_tail": {
            "method": f"block bootstrap (block={BLOCK}, n_boot={N_BOOT}, seed={SEED}) of {int(TAIL_Q*100)}% quantile",
            "rally_q05_ci": {"lo": tail_rally[0], "median": tail_rally[1], "hi": tail_rally[2]},
            "other_q05_ci": {"lo": tail_other[0], "median": tail_other[1], "hi": tail_other[2]},
            "rally_empirical_q05": float(np.quantile(ret_rally.values, TAIL_Q)),
            "other_empirical_q05": float(np.quantile(ret_other.values, TAIL_Q)),
            "n_rally": int(len(ret_rally)),
            "n_other": int(len(ret_other)),
        },
    }

    # ---- 4. 產業輪動：大漲段中各產業相對 TWII 超額報酬與波動 ----
    # 對齊每個 sector 與 TWII，計算 sector 日報酬 - TWII 日報酬（超額）
    rotation = {}
    twii_ret_aligned = ret.copy()
    for k, sp in sector_prices.items():
        sret = sp.pct_change()
        df = pd.DataFrame({"s": sret, "t": twii_ret_aligned, "rally": in_rally}).dropna()
        # 大漲段 vs 其他
        rally_d = df[df["rally"] == True]
        other_d = df[df["rally"] == False]
        excess_rally = (rally_d["s"] - rally_d["t"])
        excess_other = (other_d["s"] - other_d["t"])
        # 累積超額報酬（in-rally 期間複利相對表現）
        # 用日報酬幾何累積差近似相對表現
        cum_rally_s = float((1 + rally_d["s"]).prod() - 1) if len(rally_d) else np.nan
        cum_rally_t = float((1 + rally_d["t"]).prod() - 1) if len(rally_d) else np.nan
        # information ratio of the daily excess during rally days (stable, comparable)
        ir = float(excess_rally.mean() / excess_rally.std() * ANNUALIZE) if excess_rally.std() > 0 else np.nan
        rotation[k] = {
            "label_zh": SECTOR_LABELS_ZH[k],
            "ticker": SECTORS[k],
            "rally_mean_daily_excess_bps": float(excess_rally.mean() * 1e4),
            "rally_ann_excess_pct": float(excess_rally.mean() * 252 * 100),   # PRIMARY stable rotation metric
            "rally_excess_info_ratio_ann": ir,
            "rally_excess_vol_ann_pct": float(excess_rally.std() * ANNUALIZE * 100),
            "rally_sector_vol_ann_pct": float(rally_d["s"].std() * ANNUALIZE * 100),
            "rally_cum_sector_ret_pct": cum_rally_s * 100 if not np.isnan(cum_rally_s) else None,
            "rally_cum_twii_ret_pct": cum_rally_t * 100 if not np.isnan(cum_rally_t) else None,
            "rally_cum_excess_pct": (cum_rally_s - cum_rally_t) * 100 if not (np.isnan(cum_rally_s) or np.isnan(cum_rally_t)) else None,
            "cum_excess_caveat": "compounded over NON-CONTIGUOUS rally days; sensitive to single mega-episodes (e.g. 2021 shipping super-cycle). Use rally_ann_excess_pct as the stable metric.",
            "other_ann_excess_pct": float(excess_other.mean() * 252 * 100),
            "n_rally_days": int(len(rally_d)),
            "n_other_days": int(len(other_d)),
        }

    # rank leaders/laggards by the STABLE annualized mean excess (not the episode-sensitive cum)
    ranked = sorted(
        [(k, v["rally_ann_excess_pct"]) for k, v in rotation.items()],
        key=lambda x: x[1], reverse=True
    )

    # ---- per-episode robustness: does a sector LEAD in multiple distinct rally episodes, or just one? ----
    # group contiguous rally days into episodes; require >= 10 days to count as a "real" episode
    rdf = base[["in_rally"]].copy()
    rdf["grp"] = (rdf["in_rally"] != rdf["in_rally"].shift()).cumsum()
    episodes = []
    for g, sub in rdf[rdf["in_rally"]].groupby("grp"):
        if len(sub) >= 10:
            episodes.append((sub.index[0], sub.index[-1], len(sub)))
    episode_meta = [{"start": str(s.date()), "end": str(e.date()), "days": int(n)} for s, e, n in episodes]

    per_episode = {}
    for k, sp in sector_prices.items():
        sret = sp.pct_change()
        wins = 0
        ep_excess = []
        for s, e, n in episodes:
            seg_s = sret.loc[s:e].dropna()
            seg_t = ret.loc[s:e].dropna()
            common = seg_s.index.intersection(seg_t.index)
            if len(common) < 5:
                continue
            cum_s = (1 + seg_s.loc[common]).prod() - 1
            cum_t = (1 + seg_t.loc[common]).prod() - 1
            exc = float((cum_s - cum_t) * 100)
            ep_excess.append(exc)
            if exc > 0:
                wins += 1
        per_episode[k] = {
            "label_zh": SECTOR_LABELS_ZH[k],
            "episodes_outperformed": wins,
            "episodes_total": len(ep_excess),
            "hit_rate": round(wins / len(ep_excess), 2) if ep_excess else None,
            "per_episode_excess_pct": [round(x, 1) for x in ep_excess],
        }

    # ---- assemble results ----
    results = {
        "experiment_id": "k_taiex_60k_scenario_rotation",
        "title": "台股大漲段（126日報酬>=+20%）風險面與產業輪動實證",
        "data_source": "yfinance (auto_adjust=True, dividend-adjusted close)",
        "tickers": {"index": "^TWII", **SECTORS},
        "period": {"start": str(base.index[0].date()), "end": str(base.index[-1].date())},
        "sample_n": {"total_index_days": n_total, "rally_days": n_rally, "other_days": n_other,
                     "rally_pct": round(n_rally / n_total * 100, 2)},
        "definitions": {
            "rally_regime": f"trailing {RALLY_WINDOW}-trading-day TWII return >= +{int(RALLY_THRESHOLD*100)}% (no lookahead: uses past returns only)",
            "realized_vol": f"trailing {VOL_WINDOW}-day std of daily returns, annualized x sqrt(252)",
            "forward_mdd": f"max drawdown over the NEXT {FORWARD_WINDOW} trading days (forward, descriptive only)",
            "tail": f"{int(TAIL_Q*100)}% quantile of daily returns",
        },
        "seed": SEED,
        "bootstrap": {"n_boot": N_BOOT, "block": BLOCK, "seed": SEED},
        "risk": risk_block,
        "sector_rotation": rotation,
        "sector_rotation_rank_by_rally_ann_excess": ranked,
        "rally_episodes": episode_meta,
        "sector_per_episode_robustness": per_episode,
        "data_quality_flags": _DATA_FLAGS,
        "linkage_prior_research": {
            "K178_vt_monthly": "台灣 VT 月頻最佳化：MDD 改善 7.0pp (-22.9%->-15.9%)，但 VT Sharpe 顯著低於 B&H (保險費 ~4%/yr, Harvey t=-3.06)。K=6 最保守(MDD -11.2%, 持倉36%)。",
            "K177_hedge": "台灣最佳避險組合（hedge portfolio）。",
            "K176_covar": "台灣 CoVaR 傳染結構（7 資產）。",
        },
        "generated_at": datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).isoformat(),
    }

    out_json = "rotation_results.json"
    import os
    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, out_json), "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nwrote {out_json}")

    # ================= CHARTS =================
    plt.rcParams["axes.unicode_minus"] = False
    # try a CJK-capable font if present
    for fnt in ["PingFang TC", "Heiti TC", "Arial Unicode MS", "Songti TC", "STHeiti"]:
        try:
            matplotlib.font_manager.findfont(fnt, fallback_to_default=False)
            plt.rcParams["font.family"] = fnt
            break
        except Exception:
            continue

    # Chart 1: risk panel (RV distribution + forward MDD distribution + tail)
    fig, axes = plt.subplots(1, 3, figsize=(16, 5))

    # 1a RV
    axes[0].hist(rv_other.values, bins=40, alpha=0.5, density=True, label=f"Other (n={len(rv_other)})", color="#888")
    axes[0].hist(rv_rally.values, bins=40, alpha=0.6, density=True, label=f"Big-Rally (n={len(rv_rally)})", color="#d62728")
    axes[0].axvline(rv_rally.mean(), color="#d62728", ls="--", lw=1.5)
    axes[0].axvline(rv_other.mean(), color="#444", ls="--", lw=1.5)
    axes[0].set_title("Realized Vol (annualized)\nRally vs Other")
    axes[0].set_xlabel("Annualized RV"); axes[0].legend(fontsize=8)

    # 1b forward 63d MDD
    axes[1].hist(mdd_other.values, bins=40, alpha=0.5, density=True, label=f"Other (n={len(mdd_other)})", color="#888")
    axes[1].hist(mdd_rally.values, bins=40, alpha=0.6, density=True, label=f"Big-Rally (n={len(mdd_rally)})", color="#1f77b4")
    axes[1].axvline(mdd_rally.mean(), color="#1f77b4", ls="--", lw=1.5)
    axes[1].axvline(mdd_other.mean(), color="#444", ls="--", lw=1.5)
    axes[1].set_title("Forward 63d Max Drawdown\n(descriptive, post-rally)")
    axes[1].set_xlabel("MDD (negative = deeper)"); axes[1].legend(fontsize=8)

    # 1c tail bars
    labels = ["Big-Rally", "Other"]
    meds = [tail_rally[1], tail_other[1]]
    los = [tail_rally[1] - tail_rally[0], tail_other[1] - tail_other[0]]
    his = [tail_rally[2] - tail_rally[1], tail_other[2] - tail_other[1]]
    axes[2].bar(labels, meds, yerr=[los, his], capsize=6, color=["#d62728", "#888"], alpha=0.8)
    axes[2].set_title("Daily Return 5% Tail (q05)\nblock-bootstrap median ±95% CI")
    axes[2].set_ylabel("q05 daily return")
    fig.suptitle("TAIEX Big-Rally Risk Profile (2012-2026, yfinance ^TWII)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    fig.savefig(os.path.join(here, "fig_rally_risk_profile.png"), dpi=130)
    plt.close(fig)
    print("wrote fig_rally_risk_profile.png")

    # Chart 2: sector rotation in rally (stable annualized mean excess)
    fig2, ax = plt.subplots(figsize=(11, 6))
    ks = [k for k, _ in ranked]
    excs = [rotation[k]["rally_ann_excess_pct"] for k in ks]
    vols = [rotation[k]["rally_sector_vol_ann_pct"] for k in ks]
    labs = [f"{SECTOR_LABELS_ZH[k]}  (vol {vols[i]:.0f}%)" for i, k in enumerate(ks)]
    colors = ["#2ca02c" if e >= 0 else "#d62728" for e in excs]
    ax.barh(range(len(ks)), excs, color=colors, alpha=0.85)
    ax.set_yticks(range(len(ks)))
    ax.set_yticklabels(labs, fontsize=10)
    ax.invert_yaxis()
    ax.axvline(0, color="#000", lw=0.8)
    ax.set_xlabel("Annualized mean excess return vs ^TWII during big-rally regimes (%)  [stable metric]")
    ax.set_title("Sector Rotation in TAIEX Big-Rally Regimes\n(126d trailing return >= +20%, 2012-2026, data-limit-clipped)")
    for i, e in enumerate(excs):
        ax.text(e + (0.8 if e >= 0 else -0.8), i, f"{e:+.1f}%", va="center",
                ha="left" if e >= 0 else "right", fontsize=9)
    fig2.tight_layout()
    fig2.savefig(os.path.join(here, "fig_sector_rotation.png"), dpi=130)
    plt.close(fig2)
    print("wrote fig_sector_rotation.png")

    # console summary
    print("\n=== RISK SUMMARY ===")
    rb = risk_block
    print(f"  RV ann:   rally mean={rb['realized_vol_annualized']['rally_mean']:.3f} vs other={rb['realized_vol_annualized']['other_mean']:.3f}  (Welch p={rb['realized_vol_annualized']['welch_p']:.2e})")
    print(f"  Fwd MDD:  rally mean={rb['forward_63d_max_drawdown']['rally_mean']:.4f} vs other={rb['forward_63d_max_drawdown']['other_mean']:.4f}  (Welch p={rb['forward_63d_max_drawdown']['welch_p']:.2e})")
    print(f"  Fwd MDD worst: rally={rb['forward_63d_max_drawdown']['rally_worst']:.4f} vs other={rb['forward_63d_max_drawdown']['other_worst']:.4f}")
    print(f"  Tail q05: rally={rb['daily_return_5pct_tail']['rally_empirical_q05']:.4f} vs other={rb['daily_return_5pct_tail']['other_empirical_q05']:.4f}")
    print("\n=== SECTOR ROTATION (rank by STABLE rally ann excess) ===")
    for k, e in ranked:
        v = rotation[k]
        print(f"  {SECTOR_LABELS_ZH[k]:22s} ann_excess={e:+7.1f}%  IR={v['rally_excess_info_ratio_ann']:+.2f}  sector_vol={v['rally_sector_vol_ann_pct']:.1f}%  cum_excess={v['rally_cum_excess_pct']:+.0f}%")
    print("\n=== PER-EPISODE ROBUSTNESS (multi-episode hit rate) ===")
    print(f"  qualifying rally episodes (>=10 days): {len(episode_meta)}")
    for k in [kk for kk, _ in ranked]:
        pe = per_episode[k]
        print(f"  {SECTOR_LABELS_ZH[k]:22s} outperformed {pe['episodes_outperformed']}/{pe['episodes_total']} (hit={pe['hit_rate']})  per-ep={pe['per_episode_excess_pct']}")
    if _DATA_FLAGS:
        print("\n=== DATA QUALITY FLAGS (clipped artifact bars) ===")
        for fl in _DATA_FLAGS:
            print(f"  {fl['ticker']} {fl['date']} raw={fl['raw_return']:+.3f} -> {fl['action']}")

    return results


if __name__ == "__main__":
    main()
