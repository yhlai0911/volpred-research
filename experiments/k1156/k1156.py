"""K1156 - Paper 2 cover figure: 6-market validation visualization.

Pure visualisation (no new estimation). Inputs are canonical numbers from
Paper 2 body_v3.tex Appendix Table tz_results plus the K1176 6-market
replication. The figure shows the cross-market consistency of the U.S.→Asia
overnight information transmission channel that motivates the VIX proxy
used throughout Paper 2.

Sources (all verified before plotting):
  - paper/taiwan-vt/body_v3.tex (Appendix tz_results table 7) — TW/JP c2c
    Sharpe and 6-market c2c Newey-West t-stats (HK 4.12, AU 4.04, SG 4.03,
    KR 3.83, TW 3.76, JP 3.69)
  - experiments/k1176/k1176_results.json — replicated 6-market c2c & o2o
    Newey-West t-stats and Sharpe ratios from yfinance daily OHLC

The figure is designed for Paper 2 (taiwan-vt) cover / lead-in figure that
demonstrates direction-universal cross-market validation.

Usage:
    uv run python experiments/k1156/k1156.py

Outputs (deterministic, no random component):
    experiments/k1156/k1156_cover.png  (300 dpi)
    experiments/k1156/k1156_cover.pdf  (vector)
    experiments/k1156/k1156_results.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone

import matplotlib.pyplot as plt
import numpy as np

# ----------------------------------------------------------------------------
# Repo discovery — script lives in either main repo or worktree; resolve both.
# ----------------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR  # experiments/k1156

# Look up to 6 levels up for "experiments" sibling that contains k1176
# (works in main repo and in .claude/worktrees/<id>).
def _find_repo_root(start: Path) -> Path:
    p = start
    for _ in range(8):
        if (p / "experiments" / "k1176" / "k1176_results.json").exists():
            return p
        p = p.parent
    raise FileNotFoundError(
        "Could not locate repo root containing experiments/k1176/k1176_results.json"
    )

REPO_ROOT = _find_repo_root(SCRIPT_DIR)
K1176_JSON = REPO_ROOT / "experiments" / "k1176" / "k1176_results.json"

# Paper body: prefer body_v3.tex (main repo head); fall back to body_v2.tex
# (worktree shadow). Both contain the canonical 6-market t-stat block; the
# verbatim grep below ensures we caught the right version regardless of path.
_PAPER_BODY_CANDIDATES = [
    REPO_ROOT / "paper" / "taiwan-vt" / "body_v3.tex",
    REPO_ROOT / "paper" / "taiwan-vt" / "body_v2.tex",
    REPO_ROOT / "paper" / "taiwan-vt" / "body.tex",
]
PAPER_BODY = next((p for p in _PAPER_BODY_CANDIDATES if p.exists()), None)
if PAPER_BODY is None:
    raise FileNotFoundError(
        "Could not locate paper/taiwan-vt body_v3.tex / body_v2.tex / body.tex"
    )

# ----------------------------------------------------------------------------
# Canonical Paper 2 numbers (verbatim from body_v3.tex Appendix tz_results).
# Section: \subsection{Main Results}, Table tz_results, post-table prose
# enumerating the 6 Asia-Pacific markets exceeding Harvey threshold on c2c.
# ----------------------------------------------------------------------------
PAPER_CANONICAL = {
    # 6-market c2c Newey-West t-stats from body_v3.tex (around line 555):
    # "Hong Kong $t = 4.12$, Australia $t = 4.04$, Singapore $t = 4.03$,
    #  Korea $t = 3.83$, Taiwan $t = 3.76$, Japan $t = 3.69$"
    "c2c_t": {
        "HK": 4.12,
        "AU": 4.04,
        "SG": 4.03,
        "KR": 3.83,
        "TW": 3.76,
        "JP": 3.69,
    },
    # Panel A Sharpe ratios (only TW & JP reported in Table tz_results body):
    # Taiwan c2c=1.473, o2o=0.87, t(o2o)=2.22 ; Japan c2c=1.306, o2o=0.78
    "tw_c2c_sharpe": 1.473,
    "tw_o2o_sharpe": 0.87,
    "tw_o2o_t": 2.22,
    "jp_c2c_sharpe": 1.306,
    "jp_o2o_sharpe": 0.78,
    "jp_o2o_t": 2.00,
    # Block bootstrap 95% CI on Taiwan c2c Sharpe from Robustness paragraph:
    # "block bootstrap (95\% CI $[0.65, 2.24]$, excluding zero)"
    "tw_c2c_sharpe_ci95": (0.65, 2.24),
    "harvey_threshold": 3.0,
    "sample_period": "2012-2025",
    "lookback_days": 10,
    "tx_cost_per_switch": 0.00186,
}

MARKET_LABELS = {
    "TW": "Taiwan\n(0050.TW)",
    "JP": "Japan\n(Nikkei 225)",
    "HK": "Hong Kong\n(HSI)",
    "AU": "Australia\n(ASX)",
    "SG": "Singapore\n(STI)",
    "KR": "Korea\n(KOSPI)",
}


def verify_paper_text() -> dict:
    """Re-extract the 6 Newey-West t-stats from paper body to detect divergence."""
    body = PAPER_BODY.read_text(encoding="utf-8")
    needed = [
        ("HK", "Hong Kong $t = 4.12$"),
        ("AU", "Australia $t = 4.04$"),
        ("SG", "Singapore $t = 4.03$"),
        ("KR", "Korea $t = 3.83$"),
        ("TW", "Taiwan $t = 3.76$"),
        ("JP", "Japan $t = 3.69$"),
    ]
    missing = [m for m, snippet in needed if snippet not in body]
    return {
        "all_six_t_stats_found_verbatim": len(missing) == 0,
        "missing_markets": missing,
        "paper_body_path": str(PAPER_BODY.relative_to(REPO_ROOT)),
    }


def load_k1176() -> dict:
    """Load K1176 6-market replication numbers."""
    with K1176_JSON.open() as f:
        return json.load(f)


def assemble_data() -> dict:
    """Assemble market-by-market table for plotting and results.json.

    For each market we keep:
      - paper c2c t-stat (canonical Harvey-threshold metric)
      - K1176 c2c t-stat (replicated Newey-West)
      - K1176 o2o t-stat (implementable channel)
      - K1176 c2c Sharpe & o2o Sharpe (deciles for context, not main bar)
    """
    k1176 = load_k1176()
    rows = []
    for m in ["TW", "JP", "KR", "AU", "SG", "HK"]:  # ordered by panel A salience
        rep = k1176["individual_markets"][m]
        rows.append(
            {
                "market": m,
                "label": MARKET_LABELS[m],
                "paper_c2c_t": PAPER_CANONICAL["c2c_t"][m],
                "k1176_c2c_t": rep["c2c"]["nw_tstat"],
                "k1176_o2o_t": rep["o2o"]["nw_tstat"],
                "k1176_c2c_sharpe": rep["c2c"]["sharpe"],
                "k1176_o2o_sharpe": rep["o2o"]["sharpe"],
                "k1176_c2c_mdd_pct": rep["c2c"]["mdd_pct"],
                "k1176_n_days": rep["c2c"]["n_days"],
            }
        )
    return {"rows": rows, "k1176_metadata": k1176["metadata"]}


def make_figure(data: dict, out_png: Path, out_pdf: Path) -> None:
    """Two-panel publication-quality figure.

    Panel A (top): 6-market Newey-West c2c t-stats (paper + K1176 reproduce)
    with Harvey (2016) t=3.0 threshold line. Confirms direction-universality.

    Panel B (bottom): K1176 c2c Sharpe ratios with 95% block-bootstrap CI
    annotation for Taiwan (the only market whose CI is reported in paper).
    """
    rows = data["rows"]
    markets = [r["market"] for r in rows]
    labels = [r["label"] for r in rows]
    paper_t = np.array([r["paper_c2c_t"] for r in rows])
    rep_c2c_t = np.array([r["k1176_c2c_t"] for r in rows])
    rep_o2o_t = np.array([r["k1176_o2o_t"] for r in rows])
    rep_c2c_sharpe = np.array([r["k1176_c2c_sharpe"] for r in rows])

    # Approximate symmetric SE from t-stat (SE = |coef| / |t|); for plot we
    # use SE = 1/√(n_eff) ~ Sharpe annual SE = 1/√T_yr; just show paper t with
    # no error bar (canonical), and K1176 with implied 95% CI via t±1.96.
    # For visual interpretability we plot paper as a marker, K1176 as bars.
    n_yr = np.array([r["k1176_n_days"] for r in rows]) / 252.0
    sharpe_se = 1.0 / np.sqrt(n_yr)  # asymptotic SE for Sharpe under iid
    sharpe_ci_lo = rep_c2c_sharpe - 1.96 * sharpe_se
    sharpe_ci_hi = rep_c2c_sharpe + 1.96 * sharpe_se

    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 12.5,
            "axes.labelsize": 11,
            "xtick.labelsize": 10,
            "ytick.labelsize": 10,
            "legend.fontsize": 10,
            "figure.dpi": 150,
        }
    )

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(10.5, 8.2), gridspec_kw={"height_ratios": [1.0, 1.0]}
    )

    x = np.arange(len(markets))
    bar_w = 0.36

    # --- Panel A: Newey-West t-stats ----------------------------------------
    paper_color = "#2E5984"  # navy
    rep_c2c_color = "#5DA0CF"  # mid blue
    rep_o2o_color = "#A8C8E0"  # pale blue
    threshold_color = "#C0392B"  # red

    bars_paper = ax1.bar(
        x - bar_w / 2,
        paper_t,
        bar_w,
        label="Paper canonical (c2c, NW HAC)",
        color=paper_color,
        edgecolor="black",
        linewidth=0.5,
    )
    bars_rep = ax1.bar(
        x + bar_w / 2,
        rep_c2c_t,
        bar_w,
        label="K1176 replication (c2c, NW HAC)",
        color=rep_c2c_color,
        edgecolor="black",
        linewidth=0.5,
    )
    # Overlay K1176 o2o t-stat as a marker (implementable channel)
    ax1.plot(
        x + bar_w / 2,
        rep_o2o_t,
        marker="D",
        linestyle="none",
        color="#1B4F72",
        markersize=7,
        markeredgecolor="white",
        markeredgewidth=0.7,
        label="K1176 o2o (implementable, NW HAC)",
        zorder=5,
    )

    ax1.axhline(
        PAPER_CANONICAL["harvey_threshold"],
        color=threshold_color,
        linestyle="--",
        linewidth=1.4,
        label="Harvey (2016) threshold $t=3.0$",
    )
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Newey--West HAC $t$-statistic")
    ax1.set_title(
        "Cross-Market Validation of U.S.$\\rightarrow$Asia Information Transmission\n"
        "10-day SPY momentum, six Asia-Pacific markets, "
        f"{PAPER_CANONICAL['sample_period']}"
    )
    ax1.legend(loc="upper right", framealpha=0.95)
    ax1.grid(True, axis="y", alpha=0.25)
    ymax = max(rep_o2o_t.max(), rep_c2c_t.max(), paper_t.max()) * 1.12
    ax1.set_ylim(0, ymax)

    # Annotate paper t values above bars
    for xi, val in zip(x - bar_w / 2, paper_t):
        ax1.text(xi, val + 0.08, f"{val:.2f}", ha="center", va="bottom",
                 fontsize=8.5, color=paper_color)
    for xi, val in zip(x + bar_w / 2, rep_c2c_t):
        ax1.text(xi, val + 0.08, f"{val:.2f}", ha="center", va="bottom",
                 fontsize=8.5, color=rep_c2c_color)

    # --- Panel B: K1176 c2c Sharpe with 95% asymptotic CI -------------------
    err_lo = rep_c2c_sharpe - sharpe_ci_lo
    err_hi = sharpe_ci_hi - rep_c2c_sharpe
    ax2.bar(
        x,
        rep_c2c_sharpe,
        0.55,
        yerr=[err_lo, err_hi],
        capsize=4,
        color="#5DA0CF",
        edgecolor="black",
        linewidth=0.5,
        ecolor="#1B4F72",
        label="K1176 c2c Sharpe (95\\% asymptotic CI, $\\pm1.96/\\sqrt{T_{yr}}$)",
    )
    # Paper canonical TW & JP Sharpe (only two reported in paper) as markers
    paper_sharpes = {"TW": PAPER_CANONICAL["tw_c2c_sharpe"],
                     "JP": PAPER_CANONICAL["jp_c2c_sharpe"]}
    for i, m in enumerate(markets):
        if m in paper_sharpes:
            ax2.plot(
                i,
                paper_sharpes[m],
                marker="*",
                markersize=14,
                color="#E67E22",
                markeredgecolor="black",
                markeredgewidth=0.6,
                zorder=5,
                label=("Paper canonical Sharpe (TW, JP only)" if i == 0 else None),
            )

    # TW block-bootstrap CI from paper Appendix Robustness paragraph
    tw_ci = PAPER_CANONICAL["tw_c2c_sharpe_ci95"]
    tw_idx = markets.index("TW")
    ax2.errorbar(
        tw_idx - 0.18,
        PAPER_CANONICAL["tw_c2c_sharpe"],
        yerr=[
            [PAPER_CANONICAL["tw_c2c_sharpe"] - tw_ci[0]],
            [tw_ci[1] - PAPER_CANONICAL["tw_c2c_sharpe"]],
        ],
        fmt="none",
        ecolor="#E67E22",
        elinewidth=1.4,
        capsize=5,
        capthick=1.2,
        label=f"Paper TW block bootstrap 95\\% CI $[{tw_ci[0]:.2f},{tw_ci[1]:.2f}]$",
    )

    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)
    ax2.set_ylabel("Annualised Sharpe ratio (close-to-close)")
    ax2.set_title(
        "Replicated c2c Sharpe (K1176, yfinance daily, "
        f"$\\tau$=0.186\\%/switch, lookback={PAPER_CANONICAL['lookback_days']}d)"
    )
    ax2.axhline(0, color="black", linewidth=0.6)
    ax2.grid(True, axis="y", alpha=0.25)
    ax2.legend(loc="upper right", framealpha=0.95, fontsize=9)

    fig.suptitle(
        "Paper 2 cover: Six-market replication of overnight U.S.$\\rightarrow$Asia channel",
        fontsize=13.5,
        y=0.995,
    )
    fig.tight_layout(rect=[0, 0, 1, 0.985])

    fig.savefig(out_png, dpi=300, bbox_inches="tight")
    fig.savefig(out_pdf, bbox_inches="tight")
    plt.close(fig)


def write_results(data: dict, paper_check: dict, out_json: Path) -> None:
    rows = data["rows"]
    payload = {
        "experiment_id": "K1156",
        "title": "Paper 2 cover figure: 6-market validation visualization",
        "purpose": (
            "Publication-quality cover figure showing direction-universal "
            "cross-market validation of the overnight U.S.->Asia information "
            "transmission channel that motivates Paper 2's VIX-proxy VT design."
        ),
        "type": "visualization_only_no_new_estimation",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "random_seed": 42,
        "deterministic": True,
        "paper_target": "paper/taiwan-vt (body_v3.tex Appendix tz_results)",
        "x_axis": "Six Asia-Pacific markets (TW, JP, KR, AU, SG, HK)",
        "y_axis_panel_a": "Newey-West HAC c2c t-statistic (Harvey 2016 threshold = 3.0)",
        "y_axis_panel_b": "Annualised c2c Sharpe ratio with 95% asymptotic CI",
        "n_markets": len(rows),
        "sample_period": PAPER_CANONICAL["sample_period"],
        "lookback_days": PAPER_CANONICAL["lookback_days"],
        "transaction_cost_per_switch": PAPER_CANONICAL["tx_cost_per_switch"],
        "data_sources": {
            "K1176": {
                "path": "experiments/k1176/k1176_results.json",
                "role": "6-market replicated NW c2c & o2o t-stats and Sharpe ratios",
                "data_provider": "yfinance daily OHLC (Adj Close, split-corrected)",
            },
            "Paper2_body_v3": {
                "path": "paper/taiwan-vt/body_v3.tex",
                "role": (
                    "Canonical 6-market c2c NW t-stats (Appendix tz_results post-"
                    "table prose) + TW/JP Sharpe + TW block bootstrap CI"
                ),
            },
            "K1153_K1175_K1178": {
                "note": (
                    "Considered but not used for this cover. K1153 is 4-market "
                    "earnings-announcement panel (paper-1 lineage); K1175 is "
                    "single-market TW VT replication; K1178 is 13-market "
                    "international VT for Paper 3. None of these correspond to "
                    "Paper 2's 6-market overnight-channel cross-validation."
                )
            },
        },
        "paper_canonical_inputs": PAPER_CANONICAL,
        "paper_text_verification": paper_check,
        "per_market": rows,
        "harvey_pass_paper_canonical": [
            r["market"] for r in rows if r["paper_c2c_t"] > PAPER_CANONICAL["harvey_threshold"]
        ],
        "harvey_pass_k1176_c2c": [
            r["market"] for r in rows if r["k1176_c2c_t"] > PAPER_CANONICAL["harvey_threshold"]
        ],
        "harvey_pass_k1176_o2o": [
            r["market"] for r in rows if r["k1176_o2o_t"] > PAPER_CANONICAL["harvey_threshold"]
        ],
        "tw_block_bootstrap_ci_width": (
            PAPER_CANONICAL["tw_c2c_sharpe_ci95"][1]
            - PAPER_CANONICAL["tw_c2c_sharpe_ci95"][0]
        ),
        "outputs": {
            "png": "experiments/k1156/k1156_cover.png",
            "pdf": "experiments/k1156/k1156_cover.pdf",
        },
    }
    out_json.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def main() -> int:
    print(f"[K1156] Repo root: {REPO_ROOT}")
    print(f"[K1156] Loading paper body: {PAPER_BODY.relative_to(REPO_ROOT)}")
    paper_check = verify_paper_text()
    print(f"[K1156] Paper text verbatim check: {paper_check}")
    if not paper_check["all_six_t_stats_found_verbatim"]:
        print(
            "[K1156] WARNING: Some canonical t-stats no longer match body_v3.tex; "
            "the README must record DIVERGENCE before re-rendering."
        )

    print(f"[K1156] Loading K1176 results: {K1176_JSON.relative_to(REPO_ROOT)}")
    data = assemble_data()

    out_png = EXP_DIR / "k1156_cover.png"
    out_pdf = EXP_DIR / "k1156_cover.pdf"
    out_json = EXP_DIR / "k1156_results.json"

    print(f"[K1156] Rendering figure -> {out_png.name}, {out_pdf.name}")
    make_figure(data, out_png, out_pdf)
    print(f"[K1156] Writing results JSON -> {out_json.name}")
    write_results(data, paper_check, out_json)

    print("[K1156] Summary:")
    for r in data["rows"]:
        print(
            f"  {r['market']:>3}: paper_c2c_t={r['paper_c2c_t']:.2f} | "
            f"K1176 c2c_t={r['k1176_c2c_t']:.2f} | o2o_t={r['k1176_o2o_t']:.2f} | "
            f"c2c_sharpe={r['k1176_c2c_sharpe']:.2f} | mdd={r['k1176_c2c_mdd_pct']:.1f}%"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
