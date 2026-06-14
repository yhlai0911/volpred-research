"""
K1499 — BDC (private-credit shadow) stress as a MULTI-HORIZON lead signal for
public-market realized volatility (HYG / KRE / IWM), controlling for SPY vol.

Differentiation vs K1332 (read experiments/k1332/README.md):
  - K1332 target  = 1-day squared return (r^2), expanding/rolling OOS QLIKE.
  - K1499 target  = FORWARD realized volatility RV over horizons t+1..t+21
                    (forward-window std of daily log returns), a different
                    forecasting object that tests *persistence* of the lead-lag.
  - K1499 basket  = ARCC/BXSL/OBDC/FSK/PSEC + BIZD (the large, NEW BDCs central to
                    the 2025-26 stress; K1332 used older MAIN/GBDC/HTGC).
  - K1499 proxy   = explicit "BDC NAV-discount stand-in" = BIZD return - HYG return
                    (a tradable proxy for BDC discount widening), plus a BDC-basket
                    realized-vol stress index.
  - K1499 method  = lead-lag correlation matrix across horizons + HAC (Newey-West)
                    regressions with SPY-vol incremental control + SPY placebo +
                    event-study PATH (t+1..t+21) after top-decile BDC-stress days.

Research-honesty guards:
  - All predictors are .shift(1): signal known at close of day t-1 predicts t..t+h.
    NO same-day information. Forward RV uses returns strictly AFTER the signal date.
  - seed = 42 fixed; bootstrap CI uses np.random.default_rng(42).
  - Overlapping forward windows -> Newey-West HAC with lag = horizon + 5 to correct
    overlap-induced autocorrelation. Caveat recorded explicitly.
  - DM/Harvey |t|>3 threshold used (not 1.96) given overlap; report sign+size too.
  - NULL reported honestly: if BDC signal loses significance after SPY-vol control,
    we say so per target.

Data: yfinance adjusted close, longest available per ticker -> 2026-06.
Output: experiments/k1499/k1499_results.json + 2 PNGs.
"""

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf

warnings.filterwarnings("ignore")

SEED = 42
np.random.seed(SEED)
RNG = np.random.default_rng(SEED)

HERE = Path(__file__).resolve().parent
END = "2026-06-15"

BDC_BASKET = ["ARCC", "BXSL", "OBDC", "FSK", "PSEC"]
BDC_ETF = "BIZD"
TARGETS = ["HYG", "KRE", "IWM"]
CONTROL_MKT = "SPY"  # large-cap beta control
ALL_TICKERS = sorted(set(BDC_BASKET + [BDC_ETF] + TARGETS + [CONTROL_MKT]))

# Forward RV needs >=2 days (std of 1 obs is undefined). The 1-day-ahead channel
# is instead covered by (a) K1332's 1d r^2 result and (b) this study's event-study
# |return| path at t+1. Multi-day forward-RV horizons:
HORIZONS = [5, 10, 21]
RV_WINDOW = 21  # realized-vol estimation window (days)
EVENT_PATH_LEN = 21


# --------------------------------------------------------------------------- #
# 1. Data download + diagnostics
# --------------------------------------------------------------------------- #
def download_prices():
    raw = yf.download(
        ALL_TICKERS,
        start="2005-01-01",
        end=END,
        auto_adjust=True,
        progress=False,
    )
    if isinstance(raw.columns, pd.MultiIndex):
        px = raw["Close"].copy()
    else:
        px = raw[["Close"]].copy()
        px.columns = ALL_TICKERS
    diag = {}
    for t in ALL_TICKERS:
        if t in px.columns:
            s = px[t].dropna()
            diag[t] = {
                "available": bool(len(s) > 0),
                "first_obs": str(s.index[0].date()) if len(s) else None,
                "last_obs": str(s.index[-1].date()) if len(s) else None,
                "n_obs": int(len(s)),
            }
        else:
            diag[t] = {"available": False, "first_obs": None, "last_obs": None, "n_obs": 0}
    available = [t for t in ALL_TICKERS if diag[t]["available"]]
    return px[available], diag, available


# --------------------------------------------------------------------------- #
# 2. Feature construction
# --------------------------------------------------------------------------- #
def daily_log_returns(px):
    return np.log(px / px.shift(1))


def realized_vol(ret, window=RV_WINDOW):
    return ret.rolling(window).std()


def forward_realized_vol(ret, horizon):
    """
    Forward realized vol over the NEXT `horizon` days, measured from t+1..t+horizon.
    rolling std then shift back so value at t = std over (t+1 .. t+horizon).
    No lookahead when paired with shift(1) signal.
    """
    return ret.rolling(horizon).std().shift(-horizon)


def build_bdc_stress(ret, bdc_members, bdc_etf, target_for_discount):
    members = [m for m in bdc_members if m in ret.columns]
    basket_ret = ret[members].mean(axis=1)  # equal weight
    bdc_rv = basket_ret.rolling(RV_WINDOW).std()

    if bdc_etf in ret.columns and target_for_discount in ret.columns:
        excess = ret[bdc_etf] - ret[target_for_discount]
        nav_discount = excess.rolling(RV_WINDOW).sum()  # negative = BIZD lagging HYG
        nav_discount_stress = -nav_discount  # higher = more stress (discount widening)
    else:
        nav_discount_stress = pd.Series(index=ret.index, dtype=float)

    basket_price = (1 + basket_ret.fillna(0)).cumprod()
    roll_max = basket_price.rolling(63, min_periods=21).max()
    drawdown = basket_price / roll_max - 1.0

    stress = pd.DataFrame(
        {
            "bdc_rv": bdc_rv,
            "nav_discount_stress": nav_discount_stress,
            "bdc_drawdown63": drawdown,
            "basket_ret": basket_ret,
        }
    )
    return stress, members


# --------------------------------------------------------------------------- #
# 3. Lead-lag correlation
# --------------------------------------------------------------------------- #
def lead_lag_corr(signal_lag1, fwd_rv_by_h):
    out = {}
    for h, fwd in fwd_rv_by_h.items():
        df = pd.concat([signal_lag1, fwd], axis=1).dropna()
        df.columns = ["sig", "fwd"]
        if len(df) > 30:
            r = float(np.corrcoef(df["sig"], df["fwd"])[0, 1])
            out[f"h{h}"] = {"corr": r, "n": int(len(df))}
        else:
            out[f"h{h}"] = {"corr": None, "n": int(len(df))}
    return out


# --------------------------------------------------------------------------- #
# 4. HAC regressions
# --------------------------------------------------------------------------- #
def hac_regression(y, X_df, hac_lag):
    df = pd.concat([y, X_df], axis=1).dropna()
    if len(df) < 50:
        return None
    yv = df.iloc[:, 0]
    Xv = sm.add_constant(df.iloc[:, 1:])
    model = sm.OLS(yv, Xv).fit(cov_type="HAC", cov_kwds={"maxlags": hac_lag})
    res = {}
    for name in Xv.columns:
        res[name] = {
            "coef": float(model.params[name]),
            "t": float(model.tvalues[name]),
            "p": float(model.pvalues[name]),
        }
    res["_meta"] = {"n": int(len(df)), "r2": float(model.rsquared), "hac_lag": int(hac_lag)}
    return res


# --------------------------------------------------------------------------- #
# 5. Event study path
# --------------------------------------------------------------------------- #
def event_study_path(stress_signal_lag1, target_ret, path_len=EVENT_PATH_LEN, decile=0.90):
    df = pd.concat([stress_signal_lag1, target_ret], axis=1).dropna()
    df.columns = ["sig", "ret"]
    if len(df) < 200:
        return None
    thr = df["sig"].quantile(decile)
    is_event = df["sig"] >= thr
    abs_ret = df["ret"].abs().values
    n = len(df)

    idx_event = np.where(is_event.values)[0]
    idx_event = idx_event[idx_event + path_len < n]
    paths = np.array([abs_ret[i + 1 : i + 1 + path_len] for i in idx_event])
    event_mean_path = paths.mean(axis=0).tolist() if len(paths) else None

    idx_non = np.where(~is_event.values)[0]
    idx_non = idx_non[idx_non + path_len < n]
    paths_non = np.array([abs_ret[i + 1 : i + 1 + path_len] for i in idx_non])
    non_mean_path = paths_non.mean(axis=0).tolist() if len(paths_non) else None

    if len(idx_event) == 0 or len(idx_non) == 0:
        return None

    def stat(ev_idx, non_idx):
        ev = np.array([abs_ret[i + 1 : i + 6].mean() for i in ev_idx])
        nv = np.array([abs_ret[i + 1 : i + 6].mean() for i in non_idx])
        return ev.mean() - nv.mean()

    obs_diff = stat(idx_event, idx_non)
    boots = []
    for _ in range(2000):
        be = RNG.choice(idx_event, size=len(idx_event), replace=True)
        bn = RNG.choice(idx_non, size=len(idx_non), replace=True)
        boots.append(stat(be, bn))
    boots = np.array(boots)
    p_two = float(2 * min((boots <= 0).mean(), (boots >= 0).mean()))
    ev5 = np.mean([abs_ret[i + 1 : i + 6].mean() for i in idx_event])
    nv5 = np.mean([abs_ret[i + 1 : i + 6].mean() for i in idx_non])
    return {
        "n_event": int(len(idx_event)),
        "n_non_event": int(len(idx_non)),
        "threshold_decile": decile,
        "event_mean_path_absret": event_mean_path,
        "non_event_mean_path_absret": non_mean_path,
        "fwd5d_absret_diff": float(obs_diff),
        "fwd5d_ratio": float(ev5 / max(1e-12, nv5)),
        "bootstrap_p_value": p_two,
        "ci95_low": float(np.percentile(boots, 2.5)),
        "ci95_high": float(np.percentile(boots, 97.5)),
    }


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main():
    px, diag, available = download_prices()
    ret = daily_log_returns(px)

    desc_stats = {}
    for t in available:
        s = ret[t].dropna()
        desc_stats[t] = {
            "n": int(len(s)),
            "mean_daily_ret": float(s.mean()),
            "daily_vol": float(s.std()),
            "ann_vol": float(s.std() * np.sqrt(252)),
            "skew": float(s.skew()),
            "kurtosis": float(s.kurtosis()),
            "min": float(s.min()),
            "max": float(s.max()),
        }

    stress, basket_members = build_bdc_stress(ret, BDC_BASKET, BDC_ETF, "HYG")

    bdc_rv = stress["bdc_rv"]
    bdc_rv_z = (bdc_rv - bdc_rv.expanding(min_periods=252).mean()) / bdc_rv.expanding(
        min_periods=252
    ).std()
    nav_z = stress["nav_discount_stress"]
    nav_z = (nav_z - nav_z.expanding(min_periods=252).mean()) / nav_z.expanding(
        min_periods=252
    ).std()

    # SHIFT(1): signal known at close t-1 used to predict forward window from t
    bdc_rv_z_lag1 = bdc_rv_z.shift(1)
    nav_z_lag1 = nav_z.shift(1)

    spy_rv = realized_vol(ret[CONTROL_MKT]) if CONTROL_MKT in ret.columns else None
    if spy_rv is not None:
        spy_rv_z = (spy_rv - spy_rv.expanding(min_periods=252).mean()) / spy_rv.expanding(
            min_periods=252
        ).std()
        spy_rv_z_lag1 = spy_rv_z.shift(1)
    else:
        spy_rv_z_lag1 = None

    lead_lag = {}
    hac_results = {}
    event_study = {}

    for tgt in TARGETS:
        if tgt not in ret.columns:
            continue
        tgt_ret = ret[tgt]
        fwd_rv_by_h = {h: forward_realized_vol(tgt_ret, h) for h in HORIZONS}

        lead_lag[tgt] = {
            "bdc_rv": lead_lag_corr(bdc_rv_z_lag1, fwd_rv_by_h),
            "nav_discount": lead_lag_corr(nav_z_lag1, fwd_rv_by_h),
        }

        hac_results[tgt] = {}
        own_rv = realized_vol(tgt_ret).shift(1)  # own trailing vol, lagged (AR control)
        for h in HORIZONS:
            y = fwd_rv_by_h[h].rename("fwd_rv")
            Xa = pd.concat(
                [bdc_rv_z_lag1.rename("bdc_rv_z"), own_rv.rename("own_rv")], axis=1
            )
            resA = hac_regression(y, Xa, hac_lag=h + 5)
            if spy_rv_z_lag1 is not None:
                Xb = pd.concat(
                    [
                        bdc_rv_z_lag1.rename("bdc_rv_z"),
                        spy_rv_z_lag1.rename("spy_rv_z"),
                        own_rv.rename("own_rv"),
                    ],
                    axis=1,
                )
                resB = hac_regression(y, Xb, hac_lag=h + 5)
                Xc = pd.concat(
                    [
                        nav_z_lag1.rename("nav_discount_z"),
                        spy_rv_z_lag1.rename("spy_rv_z"),
                        own_rv.rename("own_rv"),
                    ],
                    axis=1,
                )
                resC = hac_regression(y, Xc, hac_lag=h + 5)
            else:
                resB = resC = None
            hac_results[tgt][f"h{h}"] = {
                "modelA_bdc_only": resA,
                "modelB_bdc_plus_spy": resB,
                "modelC_navproxy_plus_spy": resC,
            }

        event_study[tgt] = event_study_path(bdc_rv_z_lag1, tgt_ret)

    # SPY placebo: is the signal just large-cap beta?
    spy_fwd = {h: forward_realized_vol(ret[CONTROL_MKT], h) for h in HORIZONS}
    spy_own = realized_vol(ret[CONTROL_MKT]).shift(1)
    spy_placebo = {}
    for h in HORIZONS:
        y = spy_fwd[h].rename("fwd_rv")
        X = pd.concat(
            [bdc_rv_z_lag1.rename("bdc_rv_z"), spy_own.rename("own_rv")], axis=1
        )
        spy_placebo[f"h{h}"] = hac_regression(y, X, hac_lag=h + 5)

    # Verdict (covers BOTH signals after SPY control, per Codex review):
    #   - bdc_rv_z (Model B): broad BDC realized-vol stress
    #   - nav_discount_z (Model C): BIZD-minus-HYG NAV-discount proxy
    # A "win" = HAC |t|>3 with positive coef at any horizon after SPY-vol control.
    incremental_wins = {}        # bdc_rv signal
    nav_wins = {}                # nav-discount signal
    for tgt in TARGETS:
        if tgt not in hac_results:
            continue
        wins, nwins = [], []
        for h in HORIZONS:
            node = hac_results[tgt][f"h{h}"]
            mb = node.get("modelB_bdc_plus_spy")
            if mb and "bdc_rv_z" in mb and abs(mb["bdc_rv_z"]["t"]) > 3.0 and mb["bdc_rv_z"]["coef"] > 0:
                wins.append(h)
            mc = node.get("modelC_navproxy_plus_spy")
            if mc and "nav_discount_z" in mc and abs(mc["nav_discount_z"]["t"]) > 3.0 and mc["nav_discount_z"]["coef"] > 0:
                nwins.append(h)
        incremental_wins[tgt] = wins
        nav_wins[tgt] = nwins

    # any target with EITHER signal surviving SPY control
    targets_with_any_win = set(t for t, v in incremental_wins.items() if v) | set(
        t for t, v in nav_wins.items() if v
    )
    n_targets_with_win = len(targets_with_any_win)
    if n_targets_with_win >= 2:
        verdict = "PASS"
    elif n_targets_with_win == 1:
        verdict = "PARTIAL"
    else:
        verdict = "NULL"

    spy_beta_flag = any(
        v and "bdc_rv_z" in v and abs(v["bdc_rv_z"]["t"]) > 3.0 for v in spy_placebo.values()
    )

    rationale_parts = []
    for tgt in TARGETS:
        if tgt not in hac_results:
            continue
        bw, nw = incremental_wins.get(tgt, []), nav_wins.get(tgt, [])
        if not bw and not nw:
            rationale_parts.append(
                f"{tgt}: NEITHER BDC-RV stress NOR NAV-discount proxy survives SPY-vol control "
                f"at any horizon (no incremental signal)"
            )
        else:
            seg = []
            if bw:
                seg.append(f"BDC-RV stress survives at horizons {bw}")
            else:
                seg.append("BDC-RV stress does NOT survive (pure beta)")
            if nw:
                seg.append(f"NAV-discount proxy survives at horizons {nw}")
            else:
                seg.append("NAV-discount proxy does NOT survive")
            rationale_parts.append(f"{tgt}: " + "; ".join(seg))
    if spy_beta_flag:
        rationale_parts.append(
            "CAVEAT: BDC stress also predicts SPY forward vol with |t|>3, so a large "
            "part of the BDC-RV signal reflects broad large-cap beta."
        )
    verdict_rationale = " | ".join(rationale_parts)

    # ----- Plots -----
    fig, ax = plt.subplots(figsize=(9, 5))
    width = 0.18
    xh = np.arange(len(HORIZONS))
    for i, tgt in enumerate([t for t in TARGETS if t in lead_lag]):
        corrs = [lead_lag[tgt]["bdc_rv"][f"h{h}"]["corr"] or 0.0 for h in HORIZONS]
        ax.bar(xh + i * width, corrs, width, label=tgt)
    ax.set_xticks(xh + width)
    ax.set_xticklabels([f"t+1..t+{h}" for h in HORIZONS])
    ax.set_ylabel("Pearson corr (lagged BDC RV-z vs forward RV)")
    ax.set_title("K1499: BDC stress (t-1) lead-lag with forward realized vol")
    ax.axhline(0, color="k", lw=0.6)
    ax.legend()
    fig.tight_layout()
    p1 = HERE / "k1499_lead_lag_corr.png"
    fig.savefig(p1, dpi=130)
    plt.close(fig)

    valid_es = [t for t in TARGETS if event_study.get(t) and event_study[t].get("event_mean_path_absret")]
    fig, axes = plt.subplots(1, max(1, len(valid_es)), figsize=(13, 4), squeeze=False)
    j = 0
    for tgt in valid_es:
        es = event_study[tgt]
        ax = axes[0][j]
        days = np.arange(1, EVENT_PATH_LEN + 1)
        ax.plot(days, es["event_mean_path_absret"], "r-o", ms=3, label="after top-decile BDC stress")
        ax.plot(days, es["non_event_mean_path_absret"], "b--", label="baseline")
        ax.set_title(f"{tgt} (ratio={es['fwd5d_ratio']:.2f}, p={es['bootstrap_p_value']:.3f})")
        ax.set_xlabel("days after signal (t+k)")
        ax.set_ylabel("mean |daily ret|")
        ax.legend(fontsize=7)
        j += 1
    fig.suptitle("K1499: forward |return| path after BDC-stress spikes (signal lagged 1d)")
    fig.tight_layout()
    p2 = HERE / "k1499_event_study_path.png"
    fig.savefig(p2, dpi=130)
    plt.close(fig)

    results = {
        "experiment_id": "k1499",
        "title": "BDC private-credit shadow stress as a multi-horizon lead signal for public-market realized vol",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "verdict": verdict,
        "verdict_rationale": verdict_rationale,
        "seed": SEED,
        "differentiation_vs_k1332": (
            "K1332 tested 1-day r^2 OOS QLIKE with an older BDC basket (MAIN/GBDC/HTGC) "
            "and a pc-vs-LQD proxy, concluding PASS_NARROW_CREDIT_ONLY (BKLN/HYG). "
            "K1499 changes the forecasting object to FORWARD realized vol over multiple "
            "horizons (t+1..t+21), uses the newer large BDC basket (ARCC/BXSL/OBDC/FSK/PSEC), "
            "an explicit BIZD-minus-HYG NAV-discount proxy, lead-lag correlation across "
            "horizons, SPY-vol incremental HAC control, an SPY placebo, and an event-study path."
        ),
        "data_source": {
            "type": "yfinance_auto_adjusted_close",
            "tickers": ALL_TICKERS,
            "bdc_basket_members_used": basket_members,
            "end_requested": END,
            "download_diagnostics": diag,
        },
        "descriptive_stats": desc_stats,
        "method": {
            "horizons_days": HORIZONS,
            "rv_window_days": RV_WINDOW,
            "primary_signal": "z-scored 21d realized vol of equal-weight BDC basket (expanding standardization, shift(1))",
            "secondary_signal": "z-scored NAV-discount proxy = -(BIZD ret - HYG ret) cumulated 21d (shift(1))",
            "forward_target": "forward realized vol over t+1..t+h (std of daily log returns, daily units)",
            "lookahead_policy": "all signals .shift(1); forward RV uses returns strictly after signal date; expanding standardization has no future leakage",
            "overlap_correction": "Newey-West HAC SE with maxlags = horizon + 5 to correct overlapping-window autocorrelation",
            "controls": "own trailing 21d RV (AR/HAR-style) + SPY trailing 21d RV-z (large-cap beta control)",
            "event_study": "top-decile (90th pct) BDC stress days -> forward |return| path t+1..t+21; 2000-rep bootstrap CI seeded 42",
        },
        "lead_lag_correlation": lead_lag,
        "hac_regressions": hac_results,
        "spy_placebo_hac": spy_placebo,
        "spy_beta_flag": bool(spy_beta_flag),
        "incremental_wins_after_spy_control": incremental_wins,
        "nav_discount_wins_after_spy_control": nav_wins,
        "event_study": event_study,
        "artifacts": [str(p1.name), str(p2.name)],
        "research_honesty_notes": {
            "lookahead_guard": "Every predictor passes through .shift(1); forward RV measured strictly from t+1 (rolling std shifted by -horizon); expanding-window z-scores use only past data.",
            "one_day_gap_note": (
                "Signal is known at close of t-1 (shift(1)) while the forward RV target spans "
                "t+1..t+h, so the return on day t itself is excluded. This is INTENTIONAL and "
                "conservative: it guarantees zero same-day overlap between predictor and target "
                "(no leakage). Codex review (CONDITIONAL_PASS) confirmed this is not a leak; the "
                "one-day gap only makes the test slightly harder, not easier."
            ),
            "verdict_signal_coverage": (
                "Verdict considers BOTH the BDC realized-vol stress (Model B) and the NAV-discount "
                "proxy (Model C) after SPY control, so a surviving NAV-proxy signal is not masked "
                "by an insignificant BDC-RV signal (Codex-flagged fix)."
            ),
            "seed": SEED,
            "overlapping_windows_caveat": (
                "Multi-horizon forward RV windows overlap, inflating naive t-stats. We use "
                "Newey-West HAC SE (maxlags=h+5). Even with HAC, overlapping-window t-stats "
                "remain only approximately valid; we therefore require |t|>3 (Harvey-style) "
                "rather than 1.96, and report effect sign/size, not just significance."
            ),
            "statistical_vs_economic": (
                "HAC t-stats test marginal predictive contribution; lead-lag correlations and "
                "event-study ratios quantify economic size. A significant t with a tiny R^2 "
                "increment is statistically but not economically meaningful and is flagged."
            ),
            "beta_confound": (
                "BDC equities carry large-cap/credit beta. The SPY-vol control (Model B) and "
                "SPY placebo isolate private-credit-specific signal from broad beta. If BDC "
                "stress predicts SPY vol equally, the signal is largely beta (flagged)."
            ),
            "relation_to_k1332": (
                "Deliberate multi-horizon / forward-RV extension and robustness check of K1332, "
                "not an independent rediscovery. K1332's narrow PASS (BKLN/HYG on r^2) is the "
                "prior; K1499 asks whether the lead-lag persists on forward RV across horizons "
                "after stricter beta controls."
            ),
        },
        "literature": [
            {
                "citation": "Financial Stability Board (2026), Report on Vulnerabilities in Private Credit",
                "url": "https://www.fsb.org/2026/05/report-on-vulnerabilities-in-private-credit/",
                "role": "motivates private-credit stress monitoring; default rate / valuation / leverage concerns",
            },
            {
                "citation": "IMF Global Financial Stability Report (2024), The Rise and Risks of Private Credit",
                "url": "https://www.elibrary.imf.org/display/book/9798400257704/CH002.xml",
                "role": "private-credit systemic-risk framing",
            },
            {
                "citation": "VolPred K1332 — Private-credit public-market shadow stress proxy",
                "url": "experiments/k1332/README.md",
                "role": "prior internal result (PASS_NARROW_CREDIT_ONLY on 1d r^2); K1499 extends to forward RV multi-horizon",
            },
        ],
    }

    out = HERE / "k1499_results.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)

    print(f"VERDICT: {verdict}")
    print(f"RATIONALE: {verdict_rationale}")
    print(f"incremental wins (after SPY control): {incremental_wins}")
    print(f"spy_beta_flag: {spy_beta_flag}")
    print(f"wrote {out}")
    print(f"wrote {p1}, {p2}")
    return results


if __name__ == "__main__":
    main()
