"""
K1581 — Maritime Chokepoint / Supply-Chain Stress (GSCPI) vs Commodity/Shipping/Retail ETF Vol
==============================================================================================

(Brief originally requested K1573 but that ID was already used for an unrelated CHIPS Act
experiment. Renumbered to K1581 to preserve experimental ledger integrity.)

Hypothesis: Monthly GSCPI shocks (Δz_t) predict next-month realized volatility of
commodity (USO oil, DBA agriculture), retail (XRT), and shipping/transport (IYT) ETFs.

Lookahead control: Signal observed at month-end t; RV window strictly indexed from
the first trading day of month t+1 forward (no contemporaneous month leakage).

Tests:
  A) HAC-OLS (Newey-West lag=6) per ETF: cum_RV[t+1..t+22 trading days] ~ const + β·Δz_t
  B) Welch t-test: high-stress months (z>1.5) T+22 cum RV vs benign (|z|<0.5)
  C) Bootstrap 95% CI on β (1000 reps, seed=42, IID resample over month rows)

Data sources:
  - GSCPI: NY Fed Liberty Street, monthly, 1998-01 to ~current (xlsx)
  - ETFs: yfinance daily Adj Close, log-returns

Sample: 2018-01 → most recent complete month
Seed: 42
"""

from __future__ import annotations

import io
import json
import urllib.request
from datetime import datetime
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
import yfinance as yf
from scipy import stats

SEED = 42
ETFS = ["USO", "DBA", "XRT", "IYT"]
START = "2018-01-01"
END = "2026-06-30"
RV_WINDOW_DAYS = 22  # one trading month forward window
HAC_LAG = 6
HIGH_STRESS_Z = 1.5
BENIGN_Z = 0.5
BOOT_REPS = 1000

OUT_DIR = Path(__file__).resolve().parent
FIG_DIR = OUT_DIR / "figs"
FIG_DIR.mkdir(exist_ok=True)


# --------------------------------------------------------------------------------------
# Data loaders
# --------------------------------------------------------------------------------------
def fetch_gscpi() -> pd.Series:
    """Fetch GSCPI monthly series from NY Fed xlsx."""
    url = (
        "https://www.newyorkfed.org/medialibrary/research/interactives/"
        "gscpi/downloads/gscpi_data.xlsx"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        raw = r.read()
    df = pd.read_excel(
        io.BytesIO(raw),
        sheet_name="GSCPI Monthly Data",
        skiprows=4,
        header=None,
        names=["Date", "GSCPI", "_a", "_b"],
        usecols=[0, 1],
    )
    df["Date"] = pd.to_datetime(df["Date"], format="%d-%b-%Y", errors="coerce")
    df = df.dropna(subset=["Date", "GSCPI"]).sort_values("Date")
    s = df.set_index("Date")["GSCPI"].astype(float)
    s.name = "GSCPI"
    return s


def fetch_etfs(tickers: list[str], start: str, end: str) -> pd.DataFrame:
    df = yf.download(
        tickers,
        start=start,
        end=end,
        progress=False,
        auto_adjust=True,
        group_by="column",
    )
    if isinstance(df.columns, pd.MultiIndex):
        closes = df["Close"].copy()
    else:
        closes = df[["Close"]].rename(columns={"Close": tickers[0]})
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    return closes.dropna(how="all").sort_index()


# --------------------------------------------------------------------------------------
# Feature engineering
# --------------------------------------------------------------------------------------
def realized_vol_forward(prices: pd.DataFrame, window: int) -> pd.DataFrame:
    """At index t, returns annualized RV computed from log-returns t+1..t+window.

    Implemented via reverse-rolling then re-reverse, then shift(-1) so the value at row t
    sums sq[t+1] ... sq[t+window].
    """
    log_ret = np.log(prices / prices.shift(1))
    sq = log_ret ** 2
    rev = sq[::-1]
    fwd_sum_rev = rev.rolling(window).sum()
    fwd_sum = fwd_sum_rev[::-1]
    # at index t, fwd_sum.loc[t] = sq[t] + sq[t+1] + ... + sq[t+window-1]
    # we want t+1 .. t+window  → shift -1
    fwd_sum = fwd_sum.shift(-1)
    rv_ann = np.sqrt(fwd_sum * 252.0 / window)
    return rv_ann


def month_end_panel(
    gscpi: pd.Series, etf_prices: pd.DataFrame, window_start: str
) -> pd.DataFrame:
    """Build panel: at each month-end trading day t, attach GSCPI z and Δz of that month."""
    # Restrict GSCPI to analysis window, recompute z within window
    g_in = gscpi[gscpi.index >= pd.Timestamp(window_start)].copy()
    z = (g_in - g_in.mean()) / g_in.std(ddof=1)
    dz = z.diff()

    # ETF trading-day index → last trading day per month
    last_trading = (
        pd.Series(etf_prices.index, index=etf_prices.index).resample("ME").last().dropna()
    )

    z_pm = z.copy()
    z_pm.index = z_pm.index.to_period("M")
    dz_pm = dz.copy()
    dz_pm.index = dz_pm.index.to_period("M")

    rows = []
    for trade_day in last_trading.values:
        per = pd.Timestamp(trade_day).to_period("M")
        if per in z_pm.index:
            rows.append(
                {
                    "month_end_trade_day": pd.Timestamp(trade_day),
                    "period": str(per),
                    "z": float(z_pm.loc[per]),
                    "dz": float(dz_pm.loc[per]) if pd.notna(dz_pm.loc[per]) else np.nan,
                }
            )
    return pd.DataFrame(rows)


def attach_rv(panel: pd.DataFrame, rv_fwd: pd.DataFrame, ticker: str) -> pd.DataFrame:
    rv_vals = rv_fwd[ticker].reindex(panel["month_end_trade_day"]).values
    out = panel.copy()
    out[f"rv_fwd_{ticker}"] = rv_vals
    return out.dropna(subset=["dz", f"rv_fwd_{ticker}"]).reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------
def hac_ols(y: np.ndarray, x: np.ndarray, lag: int) -> dict:
    X = sm.add_constant(x)
    model = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lag})
    return {
        "beta": float(model.params[1]),
        "se_hac": float(model.bse[1]),
        "t_hac": float(model.tvalues[1]),
        "p_hac": float(model.pvalues[1]),
        "alpha": float(model.params[0]),
        "r2": float(model.rsquared),
        "n": int(model.nobs),
    }


def bootstrap_beta(
    y: np.ndarray, x: np.ndarray, reps: int, seed: int
) -> tuple[float, float, float]:
    rng = np.random.default_rng(seed)
    n = len(y)
    Xfull = sm.add_constant(x)
    betas = np.empty(reps)
    for i in range(reps):
        idx = rng.integers(0, n, size=n)
        Xs = Xfull[idx]
        ys = y[idx]
        try:
            b = np.linalg.lstsq(Xs, ys, rcond=None)[0]
            betas[i] = b[1]
        except Exception:
            betas[i] = np.nan
    betas = betas[~np.isnan(betas)]
    return (
        float(np.quantile(betas, 0.025)),
        float(np.quantile(betas, 0.975)),
        float(np.median(betas)),
    )


def welch_test(panel: pd.DataFrame, ticker: str) -> dict:
    high = panel.loc[panel["z"] > HIGH_STRESS_Z, f"rv_fwd_{ticker}"].values
    benign = panel.loc[panel["z"].abs() < BENIGN_Z, f"rv_fwd_{ticker}"].values
    if len(high) < 3 or len(benign) < 3:
        return {
            "n_high": int(len(high)),
            "n_benign": int(len(benign)),
            "mean_high": float(np.nanmean(high)) if len(high) else None,
            "mean_benign": float(np.nanmean(benign)) if len(benign) else None,
            "t": None,
            "p": None,
            "cohen_d": None,
            "note": "insufficient cells",
        }
    t, p = stats.ttest_ind(high, benign, equal_var=False, nan_policy="omit")
    s_pool = np.sqrt(
        (
            np.nanvar(high, ddof=1) * (len(high) - 1)
            + np.nanvar(benign, ddof=1) * (len(benign) - 1)
        )
        / (len(high) + len(benign) - 2)
    )
    d = float((np.nanmean(high) - np.nanmean(benign)) / s_pool) if s_pool > 0 else None
    return {
        "n_high": int(len(high)),
        "n_benign": int(len(benign)),
        "mean_high": float(np.nanmean(high)),
        "mean_benign": float(np.nanmean(benign)),
        "t": float(t),
        "p": float(p),
        "cohen_d": d,
    }


# --------------------------------------------------------------------------------------
# Plot
# --------------------------------------------------------------------------------------
def overlay_plot(gscpi: pd.Series, rv_fwd: pd.DataFrame) -> Path:
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    g_in = gscpi[
        (gscpi.index >= pd.Timestamp(START)) & (gscpi.index <= pd.Timestamp(END))
    ]
    axes[0].plot(g_in.index, g_in.values, color="black", lw=1.2, label="GSCPI (raw level)")
    z = (g_in - g_in.mean()) / g_in.std(ddof=1)
    ax0b = axes[0].twinx()
    ax0b.plot(z.index, z.values, color="darkblue", lw=0.8, alpha=0.4, label="z-score")
    ax0b.axhline(HIGH_STRESS_Z, color="red", ls="--", lw=0.8, alpha=0.6)
    ax0b.set_ylabel("z-score")
    axes[0].axhline(0, color="gray", ls=":", lw=0.6)
    axes[0].set_ylabel("GSCPI level")
    axes[0].set_title(
        "K1581: GSCPI vs Commodity/Retail/Transport ETF 22d Forward Realized Vol"
    )
    axes[0].legend(loc="upper left", fontsize=8)
    ax0b.legend(loc="upper right", fontsize=8)
    for tk in ETFS:
        axes[1].plot(rv_fwd.index, rv_fwd[tk].values, lw=0.9, label=tk, alpha=0.85)
    axes[1].set_ylabel("Forward 22d Realized Vol (annualized)")
    axes[1].set_xlabel("Date")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(alpha=0.3)
    axes[0].grid(alpha=0.3)
    fig.tight_layout()
    out_path = FIG_DIR / "k1581_overlay.png"
    fig.savefig(out_path, dpi=110)
    plt.close(fig)
    return out_path


# --------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------
def main() -> None:
    np.random.seed(SEED)
    print("[K1581] Fetching GSCPI from NY Fed...")
    gscpi = fetch_gscpi()
    print(
        f"  GSCPI range {gscpi.index.min().date()} → {gscpi.index.max().date()} (n={len(gscpi)})"
    )

    print(f"[K1581] Fetching ETF prices {ETFS}...")
    prices = fetch_etfs(ETFS, START, END)
    print(
        f"  ETF rows {len(prices)}; date {prices.index.min().date()} → {prices.index.max().date()}"
    )

    rv_fwd = realized_vol_forward(prices, RV_WINDOW_DAYS)
    panel_base = month_end_panel(gscpi, prices, START)
    print(f"[K1581] Month-end signal panel rows: {len(panel_base)}")

    fig_path = overlay_plot(gscpi, rv_fwd)
    print(f"[K1581] Saved overlay → {fig_path}")

    results: dict = {
        "experiment_id": "K1581",
        "title": "GSCPI Maritime/Supply-Chain Stress vs Commodity/Shipping/Retail ETF Forward Vol",
        "id_note": (
            "Brief specified K1573 but that ID was used by unrelated CHIPS Act experiment; "
            "renumbered to K1581 (next free) to preserve ledger integrity."
        ),
        "run_timestamp": datetime.utcnow().isoformat() + "Z",
        "seed": SEED,
        "period": {
            "start": START,
            "end": str(prices.index.max().date()),
            "n_months_in_panel": int(len(panel_base)),
        },
        "data_sources": {
            "GSCPI": "NY Fed Liberty Street (newyorkfed.org/research/policy/gscpi)",
            "ETFs": "yfinance daily Close (auto_adjust=True)",
        },
        "lookahead_control": (
            "Signal Δz observed at month-end t (NY Fed releases GSCPI for month t shortly "
            "after month-end). Forward RV window strictly indexed t+1..t+22 trading days "
            "via reverse-rolling + shift(-1) in realized_vol_forward(). No use of returns "
            "from month t or earlier in the RV computation."
        ),
        "params": {
            "rv_window_days": RV_WINDOW_DAYS,
            "hac_lag": HAC_LAG,
            "high_stress_z": HIGH_STRESS_Z,
            "benign_z": BENIGN_Z,
            "bootstrap_reps": BOOT_REPS,
        },
        "tests": {},
    }

    summary_lines = []
    for tk in ETFS:
        panel = attach_rv(panel_base, rv_fwd, tk)
        if len(panel) < 12:
            results["tests"][tk] = {"error": f"too few months ({len(panel)})"}
            summary_lines.append(f"  {tk}: insufficient n={len(panel)}")
            continue
        y = panel[f"rv_fwd_{tk}"].values
        x = panel["dz"].values
        ols = hac_ols(y, x, HAC_LAG)
        boot_lo, boot_hi, boot_med = bootstrap_beta(y, x, BOOT_REPS, SEED)
        welch = welch_test(panel, tk)
        results["tests"][tk] = {
            "ols_hac": ols,
            "bootstrap_95ci_beta": [boot_lo, boot_hi],
            "bootstrap_median_beta": boot_med,
            "welch_high_vs_benign": welch,
            "panel_n": int(len(panel)),
        }
        summary_lines.append(
            f"  {tk}: β={ols['beta']:.4f} HAC-p={ols['p_hac']:.3f} n={ols['n']} "
            f"| Welch p={welch.get('p')}"
        )

    # Verdict
    sig_count = sum(
        1
        for r in results["tests"].values()
        if "ols_hac" in r and r["ols_hac"]["p_hac"] < 0.10
    )
    sig_count_strict = sum(
        1
        for r in results["tests"].values()
        if "ols_hac" in r and r["ols_hac"]["p_hac"] < 0.05
    )

    if sig_count_strict >= 3:
        verdict = "PASS"
    elif sig_count_strict >= 2 or sig_count >= 3:
        verdict = "CONDITIONAL_PASS"
    elif sig_count >= 1:
        verdict = "WEAK_SIGNAL"
    else:
        verdict = "NULL"
    results["verdict"] = verdict
    results["verdict_rule"] = (
        "PASS: ≥3/4 ETFs with HAC p<0.05 on Δz; "
        "CONDITIONAL_PASS: ≥2 at p<0.05 OR ≥3 at p<0.10; "
        "WEAK_SIGNAL: ≥1 at p<0.10; NULL: 0/4. "
        "Single-test thresholds — no multiple-testing correction applied (4 tests; "
        "Bonferroni would require p<0.0125 for 'PASS')."
    )
    results["sig_counts"] = {
        "n_etfs_p_below_0_05": int(sig_count_strict),
        "n_etfs_p_below_0_10": int(sig_count),
    }

    out_path = OUT_DIR / "k1581_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"[K1581] Wrote results → {out_path}")
    print("\n".join(summary_lines))
    print(f"[K1581] VERDICT: {verdict}  (sig_strict={sig_count_strict}/{len(ETFS)}, sig_p10={sig_count}/{len(ETFS)})")


if __name__ == "__main__":
    main()
