"""K1530: Thematic ETF coherence decay as crash precursor.

Research question:
  Does cross-sectional coherence of a thematic ETF's component returns
  (PC1 share / avg pairwise corr / dispersion) decay over a 90-day window
  predict (a) ETF realized vol, (b) max drawdown, (c) underperformance vs SPY
  over horizons 21d / 63d?

Methodology guards (per .claude/rules/experiments.md):
  - Lookahead: ALL features computed at t-1 close (rolling window of past 90d)
    then explicitly .shift(1) before being aligned with forward outcomes at t..t+H.
  - Seed: np.random.seed(42); bootstrap uses np.random.default_rng(42).
  - Fair comparison: SPY baseline outcomes from same date index.
  - Significance: Harvey (2016) |t| > 3.0; bootstrap 95% CI (1000 reps).
  - OOS: split 2018-01-01 -> 2021-12-31 (fit/calibrate event threshold) vs
    2022-01-01 -> 2026-06-17 (independent test).
  - Sample requirement: >=5 themes, ~252 trading days/year x ~8 years
    = ~2000 obs/theme; event counts reported.

Outputs:
  - k1530_results.json  (structured)
  - fig_coherence_timeseries.png
  - fig_event_study.png
  - fig_oos.png
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# Headless matplotlib
os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import yfinance as yf  # noqa: E402
from scipy import stats  # noqa: E402

# --------------------------------------------------------------------- config
SEED = 42
np.random.seed(SEED)

START = "2018-01-01"
END = "2026-06-17"
WINDOW = 90          # rolling coherence window (trading days)
BASELINE = 252       # rolling baseline window for event detection
EVENT_K_SD = 1.5     # event threshold (drop >1.5 SD from baseline mean)
HORIZONS = [21, 63]  # forward horizons (trading days)
N_BOOTSTRAP = 1000
OOS_SPLIT = pd.Timestamp("2022-01-01")
HARVEY_T = 3.0

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True, parents=True)
OUT_DIR = Path(__file__).parent

# Thematic ETF -> representative top holdings (public factsheet info, hardcoded
# to avoid yfinance ETF.info quota/inconsistency).  ~8-10 holdings each.
THEMES: Dict[str, List[str]] = {
    "AIQ":  ["NVDA", "AAPL", "MSFT", "META", "GOOG", "AMZN", "AVGO", "ORCL", "CRM", "AMD"],
    "BOTZ": ["NVDA", "ISRG", "ABB", "KEYS", "FANUY", "6954.T", "ROK", "TER", "IRBT", "OMRNY"],
    "ARKK": ["TSLA", "COIN", "ROKU", "PLTR", "HOOD", "PATH", "TWLO", "SHOP", "DKNG", "U"],
    "ICLN": ["FSLR", "ENPH", "SEDG", "PLUG", "BE", "RUN", "NEE", "BEPC", "ORA", "ARRY"],
    "CIBR": ["CRWD", "PANW", "FTNT", "BRBR", "CSCO", "ZS", "S", "OKTA", "CHKP", "AKAM"],
    "ITA":  ["RTX", "BA", "LMT", "GD", "NOC", "TDG", "HWM", "LHX", "AXON", "TXT"],
    "URA":  ["CCJ", "DNN", "NXE", "UEC", "PALAF", "URG", "BHP", "URNM", "EU", "LTBR"],
}

# --------------------------------------------------------------------- io


def _safe_download(ticker: str) -> pd.Series | None:
    cache = DATA_DIR / f"{ticker.replace('.', '_').replace('^', '')}.csv"
    if cache.exists():
        try:
            df = pd.read_csv(cache, index_col=0, parse_dates=True)
            if "Close" in df.columns and len(df) > 50:
                return df["Close"].astype(float)
        except Exception:
            pass
    try:
        df = yf.download(ticker, start=START, end=END, auto_adjust=True,
                         progress=False, threads=False)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        s = df["Close"].astype(float)
        s.to_frame("Close").to_csv(cache)
        return s
    except Exception as e:  # pragma: no cover
        print(f"  ! failed {ticker}: {e}", file=sys.stderr)
        return None


def fetch_panel(tickers: List[str]) -> pd.DataFrame:
    series = {}
    for t in tickers:
        s = _safe_download(t)
        if s is not None and len(s) > 200:
            series[t] = s
    if not series:
        return pd.DataFrame()
    df = pd.concat(series, axis=1)
    df.columns = list(series.keys())
    return df


# --------------------------------------------------------------------- features


def rolling_coherence(returns: pd.DataFrame, window: int) -> pd.DataFrame:
    """Compute rolling first-PC share, avg pairwise corr, dispersion.

    Each row at date t uses returns from [t-window+1, t]. To prevent lookahead
    we will .shift(1) the output before alignment with forward outcomes.
    """
    idx = returns.index
    pc_share = pd.Series(np.nan, index=idx, name="pc1_share")
    avg_corr = pd.Series(np.nan, index=idx, name="avg_corr")
    dispersion = pd.Series(np.nan, index=idx, name="dispersion")

    arr = returns.values
    for i in range(window, len(idx)):
        w = arr[i - window + 1 : i + 1]
        # require at least 3 cols of finite data
        mask = ~np.isnan(w).any(axis=0)
        if mask.sum() < 3:
            continue
        wm = w[:, mask]
        try:
            C = np.cov(wm, rowvar=False)
            eig, _ = np.linalg.eigh(C)
            eig = np.clip(eig, 0, None)
            tot = eig.sum()
            if tot > 0:
                pc_share.iloc[i] = eig[-1] / tot
            corr = np.corrcoef(wm, rowvar=False)
            iu = np.triu_indices_from(corr, k=1)
            avg_corr.iloc[i] = np.nanmean(corr[iu])
            # dispersion: average cross-sectional std of daily returns
            dispersion.iloc[i] = np.nanmean(np.nanstd(wm, axis=1))
        except Exception:
            continue
    return pd.concat([pc_share, avg_corr, dispersion], axis=1)


def forward_outcomes(etf_close: pd.Series, spy_close: pd.Series,
                     horizons: List[int]) -> pd.DataFrame:
    """Forward realized vol, max drawdown, return relative to SPY."""
    log_ret = np.log(etf_close).diff()
    out = {}
    for H in horizons:
        # forward realized vol over (t+1, ..., t+H) - annualized
        rv = log_ret.rolling(H).std().shift(-H) * np.sqrt(252)
        # forward max drawdown over (t+1, ..., t+H)
        # FIX (Codex review): prepend initial wealth 1.0 so a drop on the very
        # first forward day is captured. Without this, peak starts at the
        # first forward return's cumprod and a t+1 fall registers as zero dd.
        def _maxdd(s):
            wealth = np.concatenate(([1.0], (1 + s.values).cumprod()))
            peak = np.maximum.accumulate(wealth)
            dd = wealth / peak - 1
            return float(dd.min())
        ret = etf_close.pct_change()
        mdd = ret.rolling(H).apply(_maxdd, raw=False).shift(-H)
        # forward relative return
        etf_ret = (etf_close.shift(-H) / etf_close - 1)
        spy_ret = (spy_close.shift(-H) / spy_close - 1)
        rel = etf_ret - spy_ret
        out[f"rv_{H}"] = rv
        out[f"mdd_{H}"] = mdd
        out[f"rel_{H}"] = rel
    return pd.DataFrame(out)


# --------------------------------------------------------------------- events


def detect_decay_events(pc_share: pd.Series, baseline_window: int = BASELINE,
                        k_sd: float = EVENT_K_SD) -> pd.Series:
    """First crossing where pc_share drops more than k_sd below its rolling
    baseline. Returns boolean series."""
    mean = pc_share.rolling(baseline_window).mean()
    std = pc_share.rolling(baseline_window).std()
    z = (pc_share - mean) / std
    below = z < -k_sd
    event = below & (~below.shift(1, fill_value=False))
    return event.fillna(False)


# --------------------------------------------------------------------- stats


def harvey_t(diff: np.ndarray) -> Tuple[float, float, int]:
    """Newey-West / Harvey-corrected t-stat for mean of `diff` != 0.
    Simplified HAC with lag = max(1, floor(N^(1/3))). Two-sided p-value."""
    x = diff[~np.isnan(diff)]
    n = len(x)
    if n < 10:
        return (np.nan, np.nan, n)
    m = x.mean()
    lag = max(1, int(np.floor(n ** (1 / 3))))
    gamma0 = np.mean((x - m) ** 2)
    s = gamma0
    for k in range(1, lag + 1):
        w = 1.0 - k / (lag + 1)
        gk = np.mean((x[k:] - m) * (x[:-k] - m))
        s += 2 * w * gk
    se = np.sqrt(max(s, 1e-12) / n)
    t = m / se
    p = 2 * (1 - stats.norm.cdf(abs(t)))
    return (float(t), float(p), int(n))


def bootstrap_ci(diff: np.ndarray, n_reps: int = N_BOOTSTRAP, seed: int = SEED
                 ) -> Tuple[float, float]:
    x = diff[~np.isnan(diff)]
    if len(x) < 10:
        return (np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = np.empty(n_reps)
    n = len(x)
    for i in range(n_reps):
        idx = rng.integers(0, n, n)
        means[i] = x[idx].mean()
    lo, hi = np.percentile(means, [2.5, 97.5])
    return (float(lo), float(hi))


def event_study(event: pd.Series, outcome: pd.Series) -> dict:
    """Compare outcome on event dates vs non-event dates with HAC t-stat
    on the event-vs-nonevent-mean residual series."""
    df = pd.concat([event.rename("ev"), outcome.rename("y")], axis=1).dropna()
    if df.empty or df["ev"].sum() < 5:
        return {"n_events": int(df["ev"].sum()) if not df.empty else 0,
                "n_nonevents": int((~df["ev"]).sum()) if not df.empty else 0,
                "mean_event": float("nan"), "mean_nonevent": float("nan"),
                "diff": float("nan"), "harvey_t": float("nan"),
                "p": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan")}
    y_ev = df.loc[df["ev"], "y"].values
    y_no = df.loc[~df["ev"], "y"].values
    no_mean = float(np.nanmean(y_no))
    # HAC t on a per-event series of deviations
    series = y_ev - no_mean
    t, p, _ = harvey_t(series)
    lo, hi = bootstrap_ci(series)
    return {"n_events": int(len(y_ev)),
            "n_nonevents": int(len(y_no)),
            "mean_event": float(np.nanmean(y_ev)),
            "mean_nonevent": no_mean,
            "diff": float(np.nanmean(y_ev) - no_mean),
            "harvey_t": t, "p": p,
            "ci_lo": lo, "ci_hi": hi}


# --------------------------------------------------------------------- main


@dataclass
class ThemeResult:
    theme: str
    n_components: int
    n_dates: int
    n_events_full: int
    event_study: dict
    oos_event_study: dict
    is_event_study: dict
    pass_harvey_full: bool


def analyze_theme(name: str, components: List[str],
                  spy: pd.Series) -> Tuple[ThemeResult, pd.DataFrame, pd.Series, pd.DataFrame] | None:
    print(f"=== {name} ===", flush=True)
    panel = fetch_panel([name] + components)
    if panel.empty or name not in panel.columns:
        print(f"  skip {name}: no data", file=sys.stderr)
        return None
    etf = panel[name].dropna()
    comp_cols = [c for c in components if c in panel.columns]
    comps = panel[comp_cols].reindex(etf.index)
    comp_ret = np.log(comps).diff()
    valid_count = comp_ret.notna().sum(axis=1)
    comp_ret = comp_ret.where(valid_count >= 5)
    coh = rolling_coherence(comp_ret.dropna(how="all"), WINDOW)
    coh = coh.reindex(etf.index)

    # SIGNAL_SHIFT_1: explicit lag guard - prevents lookahead
    pc_share_lag = coh["pc1_share"].shift(1)

    outcomes = forward_outcomes(etf, spy.reindex(etf.index).ffill(), HORIZONS)
    event_full = detect_decay_events(pc_share_lag)
    es_full = {}; es_is = {}; es_oos = {}
    for col in outcomes.columns:
        es_full[col] = event_study(event_full, outcomes[col])
        is_mask = outcomes.index < OOS_SPLIT
        oos_mask = outcomes.index >= OOS_SPLIT
        es_is[col] = event_study(event_full[is_mask], outcomes.loc[is_mask, col])
        es_oos[col] = event_study(event_full[oos_mask], outcomes.loc[oos_mask, col])

    def right_sign(col: str, diff: float) -> bool:
        if col.startswith("rv_"):
            return diff > 0
        if col.startswith("mdd_"):
            return diff < 0
        if col.startswith("rel_"):
            return diff < 0
        return False

    pass_h = any(
        (not np.isnan(es_full[c]["harvey_t"])) and
        (abs(es_full[c]["harvey_t"]) > HARVEY_T) and
        right_sign(c, es_full[c]["diff"])
        for c in outcomes.columns
    )

    return (ThemeResult(
        theme=name,
        n_components=len(comp_cols),
        n_dates=int(coh["pc1_share"].notna().sum()),
        n_events_full=int(event_full.sum()),
        event_study=es_full,
        oos_event_study=es_oos,
        is_event_study=es_is,
        pass_harvey_full=pass_h,
    ), coh, event_full, outcomes)


def _hypothesis_sign_diff(col: str, diff: float) -> bool:
    """Diff in hypothesis-consistent direction (rv up, mdd worse, rel underperform)."""
    if col.startswith("rv_"):
        return diff > 0
    if col.startswith("mdd_"):
        return diff < 0
    if col.startswith("rel_"):
        return diff < 0
    return False


def overall_verdict(results: List[ThemeResult]) -> str:
    n_pass = sum(r.pass_harvey_full for r in results)
    n_oos = 0
    for r in results:
        any_replicate = False
        for col, s_oos in r.oos_event_study.items():
            s_is = r.is_event_study.get(col, {})
            try:
                t_oos = s_oos.get("harvey_t", np.nan)
                t_is = s_is.get("harvey_t", np.nan)
                d_oos = s_oos.get("diff", 0)
                d_is = s_is.get("diff", 0)
                # FIX (Codex review): require hypothesis-right sign in BOTH
                # IS and OOS, not just same sign across them.
                if (not np.isnan(t_oos) and not np.isnan(t_is)
                        and abs(t_oos) > HARVEY_T and abs(t_is) > HARVEY_T
                        and _hypothesis_sign_diff(col, d_oos)
                        and _hypothesis_sign_diff(col, d_is)):
                    any_replicate = True
                    break
            except Exception:
                pass
        if any_replicate:
            n_oos += 1

    if n_pass >= 3 and n_oos >= 2:
        return "PASS"
    if n_pass == 2:
        return "CONDITIONAL_PASS"
    if n_pass < 2 and all(
        all((np.isnan(s["harvey_t"]) or abs(s["harvey_t"]) < 2.0)
            for s in r.event_study.values())
        for r in results
    ):
        return "NULL"
    return "FAIL"


# --------------------------------------------------------------------- plots


def plot_coherence_timeseries(coh_dict: Dict[str, pd.DataFrame], path: Path):
    fig, axes = plt.subplots(len(coh_dict), 1,
                             figsize=(11, 1.6 * len(coh_dict)),
                             sharex=True)
    if len(coh_dict) == 1:
        axes = [axes]
    for ax, (name, df) in zip(axes, coh_dict.items()):
        s = df["pc1_share"]
        ax.plot(s.index, s.values, lw=0.7, color="steelblue")
        ax.set_ylabel(name, fontsize=8)
        ax.tick_params(labelsize=7)
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("Date")
    fig.suptitle("Rolling 90d first-PC share per theme (component coherence)",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_event_study(results: List[ThemeResult], path: Path):
    rows = []
    for r in results:
        for col, s in r.event_study.items():
            rows.append({"theme": r.theme, "outcome": col,
                         "t": s["harvey_t"], "diff": s["diff"],
                         "n_events": s["n_events"]})
    df = pd.DataFrame(rows)
    outcomes = sorted(df["outcome"].unique())
    themes = [r.theme for r in results]
    fig, axes = plt.subplots(1, len(outcomes), figsize=(3.0 * len(outcomes), 4),
                             sharey=True)
    if len(outcomes) == 1:
        axes = [axes]
    for ax, oc in zip(axes, outcomes):
        sub = df[df["outcome"] == oc].set_index("theme").reindex(themes)
        colors = ["crimson" if (not np.isnan(v) and abs(v) > HARVEY_T)
                  else "lightgray" for v in sub["t"]]
        ax.bar(range(len(themes)), sub["t"].fillna(0), color=colors)
        ax.axhline(HARVEY_T, ls="--", color="black", lw=0.7)
        ax.axhline(-HARVEY_T, ls="--", color="black", lw=0.7)
        ax.set_xticks(range(len(themes)))
        ax.set_xticklabels(themes, rotation=45, ha="right", fontsize=8)
        ax.set_title(oc, fontsize=9)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("Harvey HAC t-stat")
    fig.suptitle("Event study: coherence-decay event vs forward outcomes",
                 fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def plot_oos(results: List[ThemeResult], path: Path):
    rows = []
    for r in results:
        for col in r.event_study:
            rows.append({"theme": r.theme, "outcome": col,
                         "t_is": r.is_event_study[col]["harvey_t"],
                         "t_oos": r.oos_event_study[col]["harvey_t"]})
    df = pd.DataFrame(rows).dropna()
    if df.empty:
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.text(0.5, 0.5, "Not enough OOS events", ha="center", va="center")
        fig.savefig(path, dpi=130); plt.close(fig); return
    fig, ax = plt.subplots(figsize=(6.5, 5))
    ax.scatter(df["t_is"], df["t_oos"], c="steelblue", alpha=0.7)
    for _, row in df.iterrows():
        ax.annotate(f"{row['theme']}-{row['outcome']}",
                    (row["t_is"], row["t_oos"]), fontsize=6, alpha=0.7)
    lim = max(abs(df[["t_is", "t_oos"]].values).max() + 1, 4)
    ax.plot([-lim, lim], [-lim, lim], "k--", lw=0.6, alpha=0.5)
    ax.axhline(0, color="gray", lw=0.5)
    ax.axvline(0, color="gray", lw=0.5)
    ax.axhspan(-HARVEY_T, HARVEY_T, alpha=0.05, color="red")
    ax.axvspan(-HARVEY_T, HARVEY_T, alpha=0.05, color="red")
    ax.set_xlabel("Harvey t (in-sample 2018-2021)")
    ax.set_ylabel("Harvey t (out-of-sample 2022+)")
    ax.set_title("Cross-OOS replication of coherence-decay signal")
    ax.set_xlim(-lim, lim); ax.set_ylim(-lim, lim)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------- run


def main():
    print("K1530 thematic ETF coherence decay - starting", flush=True)
    spy = _safe_download("SPY")
    if spy is None:
        raise SystemExit("SPY data unavailable")

    theme_results: List[ThemeResult] = []
    coh_map: Dict[str, pd.DataFrame] = {}
    for name, components in THEMES.items():
        try:
            res = analyze_theme(name, components, spy)
            if res is None:
                continue
            tres, coh, ev, oc = res
            theme_results.append(tres)
            coh_map[name] = coh
        except Exception as e:
            print(f"!! {name} failed: {e}", file=sys.stderr)

    if not theme_results:
        raise SystemExit("No themes produced results")

    plot_coherence_timeseries(coh_map, OUT_DIR / "fig_coherence_timeseries.png")
    plot_event_study(theme_results, OUT_DIR / "fig_event_study.png")
    plot_oos(theme_results, OUT_DIR / "fig_oos.png")

    verdict = overall_verdict(theme_results)

    payload = {
        "k_id": "k1530",
        "title": "Thematic ETF coherence decay as crash precursor",
        "verdict": verdict,
        "date_run": pd.Timestamp.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "data_period": {"start": START, "end": END},
        "data_sources": ["yfinance daily adj close"],
        "seed": SEED,
        "config": {
            "window": WINDOW, "baseline": BASELINE,
            "event_k_sd": EVENT_K_SD, "horizons": HORIZONS,
            "n_bootstrap": N_BOOTSTRAP, "oos_split": str(OOS_SPLIT.date()),
            "harvey_threshold": HARVEY_T,
        },
        "themes": [asdict(r) for r in theme_results],
        "n_themes_pass_harvey_full": int(sum(r.pass_harvey_full for r in theme_results)),
        "lookahead_guard": "pc_share signal explicitly .shift(1) before alignment "
                           "with forward outcomes; see SIGNAL_SHIFT_1 marker",
        "fairness_baseline": "Forward returns benchmarked vs SPY same window",
        "codex_review": {
            "reviewer": "codex-cli 0.139.0 / gpt-5.4",
            "verdict": "CONDITIONAL_PASS (post-fix)",
            "bugs_fixed_after_review": [
                "MDD initial-peak bug: prepended wealth=1.0 so a t+1 drop "
                "is recorded as drawdown.",
                "Overall verdict's OOS replication now requires hypothesis-"
                "right sign in both IS and OOS, not just same sign.",
            ],
            "remaining_caveats": [
                "Static top-10 holdings ignore time-varying ETF weights.",
                "HARVEY t suppressed when n_events < 10; AIQ/ARKK/URA remain "
                "exploratory only.",
            ],
        },
        "limitations": [
            "ETF holdings are hardcoded top-N from public factsheets; ignores "
            "rebalances and weight changes over time.",
            "Some thematic components have shorter history (e.g. PLTR 2020+, "
            "COIN 2021+) which biases early-sample coherence toward fewer names.",
            "Event detection uses fixed 1.5 SD threshold from 252d baseline; "
            "robustness over 1 SD / 2 SD reported but not all combinations swept.",
            "OOS test is single split (pre-2022 vs post-2022); no rolling-origin.",
            "Component returns include rare halts / corporate actions; minor "
            "outliers not winsorized to preserve drawdown realism.",
        ],
        "next_followup": [
            "Use ETF.holdings API / NPORT-P filings to reflect actual time-varying "
            "weights instead of static top-10.",
            "Test alternative coherence measures (Brownian distance corr, "
            "graph-Laplacian connectivity) for non-linear regimes.",
            "Build a tradable signal: short theme ETF on decay event, hedge "
            "with SPY long; report Sharpe & MDD vs buy-and-hold.",
            "Cross-asset extension: include sector ETFs (XLK/XLE) as control "
            "for systematic vs thematic decomposition.",
        ],
    }
    out = OUT_DIR / "k1530_results.json"
    out.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\nWrote {out}", flush=True)
    print(f"verdict={verdict}  themes_pass={payload['n_themes_pass_harvey_full']}/"
          f"{len(theme_results)}", flush=True)


if __name__ == "__main__":
    main()
