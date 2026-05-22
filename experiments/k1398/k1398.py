from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
from arch import arch_model
from scipy.optimize import minimize
from scipy.special import gammaln
from scipy.stats import t as student_t

np.random.seed(42)

EXPERIMENT_ID = "K1398"
TITLE = "MEM/AMEM vs GJR/HAR: Daily Volatility Forecasting"
WINDOW = 2000
REFIT_EVERY = 100
FIT_SAMPLE = 2500
EPS = 1e-12
ROOT = Path(__file__).resolve().parents[2]
EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / "k1398_results.json"
README_PATH = EXPERIMENT_DIR / "README.md"


@dataclass
class AssetConfig:
    name: str
    csv_path: Path
    price_col: str


ASSETS = [
    AssetConfig(
        name="SPY",
        csv_path=ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        price_col="spy_adj_close",
    ),
    AssetConfig(
        name="QQQ",
        csv_path=ROOT / "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
        price_col="qqq_adj_close",
    ),
    AssetConfig(
        name="GLD",
        csv_path=ROOT / "paper/garch-x-vix/data/gld_vix_gvz_2000-2026.csv",
        price_col="gld_adj_close",
    ),
]


def load_asset_series(config: AssetConfig) -> pd.DataFrame:
    df = pd.read_csv(config.csv_path, usecols=["date", config.price_col])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").dropna().copy()
    df["r"] = np.log(df[config.price_col] / df[config.price_col].shift(1))
    df["rv"] = np.square(df["r"])
    df = df.replace([np.inf, -np.inf], np.nan).dropna(subset=["r", "rv"]).reset_index(drop=True)
    return df[["date", "r", "rv"]]


def mem_loglik(params: np.ndarray, rv: np.ndarray, returns: np.ndarray, asymmetric: bool) -> float:
    omega = params[0]
    alpha = params[1]
    beta = params[2]
    gamma = params[3] if asymmetric else 0.0
    shape = params[4] if asymmetric else params[3]

    if omega <= 0 or alpha < 0 or beta < 0 or shape <= 0 or gamma < 0 or alpha + beta >= 1:
        return 1e12

    n = len(rv)
    if n < 2:
        return 1e12

    mu = np.empty(n)
    mu[0] = max(rv.mean(), EPS)
    for i in range(1, n):
        leverage = rv[i - 1] * (returns[i - 1] < 0) if asymmetric else 0.0
        mu[i] = omega + alpha * rv[i - 1] + beta * mu[i - 1] + gamma * leverage
        mu[i] = max(mu[i], EPS)

    rv_eval = np.maximum(rv[1:], EPS)
    mu_eval = np.maximum(mu[1:], EPS)
    ll = (
        shape * np.log(shape)
        - shape * np.log(mu_eval)
        + (shape - 1.0) * np.log(rv_eval)
        - shape * rv_eval / mu_eval
        - gammaln(shape)
    )
    if not np.all(np.isfinite(ll)):
        return 1e12
    return float(-np.sum(ll))


def fit_mem(rv: np.ndarray, returns: np.ndarray, asymmetric: bool, initial_guess: np.ndarray | None = None) -> np.ndarray:
    if asymmetric:
        x0 = np.array([1e-4, 0.10, 0.85, 0.05, 1.0]) if initial_guess is None else initial_guess
        bounds = [(1e-8, None), (0.0, 0.99), (0.0, 0.99), (0.0, 0.99), (0.1, 50.0)]
    else:
        x0 = np.array([1e-4, 0.10, 0.85, 1.0]) if initial_guess is None else initial_guess
        bounds = [(1e-8, None), (0.0, 0.99), (0.0, 0.99), (0.1, 50.0)]

    constraints = [{"type": "ineq", "fun": lambda p: 0.999999 - p[1] - p[2]}]
    result = minimize(
        mem_loglik,
        x0=x0,
        args=(rv, returns, asymmetric),
        method="SLSQP",
        bounds=bounds,
        constraints=constraints,
        options={"maxiter": 150, "ftol": 1e-7},
    )
    if result.success and np.all(np.isfinite(result.x)):
        return result.x
    return x0


def mem_last_state(params: np.ndarray, rv: np.ndarray, returns: np.ndarray, asymmetric: bool) -> float:
    omega = params[0]
    alpha = params[1]
    beta = params[2]
    gamma = params[3] if asymmetric else 0.0

    mu_prev = max(rv[0], EPS)
    for i in range(1, len(rv)):
        leverage = rv[i - 1] * (returns[i - 1] < 0) if asymmetric else 0.0
        mu_prev = omega + alpha * rv[i - 1] + beta * mu_prev + gamma * leverage
        mu_prev = max(mu_prev, EPS)

    return float(max(mu_prev, EPS))


def mem_next_forecast(params: np.ndarray, last_rv: float, last_return: float, mu_last: float, asymmetric: bool) -> float:
    omega = params[0]
    alpha = params[1]
    beta = params[2]
    gamma = params[3] if asymmetric else 0.0
    leverage = last_rv * (last_return < 0) if asymmetric else 0.0
    forecast = omega + alpha * last_rv + beta * mu_last + gamma * leverage
    return float(max(forecast, EPS))


def har_one_step(rv: np.ndarray) -> float:
    if len(rv) < 23:
        return float(max(np.mean(rv), EPS))

    rows = []
    targets = []
    for idx in range(22, len(rv)):
        rows.append(
            [
                1.0,
                rv[idx - 1],
                rv[idx - 5 : idx].mean(),
                rv[idx - 22 : idx].mean(),
            ]
        )
        targets.append(rv[idx])

    x = np.asarray(rows)
    y = np.asarray(targets)
    try:
        coef, *_ = np.linalg.lstsq(x, y, rcond=None)
    except np.linalg.LinAlgError:
        return float(max(np.mean(rv), EPS))

    x_next = np.array([1.0, rv[-1], rv[-5:].mean(), rv[-22:].mean()])
    forecast = float(np.dot(x_next, coef))
    return float(max(forecast, EPS))


def gjr_next_forecast(params: pd.Series, last_return: float, last_variance: float) -> float:
    omega = float(params["omega"]) / 10000.0
    alpha = float(params["alpha[1]"])
    gamma = float(params["gamma[1]"])
    beta = float(params["beta[1]"])
    shock = float(last_return**2)
    asym = shock if last_return < 0 else 0.0
    return float(max(omega + alpha * shock + gamma * asym + beta * last_variance, EPS))


def gjr_fit(train_returns: np.ndarray) -> tuple[pd.Series, float]:
    scaled = train_returns * 100.0
    model = arch_model(scaled, mean="Zero", vol="Garch", p=1, o=1, q=1, dist="normal", rescale=False)
    fitted = model.fit(disp="off", show_warning=False)
    params = fitted.params
    last_variance = float((fitted.conditional_volatility[-1] ** 2) / 10000.0)
    return params, max(last_variance, EPS)


def qlike_loss(pred: np.ndarray, actual: np.ndarray) -> np.ndarray:
    pred = np.maximum(pred, EPS)
    actual = np.maximum(actual, EPS)
    losses = np.log(pred) + actual / pred
    return losses[np.isfinite(losses)]


def mse_loss(pred: np.ndarray, actual: np.ndarray) -> np.ndarray:
    losses = np.square(pred - actual)
    return losses[np.isfinite(losses)]


def dm_test(loss_a: np.ndarray, loss_b: np.ndarray) -> dict[str, float | bool]:
    mask = np.isfinite(loss_a) & np.isfinite(loss_b)
    d = loss_a[mask] - loss_b[mask]
    n = int(len(d))
    if n < 2:
        return {"t_stat": float("nan"), "p_value": float("nan"), "significant": False}

    mean_d = float(np.mean(d))
    sd_d = float(np.std(d, ddof=1))
    if sd_d <= 0 or not np.isfinite(sd_d):
        return {"t_stat": float("nan"), "p_value": float("nan"), "significant": False}

    t_stat = mean_d / (sd_d / np.sqrt(n))
    p_value = 2.0 * (1.0 - student_t.cdf(abs(t_stat), df=n - 1))
    return {"t_stat": float(t_stat), "p_value": float(p_value), "significant": bool(p_value < 0.05)}


def rolling_forecasts(df: pd.DataFrame) -> dict[str, np.ndarray]:
    rv = df["rv"].to_numpy()
    returns = df["r"].to_numpy()
    preds = {"MEM": [], "AMEM": [], "HAR": [], "GJR": [], "actual": []}

    mem_params = None
    amem_params = None
    gjr_params = None
    mem_mu_last = None
    amem_mu_last = None
    gjr_h_last = None

    for t in range(WINDOW, len(df)):
        train_rv = rv[:t]
        train_returns = returns[:t]
        est_rv = train_rv[-FIT_SAMPLE:]
        est_returns = train_returns[-FIT_SAMPLE:]
        actual = rv[t]

        refit_now = (t - WINDOW) % REFIT_EVERY == 0
        if refit_now or mem_params is None:
            mem_params = fit_mem(est_rv, est_returns, asymmetric=False, initial_guess=mem_params)
            mem_mu_last = mem_last_state(mem_params, train_rv, train_returns, asymmetric=False)
        if refit_now or amem_params is None:
            amem_params = fit_mem(est_rv, est_returns, asymmetric=True, initial_guess=amem_params)
            amem_mu_last = mem_last_state(amem_params, train_rv, train_returns, asymmetric=True)
        if refit_now or gjr_params is None:
            gjr_params, gjr_h_last = gjr_fit(est_returns)

        mem_pred = mem_next_forecast(mem_params, train_rv[-1], train_returns[-1], mem_mu_last, asymmetric=False)
        amem_pred = mem_next_forecast(amem_params, train_rv[-1], train_returns[-1], amem_mu_last, asymmetric=True)
        gjr_pred = gjr_next_forecast(gjr_params, train_returns[-1], gjr_h_last)

        preds["MEM"].append(mem_pred)
        preds["AMEM"].append(amem_pred)
        preds["HAR"].append(har_one_step(train_rv))
        preds["GJR"].append(gjr_pred)
        preds["actual"].append(actual)
        mem_mu_last = mem_pred
        amem_mu_last = amem_pred
        gjr_h_last = gjr_pred

    return {k: np.asarray(v, dtype=float) for k, v in preds.items()}


def evaluate_asset(name: str, df: pd.DataFrame) -> dict[str, object]:
    forecasts = rolling_forecasts(df)
    actual = forecasts.pop("actual")

    qlike = {}
    mse = {}
    qlike_series = {}

    for model, pred in forecasts.items():
        mask = np.isfinite(pred) & np.isfinite(actual) & (pred > 0) & (actual >= 0)
        pred_clean = pred[mask]
        actual_clean = actual[mask]
        ql = qlike_loss(pred_clean, actual_clean)
        ms = mse_loss(pred_clean, actual_clean)
        qlike[model] = float(np.mean(ql))
        mse[model] = float(np.mean(ms))
        qlike_series[model] = ql

    return {
        "qlike": qlike,
        "mse": mse,
        "dm_vs_gjr": {
            "MEM": dm_test(qlike_series["MEM"], qlike_series["GJR"]),
            "AMEM": dm_test(qlike_series["AMEM"], qlike_series["GJR"]),
        },
        "oos_n": int(len(actual)),
    }


def decide_verdict(results: dict[str, dict[str, object]]) -> tuple[dict[str, int], str, str]:
    mem_pass = sum(results[asset]["qlike"]["MEM"] < results[asset]["qlike"]["GJR"] for asset in results)
    amem_pass = sum(results[asset]["qlike"]["AMEM"] < results[asset]["qlike"]["GJR"] for asset in results)
    best_pass = max(mem_pass, amem_pass)

    if best_pass >= 2:
        verdict = "PASS"
    elif best_pass == 1:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    best_model = "MEM" if mem_pass >= amem_pass else "AMEM"
    key_finding = (
        f"{best_model} beats GJR on {best_pass}/3 assets by QLIKE; "
        f"MEM pass count={mem_pass}, AMEM pass count={amem_pass}."
    )
    gates = {"MEM_PASS_count": int(mem_pass), "AMEM_PASS_count": int(amem_pass), "total_assets": 3}
    return gates, verdict, key_finding


def build_readme(payload: dict[str, object]) -> str:
    results = payload["results"]
    lines = [
        f"# {payload['experiment_id']} — {payload['title']}",
        "",
        f"- Status: `{payload['verdict']}`",
        f"- Date: `{payload['date']}`",
        "- Motivation: MEM models directly target non-negative realized variance dynamics and let the conditional mean evolve through a persistence structure closer to variance processes than plain OLS. AMEM adds a downside asymmetry term so we can test whether negative-return days materially improve next-day volatility forecasts relative to symmetric MEM and standard GJR/HAR baselines.",
        f"- Method Summary: Daily log returns were computed from adjusted close prices for SPY, QQQ, and GLD, with realized variance defined as `RV_t = r_t^2`. Forecasts were evaluated in an expanding-window out-of-sample design with a 2000-observation initial window; HAR was refit by OLS each step, while MEM/AMEM/GJR parameters were refreshed every {REFIT_EVERY} OOS steps using the most recent {FIT_SAMPLE} training observations and cached state updates in between to keep the rolling experiment tractable without introducing lookahead.",
        "",
        "## Results",
        "",
        "| Asset | QLIKE MEM | QLIKE AMEM | QLIKE GJR | QLIKE HAR | MSE MEM | MSE AMEM | MSE GJR | MSE HAR | OOS N |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for asset in payload["assets"]:
        asset_result = results[asset]
        lines.append(
            "| {asset} | {mem_q:.6g} | {amem_q:.6g} | {gjr_q:.6g} | {har_q:.6g} | {mem_m:.6g} | {amem_m:.6g} | {gjr_m:.6g} | {har_m:.6g} | {oos_n} |".format(
                asset=asset,
                mem_q=asset_result["qlike"]["MEM"],
                amem_q=asset_result["qlike"]["AMEM"],
                gjr_q=asset_result["qlike"]["GJR"],
                har_q=asset_result["qlike"]["HAR"],
                mem_m=asset_result["mse"]["MEM"],
                amem_m=asset_result["mse"]["AMEM"],
                gjr_m=asset_result["mse"]["GJR"],
                har_m=asset_result["mse"]["HAR"],
                oos_n=asset_result["oos_n"],
            )
        )

    lines.extend(
        [
            "",
            "## DM Test vs GJR (QLIKE loss differential)",
            "",
            "| Asset | MEM t-stat | MEM p-value | AMEM t-stat | AMEM p-value |",
            "|---|---:|---:|---:|---:|",
        ]
    )

    for asset in payload["assets"]:
        dm = results[asset]["dm_vs_gjr"]
        lines.append(
            "| {asset} | {mem_t:.4f} | {mem_p:.4f} | {amem_t:.4f} | {amem_p:.4f} |".format(
                asset=asset,
                mem_t=dm["MEM"]["t_stat"],
                mem_p=dm["MEM"]["p_value"],
                amem_t=dm["AMEM"]["t_stat"],
                amem_p=dm["AMEM"]["p_value"],
            )
        )

    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            (
                f"{payload['key_finding']} Verdict rule outcome: `{payload['verdict']}`. "
                "This experiment should be treated as a direct forecasting comparison under the specified rolling protocol, not as structural evidence that MEM-family models dominate in all volatility settings."
            ),
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    results = {}
    for config in ASSETS:
        asset_df = load_asset_series(config)
        results[config.name] = evaluate_asset(config.name, asset_df)

    gates, verdict, key_finding = decide_verdict(results)
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "title": TITLE,
        "description": (
            "Compare rolling 1-step-ahead daily volatility forecasts from MEM(1,1) and AMEM(1,1) "
            "against GJR-GARCH(1,1) and HAR baselines on SPY, QQQ, and GLD using realized variance from squared log returns."
        ),
        "date": str(date.today()),
        "assets": [config.name for config in ASSETS],
        "window": WINDOW,
        "models": ["MEM", "AMEM", "GJR", "HAR"],
        "results": results,
        "gates": gates,
        "verdict": verdict,
        "key_finding": key_finding,
        "reviewer": None,
        "experiment_path": "experiments/k1398/",
    }

    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    README_PATH.write_text(build_readme(payload), encoding="utf-8")
    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {README_PATH}")


if __name__ == "__main__":
    main()
