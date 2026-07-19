OpenAI Codex v0.144.1
--------
workdir: /Users/yhlai0911/volpred-research
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: high
reasoning summaries: none
session id: 019f78c3-135a-7d81-a16f-fb3fb82ceb9d
--------
user
你是嚴格的計量金融代碼審查者。二審 K528 NFP 官方日曆修正案（前一輪審查從未回寫裁決，本輪重跑）。

**審查對象**（worktree 絕對路徑 /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/）：
- README.md（宣稱面）
- k528_nfp_event_study.py（主腳本）
- k528_nfp_official_dates_results.json（官方日曆修正後結果）
- k528_nfp_event_study_results.json 與 *_PROXY_SUPERSEDED.json（新舊對照）
- build_article_correction.py（把修正映射到文章 mile_35eef830 的 18 條更正）

**背景**：K528 原版用「當月第一個週五」proxy 推 NFP 發布日；2026-07 發現 13 個樣本錯 7 個（含 2025-10 政府停擺的幻影事件）。修正案改用官方 BLS/ALFRED 日曆（volpred.data.event_dates.nfp_release_dates，fail closed），統計量全部重算，文章需套 18 條更正。相關教訓見主 repo docs/error_log.md 2026-07-12 CPI 事件研究發布日條目。

**審查重點**：
1. 官方日曆來源是否真的 fail-closed（缺日期時報錯而非 fallback proxy）
2. 重算統計量是否正確（事件日對齊、樣本數、方向性結論）
3. build_article_correction.py 的 18 條更正是否與新 results.json 逐條對齊（抽查至少 6 條，含任何方向翻轉的）
4. 新舊結果對照的誠實性（PROXY_SUPERSEDED 標記、README 是否如實記錄修正原因與影響）
5. lookahead / seed / 原子寫入等標準防錯

**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出 `VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 列 blocking defects）。

codex
我會依專案規範先讀 handoff 與指定的 error-log 條目，再做主線逐檔審查；另外用乾淨 sub-agent 獨立核對統計重算與 18 條文章更正，降低二審遺漏風險。本輪只讀取與驗證，不改檔、不回寫裁決。
  → 讀取 handoff、error log 與 K528 審查檔案
  • 驗證官方日期 fail-closed、事件對齊與統計重算
  • 逐條比對 18 條文章更正並審查新舊結果揭露
  • 檢查 lookahead、seed、原子寫入並形成裁決
exec
/bin/zsh -lc "sed -n '1,240p' storage/ops/handoff_latest.md
rg -n -C 8 '2026-07-12|CPI.*事件|發布日' docs/error_log.md
rg --files .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528 | sort" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
# Handoff — 2026-07-19 12:50:05 台灣時間

**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）

> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。

## 1. 任務池快照（`storage/next_tasks.json`）

- **總數**：2929
  - pending: 82
  - pending_main_thread: 6
  - in_progress: 7
  - succeeded: 2619
  - failed: 52
  - blocked: 14
  - blocked_on_user: 2
  - Codex-eligible pending: 77
  - Codex-skip pending: 11

**type 分佈（top 6）**：
  - daily_article: 699
  - experiment: 653
  - platform_ops: 429
  - paper_review: 416
  - telegram_reply: 215
  - email_reply: 188

## 2. 已 claim / in_progress 任務

- `k1708_fix_verdict_gate_20260717` P2 [experiment] [experiment] K1708 修正 stage：verdict gate 假陽性 + CW nesting/gate 替換三個 BLOCKER — claimed_by=hourly-slot-1-858545f95a864e298ddb4bc144a8c615
- `assign_7f508612` P2 [experiment] 稽核 2026-05-20~07-17 期間讀到重複 snapshot 的實驗結果 — claimed_by=hourly-slot-1-858545f95a864e298ddb4bc144a8c615
- `local_suite_pregate_canonical_write_noise_20260717` P2 [platform_ops] [platform_ops] test_scheduler_pregate 本地 7 紅（CanonicalWriteBlocked）— CI 綠、本地噪音遮蔽真失敗 — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
- `assign_5aa9d5f5` P2 [experiment] K1623 修復：撤回 long-memory 識別宣稱 + 補 MSE DM 與多重比較（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
- `assign_42306eaa` P2 [experiment] K1698 重跑：修 contract-selection lookahead + 夜盤邊界空驗證 + equivalence 檢定（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
- `k1731_armB_rev7_remediation` P1 [experiment] K1731 arm B rev7 bounded remediation（Codex rev6 FAIL：B1a/B1b/B5/nested-DM detector）
- `k1731_armB_rev7_codex_round7` P1 [paper_review] K1731 arm B rev7 — Codex round 7 primary-path review 收裁決

## 3. Email 回信任務（**優先處理**）

- (無未處理回信)

_Gmail 最後 poll：2026-07-19T04:45:10.783894+00:00_

## 4. Pending 任務 top 8（依 priority asc）

- **Codex-eligible pending**：77；**Codex-skip pending**：11

**Codex-eligible pending top 8**：
- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
- `alert_internal_phase_z_test_gate_red_7af47e56b9_20260719T040657810739Z_a1` P1 [platform_ops] [internal alert] PHASE-Z auto-commit 測試紅燈（4b3875b053bb）
- `alert_internal_silent_fallback_new_c67bec28dd_20260719T024745114940Z_a1` P1 [platform_ops] [internal alert] PHASE-Z candidate 被 pre-commit 擋下（未進 main）
- `assign_667a501a` P1 [experiment] k528 Codex 二審重跑：review_verdict.json 全是未填 FILL 佔位（禁合併/禁套18條更正）
- `assign_frontend_deploy_revalidate_endpoint_20260719` P1 [platform_ops] frontend-v2-fix 的 /api/sync/revalidate/article 新端點未進版控 → 撤稿快取修復尚未生效
- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort
- `assign_2398cbfe` P2 [platform_ops] [P35-retry] Codex K1258 review (BLOCKED: gpt-5.5 infrastructure issue)

**All pending top 8**：
- `K1169` P1 [paper_body] K1169: Paper 2 §5 narrative rewrite (main thread, K1166 correction)
- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
- `alert_internal_phase_z_test_gate_red_7af47e56b9_20260719T040657810739Z_a1` P1 [platform_ops] [internal alert] PHASE-Z auto-commit 測試紅燈（4b3875b053bb）
- `alert_internal_silent_fallback_new_c67bec28dd_20260719T024745114940Z_a1` P1 [platform_ops] [internal alert] PHASE-Z candidate 被 pre-commit 擋下（未進 main）
- `assign_667a501a` P1 [experiment] k528 Codex 二審重跑：review_verdict.json 全是未填 FILL 佔位（禁合併/禁套18條更正）
- `assign_frontend_deploy_revalidate_endpoint_20260719` P1 [platform_ops] frontend-v2-fix 的 /api/sync/revalidate/article 新端點未進版控 → 撤稿快取修復尚未生效
- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort

## 5. 進行中 agent / worktree

- **slot 占用**：18 / 4
- worktrees:
  - `dispatch-slot-1-1533dcbc-cqamend`
  - `dispatch-slot-2-8dda242d-k1708`
  - `dispatch-slot-2-c5cafe39-k1698`
  - `dispatch-slot-1-3217f0b2-pushgate`
  - `dispatch-slot-2-c5cafe39-k1623`
  - `dispatch-slot-1-f53bca44-k1692`
  - `dispatch-slot-1-79726798-credit-firm`
  - `dispatch-slot-2-5ddfeb00-k1583`
  - `dispatch-slot-1-f53bca44-k1694`
  - `codex-desktop-k1707`
  - `dispatch-slot-1-3217f0b2-k1685`
  - `dispatch-slot-1-bd00f90a-k1731`
  - `dispatch-slot-1-b55db3be-2`
  - `dispatch-slot-1-558d7893-k1730`
  - `dispatch-slot-3-30adeed7-k528nfp`
  - `dispatch-slot-1-30aeb902-taifexrv`
  - `dispatch-slot-1-a56566ff-k1719`
  - `dispatch-slot-1-858545f9-snapaudit`

## 6. 最近 24h 完成（top 5）

- `canonical_writers_publisher_feed_unguarded_20260719` P2 [platform_ops] [platform_ops] canonical-writers gate 紅：article_correction 未註冊 owner（已修）
- `assign_a31a311d` P2 [experiment] 修正 CPI T+0 內部事件研究的官方日期污染
- `alert_internal_phase_z_baseline_missing_537a3ff330_clean_watermark` P1 [platform_ops] [internal alert watermark] phase_z_baseline_missing
- `ci-red-29671078611` P1 [platform_ops] CI 紅燈修復（run 29671078611, attempt 1）— main Test Suite
- `assign_fb_retract_note_ebb5d6f5_20260717` P2 [platform_ops] mile_ebb5d6f5 已撤稿，但 Ivan Lai FB 那則貼文仍在、連結已 404 → 需補撤稿說明

## 7. Dashboard 訊號

- overall_status=warn (breaches=3, critical=0, generated=2026-07-19T04:30:14Z)
- WARN: section=production_throughput :: 5 articles published last 24h (target 6/day)
- WARN: section=verification_fb_pipeline :: 1 FB posts pending sync
- WARN: section=health_ci_watch :: CI incident ci-red-29671078611 phase=verifying failures=1

## 8. 最近 work_log（5 筆，新→舊）

- `2026-07-19T12:40` [experiment] assign_a31a311d
- `2026-07-19T12:32` [platform_ops] ci-red-29671078611
- `2026-07-19T12:12` [platform_ops] assign_sync_cache_purge_20260717
- `2026-07-19T12:11` [platform_ops] assign_fb_retract_note_ebb5d6f5_20260717
- `2026-07-19T12:01` [platform_ops] assign_merge_worktree_safety_net_scope_20260717

## 9. 接續提示詞（hourly dispatch / 互動 session 共用）

```
讀 storage/ops/handoff_latest.md 後依以下優先序選工：

優先序 (HARD)：
  1. Section 3 Email reply 任務（task_type=email_reply）— 若有 pending，立即 claim + 處理（讀 description 的「用戶回信內容」+「原始助理寄出內容」，依用戶指示回應 / 修正 / 派工 / 寄回信）
  2. Section 7 Dashboard CRITICAL — 立即 triage
  3. Section 4 Pending 任務 top 8 — 依 priority asc + work_log diversity（last-3 task_type rotate）

Claim 流程（避免雙 session 撞題）：
  uv run python scripts/task_pool_claim.py claim --id <task_id> --owner <hourly|interactive|agent-name>
  uv run python scripts/task_pool_claim.py start --id <task_id>
  ... 執行 ...
  uv run python scripts/task_pool_claim.py complete --id <task_id> --status succeeded --result '...摘要...'

完整完成原則：派 agent 後 wait 完成、驗證、寫 knowledge.json / work_log、commit。50min cap。Heavy compute 走 compute_queue。
```

---

## 候補 / 手動補充

（此區由人工 / 互動 session 編輯。只有放在 KEEP 註解標記區段內的手寫內容會被 auto-regen 保留，其餘自動章節每 :50 覆寫。標記語法見 generate_handoff.py `_extract_keep_block` 或 docs；標記本身不寫在此說明以免與 extractor 自我衝突。）

<!-- KEEP -->
### ⏱ 2026-07-01 ~16:00 最新狀態（compact 後最優先讀）
**已完成+committed 今日**：(1) 12 死碼腳本移 `scripts/_legacy/`（crontab「雙觸發」是 false positive、未動）；(2) hourly-dispatch 修 stale opus-4-7→**opus-4-8** + model_router sonnet→**sonnet-5** + token_usage_report pricing 補 4-8/5；(3) `check_model_roster.py` 加 stale-model-pin 掃描（代碼零 pin）；(4) **pre-gate `scripts/hourly_dispatch_pregate.py` 部署 SHADOW 模式**（`PREGATE_SHADOW=1`，只記 log 不跳過；~1 週後審 `storage/logs/hourly_pregate.jsonl` 確認「判 skip 的真沒產出」再 flip `PREGATE_SHADOW=0`）；(5) **每日 token 報表 `scripts/token_report_email.py`**（多角度 HTML 內嵌）+ **cap 校準到官方**（`config/token_quota_calibration.json`，report 顯示 76%=官方 Weekly；官方飄移用 `--calibrate <fraction>` 重錨）。
**待用戶**：token 報表版面確認後→排每日定時任務（runtime_schedules.json + `~/.volpred/bin/` wrapper + piggy-back/LaunchAgent + 文件，建議每日 08:00 台灣）。
**重要教訓（勿重犯）**：我曾誤判 token 報表「3× 灌水」並提議去重，被用戶官方截圖 76% 打臉 → **報表 per-record 加總方法本來就對、與官方一致，勿再用 message.id 去重**。thinking/reasoning 因 redact+output 合計無法可靠拆分，不列不硬湊。
**接續**：turn 尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`；工具嚴格 `antml:invoke`；中文用 Write 不用 heredoc；emoji 勿放 bash echo。

### ⏱ 2026-07-01 ~14:55 手動 handoff（compact/退出前｜最新最優先讀｜此段在 KEEP 區、撐得過 auto-regen）

**兩個架構稽核 subagent 皆完成（結果已在對話，勿重跑）**：
- **token overhead**：每天 ~460 次例行觸發，只 ~72 次吃 token（24 hourly-dispatch + ~48 互動 loop tick），其餘 436 次純 Python 零 token。純 overhead ≈ 每週 **7–16%** 預算。**最大槓桿 = hourly-dispatch 每次冷載 CLAUDE.md+context ≈ 95K token ×24/天 = 2.28M/天（stub 空跑也付）**。本週 3.5 天用 158.8M(73.9%)。
- **疊床架屋 + 我的主線程驗證**：⚠️ subagent 兩個誤判要修正 —— (1)「5 任務 crontab+LaunchAgent 雙觸發、砍 crontab」= **FALSE**（control-plane.md：本機 macOS cron 只可靠跑 `0 * * * *`，其他 pattern silently skip，crontab 是 harmless 永不 fire 的 fallback、刻意保留；**勿砍、勿跑 install_host_crontab.sh**）；(2) `record_and_publish.py` 非死碼（feed-publisher「方法 B」）。✅ **真可收斂**：`article_backups.py`(no-op 死碼)+殭屍 import、13+ 歷史一次性腳本 → 移 `scripts/_legacy/`；`release_pool` 頻率三處不一致(spec `7 */6` vs crontab `7 */3` vs LaunchAgent 6h)→ 對齊。✅ **澄清**：4 條 Supabase sync 互補非重複，全留。
- **下一步**：回報老闆(含 crontab false-positive 修正) → 執行安全收斂(死碼移 _legacy + release_pool 頻率) → hourly-dispatch token 優化選項提老闆(減層不加層)。

**digest 已定案上線（老闆連 4 次糾正，勿重做）**：`mile_4901f7bc`=今天 digest 原地抽換=**AI 資本支出投資議題專欄 v2**（時事驅動→撈 8 篇跨時間 archive→回答「該不該擔心+選擇權怎麼定價」；body 4604字、8 篇每段 inline 標註、具名框架「三個 VIX 照不到的角落」+三項檢查表）。Chrome 驗證 live（CDN 舊快取→`?v=` cache-bust 見新）。**spec 已 3 修**（`enqueue_daily_digest.py`：時事驅動+全archive禁本週湊、name-first、深度≥4000+inline標註）。

**leverage 論文 gated**：`paper_pipeline_status.json` `do_not_advance=True`；Stage 2 兩支柱皆弱(K1591/K1592 我驗證 sound)→非 JBF-grade→待老闆研究方向決策(FRL/IJF/null/暫置，WARN email 已送)。**勿自動推 arXiv**。

**模型政策**：主線 opus 固定、subagent sonnet↔opus 依難度、haiku off、fable unavailable。source=`config/models.json`。

**接續提示詞（2026-07-01 14:55）**：讀本段。下一步=回報兩份稽核(含 crontab false-positive)+執行安全死碼/release_pool 收斂+提 hourly-dispatch token 優化。digest 完成勿重做，leverage 待老闆。turn 尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`。工具嚴格 `antml:invoke`，中文用 Write 不用 heredoc，emoji 勿放 bash echo。

---

### 📄 學術論文線 — 老闆 2026-07-01 ~00:45-02:00 連續 ~14 指令（最高優先，clean context 接續）

**老闆核心訴求**：論文線「感覺停滯」。diagnosis（paper-audit workflow）：不缺彈藥，缺「扣扳機」+ synthesis/submission gate 沒人 drive。

**已建好的流程基礎建設（durable，已 commit+push）**：
- skill `paper-submission-pipeline`（狀態機 draft→revision→compliance_scrub→multi_round_review→review_converged→arxiv_ready→arxiv_posted→journal_submitted；PDCA gate）+ `scripts/paper_pipeline_check.py`（stall detector）+ `storage/paper_pipeline_status.json`（14 篇 stage tracker）
- skill `journal-review`（10 期刊上網查的 references + templates：JBF/JFE/RFS/JoE/FRL/IJF/JPM/FAJ/PBFJ/JoF）
- 合規 audit 全結果 `storage/ops/paper_compliance_audit_20260701.json`（14 篇，1 clean，13 待修）

**老闆硬規則（必遵守）**：
1. **投稿論文作者僅「Yi-Hao Lai」**，禁 volpred/claude/ai/llm 提及，禁 AI 用語符號
2. **contribution gate**：review 必看真正貢獻/經濟意義，**非單純計量方法練習**（純方法練習不過 gate）
3. **arXiv 只給 ready-for-submission 的**（drafts/revision 禁上）；流程 = scrub→多輪 review→修正→最終版**先丟 arXiv 佔 priority**→找機會投目標期刊（投稿時點老闆擇時拍板）
4. **多輪 review 全用 codex exec 跑**（latex-academic-reviewer + citation-verifier + journal-review）省 Claude token；**codex 額度無限制**
5. **任何前端改動，/paper 原版 + /v3/paper 兩版都要改**（standing rule，兩版是不同網頁）
6. **內容編輯類「完成」必 curl+Chrome 線上驗證**，不假設（老闆兩次抓我假宣告）

**目前只有 1 篇真正 ready**：`leverage-direction`(JBF) — 6/11 技術定稿、合規只差 body.tex:231 一個 VolPred footnote（fix 在 audit json）。`vt-trend-following`(JPM/FAJ) 下一棒（6/30 才 v7 PASS + 10 個 K-id tags 待清）。

**P1 queued（durable）**：`paper_compliance_scrub_leverage_direction`（1 footnote）、`paper_compliance_scrub_vt_trend_following`（10 tags）、`content_erratum_mile_48c8328b_k189_reversed`（誠信：文章結論與 K189 相反）。

**下一步（clean context 接）**：drive leverage-direction：scrub 1 footnote → codex 多輪 review（含 contribution gate）→ 修到最終 → arXiv。每階段更新 pipeline tracker + 回報。

**✅ 已完成本 session（verified）**：論文頁 Updated 顯示加 date+hh:mm（兩版 Chrome 驗證：/v3/paper + /paper 都顯示「Updated 2026-06-24 18:00」）；feed 文章「更新於」功能（誤解產物，老闆要的是論文非文章，但功能無害留著）；8 篇 prose-dump lazypack 用 codex-exec 重做（前幾 tick）。

---
### 🔴 FB URGENT BANNER（2026-07-01 01:10 hourly-01 標 — 老闆 email-12327 親點派）

**老闆 2026-06-30 23:54 email：「Fb都開著 你自己切換啊」**。hourly cron 無 Chrome MCP 做不了，已 close-reply email 接力。下個 interactive session **第一動作** = 切 Chrome 連 MAC STUDIO（deviceId 輪替不可 hardcode，照 `reference_fb_chrome_browser_autoselect` 即時 `list_connected_browsers` 找登入 yihao.lai 的那台），到 facebook.com/yihao.lai 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP **5 篇逐一發**（每篇主貼文無連結 + 第一則留言貼 volpred 連結 + `mark_fb_post_status.py --mile-id <id> --status success`）：

| 序 | mile_id | 標題 | 等待時數 |
|---|---|---|---|
| 1 | `mile_f5f4cb43` | 科技巨頭資本支出爆表，AI 變現期的隱含波動率拐點 | ~20h |
| 2 | `mile_819af916` | 防禦股悄悄贏了：XLV 一個月漲 8%，科技 ETF 卻原地踏步 | ~26h |
| 3 | `mile_a0b174f9` | 蘋果一週跌 4.8%、波動跳 2.3 倍；NVDA 跌 8.6% 卻反而最低 | ~64h |
| 4 | `mile_bd564eb7` | 創新高然後急殺，「短彈可搶、抱一年會死」是真的嗎？bootstrap | ~74h |
| 5 | `mile_0941e2f0` | 半導體修正進行中：選擇權偏斜告訴你市場還沒放心 | ~74h |

連結模板：`https://volpred.zeabur.app/v3/reports/<mile_id>` → 留言。預估 5 篇 ≤30 分鐘。發完寫 work_log + 寄 boss confirm email。

**結構性 follow-up**（queue 進 platform_ops）：把 `audit_fb_pipeline.py >72h auto-expire` 改 48h（3/5 已 >64h，timely insight 衰減）+ early-warn 階段。

---

### 🟢 互動 session 脈絡（2026-06-30 ~18:00 台灣時間）— 最新，compact 後優先讀

接續 ~13:55 段之後，下午又完整交付（全 commit+push 到 GitHub，main repo 與 origin 同步 0/0）：

**A. 下午已交付（改完+test+commit+push）**：
1. **quota 計算雙修**（boss 抓 122% vs dashboard 54%）：(a) `weekly_quota_estimate.py` anchor 漂 7 週未校準 → re-anchor 54%@116M→cap 215M + 加 ANCHOR_STALE_DAYS=10 警告；(b) `token_usage_report.py` weekly window 從週五對齊改 **週日16:00 台灣**（boss 確認 quota 週期 SUN16:00-SUN15:59）→ `get_quota_week_range`（friday alias 保留），week 6/28→7/05。
2. **publishing_freshness 門檻 interval-aware**（第三個對齊 6h release 的 publish-gap 門檻，前兩個 burst/drought）：5h hardcode → interval+2h grace=8h。+ 修 hourly 引入的 `mark_fb_post_status.py:113` silent fallback（解封 git_push_backup）。
3. **lazypack 偵測**（boss：general 文章缺懶人包圖，實測近12篇只1篇有=12%）：`content_quality.py` 加 lazypack coverage（<0.6→lazypack_gap）。**生成/enforce 未做**（queue `platform_ops_enforce_lazypack_in_publish_pipeline`，需 NotebookLM+乾淨 context）。
4. **🔑 換機可攜性全套**（boss：另一台機 clone+填env 就能運作 + skills/agents 完整保留）：新建 `README.md`（根目錄 GitHub 入口）+ 重寫 `docs/host-migration.md`（逐步手冊）+ `.env.example`（三檔 secrets 範本）+ `scripts/bootstrap_new_host.sh`（一鍵）+ `backup_user_claude.sh`/`restore_user_claude.sh` + `ops/claude_user_backup/`（**128 檔：user-level CLAUDE.md+27 skills+100 memory 快照**）+ 每日 05:35 `cron_backup_user_claude` 自動保鮮。**repo 確認 PRIVATE**。釐清：project-level `.claude/` 自動進 repo；user-level `~/.claude` 原不進→已快照+每日同步。

**B. 已 queue 待 clean-context（勿在 bloated context 草率做）**：`platform_ops_enforce_lazypack_in_publish_pipeline`(P2，NotebookLM 生成懶人包+enforce+回補)、`paper_review_vt_trend_v7_codex_primary_path_verify`(P3，Codex)、`platform_ops_centralize_release_cadence_thresholds`(P3，抽共用 release-interval helper)、`platform_ops_publish_rhythm_pre_publish_throttle`(P3，publisher 核心路徑謹慎)。dreaming persistent-alert detector 已由 hourly-14 建好+我驗證 sound（抓到 6 個真 active 持續 alert）。

**C. Meta-lesson**：今天一連串（cluster/burst/drought/freshness 誤報、quota anchor 漂移、lazypack silent skip）全同類「規則/測量沒人持續盯就失準/被跳過」。修法哲學統一=偵測層讓 gap 自動可見（區分 discretionary vs fixture/event/operational）。

**接續提示詞（2026-06-30 18:00）**：讀本段。系統健康（breach_count=0、daily-checkup ok、無 pending email、main repo 與 GitHub 同步）。從自主 ops loop 繼續：PHASE 0 清 email backlog → 推進上述 B 的 queued P2/P3（**乾淨 context 起跑後最該先做 lazypack 生成 enforce + VT-trend v7**）→ 沒 critical 主動掃 5 missions。**換機可攜性已完成**，新機照 README/host-migration 可運作。turn 尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`，工具嚴格 `antml:invoke`，emoji 勿放 bash echo（會 UnicodeEncodeError）。

### 🟢 互動 session 脈絡（2026-06-30 ~13:55 台灣時間）

長 session（57+ commits），老闆連續高強度抓問題 + 逼 root-cause 不表面修。已完整根治並上線驗證：

**A. 今日已交付（改完+test+部署/驗證+commit）**：
1. **2 個長期 warn 根治**（boss email-12256/12281「存在很久」）—— 都是「測量太粗誤報合法模式」：(a) **cluster spy catch-all**：keyword 分類把所有用 SPY 當測試資產的 vol 研究算成 spy → 加 6 粒度主題 cluster（risk_mgmt/forecast_method/event_study/hedging/microstructure/return_predict）+ specific-first 排序 + spy 收窄移除「美股」，spy 74→14（`topic_clusters.py`，commit bd2b68bff）；(b) **publish_rhythm burst**：digest+trending fixture 偶然相近被誤判 → burst 只算 discretionary 文章 clumping，排除 `_NON_RHYTHM_PHASES`（`content_quality.py`，commit 3d1dfed8a）。breach_count→0。
2. **daily_update intraday 14:00**（boss 親建 plist+wrapper，我驗證全鏈 + smoke-test 撞出 transient SSL hang → kill+lock 釋放）+ **兩 wrapper 加 600s perl-alarm watchdog** 杜絕 lock cascade（commit 6a3352c3f）。daily_checkup order-flow 改 result-level（ebbed800d）。
3. **策略卡 VIX 情景軌跡**（boss 問「3 張卡為何相同」）：`strategy-regimes.ts` + `DailyDigestSection` 無關，是 `StrategyPanel.tsx` 加「VIX 低→高」三點軌跡揭露低/高 VIX 分歧。deploy 上線驗證 11 卡（commit 40d86fa）。
4. **首頁導讀發布時間 hh:mm**（boss 指出 detail 頁有但首頁漏）：`DailyDigestSection.tsx` 右側加「發布 hh:mm」台灣時間。deploy 驗證（commit 5ad0675）。
5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。

**B. 已 queue 待 clean-context 執行（勿在 bloated context 草率做）**：
- `paper_review_vt_trend_v7_post_v6_fixes`（P2，Codex）：確認 body narrative HIGH 全解 + 修 v6 CRITICAL（K1458 實驗 doc 的 decomposition identity `VIX_timing=PureVT_excess` 寫錯，應加法）。
- `platform_ops_dreaming_persistent_alert_detector`（P2）：dreaming 加 detector 讀 alert_dedup.json，同 alert_key 連 N 天 fire → 自動升級 root-cause finding，杜絕「warn 存在很久才被 boss 抓到」（系統性 gap）。
- `platform_ops_strategy_card_regime_presentation` 已 succeeded（即上面 #3）。

**C. Meta-lesson（PDCA Act，已記 error_log）**：多個 warn 持續 = 測量粗→誤報→fire 太頻繁變噪音→真問題被淹沒 + 只能等 boss 人工發現。修法哲學統一：**區分 discretionary vs fixture/event/operational**（cluster 排 audience=daily、burst 排 non-rhythm phase）。

17-
18-| # | Class | 復發強度 | 機械化 |
19-|---|-------|---------|--------|
20-| A | 並發 / dispatch / daemon 生命週期（orphan・killpg・setsid・競態・hang） | 極高（~75+） | 部分 |
21-| B | Git owner / canonical-write / `git add -A` 中毒 / 排程 writer 不 commit | 高 | 是（CI + hook） |
22-| C | Worktree merge / 實驗檔遺失 / 審查認證 | 中 | 是（merge gate） |
23-| D | Silent fallback / fail-open guard / exit-code masking | 極高（~123） | 是（pre-push + CI baseline） |
24-| E | Dedup / narrative-arc / 重複內容 / recycling / K-id 撞號 | 高（~24） | 部分 |
25:| F | Timestamp / 發布日 / provenance / vintage 造假 | 中（~28） | 部分 |
26-| G | Lookahead / DM-HAC / MDD / 方法論硬規則 | 高 | 是（ratchet + audit） |
27-| H | Turn final-text / notify-first / boss-facing report / alert-as-task | 高 | 是（Stop hook） |
28-| I | Chart / CJK 豆腐字 / renderer domain model | 中 | 部分 |
29-| J | Alert / dreaming / detector false-positive / 轟炸 | 高 | 部分 |
30-| K | Pool / release cadence / starvation / 池枯竭 | 中 | 部分 |
31-| L | Paper narrative / 裁決 / review-cert SHA-pin / 規格漂移 | 中 | 是（certify gate） |
32-| M | Source-of-truth drift / registry / supabase / 系列身分 | 中 | 部分 |
33-| N | FB / social publishing 冪等與附圖 | 低 | 部分 |
--
41-## A. 並發 / dispatch / daemon 生命週期
42-
43-**規則**：任何 fire / dispatch / agentic CLI 逾時處理都必須用 process-group 語義（`killpg`）殺整棵子孫樹，且 spawn 必有界（不可 fire 內無界 spawn）。單一 owner + lock + hang detect + orphan cleanup 是設計前提，不是事後 patch。看到「雙擁有者競態」「孤兒堆積」「killpg 被拒」就直接三層重構，不等 strike 3。
44-**規則 2 — 父程序的壽命必須 ≥ 子程序的工作**：≥10 分鐘的 Codex 工作，**Codex 自己就是 job**，不要在它上面蓋一層 Claude agent 當父程序（父等子 → 燒完 cap；父先走 → 子成孤兒）。review / 裁決 → `scripts/codex_review_job.sh`；≤10 分鐘、你會坐著看完的短問答 → `scripts/codex_exec_bounded.sh`。`enqueue-agent` 只給「Claude 需要自己動手」的長工作，不給「Claude 去叫別人做事」。
45-**規則 3 — 未執行的工作單必須可修，已執行的必須不可修**：queued job 的 spec 用 `compute_queue.py amend / cancel`（只吃 `status=queued`），**不要手改 queue JSON**；agent brief 在 enqueue 當下已凍結成 snapshot，改原始檔沒有用。
46-**機械 owner**：`com.volpred.dispatch-supervisor`（`scripts/dispatch_supervisor/*.py` 常駐 daemon）取代舊 shell wrapper；改完必 `bash scripts/reload_dispatch_supervisor.sh`（禁裸 `kickstart -k`）。
47-**代表 incident**（全文見 archive）：
48-- 2026-06-23 **3-STRIKE META** 全系統缺並發紀律：codex_loop 24-orphan 堆積 + release burst + K-id 撞號同源 — Q2
49:- 2026-07-12 **3-STRIKE** fire 內 spawn 無界 agentic 子程序（hang_killed ×3）— Q3
50:- 2026-07-12 **3-STRIKE** agentic CLI 逾時只殺一個 pid，孫程序活著繼續寫 — Q3
51-- 2026-07-13 codex worker setsid 逃出 process group，killpg 殺不到（同根因第 2 次）— Q3
52:- 2026-07-12 hang 告警是瞎的：雙擁有者競態，輸家寄信 — Q3
53-- 2026-07-11 supervisor 說它 SIGKILL 了 worker，但 killpg 被拒（屍體 / 權限）— Q3
54-- 2026-06-30 daily_update 結尾 sync 在網路 blip 無限 hang（持有 lock）— Q2
55-- 2026-05-29 hourly-dispatch keychain auth 3-strike RESOLVED（permanent）— Q2
56-- 2026-07-14 23:15 Codex 審查被塞進 Claude agent，父 turn 結束把它殺在寫裁決前一秒（跑完 20 分鐘、844KB transcript、零產出）— 修法早存在（`codex_review_job.sh`）只是沒路由過去 — Q3
57-- 2026-07-14 23:20 queued job 的 spec 改不了 → 「enqueue 後修 brief」是跟 worker 賽跑且輸了沒人告訴你（晚 48 秒 = 一輪 30 分鐘 xhigh 審查報廢）；修：enqueue 凍結 brief + `amend`/`cancel` — Q3
58-- 2026-07-14 22:20 **RESOLVED** agent-job 的認證牆被歸檔成「研究失敗」：repo 有兩處 spawn `claude -p`，只有 supervisor 的 `worker.py` 分得出 auth / quota / transient，`run_agent_job.py` 只看得到 exit≠0 → K1709 rev3 重審 agent 5 秒死於 `Not logged in`（同時段 supervisor fire 認證正常＝暫時性刷新競態），queue 標 failed，followup brief 派下一班 fire「去 worktree 翻可搶救成果」— 那裡什麼都沒有，agent 從未啟動。**修**：分類邏輯抽成單一 owner `scripts/dispatch_supervisor/failure_class.py`（worker.py 改引用，行為不變）；runner 用同一份定義，auth → 有界重試（3 次 / 120s，且只在剩餘 budget 塞得下正事時），真失敗 → 一如既往不重試；`failure_class` 寫進 metadata receipt，compute_queue 據此把 auth 類 followup 改成「re-enqueue，不要 triage、不要記任何研究裁決」。Gate: `scripts/tests/test_agent_job_auth_class.py`（break-then-verify 確認會咬）。commit b4b2db64d — Q3
59-
60-## B. Git owner / canonical-write / `git add -A` 中毒
--
76-- 2026-07-16 PHASE-Z candidate 被 gate 擋下後只保留 3 次短期 baseline；重試上限一到便丟失原 fire 的 ownership 證明，修 gate 的下一班反而只能把 20 個正確產物視為 foreign，最久卡 54 班。修成 git-dir durable failed-closeout receipt（exact paths + SHA-256 / deletion state）；下班前只重試 byte-for-byte 未變的原產物，任何後續修改 fail-closed。同期抓到 `market_closure_detect` 空檔其實是 host crontab 錯誤重導向且與 LaunchAgent 雙觸發；canonical schedule 改為 launchd-only — 全文：`docs/error_log_archive/2026-Q3-phase-z-failed-closeout.md`
77-
78-## C. Worktree merge / 實驗檔遺失 / 審查認證
79-
80-**規則**：worktree agent 只產 `experiments/kXXX/`，禁改共享狀態；主線程用 `scripts/merge_worktree.sh` 合併，**禁 `git worktree remove --force`**（L1 hook 擋）。實驗進 main 的唯一門票 = `experiments/<kid>/review_verdict.json` 且 sha256 綁「現在這份 bytes」（PASS 後又改 code 也擋）。裁決檔一律由 `verdict-template` 產生，不手抄。**保留 branch ≠ 收割成果**：clean tree 只證明沒有未提交檔案，不證明那些 commits 進了 main；移除 unmerged checkout 就是在製造下一個殭屍。**任務引用的資源會消失，必須有東西去 reconcile**——否則任務永遠 blocked 又永遠不關單。
81-**機械 owner**：`scripts/merge_worktree.sh` → `scripts/experiment_gates.py certify`；`worktree-merge-verification` skill；`scripts/reclaim_stale_worktrees.py` 的 **unmerged gate**（dirty 與 unmerged 兩道都 fail-closed，只放行「clean 且已進 main」）；`scripts/daily_checkup.py::check_worktree_reconcile`（open 任務 ↔ 磁碟 reconcile，branch 也沒了 → critical）。
82-**代表 incident**：
83-- 2026-07-19 **k1709 殭屍任務**：任務指向的 worktree 消失了，任務卻沒有任何機制發現 —— 自 07-14 起 blocked 5 天，不會被 dispatch 也不會被關單。根因是 **task pool 與磁碟從來沒有 reconcile**：`reclaim_stale_worktrees.py` 的安全條件只查 dirty，漏查 merged，於是「clean 但未合併」的 checkout 可被回收、branch 隨後也消失，而指著它的任務無人聞問。裁定結果 3 個 commits 其實已進 main（無遺失）。同次修復發現另外 4 個 worktree 共 9 個 commits 正處在同一個懸崖邊上，被新 gate 攔下 — Q3
84:- 2026-07-12 **3-STRIKE（K1032 class）** `.claude/worktrees/` 底下「獨立 repo」對 merge 的破壞 — Q3
85-- 2026-07-14 Merge 認證聲稱可用裸 `python3`，卻在解析子命令前 eager-import 專案套件 — Q3
86-- 2026-07-14 Review 對移動中的樹裁決：verdict 沒綁 commit SHA，一落地就過期 — Q3
87-- 2026-07-13 orphan branch：三個 commit 全被平行實作取代而丟棄 — Q3
88-- (K1032 原始教訓：merge_worktree 誤判「no commits」但 reflog 有 commit → 檔案遺失) — Q2
89-
90-## D. Silent fallback / fail-open guard / exit-code masking
91-
92-**規則**：不可用 silent fallback / try-except swallow / 靜默降級掩蓋 schema 或流程缺陷；護欄不可放在 fail-open 的 `try` 內（等於沒護欄）。hook / wrapper 不可把 shell pipeline exit code 當 tool outcome（pytest false-green）。silent fallback **當場修**，不丟下一班。
--
106-**代表 incident**：
107-- 2026-07-14 136/1252 已完成實驗從未進 knowledge.json（對查重隱形）；同時 `research_program.md` 把 `experiments/k1536/` 誤標成 K1537 並編造「K1536 已被預留」的理由，衍生出一個要 scaffold 幽靈 K1537 的 stale task — Q3
108-- 2026-06-10 **3-STRIKE** 文章 narrative-arc 重複（K1449/K1091）→ arc-dedup 三層重構 — Q2
109-- 2026-06-24 arc_dedup gate 過粗 entity granularity → K1547 被 K1417 誤擋 — Q2
110-- 2026-06-23 **3-STRIKE** 並行 cron agent 撞同一 journal-discovery 題 + K-id 雙佔 — Q2
111-- 2026-06-23 release_dedup_skipped 21 天 TTL 凍結 46/46 draft（「可以發文了嗎」）— Q2
112-- 2026-06-08 Refill_task_pool 8th belt — research-saturated K narrative-arc dup — Q2
113-
114:## F. Timestamp / 發布日 / provenance / vintage 造假
115-
116:**規則**：時間戳一律取自實際 `date` 命令輸出，不可臆造（時間也是數據）。事件研究的「發布日」不可用猜的（污染已發佈數字）。總經修訂序列 OOS 必用 real-time vintage，且不得在首次 ALFRED release date 前評分（否則改稱 final-vintage pseudo-OOS，撤回 real-time claim）。文章 cite 的數字必對得上 git-tracked artifact（「曾經跑過」≠「現在可復現」）。
117-**機械 owner**：`.claude/rules/experiments.md`（PIT/vintage 硬規則）+ `scripts/validate_knowledge_provenance.py`（CI invariant）+ `src/volpred/memory/provenance.py`。
118-**代表 incident**：
119-- 2026-07-16 daily digest 發佈前近失：把 7/15 VIX/OVX 收盤誤當成已反映 7/16 最新攻擊、把 60 日係數寫成 4,693 日全樣本統計，並誤稱 WTI 79.5 已觸發 98.26 前高門檻；跨模型 gate 在 publish 前攔下，未流到讀者端。已把 as-of／rolling-window／trigger-current 雙值規則寫進 publishing canonical（全文：`docs/governance/2026-07/daily_digest_cross_vintage_nearmiss.md`）
120:- 2026-07-12 CPI 事件研究的發布日是「每月 13 號」猜出來的（已發佈數字受污染）— Q3
121-- 2026-07-09 Paper2 headline TWII γ=0.272 UNTRACEABLE，實際 ≈0.109（provenance-sweep）— Q3
122-- 2026-07-11 NFCI vintage / back-stamp（K1655：2011 才公開卻從 2004 評分）— Q3
123-- 2026-05-27 mile_91af7c48：文章數字歷史真實但 K562 patch + rerun 從未 commit — Q2
124-
125-## G. Lookahead / DM-HAC / MDD / 方法論硬規則
126-
127-**規則**：Lookahead 是最高風險 —— code 要有明確 `signal.shift(1)`；forward-label target 訓練列須 `target_end < forecast_origin`。DM 的 HAC lag 不可只用 `h-1`（h=1 時退化成 iid）；先量 loss differential 的 acf 再決定 lag。raw MDD 不可跨不同曝險比較（scale artifact）；正 exposure-matched gap 仍需對照 phase-randomization null。QLIKE 用 actual/predicted；套件限制 ≠ 模型無效。**完整硬規則見 `.claude/rules/experiments.md` §Methodology 硬規則。**
128-**機械 owner**：`scripts/experiment_gates.py run`（自檢 / compute queue）+ `scripts/experiment_gates.py certify`（worktree merge 的 stdlib-only MDD 硬 gate）+ `scripts/tests/test_dm_hac_lag_ratchet.py` + `scripts/tests/test_mdd_scale_artifact_ratchet.py` + `audit_dm_hac_lag.py` / `audit_mdd_scale_artifact.py`（凍結 baseline 只准變少）。
--
130-- 2026-07-15 **K841 方法修復**：local `range(h)` 在 h=1 只留下 gamma0，七格策略平方報酬風險 DM 都是 iid；重建舊 returns 後用 canonical Bartlett-HAC lag=13，七格 t 全變但 `|t|>3` 分類未翻。完整重跑另修正開盤才知道的權重誤套隔夜 gap、每晚平倉再開倉卻只在 ratio 改變時計成本、S5 漏 stock cost、Monday 檔漏 Saturday-AM。舊「S1 最佳」及「夜盤避險普遍不可行」因此撤回/收窄；`feed×5 + knowledge×2` 實為兩篇文章與同一筆 knowledge 的字串命中。稽核器已補 `range(h)` regression 並退休此站點。
131-- 2026-07-15 **K1386 三重方法缺陷修復**：h=1 local DM 的 autocovariance 迴圈空轉；兩份來源各 10 個完全相同重複日期使 inner merge 形成 2×2 膨脹；HAR 最後一個 IS feature row 誤吃第一個 OOS target。改用 canonical `dm_test`（lag=11）、duplicate identity check + one-to-one merge、IS target boundary 後，n_eval=1,097，DM t=3.437/3.452，原 NULL 質性結論不變但舊精確數字作廢。連帶教訓：`feed×N` 的 grep 命中數不可當文章數；本案 6 次命中只在一篇文章。稽核器已補 `max(1,h)` / `max(h,1)` h=1 退化 regression。
132-  - 2026-07-16 **K1386 frozen slice 跨平台 hash 漂移**：同一份 source file SHA、4,119 列與 one-to-one merge 在 macOS/ARM 得 `45160d...`、Linux/x86 CI 得 `500376...`；根因是 pandas 預設 C float parser 可有 1 ULP 平台差。兩個 frozen CSV reader 改用 `float_precision="round_trip"`，canonical slice hash 更新為 `9bce8a...`；完整重跑兩次所有 results/NPY/PNG byte-identical，QLIKE 八位小數、DM 判定與 NULL 結論均未變。class sweep 的另一個 analysis-slice pin K841 原已使用 round-trip parser。
133-- 2026-07-14 **K1709** 重犯 K1701 教訓：ratchet 抓得到，但它在 worktree 裡沒牙齒 — Q3
134-- 2026-07-15 **MDD class 交件機制補洞**：K1695 招牌 drawdown protection 是 exposure artifact：raw ΔMDD +12.61pp（13/13 市場為正）在同曝險口徑下變 **−0.87pp（只剩 7/13）**；`compare_max_drawdown` 對 13/13 市場亮 `exposure_mismatch`（vol ratio 0.61–0.68，遠超 20% 門檻），`k1695_results.json` 卻無任何 exposure 欄位。時間線訂正：K1695 commit `a20099d99`（7/12 14:45）早於 auditor/baseline `a3858edbe`（7/13 08:17）與 runner gate `1f6097af4`（7/14 13:20），故交件當時不存在「audit 抓得到卻沒跑」；隔日 sweep 才找到 k1695.py 5 個 production `RAW_COMPARISON`，並凍入 legacy baseline。後續真正的 enforcement gap 是 merge `certify` 只驗 review SHA，不跑 MDD gate；現已補上 trusted-main merge gate。數值證據：`storage/ops/k1695_exposure_artifact_verification.md`（文末原 certification 狀態已訂正）；完整根因：`docs/governance/2026-07/mdd_merge_certification_gate.md`。連帶 paper `vt-trend-following` Table 5 + 第三項 contribution 暫緩。
135-  - **2026-07-15 05:30 hourly-05 class sweep 補記 —— 這個 artifact 已經流到讀者端，不只卡在實驗與論文**：feed 有 3 篇 published + 2 篇 archived 文章的結論建立在 raw 口徑上（`mile_0d595dfb`「13 個國際市場實測：美國 VIX 是全球股票的通用避險信號嗎？」整篇、`mile_2d4edb65`、`mile_ee473d5a`）。**數字本身沒造假（raw ΔMDD 確實 13/13 為正），被推翻的是「這是抗跌保護」的因果解讀** —— 這正是 scale artifact 最陰險的地方：它不會讓 audit 抓到假數字，它讓真數字撐起假結論，於是機械 gate（掃 code）永遠掃不到已經發出去的散文。教訓：**MDD class 的 blast radius 必須從 code 一路掃到 feed，不能只掃 `experiments/**`**。paper hold 寫進 `storage/paper_pipeline_status.json` 的 `awaiting_correction`（vt-trend-following）；文章回溯更正 = task `feed_correction_k1695_exposure_artifact`（P1，blocked 等認證，因為沒 null 分佈前只能說「約等於零」不能說「顯著為負」）。
136-  - **2026-07-15 07:15 hourly-07 collect_completed 收尾（closure）**：rerun 補上 circular-shift/phase-randomized null（common p=0.559、inception p=0.212 均未拒絕、Holm 0/13）+ no-timing 常數減碼 reference（複製 59–85% raw gap、matched gap ~0），commit `bdf6b451f`。主線程獨立重算兩樣本 byte 對齊；fresh-context code-reviewer 判 PASS（7/7 checklist 無 blocking defect）→ `experiments/k1695/review_verdict.json`（PASS，pin 現行 sha）+ certify PASS。knowledge append 更正條目 `8f80b2ee`（撤回舊 PASS `f4a73c83`）。paper 決定＝**撤除第三 contribution**（非把 null 包裝成 finding），routed to `paper_body_vt_trend_withdraw_k1695_contribution`。`feed_correction_k1695_exposure_artifact` 認證後已解除 blocked→pending P1。primary-path Codex re-verify 已 enqueue（`agent-brief_k1695_codex_reverify-be9cd6`）作 belt-and-suspenders。**流程觀察**：knowledge store append-only、無 in-place retract CLI，舊 PASS 條目仍在庫（靠 correction 條目 + `content_correction_scanner` 覆蓋）——若日後同類撤回頻繁，值得補 supersede 機制。
137-  - **2026-07-15 09:xx hourly-09 reader-facing 回溯更正完成（closure）**：`feed_correction_k1695_exposure_artifact` 執行完畢。3 篇 published（`mile_0d595dfb` 招牌篇、`mile_2d4edb65`、`mile_ee473d5a` VT 完全指南）於 feed.json `content` 前置「編者更正聲明」——保留原數字未刪，明寫舊結論被推翻＋推翻理由（曝險假象：VT 實現波動 0.61–0.68× B&H，同曝險口徑平均 ΔMDD −0.87pp/7-of-13、null p=0.559，一個固定減碼策略即複製 85%）；嚴守強度邊界（不寫「擇時有害」、不宣稱 inception +4.96pp 被否證）。2 篇 archived（`mile_f2e26f43`/`mile_9eaadbd1`）加「更正註記」。anti_ai_gate PASS；`storage/reports/<id>.json`（存在的 2 檔）同步；`supabase_sync full` 推平台（5 篇皆入 sync log、reconcile no_drift 1810=1810）。blast radius 從 code→paper→feed 全數收口。
138:- 2026-07-12 DM helper 在 h=1 退化成 iid，K565 的 Harvey PASS 被推翻 — Q3
139-- 2026-07-13 K1702 把 MDD/vol 比率誤當尺度不變，原 Codex gate 因此失效 — Q3
140-- 2026-07-11 FEVD 取錯軸：`decomp[-1]` 把「最後一個變數」當成「最後一個 horizon」（K865 作廢）— Q3
141-- 2026-07-13 K1701 巢狀 QLIKE 用 expanding raw DM 承載 NULL，修正後只能判 inconclusive — Q3
142-- 2026-06-16 K445 article OOS 用 origin-aligned forecasts（off-by-one / lookahead 風險）— Q2
143-- 2026-05-06 K547 lookahead audit sweep：`weights * ret` 同期 pattern 跨 11 檔 — Q2
144-
145-## H. Turn final-text / notify-first / boss-facing report / alert-as-task
146-
--
199-- 2026-07-16 anti-AI publish gate `_anti_ai_fb_mode` 把所有 general/digest feed 長文誤套 **FB 短文排版檢查**（3.2 段落 ≤4 行、3.4 列表 ≥3 項即 WARN）→ 與 digest 規格「文末必列 5-8 篇精選清單」結構性矛盾，兩檢查恆貢獻 2 WARN、再加任一風格 WARN 即達 3-WARN hard-block。warn-only 遷移期（至 07-13）掩蓋了矛盾，strict 生效後第一篇 digest（07-16 補發）即被擋。修：feed 文章一律 `fb_mode=False`（FB 文案走 fb-publishing 流程不經 publish_milestone）+ regression `test_fb_mode_never_applies_to_feed_items`。教訓：**gate 從 warn-only 轉 strict 前，必須拿受影響 content_type 的真實樣本（尤其規格強制含列表/長段的類型）跑 dry-run 校準** — Q3
200-
201-## L. Paper narrative / 裁決 / review-cert SHA-pin / 規格漂移
202-
203-**規則**：單一實驗不直接改 `paper/*/body.tex`（只更新 research_program + knowledge）；≥3 互補實驗 + 用戶 confirm 才進 body rewrite。gating 實驗完成必須機械地產生**裁決義務**；handoff 隊列項禁止複製裁定內容（只放 pointer，否則變第二個會漂移的 SoT）。表面 gate 過 ≠ 語義無漂移。
204-**機械 owner**：`scripts/experiment_gates.py certify` + `review_verdict.json` sha-pin + `paper_adjudication_gap` alert（`src/volpred/ops/alerts.py`）。
205-**代表 incident**：
206-- 2026-07-14 Gating 實驗完成後無人裁決 + handoff 抄到已撤回裁定（差點錯殺一篇 JBF 論文）— Q3
207:- 2026-07-12 K1025_v3 初稿通過表面 gate，語義審查仍抓出四類規格漂移 — Q3
208-- 2026-07-14 paper snapshot pin 的 auto_adjust 硬規則張力（prg v7 重寫時發現）— Q3
209-- 2026-05-22 **3-STRIKE** K1380 SPA/RC Test — valid_all joint-mask n_valid=0 結構 — Q2
210-
211-## M. Source-of-truth drift / registry / supabase / 系列身分
212-
213-**（2026-07-16 追加，歸本 class：dual task queue + 雙回覆）**
214-- 2026-07-16 **3-STRIKE 級結構修復（老闆直接下令「該單一關口的就單一關口」）**：`volpred ops assign` 寫入的 `storage/ops/tasks/` queue **無任何 dispatcher 消費**（唯一 reader=手動 claim-next，無人跑）→ 16 任務黑洞 5 天，含結論已推翻仍在排隊的 K1695 舊敘事文章（執行=發錯誤內容）；同晚兩個並行互動 session 對老闆同一則 Telegram（msg877）**矛盾雙回覆**（msg879 排 credit→vol 研究 vs msg880 判 aggregate 版全 NULL），本 session 亦違反 claim-first（先做事先回覆最後才 claim）。**修**：(a) assign 重定向為 next_tasks.json thin wrapper（`append_next_task`，flock）；(b) 存量 17 個非終態 triage（4 終態含 1 deprecated 有害任務 + 13 遷入 canonical queue，credit 題合併雙方判斷成單一 brief）；(c) reply-right guard：`telegram-send --reply-to-task` 對已完成/他人持有任務拒發（break-then-verify 過）；(d) 機械 gate `scripts/tests/test_ops_tasks_receipts_only.py`（先 FAIL 於存量、遷移後轉綠，證明會咬）。設計：`docs/refactor_plan_single_gateway_task_system.md` — Q3
215-
216-
217-**規則**：文章系列身分 / 成員 / 格式一律讀 machine-readable registry（`config/article_series.json`），禁從標題 / 代號重新推導（無 SoT → 同系列反覆搞錯）。config 是唯一源頭；registry 存第二份 status = dual SoT。Supabase 1000-row cap 要 explicit 處理。
218-**機械 owner**：`scripts/series_registry.py --audit`（drift 每小時 check_alerts 告警）+ config single-source 規則。
219-**代表 incident**：
220-- 2026-07-06 **3-STRIKE STRUCTURAL** 文章系列身分無 single-source-of-truth → 反覆搞錯 — Q3
221-- 2026-07-14 09:50 series_registry 品牌漂移：registry 存了第二份 status（dual SoT）— Q3
222:- 2026-07-15 **事件內容走 general pipeline → 漏掛系列品牌**：台積電 7/16 法說會前夕 IV 定位文（`mile_5a20a332`）本應是「🌡️ 事件溫度計」時效事件文，卻以 `general_article` draft（`tsmc_earnings_iv_..._general_draft.md`）派工發佈 → 無 `event_series_slot` marker → 未進 registry members → **`series_registry --audit` 靜默（audit 只驗 registered members 是否掛前綴，看不到「該屬某系列卻沒註冊」的漏網文章）**。boss 巡檢抓到。修：手動歸位 members + `--apply` 掛前綴 + `supabase_sync`。**根因在 dispatch 分類**（時效 dated-event 文被當一般文），非 registry：帶 marker 的 5 篇 auto-path 全對。**教訓：時效性 dated-event 文（財報/FOMC/CPI 預告）選題時就要判為 event_article（→ 事件溫度計 + 立即發 + FB），不是 general_article；audit 只能抓 registered drift，dispatch 誤分類要靠選題紀律擋** — Q3
223-- 2026-07-15 **3-STRIKE TRIGGER（第 4 次）PostgREST 1000-row cap：v3 統計「1000 篇研究」vs 真值 1612**：boss 抓到 v3 報頭統計錯、原版正確。根因 = `fetchArticleSummaries` 無分頁 → diversify=cluster 路徑 total=1000 且 diversify/載入全部只看得到最新 1000 篇（一般路徑走 RPC 正確 → 兩版數字脫鉤）。同 class 第 4 次：paper_trades(03-18)、knowledge(04-17)、article_tags(06-23)、本次。已修 3 站點（summaries 分頁 / tags 150-id chunk + 退役 06-23 page-level 補撈 workaround / market_daily 分頁 — 後者 ascending ~880 列逼近 cap，溢出會先砍最新行情）。**2026-07-16 結構性收尾**：`data-server.ts` 統一由 `fetchAllRows` 負責所有會成長 select 的 range loop，relations / member-QA / reactions / questions / digest / paper trades 全部收編；`strategy_signals` / `strategy_metrics_cache` 以有理由的 bounded exemption 保留。新增機械 gate 掃描每個 `.from().select()`，缺 `fetchAllRows` / `range` / `limit` / `single` / `in` 或 `// row-cap-exempt: <reason>` 即 fail。production deployment `6a57ce173d3d099ed2f12794` 驗證 cluster feed total=1614、tagCounts=2082、market latest=2026-07-15。**同日老闆立 standing rule：原版=核心內容數據、v3=美化呈現、不能脫鉤**（`.claude/rules/frontend-and-deploy.md` 主從關係段）（frontend 3e72eef + b0325d1）— Q3
224-- 2026-07-15 **v3 報頭連環假資訊 — SoT 遷移後 consumer 未跟上 + 前端 workaround 掩蓋根因**：boss 抓到報頭「2026-07-14 · 星期日」（當天 7/15 週三）+ ticker 全 ▲0.00%。三層根因：(a) `星期日`/`台北·晴·24°C`/`Vol. IV No. 128` 是 mock 設計殘留硬編碼；(b) market 價格 SoT 遷移到 `market_daily` 表後 `buildStrategyOverview` 仍從 `paper_trades.entry` 撈（欄位已被 strip）→ API 回 null 多時**無人發現**，因為 (c) 前端 `useV3Data` 加了 portfolio-overview enrich workaround 把 null 蓋掉 — workaround 讓 API 根因隱形存活。修：API 改讀 market_daily（+change_pct/trade_date），移除前端 workaround（註解明令勿重引入），報頭全真值化。**教訓：client-side workaround 蓋 API 缺陷 = 把根因變隱形；發現 API 欄位 null 要修 API，不是在 consumer 補刀**（frontend aa62215）。資料端 SPY/GLD carry-forward stale 另開 task `market_daily_stale_spygld_backfill_verify` — Q3
225-- 2026-07-15 **v3 研究動態摘要裸露 md 符號 — helper 副本漂移**：`stripMarkdown` 存在 3 份本地副本（FeedBrowser 2026-06-11 修 / radar-data / reports metadata），v3 `useV3Data.adaptFeedItem` 沒有自己的副本 → 同 bug 原版修過、v3 再犯（boss 抓到）。修：收編為 `src/lib/strip-markdown.ts` 單一 util，v3 在資料組裝層 strip（全 variant 生效）；class sweep 同補兩版書籤頁裸 excerpt。**教訓：display-sanitize 這類 cross-cutting helper 第一次出現第二個 call site 時就該進 lib/，不是等第三份副本漂移**（frontend commit 13cbecb）— Q3
226-- 2026-06-23 首頁 feed 標籤消失 + tw/us 篩選慢（同根：Supabase 1000-row cap）— Q2
227-
228-## N. FB / social publishing 冪等與附圖
229-
230-**規則**：outward-facing 動作必須有冪等 guard；發 FB 前查老闆是否已手動發過。主貼文必附圖（結果圖 + 懶人包）；連結放第一則留言（壓觸及）。FB 完稿要持久化到 canonical draft 位置（非只 /tmp）。
--
357-
358-**教訓**：Stop 是 turn-end，不是 task-completed；任何非空文字都算完成會把 no-op、拒絕、timeout
359-誤播。語意層必須提供明確 receipt，機械層才 consume；外部文字不可拼 shell command。
360-
361-## 2026-07-19 dreaming 寄信閘門判「有沒有新東西」而非「有沒有人得動手」 — FIXED
362-
363-**根因**：`main()` 的寄信條件是 `if new_findings or escalations`。這判的是**新奇度**，但
364-dreaming 的設計目標（`loop-health-and-dreaming.md` §Auto vs Propose）把責任切得很清楚：
365:`auto_dispatch` 是 actuator 的事（自 2026-07-12 預設 ON，finding 一出現就自己進 next_tasks），
366-`propose_only` 才是人的事。兩者都算「新」，於是機器正在處理的照樣寄給老闆。
367-
368-第二個放大器：`reconcile()` **早就算出** `quiescent`（底層訊號自上次 run 起未推進 = 已停火、
369-正在 48h 自清），但只拿來擋 strike，算完就丟 —— 一個正在自清的 alert 仍以 active warn finding
370-的身分出現在信裡。
371-
372-標本 = 老闆 2026-07-19 回信點名的那封（email-12141，報告 `2026-07-18.json`）：9 findings =
373-4 個 auto_dispatch（其中 2 個 `remediation_ref` 已寫著派出去的 task id）+ 5 個 quiescent
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/review_verdict.json

exec
/bin/zsh -lc 'wc -l .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/*
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
wc: .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/__pycache__: read: Is a directory
wc: .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/data: read: Is a directory
wc: .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/references: read: Is a directory
     233 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py
    4267 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
    4258 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json
     873 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py
     457 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json
     128 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md
      18 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/review_verdict.json
   10234 total
     1	# k528 — NFP 事件研究（SPY 波動率）
     2	
     3	- Experiment ID: `k528`
     4	- Created At: 2026-04-16T09:39:52.904348+00:00
     5	- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑）
     6	- Status: 已重跑，結論方向不變、其中一項顯著性翻轉
     7	
     8	## 問題描述
     9	
    10	NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
    11	事件本身」，還是「進場當下的市場狀態」？
    12	
    13	## 2026-07-19 更正：事件日期從 proxy 換成官方日曆
    14	
    15	原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 在全樣本中約兩成是錯的，
    16	而且**錯得有結構、不是隨機噪音**：
    17	
    18	- BLS 在參考週較晚的月份會改到**第二個週五**發布（28 筆剛好早 7 天）
    19	- 遇到聯邦假期會**提前**（12 筆晚 3–4 天）
    20	- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
    21	- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 231 場在週五
    22	
    23	錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
    24	同時把真的事件日丟進對照組。這是本次修正存在的理由。
    25	
    26	修正後 `get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
    27	`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
    28	release id 50），且**取不到就 raise，不回退 proxy**。
    29	
    30	**樣本數幾乎沒變，但樣本本身變了很多**：254 → 253 筆，其中**只有 207 個日期是共通的**，
    31	46 場換成了不同的日子。只看筆數會誤以為沒事。
    32	
    33	## 方法
    34	
    35	- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
    36	- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
    37	- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
    38	- 檢定：Welch t（vs 全體非 NFP 日 / vs 非 NFP 週五）、Mann-Whitney U、
    39	  VIX 中位數分組 regime 檢定、Pearson / Spearman 相關
    40	
    41	## 結果：逐項前後對照
    42	
    43	每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
    44	而中位數與勝率在底下已經移位。本次就抓到一例（regime 那列）。
    45	
    46	| 指標 | 修正前（proxy） | 修正後（官方） | 判定 |
    47	|---|---|---|---|
    48	| 樣本數 | 254 | 253（僅 207 日期共通） | 數值微調，但**樣本換掉 46 場** |
    49	| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.083× (p=0.218, NS) | 數值微調 |
    50	| ↳ 中位數比 / 勝率 | 1.190× / 0.555 | 1.136× / 0.549 | 數值微調 |
    51	| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.150× (p=0.0571, **不顯著**) | **結論翻轉** |
    52	| ↳ 中位數比 / 勝率 | 1.209× / 0.563 | 1.161× / 0.561 | 數值微調 |
    53	| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.039× (p=8.1e-9) | 數值微調（仍極顯著） |
    54	| ↳ **中位數比** / 勝率 | **2.265×** / 0.717 | **2.023×** / 0.685 | **中位數移動 10.7%**（平均只動 5.9%） |
    55	| 事前 VIX 相關（Pearson） | 0.451 (p=3.9e-14) | 0.438 (p=2.8e-13) | 數值微調 |
    56	| ↳ Spearman | 0.377 | 0.337 | 數值微調 |
    57	| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
    58	
    59	**唯一的結論翻轉**：NFP 對「非 NFP 週五」基準的差距，原本 p=0.0335 達 5% 顯著，
    60	修正後 p=0.0571 **未達顯著**。這一項在線上文章 `mile_35eef830` 被明確寫成「達到顯著水準」，
    61	必須更正。
    62	
    63	翻轉的機制不只是數字抖動：proxy 下每一場 NFP 都是週五，這個檢定實際上是「週五 vs 週五」；
    64	官方日曆下有 22 場不在週五，檢定的**含義本身也變了**，不只是值變了。
    65	
    66	**方向性主結論不變**：決定 NFP 日波動的是**進場當下的 VIX 體制**（2.04 倍、p≈8e-9），
    67	不是 NFP 這個日曆事件本身（1.08 倍、不顯著）。修正反而讓這個對比更乾淨 —— 現在兩個基準
    68	都不顯著。
    69	
    70	regime 那一列值得單獨看：**平均只移動 5.9%，中位數卻移動 10.7%**，只報平均會漏掉這件事。
    71	
    72	## 產出檔案
    73	
    74	| 檔案 | 內容 |
    75	|---|---|
    76	| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
    77	| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
    78	| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄 |
    79	| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 46 個換掉的日期 + 文章更正替換清單 |
    80	| `build_article_correction.py` | 文章更正計畫（預設 dry-run 驗證，`--apply` 才寫入） |
    81	
    82	修正前的結果檔以 archive 形式保留，`k528_nfp_event_study.py` 的 audit 段直接讀它做對照。
    83	proxy 當年只報平均、沒報中位數與勝率，因此 audit 段會從 archive 的逐事件資料**重建**
    84	proxy 當時的分佈（日期取自 archive，不是重新生成一份 proxy 日曆），並先驗證重建出來的
    85	平均能重現 archive 的平均 —— 對不上就 raise，因為對不上的重建算出來的中位數同樣不可信。
    86	
    87	## 線上文章更正（`mile_35eef830`）
    88	
    89	文章正文六個主要數字全部出自本實驗，全部需要更正，其中「1.17 倍達顯著」是**論述層級**的更正。
    90	
    91	更正走 `volpred.publisher.article_correction.apply_article_correction`（唯一入口，
    92	all-or-nothing，每個替換必須恰好命中一次），**不另發第二篇更正文**。18 個替換已對線上
    93	canonical 文章驗證，全部恰好命中一次。
    94	
    95	```bash
    96	# 主線程在 repo root 執行
    97	uv run python experiments/k528/build_article_correction.py            # 驗證
    98	uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
    99	```
   100	
   101	**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
   102	`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
   103	自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
   104	合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。
   105	
   106	**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
   107	與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
   108	因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。
   109	
   110	## 防迴歸
   111	
   112	`tests/test_nfp_official_release_dates.py`（既有檔案，NFP 事件日期正確性的單一 owner，
   113	未另開新檔）新增兩組：
   114	
   115	- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、231 筆在週五、
   116	  46 個日期被換掉、結果檔宣告 fail-closed
   117	- `TestProxyMutationIsCaught` — **mutation test**：把 proxy 日曆餵給同一個 guard 必須被拒；
   118	  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆
   119	
   120	Mutation 已實測：把 `get_first_friday()` 塞回腳本 + 把結果檔換回 proxy 日期後，
   121	4 個測試由綠轉紅（source guard 2 個、artifact guard 2 個），還原後 42 passed。
   122	沒被實際觸發過的 gate 不算 gate。
   123	
   124	## 參考
   125	
   126	- K1442 事件日期稽核（發現本 bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
   127	- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
   128	- K513：先前的 FOMC/NFP/CPI 事件研究
     1	"""
     2	K528: NFP (Non-Farm Payrolls) Event Study on SPY Volatility
     3	=============================================================
     4	Extends K513 (FOMC/NFP/CPI event study) with deeper NFP-specific analysis.
     5	
     6	K513 finding: NFP vol ratio = 1.09x (NS, p=0.195). This study digs deeper:
     7	  - Larger sample with more granular windows
     8	  - VIX predictive regression
     9	  - Vol crush pattern analysis
    10	  - Seasonal decomposition (which months matter?)
    11	  - NFP surprise impact (FRED PAYEMS data)
    12	
    13	Data sources:
    14	  - SPY daily OHLCV: yfinance (2005-01 to 2026-03)
    15	  - VIX daily close: yfinance (^VIX)
    16	  - NFP dates: OFFICIAL BLS release calendar via ALFRED (FRED release id 50)
    17	  - NFP actual values: FRED PAYEMS (monthly, for surprise calculation)
    18	
    19	CORRECTION 2026-07-19
    20	---------------------
    21	The original run dated every NFP to the first Friday of the month. That proxy is
    22	wrong for ~20% of the sample and it is wrong SYSTEMATICALLY, not randomly: BLS
    23	moves the release to the second Friday whenever the reference week falls late
    24	(28 dates land exactly 7 days early), and pulls it forward around holidays (12
    25	dates land 3-4 days late). It also invents a release in 2025-10 that never
    26	happened, and it forces every event onto a Friday when 16 of the 254 official
    27	releases are not on a Friday at all.
    28	
    29	Wrong event dates do not fail loudly. They count quiet days as event days and
    30	dump real event days into the control group, and the figures still render. So
    31	the dates now come from the official release calendar and the run FAILS CLOSED
    32	if that calendar is unreachable -- `get_first_friday` is gone, not deprecated.
    33	
    34	This script also emits a before/after comparison against the archived proxy-era
    35	results so the correction's effect on every published number is auditable
    36	(k528_nfp_official_dates_results.json).
    37	
    38	References:
    39	  - Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?"
    40	    JFE, core finding: scheduled macro announcements earn risk premium
    41	  - Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JFE
    42	  - K513: Our prior FOMC/NFP/CPI event study (2005-2025, 668 events)
    43	  - K1442: event-date audit that found this bug
    44	
    45	Author: VolPred Research System
    46	Date: 2026-03-27 (corrected 2026-07-19)
    47	"""
    48	
    49	import json
    50	import warnings
    51	from datetime import datetime, timezone
    52	from pathlib import Path
    53	
    54	import numpy as np
    55	import pandas as pd
    56	import yfinance as yf
    57	from scipy import stats
    58	
    59	from volpred.data.event_dates import nfp_release_dates
    60	
    61	warnings.filterwarnings("ignore")
    62	
    63	SAMPLE_START = "2005-01-01"
    64	SAMPLE_END = "2026-03-27"
    65	
    66	# ============================================================
    67	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
    68	# ============================================================
    69	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
    70	    """Official NFP (Employment Situation) release dates.
    71	
    72	    Deliberately has no except branch. If the release calendar cannot be
    73	    reached, this run must die -- a proxy calendar produces plausible numbers
    74	    from non-events, which is worse than no numbers at all. See the CORRECTION
    75	    note in the module docstring.
    76	    """
    77	    dates = nfp_release_dates(start, end)
    78	    if len(dates) == 0:
    79	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
    80	    return list(dates)
    81	
    82	
    83	# ============================================================
    84	# 2. Download data
    85	# ============================================================
    86	print("=" * 60)
    87	print("K528: NFP Event Study on SPY Volatility")
    88	print("=" * 60)
    89	
    90	print("\n[1/6] Downloading SPY and VIX data...")
    91	spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
    92	vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)
    93	
    94	# Handle multi-level columns from yfinance
    95	if isinstance(spy.columns, pd.MultiIndex):
    96	    spy.columns = spy.columns.get_level_values(0)
    97	if isinstance(vix.columns, pd.MultiIndex):
    98	    vix.columns = vix.columns.get_level_values(0)
    99	
   100	# Calculate returns
   101	spy["Return"] = spy["Close"].pct_change()
   102	spy["AbsReturn"] = spy["Return"].abs()
   103	spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
   104	spy.dropna(subset=["Return"], inplace=True)
   105	
   106	# Merge VIX
   107	vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
   108	spy = spy.join(vix_close, how="left")
   109	spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays
   110	
   111	print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
   112	print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")
   113	
   114	# ============================================================
   115	# 3. Map NFP dates to trading days
   116	# ============================================================
   117	print("\n[2/6] Mapping NFP dates to trading days...")
   118	
   119	nfp_calendar = load_nfp_dates()
   120	trading_dates = spy.index
   121	
   122	# The proxy forced every event onto a Friday. The official calendar does not,
   123	# and that is load-bearing for the Friday-baseline test below.
   124	n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
   125	print(f"  Official releases: {len(nfp_calendar)} "
   126	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
   127	
   128	# Map each NFP date to nearest trading day (could be holiday/early close)
   129	nfp_trading_dates = []
   130	for nfp_date in nfp_calendar:
   131	    nfp_ts = pd.Timestamp(nfp_date)
   132	    # Find exact match or next trading day
   133	    if nfp_ts in trading_dates:
   134	        nfp_trading_dates.append(nfp_ts)
   135	    else:
   136	        # Find nearest trading day within 3 days
   137	        mask = (trading_dates >= nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
   138	        candidates = trading_dates[mask]
   139	        if len(candidates) > 0:
   140	            nfp_trading_dates.append(candidates[0])
   141	
   142	nfp_trading_dates = sorted(set(nfp_trading_dates))
   143	
   144	# Only keep dates within our data range (with enough buffer for pre/post windows)
   145	valid_nfp = [d for d in nfp_trading_dates
   146	             if d >= trading_dates[10] and d <= trading_dates[-6]]
   147	
   148	print(f"  Total NFP dates generated: {len(nfp_calendar)}")
   149	print(f"  Matched to trading days: {len(nfp_trading_dates)}")
   150	print(f"  Valid (with pre/post window): {len(valid_nfp)}")
   151	
   152	# ============================================================
   153	# 4. Calculate event windows
   154	# ============================================================
   155	print("\n[3/6] Calculating event window statistics...")
   156	
   157	results = []
   158	idx_list = list(trading_dates)
   159	
   160	for nfp_date in valid_nfp:
   161	    pos = idx_list.index(nfp_date)
   162	
   163	    # Pre-event: T-5 to T-1
   164	    pre_window = spy.iloc[pos-5:pos]
   165	    # Event day: T
   166	    event_day = spy.iloc[pos]
   167	    # Post-event: T+1 to T+5
   168	    post_window = spy.iloc[pos+1:pos+6]
   169	
   170	    if len(pre_window) < 5 or len(post_window) < 5:
   171	        continue
   172	
   173	    row = {
   174	        "date": nfp_date.strftime("%Y-%m-%d"),
   175	        "year": nfp_date.year,
   176	        "month": nfp_date.month,
   177	        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
   178	        "event_return": float(event_day["Return"]),
   179	        "event_abs_return": float(event_day["AbsReturn"]),
   180	        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
   181	        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
   182	        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
   183	        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
   184	        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
   185	        "vix_change_event": None,
   186	        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
   187	        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
   188	    }
   189	
   190	    if row["pre_vix"] is not None and row["event_vix"] is not None:
   191	        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
   192	
   193	    results.append(row)
   194	
   195	df = pd.DataFrame(results)
   196	print(f"  Events with complete data: {len(df)}")
   197	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
   198	
   199	# ============================================================
   200	# 5. Non-NFP baseline calculation
   201	# ============================================================
   202	print("\n[4/6] Computing non-NFP baseline...")
   203	
   204	nfp_set = set(valid_nfp)
   205	non_nfp_mask = ~spy.index.isin(nfp_set)
   206	non_nfp = spy[non_nfp_mask]
   207	
   208	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
   209	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
   210	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   211	
   212	# Also compute Friday-only baseline (since NFP is always Friday)
   213	friday_mask = non_nfp.index.weekday == 4
   214	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
   215	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
   216	
   217	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   218	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
   219	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   220	
   221	# ============================================================
   222	# 6. Statistical tests
   223	# ============================================================
   224	print("\n[5/6] Running statistical tests...")
   225	
   226	nfp_abs_returns = df["event_abs_return"].values
   227	non_nfp_abs_returns = non_nfp["AbsReturn"].values
   228	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
   229	
   230	# --- Test A: NFP vs all non-NFP days ---
   231	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
   232	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
   233	
   234	# --- Test B: NFP vs Friday-only baseline ---
   235	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
   236	vol_ratio_fri = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
   237	
   238	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
   239	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
   240	
   241	# --- Test D: Vol crush pattern (post vs pre) ---
   242	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
   243	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
   244	
   245	# --- Test E: VIX predictive regression ---
   246	vix_valid = df.dropna(subset=["pre_vix"])
   247	if len(vix_valid) > 10:
   248	    from numpy.polynomial.polynomial import polyfit
   249	    X_vix = vix_valid["pre_vix"].values
   250	    Y_abs = vix_valid["event_abs_return"].values
   251	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
   252	    # correlation and p-value
   253	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
   254	    # also spearman
   255	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
   256	else:
   257	    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6
   258	
   259	# --- Test F: Pre-event VIX change (buildup) ---
   260	# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
   261	vix_buildup = []
   262	for nfp_date in valid_nfp:
   263	    pos = idx_list.index(nfp_date)
   264	    pre5 = spy.iloc[pos-5]
   265	    pre1 = spy.iloc[pos-1]
   266	    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
   267	        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))
   268	
   269	t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
   270	
   271	# --- Test G: Seasonal analysis (by month) ---
   272	monthly_stats = {}
   273	for month in range(1, 13):
   274	    month_data = df[df["month"] == month]["event_abs_return"]
   275	    if len(month_data) >= 5:
   276	        monthly_stats[str(month)] = {
   277	            "n": int(len(month_data)),
   278	            "mean_abs_return": float(month_data.mean()),
   279	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
   280	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
   281	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
   282	        }
   283	
   284	# --- Test H: Regime analysis (high VIX vs low VIX) ---
   285	vix_median = df["pre_vix"].median()
   286	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
   287	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
   288	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
   289	
   290	# --- Test I: Time trend (has NFP impact changed over time?) ---
   291	# Split into halves
   292	midpoint = len(df) // 2
   293	first_half = df.iloc[:midpoint]["event_abs_return"]
   294	second_half = df.iloc[midpoint:]["event_abs_return"]
   295	t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
   296	
   297	# --- Test J: Event-day return direction ---
   298	pos_returns = (df["event_return"] > 0).sum()
   299	neg_returns = (df["event_return"] < 0).sum()
   300	# Binomial test: is there a directional bias?
   301	binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)
   302	
   303	print("\n" + "=" * 60)
   304	print("RESULTS")
   305	print("=" * 60)
   306	
   307	print(f"\n--- A. NFP vs All Non-NFP Days ---")
   308	print(f"  NFP day |return|:     {nfp_abs_returns.mean():.6f} ({nfp_abs_returns.mean()*100:.3f}%)")
   309	print(f"  Non-NFP |return|:     {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   310	print(f"  Vol ratio:            {vol_ratio_all:.3f}x")
   311	print(f"  t-stat:               {t_stat_all:.3f}")
   312	print(f"  p-value:              {p_val_all:.4f}")
   313	print(f"  Significant (5%):     {'YES' if p_val_all < 0.05 else 'NO'}")
   314	
   315	print(f"\n--- B. NFP vs Friday-Only Baseline ---")
   316	print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   317	print(f"  Vol ratio (vs Fri):   {vol_ratio_fri:.3f}x")
   318	print(f"  t-stat:               {t_stat_fri:.3f}")
   319	print(f"  p-value:              {p_val_fri:.4f}")
   320	
   321	print(f"\n--- C. Wilcoxon Rank-Sum (non-parametric) ---")
   322	print(f"  U-stat:               {u_stat:.1f}")
   323	print(f"  p-value (one-sided):  {p_val_wilcox:.4f}")
   324	
   325	print(f"\n--- D. Vol Crush Pattern (Post vs Pre) ---")
   326	print(f"  Pre-event avg |ret|:  {df['pre_avg_abs_return'].mean():.6f}")
   327	print(f"  Post-event avg |ret|: {df['post_avg_abs_return'].mean():.6f}")
   328	print(f"  Difference:           {vol_crush.mean():.6f}")
   329	print(f"  t-stat:               {t_crush:.3f}")
   330	print(f"  p-value:              {p_crush:.4f}")
   331	print(f"  Vol crush present:    {'YES' if vol_crush.mean() < 0 and p_crush < 0.05 else 'NO'}")
   332	
   333	print(f"\n--- E. VIX Predictive Regression ---")
   334	if r_vix is not None:
   335	    print(f"  Pearson r:            {r_vix:.4f} (p={p_vix:.4f})")
   336	    print(f"  Spearman rho:         {rho_vix:.4f} (p={p_rho_vix:.4f})")
   337	    print(f"  Slope:                {slope:.8f}")
   338	    print(f"  Interpretation:       1pt VIX increase → {slope*100:.4f}% more |return|")
   339	
   340	print(f"\n--- F. VIX Buildup (T-5 to T-1) ---")
   341	if t_buildup is not None:
   342	    print(f"  Mean VIX change:      {np.mean(vix_buildup):.4f}")
   343	    print(f"  t-stat:               {t_buildup:.3f}")
   344	    print(f"  p-value:              {p_buildup:.4f}")
   345	    print(f"  Anticipatory buildup: {'YES' if np.mean(vix_buildup) > 0 and p_buildup < 0.05 else 'NO'}")
   346	
   347	print(f"\n--- G. Seasonal Pattern (by month) ---")
   348	print(f"  {'Month':<8} {'N':<5} {'Avg |Ret|':<12} {'Ratio':<8} {'t-stat':<8} {'p-val':<8}")
   349	month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
   350	               7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
   351	for m in range(1, 13):
   352	    if str(m) in monthly_stats:
   353	        ms = monthly_stats[str(m)]
   354	        sig = "*" if ms["p_val"] < 0.05 else ""
   355	        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")
   356	
   357	print(f"\n--- H. VIX Regime Analysis ---")
   358	print(f"  VIX median split:     {vix_median:.1f}")
   359	print(f"  High VIX NFP |ret|:   {high_vix.mean():.6f} (n={len(high_vix)})")
   360	print(f"  Low VIX NFP |ret|:    {low_vix.mean():.6f} (n={len(low_vix)})")
   361	print(f"  t-stat:               {t_regime:.3f}")
   362	print(f"  p-value:              {p_regime:.4f}")
   363	
   364	print(f"\n--- I. Time Trend (First Half vs Second Half) ---")
   365	print(f"  First half |ret|:     {first_half.mean():.6f} (n={len(first_half)}, ~{df['date'].iloc[0][:4]}-{df['date'].iloc[midpoint-1][:4]})")
   366	print(f"  Second half |ret|:    {second_half.mean():.6f} (n={len(second_half)}, ~{df['date'].iloc[midpoint][:4]}-{df['date'].iloc[-1][:4]})")
   367	print(f"  t-stat:               {t_trend:.3f}")
   368	print(f"  p-value:              {p_trend:.4f}")
   369	
   370	print(f"\n--- J. Directional Bias ---")
   371	print(f"  Positive returns:     {pos_returns}/{len(df)} ({pos_returns/len(df)*100:.1f}%)")
   372	print(f"  Negative returns:     {neg_returns}/{len(df)} ({neg_returns/len(df)*100:.1f}%)")
   373	print(f"  Binomial p-value:     {binom_p:.4f}")
   374	
   375	# ============================================================
   376	# 7. High-low range analysis (intraday vol proxy)
   377	# ============================================================
   378	print(f"\n--- K. Intraday Range (High-Low / Close) ---")
   379	nfp_range = df["high_low_range"].mean()
   380	non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
   381	range_ratio = nfp_range / non_nfp_range
   382	print(f"  NFP day range:        {nfp_range:.6f} ({nfp_range*100:.3f}%)")
   383	print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
   384	print(f"  Range ratio:          {range_ratio:.3f}x")
   385	
   386	# Volume analysis
   387	print(f"\n--- L. Volume Analysis ---")
   388	vol_ratio_data = df["volume_ratio"].dropna()
   389	print(f"  NFP/avg volume ratio: {vol_ratio_data.mean():.3f}x")
   390	print(f"  NFP volume > avg:     {(vol_ratio_data > 1).sum()}/{len(vol_ratio_data)} ({(vol_ratio_data > 1).mean()*100:.1f}%)")
   391	
   392	# ============================================================
   393	# 8. April NFP specific (for upcoming 04/03 article)
   394	# ============================================================
   395	print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
   396	april_nfp = df[df["month"] == 4]
   397	print(f"  April NFP events:     {len(april_nfp)}")
   398	print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
   399	print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
   400	print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
   401	if "4" in monthly_stats:
   402	    ms4 = monthly_stats["4"]
   403	    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")
   404	
   405	# ============================================================
   406	# 9. Summary conclusion
   407	# ============================================================
   408	print(f"\n{'=' * 60}")
   409	print("SUMMARY CONCLUSION")
   410	print("=" * 60)
   411	
   412	sig_level = 0.05
   413	conclusions = []
   414	
   415	if p_val_all < sig_level:
   416	    conclusions.append(f"NFP days show significantly higher vol ({vol_ratio_all:.2f}x, p={p_val_all:.4f})")
   417	else:
   418	    conclusions.append(f"NFP days do NOT show significantly higher vol ({vol_ratio_all:.2f}x, p={p_val_all:.4f})")
   419	
   420	if p_val_fri < sig_level:
   421	    conclusions.append(f"Even vs Friday baseline, NFP is significant ({vol_ratio_fri:.2f}x, p={p_val_fri:.4f})")
   422	else:
   423	    conclusions.append(f"Vs Friday baseline, NFP is also not significant ({vol_ratio_fri:.2f}x, p={p_val_fri:.4f})")
   424	
   425	if vol_crush.mean() < 0 and p_crush < sig_level:
   426	    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
   427	else:
   428	    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")
   429	
   430	if r_vix is not None and p_vix < sig_level:
   431	    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
   432	else:
   433	    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")
   434	
   435	for c in conclusions:
   436	    print(f"  • {c}")
   437	
   438	print(f"\n  Practical implication for 04/03 NFP:")
   439	print(f"    → NFP alone does not warrant reducing SPY exposure")
   440	print(f"    → Focus on VIX level and broader market conditions instead")
   441	print(f"    → Consistent with K513 findings (NFP 1.09x, NS)")
   442	
   443	# ============================================================
   444	# 9b. Correction audit: every published number, before vs after
   445	# ============================================================
   446	# A mean can sit still while the median and the win rate move underneath it,
   447	# so no claim is judged on its mean alone. Each item carries mean / median /
   448	# win rate / n / significance, and the flip test looks at all of them.
   449	print(f"\n{'=' * 60}")
   450	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
   451	print("=" * 60)
   452	
   453	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
   454	if not PROXY_PATH.exists():
   455	    raise FileNotFoundError(
   456	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
   457	        "only record of what the published article claimed. Do not regenerate it."
   458	    )
   459	proxy = json.loads(PROXY_PATH.read_text())
   460	
   461	
   462	def win_rate(sample, reference):
   463	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
   464	    ref_med = float(np.median(reference))
   465	    return float(np.mean(np.asarray(sample) > ref_med))
   466	
   467	
   468	# The proxy run only ever reported means, and a mean can hold still while the
   469	# median and the win rate move underneath it. Rather than leave the before-side
   470	# of those two columns null -- which would make the comparison unable to detect
   471	# exactly the failure it is looking for -- rebuild the proxy-era distributions
   472	# from the ARCHIVED per-event data. The dates come out of the archive, so this
   473	# reconstructs history without reintroducing a proxy calendar generator.
   474	proxy_events = proxy["event_data"]
   475	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
   476	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
   477	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
   478	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
   479	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
   480	
   481	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   482	                       for e in proxy_events])
   483	_p_thr = proxy["regime_analysis"]["vix_median_split"]
   484	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   485	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   486	
   487	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
   488	# reconstruction is wrong and its medians cannot be trusted either.
   489	for _label, _rebuilt, _archived in (
   490	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   491	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   492	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   493	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   494	):
   495	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   496	        raise AssertionError(
   497	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   498	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   499	            "from a reconstruction that cannot reproduce the archived means."
   500	        )
   501	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   502	
   503	audit_items = {}
   504	
   505	
   506	def record(key, label, before, after, note=""):
   507	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   508	
   509	
   510	# --- 1.10x : NFP vs all non-NFP days ---
   511	record(
   512	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   513	    {
   514	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   515	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   516	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   517	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   518	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   519	        "n": proxy["sample"]["total_nfp_events"],
   520	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   521	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   522	    },
   523	    {
   524	        "mean_ratio": vol_ratio_all,
   525	        "nfp_mean": float(nfp_abs_returns.mean()),
   526	        "baseline_mean": baseline_abs_return,
   527	        "p_value": float(p_val_all),
   528	        "significant_5pct": bool(p_val_all < 0.05),
   529	        "n": int(len(df)),
   530	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   531	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   532	    },
   533	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   534	         "per-event data, not from the proxy run's own output (it only reported means).",
   535	)
   536	
   537	# --- 1.17x : NFP vs Friday-only baseline ---
   538	record(
   539	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   540	    {
   541	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   542	        "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   543	        "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   544	        "n": proxy["sample"]["total_nfp_events"],
   545	        "nfp_days_on_friday": proxy["sample"]["total_nfp_events"],
   546	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_fri_abs)),
   547	        "win_rate": win_rate(proxy_nfp_abs, proxy_fri_abs),
   548	    },
   549	    {
   550	        "mean_ratio": vol_ratio_fri,
   551	        "p_value": float(p_val_fri),
   552	        "significant_5pct": bool(p_val_fri < 0.05),
   553	        "n": int(len(df)),
   554	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   555	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(friday_non_nfp_abs)),
   556	        "win_rate": win_rate(nfp_abs_returns, friday_non_nfp_abs),
   557	    },
   558	    note="Under the proxy every NFP day was a Friday by construction, so this "
   559	         "test compared Fridays with Fridays. On the official calendar it no "
   560	         "longer does, which is a change in what the test means, not just in "
   561	         "its value.",
   562	)
   563	
   564	# --- 2.17x : high-VIX vs low-VIX regime ---
   565	proxy_reg = proxy["regime_analysis"]
   566	record(
   567	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   568	    {
   569	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
   570	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
   571	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
   572	        "n_high": proxy_reg["n_high"],
   573	        "n_low": proxy_reg["n_low"],
   574	        "p_value": proxy_reg["p_value"],
   575	        "significant_5pct": proxy_reg["p_value"] < 0.05,
   576	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
   577	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
   578	    },
   579	    {
   580	        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
   581	        "high_mean": float(high_vix.mean()),
   582	        "low_mean": float(low_vix.mean()),
   583	        "n_high": int(len(high_vix)),
   584	        "n_low": int(len(low_vix)),
   585	        "p_value": float(p_regime),
   586	        "significant_5pct": bool(p_regime < 0.05),
   587	        "median_ratio": float(high_vix.median() / low_vix.median()),
   588	        "win_rate": win_rate(high_vix.values, low_vix.values),
   589	    },
   590	)
   591	
   592	# --- 0.45 : pre-event VIX correlation ---
   593	proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
   594	record(
   595	    "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
   596	    {
   597	        "pearson_r": proxy_e["pearson_r"],
   598	        "pearson_p": proxy_e["pearson_p"],
   599	        "spearman_rho": proxy_e["spearman_rho"],
   600	        "spearman_p": proxy_e["spearman_p"],
   601	        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
   602	        "n": proxy["sample"]["total_nfp_events"],
   603	        "significant_5pct": proxy_e["pearson_p"] < 0.05,
   604	    },
   605	    {
   606	        "pearson_r": float(r_vix),
   607	        "pearson_p": float(p_vix),
   608	        "spearman_rho": float(rho_vix),
   609	        "spearman_p": float(p_rho_vix),
   610	        "slope_pct_per_vix_pt": float(slope) * 100,
   611	        "n": int(len(vix_valid)),
   612	        "significant_5pct": bool(p_vix < 0.05),
   613	    },
   614	)
   615	
   616	# --- 16.71 : the VIX median that splits the regimes ---
   617	# The article uses this threshold to place a specific date (2026-07-01 VIX
   618	# 16.59) on the low-VIX side. If the threshold crosses 16.59 the article's
   619	# worked example inverts, so it is audited as a claim in its own right.
   620	proxy_thr = proxy_reg["vix_median_split"]
   621	record(
   622	    "vix_median_threshold", "VIX median split (article: 16.71)",
   623	    {
   624	        "threshold": proxy_thr,
   625	        "n": proxy["sample"]["total_nfp_events"],
   626	        "places_20260701_vix_1659_in": "low" if 16.59 < proxy_thr else "high",
   627	    },
   628	    {
   629	        "threshold": float(vix_median),
   630	        "n": int(df["pre_vix"].notna().sum()),
   631	        "places_20260701_vix_1659_in": "low" if 16.59 < float(vix_median) else "high",
   632	    },
   633	)
   634	
   635	# --- 254 : the sample itself ---
   636	proxy_dates = {r["date"] for r in proxy["event_data"]}
   637	new_dates = {r["date"] for r in results}
   638	record(
   639	    "sample", "NFP event sample (article: 254 events)",
   640	    {
   641	        "n": proxy["sample"]["total_nfp_events"],
   642	        "date_range": proxy["sample"]["date_range"],
   643	        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
   644	    },
   645	    {
   646	        "n": int(len(df)),
   647	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   648	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   649	        "dates_in_common": len(proxy_dates & new_dates),
   650	        "proxy_only_dates": sorted(proxy_dates - new_dates),
   651	        "official_only_dates": sorted(new_dates - proxy_dates),
   652	    },
   653	    note="Equal counts do not mean equal samples -- check dates_in_common.",
   654	)
   655	
   656	
   657	def verdict_for(key):
   658	    """Flip test: significance change, sign change, or a >10% move in the headline."""
   659	    b, a = audit_items[key]["before"], audit_items[key]["after"]
   660	    reasons = []
   661	    if b.get("significant_5pct") is not None and a.get("significant_5pct") is not None:
   662	        if bool(b["significant_5pct"]) != bool(a["significant_5pct"]):
   663	            reasons.append(
   664	                "significance flipped "
   665	                f"({'sig' if b['significant_5pct'] else 'NS'} -> "
   666	                f"{'sig' if a['significant_5pct'] else 'NS'})"
   667	            )
   668	    # The mean is not trusted on its own: the median and the win rate are
   669	    # checked independently, because the failure mode this audit exists to
   670	    # catch is a stable mean sitting on top of a moved distribution.
   671	    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
   672	        if field in b and field in a and b[field] and a[field]:
   673	            rel = abs(a[field] - b[field]) / abs(b[field])
   674	            if rel > 0.10:
   675	                reasons.append(f"{field} moved {rel * 100:.1f}%")
   676	    if b.get("win_rate") and a.get("win_rate"):
   677	        if abs(a["win_rate"] - b["win_rate"]) > 0.05:
   678	            reasons.append(
   679	                f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
   680	            )
   681	    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
   682	        reasons.append("the article's worked example changes regime")
   683	    return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons
   684	
   685	
   686	print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
   687	for key, item in audit_items.items():
   688	    v, reasons = verdict_for(key)
   689	    item["verdict"], item["verdict_reasons"] = v, reasons
   690	    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
   691	                     if f in item["before"]), None)
   692	    bf = item["before"].get(headline)
   693	    af = item["after"].get(headline)
   694	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
   695	    print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
   696	    for r in reasons:
   697	        print(f"      - {r}")
   698	
   699	n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
   700	print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
   701	
   702	# ============================================================
   703	# 10. Save results
   704	# ============================================================
   705	print("\n[6/6] Saving results...")
   706	
   707	output = {
   708	    "experiment_id": "K528",
   709	    "title": "NFP Event Study on SPY Volatility",
   710	    "date": datetime.now(timezone.utc).isoformat(),
   711	    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
   712	    "event_date_source": {
   713	        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
   714	        "accessor": "volpred.data.event_dates.nfp_release_dates",
   715	        "fallback": "none - the run raises if the calendar is unreachable",
   716	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
   717	    },
   718	    "sample": {
   719	        "total_nfp_events": len(df),
   720	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   721	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   722	        "friday_baseline_days": int(friday_mask.sum()),
   723	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   724	    },
   725	    "main_results": {
   726	        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
   727	        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
   728	        "non_nfp_avg_abs_return": baseline_abs_return,
   729	        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
   730	        "friday_baseline_abs_return": friday_baseline,
   731	        "vol_ratio_vs_all": vol_ratio_all,
   732	        "vol_ratio_vs_friday": vol_ratio_fri,
   733	    },
   734	    "statistical_tests": {
   735	        "A_nfp_vs_all": {
   736	            "test": "Welch t-test",
   737	            "t_stat": float(t_stat_all),
   738	            "p_value": float(p_val_all),
   739	            "significant_5pct": bool(p_val_all < 0.05),
   740	        },
   741	        "B_nfp_vs_friday": {
   742	            "test": "Welch t-test",
   743	            "t_stat": float(t_stat_fri),
   744	            "p_value": float(p_val_fri),
   745	            "significant_5pct": bool(p_val_fri < 0.05),
   746	        },
   747	        "C_wilcoxon": {
   748	            "test": "Mann-Whitney U (one-sided)",
   749	            "u_stat": float(u_stat),
   750	            "p_value": float(p_val_wilcox),
   751	            "significant_5pct": bool(p_val_wilcox < 0.05),
   752	        },
   753	        "D_vol_crush": {
   754	            "test": "One-sample t-test (post-pre diff)",
   755	            "pre_avg": float(df["pre_avg_abs_return"].mean()),
   756	            "post_avg": float(df["post_avg_abs_return"].mean()),
   757	            "diff": float(vol_crush.mean()),
   758	            "t_stat": float(t_crush),
   759	            "p_value": float(p_crush),
   760	            "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
   761	        },
   762	        "E_vix_predictive": {
   763	            "test": "Pearson + Spearman correlation",
   764	            "pearson_r": float(r_vix) if r_vix else None,
   765	            "pearson_p": float(p_vix) if p_vix else None,
   766	            "spearman_rho": float(rho_vix) if rho_vix else None,
   767	            "spearman_p": float(p_rho_vix) if p_rho_vix else None,
   768	            "slope": float(slope) if slope else None,
   769	            "interpretation": f"1pt VIX → {slope*100:.4f}% more |return|" if slope else None,
   770	        },
   771	        "F_vix_buildup": {
   772	            "test": "One-sample t-test (T-5 to T-1 VIX change)",
   773	            "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
   774	            "t_stat": float(t_buildup) if t_buildup else None,
   775	            "p_value": float(p_buildup) if p_buildup else None,
   776	            "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
   777	        },
   778	    },
   779	    "seasonal_analysis": monthly_stats,
   780	    "regime_analysis": {
   781	        "vix_median_split": float(vix_median),
   782	        "high_vix_nfp_abs_return": float(high_vix.mean()),
   783	        "low_vix_nfp_abs_return": float(low_vix.mean()),
   784	        "n_high": int(len(high_vix)),
   785	        "n_low": int(len(low_vix)),
   786	        "t_stat": float(t_regime),
   787	        "p_value": float(p_regime),
   788	    },
   789	    "time_trend": {
   790	        "first_half_abs_return": float(first_half.mean()),
   791	        "second_half_abs_return": float(second_half.mean()),
   792	        "t_stat": float(t_trend),
   793	        "p_value": float(p_trend),
   794	    },
   795	    "directional_bias": {
   796	        "positive_count": int(pos_returns),
   797	        "negative_count": int(neg_returns),
   798	        "total": int(pos_returns + neg_returns),
   799	        "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
   800	        "binomial_p": binom_p,
   801	    },
   802	    "intraday_range": {
   803	        "nfp_avg_range": float(nfp_range),
   804	        "non_nfp_avg_range": float(non_nfp_range),
   805	        "range_ratio": float(range_ratio),
   806	    },
   807	    "volume": {
   808	        "avg_volume_ratio": float(vol_ratio_data.mean()),
   809	        "pct_above_avg": float((vol_ratio_data > 1).mean()),
   810	    },
   811	    "april_nfp": {
   812	        "n": int(len(april_nfp)),
   813	        "avg_abs_return": float(april_nfp["event_abs_return"].mean()),
   814	        "avg_signed_return": float(april_nfp["event_return"].mean()),
   815	        "positive_rate": float((april_nfp["event_return"] > 0).mean()),
   816	        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
   817	    },
   818	    "conclusions": conclusions,
   819	    "practical_implication": (
   820	        "NFP does NOT warrant reducing SPY exposure. Vol ratio ~1.09x is statistically "
   821	        "insignificant across all tests. Consistent with K513. For 04/03 NFP: focus on "
   822	        "VIX level and broader conditions, not the NFP event itself."
   823	    ),
   824	    "references": [
   825	        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
   826	        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
   827	        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
   828	    ],
   829	    "event_data": results,  # full per-event data
   830	}
   831	
   832	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
   833	with open(out_path, "w") as f:
   834	    json.dump(output, f, indent=2, default=str)
   835	
   836	print(f"  Saved to: {out_path}")
   837	
   838	# The correction audit is written separately: it is the artifact the article
   839	# correction is justified against, and it must stay readable without wading
   840	# through 254 events of per-day data.
   841	audit_out = {
   842	    "experiment_id": "K528",
   843	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
   844	    "generated_at": datetime.now(timezone.utc).isoformat(),
   845	    "before_source": PROXY_PATH.name,
   846	    "after_source": out_path.name,
   847	    "event_date_source": output["event_date_source"],
   848	    "calendar_diff": {
   849	        "proxy_only_dates": sorted(proxy_dates - new_dates),
   850	        "official_only_dates": sorted(new_dates - proxy_dates),
   851	        "dates_in_common": len(proxy_dates & new_dates),
   852	        "n_proxy": len(proxy_dates),
   853	        "n_official": len(new_dates),
   854	        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
   855	    },
   856	    "win_rate_definition": (
   857	        "share of the sample exceeding the MEDIAN of its comparison group; "
   858	        "0.5 under the null"
   859	    ),
   860	    "items": audit_items,
   861	    "n_claims_flipped": n_flipped,
   862	    "n_claims_audited": len(audit_items),
   863	    "article_correction": {
   864	        "article_id": "mile_35eef830",
   865	        "status": "pending - filled in by the correction step",
   866	        "replacements": None,
   867	    },
   868	}
   869	audit_path = Path(__file__).parent / "k528_nfp_official_dates_results.json"
   870	with open(audit_path, "w") as f:
   871	    json.dump(audit_out, f, indent=2, default=str)
   872	print(f"  Saved to: {audit_path}")
   873	print("\nDone!")
     1	"""Build and validate the in-place correction to mile_35eef830.
     2	
     3	The article was published 2026-07-01 with six headline numbers taken from
     4	K528, which dated every NFP to the first Friday of the month. On the official
     5	BLS calendar 46 of its 254 events were the wrong day. Every one of those six
     6	numbers moved, and one changed a stated conclusion: the NFP-vs-Friday gap was
     7	reported as statistically significant and is not (p 0.0335 -> 0.0571).
     8	
     9	WHY THIS SCRIPT DOES NOT WRITE BY DEFAULT
    10	-----------------------------------------
    11	`storage/reports/feed.json` is shared canonical state. `.claude/rules/worktree.md`
    12	forbids a worktree agent from touching it, and the reason is mechanical rather
    13	than ceremonial: this worktree carries its own 15MB checkout of feed.json, so a
    14	write here lands on a branch copy that is already stale the moment any other
    15	article is published, and merging it would silently revert them.
    16	
    17	So the split is: this script (run from the worktree) resolves and VALIDATES
    18	every replacement against the canonical article, proving each matches exactly
    19	once before anything is written. The main thread then runs it with --apply from
    20	the repo root, where the write is legitimate.
    21	
    22	    uv run python experiments/k528/build_article_correction.py            # validate
    23	    uv run python experiments/k528/build_article_correction.py --apply    # write + sync
    24	
    25	Validation uses `article_correction._splice`, the same resolver the writer
    26	uses, so a plan that validates here cannot fail differently there.
    27	"""
    28	
    29	from __future__ import annotations
    30	
    31	import argparse
    32	import json
    33	from pathlib import Path
    34	
    35	REPO_ROOT = Path(__file__).resolve().parents[2]
    36	ARTICLE_ID = "mile_35eef830"
    37	AUDIT_PATH = Path(__file__).parent / "k528_nfp_official_dates_results.json"
    38	
    39	# (old, new). Each `old` must occur exactly once in the article body; the
    40	# resolver rejects the whole batch otherwise. Ordered as they appear.
    41	REPLACEMENTS: list[tuple[str, str]] = [
    42	    # --- sample size: 254 -> 253 (and 46 of the survivors are different days) ---
    43	    (
    44	        "總共 254 次 NFP 公布日的資料算過一遍",
    45	        "總共 253 次 NFP 公布日的資料算過一遍",
    46	    ),
    47	    # --- 1.10x vs all non-NFP days ---
    48	    (
    49	        "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
    50	        "NFP 當日 SPY 的平均絕對日報酬是 0.828%，非 NFP 交易日是 0.764%，兩者相除是 1.08 倍。",
    51	    ),
    52	    (
    53	        "換句話說，這 1.10 倍的差距",
    54	        "換句話說，這 1.08 倍的差距",
    55	    ),
    56	    # --- 1.17x vs Friday baseline: THE CONCLUSION FLIP ---
    57	    (
    58	        "NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。"
    59	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
    60	        "NFP 當日波動是這個基準的 1.15 倍，但用 Welch t 檢定算下來，這個差距並沒有達到顯著水準"
    61	        "（p=0.057，差一點過線但沒過）。"
    62	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈仍然明顯偏高。）",
    63	    ),
    64	    (
    65	        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
    66	        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
    67	        "所以精確的講法是：NFP 日看起來比一般週五抖一點（1.15 倍），但這個差距沒有通過顯著性檢定；"
    68	        "拿全部交易日當對照，放大效果（1.08 倍）同樣談不上統計顯著。兩個基準指向同一件事——"
    69	        "以平均絕對報酬來看，NFP 日的放大效果站不住統計檢定。",
    70	    ),
    71	    # --- regime split: threshold, group sizes, means, ratio ---
    72	    (
    73	        "那 254 次 NFP 日裡",
    74	        "那 253 次 NFP 日裡",
    75	    ),
    76	    (
    77	        "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
    78	        "分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；"
    79	        "VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
    80	        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
    81	        "分界點是歷史中位數 16.69。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.11%；"
    82	        "VIX 低於中位數的 126 次，只有 0.54%。兩者相差 2.04 倍",
    83	    ),
    84	    # --- VIX correlation ---
    85	    (
    86	        "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
    87	        "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.34）",
    88	    ),
    89	    (
    90	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
    91	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.042 個百分點。",
    92	    ),
    93	    # --- figure caption ---
    94	    (
    95	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
    96	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.04 倍）]",
    97	    ),
    98	    # --- the worked example: 2026-07-01 VIX 16.59 vs the threshold ---
    99	    (
   100	        "貼在歷史分界線 16.71 的下緣",
   101	        "貼在歷史分界線 16.69 的下緣",
   102	    ),
   103	    (
   104	        "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
   105	        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
   106	    ),
   107	    # --- conclusions section ---
   108	    (
   109	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
   110	        "對週五基準是 1.17 倍、達到顯著水準。這兩個數字合起來說的是同一件事：放大效果存在，"
   111	        "但幅度有限，遠不到「本月最危險的一天」的地步。",
   112	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.08 倍、對週五基準是 1.15 倍，"
   113	        "兩個基準都沒有達到顯著水準。這兩個數字合起來說的是同一件事：放大效果就算存在，"
   114	        "幅度也有限，遠不到「本月最危險的一天」的地步。",
   115	    ),
   116	    (
   117	        "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
   118	        "高低體制差 2.04 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
   119	    ),
   120	    (
   121	        "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
   122	        "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
   123	    ),
   124	    (
   125	        "254 場歷史樣本加上 7/2 這場實測",
   126	        "253 場歷史樣本加上 7/2 這場實測",
   127	    ),
   128	    # --- methodology section + reader-facing errata ---
   129	    (
   130	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，"
   131	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
   132	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
   133	        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
   134	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n"
   135	        "**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。"
   136	        "與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，"
   137	        "遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布。"
   138	        "改用官方日曆重跑後，原本 254 場樣本中有 46 場換成了不同的日子。"
   139	        "本文正文數字已全部同步更正；**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。"
   140	        "方向性結論不變（決定波動的是進場 VIX 體制，不是 NFP 本身），"
   141	        "但有一項判讀翻轉：NFP 對「非 NFP 週五」基準的差距原本報為統計顯著（1.17 倍），"
   142	        "改用官方日期後為 1.15 倍且未達顯著（p=0.057）。"
   143	        "逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
   144	    ),
   145	    (
   146	        "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
   147	        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 127 與 126 筆；",
   148	    ),
   149	]
   150	
   151	
   152	def load_article_content(storage_dir: Path) -> str:
   153	    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
   154	    art = next((a for a in feed if isinstance(a, dict) and a.get("id") == ARTICLE_ID), None)
   155	    if art is None:
   156	        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
   157	    return art.get("content") or ""
   158	
   159	
   160	def validate(storage_dir: Path) -> list[dict]:
   161	    """Resolve every replacement against the live article. Raises if any does
   162	    not match exactly once, before a single byte is written."""
   163	    from volpred.publisher.article_correction import _splice
   164	
   165	    content = load_article_content(storage_dir)
   166	    spans = _splice(content, REPLACEMENTS)
   167	    return [
   168	        {"index": i, "hits": 1, "from": s["from"], "to": s["to"], "offset": s["start"]}
   169	        for i, s in enumerate(sorted(spans, key=lambda x: x["start"]))
   170	    ]
   171	
   172	
   173	def record_plan(validated: list[dict], applied: dict | None) -> None:
   174	    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
   175	    audit["article_correction"] = {
   176	        "article_id": ARTICLE_ID,
   177	        "status": "applied" if applied else "validated_not_applied",
   178	        "n_replacements": len(REPLACEMENTS),
   179	        "all_matched_exactly_once": True,
   180	        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
   181	        "apply_result": applied,
   182	        "residual_gap": (
   183	            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
   184	            "and the two lazypack images still render proxy-era numbers. Text and images "
   185	            "now disagree; the article carries a visible note saying so. Regenerating and "
   186	            "re-uploading them is follow-up work outside this worktree's scope."
   187	        ),
   188	    }
   189	    AUDIT_PATH.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
   190	
   191	
   192	def main() -> int:
   193	    ap = argparse.ArgumentParser(description=__doc__)
   194	    ap.add_argument("--apply", action="store_true",
   195	                    help="write the correction (main thread, repo root only)")
   196	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
   197	    args = ap.parse_args()
   198	
   199	    storage_dir = Path(args.storage_dir)
   200	    validated = validate(storage_dir)
   201	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   202	    for v in validated:
   203	        head = v["from"].splitlines()[0][:64]
   204	        print(f"  @{v['offset']:>6}  {head}...")
   205	
   206	    applied = None
   207	    if args.apply:
   208	        from volpred.publisher.article_correction import apply_article_correction
   209	
   210	        applied = apply_article_correction(
   211	            ARTICLE_ID,
   212	            content_replacements=REPLACEMENTS,
   213	            summary=(
   214	                "K528 event dates corrected from a first-Friday proxy to the official BLS "
   215	                "release calendar (46 of 254 dates were wrong). All six headline numbers "
   216	                "restated; the NFP-vs-Friday gap is no longer statistically significant "
   217	                "(1.17x p=0.0335 -> 1.15x p=0.0571)."
   218	            ),
   219	            action="content_correction",
   220	            storage_dir=str(storage_dir),
   221	        )
   222	        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
   223	              f"synced={applied['synced']}")
   224	    else:
   225	        print("\ndry run -- nothing written. Re-run with --apply from the repo root.")
   226	
   227	    record_plan(validated, applied)
   228	    print(f"plan recorded in {AUDIT_PATH.name}")
   229	    return 0
   230	
   231	
   232	if __name__ == "__main__":
   233	    raise SystemExit(main())

exec
/bin/zsh -lc "rg -n \"def nfp_release_dates|nfp_release_dates\" src tests .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp -g '*.py' | head -80
nl -ba src/volpred/data/event_dates.py | sed -n '1,280p'
for f in .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/*.json; do echo \""'$f"; jq '"'{experiment_id,metadata,event_date_source,sample_info,baseline_comparison,statistical_tests,regime_analysis,article_correction,n_claims_flipped,n_claims_audited,proxy_superseded,superseded,superseded_by,calendar_diff}' \""'$f"; done' in /Users/yhlai0911/volpred-research
 succeeded in 284ms:
tests/test_cpi_t0_official_release_dates.py:212:        script that called `nfp_release_dates` would be handed the CPI fixture and
tests/test_nfp_official_release_dates.py:91:    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
tests/test_nfp_official_release_dates.py:174:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:175:            lambda start, end, **kw: event_dates.nfp_release_dates(
tests/test_nfp_official_release_dates.py:190:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:191:            lambda start, end, **kw: event_dates.nfp_release_dates(
tests/test_nfp_official_release_dates.py:202:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:215:        monkeypatch.setattr(experiment, "nfp_release_dates", boom)
tests/test_nfp_official_release_dates.py:250:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:251:            lambda start, end, **kw: event_dates.nfp_release_dates(
tests/test_nfp_official_release_dates.py:317:        assert "from volpred.data.event_dates import nfp_release_dates" in src
tests/test_nfp_official_release_dates.py:327:        assert "nfp_release_dates" in results["event_date_source"]
src/volpred/data/event_dates.py:133:def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:133:def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:59:from volpred.data.event_dates import nfp_release_dates
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77:    dates = nfp_release_dates(start, end)
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:714:        "accessor": "volpred.data.event_dates.nfp_release_dates",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:91:    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:174:            "nfp_release_dates",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:175:            lambda start, end, **kw: event_dates.nfp_release_dates(
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:190:            "nfp_release_dates",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:191:            lambda start, end, **kw: event_dates.nfp_release_dates(
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:202:            "nfp_release_dates",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:215:        monkeypatch.setattr(experiment, "nfp_release_dates", boom)
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:250:            "nfp_release_dates",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:251:            lambda start, end, **kw: event_dates.nfp_release_dates(
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:317:        assert "from volpred.data.event_dates import nfp_release_dates" in src
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:327:        assert "nfp_release_dates" in results["event_date_source"]
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:402:        assert "from volpred.data.event_dates import nfp_release_dates" in src
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:406:        assert "nfp_release_dates" in source["accessor"]
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/event_article_nfp_2026_07_03_t1/event_article_nfp_2026_07_03_t1.py:11:`volpred.data.event_dates.nfp_release_dates`, which fails closed if the
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/event_article_nfp_2026_07_03_t1/event_article_nfp_2026_07_03_t1.py:37:from volpred.data.event_dates import nfp_release_dates
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/event_article_nfp_2026_07_03_t1/event_article_nfp_2026_07_03_t1.py:50:    No proxy and no fallback: `nfp_release_dates` raises if the official
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/event_article_nfp_2026_07_03_t1/event_article_nfp_2026_07_03_t1.py:56:    official = nfp_release_dates("2024-01-01", RELEASE_DATE)
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/event_article_nfp_2026_07_03_t1/event_article_nfp_2026_07_03_t1.py:212:            "volpred.data.event_dates.nfp_release_dates (FRED/ALFRED release id 50)"
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/event_article_nfp_2026_07_03_t1/event_article_nfp_2026_07_03_t1.py:258:            "50), retrieved via volpred.data.event_dates.nfp_release_dates, "
     1	"""Official macro-event release dates.
     2	
     3	Event studies treat the event date as a constant. It is not — it is data, and it
     4	needs a primary source like any other input. A calendar proxy ("CPI comes out
     5	around the 13th") silently does two things at once: it counts non-event days as
     6	event days, and it dumps real event days into the control group. Nothing throws,
     7	nothing is NaN, the figures still render.
     8	
     9	That is not hypothetical. Until 2026-07-12 our CPI event studies hard-coded the
    10	release dates from a 13th-of-month proxy. Against the official calendar 7 of 13
    11	dates were wrong, one of them a day on which BLS published no CPI at all (the
    12	Oct-2025 release was cancelled during the shutdown). Recomputing the CPI-day VIX
    13	reaction on the real dates flipped the mean from +2.18% to -0.85%.
    14	
    15	So: get the dates from the release calendar. `ALFRED` (FRED's real-time archive)
    16	publishes the actual news-release dates per statistical release, which is exactly
    17	the ground truth an event study needs.
    18	
    19	Usage:
    20	    from volpred.data.event_dates import cpi_release_dates
    21	    dates = cpi_release_dates("2024-01-01", "2026-12-31")   # DatetimeIndex
    22	
    23	See docs/error_log.md 2026-07-12 for the incident this module exists to prevent.
    24	"""
    25	
    26	from __future__ import annotations
    27	
    28	import json
    29	import logging
    30	import os
    31	from datetime import timedelta
    32	from pathlib import Path
    33	
    34	import pandas as pd
    35	import requests
    36	
    37	logger = logging.getLogger(__name__)
    38	
    39	# FRED release ids for the macro releases we run event studies on.
    40	# https://fred.stlouisfed.org/releases
    41	RELEASE_IDS = {
    42	    "CPI_US": 10,      # Consumer Price Index
    43	    "NFP_US": 50,      # Employment Situation
    44	    "FOMC": 101,       # H.4.1 is not the FOMC; FOMC statements are not a FRED release
    45	}
    46	
    47	_CACHE_DIR = Path(__file__).resolve().parents[3] / "storage" / "data" / "event_dates_cache"
    48	_CACHE_TTL = timedelta(days=7)
    49	
    50	
    51	def _api_key() -> str:
    52	    key = os.environ.get("FRED_API_KEY")
    53	    if key:
    54	        return key
    55	    root = Path(__file__).resolve().parents[3]
    56	    for cand in (".env.local", ".env"):
    57	        p = root / cand
    58	        if not p.exists():
    59	            continue
    60	        for line in p.read_text().splitlines():
    61	            if line.startswith("FRED_API_KEY"):
    62	                return line.split("=", 1)[1].strip().strip("\"'")
    63	    raise RuntimeError(
    64	        "FRED_API_KEY not found. Event dates must come from the official release "
    65	        "calendar — do not fall back to a hard-coded list or a calendar proxy."
    66	    )
    67	
    68	
    69	def _fetch(release_id: int, start: str, end: str) -> list[str]:
    70	    r = requests.get(
    71	        "https://api.stlouisfed.org/fred/release/dates",
    72	        params={
    73	            "release_id": release_id,
    74	            "api_key": _api_key(),
    75	            "file_type": "json",
    76	            "realtime_start": start,
    77	            "realtime_end": end,
    78	            # Without this, ALFRED only returns releases that already carry data, so
    79	            # scheduled-but-not-yet-published dates (the ones an upcoming-event
    80	            # populator actually needs) are missing. Verified 2026-07-12 that it does
    81	            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
    82	            # shutdown, stays absent either way.
    83	            "include_release_dates_with_no_data": "true",
    84	            "limit": 1000,
    85	            "sort_order": "asc",
    86	        },
    87	        timeout=30,
    88	    )
    89	    r.raise_for_status()
    90	    return [d["date"] for d in r.json()["release_dates"]]
    91	
    92	
    93	def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
    94	    """Official news-release dates for `event` within [start, end].
    95	
    96	    Monthly releases can carry off-cycle entries (annual seasonal-factor revisions
    97	    are filed against the same release id). The news release is one per calendar
    98	    month, so we keep the last entry in each month.
    99	
   100	    Raises rather than falling back — a silently-wrong event date is worse than a
   101	    failed run, because it produces plausible numbers.
   102	    """
   103	    if event not in RELEASE_IDS:
   104	        raise KeyError(f"unknown event {event!r}; known: {sorted(RELEASE_IDS)}")
   105	
   106	    cache = _CACHE_DIR / f"{event}_{start}_{end}.json"
   107	    if use_cache and cache.exists():
   108	        age = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cache.stat().st_mtime, unit="s")
   109	        if age < _CACHE_TTL:
   110	            raw = json.loads(cache.read_text())
   111	        else:
   112	            raw = None
   113	    else:
   114	        raw = None
   115	
   116	    if raw is None:
   117	        raw = _fetch(RELEASE_IDS[event], start, end)
   118	        cache.parent.mkdir(parents=True, exist_ok=True)
   119	        cache.write_text(json.dumps(raw) + "\n")
   120	
   121	    dates = pd.to_datetime(raw)
   122	    if len(dates) == 0:
   123	        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
   124	    s = pd.Series(dates, index=dates)
   125	    monthly = s.groupby([dates.year, dates.month]).max()
   126	    return pd.DatetimeIndex(sorted(monthly.values))
   127	
   128	
   129	def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   130	    return release_dates("CPI_US", start, end, **kw)
   131	
   132	
   133	def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   134	    return release_dates("NFP_US", start, end, **kw)
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
{
  "experiment_id": "K528",
  "metadata": null,
  "event_date_source": null,
  "sample_info": null,
  "baseline_comparison": null,
  "statistical_tests": {
    "A_nfp_vs_all": {
      "test": "Welch t-test",
      "t_stat": 1.5249538617647196,
      "p_value": 0.1283682008960355,
      "significant_5pct": false
    },
    "B_nfp_vs_friday": {
      "test": "Welch t-test",
      "t_stat": 2.132732372841885,
      "p_value": 0.03354366521379227,
      "significant_5pct": true
    },
    "C_wilcoxon": {
      "test": "Mann-Whitney U (one-sided)",
      "u_stat": 710364.0,
      "p_value": 0.0036000239515961954,
      "significant_5pct": true
    },
    "D_vol_crush": {
      "test": "One-sample t-test (post-pre diff)",
      "pre_avg": 0.007696814913426801,
      "post_avg": 0.007809087311450007,
      "diff": 0.00011227239802320719,
      "t_stat": 0.3375654948476601,
      "p_value": 0.7359705489035292,
      "vol_crush_present": false
    },
    "E_vix_predictive": {
      "test": "Pearson + Spearman correlation",
      "pearson_r": 0.45116558631194703,
      "pearson_p": 3.854493703611817E-14,
      "spearman_rho": 0.3766062270606868,
      "spearman_p": 5.561878132730772E-10,
      "slope": 0.0004387491083793095,
      "interpretation": "1pt VIX → 0.0439% more |return|"
    },
    "F_vix_buildup": {
      "test": "One-sample t-test (T-5 to T-1 VIX change)",
      "mean_change": 0.22972441095066823,
      "t_stat": 1.2103617700215832,
      "p_value": 0.22726966583806735,
      "anticipatory_buildup": false
    }
  },
  "regime_analysis": {
    "vix_median_split": 16.710000038146973,
    "high_vix_nfp_abs_return": 0.011524027931522324,
    "low_vix_nfp_abs_return": 0.005317816887784345,
    "n_high": 127,
    "n_low": 127,
    "t_stat": 6.7021718930396315,
    "p_value": 2.8361186837189765E-10
  },
  "article_correction": null,
  "n_claims_flipped": null,
  "n_claims_audited": null,
  "proxy_superseded": null,
  "superseded": null,
  "superseded_by": null,
  "calendar_diff": null
}
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json
{
  "experiment_id": "K528",
  "metadata": null,
  "event_date_source": {
    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
    "accessor": "volpred.data.event_dates.nfp_release_dates",
    "fallback": "none - the run raises if the calendar is unreachable",
    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
  },
  "sample_info": null,
  "baseline_comparison": null,
  "statistical_tests": {
    "A_nfp_vs_all": {
      "test": "Welch t-test",
      "t_stat": 1.2346489119140018,
      "p_value": 0.21797058884479614,
      "significant_5pct": false
    },
    "B_nfp_vs_friday": {
      "test": "Welch t-test",
      "t_stat": 1.9076176053668994,
      "p_value": 0.05714400414517939,
      "significant_5pct": false
    },
    "C_wilcoxon": {
      "test": "Mann-Whitney U (one-sided)",
      "u_stat": 700286.0,
      "p_value": 0.008837037232261593,
      "significant_5pct": true
    },
    "D_vol_crush": {
      "test": "One-sample t-test (post-pre diff)",
      "pre_avg": 0.007788905291648967,
      "post_avg": 0.007690558085775249,
      "diff": -0.00009834720587371829,
      "t_stat": -0.30495456866001985,
      "p_value": 0.7606524679691259,
      "vol_crush_present": false
    },
    "E_vix_predictive": {
      "test": "Pearson + Spearman correlation",
      "pearson_r": 0.4379026524892069,
      "pearson_p": 2.8166495806053283E-13,
      "spearman_rho": 0.33650562171674236,
      "spearman_p": 4.093044630758536E-8,
      "slope": 0.0004234189924288398,
      "interpretation": "1pt VIX → 0.0423% more |return|"
    },
    "F_vix_buildup": {
      "test": "One-sample t-test (T-5 to T-1 VIX change)",
      "mean_change": 0.03837944302163105,
      "t_stat": 0.20634816823339616,
      "p_value": 0.8366855725287482,
      "anticipatory_buildup": false
    }
  },
  "regime_analysis": {
    "vix_median_split": 16.690000534057617,
    "high_vix_nfp_abs_return": 0.011089691172140035,
    "low_vix_nfp_abs_return": 0.005438353687571986,
    "n_high": 127,
    "n_low": 126,
    "t_stat": 6.061575874792647,
    "p_value": 8.143424658634764E-9
  },
  "article_correction": null,
  "n_claims_flipped": null,
  "n_claims_audited": null,
  "proxy_superseded": null,
  "superseded": null,
  "superseded_by": null,
  "calendar_diff": null
}
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json
{
  "experiment_id": "K528",
  "metadata": null,
  "event_date_source": {
    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
    "accessor": "volpred.data.event_dates.nfp_release_dates",
    "fallback": "none - the run raises if the calendar is unreachable",
    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
  },
  "sample_info": null,
  "baseline_comparison": null,
  "statistical_tests": null,
  "regime_analysis": null,
  "article_correction": {
    "article_id": "mile_35eef830",
    "status": "validated_not_applied",
    "n_replacements": 18,
    "all_matched_exactly_once": true,
    "replacements": [
      {
        "from": "總共 254 次 NFP 公布日的資料算過一遍",
        "to": "總共 253 次 NFP 公布日的資料算過一遍",
        "hits": 1
      },
      {
        "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
        "to": "NFP 當日 SPY 的平均絕對日報酬是 0.828%，非 NFP 交易日是 0.764%，兩者相除是 1.08 倍。",
        "hits": 1
      },
      {
        "from": "換句話說，這 1.10 倍的差距",
        "to": "換句話說，這 1.08 倍的差距",
        "hits": 1
      },
      {
        "from": "NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
        "to": "NFP 當日波動是這個基準的 1.15 倍，但用 Welch t 檢定算下來，這個差距並沒有達到顯著水準（p=0.057，差一點過線但沒過）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈仍然明顯偏高。）",
        "hits": 1
      },
      {
        "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
        "to": "所以精確的講法是：NFP 日看起來比一般週五抖一點（1.15 倍），但這個差距沒有通過顯著性檢定；拿全部交易日當對照，放大效果（1.08 倍）同樣談不上統計顯著。兩個基準指向同一件事——以平均絕對報酬來看，NFP 日的放大效果站不住統計檢定。",
        "hits": 1
      },
      {
        "from": "那 254 次 NFP 日裡",
        "to": "那 253 次 NFP 日裡",
        "hits": 1
      },
      {
        "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
        "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.11%；VIX 低於中位數的 126 次，只有 0.54%。兩者相差 2.04 倍",
        "hits": 1
      },
      {
        "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
        "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.34）",
        "hits": 1
      },
      {
        "from": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
        "to": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.042 個百分點。",
        "hits": 1
      },
      {
        "from": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
        "to": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.04 倍）]",
        "hits": 1
      },
      {
        "from": "貼在歷史分界線 16.71 的下緣",
        "to": "貼在歷史分界線 16.69 的下緣",
        "hits": 1
      },
      {
        "from": "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
        "to": "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
        "hits": 1
      },
      {
        "from": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。這兩個數字合起來說的是同一件事：放大效果存在，但幅度有限，遠不到「本月最危險的一天」的地步。",
        "to": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.08 倍、對週五基準是 1.15 倍，兩個基準都沒有達到顯著水準。這兩個數字合起來說的是同一件事：放大效果就算存在，幅度也有限，遠不到「本月最危險的一天」的地步。",
        "hits": 1
      },
      {
        "from": "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
        "to": "高低體制差 2.04 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
        "hits": 1
      },
      {
        "from": "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
        "to": "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
        "hits": 1
      },
      {
        "from": "254 場歷史樣本加上 7/2 這場實測",
        "to": "253 場歷史樣本加上 7/2 這場實測",
        "hits": 1
      },
      {
        "from": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布。改用官方日曆重跑後，原本 254 場樣本中有 46 場換成了不同的日子。本文正文數字已全部同步更正；**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。方向性結論不變（決定波動的是進場 VIX 體制，不是 NFP 本身），但有一項判讀翻轉：NFP 對「非 NFP 週五」基準的差距原本報為統計顯著（1.17 倍），改用官方日期後為 1.15 倍且未達顯著（p=0.057）。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
        "hits": 1
      },
      {
        "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
        "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 127 與 126 筆；",
        "hits": 1
      }
    ],
    "apply_result": null,
    "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
  },
  "n_claims_flipped": 2,
  "n_claims_audited": 6,
  "proxy_superseded": null,
  "superseded": null,
  "superseded_by": null,
  "calendar_diff": {
    "proxy_only_dates": [
      "2005-07-01",
      "2006-03-03",
      "2006-05-05",
      "2006-12-01",
      "2007-03-02",
      "2008-07-07",
      "2009-01-02",
      "2009-05-01",
      "2009-07-06",
      "2010-01-04",
      "2010-10-01",
      "2011-07-01",
      "2012-03-02",
      "2012-12-07",
      "2013-03-01",
      "2013-05-03",
      "2013-10-04",
      "2013-11-01",
      "2014-01-03",
      "2014-07-07",
      "2015-01-02",
      "2015-05-01",
      "2015-07-06",
      "2016-01-04",
      "2016-07-01",
      "2017-03-03",
      "2017-12-01",
      "2018-03-02",
      "2019-03-01",
      "2020-01-03",
      "2020-05-01",
      "2020-07-06",
      "2021-01-04",
      "2021-10-01",
      "2022-07-01",
      "2023-03-03",
      "2023-12-01",
      "2024-01-05",
      "2024-03-01",
      "2024-08-02",
      "2025-01-03",
      "2025-07-07",
      "2025-10-03",
      "2025-11-07",
      "2025-12-05",
      "2026-01-02",
      "2026-02-06"
    ],
    "official_only_dates": [
      "2005-07-08",
      "2006-03-10",
      "2006-05-08",
      "2006-12-08",
      "2007-03-09",
      "2008-07-03",
      "2009-01-09",
      "2009-05-08",
      "2009-07-02",
      "2010-01-08",
      "2010-10-08",
      "2011-07-08",
      "2012-03-09",
      "2012-12-12",
      "2013-03-08",
      "2013-05-06",
      "2013-10-22",
      "2013-11-08",
      "2014-01-10",
      "2014-07-03",
      "2015-01-09",
      "2015-05-08",
      "2015-07-02",
      "2016-01-08",
      "2016-07-08",
      "2017-03-10",
      "2017-12-08",
      "2018-03-09",
      "2019-03-08",
      "2020-01-10",
      "2020-05-11",
      "2020-07-02",
      "2021-01-08",
      "2021-10-08",
      "2022-07-08",
      "2023-03-10",
      "2023-12-08",
      "2024-01-10",
      "2024-03-08",
      "2024-08-21",
      "2025-01-10",
      "2025-07-03",
      "2025-11-20",
      "2025-12-16",
      "2026-01-09",
      "2026-02-11"
    ],
    "dates_in_common": 207,
    "n_proxy": 254,
    "n_official": 253,
    "nfp_days_on_friday_official": 231
  }
}
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/review_verdict.json
{
  "experiment_id": null,
  "metadata": null,
  "event_date_source": null,
  "sample_info": null,
  "baseline_comparison": null,
  "statistical_tests": null,
  "regime_analysis": null,
  "article_correction": null,
  "n_claims_flipped": null,
  "n_claims_audited": null,
  "proxy_superseded": null,
  "superseded": null,
  "superseded_by": null,
  "calendar_diff": null
}

codex
初步檢查已抓到一個高風險點：腳本本身沒有 proxy fallback，但共用 accessor 會把同月多個 release-id 50 日期取「當月最後一筆」。修正清單因此出現 2024-01-10、2024-08-21、2025-11-20、2025-12-16 等非典型日期；我正在核對這些是否真的是 Employment Situation 首次發布，而不是同 release id 的後續資料更新。這會直接決定是否可過。
exec
/bin/zsh -lc 'find .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache storage/data/event_dates_cache -type f -maxdepth 1 -print 2>/dev/null | sort
for f in $(find .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache storage/data/event_dates_cache -type f -maxdepth 1 -name '"'NFP_US*' 2>/dev/null | sort); do echo \""'$f"; jq -r '"'.[]' \""'$f" | tail -80; done
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py | sed -n '"'1,460p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-27.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-31.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache/NFP_US_2005-02-01_2026-03-31.json
storage/data/event_dates_cache/CPI_US_2024-01-01_2026-05-31.json
storage/data/event_dates_cache/CPI_US_2025-01-01_2026-12-31.json
storage/data/event_dates_cache/CPI_US_2025-05-01_2026-07-01.json
storage/data/event_dates_cache/CPI_US_2026-07-12_2026-08-11.json
storage/data/event_dates_cache/CPI_US_2026-07-13_2026-08-12.json
storage/data/event_dates_cache/NFP_US_2026-01-01_2026-12-31.json
storage/data/event_dates_cache/NFP_US_2026-07-12_2026-08-11.json
storage/data/event_dates_cache/NFP_US_2026-07-13_2026-08-12.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-27.json
2019-10-04
2019-11-01
2019-12-06
2020-01-10
2020-02-07
2020-03-06
2020-04-03
2020-05-08
2020-05-11
2020-06-05
2020-07-02
2020-08-07
2020-09-04
2020-10-02
2020-11-06
2020-12-04
2021-01-08
2021-02-05
2021-03-05
2021-04-02
2021-05-07
2021-06-04
2021-07-02
2021-08-06
2021-09-03
2021-10-08
2021-11-05
2021-12-03
2022-01-07
2022-02-04
2022-03-04
2022-04-01
2022-05-06
2022-06-03
2022-07-08
2022-08-05
2022-09-02
2022-10-07
2022-11-04
2022-12-02
2023-01-06
2023-02-03
2023-03-10
2023-04-07
2023-05-05
2023-06-02
2023-07-07
2023-08-04
2023-09-01
2023-10-06
2023-11-03
2023-12-08
2024-01-05
2024-01-10
2024-02-02
2024-03-08
2024-04-05
2024-05-03
2024-06-07
2024-07-05
2024-08-02
2024-08-21
2024-09-06
2024-10-04
2024-11-01
2024-12-06
2025-01-10
2025-02-07
2025-03-07
2025-04-04
2025-05-02
2025-06-06
2025-07-03
2025-08-01
2025-09-05
2025-11-20
2025-12-16
2026-01-09
2026-02-11
2026-03-06
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-31.json
2019-10-04
2019-11-01
2019-12-06
2020-01-10
2020-02-07
2020-03-06
2020-04-03
2020-05-08
2020-05-11
2020-06-05
2020-07-02
2020-08-07
2020-09-04
2020-10-02
2020-11-06
2020-12-04
2021-01-08
2021-02-05
2021-03-05
2021-04-02
2021-05-07
2021-06-04
2021-07-02
2021-08-06
2021-09-03
2021-10-08
2021-11-05
2021-12-03
2022-01-07
2022-02-04
2022-03-04
2022-04-01
2022-05-06
2022-06-03
2022-07-08
2022-08-05
2022-09-02
2022-10-07
2022-11-04
2022-12-02
2023-01-06
2023-02-03
2023-03-10
2023-04-07
2023-05-05
2023-06-02
2023-07-07
2023-08-04
2023-09-01
2023-10-06
2023-11-03
2023-12-08
2024-01-05
2024-01-10
2024-02-02
2024-03-08
2024-04-05
2024-05-03
2024-06-07
2024-07-05
2024-08-02
2024-08-21
2024-09-06
2024-10-04
2024-11-01
2024-12-06
2025-01-10
2025-02-07
2025-03-07
2025-04-04
2025-05-02
2025-06-06
2025-07-03
2025-08-01
2025-09-05
2025-11-20
2025-12-16
2026-01-09
2026-02-11
2026-03-06
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache/NFP_US_2005-02-01_2026-03-31.json
2019-10-04
2019-11-01
2019-12-06
2020-01-10
2020-02-07
2020-03-06
2020-04-03
2020-05-08
2020-05-11
2020-06-05
2020-07-02
2020-08-07
2020-09-04
2020-10-02
2020-11-06
2020-12-04
2021-01-08
2021-02-05
2021-03-05
2021-04-02
2021-05-07
2021-06-04
2021-07-02
2021-08-06
2021-09-03
2021-10-08
2021-11-05
2021-12-03
2022-01-07
2022-02-04
2022-03-04
2022-04-01
2022-05-06
2022-06-03
2022-07-08
2022-08-05
2022-09-02
2022-10-07
2022-11-04
2022-12-02
2023-01-06
2023-02-03
2023-03-10
2023-04-07
2023-05-05
2023-06-02
2023-07-07
2023-08-04
2023-09-01
2023-10-06
2023-11-03
2023-12-08
2024-01-05
2024-01-10
2024-02-02
2024-03-08
2024-04-05
2024-05-03
2024-06-07
2024-07-05
2024-08-02
2024-08-21
2024-09-06
2024-10-04
2024-11-01
2024-12-06
2025-01-10
2025-02-07
2025-03-07
2025-04-04
2025-05-02
2025-06-06
2025-07-03
2025-08-01
2025-09-05
2025-11-20
2025-12-16
2026-01-09
2026-02-11
2026-03-06
storage/data/event_dates_cache/NFP_US_2026-01-01_2026-12-31.json
2026-01-09
2026-02-11
2026-03-06
2026-04-03
2026-05-08
2026-06-05
2026-07-02
2026-08-07
2026-09-04
2026-10-02
2026-11-06
2026-12-04
storage/data/event_dates_cache/NFP_US_2026-07-12_2026-08-11.json
2026-08-07
storage/data/event_dates_cache/NFP_US_2026-07-13_2026-08-12.json
2026-08-07
     1	"""Pin the NFP event dates that a first-Friday proxy gets wrong.
     2	
     3	`experiments/event_article_nfp_2026_07_03_t1` used to derive its NFP release
     4	dates from a "first Friday of the month" rule. Against the official BLS
     5	Employment Situation calendar, 7 of its 13 historical events were on the wrong
     6	day, and correcting them flipped the headline direction: the SPY up-day rate
     7	went from 53.8% to 46.2% and both medians changed sign.
     8	
     9	The proxy never raised and never produced a NaN. It produced a complete,
    10	plausible, wrong table. These tests exist so that failure mode cannot come
    11	back silently. See experiments/k1442/related_event_date_audit.md.
    12	
    13	Network is mocked throughout: the point is to pin the calendar semantics, not
    14	to re-verify FRED's uptime. The fixture dates below are the real values
    15	returned by FRED release id 50 (Employment Situation), fetched 2026-07-19.
    16	"""
    17	
    18	from __future__ import annotations
    19	
    20	import importlib.util
    21	from datetime import date, timedelta
    22	from pathlib import Path
    23	
    24	import pandas as pd
    25	import pytest
    26	
    27	from volpred.data import event_dates
    28	
    29	REPO_ROOT = Path(__file__).resolve().parents[1]
    30	EXPERIMENT_DIR = REPO_ROOT / "experiments" / "event_article_nfp_2026_07_03_t1"
    31	EXPERIMENT_PY = EXPERIMENT_DIR / "event_article_nfp_2026_07_03_t1.py"
    32	
    33	# Official Employment Situation release dates, FRED release id 50.
    34	OFFICIAL_2024_2026 = [
    35	    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03",
    36	    "2024-06-07", "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04",
    37	    "2024-11-01", "2024-12-06",
    38	    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02",
    39	    "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
    40	    # No October 2025 release: the shutdown cancelled it and pushed the
    41	    # September report to 2025-11-20.
    42	    "2025-11-20", "2025-12-16",
    43	    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08",
    44	    "2026-06-05", "2026-07-02",
    45	]
    46	
    47	# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
    48	# `None` means the proxy invented an event that does not exist.
    49	PROXY_MISMATCHES = [
    50	    ("2025-07-04", "2025-07-03"),  # proxy landed on the closed July 4 holiday
    51	    ("2025-10-03", None),          # phantom: no Employment Situation in Oct 2025
    52	    ("2025-11-07", "2025-11-20"),  # shutdown backlog
    53	    ("2025-12-05", "2025-12-16"),
    54	    ("2026-01-02", "2026-01-09"),
    55	    ("2026-02-06", "2026-02-11"),
    56	    ("2026-05-01", "2026-05-08"),
    57	]
    58	
    59	# The 6 the proxy happened to get right. Pinned so a "fix" that shifts every
    60	# date is caught too -- the proxy is not wrong everywhere, it is wrong at the
    61	# holiday and shutdown boundaries.
    62	PROXY_CORRECT = [
    63	    "2025-06-06", "2025-08-01", "2025-09-05",
    64	    "2026-03-06", "2026-04-03", "2026-06-05",
    65	]
    66	
    67	# What the experiment must use: trailing 13 official releases before 2026-07-02.
    68	EXPECTED_TRAILING_13 = [
    69	    "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
    70	    "2025-11-20", "2025-12-16", "2026-01-09", "2026-02-11", "2026-03-06",
    71	    "2026-04-03", "2026-05-08", "2026-06-05",
    72	]
    73	
    74	
    75	def _first_friday(year: int, month: int) -> date:
    76	    """The proxy this module exists to keep out of the codebase."""
    77	    d = date(year, month, 1)
    78	    return d + timedelta(days=(4 - d.weekday()) % 7)
    79	
    80	
    81	@pytest.fixture(autouse=True)
    82	def isolate_event_date_cache(monkeypatch, tmp_path):
    83	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
    84	
    85	
    86	@pytest.fixture
    87	def official(monkeypatch):
    88	    monkeypatch.setattr(
    89	        event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
    90	    )
    91	    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
    92	
    93	
    94	@pytest.fixture(scope="module")
    95	def experiment():
    96	    spec = importlib.util.spec_from_file_location(
    97	        "nfp_t1_experiment", EXPERIMENT_PY
    98	    )
    99	    module = importlib.util.module_from_spec(spec)
   100	    spec.loader.exec_module(module)
   101	    return module
   102	
   103	
   104	class TestProxyMismatches:
   105	    @pytest.mark.parametrize("proxy_date,official_date", PROXY_MISMATCHES)
   106	    def test_proxy_date_is_not_an_official_release(
   107	        self, official, proxy_date, official_date
   108	    ):
   109	        assert pd.Timestamp(proxy_date) not in official, (
   110	            f"{proxy_date} came from the first-Friday proxy and is not an "
   111	            "Employment Situation release date"
   112	        )
   113	        if official_date is not None:
   114	            assert pd.Timestamp(official_date) in official
   115	
   116	    @pytest.mark.parametrize("proxy_date,official_date", PROXY_MISMATCHES)
   117	    def test_mismatch_really_is_what_the_proxy_would_have_produced(
   118	        self, proxy_date, official_date
   119	    ):
   120	        """Guard the fixture itself: each 'proxy' date must be a first Friday.
   121	
   122	        Without this, a typo in PROXY_MISMATCHES would make the suite pass by
   123	        testing a date the proxy never generated.
   124	        """
   125	        d = pd.Timestamp(proxy_date)
   126	        assert _first_friday(d.year, d.month) == d.date()
   127	
   128	    def test_october_2025_release_does_not_exist(self, official):
   129	        """The proxy's worst failure: a full event window scored on a non-event.
   130	
   131	        No Employment Situation was published in October 2025. A monthly
   132	        heuristic cannot represent this, which is why the calendar has to be
   133	        data rather than a rule.
   134	        """
   135	        assert not [d for d in official if (d.year, d.month) == (2025, 10)]
   136	
   137	    @pytest.mark.parametrize("proxy_date", PROXY_CORRECT)
   138	    def test_proxy_dates_that_were_already_correct_stay_correct(
   139	        self, official, proxy_date
   140	    ):
   141	        assert pd.Timestamp(proxy_date) in official
   142	
   143	    def test_seven_of_thirteen_were_wrong(self, official):
   144	        """The headline number from the K1442 audit, recomputed not restated."""
   145	        proxy_dates = []
   146	        y, m = 2026, 6
   147	        while len(proxy_dates) < 13:
   148	            ff = _first_friday(y, m)
   149	            if ff < date(2026, 7, 3):
   150	                proxy_dates.append(ff)
   151	            m -= 1
   152	            if m == 0:
   153	                m, y = 12, y - 1
   154	
   155	        wrong = [d for d in proxy_dates if pd.Timestamp(d) not in official]
   156	        assert len(wrong) == 7
   157	        assert {str(d) for d in wrong} == {p for p, _ in PROXY_MISMATCHES}
   158	
   159	
   160	class TestExperimentUsesOfficialCalendar:
   161	    def test_release_date_is_july_2_not_july_3(self, experiment):
   162	        """July 4 fell on a Saturday, observed Friday July 3, so BLS moved up."""
   163	        assert experiment.RELEASE_DATE == "2026-07-02"
   164	        assert experiment.AS_OF == "2026-07-01"
   165	
   166	    def test_build_nfp_dates_returns_the_official_trailing_thirteen(
   167	        self, experiment, monkeypatch
   168	    ):
   169	        monkeypatch.setattr(
   170	            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
   171	        )
   172	        monkeypatch.setattr(
   173	            experiment,
   174	            "nfp_release_dates",
   175	            lambda start, end, **kw: event_dates.nfp_release_dates(
   176	                start, end, use_cache=False
   177	            ),
   178	        )
   179	
   180	        actual = [str(d.date()) for d in experiment.build_nfp_dates(13)]
   181	        assert actual == EXPECTED_TRAILING_13
   182	
   183	    def test_release_date_itself_is_excluded(self, experiment, monkeypatch):
   184	        """2026-07-02 is the event under study; it must not enter its own history."""
   185	        monkeypatch.setattr(
   186	            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
   187	        )
   188	        monkeypatch.setattr(
   189	            experiment,
   190	            "nfp_release_dates",
   191	            lambda start, end, **kw: event_dates.nfp_release_dates(
   192	                start, end, use_cache=False
   193	            ),
   194	        )
   195	
   196	        assert pd.Timestamp("2026-07-02") not in experiment.build_nfp_dates(13)
   197	
   198	    def test_fails_closed_when_calendar_is_short(self, experiment, monkeypatch):
   199	        """No proxy fallback: too few official dates must raise, not improvise."""
   200	        monkeypatch.setattr(
   201	            experiment,
   202	            "nfp_release_dates",
   203	            lambda *_a, **_kw: pd.DatetimeIndex(pd.to_datetime(["2026-06-05"])),
   204	        )
   205	
   206	        with pytest.raises(RuntimeError, match="only 1 releases"):
   207	            experiment.build_nfp_dates(13)
   208	
   209	    def test_fails_closed_when_calendar_is_unreachable(
   210	        self, experiment, monkeypatch
   211	    ):
   212	        def boom(*_a, **_kw):
   213	            raise RuntimeError("FRED_API_KEY not found")
   214	
   215	        monkeypatch.setattr(experiment, "nfp_release_dates", boom)
   216	
   217	        with pytest.raises(RuntimeError, match="FRED_API_KEY"):
   218	            experiment.build_nfp_dates(13)
   219	
   220	
   221	class TestNoLookahead:
   222	    """The download window itself must exclude the release day.
   223	
   224	    Asserting on constants is not enough: the constant can be right while the
   225	    call still passes a later `end`. These observe the actual yfinance calls.
   226	    """
   227	
   228	    # SPY, ^VIX, ^VIX9D -- every series must respect the cutoff, so the
   229	    # recorder has to survive past the first call. Stopping on call 1 would
   230	    # leave a mutated ^VIX or ^VIX9D `end` completely untested.
   231	    EXPECTED_TICKERS = ["SPY", "^VIX", "^VIX9D"]
   232	
   233	    def _capture_downloads(self, experiment, monkeypatch):
   234	        calls = []
   235	
   236	        def recorder(ticker, **kw):
   237	            calls.append({"ticker": ticker, **kw})
   238	            # Never abort inside the recorder itself. Stopping on call N would
   239	            # make a download added AFTER the ones we know about unreachable,
   240	            # so a 4th series could ship with an unchecked `end`. The tripwire
   241	            # defers the abort until main() first touches a frame, which is
   242	            # past the whole download block.
   243	            return _Tripwire()
   244	
   245	        monkeypatch.setattr(
   246	            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
   247	        )
   248	        monkeypatch.setattr(
   249	            experiment,
   250	            "nfp_release_dates",
   251	            lambda start, end, **kw: event_dates.nfp_release_dates(
   252	                start, end, use_cache=False
   253	            ),
   254	        )
   255	        monkeypatch.setattr(experiment.yf, "download", recorder)
   256	        try:
   257	            experiment.main()
   258	        except _StopEarly:
   259	            pass  # silent-ok: sentinel to stop main() once args are captured
   260	        return calls
   261	
   262	    def test_every_series_is_downloaded(self, experiment, monkeypatch):
   263	        """Pin the call count so the assertions below cannot pass vacuously."""
   264	        calls = self._capture_downloads(experiment, monkeypatch)
   265	        assert [c["ticker"] for c in calls] == self.EXPECTED_TICKERS
   266	
   267	    def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
   268	        calls = self._capture_downloads(experiment, monkeypatch)
   269	        assert len(calls) == len(self.EXPECTED_TICKERS)
   270	        for call in calls:
   271	            # yfinance `end` is exclusive, so end == release date means the
   272	            # last obtainable session is 2026-07-01.
   273	            assert call["end"] == "2026-07-02", (
   274	                f"{call['ticker']} download window ends at {call['end']!r}; "
   275	                "the 2026-07-02 release day must not be downloadable"
   276	            )
   277	
   278	    def test_download_window_starts_before_the_earliest_event(
   279	        self, experiment, monkeypatch
   280	    ):
   281	        calls = self._capture_downloads(experiment, monkeypatch)
   282	        # Guard against all([]) passing vacuously if nothing was captured.
   283	        assert len(calls) == len(self.EXPECTED_TICKERS)
   284	        # Needs a prior close to difference against 2025-05-02.
   285	        assert all(call["start"] < "2025-05-02" for call in calls)
   286	
   287	
   288	class _StopEarly(Exception):
   289	    """Abort main() once the download arguments have been observed."""
   290	
   291	
   292	class _Tripwire:
   293	    """Stand-in for a downloaded frame that raises when first consumed.
   294	
   295	    Lets every `yf.download` call run and be recorded before main() is
   296	    aborted, so the ticker-sequence assertion can see a download that does
   297	    not exist yet. main() touches `.columns` first when it flattens the
   298	    MultiIndex.
   299	    """
   300	
   301	    @property
   302	    def columns(self):
   303	        raise _StopEarly()
   304	
   305	
   306	class TestNoProxyResidue:
   307	    """Source-level guard. The behavioural tests above can all pass while a
   308	    dormant proxy helper sits in the file waiting to be called again."""
   309	
   310	    def test_experiment_defines_no_first_friday_helper(self):
   311	        src = EXPERIMENT_PY.read_text(encoding="utf-8")
   312	        assert "def first_friday" not in src
   313	        assert "(4 - d.weekday()) % 7" not in src
   314	
   315	    def test_experiment_imports_the_official_calendar(self):
   316	        src = EXPERIMENT_PY.read_text(encoding="utf-8")
   317	        assert "from volpred.data.event_dates import nfp_release_dates" in src
   318	
   319	    def test_results_json_declares_its_event_date_source(self):
   320	        import json
   321	
   322	        results = json.loads(
   323	            (EXPERIMENT_DIR / "event_article_nfp_2026_07_03_t1_results.json")
   324	            .read_text(encoding="utf-8")
   325	        )
   326	        assert results["nfp_release_date"] == "2026-07-02"
   327	        assert "nfp_release_dates" in results["event_date_source"]
   328	        assert [r["nfp_release_date"] for r in results["historical_nfp_table"]] == (
   329	            EXPECTED_TRAILING_13
   330	        )
   331	
   332	
   333	# ---------------------------------------------------------------------------
   334	# K528 -- the same proxy, the same bug, a 21-year sample.
   335	#
   336	# The sibling experiment above had 13 events. K528 had 254 and fed six numbers
   337	# straight into a published article (mile_35eef830). Correcting its calendar
   338	# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
   339	# (p 0.0335 -> 0.0571). Same module rather than a new file: "NFP event dates
   340	# are official" is one concern and should keep one enforcement owner.
   341	# ---------------------------------------------------------------------------
   342	
   343	K528_DIR = REPO_ROOT / "experiments" / "k528"
   344	K528_PY = K528_DIR / "k528_nfp_event_study.py"
   345	K528_RESULTS = K528_DIR / "k528_nfp_event_study_results.json"
   346	K528_AUDIT = K528_DIR / "k528_nfp_official_dates_results.json"
   347	
   348	
   349	def _load_k528(path):
   350	    import json
   351	
   352	    return json.loads(path.read_text(encoding="utf-8"))
   353	
   354	
   355	def _k528_event_dates():
   356	    return [pd.Timestamp(e["date"]) for e in _load_k528(K528_RESULTS)["event_data"]]
   357	
   358	
   359	def assert_not_first_friday_proxy(dates):
   360	    """Reject a calendar carrying the first-Friday proxy's fingerprints.
   361	
   362	    Three independent signatures, because a partial revert should be caught as
   363	    readily as a total one. This is the function the mutation test below fires
   364	    a proxy calendar at: a guard nobody has ever seen fail is not a guard.
   365	    """
   366	    dates = pd.DatetimeIndex(dates)
   367	    if len(dates) == 0:
   368	        raise AssertionError("empty calendar")
   369	
   370	    if (dates.weekday == 4).all():
   371	        raise AssertionError(
   372	            f"all {len(dates)} releases fall on a Friday. The official calendar "
   373	            "does not: BLS moves the release off Friday at holiday and shutdown "
   374	            "boundaries. This is the proxy's signature."
   375	        )
   376	
   377	    on_first_friday = [
   378	        d for d in dates if d.date() == _first_friday(d.year, d.month)
   379	    ]
   380	    if len(on_first_friday) == len(dates):
   381	        raise AssertionError(
   382	            "every release sits on the first Friday of its month -- proxy calendar"
   383	        )
   384	
   385	    phantom = [d for d in dates if (d.year, d.month) == (2025, 10)]
   386	    if phantom:
   387	        raise AssertionError(
   388	            f"calendar contains an October 2025 release ({phantom[0].date()}). "
   389	            "The shutdown cancelled it; only the proxy invents one."
   390	        )
   391	
   392	
   393	class TestK528UsesOfficialCalendar:
   394	    def test_defines_no_first_friday_helper(self):
   395	        src = K528_PY.read_text(encoding="utf-8")
   396	        assert "def get_first_friday" not in src
   397	        assert "def generate_nfp_dates" not in src
   398	        assert "(4 - first_day.weekday()) % 7" not in src
   399	
   400	    def test_imports_the_official_calendar(self):
   401	        src = K528_PY.read_text(encoding="utf-8")
   402	        assert "from volpred.data.event_dates import nfp_release_dates" in src
   403	
   404	    def test_results_declare_the_official_source_and_no_fallback(self):
   405	        source = _load_k528(K528_RESULTS)["event_date_source"]
   406	        assert "nfp_release_dates" in source["accessor"]
   407	        assert source["fallback"] == "none - the run raises if the calendar is unreachable"
   408	
   409	    def test_event_dates_carry_no_proxy_signature(self):
   410	        assert_not_first_friday_proxy(_k528_event_dates())
   411	
   412	    def test_sample_is_not_uniformly_friday(self):
   413	        """231 of 253, not 253 of 253. The gap is the corrected dates."""
   414	        results = _load_k528(K528_RESULTS)
   415	        n, on_friday = results["sample"]["total_nfp_events"], results["sample"]["nfp_days_on_friday"]
   416	        assert n == 253
   417	        assert on_friday == 231
   418	        assert on_friday < n
   419	
   420	    def test_audit_records_the_dates_that_changed(self):
   421	        diff = _load_k528(K528_AUDIT)["calendar_diff"]
   422	        assert diff["dates_in_common"] == 207
   423	        # The equal-looking sample sizes hide a 46-date swap; assert the swap,
   424	        # not the count, or a silent revert reads as unchanged.
   425	        assert len(diff["proxy_only_dates"]) == 47
   426	        assert len(diff["official_only_dates"]) == 46
   427	        assert "2025-10-03" in diff["proxy_only_dates"]
   428	        assert "2025-11-20" in diff["official_only_dates"]
   429	
   430	
   431	class TestProxyMutationIsCaught:
   432	    """Mutation test. Reverting to the proxy must turn the suite red, and the
   433	    only way to know that is to build the proxy calendar and watch the guard
   434	    reject it."""
   435	
   436	    @staticmethod
   437	    def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
   438	        out = []
   439	        for year in range(start_year, end_year + 1):
   440	            last = 12 if year < end_year else end_month
   441	            for month in range(1, last + 1):
   442	                out.append(pd.Timestamp(_first_friday(year, month)))
   443	        return pd.DatetimeIndex(out)
   444	
   445	    def test_the_proxy_calendar_is_rejected(self):
   446	        with pytest.raises(AssertionError, match="Friday"):
   447	            assert_not_first_friday_proxy(self._proxy_calendar())
   448	
   449	    def test_phantom_october_2025_alone_is_enough_to_fail(self):
   450	        """A partial revert that keeps some real dates still gets caught."""
   451	        mixed = pd.DatetimeIndex(
   452	            _k528_event_dates() + [pd.Timestamp("2025-10-03")]
   453	        )
   454	        with pytest.raises(AssertionError, match="October 2025"):
   455	            assert_not_first_friday_proxy(mixed)
   456	
   457	    def test_the_guard_accepts_the_official_calendar(self, official):
   458	        """The other half of the mutation test: the guard must not reject
   459	        everything. A guard that always fails is as useless as one that never
   460	        does."""

web search: 
web search: site:bls.gov/news.release/archives/empsit_01052024.pdf Employment Situation January 5 2024 ...
web search: 
web search: BLS Employment Situation January 2024 released January 5 2024 official ...
exec
/bin/zsh -lc "nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py | sed -n '195,470p'
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py | sed -n '470,740p'
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py | sed -n '700,880p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
   195	df = pd.DataFrame(results)
   196	print(f"  Events with complete data: {len(df)}")
   197	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
   198	
   199	# ============================================================
   200	# 5. Non-NFP baseline calculation
   201	# ============================================================
   202	print("\n[4/6] Computing non-NFP baseline...")
   203	
   204	nfp_set = set(valid_nfp)
   205	non_nfp_mask = ~spy.index.isin(nfp_set)
   206	non_nfp = spy[non_nfp_mask]
   207	
   208	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
   209	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
   210	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   211	
   212	# Also compute Friday-only baseline (since NFP is always Friday)
   213	friday_mask = non_nfp.index.weekday == 4
   214	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
   215	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
   216	
   217	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   218	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
   219	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   220	
   221	# ============================================================
   222	# 6. Statistical tests
   223	# ============================================================
   224	print("\n[5/6] Running statistical tests...")
   225	
   226	nfp_abs_returns = df["event_abs_return"].values
   227	non_nfp_abs_returns = non_nfp["AbsReturn"].values
   228	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
   229	
   230	# --- Test A: NFP vs all non-NFP days ---
   231	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
   232	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
   233	
   234	# --- Test B: NFP vs Friday-only baseline ---
   235	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
   236	vol_ratio_fri = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
   237	
   238	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
   239	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
   240	
   241	# --- Test D: Vol crush pattern (post vs pre) ---
   242	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
   243	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
   244	
   245	# --- Test E: VIX predictive regression ---
   246	vix_valid = df.dropna(subset=["pre_vix"])
   247	if len(vix_valid) > 10:
   248	    from numpy.polynomial.polynomial import polyfit
   249	    X_vix = vix_valid["pre_vix"].values
   250	    Y_abs = vix_valid["event_abs_return"].values
   251	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
   252	    # correlation and p-value
   253	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
   254	    # also spearman
   255	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
   256	else:
   257	    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6
   258	
   259	# --- Test F: Pre-event VIX change (buildup) ---
   260	# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
   261	vix_buildup = []
   262	for nfp_date in valid_nfp:
   263	    pos = idx_list.index(nfp_date)
   264	    pre5 = spy.iloc[pos-5]
   265	    pre1 = spy.iloc[pos-1]
   266	    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
   267	        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))
   268	
   269	t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
   270	
   271	# --- Test G: Seasonal analysis (by month) ---
   272	monthly_stats = {}
   273	for month in range(1, 13):
   274	    month_data = df[df["month"] == month]["event_abs_return"]
   275	    if len(month_data) >= 5:
   276	        monthly_stats[str(month)] = {
   277	            "n": int(len(month_data)),
   278	            "mean_abs_return": float(month_data.mean()),
   279	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
   280	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
   281	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
   282	        }
   283	
   284	# --- Test H: Regime analysis (high VIX vs low VIX) ---
   285	vix_median = df["pre_vix"].median()
   286	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
   287	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
   288	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
   289	
   290	# --- Test I: Time trend (has NFP impact changed over time?) ---
   291	# Split into halves
   292	midpoint = len(df) // 2
   293	first_half = df.iloc[:midpoint]["event_abs_return"]
   294	second_half = df.iloc[midpoint:]["event_abs_return"]
   295	t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
   296	
   297	# --- Test J: Event-day return direction ---
   298	pos_returns = (df["event_return"] > 0).sum()
   299	neg_returns = (df["event_return"] < 0).sum()
   300	# Binomial test: is there a directional bias?
   301	binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)
   302	
   303	print("\n" + "=" * 60)
   304	print("RESULTS")
   305	print("=" * 60)
   306	
   307	print(f"\n--- A. NFP vs All Non-NFP Days ---")
   308	print(f"  NFP day |return|:     {nfp_abs_returns.mean():.6f} ({nfp_abs_returns.mean()*100:.3f}%)")
   309	print(f"  Non-NFP |return|:     {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   310	print(f"  Vol ratio:            {vol_ratio_all:.3f}x")
   311	print(f"  t-stat:               {t_stat_all:.3f}")
   312	print(f"  p-value:              {p_val_all:.4f}")
   313	print(f"  Significant (5%):     {'YES' if p_val_all < 0.05 else 'NO'}")
   314	
   315	print(f"\n--- B. NFP vs Friday-Only Baseline ---")
   316	print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   317	print(f"  Vol ratio (vs Fri):   {vol_ratio_fri:.3f}x")
   318	print(f"  t-stat:               {t_stat_fri:.3f}")
   319	print(f"  p-value:              {p_val_fri:.4f}")
   320	
   321	print(f"\n--- C. Wilcoxon Rank-Sum (non-parametric) ---")
   322	print(f"  U-stat:               {u_stat:.1f}")
   323	print(f"  p-value (one-sided):  {p_val_wilcox:.4f}")
   324	
   325	print(f"\n--- D. Vol Crush Pattern (Post vs Pre) ---")
   326	print(f"  Pre-event avg |ret|:  {df['pre_avg_abs_return'].mean():.6f}")
   327	print(f"  Post-event avg |ret|: {df['post_avg_abs_return'].mean():.6f}")
   328	print(f"  Difference:           {vol_crush.mean():.6f}")
   329	print(f"  t-stat:               {t_crush:.3f}")
   330	print(f"  p-value:              {p_crush:.4f}")
   331	print(f"  Vol crush present:    {'YES' if vol_crush.mean() < 0 and p_crush < 0.05 else 'NO'}")
   332	
   333	print(f"\n--- E. VIX Predictive Regression ---")
   334	if r_vix is not None:
   335	    print(f"  Pearson r:            {r_vix:.4f} (p={p_vix:.4f})")
   336	    print(f"  Spearman rho:         {rho_vix:.4f} (p={p_rho_vix:.4f})")
   337	    print(f"  Slope:                {slope:.8f}")
   338	    print(f"  Interpretation:       1pt VIX increase → {slope*100:.4f}% more |return|")
   339	
   340	print(f"\n--- F. VIX Buildup (T-5 to T-1) ---")
   341	if t_buildup is not None:
   342	    print(f"  Mean VIX change:      {np.mean(vix_buildup):.4f}")
   343	    print(f"  t-stat:               {t_buildup:.3f}")
   344	    print(f"  p-value:              {p_buildup:.4f}")
   345	    print(f"  Anticipatory buildup: {'YES' if np.mean(vix_buildup) > 0 and p_buildup < 0.05 else 'NO'}")
   346	
   347	print(f"\n--- G. Seasonal Pattern (by month) ---")
   348	print(f"  {'Month':<8} {'N':<5} {'Avg |Ret|':<12} {'Ratio':<8} {'t-stat':<8} {'p-val':<8}")
   349	month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
   350	               7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
   351	for m in range(1, 13):
   352	    if str(m) in monthly_stats:
   353	        ms = monthly_stats[str(m)]
   354	        sig = "*" if ms["p_val"] < 0.05 else ""
   355	        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")
   356	
   357	print(f"\n--- H. VIX Regime Analysis ---")
   358	print(f"  VIX median split:     {vix_median:.1f}")
   359	print(f"  High VIX NFP |ret|:   {high_vix.mean():.6f} (n={len(high_vix)})")
   360	print(f"  Low VIX NFP |ret|:    {low_vix.mean():.6f} (n={len(low_vix)})")
   361	print(f"  t-stat:               {t_regime:.3f}")
   362	print(f"  p-value:              {p_regime:.4f}")
   363	
   364	print(f"\n--- I. Time Trend (First Half vs Second Half) ---")
   365	print(f"  First half |ret|:     {first_half.mean():.6f} (n={len(first_half)}, ~{df['date'].iloc[0][:4]}-{df['date'].iloc[midpoint-1][:4]})")
   366	print(f"  Second half |ret|:    {second_half.mean():.6f} (n={len(second_half)}, ~{df['date'].iloc[midpoint][:4]}-{df['date'].iloc[-1][:4]})")
   367	print(f"  t-stat:               {t_trend:.3f}")
   368	print(f"  p-value:              {p_trend:.4f}")
   369	
   370	print(f"\n--- J. Directional Bias ---")
   371	print(f"  Positive returns:     {pos_returns}/{len(df)} ({pos_returns/len(df)*100:.1f}%)")
   372	print(f"  Negative returns:     {neg_returns}/{len(df)} ({neg_returns/len(df)*100:.1f}%)")
   373	print(f"  Binomial p-value:     {binom_p:.4f}")
   374	
   375	# ============================================================
   376	# 7. High-low range analysis (intraday vol proxy)
   377	# ============================================================
   378	print(f"\n--- K. Intraday Range (High-Low / Close) ---")
   379	nfp_range = df["high_low_range"].mean()
   380	non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
   381	range_ratio = nfp_range / non_nfp_range
   382	print(f"  NFP day range:        {nfp_range:.6f} ({nfp_range*100:.3f}%)")
   383	print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
   384	print(f"  Range ratio:          {range_ratio:.3f}x")
   385	
   386	# Volume analysis
   387	print(f"\n--- L. Volume Analysis ---")
   388	vol_ratio_data = df["volume_ratio"].dropna()
   389	print(f"  NFP/avg volume ratio: {vol_ratio_data.mean():.3f}x")
   390	print(f"  NFP volume > avg:     {(vol_ratio_data > 1).sum()}/{len(vol_ratio_data)} ({(vol_ratio_data > 1).mean()*100:.1f}%)")
   391	
   392	# ============================================================
   393	# 8. April NFP specific (for upcoming 04/03 article)
   394	# ============================================================
   395	print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
   396	april_nfp = df[df["month"] == 4]
   397	print(f"  April NFP events:     {len(april_nfp)}")
   398	print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
   399	print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
   400	print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
   401	if "4" in monthly_stats:
   402	    ms4 = monthly_stats["4"]
   403	    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")
   404	
   405	# ============================================================
   406	# 9. Summary conclusion
   407	# ============================================================
   408	print(f"\n{'=' * 60}")
   409	print("SUMMARY CONCLUSION")
   410	print("=" * 60)
   411	
   412	sig_level = 0.05
   413	conclusions = []
   414	
   415	if p_val_all < sig_level:
   416	    conclusions.append(f"NFP days show significantly higher vol ({vol_ratio_all:.2f}x, p={p_val_all:.4f})")
   417	else:
   418	    conclusions.append(f"NFP days do NOT show significantly higher vol ({vol_ratio_all:.2f}x, p={p_val_all:.4f})")
   419	
   420	if p_val_fri < sig_level:
   421	    conclusions.append(f"Even vs Friday baseline, NFP is significant ({vol_ratio_fri:.2f}x, p={p_val_fri:.4f})")
   422	else:
   423	    conclusions.append(f"Vs Friday baseline, NFP is also not significant ({vol_ratio_fri:.2f}x, p={p_val_fri:.4f})")
   424	
   425	if vol_crush.mean() < 0 and p_crush < sig_level:
   426	    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
   427	else:
   428	    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")
   429	
   430	if r_vix is not None and p_vix < sig_level:
   431	    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
   432	else:
   433	    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")
   434	
   435	for c in conclusions:
   436	    print(f"  • {c}")
   437	
   438	print(f"\n  Practical implication for 04/03 NFP:")
   439	print(f"    → NFP alone does not warrant reducing SPY exposure")
   440	print(f"    → Focus on VIX level and broader market conditions instead")
   441	print(f"    → Consistent with K513 findings (NFP 1.09x, NS)")
   442	
   443	# ============================================================
   444	# 9b. Correction audit: every published number, before vs after
   445	# ============================================================
   446	# A mean can sit still while the median and the win rate move underneath it,
   447	# so no claim is judged on its mean alone. Each item carries mean / median /
   448	# win rate / n / significance, and the flip test looks at all of them.
   449	print(f"\n{'=' * 60}")
   450	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
   451	print("=" * 60)
   452	
   453	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
   454	if not PROXY_PATH.exists():
   455	    raise FileNotFoundError(
   456	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
   457	        "only record of what the published article claimed. Do not regenerate it."
   458	    )
   459	proxy = json.loads(PROXY_PATH.read_text())
   460	
   461	
   462	def win_rate(sample, reference):
   463	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
   464	    ref_med = float(np.median(reference))
   465	    return float(np.mean(np.asarray(sample) > ref_med))
   466	
   467	
   468	# The proxy run only ever reported means, and a mean can hold still while the
   469	# median and the win rate move underneath it. Rather than leave the before-side
   470	# of those two columns null -- which would make the comparison unable to detect
   470	# of those two columns null -- which would make the comparison unable to detect
   471	# exactly the failure it is looking for -- rebuild the proxy-era distributions
   472	# from the ARCHIVED per-event data. The dates come out of the archive, so this
   473	# reconstructs history without reintroducing a proxy calendar generator.
   474	proxy_events = proxy["event_data"]
   475	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
   476	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
   477	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
   478	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
   479	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
   480	
   481	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   482	                       for e in proxy_events])
   483	_p_thr = proxy["regime_analysis"]["vix_median_split"]
   484	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   485	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   486	
   487	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
   488	# reconstruction is wrong and its medians cannot be trusted either.
   489	for _label, _rebuilt, _archived in (
   490	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   491	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   492	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   493	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   494	):
   495	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   496	        raise AssertionError(
   497	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   498	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   499	            "from a reconstruction that cannot reproduce the archived means."
   500	        )
   501	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   502	
   503	audit_items = {}
   504	
   505	
   506	def record(key, label, before, after, note=""):
   507	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   508	
   509	
   510	# --- 1.10x : NFP vs all non-NFP days ---
   511	record(
   512	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   513	    {
   514	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   515	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   516	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   517	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   518	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   519	        "n": proxy["sample"]["total_nfp_events"],
   520	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   521	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   522	    },
   523	    {
   524	        "mean_ratio": vol_ratio_all,
   525	        "nfp_mean": float(nfp_abs_returns.mean()),
   526	        "baseline_mean": baseline_abs_return,
   527	        "p_value": float(p_val_all),
   528	        "significant_5pct": bool(p_val_all < 0.05),
   529	        "n": int(len(df)),
   530	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   531	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   532	    },
   533	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   534	         "per-event data, not from the proxy run's own output (it only reported means).",
   535	)
   536	
   537	# --- 1.17x : NFP vs Friday-only baseline ---
   538	record(
   539	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   540	    {
   541	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   542	        "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   543	        "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   544	        "n": proxy["sample"]["total_nfp_events"],
   545	        "nfp_days_on_friday": proxy["sample"]["total_nfp_events"],
   546	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_fri_abs)),
   547	        "win_rate": win_rate(proxy_nfp_abs, proxy_fri_abs),
   548	    },
   549	    {
   550	        "mean_ratio": vol_ratio_fri,
   551	        "p_value": float(p_val_fri),
   552	        "significant_5pct": bool(p_val_fri < 0.05),
   553	        "n": int(len(df)),
   554	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   555	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(friday_non_nfp_abs)),
   556	        "win_rate": win_rate(nfp_abs_returns, friday_non_nfp_abs),
   557	    },
   558	    note="Under the proxy every NFP day was a Friday by construction, so this "
   559	         "test compared Fridays with Fridays. On the official calendar it no "
   560	         "longer does, which is a change in what the test means, not just in "
   561	         "its value.",
   562	)
   563	
   564	# --- 2.17x : high-VIX vs low-VIX regime ---
   565	proxy_reg = proxy["regime_analysis"]
   566	record(
   567	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   568	    {
   569	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
   570	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
   571	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
   572	        "n_high": proxy_reg["n_high"],
   573	        "n_low": proxy_reg["n_low"],
   574	        "p_value": proxy_reg["p_value"],
   575	        "significant_5pct": proxy_reg["p_value"] < 0.05,
   576	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
   577	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
   578	    },
   579	    {
   580	        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
   581	        "high_mean": float(high_vix.mean()),
   582	        "low_mean": float(low_vix.mean()),
   583	        "n_high": int(len(high_vix)),
   584	        "n_low": int(len(low_vix)),
   585	        "p_value": float(p_regime),
   586	        "significant_5pct": bool(p_regime < 0.05),
   587	        "median_ratio": float(high_vix.median() / low_vix.median()),
   588	        "win_rate": win_rate(high_vix.values, low_vix.values),
   589	    },
   590	)
   591	
   592	# --- 0.45 : pre-event VIX correlation ---
   593	proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
   594	record(
   595	    "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
   596	    {
   597	        "pearson_r": proxy_e["pearson_r"],
   598	        "pearson_p": proxy_e["pearson_p"],
   599	        "spearman_rho": proxy_e["spearman_rho"],
   600	        "spearman_p": proxy_e["spearman_p"],
   601	        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
   602	        "n": proxy["sample"]["total_nfp_events"],
   603	        "significant_5pct": proxy_e["pearson_p"] < 0.05,
   604	    },
   605	    {
   606	        "pearson_r": float(r_vix),
   607	        "pearson_p": float(p_vix),
   608	        "spearman_rho": float(rho_vix),
   609	        "spearman_p": float(p_rho_vix),
   610	        "slope_pct_per_vix_pt": float(slope) * 100,
   611	        "n": int(len(vix_valid)),
   612	        "significant_5pct": bool(p_vix < 0.05),
   613	    },
   614	)
   615	
   616	# --- 16.71 : the VIX median that splits the regimes ---
   617	# The article uses this threshold to place a specific date (2026-07-01 VIX
   618	# 16.59) on the low-VIX side. If the threshold crosses 16.59 the article's
   619	# worked example inverts, so it is audited as a claim in its own right.
   620	proxy_thr = proxy_reg["vix_median_split"]
   621	record(
   622	    "vix_median_threshold", "VIX median split (article: 16.71)",
   623	    {
   624	        "threshold": proxy_thr,
   625	        "n": proxy["sample"]["total_nfp_events"],
   626	        "places_20260701_vix_1659_in": "low" if 16.59 < proxy_thr else "high",
   627	    },
   628	    {
   629	        "threshold": float(vix_median),
   630	        "n": int(df["pre_vix"].notna().sum()),
   631	        "places_20260701_vix_1659_in": "low" if 16.59 < float(vix_median) else "high",
   632	    },
   633	)
   634	
   635	# --- 254 : the sample itself ---
   636	proxy_dates = {r["date"] for r in proxy["event_data"]}
   637	new_dates = {r["date"] for r in results}
   638	record(
   639	    "sample", "NFP event sample (article: 254 events)",
   640	    {
   641	        "n": proxy["sample"]["total_nfp_events"],
   642	        "date_range": proxy["sample"]["date_range"],
   643	        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
   644	    },
   645	    {
   646	        "n": int(len(df)),
   647	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   648	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   649	        "dates_in_common": len(proxy_dates & new_dates),
   650	        "proxy_only_dates": sorted(proxy_dates - new_dates),
   651	        "official_only_dates": sorted(new_dates - proxy_dates),
   652	    },
   653	    note="Equal counts do not mean equal samples -- check dates_in_common.",
   654	)
   655	
   656	
   657	def verdict_for(key):
   658	    """Flip test: significance change, sign change, or a >10% move in the headline."""
   659	    b, a = audit_items[key]["before"], audit_items[key]["after"]
   660	    reasons = []
   661	    if b.get("significant_5pct") is not None and a.get("significant_5pct") is not None:
   662	        if bool(b["significant_5pct"]) != bool(a["significant_5pct"]):
   663	            reasons.append(
   664	                "significance flipped "
   665	                f"({'sig' if b['significant_5pct'] else 'NS'} -> "
   666	                f"{'sig' if a['significant_5pct'] else 'NS'})"
   667	            )
   668	    # The mean is not trusted on its own: the median and the win rate are
   669	    # checked independently, because the failure mode this audit exists to
   670	    # catch is a stable mean sitting on top of a moved distribution.
   671	    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
   672	        if field in b and field in a and b[field] and a[field]:
   673	            rel = abs(a[field] - b[field]) / abs(b[field])
   674	            if rel > 0.10:
   675	                reasons.append(f"{field} moved {rel * 100:.1f}%")
   676	    if b.get("win_rate") and a.get("win_rate"):
   677	        if abs(a["win_rate"] - b["win_rate"]) > 0.05:
   678	            reasons.append(
   679	                f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
   680	            )
   681	    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
   682	        reasons.append("the article's worked example changes regime")
   683	    return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons
   684	
   685	
   686	print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
   687	for key, item in audit_items.items():
   688	    v, reasons = verdict_for(key)
   689	    item["verdict"], item["verdict_reasons"] = v, reasons
   690	    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
   691	                     if f in item["before"]), None)
   692	    bf = item["before"].get(headline)
   693	    af = item["after"].get(headline)
   694	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
   695	    print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
   696	    for r in reasons:
   697	        print(f"      - {r}")
   698	
   699	n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
   700	print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
   701	
   702	# ============================================================
   703	# 10. Save results
   704	# ============================================================
   705	print("\n[6/6] Saving results...")
   706	
   707	output = {
   708	    "experiment_id": "K528",
   709	    "title": "NFP Event Study on SPY Volatility",
   710	    "date": datetime.now(timezone.utc).isoformat(),
   711	    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
   712	    "event_date_source": {
   713	        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
   714	        "accessor": "volpred.data.event_dates.nfp_release_dates",
   715	        "fallback": "none - the run raises if the calendar is unreachable",
   716	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
   717	    },
   718	    "sample": {
   719	        "total_nfp_events": len(df),
   720	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   721	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   722	        "friday_baseline_days": int(friday_mask.sum()),
   723	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   724	    },
   725	    "main_results": {
   726	        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
   727	        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
   728	        "non_nfp_avg_abs_return": baseline_abs_return,
   729	        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
   730	        "friday_baseline_abs_return": friday_baseline,
   731	        "vol_ratio_vs_all": vol_ratio_all,
   732	        "vol_ratio_vs_friday": vol_ratio_fri,
   733	    },
   734	    "statistical_tests": {
   735	        "A_nfp_vs_all": {
   736	            "test": "Welch t-test",
   737	            "t_stat": float(t_stat_all),
   738	            "p_value": float(p_val_all),
   739	            "significant_5pct": bool(p_val_all < 0.05),
   740	        },
   700	print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
   701	
   702	# ============================================================
   703	# 10. Save results
   704	# ============================================================
   705	print("\n[6/6] Saving results...")
   706	
   707	output = {
   708	    "experiment_id": "K528",
   709	    "title": "NFP Event Study on SPY Volatility",
   710	    "date": datetime.now(timezone.utc).isoformat(),
   711	    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
   712	    "event_date_source": {
   713	        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
   714	        "accessor": "volpred.data.event_dates.nfp_release_dates",
   715	        "fallback": "none - the run raises if the calendar is unreachable",
   716	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
   717	    },
   718	    "sample": {
   719	        "total_nfp_events": len(df),
   720	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   721	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   722	        "friday_baseline_days": int(friday_mask.sum()),
   723	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   724	    },
   725	    "main_results": {
   726	        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
   727	        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
   728	        "non_nfp_avg_abs_return": baseline_abs_return,
   729	        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
   730	        "friday_baseline_abs_return": friday_baseline,
   731	        "vol_ratio_vs_all": vol_ratio_all,
   732	        "vol_ratio_vs_friday": vol_ratio_fri,
   733	    },
   734	    "statistical_tests": {
   735	        "A_nfp_vs_all": {
   736	            "test": "Welch t-test",
   737	            "t_stat": float(t_stat_all),
   738	            "p_value": float(p_val_all),
   739	            "significant_5pct": bool(p_val_all < 0.05),
   740	        },
   741	        "B_nfp_vs_friday": {
   742	            "test": "Welch t-test",
   743	            "t_stat": float(t_stat_fri),
   744	            "p_value": float(p_val_fri),
   745	            "significant_5pct": bool(p_val_fri < 0.05),
   746	        },
   747	        "C_wilcoxon": {
   748	            "test": "Mann-Whitney U (one-sided)",
   749	            "u_stat": float(u_stat),
   750	            "p_value": float(p_val_wilcox),
   751	            "significant_5pct": bool(p_val_wilcox < 0.05),
   752	        },
   753	        "D_vol_crush": {
   754	            "test": "One-sample t-test (post-pre diff)",
   755	            "pre_avg": float(df["pre_avg_abs_return"].mean()),
   756	            "post_avg": float(df["post_avg_abs_return"].mean()),
   757	            "diff": float(vol_crush.mean()),
   758	            "t_stat": float(t_crush),
   759	            "p_value": float(p_crush),
   760	            "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
   761	        },
   762	        "E_vix_predictive": {
   763	            "test": "Pearson + Spearman correlation",
   764	            "pearson_r": float(r_vix) if r_vix else None,
   765	            "pearson_p": float(p_vix) if p_vix else None,
   766	            "spearman_rho": float(rho_vix) if rho_vix else None,
   767	            "spearman_p": float(p_rho_vix) if p_rho_vix else None,
   768	            "slope": float(slope) if slope else None,
   769	            "interpretation": f"1pt VIX → {slope*100:.4f}% more |return|" if slope else None,
   770	        },
   771	        "F_vix_buildup": {
   772	            "test": "One-sample t-test (T-5 to T-1 VIX change)",
   773	            "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
   774	            "t_stat": float(t_buildup) if t_buildup else None,
   775	            "p_value": float(p_buildup) if p_buildup else None,
   776	            "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
   777	        },
   778	    },
   779	    "seasonal_analysis": monthly_stats,
   780	    "regime_analysis": {
   781	        "vix_median_split": float(vix_median),
   782	        "high_vix_nfp_abs_return": float(high_vix.mean()),
   783	        "low_vix_nfp_abs_return": float(low_vix.mean()),
   784	        "n_high": int(len(high_vix)),
   785	        "n_low": int(len(low_vix)),
   786	        "t_stat": float(t_regime),
   787	        "p_value": float(p_regime),
   788	    },
   789	    "time_trend": {
   790	        "first_half_abs_return": float(first_half.mean()),
   791	        "second_half_abs_return": float(second_half.mean()),
   792	        "t_stat": float(t_trend),
   793	        "p_value": float(p_trend),
   794	    },
   795	    "directional_bias": {
   796	        "positive_count": int(pos_returns),
   797	        "negative_count": int(neg_returns),
   798	        "total": int(pos_returns + neg_returns),
   799	        "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
   800	        "binomial_p": binom_p,
   801	    },
   802	    "intraday_range": {
   803	        "nfp_avg_range": float(nfp_range),
   804	        "non_nfp_avg_range": float(non_nfp_range),
   805	        "range_ratio": float(range_ratio),
   806	    },
   807	    "volume": {
   808	        "avg_volume_ratio": float(vol_ratio_data.mean()),
   809	        "pct_above_avg": float((vol_ratio_data > 1).mean()),
   810	    },
   811	    "april_nfp": {
   812	        "n": int(len(april_nfp)),
   813	        "avg_abs_return": float(april_nfp["event_abs_return"].mean()),
   814	        "avg_signed_return": float(april_nfp["event_return"].mean()),
   815	        "positive_rate": float((april_nfp["event_return"] > 0).mean()),
   816	        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
   817	    },
   818	    "conclusions": conclusions,
   819	    "practical_implication": (
   820	        "NFP does NOT warrant reducing SPY exposure. Vol ratio ~1.09x is statistically "
   821	        "insignificant across all tests. Consistent with K513. For 04/03 NFP: focus on "
   822	        "VIX level and broader conditions, not the NFP event itself."
   823	    ),
   824	    "references": [
   825	        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
   826	        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
   827	        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
   828	    ],
   829	    "event_data": results,  # full per-event data
   830	}
   831	
   832	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
   833	with open(out_path, "w") as f:
   834	    json.dump(output, f, indent=2, default=str)
   835	
   836	print(f"  Saved to: {out_path}")
   837	
   838	# The correction audit is written separately: it is the artifact the article
   839	# correction is justified against, and it must stay readable without wading
   840	# through 254 events of per-day data.
   841	audit_out = {
   842	    "experiment_id": "K528",
   843	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
   844	    "generated_at": datetime.now(timezone.utc).isoformat(),
   845	    "before_source": PROXY_PATH.name,
   846	    "after_source": out_path.name,
   847	    "event_date_source": output["event_date_source"],
   848	    "calendar_diff": {
   849	        "proxy_only_dates": sorted(proxy_dates - new_dates),
   850	        "official_only_dates": sorted(new_dates - proxy_dates),
   851	        "dates_in_common": len(proxy_dates & new_dates),
   852	        "n_proxy": len(proxy_dates),
   853	        "n_official": len(new_dates),
   854	        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
   855	    },
   856	    "win_rate_definition": (
   857	        "share of the sample exceeding the MEDIAN of its comparison group; "
   858	        "0.5 under the null"
   859	    ),
   860	    "items": audit_items,
   861	    "n_claims_flipped": n_flipped,
   862	    "n_claims_audited": len(audit_items),
   863	    "article_correction": {
   864	        "article_id": "mile_35eef830",
   865	        "status": "pending - filled in by the correction step",
   866	        "replacements": None,
   867	    },
   868	}
   869	audit_path = Path(__file__).parent / "k528_nfp_official_dates_results.json"
   870	with open(audit_path, "w") as f:
   871	    json.dump(audit_out, f, indent=2, default=str)
   872	print(f"  Saved to: {audit_path}")
   873	print("\nDone!")

exec
/bin/zsh -lc "find .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528 -maxdepth 2 -type f -print | sort
jq 'keys, .sample, .main_results, .event_data[0], .event_data[-1]' .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json
jq '{top_keys:keys, superseded_fields:{status:.status,event_date_source:.event_date_source,correction:.correction,superseded:.superseded,superseded_by:.superseded_by}, sample:.sample, main_results:.main_results}' .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
head -40 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
head -40 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/__pycache__/build_article_correction.cpython-312.pyc
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/__pycache__/k528_nfp_event_study.cpython-312.pyc
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/data/.gitkeep
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/references/.gitkeep
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/review_verdict.json
[
  "april_nfp",
  "conclusions",
  "data_source",
  "date",
  "directional_bias",
  "event_data",
  "event_date_source",
  "experiment_id",
  "intraday_range",
  "main_results",
  "practical_implication",
  "references",
  "regime_analysis",
  "sample",
  "seasonal_analysis",
  "statistical_tests",
  "time_trend",
  "title",
  "volume"
]
{
  "total_nfp_events": 253,
  "date_range": "2005-02-04 to 2026-03-06",
  "non_nfp_trading_days": 5087,
  "friday_baseline_days": 841,
  "nfp_days_on_friday": 231
}
{
  "nfp_avg_abs_return": 0.008275191081011284,
  "nfp_avg_abs_return_pct": "0.828%",
  "non_nfp_avg_abs_return": 0.007638268420351756,
  "non_nfp_avg_abs_return_pct": "0.764%",
  "friday_baseline_abs_return": 0.007194857331134232,
  "vol_ratio_vs_all": 1.0833857394907047,
  "vol_ratio_vs_friday": 1.1501536027965606
}
{
  "date": "2005-02-04",
  "year": 2005,
  "month": 2,
  "weekday": 4,
  "event_return": 0.01067596446186192,
  "event_abs_return": 0.01067596446186192,
  "pre_avg_abs_return": 0.003637976546006749,
  "post_avg_abs_return": 0.004438204116162092,
  "pre_vix": 11.789999961853027,
  "event_vix": 11.210000038146973,
  "post_vix_1d": 11.729999542236328,
  "vix_change_event": -0.5799999237060547,
  "high_low_range": 0.012060192196264896,
  "volume_ratio": 0.9459350091597117
}
{
  "date": "2026-03-06",
  "year": 2026,
  "month": 3,
  "weekday": 4,
  "event_return": -0.013107129910862048,
  "event_abs_return": 0.013107129910862048,
  "pre_avg_abs_return": 0.005363148241470039,
  "post_avg_abs_return": 0.006493442734216037,
  "pre_vix": 23.75,
  "event_vix": 29.489999771118164,
  "post_vix_1d": 25.5,
  "vix_change_event": 5.739999771118164,
  "high_low_range": 0.009444027989863117,
  "volume_ratio": 1.0906826345022151
}
{
  "top_keys": [
    "april_nfp",
    "conclusions",
    "data_source",
    "date",
    "directional_bias",
    "event_data",
    "experiment_id",
    "intraday_range",
    "main_results",
    "practical_implication",
    "references",
    "regime_analysis",
    "sample",
    "seasonal_analysis",
    "statistical_tests",
    "time_trend",
    "title",
    "volume"
  ],
  "superseded_fields": {
    "status": null,
    "event_date_source": null,
    "correction": null,
    "superseded": null,
    "superseded_by": null
  },
  "sample": {
    "total_nfp_events": 254,
    "date_range": "2005-02-04 to 2026-03-06",
    "non_nfp_trading_days": 5086,
    "friday_baseline_days": 833
  },
  "main_results": {
    "nfp_avg_abs_return": 0.008420922409653335,
    "nfp_avg_abs_return_pct": "0.842%",
    "non_nfp_avg_abs_return": 0.0076308537469923455,
    "non_nfp_avg_abs_return_pct": "0.763%",
    "friday_baseline_abs_return": 0.007208381049566983,
    "vol_ratio_vs_all": 1.1035360772013734,
    "vol_ratio_vs_friday": 1.168212716801256
  }
}
{
  "experiment_id": "K528",
  "title": "NFP Event Study on SPY Volatility",
  "date": "2026-03-27T12:26:19.183627+00:00",
  "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
  "sample": {
    "total_nfp_events": 254,
    "date_range": "2005-02-04 to 2026-03-06",
    "non_nfp_trading_days": 5086,
    "friday_baseline_days": 833
  },
  "main_results": {
    "nfp_avg_abs_return": 0.008420922409653335,
    "nfp_avg_abs_return_pct": "0.842%",
    "non_nfp_avg_abs_return": 0.0076308537469923455,
    "non_nfp_avg_abs_return_pct": "0.763%",
    "friday_baseline_abs_return": 0.007208381049566983,
    "vol_ratio_vs_all": 1.1035360772013734,
    "vol_ratio_vs_friday": 1.168212716801256
  },
  "statistical_tests": {
    "A_nfp_vs_all": {
      "test": "Welch t-test",
      "t_stat": 1.5249538617647196,
      "p_value": 0.1283682008960355,
      "significant_5pct": false
    },
    "B_nfp_vs_friday": {
      "test": "Welch t-test",
      "t_stat": 2.132732372841885,
      "p_value": 0.03354366521379227,
      "significant_5pct": true
    },
    "C_wilcoxon": {
      "test": "Mann-Whitney U (one-sided)",
      "u_stat": 710364.0,
      "p_value": 0.0036000239515961954,
      "significant_5pct": true
    },
    "D_vol_crush": {
{
  "experiment_id": "K528",
  "title": "NFP Event Study on SPY Volatility",
  "date": "2026-07-19T02:50:41.511727+00:00",
  "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
  "event_date_source": {
    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
    "accessor": "volpred.data.event_dates.nfp_release_dates",
    "fallback": "none - the run raises if the calendar is unreachable",
    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
  },
  "sample": {
    "total_nfp_events": 253,
    "date_range": "2005-02-04 to 2026-03-06",
    "non_nfp_trading_days": 5087,
    "friday_baseline_days": 841,
    "nfp_days_on_friday": 231
  },
  "main_results": {
    "nfp_avg_abs_return": 0.008275191081011284,
    "nfp_avg_abs_return_pct": "0.828%",
    "non_nfp_avg_abs_return": 0.007638268420351756,
    "non_nfp_avg_abs_return_pct": "0.764%",
    "friday_baseline_abs_return": 0.007194857331134232,
    "vol_ratio_vs_all": 1.0833857394907047,
    "vol_ratio_vs_friday": 1.1501536027965606
  },
  "statistical_tests": {
    "A_nfp_vs_all": {
      "test": "Welch t-test",
      "t_stat": 1.2346489119140018,
      "p_value": 0.21797058884479614,
      "significant_5pct": false
    },
    "B_nfp_vs_friday": {
      "test": "Welch t-test",
      "t_stat": 1.9076176053668994,
      "p_value": 0.05714400414517939,
      "significant_5pct": false
    },

exec
/bin/zsh -lc "python - <<'PY'
import requests
urls = [
'https://www.bls.gov/news.release/archives/empsit_01052024.htm',
'https://www.bls.gov/news.release/archives/empsit_08022024.htm',
'https://www.bls.gov/news.release/archives/empsit_05082020.htm',
'https://fred.stlouisfed.org/releases/calendar?rid=50&y=2024',
]
for u in urls:
    r=requests.get(u,timeout=30,headers={'User-Agent':'Mozilla/5.0'})
    print(r.status_code, len(r.content), r.url)
    txt=' '.join(r.text[:2000].split())
    print(txt[:300])
PY" in /Users/yhlai0911/volpred-research
 exited 1 in 31459ms:
403 1323 https://www.bls.gov/news.release/archives/empsit_01052024.htm
<!DOCTYPE HTML> <html lang="en-us"> <head> <meta http-equiv="Content-Type" content="text/html; charset=utf-8" /> <title>Access Denied</title> </head> <style type="text/css"> .centerDiv { width: 60%; height:200px; margin: 0 auto; background-color:#FFFFFF ; } </style> <body> <div class="centerDiv"> <h
403 1323 https://www.bls.gov/news.release/archives/empsit_08022024.htm
<!DOCTYPE HTML> <html lang="en-us"> <head> <meta http-equiv="Content-Type" content="text/html; charset=utf-8" /> <title>Access Denied</title> </head> <style type="text/css"> .centerDiv { width: 60%; height:200px; margin: 0 auto; background-color:#FFFFFF ; } </style> <body> <div class="centerDiv"> <h
403 1323 https://www.bls.gov/news.release/archives/empsit_05082020.htm
<!DOCTYPE HTML> <html lang="en-us"> <head> <meta http-equiv="Content-Type" content="text/html; charset=utf-8" /> <title>Access Denied</title> </head> <style type="text/css"> .centerDiv { width: 60%; height:200px; margin: 0 auto; background-color:#FFFFFF ; } </style> <body> <div class="centerDiv"> <h
Traceback (most recent call last):
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/connectionpool.py", line 449, in _make_request
    six.raise_from(e, None)
  File "<string>", line 3, in raise_from
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/connectionpool.py", line 444, in _make_request
    httplib_response = conn.getresponse()
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/http/client.py", line 1377, in getresponse
    response.begin()
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/http/client.py", line 320, in begin
    version, status, reason = self._read_status()
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/http/client.py", line 281, in _read_status
    line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/socket.py", line 704, in readinto
    return self._sock.recv_into(b)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/ssl.py", line 1241, in recv_into
    return self.read(nbytes, buffer)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/ssl.py", line 1099, in read
    return self._sslobj.read(len, buffer)
socket.timeout: The read operation timed out

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/requests/adapters.py", line 589, in send
    resp = conn.urlopen(
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/connectionpool.py", line 785, in urlopen
    retries = retries.increment(
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/util/retry.py", line 550, in increment
    raise six.reraise(type(error), error, _stacktrace)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/packages/six.py", line 770, in reraise
    raise value
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/connectionpool.py", line 703, in urlopen
    httplib_response = self._make_request(
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/connectionpool.py", line 451, in _make_request
    self._raise_timeout(err=e, url=url, timeout_value=read_timeout)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/urllib3/connectionpool.py", line 340, in _raise_timeout
    raise ReadTimeoutError(
urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(host='fred.stlouisfed.org', port=443): Read timed out. (read timeout=30)

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<stdin>", line 9, in <module>
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/requests/api.py", line 73, in get
    return request("get", url, params=params, **kwargs)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/requests/api.py", line 59, in request
    return session.request(method=method, url=url, **kwargs)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/requests/sessions.py", line 589, in request
    resp = self.send(prep, **send_kwargs)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/requests/sessions.py", line 703, in send
    r = adapter.send(request, **kwargs)
  File "/Users/yhlai0911/opt/anaconda3/lib/python3.9/site-packages/requests/adapters.py", line 635, in send
    raise ReadTimeout(e, request=request)
requests.exceptions.ReadTimeout: HTTPSConnectionPool(host='fred.stlouisfed.org', port=443): Read timed out. (read timeout=30)

exec
/bin/zsh -lc "curl -L --max-time 20 -sS -o /tmp/k528_bls_jan2024.html -w '%{http_code} %{size_download}\\n' https://www.bls.gov/news.release/archives/empsit_01052024.htm
rg -n -m 5 'Transmission|Employment Situation|January 5|January 10' /tmp/k528_bls_jan2024.html
curl -L --max-time 20 -sS -o /tmp/k528_bls_aug2024.html -w '%{http_code} %{size_download}\\n' https://www.bls.gov/news.release/archives/empsit_08022024.htm
rg -n -m 5 'Transmission|Employment Situation|August 2|August 21' /tmp/k528_bls_aug2024.html" in /Users/yhlai0911/volpred-research
 exited 1 in 483ms:
403 1323
403 1323

exec
/bin/zsh -lc "for u in https://www.bls.gov/news.release/archives/empsit_01052024.pdf https://www.bls.gov/news.release/archives/empsit_08022024.pdf https://www.bls.gov/news.release/archives/empsit_05082020.pdf; do curl -L --max-time 20 -A 'Mozilla/5.0' -sS -o /tmp/"'$(basename "$u") -w '"'%{http_code} %{size_download} %{url_effective}\\n' \""'$u"; done
file /tmp/empsit_*.pdf
for f in /tmp/empsit_*.pdf; do pdftotext -f 1 -l 1 "$f" - 2>/dev/null | sed -n '"'1,18p'; done" in /Users/yhlai0911/volpred-research
 succeeded in 712ms:
403 1323 https://www.bls.gov/news.release/archives/empsit_01052024.pdf
403 1323 https://www.bls.gov/news.release/archives/empsit_08022024.pdf
403 1323 https://www.bls.gov/news.release/archives/empsit_05082020.pdf
/tmp/empsit_01052024.pdf: HTML document text, ASCII text, with very long lines (338)
/tmp/empsit_05082020.pdf: HTML document text, ASCII text, with very long lines (338)
/tmp/empsit_08022024.pdf: HTML document text, ASCII text, with very long lines (338)

exec
/bin/zsh -lc "uv run python - <<'PY'
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
p=Path('.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json')
r=json.loads(p.read_text())
df=pd.DataFrame(r['event_data'])
x=df.event_abs_return.to_numpy()
hi=df.loc[df.pre_vix >= df.pre_vix.median(),'event_abs_return'].to_numpy()
lo=df.loc[df.pre_vix < df.pre_vix.median(),'event_abs_return'].to_numpy()
calc={
'n':len(df),'friday_n':int((df.weekday==4).sum()),'nfp_mean':x.mean(),
'vix_med':df.pre_vix.median(),'hi_mean':hi.mean(),'lo_mean':lo.mean(),
'regime_t_p':stats.ttest_ind(hi,lo,equal_var=False),
'pearson':stats.pearsonr(df.pre_vix,x),'spearman':stats.spearmanr(df.pre_vix,x),
'slope':np.polyfit(df.pre_vix,x,1)[0],
}
for k,v in calc.items(): print(k,v)
print('stored',r['sample'],r['main_results'],r['regime_analysis'],r['statistical_tests']['E_vix_predictive'])
# identify accessor-selected dates in months with multiple raw FRED release-id-50 dates
cache=Path('.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-27.json')
raw=pd.to_datetime(json.loads(cache.read_text()))
s=pd.Series(raw,index=raw)
for (y,m),g in s.groupby([raw.year,raw.month]):
    if len(g)>1: print('MULTIPLE',y,m,[str(d.date()) for d in g.tolist()],'selected',g.max().date())
PY" in /Users/yhlai0911/volpred-research
 succeeded in 2029ms:
n 253
friday_n 231
nfp_mean 0.008275191081011284
vix_med 16.690000534057617
hi_mean 0.011089691172140035
lo_mean 0.005438353687571986
regime_t_p TtestResult(statistic=np.float64(6.061575874792647), pvalue=np.float64(8.143424658634764e-09), df=np.float64(173.96033705929406))
pearson PearsonRResult(statistic=np.float64(0.4379026524892069), pvalue=np.float64(2.8166495806053283e-13))
spearman SignificanceResult(statistic=np.float64(0.33650562171674236), pvalue=np.float64(4.093044630758536e-08))
slope 0.0004234189924288398
stored {'total_nfp_events': 253, 'date_range': '2005-02-04 to 2026-03-06', 'non_nfp_trading_days': 5087, 'friday_baseline_days': 841, 'nfp_days_on_friday': 231} {'nfp_avg_abs_return': 0.008275191081011284, 'nfp_avg_abs_return_pct': '0.828%', 'non_nfp_avg_abs_return': 0.007638268420351756, 'non_nfp_avg_abs_return_pct': '0.764%', 'friday_baseline_abs_return': 0.007194857331134232, 'vol_ratio_vs_all': 1.0833857394907047, 'vol_ratio_vs_friday': 1.1501536027965606} {'vix_median_split': 16.690000534057617, 'high_vix_nfp_abs_return': 0.011089691172140035, 'low_vix_nfp_abs_return': 0.005438353687571986, 'n_high': 127, 'n_low': 126, 't_stat': 6.061575874792647, 'p_value': 8.143424658634764e-09} {'test': 'Pearson + Spearman correlation', 'pearson_r': 0.4379026524892069, 'pearson_p': 2.8166495806053283e-13, 'spearman_rho': 0.33650562171674236, 'spearman_p': 4.093044630758536e-08, 'slope': 0.0004234189924288398, 'interpretation': '1pt VIX → 0.0423% more |return|'}
MULTIPLE 2006 5 ['2006-05-05', '2006-05-08'] selected 2006-05-08
MULTIPLE 2012 12 ['2012-12-07', '2012-12-12'] selected 2012-12-12
MULTIPLE 2013 5 ['2013-05-03', '2013-05-06'] selected 2013-05-06
MULTIPLE 2020 5 ['2020-05-08', '2020-05-11'] selected 2020-05-11
MULTIPLE 2024 1 ['2024-01-05', '2024-01-10'] selected 2024-01-10
MULTIPLE 2024 8 ['2024-08-02', '2024-08-21'] selected 2024-08-21

exec
/bin/zsh -lc "uv run python - <<'PY'
import json
from pathlib import Path
import numpy as np, pandas as pd
from scipy import stats
base=Path('.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528')
new=json.loads((base/'k528_nfp_event_study_results.json').read_text())
old=json.loads((base/'k528_nfp_event_study_results_PROXY_SUPERSEDED.json').read_text())
N=pd.DataFrame(new['event_data']).set_index('date')
O=pd.DataFrame(old['event_data']).set_index('date')
swaps={
'2006-05-08':'2006-05-05','2012-12-12':'2012-12-07','2013-05-06':'2013-05-03',
'2020-05-11':'2020-05-08','2024-01-10':'2024-01-05','2024-08-21':'2024-08-02'}
T=N.drop(index=list(swaps)).copy()
T=pd.concat([T,O.loc[list(swaps.values())]]).sort_index()
x=T.event_abs_return.to_numpy()
# adjust all non-event sum: current baseline includes the six true events and excludes six bogus; reverse those
cur_all_n=new['sample']['non_nfp_trading_days']; cur_all_mean=new['main_results']['non_nfp_avg_abs_return']
all_sum=cur_all_n*cur_all_mean - O.loc[list(swaps.values()),'event_abs_return'].sum() + N.loc[list(swaps),'event_abs_return'].sum()
all_n=cur_all_n
all_mean=all_sum/all_n
# current friday baseline includes all six true events. bogus later are non-Friday, hence no add-back
cur_fn=new['sample']['friday_baseline_days']; cur_fm=new['main_results']['friday_baseline_abs_return']
fri_sum=cur_fn*cur_fm - O.loc[list(swaps.values()),'event_abs_return'].sum()
fri_n=cur_fn-6
fri_mean=fri_sum/fri_n
# Need full control samples variance for exact Welch; derive arrays not possible. Approx via archived baseline arrays absent.
# Reconstruct p via yfinance not here. Event measures and ratios exact from artifacts.
med=T.pre_vix.median(); hi=T[T.pre_vix>=med].event_abs_return; lo=T[T.pre_vix<med].event_abs_return
print('true_n',len(T),'friday_n',int((T.weekday==4).sum()))
print('nfp_mean',x.mean(),'all_mean',all_mean,'ratio_all',x.mean()/all_mean)
print('fri_n',fri_n,'fri_mean',fri_mean,'ratio_fri',x.mean()/fri_mean)
print('regime threshold',med,'means',hi.mean(),lo.mean(),'ratio',hi.mean()/lo.mean(),'n',len(hi),len(lo),'welch',stats.ttest_ind(hi,lo,equal_var=False))
print('pearson',stats.pearsonr(T.pre_vix,T.event_abs_return))
print('spearman',stats.spearmanr(T.pre_vix,T.event_abs_return))
print('slope',np.polyfit(T.pre_vix,T.event_abs_return,1)[0])
for wrong,right in swaps.items():
 print(wrong,'chosen',N.loc[wrong,['weekday','event_abs_return','pre_vix']].to_dict(),'should',right,O.loc[right,['weekday','event_abs_return','pre_vix']].to_dict())
PY" in /Users/yhlai0911/volpred-research
 exited 1 in 2187ms:
Traceback (most recent call last):
  File "<stdin>", line 14, in <module>
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pandas/core/indexing.py", line 1207, in __getitem__
    return self._getitem_axis(maybe_callable, axis=axis)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pandas/core/indexing.py", line 1438, in _getitem_axis
    return self._getitem_iterable(key, axis=axis)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pandas/core/indexing.py", line 1378, in _getitem_iterable
    keyarr, indexer = self._get_listlike_indexer(key, axis)
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pandas/core/indexing.py", line 1576, in _get_listlike_indexer
    keyarr, indexer = ax._get_indexer_strict(key, axis_name)
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pandas/core/indexes/base.py", line 6302, in _get_indexer_strict
    self._raise_if_missing(keyarr, indexer, axis_name)
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/pandas/core/indexes/base.py", line 6355, in _raise_if_missing
    raise KeyError(f"{not_found} not in index")
KeyError: "['2020-05-08'] not in index"

exec
/bin/zsh -lc "uv run python - <<'PY'
import json
from pathlib import Path
import numpy as np, pandas as pd, yfinance as yf
from scipy import stats
root=Path('.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp')
raw=pd.to_datetime(json.loads((root/'storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-27.json').read_text()))
s=pd.Series(raw,index=raw)
dates=pd.DatetimeIndex(sorted(s.groupby([raw.year,raw.month]).min().values))
spy=yf.download('SPY',start='2005-01-01',end='2026-03-27',progress=False)
vix=yf.download('"'^VIX'"',start='2005-01-01',end='2026-03-27',progress=False)
if isinstance(spy.columns,pd.MultiIndex): spy.columns=spy.columns.get_level_values(0)
if isinstance(vix.columns,pd.MultiIndex): vix.columns=vix.columns.get_level_values(0)
spy['Return']=spy['Close'].pct_change(); spy['AbsReturn']=spy.Return.abs(); spy=spy.dropna(subset=['Return'])
spy=spy.join(vix[['Close']].rename(columns={'Close':'VIX'}),how='left'); spy['VIX']=spy.VIX.ffill()
tr=spy.index; mapped=[]
for d in dates:
 c=tr[(tr>=d)&(tr<=d+pd.Timedelta(days=3))]
 if len(c): mapped.append(c[0])
valid=sorted(set(d for d in mapped if d>=tr[10] and d<=tr[-6]))
rows=[]; idx=list(tr)
for d in valid:
 pos=idx.index(d); pre=spy.iloc[pos-5:pos]; e=spy.iloc[pos]; post=spy.iloc[pos+1:pos+6]
 rows.append(dict(date=d,weekday=d.weekday(),event_abs_return=float(e.AbsReturn),pre_vix=float(pre.VIX.iloc[-1]),pre_avg_abs_return=float(pre.AbsReturn.mean()),post_avg_abs_return=float(post.AbsReturn.mean())))
df=pd.DataFrame(rows); x=df.event_abs_return.to_numpy(); non=spy[~spy.index.isin(set(valid))]; fri=non[non.index.weekday==4]
med=df.pre_vix.median(); hi=df[df.pre_vix>=med].event_abs_return; lo=df[df.pre_vix<med].event_abs_return
print('sample',len(df),'friday',int((df.weekday==4).sum()),'range',df.date.min().date(),df.date.max().date())
print('all',x.mean(),non.AbsReturn.mean(),x.mean()/non.AbsReturn.mean(),stats.ttest_ind(x,non.AbsReturn,equal_var=False))
print('fri',fri.AbsReturn.mean(),x.mean()/fri.AbsReturn.mean(),stats.ttest_ind(x,fri.AbsReturn,equal_var=False))
print('fri_event_only vs friday',df[df.weekday==4].event_abs_return.mean()/fri.AbsReturn.mean(),stats.ttest_ind(df[df.weekday==4].event_abs_return,fri.AbsReturn,equal_var=False))
print('regime',med,hi.mean(),lo.mean(),hi.mean()/lo.mean(),len(hi),len(lo),stats.ttest_ind(hi,lo,equal_var=False))
print('cor',stats.pearsonr(df.pre_vix,df.event_abs_return),stats.spearmanr(df.pre_vix,df.event_abs_return),np.polyfit(df.pre_vix,df.event_abs_return,1)[0])
PY" in /Users/yhlai0911/volpred-research
 succeeded in 3884ms:
sample 253 friday 237 range 2005-02-04 2026-03-06
all 0.008453086994788967 0.007629423402170562 1.107958825877205 TtestResult(statistic=np.float64(1.5962965567646519), pvalue=np.float64(0.11152261785592105), df=np.float64(287.11994457185926))
fri 0.007176440975409278 1.1778940318403275 TtestResult(statistic=np.float64(2.251647806217478), pvalue=np.float64(0.024875292251455964), df=np.float64(408.3884529275911))
fri_event_only vs friday 1.1901389457426323 TtestResult(statistic=np.float64(2.3327568762166306), pvalue=np.float64(0.0201945335683474), df=np.float64(371.27898534159647))
regime 16.690000534057617 0.011276176693044912 0.005562243143774878 2.027271444554689 128 125 TtestResult(statistic=np.float64(6.169002083299259), pvalue=np.float64(4.553485744923742e-09), df=np.float64(176.7881111529061))
cor PearsonRResult(statistic=np.float64(0.4404344838061744), pvalue=np.float64(1.9822337597616836e-13)) SignificanceResult(statistic=np.float64(0.3455048873701663), pvalue=np.float64(1.6699985504624933e-08)) 0.00042561483233382935

exec
/bin/zsh -lc "rg -n \"def apply_article_correction|def _splice\" src/volpred/publisher/article_correction.py
nl -ba src/volpred/publisher/article_correction.py | sed -n '1,320p'
rg -n 'mile_35eef830' storage/reports/feed.json | head
uv run python .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py --storage-dir /Users/yhlai0911/volpred-research/storage" in /Users/yhlai0911/volpred-research
 succeeded in 247ms:
validated 18/18 replacements, each matched exactly once
  @   416  總共 254 次 NFP 公布日的資料算過一遍...
  @   506  NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。...
  @   600  換句話說，這 1.10 倍的差距...
  @   730  NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一...
  @   833  所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1...
  @  1132  那 254 次 NFP 日裡...
  @  1159  VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71...
  @  1395  相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）...
  @  1480  VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。...
  @  1717  ![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]...
  @  1923  貼在歷史分界線 16.71 的下緣...
  @  2352  7/1 收盤的 16.59 距離 16.71 只差 0.12 點...
  @  2487  第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。...
  @  2625  高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。...
  @  2760  這跟 k528 在 254 場歷史樣本上得到的傾向一致...
  @  3014  254 場歷史樣本加上 7/2 這場實測...
  @  3131  樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinan...
  @  3383  VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；...

dry run -- nothing written. Re-run with --apply from the repo root.
plan recorded in k528_nfp_official_dates_results.json

exec
/bin/zsh -lc "git -C .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short experiments/k528
git -C .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff -- experiments/k528/k528_nfp_official_dates_results.json | sed -n '1,160p'
stat -f '%Sm %N' -t '%Y-%m-%dT%H:%M:%S%z' .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
?? experiments/k528/review_verdict.json
2026-07-19T13:09:11+0800 .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json

exec
/bin/zsh -lc "git -C .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short
git -C .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp log --oneline -8 -- experiments/k528
git -C .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff --stat main...HEAD -- experiments/k528 src/volpred/data/event_dates.py tests/test_nfp_official_release_dates.py
git -C .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff main...HEAD -- src/volpred/data/event_dates.py tests/test_nfp_official_release_dates.py | sed -n '1,320p'
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/review_verdict.json" in /Users/yhlai0911/volpred-research
 succeeded in 730ms:
?? experiments/k528/review_verdict.json
af2fad356 fix(k528): NFP 事件日改用官方日曆重跑，1 項顯著性翻轉
76aa426d0 chore(experiments+archive): migrate legacy experiment artifacts to canonical layout
 experiments/k528/README.md                         |  123 +-
 experiments/k528/build_article_correction.py       |  233 ++
 experiments/k528/k528_nfp_event_study.py           |  374 +-
 experiments/k528/k528_nfp_event_study_results.json | 3353 ++++++++-------
 ...8_nfp_event_study_results_PROXY_SUPERSEDED.json | 4268 ++++++++++++++++++++
 .../k528/k528_nfp_official_dates_results.json      |  457 +++
 tests/test_nfp_official_release_dates.py           |  131 +
 7 files changed, 7225 insertions(+), 1714 deletions(-)
diff --git a/tests/test_nfp_official_release_dates.py b/tests/test_nfp_official_release_dates.py
index 18957a417..213a7f874 100644
--- a/tests/test_nfp_official_release_dates.py
+++ b/tests/test_nfp_official_release_dates.py
@@ -328,3 +328,134 @@ class TestNoProxyResidue:
         assert [r["nfp_release_date"] for r in results["historical_nfp_table"]] == (
             EXPECTED_TRAILING_13
         )
+
+
+# ---------------------------------------------------------------------------
+# K528 -- the same proxy, the same bug, a 21-year sample.
+#
+# The sibling experiment above had 13 events. K528 had 254 and fed six numbers
+# straight into a published article (mile_35eef830). Correcting its calendar
+# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
+# (p 0.0335 -> 0.0571). Same module rather than a new file: "NFP event dates
+# are official" is one concern and should keep one enforcement owner.
+# ---------------------------------------------------------------------------
+
+K528_DIR = REPO_ROOT / "experiments" / "k528"
+K528_PY = K528_DIR / "k528_nfp_event_study.py"
+K528_RESULTS = K528_DIR / "k528_nfp_event_study_results.json"
+K528_AUDIT = K528_DIR / "k528_nfp_official_dates_results.json"
+
+
+def _load_k528(path):
+    import json
+
+    return json.loads(path.read_text(encoding="utf-8"))
+
+
+def _k528_event_dates():
+    return [pd.Timestamp(e["date"]) for e in _load_k528(K528_RESULTS)["event_data"]]
+
+
+def assert_not_first_friday_proxy(dates):
+    """Reject a calendar carrying the first-Friday proxy's fingerprints.
+
+    Three independent signatures, because a partial revert should be caught as
+    readily as a total one. This is the function the mutation test below fires
+    a proxy calendar at: a guard nobody has ever seen fail is not a guard.
+    """
+    dates = pd.DatetimeIndex(dates)
+    if len(dates) == 0:
+        raise AssertionError("empty calendar")
+
+    if (dates.weekday == 4).all():
+        raise AssertionError(
+            f"all {len(dates)} releases fall on a Friday. The official calendar "
+            "does not: BLS moves the release off Friday at holiday and shutdown "
+            "boundaries. This is the proxy's signature."
+        )
+
+    on_first_friday = [
+        d for d in dates if d.date() == _first_friday(d.year, d.month)
+    ]
+    if len(on_first_friday) == len(dates):
+        raise AssertionError(
+            "every release sits on the first Friday of its month -- proxy calendar"
+        )
+
+    phantom = [d for d in dates if (d.year, d.month) == (2025, 10)]
+    if phantom:
+        raise AssertionError(
+            f"calendar contains an October 2025 release ({phantom[0].date()}). "
+            "The shutdown cancelled it; only the proxy invents one."
+        )
+
+
+class TestK528UsesOfficialCalendar:
+    def test_defines_no_first_friday_helper(self):
+        src = K528_PY.read_text(encoding="utf-8")
+        assert "def get_first_friday" not in src
+        assert "def generate_nfp_dates" not in src
+        assert "(4 - first_day.weekday()) % 7" not in src
+
+    def test_imports_the_official_calendar(self):
+        src = K528_PY.read_text(encoding="utf-8")
+        assert "from volpred.data.event_dates import nfp_release_dates" in src
+
+    def test_results_declare_the_official_source_and_no_fallback(self):
+        source = _load_k528(K528_RESULTS)["event_date_source"]
+        assert "nfp_release_dates" in source["accessor"]
+        assert source["fallback"] == "none - the run raises if the calendar is unreachable"
+
+    def test_event_dates_carry_no_proxy_signature(self):
+        assert_not_first_friday_proxy(_k528_event_dates())
+
+    def test_sample_is_not_uniformly_friday(self):
+        """231 of 253, not 253 of 253. The gap is the corrected dates."""
+        results = _load_k528(K528_RESULTS)
+        n, on_friday = results["sample"]["total_nfp_events"], results["sample"]["nfp_days_on_friday"]
+        assert n == 253
+        assert on_friday == 231
+        assert on_friday < n
+
+    def test_audit_records_the_dates_that_changed(self):
+        diff = _load_k528(K528_AUDIT)["calendar_diff"]
+        assert diff["dates_in_common"] == 207
+        # The equal-looking sample sizes hide a 46-date swap; assert the swap,
+        # not the count, or a silent revert reads as unchanged.
+        assert len(diff["proxy_only_dates"]) == 47
+        assert len(diff["official_only_dates"]) == 46
+        assert "2025-10-03" in diff["proxy_only_dates"]
+        assert "2025-11-20" in diff["official_only_dates"]
+
+
+class TestProxyMutationIsCaught:
+    """Mutation test. Reverting to the proxy must turn the suite red, and the
+    only way to know that is to build the proxy calendar and watch the guard
+    reject it."""
+
+    @staticmethod
+    def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
+        out = []
+        for year in range(start_year, end_year + 1):
+            last = 12 if year < end_year else end_month
+            for month in range(1, last + 1):
+                out.append(pd.Timestamp(_first_friday(year, month)))
+        return pd.DatetimeIndex(out)
+
+    def test_the_proxy_calendar_is_rejected(self):
+        with pytest.raises(AssertionError, match="Friday"):
+            assert_not_first_friday_proxy(self._proxy_calendar())
+
+    def test_phantom_october_2025_alone_is_enough_to_fail(self):
+        """A partial revert that keeps some real dates still gets caught."""
+        mixed = pd.DatetimeIndex(
+            _k528_event_dates() + [pd.Timestamp("2025-10-03")]
+        )
+        with pytest.raises(AssertionError, match="October 2025"):
+            assert_not_first_friday_proxy(mixed)
+
+    def test_the_guard_accepts_the_official_calendar(self, official):
+        """The other half of the mutation test: the guard must not reject
+        everything. A guard that always fails is as useless as one that never
+        does."""
+        assert_not_first_friday_proxy(official)
     1	{
     2	  "kid": "k528",
     3	  "verdict": "FILL: PASS or FAIL — anything but PASS blocks the merge",
     4	  "reviewer": "FILL: model / effort",
     5	  "reviewed_at": "FILL: ISO8601",
     6	  "reviewed_commit": "FILL: the frozen SHA you read",
     7	  "review_artifact": "FILL: relpath of the written review",
     8	  "blocking_defects": [
     9	    "FILL: one entry per defect that makes this a FAIL; [] if PASS"
    10	  ],
    11	  "reviewed_sha256": {
    12	    "README.md": "a51a9c6a6abe9667fd86e58ad27a641d6732f5a6fccdc8e4e741ec1dec936083",
    13	    "build_article_correction.py": "922805051b2fa064b433485093b40b0e4677b69ea0e813e1576e6c02428fd6c9",
    14	    "k528_nfp_event_study.py": "d27afe1b822034272ae6c44493af092405e95cb55370651dda9734e7f1d2944a",
    15	    "k528_nfp_event_study_results.json": "84070e93f77f02abac8c5660e897e6093c6fb6835b3df520bb10dc33d7dde339",
    16	    "k528_nfp_official_dates_results.json": "41440b18d33134ad87772dafcbae0fc9603d1a5e53297111f1b6d76855040911"
    17	  }
    18	}

exec
/bin/zsh -lc "BASE=.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528
rg -n '2006-05-08|2012-12-12|2013-05-06|2020-05-11|2024-01-10|2024-08-21|\"p_value\": 0.057144|\"nfp_days_on_friday\": 231|\"nfp_avg_abs_return\": 0.008275|\"high_vix_nfp_abs_return\": 0.011089|\"low_vix_nfp_abs_return\": 0.005438|\"pearson_r\": 0.437902|\"spearman_rho\": 0.336505' \""'$BASE/k528_nfp_event_study_results.json" "$BASE/k528_nfp_official_dates_results.json"
rg -n '"'\"experiment_id\"|\"title\"|\"date\"|\"data_source\"|\"sample\"' \""'$BASE/k528_nfp_event_study_results_PROXY_SUPERSEDED.json" | head -12
rg -n '"'0.828%|1.08 倍|1.15 倍|2.04 倍|0.042|16.69|253 個|253 次|p=0.057' \""'$BASE/build_article_correction.py"
rg -n '"'取不到就 raise|231 場|唯一的結論翻轉|p=0.0571|全部恰好命中|圖表仍是修正前' \""'$BASE/README.md"' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:66:      "2006-05-08",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:77:      "2012-12-12",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:79:      "2013-05-06",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:94:      "2020-05-11",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:101:      "2024-01-10",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:103:      "2024-08-21",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:157:        "p_value": 0.05714400414517939,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:160:        "nfp_days_on_friday": 231,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:212:        "pearson_r": 0.4379026524892069,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:214:        "spearman_rho": 0.33650562171674236,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:304:          "2006-05-08",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:315:          "2012-12-12",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:317:          "2013-05-06",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:332:          "2020-05-11",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:339:          "2024-01-10",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:341:          "2024-08-21",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:17:    "nfp_days_on_friday": 231
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:20:    "nfp_avg_abs_return": 0.008275191081011284,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:38:      "p_value": 0.05714400414517939,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:58:      "pearson_r": 0.4379026524892069,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:60:      "spearman_rho": 0.33650562171674236,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:161:    "high_vix_nfp_abs_return": 0.011089691172140035,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:162:    "low_vix_nfp_abs_return": 0.005438353687571986,
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:451:      "date": "2006-05-08",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:1715:      "date": "2012-12-12",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:1795:      "date": "2013-05-06",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3139:      "date": "2020-05-11",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3843:      "date": "2024-01-10",
.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955:      "date": "2024-08-21",
2:  "experiment_id": "K528",
3:  "title": "NFP Event Study on SPY Volatility",
4:  "date": "2026-03-27T12:26:19.183627+00:00",
5:  "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
6:  "sample": {
204:      "date": "2005-02-04",
220:      "date": "2005-03-04",
236:      "date": "2005-04-01",
252:      "date": "2005-05-06",
268:      "date": "2005-06-03",
284:      "date": "2005-07-01",
300:      "date": "2005-08-05",
45:        "總共 253 次 NFP 公布日的資料算過一遍",
50:        "NFP 當日 SPY 的平均絕對日報酬是 0.828%，非 NFP 交易日是 0.764%，兩者相除是 1.08 倍。",
54:        "換句話說，這 1.08 倍的差距",
60:        "NFP 當日波動是這個基準的 1.15 倍，但用 Welch t 檢定算下來，這個差距並沒有達到顯著水準"
61:        "（p=0.057，差一點過線但沒過）。"
67:        "所以精確的講法是：NFP 日看起來比一般週五抖一點（1.15 倍），但這個差距沒有通過顯著性檢定；"
68:        "拿全部交易日當對照，放大效果（1.08 倍）同樣談不上統計顯著。兩個基準指向同一件事——"
74:        "那 253 次 NFP 日裡",
80:        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
81:        "分界點是歷史中位數 16.69。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.11%；"
82:        "VIX 低於中位數的 126 次，只有 0.54%。兩者相差 2.04 倍",
91:        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.042 個百分點。",
96:        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.04 倍）]",
101:        "貼在歷史分界線 16.69 的下緣",
105:        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
112:        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.08 倍、對週五基準是 1.15 倍，"
118:        "高低體制差 2.04 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
132:        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
142:        "改用官方日期後為 1.15 倍且未達顯著（p=0.057）。"
147:        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 127 與 126 筆；",
217:                "(1.17x p=0.0335 -> 1.15x p=0.0571)."
21:- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 231 場在週五
28:release id 50），且**取不到就 raise，不回退 proxy**。
51:| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.150× (p=0.0571, **不顯著**) | **結論翻轉** |
59:**唯一的結論翻轉**：NFP 對「非 NFP 週五」基準的差距，原本 p=0.0335 達 5% 顯著，
60:修正後 p=0.0571 **未達顯著**。這一項在線上文章 `mile_35eef830` 被明確寫成「達到顯著水準」，
93:canonical 文章驗證，全部恰好命中一次。

exec
/bin/zsh -lc "nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py | sed -n '69,136p'
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py | sed -n '152,233p'
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py | sed -n '63,151p'
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py | sed -n '828,874p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
    69	def _fetch(release_id: int, start: str, end: str) -> list[str]:
    70	    r = requests.get(
    71	        "https://api.stlouisfed.org/fred/release/dates",
    72	        params={
    73	            "release_id": release_id,
    74	            "api_key": _api_key(),
    75	            "file_type": "json",
    76	            "realtime_start": start,
    77	            "realtime_end": end,
    78	            # Without this, ALFRED only returns releases that already carry data, so
    79	            # scheduled-but-not-yet-published dates (the ones an upcoming-event
    80	            # populator actually needs) are missing. Verified 2026-07-12 that it does
    81	            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
    82	            # shutdown, stays absent either way.
    83	            "include_release_dates_with_no_data": "true",
    84	            "limit": 1000,
    85	            "sort_order": "asc",
    86	        },
    87	        timeout=30,
    88	    )
    89	    r.raise_for_status()
    90	    return [d["date"] for d in r.json()["release_dates"]]
    91	
    92	
    93	def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
    94	    """Official news-release dates for `event` within [start, end].
    95	
    96	    Monthly releases can carry off-cycle entries (annual seasonal-factor revisions
    97	    are filed against the same release id). The news release is one per calendar
    98	    month, so we keep the last entry in each month.
    99	
   100	    Raises rather than falling back — a silently-wrong event date is worse than a
   101	    failed run, because it produces plausible numbers.
   102	    """
   103	    if event not in RELEASE_IDS:
   104	        raise KeyError(f"unknown event {event!r}; known: {sorted(RELEASE_IDS)}")
   105	
   106	    cache = _CACHE_DIR / f"{event}_{start}_{end}.json"
   107	    if use_cache and cache.exists():
   108	        age = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cache.stat().st_mtime, unit="s")
   109	        if age < _CACHE_TTL:
   110	            raw = json.loads(cache.read_text())
   111	        else:
   112	            raw = None
   113	    else:
   114	        raw = None
   115	
   116	    if raw is None:
   117	        raw = _fetch(RELEASE_IDS[event], start, end)
   118	        cache.parent.mkdir(parents=True, exist_ok=True)
   119	        cache.write_text(json.dumps(raw) + "\n")
   120	
   121	    dates = pd.to_datetime(raw)
   122	    if len(dates) == 0:
   123	        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
   124	    s = pd.Series(dates, index=dates)
   125	    monthly = s.groupby([dates.year, dates.month]).max()
   126	    return pd.DatetimeIndex(sorted(monthly.values))
   127	
   128	
   129	def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   130	    return release_dates("CPI_US", start, end, **kw)
   131	
   132	
   133	def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   134	    return release_dates("NFP_US", start, end, **kw)
   152	def load_article_content(storage_dir: Path) -> str:
   153	    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
   154	    art = next((a for a in feed if isinstance(a, dict) and a.get("id") == ARTICLE_ID), None)
   155	    if art is None:
   156	        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
   157	    return art.get("content") or ""
   158	
   159	
   160	def validate(storage_dir: Path) -> list[dict]:
   161	    """Resolve every replacement against the live article. Raises if any does
   162	    not match exactly once, before a single byte is written."""
   163	    from volpred.publisher.article_correction import _splice
   164	
   165	    content = load_article_content(storage_dir)
   166	    spans = _splice(content, REPLACEMENTS)
   167	    return [
   168	        {"index": i, "hits": 1, "from": s["from"], "to": s["to"], "offset": s["start"]}
   169	        for i, s in enumerate(sorted(spans, key=lambda x: x["start"]))
   170	    ]
   171	
   172	
   173	def record_plan(validated: list[dict], applied: dict | None) -> None:
   174	    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
   175	    audit["article_correction"] = {
   176	        "article_id": ARTICLE_ID,
   177	        "status": "applied" if applied else "validated_not_applied",
   178	        "n_replacements": len(REPLACEMENTS),
   179	        "all_matched_exactly_once": True,
   180	        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
   181	        "apply_result": applied,
   182	        "residual_gap": (
   183	            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
   184	            "and the two lazypack images still render proxy-era numbers. Text and images "
   185	            "now disagree; the article carries a visible note saying so. Regenerating and "
   186	            "re-uploading them is follow-up work outside this worktree's scope."
   187	        ),
   188	    }
   189	    AUDIT_PATH.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
   190	
   191	
   192	def main() -> int:
   193	    ap = argparse.ArgumentParser(description=__doc__)
   194	    ap.add_argument("--apply", action="store_true",
   195	                    help="write the correction (main thread, repo root only)")
   196	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
   197	    args = ap.parse_args()
   198	
   199	    storage_dir = Path(args.storage_dir)
   200	    validated = validate(storage_dir)
   201	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   202	    for v in validated:
   203	        head = v["from"].splitlines()[0][:64]
   204	        print(f"  @{v['offset']:>6}  {head}...")
   205	
   206	    applied = None
   207	    if args.apply:
   208	        from volpred.publisher.article_correction import apply_article_correction
   209	
   210	        applied = apply_article_correction(
   211	            ARTICLE_ID,
   212	            content_replacements=REPLACEMENTS,
   213	            summary=(
   214	                "K528 event dates corrected from a first-Friday proxy to the official BLS "
   215	                "release calendar (46 of 254 dates were wrong). All six headline numbers "
   216	                "restated; the NFP-vs-Friday gap is no longer statistically significant "
   217	                "(1.17x p=0.0335 -> 1.15x p=0.0571)."
   218	            ),
   219	            action="content_correction",
   220	            storage_dir=str(storage_dir),
   221	        )
   222	        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
   223	              f"synced={applied['synced']}")
   224	    else:
   225	        print("\ndry run -- nothing written. Re-run with --apply from the repo root.")
   226	
   227	    record_plan(validated, applied)
   228	    print(f"plan recorded in {AUDIT_PATH.name}")
   229	    return 0
   230	
   231	
   232	if __name__ == "__main__":
   233	    raise SystemExit(main())
    63	SAMPLE_START = "2005-01-01"
    64	SAMPLE_END = "2026-03-27"
    65	
    66	# ============================================================
    67	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
    68	# ============================================================
    69	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
    70	    """Official NFP (Employment Situation) release dates.
    71	
    72	    Deliberately has no except branch. If the release calendar cannot be
    73	    reached, this run must die -- a proxy calendar produces plausible numbers
    74	    from non-events, which is worse than no numbers at all. See the CORRECTION
    75	    note in the module docstring.
    76	    """
    77	    dates = nfp_release_dates(start, end)
    78	    if len(dates) == 0:
    79	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
    80	    return list(dates)
    81	
    82	
    83	# ============================================================
    84	# 2. Download data
    85	# ============================================================
    86	print("=" * 60)
    87	print("K528: NFP Event Study on SPY Volatility")
    88	print("=" * 60)
    89	
    90	print("\n[1/6] Downloading SPY and VIX data...")
    91	spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
    92	vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)
    93	
    94	# Handle multi-level columns from yfinance
    95	if isinstance(spy.columns, pd.MultiIndex):
    96	    spy.columns = spy.columns.get_level_values(0)
    97	if isinstance(vix.columns, pd.MultiIndex):
    98	    vix.columns = vix.columns.get_level_values(0)
    99	
   100	# Calculate returns
   101	spy["Return"] = spy["Close"].pct_change()
   102	spy["AbsReturn"] = spy["Return"].abs()
   103	spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
   104	spy.dropna(subset=["Return"], inplace=True)
   105	
   106	# Merge VIX
   107	vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
   108	spy = spy.join(vix_close, how="left")
   109	spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays
   110	
   111	print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
   112	print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")
   113	
   114	# ============================================================
   115	# 3. Map NFP dates to trading days
   116	# ============================================================
   117	print("\n[2/6] Mapping NFP dates to trading days...")
   118	
   119	nfp_calendar = load_nfp_dates()
   120	trading_dates = spy.index
   121	
   122	# The proxy forced every event onto a Friday. The official calendar does not,
   123	# and that is load-bearing for the Friday-baseline test below.
   124	n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
   125	print(f"  Official releases: {len(nfp_calendar)} "
   126	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
   127	
   128	# Map each NFP date to nearest trading day (could be holiday/early close)
   129	nfp_trading_dates = []
   130	for nfp_date in nfp_calendar:
   131	    nfp_ts = pd.Timestamp(nfp_date)
   132	    # Find exact match or next trading day
   133	    if nfp_ts in trading_dates:
   134	        nfp_trading_dates.append(nfp_ts)
   135	    else:
   136	        # Find nearest trading day within 3 days
   137	        mask = (trading_dates >= nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
   138	        candidates = trading_dates[mask]
   139	        if len(candidates) > 0:
   140	            nfp_trading_dates.append(candidates[0])
   141	
   142	nfp_trading_dates = sorted(set(nfp_trading_dates))
   143	
   144	# Only keep dates within our data range (with enough buffer for pre/post windows)
   145	valid_nfp = [d for d in nfp_trading_dates
   146	             if d >= trading_dates[10] and d <= trading_dates[-6]]
   147	
   148	print(f"  Total NFP dates generated: {len(nfp_calendar)}")
   149	print(f"  Matched to trading days: {len(nfp_trading_dates)}")
   150	print(f"  Valid (with pre/post window): {len(valid_nfp)}")
   151	
   828	    ],
   829	    "event_data": results,  # full per-event data
   830	}
   831	
   832	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
   833	with open(out_path, "w") as f:
   834	    json.dump(output, f, indent=2, default=str)
   835	
   836	print(f"  Saved to: {out_path}")
   837	
   838	# The correction audit is written separately: it is the artifact the article
   839	# correction is justified against, and it must stay readable without wading
   840	# through 254 events of per-day data.
   841	audit_out = {
   842	    "experiment_id": "K528",
   843	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
   844	    "generated_at": datetime.now(timezone.utc).isoformat(),
   845	    "before_source": PROXY_PATH.name,
   846	    "after_source": out_path.name,
   847	    "event_date_source": output["event_date_source"],
   848	    "calendar_diff": {
   849	        "proxy_only_dates": sorted(proxy_dates - new_dates),
   850	        "official_only_dates": sorted(new_dates - proxy_dates),
   851	        "dates_in_common": len(proxy_dates & new_dates),
   852	        "n_proxy": len(proxy_dates),
   853	        "n_official": len(new_dates),
   854	        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
   855	    },
   856	    "win_rate_definition": (
   857	        "share of the sample exceeding the MEDIAN of its comparison group; "
   858	        "0.5 under the null"
   859	    ),
   860	    "items": audit_items,
   861	    "n_claims_flipped": n_flipped,
   862	    "n_claims_audited": len(audit_items),
   863	    "article_correction": {
   864	        "article_id": "mile_35eef830",
   865	        "status": "pending - filled in by the correction step",
   866	        "replacements": None,
   867	    },
   868	}
   869	audit_path = Path(__file__).parent / "k528_nfp_official_dates_results.json"
   870	with open(audit_path, "w") as f:
   871	    json.dump(audit_out, f, indent=2, default=str)
   872	print(f"  Saved to: {audit_path}")
   873	print("\nDone!")

exec
/bin/zsh -lc "uv run python - <<'PY'
import json
from pathlib import Path
import pandas as pd, yfinance as yf
from scipy import stats
p=Path('.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json')
r=json.loads(p.read_text()); dates=pd.DatetimeIndex([e['date'] for e in r['event_data']])
spy=yf.download('SPY',start='2005-01-01',end='2026-03-27',progress=False)
if isinstance(spy.columns,pd.MultiIndex): spy.columns=spy.columns.get_level_values(0)
spy['Return']=spy.Close.pct_change(); spy['AbsReturn']=spy.Return.abs(); spy=spy.dropna(subset=['Return'])
x=spy.loc[dates,'AbsReturn']; non=spy[~spy.index.isin(set(dates))]; fri=non[non.index.weekday==4]
print('artifact-calendar reproduction')
print(len(x),x.mean(),non.AbsReturn.mean(),x.mean()/non.AbsReturn.mean(),stats.ttest_ind(x,non.AbsReturn,equal_var=False))
print(len(fri),fri.AbsReturn.mean(),x.mean()/fri.AbsReturn.mean(),stats.ttest_ind(x,fri.AbsReturn,equal_var=False))
PY" in /Users/yhlai0911/volpred-research
 succeeded in 4205ms:
artifact-calendar reproduction
253 0.008275180010500968 0.007638267092065077 1.083384478541938 TtestResult(statistic=np.float64(1.2346301534449453), pvalue=np.float64(0.21797756288886927), df=np.float64(287.14300774036207))
841 0.007194853410407118 1.1501526908847362 TtestResult(statistic=np.float64(1.9076051396362153), pvalue=np.float64(0.057145621385035095), df=np.float64(407.1156108957851))

codex
獨立重算已確認：現有 JSON 的算術在「目前選錯的日期集合」內是一致的；問題不是公式抄錯，而是日期 accessor 把同月較晚的非 headline 更新當成 NFP。把六個重複月份改回該月實際 Employment Situation 首發日後，NFP-vs-Friday 變為約 1.178×、p≈0.0249，原修正案宣稱的「顯著→不顯著」反而不成立。接著我會跑防迴歸測試並檢查它為何沒攔住這個錯誤。
exec
/bin/zsh -lc 'PYTHONDONTWRITEBYTECODE=1 uv run pytest -p no:cacheprovider tests/test_nfp_official_release_dates.py -q' in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 3207ms:
..........................................                               [100%]
42 passed in 2.00s

已定位 blocking calendar-selection defect，並以相同 yfinance 規格重算確認它會推翻修正案的核心顯著性翻轉。
  ✓ 讀取 handoff、error log 與 K528 審查檔案
  ✓ 驗證官方日期 fail-closed、事件對齊與統計重算
  → 逐條比對 18 條文章更正並審查新舊結果揭露
  • 檢查 lookahead、seed、原子寫入並形成裁決
已定位 blocking calendar-selection defect，並以相同 yfinance 規格重算確認它會推翻修正案的核心顯著性翻轉。
  ✓ 讀取 handoff、error log 與 K528 審查檔案
  ✓ 驗證官方日期 fail-closed、事件對齊與統計重算
  → 逐條比對 18 條文章更正並審查新舊結果揭露
  • 檢查 lookahead、seed、原子寫入並形成裁決
exec
/bin/zsh -lc "nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json | sed -n '125,255p'
nl -ba .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json | sed -n '430,460p'
rg -n 'CONCLUSION_FLIPPED|n_claims_flipped' .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
   125	        "significant_5pct": false,
   126	        "n": 254,
   127	        "median_ratio": 1.1896204866255515,
   128	        "win_rate": 0.5551181102362205
   129	      },
   130	      "after": {
   131	        "mean_ratio": 1.0833857394907047,
   132	        "nfp_mean": 0.008275191081011284,
   133	        "baseline_mean": 0.007638268420351756,
   134	        "p_value": 0.21797058884479614,
   135	        "significant_5pct": false,
   136	        "n": 253,
   137	        "median_ratio": 1.1357040852615625,
   138	        "win_rate": 0.549407114624506
   139	      },
   140	      "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
   141	      "verdict": "NUMERIC_ADJUSTMENT",
   142	      "verdict_reasons": []
   143	    },
   144	    "vol_ratio_vs_friday": {
   145	      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
   146	      "before": {
   147	        "mean_ratio": 1.168212716801256,
   148	        "p_value": 0.03354366521379227,
   149	        "significant_5pct": true,
   150	        "n": 254,
   151	        "nfp_days_on_friday": 254,
   152	        "median_ratio": 1.2091843441916237,
   153	        "win_rate": 0.562992125984252
   154	      },
   155	      "after": {
   156	        "mean_ratio": 1.1501536027965606,
   157	        "p_value": 0.05714400414517939,
   158	        "significant_5pct": false,
   159	        "n": 253,
   160	        "nfp_days_on_friday": 231,
   161	        "median_ratio": 1.1608717980245844,
   162	        "win_rate": 0.5612648221343873
   163	      },
   164	      "note": "Under the proxy every NFP day was a Friday by construction, so this test compared Fridays with Fridays. On the official calendar it no longer does, which is a change in what the test means, not just in its value.",
   165	      "verdict": "CONCLUSION_FLIPPED",
   166	      "verdict_reasons": [
   167	        "significance flipped (sig -> NS)"
   168	      ]
   169	    },
   170	    "regime_ratio": {
   171	      "label": "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   172	      "before": {
   173	        "mean_ratio": 2.1670599373202153,
   174	        "high_mean": 0.011524027931522324,
   175	        "low_mean": 0.005317816887784345,
   176	        "n_high": 127,
   177	        "n_low": 127,
   178	        "p_value": 2.8361186837189765e-10,
   179	        "significant_5pct": true,
   180	        "median_ratio": 2.2653573776192792,
   181	        "win_rate": 0.7165354330708661
   182	      },
   183	      "after": {
   184	        "mean_ratio": 2.0391632852940007,
   185	        "high_mean": 0.011089691172140035,
   186	        "low_mean": 0.005438353687571986,
   187	        "n_high": 127,
   188	        "n_low": 126,
   189	        "p_value": 8.143424658634764e-09,
   190	        "significant_5pct": true,
   191	        "median_ratio": 2.023040371729799,
   192	        "win_rate": 0.6850393700787402
   193	      },
   194	      "note": "",
   195	      "verdict": "CONCLUSION_FLIPPED",
   196	      "verdict_reasons": [
   197	        "median_ratio moved 10.7%"
   198	      ]
   199	    },
   200	    "vix_correlation": {
   201	      "label": "Pre-event VIX vs event-day |return| (article: r=0.45)",
   202	      "before": {
   203	        "pearson_r": 0.45116558631194703,
   204	        "pearson_p": 3.854493703611817e-14,
   205	        "spearman_rho": 0.3766062270606868,
   206	        "spearman_p": 5.561878132730772e-10,
   207	        "slope_pct_per_vix_pt": 0.04387491083793095,
   208	        "n": 254,
   209	        "significant_5pct": true
   210	      },
   211	      "after": {
   212	        "pearson_r": 0.4379026524892069,
   213	        "pearson_p": 2.8166495806053283e-13,
   214	        "spearman_rho": 0.33650562171674236,
   215	        "spearman_p": 4.093044630758536e-08,
   216	        "slope_pct_per_vix_pt": 0.04234189924288398,
   217	        "n": 253,
   218	        "significant_5pct": true
   219	      },
   220	      "note": "",
   221	      "verdict": "NUMERIC_ADJUSTMENT",
   222	      "verdict_reasons": []
   223	    },
   224	    "vix_median_threshold": {
   225	      "label": "VIX median split (article: 16.71)",
   226	      "before": {
   227	        "threshold": 16.710000038146973,
   228	        "n": 254,
   229	        "places_20260701_vix_1659_in": "low"
   230	      },
   231	      "after": {
   232	        "threshold": 16.690000534057617,
   233	        "n": 253,
   234	        "places_20260701_vix_1659_in": "low"
   235	      },
   236	      "note": "",
   237	      "verdict": "NUMERIC_ADJUSTMENT",
   238	      "verdict_reasons": []
   239	    },
   240	    "sample": {
   241	      "label": "NFP event sample (article: 254 events)",
   242	      "before": {
   243	        "n": 254,
   244	        "date_range": "2005-02-04 to 2026-03-06",
   245	        "non_nfp_trading_days": 5086
   246	      },
   247	      "after": {
   248	        "n": 253,
   249	        "date_range": "2005-02-04 to 2026-03-06",
   250	        "non_nfp_trading_days": 5087,
   251	        "dates_in_common": 207,
   252	        "proxy_only_dates": [
   253	          "2005-07-01",
   254	          "2006-03-03",
   255	          "2006-05-05",
   430	        "to": "高低體制差 2.04 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
   431	        "hits": 1
   432	      },
   433	      {
   434	        "from": "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
   435	        "to": "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
   436	        "hits": 1
   437	      },
   438	      {
   439	        "from": "254 場歷史樣本加上 7/2 這場實測",
   440	        "to": "253 場歷史樣本加上 7/2 這場實測",
   441	        "hits": 1
   442	      },
   443	      {
   444	        "from": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
   445	        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布。改用官方日曆重跑後，原本 254 場樣本中有 46 場換成了不同的日子。本文正文數字已全部同步更正；**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。方向性結論不變（決定波動的是進場 VIX 體制，不是 NFP 本身），但有一項判讀翻轉：NFP 對「非 NFP 週五」基準的差距原本報為統計顯著（1.17 倍），改用官方日期後為 1.15 倍且未達顯著（p=0.057）。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
   446	        "hits": 1
   447	      },
   448	      {
   449	        "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
   450	        "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 127 與 126 筆；",
   451	        "hits": 1
   452	      }
   453	    ],
   454	    "apply_result": null,
   455	    "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
   456	  }
   457	}
165:      "verdict": "CONCLUSION_FLIPPED",
195:      "verdict": "CONCLUSION_FLIPPED",
355:  "n_claims_flipped": 2,

collab: Wait
exec
/bin/zsh -lc "rg -n 'across all tests|NFP does NOT warrant|practical_implication' .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json
rg -n '\"p_value\": 0.008837|\"significant_5pct\": true' .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json | head -6
git -C .claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short experiments/k528" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
203:  "practical_implication": "NFP does NOT warrant reducing SPY exposure. Vol ratio ~1.09x is statistically insignificant across all tests. Consistent with K513. For 04/03 NFP: focus on VIX level and broader conditions, not the NFP event itself.",
44:      "p_value": 0.008837037232261593,
45:      "significant_5pct": true
?? experiments/k528/review_verdict.json

二審完成：42 個既有測試雖全綠，但 fixture 未涵蓋 FRED 同月多筆 release 的真實輸入；兩項 blocking defects 已由獨立重算交叉確認。
  ✓ 讀取 handoff、error log 與 K528 審查檔案
  ✓ 驗證官方日期 fail-closed、事件對齊與統計重算
  ✓ 逐條比對 18 條文章更正並審查新舊結果揭露
  ✓ 檢查 lookahead、seed、原子寫入並形成裁決
codex
1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。

2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。

3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。

4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。

5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。

6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。

7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。

8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。

9. **防錯核對：** `pre_vix` 正確取自 T−1（[k528_nfp_event_study.py:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:163)、[k528_nfp_event_study.py:182](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:182)），未見交易 lookahead。本實驗沒有 bootstrap、抽樣或 Monte Carlo，seed 不適用。

Blocking defects：官方 accessor 把 off-cycle entries 當 NFP；錯誤日期直接否定核心顯著性翻轉及 18 條文章更正；partial／ambiguous calendar 亦未真正 fail-closed。

VERDICT: FAIL
tokens used
140,901
1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。

2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。

3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。

4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。

5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。

6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。

7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。

8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。

9. **防錯核對：** `pre_vix` 正確取自 T−1（[k528_nfp_event_study.py:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:163)、[k528_nfp_event_study.py:182](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:182)），未見交易 lookahead。本實驗沒有 bootstrap、抽樣或 Monte Carlo，seed 不適用。

Blocking defects：官方 accessor 把 off-cycle entries 當 NFP；錯誤日期直接否定核心顯著性翻轉及 18 條文章更正；partial／ambiguous calendar 亦未真正 fail-closed。

VERDICT: FAIL
