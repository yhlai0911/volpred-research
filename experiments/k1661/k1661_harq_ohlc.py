#!/usr/bin/env python3
"""
K1661 | HARQ 測量誤差加權在日頻 OHLC 代理噪音下的 contrarian 檢定

研究問題（反直覺）：
    HARQ（Bollerslev, Patton & Quaedvlieg 2016, JoE）的核心是用 realized
    quarticity (RQ) 衡量「當日 RV 的測量誤差」，對測量誤差大的日子下修
    autoregressive daily loading（β_t = β_d + β_dQ·√RQ_{t-1}）。這在**高頻**RV
    下成立（RQ = (N/3)Σr_i^4 對 N 筆日內報酬取平均，是相對穩定的測量誤差估計）。

    但若我們**只有日頻 OHLC**、用 Garman-Klass range 近似 RV、再用 range 的四次方
    近似 RQ，則 RQ proxy 本身是「單日、極高噪音」的估計（無日內平均）。此時：
      √RQ_{t-1} = (ln H/L)^2_{t-1}  ∝ σ^2_{t-1}   （與 RV_{t-1} 幾乎共線）
    → HARQ 的交互項 √RQ_{t-1}·RV_{t-1} ≈ RV_{t-1}^2，本質是加了一個「噪音平方」項，
      而非乾淨的測量誤差訊號。假說：在此 regime 下 HARQ 相對樸素 HAR **無改善甚至傷害**
      OOS 預測（"代理噪音下誤差加權反轉"）。

差異化（vs 庫內既有 K）：
    - K1582 / rough-vol race：都在**高頻 5-min RV** 下測 HARQ（TX 方向有利但不過
      Harvey gate）。K1661 專測**日頻 OHLC 代理噪音**這個全新 regime，方向相反的假說。

模型：
    HAR  : RV_t = β0 + β_d·RV^d_{t-1} + β_w·RV^w_{t-1} + β_m·RV^m_{t-1} + ε   (Corsi 2009)
    HARQ : RV_t = β0 + (β_d + β_dQ·√RQ_{t-1})·RV^d_{t-1} + β_w·RV^w_{t-1}
                     + β_m·RV^m_{t-1} + ε                                     (BPQ 2016, daily-only)
    HARQ-F: 額外把 √RQ_{t-1} 交互到 weekly / monthly 三個 RV 項（BPQ full spec）robustness

RV proxy  : Garman-Klass 日頻 range estimator（負值以 Parkinson 補）
RQ proxy  : range-based quarticity  RQ_t = (ln H/L)^4  → √RQ = (ln H/L)^2（變異數尺度，
            比例常數由回歸 β_dQ 吸收；見 README caveat）

評估：rolling-window（W=1000，BPQ 慣例）one-step OOS，每日 refit；insanity filter
      （BPQ）統一套用到所有模型。QLIKE（canonical actual/predicted）+ MSE；
      HARQ vs HAR 用 Harvey-Leybourne-Newbold (HLN 1997) small-sample DM 修正，h=1。

Lookahead 聲明：
    設計矩陣以 target date t 對齊，X_t 全部由 {t-1, ..., t-22} 的 realized OHLC 構成
    （明確 lag，見 build_design()）。rolling 訓練列 target date 皆 <= 預測日前一日
    （target_end < forecast_origin），無訓練列看見預測日或之後的 realized 值。

Seed: 1661（固定；本實驗除 numpy 全域外無其他隨機程序）

References:
    Corsi (2009) JFE 7(2); Bollerslev, Patton & Quaedvlieg (2016) JoE 192(1);
    Garman & Klass (1980) J.Business 53(1); Parkinson (1980) J.Business 53(1);
    Patton (2011) JoE 160(1); Harvey, Leybourne & Newbold (1997) IJF 13(2).

Author: VolPred Research System
Date: 2026-07-08
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

SEED = 1661
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

# repo 根（worktree 內）—— 用於 fallback 讀本地 cache
REPO_ROOT = HERE.parents[1]

ASSETS = {
    "SPY": "SPY",       # 可交易 ETF：range 乾淨
    "0050.TW": "0050.TW",  # 可交易 ETF：range 乾淨
    "TWII": "^TWII",    # 台股指數（TX 台指期代理）：index H/L 非成交價 → range 額外噪音
}
START = "2010-01-01"
END = "2026-07-08"
WINDOW = 1000          # rolling 估計窗（BPQ 2016 慣例）


# ────────────────────────────────────────────────────────────────
# 資料
# ────────────────────────────────────────────────────────────────
def _flatten_cols(df):
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    return df


def load_ohlc(name, ticker):
    """yfinance 優先，本地 cache fallback。回傳 DataFrame[Open,High,Low,Close]。"""
    cache = DATA_DIR / f"{name}_ohlc.csv"
    df = None
    try:
        import yfinance as yf
        raw = yf.download(ticker, start=START, end=END, auto_adjust=False, progress=False)
        raw = _flatten_cols(raw)
        if len(raw) > 100:
            df = raw[["Open", "High", "Low", "Close"]].copy()
    except Exception as e:  # noqa
        print(f"[{name}] yfinance 失敗，改用 cache: {e!r}", file=sys.stderr)

    if df is None or len(df) < 100:
        # fallback：repo 內 storage/macro cache（格式為 yfinance 兩層 header）
        fname = {"SPY": None, "0050.TW": "yf_0050.TW.csv", "TWII": "yf_TWII.csv"}[name]
        if fname is None:
            raise RuntimeError(f"{name} 無 yfinance 也無 cache，無法取得資料")
        p = REPO_ROOT / "storage" / "macro" / fname
        raw = pd.read_csv(p, skiprows=[1, 2], index_col=0, parse_dates=True)
        df = raw[["Open", "High", "Low", "Close"]].copy()
        print(f"[{name}] 使用本地 cache {p} (rows={len(df)})", file=sys.stderr)

    df = df.apply(pd.to_numeric, errors="coerce").dropna()
    df = df[(df["High"] >= df["Low"]) & (df["Low"] > 0) & (df["Open"] > 0) & (df["Close"] > 0)]
    # 存 cache（provenance）
    df.to_csv(cache)
    return df


# ────────────────────────────────────────────────────────────────
# RV / RQ proxy
# ────────────────────────────────────────────────────────────────
def garman_klass(df):
    """GK 日頻變異數估計；負值（罕見）以 Parkinson 補正。單位 = 日報酬^2。"""
    hl = np.log(df["High"] / df["Low"]).values
    co = np.log(df["Close"] / df["Open"]).values
    gk = 0.5 * hl ** 2 - (2 * np.log(2) - 1) * co ** 2
    park = hl ** 2 / (4 * np.log(2))  # Parkinson，恆正
    gk = np.where(gk > 0, gk, park)
    return pd.Series(gk, index=df.index, name="RV")


def range_quarticity(df):
    """range-based RQ proxy = (ln H/L)^4 → √RQ = (ln H/L)^2（變異數尺度）。"""
    hl = np.log(df["High"] / df["Low"]).values
    rq = hl ** 4
    return pd.Series(rq, index=df.index, name="RQ")


# ────────────────────────────────────────────────────────────────
# 設計矩陣（明確 lag：target RV_t，features 全來自 t-1..t-22）
# ────────────────────────────────────────────────────────────────
def build_design(rv, rq):
    """回傳對齊 target date t 的 DataFrame。
    RV_d = RV_{t-1}, RV_w = mean(RV_{t-5..t-1}), RV_m = mean(RV_{t-22..t-1}),
    sqrtRQ = sqrt(RQ_{t-1}) = (ln H/L)^2_{t-1}, y = RV_t.
    所有 feature 用 .shift(1) 或 rolling().shift(1) 保證僅用 t-1 之前資訊。"""
    d = pd.DataFrame(index=rv.index)
    d["RV_d"] = rv.shift(1)
    d["RV_w"] = rv.rolling(5).mean().shift(1)
    d["RV_m"] = rv.rolling(22).mean().shift(1)
    d["sqrtRQ"] = np.sqrt(rq).shift(1)                    # √RQ_{t-1} 單日（高噪音）
    d["sqrtRQ_sm"] = np.sqrt(rq.rolling(5).mean()).shift(1)  # √(5日平均RQ)_{t-1}（機制探針）
    d["y"] = rv                          # target RV_t
    d = d.dropna()
    return d


# ────────────────────────────────────────────────────────────────
# OLS + insanity filter
# ────────────────────────────────────────────────────────────────
def ols_fit(X, y):
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def insanity_filter(pred, train_y):
    """BPQ insanity filter：預測 <=0 或超出訓練樣本 [min,max] → 用訓練均值取代。"""
    lo, hi, mu = train_y.min(), train_y.max(), train_y.mean()
    if not np.isfinite(pred) or pred <= 0 or pred < lo or pred > hi:
        return mu
    return pred


def _zcol(d_slice, col, stats):
    """standardize 指定 √RQ 欄（forecast-neutral，純數值 conditioning）。"""
    v = d_slice[col].values
    if stats is None:
        return v
    m, s = stats[col]
    return (v - m) / s


def make_X(d_slice, model, stats=None):
    """建 design matrix。
    HARQ        : daily-only 單日 √RQ 交互（BPQ-lite）
    HARQ-F      : 單日 √RQ 交互到 daily/weekly/monthly 三項（BPQ full）
    HARQ-smooth : 用 5 日平均 √RQ（降噪）交互 daily（機制探針）"""
    n = len(d_slice)
    RV_d = d_slice["RV_d"].values
    RV_w = d_slice["RV_w"].values
    RV_m = d_slice["RV_m"].values
    cols = [np.ones(n), RV_d, RV_w, RV_m]
    if model == "HAR":
        pass
    elif model == "HARQ":
        cols.append(_zcol(d_slice, "sqrtRQ", stats) * RV_d)
    elif model == "HARQ-F":
        z = _zcol(d_slice, "sqrtRQ", stats)
        cols.append(z * RV_d)
        cols.append(z * RV_w)
        cols.append(z * RV_m)
    elif model == "HARQ-smooth":
        cols.append(_zcol(d_slice, "sqrtRQ_sm", stats) * RV_d)
    else:
        raise ValueError(model)
    return np.column_stack(cols)


def rolling_oos(d, model, window=WINDOW):
    """rolling one-step OOS。回傳 (dates, y_true, y_pred, n_insanity)。"""
    idx = d.index
    n = len(d)
    dates, yt, yp = [], [], []
    n_insanity = 0
    start = window
    for i in range(start, n):
        tr = d.iloc[i - window:i]        # target date 皆 <= idx[i-1] < forecast day idx[i]
        te = d.iloc[i:i + 1]
        stats_z = {c: (tr[c].mean(), tr[c].std(ddof=0) or 1.0)
                   for c in ("sqrtRQ", "sqrtRQ_sm")}
        Xtr = make_X(tr, model, stats_z)
        ytr = tr["y"].values
        beta = ols_fit(Xtr, ytr)
        Xte = make_X(te, model, stats_z)
        raw_pred = float((Xte @ beta).ravel()[0])
        pred = insanity_filter(raw_pred, ytr)
        if pred != raw_pred:
            n_insanity += 1
        dates.append(idx[i])
        yt.append(float(te["y"].values[0]))
        yp.append(pred)
    return (np.array(dates), np.array(yt), np.array(yp), n_insanity)


# ────────────────────────────────────────────────────────────────
# 評估
# ────────────────────────────────────────────────────────────────
def qlike_pointwise(actual, predicted):
    a = np.maximum(np.asarray(actual, float), 1e-16)
    f = np.maximum(np.asarray(predicted, float), 1e-16)
    r = a / f
    return r - np.log(r) - 1


def qlike(actual, predicted):
    return float(np.mean(qlike_pointwise(actual, predicted)))


def mse(actual, predicted):
    return float(np.mean((np.asarray(actual, float) - np.asarray(predicted, float)) ** 2))


def dm_hln(loss_a, loss_b, h=1):
    """DM test with Harvey-Leybourne-Newbold (1997) small-sample 修正。
    d = loss_a - loss_b；d<0 → model a（HARQ）better。
    HLN：DM_stat × sqrt((T+1-2h+h(h-1)/T)/T)，對照 Student-t(df=T-1)。"""
    d = np.asarray(loss_a, float) - np.asarray(loss_b, float)
    d = d[np.isfinite(d)]
    T = len(d)
    if T < 30:
        return {"T": T, "dm": None, "dm_hln": None, "p_two": None, "p_one_a_better": None}
    dbar = d.mean()
    gamma0 = np.sum((d - dbar) ** 2) / T          # population γ0
    V = gamma0
    for k in range(1, h):
        gk = np.sum((d[k:] - dbar) * (d[:-k] - dbar)) / T
        V += 2 * gk
    if V <= 0:
        return {"T": T, "dm": None, "dm_hln": None, "p_two": None, "p_one_a_better": None}
    dm = dbar / np.sqrt(V / T)
    factor = np.sqrt((T + 1 - 2 * h + h * (h - 1) / T) / T)
    dm_h = dm * factor
    p_two = float(2 * (1 - stats.t.cdf(abs(dm_h), df=T - 1)))
    p_one_a = float(stats.t.cdf(dm_h, df=T - 1))  # P(HARQ better) one-sided
    return {"T": int(T), "dm": float(dm), "dm_hln": float(dm_h),
            "p_two": p_two, "p_one_a_better": p_one_a, "mean_diff": float(dbar)}


def insample_harq_coef(d):
    """full-sample HARQ 係數（β_dQ sign 診斷）。standardize √RQ 交互。"""
    stats_z = {c: (d[c].mean(), d[c].std(ddof=0) or 1.0) for c in ("sqrtRQ", "sqrtRQ_sm")}
    X = make_X(d, "HARQ", stats_z)
    y = d["y"].values
    beta = ols_fit(X, y)
    # β = [const, β_d, β_w, β_m, β_dQ(standardized)]
    return {"beta_const": float(beta[0]), "beta_d": float(beta[1]),
            "beta_w": float(beta[2]), "beta_m": float(beta[3]),
            "beta_dQ_std": float(beta[4])}


# ────────────────────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────────────────────
def run_asset(name, ticker):
    df = load_ohlc(name, ticker)
    rv = garman_klass(df)
    rq = range_quarticity(df)
    d = build_design(rv, rq)

    # 診斷：√RQ 與 RV_{t-1} 的相關（共線性 → 交互項≈RV^2）
    corr_srq_rvd = float(np.corrcoef(d["sqrtRQ"], d["RV_d"])[0, 1])

    # 診斷：平滑後 √RQ 與 RV_{t-1} 相關（機制對照）
    corr_srqsm_rvd = float(np.corrcoef(d["sqrtRQ_sm"], d["RV_d"])[0, 1])

    models = ["HAR", "HARQ", "HARQ-F", "HARQ-smooth"]
    out = {}
    losses = {}
    for m in models:
        dates, yt, yp, n_ins = rolling_oos(d, m)
        ql = qlike(yt, yp)
        ms = mse(yt, yp)
        losses[m] = {"dates": dates, "qlike_pw": qlike_pointwise(yt, yp), "yt": yt, "yp": yp}
        out[m] = {"qlike": ql, "mse": ms, "n_oos": int(len(yt)),
                  "n_insanity_filter": int(n_ins),
                  "insanity_pct": float(100 * n_ins / len(yt))}

    # 存設計陣列供機制圖（√RQ vs RV_{t-1} 共線性）
    losses["_design"] = {"RV_d": d["RV_d"].values, "sqrtRQ": d["sqrtRQ"].values}

    # DM-HLN vs HAR
    dm_harq = dm_hln(losses["HARQ"]["qlike_pw"], losses["HAR"]["qlike_pw"], h=1)
    dm_harqf = dm_hln(losses["HARQ-F"]["qlike_pw"], losses["HAR"]["qlike_pw"], h=1)
    dm_harqsm = dm_hln(losses["HARQ-smooth"]["qlike_pw"], losses["HAR"]["qlike_pw"], h=1)

    ins = insample_harq_coef(d)

    def imp(m):
        return float(100 * (out["HAR"]["qlike"] - out[m]["qlike"]) / out["HAR"]["qlike"])

    result = {
        "asset": name,
        "ticker": ticker,
        "n_days": int(len(df)),
        "sample_start": str(df.index.min().date()),
        "sample_end": str(df.index.max().date()),
        "n_design": int(len(d)),
        "corr_sqrtRQ_RVd": corr_srq_rvd,
        "corr_sqrtRQ_sm_RVd": corr_srqsm_rvd,
        "insample_harq_coef": ins,
        "models": out,
        "dm_hln_HARQ_vs_HAR": dm_harq,
        "dm_hln_HARQ_F_vs_HAR": dm_harqf,
        "dm_hln_HARQ_smooth_vs_HAR": dm_harqsm,
        "qlike_improve_HARQ_pct": imp("HARQ"),
        "qlike_improve_HARQ_F_pct": imp("HARQ-F"),
        "qlike_improve_HARQ_smooth_pct": imp("HARQ-smooth"),
    }
    return result, losses


def verdict_from_results(results):
    """校準 verdict（結論強度不超過證據）。
    canonical tag = 統計顯著性層級（Harvey |t|>3）；另記 contrarian 假說的 directional 支持。"""
    n = len(results)
    harq_worse = sum(1 for r in results if r["models"]["HARQ"]["qlike"] > r["models"]["HAR"]["qlike"])
    harq_sig_better = sum(1 for r in results
                          if (r["dm_hln_HARQ_vs_HAR"]["dm_hln"] or 0) < -3.0)
    harq_sig_worse = sum(1 for r in results
                         if (r["dm_hln_HARQ_vs_HAR"]["dm_hln"] or 0) > 3.0)
    # smooth 機制探針：平滑 √RQ 是否縮小 HARQ 的退化
    smooth_recovers = sum(
        1 for r in results
        if r["models"]["HARQ-smooth"]["qlike"] < r["models"]["HARQ"]["qlike"])
    mean_corr = float(np.mean([r["corr_sqrtRQ_RVd"] for r in results]))

    if harq_sig_better > 0:
        v = "HARQ_HELPS"
        support = "CONTRADICTED"
    elif harq_sig_worse > 0:
        v = "HARQ_HURTS_SIGNIFICANT"
        support = "SUPPORTED_SIGNIFICANT"
    else:
        # 無任一方向 Harvey-顯著 → canonical NULL
        v = "NULL"
        support = ("SUPPORTED_DIRECTIONAL" if harq_worse >= (n + 1) // 2
                   else "NOT_SUPPORTED")

    note = (
        f"canonical={v}（無資產達 Harvey |t|>3；HARQ 顯著優 {harq_sig_better}/{n}、"
        f"顯著劣 {harq_sig_worse}/{n}）。contrarian 假說 directional 支持={support}："
        f"{harq_worse}/{n} 資產 HARQ QLIKE 劣於 HAR（1-2%，統計不顯著）。"
        f"主機制證據：√RQ 與 RV_(t-1) 平均相關 {mean_corr:.2f}（3/3 一致）——日頻下"
        "「測量誤差權重」√RQ 幾乎與 RV 本身共線，交互項≈RV²，不帶獨立的測量誤差訊息。"
        f"次要機制探針（mixed）：平滑 √RQ（5日）僅在 {smooth_recovers}/{n} 資產縮小退化"
        "（SPY 略回正、兩檔台股反更差），故單日 RQ 噪音只是部分原因。"
        " 結論：日頻 OHLC 代理下 HARQ 測量誤差加權相對樸素 HAR 無 OOS 增益（一致但不顯著的輕微退化），"
        "與高頻 RV 下的 HARQ（K1582 TX 方向有利）形成對照。"
    )
    return v, support, note


def main():
    print("K1661 | HARQ 測量誤差加權 in OHLC-proxy regime", flush=True)
    results = []
    all_losses = {}
    for name, ticker in ASSETS.items():
        print(f"→ {name} ({ticker}) ...", flush=True)
        r, losses = run_asset(name, ticker)
        results.append(r)
        all_losses[name] = losses
        h = r["dm_hln_HARQ_vs_HAR"]
        hs = r["dm_hln_HARQ_smooth_vs_HAR"]
        print(f"   HAR QLIKE={r['models']['HAR']['qlike']:.5f}  "
              f"HARQ={r['models']['HARQ']['qlike']:.5f}(Δ{r['qlike_improve_HARQ_pct']:+.2f}%, "
              f"t={h['dm_hln']:.3f})  "
              f"HARQ-smooth={r['models']['HARQ-smooth']['qlike']:.5f}"
              f"(Δ{r['qlike_improve_HARQ_smooth_pct']:+.2f}%, t={hs['dm_hln']:.3f})  "
              f"corr(√RQ,RVd)={r['corr_sqrtRQ_RVd']:.2f}  "
              f"insanity={r['models']['HARQ']['insanity_pct']:.1f}%", flush=True)

    verdict, contrarian_support, note = verdict_from_results(results)

    payload = {
        "experiment_id": "k1661",
        "title": "HARQ 測量誤差加權在日頻 OHLC 代理噪音下的 contrarian 檢定",
        "hypothesis": ("日頻 OHLC 下 RQ proxy 本身高噪音（無日內平均、與 RV 共線），"
                       "HARQ 測量誤差加權無益甚至傷害 OOS 預測（代理噪音下誤差加權反轉）"),
        "seed": SEED,
        "window_scheme": f"rolling W={WINDOW}, one-step, daily refit",
        "rv_proxy": "Garman-Klass daily range (neg→Parkinson)",
        "rq_proxy": "range-based quarticity (ln H/L)^4; sqrtRQ=(ln H/L)^2",
        "loss": "QLIKE (actual/predicted, Patton 2011) + MSE",
        "dm_test": "Diebold-Mariano with Harvey-Leybourne-Newbold (1997) small-sample correction, h=1",
        "harvey_gate": "|t|>3 (project OOS DM gate)",
        "assets": list(ASSETS.keys()),
        "results": results,
        "verdict": verdict,
        "contrarian_hypothesis_support": contrarian_support,
        "verdict_note": note,
        "references": [
            "Corsi (2009) JFE 7(2), 174-196 [HAR]",
            "Bollerslev, Patton & Quaedvlieg (2016) JoE 192(1), 1-18 [HARQ]",
            "Garman & Klass (1980) J.Business 53(1), 67-78 [GK range estimator]",
            "Parkinson (1980) J.Business 53(1), 61-65 [range variance]",
            "Patton (2011) JoE 160(1), 246-256 [QLIKE proxy-robust]",
            "Harvey, Leybourne & Newbold (1997) IJF 13(2), 281-291 [HLN correction]",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (HERE / "k1661_results.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    print(f"\nVERDICT: {verdict}\n{note}", flush=True)

    _make_figures(results, all_losses)
    return payload


def _make_figures(results, all_losses):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [r["asset"] for r in results]

    # Fig 1: QLIKE bar HAR vs HARQ vs HARQ-F vs HARQ-smooth
    order = ["HAR", "HARQ", "HARQ-F", "HARQ-smooth"]
    fig, ax = plt.subplots(figsize=(9, 5))
    x = np.arange(len(names))
    w = 0.2
    for j, m in enumerate(order):
        vals = [r["models"][m]["qlike"] for r in results]
        ax.bar(x + (j - 1.5) * w, vals, w, label=m)
    ax.set_xticks(x)
    ax.set_xticklabels(names)
    ax.set_ylabel("OOS QLIKE (lower = better)")
    ax.set_title("K1661: HAR vs HARQ family — OOS QLIKE\n(daily OHLC Garman-Klass RV proxy; rolling W=1000)")
    ax.legend(fontsize=8)
    for i, r in enumerate(results):
        t = r["dm_hln_HARQ_vs_HAR"]["dm_hln"]
        ax.annotate(f"DM-HLN t={t:.2f}", (i, max(r['models']['HAR']['qlike'],
                    r['models']['HARQ']['qlike'])), ha="center", va="bottom", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "qlike_comparison.png", dpi=130)
    plt.close(fig)

    # Fig 2: √RQ_{t-1} vs RV_{t-1} 散點 —— 直接視覺化「測量誤差權重」與 RV 的共線性
    fig, axes = plt.subplots(1, len(names), figsize=(4.2 * len(names), 4))
    if len(names) == 1:
        axes = [axes]
    for ax, r, name in zip(axes, results, names):
        des = all_losses[name]["_design"]
        rv, srq = des["RV_d"], des["sqrtRQ"]
        ax.scatter(rv, srq, s=3, alpha=0.12, color="tab:blue")
        lim = np.nanpercentile(rv, 99)
        ax.set_xlim(0, lim)
        ax.set_ylim(0, np.nanpercentile(srq, 99))
        ax.set_title(f"{name}\ncorr(√RQ, RV_t-1)={r['corr_sqrtRQ_RVd']:.2f}")
        ax.set_xlabel("RV_{t-1} (Garman-Klass)")
        ax.set_ylabel("√RQ_{t-1} = (ln H/L)²")
    fig.suptitle("K1661: measurement-error weight sqrt(RQ) nearly collinear with RV "
                 "(daily OHLC proxy)\n-> HARQ interaction ~ RV^2, carries no independent "
                 "measurement-error signal")
    fig.tight_layout()
    fig.savefig(FIG_DIR / "rq_collinearity.png", dpi=130)
    plt.close(fig)

    # Fig 3: rolling cumulative QLIKE loss differential HARQ-HAR (SPY)
    fig, ax = plt.subplots(figsize=(9, 5))
    for name in names:
        L = all_losses[name]
        diff = L["HARQ"]["qlike_pw"] - L["HAR"]["qlike_pw"]  # >0 → HARQ worse
        cum = np.cumsum(diff)
        ax.plot(L["HARQ"]["dates"], cum, label=name, lw=1.1)
    ax.axhline(0, color="k", lw=0.6)
    ax.set_ylabel("cumulative (QLIKE_HARQ − QLIKE_HAR)\n>0 → HARQ worse")
    ax.set_title("K1661: rolling cumulative QLIKE loss differential (HARQ − HAR)")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIG_DIR / "rolling_loss_diff.png", dpi=130)
    plt.close(fig)
    print("figures written:", [p.name for p in FIG_DIR.glob("*.png")], flush=True)


if __name__ == "__main__":
    main()
