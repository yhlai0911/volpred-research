#!/usr/bin/env python3
"""
K1505: Vol-aware withdrawal rules for sequence-of-returns risk.

This is a retirement decumulation simulation, not a trading strategy and not an
out-of-sample volatility forecast. It uses real SPY/IEF ETF returns and FRED CPI
to build monthly real 60/40 returns, then compares fixed real withdrawals with
withdrawal cuts triggered by lagged realized volatility and/or lagged drawdown.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager


for font_name in ["Arial Unicode MS", "PingFang TC", "Heiti TC", "Hiragino Sans GB"]:
    try:
        font_manager.findfont(font_name, fallback_to_default=False)
        plt.rcParams["font.sans-serif"] = [font_name]
        break
    except Exception:
        continue
plt.rcParams["axes.unicode_minus"] = False


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA_DIR = HERE / "data"
FIG_DIR = HERE / "figures"
DATA_DIR.mkdir(exist_ok=True)
FIG_DIR.mkdir(exist_ok=True)

SEED = 20260616
N_PATHS = 10_000
HORIZON_MONTHS = 360
BLOCK_SIZE_MONTHS = 12
INITIAL_WEALTH = 1_000_000.0
WITHDRAWAL_RATES = [0.035, 0.04, 0.045, 0.05, 0.055]
MAIN_WITHDRAWAL_RATE = 0.04
STOCK_WEIGHT = 0.60
BOND_WEIGHT = 0.40
VOL_WINDOW_MONTHS = 12
VOL_THRESHOLD_QUANTILE = 0.75
DRAWDOWN_THRESHOLD = -0.15
WITHDRAWAL_CUT = 0.15
ETF_START = "2006-01-01"
TICKERS = {"stock": "SPY", "bond": "IEF"}


@dataclass(frozen=True)
class Policy:
    key: str
    label: str
    use_vol: bool
    use_drawdown: bool
    cut: float


POLICIES = [
    Policy("fixed", "Fixed real withdrawal", False, False, 0.0),
    Policy("vol_cut", "Lagged-vol cut", True, False, WITHDRAWAL_CUT),
    Policy("drawdown_cut", "Lagged-drawdown cut", False, True, WITHDRAWAL_CUT),
    Policy("combined_cut", "Vol or drawdown cut", True, True, WITHDRAWAL_CUT),
]


def _drop_partial_current_month(monthly: pd.Series, raw_last_date: pd.Timestamp) -> pd.Series:
    today = pd.Timestamp.today().normalize()
    if raw_last_date.year == today.year and raw_last_date.month == today.month:
        return monthly.iloc[:-1]
    return monthly


def load_adjusted_close(ticker: str, refresh: bool) -> pd.Series:
    cache_path = DATA_DIR / f"{ticker}.csv"
    if cache_path.exists() and not refresh:
        close = pd.read_csv(cache_path, parse_dates=["Date"]).set_index("Date")["Close"]
        return close.sort_index()

    import yfinance as yf

    hist = yf.Ticker(ticker).history(start=ETF_START, auto_adjust=True)
    if hist is None or hist.empty:
        raise RuntimeError(f"yfinance returned no rows for {ticker}")
    close = hist["Close"].copy()
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close = close[~close.index.duplicated(keep="last")].sort_index()
    close.to_frame("Close").reset_index().rename(columns={"index": "Date"}).to_csv(
        cache_path, index=False
    )
    return close


def monthly_returns_from_close(close: pd.Series) -> pd.Series:
    monthly = close.resample("ME").last()
    monthly = _drop_partial_current_month(monthly, close.index.max())
    return monthly.pct_change().dropna()


def load_monthly_inflation() -> pd.Series:
    cpi_path = ROOT / "storage" / "macro" / "fred_CPIAUCSL.csv"
    cpi = pd.read_csv(cpi_path, parse_dates=["date"]).set_index("date")["CPIAUCSL"]
    cpi = cpi.sort_index().resample("ME").last()
    return cpi.pct_change().dropna()


def build_real_return_data(refresh: bool) -> tuple[pd.DataFrame, dict]:
    closes = {name: load_adjusted_close(ticker, refresh) for name, ticker in TICKERS.items()}
    monthly = pd.DataFrame({name: monthly_returns_from_close(px) for name, px in closes.items()})
    inflation = load_monthly_inflation().rename("inflation")
    data = monthly.join(inflation, how="inner").dropna()
    data["nominal_6040"] = STOCK_WEIGHT * data["stock"] + BOND_WEIGHT * data["bond"]
    data["real_6040"] = (1.0 + data["nominal_6040"]) / (1.0 + data["inflation"]) - 1.0

    trailing_vol = data["real_6040"].rolling(VOL_WINDOW_MONTHS).std(ddof=1) * np.sqrt(12)
    vol_threshold = float(trailing_vol.dropna().quantile(VOL_THRESHOLD_QUANTILE))
    nav = (1.0 + data["real_6040"]).cumprod()
    drawdown = nav / nav.cummax() - 1.0

    meta = {
        "tickers": TICKERS,
        "source": "yfinance adjusted close for SPY/IEF; storage/macro/fred_CPIAUCSL.csv for FRED CPIAUCSL",
        "monthly_start": str(data.index.min().date()),
        "monthly_end": str(data.index.max().date()),
        "n_months": int(len(data)),
        "stock_weight": STOCK_WEIGHT,
        "bond_weight": BOND_WEIGHT,
        "ann_real_mean_arithmetic": float(data["real_6040"].mean() * 12),
        "ann_real_vol": float(data["real_6040"].std(ddof=1) * np.sqrt(12)),
        "real_nav_max_drawdown": float(drawdown.min()),
        "vol_window_months": VOL_WINDOW_MONTHS,
        "vol_threshold_quantile": VOL_THRESHOLD_QUANTILE,
        "vol_threshold_ann": vol_threshold,
        "share_high_vol_months_after_window": float((trailing_vol.dropna() > vol_threshold).mean()),
        "drawdown_threshold": DRAWDOWN_THRESHOLD,
        "share_drawdown_breach_months": float((drawdown <= DRAWDOWN_THRESHOLD).mean()),
        "inflation_ann_mean": float(data["inflation"].mean() * 12),
    }
    return data, meta


def moving_block_bootstrap(values: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    if len(values) < BLOCK_SIZE_MONTHS:
        raise ValueError("not enough observations for block bootstrap")
    n_blocks = int(np.ceil(HORIZON_MONTHS / BLOCK_SIZE_MONTHS))
    max_start = len(values) - BLOCK_SIZE_MONTHS
    starts = rng.integers(0, max_start + 1, size=(N_PATHS, n_blocks))
    out = np.empty((N_PATHS, HORIZON_MONTHS), dtype=float)
    for block_idx in range(n_blocks):
        start_col = block_idx * BLOCK_SIZE_MONTHS
        block_len = min(BLOCK_SIZE_MONTHS, HORIZON_MONTHS - start_col)
        idx = starts[:, block_idx][:, None] + np.arange(block_len)
        out[:, start_col : start_col + block_len] = values[idx]
    return out


def max_drawdown_rows(wealth_paths: np.ndarray) -> np.ndarray:
    peaks = np.maximum.accumulate(wealth_paths, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        dd = np.where(peaks > 0, wealth_paths / peaks - 1.0, 0.0)
    return dd.min(axis=1)


def simulate_policy(
    real_return_paths: np.ndarray,
    policy: Policy,
    base_withdrawal_rate: float,
    vol_threshold: float,
) -> dict:
    n_paths, n_months = real_return_paths.shape
    wealth = np.full(n_paths, INITIAL_WEALTH, dtype=float)
    peak = np.full(n_paths, INITIAL_WEALTH, dtype=float)
    market_nav = np.ones(n_paths, dtype=float)
    market_peak = np.ones(n_paths, dtype=float)
    total_withdrawn = np.zeros(n_paths, dtype=float)
    cut_months = np.zeros(n_paths, dtype=int)
    ruin_month = np.full(n_paths, -1, dtype=int)
    wealth_paths = np.empty((n_paths, n_months), dtype=float)
    monthly_base = INITIAL_WEALTH * base_withdrawal_rate / 12.0

    for month in range(n_months):
        alive = wealth > 0.0

        if policy.use_vol and month >= VOL_WINDOW_MONTHS:
            # Signal for month t uses path returns [t-12, ..., t-1], never r_t.
            trailing = real_return_paths[:, month - VOL_WINDOW_MONTHS : month]
            vol_signal = trailing.std(axis=1, ddof=1) * np.sqrt(12) > vol_threshold
        else:
            vol_signal = np.zeros(n_paths, dtype=bool)

        if policy.use_drawdown:
            # Market drawdown is measured on the no-withdrawal 60/40 return NAV,
            # before month-t return, so it only contains information through t-1.
            prev_drawdown = np.where(market_peak > 0.0, market_nav / market_peak - 1.0, 0.0)
            drawdown_signal = prev_drawdown <= DRAWDOWN_THRESHOLD
        else:
            drawdown_signal = np.zeros(n_paths, dtype=bool)

        trigger = (vol_signal if policy.use_vol else False) | (
            drawdown_signal if policy.use_drawdown else False
        )
        multiplier = np.where(trigger, 1.0 - policy.cut, 1.0)
        planned_withdrawal = monthly_base * multiplier
        paid = np.where(alive, np.minimum(wealth, planned_withdrawal), 0.0)
        total_withdrawn += paid
        cut_months += (alive & (multiplier < 1.0)).astype(int)

        wealth = np.where(alive, wealth - paid, wealth)
        newly_ruined = alive & (wealth <= 0.0)
        ruin_month = np.where(newly_ruined & (ruin_month < 0), month + 1, ruin_month)

        still_alive = wealth > 0.0
        wealth = np.where(still_alive, wealth * (1.0 + real_return_paths[:, month]), wealth)
        wealth = np.maximum(wealth, 0.0)
        peak = np.maximum(peak, wealth)
        market_nav = market_nav * (1.0 + real_return_paths[:, month])
        market_peak = np.maximum(market_peak, market_nav)
        wealth_paths[:, month] = wealth

    success = wealth > 0.0
    return {
        "success": success,
        "ruined": ~success,
        "terminal_wealth": wealth,
        "total_withdrawn": total_withdrawn,
        "cut_months": cut_months,
        "ruin_month": ruin_month,
        "max_drawdown": max_drawdown_rows(wealth_paths),
    }


def ci_mean(values: np.ndarray, z: float = 1.96) -> tuple[float, float]:
    values = np.asarray(values, dtype=float)
    se = values.std(ddof=1) / np.sqrt(len(values))
    mean = values.mean()
    return float(mean - z * se), float(mean + z * se)


def summarize_simulation(sim: dict, planned_total: float) -> dict:
    terminal = sim["terminal_wealth"]
    withdrawn = sim["total_withdrawn"]
    ruined = sim["ruined"].astype(float)
    p5 = float(np.quantile(terminal, 0.05))
    es5 = float(terminal[terminal <= p5].mean())
    ruined_months = sim["ruin_month"][sim["ruin_month"] > 0]
    return {
        "ruin_probability": float(ruined.mean()),
        "ruin_probability_ci95": list(ci_mean(ruined)),
        "terminal_wealth_mean": float(terminal.mean()),
        "terminal_wealth_median": float(np.median(terminal)),
        "terminal_wealth_p05": p5,
        "terminal_wealth_expected_shortfall_5pct": es5,
        "terminal_wealth_p95": float(np.quantile(terminal, 0.95)),
        "total_withdrawn_mean": float(withdrawn.mean()),
        "total_withdrawn_p05": float(np.quantile(withdrawn, 0.05)),
        "spending_shortfall_vs_full_plan": float(1.0 - withdrawn.mean() / planned_total),
        "prob_spending_below_90pct_plan": float((withdrawn < 0.90 * planned_total).mean()),
        "avg_cut_months": float(sim["cut_months"].mean()),
        "avg_max_drawdown": float(sim["max_drawdown"].mean()),
        "median_ruin_month_if_ruined": float(np.median(ruined_months)) if len(ruined_months) else None,
    }


def paired_delta(dynamic_sim: dict, fixed_sim: dict) -> dict:
    ruin_diff = dynamic_sim["ruined"].astype(float) - fixed_sim["ruined"].astype(float)
    terminal_diff = dynamic_sim["terminal_wealth"] - fixed_sim["terminal_wealth"]
    spending_diff = dynamic_sim["total_withdrawn"] - fixed_sim["total_withdrawn"]
    return {
        "delta_ruin_probability": float(ruin_diff.mean()),
        "delta_ruin_probability_ci95": list(ci_mean(ruin_diff)),
        "delta_terminal_wealth_mean": float(terminal_diff.mean()),
        "delta_terminal_wealth_ci95": list(ci_mean(terminal_diff)),
        "delta_total_withdrawn_mean": float(spending_diff.mean()),
        "delta_total_withdrawn_ci95": list(ci_mean(spending_diff)),
    }


def run_experiment(refresh: bool) -> dict:
    data, data_meta = build_real_return_data(refresh)
    rng = np.random.default_rng(SEED)
    return_paths = moving_block_bootstrap(data["real_6040"].to_numpy(), rng)
    vol_threshold = data_meta["vol_threshold_ann"]

    all_summaries: dict[str, dict[str, dict]] = {}
    all_deltas: dict[str, dict[str, dict]] = {}
    raw_main_sims: dict[str, dict] = {}

    for wr in WITHDRAWAL_RATES:
        planned_total = INITIAL_WEALTH * wr * HORIZON_MONTHS / 12.0
        wr_key = f"{wr:.1%}"
        sims = {
            policy.key: simulate_policy(return_paths, policy, wr, vol_threshold)
            for policy in POLICIES
        }
        all_summaries[wr_key] = {
            policy.key: summarize_simulation(sims[policy.key], planned_total)
            for policy in POLICIES
        }
        all_deltas[wr_key] = {
            policy.key: paired_delta(sims[policy.key], sims["fixed"])
            for policy in POLICIES
            if policy.key != "fixed"
        }
        if abs(wr - MAIN_WITHDRAWAL_RATE) < 1e-12:
            raw_main_sims = sims

    literature = [
        {
            "citation": "Bengen (1994), Determining Withdrawal Rates Using Historical Data, Journal of Financial Planning",
            "url": "https://www.financialplanningassociation.org/sites/default/files/2020-05/7%20Determining%20Withdrawal%20Rates%20Using%20Historical%20Data.pdf",
            "role": "constant real withdrawal benchmark",
        },
        {
            "citation": "Guyton and Klinger (2006), Decision Rules and Maximum Initial Withdrawal Rates, Journal of Financial Planning",
            "url": "https://www.financialplanningassociation.org/article/journal/MAR06-decision-rules-and-maximum-initial-withdrawal-rates",
            "role": "flexible withdrawal guardrail motivation",
        },
        {
            "citation": "Finke, Pfau, and Blanchett (2013), The 4 Percent Rule Is Not Safe in a Low-Yield World, Journal of Financial Planning",
            "url": "https://www.financialplanningassociation.org/article/4-percent-rule-not-safe-low-yield-world",
            "role": "forward-looking caveat for fixed 4% rule",
        },
        {
            "citation": "CFA Institute FAJ summary (2017), Managing Sequence Risk to Optimize Retirement Income",
            "url": "https://rpc.cfainstitute.org/research/financial-analysts-journal/2017/managing-sequence-risk",
            "role": "sequence risk framing",
        },
    ]

    results = {
        "experiment_id": "k1505",
        "title": "Vol-aware withdrawal rules for sequence-of-returns risk",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "methodology_type": "simulation_with_empirical_inputs",
        "not_an_oos_forecast": True,
        "data": data_meta,
        "config": {
            "seed": SEED,
            "n_paths": N_PATHS,
            "horizon_months": HORIZON_MONTHS,
            "block_size_months": BLOCK_SIZE_MONTHS,
            "initial_wealth": INITIAL_WEALTH,
            "withdrawal_rates": WITHDRAWAL_RATES,
            "main_withdrawal_rate": MAIN_WITHDRAWAL_RATE,
            "stock_weight": STOCK_WEIGHT,
            "bond_weight": BOND_WEIGHT,
            "vol_window_months": VOL_WINDOW_MONTHS,
            "vol_threshold_quantile": VOL_THRESHOLD_QUANTILE,
            "vol_threshold_ann": vol_threshold,
            "drawdown_threshold": DRAWDOWN_THRESHOLD,
            "withdrawal_cut": WITHDRAWAL_CUT,
            "withdrawal_timing": "beginning_of_month_before_return",
            "timing_rule": "month-t withdrawal signal uses returns and wealth through t-1 only",
        },
        "policy_definitions": {
            p.key: {
                "label": p.label,
                "use_lagged_realized_vol": p.use_vol,
                "use_lagged_drawdown": p.use_drawdown,
                "withdrawal_cut_when_triggered": p.cut,
            }
            for p in POLICIES
        },
        "literature": literature,
        "main_results_4pct": all_summaries["4.0%"],
        "paired_deltas_vs_fixed_4pct": all_deltas["4.0%"],
        "sensitivity_by_withdrawal_rate": all_summaries,
        "paired_deltas_by_withdrawal_rate": all_deltas,
        "limitations": [
            "ETF/CPI sample starts in 2006 because local CPIAUCSL cache starts there; the 30-year horizon is bootstrapped, not a true 30-year historical cohort.",
            "The vol threshold is calibrated on the full empirical sample for descriptive simulation, so this is not marketed as an OOS timing signal.",
            "Withdrawal cuts improve solvency only by reducing spending; the simulation reports spending shortfall explicitly and does not model utility or essential-expense floors.",
            "Taxes, fees, advisor behavior, annuities, Social Security, and required minimum distributions are excluded.",
        ],
    }

    save_results(results)
    make_figures(results, raw_main_sims)
    return results


def save_results(results: dict) -> None:
    out_path = HERE / "k1505_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")


def make_figures(results: dict, raw_main_sims: dict[str, dict]) -> None:
    labels = [POLICIES[i].label for i in range(len(POLICIES))]
    keys = [p.key for p in POLICIES]
    main = results["main_results_4pct"]

    ruin = [main[k]["ruin_probability"] * 100.0 for k in keys]
    shortfall = [main[k]["spending_shortfall_vs_full_plan"] * 100.0 for k in keys]

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    colors = ["#4c78a8", "#f58518", "#54a24b", "#b279a2"]
    axes[0].bar(labels, ruin, color=colors)
    axes[0].set_ylabel("Ruin probability (%)")
    axes[0].set_title("30-year ruin risk at 4% real withdrawal")
    axes[0].tick_params(axis="x", rotation=20)
    axes[1].bar(labels, shortfall, color=colors)
    axes[1].set_ylabel("Mean spending shortfall vs full plan (%)")
    axes[1].set_title("Cost of dynamic withdrawal cuts")
    axes[1].tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1505_ruin_shortfall.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    terminal_millions = [raw_main_sims[k]["terminal_wealth"] / 1_000_000.0 for k in keys]
    ax.boxplot(terminal_millions, tick_labels=labels, showfliers=False)
    ax.set_ylabel("Terminal wealth ($ millions, real)")
    ax.set_title("Terminal wealth distribution, 10k bootstrap paths")
    ax.tick_params(axis="x", rotation=20)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1505_terminal_distribution.png", dpi=180)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 5))
    rate_labels = list(results["sensitivity_by_withdrawal_rate"].keys())
    x = [float(label.rstrip("%")) for label in rate_labels]
    for policy in POLICIES:
        y = [
            results["sensitivity_by_withdrawal_rate"][label][policy.key][
                "ruin_probability"
            ]
            * 100.0
            for label in rate_labels
        ]
        ax.plot(x, y, marker="o", label=policy.label)
    ax.set_xlabel("Initial withdrawal rate (%)")
    ax.set_ylabel("Ruin probability (%)")
    ax.set_title("Sensitivity to withdrawal rate")
    ax.legend(frameon=False)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "k1505_ruin_sensitivity.png", dpi=180)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="refresh yfinance ETF cache")
    args = parser.parse_args()
    results = run_experiment(refresh=args.refresh)
    main = results["main_results_4pct"]
    print(json.dumps({
        "experiment_id": results["experiment_id"],
        "data_period": [results["data"]["monthly_start"], results["data"]["monthly_end"]],
        "n_months": results["data"]["n_months"],
        "fixed_4pct_ruin_probability": main["fixed"]["ruin_probability"],
        "combined_cut_ruin_probability": main["combined_cut"]["ruin_probability"],
        "combined_cut_spending_shortfall": main["combined_cut"]["spending_shortfall_vs_full_plan"],
    }, indent=2))


if __name__ == "__main__":
    main()
