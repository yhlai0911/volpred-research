# resource_monitor 工作日誌（append-only）

## 2026-08-05T06:52:15Z — per-agent/per-model token 消耗分解報告 v1

- **outcome**: done
- **工作項**: `item_20260805T055820533785Z_per-agent-per-model-token-v1-to`（P2，已歸檔）
- **結論**: 平台 7 日（2026-07-29～08-04 UTC）billable 184.4M，Codex 佔 76.4% 且其中
  81.6% 是桌面互動而非自動化 backbone；同時查出兩個結構性會計缺陷——每日日報連續 6 天
  寫成 0（少記 141.1M）、Codex fork 讓單一對話被計為 76 個 session（重複上界 60.1M）。
- **產出**: `reports/2026-08-05_token_breakdown_v1.md`、
  `memory/token_breakdown_2026-08-04_7d.json`、`tools/token_breakdown.py`（可重跑）
- **未做**: F1/F2/F3 的修正都落在 `scripts/token_usage_report.py` 與 cron wrapper，
  不在本部門 owned_paths，**未自行修改**，已列 R1–R4 回報經理指派。
- **下次接手先看**: `memory/notes.md` 的「已知缺陷」與「分析陷阱」兩節。

## 2026-08-05T08:05:00Z — v2：異常規則、F2 定案、分類口徑修正

- **outcome**: done
- **工作項**: `item_20260805T074432202854Z_r5-r2-v1-f1-f2-platform-eng-own`（P2）
  ＋ `item_20260805T071751544758Z_f1-commit-dab112d3a-summaries-py`（P2），兩項均已歸檔
- **結論**:
  (1) R5 自辦完成 —— 新增 `agent_concentration`(>20%)、`session_longevity`(>48h)、
      `idle_burn_session`、`repeat_churn` 四條規則；同窗觸發 3 件（單一 Codex 桌面對話
      佔 34.2%、窗內存活 103.8h、main_thread 一處 Read×6 重複）。日級規則仍 0 件，證明
      v1 F4 的盲區是真的。
  (2) F2 定案 —— turn-level 重算得重複量 **4,067,614（Codex 2.89%／平台 2.21%）**，
      v1 的上界 60.1M **高估約 15 倍**，對外口徑須改用定案值；但 session 計數灌水是真的
      （280 → 131 個邏輯對話）。
  (3) 分類口徑 —— 欄位改名為 `mission_output_share_pct_upstream_NOT_KPI` 就地標死，
      並新增部門自有口徑：Claude 側 effectful **41.65%（下界）**，推翻「主線程只有 0.5% 產出」。
- **重要更正（發給 platform_eng 的 P1 request）**: v1 寫的「最小修法：session_id 改綁
  `session_meta.session_id`」**是錯的** —— 2815 個 rollout 檔有 2815 個相異
  `session_meta.id`，且該綁定自 `95831cdb6` 起早已存在。正確鍵是 `forked_from_id` /
  `parent_thread_id` 追到底的 fork root。已於 07:55Z 直送其 inbox（當時他們正在寫該檔）。
- **產出**: `reports/2026-08-05_token_breakdown_v2.md`、
  `memory/token_breakdown_2026-08-04_7d.json`（v2 schema）、`tools/token_breakdown.py`（v2）
- **未做**: F3（PRICING 覆蓋率 20.2%）仍未修，成本欄位不可對外；
  `weekly_2026-07-31.json` 仍是 0，需回填（不在本部門 owned_paths，已回報經理）。
- **下次接手先看**: `memory/notes.md` 的「已知缺陷」與「分析陷阱」兩節，特別是
  「上界不是結論」與「effectful 是下界」兩條。

## 2026-08-05T09:10:00Z — v3：對外口徑清單與影響面盤點

- **outcome**: done
- **工作項**: `item_20260805T084436183518Z_v2-1-f2-v1-60-1m-4-07m-15-v1-fo`（P2，已歸檔）
- **結論**:
  (1) **184.4M -> 180.3M 完全沒有對外** —— 全量掃 storage/、docs/、.claude/、
      storage/notifications/ 後 11 處命中全在 `storage/org/` 內部。內部修即可。
  (2) **280 -> 131 有對外** —— 每日 08:00 token email 帶三個 session 維度欄位
      （`unique_sessions` KPI、`by_session` top-3、說明敘事）；內部側另有
      `storage/reports/token_usage/` 98 份中 87 份帶非零 session 計數。
  (3) **自我更正（方向更嚴重）**：v2 報的 R2 集中度 34.2% 是 session_id 層級下界，
      fork root 收斂後真值 **59.0%**（106,410,266 / 180,312,894）——一個 Codex 桌面對話
      吃掉平台 7 日近六成。R3 壽命 103.76h 同為下界。per-session 平均 0.50M -> 1.04M。
  (4) **盤點外的重大發現**：**連續 6 封已寄出的日報寫「今日 0 billable」**
      （07-31～08-05，`sent=True`），是 F1 日界缺陷的對外顯現；且老闆已在回應該線
      （08-05T01:45 P1 回信、02:28 平台承諾今日交付）。已附更正方式建議請經理裁決。
  (5) **F3 已可回答，不必等 platform_eng**：covered 20.2% / uncovered 79.8%，
      **Codex 側覆蓋率 0.0%**；成本下界 1242.43 美元，上界無法給定，
      外推參考值約 6141 美元（非量測、不可對外）。
- **產出**: `reports/2026-08-05_external_figure_inventory.md`；
  `reports/2026-08-05_token_breakdown_v1.md` 加 SUPERSEDED 標頭；`memory/notes.md` 三節新增
- **送出**: 經理回報（P1，reply-to 本工作項）＋ governance 更正 request（P2，34.2% -> 59.0%）
- **未做**: R3 壽命的 root 層級重算（只標下界，不給假數字）；
  `weekly_2026-07-31.json` 仍是 0（不在 owned_paths，已第二次上報）
- **下次接手先看**: `memory/notes.md` 新增的「對外口徑地圖」——判「這數字對外了嗎」
  一律先掃 `storage/notifications/` 的 `sent=True`，不要重查一遍全 repo。

## 2026-08-05T09:16:00Z — D6 三項 ＋ 自我更正（同 session 續辦）

- **outcome**: done
- **工作項**: `item_20260805T090331099550Z_d6-...`（P2，經理裁決 D6）已歸檔；
  `item_20260805T091405166238Z_...`（governance 回覆，已獨立複算驗證 59.0%）已歸檔
- **(a) weekly_2026-07-31.json —— 撤回前兩輪的說法，是我判讀錯誤**：該檔的 `week_range`
  是 2026-07-31 → 2026-08-07（**未來的一週**），07-31 08:01 產出時該週才開始 1 分鐘。
  commit `dab112d3a` 的 `_report_covers_its_period()` 正為此設計，會在 08-07 後自動重產。
  實測：`build_token_usage_maintenance()` → `action=skip`、`weekly_due=false`、
  最近完整週＝`weekly_2026-07-24.json`（238,499,898）。**不需回填、不需送 platform_eng。**
  教訓：報表是 0 時先讀 `week_range` 判斷期間結束了沒，再跑 plan 函式看系統怎麼看它。
- **(b) 34.2% 是下界，真值 59.0%**（fork root 收斂）—— 已直送 governance，對方回讀
  `codex_duplicate_audit` 獨立複算確認，並據此解除了自己的 blocked-on-R2。
- **(c) idle_burn caveat 從 md 正文升級為機器可讀**：`kpi_field_warnings` 新增三條
  （`idle_burn_session_NOT_A_PASS`、`agent_concentration_IS_A_LOWER_BOUND`、
  `effectfulness_bounds`），並改 `tools/token_breakdown.py` 讓之後每次產出都自帶。
- **產出**: `tools/token_breakdown.py`（warnings）、`memory/token_breakdown_2026-08-04_7d.json`
  （回填 warnings）、`memory/notes.md`（撤回週報缺陷條目＋教訓）、
  `reports/2026-08-05_external_figure_inventory.md` §5（撤回第 6 項）、`state.json`
- **下次接手先看**: open_items 只剩 4 項真的沒做的 ＋ 1 項等 08-07 自動重產後回讀。

## 2026-08-05T09:42:00Z — D12：更正區塊規格 ＋ 往定義修挖出三件新事

- **outcome**: done
- **工作項**: `item_20260805T093339062005Z_d12-...`（P1，經理裁決 D12）已歸檔
- **(1) 更正區塊規格已交付並直送 platform_eng（P1，時效綁下一封 email）**：
  實際值 07-31=547,759／08-01=43,240,765／08-02=25,093,007／08-03=9,698,197／
  08-04=24,178,959（5 日合計 102,758,687）；08-05 寄信時該 UTC 日未結束，無真值。
  規格三項硬要求：07-31 照實寫不誇大、措辭不可讀成「已優化」、**成本欄位不進更正區塊**。
  數據可信度：獨立管線逐日對照，7 天中 6 天完全一致，07-31 差 3,933（0.7%）。
- **(5) 一句話結論：不該回填；判準是「期間結束了沒」，不是「內容是不是 0」。**
  根因是**報表無法自我描述**——完整性存在 mtime（`summaries.py:513`）而非 payload。
  經理「三輪改口＝定義不清」的判斷正確。修法已送 platform_eng（`period_end` +
  `generated_at`，欄位缺失才 fallback mtime）。
- **往定義挖之後的三件新發現**：
  (a) **現場實證**：17:37:56 dispatch-supervisor 例行跑（`8cc3a6afc`）重產
      `weekly_2026-07-31`，值 0 → 126,428,721，而該週還沒結束。同一天兩個值、
      兩個都是中間態、讀者無法分辨——我本要論證的風險自己演了一次。
  (b) **98 份報表中 47 份寫在期間結束前**；其中 5 份 weekly 期間早已結束卻
      **永久凍結在部分期間值**（05-29～06-26），因自癒只補「最近一個完整週」。
      **這類比「今日 0」更該擔心：0 顯眼會被抓到，部分期間的非 0 值沒人會懷疑。**
  (c) **F5（新缺陷，與 F1 無關）**：`weekly_2026-07-19` mtime 在期間結束後、
      通過完整性檢查，卻至少低估 58,272,103（≥2.9 倍）；`unique_sessions`=63
      vs 相鄰週 516/390/726/799。根因不推測，證據已交 platform_eng。
- **另交回歸基準**：`daily_2026-07-21`～`07-28` 八天全是 0（回填只做近 7 天），
  真值合計 **222,196,866**。交叉驗證通過（weekly_07-24 − 已回填兩日 = 逐日重算加總，
  兩條獨立路徑完全相同）。
- **產出**: `reports/2026-08-05_email_correction_block_spec.md`、
  `reports/2026-08-05_period_semantics_ruling.md`、`memory/notes.md`
- **送出**: platform_eng ×2（P1 更正區塊、P1 三件新證據）、經理回報（P1）
- **下次接手先看**: `memory/notes.md` 的「報表可信度的唯一判準」三分支決策樹——
  讀到任何 token 報表先走它，不要再從 `totals == 0` 起手。

## 2026-08-05T10:07:00Z — D18：三分支規則寫成常規 ＋ fresh clone 加驗規格化

- **outcome**: done
- **工作項**: `item_20260805T100345300002Z_d18-...`（P1，經理裁決 D18）已歸檔
- **經理指定寫成常規的方法已入 memory**：
  「**改口 ≥2 次 → 去看那份資料能不能自我描述；不能，那才是要修的東西。**」
  附 07-31 三輪實例當範本，並記下：只改結論的話，47/98、五份凍結 weekly、F5、
  移機風險這四件一件都不會被發現。
  一併寫入排序原則：「通過檢查的錯誤 > 沒通過檢查的錯誤」「看起來正常的錯值 > 顯眼的 0」。
- **fresh clone 加驗（D18 新增第 7 項）已規格化交付 platform_eng**：
  設計成 **regression test 而非一次性人工驗證**（一次性擋不住復活，測試才擋得住），
  且**不真 clone**——用 `os.utime` 模擬 clone 後 mtime，確定性且可進 CI。四個 case，
  core case = 新格式・期間未結束・mtime 設成現在 → 期望 `covers == False`（現在會失敗）。
- **實測佐證**：weekly_2026-05-29／weekly_2026-07-31／daily_2026-08-04 三份 payload
  **完全沒有** `generated_at` / `period_end` / `period_complete` 任何欄位。
- **回填期望值**：daily 07-21~07-28 合計 **222,196,866**（容差 0，交叉驗證已通過）；
  F5 的 07-19 標為**下界 > 78,116,380 而非期望值**；
  五份凍結 weekly **明確不給數字**（需重算約 25 分鐘，本輪未做——給不出來就不給，
  不用推估值冒充期望值）。
- **誠實缺口（已主動向經理揭露）**：「git 不儲存 mtime」本環境**未實測**，
  `git clone` / `checkout-index` / `ls-tree` 三種驗法全被權限模式 deny。
  未硬繞權限；該缺口由 core case 那個測試補上。
- **邊界**: 五份 weekly、F5、八天 daily 的回填動作全歸 platform_eng，
  本部門只交數字與驗證方法，未動任何一份報表檔。
- **產出**: `reports/2026-08-05_verification_plan_v2.md`、`memory/notes.md`
- **送出**: platform_eng（P2 驗證計畫 v2）、經理回報（P2）
- **下次接手先看**: `reports/2026-08-05_verification_plan_v2.md` —— platform_eng 交付後
  直接照它跑；B2 那批要先花約 25 分鐘重算真值才能比對。

## 2026-08-05T10:22:00Z — D22：更正文字由規格升級為完成文字（可直接貼上）

- **outcome**: done
- **工作項**: `item_20260805T101644798574Z_184-4m-180-3m-bulletin-2026-08`（P2）已歸檔
- **第二項（經理裁決改由本部門主張）**：寫出**完成文字**而非規格，platform_eng 只需貼上。
  產出 `reports/2026-08-05_email_correction_TEXT_ready_to_paste.md`，含可直接複製的
  HTML python 片段與純文字版，並標明貼入 `token_report_email.py` 的精確位置
  （h1／sub 之後、week cap card 之前）與**一次性生效條件**（寄出後刪除該段程式碼）。
  上一則送出的「規格」已明確作廢。
  **自行驗證**：把片段抽出以 mock `esc`／`p` 實跑，渲染正常、五列正確、
  合計 102,758,687 與逐項加總相符——承諾「貼上就能用」就該由我確保它不在別人手上爆。
- **措辭四決定**：標題與底色避開「好消息」形式；07-31 照實寫 547,759 不跳過
  （落差最小的一天，挑掉它會像在挑證據）；**08-05 那格不填數字**、只指向信裡既有的
  當週趨勢（寫文字時該檔仍是 0，且無法預知寄出日；已明確要求 platform_eng 不要代填）；
  金額完全不進更正區塊。
- **第一項（bulletin 更正）**：經理寫不進 bulletin（`bulletin_append` 只被 `org_admin.py`
  四處呼叫、無獨立 CLI）。本部門**建議不必單獨為它開寫入通道**——該條錯誤數字的下游
  危害已封住（platform_eng 與 governance 都已收到定案值，後者還獨立複算過），
  缺的只是紀錄面；為一條無下游危害的紀錄開新通道正是疊床架屋。建議併入既有提案批次。
  裁決權在經理，已聲明照辦。
- **第三項（mtime 載體）**：修法卡在保留區，但本部門已把 fresh clone case 規格化交付，
  **測試先於修法存在**，修法一落地就有東西擋它復活。
- **產出**: `reports/2026-08-05_email_correction_TEXT_ready_to_paste.md`
- **送出**: platform_eng（P1，完成文字）、經理回報（P2）
- **下次接手先看**: 若 platform_eng 回報日報數字因修法而變動，**不要沿用那張表**，
  重跑獨立管線對照後再更新文字（已在文字檔第 4 節寫成貼上前檢查）。

## 2026-08-05 21:03 台灣時間 — D43（token 實況盤點 + 判準寫成 skill）

工作項 `item_20260805T111916735231Z_d43-idle-platform-eng-f1-f2-f3-w`（P3, manager）
**outcome=done** — 停擺那 2.5 小時燒掉全日 52.1% 但不是空轉（effectful 46.7% 高於全天
44.6%），因為部門 pane 是 16:51 才批次啟動、正好落在停擺窗內；並行部門制的倍數是
每活躍小時 2.14x／尖峰 3.77x／併發 2.8x，而**單 session 速率沒變**（成本隨部門數線性）。

- 產出：`reports/2026-08-05_D43_today_token_reality.md` ＋ turn-level 原始資料
  `reports/data/2026-08-05_today_burn.json` ＋ 兩支新工具
  `tools/today_burn.py`（小時×session×效力）、`tools/hourly_baseline.py`（併發基線）
- 沒被問到但更該知道：**今天 Codex 側 telemetry 零記錄**，平台總量 4.7M 只有 08-02
  （41.8M）的 11%。部門制的邊際成本應該跟 Codex backbone 的 20–45M/日 比，不是跟
  Claude 側的 1M/日 比——這條會改變「部門制貴不貴」的結論方向。
- 判準已升級成部門 skill `skills/report-trust-judgment/SKILL.md`（三條規則：改口≥2次→
  查資料能否自我描述／可信度看期間結束沒而非內容是否為 0／通過檢查的錯誤優先於顯眼的 0），
  `memory/notes.md` 對應三節縮成 pointer（8761→8026 bytes，去重不留兩份）。
- **發現一個 skill 載入缺口並已通報**：`scripts/org/_core.py:431-441` 的
  `identity_prompt()` 只讀 charter.md 與 memory/notes.md，**沒有任何 skills/ 載入路徑**，
  所以經理說的「下次 attach 自動載入」目前不成立。已送 request 給 platform_eng
  （`item_20260805T112311829955Z`），暫解是 notes.md 的 pointer 行。

## 2026-08-05 21:14 台灣時間 — P1 platform_eng 收件匣分流盤點

工作項 `item_20260805T112000862739Z_platform-eng-74-read-only-platf`（P1, manager）
**outcome=done** — 四類分佈 (a)52／(b)16／(c)5／(d)9，合計 82 件（非派工說的 74）。
(b)+(c)+(d)=36.6% **未過半**，所以「真實負載可能只有 30 出頭」的假設不成立，真值是 52。

- **兩個派工前提都被推翻**：件數是 82 不是 74；「33 筆 >7 天」完全不成立——收件匣最舊
  0.2 天，全部今天產生。那組 74/33 出自收件匣**裡面**的一張 canonical 鏡像單標題
  （platform_ops pending 池，assign_2fdba4c4），講的是任務池不是收件匣，兩個語料被合成一個。
- blocking_on 給了兩欄：機械規則 zone_a=8，人工複讀後真正修復面在 Zone A 的只有 3 件
  （機械規則會把「提到 Zone A 只為了說這不是你的」誤判成阻塞）。**48/52 零外部依賴。**
- 產出：`reports/2026-08-05_platform_eng_inbox_triage.md` ＋ 五支唯讀複驗腳本
  `tools/pe_triage/`。全程未動 platform_eng 子樹任何檔案。
- **本班我自己犯了一次錯並撤回**：送給 platform_eng 的「部門 skills/ 不會被載入」request
  是錯的（org_attach.py:278-280 早就以 --plugin-dir 掛上，commit 407a367e9）。
  我只 grep 了 _core.py 一個檔就下「全組織不存在」的結論。已於同班撤回並回報經理。

## 2026-08-05 22:03 台灣時間 — P1 今日採集為 0 的根因 + 儀表分工 + 章程事故定義

工作項 `item_20260805T135712462998Z`（P1, manager）
**outcome=done** — 根因是 F1 的**最後一個受害者**，不是新缺陷也不是未修的缺陷：
修法 `dab112d3a` 落地於今天 15:17:15，而那個 0 是今早 00:00:50Z（台灣 08:00:50）
由**修法前的程式碼**寫下的，早了 7 小時 17 分。

- **不補資料，而且補了有害**：人工重產會把 mtime 蓋成期間之後，自癒機制以後就認為它完整。
  現行程式碼的判定我直接問了 planner（不預測）：
  `_report_covers_its_period(daily_2026-08-05, 08-06)=False`、
  `build_token_usage_maintenance(target=08-05) → action=generate_daily_report`
  → **明早 08:00 那班會自動重產**。對照組 target=08-04 回 skip，證明自癒只針對真的不完整的。
- **我的失職點不在修法，在對照**：我今天 D43 自己算出 4,734,619，canonical 日報寫 0，
  **兩個數字都在我手上而我沒有放在一起看**。已寫進 charter 的事故定義。
- 順線抓到第二個儀表缺陷（P1）：`ops_snapshot.alerts.sent_last_24h` **結構性恆為 0**
  （讀 `sent_at`/`ts`，寫端寫 `last_sent_at`；678 筆 dedup 中 0 筆有 `sent_at`），
  而它進**每一份經理 brief**——今天停擺 2h45m 期間經理看到的是「alerts 已送 0 則」。
- 儀表分工已入章程：額度只看 `/usage`，billable 只做成本歸屬。實測落差：
  email 報 76%、`/usage` 89%；repo 內兩個 cap 常數（77.7M vs 213.3M）差 2.75 倍，
  錨點停在 07-01（35 天前）。
- 兩個缺陷已送 platform_eng（`item_20260805T140214140944Z`，附行號與全量佐證）。
  **我沒有 owned_paths，本班未修任何程式碼，也不宣稱修了。**
- 產出：`reports/2026-08-05_daily_zero_root_cause.md`、`tools/verify_selfheal.py`、
  charter 新增三節（儀表分工／事故定義／開班儀表巡檢）。
