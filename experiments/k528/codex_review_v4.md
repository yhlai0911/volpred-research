OpenAI Codex v0.144.1
--------
workdir: /Users/yhlai0911/volpred-research
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019f7987-8394-7bf0-b7eb-6e7ddf8ded77
--------
user
你是嚴格的計量金融代碼審查者。這是 K528 NFP 事件研究修正案的**第四輪**審查
（三審 round-2）。**審查範圍固定為 commit `2abb3f68c`**；若工作樹有未提交修改，
一律以 `git show 2abb3f68c:<path>` 為準。

**審查對象**（絕對路徑 `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/`）：

實驗目錄 `experiments/k528/`：
- `README.md`、`k528_nfp_event_study.py`、`build_article_correction.py`
- `k528_nfp_event_study_results.json`、`k528_nfp_official_dates_results.json`
- `k528_nfp_event_study_results_PROXY_SUPERSEDED.json`
- `codex_review_v2.md` + `review_verdict.json`（二審 FAIL）
- `codex_review_v3.md`（**你上一輪的 FAIL 裁決，本輪要驗收它**）

共用模組與測試：
- `src/volpred/data/event_dates.py`
- `tests/test_nfp_official_release_dates.py`、`tests/test_event_dates_real_raw_response.py`
- `tests/test_event_dates_release_selection.py`、`tests/fixtures/fred_release_50_nfp_raw_20260719.json`

**背景**：你在三審 round-1（`codex_review_v3.md`，對 commit `6fd281901`）判 FAIL，
列三條 blocking + findings 4-6。本 commit 是針對那些 issue 的 remediation。

**本輪聲稱做了什麼**（逐條驗收，不要照單全收）：

1. **BLOCKER 1（控制組洩漏 2005-01-07）** — 聲稱對照組改為排除**全部 254 個**已映射
   NFP session（非只有 253 個 valid），`non_nfp_trading_days` 由 5087 → 5086。
   聲稱修正後數值為 Friday-only 1.18899/p=0.02086/n=237 vs 834、
   mixed diagnostic 1.17676/p=0.02569 —— 與你 round-1 的獨立預測一致。

2. **BLOCKER 2（before/after 硬比不同 estimand + 「proxy 全為週五」錯誤）** — 聲稱
   audit 現在兩種口徑**平行呈現**：主 before/after 兩欄同為 Friday-restricted
   （proxy 239 vs official 237），另以 `as_published_mixed_weekday`（before）與
   `diagnostic_mixed_weekday`（after）保留舊口徑；並在 README、builder、讀者更正說明
   三處改正「proxy 全為週五」的錯誤敘述（實為 239 Friday / 15 Monday，94.1% vs 93.7%，
   亦即該缺陷不是日期修正造成的）。

3. **BLOCKER 3（fail-closed 可繞過）** — 聲稱 `check_calendar_is_complete` 改為**同時
   驗證 raw feed 與 accessor 選擇**，四道關卡：(a) 同月兩筆間隔 <3 天 raise、
   (b) 選擇非該月最早 raise、(c) 觀測跨度內缺月 raise（移除首尾月無條件豁免）、
   (d) `KNOWN_MISSING_MONTHS` 宣稱的缺口會回頭驗證 raw feed 真的沒資料。

4. **finding 4（claim scope）** — 聲稱 results 加 `claim_scope` 與
   `restriction_is_not_neutral`（排除的 16 場比週五場平靜 16.3%），並在 README 與
   讀者更正說明中揭露「限定週五會墊高倍數（1.18→1.19）」與「這是條件於週五的結論」。

5. **finding 5（results 內部矛盾 11 vs 16）** — 聲稱 estimand 字串改由資料生成。

6. **finding 6（fixture overclaim + 殘留 p=0.0571）** — 聲稱 docstring 改口並明寫覆蓋
   邊界（是 `_fetch` 回傳值、不是完整 HTTP body）；測試檔殘留敘述改為記錄「那是錯的」。

7. **新增迴歸測試** — `TestControlGroupHasNoNfpDays`、
   `TestCalendarFailClosedCannotBeBypassed`（四個繞過路徑 + 一個必須通過的乾淨日曆）、
   `TestFridayEstimandIsScopedHonestly`。聲稱 115 tests 全綠。

**審查重點（請獨立驗算，不要只讀 diff）**：

1. 控制組是否真的不含任何 NFP session；統計量是否可獨立重現
2. audit 的 before/after 是否真的同口徑；「proxy 239/15」的說法是否正確
3. **試著繞過新的 `check_calendar_is_complete`** —— 想出它仍然接受的錯誤輸入形狀。
   3 天門檻是否可被規避？(c) 的觀測跨度錨定有沒有新漏洞（例如整個尾段消失）？
4. 19 條文章更正是否逐條與新 results 對齊（抽查至少 8 條）；claim scope 是否真的
   在讀者看得到的地方講清楚，還是只藏在 JSON 裡
5. 新測試是否 vacuous；`_k528_module()` 這種 AST 抽取方式會不會讓測試測到的不是
   production 實際執行的程式碼路徑
6. lookahead / seed / 原子寫入
7. README 宣稱面與 artifact 是否一致（有沒有新的 overclaim）

**特別注意**：本輪 agent 有動機把結果導向「已修好」，且已經連續兩輪被判 FAIL，
壓力更大。請主動找它可能自我欺騙或過度宣稱的地方。若確認修好了也請明說哪幾條已驗收。

**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出
`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 須列 blocking defects）。

codex
我會嚴格鎖定 `2abb3f68c` 的 blob，不採信工作樹內容。先讀 handoff 與上一輪裁決，再用 commit 內程式與 artifacts 獨立重算，接著刻意攻擊 calendar fail-closed、檢查測試是否真的走 production path，最後逐條抽查文章更正與 README claim。
  → 讀取 handoff、commit 狀態與上一輪 FAIL findings
  • 檢查修正 diff、production 程式與測試實際覆蓋路徑
  • 從 commit artifacts 獨立重算控制組、統計量與日期分布
  • 攻擊 calendar fail-closed 並檢查 lookahead、seed、原子寫入
  • 抽查至少 8 條文章更正及 README/artifact 一致性，形成裁決
exec
/bin/zsh -lc "sed -n '1,240p' storage/ops/handoff_latest.md
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp rev-parse 2abb3f68c"'^{commit}
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show --stat --oneline --decorate --no-renames 2abb3f68c
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/codex_review_v3.md | nl -ba | sed -n '"'1,280p'" in /Users/yhlai0911/volpred-research
 succeeded in 258ms:
2abb3f68c5b2ca480bffbd7d919da884a970d72b
2abb3f68c (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex 三審 round-1 的三個 BLOCKER + findings 4-6
 experiments/k528/README.md                         |   90 +-
 experiments/k528/build_article_correction.py       |   47 +-
 experiments/k528/codex_review_v3.md                | 5770 ++++++++++++++++++++
 experiments/k528/k528_nfp_event_study.py           |  269 +-
 experiments/k528/k528_nfp_event_study_results.json | 2538 ++++-----
 .../k528/k528_nfp_official_dates_results.json      |   72 +-
 .../fixtures/fred_release_50_nfp_raw_20260719.json |    2 +-
 tests/test_event_dates_real_raw_response.py        |   15 +-
 tests/test_nfp_official_release_dates.py           |  149 +-
 9 files changed, 7537 insertions(+), 1415 deletions(-)
     1	OpenAI Codex v0.144.1
     2	--------
     3	workdir: /Users/yhlai0911/volpred-research
     4	model: gpt-5.6-sol
     5	provider: openai
     6	approval: never
     7	sandbox: read-only
     8	reasoning effort: high
     9	reasoning summaries: none
    10	session id: 019f7975-0d36-77d3-9b16-20f8155c2e84
    11	--------
    12	user
    13	你是嚴格的計量金融代碼審查者。三審 K528 NFP 事件研究修正案。
    14	
    15	**審查對象**（絕對路徑 `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/`）：
    16	
    17	實驗目錄 `experiments/k528/`：
    18	- `README.md`（宣稱面）
    19	- `k528_nfp_event_study.py`（主腳本）
    20	- `k528_nfp_event_study_results.json`（現行結果）
    21	- `k528_nfp_event_study_results_PROXY_SUPERSEDED.json`（proxy 時代存證）
    22	- `k528_nfp_official_dates_results.json`（前後對照 audit + 文章更正計畫）
    23	- `build_article_correction.py`（文章 mile_35eef830 的更正清單）
    24	- `codex_review_v2.md` + `review_verdict.json`（**你上一輪的 FAIL 裁決，本輪要驗收它**）
    25	
    26	共用模組與測試：
    27	- `src/volpred/data/event_dates.py`（官方日曆 accessor，根修）
    28	- `tests/test_event_dates_real_raw_response.py`（新增）
    29	- `tests/test_event_dates_release_selection.py`
    30	- `tests/test_nfp_official_release_dates.py`
    31	- `tests/fixtures/fred_release_50_nfp_raw_20260719.json`（新增，ALFRED 原始回應）
    32	
    33	**背景**：你在二審（`codex_review_v2.md`）判 FAIL，列三條 blocking defects 與 findings 3-8。
    34	本輪是針對那些 issue 的 remediation。commit `6fd281901`。
    35	
    36	**本輪聲稱做了什麼**（逐條驗收，不要照單全收）：
    37	
    38	1. **BLOCKER 1（accessor 取 max() 選錯六個日期）** — 聲稱根修在 main commit `305d118a3`，
    39	   改為 per-month `min()` + 13–110 天 cadence fail-closed 驗證；branch 已 rebase 帶入。
    40	   聲稱六個月份以 live ALFRED 驗證正確：2006-05-05 / 2012-12-07 / 2013-05-03 /
    41	   2020-05-08 / 2024-01-05 / 2024-08-02。
    42	
    43	2. **BLOCKER 2（顯著性翻轉不成立）** — 聲稱確認你是對的：翻轉不成立。舊口徑重算得
    44	   1.1779×、p=0.02488（與你二審預算一致）；新口徑（週五對週五）為 1.190×、p=0.0202。
    45	   原 18 條文章更正**全數作廢**，改為 19 條純數值重述、0 條方向翻轉。
    46	
    47	3. **BLOCKER 3 / finding 4（fail-closed 不完整）** — 聲稱補了 `check_calendar_is_complete`
    48	   （同月多筆 raise、樣本窗內缺月 raise，2025-10 政府關門列 `KNOWN_MISSING_MONTHS`）
    49	   與事件日→交易日一對一斷言（找不到 session raise、兩發布日撞同 session raise）。
    50	
    51	4. **finding 5（Friday baseline estimand）** — 聲稱改為「237 場週五 NFP vs 非 NFP 週五」，
    52	   兩邊星期別一致；未採 weekday-matched controls 的理由寫在 README；舊口徑以
    53	   `B_diagnostic_mixed_weekday` 保留並標 DIAGNOSTIC ONLY。
    54	
    55	5. **finding 6（方向性敘述超過證據）** — 聲稱移除 "insignificant across all tests"，
    56	   每個顯著性陳述綁定自己的檢定。
    57	
    58	6. **finding 7（原子寫入 / dry-run）** — 聲稱主結果與 audit 改 temp+fsync+`os.replace`；
    59	   builder dry-run 改為真的不寫。
    60	
    61	7. **finding 8（superseded metadata）** — 聲稱 archive JSON 本體加了
    62	   `superseded` / `do_not_cite` / 撤回原因。
    63	
    64	8. **迴歸測試** — 聲稱新增用真實 raw-response 語義（同月多筆）的 regression test，
    65	   並附 mutation 檢查；聲稱實測 `min()`→`max()` 會轉紅。
    66	
    67	**審查重點（請獨立驗算，不要只讀 diff）**：
    68	
    69	1. 六個問題月份是否真的修正（自己跑 accessor 或讀 fixture 核對）
    70	2. 統計量是否可獨立重現：特別是 1.190×/p=0.0202（新口徑）與 1.1779×/p=0.02488（舊口徑）
    71	3. **estimand 選擇是否誠實且一致**：限定週五是否有把樣本選擇偏誤引進來？
    72	   `B_diagnostic_mixed_weekday` 有沒有被誤用成 headline？audit 的 before/after 對照
    73	   是否拿了不同口徑硬比（`before` 是舊口徑、`after` 是新口徑，這樣比公平嗎？
    74	   README 有沒有講清楚）？
    75	4. 19 條文章更正是否逐條與新 results 對齊（抽查至少 8 條）；作廢 18 條的理由是否成立；
    76	   有沒有殘留任何方向翻轉
    77	5. fail-closed 是否真的關上（試著想出能繞過 `check_calendar_is_complete` 的輸入）；
    78	   `KNOWN_MISSING_MONTHS` 是不是被拿來讓檢查通過的後門
    79	6. 新測試是否**真的**測得到 bug（fixture 有沒有被動過手腳、mutation 檢查是否 vacuous）
    80	7. lookahead / seed / 原子寫入等標準防錯
    81	8. README 宣稱面與 artifact 是否一致（有沒有 overclaim）
    82	
    83	**特別注意**：本輪 agent 有動機把結果導向「已修好」。請主動找它可能自我欺騙的地方。
    84	若發現新的 blocking defect，照列不誤；若確認修好了，也請明說哪幾條已驗收。
    85	
    86	**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出
    87	`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 須列 blocking defects）。
    88	
    89	codex
    90	我會把二審裁決當作驗收規格，但不採信本輪摘要：先讀統一 handoff 與舊裁決，再核對 commit/diff、fixture 原始語義，最後用獨立計算與 mutation/邊界案例重跑。全程只讀，不改工作樹。
    91	  → 讀 handoff、二審裁決與本輪 commit/diff，建立逐項驗收表
    92	  • 審查 accessor、fixture、fail-closed 與測試，做 mutation/繞過驗證
    93	  • 獨立重算新舊 estimand 統計量並核對事件日期
    94	  • 核對 README、results、audit、19 條文章更正與 superseded metadata
    95	  • 彙整逐點 findings、blocking defects 與最終 verdict
    96	exec
    97	/bin/zsh -lc "sed -n '1,240p' storage/ops/handoff_latest.md
    98	pwd
    99	git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short --branch
   100	git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show --stat --oneline --decorate --no-renames 6fd281901
   101	git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff --stat 6fd281901"'^ 6fd281901' in /Users/yhlai0911/volpred-research
   102	 succeeded in 205ms:
   103	## k528-nfp-official-dates
   104	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
   105	 experiments/k528/README.md                         |  188 +-
   106	 experiments/k528/build_article_correction.py       |  170 +-
   107	 experiments/k528/codex_review_v2.md                | 5028 ++++++++++++++++++++
   108	 experiments/k528/k528_nfp_event_study.py           |  338 +-
   109	 experiments/k528/k528_nfp_event_study_results.json | 2698 +++++------
   110	 ...8_nfp_event_study_results_PROXY_SUPERSEDED.json |   13 +
   111	 .../k528/k528_nfp_official_dates_results.json      |  153 +-
   112	 experiments/k528/review_verdict.json               |   20 +
   113	 .../fixtures/fred_release_50_nfp_raw_20260719.json |  278 ++
   114	 tests/test_event_dates_real_raw_response.py        |  106 +
   115	 tests/test_nfp_official_release_dates.py           |   40 +-
   116	 11 files changed, 7461 insertions(+), 1571 deletions(-)
   117	 experiments/k528/README.md                         |  188 +-
   118	 experiments/k528/build_article_correction.py       |  170 +-
   119	 experiments/k528/codex_review_v2.md                | 5028 ++++++++++++++++++++
   120	 experiments/k528/k528_nfp_event_study.py           |  338 +-
   121	 experiments/k528/k528_nfp_event_study_results.json | 2698 +++++------
   122	 ...8_nfp_event_study_results_PROXY_SUPERSEDED.json |   13 +
   123	 .../k528/k528_nfp_official_dates_results.json      |  153 +-
   124	 experiments/k528/review_verdict.json               |   20 +
   125	 .../fixtures/fred_release_50_nfp_raw_20260719.json |  278 ++
   126	 tests/test_event_dates_real_raw_response.py        |  106 +
   127	 tests/test_nfp_official_release_dates.py           |   40 +-
   128	 11 files changed, 7461 insertions(+), 1571 deletions(-)
   129	
   130	codex
   131	初步確認 worktree 乾淨、HEAD 是指定 commit。接下來我先鎖定實作與 artifact schema；二審檔異常膨脹到約 5,000 行，我只取其正式 findings/verdict 區段，不把工具輸出雜訊當審查內容。
   132	exec
   133	/bin/zsh -lc "git log --oneline --decorate -12
   134	git merge-base --is-ancestor 305d118a3 HEAD; printf 'ancestor_exit=%s\\n' \""'$?"
   135	rg -n "BLOCKER|Finding|VERDICT|FAIL|CONDITIONAL|PASS" experiments/k528/codex_review_v2.md experiments/k528/review_verdict.json | tail -n 120
   136	rg -n "def |KNOWN_MISSING|check_calendar|release|month|min'"\\(|max\\(|cadence|13|110|replace|fsync|dry.run|Friday|DIAGNOSTIC|headline|superseded|do_not_cite\" src/volpred/data/event_dates.py experiments/k528/k528_nfp_event_study.py experiments/k528/build_article_correction.py experiments/k528/README.md tests/test_event_dates_real_raw_response.py tests/test_event_dates_release_selection.py tests/test_nfp_official_release_dates.py" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
   137	 succeeded in 0ms:
   138	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
   139	e42dc25ad fix(k528): NFP 事件日改用官方日曆重跑，1 項顯著性翻轉
   140	50bb24870 (origin/main, origin/HEAD) dispatch(15:22): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(2)
   141	28a14f7c7 [codex] queue BMA remediation reruns
   142	1af0e3fbf [codex] guard BMA invalid model posterior
   143	363cae2a2 [codex] detect nested DM coefficient masks
   144	ae815f3e5 [codex] fix worktree-owned orphan outputs
   145	cb97c0b7f [codex] serialize compute retry and triage ownership
   146	175b3b67c [codex] fail snapaudit incomplete coverage review
   147	f0350b912 (k741-nfp-canonical) dispatch(14:42): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(8)、scripts(1)、scripts/tests/(1) 等 5 處
   148	20ffdc4a3 ci-fix(2): event_dates use_cache=False now bypasses cache WRITE too + guard_canonical_write before cache write; sandbox fixture in selection tests (repo-state guard leak)
   149	3cb072b83 firstfriday sweep: 8 archived-experiment README warnings + sweep report (9 sites, k741->volatility-absorption paper NFP table contamination documented)
   150	ancestor_exit=0
   151	experiments/k528/review_verdict.json:3:  "verdict": "FAIL",
   152	experiments/k528/codex_review_v2.md:31:**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出 `VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 列 blocking defects）。
   153	experiments/k528/codex_review_v2.md:73:- `k1708_fix_verdict_gate_20260717` P2 [experiment] [experiment] K1708 修正 stage：verdict gate 假陽性 + CW nesting/gate 替換三個 BLOCKER — claimed_by=hourly-slot-1-858545f95a864e298ddb4bc144a8c615
   154	experiments/k528/codex_review_v2.md:76:- `assign_5aa9d5f5` P2 [experiment] K1623 修復：撤回 long-memory 識別宣稱 + 補 MSE DM 與多重比較（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
   155	experiments/k528/codex_review_v2.md:77:- `assign_42306eaa` P2 [experiment] K1698 重跑：修 contract-selection lookahead + 夜盤邊界空驗證 + equivalence 檢定（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
   156	experiments/k528/codex_review_v2.md:78:- `k1731_armB_rev7_remediation` P1 [experiment] K1731 arm B rev7 bounded remediation（Codex rev6 FAIL：B1a/B1b/B5/nested-DM detector）
   157	experiments/k528/codex_review_v2.md:223:**目前只有 1 篇真正 ready**：`leverage-direction`(JBF) — 6/11 技術定稿、合規只差 body.tex:231 一個 VolPred footnote（fix 在 audit json）。`vt-trend-following`(JPM/FAJ) 下一棒（6/30 才 v7 PASS + 10 個 K-id tags 待清）。
   158	experiments/k528/codex_review_v2.md:275:5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。
   159	experiments/k528/codex_review_v2.md:327:80-**規則**：worktree agent 只產 `experiments/kXXX/`，禁改共享狀態；主線程用 `scripts/merge_worktree.sh` 合併，**禁 `git worktree remove --force`**（L1 hook 擋）。實驗進 main 的唯一門票 = `experiments/<kid>/review_verdict.json` 且 sha256 綁「現在這份 bytes」（PASS 後又改 code 也擋）。裁決檔一律由 `verdict-template` 產生，不手抄。**保留 branch ≠ 收割成果**：clean tree 只證明沒有未提交檔案，不證明那些 commits 進了 main；移除 unmerged checkout 就是在製造下一個殭屍。**任務引用的資源會消失，必須有東西去 reconcile**——否則任務永遠 blocked 又永遠不關單。
   160	experiments/k528/codex_review_v2.md:371:136-  - **2026-07-15 07:15 hourly-07 collect_completed 收尾（closure）**：rerun 補上 circular-shift/phase-randomized null（common p=0.559、inception p=0.212 均未拒絕、Holm 0/13）+ no-timing 常數減碼 reference（複製 59–85% raw gap、matched gap ~0），commit `bdf6b451f`。主線程獨立重算兩樣本 byte 對齊；fresh-context code-reviewer 判 PASS（7/7 checklist 無 blocking defect）→ `experiments/k1695/review_verdict.json`（PASS，pin 現行 sha）+ certify PASS。knowledge append 更正條目 `8f80b2ee`（撤回舊 PASS `f4a73c83`）。paper 決定＝**撤除第三 contribution**（非把 null 包裝成 finding），routed to `paper_body_vt_trend_withdraw_k1695_contribution`。`feed_correction_k1695_exposure_artifact` 認證後已解除 blocked→pending P1。primary-path Codex re-verify 已 enqueue（`agent-brief_k1695_codex_reverify-be9cd6`）作 belt-and-suspenders。**流程觀察**：knowledge store append-only、無 in-place retract CLI，舊 PASS 條目仍在庫（靠 correction 條目 + `content_correction_scanner` 覆蓋）——若日後同類撤回頻繁，值得補 supersede 機制。
   161	experiments/k528/codex_review_v2.md:372:137-  - **2026-07-15 09:xx hourly-09 reader-facing 回溯更正完成（closure）**：`feed_correction_k1695_exposure_artifact` 執行完畢。3 篇 published（`mile_0d595dfb` 招牌篇、`mile_2d4edb65`、`mile_ee473d5a` VT 完全指南）於 feed.json `content` 前置「編者更正聲明」——保留原數字未刪，明寫舊結論被推翻＋推翻理由（曝險假象：VT 實現波動 0.61–0.68× B&H，同曝險口徑平均 ΔMDD −0.87pp/7-of-13、null p=0.559，一個固定減碼策略即複製 85%）；嚴守強度邊界（不寫「擇時有害」、不宣稱 inception +4.96pp 被否證）。2 篇 archived（`mile_f2e26f43`/`mile_9eaadbd1`）加「更正註記」。anti_ai_gate PASS；`storage/reports/<id>.json`（存在的 2 檔）同步；`supabase_sync full` 推平台（5 篇皆入 sync log、reconcile no_drift 1810=1810）。blast radius 從 code→paper→feed 全數收口。
   162	experiments/k528/codex_review_v2.md:373:138:- 2026-07-12 DM helper 在 h=1 退化成 iid，K565 的 Harvey PASS 被推翻 — Q3
   163	experiments/k528/codex_review_v2.md:398:214-- 2026-07-16 **3-STRIKE 級結構修復（老闆直接下令「該單一關口的就單一關口」）**：`volpred ops assign` 寫入的 `storage/ops/tasks/` queue **無任何 dispatcher 消費**（唯一 reader=手動 claim-next，無人跑）→ 16 任務黑洞 5 天，含結論已推翻仍在排隊的 K1695 舊敘事文章（執行=發錯誤內容）；同晚兩個並行互動 session 對老闆同一則 Telegram（msg877）**矛盾雙回覆**（msg879 排 credit→vol 研究 vs msg880 判 aggregate 版全 NULL），本 session 亦違反 claim-first（先做事先回覆最後才 claim）。**修**：(a) assign 重定向為 next_tasks.json thin wrapper（`append_next_task`，flock）；(b) 存量 17 個非終態 triage（4 終態含 1 deprecated 有害任務 + 13 遷入 canonical queue，credit 題合併雙方判斷成單一 brief）；(c) reply-right guard：`telegram-send --reply-to-task` 對已完成/他人持有任務拒發（break-then-verify 過）；(d) 機械 gate `scripts/tests/test_ops_tasks_receipts_only.py`（先 FAIL 於存量、遷移後轉綠，證明會咬）。設計：`docs/refactor_plan_single_gateway_task_system.md` — Q3
   164	experiments/k528/codex_review_v2.md:616:    31	the dates now come from the official release calendar and the run FAILS CLOSED
   165	experiments/k528/codex_review_v2.md:4378:     3	  "verdict": "FILL: PASS or FAIL — anything but PASS blocks the merge",
   166	experiments/k528/codex_review_v2.md:4384:     9	    "FILL: one entry per defect that makes this a FAIL; [] if PASS"
   167	experiments/k528/codex_review_v2.md:4985:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
   168	experiments/k528/codex_review_v2.md:4987:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
   169	experiments/k528/codex_review_v2.md:5005:VERDICT: FAIL
   170	experiments/k528/codex_review_v2.md:5008:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
   171	experiments/k528/codex_review_v2.md:5010:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
   172	experiments/k528/codex_review_v2.md:5028:VERDICT: FAIL
   173	experiments/k528/README.md:30:`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
   174	experiments/k528/README.md:31:release id 50），且**取不到就 raise，不回退 proxy**。
   175	experiments/k528/README.md:35:第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
   176	experiments/k528/README.md:37:因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：
   177	experiments/k528/README.md:39:| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
   178	experiments/k528/README.md:43:| 2013-05 | 2013-05-03 | 2013-05-06 |
   179	experiments/k528/README.md:52:根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
   180	experiments/k528/README.md:58:（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
   181	experiments/k528/README.md:59:那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。
   182	experiments/k528/README.md:64:- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
   183	experiments/k528/README.md:81:標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。
   184	experiments/k528/README.md:129:| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
   185	experiments/k528/README.md:131:| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
   186	experiments/k528/README.md:170:事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
   187	experiments/k528/README.md:180:accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
   188	experiments/k528/README.md:183:Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
   189	experiments/k528/README.md:188:- **日曆完整性**（`check_calendar_is_complete`）：同月多筆 → raise；樣本窗內缺月 → raise。
   190	experiments/k528/README.md:190:  條目），寫在 `KNOWN_MISSING_MONTHS` 並附理由 —— 這個清單是用來記錄真實缺口的，
   191	experiments/k528/README.md:195:- **原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`
   192	experiments/k528/README.md:201:- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
   193	experiments/k528/README.md:202:- K513：先前的 FOMC/NFP/CPI 事件研究
   194	tests/test_nfp_official_release_dates.py:1:"""Pin the NFP event dates that a first-Friday proxy gets wrong.
   195	tests/test_nfp_official_release_dates.py:3:`experiments/event_article_nfp_2026_07_03_t1` used to derive its NFP release
   196	tests/test_nfp_official_release_dates.py:4:dates from a "first Friday of the month" rule. Against the official BLS
   197	tests/test_nfp_official_release_dates.py:5:Employment Situation calendar, 7 of its 13 historical events were on the wrong
   198	tests/test_nfp_official_release_dates.py:6:day, and correcting them flipped the headline direction: the SPY up-day rate
   199	tests/test_nfp_official_release_dates.py:15:returned by FRED release id 50 (Employment Situation), fetched 2026-07-19.
   200	tests/test_nfp_official_release_dates.py:33:# Official Employment Situation release dates, FRED release id 50.
   201	tests/test_nfp_official_release_dates.py:40:    # No October 2025 release: the shutdown cancelled it and pushed the
   202	tests/test_nfp_official_release_dates.py:47:# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
   203	tests/test_nfp_official_release_dates.py:67:# What the experiment must use: trailing 13 official releases before 2026-07-02.
   204	tests/test_nfp_official_release_dates.py:68:EXPECTED_TRAILING_13 = [
   205	tests/test_nfp_official_release_dates.py:75:def _first_friday(year: int, month: int) -> date:
   206	tests/test_nfp_official_release_dates.py:77:    d = date(year, month, 1)
   207	tests/test_nfp_official_release_dates.py:82:def isolate_event_date_cache(monkeypatch, tmp_path):
   208	tests/test_nfp_official_release_dates.py:87:def official(monkeypatch):
   209	tests/test_nfp_official_release_dates.py:91:    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
   210	tests/test_nfp_official_release_dates.py:95:def experiment():
   211	tests/test_nfp_official_release_dates.py:106:    def test_proxy_date_is_not_an_official_release(
   212	tests/test_nfp_official_release_dates.py:110:            f"{proxy_date} came from the first-Friday proxy and is not an "
   213	tests/test_nfp_official_release_dates.py:111:            "Employment Situation release date"
   214	tests/test_nfp_official_release_dates.py:117:    def test_mismatch_really_is_what_the_proxy_would_have_produced(
   215	tests/test_nfp_official_release_dates.py:120:        """Guard the fixture itself: each 'proxy' date must be a first Friday.
   216	tests/test_nfp_official_release_dates.py:126:        assert _first_friday(d.year, d.month) == d.date()
   217	tests/test_nfp_official_release_dates.py:128:    def test_october_2025_release_does_not_exist(self, official):
   218	tests/test_nfp_official_release_dates.py:131:        No Employment Situation was published in October 2025. A monthly
   219	tests/test_nfp_official_release_dates.py:135:        assert not [d for d in official if (d.year, d.month) == (2025, 10)]
   220	tests/test_nfp_official_release_dates.py:138:    def test_proxy_dates_that_were_already_correct_stay_correct(
   221	tests/test_nfp_official_release_dates.py:143:    def test_seven_of_thirteen_were_wrong(self, official):
   222	tests/test_nfp_official_release_dates.py:144:        """The headline number from the K1442 audit, recomputed not restated."""
   223	tests/test_nfp_official_release_dates.py:147:        while len(proxy_dates) < 13:
   224	tests/test_nfp_official_release_dates.py:161:    def test_release_date_is_july_2_not_july_3(self, experiment):
   225	tests/test_nfp_official_release_dates.py:162:        """July 4 fell on a Saturday, observed Friday July 3, so BLS moved up."""
   226	tests/test_nfp_official_release_dates.py:166:    def test_build_nfp_dates_returns_the_official_trailing_thirteen(
   227	tests/test_nfp_official_release_dates.py:174:            "nfp_release_dates",
   228	tests/test_nfp_official_release_dates.py:175:            lambda start, end, **kw: event_dates.nfp_release_dates(
   229	tests/test_nfp_official_release_dates.py:180:        actual = [str(d.date()) for d in experiment.build_nfp_dates(13)]
   230	tests/test_nfp_official_release_dates.py:181:        assert actual == EXPECTED_TRAILING_13
   231	tests/test_nfp_official_release_dates.py:183:    def test_release_date_itself_is_excluded(self, experiment, monkeypatch):
   232	tests/test_nfp_official_release_dates.py:190:            "nfp_release_dates",
   233	tests/test_nfp_official_release_dates.py:191:            lambda start, end, **kw: event_dates.nfp_release_dates(
   234	tests/test_nfp_official_release_dates.py:196:        assert pd.Timestamp("2026-07-02") not in experiment.build_nfp_dates(13)
   235	tests/test_nfp_official_release_dates.py:198:    def test_fails_closed_when_calendar_is_short(self, experiment, monkeypatch):
   236	tests/test_nfp_official_release_dates.py:202:            "nfp_release_dates",
   237	tests/test_nfp_official_release_dates.py:206:        with pytest.raises(RuntimeError, match="only 1 releases"):
   238	tests/test_nfp_official_release_dates.py:207:            experiment.build_nfp_dates(13)
   239	tests/test_nfp_official_release_dates.py:209:    def test_fails_closed_when_calendar_is_unreachable(
   240	tests/test_nfp_official_release_dates.py:212:        def boom(*_a, **_kw):
   241	tests/test_nfp_official_release_dates.py:215:        monkeypatch.setattr(experiment, "nfp_release_dates", boom)
   242	tests/test_nfp_official_release_dates.py:218:            experiment.build_nfp_dates(13)
   243	tests/test_nfp_official_release_dates.py:222:    """The download window itself must exclude the release day.
   244	tests/test_nfp_official_release_dates.py:233:    def _capture_downloads(self, experiment, monkeypatch):
   245	tests/test_nfp_official_release_dates.py:236:        def recorder(ticker, **kw):
   246	tests/test_nfp_official_release_dates.py:250:            "nfp_release_dates",
   247	tests/test_nfp_official_release_dates.py:251:            lambda start, end, **kw: event_dates.nfp_release_dates(
   248	tests/test_nfp_official_release_dates.py:262:    def test_every_series_is_downloaded(self, experiment, monkeypatch):
   249	tests/test_nfp_official_release_dates.py:267:    def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
   250	tests/test_nfp_official_release_dates.py:271:            # yfinance `end` is exclusive, so end == release date means the
   251	tests/test_nfp_official_release_dates.py:275:                "the 2026-07-02 release day must not be downloadable"
   252	tests/test_nfp_official_release_dates.py:278:    def test_download_window_starts_before_the_earliest_event(
   253	tests/test_nfp_official_release_dates.py:302:    def columns(self):
   254	tests/test_nfp_official_release_dates.py:310:    def test_experiment_defines_no_first_friday_helper(self):
   255	tests/test_nfp_official_release_dates.py:312:        assert "def first_friday" not in src
   256	tests/test_nfp_official_release_dates.py:315:    def test_experiment_imports_the_official_calendar(self):
   257	tests/test_nfp_official_release_dates.py:317:        assert "from volpred.data.event_dates import nfp_release_dates" in src
   258	tests/test_nfp_official_release_dates.py:319:    def test_results_json_declares_its_event_date_source(self):
   259	tests/test_nfp_official_release_dates.py:326:        assert results["nfp_release_date"] == "2026-07-02"
   260	tests/test_nfp_official_release_dates.py:327:        assert "nfp_release_dates" in results["event_date_source"]
   261	tests/test_nfp_official_release_dates.py:328:        assert [r["nfp_release_date"] for r in results["historical_nfp_table"]] == (
   262	tests/test_nfp_official_release_dates.py:329:            EXPECTED_TRAILING_13
   263	tests/test_nfp_official_release_dates.py:336:# The sibling experiment above had 13 events. K528 had 254 and fed six numbers
   264	tests/test_nfp_official_release_dates.py:338:# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
   265	tests/test_nfp_official_release_dates.py:349:def _load_k528(path):
   266	tests/test_nfp_official_release_dates.py:355:def _k528_event_dates():
   267	tests/test_nfp_official_release_dates.py:359:def assert_not_first_friday_proxy(dates):
   268	tests/test_nfp_official_release_dates.py:360:    """Reject a calendar carrying the first-Friday proxy's fingerprints.
   269	tests/test_nfp_official_release_dates.py:372:            f"all {len(dates)} releases fall on a Friday. The official calendar "
   270	tests/test_nfp_official_release_dates.py:373:            "does not: BLS moves the release off Friday at holiday and shutdown "
   271	tests/test_nfp_official_release_dates.py:378:        d for d in dates if d.date() == _first_friday(d.year, d.month)
   272	tests/test_nfp_official_release_dates.py:382:            "every release sits on the first Friday of its month -- proxy calendar"
   273	tests/test_nfp_official_release_dates.py:385:    phantom = [d for d in dates if (d.year, d.month) == (2025, 10)]
   274	tests/test_nfp_official_release_dates.py:388:            f"calendar contains an October 2025 release ({phantom[0].date()}). "
   275	tests/test_nfp_official_release_dates.py:394:    def test_defines_no_first_friday_helper(self):
   276	tests/test_nfp_official_release_dates.py:396:        assert "def get_first_friday" not in src
   277	tests/test_nfp_official_release_dates.py:397:        assert "def generate_nfp_dates" not in src
   278	tests/test_nfp_official_release_dates.py:400:    def test_imports_the_official_calendar(self):
   279	tests/test_nfp_official_release_dates.py:402:        assert "from volpred.data.event_dates import nfp_release_dates" in src
   280	tests/test_nfp_official_release_dates.py:404:    def test_results_declare_the_official_source_and_no_fallback(self):

exec
/bin/zsh -lc 'git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show --name-status --format=fuller --no-renames 2abb3f68c
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/codex_review_v3.md | nl -ba' in /Users/yhlai0911/volpred-research
 succeeded in 179ms:
commit 2abb3f68c5b2ca480bffbd7d919da884a970d72b
Author:     yhlai <yihao.lai@gmail.com>
AuthorDate: Sun Jul 19 16:36:58 2026 +0800
Commit:     yhlai <yihao.lai@gmail.com>
CommitDate: Sun Jul 19 16:36:58 2026 +0800

    fix(k528): 修 Codex 三審 round-1 的三個 BLOCKER + findings 4-6
    
    Codex 三審對 commit 6fd281901 判 FAIL。三條 blocking 中有兩條本輪自查已獨立發現
    並修好（Codex 的 post-fix 預測數值 1.18899/p=0.02086 與 1.17676/p=0.02569 與實測
    逐位吻合），第三條是 Codex 獨立找到的：
    
    - BLOCKER 1 控制組洩漏：2005-01-07 因事件窗不足被排除出事件組，卻仍留在對照組 ——
      正是本實驗存在的理由（把真的事件日丟進對照組）的 1/253 版本。對照組改為排除全部
      254 個已映射 session（5087→5086）
    - BLOCKER 2 audit 拿不同 estimand 硬比，且「proxy 全為週五」是錯的：proxy 日曆確為
      全週五，但遇休市映射到下一 session，實際 239 Friday/15 Monday。混合程度修正前後
      幾乎相同（94.1%→93.7%），亦即該缺陷不是日期修正造成的。audit 改為兩種口徑各自
      平行呈現，主對照兩欄同口徑，差異可歸因於日期
    - BLOCKER 3 fail-closed 仍可繞過：只驗 accessor 輸出無效（它已先按月收斂）。改為
      同時驗 raw feed，四道關卡：同月兩筆 <3 天視為無法辨識、選擇非最早、觀測跨度內
      缺月（移除首尾月無條件豁免）、allowlist 宣稱的缺口回頭驗證 raw 真的沒資料
    - finding 4 claim scope：週五限定是 conditional estimand，不再支撐「NFP 一般而言」
      的敘述；排除的 16 場比週五場平靜 16.3%，限定會墊高倍數 —— 已在 results、README
      與讀者更正說明三處揭露
    - finding 5 內部矛盾：results 散文寫「11 場 non-Friday」、資料寫 16，改為由資料生成
    - finding 6 overclaim：fixture 是 _fetch 回傳值不是完整 HTTP bytes，docstring 已改口
      並明寫覆蓋邊界；測試檔殘留的 p=0.0571 敘述改為記錄「那是錯的」
    
    新增迴歸測試：TestControlGroupHasNoNfpDays、TestCalendarFailClosedCannotBeBypassed
    （逐條釘住四個繞過路徑 + 一個必須通過的乾淨日曆）、TestFridayEstimandIsScopedHonestly。
    
    驗證：115 tests 全綠；experiment_gates PASS；19/19 文章替換各命中一次；
    dry-run 不寫入以 sha256+mtime 實測。
    
    Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>

M	experiments/k528/README.md
M	experiments/k528/build_article_correction.py
A	experiments/k528/codex_review_v3.md
M	experiments/k528/k528_nfp_event_study.py
M	experiments/k528/k528_nfp_event_study_results.json
M	experiments/k528/k528_nfp_official_dates_results.json
M	tests/fixtures/fred_release_50_nfp_raw_20260719.json
M	tests/test_event_dates_real_raw_response.py
M	tests/test_nfp_official_release_dates.py
     1	OpenAI Codex v0.144.1
     2	--------
     3	workdir: /Users/yhlai0911/volpred-research
     4	model: gpt-5.6-sol
     5	provider: openai
     6	approval: never
     7	sandbox: read-only
     8	reasoning effort: high
     9	reasoning summaries: none
    10	session id: 019f7975-0d36-77d3-9b16-20f8155c2e84
    11	--------
    12	user
    13	你是嚴格的計量金融代碼審查者。三審 K528 NFP 事件研究修正案。
    14	
    15	**審查對象**（絕對路徑 `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/`）：
    16	
    17	實驗目錄 `experiments/k528/`：
    18	- `README.md`（宣稱面）
    19	- `k528_nfp_event_study.py`（主腳本）
    20	- `k528_nfp_event_study_results.json`（現行結果）
    21	- `k528_nfp_event_study_results_PROXY_SUPERSEDED.json`（proxy 時代存證）
    22	- `k528_nfp_official_dates_results.json`（前後對照 audit + 文章更正計畫）
    23	- `build_article_correction.py`（文章 mile_35eef830 的更正清單）
    24	- `codex_review_v2.md` + `review_verdict.json`（**你上一輪的 FAIL 裁決，本輪要驗收它**）
    25	
    26	共用模組與測試：
    27	- `src/volpred/data/event_dates.py`（官方日曆 accessor，根修）
    28	- `tests/test_event_dates_real_raw_response.py`（新增）
    29	- `tests/test_event_dates_release_selection.py`
    30	- `tests/test_nfp_official_release_dates.py`
    31	- `tests/fixtures/fred_release_50_nfp_raw_20260719.json`（新增，ALFRED 原始回應）
    32	
    33	**背景**：你在二審（`codex_review_v2.md`）判 FAIL，列三條 blocking defects 與 findings 3-8。
    34	本輪是針對那些 issue 的 remediation。commit `6fd281901`。
    35	
    36	**本輪聲稱做了什麼**（逐條驗收，不要照單全收）：
    37	
    38	1. **BLOCKER 1（accessor 取 max() 選錯六個日期）** — 聲稱根修在 main commit `305d118a3`，
    39	   改為 per-month `min()` + 13–110 天 cadence fail-closed 驗證；branch 已 rebase 帶入。
    40	   聲稱六個月份以 live ALFRED 驗證正確：2006-05-05 / 2012-12-07 / 2013-05-03 /
    41	   2020-05-08 / 2024-01-05 / 2024-08-02。
    42	
    43	2. **BLOCKER 2（顯著性翻轉不成立）** — 聲稱確認你是對的：翻轉不成立。舊口徑重算得
    44	   1.1779×、p=0.02488（與你二審預算一致）；新口徑（週五對週五）為 1.190×、p=0.0202。
    45	   原 18 條文章更正**全數作廢**，改為 19 條純數值重述、0 條方向翻轉。
    46	
    47	3. **BLOCKER 3 / finding 4（fail-closed 不完整）** — 聲稱補了 `check_calendar_is_complete`
    48	   （同月多筆 raise、樣本窗內缺月 raise，2025-10 政府關門列 `KNOWN_MISSING_MONTHS`）
    49	   與事件日→交易日一對一斷言（找不到 session raise、兩發布日撞同 session raise）。
    50	
    51	4. **finding 5（Friday baseline estimand）** — 聲稱改為「237 場週五 NFP vs 非 NFP 週五」，
    52	   兩邊星期別一致；未採 weekday-matched controls 的理由寫在 README；舊口徑以
    53	   `B_diagnostic_mixed_weekday` 保留並標 DIAGNOSTIC ONLY。
    54	
    55	5. **finding 6（方向性敘述超過證據）** — 聲稱移除 "insignificant across all tests"，
    56	   每個顯著性陳述綁定自己的檢定。
    57	
    58	6. **finding 7（原子寫入 / dry-run）** — 聲稱主結果與 audit 改 temp+fsync+`os.replace`；
    59	   builder dry-run 改為真的不寫。
    60	
    61	7. **finding 8（superseded metadata）** — 聲稱 archive JSON 本體加了
    62	   `superseded` / `do_not_cite` / 撤回原因。
    63	
    64	8. **迴歸測試** — 聲稱新增用真實 raw-response 語義（同月多筆）的 regression test，
    65	   並附 mutation 檢查；聲稱實測 `min()`→`max()` 會轉紅。
    66	
    67	**審查重點（請獨立驗算，不要只讀 diff）**：
    68	
    69	1. 六個問題月份是否真的修正（自己跑 accessor 或讀 fixture 核對）
    70	2. 統計量是否可獨立重現：特別是 1.190×/p=0.0202（新口徑）與 1.1779×/p=0.02488（舊口徑）
    71	3. **estimand 選擇是否誠實且一致**：限定週五是否有把樣本選擇偏誤引進來？
    72	   `B_diagnostic_mixed_weekday` 有沒有被誤用成 headline？audit 的 before/after 對照
    73	   是否拿了不同口徑硬比（`before` 是舊口徑、`after` 是新口徑，這樣比公平嗎？
    74	   README 有沒有講清楚）？
    75	4. 19 條文章更正是否逐條與新 results 對齊（抽查至少 8 條）；作廢 18 條的理由是否成立；
    76	   有沒有殘留任何方向翻轉
    77	5. fail-closed 是否真的關上（試著想出能繞過 `check_calendar_is_complete` 的輸入）；
    78	   `KNOWN_MISSING_MONTHS` 是不是被拿來讓檢查通過的後門
    79	6. 新測試是否**真的**測得到 bug（fixture 有沒有被動過手腳、mutation 檢查是否 vacuous）
    80	7. lookahead / seed / 原子寫入等標準防錯
    81	8. README 宣稱面與 artifact 是否一致（有沒有 overclaim）
    82	
    83	**特別注意**：本輪 agent 有動機把結果導向「已修好」。請主動找它可能自我欺騙的地方。
    84	若發現新的 blocking defect，照列不誤；若確認修好了，也請明說哪幾條已驗收。
    85	
    86	**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出
    87	`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 須列 blocking defects）。
    88	
    89	codex
    90	我會把二審裁決當作驗收規格，但不採信本輪摘要：先讀統一 handoff 與舊裁決，再核對 commit/diff、fixture 原始語義，最後用獨立計算與 mutation/邊界案例重跑。全程只讀，不改工作樹。
    91	  → 讀 handoff、二審裁決與本輪 commit/diff，建立逐項驗收表
    92	  • 審查 accessor、fixture、fail-closed 與測試，做 mutation/繞過驗證
    93	  • 獨立重算新舊 estimand 統計量並核對事件日期
    94	  • 核對 README、results、audit、19 條文章更正與 superseded metadata
    95	  • 彙整逐點 findings、blocking defects 與最終 verdict
    96	exec
    97	/bin/zsh -lc "sed -n '1,240p' storage/ops/handoff_latest.md
    98	pwd
    99	git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short --branch
   100	git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show --stat --oneline --decorate --no-renames 6fd281901
   101	git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff --stat 6fd281901"'^ 6fd281901' in /Users/yhlai0911/volpred-research
   102	 succeeded in 205ms:
   103	## k528-nfp-official-dates
   104	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
   105	 experiments/k528/README.md                         |  188 +-
   106	 experiments/k528/build_article_correction.py       |  170 +-
   107	 experiments/k528/codex_review_v2.md                | 5028 ++++++++++++++++++++
   108	 experiments/k528/k528_nfp_event_study.py           |  338 +-
   109	 experiments/k528/k528_nfp_event_study_results.json | 2698 +++++------
   110	 ...8_nfp_event_study_results_PROXY_SUPERSEDED.json |   13 +
   111	 .../k528/k528_nfp_official_dates_results.json      |  153 +-
   112	 experiments/k528/review_verdict.json               |   20 +
   113	 .../fixtures/fred_release_50_nfp_raw_20260719.json |  278 ++
   114	 tests/test_event_dates_real_raw_response.py        |  106 +
   115	 tests/test_nfp_official_release_dates.py           |   40 +-
   116	 11 files changed, 7461 insertions(+), 1571 deletions(-)
   117	 experiments/k528/README.md                         |  188 +-
   118	 experiments/k528/build_article_correction.py       |  170 +-
   119	 experiments/k528/codex_review_v2.md                | 5028 ++++++++++++++++++++
   120	 experiments/k528/k528_nfp_event_study.py           |  338 +-
   121	 experiments/k528/k528_nfp_event_study_results.json | 2698 +++++------
   122	 ...8_nfp_event_study_results_PROXY_SUPERSEDED.json |   13 +
   123	 .../k528/k528_nfp_official_dates_results.json      |  153 +-
   124	 experiments/k528/review_verdict.json               |   20 +
   125	 .../fixtures/fred_release_50_nfp_raw_20260719.json |  278 ++
   126	 tests/test_event_dates_real_raw_response.py        |  106 +
   127	 tests/test_nfp_official_release_dates.py           |   40 +-
   128	 11 files changed, 7461 insertions(+), 1571 deletions(-)
   129	
   130	codex
   131	初步確認 worktree 乾淨、HEAD 是指定 commit。接下來我先鎖定實作與 artifact schema；二審檔異常膨脹到約 5,000 行，我只取其正式 findings/verdict 區段，不把工具輸出雜訊當審查內容。
   132	exec
   133	/bin/zsh -lc "git log --oneline --decorate -12
   134	git merge-base --is-ancestor 305d118a3 HEAD; printf 'ancestor_exit=%s\\n' \""'$?"
   135	rg -n "BLOCKER|Finding|VERDICT|FAIL|CONDITIONAL|PASS" experiments/k528/codex_review_v2.md experiments/k528/review_verdict.json | tail -n 120
   136	rg -n "def |KNOWN_MISSING|check_calendar|release|month|min'"\\(|max\\(|cadence|13|110|replace|fsync|dry.run|Friday|DIAGNOSTIC|headline|superseded|do_not_cite\" src/volpred/data/event_dates.py experiments/k528/k528_nfp_event_study.py experiments/k528/build_article_correction.py experiments/k528/README.md tests/test_event_dates_real_raw_response.py tests/test_event_dates_release_selection.py tests/test_nfp_official_release_dates.py" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
   137	 succeeded in 0ms:
   138	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
   139	e42dc25ad fix(k528): NFP 事件日改用官方日曆重跑，1 項顯著性翻轉
   140	50bb24870 (origin/main, origin/HEAD) dispatch(15:22): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(2)
   141	28a14f7c7 [codex] queue BMA remediation reruns
   142	1af0e3fbf [codex] guard BMA invalid model posterior
   143	363cae2a2 [codex] detect nested DM coefficient masks
   144	ae815f3e5 [codex] fix worktree-owned orphan outputs
   145	cb97c0b7f [codex] serialize compute retry and triage ownership
   146	175b3b67c [codex] fail snapaudit incomplete coverage review
   147	f0350b912 (k741-nfp-canonical) dispatch(14:42): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(8)、scripts(1)、scripts/tests/(1) 等 5 處
   148	20ffdc4a3 ci-fix(2): event_dates use_cache=False now bypasses cache WRITE too + guard_canonical_write before cache write; sandbox fixture in selection tests (repo-state guard leak)
   149	3cb072b83 firstfriday sweep: 8 archived-experiment README warnings + sweep report (9 sites, k741->volatility-absorption paper NFP table contamination documented)
   150	ancestor_exit=0
   151	experiments/k528/review_verdict.json:3:  "verdict": "FAIL",
   152	experiments/k528/codex_review_v2.md:31:**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出 `VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 列 blocking defects）。
   153	experiments/k528/codex_review_v2.md:73:- `k1708_fix_verdict_gate_20260717` P2 [experiment] [experiment] K1708 修正 stage：verdict gate 假陽性 + CW nesting/gate 替換三個 BLOCKER — claimed_by=hourly-slot-1-858545f95a864e298ddb4bc144a8c615
   154	experiments/k528/codex_review_v2.md:76:- `assign_5aa9d5f5` P2 [experiment] K1623 修復：撤回 long-memory 識別宣稱 + 補 MSE DM 與多重比較（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
   155	experiments/k528/codex_review_v2.md:77:- `assign_42306eaa` P2 [experiment] K1698 重跑：修 contract-selection lookahead + 夜盤邊界空驗證 + equivalence 檢定（codex FAIL） — claimed_by=hourly-slot-2-c5cafe39b455474b8cd5a4e225b64705
   156	experiments/k528/codex_review_v2.md:78:- `k1731_armB_rev7_remediation` P1 [experiment] K1731 arm B rev7 bounded remediation（Codex rev6 FAIL：B1a/B1b/B5/nested-DM detector）
   157	experiments/k528/codex_review_v2.md:223:**目前只有 1 篇真正 ready**：`leverage-direction`(JBF) — 6/11 技術定稿、合規只差 body.tex:231 一個 VolPred footnote（fix 在 audit json）。`vt-trend-following`(JPM/FAJ) 下一棒（6/30 才 v7 PASS + 10 個 K-id tags 待清）。
   158	experiments/k528/codex_review_v2.md:275:5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。
   159	experiments/k528/codex_review_v2.md:327:80-**規則**：worktree agent 只產 `experiments/kXXX/`，禁改共享狀態；主線程用 `scripts/merge_worktree.sh` 合併，**禁 `git worktree remove --force`**（L1 hook 擋）。實驗進 main 的唯一門票 = `experiments/<kid>/review_verdict.json` 且 sha256 綁「現在這份 bytes」（PASS 後又改 code 也擋）。裁決檔一律由 `verdict-template` 產生，不手抄。**保留 branch ≠ 收割成果**：clean tree 只證明沒有未提交檔案，不證明那些 commits 進了 main；移除 unmerged checkout 就是在製造下一個殭屍。**任務引用的資源會消失，必須有東西去 reconcile**——否則任務永遠 blocked 又永遠不關單。
   160	experiments/k528/codex_review_v2.md:371:136-  - **2026-07-15 07:15 hourly-07 collect_completed 收尾（closure）**：rerun 補上 circular-shift/phase-randomized null（common p=0.559、inception p=0.212 均未拒絕、Holm 0/13）+ no-timing 常數減碼 reference（複製 59–85% raw gap、matched gap ~0），commit `bdf6b451f`。主線程獨立重算兩樣本 byte 對齊；fresh-context code-reviewer 判 PASS（7/7 checklist 無 blocking defect）→ `experiments/k1695/review_verdict.json`（PASS，pin 現行 sha）+ certify PASS。knowledge append 更正條目 `8f80b2ee`（撤回舊 PASS `f4a73c83`）。paper 決定＝**撤除第三 contribution**（非把 null 包裝成 finding），routed to `paper_body_vt_trend_withdraw_k1695_contribution`。`feed_correction_k1695_exposure_artifact` 認證後已解除 blocked→pending P1。primary-path Codex re-verify 已 enqueue（`agent-brief_k1695_codex_reverify-be9cd6`）作 belt-and-suspenders。**流程觀察**：knowledge store append-only、無 in-place retract CLI，舊 PASS 條目仍在庫（靠 correction 條目 + `content_correction_scanner` 覆蓋）——若日後同類撤回頻繁，值得補 supersede 機制。
   161	experiments/k528/codex_review_v2.md:372:137-  - **2026-07-15 09:xx hourly-09 reader-facing 回溯更正完成（closure）**：`feed_correction_k1695_exposure_artifact` 執行完畢。3 篇 published（`mile_0d595dfb` 招牌篇、`mile_2d4edb65`、`mile_ee473d5a` VT 完全指南）於 feed.json `content` 前置「編者更正聲明」——保留原數字未刪，明寫舊結論被推翻＋推翻理由（曝險假象：VT 實現波動 0.61–0.68× B&H，同曝險口徑平均 ΔMDD −0.87pp/7-of-13、null p=0.559，一個固定減碼策略即複製 85%）；嚴守強度邊界（不寫「擇時有害」、不宣稱 inception +4.96pp 被否證）。2 篇 archived（`mile_f2e26f43`/`mile_9eaadbd1`）加「更正註記」。anti_ai_gate PASS；`storage/reports/<id>.json`（存在的 2 檔）同步；`supabase_sync full` 推平台（5 篇皆入 sync log、reconcile no_drift 1810=1810）。blast radius 從 code→paper→feed 全數收口。
   162	experiments/k528/codex_review_v2.md:373:138:- 2026-07-12 DM helper 在 h=1 退化成 iid，K565 的 Harvey PASS 被推翻 — Q3
   163	experiments/k528/codex_review_v2.md:398:214-- 2026-07-16 **3-STRIKE 級結構修復（老闆直接下令「該單一關口的就單一關口」）**：`volpred ops assign` 寫入的 `storage/ops/tasks/` queue **無任何 dispatcher 消費**（唯一 reader=手動 claim-next，無人跑）→ 16 任務黑洞 5 天，含結論已推翻仍在排隊的 K1695 舊敘事文章（執行=發錯誤內容）；同晚兩個並行互動 session 對老闆同一則 Telegram（msg877）**矛盾雙回覆**（msg879 排 credit→vol 研究 vs msg880 判 aggregate 版全 NULL），本 session 亦違反 claim-first（先做事先回覆最後才 claim）。**修**：(a) assign 重定向為 next_tasks.json thin wrapper（`append_next_task`，flock）；(b) 存量 17 個非終態 triage（4 終態含 1 deprecated 有害任務 + 13 遷入 canonical queue，credit 題合併雙方判斷成單一 brief）；(c) reply-right guard：`telegram-send --reply-to-task` 對已完成/他人持有任務拒發（break-then-verify 過）；(d) 機械 gate `scripts/tests/test_ops_tasks_receipts_only.py`（先 FAIL 於存量、遷移後轉綠，證明會咬）。設計：`docs/refactor_plan_single_gateway_task_system.md` — Q3
   164	experiments/k528/codex_review_v2.md:616:    31	the dates now come from the official release calendar and the run FAILS CLOSED
   165	experiments/k528/codex_review_v2.md:4378:     3	  "verdict": "FILL: PASS or FAIL — anything but PASS blocks the merge",
   166	experiments/k528/codex_review_v2.md:4384:     9	    "FILL: one entry per defect that makes this a FAIL; [] if PASS"
   167	experiments/k528/codex_review_v2.md:4985:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
   168	experiments/k528/codex_review_v2.md:4987:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
   169	experiments/k528/codex_review_v2.md:5005:VERDICT: FAIL
   170	experiments/k528/codex_review_v2.md:5008:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
   171	experiments/k528/codex_review_v2.md:5010:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
   172	experiments/k528/codex_review_v2.md:5028:VERDICT: FAIL
   173	experiments/k528/README.md:30:`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
   174	experiments/k528/README.md:31:release id 50），且**取不到就 raise，不回退 proxy**。
   175	experiments/k528/README.md:35:第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
   176	experiments/k528/README.md:37:因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：
   177	experiments/k528/README.md:39:| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
   178	experiments/k528/README.md:43:| 2013-05 | 2013-05-03 | 2013-05-06 |
   179	experiments/k528/README.md:52:根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
   180	experiments/k528/README.md:58:（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
   181	experiments/k528/README.md:59:那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。
   182	experiments/k528/README.md:64:- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
   183	experiments/k528/README.md:81:標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。
   184	experiments/k528/README.md:129:| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
   185	experiments/k528/README.md:131:| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
   186	experiments/k528/README.md:170:事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
   187	experiments/k528/README.md:180:accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
   188	experiments/k528/README.md:183:Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
   189	experiments/k528/README.md:188:- **日曆完整性**（`check_calendar_is_complete`）：同月多筆 → raise；樣本窗內缺月 → raise。
   190	experiments/k528/README.md:190:  條目），寫在 `KNOWN_MISSING_MONTHS` 並附理由 —— 這個清單是用來記錄真實缺口的，
   191	experiments/k528/README.md:195:- **原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`
   192	experiments/k528/README.md:201:- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
   193	experiments/k528/README.md:202:- K513：先前的 FOMC/NFP/CPI 事件研究
   194	tests/test_nfp_official_release_dates.py:1:"""Pin the NFP event dates that a first-Friday proxy gets wrong.
   195	tests/test_nfp_official_release_dates.py:3:`experiments/event_article_nfp_2026_07_03_t1` used to derive its NFP release
   196	tests/test_nfp_official_release_dates.py:4:dates from a "first Friday of the month" rule. Against the official BLS
   197	tests/test_nfp_official_release_dates.py:5:Employment Situation calendar, 7 of its 13 historical events were on the wrong
   198	tests/test_nfp_official_release_dates.py:6:day, and correcting them flipped the headline direction: the SPY up-day rate
   199	tests/test_nfp_official_release_dates.py:15:returned by FRED release id 50 (Employment Situation), fetched 2026-07-19.
   200	tests/test_nfp_official_release_dates.py:33:# Official Employment Situation release dates, FRED release id 50.
   201	tests/test_nfp_official_release_dates.py:40:    # No October 2025 release: the shutdown cancelled it and pushed the
   202	tests/test_nfp_official_release_dates.py:47:# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
   203	tests/test_nfp_official_release_dates.py:67:# What the experiment must use: trailing 13 official releases before 2026-07-02.
   204	tests/test_nfp_official_release_dates.py:68:EXPECTED_TRAILING_13 = [
   205	tests/test_nfp_official_release_dates.py:75:def _first_friday(year: int, month: int) -> date:
   206	tests/test_nfp_official_release_dates.py:77:    d = date(year, month, 1)
   207	tests/test_nfp_official_release_dates.py:82:def isolate_event_date_cache(monkeypatch, tmp_path):
   208	tests/test_nfp_official_release_dates.py:87:def official(monkeypatch):
   209	tests/test_nfp_official_release_dates.py:91:    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
   210	tests/test_nfp_official_release_dates.py:95:def experiment():
   211	tests/test_nfp_official_release_dates.py:106:    def test_proxy_date_is_not_an_official_release(
   212	tests/test_nfp_official_release_dates.py:110:            f"{proxy_date} came from the first-Friday proxy and is not an "
   213	tests/test_nfp_official_release_dates.py:111:            "Employment Situation release date"
   214	tests/test_nfp_official_release_dates.py:117:    def test_mismatch_really_is_what_the_proxy_would_have_produced(
   215	tests/test_nfp_official_release_dates.py:120:        """Guard the fixture itself: each 'proxy' date must be a first Friday.
   216	tests/test_nfp_official_release_dates.py:126:        assert _first_friday(d.year, d.month) == d.date()
   217	tests/test_nfp_official_release_dates.py:128:    def test_october_2025_release_does_not_exist(self, official):
   218	tests/test_nfp_official_release_dates.py:131:        No Employment Situation was published in October 2025. A monthly
   219	tests/test_nfp_official_release_dates.py:135:        assert not [d for d in official if (d.year, d.month) == (2025, 10)]
   220	tests/test_nfp_official_release_dates.py:138:    def test_proxy_dates_that_were_already_correct_stay_correct(
   221	tests/test_nfp_official_release_dates.py:143:    def test_seven_of_thirteen_were_wrong(self, official):
   222	tests/test_nfp_official_release_dates.py:144:        """The headline number from the K1442 audit, recomputed not restated."""
   223	tests/test_nfp_official_release_dates.py:147:        while len(proxy_dates) < 13:
   224	tests/test_nfp_official_release_dates.py:161:    def test_release_date_is_july_2_not_july_3(self, experiment):
   225	tests/test_nfp_official_release_dates.py:162:        """July 4 fell on a Saturday, observed Friday July 3, so BLS moved up."""
   226	tests/test_nfp_official_release_dates.py:166:    def test_build_nfp_dates_returns_the_official_trailing_thirteen(
   227	tests/test_nfp_official_release_dates.py:174:            "nfp_release_dates",
   228	tests/test_nfp_official_release_dates.py:175:            lambda start, end, **kw: event_dates.nfp_release_dates(
   229	tests/test_nfp_official_release_dates.py:180:        actual = [str(d.date()) for d in experiment.build_nfp_dates(13)]
   230	tests/test_nfp_official_release_dates.py:181:        assert actual == EXPECTED_TRAILING_13
   231	tests/test_nfp_official_release_dates.py:183:    def test_release_date_itself_is_excluded(self, experiment, monkeypatch):
   232	tests/test_nfp_official_release_dates.py:190:            "nfp_release_dates",
   233	tests/test_nfp_official_release_dates.py:191:            lambda start, end, **kw: event_dates.nfp_release_dates(
   234	tests/test_nfp_official_release_dates.py:196:        assert pd.Timestamp("2026-07-02") not in experiment.build_nfp_dates(13)
   235	tests/test_nfp_official_release_dates.py:198:    def test_fails_closed_when_calendar_is_short(self, experiment, monkeypatch):
   236	tests/test_nfp_official_release_dates.py:202:            "nfp_release_dates",
   237	tests/test_nfp_official_release_dates.py:206:        with pytest.raises(RuntimeError, match="only 1 releases"):
   238	tests/test_nfp_official_release_dates.py:207:            experiment.build_nfp_dates(13)
   239	tests/test_nfp_official_release_dates.py:209:    def test_fails_closed_when_calendar_is_unreachable(
   240	tests/test_nfp_official_release_dates.py:212:        def boom(*_a, **_kw):
   241	tests/test_nfp_official_release_dates.py:215:        monkeypatch.setattr(experiment, "nfp_release_dates", boom)
   242	tests/test_nfp_official_release_dates.py:218:            experiment.build_nfp_dates(13)
   243	tests/test_nfp_official_release_dates.py:222:    """The download window itself must exclude the release day.
   244	tests/test_nfp_official_release_dates.py:233:    def _capture_downloads(self, experiment, monkeypatch):
   245	tests/test_nfp_official_release_dates.py:236:        def recorder(ticker, **kw):
   246	tests/test_nfp_official_release_dates.py:250:            "nfp_release_dates",
   247	tests/test_nfp_official_release_dates.py:251:            lambda start, end, **kw: event_dates.nfp_release_dates(
   248	tests/test_nfp_official_release_dates.py:262:    def test_every_series_is_downloaded(self, experiment, monkeypatch):
   249	tests/test_nfp_official_release_dates.py:267:    def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
   250	tests/test_nfp_official_release_dates.py:271:            # yfinance `end` is exclusive, so end == release date means the
   251	tests/test_nfp_official_release_dates.py:275:                "the 2026-07-02 release day must not be downloadable"
   252	tests/test_nfp_official_release_dates.py:278:    def test_download_window_starts_before_the_earliest_event(
   253	tests/test_nfp_official_release_dates.py:302:    def columns(self):
   254	tests/test_nfp_official_release_dates.py:310:    def test_experiment_defines_no_first_friday_helper(self):
   255	tests/test_nfp_official_release_dates.py:312:        assert "def first_friday" not in src
   256	tests/test_nfp_official_release_dates.py:315:    def test_experiment_imports_the_official_calendar(self):
   257	tests/test_nfp_official_release_dates.py:317:        assert "from volpred.data.event_dates import nfp_release_dates" in src
   258	tests/test_nfp_official_release_dates.py:319:    def test_results_json_declares_its_event_date_source(self):
   259	tests/test_nfp_official_release_dates.py:326:        assert results["nfp_release_date"] == "2026-07-02"
   260	tests/test_nfp_official_release_dates.py:327:        assert "nfp_release_dates" in results["event_date_source"]
   261	tests/test_nfp_official_release_dates.py:328:        assert [r["nfp_release_date"] for r in results["historical_nfp_table"]] == (
   262	tests/test_nfp_official_release_dates.py:329:            EXPECTED_TRAILING_13
   263	tests/test_nfp_official_release_dates.py:336:# The sibling experiment above had 13 events. K528 had 254 and fed six numbers
   264	tests/test_nfp_official_release_dates.py:338:# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
   265	tests/test_nfp_official_release_dates.py:349:def _load_k528(path):
   266	tests/test_nfp_official_release_dates.py:355:def _k528_event_dates():
   267	tests/test_nfp_official_release_dates.py:359:def assert_not_first_friday_proxy(dates):
   268	tests/test_nfp_official_release_dates.py:360:    """Reject a calendar carrying the first-Friday proxy's fingerprints.
   269	tests/test_nfp_official_release_dates.py:372:            f"all {len(dates)} releases fall on a Friday. The official calendar "
   270	tests/test_nfp_official_release_dates.py:373:            "does not: BLS moves the release off Friday at holiday and shutdown "
   271	tests/test_nfp_official_release_dates.py:378:        d for d in dates if d.date() == _first_friday(d.year, d.month)
   272	tests/test_nfp_official_release_dates.py:382:            "every release sits on the first Friday of its month -- proxy calendar"
   273	tests/test_nfp_official_release_dates.py:385:    phantom = [d for d in dates if (d.year, d.month) == (2025, 10)]
   274	tests/test_nfp_official_release_dates.py:388:            f"calendar contains an October 2025 release ({phantom[0].date()}). "
   275	tests/test_nfp_official_release_dates.py:394:    def test_defines_no_first_friday_helper(self):
   276	tests/test_nfp_official_release_dates.py:396:        assert "def get_first_friday" not in src
   277	tests/test_nfp_official_release_dates.py:397:        assert "def generate_nfp_dates" not in src
   278	tests/test_nfp_official_release_dates.py:400:    def test_imports_the_official_calendar(self):
   279	tests/test_nfp_official_release_dates.py:402:        assert "from volpred.data.event_dates import nfp_release_dates" in src
   280	tests/test_nfp_official_release_dates.py:404:    def test_results_declare_the_official_source_and_no_fallback(self):
   281	tests/test_nfp_official_release_dates.py:406:        assert "nfp_release_dates" in source["accessor"]
   282	tests/test_nfp_official_release_dates.py:409:    def test_event_dates_carry_no_proxy_signature(self):
   283	tests/test_nfp_official_release_dates.py:412:    def test_sample_is_not_uniformly_friday(self):
   284	tests/test_nfp_official_release_dates.py:420:    def test_audit_records_the_dates_that_changed(self):
   285	tests/test_nfp_official_release_dates.py:430:    def test_no_off_cycle_revision_date_is_treated_as_an_event(self):
   286	tests/test_nfp_official_release_dates.py:433:        For six months ALFRED returns two release-id-50 entries; the later one
   287	tests/test_nfp_official_release_dates.py:435:        An earlier rerun selected those six and moved the NFP-vs-Friday test
   288	tests/test_nfp_official_release_dates.py:441:            "2006-05-08", "2012-12-12", "2013-05-06",
   289	tests/test_nfp_official_release_dates.py:445:            "2006-05-05", "2012-12-07", "2013-05-03",
   290	tests/test_nfp_official_release_dates.py:453:            f"regular releases missing from k528 event set: {sorted(regular - event_dates)}"
   291	tests/test_nfp_official_release_dates.py:463:    def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
   292	tests/test_nfp_official_release_dates.py:466:            last = 12 if year < end_year else end_month
   293	tests/test_nfp_official_release_dates.py:467:            for month in range(1, last + 1):
   294	tests/test_nfp_official_release_dates.py:468:                out.append(pd.Timestamp(_first_friday(year, month)))
   295	tests/test_nfp_official_release_dates.py:471:    def test_the_proxy_calendar_is_rejected(self):
   296	tests/test_nfp_official_release_dates.py:472:        with pytest.raises(AssertionError, match="Friday"):
   297	tests/test_nfp_official_release_dates.py:475:    def test_phantom_october_2025_alone_is_enough_to_fail(self):
   298	tests/test_nfp_official_release_dates.py:483:    def test_the_guard_accepts_the_official_calendar(self, official):
   299	experiments/k528/build_article_correction.py:3:The article was published 2026-07-01 with headline numbers taken from K528,
   300	experiments/k528/build_article_correction.py:4:which dated every NFP to the first Friday of the month. On the official BLS
   301	experiments/k528/build_article_correction.py:12:months where ALFRED returns two entries, picked the LATER one -- an off-cycle
   302	experiments/k528/build_article_correction.py:14:dates were therefore wrong (2006-05-08, 2012-12-12, 2013-05-06, 2020-05-11,
   303	experiments/k528/build_article_correction.py:18:NFP-vs-Friday test across the 5% line. The voided list told readers that a
   304	experiments/k528/build_article_correction.py:25:So: no claim in this article reverses direction. Every replacement below is a
   305	experiments/k528/build_article_correction.py:30:Under the proxy every NFP landed on a Friday by construction, so "NFP days vs
   306	experiments/k528/build_article_correction.py:31:non-NFP Fridays" held weekday fixed for free. On the official calendar 16 of
   307	experiments/k528/build_article_correction.py:32:253 events are not Fridays, so that same comparison would put a weekday-mixed
   308	experiments/k528/build_article_correction.py:33:event group against a pure-Friday control group and let the Friday effect leak
   309	experiments/k528/build_article_correction.py:35:Friday releases. This is stated in the article's correction note rather than
   310	experiments/k528/build_article_correction.py:47:every replacement against the canonical article, proving each matches exactly
   311	experiments/k528/build_article_correction.py:93:    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
   312	experiments/k528/build_article_correction.py:119:        "分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；"
   313	experiments/k528/build_article_correction.py:143:        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
   314	experiments/k528/build_article_correction.py:173:        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
   315	experiments/k528/build_article_correction.py:194:def load_article_content(storage_dir: Path) -> str:
   316	experiments/k528/build_article_correction.py:202:def validate(storage_dir: Path) -> list[dict]:
   317	experiments/k528/build_article_correction.py:203:    """Resolve every replacement against the live article. Raises if any does
   318	experiments/k528/build_article_correction.py:215:def _write_json_atomic(path: Path, payload) -> None:
   319	experiments/k528/build_article_correction.py:222:            os.fsync(f.fileno())
   320	experiments/k528/build_article_correction.py:223:        os.replace(tmp, path)
   321	experiments/k528/build_article_correction.py:232:def record_plan(validated: list[dict], applied: dict | None) -> None:
   322	experiments/k528/build_article_correction.py:237:        "n_replacements": len(REPLACEMENTS),
   323	experiments/k528/build_article_correction.py:244:                "off-cycle ALFRED entries for six months, which pushed the "
   324	experiments/k528/build_article_correction.py:245:                "NFP-vs-Friday test across the 5% line. It would have retracted a "
   325	experiments/k528/build_article_correction.py:250:        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
   326	experiments/k528/build_article_correction.py:262:def main() -> int:
   327	experiments/k528/build_article_correction.py:273:    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   328	experiments/k528/build_article_correction.py:284:            content_replacements=REPLACEMENTS,
   329	experiments/k528/build_article_correction.py:286:                "K528 event dates corrected from a first-Friday proxy to the official BLS "
   330	experiments/k528/build_article_correction.py:287:                "release calendar. Sample 254 -> 253 events; headline numbers restated "
   331	experiments/k528/build_article_correction.py:288:                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
   332	experiments/k528/build_article_correction.py:289:                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
   333	experiments/k528/build_article_correction.py:290:                "now restricts the event group to the 237 Friday releases so weekday is "
   334	experiments/k528/build_article_correction.py:296:        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
   335	experiments/k528/build_article_correction.py:299:    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
   336	experiments/k528/build_article_correction.py:305:        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
   337	tests/test_event_dates_real_raw_response.py:3:Why this file exists, separately from test_event_dates_release_selection.py:
   338	tests/test_event_dates_real_raw_response.py:5:The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
   339	tests/test_event_dates_real_raw_response.py:6:a *hand-built* fixture in which the same-month duplicate entries had already
   340	tests/test_event_dates_real_raw_response.py:8:not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
   341	tests/test_event_dates_real_raw_response.py:12:it is real input. This module pins `_fetch`'s actual bytes for release id 50
   342	tests/test_event_dates_real_raw_response.py:14:six regular releases survive selection.
   343	tests/test_event_dates_real_raw_response.py:16:Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
   344	tests/test_event_dates_real_raw_response.py:28:_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
   345	tests/test_event_dates_real_raw_response.py:30:# The six months ALFRED returns twice for, with the regular Employment Situation
   346	tests/test_event_dates_real_raw_response.py:31:# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
   347	tests/test_event_dates_real_raw_response.py:32:# filed against the same release id LATER in the month). Verified against the
   348	tests/test_event_dates_real_raw_response.py:33:# live API on 2026-07-19; the right-hand column is exactly what the old max()
   349	tests/test_event_dates_real_raw_response.py:38:    "2013-05": ("2013-05-03", "2013-05-06"),
   350	tests/test_event_dates_real_raw_response.py:46:def _sandbox_cache_dir(monkeypatch, tmp_path):
   351	tests/test_event_dates_real_raw_response.py:52:def raw_response() -> list[str]:
   352	tests/test_event_dates_real_raw_response.py:53:    return json.loads(_FIXTURE.read_text())["release_dates"]
   353	tests/test_event_dates_real_raw_response.py:57:def selected(monkeypatch, raw_response) -> list[str]:
   354	tests/test_event_dates_real_raw_response.py:59:    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
   355	tests/test_event_dates_real_raw_response.py:63:def test_fixture_still_carries_the_duplicate_months(raw_response):
   356	tests/test_event_dates_real_raw_response.py:65:    by_month: dict[str, list[str]] = {}
   357	tests/test_event_dates_real_raw_response.py:67:        by_month.setdefault(d[:7], []).append(d)
   358	tests/test_event_dates_real_raw_response.py:68:    multi = {m: v for m, v in by_month.items() if len(v) > 1}
   359	tests/test_event_dates_real_raw_response.py:70:        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
   360	tests/test_event_dates_real_raw_response.py:73:    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
   361	tests/test_event_dates_real_raw_response.py:74:        assert sorted(multi[month]) == [regular, off_cycle]
   362	tests/test_event_dates_real_raw_response.py:77:def test_regular_release_wins_in_every_duplicate_month(selected):
   363	tests/test_event_dates_real_raw_response.py:78:    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
   364	tests/test_event_dates_real_raw_response.py:79:        in_month = [d for d in selected if d.startswith(month)]
   365	tests/test_event_dates_real_raw_response.py:80:        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
   366	tests/test_event_dates_real_raw_response.py:84:def test_selection_is_one_per_month_and_complete(selected, raw_response):
   367	tests/test_event_dates_real_raw_response.py:85:    months_in = {d[:7] for d in raw_response}
   368	tests/test_event_dates_real_raw_response.py:86:    months_out = [d[:7] for d in selected]
   369	tests/test_event_dates_real_raw_response.py:87:    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
   370	tests/test_event_dates_real_raw_response.py:88:    assert set(months_out) == months_in, "selection dropped or invented a month"
   371	tests/test_event_dates_real_raw_response.py:92:def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
   372	tests/test_event_dates_real_raw_response.py:95:    Without this, a future refactor could silently restore max() and the two
   373	tests/test_event_dates_real_raw_response.py:99:    by_month: dict[str, list[str]] = {}
   374	tests/test_event_dates_real_raw_response.py:101:        by_month.setdefault(d[:7], []).append(d)
   375	tests/test_event_dates_real_raw_response.py:102:    old_rule = {m: max(v) for m, v in by_month.items()}
   376	tests/test_event_dates_real_raw_response.py:105:        "the old max() rule must pick exactly the six off-cycle dates on this input"
   377	tests/test_event_dates_release_selection.py:1:"""Regression tests for release_dates off-cycle selection + cadence gate.
   378	tests/test_event_dates_release_selection.py:3:2026-07-19 k528 Codex review: the old per-month max() rule picked 6 off-cycle
   379	tests/test_event_dates_release_selection.py:5:release id, later in the month) as NFP event dates, flipping a significance
   380	tests/test_event_dates_release_selection.py:6:result. The fix keeps each month's EARLIEST entry and fail-closes when the
   381	tests/test_event_dates_release_selection.py:7:resulting sequence does not look like a monthly release calendar.
   382	tests/test_event_dates_release_selection.py:17:def _sandbox_cache_dir(monkeypatch, tmp_path):
   383	tests/test_event_dates_release_selection.py:23:def _dates(monkeypatch, raw):
   384	tests/test_event_dates_release_selection.py:25:    return event_dates.release_dates("NFP_US", "2024-01-01", "2024-12-31", use_cache=False)
   385	tests/test_event_dates_release_selection.py:28:def test_off_cycle_late_entry_loses_to_regular_release(monkeypatch):
   386	tests/test_event_dates_release_selection.py:38:def test_shutdown_gap_within_band_passes(monkeypatch):
   387	tests/test_event_dates_release_selection.py:39:    # One cancelled month (~77d gap) is a real calendar, not an error.
   388	tests/test_event_dates_release_selection.py:45:def test_collapsed_gap_fails_closed(monkeypatch):
   389	tests/test_event_dates_release_selection.py:46:    # A month whose ONLY entry is a late off-cycle date makes the next gap
   390	tests/test_event_dates_release_selection.py:47:    # collapse (<20d) — the sequence no longer looks like a release calendar.
   391	tests/test_event_dates_release_selection.py:49:    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
   392	tests/test_event_dates_release_selection.py:53:def test_three_missing_cycles_fail_closed(monkeypatch):
   393	tests/test_event_dates_release_selection.py:55:    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
   394	src/volpred/data/event_dates.py:1:"""Official macro-event release dates.
   395	src/volpred/data/event_dates.py:5:around the 13th") silently does two things at once: it counts non-event days as
   396	src/volpred/data/event_dates.py:10:release dates from a 13th-of-month proxy. Against the official calendar 7 of 13
   397	src/volpred/data/event_dates.py:12:Oct-2025 release was cancelled during the shutdown). Recomputing the CPI-day VIX
   398	src/volpred/data/event_dates.py:15:So: get the dates from the release calendar. `ALFRED` (FRED's real-time archive)
   399	src/volpred/data/event_dates.py:16:publishes the actual news-release dates per statistical release, which is exactly
   400	src/volpred/data/event_dates.py:20:    from volpred.data.event_dates import cpi_release_dates
   401	src/volpred/data/event_dates.py:21:    dates = cpi_release_dates("2024-01-01", "2026-12-31")   # DatetimeIndex
   402	src/volpred/data/event_dates.py:39:# FRED release ids for the macro releases we run event studies on.
   403	src/volpred/data/event_dates.py:40:# https://fred.stlouisfed.org/releases
   404	src/volpred/data/event_dates.py:44:    "FOMC": 101,       # H.4.1 is not the FOMC; FOMC statements are not a FRED release
   405	src/volpred/data/event_dates.py:51:def _api_key() -> str:
   406	src/volpred/data/event_dates.py:64:        "FRED_API_KEY not found. Event dates must come from the official release "
   407	src/volpred/data/event_dates.py:69:def _fetch(release_id: int, start: str, end: str) -> list[str]:
   408	src/volpred/data/event_dates.py:71:        "https://api.stlouisfed.org/fred/release/dates",
   409	src/volpred/data/event_dates.py:73:            "release_id": release_id,
   410	src/volpred/data/event_dates.py:78:            # Without this, ALFRED only returns releases that already carry data, so
   411	src/volpred/data/event_dates.py:81:            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
   412	src/volpred/data/event_dates.py:83:            "include_release_dates_with_no_data": "true",
   413	src/volpred/data/event_dates.py:90:    return [d["date"] for d in r.json()["release_dates"]]
   414	src/volpred/data/event_dates.py:93:def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
   415	src/volpred/data/event_dates.py:94:    """Official news-release dates for `event` within [start, end].
   416	src/volpred/data/event_dates.py:96:    Monthly releases can carry off-cycle entries (annual seasonal-factor and
   417	src/volpred/data/event_dates.py:97:    benchmark revisions are filed against the same release id, LATER in the
   418	src/volpred/data/event_dates.py:98:    month than the regular report). We therefore keep the EARLIEST entry in
   419	src/volpred/data/event_dates.py:99:    each month — 2026-07-19 k528 Codex review proved the previous `max()` rule
   420	src/volpred/data/event_dates.py:102:    Fail-closed on ambiguity: the selected sequence must look like a monthly
   421	src/volpred/data/event_dates.py:103:    release calendar (consecutive gaps 13–110 days; shutdown catch-ups compress for real,
   422	src/volpred/data/event_dates.py:104:    e.g. 2013-10-22 -> 2013-11-08 = 17d, and cancelled months stretch,
   423	src/volpred/data/event_dates.py:136:        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
   424	src/volpred/data/event_dates.py:138:    monthly = s.groupby([dates.year, dates.month]).min()
   425	src/volpred/data/event_dates.py:139:    selected = pd.DatetimeIndex(sorted(monthly.values))
   426	src/volpred/data/event_dates.py:140:    # Lower bound 13d catches mispicked entries (collapse patterns run <=12d)
   427	src/volpred/data/event_dates.py:141:    # while passing real shutdown catch-ups (2013-10-22 -> 2013-11-08 = 17d).
   428	src/volpred/data/event_dates.py:142:    # Upper bound 110d allows cancelled months (76d real) but trips on 3+ gaps.
   429	src/volpred/data/event_dates.py:144:    bad = gaps[(gaps < 13) | (gaps > 110)]
   430	src/volpred/data/event_dates.py:151:            f"{event} release calendar failed monthly-cadence validation "
   431	src/volpred/data/event_dates.py:152:            f"(gaps outside 13-110 days): {offenders}. Off-cycle entries or "
   432	src/volpred/data/event_dates.py:153:            f"missing months need manual disambiguation — refusing to return "
   433	src/volpred/data/event_dates.py:159:def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   434	src/volpred/data/event_dates.py:160:    return release_dates("CPI_US", start, end, **kw)
   435	src/volpred/data/event_dates.py:163:def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   436	src/volpred/data/event_dates.py:164:    return release_dates("NFP_US", start, end, **kw)
   437	experiments/k528/k528_nfp_event_study.py:4:Extends K513 (FOMC/NFP/CPI event study) with deeper NFP-specific analysis.
   438	experiments/k528/k528_nfp_event_study.py:6:K513 finding: NFP vol ratio = 1.09x (NS, p=0.195). This study digs deeper:
   439	experiments/k528/k528_nfp_event_study.py:10:  - Seasonal decomposition (which months matter?)
   440	experiments/k528/k528_nfp_event_study.py:16:  - NFP dates: OFFICIAL BLS release calendar via ALFRED (FRED release id 50)
   441	experiments/k528/k528_nfp_event_study.py:17:  - NFP actual values: FRED PAYEMS (monthly, for surprise calculation)
   442	experiments/k528/k528_nfp_event_study.py:21:The original run dated every NFP to the first Friday of the month. That proxy is
   443	experiments/k528/k528_nfp_event_study.py:23:moves the release to the second Friday whenever the reference week falls late
   444	experiments/k528/k528_nfp_event_study.py:25:dates land 3-4 days late). It also invents a release in 2025-10 that never
   445	experiments/k528/k528_nfp_event_study.py:26:happened, and it forces every event onto a Friday when 16 of the 254 official
   446	experiments/k528/k528_nfp_event_study.py:27:releases are not on a Friday at all.
   447	experiments/k528/k528_nfp_event_study.py:31:the dates now come from the official release calendar and the run FAILS CLOSED
   448	experiments/k528/k528_nfp_event_study.py:39:  - Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?"
   449	experiments/k528/k528_nfp_event_study.py:42:  - K513: Our prior FOMC/NFP/CPI event study (2005-2025, 668 events)
   450	experiments/k528/k528_nfp_event_study.py:61:from volpred.data.event_dates import nfp_release_dates
   451	experiments/k528/k528_nfp_event_study.py:70:# here is a data-integrity failure, not a known hole -- see check_calendar_is_complete.
   452	experiments/k528/k528_nfp_event_study.py:72:# 2025-10: the federal government shutdown. ALFRED shows no release id 50 entry
   453	experiments/k528/k528_nfp_event_study.py:73:# between 2025-09-05 and 2025-11-20 (a 76-day gap against a ~30-day cadence);
   454	experiments/k528/k528_nfp_event_study.py:75:# cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py.
   455	experiments/k528/k528_nfp_event_study.py:76:# It is a real absence of an event, which is why the month is excluded rather
   456	experiments/k528/k528_nfp_event_study.py:77:# than back-filled -- the first-Friday proxy INVENTED an event here, and that
   457	experiments/k528/k528_nfp_event_study.py:79:KNOWN_MISSING_MONTHS: set[str] = {"2025-10"}
   458	experiments/k528/k528_nfp_event_study.py:82:def write_json_atomic(path: Path, payload) -> None:
   459	experiments/k528/k528_nfp_event_study.py:88:    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
   460	experiments/k528/k528_nfp_event_study.py:96:            os.fsync(f.fileno())
   461	experiments/k528/k528_nfp_event_study.py:97:        os.replace(tmp, path)
   462	experiments/k528/k528_nfp_event_study.py:107:# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
   463	experiments/k528/k528_nfp_event_study.py:109:def check_calendar_is_complete(dates, start, end):
   464	experiments/k528/k528_nfp_event_study.py:112:    "Did the call succeed?" is the wrong question. A monthly release calendar
   465	experiments/k528/k528_nfp_event_study.py:115:    without being empty are: a month appears twice (off-cycle revision picked
   466	experiments/k528/k528_nfp_event_study.py:116:    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
   467	experiments/k528/k528_nfp_event_study.py:119:    months = [pd.Timestamp(d).strftime("%Y-%m") for d in dates]
   468	experiments/k528/k528_nfp_event_study.py:121:    dupes = sorted({m for m in months if months.count(m) > 1})
   469	experiments/k528/k528_nfp_event_study.py:124:            f"official NFP calendar returned {len(dupes)} month(s) with more than one "
   470	experiments/k528/k528_nfp_event_study.py:125:            f"release date: {dupes}. The Employment Situation is published once per "
   471	experiments/k528/k528_nfp_event_study.py:126:            "month; a second same-month entry is an off-cycle revision and must not be "
   472	experiments/k528/k528_nfp_event_study.py:134:    # The endpoint months are partial by construction: a run ending 2026-03-27
   473	experiments/k528/k528_nfp_event_study.py:136:    interior = {m for m in expected if m not in {min(expected), max(expected)}}
   474	experiments/k528/k528_nfp_event_study.py:137:    missing = sorted(interior - set(months) - KNOWN_MISSING_MONTHS)
   475	experiments/k528/k528_nfp_event_study.py:140:            f"official NFP calendar is missing {len(missing)} month(s) inside the sample "
   476	experiments/k528/k528_nfp_event_study.py:142:            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
   477	experiments/k528/k528_nfp_event_study.py:143:            "reason (e.g. a cancelled release), never to make this check pass."
   478	experiments/k528/k528_nfp_event_study.py:145:    return {"n_months_expected": len(interior), "known_missing_months": sorted(KNOWN_MISSING_MONTHS)}
   479	experiments/k528/k528_nfp_event_study.py:148:def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   480	experiments/k528/k528_nfp_event_study.py:149:    """Official NFP (Employment Situation) release dates.
   481	experiments/k528/k528_nfp_event_study.py:151:    Deliberately has no except branch. If the release calendar cannot be
   482	experiments/k528/k528_nfp_event_study.py:156:    dates = nfp_release_dates(start, end)
   483	experiments/k528/k528_nfp_event_study.py:159:    completeness = check_calendar_is_complete(dates, start, end)
   484	experiments/k528/k528_nfp_event_study.py:202:# The proxy forced every event onto a Friday. The official calendar does not,
   485	experiments/k528/k528_nfp_event_study.py:203:# and that is load-bearing for the Friday-baseline test below.
   486	experiments/k528/k528_nfp_event_study.py:205:print(f"  Official releases: {len(nfp_calendar)} "
   487	experiments/k528/k528_nfp_event_study.py:206:      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
   488	experiments/k528/k528_nfp_event_study.py:209:# 08:30 ET, before the open, so a release on a closed day is traded at the next
   489	experiments/k528/k528_nfp_event_study.py:210:# open -- hence "next trading day", not "nearest". Every release must land on
   490	experiments/k528/k528_nfp_event_study.py:211:# exactly one session and no two releases may share one: both failures shrink
   491	experiments/k528/k528_nfp_event_study.py:213:release_to_session = {}
   492	experiments/k528/k528_nfp_event_study.py:218:        release_to_session[nfp_ts] = nfp_ts
   493	experiments/k528/k528_nfp_event_study.py:223:        release_to_session[nfp_ts] = candidates[0]
   494	experiments/k528/k528_nfp_event_study.py:227:# In-sample releases must map. Releases outside the price series (the calendar
   495	experiments/k528/k528_nfp_event_study.py:236:        f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
   496	experiments/k528/k528_nfp_event_study.py:242:for rel, sess in release_to_session.items():
   497	experiments/k528/k528_nfp_event_study.py:247:        f"two or more NFP releases mapped to the same trading session: {colliding}. "
   498	experiments/k528/k528_nfp_event_study.py:251:nfp_trading_dates = sorted(release_to_session.values())
   499	experiments/k528/k528_nfp_event_study.py:252:n_shifted = sum(1 for r, s in release_to_session.items() if r != s)
   500	experiments/k528/k528_nfp_event_study.py:265:    "n_official_releases": len(nfp_calendar),
   501	experiments/k528/k528_nfp_event_study.py:275:print(f"  Total official releases: {len(nfp_calendar)}")
   502	experiments/k528/k528_nfp_event_study.py:312:        "month": nfp_date.month,
   503	experiments/k528/k528_nfp_event_study.py:313:        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
   504	experiments/k528/k528_nfp_event_study.py:348:# Friday-only baseline. Under the proxy every event was a Friday by
   505	experiments/k528/k528_nfp_event_study.py:349:# construction, so "all NFP events vs non-NFP Fridays" was a clean
   506	experiments/k528/k528_nfp_event_study.py:351:# group is a weekday mixture and the control group is pure Friday, so any
   507	experiments/k528/k528_nfp_event_study.py:352:# Friday-vs-other-weekday volatility difference loads directly onto the
   508	experiments/k528/k528_nfp_event_study.py:360:print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   509	experiments/k528/k528_nfp_event_study.py:375:# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
   510	experiments/k528/k528_nfp_event_study.py:378:#   (i)  restrict the event group to Friday releases, or
   511	experiments/k528/k528_nfp_event_study.py:380:# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
   512	experiments/k528/k528_nfp_event_study.py:384:# (i) answers one clean question: on a Friday, does an NFP release raise
   513	experiments/k528/k528_nfp_event_study.py:385:# volatility? It costs the 11 non-Friday events, which are reported below as a
   514	experiments/k528/k528_nfp_event_study.py:395:# audit can show what the contaminated estimand was worth. Not a headline
   515	experiments/k528/k528_nfp_event_study.py:435:# --- Test G: Seasonal analysis (by month) ---
   516	experiments/k528/k528_nfp_event_study.py:436:monthly_stats = {}
   517	experiments/k528/k528_nfp_event_study.py:437:for month in range(1, 13):
   518	experiments/k528/k528_nfp_event_study.py:438:    month_data = df[df["month"] == month]["event_abs_return"]
   519	experiments/k528/k528_nfp_event_study.py:439:    if len(month_data) >= 5:
   520	experiments/k528/k528_nfp_event_study.py:440:        monthly_stats[str(month)] = {
   521	experiments/k528/k528_nfp_event_study.py:441:            "n": int(len(month_data)),
   522	experiments/k528/k528_nfp_event_study.py:442:            "mean_abs_return": float(month_data.mean()),
   523	experiments/k528/k528_nfp_event_study.py:443:            "vol_ratio": float(month_data.mean() / baseline_abs_return),
   524	experiments/k528/k528_nfp_event_study.py:444:            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
   525	experiments/k528/k528_nfp_event_study.py:445:            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
   526	experiments/k528/k528_nfp_event_study.py:479:print(f"\n--- B. Friday NFP vs Friday Non-NFP (weekday held fixed) ---")
   527	experiments/k528/k528_nfp_event_study.py:480:print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
   528	experiments/k528/k528_nfp_event_study.py:481:print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   529	experiments/k528/k528_nfp_event_study.py:486:print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
   530	experiments/k528/k528_nfp_event_study.py:488:print(f"  [diagnostic, NOT a headline] all-events vs Friday baseline: "
   531	experiments/k528/k528_nfp_event_study.py:518:print(f"\n--- G. Seasonal Pattern (by month) ---")
   532	experiments/k528/k528_nfp_event_study.py:520:month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
   533	experiments/k528/k528_nfp_event_study.py:522:for m in range(1, 13):
   534	experiments/k528/k528_nfp_event_study.py:523:    if str(m) in monthly_stats:
   535	experiments/k528/k528_nfp_event_study.py:524:        ms = monthly_stats[str(m)]
   536	experiments/k528/k528_nfp_event_study.py:526:        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")
   537	experiments/k528/k528_nfp_event_study.py:567:april_nfp = df[df["month"] == 4]
   538	experiments/k528/k528_nfp_event_study.py:572:if "4" in monthly_stats:
   539	experiments/k528/k528_nfp_event_study.py:573:    ms4 = monthly_stats["4"]
   540	experiments/k528/k528_nfp_event_study.py:597:    f"Welch mean-difference, Friday NFP vs Friday non-NFP (weekday held fixed): "
   541	experiments/k528/k528_nfp_event_study.py:640:print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
   542	experiments/k528/k528_nfp_event_study.py:652:def win_rate(sample, reference):
   543	experiments/k528/k528_nfp_event_study.py:696:def record(key, label, before, after, note=""):
   544	experiments/k528/k528_nfp_event_study.py:727:# --- 1.17x : NFP vs Friday-only baseline ---
   545	experiments/k528/k528_nfp_event_study.py:729:    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   546	experiments/k528/k528_nfp_event_study.py:747:        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   547	experiments/k528/k528_nfp_event_study.py:753:            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
   548	experiments/k528/k528_nfp_event_study.py:758:         "the proxy every NFP day was a Friday by construction, so this test "
   549	experiments/k528/k528_nfp_event_study.py:759:         "compared Fridays with Fridays; on the official calendar the event "
   550	experiments/k528/k528_nfp_event_study.py:761:         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
   551	experiments/k528/k528_nfp_event_study.py:859:def verdict_for(key):
   552	experiments/k528/k528_nfp_event_study.py:860:    """Flip test: significance change, sign change, or a >10% move in the headline."""
   553	experiments/k528/k528_nfp_event_study.py:892:    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
   554	experiments/k528/k528_nfp_event_study.py:894:    bf = item["before"].get(headline)
   555	experiments/k528/k528_nfp_event_study.py:895:    af = item["after"].get(headline)
   556	experiments/k528/k528_nfp_event_study.py:915:        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
   557	experiments/k528/k528_nfp_event_study.py:916:        "accessor": "volpred.data.event_dates.nfp_release_dates",
   558	experiments/k528/k528_nfp_event_study.py:918:        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
   559	experiments/k528/k528_nfp_event_study.py:946:            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
   560	experiments/k528/k528_nfp_event_study.py:949:                "releases that trade on a Friday; the 11 non-Friday events are "
   561	experiments/k528/k528_nfp_event_study.py:950:                "excluded rather than compared against a pure-Friday control group."
   562	experiments/k528/k528_nfp_event_study.py:964:            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
   563	experiments/k528/k528_nfp_event_study.py:965:            "status": "DIAGNOSTIC ONLY - do not quote",
   564	experiments/k528/k528_nfp_event_study.py:966:            "why_not_a_headline": (
   565	experiments/k528/k528_nfp_event_study.py:968:                "group against a pure-Friday control group, so the p-value absorbs "
   566	experiments/k528/k528_nfp_event_study.py:969:                "any Friday-vs-other-weekday volatility difference. Retained solely "
   567	experiments/k528/k528_nfp_event_study.py:1010:    "seasonal_analysis": monthly_stats,
   568	experiments/k528/k528_nfp_event_study.py:1047:        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
   569	experiments/k528/k528_nfp_event_study.py:1062:        "The superseded run summarised these as 'insignificant across all tests', "
   570	experiments/k528/k528_nfp_event_study.py:1067:        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
   571	experiments/k528/k528_nfp_event_study.py:1068:        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
   572	experiments/k528/k528_nfp_event_study.py:1084:    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
   573	experiments/k528/k528_nfp_event_study.py:1107:        "replacements": None,
   574	
   575	exec
   576	/bin/zsh -lc "nl -ba src/volpred/data/event_dates.py | sed -n '1,210p'
   577	nl -ba tests/test_event_dates_real_raw_response.py | sed -n '1,220p'
   578	nl -ba tests/test_event_dates_release_selection.py | sed -n '1,260p'
   579	nl -ba tests/test_nfp_official_release_dates.py | sed -n '1,300p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
   580	 succeeded in 0ms:
   581	     1	"""Official macro-event release dates.
   582	     2	
   583	     3	Event studies treat the event date as a constant. It is not — it is data, and it
   584	     4	needs a primary source like any other input. A calendar proxy ("CPI comes out
   585	     5	around the 13th") silently does two things at once: it counts non-event days as
   586	     6	event days, and it dumps real event days into the control group. Nothing throws,
   587	     7	nothing is NaN, the figures still render.
   588	     8	
   589	     9	That is not hypothetical. Until 2026-07-12 our CPI event studies hard-coded the
   590	    10	release dates from a 13th-of-month proxy. Against the official calendar 7 of 13
   591	    11	dates were wrong, one of them a day on which BLS published no CPI at all (the
   592	    12	Oct-2025 release was cancelled during the shutdown). Recomputing the CPI-day VIX
   593	    13	reaction on the real dates flipped the mean from +2.18% to -0.85%.
   594	    14	
   595	    15	So: get the dates from the release calendar. `ALFRED` (FRED's real-time archive)
   596	    16	publishes the actual news-release dates per statistical release, which is exactly
   597	    17	the ground truth an event study needs.
   598	    18	
   599	    19	Usage:
   600	    20	    from volpred.data.event_dates import cpi_release_dates
   601	    21	    dates = cpi_release_dates("2024-01-01", "2026-12-31")   # DatetimeIndex
   602	    22	
   603	    23	See docs/error_log.md 2026-07-12 for the incident this module exists to prevent.
   604	    24	"""
   605	    25	
   606	    26	from __future__ import annotations
   607	    27	
   608	    28	import json
   609	    29	import logging
   610	    30	import os
   611	    31	from datetime import timedelta
   612	    32	from pathlib import Path
   613	    33	
   614	    34	import pandas as pd
   615	    35	import requests
   616	    36	
   617	    37	logger = logging.getLogger(__name__)
   618	    38	
   619	    39	# FRED release ids for the macro releases we run event studies on.
   620	    40	# https://fred.stlouisfed.org/releases
   621	    41	RELEASE_IDS = {
   622	    42	    "CPI_US": 10,      # Consumer Price Index
   623	    43	    "NFP_US": 50,      # Employment Situation
   624	    44	    "FOMC": 101,       # H.4.1 is not the FOMC; FOMC statements are not a FRED release
   625	    45	}
   626	    46	
   627	    47	_CACHE_DIR = Path(__file__).resolve().parents[3] / "storage" / "data" / "event_dates_cache"
   628	    48	_CACHE_TTL = timedelta(days=7)
   629	    49	
   630	    50	
   631	    51	def _api_key() -> str:
   632	    52	    key = os.environ.get("FRED_API_KEY")
   633	    53	    if key:
   634	    54	        return key
   635	    55	    root = Path(__file__).resolve().parents[3]
   636	    56	    for cand in (".env.local", ".env"):
   637	    57	        p = root / cand
   638	    58	        if not p.exists():
   639	    59	            continue
   640	    60	        for line in p.read_text().splitlines():
   641	    61	            if line.startswith("FRED_API_KEY"):
   642	    62	                return line.split("=", 1)[1].strip().strip("\"'")
   643	    63	    raise RuntimeError(
   644	    64	        "FRED_API_KEY not found. Event dates must come from the official release "
   645	    65	        "calendar — do not fall back to a hard-coded list or a calendar proxy."
   646	    66	    )
   647	    67	
   648	    68	
   649	    69	def _fetch(release_id: int, start: str, end: str) -> list[str]:
   650	    70	    r = requests.get(
   651	    71	        "https://api.stlouisfed.org/fred/release/dates",
   652	    72	        params={
   653	    73	            "release_id": release_id,
   654	    74	            "api_key": _api_key(),
   655	    75	            "file_type": "json",
   656	    76	            "realtime_start": start,
   657	    77	            "realtime_end": end,
   658	    78	            # Without this, ALFRED only returns releases that already carry data, so
   659	    79	            # scheduled-but-not-yet-published dates (the ones an upcoming-event
   660	    80	            # populator actually needs) are missing. Verified 2026-07-12 that it does
   661	    81	            # NOT resurrect cancelled releases: the Oct-2025 CPI, scrapped during the
   662	    82	            # shutdown, stays absent either way.
   663	    83	            "include_release_dates_with_no_data": "true",
   664	    84	            "limit": 1000,
   665	    85	            "sort_order": "asc",
   666	    86	        },
   667	    87	        timeout=30,
   668	    88	    )
   669	    89	    r.raise_for_status()
   670	    90	    return [d["date"] for d in r.json()["release_dates"]]
   671	    91	
   672	    92	
   673	    93	def release_dates(event: str, start: str, end: str, *, use_cache: bool = True) -> pd.DatetimeIndex:
   674	    94	    """Official news-release dates for `event` within [start, end].
   675	    95	
   676	    96	    Monthly releases can carry off-cycle entries (annual seasonal-factor and
   677	    97	    benchmark revisions are filed against the same release id, LATER in the
   678	    98	    month than the regular report). We therefore keep the EARLIEST entry in
   679	    99	    each month — 2026-07-19 k528 Codex review proved the previous `max()` rule
   680	   100	    picked 6 off-cycle dates as NFP events and flipped a significance result.
   681	   101	
   682	   102	    Fail-closed on ambiguity: the selected sequence must look like a monthly
   683	   103	    release calendar (consecutive gaps 13–110 days; shutdown catch-ups compress for real,
   684	   104	    e.g. 2013-10-22 -> 2013-11-08 = 17d, and cancelled months stretch,
   685	   105	    e.g. 2025-09-05 -> 2025-11-20 = 76d). Any gap outside that band
   686	   106	    raises instead of returning a plausible-but-wrong calendar —
   687	   107	    silently-wrong event dates are worse than a failed run.
   688	   108	    """
   689	   109	    if event not in RELEASE_IDS:
   690	   110	        raise KeyError(f"unknown event {event!r}; known: {sorted(RELEASE_IDS)}")
   691	   111	
   692	   112	    cache = _CACHE_DIR / f"{event}_{start}_{end}.json"
   693	   113	    if use_cache and cache.exists():
   694	   114	        age = pd.Timestamp.now(tz="UTC").tz_localize(None) - pd.Timestamp(cache.stat().st_mtime, unit="s")
   695	   115	        if age < _CACHE_TTL:
   696	   116	            raw = json.loads(cache.read_text())
   697	   117	        else:
   698	   118	            raw = None
   699	   119	    else:
   700	   120	        raw = None
   701	   121	
   702	   122	    if raw is None:
   703	   123	        raw = _fetch(RELEASE_IDS[event], start, end)
   704	   124	        if use_cache:
   705	   125	            # use_cache=False must bypass the cache ENTIRELY — the old code
   706	   126	            # skipped only the read and still wrote, which leaked canonical
   707	   127	            # writes out of hermetic tests (CI repo-state guard, 2026-07-19).
   708	   128	            from volpred.canonical_write import guard_canonical_write
   709	   129	
   710	   130	            guard_canonical_write(cache)
   711	   131	            cache.parent.mkdir(parents=True, exist_ok=True)
   712	   132	            cache.write_text(json.dumps(raw) + "\n")
   713	   133	
   714	   134	    dates = pd.to_datetime(raw)
   715	   135	    if len(dates) == 0:
   716	   136	        raise RuntimeError(f"no {event} release dates returned for {start}..{end}")
   717	   137	    s = pd.Series(dates, index=dates)
   718	   138	    monthly = s.groupby([dates.year, dates.month]).min()
   719	   139	    selected = pd.DatetimeIndex(sorted(monthly.values))
   720	   140	    # Lower bound 13d catches mispicked entries (collapse patterns run <=12d)
   721	   141	    # while passing real shutdown catch-ups (2013-10-22 -> 2013-11-08 = 17d).
   722	   142	    # Upper bound 110d allows cancelled months (76d real) but trips on 3+ gaps.
   723	   143	    gaps = pd.Series(selected).diff().dropna().dt.days
   724	   144	    bad = gaps[(gaps < 13) | (gaps > 110)]
   725	   145	    if len(bad) > 0:
   726	   146	        offenders = [
   727	   147	            f"{selected[i - 1].date()} -> {selected[i].date()} ({int(g)}d)"
   728	   148	            for i, g in zip(bad.index, bad.values)
   729	   149	        ]
   730	   150	        raise RuntimeError(
   731	   151	            f"{event} release calendar failed monthly-cadence validation "
   732	   152	            f"(gaps outside 13-110 days): {offenders}. Off-cycle entries or "
   733	   153	            f"missing months need manual disambiguation — refusing to return "
   734	   154	            f"a plausible-but-wrong calendar."
   735	   155	        )
   736	   156	    return selected
   737	   157	
   738	   158	
   739	   159	def cpi_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   740	   160	    return release_dates("CPI_US", start, end, **kw)
   741	   161	
   742	   162	
   743	   163	def nfp_release_dates(start: str, end: str, **kw) -> pd.DatetimeIndex:
   744	   164	    return release_dates("NFP_US", start, end, **kw)
   745	     1	"""Regression test against the VERBATIM ALFRED raw response.
   746	     2	
   747	     3	Why this file exists, separately from test_event_dates_release_selection.py:
   748	     4	
   749	     5	The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
   750	     6	a *hand-built* fixture in which the same-month duplicate entries had already
   751	     7	been removed. So they exercised the selection rule against input that could
   752	     8	not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
   753	     9	dates and flipped a significance result with a fully green suite.
   754	    10	
   755	    11	The fix for a fixture that cannot express the bug is not a better assertion —
   756	    12	it is real input. This module pins `_fetch`'s actual bytes for release id 50
   757	    13	(Employment Situation, 2005-01-01..2026-07-19, 264 entries) and asserts the
   758	    14	six regular releases survive selection.
   759	    15	
   760	    16	Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
   761	    17	it — the duplicate pairs ARE the regression surface).
   762	    18	"""
   763	    19	from __future__ import annotations
   764	    20	
   765	    21	import json
   766	    22	from pathlib import Path
   767	    23	
   768	    24	import pytest
   769	    25	
   770	    26	from volpred.data import event_dates
   771	    27	
   772	    28	_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
   773	    29	
   774	    30	# The six months ALFRED returns twice for, with the regular Employment Situation
   775	    31	# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
   776	    32	# filed against the same release id LATER in the month). Verified against the
   777	    33	# live API on 2026-07-19; the right-hand column is exactly what the old max()
   778	    34	# rule picked and what k528's contaminated run treated as NFP event days.
   779	    35	OFF_CYCLE_PAIRS = {
   780	    36	    "2006-05": ("2006-05-05", "2006-05-08"),
   781	    37	    "2012-12": ("2012-12-07", "2012-12-12"),
   782	    38	    "2013-05": ("2013-05-03", "2013-05-06"),
   783	    39	    "2020-05": ("2020-05-08", "2020-05-11"),
   784	    40	    "2024-01": ("2024-01-05", "2024-01-10"),
   785	    41	    "2024-08": ("2024-08-02", "2024-08-21"),
   786	    42	}
   787	    43	
   788	    44	
   789	    45	@pytest.fixture(autouse=True)
   790	    46	def _sandbox_cache_dir(monkeypatch, tmp_path):
   791	    47	    # No test may touch the canonical storage/data cache dir (CI repo-state guard).
   792	    48	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
   793	    49	
   794	    50	
   795	    51	@pytest.fixture
   796	    52	def raw_response() -> list[str]:
   797	    53	    return json.loads(_FIXTURE.read_text())["release_dates"]
   798	    54	
   799	    55	
   800	    56	@pytest.fixture
   801	    57	def selected(monkeypatch, raw_response) -> list[str]:
   802	    58	    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw_response))
   803	    59	    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
   804	    60	    return [str(d.date()) for d in idx]
   805	    61	
   806	    62	
   807	    63	def test_fixture_still_carries_the_duplicate_months(raw_response):
   808	    64	    """Guard the guard: if someone 'cleans' the fixture, the suite goes quiet again."""
   809	    65	    by_month: dict[str, list[str]] = {}
   810	    66	    for d in raw_response:
   811	    67	        by_month.setdefault(d[:7], []).append(d)
   812	    68	    multi = {m: v for m, v in by_month.items() if len(v) > 1}
   813	    69	    assert set(multi) == set(OFF_CYCLE_PAIRS), (
   814	    70	        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
   815	    71	        f"got {sorted(multi)}"
   816	    72	    )
   817	    73	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
   818	    74	        assert sorted(multi[month]) == [regular, off_cycle]
   819	    75	
   820	    76	
   821	    77	def test_regular_release_wins_in_every_duplicate_month(selected):
   822	    78	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
   823	    79	        in_month = [d for d in selected if d.startswith(month)]
   824	    80	        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
   825	    81	        assert off_cycle not in selected, f"{off_cycle} is an off-cycle revision, not an NFP event"
   826	    82	
   827	    83	
   828	    84	def test_selection_is_one_per_month_and_complete(selected, raw_response):
   829	    85	    months_in = {d[:7] for d in raw_response}
   830	    86	    months_out = [d[:7] for d in selected]
   831	    87	    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
   832	    88	    assert set(months_out) == months_in, "selection dropped or invented a month"
   833	    89	    assert len(selected) == 258
   834	    90	
   835	    91	
   836	    92	def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
   837	    93	    """Mutation check: the OLD rule must fail this file, or it proves nothing.
   838	    94	
   839	    95	    Without this, a future refactor could silently restore max() and the two
   840	    96	    assertions above would be the only thing standing in the way — this pins
   841	    97	    WHY they matter.
   842	    98	    """
   843	    99	    by_month: dict[str, list[str]] = {}
   844	   100	    for d in raw_response:
   845	   101	        by_month.setdefault(d[:7], []).append(d)
   846	   102	    old_rule = {m: max(v) for m, v in by_month.items()}
   847	   103	    wrong = {m: old_rule[m] for m, (regular, _) in OFF_CYCLE_PAIRS.items() if old_rule[m] != regular}
   848	   104	    assert wrong == {m: off for m, (_, off) in OFF_CYCLE_PAIRS.items()}, (
   849	   105	        "the old max() rule must pick exactly the six off-cycle dates on this input"
   850	   106	    )
   851	     1	"""Regression tests for release_dates off-cycle selection + cadence gate.
   852	     2	
   853	     3	2026-07-19 k528 Codex review: the old per-month max() rule picked 6 off-cycle
   854	     4	FRED entries (seasonal-factor / benchmark revisions filed against the same
   855	     5	release id, later in the month) as NFP event dates, flipping a significance
   856	     6	result. The fix keeps each month's EARLIEST entry and fail-closes when the
   857	     7	resulting sequence does not look like a monthly release calendar.
   858	     8	"""
   859	     9	from __future__ import annotations
   860	    10	
   861	    11	import pytest
   862	    12	
   863	    13	from volpred.data import event_dates
   864	    14	
   865	    15	
   866	    16	@pytest.fixture(autouse=True)
   867	    17	def _sandbox_cache_dir(monkeypatch, tmp_path):
   868	    18	    # belt-and-suspenders with use_cache=False: no test may touch the
   869	    19	    # canonical storage/data cache dir (CI repo-state guard, 2026-07-19).
   870	    20	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
   871	    21	
   872	    22	
   873	    23	def _dates(monkeypatch, raw):
   874	    24	    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw))
   875	    25	    return event_dates.release_dates("NFP_US", "2024-01-01", "2024-12-31", use_cache=False)
   876	    26	
   877	    27	
   878	    28	def test_off_cycle_late_entry_loses_to_regular_release(monkeypatch):
   879	    29	    raw = [
   880	    30	        "2024-01-05",
   881	    31	        "2024-02-02", "2024-02-09",  # 02-09 = off-cycle revision entry, must lose
   882	    32	        "2024-03-08",
   883	    33	    ]
   884	    34	    got = [str(d.date()) for d in _dates(monkeypatch, raw)]
   885	    35	    assert got == ["2024-01-05", "2024-02-02", "2024-03-08"]
   886	    36	
   887	    37	
   888	    38	def test_shutdown_gap_within_band_passes(monkeypatch):
   889	    39	    # One cancelled month (~77d gap) is a real calendar, not an error.
   890	    40	    raw = ["2024-01-05", "2024-02-02", "2024-04-19", "2024-05-17"]
   891	    41	    got = [str(d.date()) for d in _dates(monkeypatch, raw)]
   892	    42	    assert got == ["2024-01-05", "2024-02-02", "2024-04-19", "2024-05-17"]
   893	    43	
   894	    44	
   895	    45	def test_collapsed_gap_fails_closed(monkeypatch):
   896	    46	    # A month whose ONLY entry is a late off-cycle date makes the next gap
   897	    47	    # collapse (<20d) — the sequence no longer looks like a release calendar.
   898	    48	    raw = ["2024-01-05", "2024-02-27", "2024-03-07"]
   899	    49	    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
   900	    50	        _dates(monkeypatch, raw)
   901	    51	
   902	    52	
   903	    53	def test_three_missing_cycles_fail_closed(monkeypatch):
   904	    54	    raw = ["2024-01-05", "2024-06-07"]
   905	    55	    with pytest.raises(RuntimeError, match="monthly-cadence validation"):
   906	    56	        _dates(monkeypatch, raw)
   907	     1	"""Pin the NFP event dates that a first-Friday proxy gets wrong.
   908	     2	
   909	     3	`experiments/event_article_nfp_2026_07_03_t1` used to derive its NFP release
   910	     4	dates from a "first Friday of the month" rule. Against the official BLS
   911	     5	Employment Situation calendar, 7 of its 13 historical events were on the wrong
   912	     6	day, and correcting them flipped the headline direction: the SPY up-day rate
   913	     7	went from 53.8% to 46.2% and both medians changed sign.
   914	     8	
   915	     9	The proxy never raised and never produced a NaN. It produced a complete,
   916	    10	plausible, wrong table. These tests exist so that failure mode cannot come
   917	    11	back silently. See experiments/k1442/related_event_date_audit.md.
   918	    12	
   919	    13	Network is mocked throughout: the point is to pin the calendar semantics, not
   920	    14	to re-verify FRED's uptime. The fixture dates below are the real values
   921	    15	returned by FRED release id 50 (Employment Situation), fetched 2026-07-19.
   922	    16	"""
   923	    17	
   924	    18	from __future__ import annotations
   925	    19	
   926	    20	import importlib.util
   927	    21	from datetime import date, timedelta
   928	    22	from pathlib import Path
   929	    23	
   930	    24	import pandas as pd
   931	    25	import pytest
   932	    26	
   933	    27	from volpred.data import event_dates
   934	    28	
   935	    29	REPO_ROOT = Path(__file__).resolve().parents[1]
   936	    30	EXPERIMENT_DIR = REPO_ROOT / "experiments" / "event_article_nfp_2026_07_03_t1"
   937	    31	EXPERIMENT_PY = EXPERIMENT_DIR / "event_article_nfp_2026_07_03_t1.py"
   938	    32	
   939	    33	# Official Employment Situation release dates, FRED release id 50.
   940	    34	OFFICIAL_2024_2026 = [
   941	    35	    "2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05", "2024-05-03",
   942	    36	    "2024-06-07", "2024-07-05", "2024-08-02", "2024-09-06", "2024-10-04",
   943	    37	    "2024-11-01", "2024-12-06",
   944	    38	    "2025-01-10", "2025-02-07", "2025-03-07", "2025-04-04", "2025-05-02",
   945	    39	    "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
   946	    40	    # No October 2025 release: the shutdown cancelled it and pushed the
   947	    41	    # September report to 2025-11-20.
   948	    42	    "2025-11-20", "2025-12-16",
   949	    43	    "2026-01-09", "2026-02-11", "2026-03-06", "2026-04-03", "2026-05-08",
   950	    44	    "2026-06-05", "2026-07-02",
   951	    45	]
   952	    46	
   953	    47	# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
   954	    48	# `None` means the proxy invented an event that does not exist.
   955	    49	PROXY_MISMATCHES = [
   956	    50	    ("2025-07-04", "2025-07-03"),  # proxy landed on the closed July 4 holiday
   957	    51	    ("2025-10-03", None),          # phantom: no Employment Situation in Oct 2025
   958	    52	    ("2025-11-07", "2025-11-20"),  # shutdown backlog
   959	    53	    ("2025-12-05", "2025-12-16"),
   960	    54	    ("2026-01-02", "2026-01-09"),
   961	    55	    ("2026-02-06", "2026-02-11"),
   962	    56	    ("2026-05-01", "2026-05-08"),
   963	    57	]
   964	    58	
   965	    59	# The 6 the proxy happened to get right. Pinned so a "fix" that shifts every
   966	    60	# date is caught too -- the proxy is not wrong everywhere, it is wrong at the
   967	    61	# holiday and shutdown boundaries.
   968	    62	PROXY_CORRECT = [
   969	    63	    "2025-06-06", "2025-08-01", "2025-09-05",
   970	    64	    "2026-03-06", "2026-04-03", "2026-06-05",
   971	    65	]
   972	    66	
   973	    67	# What the experiment must use: trailing 13 official releases before 2026-07-02.
   974	    68	EXPECTED_TRAILING_13 = [
   975	    69	    "2025-05-02", "2025-06-06", "2025-07-03", "2025-08-01", "2025-09-05",
   976	    70	    "2025-11-20", "2025-12-16", "2026-01-09", "2026-02-11", "2026-03-06",
   977	    71	    "2026-04-03", "2026-05-08", "2026-06-05",
   978	    72	]
   979	    73	
   980	    74	
   981	    75	def _first_friday(year: int, month: int) -> date:
   982	    76	    """The proxy this module exists to keep out of the codebase."""
   983	    77	    d = date(year, month, 1)
   984	    78	    return d + timedelta(days=(4 - d.weekday()) % 7)
   985	    79	
   986	    80	
   987	    81	@pytest.fixture(autouse=True)
   988	    82	def isolate_event_date_cache(monkeypatch, tmp_path):
   989	    83	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
   990	    84	
   991	    85	
   992	    86	@pytest.fixture
   993	    87	def official(monkeypatch):
   994	    88	    monkeypatch.setattr(
   995	    89	        event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
   996	    90	    )
   997	    91	    return event_dates.nfp_release_dates("2024-01-01", "2026-07-02", use_cache=False)
   998	    92	
   999	    93	
  1000	    94	@pytest.fixture(scope="module")
  1001	    95	def experiment():
  1002	    96	    spec = importlib.util.spec_from_file_location(
  1003	    97	        "nfp_t1_experiment", EXPERIMENT_PY
  1004	    98	    )
  1005	    99	    module = importlib.util.module_from_spec(spec)
  1006	   100	    spec.loader.exec_module(module)
  1007	   101	    return module
  1008	   102	
  1009	   103	
  1010	   104	class TestProxyMismatches:
  1011	   105	    @pytest.mark.parametrize("proxy_date,official_date", PROXY_MISMATCHES)
  1012	   106	    def test_proxy_date_is_not_an_official_release(
  1013	   107	        self, official, proxy_date, official_date
  1014	   108	    ):
  1015	   109	        assert pd.Timestamp(proxy_date) not in official, (
  1016	   110	            f"{proxy_date} came from the first-Friday proxy and is not an "
  1017	   111	            "Employment Situation release date"
  1018	   112	        )
  1019	   113	        if official_date is not None:
  1020	   114	            assert pd.Timestamp(official_date) in official
  1021	   115	
  1022	   116	    @pytest.mark.parametrize("proxy_date,official_date", PROXY_MISMATCHES)
  1023	   117	    def test_mismatch_really_is_what_the_proxy_would_have_produced(
  1024	   118	        self, proxy_date, official_date
  1025	   119	    ):
  1026	   120	        """Guard the fixture itself: each 'proxy' date must be a first Friday.
  1027	   121	
  1028	   122	        Without this, a typo in PROXY_MISMATCHES would make the suite pass by
  1029	   123	        testing a date the proxy never generated.
  1030	   124	        """
  1031	   125	        d = pd.Timestamp(proxy_date)
  1032	   126	        assert _first_friday(d.year, d.month) == d.date()
  1033	   127	
  1034	   128	    def test_october_2025_release_does_not_exist(self, official):
  1035	   129	        """The proxy's worst failure: a full event window scored on a non-event.
  1036	   130	
  1037	   131	        No Employment Situation was published in October 2025. A monthly
  1038	   132	        heuristic cannot represent this, which is why the calendar has to be
  1039	   133	        data rather than a rule.
  1040	   134	        """
  1041	   135	        assert not [d for d in official if (d.year, d.month) == (2025, 10)]
  1042	   136	
  1043	   137	    @pytest.mark.parametrize("proxy_date", PROXY_CORRECT)
  1044	   138	    def test_proxy_dates_that_were_already_correct_stay_correct(
  1045	   139	        self, official, proxy_date
  1046	   140	    ):
  1047	   141	        assert pd.Timestamp(proxy_date) in official
  1048	   142	
  1049	   143	    def test_seven_of_thirteen_were_wrong(self, official):
  1050	   144	        """The headline number from the K1442 audit, recomputed not restated."""
  1051	   145	        proxy_dates = []
  1052	   146	        y, m = 2026, 6
  1053	   147	        while len(proxy_dates) < 13:
  1054	   148	            ff = _first_friday(y, m)
  1055	   149	            if ff < date(2026, 7, 3):
  1056	   150	                proxy_dates.append(ff)
  1057	   151	            m -= 1
  1058	   152	            if m == 0:
  1059	   153	                m, y = 12, y - 1
  1060	   154	
  1061	   155	        wrong = [d for d in proxy_dates if pd.Timestamp(d) not in official]
  1062	   156	        assert len(wrong) == 7
  1063	   157	        assert {str(d) for d in wrong} == {p for p, _ in PROXY_MISMATCHES}
  1064	   158	
  1065	   159	
  1066	   160	class TestExperimentUsesOfficialCalendar:
  1067	   161	    def test_release_date_is_july_2_not_july_3(self, experiment):
  1068	   162	        """July 4 fell on a Saturday, observed Friday July 3, so BLS moved up."""
  1069	   163	        assert experiment.RELEASE_DATE == "2026-07-02"
  1070	   164	        assert experiment.AS_OF == "2026-07-01"
  1071	   165	
  1072	   166	    def test_build_nfp_dates_returns_the_official_trailing_thirteen(
  1073	   167	        self, experiment, monkeypatch
  1074	   168	    ):
  1075	   169	        monkeypatch.setattr(
  1076	   170	            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
  1077	   171	        )
  1078	   172	        monkeypatch.setattr(
  1079	   173	            experiment,
  1080	   174	            "nfp_release_dates",
  1081	   175	            lambda start, end, **kw: event_dates.nfp_release_dates(
  1082	   176	                start, end, use_cache=False
  1083	   177	            ),
  1084	   178	        )
  1085	   179	
  1086	   180	        actual = [str(d.date()) for d in experiment.build_nfp_dates(13)]
  1087	   181	        assert actual == EXPECTED_TRAILING_13
  1088	   182	
  1089	   183	    def test_release_date_itself_is_excluded(self, experiment, monkeypatch):
  1090	   184	        """2026-07-02 is the event under study; it must not enter its own history."""
  1091	   185	        monkeypatch.setattr(
  1092	   186	            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
  1093	   187	        )
  1094	   188	        monkeypatch.setattr(
  1095	   189	            experiment,
  1096	   190	            "nfp_release_dates",
  1097	   191	            lambda start, end, **kw: event_dates.nfp_release_dates(
  1098	   192	                start, end, use_cache=False
  1099	   193	            ),
  1100	   194	        )
  1101	   195	
  1102	   196	        assert pd.Timestamp("2026-07-02") not in experiment.build_nfp_dates(13)
  1103	   197	
  1104	   198	    def test_fails_closed_when_calendar_is_short(self, experiment, monkeypatch):
  1105	   199	        """No proxy fallback: too few official dates must raise, not improvise."""
  1106	   200	        monkeypatch.setattr(
  1107	   201	            experiment,
  1108	   202	            "nfp_release_dates",
  1109	   203	            lambda *_a, **_kw: pd.DatetimeIndex(pd.to_datetime(["2026-06-05"])),
  1110	   204	        )
  1111	   205	
  1112	   206	        with pytest.raises(RuntimeError, match="only 1 releases"):
  1113	   207	            experiment.build_nfp_dates(13)
  1114	   208	
  1115	   209	    def test_fails_closed_when_calendar_is_unreachable(
  1116	   210	        self, experiment, monkeypatch
  1117	   211	    ):
  1118	   212	        def boom(*_a, **_kw):
  1119	   213	            raise RuntimeError("FRED_API_KEY not found")
  1120	   214	
  1121	   215	        monkeypatch.setattr(experiment, "nfp_release_dates", boom)
  1122	   216	
  1123	   217	        with pytest.raises(RuntimeError, match="FRED_API_KEY"):
  1124	   218	            experiment.build_nfp_dates(13)
  1125	   219	
  1126	   220	
  1127	   221	class TestNoLookahead:
  1128	   222	    """The download window itself must exclude the release day.
  1129	   223	
  1130	   224	    Asserting on constants is not enough: the constant can be right while the
  1131	   225	    call still passes a later `end`. These observe the actual yfinance calls.
  1132	   226	    """
  1133	   227	
  1134	   228	    # SPY, ^VIX, ^VIX9D -- every series must respect the cutoff, so the
  1135	   229	    # recorder has to survive past the first call. Stopping on call 1 would
  1136	   230	    # leave a mutated ^VIX or ^VIX9D `end` completely untested.
  1137	   231	    EXPECTED_TICKERS = ["SPY", "^VIX", "^VIX9D"]
  1138	   232	
  1139	   233	    def _capture_downloads(self, experiment, monkeypatch):
  1140	   234	        calls = []
  1141	   235	
  1142	   236	        def recorder(ticker, **kw):
  1143	   237	            calls.append({"ticker": ticker, **kw})
  1144	   238	            # Never abort inside the recorder itself. Stopping on call N would
  1145	   239	            # make a download added AFTER the ones we know about unreachable,
  1146	   240	            # so a 4th series could ship with an unchecked `end`. The tripwire
  1147	   241	            # defers the abort until main() first touches a frame, which is
  1148	   242	            # past the whole download block.
  1149	   243	            return _Tripwire()
  1150	   244	
  1151	   245	        monkeypatch.setattr(
  1152	   246	            event_dates, "_fetch", lambda *_a, **_kw: list(OFFICIAL_2024_2026)
  1153	   247	        )
  1154	   248	        monkeypatch.setattr(
  1155	   249	            experiment,
  1156	   250	            "nfp_release_dates",
  1157	   251	            lambda start, end, **kw: event_dates.nfp_release_dates(
  1158	   252	                start, end, use_cache=False
  1159	   253	            ),
  1160	   254	        )
  1161	   255	        monkeypatch.setattr(experiment.yf, "download", recorder)
  1162	   256	        try:
  1163	   257	            experiment.main()
  1164	   258	        except _StopEarly:
  1165	   259	            pass  # silent-ok: sentinel to stop main() once args are captured
  1166	   260	        return calls
  1167	   261	
  1168	   262	    def test_every_series_is_downloaded(self, experiment, monkeypatch):
  1169	   263	        """Pin the call count so the assertions below cannot pass vacuously."""
  1170	   264	        calls = self._capture_downloads(experiment, monkeypatch)
  1171	   265	        assert [c["ticker"] for c in calls] == self.EXPECTED_TICKERS
  1172	   266	
  1173	   267	    def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
  1174	   268	        calls = self._capture_downloads(experiment, monkeypatch)
  1175	   269	        assert len(calls) == len(self.EXPECTED_TICKERS)
  1176	   270	        for call in calls:
  1177	   271	            # yfinance `end` is exclusive, so end == release date means the
  1178	   272	            # last obtainable session is 2026-07-01.
  1179	   273	            assert call["end"] == "2026-07-02", (
  1180	   274	                f"{call['ticker']} download window ends at {call['end']!r}; "
  1181	   275	                "the 2026-07-02 release day must not be downloadable"
  1182	   276	            )
  1183	   277	
  1184	   278	    def test_download_window_starts_before_the_earliest_event(
  1185	   279	        self, experiment, monkeypatch
  1186	   280	    ):
  1187	   281	        calls = self._capture_downloads(experiment, monkeypatch)
  1188	   282	        # Guard against all([]) passing vacuously if nothing was captured.
  1189	   283	        assert len(calls) == len(self.EXPECTED_TICKERS)
  1190	   284	        # Needs a prior close to difference against 2025-05-02.
  1191	   285	        assert all(call["start"] < "2025-05-02" for call in calls)
  1192	   286	
  1193	   287	
  1194	   288	class _StopEarly(Exception):
  1195	   289	    """Abort main() once the download arguments have been observed."""
  1196	   290	
  1197	   291	
  1198	   292	class _Tripwire:
  1199	   293	    """Stand-in for a downloaded frame that raises when first consumed.
  1200	   294	
  1201	   295	    Lets every `yf.download` call run and be recorded before main() is
  1202	   296	    aborted, so the ticker-sequence assertion can see a download that does
  1203	   297	    not exist yet. main() touches `.columns` first when it flattens the
  1204	   298	    MultiIndex.
  1205	   299	    """
  1206	   300	
  1207	
  1208	exec
  1209	/bin/zsh -lc "sed -n '1,80p' tests/fixtures/fred_release_50_nfp_raw_20260719.json
  1210	sed -n '240,340p' tests/fixtures/fred_release_50_nfp_raw_20260719.json
  1211	wc -c -l tests/fixtures/fred_release_50_nfp_raw_20260719.json
  1212	jq '{keys:keys, n:(.release_dates|length), first:.release_dates[0], last:.release_dates[-1], duplicate_months:([.release_dates[]|.[0:7]]|group_by(.)|map(select(length>1)|{month:.[0],n:length}))}' tests/fixtures/fred_release_50_nfp_raw_20260719.json
  1213	nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '50,280p'
  1214	nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '280,460p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  1215	 succeeded in 0ms:
  1216	{
  1217	  "source": "FRED/ALFRED release/dates API, release_id=50 (Employment Situation)",
  1218	  "params": {
  1219	    "realtime_start": "2005-01-01",
  1220	    "realtime_end": "2026-07-19",
  1221	    "include_release_dates_with_no_data": true,
  1222	    "limit": 1000,
  1223	    "sort_order": "asc"
  1224	  },
  1225	  "captured_at": "2026-07-19",
  1226	  "note": "VERBATIM _fetch() output. Do NOT hand-edit or de-duplicate: the six same-month duplicate pairs ARE the regression surface (k528 Codex v2 BLOCKER 1).",
  1227	  "release_dates": [
  1228	    "2005-01-07",
  1229	    "2005-02-04",
  1230	    "2005-03-04",
  1231	    "2005-04-01",
  1232	    "2005-05-06",
  1233	    "2005-06-03",
  1234	    "2005-07-08",
  1235	    "2005-08-05",
  1236	    "2005-09-02",
  1237	    "2005-10-07",
  1238	    "2005-11-04",
  1239	    "2005-12-02",
  1240	    "2006-01-06",
  1241	    "2006-02-03",
  1242	    "2006-03-10",
  1243	    "2006-04-07",
  1244	    "2006-05-05",
  1245	    "2006-05-08",
  1246	    "2006-06-02",
  1247	    "2006-07-07",
  1248	    "2006-08-04",
  1249	    "2006-09-01",
  1250	    "2006-10-06",
  1251	    "2006-11-03",
  1252	    "2006-12-08",
  1253	    "2007-01-05",
  1254	    "2007-02-02",
  1255	    "2007-03-09",
  1256	    "2007-04-06",
  1257	    "2007-05-04",
  1258	    "2007-06-01",
  1259	    "2007-07-06",
  1260	    "2007-08-03",
  1261	    "2007-09-07",
  1262	    "2007-10-05",
  1263	    "2007-11-02",
  1264	    "2007-12-07",
  1265	    "2008-01-04",
  1266	    "2008-02-01",
  1267	    "2008-03-07",
  1268	    "2008-04-04",
  1269	    "2008-05-02",
  1270	    "2008-06-06",
  1271	    "2008-07-03",
  1272	    "2008-08-01",
  1273	    "2008-09-05",
  1274	    "2008-10-03",
  1275	    "2008-11-07",
  1276	    "2008-12-05",
  1277	    "2009-01-09",
  1278	    "2009-02-06",
  1279	    "2009-03-06",
  1280	    "2009-04-03",
  1281	    "2009-05-08",
  1282	    "2009-06-05",
  1283	    "2009-07-02",
  1284	    "2009-08-07",
  1285	    "2009-09-04",
  1286	    "2009-10-02",
  1287	    "2009-11-06",
  1288	    "2009-12-04",
  1289	    "2010-01-08",
  1290	    "2010-02-05",
  1291	    "2010-03-05",
  1292	    "2010-04-02",
  1293	    "2010-05-07",
  1294	    "2010-06-04",
  1295	    "2010-07-02",
  1296	    "2023-08-04",
  1297	    "2023-09-01",
  1298	    "2023-10-06",
  1299	    "2023-11-03",
  1300	    "2023-12-08",
  1301	    "2024-01-05",
  1302	    "2024-01-10",
  1303	    "2024-02-02",
  1304	    "2024-03-08",
  1305	    "2024-04-05",
  1306	    "2024-05-03",
  1307	    "2024-06-07",
  1308	    "2024-07-05",
  1309	    "2024-08-02",
  1310	    "2024-08-21",
  1311	    "2024-09-06",
  1312	    "2024-10-04",
  1313	    "2024-11-01",
  1314	    "2024-12-06",
  1315	    "2025-01-10",
  1316	    "2025-02-07",
  1317	    "2025-03-07",
  1318	    "2025-04-04",
  1319	    "2025-05-02",
  1320	    "2025-06-06",
  1321	    "2025-07-03",
  1322	    "2025-08-01",
  1323	    "2025-09-05",
  1324	    "2025-11-20",
  1325	    "2025-12-16",
  1326	    "2026-01-09",
  1327	    "2026-02-11",
  1328	    "2026-03-06",
  1329	    "2026-04-03",
  1330	    "2026-05-08",
  1331	    "2026-06-05",
  1332	    "2026-07-02"
  1333	  ]
  1334	}
  1335	     278    5236 tests/fixtures/fred_release_50_nfp_raw_20260719.json
  1336	{
  1337	  "keys": [
  1338	    "captured_at",
  1339	    "note",
  1340	    "params",
  1341	    "release_dates",
  1342	    "source"
  1343	  ],
  1344	  "n": 264,
  1345	  "first": "2005-01-07",
  1346	  "last": "2026-07-02",
  1347	  "duplicate_months": [
  1348	    {
  1349	      "month": "2006-05",
  1350	      "n": 2
  1351	    },
  1352	    {
  1353	      "month": "2012-12",
  1354	      "n": 2
  1355	    },
  1356	    {
  1357	      "month": "2013-05",
  1358	      "n": 2
  1359	    },
  1360	    {
  1361	      "month": "2020-05",
  1362	      "n": 2
  1363	    },
  1364	    {
  1365	      "month": "2024-01",
  1366	      "n": 2
  1367	    },
  1368	    {
  1369	      "month": "2024-08",
  1370	      "n": 2
  1371	    }
  1372	  ]
  1373	}
  1374	    50	import os
  1375	    51	import tempfile
  1376	    52	import warnings
  1377	    53	from datetime import datetime, timezone
  1378	    54	from pathlib import Path
  1379	    55	
  1380	    56	import numpy as np
  1381	    57	import pandas as pd
  1382	    58	import yfinance as yf
  1383	    59	from scipy import stats
  1384	    60	
  1385	    61	from volpred.data.event_dates import nfp_release_dates
  1386	    62	
  1387	    63	warnings.filterwarnings("ignore")
  1388	    64	
  1389	    65	SAMPLE_START = "2005-01-01"
  1390	    66	SAMPLE_END = "2026-03-27"
  1391	    67	
  1392	    68	# Months in [SAMPLE_START, SAMPLE_END] for which BLS published no Employment
  1393	    69	# Situation report at all. Anything absent from the calendar that is NOT listed
  1394	    70	# here is a data-integrity failure, not a known hole -- see check_calendar_is_complete.
  1395	    71	#
  1396	    72	# 2025-10: the federal government shutdown. ALFRED shows no release id 50 entry
  1397	    73	# between 2025-09-05 and 2025-11-20 (a 76-day gap against a ~30-day cadence);
  1398	    74	# the delayed September report came out on 11-20. This is the same shutdown that
  1399	    75	# cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py.
  1400	    76	# It is a real absence of an event, which is why the month is excluded rather
  1401	    77	# than back-filled -- the first-Friday proxy INVENTED an event here, and that
  1402	    78	# phantom event is one of the reasons this experiment was rerun.
  1403	    79	KNOWN_MISSING_MONTHS: set[str] = {"2025-10"}
  1404	    80	
  1405	    81	
  1406	    82	def write_json_atomic(path: Path, payload) -> None:
  1407	    83	    """Write `payload` to `path` atomically.
  1408	    84	
  1409	    85	    A truncate-then-write leaves a half-written results file on the disk if the
  1410	    86	    run dies mid-dump, and a half-written results file is worse than none: it
  1411	    87	    still parses far enough to look like data to the next reader. Write to a
  1412	    88	    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
  1413	    89	    """
  1414	    90	    path.parent.mkdir(parents=True, exist_ok=True)
  1415	    91	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
  1416	    92	    try:
  1417	    93	        with os.fdopen(fd, "w") as f:
  1418	    94	            json.dump(payload, f, indent=2, default=str)
  1419	    95	            f.flush()
  1420	    96	            os.fsync(f.fileno())
  1421	    97	        os.replace(tmp, path)
  1422	    98	    except BaseException:
  1423	    99	        try:
  1424	   100	            os.unlink(tmp)
  1425	   101	        except FileNotFoundError:
  1426	   102	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
  1427	   103	        raise
  1428	   104	
  1429	   105	
  1430	   106	# ============================================================
  1431	   107	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
  1432	   108	# ============================================================
  1433	   109	def check_calendar_is_complete(dates, start, end):
  1434	   110	    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
  1435	   111	
  1436	   112	    "Did the call succeed?" is the wrong question. A monthly release calendar
  1437	   113	    that silently lost 2019 still returns a non-empty list, still produces
  1438	   114	    event windows, still renders. The three ways this input can be wrong
  1439	   115	    without being empty are: a month appears twice (off-cycle revision picked
  1440	   116	    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
  1441	   117	    range is not covered at all. All three raise here.
  1442	   118	    """
  1443	   119	    months = [pd.Timestamp(d).strftime("%Y-%m") for d in dates]
  1444	   120	
  1445	   121	    dupes = sorted({m for m in months if months.count(m) > 1})
  1446	   122	    if dupes:
  1447	   123	        raise RuntimeError(
  1448	   124	            f"official NFP calendar returned {len(dupes)} month(s) with more than one "
  1449	   125	            f"release date: {dupes}. The Employment Situation is published once per "
  1450	   126	            "month; a second same-month entry is an off-cycle revision and must not be "
  1451	   127	            "treated as an event. Fix the accessor, do not de-duplicate here."
  1452	   128	        )
  1453	   129	
  1454	   130	    expected = {
  1455	   131	        p.strftime("%Y-%m")
  1456	   132	        for p in pd.period_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="M")
  1457	   133	    }
  1458	   134	    # The endpoint months are partial by construction: a run ending 2026-03-27
  1459	   135	    # legitimately has 2026-03, but a run ending 2026-03-02 may not yet.
  1460	   136	    interior = {m for m in expected if m not in {min(expected), max(expected)}}
  1461	   137	    missing = sorted(interior - set(months) - KNOWN_MISSING_MONTHS)
  1462	   138	    if missing:
  1463	   139	        raise RuntimeError(
  1464	   140	            f"official NFP calendar is missing {len(missing)} month(s) inside the sample "
  1465	   141	            f"window: {missing}. A partial calendar dumps real event days into the control "
  1466	   142	            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
  1467	   143	            "reason (e.g. a cancelled release), never to make this check pass."
  1468	   144	        )
  1469	   145	    return {"n_months_expected": len(interior), "known_missing_months": sorted(KNOWN_MISSING_MONTHS)}
  1470	   146	
  1471	   147	
  1472	   148	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
  1473	   149	    """Official NFP (Employment Situation) release dates.
  1474	   150	
  1475	   151	    Deliberately has no except branch. If the release calendar cannot be
  1476	   152	    reached, this run must die -- a proxy calendar produces plausible numbers
  1477	   153	    from non-events, which is worse than no numbers at all. See the CORRECTION
  1478	   154	    note in the module docstring.
  1479	   155	    """
  1480	   156	    dates = nfp_release_dates(start, end)
  1481	   157	    if len(dates) == 0:
  1482	   158	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
  1483	   159	    completeness = check_calendar_is_complete(dates, start, end)
  1484	   160	    return list(dates), completeness
  1485	   161	
  1486	   162	
  1487	   163	# ============================================================
  1488	   164	# 2. Download data
  1489	   165	# ============================================================
  1490	   166	print("=" * 60)
  1491	   167	print("K528: NFP Event Study on SPY Volatility")
  1492	   168	print("=" * 60)
  1493	   169	
  1494	   170	print("\n[1/6] Downloading SPY and VIX data...")
  1495	   171	spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
  1496	   172	vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)
  1497	   173	
  1498	   174	# Handle multi-level columns from yfinance
  1499	   175	if isinstance(spy.columns, pd.MultiIndex):
  1500	   176	    spy.columns = spy.columns.get_level_values(0)
  1501	   177	if isinstance(vix.columns, pd.MultiIndex):
  1502	   178	    vix.columns = vix.columns.get_level_values(0)
  1503	   179	
  1504	   180	# Calculate returns
  1505	   181	spy["Return"] = spy["Close"].pct_change()
  1506	   182	spy["AbsReturn"] = spy["Return"].abs()
  1507	   183	spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
  1508	   184	spy.dropna(subset=["Return"], inplace=True)
  1509	   185	
  1510	   186	# Merge VIX
  1511	   187	vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
  1512	   188	spy = spy.join(vix_close, how="left")
  1513	   189	spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays
  1514	   190	
  1515	   191	print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
  1516	   192	print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")
  1517	   193	
  1518	   194	# ============================================================
  1519	   195	# 3. Map NFP dates to trading days
  1520	   196	# ============================================================
  1521	   197	print("\n[2/6] Mapping NFP dates to trading days...")
  1522	   198	
  1523	   199	nfp_calendar, calendar_completeness = load_nfp_dates()
  1524	   200	trading_dates = spy.index
  1525	   201	
  1526	   202	# The proxy forced every event onto a Friday. The official calendar does not,
  1527	   203	# and that is load-bearing for the Friday-baseline test below.
  1528	   204	n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
  1529	   205	print(f"  Official releases: {len(nfp_calendar)} "
  1530	   206	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
  1531	   207	
  1532	   208	# Map each NFP date to the session that trades the news. The report drops at
  1533	   209	# 08:30 ET, before the open, so a release on a closed day is traded at the next
  1534	   210	# open -- hence "next trading day", not "nearest". Every release must land on
  1535	   211	# exactly one session and no two releases may share one: both failures shrink
  1536	   212	# the event set without shrinking any count that gets printed.
  1537	   213	release_to_session = {}
  1538	   214	unmapped = []
  1539	   215	for nfp_date in nfp_calendar:
  1540	   216	    nfp_ts = pd.Timestamp(nfp_date)
  1541	   217	    if nfp_ts in trading_dates:
  1542	   218	        release_to_session[nfp_ts] = nfp_ts
  1543	   219	        continue
  1544	   220	    mask = (trading_dates > nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
  1545	   221	    candidates = trading_dates[mask]
  1546	   222	    if len(candidates) > 0:
  1547	   223	        release_to_session[nfp_ts] = candidates[0]
  1548	   224	    else:
  1549	   225	        unmapped.append(nfp_ts.date().isoformat())
  1550	   226	
  1551	   227	# In-sample releases must map. Releases outside the price series (the calendar
  1552	   228	# window can overhang the SPY history on either end) are excluded by design,
  1553	   229	# not by failure, so they are separated before the assertion.
  1554	   230	in_sample_unmapped = [
  1555	   231	    d for d in unmapped
  1556	   232	    if trading_dates[0] <= pd.Timestamp(d) <= trading_dates[-1]
  1557	   233	]
  1558	   234	if in_sample_unmapped:
  1559	   235	    raise RuntimeError(
  1560	   236	        f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
  1561	   237	        f"trading session within 3 days: {in_sample_unmapped}. Silently skipping them would "
  1562	   238	        "drop real event days into the control group."
  1563	   239	    )
  1564	   240	
  1565	   241	collisions = {}
  1566	   242	for rel, sess in release_to_session.items():
  1567	   243	    collisions.setdefault(sess, []).append(rel.date().isoformat())
  1568	   244	colliding = {str(s.date()): sorted(v) for s, v in collisions.items() if len(v) > 1}
  1569	   245	if colliding:
  1570	   246	    raise RuntimeError(
  1571	   247	        f"two or more NFP releases mapped to the same trading session: {colliding}. "
  1572	   248	        "The de-duplication that used to hide this also silently reduced the event count."
  1573	   249	    )
  1574	   250	
  1575	   251	nfp_trading_dates = sorted(release_to_session.values())
  1576	   252	n_shifted = sum(1 for r, s in release_to_session.items() if r != s)
  1577	   253	
  1578	   254	# Window buffer: an event needs 5 sessions before and 5 after to have a window
  1579	   255	# at all. Excluding the edges is correct; doing it without saying so is not.
  1580	   256	window_excluded = [d for d in nfp_trading_dates
  1581	   257	                   if d < trading_dates[10] or d > trading_dates[-6]]
  1582	   258	valid_nfp = [d for d in nfp_trading_dates
  1583	   259	             if d >= trading_dates[10] and d <= trading_dates[-6]]
  1584	   260	
  1585	   261	if len(valid_nfp) + len(window_excluded) != len(nfp_trading_dates):
  1586	   262	    raise RuntimeError("event-window partition lost events; refusing to continue")
  1587	   263	
  1588	   264	mapping_audit = {
  1589	   265	    "n_official_releases": len(nfp_calendar),
  1590	   266	    "n_mapped_to_sessions": len(nfp_trading_dates),
  1591	   267	    "n_shifted_to_next_session": n_shifted,
  1592	   268	    "n_outside_price_sample": len(unmapped),
  1593	   269	    "outside_price_sample_dates": sorted(unmapped),
  1594	   270	    "n_excluded_for_window_buffer": len(window_excluded),
  1595	   271	    "window_excluded_dates": [str(d.date()) for d in window_excluded],
  1596	   272	    "n_valid_events": len(valid_nfp),
  1597	   273	}
  1598	   274	
  1599	   275	print(f"  Total official releases: {len(nfp_calendar)}")
  1600	   276	print(f"  Mapped to trading sessions: {len(nfp_trading_dates)} ({n_shifted} shifted to next open)")
  1601	   277	print(f"  Outside price sample: {len(unmapped)}")
  1602	   278	print(f"  Excluded for window buffer: {len(window_excluded)}")
  1603	   279	print(f"  Valid (with pre/post window): {len(valid_nfp)}")
  1604	   280	
  1605	   280	
  1606	   281	# ============================================================
  1607	   282	# 4. Calculate event windows
  1608	   283	# ============================================================
  1609	   284	print("\n[3/6] Calculating event window statistics...")
  1610	   285	
  1611	   286	results = []
  1612	   287	idx_list = list(trading_dates)
  1613	   288	
  1614	   289	for nfp_date in valid_nfp:
  1615	   290	    pos = idx_list.index(nfp_date)
  1616	   291	
  1617	   292	    # Pre-event: T-5 to T-1
  1618	   293	    pre_window = spy.iloc[pos-5:pos]
  1619	   294	    # Event day: T
  1620	   295	    event_day = spy.iloc[pos]
  1621	   296	    # Post-event: T+1 to T+5
  1622	   297	    post_window = spy.iloc[pos+1:pos+6]
  1623	   298	
  1624	   299	    # Unreachable given the window-buffer partition above. Kept as an assertion
  1625	   300	    # rather than a `continue`: if the partition ever stops holding, the run
  1626	   301	    # must stop, not quietly analyse a smaller sample than it reports.
  1627	   302	    if len(pre_window) < 5 or len(post_window) < 5:
  1628	   303	        raise RuntimeError(
  1629	   304	            f"event {nfp_date.date()} has an incomplete window "
  1630	   305	            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
  1631	   306	            "window-buffer filter -- the partition and the window logic disagree"
  1632	   307	        )
  1633	   308	
  1634	   309	    row = {
  1635	   310	        "date": nfp_date.strftime("%Y-%m-%d"),
  1636	   311	        "year": nfp_date.year,
  1637	   312	        "month": nfp_date.month,
  1638	   313	        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
  1639	   314	        "event_return": float(event_day["Return"]),
  1640	   315	        "event_abs_return": float(event_day["AbsReturn"]),
  1641	   316	        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
  1642	   317	        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
  1643	   318	        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
  1644	   319	        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
  1645	   320	        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
  1646	   321	        "vix_change_event": None,
  1647	   322	        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
  1648	   323	        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
  1649	   324	    }
  1650	   325	
  1651	   326	    if row["pre_vix"] is not None and row["event_vix"] is not None:
  1652	   327	        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
  1653	   328	
  1654	   329	    results.append(row)
  1655	   330	
  1656	   331	df = pd.DataFrame(results)
  1657	   332	print(f"  Events with complete data: {len(df)}")
  1658	   333	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
  1659	   334	
  1660	   335	# ============================================================
  1661	   336	# 5. Non-NFP baseline calculation
  1662	   337	# ============================================================
  1663	   338	print("\n[4/6] Computing non-NFP baseline...")
  1664	   339	
  1665	   340	# Exclude EVERY NFP session from the control group, not just the ones that
  1666	   341	# survived the event-window filter. An event dropped for lacking a pre-window
  1667	   342	# is still an NFP day; leaving it in the control group is the exact failure this
  1668	   343	# experiment exists to fix ("dump real event days into the control group"), just
  1669	   344	# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
  1670	   345	nfp_set = set(nfp_trading_dates)
  1671	   346	non_nfp_mask = ~spy.index.isin(nfp_set)
  1672	   347	non_nfp = spy[non_nfp_mask]
  1673	   348	n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
  1674	   349	if n_leaked:
  1675	   350	    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
  1676	   351	
  1677	   352	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
  1678	   353	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
  1679	   354	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
  1680	   355	
  1681	   356	# Friday-only baseline. Under the proxy every event was a Friday by
  1682	   357	# construction, so "all NFP events vs non-NFP Fridays" was a clean
  1683	   358	# weekday-held-fixed contrast. On the official calendar it is not: the event
  1684	   359	# group is a weekday mixture and the control group is pure Friday, so any
  1685	   360	# Friday-vs-other-weekday volatility difference loads directly onto the
  1686	   361	# estimate. The test below therefore holds weekday fixed on BOTH sides.
  1687	   362	friday_mask = non_nfp.index.weekday == 4
  1688	   363	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
  1689	   364	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
  1690	   365	
  1691	   366	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
  1692	   367	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
  1693	   368	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
  1694	   369	
  1695	   370	# ============================================================
  1696	   371	# 6. Statistical tests
  1697	   372	# ============================================================
  1698	   373	print("\n[5/6] Running statistical tests...")
  1699	   374	
  1700	   375	nfp_abs_returns = df["event_abs_return"].values
  1701	   376	non_nfp_abs_returns = non_nfp["AbsReturn"].values
  1702	   377	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
  1703	   378	
  1704	   379	# --- Test A: NFP vs all non-NFP days ---
  1705	   380	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
  1706	   381	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
  1707	   382	
  1708	   383	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
  1709	   384	#
  1710	   385	# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
  1711	   386	#   (i)  restrict the event group to Friday releases, or
  1712	   387	#   (ii) keep all events and use weekday-matched controls.
  1713	   388	# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
  1714	   389	# 253 -- cells that thin make (ii) a weighted average dominated by three
  1715	   390	# single-digit strata, with standard errors driven by the 1-observation
  1716	   391	# Wednesday cell. That is a noisier estimator of a harder-to-state quantity.
  1717	   392	# (i) answers one clean question: on a Friday, does an NFP release raise
  1718	   393	# volatility? It costs the 11 non-Friday events, which are reported below as a
  1719	   394	# separate descriptive line rather than dropped in silence.
  1720	   395	nfp_friday_mask = (df["weekday"] == 4).values
  1721	   396	nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
  1722	   397	nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
  1723	   398	
  1724	   399	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
  1725	   400	vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
  1726	   401	
  1727	   402	# Diagnostic ONLY -- the pre-correction specification, kept so the correction
  1728	   403	# audit can show what the contaminated estimand was worth. Not a headline
  1729	   404	# number and not eligible to be quoted: its p-value mixes in weekday
  1730	   405	# composition, which is exactly the defect being repaired.
  1731	   406	t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
  1732	   407	    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
  1733	   408	vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
  1734	   409	
  1735	   410	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
  1736	   411	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
  1737	   412	
  1738	   413	# --- Test D: Vol crush pattern (post vs pre) ---
  1739	   414	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
  1740	   415	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
  1741	   416	
  1742	   417	# --- Test E: VIX predictive regression ---
  1743	   418	vix_valid = df.dropna(subset=["pre_vix"])
  1744	   419	if len(vix_valid) > 10:
  1745	   420	    from numpy.polynomial.polynomial import polyfit
  1746	   421	    X_vix = vix_valid["pre_vix"].values
  1747	   422	    Y_abs = vix_valid["event_abs_return"].values
  1748	   423	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
  1749	   424	    # correlation and p-value
  1750	   425	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
  1751	   426	    # also spearman
  1752	   427	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
  1753	   428	else:
  1754	   429	    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6
  1755	   430	
  1756	   431	# --- Test F: Pre-event VIX change (buildup) ---
  1757	   432	# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
  1758	   433	vix_buildup = []
  1759	   434	for nfp_date in valid_nfp:
  1760	   435	    pos = idx_list.index(nfp_date)
  1761	   436	    pre5 = spy.iloc[pos-5]
  1762	   437	    pre1 = spy.iloc[pos-1]
  1763	   438	    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
  1764	   439	        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))
  1765	   440	
  1766	   441	t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
  1767	   442	
  1768	   443	# --- Test G: Seasonal analysis (by month) ---
  1769	   444	monthly_stats = {}
  1770	   445	for month in range(1, 13):
  1771	   446	    month_data = df[df["month"] == month]["event_abs_return"]
  1772	   447	    if len(month_data) >= 5:
  1773	   448	        monthly_stats[str(month)] = {
  1774	   449	            "n": int(len(month_data)),
  1775	   450	            "mean_abs_return": float(month_data.mean()),
  1776	   451	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
  1777	   452	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
  1778	   453	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
  1779	   454	        }
  1780	   455	
  1781	   456	# --- Test H: Regime analysis (high VIX vs low VIX) ---
  1782	   457	vix_median = df["pre_vix"].median()
  1783	   458	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
  1784	   459	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
  1785	   460	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
  1786	
  1787	exec
  1788	/bin/zsh -lc "jq 'keys' experiments/k528/k528_nfp_event_study_results.json
  1789	jq '{metadata, sample, baseline, tests, summary, correction_audit}' experiments/k528/k528_nfp_event_study_results.json | sed -n '1,520p'
  1790	jq 'keys' experiments/k528/k528_nfp_official_dates_results.json
  1791	jq '.' experiments/k528/k528_nfp_official_dates_results.json | sed -n '1,500p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  1792	 succeeded in 0ms:
  1793	[
  1794	  "april_nfp",
  1795	  "claim_scope_note",
  1796	  "conclusions",
  1797	  "data_source",
  1798	  "date",
  1799	  "directional_bias",
  1800	  "event_data",
  1801	  "event_date_source",
  1802	  "experiment_id",
  1803	  "intraday_range",
  1804	  "main_results",
  1805	  "practical_implication",
  1806	  "references",
  1807	  "regime_analysis",
  1808	  "sample",
  1809	  "seasonal_analysis",
  1810	  "statistical_tests",
  1811	  "time_trend",
  1812	  "title",
  1813	  "volume"
  1814	]
  1815	{
  1816	  "metadata": null,
  1817	  "sample": {
  1818	    "total_nfp_events": 253,
  1819	    "date_range": "2005-02-04 to 2026-03-06",
  1820	    "non_nfp_trading_days": 5087,
  1821	    "friday_baseline_days": 835,
  1822	    "nfp_days_on_friday": 237,
  1823	    "event_mapping_audit": {
  1824	      "n_official_releases": 254,
  1825	      "n_mapped_to_sessions": 254,
  1826	      "n_shifted_to_next_session": 6,
  1827	      "n_outside_price_sample": 0,
  1828	      "outside_price_sample_dates": [],
  1829	      "n_excluded_for_window_buffer": 1,
  1830	      "window_excluded_dates": [
  1831	        "2005-01-07"
  1832	      ],
  1833	      "n_valid_events": 253
  1834	    },
  1835	    "calendar_completeness": {
  1836	      "n_months_expected": 253,
  1837	      "known_missing_months": [
  1838	        "2025-10"
  1839	      ]
  1840	    }
  1841	  },
  1842	  "baseline": null,
  1843	  "tests": null,
  1844	  "summary": null,
  1845	  "correction_audit": null
  1846	}
  1847	[
  1848	  "after_source",
  1849	  "article_correction",
  1850	  "before_source",
  1851	  "calendar_diff",
  1852	  "event_date_source",
  1853	  "experiment_id",
  1854	  "generated_at",
  1855	  "items",
  1856	  "n_claims_audited",
  1857	  "n_claims_flipped",
  1858	  "title",
  1859	  "win_rate_definition"
  1860	]
  1861	{
  1862	  "experiment_id": "K528",
  1863	  "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
  1864	  "generated_at": "2026-07-19T08:16:52.824497+00:00",
  1865	  "before_source": "k528_nfp_event_study_results_PROXY_SUPERSEDED.json",
  1866	  "after_source": "k528_nfp_event_study_results.json",
  1867	  "event_date_source": {
  1868	    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
  1869	    "accessor": "volpred.data.event_dates.nfp_release_dates",
  1870	    "fallback": "none - the run raises if the calendar is unreachable",
  1871	    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
  1872	  },
  1873	  "calendar_diff": {
  1874	    "proxy_only_dates": [
  1875	      "2005-07-01",
  1876	      "2006-03-03",
  1877	      "2006-12-01",
  1878	      "2007-03-02",
  1879	      "2008-07-07",
  1880	      "2009-01-02",
  1881	      "2009-05-01",
  1882	      "2009-07-06",
  1883	      "2010-01-04",
  1884	      "2010-10-01",
  1885	      "2011-07-01",
  1886	      "2012-03-02",
  1887	      "2013-03-01",
  1888	      "2013-10-04",
  1889	      "2013-11-01",
  1890	      "2014-01-03",
  1891	      "2014-07-07",
  1892	      "2015-01-02",
  1893	      "2015-05-01",
  1894	      "2015-07-06",
  1895	      "2016-01-04",
  1896	      "2016-07-01",
  1897	      "2017-03-03",
  1898	      "2017-12-01",
  1899	      "2018-03-02",
  1900	      "2019-03-01",
  1901	      "2020-01-03",
  1902	      "2020-05-01",
  1903	      "2020-07-06",
  1904	      "2021-01-04",
  1905	      "2021-10-01",
  1906	      "2022-07-01",
  1907	      "2023-03-03",
  1908	      "2023-12-01",
  1909	      "2024-03-01",
  1910	      "2025-01-03",
  1911	      "2025-07-07",
  1912	      "2025-10-03",
  1913	      "2025-11-07",
  1914	      "2025-12-05",
  1915	      "2026-01-02",
  1916	      "2026-02-06"
  1917	    ],
  1918	    "official_only_dates": [
  1919	      "2005-07-08",
  1920	      "2006-03-10",
  1921	      "2006-12-08",
  1922	      "2007-03-09",
  1923	      "2008-07-03",
  1924	      "2009-01-09",
  1925	      "2009-05-08",
  1926	      "2009-07-02",
  1927	      "2010-01-08",
  1928	      "2010-10-08",
  1929	      "2011-07-08",
  1930	      "2012-03-09",
  1931	      "2013-03-08",
  1932	      "2013-10-22",
  1933	      "2013-11-08",
  1934	      "2014-01-10",
  1935	      "2014-07-03",
  1936	      "2015-01-09",
  1937	      "2015-05-08",
  1938	      "2015-07-02",
  1939	      "2016-01-08",
  1940	      "2016-07-08",
  1941	      "2017-03-10",
  1942	      "2017-12-08",
  1943	      "2018-03-09",
  1944	      "2019-03-08",
  1945	      "2020-01-10",
  1946	      "2020-05-08",
  1947	      "2020-07-02",
  1948	      "2021-01-08",
  1949	      "2021-10-08",
  1950	      "2022-07-08",
  1951	      "2023-03-10",
  1952	      "2023-12-08",
  1953	      "2024-03-08",
  1954	      "2025-01-10",
  1955	      "2025-07-03",
  1956	      "2025-11-20",
  1957	      "2025-12-16",
  1958	      "2026-01-09",
  1959	      "2026-02-11"
  1960	    ],
  1961	    "dates_in_common": 212,
  1962	    "n_proxy": 254,
  1963	    "n_official": 253,
  1964	    "nfp_days_on_friday_official": 237
  1965	  },
  1966	  "win_rate_definition": "share of the sample exceeding the MEDIAN of its comparison group; 0.5 under the null",
  1967	  "items": {
  1968	    "vol_ratio_vs_all": {
  1969	      "label": "NFP vs all non-NFP days (article: 1.10x)",
  1970	      "before": {
  1971	        "mean_ratio": 1.1035360772013734,
  1972	        "nfp_mean": 0.008420922409653335,
  1973	        "baseline_mean": 0.0076308537469923455,
  1974	        "p_value": 0.1283682008960355,
  1975	        "significant_5pct": false,
  1976	        "n": 254,
  1977	        "median_ratio": 1.189607971494038,
  1978	        "win_rate": 0.5551181102362205
  1979	      },
  1980	      "after": {
  1981	        "mean_ratio": 1.1079551223284374,
  1982	        "nfp_mean": 0.008453062192235669,
  1983	        "baseline_mean": 0.007629426519073289,
  1984	        "p_value": 0.1115348306661545,
  1985	        "significant_5pct": false,
  1986	        "n": 253,
  1987	        "median_ratio": 1.1924408913550162,
  1988	        "win_rate": 0.5612648221343873
  1989	      },
  1990	      "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
  1991	      "verdict": "NUMERIC_ADJUSTMENT",
  1992	      "verdict_reasons": []
  1993	    },
  1994	    "vol_ratio_vs_friday": {
  1995	      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
  1996	      "before": {
  1997	        "mean_ratio": 1.168212716801256,
  1998	        "p_value": 0.03354366521379227,
  1999	        "significant_5pct": true,
  2000	        "n": 254,
  2001	        "nfp_days_on_friday": 254,
  2002	        "median_ratio": 1.2091317875797052,
  2003	        "win_rate": 0.562992125984252
  2004	      },
  2005	      "after": {
  2006	        "mean_ratio": 1.1901328478556155,
  2007	        "p_value": 0.020198459584478665,
  2008	        "significant_5pct": true,
  2009	        "n": 237,
  2010	        "nfp_days_on_friday": 237,
  2011	        "median_ratio": 1.2225564362044339,
  2012	        "win_rate": 0.569620253164557,
  2013	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  2014	        "diagnostic_mixed_weekday": {
  2015	          "mean_ratio": 1.177889180968137,
  2016	          "p_value": 0.024879138655181043,
  2017	          "significant_5pct": true,
  2018	          "n": 253,
  2019	          "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
  2020	        }
  2021	      },
  2022	      "note": "Two things changed at once here, and they must not be conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: under the proxy every NFP day was a Friday by construction, so this test compared Fridays with Fridays; on the official calendar the event group is a weekday mixture, so the like-for-like test now restricts the event group to Friday releases. `diagnostic_mixed_weekday` holds the date-corrected value of the OLD estimand, which is the apples-to-apples comparison against the `before` column.",
  2023	      "verdict": "NUMERIC_ADJUSTMENT",
  2024	      "verdict_reasons": []
  2025	    },
  2026	    "regime_ratio": {
  2027	      "label": "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
  2028	      "before": {
  2029	        "mean_ratio": 2.1670599373202153,
  2030	        "high_mean": 0.011524027931522324,
  2031	        "low_mean": 0.005317816887784345,
  2032	        "n_high": 127,
  2033	        "n_low": 127,
  2034	        "p_value": 2.8361186837189765E-10,
  2035	        "significant_5pct": true,
  2036	        "median_ratio": 2.2653573776192792,
  2037	        "win_rate": 0.7165354330708661
  2038	      },
  2039	      "after": {
  2040	        "mean_ratio": 2.0272879955976624,
  2041	        "high_mean": 0.011276173536394039,
  2042	        "low_mean": 0.005562196175817499,
  2043	        "n_high": 128,
  2044	        "n_low": 125,
  2045	        "p_value": 4.552281833425917E-9,
  2046	        "significant_5pct": true,
  2047	        "median_ratio": 2.0732630504358394,
  2048	        "win_rate": 0.6953125
  2049	      },
  2050	      "note": "",
  2051	      "verdict": "NUMERIC_ADJUSTMENT",
  2052	      "verdict_reasons": []
  2053	    },
  2054	    "vix_correlation": {
  2055	      "label": "Pre-event VIX vs event-day |return| (article: r=0.45)",
  2056	      "before": {
  2057	        "pearson_r": 0.45116558631194703,
  2058	        "pearson_p": 3.854493703611817E-14,
  2059	        "spearman_rho": 0.3766062270606868,
  2060	        "spearman_p": 5.561878132730772E-10,
  2061	        "slope_pct_per_vix_pt": 0.04387491083793095,
  2062	        "n": 254,
  2063	        "significant_5pct": true
  2064	      },
  2065	      "after": {
  2066	        "pearson_r": 0.44043736398798927,
  2067	        "pearson_p": 1.9814384001854257E-13,
  2068	        "spearman_rho": 0.3455048873701663,
  2069	        "spearman_p": 1.6699985504624933E-8,
  2070	        "slope_pct_per_vix_pt": 0.042561778477078566,
  2071	        "n": 253,
  2072	        "significant_5pct": true
  2073	      },
  2074	      "note": "",
  2075	      "verdict": "NUMERIC_ADJUSTMENT",
  2076	      "verdict_reasons": []
  2077	    },
  2078	    "vix_median_threshold": {
  2079	      "label": "VIX median split (article: 16.71)",
  2080	      "before": {
  2081	        "threshold": 16.710000038146973,
  2082	        "n": 254,
  2083	        "places_20260701_vix_1659_in": "low"
  2084	      },
  2085	      "after": {
  2086	        "threshold": 16.690000534057617,
  2087	        "n": 253,
  2088	        "places_20260701_vix_1659_in": "low"
  2089	      },
  2090	      "note": "",
  2091	      "verdict": "NUMERIC_ADJUSTMENT",
  2092	      "verdict_reasons": []
  2093	    },
  2094	    "sample": {
  2095	      "label": "NFP event sample (article: 254 events)",
  2096	      "before": {
  2097	        "n": 254,
  2098	        "date_range": "2005-02-04 to 2026-03-06",
  2099	        "non_nfp_trading_days": 5086
  2100	      },
  2101	      "after": {
  2102	        "n": 253,
  2103	        "date_range": "2005-02-04 to 2026-03-06",
  2104	        "non_nfp_trading_days": 5087,
  2105	        "dates_in_common": 212,
  2106	        "proxy_only_dates": [
  2107	          "2005-07-01",
  2108	          "2006-03-03",
  2109	          "2006-12-01",
  2110	          "2007-03-02",
  2111	          "2008-07-07",
  2112	          "2009-01-02",
  2113	          "2009-05-01",
  2114	          "2009-07-06",
  2115	          "2010-01-04",
  2116	          "2010-10-01",
  2117	          "2011-07-01",
  2118	          "2012-03-02",
  2119	          "2013-03-01",
  2120	          "2013-10-04",
  2121	          "2013-11-01",
  2122	          "2014-01-03",
  2123	          "2014-07-07",
  2124	          "2015-01-02",
  2125	          "2015-05-01",
  2126	          "2015-07-06",
  2127	          "2016-01-04",
  2128	          "2016-07-01",
  2129	          "2017-03-03",
  2130	          "2017-12-01",
  2131	          "2018-03-02",
  2132	          "2019-03-01",
  2133	          "2020-01-03",
  2134	          "2020-05-01",
  2135	          "2020-07-06",
  2136	          "2021-01-04",
  2137	          "2021-10-01",
  2138	          "2022-07-01",
  2139	          "2023-03-03",
  2140	          "2023-12-01",
  2141	          "2024-03-01",
  2142	          "2025-01-03",
  2143	          "2025-07-07",
  2144	          "2025-10-03",
  2145	          "2025-11-07",
  2146	          "2025-12-05",
  2147	          "2026-01-02",
  2148	          "2026-02-06"
  2149	        ],
  2150	        "official_only_dates": [
  2151	          "2005-07-08",
  2152	          "2006-03-10",
  2153	          "2006-12-08",
  2154	          "2007-03-09",
  2155	          "2008-07-03",
  2156	          "2009-01-09",
  2157	          "2009-05-08",
  2158	          "2009-07-02",
  2159	          "2010-01-08",
  2160	          "2010-10-08",
  2161	          "2011-07-08",
  2162	          "2012-03-09",
  2163	          "2013-03-08",
  2164	          "2013-10-22",
  2165	          "2013-11-08",
  2166	          "2014-01-10",
  2167	          "2014-07-03",
  2168	          "2015-01-09",
  2169	          "2015-05-08",
  2170	          "2015-07-02",
  2171	          "2016-01-08",
  2172	          "2016-07-08",
  2173	          "2017-03-10",
  2174	          "2017-12-08",
  2175	          "2018-03-09",
  2176	          "2019-03-08",
  2177	          "2020-01-10",
  2178	          "2020-05-08",
  2179	          "2020-07-02",
  2180	          "2021-01-08",
  2181	          "2021-10-08",
  2182	          "2022-07-08",
  2183	          "2023-03-10",
  2184	          "2023-12-08",
  2185	          "2024-03-08",
  2186	          "2025-01-10",
  2187	          "2025-07-03",
  2188	          "2025-11-20",
  2189	          "2025-12-16",
  2190	          "2026-01-09",
  2191	          "2026-02-11"
  2192	        ]
  2193	      },
  2194	      "note": "Equal counts do not mean equal samples -- check dates_in_common.",
  2195	      "verdict": "NUMERIC_ADJUSTMENT",
  2196	      "verdict_reasons": []
  2197	    }
  2198	  },
  2199	  "n_claims_flipped": 0,
  2200	  "n_claims_audited": 6,
  2201	  "article_correction": {
  2202	    "article_id": "mile_35eef830",
  2203	    "status": "validated_not_applied",
  2204	    "n_replacements": 19,
  2205	    "all_matched_exactly_once": true,
  2206	    "supersedes": {
  2207	      "voided_list_size": 18,
  2208	      "voided_at": "2026-07-19",
  2209	      "reason": "the 18-item list was built against a rerun whose accessor picked off-cycle ALFRED entries for six months, which pushed the NFP-vs-Friday test across the 5% line. It would have retracted a finding that is in fact correct."
  2210	    },
  2211	    "directional_claims_changed": 0,
  2212	    "replacements": [
  2213	      {
  2214	        "from": "總共 254 次 NFP 公布日的資料算過一遍",
  2215	        "to": "總共 253 次 NFP 公布日的資料算過一遍",
  2216	        "hits": 1
  2217	      },
  2218	      {
  2219	        "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
  2220	        "to": "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
  2221	        "hits": 1
  2222	      },
  2223	      {
  2224	        "from": "換句話說，這 1.10 倍的差距",
  2225	        "to": "換句話說，這 1.11 倍的差距",
  2226	        "hits": 1
  2227	      },
  2228	      {
  2229	        "from": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  2230	        "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  2231	        "hits": 1
  2232	      },
  2233	      {
  2234	        "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
  2235	        "to": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
  2236	        "hits": 1
  2237	      },
  2238	      {
  2239	        "from": "那 254 次 NFP 日裡",
  2240	        "to": "那 253 次 NFP 日裡",
  2241	        "hits": 1
  2242	      },
  2243	      {
  2244	        "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
  2245	        "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
  2246	        "hits": 1
  2247	      },
  2248	      {
  2249	        "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
  2250	        "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
  2251	        "hits": 1
  2252	      },
  2253	      {
  2254	        "from": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
  2255	        "to": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
  2256	        "hits": 1
  2257	      },
  2258	      {
  2259	        "from": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
  2260	        "to": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
  2261	        "hits": 1
  2262	      },
  2263	      {
  2264	        "from": "貼在歷史分界線 16.71 的下緣",
  2265	        "to": "貼在歷史分界線 16.69 的下緣",
  2266	        "hits": 1
  2267	      },
  2268	      {
  2269	        "from": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
  2270	        "to": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
  2271	        "hits": 1
  2272	      },
  2273	      {
  2274	        "from": "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
  2275	        "to": "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
  2276	        "hits": 1
  2277	      },
  2278	      {
  2279	        "from": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。",
  2280	        "to": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準，對週五基準是 1.19 倍、達到顯著水準。",
  2281	        "hits": 1
  2282	      },
  2283	      {
  2284	        "from": "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
  2285	        "to": "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
  2286	        "hits": 1
  2287	      },
  2288	      {
  2289	        "from": "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
  2290	        "to": "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
  2291	        "hits": 1
  2292	      },
  2293	      {
  2294	        "from": "254 場歷史樣本加上 7/2 這場實測",
  2295	        "to": "253 場歷史樣本加上 7/2 這場實測",
  2296	        "hits": 1
  2297	      },
  2298	      {
  2299	        "from": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
  2300	        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。另有一項口徑調整：初版的 NFP 全部落在週五，週五基準比較是同星期別對同星期別；官方日曆下有 16 場不在週五，因此該比較改為只取在週五公布的 237 場，維持兩邊星期別一致。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
  2301	        "hits": 1
  2302	      },
  2303	      {
  2304	        "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
  2305	        "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
  2306	        "hits": 1
  2307	      }
  2308	    ],
  2309	    "apply_result": null,
  2310	    "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
  2311	  }
  2312	}
  2313	
  2314	codex
  2315	已抓到第一個值得警戒的結構問題：實驗層宣稱「同月多筆會 raise」，但共用 accessor 在進入該檢查前已先按月 `min()` 去重，因此 live 路徑根本看不到重複；而 13–110 天 cadence 也無法辨識「同月較早的 off-cycle 假日期」。我會用具體反例驗證它是否能靜默通過，再判斷是否升為 blocker。統計驗算則會從逐事件資料與控制組 moments 重新算，不只抄 JSON 欄位。
  2316	exec
  2317	/bin/zsh -lc "jq '.main_results, .statistical_tests, .data_source, .claim_scope_note, .conclusions' experiments/k528/k528_nfp_event_study_results.json
  2318	jq '.event_data | length' experiments/k528/k528_nfp_event_study_results.json
  2319	jq '.event_data[0], .event_data[-1]' experiments/k528/k528_nfp_event_study_results.json
  2320	jq '.main_results, .statistical_tests, .sample, .event_data|length' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
  2321	nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '460,660p'
  2322	nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '660,940p'
  2323	nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '940,1135p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  2324	 succeeded in 0ms:
  2325	{
  2326	  "nfp_avg_abs_return": 0.008453062192235669,
  2327	  "nfp_avg_abs_return_pct": "0.845%",
  2328	  "non_nfp_avg_abs_return": 0.007629426519073289,
  2329	  "non_nfp_avg_abs_return_pct": "0.763%",
  2330	  "friday_baseline_abs_return": 0.0071764494731905775,
  2331	  "vol_ratio_vs_all": 1.1079551223284374,
  2332	  "vol_ratio_vs_friday": 1.1901328478556155
  2333	}
  2334	{
  2335	  "A_nfp_vs_all": {
  2336	    "test": "Welch t-test",
  2337	    "t_stat": 1.596241850709586,
  2338	    "p_value": 0.1115348306661545,
  2339	    "significant_5pct": false
  2340	  },
  2341	  "B_nfp_vs_friday": {
  2342	    "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
  2343	    "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
  2344	    "n_event": 237,
  2345	    "n_control": 835,
  2346	    "vol_ratio": 1.1901328478556155,
  2347	    "t_stat": 2.332682989591967,
  2348	    "p_value": 0.020198459584478665,
  2349	    "significant_5pct": true,
  2350	    "excluded_non_friday_events": {
  2351	      "n": 16,
  2352	      "mean_abs_return": 0.0071515462261143095
  2353	    }
  2354	  },
  2355	  "B_diagnostic_mixed_weekday": {
  2356	    "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
  2357	    "status": "DIAGNOSTIC ONLY - do not quote",
  2358	    "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
  2359	    "vol_ratio": 1.177889180968137,
  2360	    "t_stat": 2.2515875177085047,
  2361	    "p_value": 0.024879138655181043,
  2362	    "significant_5pct": true
  2363	  },
  2364	  "C_wilcoxon": {
  2365	    "test": "Mann-Whitney U (one-sided)",
  2366	    "u_stat": 712704.0,
  2367	    "p_value": 0.001918721963396258,
  2368	    "significant_5pct": true
  2369	  },
  2370	  "D_vol_crush": {
  2371	    "test": "One-sample t-test (post-pre diff)",
  2372	    "pre_avg": 0.007787024581397933,
  2373	    "post_avg": 0.0076873544749868,
  2374	    "diff": -0.0000996701064111322,
  2375	    "t_stat": -0.31069924923269754,
  2376	    "p_value": 0.7562860985174406,
  2377	    "vol_crush_present": false
  2378	  },
  2379	  "E_vix_predictive": {
  2380	    "test": "Pearson + Spearman correlation",
  2381	    "pearson_r": 0.44043736398798927,
  2382	    "pearson_p": 1.9814384001854257E-13,
  2383	    "spearman_rho": 0.3455048873701663,
  2384	    "spearman_p": 1.6699985504624933E-8,
  2385	    "slope": 0.00042561778477078567,
  2386	    "interpretation": "1pt VIX → 0.0426% more |return|"
  2387	  },
  2388	  "F_vix_buildup": {
  2389	    "test": "One-sample t-test (T-5 to T-1 VIX change)",
  2390	    "mean_change": 0.08312253989721004,
  2391	    "t_stat": 0.44978438962865197,
  2392	    "p_value": 0.653252559944604,
  2393	    "anticipatory_buildup": false
  2394	  }
  2395	}
  2396	"yfinance (SPY, ^VIX), 2005-01 to 2026-03"
  2397	"Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6)."
  2398	[
  2399	  "Welch mean-difference, NFP vs all non-NFP days: 1.11x, p=0.1115 (does not reject at 5%)",
  2400	  "Welch mean-difference, Friday NFP vs Friday non-NFP (weekday held fixed): 1.19x, p=0.0202 (rejects at 5%; n=237 vs 835)",
  2401	  "Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: p=0.00192 (rejects at 5%)",
  2402	  "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, so a rank test can detect a location shift the Welch mean test cannot. Report both; do not summarise them as a single verdict.",
  2403	  "No significant vol crush pattern (p=0.7563)",
  2404	  "Pre-event VIX predicts event vol (r=0.440, p=0.0000)"
  2405	]
  2406	253
  2407	{
  2408	  "date": "2005-02-04",
  2409	  "year": 2005,
  2410	  "month": 2,
  2411	  "weekday": 4,
  2412	  "event_return": 0.010676158613085907,
  2413	  "event_abs_return": 0.010676158613085907,
  2414	  "pre_avg_abs_return": 0.0036382030234154207,
  2415	  "post_avg_abs_return": 0.004437752197660916,
  2416	  "pre_vix": 11.789999961853027,
  2417	  "event_vix": 11.210000038146973,
  2418	  "post_vix_1d": 11.729999542236328,
  2419	  "vix_change_event": -0.5799999237060547,
  2420	  "high_low_range": 0.012060192196264854,
  2421	  "volume_ratio": 0.9459350091597117
  2422	}
  2423	{
  2424	  "date": "2026-03-06",
  2425	  "year": 2026,
  2426	  "month": 3,
  2427	  "weekday": 4,
  2428	  "event_return": -0.01310712873041986,
  2429	  "event_abs_return": 0.01310712873041986,
  2430	  "pre_avg_abs_return": 0.005363130090510459,
  2431	  "post_avg_abs_return": 0.006493460638204107,
  2432	  "pre_vix": 23.75,
  2433	  "event_vix": 29.489999771118164,
  2434	  "post_vix_1d": 25.5,
  2435	  "vix_change_event": 5.739999771118164,
  2436	  "high_low_range": 0.00944402798986296,
  2437	  "volume_ratio": 1.0906826345022151
  2438	}
  2439	7
  2440	6
  2441	4
  2442	254
  2443	   460	            "n": int(len(month_data)),
  2444	   461	            "mean_abs_return": float(month_data.mean()),
  2445	   462	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
  2446	   463	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
  2447	   464	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
  2448	   465	        }
  2449	   466	
  2450	   467	# --- Test H: Regime analysis (high VIX vs low VIX) ---
  2451	   468	vix_median = df["pre_vix"].median()
  2452	   469	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
  2453	   470	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
  2454	   471	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
  2455	   472	
  2456	   473	# --- Test I: Time trend (has NFP impact changed over time?) ---
  2457	   474	# Split into halves
  2458	   475	midpoint = len(df) // 2
  2459	   476	first_half = df.iloc[:midpoint]["event_abs_return"]
  2460	   477	second_half = df.iloc[midpoint:]["event_abs_return"]
  2461	   478	t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
  2462	   479	
  2463	   480	# --- Test J: Event-day return direction ---
  2464	   481	pos_returns = (df["event_return"] > 0).sum()
  2465	   482	neg_returns = (df["event_return"] < 0).sum()
  2466	   483	# Binomial test: is there a directional bias?
  2467	   484	binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)
  2468	   485	
  2469	   486	print("\n" + "=" * 60)
  2470	   487	print("RESULTS")
  2471	   488	print("=" * 60)
  2472	   489	
  2473	   490	print(f"\n--- A. NFP vs All Non-NFP Days ---")
  2474	   491	print(f"  NFP day |return|:     {nfp_abs_returns.mean():.6f} ({nfp_abs_returns.mean()*100:.3f}%)")
  2475	   492	print(f"  Non-NFP |return|:     {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
  2476	   493	print(f"  Vol ratio:            {vol_ratio_all:.3f}x")
  2477	   494	print(f"  t-stat:               {t_stat_all:.3f}")
  2478	   495	print(f"  p-value:              {p_val_all:.4f}")
  2479	   496	print(f"  Significant (5%):     {'YES' if p_val_all < 0.05 else 'NO'}")
  2480	   497	
  2481	   498	print(f"\n--- B. Friday NFP vs Friday Non-NFP (weekday held fixed) ---")
  2482	   499	print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
  2483	   500	print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
  2484	   501	print(f"  Vol ratio (vs Fri):   {vol_ratio_fri:.3f}x")
  2485	   502	print(f"  t-stat:               {t_stat_fri:.3f}")
  2486	   503	print(f"  p-value:              {p_val_fri:.4f}")
  2487	   504	print(f"  Significant (5%):     {'YES' if p_val_fri < 0.05 else 'NO'}")
  2488	   505	print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
  2489	   506	      f"mean |ret|={nfp_nonfriday_abs.mean():.6f}" if len(nfp_nonfriday_abs) else "  [excluded] none")
  2490	   507	print(f"  [diagnostic, NOT a headline] all-events vs Friday baseline: "
  2491	   508	      f"{vol_ratio_fri_mixed:.4f}x, p={p_val_fri_mixed:.5f}")
  2492	   509	print(f"      ^ pre-correction estimand; p mixes in weekday composition")
  2493	   510	
  2494	   511	print(f"\n--- C. Wilcoxon Rank-Sum (non-parametric) ---")
  2495	   512	print(f"  U-stat:               {u_stat:.1f}")
  2496	   513	print(f"  p-value (one-sided):  {p_val_wilcox:.4f}")
  2497	   514	
  2498	   515	print(f"\n--- D. Vol Crush Pattern (Post vs Pre) ---")
  2499	   516	print(f"  Pre-event avg |ret|:  {df['pre_avg_abs_return'].mean():.6f}")
  2500	   517	print(f"  Post-event avg |ret|: {df['post_avg_abs_return'].mean():.6f}")
  2501	   518	print(f"  Difference:           {vol_crush.mean():.6f}")
  2502	   519	print(f"  t-stat:               {t_crush:.3f}")
  2503	   520	print(f"  p-value:              {p_crush:.4f}")
  2504	   521	print(f"  Vol crush present:    {'YES' if vol_crush.mean() < 0 and p_crush < 0.05 else 'NO'}")
  2505	   522	
  2506	   523	print(f"\n--- E. VIX Predictive Regression ---")
  2507	   524	if r_vix is not None:
  2508	   525	    print(f"  Pearson r:            {r_vix:.4f} (p={p_vix:.4f})")
  2509	   526	    print(f"  Spearman rho:         {rho_vix:.4f} (p={p_rho_vix:.4f})")
  2510	   527	    print(f"  Slope:                {slope:.8f}")
  2511	   528	    print(f"  Interpretation:       1pt VIX increase → {slope*100:.4f}% more |return|")
  2512	   529	
  2513	   530	print(f"\n--- F. VIX Buildup (T-5 to T-1) ---")
  2514	   531	if t_buildup is not None:
  2515	   532	    print(f"  Mean VIX change:      {np.mean(vix_buildup):.4f}")
  2516	   533	    print(f"  t-stat:               {t_buildup:.3f}")
  2517	   534	    print(f"  p-value:              {p_buildup:.4f}")
  2518	   535	    print(f"  Anticipatory buildup: {'YES' if np.mean(vix_buildup) > 0 and p_buildup < 0.05 else 'NO'}")
  2519	   536	
  2520	   537	print(f"\n--- G. Seasonal Pattern (by month) ---")
  2521	   538	print(f"  {'Month':<8} {'N':<5} {'Avg |Ret|':<12} {'Ratio':<8} {'t-stat':<8} {'p-val':<8}")
  2522	   539	month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
  2523	   540	               7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
  2524	   541	for m in range(1, 13):
  2525	   542	    if str(m) in monthly_stats:
  2526	   543	        ms = monthly_stats[str(m)]
  2527	   544	        sig = "*" if ms["p_val"] < 0.05 else ""
  2528	   545	        print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")
  2529	   546	
  2530	   547	print(f"\n--- H. VIX Regime Analysis ---")
  2531	   548	print(f"  VIX median split:     {vix_median:.1f}")
  2532	   549	print(f"  High VIX NFP |ret|:   {high_vix.mean():.6f} (n={len(high_vix)})")
  2533	   550	print(f"  Low VIX NFP |ret|:    {low_vix.mean():.6f} (n={len(low_vix)})")
  2534	   551	print(f"  t-stat:               {t_regime:.3f}")
  2535	   552	print(f"  p-value:              {p_regime:.4f}")
  2536	   553	
  2537	   554	print(f"\n--- I. Time Trend (First Half vs Second Half) ---")
  2538	   555	print(f"  First half |ret|:     {first_half.mean():.6f} (n={len(first_half)}, ~{df['date'].iloc[0][:4]}-{df['date'].iloc[midpoint-1][:4]})")
  2539	   556	print(f"  Second half |ret|:    {second_half.mean():.6f} (n={len(second_half)}, ~{df['date'].iloc[midpoint][:4]}-{df['date'].iloc[-1][:4]})")
  2540	   557	print(f"  t-stat:               {t_trend:.3f}")
  2541	   558	print(f"  p-value:              {p_trend:.4f}")
  2542	   559	
  2543	   560	print(f"\n--- J. Directional Bias ---")
  2544	   561	print(f"  Positive returns:     {pos_returns}/{len(df)} ({pos_returns/len(df)*100:.1f}%)")
  2545	   562	print(f"  Negative returns:     {neg_returns}/{len(df)} ({neg_returns/len(df)*100:.1f}%)")
  2546	   563	print(f"  Binomial p-value:     {binom_p:.4f}")
  2547	   564	
  2548	   565	# ============================================================
  2549	   566	# 7. High-low range analysis (intraday vol proxy)
  2550	   567	# ============================================================
  2551	   568	print(f"\n--- K. Intraday Range (High-Low / Close) ---")
  2552	   569	nfp_range = df["high_low_range"].mean()
  2553	   570	non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
  2554	   571	range_ratio = nfp_range / non_nfp_range
  2555	   572	print(f"  NFP day range:        {nfp_range:.6f} ({nfp_range*100:.3f}%)")
  2556	   573	print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
  2557	   574	print(f"  Range ratio:          {range_ratio:.3f}x")
  2558	   575	
  2559	   576	# Volume analysis
  2560	   577	print(f"\n--- L. Volume Analysis ---")
  2561	   578	vol_ratio_data = df["volume_ratio"].dropna()
  2562	   579	print(f"  NFP/avg volume ratio: {vol_ratio_data.mean():.3f}x")
  2563	   580	print(f"  NFP volume > avg:     {(vol_ratio_data > 1).sum()}/{len(vol_ratio_data)} ({(vol_ratio_data > 1).mean()*100:.1f}%)")
  2564	   581	
  2565	   582	# ============================================================
  2566	   583	# 8. April NFP specific (for upcoming 04/03 article)
  2567	   584	# ============================================================
  2568	   585	print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
  2569	   586	april_nfp = df[df["month"] == 4]
  2570	   587	print(f"  April NFP events:     {len(april_nfp)}")
  2571	   588	print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
  2572	   589	print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
  2573	   590	print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
  2574	   591	if "4" in monthly_stats:
  2575	   592	    ms4 = monthly_stats["4"]
  2576	   593	    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")
  2577	   594	
  2578	   595	# ============================================================
  2579	   596	# 9. Summary conclusion
  2580	   597	# ============================================================
  2581	   598	print(f"\n{'=' * 60}")
  2582	   599	print("SUMMARY CONCLUSION")
  2583	   600	print("=" * 60)
  2584	   601	
  2585	   602	sig_level = 0.05
  2586	   603	conclusions = []
  2587	   604	
  2588	   605	# Each conclusion names the test it came from. The previous run collapsed
  2589	   606	# several tests into "insignificant across all tests" while the one-sided
  2590	   607	# Mann-Whitney in the same artifact was significant at p<0.01 -- a summary that
  2591	   608	# contradicted its own numbers. A Welch test on |return| is a test of MEANS;
  2592	   609	# it not rejecting is not a finding that the distributions match, and it is
  2593	   610	# never evidence that the effect is zero.
  2594	   611	conclusions.append(
  2595	   612	    f"Welch mean-difference, NFP vs all non-NFP days: {vol_ratio_all:.2f}x, "
  2596	   613	    f"p={p_val_all:.4f} ({'rejects' if p_val_all < sig_level else 'does not reject'} at 5%)"
  2597	   614	)
  2598	   615	conclusions.append(
  2599	   616	    f"Welch mean-difference, Friday NFP vs Friday non-NFP (weekday held fixed): "
  2600	   617	    f"{vol_ratio_fri:.2f}x, p={p_val_fri:.4f} "
  2601	   618	    f"({'rejects' if p_val_fri < sig_level else 'does not reject'} at 5%; "
  2602	   619	    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)})"
  2603	   620	)
  2604	   621	conclusions.append(
  2605	   622	    f"Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: "
  2606	   623	    f"p={p_val_wilcox:.5f} ({'rejects' if p_val_wilcox < sig_level else 'does not reject'} at 5%)"
  2607	   624	)
  2608	   625	if (p_val_all >= sig_level) != (p_val_wilcox >= sig_level):
  2609	   626	    conclusions.append(
  2610	   627	        "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, "
  2611	   628	        "so a rank test can detect a location shift the Welch mean test cannot. "
  2612	   629	        "Report both; do not summarise them as a single verdict."
  2613	   630	    )
  2614	   631	
  2615	   632	if vol_crush.mean() < 0 and p_crush < sig_level:
  2616	   633	    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
  2617	   634	else:
  2618	   635	    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")
  2619	   636	
  2620	   637	if r_vix is not None and p_vix < sig_level:
  2621	   638	    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
  2622	   639	else:
  2623	   640	    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")
  2624	   641	
  2625	   642	for c in conclusions:
  2626	   643	    print(f"  • {c}")
  2627	   644	
  2628	   645	print(f"\n  Practical implication:")
  2629	   646	print(f"    → Entry VIX regime is the larger and more reliably measured effect "
  2630	   647	      f"({high_vix.mean()/low_vix.mean():.2f}x, p={p_regime:.4g})")
  2631	   648	print(f"    → The NFP-day effect is smaller; mean and rank tests do not agree on it, "
  2632	   649	      f"so it is not established either way")
  2633	   650	print(f"    → Non-significance of a mean test is not evidence of no effect")
  2634	   651	
  2635	   652	# ============================================================
  2636	   653	# 9b. Correction audit: every published number, before vs after
  2637	   654	# ============================================================
  2638	   655	# A mean can sit still while the median and the win rate move underneath it,
  2639	   656	# so no claim is judged on its mean alone. Each item carries mean / median /
  2640	   657	# win rate / n / significance, and the flip test looks at all of them.
  2641	   658	print(f"\n{'=' * 60}")
  2642	   659	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
  2643	   660	print("=" * 60)
  2644	   660	print("=" * 60)
  2645	   661	
  2646	   662	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
  2647	   663	if not PROXY_PATH.exists():
  2648	   664	    raise FileNotFoundError(
  2649	   665	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
  2650	   666	        "only record of what the published article claimed. Do not regenerate it."
  2651	   667	    )
  2652	   668	proxy = json.loads(PROXY_PATH.read_text())
  2653	   669	
  2654	   670	
  2655	   671	def win_rate(sample, reference):
  2656	   672	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
  2657	   673	    ref_med = float(np.median(reference))
  2658	   674	    return float(np.mean(np.asarray(sample) > ref_med))
  2659	   675	
  2660	   676	
  2661	   677	# The proxy run only ever reported means, and a mean can hold still while the
  2662	   678	# median and the win rate move underneath it. Rather than leave the before-side
  2663	   679	# of those two columns null -- which would make the comparison unable to detect
  2664	   680	# exactly the failure it is looking for -- rebuild the proxy-era distributions
  2665	   681	# from the ARCHIVED per-event data. The dates come out of the archive, so this
  2666	   682	# reconstructs history without reintroducing a proxy calendar generator.
  2667	   683	proxy_events = proxy["event_data"]
  2668	   684	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
  2669	   685	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
  2670	   686	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
  2671	   687	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
  2672	   688	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
  2673	   689	
  2674	   690	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
  2675	   691	# mapped to a Monday because the first Friday was a market holiday. So the
  2676	   692	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
  2677	   693	# rebuild the proxy side under the SAME estimand the corrected run uses
  2678	   694	# (Friday events only) rather than comparing a mixed `before` against a
  2679	   695	# restricted `after` and calling the difference a correction effect.
  2680	   696	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
  2681	   697	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
  2682	   698	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
  2683	   699	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
  2684	   700	
  2685	   701	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
  2686	   702	                       for e in proxy_events])
  2687	   703	_p_thr = proxy["regime_analysis"]["vix_median_split"]
  2688	   704	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
  2689	   705	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
  2690	   706	
  2691	   707	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
  2692	   708	# reconstruction is wrong and its medians cannot be trusted either.
  2693	   709	for _label, _rebuilt, _archived in (
  2694	   710	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
  2695	   711	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
  2696	   712	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
  2697	   713	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
  2698	   714	):
  2699	   715	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
  2700	   716	        raise AssertionError(
  2701	   717	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
  2702	   718	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
  2703	   719	            "from a reconstruction that cannot reproduce the archived means."
  2704	   720	        )
  2705	   721	print("  proxy-era distributions reconstructed from archive (means reproduce)")
  2706	   722	
  2707	   723	audit_items = {}
  2708	   724	
  2709	   725	
  2710	   726	def record(key, label, before, after, note=""):
  2711	   727	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
  2712	   728	
  2713	   729	
  2714	   730	# --- 1.10x : NFP vs all non-NFP days ---
  2715	   731	record(
  2716	   732	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
  2717	   733	    {
  2718	   734	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
  2719	   735	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
  2720	   736	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
  2721	   737	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
  2722	   738	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
  2723	   739	        "n": proxy["sample"]["total_nfp_events"],
  2724	   740	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
  2725	   741	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
  2726	   742	    },
  2727	   743	    {
  2728	   744	        "mean_ratio": vol_ratio_all,
  2729	   745	        "nfp_mean": float(nfp_abs_returns.mean()),
  2730	   746	        "baseline_mean": baseline_abs_return,
  2731	   747	        "p_value": float(p_val_all),
  2732	   748	        "significant_5pct": bool(p_val_all < 0.05),
  2733	   749	        "n": int(len(df)),
  2734	   750	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
  2735	   751	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
  2736	   752	    },
  2737	   753	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
  2738	   754	         "per-event data, not from the proxy run's own output (it only reported means).",
  2739	   755	)
  2740	   756	
  2741	   757	# --- 1.17x : NFP vs Friday-only baseline ---
  2742	   758	record(
  2743	   759	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
  2744	   760	    {
  2745	   761	        # Same estimand as the `after` column: Friday events only.
  2746	   762	        "mean_ratio": proxy_ratio_fri_restricted,
  2747	   763	        "p_value": float(_p_p_fri),
  2748	   764	        "significant_5pct": bool(_p_p_fri < 0.05),
  2749	   765	        "n": int(len(proxy_nfp_friday_abs)),
  2750	   766	        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
  2751	   767	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
  2752	   768	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
  2753	   769	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  2754	   770	        "as_published_mixed_weekday": {
  2755	   771	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
  2756	   772	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
  2757	   773	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
  2758	   774	            "n": proxy["sample"]["total_nfp_events"],
  2759	   775	            "note": (
  2760	   776	                "what the proxy run actually published: all 254 events (239 Friday, "
  2761	   777	                "15 Monday) against non-NFP Fridays. This is the number the article "
  2762	   778	                "quoted, so it is kept, but it is NOT the like-for-like comparison "
  2763	   779	                "against the corrected column."
  2764	   780	            ),
  2765	   781	        },
  2766	   782	    },
  2767	   783	    {
  2768	   784	        "mean_ratio": vol_ratio_fri,
  2769	   785	        "p_value": float(p_val_fri),
  2770	   786	        "significant_5pct": bool(p_val_fri < 0.05),
  2771	   787	        "n": int(len(nfp_friday_abs)),
  2772	   788	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
  2773	   789	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
  2774	   790	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
  2775	   791	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  2776	   792	        "diagnostic_mixed_weekday": {
  2777	   793	            "mean_ratio": vol_ratio_fri_mixed,
  2778	   794	            "p_value": float(p_val_fri_mixed),
  2779	   795	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
  2780	   796	            "n": int(len(df)),
  2781	   797	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
  2782	   798	        },
  2783	   799	    },
  2784	   800	    note="Two things changed at once here, and they must not be conflated. "
  2785	   801	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: under "
  2786	   802	         "the proxy every NFP day was a Friday by construction, so this test "
  2787	   803	         "compared Fridays with Fridays; on the official calendar the event "
  2788	   804	         "group is a weekday mixture, so the like-for-like test now restricts "
  2789	   805	         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
  2790	   806	         "the date-corrected value of the OLD estimand, which is the apples-to-"
  2791	   807	         "apples comparison against the `before` column.",
  2792	   808	)
  2793	   809	
  2794	   810	# --- 2.17x : high-VIX vs low-VIX regime ---
  2795	   811	proxy_reg = proxy["regime_analysis"]
  2796	   812	record(
  2797	   813	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
  2798	   814	    {
  2799	   815	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
  2800	   816	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
  2801	   817	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
  2802	   818	        "n_high": proxy_reg["n_high"],
  2803	   819	        "n_low": proxy_reg["n_low"],
  2804	   820	        "p_value": proxy_reg["p_value"],
  2805	   821	        "significant_5pct": proxy_reg["p_value"] < 0.05,
  2806	   822	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
  2807	   823	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
  2808	   824	    },
  2809	   825	    {
  2810	   826	        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
  2811	   827	        "high_mean": float(high_vix.mean()),
  2812	   828	        "low_mean": float(low_vix.mean()),
  2813	   829	        "n_high": int(len(high_vix)),
  2814	   830	        "n_low": int(len(low_vix)),
  2815	   831	        "p_value": float(p_regime),
  2816	   832	        "significant_5pct": bool(p_regime < 0.05),
  2817	   833	        "median_ratio": float(high_vix.median() / low_vix.median()),
  2818	   834	        "win_rate": win_rate(high_vix.values, low_vix.values),
  2819	   835	    },
  2820	   836	)
  2821	   837	
  2822	   838	# --- 0.45 : pre-event VIX correlation ---
  2823	   839	proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
  2824	   840	record(
  2825	   841	    "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
  2826	   842	    {
  2827	   843	        "pearson_r": proxy_e["pearson_r"],
  2828	   844	        "pearson_p": proxy_e["pearson_p"],
  2829	   845	        "spearman_rho": proxy_e["spearman_rho"],
  2830	   846	        "spearman_p": proxy_e["spearman_p"],
  2831	   847	        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
  2832	   848	        "n": proxy["sample"]["total_nfp_events"],
  2833	   849	        "significant_5pct": proxy_e["pearson_p"] < 0.05,
  2834	   850	    },
  2835	   851	    {
  2836	   852	        "pearson_r": float(r_vix),
  2837	   853	        "pearson_p": float(p_vix),
  2838	   854	        "spearman_rho": float(rho_vix),
  2839	   855	        "spearman_p": float(p_rho_vix),
  2840	   856	        "slope_pct_per_vix_pt": float(slope) * 100,
  2841	   857	        "n": int(len(vix_valid)),
  2842	   858	        "significant_5pct": bool(p_vix < 0.05),
  2843	   859	    },
  2844	   860	)
  2845	   861	
  2846	   862	# --- 16.71 : the VIX median that splits the regimes ---
  2847	   863	# The article uses this threshold to place a specific date (2026-07-01 VIX
  2848	   864	# 16.59) on the low-VIX side. If the threshold crosses 16.59 the article's
  2849	   865	# worked example inverts, so it is audited as a claim in its own right.
  2850	   866	proxy_thr = proxy_reg["vix_median_split"]
  2851	   867	record(
  2852	   868	    "vix_median_threshold", "VIX median split (article: 16.71)",
  2853	   869	    {
  2854	   870	        "threshold": proxy_thr,
  2855	   871	        "n": proxy["sample"]["total_nfp_events"],
  2856	   872	        "places_20260701_vix_1659_in": "low" if 16.59 < proxy_thr else "high",
  2857	   873	    },
  2858	   874	    {
  2859	   875	        "threshold": float(vix_median),
  2860	   876	        "n": int(df["pre_vix"].notna().sum()),
  2861	   877	        "places_20260701_vix_1659_in": "low" if 16.59 < float(vix_median) else "high",
  2862	   878	    },
  2863	   879	)
  2864	   880	
  2865	   881	# --- 254 : the sample itself ---
  2866	   882	proxy_dates = {r["date"] for r in proxy["event_data"]}
  2867	   883	new_dates = {r["date"] for r in results}
  2868	   884	record(
  2869	   885	    "sample", "NFP event sample (article: 254 events)",
  2870	   886	    {
  2871	   887	        "n": proxy["sample"]["total_nfp_events"],
  2872	   888	        "date_range": proxy["sample"]["date_range"],
  2873	   889	        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
  2874	   890	    },
  2875	   891	    {
  2876	   892	        "n": int(len(df)),
  2877	   893	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
  2878	   894	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
  2879	   895	        "dates_in_common": len(proxy_dates & new_dates),
  2880	   896	        "proxy_only_dates": sorted(proxy_dates - new_dates),
  2881	   897	        "official_only_dates": sorted(new_dates - proxy_dates),
  2882	   898	    },
  2883	   899	    note="Equal counts do not mean equal samples -- check dates_in_common.",
  2884	   900	)
  2885	   901	
  2886	   902	
  2887	   903	def verdict_for(key):
  2888	   904	    """Flip test: significance change, sign change, or a >10% move in the headline."""
  2889	   905	    b, a = audit_items[key]["before"], audit_items[key]["after"]
  2890	   906	    reasons = []
  2891	   907	    if b.get("significant_5pct") is not None and a.get("significant_5pct") is not None:
  2892	   908	        if bool(b["significant_5pct"]) != bool(a["significant_5pct"]):
  2893	   909	            reasons.append(
  2894	   910	                "significance flipped "
  2895	   911	                f"({'sig' if b['significant_5pct'] else 'NS'} -> "
  2896	   912	                f"{'sig' if a['significant_5pct'] else 'NS'})"
  2897	   913	            )
  2898	   914	    # The mean is not trusted on its own: the median and the win rate are
  2899	   915	    # checked independently, because the failure mode this audit exists to
  2900	   916	    # catch is a stable mean sitting on top of a moved distribution.
  2901	   917	    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
  2902	   918	        if field in b and field in a and b[field] and a[field]:
  2903	   919	            rel = abs(a[field] - b[field]) / abs(b[field])
  2904	   920	            if rel > 0.10:
  2905	   921	                reasons.append(f"{field} moved {rel * 100:.1f}%")
  2906	   922	    if b.get("win_rate") and a.get("win_rate"):
  2907	   923	        if abs(a["win_rate"] - b["win_rate"]) > 0.05:
  2908	   924	            reasons.append(
  2909	   925	                f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
  2910	   926	            )
  2911	   927	    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
  2912	   928	        reasons.append("the article's worked example changes regime")
  2913	   929	    return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons
  2914	   930	
  2915	   931	
  2916	   932	print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
  2917	   933	for key, item in audit_items.items():
  2918	   934	    v, reasons = verdict_for(key)
  2919	   935	    item["verdict"], item["verdict_reasons"] = v, reasons
  2920	   936	    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
  2921	   937	                     if f in item["before"]), None)
  2922	   938	    bf = item["before"].get(headline)
  2923	   939	    af = item["after"].get(headline)
  2924	   940	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
  2925	   940	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
  2926	   941	    print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
  2927	   942	    for r in reasons:
  2928	   943	        print(f"      - {r}")
  2929	   944	
  2930	   945	n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
  2931	   946	print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
  2932	   947	
  2933	   948	# ============================================================
  2934	   949	# 10. Save results
  2935	   950	# ============================================================
  2936	   951	print("\n[6/6] Saving results...")
  2937	   952	
  2938	   953	output = {
  2939	   954	    "experiment_id": "K528",
  2940	   955	    "title": "NFP Event Study on SPY Volatility",
  2941	   956	    "date": datetime.now(timezone.utc).isoformat(),
  2942	   957	    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
  2943	   958	    "event_date_source": {
  2944	   959	        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
  2945	   960	        "accessor": "volpred.data.event_dates.nfp_release_dates",
  2946	   961	        "fallback": "none - the run raises if the calendar is unreachable",
  2947	   962	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
  2948	   963	    },
  2949	   964	    "sample": {
  2950	   965	        "total_nfp_events": len(df),
  2951	   966	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
  2952	   967	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
  2953	   968	        "friday_baseline_days": int(friday_mask.sum()),
  2954	   969	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
  2955	   970	        "event_mapping_audit": mapping_audit,
  2956	   971	        "calendar_completeness": calendar_completeness,
  2957	   972	    },
  2958	   973	    "main_results": {
  2959	   974	        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
  2960	   975	        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
  2961	   976	        "non_nfp_avg_abs_return": baseline_abs_return,
  2962	   977	        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
  2963	   978	        "friday_baseline_abs_return": friday_baseline,
  2964	   979	        "vol_ratio_vs_all": vol_ratio_all,
  2965	   980	        "vol_ratio_vs_friday": vol_ratio_fri,
  2966	   981	    },
  2967	   982	    "statistical_tests": {
  2968	   983	        "A_nfp_vs_all": {
  2969	   984	            "test": "Welch t-test",
  2970	   985	            "t_stat": float(t_stat_all),
  2971	   986	            "p_value": float(p_val_all),
  2972	   987	            "significant_5pct": bool(p_val_all < 0.05),
  2973	   988	        },
  2974	   989	        "B_nfp_vs_friday": {
  2975	   990	            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
  2976	   991	            "estimand": (
  2977	   992	                "weekday held fixed on both sides. Event group restricted to NFP "
  2978	   993	                "releases that trade on a Friday; the 11 non-Friday events are "
  2979	   994	                "excluded rather than compared against a pure-Friday control group."
  2980	   995	            ),
  2981	   996	            "n_event": int(len(nfp_friday_abs)),
  2982	   997	            "n_control": int(len(friday_non_nfp_abs)),
  2983	   998	            "vol_ratio": vol_ratio_fri,
  2984	   999	            "t_stat": float(t_stat_fri),
  2985	  1000	            "p_value": float(p_val_fri),
  2986	  1001	            "significant_5pct": bool(p_val_fri < 0.05),
  2987	  1002	            "excluded_non_friday_events": {
  2988	  1003	                "n": int(len(nfp_nonfriday_abs)),
  2989	  1004	                "mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
  2990	  1005	            },
  2991	  1006	        },
  2992	  1007	        "B_diagnostic_mixed_weekday": {
  2993	  1008	            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
  2994	  1009	            "status": "DIAGNOSTIC ONLY - do not quote",
  2995	  1010	            "why_not_a_headline": (
  2996	  1011	                "this is the pre-correction specification: a weekday-mixed event "
  2997	  1012	                "group against a pure-Friday control group, so the p-value absorbs "
  2998	  1013	                "any Friday-vs-other-weekday volatility difference. Retained solely "
  2999	  1014	                "so the correction audit can show what the contaminated estimand was "
  3000	  1015	                "worth (k528 Codex v2 finding 5)."
  3001	  1016	            ),
  3002	  1017	            "vol_ratio": vol_ratio_fri_mixed,
  3003	  1018	            "t_stat": float(t_stat_fri_mixed),
  3004	  1019	            "p_value": float(p_val_fri_mixed),
  3005	  1020	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
  3006	  1021	        },
  3007	  1022	        "C_wilcoxon": {
  3008	  1023	            "test": "Mann-Whitney U (one-sided)",
  3009	  1024	            "u_stat": float(u_stat),
  3010	  1025	            "p_value": float(p_val_wilcox),
  3011	  1026	            "significant_5pct": bool(p_val_wilcox < 0.05),
  3012	  1027	        },
  3013	  1028	        "D_vol_crush": {
  3014	  1029	            "test": "One-sample t-test (post-pre diff)",
  3015	  1030	            "pre_avg": float(df["pre_avg_abs_return"].mean()),
  3016	  1031	            "post_avg": float(df["post_avg_abs_return"].mean()),
  3017	  1032	            "diff": float(vol_crush.mean()),
  3018	  1033	            "t_stat": float(t_crush),
  3019	  1034	            "p_value": float(p_crush),
  3020	  1035	            "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
  3021	  1036	        },
  3022	  1037	        "E_vix_predictive": {
  3023	  1038	            "test": "Pearson + Spearman correlation",
  3024	  1039	            "pearson_r": float(r_vix) if r_vix else None,
  3025	  1040	            "pearson_p": float(p_vix) if p_vix else None,
  3026	  1041	            "spearman_rho": float(rho_vix) if rho_vix else None,
  3027	  1042	            "spearman_p": float(p_rho_vix) if p_rho_vix else None,
  3028	  1043	            "slope": float(slope) if slope else None,
  3029	  1044	            "interpretation": f"1pt VIX → {slope*100:.4f}% more |return|" if slope else None,
  3030	  1045	        },
  3031	  1046	        "F_vix_buildup": {
  3032	  1047	            "test": "One-sample t-test (T-5 to T-1 VIX change)",
  3033	  1048	            "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
  3034	  1049	            "t_stat": float(t_buildup) if t_buildup else None,
  3035	  1050	            "p_value": float(p_buildup) if p_buildup else None,
  3036	  1051	            "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
  3037	  1052	        },
  3038	  1053	    },
  3039	  1054	    "seasonal_analysis": monthly_stats,
  3040	  1055	    "regime_analysis": {
  3041	  1056	        "vix_median_split": float(vix_median),
  3042	  1057	        "high_vix_nfp_abs_return": float(high_vix.mean()),
  3043	  1058	        "low_vix_nfp_abs_return": float(low_vix.mean()),
  3044	  1059	        "n_high": int(len(high_vix)),
  3045	  1060	        "n_low": int(len(low_vix)),
  3046	  1061	        "t_stat": float(t_regime),
  3047	  1062	        "p_value": float(p_regime),
  3048	  1063	    },
  3049	  1064	    "time_trend": {
  3050	  1065	        "first_half_abs_return": float(first_half.mean()),
  3051	  1066	        "second_half_abs_return": float(second_half.mean()),
  3052	  1067	        "t_stat": float(t_trend),
  3053	  1068	        "p_value": float(p_trend),
  3054	  1069	    },
  3055	  1070	    "directional_bias": {
  3056	  1071	        "positive_count": int(pos_returns),
  3057	  1072	        "negative_count": int(neg_returns),
  3058	  1073	        "total": int(pos_returns + neg_returns),
  3059	  1074	        "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
  3060	  1075	        "binomial_p": binom_p,
  3061	  1076	    },
  3062	  1077	    "intraday_range": {
  3063	  1078	        "nfp_avg_range": float(nfp_range),
  3064	  1079	        "non_nfp_avg_range": float(non_nfp_range),
  3065	  1080	        "range_ratio": float(range_ratio),
  3066	  1081	    },
  3067	  1082	    "volume": {
  3068	  1083	        "avg_volume_ratio": float(vol_ratio_data.mean()),
  3069	  1084	        "pct_above_avg": float((vol_ratio_data > 1).mean()),
  3070	  1085	    },
  3071	  1086	    "april_nfp": {
  3072	  1087	        "n": int(len(april_nfp)),
  3073	  1088	        "avg_abs_return": float(april_nfp["event_abs_return"].mean()),
  3074	  1089	        "avg_signed_return": float(april_nfp["event_return"].mean()),
  3075	  1090	        "positive_rate": float((april_nfp["event_return"] > 0).mean()),
  3076	  1091	        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
  3077	  1092	    },
  3078	  1093	    "conclusions": conclusions,
  3079	  1094	    "practical_implication": (
  3080	  1095	        f"Entry VIX regime is the dominant and most reliably measured effect here: "
  3081	  1096	        f"{high_vix.mean()/low_vix.mean():.2f}x between high- and low-VIX NFP days "
  3082	  1097	        f"(p={p_regime:.4g}). The NFP-day effect itself is smaller and the tests do not "
  3083	  1098	        f"agree on it -- the Welch mean-difference test against all non-NFP days gives "
  3084	  1099	        f"{vol_ratio_all:.2f}x (p={p_val_all:.4f}) while the one-sided Mann-Whitney gives "
  3085	  1100	        f"p={p_val_wilcox:.5f}. Report both. A mean test that does not reject is not "
  3086	  1101	        "evidence that the effect is zero, and it does not license the claim that the "
  3087	  1102	        "event 'is not NFP itself'."
  3088	  1103	    ),
  3089	  1104	    "claim_scope_note": (
  3090	  1105	        "Every significance statement in this artifact is scoped to its own test. "
  3091	  1106	        "The superseded run summarised these as 'insignificant across all tests', "
  3092	  1107	        "which contradicted the one-sided Mann-Whitney result in the same file "
  3093	  1108	        "(k528 Codex v2 finding 6)."
  3094	  1109	    ),
  3095	  1110	    "references": [
  3096	  1111	        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
  3097	  1112	        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
  3098	  1113	        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
  3099	  1114	    ],
  3100	  1115	    "event_data": results,  # full per-event data
  3101	  1116	}
  3102	  1117	
  3103	  1118	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
  3104	  1119	write_json_atomic(out_path, output)
  3105	  1120	
  3106	  1121	print(f"  Saved to: {out_path}")
  3107	  1122	
  3108	  1123	# The correction audit is written separately: it is the artifact the article
  3109	  1124	# correction is justified against, and it must stay readable without wading
  3110	  1125	# through 254 events of per-day data.
  3111	  1126	audit_out = {
  3112	  1127	    "experiment_id": "K528",
  3113	  1128	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
  3114	  1129	    "generated_at": datetime.now(timezone.utc).isoformat(),
  3115	  1130	    "before_source": PROXY_PATH.name,
  3116	  1131	    "after_source": out_path.name,
  3117	  1132	    "event_date_source": output["event_date_source"],
  3118	  1133	    "calendar_diff": {
  3119	  1134	        "proxy_only_dates": sorted(proxy_dates - new_dates),
  3120	  1135	        "official_only_dates": sorted(new_dates - proxy_dates),
  3121	
  3122	exec
  3123	/bin/zsh -lc "nl -ba experiments/k528/k528_nfp_event_study.py | sed -n '670,820p'
  3124	jq '.items.vol_ratio_vs_friday' experiments/k528/k528_nfp_official_dates_results.json
  3125	jq '[.event_data[].weekday] | group_by(.) | map({weekday:.[0], n:length})' experiments/k528/k528_nfp_event_study_results.json
  3126	jq '[.event_data[].weekday] | group_by(.) | map({weekday:.[0], n:length})' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
  3127	jq '[.event_data[].date[0:10]] | map(strptime(\"%Y-%m-%d\")|mktime|strftime(\"%w\")) | group_by(.) | map({weekday:.[0], n:length})' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
  3128	jq '{superseded,do_not_cite,superseded_at,superseded_reason,keys:keys}' experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  3129	 succeeded in 0ms:
  3130	   670	
  3131	   671	def win_rate(sample, reference):
  3132	   672	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
  3133	   673	    ref_med = float(np.median(reference))
  3134	   674	    return float(np.mean(np.asarray(sample) > ref_med))
  3135	   675	
  3136	   676	
  3137	   677	# The proxy run only ever reported means, and a mean can hold still while the
  3138	   678	# median and the win rate move underneath it. Rather than leave the before-side
  3139	   679	# of those two columns null -- which would make the comparison unable to detect
  3140	   680	# exactly the failure it is looking for -- rebuild the proxy-era distributions
  3141	   681	# from the ARCHIVED per-event data. The dates come out of the archive, so this
  3142	   682	# reconstructs history without reintroducing a proxy calendar generator.
  3143	   683	proxy_events = proxy["event_data"]
  3144	   684	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
  3145	   685	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
  3146	   686	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
  3147	   687	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
  3148	   688	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
  3149	   689	
  3150	   690	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
  3151	   691	# mapped to a Monday because the first Friday was a market holiday. So the
  3152	   692	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
  3153	   693	# rebuild the proxy side under the SAME estimand the corrected run uses
  3154	   694	# (Friday events only) rather than comparing a mixed `before` against a
  3155	   695	# restricted `after` and calling the difference a correction effect.
  3156	   696	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
  3157	   697	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
  3158	   698	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
  3159	   699	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
  3160	   700	
  3161	   701	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
  3162	   702	                       for e in proxy_events])
  3163	   703	_p_thr = proxy["regime_analysis"]["vix_median_split"]
  3164	   704	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
  3165	   705	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
  3166	   706	
  3167	   707	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
  3168	   708	# reconstruction is wrong and its medians cannot be trusted either.
  3169	   709	for _label, _rebuilt, _archived in (
  3170	   710	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
  3171	   711	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
  3172	   712	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
  3173	   713	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
  3174	   714	):
  3175	   715	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
  3176	   716	        raise AssertionError(
  3177	   717	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
  3178	   718	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
  3179	   719	            "from a reconstruction that cannot reproduce the archived means."
  3180	   720	        )
  3181	   721	print("  proxy-era distributions reconstructed from archive (means reproduce)")
  3182	   722	
  3183	   723	audit_items = {}
  3184	   724	
  3185	   725	
  3186	   726	def record(key, label, before, after, note=""):
  3187	   727	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
  3188	   728	
  3189	   729	
  3190	   730	# --- 1.10x : NFP vs all non-NFP days ---
  3191	   731	record(
  3192	   732	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
  3193	   733	    {
  3194	   734	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
  3195	   735	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
  3196	   736	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
  3197	   737	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
  3198	   738	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
  3199	   739	        "n": proxy["sample"]["total_nfp_events"],
  3200	   740	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
  3201	   741	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
  3202	   742	    },
  3203	   743	    {
  3204	   744	        "mean_ratio": vol_ratio_all,
  3205	   745	        "nfp_mean": float(nfp_abs_returns.mean()),
  3206	   746	        "baseline_mean": baseline_abs_return,
  3207	   747	        "p_value": float(p_val_all),
  3208	   748	        "significant_5pct": bool(p_val_all < 0.05),
  3209	   749	        "n": int(len(df)),
  3210	   750	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
  3211	   751	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
  3212	   752	    },
  3213	   753	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
  3214	   754	         "per-event data, not from the proxy run's own output (it only reported means).",
  3215	   755	)
  3216	   756	
  3217	   757	# --- 1.17x : NFP vs Friday-only baseline ---
  3218	   758	record(
  3219	   759	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
  3220	   760	    {
  3221	   761	        # Same estimand as the `after` column: Friday events only.
  3222	   762	        "mean_ratio": proxy_ratio_fri_restricted,
  3223	   763	        "p_value": float(_p_p_fri),
  3224	   764	        "significant_5pct": bool(_p_p_fri < 0.05),
  3225	   765	        "n": int(len(proxy_nfp_friday_abs)),
  3226	   766	        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
  3227	   767	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
  3228	   768	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
  3229	   769	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  3230	   770	        "as_published_mixed_weekday": {
  3231	   771	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
  3232	   772	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
  3233	   773	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
  3234	   774	            "n": proxy["sample"]["total_nfp_events"],
  3235	   775	            "note": (
  3236	   776	                "what the proxy run actually published: all 254 events (239 Friday, "
  3237	   777	                "15 Monday) against non-NFP Fridays. This is the number the article "
  3238	   778	                "quoted, so it is kept, but it is NOT the like-for-like comparison "
  3239	   779	                "against the corrected column."
  3240	   780	            ),
  3241	   781	        },
  3242	   782	    },
  3243	   783	    {
  3244	   784	        "mean_ratio": vol_ratio_fri,
  3245	   785	        "p_value": float(p_val_fri),
  3246	   786	        "significant_5pct": bool(p_val_fri < 0.05),
  3247	   787	        "n": int(len(nfp_friday_abs)),
  3248	   788	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
  3249	   789	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
  3250	   790	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
  3251	   791	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  3252	   792	        "diagnostic_mixed_weekday": {
  3253	   793	            "mean_ratio": vol_ratio_fri_mixed,
  3254	   794	            "p_value": float(p_val_fri_mixed),
  3255	   795	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
  3256	   796	            "n": int(len(df)),
  3257	   797	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
  3258	   798	        },
  3259	   799	    },
  3260	   800	    note="Two things changed here and they are separated rather than conflated. "
  3261	   801	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
  3262	   802	         "event group is a weekday mixture while the control group is pure "
  3263	   803	         "Friday, so the test now restricts the event group to Friday releases. "
  3264	   804	         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
  3265	   805	         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
  3266	   806	         "simply never noticed. Both columns above therefore use the SAME "
  3267	   807	         "restricted estimand so the delta is attributable to the dates alone; "
  3268	   808	         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
  3269	   809	         "(after) hold the old estimand on each side for reference.",
  3270	   810	)
  3271	   811	
  3272	   812	# --- 2.17x : high-VIX vs low-VIX regime ---
  3273	   813	proxy_reg = proxy["regime_analysis"]
  3274	   814	record(
  3275	   815	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
  3276	   816	    {
  3277	   817	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
  3278	   818	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
  3279	   819	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
  3280	   820	        "n_high": proxy_reg["n_high"],
  3281	{
  3282	  "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
  3283	  "before": {
  3284	    "mean_ratio": 1.1678258584088317,
  3285	    "p_value": 0.040941658051326435,
  3286	    "significant_5pct": true,
  3287	    "n": 239,
  3288	    "nfp_days_on_friday": 239,
  3289	    "median_ratio": 1.19826014827573,
  3290	    "win_rate": 0.5564853556485355,
  3291	    "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  3292	    "as_published_mixed_weekday": {
  3293	      "mean_ratio": 1.168212716801256,
  3294	      "p_value": 0.03354366521379227,
  3295	      "significant_5pct": true,
  3296	      "n": 254,
  3297	      "note": "what the proxy run actually published: all 254 events (239 Friday, 15 Monday) against non-NFP Fridays. This is the number the article quoted, so it is kept, but it is NOT the like-for-like comparison against the corrected column."
  3298	    }
  3299	  },
  3300	  "after": {
  3301	    "mean_ratio": 1.1889914161952833,
  3302	    "p_value": 0.020855995901856498,
  3303	    "significant_5pct": true,
  3304	    "n": 237,
  3305	    "nfp_days_on_friday": 237,
  3306	    "median_ratio": 1.2184264509585134,
  3307	    "win_rate": 0.569620253164557,
  3308	    "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  3309	    "diagnostic_mixed_weekday": {
  3310	      "mean_ratio": 1.1767586712062934,
  3311	      "p_value": 0.025694250730145685,
  3312	      "significant_5pct": true,
  3313	      "n": 253,
  3314	      "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
  3315	    }
  3316	  },
  3317	  "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to Friday releases. Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
  3318	  "verdict": "NUMERIC_ADJUSTMENT",
  3319	  "verdict_reasons": []
  3320	}
  3321	[
  3322	  {
  3323	    "weekday": 0,
  3324	    "n": 6
  3325	  },
  3326	  {
  3327	    "weekday": 1,
  3328	    "n": 2
  3329	  },
  3330	  {
  3331	    "weekday": 2,
  3332	    "n": 1
  3333	  },
  3334	  {
  3335	    "weekday": 3,
  3336	    "n": 7
  3337	  },
  3338	  {
  3339	    "weekday": 4,
  3340	    "n": 237
  3341	  }
  3342	]
  3343	[
  3344	  {
  3345	    "weekday": 0,
  3346	    "n": 15
  3347	  },
  3348	  {
  3349	    "weekday": 4,
  3350	    "n": 239
  3351	  }
  3352	]
  3353	[
  3354	  {
  3355	    "weekday": "1",
  3356	    "n": 15
  3357	  },
  3358	  {
  3359	    "weekday": "5",
  3360	    "n": 239
  3361	  }
  3362	]
  3363	{
  3364	  "superseded": true,
  3365	  "do_not_cite": true,
  3366	  "superseded_at": "2026-07-19",
  3367	  "superseded_reason": null,
  3368	  "keys": [
  3369	    "april_nfp",
  3370	    "audit_artifact",
  3371	    "conclusions",
  3372	    "data_source",
  3373	    "date",
  3374	    "directional_bias",
  3375	    "do_not_cite",
  3376	    "event_data",
  3377	    "event_date_source",
  3378	    "experiment_id",
  3379	    "impact_on_published_numbers",
  3380	    "intraday_range",
  3381	    "main_results",
  3382	    "note_for_machines",
  3383	    "practical_implication",
  3384	    "references",
  3385	    "regime_analysis",
  3386	    "retraction_reason",
  3387	    "sample",
  3388	    "seasonal_analysis",
  3389	    "statistical_tests",
  3390	    "superseded",
  3391	    "superseded_at",
  3392	    "superseded_by",
  3393	    "time_trend",
  3394	    "title",
  3395	    "volume"
  3396	  ]
  3397	}
  3398	
  3399	exec
  3400	/bin/zsh -lc "git status --short --branch
  3401	git diff -- experiments/k528/k528_nfp_event_study.py experiments/k528/k528_nfp_official_dates_results.json experiments/k528/k528_nfp_event_study_results.json | sed -n '1,260p'
  3402	git log -3 --oneline --decorate" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  3403	 succeeded in 222ms:
  3404	## k528-nfp-official-dates
  3405	 M experiments/k528/k528_nfp_event_study.py
  3406	 M experiments/k528/k528_nfp_event_study_results.json
  3407	 M experiments/k528/k528_nfp_official_dates_results.json
  3408	diff --git a/experiments/k528/k528_nfp_event_study.py b/experiments/k528/k528_nfp_event_study.py
  3409	index 6983a642f..93ef63d38 100644
  3410	--- a/experiments/k528/k528_nfp_event_study.py
  3411	+++ b/experiments/k528/k528_nfp_event_study.py
  3412	@@ -337,20 +337,34 @@ print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
  3413	 # ============================================================
  3414	 print("\n[4/6] Computing non-NFP baseline...")
  3415	 
  3416	-nfp_set = set(valid_nfp)
  3417	+# Exclude EVERY NFP session from the control group, not just the ones that
  3418	+# survived the event-window filter. An event dropped for lacking a pre-window
  3419	+# is still an NFP day; leaving it in the control group is the exact failure this
  3420	+# experiment exists to fix ("dump real event days into the control group"), just
  3421	+# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
  3422	+nfp_set = set(nfp_trading_dates)
  3423	 non_nfp_mask = ~spy.index.isin(nfp_set)
  3424	 non_nfp = spy[non_nfp_mask]
  3425	+n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
  3426	+if n_leaked:
  3427	+    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
  3428	 
  3429	 baseline_abs_return = float(non_nfp["AbsReturn"].mean())
  3430	 baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
  3431	 baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
  3432	 
  3433	-# Friday-only baseline. Under the proxy every event was a Friday by
  3434	-# construction, so "all NFP events vs non-NFP Fridays" was a clean
  3435	-# weekday-held-fixed contrast. On the official calendar it is not: the event
  3436	-# group is a weekday mixture and the control group is pure Friday, so any
  3437	-# Friday-vs-other-weekday volatility difference loads directly onto the
  3438	-# estimate. The test below therefore holds weekday fixed on BOTH sides.
  3439	+# Friday-only baseline. The event group is a weekday MIXTURE while the control
  3440	+# group is pure Friday, so any Friday-vs-other-weekday volatility difference
  3441	+# loads straight onto the estimate. The test below holds weekday fixed on BOTH
  3442	+# sides.
  3443	+#
  3444	+# Note against the obvious story: this defect is NOT introduced by the date
  3445	+# correction. The proxy calendar was all-Friday by construction, but mapping
  3446	+# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
  3447	+# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
  3448	+# always there and is essentially unchanged; the old spec was already comparing
  3449	+# a mixed group against a pure-Friday control. Correcting the dates is what made
  3450	+# it visible, not what caused it.
  3451	 friday_mask = non_nfp.index.weekday == 4
  3452	 friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
  3453	 friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
  3454	@@ -377,13 +391,18 @@ vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
  3455	 # Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
  3456	 #   (i)  restrict the event group to Friday releases, or
  3457	 #   (ii) keep all events and use weekday-matched controls.
  3458	-# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
  3459	-# 253 -- cells that thin make (ii) a weighted average dominated by three
  3460	-# single-digit strata, with standard errors driven by the 1-observation
  3461	-# Wednesday cell. That is a noisier estimator of a harder-to-state quantity.
  3462	-# (i) answers one clean question: on a Friday, does an NFP release raise
  3463	-# volatility? It costs the 11 non-Friday events, which are reported below as a
  3464	-# separate descriptive line rather than dropped in silence.
  3465	+# This run takes (i). The non-Friday events are a handful of thin weekday cells
  3466	+# out of 253 -- cells that thin make (ii) a weighted average dominated by a few
  3467	+# single-digit strata, with standard errors driven by the smallest of them.
  3468	+# That is a noisier estimator of a harder-to-state quantity. (i) answers one
  3469	+# clean question: on a Friday, does an NFP release raise volatility? It costs
  3470	+# the non-Friday events, which are reported below as a separate descriptive
  3471	+# line rather than dropped in silence.
  3472	+#
  3473	+# The exclusion is not neutral and should not be sold as such: the excluded
  3474	+# events are quieter than the Friday ones, so restricting RAISES the ratio
  3475	+# relative to the mixed spec. That is a property of the estimand, not evidence
  3476	+# of a stronger effect. Both numbers are reported.
  3477	 nfp_friday_mask = (df["weekday"] == 4).values
  3478	 nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
  3479	 nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
  3480	@@ -668,6 +687,17 @@ proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
  3481	 proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
  3482	 proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
  3483	 
  3484	+# The proxy calendar was all-Friday by construction, but 15 of its 254 events
  3485	+# mapped to a Monday because the first Friday was a market holiday. So the
  3486	+# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
  3487	+# rebuild the proxy side under the SAME estimand the corrected run uses
  3488	+# (Friday events only) rather than comparing a mixed `before` against a
  3489	+# restricted `after` and calling the difference a correction effect.
  3490	+_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
  3491	+proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
  3492	+_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
  3493	+proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
  3494	+
  3495	 _p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
  3496	                        for e in proxy_events])
  3497	 _p_thr = proxy["regime_analysis"]["vix_median_split"]
  3498	@@ -728,13 +758,27 @@ record(
  3499	 record(
  3500	     "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
  3501	     {
  3502	-        "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
  3503	-        "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
  3504	-        "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
  3505	-        "n": proxy["sample"]["total_nfp_events"],
  3506	-        "nfp_days_on_friday": proxy["sample"]["total_nfp_events"],
  3507	-        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_fri_abs)),
  3508	-        "win_rate": win_rate(proxy_nfp_abs, proxy_fri_abs),
  3509	+        # Same estimand as the `after` column: Friday events only.
  3510	+        "mean_ratio": proxy_ratio_fri_restricted,
  3511	+        "p_value": float(_p_p_fri),
  3512	+        "significant_5pct": bool(_p_p_fri < 0.05),
  3513	+        "n": int(len(proxy_nfp_friday_abs)),
  3514	+        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
  3515	+        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
  3516	+        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
  3517	+        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  3518	+        "as_published_mixed_weekday": {
  3519	+            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
  3520	+            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
  3521	+            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
  3522	+            "n": proxy["sample"]["total_nfp_events"],
  3523	+            "note": (
  3524	+                "what the proxy run actually published: all 254 events (239 Friday, "
  3525	+                "15 Monday) against non-NFP Fridays. This is the number the article "
  3526	+                "quoted, so it is kept, but it is NOT the like-for-like comparison "
  3527	+                "against the corrected column."
  3528	+            ),
  3529	+        },
  3530	     },
  3531	     {
  3532	         "mean_ratio": vol_ratio_fri,
  3533	@@ -753,14 +797,16 @@ record(
  3534	             "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
  3535	         },
  3536	     },
  3537	-    note="Two things changed at once here, and they must not be conflated. "
  3538	-         "(1) The dates were corrected. (2) The ESTIMAND was corrected: under "
  3539	-         "the proxy every NFP day was a Friday by construction, so this test "
  3540	-         "compared Fridays with Fridays; on the official calendar the event "
  3541	-         "group is a weekday mixture, so the like-for-like test now restricts "
  3542	-         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
  3543	-         "the date-corrected value of the OLD estimand, which is the apples-to-"
  3544	-         "apples comparison against the `before` column.",
  3545	+    note="Two things changed here and they are separated rather than conflated. "
  3546	+         "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
  3547	+         "event group is a weekday mixture while the control group is pure "
  3548	+         "Friday, so the test now restricts the event group to Friday releases. "
  3549	+         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
  3550	+         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
  3551	+         "simply never noticed. Both columns above therefore use the SAME "
  3552	+         "restricted estimand so the delta is attributable to the dates alone; "
  3553	+         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
  3554	+         "(after) hold the old estimand on each side for reference.",
  3555	 )
  3556	 
  3557	 # --- 2.17x : high-VIX vs low-VIX regime ---
  3558	diff --git a/experiments/k528/k528_nfp_event_study_results.json b/experiments/k528/k528_nfp_event_study_results.json
  3559	index 548670944..4e136ece5 100644
  3560	--- a/experiments/k528/k528_nfp_event_study_results.json
  3561	+++ b/experiments/k528/k528_nfp_event_study_results.json
  3562	@@ -1,7 +1,7 @@
  3563	 {
  3564	   "experiment_id": "K528",
  3565	   "title": "NFP Event Study on SPY Volatility",
  3566	-  "date": "2026-07-19T08:16:52.820209+00:00",
  3567	+  "date": "2026-07-19T08:21:14.483198+00:00",
  3568	   "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
  3569	   "event_date_source": {
  3570	     "source": "official BLS release calendar via ALFRED (FRED release id 50)",
  3571	@@ -12,8 +12,8 @@
  3572	   "sample": {
  3573	     "total_nfp_events": 253,
  3574	     "date_range": "2005-02-04 to 2026-03-06",
  3575	-    "non_nfp_trading_days": 5087,
  3576	-    "friday_baseline_days": 835,
  3577	+    "non_nfp_trading_days": 5086,
  3578	+    "friday_baseline_days": 834,
  3579	     "nfp_days_on_friday": 237,
  3580	     "event_mapping_audit": {
  3581	       "n_official_releases": 254,
  3582	@@ -35,66 +35,66 @@
  3583	     }
  3584	   },
  3585	   "main_results": {
  3586	-    "nfp_avg_abs_return": 0.008453062192235669,
  3587	+    "nfp_avg_abs_return": 0.008453069476984605,
  3588	     "nfp_avg_abs_return_pct": "0.845%",
  3589	-    "non_nfp_avg_abs_return": 0.007629426519073289,
  3590	+    "non_nfp_avg_abs_return": 0.007630641051729298,
  3591	     "non_nfp_avg_abs_return_pct": "0.763%",
  3592	-    "friday_baseline_abs_return": 0.0071764494731905775,
  3593	-    "vol_ratio_vs_all": 1.1079551223284374,
  3594	-    "vol_ratio_vs_friday": 1.1901328478556155
  3595	+    "friday_baseline_abs_return": 0.007183350064732795,
  3596	+    "vol_ratio_vs_all": 1.1077797290791085,
  3597	+    "vol_ratio_vs_friday": 1.1889914161952833
  3598	   },
  3599	   "statistical_tests": {
  3600	     "A_nfp_vs_all": {
  3601	       "test": "Welch t-test",
  3602	-      "t_stat": 1.596241850709586,
  3603	-      "p_value": 0.1115348306661545,
  3604	+      "t_stat": 1.593882436719971,
  3605	+      "p_value": 0.11206252056069128,
  3606	       "significant_5pct": false
  3607	     },
  3608	     "B_nfp_vs_friday": {
  3609	       "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
  3610	       "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
  3611	       "n_event": 237,
  3612	-      "n_control": 835,
  3613	-      "vol_ratio": 1.1901328478556155,
  3614	-      "t_stat": 2.332682989591967,
  3615	-      "p_value": 0.020198459584478665,
  3616	+      "n_control": 834,
  3617	+      "vol_ratio": 1.1889914161952833,
  3618	+      "t_stat": 2.3204773740207667,
  3619	+      "p_value": 0.020855995901856498,
  3620	       "significant_5pct": true,
  3621	       "excluded_non_friday_events": {
  3622	         "n": 16,
  3623	-        "mean_abs_return": 0.0071515462261143095
  3624	+        "mean_abs_return": 0.007151464151139632
  3625	       }
  3626	     },
  3627	     "B_diagnostic_mixed_weekday": {
  3628	       "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
  3629	       "status": "DIAGNOSTIC ONLY - do not quote",
  3630	       "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
  3631	-      "vol_ratio": 1.177889180968137,
  3632	-      "t_stat": 2.2515875177085047,
  3633	-      "p_value": 0.024879138655181043,
  3634	+      "vol_ratio": 1.1767586712062934,
  3635	+      "t_stat": 2.2389868815589358,
  3636	+      "p_value": 0.025694250730145685,
  3637	       "significant_5pct": true
  3638	     },
  3639	     "C_wilcoxon": {
  3640	       "test": "Mann-Whitney U (one-sided)",
  3641	-      "u_stat": 712704.0,
  3642	-      "p_value": 0.001918721963396258,
  3643	+      "u_stat": 712480.0,
  3644	+      "p_value": 0.001940321187311424,
  3645	       "significant_5pct": true
  3646	     },
  3647	     "D_vol_crush": {
  3648	       "test": "One-sample t-test (post-pre diff)",
  3649	-      "pre_avg": 0.007787024581397933,
  3650	-      "post_avg": 0.0076873544749868,
  3651	-      "diff": -9.96701064111322e-05,
  3652	-      "t_stat": -0.31069924923269754,
  3653	-      "p_value": 0.7562860985174406,
  3654	+      "pre_avg": 0.007787018553374247,
  3655	+      "post_avg": 0.007687361612714394,
  3656	+      "diff": -9.965694065985285e-05,
  3657	+      "t_stat": -0.31065889096205646,
  3658	+      "p_value": 0.7563167465955569,
  3659	       "vol_crush_present": false
  3660	     },
  3661	     "E_vix_predictive": {
  3662	       "test": "Pearson + Spearman correlation",
  3663	-      "pearson_r": 0.44043736398798927,
  3664	-      "pearson_p": 1.9814384001854257e-13,
  3665	-      "spearman_rho": 0.3455048873701663,
  3666	-      "spearman_p": 1.6699985504624933e-08,
  3667	-      "slope": 0.00042561778477078567,
  3668	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
  3669	e42dc25ad fix(k528): NFP 事件日改用官方日曆重跑，1 項顯著性翻轉
  3670	50bb24870 (origin/main, origin/HEAD) dispatch(15:22): 自動摘要（agent 未留 receipt）: 動到 storage/ops/(2)
  3671	
  3672	codex
  3673	審查中 worktree 被另一程序改成 dirty；我已停止把「目前檔案」當目標，後續一律以使用者指定的 commit `6fd281901` 取證。這次漂移反而暴露一個實質問題：該 commit 只從控制組排除 `valid_nfp`，把因視窗緩衝被排除的真實 NFP 日（2005-01-07）誤留在 non-NFP 控制組；因此聲稱的 1.190/0.0202 與 1.1779/0.02488 是受污染數字。未提交 rerun 自己把它改成約 1.1890/0.02086 與 1.1768/0.02569。這會作為新 blocker 進一步獨立驗算。
  3674	exec
  3675	/bin/zsh -lc "rg --files storage | rg -i '(spy|yfinance|yf_|prices|market_data)' | head -n 200
  3676	find . -path '*/.cache/*' -o -path '*/storage/data/*' | rg -i '(spy|yfinance|sqlite|cache)' | head -n 200
  3677	
  3678	git show 6fd281901:experiments/k528/k528_nfp_event_study_results.json | jq '{sample:.sample, main_results:.main_results, B:.statistical_tests.B_nfp_vs_friday, Bdiag:.statistical_tests.B_diagnostic_mixed_weekday}'
  3679	git show 6fd281901:experiments/k528/k528_nfp_official_dates_results.json | jq '.items.vol_ratio_vs_friday, .article_correction'
  3680	
  3681	git show 6fd281901:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '330,420p'
  3682	git show 6fd281901:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '680,815p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  3683	 succeeded in 1522ms:
  3684	./storage/data/event_dates_cache
  3685	./storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-27.json
  3686	./storage/data/event_dates_cache/NFP_US_2005-01-01_2026-03-31.json
  3687	./storage/data/event_dates_cache/NFP_US_2005-02-01_2026-03-31.json
  3688	{
  3689	  "sample": {
  3690	    "total_nfp_events": 253,
  3691	    "date_range": "2005-02-04 to 2026-03-06",
  3692	    "non_nfp_trading_days": 5087,
  3693	    "friday_baseline_days": 835,
  3694	    "nfp_days_on_friday": 237,
  3695	    "event_mapping_audit": {
  3696	      "n_official_releases": 254,
  3697	      "n_mapped_to_sessions": 254,
  3698	      "n_shifted_to_next_session": 6,
  3699	      "n_outside_price_sample": 0,
  3700	      "outside_price_sample_dates": [],
  3701	      "n_excluded_for_window_buffer": 1,
  3702	      "window_excluded_dates": [
  3703	        "2005-01-07"
  3704	      ],
  3705	      "n_valid_events": 253
  3706	    },
  3707	    "calendar_completeness": {
  3708	      "n_months_expected": 253,
  3709	      "known_missing_months": [
  3710	        "2025-10"
  3711	      ]
  3712	    }
  3713	  },
  3714	  "main_results": {
  3715	    "nfp_avg_abs_return": 0.008453062192235669,
  3716	    "nfp_avg_abs_return_pct": "0.845%",
  3717	    "non_nfp_avg_abs_return": 0.007629426519073289,
  3718	    "non_nfp_avg_abs_return_pct": "0.763%",
  3719	    "friday_baseline_abs_return": 0.0071764494731905775,
  3720	    "vol_ratio_vs_all": 1.1079551223284374,
  3721	    "vol_ratio_vs_friday": 1.1901328478556155
  3722	  },
  3723	  "B": {
  3724	    "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
  3725	    "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
  3726	    "n_event": 237,
  3727	    "n_control": 835,
  3728	    "vol_ratio": 1.1901328478556155,
  3729	    "t_stat": 2.332682989591967,
  3730	    "p_value": 0.020198459584478665,
  3731	    "significant_5pct": true,
  3732	    "excluded_non_friday_events": {
  3733	      "n": 16,
  3734	      "mean_abs_return": 0.0071515462261143095
  3735	    }
  3736	  },
  3737	  "Bdiag": {
  3738	    "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
  3739	    "status": "DIAGNOSTIC ONLY - do not quote",
  3740	    "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
  3741	    "vol_ratio": 1.177889180968137,
  3742	    "t_stat": 2.2515875177085047,
  3743	    "p_value": 0.024879138655181043,
  3744	    "significant_5pct": true
  3745	  }
  3746	}
  3747	{
  3748	  "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
  3749	  "before": {
  3750	    "mean_ratio": 1.168212716801256,
  3751	    "p_value": 0.03354366521379227,
  3752	    "significant_5pct": true,
  3753	    "n": 254,
  3754	    "nfp_days_on_friday": 254,
  3755	    "median_ratio": 1.2091317875797052,
  3756	    "win_rate": 0.562992125984252
  3757	  },
  3758	  "after": {
  3759	    "mean_ratio": 1.1901328478556155,
  3760	    "p_value": 0.020198459584478665,
  3761	    "significant_5pct": true,
  3762	    "n": 237,
  3763	    "nfp_days_on_friday": 237,
  3764	    "median_ratio": 1.2225564362044339,
  3765	    "win_rate": 0.569620253164557,
  3766	    "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  3767	    "diagnostic_mixed_weekday": {
  3768	      "mean_ratio": 1.177889180968137,
  3769	      "p_value": 0.024879138655181043,
  3770	      "significant_5pct": true,
  3771	      "n": 253,
  3772	      "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
  3773	    }
  3774	  },
  3775	  "note": "Two things changed at once here, and they must not be conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: under the proxy every NFP day was a Friday by construction, so this test compared Fridays with Fridays; on the official calendar the event group is a weekday mixture, so the like-for-like test now restricts the event group to Friday releases. `diagnostic_mixed_weekday` holds the date-corrected value of the OLD estimand, which is the apples-to-apples comparison against the `before` column.",
  3776	  "verdict": "NUMERIC_ADJUSTMENT",
  3777	  "verdict_reasons": []
  3778	}
  3779	{
  3780	  "article_id": "mile_35eef830",
  3781	  "status": "validated_not_applied",
  3782	  "n_replacements": 19,
  3783	  "all_matched_exactly_once": true,
  3784	  "supersedes": {
  3785	    "voided_list_size": 18,
  3786	    "voided_at": "2026-07-19",
  3787	    "reason": "the 18-item list was built against a rerun whose accessor picked off-cycle ALFRED entries for six months, which pushed the NFP-vs-Friday test across the 5% line. It would have retracted a finding that is in fact correct."
  3788	  },
  3789	  "directional_claims_changed": 0,
  3790	  "replacements": [
  3791	    {
  3792	      "from": "總共 254 次 NFP 公布日的資料算過一遍",
  3793	      "to": "總共 253 次 NFP 公布日的資料算過一遍",
  3794	      "hits": 1
  3795	    },
  3796	    {
  3797	      "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
  3798	      "to": "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
  3799	      "hits": 1
  3800	    },
  3801	    {
  3802	      "from": "換句話說，這 1.10 倍的差距",
  3803	      "to": "換句話說，這 1.11 倍的差距",
  3804	      "hits": 1
  3805	    },
  3806	    {
  3807	      "from": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  3808	      "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  3809	      "hits": 1
  3810	    },
  3811	    {
  3812	      "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
  3813	      "to": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
  3814	      "hits": 1
  3815	    },
  3816	    {
  3817	      "from": "那 254 次 NFP 日裡",
  3818	      "to": "那 253 次 NFP 日裡",
  3819	      "hits": 1
  3820	    },
  3821	    {
  3822	      "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
  3823	      "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
  3824	      "hits": 1
  3825	    },
  3826	    {
  3827	      "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
  3828	      "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
  3829	      "hits": 1
  3830	    },
  3831	    {
  3832	      "from": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
  3833	      "to": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
  3834	      "hits": 1
  3835	    },
  3836	    {
  3837	      "from": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
  3838	      "to": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
  3839	      "hits": 1
  3840	    },
  3841	    {
  3842	      "from": "貼在歷史分界線 16.71 的下緣",
  3843	      "to": "貼在歷史分界線 16.69 的下緣",
  3844	      "hits": 1
  3845	    },
  3846	    {
  3847	      "from": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
  3848	      "to": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
  3849	      "hits": 1
  3850	    },
  3851	    {
  3852	      "from": "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
  3853	      "to": "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
  3854	      "hits": 1
  3855	    },
  3856	    {
  3857	      "from": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。",
  3858	      "to": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準，對週五基準是 1.19 倍、達到顯著水準。",
  3859	      "hits": 1
  3860	    },
  3861	    {
  3862	      "from": "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
  3863	      "to": "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
  3864	      "hits": 1
  3865	    },
  3866	    {
  3867	      "from": "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
  3868	      "to": "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
  3869	      "hits": 1
  3870	    },
  3871	    {
  3872	      "from": "254 場歷史樣本加上 7/2 這場實測",
  3873	      "to": "253 場歷史樣本加上 7/2 這場實測",
  3874	      "hits": 1
  3875	    },
  3876	    {
  3877	      "from": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
  3878	      "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。另有一項口徑調整：初版的 NFP 全部落在週五，週五基準比較是同星期別對同星期別；官方日曆下有 16 場不在週五，因此該比較改為只取在週五公布的 237 場，維持兩邊星期別一致。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
  3879	      "hits": 1
  3880	    },
  3881	    {
  3882	      "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
  3883	      "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
  3884	      "hits": 1
  3885	    }
  3886	  ],
  3887	  "apply_result": null,
  3888	  "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
  3889	}
  3890	   330	
  3891	   331	df = pd.DataFrame(results)
  3892	   332	print(f"  Events with complete data: {len(df)}")
  3893	   333	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
  3894	   334	
  3895	   335	# ============================================================
  3896	   336	# 5. Non-NFP baseline calculation
  3897	   337	# ============================================================
  3898	   338	print("\n[4/6] Computing non-NFP baseline...")
  3899	   339	
  3900	   340	nfp_set = set(valid_nfp)
  3901	   341	non_nfp_mask = ~spy.index.isin(nfp_set)
  3902	   342	non_nfp = spy[non_nfp_mask]
  3903	   343	
  3904	   344	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
  3905	   345	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
  3906	   346	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
  3907	   347	
  3908	   348	# Friday-only baseline. Under the proxy every event was a Friday by
  3909	   349	# construction, so "all NFP events vs non-NFP Fridays" was a clean
  3910	   350	# weekday-held-fixed contrast. On the official calendar it is not: the event
  3911	   351	# group is a weekday mixture and the control group is pure Friday, so any
  3912	   352	# Friday-vs-other-weekday volatility difference loads directly onto the
  3913	   353	# estimate. The test below therefore holds weekday fixed on BOTH sides.
  3914	   354	friday_mask = non_nfp.index.weekday == 4
  3915	   355	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
  3916	   356	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
  3917	   357	
  3918	   358	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
  3919	   359	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
  3920	   360	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
  3921	   361	
  3922	   362	# ============================================================
  3923	   363	# 6. Statistical tests
  3924	   364	# ============================================================
  3925	   365	print("\n[5/6] Running statistical tests...")
  3926	   366	
  3927	   367	nfp_abs_returns = df["event_abs_return"].values
  3928	   368	non_nfp_abs_returns = non_nfp["AbsReturn"].values
  3929	   369	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
  3930	   370	
  3931	   371	# --- Test A: NFP vs all non-NFP days ---
  3932	   372	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
  3933	   373	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
  3934	   374	
  3935	   375	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
  3936	   376	#
  3937	   377	# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
  3938	   378	#   (i)  restrict the event group to Friday releases, or
  3939	   379	#   (ii) keep all events and use weekday-matched controls.
  3940	   380	# This run takes (i). The non-Friday events are Thu 8 / Tue 2 / Wed 1 out of
  3941	   381	# 253 -- cells that thin make (ii) a weighted average dominated by three
  3942	   382	# single-digit strata, with standard errors driven by the 1-observation
  3943	   383	# Wednesday cell. That is a noisier estimator of a harder-to-state quantity.
  3944	   384	# (i) answers one clean question: on a Friday, does an NFP release raise
  3945	   385	# volatility? It costs the 11 non-Friday events, which are reported below as a
  3946	   386	# separate descriptive line rather than dropped in silence.
  3947	   387	nfp_friday_mask = (df["weekday"] == 4).values
  3948	   388	nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
  3949	   389	nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
  3950	   390	
  3951	   391	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
  3952	   392	vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
  3953	   393	
  3954	   394	# Diagnostic ONLY -- the pre-correction specification, kept so the correction
  3955	   395	# audit can show what the contaminated estimand was worth. Not a headline
  3956	   396	# number and not eligible to be quoted: its p-value mixes in weekday
  3957	   397	# composition, which is exactly the defect being repaired.
  3958	   398	t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
  3959	   399	    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
  3960	   400	vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
  3961	   401	
  3962	   402	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
  3963	   403	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
  3964	   404	
  3965	   405	# --- Test D: Vol crush pattern (post vs pre) ---
  3966	   406	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
  3967	   407	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
  3968	   408	
  3969	   409	# --- Test E: VIX predictive regression ---
  3970	   410	vix_valid = df.dropna(subset=["pre_vix"])
  3971	   411	if len(vix_valid) > 10:
  3972	   412	    from numpy.polynomial.polynomial import polyfit
  3973	   413	    X_vix = vix_valid["pre_vix"].values
  3974	   414	    Y_abs = vix_valid["event_abs_return"].values
  3975	   415	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
  3976	   416	    # correlation and p-value
  3977	   417	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
  3978	   418	    # also spearman
  3979	   419	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
  3980	   420	else:
  3981	   680	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
  3982	   681	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
  3983	   682	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
  3984	   683	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
  3985	   684	):
  3986	   685	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
  3987	   686	        raise AssertionError(
  3988	   687	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
  3989	   688	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
  3990	   689	            "from a reconstruction that cannot reproduce the archived means."
  3991	   690	        )
  3992	   691	print("  proxy-era distributions reconstructed from archive (means reproduce)")
  3993	   692	
  3994	   693	audit_items = {}
  3995	   694	
  3996	   695	
  3997	   696	def record(key, label, before, after, note=""):
  3998	   697	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
  3999	   698	
  4000	   699	
  4001	   700	# --- 1.10x : NFP vs all non-NFP days ---
  4002	   701	record(
  4003	   702	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
  4004	   703	    {
  4005	   704	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
  4006	   705	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
  4007	   706	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
  4008	   707	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
  4009	   708	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
  4010	   709	        "n": proxy["sample"]["total_nfp_events"],
  4011	   710	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
  4012	   711	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
  4013	   712	    },
  4014	   713	    {
  4015	   714	        "mean_ratio": vol_ratio_all,
  4016	   715	        "nfp_mean": float(nfp_abs_returns.mean()),
  4017	   716	        "baseline_mean": baseline_abs_return,
  4018	   717	        "p_value": float(p_val_all),
  4019	   718	        "significant_5pct": bool(p_val_all < 0.05),
  4020	   719	        "n": int(len(df)),
  4021	   720	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
  4022	   721	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
  4023	   722	    },
  4024	   723	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
  4025	   724	         "per-event data, not from the proxy run's own output (it only reported means).",
  4026	   725	)
  4027	   726	
  4028	   727	# --- 1.17x : NFP vs Friday-only baseline ---
  4029	   728	record(
  4030	   729	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
  4031	   730	    {
  4032	   731	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
  4033	   732	        "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
  4034	   733	        "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
  4035	   734	        "n": proxy["sample"]["total_nfp_events"],
  4036	   735	        "nfp_days_on_friday": proxy["sample"]["total_nfp_events"],
  4037	   736	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_fri_abs)),
  4038	   737	        "win_rate": win_rate(proxy_nfp_abs, proxy_fri_abs),
  4039	   738	    },
  4040	   739	    {
  4041	   740	        "mean_ratio": vol_ratio_fri,
  4042	   741	        "p_value": float(p_val_fri),
  4043	   742	        "significant_5pct": bool(p_val_fri < 0.05),
  4044	   743	        "n": int(len(nfp_friday_abs)),
  4045	   744	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
  4046	   745	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
  4047	   746	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
  4048	   747	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  4049	   748	        "diagnostic_mixed_weekday": {
  4050	   749	            "mean_ratio": vol_ratio_fri_mixed,
  4051	   750	            "p_value": float(p_val_fri_mixed),
  4052	   751	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
  4053	   752	            "n": int(len(df)),
  4054	   753	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
  4055	   754	        },
  4056	   755	    },
  4057	   756	    note="Two things changed at once here, and they must not be conflated. "
  4058	   757	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: under "
  4059	   758	         "the proxy every NFP day was a Friday by construction, so this test "
  4060	   759	         "compared Fridays with Fridays; on the official calendar the event "
  4061	   760	         "group is a weekday mixture, so the like-for-like test now restricts "
  4062	   761	         "the event group to Friday releases. `diagnostic_mixed_weekday` holds "
  4063	   762	         "the date-corrected value of the OLD estimand, which is the apples-to-"
  4064	   763	         "apples comparison against the `before` column.",
  4065	   764	)
  4066	   765	
  4067	   766	# --- 2.17x : high-VIX vs low-VIX regime ---
  4068	   767	proxy_reg = proxy["regime_analysis"]
  4069	   768	record(
  4070	   769	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
  4071	   770	    {
  4072	   771	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
  4073	   772	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
  4074	   773	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
  4075	   774	        "n_high": proxy_reg["n_high"],
  4076	   775	        "n_low": proxy_reg["n_low"],
  4077	   776	        "p_value": proxy_reg["p_value"],
  4078	   777	        "significant_5pct": proxy_reg["p_value"] < 0.05,
  4079	   778	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
  4080	   779	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
  4081	   780	    },
  4082	   781	    {
  4083	   782	        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
  4084	   783	        "high_mean": float(high_vix.mean()),
  4085	   784	        "low_mean": float(low_vix.mean()),
  4086	   785	        "n_high": int(len(high_vix)),
  4087	   786	        "n_low": int(len(low_vix)),
  4088	   787	        "p_value": float(p_regime),
  4089	   788	        "significant_5pct": bool(p_regime < 0.05),
  4090	   789	        "median_ratio": float(high_vix.median() / low_vix.median()),
  4091	   790	        "win_rate": win_rate(high_vix.values, low_vix.values),
  4092	   791	    },
  4093	   792	)
  4094	   793	
  4095	   794	# --- 0.45 : pre-event VIX correlation ---
  4096	   795	proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
  4097	   796	record(
  4098	   797	    "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
  4099	   798	    {
  4100	   799	        "pearson_r": proxy_e["pearson_r"],
  4101	   800	        "pearson_p": proxy_e["pearson_p"],
  4102	   801	        "spearman_rho": proxy_e["spearman_rho"],
  4103	   802	        "spearman_p": proxy_e["spearman_p"],
  4104	   803	        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
  4105	   804	        "n": proxy["sample"]["total_nfp_events"],
  4106	   805	        "significant_5pct": proxy_e["pearson_p"] < 0.05,
  4107	   806	    },
  4108	   807	    {
  4109	   808	        "pearson_r": float(r_vix),
  4110	   809	        "pearson_p": float(p_vix),
  4111	   810	        "spearman_rho": float(rho_vix),
  4112	   811	        "spearman_p": float(p_rho_vix),
  4113	   812	        "slope_pct_per_vix_pt": float(slope) * 100,
  4114	   813	        "n": int(len(vix_valid)),
  4115	   814	        "significant_5pct": bool(p_vix < 0.05),
  4116	   815	    },
  4117	
  4118	exec
  4119	/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 uv run python -c 'import requests,datetime as dt; u=\"https://query1.finance.yahoo.com/v8/finance/chart/SPY\"; p={\"period1\":int(dt.datetime(2005,1,1,tzinfo=dt.timezone.utc).timestamp()),\"period2\":int(dt.datetime(2005,1,12,tzinfo=dt.timezone.utc).timestamp()),\"interval\":\"1d\",\"events\":\"history\",\"includeAdjustedClose\":\"true\"}; r=requests.get(u,params=p,timeout=20); print(r.status_code,len(r.content)); d=r.json()[\"chart\"][\"result\"][0] if r.ok else None; print([(str(dt.datetime.fromtimestamp(t,dt.timezone.utc).date()),c) for t,c in zip(d[\"timestamp\"],d[\"indicators\"][\"quote\"][0][\"close\"])]) if d else None'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  4120	 exited 2 in 280ms:
  4121	error: failed to open file `/Users/yhlai0911/.cache/uv/sdists-v9/.git`: Operation not permitted (os error 1)
  4122	
  4123	exec
  4124	/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import requests,datetime as dt; u=\"https://query1.finance.yahoo.com/v8/finance/chart/SPY\"; p={\"period1\":int(dt.datetime(2005,1,1,tzinfo=dt.timezone.utc).timestamp()),\"period2\":int(dt.datetime(2005,1,12,tzinfo=dt.timezone.utc).timestamp()),\"interval\":\"1d\",\"events\":\"history\",\"includeAdjustedClose\":\"true\"}; r=requests.get(u,params=p,timeout=20); print(r.status_code,len(r.content)); d=r.json()[\"chart\"][\"result\"][0] if r.ok else None; print([(str(dt.datetime.fromtimestamp(t,dt.timezone.utc).date()),c) for t,c in zip(d[\"timestamp\"],d[\"indicators\"][\"quote\"][0][\"close\"])]) if d else None'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  4125	 exited 1 in 117ms:
  4126	    for res in _socket.getaddrinfo(host, port, family, type, proto, flags):
  4127	               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  4128	socket.gaierror: [Errno 8] nodename nor servname provided, or not known
  4129	
  4130	The above exception was the direct cause of the following exception:
  4131	
  4132	Traceback (most recent call last):
  4133	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 787, in urlopen
  4134	    response = self._make_request(
  4135	               ^^^^^^^^^^^^^^^^^^^
  4136	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 488, in _make_request
  4137	    raise new_e
  4138	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 464, in _make_request
  4139	    self._validate_conn(conn)
  4140	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 1093, in _validate_conn
  4141	    conn.connect()
  4142	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connection.py", line 759, in connect
  4143	    self.sock = sock = self._new_conn()
  4144	                       ^^^^^^^^^^^^^^^^
  4145	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connection.py", line 211, in _new_conn
  4146	    raise NameResolutionError(self.host, self, e) from e
  4147	urllib3.exceptions.NameResolutionError: HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)
  4148	
  4149	The above exception was the direct cause of the following exception:
  4150	
  4151	Traceback (most recent call last):
  4152	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/adapters.py", line 644, in send
  4153	    resp = conn.urlopen(
  4154	           ^^^^^^^^^^^^^
  4155	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/connectionpool.py", line 841, in urlopen
  4156	    retries = retries.increment(
  4157	              ^^^^^^^^^^^^^^^^^^
  4158	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/urllib3/util/retry.py", line 535, in increment
  4159	    raise MaxRetryError(_pool, url, reason) from reason  # type: ignore[arg-type]
  4160	    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  4161	urllib3.exceptions.MaxRetryError: HTTPSConnectionPool(host='query1.finance.yahoo.com', port=443): Max retries exceeded with url: /v8/finance/chart/SPY?period1=1104537600&period2=1105488000&interval=1d&events=history&includeAdjustedClose=true (Caused by NameResolutionError("HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)"))
  4162	
  4163	During handling of the above exception, another exception occurred:
  4164	
  4165	Traceback (most recent call last):
  4166	  File "<string>", line 1, in <module>
  4167	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/api.py", line 73, in get
  4168	    return request("get", url, params=params, **kwargs)
  4169	           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  4170	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/api.py", line 59, in request
  4171	    return session.request(method=method, url=url, **kwargs)
  4172	           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  4173	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/sessions.py", line 589, in request
  4174	    resp = self.send(prep, **send_kwargs)
  4175	           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  4176	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/sessions.py", line 703, in send
  4177	    r = adapter.send(request, **kwargs)
  4178	        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  4179	  File "/Users/yhlai0911/volpred-research/.venv/lib/python3.12/site-packages/requests/adapters.py", line 677, in send
  4180	    raise ConnectionError(e, request=request)
  4181	requests.exceptions.ConnectionError: HTTPSConnectionPool(host='query1.finance.yahoo.com', port=443): Max retries exceeded with url: /v8/finance/chart/SPY?period1=1104537600&period2=1105488000&interval=1d&events=history&includeAdjustedClose=true (Caused by NameResolutionError("HTTPSConnection(host='query1.finance.yahoo.com', port=443): Failed to resolve 'query1.finance.yahoo.com' ([Errno 8] nodename nor servname provided, or not known)"))
  4182	
  4183	web search: 
  4184	web search: site:fred.stlouisfed.org release Employment Situation May 2006 2006-05-05 2006-05-08 ...
  4185	web search: 
  4186	web search: site:bls.gov/news.release/archives/empsit_08022024.htm ...
  4187	web search: 
  4188	web search: site:bls.gov/news.release/archives/empsit_05052006.htm ...
  4189	web search: 
  4190	web search: https://www.bls.gov/news.release/archives/empsit_05052006.htm
  4191	exec
  4192	/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import json; from pathlib import Path; from volpred.data import event_dates as e; raw=json.loads(Path(\"tests/fixtures/fred_release_50_nfp_raw_20260719.json\").read_text())[\"release_dates\"]; e._fetch=lambda *a,**k:list(raw); got=e.release_dates(\"NFP_US\",\"2005-01-01\",\"2026-07-19\",use_cache=False); six=[str(d.date()) for d in got if str(d.date())[:7] in {\"2006-05\",\"2012-12\",\"2013-05\",\"2020-05\",\"2024-01\",\"2024-08\"}]; print(\"six_selected\",six,\"n\",len(got)); e._fetch=lambda *a,**k:[\"2024-01-05\",\"2024-02-01\",\"2024-02-02\",\"2024-03-08\"]; got=e.release_dates(\"NFP_US\",\"2024-01-01\",\"2024-03-31\",use_cache=False); print(\"earlier_offcycle_silently_selected\",[str(d.date()) for d in got])'
  4193	
  4194	git show 6fd281901:experiments/k528/k528_nfp_event_study.py | PYTHONDONTWRITEBYTECODE=1 python -c 'import sys,ast,pandas as pd; s=sys.stdin.read(); tree=ast.parse(s); fn=next(x for x in tree.body if isinstance(x,ast.FunctionDef) and x.name==\"check_calendar_is_complete\"); ns={\"pd\":pd,\"KNOWN_MISSING_MONTHS\":{\"2025-10\"}}; exec(compile(ast.Module(body=[fn],type_ignores=[]),\"k528\", \"exec\"),ns); f=ns[\"check_calendar_is_complete\"]; print(\"missing_first_month_passes\",f(pd.to_datetime([\"2005-02-04\",\"2005-03-04\"]),\"2005-01-01\",\"2005-03-27\")); print(\"missing_last_full_month_passes\",f(pd.to_datetime([\"2005-01-07\",\"2005-02-04\"]),\"2005-01-01\",\"2005-03-31\")); print(\"known_missing_unbounded\",f(pd.to_datetime([\"2025-09-05\",\"2025-11-20\"]),\"2025-09-01\",\"2025-11-30\"))'
  4195	
  4196	PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess, numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([x[\"event_abs_return\"] for x in d[\"event_data\"]]); wd=np.array([x[\"weekday\"] for x in d[\"event_data\"]]); fri=a[wd==4]; non=a[wd"'!=4]; print("events",len(a),"friday",len(fri),"nonfriday",len(non)); print("means_all_friday_nonfriday",a.mean(),fri.mean(),non.mean()); b=d["main_results"]["friday_baseline_abs_return"]; print("ratios_recomputed",fri.mean()/b,a.mean()/b); print("committed",d["statistical_tests"]["B_nfp_vs_friday"]["vol_ratio"],d["statistical_tests"]["B_nfp_vs_friday"]["p_value"],d["statistical_tests"]["B_diagnostic_mixed_weekday"]["vol_ratio"],d["statistical_tests"]["B_diagnostic_mixed_weekday"]["p_value"]); print("nonfriday_quieter_by_pct",(non.mean()/fri.mean()-1)*100)'"'
  4197	" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  4198	 succeeded in 1617ms:
  4199	six_selected ['2006-05-05', '2012-12-07', '2013-05-03', '2020-05-08', '2024-01-05', '2024-08-02'] n 258
  4200	earlier_offcycle_silently_selected ['2024-01-05', '2024-02-01', '2024-03-08']
  4201	missing_first_month_passes {'n_months_expected': 1, 'known_missing_months': ['2025-10']}
  4202	missing_last_full_month_passes {'n_months_expected': 1, 'known_missing_months': ['2025-10']}
  4203	known_missing_unbounded {'n_months_expected': 1, 'known_missing_months': ['2025-10']}
  4204	events 253 friday 237 nonfriday 16
  4205	means_all_friday_nonfriday 0.008453062192235669 0.008540928249020233 0.0071515462261143095
  4206	ratios_recomputed 1.1901328478556155 1.177889180968137
  4207	committed 1.1901328478556155 0.020198459584478665 1.177889180968137 0.024879138655181043
  4208	nonfriday_quieter_by_pct -16.267342171681463
  4209	
  4210	exec
  4211	/bin/zsh -lc "git show 6fd281901:experiments/k528/build_article_correction.py | nl -ba | sed -n '1,320p'
  4212	git show 6fd281901:experiments/k528/README.md | nl -ba | sed -n '1,240p'
  4213	git show 6fd281901:experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json | jq '{superseded,do_not_cite,superseded_at,superseded_by,retraction_reason,note_for_machines,audit_artifact}'
  4214	git show 6fd281901:experiments/k528/review_verdict.json | jq '.'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  4215	 succeeded in 0ms:
  4216	     1	"""Build and validate the in-place correction to mile_35eef830.
  4217	     2	
  4218	     3	The article was published 2026-07-01 with headline numbers taken from K528,
  4219	     4	which dated every NFP to the first Friday of the month. On the official BLS
  4220	     5	calendar that proxy is wrong for ~20% of the sample, so every number moved a
  4221	     6	little. This script restates them.
  4222	     7	
  4223	     8	WHAT CHANGED SINCE THE VOIDED 2026-07-19 CORRECTION LIST
  4224	     9	--------------------------------------------------------
  4225	    10	An earlier 18-item list was built against a contaminated rerun and has been
  4226	    11	VOIDED IN FULL. That rerun used an event-date accessor which, for the six
  4227	    12	months where ALFRED returns two entries, picked the LATER one -- an off-cycle
  4228	    13	seasonal-factor revision rather than the Employment Situation report. Six event
  4229	    14	dates were therefore wrong (2006-05-08, 2012-12-12, 2013-05-06, 2020-05-11,
  4230	    15	2024-01-10, 2024-08-21).
  4231	    16	
  4232	    17	That mattered far more than six dates out of 253 suggests, because it moved the
  4233	    18	NFP-vs-Friday test across the 5% line. The voided list told readers that a
  4234	    19	result the article reported as significant was in fact not significant
  4235	    20	(1.17x p=0.0335 -> "1.15x p=0.057, 差一點過線但沒過"). On correct dates the
  4236	    21	comparison is 1.19x at p=0.020 -- significant, exactly as the article
  4237	    22	originally said. Applying that list would have published a retraction of a
  4238	    23	correct finding.
  4239	    24	
  4240	    25	So: no claim in this article reverses direction. Every replacement below is a
  4241	    26	numeric restatement, plus one estimand refinement that is disclosed in the note.
  4242	    27	
  4243	    28	THE ONE ESTIMAND CHANGE
  4244	    29	-----------------------
  4245	    30	Under the proxy every NFP landed on a Friday by construction, so "NFP days vs
  4246	    31	non-NFP Fridays" held weekday fixed for free. On the official calendar 16 of
  4247	    32	253 events are not Fridays, so that same comparison would put a weekday-mixed
  4248	    33	event group against a pure-Friday control group and let the Friday effect leak
  4249	    34	into the estimate. The corrected test restricts the event group to the 237
  4250	    35	Friday releases. This is stated in the article's correction note rather than
  4251	    36	folded in silently.
  4252	    37	
  4253	    38	WHY THIS SCRIPT DOES NOT WRITE BY DEFAULT
  4254	    39	-----------------------------------------
  4255	    40	`storage/reports/feed.json` is shared canonical state. `.claude/rules/worktree.md`
  4256	    41	forbids a worktree agent from touching it, and the reason is mechanical rather
  4257	    42	than ceremonial: this worktree carries its own 15MB checkout of feed.json, so a
  4258	    43	write here lands on a branch copy that is already stale the moment any other
  4259	    44	article is published, and merging it would silently revert them.
  4260	    45	
  4261	    46	So the split is: this script (run from the worktree) resolves and VALIDATES
  4262	    47	every replacement against the canonical article, proving each matches exactly
  4263	    48	once before anything is written. The main thread then runs it with --apply from
  4264	    49	the repo root, where the write is legitimate.
  4265	    50	
  4266	    51	    uv run python experiments/k528/build_article_correction.py            # validate, writes nothing
  4267	    52	    uv run python experiments/k528/build_article_correction.py --apply    # write + sync
  4268	    53	
  4269	    54	Validation uses `article_correction._splice`, the same resolver the writer
  4270	    55	uses, so a plan that validates here cannot fail differently there.
  4271	    56	"""
  4272	    57	
  4273	    58	from __future__ import annotations
  4274	    59	
  4275	    60	import argparse
  4276	    61	import json
  4277	    62	import os
  4278	    63	import tempfile
  4279	    64	from pathlib import Path
  4280	    65	
  4281	    66	REPO_ROOT = Path(__file__).resolve().parents[2]
  4282	    67	ARTICLE_ID = "mile_35eef830"
  4283	    68	AUDIT_PATH = Path(__file__).parent / "k528_nfp_official_dates_results.json"
  4284	    69	
  4285	    70	# The 18-item list built on 2026-07-19 against the contaminated rerun. Kept as a
  4286	    71	# record of what must NOT be applied, not as a fallback -- see the module
  4287	    72	# docstring. Anything that resurrects these strings is reintroducing a
  4288	    73	# retraction of a correct finding.
  4289	    74	VOIDED_20260719_LIST_SIZE = 18
  4290	    75	
  4291	    76	# (old, new). Each `old` must occur exactly once in the article body; the
  4292	    77	# resolver rejects the whole batch otherwise. Ordered as they appear.
  4293	    78	REPLACEMENTS: list[tuple[str, str]] = [
  4294	    79	    # --- sample size: 254 -> 253 ---
  4295	    80	    (
  4296	    81	        "總共 254 次 NFP 公布日的資料算過一遍",
  4297	    82	        "總共 253 次 NFP 公布日的資料算過一遍",
  4298	    83	    ),
  4299	    84	    # --- 1.10x -> 1.11x vs all non-NFP days (direction unchanged: NOT significant) ---
  4300	    85	    (
  4301	    86	        "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
  4302	    87	        "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
  4303	    88	    ),
  4304	    89	    (
  4305	    90	        "換句話說，這 1.10 倍的差距",
  4306	    91	        "換句話說，這 1.11 倍的差距",
  4307	    92	    ),
  4308	    93	    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
  4309	    94	    (
  4310	    95	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，"
  4311	    96	        "用 Welch t 檢定算下來，這個差距達到顯著水準。"
  4312	    97	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  4313	    98	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場"
  4314	    99	        "落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致："
  4315	   100	        "這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。"
  4316	   101	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  4317	   102	    ),
  4318	   103	    (
  4319	   104	        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
  4320	   105	        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
  4321	   106	        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；"
  4322	   107	        "但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
  4323	   108	    ),
  4324	   109	    # --- regime split: threshold, group sizes, means, ratio ---
  4325	   110	    (
  4326	   111	        "那 254 次 NFP 日裡",
  4327	   112	        "那 253 次 NFP 日裡",
  4328	   113	    ),
  4329	   114	    (
  4330	   115	        "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
  4331	   116	        "分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；"
  4332	   117	        "VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
  4333	   118	        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
  4334	   119	        "分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；"
  4335	   120	        "VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
  4336	   121	    ),
  4337	   122	    # --- VIX correlation ---
  4338	   123	    (
  4339	   124	        "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
  4340	   125	        "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
  4341	   126	    ),
  4342	   127	    (
  4343	   128	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
  4344	   129	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
  4345	   130	    ),
  4346	   131	    # --- figure caption ---
  4347	   132	    (
  4348	   133	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
  4349	   134	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
  4350	   135	    ),
  4351	   136	    # --- the worked example: 2026-07-01 VIX 16.59 vs the threshold (still low regime) ---
  4352	   137	    (
  4353	   138	        "貼在歷史分界線 16.71 的下緣",
  4354	   139	        "貼在歷史分界線 16.69 的下緣",
  4355	   140	    ),
  4356	   141	    (
  4357	   142	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
  4358	   143	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
  4359	   144	    ),
  4360	   145	    (
  4361	   146	        "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
  4362	   147	        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
  4363	   148	    ),
  4364	   149	    # --- conclusions section (direction unchanged on both baselines) ---
  4365	   150	    (
  4366	   151	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
  4367	   152	        "對週五基準是 1.17 倍、達到顯著水準。",
  4368	   153	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準，"
  4369	   154	        "對週五基準是 1.19 倍、達到顯著水準。",
  4370	   155	    ),
  4371	   156	    (
  4372	   157	        "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
  4373	   158	        "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
  4374	   159	    ),
  4375	   160	    (
  4376	   161	        "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
  4377	   162	        "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
  4378	   163	    ),
  4379	   164	    (
  4380	   165	        "254 場歷史樣本加上 7/2 這場實測",
  4381	   166	        "253 場歷史樣本加上 7/2 這場實測",
  4382	   167	    ),
  4383	   168	    # --- methodology section + reader-facing errata ---
  4384	   169	    (
  4385	   170	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，"
  4386	   171	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
  4387	   172	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
  4388	   173	        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
  4389	   174	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n"
  4390	   175	        "**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。"
  4391	   176	        "與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，"
  4392	   177	        "遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，"
  4393	   178	        "但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n"
  4394	   179	        "**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、"
  4395	   180	        "真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整"
  4396	   181	        "（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。"
  4397	   182	        "另有一項口徑調整：初版的 NFP 全部落在週五，週五基準比較是同星期別對同星期別；"
  4398	   183	        "官方日曆下有 16 場不在週五，因此該比較改為只取在週五公布的 237 場，維持兩邊星期別一致。\n\n"
  4399	   184	        "**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。"
  4400	   185	        "逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
  4401	   186	    ),
  4402	   187	    (
  4403	   188	        "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
  4404	   189	        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
  4405	   190	    ),
  4406	   191	]
  4407	   192	
  4408	   193	
  4409	   194	def load_article_content(storage_dir: Path) -> str:
  4410	   195	    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
  4411	   196	    art = next((a for a in feed if isinstance(a, dict) and a.get("id") == ARTICLE_ID), None)
  4412	   197	    if art is None:
  4413	   198	        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
  4414	   199	    return art.get("content") or ""
  4415	   200	
  4416	   201	
  4417	   202	def validate(storage_dir: Path) -> list[dict]:
  4418	   203	    """Resolve every replacement against the live article. Raises if any does
  4419	   204	    not match exactly once, before a single byte is written."""
  4420	   205	    from volpred.publisher.article_correction import _splice
  4421	   206	
  4422	   207	    content = load_article_content(storage_dir)
  4423	   208	    spans = _splice(content, REPLACEMENTS)
  4424	   209	    return [
  4425	   210	        {"index": i, "hits": 1, "from": s["from"], "to": s["to"], "offset": s["start"]}
  4426	   211	        for i, s in enumerate(sorted(spans, key=lambda x: x["start"]))
  4427	   212	    ]
  4428	   213	
  4429	   214	
  4430	   215	def _write_json_atomic(path: Path, payload) -> None:
  4431	   216	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
  4432	   217	    try:
  4433	   218	        with os.fdopen(fd, "w", encoding="utf-8") as f:
  4434	   219	            json.dump(payload, f, indent=2, ensure_ascii=False)
  4435	   220	            f.write("\n")
  4436	   221	            f.flush()
  4437	   222	            os.fsync(f.fileno())
  4438	   223	        os.replace(tmp, path)
  4439	   224	    except BaseException:
  4440	   225	        try:
  4441	   226	            os.unlink(tmp)
  4442	   227	        except FileNotFoundError:
  4443	   228	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
  4444	   229	        raise
  4445	   230	
  4446	   231	
  4447	   232	def record_plan(validated: list[dict], applied: dict | None) -> None:
  4448	   233	    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
  4449	   234	    audit["article_correction"] = {
  4450	   235	        "article_id": ARTICLE_ID,
  4451	   236	        "status": "applied" if applied else "validated_not_applied",
  4452	   237	        "n_replacements": len(REPLACEMENTS),
  4453	   238	        "all_matched_exactly_once": True,
  4454	   239	        "supersedes": {
  4455	   240	            "voided_list_size": VOIDED_20260719_LIST_SIZE,
  4456	   241	            "voided_at": "2026-07-19",
  4457	   242	            "reason": (
  4458	   243	                "the 18-item list was built against a rerun whose accessor picked "
  4459	   244	                "off-cycle ALFRED entries for six months, which pushed the "
  4460	   245	                "NFP-vs-Friday test across the 5% line. It would have retracted a "
  4461	   246	                "finding that is in fact correct."
  4462	   247	            ),
  4463	   248	        },
  4464	   249	        "directional_claims_changed": 0,
  4465	   250	        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
  4466	   251	        "apply_result": applied,
  4467	   252	        "residual_gap": (
  4468	   253	            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
  4469	   254	            "and the two lazypack images still render proxy-era numbers. Text and images "
  4470	   255	            "now disagree; the article carries a visible note saying so. Regenerating and "
  4471	   256	            "re-uploading them is follow-up work outside this worktree's scope."
  4472	   257	        ),
  4473	   258	    }
  4474	   259	    _write_json_atomic(AUDIT_PATH, audit)
  4475	   260	
  4476	   261	
  4477	   262	def main() -> int:
  4478	   263	    ap = argparse.ArgumentParser(description=__doc__)
  4479	   264	    ap.add_argument("--apply", action="store_true",
  4480	   265	                    help="write the correction (main thread, repo root only)")
  4481	   266	    ap.add_argument("--record-plan", action="store_true",
  4482	   267	                    help="record the validated plan into the audit JSON without applying it")
  4483	   268	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
  4484	   269	    args = ap.parse_args()
  4485	   270	
  4486	   271	    storage_dir = Path(args.storage_dir)
  4487	   272	    validated = validate(storage_dir)
  4488	   273	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
  4489	   274	    for v in validated:
  4490	   275	        head = v["from"].splitlines()[0][:64]
  4491	   276	        print(f"  @{v['offset']:>6}  {head}...")
  4492	   277	
  4493	   278	    applied = None
  4494	   279	    if args.apply:
  4495	   280	        from volpred.publisher.article_correction import apply_article_correction
  4496	   281	
  4497	   282	        applied = apply_article_correction(
  4498	   283	            ARTICLE_ID,
  4499	   284	            content_replacements=REPLACEMENTS,
  4500	   285	            summary=(
  4501	   286	                "K528 event dates corrected from a first-Friday proxy to the official BLS "
  4502	   287	                "release calendar. Sample 254 -> 253 events; headline numbers restated "
  4503	   288	                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
  4504	   289	                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
  4505	   290	                "now restricts the event group to the 237 Friday releases so weekday is "
  4506	   291	                "held fixed on both sides."
  4507	   292	            ),
  4508	   293	            action="content_correction",
  4509	   294	            storage_dir=str(storage_dir),
  4510	   295	        )
  4511	   296	        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
  4512	   297	              f"synced={applied['synced']}")
  4513	   298	
  4514	   299	    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
  4515	   300	    # finding 7). Recording is opt-in and never implicit.
  4516	   301	    if args.apply or args.record_plan:
  4517	   302	        record_plan(validated, applied)
  4518	   303	        print(f"plan recorded in {AUDIT_PATH.name}")
  4519	   304	    else:
  4520	   305	        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
  4521	   306	              "or --record-plan to persist the validated plan only.")
  4522	   307	    return 0
  4523	   308	
  4524	   309	
  4525	   310	if __name__ == "__main__":
  4526	   311	    raise SystemExit(main())
  4527	     1	# k528 — NFP 事件研究（SPY 波動率）
  4528	     2	
  4529	     3	- Experiment ID: `k528`
  4530	     4	- Created At: 2026-04-16T09:39:52.904348+00:00
  4531	     5	- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑；同日第二次修正見下）
  4532	     6	- Status: 已重跑，**方向性結論全部不變**，僅數值微調 + 一項口徑澄清
  4533	     7	
  4534	     8	## 問題描述
  4535	     9	
  4536	    10	NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
  4537	    11	事件本身」，還是「進場當下的市場狀態」？
  4538	    12	
  4539	    13	## 兩次修正，不要混為一談
  4540	    14	
  4541	    15	本實驗在 2026-07-19 被修正了**兩次**，第二次是修第一次修壞的地方。
  4542	    16	
  4543	    17	### 修正 1：事件日期從 proxy 換成官方日曆
  4544	    18	
  4545	    19	原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：
  4546	    20	
  4547	    21	- BLS 在參考週較晚的月份會改到**第二個週五**發布
  4548	    22	- 遇到聯邦假期會**提前**
  4549	    23	- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
  4550	    24	- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 237 場在週五
  4551	    25	
  4552	    26	錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
  4553	    27	同時把真的事件日丟進對照組。這是修正存在的理由。
  4554	    28	
  4555	    29	`get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
  4556	    30	`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
  4557	    31	release id 50），且**取不到就 raise，不回退 proxy**。
  4558	    32	
  4559	    33	### 修正 2（本輪）：accessor 的同月多筆選擇錯誤
  4560	    34	
  4561	    35	第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
  4562	    36	在**六個月份**會回兩筆：前一筆是 Employment Situation 正式報告，後一筆是年度季節調整
  4563	    37	因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：
  4564	    38	
  4565	    39	| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
  4566	    40	|---|---|---|
  4567	    41	| 2006-05 | 2006-05-05 | 2006-05-08 |
  4568	    42	| 2012-12 | 2012-12-07 | 2012-12-12 |
  4569	    43	| 2013-05 | 2013-05-03 | 2013-05-06 |
  4570	    44	| 2020-05 | 2020-05-08 | 2020-05-11 |
  4571	    45	| 2024-01 | 2024-01-05 | 2024-01-10 |
  4572	    46	| 2024-08 | 2024-08-02 | 2024-08-21 |
  4573	    47	
  4574	    48	六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
  4575	    49	**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
  4576	    50	那 18 條會把一個本來正確的結論撤回。** Codex 二審判 FAIL 擋下，未套用。
  4577	    51	
  4578	    52	根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
  4579	    53	fail-closed 驗證，commit `305d118a3`）。
  4580	    54	
  4581	    55	**為什麼原本 42 個測試全綠卻沒抓到**：fixture 是手寫的，同月第二筆事先就被刪掉了 ——
  4582	    56	測試餵進去的輸入根本表達不出這個 bug。修法不是加更好的斷言，是餵真實輸入：
  4583	    57	`tests/test_event_dates_real_raw_response.py` 直接釘住 ALFRED 的 264 筆原始回應
  4584	    58	（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
  4585	    59	那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。
  4586	    60	
  4587	    61	## 方法
  4588	    62	
  4589	    63	- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
  4590	    64	- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
  4591	    65	- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
  4592	    66	- 檢定：Welch t（vs 全體非 NFP 日 / vs 非 NFP 週五）、Mann-Whitney U、
  4593	    67	  VIX 中位數分組 regime 檢定、Pearson / Spearman 相關
  4594	    68	
  4595	    69	### 週五基準的口徑（estimand）調整
  4596	    70	
  4597	    71	proxy 下每一場 NFP 都是週五，「NFP vs 非 NFP 週五」自動就是同星期別對同星期別。
  4598	    72	官方日曆下有 16 場不在週五，若沿用原寫法，就變成**星期別混合的事件組**對**純週五的
  4599	    73	對照組**，週五本身的波動特性會直接混進 p 值。
  4600	    74	
  4601	    75	本輪把事件組**限定為在週五公布的 237 場**，兩邊星期別一致。另一個選項是保留全部 253 場
  4602	    76	改用 weekday-matched controls，未採用的理由：非週五事件是週四 8、週二 2、週三 1，
  4603	    77	用這種格數做加權平均，標準誤會被 1 筆的週三格主導 —— 那是對一個更難陳述的量做更吵的估計。
  4604	    78	被排除的 16 場以描述統計另行報告（平均 |ret| 0.715%），不是靜默丟掉。
  4605	    79	
  4606	    80	原口徑（全部事件 vs 非 NFP 週五）以 `B_diagnostic_mixed_weekday` 保留在結果檔中，
  4607	    81	標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。
  4608	    82	
  4609	    83	## 結果：逐項前後對照
  4610	    84	
  4611	    85	每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
  4612	    86	而中位數與勝率在底下已經移位。
  4613	    87	
  4614	    88	| 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
  4615	    89	|---|---|---|---|
  4616	    90	| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
  4617	    91	| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.108× (p=0.112, NS) | 數值微調 |
  4618	    92	| ↳ 中位數比 / 勝率 | 1.190× / 0.555 | 1.193× / 0.561 | 數值微調 |
  4619	    93	| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.190× (p=0.0202, **仍顯著**) | 數值微調（口徑見上） |
  4620	    94	| ↳ 中位數比 / 勝率 | 1.209× / 0.563 | 1.223× / 0.570 | 數值微調 |
  4621	    95	| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
  4622	    96	| ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
  4623	    97	| 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
  4624	    98	| ↳ Spearman | 0.377 | 0.346 | 數值微調 |
  4625	    99	| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
  4626	   100	
  4627	   101	**6 項受稽核宣稱中，0 項結論翻轉。**
  4628	   102	
  4629	   103	參考：若沿用修正前的舊口徑（全部 253 場 vs 非 NFP 週五），數值為 1.178×、p=0.0249 ——
  4630	   104	同樣顯著。也就是說**「顯著→不顯著」的翻轉在任何一種口徑下都不成立**，那是六個錯誤
  4631	   105	日期造成的假象。
  4632	   106	
  4633	   107	**方向性主結論不變**：決定 NFP 日波動的是**進場當下的 VIX 體制**（2.03 倍、p≈4.6e-9），
  4634	   108	遠大於 NFP 這個日曆事件本身。
  4635	   109	
  4636	   110	### 關於「不顯著」的措辭
  4637	   111	
  4638	   112	修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
  4639	   113	Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
  4640	   114	陳述都綁定它自己的檢定：
  4641	   115	
  4642	   116	- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
  4643	   117	- Welch 平均差（週五對週五）：1.190×，p=0.0202，**拒絕**
  4644	   118	- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019，**拒絕**
  4645	   119	
  4646	   120	平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
  4647	   121	排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。
  4648	   122	
  4649	   123	## 產出檔案
  4650	   124	
  4651	   125	| 檔案 | 內容 |
  4652	   126	|---|---|
  4653	   127	| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
  4654	   128	| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
  4655	   129	| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
  4656	   130	| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 換掉的日期 + 文章更正替換清單 |
  4657	   131	| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
  4658	   132	| `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
  4659	   133	| `review_verdict_v3.json` / `codex_review_v3.md` | Codex 三審裁決與全文 |
  4660	   134	
  4661	   135	## 線上文章更正（`mile_35eef830`）
  4662	   136	
  4663	   137	### ⚠️ 原 18 條更正清單已全數作廢
  4664	   138	
  4665	   139	原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
  4666	   140	改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
  4667	   141	撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
  4668	   142	`article_correction.supersedes`。
  4669	   143	
  4670	   144	### 新清單：19 條，全部是數值重述，0 條方向翻轉
  4671	   145	
  4672	   146	文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
  4673	   147	差距的是進場 VIX 體制 —— 在官方日期下**全部成立**。新清單只改數字
  4674	   148	（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
  4675	   149	外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
  4676	   150	
  4677	   151	19 條已對線上 canonical 文章驗證，全部恰好命中一次。
  4678	   152	
  4679	   153	```bash
  4680	   154	# 主線程在 repo root 執行
  4681	   155	uv run python experiments/k528/build_article_correction.py            # 驗證（不寫任何檔）
  4682	   156	uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
  4683	   157	```
  4684	   158	
  4685	   159	**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
  4686	   160	`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
  4687	   161	自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
  4688	   162	合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。
  4689	   163	
  4690	   164	**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
  4691	   165	與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
  4692	   166	因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。
  4693	   167	
  4694	   168	## 防迴歸
  4695	   169	
  4696	   170	事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
  4697	   171	
  4698	   172	- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
  4699	   173	  212 個日期共通、結果檔宣告 fail-closed
  4700	   174	- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住本輪 BLOCKER**：
  4701	   175	  對 artifact 斷言六個 off-cycle 日期不在事件集合、六個正式發布日在。對 artifact 而非
  4702	   176	  只對 accessor 斷言，因為「accessor 是對的」不能證明「出貨的結果用了它」
  4703	   177	- `TestProxyMutationIsCaught` — mutation test：proxy 日曆餵給 guard 必須被拒；
  4704	   178	  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆
  4705	   179	
  4706	   180	accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
  4707	   181	`tests/test_event_dates_real_raw_response.py`（真實 raw response + mutation 檢查）。
  4708	   182	
  4709	   183	Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
  4710	   184	由綠轉紅（`2006-05-08 != 2006-05-05`），還原後 51 passed。沒被實際觸發過的 gate 不算 gate。
  4711	   185	
  4712	   186	## 主腳本的 fail-closed 面
  4713	   187	
  4714	   188	- **日曆完整性**（`check_calendar_is_complete`）：同月多筆 → raise；樣本窗內缺月 → raise。
  4715	   189	  已知的真實缺口只有 2025-10（政府關門，ALFRED 在 2025-09-05 與 2025-11-20 之間 76 天無
  4716	   190	  條目），寫在 `KNOWN_MISSING_MONTHS` 並附理由 —— 這個清單是用來記錄真實缺口的，
  4717	   191	  不是用來讓檢查通過的
  4718	   192	- **事件日→交易日對映**：一對一完整性斷言。樣本內發布日找不到三日內交易日 → raise；
  4719	   193	  兩個發布日映射到同一個 session → raise（原本的 `set()` 去重會把這件事藏起來並靜默減少
  4720	   194	  事件數）。窗口邊界排除改為明確記錄在 `sample.event_mapping_audit`，不再靜默 `continue`
  4721	   195	- **原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`
  4722	   196	
  4723	   197	## 參考
  4724	   198	
  4725	   199	- K1442 事件日期稽核（發現 proxy bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
  4726	   200	- `docs/error_log.md` 2026-07-12 CPI 事件研究發布日條目（同一 bug class 的前例）
  4727	   201	- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
  4728	   202	- K513：先前的 FOMC/NFP/CPI 事件研究
  4729	{
  4730	  "superseded": true,
  4731	  "do_not_cite": true,
  4732	  "superseded_at": "2026-07-19",
  4733	  "superseded_by": "k528_nfp_event_study_results.json",
  4734	  "retraction_reason": "The first-Friday-of-month rule is wrong for roughly 20% of the sample and wrong SYSTEMATICALLY, not randomly: BLS moves the release to the second Friday when the reference week falls late, pulls it forward around holidays, and did not publish at all in 2025-10 during the federal shutdown -- for which this proxy invented an event day that never existed. Wrong event dates do not fail loudly: they count quiet days as event days and dump real event days into the control group, and every figure still renders.",
  4735	  "note_for_machines": "This object exists so the file is identifiable as retracted WITHOUT relying on its filename or on README prose (k528 Codex v2 finding 8). If you are reading this key, do not use any number in this file.",
  4736	  "audit_artifact": "k528_nfp_official_dates_results.json"
  4737	}
  4738	{
  4739	  "kid": "k528",
  4740	  "verdict": "FAIL",
  4741	  "reviewer": "Codex gpt-5.6-sol / high (re-run after first review never wrote verdict)",
  4742	  "reviewed_at": "2026-07-19T13:15:30+08:00",
  4743	  "reviewed_commit": "af2fad3569347e728b6fa29c90ddea38bf500e05",
  4744	  "review_artifact": "experiments/k528/codex_review_v2.md",
  4745	  "blocking_defects": [
  4746	    "official-calendar accessor picks 6 wrong event dates: max() over multiple same-month FRED release-id-50 entries mistakes off-cycle releases for NFP (event_dates.py:96)",
  4747	    "core sig->NS flip does not hold with correct dates (1.1779x, p~0.0249 still significant) — the 18 article corrections are contaminated and must not be applied",
  4748	    "fail-closed incomplete: only all-empty month errors; partial/ambiguous calendar passes silently (event_dates.py:121)"
  4749	  ],
  4750	  "reviewed_sha256": {
  4751	    "README.md": "a51a9c6a6abe9667fd86e58ad27a641d6732f5a6fccdc8e4e741ec1dec936083",
  4752	    "build_article_correction.py": "922805051b2fa064b433485093b40b0e4677b69ea0e813e1576e6c02428fd6c9",
  4753	    "k528_nfp_event_study.py": "d27afe1b822034272ae6c44493af092405e95cb55370651dda9734e7f1d2944a",
  4754	    "k528_nfp_event_study_results.json": "84070e93f77f02abac8c5660e897e6093c6fb6835b3df520bb10dc33d7dde339",
  4755	    "k528_nfp_official_dates_results.json": "41440b18d33134ad87772dafcbae0fc9603d1a5e53297111f1b6d76855040911"
  4756	  }
  4757	}
  4758	
  4759	exec
  4760	/bin/zsh -lc "git show 6fd281901:tests/test_nfp_official_release_dates.py | nl -ba | sed -n '300,620p'
  4761	PYTHONDONTWRITEBYTECODE=1 python experiments/k528/build_article_correction.py --storage-dir /Users/yhlai0911/volpred-research/storage
  4762	
  4763	git show 6fd281901:experiments/k528/build_article_correction.py | PYTHONDONTWRITEBYTECODE=1 python -c 'import sys,ast; s=sys.stdin.read(); t=ast.parse(s); a=next(x for x in t.body if isinstance(x,ast.AnnAssign) and getattr(x.target,\"id\",None)==\"REPLACEMENTS\"); reps=ast.literal_eval(a.value); print(\"n_replacements\",len(reps)); print(\"distinct_old\",len({x for x,_ in reps}),\"distinct_new\",len({x for _,x in reps}))'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  4764	 succeeded in 139ms:
  4765	validated 19/19 replacements, each matched exactly once
  4766	  @   416  總共 254 次 NFP 公布日的資料算過一遍...
  4767	  @   506  NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。...
  4768	  @   600  換句話說，這 1.10 倍的差距...
  4769	  @   698  VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t ...
  4770	  @   833  所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1...
  4771	  @  1132  那 254 次 NFP 日裡...
  4772	  @  1159  VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71...
  4773	  @  1395  相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）...
  4774	  @  1480  VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。...
  4775	  @  1717  ![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]...
  4776	  @  1923  貼在歷史分界線 16.71 的下緣...
  4777	  @  2057  落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。...
  4778	  @  2352  7/1 收盤的 16.59 距離 16.71 只差 0.12 點...
  4779	  @  2487  第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。...
  4780	  @  2625  高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。...
  4781	  @  2760  這跟 k528 在 254 場歷史樣本上得到的傾向一致...
  4782	  @  3014  254 場歷史樣本加上 7/2 這場實測...
  4783	  @  3131  樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinan...
  4784	  @  3383  VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；...
  4785	
  4786	dry run -- nothing written. Re-run with --apply from the repo root, or --record-plan to persist the validated plan only.
  4787	n_replacements 19
  4788	distinct_old 19 distinct_new 19
  4789	
  4790	exec
  4791	/bin/zsh -lc "git show 6fd281901:experiments/k528/codex_review_v2.md | nl -ba | sed -n '4980,5035p'
  4792	git show 6fd281901:experiments/k528/README.md | rg -n \"11|16|239|254|Friday|週五|apples|原口徑|flip|翻轉|insignificant\"
  4793	git show 6fd281901:experiments/k528/k528_nfp_event_study_results.json | rg -n \"11 non-Friday|16|DIAGNOSTIC|1.190132|1.177889|insignificant\"
  4794	git show 6fd281901:tests/test_nfp_official_release_dates.py | rg -n \"0.0571|stopped being significant|all-Friday|gap is the corrected dates|first-Friday\"" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  4795	 succeeded in 0ms:
  4796	  4980	  ✓ 讀取 handoff、error log 與 K528 審查檔案
  4797	  4981	  ✓ 驗證官方日期 fail-closed、事件對齊與統計重算
  4798	  4982	  ✓ 逐條比對 18 條文章更正並審查新舊結果揭露
  4799	  4983	  ✓ 檢查 lookahead、seed、原子寫入並形成裁決
  4800	  4984	codex
  4801	  4985	1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
  4802	  4986	
  4803	  4987	2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
  4804	  4988	
  4805	  4989	3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。
  4806	  4990	
  4807	  4991	4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。
  4808	  4992	
  4809	  4993	5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。
  4810	  4994	
  4811	  4995	6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。
  4812	  4996	
  4813	  4997	7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。
  4814	  4998	
  4815	  4999	8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。
  4816	  5000	
  4817	  5001	9. **防錯核對：** `pre_vix` 正確取自 T−1（[k528_nfp_event_study.py:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:163)、[k528_nfp_event_study.py:182](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:182)），未見交易 lookahead。本實驗沒有 bootstrap、抽樣或 Monte Carlo，seed 不適用。
  4818	  5002	
  4819	  5003	Blocking defects：官方 accessor 把 off-cycle entries 當 NFP；錯誤日期直接否定核心顯著性翻轉及 18 條文章更正；partial／ambiguous calendar 亦未真正 fail-closed。
  4820	  5004	
  4821	  5005	VERDICT: FAIL
  4822	  5006	tokens used
  4823	  5007	140,901
  4824	  5008	1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
  4825	  5009	
  4826	  5010	2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
  4827	  5011	
  4828	  5012	3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。
  4829	  5013	
  4830	  5014	4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。
  4831	  5015	
  4832	  5016	5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。
  4833	  5017	
  4834	  5018	6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。
  4835	  5019	
  4836	  5020	7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。
  4837	  5021	
  4838	  5022	8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。
  4839	  5023	
  4840	  5024	9. **防錯核對：** `pre_vix` 正確取自 T−1（[k528_nfp_event_study.py:163](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:163)、[k528_nfp_event_study.py:182](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:182)），未見交易 lookahead。本實驗沒有 bootstrap、抽樣或 Monte Carlo，seed 不適用。
  4841	  5025	
  4842	  5026	Blocking defects：官方 accessor 把 off-cycle entries 當 NFP；錯誤日期直接否定核心顯著性翻轉及 18 條文章更正；partial／ambiguous calendar 亦未真正 fail-closed。
  4843	  5027	
  4844	  5028	VERDICT: FAIL
  4845	4:- Created At: 2026-04-16T09:39:52.904348+00:00
  4846	19:原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：
  4847	21:- BLS 在參考週較晚的月份會改到**第二個週五**發布
  4848	24:- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 237 場在週五
  4849	44:| 2020-05 | 2020-05-08 | 2020-05-11 |
  4850	48:六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
  4851	49:**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
  4852	52:根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
  4853	53:fail-closed 驗證，commit `305d118a3`）。
  4854	66:- 檢定：Welch t（vs 全體非 NFP 日 / vs 非 NFP 週五）、Mann-Whitney U、
  4855	69:### 週五基準的口徑（estimand）調整
  4856	71:proxy 下每一場 NFP 都是週五，「NFP vs 非 NFP 週五」自動就是同星期別對同星期別。
  4857	72:官方日曆下有 16 場不在週五，若沿用原寫法，就變成**星期別混合的事件組**對**純週五的
  4858	73:對照組**，週五本身的波動特性會直接混進 p 值。
  4859	75:本輪把事件組**限定為在週五公布的 237 場**，兩邊星期別一致。另一個選項是保留全部 253 場
  4860	76:改用 weekday-matched controls，未採用的理由：非週五事件是週四 8、週二 2、週三 1，
  4861	78:被排除的 16 場以描述統計另行報告（平均 |ret| 0.715%），不是靜默丟掉。
  4862	80:原口徑（全部事件 vs 非 NFP 週五）以 `B_diagnostic_mixed_weekday` 保留在結果檔中，
  4863	81:標明 **DIAGNOSTIC ONLY、不可引用**，只用於和修正前做 apples-to-apples 對照。
  4864	90:| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
  4865	91:| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.108× (p=0.112, NS) | 數值微調 |
  4866	93:| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.190× (p=0.0202, **仍顯著**) | 數值微調（口徑見上） |
  4867	95:| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
  4868	99:| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
  4869	101:**6 項受稽核宣稱中，0 項結論翻轉。**
  4870	103:參考：若沿用修正前的舊口徑（全部 253 場 vs 非 NFP 週五），數值為 1.178×、p=0.0249 ——
  4871	104:同樣顯著。也就是說**「顯著→不顯著」的翻轉在任何一種口徑下都不成立**，那是六個錯誤
  4872	112:修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
  4873	116:- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
  4874	117:- Welch 平均差（週五對週五）：1.190×，p=0.0202，**拒絕**
  4875	139:原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
  4876	144:### 新清單：19 條，全部是數值重述，0 條方向翻轉
  4877	146:文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
  4878	148:（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
  4879	149:外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
  4880	172:- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
  4881	189:  已知的真實缺口只有 2025-10（政府關門，ALFRED 在 2025-09-05 與 2025-11-20 之間 76 天無
  4882	4:  "date": "2026-07-19T08:16:52.820209+00:00",
  4883	44:    "vol_ratio_vs_friday": 1.1901328478556155
  4884	55:      "estimand": "weekday held fixed on both sides. Event group restricted to NFP releases that trade on a Friday; the 11 non-Friday events are excluded rather than compared against a pure-Friday control group.",
  4885	58:      "vol_ratio": 1.1901328478556155,
  4886	63:        "n": 16,
  4887	69:      "status": "DIAGNOSTIC ONLY - do not quote",
  4888	71:      "vol_ratio": 1.177889180968137,
  4889	95:      "spearman_rho": 0.3455048873701663,
  4890	111:      "mean_abs_return": 0.009459292256163645,
  4891	125:      "mean_abs_return": 0.008502231669747567,
  4892	132:      "mean_abs_return": 0.010016738048407288,
  4893	140:      "vol_ratio": 1.297816321779998,
  4894	167:      "mean_abs_return": 0.007168557128140611,
  4895	182:      "vol_ratio": 0.8727716688091264,
  4896	184:      "p_val": 0.5675916686325496
  4897	188:      "mean_abs_return": 0.006880289163056845,
  4898	195:    "vix_median_split": 16.690000534057617,
  4899	200:    "t_stat": 6.169053858918396,
  4900	205:    "second_half_abs_return": 0.008691916519271146,
  4901	206:    "t_stat": -0.47950252995859216,
  4902	227:    "avg_abs_return": 0.010016738048407288,
  4903	241:  "claim_scope_note": "Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6).",
  4904	256:      "post_avg_abs_return": 0.004437752197660916,
  4905	269:      "event_return": 0.012456668331610077,
  4906	270:      "event_abs_return": 0.012456668331610077,
  4907	271:      "pre_avg_abs_return": 0.004473473755634516,
  4908	272:      "post_avg_abs_return": 0.004919147712201632,
  4909	304:      "post_avg_abs_return": 0.007013133994161836,
  4910	308:      "vix_change_event": 0.07000064849853516,
  4911	335:      "pre_avg_abs_return": 0.0057416373651214105,
  4912	337:      "pre_vix": 12.489999771118164,
  4913	381:      "event_return": 0.0034391603058943065,
  4914	382:      "event_abs_return": 0.0034391603058943065,
  4915	383:      "pre_avg_abs_return": 0.0069281751086755165,
  4916	417:      "pre_vix": 11.239999771118164,
  4917	433:      "pre_vix": 11.3100004196167,
  4918	436:      "vix_change_event": -0.3100004196166992,
  4919	469:      "high_low_range": 0.010887269121663814,
  4920	477:      "event_return": -0.010163338799748955,
  4921	478:      "event_abs_return": 0.010163338799748955,
  4922	484:      "vix_change_event": 0.8100004196166992,
  4923	500:      "vix_change_event": -0.23999977111816406,
  4924	501:      "high_low_range": 0.007168705988637018,
  4925	512:      "post_avg_abs_return": 0.005711716808938894,
  4926	515:      "post_vix_1d": 16.649999618530273,
  4927	532:      "vix_change_event": 0.32000064849853516,
  4928	544:      "post_avg_abs_return": 0.0030887140794647163,
  4929	561:      "pre_vix": 12.3100004196167,
  4930	573:      "event_return": -0.0012574110770166014,
  4931	574:      "event_abs_return": 0.0012574110770166014,
  4932	578:      "event_vix": 11.5600004196167,
  4933	641:      "pre_vix": 10.3100004196167,
  4934	659:      "post_vix_1d": 13.989999771118164,
  4935	672:      "post_avg_abs_return": 0.0047521168530124894,
  4936	678:      "volume_ratio": 0.6357474174016325
  4937	687:      "pre_avg_abs_return": 0.004584923166900801,
  4938	703:      "pre_avg_abs_return": 0.005207381775571696,
  4939	709:      "high_low_range": 0.005776216115471623,
  4940	720:      "post_avg_abs_return": 0.008176627484838116,
  4941	753:      "pre_vix": 23.989999771118164,
  4942	755:      "post_vix_1d": 27.3799991607666,
  4943	756:      "vix_change_event": 2.239999771118164,
  4944	770:      "event_vix": 16.90999984741211,
  4945	799:      "pre_avg_abs_return": 0.011327959273608168,
  4946	800:      "post_avg_abs_return": 0.011959847889816456,
  4947	803:      "post_vix_1d": 20.739999771118164,
  4948	817:      "pre_vix": 22.489999771118164,
  4949	829:      "event_return": 0.016088063012028586,
  4950	830:      "event_abs_return": 0.016088063012028586,
  4951	835:      "post_vix_1d": 25.989999771118164,
  4952	845:      "event_return": -0.010300816500528942,
  4953	846:      "event_abs_return": 0.010300816500528942,
  4954	850:      "event_vix": 27.489999771118164,
  4955	851:      "post_vix_1d": 29.3799991607666,
  4956	881:      "pre_vix": 18.8799991607666,
  4957	897:      "pre_vix": 18.6299991607666,
  4958	917:      "high_low_range": 0.016784124673888734,
  4959	931:      "post_vix_1d": 23.489999771118164,
  4960	959:      "pre_avg_abs_return": 0.03142508497941687,
  4961	981:      "high_low_range": 0.037289579983382164,
  4962	992:      "post_avg_abs_return": 0.018846916632064947,
  4963	995:      "post_vix_1d": 58.4900016784668,
  4964	1009:      "pre_vix": 42.560001373291016,
  4965	1021:      "event_return": 0.02849688160564745,
  4966	1022:      "event_abs_return": 0.02849688160564745,
  4967	1029:      "high_low_range": 0.030581696137665246,
  4968	1041:      "pre_vix": 50.16999816894531,
  4969	1056:      "post_avg_abs_return": 0.016382252602030987,
  4970	1085:      "event_return": 0.00021236320810169573,
  4971	1086:      "event_abs_return": 0.00021236320810169573,
  4972	1123:      "post_vix_1d": 24.989999771118164,
  4973	1125:      "high_low_range": 0.01620552805438533,
  4974	1151:      "pre_avg_abs_return": 0.010985390168460363,
  4975	1158:      "volume_ratio": 1.132461347716316
  4976	1172:      "vix_change_event": -1.239999771118164,
  4977	1199:      "pre_avg_abs_return": 0.006826103816378581,
  4978	1202:      "event_vix": 18.1299991607666,
  4979	1229:      "event_return": 0.014293581665240529,
  4980	1230:      "event_abs_return": 0.014293581665240529,
  4981	1251:      "post_vix_1d": 16.229999542236328,
  4982	1296:      "post_avg_abs_return": 0.011212316061533435,
  4983	1300:      "vix_change_event": -2.739999771118164,
  4984	1314:      "event_vix": 21.739999771118164,
  4985	1334:      "volume_ratio": 0.9416251538702529
  4986	1376:      "post_avg_abs_return": 0.0030005423381657126,
  4987	1380:      "vix_change_event": -1.3799991607666016,
  4988	1398:      "volume_ratio": 1.2505816720448455
  4989	1409:      "pre_vix": 16.690000534057617,
  4990	1411:      "post_vix_1d": 16.280000686645508,
  4991	1441:      "pre_vix": 17.739999771118164,
  4992	1472:      "post_avg_abs_return": 0.00738611160357916,
  4993	1475:      "post_vix_1d": 18.489999771118164,
  4994	1487:      "pre_avg_abs_return": 0.007346168083204185,
  4995	1501:      "event_return": -0.0014964664904916214,
  4996	1502:      "event_abs_return": 0.0014964664904916214,
  4997	1504:      "post_avg_abs_return": 0.041483440705586516,
  4998	1519:      "pre_avg_abs_return": 0.012163542237779667,
  4999	1522:      "event_vix": 33.91999816894531,
  5000	1525:      "high_low_range": 0.029189668951600765,
  5001	1533:      "event_return": -0.0066956410126548516,
  5002	1534:      "event_abs_return": 0.0066956410126548516,
  5003	1541:      "high_low_range": 0.018926648161214376,
  5004	1552:      "post_avg_abs_return": 0.016839738051925422,
  5005	1573:      "high_low_range": 0.013775438189133916,
  5006	1583:      "pre_avg_abs_return": 0.0070834274334167,
  5007	1586:      "event_vix": 20.6299991607666,
  5008	1599:      "pre_avg_abs_return": 0.0029182755788711655,
  5009	1604:      "vix_change_event": -0.8799991607666016,
  5010	1605:      "high_low_range": 0.00631775596211639,
  5011	1606:      "volume_ratio": 1.1166510779051486
  5012	1615:      "pre_avg_abs_return": 0.0077355341428540616,
  5013	1633:      "pre_vix": 16.700000762939453,
  5014	1645:      "event_return": -0.016157815269923215,
  5015	1646:      "event_abs_return": 0.016157815269923215,
  5016	1670:      "volume_ratio": 1.5550311686726317
  5017	1712:      "post_avg_abs_return": 0.00629504161687402,
  5018	1715:      "post_vix_1d": 16.280000686645508,
  5019	1745:      "pre_vix": 16.690000534057617,
  5020	1749:      "high_low_range": 0.016318152009275222,
  5021	1750:      "volume_ratio": 1.1378571674105726
  5022	1761:      "pre_vix": 16.579999923706055,
  5023	1763:      "post_vix_1d": 16.049999237060547,
  5024	1765:      "high_low_range": 0.007162448186442471,
  5025	1777:      "pre_vix": 14.5600004196167,
  5026	1807:      "pre_avg_abs_return": 0.004151116577334602,
  5027	1809:      "pre_vix": 13.0600004196167,
  5028	1811:      "post_vix_1d": 11.5600004196167,
  5029	1830:      "volume_ratio": 1.3538277137095216
  5030	1840:      "post_avg_abs_return": 0.0036462555091165473,
  5031	1844:      "vix_change_event": -0.7399997711181641,
  5032	1857:      "pre_vix": 16.6299991607666,
  5033	1873:      "pre_vix": 16.200000762939453,
  5034	1876:      "vix_change_event": -1.3100004196166992,
  5035	1885:      "event_return": 0.001698902174922523,
  5036	1886:      "event_abs_return": 0.001698902174922523,
  5037	1887:      "pre_avg_abs_return": 0.0032821649813985056,
  5038	1888:      "post_avg_abs_return": 0.003387316466368406,
  5039	1893:      "high_low_range": 0.005381679937811645,
  5040	1917:      "event_return": 0.005791669706856295,
  5041	1918:      "event_abs_return": 0.005791669706856295,
  5042	1955:      "post_vix_1d": 13.489999771118164,
  5043	1974:      "volume_ratio": 1.1022047682004164
  5044	1989:      "high_low_range": 0.01191005942164021,
  5045	1999:      "pre_avg_abs_return": 0.005362671630558036,
  5046	2032:      "post_avg_abs_return": 0.0038126889365168505,
  5047	2081:      "pre_vix": 16.950000762939453,
  5048	2085:      "high_low_range": 0.011376556792816654,
  5049	2113:      "pre_vix": 16.15999984741211,
  5050	2117:      "high_low_range": 0.009464688428221216,
  5051	2125:      "event_return": 0.0009349103953533167,
  5052	2126:      "event_abs_return": 0.0009349103953533167,
  5053	2134:      "volume_ratio": 0.8405238771111662
  5054	2141:      "event_return": 0.0016370774151923673,
  5055	2142:      "event_abs_return": 0.0016370774151923673,
  5056	2148:      "vix_change_event": -0.48999977111816406,
  5057	2159:      "pre_avg_abs_return": 0.011643978770353103,
  5058	2177:      "pre_vix": 16.850000381469727,
  5059	2195:      "post_vix_1d": 15.0600004196167,
  5060	2198:      "volume_ratio": 1.8916332873080948
  5061	2205:      "event_return": 0.006733051093951614,
  5062	2206:      "event_abs_return": 0.006733051093951614,
  5063	2210:      "event_vix": 14.739999771118164,
  5064	2221:      "event_return": 0.013166094849205168,
  5065	2222:      "event_abs_return": 0.013166094849205168,
  5066	2240:      "post_avg_abs_return": 0.005833181612777993,
  5067	2253:      "event_return": -0.0009157907354223616,
  5068	2254:      "event_abs_return": 0.0009157907354223616,
  5069	2257:      "pre_vix": 16.09000015258789,
  5070	2258:      "event_vix": 16.790000915527344,
  5071	2293:      "high_low_range": 0.011682849798971238,
  5072	2294:      "volume_ratio": 1.1606759419404762
  5073	2303:      "pre_avg_abs_return": 0.009441698045047553,
  5074	2304:      "post_avg_abs_return": 0.00780684794163351,
  5075	2319:      "pre_avg_abs_return": 0.004614440031642686,
  5076	2323:      "post_vix_1d": 16.520000457763672,
  5077	2338:      "event_vix": 14.8100004196167,
  5078	2345:      "date": "2016-01-08",
  5079	2346:      "year": 2016,
  5080	2353:      "pre_vix": 24.989999771118164,
  5081	2357:      "high_low_range": 0.022248876162983718,
  5082	2361:      "date": "2016-02-05",
  5083	2362:      "year": 2016,
  5084	2370:      "event_vix": 23.3799991607666,
  5085	2377:      "date": "2016-03-04",
  5086	2378:      "year": 2016,
  5087	2384:      "post_avg_abs_return": 0.0067191666517157685,
  5088	2385:      "pre_vix": 16.700000762939453,
  5089	2386:      "event_vix": 16.860000610351562,
  5090	2393:      "date": "2016-04-01",
  5091	2394:      "year": 2016,
  5092	2397:      "event_return": 0.006811825212216904,
  5093	2398:      "event_abs_return": 0.006811825212216904,
  5094	2405:      "high_low_range": 0.01527162038504038,
  5095	2409:      "date": "2016-05-06",
  5096	2410:      "year": 2016,
  5097	2415:      "pre_avg_abs_return": 0.005564758168076067,
  5098	2425:      "date": "2016-06-03",
  5099	2426:      "year": 2016,
  5100	2431:      "pre_avg_abs_return": 0.0023161152469873157,
  5101	2441:      "date": "2016-07-08",
  5102	2442:      "year": 2016,
  5103	2447:      "pre_avg_abs_return": 0.005911209816779839,
  5104	2452:      "vix_change_event": -1.5600004196166992,
  5105	2457:      "date": "2016-08-05",
  5106	2458:      "year": 2016,
  5107	2473:      "date": "2016-09-02",
  5108	2474:      "year": 2016,
  5109	2489:      "date": "2016-10-07",
  5110	2490:      "year": 2016,
  5111	2505:      "date": "2016-11-04",
  5112	2506:      "year": 2016,
  5113	2511:      "pre_avg_abs_return": 0.004168689860475539,
  5114	2521:      "date": "2016-12-02",
  5115	2522:      "year": 2016,
  5116	2525:      "event_return": 0.0005011654084499106,
  5117	2526:      "event_abs_return": 0.0005011654084499106,
  5118	2547:      "post_vix_1d": 11.5600004196167,
  5119	2565:      "high_low_range": 0.004752752922716175,
  5120	2566:      "volume_ratio": 1.1063197516097714
  5121	2581:      "high_low_range": 0.006016272960083019,
  5122	2646:      "volume_ratio": 0.8217132914116012
  5123	2662:      "volume_ratio": 1.1618033489972965
  5124	2688:      "post_avg_abs_return": 0.0017135397971616672,
  5125	2694:      "volume_ratio": 1.2186313418816541
  5126	2742:      "volume_ratio": 1.0480167433736693
  5127	2758:      "volume_ratio": 1.6395244232853163
  5128	2767:      "pre_avg_abs_return": 0.004890758021622732,
  5129	2769:      "pre_vix": 16.540000915527344,
  5130	2781:      "event_return": -0.022286164959837373,
  5131	2782:      "event_abs_return": 0.022286164959837373,
  5132	2784:      "post_avg_abs_return": 0.0074462251616837834,
  5133	2786:      "event_vix": 21.489999771118164,
  5134	2790:      "volume_ratio": 1.4379809959009164
  5135	2804:      "vix_change_event": -1.1299991607666016,
  5136	2815:      "pre_avg_abs_return": 0.007080551693358528,
  5137	2819:      "post_vix_1d": 12.739999771118164,
  5138	2909:      "event_return": -0.023235724014883163,
  5139	2910:      "event_abs_return": 0.023235724014883163,
  5140	2930:      "event_vix": 21.3799991607666,
  5141	2932:      "vix_change_event": -4.070001602172852,
  5142	2945:      "pre_vix": 16.56999969482422,
  5143	2946:      "event_vix": 16.139999389648438,
  5144	2949:      "high_low_range": 0.00747989168892642,
  5145	2957:      "event_return": -0.0020000544561606937,
  5146	2958:      "event_abs_return": 0.0020000544561606937,
  5147	2961:      "pre_vix": 16.59000015258789,
  5148	2962:      "event_vix": 16.049999237060547,
  5149	2976:      "post_avg_abs_return": 0.0032683320976225616,
  5150	2989:      "event_return": 0.009787911667226146,
  5151	2990:      "event_abs_return": 0.009787911667226146,
  5152	3008:      "post_avg_abs_return": 0.0023655833125168614,
  5153	3010:      "event_vix": 16.299999237060547,
  5154	3056:      "post_avg_abs_return": 0.002395419600160054,
  5155	3057:      "pre_vix": 16.270000457763672,
  5156	3085:      "event_return": 0.009264026644974166,
  5157	3086:      "event_abs_return": 0.009264026644974166,
  5158	3120:      "post_avg_abs_return": 0.0044185542165529725,
  5159	3122:      "event_vix": 12.5600004196167,
  5160	3142:      "volume_ratio": 0.8863621664917142
  5161	3149:      "event_return": -0.016531185200214682,
  5162	3150:      "event_abs_return": 0.016531185200214682,
  5163	3165:      "event_return": -0.014454160205242927,
  5164	3166:      "event_abs_return": 0.014454160205242927,
  5165	3168:      "post_avg_abs_return": 0.02522033248893716,
  5166	3171:      "post_vix_1d": 45.2400016784668,
  5167	3174:      "volume_ratio": 0.707664635498516
  5168	3181:      "event_return": 0.016546295716731718,
  5169	3182:      "event_abs_return": 0.016546295716731718,
  5170	3197:      "event_return": 0.025629768313761625,
  5171	3198:      "event_abs_return": 0.025629768313761625,
  5172	3213:      "event_return": 0.00550680279731619,
  5173	3214:      "event_abs_return": 0.00550680279731619,
  5174	3235:      "post_vix_1d": 22.1299991607666,
  5175	3237:      "high_low_range": 0.00771144165156306,
  5176	3245:      "event_return": -0.008165087864258957,
  5177	3246:      "event_abs_return": 0.008165087864258957,
  5178	3253:      "high_low_range": 0.0378316582829518,
  5179	3266:      "event_vix": 27.6299991607666,
  5180	3279:      "pre_avg_abs_return": 0.016228256836179476,
  5181	3280:      "post_avg_abs_return": 0.009001408767163266,
  5182	3300:      "vix_change_event": -0.48999977111816406,
  5183	3302:      "volume_ratio": 0.8589239582543516
  5184	3317:      "high_low_range": 0.011514410162130836,
  5185	3327:      "pre_avg_abs_return": 0.012591500767016072,
  5186	3328:      "post_avg_abs_return": 0.002975816499178374,
  5187	3331:      "post_vix_1d": 21.239999771118164,
  5188	3334:      "volume_ratio": 0.6637941686799702
  5189	3360:      "post_avg_abs_return": 0.0028259167235368254,
  5190	3378:      "event_vix": 16.690000534057617,
  5191	3382:      "volume_ratio": 0.8689834323805116
  5192	3391:      "pre_avg_abs_return": 0.0016957388159845044,
  5193	3394:      "event_vix": 16.420000076293945,
  5194	3395:      "post_vix_1d": 16.420000076293945,
  5195	3411:      "post_vix_1d": 16.440000534057617,
  5196	3421:      "event_return": 0.0016521877573574262,
  5197	3422:      "event_abs_return": 0.0016521877573574262,
  5198	3426:      "event_vix": 16.149999618530273,
  5199	3427:      "post_vix_1d": 16.719999313354492,
  5200	3441:      "pre_vix": 16.40999984741211,
  5201	3442:      "event_vix": 16.40999984741211,
  5202	3461:      "high_low_range": 0.00616638262768718,
  5203	3474:      "event_vix": 16.479999542236328,
  5204	3478:      "volume_ratio": 1.2165631403207418
  5205	3485:      "event_return": -0.008701149916033324,
  5206	3486:      "event_abs_return": 0.008701149916033324,
  5207	3487:      "pre_avg_abs_return": 0.01609030573639949,
  5208	3488:      "post_avg_abs_return": 0.010268167273724104,
  5209	3504:      "post_avg_abs_return": 0.0054487871355916265,
  5210	3519:      "pre_avg_abs_return": 0.01656450149868549,
  5211	3520:      "post_avg_abs_return": 0.01275153208026516,
  5212	3536:      "post_avg_abs_return": 0.016220448493387284,
  5213	3551:      "pre_avg_abs_return": 0.009186709241659896,
  5214	3554:      "event_vix": 19.6299991607666,
  5215	3567:      "pre_avg_abs_return": 0.022710938440661653,
  5216	3581:      "event_return": -0.016411313040607944,
  5217	3582:      "event_abs_return": 0.016411313040607944,
  5218	3588:      "vix_change_event": 0.07000160217285156,
  5219	3600:      "post_avg_abs_return": 0.009411659762782488,
  5220	3605:      "high_low_range": 0.012812953956516413,
  5221	3613:      "event_return": -0.001689972286972985,
  5222	3614:      "event_abs_return": 0.001689972286972985,
  5223	3664:      "post_avg_abs_return": 0.020039033950871653,
  5224	3698:      "event_vix": 21.1299991607666,
  5225	3725:      "event_return": -0.014429451153161188,
  5226	3726:      "event_abs_return": 0.014429451153161188,
  5227	3727:      "pre_avg_abs_return": 0.010428277330316527,
  5228	3763:      "post_vix_1d": 16.979999542236328,
  5229	3776:      "post_avg_abs_return": 0.0030788718445164953,
  5230	3830:      "volume_ratio": 0.7712351648305638
  5231	3841:      "pre_vix": 18.489999771118164,
  5232	3873:      "pre_vix": 13.0600004196167,
  5233	3888:      "post_avg_abs_return": 0.004516300813581386,
  5234	3893:      "high_low_range": 0.008569861622822642,
  5235	3922:      "event_vix": 14.739999771118164,
  5236	3925:      "high_low_range": 0.01385516650394639,
  5237	3937:      "pre_vix": 16.350000381469727,
  5238	3938:      "event_vix": 16.030000686645508,
  5239	3952:      "post_avg_abs_return": 0.0037153588616695376,
  5240	3954:      "event_vix": 13.489999771118164,
  5241	3955:      "post_vix_1d": 13.489999771118164,
  5242	3958:      "volume_ratio": 1.0990501153934116
  5243	3965:      "event_return": -0.0012158589936518416,
  5244	3966:      "event_abs_return": 0.0012158589936518416,
  5245	3971:      "post_vix_1d": 12.739999771118164,
  5246	3974:      "volume_ratio": 0.8621686970001967
  5247	3990:      "volume_ratio": 0.9231604500942332
  5248	3999:      "pre_avg_abs_return": 0.009453834221652935,
  5249	4013:      "event_return": -0.016829978520024547,
  5250	4014:      "event_abs_return": 0.016829978520024547,
  5251	4016:      "post_avg_abs_return": 0.00789131615536629,
  5252	4018:      "event_vix": 22.3799991607666,
  5253	4033:      "pre_vix": 20.489999771118164,
  5254	4050:      "event_vix": 21.8799991607666,
  5255	4053:      "high_low_range": 0.008633358198163082,
  5256	4086:      "volume_ratio": 1.5013161802064077
  5257	4098:      "event_vix": 16.540000915527344,
  5258	4099:      "post_vix_1d": 15.8100004196167,
  5259	4130:      "event_vix": 45.310001373291016,
  5260	4143:      "pre_avg_abs_return": 0.004277911690709635,
  5261	4162:      "event_vix": 16.770000457763672,
  5262	4165:      "high_low_range": 0.00662621697970003,
  5263	4177:      "pre_vix": 16.639999389648438,
  5264	4178:      "event_vix": 16.3799991607666,
  5265	4189:      "event_return": -0.01639041762130744,
  5266	4190:      "event_abs_return": 0.01639041762130744,
  5267	4193:      "pre_vix": 16.719999313354492,
  5268	4194:      "event_vix": 20.3799991607666,
  5269	4221:      "event_return": -0.015242227316648038,
  5270	4222:      "event_abs_return": 0.015242227316648038,
  5271	4223:      "pre_avg_abs_return": 0.007666979191613077,
  5272	4229:      "high_low_range": 0.036274166471176136,
  5273	4230:      "volume_ratio": 1.653162805834644
  5274	4233:      "date": "2025-12-16",
  5275	4241:      "pre_vix": 16.5,
  5276	4242:      "event_vix": 16.479999542236328,
  5277	4258:      "event_vix": 14.489999771118164,
  5278	4290:      "event_vix": 29.489999771118164,
  5279	4292:      "vix_change_event": 5.739999771118164,
  5280	1:"""Pin the NFP event dates that a first-Friday proxy gets wrong.
  5281	47:# The 7 dates the first-Friday proxy got wrong, as (proxy, official).
  5282	110:            f"{proxy_date} came from the first-Friday proxy and is not an "
  5283	338:# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
  5284	339:# (p 0.0335 -> 0.0571). Same module rather than a new file: "NFP event dates
  5285	360:    """Reject a calendar carrying the first-Friday proxy's fingerprints.
  5286	413:        """237 of 253, not 253 of 253. The gap is the corrected dates."""
  5287	
  5288	exec
  5289	/bin/zsh -lc "python -c 'oldn=835; oldm=.0071764494731905775; newn=834; newm=.007183350064732795; x=oldn*oldm-newn*newm; print(x); print((x)*100)'
  5290	# Recompute corrected Welch from committed event sample, committed t, and leaked observation inferred from aggregate difference
  5291	PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess,numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([e[\"event_abs_return\"] for e in d[\"event_data\"]]); wd=np.array([e[\"weekday\"] for e in d[\"event_data\"]]); x=a[wd==4]; ymean=d[\"main_results\"][\"friday_baseline_abs_return\"]; ny=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"n_control\"]; t=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"t_stat\"]; vx=x.var(ddof=1); vy=ny*((x.mean()-ymean)/t)**2-vx*ny/len(x); leaked=0.001157; sumy=ny*ymean; ss=(ny-1)*vy+ny*ymean*ymean; n2=ny-1; m2=(sumy-leaked)/n2; v2=(ss-leaked*leaked-n2*m2*m2)/(n2-1); t2=(x.mean()-m2)/(vx/len(x)+v2/n2)**.5; df=(vx/len(x)+v2/n2)**2/((vx/len(x))**2/(len(x)-1)+(v2/n2)**2/(n2-1)); p2=2*stats.t.sf(abs(t2),df); print({\"event_mean\":x.mean(),\"event_sd\":x.std(ddof=1),\"control_sd_solved\":vy**.5,\"corrected_mean\":m2,\"corrected_ratio\":x.mean()/m2,\"corrected_t\":t2,\"df\":df,\"p\":p2})'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  5292	 succeeded in 659ms:
  5293	{'event_mean': np.float64(0.008540928249020233), 'event_sd': np.float64(0.00800058876305757), 'control_sd_solved': np.float64(0.007757609057712275), 'corrected_mean': 0.0071836670385061535, 'corrected_ratio': np.float64(1.1889370990106918), 'corrected_t': np.float64(2.3199344158378814), 'df': np.float64(371.5081172067744), 'p': np.float64(0.02088570480457319)}
  5294	
  5295	exec
  5296	/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess,numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([e[\"event_abs_return\"] for e in d[\"event_data\"]]); wd=np.array([e[\"weekday\"] for e in d[\"event_data\"]]); x=a[wd==4]; ymean=d[\"main_results\"][\"friday_baseline_abs_return\"]; ny=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"n_control\"]; t=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"t_stat\"]; vx=x.var(ddof=1); vy=ny*((x.mean()-ymean)/t)**2-vx*ny/len(x); leaked=0.0014213561269809105; sumy=ny*ymean; ss=(ny-1)*vy+ny*ymean*ymean; n2=ny-1; m2=(sumy-leaked)/n2; v2=(ss-leaked*leaked-n2*m2*m2)/(n2-1); t2=(x.mean()-m2)/(vx/len(x)+v2/n2)**.5; df=(vx/len(x)+v2/n2)**2/((vx/len(x))**2/(len(x)-1)+(v2/n2)**2/(n2-1)); p2=2*stats.t.sf(abs(t2),df); print({\"leaked_abs_return\":leaked,\"corrected_mean\":m2,\"corrected_ratio\":x.mean()/m2,\"corrected_t\":t2,\"p\":p2})'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  5297	 succeeded in 618ms:
  5298	{'leaked_abs_return': 0.0014213561269809105, 'corrected_mean': 0.007183350064732795, 'corrected_ratio': np.float64(1.1889895622590594), 'corrected_t': np.float64(2.3204610057628905), 'p': np.float64(0.020856890586645502)}
  5299	
  5300	exec
  5301	/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import json,subprocess,numpy as np; from scipy import stats; d=json.loads(subprocess.check_output([\"git\",\"show\",\"6fd281901:experiments/k528/k528_nfp_event_study_results.json\"])); a=np.array([e[\"event_abs_return\"] for e in d[\"event_data\"]]); wd=np.array([e[\"weekday\"] for e in d[\"event_data\"]]); xf=a[wd==4]; ymean=d[\"main_results\"][\"friday_baseline_abs_return\"]; ny=835; t=d[\"statistical_tests\"][\"B_nfp_vs_friday\"][\"t_stat\"]; vxf=xf.var(ddof=1); vy=ny*((xf.mean()-ymean)/t)**2-vxf*ny/len(xf); leaked=.0014213561269809105; sy=ny*ymean; ss=(ny-1)*vy+ny*ymean*ymean; n2=834; m2=(sy-leaked)/n2; v2=(ss-leaked*leaked-n2*m2*m2)/(n2-1); 
  5302	for name,x in [(\"friday\",xf),(\"mixed\",a)]:
  5303	 vx=x.var(ddof=1); tt=(x.mean()-m2)/(vx/len(x)+v2/n2)**.5; df=(vx/len(x)+v2/n2)**2/((vx/len(x))**2/(len(x)-1)+(v2/n2)**2/(n2-1)); print(name,len(x),x.mean()/m2,tt,2*stats.t.sf(abs(tt),df))'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  5304	 succeeded in 607ms:
  5305	friday 237 1.1889895622590594 2.3204610057628905 0.020856890586645502
  5306	mixed 253 1.176757657090474 2.2389804655292807 0.025694671724286588
  5307	
  5308	exec
  5309	/bin/zsh -lc "git show 6fd281901:src/volpred/data/event_dates.py | PYTHONDONTWRITEBYTECODE=1 python -c 'import sys,json; from pathlib import Path; src=sys.stdin.read(); assert \"monthly = s.groupby([dates.year, dates.month]).min()\" in src; mut=src.replace(\"monthly = s.groupby([dates.year, dates.month]).min()\",\"monthly = s.groupby([dates.year, dates.month]).max()\"); ns={\"__file__\":str(Path(\"src/volpred/data/event_dates.py\").resolve()),\"__name__\":\"mutated_event_dates\"}; exec(compile(mut,\"mutated_event_dates.py\",\"exec\"),ns); raw=json.loads(Path(\"tests/fixtures/fred_release_50_nfp_raw_20260719.json\").read_text())[\"release_dates\"]; ns[\"_fetch\"]=lambda *a,**k:list(raw); got=[str(x.date()) for x in ns[\"release_dates\"](\"NFP_US\",\"2005-01-01\",\"2026-07-19\",use_cache=False)]; exp=[\"2006-05-05\",\"2012-12-07\",\"2013-05-03\",\"2020-05-08\",\"2024-01-05\",\"2024-08-02\"]; print(\"mutated_selected\",[x for x in got if x[:7] in {z[:7] for z in exp}]); print(\"would_test_fail\",not all(x in got for x in exp))'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  5310	 succeeded in 361ms:
  5311	mutated_selected ['2006-05-08', '2012-12-12', '2013-05-06', '2020-05-11', '2024-01-10', '2024-08-21']
  5312	would_test_fail True
  5313	
  5314	exec
  5315	/bin/zsh -lc "git show 6fd281901:experiments/k528/k528_nfp_event_study_results.json | nl -ba | sed -n '1,90p'
  5316	git show 6fd281901:experiments/k528/k528_nfp_official_dates_results.json | nl -ba | sed -n '100,230p'
  5317	git show 6fd281901:experiments/k528/k528_nfp_official_dates_results.json | nl -ba | sed -n '230,390p'
  5318	git show 6fd281901:tests/test_event_dates_real_raw_response.py | nl -ba | sed -n '1,120p'
  5319	git show 6fd281901:tests/fixtures/fred_release_50_nfp_raw_20260719.json | nl -ba | sed -n '1,30p'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  5320	 succeeded in 245ms:
  5321	   230	      "note": "",
  5322	   231	      "verdict": "NUMERIC_ADJUSTMENT",
  5323	   232	      "verdict_reasons": []
  5324	   233	    },
  5325	   234	    "sample": {
  5326	   235	      "label": "NFP event sample (article: 254 events)",
  5327	   236	      "before": {
  5328	   237	        "n": 254,
  5329	   238	        "date_range": "2005-02-04 to 2026-03-06",
  5330	   239	        "non_nfp_trading_days": 5086
  5331	   240	      },
  5332	   241	      "after": {
  5333	   242	        "n": 253,
  5334	   243	        "date_range": "2005-02-04 to 2026-03-06",
  5335	   244	        "non_nfp_trading_days": 5087,
  5336	   245	        "dates_in_common": 212,
  5337	   246	        "proxy_only_dates": [
  5338	   247	          "2005-07-01",
  5339	   248	          "2006-03-03",
  5340	   249	          "2006-12-01",
  5341	   250	          "2007-03-02",
  5342	   251	          "2008-07-07",
  5343	   252	          "2009-01-02",
  5344	   253	          "2009-05-01",
  5345	   254	          "2009-07-06",
  5346	   255	          "2010-01-04",
  5347	   256	          "2010-10-01",
  5348	   257	          "2011-07-01",
  5349	   258	          "2012-03-02",
  5350	   259	          "2013-03-01",
  5351	   260	          "2013-10-04",
  5352	   261	          "2013-11-01",
  5353	   262	          "2014-01-03",
  5354	   263	          "2014-07-07",
  5355	   264	          "2015-01-02",
  5356	   265	          "2015-05-01",
  5357	   266	          "2015-07-06",
  5358	   267	          "2016-01-04",
  5359	   268	          "2016-07-01",
  5360	   269	          "2017-03-03",
  5361	   270	          "2017-12-01",
  5362	   271	          "2018-03-02",
  5363	   272	          "2019-03-01",
  5364	   273	          "2020-01-03",
  5365	   274	          "2020-05-01",
  5366	   275	          "2020-07-06",
  5367	   276	          "2021-01-04",
  5368	   277	          "2021-10-01",
  5369	   278	          "2022-07-01",
  5370	   279	          "2023-03-03",
  5371	   280	          "2023-12-01",
  5372	   281	          "2024-03-01",
  5373	   282	          "2025-01-03",
  5374	   283	          "2025-07-07",
  5375	   284	          "2025-10-03",
  5376	   285	          "2025-11-07",
  5377	   286	          "2025-12-05",
  5378	   287	          "2026-01-02",
  5379	   288	          "2026-02-06"
  5380	   289	        ],
  5381	   290	        "official_only_dates": [
  5382	   291	          "2005-07-08",
  5383	   292	          "2006-03-10",
  5384	   293	          "2006-12-08",
  5385	   294	          "2007-03-09",
  5386	   295	          "2008-07-03",
  5387	   296	          "2009-01-09",
  5388	   297	          "2009-05-08",
  5389	   298	          "2009-07-02",
  5390	   299	          "2010-01-08",
  5391	   300	          "2010-10-08",
  5392	   301	          "2011-07-08",
  5393	   302	          "2012-03-09",
  5394	   303	          "2013-03-08",
  5395	   304	          "2013-10-22",
  5396	   305	          "2013-11-08",
  5397	   306	          "2014-01-10",
  5398	   307	          "2014-07-03",
  5399	   308	          "2015-01-09",
  5400	   309	          "2015-05-08",
  5401	   310	          "2015-07-02",
  5402	   311	          "2016-01-08",
  5403	   312	          "2016-07-08",
  5404	   313	          "2017-03-10",
  5405	   314	          "2017-12-08",
  5406	   315	          "2018-03-09",
  5407	   316	          "2019-03-08",
  5408	   317	          "2020-01-10",
  5409	   318	          "2020-05-08",
  5410	   319	          "2020-07-02",
  5411	   320	          "2021-01-08",
  5412	   321	          "2021-10-08",
  5413	   322	          "2022-07-08",
  5414	   323	          "2023-03-10",
  5415	   324	          "2023-12-08",
  5416	   325	          "2024-03-08",
  5417	   326	          "2025-01-10",
  5418	   327	          "2025-07-03",
  5419	   328	          "2025-11-20",
  5420	   329	          "2025-12-16",
  5421	   330	          "2026-01-09",
  5422	   331	          "2026-02-11"
  5423	   332	        ]
  5424	   333	      },
  5425	   334	      "note": "Equal counts do not mean equal samples -- check dates_in_common.",
  5426	   335	      "verdict": "NUMERIC_ADJUSTMENT",
  5427	   336	      "verdict_reasons": []
  5428	   337	    }
  5429	   338	  },
  5430	   339	  "n_claims_flipped": 0,
  5431	   340	  "n_claims_audited": 6,
  5432	   341	  "article_correction": {
  5433	   342	    "article_id": "mile_35eef830",
  5434	   343	    "status": "validated_not_applied",
  5435	   344	    "n_replacements": 19,
  5436	   345	    "all_matched_exactly_once": true,
  5437	   346	    "supersedes": {
  5438	   347	      "voided_list_size": 18,
  5439	   348	      "voided_at": "2026-07-19",
  5440	   349	      "reason": "the 18-item list was built against a rerun whose accessor picked off-cycle ALFRED entries for six months, which pushed the NFP-vs-Friday test across the 5% line. It would have retracted a finding that is in fact correct."
  5441	   350	    },
  5442	   351	    "directional_claims_changed": 0,
  5443	   352	    "replacements": [
  5444	   353	      {
  5445	   354	        "from": "總共 254 次 NFP 公布日的資料算過一遍",
  5446	   355	        "to": "總共 253 次 NFP 公布日的資料算過一遍",
  5447	   356	        "hits": 1
  5448	   357	      },
  5449	   358	      {
  5450	   359	        "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
  5451	   360	        "to": "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
  5452	   361	        "hits": 1
  5453	   362	      },
  5454	   363	      {
  5455	   364	        "from": "換句話說，這 1.10 倍的差距",
  5456	   365	        "to": "換句話說，這 1.11 倍的差距",
  5457	   366	        "hits": 1
  5458	   367	      },
  5459	   368	      {
  5460	   369	        "from": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  5461	   370	        "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。改用官方日曆之後，253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.020）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
  5462	   371	        "hits": 1
  5463	   372	      },
  5464	   373	      {
  5465	   374	        "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
  5466	   375	        "to": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
  5467	   376	        "hits": 1
  5468	   377	      },
  5469	   378	      {
  5470	   379	        "from": "那 254 次 NFP 日裡",
  5471	   380	        "to": "那 253 次 NFP 日裡",
  5472	   381	        "hits": 1
  5473	   382	      },
  5474	   383	      {
  5475	   384	        "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
  5476	   385	        "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
  5477	   386	        "hits": 1
  5478	   387	      },
  5479	   388	      {
  5480	   389	        "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
  5481	   390	        "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
  5482	     1	"""Regression test against the VERBATIM ALFRED raw response.
  5483	     2	
  5484	     3	Why this file exists, separately from test_event_dates_release_selection.py:
  5485	     4	
  5486	     5	The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
  5487	     6	a *hand-built* fixture in which the same-month duplicate entries had already
  5488	     7	been removed. So they exercised the selection rule against input that could
  5489	     8	not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
  5490	     9	dates and flipped a significance result with a fully green suite.
  5491	    10	
  5492	    11	The fix for a fixture that cannot express the bug is not a better assertion —
  5493	    12	it is real input. This module pins `_fetch`'s actual bytes for release id 50
  5494	    13	(Employment Situation, 2005-01-01..2026-07-19, 264 entries) and asserts the
  5495	    14	six regular releases survive selection.
  5496	    15	
  5497	    16	Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
  5498	    17	it — the duplicate pairs ARE the regression surface).
  5499	    18	"""
  5500	    19	from __future__ import annotations
  5501	    20	
  5502	    21	import json
  5503	    22	from pathlib import Path
  5504	    23	
  5505	    24	import pytest
  5506	    25	
  5507	    26	from volpred.data import event_dates
  5508	    27	
  5509	    28	_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
  5510	    29	
  5511	    30	# The six months ALFRED returns twice for, with the regular Employment Situation
  5512	    31	# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
  5513	    32	# filed against the same release id LATER in the month). Verified against the
  5514	    33	# live API on 2026-07-19; the right-hand column is exactly what the old max()
  5515	    34	# rule picked and what k528's contaminated run treated as NFP event days.
  5516	    35	OFF_CYCLE_PAIRS = {
  5517	    36	    "2006-05": ("2006-05-05", "2006-05-08"),
  5518	    37	    "2012-12": ("2012-12-07", "2012-12-12"),
  5519	    38	    "2013-05": ("2013-05-03", "2013-05-06"),
  5520	    39	    "2020-05": ("2020-05-08", "2020-05-11"),
  5521	    40	    "2024-01": ("2024-01-05", "2024-01-10"),
  5522	    41	    "2024-08": ("2024-08-02", "2024-08-21"),
  5523	    42	}
  5524	    43	
  5525	    44	
  5526	    45	@pytest.fixture(autouse=True)
  5527	    46	def _sandbox_cache_dir(monkeypatch, tmp_path):
  5528	    47	    # No test may touch the canonical storage/data cache dir (CI repo-state guard).
  5529	    48	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
  5530	    49	
  5531	    50	
  5532	    51	@pytest.fixture
  5533	    52	def raw_response() -> list[str]:
  5534	    53	    return json.loads(_FIXTURE.read_text())["release_dates"]
  5535	    54	
  5536	    55	
  5537	    56	@pytest.fixture
  5538	    57	def selected(monkeypatch, raw_response) -> list[str]:
  5539	    58	    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw_response))
  5540	    59	    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
  5541	    60	    return [str(d.date()) for d in idx]
  5542	    61	
  5543	    62	
  5544	    63	def test_fixture_still_carries_the_duplicate_months(raw_response):
  5545	    64	    """Guard the guard: if someone 'cleans' the fixture, the suite goes quiet again."""
  5546	    65	    by_month: dict[str, list[str]] = {}
  5547	    66	    for d in raw_response:
  5548	    67	        by_month.setdefault(d[:7], []).append(d)
  5549	    68	    multi = {m: v for m, v in by_month.items() if len(v) > 1}
  5550	    69	    assert set(multi) == set(OFF_CYCLE_PAIRS), (
  5551	    70	        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
  5552	    71	        f"got {sorted(multi)}"
  5553	    72	    )
  5554	    73	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
  5555	    74	        assert sorted(multi[month]) == [regular, off_cycle]
  5556	    75	
  5557	    76	
  5558	    77	def test_regular_release_wins_in_every_duplicate_month(selected):
  5559	    78	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
  5560	    79	        in_month = [d for d in selected if d.startswith(month)]
  5561	    80	        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
  5562	    81	        assert off_cycle not in selected, f"{off_cycle} is an off-cycle revision, not an NFP event"
  5563	    82	
  5564	    83	
  5565	    84	def test_selection_is_one_per_month_and_complete(selected, raw_response):
  5566	    85	    months_in = {d[:7] for d in raw_response}
  5567	    86	    months_out = [d[:7] for d in selected]
  5568	    87	    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
  5569	    88	    assert set(months_out) == months_in, "selection dropped or invented a month"
  5570	    89	    assert len(selected) == 258
  5571	    90	
  5572	    91	
  5573	    92	def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
  5574	    93	    """Mutation check: the OLD rule must fail this file, or it proves nothing.
  5575	    94	
  5576	    95	    Without this, a future refactor could silently restore max() and the two
  5577	    96	    assertions above would be the only thing standing in the way — this pins
  5578	    97	    WHY they matter.
  5579	    98	    """
  5580	    99	    by_month: dict[str, list[str]] = {}
  5581	   100	    for d in raw_response:
  5582	   101	        by_month.setdefault(d[:7], []).append(d)
  5583	   102	    old_rule = {m: max(v) for m, v in by_month.items()}
  5584	   103	    wrong = {m: old_rule[m] for m, (regular, _) in OFF_CYCLE_PAIRS.items() if old_rule[m] != regular}
  5585	   104	    assert wrong == {m: off for m, (_, off) in OFF_CYCLE_PAIRS.items()}, (
  5586	   105	        "the old max() rule must pick exactly the six off-cycle dates on this input"
  5587	   106	    )
  5588	     1	{
  5589	     2	  "source": "FRED/ALFRED release/dates API, release_id=50 (Employment Situation)",
  5590	     3	  "params": {
  5591	     4	    "realtime_start": "2005-01-01",
  5592	     5	    "realtime_end": "2026-07-19",
  5593	     6	    "include_release_dates_with_no_data": true,
  5594	     7	    "limit": 1000,
  5595	     8	    "sort_order": "asc"
  5596	     9	  },
  5597	    10	  "captured_at": "2026-07-19",
  5598	    11	  "note": "VERBATIM _fetch() output. Do NOT hand-edit or de-duplicate: the six same-month duplicate pairs ARE the regression surface (k528 Codex v2 BLOCKER 1).",
  5599	    12	  "release_dates": [
  5600	    13	    "2005-01-07",
  5601	    14	    "2005-02-04",
  5602	    15	    "2005-03-04",
  5603	    16	    "2005-04-01",
  5604	    17	    "2005-05-06",
  5605	    18	    "2005-06-03",
  5606	    19	    "2005-07-08",
  5607	    20	    "2005-08-05",
  5608	    21	    "2005-09-02",
  5609	    22	    "2005-10-07",
  5610	    23	    "2005-11-04",
  5611	    24	    "2005-12-02",
  5612	    25	    "2006-01-06",
  5613	    26	    "2006-02-03",
  5614	    27	    "2006-03-10",
  5615	    28	    "2006-04-07",
  5616	    29	    "2006-05-05",
  5617	    30	    "2006-05-08",
  5618	
  5619	codex
  5620	核心驗收已完成：六個日期與 mutation 測試都通過；舊 18 條「方向翻轉」作廢也成立；原子寫入、真正 dry-run、superseded metadata、lookahead/seed 均可驗收。但指定 commit 仍有三個獨立 blocker：控制組漏排一個真實 NFP 日、before/after 審計硬比不同 estimand 且錯報 proxy 全為週五、fail-closed 可被多種合法形狀的錯資料繞過。現在整理逐點行號與最後裁決。
  5621	已完成指定 commit 的獨立驗算；worktree 後續出現的未提交變更不納入裁決。
  5622	  ✓ 讀 handoff、二審裁決與本輪 commit/diff，建立逐項驗收表
  5623	  ✓ 審查 accessor、fixture、fail-closed 與測試，做 mutation/繞過驗證
  5624	  ✓ 獨立重算新舊 estimand 統計量並核對事件日期
  5625	  ✓ 核對 README、results、audit、19 條文章更正與 superseded metadata
  5626	  ✓ 彙整逐點 findings、blocking defects 與最終 verdict
  5627	exec
  5628	/bin/zsh -lc 'git status --short --branch
  5629	git diff --name-only' in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
  5630	 succeeded in 200ms:
  5631	## k528-nfp-official-dates
  5632	 M experiments/k528/k528_nfp_event_study.py
  5633	 M experiments/k528/k528_nfp_event_study_results.json
  5634	 M experiments/k528/k528_nfp_official_dates_results.json
  5635	experiments/k528/k528_nfp_event_study.py
  5636	experiments/k528/k528_nfp_event_study_results.json
  5637	experiments/k528/k528_nfp_official_dates_results.json
  5638	
  5639	codex
  5640	審查範圍固定為 commit `6fd281901`。審查途中 worktree 另出現 3 個未提交修改；以下行號與裁決均以 `git show 6fd281901:<path>` 為準，不把移動中的修正版算進驗收。
  5641	
  5642	1. **BLOCKER — 真實 NFP 日洩漏進控制組，兩個指定統計量受污染。**  
  5643	   `experiments/k528/k528_nfp_event_study.py:340-342` 只以 `valid_nfp` 排除控制組；但 `2005-01-07` 雖因事件窗不足被排除，仍是真實 NFP session。artifact 自己記錄 254 場已映射、1 場 window-excluded、253 場 valid（`k528_nfp_event_study_results.json:18-28`），卻把該日留在 non-NFP Fridays。  
  5644	   我由逐事件資料獨立重算，commit 內的 1.19013285 / p=0.02019846 與 1.17788918 / p=0.02487914 確實能重現，但那只是重現了污染。排除該日後應約為：
  5645	
  5646	   - Friday-only：**1.18899×，p=0.02086，n=237 vs 834**
  5647	   - Mixed-weekday diagnostic：**1.17676×，p=0.02569，n=253 vs 834**
  5648	
  5649	   方向仍顯著，但現行 results、README、audit 與 19 條更正中的精確數值都不是正確最終結果。正確集合應為所有 `nfp_trading_dates`，不是 `valid_nfp`。
  5650	
  5651	2. **BLOCKER — before/after audit 硬比不同 estimand，且「proxy 全為週五」是錯的。**  
  5652	   proxy 日期雖由第一個週五產生，但遇休市會映射到下一個 session；archive 的實際事件資料是 **239 個 Friday、15 個 Monday**，不是 254/254 Friday。可是 audit 把 before 寫成 254 個 Friday（`k528_nfp_official_dates_results.json:136-143`），after 則只取 237 個 Friday（`145-160`），再宣稱是 apples-to-apples（`162`）。主腳本同樣直接把 before 全 254 場拿來比較（`k528_nfp_event_study.py:730-763`）。  
  5653	   正確 audit 必須提供兩組平行比較：
  5654	
  5655	   - restricted estimand：proxy Friday 239 vs official Friday 237；
  5656	   - as-published mixed estimand：proxy 全 254 vs official 全 253。
  5657	
  5658	   README `:71-81`、builder `:30-35` 和更正說明 `:179-183` 都錯稱初版已自動控制 weekday。這不是單純措辭問題，而是前後比較的識別口徑錯誤。
  5659	
  5660	3. **BLOCKER — fail-closed 仍可被合理形狀的錯資料繞過。**  
  5661	   `src/volpred/data/event_dates.py:134-156` 在交給實驗前已按月 `min()`，因此 `check_calendar_is_complete()` 的「同月多筆 raise」（`k528_nfp_event_study.py:121-128`）在 live accessor 路徑不可達。實測輸入：
  5662	
  5663	   ```text
  5664	   2024-01-05, 2024-02-01(off-cycle), 2024-02-02(regular), 2024-03-08
  5665	   ```
  5666	
  5667	   accessor 靜默選 `2024-02-01`，且 cadence 完全通過。另有：
  5668	
  5669	   - `check_calendar_is_complete()` 無條件忽略首尾月份（`:130-137`）；即使 `start=2005-01-01` 或 `end=2005-03-31` 是完整月份，缺月仍通過。
  5670	   - 13–110 天允許一至兩個月消失而不報錯。
  5671	   - `KNOWN_MISSING_MONTHS` 現行只有有文件依據的 2025-10，未見本輪濫用；但它是未驗證的全域 allowlist，技術上仍可用新增字串繞過檢查。
  5672	
  5673	4. **HIGH — 19 條替換雖全部命中，但不能套用。**  
  5674	   dry-run 實測 19/19 舊字串各命中一次且沒有寫入。抽查超過 8 項後，253、0.845%、1.11×、16.69、128/125、2.03×、Pearson 0.44、Spearman 0.35、斜率 0.043pp、VIX 距離 0.10 等均與 commit artifact 的四捨五入值對齊。  
  5675	   問題集中在 Friday headline：
  5676	
  5677	   - builder `:104-107` 仍寫「NFP 日確實比一般週五抖」，但檢定只識別「Friday NFP」。
  5678	   - builder `:151-154` 又把 conditional estimand 泛化成「NFP 事件本身」。
  5679	   - 被排除的 16 場平均 |return| 為 0.715%，比 Friday NFP 的 0.854% 低約 **16.3%**；限制 Friday 並非中性的樣本刪除，確實提高 headline ratio。
  5680	
  5681	   限定週五本身可以是誠實的 conditional estimand，但不能再支持全體 NFP 的敘述。
  5682	
  5683	5. **MEDIUM — results 內部仍有直接矛盾。**  
  5684	   `k528_nfp_event_study_results.json:55` 說排除 11 場 non-Friday，`:63` 卻記錄 16 場；README `:76` 的 weekday 分解也只加總到 11，漏掉映射後的 6 個 Monday，且 Thursday 數量亦不一致。
  5685	
  5686	6. **MEDIUM — 新測試確實咬得到 `max()`，但 coverage 宣稱過頭。**  
  5687	   我把 production selection 動態 mutation 為 `max()`，六個月份精確變回 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；`test_regular_release_wins_in_every_duplicate_month` 會轉紅，因此不是 vacuous。正常 accessor 也確實選回六個正確日期；BLS 官方 Employment Situation archive 可交叉確認，例如 [2013-05-03](https://www.bls.gov/news.release/archives/empsit_05032013.htm)、[2020-05-08](https://www.bls.gov/news.release/archives/empsit_05082020.htm)、[2024-08-02](https://www.bls.gov/news.release/archives/empsit_08022024.htm)。  
  5688	   但 fixture 是 `_fetch()` 抽出的日期清單，不是完整 ALFRED HTTP raw-response bytes；`test_event_dates_real_raw_response.py:1-14` 的 “VERBATIM raw response/actual bytes” 是 overclaim。測試也沒有覆蓋較早 off-cycle、完整首尾月缺失或控制組洩漏。`tests/test_nfp_official_release_dates.py:338-340` 還殘留已推翻的 p=0.0571 敘述。
  5689	
  5690	7. **已驗收通過。**
  5691	
  5692	   - 六個問題月份已由 accessor 選回正確日期；`min()`→`max()` mutation 會失敗。
  5693	   - 二審指出「顯著→不顯著」不成立是正確的；原 18 條方向翻轉清單全數作廢理由成立。
  5694	   - `B_diagnostic_mixed_weekday` 在 results 中有清楚標成 diagnostic；問題是 audit/README 對 before estimand 的描述，不是該欄被直接當 headline。
  5695	   - `insignificant across all tests` 已移除，各主要顯著性敘述有綁定個別檢定。
  5696	   - 主結果與 audit 使用 temp file、`fsync`、`os.replace`；builder 預設 dry-run 不寫。
  5697	   - archive JSON 已具 `superseded=true`、`do_not_cite=true`、`superseded_by` 與 `retraction_reason`。
  5698	   - `pre_vix` 取 T−1，未見 lookahead；本實驗沒有隨機抽樣/bootstrap，seed 不適用。
  5699	   - 事件日映射碰撞與樣本內 unmapped assertion 已補上。
  5700	
  5701	Blocking defects：控制組混入 `2005-01-07` 真實 NFP 日；before/after Friday audit 比較不同 estimand 且錯報 proxy weekday composition；calendar completeness 仍無法真正 fail-closed。19 條更正不得以 commit `6fd281901` 套用。
  5702	
  5703	VERDICT: FAIL
  5704	tokens used
  5705	199,132
  5706	審查範圍固定為 commit `6fd281901`。審查途中 worktree 另出現 3 個未提交修改；以下行號與裁決均以 `git show 6fd281901:<path>` 為準，不把移動中的修正版算進驗收。
  5707	
  5708	1. **BLOCKER — 真實 NFP 日洩漏進控制組，兩個指定統計量受污染。**  
  5709	   `experiments/k528/k528_nfp_event_study.py:340-342` 只以 `valid_nfp` 排除控制組；但 `2005-01-07` 雖因事件窗不足被排除，仍是真實 NFP session。artifact 自己記錄 254 場已映射、1 場 window-excluded、253 場 valid（`k528_nfp_event_study_results.json:18-28`），卻把該日留在 non-NFP Fridays。  
  5710	   我由逐事件資料獨立重算，commit 內的 1.19013285 / p=0.02019846 與 1.17788918 / p=0.02487914 確實能重現，但那只是重現了污染。排除該日後應約為：
  5711	
  5712	   - Friday-only：**1.18899×，p=0.02086，n=237 vs 834**
  5713	   - Mixed-weekday diagnostic：**1.17676×，p=0.02569，n=253 vs 834**
  5714	
  5715	   方向仍顯著，但現行 results、README、audit 與 19 條更正中的精確數值都不是正確最終結果。正確集合應為所有 `nfp_trading_dates`，不是 `valid_nfp`。
  5716	
  5717	2. **BLOCKER — before/after audit 硬比不同 estimand，且「proxy 全為週五」是錯的。**  
  5718	   proxy 日期雖由第一個週五產生，但遇休市會映射到下一個 session；archive 的實際事件資料是 **239 個 Friday、15 個 Monday**，不是 254/254 Friday。可是 audit 把 before 寫成 254 個 Friday（`k528_nfp_official_dates_results.json:136-143`），after 則只取 237 個 Friday（`145-160`），再宣稱是 apples-to-apples（`162`）。主腳本同樣直接把 before 全 254 場拿來比較（`k528_nfp_event_study.py:730-763`）。  
  5719	   正確 audit 必須提供兩組平行比較：
  5720	
  5721	   - restricted estimand：proxy Friday 239 vs official Friday 237；
  5722	   - as-published mixed estimand：proxy 全 254 vs official 全 253。
  5723	
  5724	   README `:71-81`、builder `:30-35` 和更正說明 `:179-183` 都錯稱初版已自動控制 weekday。這不是單純措辭問題，而是前後比較的識別口徑錯誤。
  5725	
  5726	3. **BLOCKER — fail-closed 仍可被合理形狀的錯資料繞過。**  
  5727	   `src/volpred/data/event_dates.py:134-156` 在交給實驗前已按月 `min()`，因此 `check_calendar_is_complete()` 的「同月多筆 raise」（`k528_nfp_event_study.py:121-128`）在 live accessor 路徑不可達。實測輸入：
  5728	
  5729	   ```text
  5730	   2024-01-05, 2024-02-01(off-cycle), 2024-02-02(regular), 2024-03-08
  5731	   ```
  5732	
  5733	   accessor 靜默選 `2024-02-01`，且 cadence 完全通過。另有：
  5734	
  5735	   - `check_calendar_is_complete()` 無條件忽略首尾月份（`:130-137`）；即使 `start=2005-01-01` 或 `end=2005-03-31` 是完整月份，缺月仍通過。
  5736	   - 13–110 天允許一至兩個月消失而不報錯。
  5737	   - `KNOWN_MISSING_MONTHS` 現行只有有文件依據的 2025-10，未見本輪濫用；但它是未驗證的全域 allowlist，技術上仍可用新增字串繞過檢查。
  5738	
  5739	4. **HIGH — 19 條替換雖全部命中，但不能套用。**  
  5740	   dry-run 實測 19/19 舊字串各命中一次且沒有寫入。抽查超過 8 項後，253、0.845%、1.11×、16.69、128/125、2.03×、Pearson 0.44、Spearman 0.35、斜率 0.043pp、VIX 距離 0.10 等均與 commit artifact 的四捨五入值對齊。  
  5741	   問題集中在 Friday headline：
  5742	
  5743	   - builder `:104-107` 仍寫「NFP 日確實比一般週五抖」，但檢定只識別「Friday NFP」。
  5744	   - builder `:151-154` 又把 conditional estimand 泛化成「NFP 事件本身」。
  5745	   - 被排除的 16 場平均 |return| 為 0.715%，比 Friday NFP 的 0.854% 低約 **16.3%**；限制 Friday 並非中性的樣本刪除，確實提高 headline ratio。
  5746	
  5747	   限定週五本身可以是誠實的 conditional estimand，但不能再支持全體 NFP 的敘述。
  5748	
  5749	5. **MEDIUM — results 內部仍有直接矛盾。**  
  5750	   `k528_nfp_event_study_results.json:55` 說排除 11 場 non-Friday，`:63` 卻記錄 16 場；README `:76` 的 weekday 分解也只加總到 11，漏掉映射後的 6 個 Monday，且 Thursday 數量亦不一致。
  5751	
  5752	6. **MEDIUM — 新測試確實咬得到 `max()`，但 coverage 宣稱過頭。**  
  5753	   我把 production selection 動態 mutation 為 `max()`，六個月份精確變回 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；`test_regular_release_wins_in_every_duplicate_month` 會轉紅，因此不是 vacuous。正常 accessor 也確實選回六個正確日期；BLS 官方 Employment Situation archive 可交叉確認，例如 [2013-05-03](https://www.bls.gov/news.release/archives/empsit_05032013.htm)、[2020-05-08](https://www.bls.gov/news.release/archives/empsit_05082020.htm)、[2024-08-02](https://www.bls.gov/news.release/archives/empsit_08022024.htm)。  
  5754	   但 fixture 是 `_fetch()` 抽出的日期清單，不是完整 ALFRED HTTP raw-response bytes；`test_event_dates_real_raw_response.py:1-14` 的 “VERBATIM raw response/actual bytes” 是 overclaim。測試也沒有覆蓋較早 off-cycle、完整首尾月缺失或控制組洩漏。`tests/test_nfp_official_release_dates.py:338-340` 還殘留已推翻的 p=0.0571 敘述。
  5755	
  5756	7. **已驗收通過。**
  5757	
  5758	   - 六個問題月份已由 accessor 選回正確日期；`min()`→`max()` mutation 會失敗。
  5759	   - 二審指出「顯著→不顯著」不成立是正確的；原 18 條方向翻轉清單全數作廢理由成立。
  5760	   - `B_diagnostic_mixed_weekday` 在 results 中有清楚標成 diagnostic；問題是 audit/README 對 before estimand 的描述，不是該欄被直接當 headline。
  5761	   - `insignificant across all tests` 已移除，各主要顯著性敘述有綁定個別檢定。
  5762	   - 主結果與 audit 使用 temp file、`fsync`、`os.replace`；builder 預設 dry-run 不寫。
  5763	   - archive JSON 已具 `superseded=true`、`do_not_cite=true`、`superseded_by` 與 `retraction_reason`。
  5764	   - `pre_vix` 取 T−1，未見 lookahead；本實驗沒有隨機抽樣/bootstrap，seed 不適用。
  5765	   - 事件日映射碰撞與樣本內 unmapped assertion 已補上。
  5766	
  5767	Blocking defects：控制組混入 `2005-01-07` 真實 NFP 日；before/after Friday audit 比較不同 estimand 且錯報 proxy weekday composition；calendar completeness 仍無法真正 fail-closed。19 條更正不得以 commit `6fd281901` 套用。
  5768	
  5769	VERDICT: FAIL
  5770	EXIT=0

codex
上一輪三個 blocker 的原始證據已定位。現在進入本輪驗收：我先比對 `6fd281901..2abb3f68c` 的精確改動，再直接從 commit JSON 的逐事件資料重算，不使用 README 已彙總的數字。特別會分開驗證「所有已映射 NFP sessions」與「有效事件樣本」，避免再把 sample eligibility 當成事件身分。
exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff --unified=80 6fd281901 2abb3f68c -- experiments/k528/k528_nfp_event_study.py src/volpred/data/event_dates.py tests/test_nfp_official_release_dates.py tests/test_event_dates_real_raw_response.py tests/test_event_dates_release_selection.py | sed -n '1,2600p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
diff --git a/experiments/k528/k528_nfp_event_study.py b/experiments/k528/k528_nfp_event_study.py
index 6983a642f..3a0338a4c 100644
--- a/experiments/k528/k528_nfp_event_study.py
+++ b/experiments/k528/k528_nfp_event_study.py
@@ -1,239 +1,302 @@
 """
 K528: NFP (Non-Farm Payrolls) Event Study on SPY Volatility
 =============================================================
 Extends K513 (FOMC/NFP/CPI event study) with deeper NFP-specific analysis.
 
 K513 finding: NFP vol ratio = 1.09x (NS, p=0.195). This study digs deeper:
   - Larger sample with more granular windows
   - VIX predictive regression
   - Vol crush pattern analysis
   - Seasonal decomposition (which months matter?)
   - NFP surprise impact (FRED PAYEMS data)
 
 Data sources:
   - SPY daily OHLCV: yfinance (2005-01 to 2026-03)
   - VIX daily close: yfinance (^VIX)
   - NFP dates: OFFICIAL BLS release calendar via ALFRED (FRED release id 50)
   - NFP actual values: FRED PAYEMS (monthly, for surprise calculation)
 
 CORRECTION 2026-07-19
 ---------------------
 The original run dated every NFP to the first Friday of the month. That proxy is
 wrong for ~20% of the sample and it is wrong SYSTEMATICALLY, not randomly: BLS
 moves the release to the second Friday whenever the reference week falls late
 (28 dates land exactly 7 days early), and pulls it forward around holidays (12
 dates land 3-4 days late). It also invents a release in 2025-10 that never
 happened, and it forces every event onto a Friday when 16 of the 254 official
 releases are not on a Friday at all.
 
 Wrong event dates do not fail loudly. They count quiet days as event days and
 dump real event days into the control group, and the figures still render. So
 the dates now come from the official release calendar and the run FAILS CLOSED
 if that calendar is unreachable -- `get_first_friday` is gone, not deprecated.
 
 This script also emits a before/after comparison against the archived proxy-era
 results so the correction's effect on every published number is auditable
 (k528_nfp_official_dates_results.json).
 
 References:
   - Savor & Wilson (2013) "How Much Do Investors Care About Macroeconomic Risk?"
     JFE, core finding: scheduled macro announcements earn risk premium
   - Lucca & Moench (2015) "The Pre-FOMC Announcement Drift" JFE
   - K513: Our prior FOMC/NFP/CPI event study (2005-2025, 668 events)
   - K1442: event-date audit that found this bug
 
 Author: VolPred Research System
 Date: 2026-03-27 (corrected 2026-07-19)
 """
 
 import json
 import os
 import tempfile
 import warnings
 from datetime import datetime, timezone
 from pathlib import Path
 
 import numpy as np
 import pandas as pd
 import yfinance as yf
 from scipy import stats
 
-from volpred.data.event_dates import nfp_release_dates
+from volpred.data.event_dates import RELEASE_IDS, _fetch, nfp_release_dates
 
 warnings.filterwarnings("ignore")
 
 SAMPLE_START = "2005-01-01"
 SAMPLE_END = "2026-03-27"
 
-# Months in [SAMPLE_START, SAMPLE_END] for which BLS published no Employment
-# Situation report at all. Anything absent from the calendar that is NOT listed
-# here is a data-integrity failure, not a known hole -- see check_calendar_is_complete.
-#
-# 2025-10: the federal government shutdown. ALFRED shows no release id 50 entry
-# between 2025-09-05 and 2025-11-20 (a 76-day gap against a ~30-day cadence);
-# the delayed September report came out on 11-20. This is the same shutdown that
-# cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py.
-# It is a real absence of an event, which is why the month is excluded rather
-# than back-filled -- the first-Friday proxy INVENTED an event here, and that
-# phantom event is one of the reasons this experiment was rerun.
-KNOWN_MISSING_MONTHS: set[str] = {"2025-10"}
+# Months for which BLS published no Employment Situation report at all. Each
+# entry needs a documented reason, and check_calendar_is_complete VERIFIES the
+# claim against the raw feed before honouring it -- an allowlist that is taken
+# on faith is just a way to make a failing check pass, which is the failure mode
+# this whole experiment exists to document.
+KNOWN_MISSING_MONTHS: dict[str, str] = {
+    "2025-10": (
+        "Federal government shutdown. ALFRED shows no release id 50 entry between "
+        "2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed "
+        "September report landed on 11-20. Same shutdown that cancelled the Oct-2025 "
+        "CPI release described in volpred/data/event_dates.py. The first-Friday proxy "
+        "INVENTED an event here -- that phantom is one of the reasons for this rerun."
+    ),
+}
+
+# Two same-month entries closer together than this cannot be told apart as
+# "regular report" vs "off-cycle revision" by date order alone, so the run
+# refuses to guess. Revisions are filed weeks after the report, not days.
+AMBIGUOUS_SAME_MONTH_GAP_DAYS = 3
 
 
 def write_json_atomic(path: Path, payload) -> None:
     """Write `payload` to `path` atomically.
 
     A truncate-then-write leaves a half-written results file on the disk if the
     run dies mid-dump, and a half-written results file is worse than none: it
     still parses far enough to look like data to the next reader. Write to a
     temp file in the same directory, fsync, then os.replace (atomic on POSIX).
     """
     path.parent.mkdir(parents=True, exist_ok=True)
     fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
     try:
         with os.fdopen(fd, "w") as f:
             json.dump(payload, f, indent=2, default=str)
             f.flush()
             os.fsync(f.fileno())
         os.replace(tmp, path)
     except BaseException:
         try:
             os.unlink(tmp)
         except FileNotFoundError:
             pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
         raise
 
 
 # ============================================================
 # 1. NFP dates: official BLS release calendar (no proxy, no fallback)
 # ============================================================
-def check_calendar_is_complete(dates, start, end):
+def check_calendar_is_complete(selected, raw, start, end):
     """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
 
     "Did the call succeed?" is the wrong question. A monthly release calendar
     that silently lost 2019 still returns a non-empty list, still produces
-    event windows, still renders. The three ways this input can be wrong
-    without being empty are: a month appears twice (off-cycle revision picked
-    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
-    range is not covered at all. All three raise here.
+    event windows, still renders.
+
+    This validates the RAW feed as well as the accessor's per-month selection.
+    Validating only the selection cannot work: the accessor collapses each month
+    to one date before this function ever sees it, so a same-month ambiguity is
+    already resolved -- silently, and possibly wrongly -- by the time a check on
+    the output could look for it. That is precisely how the k528 v2 BLOCKER got
+    through (Codex v3 finding 3).
+
+    Four ways the input can be wrong without being empty, all of which raise:
+      1. a month has two entries too close together to tell report from revision
+      2. the selection is not the earliest entry of its month
+      3. a month is missing from the observed span
+      4. a month is claimed as a known hole but the raw feed actually has data
     """
-    months = [pd.Timestamp(d).strftime("%Y-%m") for d in dates]
-
-    dupes = sorted({m for m in months if months.count(m) > 1})
-    if dupes:
+    sel = [pd.Timestamp(d) for d in selected]
+    sel_months = [d.strftime("%Y-%m") for d in sel]
+
+    raw_by_month: dict[str, list[pd.Timestamp]] = {}
+    for d in raw:
+        ts = pd.Timestamp(d)
+        raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
+    for v in raw_by_month.values():
+        v.sort()
+
+    # 1 + 2: same-month resolution must be unambiguous AND actually taken.
+    ambiguous, mis_selected = [], []
+    sel_by_month = dict(zip(sel_months, sel))
+    for month, entries in raw_by_month.items():
+        if len(entries) > 1:
+            gap = (entries[1] - entries[0]).days
+            if gap < AMBIGUOUS_SAME_MONTH_GAP_DAYS:
+                ambiguous.append(f"{month}: {entries[0].date()} vs {entries[1].date()} ({gap}d apart)")
+        if month in sel_by_month and sel_by_month[month] != entries[0]:
+            mis_selected.append(
+                f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
+            )
+    if ambiguous:
         raise RuntimeError(
-            f"official NFP calendar returned {len(dupes)} month(s) with more than one "
-            f"release date: {dupes}. The Employment Situation is published once per "
-            "month; a second same-month entry is an off-cycle revision and must not be "
-            "treated as an event. Fix the accessor, do not de-duplicate here."
+            f"{len(ambiguous)} month(s) carry two release entries too close together to "
+            f"identify the Employment Situation report by date order: {ambiguous}. "
+            "Revisions are filed weeks after the report, not days -- this shape means the "
+            "feed changed or the release id is carrying something new. Refusing to guess."
+        )
+    if mis_selected:
+        raise RuntimeError(
+            f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
+            f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
+            "monthly report -- selecting it is the k528 v2 BLOCKER."
         )
 
-    expected = {
+    # 3: no month may vanish from the observed span. Anchoring on the observed
+    # span rather than [start, end] removes the endpoint fudge that used to
+    # exempt the first and last month unconditionally (Codex v3 finding 3).
+    span = {
         p.strftime("%Y-%m")
-        for p in pd.period_range(start=pd.Timestamp(start), end=pd.Timestamp(end), freq="M")
+        for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
     }
-    # The endpoint months are partial by construction: a run ending 2026-03-27
-    # legitimately has 2026-03, but a run ending 2026-03-02 may not yet.
-    interior = {m for m in expected if m not in {min(expected), max(expected)}}
-    missing = sorted(interior - set(months) - KNOWN_MISSING_MONTHS)
+    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
     if missing:
         raise RuntimeError(
-            f"official NFP calendar is missing {len(missing)} month(s) inside the sample "
-            f"window: {missing}. A partial calendar dumps real event days into the control "
+            f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
+            f"span: {missing}. A partial calendar dumps real event days into the control "
             "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
             "reason (e.g. a cancelled release), never to make this check pass."
         )
-    return {"n_months_expected": len(interior), "known_missing_months": sorted(KNOWN_MISSING_MONTHS)}
+
+    # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
+    # allowlist is a bypass: any month could be declared 'known missing' and the
+    # check would stop looking at it.
+    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if m in span and raw_by_month.get(m))
+    if bogus:
+        raise RuntimeError(
+            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
+            f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
+            "The allowlist is for real cancellations, not for silencing a selection bug."
+        )
+
+    return {
+        "n_months_in_span": len(span),
+        "n_raw_entries": len(raw),
+        "months_with_multiple_raw_entries": sorted(m for m, v in raw_by_month.items() if len(v) > 1),
+        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
+        "ambiguity_gap_threshold_days": AMBIGUOUS_SAME_MONTH_GAP_DAYS,
+    }
 
 
 def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
     """Official NFP (Employment Situation) release dates.
 
     Deliberately has no except branch. If the release calendar cannot be
     reached, this run must die -- a proxy calendar produces plausible numbers
     from non-events, which is worse than no numbers at all. See the CORRECTION
     note in the module docstring.
     """
     dates = nfp_release_dates(start, end)
     if len(dates) == 0:
         raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
-    completeness = check_calendar_is_complete(dates, start, end)
+    # Pull the unselected feed as well: the accessor collapses each month to one
+    # date, so the only place a same-month ambiguity is still visible is here.
+    raw = _fetch(RELEASE_IDS["NFP_US"], start, end)
+    completeness = check_calendar_is_complete(dates, raw, start, end)
     return list(dates), completeness
 
 
 # ============================================================
 # 2. Download data
 # ============================================================
 print("=" * 60)
 print("K528: NFP Event Study on SPY Volatility")
 print("=" * 60)
 
 print("\n[1/6] Downloading SPY and VIX data...")
 spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
 vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)
 
 # Handle multi-level columns from yfinance
 if isinstance(spy.columns, pd.MultiIndex):
     spy.columns = spy.columns.get_level_values(0)
 if isinstance(vix.columns, pd.MultiIndex):
     vix.columns = vix.columns.get_level_values(0)
 
 # Calculate returns
 spy["Return"] = spy["Close"].pct_change()
 spy["AbsReturn"] = spy["Return"].abs()
 spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
 spy.dropna(subset=["Return"], inplace=True)
 
 # Merge VIX
 vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
 spy = spy.join(vix_close, how="left")
 spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays
 
 print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
 print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")
 
 # ============================================================
 # 3. Map NFP dates to trading days
 # ============================================================
 print("\n[2/6] Mapping NFP dates to trading days...")
 
 nfp_calendar, calendar_completeness = load_nfp_dates()
 trading_dates = spy.index
 
 # The proxy forced every event onto a Friday. The official calendar does not,
 # and that is load-bearing for the Friday-baseline test below.
 n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
 print(f"  Official releases: {len(nfp_calendar)} "
       f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
 
 # Map each NFP date to the session that trades the news. The report drops at
 # 08:30 ET, before the open, so a release on a closed day is traded at the next
 # open -- hence "next trading day", not "nearest". Every release must land on
 # exactly one session and no two releases may share one: both failures shrink
 # the event set without shrinking any count that gets printed.
 release_to_session = {}
 unmapped = []
 for nfp_date in nfp_calendar:
     nfp_ts = pd.Timestamp(nfp_date)
     if nfp_ts in trading_dates:
         release_to_session[nfp_ts] = nfp_ts
         continue
     mask = (trading_dates > nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
     candidates = trading_dates[mask]
     if len(candidates) > 0:
         release_to_session[nfp_ts] = candidates[0]
     else:
         unmapped.append(nfp_ts.date().isoformat())
 
 # In-sample releases must map. Releases outside the price series (the calendar
 # window can overhang the SPY history on either end) are excluded by design,
 # not by failure, so they are separated before the assertion.
 in_sample_unmapped = [
     d for d in unmapped
     if trading_dates[0] <= pd.Timestamp(d) <= trading_dates[-1]
 ]
 if in_sample_unmapped:
     raise RuntimeError(
         f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
         f"trading session within 3 days: {in_sample_unmapped}. Silently skipping them would "
         "drop real event days into the control group."
     )
@@ -260,207 +323,226 @@ valid_nfp = [d for d in nfp_trading_dates
 
 if len(valid_nfp) + len(window_excluded) != len(nfp_trading_dates):
     raise RuntimeError("event-window partition lost events; refusing to continue")
 
 mapping_audit = {
     "n_official_releases": len(nfp_calendar),
     "n_mapped_to_sessions": len(nfp_trading_dates),
     "n_shifted_to_next_session": n_shifted,
     "n_outside_price_sample": len(unmapped),
     "outside_price_sample_dates": sorted(unmapped),
     "n_excluded_for_window_buffer": len(window_excluded),
     "window_excluded_dates": [str(d.date()) for d in window_excluded],
     "n_valid_events": len(valid_nfp),
 }
 
 print(f"  Total official releases: {len(nfp_calendar)}")
 print(f"  Mapped to trading sessions: {len(nfp_trading_dates)} ({n_shifted} shifted to next open)")
 print(f"  Outside price sample: {len(unmapped)}")
 print(f"  Excluded for window buffer: {len(window_excluded)}")
 print(f"  Valid (with pre/post window): {len(valid_nfp)}")
 
 # ============================================================
 # 4. Calculate event windows
 # ============================================================
 print("\n[3/6] Calculating event window statistics...")
 
 results = []
 idx_list = list(trading_dates)
 
 for nfp_date in valid_nfp:
     pos = idx_list.index(nfp_date)
 
     # Pre-event: T-5 to T-1
     pre_window = spy.iloc[pos-5:pos]
     # Event day: T
     event_day = spy.iloc[pos]
     # Post-event: T+1 to T+5
     post_window = spy.iloc[pos+1:pos+6]
 
     # Unreachable given the window-buffer partition above. Kept as an assertion
     # rather than a `continue`: if the partition ever stops holding, the run
     # must stop, not quietly analyse a smaller sample than it reports.
     if len(pre_window) < 5 or len(post_window) < 5:
         raise RuntimeError(
             f"event {nfp_date.date()} has an incomplete window "
             f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
             "window-buffer filter -- the partition and the window logic disagree"
         )
 
     row = {
         "date": nfp_date.strftime("%Y-%m-%d"),
         "year": nfp_date.year,
         "month": nfp_date.month,
         "weekday": nfp_date.weekday(),  # should be 4 (Friday)
         "event_return": float(event_day["Return"]),
         "event_abs_return": float(event_day["AbsReturn"]),
         "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
         "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
         "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
         "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
         "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
         "vix_change_event": None,
         "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
         "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
     }
 
     if row["pre_vix"] is not None and row["event_vix"] is not None:
         row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
 
     results.append(row)
 
 df = pd.DataFrame(results)
 print(f"  Events with complete data: {len(df)}")
 print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
 
 # ============================================================
 # 5. Non-NFP baseline calculation
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
 
 print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
 print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
 print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
 
 # ============================================================
 # 6. Statistical tests
 # ============================================================
 print("\n[5/6] Running statistical tests...")
 
 nfp_abs_returns = df["event_abs_return"].values
 non_nfp_abs_returns = non_nfp["AbsReturn"].values
 friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
 
 # --- Test A: NFP vs all non-NFP days ---
 t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
 vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
 
 # --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
 #
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
 
 t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
 vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
 
 # Diagnostic ONLY -- the pre-correction specification, kept so the correction
 # audit can show what the contaminated estimand was worth. Not a headline
 # number and not eligible to be quoted: its p-value mixes in weekday
 # composition, which is exactly the defect being repaired.
 t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
     nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
 vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
 
 # --- Test C: Wilcoxon rank-sum (non-parametric) ---
 u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
 
 # --- Test D: Vol crush pattern (post vs pre) ---
 vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
 t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
 
 # --- Test E: VIX predictive regression ---
 vix_valid = df.dropna(subset=["pre_vix"])
 if len(vix_valid) > 10:
     from numpy.polynomial.polynomial import polyfit
     X_vix = vix_valid["pre_vix"].values
     Y_abs = vix_valid["event_abs_return"].values
     slope, intercept = np.polyfit(X_vix, Y_abs, 1)
     # correlation and p-value
     r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
     # also spearman
     rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
 else:
     slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6
 
 # --- Test F: Pre-event VIX change (buildup) ---
 # Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
 vix_buildup = []
 for nfp_date in valid_nfp:
     pos = idx_list.index(nfp_date)
     pre5 = spy.iloc[pos-5]
     pre1 = spy.iloc[pos-1]
     if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
         vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))
 
 t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
 
 # --- Test G: Seasonal analysis (by month) ---
 monthly_stats = {}
 for month in range(1, 13):
     month_data = df[df["month"] == month]["event_abs_return"]
     if len(month_data) >= 5:
         monthly_stats[str(month)] = {
             "n": int(len(month_data)),
             "mean_abs_return": float(month_data.mean()),
             "vol_ratio": float(month_data.mean() / baseline_abs_return),
             "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
             "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
         }
 
 # --- Test H: Regime analysis (high VIX vs low VIX) ---
 vix_median = df["pre_vix"].median()
 high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
 low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
 t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
 
 # --- Test I: Time trend (has NFP impact changed over time?) ---
 # Split into halves
 midpoint = len(df) // 2
 first_half = df.iloc[:midpoint]["event_abs_return"]
 second_half = df.iloc[midpoint:]["event_abs_return"]
 t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
 
 # --- Test J: Event-day return direction ---
 pos_returns = (df["event_return"] > 0).sum()
 neg_returns = (df["event_return"] < 0).sum()
 # Binomial test: is there a directional bias?
 binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)
 
@@ -517,327 +599,356 @@ if t_buildup is not None:
 
 print(f"\n--- G. Seasonal Pattern (by month) ---")
 print(f"  {'Month':<8} {'N':<5} {'Avg |Ret|':<12} {'Ratio':<8} {'t-stat':<8} {'p-val':<8}")
 month_names = {1:'Jan', 2:'Feb', 3:'Mar', 4:'Apr', 5:'May', 6:'Jun',
                7:'Jul', 8:'Aug', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dec'}
 for m in range(1, 13):
     if str(m) in monthly_stats:
         ms = monthly_stats[str(m)]
         sig = "*" if ms["p_val"] < 0.05 else ""
         print(f"  {month_names[m]:<8} {ms['n']:<5} {ms['mean_abs_return']:.6f}    {ms['vol_ratio']:.3f}x  {ms['t_stat']:>7.3f}  {ms['p_val']:.4f} {sig}")
 
 print(f"\n--- H. VIX Regime Analysis ---")
 print(f"  VIX median split:     {vix_median:.1f}")
 print(f"  High VIX NFP |ret|:   {high_vix.mean():.6f} (n={len(high_vix)})")
 print(f"  Low VIX NFP |ret|:    {low_vix.mean():.6f} (n={len(low_vix)})")
 print(f"  t-stat:               {t_regime:.3f}")
 print(f"  p-value:              {p_regime:.4f}")
 
 print(f"\n--- I. Time Trend (First Half vs Second Half) ---")
 print(f"  First half |ret|:     {first_half.mean():.6f} (n={len(first_half)}, ~{df['date'].iloc[0][:4]}-{df['date'].iloc[midpoint-1][:4]})")
 print(f"  Second half |ret|:    {second_half.mean():.6f} (n={len(second_half)}, ~{df['date'].iloc[midpoint][:4]}-{df['date'].iloc[-1][:4]})")
 print(f"  t-stat:               {t_trend:.3f}")
 print(f"  p-value:              {p_trend:.4f}")
 
 print(f"\n--- J. Directional Bias ---")
 print(f"  Positive returns:     {pos_returns}/{len(df)} ({pos_returns/len(df)*100:.1f}%)")
 print(f"  Negative returns:     {neg_returns}/{len(df)} ({neg_returns/len(df)*100:.1f}%)")
 print(f"  Binomial p-value:     {binom_p:.4f}")
 
 # ============================================================
 # 7. High-low range analysis (intraday vol proxy)
 # ============================================================
 print(f"\n--- K. Intraday Range (High-Low / Close) ---")
 nfp_range = df["high_low_range"].mean()
 non_nfp_range = float(((spy["High"] - spy["Low"]) / spy["Close"])[non_nfp_mask].mean())
 range_ratio = nfp_range / non_nfp_range
 print(f"  NFP day range:        {nfp_range:.6f} ({nfp_range*100:.3f}%)")
 print(f"  Non-NFP range:        {non_nfp_range:.6f} ({non_nfp_range*100:.3f}%)")
 print(f"  Range ratio:          {range_ratio:.3f}x")
 
 # Volume analysis
 print(f"\n--- L. Volume Analysis ---")
 vol_ratio_data = df["volume_ratio"].dropna()
 print(f"  NFP/avg volume ratio: {vol_ratio_data.mean():.3f}x")
 print(f"  NFP volume > avg:     {(vol_ratio_data > 1).sum()}/{len(vol_ratio_data)} ({(vol_ratio_data > 1).mean()*100:.1f}%)")
 
 # ============================================================
 # 8. April NFP specific (for upcoming 04/03 article)
 # ============================================================
 print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
 april_nfp = df[df["month"] == 4]
 print(f"  April NFP events:     {len(april_nfp)}")
 print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
 print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
 print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
 if "4" in monthly_stats:
     ms4 = monthly_stats["4"]
     print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")
 
 # ============================================================
 # 9. Summary conclusion
 # ============================================================
 print(f"\n{'=' * 60}")
 print("SUMMARY CONCLUSION")
 print("=" * 60)
 
 sig_level = 0.05
 conclusions = []
 
 # Each conclusion names the test it came from. The previous run collapsed
 # several tests into "insignificant across all tests" while the one-sided
 # Mann-Whitney in the same artifact was significant at p<0.01 -- a summary that
 # contradicted its own numbers. A Welch test on |return| is a test of MEANS;
 # it not rejecting is not a finding that the distributions match, and it is
 # never evidence that the effect is zero.
 conclusions.append(
     f"Welch mean-difference, NFP vs all non-NFP days: {vol_ratio_all:.2f}x, "
     f"p={p_val_all:.4f} ({'rejects' if p_val_all < sig_level else 'does not reject'} at 5%)"
 )
 conclusions.append(
-    f"Welch mean-difference, Friday NFP vs Friday non-NFP (weekday held fixed): "
-    f"{vol_ratio_fri:.2f}x, p={p_val_fri:.4f} "
+    f"Welch mean-difference, Friday NFP vs Friday non-NFP (CONDITIONAL ON FRIDAY, "
+    f"weekday held fixed): {vol_ratio_fri:.2f}x, p={p_val_fri:.4f} "
     f"({'rejects' if p_val_fri < sig_level else 'does not reject'} at 5%; "
-    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)})"
+    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)}). Scoped to Friday "
+    f"releases; the {len(nfp_nonfriday_abs)} non-Friday events are quieter, so this "
+    f"is not a statement about NFP releases in general."
 )
 conclusions.append(
     f"Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: "
     f"p={p_val_wilcox:.5f} ({'rejects' if p_val_wilcox < sig_level else 'does not reject'} at 5%)"
 )
 if (p_val_all >= sig_level) != (p_val_wilcox >= sig_level):
     conclusions.append(
         "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, "
         "so a rank test can detect a location shift the Welch mean test cannot. "
         "Report both; do not summarise them as a single verdict."
     )
 
 if vol_crush.mean() < 0 and p_crush < sig_level:
     conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
 else:
     conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")
 
 if r_vix is not None and p_vix < sig_level:
     conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
 else:
     conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")
 
 for c in conclusions:
     print(f"  • {c}")
 
 print(f"\n  Practical implication:")
 print(f"    → Entry VIX regime is the larger and more reliably measured effect "
       f"({high_vix.mean()/low_vix.mean():.2f}x, p={p_regime:.4g})")
 print(f"    → The NFP-day effect is smaller; mean and rank tests do not agree on it, "
       f"so it is not established either way")
 print(f"    → Non-significance of a mean test is not evidence of no effect")
 
 # ============================================================
 # 9b. Correction audit: every published number, before vs after
 # ============================================================
 # A mean can sit still while the median and the win rate move underneath it,
 # so no claim is judged on its mean alone. Each item carries mean / median /
 # win rate / n / significance, and the flip test looks at all of them.
 print(f"\n{'=' * 60}")
 print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
 print("=" * 60)
 
 PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
 if not PROXY_PATH.exists():
     raise FileNotFoundError(
         f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
         "only record of what the published article claimed. Do not regenerate it."
     )
 proxy = json.loads(PROXY_PATH.read_text())
 
 
 def win_rate(sample, reference):
     """Share of `sample` above the median of `reference` (0.5 under the null)."""
     ref_med = float(np.median(reference))
     return float(np.mean(np.asarray(sample) > ref_med))
 
 
 # The proxy run only ever reported means, and a mean can hold still while the
 # median and the win rate move underneath it. Rather than leave the before-side
 # of those two columns null -- which would make the comparison unable to detect
 # exactly the failure it is looking for -- rebuild the proxy-era distributions
 # from the ARCHIVED per-event data. The dates come out of the archive, so this
 # reconstructs history without reintroducing a proxy calendar generator.
 proxy_events = proxy["event_data"]
 proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
 proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
 proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
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
 proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
 proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
 
 # Sanity: the rebuilt means must reproduce the archived means, otherwise the
 # reconstruction is wrong and its medians cannot be trusted either.
 for _label, _rebuilt, _archived in (
     ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
     ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
     ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
     ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
 ):
     if not np.isclose(_rebuilt, _archived, rtol=1e-6):
         raise AssertionError(
             f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
             f"vs archived {_archived:.8f}. Refusing to report medians derived "
             "from a reconstruction that cannot reproduce the archived means."
         )
 print("  proxy-era distributions reconstructed from archive (means reproduce)")
 
 audit_items = {}
 
 
 def record(key, label, before, after, note=""):
     audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
 
 
 # --- 1.10x : NFP vs all non-NFP days ---
 record(
     "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
     {
         "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
         "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
         "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
         "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
         "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
         "n": proxy["sample"]["total_nfp_events"],
         "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
         "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
     },
     {
         "mean_ratio": vol_ratio_all,
         "nfp_mean": float(nfp_abs_returns.mean()),
         "baseline_mean": baseline_abs_return,
         "p_value": float(p_val_all),
         "significant_5pct": bool(p_val_all < 0.05),
         "n": int(len(df)),
         "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
         "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
     },
     note="proxy-side median_ratio / win_rate are reconstructed from the archived "
          "per-event data, not from the proxy run's own output (it only reported means).",
 )
 
 # --- 1.17x : NFP vs Friday-only baseline ---
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
         "p_value": float(p_val_fri),
         "significant_5pct": bool(p_val_fri < 0.05),
         "n": int(len(nfp_friday_abs)),
         "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
         "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
         "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
         "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
         "diagnostic_mixed_weekday": {
             "mean_ratio": vol_ratio_fri_mixed,
             "p_value": float(p_val_fri_mixed),
             "significant_5pct": bool(p_val_fri_mixed < 0.05),
             "n": int(len(df)),
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
 proxy_reg = proxy["regime_analysis"]
 record(
     "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
     {
         "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
         "high_mean": proxy_reg["high_vix_nfp_abs_return"],
         "low_mean": proxy_reg["low_vix_nfp_abs_return"],
         "n_high": proxy_reg["n_high"],
         "n_low": proxy_reg["n_low"],
         "p_value": proxy_reg["p_value"],
         "significant_5pct": proxy_reg["p_value"] < 0.05,
         "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
         "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
     },
     {
         "mean_ratio": float(high_vix.mean() / low_vix.mean()),
         "high_mean": float(high_vix.mean()),
         "low_mean": float(low_vix.mean()),
         "n_high": int(len(high_vix)),
         "n_low": int(len(low_vix)),
         "p_value": float(p_regime),
         "significant_5pct": bool(p_regime < 0.05),
         "median_ratio": float(high_vix.median() / low_vix.median()),
         "win_rate": win_rate(high_vix.values, low_vix.values),
     },
 )
 
 # --- 0.45 : pre-event VIX correlation ---
 proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
 record(
     "vix_correlation", "Pre-event VIX vs event-day |return| (article: r=0.45)",
     {
         "pearson_r": proxy_e["pearson_r"],
         "pearson_p": proxy_e["pearson_p"],
         "spearman_rho": proxy_e["spearman_rho"],
         "spearman_p": proxy_e["spearman_p"],
         "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
         "n": proxy["sample"]["total_nfp_events"],
         "significant_5pct": proxy_e["pearson_p"] < 0.05,
     },
     {
         "pearson_r": float(r_vix),
         "pearson_p": float(p_vix),
         "spearman_rho": float(rho_vix),
         "spearman_p": float(p_rho_vix),
         "slope_pct_per_vix_pt": float(slope) * 100,
         "n": int(len(vix_valid)),
         "significant_5pct": bool(p_vix < 0.05),
     },
 )
 
 # --- 16.71 : the VIX median that splits the regimes ---
 # The article uses this threshold to place a specific date (2026-07-01 VIX
 # 16.59) on the low-VIX side. If the threshold crosses 16.59 the article's
 # worked example inverts, so it is audited as a claim in its own right.
 proxy_thr = proxy_reg["vix_median_split"]
 record(
     "vix_median_threshold", "VIX median split (article: 16.71)",
     {
         "threshold": proxy_thr,
         "n": proxy["sample"]["total_nfp_events"],
         "places_20260701_vix_1659_in": "low" if 16.59 < proxy_thr else "high",
     },
     {
         "threshold": float(vix_median),
         "n": int(df["pre_vix"].notna().sum()),
         "places_20260701_vix_1659_in": "low" if 16.59 < float(vix_median) else "high",
     },
 )
 
 # --- 254 : the sample itself ---
 proxy_dates = {r["date"] for r in proxy["event_data"]}
 new_dates = {r["date"] for r in results}
 record(
     "sample", "NFP event sample (article: 254 events)",
     {
         "n": proxy["sample"]["total_nfp_events"],
@@ -868,164 +979,180 @@ def verdict_for(key):
                 f"{'sig' if a['significant_5pct'] else 'NS'})"
             )
     # The mean is not trusted on its own: the median and the win rate are
     # checked independently, because the failure mode this audit exists to
     # catch is a stable mean sitting on top of a moved distribution.
     for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
         if field in b and field in a and b[field] and a[field]:
             rel = abs(a[field] - b[field]) / abs(b[field])
             if rel > 0.10:
                 reasons.append(f"{field} moved {rel * 100:.1f}%")
     if b.get("win_rate") and a.get("win_rate"):
         if abs(a["win_rate"] - b["win_rate"]) > 0.05:
             reasons.append(
                 f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
             )
     if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
         reasons.append("the article's worked example changes regime")
     return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons
 
 
 print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
 for key, item in audit_items.items():
     v, reasons = verdict_for(key)
     item["verdict"], item["verdict_reasons"] = v, reasons
     headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
                      if f in item["before"]), None)
     bf = item["before"].get(headline)
     af = item["after"].get(headline)
     fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
     print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
     for r in reasons:
         print(f"      - {r}")
 
 n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
 print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
 
 # ============================================================
 # 10. Save results
 # ============================================================
 print("\n[6/6] Saving results...")
 
 output = {
     "experiment_id": "K528",
     "title": "NFP Event Study on SPY Volatility",
     "date": datetime.now(timezone.utc).isoformat(),
     "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
     "event_date_source": {
         "source": "official BLS release calendar via ALFRED (FRED release id 50)",
         "accessor": "volpred.data.event_dates.nfp_release_dates",
         "fallback": "none - the run raises if the calendar is unreachable",
         "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
     },
     "sample": {
         "total_nfp_events": len(df),
         "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
         "non_nfp_trading_days": int(non_nfp_mask.sum()),
         "friday_baseline_days": int(friday_mask.sum()),
         "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
         "event_mapping_audit": mapping_audit,
         "calendar_completeness": calendar_completeness,
     },
     "main_results": {
         "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
         "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
         "non_nfp_avg_abs_return": baseline_abs_return,
         "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
         "friday_baseline_abs_return": friday_baseline,
         "vol_ratio_vs_all": vol_ratio_all,
         "vol_ratio_vs_friday": vol_ratio_fri,
     },
     "statistical_tests": {
         "A_nfp_vs_all": {
             "test": "Welch t-test",
             "t_stat": float(t_stat_all),
             "p_value": float(p_val_all),
             "significant_5pct": bool(p_val_all < 0.05),
         },
         "B_nfp_vs_friday": {
             "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
             "estimand": (
-                "weekday held fixed on both sides. Event group restricted to NFP "
-                "releases that trade on a Friday; the 11 non-Friday events are "
-                "excluded rather than compared against a pure-Friday control group."
+                "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event "
+                "group is restricted to NFP releases that trade on a Friday, and the "
+                f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
+                "than compared against a pure-Friday control group."
             ),
+            "claim_scope": (
+                "This identifies the effect of an NFP release ON A FRIDAY. It does not "
+                "license a statement about NFP releases in general -- the excluded "
+                "non-Friday events are quieter, so the restriction raises the ratio "
+                "relative to the mixed-weekday spec. Any prose quoting this number must "
+                "say 'Friday NFP', not 'NFP'."
+            ),
+            "restriction_is_not_neutral": {
+                "excluded_mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
+                "friday_mean_abs_return": float(nfp_friday_abs.mean()),
+                "excluded_are_quieter_by_pct": (
+                    float((nfp_friday_abs.mean() - nfp_nonfriday_abs.mean()) / nfp_friday_abs.mean() * 100)
+                    if len(nfp_nonfriday_abs) else None
+                ),
+            },
             "n_event": int(len(nfp_friday_abs)),
             "n_control": int(len(friday_non_nfp_abs)),
             "vol_ratio": vol_ratio_fri,
             "t_stat": float(t_stat_fri),
             "p_value": float(p_val_fri),
             "significant_5pct": bool(p_val_fri < 0.05),
             "excluded_non_friday_events": {
                 "n": int(len(nfp_nonfriday_abs)),
                 "mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
             },
         },
         "B_diagnostic_mixed_weekday": {
             "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
             "status": "DIAGNOSTIC ONLY - do not quote",
             "why_not_a_headline": (
                 "this is the pre-correction specification: a weekday-mixed event "
                 "group against a pure-Friday control group, so the p-value absorbs "
                 "any Friday-vs-other-weekday volatility difference. Retained solely "
                 "so the correction audit can show what the contaminated estimand was "
                 "worth (k528 Codex v2 finding 5)."
             ),
             "vol_ratio": vol_ratio_fri_mixed,
             "t_stat": float(t_stat_fri_mixed),
             "p_value": float(p_val_fri_mixed),
             "significant_5pct": bool(p_val_fri_mixed < 0.05),
         },
         "C_wilcoxon": {
             "test": "Mann-Whitney U (one-sided)",
             "u_stat": float(u_stat),
             "p_value": float(p_val_wilcox),
             "significant_5pct": bool(p_val_wilcox < 0.05),
         },
         "D_vol_crush": {
             "test": "One-sample t-test (post-pre diff)",
             "pre_avg": float(df["pre_avg_abs_return"].mean()),
             "post_avg": float(df["post_avg_abs_return"].mean()),
             "diff": float(vol_crush.mean()),
             "t_stat": float(t_crush),
             "p_value": float(p_crush),
             "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
         },
         "E_vix_predictive": {
             "test": "Pearson + Spearman correlation",
             "pearson_r": float(r_vix) if r_vix else None,
             "pearson_p": float(p_vix) if p_vix else None,
             "spearman_rho": float(rho_vix) if rho_vix else None,
             "spearman_p": float(p_rho_vix) if p_rho_vix else None,
             "slope": float(slope) if slope else None,
             "interpretation": f"1pt VIX → {slope*100:.4f}% more |return|" if slope else None,
         },
         "F_vix_buildup": {
             "test": "One-sample t-test (T-5 to T-1 VIX change)",
             "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
             "t_stat": float(t_buildup) if t_buildup else None,
             "p_value": float(p_buildup) if p_buildup else None,
             "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
         },
     },
     "seasonal_analysis": monthly_stats,
     "regime_analysis": {
         "vix_median_split": float(vix_median),
         "high_vix_nfp_abs_return": float(high_vix.mean()),
         "low_vix_nfp_abs_return": float(low_vix.mean()),
         "n_high": int(len(high_vix)),
         "n_low": int(len(low_vix)),
         "t_stat": float(t_regime),
         "p_value": float(p_regime),
     },
     "time_trend": {
         "first_half_abs_return": float(first_half.mean()),
         "second_half_abs_return": float(second_half.mean()),
         "t_stat": float(t_trend),
         "p_value": float(p_trend),
     },
     "directional_bias": {
         "positive_count": int(pos_returns),
         "negative_count": int(neg_returns),
         "total": int(pos_returns + neg_returns),
         "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
         "binomial_p": binom_p,
diff --git a/tests/test_event_dates_real_raw_response.py b/tests/test_event_dates_real_raw_response.py
index 3ddb525b9..a08a66173 100644
--- a/tests/test_event_dates_real_raw_response.py
+++ b/tests/test_event_dates_real_raw_response.py
@@ -1,94 +1,101 @@
-"""Regression test against the VERBATIM ALFRED raw response.
+"""Regression test against the unedited ALFRED release-date feed.
 
 Why this file exists, separately from test_event_dates_release_selection.py:
 
 The 42 tests that were green when Codex reviewed k528 all fed `release_dates`
 a *hand-built* fixture in which the same-month duplicate entries had already
 been removed. So they exercised the selection rule against input that could
 not express the bug. The old per-month `max()` rule shipped 6 wrong NFP event
 dates and flipped a significance result with a fully green suite.
 
 The fix for a fixture that cannot express the bug is not a better assertion —
-it is real input. This module pins `_fetch`'s actual bytes for release id 50
-(Employment Situation, 2005-01-01..2026-07-19, 264 entries) and asserts the
-six regular releases survive selection.
+it is real input. This module pins the unedited return value of `_fetch` for
+release id 50 (Employment Situation, 2005-01-01..2026-07-19, 264 entries) and
+asserts the six regular releases survive selection.
+
+SCOPE — what this fixture is and is not (Codex v3 finding 6): it is `_fetch`'s
+output, i.e. the `release_dates[].date` list exactly as the live API returned
+it on 2026-07-19, with nothing removed. It is NOT the full HTTP response body,
+so it does not cover JSON envelope changes, pagination, or field renames — a
+schema break in `_fetch` itself would not be caught here. What it does cover is
+the selection semantics downstream of `_fetch`, which is where the k528 bug was.
 
 Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
 it — the duplicate pairs ARE the regression surface).
 """
 from __future__ import annotations
 
 import json
 from pathlib import Path
 
 import pytest
 
 from volpred.data import event_dates
 
 _FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
 
 # The six months ALFRED returns twice for, with the regular Employment Situation
 # release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
 # filed against the same release id LATER in the month). Verified against the
 # live API on 2026-07-19; the right-hand column is exactly what the old max()
 # rule picked and what k528's contaminated run treated as NFP event days.
 OFF_CYCLE_PAIRS = {
     "2006-05": ("2006-05-05", "2006-05-08"),
     "2012-12": ("2012-12-07", "2012-12-12"),
     "2013-05": ("2013-05-03", "2013-05-06"),
     "2020-05": ("2020-05-08", "2020-05-11"),
     "2024-01": ("2024-01-05", "2024-01-10"),
     "2024-08": ("2024-08-02", "2024-08-21"),
 }
 
 
 @pytest.fixture(autouse=True)
 def _sandbox_cache_dir(monkeypatch, tmp_path):
     # No test may touch the canonical storage/data cache dir (CI repo-state guard).
     monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
 
 
 @pytest.fixture
 def raw_response() -> list[str]:
     return json.loads(_FIXTURE.read_text())["release_dates"]
 
 
 @pytest.fixture
 def selected(monkeypatch, raw_response) -> list[str]:
     monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw_response))
     idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
     return [str(d.date()) for d in idx]
 
 
 def test_fixture_still_carries_the_duplicate_months(raw_response):
     """Guard the guard: if someone 'cleans' the fixture, the suite goes quiet again."""
     by_month: dict[str, list[str]] = {}
     for d in raw_response:
         by_month.setdefault(d[:7], []).append(d)
     multi = {m: v for m, v in by_month.items() if len(v) > 1}
     assert set(multi) == set(OFF_CYCLE_PAIRS), (
         "fixture must keep exactly the six same-month duplicate pairs verbatim; "
         f"got {sorted(multi)}"
     )
     for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
         assert sorted(multi[month]) == [regular, off_cycle]
 
 
 def test_regular_release_wins_in_every_duplicate_month(selected):
     for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
         in_month = [d for d in selected if d.startswith(month)]
         assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
         assert off_cycle not in selected, f"{off_cycle} is an off-cycle revision, not an NFP event"
 
 
 def test_selection_is_one_per_month_and_complete(selected, raw_response):
     months_in = {d[:7] for d in raw_response}
     months_out = [d[:7] for d in selected]
     assert len(months_out) == len(set(months_out)), "more than one event date in some month"
     assert set(months_out) == months_in, "selection dropped or invented a month"
     assert len(selected) == 258
 
 
 def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
     """Mutation check: the OLD rule must fail this file, or it proves nothing.
 
diff --git a/tests/test_nfp_official_release_dates.py b/tests/test_nfp_official_release_dates.py
index decf44024..8f3a091ee 100644
--- a/tests/test_nfp_official_release_dates.py
+++ b/tests/test_nfp_official_release_dates.py
@@ -258,230 +258,371 @@ class TestNoLookahead:
         except _StopEarly:
             pass  # silent-ok: sentinel to stop main() once args are captured
         return calls
 
     def test_every_series_is_downloaded(self, experiment, monkeypatch):
         """Pin the call count so the assertions below cannot pass vacuously."""
         calls = self._capture_downloads(experiment, monkeypatch)
         assert [c["ticker"] for c in calls] == self.EXPECTED_TICKERS
 
     def test_download_window_ends_before_the_release(self, experiment, monkeypatch):
         calls = self._capture_downloads(experiment, monkeypatch)
         assert len(calls) == len(self.EXPECTED_TICKERS)
         for call in calls:
             # yfinance `end` is exclusive, so end == release date means the
             # last obtainable session is 2026-07-01.
             assert call["end"] == "2026-07-02", (
                 f"{call['ticker']} download window ends at {call['end']!r}; "
                 "the 2026-07-02 release day must not be downloadable"
             )
 
     def test_download_window_starts_before_the_earliest_event(
         self, experiment, monkeypatch
     ):
         calls = self._capture_downloads(experiment, monkeypatch)
         # Guard against all([]) passing vacuously if nothing was captured.
         assert len(calls) == len(self.EXPECTED_TICKERS)
         # Needs a prior close to difference against 2025-05-02.
         assert all(call["start"] < "2025-05-02" for call in calls)
 
 
 class _StopEarly(Exception):
     """Abort main() once the download arguments have been observed."""
 
 
 class _Tripwire:
     """Stand-in for a downloaded frame that raises when first consumed.
 
     Lets every `yf.download` call run and be recorded before main() is
     aborted, so the ticker-sequence assertion can see a download that does
     not exist yet. main() touches `.columns` first when it flattens the
     MultiIndex.
     """
 
     @property
     def columns(self):
         raise _StopEarly()
 
 
 class TestNoProxyResidue:
     """Source-level guard. The behavioural tests above can all pass while a
     dormant proxy helper sits in the file waiting to be called again."""
 
     def test_experiment_defines_no_first_friday_helper(self):
         src = EXPERIMENT_PY.read_text(encoding="utf-8")
         assert "def first_friday" not in src
         assert "(4 - d.weekday()) % 7" not in src
 
     def test_experiment_imports_the_official_calendar(self):
         src = EXPERIMENT_PY.read_text(encoding="utf-8")
         assert "from volpred.data.event_dates import nfp_release_dates" in src
 
     def test_results_json_declares_its_event_date_source(self):
         import json
 
         results = json.loads(
             (EXPERIMENT_DIR / "event_article_nfp_2026_07_03_t1_results.json")
             .read_text(encoding="utf-8")
         )
         assert results["nfp_release_date"] == "2026-07-02"
         assert "nfp_release_dates" in results["event_date_source"]
         assert [r["nfp_release_date"] for r in results["historical_nfp_table"]] == (
             EXPECTED_TRAILING_13
         )
 
 
 # ---------------------------------------------------------------------------
 # K528 -- the same proxy, the same bug, a 21-year sample.
 #
 # The sibling experiment above had 13 events. K528 had 254 and fed six numbers
 # straight into a published article (mile_35eef830). Correcting its calendar
-# swapped 46 of them, and the NFP-vs-Friday result stopped being significant
-# (p 0.0335 -> 0.0571). Same module rather than a new file: "NFP event dates
-# are official" is one concern and should keep one enforcement owner.
+# swapped dates but reversed NO conclusion.
+#
+# An intermediate 2026-07-19 rerun did report the NFP-vs-Friday result flipping
+# to non-significant (p 0.0335 -> 0.0571). That was WRONG and is recorded here
+# so it is not repeated: the accessor was picking off-cycle revision entries for
+# six months, and on correct dates the comparison stays significant
+# (1.189x, p=0.021). A retraction of a correct finding was one Codex review away
+# from being published. Same module rather than a new file: "NFP event dates are
+# official" is one concern and should keep one enforcement owner.
 # ---------------------------------------------------------------------------
 
 K528_DIR = REPO_ROOT / "experiments" / "k528"
 K528_PY = K528_DIR / "k528_nfp_event_study.py"
 K528_RESULTS = K528_DIR / "k528_nfp_event_study_results.json"
 K528_AUDIT = K528_DIR / "k528_nfp_official_dates_results.json"
 
 
 def _load_k528(path):
     import json
 
     return json.loads(path.read_text(encoding="utf-8"))
 
 
 def _k528_event_dates():
     return [pd.Timestamp(e["date"]) for e in _load_k528(K528_RESULTS)["event_data"]]
 
 
 def assert_not_first_friday_proxy(dates):
     """Reject a calendar carrying the first-Friday proxy's fingerprints.
 
     Three independent signatures, because a partial revert should be caught as
     readily as a total one. This is the function the mutation test below fires
     a proxy calendar at: a guard nobody has ever seen fail is not a guard.
     """
     dates = pd.DatetimeIndex(dates)
     if len(dates) == 0:
         raise AssertionError("empty calendar")
 
     if (dates.weekday == 4).all():
         raise AssertionError(
             f"all {len(dates)} releases fall on a Friday. The official calendar "
             "does not: BLS moves the release off Friday at holiday and shutdown "
             "boundaries. This is the proxy's signature."
         )
 
     on_first_friday = [
         d for d in dates if d.date() == _first_friday(d.year, d.month)
     ]
     if len(on_first_friday) == len(dates):
         raise AssertionError(
             "every release sits on the first Friday of its month -- proxy calendar"
         )
 
     phantom = [d for d in dates if (d.year, d.month) == (2025, 10)]
     if phantom:
         raise AssertionError(
             f"calendar contains an October 2025 release ({phantom[0].date()}). "
             "The shutdown cancelled it; only the proxy invents one."
         )
 
 
 class TestK528UsesOfficialCalendar:
     def test_defines_no_first_friday_helper(self):
         src = K528_PY.read_text(encoding="utf-8")
         assert "def get_first_friday" not in src
         assert "def generate_nfp_dates" not in src
         assert "(4 - first_day.weekday()) % 7" not in src
 
     def test_imports_the_official_calendar(self):
+        """Match the import target, not the whole line: the script also imports
+        _fetch/RELEASE_IDS to validate the unselected feed, and pinning the exact
+        line text would fail on that without anything being wrong."""
         src = K528_PY.read_text(encoding="utf-8")
-        assert "from volpred.data.event_dates import nfp_release_dates" in src
+        assert "from volpred.data.event_dates import" in src
+        assert "nfp_release_dates" in src
 
     def test_results_declare_the_official_source_and_no_fallback(self):
         source = _load_k528(K528_RESULTS)["event_date_source"]
         assert "nfp_release_dates" in source["accessor"]
         assert source["fallback"] == "none - the run raises if the calendar is unreachable"
 
     def test_event_dates_carry_no_proxy_signature(self):
         assert_not_first_friday_proxy(_k528_event_dates())
 
     def test_sample_is_not_uniformly_friday(self):
         """237 of 253, not 253 of 253. The gap is the corrected dates."""
         results = _load_k528(K528_RESULTS)
         n, on_friday = results["sample"]["total_nfp_events"], results["sample"]["nfp_days_on_friday"]
         assert n == 253
         assert on_friday == 237
         assert on_friday < n
 
     def test_audit_records_the_dates_that_changed(self):
         diff = _load_k528(K528_AUDIT)["calendar_diff"]
         assert diff["dates_in_common"] == 212
         # The near-equal sample sizes hide a date swap; assert the swap, not the
         # count, or a silent revert reads as unchanged.
         assert len(diff["proxy_only_dates"]) == 42
         assert len(diff["official_only_dates"]) == 41
         assert "2025-10-03" in diff["proxy_only_dates"]
         assert "2025-11-20" in diff["official_only_dates"]
 
     def test_no_off_cycle_revision_date_is_treated_as_an_event(self):
         """Direct pin on the k528 Codex v2 BLOCKER.
 
         For six months ALFRED returns two release-id-50 entries; the later one
         is a seasonal-factor/benchmark revision, not the Employment Situation.
         An earlier rerun selected those six and moved the NFP-vs-Friday test
         across the 5% line. Assert on the ARTIFACT, not just on the accessor:
         the accessor being right does not prove the shipped results used it.
         """
         event_dates = {str(d.date()) for d in _k528_event_dates()}
         off_cycle = {
             "2006-05-08", "2012-12-12", "2013-05-06",
             "2020-05-11", "2024-01-10", "2024-08-21",
         }
         regular = {
             "2006-05-05", "2012-12-07", "2013-05-03",
             "2020-05-08", "2024-01-05", "2024-08-02",
         }
         assert not (event_dates & off_cycle), (
             f"off-cycle revision dates present in k528 event set: "
             f"{sorted(event_dates & off_cycle)}"
         )
         assert regular <= event_dates, (
             f"regular releases missing from k528 event set: {sorted(regular - event_dates)}"
         )
 
 
 class TestProxyMutationIsCaught:
     """Mutation test. Reverting to the proxy must turn the suite red, and the
     only way to know that is to build the proxy calendar and watch the guard
     reject it."""
 
     @staticmethod
     def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
         out = []
         for year in range(start_year, end_year + 1):
             last = 12 if year < end_year else end_month
             for month in range(1, last + 1):
                 out.append(pd.Timestamp(_first_friday(year, month)))
         return pd.DatetimeIndex(out)
 
     def test_the_proxy_calendar_is_rejected(self):
         with pytest.raises(AssertionError, match="Friday"):
             assert_not_first_friday_proxy(self._proxy_calendar())
 
     def test_phantom_october_2025_alone_is_enough_to_fail(self):
         """A partial revert that keeps some real dates still gets caught."""
         mixed = pd.DatetimeIndex(
             _k528_event_dates() + [pd.Timestamp("2025-10-03")]
         )
         with pytest.raises(AssertionError, match="October 2025"):
             assert_not_first_friday_proxy(mixed)
 
     def test_the_guard_accepts_the_official_calendar(self, official):
         """The other half of the mutation test: the guard must not reject
         everything. A guard that always fails is as useless as one that never
         does."""
         assert_not_first_friday_proxy(official)
+
+
+# ---------------------------------------------------------------------------
+# Holes found by Codex v3 against commit 6fd281901. Each of these shipped once
+# with a green suite, so each gets an assertion rather than a comment.
+# ---------------------------------------------------------------------------
+
+
+def _k528_module():
+    """Load the k528 script's pure helpers without running the analysis body."""
+    import ast
+    import types
+
+    src = K528_PY.read_text(encoding="utf-8")
+    tree = ast.parse(src)
+    keep = [
+        n for n in tree.body
+        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))
+        or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "KNOWN_MISSING_MONTHS")
+        or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in (
+            "SAMPLE_START", "SAMPLE_END", "AMBIGUOUS_SAME_MONTH_GAP_DAYS"))
+    ]
+    mod = types.ModuleType("k528_helpers")
+    exec(compile(ast.Module(body=keep, type_ignores=[]), "k528", "exec"), mod.__dict__)
+    return mod
+
+
+class TestControlGroupHasNoNfpDays:
+    """A real NFP session sitting in the control group is the exact failure this
+    experiment exists to document -- it just happened at 1/253 scale instead of
+    46/254, via an event dropped for lacking a pre-window but never removed from
+    the baseline."""
+
+    def test_every_mapped_nfp_session_is_excluded_from_the_control_group(self):
+        sample = _load_k528(K528_RESULTS)["sample"]
+        audit = sample["event_mapping_audit"]
+        total_sessions = sample["non_nfp_trading_days"] + audit["n_mapped_to_sessions"]
+        assert sample["non_nfp_trading_days"] == total_sessions - audit["n_mapped_to_sessions"], (
+            "control group size must exclude ALL mapped NFP sessions, not just the "
+            "ones that survived the event-window filter"
+        )
+
+    def test_window_excluded_event_is_not_silently_analysed_or_kept_as_control(self):
+        audit = _load_k528(K528_RESULTS)["sample"]["event_mapping_audit"]
+        assert audit["n_valid_events"] + audit["n_excluded_for_window_buffer"] == \
+            audit["n_mapped_to_sessions"]
+        assert audit["window_excluded_dates"], "the partition must name what it dropped"
+
+
+class TestCalendarFailClosedCannotBeBypassed:
+    """Codex v3 finding 3: validating only the accessor's OUTPUT cannot work,
+    because the accessor collapses each month to one date before any check on
+    the output can look for an ambiguity."""
+
+    @pytest.fixture
+    def check(self):
+        return _k528_module().check_calendar_is_complete
+
+    def test_off_cycle_entry_earlier_in_the_month_is_ambiguous_not_silently_picked(self, check):
+        """The bypass: an off-cycle entry filed EARLIER than the report. A
+        per-month min() takes it without complaint and the cadence still passes."""
+        with pytest.raises(RuntimeError, match="too close together"):
+            check(
+                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
+                ["2024-01-05", "2024-02-01", "2024-02-02", "2024-03-08"],
+                "2024-01-01", "2024-12-31",
+            )
+
+    def test_selection_that_is_not_the_earliest_entry_fails(self, check):
+        with pytest.raises(RuntimeError, match="did not select the earliest"):
+            check(
+                pd.to_datetime(["2024-01-05", "2024-02-09", "2024-03-08"]),
+                ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
+                "2024-01-01", "2024-12-31",
+            )
+
+    def test_missing_month_inside_the_observed_span_fails(self, check):
+        """The old check exempted the first and last month unconditionally, so a
+        genuinely complete endpoint month could vanish for free."""
+        with pytest.raises(RuntimeError, match="missing 1 month"):
+            check(
+                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
+                ["2024-01-05", "2024-02-02", "2024-04-05"],
+                "2024-01-01", "2024-12-31",
+            )
+
+    def test_allowlist_cannot_silence_a_month_that_has_data(self, check):
+        """KNOWN_MISSING_MONTHS is for real cancellations. If it is taken on
+        faith it is just a way to make a failing check pass."""
+        mod = _k528_module()
+        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
+        with pytest.raises(RuntimeError, match="claims"):
+            mod.check_calendar_is_complete(
+                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
+                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
+                "2024-01-01", "2024-12-31",
+            )
+
+    def test_a_legitimate_calendar_with_a_normal_revision_still_passes(self, check):
+        """The other half: a guard that rejects everything is as useless as one
+        that rejects nothing. A revision filed a week later is normal."""
+        out = check(
+            pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
+            ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
+            "2024-01-01", "2024-12-31",
+        )
+        assert out["months_with_multiple_raw_entries"] == ["2024-02"]
+
+
+class TestFridayEstimandIsScopedHonestly:
+    """Codex v3 finding 4: restricting to Friday is a legitimate conditional
+    estimand, but it stops supporting statements about NFP releases in general,
+    and the restriction is not a neutral sample deletion."""
+
+    def test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality(self):
+        b = _load_k528(K528_RESULTS)["statistical_tests"]["B_nfp_vs_friday"]
+        assert "CONDITIONAL ON FRIDAY" in b["estimand"]
+        assert "Friday NFP" in b["claim_scope"]
+        nn = b["restriction_is_not_neutral"]
+        assert nn["excluded_are_quieter_by_pct"] > 0, (
+            "if the excluded events are quieter, the restriction RAISES the ratio "
+            "and that must be stated, not discovered by a reviewer"
+        )
+
+    def test_excluded_count_matches_the_weekday_breakdown(self):
+        """The results file once said 11 in prose and 16 in data."""
+        results = _load_k528(K528_RESULTS)
+        b = results["statistical_tests"]["B_nfp_vs_friday"]
+        non_friday = sum(1 for e in results["event_data"] if e["weekday"] != 4)
+        assert b["excluded_non_friday_events"]["n"] == non_friday == 16
+        assert str(non_friday) in b["estimand"]

exec
/bin/zsh -lc "for spec in \\
'experiments/k528/k528_nfp_event_study.py 90 210' \\
'experiments/k528/k528_nfp_event_study.py 250 430' \\
'experiments/k528/k528_nfp_event_study.py 650 850' \\
'src/volpred/data/event_dates.py 1 220' \\
'tests/test_nfp_official_release_dates.py 430 720'; do set -- "'$spec; p=$1; a=$2; b=$3; git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:$p | nl -ba | sed -n "${a},${b}p"; done' in /Users/yhlai0911/volpred-research
 exited 1 in 0ms:
sed: 1: ",p
": invalid command code ,
fatal: path 'experiments/k528/k528_nfp_event_study.py 90 210' does not exist in '2abb3f68c'
sed: 1: ",p
": invalid command code ,
fatal: path 'experiments/k528/k528_nfp_event_study.py 250 430' does not exist in '2abb3f68c'
sed: 1: ",p
": invalid command code ,
fatal: path 'experiments/k528/k528_nfp_event_study.py 650 850' does not exist in '2abb3f68c'
sed: 1: ",p
": invalid command code ,
fatal: path 'src/volpred/data/event_dates.py 1 220' does not exist in '2abb3f68c'
sed: 1: ",p
": invalid command code ,
fatal: path 'tests/test_nfp_official_release_dates.py 430 720' does not exist in '2abb3f68c'

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '90,210p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '250,430p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '650,850p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:src/volpred/data/event_dates.py | nl -ba | sed -n '1,220p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:tests/test_nfp_official_release_dates.py | nl -ba | sed -n '430,720p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
    90	    """Write `payload` to `path` atomically.
    91	
    92	    A truncate-then-write leaves a half-written results file on the disk if the
    93	    run dies mid-dump, and a half-written results file is worse than none: it
    94	    still parses far enough to look like data to the next reader. Write to a
    95	    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
    96	    """
    97	    path.parent.mkdir(parents=True, exist_ok=True)
    98	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    99	    try:
   100	        with os.fdopen(fd, "w") as f:
   101	            json.dump(payload, f, indent=2, default=str)
   102	            f.flush()
   103	            os.fsync(f.fileno())
   104	        os.replace(tmp, path)
   105	    except BaseException:
   106	        try:
   107	            os.unlink(tmp)
   108	        except FileNotFoundError:
   109	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
   110	        raise
   111	
   112	
   113	# ============================================================
   114	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
   115	# ============================================================
   116	def check_calendar_is_complete(selected, raw, start, end):
   117	    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
   118	
   119	    "Did the call succeed?" is the wrong question. A monthly release calendar
   120	    that silently lost 2019 still returns a non-empty list, still produces
   121	    event windows, still renders.
   122	
   123	    This validates the RAW feed as well as the accessor's per-month selection.
   124	    Validating only the selection cannot work: the accessor collapses each month
   125	    to one date before this function ever sees it, so a same-month ambiguity is
   126	    already resolved -- silently, and possibly wrongly -- by the time a check on
   127	    the output could look for it. That is precisely how the k528 v2 BLOCKER got
   128	    through (Codex v3 finding 3).
   129	
   130	    Four ways the input can be wrong without being empty, all of which raise:
   131	      1. a month has two entries too close together to tell report from revision
   132	      2. the selection is not the earliest entry of its month
   133	      3. a month is missing from the observed span
   134	      4. a month is claimed as a known hole but the raw feed actually has data
   135	    """
   136	    sel = [pd.Timestamp(d) for d in selected]
   137	    sel_months = [d.strftime("%Y-%m") for d in sel]
   138	
   139	    raw_by_month: dict[str, list[pd.Timestamp]] = {}
   140	    for d in raw:
   141	        ts = pd.Timestamp(d)
   142	        raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
   143	    for v in raw_by_month.values():
   144	        v.sort()
   145	
   146	    # 1 + 2: same-month resolution must be unambiguous AND actually taken.
   147	    ambiguous, mis_selected = [], []
   148	    sel_by_month = dict(zip(sel_months, sel))
   149	    for month, entries in raw_by_month.items():
   150	        if len(entries) > 1:
   151	            gap = (entries[1] - entries[0]).days
   152	            if gap < AMBIGUOUS_SAME_MONTH_GAP_DAYS:
   153	                ambiguous.append(f"{month}: {entries[0].date()} vs {entries[1].date()} ({gap}d apart)")
   154	        if month in sel_by_month and sel_by_month[month] != entries[0]:
   155	            mis_selected.append(
   156	                f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
   157	            )
   158	    if ambiguous:
   159	        raise RuntimeError(
   160	            f"{len(ambiguous)} month(s) carry two release entries too close together to "
   161	            f"identify the Employment Situation report by date order: {ambiguous}. "
   162	            "Revisions are filed weeks after the report, not days -- this shape means the "
   163	            "feed changed or the release id is carrying something new. Refusing to guess."
   164	        )
   165	    if mis_selected:
   166	        raise RuntimeError(
   167	            f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
   168	            f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
   169	            "monthly report -- selecting it is the k528 v2 BLOCKER."
   170	        )
   171	
   172	    # 3: no month may vanish from the observed span. Anchoring on the observed
   173	    # span rather than [start, end] removes the endpoint fudge that used to
   174	    # exempt the first and last month unconditionally (Codex v3 finding 3).
   175	    span = {
   176	        p.strftime("%Y-%m")
   177	        for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
   178	    }
   179	    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
   180	    if missing:
   181	        raise RuntimeError(
   182	            f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
   183	            f"span: {missing}. A partial calendar dumps real event days into the control "
   184	            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
   185	            "reason (e.g. a cancelled release), never to make this check pass."
   186	        )
   187	
   188	    # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
   189	    # allowlist is a bypass: any month could be declared 'known missing' and the
   190	    # check would stop looking at it.
   191	    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if m in span and raw_by_month.get(m))
   192	    if bogus:
   193	        raise RuntimeError(
   194	            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
   195	            f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
   196	            "The allowlist is for real cancellations, not for silencing a selection bug."
   197	        )
   198	
   199	    return {
   200	        "n_months_in_span": len(span),
   201	        "n_raw_entries": len(raw),
   202	        "months_with_multiple_raw_entries": sorted(m for m, v in raw_by_month.items() if len(v) > 1),
   203	        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
   204	        "ambiguity_gap_threshold_days": AMBIGUOUS_SAME_MONTH_GAP_DAYS,
   205	    }
   206	
   207	
   208	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   209	    """Official NFP (Employment Situation) release dates.
   210	
   250	vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
   251	spy = spy.join(vix_close, how="left")
   252	spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays
   253	
   254	print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
   255	print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")
   256	
   257	# ============================================================
   258	# 3. Map NFP dates to trading days
   259	# ============================================================
   260	print("\n[2/6] Mapping NFP dates to trading days...")
   261	
   262	nfp_calendar, calendar_completeness = load_nfp_dates()
   263	trading_dates = spy.index
   264	
   265	# The proxy forced every event onto a Friday. The official calendar does not,
   266	# and that is load-bearing for the Friday-baseline test below.
   267	n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
   268	print(f"  Official releases: {len(nfp_calendar)} "
   269	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
   270	
   271	# Map each NFP date to the session that trades the news. The report drops at
   272	# 08:30 ET, before the open, so a release on a closed day is traded at the next
   273	# open -- hence "next trading day", not "nearest". Every release must land on
   274	# exactly one session and no two releases may share one: both failures shrink
   275	# the event set without shrinking any count that gets printed.
   276	release_to_session = {}
   277	unmapped = []
   278	for nfp_date in nfp_calendar:
   279	    nfp_ts = pd.Timestamp(nfp_date)
   280	    if nfp_ts in trading_dates:
   281	        release_to_session[nfp_ts] = nfp_ts
   282	        continue
   283	    mask = (trading_dates > nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
   284	    candidates = trading_dates[mask]
   285	    if len(candidates) > 0:
   286	        release_to_session[nfp_ts] = candidates[0]
   287	    else:
   288	        unmapped.append(nfp_ts.date().isoformat())
   289	
   290	# In-sample releases must map. Releases outside the price series (the calendar
   291	# window can overhang the SPY history on either end) are excluded by design,
   292	# not by failure, so they are separated before the assertion.
   293	in_sample_unmapped = [
   294	    d for d in unmapped
   295	    if trading_dates[0] <= pd.Timestamp(d) <= trading_dates[-1]
   296	]
   297	if in_sample_unmapped:
   298	    raise RuntimeError(
   299	        f"{len(in_sample_unmapped)} official NFP release(s) inside the price sample found no "
   300	        f"trading session within 3 days: {in_sample_unmapped}. Silently skipping them would "
   301	        "drop real event days into the control group."
   302	    )
   303	
   304	collisions = {}
   305	for rel, sess in release_to_session.items():
   306	    collisions.setdefault(sess, []).append(rel.date().isoformat())
   307	colliding = {str(s.date()): sorted(v) for s, v in collisions.items() if len(v) > 1}
   308	if colliding:
   309	    raise RuntimeError(
   310	        f"two or more NFP releases mapped to the same trading session: {colliding}. "
   311	        "The de-duplication that used to hide this also silently reduced the event count."
   312	    )
   313	
   314	nfp_trading_dates = sorted(release_to_session.values())
   315	n_shifted = sum(1 for r, s in release_to_session.items() if r != s)
   316	
   317	# Window buffer: an event needs 5 sessions before and 5 after to have a window
   318	# at all. Excluding the edges is correct; doing it without saying so is not.
   319	window_excluded = [d for d in nfp_trading_dates
   320	                   if d < trading_dates[10] or d > trading_dates[-6]]
   321	valid_nfp = [d for d in nfp_trading_dates
   322	             if d >= trading_dates[10] and d <= trading_dates[-6]]
   323	
   324	if len(valid_nfp) + len(window_excluded) != len(nfp_trading_dates):
   325	    raise RuntimeError("event-window partition lost events; refusing to continue")
   326	
   327	mapping_audit = {
   328	    "n_official_releases": len(nfp_calendar),
   329	    "n_mapped_to_sessions": len(nfp_trading_dates),
   330	    "n_shifted_to_next_session": n_shifted,
   331	    "n_outside_price_sample": len(unmapped),
   332	    "outside_price_sample_dates": sorted(unmapped),
   333	    "n_excluded_for_window_buffer": len(window_excluded),
   334	    "window_excluded_dates": [str(d.date()) for d in window_excluded],
   335	    "n_valid_events": len(valid_nfp),
   336	}
   337	
   338	print(f"  Total official releases: {len(nfp_calendar)}")
   339	print(f"  Mapped to trading sessions: {len(nfp_trading_dates)} ({n_shifted} shifted to next open)")
   340	print(f"  Outside price sample: {len(unmapped)}")
   341	print(f"  Excluded for window buffer: {len(window_excluded)}")
   342	print(f"  Valid (with pre/post window): {len(valid_nfp)}")
   343	
   344	# ============================================================
   345	# 4. Calculate event windows
   346	# ============================================================
   347	print("\n[3/6] Calculating event window statistics...")
   348	
   349	results = []
   350	idx_list = list(trading_dates)
   351	
   352	for nfp_date in valid_nfp:
   353	    pos = idx_list.index(nfp_date)
   354	
   355	    # Pre-event: T-5 to T-1
   356	    pre_window = spy.iloc[pos-5:pos]
   357	    # Event day: T
   358	    event_day = spy.iloc[pos]
   359	    # Post-event: T+1 to T+5
   360	    post_window = spy.iloc[pos+1:pos+6]
   361	
   362	    # Unreachable given the window-buffer partition above. Kept as an assertion
   363	    # rather than a `continue`: if the partition ever stops holding, the run
   364	    # must stop, not quietly analyse a smaller sample than it reports.
   365	    if len(pre_window) < 5 or len(post_window) < 5:
   366	        raise RuntimeError(
   367	            f"event {nfp_date.date()} has an incomplete window "
   368	            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
   369	            "window-buffer filter -- the partition and the window logic disagree"
   370	        )
   371	
   372	    row = {
   373	        "date": nfp_date.strftime("%Y-%m-%d"),
   374	        "year": nfp_date.year,
   375	        "month": nfp_date.month,
   376	        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
   377	        "event_return": float(event_day["Return"]),
   378	        "event_abs_return": float(event_day["AbsReturn"]),
   379	        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
   380	        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
   381	        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
   382	        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
   383	        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
   384	        "vix_change_event": None,
   385	        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
   386	        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
   387	    }
   388	
   389	    if row["pre_vix"] is not None and row["event_vix"] is not None:
   390	        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
   391	
   392	    results.append(row)
   393	
   394	df = pd.DataFrame(results)
   395	print(f"  Events with complete data: {len(df)}")
   396	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
   397	
   398	# ============================================================
   399	# 5. Non-NFP baseline calculation
   400	# ============================================================
   401	print("\n[4/6] Computing non-NFP baseline...")
   402	
   403	# Exclude EVERY NFP session from the control group, not just the ones that
   404	# survived the event-window filter. An event dropped for lacking a pre-window
   405	# is still an NFP day; leaving it in the control group is the exact failure this
   406	# experiment exists to fix ("dump real event days into the control group"), just
   407	# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
   408	nfp_set = set(nfp_trading_dates)
   409	non_nfp_mask = ~spy.index.isin(nfp_set)
   410	non_nfp = spy[non_nfp_mask]
   411	n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
   412	if n_leaked:
   413	    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
   414	
   415	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
   416	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
   417	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   418	
   419	# Friday-only baseline. The event group is a weekday MIXTURE while the control
   420	# group is pure Friday, so any Friday-vs-other-weekday volatility difference
   421	# loads straight onto the estimate. The test below holds weekday fixed on BOTH
   422	# sides.
   423	#
   424	# Note against the obvious story: this defect is NOT introduced by the date
   425	# correction. The proxy calendar was all-Friday by construction, but mapping
   426	# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
   427	# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
   428	# always there and is essentially unchanged; the old spec was already comparing
   429	# a mixed group against a pure-Friday control. Correcting the dates is what made
   430	# it visible, not what caused it.
   650	print(f"  April NFP events:     {len(april_nfp)}")
   651	print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
   652	print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
   653	print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
   654	if "4" in monthly_stats:
   655	    ms4 = monthly_stats["4"]
   656	    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")
   657	
   658	# ============================================================
   659	# 9. Summary conclusion
   660	# ============================================================
   661	print(f"\n{'=' * 60}")
   662	print("SUMMARY CONCLUSION")
   663	print("=" * 60)
   664	
   665	sig_level = 0.05
   666	conclusions = []
   667	
   668	# Each conclusion names the test it came from. The previous run collapsed
   669	# several tests into "insignificant across all tests" while the one-sided
   670	# Mann-Whitney in the same artifact was significant at p<0.01 -- a summary that
   671	# contradicted its own numbers. A Welch test on |return| is a test of MEANS;
   672	# it not rejecting is not a finding that the distributions match, and it is
   673	# never evidence that the effect is zero.
   674	conclusions.append(
   675	    f"Welch mean-difference, NFP vs all non-NFP days: {vol_ratio_all:.2f}x, "
   676	    f"p={p_val_all:.4f} ({'rejects' if p_val_all < sig_level else 'does not reject'} at 5%)"
   677	)
   678	conclusions.append(
   679	    f"Welch mean-difference, Friday NFP vs Friday non-NFP (CONDITIONAL ON FRIDAY, "
   680	    f"weekday held fixed): {vol_ratio_fri:.2f}x, p={p_val_fri:.4f} "
   681	    f"({'rejects' if p_val_fri < sig_level else 'does not reject'} at 5%; "
   682	    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)}). Scoped to Friday "
   683	    f"releases; the {len(nfp_nonfriday_abs)} non-Friday events are quieter, so this "
   684	    f"is not a statement about NFP releases in general."
   685	)
   686	conclusions.append(
   687	    f"Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: "
   688	    f"p={p_val_wilcox:.5f} ({'rejects' if p_val_wilcox < sig_level else 'does not reject'} at 5%)"
   689	)
   690	if (p_val_all >= sig_level) != (p_val_wilcox >= sig_level):
   691	    conclusions.append(
   692	        "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, "
   693	        "so a rank test can detect a location shift the Welch mean test cannot. "
   694	        "Report both; do not summarise them as a single verdict."
   695	    )
   696	
   697	if vol_crush.mean() < 0 and p_crush < sig_level:
   698	    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
   699	else:
   700	    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")
   701	
   702	if r_vix is not None and p_vix < sig_level:
   703	    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
   704	else:
   705	    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")
   706	
   707	for c in conclusions:
   708	    print(f"  • {c}")
   709	
   710	print(f"\n  Practical implication:")
   711	print(f"    → Entry VIX regime is the larger and more reliably measured effect "
   712	      f"({high_vix.mean()/low_vix.mean():.2f}x, p={p_regime:.4g})")
   713	print(f"    → The NFP-day effect is smaller; mean and rank tests do not agree on it, "
   714	      f"so it is not established either way")
   715	print(f"    → Non-significance of a mean test is not evidence of no effect")
   716	
   717	# ============================================================
   718	# 9b. Correction audit: every published number, before vs after
   719	# ============================================================
   720	# A mean can sit still while the median and the win rate move underneath it,
   721	# so no claim is judged on its mean alone. Each item carries mean / median /
   722	# win rate / n / significance, and the flip test looks at all of them.
   723	print(f"\n{'=' * 60}")
   724	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
   725	print("=" * 60)
   726	
   727	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
   728	if not PROXY_PATH.exists():
   729	    raise FileNotFoundError(
   730	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
   731	        "only record of what the published article claimed. Do not regenerate it."
   732	    )
   733	proxy = json.loads(PROXY_PATH.read_text())
   734	
   735	
   736	def win_rate(sample, reference):
   737	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
   738	    ref_med = float(np.median(reference))
   739	    return float(np.mean(np.asarray(sample) > ref_med))
   740	
   741	
   742	# The proxy run only ever reported means, and a mean can hold still while the
   743	# median and the win rate move underneath it. Rather than leave the before-side
   744	# of those two columns null -- which would make the comparison unable to detect
   745	# exactly the failure it is looking for -- rebuild the proxy-era distributions
   746	# from the ARCHIVED per-event data. The dates come out of the archive, so this
   747	# reconstructs history without reintroducing a proxy calendar generator.
   748	proxy_events = proxy["event_data"]
   749	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
   750	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
   751	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
   752	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
   753	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
   754	
   755	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
   756	# mapped to a Monday because the first Friday was a market holiday. So the
   757	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
   758	# rebuild the proxy side under the SAME estimand the corrected run uses
   759	# (Friday events only) rather than comparing a mixed `before` against a
   760	# restricted `after` and calling the difference a correction effect.
   761	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
   762	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
   763	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
   764	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
   765	
   766	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   767	                       for e in proxy_events])
   768	_p_thr = proxy["regime_analysis"]["vix_median_split"]
   769	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   770	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   771	
   772	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
   773	# reconstruction is wrong and its medians cannot be trusted either.
   774	for _label, _rebuilt, _archived in (
   775	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   776	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   777	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   778	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   779	):
   780	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   781	        raise AssertionError(
   782	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   783	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   784	            "from a reconstruction that cannot reproduce the archived means."
   785	        )
   786	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   787	
   788	audit_items = {}
   789	
   790	
   791	def record(key, label, before, after, note=""):
   792	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   793	
   794	
   795	# --- 1.10x : NFP vs all non-NFP days ---
   796	record(
   797	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   798	    {
   799	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   800	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   801	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   802	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   803	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   804	        "n": proxy["sample"]["total_nfp_events"],
   805	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   806	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   807	    },
   808	    {
   809	        "mean_ratio": vol_ratio_all,
   810	        "nfp_mean": float(nfp_abs_returns.mean()),
   811	        "baseline_mean": baseline_abs_return,
   812	        "p_value": float(p_val_all),
   813	        "significant_5pct": bool(p_val_all < 0.05),
   814	        "n": int(len(df)),
   815	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   816	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   817	    },
   818	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   819	         "per-event data, not from the proxy run's own output (it only reported means).",
   820	)
   821	
   822	# --- 1.17x : NFP vs Friday-only baseline ---
   823	record(
   824	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   825	    {
   826	        # Same estimand as the `after` column: Friday events only.
   827	        "mean_ratio": proxy_ratio_fri_restricted,
   828	        "p_value": float(_p_p_fri),
   829	        "significant_5pct": bool(_p_p_fri < 0.05),
   830	        "n": int(len(proxy_nfp_friday_abs)),
   831	        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
   832	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
   833	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
   834	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   835	        "as_published_mixed_weekday": {
   836	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   837	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   838	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   839	            "n": proxy["sample"]["total_nfp_events"],
   840	            "note": (
   841	                "what the proxy run actually published: all 254 events (239 Friday, "
   842	                "15 Monday) against non-NFP Fridays. This is the number the article "
   843	                "quoted, so it is kept, but it is NOT the like-for-like comparison "
   844	                "against the corrected column."
   845	            ),
   846	        },
   847	    },
   848	    {
   849	        "mean_ratio": vol_ratio_fri,
   850	        "p_value": float(p_val_fri),
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
   430	    def test_audit_records_the_dates_that_changed(self):
   431	        diff = _load_k528(K528_AUDIT)["calendar_diff"]
   432	        assert diff["dates_in_common"] == 212
   433	        # The near-equal sample sizes hide a date swap; assert the swap, not the
   434	        # count, or a silent revert reads as unchanged.
   435	        assert len(diff["proxy_only_dates"]) == 42
   436	        assert len(diff["official_only_dates"]) == 41
   437	        assert "2025-10-03" in diff["proxy_only_dates"]
   438	        assert "2025-11-20" in diff["official_only_dates"]
   439	
   440	    def test_no_off_cycle_revision_date_is_treated_as_an_event(self):
   441	        """Direct pin on the k528 Codex v2 BLOCKER.
   442	
   443	        For six months ALFRED returns two release-id-50 entries; the later one
   444	        is a seasonal-factor/benchmark revision, not the Employment Situation.
   445	        An earlier rerun selected those six and moved the NFP-vs-Friday test
   446	        across the 5% line. Assert on the ARTIFACT, not just on the accessor:
   447	        the accessor being right does not prove the shipped results used it.
   448	        """
   449	        event_dates = {str(d.date()) for d in _k528_event_dates()}
   450	        off_cycle = {
   451	            "2006-05-08", "2012-12-12", "2013-05-06",
   452	            "2020-05-11", "2024-01-10", "2024-08-21",
   453	        }
   454	        regular = {
   455	            "2006-05-05", "2012-12-07", "2013-05-03",
   456	            "2020-05-08", "2024-01-05", "2024-08-02",
   457	        }
   458	        assert not (event_dates & off_cycle), (
   459	            f"off-cycle revision dates present in k528 event set: "
   460	            f"{sorted(event_dates & off_cycle)}"
   461	        )
   462	        assert regular <= event_dates, (
   463	            f"regular releases missing from k528 event set: {sorted(regular - event_dates)}"
   464	        )
   465	
   466	
   467	class TestProxyMutationIsCaught:
   468	    """Mutation test. Reverting to the proxy must turn the suite red, and the
   469	    only way to know that is to build the proxy calendar and watch the guard
   470	    reject it."""
   471	
   472	    @staticmethod
   473	    def _proxy_calendar(start_year=2005, end_year=2026, end_month=3):
   474	        out = []
   475	        for year in range(start_year, end_year + 1):
   476	            last = 12 if year < end_year else end_month
   477	            for month in range(1, last + 1):
   478	                out.append(pd.Timestamp(_first_friday(year, month)))
   479	        return pd.DatetimeIndex(out)
   480	
   481	    def test_the_proxy_calendar_is_rejected(self):
   482	        with pytest.raises(AssertionError, match="Friday"):
   483	            assert_not_first_friday_proxy(self._proxy_calendar())
   484	
   485	    def test_phantom_october_2025_alone_is_enough_to_fail(self):
   486	        """A partial revert that keeps some real dates still gets caught."""
   487	        mixed = pd.DatetimeIndex(
   488	            _k528_event_dates() + [pd.Timestamp("2025-10-03")]
   489	        )
   490	        with pytest.raises(AssertionError, match="October 2025"):
   491	            assert_not_first_friday_proxy(mixed)
   492	
   493	    def test_the_guard_accepts_the_official_calendar(self, official):
   494	        """The other half of the mutation test: the guard must not reject
   495	        everything. A guard that always fails is as useless as one that never
   496	        does."""
   497	        assert_not_first_friday_proxy(official)
   498	
   499	
   500	# ---------------------------------------------------------------------------
   501	# Holes found by Codex v3 against commit 6fd281901. Each of these shipped once
   502	# with a green suite, so each gets an assertion rather than a comment.
   503	# ---------------------------------------------------------------------------
   504	
   505	
   506	def _k528_module():
   507	    """Load the k528 script's pure helpers without running the analysis body."""
   508	    import ast
   509	    import types
   510	
   511	    src = K528_PY.read_text(encoding="utf-8")
   512	    tree = ast.parse(src)
   513	    keep = [
   514	        n for n in tree.body
   515	        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))
   516	        or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "KNOWN_MISSING_MONTHS")
   517	        or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in (
   518	            "SAMPLE_START", "SAMPLE_END", "AMBIGUOUS_SAME_MONTH_GAP_DAYS"))
   519	    ]
   520	    mod = types.ModuleType("k528_helpers")
   521	    exec(compile(ast.Module(body=keep, type_ignores=[]), "k528", "exec"), mod.__dict__)
   522	    return mod
   523	
   524	
   525	class TestControlGroupHasNoNfpDays:
   526	    """A real NFP session sitting in the control group is the exact failure this
   527	    experiment exists to document -- it just happened at 1/253 scale instead of
   528	    46/254, via an event dropped for lacking a pre-window but never removed from
   529	    the baseline."""
   530	
   531	    def test_every_mapped_nfp_session_is_excluded_from_the_control_group(self):
   532	        sample = _load_k528(K528_RESULTS)["sample"]
   533	        audit = sample["event_mapping_audit"]
   534	        total_sessions = sample["non_nfp_trading_days"] + audit["n_mapped_to_sessions"]
   535	        assert sample["non_nfp_trading_days"] == total_sessions - audit["n_mapped_to_sessions"], (
   536	            "control group size must exclude ALL mapped NFP sessions, not just the "
   537	            "ones that survived the event-window filter"
   538	        )
   539	
   540	    def test_window_excluded_event_is_not_silently_analysed_or_kept_as_control(self):
   541	        audit = _load_k528(K528_RESULTS)["sample"]["event_mapping_audit"]
   542	        assert audit["n_valid_events"] + audit["n_excluded_for_window_buffer"] == \
   543	            audit["n_mapped_to_sessions"]
   544	        assert audit["window_excluded_dates"], "the partition must name what it dropped"
   545	
   546	
   547	class TestCalendarFailClosedCannotBeBypassed:
   548	    """Codex v3 finding 3: validating only the accessor's OUTPUT cannot work,
   549	    because the accessor collapses each month to one date before any check on
   550	    the output can look for an ambiguity."""
   551	
   552	    @pytest.fixture
   553	    def check(self):
   554	        return _k528_module().check_calendar_is_complete
   555	
   556	    def test_off_cycle_entry_earlier_in_the_month_is_ambiguous_not_silently_picked(self, check):
   557	        """The bypass: an off-cycle entry filed EARLIER than the report. A
   558	        per-month min() takes it without complaint and the cadence still passes."""
   559	        with pytest.raises(RuntimeError, match="too close together"):
   560	            check(
   561	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   562	                ["2024-01-05", "2024-02-01", "2024-02-02", "2024-03-08"],
   563	                "2024-01-01", "2024-12-31",
   564	            )
   565	
   566	    def test_selection_that_is_not_the_earliest_entry_fails(self, check):
   567	        with pytest.raises(RuntimeError, match="did not select the earliest"):
   568	            check(
   569	                pd.to_datetime(["2024-01-05", "2024-02-09", "2024-03-08"]),
   570	                ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   571	                "2024-01-01", "2024-12-31",
   572	            )
   573	
   574	    def test_missing_month_inside_the_observed_span_fails(self, check):
   575	        """The old check exempted the first and last month unconditionally, so a
   576	        genuinely complete endpoint month could vanish for free."""
   577	        with pytest.raises(RuntimeError, match="missing 1 month"):
   578	            check(
   579	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
   580	                ["2024-01-05", "2024-02-02", "2024-04-05"],
   581	                "2024-01-01", "2024-12-31",
   582	            )
   583	
   584	    def test_allowlist_cannot_silence_a_month_that_has_data(self, check):
   585	        """KNOWN_MISSING_MONTHS is for real cancellations. If it is taken on
   586	        faith it is just a way to make a failing check pass."""
   587	        mod = _k528_module()
   588	        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
   589	        with pytest.raises(RuntimeError, match="claims"):
   590	            mod.check_calendar_is_complete(
   591	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
   592	                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
   593	                "2024-01-01", "2024-12-31",
   594	            )
   595	
   596	    def test_a_legitimate_calendar_with_a_normal_revision_still_passes(self, check):
   597	        """The other half: a guard that rejects everything is as useless as one
   598	        that rejects nothing. A revision filed a week later is normal."""
   599	        out = check(
   600	            pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   601	            ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   602	            "2024-01-01", "2024-12-31",
   603	        )
   604	        assert out["months_with_multiple_raw_entries"] == ["2024-02"]
   605	
   606	
   607	class TestFridayEstimandIsScopedHonestly:
   608	    """Codex v3 finding 4: restricting to Friday is a legitimate conditional
   609	    estimand, but it stops supporting statements about NFP releases in general,
   610	    and the restriction is not a neutral sample deletion."""
   611	
   612	    def test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality(self):
   613	        b = _load_k528(K528_RESULTS)["statistical_tests"]["B_nfp_vs_friday"]
   614	        assert "CONDITIONAL ON FRIDAY" in b["estimand"]
   615	        assert "Friday NFP" in b["claim_scope"]
   616	        nn = b["restriction_is_not_neutral"]
   617	        assert nn["excluded_are_quieter_by_pct"] > 0, (
   618	            "if the excluded events are quieter, the restriction RAISES the ratio "
   619	            "and that must be stated, not discovered by a reviewer"
   620	        )
   621	
   622	    def test_excluded_count_matches_the_weekday_breakdown(self):
   623	        """The results file once said 11 in prose and 16 in data."""
   624	        results = _load_k528(K528_RESULTS)
   625	        b = results["statistical_tests"]["B_nfp_vs_friday"]
   626	        non_friday = sum(1 for e in results["event_data"] if e["weekday"] != 4)
   627	        assert b["excluded_non_friday_events"]["n"] == non_friday == 16
   628	        assert str(non_friday) in b["estimand"]

exec
/bin/zsh -lc "python -c 'import json,subprocess; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; paths=[\"experiments/k528/k528_nfp_event_study_results.json\",\"experiments/k528/k528_nfp_official_dates_results.json\",\"experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json\"];
for path in paths:
 x=json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",f\"2abb3f68c:{path}\"])); print(\"PATH\",path); print(\"keys\",list(x));
 for k,v in x.items():
  print(k, \"dict keys=\"+str(list(v)[:30]) if isinstance(v,dict) else \"list n=\"+str(len(v))+\" first=\"+repr(v[:1]) if isinstance(v,list) else repr(v)[:300])'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
PATH experiments/k528/k528_nfp_event_study_results.json
keys ['experiment_id', 'title', 'date', 'data_source', 'event_date_source', 'sample', 'main_results', 'statistical_tests', 'seasonal_analysis', 'regime_analysis', 'time_trend', 'directional_bias', 'intraday_range', 'volume', 'april_nfp', 'conclusions', 'practical_implication', 'claim_scope_note', 'references', 'event_data']
experiment_id 'K528'
title 'NFP Event Study on SPY Volatility'
date '2026-07-19T08:36:00.092793+00:00'
data_source 'yfinance (SPY, ^VIX), 2005-01 to 2026-03'
event_date_source dict keys=['source', 'accessor', 'fallback', 'supersedes']
sample dict keys=['total_nfp_events', 'date_range', 'non_nfp_trading_days', 'friday_baseline_days', 'nfp_days_on_friday', 'event_mapping_audit', 'calendar_completeness']
main_results dict keys=['nfp_avg_abs_return', 'nfp_avg_abs_return_pct', 'non_nfp_avg_abs_return', 'non_nfp_avg_abs_return_pct', 'friday_baseline_abs_return', 'vol_ratio_vs_all', 'vol_ratio_vs_friday']
statistical_tests dict keys=['A_nfp_vs_all', 'B_nfp_vs_friday', 'B_diagnostic_mixed_weekday', 'C_wilcoxon', 'D_vol_crush', 'E_vix_predictive', 'F_vix_buildup']
seasonal_analysis dict keys=['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']
regime_analysis dict keys=['vix_median_split', 'high_vix_nfp_abs_return', 'low_vix_nfp_abs_return', 'n_high', 'n_low', 't_stat', 'p_value']
time_trend dict keys=['first_half_abs_return', 'second_half_abs_return', 't_stat', 'p_value']
directional_bias dict keys=['positive_count', 'negative_count', 'total', 'positive_rate', 'binomial_p']
intraday_range dict keys=['nfp_avg_range', 'non_nfp_avg_range', 'range_ratio']
volume dict keys=['avg_volume_ratio', 'pct_above_avg']
april_nfp dict keys=['n', 'avg_abs_return', 'avg_signed_return', 'positive_rate', 'vol_ratio']
conclusions list n=6 first=['Welch mean-difference, NFP vs all non-NFP days: 1.11x, p=0.1121 (does not reject at 5%)']
practical_implication "Entry VIX regime is the dominant and most reliably measured effect here: 2.03x between high- and low-VIX NFP days (p=4.553e-09). The NFP-day effect itself is smaller and the tests do not agree on it -- the Welch mean-difference test against all non-NFP days gives 1.11x (p=0.1121) while the one-side
claim_scope_note "Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6)."
references list n=3 first=['K513: FOMC/NFP/CPI event study (2005-2025, 668 events)']
event_data list n=253 first=[{'date': '2005-02-04', 'year': 2005, 'month': 2, 'weekday': 4, 'event_return': 0.010676250615067495, 'event_abs_return': 0.010676250615067495, 'pre_avg_abs_return': 0.0036380898443863384, 'post_avg_abs_return': 0.0044380922327300395, 'pre_vix': 11.789999961853027, 'event_vix': 11.210000038146973, 'post_vix_1d': 11.729999542236328, 'vix_change_event': -0.5799999237060547, 'high_low_range': 0.012060192196264936, 'volume_ratio': 0.9459350091597117}]
PATH experiments/k528/k528_nfp_official_dates_results.json
keys ['experiment_id', 'title', 'generated_at', 'before_source', 'after_source', 'event_date_source', 'calendar_diff', 'win_rate_definition', 'items', 'n_claims_flipped', 'n_claims_audited', 'article_correction']
experiment_id 'K528'
title 'NFP event-date correction: first-Friday proxy vs official BLS calendar'
generated_at '2026-07-19T08:36:00.097665+00:00'
before_source 'k528_nfp_event_study_results_PROXY_SUPERSEDED.json'
after_source 'k528_nfp_event_study_results.json'
event_date_source dict keys=['source', 'accessor', 'fallback', 'supersedes']
calendar_diff dict keys=['proxy_only_dates', 'official_only_dates', 'dates_in_common', 'n_proxy', 'n_official', 'nfp_days_on_friday_official']
win_rate_definition 'share of the sample exceeding the MEDIAN of its comparison group; 0.5 under the null'
items dict keys=['vol_ratio_vs_all', 'vol_ratio_vs_friday', 'regime_ratio', 'vix_correlation', 'vix_median_threshold', 'sample']
n_claims_flipped 0
n_claims_audited 6
article_correction dict keys=['article_id', 'status', 'n_replacements', 'all_matched_exactly_once', 'supersedes', 'directional_claims_changed', 'replacements', 'apply_result', 'residual_gap']
PATH experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json
keys ['superseded', 'superseded_at', 'superseded_by', 'do_not_cite', 'event_date_source', 'retraction_reason', 'impact_on_published_numbers', 'audit_artifact', 'note_for_machines', 'experiment_id', 'title', 'date', 'data_source', 'sample', 'main_results', 'statistical_tests', 'seasonal_analysis', 'regime_analysis', 'time_trend', 'directional_bias', 'intraday_range', 'volume', 'april_nfp', 'conclusions', 'practical_implication', 'references', 'event_data']
superseded True
superseded_at '2026-07-19'
superseded_by 'k528_nfp_event_study_results.json'
do_not_cite True
event_date_source dict keys=['source', 'accessor', 'official_source_it_should_have_used']
retraction_reason 'The first-Friday-of-month rule is wrong for roughly 20% of the sample and wrong SYSTEMATICALLY, not randomly: BLS moves the release to the second Friday when the reference week falls late, pulls it forward around holidays, and did not publish at all in 2025-10 during the federal shutdown -- for whi
impact_on_published_numbers 'Sample 254 -> 253 events. Headline numbers moved modestly (1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, Pearson r 0.45->0.44, VIX median 16.71->16.69). No directional conclusion reversed.'
audit_artifact 'k528_nfp_official_dates_results.json'
note_for_machines 'This object exists so the file is identifiable as retracted WITHOUT relying on its filename or on README prose (k528 Codex v2 finding 8). If you are reading this key, do not use any number in this file.'
experiment_id 'K528'
title 'NFP Event Study on SPY Volatility'
date '2026-03-27T12:26:19.183627+00:00'
data_source 'yfinance (SPY, ^VIX), 2005-01 to 2026-03'
sample dict keys=['total_nfp_events', 'date_range', 'non_nfp_trading_days', 'friday_baseline_days']
main_results dict keys=['nfp_avg_abs_return', 'nfp_avg_abs_return_pct', 'non_nfp_avg_abs_return', 'non_nfp_avg_abs_return_pct', 'friday_baseline_abs_return', 'vol_ratio_vs_all', 'vol_ratio_vs_friday']
statistical_tests dict keys=['A_nfp_vs_all', 'B_nfp_vs_friday', 'C_wilcoxon', 'D_vol_crush', 'E_vix_predictive', 'F_vix_buildup']
seasonal_analysis dict keys=['1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11', '12']
regime_analysis dict keys=['vix_median_split', 'high_vix_nfp_abs_return', 'low_vix_nfp_abs_return', 'n_high', 'n_low', 't_stat', 'p_value']
time_trend dict keys=['first_half_abs_return', 'second_half_abs_return', 't_stat', 'p_value']
directional_bias dict keys=['positive_count', 'negative_count', 'total', 'positive_rate', 'binomial_p']
intraday_range dict keys=['nfp_avg_range', 'non_nfp_avg_range', 'range_ratio']
volume dict keys=['avg_volume_ratio', 'pct_above_avg']
april_nfp dict keys=['n', 'avg_abs_return', 'avg_signed_return', 'positive_rate', 'vol_ratio']
conclusions list n=4 first=['NFP days do NOT show significantly higher vol (1.10x, p=0.1284)']
practical_implication 'NFP does NOT warrant reducing SPY exposure. Vol ratio ~1.09x is statistically insignificant across all tests. Consistent with K513. For 04/03 NFP: focus on VIX level and broader conditions, not the NFP event itself.'
references list n=3 first=['K513: FOMC/NFP/CPI event study (2005-2025, 668 events)']
event_data list n=254 first=[{'date': '2005-02-04', 'year': 2005, 'month': 2, 'weekday': 4, 'event_return': 0.01067554897419587, 'event_abs_return': 0.01067554897419587, 'pre_avg_abs_return': 0.0036378071210083187, 'post_avg_abs_return': 0.004438089528654277, 'pre_vix': 11.789999961853027, 'event_vix': 11.210000038146973, 'post_vix_1d': 11.729999542236328, 'vix_change_event': -0.5799999237060547, 'high_low_range': 0.012060192196264882, 'volume_ratio': 0.9459350091597117}]

exec
/bin/zsh -lc "rg --files storage experiments/k528 | rg -i 'spy|yfinance|price|market|ohlc|parquet|\\.csv"'$'"' | sed -n '1,240p'
rg -n 'SPY.*Close|Date,Open,High,Low,Close|2005-01-0[3-9]' storage/data experiments/k528 --glob '*.csv' --glob '*.json' --glob '*.parquet' | sed -n '1,120p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
storage/market_status.json
storage/reports/nvda_spy_vix_2026.png
storage/reports/figures/earnings_vol_crossmarket_summary.png
storage/reports/figures/k1151_general_crossmarket_summary.png
storage/reports/figures/event_nfp_2026_06_05/market_reaction.png
storage/lazypack_jobs/mile_cdc7f6e8/panels/4_market_takeaway.png
storage/charts/mile_binary_universality_cross_market_theta.png
storage/ops/agent_briefs/k1684_e2_own_market_ftd_cross_oos.md
storage/drafts/assets/spy_vix_long_history_windows.png
storage/drafts/assets/spy_har_combo_cumulative.png
storage/drafts/assets/k1332_general_companion/k1499_hyg_spy_control.png
storage/drafts/assets/global_vix_cross_market.png
storage/drafts/assets/drone_ep2_price_paths.png
storage/article_assets/jpy_carry_move_transmission/raw_prices.csv
storage/experiments/cross_market_transmission.json
storage/experiments/spy_gld_correlation.json
storage/drafts/article_images/smart_model_spy_path.png
storage/drafts/drone_ep0_market_snapshot.json
storage/drafts/k1624_d_collapse_spy.png
storage/drafts/vt_crowding_market_dynamics.png
storage/drafts/k1624_breaks_spy.png
storage/drafts/assets/trending_tsmc_call_20260716/fig_a_price_30d.png
storage/drafts/assets/trending_tsmc_call_20260716/prices.json
storage/drafts/assets/trending_tsmc_call_20260716/tsm_daily.csv
storage/drafts/assets/trending_tsmc_call_20260716/twn2330_daily.csv
storage/drafts/assets/spy_vix_crisis_windows.png
storage/drafts/assets/trending_ai_concentration_20260716/daily_series.csv
storage/drafts/assets/spy_quantile_model_ranking.png
storage/drafts/assets/drone_ep4_price_vs_revenue.png
storage/drafts/assets/global_vix_market_improvement.png
storage/macro/fred_VALIMPTWM052N.csv
storage/macro/fred_DEXTAUS.csv
storage/macro/tw_dgbas_gdp_common.csv
storage/macro/fred_PPIACO.csv
storage/macro/fred_RBTWBIS.csv
storage/macro/fred_STLFSI4.csv
storage/macro/fred_UNRATE.csv
storage/macro/fred_T10YIE.csv
storage/macro/tw_dgbas_gdp_q.csv
storage/macro/tw_dgbas_cpi_m.csv
storage/macro/fred_STLFSI2.csv
storage/macro/fred_VALEXPTWM052N.csv
storage/macro/tw_dgbas_rate_m.csv
storage/macro/fred_BAMLH0A0HYM2.csv
storage/macro/fred_DGORDER.csv
storage/macro/fred_WUITWN.csv
storage/macro/tw_dgbas_trade_m.csv
storage/macro/fred_PCEPILFE.csv
storage/macro/fred_DGS2.csv
storage/macro/tw_dgbas_unemp_m.csv
storage/macro/yf_TWII.csv
storage/macro/fred_RNTWBIS.csv
storage/macro/yf_TWDX.csv
storage/macro/tw_cbc_A13RATE.csv
storage/macro/tw_dgbas_ipi_m.csv
storage/macro/fred_DGS10.csv
storage/macro/fred_GDP.csv
storage/macro/tw_dgbas_gdp_sa_q.csv
storage/macro/fred_GDPC1.csv
storage/macro/fred_EXP5830.csv
storage/macro/fred_TRESEGTWM194N.csv
storage/macro/fred_UMCSENT.csv
storage/macro/fred_POPTTLTWA148NRUG.csv
storage/macro/tw_dgbas_ppi_m.csv
storage/macro/fred_EFFR.csv
storage/macro/fred_PAYEMS.csv
storage/macro/fred_TWNPCPIPCPPPT.csv
storage/macro/fred_FEDFUNDS.csv
storage/macro/fred_NBTWBIS.csv
storage/macro/fred_RSAFS.csv
storage/macro/fred_M2SL.csv
storage/macro/yf_0050.TW.csv
storage/macro/fred_ICSA.csv
storage/macro/fred_TWNBCABP6USD.csv
storage/macro/fred_TWNNGDPRPCPPPT.csv
storage/macro/tw_dgbas_money_m.csv
storage/macro/tw_dgbas_bci_m.csv
storage/macro/fred_AWHMAN.csv
storage/macro/fred_TWNNGDPDUSD.csv
storage/macro/tw_dgbas_m2_m.csv
storage/macro/fred_GGGDTATWA188N.csv
storage/macro/fred_CPIAUCSL.csv
storage/macro/fred_RGDPNATWA666NRUG.csv
storage/macro/fred_WALCL.csv
storage/macro/fred_NNTWBIS.csv
storage/macro/fred_EXTAUS.csv
storage/macro/fred_PERMIT.csv
storage/macro/tw_dgbas_retail_m.csv
storage/macro/tw_dgbas_fx_m.csv
storage/macro/fred_INDPRO.csv
storage/macro/fred_HOUST.csv
storage/macro/fred_IMP5830.csv
storage/macro/tw_dgbas_MacroDatabase.csv
storage/next_draft_candidate_cross_market_binary.md
storage/drafts/assets/event_cpi_20260714_t0/vix_close.csv
storage/drafts/assets/event_cpi_20260714_t0/spy_close.csv
storage/drafts/assets/event_cpi_20260714_t0/market_raw.json
storage/drafts/assets/event_cpi_20260714_t0/fig1_spy_vix_around_cpi.png
storage/drafts/assets/spy_quantile_coverage.png
storage/drafts/assets/drone_ep0_market_cap.png
storage/drafts/assets/drone_ep3_price_paths.png
storage/drafts/assets/spy_har_combo_ranking.png
storage/logs/cron/market_cal.log
storage/logs/cron/market_closure_detect.log
storage/logs/cron/market_closure.log
storage/drafts/assets/digest_20260716/vix_close.csv
storage/drafts/assets/digest_20260716/ovx_close.csv
storage/drafts/assets/digest_20260716/wti_close.csv
storage/reports/master_var_panel.csv
storage/results/cross_asset_multistep_gjr.csv
storage/ops/agent_jobs/k1684_e2_own_market_ftd_cross_oos.json
storage/ops/locks/paper_snapshot_paper_leverage-direction_data_spy_vix_2004-2026.csv.lock
storage/ops/locks/paper_snapshot_paper_leverage-direction_data_spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv.lock
storage/ops/locks/paper_snapshot_paper_taiwan-vt_data_0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv.lock
storage/ops/locks/paper_snapshot_paper_volatility-absorption_data_spy_gld_tlt_qqq_eem_vix_2005-2026.csv.lock
storage/ops/locks/paper_snapshot_paper_crypto-fear-channel_data_spy_btc_usd_vix_2015-2026.csv.lock
storage/ops/locks/paper_snapshot_paper_vt-insurance-cost_data_spy_2006_2024.csv.lock
storage/ops/locks/paper_snapshot_paper_vt-insurance-cost_data_spy_gld_vix_vvix_2012-2024_snapshot.csv.lock
storage/ops/locks/paper_snapshot_paper_garch-x-vix_data_spy_vix_qqq_eem_fez_2000-2026.csv.lock
storage/ops/locks/paper_snapshot_paper_vt-insurance-cost_data_spy_2012_2024.csv.lock
storage/ops/locks/paper_snapshot_paper_vt-insurance-cost_data_spy_gld_2006-2024_rebal_snapshot.csv.lock
storage/ops/compute_queue/compute-paper3-e2-cross-market-copula-full-run-10-pairs-x-3-models-5-1780024655.json
storage/logs/compute/compute-k901-re-run-international-vt-13-markets-post-fix-gjr-converg-1778890480.stdout
storage/logs/compute/compute-k1426-oos-split-shard-a-pair-1-spy-ivv-pair-2-uso-bno-1784182380.stdout
storage/logs/compute/compute-k1558-candlestick-ohlc-spot-vol-direct-forecast-6-etfs-4-est-1782677424.stdout
storage/logs/compute/compute-paper3-e2-cross-market-copula-full-run-10-pairs-x-3-models-5-1780024655.stdout
storage/ops/compute_queue/compute-k1558-candlestick-ohlc-spot-vol-direct-forecast-6-etfs-4-est-1782677424.json
storage/ops/compute_queue/compute-k901-re-run-international-vt-13-markets-post-fix-gjr-converg-1778890480.json
storage/ops/compute_queue/compute-k1426-oos-split-shard-a-pair-1-spy-ivv-pair-2-uso-bno-1784182380.json
storage/ops/compute_queue/k1684_e2_own_market_ftd_cross_oos.json
storage/logs/compute/compute-paper3-e2-cross-market-copula-full-run-10-pairs-x-3-models-5-1780024655.stderr
storage/logs/compute/compute-k901-re-run-international-vt-13-markets-post-fix-gjr-converg-1778890480.stderr
storage/logs/compute/compute-k1558-candlestick-ohlc-spot-vol-direct-forecast-6-etfs-4-est-1782677424.stderr
storage/logs/compute/compute-k1426-oos-split-shard-a-pair-1-spy-ivv-pair-2-uso-bno-1784182380.stderr
storage/logs/compute/k1684_e2_own_market_ftd_cross_oos.stderr
storage/logs/compute/k1684_e2_own_market_ftd_cross_oos.stdout
storage/sentiment/credit_spread_proxy.csv
storage/sentiment/skew_index.csv
storage/sentiment/google_trends_weekly_vix.csv
storage/sentiment/cnn_fear_greed_historical.csv
storage/sentiment/google_trends_weekly_crash.csv
storage/sentiment/vix_historical.csv
storage/sentiment/tw_margin_0050.csv
storage/sentiment/tw_institutional_0050.csv
storage/sentiment/vvix_historical.csv
storage/sentiment/google_trends_vix_crash.csv
storage/sentiment/aaii_sentiment.csv
storage/sentiment/shiller_cape.csv
storage/sentiment/treasury_yield_spread.csv
storage/sentiment/google_trends_weekly_tw_disaster.csv
storage/sentiment/tw_pe_2330.csv
storage/sentiment/fred_umcsent.csv
storage/sentiment/google_trends_weekly_tw_crash.csv
storage/sentiment/crypto_fear_greed.csv
storage/sentiment/google_trends_taiwan.csv
storage/sentiment/tw_pcr_taifex.csv

exec
/bin/zsh -lc "rg --files paper | rg 'spy.*vix.*200[0-9]-2026|volatility-absorption/data|leverage-direction/data' | sed -n '1,160p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
paper/volatility-absorption/data_sources.md
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv
paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv
paper/taiwan-vt/data/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv
paper/leverage-direction/data/README.md
paper/leverage-direction/data/vix_daily.csv
paper/leverage-direction/data/spy_qqq_gld_tlt_eem_iwm_slv_btc_usd_vix_2010-2026.csv
paper/leverage-direction/data/spy_vix_2004-2026.csv
paper/leverage-direction/data_sources.md

exec
/bin/zsh -lc "sed -n '1,8p' paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv
sed -n '1,8p' paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv
rg -n '"'^2005-02-04|''^2005-01-07|''^2026-03-2[67]'"' paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
date,eem_adj_close,gld_adj_close,qqq_adj_close,spy_adj_close,tlt_adj_close,vix_adj_close,eem_close,gld_close,qqq_close,spy_close,tlt_close,vix_close,eem_high,gld_high,qqq_high,spy_high,tlt_high,vix_high,eem_low,gld_low,qqq_low,spy_low,tlt_low,vix_low,eem_open,gld_open,qqq_open,spy_open,tlt_open,vix_open,eem_volume,gld_volume,qqq_volume,spy_volume,tlt_volume,vix_volume
2005-01-03,14.562676429748535,43.02000045776367,33.65294647216797,81.38371276855469,44.5604248046875,14.079999923706055,22.19444465637207,43.02000045776367,39.5,120.30000305175781,88.73999786376953,14.079999923706055,22.494443893432617,43.16999816894531,40.290000915527344,121.76000213623047,88.83999633789062,14.229999542236328,22.15333366394043,42.7400016784668,39.369998931884766,119.9000015258789,88.16000366210938,13.25,22.41111183166504,42.97999954223633,40.09000015258789,121.55999755859375,88.18000030517578,13.390000343322754,4275000,4750400,100970900,55748000,1168000,0
2005-01-04,14.114309310913086,42.7400016784668,33.03953552246094,80.38926696777344,44.09343338012695,13.979999542236328,21.511110305786133,42.7400016784668,38.779998779296875,118.83000183105469,87.80999755859375,13.979999542236328,22.149999618530273,42.90999984741211,39.7400016784668,120.54000091552734,88.75,14.449999809265137,21.511110305786133,42.459999084472656,38.54999923706055,118.44000244140625,87.80999755859375,13.930000305175781,22.13888931274414,42.79999923706055,39.66999816894531,120.45999908447266,88.72000122070312,14.010000228881836,4205700,3456800,136623200,69167600,1935400,0
2005-01-05,13.94153118133545,42.66999816894531,32.835044860839844,79.83454895019531,44.32943344116211,14.09000015258789,21.247777938842773,42.66999816894531,38.540000915527344,118.01000213623047,88.27999877929688,14.09000015258789,21.530000686645508,42.880001068115234,38.959999084472656,119.25,88.55000305175781,14.09000015258789,21.244443893432617,42.599998474121094,38.470001220703125,118.0,87.94000244140625,13.260000228881836,21.488889694213867,42.75,38.68000030517578,118.73999786376953,87.98999786376953,13.979999542236328,3006900,2033600,127925500,65667300,1094100,0
2005-01-06,13.932056427001953,42.150001525878906,32.67316818237305,80.2404556274414,44.35958480834961,13.579999923706055,21.233333587646484,42.150001525878906,38.349998474121094,118.61000061035156,88.33999633789062,13.579999923706055,21.34666633605957,42.560001373291016,38.709999084472656,119.1500015258789,88.54000091552734,14.09000015258789,21.12555694580078,42.06999969482422,38.34000015258789,118.26000213623047,88.22000122070312,13.329999923706055,21.316667556762695,42.47999954223633,38.630001068115234,118.44000244140625,88.29000091552734,14.09000015258789,2268000,2556400,102934600,47814700,1057400,0
2005-01-07,13.959029197692871,41.84000015258789,32.84358215332031,80.12543487548828,44.46000671386719,13.489999771118164,21.274444580078125,41.84000015258789,38.54999923706055,118.44000244140625,88.54000091552734,13.489999771118164,21.41777801513672,42.38999938964844,38.869998931884766,119.2300033569336,88.87000274658203,13.510000228881836,21.166667938232422,41.70000076293945,38.209999084472656,118.12999725341797,88.3499984741211,12.9399995803833,21.377777099609375,42.09000015258789,38.560001373291016,118.97000122070312,88.76000213623047,13.470000267028809,4920300,4492700,123104000,55847700,738700,0
2005-01-10,13.976521492004395,41.95000076293945,32.8265380859375,80.5042495727539,44.530277252197266,13.229999542236328,21.301111221313477,41.95000076293945,38.529998779296875,119.0,88.68000030517578,13.229999542236328,21.512222290039062,42.06999969482422,38.869998931884766,119.45999908447266,88.72000122070312,13.930000305175781,21.294443130493164,41.88999938964844,38.38999938964844,118.33999633789062,88.47000122070312,12.9399995803833,21.399999618530273,41.9900016784668,38.439998626708984,118.33999633789062,88.63999938964844,13.920000076293945,2007000,1025800,88764200,56563300,379400,0
2005-01-11,13.950273513793945,42.209999084472656,32.596492767333984,79.94953918457031,44.79143142700195,13.1899995803833,21.261110305786133,42.209999084472656,38.2599983215332,118.18000030517578,89.19999694824219,13.1899995803833,21.405555725097656,42.279998779296875,38.5,118.73999786376953,89.27999877929688,13.680000305175781,21.22333335876465,42.119998931884766,38.06999969482422,117.98999786376953,88.73999786376953,13.050000190734863,21.399999618530273,42.209999084472656,38.369998931884766,118.63999938964844,88.9000015258789,13.4399995803833,2440800,1507300,106398800,63099700,844100,0
date,eem_adj_close,fez_adj_close,qqq_adj_close,spy_adj_close,vix_adj_close,eem_close,fez_close,qqq_close,spy_close,vix_close,eem_high,fez_high,qqq_high,spy_high,vix_high,eem_low,fez_low,qqq_low,spy_low,vix_low,eem_open,fez_open,qqq_open,spy_open,vix_open,eem_volume,fez_volume,qqq_volume,spy_volume,vix_volume
2000-01-03,,,79.92739868164062,91.36750030517578,24.209999084472656,,,94.75,145.4375,24.209999084472656,,,96.1875,148.25,26.149999618530273,,,90.75,143.875,23.979999542236328,,,96.1875,148.25,24.360000610351562,,,36345200,8164300,0
2000-01-04,,,74.44425964355469,87.7945327758789,27.010000228881836,,,88.25,139.75,27.010000228881836,,,93.5,144.0625,27.18000030517578,,,87.9375,139.640625,24.799999237060547,,,92.0,143.53125,24.940000534057617,,,33786600,8089800,0
2000-01-05,,,72.54622650146484,87.95154571533203,26.40999984741211,,,86.0,140.0,26.40999984741211,,,89.625,141.53125,29.0,,,84.25,137.25,25.850000381469727,,,87.5,139.9375,27.979999542236328,,,42496600,12177900,0
2000-01-06,,,67.56397247314453,86.53801727294922,25.729999542236328,,,80.09375,137.75,25.729999542236328,,,88.0,141.5,26.709999084472656,,,79.75,137.75,24.700000762939453,,,86.875,139.625,26.68000030517578,,,37134800,6227200,0
2000-01-07,,,75.92051696777344,91.5638656616211,21.719999313354492,,,90.0,145.75,21.719999313354492,,,90.0,145.75,25.170000076293945,,,82.5,140.0625,21.719999313354492,,,82.9375,140.3125,25.139999389648438,,,28138200,8066500,0
2000-01-10,,,78.0294189453125,91.87793731689453,21.709999084472656,,,92.5,146.25,21.709999084472656,,,93.9375,146.90625,22.489999771118164,,,89.9375,145.03125,21.360000610351562,,,91.0,146.25,21.889999389648438,,,29675600,5741700,0
2000-01-11,,,74.23335266113281,90.77855682373047,22.5,,,88.0,144.5,22.5,,,92.875,146.09375,22.6299991607666,,,87.0,143.5,21.690000534057617,,,91.75,145.8125,21.979999542236328,,,32546600,7503700,0
paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv:1262:2005-01-07,13.959030151367188,19.77303695678711,32.843563079833984,80.12545013427734,13.489999771118164,21.274444580078125,38.970001220703125,38.54999923706055,118.44000244140625,13.489999771118164,21.41777801513672,39.58000183105469,38.869998931884766,119.2300033569336,13.510000228881836,21.166667938232422,38.810001373291016,38.209999084472656,118.12999725341797,12.9399995803833,21.377777099609375,39.459999084472656,38.560001373291016,118.97000122070312,13.470000267028809,4920300.0,24700.0,123104000,55847700,0
paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv:1281:2005-02-04,15.025619506835938,20.178951263427734,32.161983489990234,81.33636474609375,11.210000038146973,22.899999618530273,39.77000045776367,37.75,120.2300033569336,11.210000038146973,22.933332443237305,39.77000045776367,37.81999969482422,120.43000030517578,11.970000267028809,22.622222900390625,39.400001525878906,37.150001525878906,118.9800033569336,10.899999618530273,22.681110382080078,39.400001525878906,37.150001525878906,119.0,11.970000267028809,2437200.0,37800.0,99302000,50024600,0
paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv:6598:2026-03-26,55.470001220703125,60.459999084472656,573.7899780273438,645.0900268554688,27.440000534057617,55.470001220703125,60.459999084472656,573.7899780273438,645.0900268554688,27.440000534057617,56.63999938964844,61.52000045776367,584.6300048828125,654.8499755859375,28.489999771118164,55.439998626708984,60.43000030517578,573.4299926757812,644.8200073242188,26.1200008392334,56.2599983215332,61.02000045776367,582.5999755859375,652.0599975585938,26.489999771118164,42794900.0,2215200.0,81492100,96494400,0
paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv:6599:2026-03-27,55.20000076293945,59.79999923706055,562.5800170898438,634.0900268554688,31.049999237060547,55.20000076293945,59.79999923706055,562.5800170898438,634.0900268554688,31.049999237060547,55.7400016784668,60.650001525878906,571.02001953125,642.6599731445312,31.649999618530273,55.0,59.619998931884766,561.5700073242188,633.1099853515625,27.540000915527344,55.349998474121094,60.25,570.8099975585938,642.5,27.540000915527344,38596100.0,1782300.0,82702200,103649400,0
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv:6:2005-01-07,13.959029197692871,41.84000015258789,32.84358215332031,80.12543487548828,44.46000671386719,13.489999771118164,21.274444580078125,41.84000015258789,38.54999923706055,118.44000244140625,88.54000091552734,13.489999771118164,21.41777801513672,42.38999938964844,38.869998931884766,119.2300033569336,88.87000274658203,13.510000228881836,21.166667938232422,41.70000076293945,38.209999084472656,118.12999725341797,88.3499984741211,12.9399995803833,21.377777099609375,42.09000015258789,38.560001373291016,118.97000122070312,88.76000213623047,13.470000267028809,4920300,4492700,123104000,55847700,738700,0
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv:25:2005-02-04,15.025618553161621,41.470001220703125,32.1619987487793,81.33637237548828,46.69950866699219,11.210000038146973,22.899999618530273,41.470001220703125,37.75,120.2300033569336,92.6500015258789,11.210000038146973,22.933332443237305,41.650001525878906,37.81999969482422,120.43000030517578,92.94000244140625,11.970000267028809,22.622222900390625,41.38999938964844,37.150001525878906,118.9800033569336,92.45999908447266,10.899999618530273,22.681110382080078,41.59000015258789,37.150001525878906,119.0,92.47000122070312,11.970000267028809,2437200,1819400,99302000,50024600,3483900,0
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv:5342:2026-03-26,55.470001220703125,400.6400146484375,573.7899780273438,645.0900268554688,85.7673110961914,27.440000534057617,55.470001220703125,400.6400146484375,573.7899780273438,645.0900268554688,86.11000061035156,27.440000534057617,56.63999938964844,411.3699951171875,584.6300048828125,654.8499755859375,86.61000061035156,28.489999771118164,55.439998626708984,400.260009765625,573.4299926757812,644.8200073242188,85.93000030517578,26.1200008392334,56.2599983215332,408.5299987792969,582.5999755859375,652.0599975585938,86.33999633789062,26.489999771118164,42794900,15756300,81492100,96494400,39537000,0
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv:5343:2026-03-27,55.20000076293945,414.70001220703125,562.5800170898438,634.0900268554688,85.29917907714844,31.049999237060547,55.20000076293945,414.70001220703125,562.5800170898438,634.0900268554688,85.63999938964844,31.049999237060547,55.7400016784668,418.3999938964844,571.02001953125,642.6599731445312,86.0999984741211,31.649999618530273,55.0,405.4100036621094,561.5700073242188,633.1099853515625,85.44999694824219,27.540000915527344,55.349998474121094,406.20001220703125,570.8099975585938,642.5,85.5,27.540000915527344,38596100,16580700,82702200,103649400,39928900,0

exec
/bin/zsh -lc "python -c 'import json,subprocess,pprint; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; g=lambda p: json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",f\"2abb3f68c:{p}\"])); x=g(\"experiments/k528/k528_nfp_event_study_results.json\"); pprint.pp(x[\"sample\"]); pprint.pp(x[\"main_results\"]); pprint.pp(x[\"statistical_tests\"][\"A_nfp_vs_all\"]); pprint.pp(x[\"statistical_tests\"][\"B_nfp_vs_friday\"]); pprint.pp(x[\"statistical_tests\"][\"B_diagnostic_mixed_weekday\"]); a=g(\"experiments/k528/k528_nfp_official_dates_results.json\"); pprint.pp(a[\"items\"][\"vol_ratio_vs_friday\"]); pprint.pp(a[\"article_correction\"][\"residual_gap\"])'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
{'total_nfp_events': 253,
 'date_range': '2005-02-04 to 2026-03-06',
 'non_nfp_trading_days': 5086,
 'friday_baseline_days': 834,
 'nfp_days_on_friday': 237,
 'event_mapping_audit': {'n_official_releases': 254,
                         'n_mapped_to_sessions': 254,
                         'n_shifted_to_next_session': 6,
                         'n_outside_price_sample': 0,
                         'outside_price_sample_dates': [],
                         'n_excluded_for_window_buffer': 1,
                         'window_excluded_dates': ['2005-01-07'],
                         'n_valid_events': 253},
 'calendar_completeness': {'n_months_in_span': 255,
                           'n_raw_entries': 260,
                           'months_with_multiple_raw_entries': ['2006-05',
                                                                '2012-12',
                                                                '2013-05',
                                                                '2020-05',
                                                                '2024-01',
                                                                '2024-08'],
                           'known_missing_months': {'2025-10': 'Federal '
                                                               'government '
                                                               'shutdown. '
                                                               'ALFRED shows '
                                                               'no release id '
                                                               '50 entry '
                                                               'between '
                                                               '2025-09-05 and '
                                                               '2025-11-20 (76 '
                                                               'days against a '
                                                               '~30-day '
                                                               'cadence); the '
                                                               'delayed '
                                                               'September '
                                                               'report landed '
                                                               'on 11-20. Same '
                                                               'shutdown that '
                                                               'cancelled the '
                                                               'Oct-2025 CPI '
                                                               'release '
                                                               'described in '
                                                               'volpred/data/event_dates.py. '
                                                               'The '
                                                               'first-Friday '
                                                               'proxy INVENTED '
                                                               'an event here '
                                                               '-- that '
                                                               'phantom is one '
                                                               'of the reasons '
                                                               'for this '
                                                               'rerun.'},
                           'ambiguity_gap_threshold_days': 3}}
{'nfp_avg_abs_return': 0.008453056751192095,
 'nfp_avg_abs_return_pct': '0.845%',
 'non_nfp_avg_abs_return': 0.007630635156015721,
 'non_nfp_avg_abs_return_pct': '0.763%',
 'friday_baseline_abs_return': 0.007183321144437934,
 'vol_ratio_vs_all': 1.1077789172671957,
 'vol_ratio_vs_friday': 1.1889943941490353}
{'test': 'Welch t-test',
 't_stat': 1.5938698340236177,
 'p_value': 0.11206534461843846,
 'significant_5pct': False}
{'test': 'Welch t-test, Friday NFP sessions vs Friday non-NFP sessions',
 'estimand': 'CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the '
             'event group is restricted to NFP releases that trade on a '
             'Friday, and the 16 non-Friday events are excluded rather than '
             'compared against a pure-Friday control group.',
 'claim_scope': 'This identifies the effect of an NFP release ON A FRIDAY. It '
                'does not license a statement about NFP releases in general -- '
                'the excluded non-Friday events are quieter, so the '
                'restriction raises the ratio relative to the mixed-weekday '
                "spec. Any prose quoting this number must say 'Friday NFP', "
                "not 'NFP'.",
 'restriction_is_not_neutral': {'excluded_mean_abs_return': 0.007151455403861362,
                                'friday_mean_abs_return': 0.008540928572108936,
                                'excluded_are_quieter_by_pct': 16.268408715944616},
 'n_event': 237,
 'n_control': 834,
 'vol_ratio': 1.1889943941490353,
 't_stat': 2.320506683032578,
 'p_value': 0.020854393889216647,
 'significant_5pct': True,
 'excluded_non_friday_events': {'n': 16,
                                'mean_abs_return': 0.007151455403861362}}
{'test': 'Welch t-test, ALL NFP events vs Friday non-NFP sessions',
 'status': 'DIAGNOSTIC ONLY - do not quote',
 'why_not_a_headline': 'this is the pre-correction specification: a '
                       'weekday-mixed event group against a pure-Friday '
                       'control group, so the p-value absorbs any '
                       'Friday-vs-other-weekday volatility difference. '
                       'Retained solely so the correction audit can show what '
                       'the contaminated estimand was worth (k528 Codex v2 '
                       'finding 5).',
 'vol_ratio': 1.1767616373016152,
 't_stat': 2.2390165569579286,
 'p_value': 0.025692303463617307,
 'significant_5pct': True}
{'label': 'NFP vs non-NFP Friday baseline (article: 1.17x)',
 'before': {'mean_ratio': 1.1678305805326317,
            'p_value': 0.04093676828523356,
            'significant_5pct': True,
            'n': 239,
            'nfp_days_on_friday': 239,
            'median_ratio': 1.1982080672282966,
            'win_rate': 0.5564853556485355,
            'estimand': 'Friday NFP sessions vs Friday non-NFP sessions '
                        '(weekday held fixed)',
            'as_published_mixed_weekday': {'mean_ratio': 1.168212716801256,
                                           'p_value': 0.03354366521379227,
                                           'significant_5pct': True,
                                           'n': 254,
                                           'note': 'what the proxy run '
                                                   'actually published: all '
                                                   '254 events (239 Friday, 15 '
                                                   'Monday) against non-NFP '
                                                   'Fridays. This is the '
                                                   'number the article quoted, '
                                                   'so it is kept, but it is '
                                                   'NOT the like-for-like '
                                                   'comparison against the '
                                                   'corrected column.'}},
 'after': {'mean_ratio': 1.1889943941490353,
           'p_value': 0.020854393889216647,
           'significant_5pct': True,
           'n': 237,
           'nfp_days_on_friday': 237,
           'median_ratio': 1.2184396832095086,
           'win_rate': 0.569620253164557,
           'estimand': 'Friday NFP sessions vs Friday non-NFP sessions '
                       '(weekday held fixed)',
           'diagnostic_mixed_weekday': {'mean_ratio': 1.1767616373016152,
                                        'p_value': 0.025692303463617307,
                                        'significant_5pct': True,
                                        'n': 253,
                                        'status': 'DIAGNOSTIC ONLY - the '
                                                  'pre-correction estimand, '
                                                  'not quotable'}},
 'note': 'Two things changed here and they are separated rather than '
         'conflated. (1) The dates were corrected. (2) The ESTIMAND was '
         'corrected: the event group is a weekday mixture while the control '
         'group is pure Friday, so the test now restricts the event group to '
         'Friday releases. Defect (2) was NOT created by (1) -- the proxy run '
         'was already mixed (239/254 Friday, the other 15 being '
         'holiday-shifted Mondays), it was simply never noticed. Both columns '
         'above therefore use the SAME restricted estimand so the delta is '
         'attributable to the dates alone; `as_published_mixed_weekday` '
         '(before) and `diagnostic_mixed_weekday` (after) hold the old '
         'estimand on each side for reference.',
 'verdict': 'NUMERIC_ADJUSTMENT',
 'verdict_reasons': []}
('The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) '
 'and the two lazypack images still render proxy-era numbers. Text and images '
 'now disagree; the article carries a visible note saying so. Regenerating and '
 "re-uploading them is follow-up work outside this worktree's scope.")

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '715,900p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '430,560p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
   715	print(f"    → Non-significance of a mean test is not evidence of no effect")
   716	
   717	# ============================================================
   718	# 9b. Correction audit: every published number, before vs after
   719	# ============================================================
   720	# A mean can sit still while the median and the win rate move underneath it,
   721	# so no claim is judged on its mean alone. Each item carries mean / median /
   722	# win rate / n / significance, and the flip test looks at all of them.
   723	print(f"\n{'=' * 60}")
   724	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
   725	print("=" * 60)
   726	
   727	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
   728	if not PROXY_PATH.exists():
   729	    raise FileNotFoundError(
   730	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
   731	        "only record of what the published article claimed. Do not regenerate it."
   732	    )
   733	proxy = json.loads(PROXY_PATH.read_text())
   734	
   735	
   736	def win_rate(sample, reference):
   737	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
   738	    ref_med = float(np.median(reference))
   739	    return float(np.mean(np.asarray(sample) > ref_med))
   740	
   741	
   742	# The proxy run only ever reported means, and a mean can hold still while the
   743	# median and the win rate move underneath it. Rather than leave the before-side
   744	# of those two columns null -- which would make the comparison unable to detect
   745	# exactly the failure it is looking for -- rebuild the proxy-era distributions
   746	# from the ARCHIVED per-event data. The dates come out of the archive, so this
   747	# reconstructs history without reintroducing a proxy calendar generator.
   748	proxy_events = proxy["event_data"]
   749	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
   750	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
   751	proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
   752	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
   753	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
   754	
   755	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
   756	# mapped to a Monday because the first Friday was a market holiday. So the
   757	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
   758	# rebuild the proxy side under the SAME estimand the corrected run uses
   759	# (Friday events only) rather than comparing a mixed `before` against a
   760	# restricted `after` and calling the difference a correction effect.
   761	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
   762	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
   763	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
   764	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
   765	
   766	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   767	                       for e in proxy_events])
   768	_p_thr = proxy["regime_analysis"]["vix_median_split"]
   769	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   770	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   771	
   772	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
   773	# reconstruction is wrong and its medians cannot be trusted either.
   774	for _label, _rebuilt, _archived in (
   775	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   776	    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   777	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   778	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   779	):
   780	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   781	        raise AssertionError(
   782	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   783	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   784	            "from a reconstruction that cannot reproduce the archived means."
   785	        )
   786	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   787	
   788	audit_items = {}
   789	
   790	
   791	def record(key, label, before, after, note=""):
   792	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   793	
   794	
   795	# --- 1.10x : NFP vs all non-NFP days ---
   796	record(
   797	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   798	    {
   799	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   800	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   801	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   802	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   803	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   804	        "n": proxy["sample"]["total_nfp_events"],
   805	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   806	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   807	    },
   808	    {
   809	        "mean_ratio": vol_ratio_all,
   810	        "nfp_mean": float(nfp_abs_returns.mean()),
   811	        "baseline_mean": baseline_abs_return,
   812	        "p_value": float(p_val_all),
   813	        "significant_5pct": bool(p_val_all < 0.05),
   814	        "n": int(len(df)),
   815	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   816	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   817	    },
   818	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   819	         "per-event data, not from the proxy run's own output (it only reported means).",
   820	)
   821	
   822	# --- 1.17x : NFP vs Friday-only baseline ---
   823	record(
   824	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   825	    {
   826	        # Same estimand as the `after` column: Friday events only.
   827	        "mean_ratio": proxy_ratio_fri_restricted,
   828	        "p_value": float(_p_p_fri),
   829	        "significant_5pct": bool(_p_p_fri < 0.05),
   830	        "n": int(len(proxy_nfp_friday_abs)),
   831	        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
   832	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
   833	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
   834	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   835	        "as_published_mixed_weekday": {
   836	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   837	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   838	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   839	            "n": proxy["sample"]["total_nfp_events"],
   840	            "note": (
   841	                "what the proxy run actually published: all 254 events (239 Friday, "
   842	                "15 Monday) against non-NFP Fridays. This is the number the article "
   843	                "quoted, so it is kept, but it is NOT the like-for-like comparison "
   844	                "against the corrected column."
   845	            ),
   846	        },
   847	    },
   848	    {
   849	        "mean_ratio": vol_ratio_fri,
   850	        "p_value": float(p_val_fri),
   851	        "significant_5pct": bool(p_val_fri < 0.05),
   852	        "n": int(len(nfp_friday_abs)),
   853	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   854	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
   855	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
   856	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   857	        "diagnostic_mixed_weekday": {
   858	            "mean_ratio": vol_ratio_fri_mixed,
   859	            "p_value": float(p_val_fri_mixed),
   860	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
   861	            "n": int(len(df)),
   862	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
   863	        },
   864	    },
   865	    note="Two things changed here and they are separated rather than conflated. "
   866	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
   867	         "event group is a weekday mixture while the control group is pure "
   868	         "Friday, so the test now restricts the event group to Friday releases. "
   869	         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
   870	         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
   871	         "simply never noticed. Both columns above therefore use the SAME "
   872	         "restricted estimand so the delta is attributable to the dates alone; "
   873	         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
   874	         "(after) hold the old estimand on each side for reference.",
   875	)
   876	
   877	# --- 2.17x : high-VIX vs low-VIX regime ---
   878	proxy_reg = proxy["regime_analysis"]
   879	record(
   880	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   881	    {
   882	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
   883	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
   884	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
   885	        "n_high": proxy_reg["n_high"],
   886	        "n_low": proxy_reg["n_low"],
   887	        "p_value": proxy_reg["p_value"],
   888	        "significant_5pct": proxy_reg["p_value"] < 0.05,
   889	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
   890	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
   891	    },
   892	    {
   893	        "mean_ratio": float(high_vix.mean() / low_vix.mean()),
   894	        "high_mean": float(high_vix.mean()),
   895	        "low_mean": float(low_vix.mean()),
   896	        "n_high": int(len(high_vix)),
   897	        "n_low": int(len(low_vix)),
   898	        "p_value": float(p_regime),
   899	        "significant_5pct": bool(p_regime < 0.05),
   900	        "median_ratio": float(high_vix.median() / low_vix.median()),
   430	# it visible, not what caused it.
   431	friday_mask = non_nfp.index.weekday == 4
   432	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
   433	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
   434	
   435	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   436	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
   437	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   438	
   439	# ============================================================
   440	# 6. Statistical tests
   441	# ============================================================
   442	print("\n[5/6] Running statistical tests...")
   443	
   444	nfp_abs_returns = df["event_abs_return"].values
   445	non_nfp_abs_returns = non_nfp["AbsReturn"].values
   446	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
   447	
   448	# --- Test A: NFP vs all non-NFP days ---
   449	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
   450	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
   451	
   452	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
   453	#
   454	# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
   455	#   (i)  restrict the event group to Friday releases, or
   456	#   (ii) keep all events and use weekday-matched controls.
   457	# This run takes (i). The non-Friday events are a handful of thin weekday cells
   458	# out of 253 -- cells that thin make (ii) a weighted average dominated by a few
   459	# single-digit strata, with standard errors driven by the smallest of them.
   460	# That is a noisier estimator of a harder-to-state quantity. (i) answers one
   461	# clean question: on a Friday, does an NFP release raise volatility? It costs
   462	# the non-Friday events, which are reported below as a separate descriptive
   463	# line rather than dropped in silence.
   464	#
   465	# The exclusion is not neutral and should not be sold as such: the excluded
   466	# events are quieter than the Friday ones, so restricting RAISES the ratio
   467	# relative to the mixed spec. That is a property of the estimand, not evidence
   468	# of a stronger effect. Both numbers are reported.
   469	nfp_friday_mask = (df["weekday"] == 4).values
   470	nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
   471	nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
   472	
   473	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
   474	vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
   475	
   476	# Diagnostic ONLY -- the pre-correction specification, kept so the correction
   477	# audit can show what the contaminated estimand was worth. Not a headline
   478	# number and not eligible to be quoted: its p-value mixes in weekday
   479	# composition, which is exactly the defect being repaired.
   480	t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
   481	    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
   482	vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
   483	
   484	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
   485	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
   486	
   487	# --- Test D: Vol crush pattern (post vs pre) ---
   488	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
   489	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
   490	
   491	# --- Test E: VIX predictive regression ---
   492	vix_valid = df.dropna(subset=["pre_vix"])
   493	if len(vix_valid) > 10:
   494	    from numpy.polynomial.polynomial import polyfit
   495	    X_vix = vix_valid["pre_vix"].values
   496	    Y_abs = vix_valid["event_abs_return"].values
   497	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
   498	    # correlation and p-value
   499	    r_vix, p_vix = stats.pearsonr(X_vix, Y_abs)
   500	    # also spearman
   501	    rho_vix, p_rho_vix = stats.spearmanr(X_vix, Y_abs)
   502	else:
   503	    slope, intercept, r_vix, p_vix, rho_vix, p_rho_vix = [None]*6
   504	
   505	# --- Test F: Pre-event VIX change (buildup) ---
   506	# Compare VIX at T-5 vs T-1 (is there anticipatory VIX increase?)
   507	vix_buildup = []
   508	for nfp_date in valid_nfp:
   509	    pos = idx_list.index(nfp_date)
   510	    pre5 = spy.iloc[pos-5]
   511	    pre1 = spy.iloc[pos-1]
   512	    if pd.notna(pre5["VIX"]) and pd.notna(pre1["VIX"]):
   513	        vix_buildup.append(float(pre1["VIX"] - pre5["VIX"]))
   514	
   515	t_buildup, p_buildup = stats.ttest_1samp(vix_buildup, 0) if len(vix_buildup) > 5 else (None, None)
   516	
   517	# --- Test G: Seasonal analysis (by month) ---
   518	monthly_stats = {}
   519	for month in range(1, 13):
   520	    month_data = df[df["month"] == month]["event_abs_return"]
   521	    if len(month_data) >= 5:
   522	        monthly_stats[str(month)] = {
   523	            "n": int(len(month_data)),
   524	            "mean_abs_return": float(month_data.mean()),
   525	            "vol_ratio": float(month_data.mean() / baseline_abs_return),
   526	            "t_stat": float(stats.ttest_1samp(month_data, baseline_abs_return)[0]),
   527	            "p_val": float(stats.ttest_1samp(month_data, baseline_abs_return)[1]),
   528	        }
   529	
   530	# --- Test H: Regime analysis (high VIX vs low VIX) ---
   531	vix_median = df["pre_vix"].median()
   532	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
   533	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
   534	t_regime, p_regime = stats.ttest_ind(high_vix, low_vix, equal_var=False)
   535	
   536	# --- Test I: Time trend (has NFP impact changed over time?) ---
   537	# Split into halves
   538	midpoint = len(df) // 2
   539	first_half = df.iloc[:midpoint]["event_abs_return"]
   540	second_half = df.iloc[midpoint:]["event_abs_return"]
   541	t_trend, p_trend = stats.ttest_ind(first_half, second_half, equal_var=False)
   542	
   543	# --- Test J: Event-day return direction ---
   544	pos_returns = (df["event_return"] > 0).sum()
   545	neg_returns = (df["event_return"] < 0).sum()
   546	# Binomial test: is there a directional bias?
   547	binom_p = float(stats.binomtest(pos_returns, pos_returns + neg_returns, 0.5).pvalue)
   548	
   549	print("\n" + "=" * 60)
   550	print("RESULTS")
   551	print("=" * 60)
   552	
   553	print(f"\n--- A. NFP vs All Non-NFP Days ---")
   554	print(f"  NFP day |return|:     {nfp_abs_returns.mean():.6f} ({nfp_abs_returns.mean()*100:.3f}%)")
   555	print(f"  Non-NFP |return|:     {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   556	print(f"  Vol ratio:            {vol_ratio_all:.3f}x")
   557	print(f"  t-stat:               {t_stat_all:.3f}")
   558	print(f"  p-value:              {p_val_all:.4f}")
   559	print(f"  Significant (5%):     {'YES' if p_val_all < 0.05 else 'NO'}")
   560	

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/README.md | nl -ba | sed -n '1,230p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/build_article_correction.py | nl -ba | sed -n '1,300p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
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
    71	事件組是**星期別混合**、對照組是**純週五**，週五本身的波動特性會直接混進 p 值。
    72	
    73	**這個缺陷不是日期修正造成的 —— 修正只是讓它被看見。** proxy 的*日曆*確實每場都是週五，
    74	但遇休市會映射到下一個 session，所以它實際的 254 場事件裡有 **15 場是週一**（239/254 =
    75	94.1% 在週五）；官方日曆是 237/253 = 93.7%。混合程度幾乎沒變，舊版一直都在拿混合事件組
    76	比純週五對照組，只是從來沒人注意到。
    77	
    78	本輪把事件組**限定為在週五公布的 237 場**，兩邊星期別一致。另一個選項是保留全部 253 場
    79	改用 weekday-matched controls，未採用的理由：非週五事件是週一 6、週二 2、週三 1、週四 7，
    80	用這種格數做加權平均，標準誤會被 1 筆的週三格主導 —— 那是對一個更難陳述的量做更吵的估計。
    81	
    82	**限定週五不是中性的樣本刪除，這點必須明講**：被排除的 16 場平均 |ret| 是 0.715%，比週五
    83	NFP 的 0.854% **低 16.3%**，所以限定之後 ratio 會被墊高（1.177× → 1.189×）。那是口徑的
    84	性質，不是效果變強的證據。
    85	
    86	**因此這個檢定識別的是「週五公布的 NFP」，不是「NFP 一般而言」。** 引用這個數字的文字
    87	必須寫「在週五公布的 NFP」。
    88	
    89	兩種口徑在 audit 中**兩邊平行呈現**（修正前後各自都算了兩種），不拿不同口徑硬比：
    90	
    91	| | 限定週五（主口徑） | 混合星期別（舊口徑） |
    92	|---|---|---|
    93	| 修正前（proxy） | 1.168× / p=0.0409 / n=239 | 1.168× / p=0.0335 / n=254（文章當初引用的） |
    94	| 修正後（官方） | **1.189× / p=0.0209 / n=237** | 1.177× / p=0.0257 / n=253（DIAGNOSTIC ONLY） |
    95	
    96	**兩種口徑、修正前後，四格全部顯著** —— 「顯著→不顯著」的翻轉在任何一種讀法下都不成立。
    97	
    98	## 結果：逐項前後對照
    99	
   100	每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
   101	而中位數與勝率在底下已經移位。
   102	
   103	兩欄使用**相同口徑**，所以差異可歸因於日期本身，不是口徑改動。
   104	
   105	| 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
   106	|---|---|---|---|
   107	| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
   108	| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.108× (p=0.112, NS) | 數值微調 |
   109	| ↳ 中位數比 / 勝率 | 1.190× / 0.555 | 1.192× / 0.561 | 數值微調 |
   110	| 週五 NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0409, **顯著**, n=239) | 1.189× (p=0.0209, **仍顯著**, n=237) | 數值微調 |
   111	| ↳ 中位數比 / 勝率 | 1.198× / 0.557 | 1.219× / 0.570 | 數值微調 |
   112	| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
   113	| ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
   114	| 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
   115	| ↳ Spearman | 0.377 | 0.346 | 數值微調 |
   116	| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
   117	
   118	**6 項受稽核宣稱中，0 項結論翻轉。**
   119	
   120	**方向性主結論不變**：決定 NFP 日波動的是**進場當下的 VIX 體制**（2.03 倍、p≈4.6e-9），
   121	遠大於 NFP 這個日曆事件本身。
   122	
   123	### 關於「不顯著」的措辭
   124	
   125	修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
   126	Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
   127	陳述都綁定它自己的檢定：
   128	
   129	- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
   130	- Welch 平均差（**週五公布的 NFP** 對非 NFP 週五）：1.189×，p=0.0209，**拒絕**
   131	  —— 條件於週五，不是關於 NFP 一般而言
   132	- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019，**拒絕**
   133	
   134	平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
   135	排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。
   136	
   137	## 產出檔案
   138	
   139	| 檔案 | 內容 |
   140	|---|---|
   141	| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
   142	| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
   143	| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
   144	| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 換掉的日期 + 文章更正替換清單 |
   145	| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
   146	| `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
   147	| `review_verdict_v3.json` / `codex_review_v3.md` | Codex 三審裁決與全文 |
   148	
   149	## 線上文章更正（`mile_35eef830`）
   150	
   151	### ⚠️ 原 18 條更正清單已全數作廢
   152	
   153	原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
   154	改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
   155	撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
   156	`article_correction.supersedes`。
   157	
   158	### 新清單：19 條，全部是數值重述，0 條方向翻轉
   159	
   160	文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
   161	差距的是進場 VIX 體制 —— 在官方日期下**全部成立**。新清單只改數字
   162	（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
   163	外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
   164	
   165	19 條已對線上 canonical 文章驗證，全部恰好命中一次。
   166	
   167	```bash
   168	# 主線程在 repo root 執行
   169	uv run python experiments/k528/build_article_correction.py            # 驗證（不寫任何檔）
   170	uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
   171	```
   172	
   173	**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
   174	`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
   175	自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
   176	合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。
   177	
   178	**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
   179	與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
   180	因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。
   181	
   182	## 防迴歸
   183	
   184	事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
   185	
   186	- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
   187	  212 個日期共通、結果檔宣告 fail-closed
   188	- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住 v2 BLOCKER**：
   189	  對 artifact 斷言六個 off-cycle 日期不在事件集合、六個正式發布日在。對 artifact 而非
   190	  只對 accessor 斷言，因為「accessor 是對的」不能證明「出貨的結果用了它」
   191	- `TestControlGroupHasNoNfpDays` — 釘住控制組不含任何已映射 NFP session
   192	- `TestCalendarFailClosedCannotBeBypassed` — 逐條釘住三審找到的繞過路徑：較早的
   193	  off-cycle、選擇非最早、跨度內缺月、allowlist 濫用；外加一個**必須通過**的乾淨日曆
   194	  （只會拒絕的 guard 和永不拒絕的一樣沒用）
   195	- `TestFridayEstimandIsScopedHonestly` — 釘住 conditional estimand 有標示、
   196	  非中性排除有揭露、排除筆數與 weekday 分解一致（結果檔曾經散文寫 11、資料寫 16）
   197	- `TestProxyMutationIsCaught` — mutation test：proxy 日曆餵給 guard 必須被拒；
   198	  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆
   199	
   200	accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
   201	`tests/test_event_dates_real_raw_response.py`（未經編輯的 ALFRED 日期清單 + mutation 檢查）。
   202	後者的 scope 有明寫：它釘的是 `_fetch` 的**回傳值**（原樣、未去重），不是完整 HTTP
   203	response body，所以 `_fetch` 自身的 schema 破壞不在覆蓋範圍內。
   204	
   205	Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
   206	由綠轉紅（`2006-05-08 != 2006-05-05`），還原後 99 passed。沒被實際觸發過的 gate 不算 gate。
   207	
   208	## 主腳本的 fail-closed 面
   209	
   210	**日曆完整性**（`check_calendar_is_complete`）**同時驗證 raw feed 與 accessor 的選擇**。
   211	只驗證 accessor 的**輸出**是行不通的：accessor 在把資料交出來之前就已經把每個月收斂成一個
   212	日期，等到能檢查輸出的時候，同月歧義早就被（可能錯誤地）默默解決掉了。四道關卡：
   213	
   214	1. 同月兩筆間隔 < 3 天 → raise（修訂是報告後**數週**才報，不是數天；這種形狀代表 feed
   215	   變了或 release id 開始夾帶別的東西，拒絕猜測）
   216	2. 選到的不是該月最早一筆 → raise（這正是 v2 BLOCKER 的形狀）
   217	3. 觀測跨度內缺月 → raise。錨定在**實際觀測跨度**而非 `[start, end]`，移除了舊版
   218	   「首尾月無條件豁免」的漏洞（完整的首月照樣可以無聲消失）
   219	4. `KNOWN_MISSING_MONTHS` 宣稱的缺口，會回頭去 raw feed **驗證它真的是缺口** → 有資料就
   220	   raise。沒有這一關，allowlist 就只是「讓失敗的檢查通過」的另一個名字
   221	
   222	已知的真實缺口只有 2025-10（政府關門），每筆都要附理由字串。
   223	
   224	**事件日→交易日對映**：一對一完整性斷言。樣本內發布日找不到三日內交易日 → raise；
   225	兩個發布日映射到同一個 session → raise（原本的 `set()` 去重會把這件事藏起來並靜默減少
   226	事件數）。窗口邊界排除改為明確記錄在 `sample.event_mapping_audit`，不再靜默 `continue`。
   227	
   228	**控制組不含任何 NFP session**：對照組排除**全部 254 個**已映射 NFP session，不只是通過
   229	事件窗篩選的 253 個。因窗口不足被排除的 `2005-01-07` 仍然是真實的 NFP 日，把它留在對照組
   230	就是本實驗存在的理由（「把真的事件日丟進對照組」）的 1/253 版本。三審 Codex 與本輪自查
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
    30	The event group is a weekday mixture while the control group is pure Friday, so
    31	the Friday effect leaks into the estimate. The corrected test restricts the
    32	event group to the 237 Friday releases.
    33	
    34	Note against the tempting story: this defect was NOT introduced by the date
    35	correction. The proxy CALENDAR was all-Friday by construction, but mapping
    36	holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
    37	(239/254 = 94.1% Friday, against 237/253 = 93.7% now). The old spec was already
    38	comparing a mixed group against a pure-Friday control; correcting the dates is
    39	what made it visible, not what caused it.
    40	
    41	Two consequences the article text must respect:
    42	  1. The test now identifies the effect of an NFP release ON A FRIDAY. Prose
    43	     quoting it says "在週五公布的 NFP", not "NFP".
    44	  2. The restriction is not a neutral deletion — the excluded events are 16.3%
    45	     quieter, so restricting RAISES the ratio (1.177x -> 1.189x). Both numbers
    46	     are disclosed in the correction note rather than only the flattering one.
    47	
    48	WHY THIS SCRIPT DOES NOT WRITE BY DEFAULT
    49	-----------------------------------------
    50	`storage/reports/feed.json` is shared canonical state. `.claude/rules/worktree.md`
    51	forbids a worktree agent from touching it, and the reason is mechanical rather
    52	than ceremonial: this worktree carries its own 15MB checkout of feed.json, so a
    53	write here lands on a branch copy that is already stale the moment any other
    54	article is published, and merging it would silently revert them.
    55	
    56	So the split is: this script (run from the worktree) resolves and VALIDATES
    57	every replacement against the canonical article, proving each matches exactly
    58	once before anything is written. The main thread then runs it with --apply from
    59	the repo root, where the write is legitimate.
    60	
    61	    uv run python experiments/k528/build_article_correction.py            # validate, writes nothing
    62	    uv run python experiments/k528/build_article_correction.py --apply    # write + sync
    63	
    64	Validation uses `article_correction._splice`, the same resolver the writer
    65	uses, so a plan that validates here cannot fail differently there.
    66	"""
    67	
    68	from __future__ import annotations
    69	
    70	import argparse
    71	import json
    72	import os
    73	import tempfile
    74	from pathlib import Path
    75	
    76	REPO_ROOT = Path(__file__).resolve().parents[2]
    77	ARTICLE_ID = "mile_35eef830"
    78	AUDIT_PATH = Path(__file__).parent / "k528_nfp_official_dates_results.json"
    79	
    80	# The 18-item list built on 2026-07-19 against the contaminated rerun. Kept as a
    81	# record of what must NOT be applied, not as a fallback -- see the module
    82	# docstring. Anything that resurrects these strings is reintroducing a
    83	# retraction of a correct finding.
    84	VOIDED_20260719_LIST_SIZE = 18
    85	
    86	# (old, new). Each `old` must occur exactly once in the article body; the
    87	# resolver rejects the whole batch otherwise. Ordered as they appear.
    88	REPLACEMENTS: list[tuple[str, str]] = [
    89	    # --- sample size: 254 -> 253 ---
    90	    (
    91	        "總共 254 次 NFP 公布日的資料算過一遍",
    92	        "總共 253 次 NFP 公布日的資料算過一遍",
    93	    ),
    94	    # --- 1.10x -> 1.11x vs all non-NFP days (direction unchanged: NOT significant) ---
    95	    (
    96	        "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
    97	        "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
    98	    ),
    99	    (
   100	        "換句話說，這 1.10 倍的差距",
   101	        "換句話說，這 1.11 倍的差距",
   102	    ),
   103	    # --- Friday baseline: 1.17x -> 1.19x, STILL significant; estimand made explicit ---
   104	    (
   105	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，"
   106	        "用 Welch t 檢定算下來，這個差距達到顯著水準。"
   107	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   108	        "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。253 場 NFP 裡有 237 場落在週五、"
   109	        "16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致："
   110	        "這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.021）。"
   111	        "要注意這個數字講的是「**在週五公布的** NFP」，不是 NFP 一般而言；被排掉的那 16 場本身比較平靜，"
   112	        "所以限定週五會把倍數墊高一些（不限定的話是 1.18 倍）。"
   113	        "（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   114	    ),
   115	    (
   116	        "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；"
   117	        "但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
   118	        "所以精確的講法是：在週五公布的 NFP 確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；"
   119	        "但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
   120	    ),
   121	    # --- regime split: threshold, group sizes, means, ratio ---
   122	    (
   123	        "那 254 次 NFP 日裡",
   124	        "那 253 次 NFP 日裡",
   125	    ),
   126	    (
   127	        "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
   128	        "分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；"
   129	        "VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
   130	        "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，"
   131	        "分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；"
   132	        "VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
   133	    ),
   134	    # --- VIX correlation ---
   135	    (
   136	        "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
   137	        "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
   138	    ),
   139	    (
   140	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
   141	        "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
   142	    ),
   143	    # --- figure caption ---
   144	    (
   145	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
   146	        "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
   147	    ),
   148	    # --- the worked example: 2026-07-01 VIX 16.59 vs the threshold (still low regime) ---
   149	    (
   150	        "貼在歷史分界線 16.71 的下緣",
   151	        "貼在歷史分界線 16.69 的下緣",
   152	    ),
   153	    (
   154	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
   155	        "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
   156	    ),
   157	    (
   158	        "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
   159	        "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
   160	    ),
   161	    # --- conclusions section (direction unchanged on both baselines) ---
   162	    (
   163	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，"
   164	        "對週五基準是 1.17 倍、達到顯著水準。",
   165	        "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準；"
   166	        "若只看在週五公布的那 237 場、拿非 NFP 的週五當基準，是 1.19 倍、達到顯著水準。",
   167	    ),
   168	    (
   169	        "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
   170	        "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
   171	    ),
   172	    (
   173	        "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
   174	        "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
   175	    ),
   176	    (
   177	        "254 場歷史樣本加上 7/2 這場實測",
   178	        "253 場歷史樣本加上 7/2 這場實測",
   179	    ),
   180	    # --- methodology section + reader-facing errata ---
   181	    (
   182	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，"
   183	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
   184	        "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，"
   185	        "NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），"
   186	        "資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n"
   187	        "**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。"
   188	        "與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，"
   189	        "遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，"
   190	        "但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n"
   191	        "**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、"
   192	        "真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整"
   193	        "（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。\n\n"
   194	        "另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，"
   195	        "兩邊不對等。現改為只取在週五公布的 237 場，維持兩邊星期別一致，"
   196	        "所以該數字講的是「在週五公布的 NFP」而非 NFP 一般而言。"
   197	        "被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），"
   198	        "兩個數字都列出以免只揭露比較好看的那個。\n\n"
   199	        "**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。"
   200	        "逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
   201	    ),
   202	    (
   203	        "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
   204	        "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
   205	    ),
   206	]
   207	
   208	
   209	def load_article_content(storage_dir: Path) -> str:
   210	    feed = json.loads((storage_dir / "reports" / "feed.json").read_text(encoding="utf-8"))
   211	    art = next((a for a in feed if isinstance(a, dict) and a.get("id") == ARTICLE_ID), None)
   212	    if art is None:
   213	        raise KeyError(f"{ARTICLE_ID} not found in {storage_dir}/reports/feed.json")
   214	    return art.get("content") or ""
   215	
   216	
   217	def validate(storage_dir: Path) -> list[dict]:
   218	    """Resolve every replacement against the live article. Raises if any does
   219	    not match exactly once, before a single byte is written."""
   220	    from volpred.publisher.article_correction import _splice
   221	
   222	    content = load_article_content(storage_dir)
   223	    spans = _splice(content, REPLACEMENTS)
   224	    return [
   225	        {"index": i, "hits": 1, "from": s["from"], "to": s["to"], "offset": s["start"]}
   226	        for i, s in enumerate(sorted(spans, key=lambda x: x["start"]))
   227	    ]
   228	
   229	
   230	def _write_json_atomic(path: Path, payload) -> None:
   231	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
   232	    try:
   233	        with os.fdopen(fd, "w", encoding="utf-8") as f:
   234	            json.dump(payload, f, indent=2, ensure_ascii=False)
   235	            f.write("\n")
   236	            f.flush()
   237	            os.fsync(f.fileno())
   238	        os.replace(tmp, path)
   239	    except BaseException:
   240	        try:
   241	            os.unlink(tmp)
   242	        except FileNotFoundError:
   243	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
   244	        raise
   245	
   246	
   247	def record_plan(validated: list[dict], applied: dict | None) -> None:
   248	    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
   249	    audit["article_correction"] = {
   250	        "article_id": ARTICLE_ID,
   251	        "status": "applied" if applied else "validated_not_applied",
   252	        "n_replacements": len(REPLACEMENTS),
   253	        "all_matched_exactly_once": True,
   254	        "supersedes": {
   255	            "voided_list_size": VOIDED_20260719_LIST_SIZE,
   256	            "voided_at": "2026-07-19",
   257	            "reason": (
   258	                "the 18-item list was built against a rerun whose accessor picked "
   259	                "off-cycle ALFRED entries for six months, which pushed the "
   260	                "NFP-vs-Friday test across the 5% line. It would have retracted a "
   261	                "finding that is in fact correct."
   262	            ),
   263	        },
   264	        "directional_claims_changed": 0,
   265	        "replacements": [{"from": v["from"], "to": v["to"], "hits": v["hits"]} for v in validated],
   266	        "apply_result": applied,
   267	        "residual_gap": (
   268	            "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) "
   269	            "and the two lazypack images still render proxy-era numbers. Text and images "
   270	            "now disagree; the article carries a visible note saying so. Regenerating and "
   271	            "re-uploading them is follow-up work outside this worktree's scope."
   272	        ),
   273	    }
   274	    _write_json_atomic(AUDIT_PATH, audit)
   275	
   276	
   277	def main() -> int:
   278	    ap = argparse.ArgumentParser(description=__doc__)
   279	    ap.add_argument("--apply", action="store_true",
   280	                    help="write the correction (main thread, repo root only)")
   281	    ap.add_argument("--record-plan", action="store_true",
   282	                    help="record the validated plan into the audit JSON without applying it")
   283	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
   284	    args = ap.parse_args()
   285	
   286	    storage_dir = Path(args.storage_dir)
   287	    validated = validate(storage_dir)
   288	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   289	    for v in validated:
   290	        head = v["from"].splitlines()[0][:64]
   291	        print(f"  @{v['offset']:>6}  {head}...")
   292	
   293	    applied = None
   294	    if args.apply:
   295	        from volpred.publisher.article_correction import apply_article_correction
   296	
   297	        applied = apply_article_correction(
   298	            ARTICLE_ID,
   299	            content_replacements=REPLACEMENTS,
   300	            summary=(

exec
/bin/zsh -lc "python -c 'import json,subprocess,collections; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; load=lambda p: json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",f\"2abb3f68c:{p}\"])); f=load(\"tests/fixtures/fred_release_50_nfp_raw_20260719.json\"); raw=f[\"release_dates\"]; print(\"fixture raw\",len(raw),\"months\",len(set(x[:7] for x in raw)),\"range\",raw[0],raw[-1]); print(collections.Counter(x[:7] for x in raw).most_common(10)); x=load(\"experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json\"); c=collections.Counter(e[\"weekday\"] for e in x[\"event_data\"]); print(\"proxy weekday\",c,\"n\",len(x[\"event_data\"]),\"range\",x[\"event_data\"][0][\"date\"],x[\"event_data\"][-1][\"date\"]); y=load(\"experiments/k528/k528_nfp_event_study_results.json\"); print(\"official weekday\",collections.Counter(e[\"weekday\"] for e in y[\"event_data\"])); print(\"event mean\",sum(e[\"event_abs_return\"] for e in y[\"event_data\"])/len(y[\"event_data\"])); print(\"friday mean\",sum(e[\"event_abs_return\"] for e in y[\"event_data\"] if e[\"weekday\"]==4)/sum(e[\"weekday\"]==4 for e in y[\"event_data\"])); print(\"nonfri mean\",sum(e[\"event_abs_return\"] for e in y[\"event_data\"] if e[\"weekday\"]"'!=4)/sum(e["weekday"]!=4 for e in y["event_data"]));'"'" in /Users/yhlai0911/volpred-research
 succeeded in 104ms:
exec
/bin/zsh -lc "python -c 'import pandas as pd,json,subprocess,numpy as np; from scipy import stats; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; load=lambda p: json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",f\"2abb3f68c:{p}\"])); cur=load(\"experiments/k528/k528_nfp_event_study_results.json\"); old=load(\"experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json\"); p=\"paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv\"; d=pd.read_csv(p,parse_dates=[\"date\"]).set_index(\"date\"); d=d[(d.index>=pd.Timestamp(\"2005-01-01\"))&(d.index<pd.Timestamp(\"2026-03-27\"))].copy(); d[\"ret\"]=d.spy_adj_close.pct_change(); d=d.dropna(subset=[\"ret\"]); d[\"abs\"]=d.ret.abs(); ev=pd.DatetimeIndex([e[\"date\"] for e in cur[\"event_data\"]]); mapped=ev.append(pd.DatetimeIndex(cur[\"sample\"][\"event_mapping_audit\"][\"window_excluded_dates\"])); control=d.loc[~d.index.isin(mapped),\"abs\"]; fri=control[control.index.weekday==4]; event=np.array([e[\"event_abs_return\"] for e in cur[\"event_data\"]]); event_fri=np.array([e[\"event_abs_return\"] for e in cur[\"event_data\"] if e[\"weekday\"]==4]); print(\"snapshot rows\",len(d),\"controls\",len(control),\"fri\",len(fri)); print(\"event artifact mean\",event.mean(),\"snapshot event mean\",d.loc[ev,\"abs\"].mean(),\"maxdiff\",np.max(np.abs(event-d.loc[ev,\"abs\"].values))); print(\"current fri ratio/p artifact events vs snapshot control\",event_fri.mean()/fri.mean(),stats.ttest_ind(event_fri,fri,equal_var=False)); print(\"current mixed ratio/p\",event.mean()/fri.mean(),stats.ttest_ind(event,fri,equal_var=False)); oldev=pd.DatetimeIndex([e[\"date\"] for e in old[\"event_data\"]]); oldabs=np.array([e[\"event_abs_return\"] for e in old[\"event_data\"]]); oldfri=oldabs[oldev.weekday==4]; old_control_bad=d.loc[~d.index.isin(oldev),\"abs\"]; old_fri_bad=old_control_bad[old_control_bad.index.weekday==4]; oldmapped=oldev.append(pd.DatetimeIndex([\"2005-01-07\"])); old_control_good=d.loc[~d.index.isin(oldmapped),\"abs\"]; old_fri_good=old_control_good[old_control_good.index.weekday==4]; print(\"proxy weekday\",sum(oldev.weekday==4),sum(oldev.weekday==0)); print(\"proxy restricted BAD ratio/p/nctrl\",oldfri.mean()/old_fri_bad.mean(),stats.ttest_ind(oldfri,old_fri_bad,equal_var=False),len(old_fri_bad)); print(\"proxy restricted GOOD ratio/p/nctrl\",oldfri.mean()/old_fri_good.mean(),stats.ttest_ind(oldfri,old_fri_good,equal_var=False),len(old_fri_good)); print(\"jan7 abs\",d.loc[pd.Timestamp(\"2005-01-07\"),\"abs\"]);'" in /Users/yhlai0911/volpred-research
 succeeded in 1173ms:
snapshot rows 5340 controls 5086 fri 834
event artifact mean 0.008453056751192095 snapshot event mean 0.00845306714902815 maxdiff 1.0644831389683418e-06
current fri ratio/p artifact events vs snapshot control 1.1889933245975217 TtestResult(statistic=np.float64(2.3204958830005955), pvalue=np.float64(0.02085498438266516), df=np.float64(371.51684055920697))
current mixed ratio/p 1.1767605787539916 TtestResult(statistic=np.float64(2.2390054138734397), pvalue=np.float64(0.02569303491755321), df=np.float64(408.6598723684834))
proxy weekday 239 15
proxy restricted BAD ratio/p/nctrl 1.1678298050443163 TtestResult(statistic=np.float64(2.0513312736531963), pvalue=np.float64(0.04093755826854455), df=np.float64(370.3980212068763)) 833
proxy restricted GOOD ratio/p/nctrl 1.1667063717618518 TtestResult(statistic=np.float64(2.0391979860486593), pvalue=np.float64(0.042139201050883576), df=np.float64(370.6297675434064)) 832
jan7 abs 0.0014334508827712478

codex
目前兩個關鍵訊號已出現：

- 現行 official 組的控制排除確實修正，使用獨立 pinned SPY snapshot 可重現 237 vs 834、1.18899、p=0.02085，以及 mixed 1.17676、p=0.02569。
- 但 fail-closed 的新「乾淨日曆」測試本身用 `start=2024-01-01, end=2024-12-31` 卻只提供 1–3 月，並期待通過；這正好把「整個尾段消失」當成合法輸入。`start/end` 在完整性判定中實際未被使用。另 audit 的 proxy restricted control 仍把 2005-01-07 留在「non-NFP Friday」裡，故主 before/after 尚未真正同一個乾淨 estimand。

我會再把這兩點以可重現數值、測試 vacuity 與文章更正影響釘實。
exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short --branch
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp diff --name-only 2abb3f68c
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:tests/test_event_dates_real_raw_response.py | nl -ba | sed -n '1,150p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:tests/test_event_dates_release_selection.py | nl -ba | sed -n '1,300p'" in /Users/yhlai0911/volpred-research
 succeeded in 215ms:
## k528-nfp-official-dates
 M experiments/k528/README.md
 M experiments/k528/k528_nfp_event_study.py
 M experiments/k528/k528_nfp_event_study_results.json
 M experiments/k528/k528_nfp_official_dates_results.json
 M tests/test_nfp_official_release_dates.py
experiments/k528/README.md
experiments/k528/k528_nfp_event_study.py
experiments/k528/k528_nfp_event_study_results.json
experiments/k528/k528_nfp_official_dates_results.json
tests/test_nfp_official_release_dates.py
     1	"""Regression test against the unedited ALFRED release-date feed.
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
    12	it is real input. This module pins the unedited return value of `_fetch` for
    13	release id 50 (Employment Situation, 2005-01-01..2026-07-19, 264 entries) and
    14	asserts the six regular releases survive selection.
    15	
    16	SCOPE — what this fixture is and is not (Codex v3 finding 6): it is `_fetch`'s
    17	output, i.e. the `release_dates[].date` list exactly as the live API returned
    18	it on 2026-07-19, with nothing removed. It is NOT the full HTTP response body,
    19	so it does not cover JSON envelope changes, pagination, or field renames — a
    20	schema break in `_fetch` itself would not be caught here. What it does cover is
    21	the selection semantics downstream of `_fetch`, which is where the k528 bug was.
    22	
    23	Fixture: tests/fixtures/fred_release_50_nfp_raw_20260719.json (never de-duplicate
    24	it — the duplicate pairs ARE the regression surface).
    25	"""
    26	from __future__ import annotations
    27	
    28	import json
    29	from pathlib import Path
    30	
    31	import pytest
    32	
    33	from volpred.data import event_dates
    34	
    35	_FIXTURE = Path(__file__).parent / "fixtures" / "fred_release_50_nfp_raw_20260719.json"
    36	
    37	# The six months ALFRED returns twice for, with the regular Employment Situation
    38	# release and the off-cycle entry (annual seasonal-factor / benchmark revisions,
    39	# filed against the same release id LATER in the month). Verified against the
    40	# live API on 2026-07-19; the right-hand column is exactly what the old max()
    41	# rule picked and what k528's contaminated run treated as NFP event days.
    42	OFF_CYCLE_PAIRS = {
    43	    "2006-05": ("2006-05-05", "2006-05-08"),
    44	    "2012-12": ("2012-12-07", "2012-12-12"),
    45	    "2013-05": ("2013-05-03", "2013-05-06"),
    46	    "2020-05": ("2020-05-08", "2020-05-11"),
    47	    "2024-01": ("2024-01-05", "2024-01-10"),
    48	    "2024-08": ("2024-08-02", "2024-08-21"),
    49	}
    50	
    51	
    52	@pytest.fixture(autouse=True)
    53	def _sandbox_cache_dir(monkeypatch, tmp_path):
    54	    # No test may touch the canonical storage/data cache dir (CI repo-state guard).
    55	    monkeypatch.setattr(event_dates, "_CACHE_DIR", tmp_path)
    56	
    57	
    58	@pytest.fixture
    59	def raw_response() -> list[str]:
    60	    return json.loads(_FIXTURE.read_text())["release_dates"]
    61	
    62	
    63	@pytest.fixture
    64	def selected(monkeypatch, raw_response) -> list[str]:
    65	    monkeypatch.setattr(event_dates, "_fetch", lambda *_a, **_kw: list(raw_response))
    66	    idx = event_dates.release_dates("NFP_US", "2005-01-01", "2026-07-19", use_cache=False)
    67	    return [str(d.date()) for d in idx]
    68	
    69	
    70	def test_fixture_still_carries_the_duplicate_months(raw_response):
    71	    """Guard the guard: if someone 'cleans' the fixture, the suite goes quiet again."""
    72	    by_month: dict[str, list[str]] = {}
    73	    for d in raw_response:
    74	        by_month.setdefault(d[:7], []).append(d)
    75	    multi = {m: v for m, v in by_month.items() if len(v) > 1}
    76	    assert set(multi) == set(OFF_CYCLE_PAIRS), (
    77	        "fixture must keep exactly the six same-month duplicate pairs verbatim; "
    78	        f"got {sorted(multi)}"
    79	    )
    80	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
    81	        assert sorted(multi[month]) == [regular, off_cycle]
    82	
    83	
    84	def test_regular_release_wins_in_every_duplicate_month(selected):
    85	    for month, (regular, off_cycle) in OFF_CYCLE_PAIRS.items():
    86	        in_month = [d for d in selected if d.startswith(month)]
    87	        assert in_month == [regular], f"{month}: expected {regular}, got {in_month}"
    88	        assert off_cycle not in selected, f"{off_cycle} is an off-cycle revision, not an NFP event"
    89	
    90	
    91	def test_selection_is_one_per_month_and_complete(selected, raw_response):
    92	    months_in = {d[:7] for d in raw_response}
    93	    months_out = [d[:7] for d in selected]
    94	    assert len(months_out) == len(set(months_out)), "more than one event date in some month"
    95	    assert set(months_out) == months_in, "selection dropped or invented a month"
    96	    assert len(selected) == 258
    97	
    98	
    99	def test_max_rule_would_reproduce_the_k528_contamination(raw_response):
   100	    """Mutation check: the OLD rule must fail this file, or it proves nothing.
   101	
   102	    Without this, a future refactor could silently restore max() and the two
   103	    assertions above would be the only thing standing in the way — this pins
   104	    WHY they matter.
   105	    """
   106	    by_month: dict[str, list[str]] = {}
   107	    for d in raw_response:
   108	        by_month.setdefault(d[:7], []).append(d)
   109	    old_rule = {m: max(v) for m, v in by_month.items()}
   110	    wrong = {m: old_rule[m] for m, (regular, _) in OFF_CYCLE_PAIRS.items() if old_rule[m] != regular}
   111	    assert wrong == {m: off for m, (_, off) in OFF_CYCLE_PAIRS.items()}, (
   112	        "the old max() rule must pick exactly the six off-cycle dates on this input"
   113	    )
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

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_official_dates_results.json | nl -ba | sed -n '120,230p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study_results.json | nl -ba | sed -n '1,190p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_official_dates_results.json | nl -ba | sed -n '250,540p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
   120	      "after": {
   121	        "mean_ratio": 1.1077789172671957,
   122	        "nfp_mean": 0.008453056751192095,
   123	        "baseline_mean": 0.007630635156015721,
   124	        "p_value": 0.11206534461843846,
   125	        "significant_5pct": false,
   126	        "n": 253,
   127	        "median_ratio": 1.1915805444616765,
   128	        "win_rate": 0.5612648221343873
   129	      },
   130	      "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
   131	      "verdict": "NUMERIC_ADJUSTMENT",
   132	      "verdict_reasons": []
   133	    },
   134	    "vol_ratio_vs_friday": {
   135	      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
   136	      "before": {
   137	        "mean_ratio": 1.1678305805326317,
   138	        "p_value": 0.04093676828523356,
   139	        "significant_5pct": true,
   140	        "n": 239,
   141	        "nfp_days_on_friday": 239,
   142	        "median_ratio": 1.1982080672282966,
   143	        "win_rate": 0.5564853556485355,
   144	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   145	        "as_published_mixed_weekday": {
   146	          "mean_ratio": 1.168212716801256,
   147	          "p_value": 0.03354366521379227,
   148	          "significant_5pct": true,
   149	          "n": 254,
   150	          "note": "what the proxy run actually published: all 254 events (239 Friday, 15 Monday) against non-NFP Fridays. This is the number the article quoted, so it is kept, but it is NOT the like-for-like comparison against the corrected column."
   151	        }
   152	      },
   153	      "after": {
   154	        "mean_ratio": 1.1889943941490353,
   155	        "p_value": 0.020854393889216647,
   156	        "significant_5pct": true,
   157	        "n": 237,
   158	        "nfp_days_on_friday": 237,
   159	        "median_ratio": 1.2184396832095086,
   160	        "win_rate": 0.569620253164557,
   161	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   162	        "diagnostic_mixed_weekday": {
   163	          "mean_ratio": 1.1767616373016152,
   164	          "p_value": 0.025692303463617307,
   165	          "significant_5pct": true,
   166	          "n": 253,
   167	          "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
   168	        }
   169	      },
   170	      "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to Friday releases. Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
   171	      "verdict": "NUMERIC_ADJUSTMENT",
   172	      "verdict_reasons": []
   173	    },
   174	    "regime_ratio": {
   175	      "label": "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   176	      "before": {
   177	        "mean_ratio": 2.1670599373202153,
   178	        "high_mean": 0.011524027931522324,
   179	        "low_mean": 0.005317816887784345,
   180	        "n_high": 127,
   181	        "n_low": 127,
   182	        "p_value": 2.8361186837189765e-10,
   183	        "significant_5pct": true,
   184	        "median_ratio": 2.2653573776192792,
   185	        "win_rate": 0.7165354330708661
   186	      },
   187	      "after": {
   188	        "mean_ratio": 2.027288651305541,
   189	        "high_mean": 0.011276167463886846,
   190	        "low_mean": 0.005562191381392668,
   191	        "n_high": 128,
   192	        "n_low": 125,
   193	        "p_value": 4.5527707460242615e-09,
   194	        "significant_5pct": true,
   195	        "median_ratio": 2.0733601176414456,
   196	        "win_rate": 0.6953125
   197	      },
   198	      "note": "",
   199	      "verdict": "NUMERIC_ADJUSTMENT",
   200	      "verdict_reasons": []
   201	    },
   202	    "vix_correlation": {
   203	      "label": "Pre-event VIX vs event-day |return| (article: r=0.45)",
   204	      "before": {
   205	        "pearson_r": 0.45116558631194703,
   206	        "pearson_p": 3.854493703611817e-14,
   207	        "spearman_rho": 0.3766062270606868,
   208	        "spearman_p": 5.561878132730772e-10,
   209	        "slope_pct_per_vix_pt": 0.04387491083793095,
   210	        "n": 254,
   211	        "significant_5pct": true
   212	      },
   213	      "after": {
   214	        "pearson_r": 0.4404376134668122,
   215	        "pearson_p": 1.9813695215037463e-13,
   216	        "spearman_rho": 0.3455048873701663,
   217	        "spearman_p": 1.6699985504624933e-08,
   218	        "slope_pct_per_vix_pt": 0.04256190841887098,
   219	        "n": 253,
   220	        "significant_5pct": true
   221	      },
   222	      "note": "",
   223	      "verdict": "NUMERIC_ADJUSTMENT",
   224	      "verdict_reasons": []
   225	    },
   226	    "vix_median_threshold": {
   227	      "label": "VIX median split (article: 16.71)",
   228	      "before": {
   229	        "threshold": 16.710000038146973,
   230	        "n": 254,
     1	{
     2	  "experiment_id": "K528",
     3	  "title": "NFP Event Study on SPY Volatility",
     4	  "date": "2026-07-19T08:36:00.092793+00:00",
     5	  "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
     6	  "event_date_source": {
     7	    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
     8	    "accessor": "volpred.data.event_dates.nfp_release_dates",
     9	    "fallback": "none - the run raises if the calendar is unreachable",
    10	    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
    11	  },
    12	  "sample": {
    13	    "total_nfp_events": 253,
    14	    "date_range": "2005-02-04 to 2026-03-06",
    15	    "non_nfp_trading_days": 5086,
    16	    "friday_baseline_days": 834,
    17	    "nfp_days_on_friday": 237,
    18	    "event_mapping_audit": {
    19	      "n_official_releases": 254,
    20	      "n_mapped_to_sessions": 254,
    21	      "n_shifted_to_next_session": 6,
    22	      "n_outside_price_sample": 0,
    23	      "outside_price_sample_dates": [],
    24	      "n_excluded_for_window_buffer": 1,
    25	      "window_excluded_dates": [
    26	        "2005-01-07"
    27	      ],
    28	      "n_valid_events": 253
    29	    },
    30	    "calendar_completeness": {
    31	      "n_months_in_span": 255,
    32	      "n_raw_entries": 260,
    33	      "months_with_multiple_raw_entries": [
    34	        "2006-05",
    35	        "2012-12",
    36	        "2013-05",
    37	        "2020-05",
    38	        "2024-01",
    39	        "2024-08"
    40	      ],
    41	      "known_missing_months": {
    42	        "2025-10": "Federal government shutdown. ALFRED shows no release id 50 entry between 2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed September report landed on 11-20. Same shutdown that cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py. The first-Friday proxy INVENTED an event here -- that phantom is one of the reasons for this rerun."
    43	      },
    44	      "ambiguity_gap_threshold_days": 3
    45	    }
    46	  },
    47	  "main_results": {
    48	    "nfp_avg_abs_return": 0.008453056751192095,
    49	    "nfp_avg_abs_return_pct": "0.845%",
    50	    "non_nfp_avg_abs_return": 0.007630635156015721,
    51	    "non_nfp_avg_abs_return_pct": "0.763%",
    52	    "friday_baseline_abs_return": 0.007183321144437934,
    53	    "vol_ratio_vs_all": 1.1077789172671957,
    54	    "vol_ratio_vs_friday": 1.1889943941490353
    55	  },
    56	  "statistical_tests": {
    57	    "A_nfp_vs_all": {
    58	      "test": "Welch t-test",
    59	      "t_stat": 1.5938698340236177,
    60	      "p_value": 0.11206534461843846,
    61	      "significant_5pct": false
    62	    },
    63	    "B_nfp_vs_friday": {
    64	      "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
    65	      "estimand": "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event group is restricted to NFP releases that trade on a Friday, and the 16 non-Friday events are excluded rather than compared against a pure-Friday control group.",
    66	      "claim_scope": "This identifies the effect of an NFP release ON A FRIDAY. It does not license a statement about NFP releases in general -- the excluded non-Friday events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec. Any prose quoting this number must say 'Friday NFP', not 'NFP'.",
    67	      "restriction_is_not_neutral": {
    68	        "excluded_mean_abs_return": 0.007151455403861362,
    69	        "friday_mean_abs_return": 0.008540928572108936,
    70	        "excluded_are_quieter_by_pct": 16.268408715944616
    71	      },
    72	      "n_event": 237,
    73	      "n_control": 834,
    74	      "vol_ratio": 1.1889943941490353,
    75	      "t_stat": 2.320506683032578,
    76	      "p_value": 0.020854393889216647,
    77	      "significant_5pct": true,
    78	      "excluded_non_friday_events": {
    79	        "n": 16,
    80	        "mean_abs_return": 0.007151455403861362
    81	      }
    82	    },
    83	    "B_diagnostic_mixed_weekday": {
    84	      "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
    85	      "status": "DIAGNOSTIC ONLY - do not quote",
    86	      "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
    87	      "vol_ratio": 1.1767616373016152,
    88	      "t_stat": 2.2390165569579286,
    89	      "p_value": 0.025692303463617307,
    90	      "significant_5pct": true
    91	    },
    92	    "C_wilcoxon": {
    93	      "test": "Mann-Whitney U (one-sided)",
    94	      "u_stat": 712484.0,
    95	      "p_value": 0.001939290371011189,
    96	      "significant_5pct": true
    97	    },
    98	    "D_vol_crush": {
    99	      "test": "One-sample t-test (post-pre diff)",
   100	      "pre_avg": 0.007787012898562973,
   101	      "post_avg": 0.007687344759629084,
   102	      "diff": -9.966813893388814e-05,
   103	      "t_stat": -0.31069347719530527,
   104	      "p_value": 0.7562904817800591,
   105	      "vol_crush_present": false
   106	    },
   107	    "E_vix_predictive": {
   108	      "test": "Pearson + Spearman correlation",
   109	      "pearson_r": 0.4404376134668122,
   110	      "pearson_p": 1.9813695215037463e-13,
   111	      "spearman_rho": 0.3455048873701663,
   112	      "spearman_p": 1.6699985504624933e-08,
   113	      "slope": 0.00042561908418870984,
   114	      "interpretation": "1pt VIX \u2192 0.0426% more |return|"
   115	    },
   116	    "F_vix_buildup": {
   117	      "test": "One-sample t-test (T-5 to T-1 VIX change)",
   118	      "mean_change": 0.08312253989721004,
   119	      "t_stat": 0.44978438962865197,
   120	      "p_value": 0.653252559944604,
   121	      "anticipatory_buildup": false
   122	    }
   123	  },
   124	  "seasonal_analysis": {
   125	    "1": {
   126	      "n": 21,
   127	      "mean_abs_return": 0.009459230168352569,
   128	      "vol_ratio": 1.2396386375379576,
   129	      "t_stat": 0.9409165625722887,
   130	      "p_val": 0.35797441694582693
   131	    },
   132	    "2": {
   133	      "n": 22,
   134	      "mean_abs_return": 0.00903075762176682,
   135	      "vol_ratio": 1.1834870147929026,
   136	      "t_stat": 0.8868882443179639,
   137	      "p_val": 0.3851836720495548
   138	    },
   139	    "3": {
   140	      "n": 22,
   141	      "mean_abs_return": 0.00850216957534808,
   142	      "vol_ratio": 1.1142151867456633,
   143	      "t_stat": 0.7026646629357496,
   144	      "p_val": 0.4899813531810133
   145	    },
   146	    "4": {
   147	      "n": 21,
   148	      "mean_abs_return": 0.010016764369971544,
   149	      "vol_ratio": 1.3127038791881804,
   150	      "t_stat": 0.8837006477100114,
   151	      "p_val": 0.38735755919352954
   152	    },
   153	    "5": {
   154	      "n": 21,
   155	      "mean_abs_return": 0.00990151655446461,
   156	      "vol_ratio": 1.297600573480257,
   157	      "t_stat": 1.7028502040036422,
   158	      "p_val": 0.10408797451259022
   159	    },
   160	    "6": {
   161	      "n": 21,
   162	      "mean_abs_return": 0.0112836593639662,
   163	      "vol_ratio": 1.4787313419211985,
   164	      "t_stat": 1.635471734177157,
   165	      "p_val": 0.11759165773012344
   166	    },
   167	    "7": {
   168	      "n": 21,
   169	      "mean_abs_return": 0.007204800057920193,
   170	      "vol_ratio": 0.944194016698621,
   171	      "t_stat": -0.3308069022883639,
   172	      "p_val": 0.7442309995287174
   173	    },
   174	    "8": {
   175	      "n": 21,
   176	      "mean_abs_return": 0.007149200610417382,
   177	      "vol_ratio": 0.9369076707567661,
   178	      "t_stat": -0.3039566760489702,
   179	      "p_val": 0.7643006585410423
   180	    },
   181	    "9": {
   182	      "n": 21,
   183	      "mean_abs_return": 0.007168471273703178,
   184	      "vol_ratio": 0.9394331044712327,
   185	      "t_stat": -0.30814348665813557,
   186	      "p_val": 0.7611594983717854
   187	    },
   188	    "10": {
   189	      "n": 20,
   190	      "mean_abs_return": 0.008136053675706656,
   250	        "n": 253,
   251	        "date_range": "2005-02-04 to 2026-03-06",
   252	        "non_nfp_trading_days": 5086,
   253	        "dates_in_common": 212,
   254	        "proxy_only_dates": [
   255	          "2005-07-01",
   256	          "2006-03-03",
   257	          "2006-12-01",
   258	          "2007-03-02",
   259	          "2008-07-07",
   260	          "2009-01-02",
   261	          "2009-05-01",
   262	          "2009-07-06",
   263	          "2010-01-04",
   264	          "2010-10-01",
   265	          "2011-07-01",
   266	          "2012-03-02",
   267	          "2013-03-01",
   268	          "2013-10-04",
   269	          "2013-11-01",
   270	          "2014-01-03",
   271	          "2014-07-07",
   272	          "2015-01-02",
   273	          "2015-05-01",
   274	          "2015-07-06",
   275	          "2016-01-04",
   276	          "2016-07-01",
   277	          "2017-03-03",
   278	          "2017-12-01",
   279	          "2018-03-02",
   280	          "2019-03-01",
   281	          "2020-01-03",
   282	          "2020-05-01",
   283	          "2020-07-06",
   284	          "2021-01-04",
   285	          "2021-10-01",
   286	          "2022-07-01",
   287	          "2023-03-03",
   288	          "2023-12-01",
   289	          "2024-03-01",
   290	          "2025-01-03",
   291	          "2025-07-07",
   292	          "2025-10-03",
   293	          "2025-11-07",
   294	          "2025-12-05",
   295	          "2026-01-02",
   296	          "2026-02-06"
   297	        ],
   298	        "official_only_dates": [
   299	          "2005-07-08",
   300	          "2006-03-10",
   301	          "2006-12-08",
   302	          "2007-03-09",
   303	          "2008-07-03",
   304	          "2009-01-09",
   305	          "2009-05-08",
   306	          "2009-07-02",
   307	          "2010-01-08",
   308	          "2010-10-08",
   309	          "2011-07-08",
   310	          "2012-03-09",
   311	          "2013-03-08",
   312	          "2013-10-22",
   313	          "2013-11-08",
   314	          "2014-01-10",
   315	          "2014-07-03",
   316	          "2015-01-09",
   317	          "2015-05-08",
   318	          "2015-07-02",
   319	          "2016-01-08",
   320	          "2016-07-08",
   321	          "2017-03-10",
   322	          "2017-12-08",
   323	          "2018-03-09",
   324	          "2019-03-08",
   325	          "2020-01-10",
   326	          "2020-05-08",
   327	          "2020-07-02",
   328	          "2021-01-08",
   329	          "2021-10-08",
   330	          "2022-07-08",
   331	          "2023-03-10",
   332	          "2023-12-08",
   333	          "2024-03-08",
   334	          "2025-01-10",
   335	          "2025-07-03",
   336	          "2025-11-20",
   337	          "2025-12-16",
   338	          "2026-01-09",
   339	          "2026-02-11"
   340	        ]
   341	      },
   342	      "note": "Equal counts do not mean equal samples -- check dates_in_common.",
   343	      "verdict": "NUMERIC_ADJUSTMENT",
   344	      "verdict_reasons": []
   345	    }
   346	  },
   347	  "n_claims_flipped": 0,
   348	  "n_claims_audited": 6,
   349	  "article_correction": {
   350	    "article_id": "mile_35eef830",
   351	    "status": "validated_not_applied",
   352	    "n_replacements": 19,
   353	    "all_matched_exactly_once": true,
   354	    "supersedes": {
   355	      "voided_list_size": 18,
   356	      "voided_at": "2026-07-19",
   357	      "reason": "the 18-item list was built against a rerun whose accessor picked off-cycle ALFRED entries for six months, which pushed the NFP-vs-Friday test across the 5% line. It would have retracted a finding that is in fact correct."
   358	    },
   359	    "directional_claims_changed": 0,
   360	    "replacements": [
   361	      {
   362	        "from": "總共 254 次 NFP 公布日的資料算過一遍",
   363	        "to": "總共 253 次 NFP 公布日的資料算過一遍",
   364	        "hits": 1
   365	      },
   366	      {
   367	        "from": "NFP 當日 SPY 的平均絕對日報酬是 0.842%，非 NFP 交易日是 0.763%，兩者相除是 1.10 倍。",
   368	        "to": "NFP 當日 SPY 的平均絕對日報酬是 0.845%，非 NFP 交易日是 0.763%，兩者相除是 1.11 倍。",
   369	        "hits": 1
   370	      },
   371	      {
   372	        "from": "換句話說，這 1.10 倍的差距",
   373	        "to": "換句話說，這 1.11 倍的差距",
   374	        "hits": 1
   375	      },
   376	      {
   377	        "from": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準：NFP 當日波動是這個基準的 1.17 倍，用 Welch t 檢定算下來，這個差距達到顯著水準。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   378	        "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.021）。要注意這個數字講的是「**在週五公布的** NFP」，不是 NFP 一般而言；被排掉的那 16 場本身比較平靜，所以限定週五會把倍數墊高一些（不限定的話是 1.18 倍）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
   379	        "hits": 1
   380	      },
   381	      {
   382	        "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
   383	        "to": "所以精確的講法是：在週五公布的 NFP 確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
   384	        "hits": 1
   385	      },
   386	      {
   387	        "from": "那 254 次 NFP 日裡",
   388	        "to": "那 253 次 NFP 日裡",
   389	        "hits": 1
   390	      },
   391	      {
   392	        "from": "VolPred 把這 254 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.71。VIX 高於中位數的 127 次 NFP，SPY 當日平均絕對報酬是 1.15%；VIX 低於中位數的 127 次，只有 0.53%。兩者相差 2.17 倍",
   393	        "to": "VolPred 把這 253 個 NFP 交易日，按公布前一個交易日收盤的 VIX 水準切成兩半，分界點是歷史中位數 16.69。VIX 高於中位數的 128 次 NFP，SPY 當日平均絕對報酬是 1.13%；VIX 低於中位數的 125 次，只有 0.56%。兩者相差 2.03 倍",
   394	        "hits": 1
   395	      },
   396	      {
   397	        "from": "相關係數落在 0.45 左右（換另一種排序算法也給出一致的 0.38）",
   398	        "to": "相關係數落在 0.44 左右（換另一種排序算法也給出一致的 0.35）",
   399	        "hits": 1
   400	      },
   401	      {
   402	        "from": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.044 個百分點。",
   403	        "to": "VIX 每高 1 點，就業日的預期絕對報酬就多墊高約 0.043 個百分點。",
   404	        "hits": 1
   405	      },
   406	      {
   407	        "from": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.17 倍）]",
   408	        "to": "![圖1：VIX 高低體制下的 NFP 日波動差距（2.03 倍）]",
   409	        "hits": 1
   410	      },
   411	      {
   412	        "from": "貼在歷史分界線 16.71 的下緣",
   413	        "to": "貼在歷史分界線 16.69 的下緣",
   414	        "hits": 1
   415	      },
   416	      {
   417	        "from": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.53%，而不是高體制的 1.15%。",
   418	        "to": "落在低體制的 NFP，當日絕對報酬的 base case 約 0.56%，而不是高體制的 1.13%。",
   419	        "hits": 1
   420	      },
   421	      {
   422	        "from": "7/1 收盤的 16.59 距離 16.71 只差 0.12 點",
   423	        "to": "7/1 收盤的 16.59 距離 16.69 只差 0.10 點",
   424	        "hits": 1
   425	      },
   426	      {
   427	        "from": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.10 倍、未達顯著水準，對週五基準是 1.17 倍、達到顯著水準。",
   428	        "to": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準；若只看在週五公布的那 237 場、拿非 NFP 的週五當基準，是 1.19 倍、達到顯著水準。",
   429	        "hits": 1
   430	      },
   431	      {
   432	        "from": "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
   433	        "to": "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
   434	        "hits": 1
   435	      },
   436	      {
   437	        "from": "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
   438	        "to": "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
   439	        "hits": 1
   440	      },
   441	      {
   442	        "from": "254 場歷史樣本加上 7/2 這場實測",
   443	        "to": "253 場歷史樣本加上 7/2 這場實測",
   444	        "hits": 1
   445	      },
   446	      {
   447	        "from": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
   448	        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。\n\n另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，兩邊不對等。現改為只取在週五公布的 237 場，維持兩邊星期別一致，所以該數字講的是「在週五公布的 NFP」而非 NFP 一般而言。被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），兩個數字都列出以免只揭露比較好看的那個。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
   449	        "hits": 1
   450	      },
   451	      {
   452	        "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
   453	        "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
   454	        "hits": 1
   455	      }
   456	    ],
   457	    "apply_result": null,
   458	    "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
   459	  }
   460	}

exec
/bin/zsh -lc "python -c 'import json,subprocess; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; audit=json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",\"2abb3f68c:experiments/k528/k528_nfp_official_dates_results.json\"])); content=subprocess.check_output([\"jq\",\"-r\",\".[] | select(.id == \\\"mile_35eef830\\\") | .content\",\"/Users/yhlai0911/volpred-research/storage/reports/feed.json\"],text=True); reps=audit[\"article_correction\"][\"replacements\"]; print(\"article chars\",len(content),\"replacements\",len(reps)); print(\"old hit counts\",{n:sum(1 for r in reps if content.count(r[\"from\"])==n) for n in set(content.count(r[\"from\"]) for r in reps)}); print(\"new hit counts\",{n:sum(1 for r in reps if content.count(r[\"to\"])==n) for n in set(content.count(r[\"to\"]) for r in reps)}); print(\"visible_scope_preapply\", \"在週五公布的\" in content, \"16.3%\" in content, \"限定週五\" in content); print(\"bad indices\",[(i,content.count(r[\"from\"]),content.count(r[\"to\"])) for i,r in enumerate(reps) if content.count(r[\"from\"])"'!=1 or content.count(r["to"])!=0])'"'" in /Users/yhlai0911/volpred-research
 succeeded in 151ms:
article chars 3930 replacements 19
old hit counts {1: 19}
new hit counts {0: 19}
visible_scope_preapply False False False
bad indices []

exec
/bin/zsh -lc "python -c 'import json,subprocess; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; x=json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",\"2abb3f68c:experiments/k528/k528_nfp_event_study_results.json\"])); print(\"CONCLUSIONS\"); print(\"\\n\".join(x[\"conclusions\"])); print(\"PRACTICAL\",x[\"practical_implication\"]); print(\"CLAIM\",x[\"claim_scope_note\"])'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
CONCLUSIONS
Welch mean-difference, NFP vs all non-NFP days: 1.11x, p=0.1121 (does not reject at 5%)
Welch mean-difference, Friday NFP vs Friday non-NFP (CONDITIONAL ON FRIDAY, weekday held fixed): 1.19x, p=0.0209 (rejects at 5%; n=237 vs 834). Scoped to Friday releases; the 16 non-Friday events are quieter, so this is not a statement about NFP releases in general.
Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: p=0.00194 (rejects at 5%)
NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, so a rank test can detect a location shift the Welch mean test cannot. Report both; do not summarise them as a single verdict.
No significant vol crush pattern (p=0.7563)
Pre-event VIX predicts event vol (r=0.440, p=0.0000)
PRACTICAL Entry VIX regime is the dominant and most reliably measured effect here: 2.03x between high- and low-VIX NFP days (p=4.553e-09). The NFP-day effect itself is smaller and the tests do not agree on it -- the Welch mean-difference test against all non-NFP days gives 1.11x (p=0.1121) while the one-sided Mann-Whitney gives p=0.00194. Report both. A mean test that does not reject is not evidence that the effect is zero, and it does not license the claim that the event 'is not NFP itself'.
CLAIM Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6).

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import ast,subprocess,types; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; src=subprocess.check_output([\"git\",\"-C\",repo,\"show\",\"2abb3f68c:experiments/k528/k528_nfp_event_study.py\"],text=True); tree=ast.parse(src); keep=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef)) or (isinstance(n,ast.AnnAssign) and getattr(n.target,\"id\",\"\")==\"KNOWN_MISSING_MONTHS\") or (isinstance(n,ast.Assign) and getattr(n.targets[0],\"id\",\"\") in (\"SAMPLE_START\",\"SAMPLE_END\",\"AMBIGUOUS_SAME_MONTH_GAP_DAYS\"))]; mod=types.ModuleType(\"k528_helpers\"); exec(compile(ast.Module(body=keep,type_ignores=[]),\"k528\",\"exec\"),mod.__dict__); cases={\"tail_missing_even_raw_has_tail\":([\"2024-01-05\",\"2024-02-02\",\"2024-03-08\"],[\"2024-01-05\",\"2024-02-02\",\"2024-03-08\",\"2024-04-05\",\"2024-05-03\",\"2024-06-07\",\"2024-07-05\",\"2024-08-02\",\"2024-09-06\",\"2024-10-04\",\"2024-11-01\",\"2024-12-06\"]),\"exactly_3d_earlier_wrong_entry\":([\"2024-01-05\",\"2024-02-01\",\"2024-03-08\"],[\"2024-01-05\",\"2024-02-01\",\"2024-02-04\",\"2024-03-08\"]),\"selected_invents_rawless_month\":([\"2024-01-05\",\"2024-02-02\",\"2024-03-08\"],[\"2024-01-05\",\"2024-03-08\"]),\"duplicate_selected_month_reversed\":([\"2024-01-05\",\"2024-02-09\",\"2024-02-02\",\"2024-03-08\"],[\"2024-01-05\",\"2024-02-02\",\"2024-02-09\",\"2024-03-08\"])};
for name,(sel,raw) in cases.items():
 try: out=mod.check_calendar_is_complete(sel,raw,\"2024-01-01\",\"2024-12-31\"); print(name,\"ACCEPTED\",out[\"n_months_in_span\"])
 except Exception as e: print(name,\"REJECTED\",type(e).__name__,str(e)[:100])'" in /Users/yhlai0911/volpred-research
 succeeded in 1362ms:
tail_missing_even_raw_has_tail ACCEPTED 3
exactly_3d_earlier_wrong_entry ACCEPTED 3
selected_invents_rawless_month ACCEPTED 3
duplicate_selected_month_reversed ACCEPTED 3

exec
/bin/zsh -lc "PYTHONDONTWRITEBYTECODE=1 python -c 'import ast,subprocess,types,pandas as pd; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; src=subprocess.check_output([\"git\",\"-C\",repo,\"show\",\"2abb3f68c:experiments/k528/k528_nfp_event_study.py\"],text=True); tree=ast.parse(src); keep=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.FunctionDef)) or (isinstance(n,ast.AnnAssign) and getattr(n.target,\"id\",\"\")==\"KNOWN_MISSING_MONTHS\") or (isinstance(n,ast.Assign) and getattr(n.targets[0],\"id\",\"\") in (\"SAMPLE_START\",\"SAMPLE_END\",\"AMBIGUOUS_SAME_MONTH_GAP_DAYS\"))]; mod=types.ModuleType(\"k528_helpers\"); exec(compile(ast.Module(body=keep,type_ignores=[]),\"k528\",\"exec\"),mod.__dict__); sel=pd.to_datetime([\"2024-01-05\",\"2024-02-02\",\"2024-03-08\"]); raw=[\"2024-01-05\",\"2024-02-02\",\"2024-03-08\",\"2024-04-05\",\"2024-05-03\",\"2024-06-07\",\"2024-07-05\",\"2024-08-02\",\"2024-09-06\",\"2024-10-04\",\"2024-11-01\",\"2024-12-06\"]; mod.nfp_release_dates=lambda *a,**k: sel; mod._fetch=lambda *a,**k: raw; dates,audit=mod.load_nfp_dates(\"2024-01-01\",\"2024-12-31\"); print(\"production load accepted\",len(dates),\"selected; raw\",audit[\"n_raw_entries\"],\"span\",audit[\"n_months_in_span\"])'" in /Users/yhlai0911/volpred-research
 succeeded in 1099ms:
production load accepted 3 selected; raw 12 span 3

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/build_article_correction.py | nl -ba | sed -n '277,380p'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '950,1120p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
   277	def main() -> int:
   278	    ap = argparse.ArgumentParser(description=__doc__)
   279	    ap.add_argument("--apply", action="store_true",
   280	                    help="write the correction (main thread, repo root only)")
   281	    ap.add_argument("--record-plan", action="store_true",
   282	                    help="record the validated plan into the audit JSON without applying it")
   283	    ap.add_argument("--storage-dir", default=str(REPO_ROOT / "storage"))
   284	    args = ap.parse_args()
   285	
   286	    storage_dir = Path(args.storage_dir)
   287	    validated = validate(storage_dir)
   288	    print(f"validated {len(validated)}/{len(REPLACEMENTS)} replacements, each matched exactly once")
   289	    for v in validated:
   290	        head = v["from"].splitlines()[0][:64]
   291	        print(f"  @{v['offset']:>6}  {head}...")
   292	
   293	    applied = None
   294	    if args.apply:
   295	        from volpred.publisher.article_correction import apply_article_correction
   296	
   297	        applied = apply_article_correction(
   298	            ARTICLE_ID,
   299	            content_replacements=REPLACEMENTS,
   300	            summary=(
   301	                "K528 event dates corrected from a first-Friday proxy to the official BLS "
   302	                "release calendar. Sample 254 -> 253 events; headline numbers restated "
   303	                "(1.10->1.11x vs all days, 1.17->1.19x vs Friday, 2.17->2.03x regime gap, "
   304	                "r 0.45->0.44). No directional conclusion changes. The Friday comparison "
   305	                "now restricts the event group to the 237 Friday releases so weekday is "
   306	                "held fixed on both sides."
   307	            ),
   308	            action="content_correction",
   309	            storage_dir=str(storage_dir),
   310	        )
   311	        print(f"\napplied: {len(applied['content_replacements'])} replacements, "
   312	              f"synced={applied['synced']}")
   313	
   314	    # A dry run that rewrites the audit file is not a dry run (k528 Codex v2
   315	    # finding 7). Recording is opt-in and never implicit.
   316	    if args.apply or args.record_plan:
   317	        record_plan(validated, applied)
   318	        print(f"plan recorded in {AUDIT_PATH.name}")
   319	    else:
   320	        print("\ndry run -- nothing written. Re-run with --apply from the repo root, "
   321	              "or --record-plan to persist the validated plan only.")
   322	    return 0
   323	
   324	
   325	if __name__ == "__main__":
   326	    raise SystemExit(main())
   950	new_dates = {r["date"] for r in results}
   951	record(
   952	    "sample", "NFP event sample (article: 254 events)",
   953	    {
   954	        "n": proxy["sample"]["total_nfp_events"],
   955	        "date_range": proxy["sample"]["date_range"],
   956	        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
   957	    },
   958	    {
   959	        "n": int(len(df)),
   960	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
   961	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
   962	        "dates_in_common": len(proxy_dates & new_dates),
   963	        "proxy_only_dates": sorted(proxy_dates - new_dates),
   964	        "official_only_dates": sorted(new_dates - proxy_dates),
   965	    },
   966	    note="Equal counts do not mean equal samples -- check dates_in_common.",
   967	)
   968	
   969	
   970	def verdict_for(key):
   971	    """Flip test: significance change, sign change, or a >10% move in the headline."""
   972	    b, a = audit_items[key]["before"], audit_items[key]["after"]
   973	    reasons = []
   974	    if b.get("significant_5pct") is not None and a.get("significant_5pct") is not None:
   975	        if bool(b["significant_5pct"]) != bool(a["significant_5pct"]):
   976	            reasons.append(
   977	                "significance flipped "
   978	                f"({'sig' if b['significant_5pct'] else 'NS'} -> "
   979	                f"{'sig' if a['significant_5pct'] else 'NS'})"
   980	            )
   981	    # The mean is not trusted on its own: the median and the win rate are
   982	    # checked independently, because the failure mode this audit exists to
   983	    # catch is a stable mean sitting on top of a moved distribution.
   984	    for field in ("mean_ratio", "median_ratio", "pearson_r", "threshold", "n"):
   985	        if field in b and field in a and b[field] and a[field]:
   986	            rel = abs(a[field] - b[field]) / abs(b[field])
   987	            if rel > 0.10:
   988	                reasons.append(f"{field} moved {rel * 100:.1f}%")
   989	    if b.get("win_rate") and a.get("win_rate"):
   990	        if abs(a["win_rate"] - b["win_rate"]) > 0.05:
   991	            reasons.append(
   992	                f"win_rate moved {b['win_rate']:.3f} -> {a['win_rate']:.3f}"
   993	            )
   994	    if key == "vix_median_threshold" and b["places_20260701_vix_1659_in"] != a["places_20260701_vix_1659_in"]:
   995	        reasons.append("the article's worked example changes regime")
   996	    return ("CONCLUSION_FLIPPED" if reasons else "NUMERIC_ADJUSTMENT"), reasons
   997	
   998	
   999	print(f"\n  {'Claim':<46} {'Before':>12} {'After':>12}  Verdict")
  1000	for key, item in audit_items.items():
  1001	    v, reasons = verdict_for(key)
  1002	    item["verdict"], item["verdict_reasons"] = v, reasons
  1003	    headline = next((f for f in ("mean_ratio", "pearson_r", "threshold", "n")
  1004	                     if f in item["before"]), None)
  1005	    bf = item["before"].get(headline)
  1006	    af = item["after"].get(headline)
  1007	    fmt = (lambda x: f"{x:,.4f}" if isinstance(x, float) else str(x))
  1008	    print(f"  {item['label']:<46} {fmt(bf):>12} {fmt(af):>12}  {v}")
  1009	    for r in reasons:
  1010	        print(f"      - {r}")
  1011	
  1012	n_flipped = sum(1 for i in audit_items.values() if i["verdict"] == "CONCLUSION_FLIPPED")
  1013	print(f"\n  {n_flipped} of {len(audit_items)} audited claims changed materially.")
  1014	
  1015	# ============================================================
  1016	# 10. Save results
  1017	# ============================================================
  1018	print("\n[6/6] Saving results...")
  1019	
  1020	output = {
  1021	    "experiment_id": "K528",
  1022	    "title": "NFP Event Study on SPY Volatility",
  1023	    "date": datetime.now(timezone.utc).isoformat(),
  1024	    "data_source": "yfinance (SPY, ^VIX), 2005-01 to 2026-03",
  1025	    "event_date_source": {
  1026	        "source": "official BLS release calendar via ALFRED (FRED release id 50)",
  1027	        "accessor": "volpred.data.event_dates.nfp_release_dates",
  1028	        "fallback": "none - the run raises if the calendar is unreachable",
  1029	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
  1030	    },
  1031	    "sample": {
  1032	        "total_nfp_events": len(df),
  1033	        "date_range": f"{df['date'].iloc[0]} to {df['date'].iloc[-1]}",
  1034	        "non_nfp_trading_days": int(non_nfp_mask.sum()),
  1035	        "friday_baseline_days": int(friday_mask.sum()),
  1036	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
  1037	        "event_mapping_audit": mapping_audit,
  1038	        "calendar_completeness": calendar_completeness,
  1039	    },
  1040	    "main_results": {
  1041	        "nfp_avg_abs_return": float(nfp_abs_returns.mean()),
  1042	        "nfp_avg_abs_return_pct": f"{nfp_abs_returns.mean()*100:.3f}%",
  1043	        "non_nfp_avg_abs_return": baseline_abs_return,
  1044	        "non_nfp_avg_abs_return_pct": f"{baseline_abs_return*100:.3f}%",
  1045	        "friday_baseline_abs_return": friday_baseline,
  1046	        "vol_ratio_vs_all": vol_ratio_all,
  1047	        "vol_ratio_vs_friday": vol_ratio_fri,
  1048	    },
  1049	    "statistical_tests": {
  1050	        "A_nfp_vs_all": {
  1051	            "test": "Welch t-test",
  1052	            "t_stat": float(t_stat_all),
  1053	            "p_value": float(p_val_all),
  1054	            "significant_5pct": bool(p_val_all < 0.05),
  1055	        },
  1056	        "B_nfp_vs_friday": {
  1057	            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
  1058	            "estimand": (
  1059	                "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event "
  1060	                "group is restricted to NFP releases that trade on a Friday, and the "
  1061	                f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
  1062	                "than compared against a pure-Friday control group."
  1063	            ),
  1064	            "claim_scope": (
  1065	                "This identifies the effect of an NFP release ON A FRIDAY. It does not "
  1066	                "license a statement about NFP releases in general -- the excluded "
  1067	                "non-Friday events are quieter, so the restriction raises the ratio "
  1068	                "relative to the mixed-weekday spec. Any prose quoting this number must "
  1069	                "say 'Friday NFP', not 'NFP'."
  1070	            ),
  1071	            "restriction_is_not_neutral": {
  1072	                "excluded_mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
  1073	                "friday_mean_abs_return": float(nfp_friday_abs.mean()),
  1074	                "excluded_are_quieter_by_pct": (
  1075	                    float((nfp_friday_abs.mean() - nfp_nonfriday_abs.mean()) / nfp_friday_abs.mean() * 100)
  1076	                    if len(nfp_nonfriday_abs) else None
  1077	                ),
  1078	            },
  1079	            "n_event": int(len(nfp_friday_abs)),
  1080	            "n_control": int(len(friday_non_nfp_abs)),
  1081	            "vol_ratio": vol_ratio_fri,
  1082	            "t_stat": float(t_stat_fri),
  1083	            "p_value": float(p_val_fri),
  1084	            "significant_5pct": bool(p_val_fri < 0.05),
  1085	            "excluded_non_friday_events": {
  1086	                "n": int(len(nfp_nonfriday_abs)),
  1087	                "mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
  1088	            },
  1089	        },
  1090	        "B_diagnostic_mixed_weekday": {
  1091	            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
  1092	            "status": "DIAGNOSTIC ONLY - do not quote",
  1093	            "why_not_a_headline": (
  1094	                "this is the pre-correction specification: a weekday-mixed event "
  1095	                "group against a pure-Friday control group, so the p-value absorbs "
  1096	                "any Friday-vs-other-weekday volatility difference. Retained solely "
  1097	                "so the correction audit can show what the contaminated estimand was "
  1098	                "worth (k528 Codex v2 finding 5)."
  1099	            ),
  1100	            "vol_ratio": vol_ratio_fri_mixed,
  1101	            "t_stat": float(t_stat_fri_mixed),
  1102	            "p_value": float(p_val_fri_mixed),
  1103	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
  1104	        },
  1105	        "C_wilcoxon": {
  1106	            "test": "Mann-Whitney U (one-sided)",
  1107	            "u_stat": float(u_stat),
  1108	            "p_value": float(p_val_wilcox),
  1109	            "significant_5pct": bool(p_val_wilcox < 0.05),
  1110	        },
  1111	        "D_vol_crush": {
  1112	            "test": "One-sample t-test (post-pre diff)",
  1113	            "pre_avg": float(df["pre_avg_abs_return"].mean()),
  1114	            "post_avg": float(df["post_avg_abs_return"].mean()),
  1115	            "diff": float(vol_crush.mean()),
  1116	            "t_stat": float(t_crush),
  1117	            "p_value": float(p_crush),
  1118	            "vol_crush_present": bool(vol_crush.mean() < 0 and p_crush < 0.05),
  1119	        },
  1120	        "E_vix_predictive": {

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '1180,1280p'
rg -n 'seed|random|bootstrap|permutation|shift\\(|pre_vix|event_vix|write_json_atomic|os.replace|to_json|write_text' /dev/null" in /Users/yhlai0911/volpred-research
 exited 1 in 0ms:
  1180	        f"(p={p_regime:.4g}). The NFP-day effect itself is smaller and the tests do not "
  1181	        f"agree on it -- the Welch mean-difference test against all non-NFP days gives "
  1182	        f"{vol_ratio_all:.2f}x (p={p_val_all:.4f}) while the one-sided Mann-Whitney gives "
  1183	        f"p={p_val_wilcox:.5f}. Report both. A mean test that does not reject is not "
  1184	        "evidence that the effect is zero, and it does not license the claim that the "
  1185	        "event 'is not NFP itself'."
  1186	    ),
  1187	    "claim_scope_note": (
  1188	        "Every significance statement in this artifact is scoped to its own test. "
  1189	        "The superseded run summarised these as 'insignificant across all tests', "
  1190	        "which contradicted the one-sided Mann-Whitney result in the same file "
  1191	        "(k528 Codex v2 finding 6)."
  1192	    ),
  1193	    "references": [
  1194	        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
  1195	        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
  1196	        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
  1197	    ],
  1198	    "event_data": results,  # full per-event data
  1199	}
  1200	
  1201	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
  1202	write_json_atomic(out_path, output)
  1203	
  1204	print(f"  Saved to: {out_path}")
  1205	
  1206	# The correction audit is written separately: it is the artifact the article
  1207	# correction is justified against, and it must stay readable without wading
  1208	# through 254 events of per-day data.
  1209	audit_out = {
  1210	    "experiment_id": "K528",
  1211	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
  1212	    "generated_at": datetime.now(timezone.utc).isoformat(),
  1213	    "before_source": PROXY_PATH.name,
  1214	    "after_source": out_path.name,
  1215	    "event_date_source": output["event_date_source"],
  1216	    "calendar_diff": {
  1217	        "proxy_only_dates": sorted(proxy_dates - new_dates),
  1218	        "official_only_dates": sorted(new_dates - proxy_dates),
  1219	        "dates_in_common": len(proxy_dates & new_dates),
  1220	        "n_proxy": len(proxy_dates),
  1221	        "n_official": len(new_dates),
  1222	        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
  1223	    },
  1224	    "win_rate_definition": (
  1225	        "share of the sample exceeding the MEDIAN of its comparison group; "
  1226	        "0.5 under the null"
  1227	    ),
  1228	    "items": audit_items,
  1229	    "n_claims_flipped": n_flipped,
  1230	    "n_claims_audited": len(audit_items),
  1231	    "article_correction": {
  1232	        "article_id": "mile_35eef830",
  1233	        "status": "pending - filled in by the correction step",
  1234	        "replacements": None,
  1235	    },
  1236	}
  1237	audit_path = Path(__file__).parent / "k528_nfp_official_dates_results.json"
  1238	write_json_atomic(audit_path, audit_out)
  1239	print(f"  Saved to: {audit_path}")
  1240	print("\nDone!")

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp ls-tree --name-only 2abb3f68c:experiments/k528
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/README.md | nl -ba | sed -n '228,270p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
README.md
build_article_correction.py
codex_review_v2.md
codex_review_v3.md
data
k528_nfp_event_study.py
k528_nfp_event_study_results.json
k528_nfp_event_study_results_PROXY_SUPERSEDED.json
k528_nfp_official_dates_results.json
references
review_verdict.json
   228	**控制組不含任何 NFP session**：對照組排除**全部 254 個**已映射 NFP session，不只是通過
   229	事件窗篩選的 253 個。因窗口不足被排除的 `2005-01-07` 仍然是真實的 NFP 日，把它留在對照組
   230	就是本實驗存在的理由（「把真的事件日丟進對照組」）的 1/253 版本。三審 Codex 與本輪自查
   231	獨立發現同一件事。
   232	
   233	**原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`。
   234	
   235	## 參考
   236	
   237	- K1442 事件日期稽核（發現 proxy bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
   238	- `docs/error_log.md` 2026-07-12 CPI 事件研究發布日條目（同一 bug class 的前例）
   239	- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
   240	- K513：先前的 FOMC/NFP/CPI 事件研究

exec
/bin/zsh -lc "python -c 'import json,subprocess,numpy as np; from scipy import stats; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; x=json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",\"2abb3f68c:experiments/k528/k528_nfp_event_study_results.json\"])); e=x[\"event_data\"]; a=np.array([r[\"event_abs_return\"] for r in e]); v=np.array([r[\"pre_vix\"] for r in e]); med=np.median(v); hi=a[v>=med]; lo=a[v<med]; lr=np.polyfit(v,a,1)[0]; print(\"n\",len(a),\"mean_pct\",a.mean()*100,\"median_vix\",med,\"n_hi_lo\",len(hi),len(lo),\"means_pct\",hi.mean()*100,lo.mean()*100,\"ratio\",hi.mean()/lo.mean()); print(\"pearson\",stats.pearsonr(v,a),\"spearman\",stats.spearmanr(v,a),\"slope_pp\",lr*100); print(\"direction\",sum(np.array([r[\"event_return\"] for r in e])>0),sum(np.array([r[\"event_return\"] for r in e])<0));'" in /Users/yhlai0911/volpred-research
 succeeded in 591ms:
n 253 mean_pct 0.8453056751192095 median_vix 16.690000534057617 n_hi_lo 128 125 means_pct 1.1276167463886846 0.5562191381392667 ratio 2.027288651305541
pearson PearsonRResult(statistic=np.float64(0.4404376134668122), pvalue=np.float64(1.9813695215037463e-13)) spearman SignificanceResult(statistic=np.float64(0.3455048873701663), pvalue=np.float64(1.6699985504624933e-08)) slope_pp 0.04256190841887098
direction 145 108

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | rg 'random|seed|bootstrap|permutation|pre_window|pre_vix|shift\\(|write_json_atomic|os\\.replace|tempfile|VIX.*median|median\\(\\)'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
    22	wrong for ~20% of the sample and it is wrong SYSTEMATICALLY, not randomly: BLS
    51	import tempfile
    89	def write_json_atomic(path: Path, payload) -> None:
    95	    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
    98	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
   104	        os.replace(tmp, path)
   246	spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
   356	    pre_window = spy.iloc[pos-5:pos]
   365	    if len(pre_window) < 5 or len(post_window) < 5:
   368	            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
   379	        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
   381	        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
   386	        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
   389	    if row["pre_vix"] is not None and row["event_vix"] is not None:
   390	        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
   417	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   492	vix_valid = df.dropna(subset=["pre_vix"])
   495	    X_vix = vix_valid["pre_vix"].values
   531	vix_median = df["pre_vix"].median()
   532	high_vix = df[df["pre_vix"] >= vix_median]["event_abs_return"]
   533	low_vix = df[df["pre_vix"] < vix_median]["event_abs_return"]
   611	print(f"  VIX median split:     {vix_median:.1f}")
   766	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   769	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   770	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   900	        "median_ratio": float(high_vix.median() / low_vix.median()),
   929	# --- 16.71 : the VIX median that splits the regimes ---
   935	    "vix_median_threshold", "VIX median split (article: 16.71)",
   943	        "n": int(df["pre_vix"].notna().sum()),
  1202	write_json_atomic(out_path, output)
  1238	write_json_atomic(audit_path, audit_out)

已完成指定 commit 的 blob 級審查、獨立重算、production helper 攻擊與文章替換核對。現行 official 統計與讀者可見 scope 已驗收；audit 的 proxy control 仍洩漏，calendar completeness 可由多種形狀繞過，且新增控制組測試是代數恆等式。
  ✓ 讀取 handoff、commit 狀態與上一輪 FAIL findings
  ✓ 檢查修正 diff、production 程式與測試實際覆蓋路徑
  ✓ 從 commit artifacts 獨立重算控制組、統計量與日期分布
  ✓ 攻擊 calendar fail-closed 並檢查 lookahead、seed、原子寫入
  ✓ 抽查至少 8 條文章更正及 README/artifact 一致性，形成裁決
exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json | nl -ba | rg -m 4 '\"non_nfp_trading_days\"|\"event_data\"|\"date\": \"2005-02-04\"|\"total_nfp_events\"'
git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '60,90p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
    20	    "total_nfp_events": 254,
    22	    "non_nfp_trading_days": 5086,
   215	  "event_data": [
   217	      "date": "2005-02-04",
    60	
    61	from volpred.data.event_dates import RELEASE_IDS, _fetch, nfp_release_dates
    62	
    63	warnings.filterwarnings("ignore")
    64	
    65	SAMPLE_START = "2005-01-01"
    66	SAMPLE_END = "2026-03-27"
    67	
    68	# Months for which BLS published no Employment Situation report at all. Each
    69	# entry needs a documented reason, and check_calendar_is_complete VERIFIES the
    70	# claim against the raw feed before honouring it -- an allowlist that is taken
    71	# on faith is just a way to make a failing check pass, which is the failure mode
    72	# this whole experiment exists to document.
    73	KNOWN_MISSING_MONTHS: dict[str, str] = {
    74	    "2025-10": (
    75	        "Federal government shutdown. ALFRED shows no release id 50 entry between "
    76	        "2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed "
    77	        "September report landed on 11-20. Same shutdown that cancelled the Oct-2025 "
    78	        "CPI release described in volpred/data/event_dates.py. The first-Friday proxy "
    79	        "INVENTED an event here -- that phantom is one of the reasons for this rerun."
    80	    ),
    81	}
    82	
    83	# Two same-month entries closer together than this cannot be told apart as
    84	# "regular report" vs "off-cycle revision" by date order alone, so the run
    85	# refuses to guess. Revisions are filed weeks after the report, not days.
    86	AMBIGUOUS_SAME_MONTH_GAP_DAYS = 3
    87	
    88	
    89	def write_json_atomic(path: Path, payload) -> None:
    90	    """Write `payload` to `path` atomically.

exec
/bin/zsh -lc "git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show 2abb3f68c:experiments/k528/k528_nfp_event_study.py | nl -ba | sed -n '208,235p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
   208	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   209	    """Official NFP (Employment Situation) release dates.
   210	
   211	    Deliberately has no except branch. If the release calendar cannot be
   212	    reached, this run must die -- a proxy calendar produces plausible numbers
   213	    from non-events, which is worse than no numbers at all. See the CORRECTION
   214	    note in the module docstring.
   215	    """
   216	    dates = nfp_release_dates(start, end)
   217	    if len(dates) == 0:
   218	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
   219	    # Pull the unselected feed as well: the accessor collapses each month to one
   220	    # date, so the only place a same-month ambiguity is still visible is here.
   221	    raw = _fetch(RELEASE_IDS["NFP_US"], start, end)
   222	    completeness = check_calendar_is_complete(dates, raw, start, end)
   223	    return list(dates), completeness
   224	
   225	
   226	# ============================================================
   227	# 2. Download data
   228	# ============================================================
   229	print("=" * 60)
   230	print("K528: NFP Event Study on SPY Volatility")
   231	print("=" * 60)
   232	
   233	print("\n[1/6] Downloading SPY and VIX data...")
   234	spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
   235	vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)

codex
審查範圍固定為 commit `2abb3f68c`。目前 worktree 有 5 個未提交修改，以下全部以 `git show 2abb3f68c:<path>` 驗證，不納入後續修正。

1. **BLOCKER — audit 的 proxy `before` 控制組仍洩漏 `2005-01-07`，所以主 before/after 尚非同一個乾淨 estimand。**  
   `experiments/k528/k528_nfp_event_study.py:748-753` 只用 archive `event_data` 排除 proxy 事件；但 archive 第一筆是 `2005-02-04`（`k528_nfp_event_study_results_PROXY_SUPERSEDED.json:215-217`），窗口不足的 proxy NFP session `2005-01-07` 不在其中，仍被算成「non-NFP Friday」。  
   因此 audit 所報 before 1.1678306、p=0.0409368（`k528_nfp_official_dates_results.json:136-150`）仍受上一輪同類洩漏污染；卻宣稱兩欄使用相同 restricted estimand、差異只來自日期（`:170`）。用同一 pinned SPY snapshot 排除該日後，proxy restricted 應約為：

   - 1.16671×
   - p=0.04214
   - n=239 vs 832，而非實作中的 239 vs 833

   方向仍顯著，但 audit 的識別敘述和精確數值不成立。`as_published_mixed_weekday` 可以保留歷史污染值；新建的 like-for-like `before` 不應繼續污染。

2. **BLOCKER — `check_calendar_is_complete` 仍可輕易繞過，整個尾段消失正是現存漏洞。**  
   `start/end` 傳入後實際未參與 completeness span；span 完全由 `min(selected)..max(selected)` 決定（`k528_nfp_event_study.py:172-179`）。我用 commit 內的 production `load_nfp_dates` helper 實測：

   - `start=2024-01-01, end=2024-12-31`
   - raw feed 完整含 1–12 月
   - accessor selected 只剩 1–3 月

   結果仍然 **ACCEPTED**，回報 `n_raw_entries=12`、`n_months_in_span=3`。這在 production 特別合理，因為 accessor 可讀 cache、raw 又另做一次 live fetch（`:216-222`）；cache 少了新尾月時會無聲通過。

   另外三種錯誤輸入也實測被接受：

   - 較早錯誤條目與正式發布相隔剛好 3 天：條件寫成 `< 3`（`:150-153`），可規避。
   - selected 憑空包含 raw feed 沒有的月份：沒有驗證 selected/raw month-set 相等。
   - selected 同月重複但將最早日期放最後：`dict(zip(...))` 蓋掉重複（`:148`），可通過。

   更嚴重的是新增的「乾淨日曆必須通過」測試自己就用全年範圍只提供 1–3 月，並期待成功（`tests/test_nfp_official_release_dates.py:596-604`），等於把尾段消失正式寫成合法行為。README 所稱「移除首尾月漏洞」（`README.md:210-220`）是錯誤 overclaim。

3. **HIGH — `TestControlGroupHasNoNfpDays` 是 vacuous，無法抓到控制組洩漏回歸。**  
   `tests/test_nfp_official_release_dates.py:531-538` 先定義：

   `total_sessions = non_nfp_trading_days + n_mapped_to_sessions`

   再斷言：

   `non_nfp_trading_days == total_sessions - n_mapped_to_sessions`

   這是代數恆等式，`non_nfp_trading_days` 即使退回錯誤的 5087 仍會通過。`:540-544` 只驗 valid/excluded partition，完全未驗控制日期集合交集。  
   `_k528_module()` 的 AST 方式本身不是假 implementation——它確實編譯 production FunctionDef；問題是測試沒有走完整 production wiring，且上述控制組測試根本沒測日期集合。

4. **已驗收 — 現行 official 控制組與 headline 統計量正確。**  
   Production 已改用全部 `nfp_trading_dates` 排除控制（`k528_nfp_event_study.py:403-413`）。以獨立 pinned SPY snapshot 和 commit 事件日期重算：

   - 5,340 個有效交易日 − 254 個 mapped NFP sessions = **5,086 controls**
   - Friday-only：237 vs 834，**1.188993×，p=0.020855**
   - mixed diagnostic：253 vs 834，**1.176761×，p=0.025693**

   與 artifact `k528_nfp_event_study_results.json:13-17,63-90` 對齊。`2005-01-07` 已不在現行控制組。

5. **已驗收 — weekday composition、claim scope、11/16 矛盾均已修正。**  
   逐事件重算確認：

   - proxy：239 Friday、15 Monday
   - official：237 Friday、16 non-Friday，分別為 Monday 6、Tuesday 2、Wednesday 1、Thursday 7
   - 非週五平均 0.7151%，比週五 0.8541% 低 **16.268%**

   Results 的 `claim_scope`、`restriction_is_not_neutral` 和資料生成的 16 場均一致（`k528_nfp_event_study_results.json:63-81`）。README `:73-87` 與 builder `:108-119,187-200` 也把「條件於週五」及非中性排除放在讀者可見文字中，不只藏在 JSON。

6. **已驗收 — 19 條更正的 after 數值對齊，但尚未套用。**  
   對目前 canonical 文章驗證，19 個舊字串全部各命中一次，新字串目前皆為零次；audit 狀態也誠實標示 `validated_not_applied`（`k528_nfp_official_dates_results.json:349-359`）。獨立抽查超過 8 項均吻合：253、0.845%、0.763%、1.11×、237、1.19×/p=0.021、16 場、16.69、128/125、1.13%/0.56%、2.03×、Pearson 0.44、Spearman 0.35、斜率 0.043pp、VIX 距離 0.10。  
   圖表仍舊版數據也有顯式揭露（`:457-458`），沒有假稱已完成視覺更正。

7. **MEDIUM — README 仍有 artifact 與推論 overclaim。**

   - `README.md:146-147` 列出 `k528_rerun_v3_summary.json`、`review_verdict_v3.json`，但 commit tree 內兩檔都不存在；實際只有舊的 `review_verdict.json`。
   - `README.md:120-121` 宣稱「決定 NFP 日波動的是 VIX 體制、遠大於 NFP 事件本身」，超過本實驗證據。這只是 full-sample median split 的條件關聯，沒有因果識別，也沒有正式檢定 2.03× 是否顯著大於 1.11×/1.19×；results 自己反而明說不能據此宣稱「不是 NFP 本身」（`k528_nfp_event_study.py:1180-1185`）。

8. **其餘已驗收。**  
   Fixture docstring 已準確限定為 `_fetch` 回傳日期清單、非完整 HTTP body（`tests/test_event_dates_real_raw_response.py:11-21`）；殘留 p=0.0571 已改為錯誤歷史紀錄。`pre_vix` 使用 T−1（`k528_nfp_event_study.py:355-381`），未見 same-day lookahead；本實驗無隨機抽樣，seed 不適用；主 results 與 audit 均使用同目錄 tempfile、`fsync`、`os.replace`（`:89-110,1201-1238`）；builder 預設 dry-run 不寫（`build_article_correction.py:314-321`）。

Blocking defects：proxy restricted audit 仍含 `2005-01-07` 控制組洩漏；calendar completeness 仍接受完整尾段消失、3-day equality、selected/raw 不一致等錯誤輸入。

VERDICT: FAIL
tokens used
218,597
審查範圍固定為 commit `2abb3f68c`。目前 worktree 有 5 個未提交修改，以下全部以 `git show 2abb3f68c:<path>` 驗證，不納入後續修正。

1. **BLOCKER — audit 的 proxy `before` 控制組仍洩漏 `2005-01-07`，所以主 before/after 尚非同一個乾淨 estimand。**  
   `experiments/k528/k528_nfp_event_study.py:748-753` 只用 archive `event_data` 排除 proxy 事件；但 archive 第一筆是 `2005-02-04`（`k528_nfp_event_study_results_PROXY_SUPERSEDED.json:215-217`），窗口不足的 proxy NFP session `2005-01-07` 不在其中，仍被算成「non-NFP Friday」。  
   因此 audit 所報 before 1.1678306、p=0.0409368（`k528_nfp_official_dates_results.json:136-150`）仍受上一輪同類洩漏污染；卻宣稱兩欄使用相同 restricted estimand、差異只來自日期（`:170`）。用同一 pinned SPY snapshot 排除該日後，proxy restricted 應約為：

   - 1.16671×
   - p=0.04214
   - n=239 vs 832，而非實作中的 239 vs 833

   方向仍顯著，但 audit 的識別敘述和精確數值不成立。`as_published_mixed_weekday` 可以保留歷史污染值；新建的 like-for-like `before` 不應繼續污染。

2. **BLOCKER — `check_calendar_is_complete` 仍可輕易繞過，整個尾段消失正是現存漏洞。**  
   `start/end` 傳入後實際未參與 completeness span；span 完全由 `min(selected)..max(selected)` 決定（`k528_nfp_event_study.py:172-179`）。我用 commit 內的 production `load_nfp_dates` helper 實測：

   - `start=2024-01-01, end=2024-12-31`
   - raw feed 完整含 1–12 月
   - accessor selected 只剩 1–3 月

   結果仍然 **ACCEPTED**，回報 `n_raw_entries=12`、`n_months_in_span=3`。這在 production 特別合理，因為 accessor 可讀 cache、raw 又另做一次 live fetch（`:216-222`）；cache 少了新尾月時會無聲通過。

   另外三種錯誤輸入也實測被接受：

   - 較早錯誤條目與正式發布相隔剛好 3 天：條件寫成 `< 3`（`:150-153`），可規避。
   - selected 憑空包含 raw feed 沒有的月份：沒有驗證 selected/raw month-set 相等。
   - selected 同月重複但將最早日期放最後：`dict(zip(...))` 蓋掉重複（`:148`），可通過。

   更嚴重的是新增的「乾淨日曆必須通過」測試自己就用全年範圍只提供 1–3 月，並期待成功（`tests/test_nfp_official_release_dates.py:596-604`），等於把尾段消失正式寫成合法行為。README 所稱「移除首尾月漏洞」（`README.md:210-220`）是錯誤 overclaim。

3. **HIGH — `TestControlGroupHasNoNfpDays` 是 vacuous，無法抓到控制組洩漏回歸。**  
   `tests/test_nfp_official_release_dates.py:531-538` 先定義：

   `total_sessions = non_nfp_trading_days + n_mapped_to_sessions`

   再斷言：

   `non_nfp_trading_days == total_sessions - n_mapped_to_sessions`

   這是代數恆等式，`non_nfp_trading_days` 即使退回錯誤的 5087 仍會通過。`:540-544` 只驗 valid/excluded partition，完全未驗控制日期集合交集。  
   `_k528_module()` 的 AST 方式本身不是假 implementation——它確實編譯 production FunctionDef；問題是測試沒有走完整 production wiring，且上述控制組測試根本沒測日期集合。

4. **已驗收 — 現行 official 控制組與 headline 統計量正確。**  
   Production 已改用全部 `nfp_trading_dates` 排除控制（`k528_nfp_event_study.py:403-413`）。以獨立 pinned SPY snapshot 和 commit 事件日期重算：

   - 5,340 個有效交易日 − 254 個 mapped NFP sessions = **5,086 controls**
   - Friday-only：237 vs 834，**1.188993×，p=0.020855**
   - mixed diagnostic：253 vs 834，**1.176761×，p=0.025693**

   與 artifact `k528_nfp_event_study_results.json:13-17,63-90` 對齊。`2005-01-07` 已不在現行控制組。

5. **已驗收 — weekday composition、claim scope、11/16 矛盾均已修正。**  
   逐事件重算確認：

   - proxy：239 Friday、15 Monday
   - official：237 Friday、16 non-Friday，分別為 Monday 6、Tuesday 2、Wednesday 1、Thursday 7
   - 非週五平均 0.7151%，比週五 0.8541% 低 **16.268%**

   Results 的 `claim_scope`、`restriction_is_not_neutral` 和資料生成的 16 場均一致（`k528_nfp_event_study_results.json:63-81`）。README `:73-87` 與 builder `:108-119,187-200` 也把「條件於週五」及非中性排除放在讀者可見文字中，不只藏在 JSON。

6. **已驗收 — 19 條更正的 after 數值對齊，但尚未套用。**  
   對目前 canonical 文章驗證，19 個舊字串全部各命中一次，新字串目前皆為零次；audit 狀態也誠實標示 `validated_not_applied`（`k528_nfp_official_dates_results.json:349-359`）。獨立抽查超過 8 項均吻合：253、0.845%、0.763%、1.11×、237、1.19×/p=0.021、16 場、16.69、128/125、1.13%/0.56%、2.03×、Pearson 0.44、Spearman 0.35、斜率 0.043pp、VIX 距離 0.10。  
   圖表仍舊版數據也有顯式揭露（`:457-458`），沒有假稱已完成視覺更正。

7. **MEDIUM — README 仍有 artifact 與推論 overclaim。**

   - `README.md:146-147` 列出 `k528_rerun_v3_summary.json`、`review_verdict_v3.json`，但 commit tree 內兩檔都不存在；實際只有舊的 `review_verdict.json`。
   - `README.md:120-121` 宣稱「決定 NFP 日波動的是 VIX 體制、遠大於 NFP 事件本身」，超過本實驗證據。這只是 full-sample median split 的條件關聯，沒有因果識別，也沒有正式檢定 2.03× 是否顯著大於 1.11×/1.19×；results 自己反而明說不能據此宣稱「不是 NFP 本身」（`k528_nfp_event_study.py:1180-1185`）。

8. **其餘已驗收。**  
   Fixture docstring 已準確限定為 `_fetch` 回傳日期清單、非完整 HTTP body（`tests/test_event_dates_real_raw_response.py:11-21`）；殘留 p=0.0571 已改為錯誤歷史紀錄。`pre_vix` 使用 T−1（`k528_nfp_event_study.py:355-381`），未見 same-day lookahead；本實驗無隨機抽樣，seed 不適用；主 results 與 audit 均使用同目錄 tempfile、`fsync`、`os.replace`（`:89-110,1201-1238`）；builder 預設 dry-run 不寫（`build_article_correction.py:314-321`）。

Blocking defects：proxy restricted audit 仍含 `2005-01-07` 控制組洩漏；calendar completeness 仍接受完整尾段消失、3-day equality、selected/raw 不一致等錯誤輸入。

VERDICT: FAIL
EXIT=0
