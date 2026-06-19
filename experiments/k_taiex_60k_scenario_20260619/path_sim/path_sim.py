#!/usr/bin/env python3
"""
TAIEX (^TWII) "touch 60,000" 3-month path-risk scenario simulation.

Question: conditional on a GARCH(1,1) return model, what is the probability that
^TWII reaches >= 60,000 at any point within the next 63 trading days (~3 months),
given the last close ~46,465 (2026-06-18)? Reaching 60,000 requires +29.1%.

Method:
  1. yfinance ^TWII daily log returns 2012-01-01 .. latest trading day.
  2. arch: GARCH(1,1) with Student-t innovations (record dist choice + AIC vs normal).
  3. seed=42, >=10,000 Monte Carlo 63-day paths via filtered GARCH simulation.
     Two drift scenarios: (a) zero drift, (b) historical-mean drift.
  4. Report P(period max >= 60000), 3M-ahead level median + 5/95 pct,
     path max-drawdown distribution, and split for touch vs no-touch paths.
  5. Empirical benchmark: historical frequency of any 63-day forward window
     achieving >= +29% (rolling, real data, no simulation).

Honesty: probabilities are MODEL-CONDITIONAL, not a forecast that the event WILL
happen. Drift assumption strongly affects touch probability -> both scenarios reported.

Reproducible: seed=42; uses local CSV snapshot first, yfinance fallback.

Run: uv run python path_sim.py
"""
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

SEED = 42
TARGET = 60000.0
HORIZON = 63          # ~3 months of trading days
N_SIMS = 20000        # >= 10000
DATA_START = "2012-01-01"
HERE = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT = os.path.join(HERE, "data", "twii_close_snapshot.csv")


def load_close():
    """Local snapshot first (reproducibility), yfinance fallback."""
    if os.path.exists(SNAPSHOT):
        s = pd.read_csv(SNAPSHOT, index_col=0, parse_dates=True)["Close"]
        source = f"local snapshot {SNAPSHOT}"
        return s.dropna(), source
    import yfinance as yf
    df = yf.download("^TWII", start=DATA_START, auto_adjust=True, progress=False)
    close = df["Close"]
    if hasattr(close, "columns"):
        close = close.iloc[:, 0]
    close = close.dropna()
    os.makedirs(os.path.dirname(SNAPSHOT), exist_ok=True)
    close.to_frame("Close").to_csv(SNAPSHOT)
    return close, "yfinance ^TWII (auto_adjust)"


def main():
    np.random.seed(SEED)
    close, data_source = load_close()
    last_date = close.index[-1].date().isoformat()
    first_date = close.index[0].date().isoformat()
    S0 = float(close.iloc[-1])

    # log returns in pct (arch likes scaled returns)
    logret = np.log(close / close.shift(1)).dropna()
    ret_pct = logret * 100.0
    n_obs = len(ret_pct)

    mu_daily = float(logret.mean())          # historical mean daily log return
    sigma_daily_uncond = float(logret.std(ddof=1))
    ann_drift = mu_daily * 252
    needed_pct = (TARGET / S0 - 1.0) * 100.0

    # ---- Fit GARCH(1,1): Student-t and Normal, pick by AIC ----
    from arch import arch_model

    fits = {}
    for dist in ("t", "normal"):
        am = arch_model(ret_pct, mean="Constant", vol="GARCH", p=1, q=1, dist=dist)
        res = am.fit(disp="off")
        fits[dist] = res

    aic = {d: float(fits[d].aic) for d in fits}
    chosen_dist = min(aic, key=aic.get)
    res = fits[chosen_dist]
    params = {k: float(v) for k, v in res.params.items()}

    # GARCH(1,1) variance params (note: 'mu' is in pct units; we override drift below)
    omega = params["omega"]
    alpha = params["alpha[1]"]
    beta = params["beta[1]"]
    nu = params.get("nu", None)  # Student-t dof if chosen
    persistence = alpha + beta
    uncond_var_pct = omega / max(1e-12, (1 - persistence))  # in pct^2

    # last conditional variance (forecast origin) from the fitted model
    cond_vol_last_pct = float(res.conditional_volatility.iloc[-1])  # daily, pct units
    cond_var_last_pct = cond_vol_last_pct ** 2

    # ---- Monte Carlo via GARCH recursion ----
    # We simulate daily log returns in DECIMAL. Convert pct params to decimal:
    #   r_pct = mu_pct + sigma_pct * z ; r_dec = r_pct/100
    # variance recursion stays in pct^2, we convert sigma to decimal per step.
    def simulate(drift_mode):
        rng = np.random.default_rng(SEED)
        # innovations
        if chosen_dist == "t" and nu is not None:
            # standardized Student-t: scale so variance = 1
            z = rng.standard_t(nu, size=(N_SIMS, HORIZON))
            z = z * np.sqrt((nu - 2.0) / nu)
        else:
            z = rng.standard_normal(size=(N_SIMS, HORIZON))

        # daily drift in decimal
        if drift_mode == "zero":
            drift_dec = 0.0
        else:  # historical mean daily log return
            drift_dec = mu_daily

        var_pct = np.full(N_SIMS, cond_var_last_pct, dtype=float)  # start at last cond var
        # prior shock^2 for recursion start: use last residual^2 (pct)
        eps_prev_sq = float((res.resid.iloc[-1]) ** 2)
        eps_prev_sq_arr = np.full(N_SIMS, eps_prev_sq, dtype=float)

        levels = np.full(N_SIMS, S0, dtype=float)
        path_max = np.full(N_SIMS, S0, dtype=float)
        path_min = np.full(N_SIMS, S0, dtype=float)
        running_peak = np.full(N_SIMS, S0, dtype=float)
        max_dd = np.zeros(N_SIMS, dtype=float)  # max drawdown (fraction, positive)

        for t in range(HORIZON):
            # GARCH(1,1) variance update (pct^2):
            var_pct = omega + alpha * eps_prev_sq_arr + beta * var_pct
            sigma_pct = np.sqrt(var_pct)
            # shock in pct (mean-zero residual)
            eps_pct = sigma_pct * z[:, t]
            eps_prev_sq_arr = eps_pct ** 2
            # daily log return in decimal = drift + shock/100
            r_dec = drift_dec + eps_pct / 100.0
            levels = levels * np.exp(r_dec)
            path_max = np.maximum(path_max, levels)
            path_min = np.minimum(path_min, levels)
            running_peak = np.maximum(running_peak, levels)
            dd = 1.0 - levels / running_peak
            max_dd = np.maximum(max_dd, dd)

        touched = path_max >= TARGET
        return {
            "final_levels": levels,
            "path_max": path_max,
            "path_min": path_min,
            "max_dd": max_dd,
            "touched": touched,
        }

    results = {}
    for mode in ("zero", "historical"):
        sim = simulate(mode)
        final = sim["final_levels"]
        touched = sim["touched"]
        mdd = sim["max_dd"]
        p_touch = float(touched.mean())
        # final at horizon end >= target (different from "touch anytime")
        p_end_above = float((final >= TARGET).mean())
        block = {
            "drift_mode": mode,
            "drift_daily_log": (0.0 if mode == "zero" else mu_daily),
            "drift_annualized": (0.0 if mode == "zero" else ann_drift),
            "p_touch_60000_anytime": p_touch,
            "p_end_above_60000": p_end_above,
            "final_level_median": float(np.median(final)),
            "final_level_p05": float(np.percentile(final, 5)),
            "final_level_p25": float(np.percentile(final, 25)),
            "final_level_p75": float(np.percentile(final, 75)),
            "final_level_p95": float(np.percentile(final, 95)),
            "final_level_mean": float(final.mean()),
            "max_drawdown_median": float(np.median(mdd)),
            "max_drawdown_p05": float(np.percentile(mdd, 5)),
            "max_drawdown_p95": float(np.percentile(mdd, 95)),
            "max_drawdown_mean": float(mdd.mean()),
        }
        # drawdown conditional on touching
        if touched.sum() > 0:
            block["max_dd_median_given_touch"] = float(np.median(mdd[touched]))
            block["max_dd_p95_given_touch"] = float(np.percentile(mdd[touched], 95))
            block["final_median_given_touch"] = float(np.median(final[touched]))
        else:
            block["max_dd_median_given_touch"] = None
            block["max_dd_p95_given_touch"] = None
            block["final_median_given_touch"] = None
        results[mode] = block
        # stash arrays for plotting
        block["_final"] = final
        block["_mdd"] = mdd
        block["_touched"] = touched

    # ---- Empirical benchmark: historical 63-day forward +29% frequency ----
    levels_arr = close.values.astype(float)
    n = len(levels_arr)
    needed_ratio = TARGET / S0  # +29.1%
    fwd_max_ratios = []
    hits_29 = 0
    windows = 0
    for i in range(n - HORIZON):
        window = levels_arr[i + 1: i + 1 + HORIZON]
        if len(window) < HORIZON:
            continue
        max_ratio = window.max() / levels_arr[i]
        fwd_max_ratios.append(max_ratio)
        windows += 1
        if max_ratio >= needed_ratio:
            hits_29 += 1
    fwd_max_ratios = np.array(fwd_max_ratios)
    emp_freq_29 = hits_29 / windows if windows else 0.0
    # also report frequency for several thresholds for context
    emp_thresholds = {}
    for thr in (1.10, 1.15, 1.20, 1.25, 1.291, 1.30):
        emp_thresholds[f"+{round((thr-1)*100,1)}%"] = float((fwd_max_ratios >= thr).mean())

    out = {
        "experiment_id": "k_taiex_60k_scenario_20260619",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "seed": SEED,
        "data": {
            "source": data_source,
            "ticker": "^TWII",
            "period_start": first_date,
            "period_end": last_date,
            "n_trading_days": int(len(close)),
            "n_return_obs": int(n_obs),
            "last_close": S0,
            "target": TARGET,
            "needed_pct_to_target": round(needed_pct, 2),
        },
        "historical_moments": {
            "mean_daily_log_return": mu_daily,
            "annualized_drift_from_mean": ann_drift,
            "uncond_daily_vol": sigma_daily_uncond,
            "annualized_uncond_vol": sigma_daily_uncond * np.sqrt(252),
        },
        "garch": {
            "spec": "GARCH(1,1), Constant mean",
            "dist_candidates_aic": aic,
            "chosen_dist": chosen_dist,
            "params": params,
            "alpha+beta_persistence": persistence,
            "student_t_dof_nu": nu,
            "last_conditional_vol_daily_pct": cond_vol_last_pct,
            "uncond_daily_vol_from_garch_pct": float(np.sqrt(uncond_var_pct)),
        },
        "monte_carlo": {
            "n_sims": N_SIMS,
            "horizon_trading_days": HORIZON,
            "seed": SEED,
            "innovation": chosen_dist,
            "scenario_zero_drift": {k: v for k, v in results["zero"].items() if not k.startswith("_")},
            "scenario_historical_drift": {k: v for k, v in results["historical"].items() if not k.startswith("_")},
        },
        "empirical_benchmark": {
            "description": f"Rolling {HORIZON}-day forward windows, real ^TWII 2012-2026; "
                           f"fraction where the window's max reaches the same +{round(needed_pct,1)}% move.",
            "n_windows": int(windows),
            "n_hits_ge_needed": int(hits_29),
            "empirical_freq_ge_needed_pct": float(emp_freq_29),
            "needed_move_pct": round(needed_pct, 2),
            "freq_by_threshold": emp_thresholds,
            "max_fwd63_move_ever_pct": float((fwd_max_ratios.max() - 1) * 100),
        },
        "honesty_notes": [
            "Probabilities are MODEL-CONDITIONAL given a GARCH(1,1) return process; "
            "they are NOT a forecast that the event will or will not occur.",
            "Drift assumption strongly affects touch probability: zero-drift is conservative; "
            "historical-mean drift extrapolates 2012-2026 average upward drift, which need not persist.",
            "GARCH(1,1) is symmetric; TWII has documented leverage (GJR gamma=0.272, K-series), "
            "so a symmetric model may slightly understate downside-clustering tail risk.",
        ],
    }

    out_path = os.path.join(HERE, "path_sim_results.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2, default=float)

    # ---- Charts ----
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Chart 1: final-level distribution both scenarios + target line
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    for ax, (mode, color, title) in zip(
        axes,
        [("zero", "#2b6cb0", "Zero drift"),
         ("historical", "#c05621", "Historical-mean drift")],
    ):
        final = results[mode]["_final"]
        ax.hist(final, bins=80, color=color, alpha=0.75, edgecolor="none")
        ax.axvline(TARGET, color="red", ls="--", lw=1.8, label=f"60,000 target")
        ax.axvline(S0, color="black", ls=":", lw=1.4, label=f"start {S0:,.0f}")
        ax.axvline(results[mode]["final_level_median"], color="green", ls="-", lw=1.6,
                   label=f"median {results[mode]['final_level_median']:,.0f}")
        p = results[mode]["p_touch_60000_anytime"] * 100
        ax.set_title(f"{title}\nP(touch 60,000 within 63d) = {p:.1f}%")
        ax.set_xlabel("TAIEX level after 63 trading days")
        ax.set_ylabel("paths")
        ax.legend(fontsize=8)
    fig.suptitle("^TWII 3-month path simulation (GARCH(1,1), seed=42, 20,000 paths)",
                 fontsize=13, weight="bold")
    fig.tight_layout()
    chart1 = os.path.join(HERE, "chart_final_distribution.png")
    fig.savefig(chart1, dpi=130)
    plt.close(fig)

    # Chart 2: max-drawdown distribution (zero-drift) + sample paths
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.5))
    mdd0 = results["zero"]["_mdd"] * 100
    axes[0].hist(mdd0, bins=70, color="#6b46c1", alpha=0.8, edgecolor="none")
    axes[0].axvline(results["zero"]["max_drawdown_median"] * 100, color="green", lw=1.6,
                    label=f"median {results['zero']['max_drawdown_median']*100:.1f}%")
    axes[0].axvline(results["zero"]["max_drawdown_p95"] * 100, color="red", ls="--", lw=1.6,
                    label=f"p95 {results['zero']['max_drawdown_p95']*100:.1f}%")
    axes[0].set_title("Path max-drawdown distribution (zero drift)")
    axes[0].set_xlabel("Max intra-path drawdown (%)")
    axes[0].set_ylabel("paths")
    axes[0].legend(fontsize=9)

    # sample paths: 40 random, color touched vs not
    rng = np.random.default_rng(SEED)
    sim_show = simulate("zero")
    idx = rng.choice(N_SIMS, 40, replace=False)
    # re-simulate small for path display
    ax = axes[1]
    # quick path regen for plotting
    rng2 = np.random.default_rng(SEED + 1)
    if chosen_dist == "t" and nu is not None:
        zp = rng2.standard_t(nu, size=(40, HORIZON)) * np.sqrt((nu - 2) / nu)
    else:
        zp = rng2.standard_normal((40, HORIZON))
    var_pct = np.full(40, cond_var_last_pct)
    eps_prev_sq = np.full(40, float((res.resid.iloc[-1]) ** 2))
    lv = np.full(40, S0)
    paths = np.zeros((40, HORIZON + 1)); paths[:, 0] = S0
    for t in range(HORIZON):
        var_pct = omega + alpha * eps_prev_sq + beta * var_pct
        eps = np.sqrt(var_pct) * zp[:, t]
        eps_prev_sq = eps ** 2
        lv = lv * np.exp(eps / 100.0)
        paths[:, t + 1] = lv
    for j in range(40):
        c = "#dd6b20" if paths[j].max() >= TARGET else "#a0aec0"
        ax.plot(paths[j], color=c, lw=0.8, alpha=0.7)
    ax.axhline(TARGET, color="red", ls="--", lw=1.8, label="60,000 target")
    ax.axhline(S0, color="black", ls=":", lw=1.2, label=f"start {S0:,.0f}")
    ax.set_title("40 sample paths (orange = touched 60,000)")
    ax.set_xlabel("trading day")
    ax.set_ylabel("TAIEX level")
    ax.legend(fontsize=9)
    fig.suptitle("^TWII path risk: drawdown + sample trajectories (zero drift)",
                 fontsize=13, weight="bold")
    fig.tight_layout()
    chart2 = os.path.join(HERE, "chart_drawdown_and_paths.png")
    fig.savefig(chart2, dpi=130)
    plt.close(fig)

    print("=== SUMMARY ===")
    print(f"data: {data_source}  {first_date}..{last_date}  n={len(close)}")
    print(f"S0={S0:,.1f}  target={TARGET:,.0f}  needed={needed_pct:.1f}%")
    print(f"GARCH dist chosen: {chosen_dist}  AIC={aic}  persistence={persistence:.4f}  nu={nu}")
    for m in ("zero", "historical"):
        b = results[m]
        print(f"[{m:>10} drift] P(touch)={b['p_touch_60000_anytime']*100:5.2f}%  "
              f"median_end={b['final_level_median']:,.0f}  "
              f"p05={b['final_level_p05']:,.0f}  p95={b['final_level_p95']:,.0f}  "
              f"mdd_median={b['max_drawdown_median']*100:4.1f}%  mdd_p95={b['max_drawdown_p95']*100:4.1f}%  "
              f"mdd_med|touch={None if b['max_dd_median_given_touch'] is None else round(b['max_dd_median_given_touch']*100,1)}%")
    print(f"EMPIRICAL: {hits_29}/{windows} rolling 63d windows hit +{needed_pct:.1f}%  "
          f"= {emp_freq_29*100:.2f}%   (max ever fwd63 = +{(fwd_max_ratios.max()-1)*100:.1f}%)")
    print(f"charts: {chart1} | {chart2}")
    print(f"results: {out_path}")


if __name__ == "__main__":
    main()
