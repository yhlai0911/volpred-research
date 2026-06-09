"""K1439: USD regime conditional cross-asset realized volatility.

Question: Conditional on strong vs weak USD regime (DXY proxy = UUP),
are EM equity / gold / broad commodity / oil RVs systematically different?
Which assets are most regime-sensitive?

Differentiation vs related K:
- K878: DXY level *predicts* SPY vol (NULL). This is *conditioning* on regime, not predicting.
- K1435: GLD-DXY DCC FOMC *event-study*. This is unconditional regime buckets across multi-assets.

Lookahead protection:
- Regime indicator built from DXY 100d MA z-score, then shift(1) so the bucket on day t
  uses only info through t-1. 21d RV at t uses returns r[t-20..t] (backward-looking, no leak).
- Seed=42 for any random ops (no bootstrap here, but fixed anyway).

Method:
- Tickers: UUP (DXY proxy), EEM, GLD, DBC, USO, DBB
- Period: 2010-01-01 -> 2026-06-08
- Realized vol: 21d rolling std(log_ret) * sqrt(252)
- Regime A (level): 100d z-score of UUP price; z>+0.5 strong, z<-0.5 weak, else neutral
- Regime B (trend): 60d log-return sign; positive strong, negative weak
- Tests: Welch t (strong vs weak per asset), Levene (variance), Bonferroni alpha=0.05/N
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats

SEED = 42
np.random.seed(SEED)

OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

TICKERS = ["UUP", "EEM", "GLD", "DBC", "USO", "DBB"]
ASSET_TICKERS = [t for t in TICKERS if t != "UUP"]
START = "2010-01-01"
END = "2026-06-08"
RV_WINDOW = 21        # 21 trading days
DXY_MA_WINDOW = 100   # for regime A
TREND_WINDOW = 60     # for regime B
Z_THRESH = 0.5
ANNUALIZER = float(np.sqrt(252.0))


def fetch_prices(tickers: List[str]) -> pd.DataFrame:
    print(f"[fetch] {tickers} {START} -> {END}")
    df = yf.download(
        tickers,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )
    out = {}
    for t in tickers:
        try:
            ser = df[t]["Close"].rename(t)
        except Exception:
            try:
                ser = df["Close"][t].rename(t)
            except Exception:
                print(f"[warn] cannot extract {t}, skipping")
                continue
        ser = ser.dropna()
        if len(ser) < 252:
            print(f"[warn] {t} too short ({len(ser)} rows), skipping")
            continue
        out[t] = ser
    px = pd.DataFrame(out).sort_index()
    px = px.dropna(how="all")
    print(f"[fetch] price frame shape={px.shape}, range={px.index.min().date()}..{px.index.max().date()}")
    return px


def compute_rv(prices: pd.Series, window: int = RV_WINDOW) -> pd.Series:
    log_ret = np.log(prices).diff()
    rv = log_ret.rolling(window).std() * ANNUALIZER
    return rv


def build_regime_level(uup: pd.Series) -> pd.Series:
    ma = uup.rolling(DXY_MA_WINDOW).mean()
    sd = uup.rolling(DXY_MA_WINDOW).std()
    z = (uup - ma) / sd
    bucket = pd.Series(
        np.where(z > Z_THRESH, "strong",
                 np.where(z < -Z_THRESH, "weak", "neutral")),
        index=uup.index, name="regime_level",
    )
    bucket = bucket.shift(1)  # lookahead protection
    return bucket


def build_regime_trend(uup: pd.Series) -> pd.Series:
    log_ret_60d = np.log(uup).diff(TREND_WINDOW)
    bucket = pd.Series(
        np.where(log_ret_60d > 0, "strong",
                 np.where(log_ret_60d < 0, "weak", "neutral")),
        index=uup.index, name="regime_trend",
    )
    bucket = bucket.shift(1)  # lookahead protection
    return bucket


@dataclass
class RegimeStats:
    mean_rv: float
    median_rv: float
    std_rv: float
    n_days: int


def regime_stats(rv: pd.Series, regime: pd.Series) -> Dict[str, RegimeStats]:
    aligned = pd.concat([rv.rename("rv"), regime.rename("r")], axis=1).dropna()
    out = {}
    for label in ["strong", "weak", "neutral"]:
        sub = aligned.loc[aligned["r"] == label, "rv"]
        if len(sub) > 0:
            out[label] = RegimeStats(
                mean_rv=float(sub.mean()),
                median_rv=float(sub.median()),
                std_rv=float(sub.std()),
                n_days=int(len(sub)),
            )
        else:
            out[label] = RegimeStats(mean_rv=float("nan"), median_rv=float("nan"),
                                     std_rv=float("nan"), n_days=0)
    return out


def welch_levene(rv: pd.Series, regime: pd.Series) -> Dict[str, float]:
    aligned = pd.concat([rv.rename("rv"), regime.rename("r")], axis=1).dropna()
    strong = aligned.loc[aligned["r"] == "strong", "rv"].values
    weak = aligned.loc[aligned["r"] == "weak", "rv"].values
    if len(strong) < 30 or len(weak) < 30:
        return {"welch_t": float("nan"), "welch_p": float("nan"),
                "levene_p": float("nan"),
                "n_strong": int(len(strong)), "n_weak": int(len(weak)),
                "diff_mean_rv": float("nan")}
    t_stat, p_val = stats.ttest_ind(strong, weak, equal_var=False)
    lev_stat, lev_p = stats.levene(strong, weak, center="median")
    return {
        "welch_t": float(t_stat),
        "welch_p": float(p_val),
        "levene_stat": float(lev_stat),
        "levene_p": float(lev_p),
        "n_strong": int(len(strong)),
        "n_weak": int(len(weak)),
        "mean_strong_rv": float(strong.mean()),
        "mean_weak_rv": float(weak.mean()),
        "diff_mean_rv": float(strong.mean() - weak.mean()),
    }


def make_bar_figure(rv_by_asset_regime: pd.DataFrame, out_path: Path, title: str) -> None:
    fig, ax = plt.subplots(figsize=(10, 5.5))
    assets = list(rv_by_asset_regime.index)
    x = np.arange(len(assets))
    w = 0.27
    order = ["strong", "weak", "neutral"]
    colors = {"strong": "#1f77b4", "weak": "#d62728", "neutral": "#7f7f7f"}
    for i, reg in enumerate(order):
        vals = rv_by_asset_regime[reg].astype(float).values
        ax.bar(x + (i - 1) * w, vals, width=w, color=colors[reg],
               label=f"{reg} USD")
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_ylabel("Mean 21d annualized RV")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    print(f"[fig] saved {out_path}")


def main() -> Dict:
    px = fetch_prices(TICKERS)
    if "UUP" not in px.columns:
        raise RuntimeError("UUP missing — cannot build regime indicator")
    uup = px["UUP"].dropna()

    rv = pd.DataFrame({t: compute_rv(px[t].dropna()) for t in px.columns})

    reg_level = build_regime_level(uup)
    reg_trend = build_regime_trend(uup)

    asset_list = [t for t in ASSET_TICKERS if t in rv.columns]

    regime_stats_out: Dict[str, Dict[str, dict]] = {}
    tests_out: Dict[str, dict] = {}

    n_tests = len(asset_list)
    bonf_alpha = 0.05 / max(n_tests, 1)

    for asset in asset_list:
        rvs_a = rv[asset]
        rstats = regime_stats(rvs_a, reg_level)
        regime_stats_out[asset] = {k: vars(v) for k, v in rstats.items()}
        tres = welch_levene(rvs_a, reg_level)
        tres["bonferroni_alpha"] = bonf_alpha
        p = tres.get("welch_p", float("nan"))
        tres["bonferroni_significant"] = bool((p == p) and (p < bonf_alpha))
        tests_out[asset] = tres

    trend_tests: Dict[str, dict] = {}
    for asset in asset_list:
        tres = welch_levene(rv[asset], reg_trend)
        tres["bonferroni_alpha"] = bonf_alpha
        p = tres.get("welch_p", float("nan"))
        tres["bonferroni_significant"] = bool((p == p) and (p < bonf_alpha))
        trend_tests[asset] = tres

    concord_sig = 0
    concord_sign = 0
    for asset in asset_list:
        sig_l = tests_out[asset]["bonferroni_significant"]
        sig_t = trend_tests[asset]["bonferroni_significant"]
        sign_l = np.sign(tests_out[asset]["diff_mean_rv"])
        sign_t = np.sign(trend_tests[asset]["diff_mean_rv"])
        if sig_l == sig_t:
            concord_sig += 1
        if sign_l == sign_t:
            concord_sign += 1

    mean_table = pd.DataFrame(
        {reg: {a: regime_stats_out[a][reg]["mean_rv"] for a in asset_list}
         for reg in ["strong", "weak", "neutral"]}
    )
    make_bar_figure(
        mean_table, FIG_DIR / "rv_by_regime_level.png",
        "K1439: Mean 21d RV by USD level regime (UUP z-score)",
    )

    mean_table_trend = pd.DataFrame(
        index=asset_list, columns=["strong", "weak", "neutral"], dtype=float
    )
    for asset in asset_list:
        rstats = regime_stats(rv[asset], reg_trend)
        for k, v in rstats.items():
            mean_table_trend.loc[asset, k] = v.mean_rv
    make_bar_figure(
        mean_table_trend, FIG_DIR / "rv_by_regime_trend.png",
        "K1439 Robustness: Mean 21d RV by USD 60d-trend regime",
    )

    n_sig = sum(1 for a in asset_list if tests_out[a]["bonferroni_significant"])
    n_sig_trend = sum(1 for a in asset_list if trend_tests[a]["bonferroni_significant"])
    most_sensitive = None
    if asset_list:
        most_sensitive = max(
            asset_list,
            key=lambda a: abs(tests_out[a].get("welch_t", 0.0))
                          if tests_out[a].get("welch_t") == tests_out[a].get("welch_t")
                          else 0.0,
        )

    if n_sig >= 2 and concord_sign >= max(2, n_tests - 1):
        verdict = "PASS"
        verdict_reason = (
            f"{n_sig}/{n_tests} assets show Bonferroni-significant RV difference "
            f"between strong vs weak USD level regime, with sign concordant across "
            f"trend regime in {concord_sign}/{n_tests} assets."
        )
    elif n_sig >= 1:
        verdict = "CONDITIONAL_PASS"
        verdict_reason = (
            f"{n_sig}/{n_tests} assets pass Bonferroni; trend-regime sign concordance "
            f"{concord_sign}/{n_tests}. Effect not universal but isolated to {most_sensitive}."
        )
    else:
        verdict = "NULL"
        verdict_reason = (
            f"0/{n_tests} assets pass Bonferroni alpha={bonf_alpha:.4f}. "
            f"USD regime does not systematically condition cross-asset RV at significance."
        )

    period = {
        "start": str(px.index.min().date()),
        "end": str(px.index.max().date()),
        "n_obs": int(px.shape[0]),
    }

    result = {
        "k_id": "K1439",
        "title": "USD regime conditional cross-asset realized volatility",
        "hypothesis": (
            "Conditional on strong vs weak USD regime (DXY proxy=UUP), "
            "EM/gold/commodity/oil 21d realized vols differ systematically."
        ),
        "period": period,
        "tickers": asset_list,
        "uup_obs": int(uup.dropna().shape[0]),
        "regime_def": {
            "level_primary": {
                "indicator": "UUP - 100d MA, divided by 100d std",
                "strong": f"z > +{Z_THRESH}",
                "weak": f"z < -{Z_THRESH}",
                "neutral": "else",
                "lookahead_protection": "shift(1) on bucket",
            },
            "trend_robustness": {
                "indicator": "UUP 60d log-return sign",
                "strong": "60d log-return > 0",
                "weak": "60d log-return < 0",
                "neutral": "exact zero",
                "lookahead_protection": "shift(1) on bucket",
            },
        },
        "rv_definition": "21d rolling std of daily log returns, annualized by sqrt(252)",
        "regime_stats_level": regime_stats_out,
        "tests_level": tests_out,
        "tests_trend": trend_tests,
        "bonferroni_alpha": bonf_alpha,
        "robustness": {
            "n_tests": n_tests,
            "n_bonferroni_sig_level": n_sig,
            "n_bonferroni_sig_trend": n_sig_trend,
            "level_vs_trend_sig_concordance": f"{concord_sig}/{n_tests}",
            "level_vs_trend_sign_concordance": f"{concord_sign}/{n_tests}",
        },
        "most_sensitive_asset_by_abs_welch_t": most_sensitive,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "lookahead_protected": True,
        "seed": SEED,
        "figures": [
            "figures/rv_by_regime_level.png",
            "figures/rv_by_regime_trend.png",
        ],
    }

    out_path = OUT_DIR / "k1439_results.json"
    out_path.write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    print(f"[done] results -> {out_path}")
    print(f"[done] verdict={verdict} | {verdict_reason}")
    return result


if __name__ == "__main__":
    main()
