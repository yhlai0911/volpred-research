#!/usr/bin/env python3
"""K1539: news sentiment and corporate-bond ETF risk targets.

The task asks whether corporate-bond news sentiment may be too weak for bond
ETF returns but still useful for risk targets.  The long-sample signal here is
the FRBSF Daily News Sentiment Index; the corporate-credit-specific GDELT DOC
tone query is kept as a last-3-month diagnostic because the public DOC API
limits historical custom searches.

All predictive signals are lagged one trading day before matching to forward
targets.  No same-day signal is used for same-day or forward returns.
"""

from __future__ import annotations

import io
import json
import math
import sys
import time
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

from volpred.stats.model_evaluation import dm_test


ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
FIG = OUT / "figures"

SEED = 42
np.random.seed(SEED)

EXPERIMENT_ID = "K1539"
SLUG = "k1539_corporate_bond_news_sentiment_rv_only"

TICKERS = ["HYG", "LQD", "BKLN", "VCIT", "VCSH", "SPY", "^VIX"]
TARGET_ETFS = ["HYG", "LQD", "BKLN", "VCIT", "VCSH"]
START = "2007-01-01"
END = "2026-06-24"
FRBSF_XLSX_URL = (
    "https://www.frbsf.org/wp-content/uploads/"
    "news_sentiment_data.xlsx?20240826&2026-06-22"
)


@dataclass
class RegressionResult:
    target: str
    family: str
    nobs: int
    beta: float
    hac_t: float
    p_value: float
    effect_per_1sd: float
    effect_units: str
    expected_sign: str
    raw_gate: bool
    bonferroni_p: float | None = None
    bh_q: float | None = None
    gate_pass: bool = False


@dataclass
class OOSResult:
    target: str
    family: str
    nobs: int
    baseline_mse: float
    augmented_mse: float
    mse_improvement_pct: float
    dm_t: float
    dm_p: float
    gate_pass: bool


def excel_serial_to_date(value: float) -> pd.Timestamp:
    # Excel's 1900 date system includes the leap-year bug; pandas-compatible
    # conversion uses 1899-12-30 as day zero.
    return pd.Timestamp("1899-12-30") + pd.to_timedelta(float(value), unit="D")


def _xlsx_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    xml = zf.read("xl/sharedStrings.xml")
    root = ET.fromstring(xml)
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    values: list[str] = []
    for si in root.findall("x:si", ns):
        texts = [node.text or "" for node in si.findall(".//x:t", ns)]
        values.append("".join(texts))
    return values


def load_frbsf_sentiment() -> pd.DataFrame:
    response = requests.get(FRBSF_XLSX_URL, timeout=45)
    response.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(response.content))
    shared = _xlsx_shared_strings(zf)
    sheet = ET.fromstring(zf.read("xl/worksheets/sheet2.xml"))
    ns = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    rows: list[dict[str, Any]] = []
    for row in sheet.findall(".//x:sheetData/x:row", ns):
        parsed: dict[str, Any] = {}
        for cell in row.findall("x:c", ns):
            ref = cell.attrib.get("r", "")
            col = "".join(ch for ch in ref if ch.isalpha())
            v = cell.find("x:v", ns)
            if v is None or v.text is None:
                continue
            if cell.attrib.get("t") == "s":
                parsed[col] = shared[int(v.text)]
            else:
                parsed[col] = float(v.text)
        if parsed:
            rows.append(parsed)

    header = rows[0]
    date_col = header["A"]
    value_col = header["B"]
    out = pd.DataFrame(rows[1:])
    out = out.rename(columns={"A": date_col, "B": value_col})
    out["date"] = out[date_col].map(excel_serial_to_date)
    out["sentiment"] = pd.to_numeric(out[value_col], errors="coerce")
    out = out[["date", "sentiment"]].dropna().sort_values("date")
    out = out.drop_duplicates("date").set_index("date")
    return out


def fetch_gdelt_credit_tone() -> dict[str, Any]:
    query = (
        '("corporate bond" OR "high yield" OR "investment grade") '
        "(credit OR spread OR default OR downgrade)"
    )
    params = {
        "query": query,
        "mode": "timelinetone",
        "format": "json",
        "timespan": "3months",
        "timelinesmooth": "0",
    }
    url = "https://api.gdeltproject.org/api/v2/doc/doc?" + urlencode(params)
    for attempt in range(2):
        response = requests.get(url, timeout=45)
        if response.status_code == 429 and attempt == 0:
            time.sleep(6)
            continue
        if response.status_code != 200:
            return {
                "status": "unavailable",
                "http_status": response.status_code,
                "message": response.text[:200],
                "url": url,
            }
        try:
            payload = response.json()
        except json.JSONDecodeError as exc:
            return {
                "status": "unavailable",
                "http_status": response.status_code,
                "message": f"JSON parse failed: {exc}",
                "url": url,
            }
        rows = payload.get("timeline") or payload.get("data") or []
        return {
            "status": "ok",
            "http_status": response.status_code,
            "points": len(rows) if isinstance(rows, list) else None,
            "url": url,
        }
    return {"status": "unavailable", "message": "unexpected retry fallthrough", "url": url}


def load_yfinance_panel() -> pd.DataFrame:
    raw = yf.download(
        TICKERS,
        start=START,
        end=END,
        auto_adjust=True,
        progress=False,
        group_by="ticker",
        threads=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned an empty panel")

    frames: list[pd.DataFrame] = []
    for ticker in TICKERS:
        if (ticker, "Close") in raw.columns:
            sub = raw[ticker].copy()
        elif ticker in raw.columns.get_level_values(0):
            sub = raw.xs(ticker, axis=1, level=0).copy()
        else:
            raise RuntimeError(f"missing ticker in yfinance response: {ticker}")
        keep = sub[["Open", "High", "Low", "Close", "Volume"]].copy()
        keep.columns = [f"{ticker}_{c.lower()}" for c in keep.columns]
        frames.append(keep)
    panel = pd.concat(frames, axis=1).sort_index()
    panel.index = pd.to_datetime(panel.index).tz_localize(None)
    return panel


def add_return_targets(panel: pd.DataFrame, sentiment: pd.DataFrame) -> pd.DataFrame:
    df = panel.join(sentiment, how="left")
    df["sentiment"] = df["sentiment"].ffill()
    roll_mean = df["sentiment"].rolling(252, min_periods=126).mean()
    roll_std = df["sentiment"].rolling(252, min_periods=126).std()
    df["sentiment_z"] = (df["sentiment"] - roll_mean) / roll_std
    df["sentiment_stress_lag"] = (-df["sentiment_z"]).shift(1)
    df["sentiment_delta_lag"] = (-df["sentiment"].diff()).shift(1)

    for ticker in TICKERS:
        close = df[f"{ticker}_close"]
        ret = np.log(close).diff()
        df[f"{ticker}_ret"] = ret
        df[f"{ticker}_rv21_lag"] = np.sqrt(
            ret.pow(2).rolling(21, min_periods=15).sum() * 252 / 21
        ).shift(1)
        df[f"{ticker}_ret5_lag"] = ret.rolling(5, min_periods=5).sum().shift(1)

    for ticker in TARGET_ETFS:
        ret = df[f"{ticker}_ret"]
        df[f"{ticker}_fwd_ret5"] = sum(ret.shift(-i) for i in range(0, 5))
        df[f"{ticker}_fwd_rv5"] = np.sqrt(
            sum(ret.shift(-i).pow(2) for i in range(0, 5)) * 252 / 5
        )
        df[f"{ticker}_fwd_downsemi5"] = np.sqrt(
            sum(ret.shift(-i).clip(upper=0).pow(2) for i in range(0, 5)) * 252 / 5
        )

    rel = df["HYG_ret"] - df["LQD_ret"]
    fwd_cum = pd.concat(
        [sum(rel.shift(-j) for j in range(0, i + 1)) for i in range(5)], axis=1
    )
    df["HYG_LQD_fwd_spread_drawdown5"] = (-fwd_cum.min(axis=1)).clip(lower=0)
    df["HYG_LQD_rv21_lag"] = (df["HYG_rv21_lag"] + df["LQD_rv21_lag"]) / 2
    return df


def hac_regression(
    df: pd.DataFrame,
    target: str,
    controls: list[str],
    expected_sign: str,
    family: str,
    effect_units: str,
) -> RegressionResult:
    cols = [target, "sentiment_stress_lag", *controls]
    reg = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    y = reg[target]
    x = sm.add_constant(reg[["sentiment_stress_lag", *controls]], has_constant="add")
    model = sm.OLS(y, x).fit(cov_type="HAC", cov_kwds={"maxlags": 5})
    beta = float(model.params["sentiment_stress_lag"])
    tval = float(model.tvalues["sentiment_stress_lag"])
    pval = float(model.pvalues["sentiment_stress_lag"])
    signal_sd = float(reg["sentiment_stress_lag"].std())
    raw_gate = (tval >= 3.0) if expected_sign == "positive" else (tval <= -3.0)
    return RegressionResult(
        target=target,
        family=family,
        nobs=int(model.nobs),
        beta=beta,
        hac_t=tval,
        p_value=pval,
        effect_per_1sd=beta * signal_sd,
        effect_units=effect_units,
        expected_sign=expected_sign,
        raw_gate=bool(raw_gate),
    )


def add_multiple_testing(results: list[RegressionResult]) -> None:
    pvals = np.array([r.p_value for r in results], dtype=float)
    m = len(results)
    order = np.argsort(pvals)
    qvals = np.empty(m)
    prev = 1.0
    for rank_from_end, idx in enumerate(order[::-1], start=1):
        rank = m - rank_from_end + 1
        q = min(prev, pvals[idx] * m / rank)
        qvals[idx] = q
        prev = q
    for i, r in enumerate(results):
        r.bonferroni_p = float(min(1.0, pvals[i] * m))
        r.bh_q = float(min(1.0, qvals[i]))
        sign_ok = r.hac_t >= 3.0 if r.expected_sign == "positive" else r.hac_t <= -3.0
        r.gate_pass = bool(sign_ok and r.bonferroni_p < 0.05)


def expanding_oos(
    df: pd.DataFrame,
    target: str,
    controls: list[str],
    family: str,
    min_train: int = 756,
    refit_step: int = 21,
) -> OOSResult:
    cols = [target, "sentiment_stress_lag", *controls]
    data = df[cols].replace([np.inf, -np.inf], np.nan).dropna().copy()
    y = data[target].to_numpy(dtype=float)
    xb = np.column_stack([np.ones(len(data)), data[controls].to_numpy(dtype=float)])
    xa = np.column_stack(
        [
            np.ones(len(data)),
            data[["sentiment_stress_lag", *controls]].to_numpy(dtype=float),
        ]
    )

    base_preds: list[float] = []
    aug_preds: list[float] = []
    actuals: list[float] = []
    beta_b: np.ndarray | None = None
    beta_a: np.ndarray | None = None
    for i in range(min_train, len(data)):
        if beta_b is None or (i - min_train) % refit_step == 0:
            beta_b = np.linalg.lstsq(xb[:i], y[:i], rcond=None)[0]
            beta_a = np.linalg.lstsq(xa[:i], y[:i], rcond=None)[0]
        assert beta_b is not None and beta_a is not None
        base_preds.append(float(xb[i] @ beta_b))
        aug_preds.append(float(xa[i] @ beta_a))
        actuals.append(float(y[i]))

    actual = np.array(actuals)
    base = np.array(base_preds)
    aug = np.array(aug_preds)
    base_loss = (actual - base) ** 2
    aug_loss = (actual - aug) ** 2
    baseline_mse = float(np.mean(base_loss))
    augmented_mse = float(np.mean(aug_loss))
    improvement = 100.0 * (baseline_mse - augmented_mse) / baseline_mse
    dm_t, dm_p = dm_test(aug_loss, base_loss, h=5)
    return OOSResult(
        target=target,
        family=family,
        nobs=len(actual),
        baseline_mse=baseline_mse,
        augmented_mse=augmented_mse,
        mse_improvement_pct=float(improvement),
        dm_t=float(dm_t),
        dm_p=float(dm_p),
        gate_pass=bool(dm_t <= -3.0 and improvement > 0),
    )


def make_figures(panel: pd.DataFrame, regs: list[RegressionResult], oos: list[OOSResult]) -> None:
    FIG.mkdir(exist_ok=True)
    fig, ax = plt.subplots(figsize=(11, 4.8))
    panel[["sentiment_stress_lag"]].dropna().rolling(21).mean().plot(ax=ax, legend=False)
    ax.set_title("K1539: FRBSF news-sentiment stress signal (21d average, lagged)")
    ax.set_ylabel("higher = more negative news sentiment")
    ax.grid(alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "k1539_sentiment_stress.png", dpi=160)
    plt.close(fig)

    risk_regs = [r for r in regs if r.family in {"rv5", "downsemi5", "spread_drawdown5"}]
    labels = [r.target.replace("_fwd_", "\n") for r in risk_regs]
    tvals = [r.hac_t for r in risk_regs]
    colors = ["#2E6F9E" if t >= 0 else "#B45F5F" for t in tvals]
    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.bar(range(len(labels)), tvals, color=colors)
    ax.axhline(3.0, color="#333333", linestyle="--", linewidth=1)
    ax.axhline(-3.0, color="#333333", linestyle="--", linewidth=1)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("HAC t-stat on lagged sentiment stress")
    ax.set_title("K1539: risk-target regressions do not clear Harvey |t| >= 3")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "k1539_risk_target_hac_tstats.png", dpi=160)
    plt.close(fig)

    oos_risk = [r for r in oos if r.family != "return5"]
    labels = [r.target.replace("_fwd_", "\n") for r in oos_risk]
    vals = [r.mse_improvement_pct for r in oos_risk]
    colors = ["#2F7D4F" if v > 0 else "#B45F5F" for v in vals]
    fig, ax = plt.subplots(figsize=(12, 5.8))
    ax.bar(range(len(labels)), vals, color=colors)
    ax.axhline(0, color="#333333", linewidth=1)
    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_ylabel("OOS MSE improvement vs controls-only (%)")
    ax.set_title("K1539: OOS risk-target improvement is mixed")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(FIG / "k1539_oos_mse_improvement.png", dpi=160)
    plt.close(fig)


def summarize_verdict(regs: list[RegressionResult], oos: list[OOSResult]) -> str:
    return_pass = any(r.gate_pass for r in regs if r.family == "return5")
    risk_pass = any(r.gate_pass for r in regs if r.family != "return5")
    oos_pass = any(r.gate_pass for r in oos if r.family != "return5")
    if risk_pass and oos_pass and not return_pass:
        return "RISK_ONLY_PASS"
    if risk_pass or oos_pass:
        return "WEAK_RISK_ONLY_DIAGNOSTIC"
    return "NULL_NEWS_SENTIMENT_RISK_TARGET"


def main() -> None:
    sentiment = load_frbsf_sentiment()
    panel = load_yfinance_panel()
    gdelt_status = fetch_gdelt_credit_tone()
    df = add_return_targets(panel, sentiment)

    controls_by_asset = {
        ticker: [f"{ticker}_rv21_lag", f"{ticker}_ret5_lag", "SPY_rv21_lag", "^VIX_rv21_lag"]
        for ticker in TARGET_ETFS
    }
    # Replace the VIX rolling-vol control with lagged log VIX level, which is
    # the more standard market-stress state variable.
    df["log_vix_lag"] = np.log(df["^VIX_close"]).shift(1)
    for ticker in TARGET_ETFS:
        controls_by_asset[ticker] = [
            f"{ticker}_rv21_lag",
            f"{ticker}_ret5_lag",
            "SPY_rv21_lag",
            "log_vix_lag",
        ]
    spread_controls = ["HYG_LQD_rv21_lag", "HYG_ret5_lag", "LQD_ret5_lag", "SPY_rv21_lag", "log_vix_lag"]

    regs: list[RegressionResult] = []
    for ticker in TARGET_ETFS:
        regs.append(
            hac_regression(
                df,
                f"{ticker}_fwd_ret5",
                controls_by_asset[ticker],
                expected_sign="negative",
                family="return5",
                effect_units="5d log return",
            )
        )
        regs.append(
            hac_regression(
                df,
                f"{ticker}_fwd_rv5",
                controls_by_asset[ticker],
                expected_sign="positive",
                family="rv5",
                effect_units="annualized vol",
            )
        )
        regs.append(
            hac_regression(
                df,
                f"{ticker}_fwd_downsemi5",
                controls_by_asset[ticker],
                expected_sign="positive",
                family="downsemi5",
                effect_units="annualized downside semivol",
            )
        )
    regs.append(
        hac_regression(
            df,
            "HYG_LQD_fwd_spread_drawdown5",
            spread_controls,
            expected_sign="positive",
            family="spread_drawdown5",
            effect_units="5d HYG-minus-LQD drawdown",
        )
    )
    add_multiple_testing(regs)

    oos: list[OOSResult] = []
    for ticker in TARGET_ETFS:
        for family, target in [
            ("return5", f"{ticker}_fwd_ret5"),
            ("rv5", f"{ticker}_fwd_rv5"),
            ("downsemi5", f"{ticker}_fwd_downsemi5"),
        ]:
            oos.append(expanding_oos(df, target, controls_by_asset[ticker], family))
    oos.append(
        expanding_oos(
            df,
            "HYG_LQD_fwd_spread_drawdown5",
            spread_controls,
            "spread_drawdown5",
        )
    )

    make_figures(df, regs, oos)
    panel_path = OUT / f"{SLUG}_daily_panel.csv"
    keep_cols = ["sentiment", "sentiment_z", "sentiment_stress_lag", "sentiment_delta_lag"]
    keep_cols += [f"{ticker}_ret" for ticker in TARGET_ETFS + ["SPY"]]
    keep_cols += [f"{ticker}_fwd_ret5" for ticker in TARGET_ETFS]
    keep_cols += [f"{ticker}_fwd_rv5" for ticker in TARGET_ETFS]
    keep_cols += [f"{ticker}_fwd_downsemi5" for ticker in TARGET_ETFS]
    keep_cols += ["HYG_LQD_fwd_spread_drawdown5", "log_vix_lag"]
    df[keep_cols].to_csv(panel_path, index_label="date")

    best_return = sorted(
        [r for r in regs if r.family == "return5"],
        key=lambda r: abs(r.effect_per_1sd),
        reverse=True,
    )[0]
    best_risk = sorted(
        [r for r in regs if r.family != "return5"],
        key=lambda r: abs(r.hac_t),
        reverse=True,
    )[0]
    best_oos = sorted(
        [r for r in oos if r.family != "return5"],
        key=lambda r: r.mse_improvement_pct,
        reverse=True,
    )[0]

    results = {
        "experiment_id": EXPERIMENT_ID,
        "slug": SLUG,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "random_seed": SEED,
        "verdict": summarize_verdict(regs, oos),
        "data": {
            "frbsf_sentiment_url": FRBSF_XLSX_URL,
            "frbsf_start": str(sentiment.index.min().date()),
            "frbsf_end": str(sentiment.index.max().date()),
            "yfinance_tickers": TICKERS,
            "requested_start": START,
            "requested_end": END,
            "effective_panel_start": str(df.dropna(subset=["sentiment_stress_lag"]).index.min().date()),
            "effective_panel_end": str(df.dropna(subset=["sentiment_stress_lag"]).index.max().date()),
            "daily_panel_rows": int(len(df)),
            "gdelt_credit_tone_last3m": gdelt_status,
        },
        "lookahead_policy": (
            "sentiment_stress_lag = (-rolling_zscore(FRBSF sentiment)).shift(1); "
            "all targets are forward 5-trading-day outcomes beginning at date t."
        ),
        "method": {
            "primary_signal": "negative FRBSF Daily News Sentiment rolling z-score, lagged one trading day",
            "controls": "own lagged RV21, own lagged 5d return, SPY lagged RV21, lagged log VIX",
            "return_target": "forward 5-trading-day log return",
            "risk_targets": [
                "forward 5-trading-day annualized realized volatility",
                "forward 5-trading-day annualized downside semivolatility",
                "forward 5-trading-day HYG-minus-LQD spread-proxy drawdown",
            ],
            "formal_gate": "Harvey-style |HAC t| >= 3 plus Bonferroni p < 0.05 for in-sample; OOS DM t <= -3 and MSE improvement > 0 for forecasts",
        },
        "regressions": [asdict(r) for r in regs],
        "oos": [asdict(r) for r in oos],
        "summary": {
            "best_return_effect": asdict(best_return),
            "best_risk_hac": asdict(best_risk),
            "best_risk_oos": asdict(best_oos),
            "interpretation": (
                "FRBSF news sentiment stress has small return effects and does not "
                "clear the risk-only predictive gates for corporate-bond ETF RV, "
                "downside semivariance, or HYG-LQD drawdown under this free-data proxy."
            ),
        },
        "outputs": {
            "daily_panel": str(panel_path.relative_to(ROOT)),
            "figures": [
                str((FIG / "k1539_sentiment_stress.png").relative_to(ROOT)),
                str((FIG / "k1539_risk_target_hac_tstats.png").relative_to(ROOT)),
                str((FIG / "k1539_oos_mse_improvement.png").relative_to(ROOT)),
            ],
        },
    }

    out_path = OUT / f"{SLUG}_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "verdict": results["verdict"], "results": str(out_path)}, indent=2))


if __name__ == "__main__":
    main()
