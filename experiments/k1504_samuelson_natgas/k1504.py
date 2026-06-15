"""K1504: Natural gas seasonality and a front-month Samuelson proxy.

This experiment tests two related but distinct claims:

1. Natural gas realized volatility has calendar-month seasonality.
2. Front-month NG=F volatility rises as the approximate NYMEX expiry date
   approaches, a free-data proxy for the Samuelson maturity effect.

The Samuelson leg uses Yahoo's continuous front-month `NG=F` series and an
approximate CME expiry calendar. It is not a contract-level panel.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from pandas.tseries.offsets import BDay, MonthBegin
from scipy import stats

SEED = 42
RNG = np.random.default_rng(SEED)

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).resolve().parent
DATA_DIR = OUT_DIR / "data"
FIG_DIR = OUT_DIR / "figures"

LOCAL_SOURCE = (
    ROOT
    / "experiments"
    / "research_inventory_seasonality_surprise_regime_conditiona"
    / "data"
    / "close.csv"
)
CLOSE_CACHE = DATA_DIR / "natgas_close.csv"
MONTHLY_PANEL_PATH = DATA_DIR / "monthly_realized_vol.csv"
SAMUELSON_PANEL_PATH = DATA_DIR / "ng_front_month_expiry_panel.csv"

START_DATE = "2006-01-01"
END_DATE = "2026-06-16"  # yfinance end is exclusive
TICKERS = ["NG=F", "UNG"]
BOOT_REPS = 5000
PERM_REPS = 5000
HARVEY_T_ABS = 3.0

MONTH_NAMES = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}
WINTER_MONTHS = {11, 12, 1, 2, 3}
SUMMER_MONTHS = {6, 7, 8}


@dataclass
class AnovaResult:
    ticker: str
    n_months: int
    f_stat: float
    p_value: float
    permutation_p: float
    peak_month: int
    trough_month: int
    peak_rv_ann: float
    trough_rv_ann: float
    peak_trough_ratio: float
    winter_mean_rv_ann: float
    non_winter_mean_rv_ann: float
    winter_ratio: float
    summer_mean_rv_ann: float
    non_summer_mean_rv_ann: float
    summer_ratio: float


@dataclass
class RegressionResult:
    ticker: str
    n_obs: int
    model: str
    coefficient: float
    hac_t: float
    hac_p: float
    r_squared: float
    expected_direction: str
    harvey_pass_abs_t_gt_3: bool


@dataclass
class BucketResult:
    bucket: str
    n_obs: int
    rms_vol_ann: float
    mean_abs_return: float
    mean_log_abs_return: float


def load_close() -> pd.DataFrame:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if CLOSE_CACHE.exists():
        close = pd.read_csv(CLOSE_CACHE, index_col=0, parse_dates=True)
        return close[TICKERS].sort_index()

    if LOCAL_SOURCE.exists():
        raw = pd.read_csv(LOCAL_SOURCE, parse_dates=["Date"]).set_index("Date")
        close = raw[TICKERS].copy().sort_index()
        close.to_csv(CLOSE_CACHE)
        return close

    raw = yf.download(
        TICKERS,
        start=START_DATE,
        end=END_DATE,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    close = pd.DataFrame()
    for ticker in TICKERS:
        try:
            close[ticker] = raw[ticker]["Close"]
        except Exception:
            close[ticker] = raw["Close"][ticker]
    close = close.sort_index()
    close.to_csv(CLOSE_CACHE)
    return close


def clean_close(close: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    raw_rows = len(close)
    weekend_rows = int((close.index.dayofweek >= 5).sum())
    out = close.copy()
    out = out[out.index.dayofweek < 5].copy()
    for col in TICKERS:
        out.loc[out[col] <= 0, col] = np.nan
    out = out.dropna(how="all")
    return out, {
        "raw_rows": raw_rows,
        "weekend_rows_dropped": weekend_rows,
        "clean_rows": len(out),
        "start": str(out.index.min().date()),
        "end": str(out.index.max().date()),
        "source": (
            f"local snapshot {LOCAL_SOURCE.relative_to(ROOT)}"
            if LOCAL_SOURCE.exists()
            else "yfinance download fallback"
        ),
    }


def build_returns(close: pd.DataFrame) -> pd.DataFrame:
    rets = np.log(close / close.shift(1))
    rets = rets.replace([np.inf, -np.inf], np.nan)
    return rets


def build_monthly_panel(rets: pd.DataFrame) -> pd.DataFrame:
    records: list[dict] = []
    for ticker in TICKERS:
        s = rets[ticker].dropna()
        for month_end, g in s.groupby(s.index.to_period("M").to_timestamp("M")):
            if len(g) < 10:
                continue
            month = int(pd.Timestamp(month_end).month)
            rv_ann = float(np.sqrt(np.mean(np.square(g))) * np.sqrt(252))
            records.append(
                {
                    "month_end": pd.Timestamp(month_end),
                    "ticker": ticker,
                    "n_days": int(len(g)),
                    "month": month,
                    "month_name": MONTH_NAMES[month],
                    "year": int(pd.Timestamp(month_end).year),
                    "rv_ann": rv_ann,
                    "log_rv_ann": float(np.log(max(rv_ann, 1e-12))),
                    "is_winter": int(month in WINTER_MONTHS),
                    "is_summer": int(month in SUMMER_MONTHS),
                }
            )
    panel = pd.DataFrame(records).sort_values(["ticker", "month_end"])
    panel["lag_log_rv_ann"] = panel.groupby("ticker")["log_rv_ann"].shift(1)
    # Explicit lag guard: persistence controls use t-1 monthly realized vol.
    panel.to_csv(MONTHLY_PANEL_PATH, index=False)
    return panel


def one_way_f(groups: list[np.ndarray]) -> float:
    vals = np.concatenate(groups)
    grand = float(np.mean(vals))
    ss_between = sum(len(g) * (float(np.mean(g)) - grand) ** 2 for g in groups)
    ss_within = sum(float(np.sum((g - float(np.mean(g))) ** 2)) for g in groups)
    df_between = len(groups) - 1
    df_within = len(vals) - len(groups)
    if df_within <= 0 or ss_within <= 0:
        return float("nan")
    return (ss_between / df_between) / (ss_within / df_within)


def permutation_anova_p(values: np.ndarray, labels: np.ndarray) -> float:
    unique = np.array(sorted(set(labels)))
    obs_groups = [values[labels == m] for m in unique]
    obs = one_way_f(obs_groups)
    count = 0
    for _ in range(PERM_REPS):
        shuffled = RNG.permutation(labels)
        groups = [values[shuffled == m] for m in unique]
        if one_way_f(groups) >= obs:
            count += 1
    return float((count + 1) / (PERM_REPS + 1))


def seasonality_tests(monthly: pd.DataFrame) -> dict[str, AnovaResult]:
    out: dict[str, AnovaResult] = {}
    for ticker in TICKERS:
        sub = monthly[monthly["ticker"] == ticker].dropna(subset=["rv_ann"]).copy()
        groups = [g["rv_ann"].to_numpy() for _, g in sub.groupby("month")]
        f_stat, p_value = stats.f_oneway(*groups)
        perm_p = permutation_anova_p(
            sub["rv_ann"].to_numpy(),
            sub["month"].to_numpy(),
        )
        by_month = sub.groupby("month")["rv_ann"].mean()
        peak_month = int(by_month.idxmax())
        trough_month = int(by_month.idxmin())
        winter = sub[sub["is_winter"] == 1]["rv_ann"]
        non_winter = sub[sub["is_winter"] == 0]["rv_ann"]
        summer = sub[sub["is_summer"] == 1]["rv_ann"]
        non_summer = sub[sub["is_summer"] == 0]["rv_ann"]
        out[ticker] = AnovaResult(
            ticker=ticker,
            n_months=int(len(sub)),
            f_stat=float(f_stat),
            p_value=float(p_value),
            permutation_p=perm_p,
            peak_month=peak_month,
            trough_month=trough_month,
            peak_rv_ann=float(by_month.loc[peak_month]),
            trough_rv_ann=float(by_month.loc[trough_month]),
            peak_trough_ratio=float(by_month.loc[peak_month] / by_month.loc[trough_month]),
            winter_mean_rv_ann=float(winter.mean()),
            non_winter_mean_rv_ann=float(non_winter.mean()),
            winter_ratio=float(winter.mean() / non_winter.mean()),
            summer_mean_rv_ann=float(summer.mean()),
            non_summer_mean_rv_ann=float(non_summer.mean()),
            summer_ratio=float(summer.mean() / non_summer.mean()),
        )
    return out


def fit_monthly_regressions(monthly: pd.DataFrame) -> dict[str, list[RegressionResult]]:
    results: dict[str, list[RegressionResult]] = {}
    for ticker in TICKERS:
        sub = monthly[monthly["ticker"] == ticker].dropna(
            subset=["log_rv_ann", "lag_log_rv_ann"]
        )
        y = sub["log_rv_ann"]
        x = pd.DataFrame(
            {
                "const": 1.0,
                "is_winter": sub["is_winter"].astype(float),
                "is_summer": sub["is_summer"].astype(float),
                "lag_log_rv_ann": sub["lag_log_rv_ann"].astype(float),
            },
            index=sub.index,
        )
        fit = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 3})
        rows = []
        for name, expected in [("is_winter", "positive"), ("is_summer", "positive")]:
            rows.append(
                RegressionResult(
                    ticker=ticker,
                    n_obs=int(fit.nobs),
                    model=f"log_rv_ann ~ {name} + other season dummy + lag_log_rv_ann",
                    coefficient=float(fit.params[name]),
                    hac_t=float(fit.tvalues[name]),
                    hac_p=float(fit.pvalues[name]),
                    r_squared=float(fit.rsquared),
                    expected_direction=expected,
                    harvey_pass_abs_t_gt_3=bool(abs(float(fit.tvalues[name])) > HARVEY_T_ABS),
                )
            )
        results[ticker] = rows
    return results


def expiry_for_delivery_month(delivery_month: pd.Period) -> pd.Timestamp:
    first_day = delivery_month.to_timestamp()
    return (first_day - BDay(3)).normalize()


def front_month_expiry(date: pd.Timestamp) -> tuple[pd.Period, pd.Timestamp]:
    d = date.normalize()
    delivery_month = (d + MonthBegin(1)).to_period("M")
    expiry = expiry_for_delivery_month(delivery_month)
    if d > expiry:
        delivery_month = (d + MonthBegin(2)).to_period("M")
        expiry = expiry_for_delivery_month(delivery_month)
    return delivery_month, expiry


def business_days_to_expiry(date: pd.Timestamp, expiry: pd.Timestamp) -> int:
    return int(np.busday_count(date.date(), expiry.date()))


def build_samuelson_panel(rets: pd.DataFrame) -> pd.DataFrame:
    ng = rets["NG=F"].dropna().copy()
    records = []
    for date, ret in ng.items():
        delivery_month, expiry = front_month_expiry(pd.Timestamp(date))
        bdays = business_days_to_expiry(pd.Timestamp(date), expiry)
        if bdays < 0 or bdays > 35:
            continue
        records.append(
            {
                "date": pd.Timestamp(date),
                "delivery_month": str(delivery_month),
                "expiry": expiry,
                "bdays_to_expiry": bdays,
                "calendar_days_to_expiry": int((expiry - pd.Timestamp(date).normalize()).days),
                "ret": float(ret),
                "abs_ret": float(abs(ret)),
                "r2": float(ret * ret),
                "month": int(pd.Timestamp(date).month),
                "year": int(pd.Timestamp(date).year),
                "near_expiry_5bd": int(bdays <= 5),
                "far_expiry_15bd": int(bdays >= 15),
            }
        )
    panel = pd.DataFrame(records).sort_values("date")
    panel["log_abs_ret"] = np.log(panel["abs_ret"] + 1e-6)
    panel["lag_log_abs_ret"] = panel["log_abs_ret"].shift(1)
    # Explicit lag guard: daily persistence control uses t-1 absolute return.
    panel["bucket"] = pd.cut(
        panel["bdays_to_expiry"],
        bins=[-1, 5, 14, 35],
        labels=["near_0_5bd", "mid_6_14bd", "far_15plus_bd"],
    )
    panel.to_csv(SAMUELSON_PANEL_PATH, index=False)
    return panel


def fit_samuelson_regressions(panel: pd.DataFrame) -> list[RegressionResult]:
    sub = panel.dropna(subset=["log_abs_ret", "lag_log_abs_ret"]).copy()
    month_dummies = pd.get_dummies(sub["month"], prefix="m", drop_first=True, dtype=float)
    year_dummies = pd.get_dummies(sub["year"], prefix="y", drop_first=True, dtype=float)

    x_cont = pd.concat(
        [
            pd.DataFrame(
                {
                    "const": 1.0,
                    "bdays_to_expiry": sub["bdays_to_expiry"].astype(float),
                    "lag_log_abs_ret": sub["lag_log_abs_ret"].astype(float),
                },
                index=sub.index,
            ),
            month_dummies.set_index(sub.index),
            year_dummies.set_index(sub.index),
        ],
        axis=1,
    )
    fit_cont = sm.OLS(sub["log_abs_ret"], x_cont).fit(
        cov_type="HAC", cov_kwds={"maxlags": 5}
    )

    x_bucket = pd.concat(
        [
            pd.DataFrame(
                {
                    "const": 1.0,
                    "near_expiry_5bd": sub["near_expiry_5bd"].astype(float),
                    "lag_log_abs_ret": sub["lag_log_abs_ret"].astype(float),
                },
                index=sub.index,
            ),
            month_dummies.set_index(sub.index),
            year_dummies.set_index(sub.index),
        ],
        axis=1,
    )
    fit_bucket = sm.OLS(sub["log_abs_ret"], x_bucket).fit(
        cov_type="HAC", cov_kwds={"maxlags": 5}
    )

    return [
        RegressionResult(
            ticker="NG=F",
            n_obs=int(fit_cont.nobs),
            model="daily log_abs_ret ~ bdays_to_expiry + lag_log_abs_ret + month FE + year FE",
            coefficient=float(fit_cont.params["bdays_to_expiry"]),
            hac_t=float(fit_cont.tvalues["bdays_to_expiry"]),
            hac_p=float(fit_cont.pvalues["bdays_to_expiry"]),
            r_squared=float(fit_cont.rsquared),
            expected_direction="negative",
            harvey_pass_abs_t_gt_3=bool(abs(float(fit_cont.tvalues["bdays_to_expiry"])) > HARVEY_T_ABS),
        ),
        RegressionResult(
            ticker="NG=F",
            n_obs=int(fit_bucket.nobs),
            model="daily log_abs_ret ~ near_expiry_5bd + lag_log_abs_ret + month FE + year FE",
            coefficient=float(fit_bucket.params["near_expiry_5bd"]),
            hac_t=float(fit_bucket.tvalues["near_expiry_5bd"]),
            hac_p=float(fit_bucket.pvalues["near_expiry_5bd"]),
            r_squared=float(fit_bucket.rsquared),
            expected_direction="positive",
            harvey_pass_abs_t_gt_3=bool(abs(float(fit_bucket.tvalues["near_expiry_5bd"])) > HARVEY_T_ABS),
        ),
    ]


def bucket_summary(panel: pd.DataFrame) -> list[BucketResult]:
    out = []
    for bucket, g in panel.dropna(subset=["bucket"]).groupby("bucket", observed=True):
        out.append(
            BucketResult(
                bucket=str(bucket),
                n_obs=int(len(g)),
                rms_vol_ann=float(np.sqrt(np.mean(np.square(g["ret"]))) * np.sqrt(252)),
                mean_abs_return=float(g["abs_ret"].mean()),
                mean_log_abs_return=float(g["log_abs_ret"].mean()),
            )
        )
    return out


def bootstrap_near_far(panel: pd.DataFrame) -> dict:
    near = panel[panel["near_expiry_5bd"] == 1]["log_abs_ret"].dropna().to_numpy()
    far = panel[panel["far_expiry_15bd"] == 1]["log_abs_ret"].dropna().to_numpy()
    obs = float(np.mean(near) - np.mean(far))
    boot = np.empty(BOOT_REPS)
    for i in range(BOOT_REPS):
        near_b = RNG.choice(near, size=len(near), replace=True)
        far_b = RNG.choice(far, size=len(far), replace=True)
        boot[i] = np.mean(near_b) - np.mean(far_b)
    return {
        "n_near": int(len(near)),
        "n_far": int(len(far)),
        "mean_log_abs_near_minus_far": obs,
        "ci_95_low": float(np.quantile(boot, 0.025)),
        "ci_95_high": float(np.quantile(boot, 0.975)),
        "prob_gt_zero": float(np.mean(boot > 0)),
    }


def make_figures(monthly: pd.DataFrame, sam: pd.DataFrame) -> list[str]:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    paths = []

    fig, ax = plt.subplots(figsize=(10, 5))
    for ticker, color in [("NG=F", "#1f77b4"), ("UNG", "#d95f02")]:
        by_month = (
            monthly[monthly["ticker"] == ticker]
            .groupby("month")["rv_ann"]
            .mean()
            .reindex(range(1, 13))
        )
        ax.plot(
            range(1, 13),
            by_month.to_numpy(),
            marker="o",
            linewidth=2,
            color=color,
            label=ticker,
        )
    ax.set_xticks(range(1, 13), [MONTH_NAMES[i] for i in range(1, 13)])
    ax.set_ylabel("Annualized monthly realized volatility")
    ax.set_title("Natural gas realized volatility by calendar month")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = FIG_DIR / "k1504_monthly_seasonality.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(OUT_DIR)))

    fig, ax = plt.subplots(figsize=(10, 5))
    by_bday = sam.groupby("bdays_to_expiry").agg(
        rms_vol_ann=("ret", lambda x: np.sqrt(np.mean(np.square(x))) * np.sqrt(252)),
        n_obs=("ret", "size"),
    )
    by_bday = by_bday[by_bday["n_obs"] >= 20]
    ax.bar(by_bday.index, by_bday["rms_vol_ann"], color="#426a5a", alpha=0.85)
    ax.axvspan(-0.5, 5.5, color="#f2cc8f", alpha=0.3, label="near expiry <=5bd")
    ax.set_xlabel("Business days to approximate NG front-month expiry")
    ax.set_ylabel("Annualized RMS daily volatility")
    ax.set_title("NG=F volatility by business days to expiry")
    ax.grid(axis="y", alpha=0.25)
    ax.legend()
    fig.tight_layout()
    path = FIG_DIR / "k1504_samuelson_bdays_to_expiry.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths.append(str(path.relative_to(OUT_DIR)))

    return paths


def classify_verdict(
    seasonality: dict[str, AnovaResult],
    samuelson_regs: list[RegressionResult],
    near_far: dict,
) -> tuple[str, list[str]]:
    season_pass = all(
        r.permutation_p < 0.01 and r.peak_trough_ratio > 1.2
        for r in seasonality.values()
    )
    cont = samuelson_regs[0]
    bucket = samuelson_regs[1]
    sam_pass = (
        cont.coefficient < 0
        and abs(cont.hac_t) > HARVEY_T_ABS
        and bucket.coefficient > 0
        and abs(bucket.hac_t) > HARVEY_T_ABS
        and near_far["prob_gt_zero"] > 0.975
    )
    reasons = []
    reasons.append(
        f"seasonality_pass={season_pass}: both NG=F and UNG permutation p<0.01 "
        f"and peak/trough ratio>1.2"
    )
    reasons.append(
        f"samuelson_proxy_pass={sam_pass}: bdays coef={cont.coefficient:.4f} "
        f"t={cont.hac_t:.2f}, near bucket coef={bucket.coefficient:.4f} "
        f"t={bucket.hac_t:.2f}, bootstrap P(near>far)="
        f"{near_far['prob_gt_zero']:.3f}"
    )
    if season_pass and sam_pass:
        return "PASS", reasons
    if season_pass or sam_pass:
        return "CONDITIONAL_PASS", reasons
    return "NULL", reasons


def main() -> None:
    close_raw = load_close()
    close, data_info = clean_close(close_raw)
    returns = build_returns(close)
    monthly = build_monthly_panel(returns)
    seasonality = seasonality_tests(monthly)
    monthly_regs = fit_monthly_regressions(monthly)
    sam = build_samuelson_panel(returns)
    sam_regs = fit_samuelson_regressions(sam)
    buckets = bucket_summary(sam)
    near_far = bootstrap_near_far(sam)
    figures = make_figures(monthly, sam)
    verdict, verdict_reasons = classify_verdict(seasonality, sam_regs, near_far)

    result = {
        "experiment_id": "K1504",
        "title": "Natural gas seasonality and front-month Samuelson proxy",
        "created_at": datetime.now(UTC).isoformat(),
        "seed": SEED,
        "verdict": verdict,
        "verdict_reasons": verdict_reasons,
        "data": {
            **data_info,
            "tickers": TICKERS,
            "ngf_non_null": int(close["NG=F"].dropna().shape[0]),
            "ung_non_null": int(close["UNG"].dropna().shape[0]),
            "ngf_ung_overlap": int(close[TICKERS].dropna().shape[0]),
            "monthly_panel_rows": int(len(monthly)),
            "samuelson_panel_rows": int(len(sam)),
        },
        "methodology": {
            "seasonality": (
                "Monthly realized volatility from daily log returns; one-way ANOVA "
                "across calendar months plus 5,000-label permutation test."
            ),
            "monthly_regression": (
                "log monthly RV on winter and summer dummies with lagged log RV; "
                "HAC maxlags=3."
            ),
            "samuelson_proxy": (
                "NG=F continuous front-month proxy; expiry approximated as three "
                "business days before first day of delivery month, per CME rule. "
                "Daily log absolute return regressed on business days to expiry "
                "or near-expiry dummy, controlling for lagged log abs return, "
                "calendar-month FE, and year FE; HAC maxlags=5."
            ),
            "lookahead_controls": [
                "Monthly persistence control uses lag_log_rv_ann = t-1.",
                "Daily persistence control uses lag_log_abs_ret = t-1.",
                "No future returns are used to construct current month or daily predictors.",
                "Samuelson expiry proxy uses exchange calendar rule, not realized future volatility.",
            ],
            "limitations": [
                "NG=F is a Yahoo continuous front-month proxy, not a contract-level panel.",
                "Yahoo roll timing may differ from the CME active-contract convention.",
                "Expiry and business-day counts use a standard weekday calendar, not a full CME holiday calendar.",
                "Weekend-labelled futures rows are dropped to keep business-day expiry counts coherent.",
                "No options-implied vol or full term-structure curve is used.",
            ],
        },
        "literature_sources": [
            {
                "source": "Samuelson (1965), Proof that properly anticipated prices fluctuate randomly",
                "role": "Original maturity-effect hypothesis.",
            },
            {
                "source": "Mu (2007), Weather, Storage, and Natural Gas Price Dynamics",
                "role": "Documents natural gas volatility effects from weather, storage, and contract horizon.",
            },
            {
                "source": "CME Rulebook Chapter 220, Henry Hub Natural Gas Futures",
                "role": "Defines NG last trading day as three business days before delivery month.",
            },
            {
                "source": "CME Introduction to Natural Gas Seasonality",
                "role": "Describes storage/consumption seasonality and heating/cooling demand mechanism.",
            },
        ],
        "related_k": {
            "K1461": (
                "UNG month-of-year RV seasonality already found strong February-vs-September "
                "pattern; K1504 differentiates by adding NG=F and expiry-distance proxy."
            ),
            "inventory_seasonality_surprise_regime_conditiona": (
                "Low-inventory seasonal interaction was NULL for NG=F/UNG; K1504 does not "
                "use inventory regimes."
            ),
            "K1339": (
                "Commodity ETF momentum-regime switch event study; K1504 avoids calling "
                "ETF momentum a true futures-curve regime."
            ),
        },
        "seasonality_anova": {k: asdict(v) for k, v in seasonality.items()},
        "monthly_regressions": {
            k: [asdict(row) for row in rows] for k, rows in monthly_regs.items()
        },
        "samuelson_regressions": [asdict(row) for row in sam_regs],
        "samuelson_buckets": [asdict(row) for row in buckets],
        "near_far_bootstrap": near_far,
        "figures": figures,
        "artifacts": {
            "close_cache": str(CLOSE_CACHE.relative_to(OUT_DIR)),
            "monthly_panel": str(MONTHLY_PANEL_PATH.relative_to(OUT_DIR)),
            "samuelson_panel": str(SAMUELSON_PANEL_PATH.relative_to(OUT_DIR)),
        },
    }
    out_path = OUT_DIR / "k1504_results.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "results": str(out_path)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
