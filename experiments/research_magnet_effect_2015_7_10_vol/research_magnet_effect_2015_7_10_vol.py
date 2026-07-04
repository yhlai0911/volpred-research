"""Taiwan price-limit magnet effect around the 2015 7% -> 10% widening.

This experiment uses official TWSE daily all-stock closing data and tests a
daily proxy for price-limit dynamics:

    event day = a common stock either touches the up/down limit intraday or
                closes within 1 percentage point of the applicable limit.

Main target:
    next trading day's close-to-close absolute return and signed continuation.

Important scope limitation:
    Daily OHLC can test next-day continuation/reversal after limit pressure,
    but it cannot establish true intraday "magnet" behavior. Intraday order
    book / trade data would be required for that stronger claim.
"""
from __future__ import annotations

import csv
import io
import json
import math
import time
import urllib.error
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

SEED = 42
EXPERIMENT_ID = "research_magnet_effect_2015_7_10_vol"
OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = OUT_DIR / "data"
START = "2014-01-01"
END = "2016-12-31"
CHANGE_DATE = pd.Timestamp("2015-06-01")
PRE_LIMIT = 0.07
POST_LIMIT = 0.10
NEAR_CLOSE_BAND = 0.01
TOUCH_TOL = 0.0025
MIN_EVENT_STOCKS_PER_DAY = 5
MIN_CONTROL_STOCKS_PER_DAY = 50
MAX_FETCH_FAILURES = 30


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return obj.tolist()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.isoformat()
    return str(obj)


def _clean_code(value: object) -> str:
    text = str(value).strip()
    if text.startswith("="):
        text = text[1:]
    return text.strip().strip('"')


def _to_float(value: object) -> float:
    if value is None or pd.isna(value):
        return np.nan
    text = str(value).strip().replace(",", "")
    if text in {"", "--", "---", "除權", "除息"}:
        return np.nan
    try:
        return float(text)
    except ValueError:
        return np.nan


def fetch_twse_day(date: pd.Timestamp) -> pd.DataFrame:
    """Fetch one official TWSE MI_INDEX CSV day and return common-stock OHLC."""
    ymd = date.strftime("%Y%m%d")
    # The newer /rwd/zh/afterTrading endpoint intermittently returns a TWSE
    # security-block HTML page for historical dates. The legacy endpoint is the
    # same official MI_INDEX CSV surface and is stable for 2014-2016.
    url = (
        "https://www.twse.com.tw/exchangeReport/MI_INDEX"
        f"?response=csv&date={ymd}&type=ALLBUT0999"
    )
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 VolPred research script",
            "Accept": "text/csv,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()

    text = raw.decode("big5", errors="replace")
    lines = text.splitlines()
    header_idx = None
    for i, line in enumerate(lines):
        if "證券代號" in line and "收盤價" in line:
            header_idx = i
            break
    if header_idx is None:
        return pd.DataFrame()

    csv_text = "\n".join(lines[header_idx:])
    df = pd.read_csv(
        io.StringIO(csv_text),
        dtype=str,
        engine="python",
        quoting=csv.QUOTE_MINIMAL,
        on_bad_lines="skip",
    )
    if df.empty or "證券代號" not in df.columns:
        return pd.DataFrame()

    df["ticker"] = df["證券代號"].map(_clean_code)
    # Keep ordinary listed common stocks. This excludes ETFs (00xx), warrants,
    # preferred shares, and most special products.
    df = df[df["ticker"].str.match(r"^[1-9][0-9]{3}$", na=False)].copy()
    if df.empty:
        return pd.DataFrame()

    rename = {
        "證券名稱": "name",
        "成交股數": "volume_shares",
        "成交金額": "turnover_twd",
        "開盤價": "open",
        "最高價": "high",
        "最低價": "low",
        "收盤價": "close",
        "漲跌(+/-)": "change_sign",
        "漲跌價差": "change_amount",
    }
    df = df.rename(columns=rename)
    keep = [
        "ticker",
        "name",
        "volume_shares",
        "turnover_twd",
        "open",
        "high",
        "low",
        "close",
        "change_sign",
        "change_amount",
    ]
    df = df[[c for c in keep if c in df.columns]].copy()
    for col in ["volume_shares", "turnover_twd", "open", "high", "low", "close", "change_amount"]:
        if col in df.columns:
            df[col] = df[col].map(_to_float)
    df["date"] = pd.Timestamp(date).normalize()
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def fetch_panel(start: str, end: str) -> tuple[pd.DataFrame, dict]:
    dates = pd.date_range(start, end, freq="B")
    frames = []
    no_data_dates = []
    failed_dates = []
    t0 = time.time()
    for i, date in enumerate(dates, 1):
        try:
            day = fetch_twse_day(date)
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            failed_dates.append({"date": date.date().isoformat(), "error": f"{type(exc).__name__}: {exc}"})
            print(f"[fetch] WARN {date.date()} failed: {exc}")
            day = pd.DataFrame()
        if not day.empty:
            frames.append(day)
        else:
            no_data_dates.append(date.date().isoformat())
        if i % 50 == 0:
            print(
                f"[fetch] {i}/{len(dates)} weekdays, trading_days={len(frames)}, "
                f"failures={len(failed_dates)}, elapsed={time.time() - t0:.1f}s"
            )
        time.sleep(0.03)

    if len(failed_dates) > MAX_FETCH_FAILURES:
        raise RuntimeError(f"Too many TWSE fetch failures: {len(failed_dates)}")
    if not frames:
        raise RuntimeError("No TWSE daily data fetched")

    panel = pd.concat(frames, ignore_index=True)
    meta = {
        "weekday_candidates": len(dates),
        "trading_days_fetched": int(panel["date"].nunique()),
        "no_data_dates_count": len(no_data_dates),
        "failed_dates": failed_dates,
        "first_trading_date": panel["date"].min().date().isoformat(),
        "last_trading_date": panel["date"].max().date().isoformat(),
    }
    return panel, meta


def build_event_panel(panel: pd.DataFrame) -> pd.DataFrame:
    df = panel.sort_values(["ticker", "date"]).copy()
    df["prev_close"] = df.groupby("ticker")["close"].shift(1)
    df["next_close"] = df.groupby("ticker")["close"].shift(-1)
    df["next_date"] = df.groupby("ticker")["date"].shift(-1)
    df["next_change_sign"] = df.groupby("ticker")["change_sign"].shift(-1)
    df["calendar_gap_next"] = (df["next_date"] - df["date"]).dt.days

    df["limit_pct"] = np.where(df["date"] < CHANGE_DATE, PRE_LIMIT, POST_LIMIT)
    df["post_widening"] = (df["date"] >= CHANGE_DATE).astype(int)
    df["ret_close"] = df["close"] / df["prev_close"] - 1.0
    df["ret_high"] = df["high"] / df["prev_close"] - 1.0
    df["ret_low"] = df["low"] / df["prev_close"] - 1.0
    df["same_abs_ret"] = df["ret_close"].abs()
    df["next_ret"] = np.log(df["next_close"] / df["close"])
    df["next_abs_ret"] = df["next_ret"].abs()
    df["log_turnover"] = np.log(df["turnover_twd"].replace(0, np.nan))

    comparable = (
        df["prev_close"].gt(0)
        & df["close"].gt(0)
        & df["next_close"].gt(0)
        & df["calendar_gap_next"].between(1, 10)
        & ~df["change_sign"].fillna("").str.contains("X", regex=False)
        & ~df["next_change_sign"].fillna("").str.contains("X", regex=False)
    )

    upper_touch = df["ret_high"] >= (df["limit_pct"] - TOUCH_TOL)
    lower_touch = df["ret_low"] <= (-df["limit_pct"] + TOUCH_TOL)
    upper_near_close = df["ret_close"] >= (df["limit_pct"] - NEAR_CLOSE_BAND)
    lower_near_close = df["ret_close"] <= (-df["limit_pct"] + NEAR_CLOSE_BAND)
    ambiguous_both = (upper_touch | upper_near_close) & (lower_touch | lower_near_close)

    df["upper_event"] = comparable & ~ambiguous_both & (upper_touch | upper_near_close)
    df["lower_event"] = comparable & ~ambiguous_both & (lower_touch | lower_near_close)
    df["event_any"] = df["upper_event"] | df["lower_event"]
    df["touch_any"] = comparable & ~ambiguous_both & (upper_touch | lower_touch)
    df["near_close_any"] = comparable & ~ambiguous_both & (upper_near_close | lower_near_close)
    df["event_side"] = np.select([df["upper_event"], df["lower_event"]], [1.0, -1.0], default=np.nan)
    df["side_adjusted_next_ret"] = df["event_side"] * df["next_ret"]
    df["next_continues"] = df["side_adjusted_next_ret"] > 0

    # Fixed old-7% band robustness. This is the cleaner natural-experiment
    # comparison: after 2015-06-01, stocks can pass the old 7% boundary without
    # being halted, so we avoid mechanically selecting only more extreme +/-10%
    # post-widening observations.
    old_upper_touch = df["ret_high"] >= (PRE_LIMIT - TOUCH_TOL)
    old_lower_touch = df["ret_low"] <= (-PRE_LIMIT + TOUCH_TOL)
    old_upper_near_close = df["ret_close"] >= (PRE_LIMIT - NEAR_CLOSE_BAND)
    old_lower_near_close = df["ret_close"] <= (-PRE_LIMIT + NEAR_CLOSE_BAND)
    old_ambiguous = (old_upper_touch | old_upper_near_close) & (old_lower_touch | old_lower_near_close)
    df["old7_upper_event"] = comparable & ~old_ambiguous & (old_upper_touch | old_upper_near_close)
    df["old7_lower_event"] = comparable & ~old_ambiguous & (old_lower_touch | old_lower_near_close)
    df["old7_event_any"] = df["old7_upper_event"] | df["old7_lower_event"]
    df["old7_touch_any"] = comparable & ~old_ambiguous & (old_upper_touch | old_lower_touch)
    df["old7_near_close_any"] = comparable & ~old_ambiguous & (old_upper_near_close | old_lower_near_close)
    df["old7_event_side"] = np.select(
        [df["old7_upper_event"], df["old7_lower_event"]],
        [1.0, -1.0],
        default=np.nan,
    )
    df["old7_side_adjusted_next_ret"] = df["old7_event_side"] * df["next_ret"]
    df["old7_next_continues"] = df["old7_side_adjusted_next_ret"] > 0
    df["valid_target"] = comparable
    return df


def daily_event_summary(
    events: pd.DataFrame,
    *,
    event_col: str = "event_any",
    upper_col: str = "upper_event",
    lower_col: str = "lower_event",
    touch_col: str = "touch_any",
    near_col: str = "near_close_any",
    side_adj_col: str = "side_adjusted_next_ret",
    continuation_col: str = "next_continues",
) -> pd.DataFrame:
    valid = events[events["valid_target"]].copy()
    rows = []
    for date, g in valid.groupby("date"):
        event = g[g[event_col]]
        control = g[~g[event_col]]
        row = {
            "date": date,
            "post_widening": int(date >= CHANGE_DATE),
            "stock_count": int(len(g)),
            "event_count": int(len(event)),
            "control_count": int(len(control)),
            "event_rate": float(len(event) / len(g)) if len(g) else np.nan,
            "upper_event_count": int(g[upper_col].sum()),
            "lower_event_count": int(g[lower_col].sum()),
            "touch_count": int(g[touch_col].sum()),
            "near_close_count": int(g[near_col].sum()),
        }
        if len(event) >= MIN_EVENT_STOCKS_PER_DAY and len(control) >= MIN_CONTROL_STOCKS_PER_DAY:
            row.update({
                "event_next_abs_mean": float(event["next_abs_ret"].mean()),
                "control_next_abs_mean": float(control["next_abs_ret"].mean()),
                "diff_next_abs": float(event["next_abs_ret"].mean() - control["next_abs_ret"].mean()),
                "event_side_adj_next_ret_mean": float(event[side_adj_col].mean()),
                "event_continuation_share": float(event[continuation_col].mean()),
            })
        rows.append(row)
    out = pd.DataFrame(rows).sort_values("date")
    return out


def hac_regression_daily(summary: pd.DataFrame, y_col: str, hac_lags: int = 5) -> dict:
    use = summary[[y_col, "post_widening"]].replace([np.inf, -np.inf], np.nan).dropna()
    x = sm.add_constant(use["post_widening"].astype(float), has_constant="add")
    y = use[y_col].astype(float)
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lags})
    pre = use.loc[use["post_widening"] == 0, y_col]
    post = use.loc[use["post_widening"] == 1, y_col]
    coef = float(model.params["post_widening"])
    return {
        "target": y_col,
        "n_days": int(len(use)),
        "pre_n_days": int(len(pre)),
        "post_n_days": int(len(post)),
        "pre_mean": float(pre.mean()),
        "post_mean": float(post.mean()),
        "post_minus_pre": coef,
        "se": float(model.bse["post_widening"]),
        "t_stat": float(model.tvalues["post_widening"]),
        "p_value": float(model.pvalues["post_widening"]),
        "harvey_pass_abs_t_gt_3": bool(abs(float(model.tvalues["post_widening"])) > 3.0),
        "hac_lags": hac_lags,
    }


def cluster_cross_section_regression(events: pd.DataFrame, event_col: str = "event_any") -> dict:
    use = events[events["valid_target"]].copy()
    use = use[[
        "date",
        "next_abs_ret",
        event_col,
        "post_widening",
        "same_abs_ret",
        "log_turnover",
    ]].replace([np.inf, -np.inf], np.nan).dropna()
    use["event_indicator"] = use[event_col].astype(float)
    use["event_post"] = use["event_indicator"] * use["post_widening"].astype(float)
    x_cols = ["event_indicator", "post_widening", "event_post", "same_abs_ret", "log_turnover"]
    x = sm.add_constant(use[x_cols].astype(float), has_constant="add")
    y = use["next_abs_ret"].astype(float)
    model = sm.OLS(y, x).fit(cov_type="cluster", cov_kwds={"groups": use["date"]})
    return {
        "target": "next_abs_ret",
        "event_col": event_col,
        "n_obs": int(model.nobs),
        "n_dates": int(use["date"].nunique()),
        "coef_event_pre": float(model.params["event_indicator"]),
        "coef_event_post_change": float(model.params["event_post"]),
        "coef_event_post_total": float(model.params["event_indicator"] + model.params["event_post"]),
        "t_event_pre": float(model.tvalues["event_indicator"]),
        "p_event_pre": float(model.pvalues["event_indicator"]),
        "t_event_post_change": float(model.tvalues["event_post"]),
        "p_event_post_change": float(model.pvalues["event_post"]),
        "cluster_by": "date",
        "harvey_pass_event_pre_abs_t_gt_3": bool(abs(float(model.tvalues["event_indicator"])) > 3.0),
        "harvey_pass_event_post_change_abs_t_gt_3": bool(abs(float(model.tvalues["event_post"])) > 3.0),
    }


def make_figure(summary: pd.DataFrame, out_path: Path) -> None:
    plot = summary.copy()
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), sharex=True)
    axes[0].plot(plot["date"], plot["event_rate"] * 100, lw=1.0, color="#1f77b4")
    axes[0].axvline(CHANGE_DATE, color="#333333", ls="--", lw=1)
    axes[0].set_title("TWSE common stocks near/touching daily price limits")
    axes[0].set_ylabel("Event rate (%)")
    axes[0].grid(alpha=0.25)

    axes[1].plot(plot["date"], plot["diff_next_abs"] * 100, lw=0.9, color="#d62728")
    axes[1].axhline(0, color="#777777", lw=0.8)
    axes[1].axvline(CHANGE_DATE, color="#333333", ls="--", lw=1)
    axes[1].set_title("Next-day abs-return premium: event stocks minus controls")
    axes[1].set_ylabel("Percentage points")
    axes[1].grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(out_path, dpi=160)
    plt.close(fig)


def verdict_from_results(old7_abs_did: dict, old7_continuation_did: dict, old7_xsec: dict) -> str:
    if old7_abs_did["harvey_pass_abs_t_gt_3"] and old7_xsec["harvey_pass_event_post_change_abs_t_gt_3"]:
        return "STRUCTURAL_BREAK_PASS"
    if old7_continuation_did["harvey_pass_abs_t_gt_3"] and old7_continuation_did["post_minus_pre"] < 0:
        return "CONTINUATION_WEAKENED_DAILY_PROXY_NO_VOL_BREAK"
    if old7_continuation_did["harvey_pass_abs_t_gt_3"] and old7_continuation_did["post_minus_pre"] > 0:
        return "CONTINUATION_STRENGTHENED_DAILY_PROXY_NO_VOL_BREAK"
    if old7_xsec["harvey_pass_event_pre_abs_t_gt_3"] and not old7_xsec["harvey_pass_event_post_change_abs_t_gt_3"]:
        return "EVENT_PREMIUM_NO_WIDENING_BREAK"
    return "NULL_OR_DAILY_PROXY_LIMITED"


def main() -> None:
    np.random.seed(SEED)
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    print(f"[{EXPERIMENT_ID}] fetching TWSE MI_INDEX {START}..{END}")
    panel, fetch_meta = fetch_panel(START, END)
    print(f"[{EXPERIMENT_ID}] panel rows={len(panel):,}, trading_days={panel['date'].nunique()}")

    events = build_event_panel(panel)
    summary = daily_event_summary(events)
    old7_summary = daily_event_summary(
        events,
        event_col="old7_event_any",
        upper_col="old7_upper_event",
        lower_col="old7_lower_event",
        touch_col="old7_touch_any",
        near_col="old7_near_close_any",
        side_adj_col="old7_side_adjusted_next_ret",
        continuation_col="old7_next_continues",
    )

    event_rows = events[events["event_any"] & events["valid_target"]].copy()
    old7_event_rows = events[events["old7_event_any"] & events["valid_target"]].copy()
    sample_cols = [
        "date", "ticker", "name", "limit_pct", "ret_close", "ret_high", "ret_low",
        "upper_event", "lower_event", "touch_any", "near_close_any", "next_ret",
        "next_abs_ret", "side_adjusted_next_ret", "old7_upper_event", "old7_lower_event",
        "old7_touch_any", "old7_near_close_any", "old7_side_adjusted_next_ret",
    ]
    event_rows[sample_cols].to_csv(DATA_DIR / "event_rows.csv", index=False)
    summary.to_csv(DATA_DIR / "daily_event_summary.csv", index=False)
    old7_event_rows[sample_cols].to_csv(DATA_DIR / "old7_event_rows.csv", index=False)
    old7_summary.to_csv(DATA_DIR / "old7_daily_event_summary.csv", index=False)

    abs_did = hac_regression_daily(summary, "diff_next_abs", hac_lags=5)
    continuation_did = hac_regression_daily(summary, "event_side_adj_next_ret_mean", hac_lags=5)
    xsec = cluster_cross_section_regression(events)
    old7_abs_did = hac_regression_daily(old7_summary, "diff_next_abs", hac_lags=5)
    old7_continuation_did = hac_regression_daily(old7_summary, "event_side_adj_next_ret_mean", hac_lags=5)
    old7_xsec = cluster_cross_section_regression(events, event_col="old7_event_any")

    fig_path = OUT_DIR / "magnet_effect_daily_proxy.png"
    make_figure(summary, fig_path)

    pre_summary = summary[summary["post_widening"] == 0]
    post_summary = summary[summary["post_widening"] == 1]
    event_summary = {
        "total_valid_stock_days": int(events["valid_target"].sum()),
        "total_event_stock_days": int((events["event_any"] & events["valid_target"]).sum()),
        "total_old7_event_stock_days": int((events["old7_event_any"] & events["valid_target"]).sum()),
        "total_upper_event_stock_days": int((events["upper_event"] & events["valid_target"]).sum()),
        "total_lower_event_stock_days": int((events["lower_event"] & events["valid_target"]).sum()),
        "mean_stock_count_per_day": float(summary["stock_count"].mean()),
        "mean_event_rate_pre": float(pre_summary["event_rate"].mean()),
        "mean_event_rate_post": float(post_summary["event_rate"].mean()),
        "mean_event_count_pre": float(pre_summary["event_count"].mean()),
        "mean_event_count_post": float(post_summary["event_count"].mean()),
        "days_with_min_events": int(summary["diff_next_abs"].notna().sum()),
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Taiwan price-limit magnet-effect daily proxy around 2015 widening",
        "run_date": pd.Timestamp.now(tz="UTC").isoformat(),
        "seed": SEED,
        "verdict": verdict_from_results(old7_abs_did, old7_continuation_did, old7_xsec),
        "data": {
            "source": "TWSE official exchangeReport/MI_INDEX daily CSV, type=ALLBUT0999, response=csv",
            "period": {"start": START, "end": END},
            "sample": "TWSE 4-digit common stocks only; ETFs, warrants, preferred/special products excluded",
            "change_date": CHANGE_DATE.date().isoformat(),
            "price_limit_pre": PRE_LIMIT,
            "price_limit_post": POST_LIMIT,
            "event_definition": {
                "touch_tolerance": TOUCH_TOL,
                "near_close_band": NEAR_CLOSE_BAND,
                "event_any": "intraday high/low touches applicable limit within tolerance OR close is within 1pp of applicable limit",
                "old7_event_any": "same rule but fixed at the old 7% band in both pre and post periods",
            },
            "fetch_meta": fetch_meta,
        },
        "event_summary": event_summary,
        "tests": {
            "applicable_limit": {
                "daily_diff_abs_return_did": abs_did,
                "daily_side_adjusted_continuation_did": continuation_did,
                "cross_section_clustered_event_regression": xsec,
                "note": "Post events are selected at +/-10% while pre events are selected at +/-7%; use old7_band_robustness for the cleaner natural-experiment comparison.",
            },
            "old7_band_robustness": {
                "daily_diff_abs_return_did": old7_abs_did,
                "daily_side_adjusted_continuation_did": old7_continuation_did,
                "cross_section_clustered_event_regression": old7_xsec,
            },
        },
        "interpretation": {
            "primary_gate": (
                "Primary inference uses the fixed old7_band robustness, not the mechanically "
                "more extreme applicable-limit post events. A credible widening effect requires "
                "the daily event-minus-control next-day abs-return premium and the cross-sectional "
                "event_post interaction to pass Harvey |t|>3 in the same direction."
            ),
            "limitations": [
                "Daily OHLC proxy only; cannot prove intraday magnet behavior.",
                "No trade-level order book, no true TAIFEX tick RV target, and no adjustment for intraday approach speed.",
                "Raw TWSE prices are not split/dividend adjusted; rows marked X/no-comparison and next-day X rows are excluded.",
                "Some securities may have special treatment limits; ordinary 4-digit common-stock filter reduces but does not eliminate this risk.",
                "The event threshold changes mechanically from 7% to 10%, so event-rate changes are not directly comparable as investor behavior.",
            ],
        },
        "artifacts": {
            "daily_summary": "data/daily_event_summary.csv",
            "event_rows": "data/event_rows.csv",
            "old7_daily_summary": "data/old7_daily_event_summary.csv",
            "old7_event_rows": "data/old7_event_rows.csv",
            "figure": "magnet_effect_daily_proxy.png",
        },
    }

    out = OUT_DIR / f"{EXPERIMENT_ID}_results.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=True, default=_json_default) + "\n")
    print(json.dumps({
        "verdict": results["verdict"],
        "valid_stock_days": event_summary["total_valid_stock_days"],
        "event_stock_days": event_summary["total_event_stock_days"],
        "applicable_daily_abs_did_t": abs_did["t_stat"],
        "old7_daily_abs_did_t": old7_abs_did["t_stat"],
        "old7_daily_abs_pre_mean": old7_abs_did["pre_mean"],
        "old7_daily_abs_post_mean": old7_abs_did["post_mean"],
        "old7_xsec_event_pre_t": old7_xsec["t_event_pre"],
        "old7_xsec_event_post_change_t": old7_xsec["t_event_post_change"],
        "results": str(out),
    }, indent=2))


if __name__ == "__main__":
    main()
