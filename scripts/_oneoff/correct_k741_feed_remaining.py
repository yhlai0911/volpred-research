"""Correct every still-published K741 proxy-calendar citation in the feed.

The canonical K741 rerun replaced the first-Friday proxy with the official BLS
release calendar, removed backward holiday mapping, and fixed the estimation
window.  It also withdrew the old significance and regime-mechanism claims:
no overall or regime result survives Holm correction under any reported family,
and the direct calm-vs-crisis bootstrap comparison includes zero.

All numbers below are formatted from the canonical result and certification
JSON files.  Every edit goes through ``apply_article_correction`` so the
canonical feed mutation, errata trail, Mirror projection, and Supabase
projection share one fail-loud gateway.

Run from the repository root:

    uv run python scripts/_oneoff/correct_k741_feed_remaining.py \
      --chart-url https://.../k904_chart3_nfp_by_vix_canonical.png
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from volpred.publisher.article_correction import apply_article_correction


ROOT = Path(__file__).resolve().parents[2]
CANON = ROOT / "experiments/k741/k741_nfp_event_study_canonical_results.json"
CERT = ROOT / "experiments/k741/k741_cert_merge_summary.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--chart-url",
        required=True,
        help="Uploaded public URL for k904_chart3_nfp_by_vix_canonical.png",
    )
    parser.add_argument("--storage-dir", default=str(ROOT / "storage"))
    parser.add_argument(
        "--descriptions-only",
        action="store_true",
        help="Repair stale card/SEO descriptions after an earlier body-only run.",
    )
    return parser


def main() -> None:
    args = _parser().parse_args()
    data = json.loads(CANON.read_text(encoding="utf-8"))
    cert = json.loads(CERT.read_text(encoding="utf-8"))
    pa = data["part_a_historical"]
    rb = data["part_b_vix_regimes"]
    regime_test = data["regime_difference_test"]
    low = rb["Low (VIX<15)"]
    med = rb["Medium (15-20)"]
    elev = rb["Elevated (20-25)"]
    high = rb["High (VIX>=25)"]

    n = pa["n_nfp"]
    n_non = pa["n_non_nfp"]
    nfp_abs = pa["nfp_mean_abs_return_pct"]
    non_abs = pa["non_nfp_mean_abs_return_pct"]
    ratio = pa["ratio_vs_all"]
    p_welch = pa["test_variants_vs_all"]["p_welch"]
    p_student = pa["test_variants_vs_all"]["p_student"]
    holm_overall = cert["holm_families_min_adjusted_p"]["overall_pair"]
    spread = high["mean_abs_return_pct"] / low["mean_abs_return_pct"]
    assert cert["anything_clears_5pct_under_any_family"] is False
    assert regime_test["ci_excludes_zero"] is False

    source_paths = [
        "experiments/k741/k741_nfp_event_study_canonical_results.json",
        "experiments/k741/k741_cert_merge_summary.json",
    ]
    summary = (
        "K741 official-calendar retroactive correction: replace first-Friday "
        f"proxy figures with n={n}, overall ratio={ratio:.3f}, and canonical "
        "VIX-regime cells. Withdraw the old robust-significance and proven-"
        "absorption claims: the overall pair has minimum Holm-adjusted "
        f"p={holm_overall:.3f}, no regime survives Holm, and the direct "
        f"calm-vs-crisis bootstrap comparison has p={regime_test['p_two_sided']:.3f} "
        "with a confidence interval containing zero. Archived strategy/drift "
        "results were not rerun and are no longer presented as canonical. "
        "Task assign_759a28f3; AGENTS.md rule 13 retroactive correction."
    )

    corrections = [
        {
            "article_id": "mile_eda69bfb",
            "title_replacement": (
                "VIX 體制決定一切：195 次非農公佈日，波動率差距達 3 倍",
                f"VIX 體制的描述性差異：{n} 次非農公佈日，波動幅度約差 {spread:.1f} 倍",
            ),
            "description_replacement": (
                "2010-2026 年 195 次非農公佈日，VIX 低於 15 時 SPY 平均波動 0.498%，VIX 高於 25 時達 1.488%，差距三倍。完全迴避 NFP 日的策略風險調整報酬低於 Buy & Hold。",
                f"官方 BLS 日曆下的 {n} 次 NFP：低 VIX 組平均絕對報酬 {low['mean_abs_return_pct']:.3f}%，高 VIX 組 {high['mean_abs_return_pct']:.3f}%。四個分組均未通過 Holm 校正，策略部分尚未用官方日曆重跑。",
            ),
            "content_replacements": [
                (
                    "非農就業報告（NFP）每個月第一個週五上午 8:30 公布，幾乎所有做美股的人都知道這天「比較危險」。",
                    "非農就業報告（NFP）依美國勞工統計局官方日曆發布，通常落在月初星期五，但並非固定為每月第一個星期五。許多美股投資人把發布日視為事件風險。",
                ),
                (
                    "差距 2.7 倍。同樣是非農公布日，恐慌程度不同，波動幅度根本不在同一個量級。",
                    f"絕對波動約差 {spread:.1f} 倍。同樣是非農公布日，VIX 高檔組本來就處於較大的市場震幅；這個比較尚未證明事件增量由 VIX 體制決定。",
                ),
                (
                    "VIX 低的時候，NFP 日 SPY 上漲居多，上漲率約 71%（71.4%）。VIX 高的時候，完全翻轉——只有 25.0% 的 NFP 日是收漲的。換個說法：VIX 超過 25 的環境下，非農公布日三次裡有兩次以上是下跌的。\n\n**VIX 高的時候，市場早就站在高度警戒的位置，任何一個不夠強的數字都會成為賣壓的觸發點。** 非農數字本身只是觸發，底層的壓力來自 VIX 已經定價的恐慌。",
                    f"低 VIX 組有 {low['n']} 次事件，{low['pct_positive']:.1f}% 收漲；高 VIX 組只有 {high['n']} 次，{high['pct_positive']:.1f}% 收漲。兩個比例是樣本描述，尚未做足以支持方向預測的組間檢定。\n\n市場先買保護、先降槓桿，可能壓低事件新增衝擊；K741 沒有證實這條機制。高 VIX 組樣本少，不能把觀察到的方向比例寫成穩定觸發規則。",
                ),
                (
                    "![NFP 公佈日絕對報酬與上漲機率 × VIX 體制](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/K741_vix_regime_nfp_chart.png)",
                    f"![官方 BLS 日曆下的 NFP 相對波動分組]({args.chart_url})",
                ),
                (
                    "第二，上漲機率的變化是非線性的。VIX 25 以下的三個區間，上漲率落在 56-71% 之間，隨 VIX 升高緩步下滑。但一旦 VIX 超過 25，上漲率直接跌到 25%。這個斷點暗示：**「恐慌體制」是一個質變，不只是量變**。",
                    f"第二，上漲比例在四組依序為 {low['pct_positive']:.1f}%、{med['pct_positive']:.1f}%、{elev['pct_positive']:.1f}%、{high['pct_positive']:.1f}%。高 VIX 組只有 {high['n']} 次事件；現有結果沒有證實 25 是方向機率的斷點。",
                ),
                (
                    "但這個差距**談不上統計顯著**。無母數 Wilcoxon 檢定給出 p=0.00064，看起來很強；參數 t 檢定則是 p=0.039（Welch）／0.051（Student），本來就貼著 5% 邊緣，再對「vs 全體」與「vs 週五」兩個檢定做 Holm 多重比較校正後變成 p=0.072，沒有跨過 5% 門檻。方向站得住，顯著性站不住——這兩件事必須分開講。",
                    f"但這個差距**談不上統計顯著**。無母數 Wilcoxon 檢定給出 p={pa['wilcoxon_p_vs_all']:.5f}；參數 t 檢定是 p={p_welch:.3f}（Welch）／{p_student:.3f}（Student），再對「vs 全體」與「vs 週五」兩個檢定做 Holm 校正後為 p={holm_overall:.3f}，沒有跨過 5% 門檻。四個 VIX 分組也無一通過 Holm 校正，描述方向仍有很大不確定性。",
                ),
                (
                    "## 那事先避開 NFP 日划算嗎？\n\n看完波動率的數字，很多人第一個反應是：既然 NFP 日波動較大，那我提前出場，等公告後再回來，應該可以規避風險。\n\n這個邏輯聽起來合理，但數字說的不是這樣。\n\n我們跑了三個策略的 2010-2026 回測（含 10 bps 交易成本）。**注意：以下策略回測與下一段的 T±n 漂移數字，是在舊的替代日曆（每月第一個週五）下算的，2026-07 的官方日曆重跑只涵蓋波動率比較本身，沒有重跑策略部分**，因此這些數字僅供方向參考：\n\n| 策略 | 年化報酬 | 風險調整報酬 | 最大回撤 |\n|------|---------|------------|---------|\n| Buy & Hold | 13.97% | 0.816 | -33.7% |\n| VIX<20 才減半持倉 | 13.29% | 0.780 | -33.7% |\n| 完全跳過 NFP 日 | 11.896% | 0.720 | -28.2% |\n\n![NFP 迴避策略 vs Buy & Hold 比較](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/K741_strategy_comparison_chart.png)\n\n「完全跳過 NFP 日」確實把最大回撤從 33.7% 壓到 28.2%，但代價是年化報酬從 13.97% 降到 11.896%，風險調整報酬從 0.816 掉到 0.720。\n\n問題在哪？NFP 日的波動幅度放大，但 57.2% 的 NFP 日 SPY 其實是收漲的。避開 NFP 日，上漲和下跌一起避掉，然後還多付兩次交易成本。\n\nNFP 日貢獻了全樣本報酬的 7.4%。每年只有 12 個 NFP 日，卻佔了不成比例的報酬份額。這些日子的波動大，但帶來的不全是損失。",
                    "## 那事先避開 NFP 日划算嗎？\n\ncanonical 重跑只涵蓋波動比較，沒有重跑策略、產業分散或事件前後漂移。舊版「完全跳過 NFP」與條件減倉回測使用 first-Friday 替代日曆，不能繼續作為官方日曆下的策略證據。\n\n目前能確認的是 NFP 日平均絕對報酬較高，但 multiplicity 校正後未達 5% 門檻。是否值得提前出場，需要用官方日期重跑同一套 lag、成本與基準；在那之前，本篇撤回相關 Sharpe、最大回撤與報酬貢獻結論。",
                ),
                (
                    "## 隔日效應：VIX 在 NFP 日通常下跌\n\n還有一個不太被討論的細節：**66.0% 的 NFP 日，VIX 會在當天收跌**。\n\n非農公布前，市場對數字有很大的不確定性，這個不確定性定價在 VIX 裡。數字一出來，不管好壞，不確定性本身消失了，VIX 自然回落。\n\n盤後漂移也有一個值得注意的數字：NFP 公布後五天（T+1 到 T+5）的累積報酬平均 +0.36%，達統計顯著水準。\n\n這個正向漂移暗示：事件過後，市場傾向繼續往高走，而不是立刻翻轉。\n\nNFP 前兩天（T-2）同樣出現平均 +0.20%，也達統計顯著水準。那是「暖身效應」，跟公告後的動能方向相同，機制卻不同。",
                    f"## 發布日的 VIX 描述\n\ncanonical Part A 顯示 **{pa['vix_drops_pct']:.1f}% 的 NFP 日，VIX 當天收跌**。單一比例沒有檢定事件前後機制，也不能推出 VIX 部位的交易方向。\n\nT−2、T+1 到 T+5 的漂移統計沒有使用官方日曆重跑；原文的顯著性與「暖身效應」解釋已撤回。",
                ),
                (
                    "## 這些數字對你實際上有什麼用？\n\n幾個可以馬上套用的判斷框架：\n\n**1. NFP 日不是均等的風險**\n\n不要把「NFP 日比較危險」當成一個常數。這個「危險」從 0.527% 到 1.417% 差了 2.7 倍，具體取決於公告前的 VIX 水準。VIX 低的時候，NFP 日其實和普通週五沒有太大差別。\n\n**2. VIX 超過 25 才是真正的警戒信號**\n\n在 VIX < 20 的環境下，NFP 日上漲率仍在 58% 以上，減倉並不划算。VIX 超過 25 的情況完全不同：上漲率跌到 25%，這時候減倉才有防禦意義，雖然仍不建議完全出場。\n\n**3. 「避開 NFP 日」這個策略全面回測下劣於 Buy & Hold**\n\n16 年的數據（含兩次市場黑天鵝）都顯示，完全跳過 NFP 日的策略風險調整報酬從 0.816 跌到 0.720、年化報酬從 13.97% 降到 11.896%。交易成本加上錯過的上漲日，讓這個「聽起來保守」的做法實際上更虧。\n\n**4. 不確定性定價一旦消除，VIX 傾向下跌**\n\n如果你對 VIX 相關部位有操作需求，NFP 公布後 VIX 下跌的機率接近七成，這個方向性偏誤是有歷史數據支撐的。",
                    f"## 這些數字對你實際上有什麼用？\n\n**1. 用 VIX 估震幅，不用分組勝率猜方向。** NFP 日平均絕對報酬從低 VIX 組的 {low['mean_abs_return_pct']:.3f}% 到高 VIX 組的 {high['mean_abs_return_pct']:.3f}%，可作風險預算尺度。\n\n**2. 把事件增量和市場底噪分開。** 四個「NFP 日相對同體制平日」比值沒有通過 Holm 校正；高 VIX 組比值低於 1，也不能證明 VIX 25 是策略斷點。\n\n**3. 等官方日曆策略重跑。** 舊回測與漂移數字已撤回。完成同一 lag、成本與基準的 canonical 回測前，不提供機械式減倉或持有建議。",
                ),
                (
                    "「非農日恐慌」很大程度上是一個情境依賴的效應。背景環境——也就是市場已定價的恐慌——才是主要變數，非農數字本身反而是次要的。",
                    f"背景環境會改變絕對震幅；K741 尚未證明它會改變 NFP 的增量衝擊。低、高 VIX 比值的直接差異顯著性為 {regime_test['p_two_sided']:.3f}，95% bootstrap 區間包含零。",
                ),
            ],
            "details_patch": {
                "source_experiment_paths": source_paths,
            },
        },
        {
            "article_id": "mile_d721672b",
            "title_replacement": (
                "VIX 超過 30 了！你該恐慌嗎？195 次非農數據告訴你答案",
                f"VIX 超過 30 了！你該恐慌嗎？{n} 次非農數據重新算給你看",
            ),
            "description_replacement": (
                "[提出: Claude, 執行: Claude] 摘要 四月三日，全球最重要的經濟數據「非農就業報告（NFP）」即將公布。恐慌中的你或許正在考慮：要不要先出場避風頭？我們分析了 2010 年以來 195 次非農事件的數據，得出一個違反直覺的結論：當 VIX 已超過 25，非農的衝擊力幾乎消失了。 --- 想像一個場景 週四深夜，你盯著螢幕，VIX 顯示 30，新聞標題寫著「市場在等非農數據，高度警戒」。你心想：萬一明天數據出包，我是不是應該先跑？ 這個直覺，其實是錯的。 --- 195 次數據告訴你：恐慌已經被「預消化」了 我們的研究（K741）分析了 2010 至 2026 年間所有的非農發…",
                f"官方 BLS 日曆重跑涵蓋 {n} 次 NFP。高 VIX 組的絕對震幅較大，但相對同體制平日的增量未通過多重比較校正；直接組間 bootstrap 區間也包含零。VIX 提供風險尺度，無法單靠 K741 判斷事件方向。",
            ),
            "content_replacements": [
                (
                    "四月三日，全球最重要的經濟數據「非農就業報告（NFP）」即將公布。恐慌中的你或許正在考慮：要不要先出場避風頭？我們分析了 2010 年以來 195 次非農事件的數據，得出一個違反直覺的結論：**當 VIX 已超過 25，非農的衝擊力幾乎消失了。**",
                    f"四月三日，全球最重要的經濟數據「非農就業報告（NFP）」即將公布。當時的文章用替代日曆分析 195 次事件；官方 BLS 日曆重跑後，樣本是 {n} 次。新版證據顯示：VIX 高檔時，NFP 日的絕對波動較大，但相對同體制平日的增量沒有通過多重比較校正。**資料不支持「高 VIX 會讓非農衝擊消失」這個強結論。**",
                ),
                (
                    "這個直覺，其實是錯的。",
                    "先把問題拆開：VIX 高代表市場本來就很震；NFP 是否再增加一層風險，則要另外比較。",
                ),
                (
                    "## 195 次數據告訴你：恐慌已經被「預消化」了",
                    f"## {n} 次官方發布日：方向存在，顯著性不足",
                ),
                (
                    "我們的研究（K741）分析了 2010 至 2026 年間所有的非農發布日，共 195 個交易日。",
                    f"K741 canonical 版採官方 BLS 發布日曆、只向前對應交易日，分析 2010 至 2026 年共 {n} 個 NFP 交易日。",
                ),
                (
                    "**整體來看**，非農日的 SPY 平均波動幅度是 0.82%，比正常日的 0.71% 高了 15%（1.14 倍）。確實，非農日比較「有感」。",
                    f"**整體來看**，非農日的 SPY 平均絕對報酬是 {nfp_abs:.3f}%，非 NFP 日是 {non_abs:.3f}%，比值 {ratio:.3f}。原始 Welch 檢定的顯著性為 {p_welch:.3f}，Student 版本為 {p_student:.3f}；把兩個 overall 比較一起做 Holm 校正後，最小值是 {holm_overall:.3f}，未跨過 5% 門檻。",
                ),
                (
                    "**但是，VIX 水位完全改變了這個結論。**",
                    "**分組數字呈現梯度，但四組都沒有通過 Holm 校正。**",
                ),
                (
                    "![當 VIX 越高，非農對市場的衝擊反而越小](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/nfp_vix_regime_impact_7e7f45.png)\n\n*圖表：195 次非農事件按 VIX 情緒水位分組，分析當日 SPY 波動率倍數。數據來源：yfinance，2010-2026。*",
                    f"![官方 BLS 日曆下的 NFP 相對波動分組]({args.chart_url})\n\n*圖表：K904 canonical 的獨立交叉核對。四個分組的原始檢定均未通過多重比較校正，組間差異也尚未被證實。資料來源：官方 BLS 日曆、SPY 與 VIX pinned snapshot，2010-2026。*",
                ),
                (
                    "| VIX 水位 | 代表情緒 | 非農衝擊倍數 |\n|----|---|------|\n| < 15 | 冷靜 | **1.23 倍** |\n| 15–20 | 正常 | **1.18 倍** |\n| 20–25 | 偏高 | **1.17 倍** |\n| **≥ 25** | **恐慌** | **0.98 倍（消失！）** |",
                    "| VIX 水位 | NFP 日平均絕對報酬 | 相對同體制平日 | Holm 校正後顯著性 |\n|----|---:|---:|---:|\n"
                    f"| < 15 | {low['mean_abs_return_pct']:.3f}% | {low['ratio']:.3f} 倍 | {low['p_value_holm']:.3f} |\n"
                    f"| 15–20 | {med['mean_abs_return_pct']:.3f}% | {med['ratio']:.3f} 倍 | {med['p_value_holm']:.3f} |\n"
                    f"| 20–25 | {elev['mean_abs_return_pct']:.3f}% | {elev['ratio']:.3f} 倍 | {elev['p_value_holm']:.3f} |\n"
                    f"| ≥ 25 | {high['mean_abs_return_pct']:.3f}% | {high['ratio']:.3f} 倍 | {high['p_value_holm']:.3f} |",
                ),
                (
                    "你沒看錯。當 VIX 超過 25 時，非農日的衝擊倍數降到了 0.98——幾乎等於一個普通的星期五。統計上，在高 VIX 環境下，非農日與正常日的波動差距**完全不顯著**（p=0.93）。",
                    f"高 VIX 組的相對比值是 {high['ratio']:.3f}，代表 NFP 日沒有高於同體制平日；該組原始顯著性為 {high['p_value']:.3f}。低 VIX 與高 VIX 比值的直接 bootstrap 差異是 {regime_test['observed_difference']:.3f}，95% 區間從 {regime_test['ci95'][0]:.3f} 到 {regime_test['ci95'][1]:.3f}，包含零。現有樣本只能支持描述性梯度。",
                ),
                (
                    "## 為什麼會這樣？「恐慌預消化」機制\n\n想像你的腸胃已經非常不舒服了（VIX = 30），再吃一個辣椒（非農），感覺反而沒那麼刺激，因為你的身體已經「習慣」了高度緊張的狀態。\n\n市場也是一樣。\n\n當 VIX 已經衝上 25 以上，市場本身已經「充分定價」了不確定性。每個交易員都知道現在是高風險時期，每個人都已經調低了部位或買了保護。這時候，非農數據本身的衝擊，反而被這種「集體防禦姿態」給吸收掉了。\n\n這個現象，我們在另一項研究（K716、K721）中也得到了驗證：當市場整體波動率越高，每一單位新的衝擊產生的邊際效果越小。這就是「波動率吸收假說」，恐慌越深，市場對新衝擊越麻木。",
                    "## 「恐慌預消化」目前仍是待驗機制\n\n市場先買保護、先降槓桿，理論上可能壓低事件新增的衝擊。K741 的分組比值符合這個方向，卻沒有證實組間差異。高 VIX 組只有 28 個 NFP 日，bootstrap 區間很寬；樣本不足時，不能把「沒有顯著增量」改寫成「衝擊已消失」。K716、K721 提供相關背景，仍無法替代 K741 的直接組間檢定。",
                ),
                (
                    "## 04/03 非農：你應該怎麼做？\n\n目前 VIX 約 30，屬於「高 VIX」情緒區間。根據歷史數據：\n\n- **預期衝擊倍數**：0.98 倍（幾乎等同正常日）\n- **歷史上同級別 NFP 日**：平均波動幅度約 1.56%\n- **方向偏向**：66.7% 的高 VIX 非農日 SPY 收正（牛市傾向）\n\n更重要的是：**若你在非農前出場，歷史數據顯示你反而會錯過報酬。** 研究發現，跳過非農日的策略，長期 Sharpe 從 0.82 降到 0.72——因為非農日平均有 59.5% 的機率收漲，貢獻了全年 7.4% 的報酬，卻只佔 4.8% 的交易日。",
                    f"## 04/03 非農：證據能支持到哪裡？\n\n當時 VIX 約 30，高 VIX 組的 canonical 描述是：NFP 日平均絕對報酬 {high['mean_abs_return_pct']:.3f}%，相對同體制平日為 {high['ratio']:.3f} 倍，{high['pct_positive']:.1f}% 收漲。只有 28 個事件，方向與機制都不能當成預測。\n\n舊版替代日曆曾回測「跳過 NFP」策略，但 canonical 重跑只涵蓋波動比較，沒有重跑策略與事件前後漂移。舊 Sharpe、報酬貢獻與交易建議因此不再作為現行證據。",
                ),
                (
                    "## 非農前後的「漂移效應」\n\n還有一個有趣的發現：\n\n- **非農前兩天（T-2）**：SPY 平均上漲 +0.20%（p=0.009），市場在等待數據前，傾向先漲\n- **非農後五天**：SPY 平均累積 +0.36%（p=0.029），不確定性消除後，市場繼續上行\n\nVIX 在非農日平均下跌，高達 68.7% 的非農日 VIX 是下降的，「事後鬆一口氣」效應非常顯著。",
                    f"## 事件前後漂移仍待官方日曆重跑\n\ncanonical 重跑沒有涵蓋 T−2、T+5 或策略部分，因此原文的漂移顯著性已撤回。已驗證的 Part A 數字只有：{pa['pct_positive']:.1f}% 的 NFP 日 SPY 收漲，{pa['vix_drops_pct']:.1f}% 的 NFP 日 VIX 收跌；兩個比例都不能單獨證明可交易漂移。",
                ),
                (
                    "## 一句話結論\n\n**VIX 越高，非農越沒什麼好怕的。**\n\n當恐慌已經在市場裡彌漫，新的壞消息（或好消息）都難以改變局面，因為大家早已做好心理準備。目前 VIX~30 的環境下，04/03 非農不需要特別操作。繼續持有，讓數據過去，歷史對你有利。\n\n---\n\n## 行動建議\n\n如果你持有 SPY 或相關 ETF：\n- **不需要在 04/02 出場避險**\n- **正常持倉**，等待非農日自然過去\n- 若 VIX 在非農後快速下降（通常會），這是很好的「恐慌解除」信號",
                    "## 一句話結論\n\n**VIX 告訴你市場本來有多震，無法單靠 K741 判定 NFP 會往哪裡走。**\n\n部位大小應由可承受損失與既定風險預算決定。官方日曆重跑沒有證明高 VIX 會消除 NFP 衝擊，也沒有重跑事件日進出策略；本篇不再提供機械式持有或退場指令。",
                ),
                (
                    "*本文基於實驗 K741（195 次 NFP 事件分析，腳本：experiments/k741_nfp_event_study_comprehensive.py）。數據來源：yfinance（SPY、VIX），期間：2010-2026。Codex 審查已確認核心波動率吸收結論（K741-review）。注意：NFP 日期識別對特殊假日約有 5-10 個偏差，不影響整體結論方向。*",
                    f"*更正後依據：K741 canonical（`experiments/k741/k741_nfp_event_study_canonical_results.json`）與認證摘要（`experiments/k741/k741_cert_merge_summary.json`）。官方 BLS 日曆、forward-only 交易日對應；期間 2010-01-01 至 2026-03-30，{n} 次 NFP、{n_non:,} 個非 NFP 交易日。四個 regime 均未通過 Holm 校正，直接組間差異也未達顯著。*",
                ),
            ],
            "details_patch": {
                "experiment_refs": ["K741"],
                "source_experiment_paths": source_paths,
            },
        },
        {
            "article_id": "mile_630d0010",
            "title_replacement": (
                "非農數據來了！但 VIX 已經幫你消化恐慌——04/03 NFP 投資指南",
                "非農數據來了：VIX 24 提供震幅尺度，不替你做買賣決定",
            ),
            "description_replacement": (
                "[提出: Claude, 執行: Claude] 摘要 四月三日，美國勞工部將公布最新的非農就業人數（NFP）。每個月這個時刻，市場都會屏息以待，但我們的研究告訴你：當 VIX 已經偏高，你根本不需要緊張。 目前 VIX 約 24，NFP 的衝擊力已被市場「預先消化」，現在最好的策略，是按兵不動。 --- 「非農數據」是什麼？為什麼大家這麼緊張？ 每個月第一個星期五，美國政府會公布上個月「新增了多少非農業就業人數」，俗稱 NFP（Non-Farm Payrolls）。 這個數字為什麼重要？想像美國經濟是一台引擎，而「有多少人在工作」就是引擎的油表。就業人數多 → 消費旺盛 → 通膨壓力 → 聯…",
                f"K741 依官方 BLS 日曆重跑 {n} 次 NFP。VIX 20-25 組的平均絕對報酬為 {elev['mean_abs_return_pct']:.3f}%，相對同體制平日 {elev['ratio']:.3f} 倍，但 Holm 校正後未達顯著。VIX 提供震幅尺度，不替投資人做買賣決定。",
            ),
            "content_replacements": [
                (
                    "四月三日，美國勞工部將公布最新的非農就業人數（NFP）。每個月這個時刻，市場都會屏息以待，但我們的研究告訴你：**當 VIX 已經偏高，你根本不需要緊張。** 目前 VIX 約 24，NFP 的衝擊力已被市場「預先消化」，現在最好的策略，是按兵不動。",
                    "四月三日，美國勞工部將公布最新的非農就業人數（NFP）。原文把高 VIX 直接解讀成「衝擊已被消化」；官方日曆重跑後，分組梯度只剩描述性證據。**VIX 約 24 說明市場本來就比較震，無法單靠這個水位推出 NFP 不必防備或應該按兵不動。**",
                ),
                (
                    "![NFP 衝擊力 vs VIX 水準：當 VIX 偏高，非農數據的市場衝擊幾乎消失（195 次事件，2010-2026）](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/bar_chart_aea2d3.png)",
                    f"![官方 BLS 日曆下的 NFP 相對波動分組]({args.chart_url})",
                ),
                (
                    "每個月第一個星期五，美國政府會公布上個月「新增了多少非農業就業人數」，俗稱 NFP（Non-Farm Payrolls）。",
                    "美國勞工統計局依官方發布日曆公布「就業情勢」報告，通常落在月初星期五，但並非固定為每月第一個星期五。報告中的非農就業人數俗稱 NFP（Non-Farm Payrolls）。",
                ),
                (
                    "VIX 偏高（>20），代表市場已經知道風險來了，已經把保險買好、部位調輕。此時 NFP 再有驚喜，衝擊的「額外」能量已大幅減少，因為市場早就準備好了。",
                    "VIX 偏高（>20）代表選擇權市場對未來波動的定價較高。市場是否已經買足保護、NFP 還會不會增加額外震盪，需要事件日與同體制平日的直接比較；VIX 水位本身不能替代檢定。",
                ),
                (
                    "## 數據說話：195 次 NFP，VIX 高時衝擊消失\n\n我們分析了 2010 年到 2026 年間共 **195 次 NFP 事件**的市場數據（數據來源：yfinance），比較 NFP 當天與一般交易日的波動率差異：\n\n| VIX 水準 | 代表狀態 | NFP 衝擊力（比值） |\n|----|---|-----------|\n| VIX < 15 | 低恐慌、市場平靜 | **1.23x**（顯著放大） |\n| VIX 15-20 | 正常水準 | **1.18x**（略有放大） |\n| VIX 20-25 | 偏高、市場已戒備 | **1.17x**（微弱） |\n| VIX ≥ 25 | 高恐慌、市場已消化 | **0.98x**（幾乎消失）|\n\n**「比值」的意思**：1.23x 代表 NFP 當天的波動是一般日的 1.23 倍；0.98x 代表幾乎一樣，NFP 效果消失。\n\n結論很清楚：**VIX 越高，NFP 的額外衝擊力越弱。** 當 VIX ≥ 25，兩者幾乎沒有差別。",
                    f"## 官方日曆重跑：{n} 次 NFP，分組梯度尚未通過校正\n\nK741 canonical 比較 2010 年到 2026 年共 **{n} 次官方 NFP 發布日**與同體制一般交易日：\n\n"
                    "| VIX 水準 | NFP 日平均絕對報酬 | 相對同體制平日 | Holm 校正後顯著性 |\n|----|---:|---:|---:|\n"
                    f"| VIX < 15 | {low['mean_abs_return_pct']:.3f}% | {low['ratio']:.3f} 倍 | {low['p_value_holm']:.3f} |\n"
                    f"| VIX 15-20 | {med['mean_abs_return_pct']:.3f}% | {med['ratio']:.3f} 倍 | {med['p_value_holm']:.3f} |\n"
                    f"| VIX 20-25 | {elev['mean_abs_return_pct']:.3f}% | {elev['ratio']:.3f} 倍 | {elev['p_value_holm']:.3f} |\n"
                    f"| VIX ≥ 25 | {high['mean_abs_return_pct']:.3f}% | {high['ratio']:.3f} 倍 | {high['p_value_holm']:.3f} |\n\n"
                    f"四個比值依序下降，但沒有一組通過 Holm 校正。低、高 VIX 的直接比值差為 {regime_test['observed_difference']:.3f}，95% bootstrap 區間包含零，顯著性為 {regime_test['p_two_sided']:.3f}。目前只能把梯度當成待驗線索。",
                ),
                (
                    "## 那麼今天的 VIX~24 代表什麼？\n\n目前 VIX 約 24，正好落在「偏高」區間（VIX 20-25）。這代表：\n\n- 市場已知有風險，多數大戶已降低槓桿、補好保險\n- NFP 就算出現驚喜數字，能造成的「額外震盪」已大幅縮水\n- 根據歷史，這個 VIX 水準的 NFP 衝擊比值只有 **1.17x**——幾乎跟一般日無異\n\n更重要的是：**我們的研究還發現，跳過 NFP 當天（提前逃跑）的策略，長期 Sharpe 比率反而更差（0.72 vs 0.82）。**\n\n換句話說，為了躲 NFP 而減倉的人，不只沒賺到保護，還犧牲了長期報酬。",
                    f"## 那麼今天的 VIX~24 代表什麼？\n\nVIX 約 24 落在 20-25 分組。canonical 樣本中，該組 NFP 日平均絕對報酬為 {elev['mean_abs_return_pct']:.3f}%，相對同體制平日為 {elev['ratio']:.3f} 倍，Holm 校正後未達顯著。數字可用來估計可能的震幅，不能用來判斷方向。\n\n舊文引用的事件日進出策略來自 first-Friday 替代日曆，canonical 重跑沒有涵蓋策略部分。Sharpe 0.72 與 0.82 不再作為現行建議的依據。",
                ),
                (
                    "## 04/03 NFP 預測：你需要知道的數字\n\n根據 K741 研究的歷史規律，04/03 NFP 當天：\n\n- 預期市場移動幅度：約 **1.0%**（上下皆有可能）\n- 歷史上正向走勢的機率：**66.7%**（三次中有兩次是漲）\n- 目前 VIX~24，衝擊力偏低\n\n這不是預測「一定會漲」，而是說：**這次 NFP 的整體風險，比你想像的小得多。**",
                    f"## 04/03 NFP：可用的歷史尺度\n\n20-25 分組只有 {elev['n']} 個 NFP 日，平均絕對報酬 {elev['mean_abs_return_pct']:.3f}%，{elev['pct_positive']:.1f}% 收漲。樣本與不確定區間都不足以支持單日方向預測，也不能宣稱風險一定偏低。",
                ),
                (
                    "## 投資人應該怎麼做？\n\n**結論：不用在 NFP 前減倉。**\n\n具體建議：\n\n1. **持有不動**：如果你已有分散配置（例如 SPY+GLD 50/50），就保持現狀，不要在消息公布前追漲殺跌\n2. **不要加碼賭方向**：雖然正向機率偏高，但 1% 移動空間有限，交易成本可能吃掉大部分\n3. **看懂 VIX 的意義**：VIX 偏高不是「現在很危險，快跑」，反而是「市場已準備好，衝擊有限」\n4. **事後觀察即可**：NFP 公布後，如果數字極端（大幅超出或低於預期），再評估是否需要調整\n\n---\n\n## 一句話總結\n\n**當 VIX 已經偏高，市場早就把 NFP 的恐慌「預先消化」了，現在最好的策略，是按兵不動，讓時間幫你工作。**",
                    "## 投資人應該怎麼做？\n\nK741 canonical 回答的是波動描述，沒有驗證買賣策略。較穩妥的做法是沿用事前寫好的風險預算：確認單日損失是否可承受、避免用分組勝率下注方向、等事件後再依新資訊調整。需要減倉與否，取決於部位集中度和損失上限，不能由 VIX 分組單獨決定。\n\n---\n\n## 一句話總結\n\n**VIX 約 24 提供震幅尺度，沒有替投資人做出持有或減倉決定。**",
                ),
                (
                    "*本文基於實驗 K741 的實證結果（195 次 NFP 事件，數據來源：yfinance，期間：2010-2026）。研究方法：比較 NFP 當日與非事件日的波動率差異，按 VIX 水準分組，及策略回測比較（跳過 NFP vs 持有不動）。*",
                    f"*更正後依據：K741 canonical（官方 BLS 日曆、forward-only 對應），期間 2010-01-01 至 2026-03-30，{n} 次 NFP、{n_non:,} 個非 NFP 交易日。結果檔：`experiments/k741/k741_nfp_event_study_canonical_results.json`；認證：`experiments/k741/k741_cert_merge_summary.json`。策略回測未在 canonical scope 內。*",
                ),
            ],
            "details_patch": {
                "experiment_refs": ["K741"],
                "source_experiment_paths": source_paths,
            },
        },
        {
            "article_id": "mile_44fb4b90",
            "description_replacement": (
                "分析195次非農就業數據（2010–2026）：非農日波動1.17x，但VIX≥25時效果消失（比值0.95）。非農前VIX無系統性上升；非農後65.5%機率VIX當天下跌。VIX 27環境下建議：使用12/VIX策略者不需要做任何調整，月初正常rebalance即可。",
                f"官方 BLS 日曆下共 {n} 次 NFP，整體平均絕對報酬 {nfp_abs:.3f}%，相對非 NFP 日 {ratio:.3f} 倍；多重比較校正後未達 5%。高 VIX 組的描述不能證明事件效果消失，策略與事件前後視窗仍待官方日曆重跑。",
            ),
            "content_replacements": [
                (
                    "下週五（4 月 4 日）是本月非農就業數據（NFP）的公布日。",
                    "原文所指的非農就業數據（NFP）發布日是 4 月 3 日（週五）；4 月 4 日是日期誤植。",
                ),
                (
                    "我們用 16 年的歷史數據（195 次非農公布，SPY 2010–2026）做了一個完整分析（K661）。結論可能出乎你意料：**現在 VIX 27 的情況下，你其實不太需要做額外準備。**",
                    f"原文引用的 K661 使用 first-Friday 替代日曆。官方 BLS 日曆的 K741 canonical 重跑涵蓋 {n} 次發布日；結果只能描述風險尺度，**無法推出 VIX 27 時不需要額外準備。**",
                ),
                (
                    "首先，非農日確實是個波動放大的日子。整體來看，SPY 在非農發布當天的平均絕對報酬是 **0.83%**，比非 NFP 日的 **0.71%** 高出約 **17%**（波動率比值 1.17，Mann-Whitney p=0.003）。\n\n這不是大數字，但確實顯著。16 年 195 次，非農日就是比一般日子動盪一點。",
                    f"整體來看，SPY 在官方 NFP 發布日的平均絕對報酬是 **{nfp_abs:.3f}%**，非 NFP 日是 **{non_abs:.3f}%**，比值 **{ratio:.3f}**。原始 Welch 顯著性為 {p_welch:.3f}，Student 版本為 {p_student:.3f}；兩個 overall 比較做 Holm 校正後最小為 {holm_overall:.3f}。16 年 {n} 次事件支持波動較大的描述，沒有提供穩健的 5% 顯著性結論。",
                ),
                (
                    "## 但 VIX 高時這個規律消失了\n\n這是最關鍵的發現。\n\n![非農日 vs 平日波動率比值（依 VIX 分組）](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/k661_nfp_vol_ratio_by_vix_f9a0a9.png)\n\n**當 VIX ≥ 25 時，非農日波動率比值降到 0.95——低於 1.0。**\n\n| VIX 區間 | 非農日波動率 | 平日波動率 | 比值 |\n|---|------|----|-----|\n| VIX < 15 | 0.50% | 0.40% | 1.24 |\n| 15 ≤ VIX < 20 | 0.78% | 0.61% | 1.30 |\n| 20 ≤ VIX < 25 | 1.05% | 0.89% | 1.18 |\n| **VIX ≥ 25** | **1.52%** | **1.60%** | **0.95** |\n\n換句話說：在平靜市場（VIX < 15），非農日確實更震盪（1.24x）；但在已經很動盪的市場（VIX ≥ 25），非農日反而跟平日差不多，甚至更安靜一些。\n\n**為什麼？** 因為 VIX 已經夠高了，市場已經在「恐慌模式」。不確定性已經被 price in，任何數據公布只是提供一個方向性的解答，而不是增加更多不確定性。",
                    f"## VIX 分組呈現梯度，組間差異尚未證實\n\n![官方 BLS 日曆下的 NFP 相對波動分組]({args.chart_url})\n\n"
                    "| VIX 區間 | NFP 日平均絕對報酬 | 同體制平日 | 比值 | Holm 校正後顯著性 |\n|---|---:|---:|---:|---:|\n"
                    f"| VIX < 15 | {low['mean_abs_return_pct']:.3f}% | {low['non_nfp_mean_abs_return_pct']:.3f}% | {low['ratio']:.3f} | {low['p_value_holm']:.3f} |\n"
                    f"| 15 ≤ VIX < 20 | {med['mean_abs_return_pct']:.3f}% | {med['non_nfp_mean_abs_return_pct']:.3f}% | {med['ratio']:.3f} | {med['p_value_holm']:.3f} |\n"
                    f"| 20 ≤ VIX < 25 | {elev['mean_abs_return_pct']:.3f}% | {elev['non_nfp_mean_abs_return_pct']:.3f}% | {elev['ratio']:.3f} | {elev['p_value_holm']:.3f} |\n"
                    f"| VIX ≥ 25 | {high['mean_abs_return_pct']:.3f}% | {high['non_nfp_mean_abs_return_pct']:.3f}% | {high['ratio']:.3f} | {high['p_value_holm']:.3f} |\n\n"
                    f"高 VIX 組的比值低於 1，四個分組卻都沒有通過 Holm 校正。低、高 VIX 的直接差異檢定顯著性為 {regime_test['p_two_sided']:.3f}，信賴區間包含零。「預先定價」可以當解釋假說，不能寫成已證實機制。",
                ),
                (
                    "## 非農前：VIX 幾乎沒有系統性上升",
                    "## 非農前後統計仍待官方日曆重跑",
                ),
                (
                    "很多人相信非農前幾天 VIX 會慢慢爬升，就像考試前的「備考焦慮」。\n\n數據不支持這個印象。\n\n我們分析了非農前 T-5 到 T-1 的 VIX 變動：",
                    "以下 T−5 到 T−1 與發布後 VIX 統計來自舊 K661 替代日曆。K741 canonical 只重跑 Part A/B，沒有重新估計事件前後視窗；表格保留為歷史紀錄，不再作為現行推論：",
                ),
                (
                    "唯一顯著的其實是 **T-2（非農前兩天 VIX 平均下降 0.30 點）**——和大家預期的「備考焦慮」方向相反。整體累積 VIX 變動（T-5 到 T-1）均值只有 +0.13 點，t=0.57，完全不顯著。",
                    "舊版 T−2 結果與整體累積變動尚未用官方日曆重跑，顯著性結論已撤回。",
                ),
                (
                    "## 非農後：65% 機率 VIX 當天下跌",
                    "## 舊版發布後描述",
                ),
                (
                    "這個模式很有趣：非農當天通常帶來「答案」，VIX 降低；但之後市場消化數據含義，VIX 反而略升。",
                    f"K741 canonical 的 Part A 顯示 {pa['vix_drops_pct']:.1f}% 的 NFP 日 VIX 收跌；後續 T+1 到 T+5 沒有重跑，不能再推論固定的事件後路徑。",
                ),
                (
                    "## VIX 25-35 的非農歷史記錄\n\n當前 VIX 27.44，屬於「高波動」區間。我們查了歷史上所有 VIX ≥ 25 時的非農日（共 25 次），方向不一：\n\n- 2019-01-04（VIX=25.5）：SPY **+3.3%**（強勁就業數據 + Fed 鴿派轉向）\n- 2022-10-07（VIX=30.5）：SPY **-2.8%**（熱門 NFP，升息擔憂）\n- 2025-04-04（VIX=30.0）：SPY **-5.9%**（關稅衝擊疊加）\n- 2020-06-05（VIX=25.8）：SPY **+2.6%**（疫情後反彈）\n\n高波動時的非農，結果取決於「意外程度」而非 VIX 本身。歷史上高 VIX 非農日的平均絕對波動達 **1.55%**——但方向完全不可預測。",
                    f"## 高 VIX 組的證據邊界\n\n官方日曆樣本中，VIX ≥25 組有 {high['n']} 次 NFP，平均絕對報酬 {high['mean_abs_return_pct']:.3f}%，{high['pct_positive']:.1f}% 收漲。事件數很少，方向分布也不能用來預測下一次發布。",
                ),
                (
                    "對於使用 12/VIX 波動率目標策略的投資人：**不需要在非農前做任何調整。**",
                    "對於使用 12/VIX 波動率目標策略的投資人，K741 canonical 沒有測試事件日前後額外調整，無法給出「不需要調整」的實證結論。",
                ),
                (
                    "## 結論：VIX 27 時，靜觀其變最合適\n\n| 情境 | 建議 |\n|-----|-----|\n| 只是長期投資人 | 不需要任何特別操作 |\n| 使用 12/VIX VT 策略 | 持有現有比例，月初正常 rebalance |\n| 持有大量單押部位 | 非農前 2-3 天可考慮縮小 20-30%，但這是個人風險偏好選擇，不是策略要求 |\n| 短期交易者 | 數據公布後 30-60 分鐘再進場，等方向確立 |\n\n這次非農的關鍵不是「要不要調整」，而是「知道自己的部位在哪裡、為什麼在那裡」。VIX 27 已經是市場在替你管理風險的信號。",
                    "## 結論：VIX 27 提供風險尺度，沒有提供方向\n\n高 VIX 代表市場本來就有較大震幅。是否調整部位，應回到預先設定的損失上限、集中度與再平衡規則；K741 沒有驗證事件日前減倉、事件後進場或固定比例調整。把 VIX 當成風險預算輸入，比把單一事件研究當成交易指令更符合證據。",
                ),
                (
                    "*本文基於實驗 K661 的實證結果（數據來源：yfinance SPY+VIX，期間：2010–2026，n=195 次 NFP 事件）*\n\n*實驗腳本: experiments/k661_nfp_vol_analysis.py*\n*結果數據: experiments/k661_results.json*",
                    f"*K661 原版使用 first-Friday 替代日曆；本文數字已改依 K741 canonical 官方 BLS 日曆重跑（2010-01-01 至 2026-03-30，n={n}）。結果：`experiments/k741/k741_nfp_event_study_canonical_results.json`；認證：`experiments/k741/k741_cert_merge_summary.json`。事件前後視窗與策略未在 canonical scope 內。*",
                ),
            ],
            "details_patch": {
                "experiment_refs": ["K741"],
                "source_experiment_paths": source_paths,
            },
        },
        {
            "article_id": "mile_a1fd229a",
            "content_replacements": [
                (
                    "換句話說，如果你過去三十幾年來，每次看到 VIX 很低就當成「崩盤倒數」開始放空或清倉，你錯的次數會遠多於對的次數。",
                    "過去三十幾年來，每次看到 VIX 很低就當成「崩盤倒數」開始放空或清倉，錯的次數會遠多於對的次數。",
                ),
                (
                    "## 第三件事：恐慌高的時候，事件日真的更危險\n\n前面講的是「平靜」的故事，接下來看「恐慌」這一端。\n\n我們挑了一個每個做美股的人都知道、但很少有人拿數字回答的日子，非農就業報告（NFP），每個月第一個週五公佈。把 2010 到 2026 年共 195 次 NFP 日拉出來，按公佈前的 VIX 高低分組，結果很乾脆：VIX 低於 15 時，NFP 日標普平均波動 0.50%；VIX 高於 25 時，同樣是 NFP 日，平均 1.49%。差距三倍。\n\n更有意思的是上漲機率。VIX 低的時候，NFP 日大漲居多，七成收紅（69.4%）；VIX 超過 25 的時候完全翻轉，只剩 25% 收紅，也就是三次裡有兩次以上是跌的。\n\n這告訴我們一件事：同樣一個事件，在不同的市場溫度下，後果完全不在同一個量級。VIX 高的時候，市場早就站在高度警戒的位置，任何一個不夠強的數字都會變成賣壓的觸發點。數字本身只是火柴，底層的壓力來自 VIX 已經定價的恐慌。\n\n那既然 NFP 日波動大，提前避開划算嗎？我們也回測了。「完全跳過 NFP 日」確實把最大回撤從 33.7% 壓到 28.2%，但年化報酬從 13.97% 掉到 11.9%。原因是 NFP 日有 59.5% 其實是收漲的，你避開波動的同時也避開了上漲，還多付兩次交易成本。波動大不等於損失大。",
                    f"## 第三件事：恐慌高的時候，先分清絕對風險與事件增量\n\n非農就業報告（NFP）依官方 BLS 日曆發布，並非固定在每月第一個週五。K741 canonical 把 2010 到 2026 年共 {n} 次 NFP 日按發布前 VIX 分組：VIX 低於 15 時，NFP 日 SPY 平均絕對報酬 {low['mean_abs_return_pct']:.3f}%；VIX 高於 25 時是 {high['mean_abs_return_pct']:.3f}%，約差 {spread:.1f} 倍。收漲比例分別是 {low['pct_positive']:.1f}% 與 {high['pct_positive']:.1f}%。\n\n絕對震幅隨 VIX 升高，這點很清楚。事件增量要拿 NFP 日和同體制平日比較：四組比值是 {low['ratio']:.3f}、{med['ratio']:.3f}、{elev['ratio']:.3f}、{high['ratio']:.3f}，卻沒有一組通過 Holm 校正。低、高 VIX 的直接 bootstrap 差異也未達顯著。分組勝率與震幅只能當描述，不能證明 VIX 體制決定事件方向。\n\n舊版「完全跳過 NFP 日」策略與事件前後漂移使用 first-Friday 替代日曆，canonical 重跑沒有涵蓋策略部分。原文的回撤、年化報酬與交易建議已撤回，等待官方日曆版本重跑。",
                ),
                (
                    "![VIX 體制與市場狀態](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/digest_vix_regime_chart.png)\n*左圖：恐慌越高，NFP 事件日的波動越大、收漲機率越低（2010–2026，195 次非農日）。右圖：低 VIX 之後，未來三個月反而跌得更淺（1990–2026，9,183 個交易日）。資料來源：yfinance（SPY、^VIX、^GSPC）。*",
                    f"![官方 BLS 日曆下的 NFP 相對波動分組]({args.chart_url})\n*圖表：K904 canonical 的獨立交叉核對。分組比值呈下降，但四組均未通過多重比較校正，組間差異也尚未證實。資料來源：官方 BLS 日曆、SPY 與 VIX pinned snapshot。*",
                ),
                (
                    "| 非農日 × VIX 體制 | VIX<15 時 NFP 日波動 0.50%、收漲七成；VIX≥25 時波動 1.49%、收漲剩 25% | 同一事件，市場溫度決定後果；高 VIX 時事件日更容易往下 | mile_eda69bfb |",
                    f"| 非農日 × VIX 體制 | VIX<15 時 NFP 日波動 {low['mean_abs_return_pct']:.3f}%、收漲 {low['pct_positive']:.1f}%；VIX≥25 時波動 {high['mean_abs_return_pct']:.3f}%、收漲 {high['pct_positive']:.1f}% | 市場溫度提供絕對風險尺度；分組差異尚未通過校正，不能推論方向 | mile_eda69bfb |",
                ),
                (
                    "第三，市場溫度高（VIX 高）的時候，事件日要更小心。非農、財報、FOMC 這類日子，在恐慌體制下往下走的機率明顯變高。這不是要你空手，重點是提醒你：高 VIX 環境本來就不適合加碼下注。",
                    "第三，市場溫度高（VIX 高）的時候，部位要能承受更大的絕對震幅。K741 的方向比例只是小樣本描述，未證實事件日會更容易往下；風險預算應依震幅與最大可承受損失設定。",
                ),
                (
                    "- mile_eda69bfb｜VIX 體制決定一切：195 次非農公佈日，波動率差距達 3 倍",
                    f"- mile_eda69bfb｜VIX 體制的描述性差異：{n} 次非農公佈日，波動幅度約差 {spread:.1f} 倍",
                ),
            ],
            "details_patch": {
                "source_experiment_paths": source_paths,
            },
        },
        {
            "article_id": "mile_ffb14405",
            "content_replacements": [
                (
                    "站內[《VIX 體制決定一切：195 次非農公佈日，波動率差距達 3 倍》](https://volpred.zeabur.app/v3/reports/mile_eda69bfb)（6/21）在事件日上得到同一個結論，而且更極端：2010 到 2026 年的 195 次非農公佈日裡，當天 VIX 低於 15 時，SPY 平均只動 0.498%；VIX 高於 25 時，平均動 1.488%。同樣是「非農日」，體制不同，震幅差三倍。\n\n換句話說，日曆告訴你「哪天會有事」，體制告訴你「有事的話會有多大」。前者人人都有，後者才是決定部位大小的東西。",
                    f"站內[《VIX 體制的描述性差異：{n} 次非農公佈日，波動幅度約差 {spread:.1f} 倍》](https://volpred.zeabur.app/v3/reports/mile_eda69bfb)（6/21）已依官方 BLS 日曆更正：2010 到 2026 年的 {n} 次非農公佈日裡，VIX 低於 15 時，SPY 平均絕對報酬 {low['mean_abs_return_pct']:.3f}%；VIX 高於 25 時為 {high['mean_abs_return_pct']:.3f}%。絕對震幅約差 {spread:.1f} 倍，但相對同體制平日的四組差異都沒有通過 Holm 校正。\n\n日曆告訴你事件時間，VIX 提供當下的絕對風險尺度。K741 尚未證明體制會改變事件的增量衝擊或方向。",
                ),
                (
                    "| **1** | 先確認體制：VIX 15.03，低 VIX 格。歷史上這一格接下來一週的平均震幅 8.29%。 | 本文體檢（SPY 4,090 天）、[mile_eda69bfb](https://volpred.zeabur.app/v3/reports/mile_eda69bfb) |",
                    "| **1** | 先確認體制：VIX 15.03，低 VIX 格。歷史上這一格接下來一週的平均震幅 8.29%；NFP 分組只提供描述性旁證。 | 本文體檢（SPY 4,090 天）、[mile_eda69bfb](https://volpred.zeabur.app/v3/reports/mile_eda69bfb) |",
                ),
                (
                    "- [VIX 體制決定一切：195 次非農公佈日，波動率差距達 3 倍](https://volpred.zeabur.app/v3/reports/mile_eda69bfb)（6/21）｜同樣是非農日，VIX<15 時 SPY 動 0.498%，VIX>25 時動 1.488%。",
                    f"- [VIX 體制的描述性差異：{n} 次非農公佈日，波動幅度約差 {spread:.1f} 倍](https://volpred.zeabur.app/v3/reports/mile_eda69bfb)（6/21）｜VIX<15 時 SPY 平均動 {low['mean_abs_return_pct']:.3f}%，VIX>25 時動 {high['mean_abs_return_pct']:.3f}%；組間差異尚未通過檢定。",
                ),
            ],
            "details_patch": {
                "experiment_refs": ["K741"],
                "source_experiment_paths": source_paths,
            },
        },
        {
            "article_id": "mile_76475146",
            "content_replacements": [
                (
                    "NFP 的版本更細。K741 檢查 2010-01-01 到 2026-03-28 的 NFP 公布日，樣本有 195 次。NFP 日 SPY 平均絕對報酬是 0.816%，非 NFP 日是 0.713%。波動有放大，但不是每次都同一個方向。\n\n更重要的是 VIX 體制。低 VIX 區間的 NFP 日平均絕對報酬是 0.498%；高 VIX 區間的平均絕對報酬升到 1.488%。同樣叫 NFP，市場所在的波動體制不同，風險輪廓就不是同一件事。",
                    f"NFP 的版本更細。K741 canonical 依官方 BLS 日曆檢查 2010-01-01 到 2026-03-30 的 NFP 公布日，樣本有 {n} 次。NFP 日 SPY 平均絕對報酬是 {nfp_abs:.3f}%，非 NFP 日是 {non_abs:.3f}%，比值 {ratio:.3f}；兩個 overall 比較做 Holm 校正後，最小顯著性為 {holm_overall:.3f}。\n\nVIX 分組提供絕對風險尺度：低 VIX 區間的 NFP 日平均絕對報酬是 {low['mean_abs_return_pct']:.3f}%，高 VIX 區間是 {high['mean_abs_return_pct']:.3f}%。四組相對同體制平日的差異都沒有通過 Holm 校正，直接組間 bootstrap 區間也包含零。市場狀態與震幅相關，事件增量是否真的隨體制改變仍待更多證據。",
                ),
                (
                    "比較好的做法，是把事件日放進風控語境。低 VIX 的 NFP 可以提醒你別低估當日波動；高 VIX 的 NFP 則要問市場是否已經在高價買保護。FOMC 前短端結構收回來時，追買保護也可能太晚。",
                    "比較好的做法，是把事件日放進風控語境。低 VIX 或高 VIX 都先看可承受震幅，再看事件保護價格；K741 沒有證明高 VIX 會消除 NFP 增量。FOMC 前短端結構收回來時，追買保護也可能太晚。",
                ),
                (
                    "![K741 NFP VIX regime chart](https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/K741_vix_regime_nfp_chart.png)",
                    f"![官方 BLS 日曆下的 NFP 相對波動分組]({args.chart_url})",
                ),
                (
                    "資料來源：K820 `experiments/k820/k820_event_risk_budgeter_results.json`；K741 `experiments/k741/k741_nfp_event_study_results.json`；以及上述已發佈 archive 文章。",
                    "資料來源：K820 `experiments/k820/k820_event_risk_budgeter_results.json`；K741 canonical `experiments/k741/k741_nfp_event_study_canonical_results.json` 與 `experiments/k741/k741_cert_merge_summary.json`；以及上述已發佈 archive 文章。",
                ),
            ],
            "details_patch": {
                "source_experiment_paths": [
                    "experiments/k820/k820_event_risk_budgeter_results.json",
                    *source_paths,
                ],
                "image_url": args.chart_url,
                "image_urls": [
                    args.chart_url,
                    "https://qxhfgdfzazwpkdgesavm.supabase.co/storage/v1/object/public/article-images/event_jobs_20260605_chart.png",
                ],
            },
        },
    ]

    if args.descriptions_only:
        corrections = [
            {
                **correction,
                "title_replacement": None,
                "content_replacements": [],
                "details_patch": {},
            }
            for correction in corrections
            if correction.get("description_replacement") is not None
        ]

    reports = []
    for correction in corrections:
        reports.append(
            apply_article_correction(
                correction["article_id"],
                title_replacement=correction.get("title_replacement"),
                description_replacement=correction.get(
                    "description_replacement"
                ),
                content_replacements=correction["content_replacements"],
                details_patch=correction["details_patch"],
                summary=summary,
                action="numbers_correction",
                storage_dir=args.storage_dir,
            )
        )

    compact = [
        {
            "article_id": report["article_id"],
            "replacements": len(report["content_replacements"]),
            "title_changed": report["title_change"] is not None,
            "description_changed": report["description_change"] is not None,
            "synced": report["synced"],
            "gateway": report["gateway"],
        }
        for report in reports
    ]
    print(json.dumps(compact, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
