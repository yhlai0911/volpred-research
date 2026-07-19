OpenAI Codex v0.144.1
--------
workdir: /Users/yhlai0911/volpred-research
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019f7975-0d36-77d3-9b16-20f8155c2e84
--------
user
你是嚴格的計量金融代碼審查者。三審 K528 NFP 事件研究修正案。

**審查對象**（絕對路徑 `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/`）：

實驗目錄 `experiments/k528/`：
- `README.md`（宣稱面）
- `k528_nfp_event_study.py`（主腳本）
- `k528_nfp_event_study_results.json`（現行結果）
- `k528_nfp_event_study_results_PROXY_SUPERSEDED.json`（proxy 時代存證）
- `k528_nfp_official_dates_results.json`（前後對照 audit + 文章更正計畫）
- `build_article_correction.py`（文章 mile_35eef830 的更正清單）
- `codex_review_v2.md` + `review_verdict.json`（**你上一輪的 FAIL 裁決，本輪要驗收它**）

共用模組與測試：
- `src/volpred/data/event_dates.py`（官方日曆 accessor，根修）
- `tests/test_event_dates_real_raw_response.py`（新增）
- `tests/test_event_dates_release_selection.py`
- `tests/test_nfp_official_release_dates.py`
- `tests/fixtures/fred_release_50_nfp_raw_20260719.json`（新增，ALFRED 原始回應）

**背景**：你在二審（`codex_review_v2.md`）判 FAIL，列三條 blocking defects 與 findings 3-8。
本輪是針對那些 issue 的 remediation。commit `6fd281901`。

**本輪聲稱做了什麼**（逐條驗收，不要照單全收）：

1. **BLOCKER 1（accessor 取 max() 選錯六個日期）** — 聲稱根修在 main commit `305d118a3`，
   改為 per-month `min()` + 13–110 天 cadence fail-closed 驗證；branch 已 rebase 帶入。
   聲稱六個月份以 live ALFRED 驗證正確：2006-05-05 / 2012-12-07 / 2013-05-03 /
   2020-05-08 / 2024-01-05 / 2024-08-02。

2. **BLOCKER 2（顯著性翻轉不成立）** — 聲稱確認你是對的：翻轉不成立。舊口徑重算得
   1.1779×、p=0.02488（與你二審預算一致）；新口徑（週五對週五）為 1.190×、p=0.0202。
   原 18 條文章更正**全數作廢**，改為 19 條純數值重述、0 條方向翻轉。

3. **BLOCKER 3 / finding 4（fail-closed 不完整）** — 聲稱補了 `check_calendar_is_complete`
   （同月多筆 raise、樣本窗內缺月 raise，2025-10 政府關門列 `KNOWN_MISSING_MONTHS`）
   與事件日→交易日一對一斷言（找不到 session raise、兩發布日撞同 session raise）。

4. **finding 5（Friday baseline estimand）** — 聲稱改為「237 場週五 NFP vs 非 NFP 週五」，
   兩邊星期別一致；未採 weekday-matched controls 的理由寫在 README；舊口徑以
   `B_diagnostic_mixed_weekday` 保留並標 DIAGNOSTIC ONLY。

5. **finding 6（方向性敘述超過證據）** — 聲稱移除 "insignificant across all tests"，
   每個顯著性陳述綁定自己的檢定。

6. **finding 7（原子寫入 / dry-run）** — 聲稱主結果與 audit 改 temp+fsync+`os.replace`；
   builder dry-run 改為真的不寫。

7. **finding 8（superseded metadata）** — 聲稱 archive JSON 本體加了
   `superseded` / `do_not_cite` / 撤回原因。

8. **迴歸測試** — 聲稱新增用真實 raw-response 語義（同月多筆）的 regression test，
   並附 mutation 檢查；聲稱實測 `min()`→`max()` 會轉紅。

**審查重點（請獨立驗算，不要只讀 diff）**：

1. 六個問題月份是否真的修正（自己跑 accessor 或讀 fixture 核對）
2. 統計量是否可獨立重現：特別是 1.190×/p=0.0202（新口徑）與 1.1779×/p=0.02488（舊口徑）
3. **estimand 選擇是否誠實且一致**：限定週五是否有把樣本選擇偏誤引進來？
   `B_diagnostic_mixed_weekday` 有沒有被誤用成 headline？audit 的 before/after 對照
   是否拿了不同口徑硬比（`before` 是舊口徑、`after` 是新口徑，這樣比公平嗎？
   README 有沒有講清楚）？
4. 19 條文章更正是否逐條與新 results 對齊（抽查至少 8 條）；作廢 18 條的理由是否成立；
   有沒有殘留任何方向翻轉
5. fail-closed 是否真的關上（試著想出能繞過 `check_calendar_is_complete` 的輸入）；
   `KNOWN_MISSING_MONTHS` 是不是被拿來讓檢查通過的後門
6. 新測試是否**真的**測得到 bug（fixture 有沒有被動過手腳、mutation 檢查是否 vacuous）
7. lookahead / seed / 原子寫入等標準防錯
8. README 宣稱面與 artifact 是否一致（有沒有 overclaim）

**特別注意**：本輪 agent 有動機把結果導向「已修好」。請主動找它可能自我欺騙的地方。
若發現新的 blocking defect，照列不誤；若確認修好了，也請明說哪幾條已驗收。

**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出
`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 須列 blocking defects）。

codex
我會把二審裁決當作驗收規格，但不採信本輪摘要：先讀統一 handoff 與舊裁決，再核對 commit/diff、fixture 原始語義，最後用獨立計算與 mutation/邊界案例重跑。全程只讀，不改工作樹。
  → 讀 handoff、二審裁決與本輪 commit/diff，建立逐項驗收表
  • 審查 accessor、fixture、fail-closed 與測試，做 mutation/繞過驗證
  • 獨立重算新舊 estimand 統計量並核對事件日期
  • 核對 README、results、audit、19 條文章更正與 superseded metadata
  • 彙整逐點 findings、blocking defects 與最終 verdict
exec
/bin/zsh -lc "sed -n '1,240p' storage/ops/handoff_latest.md
pwd
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short --branch
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show --stat --oneline --decorate --no-renames 6fd281901
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff --stat 6fd281901"'^ 6fd281901' in /Users/yhlai0911/volpred-research
 succeeded in 205ms:
## k528-nfp-official-dates
6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
 experiments/k528/README.md                         |  188 +-
 experiments/k528/build_article_correction.py       |  170 +-
 experiments/k528/codex_review_v2.md                | 5028 ++++++++++++++++++++
 experiments/k528/k528_nfp_event_study.py           |  338 +-
 experiments/k528/k528_nfp_event_study_results.json | 2698 +++++------
 ...8_nfp_event_study_results_PROXY_SUPERSEDED.json |   13 +
 .../k528/k528_nfp_official_dates_results.json      |  153 +-
 experiments/k528/review_verdict.json               |   20 +
 .../fixtures/fred_release_50_nfp_raw_20260719.json |  278 ++
 tests/test_event_dates_real_raw_response.py        |  106 +
 tests/test_nfp_official_release_dates.py           |   40 +-
 11 files changed, 7461 insertions(+), 1571 deletions(-)
 experiments/k528/README.md                         |  188 +-
 experiments/k528/build_article_correction.py       |  170 +-
 experiments/k528/codex_review_v2.md                | 5028 ++++++++++++++++++++
 experiments/k528/k528_nfp_event_study.py           |  338 +-
 experiments/k528/k528_nfp_event_study_results.json | 2698 +++++------
 ...8_nfp_event_study_results_PROXY_SUPERSEDED.json |   13 +
 .../k528/k528_nfp_official_dates_results.json      |  153 +-
 experiments/k528/review_verdict.json               |   20 +
 .../fixtures/fred_release_50_nfp_raw_20260719.json |  278 ++
 tests/test_event_dates_real_raw_response.py        |  106 +
 tests/test_nfp_official_release_dates.py           |   40 +-
 11 files changed, 7461 insertions(+), 1571 deletions(-)

codex
初步確認 worktree 乾淨、HEAD 是指定 commit。接下來我先鎖定實作與 artifact schema；二審檔異常膨脹到約 5,000 行，我只取其正式 findings/verdict 區段，不把工具輸出雜訊當審查內容。
exec
/bin/zsh -lc "git log --oneline --decorate -12
git merge-base --is-ancestor 305d118a3 HEAD; printf 'ancestor_exit=%s\\n' \""'$?"
rg -n "BLOCKER|Finding|VERDICT|FAIL|CONDITIONAL|PASS" experiments/k528/codex_review_v2.md experiments/k528/review_verdict.json | tail -n 120
rg -n "def |KNOWN_MISSING|check_calendar|release|month|min'"\\(|max\\(|cadence|13|110|replace|fsync|dry.run|Friday|DIAGNOSTIC|headline|superseded|do_not_cite\" src/volpred/data/event_dates.py experiments/k528/k528_nfp_event_study.py experiments/k528/build_article_correction.py experiments/k528/README.md tests/test_event_dates_real_raw_response.py tests/test_event_dates_release_selection.py tests/test_nfp_official_release_dates.py" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
e42dc25ad fix(k528): NFP 事件日改用官方日曆重跑，1 項顯著性翻轉
50bb24870 (origin/main, origin/HEAD) dispatch(15:22): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(2)
28a14f7c7 [codex] queue BMA remediation reruns
1af0e3fbf [codex] guard BMA invalid model posterior
363cae2a2 [codex] detect nested DM coefficient masks
ae815f3e5 [codex] fix worktree-owned orphan outputs
cb97c0b7f [codex] serialize compute retry and triage ownership
175b3b67c [codex] fail snapaudit incomplete coverage review
f0350b912 (k741-nfp-canonical) dispatch(14:42): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(8)、scripts(1)、scripts/tests/(1) 等 5 處
20ffdc4a3 ci-fix(2): event_dates use_cache=False now bypasses cache WRITE too + guard_canonical_write before cache write; sandbox fixture in selection tests (repo-state guard leak)
3cb072b83 firstfriday sweep: 8 archived-experiment README warnings + sweep report (9 sites, k741->volatility-absorption paper NFP table contamination documented)
ancestor_exit=0
experiments/k528/review_verdict.json:3:  "verdict": "FAIL",
experiments/k528/codex_review_v2.md:31:**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出 `VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 列 blocking defects）。
experiments/k528/codex_review_v2.md:73:- `k1708_fix_verdict_gate_20260717` P2 [experiment] [experiment] K1708 修正 stage：verdict gate 假陽性 + CW nesting/gate 替換三個 BLOCKER — claimed_by=hourly-slot-1-858545f95a864e298ddb4bc144a8c615
experiments/k528/codex_review_v2.md:76:- `assign_5aa9d5f5` P2 [experiment] K1623 修復：撤回 long-memory 識別宣稱 + 補 MSE DM 與多重比較（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
experiments/k528/codex_review_v2.md:77:- `assign_42306eaa` P2 [experiment] K1698 重跑：修 contract-selection lookahead + 夜盤邊界空驗證 + equivalence 檢定（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
experiments/k528/codex_review_v2.md:78:- `k1731_armB_rev7_remediation` P1 [experiment] K1731 arm B rev7 bounded remediation（Codex rev6 FAIL：B1a/B1b/B5/nested-DM detector）
experiments/k528/codex_review_v2.md:223:**目前只有 1 篇真正 ready**：`leverage-direction`(JBF) — 6/11 技術定稿、合規只差 body.tex:231 一個 VolPred footnote（fix 在 audit json）。`vt-trend-following`(JPM/FAJ) 下一棒（6/30 才 v7 PASS + 10 個 K-id tags 待清）。
experiments/k528/codex_review_v2.md:275:5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。
experiments/k528/codex_review_v2.md:327:80-**規則**：worktree agent 只產 `experiments/kXXX/`，禁改共享狀態；主線程用 `scripts/merge_worktree.sh` 合併，**禁 `git worktree remove --force`**（L1 hook 擋）。實驗進 main 的唯一門票 = `experiments/<kid>/review_verdict.json` 且 sha256 綁「現在這份 bytes」（PASS 後又改 code 也擋）。裁決檔一律由 `verdict-template` 產生，不手抄。**保留 branch ≠ 收割成果**：clean tree 只證明沒有未提交檔案，不證明那些 commits 進了 main；移除 unmerged checkout 就是在製造下一個殭屍。**任務引用的資源會消失，必須有東西去 reconcile**——否則任務永遠 blocked 又永遠不關單。
experiments/k528/codex_review_v2.md:371:136-  - **2026-07-15 07:15 hourly-07 collect_completed 收尾（closure）**：rerun 補上 circular-shift/phase-randomized null（common p=0.559、inception p=0.212 均未拒絕、Holm 0/13）+ no-timing 常數減碼 reference（複製 59–85% raw gap、matched gap ~0），commit `bdf6b451f`。主線程獨立重算兩樣本 byte 對齊；fresh-context code-reviewer 判 PASS（7/7 checklist 無 blocking defect）→ `experiments/k1695/review_verdict.json`（PASS，pin 現行 sha）+ certify PASS。knowledge append 更正條目 `8f80b2ee`（撤回舊 PASS `f4a73c83`）。paper 決定＝**撤除第三 contribution**（非把 null 包裝成 finding），routed to `paper_body_vt_trend_withdraw_k1695_contribution`。`feed_correction_k1695_exposure_artifact` 認證後已解除 blocked→pending P1。primary-path Codex re-verify 已 enqueue（`agent-brief_k1695_codex_reverify-be9cd6`）作 belt-and-suspenders。**流程觀察**：knowledge store append-only、無 in-place retract CLI，舊 PASS 條目仍在庫（靠 correction 條目 + `content_correction_scanner` 覆蓋）——若日後同類撤回頻繁，值得補 supersede 機制。
experiments/k528/codex_review_v2.md:372:137-  - **2026-07-15 09:xx hourly-09 reader-facing 回溯更正完成（closure）**：`feed_correction_k1695_exposure_artifact` 執行完畢。3 篇 published（`mile_0d595dfb` 招牌篇、`mile_2d4edb65`、`mile_ee473d5a` VT 完全指南）於 feed.json `content` 前置「編者更正聲明」——保留原數字未刪，明寫舊結論被推翻＋推翻理由（曝險假象：VT 實現波動 0.61–0.68× B&H，同曝險口徑平均 ΔMDD −0.87pp/7-of-13、null p=0.559，一個固定減碼策略即複製 85%）；嚴守強度邊界（不寫「擇時有害」、不宣稱 inception +4.96pp 被否證）。2 篇 archived（`mile_f2e26f43`/`mile_9eaadbd1`）加「更正註記」。anti_ai_gate PASS；`storage/reports/<id>.json`（存在的 2 檔）同步；`supabase_sync full` 推平台（5 篇皆入 sync log、reconcile no_drift 1810=1810）。blast radius 從 code→paper→feed 全數收口。
experiments/k528/codex_review_v2.md:373:138:- 2026-07-12 DM helper 在 h=1 退化成 iid，K565 的 Harvey PASS 被推翻 — Q3
experiments/k528/codex_review_v2.md:398:214-- 2026-07-16 **3-STRIKE 級結構修復（老闆直接下令「該單一關口的就單一關口」）**：`volpred ops assign` 寫入的 `storage/ops/tasks/` queue **無任何 dispatcher 消費**（唯一 reader=手動 claim-next，無人跑）→ 16 任務黑洞 5 天，含結論已推翻仍在排隊的 K1695 舊敘事文章（執行=發錯誤內容）；同晚兩個並行互動 session 對老闆同一則 Telegram（msg877）**矛盾雙回覆**（msg879 排 credit→vol 研究 vs msg880 判 aggregate 版全 NULL），本 session 亦違反 claim-first（先做事先回覆最後才 claim）。**修**：(a) assign 重定向為 next_tasks.json thin wrapper（`append_next_task`，flock）；(b) 存量 17 個非終態 triage（4 終態含 1 deprecated 有害任務 + 13 遷入 canonical queue，credit 題合併雙方判斷成單一 brief）；(c) reply-right guard：`telegram-send --reply-to-task` 對已完成/他人持有任務拒發（break-then-verify 過）；(d) 機械 gate `scripts/tests/test_ops_tasks_receipts_only.py`（先 FAIL 於存量、遷移後轉綠，證明會咬）。設計：`docs/refactor_plan_single_gateway_task_system.md` — Q3
experiments/k528/codex_review_v2.md:616:    31	the dates now come from the official release calendar and the run FAILS CLOSED
experiments/k528/codex_review_v2.md:4378:     3	  "verdict": "FILL: PASS or FAIL — anything but PASS blocks the merge",
experiments/k528/codex_review_v2.md:4384:     9	    "FILL: one entry per defect that makes this a FAIL; [] if PASS"
experiments/k528/codex_review_v2.md:4985:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
experiments/k528/codex_review_v2.md:4987:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
experiments/k528/codex_review_v2.md:5005:VERDICT: FAIL
experiments/k528/codex_review_v2.md:5008:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
experiments/k528/codex_review_v2.md:5010:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
experiments/k528/codex_review_v2.md:5028:VERDICT: FAIL
experiments/k528/README.md:30:`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
experiments/k528/README.md:31:release id 50），且**取不到就 raise，不回退 proxy**。
experiments/k528/README.md:35:第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
experiments/k528/README.md:37:因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：
experiments/k528/README.md:39:| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
experiments/k528/README.md:43:| 2013-05 | 2013-05-03 | 2013-05-06 |
experiments/k528/README.md:52:根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
experiments/k528/README.md:58:（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
experiments/k528/README.md:59:那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。
experiments/k528/README.md:64:- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
experiments/k528/README.md:81:標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。
experiments/k528/README.md:129:| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
experiments/k528/README.md:131:| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
experiments/k528/README.md:170:事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
experiments/k528/README.md:180:accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
experiments/k528/README.md:183:Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
experiments/k528/README.md:188:- **日曆完整性**（`check_calendar_is_complete`）：同月多筆 → raise；樣本窗內缺月 → raise。
experiments/k528/README.md:190:  條目），寫在 `KNOWN_MISSING_MONTHS` 並附理由 —— 這個清單是用來記錄真實缺口的，
experiments/k528/README.md:195:- **原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`
experiments/k528/README.md:201:- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
experiments/k528/README.md:202:- K513：先前的 FOMC/NFP/CPI 事件研究
tests/test_nfp_official_release_dates.py:1:"""Pin the NFP event dates that a first-Friday proxy gets wrong.
tests/test_nfp_official_release_dates.py:3:`experiments/event_article_nfp_2026_07_03_t1` used to derive its NFP release
tests/test_nfp_official_release_dates.py:4:dates from a "first Friday of the month" rule. Against the official BLS
tests/test_nfp_official_release_dates.py:5:Employment Situation calendar, 7 of its 13 historical events were on the wrong
tests/test_nfp_official_release_dates.py:6:day, and correcting them flipped the headline direction: the SPY up-day rate
tests/test_nfp_official_release_dates.py:15:returned by FRED release id 50 (Employment Situation), fetched 2026-07-19.
tests/test_nfp_official_release_dates.py:33:# Official Employment Situation release dates, FRED release id 50.
tests/test_nfp_official_release_dates.py:40:    # No October 2025 release: the shutdown cancelled it and pushed the
tests/test_nfp_official_release_dates.py:47:# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
tests/test_nfp_official_release_dates.py:67:# What the experiment must use: trailing 13 official releases before 2026-07-02.
tests/test_nfp_official_release_dates.py:68:EXPECTED_TRAILING_13 = [
tests/test_nfp_official_release_dates.py:75:def _first_friday(year: int, month: int) -> date:
tests/test_nfp_official_release_dates.py:77:    d = date(year, month, 1)
tests/test_nfp_official_release_dates.py:82:def isolate_event_date_cache(monkeypatch, tmp_path):
tests/test_nfp_official_release_dates.py:87:def official(monkeypatch):
tests/test_nfp_official_release_dates.py:91:    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
tests/test_nfp_official_release_dates.py:95:def experiment():
tests/test_nfp_official_release_dates.py:106:    def test_proxy_date_is_not_an_official_release(
tests/test_nfp_official_release_dates.py:110:            f"{proxy_date} came from the first-Friday proxy and is not an "
tests/test_nfp_official_release_dates.py:111:            "Employment Situation release date"
tests/test_nfp_official_release_dates.py:117:    def test_mismatch_really_is_what_the_proxy_would_have_produced(
tests/test_nfp_official_release_dates.py:120:        """Guard the fixture itself: each 'proxy' date must be a first Friday.
tests/test_nfp_official_release_dates.py:126:        assert _first_friday(d.year, d.month) == d.date()
tests/test_nfp_official_release_dates.py:128:    def test_october_2025_release_does_not_exist(self, official):
tests/test_nfp_official_release_dates.py:131:        No Employment Situation was published in October 2025. A monthly
tests/test_nfp_official_release_dates.py:135:        assert not [d for d in official if (d.year, d.month) == (2025, 10)]
tests/test_nfp_official_release_dates.py:138:    def test_proxy_dates_that_were_already_correct_stay_correct(
tests/test_nfp_official_release_dates.py:143:    def test_seven_of_thirteen_were_wrong(self, official):
tests/test_nfp_official_release_dates.py:144:        """The headline number from the K1442 audit, recomputed not restated."""
tests/test_nfp_official_release_dates.py:147:        while len(proxy_dates) < 13:
tests/test_nfp_official_release_dates.py:161:    def test_release_date_is_july_2_not_july_3(self, experiment):
tests/test_nfp_official_release_dates.py:162:        """July 4 fell on a Saturday, observed Friday July 3, so BLS moved up."""
tests/test_nfp_official_release_dates.py:166:    def test_build_nfp_dates_returns_the_official_trailing_thirteen(
tests/test_nfp_official_release_dates.py:174:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:175:            lambda start, end, **kw: event_dates.nfp_release_dates(
tests/test_nfp_official_release_dates.py:180:        actual = [str(d.date()) for d in experiment.build_nfp_dates(13)]
tests/test_nfp_official_release_dates.py:181:        assert actual == EXPECTED_TRAILING_13
tests/test_nfp_official_release_dates.py:183:    def test_release_date_itself_is_excluded(self, experiment, monkeypatch):
tests/test_nfp_official_release_dates.py:190:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:191:            lambda start, end, **kw: event_dates.nfp_release_dates(
tests/test_nfp_official_release_dates.py:196:        assert pd.Timestamp("2026-07-02") not in experiment.build_nfp_dates(13)
tests/test_nfp_official_release_dates.py:198:    def test_fails_closed_when_calendar_is_short(self, experiment, monkeypatch):
tests/test_nfp_official_release_dates.py:202:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:206:        with pytest.raises(RuntimeError, match="only 1 releases"):
tests/test_nfp_official_release_dates.py:207:            experiment.build_nfp_dates(13)
tests/test_nfp_official_release_dates.py:209:    def test_fails_closed_when_calendar_is_unreachable(
tests/test_nfp_official_release_dates.py:212:        def boom(*_a, **_kw):
tests/test_nfp_official_release_dates.py:215:        monkeypatch.setattr(experiment, "nfp_release_dates", boom)
tests/test_nfp_official_release_dates.py:218:            experiment.build_nfp_dates(13)
tests/test_nfp_official_release_dates.py:222:    """The download window itself must exclude the release day.
tests/test_nfp_official_release_dates.py:233:    def _capture_downloads(self, experiment, monkeypatch):
tests/test_nfp_official_release_dates.py:236:        def recorder(ticker, **kw):
tests/test_nfp_official_release_dates.py:250:            "nfp_release_dates",
tests/test_nfp_official_release_dates.py:251:            lambda start, end, **kw: event_dates.nfp_release_dates(
tests/test_nfp_official_release_dates.py:262:    def test_every_series_is_downloaded(self, experiment, monkeypatch):
tests/test_nfp_official_release_dates.py:267:    def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
tests/test_nfp_official_release_dates.py:271:            # yfinance `end` is exclusive, so end == release date means the
tests/test_nfp_official_release_dates.py:275:                "the 2026-07-02 release day must not be downloadable"
tests/test_nfp_official_release_dates.py:278:    def test_download_window_starts_before_the_earliest_event(
tests/test_nfp_official_release_dates.py:302:    def columns(self):
tests/test_nfp_official_release_dates.py:310:    def test_experiment_defines_no_first_friday_helper(self):
tests/test_nfp_official_release_dates.py:312:        assert "def first_friday" not in src
tests/test_nfp_official_release_dates.py:315:    def test_experiment_imports_the_official_calendar(self):
tests/test_nfp_official_release_dates.py:317:        assert "from volpred.data.event_dates import nfp_release_dates" in src
tests/test_nfp_official_release_dates.py:319:    def test_results_json_declares_its_event_date_source(self):
tests/test_nfp_official_release_dates.py:326:        assert results["nfp_release_date"] == "2026-07-02"
tests/test_nfp_official_release_dates.py:327:        assert "nfp_release_dates" in results["event_date_source"]
tests/test_nfp_official_release_dates.py:328:        assert [r["nfp_release_date"] for r in results["historical_nfp_table"]] == (
tests/test_nfp_official_release_dates.py:329:            EXPECTED_TRAILING_13
tests/test_nfp_official_release_dates.py:336:# The sibling experiment above had 13 events. K528 had 254 and fed six numbers
tests/test_nfp_official_release_dates.py:338:# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
tests/test_nfp_official_release_dates.py:349:def _load_k528(path):
tests/test_nfp_official_release_dates.py:355:def _k528_event_dates():
tests/test_nfp_official_release_dates.py:359:def assert_not_first_friday_proxy(dates):
tests/test_nfp_official_release_dates.py:360:    """Reject a calendar carrying the first-Friday proxy's fingerprints.
tests/test_nfp_official_release_dates.py:372:            f"all {len(dates)} releases fall on a Friday. The official calendar "
tests/test_nfp_official_release_dates.py:373:            "does not: BLS moves the release off Friday at holiday and shutdown "
tests/test_nfp_official_release_dates.py:378:        d for d in dates if d.date() == _first_friday(d.year, d.month)
tests/test_nfp_official_release_dates.py:382:            "every release sits on the first Friday of its month -- proxy calendar"
tests/test_nfp_official_release_dates.py:385:    phantom = [d for d in dates if (d.year, d.month) == (2025, 10)]
tests/test_nfp_official_release_dates.py:388:            f"calendar contains an October 2025 release ({phantom[0].date()}). "
tests/test_nfp_official_release_dates.py:394:    def test_defines_no_first_friday_helper(self):
tests/test_nfp_official_release_dates.py:396:        assert "def get_first_friday" not in src
tests/test_nfp_official_release_dates.py:397:        assert "def generate_nfp_dates" not in src
tests/test_nfp_official_release_dates.py:400:    def test_imports_the_official_calendar(self):
tests/test_nfp_official_release_dates.py:402:        assert "from volpred.data.event_dates import nfp_release_dates" in src
tests/test_nfp_official_release_dates.py:404:    def test_results_declare_the_official_source_and_no_fallback(self):
tests/test_nfp_official_release_dates.py:406:        assert "nfp_release_dates" in source["accessor"]
tests/test_nfp_official_release_dates.py:409:    def test_event_dates_carry_no_proxy_signature(self):
tests/test_nfp_official_release_dates.py:412:    def test_sample_is_not_uniformly_friday(self):
tests/test_nfp_official_release_dates.py:420:    def test_audit_records_the_dates_that_changed(self):
tests/test_nfp_official_release_dates.py:430:    def test_no_off_cycle_revision_date_is_treated_as_an_event(self):
tests/test_nfp_official_release_dates.py:433:        For six months ALFRED returns two release-id-50 entries; the later one
tests/test_nfp_official_release_dates.py:435:        An earlier rerun selected those six and moved the NFP-vs-Friday test
tests/test_nfp_official_release_dates.py:441:            "2006-05-08", "2012-12-12", "2013-05-06",
tests/test_nfp_official_release_dates.py:445:            "2006-05-05", "2012-12-07", "2013-05-03",
tests/test_nfp_official_release_dates.py:453:            f"regular releases missing from k528 event set: {sorted(regular - event_dates)}"
tests/test_nfp_official_release_dates.py:463:    def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
tests/test_nfp_official_release_dates.py:466:            last = 12 if year < end_year else end_month
tests/test_nfp_official_release_dates.py:467:            for month in range(1, last + 1):
tests/test_nfp_official_release_dates.py:468:                out.append(pd.Timestamp(_first_friday(year, month)))
tests/test_nfp_official_release_dates.py:471:    def test_the_proxy_calendar_is_rejected(self):
tests/test_nfp_official_release_dates.py:472:        with pytest.raises(AssertionError, match="Friday"):
tests/test_nfp_official_release_dates.py:475:    def test_phantom_october_2025_alone_is_enough_to_fail(self):
tests/test_nfp_official_release_dates.py:483:    def test_the_guard_accepts_the_official_calendar(self, official):
experiments/k528/build_article_correction.py:3:The article was published 2026-07-01 with headline numbers taken from K528,
experiments/k528/build_article_correction.py:4:which dated every NFP to the first Friday of the month. On the official BLS
experiments/k528/build_article_correction.py:12:months where ALFRED returns two entries, picked the LATER one -- an off-cycle
experiments/k528/build_article_correction.py:14:dates were therefore wrong (2006-05-08, 2012-12-12, 2013-05-06, 2020-05-11,
experiments/k528/build_article_correction.py:18:NFP-vs-Friday test across the 5% line. The voided list told readers that a
experiments/k528/build_article_correction.py:25:So: no claim in this article reverses direction. Every replacement below is a
experiments/k528/build_article_correction.py:30:Under the proxy every NFP landed on a Friday by construction, so "NFP days vs
experiments/k528/build_article_correction.py:31:non-NFP Fridays" held weekday fixed for free. On the official calendar 16 of
experiments/k528/build_article_correction.py:32:253 events are not Fridays, so that same comparison would put a weekday-mixed
experiments/k528/build_article_correction.py:33:event group against a pure-Friday control group and let the Friday effect leak
experiments/k528/build_article_correction.py:35:Friday releases. This is stated in the article's correction note rather than
experiments/k528/build_article_correction.py:47:every replacement against the canonical article, proving each matches exactly
experiments/k528/build_article_correction.py:93:    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
experiments/k528/build_article_correction.py:119:        "分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；"
experiments/k528/build_article_correction.py:143:        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
experiments/k528/build_article_correction.py:173:        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
experiments/k528/build_article_correction.py:194:def load_article_content(storage_dir: Path) -> str:
experiments/k528/build_article_correction.py:202:def validate(storage_dir: Path) -> list[dict]:
experiments/k528/build_article_correction.py:203:    """Resolve every replacement against the live article. Raises if any does
experiments/k528/build_article_correction.py:215:def _write_json_atomic(path: Path, payload) -> None:
experiments/k528/build_article_correction.py:222:            os.fsync(f.fileno())
experiments/k528/build_article_correction.py:223:        os.replace(tmp, path)
experiments/k528/build_article_correction.py:232:def record_plan(validated: list[dict], applied: dict | None) -> None:
experiments/k528/build_article_correction.py:237:        "n_replacements": len(REPLACEMENTS),
experiments/k528/build_article_correction.py:244:                "off-cycle ALFRED entries for six months, which pushed the "
experiments/k528/build_article_correction.py:245:                "NFP-vs-Friday test across the 5% line. It would have retracted a "
experiments/k528/build_article_correction.py:250:        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
experiments/k528/build_article_correction.py:262:def main() -> int:
experiments/k528/build_article_correction.py:273:    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
experiments/k528/build_article_correction.py:284:            content_replacements=REPLACEMENTS,
experiments/k528/build_article_correction.py:286:                "K528 event dates corrected from a first-Friday proxy to the official BLS "
experiments/k528/build_article_correction.py:287:                "release calendar. Sample 254 -> 253 events; headline numbers restated "
experiments/k528/build_article_correction.py:288:                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
experiments/k528/build_article_correction.py:289:                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
experiments/k528/build_article_correction.py:290:                "now restricts the event group to the 237 Friday releases so weekday is "
experiments/k528/build_article_correction.py:296:        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
experiments/k528/build_article_correction.py:299:    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
experiments/k528/build_article_correction.py:305:        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
tests/test_event_dates_real_raw_response.py:3:Why this file exists, separately from test_event_dates_release_selection.py:
tests/test_event_dates_real_raw_response.py:5:The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
tests/test_event_dates_real_raw_response.py:6:a *hand-built* fixture in which the same-month duplicate entries had already
tests/test_event_dates_real_raw_response.py:8:not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
tests/test_event_dates_real_raw_response.py:12:it is real input. This module pins `_fetch`'s actual bytes for release id 50
tests/test_event_dates_real_raw_response.py:14:six regular releases survive selection.
tests/test_event_dates_real_raw_response.py:16:Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
tests/test_event_dates_real_raw_response.py:28:_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
tests/test_event_dates_real_raw_response.py:30:# The six months ALFRED returns twice for, with the regular Employment Situation
tests/test_event_dates_real_raw_response.py:31:# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
tests/test_event_dates_real_raw_response.py:32:# filed against the same release id LATER in the month). Verified against the
tests/test_event_dates_real_raw_response.py:33:# live API on 2026-07-19; the right-hand column is exactly what the old max()
tests/test_event_dates_real_raw_response.py:38:    "2013-05": ("2013-05-03", "2013-05-06"),
tests/test_event_dates_real_raw_response.py:46:def _sandbox_cache_dir(monkeypatch, tmp_path):
tests/test_event_dates_real_raw_response.py:52:def raw_response() -> list[str]:
tests/test_event_dates_real_raw_response.py:53:    return json.loads(_FIXTURE.read_text())["release_dates"]
tests/test_event_dates_real_raw_response.py:57:def selected(monkeypatch, raw_response) -> list[str]:
tests/test_event_dates_real_raw_response.py:59:    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
tests/test_event_dates_real_raw_response.py:63:def test_fixture_still_carries_the_duplicate_months(raw_response):
tests/test_event_dates_real_raw_response.py:65:    by_month: dict[str, list[str]] = {}
tests/test_event_dates_real_raw_response.py:67:        by_month.setdefault(d[:7], []).append(d)
tests/test_event_dates_real_raw_response.py:68:    multi = {m: v for m, v in by_month.items() if len(v) > 1}
tests/test_event_dates_real_raw_response.py:70:        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
tests/test_event_dates_real_raw_response.py:73:    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
tests/test_event_dates_real_raw_response.py:74:        assert sorted(multi[month]) == [regular, off_cycle]
tests/test_event_dates_real_raw_response.py:77:def test_regular_release_wins_in_every_duplicate_month(selected):
tests/test_event_dates_real_raw_response.py:78:    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
tests/test_event_dates_real_raw_response.py:79:        in_month = [d for d in selected if d.startswith(month)]
tests/test_event_dates_real_raw_response.py:80:        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
tests/test_event_dates_real_raw_response.py:84:def test_selection_is_one_per_month_and_complete(selected, raw_response):
tests/test_event_dates_real_raw_response.py:85:    months_in = {d[:7] for d in raw_response}
tests/test_event_dates_real_raw_response.py:86:    months_out = [d[:7] for d in selected]
tests/test_event_dates_real_raw_response.py:87:    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
tests/test_event_dates_real_raw_response.py:88:    assert set(months_out) == months_in, "selection dropped or invented a month"
tests/test_event_dates_real_raw_response.py:92:def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
tests/test_event_dates_real_raw_response.py:95:    Without this, a future refactor could silently restore max() and the two
tests/test_event_dates_real_raw_response.py:99:    by_month: dict[str, list[str]] = {}
tests/test_event_dates_real_raw_response.py:101:        by_month.setdefault(d[:7], []).append(d)
tests/test_event_dates_real_raw_response.py:102:    old_rule = {m: max(v) for m, v in by_month.items()}
tests/test_event_dates_real_raw_response.py:105:        "the old max() rule must pick exactly the six off-cycle dates on this input"
tests/test_event_dates_release_selection.py:1:"""Regression tests for release_dates off-cycle selection + cadence gate.
tests/test_event_dates_release_selection.py:3:2026-07-19 k528 Codex review: the old per-month max() rule picked 6 off-cycle
tests/test_event_dates_release_selection.py:5:release id, later in the month) as NFP event dates, flipping a significance
tests/test_event_dates_release_selection.py:6:result. The fix keeps each month's EARLIEST entry and fail-closes when the
tests/test_event_dates_release_selection.py:7:resulting sequence does not look like a monthly release calendar.
tests/test_event_dates_release_selection.py:17:def _sandbox_cache_dir(monkeypatch, tmp_path):
tests/test_event_dates_release_selection.py:23:def _dates(monkeypatch, raw):
tests/test_event_dates_release_selection.py:25:    return event_dates.release_dates("NFP_US", "2024-01-01", "2024-12-31", use_cache=False)
tests/test_event_dates_release_selection.py:28:def test_off_cycle_late_entry_loses_to_regular_release(monkeypatch):
tests/test_event_dates_release_selection.py:38:def test_shutdown_gap_within_band_passes(monkeypatch):
tests/test_event_dates_release_selection.py:39:    # One cancelled month (~77d gap) is a real calendar, not an error.
tests/test_event_dates_release_selection.py:45:def test_collapsed_gap_fails_closed(monkeypatch):
tests/test_event_dates_release_selection.py:46:    # A month whose ONLY entry is a late off-cycle date makes the next gap
tests/test_event_dates_release_selection.py:47:    # collapse (<20d) — the sequence no longer looks like a release calendar.
tests/test_event_dates_release_selection.py:49:    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
tests/test_event_dates_release_selection.py:53:def test_three_missing_cycles_fail_closed(monkeypatch):
tests/test_event_dates_release_selection.py:55:    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
src/volpred/data/event_dates.py:1:"""Official macro-event release dates.
src/volpred/data/event_dates.py:5:around the 13th") silently does two things at once: it counts non-event days as
src/volpred/data/event_dates.py:10:release dates from a 13th-of-month proxy. Against the official calendar 7 of 13
src/volpred/data/event_dates.py:12:Oct-2025 release was cancelled during the shutdown). Recomputing the CPI-day VIX
src/volpred/data/event_dates.py:15:So: get the dates from the release calendar. `ALFRED` (FRED's real-time archive)
src/volpred/data/event_dates.py:16:publishes the actual news-release dates per statistical release, which is exactly
src/volpred/data/event_dates.py:20:    from volpred.data.event_dates import cpi_release_dates
src/volpred/data/event_dates.py:21:    dates = cpi_release_dates("2024-01-01", "2026-12-31")   # DatetimeIndex
src/volpred/data/event_dates.py:39:# FRED release ids for the macro releases we run event studies on.
src/volpred/data/event_dates.py:40:# https://fred.stlouisfed.org/releases
src/volpred/data/event_dates.py:44:    "FOMC": 101,       # H.4.1 is not the FOMC; FOMC statements are not a FRED release
src/volpred/data/event_dates.py:51:def _api_key() -> str:
src/volpred/data/event_dates.py:64:        "FRED_API_KEY not found. Event dates must come from the official release "
src/volpred/data/event_dates.py:69:def _fetch(release_id: int, start: str, end: str) -> list[str]:
src/volpred/data/event_dates.py:71:        "https://api.stlouisfed.org/fred/release/dates",
src/volpred/data/event_dates.py:73:            "release_id": release_id,
src/volpred/data/event_dates.py:78:            # Without this, ALFRED only returns releases that already carry data, so
src/volpred/data/event_dates.py:81:            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
src/volpred/data/event_dates.py:83:            "include_release_dates_with_no_data": "true",
src/volpred/data/event_dates.py:90:    return [d["date"] for d in r.json()["release_dates"]]
src/volpred/data/event_dates.py:93:def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
src/volpred/data/event_dates.py:94:    """Official news-release dates for `event` within [start, end].
src/volpred/data/event_dates.py:96:    Monthly releases can carry off-cycle entries (annual seasonal-factor and
src/volpred/data/event_dates.py:97:    benchmark revisions are filed against the same release id, LATER in the
src/volpred/data/event_dates.py:98:    month than the regular report). We therefore keep the EARLIEST entry in
src/volpred/data/event_dates.py:99:    each month — 2026-07-19 k528 Codex review proved the previous `max()` rule
src/volpred/data/event_dates.py:102:    Fail-closed on ambiguity: the selected sequence must look like a monthly
src/volpred/data/event_dates.py:103:    release calendar (consecutive gaps 13–110 days; shutdown catch-ups compress for real,
src/volpred/data/event_dates.py:104:    e.g. 2013-10-22 -> 2013-11-08 = 17d, and cancelled months stretch,
src/volpred/data/event_dates.py:136:        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
src/volpred/data/event_dates.py:138:    monthly = s.groupby([dates.year, dates.month]).min()
src/volpred/data/event_dates.py:139:    selected = pd.DatetimeIndex(sorted(monthly.values))
src/volpred/data/event_dates.py:140:    # Lower bound 13d catches mispicked entries (collapse patterns run <=12d)
src/volpred/data/event_dates.py:141:    # while passing real shutdown catch-ups (2013-10-22 -> 2013-11-08 = 17d).
src/volpred/data/event_dates.py:142:    # Upper bound 110d allows cancelled months (76d real) but trips on 3+ gaps.
src/volpred/data/event_dates.py:144:    bad = gaps[(gaps < 13) | (gaps > 110)]
src/volpred/data/event_dates.py:151:            f"{event} release calendar failed monthly-cadence validation "
src/volpred/data/event_dates.py:152:            f"(gaps outside 13-110 days): {offenders}. Off-cycle entries or "
src/volpred/data/event_dates.py:153:            f"missing months need manual disambiguation — refusing to return "
src/volpred/data/event_dates.py:159:def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
src/volpred/data/event_dates.py:160:    return release_dates("CPI_US", start, end, **kw)
src/volpred/data/event_dates.py:163:def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
src/volpred/data/event_dates.py:164:    return release_dates("NFP_US", start, end, **kw)
experiments/k528/k528_nfp_event_study.py:4:Extends K513 (FOMC/NFP/CPI event study) with deeper NFP-specific analysis.
experiments/k528/k528_nfp_event_study.py:6:K513 finding: NFP vol ratio = 1.09x (NS, p=0.195). This study digs deeper:
experiments/k528/k528_nfp_event_study.py:10:  - Seasonal decomposition (which months matter?)
experiments/k528/k528_nfp_event_study.py:16:  - NFP dates: OFFICIAL BLS release calendar via ALFRED (FRED release id 50)
experiments/k528/k528_nfp_event_study.py:17:  - NFP actual values: FRED PAYEMS (monthly, for surprise calculation)
experiments/k528/k528_nfp_event_study.py:21:The original run dated every NFP to the first Friday of the month. That proxy is
experiments/k528/k528_nfp_event_study.py:23:moves the release to the second Friday whenever the reference week falls late
experiments/k528/k528_nfp_event_study.py:25:dates land 3-4 days late). It also invents a release in 2025-10 that never
experiments/k528/k528_nfp_event_study.py:26:happened, and it forces every event onto a Friday when 16 of the 254 official
experiments/k528/k528_nfp_event_study.py:27:releases are not on a Friday at all.
experiments/k528/k528_nfp_event_study.py:31:the dates now come from the official release calendar and the run FAILS CLOSED
experiments/k528/k528_nfp_event_study.py:39:  - Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?"
experiments/k528/k528_nfp_event_study.py:42:  - K513: Our prior FOMC/NFP/CPI event study (2005-2025, 668 events)
experiments/k528/k528_nfp_event_study.py:61:from volpred.data.event_dates import nfp_release_dates
experiments/k528/k528_nfp_event_study.py:70:# here is a data-integrity failure, not a known hole -- see check_calendar_is_complete.
experiments/k528/k528_nfp_event_study.py:72:# 2025-10: the federal government shutdown. ALFRED shows no release id 50 entry
experiments/k528/k528_nfp_event_study.py:73:# between 2025-09-05 and 2025-11-20 (a 76-day gap against a ~30-day cadence);
experiments/k528/k528_nfp_event_study.py:75:# cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py.
experiments/k528/k528_nfp_event_study.py:76:# It is a real absence of an event, which is why the month is excluded rather
experiments/k528/k528_nfp_event_study.py:77:# than back-filled -- the first-Friday proxy INVENTED an event here, and that
experiments/k528/k528_nfp_event_study.py:79:KNOWN_MISSING_MONTHS: set[str] = {"2025-10"}
experiments/k528/k528_nfp_event_study.py:82:def write_json_atomic(path: Path, payload) -> None:
experiments/k528/k528_nfp_event_study.py:88:    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
experiments/k528/k528_nfp_event_study.py:96:            os.fsync(f.fileno())
experiments/k528/k528_nfp_event_study.py:97:        os.replace(tmp, path)
experiments/k528/k528_nfp_event_study.py:107:# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
experiments/k528/k528_nfp_event_study.py:109:def check_calendar_is_complete(dates, start, end):
experiments/k528/k528_nfp_event_study.py:112:    "Did the call succeed?" is the wrong question. A monthly release calendar
experiments/k528/k528_nfp_event_study.py:115:    without being empty are: a month appears twice (off-cycle revision picked
experiments/k528/k528_nfp_event_study.py:116:    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
experiments/k528/k528_nfp_event_study.py:119:    months = [pd.Timestamp(d).strftime("%Y-%m") for d in dates]
experiments/k528/k528_nfp_event_study.py:121:    dupes = sorted({m for m in months if months.count(m) > 1})
experiments/k528/k528_nfp_event_study.py:124:            f"official NFP calendar returned {len(dupes)} month(s) with more than one "
experiments/k528/k528_nfp_event_study.py:125:            f"release date: {dupes}. The Employment Situation is published once per "
experiments/k528/k528_nfp_event_study.py:126:            "month; a second same-month entry is an off-cycle revision and must not be "
experiments/k528/k528_nfp_event_study.py:134:    # The endpoint months are partial by construction: a run ending 2026-03-27
experiments/k528/k528_nfp_event_study.py:136:    interior = {m for m in expected if m not in {min(expected), max(expected)}}
experiments/k528/k528_nfp_event_study.py:137:    missing = sorted(interior - set(months) - KNOWN_MISSING_MONTHS)
experiments/k528/k528_nfp_event_study.py:140:            f"official NFP calendar is missing {len(missing)} month(s) inside the sample "
experiments/k528/k528_nfp_event_study.py:142:            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
experiments/k528/k528_nfp_event_study.py:143:            "reason (e.g. a cancelled release), never to make this check pass."
experiments/k528/k528_nfp_event_study.py:145:    return {"n_months_expected": len(interior), "known_missing_months": sorted(KNOWN_MISSING_MONTHS)}
experiments/k528/k528_nfp_event_study.py:148:def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
experiments/k528/k528_nfp_event_study.py:149:    """Official NFP (Employment Situation) release dates.
experiments/k528/k528_nfp_event_study.py:151:    Deliberately has no except branch. If the release calendar cannot be
experiments/k528/k528_nfp_event_study.py:156:    dates = nfp_release_dates(start, end)
experiments/k528/k528_nfp_event_study.py:159:    completeness = check_calendar_is_complete(dates, start, end)
experiments/k528/k528_nfp_event_study.py:202:# The proxy forced every event onto a Friday. The official calendar does not,
experiments/k528/k528_nfp_event_study.py:203:# and that is load-bearing for the Friday-baseline test below.
experiments/k528/k528_nfp_event_study.py:205:print(f"  Official releases: {len(nfp_calendar)} "
experiments/k528/k528_nfp_event_study.py:206:      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
experiments/k528/k528_nfp_event_study.py:209:# 08:30 ET, before the open, so a release on a closed day is traded at the next
experiments/k528/k528_nfp_event_study.py:210:# open -- hence "next trading day", not "nearest". Every release must land on
experiments/k528/k528_nfp_event_study.py:211:# exactly one session and no two releases may share one: both failures shrink
experiments/k528/k528_nfp_event_study.py:213:release_to_session = {}
experiments/k528/k528_nfp_event_study.py:218:        release_to_session[nfp_ts] = nfp_ts
experiments/k528/k528_nfp_event_study.py:223:        release_to_session[nfp_ts] = candidates[0]
experiments/k528/k528_nfp_event_study.py:227:# In-sample releases must map. Releases outside the price series (the calendar
experiments/k528/k528_nfp_event_study.py:236:        f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
experiments/k528/k528_nfp_event_study.py:242:for rel, sess in release_to_session.items():
experiments/k528/k528_nfp_event_study.py:247:        f"two or more NFP releases mapped to the same trading session: {colliding}. "
experiments/k528/k528_nfp_event_study.py:251:nfp_trading_dates = sorted(release_to_session.values())
experiments/k528/k528_nfp_event_study.py:252:n_shifted = sum(1 for r, s in release_to_session.items() if r != s)
experiments/k528/k528_nfp_event_study.py:265:    "n_official_releases": len(nfp_calendar),
experiments/k528/k528_nfp_event_study.py:275:print(f"  Total official releases: {len(nfp_calendar)}")
experiments/k528/k528_nfp_event_study.py:312:        "month": nfp_date.month,
experiments/k528/k528_nfp_event_study.py:313:        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
experiments/k528/k528_nfp_event_study.py:348:# Friday-only baseline. Under the proxy every event was a Friday by
experiments/k528/k528_nfp_event_study.py:349:# construction, so "all NFP events vs non-NFP Fridays" was a clean
experiments/k528/k528_nfp_event_study.py:351:# group is a weekday mixture and the control group is pure Friday, so any
experiments/k528/k528_nfp_event_study.py:352:# Friday-vs-other-weekday volatility difference loads directly onto the
experiments/k528/k528_nfp_event_study.py:360:print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
experiments/k528/k528_nfp_event_study.py:375:# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
experiments/k528/k528_nfp_event_study.py:378:#   (i)  restrict the event group to Friday releases, or
experiments/k528/k528_nfp_event_study.py:380:# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
experiments/k528/k528_nfp_event_study.py:384:# (i) answers one clean question: on a Friday, does an NFP release raise
experiments/k528/k528_nfp_event_study.py:385:# volatility? It costs the 11 non-Friday events, which are reported below as a
experiments/k528/k528_nfp_event_study.py:395:# audit can show what the contaminated estimand was worth. Not a headline
experiments/k528/k528_nfp_event_study.py:435:# --- Test G: Seasonal analysis (by month) ---
experiments/k528/k528_nfp_event_study.py:436:monthly_stats = {}
experiments/k528/k528_nfp_event_study.py:437:for month in range(1, 13):
experiments/k528/k528_nfp_event_study.py:438:    month_data = df[df["month"] == month]["event_abs_return"]
experiments/k528/k528_nfp_event_study.py:439:    if len(month_data) >= 5:
experiments/k528/k528_nfp_event_study.py:440:        monthly_stats[str(month)] = {
experiments/k528/k528_nfp_event_study.py:441:            "n": int(len(month_data)),
experiments/k528/k528_nfp_event_study.py:442:            "mean_abs_return": float(month_data.mean()),
experiments/k528/k528_nfp_event_study.py:443:            "vol_ratio": float(month_data.mean() / baseline_abs_return),
experiments/k528/k528_nfp_event_study.py:444:            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
experiments/k528/k528_nfp_event_study.py:445:            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
experiments/k528/k528_nfp_event_study.py:479:print(f"\n--- B. Friday NFP vs Friday Non-NFP (weekday held fixed) ---")
experiments/k528/k528_nfp_event_study.py:480:print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
experiments/k528/k528_nfp_event_study.py:481:print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
experiments/k528/k528_nfp_event_study.py:486:print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
experiments/k528/k528_nfp_event_study.py:488:print(f"  [diagnostic, NOT a headline] all-events vs Friday baseline: "
experiments/k528/k528_nfp_event_study.py:518:print(f"\n--- G. Seasonal Pattern (by month) ---")
experiments/k528/k528_nfp_event_study.py:520:month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
experiments/k528/k528_nfp_event_study.py:522:for m in range(1, 13):
experiments/k528/k528_nfp_event_study.py:523:    if str(m) in monthly_stats:
experiments/k528/k528_nfp_event_study.py:524:        ms = monthly_stats[str(m)]
experiments/k528/k528_nfp_event_study.py:526:        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")
experiments/k528/k528_nfp_event_study.py:567:april_nfp = df[df["month"] == 4]
experiments/k528/k528_nfp_event_study.py:572:if "4" in monthly_stats:
experiments/k528/k528_nfp_event_study.py:573:    ms4 = monthly_stats["4"]
experiments/k528/k528_nfp_event_study.py:597:    f"Welch mean-difference, Friday NFP vs Friday non-NFP (weekday held fixed): "
experiments/k528/k528_nfp_event_study.py:640:print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
experiments/k528/k528_nfp_event_study.py:652:def win_rate(sample, reference):
experiments/k528/k528_nfp_event_study.py:696:def record(key, label, before, after, note=""):
experiments/k528/k528_nfp_event_study.py:727:# --- 1.17x : NFP vs Friday-only baseline ---
experiments/k528/k528_nfp_event_study.py:729:    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
experiments/k528/k528_nfp_event_study.py:747:        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
experiments/k528/k528_nfp_event_study.py:753:            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
experiments/k528/k528_nfp_event_study.py:758:         "the proxy every NFP day was a Friday by construction, so this test "
experiments/k528/k528_nfp_event_study.py:759:         "compared Fridays with Fridays; on the official calendar the event "
experiments/k528/k528_nfp_event_study.py:761:         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
experiments/k528/k528_nfp_event_study.py:859:def verdict_for(key):
experiments/k528/k528_nfp_event_study.py:860:    """Flip test: significance change, sign change, or a >10% move in the headline."""
experiments/k528/k528_nfp_event_study.py:892:    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
experiments/k528/k528_nfp_event_study.py:894:    bf = item["before"].get(headline)
experiments/k528/k528_nfp_event_study.py:895:    af = item["after"].get(headline)
experiments/k528/k528_nfp_event_study.py:915:        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
experiments/k528/k528_nfp_event_study.py:916:        "accessor": "volpred.data.event_dates.nfp_release_dates",
experiments/k528/k528_nfp_event_study.py:918:        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
experiments/k528/k528_nfp_event_study.py:946:            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
experiments/k528/k528_nfp_event_study.py:949:                "releases that trade on a Friday; the 11 non-Friday events are "
experiments/k528/k528_nfp_event_study.py:950:                "excluded rather than compared against a pure-Friday control group."
experiments/k528/k528_nfp_event_study.py:964:            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
experiments/k528/k528_nfp_event_study.py:965:            "status": "DIAGNOSTIC ONLY - do not quote",
experiments/k528/k528_nfp_event_study.py:966:            "why_not_a_headline": (
experiments/k528/k528_nfp_event_study.py:968:                "group against a pure-Friday control group, so the p-value absorbs "
experiments/k528/k528_nfp_event_study.py:969:                "any Friday-vs-other-weekday volatility difference. Retained solely "
experiments/k528/k528_nfp_event_study.py:1010:    "seasonal_analysis": monthly_stats,
experiments/k528/k528_nfp_event_study.py:1047:        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
experiments/k528/k528_nfp_event_study.py:1062:        "The superseded run summarised these as 'insignificant across all tests', "
experiments/k528/k528_nfp_event_study.py:1067:        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
experiments/k528/k528_nfp_event_study.py:1068:        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
experiments/k528/k528_nfp_event_study.py:1084:    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
experiments/k528/k528_nfp_event_study.py:1107:        "replacements": None,

exec
/bin/zsh -lc "nl -ba src/volpred/data/event_dates.py | sed -n '1,210p'
nl -ba tests/test_event_dates_real_raw_response.py | sed -n '1,220p'
nl -ba tests/test_event_dates_release_selection.py | sed -n '1,260p'
nl -ba tests/test_nfp_official_release_dates.py | sed -n '1,300p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
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
    96	    Monthly releases can carry off-cycle entries (annual seasonal-factor and
    97	    benchmark revisions are filed against the same release id, LATER in the
    98	    month than the regular report). We therefore keep the EARLIEST entry in
    99	    each month — 2026-07-19 k528 Codex review proved the previous `max()` rule
   100	    picked 6 off-cycle dates as NFP events and flipped a significance result.
   101	
   102	    Fail-closed on ambiguity: the selected sequence must look like a monthly
   103	    release calendar (consecutive gaps 13–110 days; shutdown catch-ups compress for real,
   104	    e.g. 2013-10-22 -> 2013-11-08 = 17d, and cancelled months stretch,
   105	    e.g. 2025-09-05 -> 2025-11-20 = 76d). Any gap outside that band
   106	    raises instead of returning a plausible-but-wrong calendar —
   107	    silently-wrong event dates are worse than a failed run.
   108	    """
   109	    if event not in RELEASE_IDS:
   110	        raise KeyError(f"unknown event {event!r}; known: {sorted(RELEASE_IDS)}")
   111	
   112	    cache = _CACHE_DIR / f"{event}_{start}_{end}.json"
   113	    if use_cache and cache.exists():
   114	        age = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cache.stat().st_mtime, unit="s")
   115	        if age < _CACHE_TTL:
   116	            raw = json.loads(cache.read_text())
   117	        else:
   118	            raw = None
   119	    else:
   120	        raw = None
   121	
   122	    if raw is None:
   123	        raw = _fetch(RELEASE_IDS[event], start, end)
   124	        if use_cache:
   125	            # use_cache=False must bypass the cache ENTIRELY — the old code
   126	            # skipped only the read and still wrote, which leaked canonical
   127	            # writes out of hermetic tests (CI repo-state guard, 2026-07-19).
   128	            from volpred.canonical_write import guard_canonical_write
   129	
   130	            guard_canonical_write(cache)
   131	            cache.parent.mkdir(parents=True, exist_ok=True)
   132	            cache.write_text(json.dumps(raw) + "\n")
   133	
   134	    dates = pd.to_datetime(raw)
   135	    if len(dates) == 0:
   136	        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
   137	    s = pd.Series(dates, index=dates)
   138	    monthly = s.groupby([dates.year, dates.month]).min()
   139	    selected = pd.DatetimeIndex(sorted(monthly.values))
   140	    # Lower bound 13d catches mispicked entries (collapse patterns run <=12d)
   141	    # while passing real shutdown catch-ups (2013-10-22 -> 2013-11-08 = 17d).
   142	    # Upper bound 110d allows cancelled months (76d real) but trips on 3+ gaps.
   143	    gaps = pd.Series(selected).diff().dropna().dt.days
   144	    bad = gaps[(gaps < 13) | (gaps > 110)]
   145	    if len(bad) > 0:
   146	        offenders = [
   147	            f"{selected[i - 1].date()} -> {selected[i].date()} ({int(g)}d)"
   148	            for i, g in zip(bad.index, bad.values)
   149	        ]
   150	        raise RuntimeError(
   151	            f"{event} release calendar failed monthly-cadence validation "
   152	            f"(gaps outside 13-110 days): {offenders}. Off-cycle entries or "
   153	            f"missing months need manual disambiguation — refusing to return "
   154	            f"a plausible-but-wrong calendar."
   155	        )
   156	    return selected
   157	
   158	
   159	def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   160	    return release_dates("CPI_US", start, end, **kw)
   161	
   162	
   163	def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   164	    return release_dates("NFP_US", start, end, **kw)
     1	"""Regression test against the VERBATIM ALFRED raw response.
     2	
     3	Why this file exists, separately from test_event_dates_release_selection.py:
     4	
     5	The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
     6	a *hand-built* fixture in which the same-month duplicate entries had already
     7	been removed. So they exercised the selection rule against input that could
     8	not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
     9	dates and flipped a significance result with a fully green suite.
    10	
    11	The fix for a fixture that cannot express the bug is not a better assertion —
    12	it is real input. This module pins `_fetch`'s actual bytes for release id 50
    13	(Employment Situation, 2005-01-01..2026-07-19, 264 entries) and asserts the
    14	six regular releases survive selection.
    15	
    16	Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
    17	it — the duplicate pairs ARE the regression surface).
    18	"""
    19	from __future__ import annotations
    20	
    21	import json
    22	from pathlib import Path
    23	
    24	import pytest
    25	
    26	from volpred.data import event_dates
    27	
    28	_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
    29	
    30	# The six months ALFRED returns twice for, with the regular Employment Situation
    31	# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
    32	# filed against the same release id LATER in the month). Verified against the
    33	# live API on 2026-07-19; the right-hand column is exactly what the old max()
    34	# rule picked and what k528's contaminated run treated as NFP event days.
    35	OFF_CYCLE_PAIRS = {
    36	    "2006-05": ("2006-05-05", "2006-05-08"),
    37	    "2012-12": ("2012-12-07", "2012-12-12"),
    38	    "2013-05": ("2013-05-03", "2013-05-06"),
    39	    "2020-05": ("2020-05-08", "2020-05-11"),
    40	    "2024-01": ("2024-01-05", "2024-01-10"),
    41	    "2024-08": ("2024-08-02", "2024-08-21"),
    42	}
    43	
    44	
    45	@pytest.fixture(autouse=True)
    46	def _sandbox_cache_dir(monkeypatch, tmp_path):
    47	    # No test may touch the canonical storage/data cache dir (CI repo-state guard).
    48	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
    49	
    50	
    51	@pytest.fixture
    52	def raw_response() -> list[str]:
    53	    return json.loads(_FIXTURE.read_text())["release_dates"]
    54	
    55	
    56	@pytest.fixture
    57	def selected(monkeypatch, raw_response) -> list[str]:
    58	    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw_response))
    59	    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
    60	    return [str(d.date()) for d in idx]
    61	
    62	
    63	def test_fixture_still_carries_the_duplicate_months(raw_response):
    64	    """Guard the guard: if someone 'cleans' the fixture, the suite goes quiet again."""
    65	    by_month: dict[str, list[str]] = {}
    66	    for d in raw_response:
    67	        by_month.setdefault(d[:7], []).append(d)
    68	    multi = {m: v for m, v in by_month.items() if len(v) > 1}
    69	    assert set(multi) == set(OFF_CYCLE_PAIRS), (
    70	        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
    71	        f"got {sorted(multi)}"
    72	    )
    73	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
    74	        assert sorted(multi[month]) == [regular, off_cycle]
    75	
    76	
    77	def test_regular_release_wins_in_every_duplicate_month(selected):
    78	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
    79	        in_month = [d for d in selected if d.startswith(month)]
    80	        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
    81	        assert off_cycle not in selected, f"{off_cycle} is an off-cycle revision, not an NFP event"
    82	
    83	
    84	def test_selection_is_one_per_month_and_complete(selected, raw_response):
    85	    months_in = {d[:7] for d in raw_response}
    86	    months_out = [d[:7] for d in selected]
    87	    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
    88	    assert set(months_out) == months_in, "selection dropped or invented a month"
    89	    assert len(selected) == 258
    90	
    91	
    92	def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
    93	    """Mutation check: the OLD rule must fail this file, or it proves nothing.
    94	
    95	    Without this, a future refactor could silently restore max() and the two
    96	    assertions above would be the only thing standing in the way — this pins
    97	    WHY they matter.
    98	    """
    99	    by_month: dict[str, list[str]] = {}
   100	    for d in raw_response:
   101	        by_month.setdefault(d[:7], []).append(d)
   102	    old_rule = {m: max(v) for m, v in by_month.items()}
   103	    wrong = {m: old_rule[m] for m, (regular, _) in OFF_CYCLE_PAIRS.items() if old_rule[m] != regular}
   104	    assert wrong == {m: off for m, (_, off) in OFF_CYCLE_PAIRS.items()}, (
   105	        "the old max() rule must pick exactly the six off-cycle dates on this input"
   106	    )
     1	"""Regression tests for release_dates off-cycle selection + cadence gate.
     2	
     3	2026-07-19 k528 Codex review: the old per-month max() rule picked 6 off-cycle
     4	FRED entries (seasonal-factor / benchmark revisions filed against the same
     5	release id, later in the month) as NFP event dates, flipping a significance
     6	result. The fix keeps each month's EARLIEST entry and fail-closes when the
     7	resulting sequence does not look like a monthly release calendar.
     8	"""
     9	from __future__ import annotations
    10	
    11	import pytest
    12	
    13	from volpred.data import event_dates
    14	
    15	
    16	@pytest.fixture(autouse=True)
    17	def _sandbox_cache_dir(monkeypatch, tmp_path):
    18	    # belt-and-suspenders with use_cache=False: no test may touch the
    19	    # canonical storage/data cache dir (CI repo-state guard, 2026-07-19).
    20	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
    21	
    22	
    23	def _dates(monkeypatch, raw):
    24	    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw))
    25	    return event_dates.release_dates("NFP_US", "2024-01-01", "2024-12-31", use_cache=False)
    26	
    27	
    28	def test_off_cycle_late_entry_loses_to_regular_release(monkeypatch):
    29	    raw = [
    30	        "2024-01-05",
    31	        "2024-02-02", "2024-02-09",  # 02-09 = off-cycle revision entry, must lose
    32	        "2024-03-08",
    33	    ]
    34	    got = [str(d.date()) for d in _dates(monkeypatch, raw)]
    35	    assert got == ["2024-01-05", "2024-02-02", "2024-03-08"]
    36	
    37	
    38	def test_shutdown_gap_within_band_passes(monkeypatch):
    39	    # One cancelled month (~77d gap) is a real calendar, not an error.
    40	    raw = ["2024-01-05", "2024-02-02", "2024-04-19", "2024-05-17"]
    41	    got = [str(d.date()) for d in _dates(monkeypatch, raw)]
    42	    assert got == ["2024-01-05", "2024-02-02", "2024-04-19", "2024-05-17"]
    43	
    44	
    45	def test_collapsed_gap_fails_closed(monkeypatch):
    46	    # A month whose ONLY entry is a late off-cycle date makes the next gap
    47	    # collapse (<20d) — the sequence no longer looks like a release calendar.
    48	    raw = ["2024-01-05", "2024-02-27", "2024-03-07"]
    49	    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
    50	        _dates(monkeypatch, raw)
    51	
    52	
    53	def test_three_missing_cycles_fail_closed(monkeypatch):
    54	    raw = ["2024-01-05", "2024-06-07"]
    55	    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
    56	        _dates(monkeypatch, raw)
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

exec
/bin/zsh -lc "sed -n '1,80p' tests/fixtures/fred_release_50_nfp_raw_20260719.json
sed -n '240,340p' tests/fixtures/fred_release_50_nfp_raw_20260719.json
wc -c -l tests/fixtures/fred_release_50_nfp_raw_20260719.json
jq '{keys:keys, n:(.release_dates|length), first:.release_dates[0], last:.release_dates[-1], duplicate_months:([.release_dates[]|.[0:7]]|group_by(.)|map(select(length>1)|{month:.[0],n:length}))}' tests/fixtures/fred_release_50_nfp_raw_20260719.json
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '50,280p'
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '280,460p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
{
  "source": "FRED/ALFRED release/dates API, release_id=50 (Employment Situation)",
  "params": {
    "realtime_start": "2005-01-01",
    "realtime_end": "2026-07-19",
    "include_release_dates_with_no_data": true,
    "limit": 1000,
    "sort_order": "asc"
  },
  "captured_at": "2026-07-19",
  "note": "VERBATIM _fetch() output. Do NOT hand-edit or de-duplicate: the six same-month duplicate pairs ARE the regression surface (k528 Codex v2 BLOCKER 1).",
  "release_dates": [
    "2005-01-07",
    "2005-02-04",
    "2005-03-04",
    "2005-04-01",
    "2005-05-06",
    "2005-06-03",
    "2005-07-08",
    "2005-08-05",
    "2005-09-02",
    "2005-10-07",
    "2005-11-04",
    "2005-12-02",
    "2006-01-06",
    "2006-02-03",
    "2006-03-10",
    "2006-04-07",
    "2006-05-05",
    "2006-05-08",
    "2006-06-02",
    "2006-07-07",
    "2006-08-04",
    "2006-09-01",
    "2006-10-06",
    "2006-11-03",
    "2006-12-08",
    "2007-01-05",
    "2007-02-02",
    "2007-03-09",
    "2007-04-06",
    "2007-05-04",
    "2007-06-01",
    "2007-07-06",
    "2007-08-03",
    "2007-09-07",
    "2007-10-05",
    "2007-11-02",
    "2007-12-07",
    "2008-01-04",
    "2008-02-01",
    "2008-03-07",
    "2008-04-04",
    "2008-05-02",
    "2008-06-06",
    "2008-07-03",
    "2008-08-01",
    "2008-09-05",
    "2008-10-03",
    "2008-11-07",
    "2008-12-05",
    "2009-01-09",
    "2009-02-06",
    "2009-03-06",
    "2009-04-03",
    "2009-05-08",
    "2009-06-05",
    "2009-07-02",
    "2009-08-07",
    "2009-09-04",
    "2009-10-02",
    "2009-11-06",
    "2009-12-04",
    "2010-01-08",
    "2010-02-05",
    "2010-03-05",
    "2010-04-02",
    "2010-05-07",
    "2010-06-04",
    "2010-07-02",
    "2023-08-04",
    "2023-09-01",
    "2023-10-06",
    "2023-11-03",
    "2023-12-08",
    "2024-01-05",
    "2024-01-10",
    "2024-02-02",
    "2024-03-08",
    "2024-04-05",
    "2024-05-03",
    "2024-06-07",
    "2024-07-05",
    "2024-08-02",
    "2024-08-21",
    "2024-09-06",
    "2024-10-04",
    "2024-11-01",
    "2024-12-06",
    "2025-01-10",
    "2025-02-07",
    "2025-03-07",
    "2025-04-04",
    "2025-05-02",
    "2025-06-06",
    "2025-07-03",
    "2025-08-01",
    "2025-09-05",
    "2025-11-20",
    "2025-12-16",
    "2026-01-09",
    "2026-02-11",
    "2026-03-06",
    "2026-04-03",
    "2026-05-08",
    "2026-06-05",
    "2026-07-02"
  ]
}
     278    5236 tests/fixtures/fred_release_50_nfp_raw_20260719.json
{
  "keys": [
    "captured_at",
    "note",
    "params",
    "release_dates",
    "source"
  ],
  "n": 264,
  "first": "2005-01-07",
  "last": "2026-07-02",
  "duplicate_months": [
    {
      "month": "2006-05",
      "n": 2
    },
    {
      "month": "2012-12",
      "n": 2
    },
    {
      "month": "2013-05",
      "n": 2
    },
    {
      "month": "2020-05",
      "n": 2
    },
    {
      "month": "2024-01",
      "n": 2
    },
    {
      "month": "2024-08",
      "n": 2
    }
  ]
}
    50	import os
    51	import tempfile
    52	import warnings
    53	from datetime import datetime, timezone
    54	from pathlib import Path
    55	
    56	import numpy as np
    57	import pandas as pd
    58	import yfinance as yf
    59	from scipy import stats
    60	
    61	from volpred.data.event_dates import nfp_release_dates
    62	
    63	warnings.filterwarnings("ignore")
    64	
    65	SAMPLE_START = "2005-01-01"
    66	SAMPLE_END = "2026-03-27"
    67	
    68	# Months in [SAMPLE_START, SAMPLE_END] for which BLS published no Employment
    69	# Situation report at all. Anything absent from the calendar that is NOT listed
    70	# here is a data-integrity failure, not a known hole -- see check_calendar_is_complete.
    71	#
    72	# 2025-10: the federal government shutdown. ALFRED shows no release id 50 entry
    73	# between 2025-09-05 and 2025-11-20 (a 76-day gap against a ~30-day cadence);
    74	# the delayed September report came out on 11-20. This is the same shutdown that
    75	# cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py.
    76	# It is a real absence of an event, which is why the month is excluded rather
    77	# than back-filled -- the first-Friday proxy INVENTED an event here, and that
    78	# phantom event is one of the reasons this experiment was rerun.
    79	KNOWN_MISSING_MONTHS: set[str] = {"2025-10"}
    80	
    81	
    82	def write_json_atomic(path: Path, payload) -> None:
    83	    """Write `payload` to `path` atomically.
    84	
    85	    A truncate-then-write leaves a half-written results file on the disk if the
    86	    run dies mid-dump, and a half-written results file is worse than none: it
    87	    still parses far enough to look like data to the next reader. Write to a
    88	    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
    89	    """
    90	    path.parent.mkdir(parents=True, exist_ok=True)
    91	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    92	    try:
    93	        with os.fdopen(fd, "w") as f:
    94	            json.dump(payload, f, indent=2, default=str)
    95	            f.flush()
    96	            os.fsync(f.fileno())
    97	        os.replace(tmp, path)
    98	    except BaseException:
    99	        try:
   100	            os.unlink(tmp)
   101	        except FileNotFoundError:
   102	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
   103	        raise
   104	
   105	
   106	# ============================================================
   107	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
   108	# ============================================================
   109	def check_calendar_is_complete(dates, start, end):
   110	    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
   111	
   112	    "Did the call succeed?" is the wrong question. A monthly release calendar
   113	    that silently lost 2019 still returns a non-empty list, still produces
   114	    event windows, still renders. The three ways this input can be wrong
   115	    without being empty are: a month appears twice (off-cycle revision picked
   116	    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
   117	    range is not covered at all. All three raise here.
   118	    """
   119	    months = [pd.Timestamp(d).strftime("%Y-%m") for d in dates]
   120	
   121	    dupes = sorted({m for m in months if months.count(m) > 1})
   122	    if dupes:
   123	        raise RuntimeError(
   124	            f"official NFP calendar returned {len(dupes)} month(s) with more than one "
   125	            f"release date: {dupes}. The Employment Situation is published once per "
   126	            "month; a second same-month entry is an off-cycle revision and must not be "
   127	            "treated as an event. Fix the accessor, do not de-duplicate here."
   128	        )
   129	
   130	    expected = {
   131	        p.strftime("%Y-%m")
   132	        for p in pd.period_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="M")
   133	    }
   134	    # The endpoint months are partial by construction: a run ending 2026-03-27
   135	    # legitimately has 2026-03, but a run ending 2026-03-02 may not yet.
   136	    interior = {m for m in expected if m not in {min(expected), max(expected)}}
   137	    missing = sorted(interior - set(months) - KNOWN_MISSING_MONTHS)
   138	    if missing:
   139	        raise RuntimeError(
   140	            f"official NFP calendar is missing {len(missing)} month(s) inside the sample "
   141	            f"window: {missing}. A partial calendar dumps real event days into the control "
   142	            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
   143	            "reason (e.g. a cancelled release), never to make this check pass."
   144	        )
   145	    return {"n_months_expected": len(interior), "known_missing_months": sorted(KNOWN_MISSING_MONTHS)}
   146	
   147	
   148	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   149	    """Official NFP (Employment Situation) release dates.
   150	
   151	    Deliberately has no except branch. If the release calendar cannot be
   152	    reached, this run must die -- a proxy calendar produces plausible numbers
   153	    from non-events, which is worse than no numbers at all. See the CORRECTION
   154	    note in the module docstring.
   155	    """
   156	    dates = nfp_release_dates(start, end)
   157	    if len(dates) == 0:
   158	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
   159	    completeness = check_calendar_is_complete(dates, start, end)
   160	    return list(dates), completeness
   161	
   162	
   163	# ============================================================
   164	# 2. Download data
   165	# ============================================================
   166	print("=" * 60)
   167	print("K528: NFP Event Study on SPY Volatility")
   168	print("=" * 60)
   169	
   170	print("\n[1/6] Downloading SPY and VIX data...")
   171	spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
   172	vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)
   173	
   174	# Handle multi-level columns from yfinance
   175	if isinstance(spy.columns, pd.MultiIndex):
   176	    spy.columns = spy.columns.get_level_values(0)
   177	if isinstance(vix.columns, pd.MultiIndex):
   178	    vix.columns = vix.columns.get_level_values(0)
   179	
   180	# Calculate returns
   181	spy["Return"] = spy["Close"].pct_change()
   182	spy["AbsReturn"] = spy["Return"].abs()
   183	spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
   184	spy.dropna(subset=["Return"], inplace=True)
   185	
   186	# Merge VIX
   187	vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
   188	spy = spy.join(vix_close, how="left")
   189	spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays
   190	
   191	print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
   192	print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")
   193	
   194	# ============================================================
   195	# 3. Map NFP dates to trading days
   196	# ============================================================
   197	print("\n[2/6] Mapping NFP dates to trading days...")
   198	
   199	nfp_calendar, calendar_completeness = load_nfp_dates()
   200	trading_dates = spy.index
   201	
   202	# The proxy forced every event onto a Friday. The official calendar does not,
   203	# and that is load-bearing for the Friday-baseline test below.
   204	n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
   205	print(f"  Official releases: {len(nfp_calendar)} "
   206	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
   207	
   208	# Map each NFP date to the session that trades the news. The report drops at
   209	# 08:30 ET, before the open, so a release on a closed day is traded at the next
   210	# open -- hence "next trading day", not "nearest". Every release must land on
   211	# exactly one session and no two releases may share one: both failures shrink
   212	# the event set without shrinking any count that gets printed.
   213	release_to_session = {}
   214	unmapped = []
   215	for nfp_date in nfp_calendar:
   216	    nfp_ts = pd.Timestamp(nfp_date)
   217	    if nfp_ts in trading_dates:
   218	        release_to_session[nfp_ts] = nfp_ts
   219	        continue
   220	    mask = (trading_dates > nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
   221	    candidates = trading_dates[mask]
   222	    if len(candidates) > 0:
   223	        release_to_session[nfp_ts] = candidates[0]
   224	    else:
   225	        unmapped.append(nfp_ts.date().isoformat())
   226	
   227	# In-sample releases must map. Releases outside the price series (the calendar
   228	# window can overhang the SPY history on either end) are excluded by design,
   229	# not by failure, so they are separated before the assertion.
   230	in_sample_unmapped = [
   231	    d for d in unmapped
   232	    if trading_dates[0] <= pd.Timestamp(d) <= trading_dates[-1]
   233	]
   234	if in_sample_unmapped:
   235	    raise RuntimeError(
   236	        f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
   237	        f"trading session within 3 days: {in_sample_unmapped}. Silently skipping them would "
   238	        "drop real event days into the control group."
   239	    )
   240	
   241	collisions = {}
   242	for rel, sess in release_to_session.items():
   243	    collisions.setdefault(sess, []).append(rel.date().isoformat())
   244	colliding = {str(s.date()): sorted(v) for s, v in collisions.items() if len(v) > 1}
   245	if colliding:
   246	    raise RuntimeError(
   247	        f"two or more NFP releases mapped to the same trading session: {colliding}. "
   248	        "The de-duplication that used to hide this also silently reduced the event count."
   249	    )
   250	
   251	nfp_trading_dates = sorted(release_to_session.values())
   252	n_shifted = sum(1 for r, s in release_to_session.items() if r != s)
   253	
   254	# Window buffer: an event needs 5 sessions before and 5 after to have a window
   255	# at all. Excluding the edges is correct; doing it without saying so is not.
   256	window_excluded = [d for d in nfp_trading_dates
   257	                   if d < trading_dates[10] or d > trading_dates[-6]]
   258	valid_nfp = [d for d in nfp_trading_dates
   259	             if d >= trading_dates[10] and d <= trading_dates[-6]]
   260	
   261	if len(valid_nfp) + len(window_excluded) != len(nfp_trading_dates):
   262	    raise RuntimeError("event-window partition lost events; refusing to continue")
   263	
   264	mapping_audit = {
   265	    "n_official_releases": len(nfp_calendar),
   266	    "n_mapped_to_sessions": len(nfp_trading_dates),
   267	    "n_shifted_to_next_session": n_shifted,
   268	    "n_outside_price_sample": len(unmapped),
   269	    "outside_price_sample_dates": sorted(unmapped),
   270	    "n_excluded_for_window_buffer": len(window_excluded),
   271	    "window_excluded_dates": [str(d.date()) for d in window_excluded],
   272	    "n_valid_events": len(valid_nfp),
   273	}
   274	
   275	print(f"  Total official releases: {len(nfp_calendar)}")
   276	print(f"  Mapped to trading sessions: {len(nfp_trading_dates)} ({n_shifted} shifted to next open)")
   277	print(f"  Outside price sample: {len(unmapped)}")
   278	print(f"  Excluded for window buffer: {len(window_excluded)}")
   279	print(f"  Valid (with pre/post window): {len(valid_nfp)}")
   280	
   280	
   281	# ============================================================
   282	# 4. Calculate event windows
   283	# ============================================================
   284	print("\n[3/6] Calculating event window statistics...")
   285	
   286	results = []
   287	idx_list = list(trading_dates)
   288	
   289	for nfp_date in valid_nfp:
   290	    pos = idx_list.index(nfp_date)
   291	
   292	    # Pre-event: T-5 to T-1
   293	    pre_window = spy.iloc[pos-5:pos]
   294	    # Event day: T
   295	    event_day = spy.iloc[pos]
   296	    # Post-event: T+1 to T+5
   297	    post_window = spy.iloc[pos+1:pos+6]
   298	
   299	    # Unreachable given the window-buffer partition above. Kept as an assertion
   300	    # rather than a `continue`: if the partition ever stops holding, the run
   301	    # must stop, not quietly analyse a smaller sample than it reports.
   302	    if len(pre_window) < 5 or len(post_window) < 5:
   303	        raise RuntimeError(
   304	            f"event {nfp_date.date()} has an incomplete window "
   305	            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
   306	            "window-buffer filter -- the partition and the window logic disagree"
   307	        )
   308	
   309	    row = {
   310	        "date": nfp_date.strftime("%Y-%m-%d"),
   311	        "year": nfp_date.year,
   312	        "month": nfp_date.month,
   313	        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
   314	        "event_return": float(event_day["Return"]),
   315	        "event_abs_return": float(event_day["AbsReturn"]),
   316	        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
   317	        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
   318	        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
   319	        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
   320	        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
   321	        "vix_change_event": None,
   322	        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
   323	        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
   324	    }
   325	
   326	    if row["pre_vix"] is not None and row["event_vix"] is not None:
   327	        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
   328	
   329	    results.append(row)
   330	
   331	df = pd.DataFrame(results)
   332	print(f"  Events with complete data: {len(df)}")
   333	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
   334	
   335	# ============================================================
   336	# 5. Non-NFP baseline calculation
   337	# ============================================================
   338	print("\n[4/6] Computing non-NFP baseline...")
   339	
   340	# Exclude EVERY NFP session from the control group, not just the ones that
   341	# survived the event-window filter. An event dropped for lacking a pre-window
   342	# is still an NFP day; leaving it in the control group is the exact failure this
   343	# experiment exists to fix ("dump real event days into the control group"), just
   344	# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
   345	nfp_set = set(nfp_trading_dates)
   346	non_nfp_mask = ~spy.index.isin(nfp_set)
   347	non_nfp = spy[non_nfp_mask]
   348	n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
   349	if n_leaked:
   350	    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
   351	
   352	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
   353	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
   354	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   355	
   356	# Friday-only baseline. Under the proxy every event was a Friday by
   357	# construction, so "all NFP events vs non-NFP Fridays" was a clean
   358	# weekday-held-fixed contrast. On the official calendar it is not: the event
   359	# group is a weekday mixture and the control group is pure Friday, so any
   360	# Friday-vs-other-weekday volatility difference loads directly onto the
   361	# estimate. The test below therefore holds weekday fixed on BOTH sides.
   362	friday_mask = non_nfp.index.weekday == 4
   363	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
   364	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
   365	
   366	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   367	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
   368	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   369	
   370	# ============================================================
   371	# 6. Statistical tests
   372	# ============================================================
   373	print("\n[5/6] Running statistical tests...")
   374	
   375	nfp_abs_returns = df["event_abs_return"].values
   376	non_nfp_abs_returns = non_nfp["AbsReturn"].values
   377	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
   378	
   379	# --- Test A: NFP vs all non-NFP days ---
   380	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
   381	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
   382	
   383	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
   384	#
   385	# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
   386	#   (i)  restrict the event group to Friday releases, or
   387	#   (ii) keep all events and use weekday-matched controls.
   388	# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
   389	# 253 -- cells that thin make (ii) a weighted average dominated by three
   390	# single-digit strata, with standard errors driven by the 1-observation
   391	# Wednesday cell. That is a noisier estimator of a harder-to-state quantity.
   392	# (i) answers one clean question: on a Friday, does an NFP release raise
   393	# volatility? It costs the 11 non-Friday events, which are reported below as a
   394	# separate descriptive line rather than dropped in silence.
   395	nfp_friday_mask = (df["weekday"] == 4).values
   396	nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
   397	nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
   398	
   399	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
   400	vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
   401	
   402	# Diagnostic ONLY -- the pre-correction specification, kept so the correction
   403	# audit can show what the contaminated estimand was worth. Not a headline
   404	# number and not eligible to be quoted: its p-value mixes in weekday
   405	# composition, which is exactly the defect being repaired.
   406	t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
   407	    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
   408	vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
   409	
   410	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
   411	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
   412	
   413	# --- Test D: Vol crush pattern (post vs pre) ---
   414	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
   415	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
   416	
   417	# --- Test E: VIX predictive regression ---
   418	vix_valid = df.dropna(subset=["pre_vix"])
   419	if len(vix_valid) > 10:
   420	    from numpy.polynomial.polynomial import polyfit
   421	    X_vix = vix_valid["pre_vix"].values
   422	    Y_abs = vix_valid["event_abs_return"].values
   423	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
   424	    # correlation and p-value
   425	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
   426	    # also spearman
   427	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
   428	else:
   429	    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6
   430	
   431	# --- Test F: Pre-event VIX change (buildup) ---
   432	# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
   433	vix_buildup = []
   434	for nfp_date in valid_nfp:
   435	    pos = idx_list.index(nfp_date)
   436	    pre5 = spy.iloc[pos-5]
   437	    pre1 = spy.iloc[pos-1]
   438	    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
   439	        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))
   440	
   441	t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
   442	
   443	# --- Test G: Seasonal analysis (by month) ---
   444	monthly_stats = {}
   445	for month in range(1, 13):
   446	    month_data = df[df["month"] == month]["event_abs_return"]
   447	    if len(month_data) >= 5:
   448	        monthly_stats[str(month)] = {
   449	            "n": int(len(month_data)),
   450	            "mean_abs_return": float(month_data.mean()),
   451	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
   452	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
   453	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
   454	        }
   455	
   456	# --- Test H: Regime analysis (high VIX vs low VIX) ---
   457	vix_median = df["pre_vix"].median()
   458	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
   459	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
   460	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)

exec
/bin/zsh -lc "jq 'keys' experiments/k528/k528_nfp_event_study_results.json
jq '{metadata, sample, baseline, tests, summary, correction_audit}' experiments/k528/k528_nfp_event_study_results.json | sed -n '1,520p'
jq 'keys' experiments/k528/k528_nfp_official_dates_results.json
jq '.' experiments/k528/k528_nfp_official_dates_results.json | sed -n '1,500p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
[
  "april_nfp",
  "claim_scope_note",
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
  "metadata": null,
  "sample": {
    "total_nfp_events": 253,
    "date_range": "2005-02-04 to 2026-03-06",
    "non_nfp_trading_days": 5087,
    "friday_baseline_days": 835,
    "nfp_days_on_friday": 237,
    "event_mapping_audit": {
      "n_official_releases": 254,
      "n_mapped_to_sessions": 254,
      "n_shifted_to_next_session": 6,
      "n_outside_price_sample": 0,
      "outside_price_sample_dates": [],
      "n_excluded_for_window_buffer": 1,
      "window_excluded_dates": [
        "2005-01-07"
      ],
      "n_valid_events": 253
    },
    "calendar_completeness": {
      "n_months_expected": 253,
      "known_missing_months": [
        "2025-10"
      ]
    }
  },
  "baseline": null,
  "tests": null,
  "summary": null,
  "correction_audit": null
}
[
  "after_source",
  "article_correction",
  "before_source",
  "calendar_diff",
  "event_date_source",
  "experiment_id",
  "generated_at",
  "items",
  "n_claims_audited",
  "n_claims_flipped",
  "title",
  "win_rate_definition"
]
{
  "experiment_id": "K528",
  "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
  "generated_at": "2026-07-19T08:16:52.824497+00:00",
  "before_source": "k528_nfp_event_study_results_PROXY_SUPERSEDED.json",
  "after_source": "k528_nfp_event_study_results.json",
  "event_date_source": {
    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
    "accessor": "volpred.data.event_dates.nfp_release_dates",
    "fallback": "none - the run raises if the calendar is unreachable",
    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
  },
  "calendar_diff": {
    "proxy_only_dates": [
      "2005-07-01",
      "2006-03-03",
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
      "2013-03-01",
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
      "2024-03-01",
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
      "2013-03-08",
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
      "2020-05-08",
      "2020-07-02",
      "2021-01-08",
      "2021-10-08",
      "2022-07-08",
      "2023-03-10",
      "2023-12-08",
      "2024-03-08",
      "2025-01-10",
      "2025-07-03",
      "2025-11-20",
      "2025-12-16",
      "2026-01-09",
      "2026-02-11"
    ],
    "dates_in_common": 212,
    "n_proxy": 254,
    "n_official": 253,
    "nfp_days_on_friday_official": 237
  },
  "win_rate_definition": "share of the sample exceeding the MEDIAN of its comparison group; 0.5 under the null",
  "items": {
    "vol_ratio_vs_all": {
      "label": "NFP vs all non-NFP days (article: 1.10x)",
      "before": {
        "mean_ratio": 1.1035360772013734,
        "nfp_mean": 0.008420922409653335,
        "baseline_mean": 0.0076308537469923455,
        "p_value": 0.1283682008960355,
        "significant_5pct": false,
        "n": 254,
        "median_ratio": 1.189607971494038,
        "win_rate": 0.5551181102362205
      },
      "after": {
        "mean_ratio": 1.1079551223284374,
        "nfp_mean": 0.008453062192235669,
        "baseline_mean": 0.007629426519073289,
        "p_value": 0.1115348306661545,
        "significant_5pct": false,
        "n": 253,
        "median_ratio": 1.1924408913550162,
        "win_rate": 0.5612648221343873
      },
      "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "vol_ratio_vs_friday": {
      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
      "before": {
        "mean_ratio": 1.168212716801256,
        "p_value": 0.03354366521379227,
        "significant_5pct": true,
        "n": 254,
        "nfp_days_on_friday": 254,
        "median_ratio": 1.2091317875797052,
        "win_rate": 0.562992125984252
      },
      "after": {
        "mean_ratio": 1.1901328478556155,
        "p_value": 0.020198459584478665,
        "significant_5pct": true,
        "n": 237,
        "nfp_days_on_friday": 237,
        "median_ratio": 1.2225564362044339,
        "win_rate": 0.569620253164557,
        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
        "diagnostic_mixed_weekday": {
          "mean_ratio": 1.177889180968137,
          "p_value": 0.024879138655181043,
          "significant_5pct": true,
          "n": 253,
          "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
        }
      },
      "note": "Two things changed at once here, and they must not be conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: under the proxy every NFP day was a Friday by construction, so this test compared Fridays with Fridays; on the official calendar the event group is a weekday mixture, so the like-for-like test now restricts the event group to Friday releases. `diagnostic_mixed_weekday` holds the date-corrected value of the OLD estimand, which is the apples-to-apples comparison against the `before` column.",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "regime_ratio": {
      "label": "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
      "before": {
        "mean_ratio": 2.1670599373202153,
        "high_mean": 0.011524027931522324,
        "low_mean": 0.005317816887784345,
        "n_high": 127,
        "n_low": 127,
        "p_value": 2.8361186837189765E-10,
        "significant_5pct": true,
        "median_ratio": 2.2653573776192792,
        "win_rate": 0.7165354330708661
      },
      "after": {
        "mean_ratio": 2.0272879955976624,
        "high_mean": 0.011276173536394039,
        "low_mean": 0.005562196175817499,
        "n_high": 128,
        "n_low": 125,
        "p_value": 4.552281833425917E-9,
        "significant_5pct": true,
        "median_ratio": 2.0732630504358394,
        "win_rate": 0.6953125
      },
      "note": "",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "vix_correlation": {
      "label": "Pre-event VIX vs event-day |return| (article: r=0.45)",
      "before": {
        "pearson_r": 0.45116558631194703,
        "pearson_p": 3.854493703611817E-14,
        "spearman_rho": 0.3766062270606868,
        "spearman_p": 5.561878132730772E-10,
        "slope_pct_per_vix_pt": 0.04387491083793095,
        "n": 254,
        "significant_5pct": true
      },
      "after": {
        "pearson_r": 0.44043736398798927,
        "pearson_p": 1.9814384001854257E-13,
        "spearman_rho": 0.3455048873701663,
        "spearman_p": 1.6699985504624933E-8,
        "slope_pct_per_vix_pt": 0.042561778477078566,
        "n": 253,
        "significant_5pct": true
      },
      "note": "",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "vix_median_threshold": {
      "label": "VIX median split (article: 16.71)",
      "before": {
        "threshold": 16.710000038146973,
        "n": 254,
        "places_20260701_vix_1659_in": "low"
      },
      "after": {
        "threshold": 16.690000534057617,
        "n": 253,
        "places_20260701_vix_1659_in": "low"
      },
      "note": "",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    },
    "sample": {
      "label": "NFP event sample (article: 254 events)",
      "before": {
        "n": 254,
        "date_range": "2005-02-04 to 2026-03-06",
        "non_nfp_trading_days": 5086
      },
      "after": {
        "n": 253,
        "date_range": "2005-02-04 to 2026-03-06",
        "non_nfp_trading_days": 5087,
        "dates_in_common": 212,
        "proxy_only_dates": [
          "2005-07-01",
          "2006-03-03",
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
          "2013-03-01",
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
          "2024-03-01",
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
          "2013-03-08",
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
          "2020-05-08",
          "2020-07-02",
          "2021-01-08",
          "2021-10-08",
          "2022-07-08",
          "2023-03-10",
          "2023-12-08",
          "2024-03-08",
          "2025-01-10",
          "2025-07-03",
          "2025-11-20",
          "2025-12-16",
          "2026-01-09",
          "2026-02-11"
        ]
      },
      "note": "Equal counts do not mean equal samples -- check dates_in_common.",
      "verdict": "NUMERIC_ADJUSTMENT",
      "verdict_reasons": []
    }
  },
  "n_claims_flipped": 0,
  "n_claims_audited": 6,
  "article_correction": {
    "article_id": "mile_35eef830",
    "status": "validated_not_applied",
    "n_replacements": 19,
    "all_matched_exactly_once": true,
    "supersedes": {
      "voided_list_size": 18,
      "voided_at": "2026-07-19",
      "reason": "the 18-item list was built against a rerun whose accessor picked off-cycle ALFRED entries for six months, which pushed the NFP-vs-Friday test across the 5% line. It would have retracted a finding that is in fact correct."
    },
    "directional_claims_changed": 0,
    "replacements": [
      {
        "from": "總共 254 次 NFP 公布日的資料算過一遍",
        "to": "總共 253 次 NFP 公布日的資料算過一遍",
        "hits": 1
      },
      {
        "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
        "to": "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
        "hits": 1
      },
      {
        "from": "換句話說，這 1.10 倍的差距",
        "to": "換句話說，這 1.11 倍的差距",
        "hits": 1
      },
      {
        "from": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
        "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
        "hits": 1
      },
      {
        "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
        "to": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
        "hits": 1
      },
      {
        "from": "那 254 次 NFP 日裡",
        "to": "那 253 次 NFP 日裡",
        "hits": 1
      },
      {
        "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
        "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
        "hits": 1
      },
      {
        "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
        "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
        "hits": 1
      },
      {
        "from": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
        "to": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
        "hits": 1
      },
      {
        "from": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
        "to": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
        "hits": 1
      },
      {
        "from": "貼在歷史分界線 16.71 的下緣",
        "to": "貼在歷史分界線 16.69 的下緣",
        "hits": 1
      },
      {
        "from": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
        "to": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
        "hits": 1
      },
      {
        "from": "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
        "to": "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
        "hits": 1
      },
      {
        "from": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。",
        "to": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準，對週五基準是 1.19 倍、達到顯著水準。",
        "hits": 1
      },
      {
        "from": "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
        "to": "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
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
        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。另有一項口徑調整：初版的 NFP 全部落在週五，週五基準比較是同星期別對同星期別；官方日曆下有 16 場不在週五，因此該比較改為只取在週五公布的 237 場，維持兩邊星期別一致。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
        "hits": 1
      },
      {
        "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
        "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
        "hits": 1
      }
    ],
    "apply_result": null,
    "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
  }
}

codex
已抓到第一個值得警戒的結構問題：實驗層宣稱「同月多筆會 raise」，但共用 accessor 在進入該檢查前已先按月 `min()` 去重，因此 live 路徑根本看不到重複；而 13–110 天 cadence 也無法辨識「同月較早的 off-cycle 假日期」。我會用具體反例驗證它是否能靜默通過，再判斷是否升為 blocker。統計驗算則會從逐事件資料與控制組 moments 重新算，不只抄 JSON 欄位。
exec
/bin/zsh -lc "jq '.main_results, .statistical_tests, .data_source, .claim_scope_note, .conclusions' experiments/k528/k528_nfp_event_study_results.json
jq '.event_data | length' experiments/k528/k528_nfp_event_study_results.json
jq '.event_data[0], .event_data[-1]' experiments/k528/k528_nfp_event_study_results.json
jq '.main_results, .statistical_tests, .sample, .event_data|length' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '460,660p'
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '660,940p'
nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '940,1135p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
{
  "nfp_avg_abs_return": 0.008453062192235669,
  "nfp_avg_abs_return_pct": "0.845%",
  "non_nfp_avg_abs_return": 0.007629426519073289,
  "non_nfp_avg_abs_return_pct": "0.763%",
  "friday_baseline_abs_return": 0.0071764494731905775,
  "vol_ratio_vs_all": 1.1079551223284374,
  "vol_ratio_vs_friday": 1.1901328478556155
}
{
  "A_nfp_vs_all": {
    "test": "Welch t-test",
    "t_stat": 1.596241850709586,
    "p_value": 0.1115348306661545,
    "significant_5pct": false
  },
  "B_nfp_vs_friday": {
    "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
    "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
    "n_event": 237,
    "n_control": 835,
    "vol_ratio": 1.1901328478556155,
    "t_stat": 2.332682989591967,
    "p_value": 0.020198459584478665,
    "significant_5pct": true,
    "excluded_non_friday_events": {
      "n": 16,
      "mean_abs_return": 0.0071515462261143095
    }
  },
  "B_diagnostic_mixed_weekday": {
    "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
    "status": "DIAGNOSTIC ONLY - do not quote",
    "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
    "vol_ratio": 1.177889180968137,
    "t_stat": 2.2515875177085047,
    "p_value": 0.024879138655181043,
    "significant_5pct": true
  },
  "C_wilcoxon": {
    "test": "Mann-Whitney U (one-sided)",
    "u_stat": 712704.0,
    "p_value": 0.001918721963396258,
    "significant_5pct": true
  },
  "D_vol_crush": {
    "test": "One-sample t-test (post-pre diff)",
    "pre_avg": 0.007787024581397933,
    "post_avg": 0.0076873544749868,
    "diff": -0.0000996701064111322,
    "t_stat": -0.31069924923269754,
    "p_value": 0.7562860985174406,
    "vol_crush_present": false
  },
  "E_vix_predictive": {
    "test": "Pearson + Spearman correlation",
    "pearson_r": 0.44043736398798927,
    "pearson_p": 1.9814384001854257E-13,
    "spearman_rho": 0.3455048873701663,
    "spearman_p": 1.6699985504624933E-8,
    "slope": 0.00042561778477078567,
    "interpretation": "1pt VIX → 0.0426% more |return|"
  },
  "F_vix_buildup": {
    "test": "One-sample t-test (T-5 to T-1 VIX change)",
    "mean_change": 0.08312253989721004,
    "t_stat": 0.44978438962865197,
    "p_value": 0.653252559944604,
    "anticipatory_buildup": false
  }
}
"yfinance (SPY, ^VIX), 2005-01 to 2026-03"
"Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6)."
[
  "Welch mean-difference, NFP vs all non-NFP days: 1.11x, p=0.1115 (does not reject at 5%)",
  "Welch mean-difference, Friday NFP vs Friday non-NFP (weekday held fixed): 1.19x, p=0.0202 (rejects at 5%; n=237 vs 835)",
  "Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: p=0.00192 (rejects at 5%)",
  "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, so a rank test can detect a location shift the Welch mean test cannot. Report both; do not summarise them as a single verdict.",
  "No significant vol crush pattern (p=0.7563)",
  "Pre-event VIX predicts event vol (r=0.440, p=0.0000)"
]
253
{
  "date": "2005-02-04",
  "year": 2005,
  "month": 2,
  "weekday": 4,
  "event_return": 0.010676158613085907,
  "event_abs_return": 0.010676158613085907,
  "pre_avg_abs_return": 0.0036382030234154207,
  "post_avg_abs_return": 0.004437752197660916,
  "pre_vix": 11.789999961853027,
  "event_vix": 11.210000038146973,
  "post_vix_1d": 11.729999542236328,
  "vix_change_event": -0.5799999237060547,
  "high_low_range": 0.012060192196264854,
  "volume_ratio": 0.9459350091597117
}
{
  "date": "2026-03-06",
  "year": 2026,
  "month": 3,
  "weekday": 4,
  "event_return": -0.01310712873041986,
  "event_abs_return": 0.01310712873041986,
  "pre_avg_abs_return": 0.005363130090510459,
  "post_avg_abs_return": 0.006493460638204107,
  "pre_vix": 23.75,
  "event_vix": 29.489999771118164,
  "post_vix_1d": 25.5,
  "vix_change_event": 5.739999771118164,
  "high_low_range": 0.00944402798986296,
  "volume_ratio": 1.0906826345022151
}
7
6
4
254
   460	            "n": int(len(month_data)),
   461	            "mean_abs_return": float(month_data.mean()),
   462	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
   463	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
   464	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
   465	        }
   466	
   467	# --- Test H: Regime analysis (high VIX vs low VIX) ---
   468	vix_median = df["pre_vix"].median()
   469	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
   470	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
   471	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
   472	
   473	# --- Test I: Time trend (has NFP impact changed over time?) ---
   474	# Split into halves
   475	midpoint = len(df) // 2
   476	first_half = df.iloc[:midpoint]["event_abs_return"]
   477	second_half = df.iloc[midpoint:]["event_abs_return"]
   478	t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
   479	
   480	# --- Test J: Event-day return direction ---
   481	pos_returns = (df["event_return"] > 0).sum()
   482	neg_returns = (df["event_return"] < 0).sum()
   483	# Binomial test: is there a directional bias?
   484	binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)
   485	
   486	print("\n" + "=" * 60)
   487	print("RESULTS")
   488	print("=" * 60)
   489	
   490	print(f"\n--- A. NFP vs All Non-NFP Days ---")
   491	print(f"  NFP day |return|:     {nfp_abs_returns.mean():.6f} ({nfp_abs_returns.mean()*100:.3f}%)")
   492	print(f"  Non-NFP |return|:     {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   493	print(f"  Vol ratio:            {vol_ratio_all:.3f}x")
   494	print(f"  t-stat:               {t_stat_all:.3f}")
   495	print(f"  p-value:              {p_val_all:.4f}")
   496	print(f"  Significant (5%):     {'YES' if p_val_all < 0.05 else 'NO'}")
   497	
   498	print(f"\n--- B. Friday NFP vs Friday Non-NFP (weekday held fixed) ---")
   499	print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
   500	print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   501	print(f"  Vol ratio (vs Fri):   {vol_ratio_fri:.3f}x")
   502	print(f"  t-stat:               {t_stat_fri:.3f}")
   503	print(f"  p-value:              {p_val_fri:.4f}")
   504	print(f"  Significant (5%):     {'YES' if p_val_fri < 0.05 else 'NO'}")
   505	print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
   506	      f"mean |ret|={nfp_nonfriday_abs.mean():.6f}" if len(nfp_nonfriday_abs) else "  [excluded] none")
   507	print(f"  [diagnostic, NOT a headline] all-events vs Friday baseline: "
   508	      f"{vol_ratio_fri_mixed:.4f}x, p={p_val_fri_mixed:.5f}")
   509	print(f"      ^ pre-correction estimand; p mixes in weekday composition")
   510	
   511	print(f"\n--- C. Wilcoxon Rank-Sum (non-parametric) ---")
   512	print(f"  U-stat:               {u_stat:.1f}")
   513	print(f"  p-value (one-sided):  {p_val_wilcox:.4f}")
   514	
   515	print(f"\n--- D. Vol Crush Pattern (Post vs Pre) ---")
   516	print(f"  Pre-event avg |ret|:  {df['pre_avg_abs_return'].mean():.6f}")
   517	print(f"  Post-event avg |ret|: {df['post_avg_abs_return'].mean():.6f}")
   518	print(f"  Difference:           {vol_crush.mean():.6f}")
   519	print(f"  t-stat:               {t_crush:.3f}")
   520	print(f"  p-value:              {p_crush:.4f}")
   521	print(f"  Vol crush present:    {'YES' if vol_crush.mean() < 0 and p_crush < 0.05 else 'NO'}")
   522	
   523	print(f"\n--- E. VIX Predictive Regression ---")
   524	if r_vix is not None:
   525	    print(f"  Pearson r:            {r_vix:.4f} (p={p_vix:.4f})")
   526	    print(f"  Spearman rho:         {rho_vix:.4f} (p={p_rho_vix:.4f})")
   527	    print(f"  Slope:                {slope:.8f}")
   528	    print(f"  Interpretation:       1pt VIX increase → {slope*100:.4f}% more |return|")
   529	
   530	print(f"\n--- F. VIX Buildup (T-5 to T-1) ---")
   531	if t_buildup is not None:
   532	    print(f"  Mean VIX change:      {np.mean(vix_buildup):.4f}")
   533	    print(f"  t-stat:               {t_buildup:.3f}")
   534	    print(f"  p-value:              {p_buildup:.4f}")
   535	    print(f"  Anticipatory buildup: {'YES' if np.mean(vix_buildup) > 0 and p_buildup < 0.05 else 'NO'}")
   536	
   537	print(f"\n--- G. Seasonal Pattern (by month) ---")
   538	print(f"  {'Month':<8} {'N':<5} {'Avg |Ret|':<12} {'Ratio':<8} {'t-stat':<8} {'p-val':<8}")
   539	month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
   540	               7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
   541	for m in range(1, 13):
   542	    if str(m) in monthly_stats:
   543	        ms = monthly_stats[str(m)]
   544	        sig = "*" if ms["p_val"] < 0.05 else ""
   545	        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")
   546	
   547	print(f"\n--- H. VIX Regime Analysis ---")
   548	print(f"  VIX median split:     {vix_median:.1f}")
   549	print(f"  High VIX NFP |ret|:   {high_vix.mean():.6f} (n={len(high_vix)})")
   550	print(f"  Low VIX NFP |ret|:    {low_vix.mean():.6f} (n={len(low_vix)})")
   551	print(f"  t-stat:               {t_regime:.3f}")
   552	print(f"  p-value:              {p_regime:.4f}")
   553	
   554	print(f"\n--- I. Time Trend (First Half vs Second Half) ---")
   555	print(f"  First half |ret|:     {first_half.mean():.6f} (n={len(first_half)}, ~{df['date'].iloc[0][:4]}-{df['date'].iloc[midpoint-1][:4]})")
   556	print(f"  Second half |ret|:    {second_half.mean():.6f} (n={len(second_half)}, ~{df['date'].iloc[midpoint][:4]}-{df['date'].iloc[-1][:4]})")
   557	print(f"  t-stat:               {t_trend:.3f}")
   558	print(f"  p-value:              {p_trend:.4f}")
   559	
   560	print(f"\n--- J. Directional Bias ---")
   561	print(f"  Positive returns:     {pos_returns}/{len(df)} ({pos_returns/len(df)*100:.1f}%)")
   562	print(f"  Negative returns:     {neg_returns}/{len(df)} ({neg_returns/len(df)*100:.1f}%)")
   563	print(f"  Binomial p-value:     {binom_p:.4f}")
   564	
   565	# ============================================================
   566	# 7. High-low range analysis (intraday vol proxy)
   567	# ============================================================
   568	print(f"\n--- K. Intraday Range (High-Low / Close) ---")
   569	nfp_range = df["high_low_range"].mean()
   570	non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
   571	range_ratio = nfp_range / non_nfp_range
   572	print(f"  NFP day range:        {nfp_range:.6f} ({nfp_range*100:.3f}%)")
   573	print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
   574	print(f"  Range ratio:          {range_ratio:.3f}x")
   575	
   576	# Volume analysis
   577	print(f"\n--- L. Volume Analysis ---")
   578	vol_ratio_data = df["volume_ratio"].dropna()
   579	print(f"  NFP/avg volume ratio: {vol_ratio_data.mean():.3f}x")
   580	print(f"  NFP volume > avg:     {(vol_ratio_data > 1).sum()}/{len(vol_ratio_data)} ({(vol_ratio_data > 1).mean()*100:.1f}%)")
   581	
   582	# ============================================================
   583	# 8. April NFP specific (for upcoming 04/03 article)
   584	# ============================================================
   585	print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
   586	april_nfp = df[df["month"] == 4]
   587	print(f"  April NFP events:     {len(april_nfp)}")
   588	print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
   589	print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
   590	print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
   591	if "4" in monthly_stats:
   592	    ms4 = monthly_stats["4"]
   593	    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")
   594	
   595	# ============================================================
   596	# 9. Summary conclusion
   597	# ============================================================
   598	print(f"\n{'=' * 60}")
   599	print("SUMMARY CONCLUSION")
   600	print("=" * 60)
   601	
   602	sig_level = 0.05
   603	conclusions = []
   604	
   605	# Each conclusion names the test it came from. The previous run collapsed
   606	# several tests into "insignificant across all tests" while the one-sided
   607	# Mann-Whitney in the same artifact was significant at p<0.01 -- a summary that
   608	# contradicted its own numbers. A Welch test on |return| is a test of MEANS;
   609	# it not rejecting is not a finding that the distributions match, and it is
   610	# never evidence that the effect is zero.
   611	conclusions.append(
   612	    f"Welch mean-difference, NFP vs all non-NFP days: {vol_ratio_all:.2f}x, "
   613	    f"p={p_val_all:.4f} ({'rejects' if p_val_all < sig_level else 'does not reject'} at 5%)"
   614	)
   615	conclusions.append(
   616	    f"Welch mean-difference, Friday NFP vs Friday non-NFP (weekday held fixed): "
   617	    f"{vol_ratio_fri:.2f}x, p={p_val_fri:.4f} "
   618	    f"({'rejects' if p_val_fri < sig_level else 'does not reject'} at 5%; "
   619	    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)})"
   620	)
   621	conclusions.append(
   622	    f"Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: "
   623	    f"p={p_val_wilcox:.5f} ({'rejects' if p_val_wilcox < sig_level else 'does not reject'} at 5%)"
   624	)
   625	if (p_val_all >= sig_level) != (p_val_wilcox >= sig_level):
   626	    conclusions.append(
   627	        "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, "
   628	        "so a rank test can detect a location shift the Welch mean test cannot. "
   629	        "Report both; do not summarise them as a single verdict."
   630	    )
   631	
   632	if vol_crush.mean() < 0 and p_crush < sig_level:
   633	    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
   634	else:
   635	    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")
   636	
   637	if r_vix is not None and p_vix < sig_level:
   638	    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
   639	else:
   640	    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")
   641	
   642	for c in conclusions:
   643	    print(f"  • {c}")
   644	
   645	print(f"\n  Practical implication:")
   646	print(f"    → Entry VIX regime is the larger and more reliably measured effect "
   647	      f"({high_vix.mean()/low_vix.mean():.2f}x, p={p_regime:.4g})")
   648	print(f"    → The NFP-day effect is smaller; mean and rank tests do not agree on it, "
   649	      f"so it is not established either way")
   650	print(f"    → Non-significance of a mean test is not evidence of no effect")
   651	
   652	# ============================================================
   653	# 9b. Correction audit: every published number, before vs after
   654	# ============================================================
   655	# A mean can sit still while the median and the win rate move underneath it,
   656	# so no claim is judged on its mean alone. Each item carries mean / median /
   657	# win rate / n / significance, and the flip test looks at all of them.
   658	print(f"\n{'=' * 60}")
   659	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
   660	print("=" * 60)
   660	print("=" * 60)
   661	
   662	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
   663	if not PROXY_PATH.exists():
   664	    raise FileNotFoundError(
   665	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
   666	        "only record of what the published article claimed. Do not regenerate it."
   667	    )
   668	proxy = json.loads(PROXY_PATH.read_text())
   669	
   670	
   671	def win_rate(sample, reference):
   672	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
   673	    ref_med = float(np.median(reference))
   674	    return float(np.mean(np.asarray(sample) > ref_med))
   675	
   676	
   677	# The proxy run only ever reported means, and a mean can hold still while the
   678	# median and the win rate move underneath it. Rather than leave the before-side
   679	# of those two columns null -- which would make the comparison unable to detect
   680	# exactly the failure it is looking for -- rebuild the proxy-era distributions
   681	# from the ARCHIVED per-event data. The dates come out of the archive, so this
   682	# reconstructs history without reintroducing a proxy calendar generator.
   683	proxy_events = proxy["event_data"]
   684	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
   685	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
   686	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
   687	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
   688	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
   689	
   690	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
   691	# mapped to a Monday because the first Friday was a market holiday. So the
   692	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
   693	# rebuild the proxy side under the SAME estimand the corrected run uses
   694	# (Friday events only) rather than comparing a mixed `before` against a
   695	# restricted `after` and calling the difference a correction effect.
   696	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
   697	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
   698	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
   699	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
   700	
   701	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   702	                       for e in proxy_events])
   703	_p_thr = proxy["regime_analysis"]["vix_median_split"]
   704	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   705	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   706	
   707	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
   708	# reconstruction is wrong and its medians cannot be trusted either.
   709	for _label, _rebuilt, _archived in (
   710	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   711	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   712	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   713	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   714	):
   715	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   716	        raise AssertionError(
   717	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   718	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   719	            "from a reconstruction that cannot reproduce the archived means."
   720	        )
   721	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   722	
   723	audit_items = {}
   724	
   725	
   726	def record(key, label, before, after, note=""):
   727	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   728	
   729	
   730	# --- 1.10x : NFP vs all non-NFP days ---
   731	record(
   732	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   733	    {
   734	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   735	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   736	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   737	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   738	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   739	        "n": proxy["sample"]["total_nfp_events"],
   740	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   741	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   742	    },
   743	    {
   744	        "mean_ratio": vol_ratio_all,
   745	        "nfp_mean": float(nfp_abs_returns.mean()),
   746	        "baseline_mean": baseline_abs_return,
   747	        "p_value": float(p_val_all),
   748	        "significant_5pct": bool(p_val_all < 0.05),
   749	        "n": int(len(df)),
   750	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   751	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   752	    },
   753	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   754	         "per-event data, not from the proxy run's own output (it only reported means).",
   755	)
   756	
   757	# --- 1.17x : NFP vs Friday-only baseline ---
   758	record(
   759	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   760	    {
   761	        # Same estimand as the `after` column: Friday events only.
   762	        "mean_ratio": proxy_ratio_fri_restricted,
   763	        "p_value": float(_p_p_fri),
   764	        "significant_5pct": bool(_p_p_fri < 0.05),
   765	        "n": int(len(proxy_nfp_friday_abs)),
   766	        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
   767	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
   768	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
   769	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   770	        "as_published_mixed_weekday": {
   771	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   772	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   773	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   774	            "n": proxy["sample"]["total_nfp_events"],
   775	            "note": (
   776	                "what the proxy run actually published: all 254 events (239 Friday, "
   777	                "15 Monday) against non-NFP Fridays. This is the number the article "
   778	                "quoted, so it is kept, but it is NOT the like-for-like comparison "
   779	                "against the corrected column."
   780	            ),
   781	        },
   782	    },
   783	    {
   784	        "mean_ratio": vol_ratio_fri,
   785	        "p_value": float(p_val_fri),
   786	        "significant_5pct": bool(p_val_fri < 0.05),
   787	        "n": int(len(nfp_friday_abs)),
   788	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   789	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
   790	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
   791	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   792	        "diagnostic_mixed_weekday": {
   793	            "mean_ratio": vol_ratio_fri_mixed,
   794	            "p_value": float(p_val_fri_mixed),
   795	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
   796	            "n": int(len(df)),
   797	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
   798	        },
   799	    },
   800	    note="Two things changed at once here, and they must not be conflated. "
   801	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: under "
   802	         "the proxy every NFP day was a Friday by construction, so this test "
   803	         "compared Fridays with Fridays; on the official calendar the event "
   804	         "group is a weekday mixture, so the like-for-like test now restricts "
   805	         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
   806	         "the date-corrected value of the OLD estimand, which is the apples-to-"
   807	         "apples comparison against the `before` column.",
   808	)
   809	
   810	# --- 2.17x : high-VIX vs low-VIX regime ---
   811	proxy_reg = proxy["regime_analysis"]
   812	record(
   813	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   814	    {
   815	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
   816	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
   817	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
   818	        "n_high": proxy_reg["n_high"],
   819	        "n_low": proxy_reg["n_low"],
   820	        "p_value": proxy_reg["p_value"],
   821	        "significant_5pct": proxy_reg["p_value"] < 0.05,
   822	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
   823	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
   824	    },
   825	    {
   826	        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
   827	        "high_mean": float(high_vix.mean()),
   828	        "low_mean": float(low_vix.mean()),
   829	        "n_high": int(len(high_vix)),
   830	        "n_low": int(len(low_vix)),
   831	        "p_value": float(p_regime),
   832	        "significant_5pct": bool(p_regime < 0.05),
   833	        "median_ratio": float(high_vix.median() / low_vix.median()),
   834	        "win_rate": win_rate(high_vix.values, low_vix.values),
   835	    },
   836	)
   837	
   838	# --- 0.45 : pre-event VIX correlation ---
   839	proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
   840	record(
   841	    "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
   842	    {
   843	        "pearson_r": proxy_e["pearson_r"],
   844	        "pearson_p": proxy_e["pearson_p"],
   845	        "spearman_rho": proxy_e["spearman_rho"],
   846	        "spearman_p": proxy_e["spearman_p"],
   847	        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
   848	        "n": proxy["sample"]["total_nfp_events"],
   849	        "significant_5pct": proxy_e["pearson_p"] < 0.05,
   850	    },
   851	    {
   852	        "pearson_r": float(r_vix),
   853	        "pearson_p": float(p_vix),
   854	        "spearman_rho": float(rho_vix),
   855	        "spearman_p": float(p_rho_vix),
   856	        "slope_pct_per_vix_pt": float(slope) * 100,
   857	        "n": int(len(vix_valid)),
   858	        "significant_5pct": bool(p_vix < 0.05),
   859	    },
   860	)
   861	
   862	# --- 16.71 : the VIX median that splits the regimes ---
   863	# The article uses this threshold to place a specific date (2026-07-01 VIX
   864	# 16.59) on the low-VIX side. If the threshold crosses 16.59 the article's
   865	# worked example inverts, so it is audited as a claim in its own right.
   866	proxy_thr = proxy_reg["vix_median_split"]
   867	record(
   868	    "vix_median_threshold", "VIX median split (article: 16.71)",
   869	    {
   870	        "threshold": proxy_thr,
   871	        "n": proxy["sample"]["total_nfp_events"],
   872	        "places_20260701_vix_1659_in": "low" if 16.59 < proxy_thr else "high",
   873	    },
   874	    {
   875	        "threshold": float(vix_median),
   876	        "n": int(df["pre_vix"].notna().sum()),
   877	        "places_20260701_vix_1659_in": "low" if 16.59 < float(vix_median) else "high",
   878	    },
   879	)
   880	
   881	# --- 254 : the sample itself ---
   882	proxy_dates = {r["date"] for r in proxy["event_data"]}
   883	new_dates = {r["date"] for r in results}
   884	record(
   885	    "sample", "NFP event sample (article: 254 events)",
   886	    {
   887	        "n": proxy["sample"]["total_nfp_events"],
   888	        "date_range": proxy["sample"]["date_range"],
   889	        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
   890	    },
   891	    {
   892	        "n": int(len(df)),
   893	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   894	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   895	        "dates_in_common": len(proxy_dates & new_dates),
   896	        "proxy_only_dates": sorted(proxy_dates - new_dates),
   897	        "official_only_dates": sorted(new_dates - proxy_dates),
   898	    },
   899	    note="Equal counts do not mean equal samples -- check dates_in_common.",
   900	)
   901	
   902	
   903	def verdict_for(key):
   904	    """Flip test: significance change, sign change, or a >10% move in the headline."""
   905	    b, a = audit_items[key]["before"], audit_items[key]["after"]
   906	    reasons = []
   907	    if b.get("significant_5pct") is not None and a.get("significant_5pct") is not None:
   908	        if bool(b["significant_5pct"]) != bool(a["significant_5pct"]):
   909	            reasons.append(
   910	                "significance flipped "
   911	                f"({'sig' if b['significant_5pct'] else 'NS'} -> "
   912	                f"{'sig' if a['significant_5pct'] else 'NS'})"
   913	            )
   914	    # The mean is not trusted on its own: the median and the win rate are
   915	    # checked independently, because the failure mode this audit exists to
   916	    # catch is a stable mean sitting on top of a moved distribution.
   917	    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
   918	        if field in b and field in a and b[field] and a[field]:
   919	            rel = abs(a[field] - b[field]) / abs(b[field])
   920	            if rel > 0.10:
   921	                reasons.append(f"{field} moved {rel * 100:.1f}%")
   922	    if b.get("win_rate") and a.get("win_rate"):
   923	        if abs(a["win_rate"] - b["win_rate"]) > 0.05:
   924	            reasons.append(
   925	                f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
   926	            )
   927	    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
   928	        reasons.append("the article's worked example changes regime")
   929	    return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons
   930	
   931	
   932	print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
   933	for key, item in audit_items.items():
   934	    v, reasons = verdict_for(key)
   935	    item["verdict"], item["verdict_reasons"] = v, reasons
   936	    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
   937	                     if f in item["before"]), None)
   938	    bf = item["before"].get(headline)
   939	    af = item["after"].get(headline)
   940	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
   940	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
   941	    print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
   942	    for r in reasons:
   943	        print(f"      - {r}")
   944	
   945	n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
   946	print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
   947	
   948	# ============================================================
   949	# 10. Save results
   950	# ============================================================
   951	print("\n[6/6] Saving results...")
   952	
   953	output = {
   954	    "experiment_id": "K528",
   955	    "title": "NFP Event Study on SPY Volatility",
   956	    "date": datetime.now(timezone.utc).isoformat(),
   957	    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
   958	    "event_date_source": {
   959	        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
   960	        "accessor": "volpred.data.event_dates.nfp_release_dates",
   961	        "fallback": "none - the run raises if the calendar is unreachable",
   962	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
   963	    },
   964	    "sample": {
   965	        "total_nfp_events": len(df),
   966	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   967	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   968	        "friday_baseline_days": int(friday_mask.sum()),
   969	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   970	        "event_mapping_audit": mapping_audit,
   971	        "calendar_completeness": calendar_completeness,
   972	    },
   973	    "main_results": {
   974	        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
   975	        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
   976	        "non_nfp_avg_abs_return": baseline_abs_return,
   977	        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
   978	        "friday_baseline_abs_return": friday_baseline,
   979	        "vol_ratio_vs_all": vol_ratio_all,
   980	        "vol_ratio_vs_friday": vol_ratio_fri,
   981	    },
   982	    "statistical_tests": {
   983	        "A_nfp_vs_all": {
   984	            "test": "Welch t-test",
   985	            "t_stat": float(t_stat_all),
   986	            "p_value": float(p_val_all),
   987	            "significant_5pct": bool(p_val_all < 0.05),
   988	        },
   989	        "B_nfp_vs_friday": {
   990	            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
   991	            "estimand": (
   992	                "weekday held fixed on both sides. Event group restricted to NFP "
   993	                "releases that trade on a Friday; the 11 non-Friday events are "
   994	                "excluded rather than compared against a pure-Friday control group."
   995	            ),
   996	            "n_event": int(len(nfp_friday_abs)),
   997	            "n_control": int(len(friday_non_nfp_abs)),
   998	            "vol_ratio": vol_ratio_fri,
   999	            "t_stat": float(t_stat_fri),
  1000	            "p_value": float(p_val_fri),
  1001	            "significant_5pct": bool(p_val_fri < 0.05),
  1002	            "excluded_non_friday_events": {
  1003	                "n": int(len(nfp_nonfriday_abs)),
  1004	                "mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
  1005	            },
  1006	        },
  1007	        "B_diagnostic_mixed_weekday": {
  1008	            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
  1009	            "status": "DIAGNOSTIC ONLY - do not quote",
  1010	            "why_not_a_headline": (
  1011	                "this is the pre-correction specification: a weekday-mixed event "
  1012	                "group against a pure-Friday control group, so the p-value absorbs "
  1013	                "any Friday-vs-other-weekday volatility difference. Retained solely "
  1014	                "so the correction audit can show what the contaminated estimand was "
  1015	                "worth (k528 Codex v2 finding 5)."
  1016	            ),
  1017	            "vol_ratio": vol_ratio_fri_mixed,
  1018	            "t_stat": float(t_stat_fri_mixed),
  1019	            "p_value": float(p_val_fri_mixed),
  1020	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
  1021	        },
  1022	        "C_wilcoxon": {
  1023	            "test": "Mann-Whitney U (one-sided)",
  1024	            "u_stat": float(u_stat),
  1025	            "p_value": float(p_val_wilcox),
  1026	            "significant_5pct": bool(p_val_wilcox < 0.05),
  1027	        },
  1028	        "D_vol_crush": {
  1029	            "test": "One-sample t-test (post-pre diff)",
  1030	            "pre_avg": float(df["pre_avg_abs_return"].mean()),
  1031	            "post_avg": float(df["post_avg_abs_return"].mean()),
  1032	            "diff": float(vol_crush.mean()),
  1033	            "t_stat": float(t_crush),
  1034	            "p_value": float(p_crush),
  1035	            "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
  1036	        },
  1037	        "E_vix_predictive": {
  1038	            "test": "Pearson + Spearman correlation",
  1039	            "pearson_r": float(r_vix) if r_vix else None,
  1040	            "pearson_p": float(p_vix) if p_vix else None,
  1041	            "spearman_rho": float(rho_vix) if rho_vix else None,
  1042	            "spearman_p": float(p_rho_vix) if p_rho_vix else None,
  1043	            "slope": float(slope) if slope else None,
  1044	            "interpretation": f"1pt VIX → {slope*100:.4f}% more |return|" if slope else None,
  1045	        },
  1046	        "F_vix_buildup": {
  1047	            "test": "One-sample t-test (T-5 to T-1 VIX change)",
  1048	            "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
  1049	            "t_stat": float(t_buildup) if t_buildup else None,
  1050	            "p_value": float(p_buildup) if p_buildup else None,
  1051	            "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
  1052	        },
  1053	    },
  1054	    "seasonal_analysis": monthly_stats,
  1055	    "regime_analysis": {
  1056	        "vix_median_split": float(vix_median),
  1057	        "high_vix_nfp_abs_return": float(high_vix.mean()),
  1058	        "low_vix_nfp_abs_return": float(low_vix.mean()),
  1059	        "n_high": int(len(high_vix)),
  1060	        "n_low": int(len(low_vix)),
  1061	        "t_stat": float(t_regime),
  1062	        "p_value": float(p_regime),
  1063	    },
  1064	    "time_trend": {
  1065	        "first_half_abs_return": float(first_half.mean()),
  1066	        "second_half_abs_return": float(second_half.mean()),
  1067	        "t_stat": float(t_trend),
  1068	        "p_value": float(p_trend),
  1069	    },
  1070	    "directional_bias": {
  1071	        "positive_count": int(pos_returns),
  1072	        "negative_count": int(neg_returns),
  1073	        "total": int(pos_returns + neg_returns),
  1074	        "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
  1075	        "binomial_p": binom_p,
  1076	    },
  1077	    "intraday_range": {
  1078	        "nfp_avg_range": float(nfp_range),
  1079	        "non_nfp_avg_range": float(non_nfp_range),
  1080	        "range_ratio": float(range_ratio),
  1081	    },
  1082	    "volume": {
  1083	        "avg_volume_ratio": float(vol_ratio_data.mean()),
  1084	        "pct_above_avg": float((vol_ratio_data > 1).mean()),
  1085	    },
  1086	    "april_nfp": {
  1087	        "n": int(len(april_nfp)),
  1088	        "avg_abs_return": float(april_nfp["event_abs_return"].mean()),
  1089	        "avg_signed_return": float(april_nfp["event_return"].mean()),
  1090	        "positive_rate": float((april_nfp["event_return"] > 0).mean()),
  1091	        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
  1092	    },
  1093	    "conclusions": conclusions,
  1094	    "practical_implication": (
  1095	        f"Entry VIX regime is the dominant and most reliably measured effect here: "
  1096	        f"{high_vix.mean()/low_vix.mean():.2f}x between high- and low-VIX NFP days "
  1097	        f"(p={p_regime:.4g}). The NFP-day effect itself is smaller and the tests do not "
  1098	        f"agree on it -- the Welch mean-difference test against all non-NFP days gives "
  1099	        f"{vol_ratio_all:.2f}x (p={p_val_all:.4f}) while the one-sided Mann-Whitney gives "
  1100	        f"p={p_val_wilcox:.5f}. Report both. A mean test that does not reject is not "
  1101	        "evidence that the effect is zero, and it does not license the claim that the "
  1102	        "event 'is not NFP itself'."
  1103	    ),
  1104	    "claim_scope_note": (
  1105	        "Every significance statement in this artifact is scoped to its own test. "
  1106	        "The superseded run summarised these as 'insignificant across all tests', "
  1107	        "which contradicted the one-sided Mann-Whitney result in the same file "
  1108	        "(k528 Codex v2 finding 6)."
  1109	    ),
  1110	    "references": [
  1111	        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
  1112	        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
  1113	        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
  1114	    ],
  1115	    "event_data": results,  # full per-event data
  1116	}
  1117	
  1118	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
  1119	write_json_atomic(out_path, output)
  1120	
  1121	print(f"  Saved to: {out_path}")
  1122	
  1123	# The correction audit is written separately: it is the artifact the article
  1124	# correction is justified against, and it must stay readable without wading
  1125	# through 254 events of per-day data.
  1126	audit_out = {
  1127	    "experiment_id": "K528",
  1128	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
  1129	    "generated_at": datetime.now(timezone.utc).isoformat(),
  1130	    "before_source": PROXY_PATH.name,
  1131	    "after_source": out_path.name,
  1132	    "event_date_source": output["event_date_source"],
  1133	    "calendar_diff": {
  1134	        "proxy_only_dates": sorted(proxy_dates - new_dates),
  1135	        "official_only_dates": sorted(new_dates - proxy_dates),

exec
/bin/zsh -lc "nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '670,820p'
jq '.items.vol_ratio_vs_friday' experiments/k528/k528_nfp_official_dates_results.json
jq '[.event_data[].weekday] | group_by(.) | map({weekday:.[0], n:length})' experiments/k528/k528_nfp_event_study_results.json
jq '[.event_data[].weekday] | group_by(.) | map({weekday:.[0], n:length})' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
jq '[.event_data[].date[0:10]] | map(strptime(\"%Y-%m-%d\")|mktime|strftime(\"%w\")) | group_by(.) | map({weekday:.[0], n:length})' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
jq '{superseded,do_not_cite,superseded_at,superseded_reason,keys:keys}' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
   670	
   671	def win_rate(sample, reference):
   672	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
   673	    ref_med = float(np.median(reference))
   674	    return float(np.mean(np.asarray(sample) > ref_med))
   675	
   676	
   677	# The proxy run only ever reported means, and a mean can hold still while the
   678	# median and the win rate move underneath it. Rather than leave the before-side
   679	# of those two columns null -- which would make the comparison unable to detect
   680	# exactly the failure it is looking for -- rebuild the proxy-era distributions
   681	# from the ARCHIVED per-event data. The dates come out of the archive, so this
   682	# reconstructs history without reintroducing a proxy calendar generator.
   683	proxy_events = proxy["event_data"]
   684	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
   685	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
   686	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
   687	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
   688	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
   689	
   690	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
   691	# mapped to a Monday because the first Friday was a market holiday. So the
   692	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
   693	# rebuild the proxy side under the SAME estimand the corrected run uses
   694	# (Friday events only) rather than comparing a mixed `before` against a
   695	# restricted `after` and calling the difference a correction effect.
   696	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
   697	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
   698	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
   699	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
   700	
   701	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   702	                       for e in proxy_events])
   703	_p_thr = proxy["regime_analysis"]["vix_median_split"]
   704	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   705	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   706	
   707	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
   708	# reconstruction is wrong and its medians cannot be trusted either.
   709	for _label, _rebuilt, _archived in (
   710	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   711	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   712	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   713	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   714	):
   715	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   716	        raise AssertionError(
   717	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   718	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   719	            "from a reconstruction that cannot reproduce the archived means."
   720	        )
   721	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   722	
   723	audit_items = {}
   724	
   725	
   726	def record(key, label, before, after, note=""):
   727	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   728	
   729	
   730	# --- 1.10x : NFP vs all non-NFP days ---
   731	record(
   732	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   733	    {
   734	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   735	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   736	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   737	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   738	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   739	        "n": proxy["sample"]["total_nfp_events"],
   740	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   741	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   742	    },
   743	    {
   744	        "mean_ratio": vol_ratio_all,
   745	        "nfp_mean": float(nfp_abs_returns.mean()),
   746	        "baseline_mean": baseline_abs_return,
   747	        "p_value": float(p_val_all),
   748	        "significant_5pct": bool(p_val_all < 0.05),
   749	        "n": int(len(df)),
   750	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   751	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   752	    },
   753	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   754	         "per-event data, not from the proxy run's own output (it only reported means).",
   755	)
   756	
   757	# --- 1.17x : NFP vs Friday-only baseline ---
   758	record(
   759	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   760	    {
   761	        # Same estimand as the `after` column: Friday events only.
   762	        "mean_ratio": proxy_ratio_fri_restricted,
   763	        "p_value": float(_p_p_fri),
   764	        "significant_5pct": bool(_p_p_fri < 0.05),
   765	        "n": int(len(proxy_nfp_friday_abs)),
   766	        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
   767	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
   768	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
   769	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   770	        "as_published_mixed_weekday": {
   771	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   772	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   773	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   774	            "n": proxy["sample"]["total_nfp_events"],
   775	            "note": (
   776	                "what the proxy run actually published: all 254 events (239 Friday, "
   777	                "15 Monday) against non-NFP Fridays. This is the number the article "
   778	                "quoted, so it is kept, but it is NOT the like-for-like comparison "
   779	                "against the corrected column."
   780	            ),
   781	        },
   782	    },
   783	    {
   784	        "mean_ratio": vol_ratio_fri,
   785	        "p_value": float(p_val_fri),
   786	        "significant_5pct": bool(p_val_fri < 0.05),
   787	        "n": int(len(nfp_friday_abs)),
   788	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   789	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
   790	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
   791	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   792	        "diagnostic_mixed_weekday": {
   793	            "mean_ratio": vol_ratio_fri_mixed,
   794	            "p_value": float(p_val_fri_mixed),
   795	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
   796	            "n": int(len(df)),
   797	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
   798	        },
   799	    },
   800	    note="Two things changed here and they are separated rather than conflated. "
   801	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
   802	         "event group is a weekday mixture while the control group is pure "
   803	         "Friday, so the test now restricts the event group to Friday releases. "
   804	         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
   805	         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
   806	         "simply never noticed. Both columns above therefore use the SAME "
   807	         "restricted estimand so the delta is attributable to the dates alone; "
   808	         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
   809	         "(after) hold the old estimand on each side for reference.",
   810	)
   811	
   812	# --- 2.17x : high-VIX vs low-VIX regime ---
   813	proxy_reg = proxy["regime_analysis"]
   814	record(
   815	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   816	    {
   817	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
   818	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
   819	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
   820	        "n_high": proxy_reg["n_high"],
{
  "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
  "before": {
    "mean_ratio": 1.1678258584088317,
    "p_value": 0.040941658051326435,
    "significant_5pct": true,
    "n": 239,
    "nfp_days_on_friday": 239,
    "median_ratio": 1.19826014827573,
    "win_rate": 0.5564853556485355,
    "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
    "as_published_mixed_weekday": {
      "mean_ratio": 1.168212716801256,
      "p_value": 0.03354366521379227,
      "significant_5pct": true,
      "n": 254,
      "note": "what the proxy run actually published: all 254 events (239 Friday, 15 Monday) against non-NFP Fridays. This is the number the article quoted, so it is kept, but it is NOT the like-for-like comparison against the corrected column."
    }
  },
  "after": {
    "mean_ratio": 1.1889914161952833,
    "p_value": 0.020855995901856498,
    "significant_5pct": true,
    "n": 237,
    "nfp_days_on_friday": 237,
    "median_ratio": 1.2184264509585134,
    "win_rate": 0.569620253164557,
    "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
    "diagnostic_mixed_weekday": {
      "mean_ratio": 1.1767586712062934,
      "p_value": 0.025694250730145685,
      "significant_5pct": true,
      "n": 253,
      "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
    }
  },
  "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to Friday releases. Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
  "verdict": "NUMERIC_ADJUSTMENT",
  "verdict_reasons": []
}
[
  {
    "weekday": 0,
    "n": 6
  },
  {
    "weekday": 1,
    "n": 2
  },
  {
    "weekday": 2,
    "n": 1
  },
  {
    "weekday": 3,
    "n": 7
  },
  {
    "weekday": 4,
    "n": 237
  }
]
[
  {
    "weekday": 0,
    "n": 15
  },
  {
    "weekday": 4,
    "n": 239
  }
]
[
  {
    "weekday": "1",
    "n": 15
  },
  {
    "weekday": "5",
    "n": 239
  }
]
{
  "superseded": true,
  "do_not_cite": true,
  "superseded_at": "2026-07-19",
  "superseded_reason": null,
  "keys": [
    "april_nfp",
    "audit_artifact",
    "conclusions",
    "data_source",
    "date",
    "directional_bias",
    "do_not_cite",
    "event_data",
    "event_date_source",
    "experiment_id",
    "impact_on_published_numbers",
    "intraday_range",
    "main_results",
    "note_for_machines",
    "practical_implication",
    "references",
    "regime_analysis",
    "retraction_reason",
    "sample",
    "seasonal_analysis",
    "statistical_tests",
    "superseded",
    "superseded_at",
    "superseded_by",
    "time_trend",
    "title",
    "volume"
  ]
}

exec
/bin/zsh -lc "git status --short --branch
git diff -- experiments/k528/k528_nfp_event_study.py experiments/k528/k528_nfp_official_dates_results.json experiments/k528/k528_nfp_event_study_results.json | sed -n '1,260p'
git log -3 --oneline --decorate" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 222ms:
## k528-nfp-official-dates
 M experiments/k528/k528_nfp_event_study.py
 M experiments/k528/k528_nfp_event_study_results.json
 M experiments/k528/k528_nfp_official_dates_results.json
diff --git a/experiments/k528/k528_nfp_event_study.py b/experiments/k528/k528_nfp_event_study.py
index 6983a642f..93ef63d38 100644
--- a/experiments/k528/k528_nfp_event_study.py
+++ b/experiments/k528/k528_nfp_event_study.py
@@ -337,20 +337,34 @@ print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
 # ============================================================
 print("\n[4/6] Computing non-NFP baseline...")
 
-nfp_set = set(valid_nfp)
+# Exclude EVERY NFP session from the control group, not just the ones that
+# survived the event-window filter. An event dropped for lacking a pre-window
+# is still an NFP day; leaving it in the control group is the exact failure this
+# experiment exists to fix ("dump real event days into the control group"), just
+# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
+nfp_set = set(nfp_trading_dates)
 non_nfp_mask = ~spy.index.isin(nfp_set)
 non_nfp = spy[non_nfp_mask]
+n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
+if n_leaked:
+    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
 
 baseline_abs_return = float(non_nfp["AbsReturn"].mean())
 baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
 baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
 
-# Friday-only baseline. Under the proxy every event was a Friday by
-# construction, so "all NFP events vs non-NFP Fridays" was a clean
-# weekday-held-fixed contrast. On the official calendar it is not: the event
-# group is a weekday mixture and the control group is pure Friday, so any
-# Friday-vs-other-weekday volatility difference loads directly onto the
-# estimate. The test below therefore holds weekday fixed on BOTH sides.
+# Friday-only baseline. The event group is a weekday MIXTURE while the control
+# group is pure Friday, so any Friday-vs-other-weekday volatility difference
+# loads straight onto the estimate. The test below holds weekday fixed on BOTH
+# sides.
+#
+# Note against the obvious story: this defect is NOT introduced by the date
+# correction. The proxy calendar was all-Friday by construction, but mapping
+# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
+# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
+# always there and is essentially unchanged; the old spec was already comparing
+# a mixed group against a pure-Friday control. Correcting the dates is what made
+# it visible, not what caused it.
 friday_mask = non_nfp.index.weekday == 4
 friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
 friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
@@ -377,13 +391,18 @@ vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
 # Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
 #   (i)  restrict the event group to Friday releases, or
 #   (ii) keep all events and use weekday-matched controls.
-# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
-# 253 -- cells that thin make (ii) a weighted average dominated by three
-# single-digit strata, with standard errors driven by the 1-observation
-# Wednesday cell. That is a noisier estimator of a harder-to-state quantity.
-# (i) answers one clean question: on a Friday, does an NFP release raise
-# volatility? It costs the 11 non-Friday events, which are reported below as a
-# separate descriptive line rather than dropped in silence.
+# This run takes (i). The non-Friday events are a handful of thin weekday cells
+# out of 253 -- cells that thin make (ii) a weighted average dominated by a few
+# single-digit strata, with standard errors driven by the smallest of them.
+# That is a noisier estimator of a harder-to-state quantity. (i) answers one
+# clean question: on a Friday, does an NFP release raise volatility? It costs
+# the non-Friday events, which are reported below as a separate descriptive
+# line rather than dropped in silence.
+#
+# The exclusion is not neutral and should not be sold as such: the excluded
+# events are quieter than the Friday ones, so restricting RAISES the ratio
+# relative to the mixed spec. That is a property of the estimand, not evidence
+# of a stronger effect. Both numbers are reported.
 nfp_friday_mask = (df["weekday"] == 4).values
 nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
 nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
@@ -668,6 +687,17 @@ proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
 proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
 proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
 
+# The proxy calendar was all-Friday by construction, but 15 of its 254 events
+# mapped to a Monday because the first Friday was a market holiday. So the
+# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
+# rebuild the proxy side under the SAME estimand the corrected run uses
+# (Friday events only) rather than comparing a mixed `before` against a
+# restricted `after` and calling the difference a correction effect.
+_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
+proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
+_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
+proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
+
 _p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
                        for e in proxy_events])
 _p_thr = proxy["regime_analysis"]["vix_median_split"]
@@ -728,13 +758,27 @@ record(
 record(
     "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
     {
-        "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
-        "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
-        "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
-        "n": proxy["sample"]["total_nfp_events"],
-        "nfp_days_on_friday": proxy["sample"]["total_nfp_events"],
-        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_fri_abs)),
-        "win_rate": win_rate(proxy_nfp_abs, proxy_fri_abs),
+        # Same estimand as the `after` column: Friday events only.
+        "mean_ratio": proxy_ratio_fri_restricted,
+        "p_value": float(_p_p_fri),
+        "significant_5pct": bool(_p_p_fri < 0.05),
+        "n": int(len(proxy_nfp_friday_abs)),
+        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
+        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
+        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
+        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
+        "as_published_mixed_weekday": {
+            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
+            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
+            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
+            "n": proxy["sample"]["total_nfp_events"],
+            "note": (
+                "what the proxy run actually published: all 254 events (239 Friday, "
+                "15 Monday) against non-NFP Fridays. This is the number the article "
+                "quoted, so it is kept, but it is NOT the like-for-like comparison "
+                "against the corrected column."
+            ),
+        },
     },
     {
         "mean_ratio": vol_ratio_fri,
@@ -753,14 +797,16 @@ record(
             "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
         },
     },
-    note="Two things changed at once here, and they must not be conflated. "
-         "(1) The dates were corrected. (2) The ESTIMAND was corrected: under "
-         "the proxy every NFP day was a Friday by construction, so this test "
-         "compared Fridays with Fridays; on the official calendar the event "
-         "group is a weekday mixture, so the like-for-like test now restricts "
-         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
-         "the date-corrected value of the OLD estimand, which is the apples-to-"
-         "apples comparison against the `before` column.",
+    note="Two things changed here and they are separated rather than conflated. "
+         "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
+         "event group is a weekday mixture while the control group is pure "
+         "Friday, so the test now restricts the event group to Friday releases. "
+         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
+         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
+         "simply never noticed. Both columns above therefore use the SAME "
+         "restricted estimand so the delta is attributable to the dates alone; "
+         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
+         "(after) hold the old estimand on each side for reference.",
 )
 
 # --- 2.17x : high-VIX vs low-VIX regime ---
diff --git a/experiments/k528/k528_nfp_event_study_results.json b/experiments/k528/k528_nfp_event_study_results.json
index 548670944..4e136ece5 100644
--- a/experiments/k528/k528_nfp_event_study_results.json
+++ b/experiments/k528/k528_nfp_event_study_results.json
@@ -1,7 +1,7 @@
 {
   "experiment_id": "K528",
   "title": "NFP Event Study on SPY Volatility",
-  "date": "2026-07-19T08:16:52.820209+00:00",
+  "date": "2026-07-19T08:21:14.483198+00:00",
   "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
   "event_date_source": {
     "source": "official BLS release calendar via ALFRED (FRED release id 50)",
@@ -12,8 +12,8 @@
   "sample": {
     "total_nfp_events": 253,
     "date_range": "2005-02-04 to 2026-03-06",
-    "non_nfp_trading_days": 5087,
-    "friday_baseline_days": 835,
+    "non_nfp_trading_days": 5086,
+    "friday_baseline_days": 834,
     "nfp_days_on_friday": 237,
     "event_mapping_audit": {
       "n_official_releases": 254,
@@ -35,66 +35,66 @@
     }
   },
   "main_results": {
-    "nfp_avg_abs_return": 0.008453062192235669,
+    "nfp_avg_abs_return": 0.008453069476984605,
     "nfp_avg_abs_return_pct": "0.845%",
-    "non_nfp_avg_abs_return": 0.007629426519073289,
+    "non_nfp_avg_abs_return": 0.007630641051729298,
     "non_nfp_avg_abs_return_pct": "0.763%",
-    "friday_baseline_abs_return": 0.0071764494731905775,
-    "vol_ratio_vs_all": 1.1079551223284374,
-    "vol_ratio_vs_friday": 1.1901328478556155
+    "friday_baseline_abs_return": 0.007183350064732795,
+    "vol_ratio_vs_all": 1.1077797290791085,
+    "vol_ratio_vs_friday": 1.1889914161952833
   },
   "statistical_tests": {
     "A_nfp_vs_all": {
       "test": "Welch t-test",
-      "t_stat": 1.596241850709586,
-      "p_value": 0.1115348306661545,
+      "t_stat": 1.593882436719971,
+      "p_value": 0.11206252056069128,
       "significant_5pct": false
     },
     "B_nfp_vs_friday": {
       "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
       "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
       "n_event": 237,
-      "n_control": 835,
-      "vol_ratio": 1.1901328478556155,
-      "t_stat": 2.332682989591967,
-      "p_value": 0.020198459584478665,
+      "n_control": 834,
+      "vol_ratio": 1.1889914161952833,
+      "t_stat": 2.3204773740207667,
+      "p_value": 0.020855995901856498,
       "significant_5pct": true,
       "excluded_non_friday_events": {
         "n": 16,
-        "mean_abs_return": 0.0071515462261143095
+        "mean_abs_return": 0.007151464151139632
       }
     },
     "B_diagnostic_mixed_weekday": {
       "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
       "status": "DIAGNOSTIC ONLY - do not quote",
       "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
-      "vol_ratio": 1.177889180968137,
-      "t_stat": 2.2515875177085047,
-      "p_value": 0.024879138655181043,
+      "vol_ratio": 1.1767586712062934,
+      "t_stat": 2.2389868815589358,
+      "p_value": 0.025694250730145685,
       "significant_5pct": true
     },
     "C_wilcoxon": {
       "test": "Mann-Whitney U (one-sided)",
-      "u_stat": 712704.0,
-      "p_value": 0.001918721963396258,
+      "u_stat": 712480.0,
+      "p_value": 0.001940321187311424,
       "significant_5pct": true
     },
     "D_vol_crush": {
       "test": "One-sample t-test (post-pre diff)",
-      "pre_avg": 0.007787024581397933,
-      "post_avg": 0.0076873544749868,
-      "diff": -9.96701064111322e-05,
-      "t_stat": -0.31069924923269754,
-      "p_value": 0.7562860985174406,
+      "pre_avg": 0.007787018553374247,
+      "post_avg": 0.007687361612714394,
+      "diff": -9.965694065985285e-05,
+      "t_stat": -0.31065889096205646,
+      "p_value": 0.7563167465955569,
       "vol_crush_present": false
     },
     "E_vix_predictive": {
       "test": "Pearson + Spearman correlation",
-      "pearson_r": 0.44043736398798927,
-      "pearson_p": 1.9814384001854257e-13,
-      "spearman_rho": 0.3455048873701663,
-      "spearman_p": 1.6699985504624933e-08,
-      "slope": 0.00042561778477078567,
6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
e42dc25ad fix(k528): NFP 事件日改用官方日曆重跑，1 項顯著性翻轉
50bb24870 (origin/main, origin/HEAD) dispatch(15:22): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(2)

codex
審查中 worktree 被另一程序改成 dirty；我已停止把「目前檔案」當目標，後續一律以使用者指定的 commit `6fd281901` 取證。這次漂移反而暴露一個實質問題：該 commit 只從控制組排除 `valid_nfp`，把因視窗緩衝被排除的真實 NFP 日（2005-01-07）誤留在 non-NFP 控制組；因此聲稱的 1.190/0.0202 與 1.1779/0.02488 是受污染數字。未提交 rerun 自己把它改成約 1.1890/0.02086 與 1.1768/0.02569。這會作為新 blocker 進一步獨立驗算。
exec
/bin/zsh -lc "rg --files storage | rg -i '(spy|yfinance|yf_|prices|market_data)' | head -n 200
find . -path '*/.cache/*' -o -path '*/storage/data/*' | rg -i '(spy|yfinance|sqlite|cache)' | head -n 200

git show 6fd281901:experiments/k528/k528_nfp_event_study_results.json | jq '{sample:.sample, main_results:.main_results, B:.statistical_tests.B_nfp_vs_friday, Bdiag:.statistical_tests.B_diagnostic_mixed_weekday}'
git show 6fd281901:experiments/k528/k528_nfp_official_dates_results.json | jq '.items.vol_ratio_vs_friday, .article_correction'

git show 6fd281901:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '330,420p'
git show 6fd281901:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '680,815p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 1522ms:
./storage/data/event_dates_cache
./storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-27.json
./storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-31.json
./storage/data/event_dates_cache/NFP_US_2005-02-01_2026-03-31.json
{
  "sample": {
    "total_nfp_events": 253,
    "date_range": "2005-02-04 to 2026-03-06",
    "non_nfp_trading_days": 5087,
    "friday_baseline_days": 835,
    "nfp_days_on_friday": 237,
    "event_mapping_audit": {
      "n_official_releases": 254,
      "n_mapped_to_sessions": 254,
      "n_shifted_to_next_session": 6,
      "n_outside_price_sample": 0,
      "outside_price_sample_dates": [],
      "n_excluded_for_window_buffer": 1,
      "window_excluded_dates": [
        "2005-01-07"
      ],
      "n_valid_events": 253
    },
    "calendar_completeness": {
      "n_months_expected": 253,
      "known_missing_months": [
        "2025-10"
      ]
    }
  },
  "main_results": {
    "nfp_avg_abs_return": 0.008453062192235669,
    "nfp_avg_abs_return_pct": "0.845%",
    "non_nfp_avg_abs_return": 0.007629426519073289,
    "non_nfp_avg_abs_return_pct": "0.763%",
    "friday_baseline_abs_return": 0.0071764494731905775,
    "vol_ratio_vs_all": 1.1079551223284374,
    "vol_ratio_vs_friday": 1.1901328478556155
  },
  "B": {
    "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
    "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
    "n_event": 237,
    "n_control": 835,
    "vol_ratio": 1.1901328478556155,
    "t_stat": 2.332682989591967,
    "p_value": 0.020198459584478665,
    "significant_5pct": true,
    "excluded_non_friday_events": {
      "n": 16,
      "mean_abs_return": 0.0071515462261143095
    }
  },
  "Bdiag": {
    "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
    "status": "DIAGNOSTIC ONLY - do not quote",
    "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
    "vol_ratio": 1.177889180968137,
    "t_stat": 2.2515875177085047,
    "p_value": 0.024879138655181043,
    "significant_5pct": true
  }
}
{
  "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
  "before": {
    "mean_ratio": 1.168212716801256,
    "p_value": 0.03354366521379227,
    "significant_5pct": true,
    "n": 254,
    "nfp_days_on_friday": 254,
    "median_ratio": 1.2091317875797052,
    "win_rate": 0.562992125984252
  },
  "after": {
    "mean_ratio": 1.1901328478556155,
    "p_value": 0.020198459584478665,
    "significant_5pct": true,
    "n": 237,
    "nfp_days_on_friday": 237,
    "median_ratio": 1.2225564362044339,
    "win_rate": 0.569620253164557,
    "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
    "diagnostic_mixed_weekday": {
      "mean_ratio": 1.177889180968137,
      "p_value": 0.024879138655181043,
      "significant_5pct": true,
      "n": 253,
      "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
    }
  },
  "note": "Two things changed at once here, and they must not be conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: under the proxy every NFP day was a Friday by construction, so this test compared Fridays with Fridays; on the official calendar the event group is a weekday mixture, so the like-for-like test now restricts the event group to Friday releases. `diagnostic_mixed_weekday` holds the date-corrected value of the OLD estimand, which is the apples-to-apples comparison against the `before` column.",
  "verdict": "NUMERIC_ADJUSTMENT",
  "verdict_reasons": []
}
{
  "article_id": "mile_35eef830",
  "status": "validated_not_applied",
  "n_replacements": 19,
  "all_matched_exactly_once": true,
  "supersedes": {
    "voided_list_size": 18,
    "voided_at": "2026-07-19",
    "reason": "the 18-item list was built against a rerun whose accessor picked off-cycle ALFRED entries for six months, which pushed the NFP-vs-Friday test across the 5% line. It would have retracted a finding that is in fact correct."
  },
  "directional_claims_changed": 0,
  "replacements": [
    {
      "from": "總共 254 次 NFP 公布日的資料算過一遍",
      "to": "總共 253 次 NFP 公布日的資料算過一遍",
      "hits": 1
    },
    {
      "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
      "to": "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
      "hits": 1
    },
    {
      "from": "換句話說，這 1.10 倍的差距",
      "to": "換句話說，這 1.11 倍的差距",
      "hits": 1
    },
    {
      "from": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
      "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
      "hits": 1
    },
    {
      "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
      "to": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
      "hits": 1
    },
    {
      "from": "那 254 次 NFP 日裡",
      "to": "那 253 次 NFP 日裡",
      "hits": 1
    },
    {
      "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
      "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
      "hits": 1
    },
    {
      "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
      "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
      "hits": 1
    },
    {
      "from": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
      "to": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
      "hits": 1
    },
    {
      "from": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
      "to": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
      "hits": 1
    },
    {
      "from": "貼在歷史分界線 16.71 的下緣",
      "to": "貼在歷史分界線 16.69 的下緣",
      "hits": 1
    },
    {
      "from": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
      "to": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
      "hits": 1
    },
    {
      "from": "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
      "to": "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
      "hits": 1
    },
    {
      "from": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。",
      "to": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準，對週五基準是 1.19 倍、達到顯著水準。",
      "hits": 1
    },
    {
      "from": "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
      "to": "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
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
      "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。另有一項口徑調整：初版的 NFP 全部落在週五，週五基準比較是同星期別對同星期別；官方日曆下有 16 場不在週五，因此該比較改為只取在週五公布的 237 場，維持兩邊星期別一致。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
      "hits": 1
    },
    {
      "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
      "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
      "hits": 1
    }
  ],
  "apply_result": null,
  "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
}
   330	
   331	df = pd.DataFrame(results)
   332	print(f"  Events with complete data: {len(df)}")
   333	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
   334	
   335	# ============================================================
   336	# 5. Non-NFP baseline calculation
   337	# ============================================================
   338	print("\n[4/6] Computing non-NFP baseline...")
   339	
   340	nfp_set = set(valid_nfp)
   341	non_nfp_mask = ~spy.index.isin(nfp_set)
   342	non_nfp = spy[non_nfp_mask]
   343	
   344	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
   345	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
   346	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   347	
   348	# Friday-only baseline. Under the proxy every event was a Friday by
   349	# construction, so "all NFP events vs non-NFP Fridays" was a clean
   350	# weekday-held-fixed contrast. On the official calendar it is not: the event
   351	# group is a weekday mixture and the control group is pure Friday, so any
   352	# Friday-vs-other-weekday volatility difference loads directly onto the
   353	# estimate. The test below therefore holds weekday fixed on BOTH sides.
   354	friday_mask = non_nfp.index.weekday == 4
   355	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
   356	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
   357	
   358	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   359	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
   360	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   361	
   362	# ============================================================
   363	# 6. Statistical tests
   364	# ============================================================
   365	print("\n[5/6] Running statistical tests...")
   366	
   367	nfp_abs_returns = df["event_abs_return"].values
   368	non_nfp_abs_returns = non_nfp["AbsReturn"].values
   369	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
   370	
   371	# --- Test A: NFP vs all non-NFP days ---
   372	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
   373	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
   374	
   375	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
   376	#
   377	# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
   378	#   (i)  restrict the event group to Friday releases, or
   379	#   (ii) keep all events and use weekday-matched controls.
   380	# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
   381	# 253 -- cells that thin make (ii) a weighted average dominated by three
   382	# single-digit strata, with standard errors driven by the 1-observation
   383	# Wednesday cell. That is a noisier estimator of a harder-to-state quantity.
   384	# (i) answers one clean question: on a Friday, does an NFP release raise
   385	# volatility? It costs the 11 non-Friday events, which are reported below as a
   386	# separate descriptive line rather than dropped in silence.
   387	nfp_friday_mask = (df["weekday"] == 4).values
   388	nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
   389	nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
   390	
   391	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
   392	vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
   393	
   394	# Diagnostic ONLY -- the pre-correction specification, kept so the correction
   395	# audit can show what the contaminated estimand was worth. Not a headline
   396	# number and not eligible to be quoted: its p-value mixes in weekday
   397	# composition, which is exactly the defect being repaired.
   398	t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
   399	    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
   400	vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
   401	
   402	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
   403	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
   404	
   405	# --- Test D: Vol crush pattern (post vs pre) ---
   406	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
   407	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
   408	
   409	# --- Test E: VIX predictive regression ---
   410	vix_valid = df.dropna(subset=["pre_vix"])
   411	if len(vix_valid) > 10:
   412	    from numpy.polynomial.polynomial import polyfit
   413	    X_vix = vix_valid["pre_vix"].values
   414	    Y_abs = vix_valid["event_abs_return"].values
   415	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
   416	    # correlation and p-value
   417	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
   418	    # also spearman
   419	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
   420	else:
   680	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   681	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   682	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   683	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   684	):
   685	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   686	        raise AssertionError(
   687	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   688	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   689	            "from a reconstruction that cannot reproduce the archived means."
   690	        )
   691	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   692	
   693	audit_items = {}
   694	
   695	
   696	def record(key, label, before, after, note=""):
   697	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   698	
   699	
   700	# --- 1.10x : NFP vs all non-NFP days ---
   701	record(
   702	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   703	    {
   704	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   705	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   706	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   707	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   708	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   709	        "n": proxy["sample"]["total_nfp_events"],
   710	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   711	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   712	    },
   713	    {
   714	        "mean_ratio": vol_ratio_all,
   715	        "nfp_mean": float(nfp_abs_returns.mean()),
   716	        "baseline_mean": baseline_abs_return,
   717	        "p_value": float(p_val_all),
   718	        "significant_5pct": bool(p_val_all < 0.05),
   719	        "n": int(len(df)),
   720	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   721	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   722	    },
   723	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   724	         "per-event data, not from the proxy run's own output (it only reported means).",
   725	)
   726	
   727	# --- 1.17x : NFP vs Friday-only baseline ---
   728	record(
   729	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   730	    {
   731	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   732	        "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   733	        "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   734	        "n": proxy["sample"]["total_nfp_events"],
   735	        "nfp_days_on_friday": proxy["sample"]["total_nfp_events"],
   736	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_fri_abs)),
   737	        "win_rate": win_rate(proxy_nfp_abs, proxy_fri_abs),
   738	    },
   739	    {
   740	        "mean_ratio": vol_ratio_fri,
   741	        "p_value": float(p_val_fri),
   742	        "significant_5pct": bool(p_val_fri < 0.05),
   743	        "n": int(len(nfp_friday_abs)),
   744	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   745	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
   746	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
   747	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   748	        "diagnostic_mixed_weekday": {
   749	            "mean_ratio": vol_ratio_fri_mixed,
   750	            "p_value": float(p_val_fri_mixed),
   751	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
   752	            "n": int(len(df)),
   753	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
   754	        },
   755	    },
   756	    note="Two things changed at once here, and they must not be conflated. "
   757	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: under "
   758	         "the proxy every NFP day was a Friday by construction, so this test "
   759	         "compared Fridays with Fridays; on the official calendar the event "
   760	         "group is a weekday mixture, so the like-for-like test now restricts "
   761	         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
   762	         "the date-corrected value of the OLD estimand, which is the apples-to-"
   763	         "apples comparison against the `before` column.",
   764	)
   765	
   766	# --- 2.17x : high-VIX vs low-VIX regime ---
   767	proxy_reg = proxy["regime_analysis"]
   768	record(
   769	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   770	    {
   771	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
   772	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
   773	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
   774	        "n_high": proxy_reg["n_high"],
   775	        "n_low": proxy_reg["n_low"],
   776	        "p_value": proxy_reg["p_value"],
   777	        "significant_5pct": proxy_reg["p_value"] < 0.05,
   778	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
   779	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
   780	    },
   781	    {
   782	        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
   783	        "high_mean": float(high_vix.mean()),
   784	        "low_mean": float(low_vix.mean()),
   785	        "n_high": int(len(high_vix)),
   786	        "n_low": int(len(low_vix)),
   787	        "p_value": float(p_regime),
   788	        "significant_5pct": bool(p_regime < 0.05),
   789	        "median_ratio": float(high_vix.median() / low_vix.median()),
   790	        "win_rate": win_rate(high_vix.values, low_vix.values),
   791	    },
   792	)
   793	
   794	# --- 0.45 : pre-event VIX correlation ---
   795	proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
   796	record(
   797	    "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
   798	    {
   799	        "pearson_r": proxy_e["pearson_r"],
   800	        "pearson_p": proxy_e["pearson_p"],
   801	        "spearman_rho": proxy_e["spearman_rho"],
   802	        "spearman_p": proxy_e["spearman_p"],
   803	        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
   804	        "n": proxy["sample"]["total_nfp_events"],
   805	        "significant_5pct": proxy_e["pearson_p"] < 0.05,
   806	    },
   807	    {
   808	        "pearson_r": float(r_vix),
   809	        "pearson_p": float(p_vix),
   810	        "spearman_rho": float(rho_vix),
   811	        "spearman_p": float(p_rho_vix),
   812	        "slope_pct_per_vix_pt": float(slope) * 100,
   813	        "n": int(len(vix_valid)),
   814	        "significant_5pct": bool(p_vix < 0.05),
   815	    },

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 uv run python -c 'import requests,datetime as dt; u=\"https://query1.finance.yahoo.com/v8/finance/chart/SPY\"; p={\"period1\":int(dt.datetime(2005,1,1,tzinfo=dt.timezone.utc).timestamp()),\"period2\":int(dt.datetime(2005,1,12,tzinfo=dt.timezone.utc).timestamp()),\"interval\":\"1d\",\"events\":\"history\",\"includeAdjustedClose\":\"true\"}; r=requests.get(u,params=p,timeout=20); print(r.status_code,len(r.content)); d=r.json()[\"chart\"][\"result\"][0] if r.ok else None; print([(str(dt.datetime.fromtimestamp(t,dt.timezone.utc).date()),c) for t,c in zip(d[\"timestamp\"],d[\"indicators\"][\"quote\"][0][\"close\"])]) if d else None'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 exited 2 in 280ms:
error: failed to open file `/Users/yhlai0911/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import requests,datetime as dt; u=\"https://query1.finance.yahoo.com/v8/finance/chart/SPY\"; p={\"period1\":int(dt.datetime(2005,1,1,tzinfo=dt.timezone.utc).timestamp()),\"period2\":int(dt.datetime(2005,1,12,tzinfo=dt.timezone.utc).timestamp()),\"interval\":\"1d\",\"events\":\"history\",\"includeAdjustedClose\":\"true\"}; r=requests.get(u,params=p,timeout=20); print(r.status_code,len(r.content)); d=r.json()[\"chart\"][\"result\"][0] if r.ok else None; print([(str(dt.datetime.fromtimestamp(t,dt.timezone.utc).date()),c) for t,c in zip(d[\"timestamp\"],d[\"indicators\"][\"quote\"][0][\"close\"])]) if d else None'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 exited 1 in 117ms:
    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
socket.gaierror: [Errno 8] nodename nor servname provided, or not known

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 787, in urlopen
    response = self._make_request(
               ^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 488, in _make_request
    raise new_e
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 464, in _make_request
    self._validate_conn(conn)
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 1093, in _validate_conn
    conn.connect()
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connection.py", line 759, in connect
    self.sock = sock = self._new_conn()
                       ^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connection.py", line 211, in _new_conn
    raise NameResolutionError(self.host, self, e) from e
urllib3.exceptions.NameResolutionError: HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/adapters.py", line 644, in send
    resp = conn.urlopen(
           ^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 841, in urlopen
    retries = retries.increment(
              ^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/util/retry.py", line 535, in increment
    raise MaxRetryError(_pool, url, reason) from reason  # type: ignore[arg-type]
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
urllib3.exceptions.MaxRetryError: HTTPSConnectionPool(host='query1.finance.yahoo.com', port=443): Max retries exceeded with url: /v8/finance/chart/SPY?period1=1104537600&period2=1105488000&interval=1d&events=history&includeAdjustedClose=true (Caused by NameResolutionError("HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)"))

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<string>", line 1, in <module>
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/api.py", line 73, in get
    return request("get", url, params=params, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/api.py", line 59, in request
    return session.request(method=method, url=url, **kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/sessions.py", line 589, in request
    resp = self.send(prep, **send_kwargs)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/sessions.py", line 703, in send
    r = adapter.send(request, **kwargs)
        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/adapters.py", line 677, in send
    raise ConnectionError(e, request=request)
requests.exceptions.ConnectionError: HTTPSConnectionPool(host='query1.finance.yahoo.com', port=443): Max retries exceeded with url: /v8/finance/chart/SPY?period1=1104537600&period2=1105488000&interval=1d&events=history&includeAdjustedClose=true (Caused by NameResolutionError("HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)"))

web search: 
web search: site:fred.stlouisfed.org release Employment Situation May 2006 2006-05-05 2006-05-08 ...
web search: 
web search: site:bls.gov/news.release/archives/empsit_08022024.htm ...
web search: 
web search: site:bls.gov/news.release/archives/empsit_05052006.htm ...
web search: 
web search: https://www.bls.gov/news.release/archives/empsit_05052006.htm
exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import json; from pathlib import Path; from volpred.data import event_dates as e; raw=json.loads(Path(\"tests/fixtures/fred_release_50_nfp_raw_20260719.json\").read_text())[\"release_dates\"]; e._fetch=lambda *a,**k:list(raw); got=e.release_dates(\"NFP_US\",\"2005-01-01\",\"2026-07-19\",use_cache=False); six=[str(d.date()) for d in got if str(d.date())[:7] in {\"2006-05\",\"2012-12\",\"2013-05\",\"2020-05\",\"2024-01\",\"2024-08\"}]; print(\"six_selected\",six,\"n\",len(got)); e._fetch=lambda *a,**k:[\"2024-01-05\",\"2024-02-01\",\"2024-02-02\",\"2024-03-08\"]; got=e.release_dates(\"NFP_US\",\"2024-01-01\",\"2024-03-31\",use_cache=False); print(\"earlier_offcycle_silently_selected\",[str(d.date()) for d in got])'

git show 6fd281901:experiments/k528/k528_nfp_event_study.py | PYTHONDONTWRITEBYTECODE=1 python -c 'import sys,ast,pandas as pd; s=sys.stdin.read(); tree=ast.parse(s); fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==\"check_calendar_is_complete\"); ns={\"pd\":pd,\"KNOWN_MISSING_MONTHS\":{\"2025-10\"}}; exec(compile(ast.Module(body=[fn],type_ignores=[]),\"k528\", \"exec\"),ns); f=ns[\"check_calendar_is_complete\"]; print(\"missing_first_month_passes\",f(pd.to_datetime([\"2005-02-04\",\"2005-03-04\"]),\"2005-01-01\",\"2005-03-27\")); print(\"missing_last_full_month_passes\",f(pd.to_datetime([\"2005-01-07\",\"2005-02-04\"]),\"2005-01-01\",\"2005-03-31\")); print(\"known_missing_unbounded\",f(pd.to_datetime([\"2025-09-05\",\"2025-11-20\"]),\"2025-09-01\",\"2025-11-30\"))'

PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess, numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([x[\"event_abs_return\"] for x in d[\"event_data\"]]); wd=np.array([x[\"weekday\"] for x in d[\"event_data\"]]); fri=a[wd==4]; non=a[wd"'!=4]; print("events",len(a),"friday",len(fri),"nonfriday",len(non)); print("means_all_friday_nonfriday",a.mean(),fri.mean(),non.mean()); b=d["main_results"]["friday_baseline_abs_return"]; print("ratios_recomputed",fri.mean()/b,a.mean()/b); print("committed",d["statistical_tests"]["B_nfp_vs_friday"]["vol_ratio"],d["statistical_tests"]["B_nfp_vs_friday"]["p_value"],d["statistical_tests"]["B_diagnostic_mixed_weekday"]["vol_ratio"],d["statistical_tests"]["B_diagnostic_mixed_weekday"]["p_value"]); print("nonfriday_quieter_by_pct",(non.mean()/fri.mean()-1)*100)'"'
" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 1617ms:
six_selected ['2006-05-05', '2012-12-07', '2013-05-03', '2020-05-08', '2024-01-05', '2024-08-02'] n 258
earlier_offcycle_silently_selected ['2024-01-05', '2024-02-01', '2024-03-08']
missing_first_month_passes {'n_months_expected': 1, 'known_missing_months': ['2025-10']}
missing_last_full_month_passes {'n_months_expected': 1, 'known_missing_months': ['2025-10']}
known_missing_unbounded {'n_months_expected': 1, 'known_missing_months': ['2025-10']}
events 253 friday 237 nonfriday 16
means_all_friday_nonfriday 0.008453062192235669 0.008540928249020233 0.0071515462261143095
ratios_recomputed 1.1901328478556155 1.177889180968137
committed 1.1901328478556155 0.020198459584478665 1.177889180968137 0.024879138655181043
nonfriday_quieter_by_pct -16.267342171681463

exec
/bin/zsh -lc "git show 6fd281901:experiments/k528/build_article_correction.py | nl -ba | sed -n '1,320p'
git show 6fd281901:experiments/k528/README.md | nl -ba | sed -n '1,240p'
git show 6fd281901:experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json | jq '{superseded,do_not_cite,superseded_at,superseded_by,retraction_reason,note_for_machines,audit_artifact}'
git show 6fd281901:experiments/k528/review_verdict.json | jq '.'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
     1	"""Build and validate the in-place correction to mile_35eef830.
     2	
     3	The article was published 2026-07-01 with headline numbers taken from K528,
     4	which dated every NFP to the first Friday of the month. On the official BLS
     5	calendar that proxy is wrong for ~20% of the sample, so every number moved a
     6	little. This script restates them.
     7	
     8	WHAT CHANGED SINCE THE VOIDED 2026-07-19 CORRECTION LIST
     9	--------------------------------------------------------
    10	An earlier 18-item list was built against a contaminated rerun and has been
    11	VOIDED IN FULL. That rerun used an event-date accessor which, for the six
    12	months where ALFRED returns two entries, picked the LATER one -- an off-cycle
    13	seasonal-factor revision rather than the Employment Situation report. Six event
    14	dates were therefore wrong (2006-05-08, 2012-12-12, 2013-05-06, 2020-05-11,
    15	2024-01-10, 2024-08-21).
    16	
    17	That mattered far more than six dates out of 253 suggests, because it moved the
    18	NFP-vs-Friday test across the 5% line. The voided list told readers that a
    19	result the article reported as significant was in fact not significant
    20	(1.17x p=0.0335 -> "1.15x p=0.057, 差一點過線但沒過"). On correct dates the
    21	comparison is 1.19x at p=0.020 -- significant, exactly as the article
    22	originally said. Applying that list would have published a retraction of a
    23	correct finding.
    24	
    25	So: no claim in this article reverses direction. Every replacement below is a
    26	numeric restatement, plus one estimand refinement that is disclosed in the note.
    27	
    28	THE ONE ESTIMAND CHANGE
    29	-----------------------
    30	Under the proxy every NFP landed on a Friday by construction, so "NFP days vs
    31	non-NFP Fridays" held weekday fixed for free. On the official calendar 16 of
    32	253 events are not Fridays, so that same comparison would put a weekday-mixed
    33	event group against a pure-Friday control group and let the Friday effect leak
    34	into the estimate. The corrected test restricts the event group to the 237
    35	Friday releases. This is stated in the article's correction note rather than
    36	folded in silently.
    37	
    38	WHY THIS SCRIPT DOES NOT WRITE BY DEFAULT
    39	-----------------------------------------
    40	`storage/reports/feed.json` is shared canonical state. `.claude/rules/worktree.md`
    41	forbids a worktree agent from touching it, and the reason is mechanical rather
    42	than ceremonial: this worktree carries its own 15MB checkout of feed.json, so a
    43	write here lands on a branch copy that is already stale the moment any other
    44	article is published, and merging it would silently revert them.
    45	
    46	So the split is: this script (run from the worktree) resolves and VALIDATES
    47	every replacement against the canonical article, proving each matches exactly
    48	once before anything is written. The main thread then runs it with --apply from
    49	the repo root, where the write is legitimate.
    50	
    51	    uv run python experiments/k528/build_article_correction.py            # validate, writes nothing
    52	    uv run python experiments/k528/build_article_correction.py --apply    # write + sync
    53	
    54	Validation uses `article_correction._splice`, the same resolver the writer
    55	uses, so a plan that validates here cannot fail differently there.
    56	"""
    57	
    58	from __future__ import annotations
    59	
    60	import argparse
    61	import json
    62	import os
    63	import tempfile
    64	from pathlib import Path
    65	
    66	REPO_ROOT = Path(__file__).resolve().parents[2]
    67	ARTICLE_ID = "mile_35eef830"
    68	AUDIT_PATH = Path(__file__).parent / "k528_nfp_official_dates_results.json"
    69	
    70	# The 18-item list built on 2026-07-19 against the contaminated rerun. Kept as a
    71	# record of what must NOT be applied, not as a fallback -- see the module
    72	# docstring. Anything that resurrects these strings is reintroducing a
    73	# retraction of a correct finding.
    74	VOIDED_20260719_LIST_SIZE = 18
    75	
    76	# (old, new). Each `old` must occur exactly once in the article body; the
    77	# resolver rejects the whole batch otherwise. Ordered as they appear.
    78	REPLACEMENTS: list[tuple[str, str]] = [
    79	    # --- sample size: 254 -> 253 ---
    80	    (
    81	        "總共 254 次 NFP 公布日的資料算過一遍",
    82	        "總共 253 次 NFP 公布日的資料算過一遍",
    83	    ),
    84	    # --- 1.10x -> 1.11x vs all non-NFP days (direction unchanged: NOT significant) ---
    85	    (
    86	        "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
    87	        "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
    88	    ),
    89	    (
    90	        "換句話說，這 1.10 倍的差距",
    91	        "換句話說，這 1.11 倍的差距",
    92	    ),
    93	    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
    94	    (
    95	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，"
    96	        "用 Welch t 檢定算下來，這個差距達到顯著水準。"
    97	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
    98	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場"
    99	        "落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致："
   100	        "這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。"
   101	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   102	    ),
   103	    (
   104	        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
   105	        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
   106	        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；"
   107	        "但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
   108	    ),
   109	    # --- regime split: threshold, group sizes, means, ratio ---
   110	    (
   111	        "那 254 次 NFP 日裡",
   112	        "那 253 次 NFP 日裡",
   113	    ),
   114	    (
   115	        "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
   116	        "分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；"
   117	        "VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
   118	        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
   119	        "分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；"
   120	        "VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
   121	    ),
   122	    # --- VIX correlation ---
   123	    (
   124	        "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
   125	        "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
   126	    ),
   127	    (
   128	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
   129	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
   130	    ),
   131	    # --- figure caption ---
   132	    (
   133	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
   134	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
   135	    ),
   136	    # --- the worked example: 2026-07-01 VIX 16.59 vs the threshold (still low regime) ---
   137	    (
   138	        "貼在歷史分界線 16.71 的下緣",
   139	        "貼在歷史分界線 16.69 的下緣",
   140	    ),
   141	    (
   142	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
   143	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
   144	    ),
   145	    (
   146	        "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
   147	        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
   148	    ),
   149	    # --- conclusions section (direction unchanged on both baselines) ---
   150	    (
   151	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
   152	        "對週五基準是 1.17 倍、達到顯著水準。",
   153	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準，"
   154	        "對週五基準是 1.19 倍、達到顯著水準。",
   155	    ),
   156	    (
   157	        "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
   158	        "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
   159	    ),
   160	    (
   161	        "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
   162	        "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
   163	    ),
   164	    (
   165	        "254 場歷史樣本加上 7/2 這場實測",
   166	        "253 場歷史樣本加上 7/2 這場實測",
   167	    ),
   168	    # --- methodology section + reader-facing errata ---
   169	    (
   170	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，"
   171	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
   172	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
   173	        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
   174	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n"
   175	        "**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。"
   176	        "與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，"
   177	        "遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，"
   178	        "但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n"
   179	        "**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、"
   180	        "真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整"
   181	        "（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。"
   182	        "另有一項口徑調整：初版的 NFP 全部落在週五，週五基準比較是同星期別對同星期別；"
   183	        "官方日曆下有 16 場不在週五，因此該比較改為只取在週五公布的 237 場，維持兩邊星期別一致。\n\n"
   184	        "**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。"
   185	        "逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
   186	    ),
   187	    (
   188	        "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
   189	        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
   190	    ),
   191	]
   192	
   193	
   194	def load_article_content(storage_dir: Path) -> str:
   195	    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
   196	    art = next((a for a in feed if isinstance(a, dict) and a.get("id") == ARTICLE_ID), None)
   197	    if art is None:
   198	        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
   199	    return art.get("content") or ""
   200	
   201	
   202	def validate(storage_dir: Path) -> list[dict]:
   203	    """Resolve every replacement against the live article. Raises if any does
   204	    not match exactly once, before a single byte is written."""
   205	    from volpred.publisher.article_correction import _splice
   206	
   207	    content = load_article_content(storage_dir)
   208	    spans = _splice(content, REPLACEMENTS)
   209	    return [
   210	        {"index": i, "hits": 1, "from": s["from"], "to": s["to"], "offset": s["start"]}
   211	        for i, s in enumerate(sorted(spans, key=lambda x: x["start"]))
   212	    ]
   213	
   214	
   215	def _write_json_atomic(path: Path, payload) -> None:
   216	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
   217	    try:
   218	        with os.fdopen(fd, "w", encoding="utf-8") as f:
   219	            json.dump(payload, f, indent=2, ensure_ascii=False)
   220	            f.write("\n")
   221	            f.flush()
   222	            os.fsync(f.fileno())
   223	        os.replace(tmp, path)
   224	    except BaseException:
   225	        try:
   226	            os.unlink(tmp)
   227	        except FileNotFoundError:
   228	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
   229	        raise
   230	
   231	
   232	def record_plan(validated: list[dict], applied: dict | None) -> None:
   233	    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
   234	    audit["article_correction"] = {
   235	        "article_id": ARTICLE_ID,
   236	        "status": "applied" if applied else "validated_not_applied",
   237	        "n_replacements": len(REPLACEMENTS),
   238	        "all_matched_exactly_once": True,
   239	        "supersedes": {
   240	            "voided_list_size": VOIDED_20260719_LIST_SIZE,
   241	            "voided_at": "2026-07-19",
   242	            "reason": (
   243	                "the 18-item list was built against a rerun whose accessor picked "
   244	                "off-cycle ALFRED entries for six months, which pushed the "
   245	                "NFP-vs-Friday test across the 5% line. It would have retracted a "
   246	                "finding that is in fact correct."
   247	            ),
   248	        },
   249	        "directional_claims_changed": 0,
   250	        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
   251	        "apply_result": applied,
   252	        "residual_gap": (
   253	            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
   254	            "and the two lazypack images still render proxy-era numbers. Text and images "
   255	            "now disagree; the article carries a visible note saying so. Regenerating and "
   256	            "re-uploading them is follow-up work outside this worktree's scope."
   257	        ),
   258	    }
   259	    _write_json_atomic(AUDIT_PATH, audit)
   260	
   261	
   262	def main() -> int:
   263	    ap = argparse.ArgumentParser(description=__doc__)
   264	    ap.add_argument("--apply", action="store_true",
   265	                    help="write the correction (main thread, repo root only)")
   266	    ap.add_argument("--record-plan", action="store_true",
   267	                    help="record the validated plan into the audit JSON without applying it")
   268	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
   269	    args = ap.parse_args()
   270	
   271	    storage_dir = Path(args.storage_dir)
   272	    validated = validate(storage_dir)
   273	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   274	    for v in validated:
   275	        head = v["from"].splitlines()[0][:64]
   276	        print(f"  @{v['offset']:>6}  {head}...")
   277	
   278	    applied = None
   279	    if args.apply:
   280	        from volpred.publisher.article_correction import apply_article_correction
   281	
   282	        applied = apply_article_correction(
   283	            ARTICLE_ID,
   284	            content_replacements=REPLACEMENTS,
   285	            summary=(
   286	                "K528 event dates corrected from a first-Friday proxy to the official BLS "
   287	                "release calendar. Sample 254 -> 253 events; headline numbers restated "
   288	                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
   289	                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
   290	                "now restricts the event group to the 237 Friday releases so weekday is "
   291	                "held fixed on both sides."
   292	            ),
   293	            action="content_correction",
   294	            storage_dir=str(storage_dir),
   295	        )
   296	        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
   297	              f"synced={applied['synced']}")
   298	
   299	    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
   300	    # finding 7). Recording is opt-in and never implicit.
   301	    if args.apply or args.record_plan:
   302	        record_plan(validated, applied)
   303	        print(f"plan recorded in {AUDIT_PATH.name}")
   304	    else:
   305	        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
   306	              "or --record-plan to persist the validated plan only.")
   307	    return 0
   308	
   309	
   310	if __name__ == "__main__":
   311	    raise SystemExit(main())
     1	# k528 — NFP 事件研究（SPY 波動率）
     2	
     3	- Experiment ID: `k528`
     4	- Created At: 2026-04-16T09:39:52.904348+00:00
     5	- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑；同日第二次修正見下）
     6	- Status: 已重跑，**方向性結論全部不變**，僅數值微調 + 一項口徑澄清
     7	
     8	## 問題描述
     9	
    10	NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
    11	事件本身」，還是「進場當下的市場狀態」？
    12	
    13	## 兩次修正，不要混為一談
    14	
    15	本實驗在 2026-07-19 被修正了**兩次**，第二次是修第一次修壞的地方。
    16	
    17	### 修正 1：事件日期從 proxy 換成官方日曆
    18	
    19	原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：
    20	
    21	- BLS 在參考週較晚的月份會改到**第二個週五**發布
    22	- 遇到聯邦假期會**提前**
    23	- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
    24	- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 237 場在週五
    25	
    26	錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
    27	同時把真的事件日丟進對照組。這是修正存在的理由。
    28	
    29	`get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
    30	`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
    31	release id 50），且**取不到就 raise，不回退 proxy**。
    32	
    33	### 修正 2（本輪）：accessor 的同月多筆選擇錯誤
    34	
    35	第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
    36	在**六個月份**會回兩筆：前一筆是 Employment Situation 正式報告，後一筆是年度季節調整
    37	因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：
    38	
    39	| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
    40	|---|---|---|
    41	| 2006-05 | 2006-05-05 | 2006-05-08 |
    42	| 2012-12 | 2012-12-07 | 2012-12-12 |
    43	| 2013-05 | 2013-05-03 | 2013-05-06 |
    44	| 2020-05 | 2020-05-08 | 2020-05-11 |
    45	| 2024-01 | 2024-01-05 | 2024-01-10 |
    46	| 2024-08 | 2024-08-02 | 2024-08-21 |
    47	
    48	六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
    49	**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
    50	那 18 條會把一個本來正確的結論撤回。** Codex 二審判 FAIL 擋下，未套用。
    51	
    52	根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
    53	fail-closed 驗證，commit `305d118a3`）。
    54	
    55	**為什麼原本 42 個測試全綠卻沒抓到**：fixture 是手寫的，同月第二筆事先就被刪掉了 ——
    56	測試餵進去的輸入根本表達不出這個 bug。修法不是加更好的斷言，是餵真實輸入：
    57	`tests/test_event_dates_real_raw_response.py` 直接釘住 ALFRED 的 264 筆原始回應
    58	（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
    59	那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。
    60	
    61	## 方法
    62	
    63	- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
    64	- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
    65	- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
    66	- 檢定：Welch t（vs 全體非 NFP 日 / vs 非 NFP 週五）、Mann-Whitney U、
    67	  VIX 中位數分組 regime 檢定、Pearson / Spearman 相關
    68	
    69	### 週五基準的口徑（estimand）調整
    70	
    71	proxy 下每一場 NFP 都是週五，「NFP vs 非 NFP 週五」自動就是同星期別對同星期別。
    72	官方日曆下有 16 場不在週五，若沿用原寫法，就變成**星期別混合的事件組**對**純週五的
    73	對照組**，週五本身的波動特性會直接混進 p 值。
    74	
    75	本輪把事件組**限定為在週五公布的 237 場**，兩邊星期別一致。另一個選項是保留全部 253 場
    76	改用 weekday-matched controls，未採用的理由：非週五事件是週四 8、週二 2、週三 1，
    77	用這種格數做加權平均，標準誤會被 1 筆的週三格主導 —— 那是對一個更難陳述的量做更吵的估計。
    78	被排除的 16 場以描述統計另行報告（平均 |ret| 0.715%），不是靜默丟掉。
    79	
    80	原口徑（全部事件 vs 非 NFP 週五）以 `B_diagnostic_mixed_weekday` 保留在結果檔中，
    81	標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。
    82	
    83	## 結果：逐項前後對照
    84	
    85	每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
    86	而中位數與勝率在底下已經移位。
    87	
    88	| 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
    89	|---|---|---|---|
    90	| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
    91	| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.108× (p=0.112, NS) | 數值微調 |
    92	| ↳ 中位數比 / 勝率 | 1.190× / 0.555 | 1.193× / 0.561 | 數值微調 |
    93	| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.190× (p=0.0202, **仍顯著**) | 數值微調（口徑見上） |
    94	| ↳ 中位數比 / 勝率 | 1.209× / 0.563 | 1.223× / 0.570 | 數值微調 |
    95	| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
    96	| ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
    97	| 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
    98	| ↳ Spearman | 0.377 | 0.346 | 數值微調 |
    99	| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
   100	
   101	**6 項受稽核宣稱中，0 項結論翻轉。**
   102	
   103	參考：若沿用修正前的舊口徑（全部 253 場 vs 非 NFP 週五），數值為 1.178×、p=0.0249 ——
   104	同樣顯著。也就是說**「顯著→不顯著」的翻轉在任何一種口徑下都不成立**，那是六個錯誤
   105	日期造成的假象。
   106	
   107	**方向性主結論不變**：決定 NFP 日波動的是**進場當下的 VIX 體制**（2.03 倍、p≈4.6e-9），
   108	遠大於 NFP 這個日曆事件本身。
   109	
   110	### 關於「不顯著」的措辭
   111	
   112	修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
   113	Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
   114	陳述都綁定它自己的檢定：
   115	
   116	- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
   117	- Welch 平均差（週五對週五）：1.190×，p=0.0202，**拒絕**
   118	- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019，**拒絕**
   119	
   120	平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
   121	排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。
   122	
   123	## 產出檔案
   124	
   125	| 檔案 | 內容 |
   126	|---|---|
   127	| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
   128	| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
   129	| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
   130	| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 換掉的日期 + 文章更正替換清單 |
   131	| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
   132	| `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
   133	| `review_verdict_v3.json` / `codex_review_v3.md` | Codex 三審裁決與全文 |
   134	
   135	## 線上文章更正（`mile_35eef830`）
   136	
   137	### ⚠️ 原 18 條更正清單已全數作廢
   138	
   139	原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
   140	改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
   141	撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
   142	`article_correction.supersedes`。
   143	
   144	### 新清單：19 條，全部是數值重述，0 條方向翻轉
   145	
   146	文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
   147	差距的是進場 VIX 體制 —— 在官方日期下**全部成立**。新清單只改數字
   148	（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
   149	外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
   150	
   151	19 條已對線上 canonical 文章驗證，全部恰好命中一次。
   152	
   153	```bash
   154	# 主線程在 repo root 執行
   155	uv run python experiments/k528/build_article_correction.py            # 驗證（不寫任何檔）
   156	uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
   157	```
   158	
   159	**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
   160	`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
   161	自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
   162	合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。
   163	
   164	**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
   165	與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
   166	因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。
   167	
   168	## 防迴歸
   169	
   170	事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
   171	
   172	- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
   173	  212 個日期共通、結果檔宣告 fail-closed
   174	- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住本輪 BLOCKER**：
   175	  對 artifact 斷言六個 off-cycle 日期不在事件集合、六個正式發布日在。對 artifact 而非
   176	  只對 accessor 斷言，因為「accessor 是對的」不能證明「出貨的結果用了它」
   177	- `TestProxyMutationIsCaught` — mutation test：proxy 日曆餵給 guard 必須被拒；
   178	  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆
   179	
   180	accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
   181	`tests/test_event_dates_real_raw_response.py`（真實 raw response + mutation 檢查）。
   182	
   183	Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
   184	由綠轉紅（`2006-05-08 != 2006-05-05`），還原後 51 passed。沒被實際觸發過的 gate 不算 gate。
   185	
   186	## 主腳本的 fail-closed 面
   187	
   188	- **日曆完整性**（`check_calendar_is_complete`）：同月多筆 → raise；樣本窗內缺月 → raise。
   189	  已知的真實缺口只有 2025-10（政府關門，ALFRED 在 2025-09-05 與 2025-11-20 之間 76 天無
   190	  條目），寫在 `KNOWN_MISSING_MONTHS` 並附理由 —— 這個清單是用來記錄真實缺口的，
   191	  不是用來讓檢查通過的
   192	- **事件日→交易日對映**：一對一完整性斷言。樣本內發布日找不到三日內交易日 → raise；
   193	  兩個發布日映射到同一個 session → raise（原本的 `set()` 去重會把這件事藏起來並靜默減少
   194	  事件數）。窗口邊界排除改為明確記錄在 `sample.event_mapping_audit`，不再靜默 `continue`
   195	- **原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`
   196	
   197	## 參考
   198	
   199	- K1442 事件日期稽核（發現 proxy bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
   200	- `docs/error_log.md` 2026-07-12 CPI 事件研究發布日條目（同一 bug class 的前例）
   201	- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
   202	- K513：先前的 FOMC/NFP/CPI 事件研究
{
  "superseded": true,
  "do_not_cite": true,
  "superseded_at": "2026-07-19",
  "superseded_by": "k528_nfp_event_study_results.json",
  "retraction_reason": "The first-Friday-of-month rule is wrong for roughly 20% of the sample and wrong SYSTEMATICALLY, not randomly: BLS moves the release to the second Friday when the reference week falls late, pulls it forward around holidays, and did not publish at all in 2025-10 during the federal shutdown -- for which this proxy invented an event day that never existed. Wrong event dates do not fail loudly: they count quiet days as event days and dump real event days into the control group, and every figure still renders.",
  "note_for_machines": "This object exists so the file is identifiable as retracted WITHOUT relying on its filename or on README prose (k528 Codex v2 finding 8). If you are reading this key, do not use any number in this file.",
  "audit_artifact": "k528_nfp_official_dates_results.json"
}
{
  "kid": "k528",
  "verdict": "FAIL",
  "reviewer": "Codex gpt-5.6-sol / high (re-run after first review never wrote verdict)",
  "reviewed_at": "2026-07-19T13:15:30+08:00",
  "reviewed_commit": "af2fad3569347e728b6fa29c90ddea38bf500e05",
  "review_artifact": "experiments/k528/codex_review_v2.md",
  "blocking_defects": [
    "official-calendar accessor picks 6 wrong event dates: max() over multiple same-month FRED release-id-50 entries mistakes off-cycle releases for NFP (event_dates.py:96)",
    "core sig->NS flip does not hold with correct dates (1.1779x, p~0.0249 still significant) — the 18 article corrections are contaminated and must not be applied",
    "fail-closed incomplete: only all-empty month errors; partial/ambiguous calendar passes silently (event_dates.py:121)"
  ],
  "reviewed_sha256": {
    "README.md": "a51a9c6a6abe9667fd86e58ad27a641d6732f5a6fccdc8e4e741ec1dec936083",
    "build_article_correction.py": "922805051b2fa064b433485093b40b0e4677b69ea0e813e1576e6c02428fd6c9",
    "k528_nfp_event_study.py": "d27afe1b822034272ae6c44493af092405e95cb55370651dda9734e7f1d2944a",
    "k528_nfp_event_study_results.json": "84070e93f77f02abac8c5660e897e6093c6fb6835b3df520bb10dc33d7dde339",
    "k528_nfp_official_dates_results.json": "41440b18d33134ad87772dafcbae0fc9603d1a5e53297111f1b6d76855040911"
  }
}

exec
/bin/zsh -lc "git show 6fd281901:tests/test_nfp_official_release_dates.py | nl -ba | sed -n '300,620p'
PYTHONDONTWRITEBYTECODE=1 python experiments/k528/build_article_correction.py --storage-dir /Users/yhlai0911/volpred-research/storage

git show 6fd281901:experiments/k528/build_article_correction.py | PYTHONDONTWRITEBYTECODE=1 python -c 'import sys,ast; s=sys.stdin.read(); t=ast.parse(s); a=next(x for x in t.body if isinstance(x,ast.AnnAssign) and getattr(x.target,\"id\",None)==\"REPLACEMENTS\"); reps=ast.literal_eval(a.value); print(\"n_replacements\",len(reps)); print(\"distinct_old\",len({x for x,_ in reps}),\"distinct_new\",len({x for _,x in reps}))'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 139ms:
validated 19/19 replacements, each matched exactly once
  @   416  總共 254 次 NFP 公布日的資料算過一遍...
  @   506  NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。...
  @   600  換句話說，這 1.10 倍的差距...
  @   698  VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t ...
  @   833  所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1...
  @  1132  那 254 次 NFP 日裡...
  @  1159  VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71...
  @  1395  相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）...
  @  1480  VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。...
  @  1717  ![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]...
  @  1923  貼在歷史分界線 16.71 的下緣...
  @  2057  落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。...
  @  2352  7/1 收盤的 16.59 距離 16.71 只差 0.12 點...
  @  2487  第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。...
  @  2625  高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。...
  @  2760  這跟 k528 在 254 場歷史樣本上得到的傾向一致...
  @  3014  254 場歷史樣本加上 7/2 這場實測...
  @  3131  樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinan...
  @  3383  VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；...

dry run -- nothing written. Re-run with --apply from the repo root, or --record-plan to persist the validated plan only.
n_replacements 19
distinct_old 19 distinct_new 19

exec
/bin/zsh -lc "git show 6fd281901:experiments/k528/codex_review_v2.md | nl -ba | sed -n '4980,5035p'
git show 6fd281901:experiments/k528/README.md | rg -n \"11|16|239|254|Friday|週五|apples|原口徑|flip|翻轉|insignificant\"
git show 6fd281901:experiments/k528/k528_nfp_event_study_results.json | rg -n \"11 non-Friday|16|DIAGNOSTIC|1.190132|1.177889|insignificant\"
git show 6fd281901:tests/test_nfp_official_release_dates.py | rg -n \"0.0571|stopped being significant|all-Friday|gap is the corrected dates|first-Friday\"" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 0ms:
  4980	  ✓ 讀取 handoff、error log 與 K528 審查檔案
  4981	  ✓ 驗證官方日期 fail-closed、事件對齊與統計重算
  4982	  ✓ 逐條比對 18 條文章更正並審查新舊結果揭露
  4983	  ✓ 檢查 lookahead、seed、原子寫入並形成裁決
  4984	codex
  4985	1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
  4986	
  4987	2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
  4988	
  4989	3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。
  4990	
  4991	4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。
  4992	
  4993	5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。
  4994	
  4995	6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。
  4996	
  4997	7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。
  4998	
  4999	8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。
  5000	
  5001	9. **防錯核對：** `pre_vix` 正確取自 T−1（[k528_nfp_event_study.py:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:163)、[k528_nfp_event_study.py:182](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:182)），未見交易 lookahead。本實驗沒有 bootstrap、抽樣或 Monte Carlo，seed 不適用。
  5002	
  5003	Blocking defects：官方 accessor 把 off-cycle entries 當 NFP；錯誤日期直接否定核心顯著性翻轉及 18 條文章更正；partial／ambiguous calendar 亦未真正 fail-closed。
  5004	
  5005	VERDICT: FAIL
  5006	tokens used
  5007	140,901
  5008	1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
  5009	
  5010	2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
  5011	
  5012	3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。
  5013	
  5014	4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。
  5015	
  5016	5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。
  5017	
  5018	6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。
  5019	
  5020	7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。
  5021	
  5022	8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。
  5023	
  5024	9. **防錯核對：** `pre_vix` 正確取自 T−1（[k528_nfp_event_study.py:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:163)、[k528_nfp_event_study.py:182](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:182)），未見交易 lookahead。本實驗沒有 bootstrap、抽樣或 Monte Carlo，seed 不適用。
  5025	
  5026	Blocking defects：官方 accessor 把 off-cycle entries 當 NFP；錯誤日期直接否定核心顯著性翻轉及 18 條文章更正；partial／ambiguous calendar 亦未真正 fail-closed。
  5027	
  5028	VERDICT: FAIL
4:- Created At: 2026-04-16T09:39:52.904348+00:00
19:原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：
21:- BLS 在參考週較晚的月份會改到**第二個週五**發布
24:- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 237 場在週五
44:| 2020-05 | 2020-05-08 | 2020-05-11 |
48:六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
49:**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
52:根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
53:fail-closed 驗證，commit `305d118a3`）。
66:- 檢定：Welch t（vs 全體非 NFP 日 / vs 非 NFP 週五）、Mann-Whitney U、
69:### 週五基準的口徑（estimand）調整
71:proxy 下每一場 NFP 都是週五，「NFP vs 非 NFP 週五」自動就是同星期別對同星期別。
72:官方日曆下有 16 場不在週五，若沿用原寫法，就變成**星期別混合的事件組**對**純週五的
73:對照組**，週五本身的波動特性會直接混進 p 值。
75:本輪把事件組**限定為在週五公布的 237 場**，兩邊星期別一致。另一個選項是保留全部 253 場
76:改用 weekday-matched controls，未採用的理由：非週五事件是週四 8、週二 2、週三 1，
78:被排除的 16 場以描述統計另行報告（平均 |ret| 0.715%），不是靜默丟掉。
80:原口徑（全部事件 vs 非 NFP 週五）以 `B_diagnostic_mixed_weekday` 保留在結果檔中，
81:標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。
90:| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
91:| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.108× (p=0.112, NS) | 數值微調 |
93:| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.190× (p=0.0202, **仍顯著**) | 數值微調（口徑見上） |
95:| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
99:| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
101:**6 項受稽核宣稱中，0 項結論翻轉。**
103:參考：若沿用修正前的舊口徑（全部 253 場 vs 非 NFP 週五），數值為 1.178×、p=0.0249 ——
104:同樣顯著。也就是說**「顯著→不顯著」的翻轉在任何一種口徑下都不成立**，那是六個錯誤
112:修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
116:- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
117:- Welch 平均差（週五對週五）：1.190×，p=0.0202，**拒絕**
139:原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
144:### 新清單：19 條，全部是數值重述，0 條方向翻轉
146:文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
148:（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
149:外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
172:- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
189:  已知的真實缺口只有 2025-10（政府關門，ALFRED 在 2025-09-05 與 2025-11-20 之間 76 天無
4:  "date": "2026-07-19T08:16:52.820209+00:00",
44:    "vol_ratio_vs_friday": 1.1901328478556155
55:      "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
58:      "vol_ratio": 1.1901328478556155,
63:        "n": 16,
69:      "status": "DIAGNOSTIC ONLY - do not quote",
71:      "vol_ratio": 1.177889180968137,
95:      "spearman_rho": 0.3455048873701663,
111:      "mean_abs_return": 0.009459292256163645,
125:      "mean_abs_return": 0.008502231669747567,
132:      "mean_abs_return": 0.010016738048407288,
140:      "vol_ratio": 1.297816321779998,
167:      "mean_abs_return": 0.007168557128140611,
182:      "vol_ratio": 0.8727716688091264,
184:      "p_val": 0.5675916686325496
188:      "mean_abs_return": 0.006880289163056845,
195:    "vix_median_split": 16.690000534057617,
200:    "t_stat": 6.169053858918396,
205:    "second_half_abs_return": 0.008691916519271146,
206:    "t_stat": -0.47950252995859216,
227:    "avg_abs_return": 0.010016738048407288,
241:  "claim_scope_note": "Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6).",
256:      "post_avg_abs_return": 0.004437752197660916,
269:      "event_return": 0.012456668331610077,
270:      "event_abs_return": 0.012456668331610077,
271:      "pre_avg_abs_return": 0.004473473755634516,
272:      "post_avg_abs_return": 0.004919147712201632,
304:      "post_avg_abs_return": 0.007013133994161836,
308:      "vix_change_event": 0.07000064849853516,
335:      "pre_avg_abs_return": 0.0057416373651214105,
337:      "pre_vix": 12.489999771118164,
381:      "event_return": 0.0034391603058943065,
382:      "event_abs_return": 0.0034391603058943065,
383:      "pre_avg_abs_return": 0.0069281751086755165,
417:      "pre_vix": 11.239999771118164,
433:      "pre_vix": 11.3100004196167,
436:      "vix_change_event": -0.3100004196166992,
469:      "high_low_range": 0.010887269121663814,
477:      "event_return": -0.010163338799748955,
478:      "event_abs_return": 0.010163338799748955,
484:      "vix_change_event": 0.8100004196166992,
500:      "vix_change_event": -0.23999977111816406,
501:      "high_low_range": 0.007168705988637018,
512:      "post_avg_abs_return": 0.005711716808938894,
515:      "post_vix_1d": 16.649999618530273,
532:      "vix_change_event": 0.32000064849853516,
544:      "post_avg_abs_return": 0.0030887140794647163,
561:      "pre_vix": 12.3100004196167,
573:      "event_return": -0.0012574110770166014,
574:      "event_abs_return": 0.0012574110770166014,
578:      "event_vix": 11.5600004196167,
641:      "pre_vix": 10.3100004196167,
659:      "post_vix_1d": 13.989999771118164,
672:      "post_avg_abs_return": 0.0047521168530124894,
678:      "volume_ratio": 0.6357474174016325
687:      "pre_avg_abs_return": 0.004584923166900801,
703:      "pre_avg_abs_return": 0.005207381775571696,
709:      "high_low_range": 0.005776216115471623,
720:      "post_avg_abs_return": 0.008176627484838116,
753:      "pre_vix": 23.989999771118164,
755:      "post_vix_1d": 27.3799991607666,
756:      "vix_change_event": 2.239999771118164,
770:      "event_vix": 16.90999984741211,
799:      "pre_avg_abs_return": 0.011327959273608168,
800:      "post_avg_abs_return": 0.011959847889816456,
803:      "post_vix_1d": 20.739999771118164,
817:      "pre_vix": 22.489999771118164,
829:      "event_return": 0.016088063012028586,
830:      "event_abs_return": 0.016088063012028586,
835:      "post_vix_1d": 25.989999771118164,
845:      "event_return": -0.010300816500528942,
846:      "event_abs_return": 0.010300816500528942,
850:      "event_vix": 27.489999771118164,
851:      "post_vix_1d": 29.3799991607666,
881:      "pre_vix": 18.8799991607666,
897:      "pre_vix": 18.6299991607666,
917:      "high_low_range": 0.016784124673888734,
931:      "post_vix_1d": 23.489999771118164,
959:      "pre_avg_abs_return": 0.03142508497941687,
981:      "high_low_range": 0.037289579983382164,
992:      "post_avg_abs_return": 0.018846916632064947,
995:      "post_vix_1d": 58.4900016784668,
1009:      "pre_vix": 42.560001373291016,
1021:      "event_return": 0.02849688160564745,
1022:      "event_abs_return": 0.02849688160564745,
1029:      "high_low_range": 0.030581696137665246,
1041:      "pre_vix": 50.16999816894531,
1056:      "post_avg_abs_return": 0.016382252602030987,
1085:      "event_return": 0.00021236320810169573,
1086:      "event_abs_return": 0.00021236320810169573,
1123:      "post_vix_1d": 24.989999771118164,
1125:      "high_low_range": 0.01620552805438533,
1151:      "pre_avg_abs_return": 0.010985390168460363,
1158:      "volume_ratio": 1.132461347716316
1172:      "vix_change_event": -1.239999771118164,
1199:      "pre_avg_abs_return": 0.006826103816378581,
1202:      "event_vix": 18.1299991607666,
1229:      "event_return": 0.014293581665240529,
1230:      "event_abs_return": 0.014293581665240529,
1251:      "post_vix_1d": 16.229999542236328,
1296:      "post_avg_abs_return": 0.011212316061533435,
1300:      "vix_change_event": -2.739999771118164,
1314:      "event_vix": 21.739999771118164,
1334:      "volume_ratio": 0.9416251538702529
1376:      "post_avg_abs_return": 0.0030005423381657126,
1380:      "vix_change_event": -1.3799991607666016,
1398:      "volume_ratio": 1.2505816720448455
1409:      "pre_vix": 16.690000534057617,
1411:      "post_vix_1d": 16.280000686645508,
1441:      "pre_vix": 17.739999771118164,
1472:      "post_avg_abs_return": 0.00738611160357916,
1475:      "post_vix_1d": 18.489999771118164,
1487:      "pre_avg_abs_return": 0.007346168083204185,
1501:      "event_return": -0.0014964664904916214,
1502:      "event_abs_return": 0.0014964664904916214,
1504:      "post_avg_abs_return": 0.041483440705586516,
1519:      "pre_avg_abs_return": 0.012163542237779667,
1522:      "event_vix": 33.91999816894531,
1525:      "high_low_range": 0.029189668951600765,
1533:      "event_return": -0.0066956410126548516,
1534:      "event_abs_return": 0.0066956410126548516,
1541:      "high_low_range": 0.018926648161214376,
1552:      "post_avg_abs_return": 0.016839738051925422,
1573:      "high_low_range": 0.013775438189133916,
1583:      "pre_avg_abs_return": 0.0070834274334167,
1586:      "event_vix": 20.6299991607666,
1599:      "pre_avg_abs_return": 0.0029182755788711655,
1604:      "vix_change_event": -0.8799991607666016,
1605:      "high_low_range": 0.00631775596211639,
1606:      "volume_ratio": 1.1166510779051486
1615:      "pre_avg_abs_return": 0.0077355341428540616,
1633:      "pre_vix": 16.700000762939453,
1645:      "event_return": -0.016157815269923215,
1646:      "event_abs_return": 0.016157815269923215,
1670:      "volume_ratio": 1.5550311686726317
1712:      "post_avg_abs_return": 0.00629504161687402,
1715:      "post_vix_1d": 16.280000686645508,
1745:      "pre_vix": 16.690000534057617,
1749:      "high_low_range": 0.016318152009275222,
1750:      "volume_ratio": 1.1378571674105726
1761:      "pre_vix": 16.579999923706055,
1763:      "post_vix_1d": 16.049999237060547,
1765:      "high_low_range": 0.007162448186442471,
1777:      "pre_vix": 14.5600004196167,
1807:      "pre_avg_abs_return": 0.004151116577334602,
1809:      "pre_vix": 13.0600004196167,
1811:      "post_vix_1d": 11.5600004196167,
1830:      "volume_ratio": 1.3538277137095216
1840:      "post_avg_abs_return": 0.0036462555091165473,
1844:      "vix_change_event": -0.7399997711181641,
1857:      "pre_vix": 16.6299991607666,
1873:      "pre_vix": 16.200000762939453,
1876:      "vix_change_event": -1.3100004196166992,
1885:      "event_return": 0.001698902174922523,
1886:      "event_abs_return": 0.001698902174922523,
1887:      "pre_avg_abs_return": 0.0032821649813985056,
1888:      "post_avg_abs_return": 0.003387316466368406,
1893:      "high_low_range": 0.005381679937811645,
1917:      "event_return": 0.005791669706856295,
1918:      "event_abs_return": 0.005791669706856295,
1955:      "post_vix_1d": 13.489999771118164,
1974:      "volume_ratio": 1.1022047682004164
1989:      "high_low_range": 0.01191005942164021,
1999:      "pre_avg_abs_return": 0.005362671630558036,
2032:      "post_avg_abs_return": 0.0038126889365168505,
2081:      "pre_vix": 16.950000762939453,
2085:      "high_low_range": 0.011376556792816654,
2113:      "pre_vix": 16.15999984741211,
2117:      "high_low_range": 0.009464688428221216,
2125:      "event_return": 0.0009349103953533167,
2126:      "event_abs_return": 0.0009349103953533167,
2134:      "volume_ratio": 0.8405238771111662
2141:      "event_return": 0.0016370774151923673,
2142:      "event_abs_return": 0.0016370774151923673,
2148:      "vix_change_event": -0.48999977111816406,
2159:      "pre_avg_abs_return": 0.011643978770353103,
2177:      "pre_vix": 16.850000381469727,
2195:      "post_vix_1d": 15.0600004196167,
2198:      "volume_ratio": 1.8916332873080948
2205:      "event_return": 0.006733051093951614,
2206:      "event_abs_return": 0.006733051093951614,
2210:      "event_vix": 14.739999771118164,
2221:      "event_return": 0.013166094849205168,
2222:      "event_abs_return": 0.013166094849205168,
2240:      "post_avg_abs_return": 0.005833181612777993,
2253:      "event_return": -0.0009157907354223616,
2254:      "event_abs_return": 0.0009157907354223616,
2257:      "pre_vix": 16.09000015258789,
2258:      "event_vix": 16.790000915527344,
2293:      "high_low_range": 0.011682849798971238,
2294:      "volume_ratio": 1.1606759419404762
2303:      "pre_avg_abs_return": 0.009441698045047553,
2304:      "post_avg_abs_return": 0.00780684794163351,
2319:      "pre_avg_abs_return": 0.004614440031642686,
2323:      "post_vix_1d": 16.520000457763672,
2338:      "event_vix": 14.8100004196167,
2345:      "date": "2016-01-08",
2346:      "year": 2016,
2353:      "pre_vix": 24.989999771118164,
2357:      "high_low_range": 0.022248876162983718,
2361:      "date": "2016-02-05",
2362:      "year": 2016,
2370:      "event_vix": 23.3799991607666,
2377:      "date": "2016-03-04",
2378:      "year": 2016,
2384:      "post_avg_abs_return": 0.0067191666517157685,
2385:      "pre_vix": 16.700000762939453,
2386:      "event_vix": 16.860000610351562,
2393:      "date": "2016-04-01",
2394:      "year": 2016,
2397:      "event_return": 0.006811825212216904,
2398:      "event_abs_return": 0.006811825212216904,
2405:      "high_low_range": 0.01527162038504038,
2409:      "date": "2016-05-06",
2410:      "year": 2016,
2415:      "pre_avg_abs_return": 0.005564758168076067,
2425:      "date": "2016-06-03",
2426:      "year": 2016,
2431:      "pre_avg_abs_return": 0.0023161152469873157,
2441:      "date": "2016-07-08",
2442:      "year": 2016,
2447:      "pre_avg_abs_return": 0.005911209816779839,
2452:      "vix_change_event": -1.5600004196166992,
2457:      "date": "2016-08-05",
2458:      "year": 2016,
2473:      "date": "2016-09-02",
2474:      "year": 2016,
2489:      "date": "2016-10-07",
2490:      "year": 2016,
2505:      "date": "2016-11-04",
2506:      "year": 2016,
2511:      "pre_avg_abs_return": 0.004168689860475539,
2521:      "date": "2016-12-02",
2522:      "year": 2016,
2525:      "event_return": 0.0005011654084499106,
2526:      "event_abs_return": 0.0005011654084499106,
2547:      "post_vix_1d": 11.5600004196167,
2565:      "high_low_range": 0.004752752922716175,
2566:      "volume_ratio": 1.1063197516097714
2581:      "high_low_range": 0.006016272960083019,
2646:      "volume_ratio": 0.8217132914116012
2662:      "volume_ratio": 1.1618033489972965
2688:      "post_avg_abs_return": 0.0017135397971616672,
2694:      "volume_ratio": 1.2186313418816541
2742:      "volume_ratio": 1.0480167433736693
2758:      "volume_ratio": 1.6395244232853163
2767:      "pre_avg_abs_return": 0.004890758021622732,
2769:      "pre_vix": 16.540000915527344,
2781:      "event_return": -0.022286164959837373,
2782:      "event_abs_return": 0.022286164959837373,
2784:      "post_avg_abs_return": 0.0074462251616837834,
2786:      "event_vix": 21.489999771118164,
2790:      "volume_ratio": 1.4379809959009164
2804:      "vix_change_event": -1.1299991607666016,
2815:      "pre_avg_abs_return": 0.007080551693358528,
2819:      "post_vix_1d": 12.739999771118164,
2909:      "event_return": -0.023235724014883163,
2910:      "event_abs_return": 0.023235724014883163,
2930:      "event_vix": 21.3799991607666,
2932:      "vix_change_event": -4.070001602172852,
2945:      "pre_vix": 16.56999969482422,
2946:      "event_vix": 16.139999389648438,
2949:      "high_low_range": 0.00747989168892642,
2957:      "event_return": -0.0020000544561606937,
2958:      "event_abs_return": 0.0020000544561606937,
2961:      "pre_vix": 16.59000015258789,
2962:      "event_vix": 16.049999237060547,
2976:      "post_avg_abs_return": 0.0032683320976225616,
2989:      "event_return": 0.009787911667226146,
2990:      "event_abs_return": 0.009787911667226146,
3008:      "post_avg_abs_return": 0.0023655833125168614,
3010:      "event_vix": 16.299999237060547,
3056:      "post_avg_abs_return": 0.002395419600160054,
3057:      "pre_vix": 16.270000457763672,
3085:      "event_return": 0.009264026644974166,
3086:      "event_abs_return": 0.009264026644974166,
3120:      "post_avg_abs_return": 0.0044185542165529725,
3122:      "event_vix": 12.5600004196167,
3142:      "volume_ratio": 0.8863621664917142
3149:      "event_return": -0.016531185200214682,
3150:      "event_abs_return": 0.016531185200214682,
3165:      "event_return": -0.014454160205242927,
3166:      "event_abs_return": 0.014454160205242927,
3168:      "post_avg_abs_return": 0.02522033248893716,
3171:      "post_vix_1d": 45.2400016784668,
3174:      "volume_ratio": 0.707664635498516
3181:      "event_return": 0.016546295716731718,
3182:      "event_abs_return": 0.016546295716731718,
3197:      "event_return": 0.025629768313761625,
3198:      "event_abs_return": 0.025629768313761625,
3213:      "event_return": 0.00550680279731619,
3214:      "event_abs_return": 0.00550680279731619,
3235:      "post_vix_1d": 22.1299991607666,
3237:      "high_low_range": 0.00771144165156306,
3245:      "event_return": -0.008165087864258957,
3246:      "event_abs_return": 0.008165087864258957,
3253:      "high_low_range": 0.0378316582829518,
3266:      "event_vix": 27.6299991607666,
3279:      "pre_avg_abs_return": 0.016228256836179476,
3280:      "post_avg_abs_return": 0.009001408767163266,
3300:      "vix_change_event": -0.48999977111816406,
3302:      "volume_ratio": 0.8589239582543516
3317:      "high_low_range": 0.011514410162130836,
3327:      "pre_avg_abs_return": 0.012591500767016072,
3328:      "post_avg_abs_return": 0.002975816499178374,
3331:      "post_vix_1d": 21.239999771118164,
3334:      "volume_ratio": 0.6637941686799702
3360:      "post_avg_abs_return": 0.0028259167235368254,
3378:      "event_vix": 16.690000534057617,
3382:      "volume_ratio": 0.8689834323805116
3391:      "pre_avg_abs_return": 0.0016957388159845044,
3394:      "event_vix": 16.420000076293945,
3395:      "post_vix_1d": 16.420000076293945,
3411:      "post_vix_1d": 16.440000534057617,
3421:      "event_return": 0.0016521877573574262,
3422:      "event_abs_return": 0.0016521877573574262,
3426:      "event_vix": 16.149999618530273,
3427:      "post_vix_1d": 16.719999313354492,
3441:      "pre_vix": 16.40999984741211,
3442:      "event_vix": 16.40999984741211,
3461:      "high_low_range": 0.00616638262768718,
3474:      "event_vix": 16.479999542236328,
3478:      "volume_ratio": 1.2165631403207418
3485:      "event_return": -0.008701149916033324,
3486:      "event_abs_return": 0.008701149916033324,
3487:      "pre_avg_abs_return": 0.01609030573639949,
3488:      "post_avg_abs_return": 0.010268167273724104,
3504:      "post_avg_abs_return": 0.0054487871355916265,
3519:      "pre_avg_abs_return": 0.01656450149868549,
3520:      "post_avg_abs_return": 0.01275153208026516,
3536:      "post_avg_abs_return": 0.016220448493387284,
3551:      "pre_avg_abs_return": 0.009186709241659896,
3554:      "event_vix": 19.6299991607666,
3567:      "pre_avg_abs_return": 0.022710938440661653,
3581:      "event_return": -0.016411313040607944,
3582:      "event_abs_return": 0.016411313040607944,
3588:      "vix_change_event": 0.07000160217285156,
3600:      "post_avg_abs_return": 0.009411659762782488,
3605:      "high_low_range": 0.012812953956516413,
3613:      "event_return": -0.001689972286972985,
3614:      "event_abs_return": 0.001689972286972985,
3664:      "post_avg_abs_return": 0.020039033950871653,
3698:      "event_vix": 21.1299991607666,
3725:      "event_return": -0.014429451153161188,
3726:      "event_abs_return": 0.014429451153161188,
3727:      "pre_avg_abs_return": 0.010428277330316527,
3763:      "post_vix_1d": 16.979999542236328,
3776:      "post_avg_abs_return": 0.0030788718445164953,
3830:      "volume_ratio": 0.7712351648305638
3841:      "pre_vix": 18.489999771118164,
3873:      "pre_vix": 13.0600004196167,
3888:      "post_avg_abs_return": 0.004516300813581386,
3893:      "high_low_range": 0.008569861622822642,
3922:      "event_vix": 14.739999771118164,
3925:      "high_low_range": 0.01385516650394639,
3937:      "pre_vix": 16.350000381469727,
3938:      "event_vix": 16.030000686645508,
3952:      "post_avg_abs_return": 0.0037153588616695376,
3954:      "event_vix": 13.489999771118164,
3955:      "post_vix_1d": 13.489999771118164,
3958:      "volume_ratio": 1.0990501153934116
3965:      "event_return": -0.0012158589936518416,
3966:      "event_abs_return": 0.0012158589936518416,
3971:      "post_vix_1d": 12.739999771118164,
3974:      "volume_ratio": 0.8621686970001967
3990:      "volume_ratio": 0.9231604500942332
3999:      "pre_avg_abs_return": 0.009453834221652935,
4013:      "event_return": -0.016829978520024547,
4014:      "event_abs_return": 0.016829978520024547,
4016:      "post_avg_abs_return": 0.00789131615536629,
4018:      "event_vix": 22.3799991607666,
4033:      "pre_vix": 20.489999771118164,
4050:      "event_vix": 21.8799991607666,
4053:      "high_low_range": 0.008633358198163082,
4086:      "volume_ratio": 1.5013161802064077
4098:      "event_vix": 16.540000915527344,
4099:      "post_vix_1d": 15.8100004196167,
4130:      "event_vix": 45.310001373291016,
4143:      "pre_avg_abs_return": 0.004277911690709635,
4162:      "event_vix": 16.770000457763672,
4165:      "high_low_range": 0.00662621697970003,
4177:      "pre_vix": 16.639999389648438,
4178:      "event_vix": 16.3799991607666,
4189:      "event_return": -0.01639041762130744,
4190:      "event_abs_return": 0.01639041762130744,
4193:      "pre_vix": 16.719999313354492,
4194:      "event_vix": 20.3799991607666,
4221:      "event_return": -0.015242227316648038,
4222:      "event_abs_return": 0.015242227316648038,
4223:      "pre_avg_abs_return": 0.007666979191613077,
4229:      "high_low_range": 0.036274166471176136,
4230:      "volume_ratio": 1.653162805834644
4233:      "date": "2025-12-16",
4241:      "pre_vix": 16.5,
4242:      "event_vix": 16.479999542236328,
4258:      "event_vix": 14.489999771118164,
4290:      "event_vix": 29.489999771118164,
4292:      "vix_change_event": 5.739999771118164,
1:"""Pin the NFP event dates that a first-Friday proxy gets wrong.
47:# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
110:            f"{proxy_date} came from the first-Friday proxy and is not an "
338:# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
339:# (p 0.0335 -> 0.0571). Same module rather than a new file: "NFP event dates
360:    """Reject a calendar carrying the first-Friday proxy's fingerprints.
413:        """237 of 253, not 253 of 253. The gap is the corrected dates."""

exec
/bin/zsh -lc "python -c 'oldn=835; oldm=.0071764494731905775; newn=834; newm=.007183350064732795; x=oldn*oldm-newn*newm; print(x); print((x)*100)'
# Recompute corrected Welch from committed event sample, committed t, and leaked observation inferred from aggregate difference
PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess,numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([e[\"event_abs_return\"] for e in d[\"event_data\"]]); wd=np.array([e[\"weekday\"] for e in d[\"event_data\"]]); x=a[wd==4]; ymean=d[\"main_results\"][\"friday_baseline_abs_return\"]; ny=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"n_control\"]; t=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"t_stat\"]; vx=x.var(ddof=1); vy=ny*((x.mean()-ymean)/t)**2-vx*ny/len(x); leaked=0.001157; sumy=ny*ymean; ss=(ny-1)*vy+ny*ymean*ymean; n2=ny-1; m2=(sumy-leaked)/n2; v2=(ss-leaked*leaked-n2*m2*m2)/(n2-1); t2=(x.mean()-m2)/(vx/len(x)+v2/n2)**.5; df=(vx/len(x)+v2/n2)**2/((vx/len(x))**2/(len(x)-1)+(v2/n2)**2/(n2-1)); p2=2*stats.t.sf(abs(t2),df); print({\"event_mean\":x.mean(),\"event_sd\":x.std(ddof=1),\"control_sd_solved\":vy**.5,\"corrected_mean\":m2,\"corrected_ratio\":x.mean()/m2,\"corrected_t\":t2,\"df\":df,\"p\":p2})'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 659ms:
{'event_mean': np.float64(0.008540928249020233), 'event_sd': np.float64(0.00800058876305757), 'control_sd_solved': np.float64(0.007757609057712275), 'corrected_mean': 0.0071836670385061535, 'corrected_ratio': np.float64(1.1889370990106918), 'corrected_t': np.float64(2.3199344158378814), 'df': np.float64(371.5081172067744), 'p': np.float64(0.02088570480457319)}

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess,numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([e[\"event_abs_return\"] for e in d[\"event_data\"]]); wd=np.array([e[\"weekday\"] for e in d[\"event_data\"]]); x=a[wd==4]; ymean=d[\"main_results\"][\"friday_baseline_abs_return\"]; ny=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"n_control\"]; t=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"t_stat\"]; vx=x.var(ddof=1); vy=ny*((x.mean()-ymean)/t)**2-vx*ny/len(x); leaked=0.0014213561269809105; sumy=ny*ymean; ss=(ny-1)*vy+ny*ymean*ymean; n2=ny-1; m2=(sumy-leaked)/n2; v2=(ss-leaked*leaked-n2*m2*m2)/(n2-1); t2=(x.mean()-m2)/(vx/len(x)+v2/n2)**.5; df=(vx/len(x)+v2/n2)**2/((vx/len(x))**2/(len(x)-1)+(v2/n2)**2/(n2-1)); p2=2*stats.t.sf(abs(t2),df); print({\"leaked_abs_return\":leaked,\"corrected_mean\":m2,\"corrected_ratio\":x.mean()/m2,\"corrected_t\":t2,\"p\":p2})'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 618ms:
{'leaked_abs_return': 0.0014213561269809105, 'corrected_mean': 0.007183350064732795, 'corrected_ratio': np.float64(1.1889895622590594), 'corrected_t': np.float64(2.3204610057628905), 'p': np.float64(0.020856890586645502)}

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess,numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([e[\"event_abs_return\"] for e in d[\"event_data\"]]); wd=np.array([e[\"weekday\"] for e in d[\"event_data\"]]); xf=a[wd==4]; ymean=d[\"main_results\"][\"friday_baseline_abs_return\"]; ny=835; t=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"t_stat\"]; vxf=xf.var(ddof=1); vy=ny*((xf.mean()-ymean)/t)**2-vxf*ny/len(xf); leaked=.0014213561269809105; sy=ny*ymean; ss=(ny-1)*vy+ny*ymean*ymean; n2=834; m2=(sy-leaked)/n2; v2=(ss-leaked*leaked-n2*m2*m2)/(n2-1); 
for name,x in [(\"friday\",xf),(\"mixed\",a)]:
 vx=x.var(ddof=1); tt=(x.mean()-m2)/(vx/len(x)+v2/n2)**.5; df=(vx/len(x)+v2/n2)**2/((vx/len(x))**2/(len(x)-1)+(v2/n2)**2/(n2-1)); print(name,len(x),x.mean()/m2,tt,2*stats.t.sf(abs(tt),df))'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 607ms:
friday 237 1.1889895622590594 2.3204610057628905 0.020856890586645502
mixed 253 1.176757657090474 2.2389804655292807 0.025694671724286588

exec
/bin/zsh -lc "git show 6fd281901:src/volpred/data/event_dates.py | PYTHONDONTWRITEBYTECODE=1 python -c 'import sys,json; from pathlib import Path; src=sys.stdin.read(); assert \"monthly = s.groupby([dates.year, dates.month]).min()\" in src; mut=src.replace(\"monthly = s.groupby([dates.year, dates.month]).min()\",\"monthly = s.groupby([dates.year, dates.month]).max()\"); ns={\"__file__\":str(Path(\"src/volpred/data/event_dates.py\").resolve()),\"__name__\":\"mutated_event_dates\"}; exec(compile(mut,\"mutated_event_dates.py\",\"exec\"),ns); raw=json.loads(Path(\"tests/fixtures/fred_release_50_nfp_raw_20260719.json\").read_text())[\"release_dates\"]; ns[\"_fetch\"]=lambda *a,**k:list(raw); got=[str(x.date()) for x in ns[\"release_dates\"](\"NFP_US\",\"2005-01-01\",\"2026-07-19\",use_cache=False)]; exp=[\"2006-05-05\",\"2012-12-07\",\"2013-05-03\",\"2020-05-08\",\"2024-01-05\",\"2024-08-02\"]; print(\"mutated_selected\",[x for x in got if x[:7] in {z[:7] for z in exp}]); print(\"would_test_fail\",not all(x in got for x in exp))'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 361ms:
mutated_selected ['2006-05-08', '2012-12-12', '2013-05-06', '2020-05-11', '2024-01-10', '2024-08-21']
would_test_fail True

exec
/bin/zsh -lc "git show 6fd281901:experiments/k528/k528_nfp_event_study_results.json | nl -ba | sed -n '1,90p'
git show 6fd281901:experiments/k528/k528_nfp_official_dates_results.json | nl -ba | sed -n '100,230p'
git show 6fd281901:experiments/k528/k528_nfp_official_dates_results.json | nl -ba | sed -n '230,390p'
git show 6fd281901:tests/test_event_dates_real_raw_response.py | nl -ba | sed -n '1,120p'
git show 6fd281901:tests/fixtures/fred_release_50_nfp_raw_20260719.json | nl -ba | sed -n '1,30p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 245ms:
   230	      "note": "",
   231	      "verdict": "NUMERIC_ADJUSTMENT",
   232	      "verdict_reasons": []
   233	    },
   234	    "sample": {
   235	      "label": "NFP event sample (article: 254 events)",
   236	      "before": {
   237	        "n": 254,
   238	        "date_range": "2005-02-04 to 2026-03-06",
   239	        "non_nfp_trading_days": 5086
   240	      },
   241	      "after": {
   242	        "n": 253,
   243	        "date_range": "2005-02-04 to 2026-03-06",
   244	        "non_nfp_trading_days": 5087,
   245	        "dates_in_common": 212,
   246	        "proxy_only_dates": [
   247	          "2005-07-01",
   248	          "2006-03-03",
   249	          "2006-12-01",
   250	          "2007-03-02",
   251	          "2008-07-07",
   252	          "2009-01-02",
   253	          "2009-05-01",
   254	          "2009-07-06",
   255	          "2010-01-04",
   256	          "2010-10-01",
   257	          "2011-07-01",
   258	          "2012-03-02",
   259	          "2013-03-01",
   260	          "2013-10-04",
   261	          "2013-11-01",
   262	          "2014-01-03",
   263	          "2014-07-07",
   264	          "2015-01-02",
   265	          "2015-05-01",
   266	          "2015-07-06",
   267	          "2016-01-04",
   268	          "2016-07-01",
   269	          "2017-03-03",
   270	          "2017-12-01",
   271	          "2018-03-02",
   272	          "2019-03-01",
   273	          "2020-01-03",
   274	          "2020-05-01",
   275	          "2020-07-06",
   276	          "2021-01-04",
   277	          "2021-10-01",
   278	          "2022-07-01",
   279	          "2023-03-03",
   280	          "2023-12-01",
   281	          "2024-03-01",
   282	          "2025-01-03",
   283	          "2025-07-07",
   284	          "2025-10-03",
   285	          "2025-11-07",
   286	          "2025-12-05",
   287	          "2026-01-02",
   288	          "2026-02-06"
   289	        ],
   290	        "official_only_dates": [
   291	          "2005-07-08",
   292	          "2006-03-10",
   293	          "2006-12-08",
   294	          "2007-03-09",
   295	          "2008-07-03",
   296	          "2009-01-09",
   297	          "2009-05-08",
   298	          "2009-07-02",
   299	          "2010-01-08",
   300	          "2010-10-08",
   301	          "2011-07-08",
   302	          "2012-03-09",
   303	          "2013-03-08",
   304	          "2013-10-22",
   305	          "2013-11-08",
   306	          "2014-01-10",
   307	          "2014-07-03",
   308	          "2015-01-09",
   309	          "2015-05-08",
   310	          "2015-07-02",
   311	          "2016-01-08",
   312	          "2016-07-08",
   313	          "2017-03-10",
   314	          "2017-12-08",
   315	          "2018-03-09",
   316	          "2019-03-08",
   317	          "2020-01-10",
   318	          "2020-05-08",
   319	          "2020-07-02",
   320	          "2021-01-08",
   321	          "2021-10-08",
   322	          "2022-07-08",
   323	          "2023-03-10",
   324	          "2023-12-08",
   325	          "2024-03-08",
   326	          "2025-01-10",
   327	          "2025-07-03",
   328	          "2025-11-20",
   329	          "2025-12-16",
   330	          "2026-01-09",
   331	          "2026-02-11"
   332	        ]
   333	      },
   334	      "note": "Equal counts do not mean equal samples -- check dates_in_common.",
   335	      "verdict": "NUMERIC_ADJUSTMENT",
   336	      "verdict_reasons": []
   337	    }
   338	  },
   339	  "n_claims_flipped": 0,
   340	  "n_claims_audited": 6,
   341	  "article_correction": {
   342	    "article_id": "mile_35eef830",
   343	    "status": "validated_not_applied",
   344	    "n_replacements": 19,
   345	    "all_matched_exactly_once": true,
   346	    "supersedes": {
   347	      "voided_list_size": 18,
   348	      "voided_at": "2026-07-19",
   349	      "reason": "the 18-item list was built against a rerun whose accessor picked off-cycle ALFRED entries for six months, which pushed the NFP-vs-Friday test across the 5% line. It would have retracted a finding that is in fact correct."
   350	    },
   351	    "directional_claims_changed": 0,
   352	    "replacements": [
   353	      {
   354	        "from": "總共 254 次 NFP 公布日的資料算過一遍",
   355	        "to": "總共 253 次 NFP 公布日的資料算過一遍",
   356	        "hits": 1
   357	      },
   358	      {
   359	        "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
   360	        "to": "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
   361	        "hits": 1
   362	      },
   363	      {
   364	        "from": "換句話說，這 1.10 倍的差距",
   365	        "to": "換句話說，這 1.11 倍的差距",
   366	        "hits": 1
   367	      },
   368	      {
   369	        "from": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   370	        "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   371	        "hits": 1
   372	      },
   373	      {
   374	        "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
   375	        "to": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
   376	        "hits": 1
   377	      },
   378	      {
   379	        "from": "那 254 次 NFP 日裡",
   380	        "to": "那 253 次 NFP 日裡",
   381	        "hits": 1
   382	      },
   383	      {
   384	        "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
   385	        "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
   386	        "hits": 1
   387	      },
   388	      {
   389	        "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
   390	        "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
     1	"""Regression test against the VERBATIM ALFRED raw response.
     2	
     3	Why this file exists, separately from test_event_dates_release_selection.py:
     4	
     5	The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
     6	a *hand-built* fixture in which the same-month duplicate entries had already
     7	been removed. So they exercised the selection rule against input that could
     8	not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
     9	dates and flipped a significance result with a fully green suite.
    10	
    11	The fix for a fixture that cannot express the bug is not a better assertion —
    12	it is real input. This module pins `_fetch`'s actual bytes for release id 50
    13	(Employment Situation, 2005-01-01..2026-07-19, 264 entries) and asserts the
    14	six regular releases survive selection.
    15	
    16	Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
    17	it — the duplicate pairs ARE the regression surface).
    18	"""
    19	from __future__ import annotations
    20	
    21	import json
    22	from pathlib import Path
    23	
    24	import pytest
    25	
    26	from volpred.data import event_dates
    27	
    28	_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
    29	
    30	# The six months ALFRED returns twice for, with the regular Employment Situation
    31	# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
    32	# filed against the same release id LATER in the month). Verified against the
    33	# live API on 2026-07-19; the right-hand column is exactly what the old max()
    34	# rule picked and what k528's contaminated run treated as NFP event days.
    35	OFF_CYCLE_PAIRS = {
    36	    "2006-05": ("2006-05-05", "2006-05-08"),
    37	    "2012-12": ("2012-12-07", "2012-12-12"),
    38	    "2013-05": ("2013-05-03", "2013-05-06"),
    39	    "2020-05": ("2020-05-08", "2020-05-11"),
    40	    "2024-01": ("2024-01-05", "2024-01-10"),
    41	    "2024-08": ("2024-08-02", "2024-08-21"),
    42	}
    43	
    44	
    45	@pytest.fixture(autouse=True)
    46	def _sandbox_cache_dir(monkeypatch, tmp_path):
    47	    # No test may touch the canonical storage/data cache dir (CI repo-state guard).
    48	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
    49	
    50	
    51	@pytest.fixture
    52	def raw_response() -> list[str]:
    53	    return json.loads(_FIXTURE.read_text())["release_dates"]
    54	
    55	
    56	@pytest.fixture
    57	def selected(monkeypatch, raw_response) -> list[str]:
    58	    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw_response))
    59	    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
    60	    return [str(d.date()) for d in idx]
    61	
    62	
    63	def test_fixture_still_carries_the_duplicate_months(raw_response):
    64	    """Guard the guard: if someone 'cleans' the fixture, the suite goes quiet again."""
    65	    by_month: dict[str, list[str]] = {}
    66	    for d in raw_response:
    67	        by_month.setdefault(d[:7], []).append(d)
    68	    multi = {m: v for m, v in by_month.items() if len(v) > 1}
    69	    assert set(multi) == set(OFF_CYCLE_PAIRS), (
    70	        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
    71	        f"got {sorted(multi)}"
    72	    )
    73	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
    74	        assert sorted(multi[month]) == [regular, off_cycle]
    75	
    76	
    77	def test_regular_release_wins_in_every_duplicate_month(selected):
    78	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
    79	        in_month = [d for d in selected if d.startswith(month)]
    80	        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
    81	        assert off_cycle not in selected, f"{off_cycle} is an off-cycle revision, not an NFP event"
    82	
    83	
    84	def test_selection_is_one_per_month_and_complete(selected, raw_response):
    85	    months_in = {d[:7] for d in raw_response}
    86	    months_out = [d[:7] for d in selected]
    87	    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
    88	    assert set(months_out) == months_in, "selection dropped or invented a month"
    89	    assert len(selected) == 258
    90	
    91	
    92	def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
    93	    """Mutation check: the OLD rule must fail this file, or it proves nothing.
    94	
    95	    Without this, a future refactor could silently restore max() and the two
    96	    assertions above would be the only thing standing in the way — this pins
    97	    WHY they matter.
    98	    """
    99	    by_month: dict[str, list[str]] = {}
   100	    for d in raw_response:
   101	        by_month.setdefault(d[:7], []).append(d)
   102	    old_rule = {m: max(v) for m, v in by_month.items()}
   103	    wrong = {m: old_rule[m] for m, (regular, _) in OFF_CYCLE_PAIRS.items() if old_rule[m] != regular}
   104	    assert wrong == {m: off for m, (_, off) in OFF_CYCLE_PAIRS.items()}, (
   105	        "the old max() rule must pick exactly the six off-cycle dates on this input"
   106	    )
     1	{
     2	  "source": "FRED/ALFRED release/dates API, release_id=50 (Employment Situation)",
     3	  "params": {
     4	    "realtime_start": "2005-01-01",
     5	    "realtime_end": "2026-07-19",
     6	    "include_release_dates_with_no_data": true,
     7	    "limit": 1000,
     8	    "sort_order": "asc"
     9	  },
    10	  "captured_at": "2026-07-19",
    11	  "note": "VERBATIM _fetch() output. Do NOT hand-edit or de-duplicate: the six same-month duplicate pairs ARE the regression surface (k528 Codex v2 BLOCKER 1).",
    12	  "release_dates": [
    13	    "2005-01-07",
    14	    "2005-02-04",
    15	    "2005-03-04",
    16	    "2005-04-01",
    17	    "2005-05-06",
    18	    "2005-06-03",
    19	    "2005-07-08",
    20	    "2005-08-05",
    21	    "2005-09-02",
    22	    "2005-10-07",
    23	    "2005-11-04",
    24	    "2005-12-02",
    25	    "2006-01-06",
    26	    "2006-02-03",
    27	    "2006-03-10",
    28	    "2006-04-07",
    29	    "2006-05-05",
    30	    "2006-05-08",

codex
核心驗收已完成：六個日期與 mutation 測試都通過；舊 18 條「方向翻轉」作廢也成立；原子寫入、真正 dry-run、superseded metadata、lookahead/seed 均可驗收。但指定 commit 仍有三個獨立 blocker：控制組漏排一個真實 NFP 日、before/after 審計硬比不同 estimand 且錯報 proxy 全為週五、fail-closed 可被多種合法形狀的錯資料繞過。現在整理逐點行號與最後裁決。
已完成指定 commit 的獨立驗算；worktree 後續出現的未提交變更不納入裁決。
  ✓ 讀 handoff、二審裁決與本輪 commit/diff，建立逐項驗收表
  ✓ 審查 accessor、fixture、fail-closed 與測試，做 mutation/繞過驗證
  ✓ 獨立重算新舊 estimand 統計量並核對事件日期
  ✓ 核對 README、results、audit、19 條文章更正與 superseded metadata
  ✓ 彙整逐點 findings、blocking defects 與最終 verdict
exec
/bin/zsh -lc 'git status --short --branch
git diff --name-only' in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 200ms:
## k528-nfp-official-dates
 M experiments/k528/k528_nfp_event_study.py
 M experiments/k528/k528_nfp_event_study_results.json
 M experiments/k528/k528_nfp_official_dates_results.json
experiments/k528/k528_nfp_event_study.py
experiments/k528/k528_nfp_event_study_results.json
experiments/k528/k528_nfp_official_dates_results.json

codex
審查範圍固定為 commit `6fd281901`。審查途中 worktree 另出現 3 個未提交修改；以下行號與裁決均以 `git show 6fd281901:<path>` 為準，不把移動中的修正版算進驗收。

1. **BLOCKER — 真實 NFP 日洩漏進控制組，兩個指定統計量受污染。**  
   `experiments/k528/k528_nfp_event_study.py:340-342` 只以 `valid_nfp` 排除控制組；但 `2005-01-07` 雖因事件窗不足被排除，仍是真實 NFP session。artifact 自己記錄 254 場已映射、1 場 window-excluded、253 場 valid（`k528_nfp_event_study_results.json:18-28`），卻把該日留在 non-NFP Fridays。  
   我由逐事件資料獨立重算，commit 內的 1.19013285 / p=0.02019846 與 1.17788918 / p=0.02487914 確實能重現，但那只是重現了污染。排除該日後應約為：

   - Friday-only：**1.18899×，p=0.02086，n=237 vs 834**
   - Mixed-weekday diagnostic：**1.17676×，p=0.02569，n=253 vs 834**

   方向仍顯著，但現行 results、README、audit 與 19 條更正中的精確數值都不是正確最終結果。正確集合應為所有 `nfp_trading_dates`，不是 `valid_nfp`。

2. **BLOCKER — before/after audit 硬比不同 estimand，且「proxy 全為週五」是錯的。**  
   proxy 日期雖由第一個週五產生，但遇休市會映射到下一個 session；archive 的實際事件資料是 **239 個 Friday、15 個 Monday**，不是 254/254 Friday。可是 audit 把 before 寫成 254 個 Friday（`k528_nfp_official_dates_results.json:136-143`），after 則只取 237 個 Friday（`145-160`），再宣稱是 apples-to-apples（`162`）。主腳本同樣直接把 before 全 254 場拿來比較（`k528_nfp_event_study.py:730-763`）。  
   正確 audit 必須提供兩組平行比較：

   - restricted estimand：proxy Friday 239 vs official Friday 237；
   - as-published mixed estimand：proxy 全 254 vs official 全 253。

   README `:71-81`、builder `:30-35` 和更正說明 `:179-183` 都錯稱初版已自動控制 weekday。這不是單純措辭問題，而是前後比較的識別口徑錯誤。

3. **BLOCKER — fail-closed 仍可被合理形狀的錯資料繞過。**  
   `src/volpred/data/event_dates.py:134-156` 在交給實驗前已按月 `min()`，因此 `check_calendar_is_complete()` 的「同月多筆 raise」（`k528_nfp_event_study.py:121-128`）在 live accessor 路徑不可達。實測輸入：

   ```text
   2024-01-05, 2024-02-01(off-cycle), 2024-02-02(regular), 2024-03-08
   ```

   accessor 靜默選 `2024-02-01`，且 cadence 完全通過。另有：

   - `check_calendar_is_complete()` 無條件忽略首尾月份（`:130-137`）；即使 `start=2005-01-01` 或 `end=2005-03-31` 是完整月份，缺月仍通過。
   - 13–110 天允許一至兩個月消失而不報錯。
   - `KNOWN_MISSING_MONTHS` 現行只有有文件依據的 2025-10，未見本輪濫用；但它是未驗證的全域 allowlist，技術上仍可用新增字串繞過檢查。

4. **HIGH — 19 條替換雖全部命中，但不能套用。**  
   dry-run 實測 19/19 舊字串各命中一次且沒有寫入。抽查超過 8 項後，253、0.845%、1.11×、16.69、128/125、2.03×、Pearson 0.44、Spearman 0.35、斜率 0.043pp、VIX 距離 0.10 等均與 commit artifact 的四捨五入值對齊。  
   問題集中在 Friday headline：

   - builder `:104-107` 仍寫「NFP 日確實比一般週五抖」，但檢定只識別「Friday NFP」。
   - builder `:151-154` 又把 conditional estimand 泛化成「NFP 事件本身」。
   - 被排除的 16 場平均 |return| 為 0.715%，比 Friday NFP 的 0.854% 低約 **16.3%**；限制 Friday 並非中性的樣本刪除，確實提高 headline ratio。

   限定週五本身可以是誠實的 conditional estimand，但不能再支持全體 NFP 的敘述。

5. **MEDIUM — results 內部仍有直接矛盾。**  
   `k528_nfp_event_study_results.json:55` 說排除 11 場 non-Friday，`:63` 卻記錄 16 場；README `:76` 的 weekday 分解也只加總到 11，漏掉映射後的 6 個 Monday，且 Thursday 數量亦不一致。

6. **MEDIUM — 新測試確實咬得到 `max()`，但 coverage 宣稱過頭。**  
   我把 production selection 動態 mutation 為 `max()`，六個月份精確變回 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；`test_regular_release_wins_in_every_duplicate_month` 會轉紅，因此不是 vacuous。正常 accessor 也確實選回六個正確日期；BLS 官方 Employment Situation archive 可交叉確認，例如 [2013-05-03](https://www.bls.gov/news.release/archives/empsit_05032013.htm)、[2020-05-08](https://www.bls.gov/news.release/archives/empsit_05082020.htm)、[2024-08-02](https://www.bls.gov/news.release/archives/empsit_08022024.htm)。  
   但 fixture 是 `_fetch()` 抽出的日期清單，不是完整 ALFRED HTTP raw-response bytes；`test_event_dates_real_raw_response.py:1-14` 的 “VERBATIM raw response/actual bytes” 是 overclaim。測試也沒有覆蓋較早 off-cycle、完整首尾月缺失或控制組洩漏。`tests/test_nfp_official_release_dates.py:338-340` 還殘留已推翻的 p=0.0571 敘述。

7. **已驗收通過。**

   - 六個問題月份已由 accessor 選回正確日期；`min()`→`max()` mutation 會失敗。
   - 二審指出「顯著→不顯著」不成立是正確的；原 18 條方向翻轉清單全數作廢理由成立。
   - `B_diagnostic_mixed_weekday` 在 results 中有清楚標成 diagnostic；問題是 audit/README 對 before estimand 的描述，不是該欄被直接當 headline。
   - `insignificant across all tests` 已移除，各主要顯著性敘述有綁定個別檢定。
   - 主結果與 audit 使用 temp file、`fsync`、`os.replace`；builder 預設 dry-run 不寫。
   - archive JSON 已具 `superseded=true`、`do_not_cite=true`、`superseded_by` 與 `retraction_reason`。
   - `pre_vix` 取 T−1，未見 lookahead；本實驗沒有隨機抽樣/bootstrap，seed 不適用。
   - 事件日映射碰撞與樣本內 unmapped assertion 已補上。

Blocking defects：控制組混入 `2005-01-07` 真實 NFP 日；before/after Friday audit 比較不同 estimand 且錯報 proxy weekday composition；calendar completeness 仍無法真正 fail-closed。19 條更正不得以 commit `6fd281901` 套用。

VERDICT: FAIL
tokens used
199,132
審查範圍固定為 commit `6fd281901`。審查途中 worktree 另出現 3 個未提交修改；以下行號與裁決均以 `git show 6fd281901:<path>` 為準，不把移動中的修正版算進驗收。

1. **BLOCKER — 真實 NFP 日洩漏進控制組，兩個指定統計量受污染。**  
   `experiments/k528/k528_nfp_event_study.py:340-342` 只以 `valid_nfp` 排除控制組；但 `2005-01-07` 雖因事件窗不足被排除，仍是真實 NFP session。artifact 自己記錄 254 場已映射、1 場 window-excluded、253 場 valid（`k528_nfp_event_study_results.json:18-28`），卻把該日留在 non-NFP Fridays。  
   我由逐事件資料獨立重算，commit 內的 1.19013285 / p=0.02019846 與 1.17788918 / p=0.02487914 確實能重現，但那只是重現了污染。排除該日後應約為：

   - Friday-only：**1.18899×，p=0.02086，n=237 vs 834**
   - Mixed-weekday diagnostic：**1.17676×，p=0.02569，n=253 vs 834**

   方向仍顯著，但現行 results、README、audit 與 19 條更正中的精確數值都不是正確最終結果。正確集合應為所有 `nfp_trading_dates`，不是 `valid_nfp`。

2. **BLOCKER — before/after audit 硬比不同 estimand，且「proxy 全為週五」是錯的。**  
   proxy 日期雖由第一個週五產生，但遇休市會映射到下一個 session；archive 的實際事件資料是 **239 個 Friday、15 個 Monday**，不是 254/254 Friday。可是 audit 把 before 寫成 254 個 Friday（`k528_nfp_official_dates_results.json:136-143`），after 則只取 237 個 Friday（`145-160`），再宣稱是 apples-to-apples（`162`）。主腳本同樣直接把 before 全 254 場拿來比較（`k528_nfp_event_study.py:730-763`）。  
   正確 audit 必須提供兩組平行比較：

   - restricted estimand：proxy Friday 239 vs official Friday 237；
   - as-published mixed estimand：proxy 全 254 vs official 全 253。

   README `:71-81`、builder `:30-35` 和更正說明 `:179-183` 都錯稱初版已自動控制 weekday。這不是單純措辭問題，而是前後比較的識別口徑錯誤。

3. **BLOCKER — fail-closed 仍可被合理形狀的錯資料繞過。**  
   `src/volpred/data/event_dates.py:134-156` 在交給實驗前已按月 `min()`，因此 `check_calendar_is_complete()` 的「同月多筆 raise」（`k528_nfp_event_study.py:121-128`）在 live accessor 路徑不可達。實測輸入：

   ```text
   2024-01-05, 2024-02-01(off-cycle), 2024-02-02(regular), 2024-03-08
   ```

   accessor 靜默選 `2024-02-01`，且 cadence 完全通過。另有：

   - `check_calendar_is_complete()` 無條件忽略首尾月份（`:130-137`）；即使 `start=2005-01-01` 或 `end=2005-03-31` 是完整月份，缺月仍通過。
   - 13–110 天允許一至兩個月消失而不報錯。
   - `KNOWN_MISSING_MONTHS` 現行只有有文件依據的 2025-10，未見本輪濫用；但它是未驗證的全域 allowlist，技術上仍可用新增字串繞過檢查。

4. **HIGH — 19 條替換雖全部命中，但不能套用。**  
   dry-run 實測 19/19 舊字串各命中一次且沒有寫入。抽查超過 8 項後，253、0.845%、1.11×、16.69、128/125、2.03×、Pearson 0.44、Spearman 0.35、斜率 0.043pp、VIX 距離 0.10 等均與 commit artifact 的四捨五入值對齊。  
   問題集中在 Friday headline：

   - builder `:104-107` 仍寫「NFP 日確實比一般週五抖」，但檢定只識別「Friday NFP」。
   - builder `:151-154` 又把 conditional estimand 泛化成「NFP 事件本身」。
   - 被排除的 16 場平均 |return| 為 0.715%，比 Friday NFP 的 0.854% 低約 **16.3%**；限制 Friday 並非中性的樣本刪除，確實提高 headline ratio。

   限定週五本身可以是誠實的 conditional estimand，但不能再支持全體 NFP 的敘述。

5. **MEDIUM — results 內部仍有直接矛盾。**  
   `k528_nfp_event_study_results.json:55` 說排除 11 場 non-Friday，`:63` 卻記錄 16 場；README `:76` 的 weekday 分解也只加總到 11，漏掉映射後的 6 個 Monday，且 Thursday 數量亦不一致。

6. **MEDIUM — 新測試確實咬得到 `max()`，但 coverage 宣稱過頭。**  
   我把 production selection 動態 mutation 為 `max()`，六個月份精確變回 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；`test_regular_release_wins_in_every_duplicate_month` 會轉紅，因此不是 vacuous。正常 accessor 也確實選回六個正確日期；BLS 官方 Employment Situation archive 可交叉確認，例如 [2013-05-03](https://www.bls.gov/news.release/archives/empsit_05032013.htm)、[2020-05-08](https://www.bls.gov/news.release/archives/empsit_05082020.htm)、[2024-08-02](https://www.bls.gov/news.release/archives/empsit_08022024.htm)。  
   但 fixture 是 `_fetch()` 抽出的日期清單，不是完整 ALFRED HTTP raw-response bytes；`test_event_dates_real_raw_response.py:1-14` 的 “VERBATIM raw response/actual bytes” 是 overclaim。測試也沒有覆蓋較早 off-cycle、完整首尾月缺失或控制組洩漏。`tests/test_nfp_official_release_dates.py:338-340` 還殘留已推翻的 p=0.0571 敘述。

7. **已驗收通過。**

   - 六個問題月份已由 accessor 選回正確日期；`min()`→`max()` mutation 會失敗。
   - 二審指出「顯著→不顯著」不成立是正確的；原 18 條方向翻轉清單全數作廢理由成立。
   - `B_diagnostic_mixed_weekday` 在 results 中有清楚標成 diagnostic；問題是 audit/README 對 before estimand 的描述，不是該欄被直接當 headline。
   - `insignificant across all tests` 已移除，各主要顯著性敘述有綁定個別檢定。
   - 主結果與 audit 使用 temp file、`fsync`、`os.replace`；builder 預設 dry-run 不寫。
   - archive JSON 已具 `superseded=true`、`do_not_cite=true`、`superseded_by` 與 `retraction_reason`。
   - `pre_vix` 取 T−1，未見 lookahead；本實驗沒有隨機抽樣/bootstrap，seed 不適用。
   - 事件日映射碰撞與樣本內 unmapped assertion 已補上。

Blocking defects：控制組混入 `2005-01-07` 真實 NFP 日；before/after Friday audit 比較不同 estimand 且錯報 proxy weekday composition；calendar completeness 仍無法真正 fail-closed。19 條更正不得以 commit `6fd281901` 套用。

VERDICT: FAIL
EXIT=0
