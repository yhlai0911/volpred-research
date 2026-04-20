"""從 paper_trading.json 重算所有策略的績效指標。

每日由 daily_update.py 呼叫，或獨立執行：
  uv run python scripts/recalc_metrics.py

輸出：storage/strategy_metrics.json + active frontend data/strategy_metrics.json
"""
import json
import math
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT / "src"))

from volpred.config.runtime import get_strategy_metrics_sync_paths

# All strategies use the same start date for fair comparison.
# Latest common start: 2023-01-04 (US strategies).
# Earlier entries are kept in paper_trading.json but excluded from metrics.
COMMON_START_DATE = "2023-01-04"


def build_sparkline(entries: list, max_points: int = 90, start_date: str = COMMON_START_DATE) -> list:
    """Build sparkline (cumulative return pct) from paper_trading entries.

    Ported from scripts/list_new_strategy.py:_build_sparkline so recalc_metrics
    can refresh sparklines daily instead of only at strategy listing time.
    """
    valid = [
        e for e in entries
        if (e.get("data_date") or e.get("date", "")) >= start_date
        and e.get("portfolio_return") is not None
    ]
    if len(valid) < 10:
        return []
    cum = 1.0
    cum_series = []
    for e in valid:
        cum *= (1 + e["portfolio_return"])
        cum_series.append(round((cum - 1) * 100, 2))
    if len(cum_series) <= max_points:
        return cum_series
    step = len(cum_series) / max_points
    result = [cum_series[min(int(i * step), len(cum_series) - 1)] for i in range(max_points)]
    result[-1] = cum_series[-1]
    return result


def calc_metrics(entries: list, initial_capital: int = 1000000) -> dict:
    """Calculate performance metrics from paper trading entries."""
    returns = []
    for e in entries:
        ret = e.get("portfolio_return")
        if ret is not None and isinstance(ret, (int, float)):
            returns.append(ret)

    if len(returns) < 10:
        return {}

    n = len(returns)
    years = n / 252

    # Cumulative return
    cum = 1.0
    peak = 1.0
    max_dd = 0.0
    dd_start = 0
    max_dd_days = 0
    current_dd_start = 0
    for i, r in enumerate(returns):
        cum *= (1 + r)
        if cum > peak:
            peak = cum
            current_dd_start = i
        dd = (cum - peak) / peak
        if dd < max_dd:
            max_dd = dd
            max_dd_days = i - current_dd_start

    cumulative_return = (cum - 1) * 100
    annualized_return = (cum ** (1 / years) - 1) * 100 if years > 0 else 0

    # Volatility
    mean_ret = sum(returns) / n
    variance = sum((r - mean_ret) ** 2 for r in returns) / (n - 1)
    daily_vol = math.sqrt(variance)
    annualized_vol = daily_vol * math.sqrt(252) * 100

    # Sharpe
    sharpe = (mean_ret / daily_vol * math.sqrt(252)) if daily_vol > 0 else 0

    # Sortino (downside deviation)
    neg_returns = [r for r in returns if r < 0]
    if neg_returns:
        downside_var = sum(r ** 2 for r in neg_returns) / len(neg_returns)
        downside_dev = math.sqrt(downside_var)
        sortino = (mean_ret / downside_dev * math.sqrt(252)) if downside_dev > 0 else 0
    else:
        sortino = sharpe * 1.5  # all positive

    # Calmar
    calmar = (annualized_return / abs(max_dd * 100)) if max_dd != 0 else 0

    # Win rate
    wins = sum(1 for r in returns if r > 0)
    win_rate = (wins / n * 100) if n > 0 else 0

    # VaR / CVaR (95%)
    sorted_rets = sorted(returns)
    var_idx = int(n * 0.05)
    var_95 = sorted_rets[var_idx] * 100 if var_idx < n else 0
    cvar_95 = (sum(sorted_rets[:var_idx + 1]) / (var_idx + 1) * 100) if var_idx > 0 else var_95

    # Best / worst day
    best_day = max(returns) * 100
    worst_day = min(returns) * 100

    return {
        "cumulative_return": round(cumulative_return, 2),
        "annualized_return": round(annualized_return, 2),
        "sharpe": round(sharpe, 2),
        "sortino": round(sortino, 2),
        "max_drawdown": round(max_dd * 100, 2),
        "annualized_vol": round(annualized_vol, 2),
        "calmar": round(calmar, 2),
        "win_rate": round(win_rate, 1),
        "var_95": round(var_95, 2),
        "cvar_95": round(cvar_95, 2),
        "max_drawdown_days": max_dd_days,
        "best_day": round(best_day, 2),
        "worst_day": round(worst_day, 2),
        "trading_days": n,
    }


def recalc_all():
    """Recalculate metrics for all strategies in paper_trading.json."""
    pt_path = PROJECT / "storage" / "paper_trading.json"
    if not pt_path.exists():
        print("paper_trading.json not found")
        return

    pt = json.loads(pt_path.read_text())
    metrics = {}
    sparklines = {}

    for sid, strat in pt.items():
        entries = strat.get("entries", [])
        if not entries:
            continue

        # Trim to common start date for fair cross-strategy comparison
        trimmed = [e for e in entries if (e.get("data_date") or e.get("trade_date") or e.get("date", "")) >= COMMON_START_DATE]
        if not trimmed:
            continue

        m = calc_metrics(trimmed, strat.get("initial_capital", 1000000))
        if not m:
            continue

        # Get display name from strategy_signals DB (or fallback to sid)
        m["display_name"] = sid
        metrics[sid] = m
        sparklines[sid] = build_sparkline(entries)
        print(f"  {sid:25s} Sharpe={m['sharpe']:.2f} Ret={m['cumulative_return']:.1f}% MDD={m['max_drawdown']:.1f}% sparkline={len(sparklines[sid])}pt")

    # Save
    out_path = PROJECT / "storage" / "strategy_metrics.json"
    out_path.write_text(json.dumps(metrics, indent=2, ensure_ascii=False))

    synced_targets = []
    metrics_json = json.dumps(metrics, indent=2, ensure_ascii=False)
    for target_path in get_strategy_metrics_sync_paths(active_only=True):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(metrics_json)
        synced_targets.append(str(target_path.relative_to(PROJECT)))

    print(f"\n✓ {len(metrics)} strategies updated → {out_path.name}")
    if synced_targets:
        print(f"  → frontend metrics synced: {', '.join(synced_targets)}")
    else:
        print("  → frontend metrics sync skipped: no configured targets")

    # Sync metrics to Supabase strategy_metrics_cache (so frontend shows correct numbers)
    try:
        from supabase_sync import SUPABASE_URL, SUPABASE_KEY
        if SUPABASE_URL and SUPABASE_KEY:
            from urllib.request import Request, urlopen
            from urllib.error import HTTPError
            headers = {
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            }
            # NOTE (2026-04-19 21:24 UTC): sparkline field is owned by frontend
            # `computeStrategyMetricsPayload()` (data-server.ts buildSparkline ->
            # absolute equity, 60 pts, starts $1M). recalc_metrics PATCH 只 update
            # metrics field; sparkline 由 frontend refresh endpoint 或下次 cache
            # rebuild 以 canonical format 產。
            synced = 0
            for strat, m in metrics.items():
                data = json.dumps({"metrics": m}).encode("utf-8")
                url = f"{SUPABASE_URL}/rest/v1/strategy_metrics_cache?strategy=eq.{strat}"
                req = Request(url, data=data, headers=headers, method="PATCH")
                try:
                    urlopen(req)
                    synced += 1
                except HTTPError:
                    pass
            print(f"  → Supabase strategy_metrics_cache: {synced}/{len(metrics)} synced (metrics only; sparkline owned by frontend buildSparkline)")
    except Exception as e:
        print(f"  → Supabase metrics sync skipped: {e}")

    return metrics


if __name__ == "__main__":
    recalc_all()
