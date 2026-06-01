#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1410 — 報酬順序風險（Sequence of Returns Risk, SORR）的真實資料模擬
====================================================================

研究問題
--------
退休「提領期」與累積期最大的不同：累積期是純乘法（無現金流），終值只看
報酬的乘積 → 報酬「順序」不影響結果（乘法可交換律）。但提領期每年從本金
扣一筆固定（通膨調整）提款，提款打破了交換律 → **同一組報酬、不同發生順序，
終值與是否破產可天差地別**。早期遇空頭（低點還被迫賣股提領）= 永久性傷害。

這是 VolPred 理財決策系列的「提領期」缺角，與 K1408「進場時點」（累積期，
結論：時點對長期年化報酬影響小）形成對照。市面同主題文章多用「假設固定
報酬 + 波動」概念講解，少有人用真實市場月報酬資料跑。本實驗用真實資料 +
對策實證排名補上。

方法
----
1. 資料：yfinance 月報酬。
   - ^GSPC（S&P500 指數，1928 起，含大蕭條/二戰/停滯性通膨/2000/2008/2020）
   - ^TWII（台股加權指數，1997 起，含 2000 網路泡沫/2008/2020/2022）
   報酬用 auto_adjust=True 的月底收盤 pct_change（含息總報酬近似）。
2. 退休模擬：起始資產正規化為 1,000（正規化單位，等價於本金=1）。
   30 年期，年初提領，提領金額逐年依通膨（CPI 假設）成長 → 固定「實質」
   提領率。本金不足以支付當年提領即破產（耗盡）。
3. Bootstrap：stationary bootstrap（Politis-Romano 1994），期望 block≈12 月，
   保留波動叢聚與序列相依。固定 seed=20260601，≥10,000 條路徑。另跑 iid
   resample 當 robustness 對照。
4. 核心分析：
   a. 排列示範：取真實連續 N 年年報酬，固定提領下窮舉/抽樣不同順序，
      展示 best/worst/median 終值與耗盡差異。
   b. 退休風險區：在第 k 年（k=1..30）注入一次大跌，計算破產機率 vs 崩盤
      年份曲線 → 證明早期崩盤破壞力遠大於晚期。
   c. 對策實證排名（同資料同 bootstrap，比 30 年不破產成功率）：
      提領率 3.5/4/5%、Bond tent（股債 glide）、動態提領（Guyton-Klinger
      護欄簡化）、延後退休 3 年。按成功率改善排名。
5. 誠實：成功率報 Wilson CI；不過度宣稱；對策若不如預期如實寫。所有隨機
   程序固定 seed；bootstrap 為純歷史 resample，無 lookahead（路徑生成不
   使用未來資訊，提領決策只用當期/過去淨值）。

用法
----
    uv run python experiments/k1410/k1410.py            # 用 cache 離線跑
    uv run python experiments/k1410/k1410.py --refresh  # 重新抓 yfinance
"""
import os
import json
import argparse
import itertools
from datetime import datetime, timezone

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for _f in ["Arial Unicode MS", "PingFang TC", "Heiti TC", "Hiragino Sans GB"]:
    try:
        font_manager.findfont(_f, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [_f]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(HERE, "data")
FIG_DIR = os.path.join(HERE, "figures")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(FIG_DIR, exist_ok=True)

SEED = 20260601
N_SIM = 10000
HORIZON_Y = 30                 # 退休期 30 年
MEAN_BLOCK_M = 12              # stationary bootstrap 期望 block（月）
INIT_WEALTH = 1000.0           # 起始資產（正規化）
CPI = 0.02                     # 通膨假設（年），提領金額逐年成長以維持實質購買力
BASE_WR = 0.04                 # 基準提領率（佔起始資產，年初提）

# Bond / 防禦資產 proxy：用長債總報酬長期經驗值近似（避免再抓一條不同期間/
# 缺漏的債券序列造成對齊問題）。實質報酬低、波動小、與股市低相關。這是模型
# 假設，README/results 明記。
BOND_MEAN_M = 0.04 / 12.0      # 年化名目 ~4%
BOND_VOL_M = 0.05 / np.sqrt(12)  # 年化波動 ~5%

TICKERS = {"GSPC": "^GSPC", "TWII": "^TWII"}


# ---------------------------------------------------------------------------
# 1. 資料
# ---------------------------------------------------------------------------
def fetch(name, symbol, refresh=False):
    path = os.path.join(DATA_DIR, f"{name}.csv")
    if (not refresh) and os.path.exists(path):
        px = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")["Close"]
        return px
    import yfinance as yf
    h = yf.Ticker(symbol).history(period="max", auto_adjust=True)
    if h is None or h.empty:
        raise RuntimeError(f"{symbol}: empty from yfinance")
    px = h["Close"].copy()
    px.index = pd.to_datetime(px.index).tz_localize(None)
    px = px[~px.index.duplicated(keep="last")].sort_index()
    px.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(path, index=False)
    return px


def monthly_returns(px):
    """Resample 至月末取最後成交價、pct_change。**排除未完成的尾端月**
    （若資料最後一筆觀察落在當前日曆月，視為 partial-month → 剔除），
    避免把不完整月當成整月報酬污染統計。
    Codex review 2026-06-01 catch：原版把 TWII 2026-06-01 單日當 6 月月末。"""
    m = px.resample("ME").last()
    if len(m) >= 1:
        last_obs = px.index.max()
        today = pd.Timestamp.today().normalize()
        # 若最後觀察在當前日曆月內 → partial → 剔最後一個 resampled month
        if (last_obs.year == today.year) and (last_obs.month == today.month):
            m = m.iloc[:-1]
    return m.pct_change().dropna()


# ---------------------------------------------------------------------------
# 2. Bootstrap path generators
# ---------------------------------------------------------------------------
def stationary_bootstrap_paths(returns, n_paths, n_months, mean_block, rng):
    """Politis-Romano stationary bootstrap。回傳 (n_paths, n_months) 月報酬矩陣。
    每步以機率 p=1/mean_block 重新隨機選新起點，否則沿歷史序列 +1（wrap）。
    保留可變長度序列相依區塊。無 lookahead：路徑僅由歷史 returns resample。"""
    r = np.asarray(returns, dtype=float)
    n = len(r)
    p = 1.0 / mean_block
    out = np.empty((n_paths, n_months), dtype=float)
    idx = rng.integers(0, n, size=n_paths)
    for j in range(n_months):
        out[:, j] = r[idx]
        jump = rng.random(n_paths) < p
        idx = np.where(jump, rng.integers(0, n, size=n_paths), (idx + 1) % n)
    return out


def iid_bootstrap_paths(returns, n_paths, n_months, rng):
    r = np.asarray(returns, dtype=float)
    return rng.choice(r, size=(n_paths, n_months), replace=True)


# ---------------------------------------------------------------------------
# 3. 退休提領模擬核心
# ---------------------------------------------------------------------------
def simulate_depletion(equity_paths, bond_paths, equity_weight_schedule,
                       init_wealth, base_wr, cpi, horizon_y,
                       dynamic=False, guard_band=0.20, cut=0.10, raise_=0.10):
    """年初提領模型。equity_paths/bond_paths: (n_paths, horizon_y*12) 月報酬。
    equity_weight_schedule: 長度 horizon_y 的每年股票權重（其餘為債）。
    回傳 success / final_wealth / depletion_year。

    dynamic=True → Guyton-Klinger 護欄簡化版（真正 path-dependent）：維護 per-path
    的「目前提領水準」cur_level（首年=init_wealth*base_wr）。每年先把 cur_level 依
    CPI 成長一次（生活費通膨調整），再檢查當期實際提領率 = cur_level/當期淨值：
    > 初始提領率*(1+band) → cur_level 永久 cut（-10%）；< 初始*(1-band) → raise
    （+10%）。調整會**延續到後續年度**（不重設回 CPI 基線），這才是 GK 護欄的
    path-dependent 本質。決策只用當期淨值（無 lookahead）。"""
    n_paths = equity_paths.shape[0]
    wealth = np.full(n_paths, float(init_wealth))
    alive = np.ones(n_paths, dtype=bool)
    depletion_year = np.full(n_paths, horizon_y + 1, dtype=int)  # 未破產=31
    base_withdraw = init_wealth * base_wr
    cur_level = np.full(n_paths, base_withdraw)  # 動態：per-path 延續的提領水準

    for y in range(horizon_y):
        infl = (1.0 + cpi) ** y
        if dynamic:
            # 先依 CPI 成長一次（首年 y=0 不成長），再套護欄調整 cur_level
            if y > 0:
                cur_level = cur_level * (1.0 + cpi)
            with np.errstate(divide="ignore", invalid="ignore"):
                cur_rate = np.where(wealth > 0, cur_level / wealth, np.inf)
            hi = cur_rate > base_wr * (1.0 + guard_band)
            lo = cur_rate < base_wr * (1.0 - guard_band)
            cur_level = np.where(hi & alive, cur_level * (1.0 - cut), cur_level)
            cur_level = np.where(lo & alive, cur_level * (1.0 + raise_), cur_level)
            withdraw = cur_level.copy()
        else:
            withdraw = np.full(n_paths, base_withdraw * infl, dtype=float)

        wealth = np.where(alive, wealth - withdraw, wealth)
        newly_dead = alive & (wealth <= 0)
        depletion_year = np.where(newly_dead, y + 1, depletion_year)
        wealth = np.where(wealth < 0, 0.0, wealth)
        alive = alive & (wealth > 0)

        ew = equity_weight_schedule[y]
        bw = 1.0 - ew
        m0 = y * 12
        port_m = ew * equity_paths[:, m0:m0 + 12] + bw * bond_paths[:, m0:m0 + 12]
        growth = np.prod(1.0 + port_m, axis=1)
        wealth = np.where(alive, wealth * growth, wealth)

    return {"success": alive & (wealth > 0), "final_wealth": wealth,
            "depletion_year": depletion_year}


def _simulate_per_path_init(equity_paths, bond_paths, eq_w, init_wealth_per_path,
                            base_wr, cpi, horizon_y):
    """同 simulate_depletion 但 init_wealth 為 per-path 陣列（用於延後退休：
    提領基準額用 per-path 起始資產 * base_wr）。"""
    n_paths = equity_paths.shape[0]
    wealth = np.array(init_wealth_per_path, dtype=float).copy()
    alive = np.ones(n_paths, dtype=bool)
    depletion_year = np.full(n_paths, horizon_y + 1, dtype=int)
    base_withdraw = np.array(init_wealth_per_path, dtype=float) * base_wr

    for y in range(horizon_y):
        infl = (1.0 + cpi) ** y
        withdraw = base_withdraw * infl
        wealth = np.where(alive, wealth - withdraw, wealth)
        newly_dead = alive & (wealth <= 0)
        depletion_year = np.where(newly_dead, y + 1, depletion_year)
        wealth = np.where(wealth < 0, 0.0, wealth)
        alive = alive & (wealth > 0)
        ew = eq_w[y]
        bw = 1.0 - ew
        m0 = y * 12
        port_m = ew * equity_paths[:, m0:m0 + 12] + bw * bond_paths[:, m0:m0 + 12]
        growth = np.prod(1.0 + port_m, axis=1)
        wealth = np.where(alive, wealth * growth, wealth)

    return {"success": alive & (wealth > 0), "final_wealth": wealth,
            "depletion_year": depletion_year}


def wilson_ci(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    phat = k / n
    denom = 1 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = (z * np.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))


# ---------------------------------------------------------------------------
# 4a. 排列示範（同一組報酬不同順序）
# ---------------------------------------------------------------------------
def permutation_demo(returns, label, init_wealth, base_wr, cpi, n_years, rng,
                     n_sample_perm=20000):
    """取真實連續 n_years 年的年報酬（由月報酬複利成年報酬），固定提領下
    枚舉/抽樣不同順序，回傳 best/worst/median 終值與耗盡情況。"""
    r = np.asarray(returns, dtype=float)
    n_full = (len(r) // 12) * 12
    yearly = np.prod(1.0 + r[:n_full].reshape(-1, 12), axis=1) - 1.0
    basket = yearly[-n_years:]

    def terminal(order):
        w = float(init_wealth)
        dep = None
        for y, idx in enumerate(order):
            wd = init_wealth * base_wr * (1.0 + cpi) ** y
            w -= wd
            if w <= 0:
                return 0.0, y + 1
            w *= (1.0 + basket[idx])
        return w, dep

    n = len(basket)
    perms = []
    if n <= 8:
        all_perms = list(itertools.permutations(range(n)))
        for o in all_perms:
            tv, dep = terminal(o)
            perms.append((tv, dep, o))
        mode, n_eval = "exhaustive", len(all_perms)
    else:
        seen = set()
        for _ in range(n_sample_perm):
            o = tuple(rng.permutation(n))
            if o in seen:
                continue
            seen.add(o)
            tv, dep = terminal(o)
            perms.append((tv, dep, o))
        mode, n_eval = "sampled", len(perms)

    tvs = np.array([p[0] for p in perms])
    deps = [p[1] for p in perms]
    n_deplete = sum(1 for d in deps if d is not None)
    best = max(perms, key=lambda x: x[0])
    worst = min(perms, key=lambda x: x[0])
    # 乘積（順序無關，驗證「乘積相同」）
    basket_product = float(np.prod(1.0 + basket))
    return {
        "label": label,
        "basket_returns_pct": [round(float(x) * 100, 2) for x in basket],
        "basket_gross_product_order_invariant": round(basket_product, 4),
        "no_withdrawal_terminal_any_order": round(init_wealth * basket_product, 2),
        "n_years": int(n_years),
        "mode": mode,
        "n_permutations_evaluated": int(n_eval),
        "best_terminal": round(float(best[0]), 2),
        "worst_terminal": round(float(worst[0]), 2),
        "median_terminal": round(float(np.median(tvs)), 2),
        "mean_terminal": round(float(np.mean(tvs)), 2),
        "p5_terminal": round(float(np.percentile(tvs, 5)), 2),
        "p95_terminal": round(float(np.percentile(tvs, 95)), 2),
        "best_to_worst_ratio": round(float(best[0] / worst[0]), 2) if worst[0] > 0 else None,
        "n_orderings_depleted": int(n_deplete),
        "pct_orderings_depleted": round(100.0 * n_deplete / n_eval, 2),
        "init_wealth": init_wealth,
        "base_withdrawal_rate": base_wr,
        "_tvs": tvs,
    }


# ---------------------------------------------------------------------------
# 4b. 退休風險區：崩盤年份 vs 破產機率
# ---------------------------------------------------------------------------
def crash_year_risk(returns, label, init_wealth, base_wr, cpi, horizon_y,
                    crash_size, rng, n_sim=5000):
    """基準路徑用 stationary bootstrap，在第 k 年（k=1..horizon_y）第 1 個月強制
    注入 crash_size 大跌（取代當月報酬），比較不同 k 的破產機率。全程 100% 股
    以凸顯 SORR。"""
    base = stationary_bootstrap_paths(returns, n_sim, horizon_y * 12, MEAN_BLOCK_M, rng)
    eq_w = np.ones(horizon_y)
    bond = np.zeros_like(base)

    curve = []
    for k in range(1, horizon_y + 1):
        paths = base.copy()
        paths[:, (k - 1) * 12] = crash_size
        res = simulate_depletion(paths, bond, eq_w, init_wealth, base_wr, cpi, horizon_y)
        fail = ~res["success"]
        fr = float(fail.mean())
        lo, hi = wilson_ci(int(fail.sum()), n_sim)
        curve.append({"crash_year": k, "fail_prob": round(fr, 4),
                      "ci_lo": round(lo, 4), "ci_hi": round(hi, 4)})

    res0 = simulate_depletion(base, bond, eq_w, init_wealth, base_wr, cpi, horizon_y)
    base_fail = float((~res0["success"]).mean())
    early = np.mean([c["fail_prob"] for c in curve[:5]])
    late = np.mean([c["fail_prob"] for c in curve[-5:]])
    return {
        "label": label,
        "crash_size_monthly": crash_size,
        "n_sim": n_sim,
        "base_fail_prob_no_injected_crash": round(base_fail, 4),
        "curve": curve,
        "early_crash_avg_fail_y1_5": round(float(early), 4),
        "late_crash_avg_fail_y26_30": round(float(late), 4),
        "early_to_late_ratio": round(float(early / late), 2) if late > 0 else None,
    }


# ---------------------------------------------------------------------------
# 4c. 對策實證排名
# ---------------------------------------------------------------------------
def bond_tent_schedule(horizon_y, start_eq=0.60, trough_eq=0.30, recover_eq=0.70,
                       trough_year=5, recover_year=15):
    """Bond tent glide path：退休前後股票權重先降到谷底（提高防禦），再逐步回升
    （後期股票多，用成長對抗長壽風險）。回傳每年股票權重。"""
    w = np.empty(horizon_y)
    for y in range(horizon_y):
        if y <= trough_year:
            w[y] = start_eq + (trough_eq - start_eq) * (y / max(trough_year, 1))
        elif y <= recover_year:
            w[y] = trough_eq + (recover_eq - trough_eq) * ((y - trough_year) / max(recover_year - trough_year, 1))
        else:
            w[y] = recover_eq
    return w


def _simulate_defer(eq_all, bond, eq_w, init_wealth, base_wr, cpi, horizon_y, defer):
    """延後退休 defer 年：前 defer 年繼續投資（不提領，本金成長），退休後提領
    年數少 defer 年（壽命終點不變）。提領基準額用成長後 per-path 起始資產。"""
    h2 = horizon_y - defer
    eq_w_full = np.ones(horizon_y)
    grow = np.prod(1.0 + (eq_w_full[0] * eq_all[:, :defer * 12]
                          + (1 - eq_w_full[0]) * bond[:, :defer * 12]), axis=1)
    iw_path = init_wealth * grow
    eq2 = eq_all[:, defer * 12:]
    bd2 = bond[:, defer * 12:]
    return _simulate_per_path_init(eq2, bd2, eq_w[:h2], iw_path, base_wr, cpi, h2)


def evaluate_strategies(returns, label, init_wealth, cpi, horizon_y, rng):
    eq_all = stationary_bootstrap_paths(returns, N_SIM, horizon_y * 12, MEAN_BLOCK_M, rng)
    # 債：獨立常態 proxy，與股市設 0 相關（保守，不誇大分散效果）
    bond = rng.normal(BOND_MEAN_M, BOND_VOL_M, size=eq_all.shape)

    all_eq_w = np.ones(horizon_y)
    tent_w = bond_tent_schedule(horizon_y)
    static_6040 = np.full(horizon_y, 0.60)

    strategies = {}
    for wr in (0.035, 0.04, 0.05):
        strategies[f"WR{wr*100:.1f}%_100stock"] = simulate_depletion(
            eq_all, bond, all_eq_w, init_wealth, wr, cpi, horizon_y)
    strategies["WR4.0%_static6040"] = simulate_depletion(
        eq_all, bond, static_6040, init_wealth, BASE_WR, cpi, horizon_y)
    strategies["WR4.0%_bond_tent"] = simulate_depletion(
        eq_all, bond, tent_w, init_wealth, BASE_WR, cpi, horizon_y)
    strategies["WR4.0%_dynamic_GK"] = simulate_depletion(
        eq_all, bond, all_eq_w, init_wealth, BASE_WR, cpi, horizon_y, dynamic=True)
    strategies["WR4.0%_defer3y"] = _simulate_defer(
        eq_all, bond, all_eq_w, init_wealth, BASE_WR, cpi, horizon_y, defer=3)

    out = {}
    for name, res in strategies.items():
        succ = res["success"]
        k, n = int(succ.sum()), len(succ)
        lo, hi = wilson_ci(k, n)
        fw = res["final_wealth"]
        dep = res["depletion_year"]
        depleted = dep[dep <= horizon_y]
        out[name] = {
            "success_rate": round(k / n, 4),
            "ci_lo": round(lo, 4),
            "ci_hi": round(hi, 4),
            "median_final_wealth": round(float(np.median(fw)), 2),
            "p5_final_wealth": round(float(np.percentile(fw, 5)), 2),
            "median_depletion_year_if_failed": (round(float(np.median(depleted)), 1)
                                                if len(depleted) else None),
            "n_sim": n,
        }
    return out


# ---------------------------------------------------------------------------
# 5. 圖
# ---------------------------------------------------------------------------
def fig_permutation(demo_gspc, demo_twii):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, demo in zip(axes, [demo_gspc, demo_twii]):
        tvs = demo["_tvs"]
        ax.hist(tvs, bins=60, color="#4C72B0", alpha=0.85)
        ax.axvline(demo["best_terminal"], color="green", lw=2,
                   label=f"最佳順序 {demo['best_terminal']:,.0f}")
        ax.axvline(demo["worst_terminal"], color="red", lw=2,
                   label=f"最差順序 {demo['worst_terminal']:,.0f}")
        ax.axvline(demo["median_terminal"], color="black", lw=1.5, ls="--",
                   label=f"中位數 {demo['median_terminal']:,.0f}")
        ax.axvline(demo["init_wealth"], color="grey", lw=1, ls=":",
                   label=f"起始資產 {demo['init_wealth']:,.0f}")
        ax.set_title(f"{demo['label']}：同籃 {demo['n_years']} 年報酬、不同順序\n"
                     f"({demo['n_permutations_evaluated']:,} 種順序，{demo['pct_orderings_depleted']:.0f}% 破產)")
        ax.set_xlabel("30 年提領後終值（起始=1000）")
        ax.set_ylabel("頻次")
        ax.legend(fontsize=8)
    fig.suptitle("圖1 報酬順序風險示範：報酬乘積相同，順序不同 → 終值天差地別", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig1_permutation_terminal_dist.png"), dpi=300)
    plt.close(fig)


def fig_crash_curve(crash_gspc, crash_twii):
    fig, ax = plt.subplots(figsize=(10, 6))
    for crash, color, mk in [(crash_gspc, "#1f3b6f", "o"), (crash_twii, "#C44E52", "s")]:
        ys = [c["crash_year"] for c in crash["curve"]]
        fp = [c["fail_prob"] * 100 for c in crash["curve"]]
        lo = [c["ci_lo"] * 100 for c in crash["curve"]]
        hi = [c["ci_hi"] * 100 for c in crash["curve"]]
        ax.plot(ys, fp, marker=mk, color=color, lw=2,
                label=f"{crash['label']}（單月注入 {crash['crash_size_monthly']*100:.0f}% 大跌）")
        ax.fill_between(ys, lo, hi, color=color, alpha=0.15)
        ax.axhline(crash["base_fail_prob_no_injected_crash"] * 100, color=color, lw=1, ls=":",
                   alpha=0.7)
    ax.set_title("圖2 退休風險區：破產機率 vs 崩盤發生年份\n（同樣一次大跌，越早發生破壞力越大 = 報酬順序風險核心）")
    ax.set_xlabel("大跌發生於退休後第幾年")
    ax.set_ylabel("30 年破產機率 (%)")
    ax.legend(fontsize=10)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig2_crash_year_fail_curve.png"), dpi=300)
    plt.close(fig)


def fig_strategy_rank(strat_gspc, strat_twii):
    fig, axes = plt.subplots(1, 2, figsize=(13, 6), sharey=True)
    name_map = {
        "WR3.5%_100stock": "提領率 3.5%",
        "WR4.0%_100stock": "提領率 4.0%（基準）",
        "WR5.0%_100stock": "提領率 5.0%",
        "WR4.0%_static6040": "靜態 60/40",
        "WR4.0%_bond_tent": "Bond tent 股債滑道",
        "WR4.0%_dynamic_GK": "動態提領(GK護欄)",
        "WR4.0%_defer3y": "延後退休 3 年",
    }
    for ax, strat, title in zip(axes, [strat_gspc, strat_twii], ["美股 S&P500", "台股加權"]):
        items = sorted(strat.items(), key=lambda kv: kv[1]["success_rate"])
        labels = [name_map.get(k, k) for k, _ in items]
        vals = [v["success_rate"] * 100 for _, v in items]
        errs_lo = [(v["success_rate"] - v["ci_lo"]) * 100 for _, v in items]
        errs_hi = [(v["ci_hi"] - v["success_rate"]) * 100 for _, v in items]
        colors = ["#C44E52" if "5.0%" in k else ("#55A868" if v["success_rate"] >= 0.9 else "#4C72B0")
                  for k, v in items]
        bars = ax.barh(labels, vals, xerr=[errs_lo, errs_hi], color=colors,
                       error_kw={"elinewidth": 1, "capsize": 3})
        for b, v in zip(bars, vals):
            ax.text(min(v + 1.5, 98), b.get_y() + b.get_height() / 2, f"{v:.1f}%",
                    va="center", fontsize=9)
        ax.set_xlim(0, 105)
        ax.set_title(f"{title}：30 年不破產成功率（4% 基準，誤差棒=95% Wilson CI）")
        ax.set_xlabel("成功率 (%)")
    fig.suptitle("圖3 對策實證排名：哪個最能抵抗報酬順序風險", fontsize=13)
    fig.tight_layout()
    fig.savefig(os.path.join(FIG_DIR, "fig3_strategy_success_rank.png"), dpi=300)
    plt.close(fig)


# ---------------------------------------------------------------------------
def strip_arrays(d):
    return {k: v for k, v in d.items() if not k.startswith("_")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    rets, meta = {}, {}
    for name, sym in TICKERS.items():
        px = fetch(name, sym, refresh=args.refresh)
        m = monthly_returns(px)
        rets[name] = m.to_numpy()
        meta[name] = {
            "symbol": sym,
            "monthly_start": str(m.index.min().date()),
            "monthly_end": str(m.index.max().date()),
            "n_months": int(len(m)),
            "ann_mean_ret": round(float((1 + m.mean()) ** 12 - 1), 4),
            "ann_vol": round(float(m.std() * np.sqrt(12)), 4),
        }

    # 4a 排列示範
    demo_gspc = permutation_demo(rets["GSPC"], "美股 S&P500", INIT_WEALTH, BASE_WR, CPI,
                                 n_years=HORIZON_Y, rng=np.random.default_rng(SEED + 1))
    demo_twii = permutation_demo(rets["TWII"], "台股加權", INIT_WEALTH, BASE_WR, CPI,
                                 n_years=HORIZON_Y, rng=np.random.default_rng(SEED + 2))
    demo_gspc8 = permutation_demo(rets["GSPC"], "美股 S&P500（8年窮舉）", INIT_WEALTH,
                                  BASE_WR, CPI, n_years=8,
                                  rng=np.random.default_rng(SEED + 3))

    # 4b 崩盤年份風險區
    crash_gspc = crash_year_risk(rets["GSPC"], "美股 S&P500", INIT_WEALTH, BASE_WR, CPI,
                                 HORIZON_Y, crash_size=-0.35,
                                 rng=np.random.default_rng(SEED + 10))
    crash_twii = crash_year_risk(rets["TWII"], "台股加權", INIT_WEALTH, BASE_WR, CPI,
                                 HORIZON_Y, crash_size=-0.35,
                                 rng=np.random.default_rng(SEED + 11))

    # 4c 對策排名
    strat_gspc = evaluate_strategies(rets["GSPC"], "美股 S&P500", INIT_WEALTH, CPI,
                                     HORIZON_Y, rng=np.random.default_rng(SEED + 20))
    strat_twii = evaluate_strategies(rets["TWII"], "台股加權", INIT_WEALTH, CPI,
                                     HORIZON_Y, rng=np.random.default_rng(SEED + 21))

    # iid robustness 對照（4% baseline 100stock；同 bond proxy）
    def baseline_success(eq):
        bond = np.random.default_rng(SEED + 99).normal(BOND_MEAN_M, BOND_VOL_M, size=eq.shape)
        res = simulate_depletion(eq, bond, np.ones(HORIZON_Y), INIT_WEALTH, BASE_WR, CPI, HORIZON_Y)
        return float(res["success"].mean())

    iid_robust = {}
    for name in TICKERS:
        sb = stationary_bootstrap_paths(rets[name], N_SIM, HORIZON_Y * 12, MEAN_BLOCK_M,
                                        np.random.default_rng(SEED + 30))
        ii = iid_bootstrap_paths(rets[name], N_SIM, HORIZON_Y * 12,
                                 np.random.default_rng(SEED + 31))
        iid_robust[name] = {
            "stationary_success_4pct": round(baseline_success(sb), 4),
            "iid_success_4pct": round(baseline_success(ii), 4),
        }

    fig_permutation(demo_gspc, demo_twii)
    fig_crash_curve(crash_gspc, crash_twii)
    fig_strategy_rank(strat_gspc, strat_twii)

    def rank_strats(strat):
        base = strat["WR4.0%_100stock"]["success_rate"]
        ranked = [{
            "strategy": name,
            "success_rate": v["success_rate"],
            "improvement_vs_4pct_baseline_pp": round((v["success_rate"] - base) * 100, 2),
            "median_final_wealth": v["median_final_wealth"],
        } for name, v in strat.items()]
        ranked.sort(key=lambda x: x["success_rate"], reverse=True)
        return {"baseline_4pct_100stock": round(base, 4), "ranking": ranked}

    out = {
        "experiment_id": "k1410",
        "title": "報酬順序風險 (Sequence of Returns Risk) 真實資料模擬",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "seed": SEED, "n_sim": N_SIM, "horizon_years": HORIZON_Y,
            "init_wealth_normalized": INIT_WEALTH,
            "cpi_inflation_for_withdrawal_growth": CPI,
            "base_withdrawal_rate": BASE_WR,
            "stationary_bootstrap_mean_block_months": MEAN_BLOCK_M,
            "crash_year_risk_n_sim": 5000,
            "bond_proxy": {"ann_mean": round(BOND_MEAN_M * 12, 4),
                           "ann_vol": round(BOND_VOL_M * np.sqrt(12), 4),
                           "note": "獨立常態 proxy，與股市設 0 相關（保守，不誇大分散效果）"},
            "withdrawal_timing": "年初提領（先扣再投資該年市場報酬）",
            "lookahead_check": "bootstrap 路徑僅由歷史月報酬 resample；提領決策只用當期/過去淨值",
        },
        "data_meta": meta,
        "permutation_demo": {
            "gspc_30y": strip_arrays(demo_gspc),
            "twii_30y": strip_arrays(demo_twii),
            "gspc_8y_exhaustive": strip_arrays(demo_gspc8),
        },
        "crash_year_risk": {"gspc": crash_gspc, "twii": crash_twii},
        "strategy_evaluation": {"gspc": strat_gspc, "twii": strat_twii},
        "strategy_ranking": {"gspc": rank_strats(strat_gspc), "twii": rank_strats(strat_twii)},
        "iid_vs_stationary_robustness": iid_robust,
        "data_limitations": [
            "債券報酬用獨立常態 proxy（年化~4%/vol~5%，與股市 0 相關），非真實債券序列；"
            "真實股債相關隨時期變動，bond tent / 60/40 的分散效果可能被高/低估。",
            "股票月報酬用指數 auto_adjust 收盤近似總報酬，未扣管理費/稅/交易成本。",
            "stationary bootstrap 假設未來月報酬與歷史同分布；結構性轉變（長期低報酬、"
            "高通膨）下實際破產風險可能更高。",
            "CPI 固定 2%，實際通膨波動會額外加重提領期壓力（未建模通膨不確定性）。",
            "Guyton-Klinger 用簡化單一護欄（±20% band, ±10% 調整），非完整四規則版。",
            "排列示範取最近 N 年一籃真實報酬，僅代表該段歷史的報酬分布，非普適。",
        ],
    }

    out_path = os.path.join(HERE, "k1410_results.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print("=== K1410 報酬順序風險 ===")
    for name in TICKERS:
        print(f"[{name}] {meta[name]['monthly_start']}~{meta[name]['monthly_end']} "
              f"N={meta[name]['n_months']} 月  年化{meta[name]['ann_mean_ret']*100:.1f}%/vol{meta[name]['ann_vol']*100:.1f}%")
    print("\n-- 排列示範（同籃 30 年報酬，不同順序，4% 提領）--")
    for d in [demo_gspc, demo_twii]:
        print(f"  {d['label']}: 乘積(順序無關)={d['basket_gross_product_order_invariant']:.2f} → 無提領終值"
              f"{d['no_withdrawal_terminal_any_order']:,.0f}（任何順序皆同）")
        print(f"    有提領: best {d['best_terminal']:,.0f} / median {d['median_terminal']:,.0f} / "
              f"worst {d['worst_terminal']:,.0f}  破產順序占比 {d['pct_orderings_depleted']:.0f}%  "
              f"best/worst={d['best_to_worst_ratio']}")
    print(f"  {demo_gspc8['label']}: best {demo_gspc8['best_terminal']:,.0f} / "
          f"worst {demo_gspc8['worst_terminal']:,.0f} ({demo_gspc8['n_permutations_evaluated']} 全枚舉)")
    print("\n-- 崩盤年份風險區 --")
    for c in [crash_gspc, crash_twii]:
        print(f"  {c['label']}: 早期崩盤(Y1-5)破產率 {c['early_crash_avg_fail_y1_5']*100:.1f}% vs "
              f"晚期(Y26-30) {c['late_crash_avg_fail_y26_30']*100:.1f}%  early/late={c['early_to_late_ratio']}")
    print("\n-- 對策成功率排名 --")
    for name, label in [("gspc", "美股"), ("twii", "台股")]:
        print(f"  [{label}]")
        for r in out["strategy_ranking"][name]["ranking"]:
            print(f"    {r['success_rate']*100:5.1f}%  {r['strategy']:24s} "
                  f"(Δ{r['improvement_vs_4pct_baseline_pp']:+.1f}pp vs 4%基準)")
    print("\n-- iid vs stationary robustness (4% baseline) --")
    for name in TICKERS:
        r = iid_robust[name]
        print(f"  {name}: stationary {r['stationary_success_4pct']*100:.1f}% / iid {r['iid_success_4pct']*100:.1f}%")
    print(f"\nresults -> {out_path}")


if __name__ == "__main__":
    main()
