"""Correct mile_eda69bfb against the K741 canonical NFP rerun.

The article was written from the archived K741 run, which used a proxy NFP
calendar (first Friday of the month) and a control frame that leaked 21
Dec-2009 days. The canonical rerun uses the official BLS release calendar with
forward-only mapping (experiments/k741/k741_nfp_event_study_canonical_results.json),
which changes every Part A/B number the article quotes.

Two things change beyond arithmetic:

1. Significance is withdrawn. The archived article called the NFP-vs-all gap
   "確實存在，不只是碰巧". Under the canonical run the parametric test is
   p=0.0394 (Welch) / 0.0506 (Student) raw, and Holm over the two overall
   comparisons adjusts it to 0.0722 — nothing clears 5% under any Holm family
   (k741_cert_merge_summary.json: anything_clears_5pct_under_any_family=false).
   The direction survives; the claim of statistical significance does not.

2. The strategy backtest and the T+n drift numbers were NOT rerun. Canonical
   scope is "Parts A and B only"; Parts C/D are archived. Those numbers stay in
   the body but are now labelled as computed on the superseded calendar, rather
   than silently presented as current.

Numbers are read from the canonical JSON, never typed in by hand.
"""

import json
from pathlib import Path

from volpred.publisher.article_correction import apply_article_correction

ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "experiments/k741/k741_nfp_event_study_canonical_results.json"
CERT = ROOT / "experiments/k741/k741_cert_merge_summary.json"

d = json.loads(CANON.read_text(encoding="utf-8"))
cert = json.loads(CERT.read_text(encoding="utf-8"))
pa = d["part_a_historical"]
rb = d["part_b_vix_regimes"]
low, med, elev, high = (
    rb["Low (VIX<15)"],
    rb["Medium (15-20)"],
    rb["Elevated (20-25)"],
    rb["High (VIX>=25)"],
)

n = pa["n_nfp"]
n_non = pa["n_non_nfp"]
nfp_abs = pa["nfp_mean_abs_return_pct"]
non_abs = pa["non_nfp_mean_abs_return_pct"]
fri_abs = pa["friday_mean_abs_return_pct"]
wilcoxon = pa["wilcoxon_p_vs_all"]
pct_pos = pa["pct_positive"]
vix_drops = pa["vix_drops_pct"]
holm_overall = cert["holm_families_min_adjusted_p"]["overall_pair"]
p_welch = pa["test_variants_vs_all"]["p_welch"]
p_student = pa["test_variants_vs_all"]["p_student"]

assert cert["anything_clears_5pct_under_any_family"] is False
spread = high["mean_abs_return_pct"] / low["mean_abs_return_pct"]

R = [
    (f"一共 195 次非農公布日", f"一共 {n} 次非農公布日"),
    (
        "**VIX 低於 15 時，NFP 日 SPY 絕對報酬平均 0.498%；VIX 高於 25 時，同樣是 NFP 日，平均 1.488%。**",
        f"**VIX 低於 15 時，NFP 日 SPY 絕對報酬平均 {low['mean_abs_return_pct']:.3f}%；"
        f"VIX 高於 25 時，同樣是 NFP 日，平均 {high['mean_abs_return_pct']:.3f}%。**",
    ),
    ("差距三倍。同樣是非農公布日", f"差距 {spread:.1f} 倍。同樣是非農公布日"),
    ("這 195 次 NFP 覆蓋了 16 年", f"這 {n} 次 NFP 覆蓋了 16 年"),
    (
        "| VIX < 15（平靜） | 62 次 | **0.498%** | 69.4% |",
        f"| VIX < 15（平靜） | {low['n']} 次 | **{low['mean_abs_return_pct']:.3f}%** | {low['pct_positive']:.1f}% |",
    ),
    (
        "| VIX 15-20（正常） | 78 次 | **0.757%** | 61.5% |",
        f"| VIX 15-20（正常） | {med['n']} 次 | **{med['mean_abs_return_pct']:.3f}%** | {med['pct_positive']:.1f}% |",
    ),
    (
        "| VIX 20-25（偏高） | 27 次 | **1.022%** | 66.7% |",
        f"| VIX 20-25（偏高） | {elev['n']} 次 | **{elev['mean_abs_return_pct']:.3f}%** | {elev['pct_positive']:.1f}% |",
    ),
    (
        "| VIX ≥ 25（恐慌） | 28 次 | **1.488%** | **25.0%** |",
        f"| VIX ≥ 25（恐慌） | {high['n']} 次 | **{high['mean_abs_return_pct']:.3f}%** | **{high['pct_positive']:.1f}%** |",
    ),
    (
        "*對照：非 NFP 日整體平均絕對報酬 0.713%*",
        f"*對照：非 NFP 日整體平均絕對報酬 {non_abs:.3f}%*",
    ),
    (
        "*資料來源：yfinance（SPY, ^VIX），實驗 K741，2010-01-01 至 2026-03-28*",
        "*資料來源：yfinance（SPY, ^VIX），實驗 K741 canonical 重跑（官方 BLS 發布日曆），2010-01-01 至 2026-03-30*",
    ),
    (
        f"VIX 低的時候，NFP 日 SPY 大漲居多，上漲率接近七成（69.4%）。",
        f"VIX 低的時候，NFP 日 SPY 上漲居多，上漲率約 {low['pct_positive']:.0f}%（{low['pct_positive']:.1f}%）。",
    ),
    (
        "第一，NFP 日的波動幅度隨 VIX 體制幾乎線性遞增，從 0.50% 到 1.49%。每升一個 VIX 區間，波動大約加 0.3-0.5 個百分點。",
        f"第一，NFP 日的波動幅度隨 VIX 體制遞增，從 {low['mean_abs_return_pct']:.2f}% 到 "
        f"{high['mean_abs_return_pct']:.2f}%。每升一個 VIX 區間，波動大約加 0.25-0.4 個百分點。",
    ),
    (
        "第二，上漲機率的變化是非線性的。VIX 在 15-25 之間的三個區間，上漲率都在 60-70%，差異不大。但一旦 VIX 超過 25，上漲率直接跌到 25%。",
        f"第二，上漲機率的變化是非線性的。VIX 25 以下的三個區間，上漲率落在 "
        f"{elev['pct_positive']:.0f}-{low['pct_positive']:.0f}% 之間，隨 VIX 升高緩步下滑。"
        f"但一旦 VIX 超過 25，上漲率直接跌到 {high['pct_positive']:.0f}%。",
    ),
    (
        "整體而言，195 次 NFP 日，SPY 平均絕對波動 0.816%，比同期非 NFP 日的 0.713% 高出 14%，比普通週五的 0.701% 高出 16%。這個差異通過嚴格無母數檢定（p 達 0.00369），確實存在，不只是碰巧。",
        f"整體而言，{n} 次 NFP 日，SPY 平均絕對波動 {nfp_abs:.3f}%，比同期非 NFP 日的 {non_abs:.3f}% "
        f"高出 {(nfp_abs / non_abs - 1) * 100:.1f}%，比普通週五的 {fri_abs:.3f}% 高出 "
        f"{(nfp_abs / fri_abs - 1) * 100:.1f}%。\n\n"
        f"但這個差距**談不上統計顯著**。無母數 Wilcoxon 檢定給出 p={wilcoxon:.5f}，看起來很強；"
        f"參數 t 檢定則是 p={p_welch:.3f}（Welch）／{p_student:.3f}（Student），本來就貼著 5% 邊緣，"
        f"再對「vs 全體」與「vs 週五」兩個檢定做 Holm 多重比較校正後變成 p={holm_overall:.3f}，"
        f"沒有跨過 5% 門檻。方向站得住，顯著性站不住——這兩件事必須分開講。",
    ),
    (
        "問題在哪？NFP 日的波動幅度放大，但 59.5% 的 NFP 日 SPY 其實是收漲的。",
        f"問題在哪？NFP 日的波動幅度放大，但 {pct_pos:.1f}% 的 NFP 日 SPY 其實是收漲的。",
    ),
    (
        "還有一個不太被討論的細節：**68.7% 的 NFP 日，VIX 會在當天收跌**。",
        f"還有一個不太被討論的細節：**{vix_drops:.1f}% 的 NFP 日，VIX 會在當天收跌**。",
    ),
    (
        "不要把「NFP 日比較危險」當成一個常數。這個「危險」從 0.498% 到 1.488% 差了三倍，具體取決於公告前的 VIX 水準。",
        f"不要把「NFP 日比較危險」當成一個常數。這個「危險」從 {low['mean_abs_return_pct']:.3f}% 到 "
        f"{high['mean_abs_return_pct']:.3f}% 差了 {spread:.1f} 倍，具體取決於公告前的 VIX 水準。",
    ),
    (
        "在 VIX < 20 的環境下，NFP 日上漲率維持在六成以上，減倉並不划算。VIX 超過 25 的情況完全不同：上漲率跌到 25%",
        f"在 VIX < 20 的環境下，NFP 日上漲率仍在 {med['pct_positive']:.0f}% 以上，減倉並不划算。"
        f"VIX 超過 25 的情況完全不同：上漲率跌到 {high['pct_positive']:.0f}%",
    ),
    (
        "195 次非農公布日裡，有 62 次 VIX 低於 15。在那 62 次裡，NFP 日的 SPY 平均絕對波動只有 0.498%，比非 NFP 日整體的 0.713% 還要低。",
        f"{n} 次非農公布日裡，有 {low['n']} 次 VIX 低於 15。在那 {low['n']} 次裡，NFP 日的 SPY "
        f"平均絕對波動只有 {low['mean_abs_return_pct']:.3f}%，比非 NFP 日整體的 {non_abs:.3f}% 還要低。",
    ),
    # Parts C/D were not rerun on the official calendar. Say so where they appear.
    (
        "我們跑了三個策略的 2010-2026 回測（含 10 bps 交易成本）：",
        "我們跑了三個策略的 2010-2026 回測（含 10 bps 交易成本）。**注意：以下策略回測與下一段的 "
        "T±n 漂移數字，是在舊的替代日曆（每月第一個週五）下算的，2026-07 的官方日曆重跑只涵蓋"
        "波動率比較本身，沒有重跑策略部分**，因此這些數字僅供方向參考：",
    ),
    (
        "本文數字來自實驗 K741（`experiments/k741/k741_nfp_event_study_results.json`）。資料來源：yfinance（SPY, ^VIX），期間 2010-01-01 至 2026-03-28，共 195 次 NFP 事件 + 3,909 個非 NFP 交易日。",
        "本文波動率數字來自實驗 K741 **canonical 重跑**"
        "（`experiments/k741/k741_nfp_event_study_canonical_results.json`，2026-07-20），"
        "改用官方 BLS 發布日曆與 forward-only 交易日對應。資料來源：yfinance（SPY, ^VIX），"
        f"期間 2010-01-01 至 2026-03-30，共 {n} 次 NFP 事件 + {n_non:,} 個非 NFP 交易日。"
        "策略回測與事件前後漂移數字沿用舊日曆版本，尚未重跑。",
    ),
]

report = apply_article_correction(
    "mile_eda69bfb",
    content_replacements=R,
    summary=(
        "K741 canonical NFP rerun (official BLS calendar, forward-only mapping) supersedes "
        "every Part A/B number this article quoted from the archived proxy-calendar run: "
        f"n 195->{n}, non-NFP days 3909->{n_non}, NFP mean |ret| 0.816%->{nfp_abs:.3f}%, and all "
        "four VIX-regime cells (counts, means, pct-positive). Substantively the article's claim "
        "of statistical significance is WITHDRAWN: the archived text said the NFP-vs-all gap "
        "'確實存在，不只是碰巧' on a nonparametric p=0.00369; canonically the parametric test is "
        f"p={p_welch:.4f} Welch / {p_student:.4f} Student and Holm over the two overall comparisons "
        f"gives p={holm_overall:.4f}, so nothing clears 5% under any Holm family "
        "(k741_cert_merge_summary.json). Direction retained, significance not. The strategy "
        "backtest and T+-n drift figures (canonical Parts C/D, not rerun) are retained but now "
        "explicitly labelled as computed on the superseded proxy calendar. "
        "Task assign_759a28f3; AGENTS.md rule 13 retroactive correction."
    ),
    action="numbers_correction",
    storage_dir=str(ROOT / "storage"),
)
print(json.dumps(report, ensure_ascii=False, indent=2)[:1200])
