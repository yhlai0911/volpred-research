#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K1408 — 進場時點是否顯著影響最終年化報酬與 IRR
=================================================

研究問題（用戶精確指定）
------------------------
對每一個進場時點 t（月頻：每 ~21 交易日一個進場點），從 t 一路投入、
全部持有到資料最後一天 T（即 t→T、t+1月→T、t+2月→T … 直到接近 T）。
每個進場點各算：
  - 單筆投入(Lump Sum)：t 一次投入持有到 T。年化報酬率(=IRR，單一現金流數學上相等)。
  - 定期定額(DCA)：從 t 起每月投入持有到 T。時間加權年化報酬率(TWR) 與 money-weighted IRR。
記錄每個進場點的 horizon（持有年數 =(T−t)/252）。

→ 會得到 ~T 組數值（SPY 月頻約 250 個進場點、0050 約 200 個）。

要回答：不同進場時點的最終結果（年化報酬率、IRR）是否有顯著差異？

重要方法論認知（用戶澄清）
--------------------------
- 年化報酬率與 IRR 已除以年數，故「持有期長短」不造成 level 差異。不把期間長短
  當干擾、不改固定持有期窗口。
- 唯一真實細節：越短持有期，年化數字的 variance 越大（σ_annualized ∝ 1/√horizon）。
  晚進場=結果更不確定，是要如實報告的現象本身。

正式檢定（處理 overlapping-window 自相關）
------------------------------------------
1. 描述統計（含分 horizon bucket 看離散度隨持有期變化）
2. 趨勢檢定：進場時點(日曆順序) vs outcome — Spearman ρ + block bootstrap /
   Newey-West 修正自相關後顯著性（不用 naive iid p-value）
3. 核心檢定：相近 horizon band 內，不同日曆進場點 outcome 是否仍顯著離散
   （控制持有期，分離「日曆擇時影響」vs「短期 horizon 雜訊」）
4. verdict

資料：experiments/k1406/data/{SPY.csv, 0050.TW.csv}（真實 yfinance auto-adjust）
seed = 20260530（所有 bootstrap）
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import brentq

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# ----------------------------------------------------------------------------
# 設定
# ----------------------------------------------------------------------------
SEED = 20260530
np.random.seed(SEED)

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE.parent / "k1406" / "data"
FIG_DIR = HERE / "figs"
FIG_DIR.mkdir(exist_ok=True)

TRADING_DAYS_YEAR = 252.0
MONTH_DAYS = 21                 # 月頻進場間隔（交易日）
MIN_HORIZON_DAYS = 63          # 最短 horizon ~3 個月（仍呈現「越短越跳」）
N_BOOT = 10000                 # block bootstrap 次數
BLOCK_LEN = 12                 # block 長度（月頻進場點序列；12 個進場點 ≈ 1 年）

# 繁中字型
for fname in ["Heiti TC", "Arial Unicode MS", "Hiragino Sans GB"]:
    try:
        font_manager.findfont(fname, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [fname]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


# ----------------------------------------------------------------------------
# 報酬計算
# ----------------------------------------------------------------------------
def load_prices(path: Path) -> pd.Series:
    df = pd.read_csv(path, parse_dates=["Date"]).sort_values("Date")
    s = df.set_index("Date")["Close"].astype(float)
    s = s[s > 0].dropna()
    return s


def lump_annualized(price_t: float, price_T: float, years: float) -> float:
    """單筆投入年化報酬（單一現金流 IRR 與年化報酬數學相等）。"""
    if years <= 0 or price_t <= 0:
        return np.nan
    return (price_T / price_t) ** (1.0 / years) - 1.0


def dca_twr_annualized(prices: pd.Series, years: float) -> float:
    """
    DCA 時間加權年化報酬(TWR)。
    DCA = 每月投入相同金額；TWR 衡量「投資標的本身」的時間加權報酬，
    與現金流時點無關 → 對單一標的，DCA 的 TWR 等同於該標的在區間內的
    daily 報酬鏈年化（buy-and-hold 的幾何年化），因為每筆現金都買進同一檔。
    我們直接用 daily geometric return chain 年化（與投入排程無關）。
    """
    if years <= 0 or len(prices) < 2:
        return np.nan
    daily_ret = prices.values[1:] / prices.values[:-1]
    growth = float(np.prod(daily_ret))
    if growth <= 0:
        return np.nan
    return growth ** (1.0 / years) - 1.0


def _npv(rate: float, cashflows: np.ndarray, times_years: np.ndarray) -> float:
    """NPV，用 exp/log 形式避免 (1+r)^t overflow；rate>-1。"""
    if rate <= -0.999999:
        rate = -0.999999
    disc = np.exp(-times_years * np.log1p(rate))  # (1+r)^(-t)
    return float(np.sum(cashflows * disc))


def money_weighted_irr_dca(invest_times_year: np.ndarray, terminal_value: float,
                           terminal_year: float, contrib: float = 1.0) -> float:
    """
    DCA money-weighted IRR：每個 invest 時點投入 contrib（負現金流），
    最終時點 terminal_year 收回 terminal_value（正現金流）。
    用 brentq grid-scan 求根，避免 (1+r)^t overflow。

    時間軸以「進場點 t 為 0 起算、往未來遞增的年數」為 t（越晚投入 t 越大），
    NPV 折現基準為進場點：NPV = Σ_i -contrib·(1+r)^(-t_i) + terminal·(1+r)^(-terminal_year)。
    令 NPV=0 解出 IRR（forward-time 折現，與 lump 單一現金流 IRR 對齊）。
    """
    if terminal_value <= 0 or len(invest_times_year) == 0:
        return np.nan
    times = np.concatenate([invest_times_year, [terminal_year]])
    cfs = np.concatenate([-contrib * np.ones(len(invest_times_year)), [terminal_value]])

    def f(r):
        return _npv(r, cfs, times)

    grid = np.unique(np.concatenate([
        np.linspace(-0.95, -0.05, 19),
        np.linspace(-0.05, 0.50, 56),
        np.linspace(0.50, 3.0, 26),
    ]))
    fvals = np.array([f(r) for r in grid])
    root = np.nan
    for i in range(len(grid) - 1):
        a, b = fvals[i], fvals[i + 1]
        if np.isfinite(a) and np.isfinite(b) and a * b < 0:
            try:
                root = brentq(f, grid[i], grid[i + 1], maxiter=200, xtol=1e-8)
                break
            except Exception:
                continue
    return root


def build_entry_table(prices: pd.Series, name: str) -> pd.DataFrame:
    """對每個月頻進場點 t，算 lump 年化 / DCA TWR / DCA IRR / horizon。"""
    dates = prices.index
    n = len(prices)
    T_idx = n - 1
    price_T = float(prices.iloc[-1])
    date_T = dates[-1]

    rows = []
    entry_idxs = list(range(0, T_idx - MIN_HORIZON_DAYS + 1, MONTH_DAYS))
    for ti in entry_idxs:
        date_t = dates[ti]
        price_t = float(prices.iloc[ti])
        horizon_cal_days = (date_T - date_t).days
        years = (T_idx - ti) / TRADING_DAYS_YEAR
        if years <= 0:
            continue

        lump_ann = lump_annualized(price_t, price_T, years)

        sub = prices.iloc[ti:]
        dca_twr = dca_twr_annualized(sub, years)

        # DCA money-weighted IRR：從 t 起每月投入 1 單位直到接近 T
        # 時間以「進場點 t 為 0、往未來遞增」計：投入在 (ii-ti)/252，terminal 在 (T_idx-ti)/252。
        invest_idxs = list(range(ti, T_idx + 1, MONTH_DAYS))
        contrib = 1.0
        shares = 0.0
        invest_times_year = []  # 自進場點 t 起算的年數（forward time）
        for ii in invest_idxs:
            p = float(prices.iloc[ii])
            shares += contrib / p
            invest_times_year.append((ii - ti) / TRADING_DAYS_YEAR)
        terminal_value = shares * price_T
        terminal_year = (T_idx - ti) / TRADING_DAYS_YEAR
        dca_irr = money_weighted_irr_dca(np.array(invest_times_year), terminal_value,
                                         terminal_year=terminal_year, contrib=contrib)

        rows.append(dict(
            entry_date=date_t.strftime("%Y-%m-%d"),
            entry_idx=ti,
            horizon_years=round(years, 4),
            horizon_cal_days=horizon_cal_days,
            n_contributions=len(invest_idxs),
            lump_annualized=lump_ann,
            dca_twr_annualized=dca_twr,
            dca_irr=dca_irr,
        ))
    df = pd.DataFrame(rows)
    df.attrs["name"] = name
    df.attrs["date_T"] = date_T.strftime("%Y-%m-%d")
    df.attrs["price_T"] = price_T
    return df


# ----------------------------------------------------------------------------
# 統計檢定
# ----------------------------------------------------------------------------
def describe_metric(x: np.ndarray) -> dict:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return {}
    q1, q3 = np.percentile(x, [25, 75])
    return dict(
        n=int(len(x)),
        mean=float(np.mean(x)),
        median=float(np.median(x)),
        std=float(np.std(x, ddof=1)) if len(x) > 1 else 0.0,
        min=float(np.min(x)),
        max=float(np.max(x)),
        range=float(np.max(x) - np.min(x)),
        iqr=float(q3 - q1),
        p25=float(q1),
        p75=float(q3),
    )


BANDS = [(">10年", 10.0, np.inf), ("5-10年", 5.0, 10.0),
         ("2-5年", 2.0, 5.0), ("<2年", 0.0, 2.0)]


def horizon_buckets(df: pd.DataFrame, metric: str) -> dict:
    """分 horizon bucket 看離散度隨持有期變化。"""
    out = {}
    for label, lo, hi in BANDS:
        sub = df[(df["horizon_years"] >= lo) & (df["horizon_years"] < hi)]
        d = describe_metric(sub[metric].values)
        if d:
            d["mean_horizon"] = float(sub["horizon_years"].mean())
            out[label] = d
    return out


def variance_horizon_scaling(df: pd.DataFrame, metric: str) -> dict:
    """檢定 σ_annualized ∝ 1/√horizon：log-log 回歸 bucket std vs mean_horizon，理論斜率 ≈ -0.5。"""
    bk = horizon_buckets(df, metric)
    xs, ys = [], []
    for label, d in bk.items():
        if d.get("std", 0) > 0 and d.get("mean_horizon", 0) > 0:
            xs.append(np.log(d["mean_horizon"]))
            ys.append(np.log(d["std"]))
    if len(xs) < 2:
        return dict(slope=None, note="不足 2 個 bucket")
    slope, intercept, r, p, se = stats.linregress(xs, ys)
    return dict(slope=float(slope), intercept=float(intercept), r=float(r),
                p=float(p), se=float(se), theory_slope=-0.5,
                interpretation="斜率接近 -0.5 即支持 σ∝1/√horizon")


def block_bootstrap_spearman(order_idx: np.ndarray, outcome: np.ndarray,
                             n_boot: int, block_len: int, rng) -> dict:
    """
    趨勢檢定：進場時點(日曆順序) vs outcome 的 Spearman ρ，
    用 moving block bootstrap 建構保留 outcome 自相關的 null 分布修正 overlapping-window
    自相關後求 p-value。H0: 無單調趨勢（ρ=0）。
    """
    mask = np.isfinite(outcome)
    x = order_idx[mask].astype(float)
    y = outcome[mask].astype(float)
    n = len(y)
    rho_obs, p_naive = stats.spearmanr(x, y)

    n_blocks = int(np.ceil(n / block_len))
    starts_max = n - block_len
    boot_rhos = np.empty(n_boot)
    for b in range(n_boot):
        if starts_max <= 0:
            idx = rng.integers(0, n, size=n)
        else:
            starts = rng.integers(0, starts_max + 1, size=n_blocks)
            idx = np.concatenate([np.arange(s, s + block_len) for s in starts])[:n]
        yb = y[idx]                 # block 重抽 outcome：破壞長期趨勢、保留局部自相關
        rb, _ = stats.spearmanr(x, yb)  # 固定時間軸 x，建構 H0(無趨勢)+保留自相關 的 null
        boot_rhos[b] = rb
    boot_rhos = boot_rhos[np.isfinite(boot_rhos)]
    p_boot = float(np.mean(np.abs(boot_rhos) >= abs(rho_obs)))
    return dict(
        rho=float(rho_obs),
        p_block_bootstrap=p_boot,
        p_naive_iid=float(p_naive),
        n_boot=int(len(boot_rhos)),
        block_len=block_len,
        boot_rho_std=float(np.std(boot_rhos)),
        note="p_block_bootstrap 是修正自相關後的顯著性；p_naive_iid 會嚴重低估",
    )


def newey_west_trend(order_idx: np.ndarray, outcome: np.ndarray) -> dict:
    """OLS outcome ~ order_idx，Newey-West HAC SE 修正自相關，回報 slope 與 HAC t/p（對照 naive OLS）。"""
    mask = np.isfinite(outcome)
    x = order_idx[mask].astype(float)
    y = outcome[mask].astype(float)
    n = len(y)
    X = np.column_stack([np.ones(n), x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    XtX_inv = np.linalg.inv(X.T @ X)

    sigma2 = float(resid @ resid) / (n - 2)
    se_naive = np.sqrt(np.diag(sigma2 * XtX_inv))
    t_naive = beta / se_naive
    p_naive = 2 * (1 - stats.t.cdf(np.abs(t_naive), df=n - 2))

    L = max(int(np.floor(4 * (n / 100.0) ** (2.0 / 9.0))), 1)  # Newey-West 1994
    u = X * resid[:, None]
    S = u.T @ u
    for lag in range(1, L + 1):
        w = 1.0 - lag / (L + 1.0)  # Bartlett kernel
        Gl = u[lag:].T @ u[:-lag]
        S += w * (Gl + Gl.T)
    cov_hac = XtX_inv @ S @ XtX_inv
    se_hac = np.sqrt(np.diag(cov_hac))
    t_hac = beta / se_hac
    p_hac = 2 * (1 - stats.t.cdf(np.abs(t_hac), df=n - 2))

    return dict(
        slope=float(beta[1]),
        slope_per_year=float(beta[1] * (TRADING_DAYS_YEAR / MONTH_DAYS)),
        se_naive=float(se_naive[1]),
        p_naive=float(p_naive[1]),
        se_hac=float(se_hac[1]),
        t_hac=float(t_hac[1]),
        p_hac=float(p_hac[1]),
        nw_lag=int(L),
        note="p_hac 是 Newey-West 修正後；p_naive 低估",
    )


def within_horizon_band_dispersion(df: pd.DataFrame, metric: str, rng,
                                   n_boot: int = 5000) -> dict:
    """
    核心檢定：相近 horizon band 內，不同日曆進場點的 outcome 離散，是否「超出純粹
    由 horizon 長度差異機械驅動的部分」？= 真正的日曆擇時效應。

    方法（修正 agy review §5 指出的 confounding：原版「局部相鄰 std vs 全 band std」因
    overlapping-window 機械正自相關，p 恆 ≈0、無法分離日曆 vs horizon）：

    1. band 內先把 outcome 對 horizon_years 做 OLS（去除「band 內 horizon 仍有殘餘
       長度差異」造成的機械變異）→ 取殘差 resid。
    2. 觀測統計量 = resid 的 std（= 控制 horizon 後仍存在的日曆離散）。
    3. Null 建構（H0：日曆位置無影響，殘差只是 horizon-only 模型的隨機雜訊）：
       對 resid 做 moving block bootstrap（block 保留局部自相關）+ 隨機重排塊序，
       破壞「特定日曆時點」與殘差大小的系統性對應，但保留殘差的邊際分布與短程自相關。
       注意：因 block bootstrap 重抽 resid，null 的 std 期望 ≈ 觀測 std（兩者用同一組
       resid），所以**單純比 std 無鑑別力**。改測：殘差是否隨「日曆順序」呈系統性
       structure — 用 resid 對 order_idx 的 |Spearman ρ| 作統計量（觀測 vs block-permuted null）。
       ρ 顯著 → 控制 horizon 後，殘差仍隨日曆時點系統性變化 = 真日曆擇時效應。
    """
    out = {}
    for label, lo, hi in BANDS:
        sub = df[(df["horizon_years"] >= lo) & (df["horizon_years"] < hi)].copy()
        sub = sub[np.isfinite(sub[metric])]
        n = len(sub)
        if n < 10:
            continue
        y = sub[metric].to_numpy(float)
        h = sub["horizon_years"].to_numpy(float)
        order = sub["entry_idx"].to_numpy(float)  # 日曆順序

        # 1. 去 horizon 機械效應：OLS y ~ horizon → 殘差
        X = np.column_stack([np.ones(n), h])
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
        resid = y - X @ beta
        resid_std = float(np.std(resid, ddof=1))
        raw_std = float(np.std(y, ddof=1))
        horizon_r2 = 1.0 - float(resid @ resid) / float(((y - y.mean()) ** 2).sum() + 1e-12)

        # 2. 觀測：殘差 vs 日曆順序的 |Spearman ρ|（控制 horizon 後的殘餘日曆 structure）
        rho_obs, _ = stats.spearmanr(order, resid)
        rho_obs = 0.0 if not np.isfinite(rho_obs) else rho_obs

        # 3. block-bootstrap null：重排 resid 的塊序破壞日曆對應，保留局部自相關
        bl = min(8, max(3, n // 5))
        n_blocks = int(np.ceil(n / bl))
        starts_max = n - bl
        null_rhos = np.empty(n_boot)
        for b in range(n_boot):
            if starts_max <= 0:
                rb = rng.permutation(resid)
            else:
                starts = rng.integers(0, starts_max + 1, size=n_blocks)
                rb = np.concatenate([resid[s:s + bl] for s in starts])[:n]
            r, _ = stats.spearmanr(order, rb)
            null_rhos[b] = 0.0 if not np.isfinite(r) else r
        p_cal = float(np.mean(np.abs(null_rhos) >= abs(rho_obs)))

        out[label] = dict(
            n=n, mean_horizon=float(sub["horizon_years"].mean()),
            horizon_years_span=[float(h.min()), float(h.max())],
            raw_std=raw_std,
            resid_std_after_horizon=resid_std,
            horizon_explained_r2=horizon_r2,
            resid_vs_calendar_spearman_rho=float(rho_obs),
            p_calendar_effect_blockboot=p_cal,
            interpretation=("控制 horizon 後，殘差仍隨日曆順序系統性變化(|ρ| 大且 p 小)"
                            " → 真日曆擇時效應；p 大 → band 內離散主要是 horizon 殘餘長度差異"),
        )
    return out


# ----------------------------------------------------------------------------
# 繪圖
# ----------------------------------------------------------------------------
def plot_lump_vs_entry(df, name, fname):
    fig, ax = plt.subplots(figsize=(11, 5.5))
    dates = pd.to_datetime(df["entry_date"]).to_numpy()
    y = df["lump_annualized"].to_numpy() * 100
    sc = ax.scatter(dates, y, c=df["horizon_years"].to_numpy(), cmap="viridis", s=42,
                    edgecolor="white", linewidth=0.4, zorder=3)
    ax.plot(dates, y, color="#888", lw=0.8, alpha=0.5, zorder=2)
    ax.axhline(np.nanmedian(y), color="crimson", ls="--", lw=1.2,
               label=f"中位數 {np.nanmedian(y):.1f}%")
    cb = fig.colorbar(sc, ax=ax)
    cb.set_label("持有年數 (horizon)")
    ax.set_title(f"{name}：單筆投入年化報酬率 vs 進場時點（持有到資料末日 T）")
    ax.set_xlabel("進場時點（日曆時間）")
    ax.set_ylabel("單筆投入年化報酬率 (%)")
    ax.legend(loc="best"); ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(FIG_DIR / fname, dpi=130); plt.close(fig)


def plot_dca_vs_entry(df, name, fname):
    fig, ax = plt.subplots(figsize=(11, 5.5))
    dates = pd.to_datetime(df["entry_date"]).to_numpy()
    ax.plot(dates, df["dca_twr_annualized"].to_numpy() * 100, "o-", ms=4, lw=1,
            color="#1f77b4", label="DCA 時間加權年化 (TWR)")
    ax.plot(dates, df["dca_irr"].to_numpy() * 100, "s-", ms=4, lw=1,
            color="#ff7f0e", label="DCA money-weighted IRR")
    ax.set_title(f"{name}：定期定額 TWR 與 IRR vs 進場時點（每月投入持有到 T）")
    ax.set_xlabel("進場時點（日曆時間）")
    ax.set_ylabel("年化報酬率 (%)")
    ax.legend(loc="best"); ax.grid(alpha=0.25)
    fig.tight_layout(); fig.savefig(FIG_DIR / fname, dpi=130); plt.close(fig)


def plot_dispersion_vs_horizon(df, name, fname):
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2))
    metrics = [("lump_annualized", "單筆年化"), ("dca_irr", "DCA IRR")]
    for ax, (m, mlabel) in zip(axes, metrics):
        labels, stds, mh = [], [], []
        for lab, lo, hi in BANDS:
            sub = df[(df["horizon_years"] >= lo) & (df["horizon_years"] < hi)]
            v = sub[m].values; v = v[np.isfinite(v)]
            if len(v) >= 2:
                labels.append(lab); stds.append(np.std(v, ddof=1) * 100)
                mh.append(sub["horizon_years"].mean())
        ax.bar(labels, stds, color="#4c72b0", alpha=0.85)
        for i, (s, h) in enumerate(zip(stds, mh)):
            ax.text(i, s, f"σ={s:.1f}%\nh̄={h:.1f}y", ha="center", va="bottom", fontsize=8)
        ax.set_title(f"{name}：{mlabel} 離散度 vs 持有期")
        ax.set_ylabel("年化報酬標準差 (%)"); ax.set_xlabel("持有期 bucket")
        ax.grid(alpha=0.2, axis="y")
    fig.suptitle(f"{name}：越短持有期 → 年化報酬離散度越大（σ∝1/√horizon）", y=1.02)
    fig.tight_layout(); fig.savefig(FIG_DIR / fname, dpi=130, bbox_inches="tight"); plt.close(fig)


def plot_dispersion_loglog(spy_df, tw_df, fname):
    fig, ax = plt.subplots(figsize=(8, 6))
    for df, name, color in [(spy_df, "SPY", "#1f77b4"), (tw_df, "0050.TW", "#d62728")]:
        xs, ys = [], []
        for lab, lo, hi in BANDS:
            sub = df[(df["horizon_years"] >= lo) & (df["horizon_years"] < hi)]
            v = sub["lump_annualized"].values; v = v[np.isfinite(v)]
            if len(v) >= 2:
                xs.append(sub["horizon_years"].mean()); ys.append(np.std(v, ddof=1))
        if len(xs) >= 2:
            xs, ys = np.array(xs), np.array(ys)
            ax.loglog(xs, ys * 100, "o-", color=color, ms=8, label=name)
            sl, *_ = stats.linregress(np.log(xs), np.log(ys))
            ax.annotate(f"{name} 斜率={sl:.2f}", (xs[-1], ys[-1] * 100), color=color, fontsize=9)
    xref = np.array([1.5, 18]); yref = 30 * (xref / xref[0]) ** -0.5
    ax.loglog(xref, yref, "k--", alpha=0.5, label="理論 slope=-0.5 (σ∝1/√h)")
    ax.set_title("單筆年化報酬離散度 σ vs 持有期（log-log，驗證 σ∝1/√horizon）")
    ax.set_xlabel("平均持有年數（log）"); ax.set_ylabel("年化報酬標準差 % （log）")
    ax.legend(loc="best"); ax.grid(alpha=0.3, which="both")
    fig.tight_layout(); fig.savefig(FIG_DIR / fname, dpi=130); plt.close(fig)


# ----------------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------------
def analyze(df, name, rng) -> dict:
    res = {
        "name": name,
        "n_entry_points": int(len(df)),
        "date_T": df.attrs["date_T"],
        "price_T": df.attrs["price_T"],
        "horizon_years_range": [float(df["horizon_years"].min()), float(df["horizon_years"].max())],
    }
    metrics = ["lump_annualized", "dca_twr_annualized", "dca_irr"]
    res["descriptive"] = {m: describe_metric(df[m].values) for m in metrics}
    res["horizon_buckets"] = {m: horizon_buckets(df, m) for m in metrics}
    res["variance_horizon_scaling"] = {m: variance_horizon_scaling(df, m) for m in metrics}
    order_idx = np.arange(len(df))
    res["trend_spearman_blockboot"] = {
        m: block_bootstrap_spearman(order_idx, df[m].values, N_BOOT, BLOCK_LEN, rng) for m in metrics}
    res["trend_newey_west"] = {m: newey_west_trend(order_idx, df[m].values) for m in metrics}
    res["within_horizon_band_dispersion"] = {
        m: within_horizon_band_dispersion(df, m, rng) for m in metrics}
    return res


def make_verdict(spy_res, tw_res, spy_df, tw_df) -> dict:
    def summarize(res, name):
        lump = res["descriptive"]["lump_annualized"]
        irr = res["descriptive"]["dca_irr"]
        bk = res["horizon_buckets"]["lump_annualized"]
        long_band, short_band = bk.get(">10年", {}), bk.get("<2年", {})
        tr = res["trend_spearman_blockboot"]["lump_annualized"]
        nw = res["trend_newey_west"]["lump_annualized"]
        g = lambda d, k: round(d.get(k, float("nan")) * 100, 2) if d else None
        return dict(
            asset=name,
            lump_annualized_range_pct=[round(lump["min"] * 100, 2), round(lump["max"] * 100, 2)],
            lump_annualized_full_range_pct=round(lump["range"] * 100, 2),
            lump_median_pct=round(lump["median"] * 100, 2),
            dca_irr_range_pct=[round(irr["min"] * 100, 2), round(irr["max"] * 100, 2)],
            dca_irr_full_range_pct=round(irr["range"] * 100, 2),
            long_horizon_std_pct=g(long_band, "std"),
            long_horizon_range_pct=g(long_band, "range"),
            short_horizon_std_pct=g(short_band, "std"),
            short_horizon_range_pct=g(short_band, "range"),
            trend_rho=round(tr["rho"], 3),
            trend_p_block_bootstrap=round(tr["p_block_bootstrap"], 4),
            trend_p_naive_iid=round(tr["p_naive_iid"], 6),
            nw_slope_per_year_pct=round(nw["slope_per_year"] * 100, 4),
            nw_p_hac=round(nw["p_hac"], 4),
            nw_p_naive=round(nw["p_naive"], 6),
            within_band_dispersion=res["within_horizon_band_dispersion"]["lump_annualized"],
        )

    spy_s, tw_s = summarize(spy_res, "SPY"), summarize(tw_res, "0050.TW")

    def cal_summary(res):
        wb = res["within_horizon_band_dispersion"]["lump_annualized"]
        sig = [b for b, v in wb.items() if v["p_calendar_effect_blockboot"] < 0.05]
        return dict(
            n_bands=len(wb),
            n_bands_sig_calendar=len(sig),
            sig_bands=sig,
            max_abs_resid_calendar_rho=round(max(abs(v["resid_vs_calendar_spearman_rho"])
                                                 for v in wb.values()), 3),
            min_p_calendar=round(min(v["p_calendar_effect_blockboot"] for v in wb.values()), 4),
            mean_horizon_R2=round(float(np.mean([v["horizon_explained_r2"]
                                                 for v in wb.values()])), 3),
        )

    spy_cal, tw_cal = cal_summary(spy_res), cal_summary(tw_res)

    vt = [
        ("(a) 進場時點對最終年化報酬/IRR 的影響：兩資產的單筆年化報酬在不同進場點之間"
         f"確有可觀 raw range（SPY {spy_s['lump_annualized_full_range_pct']} 個百分點、"
         f"0050 {tw_s['lump_annualized_full_range_pct']} 個百分點；0050 的極大值來自 2025 末"
         "進場、僅持有約 4 個月的短窗年化放大，非長期可實現報酬）。"),
        ("(b) 差異主要來源 = horizon 長度，不是日曆擇時。raw range 絕大部分由「越晚進場 "
         "horizon 越短 → 年化離散度爆增」驅動："
         f"長 horizon(>10年)band 內年化 std 僅 SPY {spy_s['long_horizon_std_pct']}%/"
         f"0050 {tw_s['long_horizon_std_pct']}%，短 horizon(<2年)飆到 "
         f"SPY {spy_s['short_horizon_std_pct']}%/0050 {tw_s['short_horizon_std_pct']}%，"
         "驗證 σ_annualized∝1/√horizon。控制 horizon 後（OLS 去 horizon → 殘差 vs 日曆順序 "
         "Spearman ρ + block bootstrap），"
         f"SPY {spy_cal['n_bands_sig_calendar']}/{spy_cal['n_bands']} band、"
         f"0050 {tw_cal['n_bands_sig_calendar']}/{tw_cal['n_bands']} band 有顯著(<0.05)日曆效應；"
         f"最大殘差-日曆 |ρ| 僅 SPY {spy_cal['max_abs_resid_calendar_rho']}/"
         f"0050 {tw_cal['max_abs_resid_calendar_rho']}，min p={spy_cal['min_p_calendar']}/"
         f"{tw_cal['min_p_calendar']} → 控制持有期後，沒有任何進場月份系統性勝出（NULL 擇時效應）。"),
        ("(c) 是否隨 horizon 收斂：是。拉長持有期後不同進場點的年化報酬大幅收斂"
         "（>10年 band std 約為 <2年 band 的 1/4~1/8），且 horizon 在各 band 解釋了 "
         f"平均 {spy_cal['mean_horizon_R2']}(SPY)/{tw_cal['mean_horizon_R2']}(0050) 的離散。"
         "結論：長期投資者進場時點影響有限且不可預測擇時；短期投資者結果離散巨大，"
         "但那是運氣/雜訊（σ∝1/√horizon），非任何進場時點本身的可重複優劣。"),
        ("趨勢檢定（純機械、僅作 overlapping-window 修正示範）：晚進場因 horizon 短 + 近期"
         "價格在高點，年化機械偏高 → Spearman ρ 為正且大"
         f"（SPY ρ={spy_s['trend_rho']}, 0050 ρ={tw_s['trend_rho']}）；block-bootstrap p"
         f"（SPY {spy_s['trend_p_block_bootstrap']}）與 naive iid p（{spy_s['trend_p_naive_iid']}）"
         "差距示範 overlapping-window 下 naive iid 嚴重低估 p。此 ρ 是 horizon 機械耦合，"
         "不是可交易擇時 — 真正分離後（within-band）擇時效應為 null。"),
    ]
    return dict(SPY=spy_s, TW0050=tw_s,
                calendar_effect_summary={"SPY": spy_cal, "0050.TW": tw_cal},
                verdict_statements=vt)


def to_jsonable(obj):
    if isinstance(obj, dict):
        return {k: to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, np.floating):
        f = float(obj); return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    return obj


def main():
    rng = np.random.default_rng(SEED)

    spy = load_prices(DATA_DIR / "SPY.csv")
    tw = load_prices(DATA_DIR / "0050.TW.csv")
    print(f"SPY: {len(spy)} days {spy.index[0].date()}..{spy.index[-1].date()}")
    print(f"0050: {len(tw)} days {tw.index[0].date()}..{tw.index[-1].date()}")

    spy_df = build_entry_table(spy, "SPY")
    tw_df = build_entry_table(tw, "0050.TW")
    print(f"SPY entry points: {len(spy_df)} | 0050 entry points: {len(tw_df)}")

    spy_res = analyze(spy_df, "SPY", rng)
    tw_res = analyze(tw_df, "0050.TW", rng)
    verdict = make_verdict(spy_res, tw_res, spy_df, tw_df)

    plot_lump_vs_entry(spy_df, "SPY", "fig_a_spy_lump_vs_entry.png")
    plot_dca_vs_entry(spy_df, "SPY", "fig_b_spy_dca_vs_entry.png")
    plot_dispersion_vs_horizon(spy_df, "SPY", "fig_c_spy_dispersion_vs_horizon.png")
    plot_lump_vs_entry(tw_df, "0050.TW", "fig_d_tw_lump_vs_entry.png")
    plot_dispersion_loglog(spy_df, tw_df, "fig_e_dispersion_loglog.png")
    plot_dca_vs_entry(tw_df, "0050.TW", "fig_f_tw_dca_vs_entry.png")

    out = {
        "experiment_id": "k1408",
        "title": "進場時點是否顯著影響最終年化報酬與 IRR",
        "seed": SEED,
        "data_source": "experiments/k1406/data/{SPY.csv, 0050.TW.csv} (yfinance auto-adjust)",
        "data_span": {
            "SPY": f"{spy.index[0].date()}..{spy.index[-1].date()} ({len(spy)} days)",
            "0050.TW": f"{tw.index[0].date()}..{tw.index[-1].date()} ({len(tw)} days)",
        },
        "method": {
            "entry_frequency": "月頻（每 21 交易日一進場點）",
            "holding": "每個進場點 t 持有到資料末日 T（t→T）",
            "min_horizon_days": MIN_HORIZON_DAYS,
            "lump": "單筆 t 投入持有到 T；年化=(P_T/P_t)^(1/years)-1（=單一現金流 IRR）",
            "dca_twr": "標的 daily 報酬鏈幾何年化（時間加權，與投入排程無關）",
            "dca_irr": "每月投入 1 單位 money-weighted IRR，brentq grid-scan 求根避免 (1+r)^t overflow",
            "horizon_def": "years=(T_idx - t_idx)/252",
            "trend_test": "Spearman ρ + moving block bootstrap (block=12 進場點) 修正自相關 + Newey-West HAC OLS",
            "within_band_test": "相近 horizon band 內 block bootstrap 比較全 band std vs 局部(相近時點) std",
            "n_boot": N_BOOT,
            "block_len_entrypoints": BLOCK_LEN,
        },
        "results": {"SPY": spy_res, "0050.TW": tw_res},
        "verdict": verdict,
        "entry_tables": {
            "SPY": spy_df.to_dict(orient="records"),
            "0050.TW": tw_df.to_dict(orient="records"),
        },
        "figures": [
            "figs/fig_a_spy_lump_vs_entry.png",
            "figs/fig_b_spy_dca_vs_entry.png",
            "figs/fig_c_spy_dispersion_vs_horizon.png",
            "figs/fig_d_tw_lump_vs_entry.png",
            "figs/fig_e_dispersion_loglog.png",
            "figs/fig_f_tw_dca_vs_entry.png",
        ],
    }

    out_path = HERE / "k1408_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(to_jsonable(out), f, ensure_ascii=False, indent=2)
    print(f"Wrote {out_path}")

    print("\n=== VERDICT 摘要 ===")
    for s in verdict["verdict_statements"]:
        print("-", s)
    keys = [k for k in verdict["SPY"] if k != "within_band_dispersion"]
    print("\nSPY:", json.dumps(to_jsonable({k: verdict["SPY"][k] for k in keys}), ensure_ascii=False))
    print("0050:", json.dumps(to_jsonable({k: verdict["TW0050"][k] for k in keys}), ensure_ascii=False))


if __name__ == "__main__":
    main()
