"""K1519: EPU as a cross-asset volatility-regime switching trigger.

Question:
  Does monthly Baker-Bloom-Davis EPU act as a lagged trigger for high-volatility
  regime entry in SPY and TAIEX, rather than as another linear incremental
  HAR/VIX predictor?

Design:
  - Fit a 2-state Markov switching model to daily log squared returns.
  - Use filtered high-volatility probabilities as realized state outcomes.
  - Build monthly EPU shocks from daily USEPUINDXD, published to the daily panel
    only after month-end + 2 business days.
  - Test whether lagged EPU shock days have higher high-regime probability,
    low-to-high transition probability, and log variance using HAC inference.
"""
from __future__ import annotations

import json
import time
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
import yfinance as yf
from pandas.tseries.offsets import BDay

warnings.filterwarnings("ignore", category=RuntimeWarning)

SEED = 42
START = "2000-01-01"
END = "2026-06-17"
HAC_LAGS = 21
MIN_EPU_HISTORY_MONTHS = 36
OUT_DIR = Path(__file__).parent
FIG_DIR = OUT_DIR / "figures"
FIG_DIR.mkdir(parents=True, exist_ok=True)


def fetch_price_series(ticker: str, label: str) -> pd.Series:
    for attempt in range(3):
        try:
            raw = yf.download(
                ticker,
                start=START,
                end=END,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if isinstance(raw.columns, pd.MultiIndex):
                raw.columns = raw.columns.get_level_values(0)
            close_col = "Close" if "Close" in raw.columns else "Adj Close"
            series = raw[close_col].dropna().rename(label)
            if len(series) > 500:
                return series
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {ticker} download attempt {attempt + 1}/3 failed: {exc}")
        time.sleep(1 + attempt)
    raise RuntimeError(f"failed to fetch {ticker}")


def load_epu_daily() -> pd.Series:
    try:
        url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=USEPUINDXD"
        epu = pd.read_csv(url, parse_dates=["observation_date"]).set_index("observation_date")["USEPUINDXD"]
        epu = pd.to_numeric(epu, errors="coerce").dropna()
        epu = epu.loc[(epu.index >= START) & (epu.index <= END)]
        if len(epu) > 1000:
            return epu.rename("USEPUINDXD")
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] FRED USEPUINDXD fetch failed, using cached K1121 copy: {exc}")

    cached = Path("experiments/k1121/data/fred_USEPUINDXD.csv")
    epu = pd.read_csv(cached, parse_dates=["DATE"]).set_index("DATE")["USEPUINDXD"].dropna()
    epu = epu.loc[(epu.index >= START) & (epu.index <= END)]
    return epu.rename("USEPUINDXD")


def build_monthly_epu_signal(epu_daily: pd.Series, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    monthly = epu_daily.resample("ME").mean().dropna().rename("epu_monthly_mean")
    log_epu = np.log(monthly.clip(lower=1e-8))
    shock_3m = log_epu.diff(3).rename("epu_log_chg3m")
    expanding_q75 = (
        shock_3m.expanding(MIN_EPU_HISTORY_MONTHS).quantile(0.75).shift(1).rename("epu_chg3m_q75_expanding")
    )
    shock_flag = ((shock_3m > expanding_q75) & expanding_q75.notna()).astype(float).rename("epu_shock_high")
    z = ((shock_3m - shock_3m.expanding(MIN_EPU_HISTORY_MONTHS).mean().shift(1)) /
         shock_3m.expanding(MIN_EPU_HISTORY_MONTHS).std().shift(1)).rename("epu_chg3m_z")

    monthly_panel = pd.concat([monthly, shock_3m, expanding_q75, shock_flag, z], axis=1).dropna()
    # Month-M EPU is not usable until all month-M observations exist; apply it only after M-end + 2 business days.
    monthly_panel.index = monthly_panel.index + BDay(2)
    daily_panel = monthly_panel.reindex(daily_index, method="ffill")
    return daily_panel


def fit_markov_vol_state(price: pd.Series, label: str) -> dict:
    ret = np.log(price).diff().dropna().rename("ret")
    log_r2 = np.log((ret ** 2).clip(lower=1e-10)).rename("log_r2")
    lo, hi = log_r2.quantile([0.005, 0.995])
    y_raw = log_r2.clip(lower=lo, upper=hi).dropna().rename("log_r2_winsor")
    y = ((y_raw - y_raw.mean()) / y_raw.std()).rename("log_r2_winsor_z")

    last_error = None
    result = None
    fit_spec = None
    attempts = [
        {"switching_variance": True, "search_reps": 8, "search_iter": 8, "em_iter": 12},
        {"switching_variance": True, "search_reps": 0, "search_iter": 0, "em_iter": 0},
        {"switching_variance": True, "search_reps": 4, "search_iter": 5, "em_iter": 0},
        {"switching_variance": False, "search_reps": 8, "search_iter": 8, "em_iter": 12},
        {"switching_variance": False, "search_reps": 0, "search_iter": 0, "em_iter": 0},
        {"switching_variance": False, "search_reps": 4, "search_iter": 5, "em_iter": 0},
    ]
    for attempt in attempts:
        try:
            model = sm.tsa.MarkovRegression(
                y,
                k_regimes=2,
                trend="c",
                switching_variance=attempt["switching_variance"],
            )
            result = model.fit(
                search_reps=attempt["search_reps"],
                search_iter=attempt["search_iter"],
                em_iter=attempt["em_iter"],
                maxiter=300,
                disp=False,
            )
            fit_spec = attempt
            break
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
    if result is None:
        raise RuntimeError(f"{label} MarkovRegression failed: {last_error}")

    filtered = pd.DataFrame(result.filtered_marginal_probabilities, index=y.index)

    state_scores = {}
    for state in filtered.columns:
        weights = filtered[state].clip(lower=0)
        state_scores[int(state)] = float(np.average(y_raw.loc[filtered.index], weights=weights + 1e-12))
    high_state = max(state_scores, key=state_scores.get)
    high_prob = filtered[high_state].rename("high_prob")
    high_state_binary = (high_prob > 0.5).astype(int).rename("high_state")
    transition = ((high_state_binary == 1) & (high_state_binary.shift(1) == 0)).astype(int).rename("low_to_high")

    frame = pd.concat([ret, log_r2, y_raw, high_prob, high_state_binary, transition], axis=1).dropna()
    params = result.params
    if hasattr(params, "items"):
        param_dict = {str(k): float(v) for k, v in params.items()}
    else:
        param_dict = {str(i): float(v) for i, v in enumerate(params)}
    return {
        "asset": label,
        "frame": frame,
        "model": {
            "converged": bool(result.mle_retvals.get("converged", False)),
            "fit_spec": fit_spec,
            "llf": float(result.llf),
            "aic": float(result.aic),
            "bic": float(result.bic),
            "high_state": int(high_state),
            "state_log_r2_scores": state_scores,
            "params": param_dict,
        },
    }


def hac_lpm(formula: str, data: pd.DataFrame, coef_name: str) -> dict:
    model = smf.ols(formula, data=data).fit(cov_type="HAC", cov_kwds={"maxlags": HAC_LAGS})
    return {
        "formula": formula,
        "n": int(model.nobs),
        "coef": float(model.params[coef_name]),
        "se_hac": float(model.bse[coef_name]),
        "t_hac": float(model.tvalues[coef_name]),
        "p_hac": float(model.pvalues[coef_name]),
        "r2": float(model.rsquared),
        "hac_lags": HAC_LAGS,
    }


def analyze_asset(asset_state: dict, epu_daily_panel: pd.DataFrame) -> dict:
    label = asset_state["asset"]
    frame = asset_state["frame"].join(epu_daily_panel, how="left").dropna()
    frame["epu_shock_high"] = frame["epu_shock_high"].astype(int)

    normal = frame[frame["epu_shock_high"] == 0]
    shock = frame[frame["epu_shock_high"] == 1]
    tests = {
        "high_prob_on_epu_shock": hac_lpm("high_prob ~ epu_shock_high", frame, "epu_shock_high"),
        "transition_on_epu_shock": hac_lpm("low_to_high ~ epu_shock_high", frame, "epu_shock_high"),
        "log_r2_on_epu_shock": hac_lpm("log_r2_winsor ~ epu_shock_high", frame, "epu_shock_high"),
        "high_prob_on_epu_z": hac_lpm("high_prob ~ epu_chg3m_z", frame, "epu_chg3m_z"),
    }
    summary = {
        "sample_start": str(frame.index.min().date()),
        "sample_end": str(frame.index.max().date()),
        "n": int(len(frame)),
        "epu_shock_days": int(frame["epu_shock_high"].sum()),
        "epu_shock_share": float(frame["epu_shock_high"].mean()),
        "high_prob_normal": float(normal["high_prob"].mean()),
        "high_prob_epu_shock": float(shock["high_prob"].mean()),
        "transition_rate_normal": float(normal["low_to_high"].mean()),
        "transition_rate_epu_shock": float(shock["low_to_high"].mean()),
        "ann_vol_normal": float(np.sqrt(np.mean(normal["ret"] ** 2) * 252.0)),
        "ann_vol_epu_shock": float(np.sqrt(np.mean(shock["ret"] ** 2) * 252.0)),
    }
    return {"asset": label, "sample": summary, "markov_model": asset_state["model"], "tests": tests}


def multiple_test_correction(asset_results: list[dict]) -> dict:
    pvals = []
    for asset_result in asset_results:
        asset = asset_result["asset"]
        for test_name, test in asset_result["tests"].items():
            pvals.append((f"{asset}:{test_name}", test["p_hac"]))

    m = len(pvals)
    ranked = sorted(pvals, key=lambda x: x[1])
    bh_raw = [min(p * m / rank, 1.0) for rank, (_, p) in enumerate(ranked, start=1)]
    bh_adj = [0.0] * m
    running = 1.0
    for idx in range(m - 1, -1, -1):
        running = min(running, bh_raw[idx])
        bh_adj[idx] = running

    out = {}
    for idx, (label, p) in enumerate(ranked):
        out[label] = {
            "raw_p": float(p),
            "bonferroni_p": float(min(p * m, 1.0)),
            "bh_p": float(bh_adj[idx]),
            "rank": int(idx + 1),
        }
    return out


def make_figures(asset_states: list[dict], epu_daily_panel: pd.DataFrame, asset_results: list[dict]) -> list[str]:
    fig_paths = []
    for state, result in zip(asset_states, asset_results, strict=True):
        label = state["asset"]
        frame = state["frame"].join(epu_daily_panel, how="left").dropna()
        fig, axes = plt.subplots(2, 1, figsize=(12, 7))
        axes[0].plot(frame.index, frame["high_prob"], lw=0.8, color="#4c72b0", label="Filtered high-vol probability")
        axes[0].fill_between(
            frame.index,
            0,
            1,
            where=frame["epu_shock_high"].astype(bool),
            color="#c44e52",
            alpha=0.16,
            label="Lagged monthly EPU shock",
        )
        axes[0].set_ylim(-0.02, 1.02)
        axes[0].set_title(f"{label}: Markov high-vol probability and lagged EPU shocks")
        axes[0].legend(loc="upper left")
        axes[0].grid(True, alpha=0.25)

        bars = [
            result["sample"]["high_prob_normal"],
            result["sample"]["high_prob_epu_shock"],
            result["sample"]["transition_rate_normal"],
            result["sample"]["transition_rate_epu_shock"],
        ]
        axes[1].bar(["P(high)\nnormal", "P(high)\nEPU shock", "P(L->H)\nnormal", "P(L->H)\nEPU shock"], bars,
                    color=["#55a868", "#c44e52", "#55a868", "#c44e52"])
        axes[1].set_title("Conditional regime outcomes")
        axes[1].grid(True, axis="y", alpha=0.25)
        fig.tight_layout()
        rel = f"figures/{label.lower()}_epu_regime_trigger.png"
        fig.savefig(OUT_DIR / rel, dpi=130)
        plt.close(fig)
        fig_paths.append(rel)
    return fig_paths


def derive_verdict(asset_results: list[dict], correction: dict) -> tuple[str, str]:
    primary_labels = [f"{r['asset']}:high_prob_on_epu_shock" for r in asset_results]
    primary_pass = []
    directional = []
    for result in asset_results:
        asset = result["asset"]
        test = result["tests"]["high_prob_on_epu_shock"]
        corr = correction[f"{asset}:high_prob_on_epu_shock"]
        primary_pass.append(test["coef"] > 0 and corr["bh_p"] < 0.05)
        directional.append(test["coef"] > 0)

    if all(primary_pass):
        return (
            "PASS",
            "Both assets show a positive EPU-shock effect on Markov high-vol probability after BH correction.",
        )
    if any(primary_pass) and all(directional):
        return (
            "MIXED",
            "Both assets have positive EPU-shock coefficients, but only part of the cross-asset evidence survives BH correction.",
        )
    if all(directional):
        return (
            "DIRECTIONAL_ONLY",
            "EPU shocks line up with higher Markov high-vol probabilities in both assets, but formal multiple-test evidence is insufficient.",
        )
    return (
        "NULL",
        "Lagged EPU shocks do not provide consistent positive cross-asset evidence as high-volatility regime triggers.",
    )


def main() -> dict:
    np.random.seed(SEED)
    prices = {
        "SPY": fetch_price_series("SPY", "SPY"),
        "TAIEX": fetch_price_series("^TWII", "TAIEX"),
    }
    all_days = pd.date_range(START, END, freq="B")
    epu_daily = load_epu_daily()
    epu_panel = build_monthly_epu_signal(epu_daily, all_days)

    asset_states = [fit_markov_vol_state(price, label) for label, price in prices.items()]
    asset_results = [analyze_asset(state, epu_panel) for state in asset_states]
    correction = multiple_test_correction(asset_results)
    figures = make_figures(asset_states, epu_panel, asset_results)
    verdict, verdict_reason = derive_verdict(asset_results, correction)

    result = {
        "experiment_id": "K1519",
        "title": "EPU as a cross-asset volatility-regime switching trigger",
        "created_at": pd.Timestamp.now("UTC").isoformat(),
        "random_seed": SEED,
        "task_id": "research_epu_vol_regime_switching_trigger_incremental_pre",
        "data_sources": {
            "prices": "yfinance SPY and ^TWII adjusted close / index close",
            "epu": "FRED USEPUINDXD daily Baker-Bloom-Davis EPU, monthly mean transformed to lagged monthly signal",
        },
        "literature": [
            "Baker, Bloom, and Davis (2016), Measuring Economic Policy Uncertainty, QJE",
            "Economic Policy Uncertainty and Stock Market Volatility, OeNB WP 234",
            "Tzika and Pantelidis, Economic policy uncertainty as an indicator of abrupt movements in the US stock market",
            "GARCH-MIDAS and regime-switching volatility literature motivating macro-to-volatility state links",
        ],
        "methodology": {
            "state_model": "2-state MarkovRegression on winsorized daily log squared returns with switching variance",
            "trigger": "monthly log EPU 3-month change; high shock if above expanding historical 75th percentile",
            "publication_lag": "month-M EPU signal applies only after month-end + 2 business days, then forward-filled",
            "inference": f"OLS linear probability / conditional mean tests with Newey-West HAC maxlags={HAC_LAGS}",
            "multiple_testing": "BH and Bonferroni across 2 assets x 4 tests",
        },
        "lookahead_audit": {
            "epu_signal": "uses only completed monthly EPU data, delayed by two business days before use",
            "state_outcome": "filtered high-vol state is the realized outcome being explained, not a trading signal",
            "no_same_day_predictor": "no EPU value from the target day or target month is used before its release lag",
        },
        "asset_results": asset_results,
        "multiple_test_correction": correction,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "honest_limits": [
            "This is a Markov volatility-state proxy, not a full Markov-switching GARCH likelihood.",
            "State labels are estimated on the full sample; use them for mechanism identification, not tradable forecast claims.",
            "USEPUINDXD is a US EPU measure; TAIEX cross-asset evidence is a spillover test, not Taiwan-specific EPU.",
        ],
        "figures": figures,
    }
    (OUT_DIR / "k1519_results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"verdict": verdict, "reason": verdict_reason}, indent=2))
    return result


if __name__ == "__main__":
    main()
