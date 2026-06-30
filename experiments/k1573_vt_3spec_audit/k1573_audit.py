"""K1573 — VT 3-spec (保守/標準/積極) VIX 15-20 同質化 audit + 差異化方案.

Phase 1: Homogeneity audit (current 3 specs in paper_trading.json + recomputed long-period)
Phase 2: Proposed differentiated parameter design
Phase 3: Stress-period & full-period robustness simulation (2015-2026)

研究誠實:
- All VT weights use VIX_{t-1} → weight_t → return_t convention (signal lag via .shift(1))
- bootstrap / random sampling seeded with seed=42
- 結論不超過證據 — null differentiation as null finding reported faithfully
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Repo-root import path so we can use volpred DataManager.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

from volpred.data.manager import DataManager  # noqa: E402

EXP_DIR = Path(__file__).resolve().parent
FIGS = EXP_DIR / "figs"
FIGS.mkdir(exist_ok=True)
RNG = np.random.default_rng(42)

# -----------------------------------------------------------------------------
# 1) Load paper_trading actual weights for the 3 VT specs
# -----------------------------------------------------------------------------

PT_PATH = REPO_ROOT / "storage" / "paper_trading.json"
SPECS = {
    "conservative": "piecewise_conservative",
    "standard": "simple_12vix",
    "aggressive": "adaptive_tier",
}


def load_paper_trading() -> pd.DataFrame:
    pt = json.loads(PT_PATH.read_text())
    frames = []
    for spec_label, key in SPECS.items():
        entries = pt[key]["entries"]
        rows = []
        for e in entries:
            w = e.get("weights", {})
            # Total risky weight: SPY + GLD + 0050.TW (whichever present).
            risky = sum(v for k, v in w.items() if k in {"SPY", "GLD", "0050.TW"})
            rows.append({
                "data_date": e["data_date"],
                "spec": spec_label,
                "spy": float(w.get("SPY", 0.0)),
                "gld": float(w.get("GLD", 0.0)),
                "risky": float(risky),
                "portfolio_return": e.get("portfolio_return"),
                "cash_weight": e.get("cash_weight", max(0.0, 1.0 - risky)),
            })
        frames.append(pd.DataFrame(rows))
    df = pd.concat(frames, ignore_index=True)
    df["data_date"] = pd.to_datetime(df["data_date"])
    return df


# -----------------------------------------------------------------------------
# 2) Fetch SPY / GLD / VIX / SHY long history (2015-2026) for full-period simulation
# -----------------------------------------------------------------------------

def fetch_market_data(start: str = "2015-01-01", end: str | None = None) -> pd.DataFrame:
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    dm = DataManager()
    spy = dm.get_model_data("SPY", start, end)
    gld = dm.get_model_data("GLD", start, end)
    shy = dm.get_model_data("SHY", start, end)
    vix = dm.get_price_data("^VIX", start, end)

    df = pd.DataFrame({
        "spy_ret": spy["simple_return"],
        "gld_ret": gld["simple_return"],
        "shy_ret": shy["simple_return"],
    })
    df["vix"] = vix["close"]
    df = df.dropna()
    return df


# -----------------------------------------------------------------------------
# 3) Strategy weight functions (CURRENT spec — same as scripts/daily_update.py)
# -----------------------------------------------------------------------------

def weight_current_conservative(vix: float) -> tuple[float, float]:
    """piecewise_conservative on 50/50 SPY/GLD.

    VIX<12 → w=1.0, 12<=VIX<=20 → w=(20-VIX)/8, VIX>20 → 0.
    Returns (spy, gld).
    """
    if vix < 12:
        pw_w = 1.0
    elif vix <= 20:
        pw_w = (20.0 - vix) / 8.0
    else:
        pw_w = 0.0
    return 0.5 * pw_w, 0.5 * pw_w


def weight_current_standard(vix: float) -> tuple[float, float]:
    """simple_12vix: SPY = min(12/VIX, 1), GLD = 0."""
    return float(min(12.0 / vix, 1.0)), 0.0


def weight_current_aggressive(vix: float) -> tuple[float, float]:
    """adaptive_tier: VIX<15 1.5x on 12/VIX/2; 15-20 standard 12/VIX/2; >20 cash."""
    if vix < 15:
        base = 12.0 / vix / 2.0
        w = min(base * 1.5, 1.0)
    elif vix <= 20:
        w = 12.0 / vix / 2.0
    else:
        w = 0.0
    return w, w


# -----------------------------------------------------------------------------
# 4) Proposed differentiated weight functions (Phase 2)
# Design goal: all 3 specs differ meaningfully across full VIX regime, not just <12/>20.
# Constraints:
#  - Conservative: SPY hard cap 50% even at low VIX; ramps to 0 by VIX=25 (more defensive)
#  - Standard: keep canonical 12/VIX (no change)
#  - Aggressive: floor SPY at 60% in VIX<15 with 1.5x leverage (more conviction)
# -----------------------------------------------------------------------------

def weight_proposed_conservative(vix: float) -> tuple[float, float]:
    """Proposed conservative — strictly capped SPY (≤ 30%), GLD diversification.

    Design: across all VIX regimes, SPY weight ≤ aggressive_SPY − 40pp typically.
    VIX<15 → SPY=0.30, GLD=0.30 (defensive even in low vol; total risky 60%)
    15<=VIX<20 → SPY=0.20, GLD=0.20 (total risky 40% — clear separation)
    20<=VIX<25 → linear ramp: SPY 0.20 → 0, GLD 0.20 → 0
    VIX>=25 → fully cash
    """
    if vix < 15:
        spy, gld = 0.30, 0.30
    elif vix < 20:
        spy, gld = 0.20, 0.20
    elif vix < 25:
        t = (vix - 20.0) / 5.0
        spy = 0.20 * (1 - t)
        gld = 0.20 * (1 - t)
    else:
        spy, gld = 0.0, 0.0
    return spy, gld


def weight_proposed_standard(vix: float) -> tuple[float, float]:
    """Proposed standard — keep 12/VIX SPY-only (no change vs current).

    Rationale: 'standard' is the canonical anchor; differentiation comes
    from cons/agg moving away, not from disturbing the well-studied baseline.
    """
    return float(min(12.0 / vix, 1.0)), 0.0


def weight_proposed_aggressive(vix: float) -> tuple[float, float]:
    """Proposed aggressive — high-conviction SPY-only with leverage; floor in mid regime.

    VIX<15 → SPY = min(1.5 * 12/VIX, 2.0) (true leverage up to 2x)
    15<=VIX<20 → SPY = max(1.0, 12/VIX) i.e. floor at 100% SPY in mid regime
                 — explicitly DIFFERENTIATE from standard (which sits at 60-80%)
    20<=VIX<25 → linear ramp 1.0 → 0.40
    25<=VIX<35 → linear ramp 0.40 → 0
    VIX>=35 → fully cash
    """
    if vix < 15:
        spy = min(1.5 * (12.0 / vix), 2.0)
    elif vix < 20:
        spy = 1.0  # 100% SPY through entire mid regime — clear differentiator
    elif vix < 25:
        t = (vix - 20.0) / 5.0
        spy = 1.0 - 0.60 * t  # 1.0 → 0.40
    elif vix < 35:
        t = (vix - 25.0) / 10.0
        spy = 0.40 * (1 - t)
    else:
        spy = 0.0
    return spy, 0.0


WEIGHT_FNS = {
    "current": {
        "conservative": weight_current_conservative,
        "standard": weight_current_standard,
        "aggressive": weight_current_aggressive,
    },
    "proposed": {
        "conservative": weight_proposed_conservative,
        "standard": weight_proposed_standard,
        "aggressive": weight_proposed_aggressive,
    },
}


# -----------------------------------------------------------------------------
# 5) Backtest engine — VIX_{t-1} → weight_t → return_t (NO lookahead)
# -----------------------------------------------------------------------------

def simulate_strategy(mkt: pd.DataFrame, weight_fn) -> pd.DataFrame:
    """Apply a (vix → spy,gld) weight function with VIX from t-1.

    weight_t = weight_fn(vix_{t-1})
    portfolio_return_t = spy_w * spy_ret_t + gld_w * gld_ret_t + cash_w * shy_ret_t
    """
    vix_lag = mkt["vix"].shift(1)  # lookahead-safe
    weights = []
    for v in vix_lag:
        if pd.isna(v):
            weights.append((np.nan, np.nan))
        else:
            weights.append(weight_fn(float(v)))
    w_df = pd.DataFrame(weights, index=mkt.index, columns=["spy_w", "gld_w"])
    w_df["risky_w"] = w_df["spy_w"] + w_df["gld_w"]
    w_df["cash_w"] = (1.0 - w_df["risky_w"]).clip(lower=0)

    # Allow leverage > 1.0 (cash_w becomes 0; excess risky funded notionally; we don't model borrow cost)
    port_ret = (
        w_df["spy_w"] * mkt["spy_ret"]
        + w_df["gld_w"] * mkt["gld_ret"]
        + w_df["cash_w"] * mkt["shy_ret"]
    )
    out = w_df.copy()
    out["port_ret"] = port_ret
    out["vix_lag"] = vix_lag
    return out


# -----------------------------------------------------------------------------
# 6) Metrics + VIX regime breakdown
# -----------------------------------------------------------------------------

def metrics(returns: pd.Series) -> dict:
    r = returns.dropna()
    if len(r) < 30:
        return {"n": int(len(r)), "sharpe": None, "cagr": None, "mdd": None, "vol": None}
    cum = (1.0 + r).cumprod()
    cagr = cum.iloc[-1] ** (252.0 / len(r)) - 1.0
    vol = r.std() * np.sqrt(252.0)
    sharpe = (r.mean() * 252.0) / vol if vol > 0 else None
    peak = cum.cummax()
    dd = cum / peak - 1.0
    mdd = float(dd.min())
    return {
        "n": int(len(r)),
        "sharpe": float(sharpe) if sharpe is not None else None,
        "cagr": float(cagr),
        "vol_ann": float(vol),
        "mdd": mdd,
    }


def vix_regime(vix: float) -> str:
    if vix < 15:
        return "low(<15)"
    if vix <= 20:
        return "mid(15-20)"
    return "high(>20)"


def regime_breakdown(mkt: pd.DataFrame, sims: dict[str, pd.DataFrame]) -> dict:
    """For each VIX regime + each spec, compute mean spy_w / risky_w / etc.

    Uses VIX_{t-1} (same lag as simulate_strategy) reindexed to sim's full index;
    rows where vix_lag is NaN (first row) are excluded via dropna on sub.
    """
    vix_lag_full = mkt["vix"].shift(1)  # full-length, NaN at index 0
    regime_full = vix_lag_full.apply(lambda v: vix_regime(v) if pd.notna(v) else None)
    out = {}
    total_valid = regime_full.notna().sum()
    spec_keys = list(sims.keys())
    for regime in ["low(<15)", "mid(15-20)", "high(>20)"]:
        mask = (regime_full == regime)
        pct = float(mask.sum() / total_valid) if total_valid else 0.0
        out[regime] = {"days": int(mask.sum()), "pct_of_total": pct, "specs": {}}
        sub_by_spec = {}
        for spec, sim in sims.items():
            sub = sim.loc[mask].dropna(subset=["spy_w", "risky_w"])
            sub_by_spec[spec] = sub
            out[regime]["specs"][spec] = {
                "spy_w_mean": float(sub["spy_w"].mean()) if len(sub) else None,
                "spy_w_std": float(sub["spy_w"].std()) if len(sub) else None,
                "risky_w_mean": float(sub["risky_w"].mean()) if len(sub) else None,
                "risky_w_std": float(sub["risky_w"].std()) if len(sub) else None,
            }
        pair_diffs = {}
        for i, a in enumerate(spec_keys):
            for b in spec_keys[i + 1:]:
                merged = sub_by_spec[a][["risky_w"]].join(
                    sub_by_spec[b][["risky_w"]], lsuffix="_a", rsuffix="_b", how="inner"
                ).dropna()
                if len(merged):
                    pair_diffs[f"{a}_vs_{b}"] = float(
                        (merged["risky_w_a"] - merged["risky_w_b"]).abs().mean()
                    )
        out[regime]["pairwise_risky_absdiff"] = pair_diffs
    return out


def weight_corr_matrix(sims: dict[str, pd.DataFrame]) -> dict:
    """Compute pairwise correlation of risky_w and port_ret across 3 specs."""
    specs = list(sims.keys())
    w_corr = np.eye(len(specs))
    r_corr = np.eye(len(specs))
    for i, a in enumerate(specs):
        for j, b in enumerate(specs):
            if i == j:
                continue
            w_corr[i, j] = sims[a]["risky_w"].corr(sims[b]["risky_w"])
            r_corr[i, j] = sims[a]["port_ret"].corr(sims[b]["port_ret"])
    return {
        "labels": specs,
        "weight_corr": w_corr.tolist(),
        "return_corr": r_corr.tolist(),
    }


def regime_weight_spread(regime_data: dict) -> dict:
    """Pairwise mean absolute difference of risky_w (primary) and spy_w (diagnostic).

    risky_w_absdiff is the canonical homogeneity metric per audit definition
    (mean over observations of |risky_w_a - risky_w_b|). spy_w mean-of-means
    diff retained for backward-compat / asset-allocation diagnostic.
    """
    out = {}
    for regime, info in regime_data.items():
        specs = info["specs"]
        keys = list(specs.keys())
        diffs = {}
        for i, a in enumerate(keys):
            for b in keys[i + 1:]:
                pair_abs = info.get("pairwise_risky_absdiff", {}).get(f"{a}_vs_{b}")
                if pair_abs is not None:
                    diffs[f"{a}_vs_{b}_risky_absdiff"] = float(pair_abs)
                diffs[f"{a}_vs_{b}_spy_w_absdiff"] = abs(
                    specs[a]["spy_w_mean"] - specs[b]["spy_w_mean"]
                )
        out[regime] = diffs
    return out


# -----------------------------------------------------------------------------
# 7) Stress periods
# -----------------------------------------------------------------------------

STRESS_PERIODS = {
    "2020_covid": ("2020-02-19", "2020-04-30"),
    "2022_qt": ("2022-01-01", "2022-06-30"),
    "2024_carry": ("2024-07-15", "2024-09-30"),
}


def stress_breakdown(mkt: pd.DataFrame, sims: dict[str, pd.DataFrame]) -> dict:
    out = {}
    for label, (s, e) in STRESS_PERIODS.items():
        mask = (mkt.index >= pd.Timestamp(s)) & (mkt.index <= pd.Timestamp(e))
        period_n = int(mask.sum())
        per_spec = {}
        for spec, sim in sims.items():
            r = sim.loc[mask, "port_ret"].dropna()
            per_spec[spec] = metrics(r) | {
                "cumret": float((1.0 + r).prod() - 1.0) if len(r) else None,
            }
        out[label] = {"start": s, "end": e, "days": period_n, "specs": per_spec}
    return out


# -----------------------------------------------------------------------------
# 8) Figures
# -----------------------------------------------------------------------------

def fig_weight_timeseries(mkt: pd.DataFrame, sims_current: dict, sims_proposed: dict, path: Path):
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    cmap = {"conservative": "tab:green", "standard": "tab:blue", "aggressive": "tab:red"}
    for ax, sims, label in zip(axes, [sims_current, sims_proposed], ["Current", "Proposed"]):
        for spec, sim in sims.items():
            ax.plot(sim.index, sim["risky_w"], color=cmap[spec], lw=1.0, alpha=0.9, label=spec)
        ax.set_ylabel(f"{label}: risky weight")
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=0.3)
        ax2 = ax.twinx()
        ax2.plot(mkt.index, mkt["vix"], color="grey", lw=0.6, alpha=0.5, label="VIX")
        ax2.set_ylabel("VIX")
    axes[1].set_xlabel("date")
    fig.suptitle("VT 3-spec risky-weight timeseries — Current vs Proposed (2015-2026)")
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_regime_histogram(mkt: pd.DataFrame, sims_current: dict, sims_proposed: dict, path: Path):
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    for ax, sims, label in zip(axes, [sims_current, sims_proposed], ["Current", "Proposed"]):
        for spec, sim in sims.items():
            sub = sim["risky_w"].dropna()
            ax.hist(sub.values, bins=40, alpha=0.45, label=spec)
        ax.set_xlabel("risky weight")
        ax.set_title(f"{label}")
        ax.legend(fontsize=8)
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("frequency (days)")
    fig.suptitle("VT 3-spec risky-weight distribution (2015-2026)")
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_stress_returns(mkt: pd.DataFrame, sims_current: dict, sims_proposed: dict, path: Path):
    fig, axes = plt.subplots(len(STRESS_PERIODS), 2, figsize=(13, 9), sharex=False)
    cmap = {"conservative": "tab:green", "standard": "tab:blue", "aggressive": "tab:red"}
    for row, (label_p, (s, e)) in enumerate(STRESS_PERIODS.items()):
        for col, sims in enumerate([sims_current, sims_proposed]):
            ax = axes[row, col]
            mask = (mkt.index >= pd.Timestamp(s)) & (mkt.index <= pd.Timestamp(e))
            for spec, sim in sims.items():
                r = sim.loc[mask, "port_ret"].dropna()
                cum = (1.0 + r).cumprod() - 1.0
                ax.plot(cum.index, cum.values * 100, color=cmap[spec], lw=1.1, label=spec)
            ax.set_title(f"{'Current' if col == 0 else 'Proposed'} — {label_p} ({s} to {e})")
            ax.grid(alpha=0.3)
            ax.axhline(0, color="black", lw=0.5)
            ax.set_ylabel("cum % return")
            if row == 0:
                ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)


# -----------------------------------------------------------------------------
# 9) Paper-trading homogeneity audit (using realized weights, NOT recomputed)
# -----------------------------------------------------------------------------

def audit_paper_trading(pt_df: pd.DataFrame) -> dict:
    """Use real paper_trading weights (from daily_update.py) to confirm 同質化.

    Alignment: daily_update.py writes weights using the data_date market close
    + same-day VIX as the signal, then applies them forward (paid out on
    next session). For signal-regime audit ("when VIX was X, how did each
    spec react?"), the canonical join is realized weight at data_date ↔ VIX
    on the same data_date (no shift). Prior code used vix.shift(1), which
    classified weights by the previous day's VIX → spurious extra separation
    in the mid regime (K1573 Codex review issue 1, 2026-06-30).
    """
    # Pivot to per-date weight matrix
    spy_piv = pt_df.pivot_table(index="data_date", columns="spec", values="spy", aggfunc="first")
    risky_piv = pt_df.pivot_table(index="data_date", columns="spec", values="risky", aggfunc="first")
    # VIX = signal VIX at data_date (no shift). Production spec.
    dm = DataManager()
    vix_raw = dm.get_price_data("^VIX", "2022-06-01", datetime.now().strftime("%Y-%m-%d"))["close"]
    vix_raw.index = pd.to_datetime(vix_raw.index)
    vix_signal = vix_raw.rename("vix_signal")
    aligned = risky_piv.join(vix_signal.to_frame(), how="left").dropna(subset=["vix_signal"])
    aligned["regime"] = aligned["vix_signal"].apply(vix_regime)
    spy_aligned = spy_piv.join(vix_signal.to_frame(), how="left").dropna(subset=["vix_signal"])
    spy_aligned["regime"] = spy_aligned["vix_signal"].apply(vix_regime)

    out = {"by_regime": {}}
    for regime in ["low(<15)", "mid(15-20)", "high(>20)"]:
        sub = aligned[aligned["regime"] == regime]
        spy_sub = spy_aligned[spy_aligned["regime"] == regime]
        if len(sub) == 0:
            out["by_regime"][regime] = {"days": 0}
            continue
        spec_keys = [c for c in sub.columns if c in {"conservative", "standard", "aggressive"}]
        risky_means = {k: float(sub[k].mean()) for k in spec_keys}
        spy_means = {k: float(spy_sub[k].mean()) for k in spec_keys if k in spy_sub.columns}
        # Pairwise abs-diff of risky weight
        pair_diffs = {}
        for i, a in enumerate(spec_keys):
            for b in spec_keys[i + 1:]:
                pair_diffs[f"{a}_vs_{b}_risky_absdiff"] = float(
                    (sub[a] - sub[b]).abs().mean()
                )
        # Pairwise correlation of risky weight
        corr = sub[spec_keys].corr().to_dict()
        out["by_regime"][regime] = {
            "days": int(len(sub)),
            "pct_of_total": float(len(sub) / len(aligned)),
            "risky_w_mean": risky_means,
            "spy_w_mean": spy_means,
            "pairwise_absdiff": pair_diffs,
            "pairwise_corr": corr,
        }

    # Overall (full paper_trading period)
    spec_keys = ["conservative", "standard", "aggressive"]
    out["overall"] = {
        "days": int(len(aligned)),
        "date_range": [str(aligned.index.min().date()), str(aligned.index.max().date())],
        "risky_w_corr_matrix": aligned[spec_keys].corr().values.tolist(),
        "risky_w_corr_labels": spec_keys,
        "vix_15_20_pct_of_days": float(
            (aligned["regime"] == "mid(15-20)").mean()
        ),
    }
    return out


# -----------------------------------------------------------------------------
# 10) Bootstrap stability of regime breakdown (seed=42)
# -----------------------------------------------------------------------------

def bootstrap_regime_metric(
    sims: dict[str, pd.DataFrame], n_boot: int = 500
) -> dict:
    """Block-bootstrap (length=20) Sharpe per spec, 2015-2026."""
    out = {}
    block = 20
    for spec, sim in sims.items():
        r = sim["port_ret"].dropna().values
        n = len(r)
        sharpes = []
        for _ in range(n_boot):
            idx = RNG.integers(0, n - block, size=n // block)
            sample = np.concatenate([r[i:i + block] for i in idx])
            if sample.std() > 0:
                sharpes.append(np.sqrt(252) * sample.mean() / sample.std())
        if sharpes:
            arr = np.array(sharpes)
            out[spec] = {
                "boot_sharpe_mean": float(arr.mean()),
                "boot_sharpe_p2.5": float(np.quantile(arr, 0.025)),
                "boot_sharpe_p97.5": float(np.quantile(arr, 0.975)),
            }
    return out


# =============================================================================
# Main
# =============================================================================

def main():
    print("[1/6] Loading paper_trading.json + market data ...")
    pt_df = load_paper_trading()
    mkt = fetch_market_data("2015-01-01")
    print(f"  paper_trading: {len(pt_df)} rows, dates {pt_df['data_date'].min().date()}–{pt_df['data_date'].max().date()}")
    print(f"  market: {len(mkt)} rows, dates {mkt.index.min().date()}–{mkt.index.max().date()}")

    # Phase 1 — audit using REAL paper_trading weights (canonical homogeneity claim)
    print("[2/6] Phase 1: Paper-trading homogeneity audit ...")
    audit_pt = audit_paper_trading(pt_df)

    # Recompute long-period simulation for CURRENT specs (for context + figs)
    print("[3/6] Phase 1b: Recompute current specs on 2015-2026 market ...")
    sims_current = {
        spec: simulate_strategy(mkt, fn)
        for spec, fn in WEIGHT_FNS["current"].items()
    }
    audit_current = {
        "regime_breakdown": regime_breakdown(mkt, sims_current),
        "weight_corr": weight_corr_matrix(sims_current),
        "regime_weight_spread": regime_weight_spread(regime_breakdown(mkt, sims_current)),
        "fullperiod_metrics": {spec: metrics(sim["port_ret"]) for spec, sim in sims_current.items()},
    }

    # Phase 2 — proposed differentiated params, simulate 2015-2026
    print("[4/6] Phase 2: Simulate proposed specs ...")
    sims_proposed = {
        spec: simulate_strategy(mkt, fn)
        for spec, fn in WEIGHT_FNS["proposed"].items()
    }
    audit_proposed = {
        "regime_breakdown": regime_breakdown(mkt, sims_proposed),
        "weight_corr": weight_corr_matrix(sims_proposed),
        "regime_weight_spread": regime_weight_spread(regime_breakdown(mkt, sims_proposed)),
        "fullperiod_metrics": {spec: metrics(sim["port_ret"]) for spec, sim in sims_proposed.items()},
    }

    # Phase 3 — stress periods + bootstrap
    print("[5/6] Phase 3: Stress periods + bootstrap ...")
    stress_current = stress_breakdown(mkt, sims_current)
    stress_proposed = stress_breakdown(mkt, sims_proposed)
    boot_current = bootstrap_regime_metric(sims_current)
    boot_proposed = bootstrap_regime_metric(sims_proposed)

    # Figures
    print("[6/6] Generating figures ...")
    fig_weight_timeseries(mkt, sims_current, sims_proposed, FIGS / "fig1_weight_timeseries.png")
    fig_regime_histogram(mkt, sims_current, sims_proposed, FIGS / "fig2_regime_histogram.png")
    fig_stress_returns(mkt, sims_current, sims_proposed, FIGS / "fig3_stress_returns.png")

    # Assemble results
    results = {
        "k_id": "K1573",
        "experiment_id": "k1573_vt_3spec_audit",
        "run_at": datetime.utcnow().isoformat() + "Z",
        "seed": 42,
        "data_sources": {
            "paper_trading": str(PT_PATH.relative_to(REPO_ROOT)),
            "market_data": "yfinance via volpred.data.DataManager (SPY, GLD, SHY, ^VIX)",
            "period": [str(mkt.index.min().date()), str(mkt.index.max().date())],
            "n_days_market": int(len(mkt)),
        },
        "spec_mapping_canonical": {
            "conservative": "piecewise_conservative (scripts/daily_update.py:752-780)",
            "standard": "simple_12vix (scripts/daily_update.py:615)",
            "aggressive": "adaptive_tier (scripts/daily_update.py:809-842)",
        },
        "phase1_homogeneity_audit": {
            "paper_trading_realized": audit_pt,
            "recomputed_current": audit_current,
            "homogeneity_definition": "weight pairwise corr > 0.95 AND mean abs diff < 5pp",
            "differentiated_target": "weight pairwise corr < 0.85 AND mean abs diff > 15pp",
        },
        "phase2_proposed_specs": {
            "params": {
                "conservative": (
                    "VIX<15 → SPY=0.30, GLD=0.30 (total risky 60%); "
                    "15<=VIX<20 → SPY=0.20, GLD=0.20 (total risky 40%); "
                    "20<=VIX<25 → ramp to 0; VIX>=25 → cash"
                ),
                "standard": "Unchanged: SPY = min(12/VIX, 1) (canonical 12/VIX anchor)",
                "aggressive": (
                    "VIX<15 → SPY = min(1.5×12/VIX, 2.0) (leverage to 2x); "
                    "15<=VIX<20 → SPY=1.0 (100% SPY floor; clear differentiator); "
                    "20<=VIX<25 → ramp 1.0→0.40; "
                    "25<=VIX<35 → ramp 0.40→0; VIX>=35 → cash"
                ),
            },
            "simulated": audit_proposed,
        },
        "phase3_robustness": {
            "stress_periods_current": stress_current,
            "stress_periods_proposed": stress_proposed,
            "bootstrap_sharpe_current": boot_current,
            "bootstrap_sharpe_proposed": boot_proposed,
            "n_bootstrap": 500,
            "bootstrap_block_length": 20,
        },
        "figures": {
            "fig1": "figs/fig1_weight_timeseries.png",
            "fig2": "figs/fig2_regime_histogram.png",
            "fig3": "figs/fig3_stress_returns.png",
        },
    }

    # Compact summary at top level for quick read
    pt_15_20 = audit_pt["overall"]["vix_15_20_pct_of_days"]
    current_corr = audit_proposed["weight_corr"]["weight_corr"]  # 3x3
    proposed_corr = audit_proposed["weight_corr"]["weight_corr"]
    current_corr_current = audit_current["weight_corr"]["weight_corr"]
    mid_diffs_current = audit_current["regime_weight_spread"]["mid(15-20)"]
    mid_diffs_proposed = audit_proposed["regime_weight_spread"]["mid(15-20)"]

    # Homogeneity confirmed if mid(15-20) avg pairwise risky absdiff < 0.05
    mid_diffs_pt = audit_pt["by_regime"].get("mid(15-20)", {}).get("pairwise_absdiff", {})
    if mid_diffs_pt:
        avg_diff_pt = float(np.mean(list(mid_diffs_pt.values())))
    else:
        avg_diff_pt = None
    results["summary"] = {
        "vix_15_20_pct_of_days_full_market_2015_2026": float(
            audit_current["regime_breakdown"]["mid(15-20)"]["pct_of_total"]
        ),
        "vix_15_20_pct_of_days_paper_trading": float(pt_15_20),
        "current_mid_pairwise_spy_absdiff": mid_diffs_current,
        "proposed_mid_pairwise_spy_absdiff": mid_diffs_proposed,
        "paper_trading_mid_pairwise_risky_absdiff": mid_diffs_pt,
        "paper_trading_mid_avg_absdiff": avg_diff_pt,
        "homogeneity_confirmed": (
            avg_diff_pt is not None and avg_diff_pt < 0.05
        ),
        "current_weight_corr_matrix": current_corr_current,
        "proposed_weight_corr_matrix": proposed_corr,
        "weight_corr_labels": audit_current["weight_corr"]["labels"],
    }

    out_path = EXP_DIR / "k1573_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"\n✓ Results → {out_path}")
    print(f"  vix_15_20 pct (2015-2026): {results['summary']['vix_15_20_pct_of_days_full_market_2015_2026']:.1%}")
    print(f"  vix_15_20 pct (paper_trading 2023-2026): {pt_15_20:.1%}")
    print(f"  homogeneity_confirmed: {results['summary']['homogeneity_confirmed']}")
    print(f"  current corr (cons,std,agg): {current_corr_current}")
    print(f"  proposed corr (cons,std,agg): {proposed_corr}")


if __name__ == "__main__":
    main()
