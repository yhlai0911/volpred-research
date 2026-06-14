from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf


EXPERIMENT_ID = "research_long_vol_vs_gold_vs_treasury_crash"
EXPERIMENT_DIR = Path(__file__).resolve().parent
DATA_DIR = EXPERIMENT_DIR / "data"
RESULTS_PATH = EXPERIMENT_DIR / f"{EXPERIMENT_ID}_results.json"
FIG_HEATMAP = EXPERIMENT_DIR / "fig_oos_protection_matrix.png"
FIG_CUMULATIVE = EXPERIMENT_DIR / "fig_oos_strategy_cumulative.png"

START_DATE = "2018-01-25"
END_DATE = "2026-06-14"
TRAIN_END = "2021-12-31"
OOS_START = "2022-01-01"
BOOTSTRAP_B = 2000
SEED = 42
TCOST_BPS = 10.0
MIN_TRAIN_EVENTS_BY_TYPE = 5

PRICE_TICKERS = {
    "SPY": "SPY",
    "VXX": "VXX",
    "GLD": "GLD",
    "TLT": "TLT",
    "VIX": "^VIX",
    "TNX": "^TNX",
}
DEFENSE_ASSETS = ["VXX", "GLD", "TLT"]
SHOCK_TYPES = ["growth_shock", "rate_shock", "liquidity_shock", "mixed_shock"]


@dataclass
class StrategyResult:
    name: str
    total_return: float
    annual_return: float
    annual_vol: float
    sharpe: float
    max_drawdown: float
    active_days: int
    switches: int
    total_cost: float
    gross_mean_active_return: float
    net_mean_active_return: float


def safe_ticker_name(ticker: str) -> str:
    return ticker.replace("^", "index_").replace("=", "_").replace("-", "_")


def fetch_or_load_ticker(ticker: str, refresh: bool = False) -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{safe_ticker_name(ticker)}.csv"
    if path.exists() and not refresh:
        df = pd.read_csv(path, parse_dates=["Date"])
        df = df.set_index("Date").sort_index()
        return df

    df = yf.download(
        ticker,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    if df.empty:
        raise RuntimeError(f"yfinance returned no rows for {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    keep = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    out = df[keep].copy()
    out.index = pd.to_datetime(out.index).tz_localize(None)
    out = out.sort_index()
    out.to_csv(path, index_label="Date")
    return out


def load_panel(refresh: bool = False) -> pd.DataFrame:
    frames = []
    for label, ticker in PRICE_TICKERS.items():
        raw = fetch_or_load_ticker(ticker, refresh=refresh)
        close_col = "Adj Close" if "Adj Close" in raw.columns else "Close"
        px = raw[[close_col]].rename(columns={close_col: f"{label}_adj_close"})
        frames.append(px)
    panel = pd.concat(frames, axis=1, join="inner").dropna().sort_index()
    if panel.empty:
        raise RuntimeError("No common dates across downloaded tickers")

    for label in PRICE_TICKERS:
        panel[f"{label}_ret"] = panel[f"{label}_adj_close"].pct_change()
    panel["SPY_drawdown"] = panel["SPY_adj_close"] / panel["SPY_adj_close"].cummax() - 1.0
    panel["VIX_chg"] = panel["VIX_adj_close"].pct_change()
    panel["TNX_chg"] = panel["TNX_adj_close"].diff()
    panel = panel.dropna().copy()
    panel["event_signal"] = (
        (panel["SPY_ret"] <= -0.015)
        | ((panel["SPY_drawdown"] <= -0.08) & (panel["SPY_ret"] < 0))
    )
    panel["shock_type"] = panel.apply(classify_same_day_shock, axis=1)
    panel["lagged_signal"] = panel["event_signal"].shift(1).fillna(False).astype(bool)
    panel["lagged_shock_type"] = panel["shock_type"].shift(1)
    panel.loc[~panel["lagged_signal"], "lagged_shock_type"] = "no_signal"
    return panel


def classify_same_day_shock(row: pd.Series) -> str:
    if not bool(row.get("event_signal", False)):
        return "no_signal"

    tlt_ret = float(row["TLT_ret"])
    gld_ret = float(row["GLD_ret"])
    vix_chg = float(row["VIX_chg"])
    tnx_chg = float(row["TNX_chg"])

    if tlt_ret < 0 and gld_ret < 0 and vix_chg > 0.05:
        return "liquidity_shock"
    if tlt_ret < 0 and tnx_chg > 0:
        return "rate_shock"
    if tlt_ret > 0 and tnx_chg < 0:
        return "growth_shock"
    return "mixed_shock"


def event_matrix(
    df: pd.DataFrame,
    signal_col: str,
    type_col: str,
    event_return_prefix: str = "",
) -> dict[str, dict[str, dict[str, float | int]]]:
    events = df[df[signal_col]].copy()
    out: dict[str, dict[str, dict[str, float | int]]] = {}
    for shock_type in SHOCK_TYPES:
        sub = events[events[type_col] == shock_type]
        out[shock_type] = {}
        for asset in DEFENSE_ASSETS:
            if sub.empty:
                out[shock_type][asset] = {
                    "n": 0,
                    f"{event_return_prefix}mean_asset_return": math.nan,
                    f"{event_return_prefix}mean_protection_vs_spy": math.nan,
                    f"{event_return_prefix}win_rate_vs_spy": math.nan,
                    f"{event_return_prefix}positive_return_rate": math.nan,
                }
                continue
            protection = sub[f"{asset}_ret"] - sub["SPY_ret"]
            out[shock_type][asset] = {
                "n": int(len(sub)),
                f"{event_return_prefix}mean_asset_return": float(sub[f"{asset}_ret"].mean()),
                f"{event_return_prefix}mean_protection_vs_spy": float(protection.mean()),
                f"{event_return_prefix}win_rate_vs_spy": float((sub[f"{asset}_ret"] > sub["SPY_ret"]).mean()),
                f"{event_return_prefix}positive_return_rate": float((sub[f"{asset}_ret"] > 0).mean()),
            }
    return out


def choose_assets(train: pd.DataFrame) -> tuple[dict[str, str], dict[str, dict[str, float | int | str]]]:
    train_events = train[train["lagged_signal"]].copy()
    all_means = train_events[[f"{asset}_ret" for asset in DEFENSE_ASSETS]].mean()
    fallback_asset = str(all_means.idxmax()).replace("_ret", "")
    choices: dict[str, str] = {}
    diagnostics: dict[str, dict[str, float | int | str]] = {}

    for shock_type in SHOCK_TYPES:
        sub = train_events[train_events["lagged_shock_type"] == shock_type]
        if len(sub) >= MIN_TRAIN_EVENTS_BY_TYPE:
            means = sub[[f"{asset}_ret" for asset in DEFENSE_ASSETS]].mean()
            selected = str(means.idxmax()).replace("_ret", "")
            source = "type_specific_train"
        else:
            means = all_means
            selected = fallback_asset
            source = "fallback_all_train_events"
        choices[shock_type] = selected
        diagnostics[shock_type] = {
            "train_events": int(len(sub)),
            "selected_asset": selected,
            "selection_source": source,
            "train_mean_return_VXX": float(means["VXX_ret"]),
            "train_mean_return_GLD": float(means["GLD_ret"]),
            "train_mean_return_TLT": float(means["TLT_ret"]),
        }
    return choices, diagnostics


def evaluate_strategy(
    df: pd.DataFrame,
    name: str,
    active_weights: pd.DataFrame,
    cost_bps: float = TCOST_BPS,
) -> tuple[StrategyResult, pd.Series]:
    weights = active_weights.reindex(df.index).fillna(0.0)
    asset_returns = df[[f"{asset}_ret" for asset in DEFENSE_ASSETS]].to_numpy()
    gross = pd.Series((weights.to_numpy() * asset_returns).sum(axis=1), index=df.index, name=f"{name}_gross")
    turnover = weights.diff().abs().sum(axis=1)
    turnover.iloc[0] = weights.iloc[0].abs().sum()
    costs = turnover * (cost_bps / 10000.0)
    net = (gross - costs).rename(name)

    equity = (1.0 + net).cumprod()
    years = len(net) / 252.0
    total_return = float(equity.iloc[-1] - 1.0)
    annual_return = float(equity.iloc[-1] ** (1.0 / years) - 1.0) if years > 0 else math.nan
    annual_vol = float(net.std(ddof=1) * math.sqrt(252.0))
    sharpe = float(net.mean() / net.std(ddof=1) * math.sqrt(252.0)) if net.std(ddof=1) > 0 else math.nan
    max_drawdown = float((equity / equity.cummax() - 1.0).min())
    active = weights.sum(axis=1) > 0
    active_days = int(active.sum())
    active_names = weights.idxmax(axis=1).where(active, "CASH")
    switches = int((active_names != active_names.shift(1)).sum() - 1)
    switches = max(switches, 0)
    total_cost = float(costs.sum())
    result = StrategyResult(
        name=name,
        total_return=total_return,
        annual_return=annual_return,
        annual_vol=annual_vol,
        sharpe=sharpe,
        max_drawdown=max_drawdown,
        active_days=active_days,
        switches=switches,
        total_cost=total_cost,
        gross_mean_active_return=float(gross[active].mean()) if active_days else math.nan,
        net_mean_active_return=float(net[active].mean()) if active_days else math.nan,
    )
    return result, net


def weights_for_rule(df: pd.DataFrame, choices: dict[str, str]) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=df.index, columns=DEFENSE_ASSETS)
    active = df["lagged_signal"]
    for shock_type, asset in choices.items():
        mask = active & (df["lagged_shock_type"] == shock_type)
        weights.loc[mask, asset] = 1.0
    return weights


def weights_for_static(df: pd.DataFrame, asset: str) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=df.index, columns=DEFENSE_ASSETS)
    weights.loc[df["lagged_signal"], asset] = 1.0
    return weights


def weights_for_equal(df: pd.DataFrame) -> pd.DataFrame:
    weights = pd.DataFrame(0.0, index=df.index, columns=DEFENSE_ASSETS)
    weights.loc[df["lagged_signal"], DEFENSE_ASSETS] = 1.0 / len(DEFENSE_ASSETS)
    return weights


def paired_event_bootstrap(
    df: pd.DataFrame,
    rule_weights: pd.DataFrame,
    benchmark_weights: pd.DataFrame,
    rng: np.random.Generator,
) -> dict[str, float]:
    events = df[df["lagged_signal"]].copy()
    if events.empty:
        return {"n": 0, "mean_diff": math.nan, "ci_low": math.nan, "ci_high": math.nan, "p_two_sided": math.nan}

    rule = (rule_weights.loc[events.index].to_numpy() * events[[f"{a}_ret" for a in DEFENSE_ASSETS]].to_numpy()).sum(axis=1)
    bench = (
        benchmark_weights.loc[events.index].to_numpy()
        * events[[f"{a}_ret" for a in DEFENSE_ASSETS]].to_numpy()
    ).sum(axis=1)
    diff = rule - bench
    n = len(diff)
    boot = np.empty(BOOTSTRAP_B)
    for i in range(BOOTSTRAP_B):
        idx = rng.integers(0, n, size=n)
        boot[i] = float(diff[idx].mean())
    mean_diff = float(diff.mean())
    p_two_sided = float(2.0 * min((boot <= 0).mean(), (boot >= 0).mean()))
    return {
        "n": int(n),
        "mean_diff": mean_diff,
        "ci_low": float(np.quantile(boot, 0.025)),
        "ci_high": float(np.quantile(boot, 0.975)),
        "p_two_sided": min(p_two_sided, 1.0),
    }


def to_serializable_strategy(result: StrategyResult) -> dict[str, float | int | str]:
    return {
        "name": result.name,
        "total_return": result.total_return,
        "annual_return": result.annual_return,
        "annual_vol": result.annual_vol,
        "sharpe": result.sharpe,
        "max_drawdown": result.max_drawdown,
        "active_days": result.active_days,
        "switches": result.switches,
        "total_cost": result.total_cost,
        "gross_mean_active_return": result.gross_mean_active_return,
        "net_mean_active_return": result.net_mean_active_return,
    }


def plot_heatmap(matrix: dict[str, dict[str, dict[str, float | int]]]) -> None:
    values = np.array(
        [
            [float(matrix[shock_type][asset]["mean_protection_vs_spy"]) for asset in DEFENSE_ASSETS]
            for shock_type in SHOCK_TYPES
        ]
    )
    fig, ax = plt.subplots(figsize=(8, 4.8))
    vmax = np.nanmax(np.abs(values))
    im = ax.imshow(values, cmap="RdYlGn", vmin=-vmax, vmax=vmax)
    ax.set_xticks(range(len(DEFENSE_ASSETS)), DEFENSE_ASSETS)
    ax.set_yticks(range(len(SHOCK_TYPES)), [s.replace("_", " ") for s in SHOCK_TYPES])
    for i, shock_type in enumerate(SHOCK_TYPES):
        for j, asset in enumerate(DEFENSE_ASSETS):
            n = matrix[shock_type][asset]["n"]
            val = values[i, j]
            label = "NA" if np.isnan(val) else f"{val * 100:.2f}%\nn={n}"
            ax.text(j, i, label, ha="center", va="center", fontsize=9, color="black")
    ax.set_title("OOS lagged-signal mean protection vs SPY")
    cbar = fig.colorbar(im, ax=ax)
    cbar.set_label("asset return - SPY return")
    fig.tight_layout()
    fig.savefig(FIG_HEATMAP, dpi=160)
    plt.close(fig)


def plot_cumulative(strategy_returns: dict[str, pd.Series]) -> None:
    fig, ax = plt.subplots(figsize=(9, 5))
    for name, ret in strategy_returns.items():
        equity = (1.0 + ret).cumprod()
        ax.plot(equity.index, equity.values, label=name, linewidth=1.6)
    ax.axhline(1.0, color="black", linewidth=0.8)
    ax.set_title("OOS event-gated defensive strategies, net of 10 bps turnover cost")
    ax.set_ylabel("Growth of $1")
    ax.legend(loc="best", fontsize=8)
    fig.tight_layout()
    fig.savefig(FIG_CUMULATIVE, dpi=160)
    plt.close(fig)


def run(refresh: bool = False) -> dict:
    panel = load_panel(refresh=refresh)
    train = panel.loc[:TRAIN_END].copy()
    oos = panel.loc[OOS_START:].copy()
    if train.empty or oos.empty:
        raise RuntimeError("Train/OOS split produced an empty sample")

    choices, selection_diagnostics = choose_assets(train)
    rule_weights = weights_for_rule(oos, choices)

    strategies: dict[str, tuple[StrategyResult, pd.Series, pd.DataFrame]] = {}
    rule_result, rule_ret = evaluate_strategy(oos, "crash_type_rule", rule_weights)
    strategies["crash_type_rule"] = (rule_result, rule_ret, rule_weights)
    for asset in DEFENSE_ASSETS:
        weights = weights_for_static(oos, asset)
        result, ret = evaluate_strategy(oos, f"static_{asset}", weights)
        strategies[f"static_{asset}"] = (result, ret, weights)
    equal_weights = weights_for_equal(oos)
    equal_result, equal_ret = evaluate_strategy(oos, "equal_weight_defense", equal_weights)
    strategies["equal_weight_defense"] = (equal_result, equal_ret, equal_weights)

    oos_strategy_results = {name: to_serializable_strategy(value[0]) for name, value in strategies.items()}
    best_static_name = max([f"static_{a}" for a in DEFENSE_ASSETS], key=lambda name: oos_strategy_results[name]["sharpe"])
    rng = np.random.default_rng(SEED)
    bootstrap = {
        "rule_vs_equal_weight_event_gross": paired_event_bootstrap(
            oos,
            rule_weights,
            equal_weights,
            rng,
        ),
        "rule_vs_best_static_oos_event_gross": paired_event_bootstrap(
            oos,
            rule_weights,
            strategies[best_static_name][2],
            rng,
        ),
        "best_static_oos_by_sharpe": best_static_name,
        "B": BOOTSTRAP_B,
        "seed": SEED,
    }

    train_matrix = event_matrix(train, "lagged_signal", "lagged_shock_type")
    oos_matrix = event_matrix(oos, "lagged_signal", "lagged_shock_type")
    same_day_diagnostic_oos = event_matrix(
        oos,
        "event_signal",
        "shock_type",
        event_return_prefix="same_day_nontradable_",
    )
    plot_heatmap(oos_matrix)
    plot_cumulative({name: value[1] for name, value in strategies.items()})

    oos_counts = {
        shock_type: int(((oos["lagged_signal"]) & (oos["lagged_shock_type"] == shock_type)).sum())
        for shock_type in SHOCK_TYPES
    }
    train_counts = {
        shock_type: int(((train["lagged_signal"]) & (train["lagged_shock_type"] == shock_type)).sum())
        for shock_type in SHOCK_TYPES
    }
    rule_sharpe = float(oos_strategy_results["crash_type_rule"]["sharpe"])
    best_static_sharpe = float(oos_strategy_results[best_static_name]["sharpe"])
    rule_beats_best_static = bool(rule_sharpe > best_static_sharpe)
    rule_vs_best_boot = bootstrap["rule_vs_best_static_oos_event_gross"]
    significant_vs_best_static = bool(
        np.isfinite(rule_vs_best_boot["ci_low"])
        and rule_vs_best_boot["ci_low"] > 0
        and rule_vs_best_boot["p_two_sided"] < 0.05
    )
    if rule_beats_best_static and significant_vs_best_static:
        verdict = "PASS"
    elif rule_beats_best_static:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "data": {
            "source": "yfinance",
            "tickers": PRICE_TICKERS,
            "requested_start": START_DATE,
            "requested_end_exclusive": END_DATE,
            "common_sample_start": panel.index.min().strftime("%Y-%m-%d"),
            "common_sample_end": panel.index.max().strftime("%Y-%m-%d"),
            "n_daily_common": int(len(panel)),
            "train_end": TRAIN_END,
            "oos_start": OOS_START,
            "train_n": int(len(train)),
            "oos_n": int(len(oos)),
            "snapshot_files": sorted(str(p.relative_to(EXPERIMENT_DIR)) for p in DATA_DIR.glob("*.csv")),
        },
        "design": {
            "lookahead_guard": "Primary rule uses lagged_signal and lagged_shock_type: shock classification at t-1, defensive return at t.",
            "event_signal": "SPY_ret <= -1.5% OR SPY drawdown <= -8% and SPY_ret < 0.",
            "shock_classification": {
                "liquidity_shock": "event day with TLT_ret < 0, GLD_ret < 0, and VIX_chg > 5%",
                "rate_shock": "event day with TLT_ret < 0 and TNX_chg > 0",
                "growth_shock": "event day with TLT_ret > 0 and TNX_chg < 0",
                "mixed_shock": "event days not captured by the above rules",
            },
            "transaction_cost": f"{TCOST_BPS:.1f} bps per absolute change in traded asset weights.",
            "selection_rule": (
                "For each lagged shock type, choose the training asset with highest mean next-day return; "
                f"fallback to all training event days when type-specific n < {MIN_TRAIN_EVENTS_BY_TYPE}."
            ),
        },
        "event_counts": {
            "train_lagged_signal_by_type": train_counts,
            "oos_lagged_signal_by_type": oos_counts,
            "train_total_lagged_events": int(train["lagged_signal"].sum()),
            "oos_total_lagged_events": int(oos["lagged_signal"].sum()),
        },
        "asset_selection": selection_diagnostics,
        "matrices": {
            "train_lagged_signal": train_matrix,
            "oos_lagged_signal": oos_matrix,
            "oos_same_day_nontradable_diagnostic": same_day_diagnostic_oos,
        },
        "oos_strategy_results": oos_strategy_results,
        "bootstrap": bootstrap,
        "interpretation": {
            "main_result": (
                "Crash-type-aware defensive rotation does not beat the best static event-gated hedge "
                "after lagging the signal and charging turnover costs."
                if verdict == "NULL"
                else "Crash-type-aware rotation improves OOS performance, but bootstrap and small event counts determine claim strength."
            ),
            "rule_beats_best_static_by_sharpe": rule_beats_best_static,
            "significant_vs_best_static_event_bootstrap": significant_vs_best_static,
            "best_static_oos_by_sharpe": best_static_name,
            "figures": [FIG_HEATMAP.name, FIG_CUMULATIVE.name],
        },
    }

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh-data", action="store_true", help="Re-download yfinance data and overwrite CSV snapshots.")
    args = parser.parse_args()
    results = run(refresh=args.refresh_data)
    print(json.dumps({"ok": True, "verdict": results["verdict"], "results": str(RESULTS_PATH)}, indent=2))


if __name__ == "__main__":
    main()
