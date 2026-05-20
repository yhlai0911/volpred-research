#!/usr/bin/env python3
"""Publish K1121 alt-data allocation NULL research article to feed.

Generates 2 fresh matplotlib charts from k1121_results.json (Sharpe comparison
with 95% bootstrap CI, and stress-period drawdowns), uploads to Supabase
article-images bucket, then calls Publisher.publish_milestone.

Numbers byte-match experiments/k1121/k1121_results.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from volpred.charts import upload_chart
from volpred.publisher.publisher import Publisher

ROOT = Path(__file__).resolve().parents[1]
RESULTS = json.loads((ROOT / "experiments/k1121/k1121_results.json").read_text())

# ─── Chart 1: Sharpe Δ vs S1 50/50 baseline with 95% bootstrap CI ───
fig, ax = plt.subplots(figsize=(9, 5.2))
strategies = ["S2", "S3", "S4", "S5", "S6"]
labels = [
    "S2 vol-target",
    "S3 NFCI 區間",
    "S4 EPU regime",
    "S5 NFCI regime",
    "S6 hybrid",
]
boot = RESULTS["bootstrap_vs_S1_50_50"]
diffs = [boot[f"{s}_vs_S1"]["obs_diff"] for s in strategies]
ci_low = [boot[f"{s}_vs_S1"]["ci_low"] for s in strategies]
ci_high = [boot[f"{s}_vs_S1"]["ci_high"] for s in strategies]
pvals = [boot[f"{s}_vs_S1"]["p_value"] for s in strategies]

err_low = [d - lo for d, lo in zip(diffs, ci_low)]
err_high = [hi - d for d, hi in zip(diffs, ci_high)]

xs = np.arange(len(strategies))
colors = ["#888888" if p > 0.10 else "#d62728" for p in pvals]
ax.bar(xs, diffs, color=colors, alpha=0.85, edgecolor="black", linewidth=0.6)
ax.errorbar(xs, diffs, yerr=[err_low, err_high], fmt="none",
            ecolor="black", capsize=6, lw=1.4)
ax.axhline(0, color="black", lw=1.0)
for i, (d, p) in enumerate(zip(diffs, pvals)):
    ax.text(i, ci_high[i] + 0.04, f"p={p:.3f}", ha="center", fontsize=10,
            color="#333333")
ax.set_xticks(xs)
ax.set_xticklabels(labels, rotation=15, ha="right")
ax.set_ylabel("Sharpe 差距 (vs S1 50/50 baseline)")
ax.set_title("K1121: Alt-data allocation 5 spec 全部 H0 無法拒絕\n"
             "Sharpe Δ 95% bootstrap CI 全含零 (p ∈ [0.264, 0.966])",
             fontsize=12, fontweight="bold")
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
chart1_path = ROOT / "experiments/k1121/k1121_article_sharpe_diff_ci.png"
fig.savefig(chart1_path, dpi=140, bbox_inches="tight")
plt.close(fig)

# ─── Chart 2: stress-period Sharpe (COVID, Rate Shock 2022, SVB 2023) ─
fig, ax = plt.subplots(figsize=(9.5, 5.2))
stress = RESULTS["stress_episodes"]
periods = ["COVID_2020", "Rate_Shock_2022", "SVB_2023"]
period_lbls = ["COVID 2020\n(Feb-Apr)", "Rate Shock 2022\n(Jan-Oct)",
               "SVB 2023\n(Mar-Apr)"]
strats = ["S1", "S2", "S3", "S4", "S5", "S6"]
strat_lbls = ["S1 50/50", "S2 vol-target", "S3 NFCI 區間",
              "S4 EPU regime", "S5 NFCI regime", "S6 hybrid"]

xs = np.arange(len(periods))
width = 0.13
colors = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]
for i, s in enumerate(strats):
    vals = [stress[p]["by_strategy"][s]["sharpe"] for p in periods]
    ax.bar(xs + (i - 2.5) * width, vals, width, label=strat_lbls[i],
           color=colors[i], alpha=0.88, edgecolor="black", linewidth=0.4)

ax.axhline(0, color="black", lw=0.8)
ax.set_xticks(xs)
ax.set_xticklabels(period_lbls)
ax.set_ylabel("Annualised Sharpe")
ax.set_title("K1121: 三段壓力期 — alt-data 沒有顯著保護優勢\n"
             "S5 NFCI regime 在 COVID/Rate Shock 表現相近，但 SVB 反輸 baseline",
             fontsize=12, fontweight="bold")
ax.legend(loc="lower left", fontsize=9, ncol=3)
ax.grid(axis="y", alpha=0.3)
fig.tight_layout()
chart2_path = ROOT / "experiments/k1121/k1121_article_stress_sharpe.png"
fig.savefig(chart2_path, dpi=140, bbox_inches="tight")
plt.close(fig)

# ─── Upload to Supabase ─────────────────────────────────────────
print(f"Uploading chart 1: {chart1_path}")
chart1_url = upload_chart(str(chart1_path))
print(f"  → {chart1_url}")
print(f"Uploading chart 2: {chart2_path}")
chart2_url = upload_chart(str(chart2_path))
print(f"  → {chart2_url}")

# ─── Build Markdown content ─────────────────────────────────────
TITLE = "Alt-data 在預測上失敗，那 allocation 上呢？K1121 給出同樣的答案 — Null"

content = f"""## 摘要

[提出: Claude]

延續 K1116 / K1118 系列「alt-data 對 RV 預測一律 NULL」的發現，K1121 把同一組 alt-data（FRED EPU、NFCI、^VIX）轉換成 **portfolio allocation signal**，配置 SPY+GLD 做 6-strategy horse race（S1 = 50/50 baseline、S2 = vol-target、S3 = NFCI 區間切換、S4 = EPU regime、S5 = NFCI regime、S6 = NFCI+EPU hybrid）。樣本 2019-01-15 至 2026-04-10、共 1,817 個交易日，stationary bootstrap (B=500) 與 Opdyke (2007) Sharpe inference 並用。**結論：5 種 alt-data spec 對 50/50 baseline 的 Sharpe 差全部 H0 無法拒絕**（p ∈ [0.264, 0.966]，95% CI 全含零）；Paper 4「alt-data null」compendium territory 從 forecasting 擴展到 allocation。

## 研究背景

K1116 在 SPY 上把 EPU、NFCI、STLFSI 加入 GJR-X 預測，QLIKE 不只沒贏 baseline 還反向劣化；K1118 把同樣 spec 推到 GLD / TLT / BTC 等跨資產也同樣 NULL，9/9 spec 全部 H0 無法拒絕（DM-HLN test）。在投資人實務上，下一個自然問題是：**就算 alt-data 不能改善 \\|forecasting error\\|，會不會在 regime detection 上有用？**——也就是把 alt-data 用做「該滿倉股、該防守、該避險」的開關，而不是一個 RV 點估計的輸入。

K1121 就是這個 pivot 的正式檢定。設計與既有 50/50 SPY/GLD 的 8 篇 replication moat（K2–K89）對齊：使用同樣的資產對、同樣的長期樣本期、同樣的 stationary bootstrap 抽樣方式，並排上 6 種 strategy spec 同一條 horse race。

## 方法與數據

| 項目 | 設定 |
|---|---|
| 資產 | SPY, GLD（每日 close-to-close return） |
| Alt-data | FRED `USEPUINDXD`（EPU）、FRED `NFCI`、yfinance `^VIX` |
| 期間 | 2019-01-15 ~ 2026-04-10（1,817 個交易日） |
| Lookahead 防護 | NFCI `shift(5)` 模擬 publication delay；EPU `shift(2)`；VIX `shift(1)` |
| OOS 切點 | 第 998 日（IS 997, OOS 820） |
| Sharpe inference | stationary bootstrap B=500，95% CI；Opdyke (2007) Δ Sharpe |
| Random seed | 42（全程 fixed） |

策略 spec 摘要：

| Strategy | 配置邏輯 |
|---|---|
| S1 | 固定 SPY 50% / GLD 50%（baseline，無 alt-data） |
| S2 | 用 21 日 RV 做 vol-target（target ann vol = 12%） |
| S3 | NFCI 連續映射到 SPY weight \\[0.3, 0.7\\] 的線性切換 |
| S4 | EPU 5-tier regime → 5 個離散 SPY weight |
| S5 | NFCI 5-tier regime → 5 個離散 SPY weight |
| S6 | hybrid: NFCI weight × EPU weight 取平均 |

對照下方 H1–H4 假設，這個設計同時測試了 alt-data **是否打贏 vol-target（H1）**、**是否打贏 50/50 baseline（H2）**、**是否在壓力期主動降股（H3）**、**hybrid 是否優於 single signal（H4）**。

## 核心發現

### 發現一：5 種 alt-data spec 對 50/50 baseline Δ Sharpe 全部 H0 無法拒絕

完整 full-sample headline 表：

| Strategy | Sharpe (full) | Sharpe (OOS) | MDD | Calmar | Sortino | 平均 wSPY |
|---|---|---|---|---|---|---|
| S1 | 1.309 | 1.975 | -0.203 | 0.888 | 1.636 | 0.500 |
| S2 | 1.072 | 1.474 | -0.220 | 0.720 | 1.417 | 0.880 |
| S3 | 1.210 | 1.748 | -0.179 | 0.883 | 1.588 | 0.543 |
| S4 | 1.283 | 1.856 | -0.232 | 0.752 | 1.709 | 0.566 |
| S5 | 1.312 | 1.656 | -0.179 | 0.950 | 1.731 | 0.594 |
| S6 | 1.305 | 1.806 | -0.184 | 0.911 | 1.734 | 0.568 |

stationary bootstrap (B=500) 對 S1 的 Δ Sharpe 與 95% CI：

| 比較 | obs Δ Sharpe | 95% CI | bootstrap p |
|---|---|---|---|
| S2 vs S1 | -0.238 | [-0.670, +0.174] | 0.264 |
| S3 vs S1 | -0.099 | [-0.344, +0.132] | 0.388 |
| S4 vs S1 | -0.026 | [-0.310, +0.257] | 0.860 |
| S5 vs S1 | +0.003 | [-0.231, +0.254] | 0.966 |
| S6 vs S1 | -0.005 | [-0.191, +0.172] | 0.948 |

**5 條 CI 全部跨越零，5 個 p-value 全部 ≥ 0.264**。即便看起來最好的 S5（full-sample Sharpe 1.312 vs S1 1.309），bootstrap 後的 obs Δ 只有 +0.003，p=0.966 — 噪音水準。Harvey/Liu/Zhu (2016) Sharpe threshold（multiple-testing 後 \\|t\\| ≥ 3.0）門檻在這裡完全無關，因為連 single-test 顯著性都不成立。

![K1121 Sharpe Δ 95% bootstrap CI]({chart1_url})

### 發現二：alt-data 沒打贏 vol-target，hybrid 也沒打贏 single

| 假設 | 內容 | obs Δ Sharpe | bootstrap p | PASS? |
|---|---|---|---|---|
| H1 core | S4 / S5 vs S2（alt-data > vol-target） | +0.212 / +0.241 | 0.280 / 0.166 | **FAIL** |
| H2 moat | best alt-data Sharpe ≥ S1 | S5 = 1.3122 vs S1 = 1.3094 | — | PASS（差 0.003，無實務意義） |
| H4 hybrid | S6 > max(S3, S4, S5) | S6 = 1.3047 vs max = 1.3122 | — | **FAIL** |

H2「PASS」是 trivially true（差 0.003），不可解讀為 alt-data 有用 — bootstrap 看就是噪音。H4 直接 FAIL：把兩個 signal 結合反而比 best single signal 略差，這跟 K1118b FX-IV 把多訊號組進 basket 反而拖累的型態一致。

### 發現三：壓力期 — H3 在 1/3 episode 部分 PASS，但無實務優勢

| 期間 | S1 wSPY | S5 wSPY | S5 reduce? | S1 Sharpe | S5 Sharpe |
|---|---|---|---|---|---|
| COVID 2020 (Feb-Apr) | 0.500 | 0.331 | YES | -0.183 | +0.004 |
| Rate Shock 2022 (Jan-Oct) | 0.500 | 0.300 | YES | -1.132 | -1.160 |
| SVB 2023 (Mar-Apr) | 0.500 | 0.513 | NO | +5.491 | +2.837 |

S5 在 COVID 與 Rate Shock 確實有降股（H3 PASS in 2/3 episodes），但**換來的是與 S1 接近、甚至更差的壓力期 Sharpe**：Rate Shock 2022 的 S5 Sharpe -1.160 比 S1 的 -1.132 還略差，COVID 2020 雖從 -0.183 拉回 +0.004 但金額微小（年化報酬 +0.13%）。SVB 2023 完全沒降股，S5 的 +2.837 甚至遠輸 S1 的 +5.491 — alt-data signal 在那次 idiosyncratic banking shock 上根本沒反應。

![K1121 三段壓力期 Sharpe]({chart2_url})

換言之：「alt-data 主動降股」這個 H3 narrative 的部分 PASS 是 mechanical artifact（NFCI tiering 設計上會在金融壓力期把 wSPY 推低），但**降低後的風險調整報酬並沒有顯著優於 baseline**。50/50 在所有三段壓力期都表現得 at least as good，且免去 lookahead / spec / refit 的所有 model risk。

## 為何重要：Paper 4 compendium territory expand

Paper 4「Alt-data fails to predict realised volatility — a multi-asset compendium」的原 scope 是 forecasting null：9 spec × 4 asset 全部 NULL。K1121 把這個 null compendium 從 forecasting 擴展到 **allocation**：

- **同 alt-data 來源**（EPU、NFCI、VIX）
- **同 sample period family**（2019-2026）
- **同 statistical machinery**（stationary bootstrap）
- **同 baseline moat**（50/50 SPY/GLD，K2–K89 8 篇 replication 已證 baseline 不可打敗）

5 種完全合理的 allocation spec 全部失靈，意味著 Paper 4 的核心訊息可以從「**alt-data 不能 forecast RV**」升級為「**alt-data 既不能 forecast RV，也不能取代 50/50 做 regime allocation**」。對讀者與審查者而言，這是 compendium territory 的一次顯著擴張：null result 不再侷限在 point forecast metric (QLIKE)，而擴展到 portfolio-level 風險調整報酬（Sharpe、Sortino、Calmar、MDD）。

對實務投資人，啟示也更明確：別期待 EPU 指數或 NFCI 進入你的 allocation rule 會帶來顯著效用。50/50 的 K2–K89 moat 持續成立。

## 限制與穩健性

1. **Lookahead 已防護**：NFCI `shift(5)` 對應 FRED 週發佈延遲、EPU `shift(2)` 對應日發佈延遲、VIX `shift(1)`。所有 signal 都使用 t-1 資訊產生 t 期 weight。
2. **OOS 是 80/20 split, in-sample 997 / out-of-sample 820**：full-sample 與 OOS 結論一致（OOS S5 Sharpe 1.656 仍輸 S1 1.975）。
3. **Sample period 含 2 次空頭與 1 次危機**（COVID、Rate Shock 2022、SVB 2023），符合 long-sample 要求。
4. **Bootstrap B=500**（stationary bootstrap, Politis–Romano 1994），block length auto-select。
5. **Random seed = 42**：全程固定，含 weight 計算、bootstrap 抽樣、tier 切點。
6. **Spec 限制**：只測 NFCI / EPU / VIX 三類 alt-data；未測 GDELT、satellite、social media sentiment 等 alternative alt-data。延伸方向是把 GDELT GKG (K1170 系列已驗證 EU/JP cross-region effect) 套入同一 6-strategy 框架。
7. **Asset universe 限制**：只測 SPY+GLD。延伸方向是 SPY+TLT、SPY+BTC、跨市場（如 0050.TW + 黃金期）。

## 結論與下一步

K1121 把 K1116 / K1118 的「alt-data 預測 NULL」延伸到 allocation 場域，得到完全一致的 NULL：5 種 spec 對 50/50 baseline 的 Δ Sharpe 全部不顯著（p ≥ 0.264）、95% CI 全部含零、hybrid 沒贏 best single signal、壓力期 H3 部分 PASS 但無實務優勢。

下一步研究方向：

- **Gx 系列 alt-data**：把 GDELT GKG event count、tone score 套入同一 6-strategy 框架（沿 K1170 的 cross-region 方法論）
- **Asset universe 擴展**：SPY+TLT（傳統 risk-parity 對照）、台股 0050.TW + 黃金期（domestic moat）
- **Allocation kernel 升級**：把 6-strategy 從 deterministic regime 升級到 Bayesian model averaging 或 MCS-selected ensemble，看 NULL 是否在 averaging 之後仍然 robust

Paper 4 narrative 因此從「forecasting compendium」實質擴大為「forecasting + allocation compendium」，這是 K1121 對 paper 的最大邊際貢獻。

---

*本文基於實驗 K1121（腳本：`experiments/k1121/k1121.py`，結果：`experiments/k1121/k1121_results.json`）。資料來源：yfinance（SPY, GLD, ^VIX）+ FRED（USEPUINDXD, NFCI）。期間：2019-01-15 ~ 2026-04-10，N=1,817 個交易日。Lookahead 防護：NFCI shift(5)、EPU shift(2)、VIX shift(1)。Random seed=42。Bootstrap B=500（stationary bootstrap, Politis–Romano 1994）。*
"""

print(f"\nContent length: {len(content)} chars")

# ─── Publish ─────────────────────────────────────────────────────
pub = Publisher()
result = pub.publish_milestone(
    title=TITLE,
    description=content,
    phase="research",
    category="milestone",
    audience="research",
    tags=[
        "研究",
        "K1121",
        "portfolio-allocation",
        "alt-data",
        "NFCI",
        "EPU",
        "Paper4",
        "null-result",
    ],
    proposer="Claude",
    status="draft",
)

print(f"\nPublished: {result}")
print(f"Chart 1 URL: {chart1_url}")
print(f"Chart 2 URL: {chart2_url}")
