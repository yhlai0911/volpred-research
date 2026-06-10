from __future__ import annotations

import json
import time
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

EXPERIMENT_ID = "k1452"
SEED = 42
START = "2005-01-01"
END = "2026-06-10"
ROLL_RV = 22
ROLL_SHARE = 252
SHORT_H = 22
LONG_H = 126
BOOT_REPS = 2000
BOOT_BLOCK = 10
MAX_RETRIES = 3
RESULTS_PATH = Path("experiments") / EXPERIMENT_ID / f"{EXPERIMENT_ID}_results.json"
FIG_DIR = Path("experiments") / EXPERIMENT_ID / "figures"


def download_yf(ticker: str, start: str, end: str) -> pd.DataFrame:
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            df = yf.download(
                ticker,
                start=start,
                end=end,
                auto_adjust=False,
                progress=False,
                threads=False,
            )
            if df.empty:
                raise ValueError(f"{ticker} download returned empty data")
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df[["Open", "Close"]].dropna()
        except Exception as exc:  # pragma: no cover
            last_error = exc
            if attempt < MAX_RETRIES:
                time.sleep(attempt)
    raise RuntimeError(f"Failed to download {ticker} after {MAX_RETRIES} tries: {last_error}")


def forward_annualized_variance(sq: pd.Series, horizon: int) -> pd.Series:
    values = sq.to_numpy(dtype=float)
    out = np.full(values.shape, np.nan, dtype=float)
    for i in range(len(values) - horizon):
        future = values[i + 1 : i + 1 + horizon]
        if np.isnan(future).any():
            continue
        out[i] = 252.0 * future.mean()
    return pd.Series(out, index=sq.index)


def block_bootstrap_ci_mean(
    series: pd.Series,
    reps: int = BOOT_REPS,
    block: int = BOOT_BLOCK,
    seed: int = SEED,
) -> tuple[float, float]:
    x = series.dropna().to_numpy(dtype=float)
    n = len(x)
    if n == 0:
        return (np.nan, np.nan)
    if n <= block:
        mean = float(np.mean(x))
        return (mean, mean)

    rng = np.random.default_rng(seed)
    starts = np.arange(0, n - block + 1)
    means = np.empty(reps, dtype=float)
    blocks_needed = int(np.ceil(n / block))
    for r in range(reps):
        picks = rng.choice(starts, size=blocks_needed, replace=True)
        sample = np.concatenate([x[s : s + block] for s in picks])[:n]
        means[r] = np.mean(sample)
    lo, hi = np.quantile(means, [0.025, 0.975])
    return float(lo), float(hi)


def hac_mean_test(series: pd.Series, lags: int = 10, alternative: str = "two-sided") -> dict:
    y = series.dropna().astype(float)
    model = sm.OLS(y, np.ones(len(y))).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    coef = float(model.params.iloc[0])
    tval = float(model.tvalues.iloc[0])
    p_two = float(model.pvalues.iloc[0])

    if alternative == "less":
        pval = p_two / 2 if tval < 0 else 1.0 - p_two / 2
    elif alternative == "greater":
        pval = p_two / 2 if tval > 0 else 1.0 - p_two / 2
    else:
        pval = p_two

    ci_low, ci_high = block_bootstrap_ci_mean(y)
    return {
        "n": int(len(y)),
        "mean": coef,
        "t_stat_hac": tval,
        "p_value": pval,
        "alternative": alternative,
        "bootstrap_ci_95": [ci_low, ci_high],
    }


def hac_regression(df: pd.DataFrame, y_col: str, x_col: str, lags: int) -> dict:
    use = df[[y_col, x_col]].dropna().copy()
    use[f"{x_col}_z"] = (use[x_col] - use[x_col].mean()) / use[x_col].std(ddof=0)
    X = sm.add_constant(use[f"{x_col}_z"])
    model = sm.OLS(use[y_col], X).fit(cov_type="HAC", cov_kwds={"maxlags": lags})
    return {
        "n": int(len(use)),
        "coef_z": float(model.params[f"{x_col}_z"]),
        "t_stat_hac": float(model.tvalues[f"{x_col}_z"]),
        "p_value_two_sided": float(model.pvalues[f"{x_col}_z"]),
        "r_squared": float(model.rsquared),
    }


def bonferroni(pvals: list[float]) -> list[float]:
    m = len(pvals)
    return [min(1.0, p * m) for p in pvals]


def bh_adjust(pvals: list[float]) -> list[float]:
    p = np.asarray(pvals, dtype=float)
    order = np.argsort(p)
    ranked = p[order]
    m = len(p)
    adj = ranked * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(adj[::-1])[::-1]
    adj = np.clip(adj, 0, 1)
    out = np.empty_like(adj)
    out[order] = adj
    return out.tolist()


def build_dataset() -> pd.DataFrame:
    spy = download_yf("SPY", START, END)
    vix = download_yf("^VIX", START, END).rename(columns={"Close": "VIX_Close"})
    df = spy.join(vix[["VIX_Close"]], how="inner").dropna()

    df["overnight_ret"] = np.log(df["Open"] / df["Close"].shift(1))
    df["intraday_ret"] = np.log(df["Close"] / df["Open"])
    df["total_ret"] = df["overnight_ret"] + df["intraday_ret"]

    for segment in ["overnight", "intraday", "total"]:
        df[f"{segment}_sq"] = df[f"{segment}_ret"] ** 2

    df["rv_overnight_22"] = 252.0 * df["overnight_sq"].rolling(ROLL_RV).mean()
    df["rv_intraday_22"] = 252.0 * df["intraday_sq"].rolling(ROLL_RV).mean()
    df["rv_total_22"] = 252.0 * df["total_sq"].rolling(ROLL_RV).mean()

    # Codex review fix #1 (2026-06-10): shift(1) makes the share strictly
    # ex-ante — share used at day t is computed from data through t-1 only,
    # matching the stated "trailing / past-only" interpretation.
    df["share_overnight_252"] = (
        df["overnight_sq"].rolling(ROLL_SHARE).sum() / df["total_sq"].rolling(ROLL_SHARE).sum()
    ).shift(1)
    df["share_intraday_252"] = 1.0 - df["share_overnight_252"]

    df["iv_total_30d"] = (df["VIX_Close"] / 100.0) ** 2
    df["iv_overnight_proxy"] = df["iv_total_30d"] * df["share_overnight_252"]
    df["iv_intraday_proxy"] = df["iv_total_30d"] * df["share_intraday_252"]

    df["vrp_overnight"] = df["iv_overnight_proxy"] - df["rv_overnight_22"]
    df["vrp_intraday"] = df["iv_intraday_proxy"] - df["rv_intraday_22"]
    df["vrp_total"] = df["iv_total_30d"] - df["rv_total_22"]

    for horizon in [SHORT_H, LONG_H]:
        df[f"fwd_overnight_rv_{horizon}"] = forward_annualized_variance(df["overnight_sq"], horizon)
        df[f"fwd_intraday_rv_{horizon}"] = forward_annualized_variance(df["intraday_sq"], horizon)
        df[f"fwd_total_rv_{horizon}"] = forward_annualized_variance(df["total_sq"], horizon)

    # Codex review fix #2 (2026-06-10): VIX^2 is a ~30-calendar-day (~22
    # trading-day) FORWARD-looking measure while the baseline VRP subtracts
    # trailing 22d RV — a horizon/direction mismatch. Sensitivity: BTZ-style
    # ex-post premium IV_t - RV_{t+1..t+22} (horizon-matched). Used only for
    # the mean sign tests (it embeds future realizations, so it must never be
    # used as a predictive signal).
    df["vrp_overnight_hm"] = df["iv_overnight_proxy"] - df[f"fwd_overnight_rv_{SHORT_H}"]
    df["vrp_intraday_hm"] = df["iv_intraday_proxy"] - df[f"fwd_intraday_rv_{SHORT_H}"]

    return df.dropna(
        subset=[
            "vrp_overnight",
            "vrp_intraday",
            f"fwd_overnight_rv_{SHORT_H}",
            f"fwd_intraday_rv_{SHORT_H}",
            f"fwd_overnight_rv_{LONG_H}",
            f"fwd_intraday_rv_{LONG_H}",
        ]
    )


def make_figures(df: pd.DataFrame) -> list[str]:
    paths: list[str] = []

    sample = df[["vrp_overnight", "vrp_intraday"]].dropna()
    fig, ax = plt.subplots(figsize=(10, 5))
    sample.plot(ax=ax, lw=0.9)
    ax.axhline(0, color="black", lw=1, alpha=0.6)
    ax.set_title("Segment Variance Risk Premium Proxy")
    ax.set_ylabel("Annualized Variance")
    ax.set_xlabel("")
    fig.tight_layout()
    p1 = FIG_DIR / "segment_vrp_timeseries.png"
    fig.savefig(p1, dpi=160)
    plt.close(fig)
    paths.append(str(p1))

    means = pd.Series(
        {
            "Overnight VRP": sample["vrp_overnight"].mean(),
            "Intraday VRP": sample["vrp_intraday"].mean(),
        }
    )
    fig, ax = plt.subplots(figsize=(7, 4))
    colors = ["#b22222", "#1f77b4"]
    means.plot(kind="bar", ax=ax, color=colors)
    ax.axhline(0, color="black", lw=1, alpha=0.6)
    ax.set_title("Mean Segment VRP Proxy")
    ax.set_ylabel("Annualized Variance")
    fig.tight_layout()
    p2 = FIG_DIR / "segment_vrp_means.png"
    fig.savefig(p2, dpi=160)
    plt.close(fig)
    paths.append(str(p2))
    return paths


def main() -> None:
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    df = build_dataset()

    mean_tests = {
        "overnight_negative": hac_mean_test(df["vrp_overnight"], alternative="less"),
        "intraday_positive": hac_mean_test(df["vrp_intraday"], alternative="greater"),
    }

    # Horizon-matched ex-post VRP sensitivity (overlapping 22d forward windows
    # -> HAC lags = SHORT_H - 1).
    sensitivity_tests = {
        "overnight_negative_hm": hac_mean_test(df["vrp_overnight_hm"], lags=SHORT_H - 1, alternative="less"),
        "intraday_positive_hm": hac_mean_test(df["vrp_intraday_hm"], lags=SHORT_H - 1, alternative="greater"),
    }

    predictive_tests = {
        "overnight_22d": hac_regression(df, f"fwd_overnight_rv_{SHORT_H}", "vrp_overnight", lags=SHORT_H - 1),
        "intraday_22d": hac_regression(df, f"fwd_intraday_rv_{SHORT_H}", "vrp_intraday", lags=SHORT_H - 1),
        "overnight_126d": hac_regression(df, f"fwd_overnight_rv_{LONG_H}", "vrp_overnight", lags=21),
        "intraday_126d": hac_regression(df, f"fwd_intraday_rv_{LONG_H}", "vrp_intraday", lags=21),
    }

    primary_labels = [
        "overnight mean < 0",
        "intraday mean > 0",
        "overnight VRP -> fwd overnight RV (22d)",
        "intraday VRP -> fwd intraday RV (22d)",
        "overnight VRP -> fwd overnight RV (126d)",
        "intraday VRP -> fwd intraday RV (126d)",
    ]
    primary_pvals = [
        mean_tests["overnight_negative"]["p_value"],
        mean_tests["intraday_positive"]["p_value"],
        predictive_tests["overnight_22d"]["p_value_two_sided"],
        predictive_tests["intraday_22d"]["p_value_two_sided"],
        predictive_tests["overnight_126d"]["p_value_two_sided"],
        predictive_tests["intraday_126d"]["p_value_two_sided"],
    ]
    bonf = bonferroni(primary_pvals)
    bh = bh_adjust(primary_pvals)

    corrected = []
    for label, raw, p_bonf, p_bh in zip(primary_labels, primary_pvals, bonf, bh):
        corrected.append(
            {
                "label": label,
                "raw_p": float(raw),
                "bonferroni_p": float(p_bonf),
                "bh_p": float(p_bh),
                "bonferroni_sig_5pct": bool(p_bonf < 0.05),
            }
        )

    sign_split = (
        mean_tests["overnight_negative"]["mean"] < 0
        and mean_tests["intraday_positive"]["mean"] > 0
        and bonf[0] < 0.05
        and bonf[1] < 0.05
    )
    short_sig = (
        predictive_tests["overnight_22d"]["p_value_two_sided"] * 6 < 0.05
        or predictive_tests["intraday_22d"]["p_value_two_sided"] * 6 < 0.05
    )
    long_sig = (
        predictive_tests["overnight_126d"]["p_value_two_sided"] * 6 < 0.05
        or predictive_tests["intraday_126d"]["p_value_two_sided"] * 6 < 0.05
    )

    if sign_split and short_sig and not long_sig:
        verdict = "PASS"
    elif sign_split:
        verdict = "CONDITIONAL_PASS"
    else:
        verdict = "NULL"

    figures = make_figures(df)

    short_vs_long = {
        "overnight_abs_t_22_vs_126": float(
            abs(predictive_tests["overnight_22d"]["t_stat_hac"])
            - abs(predictive_tests["overnight_126d"]["t_stat_hac"])
        ),
        "intraday_abs_t_22_vs_126": float(
            abs(predictive_tests["intraday_22d"]["t_stat_hac"])
            - abs(predictive_tests["intraday_126d"]["t_stat_hac"])
        ),
    }

    results = {
        "experiment_id": EXPERIMENT_ID,
        "title": "Overnight vs Intraday Variance Risk Premium Sign-Flip Test",
        "date": pd.Timestamp.now("UTC").strftime("%Y-%m-%d"),
        "seed": SEED,
        "data": {
            "source": ["yfinance: SPY", "yfinance: ^VIX"],
            "start": str(df.index.min().date()),
            "end": str(df.index.max().date()),
            "n_obs": int(len(df)),
            "rv_window_days": ROLL_RV,
            "share_window_days": ROLL_SHARE,
            "short_horizon_days": SHORT_H,
            "long_horizon_days": LONG_H,
        },
        "methodology": {
            "signal_timing": "Signals are formed at day t close using same-day SPY open/close and VIX close; all targets are t+1 onward forward variance.",
            "segment_definition": {
                "overnight": "log(Open_t / Close_{t-1})",
                "intraday": "log(Close_t / Open_t)",
            },
            "implied_variance_proxy": (
                "Total implied variance = (VIX/100)^2. Segment implied variance proxy uses trailing 252d "
                "realized variance shares, lagged one day (shift(1)) so the share at t uses data through t-1 only."
            ),
            "horizon_mismatch_note": (
                "Baseline VRP subtracts trailing 22-trading-day RV (annualized x252) from (VIX/100)^2, a "
                "~30-calendar-day forward risk-neutral measure — a direction/horizon mismatch, so baseline VRP "
                "levels and sign tests are proxy-dependent. Sensitivity 'sensitivity_horizon_matched' uses the "
                "BTZ-style ex-post premium IV_t - RV_{t+1..t+22} (horizon-matched; mean tests only, never as a signal)."
            ),
            "formal_tests": "2 one-sided HAC mean tests + 4 HAC predictive regressions; Bonferroni and BH applied over 6 primary tests.",
            "bootstrap": {
                "type": "moving_block_bootstrap_mean_ci",
                "reps": BOOT_REPS,
                "block_size": BOOT_BLOCK,
                "seed": SEED,
            },
        },
        "summary_stats": {
            "mean_vrp_overnight": float(df["vrp_overnight"].mean()),
            "mean_vrp_intraday": float(df["vrp_intraday"].mean()),
            "mean_vrp_total": float(df["vrp_total"].mean()),
            "median_share_overnight_252": float(df["share_overnight_252"].median()),
            "median_share_intraday_252": float(df["share_intraday_252"].median()),
            "corr_overnight_intraday_vrp": float(df["vrp_overnight"].corr(df["vrp_intraday"])),
        },
        "mean_tests": mean_tests,
        "sensitivity_horizon_matched": sensitivity_tests,
        "predictive_tests": predictive_tests,
        "multiple_testing": corrected,
        "horizon_comparison": short_vs_long,
        "verdict": verdict,
        "conclusion": "",
        "figures": figures,
    }

    overnight_sig = corrected[0]["bonferroni_sig_5pct"]
    intraday_sig = corrected[1]["bonferroni_sig_5pct"]
    short_any = corrected[2]["bonferroni_sig_5pct"] or corrected[3]["bonferroni_sig_5pct"]
    long_any = corrected[4]["bonferroni_sig_5pct"] or corrected[5]["bonferroni_sig_5pct"]

    if verdict == "PASS":
        results["conclusion"] = (
            "Segment VRP proxy shows a robust sign split: overnight mean VRP is negative, intraday mean VRP is positive, "
            "and short-horizon predictive content is stronger than long-horizon predictive content after correction."
        )
    elif verdict == "CONDITIONAL_PASS":
        results["conclusion"] = (
            "The sign split survives correction, but predictive evidence is mixed. "
            f"Short-horizon corrected significance={short_any}, long-horizon corrected significance={long_any}."
        )
    else:
        results["conclusion"] = (
            "The sign-flip story does not survive the repo's minimum evidence bar. "
            f"Corrected sign tests: overnight={overnight_sig}, intraday={intraday_sig}; "
            f"predictive tests short={short_any}, long={long_any}."
        )

    results["conclusion"] += (
        " Caveat: segment VRP is a reduced-form proxy (VIX share split + 22d-RV-vs-30d-IV convention "
        "mismatch in the baseline), so VRP levels/signs are proxy-dependent; see "
        "methodology.horizon_mismatch_note and sensitivity_horizon_matched."
    )

    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(json.dumps({"ok": True, "results_path": str(RESULTS_PATH), "verdict": verdict}, ensure_ascii=False))


if __name__ == "__main__":
    main()
