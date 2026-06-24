# Refactor Plan — Release-Layer Deadlock（發文脫班 root cause）

**狀態**：診斷完成，待實作。2026-06-24 由發文脫班 CRITICAL 觸發。
**3-STRIKE TRIGGER**：脫班反覆（2026-06-22 整日脫班 + 2026-06-24 再現）+ 呼應 memory `feedback_recycling_is_release_layer_not_research`（文章鬼打牆根因在釋出端）。屬同根因重複 → 結構性重構，不再表面修補。

## 症狀
- 作用窗內 feed 最新文章距今 > 5h（dead-man switch 觸發）。
- `release-pool-by-settings`（含 `--force`）`released_count: 0`，所有 skip list 空 → candidates 本身為空。

## Root cause（精確，有 code 定位）
1. **draft 池 39 篇全被 `release_dedup_skipped` flag 鎖死**（實測 39/39 active，TTL=2 天內）。
   - flag 設定點：`src/volpred/ops/content.py:861` — `if arc_dups or dup is not None or flood is not None:` 時設 `release_dedup_skipped=True`。
   - 39 篇皆 research 同 narrative-arc 變奏（RECH-X 跨市場複製系列、VIX 拆解系列）→ 全被 **arc-dedup** 正確判重複。
2. **被擋的 draft 留池不退回**（content.py:863 comment「left as draft for review, not destructively unpublished」）→ 積壓。
3. **無限循環**：flag 2 天 TTL 過期 → 重新評估 → 還是同 arc 重複 → 又被標 → 永遠釋不出。
4. **上游持續產同 arc**：draft 生成端（research milestone → article / refill）對 research 主題缺有效 arc-dedup pre-check，持續產出與已發佈同 arc 的變奏 → 池子只有重複、無 fresh-arc。

→ 生產端產重複 + 釋出端正確擋重複 + 被擋者不退回 = 池子被重複塞滿、fresh 進不來、永久脫班。

## 為什麼 `--force` 是錯解（用戶 2026-06-24 指出）
- `--force` 只 ignore manual-mode / interval gate，**不繞 dedup**（這次仍 released 0）。
- 若 force 真的推出，等於**強推 arc 重複文章**給讀者 → 違反內容品質（Mission #1）。
- **副作用**：release 成功會 `update_last_released=True` → reset `last_released_at=now` → 打亂正常 180min cadence（用戶洞察正確）。
- 結論：force 治標且有害，廢棄為 remediation 手段。

## 鎖機制再檢討（2026-06-24 workflow 驗證更正 — 推翻原 framing）
原 plan（及當下給老闆的口頭分析）把 `release_dedup_skipped` 當「鎖+等 review」是**誤讀**，據 `content.py:863` 殘字註解「left as draft for review」。實際 code `content.py:244-253` 已於 **2026-06-23 boss throughput incident**（「可以發文了嗎」）後把它從 21天 dedup-window 改成 **2天 anti-thrash COOLDOWN**：
- flag 是**純優化**（避免每次 release run 重評同一 near-dup draft），correctness 由 **LIVE dedup gate（narrative_cluster_filtered + Jaccard near-dup）每次對 current published 重查**保證，不是 lock。
- 老闆「鎖不合理」直覺對**舊的 21天 window** 正確 — 6/23 已修（縮為 2 天 + 解綁 window）。
- 「等 review」framing 站不住：cooldown 不需 reviewer。

**→ 真 root cause 不在 flag（已是輕量 cooldown），在生產端持續產 arc 重複**：每次 release run 重判重複 → 重標 flag → 2天 cooldown 對「持續重標」無防護 → pool freeze（code 註解自記「46/46 drafts flagged, 0 eligible」）。修法核心 = **生產端 pre-check（不產重複）**，flag 的 cooldown 設計 6/23 已合理、不需廢除。

## 三層重構方案
### 1. 底層邏輯 — 生產端 arc-dedup pre-check
- draft 生成（research milestone publish + refill_reader_facing_pool）產 draft **前**跑 `find_arc_duplicates`，命中既有文章/draft 的 arc → 不產（或改寫 fresh angle 才產）。
- memory `feedback_dedup_3_layers_mainthread` + refill 已有 arc-dedup pre-check；缺口在 **research milestone → article path**（autonomous research 直接發 draft，疑繞過）。需補。

### 2. 流程 — 被擋 draft 的退回機制（不無限積壓）
- `release_dedup_skipped` 連續 N 次（或 arc-dup 確定）的 draft → 不是留池重評，而是 **退回 rewrite queue（改 fresh arc）或標 deprecated**。
- 加 `release_dedup_skip_count`；超過 threshold → 自動 `blocked_reason=deprecated` 或派 rewrite task。

### 3. 架構 — dead-man remediation 改正當解
- 脫班 auto-remediation（`.claude/rules/alert.md`）由「force release」改為「**派 fresh-arc daily_article**」（產真新主題，非推重複）。
- alert body 建議行動同步更新。

## 廢棄面
- 移除 / 標記 `release-pool-by-settings --force` 作為脫班 remediation 的建議（保留 flag 供其他用途，但 alert SOP 不再建議）。

## 驗證 gate
- Regression：構造「draft 池全 arc-dup」場景 → 脫班 remediation 應產出 fresh-arc 新文章使 candidates > 0，而非 force 推重複。
- 不變式：`released > 0` 的文章 arc 不得與最近 N 篇已發佈重複（arc-dedup 在釋出端仍有效）。
- 池健康：draft 池 arc 多樣性指標（distinct arc / total）不得長期 < 閾值。

## 即時止血（正當，非 force）
派一篇 fresh narrative-arc 的 daily_article（真新主題，過 arc-dedup）解當下脫班；治本走上述三層。
