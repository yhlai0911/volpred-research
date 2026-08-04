"""Charts for the K1354 general-audience article (monthly OPEX event study).

Every number is read at run time from the experiment artifacts:

  experiments/k1354/K1354_results.json      -- pre-registered gate, formal tests
  experiments/k1354/data/K1354_offset_panel.csv  -- event x offset (-5..+5) grid
  experiments/k1354/data/K1354_event_panel.csv   -- one row per OPEX event

Only labels, colours and layout are written here.

  1. k1354_general_offset.png -- for each trading-day offset around monthly
     option expiration, the paired event-level mean of
     (that day's Parkinson range variance - the same month's control average),
     rescaled by the overall control average so the axis reads as a percentage
     deviation.  Error bars are 95% intervals from 5,000 paired resamples.
     The rescaling divisor is a single constant, so the bars stay a difference
     in means; this deliberately avoids the per-event ratio average, which is
     heavily right-skewed and not a usable summary.
  2. k1354_general_quad.png -- quad-witching (132 events) versus ordinary
     monthly expiration (267 events) on the two pre-registered quantities,
     with the same rescaling and the same 5,000-resample intervals.

Palette: #B45309 (expiration day), #1D4ED8 (quad witching), #71717A (reference
and the offsets that carry no pre-registered hypothesis). Every mark carries a
direct value label, so the figures do not rely on colour discrimination alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
EXP = ROOT / "experiments" / "k1354"
RESULTS = EXP / "K1354_results.json"
OFFSET_CSV = EXP / "data" / "K1354_offset_panel.csv"
EVENT_CSV = EXP / "data" / "K1354_event_panel.csv"
ASSETS = ROOT / "storage" / "drafts" / "assets"

C_EXPIRY = "#B45309"
C_QUAD = "#1D4ED8"
C_PLAIN = "#71717A"
C_NEUTRAL = "#A1A1AA"
C_REF = "#52525B"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_MUTED = "#71717A"
C_SURFACE = "#FCFCFB"

BOOT_REPS = 5000
SEED = 42


def load_results() -> dict:
    with RESULTS.open(encoding="utf-8") as fh:
        return json.load(fh)


def _frame(ax) -> None:
    ax.set_facecolor(C_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(C_GRID)
    ax.tick_params(colors=C_MUTED, labelsize=10)


def _boot_ci(diffs: np.ndarray, rng: np.random.Generator) -> tuple[float, float]:
    """95% interval for the mean of paired event-level differences."""
    n = diffs.size
    draws = diffs[rng.integers(0, n, (BOOT_REPS, n))].mean(axis=1)
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return float(lo), float(hi)


def chart_offset(res: dict) -> Path:
    """Percentage deviation from the same-month control average, offset by offset."""
    scale = res["descriptive"]["mean_control_range_var"]
    panel = pd.read_csv(OFFSET_CSV)
    panel["diff"] = panel["value"] - panel["control_mean"]

    rng = np.random.default_rng(SEED)
    offsets, est, lo, hi = [], [], [], []
    for offset, grp in panel.groupby("offset"):
        diffs = grp["diff"].to_numpy()
        ci_lo, ci_hi = _boot_ci(diffs, rng)
        offsets.append(int(offset))
        est.append(diffs.mean() / scale * 100)
        lo.append(ci_lo / scale * 100)
        hi.append(ci_hi / scale * 100)

    est = np.asarray(est)
    lo = np.asarray(lo)
    hi = np.asarray(hi)
    x = np.arange(len(offsets))
    excludes_zero = (lo * hi) > 0
    colors = [
        C_EXPIRY if off == 0 else (C_PLAIN if ex else C_NEUTRAL)
        for off, ex in zip(offsets, excludes_zero)
    ]

    fig, ax = plt.subplots(figsize=(10.4, 5.9), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    ax.bar(x, est, 0.58, color=colors, zorder=2)
    ax.errorbar(
        x,
        est,
        yerr=[est - lo, hi - est],
        fmt="none",
        ecolor=C_TEXT,
        elinewidth=1.4,
        capsize=6,
        capthick=1.4,
        zorder=3,
    )
    ax.axhline(0, color=C_REF, linewidth=1.4)

    for i, off in enumerate(offsets):
        bold = off == 0 or excludes_zero[i]
        top = hi[i] if est[i] >= 0 else lo[i]
        va = "bottom" if est[i] >= 0 else "top"
        pad = 7 if est[i] >= 0 else -7
        ax.annotate(
            f"{est[i]:+.1f}%",
            (i, top),
            xytext=(0, pad),
            textcoords="offset points",
            ha="center",
            va=va,
            fontsize=11 if bold else 9.5,
            color=C_TEXT if bold else C_MUTED,
            fontweight="bold" if bold else "normal",
        )

    span = max(hi.max(), abs(lo.min()))
    ax.set_ylim(-span * 1.42, span * 1.34)
    ax.set_xticks(x)
    ax.set_xticklabels(
        [("到期日" if off == 0 else f"{off:+d}") for off in offsets],
        fontsize=11.5,
        color=C_TEXT,
    )
    ax.set_xlabel("相對到期日的交易日（負數為到期前）", fontsize=11, color=C_MUTED)
    ax.set_ylabel("與同月平常日子的差距（％，負值代表當天較窄）", fontsize=11, color=C_MUTED)
    ax.set_title(
        f"{panel['event_month'].nunique()} 次月結算、到期前後十一天，各自和同月平常日子比",
        fontsize=15,
        color=C_TEXT,
        fontweight="bold",
        pad=14,
    )

    flagged = "、".join(
        ("到期日" if off == 0 else f"{off:+d} 日")
        for off, ex in zip(offsets, excludes_zero)
        if ex
    )
    ax.annotate(
        f"誤差區間完全落在零以下的只有 {flagged}；其餘九根都跨過零。"
        f"誤差區間為 {BOOT_REPS:,} 次重複抽樣的 95% 範圍",
        (0.5, 0.02),
        xycoords="axes fraction",
        ha="center",
        fontsize=10.5,
        color=C_TEXT,
    )
    ax.grid(axis="y", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)

    out = ASSETS / "k1354_general_offset.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def chart_quad(res: dict) -> Path:
    """Quad witching versus ordinary monthly expiration on the two gate quantities."""
    scale = res["descriptive"]["mean_control_range_var"]
    events = pd.read_csv(EVENT_CSV)
    quad_mask = events["is_quad_witching"].astype(bool)

    measures = [
        ("pre3_minus_control", "到期前三天\n減同月平常日", "quad_vs_nonquad_pre3_minus_control"),
        ("post3_minus_pre3", "到期後三天\n減到期前三天", "quad_vs_nonquad_post3_minus_pre3"),
    ]
    groups = [
        ("四巫日", quad_mask, C_QUAD),
        ("普通月結算", ~quad_mask, C_PLAIN),
    ]

    rng = np.random.default_rng(SEED)
    x = np.arange(len(measures))
    width = 0.34

    fig, ax = plt.subplots(figsize=(10.0, 5.9), dpi=200)
    fig.patch.set_facecolor(C_SURFACE)
    _frame(ax)

    labels = []
    for gi, (gname, mask, color) in enumerate(groups):
        est, lo, hi = [], [], []
        for col, _, _ in measures:
            diffs = events.loc[mask, col].to_numpy()
            ci_lo, ci_hi = _boot_ci(diffs, rng)
            est.append(diffs.mean() / scale * 100)
            lo.append(ci_lo / scale * 100)
            hi.append(ci_hi / scale * 100)
        est = np.asarray(est)
        lo = np.asarray(lo)
        hi = np.asarray(hi)
        pos = x + (gi - 0.5) * width
        ax.bar(pos, est, width * 0.9, color=color, zorder=2,
               label=f"{gname}（{int(mask.sum())} 次）")
        ax.errorbar(pos, est, yerr=[est - lo, hi - est], fmt="none", ecolor=C_TEXT,
                    elinewidth=1.4, capsize=7, capthick=1.4, zorder=3)
        for i in range(len(measures)):
            top = hi[i] if est[i] >= 0 else lo[i]
            va = "bottom" if est[i] >= 0 else "top"
            pad = 7 if est[i] >= 0 else -7
            ax.annotate(
                f"{est[i]:+.1f}%",
                (pos[i], top),
                xytext=(0, pad),
                textcoords="offset points",
                ha="center",
                va=va,
                fontsize=11.5,
                color=C_TEXT,
                fontweight="bold",
            )
        labels.append((lo, hi))

    ax.axhline(0, color=C_REF, linewidth=1.4)
    span = max(max(h.max() for _, h in labels), max(abs(l.min()) for l, _ in labels))
    ax.set_ylim(-span * 1.55, span * 1.62)
    ax.set_xticks(x)
    ax.set_xticklabels([m[1] for m in measures], fontsize=12, color=C_TEXT)
    ax.set_ylabel("與比較基準的差距（％）", fontsize=11, color=C_MUTED)
    ax.set_title("四巫日並沒有比普通月結算特別", fontsize=15, color=C_TEXT,
                 fontweight="bold", pad=14)

    notes = []
    for col, name, key in measures:
        p = res["tests"][key]["welch_p_two_sided"]
        notes.append(f"{name.replace(chr(10), '')}　p = {p:.3f}")
    ax.annotate(
        "兩組差異的檢定：" + "　｜　".join(notes)
        + f"\n誤差區間為 {BOOT_REPS:,} 次重複抽樣的 95% 範圍",
        (0.5, 0.015),
        xycoords="axes fraction",
        ha="center",
        fontsize=10.5,
        color=C_TEXT,
        linespacing=1.5,
    )
    ax.legend(frameon=False, fontsize=11, loc="upper right", labelcolor=C_TEXT)
    ax.grid(axis="y", color=C_GRID, linewidth=0.7, alpha=0.6)
    ax.set_axisbelow(True)

    out = ASSETS / "k1354_general_quad.png"
    fig.tight_layout()
    fig.savefig(out, facecolor=C_SURFACE)
    plt.close(fig)
    return out


def print_offset_diagnostics(res: dict) -> None:
    """Per-offset numbers quoted in the article that are not in the results JSON.

    The published experiment only reports the pre-registered windows.  The
    article also quotes offset-by-offset figures (the +5 dip, and the fact that
    the signed-rank test flags every single offset), so they are recomputed
    here from the offset panel to keep every number in the text reproducible.
    """
    from scipy import stats  # local import: only needed for the diagnostics

    scale = res["descriptive"]["mean_control_range_var"]
    panel = pd.read_csv(OFFSET_CSV)
    panel["diff"] = panel["value"] - panel["control_mean"]
    print("\noffset  mean%    t      t_p     signed_rank_p  share_above")
    for offset, grp in panel.groupby("offset"):
        diffs = grp["diff"].to_numpy()
        t_stat, t_p = stats.ttest_1samp(diffs, 0.0)
        rank_p = stats.wilcoxon(diffs).pvalue
        print(
            f"{int(offset):+d}     {diffs.mean() / scale * 100:+6.2f}  "
            f"{t_stat:+5.2f}  {t_p:6.4f}  {rank_p:13.3e}  {(diffs > 0).mean():.3f}"
        )


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    res = load_results()
    for path in (chart_offset(res), chart_quad(res)):
        print(f"wrote {path}")
    print_offset_diagnostics(res)


if __name__ == "__main__":
    main()
