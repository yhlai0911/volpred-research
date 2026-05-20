"""K274 article charts — novelty distribution, paper-4 viability, paper readiness."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "k274_paper_mapping_results.json"
FIG_DIR = ROOT / "figures"
FIG_DIR.mkdir(exist_ok=True)

plt.rcParams["font.sans-serif"] = [
    "PingFang TC",
    "Heiti TC",
    "Microsoft JhengHei",
    "Arial Unicode MS",
]
plt.rcParams["axes.unicode_minus"] = False


def main() -> None:
    data = json.loads(RESULTS.read_text(encoding="utf-8"))

    # ---- Figure 1: novelty distribution donut ----
    summary = data["summary"]
    nov = summary["novelty_distribution"]
    labels = ["NOVEL（全新貢獻）", "EXTENSION（延伸文獻）", "CONFIRMATION（再確認）", "CONTRADICTION（推翻）"]
    keys = ["NOVEL", "EXTENSION", "CONFIRMATION", "CONTRADICTION"]
    counts = [nov[k] for k in keys]
    colors = ["#2563eb", "#10b981", "#f59e0b", "#ef4444"]

    fig, ax = plt.subplots(figsize=(7.5, 6.2), dpi=160)
    # Drop zero-count slices for cleaner pie
    nz = [(l, c, col) for l, c, col in zip(labels, counts, colors) if c > 0]
    nz_labels = [x[0] for x in nz]
    nz_counts = [x[1] for x in nz]
    nz_colors = [x[2] for x in nz]
    wedges, _texts, autotexts = ax.pie(
        nz_counts,
        labels=nz_labels,
        colors=nz_colors,
        autopct=lambda p: f"{p:.0f}%\n({int(round(p * sum(nz_counts) / 100))})",
        startangle=90,
        pctdistance=0.72,
        wedgeprops=dict(width=0.42, edgecolor="white", linewidth=2),
        textprops=dict(fontsize=11),
    )
    for at in autotexts:
        at.set_color("white")
        at.set_fontweight("bold")
    ax.set_title(
        "K274：270 實驗的新穎度分佈\n(Top 20 findings, 0 contradictions)",
        fontsize=14,
        fontweight="bold",
        pad=18,
    )
    ax.text(0, 0, "20\nfindings", ha="center", va="center", fontsize=15, fontweight="bold", color="#374151")
    plt.tight_layout()
    out1 = FIG_DIR / "k274_novelty_distribution.png"
    plt.savefig(out1, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"WROTE {out1} ({out1.stat().st_size} bytes)")

    # ---- Figure 2: paper-4 viability horizontal bar ----
    p4 = data["paper_4_opportunities"]
    items = sorted(p4, key=lambda x: x["viability"], reverse=True)
    short_labels = {
        "Paper_4A_GLD_SELFHEALING": "4A：GLD 自我修復 + 等權重",
        "Paper_4B_QLIKE_CEILING": "4B：QLIKE 天花板（不可能定理）",
        "Paper_4C_VT_INSURANCE": "4C：VT 即回撤保險",
        "Paper_4D_WHY_5050_WORKS": "4D：為什麼 50/50 不可被打敗",
    }
    names = [short_labels.get(p["paper_id"], p["paper_id"]) for p in items]
    scores = [p["viability"] for p in items]
    bar_colors = ["#2563eb" if s >= 0.65 else "#10b981" if s >= 0.55 else "#f59e0b" if s >= 0.45 else "#ef4444" for s in scores]

    fig, ax = plt.subplots(figsize=(9, 5.2), dpi=160)
    y = list(range(len(names)))
    bars = ax.barh(y, scores, color=bar_colors, edgecolor="white", linewidth=1.5)
    ax.set_yticks(y)
    ax.set_yticklabels(names, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Viability score（0-1, 越高越可行）", fontsize=11)
    ax.axvline(0.65, ls="--", color="#9ca3af", lw=1, alpha=0.7)
    ax.text(0.652, len(names) - 0.4, "可行門檻 0.65", fontsize=9, color="#6b7280")
    for bar, s in zip(bars, scores):
        ax.text(s + 0.012, bar.get_y() + bar.get_height() / 2, f"{s:.2f}", va="center", fontsize=11, fontweight="bold")
    ax.set_title("Paper 4 寫作可行性評分（K274 對照）", fontsize=14, fontweight="bold", pad=12)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", alpha=0.25, linestyle=":")
    plt.tight_layout()
    out2 = FIG_DIR / "k274_paper_4_viability.png"
    plt.savefig(out2, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"WROTE {out2} ({out2.stat().st_size} bytes)")

    # ---- Figure 3: paper readiness (3 papers from paper_mapping) ----
    pm = data["paper_mapping"]
    rows = [
        ("Paper 1（JBF）槓桿方向 + 模型選擇", pm["Paper_1_JBF"]["publication_readiness"], "70% NOVEL"),
        ("Paper 2（PBFJ）台股 VT + TZ", pm["Paper_2_PBFJ"]["publication_readiness"], "30% NOVEL"),
        ("Paper 3（VT vs Trend）gamma-TSMOM", pm["Paper_3_VT_TREND"]["publication_readiness"], "60% NOVEL"),
    ]
    rows.sort(key=lambda r: r[1], reverse=True)
    names3 = [r[0] for r in rows]
    ready = [r[1] for r in rows]
    novel_lbls = [r[2] for r in rows]

    fig, ax = plt.subplots(figsize=(9, 4.6), dpi=160)
    y = list(range(len(names3)))
    bars = ax.barh(y, ready, color=["#1e40af", "#0d9488", "#7c3aed"], edgecolor="white", linewidth=1.5)
    ax.set_yticks(y)
    ax.set_yticklabels(names3, fontsize=11)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.0)
    ax.set_xlabel("Publication readiness（0-1, 越高越接近投稿）", fontsize=11)
    for bar, r, nl in zip(bars, ready, novel_lbls):
        ax.text(r + 0.012, bar.get_y() + bar.get_height() / 2, f"{r:.2f}  |  {nl}", va="center", fontsize=10.5, fontweight="bold")
    ax.set_title("3 本論文的投稿就緒度（K274 評估）", fontsize=14, fontweight="bold", pad=12)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", alpha=0.25, linestyle=":")
    plt.tight_layout()
    out3 = FIG_DIR / "k274_paper_readiness.png"
    plt.savefig(out3, dpi=160, bbox_inches="tight")
    plt.close(fig)
    print(f"WROTE {out3} ({out3.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
