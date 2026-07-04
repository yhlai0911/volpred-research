# Refactor Plan — Release-Layer Deadlock（發文脫班 root cause）

**狀態**：**2026-07-04 ROOTFIX LANDED（code-level 真根因已修 + Codex CONDITIONAL_PASS findings 全解 + 17 tests）**。原 2026-06-24「診斷完成待實作」的三層 plan **在過去 10 天其實已陸續實作完成**（見下方「2026-07-04 更正」），持續脫班的真因是三層 plan **沒涵蓋**的一個 code-level bug + 一個 content-supply gap。

---

## 2026-07-04 更正診斷（老闆 telegram msg114「頭痛醫頭腳痛醫腳」觸發，取代下方 stale framing）

**關鍵更正**：refactor plan 原三層方案**都已實作**（不是躺 10 天沒動）：
- **Layer 1（生產端 arc-dedup）**：`publisher.py:1212` `publish_milestone` 已跑 `find_arc_duplicates`；`refill_task_pool` 有 arc-dedup pre-check。（arc-dup 在 publish 端為 **WARN-only**，2026-06-23 從 hard-block 降級；擋在釋出端。）
- **Layer 2（blocked-draft 退回）**：`content.py:851/1329/1335` `_next_release_audit_skip_count` + `_RELEASE_AUDIT_MATERIALIZE_THRESHOLD` → skip N 次自動 materialize rewrite/deprecate audit task。（實測 draft `mile_30438396` skip=3。）
- **Layer 3（drought remediation → fresh-arc）**：`remediate_publish_drought.py:191` 已用 `refill(reader_facing_only=True, emergency=True)` 補 fresh reader task，非 force-rehash。

**三層都在、drought 卻仍發生** → 這正是老闆「疊了 N 層仍頭痛醫頭」的真相。真因是：

### 真根因 A（code-level bug，已修）— proactive draft-floor 對 releasability 盲
`continue_task_dispatch.py::_draft_pool_deficit()`（2026-07-01 建的 proactive 池 floor）用 **原始 `status=="draft"` 計數** 判斷是否 refill。當池裡有 6 篇 draft 但 **全是 arc-dup / dedup-flagged（release 端 eligible=0）**，舊 code 讀 draft_count=6 ≥ FLOOR(6) → deficit=0 → **proactive refill 不觸發** → cadence 一篇都釋不出 → drought。07-03 log 坐實：`[release_drought] blocked_pool=6`；07-04 live 坐實：`pool_counts: draft=6, dedup_flagged=6, eligible=0`。
**修**：`_draft_pool_deficit` 改用 release path 自己的 post-dedup `eligible` count（`preview_release_pool_by_settings().pool_counts.eligible`，single source of truth、零 drift、anti-stacking 不疊新 gate）+ in-flight `daily_article` 數（防 refill pile-up）。fail-open 回退 raw count（Codex finding：preview raise 也要降級 raw count，不可回 0）。

### 真根因 B（cure 端 masking，已修）— refill 用 experiment fallback 遮蔽 drought
`_maybe_refill_draft_pool` 呼叫通用 `refill()`（非 reader_facing_only）；當 reader-K 文章候選耗盡，refill fallback 到 `task_type=experiment` 並回 `added>0`「成功」，但 experiment task **不會變成 releasable draft** → deficit 沒關、drought 續。
**修**：proactive refill 改 `reader_facing_only=True`（對齊 Layer 3）。reader 候選耗盡時**誠實**回 `added=0, reason=no_new_candidates`，surface 真正的 content-supply gap，不被 experiment 遮蔽。

### 殘餘真因 C（content-supply，未修，spec 給後續）— reader-K 文章候選池耗盡
Fix A/B 落地後 live run 顯示：`reader_facing_only` refill 回 `added=0`（K1513/K1611/K1572… 全 arc-dup）。**平台已發太多 research 文章，research backlog 產不出每日 6 篇 fresh-arc reader 文章**。這不是 release-layer bug，是**內容供給**問題。
**Spec（後續 platform_ops）**：reader-K 池乾時，refill/生產應轉向**結構性 fresh 來源**——`event_article`（經濟行事曆 CPI/NFP/FOMC/財報，永不 arc-saturate）、`trending_repost`（時事）、`member_qa`。即 `_maybe_refill` 的 `refill_reader_facing_pool.refill_event_candidates` 路徑應在 reader-K 耗盡時優先觸發，把 fresh event/trending 排入生產。

---

<details><summary>原 2026-06-24 診斷（stale，保留供 audit；上方 2026-07-04 更正為準）</summary>

**狀態（原）**：診斷完成，待實作。2026-06-24 由發文脫班 CRITICAL 觸發。
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

</details>
