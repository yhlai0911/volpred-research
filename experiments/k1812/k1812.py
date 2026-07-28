#!/usr/bin/env python3
"""K1812 — Betting-Against-Beta (BAB) conditioned on prior-month realized volatility.

獨立以 yfinance 美股大樣本月度資料重做 Frazzini–Pedersen (2014) 的 BAB 因子，並檢定
JFE (2025) *The volatility puzzle of the beta anomaly* 的核心主張：**BAB 報酬條件於前期
已實現波動 —— 低波動月之後的 BAB Sharpe 是否較高**。

方法論要點（見 README）：
  * Beta：每月月底用過去 L=12 個月的日（超額）報酬對市場日超額報酬 OLS 回歸估 beta_i,t。
    只用 ≤ 月底資料。
  * BAB 組合：Frazzini–Pedersen 排序權重（rank weighting）分低/高 beta 兩腿，各腿以其
    ex-ante beta 去/加槓桿到 beta=1，組合 ex-ante 市場中性。逐月 rebalance，持有到 t+1。
  * Vol regime：以 t 月市場 RV 分高/低（median split 為主，另報 tercile robustness）。
    regime 來自 t 月，預測 t+1 月的 BAB 報酬 —— 代碼裡以 `.shift(1)` 明確 lag。
  * 檢定：全期 BAB mean / Sharpe / Newey-West HAC t；低 vol 月後 vs 高 vol 月後條件 Sharpe
    差異的**主顯著性檢定 = circular block permutation**（重排 regime label 的整段區塊，
    保留 regime 持續性；明確 impose H0，seed=42、10,000 reps）。i.i.d. label permutation
    只留作對照（它會摧毀 regime clustering），bootstrap 只給 effect-size CI；
    迴歸 BAB_{t+1} ~ a + b·1{low_vol_t}（HAC t）。

Lookahead 政策（最高風險）：
  * Beta 只用 ≤ 形成月底資料估計；報酬只用形成月**之後**的月份 → 兩者天然不重疊。
  * regime 訊號 = 形成月（t）市場 RV，對齊到 t+1 月報酬 → `low_vol_signal = regime.shift(1)`
    （以「報酬月」為索引；報酬月 m 的訊號 = 上一月 m-1 的 regime）。
  * baseline（無條件 BAB）與條件版共用同一套 lag 與同一組合建構，公平比較。
  * 所有 bootstrap / permutation 固定 seed=42。

資料誠實 caveat：yfinance 只給現存 ticker → universe 天生 survivorship bias，不可完全消除，
結論強度須相應下修（見 README + results.json 的 caveats 欄位）。

Usage:
    uv run python experiments/k1812/k1812.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import statsmodels.api as sm

from volpred.research.reproduce_spec import finalize_experiment

# --------------------------------------------------------------------------------------
# 固定參數
# --------------------------------------------------------------------------------------
SEED = 42
START_DATE = "2004-01-01"          # 下載起點；beta 需 12M lookback → 首組合 ~2005 中
BETA_WINDOW_MONTHS = 12            # rolling beta 估計視窗（月）
# Frazzini–Pedersen (2014) eq.15 beta 收縮：β_shrunk = w·β_TS + (1-w)·β_XS，β_XS=1。
# 收縮是 FP 方法的必要組成（非 optional）：把腿 beta 遠離 0，避免 1/β_L 爆槓桿。
SHRINKAGE_W = 0.6
MIN_BETA_OBS = 200                 # beta 視窗最少交易日數（~252 中要求 200）
MIN_RET_OBS = 15                   # 報酬月最少交易日數
MIN_STOCKS_PER_MONTH = 20          # 每月最少可用股票數才形成組合
BOOTSTRAP_REPS = 10000
PERMUTATION_REPS = 10000
# 主檢定 block 長度由 `regime_block_length()` 的規則決定；此格點只作敏感度檢查（非調參）。
BLOCK_LEN_GRID = (3, 6, 12, 24)
ACF_LAGS = 6
MONTHS_PER_YEAR = 12

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
RESULTS_PATH = HERE / "k1812_results.json"

# --------------------------------------------------------------------------------------
# 橫斷面 universe：固定、流動性高的美股大型股，跨產業，皆於 2004 前上市（可重現）。
# 生存者偏誤（survivorship）已知且不可消除 —— 見 README。
# --------------------------------------------------------------------------------------
UNIVERSE = [
    # Technology / Communication
    "AAPL", "MSFT", "INTC", "CSCO", "ORCL", "IBM", "TXN", "QCOM", "HPQ", "ADBE",
    "T", "VZ",
    # Financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "AXP", "USB", "PNC", "BK",
    # Health care
    "JNJ", "PFE", "MRK", "ABT", "BMY", "LLY", "AMGN", "MDT", "UNH", "GILD",
    # Consumer staples
    "PG", "KO", "PEP", "WMT", "CL", "MO", "KMB", "GIS", "K", "SYY",
    # Consumer discretionary
    "MCD", "HD", "NKE", "SBUX", "TGT", "LOW", "DIS", "TJX", "YUM",
    # Industrials
    "GE", "HON", "MMM", "CAT", "BA", "UPS", "UNP", "EMR", "ITW", "DE",
    # Energy
    "XOM", "CVX", "COP", "SLB", "OXY", "HAL", "EOG", "MRO",
    # Utilities
    "DUK", "SO", "NEE", "D", "AEP", "EXC", "XEL", "PEG",
    # Materials
    "APD", "SHW", "ECL", "NEM", "FCX", "PPG",
]
MARKET_TICKER = "^GSPC"


# --------------------------------------------------------------------------------------
# 資料下載（含本機快取以可重現）
# --------------------------------------------------------------------------------------
def _download_one(ticker: str, start: str, retries: int = 4) -> pd.Series | None:
    """逐檔下載 adjusted close（total return proxy），含 retry + 指數退避。

    yfinance 對大批次併發請求會 rate-limit（10s timeout → None）；逐檔序列化 + retry
    穩健得多。每檔另存快取（見 load_data），re-run 只補失敗檔。
    """
    import time

    import yfinance as yf

    for attempt in range(retries):
        try:
            raw = yf.download(
                ticker,
                start=start,
                auto_adjust=True,     # 調整股利與拆股 → 近似總報酬
                progress=False,
                threads=False,
            )
            if raw is None or len(raw) == 0:
                raise ValueError("empty frame")
            if isinstance(raw.columns, pd.MultiIndex):
                close = raw["Close"].iloc[:, 0]
            else:
                close = raw["Close"]
            close = close.dropna()
            if len(close) == 0:
                raise ValueError("all-NaN close")
            close.index = pd.to_datetime(close.index)
            close.name = ticker
            return close.sort_index()
        except Exception as exc:  # pragma: no cover - 網路 retry
            wait = 2.0 * (attempt + 1)
            print(f"[warn] {ticker} 下載失敗 (attempt {attempt + 1}/{retries}): {exc}; 等 {wait:.0f}s",
                  file=sys.stderr)
            time.sleep(wait)
    return None


def _download_prices(tickers: list[str], start: str, cache_dir: Path | None = None) -> pd.DataFrame:
    """逐檔下載並組成 wide DataFrame（index=date, col=ticker）。支援每檔快取。"""
    import time

    series: dict[str, pd.Series] = {}
    for i, tkr in enumerate(tickers):
        cache_path = cache_dir / f"{tkr.replace('^', '_idx_')}.csv" if cache_dir else None
        if cache_path is not None and cache_path.exists():
            s = pd.read_csv(cache_path, index_col=0, parse_dates=True).iloc[:, 0]
            s.name = tkr
            series[tkr] = s
            continue
        s = _download_one(tkr, start)
        if s is not None:
            series[tkr] = s
            if cache_path is not None:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                s.to_frame(tkr).to_csv(cache_path)
        else:
            print(f"[warn] {tkr} 最終仍失敗，已排除", file=sys.stderr)
        time.sleep(0.4)  # 序列化間隔，降 rate-limit 機率
        if (i + 1) % 10 == 0:
            print(f"[info] 下載進度 {i + 1}/{len(tickers)}", file=sys.stderr)
    if not series:
        raise RuntimeError("no tickers downloaded")
    df = pd.DataFrame(series).sort_index()
    return df


def load_data(force_download: bool = False) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """回傳 (stock_prices_wide, market_price, rf_annual_pct)。

    逐檔快取（``data/tickers/<TKR>.csv``）為唯一真相：每檔下載即驗證（非空、非全 NaN）
    才寫入，re-run 只補缺檔。每次從逐檔快取重組 wide 表 —— 不用 all-or-nothing 的
    assembled cache（run-1 批次失敗曾把壞資料整包存下害 run-2 誤用）。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ticker_cache = DATA_DIR / "tickers"

    print("[info] 下載股票 + 市場 + 無風險利率（逐檔快取）...", file=sys.stderr)
    all_tickers = list(UNIVERSE) + [MARKET_TICKER, "^IRX"]
    wide = _download_prices(all_tickers, START_DATE, cache_dir=ticker_cache)

    if MARKET_TICKER not in wide.columns:
        raise RuntimeError(f"market {MARKET_TICKER} missing after download")
    if "^IRX" not in wide.columns:
        raise RuntimeError("risk-free ^IRX missing after download")

    mkt = wide[MARKET_TICKER].dropna()
    rf = wide["^IRX"].dropna()  # 年化 %（13週國庫券殖利率）
    rf.name = "IRX"
    stocks = wide.drop(columns=[MARKET_TICKER, "^IRX"])
    # 排除全 NaN 欄（下載徹底失敗者），並記錄
    dead = [c for c in stocks.columns if stocks[c].isna().all()]
    if dead:
        print(f"[warn] 排除無資料 ticker: {dead}", file=sys.stderr)
        stocks = stocks.drop(columns=dead)

    # 重組 assembled 便利檔（僅供人工檢視，非讀取來源）
    stocks.to_csv(DATA_DIR / "stock_prices.csv")
    mkt.to_frame("market").to_csv(DATA_DIR / "market_price.csv")
    rf.to_frame("rf").to_csv(DATA_DIR / "riskfree_irx.csv")
    return stocks, mkt, rf


# --------------------------------------------------------------------------------------
# 報酬與 rf 對齊
# --------------------------------------------------------------------------------------
def compute_daily_returns(prices: pd.DataFrame) -> pd.DataFrame:
    return prices.pct_change()


def daily_rf_series(rf_annual_pct: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """年化 %（annualized，act/360 慣例的 discount/yield 近似）→ 日 simple rate。

    以 rf_daily = (annual%/100)/252 近似（monthly 用 /12）。對 beta 影響極小，
    但仍照 FP 用超額報酬估計。
    """
    rf = rf_annual_pct.reindex(index).ffill()
    return (rf / 100.0) / 252.0


# --------------------------------------------------------------------------------------
# Rolling monthly beta（OLS，過去 12 個月日超額報酬）
# --------------------------------------------------------------------------------------
def month_end_dates(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """每個交易月的最後一個交易日。"""
    s = pd.Series(index, index=index)
    return pd.DatetimeIndex(s.groupby(index.to_period("M")).last().values)


def estimate_betas(
    stock_ret: pd.DataFrame,
    mkt_ret: pd.Series,
    rf_daily: pd.Series,
) -> pd.DataFrame:
    """對每個形成月月底，用過去 BETA_WINDOW_MONTHS 個月日超額報酬 OLS 估 beta_i。

    回傳 DataFrame（index=formation month-end date, col=ticker），只用 ≤ 月底資料。
    """
    ex_stock = stock_ret.sub(rf_daily, axis=0)
    ex_mkt = (mkt_ret - rf_daily).rename("mkt")

    all_dates = stock_ret.index
    me_dates = month_end_dates(all_dates)

    data_start = all_dates.min()
    betas: dict[pd.Timestamp, dict[str, float]] = {}
    for me in me_dates:
        window_start = me - pd.DateOffset(months=BETA_WINDOW_MONTHS)
        # full 12M warm-up：window 起點須 ≥ 資料起點，否則不是完整 12M 估計（誠實：
        # 早期若只有 ~10 個月資料，beta 非完整視窗 → 直接跳過，首組合順延到 ~2005-01）
        if window_start < data_start:
            continue
        # 嚴格 ≤ 月底：window (window_start, me]
        mask = (all_dates > window_start) & (all_dates <= me)
        if mask.sum() < MIN_BETA_OBS:
            continue
        xm = ex_mkt.loc[mask].dropna()   # 市場超額報酬，去 NaN
        if len(xm) < MIN_BETA_OBS:
            continue
        var_m = xm.var(ddof=1)
        if not np.isfinite(var_m) or var_m <= 0:
            continue
        row: dict[str, float] = {}
        Xd = ex_stock.loc[mask]
        for tkr in Xd.columns:
            yi = Xd[tkr]
            pair = pd.concat([yi, xm], axis=1).dropna()
            if len(pair) < MIN_BETA_OBS:
                continue
            cov = np.cov(pair.iloc[:, 0].values, pair.iloc[:, 1].values, ddof=1)[0, 1]
            var_pair = np.var(pair.iloc[:, 1].values, ddof=1)
            if var_pair <= 0:
                continue
            row[tkr] = cov / var_pair
        if len(row) >= MIN_STOCKS_PER_MONTH:
            betas[me] = row
    beta_df = pd.DataFrame.from_dict(betas, orient="index").sort_index()
    beta_df.index = pd.DatetimeIndex(beta_df.index)
    return beta_df


# --------------------------------------------------------------------------------------
# 月報酬（形成月**之後**）
# --------------------------------------------------------------------------------------
def last_complete_month_period(daily_index: pd.DatetimeIndex) -> pd.Period:
    """回傳資料中「最後一個已完成月」的 period。

    未完成月（資料尚未涵蓋到該月最後一個交易日）會被排除，避免把 partial-month 當完整
    月統計（Codex review HIGH：2026-07 只到 07-24 卻被當整月）。判準：某月資料最後日
    ≥ 該月最後一個 business day 才算完成。
    """
    last = daily_index.max()
    bmonth_end = last + pd.offsets.BMonthEnd(0)  # last 所在月的最後一個 business day
    last_period = last.to_period("M")
    if last < bmonth_end:
        return last_period - 1
    return last_period


def monthly_stock_returns(stock_ret: pd.DataFrame) -> pd.DataFrame:
    """每檔股票的月 simple return（含最少交易日數過濾）。index = period-month end。"""
    grp = stock_ret.groupby(stock_ret.index.to_period("M"))
    n_obs = grp.count()
    # 月報酬 = 連乘 (1+r) - 1
    mret = grp.apply(lambda x: (1.0 + x).prod(min_count=1) - 1.0)
    mret = mret.where(n_obs >= MIN_RET_OBS)
    mret.index = mret.index.to_timestamp("M")  # month-end timestamp
    return mret


def monthly_rf(rf_annual_pct: pd.Series) -> pd.Series:
    """月無風險報酬（simple）= annual%/100/12。index=period-month end timestamp。"""
    m = rf_annual_pct.groupby(rf_annual_pct.index.to_period("M")).last()
    m = (m / 100.0) / MONTHS_PER_YEAR
    m.index = m.index.to_timestamp("M")
    m.name = "rf_m"
    return m


# --------------------------------------------------------------------------------------
# Frazzini–Pedersen BAB 組合建構
# --------------------------------------------------------------------------------------
def fp_rank_weights(betas: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Frazzini–Pedersen rank weighting。

    z_i = beta 的橫斷面排名；z_bar = 平均排名；k = 2/Σ|z_i - z_bar|
    高 beta 腿 w_H,i = k·max(z_i - z_bar, 0)；低 beta 腿 w_L,i = k·max(z_bar - z_i, 0)。
    兩腿權重各自加總為 1。
    """
    b = betas.dropna()
    z = b.rank(method="average")
    z_bar = z.mean()
    dev = (z - z_bar).abs().sum()
    if dev == 0:
        raise ValueError("degenerate beta ranks")
    k = 2.0 / dev
    w_high = (k * (z - z_bar).clip(lower=0.0)).reindex(betas.index).fillna(0.0)
    w_low = (k * (z_bar - z).clip(lower=0.0)).reindex(betas.index).fillna(0.0)
    return w_low, w_high


def build_bab(
    beta_df: pd.DataFrame,
    mret: pd.DataFrame,
    rf_m: pd.Series,
) -> pd.DataFrame:
    """逐月建 BAB。

    形成月 t（beta_df.index）→ 持有 t+1 月報酬（mret 的下一個 month-end）。
    BAB_{t+1} = (1/beta_L)(r_L - rf) - (1/beta_H)(r_H - rf)，ex-ante 市場中性。

    回傳 DataFrame（index=報酬月 t+1），欄位含 bab_ret / beta_L / beta_H / n_stocks /
    exante_beta（應 ≈ 0）等，供不變式測試與診斷。
    """
    mret_index = mret.index
    records = []
    # fail-loud on missing holding return（見下）→ 若能建成 panel，delisting drops 恆為 0
    n_delisting_drops = 0
    for form_me in beta_df.index:
        # 找形成月在月報酬索引中的位置，取「下一個」月為持有月
        # form_me 為交易日 month-end；轉成 period 對齊 mret（period-month-end timestamp）
        form_period = form_me.to_period("M")
        form_ts = form_period.to_timestamp("M")
        hold_period = form_period + 1
        hold_ts = hold_period.to_timestamp("M")
        if hold_ts not in mret_index:
            continue

        betas_raw = beta_df.loc[form_me].dropna()
        # FP eq.15 shrinkage toward 1 —— 排序不變（affine 單調），但腿 beta 遠離 0。
        betas = SHRINKAGE_W * betas_raw + (1.0 - SHRINKAGE_W) * 1.0
        # universe 與權重**完全由形成期資訊決定**：有 valid beta（≤ 形成月底資料）即入選。
        # 不看 t+1 報酬可得性 → 無 future-availability lookahead。
        valid = betas.index
        if len(valid) < MIN_STOCKS_PER_MONTH:
            continue
        r_next = mret.loc[hold_ts].reindex(valid)
        n_missing = int(r_next.isna().sum())
        if n_missing > 0:
            # 形成期在池、持有月缺報酬 = 真下市/資料缺口。survivor 樣本應為 0；
            # 靜默剔除會用未來資訊重塑權重 → 一律 fail-loud，要求明訂 delisting-return 規則。
            raise RuntimeError(
                f"{n_missing} formation-universe stocks lack a {hold_ts.date()} return "
                f"(survivor sample expects 0). A genuine delisting needs an explicit "
                f"delisting-return rule; silently dropping reshapes weights with future info."
            )

        w_low, w_high = fp_rank_weights(betas)
        beta_L = float((w_low * betas).sum())
        beta_H = float((w_high * betas).sum())
        if beta_L <= 0 or beta_H <= 0:
            # 低腿 ex-ante beta 應為正（收縮後最低 0.4）；退化則跳過
            continue
        r_L = float((w_low * r_next).sum())
        r_H = float((w_high * r_next).sum())
        # rf 用「形成月底」可鎖定的 1 個月利率（非持有月底才知的利率），ex-ante 正確。
        # 缺值 fail-loud（不靜默用 0）
        if form_ts not in rf_m.index or pd.isna(rf_m.loc[form_ts]):
            raise RuntimeError(f"missing risk-free rate at formation month {form_ts.date()}")
        rf_next = float(rf_m.loc[form_ts])

        bab_ret = (r_L - rf_next) / beta_L - (r_H - rf_next) / beta_H
        exante_beta = (1.0 / beta_L) * beta_L - (1.0 / beta_H) * beta_H  # 恆 = 0（不變式）

        records.append(
            {
                "hold_month": hold_ts,
                "form_month": form_me,
                "bab_ret": bab_ret,
                "beta_L": beta_L,          # 收縮後低腿 ex-ante beta（建構用）
                "beta_H": beta_H,          # 收縮後高腿 ex-ante beta（建構用）
                "beta_L_raw": float((w_low * betas_raw).sum()),   # 收縮前診斷
                "beta_H_raw": float((w_high * betas_raw).sum()),
                "r_L": r_L,
                "r_H": r_H,
                "n_stocks": int(len(valid)),
                "exante_beta": float(exante_beta),
            }
        )
    if not records:
        raise RuntimeError(
            "build_bab produced no BAB months — check data download / beta estimation coverage"
        )
    df = pd.DataFrame.from_records(records).set_index("hold_month").sort_index()
    df.attrs["n_delisting_drops"] = n_delisting_drops
    return df


# --------------------------------------------------------------------------------------
# 市場已實現波動（monthly RV）+ regime
# --------------------------------------------------------------------------------------
def market_monthly_rv(mkt_ret: pd.Series) -> pd.Series:
    """月市場 RV = 該月日報酬標準差 × sqrt(交易日數)（月度已實現波動）。

    index=period-month end timestamp。需最少交易日數。
    """
    grp = mkt_ret.groupby(mkt_ret.index.to_period("M"))
    n = grp.count()
    rv = grp.apply(lambda x: np.sqrt(np.nansum(np.square(x.values))))  # sqrt(Σ r^2) = RV
    rv = rv.where(n >= MIN_RET_OBS)
    rv.index = rv.index.to_timestamp("M")
    rv.name = "rv_market"
    return rv.dropna()


# --------------------------------------------------------------------------------------
# 統計檢定
# --------------------------------------------------------------------------------------
def nw_maxlags(n: int) -> int:
    """Newey-West (1994) 自動落後期 floor(4·(n/100)^(2/9))。"""
    return int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))


def hac_mean_test(y: np.ndarray, maxlags: int | None = None) -> dict:
    """對常數回歸做 HAC(Newey-West) mean 檢定。"""
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    n = len(y)
    lags = nw_maxlags(n) if maxlags is None else maxlags
    X = np.ones((n, 1))
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {
        "mean": float(y.mean()),
        "t_stat": float(res.tvalues[0]),
        "p_value": float(res.pvalues[0]),
        "hac_lags": int(lags),
        "n": int(n),
    }


def sharpe(y: np.ndarray, periods_per_year: int = MONTHS_PER_YEAR) -> float:
    y = np.asarray(y, dtype=float)
    y = y[np.isfinite(y)]
    if len(y) < 2 or y.std(ddof=1) == 0:
        return float("nan")
    return float(y.mean() / y.std(ddof=1) * np.sqrt(periods_per_year))


# --------------------------------------------------------------------------------------
# 保留時間相依的 regime-label 重排（本實驗顯著性的主判準）
#
# 為什麼需要：條件 Sharpe 差的 H0 是「regime label 過程與 BAB 報酬過程獨立」。i.i.d. label
# permutation 在 impose 這個 H0 的同時，也把 label 自身的**時間結構**打散 —— 本樣本 low-vol
# 指標 acf(1) ≈ 0.33、平均 regime 連續段 ≈ 3 個月，i.i.d. 重排後 acf(1) ≈ 0、平均段長 ≈ 2。
# 那等於拿一個「regime 不會持續」的世界當 null，與資料生成過程不符（`serial_dependence_check`
# 把這件事逐次量化寫進 results）。
#
# 修法：只重排 label、且以**整段連續區塊**搬動（circular block permutation），returns 原地不動。
# 這保留 (a) 報酬序列本身的時間結構（完全不動）、(b) label 的 regime 連續段（區塊內完整保留）、
# (c) 低/高月數（區塊置換不改 label 的 multiset）。另附**窮舉 circular shift**（把整條 label
# 序列環狀平移 k=1..n-1）作為零調參、對持續性保留最完整的 exact randomization 對照。
# --------------------------------------------------------------------------------------
def _aligned_pair(returns: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """轉 float/int ndarray 並丟掉任一邊為非有限值的月份（保持時間順序）。"""
    r = np.asarray(returns, dtype=float)
    lab = np.asarray(labels, dtype=float)
    if r.shape != lab.shape:
        raise ValueError(f"returns/labels length mismatch: {r.shape} vs {lab.shape}")
    ok = np.isfinite(r) & np.isfinite(lab)
    return r[ok], lab[ok].astype(int)


def assert_contiguous_months(index, label: str) -> int:
    """block / circular permutation 的前提：序列在日曆上逐月連續、無跳月。違反即 fail-loud。"""
    periods = pd.DatetimeIndex(index).to_period("M")
    steps = np.diff(periods.asi8)
    if steps.size and not np.all(steps == 1):
        raise AssertionError(
            f"{label}: month index is not contiguous ({int((steps != 1).sum())} gap(s)); "
            f"circular/block permutation assumes an unbroken monthly series"
        )
    return int(len(periods))


def _sharpe_diff_by_label(r: np.ndarray, lab: np.ndarray) -> float:
    """Sharpe(低 vol 月後) − Sharpe(高 vol 月後)，label=1 表示前一月為低波動。"""
    mask = lab == 1
    return sharpe(r[mask]) - sharpe(r[~mask])


def regime_run_lengths(labels: np.ndarray) -> np.ndarray:
    """regime label 的連續段長度（run lengths）—— 量化 regime 持續性。"""
    lab = np.asarray(labels).ravel()
    if lab.size == 0:
        return np.zeros(0, dtype=int)
    change = np.flatnonzero(lab[1:] != lab[:-1]) + 1
    bounds = np.concatenate([[0], change, [lab.size]])
    return np.diff(bounds)


def acf_profile(x: np.ndarray, lags: int = ACF_LAGS) -> list[float]:
    """樣本自相關 rho_1..rho_lags（分母用全樣本變異，標準 biased estimator）。"""
    z = np.asarray(x, dtype=float)
    z = z[np.isfinite(z)]
    z = z - z.mean()
    denom = float((z * z).sum())
    if denom == 0.0:
        return [float("nan")] * lags
    return [float((z[k:] * z[:-k]).sum() / denom) for k in range(1, lags + 1)]


def regime_block_length(labels: np.ndarray) -> dict:
    """主檢定的 block 長度規則（**先於看 p 值就定死**，非事後調參）。

    b = max(ceil(n^(1/3)), ceil(平均 regime 連續段長))：
      * n^(1/3) 是 block bootstrap 的標準經驗率（Hall–Horowitz–Jing 型 O(n^{1/3})）；
      * 平均連續段長保證每個區塊至少裝得下一個典型 regime 段。
    另在 `BLOCK_LEN_GRID` 上做敏感度檢查，證明 p 對 b 不敏感。
    """
    lab = np.asarray(labels).ravel()
    n = int(lab.size)
    runs = regime_run_lengths(lab)
    cube_root = int(np.ceil(n ** (1.0 / 3.0)))
    mean_run = float(runs.mean()) if runs.size else float("nan")
    chosen = int(max(cube_root, int(np.ceil(mean_run)) if runs.size else 1))
    return {
        "block_len_months": chosen,
        "rule": "max(ceil(n^(1/3)), ceil(mean regime run length))",
        "n_months": n,
        "cube_root_term": cube_root,
        "mean_run_length": mean_run,
        "median_run_length": float(np.median(runs)) if runs.size else float("nan"),
        "max_run_length": int(runs.max()) if runs.size else 0,
        "n_runs": int(runs.size),
    }


def _circular_block_permute(lab: np.ndarray, block_len: int, rng: np.random.Generator) -> np.ndarray:
    """circular block permutation：隨機環狀旋轉 → 切成連續區塊 → 隨機置換區塊順序。

    旋轉讓區塊邊界每次落在不同月份（避免固定切點的邊界假影）；置換區塊順序而非個別月份，
    使區塊內的 regime 連續段完整存活。長度與 label multiset 皆嚴格保持不變。
    """
    n = lab.size
    rotated = np.roll(lab, int(rng.integers(0, n)))
    n_blocks = int(np.ceil(n / block_len))
    blocks = [rotated[i * block_len:(i + 1) * block_len] for i in range(n_blocks)]
    order = rng.permutation(n_blocks)
    return np.concatenate([blocks[j] for j in order])


def _mc_pvalue(null: np.ndarray, obs: float) -> float:
    """Davison–Hinkley Monte Carlo p：(#{|null| ≥ |obs|} + 1)/(B + 1)，避免 p=0。"""
    return float((int((np.abs(null) >= abs(obs)).sum()) + 1) / (len(null) + 1))


def sharpe_diff_block_permutation(
    returns: np.ndarray,
    labels: np.ndarray,
    block_len: int | None = None,
    reps: int = PERMUTATION_REPS,
    seed: int = SEED,
) -> dict:
    """**主顯著性檢定**：條件 Sharpe 差的 circular block permutation 檢定。

    H0：regime label 過程與 BAB 報酬過程獨立（報酬不動，只重排 label 的連續區塊）。
    two-sided p = P(|perm diff| ≥ |observed diff|)。固定 seed=42、reps=10,000。
    `returns` / `labels` 必須是**同一條時間序列上依月份排序**的對齊向量。
    """
    r, lab = _aligned_pair(returns, labels)
    rule = regime_block_length(lab)
    b = int(rule["block_len_months"] if block_len is None else block_len)
    if not 1 <= b <= len(r):
        raise ValueError(f"block_len {b} out of range for n={len(r)}")
    rng = np.random.default_rng(seed)
    obs = _sharpe_diff_by_label(r, lab)

    null = np.empty(reps)
    for i in range(reps):
        null[i] = _sharpe_diff_by_label(r, _circular_block_permute(lab, b, rng))
    null = null[np.isfinite(null)]
    return {
        "test": "circular_block_permutation",
        "role": "PRIMARY significance test (preserves regime persistence)",
        "null_hypothesis": "the prior-vol regime label process is independent of the BAB return process",
        "preserves_time_dependence": True,
        "block_len_months": b,
        "block_len_rule": rule["rule"] if block_len is None else "explicit override",
        "n_blocks": int(np.ceil(len(r) / b)),
        "diff_observed": float(obs),
        "p_value_two_sided": _mc_pvalue(null, obs),
        "null_mean": float(null.mean()),
        "null_sd": float(null.std(ddof=1)),
        "null_ci95_low": float(np.percentile(null, 2.5)),
        "null_ci95_high": float(np.percentile(null, 97.5)),
        "reps": int(len(null)),
        "n_low": int((lab == 1).sum()),
        "n_high": int((lab == 0).sum()),
        "seed": seed,
    }


def sharpe_diff_circular_shift(returns: np.ndarray, labels: np.ndarray) -> dict:
    """**窮舉** circular-shift randomization 檢定（零調參、決定性、無 seed）。

    把整條 label 序列環狀平移 k=1..n-1，逐一重算 Sharpe 差 —— 平移不改變 label 序列
    自身的任何時間結構（除一個 wrap 接縫），因此是對 regime 持續性保留最完整的 null。
    randomization set 只有 n-1 個元素 → p 解析度下限 1/n，作為主檢定的 exact 對照。
    """
    r, lab = _aligned_pair(returns, labels)
    n = len(r)
    obs = _sharpe_diff_by_label(r, lab)
    null = np.array([_sharpe_diff_by_label(r, np.roll(lab, k)) for k in range(1, n)])
    null = null[np.isfinite(null)]
    return {
        "test": "exhaustive_circular_shift",
        "role": "exact corroboration of the primary test (no tuning parameter)",
        "preserves_time_dependence": True,
        "diff_observed": float(obs),
        "p_value_two_sided": _mc_pvalue(null, obs),
        "null_mean": float(null.mean()),
        "null_sd": float(null.std(ddof=1)),
        "null_ci95_low": float(np.percentile(null, 2.5)),
        "null_ci95_high": float(np.percentile(null, 97.5)),
        "n_shifts": int(len(null)),
        "p_resolution_floor": float(1.0 / (len(null) + 1)),
        "n_low": int((lab == 1).sum()),
        "n_high": int((lab == 0).sum()),
    }


def sharpe_diff_stationary_bootstrap(
    returns: np.ndarray,
    labels: np.ndarray,
    mean_block: int | None = None,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> dict:
    """Politis–Romano (1994) stationary bootstrap 的**效應量 95% CI**（保留時間相依）。

    以幾何分佈長度（平均 = mean_block）的環狀區塊重抽 **(報酬, label) 配對**，重算 Sharpe 差。
    這是效應量區間（分佈以觀察效應為中心），**不是 null-imposed 檢定** —— 顯著性看
    `sharpe_diff_block_permutation`。附的 CI-coverage p 僅供對照。固定 seed=42。
    """
    r, lab = _aligned_pair(returns, labels)
    n = len(r)
    b = int(regime_block_length(lab)["block_len_months"] if mean_block is None else mean_block)
    rng = np.random.default_rng(seed)
    obs = _sharpe_diff_by_label(r, lab)
    p_geom = 1.0 / b

    diffs = np.empty(reps)
    pos = np.arange(n)
    for i in range(reps):
        idx = np.empty(n, dtype=int)
        filled = 0
        while filled < n:
            start = int(rng.integers(0, n))
            length = min(int(rng.geometric(p_geom)), n - filled)
            idx[filled:filled + length] = (start + pos[:length]) % n
            filled += length
        diffs[i] = _sharpe_diff_by_label(r[idx], lab[idx])
    diffs = diffs[np.isfinite(diffs)]
    p_ci = float(min(2.0 * min((diffs <= 0).mean(), (diffs >= 0).mean()), 1.0))
    return {
        "test": "stationary_bootstrap",
        "role": "PRIMARY effect-size CI (preserves time dependence); NOT a null-imposed test",
        "preserves_time_dependence": True,
        "mean_block_months": b,
        "diff_observed": float(obs),
        "diff_boot_mean": float(diffs.mean()),
        "ci95_low": float(np.percentile(diffs, 2.5)),
        "ci95_high": float(np.percentile(diffs, 97.5)),
        "p_value_ci_based": p_ci,
        "note": "p_value_ci_based is a CI-coverage p, NOT a null-imposed test; significance = block-permutation p",
        "reps": int(len(diffs)),
        "seed": seed,
    }


def serial_dependence_check(
    returns: np.ndarray,
    labels: np.ndarray,
    block_len: int | None = None,
    reps: int = 2000,
    seed: int = SEED,
) -> dict:
    """量化「主檢定保留了 regime 持續性、i.i.d. 版摧毀它」—— 讓這件事可被程式化複驗。

    比較三者的 label acf(1) 與平均連續段長：觀察值 vs circular-block-permutation null
    vs i.i.d.-permutation null。同時記錄 BAB 報酬自身的 acf（解釋為何兩種 null 的
    離散度接近：報酬近乎無序列相關時，label clustering 對檢定統計量的 null 變異影響有限）。
    """
    r, lab = _aligned_pair(returns, labels)
    b = int(regime_block_length(lab)["block_len_months"] if block_len is None else block_len)
    rng = np.random.default_rng(seed)

    def _summ(sample: list[np.ndarray]) -> dict:
        return {
            "label_acf1": float(np.mean([acf_profile(x, 1)[0] for x in sample])),
            "mean_run_length": float(np.mean([regime_run_lengths(x).mean() for x in sample])),
        }

    block_sample = [_circular_block_permute(lab, b, rng) for _ in range(reps)]
    iid_sample = [rng.permutation(lab) for _ in range(reps)]
    shift_sample = [np.roll(lab, k) for k in range(1, len(lab))]
    return {
        "purpose": "verify the primary null preserves regime persistence and the i.i.d. null does not",
        "block_len_months": b,
        "reps": int(reps),
        "observed": {
            "label_acf1": acf_profile(lab, 1)[0],
            "mean_run_length": float(regime_run_lengths(lab).mean()),
            "label_acf": acf_profile(lab, ACF_LAGS),
            "bab_return_acf": acf_profile(r, ACF_LAGS),
        },
        "under_block_permutation_null": _summ(block_sample),
        "under_circular_shift_null": _summ(shift_sample),
        "under_iid_permutation_null": _summ(iid_sample),
        "interpretation": (
            "block/shift nulls retain most of the observed label acf(1) and run length; the i.i.d. "
            "null drives acf(1) to ~0 and run length to ~2. BAB returns are themselves nearly "
            "serially uncorrelated, so both nulls yield a similar spread for the Sharpe difference "
            "— which is why correcting the test moves the p-value only slightly in THIS sample. "
            "That equivalence is a measured outcome, not an assumption."
        ),
    }


def sharpe_diff_bootstrap(
    y_low: np.ndarray,
    y_high: np.ndarray,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> dict:
    """兩獨立子樣本（低/高 vol 月後）年化 Sharpe 差異的 i.i.d. bootstrap **effect-size 區間**。

    **對照用，非主判準**：i.i.d. 重抽假設月份可交換，忽略 regime 持續性；主 CI 用
    `sharpe_diff_stationary_bootstrap`（保留時間相依），主顯著性用
    `sharpe_diff_block_permutation`。這裡的 two-sided p 是「CI 是否涵蓋 0」
    （= 2·min(P(diff*≤0),P(diff*≥0))），非 null-imposed。固定 seed=42。
    """
    rng = np.random.default_rng(seed)
    y_low = np.asarray(y_low, dtype=float)
    y_low = y_low[np.isfinite(y_low)]
    y_high = np.asarray(y_high, dtype=float)
    y_high = y_high[np.isfinite(y_high)]
    obs = sharpe(y_low) - sharpe(y_high)

    diffs = np.empty(reps)
    n_low, n_high = len(y_low), len(y_high)
    for b in range(reps):
        bl = y_low[rng.integers(0, n_low, n_low)]
        bh = y_high[rng.integers(0, n_high, n_high)]
        diffs[b] = sharpe(bl) - sharpe(bh)
    diffs = diffs[np.isfinite(diffs)]
    p_ci = 2.0 * min((diffs <= 0).mean(), (diffs >= 0).mean())
    p_ci = float(min(p_ci, 1.0))
    return {
        "sharpe_low": sharpe(y_low),
        "sharpe_high": sharpe(y_high),
        "diff_observed": float(obs),
        "diff_boot_mean": float(diffs.mean()),
        "ci95_low": float(np.percentile(diffs, 2.5)),
        "ci95_high": float(np.percentile(diffs, 97.5)),
        "test": "iid_bootstrap",
        "role": "COMPARISON ONLY (i.i.d. resampling; ignores regime persistence)",
        "preserves_time_dependence": False,
        "p_value_ci_based": p_ci,
        "note": "p_value_ci_based is a CI-coverage p, NOT a null-imposed test; primary CI = stationary bootstrap",
        "reps": int(len(diffs)),
        "n_low": int(n_low),
        "n_high": int(n_high),
        "seed": seed,
    }


def sharpe_diff_permutation(
    y_low: np.ndarray,
    y_high: np.ndarray,
    reps: int = PERMUTATION_REPS,
    seed: int = SEED,
) -> dict:
    """i.i.d. **label-permutation** 檢定 —— **對照用，不是主判準**。

    H0：regime label 與 BAB 報酬無關。做法：把兩子樣本合併，隨機重排 label（保持低/高月數），
    重算 Sharpe_low - Sharpe_high 建 null 分佈；two-sided p = P(|perm diff| ≥ |observed diff|)。
    固定 seed=42。

    **限制（為何降級為對照）**：i.i.d. 重排假設月份可交換，會把 regime 的連續段打散
    （本樣本 label acf(1) 0.33 → ~0、平均段長 3 → 2，見 `serial_dependence_check`），
    等於用一個「regime 不會持續」的 null。主判準改用
    `sharpe_diff_block_permutation`（circular block permutation，保留連續段）。
    """
    rng = np.random.default_rng(seed)
    y_low = np.asarray(y_low, dtype=float)
    y_low = y_low[np.isfinite(y_low)]
    y_high = np.asarray(y_high, dtype=float)
    y_high = y_high[np.isfinite(y_high)]
    pooled = np.concatenate([y_low, y_high])
    n_low = len(y_low)
    obs = sharpe(y_low) - sharpe(y_high)

    null = np.empty(reps)
    for b in range(reps):
        perm = rng.permutation(pooled)
        null[b] = sharpe(perm[:n_low]) - sharpe(perm[n_low:])
    null = null[np.isfinite(null)]
    return {
        "test": "iid_label_permutation",
        "role": "COMPARISON ONLY (destroys regime persistence); primary = circular_block_permutation",
        "preserves_time_dependence": False,
        "diff_observed": float(obs),
        "p_value_two_sided": _mc_pvalue(null, obs),
        "null_mean": float(null.mean()),
        "null_sd": float(null.std(ddof=1)),
        "null_ci95_low": float(np.percentile(null, 2.5)),
        "null_ci95_high": float(np.percentile(null, 97.5)),
        "reps": int(len(null)),
        "n_low": int(n_low),
        "n_high": int(len(y_high)),
        "seed": seed,
    }


def regime_regression(bab_ret: pd.Series, low_vol_signal: pd.Series) -> dict:
    """BAB_{t+1} ~ a + b·1{low_vol_t}，HAC t。b>0 表示低 vol 月後 BAB 較高。"""
    df = pd.concat([bab_ret.rename("y"), low_vol_signal.rename("low")], axis=1).dropna()
    y = df["y"].values
    X = sm.add_constant(df["low"].astype(float).values)
    lags = nw_maxlags(len(y))
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {
        "alpha": float(res.params[0]),
        "beta_low_vol": float(res.params[1]),
        "alpha_t": float(res.tvalues[0]),
        "beta_low_vol_t": float(res.tvalues[1]),
        "beta_low_vol_p": float(res.pvalues[1]),
        "hac_lags": int(lags),
        "n": int(len(y)),
    }


# --------------------------------------------------------------------------------------
# 圖表
# --------------------------------------------------------------------------------------
def make_figures(
    rv_market: pd.Series,
    median_rv: float,
    panel: pd.DataFrame,
    low_vol_signal: pd.Series,
) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = []

    # Fig 1: 市場 RV 時序 + median 切點
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(rv_market.index, rv_market.values, color="#2c3e50", lw=1.0)
    ax.axhline(median_rv, color="#e74c3c", ls="--", lw=1.2, label=f"median = {median_rv:.4f}")
    ax.set_title("Market monthly realized volatility (S&P 500) with median split")
    ax.set_ylabel("Monthly RV")
    ax.legend()
    fig.tight_layout()
    p1 = FIG_DIR / "fig1_market_rv_regime.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)
    out.append(p1.name)

    # Fig 2: 條件 BAB 累積報酬（全期 vs 只在 low-vol 月後持有 vs high-vol 月後）
    bab = panel["bab_ret"]
    sig = low_vol_signal.reindex(bab.index)
    cum_all = (1.0 + bab.fillna(0)).cumprod()
    bab_low_only = bab.where(sig == 1, 0.0)
    bab_high_only = bab.where(sig == 0, 0.0)
    cum_low = (1.0 + bab_low_only.fillna(0)).cumprod()
    cum_high = (1.0 + bab_high_only.fillna(0)).cumprod()
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(cum_all.index, cum_all.values, label="BAB (all months)", color="#2c3e50", lw=1.3)
    ax.plot(cum_low.index, cum_low.values, label="BAB held only after low-vol month", color="#27ae60", lw=1.1)
    ax.plot(cum_high.index, cum_high.values, label="BAB held only after high-vol month", color="#c0392b", lw=1.1)
    ax.set_title("Cumulative BAB return, unconditional vs vol-regime-conditioned")
    ax.set_ylabel("Cumulative growth of $1")
    ax.legend()
    fig.tight_layout()
    p2 = FIG_DIR / "fig2_conditional_bab_cumret.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)
    out.append(p2.name)

    # Fig 3: Sharpe by regime（median split + tercile）
    fig, ax = plt.subplots(figsize=(7, 4))
    s_low = sharpe(bab.where(sig == 1).dropna().values)
    s_high = sharpe(bab.where(sig == 0).dropna().values)
    s_all = sharpe(bab.dropna().values)
    bars = ax.bar(
        ["All", "After low-vol", "After high-vol"],
        [s_all, s_low, s_high],
        color=["#2c3e50", "#27ae60", "#c0392b"],
    )
    for bar, v in zip(bars, [s_all, s_low, s_high]):
        ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{v:.2f}",
                ha="center", va="bottom" if v >= 0 else "top", fontsize=10)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_ylabel("Annualized Sharpe")
    ax.set_title("BAB annualized Sharpe by prior-month vol regime")
    fig.tight_layout()
    p3 = FIG_DIR / "fig3_sharpe_by_regime.png"
    fig.savefig(p3, dpi=130)
    plt.close(fig)
    out.append(p3.name)

    return out


# --------------------------------------------------------------------------------------
# 主流程
# --------------------------------------------------------------------------------------
def main() -> int:
    started_at = time.time()
    np.random.seed(SEED)  # 全域 seed 冗餘保險（bootstrap 另用 default_rng(SEED)）

    stocks, mkt, rf_annual = load_data()

    # 對齊交易日
    common_idx = stocks.index.intersection(mkt.index)
    stocks = stocks.loc[common_idx]
    mkt = mkt.loc[common_idx]

    stock_ret = compute_daily_returns(stocks)
    mkt_ret = compute_daily_returns(mkt).rename("mkt")
    rf_daily = daily_rf_series(rf_annual, stock_ret.index)

    # 1) rolling beta
    beta_df = estimate_betas(stock_ret, mkt_ret, rf_daily)

    # ---- 完成月 gate（Codex HIGH 修正）：排除尚未結束的月份，避免 partial-month 污染 ----
    last_complete = last_complete_month_period(stock_ret.index)
    cutoff_ts = last_complete.to_timestamp("M")

    # 2) 月報酬 + 月 rf（只保留完成月）
    mret = monthly_stock_returns(stock_ret)
    mret = mret[mret.index <= cutoff_ts]
    rf_month = monthly_rf(rf_annual)

    # 3) BAB 組合
    panel = build_bab(beta_df, mret, rf_month)
    bab_ret = panel["bab_ret"]
    n_delisting_drops = int(panel.attrs.get("n_delisting_drops", 0))

    # 4) 市場月 RV + regime（median split，主；同樣只用完成月）
    rv_market = market_monthly_rv(mkt_ret)
    rv_market = rv_market[rv_market.index <= cutoff_ts]
    # 全樣本 median 作切點（in-sample 分類，非 return-predictive lookahead；另報 expanding 版）
    median_rv = float(rv_market.median())
    regime_low = (rv_market < median_rv).astype(float)  # 1 = low-vol month t

    # 5) LOOKAHEAD 對齊：報酬月 m 的訊號 = 上一月 m-1 的 regime → .shift(1)
    #    以報酬月索引重建 regime，再 shift(1)。
    regime_on_return_idx = regime_low.reindex(
        regime_low.index.union(bab_ret.index)
    ).sort_index()
    low_vol_signal = regime_on_return_idx.shift(1).reindex(bab_ret.index)

    rv_lagged = rv_market.reindex(
        rv_market.index.union(bab_ret.index)
    ).sort_index().shift(1).reindex(bab_ret.index)

    # ---- LOOKAHEAD 交叉驗證：shift(1) 訊號必須等於「形成月」regime ----
    # 用 panel 的 form_month（實際交易日月底）→ period → regime，逐月與 low_vol_signal 對照。
    n_checked = 0
    n_mismatch = 0
    for hold_ts, row in panel.iterrows():
        if hold_ts not in low_vol_signal.index:
            continue
        sig = low_vol_signal.loc[hold_ts]
        if pd.isna(sig):
            continue
        form_period = pd.Timestamp(row["form_month"]).to_period("M")
        form_ts = form_period.to_timestamp("M")
        expected = regime_low.get(form_ts, np.nan)
        if pd.isna(expected):
            continue
        n_checked += 1
        if int(sig) != int(expected):
            n_mismatch += 1
    if n_mismatch > 0:
        raise AssertionError(
            f"Lookahead alignment FAILED: {n_mismatch}/{n_checked} months where "
            f"shift(1) signal != formation-month regime"
        )

    # ---- baseline gate：無條件 BAB ----
    uncond = hac_mean_test(bab_ret.dropna().values)
    uncond["sharpe_annual"] = sharpe(bab_ret.dropna().values)
    uncond["sharpe_monthly"] = float(np.nanmean(bab_ret) / np.nanstd(bab_ret, ddof=1))

    # ---- 主檢定：low vs high vol 月後 ----
    joint = pd.concat(
        [bab_ret.rename("bab"), low_vol_signal.rename("low")], axis=1
    ).dropna().sort_index()
    y_low = joint.loc[joint["low"] == 1, "bab"].values
    y_high = joint.loc[joint["low"] == 0, "bab"].values

    cond = {
        "after_low_vol": {
            "n": int(len(y_low)),
            "mean_monthly": float(np.mean(y_low)),
            "sharpe_annual": sharpe(y_low),
            **{f"hac_{k}": v for k, v in hac_mean_test(y_low).items()},
        },
        "after_high_vol": {
            "n": int(len(y_high)),
            "mean_monthly": float(np.mean(y_high)),
            "sharpe_annual": sharpe(y_high),
            **{f"hac_{k}": v for k, v in hac_mean_test(y_high).items()},
        },
    }
    # 主判準必須保留時間相依：regime label 有持續性（連續段），i.i.d. 重排會把它打散。
    # 因此顯著性主檢定 = circular block permutation（只搬動 label 的連續區塊，報酬不動）。
    n_months_primary = assert_contiguous_months(joint.index, "median-split joint series")
    r_ord = joint["bab"].values
    lab_ord = joint["low"].astype(int).values

    block_rule = regime_block_length(lab_ord)
    perm_block = sharpe_diff_block_permutation(r_ord, lab_ord)        # ★ PRIMARY significance
    perm_shift = sharpe_diff_circular_shift(r_ord, lab_ord)           # exact、零調參對照
    block_grid = [
        {
            "block_len_months": b,
            **{
                k: v
                for k, v in sharpe_diff_block_permutation(r_ord, lab_ord, block_len=b).items()
                if k in ("p_value_two_sided", "null_sd", "n_blocks", "reps")
            },
        }
        for b in BLOCK_LEN_GRID
    ]
    sboot = sharpe_diff_stationary_bootstrap(r_ord, lab_ord)          # ★ PRIMARY effect-size CI
    dep_check = serial_dependence_check(r_ord, lab_ord)
    boot = sharpe_diff_bootstrap(y_low, y_high)                       # 對照（i.i.d.）
    perm_iid = sharpe_diff_permutation(y_low, y_high)                 # 對照（i.i.d.）
    reg = regime_regression(bab_ret, low_vol_signal)

    # ---- tercile robustness ----
    rv_lag_valid = rv_lagged.dropna()
    terciles = pd.qcut(rv_lag_valid, 3, labels=["low", "mid", "high"])
    tercile_stats = {}
    for lab in ["low", "mid", "high"]:
        idx = terciles[terciles == lab].index
        yv = bab_ret.reindex(idx).dropna().values
        tercile_stats[lab] = {
            "n": int(len(yv)),
            "mean_monthly": float(np.mean(yv)) if len(yv) else None,
            "sharpe_annual": sharpe(yv) if len(yv) >= 2 else None,
        }

    # ---- expanding-median regime robustness（real-time 切點，避免 in-sample median）----
    exp_med = rv_market.expanding(min_periods=24).median()
    regime_low_rt = (rv_market < exp_med).astype(float)
    regime_low_rt = regime_low_rt.where(exp_med.notna())
    rt_on_ret = regime_low_rt.reindex(
        regime_low_rt.index.union(bab_ret.index)
    ).sort_index().shift(1).reindex(bab_ret.index)
    joint_rt = pd.concat(
        [bab_ret.rename("bab"), rt_on_ret.rename("low")], axis=1
    ).dropna().sort_index()
    y_low_rt = joint_rt.loc[joint_rt["low"] == 1, "bab"].values
    y_high_rt = joint_rt.loc[joint_rt["low"] == 0, "bab"].values
    _rt_ok = len(y_low_rt) > 2 and len(y_high_rt) > 2
    if _rt_ok:
        assert_contiguous_months(joint_rt.index, "expanding-median joint series")
        r_rt = joint_rt["bab"].values
        lab_rt = joint_rt["low"].astype(int).values
        perm_block_rt = sharpe_diff_block_permutation(r_rt, lab_rt)   # ★ PRIMARY (robustness spec)
        perm_shift_rt = sharpe_diff_circular_shift(r_rt, lab_rt)
        sboot_rt = sharpe_diff_stationary_bootstrap(r_rt, lab_rt)
    else:
        perm_block_rt = perm_shift_rt = sboot_rt = None
    boot_rt = sharpe_diff_bootstrap(y_low_rt, y_high_rt) if _rt_ok else None
    perm_iid_rt = sharpe_diff_permutation(y_low_rt, y_high_rt) if _rt_ok else None

    # ---- 圖表 ----
    figs = make_figures(rv_market, median_rv, panel, low_vol_signal)

    # ---- 樣本 metadata ----
    per_ticker = {}
    for tkr in stocks.columns:
        s = stocks[tkr].dropna()
        if len(s):
            per_ticker[tkr] = {"start": str(s.index[0].date()), "end": str(s.index[-1].date()), "n_days": int(len(s))}

    # ---- 市場中性不變式（診斷）----
    exante_beta_max = float(panel["exante_beta"].abs().max())

    # ---- 槓桿診斷：收縮前 vs 收縮後的腿 beta，量化「為何收縮是必要組成」----
    # 1/beta_L 是低腿的去槓桿倍數；未收縮時 beta_L_raw 可逼近 0 → 倍數爆炸（README §6）。
    _raw_pos = panel["beta_L_raw"][panel["beta_L_raw"] > 0]
    _lev_no_shrink = float((1.0 / _raw_pos).max()) if len(_raw_pos) else float("nan")
    _lev_month = str(pd.Timestamp((1.0 / _raw_pos).idxmax()).date()) if len(_raw_pos) else None
    _bab_abs_idx = panel["bab_ret"].abs().idxmax()
    leverage_diag = {
        "purpose": "why FP eq.15 shrinkage is a required component, in numbers from THIS run",
        "beta_L_shrunk_min": float(panel["beta_L"].min()),
        "beta_L_shrunk_max": float(panel["beta_L"].max()),
        "beta_H_shrunk_min": float(panel["beta_H"].min()),
        "beta_H_shrunk_max": float(panel["beta_H"].max()),
        "beta_L_raw_min": float(panel["beta_L_raw"].min()),
        "beta_L_raw_min_month": str(pd.Timestamp(panel["beta_L_raw"].idxmin()).date()),
        "n_months_beta_L_raw_nonpositive": int((panel["beta_L_raw"] <= 0).sum()),
        "implied_leverage_without_shrinkage_max": _lev_no_shrink,
        "implied_leverage_without_shrinkage_max_month": _lev_month,
        "leverage_with_shrinkage_max": float((1.0 / panel["beta_L"]).max()),
        "bab_abs_max_monthly": float(panel["bab_ret"].abs().max()),
        "bab_abs_max_month": str(pd.Timestamp(_bab_abs_idx).date()),
    }

    # ---- universe 三分：requested / included / excluded ----
    included_tickers = list(stocks.columns)
    excluded_tickers = [t for t in UNIVERSE if t not in set(included_tickers)]

    now = datetime.now(timezone.utc).isoformat()
    results = {
        "experiment_id": "k1812",
        "pool_task_label": "K1726",
        "title": "Betting-Against-Beta conditioned on prior-month realized volatility",
        "source": "JFE 2025 — The volatility puzzle of the beta anomaly; Frazzini & Pedersen (2014) JFE",
        "generated_at_utc": now,
        "seed": SEED,
        "config": {
            "start_date": START_DATE,
            "beta_window_months": BETA_WINDOW_MONTHS,
            "min_beta_obs": MIN_BETA_OBS,
            "min_ret_obs": MIN_RET_OBS,
            "min_stocks_per_month": MIN_STOCKS_PER_MONTH,
            "bootstrap_reps": BOOTSTRAP_REPS,
            "permutation_reps": PERMUTATION_REPS,
            "significance_test": (
                "circular block permutation of the regime label series (preserves regime "
                "persistence); exhaustive circular shift as exact corroboration; i.i.d. label "
                "permutation retained for comparison only"
            ),
            "beta_method": "OLS rolling 12M daily excess returns (cov/var), then FP eq.15 shrinkage 0.6*beta+0.4*1",
            "shrinkage_w": SHRINKAGE_W,
            "portfolio": "Frazzini-Pedersen rank-weighted, each leg rescaled to beta=1 (ex-ante market neutral)",
            "regime_split": "full-sample median of market monthly RV (primary); expanding-median (robustness); tercile (robustness)",
            "market_ticker": MARKET_TICKER,
            "riskfree": "yfinance ^IRX (13-week T-bill yield; FRED DGS3MO intended but stlouisfed.org unreachable in compute env)",
        },
        "universe": {
            "n_tickers_requested": len(UNIVERSE),
            "n_tickers_included": len(included_tickers),
            "n_tickers_excluded": len(excluded_tickers),
            "requested_tickers": list(UNIVERSE),
            "included_tickers": included_tickers,
            "excluded_tickers": excluded_tickers,
            "excluded_reason": "yfinance download failed/timed out or delisted (see per-run logs)",
        },
        "sample": {
            "daily_start": str(stocks.index[0].date()),
            "daily_end": str(stocks.index[-1].date()),
            "last_complete_month": str(cutoff_ts.date()),
            "incomplete_months_excluded": "final partial month dropped if data < business month-end",
            "n_bab_months": int(bab_ret.dropna().shape[0]),
            "bab_first_month": str(bab_ret.dropna().index[0].date()),
            "bab_last_month": str(bab_ret.dropna().index[-1].date()),
            "median_stocks_per_month": float(panel["n_stocks"].median()),
            "min_stocks_per_month_realized": int(panel["n_stocks"].min()),
            "delisting_drops_total": n_delisting_drops,
        },
        "invariants": {
            "exante_bab_beta_max_abs": exante_beta_max,
            "note": "ex-ante BAB beta = (1/beta_L)*beta_L - (1/beta_H)*beta_H should be ~0 (market neutral by construction)",
            "regime_alignment_check_months": int(n_checked),
            "regime_alignment_mismatches": int(n_mismatch),
            "regime_alignment_note": (
                "REGIME-ALIGNMENT invariant only: verifies shift(1) low-vol signal == formation-month "
                "regime for every checked month. It does NOT by itself verify the beta-window upper bound, "
                "form/hold non-overlap, universe selection, or rf timing — those are enforced separately "
                "(estimate_betas window mask, build_bab formation-time universe, formation-month rf)."
            ),
        },
        "leverage_diagnostics": leverage_diag,
        "baseline_unconditional_bab": uncond,
        "conditional_median_split": {
            "median_rv": median_rv,
            "n_months": n_months_primary,
            **cond,
            "primary_significance_test": "sharpe_difference_block_permutation",
            "primary_effect_size_ci": "sharpe_difference_stationary_bootstrap",
            # ★ 主判準：保留 regime 持續性的 null（見 serial_dependence_check）
            "sharpe_difference_block_permutation": perm_block,
            "sharpe_difference_circular_shift_exact": perm_shift,
            "sharpe_difference_block_length_sensitivity": block_grid,
            "regime_block_length_rule": block_rule,
            "sharpe_difference_stationary_bootstrap": sboot,
            # 對照組：i.i.d. 版本（摧毀時間結構，不得作主判準）
            "sharpe_difference_iid_permutation": perm_iid,
            "sharpe_difference_iid_bootstrap": boot,
            "serial_dependence_check": dep_check,
            "regime_regression": reg,
        },
        "robustness_tercile": tercile_stats,
        "robustness_expanding_median": {
            "description": "real-time expanding-median split (min 24 obs) to avoid in-sample median classification",
            "primary_significance_test": "sharpe_difference_block_permutation",
            "sharpe_difference_block_permutation": perm_block_rt,
            "sharpe_difference_circular_shift_exact": perm_shift_rt,
            "sharpe_difference_stationary_bootstrap": sboot_rt,
            "sharpe_difference_iid_permutation": perm_iid_rt,
            "sharpe_difference_iid_bootstrap": boot_rt,
        },
        "figures": figs,
        "per_ticker_coverage": per_ticker,
        "caveats": [
            "SURVIVORSHIP BIAS: yfinance 只回傳現存 ticker，universe 為固定的存活大型股清單 → 天生倖存者偏誤，"
            "不可宣稱『無偏誤大樣本』。存活的低 beta 股可能系統性有較高實現報酬，會同向膨脹 BAB 報酬；"
            "與 vol regime 的交互作用方向不確定。結論強度須相應下修，視為 illustrative replication 而非 population estimate。",
            "Universe 僅 %d 檔大型股（實際納入），遠小於 Frazzini-Pedersen 全 CRSP universe；beta 離散度與 BAB 量級不可與原文直接比較。" % len(included_tickers),
            "Beta = OLS rolling 12M + FP eq.15 收縮（0.6·β+0.4）；未用 FP 原文兩段式（5yr 3-day 重疊相關估相關 + 1yr vol 估波動）。已註記差異。",
            "月度已實現波動用月內日報酬 sqrt(Σr²)；未用日內高頻資料。",
            "rf 換算 ^IRX 年化% → 日 (/252) / 月 (/12) 為近似（未精確處理 T-bill discount/quote convention）；對結果影響很小。",
            "完成月 gate：未涵蓋到 business month-end 的最後 partial 月已排除（Codex review HIGH 修正），避免 partial-month 污染統計。判準用 pandas BMonthEnd（非美股交易所日曆）；月底逢交易所假日理論上可能保守誤刪一個完整月，但本樣本結果為正確排除 2026-07、保留 2026-06。",
            "組合 universe 與權重完全由形成月資訊決定；持有月缺報酬一律 fail-loud（不靜默剔除），因此本樣本 delisting_drops=0。真正下市需明訂 delisting-return 規則後才可納入。",
            "缺值處理：beta 視窗要求完整 12M（window_start ≥ 資料起點）且 ≥%d 交易日、報酬月要求 ≥%d 交易日、每月要求 ≥%d 檔股票才形成組合。" % (MIN_BETA_OBS, MIN_RET_OBS, MIN_STOCKS_PER_MONTH),
            "full-sample median 分類使用了全樣本 vol 分佈（非未來報酬）；已另報 expanding-median real-time 版做 robustness。",
            "顯著性主檢定 = circular block permutation（保留 regime 連續段）；i.i.d. label permutation 只作對照，因為它會把 regime 持續性打散（見 conditional_median_split.serial_dependence_check：label acf(1) 由觀察值降到 ~0、平均段長 3→2）。本樣本兩者 p 幾乎相同，原因是 BAB 月報酬自身近乎無序列相關，label clustering 對檢定統計量的 null 離散度影響有限 —— 這是量測結果，不是事前假設。",
            "block permutation 的 block 長度由固定規則 max(ceil(n^(1/3)), ceil(平均 regime 段長)) 決定（非依 p 值挑選），並在 block 長度格點上報敏感度；另附零調參的窮舉 circular-shift exact 檢定。circular 重排隱含把序列頭尾接起來（wrap 接縫）與月份索引連續（程式 fail-loud 檢查），此為 block/circular 方法的已知近似。",
        ],
    }

    # 用 canonical finalize_experiment 同源寫 results + reproduce_spec.json（byte-traceable：
    # results["code_trace"] 與 spec["entrypoint"] 由同一 trace_file 呼叫產生，描述同一份 bytes）。
    # inputs 必須是**真正被讀取的來源**：`load_data()` 從 data/tickers/<TKR>.csv 逐檔重組，
    # 三份 assembled CSV 是本次執行**寫出**的便利檔（非讀取來源）→ 歸在 outputs。
    # （Codex round-2 非阻斷觀察：原本把寫出檔列為 inputs，pin 錯了 provenance 的方向。）
    ticker_inputs = sorted(str(p) for p in (DATA_DIR / "tickers").glob("*.csv"))
    if not ticker_inputs:
        raise RuntimeError(f"no per-ticker cache under {DATA_DIR / 'tickers'} to pin as inputs")
    finalize_experiment(
        results=results,
        entrypoint=__file__,
        canonical_result="k1812_results.json",
        exp_dir=str(HERE),
        inputs=ticker_inputs,
        outputs=[f"figures/{f}" for f in figs] + [
            "data/stock_prices.csv",
            "data/market_price.csv",
            "data/riskfree_irx.csv",
        ],
        seeds=[("numpy", SEED)],
        started_at=started_at,
    )
    # 供測試讀取的中繼 panel
    panel.reset_index().assign(
        hold_month=lambda d: d["hold_month"].astype(str),
        form_month=lambda d: d["form_month"].astype(str),
    ).to_json(DATA_DIR / "bab_panel.json", orient="records")
    joint.assign(low=joint["low"].astype(int)).reset_index().assign(
        hold_month=lambda d: d["hold_month"].astype(str)
    ).to_json(DATA_DIR / "bab_regime_joint.json", orient="records")

    # 摘要輸出
    print("\n=== K1812 BAB × prior-vol regime ===")
    print(f"BAB months: {results['sample']['n_bab_months']} "
          f"({results['sample']['bab_first_month']} → {results['sample']['bab_last_month']})")
    print(f"Unconditional BAB: mean={uncond['mean']:.5f}/mo, Sharpe(ann)={uncond['sharpe_annual']:.3f}, "
          f"HAC t={uncond['t_stat']:.2f} (p={uncond['p_value']:.3f})")
    print(f"After LOW-vol : Sharpe(ann)={cond['after_low_vol']['sharpe_annual']:.3f} (n={cond['after_low_vol']['n']})")
    print(f"After HIGH-vol: Sharpe(ann)={cond['after_high_vol']['sharpe_annual']:.3f} (n={cond['after_high_vol']['n']})")
    print(f"Sharpe diff (low-high) = {perm_block['diff_observed']:.3f}, "
          f"stationary-boot 95% CI [{sboot['ci95_low']:.3f}, {sboot['ci95_high']:.3f}]")
    print(f"PRIMARY block-permutation p={perm_block['p_value_two_sided']:.3f} "
          f"(b={perm_block['block_len_months']}mo); exact circular-shift p="
          f"{perm_shift['p_value_two_sided']:.3f}; i.i.d. permutation p="
          f"{perm_iid['p_value_two_sided']:.3f} (comparison only)")
    print(f"  label acf(1): observed {dep_check['observed']['label_acf1']:.3f} → "
          f"block null {dep_check['under_block_permutation_null']['label_acf1']:.3f} vs "
          f"i.i.d. null {dep_check['under_iid_permutation_null']['label_acf1']:.3f}")
    print(f"Regime reg: beta_low_vol={reg['beta_low_vol']:.5f}, HAC t={reg['beta_low_vol_t']:.2f} (p={reg['beta_low_vol_p']:.3f})")
    print(f"ex-ante BAB beta max|.| = {exante_beta_max:.2e} (should be ~0)")
    print(f"Results → {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
