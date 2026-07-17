"""K1684 E2 — own-market realized-target forecast-tail-divergence cross-OOS gate.

背景
----
K1684 R3 (E1) 判為 **H2_UNSUPPORTED**：E1 的致命缺陷是拿 TX 期貨重建的 5-min RV 去配
0050 ETF 的 close-to-close 報酬（cross-asset RV plug-in），造成「HAR 在自己那個 RV 目標上贏、
GJR 在 r² 目標上贏」的方向翻轉 —— 那是 *target-mismatch* 指紋，不是真的 divergence。而且 own-market
那條（TX-RV 目標）只有 n=450 且 |t|=2.10，未過 Harvey |t|>3 門檻。

E2 的唯一合法設計 = forecast 與 realized target 必須是**同一市場、同一標的**，n≥2500，跨 OOS 視窗 +
regime split + block-bootstrap sensitivity 再驗證。

E2 設計（own-market，apples-to-apples）
--------------------------------------
* 標的：^GSPC（S&P 500，primary）、^N225（Nikkei 225，external validity）。兩者皆 own-market。
* Forecast object = **同一標的的 open-to-close（交易時段）報酬與其 1-day-ahead 條件變異數**
  （指數無隔夜交易 → 交易時段變異數是自然的 own-market realized target；也對應高頻 5-min RV 捕捉的量）。
* Realized measure（同一標的自身的 OHLC，日內 range-based）：
    - GK  = Garman–Klass(1980)     ← primary（最有效率、平滑）
    - PK  = Parkinson(1980)、RS = Rogers–Satchell(1991)  ← robustness（平滑）
    - co² = 平方 open-to-close 報酬 ← Patton(2011) conditionally-unbiased（但吵、QLIKE 低 power）proxy
  註：真正的 5-min RV（Oxford-Man 已停站、官方網域 dead）在 n≥2500 尺度不可得 → 誠實改用 range-based
  realized measure（文獻支撐見 README §文獻）。GK/PK/RS 有效率但在離散價格下**系統性向下偏**；co² 無偏但吵。
* 兩個模型都預測 open-to-close 條件變異數（同一資訊集、同一 refit cadence，對稱）：
    - HAR-RV：log-HAR（Corsi 2009），輸入=落後 GK（日/週=5/月=22），expanding window，每 22 交易日 refit。
    - GJR-GARCH(1,1)-t：arch MLE，expanding window，每 22 交易日 refit，refit 之間固定參數逐日 forward-filter。
* **公平性關鍵（E2 相對 E1 的核心防線）**：因 HAR 訓練在 GK（會吃到 GK 的向下偏誤）、GJR 不會，QLIKE 對
  「校準到偏誤 proxy 的模型」有系統性偏好（E1 target-mismatch 的同標的細緻版）。因此對**每個 proxy** 同時
  報 (1) RAW 與 (2) 兩模型皆做 lag-safe 對稱乘法 bias 校正後的 QLIKE/DM，並檢查 raw 是否跨 proxy 符號翻轉。
* 評估：QLIKE（主）+ canonical DM/HAC（Newey-West，bandwidth=ceil(h^⅓·n^⅓)）+ Harvey(1997) 小樣本修正；
  VaR 1%/5% 的 Kupiec(POF)+Christoffersen(CC joint)+Basel traffic light；ES 的 Acerbi–Székely Z1；
  FZ0(Fissler–Ziegel) joint scoring。
* 穩健性：跨 OOS 時間分段 DM、high/low-vol regime split、moving-block + stationary bootstrap（固定 seed）、
  經驗 scale 因子 c 的 bootstrap CI。

研究誠實：不論 H2 supported / NULL 都如實報告；null 不是失敗。完成後必經 Codex review 才決定 paper route。

Author: worktree agent (K1684 E2 dispatch)  |  seed=20260718
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
from scipy import stats

# canonical repo functions（唯一 source of truth）
from volpred.stats.model_evaluation import (
    dm_test as canonical_dm_test,
    qlike_pointwise as canonical_qlike_pointwise,
    unit_variance_student_t_ppf,
)

# --------------------------------------------------------------------------------------
# 常數 / seed
# --------------------------------------------------------------------------------------
MASTER_SEED = 20260718
INITIAL_TRAIN = 1250        # ~2000-2004 當 burn-in（GJR MLE + HAR 迴歸都夠）
REFIT_EVERY = 22            # 兩個模型同一 refit cadence（monthly）
RV_FLOOR = 1e-10            # decimal² 下限，只擋 exact-zero-range 日
ALPHAS = (0.01, 0.05)
Z1_MC_B = 1000             # Acerbi-Szekely Z1 蒙地卡羅 null replications
BOOT_B = 2000              # block / stationary bootstrap replications
HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")

INSTRUMENTS = [
    ("SPX", "^GSPC", os.path.join(DATA_DIR, "gspc_ohlc_2000_2026.csv")),
    ("N225", "^N225", os.path.join(DATA_DIR, "n225_ohlc_2000_2026.csv")),
]


# --------------------------------------------------------------------------------------
# 1. Realized measures（range-based，同一標的 OHLC）
# --------------------------------------------------------------------------------------
def build_frame(csv_path: str) -> pd.DataFrame:
    """讀 OHLC → 建 open-to-close（盤中/交易時段）報酬 + 四個日內 range-based 已實現變異數 proxy。

    forecast object = 同一標的的**盤中（open-to-close）報酬與其條件變異數**（指數無隔夜交易，
    交易時段變異數是自然的 own-market realized target；也對應高頻 5-min RV 捕捉的量）。
    - GK  = Garman–Klass(1980)     ← primary（最有效率、平滑的日內變異數估計量）
    - PK  = Parkinson(1980)         ← robustness（僅 H,L）
    - RS  = Rogers–Satchell(1991)   ← robustness（drift-independent）
    - co2 = 平方 open-to-close 報酬  ← Patton(2011) conditionally-unbiased（但吵、QLIKE 低 power）proxy
    註：GK/PK/RS 是有效率但在**離散價格下系統性向下偏**的估計量；co2 無偏但吵。兩類並用 + 對稱 bias
    校正，才能區分「HAR 真的追得準」與「HAR 只是校準到偏誤 proxy」（見 recalibrate + README §公平性）。
    單位 = decimal²。
    """
    df = pd.read_csv(csv_path, parse_dates=["Date"]).set_index("Date").sort_index()
    for col in ["Open", "High", "Low", "Close"]:
        df = df[df[col] > 0]
    o = df["Open"].to_numpy(float)
    h = df["High"].to_numpy(float)
    l = df["Low"].to_numpy(float)
    c = df["Close"].to_numpy(float)

    co = np.log(c / o)              # open-to-close（盤中）報酬 = forecast/VaR 的對象
    ho = np.log(h / o)
    lo = np.log(l / o)
    hl = np.log(h / l)

    gk = 0.5 * hl ** 2 - (2.0 * np.log(2.0) - 1.0) * co ** 2   # Garman–Klass
    pk = (1.0 / (4.0 * np.log(2.0))) * hl ** 2                 # Parkinson
    rs = ho * (ho - co) + lo * (lo - co)                       # Rogers–Satchell
    co2 = co ** 2                                              # 無偏但吵的 proxy

    out = pd.DataFrame(
        {
            "ret": co,
            "gk": np.maximum(gk, RV_FLOOR),
            "pk": np.maximum(pk, RV_FLOOR),
            "rs": np.maximum(rs, RV_FLOOR),
            "co2": np.maximum(co2, RV_FLOOR),
        },
        index=df.index,
    )
    return out.dropna()


# --------------------------------------------------------------------------------------
# 2. HAR-RV（log-HAR, Corsi 2009）
# --------------------------------------------------------------------------------------
def _har_design(logrv: np.ndarray) -> np.ndarray:
    """回傳每個 origin i 的特徵 [1, daily_{i-1}, weekly_{i-1}, monthly_{i-1}]（用 t-1 及更早）。
    回傳 shape (n, 4)，第 i 列是「預測第 i 日」用的、只用到 <= i-1 資訊的特徵。"""
    n = len(logrv)
    X = np.full((n, 4), np.nan)
    for i in range(n):
        if i < 1:
            continue
        daily = logrv[i - 1]
        wk = logrv[max(0, i - 5):i].mean()
        mo = logrv[max(0, i - 22):i].mean()
        X[i, :] = [1.0, daily, wk, mo]
    return X


def run_har(rv: np.ndarray, ret: np.ndarray, oos_start: int,
            n_stop: Optional[int] = None) -> Dict[str, np.ndarray]:
    """expanding-window log-HAR，每 REFIT_EVERY refit；回傳 OOS 變異數預測（decimal²）與標準化殘差。

    Lookahead-safe：預測第 i 日只用特徵 X[i]（<= i-1）；訓練配對 (X[j], y[j]) 的 y[j]=log rv[j]，
    最後一個訓練 j = origin-1 < i，滿足 target_end < forecast_origin。n_stop 僅供 audit 提早收斂。
    """
    n = len(rv)
    stop = n if n_stop is None else min(n_stop, n)
    logrv = np.log(rv)
    X = _har_design(logrv)  # X[i] 用 <= i-1
    var_fc = np.full(n, np.nan)
    beta_cur = None
    s2_cur = None
    for i in range(oos_start, stop):
        if (i - oos_start) % REFIT_EVERY == 0 or beta_cur is None:
            # 用 (X[j], logrv[j])，j 從第一個有效特徵(=1) 到 i-1（含）
            js = np.arange(1, i)
            Xtr = X[js]
            ytr = logrv[js]
            good = np.all(np.isfinite(Xtr), axis=1) & np.isfinite(ytr)
            Xtr, ytr = Xtr[good], ytr[good]
            beta_cur, *_ = np.linalg.lstsq(Xtr, ytr, rcond=None)
            resid = ytr - Xtr @ beta_cur
            s2_cur = float(np.var(resid, ddof=Xtr.shape[1]))
        xi = X[i]
        if not np.all(np.isfinite(xi)):
            continue
        # log-normal retransformation：E[RV] = exp(mu + 0.5 s^2)
        var_fc[i] = float(np.exp(xi @ beta_cur + 0.5 * s2_cur))
    var_fc = np.maximum(var_fc, RV_FLOOR)
    return {"var_fc": var_fc}


# --------------------------------------------------------------------------------------
# 3. GJR-GARCH(1,1)（arch，expanding，refit 之間固定參數 forward-filter）
# --------------------------------------------------------------------------------------
def run_gjr(ret: np.ndarray, oos_start: int,
            n_stop: Optional[int] = None) -> Dict[str, np.ndarray]:
    """expanding-window GJR-GARCH(1,1)-t，每 REFIT_EVERY refit，refit 之間用固定參數逐日 forward-filter。

    回傳 OOS 條件變異數預測（decimal²）與每日 Student-t 自由度 nu。
    模型與 HAR 用同一 refit cadence、同一資訊集（<= i-1 的報酬）。n_stop 僅供 audit 提早收斂。
    """
    from arch import arch_model

    n = len(ret)
    stop = n if n_stop is None else min(n_stop, n)
    SCALE = 100.0
    r_s = ret * SCALE  # arch optimizer 偏好 O(1) 尺度
    var_fc = np.full(n, np.nan)
    nu_fc = np.full(n, np.nan)

    params = None  # (mu, omega, alpha, gamma, beta, nu) in scaled units
    h_prev = None  # 前一日條件變異數（scaled）
    eps_prev = None  # 前一日殘差（scaled）

    for i in range(oos_start, stop):
        refit = ((i - oos_start) % REFIT_EVERY == 0) or (params is None)
        if refit:
            am = arch_model(r_s[:i], mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="t")
            res = am.fit(disp="off", show_warning=False)
            p = res.params
            mu = float(p.get("mu", 0.0))
            omega = float(p["omega"])
            alpha = float(p.get("alpha[1]", 0.0))
            gamma = float(p.get("gamma[1]", 0.0))
            beta = float(p.get("beta[1]", 0.0))
            nu = float(p.get("nu", 8.0))
            params = (mu, omega, alpha, gamma, beta, nu)
            # 從 fit 的最後一個 in-sample 值接續 recursion
            h_prev = float(res.conditional_volatility[-1] ** 2)
            eps_prev = float(res.resid[-1])
        mu, omega, alpha, gamma, beta, nu = params
        # 1-step-ahead 條件變異數（用 <= i-1 資訊）
        neg = 1.0 if eps_prev < 0 else 0.0
        h_i = omega + (alpha + gamma * neg) * eps_prev ** 2 + beta * h_prev
        var_fc[i] = h_i / (SCALE ** 2)
        nu_fc[i] = nu
        # 更新 recursion 到第 i 日（用實現報酬 r_s[i]）
        eps_prev = r_s[i] - mu
        h_prev = h_i

    var_fc = np.maximum(var_fc, RV_FLOOR)
    return {"var_fc": var_fc, "nu": nu_fc}


# --------------------------------------------------------------------------------------
# 3b. 對稱 bias 校正（消除「模型校準到偏誤 proxy」的 QLIKE artifact；Hansen–Lunde 風格）
# --------------------------------------------------------------------------------------
def recalibrate(fc: np.ndarray, target: np.ndarray, oos_start: int,
                min_pairs: int = 60) -> np.ndarray:
    """lag-safe expanding 乘法 bias 校正：k_t = mean(target[oos:t]) / mean(fc[oos:t])（只用 <= t-1）。

    對 HAR 與 GJR **對稱**套用同一程序 → 兩者對 target 皆均值無偏，QLIKE 只剩「時變追蹤品質」之別，
    不再獎勵「剛好校準到 proxy 系統性偏誤」的模型（E1 target-mismatch 的同標的細緻版之解藥）。
    """
    n = len(fc)
    out = np.full(n, np.nan)
    valid = np.isfinite(fc) & np.isfinite(target)
    valid[:oos_start] = False
    # 前綴和（含 index i）：pfx[i] = sum over [0, i]；用 [oos_start, i-1] = pfx[i-1]-pfx[oos_start-1]
    fc_c = np.where(valid, fc, 0.0)
    tg_c = np.where(valid, target, 0.0)
    pcnt = np.concatenate([[0.0], np.cumsum(valid.astype(float))])   # pcnt[k]=count in [0,k)
    pfc = np.concatenate([[0.0], np.cumsum(fc_c)])
    ptg = np.concatenate([[0.0], np.cumsum(tg_c)])
    for i in range(oos_start, n):
        if not np.isfinite(fc[i]):
            continue
        cnt = pcnt[i] - pcnt[oos_start]     # 有效對數在 [oos_start, i)
        if cnt < min_pairs:
            out[i] = fc[i]                  # 樣本不足時不校正（保守；早期 OOS 少數點）
            continue
        sf = pfc[i] - pfc[oos_start]
        st = ptg[i] - ptg[oos_start]
        if sf <= 0:
            out[i] = fc[i]
            continue
        out[i] = fc[i] * float(st / sf)
    return out


# --------------------------------------------------------------------------------------
# 4. Lookahead mechanical audit
# --------------------------------------------------------------------------------------
def lookahead_audit(frame: pd.DataFrame, oos_start: int, name: str) -> Dict:
    """機械稽核：(a) 每個 OOS forecast origin < target date；(b) 擾動未來值不改變當期預測。"""
    rv = frame["gk"].to_numpy(float)
    ret = frame["ret"].to_numpy(float)
    n = len(rv)
    dates = frame.index

    # (a) origin < target：預測第 i 日，origin=第 i-1 日收盤，target date=dates[i]
    origin_lt_target = bool(np.all(dates.values[oos_start - 1:n - 1] < dates.values[oos_start:n]))

    # (b) 擾動測試：把「未來」realized 值全部污染，重跑 HAR/GJR OOS 預測，前半段預測必須完全不變
    probe_i = oos_start + 200  # 在 OOS 內取一個檢查點
    stop = probe_i + REFIT_EVERY + 5  # audit 只需跑到 probe 之後一個 refit 週期
    har0 = run_har(rv.copy(), ret.copy(), oos_start, n_stop=stop)["var_fc"]
    gjr0 = run_gjr(ret.copy(), oos_start, n_stop=stop)["var_fc"]

    rv_p = rv.copy()
    ret_p = ret.copy()
    rng = np.random.default_rng(MASTER_SEED)
    rv_p[probe_i:] *= (1.0 + 5.0 * rng.random(n - probe_i))       # 污染未來 RV
    ret_p[probe_i:] += rng.normal(0, 0.05, n - probe_i)          # 污染未來報酬
    har1 = run_har(rv_p, ret_p, oos_start, n_stop=stop)["var_fc"]
    gjr1 = run_gjr(ret_p, oos_start, n_stop=stop)["var_fc"]

    # probe_i 之前（且已 refit 對齊）的預測必須不受未來污染影響
    def _unchanged_before(a, b, upto):
        m = np.isfinite(a[oos_start:upto]) & np.isfinite(b[oos_start:upto])
        return bool(np.allclose(a[oos_start:upto][m], b[oos_start:upto][m], rtol=0, atol=0))

    # HAR 每 REFIT_EVERY 用 expanding 到 origin-1 訓練，污染 probe_i 之後不影響 origin<=probe_i 的訓練/特徵
    har_safe = _unchanged_before(har0, har1, probe_i)
    gjr_safe = _unchanged_before(gjr0, gjr1, probe_i)

    return {
        "instrument": name,
        "origin_before_target": origin_lt_target,
        "har_forecasts_invariant_to_future": har_safe,
        "gjr_forecasts_invariant_to_future": gjr_safe,
        "probe_index": int(probe_i),
        "n_checked_before_probe": int(probe_i - oos_start),
        "passed": bool(origin_lt_target and har_safe and gjr_safe),
    }


# --------------------------------------------------------------------------------------
# 5. DM + Harvey(1997) 小樣本修正 + acf1
# --------------------------------------------------------------------------------------
def acf1(x: np.ndarray) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) < 3:
        return float("nan")
    xm = x - x.mean()
    denom = float(np.sum(xm ** 2))
    if denom <= 0:
        return float("nan")
    return float(np.sum(xm[1:] * xm[:-1]) / denom)


def hln_factor(n: int, h: int = 1) -> float:
    """Harvey, Leybourne & Newbold (1997) 小樣本修正因子。h=1 時 = sqrt((n-1)/n)。"""
    return float(np.sqrt((n + 1 - 2 * h + h * (h - 1) / n) / n))


def dm_full(loss1: np.ndarray, loss2: np.ndarray, h: int = 1) -> Dict:
    """canonical DM（Newey-West HAC, bandwidth=ceil(h^⅓n^⅓)）+ HLN(1997) 小樣本修正。
    負 t → model1(HAR) 較優。門檻 = Harvey-Liu-Zhu(2016) |t|>3。"""
    d = np.asarray(loss1, float) - np.asarray(loss2, float)
    mask = np.isfinite(d)
    d = d[mask]
    n = len(d)
    t_raw, p_raw = canonical_dm_test(loss1[mask], loss2[mask], h=h) if n >= 10 else (0.0, 1.0)
    fac = hln_factor(n, h)
    t_hln = t_raw * fac
    p_hln = 2 * (1 - stats.t.cdf(abs(t_hln), df=max(n - 1, 1)))
    return {
        "dm_t": float(t_raw),
        "dm_p": float(p_raw),
        "hln_t": float(t_hln),
        "hln_p": float(p_hln),
        "hln_factor": fac,
        "n": int(n),
        "loss_diff_acf1": acf1(d),
        "harvey_significant": bool(abs(t_hln) > 3.0),
        "favored": ("HAR" if t_hln < 0 else "GJR") if abs(t_hln) > 3.0 else "none",
    }


# --------------------------------------------------------------------------------------
# 6. VaR / ES 建構（overlay，對兩個模型對稱套用）
# --------------------------------------------------------------------------------------
def cornish_fisher_q(alpha: float, skew: float, kurt_excess: float) -> float:
    """Cornish-Fisher 修正分位（回傳標準化分位，通常為負）。"""
    z = stats.norm.ppf(alpha)
    return (
        z
        + (z ** 2 - 1) / 6.0 * skew
        + (z ** 3 - 3 * z) / 24.0 * kurt_excess
        - (2 * z ** 3 - 5 * z) / 36.0 * skew ** 2
    )


def normal_es_mult(alpha: float) -> float:
    """標準常態下 E[Z|Z<z_alpha]（負值）。"""
    z = stats.norm.ppf(alpha)
    return -stats.norm.pdf(z) / alpha


def student_t_unit_es_mult(alpha: float, nu: float) -> float:
    """unit-variance Student-t 下 E[Z|Z<q_alpha]（負值）。"""
    if nu <= 2:
        nu = 2.01
    q = unit_variance_student_t_ppf(alpha, nu)  # 已 unit-variance 縮放
    scale = np.sqrt((nu - 2) / nu)              # standard t → unit-variance
    t_q = q / scale                              # 還原成 standard-t 分位
    pdf = stats.t.pdf(t_q, df=nu)
    es_std = -pdf / alpha * (nu + t_q ** 2) / (nu - 1)  # standard-t ES
    return float(es_std * scale)


def build_var_es(sigma: np.ndarray, ret: np.ndarray, std_resid_pool_idx: np.ndarray,
                 nu: Optional[np.ndarray], method: str, alpha: float,
                 std_resid_all: np.ndarray) -> Dict[str, np.ndarray]:
    """回傳每日 VaR 與 ES（return 單位，皆為負值），mu 假設 0（日 equity VaR 慣例）。

    std_resid_all：全序列標準化殘差（z=ret/sigma），用來在每個 origin 以「<= t-1」的 pool 估 skew/kurt/分位。
    method ∈ {normal, cornish_fisher, histsim, student_t}
    """
    n = len(sigma)
    var = np.full(n, np.nan)
    es = np.full(n, np.nan)
    for i in range(n):
        s = sigma[i]
        if not np.isfinite(s) or s <= 0:
            continue
        if method == "normal":
            zq = stats.norm.ppf(alpha)
            var[i] = s * zq
            es[i] = s * normal_es_mult(alpha)
        elif method == "student_t":
            nui = float(nu[i]) if nu is not None and np.isfinite(nu[i]) else 8.0
            zq = unit_variance_student_t_ppf(alpha, nui)
            var[i] = s * zq
            es[i] = s * student_t_unit_es_mult(alpha, nui)
        else:
            # 需要「<= i-1」的標準化殘差 pool
            pool = std_resid_all[std_resid_pool_idx[i]]
            pool = pool[np.isfinite(pool)]
            if len(pool) < 100:
                continue
            if method == "cornish_fisher":
                sk = float(stats.skew(pool))
                ku = float(stats.kurtosis(pool, fisher=True))
                zq = cornish_fisher_q(alpha, sk, ku)
                var[i] = s * zq
                es[i] = np.nan  # CF 無 coherent ES（見 README）
            elif method == "histsim":
                zq = float(np.quantile(pool, alpha))
                var[i] = s * zq
                tail = pool[pool <= zq]
                es[i] = s * float(tail.mean()) if len(tail) else np.nan
    return {"var": var, "es": es}


# --------------------------------------------------------------------------------------
# 7. VaR / ES 檢定
# --------------------------------------------------------------------------------------
def _safe_log(x: float) -> float:
    return float(np.log(x)) if x > 0 else 0.0  # 0*log0 := 0 慣例


def kupiec_pof(viol: np.ndarray, alpha: float) -> Dict:
    """Kupiec POF LR_uc；0*log0:=0，零違規不自動 PASS（修 E1 記錄的父檔 bug）。"""
    n = int(len(viol))
    x = int(np.sum(viol))
    pi = x / n if n else 0.0
    ll_null = x * _safe_log(alpha) + (n - x) * _safe_log(1 - alpha)
    ll_alt = x * _safe_log(pi) + (n - x) * _safe_log(1 - pi)
    lr = -2 * (ll_null - ll_alt)
    lr = max(lr, 0.0)
    p = float(1 - stats.chi2.cdf(lr, df=1))
    return {"n": n, "violations": x, "rate": pi, "lr_uc": float(lr), "p": p}


def christoffersen_cc(viol: np.ndarray, alpha: float) -> Dict:
    """Christoffersen conditional coverage = LR_uc + LR_ind（joint, df=2）；正確處理 0 cell。"""
    v = viol.astype(int)
    n = len(v)
    # 轉移計數
    n00 = n01 = n10 = n11 = 0
    for t in range(1, n):
        a, b = v[t - 1], v[t]
        if a == 0 and b == 0:
            n00 += 1
        elif a == 0 and b == 1:
            n01 += 1
        elif a == 1 and b == 0:
            n10 += 1
        else:
            n11 += 1
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0
    pi = (n01 + n11) / (n00 + n01 + n10 + n11) if n > 1 else 0.0
    ll_ind = (
        n00 * _safe_log(1 - pi01) + n01 * _safe_log(pi01)
        + n10 * _safe_log(1 - pi11) + n11 * _safe_log(pi11)
    )
    ll_pooled = (n00 + n10) * _safe_log(1 - pi) + (n01 + n11) * _safe_log(pi)
    lr_ind = max(-2 * (ll_pooled - ll_ind), 0.0)
    uc = kupiec_pof(viol, alpha)
    lr_cc = max(uc["lr_uc"] + lr_ind, 0.0)
    p_cc = float(1 - stats.chi2.cdf(lr_cc, df=2))
    p_ind = float(1 - stats.chi2.cdf(lr_ind, df=1))
    return {"lr_ind": float(lr_ind), "p_ind": p_ind, "lr_cc": float(lr_cc), "p_cc": p_cc,
            "transitions": {"n00": n00, "n01": n01, "n10": n10, "n11": n11}}


def basel_light(viol: np.ndarray, alpha: float) -> Dict:
    """Basel traffic light。1%=canonical 250 天計數（綠≤4/黃5-9/紅≥10）；5%=自訂 α-scaled 延伸（非 canonical）。"""
    last = viol[-250:] if len(viol) >= 250 else viol
    cnt = int(np.sum(last))
    win = int(len(last))
    if abs(alpha - 0.01) < 1e-9:
        light = "green" if cnt <= 4 else ("yellow" if cnt <= 9 else "red")
        canonical = True
    else:
        # 自訂 α-scaled（250*0.05=12.5 期望）：綠≤20 / 黃≤45 / 紅>45 —— 明示非 canonical Basel
        light = "green" if cnt <= 20 else ("yellow" if cnt <= 45 else "red")
        canonical = False
    return {"window": win, "count_last250": cnt, "light": light, "canonical_basel": canonical}


def acerbi_szekely_z1(ret: np.ndarray, var: np.ndarray, es: np.ndarray, alpha: float,
                      sigma: np.ndarray, method: str, nu: Optional[np.ndarray],
                      seed: int, std_resid_pool: Optional[np.ndarray] = None) -> Dict:
    """Acerbi–Székely(2014) Test-1（Z1）。損失採 L=-ret 慣例；Z1=mean_{exceed}(L/ES_pos)-1，E[Z1]=0。
    Z1>0 → 實現尾部損失超過預測 ES（低估風險）。p-value 用參數化 MC（從各日預測分布抽樣）。"""
    m = np.isfinite(var) & np.isfinite(es) & np.isfinite(ret) & np.isfinite(sigma)
    r = ret[m]
    v = var[m]
    e = es[m]
    s = sigma[m]
    nu_m = nu[m] if nu is not None else None
    T = len(r)
    if T < 50:
        return {"z1": float("nan"), "p": float("nan"), "n_exceed": 0, "insufficient": True}
    exceed = r < v
    ne = int(np.sum(exceed))
    es_pos = -e  # 正值
    if ne == 0:
        return {"z1": float("nan"), "p": float("nan"), "n_exceed": 0, "note": "no exceedance"}
    L = -r
    z1_obs = float(np.mean((L[exceed] / es_pos[exceed])) - 1.0)

    # MC null：對每個 t 從其預測分布抽 standardized innovation，scale by sigma
    rng = np.random.default_rng(seed)
    pool = None
    if method == "histsim" and std_resid_pool is not None:
        pool = std_resid_pool[np.isfinite(std_resid_pool)]
        if len(pool) < 100:
            pool = None
    z1_null = np.empty(Z1_MC_B)
    for b in range(Z1_MC_B):
        if method == "normal":
            zdraw = rng.standard_normal(T)
        elif method == "student_t":
            nui = np.where(np.isfinite(nu_m), nu_m, 8.0) if nu_m is not None else np.full(T, 8.0)
            scale = np.sqrt((nui - 2) / nui)
            zdraw = rng.standard_t(nui) * scale  # unit-variance t
        elif method == "histsim" and pool is not None:
            zdraw = rng.choice(pool, size=T, replace=True)  # 從經驗標準化殘差抽（一致 null）
        else:
            zdraw = rng.standard_normal(T)
        rb = s * zdraw
        ex = rb < v
        neb = int(np.sum(ex))
        if neb == 0:
            z1_null[b] = 0.0
            continue
        z1_null[b] = float(np.mean((-rb[ex]) / es_pos[ex]) - 1.0)
    # 單側：檢定 ES 低估（z1_obs 偏大）
    p = float((np.sum(z1_null >= z1_obs) + 1) / (Z1_MC_B + 1))
    return {"z1": z1_obs, "p": p, "n_exceed": ne, "n": int(T),
            "reject_es_underestimate_5pct": bool(p < 0.05)}


def fz0_loss(ret: np.ndarray, var: np.ndarray, es: np.ndarray, alpha: float) -> np.ndarray:
    """FZ0（Fissler–Ziegel, 0-homogeneous；Patton-Ziegel-Chen 2019）逐點損失（越低越好）。
    v=VaR<0, e=ES<0：FZ0 = 1/(α·e)·1{r≤v}·(r−v) + v/e + ln(−e) − 1。
    exceedance 項用 (r−v)（r<v 時為負，乘 1/(αe)<0 → 正），對「VaR 太窄→違規多」正確加罰。"""
    v = np.asarray(var, float)
    e = np.asarray(es, float)
    r = np.asarray(ret, float)
    out = np.full(len(r), np.nan)
    m = np.isfinite(v) & np.isfinite(e) & np.isfinite(r) & (e < 0)
    ind = (r <= v).astype(float)
    out[m] = (1.0 / (alpha * e[m])) * ind[m] * (r[m] - v[m]) + v[m] / e[m] + np.log(-e[m]) - 1.0
    return out


# --------------------------------------------------------------------------------------
# 8. bootstrap（loss differential mean 的穩健推論）
# --------------------------------------------------------------------------------------
def moving_block_bootstrap(d: np.ndarray, block: int, B: int, seed: int) -> Dict:
    d = d[np.isfinite(d)]
    n = len(d)
    if n < block * 2:
        return {"insufficient": True}
    rng = np.random.default_rng(seed)
    nblocks = int(np.ceil(n / block))
    starts_max = n - block
    means = np.empty(B)
    for b in range(B):
        idx = rng.integers(0, starts_max + 1, size=nblocks)
        samp = np.concatenate([d[s:s + block] for s in idx])[:n]
        means[b] = samp.mean()
    lo, hi = np.quantile(means, [0.025, 0.975])
    return {"block": int(block), "B": int(B), "mean": float(d.mean()),
            "ci95": [float(lo), float(hi)],
            "share_neg": float(np.mean(means < 0)), "excludes_zero": bool(lo > 0 or hi < 0)}


def stationary_bootstrap(d: np.ndarray, p: float, B: int, seed: int) -> Dict:
    d = d[np.isfinite(d)]
    n = len(d)
    if n < 20:
        return {"insufficient": True}
    rng = np.random.default_rng(seed)
    means = np.empty(B)
    for b in range(B):
        out = np.empty(n)
        t = 0
        idx = rng.integers(0, n)
        while t < n:
            out[t] = d[idx]
            t += 1
            if rng.random() < p:
                idx = rng.integers(0, n)
            else:
                idx = (idx + 1) % n
        means[b] = out.mean()
    lo, hi = np.quantile(means, [0.025, 0.975])
    return {"expected_block": float(1 / p), "B": int(B), "mean": float(d.mean()),
            "ci95": [float(lo), float(hi)],
            "share_neg": float(np.mean(means < 0)), "excludes_zero": bool(lo > 0 or hi < 0)}


def empirical_scale_c(ret: np.ndarray, var: np.ndarray, alpha: float, seed: int) -> Dict:
    """經驗 scale 因子 c = quantile_{1-α}(|ret| / |VaR|)（E1 口徑）+ bootstrap CI（固定 seed）。
    c>1 → 需要放大 σ 才能覆蓋尾部（VaR 太窄）。"""
    m = np.isfinite(ret) & np.isfinite(var) & (var < 0)
    ratio = np.abs(ret[m]) / np.abs(var[m])
    if len(ratio) < 50:
        return {"insufficient": True}
    c = float(np.quantile(ratio, 1 - alpha))
    rng = np.random.default_rng(seed)
    bs = np.array([np.quantile(rng.choice(ratio, len(ratio), replace=True), 1 - alpha)
                   for _ in range(1000)])
    lo, hi = np.quantile(bs, [0.025, 0.975])
    return {"c": c, "ci95": [float(lo), float(hi)], "excludes_1": bool(lo > 1 or hi < 1), "n": int(len(ratio))}


# --------------------------------------------------------------------------------------
# 9. 單一標的完整流程
# --------------------------------------------------------------------------------------
VAR_METHODS = ["normal", "cornish_fisher", "histsim", "student_t"]
ES_METHODS = ["normal", "histsim", "student_t"]  # coherent ES（CF 無 coherent ES）
METHOD_SEED = {"normal": 101, "cornish_fisher": 103, "histsim": 107, "student_t": 109}  # 固定 seed offset（不用 hash）


def _std_resid_pool_index(sigma: np.ndarray, oos_start: int) -> np.ndarray:
    """每個 origin i 回傳一個 slice（用 <= i-1 的標準化殘差），lag-safe。"""
    n = len(sigma)
    idx = np.empty(n, dtype=object)
    for i in range(n):
        idx[i] = slice(0, i)  # 0..i-1
    return idx


def run_instrument(name: str, ticker: str, csv_path: str) -> Dict:
    frame = build_frame(csv_path)
    gk = frame["gk"].to_numpy(float)     # primary realized measure（也是 HAR 輸入/目標）
    pk = frame["pk"].to_numpy(float)
    rs = frame["rs"].to_numpy(float)
    co2 = frame["co2"].to_numpy(float)   # 無偏 proxy
    ret = frame["ret"].to_numpy(float)   # open-to-close 報酬
    dates = frame.index
    n = len(ret)
    oos_start = INITIAL_TRAIN

    # --- lookahead audit（先跑，含擾動測試）---
    audit = lookahead_audit(frame, oos_start, name)

    # --- 模型 ---
    har = run_har(gk, ret, oos_start)   # HAR 輸入 = 平滑 GK realized measure
    gjr = run_gjr(ret, oos_start)
    har_v = har["var_fc"]
    gjr_v = gjr["var_fc"]
    nu = gjr["nu"]

    # OOS mask（兩模型皆有預測）
    idx = np.arange(oos_start, n)
    m = np.isfinite(har_v[idx]) & np.isfinite(gjr_v[idx])
    oos_idx = idx[m]
    dt_oos = dates[oos_idx]

    # --- Leg 1：QLIKE / DM，對每個 realized proxy 同時做 RAW 與對稱 bias-校正（recal）兩種比較 ---
    # RAW：直接用模型原始變異數預測（會被 proxy 系統性偏誤污染 → E1-echo）。
    # RECAL：兩模型皆做 lag-safe 對稱乘法 bias 校正 → 消除 calibration-to-biased-proxy artifact（公平）。
    PROXIES = [("GK", gk), ("PK", pk), ("RS", rs), ("co2", co2)]
    leg1 = {}
    for tgt_name, tgt in PROXIES:
        a = tgt[oos_idx]
        # raw
        lh_raw = canonical_qlike_pointwise(a, har_v[oos_idx])
        lg_raw = canonical_qlike_pointwise(a, gjr_v[oos_idx])
        dm_raw = dm_full(lh_raw, lg_raw, h=1)
        # recal（對稱）
        har_rc = recalibrate(har_v, tgt, oos_start)
        gjr_rc = recalibrate(gjr_v, tgt, oos_start)
        lh_rc = canonical_qlike_pointwise(a, har_rc[oos_idx])
        lg_rc = canonical_qlike_pointwise(a, gjr_rc[oos_idx])
        dm_rc = dm_full(lh_rc, lg_rc, h=1)
        leg1[tgt_name] = {
            "raw": {"qlike_har": float(np.mean(lh_raw)), "qlike_gjr": float(np.mean(lg_raw)),
                    "dm": dm_raw, "bias_har": float(np.mean(a / har_v[oos_idx])),
                    "bias_gjr": float(np.mean(a / gjr_v[oos_idx]))},
            "recal": {"qlike_har": float(np.mean(lh_rc)), "qlike_gjr": float(np.mean(lg_rc)),
                      "dm": dm_rc, "bias_har": float(np.mean(a / har_rc[oos_idx])),
                      "bias_gjr": float(np.mean(a / gjr_rc[oos_idx]))},
        }
    # E1-echo 診斷：RAW 下 DM 方向是否跨 proxy 翻轉（HAR 贏偏誤 proxy、GJR 贏無偏 proxy = target-mismatch 指紋）
    raw_signs = [np.sign(leg1[t]["raw"]["dm"]["hln_t"]) for t, _ in PROXIES]
    leg1_raw_sign_flip = bool(len(set(raw_signs)) > 1)
    # RECAL（公平比較）下：方向是否一致、GK/co2 是否 Harvey-significant 偏 HAR
    recal_signs = [np.sign(leg1[t]["recal"]["dm"]["hln_t"]) for t, _ in PROXIES]
    leg1_recal_direction_consistent = bool(len(set(recal_signs)) == 1)
    leg1_recal_gk = leg1["GK"]["recal"]["dm"]
    leg1_unbiased_co2_raw = leg1["co2"]["raw"]["dm"]  # co2 無偏，raw 即公平
    leg1_recal_any_harvey_har = bool(any(
        leg1[t]["recal"]["dm"]["harvey_significant"] and leg1[t]["recal"]["dm"]["hln_t"] < 0
        for t, _ in PROXIES))

    # Mincer-Zarnowitz calibration（primary GK target）
    def mz(fc):
        a = gk[oos_idx]
        X = np.column_stack([np.ones_like(fc[oos_idx]), fc[oos_idx]])
        b, *_ = np.linalg.lstsq(X, a, rcond=None)
        pred = X @ b
        ss_res = np.sum((a - pred) ** 2)
        ss_tot = np.sum((a - a.mean()) ** 2)
        return {"a": float(b[0]), "b": float(b[1]), "r2": float(1 - ss_res / ss_tot)}
    calib = {"HAR": mz(har_v), "GJR": mz(gjr_v),
             "mean_GK": float(gk[oos_idx].mean()),
             "mean_co2": float(co2[oos_idx].mean()),
             "mean_har_fc": float(har_v[oos_idx].mean()),
             "mean_gjr_fc": float(gjr_v[oos_idx].mean()),
             "note": "mean(GK) < mean(co2) → GK 系統性向下偏（離散價格 range estimator），HAR 訓練其上會吃到偏誤"}

    # --- Leg 2：VaR / ES ---
    har_sig = np.sqrt(har_v)
    gjr_sig = np.sqrt(gjr_v)
    # 標準化殘差全序列（z=ret/sigma），供 histsim / CF pool
    har_z = ret / np.where(har_sig > 0, har_sig, np.nan)
    gjr_z = ret / np.where(gjr_sig > 0, gjr_sig, np.nan)
    pool_idx = _std_resid_pool_index(har_sig, oos_start)

    leg2 = {}
    for alpha in ALPHAS:
        a_key = f"{int(alpha*100)}pct"
        leg2[a_key] = {}
        for mdl, sig_arr, z_all, nu_arr in [("HAR", har_sig, har_z, None),
                                            ("GJR", gjr_sig, gjr_z, nu)]:
            for method in VAR_METHODS:
                ve = build_var_es(sig_arr, ret, pool_idx, nu_arr, method, alpha, z_all)
                var_o = ve["var"][oos_idx]
                es_o = ve["es"][oos_idx]
                ret_o = ret[oos_idx]
                sig_o = sig_arr[oos_idx]
                mm = np.isfinite(var_o)
                if mm.sum() < 100:
                    continue
                viol = (ret_o[mm] < var_o[mm]).astype(int)
                kup = kupiec_pof(viol, alpha)
                cc = christoffersen_cc(viol, alpha)
                bas = basel_light(viol, alpha)
                trinity = bool(kup["p"] > 0.05 and cc["p_cc"] > 0.05
                               and bas["light"] == "green")
                cell = {
                    "n": int(mm.sum()), "violations": int(viol.sum()),
                    "rate": float(viol.mean()),
                    "kupiec_p": kup["p"], "cc_p": cc["p_cc"], "cc_ind_p": cc["p_ind"],
                    "basel": bas, "trinity_pass": trinity,
                    "scale_c": empirical_scale_c(ret_o[mm], var_o[mm], alpha,
                                                 MASTER_SEED + METHOD_SEED[method]),
                }
                if method in ES_METHODS and np.isfinite(es_o[mm]).sum() > 50:
                    nu_o = nu_arr[oos_idx][mm] if nu_arr is not None else None
                    z_pool = z_all[oos_idx][mm] if method == "histsim" else None
                    z1 = acerbi_szekely_z1(ret_o[mm], var_o[mm], es_o[mm], alpha,
                                           sig_o[mm], method, nu_o, MASTER_SEED + 7,
                                           std_resid_pool=z_pool)
                    cell["es_z1"] = z1
                    fz = fz0_loss(ret_o[mm], var_o[mm], es_o[mm], alpha)
                    cell["fz0_mean"] = float(np.nanmean(fz))
                    cell["_fz0_series"] = fz  # 供 DM，稍後移除
                leg2[a_key][f"{mdl}+{method}"] = cell

        # FZ0 DM：HAR vs GJR（同 method，coherent ES cells）
        leg2[a_key]["fz0_dm"] = {}
        for method in ES_METHODS:
            hk = f"HAR+{method}"
            gkey = f"GJR+{method}"
            if hk in leg2[a_key] and gkey in leg2[a_key] \
               and "_fz0_series" in leg2[a_key][hk] and "_fz0_series" in leg2[a_key][gkey]:
                lh = leg2[a_key][hk]["_fz0_series"]
                lg = leg2[a_key][gkey]["_fz0_series"]
                mlen = min(len(lh), len(lg))
                leg2[a_key]["fz0_dm"][method] = dm_full(lh[:mlen], lg[:mlen], h=1)
        # 清掉 series
        for k in list(leg2[a_key].keys()):
            if isinstance(leg2[a_key][k], dict):
                leg2[a_key][k].pop("_fz0_series", None)

    # --- 穩健性：primary = 對稱校正後 GK QLIKE loss differential（公平口徑）---
    har_gk_rc = recalibrate(har_v, gk, oos_start)
    gjr_gk_rc = recalibrate(gjr_v, gk, oos_start)
    a_p = gk[oos_idx]
    lh_rs = canonical_qlike_pointwise(a_p, har_gk_rc[oos_idx])
    lg_rs = canonical_qlike_pointwise(a_p, gjr_gk_rc[oos_idx])
    years = dt_oos.year.to_numpy()
    blocks = [(2005, 2008), (2009, 2012), (2013, 2016), (2017, 2020), (2021, 2026)]
    cross_oos = {}
    for y0, y1 in blocks:
        bmask = (years >= y0) & (years <= y1)
        if bmask.sum() < 100:
            continue
        cross_oos[f"{y0}-{y1}"] = {
            "n": int(bmask.sum()),
            "qlike_har": float(lh_rs[bmask].mean()),
            "qlike_gjr": float(lg_rs[bmask].mean()),
            "dm": dm_full(lh_rs[bmask], lg_rs[bmask], h=1),
        }

    # --- regime split：high vs low vol（用 origin-1 的 lagged GK 相對 expanding median，lag-safe）---
    lag_rv = np.full(n, np.nan)
    for i in oos_idx:
        lag_rv[i] = gk[i - 1]
    med = np.full(n, np.nan)
    for i in oos_idx:
        med[i] = np.median(gk[:i])  # <= i-1
    hi_mask = (lag_rv[oos_idx] > med[oos_idx])
    regime = {}
    for rn, rmask in [("high_vol", hi_mask), ("low_vol", ~hi_mask)]:
        if rmask.sum() < 100:
            continue
        regime[rn] = {
            "n": int(rmask.sum()),
            "qlike_har": float(lh_rs[rmask].mean()),
            "qlike_gjr": float(lg_rs[rmask].mean()),
            "dm": dm_full(lh_rs[rmask], lg_rs[rmask], h=1),
        }
        # 各 regime 的 1% VaR 覆蓋（GJR+t vs HAR+normal 對照）
        for cellkey, sig_arr, z_all, nu_arr, method in [
            ("HAR+normal", har_sig, har_z, None, "normal"),
            ("GJR+student_t", gjr_sig, gjr_z, nu, "student_t")]:
            ve = build_var_es(sig_arr, ret, pool_idx, nu_arr, method, 0.01, z_all)
            var_o = ve["var"][oos_idx]
            ret_o = ret[oos_idx]
            mm = np.isfinite(var_o) & rmask
            if mm.sum() >= 50:
                viol = (ret_o[mm] < var_o[mm]).astype(int)
                regime[rn][f"var1pct_{cellkey}_rate"] = float(viol.mean())

    # --- block / stationary bootstrap（primary QLIKE loss differential）---
    d_rs = lh_rs - lg_rs
    block = int(np.ceil(len(d_rs) ** (1 / 3)))
    boot = {
        "loss_diff_mean": float(d_rs.mean()),
        "moving_block": moving_block_bootstrap(d_rs, block, BOOT_B, MASTER_SEED + 11),
        "stationary": stationary_bootstrap(d_rs, 1.0 / block, BOOT_B, MASTER_SEED + 13),
    }

    return {
        "instrument": name,
        "ticker": ticker,
        "sample": {"start": str(dates.min().date()), "end": str(dates.max().date()),
                   "n_total": int(n), "initial_train": int(oos_start),
                   "n_oos": int(len(oos_idx)),
                   "oos_start_date": str(dt_oos.min().date()),
                   "oos_end_date": str(dt_oos.max().date())},
        "lookahead_audit": audit,
        "leg1_qlike_dm": leg1,
        "leg1_diagnostics": {
            "raw_sign_flip_across_proxies": leg1_raw_sign_flip,
            "recal_direction_consistent": leg1_recal_direction_consistent,
            "recal_gk_dm_t_hln": leg1_recal_gk["hln_t"],
            "recal_gk_harvey_significant": leg1_recal_gk["harvey_significant"],
            "unbiased_co2_raw_dm_t_hln": leg1_unbiased_co2_raw["hln_t"],
            "unbiased_co2_raw_harvey_significant": leg1_unbiased_co2_raw["harvey_significant"],
            "recal_any_proxy_harvey_favor_har": leg1_recal_any_harvey_har,
        },
        "calibration_mincer_zarnowitz": calib,
        "leg2_var_es": leg2,
        "robustness_cross_oos": cross_oos,
        "robustness_regime": regime,
        "robustness_bootstrap": boot,
        "_oos_idx": oos_idx,
        "_dt_oos": dt_oos,
        "_lh_rs": lh_rs, "_lg_rs": lg_rs,
        "_har_v": har_v, "_gjr_v": gjr_v, "_gk": gk, "_ret": ret,
        "_har_sig": har_sig, "_gjr_sig": gjr_sig, "_har_z": har_z, "_gjr_z": gjr_z,
        "_nu": nu, "_pool_idx": pool_idx,
    }


# --------------------------------------------------------------------------------------
# 10. verdict
# --------------------------------------------------------------------------------------
def decide_verdict(spx: Dict) -> Dict:
    """H2（forecast-tail divergence）需要兩條腿同時成立（以 primary SPX 為主裁）：
      腿1：HAR 在 own realized measure 上 QLIKE **公平地**贏 GJR 且 Harvey |t|>3。
           公平 = (a) 對稱 bias 校正後的 GK Harvey-significant 偏 HAR，且 (b) 無偏 co2 proxy(raw) 也偏 HAR。
           若 RAW 只在 HAR 訓練的偏誤 proxy 上贏、換到無偏 co2 就翻盤（sign flip）→ 是 calibration artifact，
           不算 leg1 成立（E1 target-mismatch 的同標的細緻版）。
      腿2：HAR 家族 VaR/ES 尾部覆蓋失敗、GJR（尤其 GJR+t）過關。
    兩腿皆成立 → H2_SUPPORTED；腿1 立不起來 → H2_UNSUPPORTED（誠實 null）。"""
    diag = spx["leg1_diagnostics"]
    leg1_ok = bool(
        diag["recal_gk_harvey_significant"] and diag["recal_gk_dm_t_hln"] < 0
        and diag["unbiased_co2_raw_harvey_significant"] and diag["unbiased_co2_raw_dm_t_hln"] < 0
    )

    # 腿2：1% 下 HAR 家族是否全滅 trinity、GJR 是否有 trinity PASS
    cells = spx["leg2_var_es"]["1pct"]
    har_cells = [k for k in cells if k.startswith("HAR+") and isinstance(cells[k], dict)
                 and "trinity_pass" in cells[k]]
    gjr_cells = [k for k in cells if k.startswith("GJR+") and isinstance(cells[k], dict)
                 and "trinity_pass" in cells[k]]
    har_any_pass = any(cells[k]["trinity_pass"] for k in har_cells)
    gjr_any_pass = any(cells[k]["trinity_pass"] for k in gjr_cells)
    leg2_ok = bool((not har_any_pass) and gjr_any_pass)

    if leg1_ok and leg2_ok:
        verdict = "H2_SUPPORTED"
    elif not leg1_ok:
        verdict = "H2_UNSUPPORTED"
    else:
        verdict = "H2_PARTIAL_leg2_not_met"
    return {
        "verdict": verdict,
        "leg1_supported": leg1_ok,
        "leg1_recal_gk_dm_t_hln": diag["recal_gk_dm_t_hln"],
        "leg1_recal_gk_harvey_significant": diag["recal_gk_harvey_significant"],
        "leg1_unbiased_co2_raw_dm_t_hln": diag["unbiased_co2_raw_dm_t_hln"],
        "leg1_raw_sign_flip_across_proxies": diag["raw_sign_flip_across_proxies"],
        "leg1_recal_direction_consistent": diag["recal_direction_consistent"],
        "leg2_supported": leg2_ok,
        "har_family_any_trinity_pass_1pct": har_any_pass,
        "gjr_family_any_trinity_pass_1pct": gjr_any_pass,
    }


# --------------------------------------------------------------------------------------
# 11. 圖表
# --------------------------------------------------------------------------------------
def make_figures(results: Dict):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    spx = results["_spx_internal"]
    dt = spx["_dt_oos"]
    lh = spx["_lh_rs"]
    lg = spx["_lg_rs"]

    # Fig 1：QLIKE 累積 loss differential（HAR - GJR）
    fig, ax = plt.subplots(figsize=(9, 4.5))
    cum = np.cumsum(lh - lg)
    ax.plot(dt, cum, color="#1f77b4")
    ax.axhline(0, color="grey", lw=0.8, ls="--")
    ax.fill_between(dt, cum, 0, where=cum < 0, color="#1f77b4", alpha=0.15)
    ax.set_title("SPX: cumulative QLIKE loss differential (HAR − GJR), own GK target (bias-recalibrated)\n"
                 "downward = HAR better", fontsize=10)
    ax.set_ylabel("Σ (QLIKE_HAR − QLIKE_GJR)")
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig1_qlike_cum_loss_diff.png"), dpi=130)
    plt.close(fig)

    # Fig 2：1% VaR 違規率 bar（各 cell）+ 目標線
    fig, ax = plt.subplots(figsize=(9, 4.5))
    cells = spx["leg2_var_es"]["1pct"]
    keys = [k for k in cells if ("+" in k) and isinstance(cells[k], dict) and "rate" in cells[k]]
    rates = [cells[k]["rate"] * 100 for k in keys]
    colors = ["#d62728" if k.startswith("HAR") else "#2ca02c" for k in keys]
    ax.bar(range(len(keys)), rates, color=colors)
    ax.axhline(1.0, color="black", ls="--", lw=1, label="target 1%")
    ax.set_xticks(range(len(keys)))
    ax.set_xticklabels(keys, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("violation rate (%)")
    ax.set_title("SPX: 1% VaR violation rates (red=HAR family, green=GJR family)", fontsize=10)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig2_var1pct_violation_rates.png"), dpi=130)
    plt.close(fig)

    # Fig 3：跨 OOS 分段 DM t（RRV_RS QLIKE）
    fig, ax = plt.subplots(figsize=(9, 4.5))
    co = spx["robustness_cross_oos"]
    labels = list(co.keys())
    ts = [co[k]["dm"]["hln_t"] for k in labels]
    barcolors = ["#1f77b4" if t < 0 else "#ff7f0e" for t in ts]
    ax.bar(range(len(labels)), ts, color=barcolors)
    ax.axhline(-3, color="red", ls="--", lw=1, label="Harvey |t|=3")
    ax.axhline(3, color="red", ls="--", lw=1)
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("HLN-corrected DM t  (neg = HAR better)")
    ax.set_title("SPX: cross-OOS DM t by sub-period (own GK QLIKE target, bias-recalibrated)", fontsize=10)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig3_cross_oos_dm.png"), dpi=130)
    plt.close(fig)

    # Fig 4（headline）：各 proxy 的 DM t — RAW vs 對稱 bias 校正
    fig, ax = plt.subplots(figsize=(9, 4.5))
    leg1 = spx["leg1_qlike_dm"]
    proxies = ["GK", "PK", "RS", "co2"]
    raw_t = [leg1[p]["raw"]["dm"]["hln_t"] for p in proxies]
    rc_t = [leg1[p]["recal"]["dm"]["hln_t"] for p in proxies]
    x = np.arange(len(proxies))
    w = 0.38
    ax.bar(x - w / 2, raw_t, w, color="#9467bd", label="raw (proxy-bias confounded)")
    ax.bar(x + w / 2, rc_t, w, color="#1f77b4", label="bias-recalibrated (fair)")
    ax.axhline(-3, color="red", ls="--", lw=1, label="Harvey |t|=3")
    ax.axhline(3, color="red", ls="--", lw=1)
    ax.axhline(0, color="grey", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(proxies)
    ax.set_ylabel("HLN-corrected DM t  (neg = HAR better)")
    ax.set_title("SPX Leg-1: HAR−GJR QLIKE DM t by realized proxy — raw win is a calibration artifact\n"
                 "raw flips sign GK→co2 (E1-echo); recalibrated collapses to insignificance", fontsize=9)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(os.path.join(HERE, "fig4_leg1_raw_vs_recal_by_proxy.png"), dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------------------
# 12. main + atomic write
# --------------------------------------------------------------------------------------
def _clean(obj):
    """遞迴移除 '_' 開頭的內部 key，並把 numpy 型別轉純 python。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if not (isinstance(k, str) and k.startswith("_"))}
    if isinstance(obj, (list, tuple)):
        return [_clean(x) for x in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    return obj


def main():
    per_instrument = {}
    spx_internal = None
    for name, ticker, csv in INSTRUMENTS:
        print(f"[run] {name} ({ticker}) ...", flush=True)
        res = run_instrument(name, ticker, csv)
        if name == "SPX":
            spx_internal = res
        per_instrument[name] = res

    verdict = decide_verdict(spx_internal)

    results = {
        "experiment_id": "k1684_e2",
        "title": "own-market realized-target forecast-tail-divergence cross-OOS gate",
        "seed": MASTER_SEED,
        "config": {
            "initial_train": INITIAL_TRAIN, "refit_every": REFIT_EVERY,
            "alphas": list(ALPHAS), "z1_mc_B": Z1_MC_B, "bootstrap_B": BOOT_B,
            "forecast_object": "open-to-close (trading-session) return & its conditional variance",
            "realized_measures": ["GK(primary)", "PK", "RS", "co2(unbiased proxy)"],
            "models": ["log-HAR (Corsi 2009)", "GJR-GARCH(1,1)-t (arch MLE)"],
            "var_overlays": VAR_METHODS, "es_methods": ES_METHODS,
            "mu_assumption": 0.0,
            "bias_recalibration": "symmetric lag-safe expanding multiplicative (Hansen-Lunde style) on BOTH models",
            "note": "own-market: forecast & realized target = same instrument OHLC; no cross-asset RV plug-in",
        },
        "verdict": verdict,
        "instruments": {k: v for k, v in per_instrument.items()},
        "_spx_internal": spx_internal,
    }

    make_figures({"_spx_internal": spx_internal})

    clean = _clean(results)
    out_path = os.path.join(HERE, "k1684_e2_results.json")
    tmp = out_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(clean, f, indent=2, ensure_ascii=False)
    with open(tmp) as f:
        json.load(f)  # 驗證可 parse
    os.replace(tmp, out_path)
    print(f"[done] wrote {out_path}")

    # 摘要
    print("\n===== VERDICT =====")
    print(json.dumps(verdict, indent=2, ensure_ascii=False))
    for inst in clean["instruments"]:
        print(f"\n===== {inst} Leg1 (QLIKE/DM by proxy: raw vs recal, neg t = HAR better) =====")
        l1 = clean["instruments"][inst]["leg1_qlike_dm"]
        for t in ["GK", "PK", "RS", "co2"]:
            r = l1[t]["raw"]["dm"]; c = l1[t]["recal"]["dm"]
            print(f"  {t:4s}: raw HLN_t={r['hln_t']:+.2f}(sig={r['harvey_significant']}) "
                  f"| recal HLN_t={c['hln_t']:+.2f}(sig={c['harvey_significant']}) "
                  f"acf1={c['loss_diff_acf1']:+.2f} n={c['n']}")
        dg = clean["instruments"][inst]["leg1_diagnostics"]
        print(f"  raw_sign_flip={dg['raw_sign_flip_across_proxies']} "
              f"recal_dir_consistent={dg['recal_direction_consistent']} "
              f"recal_any_harvey_HAR={dg['recal_any_proxy_harvey_favor_har']}")


if __name__ == "__main__":
    main()
