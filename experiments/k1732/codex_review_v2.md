OpenAI Codex v0.144.1
--------
workdir: /Users/yhlai0911/volpred-research
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: high
reasoning summaries: none
session id: 019f783e-adaa-7c51-b0d9-231a4c767ff5
--------
user
第二輪審查（v2）。你上一輪（experiments/k1732/codex_review_v1.md）判 FAIL 並列 8 個 findings；作者宣稱已全數修正。請驗證每一項修正是否落實，並檢查修正是否引入新問題。

**檔案**（絕對路徑 /Users/yhlai0911/volpred-research/experiments/k1732/）：k1732.py、README.md、k1732_results.json、k1732_figures.py、codex_review_v1.md（你上輪報告）。

**修正清單（作者宣稱）**：
1. cross_state 改嚴格交叉定義 `gap.lt(0) & gap.shift(1).ge(0)`（warmup 首負 gap 不再算交叉；IS_k 72→71 次）
2. 新增 circular-shift randomization 檢定（offset≥13、B=5000、p=(r+1)/(B+1) 單尾）取代 empirical bootstrap P(draw≤0) 作為正式 p 值；IS_k p=0.0138，×3 Bonferroni=0.041；README 宣稱降級為「5% 水準下顯著」
3. 「唯一帶增量資訊」改為「三個單變量檢驗中唯一估計為正且 CI 排除 0」+ 明註未做訊號間差異檢定與聯合模型；內生性優勢改為「方向上相容、非本設計可識別」
4. README/圖表更正：n=1,494 週；onset 30 次（28 次落在評估期）、alt 26（24 評估）
5. 2026 案例改寫：7/10（t−1）回彈 +0.0023 如實揭露，並明寫「依論文 5.2 判準此次 IS_k 交叉不構成有效提早預警」；圖 1 註解同步改
6. 移除 df.iloc[:-1]
7. 新增 estimator_sensitivity_ISk（population bias=True 重算：71 vs 71 次交叉、6 日期不同、5 警戒週不同）
8. β_s 調變改寫：corr 0.9715 + 樣本相對調變範圍 −36.9%~+23.9%

**輸出格式**：逐項標 FIXED / NOT FIXED / NEW ISSUE（附檔案:行號），最後一行單獨輸出 `VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`。

codex
我會先讀 handoff 與上一輪審查，再逐一對照程式、結果 JSON、README 和繪圖碼；這輪只做 read-only 審查，不修改檔案。
exec
/bin/zsh -lc "cat storage/ops/handoff_latest.md && sed -n '1,260p' experiments/k1732/codex_review_v1.md" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
# Handoff — 2026-07-19 09:50:02 台灣時間

**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）

> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。

## 1. 任務池快照（`storage/next_tasks.json`）

- **總數**：2905
  - pending: 87
  - pending_main_thread: 6
  - succeeded: 2598
  - failed: 52
  - blocked: 13
  - blocked_on_user: 2
  - Codex-eligible pending: 82
  - Codex-skip pending: 11

**type 分佈（top 6）**：
  - daily_article: 698
  - experiment: 650
  - platform_ops: 419
  - paper_review: 415
  - telegram_reply: 207
  - email_reply: 187

## 2. 已 claim / in_progress 任務

- (無 — 任務池閒置)

## 3. Email 回信任務（**優先處理**）

- (無未處理回信)

_Gmail 最後 poll：2026-07-19T01:45:10.574751+00:00_

## 4. Pending 任務 top 8（依 priority asc）

- **Codex-eligible pending**：82；**Codex-skip pending**：11

**Codex-eligible pending top 8**：
- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
- `assign_ae004ae2` P1 [experiment] k528 NFP 事件日污染修復：254 筆中 53 筆（20.9%）不是 NFP 日，線上文章 mile_35eef830 核心數字全建立其上
- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort
- `alert_content_quality_20260719` P2 [governance] [alert] 內容品質巡檢：發文間隔過久
- `alert_release_pool_gap_20260719` P2 [platform_ops] [alert] Release pool starved > 8.0h (cron healthy)
- `assign_2398cbfe` P2 [platform_ops] [P35-retry] Codex K1258 review (BLOCKED: gpt-5.5 infrastructure issue)
- `assign_23b2a961` P2 [experiment] 全 repo first-Friday proxy sweep：6 支腳本仍在用，k904 在 paper/ 底下可能影響論文

**All pending top 8**：
- `K1169` P1 [paper_body] K1169: Paper 2 §5 narrative rewrite (main thread, K1166 correction)
- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
- `assign_ae004ae2` P1 [experiment] k528 NFP 事件日污染修復：254 筆中 53 筆（20.9%）不是 NFP 日，線上文章 mile_35eef830 核心數字全建立其上
- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort
- `member_qa_3e258ba2_research_write` P1 [member_qa] [member_qa] yaoxk1431 30年7%穩定成長提問 —— research + write + publish 後半段
- `K1414_paper3_hln_retrofit` P2 [experiment] K1414: Paper 3 HLN small-sample DM correction retrofit (TW0050-N225 唯一 Harvey sig)
- `Paper3_expansion_synthesis_decision_meta` P2 [paper_decision] [paper_decision] Paper 3 A 三 E 完成後 → meta synthesis decision

## 5. 進行中 agent / worktree

- **slot 占用**：16 / 4
- worktrees:
  - `dispatch-slot-1-1533dcbc-cqamend`
  - `dispatch-slot-2-8dda242d-k1708`
  - `dispatch-slot-1-3217f0b2-pushgate`
  - `dispatch-slot-1-f53bca44-k1692`
  - `dispatch-slot-1-79726798-credit-firm`
  - `dispatch-slot-2-5ddfeb00-k1583`
  - `dispatch-slot-1-f53bca44-k1694`
  - `codex-desktop-k1707`
  - `dispatch-slot-1-3217f0b2-k1685`
  - `dispatch-slot-1-bd00f90a-k1731`
  - `dispatch-slot-1-b55db3be-2`
  - `dispatch-slot-1-558d7893-k1730`
  - `dispatch-slot-1-957aa2f2-k1630`
  - `dispatch-slot-1-30aeb902-taifexrv`
  - `dispatch-slot-1-957aa2f2-k1649`
  - `dispatch-slot-1-a56566ff-k1719`

## 6. 最近 24h 完成（top 5）

- `canonical_writers_publisher_feed_unguarded_20260719` P2 [platform_ops] [platform_ops] canonical-writers gate 紅：article_correction 未註冊 owner（已修）
- `alert_internal_phase_z_baseline_missing_537a3ff330_clean_watermark` P1 [platform_ops] [internal alert watermark] phase_z_baseline_missing
- `email-12141-5a75b7` P3 [email_reply] [email_reply] Re: [VolPred Alert][WARN] Dreaming review 2026-07-18 — 3 new / 0 escalations
- `daily_digest_20260719` P1 [daily_digest] [daily_digest] 寫一篇每日精選導讀專題策展並發佈
- `alert_internal_git_push_backup_hold_3f4834ce7a_clean_watermark` P1 [platform_ops] [internal alert watermark] git_push_backup_hold

## 7. Dashboard 訊號

- overall_status=warn (breaches=2, critical=0, generated=2026-07-19T01:30:16Z)
- WARN: section=production_throughput :: 5 articles published last 24h (target 6/day)
- WARN: section=verification_fb_pipeline :: 1 FB posts pending sync

## 8. 最近 work_log（5 筆，新→舊）

- `2026-07-19T09:39` [email_reply] email-12141-5a75b7
- `2026-07-19T09:35` [daily_digest] daily_digest_20260719
- `2026-07-19T08:12` [experiment] agent-brief_k1731_armB_rev6-526c33
- `2026-07-19T07:17` [platform_ops] trending_repost_2026_07_19_地緣避險
- `2026-07-19T07:16` [experiment] assign_67f56b79

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

**接續提示詞（2026-06-30）**：讀本段。系統健康（breach_count=0、daily-checkup ok）。從自主 ops loop 繼續：PHASE 0 清 email backlog → 推進 queued P2（VT-trend v7 派 Codex、dreaming persistent-alert detector，**兩者都需相對乾淨 context**）→ 沒 critical 就主動掃 5 missions。**context 紀律**：此 session 已長，heavy/delicate 工作（論文 body、detector build）優先在 compact 後或新 session 做，勿堆進 bloated context（boss 明確要求 token 成本紀律）。turn 尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`，工具嚴格 `antml:invoke`。

### 🟢 互動 session 脈絡（2026-06-24 ~16:30 台灣時間）

老闆整天連續高強度抓問題 + 逼「從底層邏輯/流程解決，不表面修補」。本 session 完成大量根治 + 診斷出 5 個待實作工程（含一個 meta-fix）。

**A. 已完整根治（改完+測試+部署+驗證，push 0/0）**：
1. **git 分岔 + 10 天備份缺口**（root cause = 雙 Claude dual-source）：本機與雲端 Claude routine 從 6/4 在同 `origin/main` 各自 commit、分岔 + 曾被 force 改寫。處理：(a) `git merge origin/main` 保留兩邊 + push 同步 **0/0**；(b) 用 `/schedule`+RemoteTrigger 停掉 4 個 cloud routines（兩個 push-main 的 `trig_01HzWX2ZUmsGHnzwciGpHeNz`=platform-ops-patrol、`trig_015iaE6yv3V9V1opjUAA5R2V`=token-usage-daily-report → enabled=false）；(c) 建本機自動 push：`scripts/cron_git_push_backup.sh`(canonical) + `~/.volpred/bin/cron_git_push_backup.sh`(runtime) + crontab `17 */2` + config 登記。**memory `project_cloud_agent_git_divergence`**。
2. **CI silent fallback 13 處**（背景 codex 引入，push 後 CI red）：kid_reserve.py(6)+topic_claim.py(1)+content.py(1)+alerts.py(5)，warn/silent-ok 修，**audit new=0**、tests 22 passed。
3. **health check 補強**（停雲端後補回監控）：`src/volpred/ops/health.py` 加 check_strategy_metrics_freshness/check_paper_trading_gaps/check_disk_usage，接 `alerts.py` build_alert_condition_report 鏈。**disk 改雙條件 `>85% AND free<50GB`**（避 926G 大碟誤報，老闆建議）。

**B. 診斷完成、root cause 已查實、待實作（老闆逼出來的真問題；勿表面修）**：
1. **🔝 內容品質巡檢（META-FIX，最高優先）** `docs/refactor_plan_content_quality_patrol.md` + memory `feedback_content_quality_patrol_gap`：老闆質疑「沒有固定任務檢驗發文/流程/排版有沒有問題嗎」→ 點破 meta-root-cause：系統只有基礎設施巡檢，缺內容品質層。今天 4 問題全靠老闆人工發現。新固定任務巡檢：發文節奏 / 主題 arc 多樣性（早抓 deadlock 源頭）/ digest 每日唯一 / 排版（標題前綴重複）/ 前端 render 健康(fetch 查 React error)/ 內容完整(真圖表+來源)。**判準：只有用戶會發現的問題 = 缺巡檢。**
2. **release-layer deadlock（發文脫班）** `docs/refactor_plan_release_layer_deadlock.md`：root cause = **39 draft 全被 `release_dedup_skipped` flag 排除**（觸發 if 在 `content.py:861` arc_dups/dup/flood；flag 賦值實際在 `content.py:869-870`；`_release_dedup_flag_active` `content.py:603`；`is_due` `content.py:641` draft 看 effective_include_drafts）。**⚠️ 2026-06-24 自我更正（workflow 驗證抓到）**：flag **不是「鎖+等 review」**——`content.py:244-253` 明寫 6/23 boss throughput incident 後已把它從 21天window 改成 **2天 anti-thrash COOLDOWN**（純優化，correctness 由 LIVE dedup gate 每次重查保證）。老闆「鎖不合理」直覺對舊的 21天window 正確（已修）。**真 root cause = 生產端持續產 arc 重複 → 每次 release run 重判重複 → 重標 flag → 2天 cooldown 永遠 active → pool freeze（code 註解自記 46/46 flagged）**。修法核心 = **生產端 arc-dedup pre-check（不產重複，research milestone path 缺）**，非「廢除鎖」（鎖已是輕量 cooldown）；輔以 remediation 改派 fresh-arc。**force release 是錯解**（`--force` 不繞 dedup + 成功會 reset last_released cadence timer）。
3. **digest 同日兩篇** ⚠️ **2026-06-24 自我更正**：`scripts/enqueue_daily_digest.py` **已有冪等**（`_digest_published_today` :72 + `_digest_task_exists_today` :99 + docstring :5-6，6/23 寫的）——**不是缺冪等**。6/24 兩篇 `mile_1597b341`(02:34)+`mile_f3e389cf`(02:16) 是**繞過**既有冪等：race（兩次 enqueue 都在對方標記 today-published 前觸發）或雙源/手動 dispatch。待：查為何繞過（race/雙源）+ 即時 retract `mile_f3e389cf`（`volpred ops unpublish`）。**勿重造已存在的冪等 code**。
4. **「每日精選導讀」標題重複** = 前端 digest title 帶「每日精選導讀｜」前綴 vs 區塊 header 同名重複。`frontend-v2-fix/src/app/page.tsx` + `digest/[id]/page.tsx`。
5. **前端 React #418 hydration mismatch**（老闆貼 console：HTML mismatch + 無限 postMessage re-render）。定位 `frontend-v2-fix/src/app/page.tsx` + components；高危 pattern(Date/random/toLocale in render)：SiteFooter/MyQuestionsConsole/AdminAnalyticsConsole 等。**前端是獨立巢狀 git repo → cd frontend-v2-fix 才能 commit；deploy 走 deploy-zeabur-safe.sh**。

**C. 本 session 老闆硬性 feedback（已記 memory）**：
- 從底層邏輯/流程解決不表面修補（force release 被打回）；鎖機制「鎖+等review」對自主系統不合理 → 廢除非補丁。
- 自主運營缺內容品質巡檢層（`feedback_content_quality_patrol_gap`）。
- 關 session/終端/重開機要能接續（`feedback_tasks_survive_session_close`）：backbone OS cron/LaunchAgent session-independent；**重開機後 FileVault 解鎖=登入，輸入一次密碼即全恢復**（FileVault 擋 auto-login 但不影響）；⚠️ **跑 install_host_crontab.sh 前必 `--diff`**（2026-06-24 更正：實測 --diff 不是刪 9 條，而是**新增 6 條 + 把 fred-backfill-guard 換成 supabase-sync-drain**——因 fred-backfill-guard 在 config `cron_jobs[2]` 非 system_crontab.items，腳本掃不到。會改動運作中 cron，先 --diff/--dry-run 檢視再決定）。

**D. 擱置/未做**：
- FB backlog 唯一常青 `mile_312204b2`（砍人燒錢科技股波動率）待貼 Ivan 個人 FB（老闆已開 Chrome）。**App Review 查證結果：發文 app(VolPredPoster/VolPredPage/社團發文)全 Development mode 未上線 → headless 發 FB 粉專不可行 → 走 Chrome 是對的**。FB 個人帳號 Chrome 選法（⚠️ 2026-06-24 更正，照 memory `reference_fb_chrome_browser_autoselect`）：登入的是 **「MAX STUDIO」**（有 X；「MAC STUDIO」是登出錯機別用）。**deviceId 會輪替、不可 hardcode**——每次 `list_connected_browsers` + `tabs_context_mcp`，找 tabs 含 `facebook.com/yihao.lai` 的那台（本 session 剛好是 bc09353b/Browser 3，但下次會變，勿照抄）。
- 脫班即時止血未做（正解=派 fresh-arc daily_article，非 force）。digest 去重 retract 未做。

**接續提示詞（2026-06-24）**：讀 `storage/ops/handoff_latest.md` KEEP 最上方此 2026-06-24 段。**ultracode 已開（xhigh + workflow）**。從自主 ops loop 繼續，優先序：**(1) 內容品質巡檢 meta-fix（最高——建立後自動 surface 全部，先做 digest唯一/主題多樣/前端render 三項直接覆蓋今天問題）→ (2) 前端 #418+標題重複（cd frontend-v2-fix，獨立 repo，build+deploy-zeabur-safe）→ (3) release deadlock（核心=生產端 arc-dedup pre-check 不產重複；鎖已是 6/23 改的 2天cooldown，非廢除對象；remediation 改 fresh-arc）→ (4) digest 查繞過既有冪等的 race + retract mile_f3e389cf（勿重造冪等）**。每項乾淨 context + Codex/test 驗證，**勿在單一 session 草率全堆**（老闆認可分階段保品質）。auto-push 用 `~/.volpred/bin/cron_git_push_backup.sh`。**install_host_crontab.sh 跑前必 --diff**（會新增 6 + 換 fred-backfill-guard）。turn 結尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`，工具呼叫嚴格 `antml:invoke` 格式。

---

### 互動 session 脈絡（2026-06-19 ~17:52 台灣時間）

**本 session 全部已完成 + 驗證（老闆即時連續抓問題，全從底層修，無 critical 殘留）**：
1. **鬼打牆 K1054 重發**：`mile_bb520db8`(06-19) 是 `mile_c481c8cf`(06-07) 逐字複製、同 K1054。retract+sync 前端下架（已驗證移除）+ arc_dedup `descriptive→return[]`（我前 session 自傷）改 `_descriptive_dup()` 嚴格判斷 + publish_milestone same-K-id gate + content.py 傳 experiment_refs（commit `be88c2d1`）+ regression test（SpaceX 不擋/ghost 擋，主線程驗證）+ error_log `e1de1fe6`。
2. **前端「詳情」洩漏**（老闆 2 次截圖）：arc_signature/content_type/experiment_refs 顯示給讀者。`ReportDetail.tsx` 三段 fix（frontend repo 43ff348/11fcfd5/110fd86：黑名單+空值+experiment_refs）+ **foreground** deploy volpred-v3 + 線上驗證詳情/experiment_refs/arc_signature=0（保護 1643 篇）。
3. **老闆 3 根因** `c35509c8`：release pool dedup flag 加 TTL=21天（46 篇 legacy 回流，已見 released_count=1）+ member_qa dispatch regex **strike2**（2026-06-10 yfinance 同 root，加 explicit agentable override，已驗證進 agentable）+ M2 供給派 journal-discovery 補 7 新方向 `8868f3fb`。
4. mirror SSL EOF(22MB feed PUT 超 Next.js body limit)+Codex .git sandbox(-s workspace-write 覆蓋 config) 修(dd5f1834) + CLI 診斷(Codex/agy 都正常非沒登入) + email backlog 5→0+老闆回覆。
5. **stale member_qa_9ab8d3a7**（yaoxk1431 選股/點位提問）評 18/100 **declined**，守住投資建議三紅線**未發投資建議文**，task=`pending_main_thread`（不再 stale）。

**follow-up（已記 error_log，未做）**：
- **禮貌回覆 yaoxk1431**：寫「VolPred 定位說明（只做波動率/風險，不做選股/點位/個人化建議）+ 邀請提波動率問題」簡短回應，**不可滑入投資建議**。decision: **不 archive**（真實付費會員）。
- member_qa 進 agentable 但 hourly headless 不自動執行 reader-facing workflow → 確認 dispatch prompt 涵蓋 or 靠互動/subagent 派（觀察下幾班 hourly 是否派出 9ab8d3a7）。
- dispatch ownership 改 schema `dispatch_lane`（strike3 預備）；theme_flood 改節流非封死；research_backlog 加 fallback 自動觸發 journal-discovery；legacy publish_experiment/publish_comparison 繞 dedup（_append_to_feed last-resort 防呆待評估）；M3 paper 2 筆待主線程 body rewrite。

**本 session 教訓**：多次把工具呼叫開頭標籤打成 `court`/`invoke`（應 `antml:invoke`）→ user-visible 破圖、惹惱用戶。**接續嚴格用正確 function_calls 格式**。修雙向 dedup（false-positive vs false-negative）必同時寫正反兩面 regression test。

**FB**：用戶本 session 明確說「FB 先停」；trending FB 2 篇文案備妥（/tmp/fb_index_inclusion.md + /tmp/fb_move_vix.md）但 harness facebook.com 互動權限擋——**勿主動推 FB**（下方一大串舊 FB awaiting 同理，用戶已表態 FB 暫停）。

**接續提示詞（2026-06-19）**：讀 `storage/ops/handoff_latest.md`（先看 KEEP block 最上方此 2026-06-19 段）後從自主 ops loop 繼續（dashboard 巡檢→triage→派工→收背景 agent）。老闆抱怨的鬼打牆/前端洩漏/3 根因已全修驗證生效，無 critical。優先 follow-up（視 context 鬆緊）：(1) 寫 yaoxk1431 禮貌定位回覆（純定位，不投資建議）；(2) 觀察 member_qa_9ab8d3a7 是否被 hourly 派出，連續不派則補 dispatch prompt。turn 結尾**正確格式**排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`。**工具呼叫嚴格用 `antml:invoke`，FB 暫停勿推**。

---

### 互動 session 脈絡（2026-05-29 ~13:50 台灣時間，主 agent 手動維護）

**本 session 已完成**：
1. 全面運營 audit（真實架構 = LaunchAgent + piggy-back scheduler + codex_loop daemon + dispatch_supervisor 重構，**非 crontab**；docs/architecture.md 停在 4/19 已 stale）
2. 用戶完整願景 → memory `project_platform_vision_full`（全自動不間斷自我運營）
3. codex-cli 更新 0.132→0.135 + 設週度自動更新 job（runtime_schedules `codex_update`，piggy-back 執行）
4. 大改安全網：tag `stable-pre-refactor-20260529` + branch `refactor/autonomy-overhaul` + worktree `../volpred-refactor`（回滾指令見 `docs/refactor_safety_net.md`）
5. 修 `generate_handoff.py` KEEP 保留 bug（原 main() 直接覆寫從不讀回，手寫 handoff 每 :50 被清）
6. log rotation（codex_loop.log 46MB→196K）+ crontab 違規教訓記 error_log
7. **重新擘劃**：3 平行 explorer 盤點（前端/後端/指引文件）→ `docs/master_plan.md`（已 commit，7 phase 路線圖）
8. 清理：`舊前端/` 515MB 移 ~/.Trash（未 git 追蹤、hygiene.py 標 ROOT_CLUTTER，可 Finder 還原）
9. 歸檔 11 個一次性 audit docs → `docs/archived/incident-history/`（docs/ 根 50→39，已驗證無 active 引用）
10. `architecture.md` 加當前真實架構修正區塊（原 v12 描述 stale）
11. **驗證**：double-fire（P2）已被並行流程處理 — `run_due_jobs.py` 確 honor `piggy_back_skip`（非假旗標）；config 已加 4 job 的 skip。**勿重複做**
12. **糾正 explorer 誤判**：AGENTS.md 是 codex_loop 活躍指令檔（勿歸檔，只能去重）；memory 非「僅 1 檔」（數十檔健在）

13. **用戶「你決定」→ 3 項已決並執行**：(a) 殺重複 codex_loop 82862、留 42125（兩者都 idle 無風險）(b) FB 2 篇標 wont_fix（3天 stale、無法自主 OAuth、改 headless P6）(c) main/origin reconcile：merge 39 ops-report + push，**277 commit 全備份上雲，0/0 同步**

14. **P2 文件優化（main，逐 commit 可審；worktree 因落後 main 改用 main+snapshot tag 兜底）**：AGENTS.md 7 處 `.agents/`→`.claude/` 壞路徑修正（Codex 活躍指令檔）+ 歸檔 DEPRECATED multi-agent-terminal-workflow-codex。跳過 context-hygiene path 改（explorer over-reach）。

15. **P1/P2 再推進（main，逐 commit）**：刪 16 個驗證無引用死腳本（_*/exp_*/rough_vol_pilot/test_* model 調試；scripts 179→163，git 可復原）+ system_handbook.md 加 STALE header。跳過 autonomous-loop 抽離（違反 memory `feedback_claudemd_keep_inline`：CLAUDE.md 不拆）。

16. **P2 文件優化 = 安全有效項全完成**。逐檔驗證後判定 3 項為 explorer over-reach 正確不做：(a) autonomous-loop 抽離→違反 keep-inline (b) publishing.md 砍60%→削弱治理 enforcement（rule 冗餘是刻意設計）(c) scheduler 4-way dedup→alert/publishing 只是 contextual ref 非真重複。詳見 master_plan §7 + 方法論教訓（DRY 不可套治理檔）。

17. **P1 死腳本清理完成**：再刪 35 個死的 publish_k*/publish_<topic>（發現 publish_draft.py 統一入口早已存在；35 個是 spent 一次性、無引用、文章已 published）。**本 session 共清 51 死腳本，scripts/ 179→128，publisher import 驗證 OK**。
18. **又擋下 over-reach**：generate_diverse_tasks / generate_research_backlog explorer 說「冗餘可合併」→ 驗證皆 active（dispatcher + 每日 08:00 cron 引用），**不可刪**。本 session 共擋 6 個 explorer over-reach。

**P1 清理 + P2 文件 = 完成**（安全項全做、over-reach 全擋、active 全保）。
**剩餘 = 純多 session 工程，非 chat 可完成**：P0 supervisor D5-D8、P3 前端商業化、P4 資料樞紐、P5 provenance 補修、P6 內容引擎。autonomous loop 持續推進。
**已決議**：codex_loop 去重(留42125)、FB wont_fix、main/origin 已 reconcile 上雲、double-fire 已由 piggy_back_skip 處理。

**優化路線圖 6 主題**：1.自動化可靠性地基（推完 dispatch_supervisor 4/8→8/8，最高槓桿）2.議題 selectivity/變現 gate 3.論文 pipeline 推進 4.策略自動上架+多元標的 5.曝光/社群/變現 6.活文件更新。

19. **anti-ai-style 破折號 normalizer 完成（2026-05-29 ~17:39，commit 2130d746 已推 origin）**：用戶明確指令「繼續做 normalizer」。新增 `src/volpred/publisher/emdash_normalizer.py` + 掛進 `_append_to_feed`（緊接 markdown_table_sanitizer，同兩層防禦 pattern）。保守 scope：只把 **CJK 兩側包夾**的補充式破折號 `——`/`—` 改逗號（skill 地雷 9 fix (b)「改逗號併入主句」，語意無損）；數字範圍 `2020—2024`、拉丁複合 `risk—reward`、行首署名 `——作者`、code fence、表格 cell 全跳過。10 unit tests 覆蓋各 edge case 全綠。補上 publisher 端硬 gate（先前全靠 agent 自律，validate_anti_ai_style 顯示近期僅 ~10% 乾淨）。

**接續提示詞補充**：compact/clear 後接手，先讀 `docs/refactor_safety_net.md` + memory `project_platform_vision_full` + `project_refactor_safety_net`，再依路線圖主題 1 推進 dispatch_supervisor 重構（在 `../volpred-refactor` worktree 做，主目錄 main 保持 ops 不間斷）。

---
### 🔴 進行中 user-assigned（2026-05-30 ~12:48 起，最高優先 — compact 後優先續做）

**寫 2 篇 trending articles**（用戶連發 2 主題，daily cap 2）：
1. **定期定額(DCA) vs 單筆投入(Lump Sum)** — 用戶 Ivan Lai FB，核心洞見「總報酬率 LumpSum 勝、IRR 資金效率本質相等」（工讀生/時薪比喻）
2. **逢低買進(dip-buying) vs 固定配置** — yp-finance（trending 不可引用來源），主題=time in market vs timing

**共用實驗 K1406**（worktree `agent-ae6bda7e937b51054`，subagent 獨家 owner 收尾中）：conditional block bootstrap，SPY 2005-2026 + 0050 2009-2026。
- **主線程已實跑驗證**：命題 A Lump Sum 終值勝率 **~0.74**（合 FB 69.7%）✓；命題 B dip-buying(10%) 勝率 **~0.42** + cash drag 0.20-0.62 ✓
- **✅ 最終數字已驗證（results.json 齊全，2026-05-30 ~13:20）**：
  - 命題 A confirmed：Lump FV 勝率 **74.1%**；**IRR 年化中位差 lump−dca=+0.0003（≈0）、IRR 勝率~0.50 擲銅板 → 資金效率本質相等**。per-asset：SPY IRR diff +0.0003/+0.0002、0050 −0.008/+0.005（皆微小）
  - 命題 B confirmed：dip-buying(10%) 勝率 **42.3%**、cash drag(閒置現金時間) **40.7%**、等不到回檔 **13.4%**
  - 4 圖：fig_a(DCA/Lump 勝率)/fig_b(分布+IRR)/fig_c(dip 勝率+drag)/fig_d(dip 分布+等不到)
  - **待**：subagent commit K1406 到 worktree branch（產出已在但未 commit）+ Codex verdict

**接續步驟**：(1) `bash scripts/merge_worktree.sh agent-ae6bda7e937b51054` 合併 (2) 驗證 results.json + Codex verdict (3) 寫 2 篇 anti-ai-style（讀 anti-ai-style references；破折號 ≤1/1000、禁假哲理/翻譯腔）+ 嵌真圖 → feed-publisher（trending_repost published）(4) FB 雙發走 Claude in Chrome + Ivan Lai 口吻 (5) 研究誠實：數字有出入如實報告

### 🔔 明早 follow-up（2026-05-31 09:00 後，loop 補做）
FB 文 4（K1408 進場時機文）已排程明早 09:00 自動發到 Ivan Lai。**排程貼文發出後要補第一則留言貼連結**：到 facebook.com/yihao.lai 找已發出的該篇 → 留言「完整的數字跟圖表在這 👉 https://volpred.zeabur.app/v3/reports/mile_15dcf8e6」→ 寫回 feed.json mile_15dcf8e6 fb_post_status=success + fb_post_url。Chrome=MACBOOK(398dcdba)，單步操作（batch 會被權限擋）。

### 🔔 明天 2 個 FB 留言 follow-up（貼文自動發出後補連結）
1. ~09:00 後 — K1408 進場時機文（mile_15dcf8e6）：留言「完整的數字跟圖表在這 👉 https://volpred.zeabur.app/v3/reports/mile_15dcf8e6」
2. ~20:00 後 — K1409 月月配文（mile_c523a922）：留言「完整的數字跟圖表在這 👉 https://volpred.zeabur.app/v3/reports/mile_c523a922」
做法：facebook.com/yihao.lai 找已發出該篇 → 留言貼連結 → 寫回 feed.json fb_post_status=success。Chrome=MACBOOK(398dcdba)，單步操作。

### 🔔 FB awaiting interactive — mile_072c3972（2026-06-09 05:35 hourly-05 標）

- 文章：財報前波動率反而縮水？NVDA 九次財報的 EAV 解剖（trending_repost，今早 05:23 published, sanitizer-fix 05:31 update）
- 狀態：fb_post_status=awaiting_interactive_session
- 原因：個人 FB 帳號（Ivan Lai）只能走 Claude in Chrome
- 互動 session 接手做法：開 Chrome MACBOOK(398dcdba) → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_072c3972`）→ `mark_fb_post_status.py --mile-id mile_072c3972 --status success` + URL/timestamp 寫 details
- 重點數字（FB 改寫可用）：NVDA 財報前 5 日 RV 比基準低 19.7%（單測 0.034、Bonferroni 後 NS）；MSFT 財報後 5 日 RV 飆 +102.6%（Bonferroni 後 borderline survive 0.0049）；AAPL 全 NS。九次財報 / 三家公司 / 2024–2026

### 🔔 FB awaiting interactive — mile_123a3855（2026-06-05 13:07 hourly fire 標）
- 文章：S&P 500 集中度突破 32%，指數波動率卻跌到 14%：這個缺口是怎麼來的（trending_repost，今早 07:19 published）
- 狀態：fb_post_status=awaiting_interactive_session（hourly cron 改標，dashboard WARN 解除）
- 原因：個人 FB 帳號（Ivan Lai）只能走 Claude in Chrome，hourly cron 無自主能力
- 互動 session 接手做法：開 Chrome MACBOOK(398dcdba) → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_123a3855`）→ `mark_fb_post_status.py --mile-id mile_123a3855 --status success` + URL/timestamp 寫 details

### 🔔 FB awaiting interactive — mile_0fa9c7f5（2026-06-09 08:17 hourly-08 標）
- 文章：VIX 一根長腳之後：CPI 前夕的短端結構告訴我們什麼（event_article CPI_US 2026-06-11 T-2，08:16 published）
- 狀態：fb_post_status=awaiting_interactive_session
- 原因：個人 FB 帳號（Ivan Lai）只能走 Claude in Chrome
- 互動 session 接手做法：開 Chrome MACBOOK(398dcdba) → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_0fa9c7f5`）→ `mark_fb_post_status.py --mile-id mile_0fa9c7f5 --status success`
- FB 草稿已寫好：`storage/event_articles/us_cpi_2026_06_11_t2/fb_draft.md`（200 字、Ivan Lai 口吻、6/5 VIX 長腳 + VIX9D 倒掛 hook）
- 重點數字：近 4 次 CPI 反應變淡（5/13 -0.7% vs 2/12 +18%）+ 當前 VIX9D/VIX 1.041 倒掛 + T+5 一律負（平均 -8%）

### 🔔 FB awaiting interactive — mile_0e1eb5aa（2026-06-10 10:xx hourly-10 標）
- 文章：FOMC 6/17 T-7：SOFR 期貨說「不降息」，但點陣圖說什麼？（event_article FOMC_2026_06_17 T-7，10:xx published）
- 狀態：fb_post_status=awaiting_interactive_session
- 原因：個人 FB 帳號（Ivan Lai）只能走 Claude in Chrome
- 互動 session 接手做法：開 Chrome MACBOOK(398dcdba) → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_0e1eb5aa`）→ `mark_fb_post_status.py --mile-id mile_0e1eb5aa --status success`
- FB 草稿已寫好：`experiments/event_article_fomc_2026_06_17_t7/fb_draft.md`（Ivan Lai 口吻、SOFR 期貨 vs 點陣圖分歧 hook + VIX9D/VIX 比值 1.114）
- 重點數字：VIX 19.87 / VIX9D 22.14 / 比值 1.114（今年 4 場 FOMC T-7 最高）/ SOFR Jun 3.67%→Mar27 4.06% 上坡 / SPY 5日 RV 17.6%

### ✅ RESOLVED mile_a5e79b07（2026-07-07 09:50 標 expired_skip — 事件過3週補發無ROI；勿再發，下方 stale 條目留存作 audit）
### 🔔 FB awaiting interactive — mile_a5e79b07（2026-06-15 09:25 task_89accaab6ced 標）
- 文章：FOMC 6/17 倒數 48 小時：VIX9D/VIX 比值從 1.11 跌回 0.98，市場已收手（event_article FOMC_2026_06_17 T-2，published 2026-06-15）
- 狀態：fb_post_status=awaiting_interactive_session
- 原因：個人 FB 帳號（Ivan Lai）只能走 Claude in Chrome
- 互動 session 接手做法：開 Chrome → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_a5e79b07`）→ `mark_fb_post_status.py --mile-id mile_a5e79b07 --status success`
- FB 草稿已寫好：`experiments/event_article_fomc_2026_06_17_t2/fb_draft.md`（Ivan Lai 口吻、VIX9D/VIX 從 1.11→0.98 hook + 19 場 FOMC 平均報酬 -0.22% + 降息會議反直覺 -0.44%）
- 重點數字：VIX 17.68 / VIX9D 17.26 / 比值 0.976（T-7 是 1.114，壓力已消失）/ SOFR Jun 3.67%→Mar27 4.06% / SPY 19 場 FOMC 均值 -0.22%

### 🔔 FB awaiting interactive — mile_0daa4bb2（2026-06-18 07:15 hourly-07 標）
- 文章：NVDA 選擇權把話說得很清楚：先怕，再買（trending_repost，2026-06-18 07:14 published）
- 狀態：fb_post_status=awaiting_interactive_session
- 互動 session 接手做法：開 Chrome MACBOOK(398dcdba) → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_0daa4bb2`）→ `mark_fb_post_status.py --mile-id mile_0daa4bb2 --status success`
- FB 草稿已寫好：`storage/drafts/fb_mile_0daa4bb2.md`
- 重點數字：NVDA 25Δ skew put-call +0.8%（近乎持平）/ 短 dated ±10% OTM skew +3.5%（put 較貴）/ ATM IV 32.4% vs RV30 45.4% IV-RV gap **-13pp**（市場低估近期波動）/ skew flip 約 64 天後由 put skew 翻 call skew

### 🔔 FB awaiting interactive — mile_d341175c（2026-06-18 11:19 hourly-11 標）
- 文章：Treasury 拍賣冷清不等於 MOVE 噴出（daily_article K1506 null finding general-audience，11:19 published draft）
- 狀態：fb_post_status=awaiting_interactive_session
- 原因：個人 FB 帳號（Ivan Lai）只能走 Claude in Chrome
- 互動 session 接手做法：開 Chrome MACBOOK(398dcdba) → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_d341175c`）→ `mark_fb_post_status.py --mile-id mile_d341175c --status success`
- FB 草稿：`storage/drafts/fb_mile_d341175c.md`
- 重點數字：278 場 Treasury auctions（2015-2026 / 11 年）/ Welch t=-0.47, p=0.642, Cohen's d=-0.10 / 5d MOVE cum vol weak 8.79% vs benign 9.20% / Bootstrap 95% CI [-0.020, +0.008] 橫跨 0 / Secondary z<-1.0 N=45 同方向 FAIL

### 🔔 FB awaiting interactive — mile_19fa8ca1（2026-06-17 hourly-12 標）
- 文章：空倉多到9年最高，上次這樣的時候 VIX 一週翻了兩倍（trending_repost，2026-06-17 12:20 published）
- 狀態：fb_post_status=awaiting_interactive_session
- 原因：個人 FB 帳號（Ivan Lai）只能走 Claude in Chrome
- 互動 session 接手做法：開 Chrome MACBOOK(398dcdba) → facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（200-400 字改寫、主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_19fa8ca1`）→ `mark_fb_post_status.py --mile-id mile_19fa8ca1 --status success`
- FB 草稿：`storage/drafts/fb_mile_19fa8ca1.md`（Ivan Lai 口吻，已寫好，carry trade 倉位擁擠 + VIX 定價缺口 hook）
- 重點數字：CFTC 日圓淨空倉 -145,800 張（9年高）/ 2024/8/5 VIX 38.6（月均14→38）/ USDJPY 160.2 vs 2024年152.7 / VIX 18（現在）
### 🔔 FB awaiting interactive — mile_08fefa59（2026-07-07 06:20 hourly-06 標）
- 文章：AI 基建變現疑慮升溫，科技股與防禦板塊的波動率黃金交叉（trending_repost，2026-07-07 06:20 published）
- 狀態：fb_post_status=awaiting_interactive_session（hourly headless 無 Chrome）
- 互動 session 做法：**發前先 pre-check 老闆是否已手動發過同主題** → 開 Chrome 連 MAC STUDIO（`list_connected_browsers` 找登入 yihao.lai 那台）→ facebook.com/yihao.lai → 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP（主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_08fefa59`）→ `mark_fb_post_status.py --mile-id mile_08fefa59 --status success`
- FB 草稿已寫好：`storage/drafts/fb_trending_ai_capex_20260707.md`（Ivan Lai 口吻、~300字、已過 anti_ai_gate）
- 重點數字：QQQ 20日RV 35.28%（一個月前 15.55 翻倍）vs 防禦籃 16.02%／科技−防禦利差 19.27pp（近90日高點 20.54）／VIX 15.57 低檔／SKEW 145／近1月 QQQ −2.77% vs XLV +10.25%（黃金交叉）
- ⚠️ 註記：Codex 額度用盡（reset Jul 11），本篇懶人包改自寫 matplotlib renderer（`experiments/trending_ai_capex_defensive_20260707/render_lazypack.py`，數字直讀 results.json）；lazypack 生成的 codex primary path 至 7/11 前不可用，需 lazypack 的文章走自寫 renderer 或 NotebookLM fallback。

### ✅ RESOLVED mile_d12825bb（2026-07-07 14:14 hourly-14 發佈成功 — 老闆 Telegram msg229「你立刻發」觸發）
- **已發**：fb_realchrome_post CDP-attach 老闆 port 9222 Chrome → 566字主文+4圖（結果圖+3懶人包，先 upload_chart 上傳 supabase）+第一則留言連結；canonical fb_post_status→success；獨立截圖驗證相片區顯示 MOVE 圖為最新照片。Telegram 已回 msg263。
- **教訓**：headless hourly **可**用 fb_realchrome_post CDP-attach 發 FB（不必等互動 session），前提=老闆 dedicated Chrome(port 9222)開著且已登入。draft 缺圖時先 upload_chart lazypack→補 `## 圖片` 區塊（worker 只吃 URL、0圖 ABORT）。下方 stale 條目留存作 audit。
### 🔔 FB awaiting interactive — mile_d12825bb（2026-07-07 09:50 標，email-12690 老闆「立刻處理」觸發）
- 文章：同樣動一碼，債市只怕利率往上：MOVE 指數藏了一個方向感（trending_repost，2026-07-06 published）
- 狀態：fb_post_status=awaiting_interactive_session（headless 無 Chrome 發不出）
- 互動 session 做法：**發前 pre-check 老闆是否已手動發** → 開 Chrome 連 MAC STUDIO（`list_connected_browsers` 找登入 yihao.lai 那台）→ facebook.com/yihao.lai → 主貼文不放連結、第一則留言貼 `https://volpred.zeabur.app/v3/reports/mile_d12825bb` → `mark_fb_post_status.py --mile-id mile_d12825bb --status success`
- FB 草稿已寫好：`storage/drafts/fb_trending_move_asymmetry_20260706.md`（Ivan Lai 口吻、已過 anti_ai_gate）
- 重點數字：2010以來4065交易日／殖利率上行日 MOVE +0.51% vs 下行日 −0.28%（差0.79pp, t=5.52）／扣掉幅度後每bp反應 上0.40% vs 下0.27%＝1.47倍／近90日方向差距放大近6倍(4.53pp)／MOVE 65.4, 10Y 4.485%
- ⚠️ email-12690 已寄 close email（含2篇可直接貼上完稿+連結）給老闆；老闆二選一：等 Chrome session 我發 or 他自己秒貼
<!-- /KEEP -->
OpenAI Codex v0.144.1
--------
workdir: /Users/yhlai0911/volpred-research
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: high
reasoning summaries: none
session id: 019f7833-2877-7951-b1de-c1cf1c19a252
--------
user
你是嚴格的計量金融代碼審查者。審查實驗 K1732（絕對路徑 /Users/yhlai0911/volpred-research/experiments/k1732/）：

**背景**：Lai & Chang (accepted) 提出 Cornish-Fisher VaR 分解預警（β_s/β_k/IS_k 的 MA20/MA30 死亡交叉，26 週滾動動差、α=5%、週資料）。K1732 把訊號放到 TAIEX 1997-2026 做系統性回測。論文公式：z_CF = z + (1/6)(z²−1)s + (1/24)(z³−3z)(k−3) − (1/36)(2z³−5z)s²；β_s = −σ[(1/6)(z²−1) − (1/18)(2z³−5z)s]；β_k = −σ(1/24)(z³−3z)；IS_i = |dVaR_i|/Σ|dVaR_i|，dVaR_i = β_i·ΔX_i。

**必讀檔案**：k1732.py（主腳本）、README.md（宣稱面）、k1732_results.json（結果）、k1732_figures.py（圖表）。
**必讀規範**：/Users/yhlai0911/volpred-research/.claude/skills/autonomous-research/references/experiment-preamble.md

**審查重點**：
1. Lookahead：訊號是否確實只用 t−1 資訊評估 onset？shift(1) 的對齊有無 off-by-one？forward 視窗（onset in t+1..t+13）的 rolling-reverse 實作對嗎？
2. 死亡交叉狀態機（cross_state）與 weeks_since_last_death 的回溯邏輯正確性
3. episode onset 定義（與上一崩跌週間隔 >13 週）實作是否與 README 宣稱一致
4. 公式實作是否忠於論文（z=Φ⁻¹(0.05) 負值時各項符號）；pandas skew/kurt（bias-corrected、excess）與論文樣本動差的差異是否已誠實揭露
5. circular block bootstrap 實作正確性（block 重疊、邊界、p 值定義）
6. README 每一個數字與宣稱是否被 k1732_results.json 支持？有無 overclaim（特別是「唯一帶增量資訊」「Bonferroni 後仍顯著」「boundary condition 非 refutation」等語句）
7. mechanical equivalence 宣稱（β_k 交叉恆等於 σ 上升趨勢交叉）是否被代碼驗證支持

**輸出格式**：
- 逐點 findings（嚴重度 CRITICAL/MAJOR/MINOR + 檔案:行號 + 說明）
- 最後一行單獨輸出 verdict，格式：`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 需列 blocking defects）

codex
我會依指定規範做唯讀審查，先讀 handoff、experiment preamble 與四個實驗檔，再用小型獨立重算核對索引、公式、bootstrap 和 README 宣稱；不會修改任何檔案。
exec
/bin/zsh -lc "cat storage/ops/handoff_latest.md && sed -n '1,240p' .claude/skills/autonomous-research/references/experiment-preamble.md" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
# Handoff — 2026-07-19 09:50:02 台灣時間

**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）

> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。

## 1. 任務池快照（`storage/next_tasks.json`）

- **總數**：2905
  - pending: 87
  - pending_main_thread: 6
  - succeeded: 2598
  - failed: 52
  - blocked: 13
  - blocked_on_user: 2
  - Codex-eligible pending: 82
  - Codex-skip pending: 11

**type 分佈（top 6）**：
  - daily_article: 698
  - experiment: 650
  - platform_ops: 419
  - paper_review: 415
  - telegram_reply: 207
  - email_reply: 187

## 2. 已 claim / in_progress 任務

- (無 — 任務池閒置)

## 3. Email 回信任務（**優先處理**）

- (無未處理回信)

_Gmail 最後 poll：2026-07-19T01:45:10.574751+00:00_

## 4. Pending 任務 top 8（依 priority asc）

- **Codex-eligible pending**：82；**Codex-skip pending**：11

**Codex-eligible pending top 8**：
- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
- `assign_ae004ae2` P1 [experiment] k528 NFP 事件日污染修復：254 筆中 53 筆（20.9%）不是 NFP 日，線上文章 mile_35eef830 核心數字全建立其上
- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort
- `alert_content_quality_20260719` P2 [governance] [alert] 內容品質巡檢：發文間隔過久
- `alert_release_pool_gap_20260719` P2 [platform_ops] [alert] Release pool starved > 8.0h (cron healthy)
- `assign_2398cbfe` P2 [platform_ops] [P35-retry] Codex K1258 review (BLOCKED: gpt-5.5 infrastructure issue)
- `assign_23b2a961` P2 [experiment] 全 repo first-Friday proxy sweep：6 支腳本仍在用，k904 在 paper/ 底下可能影響論文

**All pending top 8**：
- `K1169` P1 [paper_body] K1169: Paper 2 §5 narrative rewrite (main thread, K1166 correction)
- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
- `assign_ae004ae2` P1 [experiment] k528 NFP 事件日污染修復：254 筆中 53 筆（20.9%）不是 NFP 日，線上文章 mile_35eef830 核心數字全建立其上
- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort
- `member_qa_3e258ba2_research_write` P1 [member_qa] [member_qa] yaoxk1431 30年7%穩定成長提問 —— research + write + publish 後半段
- `K1414_paper3_hln_retrofit` P2 [experiment] K1414: Paper 3 HLN small-sample DM correction retrofit (TW0050-N225 唯一 Harvey sig)
- `Paper3_expansion_synthesis_decision_meta` P2 [paper_decision] [paper_decision] Paper 3 A 三 E 完成後 → meta synthesis decision

## 5. 進行中 agent / worktree

- **slot 占用**：16 / 4
- worktrees:
  - `dispatch-slot-1-1533dcbc-cqamend`
  - `dispatch-slot-2-8dda242d-k1708`
  - `dispatch-slot-1-3217f0b2-pushgate`
  - `dispatch-slot-1-f53bca44-k1692`
  - `dispatch-slot-1-79726798-credit-firm`
  - `dispatch-slot-2-5ddfeb00-k1583`
  - `dispatch-slot-1-f53bca44-k1694`
  - `codex-desktop-k1707`
  - `dispatch-slot-1-3217f0b2-k1685`
  - `dispatch-slot-1-bd00f90a-k1731`
  - `dispatch-slot-1-b55db3be-2`
  - `dispatch-slot-1-558d7893-k1730`
  - `dispatch-slot-1-957aa2f2-k1630`
  - `dispatch-slot-1-30aeb902-taifexrv`
  - `dispatch-slot-1-957aa2f2-k1649`
  - `dispatch-slot-1-a56566ff-k1719`

## 6. 最近 24h 完成（top 5）

- `canonical_writers_publisher_feed_unguarded_20260719` P2 [platform_ops] [platform_ops] canonical-writers gate 紅：article_correction 未註冊 owner（已修）
- `alert_internal_phase_z_baseline_missing_537a3ff330_clean_watermark` P1 [platform_ops] [internal alert watermark] phase_z_baseline_missing
- `email-12141-5a75b7` P3 [email_reply] [email_reply] Re: [VolPred Alert][WARN] Dreaming review 2026-07-18 — 3 new / 0 escalations
- `daily_digest_20260719` P1 [daily_digest] [daily_digest] 寫一篇每日精選導讀專題策展並發佈
- `alert_internal_git_push_backup_hold_3f4834ce7a_clean_watermark` P1 [platform_ops] [internal alert watermark] git_push_backup_hold

## 7. Dashboard 訊號

- overall_status=warn (breaches=2, critical=0, generated=2026-07-19T01:30:16Z)
- WARN: section=production_throughput :: 5 articles published last 24h (target 6/day)
- WARN: section=verification_fb_pipeline :: 1 FB posts pending sync

## 8. 最近 work_log（5 筆，新→舊）

- `2026-07-19T09:39` [email_reply] email-12141-5a75b7
- `2026-07-19T09:35` [daily_digest] daily_digest_20260719
- `2026-07-19T08:12` [experiment] agent-brief_k1731_armB_rev6-526c33
- `2026-07-19T07:17` [platform_ops] trending_repost_2026_07_19_地緣避險
- `2026-07-19T07:16` [experiment] assign_67f56b79

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


exec
/bin/zsh -lc "nl -ba experiments/k1732/codex_review_v1.md | sed -n '1,260p'
wc -l experiments/k1732/k1732.py experiments/k1732/README.md experiments/k1732/k1732_figures.py experiments/k1732/k1732_results.json
rg -n \"cross_state|circular|shift|random|bootstrap|Bonferroni|唯一|增量|內生|1494|1,494|onset|30|28|alt|26|24|7/10|0.0023|iloc|estimator_sensitivity|bias|71|0.9715|36.9|23.9|beta|β\" experiments/k1732/k1732.py experiments/k1732/README.md experiments/k1732/k1732_figures.py experiments/k1732/k1732_results.json" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
     1	OpenAI Codex v0.144.1
     2	--------
     3	workdir: /Users/yhlai0911/volpred-research
     4	model: gpt-5.6-sol
     5	provider: openai
     6	approval: never
     7	sandbox: danger-full-access
     8	reasoning effort: high
     9	reasoning summaries: none
    10	session id: 019f7833-2877-7951-b1de-c1cf1c19a252
    11	--------
    12	user
    13	你是嚴格的計量金融代碼審查者。審查實驗 K1732（絕對路徑 /Users/yhlai0911/volpred-research/experiments/k1732/）：
    14	
    15	**背景**：Lai & Chang (accepted) 提出 Cornish-Fisher VaR 分解預警（β_s/β_k/IS_k 的 MA20/MA30 死亡交叉，26 週滾動動差、α=5%、週資料）。K1732 把訊號放到 TAIEX 1997-2026 做系統性回測。論文公式：z_CF = z + (1/6)(z²−1)s + (1/24)(z³−3z)(k−3) − (1/36)(2z³−5z)s²；β_s = −σ[(1/6)(z²−1) − (1/18)(2z³−5z)s]；β_k = −σ(1/24)(z³−3z)；IS_i = |dVaR_i|/Σ|dVaR_i|，dVaR_i = β_i·ΔX_i。
    16	
    17	**必讀檔案**：k1732.py（主腳本）、README.md（宣稱面）、k1732_results.json（結果）、k1732_figures.py（圖表）。
    18	**必讀規範**：/Users/yhlai0911/volpred-research/.claude/skills/autonomous-research/references/experiment-preamble.md
    19	
    20	**審查重點**：
    21	1. Lookahead：訊號是否確實只用 t−1 資訊評估 onset？shift(1) 的對齊有無 off-by-one？forward 視窗（onset in t+1..t+13）的 rolling-reverse 實作對嗎？
    22	2. 死亡交叉狀態機（cross_state）與 weeks_since_last_death 的回溯邏輯正確性
    23	3. episode onset 定義（與上一崩跌週間隔 >13 週）實作是否與 README 宣稱一致
    24	4. 公式實作是否忠於論文（z=Φ⁻¹(0.05) 負值時各項符號）；pandas skew/kurt（bias-corrected、excess）與論文樣本動差的差異是否已誠實揭露
    25	5. circular block bootstrap 實作正確性（block 重疊、邊界、p 值定義）
    26	6. README 每一個數字與宣稱是否被 k1732_results.json 支持？有無 overclaim（特別是「唯一帶增量資訊」「Bonferroni 後仍顯著」「boundary condition 非 refutation」等語句）
    27	7. mechanical equivalence 宣稱（β_k 交叉恆等於 σ 上升趨勢交叉）是否被代碼驗證支持
    28	
    29	**輸出格式**：
    30	- 逐點 findings（嚴重度 CRITICAL/MAJOR/MINOR + 檔案:行號 + 說明）
    31	- 最後一行單獨輸出 verdict，格式：`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 需列 blocking defects）
    32	
    33	codex
    34	我會依指定規範做唯讀審查，先讀 handoff、experiment preamble 與四個實驗檔，再用小型獨立重算核對索引、公式、bootstrap 和 README 宣稱；不會修改任何檔案。
    35	exec
    36	/bin/zsh -lc "cat storage/ops/handoff_latest.md && sed -n '1,240p' .claude/skills/autonomous-research/references/experiment-preamble.md" in /Users/yhlai0911/volpred-research
    37	 succeeded in 0ms:
    38	# Handoff — 2026-07-19 09:50:02 台灣時間
    39	
    40	**角色**：VolPred 自主運營經理（用戶 = 老闆 / report-only / full autonomy）
    41	
    42	> 此檔由 `scripts/generate_handoff.py` 每小時 :50 自動產生。手寫補充請放本檔末段「## 候補 / 手動補充」並標時間戳。
    43	
    44	## 1. 任務池快照（`storage/next_tasks.json`）
    45	
    46	- **總數**：2905
    47	  - pending: 87
    48	  - pending_main_thread: 6
    49	  - succeeded: 2598
    50	  - failed: 52
    51	  - blocked: 13
    52	  - blocked_on_user: 2
    53	  - Codex-eligible pending: 82
    54	  - Codex-skip pending: 11
    55	
    56	**type 分佈（top 6）**：
    57	  - daily_article: 698
    58	  - experiment: 650
    59	  - platform_ops: 419
    60	  - paper_review: 415
    61	  - telegram_reply: 207
    62	  - email_reply: 187
    63	
    64	## 2. 已 claim / in_progress 任務
    65	
    66	- (無 — 任務池閒置)
    67	
    68	## 3. Email 回信任務（**優先處理**）
    69	
    70	- (無未處理回信)
    71	
    72	_Gmail 最後 poll：2026-07-19T01:45:10.574751+00:00_
    73	
    74	## 4. Pending 任務 top 8（依 priority asc）
    75	
    76	- **Codex-eligible pending**：82；**Codex-skip pending**：11
    77	
    78	**Codex-eligible pending top 8**：
    79	- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
    80	- `assign_ae004ae2` P1 [experiment] k528 NFP 事件日污染修復：254 筆中 53 筆（20.9%）不是 NFP 日，線上文章 mile_35eef830 核心數字全建立其上
    81	- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
    82	- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort
    83	- `alert_content_quality_20260719` P2 [governance] [alert] 內容品質巡檢：發文間隔過久
    84	- `alert_release_pool_gap_20260719` P2 [platform_ops] [alert] Release pool starved > 8.0h (cron healthy)
    85	- `assign_2398cbfe` P2 [platform_ops] [P35-retry] Codex K1258 review (BLOCKED: gpt-5.5 infrastructure issue)
    86	- `assign_23b2a961` P2 [experiment] 全 repo first-Friday proxy sweep：6 支腳本仍在用，k904 在 paper/ 底下可能影響論文
    87	
    88	**All pending top 8**：
    89	- `K1169` P1 [paper_body] K1169: Paper 2 §5 narrative rewrite (main thread, K1166 correction)
    90	- `K1699_article_general` P1 [daily_article] K1699: write general-audience article (auto-discovered uncovered K)
    91	- `assign_ae004ae2` P1 [experiment] k528 NFP 事件日污染修復：254 筆中 53 筆（20.9%）不是 NFP 日，線上文章 mile_35eef830 核心數字全建立其上
    92	- `growth_p1_auth_onboarding` P1 [platform_ops] [growth P1] 註冊/登入 flow 現況盤點 + welcome onboarding
    93	- `growth_p1_reader_analytics` P1 [platform_ops] [growth P1] Reader analytics ingestion — CTR / 停留時間 / 跳出率 / 回訪 cohort
    94	- `member_qa_3e258ba2_research_write` P1 [member_qa] [member_qa] yaoxk1431 30年7%穩定成長提問 —— research + write + publish 後半段
    95	- `K1414_paper3_hln_retrofit` P2 [experiment] K1414: Paper 3 HLN small-sample DM correction retrofit (TW0050-N225 唯一 Harvey sig)
    96	- `Paper3_expansion_synthesis_decision_meta` P2 [paper_decision] [paper_decision] Paper 3 A 三 E 完成後 → meta synthesis decision
    97	
    98	## 5. 進行中 agent / worktree
    99	
   100	- **slot 占用**：16 / 4
   101	- worktrees:
   102	  - `dispatch-slot-1-1533dcbc-cqamend`
   103	  - `dispatch-slot-2-8dda242d-k1708`
   104	  - `dispatch-slot-1-3217f0b2-pushgate`
   105	  - `dispatch-slot-1-f53bca44-k1692`
   106	  - `dispatch-slot-1-79726798-credit-firm`
   107	  - `dispatch-slot-2-5ddfeb00-k1583`
   108	  - `dispatch-slot-1-f53bca44-k1694`
   109	  - `codex-desktop-k1707`
   110	  - `dispatch-slot-1-3217f0b2-k1685`
   111	  - `dispatch-slot-1-bd00f90a-k1731`
   112	  - `dispatch-slot-1-b55db3be-2`
   113	  - `dispatch-slot-1-558d7893-k1730`
   114	  - `dispatch-slot-1-957aa2f2-k1630`
   115	  - `dispatch-slot-1-30aeb902-taifexrv`
   116	  - `dispatch-slot-1-957aa2f2-k1649`
   117	  - `dispatch-slot-1-a56566ff-k1719`
   118	
   119	## 6. 最近 24h 完成（top 5）
   120	
   121	- `canonical_writers_publisher_feed_unguarded_20260719` P2 [platform_ops] [platform_ops] canonical-writers gate 紅：article_correction 未註冊 owner（已修）
   122	- `alert_internal_phase_z_baseline_missing_537a3ff330_clean_watermark` P1 [platform_ops] [internal alert watermark] phase_z_baseline_missing
   123	- `email-12141-5a75b7` P3 [email_reply] [email_reply] Re: [VolPred Alert][WARN] Dreaming review 2026-07-18 — 3 new / 0 escalations
   124	- `daily_digest_20260719` P1 [daily_digest] [daily_digest] 寫一篇每日精選導讀專題策展並發佈
   125	- `alert_internal_git_push_backup_hold_3f4834ce7a_clean_watermark` P1 [platform_ops] [internal alert watermark] git_push_backup_hold
   126	
   127	## 7. Dashboard 訊號
   128	
   129	- overall_status=warn (breaches=2, critical=0, generated=2026-07-19T01:30:16Z)
   130	- WARN: section=production_throughput :: 5 articles published last 24h (target 6/day)
   131	- WARN: section=verification_fb_pipeline :: 1 FB posts pending sync
   132	
   133	## 8. 最近 work_log（5 筆，新→舊）
   134	
   135	- `2026-07-19T09:39` [email_reply] email-12141-5a75b7
   136	- `2026-07-19T09:35` [daily_digest] daily_digest_20260719
   137	- `2026-07-19T08:12` [experiment] agent-brief_k1731_armB_rev6-526c33
   138	- `2026-07-19T07:17` [platform_ops] trending_repost_2026_07_19_地緣避險
   139	- `2026-07-19T07:16` [experiment] assign_67f56b79
   140	
   141	## 9. 接續提示詞（hourly dispatch / 互動 session 共用）
   142	
   143	```
   144	讀 storage/ops/handoff_latest.md 後依以下優先序選工：
   145	
   146	優先序 (HARD)：
   147	  1. Section 3 Email reply 任務（task_type=email_reply）— 若有 pending，立即 claim + 處理（讀 description 的「用戶回信內容」+「原始助理寄出內容」，依用戶指示回應 / 修正 / 派工 / 寄回信）
   148	  2. Section 7 Dashboard CRITICAL — 立即 triage
   149	  3. Section 4 Pending 任務 top 8 — 依 priority asc + work_log diversity（last-3 task_type rotate）
   150	
   151	Claim 流程（避免雙 session 撞題）：
   152	  uv run python scripts/task_pool_claim.py claim --id <task_id> --owner <hourly|interactive|agent-name>
   153	  uv run python scripts/task_pool_claim.py start --id <task_id>
   154	  ... 執行 ...
   155	  uv run python scripts/task_pool_claim.py complete --id <task_id> --status succeeded --result '...摘要...'
   156	
   157	完整完成原則：派 agent 後 wait 完成、驗證、寫 knowledge.json / work_log、commit。50min cap。Heavy compute 走 compute_queue。
   158	```
   159	
   160	---
   161	
   162	## 候補 / 手動補充
   163	
   164	（此區由人工 / 互動 session 編輯。只有放在 KEEP 註解標記區段內的手寫內容會被 auto-regen 保留，其餘自動章節每 :50 覆寫。標記語法見 generate_handoff.py `_extract_keep_block` 或 docs；標記本身不寫在此說明以免與 extractor 自我衝突。）
   165	
   166	<!-- KEEP -->
   167	### ⏱ 2026-07-01 ~16:00 最新狀態（compact 後最優先讀）
   168	**已完成+committed 今日**：(1) 12 死碼腳本移 `scripts/_legacy/`（crontab「雙觸發」是 false positive、未動）；(2) hourly-dispatch 修 stale opus-4-7→**opus-4-8** + model_router sonnet→**sonnet-5** + token_usage_report pricing 補 4-8/5；(3) `check_model_roster.py` 加 stale-model-pin 掃描（代碼零 pin）；(4) **pre-gate `scripts/hourly_dispatch_pregate.py` 部署 SHADOW 模式**（`PREGATE_SHADOW=1`，只記 log 不跳過；~1 週後審 `storage/logs/hourly_pregate.jsonl` 確認「判 skip 的真沒產出」再 flip `PREGATE_SHADOW=0`）；(5) **每日 token 報表 `scripts/token_report_email.py`**（多角度 HTML 內嵌）+ **cap 校準到官方**（`config/token_quota_calibration.json`，report 顯示 76%=官方 Weekly；官方飄移用 `--calibrate <fraction>` 重錨）。
   169	**待用戶**：token 報表版面確認後→排每日定時任務（runtime_schedules.json + `~/.volpred/bin/` wrapper + piggy-back/LaunchAgent + 文件，建議每日 08:00 台灣）。
   170	**重要教訓（勿重犯）**：我曾誤判 token 報表「3× 灌水」並提議去重，被用戶官方截圖 76% 打臉 → **報表 per-record 加總方法本來就對、與官方一致，勿再用 message.id 去重**。thinking/reasoning 因 redact+output 合計無法可靠拆分，不列不硬湊。
   171	**接續**：turn 尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`；工具嚴格 `antml:invoke`；中文用 Write 不用 heredoc；emoji 勿放 bash echo。
   172	
   173	### ⏱ 2026-07-01 ~14:55 手動 handoff（compact/退出前｜最新最優先讀｜此段在 KEEP 區、撐得過 auto-regen）
   174	
   175	**兩個架構稽核 subagent 皆完成（結果已在對話，勿重跑）**：
   176	- **token overhead**：每天 ~460 次例行觸發，只 ~72 次吃 token（24 hourly-dispatch + ~48 互動 loop tick），其餘 436 次純 Python 零 token。純 overhead ≈ 每週 **7–16%** 預算。**最大槓桿 = hourly-dispatch 每次冷載 CLAUDE.md+context ≈ 95K token ×24/天 = 2.28M/天（stub 空跑也付）**。本週 3.5 天用 158.8M(73.9%)。
   177	- **疊床架屋 + 我的主線程驗證**：⚠️ subagent 兩個誤判要修正 —— (1)「5 任務 crontab+LaunchAgent 雙觸發、砍 crontab」= **FALSE**（control-plane.md：本機 macOS cron 只可靠跑 `0 * * * *`，其他 pattern silently skip，crontab 是 harmless 永不 fire 的 fallback、刻意保留；**勿砍、勿跑 install_host_crontab.sh**）；(2) `record_and_publish.py` 非死碼（feed-publisher「方法 B」）。✅ **真可收斂**：`article_backups.py`(no-op 死碼)+殭屍 import、13+ 歷史一次性腳本 → 移 `scripts/_legacy/`；`release_pool` 頻率三處不一致(spec `7 */6` vs crontab `7 */3` vs LaunchAgent 6h)→ 對齊。✅ **澄清**：4 條 Supabase sync 互補非重複，全留。
   178	- **下一步**：回報老闆(含 crontab false-positive 修正) → 執行安全收斂(死碼移 _legacy + release_pool 頻率) → hourly-dispatch token 優化選項提老闆(減層不加層)。
   179	
   180	**digest 已定案上線（老闆連 4 次糾正，勿重做）**：`mile_4901f7bc`=今天 digest 原地抽換=**AI 資本支出投資議題專欄 v2**（時事驅動→撈 8 篇跨時間 archive→回答「該不該擔心+選擇權怎麼定價」；body 4604字、8 篇每段 inline 標註、具名框架「三個 VIX 照不到的角落」+三項檢查表）。Chrome 驗證 live（CDN 舊快取→`?v=` cache-bust 見新）。**spec 已 3 修**（`enqueue_daily_digest.py`：時事驅動+全archive禁本週湊、name-first、深度≥4000+inline標註）。
   181	
   182	**leverage 論文 gated**：`paper_pipeline_status.json` `do_not_advance=True`；Stage 2 兩支柱皆弱(K1591/K1592 我驗證 sound)→非 JBF-grade→待老闆研究方向決策(FRL/IJF/null/暫置，WARN email 已送)。**勿自動推 arXiv**。
   183	
   184	**模型政策**：主線 opus 固定、subagent sonnet↔opus 依難度、haiku off、fable unavailable。source=`config/models.json`。
   185	
   186	**接續提示詞（2026-07-01 14:55）**：讀本段。下一步=回報兩份稽核(含 crontab false-positive)+執行安全死碼/release_pool 收斂+提 hourly-dispatch token 優化。digest 完成勿重做，leverage 待老闆。turn 尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`。工具嚴格 `antml:invoke`，中文用 Write 不用 heredoc，emoji 勿放 bash echo。
   187	
   188	---
   189	
   190	### 📄 學術論文線 — 老闆 2026-07-01 ~00:45-02:00 連續 ~14 指令（最高優先，clean context 接續）
   191	
   192	**老闆核心訴求**：論文線「感覺停滯」。diagnosis（paper-audit workflow）：不缺彈藥，缺「扣扳機」+ synthesis/submission gate 沒人 drive。
   193	
   194	**已建好的流程基礎建設（durable，已 commit+push）**：
   195	- skill `paper-submission-pipeline`（狀態機 draft→revision→compliance_scrub→multi_round_review→review_converged→arxiv_ready→arxiv_posted→journal_submitted；PDCA gate）+ `scripts/paper_pipeline_check.py`（stall detector）+ `storage/paper_pipeline_status.json`（14 篇 stage tracker）
   196	- skill `journal-review`（10 期刊上網查的 references + templates：JBF/JFE/RFS/JoE/FRL/IJF/JPM/FAJ/PBFJ/JoF）
   197	- 合規 audit 全結果 `storage/ops/paper_compliance_audit_20260701.json`（14 篇，1 clean，13 待修）
   198	
   199	**老闆硬規則（必遵守）**：
   200	1. **投稿論文作者僅「Yi-Hao Lai」**，禁 volpred/claude/ai/llm 提及，禁 AI 用語符號
   201	2. **contribution gate**：review 必看真正貢獻/經濟意義，**非單純計量方法練習**（純方法練習不過 gate）
   202	3. **arXiv 只給 ready-for-submission 的**（drafts/revision 禁上）；流程 = scrub→多輪 review→修正→最終版**先丟 arXiv 佔 priority**→找機會投目標期刊（投稿時點老闆擇時拍板）
   203	4. **多輪 review 全用 codex exec 跑**（latex-academic-reviewer + citation-verifier + journal-review）省 Claude token；**codex 額度無限制**
   204	5. **任何前端改動，/paper 原版 + /v3/paper 兩版都要改**（standing rule，兩版是不同網頁）
   205	6. **內容編輯類「完成」必 curl+Chrome 線上驗證**，不假設（老闆兩次抓我假宣告）
   206	
   207	**目前只有 1 篇真正 ready**：`leverage-direction`(JBF) — 6/11 技術定稿、合規只差 body.tex:231 一個 VolPred footnote（fix 在 audit json）。`vt-trend-following`(JPM/FAJ) 下一棒（6/30 才 v7 PASS + 10 個 K-id tags 待清）。
   208	
   209	**P1 queued（durable）**：`paper_compliance_scrub_leverage_direction`（1 footnote）、`paper_compliance_scrub_vt_trend_following`（10 tags）、`content_erratum_mile_48c8328b_k189_reversed`（誠信：文章結論與 K189 相反）。
   210	
   211	**下一步（clean context 接）**：drive leverage-direction：scrub 1 footnote → codex 多輪 review（含 contribution gate）→ 修到最終 → arXiv。每階段更新 pipeline tracker + 回報。
   212	
   213	**✅ 已完成本 session（verified）**：論文頁 Updated 顯示加 date+hh:mm（兩版 Chrome 驗證：/v3/paper + /paper 都顯示「Updated 2026-06-24 18:00」）；feed 文章「更新於」功能（誤解產物，老闆要的是論文非文章，但功能無害留著）；8 篇 prose-dump lazypack 用 codex-exec 重做（前幾 tick）。
   214	
   215	---
   216	### 🔴 FB URGENT BANNER（2026-07-01 01:10 hourly-01 標 — 老闆 email-12327 親點派）
   217	
   218	**老闆 2026-06-30 23:54 email：「Fb都開著 你自己切換啊」**。hourly cron 無 Chrome MCP 做不了，已 close-reply email 接力。下個 interactive session **第一動作** = 切 Chrome 連 MAC STUDIO（deviceId 輪替不可 hardcode，照 `reference_fb_chrome_browser_autoselect` 即時 `list_connected_browsers` 找登入 yihao.lai 的那台），到 facebook.com/yihao.lai 走 `.claude/skills/trending-repost/references/fb-ivanlai-tone.md` SOP **5 篇逐一發**（每篇主貼文無連結 + 第一則留言貼 volpred 連結 + `mark_fb_post_status.py --mile-id <id> --status success`）：
   219	
   220	| 序 | mile_id | 標題 | 等待時數 |
   221	|---|---|---|---|
   222	| 1 | `mile_f5f4cb43` | 科技巨頭資本支出爆表，AI 變現期的隱含波動率拐點 | ~20h |
   223	| 2 | `mile_819af916` | 防禦股悄悄贏了：XLV 一個月漲 8%，科技 ETF 卻原地踏步 | ~26h |
   224	| 3 | `mile_a0b174f9` | 蘋果一週跌 4.8%、波動跳 2.3 倍；NVDA 跌 8.6% 卻反而最低 | ~64h |
   225	| 4 | `mile_bd564eb7` | 創新高然後急殺，「短彈可搶、抱一年會死」是真的嗎？bootstrap | ~74h |
   226	| 5 | `mile_0941e2f0` | 半導體修正進行中：選擇權偏斜告訴你市場還沒放心 | ~74h |
   227	
   228	連結模板：`https://volpred.zeabur.app/v3/reports/<mile_id>` → 留言。預估 5 篇 ≤30 分鐘。發完寫 work_log + 寄 boss confirm email。
   229	
   230	**結構性 follow-up**（queue 進 platform_ops）：把 `audit_fb_pipeline.py >72h auto-expire` 改 48h（3/5 已 >64h，timely insight 衰減）+ early-warn 階段。
   231	
   232	---
   233	
   234	### 🟢 互動 session 脈絡（2026-06-30 ~18:00 台灣時間）— 最新，compact 後優先讀
   235	
   236	接續 ~13:55 段之後，下午又完整交付（全 commit+push 到 GitHub，main repo 與 origin 同步 0/0）：
   237	
   238	**A. 下午已交付（改完+test+commit+push）**：
   239	1. **quota 計算雙修**（boss 抓 122% vs dashboard 54%）：(a) `weekly_quota_estimate.py` anchor 漂 7 週未校準 → re-anchor 54%@116M→cap 215M + 加 ANCHOR_STALE_DAYS=10 警告；(b) `token_usage_report.py` weekly window 從週五對齊改 **週日16:00 台灣**（boss 確認 quota 週期 SUN16:00-SUN15:59）→ `get_quota_week_range`（friday alias 保留），week 6/28→7/05。
   240	2. **publishing_freshness 門檻 interval-aware**（第三個對齊 6h release 的 publish-gap 門檻，前兩個 burst/drought）：5h hardcode → interval+2h grace=8h。+ 修 hourly 引入的 `mark_fb_post_status.py:113` silent fallback（解封 git_push_backup）。
   241	3. **lazypack 偵測**（boss：general 文章缺懶人包圖，實測近12篇只1篇有=12%）：`content_quality.py` 加 lazypack coverage（<0.6→lazypack_gap）。**生成/enforce 未做**（queue `platform_ops_enforce_lazypack_in_publish_pipeline`，需 NotebookLM+乾淨 context）。
   242	4. **🔑 換機可攜性全套**（boss：另一台機 clone+填env 就能運作 + skills/agents 完整保留）：新建 `README.md`（根目錄 GitHub 入口）+ 重寫 `docs/host-migration.md`（逐步手冊）+ `.env.example`（三檔 secrets 範本）+ `scripts/bootstrap_new_host.sh`（一鍵）+ `backup_user_claude.sh`/`restore_user_claude.sh` + `ops/claude_user_backup/`（**128 檔：user-level CLAUDE.md+27 skills+100 memory 快照**）+ 每日 05:35 `cron_backup_user_claude` 自動保鮮。**repo 確認 PRIVATE**。釐清：project-level `.claude/` 自動進 repo；user-level `~/.claude` 原不進→已快照+每日同步。
   243	
   244	**B. 已 queue 待 clean-context（勿在 bloated context 草率做）**：`platform_ops_enforce_lazypack_in_publish_pipeline`(P2，NotebookLM 生成懶人包+enforce+回補)、`paper_review_vt_trend_v7_codex_primary_path_verify`(P3，Codex)、`platform_ops_centralize_release_cadence_thresholds`(P3，抽共用 release-interval helper)、`platform_ops_publish_rhythm_pre_publish_throttle`(P3，publisher 核心路徑謹慎)。dreaming persistent-alert detector 已由 hourly-14 建好+我驗證 sound（抓到 6 個真 active 持續 alert）。
   245	
   246	**C. Meta-lesson**：今天一連串（cluster/burst/drought/freshness 誤報、quota anchor 漂移、lazypack silent skip）全同類「規則/測量沒人持續盯就失準/被跳過」。修法哲學統一=偵測層讓 gap 自動可見（區分 discretionary vs fixture/event/operational）。
   247	
   248	**接續提示詞（2026-06-30 18:00）**：讀本段。系統健康（breach_count=0、daily-checkup ok、無 pending email、main repo 與 GitHub 同步）。從自主 ops loop 繼續：PHASE 0 清 email backlog → 推進上述 B 的 queued P2/P3（**乾淨 context 起跑後最該先做 lazypack 生成 enforce + VT-trend v7**）→ 沒 critical 主動掃 5 missions。**換機可攜性已完成**，新機照 README/host-migration 可運作。turn 尾排 `ScheduleWakeup(prompt="<<autonomous-loop-dynamic>>")`，工具嚴格 `antml:invoke`，emoji 勿放 bash echo（會 UnicodeEncodeError）。
   249	
   250	### 🟢 互動 session 脈絡（2026-06-30 ~13:55 台灣時間）
   251	
   252	長 session（57+ commits），老闆連續高強度抓問題 + 逼 root-cause 不表面修。已完整根治並上線驗證：
   253	
   254	**A. 今日已交付（改完+test+部署/驗證+commit）**：
   255	1. **2 個長期 warn 根治**（boss email-12256/12281「存在很久」）—— 都是「測量太粗誤報合法模式」：(a) **cluster spy catch-all**：keyword 分類把所有用 SPY 當測試資產的 vol 研究算成 spy → 加 6 粒度主題 cluster（risk_mgmt/forecast_method/event_study/hedging/microstructure/return_predict）+ specific-first 排序 + spy 收窄移除「美股」，spy 74→14（`topic_clusters.py`，commit bd2b68bff）；(b) **publish_rhythm burst**：digest+trending fixture 偶然相近被誤判 → burst 只算 discretionary 文章 clumping，排除 `_NON_RHYTHM_PHASES`（`content_quality.py`，commit 3d1dfed8a）。breach_count→0。
   256	2. **daily_update intraday 14:00**（boss 親建 plist+wrapper，我驗證全鏈 + smoke-test 撞出 transient SSL hang → kill+lock 釋放）+ **兩 wrapper 加 600s perl-alarm watchdog** 杜絕 lock cascade（commit 6a3352c3f）。daily_checkup order-flow 改 result-level（ebbed800d）。
   257	3. **策略卡 VIX 情景軌跡**（boss 問「3 張卡為何相同」）：`strategy-regimes.ts` + `DailyDigestSection` 無關，是 `StrategyPanel.tsx` 加「VIX 低→高」三點軌跡揭露低/高 VIX 分歧。deploy 上線驗證 11 卡（commit 40d86fa）。
   258	4. **首頁導讀發布時間 hh:mm**（boss 指出 detail 頁有但首頁漏）：`DailyDigestSection.tsx` 右側加「發布 hh:mm」台灣時間。deploy 驗證（commit 5ad0675）。
   259	5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。
   260	
     328 experiments/k1732/k1732.py
      95 experiments/k1732/README.md
     139 experiments/k1732/k1732_figures.py
     914 experiments/k1732/k1732_results.json
    1476 total
experiments/k1732/README.md:3:**日期**: 2026-07-19 ｜ **提出**: 老闆（2026-07-17 台股 -6.47% 後指示「做」）｜ **執行**: Claude（主線程）
experiments/k1732/README.md:8:Lai & Chang（2409-662，已獲接受）以 Cornish-Fisher VaR 分解建立雙預警架構：β 敏感度（β_s、β_k）
experiments/k1732/README.md:9:與峰態影響份額（IS_k）的 MA20/MA30 死亡交叉，在 19 個全球指數 × 3 次危機（2007-08、COVID、貿易戰）
experiments/k1732/README.md:10:的事件研究中驗證。2026-07-17 台股單日 -6.47%（收 42,671），本 K 把同一套訊號放到 TAIEX 全歷史
experiments/k1732/README.md:11:（1997-07 ~ 2026-07-17，週報酬 n=1,494）做**事件定義預先註冊**的系統性回測。與論文的事件研究互補：
experiments/k1732/README.md:15:相關 K / 知識庫：K836（台股 1% VaR 8 法比較，CF-VaR 唯一達標）、knowledge `a8c740e9`/`589692f0`
experiments/k1732/README.md:21:- **資料**：Yahoo Finance ^TWII，W-FRI 週 log 報酬；26 週滾動 σ/偏態/超額峰態（pandas 樣本估計式，
experiments/k1732/README.md:22:  bias-corrected；論文用標準樣本動差 — 見下方 estimator sensitivity）
experiments/k1732/README.md:23:- **訊號**（論文 eq 4/11/12/14，α=5%）：β_s、β_k、IS_k 的 MA20/MA30 死亡交叉；警戒=MA20<MA30；
experiments/k1732/README.md:25:- **事件**：週 log 報酬 ≤ −5% 為崩跌週；與上一崩跌週間隔 >13 週才算新 episode onset。
experiments/k1732/README.md:26:  全期定義出 **30** 次 onset（−4% robustness：26 次）；其中落在訊號評估期（暖機完成後）的
experiments/k1732/README.md:27:  **28** 次（robustness 24 次）進入逐事件評估
experiments/k1732/README.md:28:- **Ex-ante 紀律**：一律取 onset **前一週（t−1）** 的訊號狀態（代碼有明確 `shift(1)`）；lead time
experiments/k1732/README.md:29:  = 最近一次死亡交叉至 onset 的週數；論文有效判準 = 交叉在 onset 前 ≥3 週且中間無黃金交叉
experiments/k1732/README.md:30:- **誤報成本**：precision（死亡交叉後 26 週內出現 onset 的比例）、warning burden（警戒週占比）
experiments/k1732/README.md:31:- **關聯檢定**：週頻 P(未來 13 週出現 onset | 警戒) vs P(… | 非警戒)。
experiments/k1732/README.md:32:  - 區間估計：circular block bootstrap（block=26、B=2000、seed=42）95%/99% percentile CI
experiments/k1732/README.md:33:  - 正式檢定：**circular-shift randomization**（隨機旋轉 active 相對 fwd，offset≥13，B=5000，
experiments/k1732/README.md:34:    保留兩序列自相關、破壞對齊；p=(r+1)/(B+1)，單尾）— empirical bootstrap 的 `P(draw≤0)`
experiments/k1732/README.md:36:- **Mechanical 對照**：β_k = −σ·(1/24)(z³−3z) 是 σ 的線性變換 → β_k 死亡交叉**恆等於**
experiments/k1732/README.md:37:  「σ MA20 上穿 MA30」（代碼驗證 26 次交叉完全重合）；β_s 與 −σ 相關 0.9715，偏態項係數比
experiments/k1732/README.md:38:  為 0.0376/0.2843 ≈ 13%/每單位偏態，本樣本偏態範圍 [−2.79, +1.81] 對應相對調變 −36.9% ~ +23.9%
experiments/k1732/README.md:43:| 指標 | β_s | β_k | IS_k | σ-trend bench |
experiments/k1732/README.md:45:| 死亡交叉次數（29 年） | 28 | 26 | 71 | 26 |
experiments/k1732/README.md:46:| 命中率 P(警戒@t−1 \| onset) | 46.4% | 46.4% | **71.4%** | 46.4% |
experiments/k1732/README.md:50:| precision（26 週內有 onset） | 53.6% | 53.8% | 45.1% | 53.8% |
experiments/k1732/README.md:51:| P(onset 13w \| 警戒) − P(\| 非警戒) | −0.047 | −0.046 | **+0.151** | −0.046 |
experiments/k1732/README.md:52:| block bootstrap 95% CI | 含 0 | 含 0 | **[0.047, 0.250]** | 含 0 |
experiments/k1732/README.md:53:| circular-shift 單尾 p | 0.738 | 0.714 | **0.0138** | — |
experiments/k1732/README.md:54:| −4% robustness 命中率（n=24） | 41.7% | 37.5% | **75.0%** | 37.5% |
experiments/k1732/README.md:56:**Estimator sensitivity**（population bias=True 動差重算 IS_k）：死亡交叉 71 vs 71 次、
experiments/k1732/README.md:57:僅 6 個交叉日期不同、1,494 週中僅 5 個警戒週不同 — 主結果對估計式選擇穩健。
experiments/k1732/README.md:59:**2026-07-17 案例**（週報酬 −6.10%）：β_s 死亡交叉 2026-03-27（前 16 週）、β_k 2026-04-03（前 15 週）
experiments/k1732/README.md:61:7/03 +0.0010，**7/10（t−1）小幅回彈至 +0.0023**，7/17 翻負 −0.0042 — 大致收斂但非嚴格單調，
experiments/k1732/README.md:63:（β 警戒則滿足 ≥3 週判準）。
experiments/k1732/README.md:67:1. **三個單變量檢驗中，IS_k 是唯一估計為正且 CI 排除 0 的訊號**：警戒中未來 13 週崩跌起點機率
experiments/k1732/README.md:68:   17.2%→32.3%（circular-shift 單尾 p=0.0138；×3 訊號 Bonferroni 校正後 0.041，5% 水準下顯著；
experiments/k1732/README.md:69:   95%/99% percentile CI 均排除 0）；命中率 71.4% 高於 49.1% 覆蓋率；論文判準有效率 60.7%，
experiments/k1732/README.md:71:   也未估計聯合模型，「IS_k 顯著而 β 不顯著」不等於「兩者差異顯著」；危機類型機制（內生 vs 外生）
experiments/k1732/README.md:73:2. **β 死亡交叉在 TAIEX 29 年中未展現超越隨機覆蓋的關聯**（p≈0.71–0.74，命中率 46.4% ≈ burden
experiments/k1732/README.md:74:   46.1%）。mechanical 揭露：β_k 交叉恆等於波動率上升趨勢交叉；β_s 高度近似（corr 0.9715）。
experiments/k1732/README.md:75:   **這與論文跨 19 市場事件研究中 β 有效率較高（47–89%）並不矛盾**：論文條件在「已發生的危機」
experiments/k1732/README.md:76:   上計時，本 K 加計了全部誤報；單一市場 28 個評估事件也不足以推翻跨市場結論 —
experiments/k1732/README.md:84:- 單一市場；30 次 onset（28 次可評估）；事件門檻雖預先註冊仍屬研究者選擇（−4% robustness 方向一致）
experiments/k1732/README.md:86:- 週頻樣本動差估計噪音大（論文 §3.7 已討論；MA20/30 平滑是論文原設計）
experiments/k1732/README.md:88:- yfinance 早年 TWII 資料品質未逐點稽核；已 guard 最後日期 ≥2026-07-17 防 stale
experiments/k1732/k1732_figures.py:1:"""K1732 圖表：(1) 2026-07-17 案例時序 (2) 29 年回測摘要 (3) 全歷史警戒負擔誠實圖。
experiments/k1732/k1732_figures.py:20:px = pd.read_csv(os.path.join(D, "k1732_twii_weekly_close.csv"), index_col=0, parse_dates=True).iloc[:, 0]
experiments/k1732/k1732_figures.py:22:MA_S, MA_L = 20, 30
experiments/k1732/k1732_figures.py:31:# ---------- Fig 1: 2026-07-17 案例 ----------
experiments/k1732/k1732_figures.py:32:lo, hi = pd.Timestamp("2025-07-01"), pd.Timestamp("2026-07-24")
experiments/k1732/k1732_figures.py:38:gap_bs, act_bs = ma_state(m["beta_s"])
experiments/k1732/k1732_figures.py:42:ax1.axvline(pd.Timestamp("2026-07-17"), color=C_VERM, lw=1.2, ls="--")
experiments/k1732/k1732_figures.py:43:ax1.annotate("7/17 單日 −6.5%", xy=(pd.Timestamp("2026-07-17"), pxz.min()), xytext=(-118, 8),
experiments/k1732/k1732_figures.py:45:ax1.annotate("β 死亡交叉警戒區（3/27 起）", xy=(pd.Timestamp("2026-04-10"), pxz.max() * 0.99),
experiments/k1732/k1732_figures.py:48:ax1.set_title("2026-07-17 大跌前：論文三訊號的實際時序", fontsize=13, loc="left", pad=10)
experiments/k1732/k1732_figures.py:50:bsz = m["beta_s"].loc[lo:hi]
experiments/k1732/k1732_figures.py:51:ax2.plot(bsz.index, m["beta_s"].rolling(MA_S).mean().loc[lo:hi],
experiments/k1732/k1732_figures.py:52:         color=C_ORANGE, lw=2, label="β_s 短均線 MA20")
experiments/k1732/k1732_figures.py:53:ax2.plot(bsz.index, m["beta_s"].rolling(MA_L).mean().loc[lo:hi], color=C_GRAY, lw=2, label="β_s 長均線 MA30")
experiments/k1732/k1732_figures.py:54:ax2.axvline(pd.Timestamp("2026-03-27"), color=C_VERM, lw=1, ls=":")
experiments/k1732/k1732_figures.py:55:ax2.annotate("3/27 死亡交叉\n（大跌前 16 週）", xy=(pd.Timestamp("2026-03-27"), m["beta_s"].rolling(MA_L).mean().loc[lo:hi].min()),
experiments/k1732/k1732_figures.py:57:ax2.set_ylabel("偏態敏感度 β_s")
experiments/k1732/k1732_figures.py:61:ax3.plot(bsz.index, m["IS_k"].rolling(MA_L).mean().loc[lo:hi], color=C_GRAY, lw=2, label="IS_k 長均線 MA30")
experiments/k1732/k1732_figures.py:62:ax3.axvline(pd.Timestamp("2026-07-17"), color=C_VERM, lw=1.2, ls="--")
experiments/k1732/k1732_figures.py:63:ax3.annotate("6 月 gap 收斂近零\n（7/10 小幅回彈）", xy=(pd.Timestamp("2026-06-05"), m["IS_k"].rolling(MA_L).mean().loc[lo:hi].mean()),
experiments/k1732/k1732_figures.py:65:ax3.annotate("7/17 當天才交叉", xy=(pd.Timestamp("2026-07-17"), m["IS_k"].rolling(MA_S).mean().loc[lo:hi].iloc[-1]),
experiments/k1732/k1732_figures.py:74:fig.text(0.99, 0.005, "資料：Yahoo Finance ^TWII 週資料｜方法：Lai & Chang CF-VaR 分解（26 週動差、MA20/30）｜VolPred K1732",
experiments/k1732/k1732_figures.py:76:fig.savefig(os.path.join(D, "k1732_fig1_case2026.png"), dpi=160, bbox_inches="tight")
experiments/k1732/k1732_figures.py:80:sig_labels = {"beta_s": "β 敏感度訊號\n(≈波動率趨勢)", "IS_k": "IS_k 峰態份額訊號"}
experiments/k1732/k1732_figures.py:84:for i, key in enumerate(["beta_s", "IS_k"]):
experiments/k1732/k1732_figures.py:86:    p1, p0 = s["assoc_P_onset13_given_active"], s["assoc_P_onset13_given_inactive"]
experiments/k1732/k1732_figures.py:91:axa.set_xticks(x, [sig_labels["beta_s"], sig_labels["IS_k"]], fontsize=10)
experiments/k1732/k1732_figures.py:95:axa.annotate("IS_k：17%→32%\nbootstrap CI 排除 0", xy=(1, 0.385), fontsize=9,
experiments/k1732/k1732_figures.py:97:axa.annotate("β：無差異", xy=(0, 0.30), fontsize=9, ha="center", color="#666")
experiments/k1732/k1732_figures.py:99:for i, key in enumerate(["beta_s", "IS_k"]):
experiments/k1732/k1732_figures.py:106:axb.set_xticks(x, [sig_labels["beta_s"], sig_labels["IS_k"]], fontsize=10)
experiments/k1732/k1732_figures.py:110:axb.annotate("命中≈占比\n= 沒有增量資訊", xy=(0, 0.56), fontsize=9, ha="center", color="#666")
experiments/k1732/k1732_figures.py:111:axb.annotate("71% > 49%", xy=(1 - 0.17, 0.76), fontsize=9, ha="center", color=C_BLUE)
experiments/k1732/k1732_figures.py:115:fig.suptitle("台股 29 年系統性回測（30 次崩跌起點、28 次落在評估期，1997–2026）", fontsize=13, x=0.02, ha="left")
experiments/k1732/k1732_figures.py:127:onsets = pd.to_datetime(res["event_definition"]["onsets_primary"])
experiments/k1732/k1732_figures.py:128:ax.plot(onsets, px.reindex(onsets, method="nearest") * 1.0, "v", color=C_VERM, ms=7,
experiments/k1732/k1732_figures.py:131:ax.set_title("29 年全景：▼=30 次崩跌起點；綠色底=IS_k 警戒期（49% 的時間）", fontsize=12, loc="left", pad=8)
experiments/k1732/k1732_figures.py:134:ax.annotate("警戒期覆蓋 20/28 次可評估起點，但也覆蓋近半的承平時光 —\n它是「體質變差」的 regime 訊號，不是擇日工具",
experiments/k1732/k1732_figures.py:136:fig.text(0.99, -0.02, "資料：Yahoo Finance ^TWII 1997–2026 週資料｜VolPred K1732", ha="right", fontsize=7.5, color="#777")
experiments/k1732/k1732_results.json:8:   "2026-07-17"
experiments/k1732/k1732_results.json:10:  "n_weeks": 1494,
experiments/k1732/k1732_results.json:13:   "moment_window": 26,
experiments/k1732/k1732_results.json:16:    30
experiments/k1732/k1732_results.json:18:   "moment_estimator": "pandas sample skew / excess kurt (bias-corrected)"
experiments/k1732/k1732_results.json:23:  "alt_thr": -0.04,
experiments/k1732/k1732_results.json:25:  "n_onsets_primary": 30,
experiments/k1732/k1732_results.json:26:  "n_onsets_alt": 26,
experiments/k1732/k1732_results.json:27:  "onsets_primary": [
experiments/k1732/k1732_results.json:36:   "2004-03-26",
experiments/k1732/k1732_results.json:54:   "2024-04-19",
experiments/k1732/k1732_results.json:56:   "2026-03-06",
experiments/k1732/k1732_results.json:57:   "2026-07-17"
experiments/k1732/k1732_results.json:61:  "note": "beta_k = -sigma*(1/24)(z^3-3z) 是 sigma 的線性變換 → beta_k 死亡交叉『恆等於』sigma 上升趨勢交叉；beta_s = -sigma*(0.2843+0.0376*skew) 近似同理。此為 mechanical 結果：beta 訊號在本質上是波動率趨勢訊號，偏態僅提供 ~13% 調變。IS_k 才是higher-moment specific 訊號。",
experiments/k1732/k1732_results.json:62:  "corr_beta_k_neg_sigma": 1.0,
experiments/k1732/k1732_results.json:63:  "corr_beta_s_neg_sigma": 0.9715,
experiments/k1732/k1732_results.json:64:  "beta_k_crosses_equal_sigma_crosses": true
experiments/k1732/k1732_results.json:67:  "beta_s": {
experiments/k1732/k1732_results.json:68:   "n_onsets_evaluable": 28,
experiments/k1732/k1732_results.json:71:   "valid_per_paper_rate": 0.4286,
experiments/k1732/k1732_results.json:78:   "n_death_crosses": 28,
experiments/k1732/k1732_results.json:79:   "precision_26w": 0.5357,
experiments/k1732/k1732_results.json:81:   "assoc_P_onset13_given_active": 0.2212,
experiments/k1732/k1732_results.json:82:   "assoc_P_onset13_given_inactive": 0.268,
experiments/k1732/k1732_results.json:92:   "assoc_diff_p_circshift_onesided": 0.73825,
experiments/k1732/k1732_results.json:96:     "onset": "1999-02-05",
experiments/k1732/k1732_results.json:102:     "onset": "1999-07-16",
experiments/k1732/k1732_results.json:108:     "onset": "2000-02-25",
experiments/k1732/k1732_results.json:114:     "onset": "2000-09-01",
experiments/k1732/k1732_results.json:120:     "onset": "2001-12-21",
experiments/k1732/k1732_results.json:126:     "onset": "2003-02-07",
experiments/k1732/k1732_results.json:132:     "onset": "2004-03-26",
experiments/k1732/k1732_results.json:138:     "onset": "2006-06-09",
experiments/k1732/k1732_results.json:144:     "onset": "2007-08-17",
experiments/k1732/k1732_results.json:150:     "onset": "2007-12-14",
experiments/k1732/k1732_results.json:156:     "onset": "2008-06-13",
experiments/k1732/k1732_results.json:162:     "onset": "2009-08-21",
experiments/k1732/k1732_results.json:168:     "onset": "2010-01-22",
experiments/k1732/k1732_results.json:174:     "onset": "2011-02-11",
experiments/k1732/k1732_results.json:180:     "onset": "2011-08-05",
experiments/k1732/k1732_results.json:186:     "onset": "2014-10-17",
experiments/k1732/k1732_results.json:192:     "onset": "2015-08-21",
experiments/k1732/k1732_results.json:198:     "onset": "2016-01-08",
experiments/k1732/k1732_results.json:204:     "onset": "2018-02-09",
experiments/k1732/k1732_results.json:210:     "onset": "2020-01-31",
experiments/k1732/k1732_results.json:216:     "onset": "2020-09-25",
experiments/k1732/k1732_results.json:222:     "onset": "2021-01-29",
experiments/k1732/k1732_results.json:228:     "onset": "2021-05-14",
experiments/k1732/k1732_results.json:234:     "onset": "2022-06-17",
experiments/k1732/k1732_results.json:240:     "onset": "2024-04-19",
experiments/k1732/k1732_results.json:246:     "onset": "2025-04-11",
experiments/k1732/k1732_results.json:252:     "onset": "2026-03-06",
experiments/k1732/k1732_results.json:258:     "onset": "2026-07-17",
experiments/k1732/k1732_results.json:264:   "alt_thr_hit_rate": 0.4167,
experiments/k1732/k1732_results.json:265:   "alt_thr_n_onsets": 24
experiments/k1732/k1732_results.json:267:  "beta_k": {
experiments/k1732/k1732_results.json:268:   "n_onsets_evaluable": 28,
experiments/k1732/k1732_results.json:278:   "n_death_crosses": 26,
experiments/k1732/k1732_results.json:279:   "precision_26w": 0.5385,
experiments/k1732/k1732_results.json:281:   "assoc_P_onset13_given_active": 0.2219,
experiments/k1732/k1732_results.json:282:   "assoc_P_onset13_given_inactive": 0.2674,
experiments/k1732/k1732_results.json:286:    0.0624
experiments/k1732/k1732_results.json:292:   "assoc_diff_p_circshift_onesided": 0.71386,
experiments/k1732/k1732_results.json:296:     "onset": "1999-02-05",
experiments/k1732/k1732_results.json:302:     "onset": "1999-07-16",
experiments/k1732/k1732_results.json:308:     "onset": "2000-02-25",
experiments/k1732/k1732_results.json:314:     "onset": "2000-09-01",
experiments/k1732/k1732_results.json:320:     "onset": "2001-12-21",
experiments/k1732/k1732_results.json:326:     "onset": "2003-02-07",
experiments/k1732/k1732_results.json:332:     "onset": "2004-03-26",
experiments/k1732/k1732_results.json:338:     "onset": "2006-06-09",
experiments/k1732/k1732_results.json:344:     "onset": "2007-08-17",
experiments/k1732/k1732_results.json:350:     "onset": "2007-12-14",
experiments/k1732/k1732_results.json:356:     "onset": "2008-06-13",
experiments/k1732/k1732_results.json:362:     "onset": "2009-08-21",
experiments/k1732/k1732_results.json:368:     "onset": "2010-01-22",
experiments/k1732/k1732_results.json:374:     "onset": "2011-02-11",
experiments/k1732/k1732_results.json:380:     "onset": "2011-08-05",
experiments/k1732/k1732_results.json:386:     "onset": "2014-10-17",
experiments/k1732/k1732_results.json:392:     "onset": "2015-08-21",
experiments/k1732/k1732_results.json:398:     "onset": "2016-01-08",
experiments/k1732/k1732_results.json:404:     "onset": "2018-02-09",
experiments/k1732/k1732_results.json:410:     "onset": "2020-01-31",
experiments/k1732/k1732_results.json:416:     "onset": "2020-09-25",
experiments/k1732/k1732_results.json:418:     "lead_weeks": 26,
experiments/k1732/k1732_results.json:422:     "onset": "2021-01-29",
experiments/k1732/k1732_results.json:428:     "onset": "2021-05-14",
experiments/k1732/k1732_results.json:434:     "onset": "2022-06-17",
experiments/k1732/k1732_results.json:440:     "onset": "2024-04-19",
experiments/k1732/k1732_results.json:446:     "onset": "2025-04-11",
experiments/k1732/k1732_results.json:452:     "onset": "2026-03-06",
experiments/k1732/k1732_results.json:458:     "onset": "2026-07-17",
experiments/k1732/k1732_results.json:464:   "alt_thr_hit_rate": 0.375,
experiments/k1732/k1732_results.json:465:   "alt_thr_n_onsets": 24
experiments/k1732/k1732_results.json:468:   "n_onsets_evaluable": 28,
experiments/k1732/k1732_results.json:469:   "hit_rate_active_at_t_minus_1": 0.7143,
experiments/k1732/k1732_results.json:471:   "valid_per_paper_rate": 0.6071,
experiments/k1732/k1732_results.json:478:   "n_death_crosses": 71,
experiments/k1732/k1732_results.json:479:   "precision_26w": 0.4507,
experiments/k1732/k1732_results.json:481:   "assoc_P_onset13_given_active": 0.3229,
experiments/k1732/k1732_results.json:482:   "assoc_P_onset13_given_inactive": 0.1722,
experiments/k1732/k1732_results.json:490:    0.2852
experiments/k1732/k1732_results.json:492:   "assoc_diff_p_circshift_onesided": 0.0138,
experiments/k1732/k1732_results.json:496:     "onset": "1999-02-05",
experiments/k1732/k1732_results.json:502:     "onset": "1999-07-16",
experiments/k1732/k1732_results.json:508:     "onset": "2000-02-25",
experiments/k1732/k1732_results.json:514:     "onset": "2000-09-01",
experiments/k1732/k1732_results.json:520:     "onset": "2001-12-21",
experiments/k1732/k1732_results.json:526:     "onset": "2003-02-07",
experiments/k1732/k1732_results.json:532:     "onset": "2004-03-26",
experiments/k1732/k1732_results.json:538:     "onset": "2006-06-09",
experiments/k1732/k1732_results.json:544:     "onset": "2007-08-17",
experiments/k1732/k1732_results.json:550:     "onset": "2007-12-14",
experiments/k1732/k1732_results.json:556:     "onset": "2008-06-13",
experiments/k1732/k1732_results.json:562:     "onset": "2009-08-21",
experiments/k1732/k1732_results.json:568:     "onset": "2010-01-22",
experiments/k1732/k1732_results.json:574:     "onset": "2011-02-11",
experiments/k1732/k1732_results.json:580:     "onset": "2011-08-05",
experiments/k1732/k1732_results.json:586:     "onset": "2014-10-17",
experiments/k1732/k1732_results.json:592:     "onset": "2015-08-21",
experiments/k1732/k1732_results.json:598:     "onset": "2016-01-08",
experiments/k1732/k1732_results.json:604:     "onset": "2018-02-09",
experiments/k1732/k1732_results.json:610:     "onset": "2020-01-31",
experiments/k1732/k1732_results.json:616:     "onset": "2020-09-25",
experiments/k1732/k1732_results.json:622:     "onset": "2021-01-29",
experiments/k1732/k1732_results.json:628:     "onset": "2021-05-14",
experiments/k1732/k1732_results.json:634:     "onset": "2022-06-17",
experiments/k1732/k1732_results.json:636:     "lead_weeks": 26,
experiments/k1732/k1732_results.json:640:     "onset": "2024-04-19",
experiments/k1732/k1732_results.json:646:     "onset": "2025-04-11",
experiments/k1732/k1732_results.json:648:     "lead_weeks": 24,
experiments/k1732/k1732_results.json:652:     "onset": "2026-03-06",
experiments/k1732/k1732_results.json:658:     "onset": "2026-07-17",
experiments/k1732/k1732_results.json:664:   "alt_thr_hit_rate": 0.75,
experiments/k1732/k1732_results.json:665:   "alt_thr_n_onsets": 24
experiments/k1732/k1732_results.json:668:   "n_onsets_evaluable": 28,
experiments/k1732/k1732_results.json:678:   "n_death_crosses": 26,
experiments/k1732/k1732_results.json:679:   "precision_26w": 0.5385,
experiments/k1732/k1732_results.json:681:   "assoc_P_onset13_given_active": 0.2219,
experiments/k1732/k1732_results.json:682:   "assoc_P_onset13_given_inactive": 0.2674,
experiments/k1732/k1732_results.json:692:   "assoc_diff_p_circshift_onesided": 0.73445,
experiments/k1732/k1732_results.json:696:     "onset": "1999-02-05",
experiments/k1732/k1732_results.json:702:     "onset": "1999-07-16",
experiments/k1732/k1732_results.json:708:     "onset": "2000-02-25",
experiments/k1732/k1732_results.json:714:     "onset": "2000-09-01",
experiments/k1732/k1732_results.json:720:     "onset": "2001-12-21",
experiments/k1732/k1732_results.json:726:     "onset": "2003-02-07",
experiments/k1732/k1732_results.json:732:     "onset": "2004-03-26",
experiments/k1732/k1732_results.json:738:     "onset": "2006-06-09",
experiments/k1732/k1732_results.json:744:     "onset": "2007-08-17",
experiments/k1732/k1732_results.json:750:     "onset": "2007-12-14",
experiments/k1732/k1732_results.json:756:     "onset": "2008-06-13",
experiments/k1732/k1732_results.json:762:     "onset": "2009-08-21",
experiments/k1732/k1732_results.json:768:     "onset": "2010-01-22",
experiments/k1732/k1732_results.json:774:     "onset": "2011-02-11",
experiments/k1732/k1732_results.json:780:     "onset": "2011-08-05",
experiments/k1732/k1732_results.json:786:     "onset": "2014-10-17",
experiments/k1732/k1732_results.json:792:     "onset": "2015-08-21",
experiments/k1732/k1732_results.json:798:     "onset": "2016-01-08",
experiments/k1732/k1732_results.json:804:     "onset": "2018-02-09",
experiments/k1732/k1732_results.json:810:     "onset": "2020-01-31",
experiments/k1732/k1732_results.json:816:     "onset": "2020-09-25",
experiments/k1732/k1732_results.json:818:     "lead_weeks": 26,
experiments/k1732/k1732_results.json:822:     "onset": "2021-01-29",
experiments/k1732/k1732_results.json:828:     "onset": "2021-05-14",
experiments/k1732/k1732_results.json:834:     "onset": "2022-06-17",
experiments/k1732/k1732_results.json:840:     "onset": "2024-04-19",
experiments/k1732/k1732_results.json:846:     "onset": "2025-04-11",
experiments/k1732/k1732_results.json:852:     "onset": "2026-03-06",
experiments/k1732/k1732_results.json:858:     "onset": "2026-07-17",
experiments/k1732/k1732_results.json:864:   "alt_thr_hit_rate": 0.375,
experiments/k1732/k1732_results.json:865:   "alt_thr_n_onsets": 24
experiments/k1732/k1732_results.json:868: "case_2026_07_17": {
experiments/k1732/k1732_results.json:869:  "beta_s": {
experiments/k1732/k1732_results.json:872:   "last_death_cross": "2026-03-27"
experiments/k1732/k1732_results.json:874:  "beta_k": {
experiments/k1732/k1732_results.json:877:   "last_death_cross": "2026-04-03"
experiments/k1732/k1732_results.json:882:   "last_death_cross": "2026-07-17"
experiments/k1732/k1732_results.json:887:   "last_death_cross": "2026-04-03"
experiments/k1732/k1732_results.json:891:   "2026-05-29": 0.008348,
experiments/k1732/k1732_results.json:892:   "2026-06-05": 0.007624,
experiments/k1732/k1732_results.json:893:   "2026-06-12": 0.007493,
experiments/k1732/k1732_results.json:894:   "2026-06-19": 0.005564,
experiments/k1732/k1732_results.json:895:   "2026-06-26": 0.002411,
experiments/k1732/k1732_results.json:896:   "2026-07-03": 0.000963,
experiments/k1732/k1732_results.json:897:   "2026-07-10": 0.002346,
experiments/k1732/k1732_results.json:898:   "2026-07-17": -0.004197
experiments/k1732/k1732_results.json:902: "bootstrap": {
experiments/k1732/k1732_results.json:904:  "block": 26,
experiments/k1732/k1732_results.json:905:  "method": "circular block"
experiments/k1732/k1732_results.json:907: "estimator_sensitivity_ISk": {
experiments/k1732/k1732_results.json:908:  "note": "population (bias=True) skew/exkurt 重算 IS_k 訊號 vs 基準 pandas bias-corrected",
experiments/k1732/k1732_results.json:909:  "n_death_crosses_pop": 71,
experiments/k1732/k1732_results.json:910:  "n_death_crosses_base": 71,
experiments/k1732/k1732_results.json:913:  "n_weeks_compared": 1494
experiments/k1732/k1732.py:1:"""K1732: TAIEX Cornish-Fisher VaR 分解死亡交叉預警 — 系統性歷史回測（1997-2026）
experiments/k1732/k1732.py:3:動機：Lai & Chang (2409-662, accepted) 提出 CF-VaR 分解雙預警架構（β 敏感度 +
experiments/k1732/k1732.py:4:IS_k 峰態影響份額的 MA20/MA30 死亡交叉），以 19 指數 × 3 次危機事件研究驗證。
experiments/k1732/k1732.py:5:2026-07-17 台股單日 -6.47%，本 K 把同一套訊號放到 TAIEX 全歷史（1997-2026，
experiments/k1732/k1732.py:9:  (3) β 訊號 vs 純波動率趨勢訊號的機械等價性檢查（mechanical vs empirical）
experiments/k1732/k1732.py:10:  (4) 2026-07-17 事件的訊號時序（實時案例）
experiments/k1732/k1732.py:14:    episode onset = 前 13 週內無事件週的第一個事件週
experiments/k1732/k1732.py:15:  - 訊號狀態一律取 onset 前一週（t-1，明確 shift，杜絕 lookahead）
experiments/k1732/k1732.py:16:  - 論文有效判準：死亡交叉發生於 onset 前 >= 3 週且中間無黃金交叉
experiments/k1732/k1732.py:17:  - precision 視窗：死亡交叉後 26 週內出現 onset 算成功
experiments/k1732/k1732.py:18:  - 關聯檢定：週頻 2x2（signal active_t vs onset in t+1..t+13），
experiments/k1732/k1732.py:19:    circular block bootstrap（block=26, B=2000, seed=42）
experiments/k1732/k1732.py:20:論文規格複製：週報酬（W-FRI）、26 週滾動動差、alpha=5%、MA20/MA30。
experiments/k1732/k1732.py:36:WINDOW = 26          # 論文 26 週滾動動差
experiments/k1732/k1732.py:37:MA_S, MA_L = 20, 30  # 論文 MA20/MA30
experiments/k1732/k1732.py:40:EPISODE_GAP = 13     # 事件週前 13 週無事件 → 新 episode onset
experiments/k1732/k1732.py:41:PRECISION_H = 26     # 死亡交叉後 26 週內有 onset 算 precision 成功
experiments/k1732/k1732.py:44:BLOCK = 26
experiments/k1732/k1732.py:54:    assert close.index[-1] >= pd.Timestamp("2026-07-17"), (
experiments/k1732/k1732.py:55:        f"yfinance 資料落後（最後日 {close.index[-1].date()}）— 見 error_log 2026-07-15 stale 教訓"
experiments/k1732/k1732.py:58:    wret = np.log(wclose / wclose.shift(1)).dropna()
experiments/k1732/k1732.py:63:    """論文 eq(4)(11)(12)(13)(14) 的逐週指標。pandas 樣本偏態 / 超額峰態（bias-corrected）。"""
experiments/k1732/k1732.py:69:            + (1 / 24) * (Z ** 3 - 3 * Z) * exk
experiments/k1732/k1732.py:71:    beta_s = -sigma * ((1 / 6) * (Z ** 2 - 1) - (1 / 18) * (2 * Z ** 3 - 5 * Z) * skew)
experiments/k1732/k1732.py:72:    beta_k = -sigma * ((1 / 24) * (Z ** 3 - 3 * Z))
experiments/k1732/k1732.py:73:    beta_sig = -z_cf
experiments/k1732/k1732.py:74:    dvar_s = (beta_s * skew.diff()).abs()
experiments/k1732/k1732.py:75:    dvar_k = (beta_k * exk.diff()).abs()
experiments/k1732/k1732.py:76:    dvar_sig = (beta_sig * sigma.diff()).abs()
experiments/k1732/k1732.py:80:        "beta_s": beta_s, "beta_k": beta_k, "beta_sig": beta_sig,
experiments/k1732/k1732.py:85:def cross_state(series: pd.Series) -> pd.DataFrame:
experiments/k1732/k1732.py:86:    """MA20/MA30 死亡交叉狀態機。active=True 表 MA20<MA30（警戒中）。"""
experiments/k1732/k1732.py:93:    death = (gap.lt(0) & gap.shift(1).ge(0)).astype(bool)
experiments/k1732/k1732.py:94:    golden = (gap.ge(0) & gap.shift(1).lt(0)).astype(bool)
experiments/k1732/k1732.py:99:    """episode 邏輯：與「上一個事件週」（不限 onset）間隔 > EPISODE_GAP 週才算新 onset。"""
experiments/k1732/k1732.py:101:    onsets, last_crash = [], None
experiments/k1732/k1732.py:104:            onsets.append(d)
experiments/k1732/k1732.py:106:    return onsets
experiments/k1732/k1732.py:116:        if bool(state["golden"].iloc[j]) and j != pos:
experiments/k1732/k1732.py:118:        if bool(state["death"].iloc[j]):
experiments/k1732/k1732.py:123:def evaluate_signal(state: pd.DataFrame, onsets: list[pd.Timestamp], idx: pd.DatetimeIndex,
experiments/k1732/k1732.py:124:                    rng: np.random.Generator) -> dict:
experiments/k1732/k1732.py:126:    # --- per-onset ex-ante 評估（t-1 狀態；明確 shift）---
experiments/k1732/k1732.py:127:    active_lag = state["active"].shift(1)  # lookahead guard: 只用 onset 前一週資訊
experiments/k1732/k1732.py:129:    for t in onsets:
experiments/k1732/k1732.py:130:        if t not in active_lag.index or pd.isna(state.loc[:t, "gap"].iloc[-1]):
experiments/k1732/k1732.py:136:        if pd.isna(state["gap"].loc[t_prev]):  # 訊號 warmup 未完成的 onset 不列入評估
experiments/k1732/k1732.py:141:            "onset": str(t.date()),
experiments/k1732/k1732.py:143:            "lead_weeks": None if lead is None else int(lead + 1),  # +1: cross 至 onset 的週數
experiments/k1732/k1732.py:152:    onset_idx = pd.DatetimeIndex(onsets)
experiments/k1732/k1732.py:154:        bool(((onset_idx > c) & (onset_idx <= c + pd.Timedelta(weeks=PRECISION_H))).any())
experiments/k1732/k1732.py:157:    # --- 週頻關聯 + circular block bootstrap ---
experiments/k1732/k1732.py:158:    onset_flag = pd.Series(False, index=idx)
experiments/k1732/k1732.py:159:    onset_flag.loc[onset_flag.index.isin(onset_idx)] = True
experiments/k1732/k1732.py:160:    fwd = (onset_flag[::-1].rolling(ASSOC_H).max()[::-1].shift(-1)).astype(float)  # onset in t+1..t+13
experiments/k1732/k1732.py:181:    # 正式檢定（Codex v1 finding 2）：circular-shift randomization null。
experiments/k1732/k1732.py:194:        "n_onsets_evaluable": n_ev,
experiments/k1732/k1732.py:202:        "precision_26w": round(prec_success / len(deaths), 4) if len(deaths) else None,
experiments/k1732/k1732.py:204:        "assoc_P_onset13_given_active": round(float(p1_obs), 4),
experiments/k1732/k1732.py:205:        "assoc_P_onset13_given_inactive": round(float(p0_obs), 4),
experiments/k1732/k1732.py:209:        "assoc_diff_p_circshift_onesided": round(p_perm, 5),
experiments/k1732/k1732.py:216:    rng = np.random.default_rng(SEED)
experiments/k1732/k1732.py:221:    states = {name: cross_state(m[name]) for name in ["beta_s", "beta_k", "IS_k"]}
experiments/k1732/k1732.py:222:    # 機械等價 benchmark：純波動率趨勢（MA20(sigma) 上穿 MA30(sigma) = 警戒）
experiments/k1732/k1732.py:223:    sig_up = cross_state(-m["sigma"])  # 取負號 → death cross of -sigma == sigma 上升趨勢
experiments/k1732/k1732.py:226:    onsets = episodes(wret, CRASH_THR)
experiments/k1732/k1732.py:227:    onsets_alt = episodes(wret, CRASH_THR_ALT)
experiments/k1732/k1732.py:237:                     "moment_estimator": "pandas sample skew / excess kurt (bias-corrected)"},
experiments/k1732/k1732.py:240:            "primary_thr_weekly_log_ret": CRASH_THR, "alt_thr": CRASH_THR_ALT,
experiments/k1732/k1732.py:242:            "n_onsets_primary": len(onsets), "n_onsets_alt": len(onsets_alt),
experiments/k1732/k1732.py:243:            "onsets_primary": [str(d.date()) for d in onsets],
experiments/k1732/k1732.py:246:            "note": ("beta_k = -sigma*(1/24)(z^3-3z) 是 sigma 的線性變換 → beta_k 死亡交叉"
experiments/k1732/k1732.py:247:                     "『恆等於』sigma 上升趨勢交叉；beta_s = -sigma*(0.2843+0.0376*skew) 近似同理。"
experiments/k1732/k1732.py:248:                     "此為 mechanical 結果：beta 訊號在本質上是波動率趨勢訊號，"
experiments/k1732/k1732.py:250:            "corr_beta_k_neg_sigma": round(float(m["beta_k"].corr(-m["sigma"])), 6),
experiments/k1732/k1732.py:251:            "corr_beta_s_neg_sigma": round(float(m["beta_s"].corr(-m["sigma"])), 4),
experiments/k1732/k1732.py:252:            "beta_k_crosses_equal_sigma_crosses": bool(
experiments/k1732/k1732.py:253:                (states["beta_k"]["death"].fillna(False) == sig_up["death"].fillna(False)).all()),
experiments/k1732/k1732.py:256:        "case_2026_07_17": {},
experiments/k1732/k1732.py:257:        "seed": SEED, "bootstrap": {"B": BOOT_B, "block": BLOCK, "method": "circular block"},
experiments/k1732/k1732.py:261:        results["signals"][name] = evaluate_signal(st, onsets, idx, rng)
experiments/k1732/k1732.py:262:        # robustness: alt threshold（只記 hit rate，全表太長）
experiments/k1732/k1732.py:263:        alt = evaluate_signal(st, onsets_alt, idx, np.random.default_rng(SEED + 1))
experiments/k1732/k1732.py:264:        results["signals"][name]["alt_thr_hit_rate"] = alt["hit_rate_active_at_t_minus_1"]
experiments/k1732/k1732.py:265:        results["signals"][name]["alt_thr_n_onsets"] = alt["n_onsets_evaluable"]
experiments/k1732/k1732.py:267:    # 2026-07-17 實時案例
experiments/k1732/k1732.py:268:    t_case = pd.Timestamp("2026-07-17")
experiments/k1732/k1732.py:273:        results["case_2026_07_17"][name] = {
experiments/k1732/k1732.py:274:            "active_at_t_minus_1": bool(st["active"].shift(1).loc[t_case]),
experiments/k1732/k1732.py:278:    results["case_2026_07_17"]["week_ret"] = round(float(wret.loc[t_case]), 4)
experiments/k1732/k1732.py:280:    results["case_2026_07_17"]["isk_gap_last8"] = {str(d.date()): round(float(v), 6)
experiments/k1732/k1732.py:283:    # Estimator sensitivity（Codex v1 finding 7）：population（bias=True）動差 vs pandas bias-corrected
experiments/k1732/k1732.py:285:    skew_p = wret.rolling(WINDOW).apply(lambda x: _sk(x, bias=True), raw=True)
experiments/k1732/k1732.py:286:    exk_p = wret.rolling(WINDOW).apply(lambda x: _ku(x, bias=True, fisher=True), raw=True)
experiments/k1732/k1732.py:288:    beta_s_p = -sigma_ * ((1 / 6) * (Z ** 2 - 1) - (1 / 18) * (2 * Z ** 3 - 5 * Z) * skew_p)
experiments/k1732/k1732.py:289:    beta_k_p = -sigma_ * ((1 / 24) * (Z ** 3 - 3 * Z))
experiments/k1732/k1732.py:290:    z_cf_p = (Z + (1 / 6) * (Z ** 2 - 1) * skew_p + (1 / 24) * (Z ** 3 - 3 * Z) * exk_p
experiments/k1732/k1732.py:292:    dv_s = (beta_s_p * skew_p.diff()).abs()
experiments/k1732/k1732.py:293:    dv_k = (beta_k_p * exk_p.diff()).abs()
experiments/k1732/k1732.py:296:    st_p, st_b = cross_state(isk_p), states["IS_k"]
experiments/k1732/k1732.py:300:    results["estimator_sensitivity_ISk"] = {
experiments/k1732/k1732.py:301:        "note": "population (bias=True) skew/exkurt 重算 IS_k 訊號 vs 基準 pandas bias-corrected",
experiments/k1732/k1732.py:318:    print(json.dumps({k: v for k, v in results.items() if k not in ("signals", "case_2026_07_17")},
experiments/k1732/k1732.py:324:    print("\n=== case 2026-07-17 ===\n", json.dumps(results["case_2026_07_17"], ensure_ascii=False, indent=1))

exec
/bin/zsh -lc 'rg -n "CRITICAL|MAJOR|MINOR|VERDICT|blocking|Finding|finding" experiments/k1732/codex_review_v1.md | tail -40' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
30:- 逐點 findings（嚴重度 CRITICAL/MAJOR/MINOR + 檔案:行號 + 說明）
31:- 最後一行單獨輸出 verdict，格式：`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 需列 blocking defects）
148:  2. Section 7 Dashboard CRITICAL — 立即 triage
259:5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。
262:- `paper_review_vt_trend_v7_post_v6_fixes`（P2，Codex）：確認 body narrative HIGH 全解 + 修 v6 CRITICAL（K1458 實驗 doc 的 decomposition identity `VIX_timing=PureVT_excess` 寫錯，應加法）。
263:- `platform_ops_dreaming_persistent_alert_detector`（P2）：dreaming 加 detector 讀 alert_dedup.json，同 alert_key 連 N 天 fire → 自動升級 root-cause finding，杜絕「warn 存在很久才被 boss 抓到」（系統性 gap）。
430:- 文章：Treasury 拍賣冷清不等於 MOVE 噴出（daily_article K1506 null finding general-audience，11:19 published draft）
490:如果結果可以從模型定義直接推導，它是 **mechanical result**，不是 empirical finding：
1308:初步已發現宣稱面與結果檔有明確口徑錯置：結果檔是原始 onset 30/26 次、暖機後可評估 28/24 次，但 README 把 28/24 寫成事件總數。接下來我正在獨立驗證死亡交叉首筆、forward label 與 bootstrap 推論，這三處會決定是否只是文字修正或屬 blocking defect。
1379:- 逐點 findings（嚴重度 CRITICAL/MAJOR/MINOR + 檔案:行號 + 說明）
1380:- 最後一行單獨輸出 verdict，格式：`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 需列 blocking defects）
1497:  2. Section 7 Dashboard CRITICAL — 立即 triage
2401:## Findings
2403:1. **MAJOR — [k1732.py:90](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:90)：暖機完成的第一個負 gap 被誤判為死亡交叉。**  
2408:2. **MAJOR — [k1732.py:171](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:171)、[k1732.py:181](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:181)、[README.md:54](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:54)：`p=0.0025` 不是明確在虛無假設下產生的 bootstrap p 值。**  
2412:3. **MAJOR — [README.md:54](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:54)：「唯一帶增量資訊」超過實際檢定範圍。**  
2421:4. **MAJOR — [README.md:10](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:10)、[README.md:23](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:23)、[k1732_results.json:10](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:10)、[k1732_results.json:25](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:25)：樣本數與 onset 數混用。**  
2425:5. **MAJOR — [README.md:48](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:48)、[k1732_figures.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:63)：2026 案例的「交叉前六週單調收斂」不成立。**  
2430:6. **MINOR — [k1732.py:159](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:159)、[k1732.py:161](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:161)：forward rolling 對齊正確，但多刪了一個有效觀測。**  
2433:7. **MINOR — [k1732.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:63)、[README.md:20](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:20)：動差估計式差異有揭露，但「差異微小」缺正式敏感度證據。**  
2436:8. **MINOR — [k1732_results.json:61](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:61)、[README.md:31](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:31)：β_s「偏態僅約 13% 調變」表述不精確。**  
2450:VERDICT: FAIL
2455:## Findings
2457:1. **MAJOR — [k1732.py:90](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:90)：暖機完成的第一個負 gap 被誤判為死亡交叉。**  
2462:2. **MAJOR — [k1732.py:171](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:171)、[k1732.py:181](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:181)、[README.md:54](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:54)：`p=0.0025` 不是明確在虛無假設下產生的 bootstrap p 值。**  
2466:3. **MAJOR — [README.md:54](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:54)：「唯一帶增量資訊」超過實際檢定範圍。**  
2475:4. **MAJOR — [README.md:10](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:10)、[README.md:23](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:23)、[k1732_results.json:10](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:10)、[k1732_results.json:25](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:25)：樣本數與 onset 數混用。**  
2479:5. **MAJOR — [README.md:48](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:48)、[k1732_figures.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:63)：2026 案例的「交叉前六週單調收斂」不成立。**  
2484:6. **MINOR — [k1732.py:159](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:159)、[k1732.py:161](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:161)：forward rolling 對齊正確，但多刪了一個有效觀測。**  
2487:7. **MINOR — [k1732.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:63)、[README.md:20](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:20)：動差估計式差異有揭露，但「差異微小」缺正式敏感度證據。**  
2490:8. **MINOR — [k1732_results.json:61](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:61)、[README.md:31](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:31)：β_s「偏態僅約 13% 調變」表述不精確。**  
2504:VERDICT: FAIL

exec
/bin/zsh -lc "sed -n '2401,2451p' experiments/k1732/codex_review_v1.md
nl -ba experiments/k1732/k1732.py | sed -n '1,360p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
## Findings

1. **MAJOR — [k1732.py:90](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:90)：暖機完成的第一個負 gap 被誤判為死亡交叉。**  
   `active` 在 warmup 期間被強制設為 `False`，因此第一個有效 gap 若為負，`death = active & ~prev` 會把「未知前態 → 負值」當成真正的正轉負交叉。IS_k 在 1998-08-07 正好發生此錯誤：目前 72 次死亡交叉中有 1 次是假的。嚴格定義應直接比較 gap：
   `death = gap.lt(0) & gap.shift(1).ge(0)`。  
   修正後 IS_k 為 71 次，precision 約由 33/72=45.83% 改成 32/71=45.07%。active、命中率及主要 association 不受影響，但 README 的交叉次數與 precision 必須重算。

2. **MAJOR — [k1732.py:171](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:171)、[k1732.py:181](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:181)、[README.md:54](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:54)：`p=0.0025` 不是明確在虛無假設下產生的 bootstrap p 值。**  
   block 的抽法本身正確：允許重疊、用 modulo 處理 circular boundary，並成對 resample `(active, fwd)`。percentile CI 也可作近似信賴區間。  
   但 `mean(boot <= 0)` 是 empirical-bootstrap 分布落在零以下的比例；程式沒有施加或中心化 \(H_0:\Delta=0\)，也沒有 studentization/block permutation，因此不應直接當成可做 Bonferroni 的正式檢定 p 值。另 0.0025 在 B=2000 下只有 5 次抽樣落尾端，沒有 `(r+1)/(B+1)` 修正，Monte Carlo 誤差對「校正後仍低於 0.01」不可忽略。中央顯著性宣稱須用 null-centered/studentized block bootstrap 或適當 block randomization，並提高 B 後重跑。

3. **MAJOR — [README.md:54](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:54)：「唯一帶增量資訊」超過實際檢定範圍。**  
   程式只分別計算三個訊號的單變量條件機率差。它沒有：

   - 聯合模型中控制 β/σ 訊號；
   - 直接檢定 IS_k 效果是否顯著大於 β_s、β_k；
   - 與 base-rate-only 模型做正式增量預測比較。

   「IS_k 顯著而 β 不顯著」不等於「兩者效果差異顯著」。目前最多能寫成「三個單變量檢驗中，只有 IS_k 的估計差為正且 percentile CI 排除零」。同段「支持內生性金融風險特定優勢」也未被本實驗的事件分類設計識別。

4. **MAJOR — [README.md:10](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:10)、[README.md:23](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:23)、[k1732_results.json:10](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:10)、[k1732_results.json:25](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:25)：樣本數與 onset 數混用。**  
   JSON 是 1,494 週、primary onset 30 次、alternative onset 26 次；README 卻寫 1,514 週、28 次及 24 次。28/24 是暖機後「可評估」數，不是事件定義產生的 onset 總數。  
   更嚴重的是 [k1732_figures.py:127](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:127) 實際畫入 JSON 的全部 30 個 primary onsets，但 [k1732_figures.py:131](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:131) 標題宣稱只有 28 個，圖與標籤不一致。

5. **MAJOR — [README.md:48](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:48)、[k1732_figures.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:63)：2026 案例的「交叉前六週單調收斂」不成立。**  
   由保存的 IS_k 序列重算 MA20−MA30，2026-06-05 至 07-17 的 gap 約為：
   `0.007624, 0.007493, 0.005564, 0.002411, 0.000963, 0.002346, -0.004197`。  
   07-10 在交叉前一週明顯反彈至 0.002346，並非持續單調收斂；README 所寫「+0.0083 單調收斂至 +0.0010」選擇性停在 07-03，漏掉真正的 t−1。這直接影響案例敘事，圖表註解亦須更正。

6. **MINOR — [k1732.py:159](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:159)、[k1732.py:161](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:161)：forward rolling 對齊正確，但多刪了一個有效觀測。**  
   獨立逐列比對確認 reverse-rolling 加 `shift(-1)` 精確對應 `t+1…t+13`，沒有 off-by-one。可是 `dropna()` 已排除尾端沒有完整 13 週視窗的列，隨後的 `df.iloc[:-1]` 又無理由刪掉 2026-04-17；該列的 13 週視窗恰好包含 2026-07-17 onset。影響很小，但應移除。

7. **MINOR — [k1732.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:63)、[README.md:20](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:20)：動差估計式差異有揭露，但「差異微小」缺正式敏感度證據。**  
   公式符號本身完全忠於題示論文，`exk` 也正確對應 \(k-3\)。README 確實揭露 pandas 使用 bias-corrected skew/excess kurt。獨立用未校正中心動差重算後，IS_k active 僅差 5 週、總交叉數仍為 72，但有 6 個死亡交叉日期不同；因此差異整體不大，卻仍應將這項 estimator sensitivity 寫入 results，而非只用文字判定。

8. **MINOR — [k1732_results.json:61](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:61)、[README.md:31](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:31)：β_s「偏態僅約 13% 調變」表述不精確。**  
   13.2% 是每一單位 skew 相對常數項的係數比例，不是樣本內調變上限；本樣本實際相對調變約介於 −36.9% 至 +23.9%。β_s 與 −σ 的相關係數 0.9715 支持「高度近似」，但不支持「僅 13%」作為全樣本上限。

## 已核對無缺陷部分

- onset 評估確實使用 `active.shift(1)`；lead time 的 `+1` 對齊正確，沒有使用事件週訊號。
- `weeks_since_last_death` 在正常有效區間能正確因 intervening golden cross 回傳 `None`。
- episode 邏輯確實依「與上一個崩跌週相隔 >13 個日曆週」判定，與 README 定義一致。
- Cornish-Fisher、β_s、β_k、IS 分解的符號及 excess-kurtosis 代入均正確。
- β_k 是 −σ 的正常數倍；相關係數 1、死亡交叉逐列完全相同，[k1732.py:240](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:240) 的 mechanical-equivalence 驗證成立。
- README 結果表中除 IS_k 死亡交叉/precision 初始化問題外，其餘表列數字均可在 results JSON 找到。

Blocking defects：修正 cross-state 初始化並重跑；以正式 null bootstrap 重做 p 值與多重檢定；移除或直接檢定「唯一增量資訊」宣稱；同步更正 onset/週數及 2026 單調收斂的錯誤文字與圖表。

VERDICT: FAIL
tokens used
     1	"""K1732: TAIEX Cornish-Fisher VaR 分解死亡交叉預警 — 系統性歷史回測（1997-2026）
     2	
     3	動機：Lai & Chang (2409-662, accepted) 提出 CF-VaR 分解雙預警架構（β 敏感度 +
     4	IS_k 峰態影響份額的 MA20/MA30 死亡交叉），以 19 指數 × 3 次危機事件研究驗證。
     5	2026-07-17 台股單日 -6.47%，本 K 把同一套訊號放到 TAIEX 全歷史（1997-2026，
     6	約 1,500 週）做「事件定義預先註冊」的系統性回測，回答：
     7	  (1) 訊號對客觀定義的崩跌事件的 ex-ante 命中率與領先期分佈
     8	  (2) 誤報成本（precision、警戒時間占比）
     9	  (3) β 訊號 vs 純波動率趨勢訊號的機械等價性檢查（mechanical vs empirical）
    10	  (4) 2026-07-17 事件的訊號時序（實時案例）
    11	
    12	預先註冊的設計決策（跑之前寫死，不看結果調整）：
    13	  - 事件 = 週 log 報酬 <= -5%（primary）/ -4%(robustness)；
    14	    episode onset = 前 13 週內無事件週的第一個事件週
    15	  - 訊號狀態一律取 onset 前一週（t-1，明確 shift，杜絕 lookahead）
    16	  - 論文有效判準：死亡交叉發生於 onset 前 >= 3 週且中間無黃金交叉
    17	  - precision 視窗：死亡交叉後 26 週內出現 onset 算成功
    18	  - 關聯檢定：週頻 2x2（signal active_t vs onset in t+1..t+13），
    19	    circular block bootstrap（block=26, B=2000, seed=42）
    20	論文規格複製：週報酬（W-FRI）、26 週滾動動差、alpha=5%、MA20/MA30。
    21	資料：Yahoo Finance ^TWII（加權指數）。
    22	"""
    23	from __future__ import annotations
    24	
    25	import json
    26	import os
    27	
    28	import numpy as np
    29	import pandas as pd
    30	import yfinance as yf
    31	from scipy.stats import norm
    32	
    33	SEED = 42
    34	ALPHA = 0.05
    35	Z = norm.ppf(ALPHA)  # -1.6449
    36	WINDOW = 26          # 論文 26 週滾動動差
    37	MA_S, MA_L = 20, 30  # 論文 MA20/MA30
    38	CRASH_THR = -0.05    # primary 事件門檻（週 log return）
    39	CRASH_THR_ALT = -0.04
    40	EPISODE_GAP = 13     # 事件週前 13 週無事件 → 新 episode onset
    41	PRECISION_H = 26     # 死亡交叉後 26 週內有 onset 算 precision 成功
    42	ASSOC_H = 13         # 關聯檢定 forward 視窗
    43	BOOT_B = 2000
    44	BLOCK = 26
    45	
    46	OUT_DIR = os.path.dirname(os.path.abspath(__file__))
    47	
    48	
    49	def fetch_weekly() -> pd.Series:
    50	    px = yf.download("^TWII", start="1997-01-01", auto_adjust=True, progress=False)
    51	    if isinstance(px.columns, pd.MultiIndex):
    52	        px.columns = px.columns.get_level_values(0)
    53	    close = px["Close"].dropna()
    54	    assert close.index[-1] >= pd.Timestamp("2026-07-17"), (
    55	        f"yfinance 資料落後（最後日 {close.index[-1].date()}）— 見 error_log 2026-07-15 stale 教訓"
    56	    )
    57	    wclose = close.resample("W-FRI").last().dropna()
    58	    wret = np.log(wclose / wclose.shift(1)).dropna()
    59	    return wret, wclose
    60	
    61	
    62	def cf_metrics(wret: pd.Series) -> pd.DataFrame:
    63	    """論文 eq(4)(11)(12)(13)(14) 的逐週指標。pandas 樣本偏態 / 超額峰態（bias-corrected）。"""
    64	    sigma = wret.rolling(WINDOW).std()
    65	    skew = wret.rolling(WINDOW).skew()
    66	    exk = wret.rolling(WINDOW).kurt()  # excess kurtosis（= 論文 k_t - 3）
    67	    z_cf = (Z
    68	            + (1 / 6) * (Z ** 2 - 1) * skew
    69	            + (1 / 24) * (Z ** 3 - 3 * Z) * exk
    70	            - (1 / 36) * (2 * Z ** 3 - 5 * Z) * skew ** 2)
    71	    beta_s = -sigma * ((1 / 6) * (Z ** 2 - 1) - (1 / 18) * (2 * Z ** 3 - 5 * Z) * skew)
    72	    beta_k = -sigma * ((1 / 24) * (Z ** 3 - 3 * Z))
    73	    beta_sig = -z_cf
    74	    dvar_s = (beta_s * skew.diff()).abs()
    75	    dvar_k = (beta_k * exk.diff()).abs()
    76	    dvar_sig = (beta_sig * sigma.diff()).abs()
    77	    tot = dvar_s + dvar_k + dvar_sig
    78	    return pd.DataFrame({
    79	        "ret": wret, "sigma": sigma, "skew": skew, "exk": exk,
    80	        "beta_s": beta_s, "beta_k": beta_k, "beta_sig": beta_sig,
    81	        "IS_s": dvar_s / tot, "IS_k": dvar_k / tot, "IS_sig": dvar_sig / tot,
    82	    })
    83	
    84	
    85	def cross_state(series: pd.Series) -> pd.DataFrame:
    86	    """MA20/MA30 死亡交叉狀態機。active=True 表 MA20<MA30（警戒中）。"""
    87	    m_s = series.rolling(MA_S).mean()
    88	    m_l = series.rolling(MA_L).mean()
    89	    gap = m_s - m_l
    90	    active = ((gap < 0) & gap.notna()).astype(bool)
    91	    # 嚴格交叉定義：前一週 gap 必須為有效非負值（Codex v1 finding 1：
    92	    # warmup 後第一個負 gap 不是交叉，前態未知不得視為 False）
    93	    death = (gap.lt(0) & gap.shift(1).ge(0)).astype(bool)
    94	    golden = (gap.ge(0) & gap.shift(1).lt(0)).astype(bool)
    95	    return pd.DataFrame({"gap": gap, "active": active, "death": death, "golden": golden})
    96	
    97	
    98	def episodes(wret: pd.Series, thr: float) -> list[pd.Timestamp]:
    99	    """episode 邏輯：與「上一個事件週」（不限 onset）間隔 > EPISODE_GAP 週才算新 onset。"""
   100	    crash = wret[wret <= thr].index
   101	    onsets, last_crash = [], None
   102	    for d in crash:
   103	        if last_crash is None or (d - last_crash).days > EPISODE_GAP * 7:
   104	            onsets.append(d)
   105	        last_crash = d
   106	    return onsets
   107	
   108	
   109	def weeks_since_last_death(state: pd.DataFrame, t: pd.Timestamp) -> int | None:
   110	    """t（含）之前最近一次 death cross 距 t 的週數；若其後有 golden cross 回傳 None。"""
   111	    idx = state.index
   112	    pos = idx.get_indexer([t])[0]
   113	    if pos < 0:
   114	        return None
   115	    for j in range(pos, -1, -1):
   116	        if bool(state["golden"].iloc[j]) and j != pos:
   117	            return None
   118	        if bool(state["death"].iloc[j]):
   119	            return pos - j
   120	    return None
   121	
   122	
   123	def evaluate_signal(state: pd.DataFrame, onsets: list[pd.Timestamp], idx: pd.DatetimeIndex,
   124	                    rng: np.random.Generator) -> dict:
   125	    valid = state.dropna(subset=["gap"])
   126	    # --- per-onset ex-ante 評估（t-1 狀態；明確 shift）---
   127	    active_lag = state["active"].shift(1)  # lookahead guard: 只用 onset 前一週資訊
   128	    per_event = []
   129	    for t in onsets:
   130	        if t not in active_lag.index or pd.isna(state.loc[:t, "gap"].iloc[-1]):
   131	            continue
   132	        pos = idx.get_indexer([t])[0]
   133	        if pos == 0:
   134	            continue
   135	        t_prev = idx[pos - 1]
   136	        if pd.isna(state["gap"].loc[t_prev]):  # 訊號 warmup 未完成的 onset 不列入評估
   137	            continue
   138	        is_active = bool(active_lag.loc[t])
   139	        lead = weeks_since_last_death(state, t_prev) if is_active else None
   140	        per_event.append({
   141	            "onset": str(t.date()),
   142	            "active_at_t_minus_1": is_active,
   143	            "lead_weeks": None if lead is None else int(lead + 1),  # +1: cross 至 onset 的週數
   144	            "valid_per_paper": bool(is_active and lead is not None and lead + 1 >= 3),
   145	        })
   146	    n_ev = len(per_event)
   147	    hits = sum(e["active_at_t_minus_1"] for e in per_event)
   148	    valid_hits = sum(e["valid_per_paper"] for e in per_event)
   149	    leads = [e["lead_weeks"] for e in per_event if e["lead_weeks"] is not None]
   150	    # --- 誤報成本 ---
   151	    deaths = valid.index[valid["death"]]
   152	    onset_idx = pd.DatetimeIndex(onsets)
   153	    prec_success = sum(
   154	        bool(((onset_idx > c) & (onset_idx <= c + pd.Timedelta(weeks=PRECISION_H))).any())
   155	        for c in deaths)
   156	    burden = float(valid["active"].mean())
   157	    # --- 週頻關聯 + circular block bootstrap ---
   158	    onset_flag = pd.Series(False, index=idx)
   159	    onset_flag.loc[onset_flag.index.isin(onset_idx)] = True
   160	    fwd = (onset_flag[::-1].rolling(ASSOC_H).max()[::-1].shift(-1)).astype(float)  # onset in t+1..t+13
   161	    df = pd.DataFrame({"active": valid["active"].astype(float), "fwd": fwd}).dropna()
   162	    a, f = df["active"].to_numpy(), df["fwd"].to_numpy()
   163	    n = len(a)
   164	
   165	    def cond_diff(av, fv):
   166	        p1 = fv[av == 1].mean() if (av == 1).any() else np.nan
   167	        p0 = fv[av == 0].mean() if (av == 0).any() else np.nan
   168	        return p1 - p0, p1, p0
   169	
   170	    diff_obs, p1_obs, p0_obs = cond_diff(a, f)
   171	    boot = []
   172	    n_blocks = int(np.ceil(n / BLOCK))
   173	    for _ in range(BOOT_B):
   174	        starts = rng.integers(0, n, size=n_blocks)
   175	        pos = np.concatenate([(s + np.arange(BLOCK)) % n for s in starts])[:n]
   176	        d, _, _ = cond_diff(a[pos], f[pos])
   177	        boot.append(d)
   178	    boot = np.array([b for b in boot if not np.isnan(b)])
   179	    ci = np.percentile(boot, [2.5, 97.5]).tolist()
   180	    ci99 = np.percentile(boot, [0.5, 99.5]).tolist()
   181	    # 正式檢定（Codex v1 finding 2）：circular-shift randomization null。
   182	    # 隨機旋轉 active 相對 fwd（offset >= ASSOC_H，保留兩序列各自的自相關、破壞對齊），
   183	    # p = (r+1)/(B_perm+1)，單尾 H1: diff > 0。
   184	    B_perm = 5000
   185	    perm_stats = []
   186	    for _ in range(B_perm):
   187	        off = int(rng.integers(ASSOC_H, n - ASSOC_H))
   188	        d_p, _, _ = cond_diff(np.roll(a, off), f)
   189	        if not np.isnan(d_p):
   190	            perm_stats.append(d_p)
   191	    perm_stats = np.array(perm_stats)
   192	    p_perm = float((np.sum(perm_stats >= diff_obs) + 1) / (len(perm_stats) + 1))
   193	    return {
   194	        "n_onsets_evaluable": n_ev,
   195	        "hit_rate_active_at_t_minus_1": round(hits / n_ev, 4) if n_ev else None,
   196	        "hits": hits,
   197	        "valid_per_paper_rate": round(valid_hits / n_ev, 4) if n_ev else None,
   198	        "valid_hits": valid_hits,
   199	        "lead_weeks_median": float(np.median(leads)) if leads else None,
   200	        "lead_weeks_iqr": [float(np.percentile(leads, 25)), float(np.percentile(leads, 75))] if leads else None,
   201	        "n_death_crosses": int(len(deaths)),
   202	        "precision_26w": round(prec_success / len(deaths), 4) if len(deaths) else None,
   203	        "warning_burden_frac_weeks_active": round(burden, 4),
   204	        "assoc_P_onset13_given_active": round(float(p1_obs), 4),
   205	        "assoc_P_onset13_given_inactive": round(float(p0_obs), 4),
   206	        "assoc_diff": round(float(diff_obs), 4),
   207	        "assoc_diff_ci95_blockboot": [round(c, 4) for c in ci],
   208	        "assoc_diff_ci99_blockboot": [round(c, 4) for c in ci99],
   209	        "assoc_diff_p_circshift_onesided": round(p_perm, 5),
   210	        "assoc_perm_B": B_perm,
   211	        "per_event": per_event,
   212	    }
   213	
   214	
   215	def main():
   216	    rng = np.random.default_rng(SEED)
   217	    wret, wclose = fetch_weekly()
   218	    m = cf_metrics(wret)
   219	    idx = m.index
   220	
   221	    states = {name: cross_state(m[name]) for name in ["beta_s", "beta_k", "IS_k"]}
   222	    # 機械等價 benchmark：純波動率趨勢（MA20(sigma) 上穿 MA30(sigma) = 警戒）
   223	    sig_up = cross_state(-m["sigma"])  # 取負號 → death cross of -sigma == sigma 上升趨勢
   224	    states["sigma_uptrend_benchmark"] = sig_up
   225	
   226	    onsets = episodes(wret, CRASH_THR)
   227	    onsets_alt = episodes(wret, CRASH_THR_ALT)
   228	
   229	    results = {
   230	        "experiment_id": "k1732",
   231	        "data": {
   232	            "source": "Yahoo Finance ^TWII (auto_adjust)",
   233	            "freq": "weekly W-FRI log returns",
   234	            "period": [str(idx[0].date()), str(idx[-1].date())],
   235	            "n_weeks": int(len(wret)),
   236	            "spec": {"alpha": ALPHA, "moment_window": WINDOW, "ma": [MA_S, MA_L],
   237	                     "moment_estimator": "pandas sample skew / excess kurt (bias-corrected)"},
   238	        },
   239	        "event_definition": {
   240	            "primary_thr_weekly_log_ret": CRASH_THR, "alt_thr": CRASH_THR_ALT,
   241	            "episode_gap_weeks": EPISODE_GAP,
   242	            "n_onsets_primary": len(onsets), "n_onsets_alt": len(onsets_alt),
   243	            "onsets_primary": [str(d.date()) for d in onsets],
   244	        },
   245	        "mechanical_equivalence": {
   246	            "note": ("beta_k = -sigma*(1/24)(z^3-3z) 是 sigma 的線性變換 → beta_k 死亡交叉"
   247	                     "『恆等於』sigma 上升趨勢交叉；beta_s = -sigma*(0.2843+0.0376*skew) 近似同理。"
   248	                     "此為 mechanical 結果：beta 訊號在本質上是波動率趨勢訊號，"
   249	                     "偏態僅提供 ~13% 調變。IS_k 才是higher-moment specific 訊號。"),
   250	            "corr_beta_k_neg_sigma": round(float(m["beta_k"].corr(-m["sigma"])), 6),
   251	            "corr_beta_s_neg_sigma": round(float(m["beta_s"].corr(-m["sigma"])), 4),
   252	            "beta_k_crosses_equal_sigma_crosses": bool(
   253	                (states["beta_k"]["death"].fillna(False) == sig_up["death"].fillna(False)).all()),
   254	        },
   255	        "signals": {},
   256	        "case_2026_07_17": {},
   257	        "seed": SEED, "bootstrap": {"B": BOOT_B, "block": BLOCK, "method": "circular block"},
   258	    }
   259	
   260	    for name, st in states.items():
   261	        results["signals"][name] = evaluate_signal(st, onsets, idx, rng)
   262	        # robustness: alt threshold（只記 hit rate，全表太長）
   263	        alt = evaluate_signal(st, onsets_alt, idx, np.random.default_rng(SEED + 1))
   264	        results["signals"][name]["alt_thr_hit_rate"] = alt["hit_rate_active_at_t_minus_1"]
   265	        results["signals"][name]["alt_thr_n_onsets"] = alt["n_onsets_evaluable"]
   266	
   267	    # 2026-07-17 實時案例
   268	    t_case = pd.Timestamp("2026-07-17")
   269	    for name, st in states.items():
   270	        lead = weeks_since_last_death(st, idx[idx.get_indexer([t_case])[0] - 1])
   271	        last_death = st.index[st["death"].fillna(False)]
   272	        last_death = last_death[last_death <= t_case]
   273	        results["case_2026_07_17"][name] = {
   274	            "active_at_t_minus_1": bool(st["active"].shift(1).loc[t_case]),
   275	            "lead_weeks_at_t_minus_1": None if lead is None else int(lead + 1),
   276	            "last_death_cross": str(last_death[-1].date()) if len(last_death) else None,
   277	        }
   278	    results["case_2026_07_17"]["week_ret"] = round(float(wret.loc[t_case]), 4)
   279	    isk_gap = states["IS_k"]["gap"].loc[:t_case].tail(8)
   280	    results["case_2026_07_17"]["isk_gap_last8"] = {str(d.date()): round(float(v), 6)
   281	                                                   for d, v in isk_gap.items()}
   282	
   283	    # Estimator sensitivity（Codex v1 finding 7）：population（bias=True）動差 vs pandas bias-corrected
   284	    from scipy.stats import kurtosis as _ku, skew as _sk
   285	    skew_p = wret.rolling(WINDOW).apply(lambda x: _sk(x, bias=True), raw=True)
   286	    exk_p = wret.rolling(WINDOW).apply(lambda x: _ku(x, bias=True, fisher=True), raw=True)
   287	    sigma_ = m["sigma"]
   288	    beta_s_p = -sigma_ * ((1 / 6) * (Z ** 2 - 1) - (1 / 18) * (2 * Z ** 3 - 5 * Z) * skew_p)
   289	    beta_k_p = -sigma_ * ((1 / 24) * (Z ** 3 - 3 * Z))
   290	    z_cf_p = (Z + (1 / 6) * (Z ** 2 - 1) * skew_p + (1 / 24) * (Z ** 3 - 3 * Z) * exk_p
   291	              - (1 / 36) * (2 * Z ** 3 - 5 * Z) * skew_p ** 2)
   292	    dv_s = (beta_s_p * skew_p.diff()).abs()
   293	    dv_k = (beta_k_p * exk_p.diff()).abs()
   294	    dv_sig = ((-z_cf_p) * sigma_.diff()).abs()
   295	    isk_p = dv_k / (dv_s + dv_k + dv_sig)
   296	    st_p, st_b = cross_state(isk_p), states["IS_k"]
   297	    both = pd.DataFrame({"a_pandas": st_b["active"], "a_pop": st_p["active"]}).dropna()
   298	    d_pandas = set(st_b.index[st_b["death"]].date)
   299	    d_pop = set(st_p.index[st_p["death"]].date)
   300	    results["estimator_sensitivity_ISk"] = {
   301	        "note": "population (bias=True) skew/exkurt 重算 IS_k 訊號 vs 基準 pandas bias-corrected",
   302	        "n_death_crosses_pop": int(st_p["death"].sum()),
   303	        "n_death_crosses_base": int(st_b["death"].sum()),
   304	        "n_cross_dates_differing": len(d_pandas ^ d_pop),
   305	        "n_active_weeks_differing": int((both["a_pandas"] != both["a_pop"]).sum()),
   306	        "n_weeks_compared": int(len(both)),
   307	    }
   308	
   309	    tmp = os.path.join(OUT_DIR, "k1732_results.json.tmp")
   310	    final = os.path.join(OUT_DIR, "k1732_results.json")
   311	    with open(tmp, "w") as f:
   312	        json.dump(results, f, ensure_ascii=False, indent=1)
   313	    json.load(open(tmp))  # 驗證可解析後原子替換
   314	    os.replace(tmp, final)
   315	
   316	    m.to_csv(os.path.join(OUT_DIR, "k1732_metrics_weekly.csv"))
   317	    wclose.to_csv(os.path.join(OUT_DIR, "k1732_twii_weekly_close.csv"))
   318	    print(json.dumps({k: v for k, v in results.items() if k not in ("signals", "case_2026_07_17")},
   319	                     ensure_ascii=False, indent=1))
   320	    for name in states:
   321	        s = dict(results["signals"][name])
   322	        s.pop("per_event")
   323	        print(f"\n=== {name} ===\n", json.dumps(s, ensure_ascii=False, indent=1))
   324	    print("\n=== case 2026-07-17 ===\n", json.dumps(results["case_2026_07_17"], ensure_ascii=False, indent=1))
   325	
   326	
   327	if __name__ == "__main__":
   328	    main()

codex
初步看來 1、6、7 的核心程式改動已存在；我正在核對正式 randomization 的虛無分布設計與結果可重現性。另已看到一個可能的同步遺漏：主腳本輸出的 mechanical-equivalence note 仍保留「偏態僅提供 ~13% 調變」，需看 JSON/README 是否互相矛盾。
exec
/bin/zsh -lc "nl -ba experiments/k1732/README.md | sed -n '1,260p'
nl -ba experiments/k1732/k1732_figures.py | sed -n '1,260p'
nl -ba experiments/k1732/k1732_results.json | sed -n '1,120p'
nl -ba experiments/k1732/k1732_results.json | sed -n '450,520p'
nl -ba experiments/k1732/k1732_results.json | sed -n '860,930p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
     1	# K1732: TAIEX Cornish-Fisher VaR 分解死亡交叉預警 — 29 年系統性回測
     2	
     3	**日期**: 2026-07-19 ｜ **提出**: 老闆（2026-07-17 台股 -6.47% 後指示「做」）｜ **執行**: Claude（主線程）
     4	**審查**: Codex v1 FAIL（8 findings）→ 全數修正後 v2 再審
     5	
     6	## 動機
     7	
     8	Lai & Chang（2409-662，已獲接受）以 Cornish-Fisher VaR 分解建立雙預警架構：β 敏感度（β_s、β_k）
     9	與峰態影響份額（IS_k）的 MA20/MA30 死亡交叉，在 19 個全球指數 × 3 次危機（2007-08、COVID、貿易戰）
    10	的事件研究中驗證。2026-07-17 台股單日 -6.47%（收 42,671），本 K 把同一套訊號放到 TAIEX 全歷史
    11	（1997-07 ~ 2026-07-17，週報酬 n=1,494）做**事件定義預先註冊**的系統性回測。與論文的事件研究互補：
    12	論文問「已知危機前訊號有沒有亮」；本 K 問「訊號亮的時候接下來到底有沒有事」（unconditional
    13	誤報成本是事件研究天生無法回答的）。
    14	
    15	相關 K / 知識庫：K836（台股 1% VaR 8 法比較，CF-VaR 唯一達標）、knowledge `a8c740e9`/`589692f0`
    16	（CF-VaR 跨資產 Kupiec 全過）。文獻：Cornish & Fisher (1938)；Favre & Galeano (2002)；
    17	Maillard (2018)；Kim & White (2004)；Lai & Chang (accepted)。
    18	
    19	## 設計（跑之前寫死，不看結果調整）
    20	
    21	- **資料**：Yahoo Finance ^TWII，W-FRI 週 log 報酬；26 週滾動 σ/偏態/超額峰態（pandas 樣本估計式，
    22	  bias-corrected；論文用標準樣本動差 — 見下方 estimator sensitivity）
    23	- **訊號**（論文 eq 4/11/12/14，α=5%）：β_s、β_k、IS_k 的 MA20/MA30 死亡交叉；警戒=MA20<MA30；
    24	  交叉採嚴格定義（前一週 gap 為有效非負值才算轉負交叉）
    25	- **事件**：週 log 報酬 ≤ −5% 為崩跌週；與上一崩跌週間隔 >13 週才算新 episode onset。
    26	  全期定義出 **30** 次 onset（−4% robustness：26 次）；其中落在訊號評估期（暖機完成後）的
    27	  **28** 次（robustness 24 次）進入逐事件評估
    28	- **Ex-ante 紀律**：一律取 onset **前一週（t−1）** 的訊號狀態（代碼有明確 `shift(1)`）；lead time
    29	  = 最近一次死亡交叉至 onset 的週數；論文有效判準 = 交叉在 onset 前 ≥3 週且中間無黃金交叉
    30	- **誤報成本**：precision（死亡交叉後 26 週內出現 onset 的比例）、warning burden（警戒週占比）
    31	- **關聯檢定**：週頻 P(未來 13 週出現 onset | 警戒) vs P(… | 非警戒)。
    32	  - 區間估計：circular block bootstrap（block=26、B=2000、seed=42）95%/99% percentile CI
    33	  - 正式檢定：**circular-shift randomization**（隨機旋轉 active 相對 fwd，offset≥13，B=5000，
    34	    保留兩序列自相關、破壞對齊；p=(r+1)/(B+1)，單尾）— empirical bootstrap 的 `P(draw≤0)`
    35	    不是 null 下 p 值，僅作參考不作宣稱
    36	- **Mechanical 對照**：β_k = −σ·(1/24)(z³−3z) 是 σ 的線性變換 → β_k 死亡交叉**恆等於**
    37	  「σ MA20 上穿 MA30」（代碼驗證 26 次交叉完全重合）；β_s 與 −σ 相關 0.9715，偏態項係數比
    38	  為 0.0376/0.2843 ≈ 13%/每單位偏態，本樣本偏態範圍 [−2.79, +1.81] 對應相對調變 −36.9% ~ +23.9%
    39	  （高度但非完全等價）。另設 σ-uptrend benchmark 直接對照。
    40	
    41	## 結果
    42	
    43	| 指標 | β_s | β_k | IS_k | σ-trend bench |
    44	|---|---|---|---|---|
    45	| 死亡交叉次數（29 年） | 28 | 26 | 71 | 26 |
    46	| 命中率 P(警戒@t−1 \| onset) | 46.4% | 46.4% | **71.4%** | 46.4% |
    47	| 警戒時間占比（burden） | 46.1% | 46.0% | 49.1% | 46.0% |
    48	| 論文判準有效率（≥3 週前） | 42.9% | 39.3% | **60.7%** | 39.3% |
    49	| lead 中位數（週） | 16 | 11 | 12 | 11 |
    50	| precision（26 週內有 onset） | 53.6% | 53.8% | 45.1% | 53.8% |
    51	| P(onset 13w \| 警戒) − P(\| 非警戒) | −0.047 | −0.046 | **+0.151** | −0.046 |
    52	| block bootstrap 95% CI | 含 0 | 含 0 | **[0.047, 0.250]** | 含 0 |
    53	| circular-shift 單尾 p | 0.738 | 0.714 | **0.0138** | — |
    54	| −4% robustness 命中率（n=24） | 41.7% | 37.5% | **75.0%** | 37.5% |
    55	
    56	**Estimator sensitivity**（population bias=True 動差重算 IS_k）：死亡交叉 71 vs 71 次、
    57	僅 6 個交叉日期不同、1,494 週中僅 5 個警戒週不同 — 主結果對估計式選擇穩健。
    58	
    59	**2026-07-17 案例**（週報酬 −6.10%）：β_s 死亡交叉 2026-03-27（前 16 週）、β_k 2026-04-03（前 15 週）
    60	且警戒持續至事件；IS_k 於 7/17 **當天**才交叉（t−1 未警戒）。IS_k 的 MA gap 自 5/29 +0.0083 收斂至
    61	7/03 +0.0010，**7/10（t−1）小幅回彈至 +0.0023**，7/17 翻負 −0.0042 — 大致收斂但非嚴格單調，
    62	依論文 5.2 節「前 6 週 gap 為正且收斂」的訊號品質判準，**此次 IS_k 交叉不構成有效提早預警**
    63	（β 警戒則滿足 ≥3 週判準）。
    64	
    65	## 結論（強度不超過證據）
    66	
    67	1. **三個單變量檢驗中，IS_k 是唯一估計為正且 CI 排除 0 的訊號**：警戒中未來 13 週崩跌起點機率
    68	   17.2%→32.3%（circular-shift 單尾 p=0.0138；×3 訊號 Bonferroni 校正後 0.041，5% 水準下顯著；
    69	   95%/99% percentile CI 均排除 0）；命中率 71.4% 高於 49.1% 覆蓋率；論文判準有效率 60.7%，
    70	   落在論文報告 IS_k 跨市場有效率區間（37–63%）上緣。註：本設計未做訊號間差異的直接檢定，
    71	   也未估計聯合模型，「IS_k 顯著而 β 不顯著」不等於「兩者差異顯著」；危機類型機制（內生 vs 外生）
    72	   非本單一市場設計可識別，僅方向上與論文對 IS_k 的定位相容。
    73	2. **β 死亡交叉在 TAIEX 29 年中未展現超越隨機覆蓋的關聯**（p≈0.71–0.74，命中率 46.4% ≈ burden
    74	   46.1%）。mechanical 揭露：β_k 交叉恆等於波動率上升趨勢交叉；β_s 高度近似（corr 0.9715）。
    75	   **這與論文跨 19 市場事件研究中 β 有效率較高（47–89%）並不矛盾**：論文條件在「已發生的危機」
    76	   上計時，本 K 加計了全部誤報；單一市場 28 個評估事件也不足以推翻跨市場結論 —
    77	   定位為 boundary condition，非 refutation。
    78	3. **實務口徑**：IS_k 是「體質變差」的 regime 訊號（中位領先 12 週、警戒期近半時間、
    79	   precision 45%），不是擇日工具；7/17 案例它當天才確認、且交叉前型態依論文判準不算有效預警 —
    80	   單一事件的敘事價值有限，29 年統計才是本 K 的證據主體。
    81	
    82	## Caveats
    83	
    84	- 單一市場；30 次 onset（28 次可評估）；事件門檻雖預先註冊仍屬研究者選擇（−4% robustness 方向一致）
    85	- 訊號「警戒中」與「事件後餘波」在長警戒期內無法完全分離（episode gap 13 週已部分處理）
    86	- 週頻樣本動差估計噪音大（論文 §3.7 已討論；MA20/30 平滑是論文原設計）
    87	- 無交易策略宣稱（無部位/報酬/MDD 比較）；QLIKE/DM 不適用（非點預測比較）
    88	- yfinance 早年 TWII 資料品質未逐點稽核；已 guard 最後日期 ≥2026-07-17 防 stale
    89	
    90	## 檔案
    91	
    92	- `k1732.py`（主腳本，seed=42）/ `k1732_results.json`（原子寫入）
    93	- `k1732_metrics_weekly.csv`、`k1732_twii_weekly_close.csv`（中間序列）
    94	- `k1732_figures.py` + `k1732_fig{1,2,3}_*.png`（案例時序 / 回測摘要 / 全景負擔）
    95	- `codex_review_v1.md`（FAIL，8 findings）→ 修正 → `codex_review_v2.md`
     1	"""K1732 圖表：(1) 2026-07-17 案例時序 (2) 29 年回測摘要 (3) 全歷史警戒負擔誠實圖。
     2	色盤：Okabe-Ito（CVD-safe），固定色序；無雙 y 軸（堆疊 panel）。
     3	"""
     4	import json
     5	import os
     6	
     7	import matplotlib
     8	matplotlib.use("Agg")
     9	import matplotlib.pyplot as plt
    10	import matplotlib.dates as mdates
    11	import numpy as np
    12	import pandas as pd
    13	
    14	plt.rcParams["font.sans-serif"] = ["PingFang TC", "Heiti TC", "Arial Unicode MS"]
    15	plt.rcParams["axes.unicode_minus"] = False
    16	C_BLUE, C_ORANGE, C_GREEN, C_VERM, C_GRAY = "#0072B2", "#E69F00", "#009E73", "#D55E00", "#999999"
    17	
    18	D = os.path.dirname(os.path.abspath(__file__))
    19	m = pd.read_csv(os.path.join(D, "k1732_metrics_weekly.csv"), index_col=0, parse_dates=True)
    20	px = pd.read_csv(os.path.join(D, "k1732_twii_weekly_close.csv"), index_col=0, parse_dates=True).iloc[:, 0]
    21	res = json.load(open(os.path.join(D, "k1732_results.json")))
    22	MA_S, MA_L = 20, 30
    23	
    24	
    25	def ma_state(s):
    26	    gap = s.rolling(MA_S).mean() - s.rolling(MA_L).mean()
    27	    active = ((gap < 0) & gap.notna()).astype(bool)
    28	    return gap, active
    29	
    30	
    31	# ---------- Fig 1: 2026-07-17 案例 ----------
    32	lo, hi = pd.Timestamp("2025-07-01"), pd.Timestamp("2026-07-24")
    33	fig, (ax1, ax2, ax3) = plt.subplots(
    34	    3, 1, figsize=(9, 8.4), sharex=True, gridspec_kw={"height_ratios": [2, 1.4, 1.4], "hspace": 0.12})
    35	
    36	pxz = px.loc[lo:hi]
    37	ax1.plot(pxz.index, pxz.values, color=C_BLUE, lw=2)
    38	gap_bs, act_bs = ma_state(m["beta_s"])
    39	act_z = act_bs.loc[lo:hi]
    40	ax1.fill_between(pxz.index, *ax1.get_ylim() if False else (pxz.min() * 0.97, pxz.max() * 1.02),
    41	                 where=act_z.reindex(pxz.index).fillna(False), color=C_ORANGE, alpha=0.14, lw=0)
    42	ax1.axvline(pd.Timestamp("2026-07-17"), color=C_VERM, lw=1.2, ls="--")
    43	ax1.annotate("7/17 單日 −6.5%", xy=(pd.Timestamp("2026-07-17"), pxz.min()), xytext=(-118, 8),
    44	             textcoords="offset points", color=C_VERM, fontsize=10)
    45	ax1.annotate("β 死亡交叉警戒區（3/27 起）", xy=(pd.Timestamp("2026-04-10"), pxz.max() * 0.99),
    46	             color="#8a6100", fontsize=10)
    47	ax1.set_ylabel("台股加權指數（週收盤）")
    48	ax1.set_title("2026-07-17 大跌前：論文三訊號的實際時序", fontsize=13, loc="left", pad=10)
    49	
    50	bsz = m["beta_s"].loc[lo:hi]
    51	ax2.plot(bsz.index, m["beta_s"].rolling(MA_S).mean().loc[lo:hi],
    52	         color=C_ORANGE, lw=2, label="β_s 短均線 MA20")
    53	ax2.plot(bsz.index, m["beta_s"].rolling(MA_L).mean().loc[lo:hi], color=C_GRAY, lw=2, label="β_s 長均線 MA30")
    54	ax2.axvline(pd.Timestamp("2026-03-27"), color=C_VERM, lw=1, ls=":")
    55	ax2.annotate("3/27 死亡交叉\n（大跌前 16 週）", xy=(pd.Timestamp("2026-03-27"), m["beta_s"].rolling(MA_L).mean().loc[lo:hi].min()),
    56	             xytext=(8, 6), textcoords="offset points", color=C_VERM, fontsize=9)
    57	ax2.set_ylabel("偏態敏感度 β_s")
    58	ax2.legend(frameon=False, fontsize=9, loc="upper right")
    59	
    60	ax3.plot(bsz.index, m["IS_k"].rolling(MA_S).mean().loc[lo:hi], color=C_GREEN, lw=2, label="IS_k 短均線 MA20")
    61	ax3.plot(bsz.index, m["IS_k"].rolling(MA_L).mean().loc[lo:hi], color=C_GRAY, lw=2, label="IS_k 長均線 MA30")
    62	ax3.axvline(pd.Timestamp("2026-07-17"), color=C_VERM, lw=1.2, ls="--")
    63	ax3.annotate("6 月 gap 收斂近零\n（7/10 小幅回彈）", xy=(pd.Timestamp("2026-06-05"), m["IS_k"].rolling(MA_L).mean().loc[lo:hi].mean()),
    64	             xytext=(-90, 14), textcoords="offset points", color="#1b6e54", fontsize=9)
    65	ax3.annotate("7/17 當天才交叉", xy=(pd.Timestamp("2026-07-17"), m["IS_k"].rolling(MA_S).mean().loc[lo:hi].iloc[-1]),
    66	             xytext=(-104, -12), textcoords="offset points", color=C_VERM, fontsize=9)
    67	ax3.set_ylabel("峰態影響份額 IS_k")
    68	ax3.legend(frameon=False, fontsize=9, loc="upper right")
    69	for ax in (ax1, ax2, ax3):
    70	    ax.grid(alpha=0.22, lw=0.5)
    71	    ax.spines[["top", "right"]].set_visible(False)
    72	ax3.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    73	fig.align_ylabels()
    74	fig.text(0.99, 0.005, "資料：Yahoo Finance ^TWII 週資料｜方法：Lai & Chang CF-VaR 分解（26 週動差、MA20/30）｜VolPred K1732",
    75	         ha="right", fontsize=7.5, color="#777")
    76	fig.savefig(os.path.join(D, "k1732_fig1_case2026.png"), dpi=160, bbox_inches="tight")
    77	plt.close(fig)
    78	
    79	# ---------- Fig 2: 回測摘要 ----------
    80	sig_labels = {"beta_s": "β 敏感度訊號\n(≈波動率趨勢)", "IS_k": "IS_k 峰態份額訊號"}
    81	fig, (axa, axb) = plt.subplots(1, 2, figsize=(9.6, 4.4), gridspec_kw={"wspace": 0.3})
    82	
    83	x = np.arange(2)
    84	for i, key in enumerate(["beta_s", "IS_k"]):
    85	    s = res["signals"][key]
    86	    p1, p0 = s["assoc_P_onset13_given_active"], s["assoc_P_onset13_given_inactive"]
    87	    axa.bar(i - 0.17, p1, 0.3, color=C_VERM if key == "IS_k" else C_GRAY, alpha=0.95)
    88	    axa.bar(i + 0.17, p0, 0.3, color="#cccccc")
    89	    axa.text(i - 0.17, p1 + 0.008, f"{p1:.0%}", ha="center", fontsize=11, fontweight="bold")
    90	    axa.text(i + 0.17, p0 + 0.008, f"{p0:.0%}", ha="center", fontsize=11, color="#666")
    91	axa.set_xticks(x, [sig_labels["beta_s"], sig_labels["IS_k"]], fontsize=10)
    92	axa.set_ylabel("未來 13 週出現崩跌起點的機率")
    93	axa.set_title("警戒中（深色）vs 非警戒（淺色）", fontsize=11, loc="left")
    94	axa.set_ylim(0, 0.42)
    95	axa.annotate("IS_k：17%→32%\nbootstrap CI 排除 0", xy=(1, 0.385), fontsize=9,
    96	             ha="center", color=C_VERM)
    97	axa.annotate("β：無差異", xy=(0, 0.30), fontsize=9, ha="center", color="#666")
    98	
    99	for i, key in enumerate(["beta_s", "IS_k"]):
   100	    s = res["signals"][key]
   101	    hr, bd = s["hit_rate_active_at_t_minus_1"], s["warning_burden_frac_weeks_active"]
   102	    axb.bar(i - 0.17, hr, 0.3, color=C_BLUE)
   103	    axb.bar(i + 0.17, bd, 0.3, color="#cccccc")
   104	    axb.text(i - 0.17, hr + 0.008, f"{hr:.0%}", ha="center", fontsize=11, fontweight="bold")
   105	    axb.text(i + 0.17, bd + 0.008, f"{bd:.0%}", ha="center", fontsize=11, color="#666")
   106	axb.set_xticks(x, [sig_labels["beta_s"], sig_labels["IS_k"]], fontsize=10)
   107	axb.set_ylabel("比率")
   108	axb.set_title("命中率（藍）vs 警戒時間占比（灰）", fontsize=11, loc="left")
   109	axb.set_ylim(0, 0.85)
   110	axb.annotate("命中≈占比\n= 沒有增量資訊", xy=(0, 0.56), fontsize=9, ha="center", color="#666")
   111	axb.annotate("71% > 49%", xy=(1 - 0.17, 0.76), fontsize=9, ha="center", color=C_BLUE)
   112	for ax in (axa, axb):
   113	    ax.grid(alpha=0.22, lw=0.5, axis="y")
   114	    ax.spines[["top", "right"]].set_visible(False)
   115	fig.suptitle("台股 29 年系統性回測（30 次崩跌起點、28 次落在評估期，1997–2026）", fontsize=13, x=0.02, ha="left")
   116	fig.text(0.99, -0.02, "崩跌起點=週跌幅≤−5% 且前 13 週無事件｜訊號取前一週狀態（無 lookahead）｜VolPred K1732",
   117	         ha="right", fontsize=7.5, color="#777")
   118	fig.savefig(os.path.join(D, "k1732_fig2_backtest.png"), dpi=160, bbox_inches="tight")
   119	plt.close(fig)
   120	
   121	# ---------- Fig 3: 全歷史 + 警戒負擔 ----------
   122	fig, ax = plt.subplots(figsize=(9.6, 4.6))
   123	gap_k, act_k = ma_state(m["IS_k"])
   124	ax.semilogy(px.index, px.values, color=C_BLUE, lw=1.1)
   125	ax.fill_between(px.index, px.min() * 0.9, px.max() * 1.1,
   126	                where=act_k.reindex(px.index).fillna(False), color=C_GREEN, alpha=0.12, lw=0)
   127	onsets = pd.to_datetime(res["event_definition"]["onsets_primary"])
   128	ax.plot(onsets, px.reindex(onsets, method="nearest") * 1.0, "v", color=C_VERM, ms=7,
   129	        markeredgecolor="white", markeredgewidth=0.6)
   130	ax.set_ylabel("台股加權指數（log 尺度）")
   131	ax.set_title("29 年全景：▼=30 次崩跌起點；綠色底=IS_k 警戒期（49% 的時間）", fontsize=12, loc="left", pad=8)
   132	ax.grid(alpha=0.22, lw=0.5)
   133	ax.spines[["top", "right"]].set_visible(False)
   134	ax.annotate("警戒期覆蓋 20/28 次可評估起點，但也覆蓋近半的承平時光 —\n它是「體質變差」的 regime 訊號，不是擇日工具",
   135	            xy=(pd.Timestamp("1999-01-01"), px.max() * 0.75), fontsize=9.5, color="#1b6e54")
   136	fig.text(0.99, -0.02, "資料：Yahoo Finance ^TWII 1997–2026 週資料｜VolPred K1732", ha="right", fontsize=7.5, color="#777")
   137	fig.savefig(os.path.join(D, "k1732_fig3_history.png"), dpi=160, bbox_inches="tight")
   138	plt.close(fig)
   139	print("figures done")
     1	{
     2	 "experiment_id": "k1732",
     3	 "data": {
     4	  "source": "Yahoo Finance ^TWII (auto_adjust)",
     5	  "freq": "weekly W-FRI log returns",
     6	  "period": [
     7	   "1997-07-11",
     8	   "2026-07-17"
     9	  ],
    10	  "n_weeks": 1494,
    11	  "spec": {
    12	   "alpha": 0.05,
    13	   "moment_window": 26,
    14	   "ma": [
    15	    20,
    16	    30
    17	   ],
    18	   "moment_estimator": "pandas sample skew / excess kurt (bias-corrected)"
    19	  }
    20	 },
    21	 "event_definition": {
    22	  "primary_thr_weekly_log_ret": -0.05,
    23	  "alt_thr": -0.04,
    24	  "episode_gap_weeks": 13,
    25	  "n_onsets_primary": 30,
    26	  "n_onsets_alt": 26,
    27	  "onsets_primary": [
    28	   "1997-09-05",
    29	   "1998-05-29",
    30	   "1999-02-05",
    31	   "1999-07-16",
    32	   "2000-02-25",
    33	   "2000-09-01",
    34	   "2001-12-21",
    35	   "2003-02-07",
    36	   "2004-03-26",
    37	   "2006-06-09",
    38	   "2007-08-17",
    39	   "2007-12-14",
    40	   "2008-06-13",
    41	   "2009-08-21",
    42	   "2010-01-22",
    43	   "2011-02-11",
    44	   "2011-08-05",
    45	   "2014-10-17",
    46	   "2015-08-21",
    47	   "2016-01-08",
    48	   "2018-02-09",
    49	   "2020-01-31",
    50	   "2020-09-25",
    51	   "2021-01-29",
    52	   "2021-05-14",
    53	   "2022-06-17",
    54	   "2024-04-19",
    55	   "2025-04-11",
    56	   "2026-03-06",
    57	   "2026-07-17"
    58	  ]
    59	 },
    60	 "mechanical_equivalence": {
    61	  "note": "beta_k = -sigma*(1/24)(z^3-3z) 是 sigma 的線性變換 → beta_k 死亡交叉『恆等於』sigma 上升趨勢交叉；beta_s = -sigma*(0.2843+0.0376*skew) 近似同理。此為 mechanical 結果：beta 訊號在本質上是波動率趨勢訊號，偏態僅提供 ~13% 調變。IS_k 才是higher-moment specific 訊號。",
    62	  "corr_beta_k_neg_sigma": 1.0,
    63	  "corr_beta_s_neg_sigma": 0.9715,
    64	  "beta_k_crosses_equal_sigma_crosses": true
    65	 },
    66	 "signals": {
    67	  "beta_s": {
    68	   "n_onsets_evaluable": 28,
    69	   "hit_rate_active_at_t_minus_1": 0.4643,
    70	   "hits": 13,
    71	   "valid_per_paper_rate": 0.4286,
    72	   "valid_hits": 12,
    73	   "lead_weeks_median": 16.0,
    74	   "lead_weeks_iqr": [
    75	    7.0,
    76	    20.0
    77	   ],
    78	   "n_death_crosses": 28,
    79	   "precision_26w": 0.5357,
    80	   "warning_burden_frac_weeks_active": 0.4611,
    81	   "assoc_P_onset13_given_active": 0.2212,
    82	   "assoc_P_onset13_given_inactive": 0.268,
    83	   "assoc_diff": -0.0468,
    84	   "assoc_diff_ci95_blockboot": [
    85	    -0.1636,
    86	    0.0791
    87	   ],
    88	   "assoc_diff_ci99_blockboot": [
    89	    -0.1991,
    90	    0.1196
    91	   ],
    92	   "assoc_diff_p_circshift_onesided": 0.73825,
    93	   "assoc_perm_B": 5000,
    94	   "per_event": [
    95	    {
    96	     "onset": "1999-02-05",
    97	     "active_at_t_minus_1": true,
    98	     "lead_weeks": 18,
    99	     "valid_per_paper": true
   100	    },
   101	    {
   102	     "onset": "1999-07-16",
   103	     "active_at_t_minus_1": true,
   104	     "lead_weeks": 9,
   105	     "valid_per_paper": true
   106	    },
   107	    {
   108	     "onset": "2000-02-25",
   109	     "active_at_t_minus_1": false,
   110	     "lead_weeks": null,
   111	     "valid_per_paper": false
   112	    },
   113	    {
   114	     "onset": "2000-09-01",
   115	     "active_at_t_minus_1": true,
   116	     "lead_weeks": 6,
   117	     "valid_per_paper": true
   118	    },
   119	    {
   120	     "onset": "2001-12-21",
   450	    },
   451	    {
   452	     "onset": "2026-03-06",
   453	     "active_at_t_minus_1": false,
   454	     "lead_weeks": null,
   455	     "valid_per_paper": false
   456	    },
   457	    {
   458	     "onset": "2026-07-17",
   459	     "active_at_t_minus_1": true,
   460	     "lead_weeks": 15,
   461	     "valid_per_paper": true
   462	    }
   463	   ],
   464	   "alt_thr_hit_rate": 0.375,
   465	   "alt_thr_n_onsets": 24
   466	  },
   467	  "IS_k": {
   468	   "n_onsets_evaluable": 28,
   469	   "hit_rate_active_at_t_minus_1": 0.7143,
   470	   "hits": 20,
   471	   "valid_per_paper_rate": 0.6071,
   472	   "valid_hits": 17,
   473	   "lead_weeks_median": 12.0,
   474	   "lead_weeks_iqr": [
   475	    5.75,
   476	    16.5
   477	   ],
   478	   "n_death_crosses": 71,
   479	   "precision_26w": 0.4507,
   480	   "warning_burden_frac_weeks_active": 0.4913,
   481	   "assoc_P_onset13_given_active": 0.3229,
   482	   "assoc_P_onset13_given_inactive": 0.1722,
   483	   "assoc_diff": 0.1507,
   484	   "assoc_diff_ci95_blockboot": [
   485	    0.0472,
   486	    0.2501
   487	   ],
   488	   "assoc_diff_ci99_blockboot": [
   489	    0.0203,
   490	    0.2852
   491	   ],
   492	   "assoc_diff_p_circshift_onesided": 0.0138,
   493	   "assoc_perm_B": 5000,
   494	   "per_event": [
   495	    {
   496	     "onset": "1999-02-05",
   497	     "active_at_t_minus_1": true,
   498	     "lead_weeks": 2,
   499	     "valid_per_paper": false
   500	    },
   501	    {
   502	     "onset": "1999-07-16",
   503	     "active_at_t_minus_1": true,
   504	     "lead_weeks": 6,
   505	     "valid_per_paper": true
   506	    },
   507	    {
   508	     "onset": "2000-02-25",
   509	     "active_at_t_minus_1": true,
   510	     "lead_weeks": 7,
   511	     "valid_per_paper": true
   512	    },
   513	    {
   514	     "onset": "2000-09-01",
   515	     "active_at_t_minus_1": false,
   516	     "lead_weeks": null,
   517	     "valid_per_paper": false
   518	    },
   519	    {
   520	     "onset": "2001-12-21",
   860	     "lead_weeks": 15,
   861	     "valid_per_paper": true
   862	    }
   863	   ],
   864	   "alt_thr_hit_rate": 0.375,
   865	   "alt_thr_n_onsets": 24
   866	  }
   867	 },
   868	 "case_2026_07_17": {
   869	  "beta_s": {
   870	   "active_at_t_minus_1": true,
   871	   "lead_weeks_at_t_minus_1": 16,
   872	   "last_death_cross": "2026-03-27"
   873	  },
   874	  "beta_k": {
   875	   "active_at_t_minus_1": true,
   876	   "lead_weeks_at_t_minus_1": 15,
   877	   "last_death_cross": "2026-04-03"
   878	  },
   879	  "IS_k": {
   880	   "active_at_t_minus_1": false,
   881	   "lead_weeks_at_t_minus_1": null,
   882	   "last_death_cross": "2026-07-17"
   883	  },
   884	  "sigma_uptrend_benchmark": {
   885	   "active_at_t_minus_1": true,
   886	   "lead_weeks_at_t_minus_1": 15,
   887	   "last_death_cross": "2026-04-03"
   888	  },
   889	  "week_ret": -0.061,
   890	  "isk_gap_last8": {
   891	   "2026-05-29": 0.008348,
   892	   "2026-06-05": 0.007624,
   893	   "2026-06-12": 0.007493,
   894	   "2026-06-19": 0.005564,
   895	   "2026-06-26": 0.002411,
   896	   "2026-07-03": 0.000963,
   897	   "2026-07-10": 0.002346,
   898	   "2026-07-17": -0.004197
   899	  }
   900	 },
   901	 "seed": 42,
   902	 "bootstrap": {
   903	  "B": 2000,
   904	  "block": 26,
   905	  "method": "circular block"
   906	 },
   907	 "estimator_sensitivity_ISk": {
   908	  "note": "population (bias=True) skew/exkurt 重算 IS_k 訊號 vs 基準 pandas bias-corrected",
   909	  "n_death_crosses_pop": 71,
   910	  "n_death_crosses_base": 71,
   911	  "n_cross_dates_differing": 6,
   912	  "n_active_weeks_differing": 5,
   913	  "n_weeks_compared": 1494
   914	 }
   915	}
exec
/bin/zsh -lc "uv run python - <<'PY'
import importlib.util, json
from pathlib import Path
import numpy as np, pandas as pd
p=Path('experiments/k1732')
spec=importlib.util.spec_from_file_location('k1732', p/'k1732.py')
k=importlib.util.module_from_spec(spec); spec.loader.exec_module(k)
m=pd.read_csv(p/'k1732_metrics_weekly.csv',index_col=0,parse_dates=True)
wret=m['ret'].dropna(); idx=m.index
onsets=k.episodes(wret,k.CRASH_THR)
states={name:k.cross_state(m[name]) for name in ['beta_s','beta_k','IS_k']}
rng=np.random.default_rng(k.SEED)
for name,st in states.items():
    out=k.evaluate_signal(st,onsets,idx,rng)
    print(name, out['n_death_crosses'], out['precision_26w'], out['assoc_diff_p_circshift_onesided'],out['assoc_diff_ci95_blockboot'],out['assoc_diff_ci99_blockboot'])
# Exact finite circular-shift reference distribution for IS_k
st=states['IS_k']; valid=st.dropna(subset=['gap'])
onset_idx=pd.DatetimeIndex(onsets)
onset_flag=pd.Series(False,index=idx); onset_flag.loc[onset_flag.index.isin(onset_idx)]=True
fwd=(onset_flag[::-1].rolling(k.ASSOC_H).max()[::-1].shift(-1)).astype(float)
df=pd.DataFrame({'active':valid['active'].astype(float),'fwd':fwd}).dropna(); a=df.active.to_numpy(); f=df.fwd.to_numpy(); n=len(a)
def d(av):
 p1=f[av==1].mean(); p0=f[av==0].mean(); return p1-p0
obs=d(a)
allowed=np.arange(k.ASSOC_H,n-k.ASSOC_H)
stats=np.array([d(np.roll(a,int(off))) for off in allowed])
allnonzero=np.arange(1,n)
stats_all=np.array([d(np.roll(a,int(off))) for off in allnonzero])
print('n',n,'obs',obs,'allowed',len(allowed),'exact_r',int((stats>=obs).sum()),'exact_p_plus1',(int((stats>=obs).sum())+1)/(len(stats)+1),'exact_fraction',float((stats>=obs).mean()))
print('all_nonzero_r',int((stats_all>=obs).sum()),'all_nonzero_fraction',float((stats_all>=obs).mean()))
PY" in /Users/yhlai0911/volpred-research
 succeeded in 2297ms:
beta_s 28 0.5357 0.73825 [-0.1636, 0.0791] [-0.1991, 0.1196]
beta_k 26 0.5385 0.71386 [-0.1636, 0.0624] [-0.1982, 0.0891]
IS_k 71 0.4507 0.0138 [0.0472, 0.2501] [0.0203, 0.2852]
n 1426 obs 0.15072395341517153 allowed 1400 exact_r 15 exact_p_plus1 0.011420413990007138 exact_fraction 0.010714285714285714
all_nonzero_r 20 all_nonzero_fraction 0.014035087719298246

exec
/bin/zsh -lc 'cat .claude/skills/autonomous-research/references/experiment-preamble.md
rg -n -C 3 "K1732|circular.shift|randomization|bootstrap|動差|moment estimator|交叉" docs/error_log.md | head -160' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
# Experiment Agent Preamble（實驗 Agent 必讀）

**此文件必須附加在每個實驗 agent prompt 的開頭。不可省略。**

## 1. 模型-Target 匹配規則（最重要）

不同波動率模型預測不同的東西，評估必須在各自的原生 target 上進行：

| 模型類型 | 預測標的 | 正確評估 target | 不可用的 target |
|---------|---------|----------------|----------------|
| GARCH/GJR/EGARCH | close-to-close σ²（全日，含隔夜）| r²（squared daily return）| 日內 RV |
| HAR-RV | 日內 realized variance（僅交易時段）| 5-min RV | r² |
| MEM | |r| 或 r² | 各自原生 | 混用 |
| Range (Parkinson/GK/RS) | 日內 high-low range | range-based vol | r² |

**跨模型公平比較的唯一正確方式**：
1. Patton (2011): QLIKE on r²（proxy-robust，排名一致性有理論保證）
2. Hansen & Lunde (2005): 最優加權 RV_total = w₁×RV_intraday + w₂×r²_overnight
3. Spearman rank correlation（分配無關）

**絕對禁止**：
- 用 RV target 評估 GARCH 然後說 HAR 贏（HAR 本來就預測 RV）
- 用 r² target 評估 HAR 然後說 GARCH 贏（GARCH 本來就預測 σ²）
- 把「模型在自己 target 上贏」宣稱為「發現」——這是設計的必然，不是實證結果

## 2. Mechanical vs Empirical 區分

如果結果可以從模型定義直接推導，它是 **mechanical result**，不是 empirical finding：
- Mechanical: HAR 在 RV 上贏 GARCH（定義使然）
- Empirical: HAR-RV 經 Hansen & Lunde 調整後在全日 vol 上仍勝 GARCH（需要實證驗證）
- Mechanical: gamma > 0 implies VT de-levers after negative returns（GJR 方程式使然）
- Empirical: cross-sectional gamma-VT correlation exceeds mechanical prediction（需要數據）

**不可把 mechanical result 宣稱為 contribution 或 discovery。**

## 3. 統計門檻

| 檢定 | 門檻 | 依據 |
|------|------|------|
| DM test | Harvey (2016) \|t\| > 3.0 | 多重檢定校正 |
| Sharpe 差異 | SE ≈ 1/√N_years | 19 年 SE=0.23 |
| Cross-sectional | N ≥ 7 | Spearman 穩定性 |
| Bootstrap | ≥ 1000 reps | CI 精確度 |
| GARCH window | ≥ 500（建議 2000）| Hwang & Valls Pereira (2006) |
| OOS 期間 | ≥ 252 天 | 至少涵蓋 1 年 |

**Sharpe > 2x baseline = 幾乎一定有 bug，先停下來檢查。**

## 3b. 風險管理評估標準（VaR + ES）

模型比較必須涵蓋 VaR 和 ES 兩個維度：

| 評估 | 方法 | 門檻 | 依據 |
|------|------|------|------|
| **VaR unconditional** | Kupiec (1995) LR test | p > 0.05 | 違約率是否符合目標 |
| **VaR conditional** | Christoffersen (1998) CC test | p > 0.05 | 違約是否獨立 |
| **VaR Basel** | Traffic light (Green/Yellow/Red) | Green | 250天內違約次數 |
| **Trinity** | Kupiec + CC + Basel 全過 | 全 PASS | 三重把關 |
| **ES backtest** | Acerbi & Szekely (2014) Z-test | p > 0.05 | ES 是否充分覆蓋尾部 |
| **Joint VaR-ES** | Fissler & Ziegel (2016) scoring | 越低越好 | 唯一 strictly consistent joint loss |

**VaR 和 ES 必須同時在 1% 和 5% 信心水準評估。只測 1% 不夠。**
**VaR/ES 評估必須分 In-Sample 和 Out-of-Sample 分別報告。** IS PASS + OOS PASS = 可信；IS PASS + OOS FAIL = overfitting。只報一種沒有說服力。

## 4. 防錯規則

- **DM test**：forecast pointwise losses 用 `from volpred.stats.model_evaluation import dm_test`；交易策略報酬比較才用 `strategy_dm_test`。兩者都不可在實驗內另寫 helper
- **0050.TW**：必須 `from volpred.utils import clean_tw50_data`
- **Lookahead**：`signal = signal.shift(1)` 寫在代碼裡，不靠記憶
- **GARCH OOS**：逐日遞迴 h[t]=f(h[t-1],r²[t-1])，不用 stale variance
- **Student-t**：考慮 scale term sqrt((df-2)/df)
- **Basel/統計檢定**：用標準實作，不自定義閾值
- **TAIFEX 期貨轉倉**：不要直接用 TX1（近月），要用 **TX（全合約）數據，每日按成交量選最活躍的合約月份**。結算日（每月第三個週三）TX1 自動切換合約月份會有 roll gap（~0.5-1.0%）。正確做法：讀 TX 檔案 → 按「到期月份」分組計算成交量 → 選當日成交量最大的合約 → 只用該合約的 tick 計算 return/RV。這樣在流動性自然轉移時平滑切換，不會有假波動
- **Results JSON 寫入**：結果檔必須先寫到同目錄暫存檔、`json.load` 驗證可解析，再用 `os.replace(tmp, final)` 原子替換；禁止直接 `open(results.json, "w")` 後 `json.dump`，避免 agent 中途死亡留下截斷 JSON。

## 5. 結果自我質疑（實驗完成後必做）

在記錄結論前，問自己：
1. 這個結果是 mechanical 還是 empirical？
2. 這跟 research_program.md 已有的方法論標準矛盾嗎？
3. 如果用不同的 target/proxy，結論會改變嗎？
4. Sharpe > 2x baseline 嗎？（如果是，90% 有 bug）
5. 這個結論的強度是否超過證據支持的範圍？

## 6. Periodic Model Robustness（PRG/PRS 專用）

- **Session 收盤價可交易性**：session 收盤價可能無法即時交易。Robustness check 應使用收盤前 n 分鐘（n=1,5,10）的價格重算 session return 和 RV，確認結果穩健。
- **Information set 說明**：PRG/PRS 使用「前一 session 已實現的資訊」預測「下一 session」。這不是 lookahead——隔夜 session 在日盤開盤前已結束，日盤 session 在夜盤開盤前已結束。論文必須明確標註每個模型的 information set。
- **公平比較**：PRG 在 session 邊界有更多資訊（剛完成的 session）。與 GJR（日頻）比較時，PRG 的優勢包含「模型結構」+「資訊即時性」兩個成分。要隔離純模型結構價值，可比 PRG vs GJR-X(r²_overnight)。

## 7. Worktree 保存規則（必做）

**在完成所有工作後，必須執行以下命令保存檔案：**
```bash
git add -A && git commit -m "K9XX: description"
```
不 commit = 檔案在 worktree 清理時永久遺失。K923/K924/K932 都因此遺失過腳本。

## 8. Worktree 共享狀態禁令（必遵守）

**Worktree agent 禁止直接修改以下共享狀態檔案：**
- `storage/reports/feed.json`（由主線程透過 publish_milestone 統一寫入）
- `storage/memory/knowledge.json`（由主線程在 agent 完成後統一記錄）
- `storage/memory/thinking_journal.json`（同上）
- `storage/memory/experiment_experiences.json`（同上）
- 禁止呼叫 `supabase_sync.py`、`_sync_to_remote()` 或任何寫入 Supabase/Mirror 的操作

**原因**：Worktree 是隔離的 git 分支。若 worktree 和主線程同時修改這些 JSON 陣列檔案，git merge 無法自動合併 → 資料遺失。若同時 sync 到 Supabase，兩邊會互相覆蓋。

**Worktree agent 只應產出：**
- `experiments/kXXX/` 下的所有檔案（腳本 `.py`、結果 `_results.json`、圖表 `.png`、`README.md`）
- 結果透過 agent 返回值傳回主線程
- **主線程負責**：記錄 knowledge、發佈文章、sync 到 Supabase
124-
125-## G. Lookahead / DM-HAC / MDD / 方法論硬規則
126-
127:**規則**：Lookahead 是最高風險 —— code 要有明確 `signal.shift(1)`；forward-label target 訓練列須 `target_end < forecast_origin`。DM 的 HAC lag 不可只用 `h-1`（h=1 時退化成 iid）；先量 loss differential 的 acf 再決定 lag。raw MDD 不可跨不同曝險比較（scale artifact）；正 exposure-matched gap 仍需對照 phase-randomization null。QLIKE 用 actual/predicted；套件限制 ≠ 模型無效。**完整硬規則見 `.claude/rules/experiments.md` §Methodology 硬規則。**
128-**機械 owner**：`scripts/experiment_gates.py run`（自檢 / compute queue）+ `scripts/experiment_gates.py certify`（worktree merge 的 stdlib-only MDD 硬 gate）+ `scripts/tests/test_dm_hac_lag_ratchet.py` + `scripts/tests/test_mdd_scale_artifact_ratchet.py` + `audit_dm_hac_lag.py` / `audit_mdd_scale_artifact.py`（凍結 baseline 只准變少）。
129-**代表 incident**：
130-- 2026-07-15 **K841 方法修復**：local `range(h)` 在 h=1 只留下 gamma0，七格策略平方報酬風險 DM 都是 iid；重建舊 returns 後用 canonical Bartlett-HAC lag=13，七格 t 全變但 `|t|>3` 分類未翻。完整重跑另修正開盤才知道的權重誤套隔夜 gap、每晚平倉再開倉卻只在 ratio 改變時計成本、S5 漏 stock cost、Monday 檔漏 Saturday-AM。舊「S1 最佳」及「夜盤避險普遍不可行」因此撤回/收窄；`feed×5 + knowledge×2` 實為兩篇文章與同一筆 knowledge 的字串命中。稽核器已補 `range(h)` regression 並退休此站點。
--
133-- 2026-07-14 **K1709** 重犯 K1701 教訓：ratchet 抓得到，但它在 worktree 裡沒牙齒 — Q3
134-- 2026-07-15 **MDD class 交件機制補洞**：K1695 招牌 drawdown protection 是 exposure artifact：raw ΔMDD +12.61pp（13/13 市場為正）在同曝險口徑下變 **−0.87pp（只剩 7/13）**；`compare_max_drawdown` 對 13/13 市場亮 `exposure_mismatch`（vol ratio 0.61–0.68，遠超 20% 門檻），`k1695_results.json` 卻無任何 exposure 欄位。時間線訂正：K1695 commit `a20099d99`（7/12 14:45）早於 auditor/baseline `a3858edbe`（7/13 08:17）與 runner gate `1f6097af4`（7/14 13:20），故交件當時不存在「audit 抓得到卻沒跑」；隔日 sweep 才找到 k1695.py 5 個 production `RAW_COMPARISON`，並凍入 legacy baseline。後續真正的 enforcement gap 是 merge `certify` 只驗 review SHA，不跑 MDD gate；現已補上 trusted-main merge gate。數值證據：`storage/ops/k1695_exposure_artifact_verification.md`（文末原 certification 狀態已訂正）；完整根因：`docs/governance/2026-07/mdd_merge_certification_gate.md`。連帶 paper `vt-trend-following` Table 5 + 第三項 contribution 暫緩。
135-  - **2026-07-15 05:30 hourly-05 class sweep 補記 —— 這個 artifact 已經流到讀者端，不只卡在實驗與論文**：feed 有 3 篇 published + 2 篇 archived 文章的結論建立在 raw 口徑上（`mile_0d595dfb`「13 個國際市場實測：美國 VIX 是全球股票的通用避險信號嗎？」整篇、`mile_2d4edb65`、`mile_ee473d5a`）。**數字本身沒造假（raw ΔMDD 確實 13/13 為正），被推翻的是「這是抗跌保護」的因果解讀** —— 這正是 scale artifact 最陰險的地方：它不會讓 audit 抓到假數字，它讓真數字撐起假結論，於是機械 gate（掃 code）永遠掃不到已經發出去的散文。教訓：**MDD class 的 blast radius 必須從 code 一路掃到 feed，不能只掃 `experiments/**`**。paper hold 寫進 `storage/paper_pipeline_status.json` 的 `awaiting_correction`（vt-trend-following）；文章回溯更正 = task `feed_correction_k1695_exposure_artifact`（P1，blocked 等認證，因為沒 null 分佈前只能說「約等於零」不能說「顯著為負」）。
136:  - **2026-07-15 07:15 hourly-07 collect_completed 收尾（closure）**：rerun 補上 circular-shift/phase-randomized null（common p=0.559、inception p=0.212 均未拒絕、Holm 0/13）+ no-timing 常數減碼 reference（複製 59–85% raw gap、matched gap ~0），commit `bdf6b451f`。主線程獨立重算兩樣本 byte 對齊；fresh-context code-reviewer 判 PASS（7/7 checklist 無 blocking defect）→ `experiments/k1695/review_verdict.json`（PASS，pin 現行 sha）+ certify PASS。knowledge append 更正條目 `8f80b2ee`（撤回舊 PASS `f4a73c83`）。paper 決定＝**撤除第三 contribution**（非把 null 包裝成 finding），routed to `paper_body_vt_trend_withdraw_k1695_contribution`。`feed_correction_k1695_exposure_artifact` 認證後已解除 blocked→pending P1。primary-path Codex re-verify 已 enqueue（`agent-brief_k1695_codex_reverify-be9cd6`）作 belt-and-suspenders。**流程觀察**：knowledge store append-only、無 in-place retract CLI，舊 PASS 條目仍在庫（靠 correction 條目 + `content_correction_scanner` 覆蓋）——若日後同類撤回頻繁，值得補 supersede 機制。
137-  - **2026-07-15 09:xx hourly-09 reader-facing 回溯更正完成（closure）**：`feed_correction_k1695_exposure_artifact` 執行完畢。3 篇 published（`mile_0d595dfb` 招牌篇、`mile_2d4edb65`、`mile_ee473d5a` VT 完全指南）於 feed.json `content` 前置「編者更正聲明」——保留原數字未刪，明寫舊結論被推翻＋推翻理由（曝險假象：VT 實現波動 0.61–0.68× B&H，同曝險口徑平均 ΔMDD −0.87pp/7-of-13、null p=0.559，一個固定減碼策略即複製 85%）；嚴守強度邊界（不寫「擇時有害」、不宣稱 inception +4.96pp 被否證）。2 篇 archived（`mile_f2e26f43`/`mile_9eaadbd1`）加「更正註記」。anti_ai_gate PASS；`storage/reports/<id>.json`（存在的 2 檔）同步；`supabase_sync full` 推平台（5 篇皆入 sync log、reconcile no_drift 1810=1810）。blast radius 從 code→paper→feed 全數收口。
138-- 2026-07-12 DM helper 在 h=1 退化成 iid，K565 的 Harvey PASS 被推翻 — Q3
139-- 2026-07-13 K1702 把 MDD/vol 比率誤當尺度不變，原 Codex gate 因此失效 — Q3

exec
/bin/zsh -lc "uv run python - <<'PY'
import importlib.util
from pathlib import Path
import pandas as pd
p=Path('experiments/k1732'); spec=importlib.util.spec_from_file_location('k',p/'k1732.py'); k=importlib.util.module_from_spec(spec);spec.loader.exec_module(k)
m=pd.read_csv(p/'k1732_metrics_weekly.csv',index_col=0,parse_dates=True); w=m['ret']
from scipy.stats import kurtosis,skew
sp=w.rolling(k.WINDOW).apply(lambda x: skew(x,bias=True),raw=True)
kp=w.rolling(k.WINDOW).apply(lambda x: kurtosis(x,bias=True,fisher=True),raw=True)
sig=m['sigma']; bsp=-sig*((1/6)*(k.Z**2-1)-(1/18)*(2*k.Z**3-5*k.Z)*sp); bkp=-sig*((1/24)*(k.Z**3-3*k.Z)); z=(k.Z+(1/6)*(k.Z**2-1)*sp+(1/24)*(k.Z**3-3*k.Z)*kp-(1/36)*(2*k.Z**3-5*k.Z)*sp**2)
isk=(bkp*kp.diff()).abs()/((bsp*sp.diff()).abs()+(bkp*kp.diff()).abs()+((-z)*sig.diff()).abs())
stp=k.cross_state(isk); stb=k.cross_state(m['IS_k'])
valid=stp['gap'].notna() & stb['gap'].notna()
print('total rows',len(m),'both valid gap',valid.sum(),'first valid base',stb.index[stb.gap.notna()][0],'pop',stp.index[stp.gap.notna()][0])
print('diff valid',((stp.active"'!=stb.active)&valid).sum(),'"'diff all',(stp.active"'!=stb.active).sum())
PY
python -m py_compile experiments/k1732/k1732.py experiments/k1732/k1732_figures.py
jq -e . experiments/k1732/k1732_results.json >/dev/null' in /Users/yhlai0911/volpred-research
 succeeded in 3044ms:
total rows 1494 both valid gap 1439 first valid base 1998-08-07 00:00:00 pop 1998-08-07 00:00:00
diff valid 5 diff all 5

exec
/bin/zsh -lc 'git status --short -- experiments/k1732 && find experiments/k1732/__pycache__ -maxdepth 1 -type f -print 2>/dev/null' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
?? experiments/k1732/
experiments/k1732/__pycache__/k1732_figures.cpython-39.pyc
experiments/k1732/__pycache__/k1732.cpython-39.pyc
experiments/k1732/__pycache__/k1732.cpython-312.pyc

exec
/bin/zsh -lc "stat -f '%N %Sm' -t '%Y-%m-%d %H:%M:%S' experiments/k1732/__pycache__/*.pyc
stat -f '%N %Sm' -t '%Y-%m-%d %H:%M:%S' experiments/k1732/k1732.py experiments/k1732/k1732_figures.py" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
experiments/k1732/__pycache__/k1732_figures.cpython-39.pyc 2026-07-19 10:42:15
experiments/k1732/__pycache__/k1732.cpython-312.pyc 2026-07-19 10:41:16
experiments/k1732/__pycache__/k1732.cpython-39.pyc 2026-07-19 10:42:15
experiments/k1732/k1732.py 2026-07-19 10:36:53
experiments/k1732/k1732_figures.py 2026-07-19 10:39:20

exec
/bin/zsh -lc 'rm experiments/k1732/__pycache__/k1732.cpython-312.pyc experiments/k1732/__pycache__/k1732.cpython-39.pyc experiments/k1732/__pycache__/k1732_figures.cpython-39.pyc && rmdir experiments/k1732/__pycache__' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
exec
/bin/zsh -lc "ls -lT experiments/k1732/k1732_fig*.png 2>/dev/null || true
rg -n \"13%|唯一|增量資訊|無差異|內生|外生|显著|顯著|0\\.0025|1514|1,514|28 次崩跌|24 次|單調\" experiments/k1732/README.md experiments/k1732/k1732.py experiments/k1732/k1732_figures.py experiments/k1732/k1732_results.json" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
-rw-r--r--@ 1 yhlai0911  staff  206323 Jul 19 10:39:31 2026 experiments/k1732/k1732_fig1_case2026.png
-rw-r--r--@ 1 yhlai0911  staff  121582 Jul 19 10:39:31 2026 experiments/k1732/k1732_fig2_backtest.png
-rw-r--r--@ 1 yhlai0911  staff  117703 Jul 19 10:39:32 2026 experiments/k1732/k1732_fig3_history.png
experiments/k1732/README.md:15:相關 K / 知識庫：K836（台股 1% VaR 8 法比較，CF-VaR 唯一達標）、knowledge `a8c740e9`/`589692f0`
experiments/k1732/README.md:27:  **28** 次（robustness 24 次）進入逐事件評估
experiments/k1732/README.md:38:  為 0.0376/0.2843 ≈ 13%/每單位偏態，本樣本偏態範圍 [−2.79, +1.81] 對應相對調變 −36.9% ~ +23.9%
experiments/k1732/README.md:61:7/03 +0.0010，**7/10（t−1）小幅回彈至 +0.0023**，7/17 翻負 −0.0042 — 大致收斂但非嚴格單調，
experiments/k1732/README.md:67:1. **三個單變量檢驗中，IS_k 是唯一估計為正且 CI 排除 0 的訊號**：警戒中未來 13 週崩跌起點機率
experiments/k1732/README.md:68:   17.2%→32.3%（circular-shift 單尾 p=0.0138；×3 訊號 Bonferroni 校正後 0.041，5% 水準下顯著；
experiments/k1732/README.md:71:   也未估計聯合模型，「IS_k 顯著而 β 不顯著」不等於「兩者差異顯著」；危機類型機制（內生 vs 外生）
experiments/k1732/k1732.py:249:                     "偏態僅提供 ~13% 調變。IS_k 才是higher-moment specific 訊號。"),
experiments/k1732/k1732_results.json:61:  "note": "beta_k = -sigma*(1/24)(z^3-3z) 是 sigma 的線性變換 → beta_k 死亡交叉『恆等於』sigma 上升趨勢交叉；beta_s = -sigma*(0.2843+0.0376*skew) 近似同理。此為 mechanical 結果：beta 訊號在本質上是波動率趨勢訊號，偏態僅提供 ~13% 調變。IS_k 才是higher-moment specific 訊號。",
experiments/k1732/k1732_figures.py:97:axa.annotate("β：無差異", xy=(0, 0.30), fontsize=9, ha="center", color="#666")
experiments/k1732/k1732_figures.py:110:axb.annotate("命中≈占比\n= 沒有增量資訊", xy=(0, 0.56), fontsize=9, ha="center", color="#666")

exec
/bin/zsh -lc "uv run python - <<'PY'
import pandas as pd
from scipy.stats import norm
m=pd.read_csv('experiments/k1732/k1732_metrics_weekly.csv',index_col=0,parse_dates=True)
z=norm.ppf(.05); relcoef=((1/18)*(2*z**3-5*z))/((1/6)*(z**2-1))
# beta_s=-sigma*(constant - signedterm*skew); use direct bracket relative to bracket at skew=0
const=(1/6)*(z**2-1); slope=-(1/18)*(2*z**3-5*z)
rel=(slope*m.skew/const)
print('skew range',m.skew.min(),m.skew.max(),'relative modulation range',rel.min(),rel.max(),'corr',m.beta_s.corr(-m.sigma),'const',const,'slope',slope)
PY" in /Users/yhlai0911/volpred-research
 exited 1 in 915ms:
Traceback (most recent call last):
  File "<stdin>", line 7, in <module>
TypeError: unsupported operand type(s) for *: 'float' and 'method'

exec
/bin/zsh -lc "uv run python - <<'PY'
import pandas as pd
from scipy.stats import norm
m=pd.read_csv('experiments/k1732/k1732_metrics_weekly.csv',index_col=0,parse_dates=True)
z=norm.ppf(.05); const=(1/6)*(z**2-1); slope=-(1/18)*(2*z**3-5*z)
rel=slope*m['skew']/const
print('skew range',m['skew'].min(),m['skew'].max(),'relative modulation range',rel.min(),rel.max(),'corr',m['beta_s'].corr(-m['sigma']),'const',const,'slope',slope)
PY" in /Users/yhlai0911/volpred-research
 succeeded in 976ms:
skew range -2.7885557690442635 1.8091599338019837 relative modulation range -0.3685158686630954 0.2390858206805773 corr 0.9714500409882935 const 0.28425724234923583 slope 0.037565432884997425

codex
1. **FIXED** — `cross_state` 已改採嚴格交叉定義，warmup 首個負 gap 不再誤算；IS_k 為 71 次交叉、precision 0.4507。[k1732.py:91](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:91)、[k1732_results.json:478](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:478)

2. **FIXED** — 已新增 B=5000 circular-shift randomization、限制 circular distance、採單尾 `(r+1)/(B+1)`。用保存序列獨立重算得到 p=0.0138；Bonferroni ×3=0.0414，README 已降為 5% 顯著。[k1732.py:181](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:181)、[README.md:33](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:33)、[k1732_results.json:492](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:492)

3. **NOT FIXED** — README 主文已正確限縮為「三個單變量檢驗中唯一估計為正且 CI 排除 0」，並揭露未做直接差異檢定、聯合模型及機制識別；但圖 2 仍直接宣稱「β：無差異」及「沒有增量資訊」。這仍把未拒絕虛無假設寫成等價／無增量的確定結論。[README.md:67](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:67)、[k1732_figures.py:97](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:97)、[k1732_figures.py:110](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:110)

4. **FIXED** — 樣本與事件口徑已同步為 1,494 週、primary 30 次／可評估 28 次、alternative 26 次／可評估 24 次；圖 2、圖 3 標題亦一致。[README.md:11](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:11)、[README.md:26](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:26)、[k1732_figures.py:115](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:115)、[k1732_figures.py:131](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:131)

5. **FIXED** — README 已揭露 7/10 t−1 gap 回彈至 +0.0023，明確判定此次 IS_k 不構成有效提早預警；圖 1 註解同步更正。[README.md:59](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:59)、[k1732_figures.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:63)、[k1732_results.json:897](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:897)

6. **FIXED** — 無理由的 `df.iloc[:-1]` 已移除；reverse rolling + `shift(-1)` 後直接使用完整可評估資料。[k1732.py:160](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:160)

7. **NEW ISSUE** — estimator sensitivity 的核心結果正確：71 vs 71 次、6 個交叉日期、5 個警戒週不同。但 `both` 對已轉成 Boolean 的 `active` 欄位執行 `dropna()`，無法排除 warmup，因而把 `n_weeks_compared` 寫成 1,494；實際兩套 gap 均有效的比較期是 1,439 週。5 個差異週本身不受影響，但 README 的分母口徑誤導。[k1732.py:297](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:297)、[k1732.py:306](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:306)、[README.md:56](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:56)、[k1732_results.json:913](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:913)

8. **NOT FIXED** — README 已正確呈現 corr=0.9715、每單位偏態係數比及樣本調變範圍 −36.9%～+23.9%；但主腳本生成的 mechanical-equivalence note 與結果 JSON 仍保留不精確的「偏態僅提供 ~13% 調變」。[README.md:36](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:36)、[k1732.py:246](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:246)、[k1732_results.json:61](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:61)

VERDICT: CONDITIONAL PASS
tokens used
89,071
1. **FIXED** — `cross_state` 已改採嚴格交叉定義，warmup 首個負 gap 不再誤算；IS_k 為 71 次交叉、precision 0.4507。[k1732.py:91](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:91)、[k1732_results.json:478](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:478)

2. **FIXED** — 已新增 B=5000 circular-shift randomization、限制 circular distance、採單尾 `(r+1)/(B+1)`。用保存序列獨立重算得到 p=0.0138；Bonferroni ×3=0.0414，README 已降為 5% 顯著。[k1732.py:181](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:181)、[README.md:33](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:33)、[k1732_results.json:492](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:492)

3. **NOT FIXED** — README 主文已正確限縮為「三個單變量檢驗中唯一估計為正且 CI 排除 0」，並揭露未做直接差異檢定、聯合模型及機制識別；但圖 2 仍直接宣稱「β：無差異」及「沒有增量資訊」。這仍把未拒絕虛無假設寫成等價／無增量的確定結論。[README.md:67](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:67)、[k1732_figures.py:97](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:97)、[k1732_figures.py:110](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:110)

4. **FIXED** — 樣本與事件口徑已同步為 1,494 週、primary 30 次／可評估 28 次、alternative 26 次／可評估 24 次；圖 2、圖 3 標題亦一致。[README.md:11](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:11)、[README.md:26](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:26)、[k1732_figures.py:115](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:115)、[k1732_figures.py:131](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:131)

5. **FIXED** — README 已揭露 7/10 t−1 gap 回彈至 +0.0023，明確判定此次 IS_k 不構成有效提早預警；圖 1 註解同步更正。[README.md:59](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:59)、[k1732_figures.py:63](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_figures.py:63)、[k1732_results.json:897](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:897)

6. **FIXED** — 無理由的 `df.iloc[:-1]` 已移除；reverse rolling + `shift(-1)` 後直接使用完整可評估資料。[k1732.py:160](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:160)

7. **NEW ISSUE** — estimator sensitivity 的核心結果正確：71 vs 71 次、6 個交叉日期、5 個警戒週不同。但 `both` 對已轉成 Boolean 的 `active` 欄位執行 `dropna()`，無法排除 warmup，因而把 `n_weeks_compared` 寫成 1,494；實際兩套 gap 均有效的比較期是 1,439 週。5 個差異週本身不受影響，但 README 的分母口徑誤導。[k1732.py:297](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:297)、[k1732.py:306](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:306)、[README.md:56](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:56)、[k1732_results.json:913](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:913)

8. **NOT FIXED** — README 已正確呈現 corr=0.9715、每單位偏態係數比及樣本調變範圍 −36.9%～+23.9%；但主腳本生成的 mechanical-equivalence note 與結果 JSON 仍保留不精確的「偏態僅提供 ~13% 調變」。[README.md:36](/Users/yhlai0911/volpred-research/experiments/k1732/README.md:36)、[k1732.py:246](/Users/yhlai0911/volpred-research/experiments/k1732/k1732.py:246)、[k1732_results.json:61](/Users/yhlai0911/volpred-research/experiments/k1732/k1732_results.json:61)

VERDICT: CONDITIONAL PASS
