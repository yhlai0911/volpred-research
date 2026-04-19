# Next Draft Candidate: K1174 GDELT Empirical — EU-JP Gap Evaporates

> **⚠️ DOWNGRADED 2026-04-19 18:35 UTC** — re-inspection revealed K1174 empirical finding 已以「⚠️ 2026-04-14 更新」footer 形式吸收進 `mile_45060685` (K1170 article, research audience, published). 獨立 memo dispatch 會**內容重疊**。保留此 memo 作為日後**pivot-angle 候選**：若要寫獨立 K1174 文章，angle 必須是「empirical replication standard posture as class-wide methodology lesson」而非單純重述 K1170 vs K1174 對比。優先級低於 K1128 memo（真正 uncovered, 0 tag hits, general audience）。

**Prepared 2026-04-19** as preemptive brief for next `draft_pool_low` remediation. Fourth memo in series (after K957 consumed / K1091 consumed / K1092 ready).

## K1174 Overview

**Score**: 10 (top of publication_candidates.json K1100-K1224 research-driven filter)
**Title**: K1174: GDELT empirical partial replication WEAKENS K1170 — EU-JP 3.28σ gap evaporates under真正 press-concentration 計算
**Coverage**: uncovered any audience (feed tags 0 hits)

## Why this topic works

- **研究誠實原則 case study** — general audience hook：「一個 3.28σ 看似顯著的跨市場效應，在換成真實 GDELT 原始資料後 delta 從 0.45 → 0.005（降 ~99%）」
- **methodology lesson**：K1170 用 hardcoded press-concentration proxy 推導 3-level mechanism；K1174 用 GDELT GKG raw files 12:00 UTC slice 實算 per-stock PCR，結果 near-zero
- **under-powered 誠實標示**：K1174 自己 INSUFFICIENT_COVERAGE（1/96 files, Jan-May 2024, EU n=3 / JP n=2）— 不搞「直接推翻」姿態，是 research honesty 的正面範本
- **反向 signal**：cross-market Spearman ρ=-0.257 (p=0.62) — hardcoded calibration 與實證資料方向性都不合

## 具體數字 (3 組)

- **K1170 hardcoded**: ΔPCR(JP-EU) = 0.45 → Welch t=3.28σ 推論
- **K1174 empirical**: ΔPCR(JP-EU) = 0.005, Welch t=0.025, p=0.98 — **完全 null**
- **filled panel N=153**: t=3.43 Harvey PASS，但 140/153 imputation fallback — 作者自標 "suggestive, not confirmatory"

## Article Skeleton Proposal (general audience 2000-2500 chars)

1. **Intro**: K1170 如何用 press-concentration 解釋 EU-JP residual gap（承接 K1167 two-level mechanism 3-level 加強版）
2. **Hardcoded proxy 的方便與危險**: 為什麼當初用 hardcoded PCR — 資料取得成本、GDELT 複雜度
3. **GDELT raw files 實證**: 12:00 UTC GKG slice, 25 reliable events, 6 markets
4. **結果**: EU-JP delta 0.005 vs 宣稱 0.45 — 方向與 magnitude 都不支持
5. **研究誠實的自我標示**: K1174 不跳到「K1170 錯」姿態，標 INSUFFICIENT_COVERAGE
6. **方法論教訓**: hardcoded proxy 對 cross-market claim 特別危險 — 容易放大 between-market noise
7. **Next step**: full 96-files/day or BigQuery scan 才能定論

## Charts needed (2 real)

1. K1170 vs K1174 per-market PCR scatter（6 markets）+ 45° line + Spearman ρ=-0.26 annotation
2. EU vs JP ΔPCR bar chart — 左邊 hardcoded 0.45 with 3.28σ, 右邊 empirical 0.005 with p=0.98（視覺衝擊）

## Data sources

- `experiments/k1174/k1174_results.json` — main JSON
- `experiments/k1174/k1174_per_stock_pcr.csv` — empirical PCR
- `experiments/k1170/k1170_results.json` — hardcoded 對照
- `experiments/k1174/k1174_eu_jp_histogram.png` — ready-made fig

## Dispatch when

- Pool drops below 4 after K1092 used OR
- User requests「研究誠實案例」articles
- **Audience balance priority** (2026-04-19 18:30 UTC observation): pool 目前 3 research / 1 general（mile_a21a6e06 K1091 newest general），下次 release (20:00 UTC) 若挑 general → pool 變 3 research / 0 general，此 memo 應優先於 K1092 (research audience) dispatch 以補 general-side 平衡

## Differentiation vs other memos

- **vs K957** (methodology lessons from experiments process) — K1174 是 **single replication-failure case study**
- **vs K1091** (asset-class asymmetry FAIL mechanism) — K1174 是 **same-market proxy-replacement mechanism fail**
- **vs K1092** (Pareto-dominant but below Harvey subtlety) — K1174 是 **between-method ΔPCR 近零**
- **vs K672** (evidence hierarchy) — K1174 示範「hardcoded proxy evidence 層級應降級」

## Hard rules (agent briefing template)

- proposer="Claude" / audience="general"（research honesty hook 適合大眾）/ category="milestone" / status="draft"
- 2000+ chars CJK
- 2 real matplotlib charts
- 不 touch shared memory / 不 overreach beyond K1174 自標的 INSUFFICIENT_COVERAGE（不可寫成「K1170 被推翻」）
- 標題必須反映 "WEAKENS" / "PARTIAL" 而非 "OVERTURNS"
- 明文承認 n=25 reliable events under-powered
