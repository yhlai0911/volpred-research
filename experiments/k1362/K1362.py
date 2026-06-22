"""K1362: Public option-flow crowd proxies as short-vol timing signals.

The source task asks whether aggregate call demand can time SPY returns,
VIX changes, or short-vol drawdowns. True ACIB / open-buy order imbalance
needs proprietary option order-flow data. This experiment uses only public
Cboe aggregate put/call volume archives and treats them as proxies.

Lookahead rule: every predictive regression uses predictor_lag1 =
signal.shift(1), so option volume observed on t-1 predicts target outcomes
starting on t.
"""
from __future__ import annotations

import io
import json
import math
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.stats as st
import statsmodels.api as sm
import yfinance as yf

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

EXPERIMENT_ID = "K1362"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
FIG_DIR = ROOT / "figures"
RESULTS_PATH = ROOT / f"{EXPERIMENT_ID}_results.json"
SEED = 42

CBOE_URLS = {
    "total_archive": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpcarchive.csv",
    "total_current": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/totalpc.csv",
    "equity_archive": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypcarchive.csv",
    "equity_current": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/equitypc.csv",
    "index_archive": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/indexpcarchive.csv",
    "index_current": "https://cdn.cboe.com/resources/options/volume_and_call_put_ratios/indexpc.csv",
}


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FIG_DIR.mkdir(parents=True, exist_ok=True)


def fetch_text(url: str, cache_name: str, refresh: bool = False) -> str:
    path = DATA_DIR / cache_name
    if path.exists() and not refresh:
        return path.read_text(encoding="utf-8", errors="replace")
    req = Request(url, headers={"User-Agent": "volpred-k1362/1.0"})
    with urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    path.write_text(text, encoding="utf-8")
    return text


def _find_header(lines: list[str]) -> int:
    for i, line in enumerate(lines):
        first = line.split(",", 1)[0].strip().lower()
        if first in {"date", "trade_date"}:
            return i
    raise ValueError("Could not locate Cboe CSV header row")


def parse_cboe_csv(text: str, family: str) -> pd.DataFrame:
    lines = text.splitlines()
    header_idx = _find_header(lines)
    df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
    df.columns = [str(c).strip().lower().replace(" ", "_").replace("/", "_") for c in df.columns]

    date_col = "date" if "date" in df.columns else "trade_date"
    pcr_col = next(
        c
        for c in df.columns
        if (
            c == "p_c_ratio"
            or c.endswith("_p_c_ratio")
            or ("ratio" in c and ("p_c" in c or "pc" in c))
        )
    )
    call_col = next(c for c in df.columns if c in {"call", "calls", f"{family}_call_volume"})
    put_col = next(c for c in df.columns if c in {"put", "puts", f"{family}_put_volume"})
    total_col = next(c for c in df.columns if c in {"total", f"{family}_total_volume"})

    out = pd.DataFrame(
        {
            "date": pd.to_datetime(df[date_col], errors="coerce"),
            f"{family}_call": pd.to_numeric(df[call_col].astype(str).str.replace(",", ""), errors="coerce"),
            f"{family}_put": pd.to_numeric(df[put_col].astype(str).str.replace(",", ""), errors="coerce"),
            f"{family}_total": pd.to_numeric(df[total_col].astype(str).str.replace(",", ""), errors="coerce"),
            f"{family}_pcr": pd.to_numeric(df[pcr_col], errors="coerce"),
        }
    ).dropna(subset=["date", f"{family}_call", f"{family}_put", f"{family}_total", f"{family}_pcr"])
    out = out.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
    return out


def load_cboe(refresh: bool = False) -> pd.DataFrame:
    pieces: dict[str, list[pd.DataFrame]] = {"total": [], "equity": [], "index": []}
    for key, url in CBOE_URLS.items():
        family = key.split("_", 1)[0]
        text = fetch_text(url, f"{key}.csv", refresh=refresh)
        parsed = parse_cboe_csv(text, family)
        parsed.to_csv(DATA_DIR / f"parsed_{key}.csv")
        pieces[family].append(parsed)

    merged_family = []
    for family, dfs in pieces.items():
        df = pd.concat(dfs).sort_index()
        df = df[~df.index.duplicated(keep="last")]
        df.to_csv(DATA_DIR / f"cboe_{family}_put_call.csv")
        merged_family.append(df)

    cboe = pd.concat(merged_family, axis=1, sort=True).sort_index()
    cboe = cboe.dropna(subset=["equity_pcr", "index_pcr", "total_pcr"])
    cboe.to_csv(DATA_DIR / "cboe_put_call_panel.csv")
    return cboe


def download_prices(refresh: bool = False) -> pd.DataFrame:
    path = DATA_DIR / "market_prices_yfinance.csv"
    if path.exists() and not refresh:
        prices = pd.read_csv(path, index_col=0, parse_dates=True)
        prices.index.name = "date"
        return prices

    tickers = ["SPY", "^VIX", "SVXY", "VXX", "^IRX"]
    raw = yf.download(
        tickers,
        start="2006-10-01",
        end="2019-10-08",
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=False,
    )
    prices = pd.DataFrame(index=raw.index)
    for ticker in tickers:
        if isinstance(raw.columns, pd.MultiIndex):
            close = raw[(ticker, "Close")]
        else:
            close = raw["Close"]
        prices[ticker.replace("^", "")] = close
    prices.index.name = "date"
    prices.to_csv(path)
    return prices


def rolling_z(series: pd.Series, window: int = 252, min_periods: int = 126) -> pd.Series:
    mean = series.rolling(window, min_periods=min_periods).mean()
    std = series.rolling(window, min_periods=min_periods).std()
    return (series - mean) / std.replace(0, np.nan)


def forward_sum(ret: pd.Series, horizon: int) -> pd.Series:
    if horizon == 1:
        return ret
    return ret.rolling(horizon).sum().shift(-(horizon - 1))


def standardize(s: pd.Series) -> pd.Series:
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return s * np.nan
    return (s - s.mean()) / std


@dataclass
class RegressionSpec:
    signal: str
    target: str
    horizon: int
    expected: str


def hac_regression(df: pd.DataFrame, spec: RegressionSpec) -> dict:
    signal_col = f"{spec.signal}_lag1"
    control_cols = ["vix_level_lag1", "vix_change_lag1", "spy_ret_lag1"]
    cols = [spec.target, signal_col, *control_cols]
    d = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    d = d.apply(standardize)
    d = d.dropna()
    if len(d) < 250:
        return {"n": int(len(d)), "error": "insufficient_observations"}

    y = d[spec.target]
    x = sm.add_constant(d[[signal_col, *control_cols]])
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": max(spec.horizon, 1)})
    coef = float(model.params[signal_col])
    tval = float(model.tvalues[signal_col])
    pval = float(model.pvalues[signal_col])
    expected_pass = (spec.expected == "positive" and tval >= 3.0) or (
        spec.expected == "negative" and tval <= -3.0
    )
    return {
        "n": int(len(d)),
        "r2": float(model.rsquared),
        "signal_term": signal_col,
        "coef": coef,
        "t_hac": tval,
        "p_hac": pval,
        "expected_direction": spec.expected,
        "harvey_expected_pass": bool(expected_pass),
        "params": {k: float(v) for k, v in model.params.items()},
        "tvalues": {k: float(v) for k, v in model.tvalues.items()},
    }


def summarize_quintiles(df: pd.DataFrame, signal: str, target: str, horizon: int) -> dict:
    rng = np.random.default_rng(SEED)
    cols = [f"{signal}_lag1", target]
    d = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    if len(d) < 250:
        return {"n": int(len(d)), "error": "insufficient_observations"}
    q80 = d[f"{signal}_lag1"].quantile(0.8)
    top = d.loc[d[f"{signal}_lag1"] >= q80, target]
    rest = d.loc[d[f"{signal}_lag1"] < q80, target]
    diff = float(top.mean() - rest.mean())
    welch = st.ttest_ind(top, rest, equal_var=False, nan_policy="omit")
    boot = []
    top_values = top.to_numpy()
    rest_values = rest.to_numpy()
    for _ in range(1000):
        top_s = rng.choice(top_values, size=len(top_values), replace=True)
        rest_s = rng.choice(rest_values, size=len(rest_values), replace=True)
        boot.append(float(np.mean(top_s) - np.mean(rest_s)))
    ci = np.quantile(boot, [0.025, 0.975])
    return {
        "n": int(len(d)),
        "top_quintile_n": int(len(top)),
        "rest_n": int(len(rest)),
        "horizon": horizon,
        "top_mean": float(top.mean()),
        "rest_mean": float(rest.mean()),
        "diff_top_minus_rest": diff,
        "welch_t": float(welch.statistic),
        "p_value": float(welch.pvalue),
        "bootstrap_ci": [float(ci[0]), float(ci[1])],
    }


def max_drawdown(ret: pd.Series) -> float:
    wealth = np.exp(ret.fillna(0).cumsum())
    dd = wealth / wealth.cummax() - 1
    return float(dd.min())


def annualized_sharpe(log_ret: pd.Series) -> float:
    r = log_ret.dropna()
    if r.empty or r.std(ddof=0) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=0) * math.sqrt(252))


def drawdown_diagnostic(df: pd.DataFrame, signal: str) -> dict:
    d = df[[f"{signal}_lag1", "svxy_ret_1d"]].dropna()
    q80 = d[f"{signal}_lag1"].quantile(0.8)
    top = d.loc[d[f"{signal}_lag1"] >= q80, "svxy_ret_1d"]
    rest = d.loc[d[f"{signal}_lag1"] < q80, "svxy_ret_1d"]
    rolling_threshold = (
        df[f"{signal}_lag1"]
        .rolling(252, min_periods=126)
        .quantile(0.8)
        .shift(1)
        .reindex(d.index)
    )
    risk_off = (d[f"{signal}_lag1"] >= rolling_threshold).fillna(False).astype(float)
    gated = d["svxy_ret_1d"] * (1.0 - risk_off)
    bh = d["svxy_ret_1d"]
    tail_cut = -0.03
    top_tail = float((top <= tail_cut).mean())
    rest_tail = float((rest <= tail_cut).mean())
    return {
        "top_quintile_n": int(len(top)),
        "rest_n": int(len(rest)),
        "risk_off_fraction": float(risk_off.mean()),
        "top_quintile_mean_return": float(top.mean()),
        "rest_mean_return": float(rest.mean()),
        "tail_threshold": tail_cut,
        "top_tail_hit_rate": top_tail,
        "rest_tail_hit_rate": rest_tail,
        "tail_hit_rate_diff": top_tail - rest_tail,
        "gated_strategy": {
            "rule": f"hold cash instead of SVXY when {signal}_lag1 exceeds its lagged rolling 252d 80th percentile",
            "mean_log_return": float(gated.mean()),
            "annualized_log_return": float(gated.mean() * 252),
            "sharpe": annualized_sharpe(gated),
            "max_drawdown": max_drawdown(gated),
            "risk_off_fraction": float(risk_off.mean()),
        },
        "buy_hold_svxy": {
            "mean_log_return": float(bh.mean()),
            "annualized_log_return": float(bh.mean() * 252),
            "sharpe": annualized_sharpe(bh),
            "max_drawdown": max_drawdown(bh),
        },
    }


def build_panel(cboe: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    panel = cboe.join(prices, how="inner")
    panel["spy_ret"] = np.log(panel["SPY"] / panel["SPY"].shift(1))
    panel["vix_change"] = panel["VIX"].diff()
    panel["vix_level"] = np.log(panel["VIX"])
    panel["svxy_ret"] = np.log(panel["SVXY"] / panel["SVXY"].shift(1))
    panel["vxx_ret"] = np.log(panel["VXX"] / panel["VXX"].shift(1))
    panel["tbill_daily"] = (panel["IRX"] / 100.0) / 252.0
    panel["spy_excess"] = panel["spy_ret"] - panel["tbill_daily"].fillna(0)

    panel["equity_call_share"] = panel["equity_call"] / panel["equity_total"]
    panel["index_call_share"] = panel["index_call"] / panel["index_total"]
    panel["total_call_share"] = panel["total_call"] / panel["total_total"]
    panel["equity_call_demand"] = -panel["equity_pcr"]
    panel["equity_call_share_z"] = rolling_z(panel["equity_call_share"])
    panel["equity_call_demand_z"] = rolling_z(panel["equity_call_demand"])
    panel["call_crowd_gap_z"] = rolling_z(panel["equity_call_share"] - panel["index_call_share"])
    panel["equity_volume_z"] = rolling_z(np.log(panel["equity_total"]))
    panel["call_crowd_intensity_z"] = rolling_z(panel["equity_call_share_z"] + 0.5 * panel["equity_volume_z"])
    panel["index_hedge_pcr_z"] = rolling_z(panel["index_pcr"])
    panel["equity_minus_index_pcr_z"] = rolling_z(panel["equity_pcr"] - panel["index_pcr"])

    signals = [
        "equity_call_share_z",
        "equity_call_demand_z",
        "call_crowd_gap_z",
        "call_crowd_intensity_z",
        "equity_minus_index_pcr_z",
    ]
    for col in signals:
        panel[f"{col}_lag1"] = panel[col].shift(1)

    panel["vix_level_lag1"] = panel["vix_level"].shift(1)
    panel["vix_change_lag1"] = panel["vix_change"].shift(1)
    panel["spy_ret_lag1"] = panel["spy_ret"].shift(1)

    for horizon in [1, 5]:
        panel[f"spy_excess_{horizon}d"] = forward_sum(panel["spy_excess"], horizon)
        panel[f"vix_change_{horizon}d"] = forward_sum(panel["vix_change"], horizon)
        panel[f"svxy_ret_{horizon}d"] = forward_sum(panel["svxy_ret"], horizon)
        panel[f"neg_vxx_ret_{horizon}d"] = -forward_sum(panel["vxx_ret"], horizon)

    panel["svxy_ret_1d"] = panel["svxy_ret_1d"]
    panel.to_csv(DATA_DIR / "k1362_panel.csv")
    return panel


def run(refresh: bool = False) -> dict:
    ensure_dirs()
    cboe = load_cboe(refresh=refresh)
    prices = download_prices(refresh=refresh)
    panel = build_panel(cboe, prices)

    signals = [
        "equity_call_share_z",
        "equity_call_demand_z",
        "call_crowd_gap_z",
        "call_crowd_intensity_z",
        "equity_minus_index_pcr_z",
    ]
    target_specs = []
    for signal in signals:
        for horizon in [1, 5]:
            target_specs.extend(
                [
                    RegressionSpec(signal, f"spy_excess_{horizon}d", horizon, "negative"),
                    RegressionSpec(signal, f"vix_change_{horizon}d", horizon, "positive"),
                    RegressionSpec(signal, f"svxy_ret_{horizon}d", horizon, "negative"),
                ]
            )

    regressions = {
        f"{s.signal}_to_{s.target}": hac_regression(panel, s)
        for s in target_specs
    }
    passes = {k: v for k, v in regressions.items() if v.get("harvey_expected_pass")}

    quintiles = {}
    for signal in signals:
        for target, horizon in [
            ("spy_excess_5d", 5),
            ("vix_change_5d", 5),
            ("svxy_ret_5d", 5),
        ]:
            quintiles[f"{signal}_top_quintile_to_{target}"] = summarize_quintiles(
                panel, signal, target, horizon
            )

    drawdowns = {signal: drawdown_diagnostic(panel, signal) for signal in signals}

    verdict = verdict_from_results(regressions, drawdowns)
    figures = make_figures(panel, regressions)
    sample = {
        "start": str(panel.dropna(subset=["equity_call_share_z"]).index.min().date()),
        "end": str(panel.index.max().date()),
        "n_panel_observations": int(len(panel)),
        "n_signal_observations_after_rolling_z": int(panel["equity_call_share_z"].dropna().shape[0]),
        "cboe_archive_end": str(cboe.index.max().date()),
        "svxy_sample_start": str(panel["SVXY"].dropna().index.min().date()),
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Public option-flow crowd proxies as short-vol timing signals",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "data_sources": {
            "cboe": CBOE_URLS,
            "market_prices": "yfinance adjusted close for SPY, ^VIX, SVXY, VXX, ^IRX",
        },
        "sample": sample,
        "method": {
            "signals": {
                "equity_call_share_z": "252d rolling z-score of equity call volume share = call/(call+put)",
                "equity_call_demand_z": "252d rolling z-score of negative equity put/call ratio",
                "call_crowd_gap_z": "252d rolling z-score of equity call share minus index call share",
                "call_crowd_intensity_z": "252d rolling z-score of equity call-share z plus half equity-volume z",
                "equity_minus_index_pcr_z": "252d rolling z-score of equity P/C minus index P/C",
            },
            "lookahead_policy": "all predictive regressions use signal.shift(1) via *_lag1 columns",
            "targets": "SPY excess log return, VIX close-to-close change, and SVXY log return over 1d and 5d horizons",
            "controls": "lagged log VIX, lagged VIX change, lagged SPY return",
            "harvey_bar": "expected-direction HAC |t| >= 3",
        },
        "related_prior": {
            "K191": "PCR not available through yfinance; VIX-derived proxies were mixed/null and must not be relabeled as true PCR.",
            "K523": "VIX percentile proxy did not supply robust contrarian alpha; actual Cboe PCR availability was a limitation.",
        },
        "literature": [
            "Cao, Li, Zhan, and Zhou (2026), Betting Against the Crowd: Option Trading and Market Risk Premium, JFQA forthcoming.",
            "Pan and Poteshman (2006), The Information in Option Volume for Future Stock Prices, Review of Financial Studies.",
            "Cboe U.S. Options Daily Market Statistics and Cboe put/call ratio CSV archives.",
            "OCC market-data reports document exchange-traded options volume as a public market-data source.",
        ],
        "regressions": regressions,
        "harvey_expected_passes": passes,
        "top_quintile_diagnostics": quintiles,
        "svxy_drawdown_diagnostics": drawdowns,
        "figures": figures,
        "limitations": [
            "Public Cboe put/call archives are aggregate volume ratios, not customer open-buy minus open-sell order imbalance.",
            "Free bulk Cboe CSV archives used here stop on 2019-10-04, so the 2020-2026 retail-options boom is outside the primary test window.",
            "Cboe archive notes warn that some post-2012 volume is preliminary reported volume rather than cleared OCC volume.",
            "SVXY is an actual short-vol ETF proxy and changed exposure after the 2018 XIV event; results are not direct option-strategy P&L.",
            "Aggregate equity/index P/C split cannot identify retail vs institutional flow.",
        ],
        "key_findings": [
            f"harvey_expected_pass_count={len(passes)}",
            f"verdict={verdict}",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    return results


def verdict_from_results(regressions: dict, drawdowns: dict) -> str:
    passes = [k for k, v in regressions.items() if v.get("harvey_expected_pass")]
    short_vol_passes = [k for k in passes if "_to_svxy_ret_" in k]
    if len(passes) >= 2 and short_vol_passes:
        return "CONDITIONAL_PUBLIC_PROXY_PASS"

    drawdown_flags = []
    for row in drawdowns.values():
        mdd_improves = row["gated_strategy"]["max_drawdown"] > row["buy_hold_svxy"]["max_drawdown"] + 0.05
        sharpe_improves = row["gated_strategy"]["sharpe"] > row["buy_hold_svxy"]["sharpe"] + 0.25
        tail_worse = row["top_tail_hit_rate"] > row["rest_tail_hit_rate"] + 0.02
        if mdd_improves and sharpe_improves and tail_worse:
            drawdown_flags.append(True)
    if passes or drawdown_flags:
        return "WEAK_DIAGNOSTIC_NULL_STRONG_TIMING"
    return "NULL_PUBLIC_PROXY_NO_STRONG_TIMING"


def make_figures(panel: pd.DataFrame, regressions: dict) -> list[str]:
    figures = []
    p = panel[["equity_pcr", "index_pcr", "total_pcr"]].dropna()
    fig, ax = plt.subplots(figsize=(11, 5))
    p.rolling(21).mean().plot(ax=ax, linewidth=1.4)
    ax.set_title("Cboe put/call ratios, 21-day average")
    ax.set_ylabel("Put/call ratio")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1362_cboe_put_call_ratios.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    figures.append(str(path.relative_to(ROOT)))

    rows = []
    for key, row in regressions.items():
        if row.get("error"):
            continue
        rows.append({"key": key, "t_hac": row["t_hac"], "pass": row["harvey_expected_pass"]})
    tdf = pd.DataFrame(rows).sort_values("t_hac")
    keep = pd.concat([tdf.head(10), tdf.tail(10)]).drop_duplicates("key")
    fig, ax = plt.subplots(figsize=(10, 7))
    colors = ["#b91c1c" if x else "#334155" for x in keep["pass"]]
    ax.barh(range(len(keep)), keep["t_hac"], color=colors)
    ax.axvline(3, color="#0f766e", linestyle="--", linewidth=1)
    ax.axvline(-3, color="#0f766e", linestyle="--", linewidth=1)
    ax.set_yticks(range(len(keep)))
    ax.set_yticklabels(keep["key"], fontsize=7)
    ax.set_xlabel("HAC t-stat on lagged public option-flow proxy")
    ax.set_title("Most extreme K1362 predictive t-statistics")
    ax.grid(axis="x", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1362_predictive_tstats.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    figures.append(str(path.relative_to(ROOT)))

    signal = "equity_call_share_z_lag1"
    d = panel[[signal, "svxy_ret_5d"]].dropna()
    q80 = d[signal].quantile(0.8)
    top = d.loc[d[signal] >= q80, "svxy_ret_5d"]
    rest = d.loc[d[signal] < q80, "svxy_ret_5d"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(["Top call-demand quintile", "Other days"], [top.mean() * 100, rest.mean() * 100], color=["#b91c1c", "#334155"])
    ax.set_ylabel("Mean 5-day SVXY log return (%)")
    ax.set_title("Short-vol proxy after high public equity call demand")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = FIG_DIR / "k1362_svxy_top_quintile.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    figures.append(str(path.relative_to(ROOT)))
    return figures


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Ignore cached Cboe/yfinance files")
    args = parser.parse_args()
    out = run(refresh=args.refresh)
    print(json.dumps({"ok": True, "verdict": out["verdict"], "sample": out["sample"]}, indent=2))
