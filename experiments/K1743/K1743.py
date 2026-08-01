"""K1743: TSM/2330.TW daily price discovery and volatility transmission."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import yfinance as yf

from volpred.research.reproduce_spec import finalize_experiment
from volpred.stats.model_evaluation import clark_west_test, qlike_pointwise

SEED = 42
START = "2010-01-01"
TRAIN_END = pd.Timestamp("2020-12-31")
ADR_RATIO = 5.0
FX_VALID_RANGE_TWD_PER_USD = (10.0, 100.0)
MAX_INVALID_FX_SHARE = 0.01
np.random.seed(SEED)


def _download(ticker: str) -> pd.DataFrame:
    frame = yf.download(ticker, start=START, auto_adjust=False, progress=False)
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    needed = ["Open", "Close"]
    if frame.empty or any(col not in frame for col in needed):
        raise RuntimeError(f"Yahoo download missing OHLC for {ticker}")
    out = frame[needed].astype(float).copy()
    out.index = pd.to_datetime(out.index).tz_localize(None).normalize()
    return out[~out.index.duplicated(keep="last")]


def _ols_fit(x: pd.DataFrame, y: pd.Series) -> np.ndarray:
    design = np.column_stack([np.ones(len(x)), x.to_numpy(float)])
    return np.linalg.lstsq(design, y.to_numpy(float), rcond=None)[0]


def _predict(x: pd.DataFrame, beta: np.ndarray) -> np.ndarray:
    return np.column_stack([np.ones(len(x)), x.to_numpy(float)]) @ beta


def _clean_common_panel(panel: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Drop isolated impossible TWD/USD ticks and fail on feed corruption.

    Yahoo returned 1.8015 on 2011-10-25 and 3.67 on 2014-12-31 in an
    otherwise 28--33 TWD/USD series.  Those two provider glitches generated
    impossible -94%/-88% ADR premia.  They are excluded, never imputed; a
    material share of invalid FX observations aborts the experiment instead of
    silently manufacturing a clean series.
    """
    required = {"us_Close", "tw_Close", "fx_Close"}
    missing = sorted(required - set(panel.columns))
    if missing:
        raise RuntimeError(f"common panel missing required columns: {missing}")
    if panel.empty:
        raise RuntimeError("common panel is empty")

    price_values = panel[["us_Close", "tw_Close"]].to_numpy(float)
    if not np.isfinite(price_values).all() or (price_values <= 0).any():
        raise RuntimeError("equity close series contains non-finite/non-positive values")

    low, high = FX_VALID_RANGE_TWD_PER_USD
    fx = panel["fx_Close"].astype(float)
    invalid = ~np.isfinite(fx) | ~fx.between(low, high, inclusive="both")
    invalid_rows = panel.loc[invalid, "fx_Close"]
    invalid_share = float(invalid.sum() / len(panel))
    diagnostics = {
        "fx_valid_range_twd_per_usd": [low, high],
        "invalid_fx_count": int(invalid.sum()),
        "invalid_fx_share": invalid_share,
        "invalid_fx_observations": [
            {"date": str(pd.Timestamp(index).date()), "value": float(value)}
            for index, value in invalid_rows.items()
        ],
        "action": "dropped_not_imputed",
    }
    if invalid_share > MAX_INVALID_FX_SHARE:
        raise RuntimeError(
            "FX corruption exceeds 1% fail-closed threshold: "
            f"{int(invalid.sum())}/{len(panel)} ({invalid_share:.2%})"
        )
    return panel.loc[~invalid].copy(), diagnostics


def _evaluate(panel: pd.DataFrame, target: str, base_cols: list[str],
              aug_cols: list[str]) -> dict:
    cols = [target, *dict.fromkeys(base_cols + aug_cols)]
    sample = panel[cols].replace([np.inf, -np.inf], np.nan).dropna()
    train = sample.loc[:TRAIN_END]
    test = sample.loc[TRAIN_END + pd.Timedelta(days=1):]
    if len(train) < 500 or len(test) < 250:
        raise RuntimeError(f"insufficient split for {target}: {len(train)}/{len(test)}")

    y_train = train[target].abs()
    base_beta = _ols_fit(train[base_cols], y_train)
    aug_beta = _ols_fit(train[aug_cols], y_train)
    base_abs = np.maximum(_predict(test[base_cols], base_beta), 1e-6)
    aug_abs = np.maximum(_predict(test[aug_cols], aug_beta), 1e-6)
    actual_abs = test[target].abs().to_numpy(float)
    actual_var = np.maximum(actual_abs ** 2, 1e-12)
    base_var = np.maximum(base_abs ** 2, 1e-12)
    aug_var = np.maximum(aug_abs ** 2, 1e-12)
    base_loss = qlike_pointwise(actual_var, base_var)
    aug_loss = qlike_pointwise(actual_var, aug_var)
    cw = clark_west_test(actual_abs, base_abs, aug_abs, h=1)
    mse_base = float(np.mean((actual_abs - base_abs) ** 2))
    mse_aug = float(np.mean((actual_abs - aug_abs) ** 2))
    q_base = float(np.mean(base_loss))
    q_aug = float(np.mean(aug_loss))
    supported = bool(
        q_aug < q_base and mse_aug < mse_base
        and cw["status"] == "ok" and cw["p_value_one_sided"] < 0.05
    )
    return {
        "train_n": len(train), "oos_n": len(test),
        "train_start": str(train.index.min().date()),
        "train_end": str(train.index.max().date()),
        "oos_start": str(test.index.min().date()),
        "oos_end": str(test.index.max().date()),
        "features_baseline": base_cols, "features_augmented": aug_cols,
        "coefficients_baseline": [float(v) for v in base_beta],
        "coefficients_augmented": [float(v) for v in aug_beta],
        "mse_baseline": mse_base, "mse_augmented": mse_aug,
        "mse_improvement_pct": 100 * (mse_base - mse_aug) / mse_base,
        "qlike_baseline": q_base, "qlike_augmented": q_aug,
        "qlike_improvement_pct": 100 * (q_base - q_aug) / q_base,
        "clark_west_primary": cw,
        "direction_supported": supported,
    }


def main() -> None:
    started_at = time.time()
    tsm = _download("TSM").add_prefix("us_")
    tw = _download("2330.TW").add_prefix("tw_")
    fx = _download("TWD=X").add_prefix("fx_")
    panel = pd.concat([tsm, tw, fx], axis=1, join="inner").dropna()
    panel, data_quality = _clean_common_panel(panel)
    panel["us_ret"] = np.log(panel["us_Close"]).diff()
    panel["tw_ret"] = np.log(panel["tw_Close"]).diff()
    panel["premium"] = np.log(
        panel["us_Close"] * panel["fx_Close"] / (ADR_RATIO * panel["tw_Close"])
    )
    panel["premium_change"] = panel["premium"].diff()
    panel["us_abs_lag"] = panel["us_ret"].abs().shift(1)
    panel["tw_abs_lag"] = panel["tw_ret"].abs().shift(1)
    panel["premium_change_lag"] = panel["premium_change"].shift(1)

    # US close at t is known before the next common-date Taiwan close.
    signal = panel["us_ret"]
    panel["us_signal_for_tw"] = signal.shift(1)
    # Taiwan closes before New York opens on the same calendar day.
    panel["tw_signal_for_us"] = panel["tw_ret"]

    us_result = _evaluate(
        panel, "us_ret", ["us_abs_lag"],
        ["us_abs_lag", "tw_signal_for_us", "premium_change_lag"],
    )
    tw_result = _evaluate(
        panel, "tw_ret", ["tw_abs_lag"],
        ["tw_abs_lag", "us_signal_for_tw", "premium_change_lag"],
    )
    annual = panel.assign(year=panel.index.year).groupby("year")["premium"].agg(
        ["count", "mean", "median", "min", "max"]
    )
    annual_pct = (100 * np.expm1(annual)).round(6)
    annual_pct["count"] = annual["count"].astype(int)
    result = {
        "experiment_id": "K1743", "seed": SEED,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "data": {
            "source": "Yahoo Finance via yfinance",
            "tickers": ["TSM", "2330.TW", "TWD=X"],
            "start": str(panel.index.min().date()), "end": str(panel.index.max().date()),
            "common_date_n": len(panel), "adr_ratio": ADR_RATIO,
            "fx_interpretation": "TWD per USD",
            "quality_controls": data_quality,
            "sha256_common_close_csv": hashlib.sha256(
                panel[["us_Close", "tw_Close", "fx_Close"]].to_csv().encode()
            ).hexdigest(),
        },
        "timing": {
            "taipei_to_new_york": "same calendar date; Taipei close precedes NY open",
            "new_york_to_taipei": "previous common-date US close via signal.shift(1)",
            "limitations": (
                "Daily common-date alignment omits non-overlap holidays; a target return can "
                "span more than one local trading session around exchange-specific holidays. "
                "This is not an intraday information-share design."
            ),
        },
        "annual_adr_premium_pct": {
            str(year): {k: (int(v) if k == "count" else float(v)) for k, v in row.items()}
            for year, row in annual_pct.to_dict("index").items()
        },
        "volatility_forecast": {"taipei_to_new_york": us_result, "new_york_to_taipei": tw_result},
        "success_rule": "both OOS QLIKE and MSE improve and one-sided Clark-West p < 0.05",
        "overall_verdict": (
            "PASS" if us_result["direction_supported"] or tw_result["direction_supported"] else "NULL"
        ),
    }
    results_path, _spec = finalize_experiment(
        results=result,
        entrypoint=__file__,
        canonical_result="K1743_results.json",
        inputs=[],
        seeds=[("numpy", SEED)],
        started_at=started_at,
        network="allow",
    )
    print(json.dumps({
        "output": str(results_path),
        "verdict": result["overall_verdict"],
    }, indent=2))


if __name__ == "__main__":
    main()
