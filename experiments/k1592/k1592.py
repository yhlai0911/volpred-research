#!/usr/bin/env python3
"""K1592: genuine OOS gamma-rule horse race for leverage-direction paper.

This experiment freezes a simple gamma rule on pre-2021 evidence, then tests it
on a future 2023-2026 OOS period and a disjoint asset subset. It is intentionally
conservative: all inputs come from the paper's pinned CSV snapshot, forecasts are
target-aligned one-step variance forecasts, QLIKE uses the canonical Patton ratio
actual / predicted, and panel inference averages losses by date before DM tests.
"""

from __future__ import annotations

import json
import math
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from arch import arch_model

from volpred.stats.mcs import model_confidence_set
from volpred.stats.model_evaluation import dm_test, qlike, qlike_pointwise


EXPERIMENT_ID = "k1592"
ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "experiments" / EXPERIMENT_ID
DATA_PATH = (
    ROOT
    / "paper"
    / "leverage-direction"
    / "data"
    / "spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv"
)

SEED = 1592
WINDOW = 504
REFIT_EVERY = 21
OOS_START = pd.Timestamp("2023-01-03")
OOS_END = pd.Timestamp("2026-06-26")
DEV_START = pd.Timestamp("2017-01-01")
DEV_END = pd.Timestamp("2020-12-31")
GAMMA_T_THRESHOLD = 1.65

ASSETS = {
    "SPY": "spy_adj_close",
    "QQQ": "qqq_adj_close",
    "EEM": "eem_adj_close",
    "GLD": "gld_adj_close",
    "TLT": "tlt_adj_close",
    "IWM": "iwm_adj_close",
    "SLV": "slv_adj_close",
    "BTC-USD": "btc_usd_adj_close",
}

DEV_ASSETS = ["SPY", "QQQ", "EEM", "GLD", "TLT"]
HOLDOUT_ASSETS = ["IWM", "SLV", "BTC-USD"]
MODEL_NAMES = ["GARCH", "GJR", "GammaRule"]


@dataclass
class FitBundle:
    model: str
    params: dict[str, float]
    stderr: dict[str, float]
    last_h: float
    convergence_flag: int
    loglikelihood: float


def load_returns() -> dict[str, pd.Series]:
    raw = pd.read_csv(DATA_PATH, parse_dates=["date"]).set_index("date").sort_index()
    out: dict[str, pd.Series] = {}
    for asset, col in ASSETS.items():
        px = raw[col].dropna()
        # snapshot-dup guard (audit_snapshot_dup_20260721): dedup dates on the PRICE
        # series BEFORE differencing. Deduping AFTER .diff() (the previous order)
        # retained a fabricated 0.0 return for every duplicate date — the second copy
        # of an identical price pair diffs to 0 — and count audits missed it because
        # the row count stayed unchanged.
        px = px[~px.index.duplicated(keep="last")]
        ret = 100.0 * np.log(px).diff()
        ret = ret.replace([np.inf, -np.inf], np.nan).dropna()
        out[asset] = ret
    return out


def fit_arch(train: pd.Series, gjr: bool) -> FitBundle:
    if len(train) < WINDOW:
        raise ValueError(f"training window too short: {len(train)}")
    model_name = "GJR" if gjr else "GARCH"
    spec = arch_model(
        train,
        mean="Zero",
        vol="GARCH",
        p=1,
        o=1 if gjr else 0,
        q=1,
        dist="normal",
        rescale=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = spec.fit(disp="off", show_warning=False, options={"maxiter": 1000})
    params = {str(k): float(v) for k, v in res.params.items()}
    stderr = {str(k): float(v) for k, v in res.std_err.items()}
    last_h = float(res.conditional_volatility.iloc[-1] ** 2)
    return FitBundle(
        model=model_name,
        params=params,
        stderr=stderr,
        last_h=last_h,
        convergence_flag=int(res.convergence_flag),
        loglikelihood=float(res.loglikelihood),
    )


def next_variance(bundle: FitBundle, last_eps: float, last_h: float) -> float:
    omega = bundle.params.get("omega", np.nan)
    alpha = bundle.params.get("alpha[1]", 0.0)
    beta = bundle.params.get("beta[1]", 0.0)
    gamma = bundle.params.get("gamma[1]", 0.0)
    asym = gamma * (last_eps < 0.0) * (last_eps**2)
    h = omega + alpha * (last_eps**2) + asym + beta * last_h
    if not np.isfinite(h) or h <= 1e-12:
        return 1e-12
    return float(min(h, 1e4))


def forecast_block(bundle: FitBundle, train: pd.Series, block_returns: pd.Series) -> pd.Series:
    last_eps = float(train.iloc[-1])
    last_h = float(bundle.last_h)
    forecasts: list[float] = []
    for _, ret in block_returns.items():
        h = next_variance(bundle, last_eps=last_eps, last_h=last_h)
        forecasts.append(h)
        last_eps = float(ret)
        last_h = h
    return pd.Series(forecasts, index=block_returns.index, name=bundle.model)


def gamma_rule(gamma: float, gamma_se: float) -> tuple[str, float]:
    gamma_t = gamma / gamma_se if gamma_se and np.isfinite(gamma_se) and gamma_se > 0 else np.nan
    if np.isfinite(gamma_t) and gamma > 0.0 and gamma_t > GAMMA_T_THRESHOLD:
        return "GJR", float(gamma_t)
    return "GARCH", float(gamma_t) if np.isfinite(gamma_t) else np.nan


def development_calibration(returns: dict[str, pd.Series]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for asset in DEV_ASSETS:
        r = returns[asset].loc[DEV_START:DEV_END]
        if len(r) < WINDOW:
            continue
        try:
            fit = fit_arch(r.iloc[-WINDOW:], gjr=True)
            gamma = fit.params.get("gamma[1]", np.nan)
            gamma_se = fit.stderr.get("gamma[1]", np.nan)
            choice, gamma_t = gamma_rule(gamma, gamma_se)
            rows.append(
                {
                    "asset": asset,
                    "sample_start": str(r.iloc[-WINDOW:].index[0].date()),
                    "sample_end": str(r.index[-1].date()),
                    "n": int(len(r.iloc[-WINDOW:])),
                    "gamma": gamma,
                    "gamma_se": gamma_se,
                    "gamma_t": gamma_t,
                    "frozen_rule_choice": choice,
                    "convergence_flag": fit.convergence_flag,
                }
            )
        except Exception as exc:  # pragma: no cover - recorded in results
            rows.append({"asset": asset, "error": repr(exc)})
    return rows


def run_asset(asset: str, returns: pd.Series) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]]]:
    oos_dates = returns.loc[OOS_START:OOS_END].index
    losses: list[pd.DataFrame] = []
    decisions: list[dict[str, Any]] = []
    warnings_out: list[dict[str, Any]] = []
    if len(oos_dates) == 0:
        return pd.DataFrame(), pd.DataFrame(), [{"asset": asset, "warning": "no_oos_dates"}]

    origin_positions = list(range(0, len(oos_dates), REFIT_EVERY))
    for origin_i, pos in enumerate(origin_positions):
        origin = oos_dates[pos]
        next_pos = origin_positions[origin_i + 1] if origin_i + 1 < len(origin_positions) else len(oos_dates)
        block_dates = oos_dates[pos:next_pos]
        train = returns.loc[: returns.index[returns.index.get_loc(origin) - 1]].dropna().iloc[-WINDOW:]
        block_returns = returns.loc[block_dates].dropna()
        if len(train) < WINDOW or len(block_returns) == 0:
            continue

        try:
            garch_fit = fit_arch(train, gjr=False)
            gjr_fit = fit_arch(train, gjr=True)
        except Exception as exc:
            warnings_out.append({"asset": asset, "origin": str(origin.date()), "warning": "fit_failed", "error": repr(exc)})
            continue

        for fit in (garch_fit, gjr_fit):
            if fit.convergence_flag != 0:
                warnings_out.append(
                    {
                        "asset": asset,
                        "origin": str(origin.date()),
                        "warning": "nonzero_convergence_flag",
                        "model": fit.model,
                        "flag": fit.convergence_flag,
                    }
                )

        gamma = gjr_fit.params.get("gamma[1]", np.nan)
        gamma_se = gjr_fit.stderr.get("gamma[1]", np.nan)
        chosen_model, gamma_t = gamma_rule(gamma, gamma_se)
        f_garch = forecast_block(garch_fit, train, block_returns)
        f_gjr = forecast_block(gjr_fit, train, block_returns)
        f_rule = f_gjr if chosen_model == "GJR" else f_garch
        actual = block_returns**2
        l_garch = qlike_pointwise(actual.to_numpy(), f_garch.to_numpy())
        l_gjr = qlike_pointwise(actual.to_numpy(), f_gjr.to_numpy())
        l_rule = qlike_pointwise(actual.to_numpy(), f_rule.to_numpy())

        block_loss = pd.DataFrame(
            {
                "date": block_returns.index,
                "asset": asset,
                "actual_r2": actual.to_numpy(),
                "GARCH_forecast_var": f_garch.to_numpy(),
                "GJR_forecast_var": f_gjr.to_numpy(),
                "GammaRule_forecast_var": f_rule.to_numpy(),
                "GARCH_loss": l_garch,
                "GJR_loss": l_gjr,
                "GammaRule_loss": l_rule,
                "origin": origin,
                "chosen_model": chosen_model,
                "gamma": gamma,
                "gamma_se": gamma_se,
                "gamma_t": gamma_t,
            }
        )
        losses.append(block_loss)
        decisions.append(
            {
                "asset": asset,
                "origin": str(origin.date()),
                "train_start": str(train.index[0].date()),
                "train_end": str(train.index[-1].date()),
                "block_start": str(block_returns.index[0].date()),
                "block_end": str(block_returns.index[-1].date()),
                "n_block": int(len(block_returns)),
                "gamma": gamma,
                "gamma_se": gamma_se,
                "gamma_t": gamma_t,
                "chosen_model": chosen_model,
                "block_mean_loss_garch": float(np.nanmean(l_garch)),
                "block_mean_loss_gjr": float(np.nanmean(l_gjr)),
                "block_mean_loss_rule": float(np.nanmean(l_rule)),
                "block_rule_minus_garch": float(np.nanmean(l_rule - l_garch)),
                "block_rule_minus_gjr": float(np.nanmean(l_rule - l_gjr)),
            }
        )

    loss_df = pd.concat(losses, ignore_index=True) if losses else pd.DataFrame()
    decisions_df = pd.DataFrame(decisions)
    return loss_df, decisions_df, warnings_out


def holm_adjust(p_values: list[float]) -> list[float]:
    m = len(p_values)
    order = np.argsort(p_values)
    adjusted = np.empty(m, dtype=float)
    running = 0.0
    for rank, idx in enumerate(order):
        adj = min(1.0, (m - rank) * p_values[idx])
        running = max(running, adj)
        adjusted[idx] = running
    return adjusted.tolist()


def summarize_asset(asset: str, df: pd.DataFrame) -> dict[str, Any]:
    actual = df["actual_r2"].to_numpy()
    out: dict[str, Any] = {
        "asset": asset,
        "sample_start": str(pd.to_datetime(df["date"]).min().date()),
        "sample_end": str(pd.to_datetime(df["date"]).max().date()),
        "n": int(len(df)),
        "universe_split": "development" if asset in DEV_ASSETS else "holdout",
        "rule_gjr_share": float((df["chosen_model"] == "GJR").mean()),
        "mean_gamma_t": float(df["gamma_t"].replace([np.inf, -np.inf], np.nan).mean()),
    }
    for model in MODEL_NAMES:
        forecast_col = f"{model}_forecast_var"
        out[f"{model}_qlike"] = qlike(actual, df[forecast_col].to_numpy())
        out[f"{model}_mean_loss"] = float(df[f"{model}_loss"].mean())

    pairs = [("GammaRule", "GARCH"), ("GammaRule", "GJR"), ("GJR", "GARCH")]
    for lhs, rhs in pairs:
        t_stat, p_val = dm_test(df[f"{lhs}_loss"].to_numpy(), df[f"{rhs}_loss"].to_numpy(), h=1)
        out[f"dm_{lhs}_minus_{rhs}_t"] = t_stat
        out[f"dm_{lhs}_minus_{rhs}_p"] = p_val
        out[f"dm_{lhs}_minus_{rhs}_interpretation"] = (
            f"{lhs}_better" if t_stat < -3.0 else f"{rhs}_better" if t_stat > 3.0 else "equal_accuracy_not_rejected"
        )
    out["best_mean_loss_model"] = min(MODEL_NAMES, key=lambda m: out[f"{m}_mean_loss"])
    return out


def panel_summary(loss_df: pd.DataFrame, assets: list[str], label: str) -> dict[str, Any]:
    sub = loss_df[loss_df["asset"].isin(assets)].copy()
    if sub.empty:
        return {"label": label, "error": "empty_panel"}

    counts = sub.groupby("date")["asset"].nunique()
    common_dates = counts[counts == len(assets)].index
    sub = sub[sub["date"].isin(common_dates)]
    if sub.empty:
        return {"label": label, "error": "empty_common_date_panel"}

    by_date = (
        sub.groupby("date")[[f"{m}_loss" for m in MODEL_NAMES]]
        .mean()
        .dropna(how="any")
        .sort_index()
    )
    out: dict[str, Any] = {
        "label": label,
        "assets": assets,
        "n_dates": int(len(by_date)),
        "date_alignment": "common dates only; every listed asset has a valid loss on each panel date",
        "date_start": str(pd.to_datetime(by_date.index.min()).date()),
        "date_end": str(pd.to_datetime(by_date.index.max()).date()),
        "mean_losses": {m: float(by_date[f"{m}_loss"].mean()) for m in MODEL_NAMES},
        "best_mean_loss_model": min(MODEL_NAMES, key=lambda m: float(by_date[f"{m}_loss"].mean())),
        "dm_tests": {},
    }
    for lhs, rhs in [("GammaRule", "GARCH"), ("GammaRule", "GJR"), ("GJR", "GARCH")]:
        t_stat, p_val = dm_test(by_date[f"{lhs}_loss"].to_numpy(), by_date[f"{rhs}_loss"].to_numpy(), h=1)
        out["dm_tests"][f"{lhs}_minus_{rhs}"] = {
            "t": t_stat,
            "p": p_val,
            "interpretation": (
                f"{lhs}_better" if t_stat < -3.0 else f"{rhs}_better" if t_stat > 3.0 else "equal_accuracy_not_rejected"
            ),
        }

    mcs_losses = {m: by_date[f"{m}_loss"].to_numpy() for m in MODEL_NAMES}
    out["mcs"] = model_confidence_set(mcs_losses, alpha=0.10, n_boot=1000, seed=SEED)
    return out


def apply_multiple_testing(asset_rows: list[dict[str, Any]]) -> None:
    keys = []
    p_values = []
    for row in asset_rows:
        for comparison in ["GammaRule_minus_GARCH", "GammaRule_minus_GJR", "GJR_minus_GARCH"]:
            p_key = f"dm_{comparison}_p"
            if p_key in row and np.isfinite(row[p_key]):
                keys.append((row, comparison))
                p_values.append(float(row[p_key]))
    adjusted = holm_adjust(p_values)
    for (row, comparison), p_adj in zip(keys, adjusted):
        row[f"dm_{comparison}_p_holm"] = float(p_adj)
        t_key = f"dm_{comparison}_t"
        row[f"dm_{comparison}_harvey_holm_pass"] = bool(abs(row[t_key]) > 3.0 and p_adj < 0.05)


def write_figures(asset_summary: list[dict[str, Any]], decision_df: pd.DataFrame) -> list[str]:
    fig_paths: list[str] = []
    summary = pd.DataFrame(asset_summary)
    if not summary.empty:
        fig, ax = plt.subplots(figsize=(9, 4.8))
        x = np.arange(len(summary))
        width = 0.25
        for j, model in enumerate(MODEL_NAMES):
            ax.bar(x + (j - 1) * width, summary[f"{model}_mean_loss"], width=width, label=model)
        ax.set_xticks(x)
        ax.set_xticklabels(summary["asset"], rotation=0)
        ax.set_ylabel("Mean Patton QLIKE loss")
        ax.set_title("K1592 OOS horse race by asset")
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, 1.12), ncol=3, frameon=False)
        fig.tight_layout()
        path = OUT_DIR / "fig1_oos_mean_qlike_by_asset.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        fig_paths.append(str(path.relative_to(ROOT)))

        fig, ax = plt.subplots(figsize=(8, 4.6))
        ax.bar(summary["asset"], summary["rule_gjr_share"], color="#4C78A8")
        ax.axhline(0.5, color="black", lw=0.8, ls="--")
        ax.set_ylim(0, 1)
        ax.set_ylabel("Share of OOS days choosing GJR")
        ax.set_title("GammaRule model-selection share")
        fig.tight_layout()
        path = OUT_DIR / "fig2_gammarule_gjr_share.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        fig_paths.append(str(path.relative_to(ROOT)))

    if not decision_df.empty:
        fig, ax = plt.subplots(figsize=(9, 4.8))
        for asset, g in decision_df.groupby("asset"):
            ax.plot(pd.to_datetime(g["origin"]), g["gamma_t"], marker="o", ms=2.5, lw=0.8, label=asset)
        ax.axhline(GAMMA_T_THRESHOLD, color="black", lw=0.8, ls="--", label="t=1.65 rule")
        ax.set_ylabel("Current-window gamma t-stat")
        ax.set_title("Forecast-origin gamma signal")
        ax.legend(ncol=4, fontsize=8, frameon=False)
        fig.tight_layout()
        path = OUT_DIR / "fig3_origin_gamma_t.png"
        fig.savefig(path, dpi=160)
        plt.close(fig)
        fig_paths.append(str(path.relative_to(ROOT)))
    return fig_paths


def main() -> None:
    np.random.seed(SEED)
    returns = load_returns()
    dev_calibration = development_calibration(returns)

    all_losses: list[pd.DataFrame] = []
    all_decisions: list[pd.DataFrame] = []
    fit_warnings: list[dict[str, Any]] = []
    for asset, series in returns.items():
        loss_df, decision_df, warnings_out = run_asset(asset, series)
        if not loss_df.empty:
            all_losses.append(loss_df)
        if not decision_df.empty:
            all_decisions.append(decision_df)
        fit_warnings.extend(warnings_out)

    if not all_losses:
        raise RuntimeError("no valid OOS forecasts generated")

    loss_df = pd.concat(all_losses, ignore_index=True)
    decision_df = pd.concat(all_decisions, ignore_index=True)
    loss_df["date"] = pd.to_datetime(loss_df["date"])
    decision_df["origin"] = pd.to_datetime(decision_df["origin"])

    panel_file = OUT_DIR / "k1592_oos_losses.csv"
    decision_file = OUT_DIR / "k1592_forecast_origin_decision_log.csv"
    loss_df.to_csv(panel_file, index=False)
    decision_df.to_csv(decision_file, index=False)

    asset_summary = [summarize_asset(asset, loss_df[loss_df["asset"] == asset]) for asset in ASSETS]
    apply_multiple_testing(asset_summary)

    panels = [
        panel_summary(loss_df, DEV_ASSETS, "development_assets_future_oos"),
        panel_summary(loss_df, HOLDOUT_ASSETS, "disjoint_holdout_assets_future_oos"),
        panel_summary(loss_df, list(ASSETS), "all_assets_future_oos"),
    ]
    figures = write_figures(asset_summary, decision_df)

    rule_wins = sum(row["best_mean_loss_model"] == "GammaRule" for row in asset_summary)
    rule_strict_passes = sum(
        row.get("dm_GammaRule_minus_GARCH_harvey_holm_pass", False)
        or row.get("dm_GammaRule_minus_GJR_harvey_holm_pass", False)
        for row in asset_summary
    )
    conclusion = {
        "verdict": "NULL_OR_WEAK",
        "headline": (
            "The pre-specified positive-gamma rule is not a JBF-grade OOS superiority result; "
            "it is mainly a risk-controlled model-selection diagnostic."
        ),
        "rule_best_mean_loss_assets": int(rule_wins),
        "rule_harvey_holm_superiority_assets": int(rule_strict_passes),
        "required_paper_change": "Delete or demote any 'never significantly beaten' / 'genuine OOS gains' headline; report significant superiority separately from equal-accuracy non-rejection.",
    }

    result = {
        "experiment_id": EXPERIMENT_ID,
        "created_at": pd.Timestamp.now(tz="Asia/Taipei").isoformat(),
        "seed": SEED,
        "task": "paper_leverage_direction_stage2_oos_horse_race",
        "data": {
            "source": str(DATA_PATH.relative_to(ROOT)),
            "snapshot": "paper pinned yfinance CSV, not refreshed during experiment",
            "assets": list(ASSETS),
            "development_assets": DEV_ASSETS,
            "disjoint_holdout_assets": HOLDOUT_ASSETS,
            "development_rule_period": [str(DEV_START.date()), str(DEV_END.date())],
            "oos_period": [str(OOS_START.date()), str(OOS_END.date())],
            "return_unit": "100 * log adjusted close return; variance forecasts and r^2 are in percent-squared units",
        },
        "pre_specification": {
            "window": WINDOW,
            "refit_every_trading_days": REFIT_EVERY,
            "models": {
                "GARCH": "Zero-mean GARCH(1,1), Normal quasi-likelihood",
                "GJR": "Zero-mean GJR-GARCH(1,1), Normal quasi-likelihood",
                "GammaRule": f"Use GJR iff current-window gamma > 0 and gamma_t > {GAMMA_T_THRESHOLD}; otherwise use GARCH",
            },
            "forecast_alignment": "At each forecast origin, parameters are fit on prior 504 returns only. Daily one-step forecasts update with realized r_t only after forecasting that day.",
            "loss": "Patton QLIKE actual/predicted - log(actual/predicted) - 1 via volpred.stats.model_evaluation.qlike_pointwise",
            "inference": "Asset-level DM-HAC h=1; panel tests use date-clustered mean loss by date before DM; MCS uses HLN2011 stationary bootstrap with B=1000.",
            "significance_language": "|t| > 3 and Holm p < 0.05 is strict superiority; otherwise equal accuracy is not rejected.",
        },
        "literature_checked": [
            {
                "paper": "Patton (2011), Volatility forecast comparison using imperfect volatility proxies",
                "url": "https://doi.org/10.1016/j.jeconom.2010.03.034",
                "use": "QLIKE orientation and proxy-robust variance forecast loss",
            },
            {
                "paper": "Hansen, Lunde, and Nason (2011), The Model Confidence Set",
                "url": "https://doi.org/10.3982/ECTA5771",
                "use": "MCS to avoid declaring one best model when data are uninformative",
            },
            {
                "paper": "Harvey, Leybourne, and Newbold (1997), Testing equality of prediction mean squared errors",
                "url": "https://doi.org/10.1016/S0169-2070(96)00719-4",
                "use": "forecast-comparison small-sample caution and DM correction context",
            },
            {
                "paper": "Glosten, Jagannathan, and Runkle (1993), asymmetric volatility specification",
                "url": "https://doi.org/10.1111/j.1540-6261.1993.tb05128.x",
                "use": "gamma leverage term tested as model-selection signal",
            },
        ],
        "development_calibration": dev_calibration,
        "asset_summary": asset_summary,
        "panel_summary": panels,
        "fit_warnings": fit_warnings,
        "outputs": {
            "loss_panel_csv": str(panel_file.relative_to(ROOT)),
            "decision_log_csv": str(decision_file.relative_to(ROOT)),
            "figures": figures,
        },
        "conclusion": conclusion,
    }

    result_file = OUT_DIR / "k1592_results.json"
    with result_file.open("w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)

    print(json.dumps({"ok": True, "result_file": str(result_file), "conclusion": conclusion}, indent=2))


if __name__ == "__main__":
    main()
