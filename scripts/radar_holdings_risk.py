"""
radar_holdings_risk.py
─────────────────────────────────────────────────────────────────────────────
VolPred Radar Phase A — 持倉風險體檢計算引擎（canonical, 真實數據）。

給定使用者持倉 [{ticker, weight_pct}, ...]，用**真實歷史日報酬**計算組合風險：

  - 組合年化波動（協方差矩陣，sqrt(252) 年化）
  - 5% / 2.5% VaR（歷史模擬法 + 參數法 normal，各取 1-day horizon、% 表示的損失）
  - 各部位 marginal risk contribution（MRC）+ 找出最大風險來源部位
  - vs 上週變化（最近交易日 σ_ann vs ~5 交易日前 σ_ann，用 rolling 視窗）

研究誠實鐵律：
  - 全部用真實 adj-close（yfinance + 本地 price_cache 補洞），不臆造。
  - 抓不到的 ticker 如實標 status='no_data' 並從組合移除，不用 0 或假值填補。
  - 明確標資料截止日（as_of）+ lag：用「已收盤」的日報酬，不含未來資料。
  - 隨機性無（純歷史），無 seed 需求；參數法用樣本估計，方法明確標示。

資料源優先序（與 indicator_arena_daily.py 一致）：
  1. yfinance live daily adj-close
  2. data/cache/price_cache.db（cron 每日收的真實收盤，補 yfinance 掉的 session）

CLI：
  uv run python scripts/radar_holdings_risk.py --holdings '[{"ticker":"SPY","weight_pct":60},{"ticker":"TLT","weight_pct":40}]'
  uv run python scripts/radar_holdings_risk.py --holdings @holdings.json --lookback-days 504
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
LOCAL_PRICE_CACHE_DB = REPO_ROOT / "data" / "cache" / "price_cache.db"

TRADING_DAYS = 252
# 標準常態分位數（避免依賴 scipy）：用於參數法 VaR。
Z_SCORE = {0.05: 1.6448536269514722, 0.025: 1.959963984540054}
WEEK_TRADING_DAYS = 5


@dataclass
class PriceSeries:
    """ticker -> ordered list of (date_str, adj_close)."""

    ticker: str
    dates: list[str]
    closes: list[float]


# ---------------------------------------------------------------------------
# Data layer (real prices only)
# ---------------------------------------------------------------------------
def _local_cache_closes(ticker: str, lookback_days: int) -> PriceSeries | None:
    """Adj-closes from the project's daily collection cache (real recorded closes)."""
    if not LOCAL_PRICE_CACHE_DB.exists():
        return None
    try:
        con = sqlite3.connect(str(LOCAL_PRICE_CACHE_DB))
        try:
            rows = con.execute(
                "SELECT date, adj_close FROM price_data "
                "WHERE ticker = ? AND adj_close IS NOT NULL "
                "ORDER BY date DESC LIMIT ?",
                (ticker, lookback_days + WEEK_TRADING_DAYS + 5),
            ).fetchall()
        finally:
            con.close()
    except Exception:
        return None
    if not rows:
        return None
    rows = sorted(rows, key=lambda r: r[0])
    dates = [r[0] for r in rows]
    closes = [float(r[1]) for r in rows]
    return PriceSeries(ticker=ticker, dates=dates, closes=closes)


def _yfinance_closes(ticker: str, lookback_days: int) -> PriceSeries | None:
    """Daily auto-adjusted closes from yfinance. None on any failure."""
    try:
        import yfinance as yf  # noqa: PLC0415
    except Exception:
        return None
    # 多抓一點 buffer（假日 / 非交易日），保證有足夠交易日。
    period_days = int((lookback_days + WEEK_TRADING_DAYS + 10) * 1.6) + 10
    try:
        df = yf.download(
            ticker,
            period=f"{period_days}d",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        return None
    if df is None or df.empty:
        return None
    import pandas as pd  # noqa: PLC0415

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    col = df["Close"]
    if isinstance(col, pd.DataFrame):
        col = col.iloc[:, 0]
    col = col.dropna().astype(float)
    if col.empty:
        return None
    idx = pd.to_datetime(col.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    dates = [d.strftime("%Y-%m-%d") for d in idx.normalize()]
    return PriceSeries(ticker=ticker, dates=dates, closes=[float(x) for x in col.values])


def default_fetch(ticker: str, lookback_days: int) -> PriceSeries | None:
    """yfinance live, gap-filled by local cache. None if both unavailable.

    Real data only — never fabricated. Mirrors indicator_arena_daily.yf_fetch
    precedence (live takes priority, cache fills dropped sessions).
    """
    live = _yfinance_closes(ticker, lookback_days)
    cached = _local_cache_closes(ticker, lookback_days)
    if live is None and cached is None:
        return None
    if cached is None:
        return live
    if live is None:
        return cached
    # Merge by date; live takes precedence over cache for overlapping dates.
    merged: dict[str, float] = {d: c for d, c in zip(cached.dates, cached.closes)}
    merged.update({d: c for d, c in zip(live.dates, live.closes)})
    dates = sorted(merged)
    return PriceSeries(ticker=ticker, dates=dates, closes=[merged[d] for d in dates])


# ---------------------------------------------------------------------------
# Math helpers (no numpy dependency in the hot path; small + explicit)
# ---------------------------------------------------------------------------
def _daily_log_returns(closes: list[float]) -> list[float]:
    """Simple daily returns (P_t / P_{t-1} - 1). signal at t uses prices through t-1
    implicitly — we report risk computed on completed daily closes only."""
    out: list[float] = []
    for prev, cur in zip(closes, closes[1:]):
        if prev and prev > 0 and cur and cur > 0:
            out.append(cur / prev - 1.0)
        else:
            out.append(0.0)
    return out


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _cov(xs: list[float], ys: list[float]) -> float:
    """Sample covariance (ddof=1)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    return sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / (n - 1)


def _percentile(sorted_xs: list[float], q: float) -> float:
    """Linear-interpolation percentile (matches numpy default 'linear')."""
    if not sorted_xs:
        return 0.0
    if len(sorted_xs) == 1:
        return sorted_xs[0]
    pos = q * (len(sorted_xs) - 1)
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return sorted_xs[lo]
    frac = pos - lo
    return sorted_xs[lo] * (1 - frac) + sorted_xs[hi] * frac


# ---------------------------------------------------------------------------
# Holdings parsing / normalization
# ---------------------------------------------------------------------------
@dataclass
class Holding:
    ticker: str
    weight_pct: float


def parse_holdings(raw: object) -> list[Holding]:
    """Accept [{ticker, weight_pct}] or {ticker: weight}. Validates + dedups."""
    items: list[Holding] = []
    if isinstance(raw, dict):
        for tk, w in raw.items():
            items.append(Holding(ticker=str(tk).strip().upper(), weight_pct=float(w)))
    elif isinstance(raw, list):
        for el in raw:
            if not isinstance(el, dict):
                continue
            tk = el.get("ticker")
            w = el.get("weight_pct", el.get("weight"))
            if tk is None or w is None:
                continue
            items.append(Holding(ticker=str(tk).strip().upper(), weight_pct=float(w)))
    else:
        raise ValueError("holdings must be a list or dict")
    # merge duplicate tickers
    merged: dict[str, float] = {}
    for h in items:
        if not h.ticker or not math.isfinite(h.weight_pct) or h.weight_pct <= 0:
            continue
        merged[h.ticker] = merged.get(h.ticker, 0.0) + h.weight_pct
    return [Holding(ticker=t, weight_pct=w) for t, w in merged.items()]


# ---------------------------------------------------------------------------
# Risk engine
# ---------------------------------------------------------------------------
@dataclass
class PositionRisk:
    ticker: str
    weight_pct: float
    annual_vol_pct: float | None
    risk_contribution_pct: float | None  # share of total portfolio variance (component VaR share)


@dataclass
class HoldingsRiskResult:
    as_of: str | None
    lookback_days_used: int
    portfolio_annual_vol_pct: float | None
    var_95_hist_pct: float | None
    var_975_hist_pct: float | None
    var_95_param_pct: float | None
    var_975_param_pct: float | None
    top_risk_ticker: str | None
    top_risk_contribution_pct: float | None
    positions: list[PositionRisk] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)  # tickers with no data / insufficient
    cash_pct: float = 0.0
    week_change: dict | None = None  # {previous_annual_vol_pct, delta_pct, basis}
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "as_of": self.as_of,
            "lookback_days_used": self.lookback_days_used,
            "portfolio_annual_vol_pct": self.portfolio_annual_vol_pct,
            "var_95_hist_pct": self.var_95_hist_pct,
            "var_975_hist_pct": self.var_975_hist_pct,
            "var_95_param_pct": self.var_95_param_pct,
            "var_975_param_pct": self.var_975_param_pct,
            "top_risk_ticker": self.top_risk_ticker,
            "top_risk_contribution_pct": self.top_risk_contribution_pct,
            "cash_pct": self.cash_pct,
            "positions": [
                {
                    "ticker": p.ticker,
                    "weight_pct": p.weight_pct,
                    "annual_vol_pct": p.annual_vol_pct,
                    "risk_contribution_pct": p.risk_contribution_pct,
                }
                for p in self.positions
            ],
            "skipped": self.skipped,
            "week_change": self.week_change,
            "notes": self.notes,
        }


def _align_returns(
    series: dict[str, PriceSeries], lookback_days: int
) -> tuple[list[str], dict[str, list[float]]]:
    """Inner-join price series on common dates, then compute daily returns over the
    last `lookback_days+1` common closes. Returns (return_dates, {ticker: returns})."""
    if not series:
        return [], {}
    common = None
    for ps in series.values():
        ds = set(ps.dates)
        common = ds if common is None else (common & ds)
    common_dates = sorted(common or set())
    # keep last lookback_days+1 closes -> lookback_days returns
    keep = common_dates[-(lookback_days + 1):] if lookback_days > 0 else common_dates
    if len(keep) < 2:
        return [], {}
    close_by: dict[str, dict[str, float]] = {
        t: dict(zip(ps.dates, ps.closes)) for t, ps in series.items()
    }
    rets: dict[str, list[float]] = {}
    for t in series:
        closes = [close_by[t][d] for d in keep]
        rets[t] = _daily_log_returns(closes)
    return keep[1:], rets


def _portfolio_vol_annual(weights: dict[str, float], rets: dict[str, list[float]]) -> tuple[float, dict[str, float]]:
    """Returns (annual_vol_fraction, {ticker: risk_contribution_fraction}).

    σ_p = sqrt(w' Σ w), annualized by sqrt(252).
    Risk contribution_i = w_i (Σ w)_i / (w' Σ w)  (sums to 1).
    """
    tickers = list(weights.keys())
    w = [weights[t] for t in tickers]
    # covariance matrix
    cov = [[_cov(rets[a], rets[b]) for b in tickers] for a in tickers]
    # Σ w
    sigma_w = [sum(cov[i][j] * w[j] for j in range(len(tickers))) for i in range(len(tickers))]
    port_var = sum(w[i] * sigma_w[i] for i in range(len(tickers)))
    if port_var <= 0:
        return 0.0, {t: 0.0 for t in tickers}
    daily_vol = math.sqrt(port_var)
    annual_vol = daily_vol * math.sqrt(TRADING_DAYS)
    contrib = {tickers[i]: (w[i] * sigma_w[i]) / port_var for i in range(len(tickers))}
    return annual_vol, contrib


def _portfolio_daily_returns(weights: dict[str, float], rets: dict[str, list[float]]) -> list[float]:
    tickers = list(weights.keys())
    n = min(len(rets[t]) for t in tickers)
    out: list[float] = []
    for k in range(n):
        out.append(sum(weights[t] * rets[t][k] for t in tickers))
    return out


def compute_holdings_risk(
    holdings: list[Holding],
    lookback_days: int = 252,
    fetch: Callable[[str, int], PriceSeries | None] = default_fetch,
) -> HoldingsRiskResult:
    """Core engine. fetch is injectable for tests (mock real-shaped price series)."""
    notes: list[str] = []
    series: dict[str, PriceSeries] = {}
    skipped: list[dict] = []

    parsed = holdings
    if not parsed:
        return HoldingsRiskResult(
            as_of=None,
            lookback_days_used=0,
            portfolio_annual_vol_pct=None,
            var_95_hist_pct=None,
            var_975_hist_pct=None,
            var_95_param_pct=None,
            var_975_param_pct=None,
            top_risk_ticker=None,
            top_risk_contribution_pct=None,
            notes=["持倉為空，請先輸入持倉。"],
        )

    for h in parsed:
        ps = fetch(h.ticker, lookback_days)
        if ps is None or len(ps.closes) < 2:
            skipped.append({"ticker": h.ticker, "weight_pct": h.weight_pct, "reason": "資料不足"})
            continue
        series[h.ticker] = ps

    if not series:
        return HoldingsRiskResult(
            as_of=None,
            lookback_days_used=0,
            portfolio_annual_vol_pct=None,
            var_95_hist_pct=None,
            var_975_hist_pct=None,
            var_95_param_pct=None,
            var_975_param_pct=None,
            top_risk_ticker=None,
            top_risk_contribution_pct=None,
            skipped=skipped,
            notes=["所有持倉都抓不到真實價格資料，無法計算風險（不以假值填補）。"],
        )

    return_dates, rets = _align_returns(series, lookback_days)
    if not return_dates:
        return HoldingsRiskResult(
            as_of=None,
            lookback_days_used=0,
            portfolio_annual_vol_pct=None,
            var_95_hist_pct=None,
            var_975_hist_pct=None,
            var_95_param_pct=None,
            var_975_param_pct=None,
            top_risk_ticker=None,
            top_risk_contribution_pct=None,
            skipped=skipped,
            notes=["持倉標的的共同交易日不足，無法估計協方差（資料不足）。"],
        )

    n_obs = len(return_dates)
    as_of = return_dates[-1]
    if n_obs < 20:
        notes.append(f"共同樣本僅 {n_obs} 個交易日，估計不穩定，數字僅供參考。")

    # weights over the *priced* holdings (renormalize among tickers that have data);
    # cash = 100 - sum(priced weights as % of original 100 base).
    priced_weight_pct = {t: h.weight_pct for h in parsed for _ in [0] if (t := h.ticker) in series}
    # ^ keep mapping explicit:
    priced_weight_pct = {h.ticker: h.weight_pct for h in parsed if h.ticker in series}
    total_input_pct = sum(h.weight_pct for h in parsed)
    total_priced_pct = sum(priced_weight_pct.values())
    cash_pct = max(0.0, 100.0 - total_input_pct)

    # Portfolio risk computed on risk-asset weights normalized to 1 (cash has 0 vol).
    # We weight by share-of-total-portfolio (incl cash) so VaR is of the WHOLE portfolio.
    base = total_input_pct if total_input_pct > 0 else 100.0
    weights_frac = {t: w / base for t, w in priced_weight_pct.items()}  # fractions of whole portfolio

    annual_vol, contrib = _portfolio_vol_annual(weights_frac, rets)
    port_daily = _portfolio_daily_returns(weights_frac, rets)

    # VaR (1-day, % loss, positive number = loss magnitude)
    losses_sorted = sorted(port_daily)
    var_95_hist = -_percentile(losses_sorted, 0.05) * 100.0
    var_975_hist = -_percentile(losses_sorted, 0.025) * 100.0
    mu = _mean(port_daily)
    sd = math.sqrt(_cov(port_daily, port_daily)) if len(port_daily) > 1 else 0.0
    var_95_param = (Z_SCORE[0.05] * sd - mu) * 100.0
    var_975_param = (Z_SCORE[0.025] * sd - mu) * 100.0

    # per-position annual vol + risk contribution (% of portfolio variance)
    positions: list[PositionRisk] = []
    for h in parsed:
        if h.ticker not in series:
            continue
        own_sd = math.sqrt(_cov(rets[h.ticker], rets[h.ticker]))
        own_annual = own_sd * math.sqrt(TRADING_DAYS) * 100.0
        positions.append(
            PositionRisk(
                ticker=h.ticker,
                weight_pct=h.weight_pct,
                annual_vol_pct=own_annual,
                risk_contribution_pct=contrib.get(h.ticker, 0.0) * 100.0,
            )
        )
    positions.sort(key=lambda p: (p.risk_contribution_pct or -1), reverse=True)
    top = positions[0] if positions else None

    # vs 上週：σ_ann over the most recent window vs window ending ~5 trading days ago.
    week_change = None
    if n_obs >= 20 + WEEK_TRADING_DAYS:
        win = max(20, n_obs - WEEK_TRADING_DAYS)
        recent = {t: r[-win:] for t, r in rets.items()}
        prev = {t: r[-(win + WEEK_TRADING_DAYS):-WEEK_TRADING_DAYS] for t, r in rets.items()}
        recent_vol, _ = _portfolio_vol_annual(weights_frac, recent)
        prev_vol, _ = _portfolio_vol_annual(weights_frac, prev)
        week_change = {
            "current_annual_vol_pct": recent_vol * 100.0,
            "previous_annual_vol_pct": prev_vol * 100.0,
            "delta_pct": (recent_vol - prev_vol) * 100.0,
            "basis": f"最近 {win} 交易日 σ_ann vs {WEEK_TRADING_DAYS} 交易日前同長度視窗",
        }
    else:
        notes.append(f"樣本不足 {20 + WEEK_TRADING_DAYS} 交易日，暫無『vs 上週』比較。")

    if cash_pct > 0:
        notes.append(f"未配置權重 {cash_pct:.1f}% 視為現金（零波動），已計入全組合 VaR。")
    if abs(total_input_pct - 100.0) > 0.5 and total_input_pct > 100.0:
        notes.append(f"輸入權重合計 {total_input_pct:.1f}% 超過 100%，VaR 以原始權重比例計算。")
    if total_priced_pct < total_input_pct - 0.5:
        notes.append(
            f"有 {total_input_pct - total_priced_pct:.1f}% 權重的標的抓不到資料、未計入風險（見 skipped）。"
        )

    return HoldingsRiskResult(
        as_of=as_of,
        lookback_days_used=n_obs,
        portfolio_annual_vol_pct=annual_vol * 100.0,
        var_95_hist_pct=var_95_hist,
        var_975_hist_pct=var_975_hist,
        var_95_param_pct=var_95_param,
        var_975_param_pct=var_975_param,
        top_risk_ticker=top.ticker if top else None,
        top_risk_contribution_pct=top.risk_contribution_pct if top else None,
        positions=positions,
        skipped=skipped,
        cash_pct=cash_pct,
        week_change=week_change,
        notes=notes,
    )


def _load_holdings_arg(value: str) -> object:
    if value.startswith("@"):
        return json.loads(Path(value[1:]).read_text())
    return json.loads(value)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="VolPred Radar 持倉風險體檢計算")
    ap.add_argument("--holdings", required=True, help='JSON 或 @file.json，[{"ticker","weight_pct"}]')
    ap.add_argument("--lookback-days", type=int, default=252)
    args = ap.parse_args(argv)

    raw = _load_holdings_arg(args.holdings)
    holdings = parse_holdings(raw)
    result = compute_holdings_risk(holdings, lookback_days=args.lookback_days)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
