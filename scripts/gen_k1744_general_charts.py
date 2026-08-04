"""Charts for the K1744 general-audience article.

Every number is read at run time from the two canonical evidence files:

  experiments/k1744/K1744_results.json
  experiments/k1744/raw_cache_manifest.json

Only labels, colours and layout live in this file.

  1. k1744_general_sources.png -- horizontal bars of the nine inspected sources
     grouped by why each one can or cannot serve as the record-level monthly
     proxy. Categories are derived from the manifest's `proxy_eligibility`
     field, so the counts cannot drift from the audit. The chart annotates the
     single number that decided the experiment: zero of nine sources exposed a
     complete, versioned, record-level enumeration.
  2. k1744_general_thresholds.png -- the three preregistered minimum sample
     thresholds drawn as bars, with the observed side drawn as a hatched
     "cannot be counted" block rather than a zero bar. The distinction matters:
     the results file records the observed counts as null and flags
     `unknown_counts_are_not_zero`, so drawing them as zero would misstate the
     finding.

Palette: #B45309 (the blocking category / the unknown side), #1D4ED8 (the
preregistered requirement), #71717A (neutral context). Every mark carries a
direct numeric label, so neither figure relies on colour alone.
"""

from __future__ import annotations

import json
from collections import OrderedDict
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
RESULTS = ROOT / "experiments/k1744/K1744_results.json"
MANIFEST = ROOT / "experiments/k1744/raw_cache_manifest.json"
OUT_DIR = ROOT / "storage/drafts/assets"

BLOCK = "#B45309"
REQUIRE = "#1D4ED8"
NEUTRAL = "#71717A"

# manifest proxy_eligibility -> reader-facing bucket. Every eligibility string
# present in the manifest must appear here; the script asserts full coverage so
# a future manifest edit fails loudly instead of silently dropping a source.
BUCKETS = OrderedDict(
    [
        (
            "事後總量報告，沒有逐月時間軸",
            [
                "ineligible_retrospective_aggregate",
                "ineligible_global_retrospective_report",
                "ineligible_level_claim_only",
            ],
        ),
        (
            "研究綜述，講機制不講拉美逐筆",
            [
                "ineligible_non_latam_research_summary",
                "ineligible_global_mechanism_only",
            ],
        ),
        (
            "單筆或單一管理人公告，沒有母體名單",
            [
                "insufficient_isolated_record_without_enumeration_frame",
                "ineligible_single_manager_and_transaction_not_final_close_universe",
            ],
        ),
        (
            "方法論引用，本來就不是資料來源",
            ["not_a_proxy_source"],
        ),
        (
            "唯一規格相符的名冊，要登入才給看",
            ["inaccessible_required_record_level_export"],
        ),
    ]
)


def load() -> tuple[dict, dict]:
    return json.loads(RESULTS.read_text()), json.loads(MANIFEST.read_text())


def chart_sources(manifest: dict) -> Path:
    sources = manifest["sources"]
    lookup = {tag: bucket for bucket, tags in BUCKETS.items() for tag in tags}
    missing = {s["proxy_eligibility"] for s in sources} - set(lookup)
    if missing:
        raise SystemExit(f"unmapped proxy_eligibility values: {sorted(missing)}")

    counts = OrderedDict((bucket, 0) for bucket in BUCKETS)
    for s in sources:
        counts[lookup[s["proxy_eligibility"]]] += 1
    if sum(counts.values()) != len(sources):
        raise SystemExit("bucket counts do not sum to the manifest source count")

    labels = list(counts)
    values = [counts[k] for k in labels]
    colours = [BLOCK if k.startswith("唯一規格相符") else NEUTRAL for k in labels]

    fig, ax = plt.subplots(figsize=(10.4, 5.4))
    ypos = range(len(labels))
    ax.barh(list(ypos), values, color=colours, height=0.62)
    ax.set_yticks(list(ypos))
    ax.set_yticklabels(labels, fontsize=11.5)
    ax.invert_yaxis()
    for y, v in zip(ypos, values):
        ax.text(v + 0.06, y, f"{v} 個", va="center", fontsize=12, color="#27272A")

    ax.set_xlim(0, max(values) + 1.2)
    ax.set_xlabel("查過的來源數（共 %d 個）" % len(sources), fontsize=11.5)
    ax.set_title(
        "查了九個來源，沒有一個能拿來建逐月資料",
        fontsize=15,
        pad=14,
        loc="left",
    )
    http_ok = sum(1 for s in sources if s.get("http_status") == 200)
    ax.text(
        0.0,
        -0.155,
        f"九個來源全部留下回應雜湊與位元組數；{http_ok} 個回 200、"
        f"{len(sources) - http_ok} 個回 403。能給出「完整、可標時點、逐筆」名冊的：0 個。",
        transform=ax.transAxes,
        fontsize=10.5,
        color="#52525B",
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#E4E4E7", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()

    out = OUT_DIR / "k1744_general_sources.png"
    fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def chart_thresholds(results: dict) -> Path:
    feas = results["proxy"]["feasibility"]
    th = feas["thresholds"]
    obs = feas["observed"]

    rows = [
        ("不同的募集完成公告，至少要有", th["minimum_distinct_eligible_events"], "件", obs["eligible_event_count"]),
        ("有公告的月份，至少要有", th["minimum_nonzero_exposure_months"], "個月", obs["nonzero_month_count"]),
        ("對齊後可用的共同月份，至少要有", th["minimum_common_months_after_all_lags"], "個月", obs["common_month_count"]),
    ]

    fig, ax = plt.subplots(figsize=(10.8, 5.0))
    ypos = list(range(len(rows)))
    req = [r[1] for r in rows]
    span = max(req)
    box_left, box_width = span * 1.30, span * 0.36

    ax.barh(ypos, req, color=REQUIRE, height=0.46)
    for y, (_, value, unit, observed) in zip(ypos, rows):
        assert observed is None, "observed counts are null by contract"
        ax.text(value + span * 0.012, y, f"{value} {unit}", va="center", fontsize=12.5, color=REQUIRE)
        ax.barh(
            y,
            box_width,
            left=box_left,
            height=0.46,
            color="none",
            edgecolor=BLOCK,
            hatch="///",
            linewidth=1.2,
        )
        ax.text(
            box_left + box_width / 2,
            y,
            "數不出來",
            ha="center",
            va="center",
            fontsize=12,
            color=BLOCK,
        )

    ax.set_yticks(ypos)
    ax.set_yticklabels([r[0] for r in rows], fontsize=11.5)
    ax.invert_yaxis()
    ax.set_xlim(0, box_left + box_width + span * 0.04)
    ax.set_xticks([0, 20, 40, 60])
    ax.set_xlabel("事前寫死的最低門檻（左側藍柱）", fontsize=11.5)
    ax.set_title(
        "三道門檻不是沒達標，是連分子都湊不出來",
        fontsize=15,
        pad=14,
        loc="left",
    )
    ax.text(
        box_left + box_width / 2,
        -0.72,
        "實際值\n（記錄為未知，不是 0）",
        fontsize=11.5,
        color=BLOCK,
        ha="center",
        va="center",
    )
    ax.text(
        0.0,
        -0.24,
        "門檻在看到任何市場資料之前就寫死並鎖檔；實際市場資料抓取次數為 %d 次。"
        % results["data"]["sample"]["outcome_rows"],
        transform=ax.transAxes,
        fontsize=10.5,
        color="#52525B",
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="x", color="#E4E4E7", linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()

    out = OUT_DIR / "k1744_general_thresholds.png"
    fig.savefig(out, dpi=170, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return out


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    results, manifest = load()
    for path in (chart_sources(manifest), chart_thresholds(results)):
        print(f"wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
