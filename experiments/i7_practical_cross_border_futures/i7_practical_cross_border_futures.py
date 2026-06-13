"""I7: Practical cross-border futures hedging constraints for Taiwan investors.

This is a derived scenario experiment. It does not re-download market data.
It combines validated prior experiment outputs with local price snapshots to
quantify contract granularity, margin demand, FX exposure, and tax sensitivity.
"""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT.parents[1]
RESULTS = ROOT / "i7_practical_cross_border_futures_results.json"
FIG_A = ROOT / "fig_contract_granularity.png"
FIG_B = ROOT / "fig_margin_fx_costs.png"


@dataclass(frozen=True)
class ContractSpec:
    symbol: str
    description: str
    currency: str
    multiplier: float
    assumed_margin_rate: float
    assumed_roundtrip_cost_bps: float
    assumed_tax_rate_per_side: float = 0.0


CONTRACTS = {
    "TX": ContractSpec(
        symbol="TX",
        description="TAIFEX Taiwan index futures",
        currency="TWD",
        multiplier=200.0,
        assumed_margin_rate=0.06,
        assumed_roundtrip_cost_bps=4.0,
        assumed_tax_rate_per_side=0.00002,
    ),
    "MTX": ContractSpec(
        symbol="MTX",
        description="TAIFEX mini Taiwan index futures",
        currency="TWD",
        multiplier=50.0,
        assumed_margin_rate=0.06,
        assumed_roundtrip_cost_bps=6.0,
        assumed_tax_rate_per_side=0.00002,
    ),
    "ES": ContractSpec(
        symbol="ES",
        description="CME E-mini S&P 500 futures",
        currency="USD",
        multiplier=50.0,
        assumed_margin_rate=0.05,
        assumed_roundtrip_cost_bps=1.0,
    ),
    "MES": ContractSpec(
        symbol="MES",
        description="CME Micro E-mini S&P 500 futures",
        currency="USD",
        multiplier=5.0,
        assumed_margin_rate=0.05,
        assumed_roundtrip_cost_bps=2.0,
    ),
}

PORTFOLIOS_TWD = [1_000_000, 3_000_000, 10_000_000, 30_000_000]
TARGET_HEDGE_RATIOS = [0.25, 0.50, 0.75, 1.00]


def load_json(path: str) -> dict[str, Any]:
    return json.loads((PROJECT / path).read_text())


def latest_close(path: str) -> dict[str, Any]:
    """Read the latest close from local yfinance-style CSV snapshots."""
    p = PROJECT / path
    rows: list[dict[str, str]] = []
    with p.open(newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader)
        # Some yfinance snapshots have a 3-line multi-index header.
        if header and header[0] == "Price":
            next(reader)
            next(reader)
            columns = ["Date", "Close", "High", "Low", "Open", "Volume"]
            dict_rows = [dict(zip(columns, row)) for row in reader if row and row[0]]
        else:
            dict_rows = [dict(zip(header, row)) for row in reader if row and row[0]]
    for row in dict_rows:
        try:
            close = float(row["Close"])
        except (KeyError, TypeError, ValueError):
            continue
        rows.append({"date": row.get("Date", ""), "close": close})
    if not rows:
        raise ValueError(f"no close rows parsed from {path}")
    return rows[-1]


def contract_notional(spec: ContractSpec, index_level: float, usdtwd: float) -> dict[str, float]:
    local_notional = index_level * spec.multiplier
    if spec.currency == "USD":
        notional_twd = local_notional * usdtwd
        notional_usd = local_notional
    else:
        notional_twd = local_notional
        notional_usd = local_notional / usdtwd
    margin_local = local_notional * spec.assumed_margin_rate
    margin_twd = notional_twd * spec.assumed_margin_rate
    return {
        "notional_local": local_notional,
        "notional_twd": notional_twd,
        "notional_usd": notional_usd,
        "margin_local": margin_local,
        "margin_twd": margin_twd,
    }


def hedge_plan(
    portfolio_twd: float,
    exposure_weight: float,
    hedge_ratio: float,
    spec: ContractSpec,
    index_level: float,
    usdtwd: float,
) -> dict[str, Any]:
    c = contract_notional(spec, index_level, usdtwd)
    target_notional_twd = portfolio_twd * exposure_weight * hedge_ratio
    raw_contracts = target_notional_twd / c["notional_twd"]
    rounded_contracts = int(math.floor(raw_contracts + 0.5))
    floor_contracts = int(math.floor(raw_contracts))
    ceil_contracts = int(math.ceil(raw_contracts))

    def achieved(n: int) -> float:
        if target_notional_twd == 0:
            return 0.0
        return n * c["notional_twd"] / target_notional_twd

    selected = rounded_contracts if rounded_contracts > 0 else (1 if raw_contracts >= 0.5 else 0)
    achieved_ratio = achieved(selected)
    rounding_error = achieved_ratio - 1.0 if target_notional_twd else 0.0
    margin_twd = selected * c["margin_twd"]
    roundtrip_tax_twd = 0.0
    if spec.assumed_tax_rate_per_side:
        roundtrip_tax_twd = selected * c["notional_twd"] * spec.assumed_tax_rate_per_side * 2
    roundtrip_cost_twd = selected * c["notional_twd"] * spec.assumed_roundtrip_cost_bps / 10_000
    return {
        "portfolio_twd": portfolio_twd,
        "exposure_weight": exposure_weight,
        "hedge_ratio": hedge_ratio,
        "target_notional_twd": target_notional_twd,
        "contract": spec.symbol,
        "raw_contracts": raw_contracts,
        "rounded_contracts": selected,
        "floor_contracts": floor_contracts,
        "ceil_contracts": ceil_contracts,
        "achieved_hedge_ratio_vs_target": achieved_ratio,
        "rounding_error_pct_of_target": rounding_error * 100,
        "margin_twd": margin_twd,
        "margin_pct_of_portfolio": margin_twd / portfolio_twd * 100,
        "roundtrip_cost_twd": roundtrip_cost_twd,
        "roundtrip_tax_twd": roundtrip_tax_twd,
        "roundtrip_all_in_bps_of_portfolio": (roundtrip_cost_twd + roundtrip_tax_twd) / portfolio_twd * 10_000,
    }


def residual_vol_from_he(vol_pct: float, he: float) -> float:
    return vol_pct * math.sqrt(max(0.0, 1.0 - he))


def main() -> None:
    k758 = load_json("experiments/k758v2/k758v2_tw_cross_border_hedge_results.json")
    i9 = load_json("experiments/i9/i9_proper_hedging_results.json")
    i6 = load_json("experiments/i6/i6_fixed_results.json")
    i11 = load_json("experiments/i11/i11_full_panel_results.json")

    twii = latest_close("storage/macro/yf_TWII.csv")
    twdx = latest_close("storage/macro/yf_TWDX.csv")
    spy = latest_close("experiments/k1206/data/SPY.csv")
    usdtwd = twdx["close"]
    spx_proxy_level = spy["close"] * 10.0

    best_k758 = k758["part_c_grid_search"]["best_conservative_mdd25"]
    fx = k758["part_a_fx_risk"]
    equity = i9["pairs"]["Equity"]
    es_ols = equity["methods"]["OLS"]
    es_naive = equity["methods"]["Naive"]

    price_snapshot = {
        "TWII": twii,
        "USDTWD": twdx,
        "SPY": spy,
        "spx_proxy_level_from_spy_x10": spx_proxy_level,
        "note": "ES/SPX history is not downloaded here; SPY close times 10 is used as a contract-sizing proxy only.",
    }

    contract_summary: dict[str, Any] = {}
    for key, spec in CONTRACTS.items():
        index_level = twii["close"] if key in {"TX", "MTX"} else spx_proxy_level
        contract_summary[key] = {
            "description": spec.description,
            "currency": spec.currency,
            "multiplier": spec.multiplier,
            "assumed_margin_rate": spec.assumed_margin_rate,
            "assumed_roundtrip_cost_bps": spec.assumed_roundtrip_cost_bps,
            "assumed_tax_rate_per_side": spec.assumed_tax_rate_per_side,
            **contract_notional(spec, index_level, usdtwd),
        }

    plans: list[dict[str, Any]] = []
    for portfolio_twd in PORTFOLIOS_TWD:
        for hedge_ratio in TARGET_HEDGE_RATIOS:
            plans.append(hedge_plan(portfolio_twd, 1.0, hedge_ratio, CONTRACTS["TX"], twii["close"], usdtwd))
            plans.append(hedge_plan(portfolio_twd, 1.0, hedge_ratio, CONTRACTS["MTX"], twii["close"], usdtwd))
            plans.append(hedge_plan(portfolio_twd, 0.30, hedge_ratio, CONTRACTS["ES"], spx_proxy_level, usdtwd))
            plans.append(hedge_plan(portfolio_twd, 0.30, hedge_ratio, CONTRACTS["MES"], spx_proxy_level, usdtwd))

    # Practical pass/fail rule: at least one contract after rounding, absolute
    # rounding error <= 15%, and margin <= 25% of total portfolio.
    feasible = [
        p
        for p in plans
        if p["rounded_contracts"] > 0
        and abs(p["rounding_error_pct_of_target"]) <= 15.0
        and p["margin_pct_of_portfolio"] <= 25.0
    ]

    tax_scenarios = []
    # Tax is applied to positive hedge profits only; if the hedge loses, no tax
    # asset is assumed. This isolates upside haircut, not full tax accounting.
    hedge_profit_shocks = [0.02, 0.05, 0.10]
    tax_rates = [0.0, 0.15, 0.20, 0.30]
    for shock in hedge_profit_shocks:
        for tax_rate in tax_rates:
            tax_scenarios.append(
                {
                    "hedge_profit_pct_of_notional": shock * 100,
                    "tax_rate_on_positive_hedge_pnl": tax_rate,
                    "after_tax_profit_retention_pct": (1.0 - tax_rate) * 100,
                    "tax_drag_pct_of_notional": shock * tax_rate * 100,
                }
            )

    fx_hedge_cost = {
        "k758v2_retail_full_fx_hedge_cost_pct_per_year": k758["part_d_practical_costs"]["total_retail_pct"],
        "k758v2_institutional_full_fx_hedge_cost_pct_per_year": k758["part_d_practical_costs"]["total_inst_pct"],
        "best_grid_hedge_ratio": best_k758["hedge_ratio"],
        "best_grid_unhedged_equity_mix": {
            "w_0050": best_k758["w_0050"],
            "w_spy": best_k758["w_spy"],
            "w_gld": best_k758["w_gld"],
        },
        "fx_variance_share_pct": fx["variance_decomposition"]["pct_fx"],
        "spy_twd_vol_pct": fx["spy_vol_twd_pct"],
        "spy_usd_vol_pct": fx["spy_vol_usd_pct"],
        "fx_vol_pct": fx["fx_vol_pct"],
    }

    hedging_effectiveness = {
        "SPY_ES_OLS_HE": es_ols["HE"],
        "SPY_ES_naive_HE": es_naive["HE"],
        "SPY_ES_corr": equity["spot_futures_corr"],
        "SPY_ES_OLS_avg_h": es_ols["avg_h"],
        "SPY_ES_OLS_residual_vol_pct_from_SPY_USD": residual_vol_from_he(fx["spy_vol_usd_pct"], es_ols["HE"]),
        "I6_static_OHR_HE": i6["section_a_hedging"]["Static OHR"]["HE"],
        "I11_SPY_ES_naive_HE": i11["pairs"]["SPY-ES"]["naive"]["HE"],
        "I11_SPY_ES_best_dynamic_dm_t": i11["pairs"]["SPY-ES"]["expanding_ols"]["dm_t"],
    }

    key_findings = [
        "TX is too coarse for small and mid-sized Taiwan portfolios; MTX is the practical Taiwan hedge instrument below roughly NT$30m.",
        "ES is too coarse for a 30% US-equity sleeve even at NT$30m scale; MES is the practical contract for retail sizing.",
        "For SPY/ES, prior I9/I11 results show static OLS or naive hedge already removes about 94% of variance; dynamic hedging adds little after costs.",
        "FX hedging remains the binding cost: K758v2 estimates full retail FX hedge cost at 4.86%/yr versus 1.86%/yr institutional.",
        "Tax impact should be modeled as scenario-specific because Taiwan residence, US account status, and Section 1256 treatment are investor-specific.",
    ]

    output = {
        "experiment_id": "I7_practical_cross_border_futures",
        "title": "Taiwan investor practical cross-border futures hedging constraints",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "seed": None,
        "classification": "derived empirical + scenario analysis",
        "data_sources": {
            "prior_results": [
                "experiments/k758v2/k758v2_tw_cross_border_hedge_results.json",
                "experiments/i9/i9_proper_hedging_results.json",
                "experiments/i6/i6_fixed_results.json",
                "experiments/i11/i11_full_panel_results.json",
            ],
            "local_price_snapshots": [
                "storage/macro/yf_TWII.csv",
                "storage/macro/yf_TWDX.csv",
                "experiments/k1206/data/SPY.csv",
            ],
        },
        "sample_inherited_from_prior_results": {
            "k758v2_period": k758["period"],
            "k758v2_n_obs": k758["n_obs"],
            "i9_period": i9["data"]["period"],
            "i9_oos": i9["data"]["oos"],
        },
        "price_snapshot": price_snapshot,
        "contract_summary": contract_summary,
        "portfolio_sizing_grid": plans,
        "feasible_plans": feasible,
        "fx_hedge_cost": fx_hedge_cost,
        "hedging_effectiveness": hedging_effectiveness,
        "tax_scenarios": tax_scenarios,
        "methodology_notes": [
            "No live market data are downloaded; all calculations are reproducible from local files.",
            "ES sizing uses SPY close times 10 as an S&P 500 level proxy because ES settlement history is not available locally in this experiment.",
            "Contract margin rates, Taiwan futures tax, round-trip costs, and tax rates are explicit scenario assumptions, not broker quotes.",
            "Hedging effectiveness is evaluated with HE/VaR/ES from prior futures-hedging experiments, not with strategy Sharpe comparisons.",
        ],
        "key_findings": key_findings,
        "verdict": "CONDITIONAL_PASS",
        "limitations": [
            "Current broker-specific margin requirements were not pulled; margin is a scenario rate.",
            "Tax treatment is not legal advice and is shown as sensitivity only.",
            "Taiwan TX hedge calculations use TWII level as contract proxy, not a continuous TX settlement series.",
            "Derived experiment inherits prior data-cleaning assumptions, especially USDTWD and 0050.TW cleaning from K758v2.",
        ],
    }

    RESULTS.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n")
    make_figures(output)


def make_figures(output: dict[str, Any]) -> None:
    small = [p for p in output["portfolio_sizing_grid"] if p["portfolio_twd"] == 3_000_000 and p["hedge_ratio"] == 1.0]
    labels = [p["contract"] for p in small]
    errors = [p["rounding_error_pct_of_target"] for p in small]
    margins = [p["margin_pct_of_portfolio"] for p in small]

    fig, ax = plt.subplots(figsize=(8, 4.5))
    colors = ["#4c78a8", "#72b7b2", "#f58518", "#54a24b"]
    ax.bar(labels, errors, color=colors)
    ax.axhline(15, color="#b22222", linewidth=1, linestyle="--")
    ax.axhline(-15, color="#b22222", linewidth=1, linestyle="--")
    ax.set_title("Contract granularity: NT$3m portfolio, full hedge target")
    ax.set_ylabel("Rounding error vs target (%)")
    ax.set_xlabel("Contract")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_A, dpi=160)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.bar(labels, margins, color=colors)
    ax.axhline(25, color="#b22222", linewidth=1, linestyle="--")
    ax.set_title("Margin demand: NT$3m portfolio, selected rounded contracts")
    ax.set_ylabel("Margin as % of portfolio")
    ax.set_xlabel("Contract")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG_B, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
