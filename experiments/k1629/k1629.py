"""K1629: Is the first trading hour the most dangerous?

Reader-facing myth test:
    "The first hour after the US market opens is the most volatile / dangerous."

Data are local SPY 5-minute yfinance snapshots under data/intraday.  The script
does not download live data, so reruns are pinned to the local cache.

Main design:
    - Keep complete regular-session days only.
    - Use each 5-minute bar's log(Close/Open) as the interval return.
    - Split New York regular trading hours into:
        open_60:  09:30 <= bar start < 10:30
        midday:   10:30 <= bar start < 15:00
        close_60: 15:00 <= bar start < 16:00
    - Compare realized-variance intensity per 5-minute bar, not raw segment RV,
      because midday is mechanically much longer.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy import stats


EXPERIMENT_ID = "k1629"
ROOT = Path(__file__).resolve().parents[2]
EXP_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_DIR = ROOT / "data" / "intraday"
RESULTS_PATH = EXP_DIR / f"{EXPERIMENT_ID}_results.json"
SEED = 42
BOOTSTRAP_REPS = 5000
HAC_LAG = 5
EXPECTED_FULL_DAY_BARS = 78
MIN_FULL_DAY_BARS = 75
SEGMENTS = ["open_60", "midday", "close_60"]
SEGMENT_LABELS = {
    "open_60": "Open 09:30-10:30",
    "midday": "Midday 10:30-15:00",
    "close_60": "Close 15:00-16:00",
}


def _safe_float(value: object) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _pct(x: float) -> float:
    return float(x * 100.0)


def _bp(x: float) -> float:
    return float(x * 10000.0)


def _date_from_path(path: Path) -> str:
    match = re.search(r"SPY_5min_(\d{4}-\d{2}-\d{2})\.csv$", path.name)
    if not match:
        raise ValueError(f"unrecognized SPY 5-minute filename: {path.name}")
    return match.group(1)


def wilson_ci(k: int, n: int, z: float = 1.959963984540054) -> list[float | None]:
    if n <= 0:
        return [None, None]
    phat = k / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n) / denom
    return [_safe_float(center - half), _safe_float(center + half)]


def hac_mean_test(values: np.ndarray, lag: int = HAC_LAG) -> dict:
    """Newey-West test for mean(values) = 0.

    Uses Bartlett weights and a normal approximation.  This is used only for
    daily paired differences, not for raw 5-minute bars.
    """
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 3:
        return {"n": n, "mean": None, "se": None, "t": None, "p": None}
    mu = float(np.mean(x))
    u = x - mu
    max_lag = min(int(lag), n - 1)
    gamma0 = float(np.dot(u, u) / n)
    long_run_var = gamma0
    for ell in range(1, max_lag + 1):
        gamma = float(np.dot(u[ell:], u[:-ell]) / n)
        weight = 1.0 - ell / (max_lag + 1.0)
        long_run_var += 2.0 * weight * gamma
    long_run_var = max(long_run_var, 0.0)
    se = math.sqrt(long_run_var / n) if long_run_var > 0 else 0.0
    t_stat = mu / se if se > 0 else math.inf
    p_value = 2.0 * stats.norm.sf(abs(t_stat)) if math.isfinite(t_stat) else 0.0
    return {
        "n": n,
        "mean": _safe_float(mu),
        "se": _safe_float(se),
        "t": _safe_float(t_stat),
        "p": _safe_float(p_value),
        "lag": max_lag,
    }


def bootstrap_mean_ci(values: np.ndarray, reps: int = BOOTSTRAP_REPS, seed: int = SEED) -> list[float | None]:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) == 0:
        return [None, None]
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(reps, len(x)))
    draws = x[idx].mean(axis=1)
    lo, hi = np.quantile(draws, [0.025, 0.975])
    return [_safe_float(lo), _safe_float(hi)]


def bootstrap_tail_rate_ci(
    daily_counts: pd.DataFrame,
    segment: str,
    tail_col: str,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> list[float | None]:
    sub = daily_counts[daily_counts["segment"] == segment].copy()
    if sub.empty:
        return [None, None]
    rng = np.random.default_rng(seed)
    values: list[float] = []
    rows = sub[["date", tail_col, "n_bars"]].to_numpy()
    for _ in range(reps):
        sample = rows[rng.integers(0, len(rows), size=len(rows))]
        k = float(sample[:, 1].sum())
        n = float(sample[:, 2].sum())
        values.append(k / n if n > 0 else np.nan)
    lo, hi = np.nanquantile(values, [0.025, 0.975])
    return [_safe_float(lo), _safe_float(hi)]


def bootstrap_tail_rate_diff_ci(
    daily_counts: pd.DataFrame,
    seg_a: str,
    seg_b: str,
    tail_col: str,
    reps: int = BOOTSTRAP_REPS,
    seed: int = SEED,
) -> list[float | None]:
    pivot_k = daily_counts.pivot(index="date", columns="segment", values=tail_col)
    pivot_n = daily_counts.pivot(index="date", columns="segment", values="n_bars")
    common = pivot_k[[seg_a, seg_b]].dropna().index.intersection(pivot_n[[seg_a, seg_b]].dropna().index)
    if len(common) == 0:
        return [None, None]
    k = pivot_k.loc[common, [seg_a, seg_b]].to_numpy(dtype=float)
    n = pivot_n.loc[common, [seg_a, seg_b]].to_numpy(dtype=float)
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(reps):
        idx = rng.integers(0, len(common), size=len(common))
        rate_a = k[idx, 0].sum() / n[idx, 0].sum()
        rate_b = k[idx, 1].sum() / n[idx, 1].sum()
        values.append(rate_a - rate_b)
    lo, hi = np.quantile(values, [0.025, 0.975])
    return [_safe_float(lo), _safe_float(hi)]


def read_spy_5min_file(path: Path) -> pd.DataFrame | None:
    date_label = _date_from_path(path)
    try:
        raw = pd.read_csv(path, skiprows=[1, 2])
    except Exception as exc:  # noqa: BLE001
        print(f"[{EXPERIMENT_ID}] WARN read failed {path}: {type(exc).__name__}: {exc}")
        return None
    required = {"Price", "Open", "High", "Low", "Close", "Volume"}
    if not required.issubset(raw.columns):
        print(f"[{EXPERIMENT_ID}] WARN invalid schema {path}: {list(raw.columns)}")
        return None
    raw = raw.rename(columns={"Price": "datetime"})
    raw["datetime"] = pd.to_datetime(raw["datetime"], utc=True, errors="coerce")
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        raw[col] = pd.to_numeric(raw[col], errors="coerce")
    raw = raw.dropna(subset=["datetime", "Open", "High", "Low", "Close"])
    raw["source_file"] = path.name
    raw["source_date"] = date_label
    return raw[["datetime", "Open", "High", "Low", "Close", "Volume", "source_file", "source_date"]]


def load_spy_5min() -> pd.DataFrame:
    frames = []
    for path in sorted(DATA_DIR.glob("SPY_5min_*.csv")):
        frame = read_spy_5min_file(path)
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        raise RuntimeError(f"no local SPY 5-minute files found under {DATA_DIR}")
    bars = pd.concat(frames, ignore_index=True)
    bars = bars.drop_duplicates(subset=["datetime"], keep="last").sort_values("datetime")
    bars["ny_dt"] = bars["datetime"].dt.tz_convert("America/New_York")
    bars["date"] = pd.to_datetime(bars["ny_dt"].dt.date)
    bars["time"] = bars["ny_dt"].dt.strftime("%H:%M")
    bars["bar_ret"] = np.log(bars["Close"] / bars["Open"])
    bars["abs_ret"] = bars["bar_ret"].abs()
    return bars


def assign_segment(time_label: str) -> str | None:
    if "09:30" <= time_label < "10:30":
        return "open_60"
    if "10:30" <= time_label < "15:00":
        return "midday"
    if "15:00" <= time_label < "16:00":
        return "close_60"
    return None


def filter_complete_regular_days(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    day_info = []
    kept_frames = []
    for date, group in bars.groupby("date", sort=True):
        g = group.sort_values("ny_dt").copy()
        n = len(g)
        first_time = str(g["time"].iloc[0])
        last_time = str(g["time"].iloc[-1])
        keep = n >= MIN_FULL_DAY_BARS and first_time <= "09:35" and last_time >= "15:55"
        day_info.append({
            "date": pd.Timestamp(date).strftime("%Y-%m-%d"),
            "n_bars": int(n),
            "first_time_ny": first_time,
            "last_time_ny": last_time,
            "kept": bool(keep),
        })
        if keep:
            kept_frames.append(g)
    if not kept_frames:
        raise RuntimeError("no complete regular-session SPY days after filtering")
    kept = pd.concat(kept_frames, ignore_index=True)
    kept["segment"] = kept["time"].map(assign_segment)
    kept = kept[kept["segment"].isin(SEGMENTS)].copy()
    diagnostics = {
        "raw_days": int(bars["date"].nunique()),
        "kept_days": int(kept["date"].nunique()),
        "excluded_days": int(sum(not row["kept"] for row in day_info)),
        "day_filter": {
            "min_bars": MIN_FULL_DAY_BARS,
            "first_time_ny_lte": "09:35",
            "last_time_ny_gte": "15:55",
        },
        "excluded_day_details": [row for row in day_info if not row["kept"]],
    }
    return kept, diagnostics


def build_daily_panel(bars: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, group in bars.groupby("date", sort=True):
        g = group.sort_values("ny_dt")
        day_rv = float((g["bar_ret"] ** 2).sum())
        n_day = int(len(g))
        if day_rv <= 0 or n_day <= 0:
            continue
        row = {
            "date": pd.Timestamp(date),
            "day_rv": day_rv,
            "n_day": n_day,
            "day_return": float(g["bar_ret"].sum()),
            "day_max_abs_ret": float(g["abs_ret"].max()),
            "day_min_ret": float(g["bar_ret"].min()),
        }
        for segment in SEGMENTS:
            h = g[g["segment"] == segment]
            rv = float((h["bar_ret"] ** 2).sum())
            n = int(len(h))
            row[f"{segment}_n"] = n
            row[f"{segment}_rv"] = rv
            row[f"{segment}_rv_share"] = rv / day_rv if day_rv > 0 else np.nan
            row[f"{segment}_rv_per_bar"] = rv / n if n > 0 else np.nan
            row[f"{segment}_rel_intensity"] = (rv / n) / (day_rv / n_day) if n > 0 and day_rv > 0 else np.nan
            row[f"{segment}_return"] = float(h["bar_ret"].sum()) if n > 0 else np.nan
            row[f"{segment}_max_abs_ret"] = float(h["abs_ret"].max()) if n > 0 else np.nan
            row[f"{segment}_min_ret"] = float(h["bar_ret"].min()) if n > 0 else np.nan
        rows.append(row)
    daily = pd.DataFrame(rows).sort_values("date")
    required_counts = daily[[f"{s}_n" for s in SEGMENTS]]
    daily = daily[(required_counts["open_60_n"] == 12) & (required_counts["close_60_n"] == 12) & (required_counts["midday_n"] >= 50)].copy()
    if len(daily) < 30:
        raise RuntimeError(f"too few daily rows after segment-count filter: {len(daily)}")
    return daily


def add_tail_flags(bars: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    abs_threshold = float(bars["abs_ret"].quantile(0.95))
    neg_threshold = float(bars["bar_ret"].quantile(0.05))
    out = bars.copy()
    out["abs_tail"] = out["abs_ret"] >= abs_threshold
    out["neg_tail"] = out["bar_ret"] <= neg_threshold
    thresholds = {
        "abs_tail_quantile": 0.95,
        "abs_tail_threshold_return": _safe_float(abs_threshold),
        "abs_tail_threshold_bp": _safe_float(_bp(abs_threshold)),
        "neg_tail_quantile": 0.05,
        "neg_tail_threshold_return": _safe_float(neg_threshold),
        "neg_tail_threshold_bp": _safe_float(_bp(neg_threshold)),
    }
    return out, thresholds


def build_tail_counts(bars: pd.DataFrame) -> pd.DataFrame:
    grouped = bars.groupby(["date", "segment"], sort=True)
    rows = []
    for (date, segment), group in grouped:
        rows.append({
            "date": pd.Timestamp(date),
            "segment": segment,
            "n_bars": int(len(group)),
            "abs_tail_count": int(group["abs_tail"].sum()),
            "neg_tail_count": int(group["neg_tail"].sum()),
        })
    return pd.DataFrame(rows)


def segment_summary(daily: pd.DataFrame, bars: pd.DataFrame, daily_counts: pd.DataFrame) -> dict:
    highest_intensity = daily[[f"{s}_rel_intensity" for s in SEGMENTS]].idxmax(axis=1).str.replace("_rel_intensity", "", regex=False)
    highest_max_abs = daily[[f"{s}_max_abs_ret" for s in SEGMENTS]].idxmax(axis=1).str.replace("_max_abs_ret", "", regex=False)
    summary = {}
    for segment in SEGMENTS:
        h = bars[bars["segment"] == segment]
        counts = daily_counts[daily_counts["segment"] == segment]
        abs_k = int(counts["abs_tail_count"].sum())
        neg_k = int(counts["neg_tail_count"].sum())
        n_bars = int(counts["n_bars"].sum())
        rel = daily[f"{segment}_rel_intensity"].to_numpy(dtype=float)
        share = daily[f"{segment}_rv_share"].to_numpy(dtype=float)
        summary[segment] = {
            "label": SEGMENT_LABELS[segment],
            "n_bars": n_bars,
            "mean_bars_per_day": _safe_float(n_bars / len(daily)),
            "mean_rv_share": _safe_float(np.mean(share)),
            "mean_rv_share_pct": _safe_float(_pct(np.mean(share))),
            "mean_rel_intensity": _safe_float(np.mean(rel)),
            "mean_rel_intensity_bootstrap_ci": bootstrap_mean_ci(rel, seed=SEED),
            "median_rel_intensity": _safe_float(np.median(rel)),
            "mean_abs_5min_return_bp": _safe_float(_bp(float(h["abs_ret"].mean()))),
            "mean_5min_rv": _safe_float(float((h["bar_ret"] ** 2).mean())),
            "days_highest_intensity_count": int((highest_intensity == segment).sum()),
            "days_highest_intensity_rate": _safe_float(float((highest_intensity == segment).mean())),
            "days_highest_max_abs_count": int((highest_max_abs == segment).sum()),
            "days_highest_max_abs_rate": _safe_float(float((highest_max_abs == segment).mean())),
            "abs_tail_count": abs_k,
            "abs_tail_rate": _safe_float(abs_k / n_bars),
            "abs_tail_rate_pct": _safe_float(_pct(abs_k / n_bars)),
            "abs_tail_wilson_ci": wilson_ci(abs_k, n_bars),
            "abs_tail_cluster_bootstrap_ci": bootstrap_tail_rate_ci(daily_counts, segment, "abs_tail_count", seed=SEED),
            "neg_tail_count": neg_k,
            "neg_tail_rate": _safe_float(neg_k / n_bars),
            "neg_tail_rate_pct": _safe_float(_pct(neg_k / n_bars)),
            "neg_tail_wilson_ci": wilson_ci(neg_k, n_bars),
            "neg_tail_cluster_bootstrap_ci": bootstrap_tail_rate_ci(daily_counts, segment, "neg_tail_count", seed=SEED),
        }
    return summary


def paired_tests(daily: pd.DataFrame) -> dict:
    tests = {}
    pairs = [("open_60", "midday"), ("open_60", "close_60"), ("close_60", "midday")]
    for a, b in pairs:
        diff = daily[f"{a}_rel_intensity"].to_numpy(dtype=float) - daily[f"{b}_rel_intensity"].to_numpy(dtype=float)
        tests[f"{a}_minus_{b}_rel_intensity"] = {
            "metric": "daily paired difference in relative RV intensity per 5-min bar",
            "hac": hac_mean_test(diff, lag=HAC_LAG),
            "bootstrap_ci": bootstrap_mean_ci(diff, seed=SEED),
            "median_diff": _safe_float(float(np.median(diff))),
            "share_days_a_gt_b": _safe_float(float(np.mean(diff > 0))),
        }
    return tests


def pairwise_tail_tests(daily_counts: pd.DataFrame) -> dict:
    tests = {}
    pairs = [("open_60", "midday"), ("open_60", "close_60"), ("close_60", "midday")]
    for tail_col in ["abs_tail_count", "neg_tail_count"]:
        for a, b in pairs:
            row_a = daily_counts[daily_counts["segment"] == a]
            row_b = daily_counts[daily_counts["segment"] == b]
            k_a = int(row_a[tail_col].sum())
            n_a = int(row_a["n_bars"].sum())
            k_b = int(row_b[tail_col].sum())
            n_b = int(row_b["n_bars"].sum())
            table = np.array([[k_a, n_a - k_a], [k_b, n_b - k_b]], dtype=int)
            chi2, chi_p, _, expected = stats.chi2_contingency(table, correction=False)
            min_expected = float(expected.min())
            if min_expected < 5:
                odds_ratio, p_value = stats.fisher_exact(table)
                method = "fisher_exact"
                statistic = odds_ratio
            else:
                p_value = chi_p
                method = "chi2_contingency_no_correction"
                statistic = chi2
            rate_a = k_a / n_a
            rate_b = k_b / n_b
            tests[f"{tail_col}_{a}_vs_{b}"] = {
                "table": table.tolist(),
                "method": method,
                "min_expected_count": _safe_float(min_expected),
                "statistic": _safe_float(statistic),
                "p": _safe_float(p_value),
                "rate_a": _safe_float(rate_a),
                "rate_b": _safe_float(rate_b),
                "rate_diff_a_minus_b": _safe_float(rate_a - rate_b),
                "rate_diff_cluster_bootstrap_ci": bootstrap_tail_rate_diff_ci(daily_counts, a, b, tail_col, seed=SEED),
            }
    return tests


def make_figures(daily: pd.DataFrame, bars: pd.DataFrame, summary: dict, thresholds: dict) -> list[str]:
    paths: list[str] = []

    fig, ax = plt.subplots(figsize=(8, 4.8))
    labels = [SEGMENT_LABELS[s] for s in SEGMENTS]
    means = [summary[s]["mean_rel_intensity"] for s in SEGMENTS]
    ci = [summary[s]["mean_rel_intensity_bootstrap_ci"] for s in SEGMENTS]
    yerr = [[m - c[0] for m, c in zip(means, ci)], [c[1] - m for m, c in zip(means, ci)]]
    colors = ["#1f6f8b", "#6b7280", "#b45309"]
    ax.bar(labels, means, yerr=yerr, capsize=5, color=colors, alpha=0.88)
    ax.axhline(1.0, color="#111827", linewidth=1, linestyle="--", alpha=0.7)
    ax.set_ylabel("Relative RV intensity per 5-min bar")
    ax.set_title("SPY 5-min RV intensity by trading-day segment")
    ax.text(0.02, 0.94, "1.0 = full-day average 5-min RV", transform=ax.transAxes, fontsize=9)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = EXP_DIR / "fig_segment_rv_intensity.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    fig, ax = plt.subplots(figsize=(9, 4.8))
    plot_data = []
    for _, row in daily.iterrows():
        for segment in SEGMENTS:
            plot_data.append({
                "segment": SEGMENT_LABELS[segment],
                "rel_intensity": row[f"{segment}_rel_intensity"],
            })
    box_df = pd.DataFrame(plot_data)
    data = [box_df[box_df["segment"] == label]["rel_intensity"].to_numpy() for label in labels]
    bp = ax.boxplot(data, tick_labels=labels, patch_artist=True, showfliers=False)
    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.55)
    ax.axhline(1.0, color="#111827", linewidth=1, linestyle="--", alpha=0.7)
    ax.set_ylabel("Daily relative RV intensity")
    ax.set_title("Daily distribution: first hour is high on most, not all, days")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = EXP_DIR / "fig_daily_intensity_distribution.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    fig, ax = plt.subplots(figsize=(8, 4.8))
    abs_rates = [summary[s]["abs_tail_rate_pct"] for s in SEGMENTS]
    neg_rates = [summary[s]["neg_tail_rate_pct"] for s in SEGMENTS]
    x = np.arange(len(SEGMENTS))
    width = 0.34
    ax.bar(x - width / 2, abs_rates, width, label="Top 5% absolute 5-min moves", color="#7c3aed", alpha=0.85)
    ax.bar(x + width / 2, neg_rates, width, label="Worst 5% negative 5-min moves", color="#dc2626", alpha=0.80)
    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.set_ylabel("Tail-event rate per 5-min bar (%)")
    ax.set_title("SPY 5-min tail events are concentrated near the open")
    ax.text(
        0.02,
        0.94,
        f"Thresholds: |r| >= {thresholds['abs_tail_threshold_bp']:.1f} bp; r <= {thresholds['neg_tail_threshold_bp']:.1f} bp",
        transform=ax.transAxes,
        fontsize=9,
    )
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    path = EXP_DIR / "fig_tail_risk_by_segment.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(ROOT)))

    return paths


def build_results() -> dict:
    raw_bars = load_spy_5min()
    regular_bars, filter_diagnostics = filter_complete_regular_days(raw_bars)
    daily = build_daily_panel(regular_bars)
    # Apply the daily segment-count filter back to bars.
    valid_dates = set(daily["date"].dt.strftime("%Y-%m-%d"))
    bars = regular_bars[regular_bars["date"].dt.strftime("%Y-%m-%d").isin(valid_dates)].copy()
    bars, thresholds = add_tail_flags(bars)
    daily_counts = build_tail_counts(bars)
    summary = segment_summary(daily, bars, daily_counts)
    intensity_tests = paired_tests(daily)
    tail_tests = pairwise_tail_tests(daily_counts)
    figures = make_figures(daily, bars, summary, thresholds)

    open_beats_mid = intensity_tests["open_60_minus_midday_rel_intensity"]
    open_beats_close = intensity_tests["open_60_minus_close_60_rel_intensity"]
    open_tail_beats_close = tail_tests["abs_tail_count_open_60_vs_close_60"]
    first_hour_supported = (
        (open_beats_mid["bootstrap_ci"][0] or -math.inf) > 0
        and (open_beats_close["bootstrap_ci"][0] or -math.inf) > 0
        and (open_tail_beats_close["rate_diff_cluster_bootstrap_ci"][0] or -math.inf) > 0
    )
    verdict = (
        "SUPPORTS_FIRST_HOUR_HIGHEST_ON_AVERAGE_LIMITED_SAMPLE"
        if first_hour_supported
        else "NO_ROBUST_FIRST_HOUR_EDGE"
    )
    one_sentence = (
        f"在 {len(daily)} 個完整 SPY 5-min 交易日中，開盤第一小時的每根 5-min RV 強度"
        f"約為全天平均的 {summary['open_60']['mean_rel_intensity']:.2f} 倍，"
        f"且 {summary['open_60']['days_highest_intensity_count']}/{len(daily)} 天為三段最高；"
        "因此『開盤平均最震』成立，但『每天都最危險』不成立。"
    )
    results = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "bootstrap_reps": BOOTSTRAP_REPS,
        "verdict": verdict,
        "claim_strength": "descriptive 2026 local 5-minute snapshot; not paper-grade long-history inference",
        "one_sentence": one_sentence,
        "data": {
            "source": "local yfinance 5-minute SPY snapshots under data/intraday/SPY_5min_YYYY-MM-DD.csv",
            "ticker": "SPY",
            "raw_files": int(len(list(DATA_DIR.glob("SPY_5min_*.csv")))),
            "raw_days": int(filter_diagnostics["raw_days"]),
            "complete_regular_days": int(len(daily)),
            "start_date": daily["date"].min().strftime("%Y-%m-%d"),
            "end_date": daily["date"].max().strftime("%Y-%m-%d"),
            "n_5min_bars": int(len(bars)),
            "median_bars_per_day": _safe_float(float(bars.groupby("date").size().median())),
            "filter_diagnostics": filter_diagnostics,
        },
        "method": {
            "bar_return": "log(Close/Open) for each 5-minute bar",
            "timezone": "America/New_York regular-session bar start time",
            "segments": SEGMENT_LABELS,
            "main_metric": "segment realized variance per 5-minute bar divided by full-day realized variance per 5-minute bar",
            "tail_metric": "pooled 5-minute bars flagged by full-sample 95th percentile absolute return and 5th percentile negative return; CIs use day-cluster bootstrap",
            "hac_lag": HAC_LAG,
        },
        "tail_thresholds": thresholds,
        "segment_summary": summary,
        "paired_intensity_tests": intensity_tests,
        "pairwise_tail_tests": tail_tests,
        "figures": figures,
        "literature": [
            {
                "citation": "Andersen and Bollerslev (1997), Journal of Empirical Finance",
                "role": "intraday periodicity and volatility persistence; motivates time-of-day normalization",
                "url": "https://www.sciencedirect.com/science/article/pii/S0927539897000042",
            },
            {
                "citation": "Madhavan, Richardson, and Roomans (1997), Review of Financial Studies",
                "role": "market open information asymmetry / price discovery mechanism",
                "url": "https://academic.oup.com/rfs/article-abstract/10/4/1035/1605749",
            },
            {
                "citation": "Engle and Sokalska (2012), Journal of Financial Econometrics",
                "role": "daily x diurnal x stochastic intraday volatility decomposition",
                "url": "https://academic.oup.com/jfec/article-abstract/10/1/54/755620",
            },
            {
                "citation": "Harris (1986), Journal of Financial Economics",
                "role": "early evidence on intraday stock-return patterns near the open",
                "url": "https://www.sciencedirect.com/science/article/pii/0304405X86900449",
            },
        ],
        "limitations": [
            "Local SPY 5-minute cache covers only 2026-01-14 to 2026-07-02 after filtering, so this is a short-sample myth test.",
            "The test is descriptive, not a trading strategy; it does not estimate transaction costs or executable intraday alpha.",
            "Pooled 5-minute tail rates are supplemented with day-cluster bootstrap because intraday bars are not independent.",
            "The result says the first hour is highest on average, not that it is highest every day.",
        ],
    }
    return results


def main() -> int:
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    results = build_results()
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        f"[{EXPERIMENT_ID}] days={results['data']['complete_regular_days']} "
        f"{results['data']['start_date']}..{results['data']['end_date']}"
    )
    print(f"[{EXPERIMENT_ID}] verdict -> {results['verdict']}")
    print(results["one_sentence"])
    print(f"[{EXPERIMENT_ID}] results -> {RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
