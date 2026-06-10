"""K1448: Inflation-expectation regime and forward stock/bond volatility.

Question:
  Using yfinance-only ETF proxies for inflation expectations, do rising-vs-falling
  inflation-expectation regimes imply different forward 21d realized volatility
  and forward 21d stock-bond correlation?

Design:
  - Proxies: TIP/IEF and TIP/TLT relative-performance ratios.
  - Signal at t uses 63d log-ratio change observed at t-1 via shift(1).
  - Outcomes are forward 21d RV and forward 21d rolling correlation on returns
    t+1..t+21, avoiding same-day leakage.
  - Primary inference uses HAC(Newey-West, maxlags=21) because outcomes overlap.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.formula.api as smf
import yfinance as yf

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

START = "2010-01-01"
END = "2026-06-10"
SIGNAL_WINDOW = 63
OUTCOME_WINDOW = 21
HAC_LAGS = 21
ANNUALIZER = float(np.sqrt(252.0))
TICKERS = ["TIP", "IEF", "TLT", "SPY"]


@dataclass
class OutcomeSummary:
    mean: float
    median: float
    std: float
    n_days: int


def fetch_prices() -> pd.DataFrame:
    for attempt in range(3):
        try:
            raw = yf.download(
                TICKERS,
                start=START,
                end=END,
                auto_adjust=True,
                progress=False,
                threads=True,
                group_by="ticker",
            )
            out = {}
            for ticker in TICKERS:
                try:
                    ser = raw[ticker]["Close"].rename(ticker)
                except Exception:
                    ser = raw["Close"][ticker].rename(ticker)
                out[ticker] = ser.dropna()
            df = pd.DataFrame(out).sort_index().dropna()
            if not df.empty:
                return df
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] download attempt {attempt + 1}/3 failed: {exc}")
        time.sleep(2 + attempt)
    raise RuntimeError("yfinance download failed after 3 attempts")


def compute_forward_rv(price: pd.Series, window: int = OUTCOME_WINDOW) -> pd.Series:
    log_ret = np.log(price).diff()
    rv = log_ret.shift(-1).rolling(window).std() * ANNUALIZER
    return rv.shift(-(window - 1))


def compute_forward_corr(
    left_price: pd.Series,
    right_price: pd.Series,
    window: int = OUTCOME_WINDOW,
) -> pd.Series:
    left_ret = np.log(left_price).diff()
    right_ret = np.log(right_price).diff()
    corr = left_ret.shift(-1).rolling(window).corr(right_ret.shift(-1))
    return corr.shift(-(window - 1))


def build_regime(proxy_ratio: pd.Series, window: int = SIGNAL_WINDOW) -> pd.Series:
    signal = np.log(proxy_ratio).diff(window).shift(1)
    regime = pd.Series(
        np.where(signal > 0, "rising", "falling"),
        index=signal.index,
        name="regime",
    )
    regime[signal.isna()] = np.nan
    return regime


def summarize(frame: pd.DataFrame, outcome_col: str) -> Dict[str, OutcomeSummary]:
    out: Dict[str, OutcomeSummary] = {}
    for label in ["falling", "rising"]:
        sub = frame.loc[frame["regime"] == label, outcome_col]
        out[label] = OutcomeSummary(
            mean=float(sub.mean()),
            median=float(sub.median()),
            std=float(sub.std()),
            n_days=int(len(sub)),
        )
    return out


def hac_regression(frame: pd.DataFrame, outcome_col: str) -> Dict[str, Dict[str, float]]:
    model = smf.ols(
        f'{outcome_col} ~ C(regime, Treatment(reference="falling"))',
        data=frame,
    ).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    out: Dict[str, Dict[str, float]] = {}
    for key in model.params.index:
        out[key] = {
            "coef": float(model.params[key]),
            "se_hac": float(model.bse[key]),
            "t_hac": float(model.tvalues[key]),
            "p_hac": float(model.pvalues[key]),
        }
    out["meta"] = {
        "n_obs": int(model.nobs),
        "r2": float(model.rsquared),
        "hac_maxlags": HAC_LAGS,
    }
    return out


def bonferroni_bh(pvals: list[tuple[str, float]]) -> Dict[str, Dict[str, float]]:
    m = len(pvals)
    ranked = sorted(pvals, key=lambda x: x[1])
    bh_raw = [min(p * m / rank, 1.0) for rank, (_, p) in enumerate(ranked, start=1)]
    bh_adj = [0.0] * m
    running = 1.0
    for idx in range(m - 1, -1, -1):
        running = min(running, bh_raw[idx])
        bh_adj[idx] = running
    out: Dict[str, Dict[str, float]] = {}
    for idx, (label, p) in enumerate(ranked):
        out[label] = {
            "raw_p": float(p),
            "bonferroni_p": float(min(p * m, 1.0)),
            "bh_p": float(bh_adj[idx]),
            "rank": int(idx + 1),
        }
    return out


def make_bar_chart(results: Dict[str, Dict], out_path: Path) -> None:
    rows = []
    for proxy_name, payload in results.items():
        for outcome_name, summary in payload["summaries"].items():
            rising = summary["rising"]["mean"]
            falling = summary["falling"]["mean"]
            rows.append((f"{proxy_name}\n{outcome_name}", rising, falling))
    labels = [r[0] for r in rows]
    rising_vals = [r[1] for r in rows]
    falling_vals = [r[2] for r in rows]
    x = np.arange(len(labels))
    width = 0.36
    fig, ax = plt.subplots(figsize=(10.5, 5.4))
    ax.bar(x - width / 2, falling_vals, width, label="Falling infl. exp.", color="#4c72b0")
    ax.bar(x + width / 2, rising_vals, width, label="Rising infl. exp.", color="#dd8452")
    ax.set_title("K1448: Forward outcomes by inflation-expectation regime")
    ax.set_ylabel("Outcome mean")
    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def make_proxy_chart(prices: pd.DataFrame, out_path: Path) -> None:
    ratio_tip_ief = (prices["TIP"] / prices["IEF"]).rename("TIP/IEF")
    ratio_tip_tlt = (prices["TIP"] / prices["TLT"]).rename("TIP/TLT")
    fig, ax = plt.subplots(figsize=(10.5, 4.8))
    ax.plot(ratio_tip_ief.index, ratio_tip_ief / ratio_tip_ief.iloc[0], label="TIP/IEF", lw=1.2)
    ax.plot(ratio_tip_tlt.index, ratio_tip_tlt / ratio_tip_tlt.iloc[0], label="TIP/TLT", lw=1.2)
    ax.set_title("K1448: Inflation-expectation proxy ratios (rebased)")
    ax.set_ylabel("Rebased level")
    ax.grid(True, alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def analyze_proxy(name: str, prices: pd.DataFrame) -> Dict:
    if name == "tip_over_ief":
        ratio = prices["TIP"] / prices["IEF"]
    elif name == "tip_over_tlt":
        ratio = prices["TIP"] / prices["TLT"]
    else:
        raise ValueError(name)

    regime = build_regime(ratio)
    outcomes = {
        "fwd_rv_spy": compute_forward_rv(prices["SPY"]).rename("fwd_rv_spy"),
        "fwd_rv_ief": compute_forward_rv(prices["IEF"]).rename("fwd_rv_ief"),
        "fwd_rv_tlt": compute_forward_rv(prices["TLT"]).rename("fwd_rv_tlt"),
        "fwd_corr_spy_ief": compute_forward_corr(prices["SPY"], prices["IEF"]).rename("fwd_corr_spy_ief"),
        "fwd_corr_spy_tlt": compute_forward_corr(prices["SPY"], prices["TLT"]).rename("fwd_corr_spy_tlt"),
    }

    summaries: Dict[str, Dict] = {}
    hac: Dict[str, Dict] = {}
    acf: Dict[str, Dict[str, float]] = {}
    pvals: list[tuple[str, float]] = []
    regime_counts = None

    for outcome_name, outcome in outcomes.items():
        frame = pd.concat([regime, outcome], axis=1).dropna()
        if regime_counts is None:
            regime_counts = frame["regime"].value_counts().sort_index().to_dict()
        stats_by_regime = summarize(frame, outcome_name)
        summaries[outcome_name] = {k: asdict(v) for k, v in stats_by_regime.items()}
        hac_result = hac_regression(frame, outcome_name)
        hac[outcome_name] = hac_result
        pvals.append(
            (
                f"{name}:{outcome_name}:rising_minus_falling",
                hac_result['C(regime, Treatment(reference="falling"))[T.rising]']["p_hac"],
            )
        )
        acf[outcome_name] = {
            "lag_1": float(frame[outcome_name].autocorr(1)),
            "lag_5": float(frame[outcome_name].autocorr(5)),
            "lag_21": float(frame[outcome_name].autocorr(21)),
        }

    return {
        "proxy_name": name,
        "signal_window_days": SIGNAL_WINDOW,
        "regime_counts": regime_counts,
        "proxy_level_stats": {
            "ratio_mean": float(ratio.mean()),
            "ratio_std": float(ratio.std()),
            "ratio_min": float(ratio.min()),
            "ratio_max": float(ratio.max()),
        },
        "summaries": summaries,
        "hac_regression": hac,
        "outcome_acf": acf,
        "pvals": pvals,
    }


def main() -> Dict:
    prices = fetch_prices()
    analyses = {
        "tip_over_ief": analyze_proxy("tip_over_ief", prices),
        "tip_over_tlt": analyze_proxy("tip_over_tlt", prices),
    }

    all_pvals = analyses["tip_over_ief"]["pvals"] + analyses["tip_over_tlt"]["pvals"]
    correction = bonferroni_bh(all_pvals)
    bonf_alpha = 0.05 / len(all_pvals)
    n_sig = int(sum(v["bonferroni_p"] < 0.05 for v in correction.values()))

    make_bar_chart(analyses, FIG_DIR / "forward_outcomes_by_regime.png")
    make_proxy_chart(prices, FIG_DIR / "inflation_proxy_ratios.png")

    if n_sig == 0:
        verdict = "NULL"
        verdict_reason = (
            "0/10 rising-vs-falling HAC contrasts survive Bonferroni correction; "
            "inflation-expectation proxy regimes are not robust short-horizon vol/corr signals."
        )
    else:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            f"{n_sig}/10 HAC contrasts survive Bonferroni correction; treat as descriptive "
            "cross-asset regime evidence, not a trading rule."
        )

    result = {
        "experiment_id": "K1448",
        "title": "Inflation-expectation regime and forward stock/bond volatility",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "period": {
            "start": str(prices.index.min().date()),
            "end": str(prices.index.max().date()),
            "n_obs_joint_prices": int(len(prices)),
        },
        "data_source": "yfinance (TIP, IEF, TLT, SPY)",
        "signal_definition": {
            "tip_over_ief": "log(TIP/IEF).diff(63).shift(1)",
            "tip_over_tlt": "log(TIP/TLT).diff(63).shift(1)",
        },
        "regime_definition": {
            "rising": "lagged 63d log-ratio change > 0",
            "falling": "lagged 63d log-ratio change <= 0",
        },
        "outcomes": {
            "forward_rv": "21d annualized realized vol using returns t+1..t+21",
            "forward_corr": "21d rolling correlation using returns t+1..t+21",
        },
        "lookahead_protection": {
            "signal": "proxy diff window shifted by 1 day",
            "outcome": "forward windows start at t+1",
        },
        "multiple_testing": {
            "n_hac_contrasts": len(all_pvals),
            "bonferroni_alpha": bonf_alpha,
        },
        "analyses": {
            "tip_over_ief": {k: v for k, v in analyses["tip_over_ief"].items() if k != "pvals"},
            "tip_over_tlt": {k: v for k, v in analyses["tip_over_tlt"].items() if k != "pvals"},
        },
        "multiple_test_correction": correction,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "figures": [
            "figures/forward_outcomes_by_regime.png",
            "figures/inflation_proxy_ratios.png",
        ],
    }

    out_path = OUT_DIR / "k1448_results.json"
    out_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason}, indent=2))
    return result


if __name__ == "__main__":
    main()
