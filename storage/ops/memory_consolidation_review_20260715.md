# Feedback 記憶整併審查 — 2026-07-15

**任務**：`dreaming_memory_hygiene_consolidation_review`（P3, source=dreaming, 月度 cadence）
**觸發**：dreaming 連續 16 晚偵測 `feedback_*` 記憶數 ≥ 45（門檻）。實測 98 條 feedback / 137 總條目。
**對象**：`~/.claude/projects/-Users-yhlai0911-volpred-research/memory/`（每 session 載入 context 的操作記憶）
**性質**：propose-only（dreaming 不自動改；接手 agent 判斷）。本文為**提案 + 執行就緒計畫**，未在背景 fire 單方刪改（見 §6）。
**執行者**：hourly-19-slot2（ci_red fire 期間，ci-red 修復由 slot-1 認領，本 slot 轉做此餓死任務）

---

## 1. 摘要與核心發現

98 條 feedback 記憶可歸為 10 個主題群。**但「條數 ≥ 45 → 該整併」這個 heuristic 對本記憶系統是錯的度量**：

- 這套記憶的健康規模天生就 > 45（每個 boss 糾正／每個事故都沉澱一條），且會**永久停在門檻之上**（dreaming_review.py:119-130 的註解已自認此偵測「structurally near-permanent」）。
- 更關鍵：**重疊不等於浪費**。約半數 feedback 記憶是「行為守則」（act / finish / verify / 不 deflect），彼此重疊是**刻意的防禦縱深**——`feedback_fix_verify_then_report` 自載「記憶存在但沒擋住行為」，同一模式**一天內被老闆糾正兩次**（msg 736→796）。對這類，合併＝削弱本來就不夠的約束力。

因此本審查的建議是**分類處理**，不是齊頭砍量：
- **可整併群**（真程序冗餘、已有 skill/rules 承載 → 記憶只需保留事故錨點）：FB 發佈群、部分 email/report 群。
- **不可整併群**（行為守則，重疊即強化）：finish/act/alert 群 → 維持現狀。
- **度量修正建議**：把偵測從「raw count ≥ 45」改成「語意重疊比率」或加「last-reviewed 30 天 cooldown」，否則每晚重報無益（§5）。

---

## 2. 主題群盤點（98 條 → 10 群）

| 群 | 主題 | 代表記憶 | 條數 | 整併傾向 |
|----|------|----------|------|----------|
| A | reader-facing 內容品質/查重 | use_anti_ai_style, reader_facing_3canon, dedup_3_layers_mainthread, narrative_arc_dedup, website_article_quality_4dim, content_quality_patrol_gap, lazypack_infographic, digest_theme_first, recycling_is_release_layer | ~9 | 局部（dedup 兩條可併） |
| B | **FB 發佈** | fb_personal_account_chrome_only, fb_dual_publish_precheck, fb_opening_no_friend_asked, fb_post_idempotency_guard, boss_report_no_fb_handback, fb_link_in_first_comment | 6 | **高（6→1~2）** |
| C | **finish / act / 不 deflect（行為守則）** | finish_task_before_standby, fix_verify_then_report, repeated_done_question_means_finish_now, dont_deflect_act_on_repeated_complaints, proactively_complete_red_alerts, alerts_auto_act_not_suggest, alert_is_a_task_not_a_chore, dont_ask_do | 8 | **不併（防禦縱深）** |
| D | dispatch / pool cadence | one_dispatch_per_hour, dispatch_over_diversity, pool_fill_to_threshold, refill_check_saturation, continuous_work_and_read_mail | 5 | 低 |
| E | git 安全（multi-slot / worktree） | hermetic_git_in_tests, autocommit_poisons_before_after, parallel_impl_and_worktree_liveness, no_cd_into_worktree_before_merge, worktree_stale_base_extract_by_path, snapshot_before_refactor | 6 | 低（各為不同地雷） |
| F | 論文 review | paper_multi_round_review, paper_cross_paper_meta_eval, paper_autonomy_optimize_acceptance, 3model_review_discipline | 4 | 低 |
| G | skills 治理 | skill_autonomy, skill_structure, skill_format, self_revise_operating_docs | 4 | 低 |
| H | docs/CLAUDE.md 瘦身 | claudemd_keep_inline, progressive_disclosure, keep_concise_mnemonics, path_narrowing_audit | 4 | 低 |
| I | boss 溝通 / email / telegram | plain_language_boss_facing, answer_first_then_act, final_text_after_schedulewakeup, email_on_major_decisions, decision_email_html_form, autonomous_loop_email_summary, telegram_emoji_formatting, structured_stage_report_format, cross_machine_file_links | 9 | 局部（email 兩條可併） |
| J | 研究嚴謹 / 方法 | research_rigor, hedging_vs_trading, session_close_assumption, session_boundary_forecast_timing, long_sample_period, 3spec_disambiguation | 6 | 低（各為不同方法點） |

其餘（~30 條）分散於 skill/工具/流程細節，重疊低，維持現狀。

---

## 3. 建議整併（依信心排序）

### 3.1 FB 發佈群（B）— 6 → 1~2　**信心：高**
6 條的 actionable content 已被 `.claude/skills/fb-publishing/SKILL.md` + `trending-repost/references/fb-ivanlai-tone.md` 承載（grep 命中 first-comment / idempotency / precheck / CDP / chrome 共 24 處）。違反 `feedback_skill_structure`（方法論放 skill，不散在記憶）。
- **保留事故錨點**：每條的「Why + boss 原話 + 事故日期」是規則的正當性來源，不可丟。
- **執行計畫**：先逐條核對 6 個規則是否**完整**在 skill 內（chrome-only / 發前查重 / 開頭禁句 / 冪等 guard / 正文不放連結 / boss report 不 handback）；補齊缺口後，把 6 條**收斂成 1 條** `feedback_fb_publishing_lessons.md`（保留 6 個事故錨點 + 一句「操作細節見 fb-publishing skill」），刪除其餘 5 個檔並更新 MEMORY.md 索引與跨檔 `[[links]]`。
- **注意**：改動 fb-publishing skill 者，依 `feedback_skill_autonomy`（改既有 skill 要寄信）須 email 老闆。

### 3.2 dedup 兩條（A）— 2 → 1？　**信心：中**
`feedback_dedup_3_layers_mainthread`（主線程 3-layer 查重）與 `feedback_narrative_arc_dedup`（同 arc 換殼也算重複）是同一查重流程的兩面。可併為一條「寫作前查重」但**保留 arc 判準的具體例子**（「銅博士 vol」=「銅銀吃不到 VIX 紅利」）。低優先。

### 3.3 email 兩條（I）— 2 → 1？　**信心：中**
`feedback_email_on_major_decisions`（重要決策後主動 email）與 `feedback_decision_email_html_form`（決策 email 用 mailto 不用 form）可併為一條 email 規範。低優先。

---

## 4. 明確**不建議**整併

**C 群（finish/act/alert，8 條）維持現狀。** 理由：
1. 每條綁定**不同事故 + 不同觸發語**（排 wakeup 待機 / 回報未修問題 / 被連問 done / 反覆抱怨 / 紅色 alert / alert body 措辭 / alert=task / 問選擇題），是彼此獨立的 guardrail。
2. 這是**被反覆違反**的行為模式（`fix_verify_then_report` 一天內糾正兩次、`dont_ask_do` 被重申三次）。冗餘＝強化，正是需要的。
3. 合併成一條抽象原則會**弱化具體觸發**，讓未來 session 更容易漏觸發。

E/F/G/H/J 群同理：條目雖同主題，但各自是不同地雷/方法點（git 六條分別對應 hermetic test / autocommit / liveness / cd-before-merge / stale-base / snapshot 六個不同事故），無真冗餘。

---

## 5. 根因建議：修偵測度量，止住每晚重報

`dreaming_review.py:586` 用 `len([ln for ln in MEMORY.md if "feedback_" in ln]) >= 45` 觸發。此度量對「天生 >45 且該保留」的記憶系統會**永久為真**（作者註解已承認）。建議二選一（本文只提案，未改 code）：

- **(A) 改量重疊而非量條數**：偵測「同主題群條數 ≥ N 且 skill/rules 已承載」才提案（真冗餘信號），而非 raw count。
- **(B) 加 cooldown**：記錄 `last_consolidation_review` 時戳，30 天內不重報（符合「月度 cadence」的設計本意）。目前完成一次 review 後隔晚就再報，等於 cadence 沒落地。

建議採 (B)（最小改動、直接對齊月度語意）。可另開 `platform_ops` followup 修 `dreaming_review.py`。

---

## 6. 為何不在本 fire 直接執行刪改

1. **對象是每 session 載入的操作記憶**，且本機當前有並行 session（slot-1 同時跑 ci_red）——刪檔/改 `[[links]]` 會即時影響所有 live session 的 context。屬「難回復 / 外溢他人」動作，harness 規範建議先確認。
2. **propose-only 設計**：dreaming 明定不自動改，接手 agent 判斷「是否 + 何時」執行；本任務定義的產出就是 review。
3. **FB 整併需先驗 skill 覆蓋 + 安全 rewire 跨檔 links**，是一個值得聚焦的子任務，且涉及改 skill → 依 `feedback_skill_autonomy` 需寄信老闆。

**建議 next actions**（可各開 followup）：
- `platform_ops`：執行 §3.1 FB 6→1 整併（先驗 skill 覆蓋、寄信、snapshot、rewire links）。
- `platform_ops`：§5(B) 給 dreaming memory_hygiene 偵測加 30 天 cooldown。
- §3.2 / §3.3 低優先，可併入下次月度 review。

---

_產出：hourly-19-slot2 · 2026-07-15 · 不改記憶檔本體（propose-only）_
