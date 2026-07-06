"""K1653 — 成交量能否預測「隔日報酬方向（漲跌 sign）」？

技術分析迷思實驗室：
  迷思 1「量先價行」：成交量放大 / 量增 → 隔日上漲？
  迷思 2「爆量長黑是出貨」：爆量 + 大跌長黑K → 隔日續跌？

與既有 K 的差異化（正交角度）：
  K710  Volume as Vol Predictor      → 測 volume → 波動率（incremental R²=0.0023 beyond VIX）
  K753/K754 Volume Exhaustion Effect → 測 extreme volume → future VIX/波動率（不預測）
  K1653（本實驗）                    → 測 volume → 報酬「方向 / sign」（全新未覆蓋角度）

方法論防錯（違反即實驗失敗）：
  * Lookahead 最高風險：所有 volume 訊號一律 signal.shift(1)
    —— row i 的預測子取自 i-1（昨日已收盤、完全 realized），預測 i 日的報酬 sign。
       等價於「今日觀察到的量預測明日方向」。程式碼有明確 .shift(1)。
  * H = 1（單日 ahead），無 overlapping target，DM/檢定 horizon = 1。
  * 所有隨機程序固定 seed = 42。
  * 方向性檢定：binomial test + Pesaran-Timmermann (1992)；不看圖下結論。
  * 事件研究：event 判定僅用當日(t) 已 realized 資訊，看 t+1 報酬，無 lookahead。
  * 誠實報告 null：成交量不預測隔日方向 = 有效市場 / 迷思破解，是好結果。

可復現：uv run python experiments/k1653/k1653.py
"""

from __future__ import annotations

import json
import os
import sys
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from scipy import stats

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)

HERE = os.path.dirname(os.path.abspath(__file__))
# 讓 volpred.utils 的 clean_tw50_data 可 import（修 0050.TW split artifact）
sys.path.insert(0, os.path.join(HERE, "..", "..", "src"))

try:
    from volpred.utils import clean_tw50_data
    _HAS_CLEANER = True
except Exception:  # pragma: no cover
    _HAS_CLEANER = False


# ---------------------------------------------------------------------------
# 資料下載
# ---------------------------------------------------------------------------
def _flatten(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance 有時回 MultiIndex 欄位（單 ticker）→ 攤平成單層。"""
    if isinstance(df.columns, pd.MultiIndex):
        df = df.copy()
        df.columns = [c[0] for c in df.columns]
    return df


def download(ticker: str, start: str, end: str | None) -> pd.DataFrame:
    import yfinance as yf

    df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise RuntimeError(f"yfinance 下載 {ticker} 失敗（空資料）")
    df = _flatten(df)
    df = df[["Open", "High", "Low", "Close", "Volume"]].copy()
    df = df.dropna()
    return df


def build_features(df: pd.DataFrame, is_tw50: bool) -> pd.DataFrame:
    """建構特徵與報酬。所有量特徵在第 t 列 = 用「到 t 為止（含 t）」已收盤資訊。

    對齊由後續 .shift(1) 統一處理（signal from t-1, return at t）。
    """
    out = pd.DataFrame(index=df.index)
    close = df["Close"].astype(float)
    vol = df["Volume"].astype(float)

    # 0050.TW split artifact 修正（2014-01-02 斷點）；本實驗 TW0050 從 2015 起
    # 已避開斷點，但仍套 cleaner 作雙保險。
    if is_tw50 and _HAS_CLEANER:
        close_clean, _ = clean_tw50_data(close)
        close = close_clean.reindex(close.index)

    out["close"] = close
    out["open"] = df["Open"].astype(float)
    out["volume"] = vol

    # close-to-close 報酬（主口徑）
    out["ret"] = close.pct_change()

    # 量特徵（皆為第 t 日 realized，之後統一 shift(1)）
    vol_ma20 = vol.rolling(20).mean()
    vol_std60 = vol.rolling(60).std()
    vol_ma60 = vol.rolling(60).mean()
    out["vol_ratio20"] = vol / vol_ma20          # 相對量能（量增倍數）
    out["vol_change"] = np.log(vol / vol.shift(1))  # 量的日變化（log）
    out["vol_z60"] = (vol - vol_ma60) / vol_std60   # 量 z-score（60日）
    # 當日量在過去 252 日的百分位（top decile 用）
    out["vol_pct252"] = vol.rolling(252).apply(
        lambda w: (w[-1] >= w).mean(), raw=True
    )
    # 長黑K 判定用：當日報酬（close-to-close）已在 ret
    out["is_black"] = (df["Close"].astype(float) < df["Open"].astype(float)).astype(int)

    # sanitize：volume=0 的日子會使 log-ratio / z-score 變 inf，統一轉 NaN
    # （後續 dropna 會排除，避免 Logit exog 含 inf）
    out = out.replace([np.inf, -np.inf], np.nan)

    return out


# ---------------------------------------------------------------------------
# 方向性檢定
# ---------------------------------------------------------------------------
def pesaran_timmermann(actual_sign: np.ndarray, pred_sign: np.ndarray) -> dict:
    """Pesaran-Timmermann (1992) directional accuracy test.

    actual_sign / pred_sign ∈ {+1, -1}（0 視為 +1 平局歸多方，已在呼叫端處理）。
    回傳 PT 統計量（~N(0,1)）與 p-value（雙尾）。
    """
    a = np.asarray(actual_sign)
    p = np.asarray(pred_sign)
    n = len(a)
    if n < 20:
        return {"pt_stat": None, "p_value": None, "n": int(n), "note": "n<20"}

    # 轉成 up=1 / down=0
    ay = (a > 0).astype(float)
    px = (p > 0).astype(float)

    Py = ay.mean()          # 實際 up 比例
    Px = px.mean()          # 預測 up 比例
    # 正確命中率（同號）
    hit = ((a > 0) == (p > 0)).mean()

    Pstar = Py * Px + (1 - Py) * (1 - Px)  # 兩序列獨立時的期望命中率

    var_hit = Pstar * (1 - Pstar) / n
    var_star = (
        ((2 * Py - 1) ** 2) * Px * (1 - Px) / n
        + ((2 * Px - 1) ** 2) * Py * (1 - Py) / n
        + 4 * Py * Px * (1 - Py) * (1 - Px) / (n ** 2)
    )
    denom = var_hit - var_star
    if denom <= 0:
        return {
            "pt_stat": None, "p_value": None, "n": int(n),
            "hit_rate": float(hit), "expected_hit": float(Pstar),
            "note": "degenerate variance (Px or Py ~ 0/1)",
        }
    pt = (hit - Pstar) / np.sqrt(denom)
    pval = 2 * (1 - stats.norm.cdf(abs(pt)))
    return {
        "pt_stat": float(pt),
        "p_value": float(pval),
        "n": int(n),
        "hit_rate": float(hit),
        "expected_hit": float(Pstar),
        "pred_up_frac": float(Px),
        "actual_up_frac": float(Py),
    }


def binomial_hit(actual_sign: np.ndarray, pred_sign: np.ndarray) -> dict:
    """命中率 vs 50% 的 binomial test。"""
    correct = int(((actual_sign > 0) == (pred_sign > 0)).sum())
    n = int(len(actual_sign))
    res = stats.binomtest(correct, n, 0.5, alternative="two-sided")
    return {
        "n": n,
        "correct": correct,
        "hit_rate": correct / n if n else None,
        "binom_p": float(res.pvalue),
    }


def directional_test(sig_lagged: pd.Series, ret: pd.Series, rule: str) -> dict:
    """給定「已 lag-1 的訊號」與報酬，形成方向預測並檢定。

    rule:
      'sign'   → 預測方向 = sign(訊號)（量增/量 z-score 正→預測漲）
      'high'   → 訊號 > 中位數 → 預測漲，否則跌（量能水準迷思）
    """
    df = pd.concat([sig_lagged.rename("sig"), ret.rename("ret")], axis=1).dropna()
    # 去掉 ret 剛好 =0 的極少數（方向未定義）
    df = df[df["ret"] != 0]
    if len(df) < 30:
        return {"n": int(len(df)), "note": "insufficient"}

    if rule == "sign":
        pred = np.where(df["sig"].values > 0, 1, -1)
    elif rule == "high":
        thr = df["sig"].median()
        pred = np.where(df["sig"].values > thr, 1, -1)
    else:
        raise ValueError(rule)

    actual = np.where(df["ret"].values > 0, 1, -1)
    out = {"rule": rule}
    out.update(binomial_hit(actual, pred))
    out["pt"] = pesaran_timmermann(actual, pred)
    return out


# ---------------------------------------------------------------------------
# Logistic regression（in-sample + expanding OOS）
# ---------------------------------------------------------------------------
def logistic_analysis(feat: pd.DataFrame) -> dict:
    import statsmodels.api as sm

    cols = ["vol_ratio20", "vol_change", "vol_z60"]
    # 訊號一律 shift(1)：row i 用 i-1 的量特徵，預測 i 日方向
    X = feat[cols].shift(1)
    y = (feat["ret"] > 0).astype(int)
    lag_ret = feat["ret"].shift(1)  # 昨日報酬也是合法（已 realized）
    data = pd.concat([X, lag_ret.rename("lag_ret"), y.rename("up")], axis=1)
    data = data[feat["ret"] != 0].dropna()
    if len(data) < 200:
        return {"note": "insufficient", "n": int(len(data))}

    feat_cols = cols + ["lag_ret"]
    Xd = sm.add_constant(data[feat_cols])
    yd = data["up"].values

    # In-sample
    try:
        model = sm.Logit(yd, Xd).fit(disp=0, maxiter=200)
        insample = {
            "pseudo_r2_mcfadden": float(model.prsquared),
            "n": int(len(yd)),
            "llr_p": float(model.llr_pvalue),
            "coefs": {c: float(model.params[c]) for c in Xd.columns},
            "tstats": {c: float(model.tvalues[c]) for c in Xd.columns},
            "pvalues": {c: float(model.pvalues[c]) for c in Xd.columns},
        }
    except Exception as e:  # pragma: no cover
        insample = {"note": f"fit failed: {e}"}

    # Expanding OOS：origin o 用 rows [0, o-1] 訓練（target 為單日 H=1，
    # 訓練列 target 皆 < forecast day，無 lookahead），預測 row o 的方向。
    n = len(data)
    min_train = max(500, n // 3)
    step = 1
    preds, actuals = [], []
    Xarr = Xd.values
    for o in range(min_train, n, step):
        Xtr, ytr = Xarr[:o], yd[:o]
        try:
            m = sm.Logit(ytr, Xtr).fit(disp=0, maxiter=200)
            p_up = m.predict(Xarr[o:o + 1])[0]
        except Exception:
            continue
        preds.append(1 if p_up > 0.5 else -1)
        actuals.append(1 if yd[o] > 0 else -1)
    oos = {}
    if len(preds) >= 30:
        preds = np.array(preds)
        actuals = np.array(actuals)
        oos.update(binomial_hit(actuals, preds))
        oos["pt"] = pesaran_timmermann(actuals, preds)
        oos["min_train"] = int(min_train)
    else:
        oos = {"note": "insufficient OOS", "n": len(preds)}

    return {"in_sample": insample, "oos_expanding": oos, "features": feat_cols}


# ---------------------------------------------------------------------------
# 事件研究：爆量長黑
# ---------------------------------------------------------------------------
def event_study(feat: pd.DataFrame, drop_thr: float = -0.01) -> dict:
    """爆量長黑日（t）= 量在過去252日 top decile 且 當日報酬 < drop_thr（且長黑K）。
    看隔日(t+1) 報酬分佈 vs 無條件分佈。

    Lag：event 用當日 realized 資訊（vol_pct252 與 ret 皆 t 日已知），
         next_ret = ret.shift(-1) 對齊到 t 的隔日。等價 event.shift(1) 選隔日報酬。
    """
    df = feat.copy()
    # 爆量：過去252日百分位 >= 0.9（top decile）
    is_bang = df["vol_pct252"] >= 0.90
    is_drop = df["ret"] < drop_thr
    is_black = df["is_black"] == 1
    event = (is_bang & is_drop & is_black)

    next_ret = df["ret"].shift(-1)  # t 的隔日報酬
    ev_next = next_ret[event].dropna()
    all_next = next_ret.dropna()
    # 無條件對照 = 全樣本隔日報酬
    uncond = all_next

    if len(ev_next) < 10:
        return {
            "n_events": int(len(ev_next)),
            "note": "太少事件，無法檢定",
            "drop_threshold": drop_thr,
        }

    # t-test（事件隔日 vs 無條件平均）與 Mann-Whitney
    t_stat, t_p = stats.ttest_ind(ev_next.values, uncond.values, equal_var=False)
    mw_u, mw_p = stats.mannwhitneyu(ev_next.values, uncond.values, alternative="two-sided")
    winrate = float((ev_next > 0).mean())

    return {
        "n_events": int(len(ev_next)),
        "drop_threshold": drop_thr,
        "event_next_mean": float(ev_next.mean()),
        "event_next_median": float(ev_next.median()),
        "event_next_winrate": winrate,          # 隔日上漲比例
        "uncond_next_mean": float(uncond.mean()),
        "uncond_next_median": float(uncond.median()),
        "uncond_next_winrate": float((uncond > 0).mean()),
        "welch_t": float(t_stat),
        "welch_p": float(t_p),
        "mannwhitney_u": float(mw_u),
        "mannwhitney_p": float(mw_p),
        # 迷思說「隔日續跌」→ 若 event_next_mean 顯著 < 0 且 winrate<0.5 才支持
        "myth_supported": bool(t_p < 0.05 and ev_next.mean() < 0),
    }


# ---------------------------------------------------------------------------
# 跨期間穩健性
# ---------------------------------------------------------------------------
def subperiod_analysis(feat: pd.DataFrame) -> list:
    """把樣本切 3 段，各自報 directional accuracy（量增 sign 規則）。"""
    df = feat.dropna(subset=["ret"]).copy()
    n = len(df)
    bounds = [0, n // 3, 2 * n // 3, n]
    results = []
    for i in range(3):
        seg = df.iloc[bounds[i]:bounds[i + 1]]
        sig = seg["vol_change"].shift(1)  # 昨日量增 → 今日方向
        res = directional_test(sig, seg["ret"], rule="sign")
        res["period"] = f"P{i+1}"
        res["start"] = str(seg.index[0].date())
        res["end"] = str(seg.index[-1].date())
        results.append(res)
    return results


# ---------------------------------------------------------------------------
# 單資產完整分析
# ---------------------------------------------------------------------------
def analyze_asset(name: str, ticker: str, start: str, end: str | None,
                  is_tw50: bool) -> dict:
    df = download(ticker, start, end)
    feat = build_features(df, is_tw50)
    feat_valid = feat.dropna(subset=["ret"])
    n_obs = int(len(feat_valid))
    period = (str(feat_valid.index[0].date()), str(feat_valid.index[-1].date()))

    # 迷思 1：量先價行 —— 三種訊號 × 全樣本 directional test
    myth1 = {}
    # (a) 量增 (vol_change) sign 規則：量增→預測漲
    myth1["vol_change_sign"] = directional_test(
        feat["vol_change"].shift(1), feat["ret"], rule="sign")
    # (b) 量能水準 (vol_ratio20) high 規則：量 > 中位數 → 預測漲
    myth1["vol_ratio20_high"] = directional_test(
        feat["vol_ratio20"].shift(1), feat["ret"], rule="high")
    # (c) 量 z-score sign 規則
    myth1["vol_z60_sign"] = directional_test(
        feat["vol_z60"].shift(1), feat["ret"], rule="sign")
    # (d) logistic 多元
    myth1["logistic"] = logistic_analysis(feat)

    # 迷思 2：爆量長黑（兩個 drop threshold）
    myth2 = {
        "drop_lt_1pct": event_study(feat, drop_thr=-0.01),
        "drop_lt_2pct": event_study(feat, drop_thr=-0.02),
    }

    # 跨期間穩健性
    subperiods = subperiod_analysis(feat)

    return {
        "asset": name,
        "ticker": ticker,
        "period": {"start": period[0], "end": period[1]},
        "n_obs": n_obs,
        "unconditional_up_rate": float((feat_valid["ret"] > 0).mean()),
        "myth1_liang_xian_jia_xing": myth1,
        "myth2_bang_volume_long_black": myth2,
        "subperiods": subperiods,
        "_feat": feat,  # 內部用於畫圖，寫 JSON 前移除
    }


# ---------------------------------------------------------------------------
# 圖表
# ---------------------------------------------------------------------------
def make_charts(results: list):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # macOS CJK 字型（避免中文標題變 tofu 方框）
    for cand in ["Heiti TC", "PingFang TC", "Arial Unicode MS", "STHeiti"]:
        try:
            font_manager.findfont(cand, fallback_to_default=False)
            plt.rcParams["font.sans-serif"] = [cand]
            break
        except Exception:
            continue
    plt.rcParams["axes.unicode_minus"] = False

    # 圖 1：hit-rate by sub-period bar（各資產）
    fig, axes = plt.subplots(1, len(results), figsize=(6 * len(results), 4.5), squeeze=False)
    for j, r in enumerate(results):
        ax = axes[0][j]
        periods = [s["period"] for s in r["subperiods"]]
        hits = [s.get("hit_rate", np.nan) for s in r["subperiods"]]
        bars = ax.bar(periods, hits, color="#4C72B0")
        ax.axhline(0.5, color="red", ls="--", lw=1, label="50% baseline")
        ax.set_ylim(0.40, 0.60)
        ax.set_title(f"{r['asset']} 量增訊號 隔日命中率\n(by sub-period)")
        ax.set_ylabel("directional hit-rate")
        for b, h in zip(bars, hits):
            if h is not None and not np.isnan(h):
                ax.text(b.get_x() + b.get_width() / 2, h + 0.003, f"{h:.3f}",
                        ha="center", fontsize=9)
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "k1653_hitrate_by_period.png"), dpi=120)
    plt.close(fig)

    # 圖 2：爆量長黑 隔日報酬分佈 vs 無條件
    fig, axes = plt.subplots(1, len(results), figsize=(6 * len(results), 4.5), squeeze=False)
    for j, r in enumerate(results):
        ax = axes[0][j]
        feat = r["_feat"]
        is_bang = feat["vol_pct252"] >= 0.90
        is_drop = feat["ret"] < -0.01
        is_black = feat["is_black"] == 1
        event = is_bang & is_drop & is_black
        next_ret = feat["ret"].shift(-1)
        ev = (next_ret[event].dropna() * 100).values
        un = (next_ret.dropna() * 100).values
        ax.hist(un, bins=50, density=True, alpha=0.5, color="#999999", label="無條件隔日")
        if len(ev) >= 5:
            ax.hist(ev, bins=20, density=True, alpha=0.6, color="#C44E52",
                    label=f"爆量長黑後隔日 (n={len(ev)})")
            ax.axvline(ev.mean(), color="#C44E52", ls="--", lw=1.5)
        ax.axvline(un.mean(), color="#333333", ls="--", lw=1)
        ax.set_xlim(-6, 6)
        ax.set_title(f"{r['asset']} 爆量長黑後 隔日報酬分佈")
        ax.set_xlabel("次日報酬 (%)")
        ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "k1653_event_study_dist.png"), dpi=120)
    plt.close(fig)


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _strip_internal(obj):
    if isinstance(obj, dict):
        return {k: _strip_internal(v) for k, v in obj.items() if not k.startswith("_")}
    if isinstance(obj, list):
        return [_strip_internal(v) for v in obj]
    return obj


def atomic_write_json(path: str, data: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # 驗證可解析
    with open(tmp, "r", encoding="utf-8") as f:
        json.load(f)
    os.replace(tmp, path)


def main():
    assets = [
        # name, ticker, start, is_tw50
        ("TW0050", "0050.TW", "2015-01-01", True),  # 起 2015 避開 2014 split 斷點
        ("SPY", "SPY", "2012-01-01", False),
    ]
    end = None

    results = []
    for name, ticker, start, is_tw50 in assets:
        try:
            r = analyze_asset(name, ticker, start, end, is_tw50)
            results.append(r)
            print(f"[{name}] n={r['n_obs']} {r['period']['start']}~{r['period']['end']} done")
        except Exception as e:
            print(f"[{name}] FAILED: {e}")
            results.append({"asset": name, "ticker": ticker, "error": str(e)})

    # 圖表
    try:
        make_charts([r for r in results if "_feat" in r])
    except Exception as e:
        print(f"[charts] FAILED: {e}")

    out = {
        "experiment_id": "k1653",
        "title": "成交量能否預測隔日報酬方向（漲跌 sign）— 技術分析迷思檢定",
        "myths_tested": [
            "量先價行（量增/量放大 → 隔日漲）",
            "爆量長黑是出貨（爆量+大跌長黑K → 隔日續跌）",
        ],
        "orthogonal_to": {
            "K710": "volume → 波動率 (incremental R²=0.0023 beyond VIX)",
            "K753": "extreme volume → future VIX/波動率 (exhaustion, 不預測)",
            "K754": "volume exhaustion effect on volatility",
            "note": "K1653 測 return DIRECTION (sign)，與上述測 volatility 正交",
        },
        "methodology": {
            "target": "sign(close-to-close daily return)",
            "lag": "所有 volume 訊號 signal.shift(1) —— row i 用 i-1 已收盤量特徵預測 i 日方向",
            "horizon": 1,
            "seed": SEED,
            "tests": ["binomial vs 0.5", "Pesaran-Timmermann (1992)",
                      "logistic (in-sample + expanding OOS)", "event study Welch-t + Mann-Whitney"],
            "data_source": "yfinance auto_adjust=True daily OHLCV",
        },
        "generated_at": datetime.now().isoformat(),
        "results": _strip_internal(results),
    }

    out_path = os.path.join(HERE, "k1653_results.json")
    atomic_write_json(out_path, out)
    print(f"\nresults written -> {out_path}")

    # 簡要 verdict 印出
    for r in results:
        if "error" in r:
            continue
        print(f"\n===== {r['asset']} =====")
        for k, v in r["myth1_liang_xian_jia_xing"].items():
            if k == "logistic":
                oos = v.get("oos_expanding", {})
                print(f"  myth1/logistic OOS: hit={oos.get('hit_rate')} "
                      f"binom_p={oos.get('binom_p')} "
                      f"PT_p={oos.get('pt', {}).get('p_value')}")
            else:
                print(f"  myth1/{k}: hit={v.get('hit_rate')} binom_p={v.get('binom_p')} "
                      f"PT_p={v.get('pt', {}).get('p_value')}")
        for k, v in r["myth2_bang_volume_long_black"].items():
            print(f"  myth2/{k}: n_ev={v.get('n_events')} "
                  f"next_mean={v.get('event_next_mean')} "
                  f"winrate={v.get('event_next_winrate')} "
                  f"welch_p={v.get('welch_p')} supported={v.get('myth_supported')}")


if __name__ == "__main__":
    main()
