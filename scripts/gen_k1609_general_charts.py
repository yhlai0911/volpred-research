"""Charts for the K1609 general-audience article.

Both figures read every number from experiments/K1609/K1609_results.json.

  1. k1609_general_gate_forest.png -- all six primary cells expressed in
     standard-error units (coefficient divided by its own HAC standard error),
     with the 95% interval and the pre-registered |t| >= 3 gate drawn as a
     band. Nothing reaches the gate; the largest cell stops at -2.05.
  2. k1609_general_two_rulers.png -- the OLS p-value and the year-cluster
     resample p_sign for the same six cells, side by side. They disagree about
     which cell is "closest", because they are not measuring the same thing:
     OLS is a controlled slope on the continuous proxy, the resample is an
     uncontrolled high-minus-low mean difference.

Also prints the distance-to-gate arithmetic used in the article body.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "PingFang HK",
    "Heiti TC",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "experiments" / "K1609" / "K1609_results.json"
ASSETS = ROOT / "storage" / "assets"

C_GOLD = "#B45309"
C_SILVER = "#57534E"
C_BAND = "#EDEDF0"
C_GRID = "#D4D4D8"
C_TEXT = "#27272A"
C_ACCENT = "#0F766E"

GATE = 3.0

METAL_LABEL = {"gold": "黃金", "silver": "白銀"}
TARGET_LABEL = {
    "log_fwd5_rv_ratio": "下週波動比上週高多少",
    "downside_semivar_5d_ann": "下週的下跌波動",
    "fwd21_return_real_yield_corr": "未來一個月報酬與實質利率的連動",
}
ORDER = [
    ("gold", "log_fwd5_rv_ratio"),
    ("silver", "log_fwd5_rv_ratio"),
    ("gold", "downside_semivar_5d_ann"),
    ("silver", "downside_semivar_5d_ann"),
    ("gold", "fwd21_return_real_yield_corr"),
    ("silver", "fwd21_return_real_yield_corr"),
]


def load() -> dict:
    return json.loads(RESULTS.read_text())


def cells(data: dict) -> list[dict]:
    out = []
    for metal, target in ORDER:
        block = data["results"][metal][target]
        ols = block["ols_hac"]
        boot = block["year_bootstrap_high_proxy_diff"]
        out.append(
            {
                "metal": metal,
                "target": target,
                "label": f"{METAL_LABEL[metal]}｜{TARGET_LABEL[target]}",
                "coef": ols["coef"],
                "se": ols["se_hac_lag4"],
                "t": ols["t_hac_lag4"],
                "p": ols["p_hac_lag4"],
                "n": ols["n"],
                "r2": ols["r2"],
                "boot_p": boot["p_sign_two_sided"],
                "boot_obs": boot["observed_high_minus_low"],
                "boot_lo": boot["ci95_low"],
                "boot_hi": boot["ci95_high"],
            }
        )
    return out


def fig_gate_forest(rows: list[dict]) -> Path:
    fig, ax = plt.subplots(figsize=(9.6, 5.4), dpi=160)
    ys = list(range(len(rows)))[::-1]

    ax.axvspan(-GATE, GATE, color=C_BAND, zorder=0)
    for x in (-GATE, GATE):
        ax.axvline(x, color=C_ACCENT, lw=1.4, ls="--", zorder=1)
    ax.axvline(0, color=C_TEXT, lw=1.2, zorder=2)

    for y, r in zip(ys, rows):
        color = C_GOLD if r["metal"] == "gold" else C_SILVER
        ax.errorbar(
            r["t"], y, xerr=1.96, fmt="o", ms=8, color=color,
            ecolor=color, elinewidth=2.0, capsize=5, zorder=3,
        )
        ax.text(r["t"], y + 0.26, f"{r['t']:+.2f}", ha="center", fontsize=10.5,
                weight="bold", color=color)

    ax.set_yticks(ys)
    ax.set_yticklabels([r["label"] for r in rows], fontsize=10.5)
    ax.set_xlim(-4.6, 4.6)
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.set_xlabel("估計值 ÷ 它自己的誤差（橫線為 95% 範圍）", fontsize=10.5)
    ax.set_title("六格全部落在灰帶裡：離事先畫的那條線最近的一格，也只走到 2.05",
                 fontsize=13.5, pad=14, weight="bold")
    ax.text(GATE + 0.12, -0.62, "事先訂的門檻 3.0", fontsize=9.5, color=C_ACCENT)
    ax.text(-GATE - 0.12, -0.62, "門檻 −3.0", fontsize=9.5, color=C_ACCENT,
            ha="right")
    ax.grid(axis="x", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1609_general_gate_forest.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def fig_two_rulers(rows: list[dict]) -> Path:
    fig, ax = plt.subplots(figsize=(9.6, 5.4), dpi=160)
    ys = list(range(len(rows)))[::-1]

    ax.axvline(0.05, color=C_ACCENT, lw=1.4, ls="--", zorder=1)

    for y, r in zip(ys, rows):
        ax.plot([r["p"], r["boot_p"]], [y, y], color=C_GRID, lw=2.2, zorder=2)
        ax.scatter(r["p"], y, s=70, color=C_GOLD, zorder=3,
                   label="迴歸（有控制其他因素）" if y == ys[0] else None)
        ax.scatter(r["boot_p"], y, s=70, color=C_SILVER, marker="s", zorder=3,
                   label="按年份重抽（沒有控制）" if y == ys[0] else None)

    ax.text(rows[4]["p"], ys[4] + 0.28, f"{rows[4]['p']:.3f}", ha="center",
            fontsize=10, weight="bold", color=C_GOLD)
    ax.text(rows[3]["boot_p"], ys[3] + 0.28, f"{rows[3]['boot_p']:.4f}",
            ha="center", fontsize=10, weight="bold", color=C_SILVER)

    ax.set_yticks(ys)
    ax.set_yticklabels([r["label"] for r in rows], fontsize=10.5)
    ax.set_xlim(-0.03, 1.03)
    ax.set_ylim(-0.8, len(rows) - 0.2)
    ax.set_xlabel("機率值（越左邊越像有東西）", fontsize=10.5)
    ax.set_title("兩把尺量同一格，答案不一樣——因為它們量的本來就不是同一件事",
                 fontsize=13.5, pad=14, weight="bold")
    ax.text(0.062, -0.62, "0.05", fontsize=9.5, color=C_ACCENT)
    ax.legend(frameon=False, fontsize=9.5, loc="lower right")
    ax.grid(axis="x", color=C_GRID, lw=0.7)
    ax.set_axisbelow(True)
    for s in ("top", "right", "left"):
        ax.spines[s].set_visible(False)
    fig.tight_layout()

    out = ASSETS / "k1609_general_two_rulers.png"
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)
    return out


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    data = load()
    rows = cells(data)

    print("cell | coef | se | t | p | boot_p | need_coef_for_t3 | share_of_gate")
    for r in rows:
        need = GATE * r["se"]
        print(
            f"{r['metal']:6s} {r['target']:28s} "
            f"coef={r['coef']:+.6f} se={r['se']:.6f} t={r['t']:+.4f} "
            f"p={r['p']:.4f} boot_p={r['boot_p']:.4f} n={r['n']} "
            f"r2={r['r2']:.4f} need={need:.6f} share={abs(r['coef'])/need:.4f}"
        )
    best = max(rows, key=lambda r: abs(r["t"]))
    print(f"\nlargest |t| = {abs(best['t']):.4f} ({best['metal']} {best['target']})")
    print(f"  coef {best['coef']:+.6f}, HAC 95% CI "
          f"[{best['coef'] - 1.96 * best['se']:+.6f}, "
          f"{best['coef'] + 1.96 * best['se']:+.6f}]")
    print(f"  gate needs |coef| >= {GATE * best['se']:.6f}; "
          f"observed is {abs(best['coef']) / (GATE * best['se']) * 100:.1f}% of that, "
          f"i.e. {GATE / abs(best['t']):.2f}x too small")
    print(f"\nsample: {data['sample']['weekly_origin_rows']} weekly origins, "
          f"gold {data['sample']['rows_by_metal']['gold']}, "
          f"silver {data['sample']['rows_by_metal']['silver']}, "
          f"{data['sample']['start']} -> {data['sample']['end']}")
    print(f"seed={data['seed']}, strong_cells={data['verdict']['strong_cells']}, "
          f"verdict={data['verdict']['verdict']}")
    for a in data["cme_fetch_attempts"]:
        print(f"CME {a['metal']}: bytes={a['bytes']} elapsed={a['elapsed_sec']}s "
              f"status={a['status_code']}")

    for p in (fig_gate_forest(rows), fig_two_rulers(rows)):
        print(f"wrote {p.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
