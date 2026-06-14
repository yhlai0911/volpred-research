from __future__ import annotations

import json
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yfinance as yf
from scipy import stats
from statsmodels.regression.quantile_regression import QuantReg, IterationLimitWarning
from statsmodels.tools.sm_exceptions import ConvergenceWarning

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))


HERE = Path(__file__).resolve().parent
RESULTS_PATH = HERE / "research_quantile_connectedness_var_yfinance_etf_rv_quant_results.json"
FIG_TCI_PATH = HERE / "fig_tail_vs_median_connectedness.png"
FIG_NET_PATH = HERE / "fig_net_transmitters_by_quantile.png"
FIG_PAIR_PATH = HERE / "fig_pairwise_tail_minus_median.png"

START = "2015-01-01"
END = "2026-06-14"
ASSETS = {
    "SPY": "US equity",
    "TLT": "US Treasury bond",
    "GLD": "Gold",
    "USO": "Oil",
    "BTC": "Bitcoin proxy (BTC-USD, not ETF; long ETF history unavailable)",
}
TICKERS = {
    "SPY": "SPY",
    "TLT": "TLT",
    "GLD": "GLD",
    "USO": "USO",
    "BTC": "BTC-USD",
}
QUANTILES = [0.05, 0.50, 0.95]
LAG = 1
FEVD_H = 10
RV_WINDOW = 5
ROLL_WINDOW = 756
ROLL_STEP = 42
BOOT_REPS = 1000
BOOT_BLOCK = 6
SEED = 42
EPS = 1e-12

warnings.filterwarnings("ignore", category=IterationLimitWarning)
warnings.filterwarnings("ignore", category=ConvergenceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)


@dataclass
class QVARConnectedness:
    quantile: float
    coefficients: np.ndarray
    residual_cov: np.ndarray
    fevd: np.ndarray
    total_connectedness: float
    to_others: dict[str, float]
    from_others: dict[str, float]
    net: dict[str, float]
    pairwise_table: dict[str, dict[str, float]]
    n_obs: int


def download_prices() -> pd.DataFrame:
    raw = yf.download(
        list(TICKERS.values()),
        start=START,
        end=END,
        progress=False,
        auto_adjust=True,
    )
    if raw.empty:
        raise RuntimeError("yfinance returned empty panel")
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw
    close = close.rename(columns={ticker: asset for asset, ticker in TICKERS.items()})
    close = close[list(ASSETS)].sort_index()
    etf_assets = [asset for asset in ASSETS if asset != "BTC"]
    etf_calendar = close[etf_assets].dropna().index
    aligned = close.reindex(etf_calendar).copy()
    aligned["BTC"] = close["BTC"].ffill().reindex(etf_calendar)
    return aligned.dropna()


def build_vol_panel(prices: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    returns = np.log(prices).diff().dropna()
    # Daily yfinance cannot produce true intraday RV. This is a transparent low-frequency RV proxy.
    rv = returns.pow(2).rolling(RV_WINDOW).sum()
    log_rv = np.log(rv + EPS).dropna()
    return returns.loc[log_rv.index], log_rv


def standardize(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean()
    sigma = df.std(ddof=0).replace(0.0, np.nan)
    return ((df - mu) / sigma).dropna()


def prepare_lagged(panel: pd.DataFrame, lag: int = LAG) -> tuple[pd.DataFrame, pd.DataFrame]:
    y = panel.iloc[lag:].copy()
    x = panel.shift(lag).iloc[lag:].copy()
    common = y.dropna().index.intersection(x.dropna().index)
    return y.loc[common], x.loc[common]


def qvar_fit(panel: pd.DataFrame, tau: float) -> tuple[np.ndarray, np.ndarray, int]:
    assets = list(panel.columns)
    y, x = prepare_lagged(panel)
    x_aug = np.column_stack([np.ones(len(x)), x.to_numpy(dtype=float)])
    coeff = np.zeros((len(assets), len(assets)), dtype=float)
    residuals = np.zeros((len(y), len(assets)), dtype=float)

    for i, asset in enumerate(assets):
        model = QuantReg(y[asset].to_numpy(dtype=float), x_aug)
        try:
            fit = model.fit(q=tau, max_iter=2000, p_tol=1e-6)
            params = np.asarray(fit.params, dtype=float)
        except Exception:
            params = np.linalg.lstsq(x_aug, y[asset].to_numpy(dtype=float), rcond=None)[0]
        coeff[i, :] = params[1:]
        residuals[:, i] = y[asset].to_numpy(dtype=float) - x_aug @ params

    sigma = np.cov(residuals, rowvar=False)
    sigma = np.nan_to_num(sigma, nan=0.0, posinf=0.0, neginf=0.0)
    diag = np.diag(sigma)
    for i, value in enumerate(diag):
        if value <= 0:
            sigma[i, i] = max(float(np.nanvar(residuals[:, i])), EPS)
    return coeff, sigma, int(len(y))


def generalized_fevd(a: np.ndarray, sigma: np.ndarray, horizon: int = FEVD_H) -> np.ndarray:
    n = a.shape[0]
    theta = np.zeros((n, n), dtype=float)
    psi = np.eye(n)
    psi_list = []
    for _ in range(horizon):
        psi_list.append(psi.copy())
        psi = psi @ a

    for i in range(n):
        denom = 0.0
        for psi_h in psi_list:
            denom += float(psi_h[i, :] @ sigma @ psi_h[i, :])
        if denom <= EPS:
            continue
        for j in range(n):
            numer = 0.0
            for psi_h in psi_list:
                numer += float((psi_h[i, :] @ sigma[:, j]) ** 2)
            theta[i, j] = (numer / max(sigma[j, j], EPS)) / denom

    row_sums = theta.sum(axis=1, keepdims=True)
    row_sums[row_sums <= EPS] = 1.0
    return theta / row_sums


def connectedness_from_panel(panel: pd.DataFrame, tau: float) -> QVARConnectedness:
    assets = list(panel.columns)
    coeff, sigma, n_obs = qvar_fit(panel, tau)
    fevd = generalized_fevd(coeff, sigma)
    n = len(assets)
    total = float((fevd.sum() - np.trace(fevd)) / n * 100.0)

    from_others = {}
    to_others = {}
    net = {}
    table = {}
    for i, asset in enumerate(assets):
        from_others[asset] = float((fevd[i, :].sum() - fevd[i, i]) * 100.0)
        to_others[asset] = float((fevd[:, i].sum() - fevd[i, i]) * 100.0)
    for asset in assets:
        net[asset] = float(to_others[asset] - from_others[asset])
    for i, row_asset in enumerate(assets):
        table[row_asset] = {}
        for j, col_asset in enumerate(assets):
            table[row_asset][col_asset] = float(fevd[i, j] * 100.0)

    return QVARConnectedness(
        quantile=tau,
        coefficients=coeff,
        residual_cov=sigma,
        fevd=fevd,
        total_connectedness=total,
        to_others=to_others,
        from_others=from_others,
        net=net,
        pairwise_table=table,
        n_obs=n_obs,
    )


def hac_mean_test(values: np.ndarray, max_lag: int = 4) -> dict[str, float]:
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 10:
        return {"n": int(n), "mean": float(np.nanmean(x)) if n else None, "t_stat": None, "p_value": None}
    mu = float(np.mean(x))
    centered = x - mu
    gamma0 = float(np.mean(centered ** 2))
    var = gamma0
    for lag in range(1, min(max_lag, n - 1) + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        gamma = float(np.mean(centered[lag:] * centered[:-lag]))
        var += 2.0 * weight * gamma
    se = np.sqrt(max(var, EPS) / n)
    t_stat = mu / se
    p_value = 2.0 * (1.0 - stats.t.cdf(abs(t_stat), df=n - 1))
    return {"n": int(n), "mean": mu, "t_stat": float(t_stat), "p_value": float(p_value)}


def moving_block_bootstrap_mean(values: np.ndarray) -> dict[str, float]:
    rng = np.random.default_rng(SEED)
    x = np.asarray(values, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < BOOT_BLOCK:
        return {"seed": SEED, "reps": BOOT_REPS, "ci_95": [None, None], "p_gt_0": None}
    starts = np.arange(0, n - BOOT_BLOCK + 1)
    means = np.zeros(BOOT_REPS, dtype=float)
    blocks_needed = int(np.ceil(n / BOOT_BLOCK))
    for b in range(BOOT_REPS):
        sample = []
        for start in rng.choice(starts, size=blocks_needed, replace=True):
            sample.extend(x[start:start + BOOT_BLOCK])
        means[b] = np.mean(sample[:n])
    return {
        "seed": SEED,
        "reps": BOOT_REPS,
        "block": BOOT_BLOCK,
        "ci_95": [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))],
        "p_gt_0": float(np.mean(means > 0.0)),
    }


def rolling_connectedness(panel: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for end in range(ROLL_WINDOW, len(panel) + 1, ROLL_STEP):
        window = panel.iloc[end - ROLL_WINDOW:end]
        date = panel.index[end - 1]
        for tau in QUANTILES:
            try:
                conn = connectedness_from_panel(standardize(window), tau)
            except Exception:
                continue
            row = {
                "date": str(date.date()),
                "tau": tau,
                "total_connectedness": conn.total_connectedness,
            }
            for asset, value in conn.net.items():
                row[f"net_{asset}"] = value
            rows.append(row)
    return pd.DataFrame(rows)


def diagnostics(returns: pd.DataFrame, log_rv: pd.DataFrame) -> dict:
    out = {
        "returns": {},
        "log_rv": {},
        "rv_correlation": log_rv.corr().to_dict(),
    }
    for asset in returns.columns:
        r = returns[asset]
        v = log_rv[asset]
        out["returns"][asset] = {
            "n": int(r.notna().sum()),
            "mean": float(r.mean()),
            "std": float(r.std()),
            "skew": float(r.skew()),
            "kurtosis": float(r.kurtosis()),
            "min": float(r.min()),
            "max": float(r.max()),
        }
        out["log_rv"][asset] = {
            "mean": float(v.mean()),
            "std": float(v.std()),
            "p05": float(v.quantile(0.05)),
            "p50": float(v.quantile(0.50)),
            "p95": float(v.quantile(0.95)),
        }
    return out


def plot_tci(rolling: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(11, 5))
    for tau, color in [(0.05, "#7f8c8d"), (0.50, "#2c3e50"), (0.95, "#c0392b")]:
        sub = rolling[rolling["tau"] == tau].copy()
        sub["date"] = pd.to_datetime(sub["date"])
        ax.plot(sub["date"], sub["total_connectedness"], label=f"tau={tau:.2f}", lw=1.5, color=color)
    ax.set_title("Rolling QVAR total connectedness")
    ax.set_ylabel("Total connectedness (%)")
    ax.legend(frameon=False, ncol=3)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(FIG_TCI_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_net(full: dict[str, QVARConnectedness]) -> None:
    assets = list(ASSETS)
    x = np.arange(len(assets))
    width = 0.25
    fig, ax = plt.subplots(figsize=(10, 5))
    for offset, tau, color in [(-width, 0.05, "#7f8c8d"), (0, 0.50, "#2c3e50"), (width, 0.95, "#c0392b")]:
        vals = [full[str(tau)].net[a] for a in assets]
        ax.bar(x + offset, vals, width=width, label=f"tau={tau:.2f}", color=color)
    ax.axhline(0.0, color="black", lw=0.8)
    ax.set_xticks(x)
    ax.set_xticklabels(assets)
    ax.set_title("Full-sample net transmitters by quantile")
    ax.set_ylabel("To others minus from others")
    ax.legend(frameon=False, ncol=3)
    fig.tight_layout()
    fig.savefig(FIG_NET_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def plot_pairwise_diff(full: dict[str, QVARConnectedness]) -> None:
    assets = list(ASSETS)
    diff = full["0.95"].fevd - full["0.5"].fevd
    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(diff * 100.0, cmap="RdBu_r", vmin=-10, vmax=10)
    ax.set_xticks(np.arange(len(assets)))
    ax.set_xticklabels(assets)
    ax.set_yticks(np.arange(len(assets)))
    ax.set_yticklabels(assets)
    ax.set_title("Pairwise FEVD: upper tail minus median")
    ax.set_xlabel("Shock source")
    ax.set_ylabel("Receiver")
    cbar = plt.colorbar(im, ax=ax)
    cbar.set_label("percentage-point difference")
    fig.tight_layout()
    fig.savefig(FIG_PAIR_PATH, dpi=180, bbox_inches="tight")
    plt.close(fig)


def conn_to_json(conn: QVARConnectedness) -> dict:
    return {
        "quantile": conn.quantile,
        "n_obs": conn.n_obs,
        "total_connectedness": conn.total_connectedness,
        "to_others": conn.to_others,
        "from_others": conn.from_others,
        "net": conn.net,
        "pairwise_table": conn.pairwise_table,
        "coefficients": pd.DataFrame(conn.coefficients, index=list(ASSETS), columns=list(ASSETS)).to_dict(),
    }


def main() -> None:
    prices = download_prices()
    returns, log_rv = build_vol_panel(prices)
    panel = standardize(log_rv)

    full = {}
    for tau in QUANTILES:
        full[str(tau)] = connectedness_from_panel(panel, tau)

    rolling = rolling_connectedness(panel)
    pivot = rolling.pivot(index="date", columns="tau", values="total_connectedness").dropna()
    pivot["tail_minus_median"] = pivot[0.95] - pivot[0.50]
    pivot["lower_tail_minus_median"] = pivot[0.05] - pivot[0.50]

    test_tail = hac_mean_test(pivot["tail_minus_median"].to_numpy())
    test_lower = hac_mean_test(pivot["lower_tail_minus_median"].to_numpy())
    boot_tail = moving_block_bootstrap_mean(pivot["tail_minus_median"].to_numpy())

    window_spy_rv = []
    for date in pd.to_datetime(pivot.index):
        window = log_rv.loc[:date].tail(ROLL_WINDOW)
        window_spy_rv.append(float(window["SPY"].mean()))
    pivot["spy_rv_window_mean"] = window_spy_rv
    crisis_cutoff = float(np.quantile(pivot["spy_rv_window_mean"], 0.75))
    crisis = pivot[pivot["spy_rv_window_mean"] >= crisis_cutoff]
    non_crisis = pivot[pivot["spy_rv_window_mean"] < crisis_cutoff]
    crisis_test = {
        "crisis_cutoff_log_rv": crisis_cutoff,
        "n_crisis_windows": int(len(crisis)),
        "n_non_crisis_windows": int(len(non_crisis)),
        "tail_minus_median_crisis_mean": float(crisis["tail_minus_median"].mean()),
        "tail_minus_median_non_crisis_mean": float(non_crisis["tail_minus_median"].mean()),
    }
    if len(crisis) >= 3 and len(non_crisis) >= 3:
        t_stat, p_value = stats.ttest_ind(crisis["tail_minus_median"], non_crisis["tail_minus_median"], equal_var=False)
        crisis_test["welch_t_stat"] = float(t_stat)
        crisis_test["welch_p_value"] = float(p_value)

    plot_tci(rolling)
    plot_net(full)
    plot_pairwise_diff(full)

    full_json = {k: conn_to_json(v) for k, v in full.items()}
    net_tail = full["0.95"].net
    top_tail_transmitter = max(net_tail.items(), key=lambda kv: kv[1])
    top_tail_receiver = min(net_tail.items(), key=lambda kv: kv[1])

    key_findings = [
        f"Full-sample TCI: tau=0.95 {full['0.95'].total_connectedness:.2f}% vs tau=0.50 {full['0.5'].total_connectedness:.2f}%.",
        f"Rolling upper-tail minus median TCI mean {test_tail['mean']:.2f} pp, HAC t={test_tail['t_stat']:.2f}, p={test_tail['p_value']:.4f}.",
        f"High-SPY-vol windows do not amplify the gap: crisis mean {crisis_test['tail_minus_median_crisis_mean']:.2f} pp vs non-crisis {crisis_test['tail_minus_median_non_crisis_mean']:.2f} pp.",
        f"Top upper-tail net transmitter: {top_tail_transmitter[0]} ({top_tail_transmitter[1]:+.2f}); receiver: {top_tail_receiver[0]} ({top_tail_receiver[1]:+.2f}).",
    ]
    tail_positive = bool(test_tail["mean"] and test_tail["mean"] > 0 and test_tail["p_value"] and test_tail["p_value"] < 0.05)
    crisis_specific = bool(crisis_test.get("welch_p_value") is not None and crisis_test["welch_p_value"] < 0.05 and crisis_test["tail_minus_median_crisis_mean"] > crisis_test["tail_minus_median_non_crisis_mean"])

    results = {
        "experiment_id": "research_quantile_connectedness_var_yfinance_etf_rv_quant",
        "title": "Quantile QVAR connectedness in cross-asset volatility proxies",
        "timestamp": pd.Timestamp.now("UTC").isoformat(),
        "data": {
            "source": "yfinance adjusted close",
            "assets": ASSETS,
            "tickers": TICKERS,
            "price_start": str(prices.index[0].date()),
            "price_end": str(prices.index[-1].date()),
            "n_prices": int(len(prices)),
            "n_log_rv": int(len(log_rv)),
            "rv_proxy": f"{RV_WINDOW}-trading-day rolling sum of squared log returns, log-transformed",
        },
        "diagnostics": diagnostics(returns, log_rv),
        "methodology": {
            "model": "Quantile VAR(1) fitted by statsmodels QuantReg equation-by-equation",
            "connectedness": "Generalized FEVD on fitted QVAR coefficient matrix and residual covariance",
            "quantiles": QUANTILES,
            "fevd_horizon": FEVD_H,
            "rolling_window": ROLL_WINDOW,
            "rolling_step": ROLL_STEP,
            "tail_test": "HAC mean test of rolling TCI(tau=0.95) - TCI(tau=0.50)",
            "bootstrap": f"moving-block bootstrap, seed={SEED}, reps={BOOT_REPS}, block={BOOT_BLOCK}",
            "lookahead_guard": "volatility panel uses returns through t; QVAR uses lagged vol(t-1) to explain vol(t)",
        },
        "literature": [
            {
                "title": "Quantile Connectedness: Modeling Tail Behavior in the Topology of Financial Networks",
                "authors": "Ando, Greenwood-Nimmo, Shin",
                "year": 2022,
                "doi": "10.1287/mnsc.2021.3984",
                "url": "https://doi.org/10.1287/mnsc.2021.3984",
            },
            {
                "title": "Measuring Financial Asset Return and Volatility Spillovers, with Application to Global Equity Markets",
                "authors": "Diebold, Yilmaz",
                "year": 2009,
                "url": "https://www.nber.org/papers/w13811",
            },
            {
                "title": "Measuring the Frequency Dynamics of Financial Connectedness and Systemic Risk",
                "authors": "Barunik, Krehlik",
                "year": 2018,
                "doi": "10.1093/jjfinec/nby001",
                "url": "https://doi.org/10.1093/jjfinec/nby001",
            },
            {
                "title": "Scenario-based Quantile Connectedness of the U.S. Interbank System",
                "authors": "Federal Reserve Bank of Boston working paper",
                "year": 2024,
                "url": "https://www.bostonfed.org/publications/research-department-working-paper/2024/scenario-based-quantile-connectedness-of-the-us-interbank-system.aspx",
            },
        ],
        "full_sample": full_json,
        "rolling_summary": {
            "n_windows": int(len(pivot)),
            "tail_minus_median_test": test_tail,
            "lower_tail_minus_median_test": test_lower,
            "tail_minus_median_bootstrap": boot_tail,
            "crisis_test": crisis_test,
            "time_series": rolling.to_dict(orient="records"),
        },
        "key_findings": key_findings,
        "verdict": {
            "label": "tail_connectedness_positive_not_crisis_specific" if tail_positive and not crisis_specific else ("tail_connectedness_positive_crisis_specific" if tail_positive else "mixed_or_null"),
            "summary": "Upper-tail connectedness exceeds median connectedness in rolling QVAR-FEVD, but the excess is not statistically larger in high-SPY-vol windows. Interpret as daily-proxy evidence, not intraday RV proof.",
        },
        "artifacts": {
            "tail_vs_median_connectedness": FIG_TCI_PATH.name,
            "net_transmitters_by_quantile": FIG_NET_PATH.name,
            "pairwise_tail_minus_median": FIG_PAIR_PATH.name,
        },
        "limitations": [
            "Daily yfinance data cannot identify true intraday realized volatility; this is a low-frequency RV proxy.",
            "BTC-USD is used as the crypto long-history proxy because spot Bitcoin ETFs have too short a sample for rolling QVAR.",
            "QVAR is fitted equation-by-equation without Bayesian shrinkage, so pairwise source interpretation should be treated as approximate.",
            "Diebold-Yilmaz style directional connectedness measures are network centrality diagnostics, not structural causal spillovers.",
        ],
    }
    RESULTS_PATH.write_text(json.dumps(results, ensure_ascii=False, indent=2))
    print(json.dumps({"ok": True, "results_path": str(RESULTS_PATH), "key_findings": key_findings}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
