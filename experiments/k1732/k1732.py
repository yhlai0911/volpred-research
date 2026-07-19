"""K1732: TAIEX Cornish-Fisher VaR 分解死亡交叉預警 — 系統性歷史回測（1997-2026）

動機：Lai & Chang (2409-662, accepted) 提出 CF-VaR 分解雙預警架構（β 敏感度 +
IS_k 峰態影響份額的 MA20/MA30 死亡交叉），以 19 指數 × 3 次危機事件研究驗證。
2026-07-17 台股單日 -6.47%，本 K 把同一套訊號放到 TAIEX 全歷史（1997-2026，
約 1,500 週）做「事件定義預先註冊」的系統性回測，回答：
  (1) 訊號對客觀定義的崩跌事件的 ex-ante 命中率與領先期分佈
  (2) 誤報成本（precision、警戒時間占比）
  (3) β 訊號 vs 純波動率趨勢訊號的機械等價性檢查（mechanical vs empirical）
  (4) 2026-07-17 事件的訊號時序（實時案例）

預先註冊的設計決策（跑之前寫死，不看結果調整）：
  - 事件 = 週 log 報酬 <= -5%（primary）/ -4%(robustness)；
    episode onset = 前 13 週內無事件週的第一個事件週
  - 訊號狀態一律取 onset 前一週（t-1，明確 shift，杜絕 lookahead）
  - 論文有效判準：死亡交叉發生於 onset 前 >= 3 週且中間無黃金交叉
  - precision 視窗：死亡交叉後 26 週內出現 onset 算成功
  - 關聯檢定：週頻 2x2（signal active_t vs onset in t+1..t+13），
    circular block bootstrap（block=26, B=2000, seed=42）
論文規格複製：週報酬（W-FRI）、26 週滾動動差、alpha=5%、MA20/MA30。
資料：Yahoo Finance ^TWII（加權指數）。
"""
from __future__ import annotations

import json
import os

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.stats import norm

SEED = 42
ALPHA = 0.05
Z = norm.ppf(ALPHA)  # -1.6449
WINDOW = 26          # 論文 26 週滾動動差
MA_S, MA_L = 20, 30  # 論文 MA20/MA30
CRASH_THR = -0.05    # primary 事件門檻（週 log return）
CRASH_THR_ALT = -0.04
EPISODE_GAP = 13     # 事件週前 13 週無事件 → 新 episode onset
PRECISION_H = 26     # 死亡交叉後 26 週內有 onset 算 precision 成功
ASSOC_H = 13         # 關聯檢定 forward 視窗
BOOT_B = 2000
BLOCK = 26

OUT_DIR = os.path.dirname(os.path.abspath(__file__))


def fetch_weekly() -> pd.Series:
    px = yf.download("^TWII", start="1997-01-01", auto_adjust=True, progress=False)
    if isinstance(px.columns, pd.MultiIndex):
        px.columns = px.columns.get_level_values(0)
    close = px["Close"].dropna()
    assert close.index[-1] >= pd.Timestamp("2026-07-17"), (
        f"yfinance 資料落後（最後日 {close.index[-1].date()}）— 見 error_log 2026-07-15 stale 教訓"
    )
    wclose = close.resample("W-FRI").last().dropna()
    wret = np.log(wclose / wclose.shift(1)).dropna()
    return wret, wclose


def cf_metrics(wret: pd.Series) -> pd.DataFrame:
    """論文 eq(4)(11)(12)(13)(14) 的逐週指標。pandas 樣本偏態 / 超額峰態（bias-corrected）。"""
    sigma = wret.rolling(WINDOW).std()
    skew = wret.rolling(WINDOW).skew()
    exk = wret.rolling(WINDOW).kurt()  # excess kurtosis（= 論文 k_t - 3）
    z_cf = (Z
            + (1 / 6) * (Z ** 2 - 1) * skew
            + (1 / 24) * (Z ** 3 - 3 * Z) * exk
            - (1 / 36) * (2 * Z ** 3 - 5 * Z) * skew ** 2)
    beta_s = -sigma * ((1 / 6) * (Z ** 2 - 1) - (1 / 18) * (2 * Z ** 3 - 5 * Z) * skew)
    beta_k = -sigma * ((1 / 24) * (Z ** 3 - 3 * Z))
    beta_sig = -z_cf
    dvar_s = (beta_s * skew.diff()).abs()
    dvar_k = (beta_k * exk.diff()).abs()
    dvar_sig = (beta_sig * sigma.diff()).abs()
    tot = dvar_s + dvar_k + dvar_sig
    return pd.DataFrame({
        "ret": wret, "sigma": sigma, "skew": skew, "exk": exk,
        "beta_s": beta_s, "beta_k": beta_k, "beta_sig": beta_sig,
        "IS_s": dvar_s / tot, "IS_k": dvar_k / tot, "IS_sig": dvar_sig / tot,
    })


def cross_state(series: pd.Series) -> pd.DataFrame:
    """MA20/MA30 死亡交叉狀態機。active=True 表 MA20<MA30（警戒中）。"""
    m_s = series.rolling(MA_S).mean()
    m_l = series.rolling(MA_L).mean()
    gap = m_s - m_l
    active = ((gap < 0) & gap.notna()).astype(bool)
    # 嚴格交叉定義：前一週 gap 必須為有效非負值（Codex v1 finding 1：
    # warmup 後第一個負 gap 不是交叉，前態未知不得視為 False）
    death = (gap.lt(0) & gap.shift(1).ge(0)).astype(bool)
    golden = (gap.ge(0) & gap.shift(1).lt(0)).astype(bool)
    return pd.DataFrame({"gap": gap, "active": active, "death": death, "golden": golden})


def episodes(wret: pd.Series, thr: float) -> list[pd.Timestamp]:
    """episode 邏輯：與「上一個事件週」（不限 onset）間隔 > EPISODE_GAP 週才算新 onset。"""
    crash = wret[wret <= thr].index
    onsets, last_crash = [], None
    for d in crash:
        if last_crash is None or (d - last_crash).days > EPISODE_GAP * 7:
            onsets.append(d)
        last_crash = d
    return onsets


def weeks_since_last_death(state: pd.DataFrame, t: pd.Timestamp) -> int | None:
    """t（含）之前最近一次 death cross 距 t 的週數；若其後有 golden cross 回傳 None。"""
    idx = state.index
    pos = idx.get_indexer([t])[0]
    if pos < 0:
        return None
    for j in range(pos, -1, -1):
        if bool(state["golden"].iloc[j]) and j != pos:
            return None
        if bool(state["death"].iloc[j]):
            return pos - j
    return None


def evaluate_signal(state: pd.DataFrame, onsets: list[pd.Timestamp], idx: pd.DatetimeIndex,
                    rng: np.random.Generator) -> dict:
    valid = state.dropna(subset=["gap"])
    # --- per-onset ex-ante 評估（t-1 狀態；明確 shift）---
    active_lag = state["active"].shift(1)  # lookahead guard: 只用 onset 前一週資訊
    per_event = []
    for t in onsets:
        if t not in active_lag.index or pd.isna(state.loc[:t, "gap"].iloc[-1]):
            continue
        pos = idx.get_indexer([t])[0]
        if pos == 0:
            continue
        t_prev = idx[pos - 1]
        if pd.isna(state["gap"].loc[t_prev]):  # 訊號 warmup 未完成的 onset 不列入評估
            continue
        is_active = bool(active_lag.loc[t])
        lead = weeks_since_last_death(state, t_prev) if is_active else None
        per_event.append({
            "onset": str(t.date()),
            "active_at_t_minus_1": is_active,
            "lead_weeks": None if lead is None else int(lead + 1),  # +1: cross 至 onset 的週數
            "valid_per_paper": bool(is_active and lead is not None and lead + 1 >= 3),
        })
    n_ev = len(per_event)
    hits = sum(e["active_at_t_minus_1"] for e in per_event)
    valid_hits = sum(e["valid_per_paper"] for e in per_event)
    leads = [e["lead_weeks"] for e in per_event if e["lead_weeks"] is not None]
    # --- 誤報成本 ---
    deaths = valid.index[valid["death"]]
    onset_idx = pd.DatetimeIndex(onsets)
    prec_success = sum(
        bool(((onset_idx > c) & (onset_idx <= c + pd.Timedelta(weeks=PRECISION_H))).any())
        for c in deaths)
    burden = float(valid["active"].mean())
    # --- 週頻關聯 + circular block bootstrap ---
    onset_flag = pd.Series(False, index=idx)
    onset_flag.loc[onset_flag.index.isin(onset_idx)] = True
    fwd = (onset_flag[::-1].rolling(ASSOC_H).max()[::-1].shift(-1)).astype(float)  # onset in t+1..t+13
    df = pd.DataFrame({"active": valid["active"].astype(float), "fwd": fwd}).dropna()
    a, f = df["active"].to_numpy(), df["fwd"].to_numpy()
    n = len(a)

    def cond_diff(av, fv):
        p1 = fv[av == 1].mean() if (av == 1).any() else np.nan
        p0 = fv[av == 0].mean() if (av == 0).any() else np.nan
        return p1 - p0, p1, p0

    diff_obs, p1_obs, p0_obs = cond_diff(a, f)
    boot = []
    n_blocks = int(np.ceil(n / BLOCK))
    for _ in range(BOOT_B):
        starts = rng.integers(0, n, size=n_blocks)
        pos = np.concatenate([(s + np.arange(BLOCK)) % n for s in starts])[:n]
        d, _, _ = cond_diff(a[pos], f[pos])
        boot.append(d)
    boot = np.array([b for b in boot if not np.isnan(b)])
    ci = np.percentile(boot, [2.5, 97.5]).tolist()
    ci99 = np.percentile(boot, [0.5, 99.5]).tolist()
    # 正式檢定（Codex v1 finding 2）：circular-shift randomization null。
    # 隨機旋轉 active 相對 fwd（offset >= ASSOC_H，保留兩序列各自的自相關、破壞對齊），
    # p = (r+1)/(B_perm+1)，單尾 H1: diff > 0。
    B_perm = 5000
    perm_stats = []
    for _ in range(B_perm):
        off = int(rng.integers(ASSOC_H, n - ASSOC_H))
        d_p, _, _ = cond_diff(np.roll(a, off), f)
        if not np.isnan(d_p):
            perm_stats.append(d_p)
    perm_stats = np.array(perm_stats)
    p_perm = float((np.sum(perm_stats >= diff_obs) + 1) / (len(perm_stats) + 1))
    return {
        "n_onsets_evaluable": n_ev,
        "hit_rate_active_at_t_minus_1": round(hits / n_ev, 4) if n_ev else None,
        "hits": hits,
        "valid_per_paper_rate": round(valid_hits / n_ev, 4) if n_ev else None,
        "valid_hits": valid_hits,
        "lead_weeks_median": float(np.median(leads)) if leads else None,
        "lead_weeks_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None,
        "n_death_crosses": int(len(deaths)),
        "precision_26w": round(prec_success / len(deaths), 4) if len(deaths) else None,
        "warning_burden_frac_weeks_active": round(burden, 4),
        "assoc_P_onset13_given_active": round(float(p1_obs), 4),
        "assoc_P_onset13_given_inactive": round(float(p0_obs), 4),
        "assoc_diff": round(float(diff_obs), 4),
        "assoc_diff_ci95_blockboot": [round(c, 4) for c in ci],
        "assoc_diff_ci99_blockboot": [round(c, 4) for c in ci99],
        "assoc_diff_p_circshift_onesided": round(p_perm, 5),
        "assoc_perm_B": B_perm,
        "per_event": per_event,
    }


def main():
    rng = np.random.default_rng(SEED)
    wret, wclose = fetch_weekly()
    m = cf_metrics(wret)
    idx = m.index

    states = {name: cross_state(m[name]) for name in ["beta_s", "beta_k", "IS_k"]}
    # 機械等價 benchmark：純波動率趨勢（MA20(sigma) 上穿 MA30(sigma) = 警戒）
    sig_up = cross_state(-m["sigma"])  # 取負號 → death cross of -sigma == sigma 上升趨勢
    states["sigma_uptrend_benchmark"] = sig_up

    onsets = episodes(wret, CRASH_THR)
    onsets_alt = episodes(wret, CRASH_THR_ALT)

    results = {
        "experiment_id": "k1732",
        "data": {
            "source": "Yahoo Finance ^TWII (auto_adjust)",
            "freq": "weekly W-FRI log returns",
            "period": [str(idx[0].date()), str(idx[-1].date())],
            "n_weeks": int(len(wret)),
            "spec": {"alpha": ALPHA, "moment_window": WINDOW, "ma": [MA_S, MA_L],
                     "moment_estimator": "pandas sample skew / excess kurt (bias-corrected)"},
        },
        "event_definition": {
            "primary_thr_weekly_log_ret": CRASH_THR, "alt_thr": CRASH_THR_ALT,
            "episode_gap_weeks": EPISODE_GAP,
            "n_onsets_primary": len(onsets), "n_onsets_alt": len(onsets_alt),
            "onsets_primary": [str(d.date()) for d in onsets],
        },
        "mechanical_equivalence": {
            "note": ("beta_k = -sigma*(1/24)(z^3-3z) 是 sigma 的線性變換 → beta_k 死亡交叉"
                     "『恆等於』sigma 上升趨勢交叉；beta_s = -sigma*(0.2843+0.0376*skew) 高度近似。"
                     "此為 mechanical 結果：beta 訊號在本質上是波動率趨勢訊號，"
                     "偏態每單位貢獻 ~13% 係數比（樣本內相對調變見 range 欄位）。"
                     "IS_k 才是 higher-moment specific 訊號。"),
            "corr_beta_k_neg_sigma": round(float(m["beta_k"].corr(-m["sigma"])), 6),
            "corr_beta_s_neg_sigma": round(float(m["beta_s"].corr(-m["sigma"])), 4),
            "beta_s_skew_relative_modulation_range": [
                round(float((0.03762 / 0.28430 * m["skew"]).min()), 4),
                round(float((0.03762 / 0.28430 * m["skew"]).max()), 4)],
            "beta_k_crosses_equal_sigma_crosses": bool(
                (states["beta_k"]["death"].fillna(False) == sig_up["death"].fillna(False)).all()),
        },
        "signals": {},
        "case_2026_07_17": {},
        "seed": SEED, "bootstrap": {"B": BOOT_B, "block": BLOCK, "method": "circular block"},
    }

    for name, st in states.items():
        results["signals"][name] = evaluate_signal(st, onsets, idx, rng)
        # robustness: alt threshold（只記 hit rate，全表太長）
        alt = evaluate_signal(st, onsets_alt, idx, np.random.default_rng(SEED + 1))
        results["signals"][name]["alt_thr_hit_rate"] = alt["hit_rate_active_at_t_minus_1"]
        results["signals"][name]["alt_thr_n_onsets"] = alt["n_onsets_evaluable"]

    # 2026-07-17 實時案例
    t_case = pd.Timestamp("2026-07-17")
    for name, st in states.items():
        lead = weeks_since_last_death(st, idx[idx.get_indexer([t_case])[0] - 1])
        last_death = st.index[st["death"].fillna(False)]
        last_death = last_death[last_death <= t_case]
        results["case_2026_07_17"][name] = {
            "active_at_t_minus_1": bool(st["active"].shift(1).loc[t_case]),
            "lead_weeks_at_t_minus_1": None if lead is None else int(lead + 1),
            "last_death_cross": str(last_death[-1].date()) if len(last_death) else None,
        }
    results["case_2026_07_17"]["week_ret"] = round(float(wret.loc[t_case]), 4)
    isk_gap = states["IS_k"]["gap"].loc[:t_case].tail(8)
    results["case_2026_07_17"]["isk_gap_last8"] = {str(d.date()): round(float(v), 6)
                                                   for d, v in isk_gap.items()}

    # Estimator sensitivity（Codex v1 finding 7）：population（bias=True）動差 vs pandas bias-corrected
    from scipy.stats import kurtosis as _ku, skew as _sk
    skew_p = wret.rolling(WINDOW).apply(lambda x: _sk(x, bias=True), raw=True)
    exk_p = wret.rolling(WINDOW).apply(lambda x: _ku(x, bias=True, fisher=True), raw=True)
    sigma_ = m["sigma"]
    beta_s_p = -sigma_ * ((1 / 6) * (Z ** 2 - 1) - (1 / 18) * (2 * Z ** 3 - 5 * Z) * skew_p)
    beta_k_p = -sigma_ * ((1 / 24) * (Z ** 3 - 3 * Z))
    z_cf_p = (Z + (1 / 6) * (Z ** 2 - 1) * skew_p + (1 / 24) * (Z ** 3 - 3 * Z) * exk_p
              - (1 / 36) * (2 * Z ** 3 - 5 * Z) * skew_p ** 2)
    dv_s = (beta_s_p * skew_p.diff()).abs()
    dv_k = (beta_k_p * exk_p.diff()).abs()
    dv_sig = ((-z_cf_p) * sigma_.diff()).abs()
    isk_p = dv_k / (dv_s + dv_k + dv_sig)
    st_p, st_b = cross_state(isk_p), states["IS_k"]
    valid_mask = st_b["gap"].notna() & st_p["gap"].notna()  # 兩套 gap 均有效才比較（排除 warmup）
    both = pd.DataFrame({"a_pandas": st_b["active"], "a_pop": st_p["active"]})[valid_mask]
    d_pandas = set(st_b.index[st_b["death"]].date)
    d_pop = set(st_p.index[st_p["death"]].date)
    results["estimator_sensitivity_ISk"] = {
        "note": "population (bias=True) skew/exkurt 重算 IS_k 訊號 vs 基準 pandas bias-corrected",
        "n_death_crosses_pop": int(st_p["death"].sum()),
        "n_death_crosses_base": int(st_b["death"].sum()),
        "n_cross_dates_differing": len(d_pandas ^ d_pop),
        "n_active_weeks_differing": int((both["a_pandas"] != both["a_pop"]).sum()),
        "n_weeks_compared": int(len(both)),
    }

    tmp = os.path.join(OUT_DIR, "k1732_results.json.tmp")
    final = os.path.join(OUT_DIR, "k1732_results.json")
    with open(tmp, "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=1)
    json.load(open(tmp))  # 驗證可解析後原子替換
    os.replace(tmp, final)

    m.to_csv(os.path.join(OUT_DIR, "k1732_metrics_weekly.csv"))
    wclose.to_csv(os.path.join(OUT_DIR, "k1732_twii_weekly_close.csv"))
    print(json.dumps({k: v for k, v in results.items() if k not in ("signals", "case_2026_07_17")},
                     ensure_ascii=False, indent=1))
    for name in states:
        s = dict(results["signals"][name])
        s.pop("per_event")
        print(f"\n=== {name} ===\n", json.dumps(s, ensure_ascii=False, indent=1))
    print("\n=== case 2026-07-17 ===\n", json.dumps(results["case_2026_07_17"], ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
