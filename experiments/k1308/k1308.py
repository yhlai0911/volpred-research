"""
K1308: VIXTWN/VIX Ratio 穩定性驗證（Q6）
追蹤 ratio 是否在累積更多天數後維持穩定（K1181 基準: 1.3906, CV=0.098, n=76）
"""
import json
import numpy as np
import pandas as pd
from pathlib import Path
from scipy import stats

SEED = 42
np.random.seed(SEED)

ROOT = Path(__file__).parent.parent.parent
VIXTWN_PATH = ROOT / "data/vixtwn/vixtwn_daily.csv"
VIX_PATH = ROOT / "paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"
RESULTS_PATH = Path(__file__).parent / "k1308_results.json"

K1181_BASELINE = {"mean": 1.3906, "cv": 0.098, "n": 76, "period": "Dec2025–Apr2026"}


def load_vixtwn() -> pd.DataFrame:
    df = pd.read_csv(VIXTWN_PATH, parse_dates=["date"])
    df = df.drop_duplicates(subset="date").sort_values("date").reset_index(drop=True)
    df = df[["date", "vixtwn_close"]].dropna()
    return df


def load_vix(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    df = pd.read_csv(VIX_PATH, parse_dates=["date"], usecols=["date", "vix_close"])
    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    df = df.sort_values("date").reset_index(drop=True)
    return df


def compute_rolling_stats(ratio: pd.Series, window: int = 30) -> pd.DataFrame:
    return pd.DataFrame({
        "rolling_mean": ratio.rolling(window, min_periods=15).mean(),
        "rolling_std": ratio.rolling(window, min_periods=15).std(),
        "rolling_cv": ratio.rolling(window, min_periods=15).std() / ratio.rolling(window, min_periods=15).mean(),
    })


def ols_trend(ratio: pd.Series) -> dict:
    x = np.arange(len(ratio))
    slope, intercept, r, p, se = stats.linregress(x, ratio.values)
    return {
        "beta": round(float(slope), 6),
        "intercept": round(float(intercept), 4),
        "r_squared": round(float(r**2), 4),
        "p_value": round(float(p), 4),
        "trend_significant": bool(p < 0.05),
    }


def midpoint_mean_shift_test(ratio: pd.Series) -> dict:
    # Welch two-sample t-test at sample midpoint — tests mean equality of two halves.
    # NOTE: This is NOT a formal Chow structural break test (which tests regression
    # coefficient stability). This tests only midpoint mean shift. Limitation documented
    # per Codex review (K1308 CONDITIONAL_PASS).
    mid = len(ratio) // 2
    r1 = ratio.iloc[:mid].values
    r2 = ratio.iloc[mid:].values
    t_stat, p_val = stats.ttest_ind(r1, r2, equal_var=False)
    return {
        "test_type": "welch_ttest_at_midpoint",
        "group1_mean": round(float(r1.mean()), 4),
        "group2_mean": round(float(r2.mean()), 4),
        "t_stat": round(float(t_stat), 4),
        "p_value": round(float(p_val), 4),
        "mean_shift_detected": bool(p_val < 0.05),
        "split_at_n": mid,
        "limitation": "midpoint-only Welch t-test, not a formal Chow/CUSUM break test",
    }


def main():
    vixtwn = load_vixtwn()
    n_vixtwn = len(vixtwn)
    date_start = vixtwn["date"].iloc[0]
    date_end = vixtwn["date"].iloc[-1]

    vix = load_vix(date_start, date_end)

    merged = pd.merge(vixtwn, vix, on="date", how="inner")
    merged = merged.dropna(subset=["vixtwn_close", "vix_close"])
    merged["ratio"] = merged["vixtwn_close"] / merged["vix_close"]

    ratio = merged["ratio"]
    n = len(ratio)

    # Overall stats
    overall = {
        "mean": round(float(ratio.mean()), 4),
        "median": round(float(ratio.median()), 4),
        "std": round(float(ratio.std()), 4),
        "cv": round(float(ratio.std() / ratio.mean()), 4),
        "min": round(float(ratio.min()), 4),
        "max": round(float(ratio.max()), 4),
        "n": int(n),
        "period": f"{date_start.strftime('%Y-%m-%d')}–{date_end.strftime('%Y-%m-%d')}",
    }

    # 95% CI for mean
    ci = stats.t.interval(0.95, df=n - 1, loc=ratio.mean(), scale=stats.sem(ratio))
    overall["ci_95"] = [round(float(ci[0]), 4), round(float(ci[1]), 4)]

    # Compare to K1181
    baseline_mean = K1181_BASELINE["mean"]
    t_vs_baseline, p_vs_baseline = stats.ttest_1samp(ratio, baseline_mean)
    comparison = {
        "k1181_baseline_mean": baseline_mean,
        "k1181_baseline_cv": K1181_BASELINE["cv"],
        "k1181_n": K1181_BASELINE["n"],
        "current_n": int(n),
        "additional_days": int(n - K1181_BASELINE["n"]),
        "mean_diff": round(float(ratio.mean() - baseline_mean), 4),
        "t_stat_vs_baseline": round(float(t_vs_baseline), 4),
        "p_vs_baseline": round(float(p_vs_baseline), 4),
        "baseline_still_valid": bool(p_vs_baseline > 0.05),
    }

    # Rolling stats
    rolling = compute_rolling_stats(ratio)
    rolling_summary = {
        "window": 30,
        "final_30d_mean": round(float(rolling["rolling_mean"].dropna().iloc[-1]), 4),
        "final_30d_cv": round(float(rolling["rolling_cv"].dropna().iloc[-1]), 4),
        "rolling_mean_range": [
            round(float(rolling["rolling_mean"].dropna().min()), 4),
            round(float(rolling["rolling_mean"].dropna().max()), 4),
        ],
    }

    # OLS trend
    trend = ols_trend(ratio)

    # Midpoint mean shift test (Welch t-test, NOT a formal Chow test — see function docstring)
    chow = midpoint_mean_shift_test(ratio)

    # Progress to 252 days
    progress = {
        "current_n": int(n),
        "target_n": 252,
        "pct_complete": round(100 * n / 252, 1),
        "remaining_trading_days": int(252 - n),
        "estimated_completion": "~2026-12 (approx 7 months)",
    }

    # Stability verdict
    stable = (
        1.30 <= overall["mean"] <= 1.50
        and overall["cv"] <= 0.15
        and not trend["trend_significant"]
        and not chow["mean_shift_detected"]
        and comparison["baseline_still_valid"]
    )
    verdict_details = {
        "mean_in_range": bool(1.30 <= overall["mean"] <= 1.50),
        "cv_ok": bool(overall["cv"] <= 0.15),
        "no_trend": bool(not trend["trend_significant"]),
        "no_midpoint_mean_shift": bool(not chow["mean_shift_detected"]),
        "consistent_with_k1181": bool(comparison["baseline_still_valid"]),
        "overall_stable": stable,
        # Calendar-date inner merge: VIXTWN (Taiwan session) vs VIX (US session)
        # same date ≠ same information set. Limitation acknowledged (Codex K1308).
        "calendar_merge_limitation": "inner join on date label only; no TZ-correction",
    }

    results = {
        "experiment_id": "K1308",
        "title": "VIXTWN/VIX Ratio 穩定性驗證（Q6）",
        "run_date": "2026-05-22",
        "codex_review": "CONDITIONAL_PASS",
        "data_sources": {
            "vixtwn": str(VIXTWN_PATH),
            "vix": str(VIX_PATH),
        },
        "known_limitations": [
            "baseline comparison uses K1181 fixed constant 1.3906, not a two-sample test",
            "inner merge on calendar date only; TZ/session mismatch not corrected",
            "midpoint break test is Welch t-test, not formal Chow/CUSUM",
            "dedup keeps first row of duplicates without value validation",
        ],
        "overall_stats": overall,
        "comparison_to_k1181": comparison,
        "rolling_summary": rolling_summary,
        "ols_trend": trend,
        "midpoint_mean_shift_test": chow,
        "progress_to_252d": progress,
        "stability_verdict": verdict_details,
        "conclusion": "STABLE — ratio 與 K1181 基準一致" if stable else "UNSTABLE — ratio 顯著漂移，需進一步審查",
    }

    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False, default=str)

    print(f"K1308 完成")
    print(f"  樣本數: {n} 天（K1181: {K1181_BASELINE['n']} 天，增加 {n - K1181_BASELINE['n']} 天）")
    print(f"  VIXTWN/VIX ratio: mean={overall['mean']}, CV={overall['cv']}")
    print(f"  vs K1181 基準 (1.3906): diff={comparison['mean_diff']}, p={comparison['p_vs_baseline']}")
    print(f"  OLS trend: β={trend['beta']}, p={trend['p_value']} (significant={trend['trend_significant']})")
    print(f"  Mean shift (midpoint Welch t): {chow['mean_shift_detected']} (p={chow['p_value']})")
    print(f"  穩定性判定: {results['stability_verdict']['overall_stable']}")
    print(f"  252-day progress: {n}/252 ({progress['pct_complete']}%)")


if __name__ == "__main__":
    main()
