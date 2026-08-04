"""Charts for the K1479 general-audience article.

Every number is read at run time from the single canonical evidence file:

  experiments/k1479/k1479_results.json

Only labels, colours and layout live in this file. Two figures:

  1. k1479_general_gap.png -- for each of the three treated stocks and each of
     the three daily proxies, the pre-existing gap to the matched controls
     (``treated_beta``) next to the extra gap that opened after the ETF launch
     (``did_beta``). Both are divided by the control-group baseline
     (``intercept``) so that the three proxies, which live on different scales,
     can share one axis. The launch bar carries a +/- 2 standard-error whisker
     derived as ``did_beta / did_t``; every whisker crosses zero, which is the
     visual statement of the null.
  2. k1479_general_strength.png -- the nine tests ranked by |did_t|, i.e. how
     many measurement errors wide each estimated launch effect is, against the
     conventional 2.0 line. The largest is 1.30.

Palette: #1D4ED8 (the gap that was already there), #B45309 (the gap added after
the launch), #71717A (neutral context). Every mark carries a direct numeric
label, so neither figure relies on colour alone.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments/k1479/k1479_results.json"
OUT_DIR = ROOT / "storage/drafts/assets"

BASE = "#1D4ED8"
ADDED = "#B45309"
NEUTRAL = "#71717A"

# ETF key in the results file -> reader-facing row label.
PAIRS = [
    ("TSLL", "特斯拉\n對照 福特、通用"),
    ("NVDL", "輝達\n對照 超微、博通"),
    ("CONL", "Coinbase\n對照 Robinhood、MicroStrategy"),
]

# proxy key -> reader-facing panel title.
PROXIES = [
    ("abs_ret", "當天開盤到收盤的變動幅度"),
    ("park_var", "當天最高價和最低價拉開的幅度"),
    ("signed_clv", "順著當天方向收在極端的程度"),
]


def load() -> dict:
    return json.loads(RESULTS.read_text())


def rows(results: dict):
    """Yield (etf, label, proxy, title, base_pct, added_pct, se_pct, t, p, n)."""
    for etf, label in PAIRS:
        for proxy, title in PROXIES:
            r = results["event_results"][etf][proxy]
            icpt = r["intercept"]
            se = r["did_beta"] / r["did_t"]
            yield (
                etf,
                label,
                proxy,
                title,
                100 * r["treated_beta"] / icpt,
                100 * r["did_beta"] / icpt,
                100 * se / icpt,
                r["did_t"],
                r["did_p"],
                r["n_obs"],
            )


def chart_gap(results: dict) -> Path:
    data = list(rows(results))
    fig, axes = plt.subplots(3, 1, figsize=(11.0, 11.2))

    for ax, (proxy, title) in zip(axes, PROXIES):
        block = [d for d in data if d[2] == proxy]
        ypos = list(range(len(block)))
        h = 0.34

        for y, d in zip(ypos, block):
            _, _, _, _, base, added, se, t, p, _ = d
            ax.barh(y - h / 2, base, height=h, color=BASE)
            ax.barh(y + h / 2, added, height=h, color=ADDED)
            ax.errorbar(
                added,
                y + h / 2,
                xerr=2 * abs(se),
                fmt="none",
                ecolor="#78350F",
                elinewidth=1.3,
                capsize=4,
            )
            off = 3.0 if base >= 0 else -3.0
            ax.text(
                base + off,
                y - h / 2,
                f"{base:+.0f}%",
                va="center",
                ha="left" if base >= 0 else "right",
                fontsize=11,
                color=BASE,
            )
            edge = added + (2 * abs(se) if added >= 0 else -2 * abs(se))
            ax.text(
                edge + (4.0 if added >= 0 else -4.0),
                y + h / 2,
                f"{added:+.0f}%",
                va="center",
                ha="left" if added >= 0 else "right",
                fontsize=11,
                color=ADDED,
            )

        ax.axvline(0, color="#27272A", linewidth=1.0)
        ax.set_yticks(ypos)
        ax.set_yticklabels([d[1] for d in block], fontsize=10.5)
        ax.invert_yaxis()
        ax.set_xlim(-140, 190)
        ax.set_title(title, fontsize=13.5, loc="left", pad=8)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.grid(axis="x", color="#E4E4E7", linewidth=0.8)
        ax.set_axisbelow(True)

    handles = [
        Patch(facecolor=BASE, label="掛牌前就有的差距"),
        Patch(facecolor=ADDED, label="掛牌後新增的差距（橫線為兩倍誤差範圍）"),
    ]
    fig.legend(
        handles=handles,
        loc="upper right",
        bbox_to_anchor=(0.995, 0.995),
        fontsize=11,
        frameon=False,
    )

    axes[-1].set_xlabel("和對照組平常水準相比的百分比", fontsize=11.5)
    window = results["data"]["event_window_calendar_days_each_side"]
    axes[-1].text(
        0.0,
        -0.42,
        f"藍柱是這檔股票本來就比同業多動的幅度，橘柱是基金掛牌之後才新增的差距，"
        f"取掛牌日前後各 {window} 個日曆日。九根橘柱的誤差範圍全部跨過零。",
        transform=axes[-1].transAxes,
        fontsize=10.5,
        color="#52525B",
    )

    fig.suptitle(
        "本來就有的差距很大，掛牌之後新增的差距量不出來",
        fontsize=16,
        x=0.012,
        ha="left",
        y=0.985,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.965))

    out = OUT_DIR / "k1479_general_gap.png"
    fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def chart_strength(results: dict) -> Path:
    data = sorted(rows(results), key=lambda d: abs(d[7]))
    labels = [f"{d[1].splitlines()[0]}｜{d[3]}" for d in data]
    values = [abs(d[7]) for d in data]

    fig, ax = plt.subplots(figsize=(11.0, 5.8))
    ypos = list(range(len(data)))
    ax.barh(ypos, values, color=NEUTRAL, height=0.6)
    for y, (v, d) in zip(ypos, zip(values, data)):
        ax.text(v + 0.035, y, f"{v:.2f}", va="center", fontsize=11.5, color="#27272A")

    ax.axvline(2.0, color=ADDED, linewidth=1.6, linestyle="--")
    ax.text(2.06, len(data) - 0.4, "一般認定看得出變化的門檻", fontsize=11, color=ADDED)

    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=10.5)
    ax.invert_yaxis()
    ax.set_xlim(0, 2.5)
    ax.set_xlabel("掛牌後新增的差距等於幾倍的量測誤差", fontsize=11.5)
    ax.set_title(
        "九次比對，最強的一次只有 %.2f 倍" % max(values),
        fontsize=15.5,
        loc="left",
        pad=12,
    )
    n_obs = sorted({d[9] for d in data})
    ax.text(
        0.0,
        -0.19,
        "每次比對用 %s 筆日資料（標的股加兩檔同業，掛牌日前後各 %d 個日曆日）。"
        % ("、".join(str(n) for n in n_obs), results["data"]["event_window_calendar_days_each_side"]),
        transform=ax.transAxes,
        fontsize=10.5,
        color="#52525B",
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#E4E4E7", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()

    out = OUT_DIR / "k1479_general_strength.png"
    fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results = load()
    if results["verdict"]["overall"] != "NULL":
        raise SystemExit("verdict is no longer NULL; the chart captions must be revisited")
    for path in (chart_gap(results), chart_strength(results)):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
