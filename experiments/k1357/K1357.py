"""K1357: Low-frequency RLMM spread-asymmetry fingerprint.

Question
--------
Do daily OHLCV spread proxies show one-sided liquidity deterioration after
otherwise symmetric VIX/volume cost shocks, and does that low-frequency
asymmetry predict next-week realized variance?

Research-honesty constraints
----------------------------
* This is not TAQ, NBBO, or actual bid/ask quote data.
* Corwin-Schultz from daily high/low is a low-frequency effective-spread proxy.
* Event response is forward by design: shock at t, spread response at t+1.
* Forecasting features are explicitly lagged: signals at row t use t-1 data.
* Pooled forecast DM is date-clustered by averaging same-date asset losses
  before running the HAC DM test.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf

from volpred.stats.model_evaluation import dm_test, qlike_pointwise


SEED = 42
EXP_ID = "K1357"
EXP_DIR = Path(__file__).resolve().parent
DATA_DIR = EXP_DIR / "data"
RESULTS_PATH = EXP_DIR / "K1357_results.json"
FIG_PATH = EXP_DIR / "K1357_spread_asymmetry.png"

START = "2012-01-01"
END = datetime.now(timezone.utc).strftime("%Y-%m-%d")
OOS_START = pd.Timestamp("2020-01-01")
INIT_TRAIN_MIN = 1000
REFIT_EVERY = 252
N_BOOT = 2000
EPS = 1e-12

ASSETS = ["SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA"]
TICKERS = ASSETS + ["^VIX"]


@dataclass(frozen=True)
class ModelSpec:
    name: str
    features: list[str]


MODELS = [
    ModelSpec(
        "HAR_VIX_VOL",
        ["log_rv_1_lag1", "log_rv_5_lag1", "log_rv_22_lag1", "vix_z_lag1", "volume_z_lag1"],
    ),
    ModelSpec(
        "HAR_VIX_VOL_SPREAD_ASYM",
        [
            "log_rv_1_lag1",
            "log_rv_5_lag1",
            "log_rv_22_lag1",
            "vix_z_lag1",
            "volume_z_lag1",
            "spread_z_lag1",
            "asym_spread_cost_lag1",
        ],
    ),
]


def save_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def field(raw: pd.DataFrame, name: str, tickers: list[str]) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        out = raw[name]
    else:
        out = raw[[name]]
    cols = [ticker for ticker in tickers if ticker in out.columns]
    return out[cols].astype(float)


def load_ohlcv() -> dict[str, pd.DataFrame]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cache = DATA_DIR / "yfinance_ohlcv.csv"
    if cache.exists():
        raw = pd.read_csv(cache, header=[0, 1], index_col=0, parse_dates=True)
        raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
    else:
        raw = yf.download(
            TICKERS,
            start=START,
            end=END,
            auto_adjust=False,
            progress=False,
            threads=True,
            group_by="column",
        )
        if raw.empty:
            raise RuntimeError("yfinance returned no rows")
        raw.index = pd.to_datetime(raw.index).tz_localize(None).normalize()
        raw.to_csv(cache)
    return {
        "open": field(raw, "Open", TICKERS),
        "high": field(raw, "High", TICKERS),
        "low": field(raw, "Low", TICKERS),
        "close": field(raw, "Close", TICKERS),
        "adj_close": field(raw, "Adj Close", TICKERS),
        "volume": field(raw, "Volume", TICKERS),
    }


def rolling_z_past(x: pd.Series, window: int = 252, min_periods: int = 60) -> pd.Series:
    past = x.shift(1)
    mean = past.rolling(window, min_periods=min_periods).mean()
    std = past.rolling(window, min_periods=min_periods).std(ddof=0)
    return ((x - mean) / std.replace(0.0, np.nan)).replace([np.inf, -np.inf], np.nan)


def corwin_schultz_spread(high: pd.Series, low: pd.Series) -> pd.Series:
    hl = np.log(high / low).replace([np.inf, -np.inf], np.nan)
    beta = hl.pow(2) + hl.shift(1).pow(2)
    two_high = pd.concat([high, high.shift(1)], axis=1).max(axis=1)
    two_low = pd.concat([low, low.shift(1)], axis=1).min(axis=1)
    gamma = np.log(two_high / two_low).replace([np.inf, -np.inf], np.nan).pow(2)
    k = 3.0 - 2.0 * np.sqrt(2.0)
    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / k - np.sqrt(gamma / k)
    spread = 2.0 * (np.exp(alpha.clip(lower=0.0, upper=5.0)) - 1.0) / (
        1.0 + np.exp(alpha.clip(lower=0.0, upper=5.0))
    )
    return spread.replace([np.inf, -np.inf], np.nan).clip(lower=0.0, upper=0.25)


def garman_klass_var(open_: pd.Series, high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    valid = (open_ > 0) & (high > 0) & (low > 0) & (close > 0)
    out = pd.Series(np.nan, index=open_.index, dtype=float)
    out.loc[valid] = (
        0.5 * np.log(high.loc[valid] / low.loc[valid]) ** 2
        - (2.0 * math.log(2.0) - 1.0) * np.log(close.loc[valid] / open_.loc[valid]) ** 2
    )
    return out.clip(lower=1e-10)


def build_panel() -> pd.DataFrame:
    data = load_ohlcv()
    vix = data["close"]["^VIX"].dropna()
    spy_adj = data["adj_close"]["SPY"]
    spy_ret = np.log(spy_adj / spy_adj.shift(1)).replace([np.inf, -np.inf], np.nan)
    vix_ret = np.log(vix / vix.shift(1)).replace([np.inf, -np.inf], np.nan)
    vix_z = rolling_z_past(vix)
    vix_abs_ret_z = rolling_z_past(vix_ret).abs()
    market_ret_z = rolling_z_past(spy_ret)

    rows = []
    for asset in ASSETS:
        if asset not in data["adj_close"]:
            continue
        open_ = data["open"][asset]
        high = data["high"][asset]
        low = data["low"][asset]
        close = data["close"][asset]
        adj = data["adj_close"][asset]
        volume = data["volume"][asset]

        ret = np.log(adj / adj.shift(1)).replace([np.inf, -np.inf], np.nan)
        rv = ret.pow(2).clip(lower=1e-10)
        gk_var = garman_klass_var(open_, high, low, close)
        dollar_volume = (close * volume).replace([np.inf, -np.inf], np.nan)
        volume_z = rolling_z_past(np.log(dollar_volume.replace(0.0, np.nan)))

        cs = corwin_schultz_spread(high, low)
        spread_log = np.log1p(100.0 * cs.clip(lower=0.0))
        spread_z = rolling_z_past(spread_log)
        spread_chg_fwd1 = spread_log.shift(-1) - spread_log
        spread_chg_fwd3 = spread_log.shift(-1).rolling(3).mean().shift(-2) - spread_log

        cost_score = 0.5 * vix_abs_ret_z.reindex(adj.index) + 0.5 * volume_z.clip(lower=0.0)
        high_cost = cost_score >= 1.0
        neg_market = spy_ret.reindex(adj.index) < 0.0
        asym_spread_cost = spread_z * cost_score * neg_market.astype(float)

        fwd5_rv = sum(rv.shift(-i) for i in range(1, 6)).clip(lower=1e-10)
        frame = pd.DataFrame(
            {
                "asset": asset,
                "ret": ret,
                "rv": rv,
                "gk_var": gk_var,
                "target_rv5": fwd5_rv,
                "target_log_rv5": np.log(fwd5_rv),
                "spread_proxy": cs,
                "spread_log": spread_log,
                "spread_z": spread_z,
                "spread_chg_fwd1": spread_chg_fwd1,
                "spread_chg_fwd3": spread_chg_fwd3,
                "vix": vix.reindex(adj.index),
                "vix_z": vix_z.reindex(adj.index),
                "vix_abs_ret_z": vix_abs_ret_z.reindex(adj.index),
                "market_ret": spy_ret.reindex(adj.index),
                "market_ret_z": market_ret_z.reindex(adj.index),
                "volume_z": volume_z,
                "cost_score": cost_score,
                "high_cost_shock": high_cost.astype(float),
                "neg_market": neg_market.astype(float),
                "asym_spread_cost": asym_spread_cost,
            },
            index=adj.index,
        )
        frame["log_rv_1_lag1"] = np.log(rv).shift(1)
        frame["log_rv_5_lag1"] = np.log(rv.rolling(5).mean().clip(lower=1e-10)).shift(1)
        frame["log_rv_22_lag1"] = np.log(rv.rolling(22).mean().clip(lower=1e-10)).shift(1)
        frame["vix_z_lag1"] = frame["vix_z"].shift(1)
        frame["volume_z_lag1"] = frame["volume_z"].shift(1)
        frame["spread_z_lag1"] = frame["spread_z"].shift(1)
        frame["asym_spread_cost_lag1"] = frame["asym_spread_cost"].shift(1)
        rows.append(frame.reset_index(names="date"))

    panel = pd.concat(rows, ignore_index=True).replace([np.inf, -np.inf], np.nan)
    panel.to_csv(DATA_DIR / "model_panel.csv", index=False)
    return panel


def fit_ols(train: pd.DataFrame, features: list[str]) -> np.ndarray:
    x = train[features].to_numpy(dtype=float)
    y = train["target_log_rv5"].to_numpy(dtype=float)
    x = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    return beta


def expanding_predictions(asset_df: pd.DataFrame, spec: ModelSpec) -> pd.Series:
    df = asset_df.sort_values("date").reset_index(drop=True)
    preds = pd.Series(np.nan, index=df.index, dtype=float)
    oos_idx = np.flatnonzero(df["date"].to_numpy() >= np.datetime64(OOS_START))
    if len(oos_idx) == 0:
        preds.index = df["date"]
        return preds
    first_oos_idx = int(oos_idx[0])
    beta = None
    last_fit = -10**9
    for i in range(first_oos_idx, len(df)):
        if i < INIT_TRAIN_MIN:
            continue
        if beta is None or i - last_fit >= REFIT_EVERY:
            train = df.iloc[:i].dropna(subset=spec.features + ["target_log_rv5"])
            if len(train) < INIT_TRAIN_MIN:
                continue
            beta = fit_ols(train, spec.features)
            last_fit = i
        row = df.iloc[i]
        if row[spec.features].isna().any() or pd.isna(row["target_log_rv5"]):
            continue
        x = np.array([1.0] + [float(row[col]) for col in spec.features])
        preds.iloc[i] = float(x @ beta)
    preds.index = df["date"]
    return preds


def evaluate_asset(asset_df: pd.DataFrame) -> dict:
    asset = str(asset_df["asset"].iloc[0])
    df = asset_df.sort_values("date").reset_index(drop=True)
    pred = {spec.name: expanding_predictions(df, spec) for spec in MODELS}
    pred_df = pd.DataFrame(pred)
    actual = df.set_index("date")[["target_rv5", "target_log_rv5"]].join(pred_df)
    actual = actual.dropna(subset=["target_rv5", "target_log_rv5", "HAR_VIX_VOL", "HAR_VIX_VOL_SPREAD_ASYM"])

    metrics = {}
    losses = {}
    for spec in MODELS:
        valid = actual.dropna(subset=[spec.name])
        pred_var = np.exp(valid[spec.name].to_numpy(dtype=float)).clip(1e-10, 10.0)
        obs_var = valid["target_rv5"].to_numpy(dtype=float).clip(1e-10, 10.0)
        qloss = qlike_pointwise(obs_var, pred_var)
        mse_log = (valid["target_log_rv5"].to_numpy(dtype=float) - valid[spec.name].to_numpy(dtype=float)) ** 2
        metrics[spec.name] = {
            "n_oos": int(len(valid)),
            "qlike": float(np.mean(qloss)),
            "mse_log": float(np.mean(mse_log)),
        }
        losses[spec.name] = pd.DataFrame({"date": valid.index, "qlike": qloss, "mse_log": mse_log})

    common = losses["HAR_VIX_VOL_SPREAD_ASYM"].merge(
        losses["HAR_VIX_VOL"], on="date", suffixes=("_challenger", "_base")
    )
    q_t, q_p = dm_test(common["qlike_challenger"].to_numpy(), common["qlike_base"].to_numpy(), h=5)
    m_t, m_p = dm_test(common["mse_log_challenger"].to_numpy(), common["mse_log_base"].to_numpy(), h=5)
    base_q = metrics["HAR_VIX_VOL"]["qlike"]
    ch_q = metrics["HAR_VIX_VOL_SPREAD_ASYM"]["qlike"]
    return {
        "asset": asset,
        "metrics": metrics,
        "comparison": {
            "qlike_improvement_pct": float((base_q - ch_q) / abs(base_q) * 100.0),
            "mse_log_improvement_pct": float(
                (metrics["HAR_VIX_VOL"]["mse_log"] - metrics["HAR_VIX_VOL_SPREAD_ASYM"]["mse_log"])
                / abs(metrics["HAR_VIX_VOL"]["mse_log"])
                * 100.0
            ),
            "dm_qlike_t": float(q_t),
            "dm_qlike_p": float(q_p),
            "dm_mse_t": float(m_t),
            "dm_mse_p": float(m_p),
        },
        "losses": losses,
    }


def pooled_dm(asset_results: list[dict]) -> dict:
    pieces = []
    for res in asset_results:
        ch = res["losses"]["HAR_VIX_VOL_SPREAD_ASYM"][["date", "qlike"]].rename(columns={"qlike": "ch"})
        ba = res["losses"]["HAR_VIX_VOL"][["date", "qlike"]].rename(columns={"qlike": "base"})
        merged = ch.merge(ba, on="date")
        merged["asset"] = res["asset"]
        merged["diff"] = merged["ch"] - merged["base"]
        pieces.append(merged)
    panel = pd.concat(pieces, ignore_index=True)
    by_date = panel.groupby("date")["diff"].mean().dropna()
    t_stat, p_val = dm_test(by_date.to_numpy(), np.zeros(len(by_date)), h=5)
    return {
        "n_dates": int(len(by_date)),
        "mean_loss_diff": float(by_date.mean()),
        "dm_t": float(t_stat),
        "dm_p": float(p_val),
        "method": "date-clustered cross-asset mean QLIKE loss differential, h=5",
    }


def bootstrap_diff(neg: np.ndarray, pos: np.ndarray) -> dict:
    rng = np.random.default_rng(SEED)
    neg = neg[np.isfinite(neg)]
    pos = pos[np.isfinite(pos)]
    if len(neg) < 20 or len(pos) < 20:
        return {"point": None, "ci_lo": None, "ci_hi": None, "n_neg": int(len(neg)), "n_pos": int(len(pos))}
    diffs = np.empty(N_BOOT)
    for i in range(N_BOOT):
        ns = rng.choice(neg, size=len(neg), replace=True)
        ps = rng.choice(pos, size=len(pos), replace=True)
        diffs[i] = np.mean(ns) - np.mean(ps)
    return {
        "point": float(np.mean(neg) - np.mean(pos)),
        "ci_lo": float(np.percentile(diffs, 2.5)),
        "ci_hi": float(np.percentile(diffs, 97.5)),
        "n_neg": int(len(neg)),
        "n_pos": int(len(pos)),
    }


def event_asymmetry(panel: pd.DataFrame) -> dict:
    events = panel[(panel["high_cost_shock"] == 1.0) & panel["spread_chg_fwd1"].notna()].copy()
    date_level = (
        events.groupby("date")
        .agg(
            mean_spread_chg_fwd1=("spread_chg_fwd1", "mean"),
            mean_spread_chg_fwd3=("spread_chg_fwd3", "mean"),
            neg_market=("neg_market", "first"),
            mean_cost_score=("cost_score", "mean"),
            n_assets=("asset", "nunique"),
        )
        .reset_index()
    )
    neg = date_level.loc[date_level["neg_market"] == 1.0, "mean_spread_chg_fwd1"].to_numpy(dtype=float)
    pos = date_level.loc[date_level["neg_market"] == 0.0, "mean_spread_chg_fwd1"].to_numpy(dtype=float)
    pooled = bootstrap_diff(neg, pos)

    per_asset = []
    for asset, g in events.groupby("asset"):
        neg_a = g.loc[g["neg_market"] == 1.0, "spread_chg_fwd1"].to_numpy(dtype=float)
        pos_a = g.loc[g["neg_market"] == 0.0, "spread_chg_fwd1"].to_numpy(dtype=float)
        stat = bootstrap_diff(neg_a, pos_a)
        stat["asset"] = asset
        per_asset.append(stat)
    return {
        "definition": "high_cost_shock = 0.5*abs(VIX return z) + 0.5*positive asset dollar-volume z >= 1.0; response is t+1 log(1+100*CS spread) change",
        "pooled_by_date": pooled,
        "per_asset": per_asset,
        "n_event_asset_days": int(len(events)),
        "n_event_dates": int(len(date_level)),
    }


def verdict(results: dict) -> dict:
    pooled = results["forecast"]["pooled"]
    positive_assets = sum(1 for row in results["forecast"]["per_asset"] if row["comparison"]["qlike_improvement_pct"] > 0)
    event_ci_lo = results["event_asymmetry"]["pooled_by_date"]["ci_lo"]
    event_pass = event_ci_lo is not None and event_ci_lo > 0
    forecast_pass = pooled["dm_t"] < -3.0 and positive_assets >= 7
    if event_pass and forecast_pass:
        label = "CONDITIONAL_PASS_PROXY"
        summary = "low-frequency spread asymmetry appears after negative cost shocks and improves OOS RV forecasts"
    elif event_pass:
        label = "EVENT_ONLY_WEAK"
        summary = "spread proxy widens asymmetrically after negative cost shocks, but OOS RV forecast gate fails"
    elif pooled["dm_t"] < 0 and pooled["dm_p"] < 0.10 and positive_assets >= 7:
        label = "MIXED_WEAK"
        summary = "forecast direction is favorable but below Harvey-strength gate and event asymmetry is not robust"
    else:
        label = "NULL"
        summary = "daily OHLCV spread proxy does not show a robust RLMM-style asymmetric liquidity fingerprint"
    return {
        "verdict": label,
        "summary": summary,
        "event_pass": bool(event_pass),
        "forecast_pass": bool(forecast_pass),
        "positive_asset_count": int(positive_assets),
        "asset_count": int(len(results["forecast"]["per_asset"])),
        "claim_ceiling": "free daily OHLCV proxy only; not quote-level bid/ask, not direct RL market-maker behavior",
    }


def make_figure(results: dict) -> None:
    per_asset = results["forecast"]["per_asset"]
    labels = [row["asset"] for row in per_asset]
    improvements = [row["comparison"]["qlike_improvement_pct"] for row in per_asset]
    event_rows = results["event_asymmetry"]["per_asset"]
    event_map = {row["asset"]: row["point"] for row in event_rows}
    event_points = [event_map.get(asset, np.nan) for asset in labels]

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    ax = axes[0]
    colors = ["#2a9d8f" if v > 0 else "#d1495b" for v in event_points]
    ax.bar(labels, event_points, color=colors)
    ax.axhline(0, color="#333333", lw=0.8)
    ax.set_title("Event response: negative-market minus positive-market cost-shock t+1 spread change")
    ax.set_ylabel("Delta log spread proxy")
    ax.tick_params(axis="x", labelrotation=30)

    ax = axes[1]
    colors = ["#2a9d8f" if v > 0 else "#d1495b" for v in improvements]
    ax.bar(labels, improvements, color=colors)
    ax.axhline(0, color="#333333", lw=0.8)
    ax.set_title("OOS QLIKE improvement: HAR+VIX+volume+spread-asymmetry vs HAR+VIX+volume")
    ax.set_ylabel("Improvement (%)")
    ax.tick_params(axis="x", labelrotation=30)
    fig.savefig(FIG_PATH, dpi=140)
    plt.close(fig)


def main() -> dict:
    np.random.seed(SEED)
    panel = build_panel()
    usable = panel.dropna(
        subset=[
            "target_rv5",
            "target_log_rv5",
            "log_rv_1_lag1",
            "log_rv_5_lag1",
            "log_rv_22_lag1",
            "vix_z_lag1",
            "volume_z_lag1",
            "spread_z_lag1",
            "asym_spread_cost_lag1",
        ]
    )
    asset_results_raw = []
    for _, asset_df in usable.groupby("asset"):
        if len(asset_df) < INIT_TRAIN_MIN + 252:
            continue
        asset_results_raw.append(evaluate_asset(asset_df.copy()))

    per_asset = [
        {
            "asset": res["asset"],
            "metrics": res["metrics"],
            "comparison": res["comparison"],
        }
        for res in asset_results_raw
    ]
    results = {
        "experiment_id": EXP_ID,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": "yfinance daily OHLCV auto_adjust=False",
            "start": START,
            "end_requested": END,
            "oos_start": OOS_START.strftime("%Y-%m-%d"),
            "assets": ASSETS,
            "n_panel_rows": int(len(panel)),
            "n_usable_rows": int(len(usable)),
        },
        "lookahead_policy": {
            "event_response": "cost shock and market sign measured at t; spread response is t+1 and forward by design",
            "forecast_target": "row t target is sum of close-to-close RV over t+1..t+5",
            "forecast_signals": "all HAR/VIX/volume/spread/asymmetry predictors use explicit .shift(1)",
            "pooled_dm": "same-date cross-asset QLIKE loss differentials are averaged before DM; h=5 for overlapping target",
        },
        "proxy_design": {
            "spread_proxy": "Corwin-Schultz daily high-low effective-spread estimator, transformed as log1p(100*spread)",
            "cost_shock": "0.5*abs(VIX return z) + 0.5*positive asset dollar-volume z >= 1.0",
            "asymmetry_signal": "spread_z * cost_score * 1[SPY return < 0], then shifted one day for forecasts",
        },
        "event_asymmetry": event_asymmetry(panel),
        "forecast": {
            "baseline": "HAR_VIX_VOL",
            "challenger": "HAR_VIX_VOL_SPREAD_ASYM",
            "per_asset": per_asset,
            "pooled": pooled_dm(asset_results_raw),
        },
    }
    results["verdict"] = verdict(results)
    make_figure(results)
    save_json(RESULTS_PATH, results)
    print(json.dumps({"verdict": results["verdict"], "pooled": results["forecast"]["pooled"]}, indent=2))
    return results


if __name__ == "__main__":
    main()
