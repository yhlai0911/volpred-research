#!/usr/bin/env python3
"""無人載具 EP-Final：統一口徑重算投資組合證據與三張圖。

Universe 只讀 EP0 canonical 29 檔名冊；核心六檔讀 EP4；海域三檔讀 EP3。
所有組合共用同一價格交集與同一計算方式，避免把 EP1–EP3 不同複利口徑、
不同 universe 的既有籃子直接並排。這是 ex-post 描述，不是可交易策略回測。

輸出：
  storage/drafts/drone_ep_final_portfolio_evidence.json
  storage/drafts/assets/drone_ep_final_basket_comparison.png
  storage/drafts/assets/drone_ep_final_core_risk_map.png
  storage/drafts/assets/drone_ep_final_disclosure_gap.png
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


ROOT = Path(__file__).resolve().parents[1]
DRAFTS = ROOT / "storage" / "drafts"
ASSETS = DRAFTS / "assets"
OUT_JSON = DRAFTS / "drone_ep_final_portfolio_evidence.json"
START = "2025-06-30"
END_EXCLUSIVE = "2026-07-11"
BENCHMARK = "^TWII"
TRADING_DAYS = 252

INPUTS = {
    "ep0": DRAFTS / "drone_ep0_market_snapshot.json",
    "ep2": DRAFTS / "drone_ep2_midstream_evidence.json",
    "ep3": DRAFTS / "drone_ep3_downstream_evidence.json",
    "ep4": DRAFTS / "drone_ep4_six_dim_evidence.json",
}

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False


def require(obj: Any, path: str) -> Any:
    cur = obj
    for token in path.split("."):
        if isinstance(cur, dict) and token in cur:
            cur = cur[token]
        else:
            raise KeyError(f"missing evidence field: {path} (stopped at {token})")
    return cur


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise TypeError(f"evidence root must be object: {path}")
    return data


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_close(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    if raw.empty:
        raise RuntimeError("yfinance returned an empty frame")
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" not in raw.columns.get_level_values(0):
            raise KeyError("yfinance frame missing Close level")
        close = raw["Close"].copy()
    elif len(tickers) == 1 and "Close" in raw.columns:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})
    else:
        raise TypeError("unexpected yfinance column layout")
    missing = [ticker for ticker in tickers if ticker not in close.columns]
    if missing:
        raise KeyError(f"yfinance missing ticker columns: {missing}")
    return close[tickers].sort_index()


def fixed_weights(names: list[str]) -> pd.Series:
    if not names:
        raise ValueError("empty portfolio")
    return pd.Series(1.0 / len(names), index=names, dtype=float)


def tier_balanced_weights(roster: pd.DataFrame) -> pd.Series:
    tiers = sorted(roster["tier"].unique())
    if tiers != ["上游", "下游", "中游"]:
        raise ValueError(f"unexpected EP0 tiers: {tiers}")
    weights = pd.Series(0.0, index=roster["ticker"], dtype=float)
    for tier, group in roster.groupby("tier"):
        weights.loc[group["ticker"]] = (1.0 / len(tiers)) / len(group)
    if not np.isclose(weights.sum(), 1.0):
        raise AssertionError("tier-balanced weights do not sum to one")
    return weights


def daily_rebalanced_returns(asset_returns: pd.DataFrame, weights: pd.Series) -> pd.Series:
    aligned = asset_returns[weights.index]
    return aligned.mul(weights, axis=1).sum(axis=1)


def monthly_rebalanced_returns(asset_returns: pd.DataFrame, target: pd.Series) -> pd.Series:
    aligned = asset_returns[target.index]
    weights = target.copy()
    previous_period = None
    values: list[float] = []
    for date, row in aligned.iterrows():
        period = date.to_period("M")
        if previous_period is not None and period != previous_period:
            weights = target.copy()
        port_return = float(np.dot(weights.to_numpy(), row.to_numpy()))
        values.append(port_return)
        denominator = 1.0 + port_return
        if denominator <= 0:
            raise ValueError("portfolio wealth became non-positive")
        weights = weights * (1.0 + row) / denominator
        previous_period = period
    return pd.Series(values, index=aligned.index, name="monthly_rebalanced")


def daily_rebalance_turnover(asset_returns: pd.DataFrame, target: pd.Series) -> pd.Series:
    aligned = asset_returns[target.index]
    turnover: list[float] = []
    weights = target.copy()
    for _, row in aligned.iterrows():
        port_return = float(np.dot(weights.to_numpy(), row.to_numpy()))
        pre_trade = weights * (1.0 + row) / (1.0 + port_return)
        turnover.append(float(0.5 * np.abs(target - pre_trade).sum()))
        weights = target.copy()
    return pd.Series(turnover, index=aligned.index, name="turnover")


def max_drawdown(returns: pd.Series) -> float:
    wealth = pd.concat([pd.Series([1.0]), (1.0 + returns).cumprod().reset_index(drop=True)])
    drawdown = wealth / wealth.cummax() - 1.0
    return float(drawdown.min())


def portfolio_metrics(asset_returns: pd.DataFrame, benchmark_returns: pd.Series,
                      weights: pd.Series) -> dict[str, Any]:
    daily = daily_rebalanced_returns(asset_returns, weights)
    monthly = monthly_rebalanced_returns(asset_returns, weights)
    log_daily = np.log1p(daily)
    log_bench = np.log1p(benchmark_returns.loc[daily.index])
    covariance = float(np.cov(log_daily, log_bench, ddof=1)[0, 1])
    bench_variance = float(np.var(log_bench, ddof=1))
    downside = float(np.sqrt(np.mean(np.minimum(daily.to_numpy(), 0.0) ** 2)) * np.sqrt(TRADING_DAYS))
    q05 = float(daily.quantile(0.05))
    es_tail = daily[daily <= q05]
    individual_log = np.log1p(asset_returns[weights.index])
    individual_vol = individual_log.std(ddof=1) * np.sqrt(TRADING_DAYS)
    portfolio_vol = float(log_daily.std(ddof=1) * np.sqrt(TRADING_DAYS))
    correlations = individual_log.corr().to_numpy()
    upper = correlations[np.triu_indices_from(correlations, k=1)]
    turnover = daily_rebalance_turnover(asset_returns, weights)
    return {
        "n_names": int(len(weights)),
        "total_return": float((1.0 + daily).prod() - 1.0),
        "annualized_volatility": portfolio_vol,
        "max_drawdown": max_drawdown(daily),
        "beta_vs_twii": covariance / bench_variance,
        "corr_vs_twii": float(log_daily.corr(log_bench)),
        "tracking_error": float((log_daily - log_bench).std(ddof=1) * np.sqrt(TRADING_DAYS)),
        "historical_var_95_daily_loss": float(-q05),
        "historical_es_95_daily_loss": float(-es_tail.mean()),
        "annualized_downside_deviation": downside,
        "sortino_zero_mar": float((daily.mean() * TRADING_DAYS) / downside) if downside else None,
        "average_pairwise_correlation": float(np.mean(upper)) if len(upper) else None,
        "diversification_ratio": float(np.dot(weights.to_numpy(), individual_vol.to_numpy()) / portfolio_vol),
        "daily_rebalance_average_one_way_turnover": float(turnover.mean()),
        "daily_rebalance_total_one_way_turnover": float(turnover.sum()),
        "monthly_rebalance_total_return": float((1.0 + monthly).prod() - 1.0),
        "monthly_rebalance_annualized_volatility": float(
            np.log1p(monthly).std(ddof=1) * np.sqrt(TRADING_DAYS)
        ),
        "monthly_rebalance_max_drawdown": max_drawdown(monthly),
        "daily_minus_monthly_return": float((1.0 + daily).prod() - (1.0 + monthly).prod()),
        "construction": "fixed target weights, reset after every trading day; no fees/taxes",
    }


def individual_metrics(prices: pd.DataFrame, benchmark_returns: pd.Series,
                       ticker: str) -> dict[str, float]:
    daily = prices[ticker].pct_change(fill_method=None).dropna()
    bench = benchmark_returns.loc[daily.index]
    log_daily = np.log1p(daily)
    log_bench = np.log1p(bench)
    return {
        "window_return": float(prices[ticker].iloc[-1] / prices[ticker].iloc[0] - 1.0),
        "annualized_volatility": float(log_daily.std(ddof=1) * np.sqrt(TRADING_DAYS)),
        "max_drawdown": max_drawdown(daily),
        "beta_vs_twii": float(np.cov(log_daily, log_bench, ddof=1)[0, 1] / np.var(log_bench, ddof=1)),
        "corr_vs_twii": float(log_daily.corr(log_bench)),
    }


def build_payload(evidence: dict[str, dict[str, Any]]) -> dict[str, Any]:
    ep0, ep2, ep3, ep4 = (evidence[key] for key in ("ep0", "ep2", "ep3", "ep4"))
    names = require(ep0, "names")
    if not isinstance(names, list) or len(names) != 29 or require(ep0, "basket.n_names") != 29:
        raise ValueError("EP0 canonical roster must contain 29 names")
    roster = pd.DataFrame([
        {
            "name": require(row, "name"),
            "ticker": require(row, "ticker"),
            "tier": require(row, "tier"),
            "confidence": require(row, "confidence"),
        }
        for row in names
    ])
    if roster["ticker"].duplicated().any() or roster["name"].duplicated().any():
        raise ValueError("EP0 roster contains duplicates")

    core_companies = require(ep4, "companies")
    core_names = [require(row, "name") for row in core_companies]
    core_tickers = [require(row, "ticker") for row in core_companies]
    if len(core_tickers) != 6 or not set(core_tickers).issubset(set(roster["ticker"])):
        raise ValueError("EP4 core six do not match EP0 roster")
    sea_companies = [row for row in require(ep3, "companies") if require(row, "segment") == "無人艇"]
    sea_names = [require(row, "name") for row in sea_companies]
    sea_tickers = [require(row, "ticker") for row in sea_companies]
    if len(sea_tickers) != 3 or not set(sea_tickers).issubset(set(roster["ticker"])):
        raise ValueError("EP3 must identify exactly three listed sea-vehicle names")
    air_tickers = [ticker for ticker in core_tickers if ticker not in sea_tickers]
    if len(air_tickers) != 5:
        raise ValueError("core universe must be five air names plus one sea name")

    tickers = roster["ticker"].tolist() + [BENCHMARK]
    raw = yf.download(
        tickers,
        start=START,
        end=END_EXCLUSIVE,
        auto_adjust=True,
        progress=False,
        group_by="column",
        threads=True,
    )
    close = extract_close(raw, tickers)
    common = close.dropna(axis=0, how="any")
    if len(common) < 200:
        counts = close.notna().sum().to_dict()
        raise ValueError(f"common price panel has only {len(common)} rows: {counts}")
    asset_prices = common[roster["ticker"]]
    benchmark_prices = common[BENCHMARK]
    asset_returns = asset_prices.pct_change(fill_method=None).dropna(axis=0, how="any")
    benchmark_returns = benchmark_prices.pct_change(fill_method=None).loc[asset_returns.index]

    weights: dict[str, pd.Series] = {
        "all_29_equal": fixed_weights(roster["ticker"].tolist()),
        "upstream_13_equal": fixed_weights(roster.loc[roster["tier"] == "上游", "ticker"].tolist()),
        "midstream_6_equal": fixed_weights(roster.loc[roster["tier"] == "中游", "ticker"].tolist()),
        "downstream_10_equal": fixed_weights(roster.loc[roster["tier"] == "下游", "ticker"].tolist()),
        "layer_balanced": tier_balanced_weights(roster),
        "core_6_equal": fixed_weights(core_tickers),
        "air_core_5_equal": fixed_weights(air_tickers),
        "sea_3_equal": fixed_weights(sea_tickers),
    }
    labels = {
        "all_29_equal": "全名冊 29 檔等權",
        "upstream_13_equal": "上游 13 檔等權",
        "midstream_6_equal": "中游 6 檔等權",
        "downstream_10_equal": "下游 10 檔等權",
        "layer_balanced": "三層各 1/3",
        "core_6_equal": "核心 6 檔等權",
        "air_core_5_equal": "空中核心 5 檔等權",
        "sea_3_equal": "海域 3 檔等權",
    }
    portfolios = {
        key: {
            "label": labels[key],
            "weights": {ticker: float(value) for ticker, value in series.items()},
            **portfolio_metrics(asset_returns, benchmark_returns, series),
        }
        for key, series in weights.items()
    }
    benchmark_metrics = individual_metrics(common, benchmark_returns, BENCHMARK)
    benchmark_metrics.update({"ticker": BENCHMARK, "n_price_observations": int(len(common))})

    core_lookup = {require(row, "ticker"): row for row in core_companies}
    core_rows: list[dict[str, Any]] = []
    for ticker in core_tickers:
        source = core_lookup[ticker]
        fundamental = require(source, "fundamental")
        latest_fy = str(require(fundamental, "latest_fy"))
        core_rows.append({
            "name": require(source, "name"),
            "ticker": ticker,
            "segment": require(source, "segment"),
            **individual_metrics(common, benchmark_returns, ticker),
            "pe_asof": require(fundamental, "pe_asof"),
            "pb_asof": require(fundamental, "pb_asof"),
            "return_on_equity": require(fundamental, "return_on_equity"),
            "revenue_yoy": require(fundamental, "revenue_yoy"),
            "operating_margin": require(fundamental, f"fy_rows.{latest_fy}.operating_margin"),
            "valuation_asof_date": require(fundamental, "valuation_asof_date"),
        })

    mid_n = int(require(ep2, "summary.n_companies"))
    down_n = int(require(ep3, "summary.n_companies"))
    disclosed_revenue = int(require(ep2, "summary.n_with_separately_disclosed_uav_revenue_share")) + int(
        require(ep3, "summary.n_with_separately_disclosed_uav_usv_revenue_share")
    )
    binding_orders = int(require(ep2, "summary.n_with_public_binding_uav_order_value_in_checked_sources")) + int(
        require(ep3, "summary.n_with_public_binding_uav_usv_order_value_in_checked_sources")
    )
    all_metrics = portfolios["all_29_equal"]
    individual_vols = [individual_metrics(common, benchmark_returns, ticker)["annualized_volatility"]
                       for ticker in roster["ticker"]]

    official_positioning = {
        "checked_at": "2026-07-13",
        "realized_2025_output_twd": 12_900_000_000,
        "realized_2025_export_output_twd": 2_950_000_000,
        "realized_2025_semiconductor_output_twd": 6_838_400_000_000,
        "semiconductor_to_uav_output_ratio_2025": float(6_838_400_000_000 / 12_900_000_000),
        "target_2030_output_twd": 40_000_000_000,
        "target_2030_uav_share_of_2025_semiconductor_output": float(
            40_000_000_000 / 6_838_400_000_000
        ),
        "realized_2026_q1_complete_uav_exports_usd": 115_000_000,
        "realized_2025_full_year_complete_uav_exports_usd": 93_000_000,
        "government_planned_industry_investment_2025_2030_twd": 44_200_000_000,
        "delivered_commercial_military_uavs_asof_2026_05_21_minimum": 3_000,
        "commercial_military_uav_procurement_quantity": 3_422,
        "commercial_military_uav_procurement_twd": 6_887_000_000,
        "monthly_capacity_target": 15_000,
        "industry_alliance_members_minimum": 267,
        "taiwan_companies_in_us_uav_supply_chain_minimum": 20,
        "sources": [
            "https://www.ey.gov.tw/Page/448DE008087A1971/e687d387-4bb4-4cd7-9b7d-cbeb83970623",
            "https://www.ey.gov.tw/Page/9277F759E41CCD91/7fc92ece-9a9b-41cb-b4cc-98215c0a9e3d",
            "https://www.ey.gov.tw/Page/5A8A0CB5B41DA11E/97980e62-02ab-4c1f-b727-c51233e2ffc2",
            "https://www.moea.gov.tw/MNS/populace/news/wHandNews_File.ashx?file_id=125484",
            "https://www.moea.gov.tw/MNS/populace/content/wHandMenuFile.ashx?file_id=38766",
            "https://ws.ndc.gov.tw/Download.ashx?icon=.pdf&n=5ZyL5a6255m85bGV6KiI55WrKDExNOiHszExN%2BW5tCnmoLjlrprmnKwucGRm&u=LzAwMS9hZG1pbmlzdHJhdG9yLzEwL3JlbGZpbGUvMC8xNTY5NC81MzE5OTBlNC01YmE4LTRjNTItOTE0My0wNDBlNmJiMWE2ZGUucGRm",
        ],
        "interpretation_limits": [
            "2030 output and monthly capacity are targets, not realized production",
            "planned government investment is not the same as spent funds or company revenue",
            "MOU, supply-chain entry and orders under discussion are not binding orders",
            "air-vehicle evidence cannot be generalized to sea or underwater vehicles",
        ],
    }

    return {
        "generated_at_tw": datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S"),
        "as_of_date": "2026-07-13",
        "source_files": {
            key: {"path": str(path.relative_to(ROOT)), "sha256": sha256(path)}
            for key, path in INPUTS.items()
        },
        "data_source": "yfinance adjusted close (auto_adjust=True); universes/stages/fundamentals from EP0/EP2/EP3/EP4 evidence JSON; official positioning sources attached",
        "method": {
            "price_window_requested": {"start": START, "end_exclusive": END_EXCLUSIVE},
            "common_price_window": {
                "start": common.index[0].strftime("%Y-%m-%d"),
                "end": common.index[-1].strftime("%Y-%m-%d"),
                "price_observations": int(len(common)),
                "return_observations": int(len(asset_returns)),
            },
            "universe": "EP0 canonical 29 names as reconstructed ex post on 2026-07-13",
            "daily_rebalancing": "fixed target weights reset after each trading day; no fees/taxes",
            "monthly_sensitivity": "same target weights reset on first common trading day of each calendar month",
            "return": "compound simple daily portfolio returns",
            "volatility": "std(log(1 + daily portfolio return), ddof=1) * sqrt(252)",
            "max_drawdown": "minimum wealth/running-peak - 1, including initial wealth 1.0",
            "beta_correlation": "daily log portfolio returns versus ^TWII on the same common dates",
            "var_es": "historical daily simple-return 5th percentile loss and mean loss beyond it",
            "lookback_limit": "ex-post descriptive reconstruction; the 2026-07-13 roster/stages were not known at the 2025-06-30 start, so this is not a tradable backtest",
        },
        "roster": roster.to_dict("records"),
        "portfolio_comparison": portfolios,
        "benchmark": benchmark_metrics,
        "diversification_summary": {
            "n_names": 29,
            "median_individual_annualized_volatility": float(np.median(individual_vols)),
            "all_29_annualized_volatility": all_metrics["annualized_volatility"],
            "volatility_reduction_vs_median_individual": float(
                np.median(individual_vols) - all_metrics["annualized_volatility"]
            ),
            "n_names_beating_twii": sum(
                individual_metrics(common, benchmark_returns, ticker)["window_return"]
                > benchmark_metrics["window_return"] for ticker in roster["ticker"]
            ),
            "n_names_with_vol_above_twii": sum(
                individual_metrics(common, benchmark_returns, ticker)["annualized_volatility"]
                > benchmark_metrics["annualized_volatility"] for ticker in roster["ticker"]
            ),
            "interpretation_limit": "diversification lowers single-name volatility but cannot convert policy ceilings, prototypes or supplier qualifications into revenue",
        },
        "core_six": {
            "selection": require(ep4, "method.universe"),
            "selection_timing_limit": "selected using evidence available at the 2026-07-13 end date; descriptive only",
            "n_companies": 6,
            "n_underperforming_twii": sum(
                row["window_return"] < benchmark_metrics["window_return"] for row in core_rows
            ),
            "companies": core_rows,
        },
        "sea_exposure": {
            "names": sea_names,
            "tickers": sea_tickers,
            "all_29_nominal_weight": float(len(sea_tickers) / len(roster)),
            "downstream_10_nominal_weight": float(len(sea_tickers) / 10),
            "layer_balanced_nominal_weight": 0.1,
            "core_6_nominal_weight": float(1 / 6),
            "interpretation_limit": "nominal weights describe portfolio construction, not verified unmanned-vehicle revenue exposure",
        },
        "business_evidence_gap": {
            "n_ep2_plus_ep3_checked": mid_n + down_n,
            "n_with_separately_disclosed_uav_usv_revenue_share": disclosed_revenue,
            "n_with_public_binding_uav_usv_order_value_in_checked_sources": binding_orders,
            "ep2_stage_counts": {
                "direct_product_or_shipment": require(ep2, "summary.n_direct_product_or_shipment"),
                "development_or_intent": require(ep2, "summary.n_development_or_intent"),
                "adjacent_capability_only": require(ep2, "summary.n_adjacent_capability_only"),
            },
            "ep3_stage_counts": {
                "mass_production_or_delivered": require(ep3, "summary.n_mass_production_or_delivered"),
                "product_prototype_or_collaboration": require(ep3, "summary.n_product_prototype_or_collaboration"),
                "qualification_or_capability": require(ep3, "summary.n_qualification_or_capability"),
            },
            "interpretation_limit": "zeros apply only to EP2/EP3 audited public sources; they do not prove there are no undisclosed contracts",
        },
        "policy": require(ep3, "policy"),
        "certification_check": require(ep3, "certification_check"),
        "official_positioning": official_positioning,
        "conclusion_evidence_grade": {
            "democratic_supply_chain_node": "中高",
            "large_integrated_platform_leader": "中低",
            "global_sea_vehicle_competitiveness": "低",
            "next_semiconductor_scale_economic_pillar": "低",
            "national_security_supply_chain_resilience_cluster": "中高",
            "basis": "realized output/export/delivery and alliance participation support a supply-chain-node role; scale, key-component, revenue-segmentation and binding-order gaps reject semiconductor-scale claims",
        },
        "disclaimer": "描述性統計，非投資建議；歷史不等於未來，法案上限、規畫數量與政策目標都不等於公司訂單或營收。",
    }


def plot_basket_comparison(payload: dict[str, Any]) -> None:
    order = [
        "all_29_equal", "upstream_13_equal", "midstream_6_equal", "downstream_10_equal",
        "layer_balanced", "core_6_equal", "air_core_5_equal", "sea_3_equal",
    ]
    portfolios = require(payload, "portfolio_comparison")
    benchmark = require(payload, "benchmark")
    labels = [portfolios[key]["label"] for key in order] + ["加權指數"]
    returns = [portfolios[key]["total_return"] * 100 for key in order] + [benchmark["window_return"] * 100]
    vols = [portfolios[key]["annualized_volatility"] * 100 for key in order] + [benchmark["annualized_volatility"] * 100]
    y = np.arange(len(labels))
    height = 0.34
    fig, ax = plt.subplots(figsize=(11, 8), dpi=160)
    bars_r = ax.barh(y - height / 2, returns, height, color="#274C77", label="窗口報酬")
    bars_v = ax.barh(y + height / 2, vols, height, color="#8ECAE6", label="年化波動")
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    ax.set_xlabel("百分比（%）")
    ax.set_title("同一共同窗口、同一每日等權算法：無人載具八種曝險")
    ax.legend(frameon=False, loc="lower right")
    ax.grid(axis="x", alpha=0.2)
    ax.bar_label(bars_r, fmt="%.1f%%", padding=3, fontsize=8)
    ax.bar_label(bars_v, fmt="%.1f%%", padding=3, fontsize=8)
    ax.text(
        0.0, -0.10,
        "還原收盤價；每日重設目標權重；未計費稅。Universe 以 2026-07-13 證據回看，不是可交易回測。",
        transform=ax.transAxes, fontsize=9, color="#555555",
    )
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep_final_basket_comparison.png", facecolor="white")
    plt.close(fig)


def plot_core_risk_map(payload: dict[str, Any]) -> None:
    companies = require(payload, "core_six.companies")
    benchmark = require(payload, "benchmark")
    bx = benchmark["annualized_volatility"] * 100
    by = benchmark["window_return"] * 100
    fig, ax = plt.subplots(figsize=(10.5, 7), dpi=160)
    for row in companies:
        x = row["annualized_volatility"] * 100
        y = row["window_return"] * 100
        mdd = abs(row["max_drawdown"]) * 100
        color = "#C44536" if y < by else "#2A9D8F"
        ax.scatter(x, y, s=80 + mdd * 5, color=color, alpha=0.82,
                   edgecolor="white", linewidth=1.0)
        ax.annotate(row["name"], (x, y), xytext=(5, 5), textcoords="offset points", fontsize=9)
    ax.scatter([bx], [by], marker="*", s=420, color="#F4A261", edgecolor="white",
               linewidth=1.0, label="加權指數")
    ax.axhline(by, color="#F4A261", lw=1.0, ls="--", alpha=0.7)
    ax.axvline(bx, color="#F4A261", lw=1.0, ls="--", alpha=0.7)
    ax.set_xlabel("年化波動率（%）")
    ax.set_ylabel("窗口報酬（%）")
    ax.set_title("六檔核心股：圓點越大，期間最大回撤越深")
    ax.legend(frameon=False)
    ax.grid(alpha=0.2)
    ax.text(
        0.01, -0.12,
        "空中 5 檔＋海域 1 檔；共同窗口與大盤一致。資料源：yfinance＋EP4 universe。",
        transform=ax.transAxes, fontsize=9, color="#555555",
    )
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep_final_core_risk_map.png", facecolor="white")
    plt.close(fig)


def plot_disclosure_gap(payload: dict[str, Any]) -> None:
    gap = require(payload, "business_evidence_gap")
    ep2_counts = require(gap, "ep2_stage_counts")
    ep3_counts = require(gap, "ep3_stage_counts")
    fig, (ax, note_ax) = plt.subplots(
        2, 1, figsize=(10.5, 7), dpi=160, gridspec_kw={"height_ratios": [2.2, 1]}
    )
    labels = ["EP2 查核 8 家", "EP3 查核 10 家"]
    data = np.array([
        [ep2_counts["direct_product_or_shipment"], ep2_counts["development_or_intent"], ep2_counts["adjacent_capability_only"]],
        [ep3_counts["mass_production_or_delivered"], ep3_counts["product_prototype_or_collaboration"], ep3_counts["qualification_or_capability"]],
    ], dtype=float)
    colors = ["#2A9D8F", "#E9C46A", "#A8A8A8"]
    legends = ["直接產品／出貨／交付", "開發／原型／合作／意向", "資格或相鄰能力"]
    left = np.zeros(2)
    for idx in range(3):
        bars = ax.barh(labels, data[:, idx], left=left, color=colors[idx], label=legends[idx])
        for bar, value in zip(bars, data[:, idx]):
            if value:
                ax.text(bar.get_x() + bar.get_width() / 2, bar.get_y() + bar.get_height() / 2,
                        f"{int(value)}", ha="center", va="center", fontsize=11, fontweight="bold")
        left += data[:, idx]
    ax.set_xlim(0, max(left) + 0.5)
    ax.set_xlabel("公司家數")
    ax.set_title("公開進度有層次，財報與訂單仍接不上")
    ax.legend(frameon=False, ncol=3, loc="lower center", bbox_to_anchor=(0.5, -0.34))
    ax.grid(axis="x", alpha=0.15)
    note_ax.axis("off")
    n = gap["n_ep2_plus_ep3_checked"]
    rev = gap["n_with_separately_disclosed_uav_usv_revenue_share"]
    orders = gap["n_with_public_binding_uav_usv_order_value_in_checked_sources"]
    note_ax.text(0.23, 0.58, f"{rev}/{n}", ha="center", va="center", fontsize=31,
                 fontweight="bold", color="#C44536")
    note_ax.text(0.23, 0.20, "拆出無人載具營收占比", ha="center", fontsize=11)
    note_ax.text(0.76, 0.58, f"{orders}/{n}", ha="center", va="center", fontsize=31,
                 fontweight="bold", color="#C44536")
    note_ax.text(0.76, 0.20, "揭露可核對的具約束力訂單金額", ha="center", fontsize=11)
    note_ax.text(
        0.5, -0.08,
        "零只限 EP2／EP3 查核來源，不代表公司沒有未公開合約。資料源：EP2、EP3 evidence JSON。",
        ha="center", fontsize=9, color="#555555",
    )
    fig.tight_layout()
    fig.savefig(ASSETS / "drone_ep_final_disclosure_gap.png", facecolor="white")
    plt.close(fig)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    evidence = {key: load_json(path) for key, path in INPUTS.items()}
    payload = build_payload(evidence)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    plot_basket_comparison(payload)
    plot_core_risk_map(payload)
    plot_disclosure_gap(payload)
    print(json.dumps({
        "output": str(OUT_JSON),
        "common_window": payload["method"]["common_price_window"],
        "portfolio_comparison": {
            key: {
                "total_return": value["total_return"],
                "annualized_volatility": value["annualized_volatility"],
                "max_drawdown": value["max_drawdown"],
                "monthly_rebalance_total_return": value["monthly_rebalance_total_return"],
            }
            for key, value in payload["portfolio_comparison"].items()
        },
        "business_evidence_gap": payload["business_evidence_gap"],
    }, ensure_ascii=False, indent=2))
    print(f"[ok] 3 charts -> {ASSETS}")


if __name__ == "__main__":
    main()
