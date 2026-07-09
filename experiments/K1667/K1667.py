"""
K1667 — 「量先價行 / 爆量長黑是出貨」成交量能否預測隔日方向？（技術分析迷思破解）

散戶技術分析常說：
  (A)「量先價行」：爆量（成交量放大）代表主力進場，隔日易漲。
  (B)「爆量長黑是出貨」：高成交量 + 當日長黑 K（大跌/收在低點）= 主力出貨，
      隔日易「續跌」。

本實驗用真實日線資料檢定這兩個 folk claim 是否有統計顯著的「隔日方向」預測力。

--------------------------------------------------------------------------------
Lookahead policy（最高優先風險，一句話）：
  訊號在第 t 日「收盤後」形成（爆量 / 長黑 都只用到第 t 日及之前的價量），
  預測第 t+1 日的報酬。程式用 `signal.shift(1)` 把訊號 lag 一日後，對齊
  `signal[t-1] -> return[t]`：即「檢驗『昨天出現訊號』對『今天報酬』的預測力」。
  所有條件樣本都是 signal.shift(1)==True 的列，其 same-index 報酬即為「訊號隔日報酬」。
--------------------------------------------------------------------------------

方法論防錯：
  * 明確 signal.shift(1) lag（見 build_signals / evaluate_claim）。
  * 隨機程序（block bootstrap）固定 seed=42。
  * 跨資產彙整不把 asset-day 當 iid（K1355 教訓）：primary = per-asset 結果；
    pooled 只做「先按日期聚合 cross-asset 訊號隔日報酬，再對日期序列做 HAC t-test」
    的 diagnostic，明確標註。
  * 「上漲」的誠實 baseline 不是 50%（股票有 upward drift），因此除了 binomial vs 0.5，
    另報「條件 up-rate 減 無條件 up-rate」的兩比例差與 z 檢定（真正的可預測性訊號）。
  * 0050.TW 用 clean_tw50_data 修 2014 split artifact。
  * results.json 走 tmp + json.load 驗證 + os.replace 原子替換。

資料來源：yfinance（免費日線，auto_adjust=True）。期間涵蓋 2018 / 2020 / 2022 空頭。
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

warnings.filterwarnings("ignore")

# repo path for volpred.utils
_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _REPO not in sys.path:
    sys.path.insert(0, os.path.join(_REPO, "src"))

from volpred.utils import clean_tw50_data  # noqa: E402

SEED = 42
rng = np.random.default_rng(SEED)

# ---- Config ---------------------------------------------------------------
ASSETS = {
    "0050.TW": "台灣 50 ETF",
    "2330.TW": "台積電",
    "2317.TW": "鴻海",
    "SPY": "美股 S&P500 ETF",
    "QQQ": "美股 Nasdaq100 ETF",
}
START = "2005-01-01"          # 放寬起始日以確保各資產 >=500 日
END = "2026-07-01"
VOL_WINDOW = 20               # 成交量 rolling 均線窗口
VOL_K = [1.5, 2.0]            # 爆量門檻倍數
BLACK_RET_THR = -0.015        # 長黑：當日報酬 < -1.5%
CLOSE_POS_THR = 0.30          # 長黑（range 版）：(close-low)/(high-low) < 0.3
N_BOOT = 2000                 # block bootstrap reps
BLOCK = 5                     # bootstrap block 長度（吸收短期自相關）


# ---- Data -----------------------------------------------------------------
def load_asset(ticker: str) -> pd.DataFrame:
    """下載日線 OHLCV，回傳含 ret / hi / lo / close / volume / close_pos 的 df。

    * ret = close.pct_change()（第 t 日 close-to-close 報酬，第 t 日收盤即知）
    * 所有欄位皆為第 t 日收盤後可得的資訊。
    """
    raw = yf.download(ticker, start=START, end=END, progress=False, auto_adjust=True)
    if raw is None or len(raw) == 0:
        raise RuntimeError(f"yfinance returned empty for {ticker}")
    # yfinance 多層欄位攤平
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)
    close = raw["Close"].astype(float)
    high = raw["High"].astype(float)
    low = raw["Low"].astype(float)
    volume = raw["Volume"].astype(float)

    # close_pos 是「當日收盤在當日 high-low range 的相對位置」——是 same-day 內的比值，
    # 對每日的價格尺度不變（三者同比例縮放時比值不變），且 raw OHLC 在同一天內互相一致
    # （0050 的 split artifact 是跨時間斷點、非日內尺度問題）。因此 close_pos 用 raw 價計算，
    # 避免「只修 close 未修 high/low」造成 pre-2014 0050 的 close<low 失真（reviewer 2026-07-09 抓到）。
    rng_hl = (high - low).replace(0.0, np.nan)
    close_pos = (close - low) / rng_hl

    if ticker == "0050.TW":
        # ret 用 cleaned close（修 2014 split 斷點的假 -75%）；close_pos 已用 raw 算好，不受影響。
        close, _ = clean_tw50_data(close)

    df = pd.DataFrame(
        {"close": close, "volume": volume, "close_pos": close_pos}
    ).dropna(subset=["close", "volume"])
    df["ret"] = df["close"].pct_change()
    df = df.dropna(subset=["ret"])
    return df


# ---- Signals（第 t 日收盤後形成）-------------------------------------------
def build_signals(df: pd.DataFrame, k: float) -> pd.DataFrame:
    """在第 t 日收盤後可得的訊號（尚未 lag）。

    high_volume : volume_t > k * rolling_mean(volume, 20)（rolling 窗口結束於 t，
                  故只用到 t 及之前的成交量，t 日收盤已知）。
    long_black  : ret_t < -1.5%（報酬版），或 close_pos_t < 0.3（range 版）。
    量先價行     : high_volume（不分紅黑）。
    爆量長紅     : high_volume AND ret_t > 0。
    爆量長黑     : high_volume AND long_black（報酬版為主，range 版 robustness）。
    """
    out = pd.DataFrame(index=df.index)
    vol_ma = df["volume"].rolling(VOL_WINDOW).mean()
    high_vol = df["volume"] > (k * vol_ma)

    black_ret = df["ret"] < BLACK_RET_THR
    black_pos = df["close_pos"] < CLOSE_POS_THR

    out["high_volume"] = high_vol
    out["volume_leads"] = high_vol                      # (A) 量先價行
    out["high_vol_up"] = high_vol & (df["ret"] > 0)     # 爆量長紅
    out["high_vol_black"] = high_vol & black_ret        # (B) 爆量長黑（報酬版）
    out["high_vol_black_pos"] = high_vol & black_pos    # 爆量長黑（range 版 robustness）
    # rolling 窗口不足處為 NaN -> False
    return out.fillna(False).astype(bool)


# ---- Statistics helpers ---------------------------------------------------
def block_bootstrap_mean_diff_ci(cond: np.ndarray, uncond: np.ndarray) -> list:
    """block bootstrap 95% CI of (mean(cond) - mean(uncond))；seed 固定。

    對 cond 與 uncond 各自做 moving-block bootstrap（block=5），吸收短期自相關，
    避免低估標準誤。回傳 [lo, hi]。
    """
    def one_block_sample(x: np.ndarray, n: int) -> np.ndarray:
        if len(x) < BLOCK:
            return rng.choice(x, size=n, replace=True)
        n_blocks = int(np.ceil(n / BLOCK))
        starts = rng.integers(0, len(x) - BLOCK + 1, size=n_blocks)
        idx = (starts[:, None] + np.arange(BLOCK)[None, :]).ravel()[:n]
        return x[idx]

    diffs = np.empty(N_BOOT)
    nc, nu = len(cond), len(uncond)
    for b in range(N_BOOT):
        bc = one_block_sample(cond, nc)
        bu = one_block_sample(uncond, nu)
        diffs[b] = bc.mean() - bu.mean()
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    return [float(lo), float(hi)]


def two_prop_z(x1: int, n1: int, x2: int, n2: int) -> tuple:
    """兩比例差 z 檢定（pooled proportion）。回傳 (p1-p2, z, two-sided p)。"""
    if n1 == 0 or n2 == 0:
        return (float("nan"), float("nan"), float("nan"))
    p1, p2 = x1 / n1, x2 / n2
    p = (x1 + x2) / (n1 + n2)
    se = np.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return (p1 - p2, float("nan"), float("nan"))
    z = (p1 - p2) / se
    pval = 2 * (1 - stats.norm.cdf(abs(z)))
    return (float(p1 - p2), float(z), float(pval))


def evaluate_claim(df: pd.DataFrame, signal: pd.Series, direction: str) -> dict:
    """核心評估。

    signal   : 第 t 日收盤後形成的 bool（尚未 lag）。
    direction: "up"   -> folk claim 是「隔日易漲」（量先價行 / 爆量長紅）
               "down" -> folk claim 是「隔日續跌」（爆量長黑是出貨）

    Lookahead-safe 對齊：
        sig_lag = signal.shift(1)         # 昨天(t-1)的訊號
        cond_ret = df.ret[sig_lag]        # 今天(t)的報酬 = 訊號的「隔日報酬」
    無條件 baseline = 全樣本（valid ret）的隔日報酬 = 同段期間所有 df.ret。
    """
    # <<< signal.shift(1) lookahead guard; astype(bool) 因 shift 引入 NaN 使 dtype 變 object
    sig_lag = signal.shift(1).fillna(False).astype(bool)
    ret = df["ret"]

    cond = ret[sig_lag].dropna().to_numpy()        # 訊號隔日報酬
    all_ret = ret.dropna().to_numpy()              # 無條件隔日報酬（全樣本 drift baseline）
    noncond = ret[~sig_lag].dropna().to_numpy()    # 非訊號日隔日報酬（Welch/MWU 對照組）

    n_cond = int(len(cond))
    if n_cond < 10:
        return {"n_signal": n_cond, "insufficient": True}

    # --- 條件 vs 無條件/非條件 報酬分佈 ---
    t_stat, t_p = stats.ttest_ind(cond, noncond, equal_var=False)   # Welch
    u_stat, u_p = stats.mannwhitneyu(cond, noncond, alternative="two-sided")
    boot_ci = block_bootstrap_mean_diff_ci(cond, all_ret)

    # --- 方向命中率 ---
    up_cond = int((cond > 0).sum())
    up_all = int((all_ret > 0).sum())
    if direction == "up":
        hits, base_hits = up_cond, up_all
        hit_label = "隔日上漲率"
    else:  # down
        hits = int((cond < 0).sum())
        base_hits = int((all_ret < 0).sum())
        hit_label = "隔日下跌率"

    hit_rate = hits / n_cond
    base_rate = base_hits / len(all_ret)
    # (1) binomial vs 0.5（folk claim 的字面主張：比丟銅板好）
    binom_p_vs_half = float(stats.binomtest(hits, n_cond, 0.5).pvalue)
    # (2) 兩比例差 vs 無條件 base rate（誠實的可預測性訊號：扣掉 drift 後還有沒有）
    dprop, zprop, pprop = two_prop_z(
        hits, n_cond, base_hits, len(all_ret)
    )

    return {
        "n_signal": n_cond,
        "insufficient": False,
        "direction_tested": direction,
        "hit_label": hit_label,
        "cond_mean_ret": float(cond.mean()),
        "uncond_mean_ret": float(all_ret.mean()),
        "mean_diff": float(cond.mean() - all_ret.mean()),
        "mean_diff_boot95ci": boot_ci,
        "welch_t": float(t_stat),
        "welch_p": float(t_p),
        "mannwhitney_u": float(u_stat),
        "mannwhitney_p": float(u_p),
        "hit_rate": float(hit_rate),
        "uncond_base_rate": float(base_rate),
        "hit_rate_minus_base": float(hit_rate - base_rate),
        "binom_p_vs_0.5": binom_p_vs_half,
        "twoprop_diff_vs_base": dprop,
        "twoprop_z": zprop,
        "twoprop_p": pprop,
    }


# ---- Pooled cross-asset diagnostic（K1355-safe）----------------------------
def pooled_date_level(per_asset_cond: dict) -> dict:
    """把各資產「訊號隔日報酬」按日期聚合，再對日期序列做 HAC(Newey-West) t-test。

    per_asset_cond[ticker] = pd.Series（index=date，value=訊號隔日報酬）
    對每個日期取跨資產平均（僅計當日有訊號的資產），得到 date-level series，
    再對其做 vs 0 的 HAC t-test（不把 asset-day 當 iid — K1355）。
    這是 diagnostic，不是 primary claim。
    """
    if not per_asset_cond:
        return {"available": False}
    mat = pd.DataFrame(per_asset_cond)          # index=date, cols=ticker
    daily = mat.mean(axis=1, skipna=True).dropna()   # 每日跨資產平均訊號隔日報酬
    x = daily.to_numpy()
    n = len(x)
    if n < 30:
        return {"available": False, "n_dates": int(n)}
    mean = x.mean()
    # Newey-West HAC 標準誤 vs 0（lag = floor(4*(n/100)^(2/9)) Newey-West rule）
    demean = x - mean
    L = int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0)))
    gamma0 = (demean @ demean) / n
    var = gamma0
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)
        cov = (demean[lag:] @ demean[:-lag]) / n
        var += 2.0 * w * cov
    hac_se = np.sqrt(var / n)
    t_hac = mean / hac_se if hac_se > 0 else float("nan")
    p_hac = 2 * (1 - stats.norm.cdf(abs(t_hac)))
    return {
        "available": True,
        "n_dates": int(n),
        "mean_daily_cond_ret": float(mean),
        "hac_lag": int(L),
        "hac_se": float(hac_se),
        "hac_t": float(t_hac),
        "hac_p": float(p_hac),
        "note": "date-level cross-asset average, HAC(Newey-West) vs 0; diagnostic only (K1355)",
    }


# ---- Main -----------------------------------------------------------------
def main():
    results = {
        "experiment_id": "K1667",
        "title": "成交量能否預測隔日方向？量先價行 / 爆量長黑是出貨 迷思破解",
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "data_source": "yfinance daily OHLCV (auto_adjust=True)",
        "period": {"start": START, "end": END},
        "signal_defs": {
            "high_volume": f"volume_t > k * rolling_mean(volume,{VOL_WINDOW}); k in {VOL_K}",
            "long_black_ret": f"ret_t < {BLACK_RET_THR}",
            "long_black_range": f"(close-low)/(high-low) < {CLOSE_POS_THR}",
            "lookahead_policy": "signal.shift(1): signal[t-1] -> return[t]; 訊號 t 日收盤形成，預測 t+1",
        },
        "claims": {
            "A_volume_leads_price": "爆量 -> 隔日易漲 (direction=up)",
            "B_high_vol_black_distribution": "爆量長黑 -> 隔日續跌 (direction=down)",
        },
        "assets": {},
        "pooled_diagnostic": {},
    }

    # 收集 pooled 用的 per-asset 訊號隔日報酬（以 k=2.0 主 spec）
    pool_volume_leads = {}
    pool_high_vol_black = {}

    for ticker, name in ASSETS.items():
        print(f"[K1667] loading {ticker} ({name}) ...", flush=True)
        try:
            df = load_asset(ticker)
        except Exception as e:
            print(f"  ERROR loading {ticker}: {e}", flush=True)
            results["assets"][ticker] = {"error": str(e)}
            continue

        n_days = int(len(df))
        asset_out = {
            "name": name,
            "n_days": n_days,
            "date_range": [str(df.index[0].date()), str(df.index[-1].date())],
            "by_k": {},
        }
        if n_days < 500:
            asset_out["warn"] = f"n_days<500 ({n_days})"

        for k in VOL_K:
            sig = build_signals(df, k)
            eval_volume_leads = evaluate_claim(df, sig["volume_leads"], "up")
            eval_high_vol_up = evaluate_claim(df, sig["high_vol_up"], "up")
            eval_high_vol_black = evaluate_claim(df, sig["high_vol_black"], "down")
            eval_high_vol_black_pos = evaluate_claim(df, sig["high_vol_black_pos"], "down")
            asset_out["by_k"][str(k)] = {
                "n_high_volume_days": int(sig["high_volume"].sum()),
                "A_volume_leads_price": eval_volume_leads,
                "A2_high_vol_up_bar": eval_high_vol_up,
                "B_high_vol_black_ret": eval_high_vol_black,
                "B2_high_vol_black_rangepos": eval_high_vol_black_pos,
            }

            if k == 2.0:
                # pooled 用 signal.shift(1) 對齊的訊號隔日報酬 series
                vl = sig["volume_leads"].shift(1).fillna(False).astype(bool)
                bl = sig["high_vol_black"].shift(1).fillna(False).astype(bool)
                pool_volume_leads[ticker] = df["ret"][vl].dropna()
                pool_high_vol_black[ticker] = df["ret"][bl].dropna()

        results["assets"][ticker] = asset_out

    results["pooled_diagnostic"]["A_volume_leads_price_k2.0"] = pooled_date_level(
        pool_volume_leads
    )
    results["pooled_diagnostic"]["B_high_vol_black_k2.0"] = pooled_date_level(
        pool_high_vol_black
    )

    # --- verdict 摘要（依 k=2.0 主 spec, per-asset）---
    results["verdict"] = summarize_verdict(results)

    # --- atomic write ---
    out_path = os.path.join(_HERE, "K1667_results.json")
    tmp_path = out_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    with open(tmp_path, "r", encoding="utf-8") as f:
        json.load(f)  # validate parseable
    os.replace(tmp_path, out_path)
    print(f"[K1667] results written -> {out_path}", flush=True)

    make_figures(results)
    return results


def summarize_verdict(results: dict) -> dict:
    """依 k=2.0 主 spec 彙整各 claim 的 per-asset 顯著性（誠實口徑）。

    'significant' 定義：條件隔日報酬均值差的 bootstrap 95% CI 不含 0
    （即 mean_diff 顯著），且方向與 folk claim 一致。
    我們同時記錄「幾個資產顯著」與方向。
    """
    def scan(key: str, want_sign: int) -> dict:
        rows = []
        n_sig = 0          # 顯著 且 方向與 folk claim 一致
        n_opp_sig = 0      # 顯著 但 方向相反（例：claim=續跌 但實際顯著反彈）
        for ticker, a in results["assets"].items():
            if "by_k" not in a:
                continue
            e = a["by_k"].get("2.0", {}).get(key, {})
            if e.get("insufficient", True):
                continue
            lo, hi = e["mean_diff_boot95ci"]
            ci_excl_zero = (lo > 0) or (hi < 0)
            md = e["mean_diff"]
            sign_ok = (md > 0 and want_sign > 0) or (md < 0 and want_sign < 0)
            is_sig = ci_excl_zero and sign_ok
            is_opp_sig = ci_excl_zero and not sign_ok
            if is_sig:
                n_sig += 1
            if is_opp_sig:
                n_opp_sig += 1
            rows.append(
                {
                    "asset": ticker,
                    "n_signal": e["n_signal"],
                    "hit_rate": round(e["hit_rate"], 4),
                    "uncond_base_rate": round(e["uncond_base_rate"], 4),
                    "hit_rate_minus_base": round(e["hit_rate_minus_base"], 4),
                    "mean_diff": md,
                    "boot95ci": e["mean_diff_boot95ci"],
                    "twoprop_p": e["twoprop_p"],
                    "significant_in_claim_direction": is_sig,
                    "significant_opposite_direction": is_opp_sig,
                }
            )
        return {
            "n_assets_significant": n_sig,
            "n_assets_significant_opposite": n_opp_sig,
            "n_assets_tested": len(rows),
            "rows": rows,
        }

    return {
        "spec": "k=2.0, per-asset primary",
        "A_volume_leads_price(up)": scan("A_volume_leads_price", +1),
        "B_high_vol_black(down-continuation)": scan("B_high_vol_black_ret", -1),
    }


def make_figures(results: dict):
    """圖 1：各資產 兩 claim 的『命中率 vs 無條件 baseline』bar。
    圖 2：爆量長黑 條件 vs 無條件 隔日報酬均值（含 bootstrap CI）。"""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # CJK 字型（避免中文標題顯示成豆腐方塊）；挑第一個可用的
    for _f in ["Arial Unicode MS", "PingFang HK", "Heiti TC", "STHeiti", "Songti SC"]:
        try:
            import matplotlib.font_manager as _fm

            _fm.findfont(_f, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [_f]
            break
        except Exception:
            continue  # silent-ok: font probing, 下一個候選；找不到就用預設
    plt.rcParams["axes.unicode_minus"] = False

    tickers = [t for t in ASSETS if "by_k" in results["assets"].get(t, {})]

    # ---- Fig 1: hit rate vs base rate ----
    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    for ax, (key, title, dircol) in zip(
        axes,
        [
            ("A_volume_leads_price", "量先價行：爆量隔日『上漲率』", "#2a7fbf"),
            ("B_high_vol_black_ret", "爆量長黑：隔日『下跌率』", "#c0392b"),
        ],
    ):
        hs, bs, labs = [], [], []
        for t in tickers:
            e = results["assets"][t]["by_k"]["2.0"][key]
            if e.get("insufficient", True):
                continue
            hs.append(e["hit_rate"] * 100)
            bs.append(e["uncond_base_rate"] * 100)
            labs.append(t)
        x = np.arange(len(labs))
        ax.bar(x - 0.2, hs, 0.4, label="訊號後 條件命中率", color=dircol)
        ax.bar(x + 0.2, bs, 0.4, label="無條件 baseline", color="#bbbbbb")
        ax.axhline(50, ls="--", c="k", lw=0.8, label="50% (丟銅板)")
        ax.set_xticks(x)
        ax.set_xticklabels(labs, rotation=20)
        ax.set_ylabel("機率 (%)")
        ax.set_title(title, fontsize=11)
        # 依實際數據自動下界（避免 2330/QQQ 的低下跌率 bar 被 y 軸切掉）
        ymin = min(30, np.floor((min(hs + bs) - 3) / 5) * 5) if (hs + bs) else 30
        ax.set_ylim(ymin, 65)
        ax.legend(fontsize=8)
    fig.suptitle(
        "K1667 成交量隔日方向預測（k=2.0）：條件命中率幾乎貼齊無條件 baseline",
        fontsize=12,
    )
    fig.tight_layout()
    p1 = os.path.join(_HERE, "K1667_hitrate.png")
    fig.savefig(p1, dpi=130)
    plt.close(fig)

    # ---- Fig 2: mean next-day return, cond vs uncond, with boot CI ----
    fig, ax = plt.subplots(figsize=(9, 5))
    labs, cm, um, los, his = [], [], [], [], []
    for t in tickers:
        e = results["assets"][t]["by_k"]["2.0"]["B_high_vol_black_ret"]
        if e.get("insufficient", True):
            continue
        labs.append(t)
        cm.append(e["cond_mean_ret"] * 100)
        um.append(e["uncond_mean_ret"] * 100)
        lo, hi = e["mean_diff_boot95ci"]
        # CI 畫在 cond bar 上（相對 uncond 的差）
        los.append((e["mean_diff"] - lo) * 100)
        his.append((hi - e["mean_diff"]) * 100)
    x = np.arange(len(labs))
    ax.bar(x - 0.2, cm, 0.4, label="爆量長黑後 隔日均報酬", color="#c0392b")
    ax.bar(x + 0.2, um, 0.4, label="無條件 隔日均報酬", color="#bbbbbb")
    ax.axhline(0, c="k", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(labs, rotation=20)
    ax.set_ylabel("隔日報酬均值 (%)")
    ax.set_title(
        "K1667 爆量長黑：隔日報酬並未系統性續跌（多數資產反而 ≥ 無條件均值）",
        fontsize=11,
    )
    ax.legend(fontsize=9)
    fig.tight_layout()
    p2 = os.path.join(_HERE, "K1667_black_meanret.png")
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    print(f"[K1667] figures -> {p1} , {p2}", flush=True)


if __name__ == "__main__":
    main()
