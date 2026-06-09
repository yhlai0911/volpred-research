"""K1443: BTC / ETH vs SPY volatility spillover on an SPY-trading-day panel.

Question:
    Do BTC and ETH volatility innovations lead or lag SPY volatility?

Design:
    1. Use local cached daily close snapshots only (no live downloads).
    2. Align all assets to the SPY trading-day calendar.
    3. Crypto returns are measured between adjacent SPY trading days, so Monday's
       crypto interval naturally includes weekend moves.
    4. Main spillover test uses log(r_t^2 + eps) to avoid overlapping-window
       inference issues. 21-day realized vol is reported descriptively and as a
       robustness check.
    5. Pairwise VAR/Granger in both directions plus a 3-variable conditional VAR.
    6. Pairwise DCC-GARCH on returns for BTC-SPY and ETH-SPY.

Research-honesty guard:
    The main target is a daily volatility-shock proxy, not intraday realized
    volatility. This is deliberate because the available local crypto/SPY data
    are daily closes only.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from arch import arch_model
from scipy import optimize
from scipy.stats import jarque_bera
from statsmodels.tsa.api import VAR
from statsmodels.tsa.stattools import adfuller, grangercausalitytests

SEED = 42
ROOT = Path(__file__).resolve().parent
FIG_DIR = ROOT / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)

DATA_PATHS = {
    "BTC-USD": Path("experiments/k1206/data/BTC_USD.csv"),
    "ETH-USD": Path("experiments/k1090b/data/ETH-USD.csv"),
    "SPY": Path("experiments/k1406/data/SPY.csv"),
}

START = "2018-01-02"
END = "2026-04-16"
RV_WINDOW = 21
MAX_LAG = 5
DCC_MAX_N = 1000


def _load_close(path: Path, label: str) -> pd.Series:
    df = pd.read_csv(path)
    date_col = "Date" if "Date" in df.columns else df.columns[0]
    close_col = "Adj Close" if "Adj Close" in df.columns else "Close"
    out = (
        df[[date_col, close_col]]
        .rename(columns={date_col: "date", close_col: label})
        .dropna()
    )
    out["date"] = pd.to_datetime(out["date"])
    out = out.drop_duplicates("date", keep="last").set_index("date").sort_index()
    return out[label]


def load_panel() -> tuple[pd.DataFrame, dict[str, Any]]:
    btc = _load_close(DATA_PATHS["BTC-USD"], "BTC-USD")
    eth = _load_close(DATA_PATHS["ETH-USD"], "ETH-USD")
    spy = _load_close(DATA_PATHS["SPY"], "SPY")

    spy = spy.loc[START:END]
    btc = btc.loc[START:END]
    eth = eth.loc[START:END]

    panel = pd.concat(
        [
            spy.rename("SPY"),
            btc.reindex(spy.index).rename("BTC-USD"),
            eth.reindex(spy.index).rename("ETH-USD"),
        ],
        axis=1,
    ).dropna()

    meta = {
        "calendar": "SPY trading days; BTC/ETH sampled on SPY dates",
        "sample_start": str(panel.index[0].date()),
        "sample_end": str(panel.index[-1].date()),
        "n_obs_prices": int(len(panel)),
        "source_files": {k: str(v) for k, v in DATA_PATHS.items()},
    }
    return panel, meta


def build_features(panel: pd.DataFrame) -> pd.DataFrame:
    ret = np.log(panel / panel.shift(1))
    ret.columns = [f"{c}_ret" for c in panel.columns]

    feat = ret.copy()
    eps = 1e-10
    for asset in panel.columns:
        r = ret[f"{asset}_ret"]
        feat[f"{asset}_logrv1"] = np.log(r.pow(2) + eps)
        feat[f"{asset}_rv21"] = np.sqrt(r.pow(2).rolling(RV_WINDOW).sum() * (252 / RV_WINDOW))
    return feat.dropna().copy()


def series_diagnostics(feat: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col in [c for c in feat.columns if c.endswith(("ret", "logrv1", "rv21"))]:
        s = feat[col].dropna()
        jb_stat, jb_p = jarque_bera(s)
        adf_stat, adf_p, *_ = adfuller(s, autolag="AIC")
        out[col] = {
            "mean": float(s.mean()),
            "std": float(s.std()),
            "skew": float(s.skew()),
            "kurt": float(s.kurt()),
            "jarque_bera_stat": float(jb_stat),
            "jarque_bera_p": float(jb_p),
            "adf_stat": float(adf_stat),
            "adf_p": float(adf_p),
            "n": int(s.shape[0]),
        }
    return out


def _granger_pair(df: pd.DataFrame, y: str, x: str, max_lag: int = MAX_LAG) -> dict[str, Any]:
    g = grangercausalitytests(df[[y, x]], maxlag=max_lag, verbose=False)
    best_lag = min(g.keys(), key=lambda lag: g[lag][0]["ssr_ftest"][1])
    f_stat, p_value, df1, df2 = g[best_lag][0]["ssr_ftest"]
    return {
        "best_lag_by_min_p": int(best_lag),
        "F": float(f_stat),
        "p_value": float(p_value),
        "all_lags": {
            str(lag): {
                "F": float(g[lag][0]["ssr_ftest"][0]),
                "p_value": float(g[lag][0]["ssr_ftest"][1]),
            }
            for lag in sorted(g)
        },
    }


def pairwise_spillover(feat: pd.DataFrame, asset: str, vol_col: str) -> dict[str, Any]:
    pair = feat[[f"{asset}_{vol_col}", f"SPY_{vol_col}"]].dropna()
    pair.columns = [asset, "SPY"]
    var_model = VAR(pair)
    selection = var_model.select_order(MAX_LAG)
    p_bic = int(selection.bic)
    p_bic = 1 if p_bic < 1 else p_bic
    res = var_model.fit(p_bic)
    return {
        "var_p_bic": p_bic,
        "n_obs": int(res.nobs),
        "aic": float(res.aic),
        "bic": float(res.bic),
        f"{asset}_to_SPY": _granger_pair(pair, "SPY", asset, MAX_LAG),
        f"SPY_to_{asset}": _granger_pair(pair, asset, "SPY", MAX_LAG),
    }


def conditional_var(feat: pd.DataFrame) -> dict[str, Any]:
    cols = ["BTC-USD_logrv1", "ETH-USD_logrv1", "SPY_logrv1"]
    data = feat[cols].dropna().copy()
    data.columns = ["BTC", "ETH", "SPY"]
    model = VAR(data)
    selection = model.select_order(MAX_LAG)
    p_bic = int(selection.bic)
    p_bic = 1 if p_bic < 1 else p_bic
    res = model.fit(p_bic)

    def _caused(caused: str, causing: list[str]) -> dict[str, float]:
        test = res.test_causality(caused=caused, causing=causing, kind="f")
        return {
            "stat": float(test.test_statistic),
            "p_value": float(test.pvalue),
            "df": str(test.df),
        }

    return {
        "var_p_bic": p_bic,
        "n_obs": int(res.nobs),
        "aic": float(res.aic),
        "bic": float(res.bic),
        "tests": {
            "BTC_to_SPY_cond_on_ETH": _caused("SPY", ["BTC"]),
            "ETH_to_SPY_cond_on_BTC": _caused("SPY", ["ETH"]),
            "SPY_to_BTC_cond_on_ETH": _caused("BTC", ["SPY"]),
            "SPY_to_ETH_cond_on_BTC": _caused("ETH", ["SPY"]),
            "BTC_ETH_joint_to_SPY": _caused("SPY", ["BTC", "ETH"]),
        },
    }


def fit_gjr_garch(ret: pd.Series, label: str) -> dict[str, Any]:
    am = arch_model(
        ret * 100.0,
        mean="Constant",
        vol="GARCH",
        p=1,
        o=1,
        q=1,
        dist="t",
        rescale=False,
    )
    res = am.fit(disp="off", show_warning=False)
    sigma = res.conditional_volatility
    std_resid = ((ret * 100.0) - res.params["mu"]) / sigma
    return {
        "label": label,
        "params": {k: float(v) for k, v in res.params.items()},
        "aic": float(res.aic),
        "bic": float(res.bic),
        "loglik": float(res.loglikelihood),
        "converged": bool(res.convergence_flag == 0),
        "sigma": sigma,
        "std_resid": std_resid,
    }


def _dcc_nll(params: np.ndarray, eps: np.ndarray) -> float:
    a, b = params
    if a < 0 or b < 0 or a + b >= 0.9999:
        return 1e10
    qbar = np.cov(eps.T, ddof=0)
    q = qbar.copy()
    nll = 0.0
    for t in range(1, eps.shape[0]):
        et_1 = eps[t - 1][:, None]
        q = (1.0 - a - b) * qbar + a * (et_1 @ et_1.T) + b * q
        d = np.sqrt(np.diag(q))
        if np.any(d <= 0):
            return 1e10
        r = q / np.outer(d, d)
        det_r = np.linalg.det(r)
        if det_r <= 0:
            return 1e10
        inv_r = np.linalg.inv(r)
        e = eps[t][:, None]
        quad = (e.T @ (inv_r - np.eye(2)) @ e).item()
        nll += np.log(det_r) + float(quad)
    return 0.5 * nll


def fit_dcc(pair_rets: pd.DataFrame) -> dict[str, Any]:
    if len(pair_rets) > DCC_MAX_N:
        pair_rets = pair_rets.iloc[-DCC_MAX_N:].copy()
    gjr1 = fit_gjr_garch(pair_rets.iloc[:, 0], pair_rets.columns[0])
    gjr2 = fit_gjr_garch(pair_rets.iloc[:, 1], pair_rets.columns[1])
    eps = np.column_stack([gjr1["std_resid"], gjr2["std_resid"]])

    starts = [np.array([0.02, 0.95]), np.array([0.05, 0.90]), np.array([0.10, 0.85])]

    best = None
    successes = []
    for x0 in starts:
        res = optimize.minimize(
            _dcc_nll,
            x0=x0,
            args=(eps,),
            bounds=[(1e-4, 0.30), (0.60, 0.999)],
            method="L-BFGS-B",
            options={"maxiter": 80},
        )
        if res.success:
            successes.append(float(res.fun))
            if best is None or res.fun < best.fun:
                best = res

    if best is None:
        raise RuntimeError("DCC optimization failed for all starts")

    a, b = map(float, best.x)
    qbar = np.cov(eps.T, ddof=0)
    q = qbar.copy()
    rho = [np.nan]
    for t in range(1, eps.shape[0]):
        et_1 = eps[t - 1][:, None]
        q = (1.0 - a - b) * qbar + a * (et_1 @ et_1.T) + b * q
        d = np.sqrt(np.diag(q))
        r = q / np.outer(d, d)
        rho.append(float(r[0, 1]))
    rho_s = pd.Series(rho, index=pair_rets.index)
    return {
        "alpha": a,
        "beta": b,
        "persistence": a + b,
        "best_fun": float(best.fun),
        "n_successful_starts": len(successes),
        "n_total_starts": len(starts),
        "rho_summary": {
            "mean": float(rho_s.mean()),
            "std": float(rho_s.std()),
            "min": float(rho_s.min()),
            "max": float(rho_s.max()),
            "p10": float(rho_s.quantile(0.10)),
            "p90": float(rho_s.quantile(0.90)),
        },
        "n_obs_dcc": int(len(pair_rets)),
        "rho_series": rho_s,
        "gjr": {
            pair_rets.columns[0]: {k: v for k, v in gjr1.items() if k not in {"sigma", "std_resid"}},
            pair_rets.columns[1]: {k: v for k, v in gjr2.items() if k not in {"sigma", "std_resid"}},
        },
    }


def make_figures(feat: pd.DataFrame, dcc_results: dict[str, Any]) -> list[str]:
    rv = feat[["BTC-USD_rv21", "ETH-USD_rv21", "SPY_rv21"]].rename(
        columns={
            "BTC-USD_rv21": "BTC",
            "ETH-USD_rv21": "ETH",
            "SPY_rv21": "SPY",
        }
    )

    fig1 = FIG_DIR / "rv21_timeseries.png"
    plt.figure(figsize=(12, 5))
    rv.plot(ax=plt.gca(), linewidth=1.2)
    plt.title("K1443 — 21-day realized volatility on SPY trading-day panel")
    plt.ylabel("Annualized volatility")
    plt.tight_layout()
    plt.savefig(fig1, dpi=160)
    plt.close()

    fig2 = FIG_DIR / "dcc_correlations.png"
    plt.figure(figsize=(12, 5))
    for key, color in [("BTC-USD_vs_SPY", "#f7931a"), ("ETH-USD_vs_SPY", "#627eea")]:
        dcc_results[key]["rho_series"].plot(label=key.replace("_vs_", " / "), linewidth=1.1, color=color)
    plt.axhline(0.0, color="black", linewidth=0.8, linestyle="--")
    plt.title("K1443 — Pairwise DCC correlations")
    plt.ylabel("Conditional correlation")
    plt.legend()
    plt.tight_layout()
    plt.savefig(fig2, dpi=160)
    plt.close()
    return [fig1.name, fig2.name]


def to_jsonable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_jsonable(v) for v in obj]
    if isinstance(obj, pd.Series):
        return {str(k): to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, np.generic):
        return obj.item()
    return obj


def summarize_verdict(pairwise_logrv: dict[str, Any], cond: dict[str, Any]) -> dict[str, Any]:
    btc_to_spy = pairwise_logrv["BTC-USD"][f"BTC-USD_to_SPY"]["p_value"]
    spy_to_btc = pairwise_logrv["BTC-USD"]["SPY_to_BTC-USD"]["p_value"]
    eth_to_spy = pairwise_logrv["ETH-USD"][f"ETH-USD_to_SPY"]["p_value"]
    spy_to_eth = pairwise_logrv["ETH-USD"]["SPY_to_ETH-USD"]["p_value"]
    joint = cond["tests"]["BTC_ETH_joint_to_SPY"]["p_value"]

    if joint < 0.05 and min(btc_to_spy, eth_to_spy) < 0.05:
        leader = "crypto_leads_spy"
    elif min(spy_to_btc, spy_to_eth) < 0.05 and min(btc_to_spy, eth_to_spy) >= 0.05:
        leader = "spy_leads_crypto"
    else:
        leader = "mixed_or_no_clear_leader"

    return {
        "lead_lag_classification": leader,
        "pairwise_p_values": {
            "BTC_to_SPY": btc_to_spy,
            "SPY_to_BTC": spy_to_btc,
            "ETH_to_SPY": eth_to_spy,
            "SPY_to_ETH": spy_to_eth,
            "BTC_ETH_joint_to_SPY": joint,
        },
    }


def main() -> None:
    panel, meta = load_panel()
    feat = build_features(panel)
    diagnostics = series_diagnostics(feat)

    pairwise_logrv = {
        asset: pairwise_spillover(feat, asset, "logrv1")
        for asset in ["BTC-USD", "ETH-USD"]
    }
    pairwise_rv21 = {
        asset: pairwise_spillover(feat, asset, "rv21")
        for asset in ["BTC-USD", "ETH-USD"]
    }
    conditional = conditional_var(feat)

    dcc_results: dict[str, Any] = {}
    for asset in ["BTC-USD", "ETH-USD"]:
        pair_rets = feat[[f"{asset}_ret", "SPY_ret"]].dropna().copy()
        pair_rets.columns = [asset, "SPY"]
        dcc_results[f"{asset}_vs_SPY"] = fit_dcc(pair_rets)

    figures = make_figures(feat, dcc_results)
    verdict = summarize_verdict(pairwise_logrv, conditional)

    results = {
        "title": "BTC / ETH vs SPY volatility spillover on an SPY-trading-day panel",
        "experiment_id": "K1443",
        "seed": SEED,
        "sample": meta,
        "method": {
            "main_vol_proxy": "log(r_t^2 + 1e-10) on adjacent-SPY-day returns",
            "descriptive_vol_proxy": "21-day backward-looking realized volatility from sampled returns",
            "max_granger_lag": MAX_LAG,
            "rv_window": RV_WINDOW,
            "dcc_subsample_n": DCC_MAX_N,
            "lookahead_guard": "All spillover tests use lagged values only; no same-day forward information.",
        },
        "diagnostics": diagnostics,
        "pairwise_logrv1_spillover": pairwise_logrv,
        "pairwise_rv21_spillover_robustness": pairwise_rv21,
        "conditional_var_logrv1": conditional,
        "dcc": {
            k: {
                kk: vv for kk, vv in v.items() if kk != "rho_series"
            }
            for k, v in dcc_results.items()
        },
        "verdict": verdict,
        "figures": figures,
    }

    (ROOT / "k1443_results.json").write_text(
        json.dumps(to_jsonable(results), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(verdict, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
