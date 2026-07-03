---
name: Layer 4 narrative-arc dedup
description: 派寫作 agent 前主線程必做 Layer 4 邏輯弧線查重，不只 Layer 1-3 字串級
type: feedback
---

3-layer dedup（candidates / feed grep / draft 池）只 catch 字串級 dup。**邏輯結構相同、外殼換掉**會漏網：
- 「N 個實驗 → M 個 established facts」（K200/K644/K650 = 同 arc，N=200/24/271 換）
- 「失敗訊號 → 換變數重做 → 又失敗」（mile_bad0d545 vs K1199 = 同 arc，cut-point 固定→動態）
- 「Proxy 換但結論仍 NULL」（K1172→K1173 = 同 arc）

**Why**: 用戶 2026-05-17 抓到 K650/K1199 兩篇 retract，明示「邏輯重複比字串重複更嚴重，讀者立刻覺得繞圈」。直接傷 Mission 1（文章品質）+ Mission 4（平台 retention）。3-layer 過了不算 PASS，必須加 Layer 4。

**How to apply**:
1. 派寫作 agent 前在主線程做 Layer 4：
   - 抽 candidate 的 arc template 一句話
   - grep 過去 30 天 feed 對比 arc 關鍵詞
   - 算同 K-cluster 在 14 天內密度（≥2 → 強制換 cluster）
   - 「參數變奏 test」：N 變大 / cut-point 變奏 / proxy 換但同結論 → 不算新文章
2. Agent brief 明寫「不要做以下變奏：[list]」鎖住 agent
3. 規則完整版：`.claude/rules/publishing.md §選題三層查重 → 層 4`
4. Post-publish 才發現 dup：標 `status=retracted` + `retracted_reason="logical_dup_with_prior"` + `retracted_dup_of=[mile_xxx]`，feed.json 保留 entry 做 audit trail

**2026-06-10 升級為 code hard gate**（strike 3：K1449/K1091 銅 arc dup，用戶抓到）：soft memory 自律已證明擋不住 — 現在 `src/volpred/publisher/arc_dedup.py`（資產 entity×結論 class domain model）在三個 choke point 強制執法：publisher publish_milestone HARD BLOCK、refill 方向源頭 filter、`scripts/check_arc_dedup.py` 寫前 CLI（hourly prompt b2）。本 memory 降級為背景脈絡；執法以 code gate 為準。Regression: `tests/test_arc_dedup.py`。

**2026-07-04 邊界校準（老闆 Telegram msg95）**：不要把「結論句式像」當成不寫/不發理由。release layer 的 hard block 只應給強證據：同一 K / 同一明確 data source / near-identical same-ref recycle。不同 K、不同研究、不同數據，只是同為 NULL/positive 或同類敘事，最多是 warn-only + audit trail；尤其發文脫班時，dedup/cluster filter 不得用 fuzzy arc 阻擋釋出。reader 版 vs research 版若不是 near-identical recycle，視為互補，不算重複。
