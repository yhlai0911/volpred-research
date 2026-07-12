"""K1442 — MOVE/VIX 比值與 CPI 公布前後的隱含波動率定價

研究問題：
1. MOVE/VIX 當前比值（2026-06-09）相對歷史分布在哪？
2. CPI 公布前 5 日 MOVE/VIX 變化模式？
3. CPI 發布日（release day）MOVE 與 VIX 的相對反應？

資料：yfinance ^MOVE, ^VIX 2003-2026 daily
CPI dates: ALFRED release_id=10（BLS CPI 官方發布日）
"""
import hashlib
import json
import os
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal
from scipy import stats as scs

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from volpred.data.event_dates import cpi_release_dates

plt.rcParams["font.sans-serif"] = ["Heiti TC"]
plt.rcParams["axes.unicode_minus"] = False

OUT = Path(__file__).parent
RESULTS_PATH = OUT / "k1442_results.json"
EVENTS_PATH = OUT / "k1442_cpi_events.csv"
LEGACY_RESULTS_PATH = OUT / "k1442_results_legacy_20260609.json"
LEGACY_EVENTS_PATH = OUT / "k1442_cpi_events_legacy_20260609.csv"
MARKET_SNAPSHOT_PATH = OUT / "k1442_market_close.csv"
FIG_RATIO_PATH = OUT / "fig_a_ratio_timeseries.png"
FIG_EVENT_PATH = OUT / "fig_b_cpi_event_study.png"

LEGACY_RESULTS_SHA256 = "f875a0c22472708700b9a6548839eea96808382241c1e093372219aa97c97d76"
LEGACY_EVENTS_SHA256 = "36241b44ca8c581e38f9132aceaa0aa50ecf28ca943a1e5c8e468bef4948e189"
MARKET_SNAPSHOT_SHA256 = "8f0ea7c8f94c02c026e107c7739c6605e420bb9044344bb41e504b253f57a4af"

SNAPSHOT_DATE = pd.Timestamp("2026-06-09")
EVENT_START = "2024-01-01"
EVENT_END = "2026-05-31"
EVENT_DATE_SOURCE = "ALFRED release_id=10 (BLS Consumer Price Index release calendar)"
SEED = 42
BOOTSTRAP_REPS = 5_000
PRIMARY_ALPHA = 0.05 / 2
EXPECTED_REMOVED_DATES = {
    "2025-10-15",
    "2025-11-13",
    "2025-12-10",
    "2026-01-14",
    "2026-02-11",
    "2026-03-12",
    "2026-05-13",
}
EXPECTED_ADDED_DATES = {
    "2025-10-24",
    "2025-12-18",
    "2026-01-13",
    "2026-02-13",
    "2026-03-11",
    "2026-05-12",
}
REFERENCES = [
    {
        "citation": (
            "Andersen, Bollerslev, Diebold, and Vega (2007), Real-Time Price "
            "Discovery in Global Stock, Bond and Foreign Exchange Markets"
        ),
        "source": "Journal of International Economics 73(2), 251-277",
        "doi": "10.1016/j.jinteco.2007.02.004",
        "design_relevance": (
            "Macro-news reactions are concentrated immediately after release; "
            "daily close-to-close windows cannot identify the intraday jump."
        ),
    },
    {
        "citation": (
            "Jones, Lamont, and Lumsdaine (1998), Macroeconomic News and Bond "
            "Market Volatility"
        ),
        "source": "Journal of Financial Economics 47, 315-337",
        "doi": "10.1016/S0304-405X(97)00047-0",
        "design_relevance": (
            "Scheduled government announcement dates are distinct bond-volatility "
            "events and therefore require exact preannounced dates."
        ),
    },
    {
        "citation": (
            "Kroner (2025), How Markets Process Macro News: The Importance of "
            "Investor Attention"
        ),
        "source": "Finance and Economics Discussion Series 2025-022",
        "doi": "10.17016/FEDS.2025.022",
        "design_relevance": (
            "CPI reactions vary with attention and regime, so a 2024-2026 daily "
            "sample supports only descriptive, sample-specific conclusions."
        ),
    },
]

np.random.seed(SEED)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_legacy_audit() -> tuple[dict, pd.DataFrame]:
    """Load immutable copies of the actually shipped pre-correction artifacts."""
    required = {
        LEGACY_RESULTS_PATH: LEGACY_RESULTS_SHA256,
        LEGACY_EVENTS_PATH: LEGACY_EVENTS_SHA256,
    }
    for path, expected_hash in required.items():
        if not path.exists():
            raise FileNotFoundError(f"缺少 immutable legacy artifact：{path.name}")
        actual_hash = sha256_file(path)
        if actual_hash != expected_hash:
            raise RuntimeError(
                f"legacy artifact hash 不符：{path.name} expected={expected_hash} "
                f"actual={actual_hash}"
            )

    prior = json.loads(LEGACY_RESULTS_PATH.read_text(encoding="utf-8"))
    if prior.get("experiment_id") != "k1442":
        raise ValueError("legacy results JSON 不是 K1442")
    legacy_frame = pd.read_csv(LEGACY_EVENTS_PATH)
    if "cpi_date" not in legacy_frame or len(legacy_frame) != 29:
        raise ValueError("legacy event CSV 必須包含 29 個 CPI 日期")
    return prior, legacy_frame


def stage_json(path: Path, payload: dict) -> Path:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    with tmp.open("r", encoding="utf-8") as handle:
        verified = json.load(handle)
    if verified != payload:
        raise RuntimeError(f"JSON round-trip 驗證失敗：{path.name}")
    return tmp


def stage_csv(path: Path, frame: pd.DataFrame) -> Path:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    frame.to_csv(tmp, index=False)
    verified = pd.read_csv(tmp)
    try:
        assert_frame_equal(
            frame.reset_index(drop=True),
            verified.reset_index(drop=True),
            check_dtype=False,
            check_exact=False,
            rtol=1e-13,
            atol=1e-13,
        )
    except AssertionError as exc:
        raise RuntimeError(f"CSV round-trip 驗證失敗：{path.name}") from exc
    return tmp


def stage_figure(fig, path: Path) -> Path:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    fig.savefig(tmp, format="png", dpi=110)
    plt.close(fig)
    if tmp.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"PNG signature 驗證失敗：{path.name}")
    pixels = plt.imread(tmp, format="png")
    if pixels.ndim not in (2, 3) or min(pixels.shape[:2]) < 100:
        raise RuntimeError(f"PNG dimensions 驗證失敗：{path.name}")
    return tmp


def load_market_snapshot() -> tuple[pd.DataFrame, str]:
    """Load the committed, hash-pinned K1442 yfinance snapshot."""
    if not MARKET_SNAPSHOT_PATH.exists():
        raise FileNotFoundError(
            "缺少 committed K1442 market snapshot；正式重跑禁止即時重抓不同 vintage"
        )

    actual_sha256 = sha256_file(MARKET_SNAPSHOT_PATH)
    if actual_sha256 != MARKET_SNAPSHOT_SHA256:
        raise RuntimeError(
            "K1442 market snapshot hash 不符："
            f"expected={MARKET_SNAPSHOT_SHA256} actual={actual_sha256}"
        )

    snapshot = pd.read_csv(MARKET_SNAPSHOT_PATH)
    if list(snapshot.columns) != ["date", "MOVE", "VIX"]:
        raise ValueError("K1442 market snapshot 欄位必須是 date/MOVE/VIX")
    if len(snapshot) != 5794:
        raise ValueError(f"K1442 market snapshot 應有 5794 列，實際 {len(snapshot)}")
    if snapshot["date"].iloc[0] != "2003-01-02" or snapshot["date"].iloc[-1] != "2026-06-09":
        raise ValueError("K1442 market snapshot 起訖日期不符原實驗")
    date_index = pd.DatetimeIndex(pd.to_datetime(snapshot["date"]))
    if date_index.has_duplicates or not date_index.is_monotonic_increasing:
        raise ValueError("K1442 market snapshot 日期必須唯一且遞增")
    if not np.isfinite(snapshot[["MOVE", "VIX"]].to_numpy(dtype=float)).all():
        raise ValueError("K1442 market snapshot 含非有限值")
    if (snapshot[["MOVE", "VIX"]] <= 0).any().any():
        raise ValueError("K1442 market snapshot 含非正指數值")

    frame = snapshot.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame = frame.set_index("date")
    frame["ratio"] = frame["MOVE"] / frame["VIX"]
    return frame, actual_sha256


def mean_bootstrap(values: pd.Series, seed: int, family_alpha: float) -> dict:
    array = values.to_numpy(dtype=float)
    if len(array) == 0 or not np.isfinite(array).all():
        raise ValueError("mean bootstrap 收到空值或非有限值")
    rng = np.random.default_rng(seed)
    draws = rng.choice(array, size=(BOOTSTRAP_REPS, len(array)), replace=True).mean(axis=1)
    lower, upper = np.quantile(draws, [family_alpha / 2, 1 - family_alpha / 2])
    return {
        "estimand": "mean percentage change",
        "estimate": float(array.mean()),
        "ci_level": float(1 - family_alpha),
        "ci": [float(lower), float(upper)],
        "reps": BOOTSTRAP_REPS,
        "seed": seed,
    }


def paired_bootstrap(pre: pd.Series, post: pd.Series, seed: int) -> dict:
    """Bootstrap the paired post-minus-pre mean across monthly events."""
    differences = post.to_numpy(dtype=float) - pre.to_numpy(dtype=float)
    if len(differences) == 0 or not np.isfinite(differences).all():
        raise ValueError("paired bootstrap 收到空值或非有限差值")
    rng = np.random.default_rng(seed)
    draws = rng.choice(
        differences,
        size=(BOOTSTRAP_REPS, len(differences)),
        replace=True,
    ).mean(axis=1)
    lower, upper = np.quantile(draws, [PRIMARY_ALPHA / 2, 1 - PRIMARY_ALPHA / 2])
    return {
        "estimand": "mean(post_5d - pre_5d), percentage points",
        "estimate": float(differences.mean()),
        "ci_level": float(1 - PRIMARY_ALPHA),
        "ci": [float(lower), float(upper)],
        "reps": BOOTSTRAP_REPS,
        "seed": seed,
    }


def directional_decline_tests(values: pd.Series, seed: int) -> dict:
    """Test the pre-specified descriptive decline direction (change < 0)."""
    array = values.to_numpy(dtype=float)
    nonzero = array[array != 0]
    if len(nonzero) == 0:
        raise ValueError("directional test 沒有非零觀測")
    wilcoxon = scs.wilcoxon(nonzero, alternative="less", zero_method="wilcox")
    negative = int((nonzero < 0).sum())
    sign_test = scs.binomtest(
        negative,
        n=len(nonzero),
        p=0.5,
        alternative="greater",
    )
    bootstrap = mean_bootstrap(values, seed, PRIMARY_ALPHA)
    return {
        "hypothesis": "percentage change < 0",
        "mean": float(array.mean()),
        "median": float(np.median(array)),
        "negative_count": negative,
        "n_nonzero": int(len(nonzero)),
        "negative_frequency_pct": float(negative / len(nonzero) * 100),
        "wilcoxon_one_sided_p": float(wilcoxon.pvalue),
        "sign_test_one_sided_p": float(sign_test.pvalue),
        "bootstrap_mean": bootstrap,
        "bonferroni_alpha": PRIMARY_ALPHA,
        "robust_decline": bool(
            wilcoxon.pvalue < PRIMARY_ALPHA and bootstrap["ci"][1] < 0
        ),
    }


def build_event_frame(df: pd.DataFrame, dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Build strict T-6..T+5 event windows without shifting missing dates."""
    records = []
    n = len(df)
    for event_date in dates:
        if event_date not in df.index:
            raise RuntimeError(
                f"CPI 日期 {event_date.strftime('%Y-%m-%d')} 不在 MOVE/VIX 共同交易日"
            )
        pos = df.index.get_loc(event_date)
        if not isinstance(pos, (int, np.integer)):
            raise RuntimeError(f"重複 market date：{event_date.strftime('%Y-%m-%d')}")
        if pos < 6 or pos > n - 6:
            raise RuntimeError(
                f"CPI 日期 {event_date.strftime('%Y-%m-%d')} 缺少完整 T-6..T+5 視窗"
            )

        win = df.iloc[pos - 6 : pos + 6].copy()
        win["t"] = range(-6, 6)

        def pct(column: str, start: int, end: int) -> float:
            start_value = win.loc[win["t"] == start, column].iloc[0]
            end_value = win.loc[win["t"] == end, column].iloc[0]
            return float((end_value / start_value - 1) * 100)

        records.append(
            {
                "cpi_date": event_date.strftime("%Y-%m-%d"),
                "trading_d": event_date.strftime("%Y-%m-%d"),
                "ratio_T-6": float(win.loc[win["t"] == -6, "ratio"].iloc[0]),
                "ratio_T-5": float(win.loc[win["t"] == -5, "ratio"].iloc[0]),
                "ratio_T0": float(win.loc[win["t"] == 0, "ratio"].iloc[0]),
                "ratio_T+5": float(win.loc[win["t"] == 5, "ratio"].iloc[0]),
                # Legacy-comparable fields retain the shipped column names.
                "move_T0_pct_change_5d": pct("MOVE", -5, 0),
                "vix_T0_pct_change_5d": pct("VIX", -5, 0),
                # True pre window has five close-to-close returns.
                "move_true_pre_pct_change_5d": pct("MOVE", -6, -1),
                "vix_true_pre_pct_change_5d": pct("VIX", -6, -1),
                "move_release_day_pct_change": pct("MOVE", -1, 0),
                "vix_release_day_pct_change": pct("VIX", -1, 0),
                "move_post_pct_change_5d": pct("MOVE", 0, 5),
                "vix_post_pct_change_5d": pct("VIX", 0, 5),
            }
        )
    return pd.DataFrame(records)


def verify_legacy_reproduction(
    df: pd.DataFrame,
    legacy_frame: pd.DataFrame,
) -> float:
    """Prove the frozen snapshot reproduces every shipped legacy event row."""
    legacy_dates = pd.DatetimeIndex(pd.to_datetime(legacy_frame["cpi_date"]))
    reproduced = build_event_frame(df, legacy_dates)
    reproduced = reproduced[legacy_frame.columns]
    numeric_columns = [
        column
        for column in legacy_frame.columns
        if column not in {"cpi_date", "trading_d"}
    ]
    max_abs_diff = float(
        np.max(
            np.abs(
                reproduced[numeric_columns].to_numpy(dtype=float)
                - legacy_frame[numeric_columns].to_numpy(dtype=float)
            )
        )
    )
    try:
        assert_frame_equal(
            reproduced.reset_index(drop=True),
            legacy_frame.reset_index(drop=True),
            check_dtype=False,
            check_exact=False,
            rtol=1e-12,
            atol=1e-12,
        )
    except AssertionError as exc:
        raise RuntimeError("frozen snapshot 無法重現 legacy event rows") from exc
    return max_abs_diff


def main():
    legacy_results, legacy_frame = load_legacy_audit()
    legacy_metrics = legacy_results.get("cpi_event_study")
    if not isinstance(legacy_metrics, dict):
        raise TypeError("legacy CPI metrics 必須是物件")
    legacy_dates = legacy_frame["cpi_date"].astype(str).tolist()

    df, market_snapshot_sha256 = load_market_snapshot()

    if df.empty or df.index[-1] != SNAPSHOT_DATE:
        last_available = None if df.empty else df.index[-1].strftime("%Y-%m-%d")
        raise RuntimeError(
            f"市場資料未完整覆蓋原始 K1442 截點 {SNAPSHOT_DATE.date()}；"
            f"最後共同日期={last_available}"
        )

    n = len(df)
    last_date = df.index[-1]
    cur_move = float(df["MOVE"].iloc[-1])
    cur_vix = float(df["VIX"].iloc[-1])
    cur_ratio = float(df["ratio"].iloc[-1])

    # Historical percentile of current ratio
    pct_all = float((df["ratio"] <= cur_ratio).mean() * 100)
    # Trailing 1Y window stats
    last_1y = df["ratio"].iloc[-252:]
    pct_1y = float((last_1y <= cur_ratio).mean() * 100)
    mean_1y = float(last_1y.mean())
    median_all = float(df["ratio"].median())
    mean_all = float(df["ratio"].mean())
    std_all = float(df["ratio"].std())

    # Event dates are data: use the official release calendar, never a proxy.
    cpi_dates = cpi_release_dates(EVENT_START, EVENT_END)
    if cpi_dates.has_duplicates or not cpi_dates.is_monotonic_increasing:
        raise ValueError("官方 CPI 日期必須唯一且遞增")

    official_date_strings = cpi_dates.strftime("%Y-%m-%d").tolist()
    removed_legacy_dates = sorted(set(legacy_dates) - set(official_date_strings))
    added_official_dates = sorted(set(official_date_strings) - set(legacy_dates))
    expected_counts = {
        "legacy": 29,
        "official": 28,
        "removed": 7,
        "added": 6,
    }
    actual_counts = {
        "legacy": len(legacy_dates),
        "official": len(official_date_strings),
        "removed": len(removed_legacy_dates),
        "added": len(added_official_dates),
    }
    if actual_counts != expected_counts:
        raise RuntimeError(
            "K1442 日期稽核筆數不符已確認的官方差異："
            f"expected={expected_counts}, actual={actual_counts}"
        )
    if set(removed_legacy_dates) != EXPECTED_REMOVED_DATES:
        raise RuntimeError(f"removed legacy dates 不符：{removed_legacy_dates}")
    if set(added_official_dates) != EXPECTED_ADDED_DATES:
        raise RuntimeError(f"added official dates 不符：{added_official_dates}")

    legacy_reproduction_max_abs_diff = verify_legacy_reproduction(df, legacy_frame)
    events_df = build_event_frame(df, cpi_dates)

    # Aggregate stats
    n_events = len(events_df)
    move_pre_mean = float(events_df["move_T0_pct_change_5d"].mean())
    vix_pre_mean = float(events_df["vix_T0_pct_change_5d"].mean())
    move_post_mean = float(events_df["move_post_pct_change_5d"].mean())
    vix_post_mean = float(events_df["vix_post_pct_change_5d"].mean())
    move_pre_median = float(events_df["move_T0_pct_change_5d"].median())
    vix_pre_median = float(events_df["vix_T0_pct_change_5d"].median())
    move_true_pre_mean = float(events_df["move_true_pre_pct_change_5d"].mean())
    vix_true_pre_mean = float(events_df["vix_true_pre_pct_change_5d"].mean())
    move_true_pre_median = float(events_df["move_true_pre_pct_change_5d"].median())
    vix_true_pre_median = float(events_df["vix_true_pre_pct_change_5d"].median())
    move_release_day_mean = float(events_df["move_release_day_pct_change"].mean())
    vix_release_day_mean = float(events_df["vix_release_day_pct_change"].mean())

    # Post-window descriptive decline frequency (not a mispricing test).
    move_drop_after = float((events_df["move_post_pct_change_5d"] < 0).mean() * 100)
    vix_drop_after = float((events_df["vix_post_pct_change_5d"] < 0).mean() * 100)

    # The primary release-date estimand is a decline against zero. Pre-vs-post is
    # secondary and cannot establish that either window itself is negative.
    move_release_tests = directional_decline_tests(
        events_df["move_release_day_pct_change"], SEED
    )
    vix_release_tests = directional_decline_tests(
        events_df["vix_release_day_pct_change"], SEED + 1
    )
    move_post_tests = directional_decline_tests(
        events_df["move_post_pct_change_5d"], SEED + 2
    )
    vix_post_tests = directional_decline_tests(
        events_df["vix_post_pct_change_5d"], SEED + 3
    )

    # Legacy-comparable test retains the shipped T-5→T0 window for the sole
    # purpose of isolating the date correction.
    t_stat_move_legacy, p_move_legacy = scs.ttest_rel(
        events_df["move_T0_pct_change_5d"], events_df["move_post_pct_change_5d"]
    )
    t_stat_vix_legacy, p_vix_legacy = scs.ttest_rel(
        events_df["vix_T0_pct_change_5d"], events_df["vix_post_pct_change_5d"]
    )
    t_stat_move, p_move = scs.ttest_rel(
        events_df["move_true_pre_pct_change_5d"],
        events_df["move_post_pct_change_5d"],
    )
    t_stat_vix, p_vix = scs.ttest_rel(
        events_df["vix_true_pre_pct_change_5d"],
        events_df["vix_post_pct_change_5d"],
    )
    move_bootstrap = paired_bootstrap(
        events_df["move_true_pre_pct_change_5d"],
        events_df["move_post_pct_change_5d"],
        SEED,
    )
    vix_bootstrap = paired_bootstrap(
        events_df["vix_true_pre_pct_change_5d"],
        events_df["vix_post_pct_change_5d"],
        SEED + 1,
    )

    robust_release_assets = [
        asset
        for asset, test in (("MOVE", move_release_tests), ("VIX", vix_release_tests))
        if test["robust_decline"]
    ]
    if robust_release_assets:
        release_day_evidence = (
            "descriptive release-date decline passes the pre-specified gate for "
            + ", ".join(robust_release_assets)
        )
    else:
        release_day_evidence = "no robust negative release-date association"
    post_evidence = (
        "exploratory unadjusted sample association only; no CPI-specific inference"
    )

    results = {
        "experiment_id": "k1442",
        "title": "MOVE/VIX 比值與 CPI 公布前後的隱含波動率定價",
        "sample": {
            "data_source": "yfinance ^MOVE, ^VIX (auto_adjust=False)",
            "event_date_source": EVENT_DATE_SOURCE,
            "period": f"{df.index[0].strftime('%Y-%m-%d')} to {last_date.strftime('%Y-%m-%d')}",
            "n_days": int(n),
            "market_snapshot_file": MARKET_SNAPSHOT_PATH.name,
            "market_snapshot_sha256": market_snapshot_sha256,
            "research_type": "descriptive event study",
        },
        "current_snapshot": {
            "as_of": last_date.strftime("%Y-%m-%d"),
            "MOVE": cur_move,
            "VIX": cur_vix,
            "MOVE_VIX_ratio": cur_ratio,
            "percentile_full_history": pct_all,
            "percentile_trailing_1y": pct_1y,
            "trailing_1y_mean_ratio": mean_1y,
            "full_history_mean_ratio": mean_all,
            "full_history_median_ratio": median_all,
            "full_history_std_ratio": std_all,
        },
        "cpi_event_study": {
            "n_events": int(n_events),
            "window_def": "T-6 to T+5 trading days around CPI release",
            "window_definitions": {
                "true_pre": "T-6 close to T-1 close (five returns; excludes release day)",
                "release_day": "T-1 close to T0 close (contains the release reaction)",
                "post": "T0 close to T+5 close",
                "legacy_comparable": (
                    "T-5 close to T0 close; retained only for date-only comparison "
                    "with the shipped K1442 result and not called pre-CPI"
                ),
            },
            "move_T-5_to_T0_mean_pct": move_pre_mean,
            "move_T-5_to_T0_median_pct": move_pre_median,
            "vix_T-5_to_T0_mean_pct": vix_pre_mean,
            "vix_T-5_to_T0_median_pct": vix_pre_median,
            "move_T-6_to_T-1_mean_pct": move_true_pre_mean,
            "move_T-6_to_T-1_median_pct": move_true_pre_median,
            "vix_T-6_to_T-1_mean_pct": vix_true_pre_mean,
            "vix_T-6_to_T-1_median_pct": vix_true_pre_median,
            "move_T-1_to_T0_mean_pct": move_release_day_mean,
            "vix_T-1_to_T0_mean_pct": vix_release_day_mean,
            "move_T0_to_T+5_mean_pct": move_post_mean,
            "vix_T0_to_T+5_mean_pct": vix_post_mean,
            "move_drop_after_release_pct_events": move_drop_after,
            "vix_drop_after_release_pct_events": vix_drop_after,
            "paired_t_test_move_pre_vs_post": {"t": float(t_stat_move), "p": float(p_move)},
            "paired_t_test_vix_pre_vs_post": {"t": float(t_stat_vix), "p": float(p_vix)},
            "legacy_comparable_paired_t_tests": {
                "note": "T-5 to T0 includes release day; date-only comparison only",
                "move": {"t": float(t_stat_move_legacy), "p": float(p_move_legacy)},
                "vix": {"t": float(t_stat_vix_legacy), "p": float(p_vix_legacy)},
            },
            "paired_bootstrap_move_post_minus_pre": move_bootstrap,
            "paired_bootstrap_vix_post_minus_pre": vix_bootstrap,
            "primary_release_day_decline_tests": {
                "family": "MOVE and VIX release-day changes versus zero",
                "claim_scope": (
                    "descriptive association on CPI release dates; no non-event "
                    "benchmark, surprise regression, or intraday causal identification"
                ),
                "bonferroni_alpha": PRIMARY_ALPHA,
                "MOVE": move_release_tests,
                "VIX": vix_release_tests,
            },
            "secondary_post_5d_decline_tests": {
                "family": "MOVE and VIX T0-to-T+5 changes versus zero",
                "claim_gate": (
                    "exploratory only; unadjusted for overlapping FOMC/NFP/PPI/"
                    "other news and cannot confirm a CPI effect"
                ),
                "bonferroni_alpha": PRIMARY_ALPHA,
                "MOVE": move_post_tests,
                "VIX": vix_post_tests,
            },
            "secondary_pre_vs_post_multiple_testing": {
                "claim_gate": "exploratory only; no independent headline claim",
                "tests": 2,
                "bonferroni_alpha": PRIMARY_ALPHA,
                "move_significant": bool(p_move < PRIMARY_ALPHA),
                "vix_significant": bool(p_vix < PRIMARY_ALPHA),
            },
        },
        "date_correction_audit": {
            "reason": "legacy experiment hard-coded approximate CPI dates",
            "event_date_source": EVENT_DATE_SOURCE,
            "legacy_results_file": LEGACY_RESULTS_PATH.name,
            "legacy_results_sha256": LEGACY_RESULTS_SHA256,
            "legacy_events_file": LEGACY_EVENTS_PATH.name,
            "legacy_events_sha256": LEGACY_EVENTS_SHA256,
            "legacy_dates": legacy_dates,
            "official_dates": official_date_strings,
            "removed_legacy_dates": removed_legacy_dates,
            "added_official_dates": added_official_dates,
            "legacy_metrics": legacy_metrics,
            "legacy_sample": legacy_results.get("sample"),
            "legacy_current_snapshot": legacy_results.get("current_snapshot"),
            "legacy_rows_reproduction_max_abs_diff": legacy_reproduction_max_abs_diff,
            "date_only_comparison": {
                "legacy": {
                    "n_events": legacy_metrics.get("n_events"),
                    "move_T-5_to_T0_mean_pct": legacy_metrics.get(
                        "move_T-5_to_T0_mean_pct"
                    ),
                    "move_T0_to_T+5_mean_pct": legacy_metrics.get(
                        "move_T0_to_T+5_mean_pct"
                    ),
                    "vix_T-5_to_T0_mean_pct": legacy_metrics.get(
                        "vix_T-5_to_T0_mean_pct"
                    ),
                    "vix_T0_to_T+5_mean_pct": legacy_metrics.get(
                        "vix_T0_to_T+5_mean_pct"
                    ),
                },
                "official_dates_same_legacy_window": {
                    "n_events": int(n_events),
                    "move_T-5_to_T0_mean_pct": move_pre_mean,
                    "move_T0_to_T+5_mean_pct": move_post_mean,
                    "vix_T-5_to_T0_mean_pct": vix_pre_mean,
                    "vix_T0_to_T+5_mean_pct": vix_post_mean,
                },
            },
        },
        "interpretation_summary": {
            "ratio_position": (
                "elevated" if pct_all > 75
                else "normal" if pct_all > 25
                else "depressed"
            ),
            "sample_true_pre_move_mean": "本樣本 CPI 前五個交易日 MOVE 平均 " + (
                f"上升 {move_true_pre_mean:.2f}%"
                if move_true_pre_mean > 0
                else f"下降 {abs(move_true_pre_mean):.2f}%"
            ),
            "sample_post_5d_move_decline_frequency": (
                f"本樣本 T0→T+5 MOVE 下跌頻率 {move_drop_after:.1f}%"
            ),
            "release_day_decline_association": release_day_evidence,
            "post_5d_association_scope": post_evidence,
            "conclusion_strength": (
                "descriptive sample association only; no CPI-specific causal, "
                "mispricing, mechanism, or directional trading claim"
            ),
        },
        "references": REFERENCES,
    }

    # Figure 1: MOVE/VIX ratio time series with percentile bands + current marker
    fig, ax = plt.subplots(figsize=(11, 5.5))
    df["ratio"].plot(ax=ax, color="#2c5f8d", linewidth=0.7, label="MOVE/VIX ratio")
    ax.axhline(median_all, color="gray", linestyle="--", linewidth=0.7, alpha=0.7, label=f"歷史中位數 {median_all:.2f}")
    ax.axhline(df["ratio"].quantile(0.9), color="orange", linestyle=":", linewidth=0.7, alpha=0.7, label=f"歷史 P90 {df['ratio'].quantile(0.9):.2f}")
    ax.axhline(df["ratio"].quantile(0.1), color="green", linestyle=":", linewidth=0.7, alpha=0.7, label=f"歷史 P10 {df['ratio'].quantile(0.1):.2f}")
    ax.scatter([last_date], [cur_ratio], color="red", s=80, zorder=5, label=f"當前 {cur_ratio:.2f} (P{pct_all:.0f})")
    ax.set_title(f"MOVE/VIX 比值（{df.index[0].year}–{last_date.year}）\n當前 {cur_ratio:.2f}，歷史百分位 P{pct_all:.0f}")
    ax.set_xlabel("日期")
    ax.set_ylabel("MOVE / VIX")
    ax.legend(loc="upper right", fontsize=9)
    ax.grid(alpha=0.3)
    plt.tight_layout()
    fig_ratio_tmp = stage_figure(fig, FIG_RATIO_PATH)

    # Figure 2: CPI event study — MOVE & VIX % change pre vs post
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    axes[0].hist(events_df["move_true_pre_pct_change_5d"], bins=12, alpha=0.55, color="#2c5f8d", edgecolor="white", label="T-6→T-1 (pre)")
    axes[0].hist(events_df["move_release_day_pct_change"], bins=12, alpha=0.45, color="#6f9f6f", edgecolor="white", label="T-1→T0 (release day)")
    axes[0].hist(events_df["move_post_pct_change_5d"], bins=12, alpha=0.45, color="#d97441", edgecolor="white", label="T0→T+5 (post)")
    axes[0].axvline(0, color="gray", linewidth=0.8)
    axes[0].axvline(move_true_pre_mean, color="#2c5f8d", linestyle="--", linewidth=1, label=f"pre 均值 {move_true_pre_mean:+.2f}%")
    axes[0].axvline(move_post_mean, color="#d97441", linestyle="--", linewidth=1, label=f"post 均值 {move_post_mean:+.2f}%")
    axes[0].set_title(f"MOVE 在 CPI 前後 5 日 % 變化（{n_events} 次事件）")
    axes[0].set_xlabel("% change")
    axes[0].set_ylabel("event count")
    axes[0].legend(fontsize=8)

    axes[1].hist(events_df["vix_true_pre_pct_change_5d"], bins=12, alpha=0.55, color="#2c5f8d", edgecolor="white", label="T-6→T-1 (pre)")
    axes[1].hist(events_df["vix_release_day_pct_change"], bins=12, alpha=0.45, color="#6f9f6f", edgecolor="white", label="T-1→T0 (release day)")
    axes[1].hist(events_df["vix_post_pct_change_5d"], bins=12, alpha=0.45, color="#d97441", edgecolor="white", label="T0→T+5 (post)")
    axes[1].axvline(0, color="gray", linewidth=0.8)
    axes[1].axvline(vix_true_pre_mean, color="#2c5f8d", linestyle="--", linewidth=1, label=f"pre 均值 {vix_true_pre_mean:+.2f}%")
    axes[1].axvline(vix_post_mean, color="#d97441", linestyle="--", linewidth=1, label=f"post 均值 {vix_post_mean:+.2f}%")
    axes[1].set_title(f"VIX 在 CPI 前後 5 日 % 變化（{n_events} 次事件）")
    axes[1].set_xlabel("% change")
    axes[1].legend(fontsize=8)

    plt.tight_layout()
    fig_event_tmp = stage_figure(fig, FIG_EVENT_PATH)

    # Stage and validate every output before replacing any canonical artifact.
    # Results JSON is replaced last and serves as the commit marker for the set.
    events_tmp = stage_csv(EVENTS_PATH, events_df)
    results_tmp = stage_json(RESULTS_PATH, results)
    staged = [
        (fig_ratio_tmp, FIG_RATIO_PATH),
        (fig_event_tmp, FIG_EVENT_PATH),
        (events_tmp, EVENTS_PATH),
        (results_tmp, RESULTS_PATH),
    ]
    try:
        for tmp, target in staged:
            os.replace(tmp, target)
    except Exception:
        for tmp, _target in staged:
            tmp.unlink(missing_ok=True)
        raise

    print(json.dumps(results, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
