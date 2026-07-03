#!/usr/bin/env python3
"""K1615: Algorithmic-pricing antitrust enforcement event windows.

Question
--------
Do public DOJ/FTC algorithmic-pricing antitrust enforcement milestones around
RealPage-style rental pricing and hotel pricing algorithms coincide with higher
realized volatility, downside variance, or market-adjusted returns for public
apartment REIT and travel-pricing equity proxies?

Honesty scope
-------------
This is an event-window public-proxy diagnostic, not a causal legal-risk
identification design. RealPage, Greystar, Cortland, and most named landlords
are private or subsidiaries, so public tickers are imperfect sector proxies.

Lookahead policy
----------------
Event dates are public announcement dates. The experiment is not a forecasting
model. Event windows are [t-1, t+10] around the next trading date on or after
the announcement. No outcome information is used to choose events or tickers.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats
from statsmodels.stats.multitest import multipletests


SEED = 42
np.random.seed(SEED)

ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
FIG_DIR = EXP_DIR / "figures"
OUT_JSON = EXP_DIR / "K1615_results.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

START = "2022-01-01"
END = (datetime.now(timezone.utc).date() + timedelta(days=1)).isoformat()
EVENT_PRE = 1
EVENT_POST = 10
BASELINE_PRE_START = 63
BASELINE_PRE_END = 11
HAC_LAGS = EVENT_POST
EPS = 1e-12

APARTMENT_REITS = ["AVB", "EQR", "UDR", "ESS", "CPT", "MAA"]
TRAVEL_PRICING = ["JETS", "MAR", "HLT", "H", "ABNB", "BKNG", "EXPE"]
CONTROLS = ["SPY", "VNQ", "XLY", "^VIX"]
ALL_TICKERS = sorted(set(APARTMENT_REITS + TRAVEL_PRICING + CONTROLS))

BASKETS = {
    "APARTMENT_REIT_BASKET": APARTMENT_REITS,
    "TRAVEL_PRICING_BASKET": TRAVEL_PRICING,
}


@dataclass(frozen=True)
class Event:
    event_date: str
    event_type: str
    label: str
    source_url: str
    source_kind: str


EVENTS = [
    Event(
        "2023-11-15",
        "residential",
        "DOJ statement of interest in RealPage rental-software MDL",
        "https://www.justice.gov/atr/statements-interest",
        "DOJ case document index",
    ),
    Event(
        "2024-03-01",
        "residential",
        "DOJ statement of interest in Duffy v. Yardi algorithmic rent case",
        "https://www.justice.gov/atr/statements-interest",
        "DOJ case document index",
    ),
    Event(
        "2024-03-28",
        "travel",
        "FTC/DOJ statement of interest in hotel room algorithmic price-fixing case",
        "https://www.ftc.gov/news-events/news/press-releases/2024/03/ftc-doj-file-statement-interest-hotel-room-algorithmic-price-fixing-case",
        "FTC press release",
    ),
    Event(
        "2024-08-23",
        "residential",
        "DOJ sues RealPage for algorithmic pricing scheme",
        "https://www.justice.gov/archives/opa/pr/justice-department-sues-realpage-algorithmic-pricing-scheme-harms-millions-american-renters",
        "DOJ press release",
    ),
    Event(
        "2025-01-07",
        "residential",
        "DOJ amended complaint adds six large landlords; Cortland proposed decree",
        "https://www.justice.gov/archives/opa/pr/justice-department-sues-six-large-landlords-algorithmic-pricing-scheme-harms-millions",
        "DOJ press release",
    ),
    Event(
        "2025-08-08",
        "residential",
        "DOJ proposed Greystar settlement",
        "https://www.justice.gov/opa/pr/justice-department-reaches-proposed-settlement-greystar-largest-us-landlord-end-its",
        "DOJ press release",
    ),
    Event(
        "2025-11-24",
        "residential",
        "DOJ proposed RealPage settlement",
        "https://www.justice.gov/opa/pr/justice-department-requires-realpage-end-sharing-competitively-sensitive-information-and",
        "DOJ press release",
    ),
    Event(
        "2025-12-23",
        "residential",
        "DOJ case docket posts LivCor proposed final judgment",
        "https://www.justice.gov/atr/case/us-and-plaintiff-states-v-realpage-inc",
        "DOJ case document index",
    ),
    Event(
        "2026-03-02",
        "residential",
        "DOJ case docket posts Greystar final judgment",
        "https://www.justice.gov/atr/case/us-and-plaintiff-states-v-realpage-inc",
        "DOJ case document index",
    ),
]


def git_rev() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finite_or_none(value):
    if isinstance(value, dict):
        return {k: finite_or_none(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_or_none(v) for v in value]
    if isinstance(value, tuple):
        return [finite_or_none(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if np.isfinite(value) else None
    return value


def fetch_prices(refresh: bool = False) -> tuple[pd.DataFrame, dict]:
    path = DATA_DIR / "yfinance_adjusted_close.csv"
    fetched = False
    if refresh or not path.exists():
        raw = yf.download(
            ALL_TICKERS,
            start=START,
            end=END,
            auto_adjust=True,
            progress=False,
            threads=False,
        )
        if raw.empty:
            raise RuntimeError("yfinance returned no rows")
        if isinstance(raw.columns, pd.MultiIndex):
            if "Close" not in raw.columns.get_level_values(0):
                raise RuntimeError(f"Expected Close field, got {raw.columns}")
            close = raw["Close"].copy()
        else:
            close = raw[["Close"]].copy()
            close.columns = [ALL_TICKERS[0]]
        close.index = pd.to_datetime(close.index).tz_localize(None).normalize()
        close = close.sort_index()
        close.to_csv(path)
        fetched = True
    close = pd.read_csv(path, index_col=0, parse_dates=True)
    close = close.sort_index()
    usable = close.dropna(axis=1, thresh=252)
    missing = sorted(set(["SPY", "VNQ", "XLY"]) - set(usable.columns))
    if missing:
        raise RuntimeError(f"Missing required controls after fetch/cache: {missing}")
    meta = {
        "source": "yfinance adjusted close (auto_adjust=True)",
        "cache_path": str(path.relative_to(ROOT)),
        "sha256": sha256_file(path),
        "fetched": fetched,
        "tickers_requested": ALL_TICKERS,
        "tickers_used": list(usable.columns),
        "start": str(usable.index.min().date()),
        "end": str(usable.index.max().date()),
        "n_trading_days": int(usable.shape[0]),
    }
    return usable, meta


def build_returns(close: pd.DataFrame) -> pd.DataFrame:
    returns = np.log(close).diff()
    out = returns.copy()
    for basket, tickers in BASKETS.items():
        used = [t for t in tickers if t in returns.columns]
        if len(used) < 2:
            raise RuntimeError(f"Basket {basket} has too few usable tickers: {used}")
        out[basket] = returns[used].mean(axis=1, skipna=True)
    return out.dropna(how="all")


def map_events_to_trading_days(index: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for event in EVENTS:
        event_date = pd.Timestamp(event.event_date)
        candidates = index[index >= event_date]
        if candidates.empty:
            trading_date = pd.NaT
            offset_days = None
        else:
            trading_date = candidates[0]
            offset_days = int((trading_date - event_date).days)
        rows.append({**asdict(event), "trading_date": trading_date, "calendar_to_trading_lag_days": offset_days})
    return pd.DataFrame(rows)


def add_event_dummies(panel: pd.DataFrame, event_table: pd.DataFrame) -> pd.DataFrame:
    out = panel.copy()
    for event_type in sorted({e.event_type for e in EVENTS}):
        out[f"{event_type}_window"] = 0
    out["any_event_window"] = 0
    out["event_count"] = 0
    date_to_pos = {date: pos for pos, date in enumerate(out.index)}
    for _, event in event_table.dropna(subset=["trading_date"]).iterrows():
        pos = date_to_pos.get(pd.Timestamp(event["trading_date"]))
        if pos is None:
            continue
        lo = max(0, pos - EVENT_PRE)
        hi = min(len(out) - 1, pos + EVENT_POST)
        cols = [f"{event['event_type']}_window", "any_event_window"]
        out.iloc[lo : hi + 1, out.columns.get_indexer(cols)] = 1
        out.iloc[lo : hi + 1, out.columns.get_loc("event_count")] += 1
    return out


def make_panel(returns: pd.DataFrame, event_table: pd.DataFrame) -> pd.DataFrame:
    cols = sorted(set(list(BASKETS.keys()) + APARTMENT_REITS + TRAVEL_PRICING + CONTROLS))
    cols = [c for c in cols if c in returns.columns]
    panel = returns[cols].copy()
    for col in cols:
        panel[f"{col}_rv"] = panel[col] ** 2
        panel[f"{col}_downside"] = np.minimum(panel[col], 0.0) ** 2
    panel["log_spy_rv"] = np.log(panel["SPY_rv"].clip(lower=EPS))
    panel["abs_spy_ret"] = panel["SPY"].abs()
    if "VNQ" in panel.columns:
        panel["log_vnq_rv"] = np.log(panel["VNQ_rv"].clip(lower=EPS))
    if "XLY" in panel.columns:
        panel["log_xly_rv"] = np.log(panel["XLY_rv"].clip(lower=EPS))
    if "^VIX" in panel.columns:
        panel["d_vix"] = panel["^VIX"].replace([np.inf, -np.inf], np.nan)
    else:
        panel["d_vix"] = np.nan
    return add_event_dummies(panel, event_table)


def hac_event_regression(panel: pd.DataFrame, target: str, event_dummy: str, sector_control: str | None) -> dict:
    y_col = f"{target}_rv"
    controls = ["log_spy_rv", "abs_spy_ret", "SPY"]
    if sector_control and sector_control in panel.columns:
        controls.append(sector_control)
    if panel["d_vix"].notna().sum() >= 252:
        controls.append("d_vix")
    needed = [y_col, event_dummy] + controls
    d = panel[needed].replace([np.inf, -np.inf], np.nan).dropna()
    if d.shape[0] < 252 or d[event_dummy].sum() < 5:
        return {
            "target": target,
            "event_dummy": event_dummy,
            "n": int(d.shape[0]),
            "n_event_days": int(d[event_dummy].sum()) if event_dummy in d else 0,
            "coef": None,
            "t": None,
            "p": None,
            "note": "insufficient rows or event-window days",
        }
    y = np.log(d[y_col].clip(lower=EPS))
    x = sm.add_constant(d[[event_dummy] + controls], has_constant="add")
    fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "target": target,
        "event_dummy": event_dummy,
        "n": int(d.shape[0]),
        "n_event_days": int(d[event_dummy].sum()),
        "coef": float(fit.params[event_dummy]),
        "t": float(fit.tvalues[event_dummy]),
        "p": float(fit.pvalues[event_dummy]),
        "controls": controls,
        "hac_lags": HAC_LAGS,
        "interpretation": "coef is log daily RV premium during event windows after market controls",
    }


def window_summary(panel: pd.DataFrame, event_table: pd.DataFrame, target: str, event_type: str) -> dict:
    rv_col = f"{target}_rv"
    down_col = f"{target}_downside"
    ret_col = target
    rows = []
    for _, event in event_table[event_table["event_type"] == event_type].dropna(subset=["trading_date"]).iterrows():
        pos = panel.index.get_indexer([pd.Timestamp(event["trading_date"])])[0]
        if pos < 0:
            continue
        win = panel.iloc[max(0, pos - EVENT_PRE) : min(len(panel), pos + EVENT_POST + 1)]
        base = panel.iloc[max(0, pos - BASELINE_PRE_START) : max(0, pos - BASELINE_PRE_END + 1)]
        if win.empty or base.empty:
            continue
        rv_base = float(base[rv_col].mean())
        down_base = float(base[down_col].mean())
        rows.append(
            {
                "event_date": str(pd.Timestamp(event["event_date"]).date()),
                "trading_date": str(pd.Timestamp(event["trading_date"]).date()),
                "label": event["label"],
                "window_mean_rv": float(win[rv_col].mean()),
                "baseline_mean_rv": rv_base,
                "rv_ratio": float(win[rv_col].mean() / rv_base) if rv_base > 0 else None,
                "window_mean_downside": float(win[down_col].mean()),
                "baseline_mean_downside": down_base,
                "downside_ratio": float(win[down_col].mean() / down_base) if down_base > 0 else None,
                "cum_target_return": float(win[ret_col].sum()),
                "cum_spy_adjusted_return": float((win[ret_col] - win["SPY"]).sum()),
                "n_window_days": int(win[rv_col].notna().sum()),
                "n_baseline_days": int(base[rv_col].notna().sum()),
            }
        )
    summary = pd.DataFrame(rows)
    if summary.empty:
        return {"target": target, "event_type": event_type, "events": [], "n_events": 0}
    return {
        "target": target,
        "event_type": event_type,
        "n_events": int(summary.shape[0]),
        "median_rv_ratio": float(summary["rv_ratio"].median()),
        "mean_rv_ratio": float(summary["rv_ratio"].mean()),
        "median_downside_ratio": float(summary["downside_ratio"].median()),
        "mean_downside_ratio": float(summary["downside_ratio"].mean()),
        "mean_cum_spy_adjusted_return": float(summary["cum_spy_adjusted_return"].mean()),
        "events": summary.to_dict(orient="records"),
    }


def make_figures(results: dict) -> list[str]:
    paths: list[str] = []
    direct_pairs = {
        ("APARTMENT_REIT_BASKET", "residential"),
        ("TRAVEL_PRICING_BASKET", "travel"),
    }
    summary_rows = []
    for item in results["window_summaries"]:
        if item["n_events"] > 0 and (item["target"], item["event_type"]) in direct_pairs:
            summary_rows.append(
                {
                    "target": item["target"],
                    "event_type": item["event_type"],
                    "median_rv_ratio": item["median_rv_ratio"],
                    "median_downside_ratio": item["median_downside_ratio"],
                }
            )
    if summary_rows:
        df = pd.DataFrame(summary_rows)
        fig, ax = plt.subplots(figsize=(8.2, 4.6))
        labels = [f"{r.target}\n{r.event_type}" for r in df.itertuples()]
        x = np.arange(len(df))
        ax.bar(x - 0.18, df["median_rv_ratio"], width=0.36, label="RV ratio")
        ax.bar(x + 0.18, df["median_downside_ratio"], width=0.36, label="Downside ratio")
        ax.axhline(1.0, color="black", lw=0.8)
        ax.set_ylabel("Median event-window / pre-event baseline")
        ax.set_title("K1615 direct enforcement event-window ratios")
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=8)
        ax.legend(frameon=False)
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        path = FIG_DIR / "k1615_event_window_ratios.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(ROOT)))

    regs = pd.DataFrame(results["regressions"][:2])
    regs = regs.dropna(subset=["t"])
    if not regs.empty:
        fig, ax = plt.subplots(figsize=(8.2, 4.2))
        labels = [f"{r.target}\n{r.event_dummy}" for r in regs.itertuples()]
        colors = ["#4C78A8" if v >= 0 else "#E45756" for v in regs["t"]]
        ax.bar(np.arange(len(regs)), regs["t"], color=colors)
        ax.axhline(3, color="black", lw=0.8, ls="--")
        ax.axhline(-3, color="black", lw=0.8, ls="--")
        ax.set_ylabel("HAC t-stat on event-window dummy")
        ax.set_title("K1615 controlled log-RV event-window regressions")
        ax.set_xticks(np.arange(len(regs)))
        ax.set_xticklabels(labels, rotation=30, ha="right", fontsize=8)
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        path = FIG_DIR / "k1615_event_regression_tstats.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        paths.append(str(path.relative_to(ROOT)))
    return paths


def determine_verdict(primary: list[dict]) -> tuple[str, str]:
    gateable = [r for r in primary if r.get("n_event_days", 0) >= 30 and r.get("coef") is not None]
    passes = [
        r
        for r in gateable
        if r.get("coef", 0) > 0 and abs(r.get("t", 0)) >= 3.0 and r.get("holm_p", 1.0) < 0.05
    ]
    directional = [r for r in gateable if r.get("coef", 0) > 0 and r.get("t", 0) > 1.65]
    if passes:
        return "PASS", "At least one direct basket event-window log-RV coefficient is positive, Holm-significant, and |t|>=3."
    if directional:
        return "DIRECTIONAL_ONLY", "At least one direct basket has positive event-window log-RV direction, but it fails the formal project gate."
    return "NULL", "No direct basket shows a formal or directional controlled log-RV event-window increase."


def main(refresh: bool = False) -> dict:
    close, price_meta = fetch_prices(refresh=refresh)
    returns = build_returns(close)
    event_table = map_events_to_trading_days(returns.index)
    panel = make_panel(returns, event_table)

    event_table.to_csv(DATA_DIR / "event_calendar.csv", index=False)
    panel.to_csv(DATA_DIR / "analysis_panel.csv")

    regressions = [
        hac_event_regression(panel, "APARTMENT_REIT_BASKET", "residential_window", "log_vnq_rv"),
        hac_event_regression(panel, "TRAVEL_PRICING_BASKET", "travel_window", "log_xly_rv"),
        hac_event_regression(panel, "APARTMENT_REIT_BASKET", "travel_window", "log_vnq_rv"),
        hac_event_regression(panel, "TRAVEL_PRICING_BASKET", "residential_window", "log_xly_rv"),
    ]

    individual_regs = []
    for target in APARTMENT_REITS:
        if target in panel.columns:
            individual_regs.append(hac_event_regression(panel, target, "residential_window", "log_vnq_rv"))
    for target in TRAVEL_PRICING:
        if target in panel.columns:
            individual_regs.append(hac_event_regression(panel, target, "travel_window", "log_xly_rv"))

    primary = regressions[:2]
    pvals = [r["p"] if r.get("p") is not None else 1.0 for r in primary]
    holm = multipletests(pvals, method="holm")[1] if pvals else []
    for r, hp in zip(primary, holm):
        r["holm_p"] = float(hp)
        r["primary_gate"] = bool(
            r.get("coef") is not None
            and r.get("coef", 0) > 0
            and abs(r.get("t", 0)) >= 3.0
            and float(hp) < 0.05
            and r.get("n_event_days", 0) >= 30
        )

    window_summaries = [
        window_summary(panel, event_table, "APARTMENT_REIT_BASKET", "residential"),
        window_summary(panel, event_table, "TRAVEL_PRICING_BASKET", "travel"),
        window_summary(panel, event_table, "APARTMENT_REIT_BASKET", "travel"),
        window_summary(panel, event_table, "TRAVEL_PRICING_BASKET", "residential"),
    ]

    verdict, summary = determine_verdict(primary)
    results = {
        "experiment_id": "K1615",
        "title": "Algorithmic-pricing antitrust enforcement event windows and public equity volatility proxies",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "git_rev": git_rev(),
        "seed": SEED,
        "verdict": verdict,
        "summary": summary,
        "task_id": "research_realpage_reit_vol",
        "scope": {
            "claim_strength": "public-proxy event-window diagnostic only; no causal RealPage exposure or trading rule claim",
            "event_window": f"t-{EVENT_PRE} through t+{EVENT_POST} trading days",
            "baseline_window": f"t-{BASELINE_PRE_START} through t-{BASELINE_PRE_END} trading days",
            "formal_test": "OLS on log daily realized variance with Newey-West HAC maxlags=10 and Holm correction over two direct basket tests",
            "gate": "positive coefficient, |t|>=3, Holm p<0.05, and >=30 event-window days",
        },
        "data": {
            "prices": price_meta,
            "baskets": BASKETS,
            "controls": CONTROLS,
            "events": event_table.assign(
                trading_date=event_table["trading_date"].astype(str)
            ).to_dict(orient="records"),
            "n_events_by_type": event_table["event_type"].value_counts().to_dict(),
            "analysis_panel_file": str((DATA_DIR / "analysis_panel.csv").relative_to(ROOT)),
            "event_calendar_file": str((DATA_DIR / "event_calendar.csv").relative_to(ROOT)),
        },
        "literature_and_source_context": [
            {
                "citation": "Calvano, Calzolari, Denicolo and Pastorello (2020), American Economic Review",
                "url": "https://www.aeaweb.org/articles?id=10.1257/aer.20190623",
                "use": "theoretical/experimental motivation that autonomous pricing algorithms can learn supracompetitive pricing",
            },
            {
                "citation": "Assad, Clark, Ershov and Xu (2024), Journal of Political Economy",
                "url": "https://ideas.repec.org/a/ucp/jpolec/doi10.1086-726906.html",
                "use": "empirical evidence that algorithmic-pricing adoption can change margins in retail gasoline markets",
            },
            {
                "citation": "Calder-Wang and Kim (2026), Algorithmic Pricing in Multifamily Rentals",
                "url": "https://www.ftc.gov/system/files/ftc_gov/pdf/calder-wangkim.pdf",
                "use": "multifamily rental-market context for RealPage-style algorithmic pricing",
            },
            {
                "citation": "DOJ/FTC public enforcement documents",
                "url": "https://www.justice.gov/atr/case/us-and-plaintiff-states-v-realpage-inc",
                "use": "official event-date calendar for RealPage-related milestones",
            },
        ],
        "regressions": regressions,
        "individual_regressions": individual_regs,
        "window_summaries": window_summaries,
        "limitations": [
            "Only RealPage-related residential events have multiple official milestones; the travel/hotel side has one FTC/DOJ statement and is non-gateable.",
            "Public apartment REIT and travel tickers are sector proxies, not direct RealPage user exposure measures.",
            "Event windows can capture broad market/legal-policy news, earnings, or rate shocks even with market controls.",
            "Daily close-to-close RV is a coarse proxy; no intraday realized variance is used.",
        ],
    }
    results["figures"] = make_figures(results)
    OUT_JSON.write_text(json.dumps(finite_or_none(results), indent=2, ensure_ascii=False))
    print(json.dumps({"verdict": verdict, "summary": summary, "out": str(OUT_JSON)}, indent=2))
    return results


if __name__ == "__main__":
    refresh_flag = "--refresh" in sys.argv
    main(refresh=refresh_flag)
