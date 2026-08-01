"""Pre-NFP VIX path (T-7 -> T-1), conditioned on the VIX level at T-7.

Event article evidence package for NFP_US 2026-08-07, series slot T-7.

The question this answers is the one a T-7 article can actually ask: not "what
happens on NFP day" (covered already, K513 / mile_eda69bfb) but "what does the
week *into* NFP look like from here". Everything is measured with information
available at T-7, so the conditioning variable is observable when the article
publishes.

Release dates come from `volpred.data.event_dates.nfp_release_dates` (ALFRED
news-release calendar), never a first-Friday proxy -- see the module docstring
and docs/error_log.md 2026-07-12.

Outputs:
    experiments/nfp_20260807_t7/nfp_20260807_t7_results.json
    experiments/nfp_20260807_t7/nfp_20260807_t7_events.csv
    experiments/nfp_20260807_t7/nfp_20260807_t7_controls.csv
    experiments/nfp_20260807_t7/nfp_20260807_t7_regime.png
    experiments/nfp_20260807_t7/reproduce_spec.json

Retired 2026-08-02: this historical command now delegates to the formal,
pinned-input experiment entrypoint, so invoking the wrapper actively rewrites
the canonical outputs listed above.  Only the best-available producer source
below is inert forensic text; the exact pre-edit bytes were never tracked and
are not claimed.  The preserved legacy ``nfp_t7_*`` artifacts are read-only and
no import or invocation can overwrite them.
"""

from __future__ import annotations

import runpy
from pathlib import Path

CANONICAL_ENTRYPOINT = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "nfp_20260807_t7"
    / "nfp_20260807_t7.py"
)


def main() -> None:
    """Delegate every executable/imported call to the canonical experiment."""
    runpy.run_path(str(CANONICAL_ENTRYPOINT), run_name="__main__")


if __name__ == "__main__":
    main()


# Best-available source retained for forensic comparison only.  The producer
# was never tracked, so this text is explicitly NOT claimed to be a byte-exact
# pre-edit blob.  Keeping it inert prevents imports from reopening the retired
# writer while preserving the old algorithm for incident analysis.
LEGACY_SOURCE_UNVERIFIED = r'''

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from plot_style import apply_cjk_style
from scipy import stats

from volpred.data.event_dates import nfp_release_dates
from volpred.data.manager import DataManager

START = "2010-01-01"
END = "2026-07-31"
PRE_LAG = 7   # trading days before release = T-7
OUT_DIR = Path(__file__).resolve().parents[1] / "experiments" / "nfp_20260807_t7"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    apply_cjk_style()

    dm = DataManager()
    vix = dm.get_price_data("^VIX", START, END)
    vix.index = pd.to_datetime(vix.index).tz_localize(None).normalize()
    close = vix["close"].astype(float).sort_index()

    releases = nfp_release_dates(START, END)
    releases = pd.DatetimeIndex(pd.to_datetime(releases)).tz_localize(None).normalize()

    idx = close.index

    rows = []
    for rel in releases:
        # map release date onto the trading calendar (release day itself)
        i = idx.searchsorted(rel)
        if i >= len(idx) or idx[i] != rel:
            continue  # release day not a trading day / outside price history
        if i - PRE_LAG < 0:
            continue
        v_t7 = close.iloc[i - PRE_LAG]
        v_tm1 = close.iloc[i - 1]
        v_t0 = close.iloc[i]
        rows.append(
            {
                "release": rel.date().isoformat(),
                "vix_t7": float(v_t7),
                "vix_tm1": float(v_tm1),
                "vix_t0": float(v_t0),
                "pre_chg_pct": float(v_tm1 / v_t7 - 1.0) * 100.0,
                "event_day_chg_pct": float(v_t0 / v_tm1 - 1.0) * 100.0,
            }
        )

    ev = pd.DataFrame(rows)

    # ---- baseline: every 6-trading-day VIX change that does NOT overlap a
    # pre-NFP window. Same horizon (T-7 -> T-1 is 6 trading days) so the
    # comparison is like-for-like.
    horizon = PRE_LAG - 1
    all_chg = (close.shift(-horizon) / close - 1.0) * 100.0
    excluded = set()
    for rel in releases:
        i = idx.searchsorted(rel)
        if i >= len(idx) or idx[i] != rel:
            continue
        for k in range(max(0, i - PRE_LAG - horizon), min(len(idx), i + 1)):
            excluded.add(idx[k])
    mask = (~idx.isin(excluded)) & all_chg.notna()
    baseline = all_chg[mask]

    pre = ev["pre_chg_pct"].dropna()
    t_stat, t_p = stats.ttest_ind(pre, baseline, equal_var=False)
    u_stat, u_p = stats.mannwhitneyu(pre, baseline, alternative="two-sided")

    # ---- cross-section by VIX regime observed at T-7
    bins = [0, 15, 20, 25, 200]
    labels = ["<15", "15-20", "20-25", ">=25"]
    ev["regime"] = pd.cut(ev["vix_t7"], bins=bins, labels=labels, right=False)
    reg = (
        ev.groupby("regime", observed=False)["pre_chg_pct"]
        .agg(n="count", mean="mean", median="median", sd="std")
        .reset_index()
    )
    reg["share_up"] = (
        ev.groupby("regime", observed=False)["pre_chg_pct"]
        .apply(lambda s: float((s > 0).mean() * 100) if len(s) else float("nan"))
        .values
    )

    # ---- THE CONTROL. The regime split above is not evidence of an event
    # effect until the same split is run on weeks with no NFP in them. VIX mean
    # reverts from wherever it starts; if non-event weeks show the same
    # gradient, the "pre-NFP" story is just mean reversion wearing a costume.
    base_df = pd.DataFrame({"start_vix": close[mask].values, "chg_pct": baseline.values})
    base_df["regime"] = pd.cut(base_df["start_vix"], bins=bins, labels=labels, right=False)
    base_reg = (
        base_df.groupby("regime", observed=False)["chg_pct"]
        .agg(n="count", mean="mean", median="median", sd="std")
        .reset_index()
    )
    base_reg["share_up"] = (
        base_df.groupby("regime", observed=False)["chg_pct"]
        .apply(lambda s: float((s > 0).mean() * 100) if len(s) else float("nan"))
        .values
    )

    # per-regime event-vs-baseline test: is the pre-NFP week different *within*
    # a starting-level bucket?
    regime_tests = []
    for lab in labels:
        a = ev.loc[ev["regime"] == lab, "pre_chg_pct"].dropna()
        b = base_df.loc[base_df["regime"] == lab, "chg_pct"].dropna()
        if len(a) < 5 or len(b) < 5:
            regime_tests.append({"regime": lab, "n_event": len(a), "n_base": len(b), "p": None})
            continue
        st, p = stats.ttest_ind(a, b, equal_var=False)
        regime_tests.append(
            {
                "regime": lab,
                "n_event": len(a),
                "n_base": len(b),
                "event_mean_pct": float(a.mean()),
                "base_mean_pct": float(b.mean()),
                "diff_pct": float(a.mean() - b.mean()),
                "welch_t": float(st),
                "p": float(p),
            }
        )

    latest_date = idx[-1]
    latest_vix = float(close.iloc[-1])

    results = {
        "generated_for": "NFP_US_2026_08_07 / T-7",
        "release_source": "ALFRED news-release calendar (FRED release id 50)",
        "sample": {
            "start": START,
            "end": END,
            "n_releases_matched": len(ev),
            "first": ev["release"].iloc[0] if len(ev) else None,
            "last": ev["release"].iloc[-1] if len(ev) else None,
        },
        "pre_event_window": {
            "definition": "VIX close at T-7 trading days -> VIX close at T-1",
            "mean_pct": float(pre.mean()),
            "median_pct": float(pre.median()),
            "sd_pct": float(pre.std()),
            "share_up_pct": float((pre > 0).mean() * 100),
        },
        "baseline_non_event": {
            "definition": f"all non-overlapping {horizon}-trading-day VIX changes outside pre-NFP windows",
            "n": len(baseline),
            "mean_pct": float(baseline.mean()),
            "median_pct": float(baseline.median()),
            "sd_pct": float(baseline.std()),
            "share_up_pct": float((baseline > 0).mean() * 100),
        },
        "tests": {
            "welch_t": {"stat": float(t_stat), "p": float(t_p)},
            "mann_whitney_u": {"stat": float(u_stat), "p": float(u_p)},
        },
        "by_regime": reg.to_dict(orient="records"),
        "by_regime_baseline": base_reg.to_dict(orient="records"),
        "by_regime_tests": regime_tests,
        "current_state": {
            "as_of": latest_date.date().isoformat(),
            "vix_close": latest_vix,
            "regime": str(pd.cut([latest_vix], bins=bins, labels=labels, right=False)[0]),
            "next_release": "2026-08-07",
        },
        "event_day_reference": {
            "definition": "VIX close change T-1 -> T+0 (release day), same sample",
            "mean_pct": float(ev["event_day_chg_pct"].mean()),
            "median_pct": float(ev["event_day_chg_pct"].median()),
        },
    }

    (OUT_DIR / "nfp_t7_results.json").write_text(
        json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    ev.to_csv(OUT_DIR / "nfp_t7_events.csv", index=False)

    # ---- chart
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    ax = axes[0]
    ax.hist(baseline, bins=40, density=True, alpha=0.45, color="#9aa5b1", label="非事件週（同長度）")
    ax.hist(pre, bins=25, density=True, alpha=0.65, color="#d1495b", label="非農前一週 T-7→T-1")
    ax.axvline(0, color="#333", lw=0.8)
    ax.axvline(pre.mean(), color="#d1495b", ls="--", lw=1.4)
    ax.axvline(baseline.mean(), color="#5a6673", ls="--", lw=1.4)
    ax.set_xlim(-40, 60)
    ax.set_xlabel("VIX 六個交易日變化 (%)")
    ax.set_ylabel("密度")
    ax.set_title("非農前一週 vs 一般週")
    ax.legend(fontsize=8)

    ax = axes[1]
    sub = reg.dropna(subset=["mean"])
    bsub = base_reg.set_index("regime").reindex(sub["regime"]).reset_index()
    x = range(len(sub))
    w = 0.38
    ax.bar([i - w / 2 for i in x], sub["mean"], width=w, color="#d1495b", label="非農前一週")
    ax.bar([i + w / 2 for i in x], bsub["mean"], width=w, color="#9aa5b1", label="一般週（對照）")
    for i, (_, r) in enumerate(sub.iterrows()):
        ax.text(i - w / 2, r["mean"], f"{r['mean']:+.1f}%\nn={int(r['n'])}",
                ha="center", va="bottom" if r["mean"] >= 0 else "top", fontsize=7.5)
    for i, (_, r) in enumerate(bsub.iterrows()):
        ax.text(i + w / 2, r["mean"], f"{r['mean']:+.1f}%",
                ha="center", va="bottom" if r["mean"] >= 0 else "top", fontsize=7.5)
    ax.set_xticks(list(x))
    ax.set_xticklabels(sub["regime"].astype(str))
    ax.axhline(0, color="#333", lw=0.8)
    ax.set_xlabel("週初 VIX 水位")
    ax.set_ylabel("六個交易日平均變化 (%)")
    ax.set_title("同一組起點水位：事件週 vs 一般週")
    ax.legend(fontsize=8)
    fig.suptitle("非農公佈前一週的 VIX 路徑（2010-2026，官方發佈日）", fontsize=11)
    fig.tight_layout()
    fig.savefig(OUT_DIR / "nfp_t7_regime.png", dpi=140)

    print(json.dumps(results, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
'''
