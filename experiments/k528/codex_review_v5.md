OpenAI Codex v0.144.1
--------
workdir: /Users/yhlai0911/volpred-research
model: gpt-5.6-sol
provider: openai
approval: never
sandbox: read-only
reasoning effort: high
reasoning summaries: none
session id: 019f7998-bbf1-74f0-9f4c-7b2be024ed49
--------
user
你是嚴格的計量金融代碼審查者。K528 NFP 事件研究修正案的**第五輪**審查（三審 round-3）。
**審查範圍固定為 commit `58853f3ab`**；若工作樹有未提交修改，一律以
`git show 58853f3ab:<path>` 為準。

**審查對象**（絕對路徑 `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/`）：

`experiments/k528/`：`README.md`、`k528_nfp_event_study.py`、`build_article_correction.py`、
`k528_nfp_event_study_results.json`、`k528_nfp_official_dates_results.json`、
`k528_nfp_event_study_results_PROXY_SUPERSEDED.json`
歷史裁決：`codex_review_v2.md`、`codex_review_v3.md`、`codex_review_v4.md`
（**v4 是你上一輪的 FAIL，本輪要驗收它**）、`review_verdict_v3.json`、`review_verdict_v4.json`

共用模組與測試：`src/volpred/data/event_dates.py`、
`tests/test_nfp_official_release_dates.py`、`tests/test_event_dates_real_raw_response.py`、
`tests/test_event_dates_release_selection.py`、`tests/fixtures/fred_release_50_nfp_raw_20260719.json`

**背景**：你在 round-2（`codex_review_v4.md`，對 `2abb3f68c`）判 FAIL，列 2 條 blocking
（proxy 側控制組洩漏、completeness 四種繞過）+ 1 條 HIGH（vacuous 控制組測試）
+ 1 條 MEDIUM（README overclaim）。本 commit 是針對那些的 remediation。

**本輪聲稱做了什麼**（逐條驗收，不要照單全收）：

1. **BLOCKER 1（proxy 側控制組洩漏）** — 聲稱重建 proxy 完整 session 集合（只對 archive
   未涵蓋的月份套 first-Friday 規則，並斷言只增不移、不與 archive 事件碰撞），
   proxy restricted before 變為 **1.16671 / p=0.04214 / n=239 vs 832**（與你上一輪獨立
   重算一致）。同時保留兩個 proxy 對照組：archive 版驗證重建忠實度、leak-free 版供比較。

2. **BLOCKER 2（completeness 四種繞過）** — 聲稱補上：(a) 請求視窗覆蓋檢查（頭尾任一端
   短少 >70 天 raise，關掉「整個尾段消失」）、(b) selected 含 raw 沒有的月份/日期 raise、
   (c) selected 同月重複 raise（原本 `dict(zip())` 會靜默蓋掉）。
   **並且移除了「同月兩筆間隔 <3 天」啟發式** —— 聲稱理由是真實 feed 中六個同月多筆月份
   有三個（2006-05/2013-05/2020-05）剛好間隔 3 天，該門檻被自己的資料推翻；
   真正的控制改為 `REVIEWED_MULTI_ENTRY_MONTHS` 允許清單。

3. **HIGH 3（vacuous 測試）** — 聲稱改為對獨立記錄的 `total_trading_days`(5340) 斷言，
   並加 `control_group_excludes_all_nfp_sessions` 布林；另加
   `test_proxy_side_control_group_is_also_clean` 釘住 832。
   `_k528_module()` 改為以「是不是 literal」挑常數，不再用手寫名單。

4. **MEDIUM 7（README overclaim）** — 聲稱把「決定波動的是 VIX 體制、遠大於 NFP 本身」
   改寫為量級對照，並明列三條邊界（非因果、未檢定 2.03 是否顯著大於 1.19、事後中位數分割）。
   另聲稱補上先前缺漏的 `review_verdict_v3/v4.json`、`codex_review_v4.md`。

**審查重點（請獨立驗算，不要只讀 diff）**：

1. proxy 重建是否正確且沒有偷偷改動已分析事件；1.16671/p=0.04214/n=239 vs 832 是否可重現
2. **再試著繞過 `check_calendar_is_complete`** —— 新增三關之後還剩什麼形狀？
   70 天容忍度可否被利用？`REVIEWED_MULTI_ENTRY_MONTHS` 是不是變成新的後門？
   移除 gap 啟發式是否讓某些真實錯誤變得測不到（亦即這個移除是不是把關卡拆掉了）？
3. 新測試是否還有 vacuous 的；`test_proxy_side_control_group_is_also_clean` 是否只是
   複述 artifact 而非驗證性質
4. 19 條文章更正是否逐條與新 results 對齊（抽查至少 8 條）；claim scope 是否在讀者
   看得到的地方
5. README / results / builder 三處敘述是否互相一致，有沒有新的 overclaim 或殘留舊數字
6. lookahead / seed / 原子寫入
7. 兩個 proxy 對照組並存會不會讓某個 audit 欄位不小心用錯那一個

**特別注意**：這是連續第三輪 FAIL 後的修正，agent 有強烈動機宣稱收斂。請主動找它可能
自我欺騙、過度宣稱、或「修 A 弄壞 B」的地方。若確認修好了也請明說哪幾條已驗收。

**輸出格式**：逐點 findings（嚴重度 + 檔案:行號）；最後一行單獨輸出
`VERDICT: PASS` 或 `VERDICT: CONDITIONAL PASS` 或 `VERDICT: FAIL`（FAIL 須列 blocking defects）。

codex
我會把 `58853f3ab` 當唯一證據源，先讀 handoff 與 v4 裁決，再分別獨立驗算 proxy 統計、攻擊 completeness invariant、核對測試與 19 條更正。工作樹內容即使不同，也不會納入裁決。
exec
/bin/zsh -lc "sed -n '1,220p' storage/ops/handoff_latest.md && git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp rev-parse --verify 58853f3ab"'^{commit} && git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp status --short && git -C /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp show --stat --oneline --decorate --no-renames 58853f3ab' in /Users/yhlai0911/volpred-research
 succeeded in 189ms:
58853f3ab (HEAD -> k528-nfp-official-dates) fix(k528): 修三審 round-2 的兩個 BLOCKER + vacuous test；移除被自己資料推翻的 gap 啟發式
 experiments/k528/README.md                         |    38 +-
 experiments/k528/codex_review_v4.md                | 11402 +++++++++++++++++++
 experiments/k528/k528_nfp_event_study.py           |   202 +-
 experiments/k528/k528_nfp_event_study_results.json |  2563 ++---
 .../k528/k528_nfp_official_dates_results.json      |    47 +-
 experiments/k528/review_verdict_v3.json            |    21 +
 experiments/k528/review_verdict_v4.json            |    21 +
 tests/test_nfp_official_release_dates.py           |   153 +-
 8 files changed, 13099 insertions(+), 1348 deletions(-)

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
for p in experiments/k528/README.md experiments/k528/k528_nfp_event_study.py experiments/k528/build_article_correction.py experiments/k528/k528_nfp_event_study_results.json experiments/k528/k528_nfp_official_dates_results.json experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json experiments/k528/codex_review_v2.md experiments/k528/codex_review_v3.md experiments/k528/codex_review_v4.md experiments/k528/review_verdict_v3.json experiments/k528/review_verdict_v4.json src/volpred/data/event_dates.py tests/test_nfp_official_release_dates.py tests/test_event_dates_real_raw_response.py tests/test_event_dates_release_selection.py tests/fixtures/fred_release_50_nfp_raw_20260719.json; do
  git -C "$repo" cat-file -e "58853f3ab:$p" 2>/dev/null && echo "OK $p" || echo "MISSING $p"
done

git -C "$repo" show --format= --no-ext-diff --unified=35 58853f3ab -- experiments/k528/k528_nfp_event_study.py tests/test_nfp_official_release_dates.py src/volpred/data/event_dates.py experiments/k528/README.md | sed -n '"'1,2600p'" in /Users/yhlai0911/volpred-research
 succeeded in 140ms:
OK tests/test_nfp_official_release_dates.py
OK tests/test_event_dates_real_raw_response.py
OK tests/test_event_dates_release_selection.py
OK tests/fixtures/fred_release_50_nfp_raw_20260719.json
diff --git a/experiments/k528/README.md b/experiments/k528/README.md
index 27f7282e8..ca750de48 100644
--- a/experiments/k528/README.md
+++ b/experiments/k528/README.md
@@ -85,72 +85,77 @@ NFP 的 0.854% **低 16.3%**，所以限定之後 ratio 會被墊高（1.177× 
 
 **因此這個檢定識別的是「週五公布的 NFP」，不是「NFP 一般而言」。** 引用這個數字的文字
 必須寫「在週五公布的 NFP」。
 
 兩種口徑在 audit 中**兩邊平行呈現**（修正前後各自都算了兩種），不拿不同口徑硬比：
 
 | | 限定週五（主口徑） | 混合星期別（舊口徑） |
 |---|---|---|
 | 修正前（proxy） | 1.168× / p=0.0409 / n=239 | 1.168× / p=0.0335 / n=254（文章當初引用的） |
 | 修正後（官方） | **1.189× / p=0.0209 / n=237** | 1.177× / p=0.0257 / n=253（DIAGNOSTIC ONLY） |
 
 **兩種口徑、修正前後，四格全部顯著** —— 「顯著→不顯著」的翻轉在任何一種讀法下都不成立。
 
 ## 結果：逐項前後對照
 
 每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
 而中位數與勝率在底下已經移位。
 
 兩欄使用**相同口徑**，所以差異可歸因於日期本身，不是口徑改動。
 
 | 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
 |---|---|---|---|
 | 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
 | NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.108× (p=0.112, NS) | 數值微調 |
 | ↳ 中位數比 / 勝率 | 1.190× / 0.555 | 1.192× / 0.561 | 數值微調 |
 | 週五 NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0409, **顯著**, n=239) | 1.189× (p=0.0209, **仍顯著**, n=237) | 數值微調 |
 | ↳ 中位數比 / 勝率 | 1.198× / 0.557 | 1.219× / 0.570 | 數值微調 |
 | VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
 | ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
 | 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
 | ↳ Spearman | 0.377 | 0.346 | 數值微調 |
 | VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |
 
 **6 項受稽核宣稱中，0 項結論翻轉。**
 
-**方向性主結論不變**：決定 NFP 日波動的是**進場當下的 VIX 體制**（2.03 倍、p≈4.6e-9），
-遠大於 NFP 這個日曆事件本身。
+**方向性主結論不變**：以進場 VIX 中位數分組，兩組 NFP 日的波動差距（2.03 倍、p≈4.6e-9）
+在數值上遠大於 NFP 對基準的差距（1.11 / 1.19 倍）。
+
+**這句話的邊界（不要讀過頭）**：這是**條件關聯**，不是因果識別。本實驗**沒有**正式檢定
+「2.03 倍顯著大於 1.19 倍」—— 兩者的樣本與對照組都不同，並排只是量級對照，不是統計比較。
+也不能反推「所以不是 NFP 本身」：平均差檢定沒拒絕不是零效果的證據，而排序檢定其實拒絕了
+（見上）。VIX 分組同時也是**事後**中位數分割，本身帶有樣本內成分。
 
 ### 關於「不顯著」的措辭
 
 修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
 Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
 陳述都綁定它自己的檢定：
 
 - Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
 - Welch 平均差（**週五公布的 NFP** 對非 NFP 週五）：1.189×，p=0.0209，**拒絕**
   —— 條件於週五，不是關於 NFP 一般而言
 - Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019，**拒絕**
 
 平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
 排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。
 
 ## 產出檔案
 
 | 檔案 | 內容 |
 |---|---|
 | `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
 | `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
 | `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
 | `k528_nfp_official_dates_results.json` | 逐項前後對照 + 換掉的日期 + 文章更正替換清單 |
 | `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
 | `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
 | `review_verdict_v3.json` / `codex_review_v3.md` | Codex 三審裁決與全文 |
 
 ## 線上文章更正（`mile_35eef830`）
 
 ### ⚠️ 原 18 條更正清單已全數作廢
 
 原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
 改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
 撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
 `article_correction.supersedes`。
@@ -179,62 +184,81 @@ uv run python experiments/k528/build_article_correction.py --apply    # 寫入 +
 與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
 因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。
 
 ## 防迴歸
 
 事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
 
 - `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
   212 個日期共通、結果檔宣告 fail-closed
 - `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住 v2 BLOCKER**：
   對 artifact 斷言六個 off-cycle 日期不在事件集合、六個正式發布日在。對 artifact 而非
   只對 accessor 斷言，因為「accessor 是對的」不能證明「出貨的結果用了它」
 - `TestControlGroupHasNoNfpDays` — 釘住控制組不含任何已映射 NFP session
 - `TestCalendarFailClosedCannotBeBypassed` — 逐條釘住三審找到的繞過路徑：較早的
   off-cycle、選擇非最早、跨度內缺月、allowlist 濫用；外加一個**必須通過**的乾淨日曆
   （只會拒絕的 guard 和永不拒絕的一樣沒用）
 - `TestFridayEstimandIsScopedHonestly` — 釘住 conditional estimand 有標示、
   非中性排除有揭露、排除筆數與 weekday 分解一致（結果檔曾經散文寫 11、資料寫 16）
 - `TestProxyMutationIsCaught` — mutation test：proxy 日曆餵給 guard 必須被拒；
   只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆
 
 accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
 `tests/test_event_dates_real_raw_response.py`（未經編輯的 ALFRED 日期清單 + mutation 檢查）。
 後者的 scope 有明寫：它釘的是 `_fetch` 的**回傳值**（原樣、未去重），不是完整 HTTP
 response body，所以 `_fetch` 自身的 schema 破壞不在覆蓋範圍內。
 
 Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
 由綠轉紅（`2006-05-08 != 2006-05-05`），還原後 99 passed。沒被實際觸發過的 gate 不算 gate。
 
 ## 主腳本的 fail-closed 面
 
 **日曆完整性**（`check_calendar_is_complete`）**同時驗證 raw feed 與 accessor 的選擇**。
 只驗證 accessor 的**輸出**是行不通的：accessor 在把資料交出來之前就已經把每個月收斂成一個
 日期，等到能檢查輸出的時候，同月歧義早就被（可能錯誤地）默默解決掉了。四道關卡：
 
-1. 同月兩筆間隔 < 3 天 → raise（修訂是報告後**數週**才報，不是數天；這種形狀代表 feed
-   變了或 release id 開始夾帶別的東西，拒絕猜測）
-2. 選到的不是該月最早一筆 → raise（這正是 v2 BLOCKER 的形狀）
-3. 觀測跨度內缺月 → raise。錨定在**實際觀測跨度**而非 `[start, end]`，移除了舊版
+0. 選擇本身要 well-formed：同一個月被選了兩次 → raise；選出來的月份/日期不存在於 raw
+   feed → raise（否則後面用 `dict` 建 month→date 對照時，重複的月份會被靜默蓋掉，
+   剛好蓋掉我們要找的東西）
+1. 選到的不是該月最早一筆 → raise（這正是 v2 BLOCKER 的形狀）
+2. 任何同月多筆的月份**必須列在 `REVIEWED_MULTI_ENTRY_MONTHS`**，且選到的日期要與人工
+   核對過的答案一致 → 否則 raise（理由見下方「殘留限制」）
+3. 觀測跨度**沒有覆蓋到請求視窗**（頭尾任一端短少 > 70 天）→ raise。只檢查跨度「內部」
+   的缺口抓不到截斷：feed 提早結束的話，跨度會跟著縮短，於是看起來什麼都不缺
+4. 觀測跨度內缺月 → raise。錨定在實際觀測跨度而非 `[start, end]`，移除了舊版
    「首尾月無條件豁免」的漏洞（完整的首月照樣可以無聲消失）
-4. `KNOWN_MISSING_MONTHS` 宣稱的缺口，會回頭去 raw feed **驗證它真的是缺口** → 有資料就
+5. `KNOWN_MISSING_MONTHS` 宣稱的缺口，會回頭去 raw feed **驗證它真的是缺口** → 有資料就
    raise。沒有這一關，allowlist 就只是「讓失敗的檢查通過」的另一個名字
 
+**一個被自己的資料推翻的設計**（留著當紀錄）：這裡原本還有一關「同月兩筆間隔 < 3 天就
+視為無法辨識」，理由是「修訂都是報告後數週才報」。拿真實 feed 一跑就被推翻 —— 六個真實
+同月多筆月份裡有**三個**（2006-05、2013-05、2020-05）剛好間隔 **3 天**。真實資料橫跨在
+自己設的門檻上，那就不是安全檢查，是製造信心的旋鈕，因此整關移除。
+`tests/...::test_real_multi_entry_gaps_are_too_small_for_a_gap_rule` 把這個事實釘住，
+以免有人再發明一次同樣的規則。
+
 已知的真實缺口只有 2025-10（政府關門），每筆都要附理由字串。
 
+**殘留限制（明講，不假裝已完全關上）**：同月選擇用的「取最早一筆」是**啟發式**。它對目前
+查過的每一個案例都對，但它無法區分「比正式報告**更早**歸檔的 off-cycle 項目」與報告本身
+—— 單靠日期不可能分辨。因此規則照跑，但**額外**要求每個同月多筆的月份都出現在
+`REVIEWED_MULTI_ENTRY_MONTHS`（六個月份逐一對照 BLS news-release archive 驗證過）。
+新出現的同月多筆月份會**讓整個 run 失敗**，而不是被這支腳本自行假設掉。
+第 4、第 3 兩關是三審 round-2 進行期間自查補上的。
+
 **事件日→交易日對映**：一對一完整性斷言。樣本內發布日找不到三日內交易日 → raise；
 兩個發布日映射到同一個 session → raise（原本的 `set()` 去重會把這件事藏起來並靜默減少
 事件數）。窗口邊界排除改為明確記錄在 `sample.event_mapping_audit`，不再靜默 `continue`。
 
 **控制組不含任何 NFP session**：對照組排除**全部 254 個**已映射 NFP session，不只是通過
 事件窗篩選的 253 個。因窗口不足被排除的 `2005-01-07` 仍然是真實的 NFP 日，把它留在對照組
 就是本實驗存在的理由（「把真的事件日丟進對照組」）的 1/253 版本。三審 Codex 與本輪自查
 獨立發現同一件事。
 
 **原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`。
 
 ## 參考
 
 - K1442 事件日期稽核（發現 proxy bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
 - `docs/error_log.md` 2026-07-12 CPI 事件研究發布日條目（同一 bug class 的前例）
 - Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
 - K513：先前的 FOMC/NFP/CPI 事件研究
diff --git a/experiments/k528/k528_nfp_event_study.py b/experiments/k528/k528_nfp_event_study.py
index 3a0338a4c..278400b74 100644
--- a/experiments/k528/k528_nfp_event_study.py
+++ b/experiments/k528/k528_nfp_event_study.py
@@ -48,192 +48,285 @@ Date: 2026-03-27 (corrected 2026-07-19)
 
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
 
 from volpred.data.event_dates import RELEASE_IDS, _fetch, nfp_release_dates
 
 warnings.filterwarnings("ignore")
 
 SAMPLE_START = "2005-01-01"
 SAMPLE_END = "2026-03-27"
 
 # Months for which BLS published no Employment Situation report at all. Each
 # entry needs a documented reason, and check_calendar_is_complete VERIFIES the
 # claim against the raw feed before honouring it -- an allowlist that is taken
 # on faith is just a way to make a failing check pass, which is the failure mode
 # this whole experiment exists to document.
 KNOWN_MISSING_MONTHS: dict[str, str] = {
     "2025-10": (
         "Federal government shutdown. ALFRED shows no release id 50 entry between "
         "2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed "
         "September report landed on 11-20. Same shutdown that cancelled the Oct-2025 "
         "CPI release described in volpred/data/event_dates.py. The first-Friday proxy "
         "INVENTED an event here -- that phantom is one of the reasons for this rerun."
     ),
 }
 
-# Two same-month entries closer together than this cannot be told apart as
-# "regular report" vs "off-cycle revision" by date order alone, so the run
-# refuses to guess. Revisions are filed weeks after the report, not days.
-AMBIGUOUS_SAME_MONTH_GAP_DAYS = 3
+# NOTE: an earlier version of this file gated same-month ambiguity on a minimum
+# day-gap, on the premise that "revisions are filed weeks after the report, not
+# days". Running it against the real feed falsified that premise immediately:
+# three of the six genuine multi-entry months (2006-05, 2013-05, 2020-05) are
+# exactly 3 days apart. A threshold the real data straddles is not a safety
+# check, it is a knob that manufactures confidence, so it is gone. The reviewed
+# allowlist below is the actual control, and unlike a gap rule it is verifiable.
+
+# The months where ALFRED returns two release-id-50 entries, with the entry that
+# is the actual Employment Situation report. Verified individually against the
+# BLS news-release archive (bls.gov/news.release/archives/empsit_<MMDDYYYY>.htm).
+#
+# Why an explicit reviewed list rather than a rule: "earliest entry in the month"
+# is right for every case we have checked, but it is a HEURISTIC, and it fails
+# silently if an off-cycle item is ever filed BEFORE the report. There is no way
+# to tell those apart from dates alone. So the rule still runs, and on top of it
+# any month with multiple entries must appear here -- a new multi-entry month is
+# something a human has to look at, not something this script gets to assume.
+REVIEWED_MULTI_ENTRY_MONTHS: dict[str, str] = {
+    "2006-05": "2006-05-05",
+    "2012-12": "2012-12-07",
+    "2013-05": "2013-05-03",
+    "2020-05": "2020-05-08",
+    "2024-01": "2024-01-05",
+    "2024-08": "2024-08-02",
+}
+
+# How far the observed calendar may fall short of the requested window before the
+# run treats it as truncated. One monthly cycle plus slack; a feed that stops
+# early otherwise shrinks the "observed span" it is checked against and passes.
+MAX_WINDOW_SHORTFALL_DAYS = 70
 
 
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
 def check_calendar_is_complete(selected, raw, start, end):
     """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
 
     "Did the call succeed?" is the wrong question. A monthly release calendar
     that silently lost 2019 still returns a non-empty list, still produces
     event windows, still renders.
 
     This validates the RAW feed as well as the accessor's per-month selection.
     Validating only the selection cannot work: the accessor collapses each month
     to one date before this function ever sees it, so a same-month ambiguity is
     already resolved -- silently, and possibly wrongly -- by the time a check on
     the output could look for it. That is precisely how the k528 v2 BLOCKER got
     through (Codex v3 finding 3).
 
     Four ways the input can be wrong without being empty, all of which raise:
       1. a month has two entries too close together to tell report from revision
       2. the selection is not the earliest entry of its month
       3. a month is missing from the observed span
       4. a month is claimed as a known hole but the raw feed actually has data
     """
     sel = [pd.Timestamp(d) for d in selected]
     sel_months = [d.strftime("%Y-%m") for d in sel]
 
     raw_by_month: dict[str, list[pd.Timestamp]] = {}
     for d in raw:
         ts = pd.Timestamp(d)
         raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
     for v in raw_by_month.values():
         v.sort()
 
-    # 1 + 2: same-month resolution must be unambiguous AND actually taken.
-    ambiguous, mis_selected = [], []
+    # 0: the selection itself must be well-formed before anything is inferred
+    # from it. Building a month->date dict first would silently keep only the
+    # last of a duplicated month and hide exactly what we are looking for.
+    sel_month_counts: dict[str, int] = {}
+    for m in sel_months:
+        sel_month_counts[m] = sel_month_counts.get(m, 0) + 1
+    sel_dupes = sorted(m for m, c in sel_month_counts.items() if c > 1)
+    if sel_dupes:
+        raise RuntimeError(
+            f"selected calendar has more than one entry for {sel_dupes}. The Employment "
+            "Situation is monthly; a duplicated month means the accessor stopped collapsing."
+        )
+    invented = sorted(set(sel_months) - set(raw_by_month))
+    if invented:
+        raise RuntimeError(
+            f"selected calendar contains month(s) absent from the raw feed: {invented}. "
+            "The selection must be a subset of what the source actually published."
+        )
+    off_feed = sorted(str(d.date()) for d in sel if d not in raw_by_month.get(d.strftime("%Y-%m"), []))
+    if off_feed:
+        raise RuntimeError(
+            f"selected dates that do not appear in the raw feed at all: {off_feed}."
+        )
+
+    # 1: the accessor's per-month choice must be the earliest entry.
+    mis_selected = []
     sel_by_month = dict(zip(sel_months, sel))
     for month, entries in raw_by_month.items():
-        if len(entries) > 1:
-            gap = (entries[1] - entries[0]).days
-            if gap < AMBIGUOUS_SAME_MONTH_GAP_DAYS:
-                ambiguous.append(f"{month}: {entries[0].date()} vs {entries[1].date()} ({gap}d apart)")
         if month in sel_by_month and sel_by_month[month] != entries[0]:
             mis_selected.append(
                 f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
             )
-    if ambiguous:
-        raise RuntimeError(
-            f"{len(ambiguous)} month(s) carry two release entries too close together to "
-            f"identify the Employment Situation report by date order: {ambiguous}. "
-            "Revisions are filed weeks after the report, not days -- this shape means the "
-            "feed changed or the release id is carrying something new. Refusing to guess."
-        )
     if mis_selected:
         raise RuntimeError(
             f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
             f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
             "monthly report -- selecting it is the k528 v2 BLOCKER."
         )
 
-    # 3: no month may vanish from the observed span. Anchoring on the observed
-    # span rather than [start, end] removes the endpoint fudge that used to
-    # exempt the first and last month unconditionally (Codex v3 finding 3).
+    # "Earliest wins" is a heuristic and cannot survive an off-cycle item filed
+    # BEFORE the report. Every multi-entry month therefore has to be one a human
+    # checked against the BLS archive, and the checked answer has to match.
+    multi = {m: v for m, v in raw_by_month.items() if len(v) > 1}
+    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
+    if unreviewed:
+        raise RuntimeError(
+            f"{len(unreviewed)} month(s) carry multiple release entries but have never been "
+            f"checked against the BLS archive: "
+            f"{ {m: [str(d.date()) for d in multi[m]] for m in unreviewed} }. "
+            "Selecting the earliest is only a heuristic; verify which entry is the Employment "
+            "Situation report at bls.gov/news.release/archives/ and add it to "
+            "REVIEWED_MULTI_ENTRY_MONTHS."
+        )
+    contradicted = {
+        m: {"selected": str(sel_by_month[m].date()), "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]}
+        for m in multi
+        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]
+    }
+    if contradicted:
+        raise RuntimeError(
+            f"selection contradicts the human-verified release date in {contradicted}. "
+            "Either the feed changed or the accessor regressed; do not proceed on the guess."
+        )
+
+    # 3a: the observed span must actually cover what was asked for. Checking only
+    # for gaps INSIDE the observed span cannot catch truncation -- if the feed
+    # stops early, the span shrinks with it and nothing looks missing. Found by
+    # self-audit while Codex v3 round-2 was running.
+    want_start, want_end = pd.Timestamp(start), pd.Timestamp(end)
+    head_short = (min(sel) - want_start).days
+    tail_short = (want_end - max(sel)).days
+    if head_short > MAX_WINDOW_SHORTFALL_DAYS or tail_short > MAX_WINDOW_SHORTFALL_DAYS:
+        raise RuntimeError(
+            f"official NFP calendar does not cover the requested window "
+            f"{start}..{end}: first release {min(sel).date()} ({head_short}d in), "
+            f"last release {max(sel).date()} ({tail_short}d short of the end). "
+            f"Tolerance is {MAX_WINDOW_SHORTFALL_DAYS}d. A truncated feed silently "
+            "shortens the sample while every printed count still agrees with itself."
+        )
+
+    # 3b: no month may vanish from inside the observed span.
     span = {
         p.strftime("%Y-%m")
         for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
     }
     missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
     if missing:
         raise RuntimeError(
             f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
             f"span: {missing}. A partial calendar dumps real event days into the control "
             "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
             "reason (e.g. a cancelled release), never to make this check pass."
         )
 
     # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
     # allowlist is a bypass: any month could be declared 'known missing' and the
     # check would stop looking at it.
     bogus = sorted(m for m in KNOWN_MISSING_MONTHS if m in span and raw_by_month.get(m))
     if bogus:
         raise RuntimeError(
             f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
             f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
             "The allowlist is for real cancellations, not for silencing a selection bug."
         )
 
     return {
         "n_months_in_span": len(span),
         "n_raw_entries": len(raw),
-        "months_with_multiple_raw_entries": sorted(m for m, v in raw_by_month.items() if len(v) > 1),
+        "months_with_multiple_raw_entries": sorted(multi),
+        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
         "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
-        "ambiguity_gap_threshold_days": AMBIGUOUS_SAME_MONTH_GAP_DAYS,
+        "window_coverage": {
+            "requested": f"{start}..{end}",
+            "observed": f"{min(sel).date()}..{max(sel).date()}",
+            "head_shortfall_days": int(head_short),
+            "tail_shortfall_days": int(tail_short),
+            "tolerance_days": MAX_WINDOW_SHORTFALL_DAYS,
+        },
+        "residual_limitation": (
+            "Same-month selection uses 'earliest wins', which is a heuristic. It cannot "
+            "distinguish an off-cycle item filed BEFORE the report from the report itself, "
+            "so every multi-entry month must additionally appear in "
+            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A "
+            "new multi-entry month fails the run rather than being assumed."
+        ),
     }
 
 
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
     # Pull the unselected feed as well: the accessor collapses each month to one
     # date, so the only place a same-month ambiguity is still visible is here.
     raw = _fetch(RELEASE_IDS["NFP_US"], start, end)
     completeness = check_calendar_is_complete(dates, raw, start, end)
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
@@ -716,153 +809,205 @@ print(f"    → Non-significance of a mean test is not evidence of no effect")
 
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
-proxy_non_nfp = spy[~spy.index.isin(set(proxy_event_dates))]
+
+# The archive holds the proxy run's ANALYSED events, which is not the same as
+# its NFP sessions: the proxy also had a January-2005 event that its own
+# window-buffer dropped, and leaving that day in the proxy control group is the
+# identical leak just repaired on the official side (Codex v3 round-2 BLOCKER 1).
+# Reconstructing it needs the first-Friday rule for exactly the months the
+# archive does not cover. That is legitimate here and only here: the audit's job
+# IS to reconstruct what the superseded run did. It is not reintroduced as a
+# data source -- every analysed date still comes from the archive.
+_archive_months = {d.strftime("%Y-%m") for d in proxy_event_dates}
+_sample_months = [
+    p.strftime("%Y-%m")
+    for p in pd.period_range(start=pd.Timestamp(SAMPLE_START), end=pd.Timestamp(SAMPLE_END), freq="M")
+]
+_proxy_extra_sessions = []
+for _m in _sample_months:
+    if _m in _archive_months:
+        continue
+    _y, _mm = int(_m[:4]), int(_m[5:])
+    _first = pd.Timestamp(year=_y, month=_mm, day=1)
+    _ff = _first + pd.Timedelta(days=(4 - _first.weekday()) % 7)   # first Friday
+    _cand = trading_dates[(trading_dates >= _ff) & (trading_dates <= _ff + pd.Timedelta(days=3))]
+    if len(_cand):
+        _proxy_extra_sessions.append(_cand[0])
+
+proxy_all_sessions = set(proxy_event_dates) | set(_proxy_extra_sessions)
+# The reconstruction must only ADD window-dropped months, never move an analysed
+# one; and the months it adds must be exactly those the archive is missing.
+if not set(proxy_event_dates) <= proxy_all_sessions:
+    raise AssertionError("proxy session reconstruction dropped an archived event")
+if len(proxy_all_sessions) != len(proxy_event_dates) + len(_proxy_extra_sessions):
+    raise AssertionError("proxy session reconstruction collided with an archived event")
+proxy_non_nfp = spy[~spy.index.isin(proxy_all_sessions)]
 proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
 proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
 
+# Two proxy control groups, deliberately, because they answer different questions:
+#   _archive  -- excludes only the archive's ANALYSED events. Reproduces the
+#                published proxy-era means, which is how we verify the
+#                reconstruction is reading the archive correctly.
+#   (above)   -- also excludes the proxy's window-dropped session. Leak-free, so
+#                it is what the before/after comparison uses.
+# Keeping only the first would carry the leak into the audit; keeping only the
+# second would silently discard the faithfulness check.
+proxy_non_nfp_archive = spy[~spy.index.isin(set(proxy_event_dates))]
+proxy_non_nfp_abs_archive = proxy_non_nfp_archive["AbsReturn"].values
+_leak_sessions = sorted(str(d.date()) for d in _proxy_extra_sessions)
+if len(proxy_non_nfp_archive) - len(proxy_non_nfp) != len(_proxy_extra_sessions):
+    raise AssertionError("proxy control groups differ by something other than the reconstructed sessions")
+
 # The proxy calendar was all-Friday by construction, but 15 of its 254 events
 # mapped to a Monday because the first Friday was a market holiday. So the
 # proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
 # rebuild the proxy side under the SAME estimand the corrected run uses
 # (Friday events only) rather than comparing a mixed `before` against a
 # restricted `after` and calling the difference a correction effect.
 _p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
 proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
 _p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
 proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
 
 _p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
                        for e in proxy_events])
 _p_thr = proxy["regime_analysis"]["vix_median_split"]
 proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
 proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
 
 # Sanity: the rebuilt means must reproduce the archived means, otherwise the
-# reconstruction is wrong and its medians cannot be trusted either.
+# reconstruction is wrong and its medians cannot be trusted either. The baseline
+# is checked against the ARCHIVE'S control definition -- the leak-free one is a
+# deliberate departure from what was published, so holding it to the published
+# value would just re-import the leak.
 for _label, _rebuilt, _archived in (
     ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
-    ("baseline mean", proxy_non_nfp_abs.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
+    ("baseline mean", proxy_non_nfp_abs_archive.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
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
+print(f"  proxy control group additionally excludes {len(_proxy_extra_sessions)} "
+      f"window-dropped NFP session(s): {_leak_sessions}")
 
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
         # Same estimand as the `after` column: Friday events only.
         "mean_ratio": proxy_ratio_fri_restricted,
         "p_value": float(_p_p_fri),
         "significant_5pct": bool(_p_p_fri < 0.05),
         "n": int(len(proxy_nfp_friday_abs)),
         "nfp_days_on_friday": int((_p_weekday == 4).sum()),
         "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
         "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
+        "n_control_friday": int(len(proxy_fri_abs)),
         "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
         "as_published_mixed_weekday": {
             "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
             "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
             "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
             "n": proxy["sample"]["total_nfp_events"],
             "note": (
                 "what the proxy run actually published: all 254 events (239 Friday, "
                 "15 Monday) against non-NFP Fridays. This is the number the article "
                 "quoted, so it is kept, but it is NOT the like-for-like comparison "
                 "against the corrected column."
             ),
         },
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
     note="Two things changed here and they are separated rather than conflated. "
          "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
          "event group is a weekday mixture while the control group is pure "
          "Friday, so the test now restricts the event group to Friday releases. "
@@ -1004,70 +1149,77 @@ for key, item in audit_items.items():
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
+        # Recorded independently so the control-group invariant
+        # (controls == total - mapped NFP sessions) is checkable rather than an
+        # algebraic identity between two numbers derived from each other.
+        "total_trading_days": int(len(spy)),
+        "control_group_excludes_all_nfp_sessions": bool(
+            len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask])) == 0
+        ),
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
                 "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event "
                 "group is restricted to NFP releases that trade on a Friday, and the "
                 f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
                 "than compared against a pure-Friday control group."
             ),
             "claim_scope": (
                 "This identifies the effect of an NFP release ON A FRIDAY. It does not "
                 "license a statement about NFP releases in general -- the excluded "
                 "non-Friday events are quieter, so the restriction raises the ratio "
                 "relative to the mixed-weekday spec. Any prose quoting this number must "
                 "say 'Friday NFP', not 'NFP'."
             ),
             "restriction_is_not_neutral": {
                 "excluded_mean_abs_return": float(nfp_nonfriday_abs.mean()) if len(nfp_nonfriday_abs) else None,
                 "friday_mean_abs_return": float(nfp_friday_abs.mean()),
diff --git a/tests/test_nfp_official_release_dates.py b/tests/test_nfp_official_release_dates.py
index 8f3a091ee..24836f326 100644
--- a/tests/test_nfp_official_release_dates.py
+++ b/tests/test_nfp_official_release_dates.py
@@ -472,157 +472,270 @@ class TestProxyMutationIsCaught:
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
 
 
 # ---------------------------------------------------------------------------
 # Holes found by Codex v3 against commit 6fd281901. Each of these shipped once
 # with a green suite, so each gets an assertion rather than a comment.
 # ---------------------------------------------------------------------------
 
 
 def _k528_module():
-    """Load the k528 script's pure helpers without running the analysis body."""
+    """Load the k528 script's functions and literal constants without running
+    the analysis body (which downloads data and would need a live API key).
+
+    Constants are selected by "is it a literal?", not by a hand-maintained name
+    list. The name-list version silently dropped every constant added after it
+    was written, and a helper that quietly omits what it is supposed to load
+    makes the tests exercise something other than the production code path.
+    """
     import ast
     import types
 
+    def _is_literal_assignment(node):
+        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
+            return False
+        try:
+            ast.literal_eval(node.value)
+        except (ValueError, SyntaxError):
+            return False  # silent-ok: "is this a literal?" probe; a non-literal is the expected answer, not a failure
+        return True
+
     src = K528_PY.read_text(encoding="utf-8")
     tree = ast.parse(src)
     keep = [
         n for n in tree.body
-        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef))
-        or (isinstance(n, ast.AnnAssign) and getattr(n.target, "id", "") == "KNOWN_MISSING_MONTHS")
-        or (isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") in (
-            "SAMPLE_START", "SAMPLE_END", "AMBIGUOUS_SAME_MONTH_GAP_DAYS"))
+        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
+        or _is_literal_assignment(n)
     ]
     mod = types.ModuleType("k528_helpers")
     exec(compile(ast.Module(body=keep, type_ignores=[]), "k528", "exec"), mod.__dict__)
+    # Guard the loader: if this ever silently stops loading what the tests need,
+    # the tests below would pass vacuously or error confusingly.
+    for required in ("check_calendar_is_complete", "KNOWN_MISSING_MONTHS",
+                     "REVIEWED_MULTI_ENTRY_MONTHS", "MAX_WINDOW_SHORTFALL_DAYS"):
+        assert hasattr(mod, required), f"_k528_module failed to load {required}"
     return mod
 
 
 class TestControlGroupHasNoNfpDays:
     """A real NFP session sitting in the control group is the exact failure this
     experiment exists to document -- it just happened at 1/253 scale instead of
     46/254, via an event dropped for lacking a pre-window but never removed from
     the baseline."""
 
     def test_every_mapped_nfp_session_is_excluded_from_the_control_group(self):
+        """Assert against an INDEPENDENTLY recorded total.
+
+        The first version of this test defined total = controls + mapped and
+        then asserted controls == total - mapped, which is an algebraic identity
+        that passes for any value of controls -- including the leaking 5087 it
+        was written to catch. A test that cannot fail is worse than no test: it
+        reads as coverage. (Codex v3 round-2 finding 3.)
+        """
         sample = _load_k528(K528_RESULTS)["sample"]
         audit = sample["event_mapping_audit"]
-        total_sessions = sample["non_nfp_trading_days"] + audit["n_mapped_to_sessions"]
-        assert sample["non_nfp_trading_days"] == total_sessions - audit["n_mapped_to_sessions"], (
-            "control group size must exclude ALL mapped NFP sessions, not just the "
-            "ones that survived the event-window filter"
+        total = sample["total_trading_days"]
+        assert total == 5340, "pinned SPY session count for this sample window"
+        assert sample["non_nfp_trading_days"] == total - audit["n_mapped_to_sessions"] == 5086, (
+            "control group must exclude ALL mapped NFP sessions, not just the ones "
+            "that survived the event-window filter (5087 was the leaking value)"
+        )
+        assert sample["control_group_excludes_all_nfp_sessions"] is True
+
+    def test_proxy_side_control_group_is_also_clean(self):
+        """The same leak existed on the proxy side of the before/after audit:
+        the archive holds the proxy's ANALYSED events, not its NFP sessions."""
+        audit = _load_k528(K528_AUDIT)
+        before = audit["items"]["vol_ratio_vs_friday"]["before"]
+        assert before["n_control_friday"] == 832, (
+            "proxy Friday control count must exclude the proxy's own "
+            "window-dropped January-2005 session"
         )
 
     def test_window_excluded_event_is_not_silently_analysed_or_kept_as_control(self):
         audit = _load_k528(K528_RESULTS)["sample"]["event_mapping_audit"]
         assert audit["n_valid_events"] + audit["n_excluded_for_window_buffer"] == \
             audit["n_mapped_to_sessions"]
         assert audit["window_excluded_dates"], "the partition must name what it dropped"
 
 
 class TestCalendarFailClosedCannotBeBypassed:
     """Codex v3 finding 3: validating only the accessor's OUTPUT cannot work,
     because the accessor collapses each month to one date before any check on
     the output can look for an ambiguity."""
 
     @pytest.fixture
     def check(self):
         return _k528_module().check_calendar_is_complete
 
-    def test_off_cycle_entry_earlier_in_the_month_is_ambiguous_not_silently_picked(self, check):
+    def test_off_cycle_entry_earlier_in_the_month_is_refused_not_silently_picked(self, check):
         """The bypass: an off-cycle entry filed EARLIER than the report. A
-        per-month min() takes it without complaint and the cadence still passes."""
-        with pytest.raises(RuntimeError, match="too close together"):
+        per-month min() takes it without complaint and the cadence still passes.
+        Only the reviewed-month allowlist catches this -- a day-gap threshold
+        cannot, because three of the six real cases are 3 days apart."""
+        with pytest.raises(RuntimeError, match="never been"):
             check(
                 pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
                 ["2024-01-05", "2024-02-01", "2024-02-02", "2024-03-08"],
-                "2024-01-01", "2024-12-31",
+                "2024-01-01", "2024-03-31",
             )
 
+    def test_real_multi_entry_gaps_are_too_small_for_a_gap_rule(self):
+        """Pin the fact that killed the gap heuristic: 2006-05, 2013-05 and
+        2020-05 have the revision exactly 3 days after the report. Any future
+        'revisions are filed weeks later' rule is wrong on the real feed."""
+        import json
+
+        raw = json.loads(
+            (REPO_ROOT / "tests" / "fixtures" / "fred_release_50_nfp_raw_20260719.json")
+            .read_text(encoding="utf-8")
+        )["release_dates"]
+        by_month = {}
+        for d in raw:
+            by_month.setdefault(d[:7], []).append(d)
+        gaps = {
+            m: (pd.Timestamp(sorted(v)[1]) - pd.Timestamp(sorted(v)[0])).days
+            for m, v in by_month.items() if len(v) > 1
+        }
+        assert min(gaps.values()) == 3, gaps
+        assert sorted(m for m, g in gaps.items() if g == 3) == ["2006-05", "2013-05", "2020-05"]
+
     def test_selection_that_is_not_the_earliest_entry_fails(self, check):
         with pytest.raises(RuntimeError, match="did not select the earliest"):
             check(
                 pd.to_datetime(["2024-01-05", "2024-02-09", "2024-03-08"]),
                 ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
-                "2024-01-01", "2024-12-31",
+                "2024-01-01", "2024-03-31",
             )
 
     def test_missing_month_inside_the_observed_span_fails(self, check):
         """The old check exempted the first and last month unconditionally, so a
         genuinely complete endpoint month could vanish for free."""
         with pytest.raises(RuntimeError, match="missing 1 month"):
             check(
                 pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
                 ["2024-01-05", "2024-02-02", "2024-04-05"],
-                "2024-01-01", "2024-12-31",
+                "2024-01-01", "2024-04-30",
             )
 
     def test_allowlist_cannot_silence_a_month_that_has_data(self, check):
         """KNOWN_MISSING_MONTHS is for real cancellations. If it is taken on
         faith it is just a way to make a failing check pass."""
         mod = _k528_module()
         mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
         with pytest.raises(RuntimeError, match="claims"):
             mod.check_calendar_is_complete(
                 pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
                 ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
-                "2024-01-01", "2024-12-31",
+                "2024-01-01", "2024-04-30",
             )
 
-    def test_a_legitimate_calendar_with_a_normal_revision_still_passes(self, check):
+    def test_truncated_feed_cannot_hide_behind_its_own_shrunken_span(self, check):
+        """Anchoring the gap check on the OBSERVED span cannot catch truncation:
+        if the feed stops early the span shrinks with it and nothing looks
+        missing. Found by self-audit, not by a reviewer."""
+        dates = ["2024-01-05", "2024-02-02", "2024-03-08"]
+        with pytest.raises(RuntimeError, match="does not cover"):
+            check(pd.to_datetime(dates), dates, "2024-01-01", "2024-12-31")
+
+    def test_unreviewed_multi_entry_month_is_refused_not_guessed(self, check):
+        """'Earliest wins' cannot distinguish an off-cycle item filed BEFORE the
+        report from the report. A new multi-entry month must stop the run."""
+        with pytest.raises(RuntimeError, match="never been"):
+            check(
+                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
+                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
+                "2024-01-01", "2024-03-31",
+            )
+
+    def test_selection_contradicting_the_human_verified_date_fails(self):
+        mod = _k528_module()
+        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = "2024-02-06"
+        with pytest.raises(RuntimeError, match="contradicts"):
+            mod.check_calendar_is_complete(
+                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
+                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
+                "2024-01-01", "2024-03-31",
+            )
+
+    def test_a_reviewed_month_with_a_normal_revision_still_passes(self):
         """The other half: a guard that rejects everything is as useless as one
-        that rejects nothing. A revision filed a week later is normal."""
-        out = check(
+        that rejects nothing. A revision filed a week later, in a month someone
+        has checked against the BLS archive, must go through."""
+        mod = _k528_module()
+        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = "2024-02-02"
+        out = mod.check_calendar_is_complete(
             pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
             ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
-            "2024-01-01", "2024-12-31",
+            "2024-01-01", "2024-03-31",
         )
         assert out["months_with_multiple_raw_entries"] == ["2024-02"]
 
+    def test_the_six_real_multi_entry_months_pass_on_the_real_feed(self):
+        """The strongest negative control available: the actual 264-entry ALFRED
+        feed, whose six duplicate months are exactly the reviewed ones."""
+        import json
+
+        mod = _k528_module()
+        raw = json.loads(
+            (REPO_ROOT / "tests" / "fixtures" / "fred_release_50_nfp_raw_20260719.json")
+            .read_text(encoding="utf-8")
+        )["release_dates"]
+        by_month = {}
+        for d in raw:
+            by_month.setdefault(d[:7], []).append(d)
+        sel = sorted(min(v) for v in by_month.values())
+        out = mod.check_calendar_is_complete(
+            pd.to_datetime(sel), raw, "2005-01-01", "2026-07-19"
+        )
+        assert out["months_with_multiple_raw_entries"] == sorted(
+            mod.REVIEWED_MULTI_ENTRY_MONTHS
+        )
+
 
 class TestFridayEstimandIsScopedHonestly:
     """Codex v3 finding 4: restricting to Friday is a legitimate conditional
     estimand, but it stops supporting statements about NFP releases in general,
     and the restriction is not a neutral sample deletion."""
 
     def test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality(self):
         b = _load_k528(K528_RESULTS)["statistical_tests"]["B_nfp_vs_friday"]
         assert "CONDITIONAL ON FRIDAY" in b["estimand"]
         assert "Friday NFP" in b["claim_scope"]
         nn = b["restriction_is_not_neutral"]
         assert nn["excluded_are_quieter_by_pct"] > 0, (
             "if the excluded events are quieter, the restriction RAISES the ratio "
             "and that must be stated, not discovered by a reviewer"
         )
 
     def test_excluded_count_matches_the_weekday_breakdown(self):
         """The results file once said 11 in prose and 16 in data."""
         results = _load_k528(K528_RESULTS)
         b = results["statistical_tests"]["B_nfp_vs_friday"]
         non_friday = sum(1 for e in results["event_data"] if e["weekday"] != 4)
         assert b["excluded_non_friday_events"]["n"] == non_friday == 16
         assert str(non_friday) in b["estimand"]

codex
初步看見 remediation 的主要結構確實進了固定 commit，但 README 的完整性函式 docstring 仍描述舊的「四種錯誤」，與實際新增關卡不一致。這先列為文件一致性候選；目前正在驗證是否存在真正可繞過的資料形狀，及 proxy audit 是否用錯 archive/leak-free 組。
exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

git -C "$repo" show "$commit:experiments/k528/codex_review_v4.md" | rg -n "''^(#|##|###|[-*] '"\\*\\*|VERDICT:)|BLOCK|HIGH|MEDIUM|vacuous|overclaim|洩漏|completeness\" | tail -n 180

git -C \""'$repo" show "$commit:experiments/k528/review_verdict_v4.json"

git -C "$repo" show "$commit:experiments/k528/k528_nfp_event_study.py" | nl -ba | sed -n '"'90,380p'

git -C \""'$repo" show "$commit:experiments/k528/k528_nfp_event_study.py" | nl -ba | rg -n "proxy|archive|before|control|n_control|reconstruct|SUPERSEDED|first Friday|first-Friday|Friday" | sed -n '"'1,240p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
fatal: ambiguous argument 'xperiments/k528/codex_review_v4.md': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
fatal: ambiguous argument 'xperiments/k528/review_verdict_v4.json': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
fatal: ambiguous argument 'xperiments/k528/k528_nfp_event_study.py': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
fatal: ambiguous argument 'xperiments/k528/k528_nfp_event_study.py': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

git -C "$repo" show "${commit}:experiments/k528/codex_review_v4.md" | rg -n "''^(#|##|###|[-*] '"\\*\\*|VERDICT:)|BLOCK|HIGH|MEDIUM|vacuous|overclaim|洩漏|completeness\" | tail -n 180

git -C \""'$repo" show "${commit}:experiments/k528/review_verdict_v4.json"

git -C "$repo" show "${commit}:experiments/k528/k528_nfp_event_study.py" | nl -ba | sed -n '"'90,380p'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_event_study.py" | nl -ba | rg -n "proxy|archive|before|control|n_control|reconstruct|SUPERSEDED|first Friday|first-Friday|Friday" | sed -n '"'1,240p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
36:1. **BLOCKER 1（控制組洩漏 2005-01-07）** — 聲稱對照組改為排除**全部 254 個**已映射
41:2. **BLOCKER 2（before/after 硬比不同 estimand + 「proxy 全為週五」錯誤）** — 聲稱
48:3. **BLOCKER 3（fail-closed 可繞過）** — 聲稱 `check_calendar_is_complete` 改為**同時
59:6. **finding 6（fixture overclaim + 殘留 p=0.0571）** — 聲稱 docstring 改口並明寫覆蓋
74:5. 新測試是否 vacuous；`_k528_module()` 這種 AST 抽取方式會不會讓測試測到的不是
77:7. README 宣稱面與 artifact 是否一致（有沒有新的 overclaim）
100:2abb3f68c (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex 三審 round-1 的三個 BLOCKER + findings 4-6
148:    38	1. **BLOCKER 1（accessor 取 max() 選錯六個日期）** — 聲稱根修在 main commit `305d118a3`，
153:    43	2. **BLOCKER 2（顯著性翻轉不成立）** — 聲稱確認你是對的：翻轉不成立。舊口徑重算得
157:    47	3. **BLOCKER 3 / finding 4（fail-closed 不完整）** — 聲稱補了 `check_calendar_is_complete`
189:    79	6. 新測試是否**真的**測得到 bug（fixture 有沒有被動過手腳、mutation 檢查是否 vacuous）
191:    81	8. README 宣稱面與 artifact 是否一致（有沒有 overclaim）
214:   104	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
245:   135	rg -n "BLOCKER|Finding|VERDICT|FAIL|CONDITIONAL|PASS" experiments/k528/codex_review_v2.md experiments/k528/review_verdict.json | tail -n 120
248:   138	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
263:   153	experiments/k528/codex_review_v2.md:73:- `k1708_fix_verdict_gate_20260717` P2 [experiment] [experiment] K1708 修正 stage：verdict gate 假陽性 + CW nesting/gate 替換三個 BLOCKER — claimed_by=hourly-slot-1-858545f95a864e298ddb4bc144a8c615
268:   158	experiments/k528/codex_review_v2.md:275:5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。
277:   167	experiments/k528/codex_review_v2.md:4985:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
278:   168	experiments/k528/codex_review_v2.md:4987:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
280:   170	experiments/k528/codex_review_v2.md:5008:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
281:   171	experiments/k528/codex_review_v2.md:5010:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
403:    fix(k528): 修 Codex 三審 round-1 的三個 BLOCKER + findings 4-6
409:    - BLOCKER 1 控制組洩漏：2005-01-07 因事件窗不足被排除出事件組，卻仍留在對照組 ——
412:    - BLOCKER 2 audit 拿不同 estimand 硬比，且「proxy 全為週五」是錯的：proxy 日曆確為
416:    - BLOCKER 3 fail-closed 仍可繞過：只驗 accessor 輸出無效（它已先按月收斂）。改為
423:    - finding 6 overclaim：fixture 是 _fetch 回傳值不是完整 HTTP bytes，docstring 已改口
480:    38	1. **BLOCKER 1（accessor 取 max() 選錯六個日期）** — 聲稱根修在 main commit `305d118a3`，
485:    43	2. **BLOCKER 2（顯著性翻轉不成立）** — 聲稱確認你是對的：翻轉不成立。舊口徑重算得
489:    47	3. **BLOCKER 3 / finding 4（fail-closed 不完整）** — 聲稱補了 `check_calendar_is_complete`
521:    79	6. 新測試是否**真的**測得到 bug（fixture 有沒有被動過手腳、mutation 檢查是否 vacuous）
523:    81	8. README 宣稱面與 artifact 是否一致（有沒有 overclaim）
546:   104	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
577:   135	rg -n "BLOCKER|Finding|VERDICT|FAIL|CONDITIONAL|PASS" experiments/k528/codex_review_v2.md experiments/k528/review_verdict.json | tail -n 120
580:   138	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
595:   153	experiments/k528/codex_review_v2.md:73:- `k1708_fix_verdict_gate_20260717` P2 [experiment] [experiment] K1708 修正 stage：verdict gate 假陽性 + CW nesting/gate 替換三個 BLOCKER — claimed_by=hourly-slot-1-858545f95a864e298ddb4bc144a8c615
600:   158	experiments/k528/codex_review_v2.md:275:5. **VT-trend 論文 body v6 HIGH Finding 3**（2009 trough 過強）：精準化「3/5 零、2/5 mixed sign（50/50 +2.1pp, QQQ -3.5pp）不能說完全不存在」，xelatex 編譯通過（commit f08b12263）。
609:   167	experiments/k528/codex_review_v2.md:4985:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
610:   168	experiments/k528/codex_review_v2.md:4987:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
612:   170	experiments/k528/codex_review_v2.md:5008:1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
613:   171	experiments/k528/codex_review_v2.md:5010:2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
908:   466	experiments/k528/k528_nfp_event_study.py:116:    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
925:   483	experiments/k528/k528_nfp_event_study.py:159:    completeness = check_calendar_is_complete(dates, start, end)
1611:  1169	   263	        """Pin the call count so the assertions below cannot pass vacuously."""
1630:  1188	   282	        # Guard against all([]) passing vacuously if nothing was captured.
1668:  1226	  "note": "VERBATIM _fetch() output. Do NOT hand-edit or de-duplicate: the six same-month duplicate pairs ARE the regression surface (k528 Codex v2 BLOCKER 1).",
1882:  1440	   116	    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
1925:  1483	   159	    completeness = check_calendar_is_complete(dates, start, end)
1926:  1484	   160	    return list(dates), completeness
1965:  1523	   199	nfp_calendar, calendar_completeness = load_nfp_dates()
2277:  1835	    "calendar_completeness": {
3398:  2956	   971	        "calendar_completeness": calendar_completeness,
4110:  3668	6fd281901 (HEAD -> k528-nfp-official-dates) fix(k528): 修 Codex v2 三個 BLOCKER — 顯著性翻轉不成立，18 條更正作廢
4149:  3707	    "calendar_completeness": {
5142:  4700	   174	- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住本輪 BLOCKER**：
5243:  4801	  4985	1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
5245:  4803	  4987	2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
5247:  4805	  4989	3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。
5249:  4807	  4991	4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。
5251:  4809	  4993	5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。
5253:  4811	  4995	6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。
5255:  4813	  4997	7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。
5257:  4815	  4999	8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。
5266:  4824	  5008	1. **BLOCKER — 官方日曆仍選錯六個事件日。** 共用 accessor 對同月多筆 FRED release-id 50 entries 取 `max()`（[event_dates.py:96](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:96)、[event_dates.py:125](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:125)），把後續修訂／特殊發布誤當 monthly Employment Situation。錯誤日期包括 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；例如 artifact 採 2024-08-21（[results.json:3955](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:3955)），實際 regular release 是 2024-08-02。現有 42 tests 全綠，但 fixture 已事先刪掉這些同月第二筆，未測真實 raw-response 語義。
5268:  4826	  5010	2. **BLOCKER — 核心「顯著→不顯著」翻轉不成立，18 條更正禁止套用。** 以相同 yfinance 規格可重現現行錯誤日期結果 1.1502×、p≈0.05715；換回上述六個 regular release dates 後為約 **1.1779×、p≈0.02488**，仍達 5% 顯著。故 audit 的 `sig -> NS`（[official_dates_results.json:144](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:144)）、README 的「唯一結論翻轉」（[README.md:59](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:59)），以及文章更正中的方向翻轉（[build_article_correction.py:58](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:58)、[build_article_correction.py:109](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:109)）均為錯誤。
5270:  4828	  5012	3. **HIGH — 18 條替換只對齊受污染的 JSON。** 18 個舊字串目前確實各命中正文一次；但重新選對日期後，抽查結果顯示：樣本數 253 仍正確；NFP 均值應約 0.845% 而非 0.828%、全體 ratio 約 1.11 而非 1.08；Friday ratio 約 1.18 且顯著；regime 約 2.03、組數 128/125；Spearman 約 0.35、斜率約 0.043 個百分點；只有 16.69 門檻與 worked example 大致不變。因此 [build_article_correction.py:49](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:49)、[build_article_correction.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:77)、[build_article_correction.py:85](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:85) 等多數替換需重建。
5272:  4830	  5014	4. **HIGH — fail-closed 不完整。** accessor 與主腳本都只有「整段零筆」才報錯（[event_dates.py:121](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:121)、[k528_nfp_event_study.py:77](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:77)）；缺一個月、同月多筆歧義均會繼續。此外，發布日找不到三日內交易日時會靜默略過或映射到下一交易日，沒有一對一完整性 assertion（[k528_nfp_event_study.py:128](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:128)）。不符合「缺日期就報錯」。
5274:  4832	  5016	5. **HIGH — Friday baseline estimand 不乾淨。** 全部 NFP 事件（artifact 中只有 231/253 在週五）直接和非 NFP 週五比較（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)、[k528_nfp_event_study.py:234](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:234)）。應限制事件組為 Friday releases，或使用 weekday-matched controls；目前 p 值混入 weekday composition。
5276:  4834	  5018	6. **MEDIUM — 方向性敘述超過證據。** 結果宣稱 NFP 效果「insignificant across all tests」（[results.json:203](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:203)），但同一 artifact 的單尾 Mann–Whitney p=0.00884、明確顯著（[results.json:44](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:44)）。只能說 Welch mean-difference 未顯著，不能推成「不是 NFP 本身」；非顯著也不是零效果證明。
5278:  4836	  5020	7. **MEDIUM — 寫入防錯不足。** 主結果與 audit 直接 truncate/write，非原子更新（[k528_nfp_event_study.py:832](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:832)、[k528_nfp_event_study.py:869](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:869)）。builder 即使 dry-run 仍無條件覆寫 audit（[build_article_correction.py:173](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:173)、[build_article_correction.py:227](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:227)），與「nothing written」矛盾。canonical feed writer 本身的 lock、temporary file、`fsync`、`os.replace` 合格。
5280:  4838	  5022	8. **MEDIUM — superseded 揭露主要靠檔名。** README 對 proxy 原因與影響揭露充分，但 archive JSON 本體沒有 `superseded=true`、proxy 日期來源或撤回原因（[PROXY_SUPERSEDED.json:1](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json:1)）。離開檔名／README 後不可機器判別。
6040:  5598	    11	  "note": "VERBATIM _fetch() output. Do NOT hand-edit or de-duplicate: the six same-month duplicate pairs ARE the regression surface (k528 Codex v2 BLOCKER 1).",
6084:  5642	1. **BLOCKER — 真實 NFP 日洩漏進控制組，兩個指定統計量受污染。**  
6093:  5651	2. **BLOCKER — before/after audit 硬比不同 estimand，且「proxy 全為週五」是錯的。**  
6102:  5660	3. **BLOCKER — fail-closed 仍可被合理形狀的錯資料繞過。**  
6115:  5673	4. **HIGH — 19 條替換雖全部命中，但不能套用。**  
6125:  5683	5. **MEDIUM — results 內部仍有直接矛盾。**  
6128:  5686	6. **MEDIUM — 新測試確實咬得到 `max()`，但 coverage 宣稱過頭。**  
6129:  5687	   我把 production selection 動態 mutation 為 `max()`，六個月份精確變回 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；`test_regular_release_wins_in_every_duplicate_month` 會轉紅，因此不是 vacuous。正常 accessor 也確實選回六個正確日期；BLS 官方 Employment Situation archive 可交叉確認，例如 [2013-05-03](https://www.bls.gov/news.release/archives/empsit_05032013.htm)、[2020-05-08](https://www.bls.gov/news.release/archives/empsit_05082020.htm)、[2024-08-02](https://www.bls.gov/news.release/archives/empsit_08022024.htm)。  
6130:  5688	   但 fixture 是 `_fetch()` 抽出的日期清單，不是完整 ALFRED HTTP raw-response bytes；`test_event_dates_real_raw_response.py:1-14` 的 “VERBATIM raw response/actual bytes” 是 overclaim。測試也沒有覆蓋較早 off-cycle、完整首尾月缺失或控制組洩漏。`tests/test_nfp_official_release_dates.py:338-340` 還殘留已推翻的 p=0.0571 敘述。
6143:  5701	Blocking defects：控制組混入 `2005-01-07` 真實 NFP 日；before/after Friday audit 比較不同 estimand 且錯報 proxy weekday composition；calendar completeness 仍無法真正 fail-closed。19 條更正不得以 commit `6fd281901` 套用。
6150:  5708	1. **BLOCKER — 真實 NFP 日洩漏進控制組，兩個指定統計量受污染。**  
6159:  5717	2. **BLOCKER — before/after audit 硬比不同 estimand，且「proxy 全為週五」是錯的。**  
6168:  5726	3. **BLOCKER — fail-closed 仍可被合理形狀的錯資料繞過。**  
6181:  5739	4. **HIGH — 19 條替換雖全部命中，但不能套用。**  
6191:  5749	5. **MEDIUM — results 內部仍有直接矛盾。**  
6194:  5752	6. **MEDIUM — 新測試確實咬得到 `max()`，但 coverage 宣稱過頭。**  
6195:  5753	   我把 production selection 動態 mutation 為 `max()`，六個月份精確變回 2006-05-08、2012-12-12、2013-05-06、2020-05-11、2024-01-10、2024-08-21；`test_regular_release_wins_in_every_duplicate_month` 會轉紅，因此不是 vacuous。正常 accessor 也確實選回六個正確日期；BLS 官方 Employment Situation archive 可交叉確認，例如 [2013-05-03](https://www.bls.gov/news.release/archives/empsit_05032013.htm)、[2020-05-08](https://www.bls.gov/news.release/archives/empsit_05082020.htm)、[2024-08-02](https://www.bls.gov/news.release/archives/empsit_08022024.htm)。  
6196:  5754	   但 fixture 是 `_fetch()` 抽出的日期清單，不是完整 ALFRED HTTP raw-response bytes；`test_event_dates_real_raw_response.py:1-14` 的 “VERBATIM raw response/actual bytes” 是 overclaim。測試也沒有覆蓋較早 off-cycle、完整首尾月缺失或控制組洩漏。`tests/test_nfp_official_release_dates.py:338-340` 還殘留已推翻的 p=0.0571 敘述。
6209:  5767	Blocking defects：控制組混入 `2005-01-07` 真實 NFP 日；before/after Friday audit 比較不同 estimand 且錯報 proxy weekday composition；calendar completeness 仍無法真正 fail-closed。19 條更正不得以 commit `6fd281901` 套用。
6360:-    up as a second event -- the k528 v2 BLOCKER), a month is missing, or the
6368:+    the output could look for it. That is precisely how the k528 v2 BLOCKER got
6418:+            "monthly report -- selecting it is the k528 v2 BLOCKER."
6477:-    completeness = check_calendar_is_complete(dates, start, end)
6481:+    completeness = check_calendar_is_complete(dates, raw, start, end)
6482:     return list(dates), completeness
6521: nfp_calendar, calendar_completeness = load_nfp_dates()
7238:         "calendar_completeness": calendar_completeness,
7482:         """Pin the call count so the assertions below cannot pass vacuously."""
7501:         # Guard against all([]) passing vacuously if nothing was captured.
7664:         """Direct pin on the k528 Codex v2 BLOCKER.
7921:   127	    the output could look for it. That is precisely how the k528 v2 BLOCKER got
7963:   169	            "monthly report -- selecting it is the k528 v2 BLOCKER."
8017:   262	nfp_calendar, calendar_completeness = load_nfp_dates()
8562:   441	        """Direct pin on the k528 Codex v2 BLOCKER.
8765:sample dict keys=['total_nfp_events', 'date_range', 'non_nfp_trading_days', 'friday_baseline_days', 'nfp_days_on_friday', 'event_mapping_audit', 'calendar_completeness']
9044: 'calendar_completeness': {'n_months_in_span': 255,
9701:   188	- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住 v2 BLOCKER**：
9729:   216	2. 選到的不是該月最早一筆 → raise（這正是 v2 BLOCKER 的形狀）
10073:## k528-nfp-official-dates
10399:    30	    "calendar_completeness": {
10952:  1038	        "calendar_completeness": calendar_completeness,
11173:已完成指定 commit 的 blob 級審查、獨立重算、production helper 攻擊與文章替換核對。現行 official 統計與讀者可見 scope 已驗收；audit 的 proxy control 仍洩漏，calendar completeness 可由多種形狀繞過，且新增控制組測試是代數恆等式。
11236:   222	    completeness = check_calendar_is_complete(dates, raw, start, end)
11237:   223	    return list(dates), completeness
11254:1. **BLOCKER — audit 的 proxy `before` 控制組仍洩漏 `2005-01-07`，所以主 before/after 尚非同一個乾淨 estimand。**  
11256:   因此 audit 所報 before 1.1678306、p=0.0409368（`k528_nfp_official_dates_results.json:136-150`）仍受上一輪同類洩漏污染；卻宣稱兩欄使用相同 restricted estimand、差異只來自日期（`:170`）。用同一 pinned SPY snapshot 排除該日後，proxy restricted 應約為：
11264:2. **BLOCKER — `check_calendar_is_complete` 仍可輕易繞過，整個尾段消失正是現存漏洞。**  
11265:   `start/end` 傳入後實際未參與 completeness span；span 完全由 `min(selected)..max(selected)` 決定（`k528_nfp_event_study.py:172-179`）。我用 commit 內的 production `load_nfp_dates` helper 實測：
11279:   更嚴重的是新增的「乾淨日曆必須通過」測試自己就用全年範圍只提供 1–3 月，並期待成功（`tests/test_nfp_official_release_dates.py:596-604`），等於把尾段消失正式寫成合法行為。README 所稱「移除首尾月漏洞」（`README.md:210-220`）是錯誤 overclaim。
11281:3. **HIGH — `TestControlGroupHasNoNfpDays` 是 vacuous，無法抓到控制組洩漏回歸。**  
11315:7. **MEDIUM — README 仍有 artifact 與推論 overclaim。**
11323:Blocking defects：proxy restricted audit 仍含 `2005-01-07` 控制組洩漏；calendar completeness 仍接受完整尾段消失、3-day equality、selected/raw 不一致等錯誤輸入。
11325:VERDICT: FAIL
11330:1. **BLOCKER — audit 的 proxy `before` 控制組仍洩漏 `2005-01-07`，所以主 before/after 尚非同一個乾淨 estimand。**  
11332:   因此 audit 所報 before 1.1678306、p=0.0409368（`k528_nfp_official_dates_results.json:136-150`）仍受上一輪同類洩漏污染；卻宣稱兩欄使用相同 restricted estimand、差異只來自日期（`:170`）。用同一 pinned SPY snapshot 排除該日後，proxy restricted 應約為：
11340:2. **BLOCKER — `check_calendar_is_complete` 仍可輕易繞過，整個尾段消失正是現存漏洞。**  
11341:   `start/end` 傳入後實際未參與 completeness span；span 完全由 `min(selected)..max(selected)` 決定（`k528_nfp_event_study.py:172-179`）。我用 commit 內的 production `load_nfp_dates` helper 實測：
11355:   更嚴重的是新增的「乾淨日曆必須通過」測試自己就用全年範圍只提供 1–3 月，並期待成功（`tests/test_nfp_official_release_dates.py:596-604`），等於把尾段消失正式寫成合法行為。README 所稱「移除首尾月漏洞」（`README.md:210-220`）是錯誤 overclaim。
11357:3. **HIGH — `TestControlGroupHasNoNfpDays` 是 vacuous，無法抓到控制組洩漏回歸。**  
11391:7. **MEDIUM — README 仍有 artifact 與推論 overclaim。**
11399:Blocking defects：proxy restricted audit 仍含 `2005-01-07` 控制組洩漏；calendar completeness 仍接受完整尾段消失、3-day equality、selected/raw 不一致等錯誤輸入。
11401:VERDICT: FAIL
{
  "kid": "k528",
  "verdict": "FAIL",
  "reviewer": "Codex gpt-5.6-sol / high",
  "reviewed_at": "2026-07-19T16:45:00+08:00",
  "reviewed_commit": "2abb3f68c",
  "review_artifact": "experiments/k528/codex_review_v4.md",
  "blocking_defects": [
    "proxy-side `before` control group still leaked the proxy's own window-dropped 2005-01-07 session",
    "calendar completeness accepted a fully truncated tail, a 3-day-equality gap, selected months absent from raw, and duplicate selected months",
    "TestControlGroupHasNoNfpDays was an algebraic identity and could not fail"
  ],
  "reviewed_sha256": {
    "README.md": "29e8781d3e1860ad041af2f0eecddf1177975daa89709efc16b7a88dfe0d3f8f",
    "build_article_correction.py": "c4e3cf99627faa7a60565e5e9df89d44f99de6bf7900716b59451e25637b2e31",
    "k528_nfp_event_study.py": "da6007e445d846268ea3216944c61b364fc6cd2aa7520d960412d0bf2f8c671e",
    "k528_nfp_event_study_results.json": "fb536843e3c98fe38d7bdd8efc9fca043e245cc004a8ff8b9439148f67ea2137",
    "k528_nfp_official_dates_results.json": "db7e35c3a9ada8e02661e1abcb636dfa07d8bf913ef05bc05af93441f760bdee"
  },
  "note": "Historical record of one round of the third-review cycle. Superseded by the next round; retained because a verdict is only worth the snapshot it read, and deleting a FAIL teaches the wrong lesson."
}
    90	
    91	# The months where ALFRED returns two release-id-50 entries, with the entry that
    92	# is the actual Employment Situation report. Verified individually against the
    93	# BLS news-release archive (bls.gov/news.release/archives/empsit_<MMDDYYYY>.htm).
    94	#
    95	# Why an explicit reviewed list rather than a rule: "earliest entry in the month"
    96	# is right for every case we have checked, but it is a HEURISTIC, and it fails
    97	# silently if an off-cycle item is ever filed BEFORE the report. There is no way
    98	# to tell those apart from dates alone. So the rule still runs, and on top of it
    99	# any month with multiple entries must appear here -- a new multi-entry month is
   100	# something a human has to look at, not something this script gets to assume.
   101	REVIEWED_MULTI_ENTRY_MONTHS: dict[str, str] = {
   102	    "2006-05": "2006-05-05",
   103	    "2012-12": "2012-12-07",
   104	    "2013-05": "2013-05-03",
   105	    "2020-05": "2020-05-08",
   106	    "2024-01": "2024-01-05",
   107	    "2024-08": "2024-08-02",
   108	}
   109	
   110	# How far the observed calendar may fall short of the requested window before the
   111	# run treats it as truncated. One monthly cycle plus slack; a feed that stops
   112	# early otherwise shrinks the "observed span" it is checked against and passes.
   113	MAX_WINDOW_SHORTFALL_DAYS = 70
   114	
   115	
   116	def write_json_atomic(path: Path, payload) -> None:
   117	    """Write `payload` to `path` atomically.
   118	
   119	    A truncate-then-write leaves a half-written results file on the disk if the
   120	    run dies mid-dump, and a half-written results file is worse than none: it
   121	    still parses far enough to look like data to the next reader. Write to a
   122	    temp file in the same directory, fsync, then os.replace (atomic on POSIX).
   123	    """
   124	    path.parent.mkdir(parents=True, exist_ok=True)
   125	    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
   126	    try:
   127	        with os.fdopen(fd, "w") as f:
   128	            json.dump(payload, f, indent=2, default=str)
   129	            f.flush()
   130	            os.fsync(f.fileno())
   131	        os.replace(tmp, path)
   132	    except BaseException:
   133	        try:
   134	            os.unlink(tmp)
   135	        except FileNotFoundError:
   136	            pass  # silent-ok: best-effort cleanup of our own temp file; the original error re-raises below
   137	        raise
   138	
   139	
   140	# ============================================================
   141	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
   142	# ============================================================
   143	def check_calendar_is_complete(selected, raw, start, end):
   144	    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
   145	
   146	    "Did the call succeed?" is the wrong question. A monthly release calendar
   147	    that silently lost 2019 still returns a non-empty list, still produces
   148	    event windows, still renders.
   149	
   150	    This validates the RAW feed as well as the accessor's per-month selection.
   151	    Validating only the selection cannot work: the accessor collapses each month
   152	    to one date before this function ever sees it, so a same-month ambiguity is
   153	    already resolved -- silently, and possibly wrongly -- by the time a check on
   154	    the output could look for it. That is precisely how the k528 v2 BLOCKER got
   155	    through (Codex v3 finding 3).
   156	
   157	    Four ways the input can be wrong without being empty, all of which raise:
   158	      1. a month has two entries too close together to tell report from revision
   159	      2. the selection is not the earliest entry of its month
   160	      3. a month is missing from the observed span
   161	      4. a month is claimed as a known hole but the raw feed actually has data
   162	    """
   163	    sel = [pd.Timestamp(d) for d in selected]
   164	    sel_months = [d.strftime("%Y-%m") for d in sel]
   165	
   166	    raw_by_month: dict[str, list[pd.Timestamp]] = {}
   167	    for d in raw:
   168	        ts = pd.Timestamp(d)
   169	        raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
   170	    for v in raw_by_month.values():
   171	        v.sort()
   172	
   173	    # 0: the selection itself must be well-formed before anything is inferred
   174	    # from it. Building a month->date dict first would silently keep only the
   175	    # last of a duplicated month and hide exactly what we are looking for.
   176	    sel_month_counts: dict[str, int] = {}
   177	    for m in sel_months:
   178	        sel_month_counts[m] = sel_month_counts.get(m, 0) + 1
   179	    sel_dupes = sorted(m for m, c in sel_month_counts.items() if c > 1)
   180	    if sel_dupes:
   181	        raise RuntimeError(
   182	            f"selected calendar has more than one entry for {sel_dupes}. The Employment "
   183	            "Situation is monthly; a duplicated month means the accessor stopped collapsing."
   184	        )
   185	    invented = sorted(set(sel_months) - set(raw_by_month))
   186	    if invented:
   187	        raise RuntimeError(
   188	            f"selected calendar contains month(s) absent from the raw feed: {invented}. "
   189	            "The selection must be a subset of what the source actually published."
   190	        )
   191	    off_feed = sorted(str(d.date()) for d in sel if d not in raw_by_month.get(d.strftime("%Y-%m"), []))
   192	    if off_feed:
   193	        raise RuntimeError(
   194	            f"selected dates that do not appear in the raw feed at all: {off_feed}."
   195	        )
   196	
   197	    # 1: the accessor's per-month choice must be the earliest entry.
   198	    mis_selected = []
   199	    sel_by_month = dict(zip(sel_months, sel))
   200	    for month, entries in raw_by_month.items():
   201	        if month in sel_by_month and sel_by_month[month] != entries[0]:
   202	            mis_selected.append(
   203	                f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
   204	            )
   205	    if mis_selected:
   206	        raise RuntimeError(
   207	            f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
   208	            f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
   209	            "monthly report -- selecting it is the k528 v2 BLOCKER."
   210	        )
   211	
   212	    # "Earliest wins" is a heuristic and cannot survive an off-cycle item filed
   213	    # BEFORE the report. Every multi-entry month therefore has to be one a human
   214	    # checked against the BLS archive, and the checked answer has to match.
   215	    multi = {m: v for m, v in raw_by_month.items() if len(v) > 1}
   216	    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
   217	    if unreviewed:
   218	        raise RuntimeError(
   219	            f"{len(unreviewed)} month(s) carry multiple release entries but have never been "
   220	            f"checked against the BLS archive: "
   221	            f"{ {m: [str(d.date()) for d in multi[m]] for m in unreviewed} }. "
   222	            "Selecting the earliest is only a heuristic; verify which entry is the Employment "
   223	            "Situation report at bls.gov/news.release/archives/ and add it to "
   224	            "REVIEWED_MULTI_ENTRY_MONTHS."
   225	        )
   226	    contradicted = {
   227	        m: {"selected": str(sel_by_month[m].date()), "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]}
   228	        for m in multi
   229	        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]
   230	    }
   231	    if contradicted:
   232	        raise RuntimeError(
   233	            f"selection contradicts the human-verified release date in {contradicted}. "
   234	            "Either the feed changed or the accessor regressed; do not proceed on the guess."
   235	        )
   236	
   237	    # 3a: the observed span must actually cover what was asked for. Checking only
   238	    # for gaps INSIDE the observed span cannot catch truncation -- if the feed
   239	    # stops early, the span shrinks with it and nothing looks missing. Found by
   240	    # self-audit while Codex v3 round-2 was running.
   241	    want_start, want_end = pd.Timestamp(start), pd.Timestamp(end)
   242	    head_short = (min(sel) - want_start).days
   243	    tail_short = (want_end - max(sel)).days
   244	    if head_short > MAX_WINDOW_SHORTFALL_DAYS or tail_short > MAX_WINDOW_SHORTFALL_DAYS:
   245	        raise RuntimeError(
   246	            f"official NFP calendar does not cover the requested window "
   247	            f"{start}..{end}: first release {min(sel).date()} ({head_short}d in), "
   248	            f"last release {max(sel).date()} ({tail_short}d short of the end). "
   249	            f"Tolerance is {MAX_WINDOW_SHORTFALL_DAYS}d. A truncated feed silently "
   250	            "shortens the sample while every printed count still agrees with itself."
   251	        )
   252	
   253	    # 3b: no month may vanish from inside the observed span.
   254	    span = {
   255	        p.strftime("%Y-%m")
   256	        for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
   257	    }
   258	    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
   259	    if missing:
   260	        raise RuntimeError(
   261	            f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
   262	            f"span: {missing}. A partial calendar dumps real event days into the control "
   263	            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
   264	            "reason (e.g. a cancelled release), never to make this check pass."
   265	        )
   266	
   267	    # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
   268	    # allowlist is a bypass: any month could be declared 'known missing' and the
   269	    # check would stop looking at it.
   270	    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if m in span and raw_by_month.get(m))
   271	    if bogus:
   272	        raise RuntimeError(
   273	            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
   274	            f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
   275	            "The allowlist is for real cancellations, not for silencing a selection bug."
   276	        )
   277	
   278	    return {
   279	        "n_months_in_span": len(span),
   280	        "n_raw_entries": len(raw),
   281	        "months_with_multiple_raw_entries": sorted(multi),
   282	        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
   283	        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
   284	        "window_coverage": {
   285	            "requested": f"{start}..{end}",
   286	            "observed": f"{min(sel).date()}..{max(sel).date()}",
   287	            "head_shortfall_days": int(head_short),
   288	            "tail_shortfall_days": int(tail_short),
   289	            "tolerance_days": MAX_WINDOW_SHORTFALL_DAYS,
   290	        },
   291	        "residual_limitation": (
   292	            "Same-month selection uses 'earliest wins', which is a heuristic. It cannot "
   293	            "distinguish an off-cycle item filed BEFORE the report from the report itself, "
   294	            "so every multi-entry month must additionally appear in "
   295	            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A "
   296	            "new multi-entry month fails the run rather than being assumed."
   297	        ),
   298	    }
   299	
   300	
   301	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   302	    """Official NFP (Employment Situation) release dates.
   303	
   304	    Deliberately has no except branch. If the release calendar cannot be
   305	    reached, this run must die -- a proxy calendar produces plausible numbers
   306	    from non-events, which is worse than no numbers at all. See the CORRECTION
   307	    note in the module docstring.
   308	    """
   309	    dates = nfp_release_dates(start, end)
   310	    if len(dates) == 0:
   311	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
   312	    # Pull the unselected feed as well: the accessor collapses each month to one
   313	    # date, so the only place a same-month ambiguity is still visible is here.
   314	    raw = _fetch(RELEASE_IDS["NFP_US"], start, end)
   315	    completeness = check_calendar_is_complete(dates, raw, start, end)
   316	    return list(dates), completeness
   317	
   318	
   319	# ============================================================
   320	# 2. Download data
   321	# ============================================================
   322	print("=" * 60)
   323	print("K528: NFP Event Study on SPY Volatility")
   324	print("=" * 60)
   325	
   326	print("\n[1/6] Downloading SPY and VIX data...")
   327	spy = yf.download("SPY", start=SAMPLE_START, end=SAMPLE_END, progress=False)
   328	vix = yf.download("^VIX", start=SAMPLE_START, end=SAMPLE_END, progress=False)
   329	
   330	# Handle multi-level columns from yfinance
   331	if isinstance(spy.columns, pd.MultiIndex):
   332	    spy.columns = spy.columns.get_level_values(0)
   333	if isinstance(vix.columns, pd.MultiIndex):
   334	    vix.columns = vix.columns.get_level_values(0)
   335	
   336	# Calculate returns
   337	spy["Return"] = spy["Close"].pct_change()
   338	spy["AbsReturn"] = spy["Return"].abs()
   339	spy["LogReturn"] = np.log(spy["Close"] / spy["Close"].shift(1))
   340	spy.dropna(subset=["Return"], inplace=True)
   341	
   342	# Merge VIX
   343	vix_close = vix[["Close"]].rename(columns={"Close": "VIX"})
   344	spy = spy.join(vix_close, how="left")
   345	spy["VIX"] = spy["VIX"].ffill()  # forward fill for holidays
   346	
   347	print(f"  SPY: {len(spy)} trading days ({spy.index[0].date()} to {spy.index[-1].date()})")
   348	print(f"  VIX: {spy['VIX'].notna().sum()} days with VIX data")
   349	
   350	# ============================================================
   351	# 3. Map NFP dates to trading days
   352	# ============================================================
   353	print("\n[2/6] Mapping NFP dates to trading days...")
   354	
   355	nfp_calendar, calendar_completeness = load_nfp_dates()
   356	trading_dates = spy.index
   357	
   358	# The proxy forced every event onto a Friday. The official calendar does not,
   359	# and that is load-bearing for the Friday-baseline test below.
   360	n_friday = sum(1 for d in nfp_calendar if pd.Timestamp(d).weekday() == 4)
   361	print(f"  Official releases: {len(nfp_calendar)} "
   362	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
   363	
   364	# Map each NFP date to the session that trades the news. The report drops at
   365	# 08:30 ET, before the open, so a release on a closed day is traded at the next
   366	# open -- hence "next trading day", not "nearest". Every release must land on
   367	# exactly one session and no two releases may share one: both failures shrink
   368	# the event set without shrinking any count that gets printed.
   369	release_to_session = {}
   370	unmapped = []
   371	for nfp_date in nfp_calendar:
   372	    nfp_ts = pd.Timestamp(nfp_date)
   373	    if nfp_ts in trading_dates:
   374	        release_to_session[nfp_ts] = nfp_ts
   375	        continue
   376	    mask = (trading_dates > nfp_ts) & (trading_dates <= nfp_ts + pd.Timedelta(days=3))
   377	    candidates = trading_dates[mask]
   378	    if len(candidates) > 0:
   379	        release_to_session[nfp_ts] = candidates[0]
   380	    else:
21:    21	The original run dated every NFP to the first Friday of the month. That proxy is
23:    23	moves the release to the second Friday whenever the reference week falls late
26:    26	happened, and it forces every event onto a Friday when 16 of the 254 official
27:    27	releases are not on a Friday at all.
30:    30	dump real event days into the control group, and the figures still render. So
34:    34	This script also emits a before/after comparison against the archived proxy-era
70:    70	# claim against the raw feed before honouring it -- an allowlist that is taken
78:    78	        "CPI release described in volpred/data/event_dates.py. The first-Friday proxy "
89:    89	# allowlist below is the actual control, and unlike a gap rule it is verifiable.
93:    93	# BLS news-release archive (bls.gov/news.release/archives/empsit_<MMDDYYYY>.htm).
110:   110	# How far the observed calendar may fall short of the requested window before the
141:   141	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
152:   152	    to one date before this function ever sees it, so a same-month ambiguity is
173:   173	    # 0: the selection itself must be well-formed before anything is inferred
214:   214	    # checked against the BLS archive, and the checked answer has to match.
220:   220	            f"checked against the BLS archive: "
223:   223	            "Situation report at bls.gov/news.release/archives/ and add it to "
262:   262	            f"span: {missing}. A partial calendar dumps real event days into the control "
295:   295	            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A "
305:   305	    reached, this run must die -- a proxy calendar produces plausible numbers
358:   358	# The proxy forced every event onto a Friday. The official calendar does not,
359:   359	# and that is load-bearing for the Friday-baseline test below.
362:   362	      f"({n_friday} Friday, {len(nfp_calendar) - n_friday} non-Friday)")
365:   365	# 08:30 ET, before the open, so a release on a closed day is traded at the next
385:   385	# not by failure, so they are separated before the assertion.
394:   394	        "drop real event days into the control group."
410:   410	# Window buffer: an event needs 5 sessions before and 5 after to have a window
469:   469	        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
496:   496	# Exclude EVERY NFP session from the control group, not just the ones that
498:   498	# is still an NFP day; leaving it in the control group is the exact failure this
499:   499	# experiment exists to fix ("dump real event days into the control group"), just
500:   500	# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
506:   506	    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
512:   512	# Friday-only baseline. The event group is a weekday MIXTURE while the control
513:   513	# group is pure Friday, so any Friday-vs-other-weekday volatility difference
518:   518	# correction. The proxy calendar was all-Friday by construction, but mapping
519:   519	# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
520:   520	# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
522:   522	# a mixed group against a pure-Friday control. Correcting the dates is what made
530:   530	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
545:   545	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
548:   548	#   (i)  restrict the event group to Friday releases, or
549:   549	#   (ii) keep all events and use weekday-matched controls.
550:   550	# This run takes (i). The non-Friday events are a handful of thin weekday cells
554:   554	# clean question: on a Friday, does an NFP release raise volatility? It costs
555:   555	# the non-Friday events, which are reported below as a separate descriptive
559:   559	# events are quieter than the Friday ones, so restricting RAISES the ratio
654:   654	print(f"\n--- B. Friday NFP vs Friday Non-NFP (weekday held fixed) ---")
655:   655	print(f"  Friday NFP |return|:  {nfp_friday_abs.mean():.6f} (n={len(nfp_friday_abs)})")
656:   656	print(f"  Friday baseline:      {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
661:   661	print(f"  [excluded] non-Friday NFP events: n={len(nfp_nonfriday_abs)}, "
663:   663	print(f"  [diagnostic, NOT a headline] all-events vs Friday baseline: "
722:   722	# 7. High-low range analysis (intraday vol proxy)
772:   772	    f"Welch mean-difference, Friday NFP vs Friday non-NFP (CONDITIONAL ON FRIDAY, "
775:   775	    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)}). Scoped to Friday "
776:   776	    f"releases; the {len(nfp_nonfriday_abs)} non-Friday events are quieter, so this "
811:   811	# 9b. Correction audit: every published number, before vs after
817:   817	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
820:   820	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
823:   823	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
826:   826	proxy = json.loads(PROXY_PATH.read_text())
835:   835	# The proxy run only ever reported means, and a mean can hold still while the
836:   836	# median and the win rate move underneath it. Rather than leave the before-side
838:   838	# exactly the failure it is looking for -- rebuild the proxy-era distributions
839:   839	# from the ARCHIVED per-event data. The dates come out of the archive, so this
840:   840	# reconstructs history without reintroducing a proxy calendar generator.
841:   841	proxy_events = proxy["event_data"]
842:   842	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
843:   843	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
845:   845	# The archive holds the proxy run's ANALYSED events, which is not the same as
846:   846	# its NFP sessions: the proxy also had a January-2005 event that its own
847:   847	# window-buffer dropped, and leaving that day in the proxy control group is the
849:   849	# Reconstructing it needs the first-Friday rule for exactly the months the
850:   850	# archive does not cover. That is legitimate here and only here: the audit's job
851:   851	# IS to reconstruct what the superseded run did. It is not reintroduced as a
852:   852	# data source -- every analysed date still comes from the archive.
853:   853	_archive_months = {d.strftime("%Y-%m") for d in proxy_event_dates}
858:   858	_proxy_extra_sessions = []
860:   860	    if _m in _archive_months:
864:   864	    _ff = _first + pd.Timedelta(days=(4 - _first.weekday()) % 7)   # first Friday
867:   867	        _proxy_extra_sessions.append(_cand[0])
869:   869	proxy_all_sessions = set(proxy_event_dates) | set(_proxy_extra_sessions)
870:   870	# The reconstruction must only ADD window-dropped months, never move an analysed
871:   871	# one; and the months it adds must be exactly those the archive is missing.
872:   872	if not set(proxy_event_dates) <= proxy_all_sessions:
873:   873	    raise AssertionError("proxy session reconstruction dropped an archived event")
874:   874	if len(proxy_all_sessions) != len(proxy_event_dates) + len(_proxy_extra_sessions):
875:   875	    raise AssertionError("proxy session reconstruction collided with an archived event")
876:   876	proxy_non_nfp = spy[~spy.index.isin(proxy_all_sessions)]
877:   877	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
878:   878	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
880:   880	# Two proxy control groups, deliberately, because they answer different questions:
881:   881	#   _archive  -- excludes only the archive's ANALYSED events. Reproduces the
882:   882	#                published proxy-era means, which is how we verify the
883:   883	#                reconstruction is reading the archive correctly.
884:   884	#   (above)   -- also excludes the proxy's window-dropped session. Leak-free, so
885:   885	#                it is what the before/after comparison uses.
888:   888	proxy_non_nfp_archive = spy[~spy.index.isin(set(proxy_event_dates))]
889:   889	proxy_non_nfp_abs_archive = proxy_non_nfp_archive["AbsReturn"].values
890:   890	_leak_sessions = sorted(str(d.date()) for d in _proxy_extra_sessions)
891:   891	if len(proxy_non_nfp_archive) - len(proxy_non_nfp) != len(_proxy_extra_sessions):
892:   892	    raise AssertionError("proxy control groups differ by something other than the reconstructed sessions")
894:   894	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
895:   895	# mapped to a Monday because the first Friday was a market holiday. So the
896:   896	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
897:   897	# rebuild the proxy side under the SAME estimand the corrected run uses
898:   898	# (Friday events only) rather than comparing a mixed `before` against a
900:   900	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
901:   901	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
902:   902	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
903:   903	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
906:   906	                       for e in proxy_events])
907:   907	_p_thr = proxy["regime_analysis"]["vix_median_split"]
908:   908	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
909:   909	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
911:   911	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
912:   912	# reconstruction is wrong and its medians cannot be trusted either. The baseline
913:   913	# is checked against the ARCHIVE'S control definition -- the leak-free one is a
916:   916	for _label, _rebuilt, _archived in (
917:   917	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
918:   918	    ("baseline mean", proxy_non_nfp_abs_archive.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
919:   919	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
920:   920	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
922:   922	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
924:   924	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
925:   925	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
926:   926	            "from a reconstruction that cannot reproduce the archived means."
928:   928	print("  proxy-era distributions reconstructed from archive (means reproduce)")
929:   929	print(f"  proxy control group additionally excludes {len(_proxy_extra_sessions)} "
935:   935	def record(key, label, before, after, note=""):
936:   936	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
943:   943	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
944:   944	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
945:   945	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
946:   946	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
947:   947	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
948:   948	        "n": proxy["sample"]["total_nfp_events"],
949:   949	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
950:   950	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
962:   962	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
963:   963	         "per-event data, not from the proxy run's own output (it only reported means).",
966:   966	# --- 1.17x : NFP vs Friday-only baseline ---
968:   968	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
970:   970	        # Same estimand as the `after` column: Friday events only.
971:   971	        "mean_ratio": proxy_ratio_fri_restricted,
974:   974	        "n": int(len(proxy_nfp_friday_abs)),
976:   976	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
977:   977	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
978:   978	        "n_control_friday": int(len(proxy_fri_abs)),
979:   979	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
981:   981	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
982:   982	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
983:   983	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
984:   984	            "n": proxy["sample"]["total_nfp_events"],
986:   986	                "what the proxy run actually published: all 254 events (239 Friday, "
987:   987	                "15 Monday) against non-NFP Fridays. This is the number the article "
1001:  1001	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
1012:  1012	         "event group is a weekday mixture while the control group is pure "
1013:  1013	         "Friday, so the test now restricts the event group to Friday releases. "
1014:  1014	         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
1015:  1015	         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
1018:  1018	         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
1023:  1023	proxy_reg = proxy["regime_analysis"]
1027:  1027	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
1028:  1028	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
1029:  1029	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
1030:  1030	        "n_high": proxy_reg["n_high"],
1031:  1031	        "n_low": proxy_reg["n_low"],
1032:  1032	        "p_value": proxy_reg["p_value"],
1033:  1033	        "significant_5pct": proxy_reg["p_value"] < 0.05,
1034:  1034	        "median_ratio": float(np.median(proxy_high_abs) / np.median(proxy_low_abs)),
1035:  1035	        "win_rate": win_rate(proxy_high_abs, proxy_low_abs),
1051:  1051	proxy_e = proxy["statistical_tests"]["E_vix_predictive"]
1055:  1055	        "pearson_r": proxy_e["pearson_r"],
1056:  1056	        "pearson_p": proxy_e["pearson_p"],
1057:  1057	        "spearman_rho": proxy_e["spearman_rho"],
1058:  1058	        "spearman_p": proxy_e["spearman_p"],
1059:  1059	        "slope_pct_per_vix_pt": proxy_e["slope"] * 100,
1060:  1060	        "n": proxy["sample"]["total_nfp_events"],
1061:  1061	        "significant_5pct": proxy_e["pearson_p"] < 0.05,
1078:  1078	proxy_thr = proxy_reg["vix_median_split"]
1082:  1082	        "threshold": proxy_thr,
1083:  1083	        "n": proxy["sample"]["total_nfp_events"],
1084:  1084	        "places_20260701_vix_1659_in": "low" if 16.59 < proxy_thr else "high",
1094:  1094	proxy_dates = {r["date"] for r in proxy["event_data"]}
1099:  1099	        "n": proxy["sample"]["total_nfp_events"],
1100:  1100	        "date_range": proxy["sample"]["date_range"],
1101:  1101	        "non_nfp_trading_days": proxy["sample"]["non_nfp_trading_days"],
1107:  1107	        "dates_in_common": len(proxy_dates & new_dates),
1108:  1108	        "proxy_only_dates": sorted(proxy_dates - new_dates),
1109:  1109	        "official_only_dates": sorted(new_dates - proxy_dates),
1117:  1117	    b, a = audit_items[key]["before"], audit_items[key]["after"]
1149:  1149	                     if f in item["before"]), None)
1150:  1150	    bf = item["before"].get(headline)
1174:  1174	        "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)",
1184:  1184	        # Recorded independently so the control-group invariant
1185:  1185	        # (controls == total - mapped NFP sessions) is checkable rather than an
1188:  1188	        "control_group_excludes_all_nfp_sessions": bool(
1209:  1209	            "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
1212:  1212	                "group is restricted to NFP releases that trade on a Friday, and the "
1213:  1213	                f"{int(len(nfp_nonfriday_abs))} non-Friday events are excluded rather "
1214:  1214	                "than compared against a pure-Friday control group."
1219:  1219	                "non-Friday events are quieter, so the restriction raises the ratio "
1221:  1221	                "say 'Friday NFP', not 'NFP'."
1232:  1232	            "n_control": int(len(friday_non_nfp_abs)),
1243:  1243	            "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
1247:  1247	                "group against a pure-Friday control group, so the p-value absorbs "
1248:  1248	                "any Friday-vs-other-weekday volatility difference. Retained solely "
1363:  1363	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
1365:  1365	    "before_source": PROXY_PATH.name,
1369:  1369	        "proxy_only_dates": sorted(proxy_dates - new_dates),
1370:  1370	        "official_only_dates": sorted(new_dates - proxy_dates),
1371:  1371	        "dates_in_common": len(proxy_dates & new_dates),
1372:  1372	        "n_proxy": len(proxy_dates),

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

git -C "$repo" show "${commit}:experiments/k528/codex_review_v4.md" | tail -n 180

git -C "$repo" show "${commit}:experiments/k528/k528_nfp_event_study.py" | nl -ba | sed -n '"'140,320p'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_event_study.py" | nl -ba | sed -n '"'810,1030p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
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
   140	# ============================================================
   141	# 1. NFP dates: official BLS release calendar (no proxy, no fallback)
   142	# ============================================================
   143	def check_calendar_is_complete(selected, raw, start, end):
   144	    """Fail closed on a calendar that is merely PLAUSIBLE rather than complete.
   145	
   146	    "Did the call succeed?" is the wrong question. A monthly release calendar
   147	    that silently lost 2019 still returns a non-empty list, still produces
   148	    event windows, still renders.
   149	
   150	    This validates the RAW feed as well as the accessor's per-month selection.
   151	    Validating only the selection cannot work: the accessor collapses each month
   152	    to one date before this function ever sees it, so a same-month ambiguity is
   153	    already resolved -- silently, and possibly wrongly -- by the time a check on
   154	    the output could look for it. That is precisely how the k528 v2 BLOCKER got
   155	    through (Codex v3 finding 3).
   156	
   157	    Four ways the input can be wrong without being empty, all of which raise:
   158	      1. a month has two entries too close together to tell report from revision
   159	      2. the selection is not the earliest entry of its month
   160	      3. a month is missing from the observed span
   161	      4. a month is claimed as a known hole but the raw feed actually has data
   162	    """
   163	    sel = [pd.Timestamp(d) for d in selected]
   164	    sel_months = [d.strftime("%Y-%m") for d in sel]
   165	
   166	    raw_by_month: dict[str, list[pd.Timestamp]] = {}
   167	    for d in raw:
   168	        ts = pd.Timestamp(d)
   169	        raw_by_month.setdefault(ts.strftime("%Y-%m"), []).append(ts)
   170	    for v in raw_by_month.values():
   171	        v.sort()
   172	
   173	    # 0: the selection itself must be well-formed before anything is inferred
   174	    # from it. Building a month->date dict first would silently keep only the
   175	    # last of a duplicated month and hide exactly what we are looking for.
   176	    sel_month_counts: dict[str, int] = {}
   177	    for m in sel_months:
   178	        sel_month_counts[m] = sel_month_counts.get(m, 0) + 1
   179	    sel_dupes = sorted(m for m, c in sel_month_counts.items() if c > 1)
   180	    if sel_dupes:
   181	        raise RuntimeError(
   182	            f"selected calendar has more than one entry for {sel_dupes}. The Employment "
   183	            "Situation is monthly; a duplicated month means the accessor stopped collapsing."
   184	        )
   185	    invented = sorted(set(sel_months) - set(raw_by_month))
   186	    if invented:
   187	        raise RuntimeError(
   188	            f"selected calendar contains month(s) absent from the raw feed: {invented}. "
   189	            "The selection must be a subset of what the source actually published."
   190	        )
   191	    off_feed = sorted(str(d.date()) for d in sel if d not in raw_by_month.get(d.strftime("%Y-%m"), []))
   192	    if off_feed:
   193	        raise RuntimeError(
   194	            f"selected dates that do not appear in the raw feed at all: {off_feed}."
   195	        )
   196	
   197	    # 1: the accessor's per-month choice must be the earliest entry.
   198	    mis_selected = []
   199	    sel_by_month = dict(zip(sel_months, sel))
   200	    for month, entries in raw_by_month.items():
   201	        if month in sel_by_month and sel_by_month[month] != entries[0]:
   202	            mis_selected.append(
   203	                f"{month}: selected {sel_by_month[month].date()}, earliest is {entries[0].date()}"
   204	            )
   205	    if mis_selected:
   206	        raise RuntimeError(
   207	            f"accessor did not select the earliest entry in {len(mis_selected)} month(s): "
   208	            f"{mis_selected}. The later same-month entry is an off-cycle revision, not the "
   209	            "monthly report -- selecting it is the k528 v2 BLOCKER."
   210	        )
   211	
   212	    # "Earliest wins" is a heuristic and cannot survive an off-cycle item filed
   213	    # BEFORE the report. Every multi-entry month therefore has to be one a human
   214	    # checked against the BLS archive, and the checked answer has to match.
   215	    multi = {m: v for m, v in raw_by_month.items() if len(v) > 1}
   216	    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
   217	    if unreviewed:
   218	        raise RuntimeError(
   219	            f"{len(unreviewed)} month(s) carry multiple release entries but have never been "
   220	            f"checked against the BLS archive: "
   221	            f"{ {m: [str(d.date()) for d in multi[m]] for m in unreviewed} }. "
   222	            "Selecting the earliest is only a heuristic; verify which entry is the Employment "
   223	            "Situation report at bls.gov/news.release/archives/ and add it to "
   224	            "REVIEWED_MULTI_ENTRY_MONTHS."
   225	        )
   226	    contradicted = {
   227	        m: {"selected": str(sel_by_month[m].date()), "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]}
   228	        for m in multi
   229	        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]
   230	    }
   231	    if contradicted:
   232	        raise RuntimeError(
   233	            f"selection contradicts the human-verified release date in {contradicted}. "
   234	            "Either the feed changed or the accessor regressed; do not proceed on the guess."
   235	        )
   236	
   237	    # 3a: the observed span must actually cover what was asked for. Checking only
   238	    # for gaps INSIDE the observed span cannot catch truncation -- if the feed
   239	    # stops early, the span shrinks with it and nothing looks missing. Found by
   240	    # self-audit while Codex v3 round-2 was running.
   241	    want_start, want_end = pd.Timestamp(start), pd.Timestamp(end)
   242	    head_short = (min(sel) - want_start).days
   243	    tail_short = (want_end - max(sel)).days
   244	    if head_short > MAX_WINDOW_SHORTFALL_DAYS or tail_short > MAX_WINDOW_SHORTFALL_DAYS:
   245	        raise RuntimeError(
   246	            f"official NFP calendar does not cover the requested window "
   247	            f"{start}..{end}: first release {min(sel).date()} ({head_short}d in), "
   248	            f"last release {max(sel).date()} ({tail_short}d short of the end). "
   249	            f"Tolerance is {MAX_WINDOW_SHORTFALL_DAYS}d. A truncated feed silently "
   250	            "shortens the sample while every printed count still agrees with itself."
   251	        )
   252	
   253	    # 3b: no month may vanish from inside the observed span.
   254	    span = {
   255	        p.strftime("%Y-%m")
   256	        for p in pd.period_range(start=min(sel), end=max(sel), freq="M")
   257	    }
   258	    missing = sorted(span - set(sel_months) - set(KNOWN_MISSING_MONTHS))
   259	    if missing:
   260	        raise RuntimeError(
   261	            f"official NFP calendar is missing {len(missing)} month(s) inside the observed "
   262	            f"span: {missing}. A partial calendar dumps real event days into the control "
   263	            "group silently. Add them to KNOWN_MISSING_MONTHS only with a documented "
   264	            "reason (e.g. a cancelled release), never to make this check pass."
   265	        )
   266	
   267	    # 4: a claimed hole must actually be a hole in the RAW feed. Without this the
   268	    # allowlist is a bypass: any month could be declared 'known missing' and the
   269	    # check would stop looking at it.
   270	    bogus = sorted(m for m in KNOWN_MISSING_MONTHS if m in span and raw_by_month.get(m))
   271	    if bogus:
   272	        raise RuntimeError(
   273	            f"KNOWN_MISSING_MONTHS claims {bogus} published nothing, but the raw feed has "
   274	            f"entries for them: { {m: [str(d.date()) for d in raw_by_month[m]] for m in bogus} }. "
   275	            "The allowlist is for real cancellations, not for silencing a selection bug."
   276	        )
   277	
   278	    return {
   279	        "n_months_in_span": len(span),
   280	        "n_raw_entries": len(raw),
   281	        "months_with_multiple_raw_entries": sorted(multi),
   282	        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
   283	        "known_missing_months": {m: KNOWN_MISSING_MONTHS[m] for m in sorted(KNOWN_MISSING_MONTHS)},
   284	        "window_coverage": {
   285	            "requested": f"{start}..{end}",
   286	            "observed": f"{min(sel).date()}..{max(sel).date()}",
   287	            "head_shortfall_days": int(head_short),
   288	            "tail_shortfall_days": int(tail_short),
   289	            "tolerance_days": MAX_WINDOW_SHORTFALL_DAYS,
   290	        },
   291	        "residual_limitation": (
   292	            "Same-month selection uses 'earliest wins', which is a heuristic. It cannot "
   293	            "distinguish an off-cycle item filed BEFORE the report from the report itself, "
   294	            "so every multi-entry month must additionally appear in "
   295	            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A "
   296	            "new multi-entry month fails the run rather than being assumed."
   297	        ),
   298	    }
   299	
   300	
   301	def load_nfp_dates(start=SAMPLE_START, end=SAMPLE_END):
   302	    """Official NFP (Employment Situation) release dates.
   303	
   304	    Deliberately has no except branch. If the release calendar cannot be
   305	    reached, this run must die -- a proxy calendar produces plausible numbers
   306	    from non-events, which is worse than no numbers at all. See the CORRECTION
   307	    note in the module docstring.
   308	    """
   309	    dates = nfp_release_dates(start, end)
   310	    if len(dates) == 0:
   311	        raise RuntimeError(f"official NFP calendar returned nothing for {start}..{end}")
   312	    # Pull the unselected feed as well: the accessor collapses each month to one
   313	    # date, so the only place a same-month ambiguity is still visible is here.
   314	    raw = _fetch(RELEASE_IDS["NFP_US"], start, end)
   315	    completeness = check_calendar_is_complete(dates, raw, start, end)
   316	    return list(dates), completeness
   317	
   318	
   319	# ============================================================
   320	# 2. Download data
   810	# ============================================================
   811	# 9b. Correction audit: every published number, before vs after
   812	# ============================================================
   813	# A mean can sit still while the median and the win rate move underneath it,
   814	# so no claim is judged on its mean alone. Each item carries mean / median /
   815	# win rate / n / significance, and the flip test looks at all of them.
   816	print(f"\n{'=' * 60}")
   817	print("CORRECTION AUDIT (proxy first-Friday -> official BLS calendar)")
   818	print("=" * 60)
   819	
   820	PROXY_PATH = Path(__file__).parent / "k528_nfp_event_study_results_PROXY_SUPERSEDED.json"
   821	if not PROXY_PATH.exists():
   822	    raise FileNotFoundError(
   823	        f"{PROXY_PATH.name} is missing. It is the archived proxy-era result and the "
   824	        "only record of what the published article claimed. Do not regenerate it."
   825	    )
   826	proxy = json.loads(PROXY_PATH.read_text())
   827	
   828	
   829	def win_rate(sample, reference):
   830	    """Share of `sample` above the median of `reference` (0.5 under the null)."""
   831	    ref_med = float(np.median(reference))
   832	    return float(np.mean(np.asarray(sample) > ref_med))
   833	
   834	
   835	# The proxy run only ever reported means, and a mean can hold still while the
   836	# median and the win rate move underneath it. Rather than leave the before-side
   837	# of those two columns null -- which would make the comparison unable to detect
   838	# exactly the failure it is looking for -- rebuild the proxy-era distributions
   839	# from the ARCHIVED per-event data. The dates come out of the archive, so this
   840	# reconstructs history without reintroducing a proxy calendar generator.
   841	proxy_events = proxy["event_data"]
   842	proxy_nfp_abs = np.array([e["event_abs_return"] for e in proxy_events])
   843	proxy_event_dates = pd.DatetimeIndex([pd.Timestamp(e["date"]) for e in proxy_events])
   844	
   845	# The archive holds the proxy run's ANALYSED events, which is not the same as
   846	# its NFP sessions: the proxy also had a January-2005 event that its own
   847	# window-buffer dropped, and leaving that day in the proxy control group is the
   848	# identical leak just repaired on the official side (Codex v3 round-2 BLOCKER 1).
   849	# Reconstructing it needs the first-Friday rule for exactly the months the
   850	# archive does not cover. That is legitimate here and only here: the audit's job
   851	# IS to reconstruct what the superseded run did. It is not reintroduced as a
   852	# data source -- every analysed date still comes from the archive.
   853	_archive_months = {d.strftime("%Y-%m") for d in proxy_event_dates}
   854	_sample_months = [
   855	    p.strftime("%Y-%m")
   856	    for p in pd.period_range(start=pd.Timestamp(SAMPLE_START), end=pd.Timestamp(SAMPLE_END), freq="M")
   857	]
   858	_proxy_extra_sessions = []
   859	for _m in _sample_months:
   860	    if _m in _archive_months:
   861	        continue
   862	    _y, _mm = int(_m[:4]), int(_m[5:])
   863	    _first = pd.Timestamp(year=_y, month=_mm, day=1)
   864	    _ff = _first + pd.Timedelta(days=(4 - _first.weekday()) % 7)   # first Friday
   865	    _cand = trading_dates[(trading_dates >= _ff) & (trading_dates <= _ff + pd.Timedelta(days=3))]
   866	    if len(_cand):
   867	        _proxy_extra_sessions.append(_cand[0])
   868	
   869	proxy_all_sessions = set(proxy_event_dates) | set(_proxy_extra_sessions)
   870	# The reconstruction must only ADD window-dropped months, never move an analysed
   871	# one; and the months it adds must be exactly those the archive is missing.
   872	if not set(proxy_event_dates) <= proxy_all_sessions:
   873	    raise AssertionError("proxy session reconstruction dropped an archived event")
   874	if len(proxy_all_sessions) != len(proxy_event_dates) + len(_proxy_extra_sessions):
   875	    raise AssertionError("proxy session reconstruction collided with an archived event")
   876	proxy_non_nfp = spy[~spy.index.isin(proxy_all_sessions)]
   877	proxy_non_nfp_abs = proxy_non_nfp["AbsReturn"].values
   878	proxy_fri_abs = proxy_non_nfp[proxy_non_nfp.index.weekday == 4]["AbsReturn"].values
   879	
   880	# Two proxy control groups, deliberately, because they answer different questions:
   881	#   _archive  -- excludes only the archive's ANALYSED events. Reproduces the
   882	#                published proxy-era means, which is how we verify the
   883	#                reconstruction is reading the archive correctly.
   884	#   (above)   -- also excludes the proxy's window-dropped session. Leak-free, so
   885	#                it is what the before/after comparison uses.
   886	# Keeping only the first would carry the leak into the audit; keeping only the
   887	# second would silently discard the faithfulness check.
   888	proxy_non_nfp_archive = spy[~spy.index.isin(set(proxy_event_dates))]
   889	proxy_non_nfp_abs_archive = proxy_non_nfp_archive["AbsReturn"].values
   890	_leak_sessions = sorted(str(d.date()) for d in _proxy_extra_sessions)
   891	if len(proxy_non_nfp_archive) - len(proxy_non_nfp) != len(_proxy_extra_sessions):
   892	    raise AssertionError("proxy control groups differ by something other than the reconstructed sessions")
   893	
   894	# The proxy calendar was all-Friday by construction, but 15 of its 254 events
   895	# mapped to a Monday because the first Friday was a market holiday. So the
   896	# proxy-era Friday test was ALREADY weekday-mixed. To compare like with like,
   897	# rebuild the proxy side under the SAME estimand the corrected run uses
   898	# (Friday events only) rather than comparing a mixed `before` against a
   899	# restricted `after` and calling the difference a correction effect.
   900	_p_weekday = np.array([pd.Timestamp(e["date"]).weekday() for e in proxy_events])
   901	proxy_nfp_friday_abs = proxy_nfp_abs[_p_weekday == 4]
   902	_p_t_fri, _p_p_fri = stats.ttest_ind(proxy_nfp_friday_abs, proxy_fri_abs, equal_var=False)
   903	proxy_ratio_fri_restricted = float(proxy_nfp_friday_abs.mean() / proxy_fri_abs.mean())
   904	
   905	_p_pre_vix = np.array([e["pre_vix"] if e["pre_vix"] is not None else np.nan
   906	                       for e in proxy_events])
   907	_p_thr = proxy["regime_analysis"]["vix_median_split"]
   908	proxy_high_abs = proxy_nfp_abs[_p_pre_vix >= _p_thr]
   909	proxy_low_abs = proxy_nfp_abs[_p_pre_vix < _p_thr]
   910	
   911	# Sanity: the rebuilt means must reproduce the archived means, otherwise the
   912	# reconstruction is wrong and its medians cannot be trusted either. The baseline
   913	# is checked against the ARCHIVE'S control definition -- the leak-free one is a
   914	# deliberate departure from what was published, so holding it to the published
   915	# value would just re-import the leak.
   916	for _label, _rebuilt, _archived in (
   917	    ("nfp mean", proxy_nfp_abs.mean(), proxy["main_results"]["nfp_avg_abs_return"]),
   918	    ("baseline mean", proxy_non_nfp_abs_archive.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   919	    ("high-vix mean", proxy_high_abs.mean(), proxy["regime_analysis"]["high_vix_nfp_abs_return"]),
   920	    ("low-vix mean", proxy_low_abs.mean(), proxy["regime_analysis"]["low_vix_nfp_abs_return"]),
   921	):
   922	    if not np.isclose(_rebuilt, _archived, rtol=1e-6):
   923	        raise AssertionError(
   924	            f"proxy reconstruction mismatch on {_label}: rebuilt {_rebuilt:.8f} "
   925	            f"vs archived {_archived:.8f}. Refusing to report medians derived "
   926	            "from a reconstruction that cannot reproduce the archived means."
   927	        )
   928	print("  proxy-era distributions reconstructed from archive (means reproduce)")
   929	print(f"  proxy control group additionally excludes {len(_proxy_extra_sessions)} "
   930	      f"window-dropped NFP session(s): {_leak_sessions}")
   931	
   932	audit_items = {}
   933	
   934	
   935	def record(key, label, before, after, note=""):
   936	    audit_items[key] = {"label": label, "before": before, "after": after, "note": note}
   937	
   938	
   939	# --- 1.10x : NFP vs all non-NFP days ---
   940	record(
   941	    "vol_ratio_vs_all", "NFP vs all non-NFP days (article: 1.10x)",
   942	    {
   943	        "mean_ratio": proxy["main_results"]["vol_ratio_vs_all"],
   944	        "nfp_mean": proxy["main_results"]["nfp_avg_abs_return"],
   945	        "baseline_mean": proxy["main_results"]["non_nfp_avg_abs_return"],
   946	        "p_value": proxy["statistical_tests"]["A_nfp_vs_all"]["p_value"],
   947	        "significant_5pct": proxy["statistical_tests"]["A_nfp_vs_all"]["significant_5pct"],
   948	        "n": proxy["sample"]["total_nfp_events"],
   949	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   950	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   951	    },
   952	    {
   953	        "mean_ratio": vol_ratio_all,
   954	        "nfp_mean": float(nfp_abs_returns.mean()),
   955	        "baseline_mean": baseline_abs_return,
   956	        "p_value": float(p_val_all),
   957	        "significant_5pct": bool(p_val_all < 0.05),
   958	        "n": int(len(df)),
   959	        "median_ratio": float(np.median(nfp_abs_returns) / np.median(non_nfp_abs_returns)),
   960	        "win_rate": win_rate(nfp_abs_returns, non_nfp_abs_returns),
   961	    },
   962	    note="proxy-side median_ratio / win_rate are reconstructed from the archived "
   963	         "per-event data, not from the proxy run's own output (it only reported means).",
   964	)
   965	
   966	# --- 1.17x : NFP vs Friday-only baseline ---
   967	record(
   968	    "vol_ratio_vs_friday", "NFP vs non-NFP Friday baseline (article: 1.17x)",
   969	    {
   970	        # Same estimand as the `after` column: Friday events only.
   971	        "mean_ratio": proxy_ratio_fri_restricted,
   972	        "p_value": float(_p_p_fri),
   973	        "significant_5pct": bool(_p_p_fri < 0.05),
   974	        "n": int(len(proxy_nfp_friday_abs)),
   975	        "nfp_days_on_friday": int((_p_weekday == 4).sum()),
   976	        "median_ratio": float(np.median(proxy_nfp_friday_abs) / np.median(proxy_fri_abs)),
   977	        "win_rate": win_rate(proxy_nfp_friday_abs, proxy_fri_abs),
   978	        "n_control_friday": int(len(proxy_fri_abs)),
   979	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   980	        "as_published_mixed_weekday": {
   981	            "mean_ratio": proxy["main_results"]["vol_ratio_vs_friday"],
   982	            "p_value": proxy["statistical_tests"]["B_nfp_vs_friday"]["p_value"],
   983	            "significant_5pct": proxy["statistical_tests"]["B_nfp_vs_friday"]["significant_5pct"],
   984	            "n": proxy["sample"]["total_nfp_events"],
   985	            "note": (
   986	                "what the proxy run actually published: all 254 events (239 Friday, "
   987	                "15 Monday) against non-NFP Fridays. This is the number the article "
   988	                "quoted, so it is kept, but it is NOT the like-for-like comparison "
   989	                "against the corrected column."
   990	            ),
   991	        },
   992	    },
   993	    {
   994	        "mean_ratio": vol_ratio_fri,
   995	        "p_value": float(p_val_fri),
   996	        "significant_5pct": bool(p_val_fri < 0.05),
   997	        "n": int(len(nfp_friday_abs)),
   998	        "nfp_days_on_friday": int((df["weekday"] == 4).sum()),
   999	        "median_ratio": float(np.median(nfp_friday_abs) / np.median(friday_non_nfp_abs)),
  1000	        "win_rate": win_rate(nfp_friday_abs, friday_non_nfp_abs),
  1001	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
  1002	        "diagnostic_mixed_weekday": {
  1003	            "mean_ratio": vol_ratio_fri_mixed,
  1004	            "p_value": float(p_val_fri_mixed),
  1005	            "significant_5pct": bool(p_val_fri_mixed < 0.05),
  1006	            "n": int(len(df)),
  1007	            "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable",
  1008	        },
  1009	    },
  1010	    note="Two things changed here and they are separated rather than conflated. "
  1011	         "(1) The dates were corrected. (2) The ESTIMAND was corrected: the "
  1012	         "event group is a weekday mixture while the control group is pure "
  1013	         "Friday, so the test now restricts the event group to Friday releases. "
  1014	         "Defect (2) was NOT created by (1) -- the proxy run was already mixed "
  1015	         "(239/254 Friday, the other 15 being holiday-shifted Mondays), it was "
  1016	         "simply never noticed. Both columns above therefore use the SAME "
  1017	         "restricted estimand so the delta is attributable to the dates alone; "
  1018	         "`as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` "
  1019	         "(after) hold the old estimand on each side for reference.",
  1020	)
  1021	
  1022	# --- 2.17x : high-VIX vs low-VIX regime ---
  1023	proxy_reg = proxy["regime_analysis"]
  1024	record(
  1025	    "regime_ratio", "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
  1026	    {
  1027	        "mean_ratio": proxy_reg["high_vix_nfp_abs_return"] / proxy_reg["low_vix_nfp_abs_return"],
  1028	        "high_mean": proxy_reg["high_vix_nfp_abs_return"],
  1029	        "low_mean": proxy_reg["low_vix_nfp_abs_return"],
  1030	        "n_high": proxy_reg["n_high"],

exec
/bin/zsh -lc "repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

rg --files /Users/yhlai0911/volpred-research /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp | rg -i '("'^|/)(spy|vix)|spy.*'"\\.(csv|parquet|json)|snapshot' | head -n 240

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_official_dates_results.json" | nl -ba | sed -n '"'1,230p'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_event_study_results.json" | nl -ba | sed -n '"'1,180p'

git -C \""'$repo" show "${commit}:experiments/k528/build_article_correction.py" | nl -ba | sed -n '"'1,390p'" in /Users/yhlai0911/volpred-research
 succeeded in 124ms:
     1	{
     2	  "experiment_id": "K528",
     3	  "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
     4	  "generated_at": "2026-07-19T08:53:23.055332+00:00",
     5	  "before_source": "k528_nfp_event_study_results_PROXY_SUPERSEDED.json",
     6	  "after_source": "k528_nfp_event_study_results.json",
     7	  "event_date_source": {
     8	    "source": "official BLS release calendar via ALFRED (FRED release id 50)",
     9	    "accessor": "volpred.data.event_dates.nfp_release_dates",
    10	    "fallback": "none - the run raises if the calendar is unreachable",
    11	    "supersedes": "first-Friday-of-month proxy (wrong on ~20% of dates)"
    12	  },
    13	  "calendar_diff": {
    14	    "proxy_only_dates": [
    15	      "2005-07-01",
    16	      "2006-03-03",
    17	      "2006-12-01",
    18	      "2007-03-02",
    19	      "2008-07-07",
    20	      "2009-01-02",
    21	      "2009-05-01",
    22	      "2009-07-06",
    23	      "2010-01-04",
    24	      "2010-10-01",
    25	      "2011-07-01",
    26	      "2012-03-02",
    27	      "2013-03-01",
    28	      "2013-10-04",
    29	      "2013-11-01",
    30	      "2014-01-03",
    31	      "2014-07-07",
    32	      "2015-01-02",
    33	      "2015-05-01",
    34	      "2015-07-06",
    35	      "2016-01-04",
    36	      "2016-07-01",
    37	      "2017-03-03",
    38	      "2017-12-01",
    39	      "2018-03-02",
    40	      "2019-03-01",
    41	      "2020-01-03",
    42	      "2020-05-01",
    43	      "2020-07-06",
    44	      "2021-01-04",
    45	      "2021-10-01",
    46	      "2022-07-01",
    47	      "2023-03-03",
    48	      "2023-12-01",
    49	      "2024-03-01",
    50	      "2025-01-03",
    51	      "2025-07-07",
    52	      "2025-10-03",
    53	      "2025-11-07",
    54	      "2025-12-05",
    55	      "2026-01-02",
    56	      "2026-02-06"
    57	    ],
    58	    "official_only_dates": [
    59	      "2005-07-08",
    60	      "2006-03-10",
    61	      "2006-12-08",
    62	      "2007-03-09",
    63	      "2008-07-03",
    64	      "2009-01-09",
    65	      "2009-05-08",
    66	      "2009-07-02",
    67	      "2010-01-08",
    68	      "2010-10-08",
    69	      "2011-07-08",
    70	      "2012-03-09",
    71	      "2013-03-08",
    72	      "2013-10-22",
    73	      "2013-11-08",
    74	      "2014-01-10",
    75	      "2014-07-03",
    76	      "2015-01-09",
    77	      "2015-05-08",
    78	      "2015-07-02",
    79	      "2016-01-08",
    80	      "2016-07-08",
    81	      "2017-03-10",
    82	      "2017-12-08",
    83	      "2018-03-09",
    84	      "2019-03-08",
    85	      "2020-01-10",
    86	      "2020-05-08",
    87	      "2020-07-02",
    88	      "2021-01-08",
    89	      "2021-10-08",
    90	      "2022-07-08",
    91	      "2023-03-10",
    92	      "2023-12-08",
    93	      "2024-03-08",
    94	      "2025-01-10",
    95	      "2025-07-03",
    96	      "2025-11-20",
    97	      "2025-12-16",
    98	      "2026-01-09",
    99	      "2026-02-11"
   100	    ],
   101	    "dates_in_common": 212,
   102	    "n_proxy": 254,
   103	    "n_official": 253,
   104	    "nfp_days_on_friday_official": 237
   105	  },
   106	  "win_rate_definition": "share of the sample exceeding the MEDIAN of its comparison group; 0.5 under the null",
   107	  "items": {
   108	    "vol_ratio_vs_all": {
   109	      "label": "NFP vs all non-NFP days (article: 1.10x)",
   110	      "before": {
   111	        "mean_ratio": 1.1035360772013734,
   112	        "nfp_mean": 0.008420922409653335,
   113	        "baseline_mean": 0.0076308537469923455,
   114	        "p_value": 0.1283682008960355,
   115	        "significant_5pct": false,
   116	        "n": 254,
   117	        "median_ratio": 1.1884376842166304,
   118	        "win_rate": 0.5551181102362205
   119	      },
   120	      "after": {
   121	        "mean_ratio": 1.1077777719197994,
   122	        "nfp_mean": 0.00845305173732809,
   123	        "baseline_mean": 0.0076306385193835365,
   124	        "p_value": 0.11206802266548598,
   125	        "significant_5pct": false,
   126	        "n": 253,
   127	        "median_ratio": 1.191581334504972,
   128	        "win_rate": 0.5612648221343873
   129	      },
   130	      "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
   131	      "verdict": "NUMERIC_ADJUSTMENT",
   132	      "verdict_reasons": []
   133	    },
   134	    "vol_ratio_vs_friday": {
   135	      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
   136	      "before": {
   137	        "mean_ratio": 1.166705672588405,
   138	        "p_value": 0.04213984873387389,
   139	        "significant_5pct": true,
   140	        "n": 239,
   141	        "nfp_days_on_friday": 239,
   142	        "median_ratio": 1.1979193428374169,
   143	        "win_rate": 0.5564853556485355,
   144	        "n_control_friday": 832,
   145	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   146	        "as_published_mixed_weekday": {
   147	          "mean_ratio": 1.168212716801256,
   148	          "p_value": 0.03354366521379227,
   149	          "significant_5pct": true,
   150	          "n": 254,
   151	          "note": "what the proxy run actually published: all 254 events (239 Friday, 15 Monday) against non-NFP Fridays. This is the number the article quoted, so it is kept, but it is NOT the like-for-like comparison against the corrected column."
   152	        }
   153	      },
   154	      "after": {
   155	        "mean_ratio": 1.1889932285781484,
   156	        "p_value": 0.02085474364987024,
   157	        "significant_5pct": true,
   158	        "n": 237,
   159	        "nfp_days_on_friday": 237,
   160	        "median_ratio": 1.2185765501135915,
   161	        "win_rate": 0.569620253164557,
   162	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   163	        "diagnostic_mixed_weekday": {
   164	          "mean_ratio": 1.1767600146677832,
   165	          "p_value": 0.025693120973358435,
   166	          "significant_5pct": true,
   167	          "n": 253,
   168	          "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
   169	        }
   170	      },
   171	      "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to Friday releases. Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
   172	      "verdict": "NUMERIC_ADJUSTMENT",
   173	      "verdict_reasons": []
   174	    },
   175	    "regime_ratio": {
   176	      "label": "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   177	      "before": {
   178	        "mean_ratio": 2.1670599373202153,
   179	        "high_mean": 0.011524027931522324,
   180	        "low_mean": 0.005317816887784345,
   181	        "n_high": 127,
   182	        "n_low": 127,
   183	        "p_value": 2.8361186837189765e-10,
   184	        "significant_5pct": true,
   185	        "median_ratio": 2.2653573776192792,
   186	        "win_rate": 0.7165354330708661
   187	      },
   188	      "after": {
   189	        "mean_ratio": 2.0272689852570607,
   190	        "high_mean": 0.011276125213428842,
   191	        "low_mean": 0.005562224497800924,
   192	        "n_high": 128,
   193	        "n_low": 125,
   194	        "p_value": 4.554489029639581e-09,
   195	        "significant_5pct": true,
   196	        "median_ratio": 2.073364952892548,
   197	        "win_rate": 0.6953125
   198	      },
   199	      "note": "",
   200	      "verdict": "NUMERIC_ADJUSTMENT",
   201	      "verdict_reasons": []
   202	    },
   203	    "vix_correlation": {
   204	      "label": "Pre-event VIX vs event-day |return| (article: r=0.45)",
   205	      "before": {
   206	        "pearson_r": 0.45116558631194703,
   207	        "pearson_p": 3.854493703611817e-14,
   208	        "spearman_rho": 0.3766062270606868,
   209	        "spearman_p": 5.561878132730772e-10,
   210	        "slope_pct_per_vix_pt": 0.04387491083793095,
   211	        "n": 254,
   212	        "significant_5pct": true
   213	      },
   214	      "after": {
   215	        "pearson_r": 0.4404312353143255,
   216	        "pearson_p": 1.9831312019194168e-13,
   217	        "spearman_rho": 0.3455048873701663,
   218	        "spearman_p": 1.6699985504624933e-08,
   219	        "slope_pct_per_vix_pt": 0.04256117035047841,
   220	        "n": 253,
   221	        "significant_5pct": true
   222	      },
   223	      "note": "",
   224	      "verdict": "NUMERIC_ADJUSTMENT",
   225	      "verdict_reasons": []
   226	    },
   227	    "vix_median_threshold": {
   228	      "label": "VIX median split (article: 16.71)",
   229	      "before": {
   230	        "threshold": 16.710000038146973,
     1	{
     2	  "experiment_id": "K528",
     3	  "title": "NFP Event Study on SPY Volatility",
     4	  "date": "2026-07-19T08:53:23.047676+00:00",
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
    41	      "reviewed_multi_entry_months": {
    42	        "2006-05": "2006-05-05",
    43	        "2012-12": "2012-12-07",
    44	        "2013-05": "2013-05-03",
    45	        "2020-05": "2020-05-08",
    46	        "2024-01": "2024-01-05",
    47	        "2024-08": "2024-08-02"
    48	      },
    49	      "known_missing_months": {
    50	        "2025-10": "Federal government shutdown. ALFRED shows no release id 50 entry between 2025-09-05 and 2025-11-20 (76 days against a ~30-day cadence); the delayed September report landed on 11-20. Same shutdown that cancelled the Oct-2025 CPI release described in volpred/data/event_dates.py. The first-Friday proxy INVENTED an event here -- that phantom is one of the reasons for this rerun."
    51	      },
    52	      "window_coverage": {
    53	        "requested": "2005-01-01..2026-03-27",
    54	        "observed": "2005-01-07..2026-03-06",
    55	        "head_shortfall_days": 6,
    56	        "tail_shortfall_days": 21,
    57	        "tolerance_days": 70
    58	      },
    59	      "residual_limitation": "Same-month selection uses 'earliest wins', which is a heuristic. It cannot distinguish an off-cycle item filed BEFORE the report from the report itself, so every multi-entry month must additionally appear in REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new multi-entry month fails the run rather than being assumed."
    60	    },
    61	    "total_trading_days": 5340,
    62	    "control_group_excludes_all_nfp_sessions": true
    63	  },
    64	  "main_results": {
    65	    "nfp_avg_abs_return": 0.00845305173732809,
    66	    "nfp_avg_abs_return_pct": "0.845%",
    67	    "non_nfp_avg_abs_return": 0.0076306385193835365,
    68	    "non_nfp_avg_abs_return_pct": "0.763%",
    69	    "friday_baseline_abs_return": 0.007183326788779879,
    70	    "vol_ratio_vs_all": 1.1077777719197994,
    71	    "vol_ratio_vs_friday": 1.1889932285781484
    72	  },
    73	  "statistical_tests": {
    74	    "A_nfp_vs_all": {
    75	      "test": "Welch t-test",
    76	      "t_stat": 1.5938578801792924,
    77	      "p_value": 0.11206802266548598,
    78	      "significant_5pct": false
    79	    },
    80	    "B_nfp_vs_friday": {
    81	      "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
    82	      "estimand": "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event group is restricted to NFP releases that trade on a Friday, and the 16 non-Friday events are excluded rather than compared against a pure-Friday control group.",
    83	      "claim_scope": "This identifies the effect of an NFP release ON A FRIDAY. It does not license a statement about NFP releases in general -- the excluded non-Friday events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec. Any prose quoting this number must say 'Friday NFP', not 'NFP'.",
    84	      "restriction_is_not_neutral": {
    85	        "excluded_mean_abs_return": 0.0071514007343742095,
    86	        "friday_mean_abs_return": 0.008540926910523291,
    87	        "excluded_are_quieter_by_pct": 16.2690325149258
    88	      },
    89	      "n_event": 237,
    90	      "n_control": 834,
    91	      "vol_ratio": 1.1889932285781484,
    92	      "t_stat": 2.3205002846661813,
    93	      "p_value": 0.02085474364987024,
    94	      "significant_5pct": true,
    95	      "excluded_non_friday_events": {
    96	        "n": 16,
    97	        "mean_abs_return": 0.0071514007343742095
    98	      }
    99	    },
   100	    "B_diagnostic_mixed_weekday": {
   101	      "test": "Welch t-test, ALL NFP events vs Friday non-NFP sessions",
   102	      "status": "DIAGNOSTIC ONLY - do not quote",
   103	      "why_not_a_headline": "this is the pre-correction specification: a weekday-mixed event group against a pure-Friday control group, so the p-value absorbs any Friday-vs-other-weekday volatility difference. Retained solely so the correction audit can show what the contaminated estimand was worth (k528 Codex v2 finding 5).",
   104	      "vol_ratio": 1.1767600146677832,
   105	      "t_stat": 2.2390040983599286,
   106	      "p_value": 0.025693120973358435,
   107	      "significant_5pct": true
   108	    },
   109	    "C_wilcoxon": {
   110	      "test": "Mann-Whitney U (one-sided)",
   111	      "u_stat": 712481.0,
   112	      "p_value": 0.0019400634362338727,
   113	      "significant_5pct": true
   114	    },
   115	    "D_vol_crush": {
   116	      "test": "One-sample t-test (post-pre diff)",
   117	      "pre_avg": 0.00778702974686821,
   118	      "post_avg": 0.007687347886443663,
   119	      "diff": -9.96818604245466e-05,
   120	      "t_stat": -0.31073754484649485,
   121	      "p_value": 0.7562570171779246,
   122	      "vol_crush_present": false
   123	    },
   124	    "E_vix_predictive": {
   125	      "test": "Pearson + Spearman correlation",
   126	      "pearson_r": 0.4404312353143255,
   127	      "pearson_p": 1.9831312019194168e-13,
   128	      "spearman_rho": 0.3455048873701663,
   129	      "spearman_p": 1.6699985504624933e-08,
   130	      "slope": 0.0004256117035047841,
   131	      "interpretation": "1pt VIX \u2192 0.0426% more |return|"
   132	    },
   133	    "F_vix_buildup": {
   134	      "test": "One-sample t-test (T-5 to T-1 VIX change)",
   135	      "mean_change": 0.08312253989721004,
   136	      "t_stat": 0.44978438962865197,
   137	      "p_value": 0.653252559944604,
   138	      "anticipatory_buildup": false
   139	    }
   140	  },
   141	  "seasonal_analysis": {
   142	    "1": {
   143	      "n": 21,
   144	      "mean_abs_return": 0.009459348442190096,
   145	      "vol_ratio": 1.2396535910017525,
   146	      "t_stat": 0.9409739025138122,
   147	      "p_val": 0.35794574604870977
   148	    },
   149	    "2": {
   150	      "n": 22,
   151	      "mean_abs_return": 0.009030613767434338,
   152	      "vol_ratio": 1.1834676409444045,
   153	      "t_stat": 0.8868121055542058,
   154	      "p_val": 0.3852237335361376
   155	    },
   156	    "3": {
   157	      "n": 22,
   158	      "mean_abs_return": 0.008502231993214836,
   159	      "vol_ratio": 1.1142228755322712,
   160	      "t_stat": 0.7027072841706888,
   161	      "p_val": 0.4899553292992369
   162	    },
   163	    "4": {
   164	      "n": 21,
   165	      "mean_abs_return": 0.01001666165281377,
   166	      "vol_ratio": 1.3126898394373154,
   167	      "t_stat": 0.883662390835162,
   168	      "p_val": 0.38737772260019515
   169	    },
   170	    "5": {
   171	      "n": 21,
   172	      "mean_abs_return": 0.009901525382701741,
   173	      "vol_ratio": 1.2976011584809897,
   174	      "t_stat": 1.7028571998111124,
   175	      "p_val": 0.10408664420681253
   176	    },
   177	    "6": {
   178	      "n": 21,
   179	      "mean_abs_return": 0.011283799381632011,
   180	      "vol_ratio": 1.4787490395421858,
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

codex
已找到兩個具體風險形狀：70 天容忍度可讓端點整月消失；而已列入 reviewed allowlist 的月份若 raw feed 後來多出一筆較晚、且只差 1–2 天的條目，現行程式會照樣通過——舊 gap gate 反而會擋。另發現兩個 proxy 控制組在 all-days audit 內混用：mean/p 取歷史洩漏組，median/win 取 leak-free 組；Friday 主項本身則已改對。接著用 production helper 實測這些反例並跑固定測試。
exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

git -C "$repo" show "${commit}:src/volpred/data/event_dates.py" | nl -ba | sed -n '"'1,230p'

git -C \""'$repo" show "${commit}:tests/test_event_dates_release_selection.py" | nl -ba | sed -n '"'1,320p'

git -C \""'$repo" show "${commit}:tests/test_event_dates_real_raw_response.py" | nl -ba | sed -n '"'1,340p'

git -C \""'$repo" show "${commit}:tests/test_nfp_official_release_dates.py" | nl -ba | sed -n '"'500,790p'" in /Users/yhlai0911/volpred-research
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
   500	# ---------------------------------------------------------------------------
   501	# Holes found by Codex v3 against commit 6fd281901. Each of these shipped once
   502	# with a green suite, so each gets an assertion rather than a comment.
   503	# ---------------------------------------------------------------------------
   504	
   505	
   506	def _k528_module():
   507	    """Load the k528 script's functions and literal constants without running
   508	    the analysis body (which downloads data and would need a live API key).
   509	
   510	    Constants are selected by "is it a literal?", not by a hand-maintained name
   511	    list. The name-list version silently dropped every constant added after it
   512	    was written, and a helper that quietly omits what it is supposed to load
   513	    makes the tests exercise something other than the production code path.
   514	    """
   515	    import ast
   516	    import types
   517	
   518	    def _is_literal_assignment(node):
   519	        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or node.value is None:
   520	            return False
   521	        try:
   522	            ast.literal_eval(node.value)
   523	        except (ValueError, SyntaxError):
   524	            return False  # silent-ok: "is this a literal?" probe; a non-literal is the expected answer, not a failure
   525	        return True
   526	
   527	    src = K528_PY.read_text(encoding="utf-8")
   528	    tree = ast.parse(src)
   529	    keep = [
   530	        n for n in tree.body
   531	        if isinstance(n, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef))
   532	        or _is_literal_assignment(n)
   533	    ]
   534	    mod = types.ModuleType("k528_helpers")
   535	    exec(compile(ast.Module(body=keep, type_ignores=[]), "k528", "exec"), mod.__dict__)
   536	    # Guard the loader: if this ever silently stops loading what the tests need,
   537	    # the tests below would pass vacuously or error confusingly.
   538	    for required in ("check_calendar_is_complete", "KNOWN_MISSING_MONTHS",
   539	                     "REVIEWED_MULTI_ENTRY_MONTHS", "MAX_WINDOW_SHORTFALL_DAYS"):
   540	        assert hasattr(mod, required), f"_k528_module failed to load {required}"
   541	    return mod
   542	
   543	
   544	class TestControlGroupHasNoNfpDays:
   545	    """A real NFP session sitting in the control group is the exact failure this
   546	    experiment exists to document -- it just happened at 1/253 scale instead of
   547	    46/254, via an event dropped for lacking a pre-window but never removed from
   548	    the baseline."""
   549	
   550	    def test_every_mapped_nfp_session_is_excluded_from_the_control_group(self):
   551	        """Assert against an INDEPENDENTLY recorded total.
   552	
   553	        The first version of this test defined total = controls + mapped and
   554	        then asserted controls == total - mapped, which is an algebraic identity
   555	        that passes for any value of controls -- including the leaking 5087 it
   556	        was written to catch. A test that cannot fail is worse than no test: it
   557	        reads as coverage. (Codex v3 round-2 finding 3.)
   558	        """
   559	        sample = _load_k528(K528_RESULTS)["sample"]
   560	        audit = sample["event_mapping_audit"]
   561	        total = sample["total_trading_days"]
   562	        assert total == 5340, "pinned SPY session count for this sample window"
   563	        assert sample["non_nfp_trading_days"] == total - audit["n_mapped_to_sessions"] == 5086, (
   564	            "control group must exclude ALL mapped NFP sessions, not just the ones "
   565	            "that survived the event-window filter (5087 was the leaking value)"
   566	        )
   567	        assert sample["control_group_excludes_all_nfp_sessions"] is True
   568	
   569	    def test_proxy_side_control_group_is_also_clean(self):
   570	        """The same leak existed on the proxy side of the before/after audit:
   571	        the archive holds the proxy's ANALYSED events, not its NFP sessions."""
   572	        audit = _load_k528(K528_AUDIT)
   573	        before = audit["items"]["vol_ratio_vs_friday"]["before"]
   574	        assert before["n_control_friday"] == 832, (
   575	            "proxy Friday control count must exclude the proxy's own "
   576	            "window-dropped January-2005 session"
   577	        )
   578	
   579	    def test_window_excluded_event_is_not_silently_analysed_or_kept_as_control(self):
   580	        audit = _load_k528(K528_RESULTS)["sample"]["event_mapping_audit"]
   581	        assert audit["n_valid_events"] + audit["n_excluded_for_window_buffer"] == \
   582	            audit["n_mapped_to_sessions"]
   583	        assert audit["window_excluded_dates"], "the partition must name what it dropped"
   584	
   585	
   586	class TestCalendarFailClosedCannotBeBypassed:
   587	    """Codex v3 finding 3: validating only the accessor's OUTPUT cannot work,
   588	    because the accessor collapses each month to one date before any check on
   589	    the output can look for an ambiguity."""
   590	
   591	    @pytest.fixture
   592	    def check(self):
   593	        return _k528_module().check_calendar_is_complete
   594	
   595	    def test_off_cycle_entry_earlier_in_the_month_is_refused_not_silently_picked(self, check):
   596	        """The bypass: an off-cycle entry filed EARLIER than the report. A
   597	        per-month min() takes it without complaint and the cadence still passes.
   598	        Only the reviewed-month allowlist catches this -- a day-gap threshold
   599	        cannot, because three of the six real cases are 3 days apart."""
   600	        with pytest.raises(RuntimeError, match="never been"):
   601	            check(
   602	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   603	                ["2024-01-05", "2024-02-01", "2024-02-02", "2024-03-08"],
   604	                "2024-01-01", "2024-03-31",
   605	            )
   606	
   607	    def test_real_multi_entry_gaps_are_too_small_for_a_gap_rule(self):
   608	        """Pin the fact that killed the gap heuristic: 2006-05, 2013-05 and
   609	        2020-05 have the revision exactly 3 days after the report. Any future
   610	        'revisions are filed weeks later' rule is wrong on the real feed."""
   611	        import json
   612	
   613	        raw = json.loads(
   614	            (REPO_ROOT / "tests" / "fixtures" / "fred_release_50_nfp_raw_20260719.json")
   615	            .read_text(encoding="utf-8")
   616	        )["release_dates"]
   617	        by_month = {}
   618	        for d in raw:
   619	            by_month.setdefault(d[:7], []).append(d)
   620	        gaps = {
   621	            m: (pd.Timestamp(sorted(v)[1]) - pd.Timestamp(sorted(v)[0])).days
   622	            for m, v in by_month.items() if len(v) > 1
   623	        }
   624	        assert min(gaps.values()) == 3, gaps
   625	        assert sorted(m for m, g in gaps.items() if g == 3) == ["2006-05", "2013-05", "2020-05"]
   626	
   627	    def test_selection_that_is_not_the_earliest_entry_fails(self, check):
   628	        with pytest.raises(RuntimeError, match="did not select the earliest"):
   629	            check(
   630	                pd.to_datetime(["2024-01-05", "2024-02-09", "2024-03-08"]),
   631	                ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   632	                "2024-01-01", "2024-03-31",
   633	            )
   634	
   635	    def test_missing_month_inside_the_observed_span_fails(self, check):
   636	        """The old check exempted the first and last month unconditionally, so a
   637	        genuinely complete endpoint month could vanish for free."""
   638	        with pytest.raises(RuntimeError, match="missing 1 month"):
   639	            check(
   640	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
   641	                ["2024-01-05", "2024-02-02", "2024-04-05"],
   642	                "2024-01-01", "2024-04-30",
   643	            )
   644	
   645	    def test_allowlist_cannot_silence_a_month_that_has_data(self, check):
   646	        """KNOWN_MISSING_MONTHS is for real cancellations. If it is taken on
   647	        faith it is just a way to make a failing check pass."""
   648	        mod = _k528_module()
   649	        mod.KNOWN_MISSING_MONTHS["2024-03"] = "fabricated"
   650	        with pytest.raises(RuntimeError, match="claims"):
   651	            mod.check_calendar_is_complete(
   652	                pd.to_datetime(["2024-01-05", "2024-02-02", "2024-04-05"]),
   653	                ["2024-01-05", "2024-02-02", "2024-03-08", "2024-04-05"],
   654	                "2024-01-01", "2024-04-30",
   655	            )
   656	
   657	    def test_truncated_feed_cannot_hide_behind_its_own_shrunken_span(self, check):
   658	        """Anchoring the gap check on the OBSERVED span cannot catch truncation:
   659	        if the feed stops early the span shrinks with it and nothing looks
   660	        missing. Found by self-audit, not by a reviewer."""
   661	        dates = ["2024-01-05", "2024-02-02", "2024-03-08"]
   662	        with pytest.raises(RuntimeError, match="does not cover"):
   663	            check(pd.to_datetime(dates), dates, "2024-01-01", "2024-12-31")
   664	
   665	    def test_unreviewed_multi_entry_month_is_refused_not_guessed(self, check):
   666	        """'Earliest wins' cannot distinguish an off-cycle item filed BEFORE the
   667	        report from the report. A new multi-entry month must stop the run."""
   668	        with pytest.raises(RuntimeError, match="never been"):
   669	            check(
   670	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   671	                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
   672	                "2024-01-01", "2024-03-31",
   673	            )
   674	
   675	    def test_selection_contradicting_the_human_verified_date_fails(self):
   676	        mod = _k528_module()
   677	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = "2024-02-06"
   678	        with pytest.raises(RuntimeError, match="contradicts"):
   679	            mod.check_calendar_is_complete(
   680	                pd.to_datetime(["2024-01-05", "2024-02-01", "2024-03-08"]),
   681	                ["2024-01-05", "2024-02-01", "2024-02-06", "2024-03-08"],
   682	                "2024-01-01", "2024-03-31",
   683	            )
   684	
   685	    def test_a_reviewed_month_with_a_normal_revision_still_passes(self):
   686	        """The other half: a guard that rejects everything is as useless as one
   687	        that rejects nothing. A revision filed a week later, in a month someone
   688	        has checked against the BLS archive, must go through."""
   689	        mod = _k528_module()
   690	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = "2024-02-02"
   691	        out = mod.check_calendar_is_complete(
   692	            pd.to_datetime(["2024-01-05", "2024-02-02", "2024-03-08"]),
   693	            ["2024-01-05", "2024-02-02", "2024-02-09", "2024-03-08"],
   694	            "2024-01-01", "2024-03-31",
   695	        )
   696	        assert out["months_with_multiple_raw_entries"] == ["2024-02"]
   697	
   698	    def test_the_six_real_multi_entry_months_pass_on_the_real_feed(self):
   699	        """The strongest negative control available: the actual 264-entry ALFRED
   700	        feed, whose six duplicate months are exactly the reviewed ones."""
   701	        import json
   702	
   703	        mod = _k528_module()
   704	        raw = json.loads(
   705	            (REPO_ROOT / "tests" / "fixtures" / "fred_release_50_nfp_raw_20260719.json")
   706	            .read_text(encoding="utf-8")
   707	        )["release_dates"]
   708	        by_month = {}
   709	        for d in raw:
   710	            by_month.setdefault(d[:7], []).append(d)
   711	        sel = sorted(min(v) for v in by_month.values())
   712	        out = mod.check_calendar_is_complete(
   713	            pd.to_datetime(sel), raw, "2005-01-01", "2026-07-19"
   714	        )
   715	        assert out["months_with_multiple_raw_entries"] == sorted(
   716	            mod.REVIEWED_MULTI_ENTRY_MONTHS
   717	        )
   718	
   719	
   720	class TestFridayEstimandIsScopedHonestly:
   721	    """Codex v3 finding 4: restricting to Friday is a legitimate conditional
   722	    estimand, but it stops supporting statements about NFP releases in general,
   723	    and the restriction is not a neutral sample deletion."""
   724	
   725	    def test_results_scope_the_claim_to_friday_and_disclose_the_non_neutrality(self):
   726	        b = _load_k528(K528_RESULTS)["statistical_tests"]["B_nfp_vs_friday"]
   727	        assert "CONDITIONAL ON FRIDAY" in b["estimand"]
   728	        assert "Friday NFP" in b["claim_scope"]
   729	        nn = b["restriction_is_not_neutral"]
   730	        assert nn["excluded_are_quieter_by_pct"] > 0, (
   731	            "if the excluded events are quieter, the restriction RAISES the ratio "
   732	            "and that must be stated, not discovered by a reviewer"
   733	        )
   734	
   735	    def test_excluded_count_matches_the_weekday_breakdown(self):
   736	        """The results file once said 11 in prose and 16 in data."""
   737	        results = _load_k528(K528_RESULTS)
   738	        b = results["statistical_tests"]["B_nfp_vs_friday"]
   739	        non_friday = sum(1 for e in results["event_data"] if e["weekday"] != 4)
   740	        assert b["excluded_non_friday_events"]["n"] == non_friday == 16
   741	        assert str(non_friday) in b["estimand"]

exec
/bin/zsh -lc 'uv run pytest -q tests/test_nfp_official_release_dates.py tests/test_event_dates_real_raw_response.py tests/test_event_dates_release_selection.py' in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 2906ms:
..................................................................       [100%]
66 passed in 2.04s

exec
/bin/zsh -lc "uv run python -c 'import runpy,pandas as pd; ns=runpy.run_path(\"tests/test_nfp_official_release_dates.py\"); m=ns[\"_k528_module\"](); sel=pd.to_datetime([\"2024-03-08\",\"2024-04-05\",\"2024-05-03\",\"2024-06-07\",\"2024-07-05\",\"2024-08-02\",\"2024-09-06\",\"2024-10-04\",\"2024-11-01\",\"2024-12-06\"]); raw=[\"2024-01-05\",\"2024-02-02\"]+[str(x.date()) for x in sel]; o=m.check_calendar_is_complete(sel,raw,\"2024-01-01\",\"2024-12-31\"); print(\"ENDPOINT_BYPASS_ACCEPTED\",o[\"window_coverage\"],o[\"n_months_in_span\"]); sel2=pd.to_datetime([\"2024-01-05\",\"2024-02-02\",\"2024-03-08\"]); raw2=[\"2024-01-05\",\"2024-01-06\",\"2024-01-10\",\"2024-02-02\",\"2024-03-08\"]; o2=m.check_calendar_is_complete(sel2,raw2,\"2024-01-01\",\"2024-03-31\"); print(\"REVIEWED_MONTH_MUTATION_ACCEPTED\",o2[\"months_with_multiple_raw_entries\"],o2[\"reviewed_multi_entry_months\"][\"2024-01\"])'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 1501ms:
ENDPOINT_BYPASS_ACCEPTED {'requested': '2024-01-01..2024-12-31', 'observed': '2024-03-08..2024-12-06', 'head_shortfall_days': 67, 'tail_shortfall_days': 25, 'tolerance_days': 70} 10
REVIEWED_MONTH_MUTATION_ACCEPTED ['2024-01'] 2024-01-05

exec
/bin/zsh -lc 'for f in paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv experiments/k1660_mz_calibration_audit/data/SPY_ohlc.csv experiments/k1530/data/SPY.csv; do echo "$f"; sed -n '"'1,4p' \""'$f"; done' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv
date,eem_adj_close,gld_adj_close,qqq_adj_close,spy_adj_close,tlt_adj_close,vix_adj_close,eem_close,gld_close,qqq_close,spy_close,tlt_close,vix_close,eem_high,gld_high,qqq_high,spy_high,tlt_high,vix_high,eem_low,gld_low,qqq_low,spy_low,tlt_low,vix_low,eem_open,gld_open,qqq_open,spy_open,tlt_open,vix_open,eem_volume,gld_volume,qqq_volume,spy_volume,tlt_volume,vix_volume
2005-01-03,14.562676429748535,43.02000045776367,33.65294647216797,81.38371276855469,44.5604248046875,14.079999923706055,22.19444465637207,43.02000045776367,39.5,120.30000305175781,88.73999786376953,14.079999923706055,22.494443893432617,43.16999816894531,40.290000915527344,121.76000213623047,88.83999633789062,14.229999542236328,22.15333366394043,42.7400016784668,39.369998931884766,119.9000015258789,88.16000366210938,13.25,22.41111183166504,42.97999954223633,40.09000015258789,121.55999755859375,88.18000030517578,13.390000343322754,4275000,4750400,100970900,55748000,1168000,0
2005-01-04,14.114309310913086,42.7400016784668,33.03953552246094,80.38926696777344,44.09343338012695,13.979999542236328,21.511110305786133,42.7400016784668,38.779998779296875,118.83000183105469,87.80999755859375,13.979999542236328,22.149999618530273,42.90999984741211,39.7400016784668,120.54000091552734,88.75,14.449999809265137,21.511110305786133,42.459999084472656,38.54999923706055,118.44000244140625,87.80999755859375,13.930000305175781,22.13888931274414,42.79999923706055,39.66999816894531,120.45999908447266,88.72000122070312,14.010000228881836,4205700,3456800,136623200,69167600,1935400,0
2005-01-05,13.94153118133545,42.66999816894531,32.835044860839844,79.83454895019531,44.32943344116211,14.09000015258789,21.247777938842773,42.66999816894531,38.540000915527344,118.01000213623047,88.27999877929688,14.09000015258789,21.530000686645508,42.880001068115234,38.959999084472656,119.25,88.55000305175781,14.09000015258789,21.244443893432617,42.599998474121094,38.470001220703125,118.0,87.94000244140625,13.260000228881836,21.488889694213867,42.75,38.68000030517578,118.73999786376953,87.98999786376953,13.979999542236328,3006900,2033600,127925500,65667300,1094100,0
paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv
date,eem_adj_close,fez_adj_close,qqq_adj_close,spy_adj_close,vix_adj_close,eem_close,fez_close,qqq_close,spy_close,vix_close,eem_high,fez_high,qqq_high,spy_high,vix_high,eem_low,fez_low,qqq_low,spy_low,vix_low,eem_open,fez_open,qqq_open,spy_open,vix_open,eem_volume,fez_volume,qqq_volume,spy_volume,vix_volume
2000-01-03,,,79.92739868164062,91.36750030517578,24.209999084472656,,,94.75,145.4375,24.209999084472656,,,96.1875,148.25,26.149999618530273,,,90.75,143.875,23.979999542236328,,,96.1875,148.25,24.360000610351562,,,36345200,8164300,0
2000-01-04,,,74.44425964355469,87.7945327758789,27.010000228881836,,,88.25,139.75,27.010000228881836,,,93.5,144.0625,27.18000030517578,,,87.9375,139.640625,24.799999237060547,,,92.0,143.53125,24.940000534057617,,,33786600,8089800,0
2000-01-05,,,72.54622650146484,87.95154571533203,26.40999984741211,,,86.0,140.0,26.40999984741211,,,89.625,141.53125,29.0,,,84.25,137.25,25.850000381469727,,,87.5,139.9375,27.979999542236328,,,42496600,12177900,0
experiments/k1660_mz_calibration_audit/data/SPY_ohlc.csv
Date,Open,High,Low,Close
2019-12-23,321.5899963378906,321.6499938964844,321.05999755859375,321.2200012207031
2019-12-24,321.4700012207031,321.5199890136719,320.8999938964844,321.2300109863281
2019-12-26,321.6499938964844,322.95001220703125,321.6400146484375,322.94000244140625
experiments/k1530/data/SPY.csv
Date,Close
2018-01-02,236.56211853027344
2018-01-03,238.05845642089844
2018-01-04,239.06179809570312

exec
/bin/zsh -lc "uv run python -c 'import json,subprocess,pandas as pd,numpy as np; from scipy import stats; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; c=\"58853f3ab\"; p=json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",f\"{c}:experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json\"])); ev=pd.DatetimeIndex([e[\"date\"] for e in p[\"event_data\"]]); d=pd.read_csv(\"paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv\",parse_dates=[\"date\"]).set_index(\"date\"); d=d[(d.index>=pd.Timestamp(\"2005-01-01\"))&(d.index<pd.Timestamp(\"2026-03-27\"))].copy();
for col in [\"spy_adj_close\",\"spy_close\"]:
 r=d[col].pct_change().abs().dropna(); pe=np.array([r.loc[x] for x in ev]); ctrl=r[~r.index.isin(set(ev)|{pd.Timestamp(\"2005-01-07\")})]; fri=ctrl[ctrl.index.weekday==4]; pefri=pe[ev.weekday==4]; t,pv=stats.ttest_ind(pefri,fri,equal_var=False); archctrl=r[~r.index.isin(set(ev))]; ta,pa=stats.ttest_ind(pefri,archctrl[archctrl.index.weekday==4],equal_var=False); print(col,\"n\",len(r),\"event_match_max\",max(abs(pe[i]-p[\"event_data\"][i][\"event_abs_return\"]) for i in range(len(pe))),\"leakfree\",pefri.mean()/fri.mean(),pv,len(pefri),len(fri),\"archive\",pefri.mean()/archctrl[archctrl.index.weekday==4].mean(),pa,len(archctrl[archctrl.index.weekday==4]))'" in /Users/yhlai0911/volpred-research
 succeeded in 1103ms:
spy_adj_close n 5340 event_match_max 1.3727990928469325e-06 leakfree 1.1667091632419213 0.04213508722021708 239 832 archive 1.16783259921233 0.04093353955247142 833
spy_close n 5340 event_match_max 8.361503691656225e-07 leakfree 1.1379881558884393 0.08494442303053097 239 832 archive 1.139090666788979 0.08273543078632936 833

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

git -C "$repo" show "${commit}:experiments/k528/k528_nfp_official_dates_results.json" | jq '"'{item:.items.vol_ratio_vs_friday, all:.items.vol_ratio_vs_all, correction:.article_correction, n_items:(.items|length), generated_at}'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_official_dates_results.json" | nl -ba | rg -n '"'\"vol_ratio_vs_all\"|\"vol_ratio_vs_friday\"|1\\.166|0\\.042|\"n_control_friday\"|\"median_ratio\"|\"win_rate\"|\"article_correction\"|\"n_replacements\"|\"claim_scope\"|validated_not_applied|真正拉開|圖表'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_event_study_results.json" | nl -ba | rg -n '"'\"total_trading_days\"|\"control_group_excludes_all_nfp_sessions\"|\"non_nfp_trading_days\"|\"n_mapped_to_sessions\"|\"claim_scope\"|\"conclusion\"|\"summary\"|\"2\\.02|\"1\\.18|\"1\\.10|not causal|causal|significant.*greater|median split|post'

git -C \""'$repo" show "${commit}:experiments/k528/README.md" | nl -ba | sed -n '"'90,260p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
{
  "item": {
    "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
    "before": {
      "mean_ratio": 1.166705672588405,
      "p_value": 0.04213984873387389,
      "significant_5pct": true,
      "n": 239,
      "nfp_days_on_friday": 239,
      "median_ratio": 1.1979193428374169,
      "win_rate": 0.5564853556485355,
      "n_control_friday": 832,
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
      "mean_ratio": 1.1889932285781484,
      "p_value": 0.02085474364987024,
      "significant_5pct": true,
      "n": 237,
      "nfp_days_on_friday": 237,
      "median_ratio": 1.2185765501135915,
      "win_rate": 0.569620253164557,
      "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
      "diagnostic_mixed_weekday": {
        "mean_ratio": 1.1767600146677832,
        "p_value": 0.025693120973358435,
        "significant_5pct": true,
        "n": 253,
        "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
      }
    },
    "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to Friday releases. Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
    "verdict": "NUMERIC_ADJUSTMENT",
    "verdict_reasons": []
  },
  "all": {
    "label": "NFP vs all non-NFP days (article: 1.10x)",
    "before": {
      "mean_ratio": 1.1035360772013734,
      "nfp_mean": 0.008420922409653335,
      "baseline_mean": 0.0076308537469923455,
      "p_value": 0.1283682008960355,
      "significant_5pct": false,
      "n": 254,
      "median_ratio": 1.1884376842166304,
      "win_rate": 0.5551181102362205
    },
    "after": {
      "mean_ratio": 1.1077777719197994,
      "nfp_mean": 0.00845305173732809,
      "baseline_mean": 0.0076306385193835365,
      "p_value": 0.11206802266548598,
      "significant_5pct": false,
      "n": 253,
      "median_ratio": 1.191581334504972,
      "win_rate": 0.5612648221343873
    },
    "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
    "verdict": "NUMERIC_ADJUSTMENT",
    "verdict_reasons": []
  },
  "correction": {
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
        "to": "VolPred 也把這層拿掉，改用「非 NFP 的週五」當基準。253 場 NFP 裡有 237 場落在週五、16 場不是，所以這個比較只取在週五公布的那 237 場，讓兩邊的星期別一致：這 237 場的當日波動是週五基準的 1.19 倍，用 Welch t 檢定算下來，這個差距達到顯著水準（p=0.021）。要注意這個數字講的是「**在週五公布的** NFP」，不是 NFP 一般而言；被排掉的那 16 場本身比較平靜，所以限定週五會把倍數墊高一些（不限定的話是 1.18 倍）。（另外拿全體非 NFP 日做一個只看排序、不看數值大小的無母數檢定，NFP 日的波動分佈同樣明顯偏高。）",
        "hits": 1
      },
      {
        "from": "所以精確的講法是：NFP 日確實比一般週五抖一點，差距顯著但不算誇張（1.17 倍）；但如果拿全部交易日當對照，這個放大效果（1.10 倍）連統計顯著都談不上。",
        "to": "所以精確的講法是：在週五公布的 NFP 確實比一般週五抖一點，差距顯著但不算誇張（1.19 倍）；但如果拿全部交易日當對照，這個放大效果（1.11 倍）連統計顯著都談不上。",
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
        "to": "第一，NFP 事件本身的波動放大效果，對全體交易日基準是 1.11 倍、未達顯著水準；若只看在週五公布的那 237 場、拿非 NFP 的週五當基準，是 1.19 倍、達到顯著水準。",
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
        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。\n\n另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，兩邊不對等。現改為只取在週五公布的 237 場，維持兩邊星期別一致，所以該數字講的是「在週五公布的 NFP」而非 NFP 一般而言。被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），兩個數字都列出以免只揭露比較好看的那個。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
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
  },
  "n_items": 6,
  "generated_at": "2026-07-19T08:53:23.055332+00:00"
}
108:   108	    "vol_ratio_vs_all": {
117:   117	        "median_ratio": 1.1884376842166304,
118:   118	        "win_rate": 0.5551181102362205
127:   127	        "median_ratio": 1.191581334504972,
128:   128	        "win_rate": 0.5612648221343873
134:   134	    "vol_ratio_vs_friday": {
137:   137	        "mean_ratio": 1.166705672588405,
138:   138	        "p_value": 0.04213984873387389,
142:   142	        "median_ratio": 1.1979193428374169,
143:   143	        "win_rate": 0.5564853556485355,
144:   144	        "n_control_friday": 832,
160:   160	        "median_ratio": 1.2185765501135915,
161:   161	        "win_rate": 0.569620253164557,
185:   185	        "median_ratio": 2.2653573776192792,
186:   186	        "win_rate": 0.7165354330708661
196:   196	        "median_ratio": 2.073364952892548,
197:   197	        "win_rate": 0.6953125
219:   219	        "slope_pct_per_vix_pt": 0.04256117035047841,
350:   350	  "article_correction": {
352:   352	    "status": "validated_not_applied",
353:   353	    "n_replacements": 19,
449:   449	        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。\n\n另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，兩邊不對等。現改為只取在週五公布的 237 場，維持兩邊星期別一致，所以該數字講的是「在週五公布的 NFP」而非 NFP 一般而言。被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），兩個數字都列出以免只揭露比較好看的那個。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
15:    15	    "non_nfp_trading_days": 5086,
20:    20	      "n_mapped_to_sessions": 254,
61:    61	    "total_trading_days": 5340,
62:    62	    "control_group_excludes_all_nfp_sessions": true
83:    83	      "claim_scope": "This identifies the effect of an NFP release ON A FRIDAY. It does not license a statement about NFP releases in general -- the excluded non-Friday events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec. Any prose quoting this number must say 'Friday NFP', not 'NFP'.",
116:   116	      "test": "One-sample t-test (post-pre diff)",
118:   118	      "post_avg": 0.007687347886443663,
289:   289	      "post_avg_abs_return": 0.00443788312790856,
292:   292	      "post_vix_1d": 11.729999542236328,
305:   305	      "post_avg_abs_return": 0.004918889633281798,
308:   308	      "post_vix_1d": 12.260000228881836,
321:   321	      "post_avg_abs_return": 0.005145579628169949,
324:   324	      "post_vix_1d": 14.109999656677246,
337:   337	      "post_avg_abs_return": 0.007013112771228536,
340:   340	      "post_vix_1d": 13.75,
353:   353	      "post_avg_abs_return": 0.0021147876036742507,
356:   356	      "post_vix_1d": 12.279999732971191,
369:   369	      "post_avg_abs_return": 0.002723110867930534,
372:   372	      "post_vix_1d": 11.279999732971191,
385:   385	      "post_avg_abs_return": 0.003700788409114675,
388:   388	      "post_vix_1d": 13.210000038146973,
401:   401	      "post_avg_abs_return": 0.005522766398304668,
404:   404	      "post_vix_1d": 12.930000305175781,
417:   417	      "post_avg_abs_return": 0.005777279408820624,
420:   420	      "post_vix_1d": 15.550000190734863,
433:   433	      "post_avg_abs_return": 0.0026918055998371494,
436:   436	      "post_vix_1d": 13.100000381469727,
449:   449	      "post_avg_abs_return": 0.0026224481162922418,
452:   452	      "post_vix_1d": 11.600000381469727,
465:   465	      "post_avg_abs_return": 0.0023271009621830705,
468:   468	      "post_vix_1d": 11.130000114440918,
481:   481	      "post_avg_abs_return": 0.00480458623834068,
484:   484	      "post_vix_1d": 13.039999961853027,
497:   497	      "post_avg_abs_return": 0.003940129432545314,
500:   500	      "post_vix_1d": 11.369999885559082,
513:   513	      "post_avg_abs_return": 0.0027189651877180367,
516:   516	      "post_vix_1d": 12.1899995803833,
529:   529	      "post_avg_abs_return": 0.0057656788781886405,
532:   532	      "post_vix_1d": 12.0,
545:   545	      "post_avg_abs_return": 0.005711818071453045,
548:   548	      "post_vix_1d": 16.649999618530273,
561:   561	      "post_avg_abs_return": 0.007423898397036921,
564:   564	      "post_vix_1d": 14.020000457763672,
577:   577	      "post_avg_abs_return": 0.0030885931177977665,
580:   580	      "post_vix_1d": 15.229999542236328,
593:   593	      "post_avg_abs_return": 0.0038311331181927867,
596:   596	      "post_vix_1d": 12.630000114440918,
609:   609	      "post_avg_abs_return": 0.002867126207658366,
612:   612	      "post_vix_1d": 11.680000305175781,
625:   625	      "post_avg_abs_return": 0.004594300152765051,
628:   628	      "post_vix_1d": 11.15999984741211,
641:   641	      "post_avg_abs_return": 0.002727171159761377,
644:   644	      "post_vix_1d": 10.710000038146973,
657:   657	      "post_avg_abs_return": 0.004156549020523026,
660:   660	      "post_vix_1d": 12.0,
673:   673	      "post_avg_abs_return": 0.002303364785725526,
676:   676	      "post_vix_1d": 10.550000190734863,
689:   689	      "post_avg_abs_return": 0.00650835729807544,
692:   692	      "post_vix_1d": 13.989999771118164,
705:   705	      "post_avg_abs_return": 0.004751967326635631,
708:   708	      "post_vix_1d": 12.680000305175781,
721:   721	      "post_avg_abs_return": 0.004651148330040322,
724:   724	      "post_vix_1d": 13.149999618530273,
737:   737	      "post_avg_abs_return": 0.009178861834197272,
740:   740	      "post_vix_1d": 13.289999961853027,
753:   753	      "post_avg_abs_return": 0.008176953504859984,
756:   756	      "post_vix_1d": 15.15999984741211,
769:   769	      "post_avg_abs_return": 0.015136126860127663,
772:   772	      "post_vix_1d": 22.940000534057617,
785:   785	      "post_avg_abs_return": 0.004651031817969775,
788:   788	      "post_vix_1d": 27.3799991607666,
801:   801	      "post_avg_abs_return": 0.005347654165975624,
804:   804	      "post_vix_1d": 17.459999084472656,
817:   817	      "post_avg_abs_return": 0.013444179694611268,
820:   820	      "post_vix_1d": 24.309999465942383,
833:   833	      "post_avg_abs_return": 0.011959844384138552,
836:   836	      "post_vix_1d": 20.739999771118164,
849:   849	      "post_avg_abs_return": 0.008425825164023482,
852:   852	      "post_vix_1d": 23.790000915527344,
865:   865	      "post_avg_abs_return": 0.01209406167168523,
868:   868	      "post_vix_1d": 25.989999771118164,
881:   881	      "post_avg_abs_return": 0.015234829534806815,
884:   884	      "post_vix_1d": 29.3799991607666,
897:   897	      "post_avg_abs_return": 0.0059152180102865605,
900:   900	      "post_vix_1d": 22.420000076293945,
913:   913	      "post_avg_abs_return": 0.007145588950028081,
916:   916	      "post_vix_1d": 18.899999618530273,
929:   929	      "post_avg_abs_return": 0.0077126852037535,
932:   932	      "post_vix_1d": 23.1200008392334,
945:   945	      "post_avg_abs_return": 0.012592788116693353,
948:   948	      "post_vix_1d": 25.780000686645508,
961:   961	      "post_avg_abs_return": 0.014829806455301898,
964:   964	      "post_vix_1d": 23.489999771118164,
977:   977	      "post_avg_abs_return": 0.014698004883704274,
980:   980	      "post_vix_1d": 22.639999389648438,
993:   993	      "post_avg_abs_return": 0.04300125979734208,
996:   996	      "post_vix_1d": 52.04999923706055,
1009:  1009	      "post_avg_abs_return": 0.04004526575981846,
1012:  1012	      "post_vix_1d": 59.97999954223633,
1025:  1025	      "post_avg_abs_return": 0.018847056173180676,
1028:  1028	      "post_vix_1d": 58.4900016784668,
1041:  1041	      "post_avg_abs_return": 0.013097970770055412,
1044:  1044	      "post_vix_1d": 45.84000015258789,
1057:  1057	      "post_avg_abs_return": 0.012912158491023295,
1060:  1060	      "post_vix_1d": 43.63999938964844,
1073:  1073	      "post_avg_abs_return": 0.025012235443572117,
1076:  1076	      "post_vix_1d": 49.68000030517578,
1089:  1089	      "post_avg_abs_return": 0.016382424016418894,
1092:  1092	      "post_vix_1d": 40.93000030517578,
1105:  1105	      "post_avg_abs_return": 0.012715492716670473,
1108:  1108	      "post_vix_1d": 32.869998931884766,
1121:  1121	      "post_avg_abs_return": 0.003789598081647716,
1124:  1124	      "post_vix_1d": 29.770000457763672,
1137:  1137	      "post_avg_abs_return": 0.004896482619768538,
1140:  1140	      "post_vix_1d": 29.0,
1153:  1153	      "post_avg_abs_return": 0.00811962258151766,
1156:  1156	      "post_vix_1d": 24.989999771118164,
1169:  1169	      "post_avg_abs_return": 0.006314834479604237,
1172:  1172	      "post_vix_1d": 25.6200008392334,
1185:  1185	      "post_avg_abs_return": 0.009150773520112709,
1188:  1188	      "post_vix_1d": 26.84000015258789,
1201:  1201	      "post_avg_abs_return": 0.00872970747399815,
1204:  1204	      "post_vix_1d": 23.149999618530273,
1217:  1217	      "post_avg_abs_return": 0.0052506177213139885,
1220:  1220	      "post_vix_1d": 22.100000381469727,
1233:  1233	      "post_avg_abs_return": 0.0066196629274844375,
1236:  1236	      "post_vix_1d": 17.549999237060547,
1249:  1249	      "post_avg_abs_return": 0.0066070550591585285,
1252:  1252	      "post_vix_1d": 26.510000228881836,
1265:  1265	      "post_avg_abs_return": 0.0021110493359335347,
1268:  1268	      "post_vix_1d": 17.790000915527344,
1281:  1281	      "post_avg_abs_return": 0.00393817013411839,
1284:  1284	      "post_vix_1d": 16.229999542236328,
1297:  1297	      "post_avg_abs_return": 0.018280582921508894,
1300:  1300	      "post_vix_1d": 28.84000015258789,
1313:  1313	      "post_avg_abs_return": 0.012518946088131245,
1316:  1316	      "post_vix_1d": 36.56999969482422,
1329:  1329	      "post_avg_abs_return": 0.011212201552847346,
1332:  1332	      "post_vix_1d": 29.649999618530273,
1345:  1345	      "post_avg_abs_return": 0.009443892626748962,
1348:  1348	      "post_vix_1d": 22.139999389648438,
1361:  1361	      "post_avg_abs_return": 0.007817308802787571,
1364:  1364	      "post_vix_1d": 23.799999237060547,
1377:  1377	      "post_avg_abs_return": 0.0035501987298883543,
1380:  1380	      "post_vix_1d": 18.959999084472656,
1393:  1393	      "post_avg_abs_return": 0.005738576011227492,
1396:  1396	      "post_vix_1d": 18.290000915527344,
1409:  1409	      "post_avg_abs_return": 0.0030005593143801468,
1412:  1412	      "post_vix_1d": 18.020000457763672,
1425:  1425	      "post_avg_abs_return": 0.004540958447308796,
1428:  1428	      "post_vix_1d": 17.540000915527344,
1441:  1441	      "post_avg_abs_return": 0.00388217171228169,
1444:  1444	      "post_vix_1d": 16.280000686645508,
1457:  1457	      "post_avg_abs_return": 0.008693357838430327,
1460:  1460	      "post_vix_1d": 20.65999984741211,
1473:  1473	      "post_avg_abs_return": 0.0020246204961404724,
1476:  1476	      "post_vix_1d": 17.5,
1489:  1489	      "post_avg_abs_return": 0.007079268329014487,
1492:  1492	      "post_vix_1d": 17.15999984741211,
1505:  1505	      "post_avg_abs_return": 0.007385973465662299,
1508:  1508	      "post_vix_1d": 18.489999771118164,
1521:  1521	      "post_avg_abs_return": 0.007691130233550436,
1524:  1524	      "post_vix_1d": 18.389999389648438,
1537:  1537	      "post_avg_abs_return": 0.0414834616817664,
1540:  1540	      "post_vix_1d": 48.0,
1553:  1553	      "post_avg_abs_return": 0.015715000236635034,
1556:  1556	      "post_vix_1d": 37.0,
1569:  1569	      "post_avg_abs_return": 0.012460599849290644,
1572:  1572	      "post_vix_1d": 33.02000045776367,
1585:  1585	      "post_avg_abs_return": 0.016839550438300897,
1588:  1588	      "post_vix_1d": 29.850000381469727,
1601:  1601	      "post_avg_abs_return": 0.010762122372985216,
1604:  1604	      "post_vix_1d": 27.84000015258789,
1617:  1617	      "post_avg_abs_return": 0.0038423534532455728,
1620:  1620	      "post_vix_1d": 21.06999969482422,
1633:  1633	      "post_avg_abs_return": 0.00296223423372588,
1636:  1636	      "post_vix_1d": 17.760000228881836,
1649:  1649	      "post_avg_abs_return": 0.005268827556466582,
1652:  1652	      "post_vix_1d": 15.640000343322754,
1665:  1665	      "post_avg_abs_return": 0.0100977023403648,
1668:  1668	      "post_vix_1d": 20.389999389648438,
1681:  1681	      "post_avg_abs_return": 0.0031500800967366295,
1684:  1684	      "post_vix_1d": 18.940000534057617,
1697:  1697	      "post_avg_abs_return": 0.007813279564042453,
1700:  1700	      "post_vix_1d": 26.1200008392334,
1713:  1713	      "post_avg_abs_return": 0.006349441228698005,
1716:  1716	      "post_vix_1d": 17.979999542236328,
1729:  1729	      "post_avg_abs_return": 0.0021304943088995554,
1732:  1732	      "post_vix_1d": 15.949999809265137,
1745:  1745	      "post_avg_abs_return": 0.006294950236621011,
1748:  1748	      "post_vix_1d": 16.280000686645508,
1761:  1761	      "post_avg_abs_return": 0.004705350960202947,
1764:  1764	      "post_vix_1d": 15.109999656677246,
1777:  1777	      "post_avg_abs_return": 0.009086102536795005,
1780:  1780	      "post_vix_1d": 18.420000076293945,
1793:  1793	      "post_avg_abs_return": 0.0035130449130160724,
1796:  1796	      "post_vix_1d": 16.049999237060547,
1809:  1809	      "post_avg_abs_return": 0.0032338292619608746,
1812:  1812	      "post_vix_1d": 13.789999961853027,
1825:  1825	      "post_avg_abs_return": 0.005791155378497326,
1828:  1828	      "post_vix_1d": 14.670000076293945,
1841:  1841	      "post_avg_abs_return": 0.002819280510059019,
1844:  1844	      "post_vix_1d": 11.5600004196167,
1857:  1857	      "post_avg_abs_return": 0.0056400687327582185,
1860:  1860	      "post_vix_1d": 13.1899995803833,
1873:  1873	      "post_avg_abs_return": 0.003646045671682052,
1876:  1876	      "post_vix_1d": 12.65999984741211,
1889:  1889	      "post_avg_abs_return": 0.008014733376411187,
1892:  1892	      "post_vix_1d": 15.4399995803833,
1905:  1905	      "post_avg_abs_return": 0.005460871137382606,
1908:  1908	      "post_vix_1d": 14.779999732971191,
1921:  1921	      "post_avg_abs_return": 0.003387315485417797,
1924:  1924	      "post_vix_1d": 11.84000015258789,
1937:  1937	      "post_avg_abs_return": 0.00500327498545774,
1940:  1940	      "post_vix_1d": 15.630000114440918,
1953:  1953	      "post_avg_abs_return": 0.00392080298184303,
1956:  1956	      "post_vix_1d": 13.420000076293945,
1969:  1969	      "post_avg_abs_return": 0.003912759728557025,
1972:  1972	      "post_vix_1d": 12.529999732971191,
1985:  1985	      "post_avg_abs_return": 0.004153857485147206,
1988:  1988	      "post_vix_1d": 13.489999771118164,
2001:  2001	      "post_avg_abs_return": 0.0070244729195350075,
2004:  2004	      "post_vix_1d": 13.279999732971191,
2017:  2017	      "post_avg_abs_return": 0.00479135554885497,
2020:  2020	      "post_vix_1d": 15.260000228881836,
2033:  2033	      "post_avg_abs_return": 0.003952323053957674,
2036:  2036	      "post_vix_1d": 14.199999809265137,
2049:  2049	      "post_avg_abs_return": 0.011187920660344375,
2052:  2052	      "post_vix_1d": 15.569999694824219,
2065:  2065	      "post_avg_abs_return": 0.003812789346537793,
2068:  2068	      "post_vix_1d": 13.289999961853027,
2081:  2081	      "post_avg_abs_return": 0.002946206789309125,
2084:  2084	      "post_vix_1d": 11.149999618530273,
2097:  2097	      "post_avg_abs_return": 0.003945711201410873,
2100:  2100	      "post_vix_1d": 11.329999923706055,
2113:  2113	      "post_avg_abs_return": 0.00684249766315308,
2116:  2116	      "post_vix_1d": 15.119999885559082,
2129:  2129	      "post_avg_abs_return": 0.003933994330446699,
2132:  2132	      "post_vix_1d": 12.65999984741211,
2145:  2145	      "post_avg_abs_return": 0.013068643197536733,
2148:  2148	      "post_vix_1d": 15.460000038146973,
2161:  2161	      "post_avg_abs_return": 0.0013157199282111565,
2164:  2164	      "post_vix_1d": 12.670000076293945,
2177:  2177	      "post_avg_abs_return": 0.008924451527341292,
2180:  2180	      "post_vix_1d": 14.210000038146973,
2193:  2193	      "post_avg_abs_return": 0.007791755725934002,
2196:  2196	      "post_vix_1d": 19.600000381469727,
2209:  2209	      "post_avg_abs_return": 0.0058883595714829704,
2212:  2212	      "post_vix_1d": 18.549999237060547,
2225:  2225	      "post_avg_abs_return": 0.008311055789138645,
2228:  2228	      "post_vix_1d": 15.0600004196167,
2241:  2241	      "post_avg_abs_return": 0.004085477921841463,
2244:  2244	      "post_vix_1d": 14.779999732971191,
2257:  2257	      "post_avg_abs_return": 0.003893246639182246,
2260:  2260	      "post_vix_1d": 13.850000381469727,
2273:  2273	      "post_avg_abs_return": 0.005833042330539362,
2276:  2276	      "post_vix_1d": 15.289999961853027,
2289:  2289	      "post_avg_abs_return": 0.008062419623871086,
2292:  2292	      "post_vix_1d": 17.010000228881836,
2305:  2305	      "post_avg_abs_return": 0.0055414670272043495,
2308:  2308	      "post_vix_1d": 12.229999542236328,
2321:  2321	      "post_avg_abs_return": 0.01043982643293424,
2324:  2324	      "post_vix_1d": 24.899999618530273,
2337:  2337	      "post_avg_abs_return": 0.007806922679098749,
2340:  2340	      "post_vix_1d": 19.540000915527344,
2353:  2353	      "post_avg_abs_return": 0.008151741515191203,
2356:  2356	      "post_vix_1d": 16.520000457763672,
2369:  2369	      "post_avg_abs_return": 0.008503984785494457,
2372:  2372	      "post_vix_1d": 15.84000015258789,
2385:  2385	      "post_avg_abs_return": 0.014376359643640457,
2388:  2388	      "post_vix_1d": 24.299999237060547,
2401:  2401	      "post_avg_abs_return": 0.009600431119323627,
2404:  2404	      "post_vix_1d": 26.0,
2417:  2417	      "post_avg_abs_return": 0.006719095444835288,
2420:  2420	      "post_vix_1d": 17.350000381469727,
2433:  2433	      "post_avg_abs_return": 0.007762070463323822,
2436:  2436	      "post_vix_1d": 14.119999885559082,
2449:  2449	      "post_avg_abs_return": 0.006323971507723747,
2452:  2452	      "post_vix_1d": 14.569999694824219,
2465:  2465	      "post_avg_abs_return": 0.004150560353822841,
2468:  2468	      "post_vix_1d": 13.649999618530273,
2481:  2481	      "post_avg_abs_return": 0.003570861108039769,
2484:  2484	      "post_vix_1d": 13.539999961853027,
2497:  2497	      "post_avg_abs_return": 0.0018356239003888275,
2500:  2500	      "post_vix_1d": 11.5,
2513:  2513	      "post_avg_abs_return": 0.008735833812446869,
2516:  2516	      "post_vix_1d": 12.020000457763672,
2529:  2529	      "post_avg_abs_return": 0.004588284018153721,
2532:  2532	      "post_vix_1d": 13.380000114440918,
2545:  2545	      "post_avg_abs_return": 0.00839263146883924,
2548:  2548	      "post_vix_1d": 18.709999084472656,
2561:  2561	      "post_avg_abs_return": 0.006149211241963393,
2564:  2564	      "post_vix_1d": 12.140000343322754,
2577:  2577	      "post_avg_abs_return": 0.002186406368716254,
2580:  2580	      "post_vix_1d": 11.5600004196167,
2593:  2593	      "post_avg_abs_return": 0.0026040900002371357,
2596:  2596	      "post_vix_1d": 11.369999885559082,
2609:  2609	      "post_avg_abs_return": 0.003341669513529011,
2612:  2612	      "post_vix_1d": 11.350000381469727,
2625:  2625	      "post_avg_abs_return": 0.0043042484444146155,
2628:  2628	      "post_vix_1d": 14.050000190734863,
2641:  2641	      "post_avg_abs_return": 0.0013188826794648279,
2644:  2644	      "post_vix_1d": 9.770000457763672,
2657:  2657	      "post_avg_abs_return": 0.001558880389325412,
2660:  2660	      "post_vix_1d": 10.069999694824219,
2673:  2673	      "post_avg_abs_return": 0.003135063000199434,
2676:  2676	      "post_vix_1d": 11.109999656677246,
2689:  2689	      "post_avg_abs_return": 0.003990501808910895,
2692:  2692	      "post_vix_1d": 9.930000305175781,
2705:  2705	      "post_avg_abs_return": 0.004511667629770488,
2708:  2708	      "post_vix_1d": 12.229999542236328,
2721:  2721	      "post_avg_abs_return": 0.0017135541837180357,
2724:  2724	      "post_vix_1d": 10.329999923706055,
2737:  2737	      "post_avg_abs_return": 0.00157645751691875,
2740:  2740	      "post_vix_1d": 9.399999618530273,
2753:  2753	      "post_avg_abs_return": 0.0034608116854145444,
2756:  2756	      "post_vix_1d": 9.34000015258789,
2769:  2769	      "post_avg_abs_return": 0.0038873694676437643,
2772:  2772	      "post_vix_1d": 9.520000457763672,
2785:  2785	      "post_avg_abs_return": 0.023896032448451156,
2788:  2788	      "post_vix_1d": 37.31999969482422,
2801:  2801	      "post_avg_abs_return": 0.0030047646095822554,
2804:  2804	      "post_vix_1d": 15.779999732971191,
2817:  2817	      "post_avg_abs_return": 0.007446185230171909,
2820:  2820	      "post_vix_1d": 21.770000457763672,
2833:  2833	      "post_avg_abs_return": 0.005090180869033701,
2836:  2836	      "post_vix_1d": 14.75,
2849:  2849	      "post_avg_abs_return": 0.003380865049727455,
2852:  2852	      "post_vix_1d": 12.739999771118164,
2865:  2865	      "post_avg_abs_return": 0.005954194190199158,
2868:  2868	      "post_vix_1d": 12.6899995803833,
2881:  2881	      "post_avg_abs_return": 0.0030911161259620677,
2884:  2884	      "post_vix_1d": 11.270000457763672,
2897:  2897	      "post_avg_abs_return": 0.0022728907519135254,
2900:  2900	      "post_vix_1d": 14.15999984741211,
2913:  2913	      "post_avg_abs_return": 0.013807333034989355,
2916:  2916	      "post_vix_1d": 15.6899995803833,
2929:  2929	      "post_avg_abs_return": 0.00896744090851782,
2932:  2932	      "post_vix_1d": 19.959999084472656,
2945:  2945	      "post_avg_abs_return": 0.005192663037733647,
2948:  2948	      "post_vix_1d": 22.639999389648438,
2961:  2961	      "post_avg_abs_return": 0.005173481017121872,
2964:  2964	      "post_vix_1d": 21.399999618530273,
2977:  2977	      "post_avg_abs_return": 0.0046598377394712065,
2980:  2980	      "post_vix_1d": 15.729999542236328,
2993:  2993	      "post_avg_abs_return": 0.006094326024659047,
2996:  2996	      "post_vix_1d": 14.329999923706055,
3009:  3009	      "post_avg_abs_return": 0.0032685910962307885,
3012:  3012	      "post_vix_1d": 13.180000305175781,
3025:  3025	      "post_avg_abs_return": 0.00605058079241354,
3028:  3028	      "post_vix_1d": 15.4399995803833,
3041:  3041	      "post_avg_abs_return": 0.002365488927200965,
3044:  3044	      "post_vix_1d": 15.9399995803833,
3057:  3057	      "post_avg_abs_return": 0.0036680448526667186,
3060:  3060	      "post_vix_1d": 13.960000038146973,
3073:  3073	      "post_avg_abs_return": 0.01422359448832855,
3076:  3076	      "post_vix_1d": 24.59000015258789,
3089:  3089	      "post_avg_abs_return": 0.002395396754944312,
3092:  3092	      "post_vix_1d": 15.270000457763672,
3105:  3105	      "post_avg_abs_return": 0.009293220409232816,
3108:  3108	      "post_vix_1d": 17.860000610351562,
3121:  3121	      "post_avg_abs_return": 0.002266990475110542,
3124:  3124	      "post_vix_1d": 12.829999923706055,
3137:  3137	      "post_avg_abs_return": 0.00326323758504623,
3140:  3140	      "post_vix_1d": 15.859999656677246,
3153:  3153	      "post_avg_abs_return": 0.004418491561429127,
3156:  3156	      "post_vix_1d": 12.319999694824219,
3169:  3169	      "post_avg_abs_return": 0.003662044986575119,
3172:  3172	      "post_vix_1d": 15.039999961853027,
3185:  3185	      "post_avg_abs_return": 0.07195029566879682,
3188:  3188	      "post_vix_1d": 54.459999084472656,
3201:  3201	      "post_avg_abs_return": 0.02522030478095023,
3204:  3204	      "post_vix_1d": 45.2400016784668,
3217:  3217	      "post_avg_abs_return": 0.01087741375151896,
3220:  3220	      "post_vix_1d": 27.56999969482422,
3233:  3233	      "post_avg_abs_return": 0.018949915964273888,
3236:  3236	      "post_vix_1d": 25.809999465942383,
3249:  3249	      "post_avg_abs_return": 0.009860800845699912,
3252:  3252	      "post_vix_1d": 27.940000534057617,
3265:  3265	      "post_avg_abs_return": 0.005404611717979591,
3268:  3268	      "post_vix_1d": 22.1299991607666,
3281:  3281	      "post_avg_abs_return": 0.015622862017710548,
3284:  3284	      "post_vix_1d": 31.459999084472656,
3297:  3297	      "post_avg_abs_return": 0.013429865270487996,
3300:  3300	      "post_vix_1d": 27.959999084472656,
3313:  3313	      "post_avg_abs_return": 0.009001165240886077,
3316:  3316	      "post_vix_1d": 25.75,
3329:  3329	      "post_avg_abs_return": 0.0030898687075065602,
3332:  3332	      "post_vix_1d": 21.299999237060547,
3345:  3345	      "post_avg_abs_return": 0.004087990834600985,
3348:  3348	      "post_vix_1d": 24.079999923706055,
3361:  3361	      "post_avg_abs_return": 0.002975579511705484,
3364:  3364	      "post_vix_1d": 21.239999771118164,
3377:  3377	      "post_avg_abs_return": 0.007393378230549974,
3380:  3380	      "post_vix_1d": 25.469999313354492,
3393:  3393	      "post_avg_abs_return": 0.0028259327849624594,
3396:  3396	      "post_vix_1d": 18.1200008392334,
3409:  3409	      "post_avg_abs_return": 0.013488120842824825,
3412:  3412	      "post_vix_1d": 19.65999984741211,
3425:  3425	      "post_avg_abs_return": 0.0017953503779393643,
3428:  3428	      "post_vix_1d": 16.420000076293945,
3441:  3441	      "post_avg_abs_return": 0.005552073995502971,
3444:  3444	      "post_vix_1d": 16.440000534057617,
3457:  3457	      "post_avg_abs_return": 0.0018718080732613273,
3460:  3460	      "post_vix_1d": 16.719999313354492,
3473:  3473	      "post_avg_abs_return": 0.0039035218001511663,
3476:  3476	      "post_vix_1d": 18.139999389648438,
3489:  3489	      "post_avg_abs_return": 0.0075470198750611,
3492:  3492	      "post_vix_1d": 20.0,
3505:  3505	      "post_avg_abs_return": 0.004014920115444398,
3508:  3508	      "post_vix_1d": 17.219999313354492,
3521:  3521	      "post_avg_abs_return": 0.010268251893703173,
3524:  3524	      "post_vix_1d": 27.18000030517578,
3537:  3537	      "post_avg_abs_return": 0.005448675662158476,
3540:  3540	      "post_vix_1d": 19.399999618530273,
3553:  3553	      "post_avg_abs_return": 0.012751489828205686,
3556:  3556	      "post_vix_1d": 22.860000610351562,
3569:  3569	      "post_avg_abs_return": 0.01622030766275464,
3572:  3572	      "post_vix_1d": 36.45000076293945,
3585:  3585	      "post_avg_abs_return": 0.0077820680379654394,
3588:  3588	      "post_vix_1d": 18.56999969482422,
3601:  3601	      "post_avg_abs_return": 0.01503317773888162,
3604:  3604	      "post_vix_1d": 34.75,
3617:  3617	      "post_avg_abs_return": 0.015257571591704155,
3620:  3620	      "post_vix_1d": 25.06999969482422,
3633:  3633	      "post_avg_abs_return": 0.009411574944401613,
3636:  3636	      "post_vix_1d": 26.170000076293945,
3649:  3649	      "post_avg_abs_return": 0.00861299274302243,
3652:  3652	      "post_vix_1d": 21.290000915527344,
3665:  3665	      "post_avg_abs_return": 0.010911439819962654,
3668:  3668	      "post_vix_1d": 26.90999984741211,
3681:  3681	      "post_avg_abs_return": 0.013289339920509513,
3684:  3684	      "post_vix_1d": 32.45000076293945,
3697:  3697	      "post_avg_abs_return": 0.020039034835209503,
3700:  3700	      "post_vix_1d": 24.350000381469727,
3713:  3713	      "post_avg_abs_return": 0.009881875947570107,
3716:  3716	      "post_vix_1d": 20.75,
3729:  3729	      "post_avg_abs_return": 0.00554947109858146,
3732:  3732	      "post_vix_1d": 21.969999313354492,
3745:  3745	      "post_avg_abs_return": 0.008225577461031364,
3748:  3748	      "post_vix_1d": 19.43000030517578,
3761:  3761	      "post_avg_abs_return": 0.01068951025349767,
3764:  3764	      "post_vix_1d": 26.520000457763672,
3777:  3777	      "post_avg_abs_return": 0.004731645041626642,
3780:  3780	      "post_vix_1d": 19.100000381469727,
3793:  3793	      "post_avg_abs_return": 0.0024756149854898712,
3796:  3796	      "post_vix_1d": 16.979999542236328,
3809:  3809	      "post_avg_abs_return": 0.0030788719666083653,
3812:  3812	      "post_vix_1d": 14.729999542236328,
3825:  3825	      "post_avg_abs_return": 0.005101077500198903,
3828:  3828	      "post_vix_1d": 15.069999694824219,
3841:  3841	      "post_avg_abs_return": 0.004140955383657973,
3844:  3844	      "post_vix_1d": 15.770000457763672,
3857:  3857	      "post_avg_abs_return": 0.004439472044295489,
3860:  3860	      "post_vix_1d": 14.010000228881836,
3873:  3873	      "post_avg_abs_return": 0.00535612524423128,
3876:  3876	      "post_vix_1d": 17.700000762939453,
3889:  3889	      "post_avg_abs_return": 0.005856555949772702,
3892:  3892	      "post_vix_1d": 14.890000343322754,
3905:  3905	      "post_avg_abs_return": 0.005420553454886945,
3908:  3908	      "post_vix_1d": 12.630000114440918,
3921:  3921	      "post_avg_abs_return": 0.004516313722229315,
3924:  3924	      "post_vix_1d": 13.079999923706055,
3937:  3937	      "post_avg_abs_return": 0.004221168253852481,
3940:  3940	      "post_vix_1d": 13.670000076293945,
3953:  3953	      "post_avg_abs_return": 0.004405617405966034,
3956:  3956	      "post_vix_1d": 15.220000267028809,
3969:  3969	      "post_avg_abs_return": 0.006615881654519207,
3972:  3972	      "post_vix_1d": 15.1899995803833,
3985:  3985	      "post_avg_abs_return": 0.003715359046346256,
3988:  3988	      "post_vix_1d": 13.489999771118164,
4001:  4001	      "post_avg_abs_return": 0.0032666233524076826,
4004:  4004	      "post_vix_1d": 12.739999771118164,
4017:  4017	      "post_avg_abs_return": 0.005390370991218929,
4020:  4020	      "post_vix_1d": 12.369999885559082,
4033:  4033	      "post_avg_abs_return": 0.014510867700126462,
4036:  4036	      "post_vix_1d": 38.56999969482422,
4049:  4049	      "post_avg_abs_return": 0.007891384325789863,
4052:  4052	      "post_vix_1d": 19.450000762939453,
4065:  4065	      "post_avg_abs_return": 0.0066325144150070955,
4068:  4068	      "post_vix_1d": 22.639999389648438,
4081:  4081	      "post_avg_abs_return": 0.01023512347692943,
4084:  4084	      "post_vix_1d": 21.979999542236328,
4097:  4097	      "post_avg_abs_return": 0.00426809106946815,
4100:  4100	      "post_vix_1d": 14.1899995803833,
4113:  4113	      "post_avg_abs_return": 0.006615955329419521,
4116:  4116	      "post_vix_1d": 19.190000534057617,
4129:  4129	      "post_avg_abs_return": 0.004275903308313267,
4132:  4132	      "post_vix_1d": 15.8100004196167,
4145:  4145	      "post_avg_abs_return": 0.014848270188088385,
4148:  4148	      "post_vix_1d": 27.860000610351562,
4161:  4161	      "post_avg_abs_return": 0.036825008053289296,
4164:  4164	      "post_vix_1d": 46.97999954223633,
4177:  4177	      "post_avg_abs_return": 0.005307966397960962,
4180:  4180	      "post_vix_1d": 23.639999389648438,
4193:  4193	      "post_avg_abs_return": 0.004915533339684486,
4196:  4196	      "post_vix_1d": 17.15999984741211,
4209:  4209	      "post_avg_abs_return": 0.004066406010723811,
4212:  4212	      "post_vix_1d": 17.790000915527344,
4225:  4225	      "post_avg_abs_return": 0.007312908442266841,
4228:  4228	      "post_vix_1d": 17.520000457763672,
4241:  4241	      "post_avg_abs_return": 0.003260875590299572,
4244:  4244	      "post_vix_1d": 15.109999656677246,
4257:  4257	      "post_avg_abs_return": 0.009289519546365855,
4260:  4260	      "post_vix_1d": 23.43000030517578,
4273:  4273	      "post_avg_abs_return": 0.007683731822900763,
4276:  4276	      "post_vix_1d": 17.6200008392334,
4289:  4289	      "post_avg_abs_return": 0.002409279073266779,
4292:  4292	      "post_vix_1d": 15.119999885559082,
4305:  4305	      "post_avg_abs_return": 0.0050883787388367185,
4308:  4308	      "post_vix_1d": 20.81999969482422,
4321:  4321	      "post_avg_abs_return": 0.006493442734216037,
4324:  4324	      "post_vix_1d": 25.5,
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
   120	**方向性主結論不變**：以進場 VIX 中位數分組，兩組 NFP 日的波動差距（2.03 倍、p≈4.6e-9）
   121	在數值上遠大於 NFP 對基準的差距（1.11 / 1.19 倍）。
   122	
   123	**這句話的邊界（不要讀過頭）**：這是**條件關聯**，不是因果識別。本實驗**沒有**正式檢定
   124	「2.03 倍顯著大於 1.19 倍」—— 兩者的樣本與對照組都不同，並排只是量級對照，不是統計比較。
   125	也不能反推「所以不是 NFP 本身」：平均差檢定沒拒絕不是零效果的證據，而排序檢定其實拒絕了
   126	（見上）。VIX 分組同時也是**事後**中位數分割，本身帶有樣本內成分。
   127	
   128	### 關於「不顯著」的措辭
   129	
   130	修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
   131	Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
   132	陳述都綁定它自己的檢定：
   133	
   134	- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112，**未拒絕**
   135	- Welch 平均差（**週五公布的 NFP** 對非 NFP 週五）：1.189×，p=0.0209，**拒絕**
   136	  —— 條件於週五，不是關於 NFP 一般而言
   137	- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019，**拒絕**
   138	
   139	平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
   140	排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。
   141	
   142	## 產出檔案
   143	
   144	| 檔案 | 內容 |
   145	|---|---|
   146	| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
   147	| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
   148	| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄；檔內已帶 `superseded: true` / `do_not_cite: true` / 撤回原因，離開檔名也可機器判別 |
   149	| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 換掉的日期 + 文章更正替換清單 |
   150	| `build_article_correction.py` | 文章更正計畫（預設 dry-run **完全不寫**，`--apply` / `--record-plan` 才寫入） |
   151	| `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
   152	| `review_verdict_v3.json` / `codex_review_v3.md` | Codex 三審裁決與全文 |
   153	
   154	## 線上文章更正（`mile_35eef830`）
   155	
   156	### ⚠️ 原 18 條更正清單已全數作廢
   157	
   158	原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
   159	改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
   160	撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
   161	`article_correction.supersedes`。
   162	
   163	### 新清單：19 條，全部是數值重述，0 條方向翻轉
   164	
   165	文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
   166	差距的是進場 VIX 體制 —— 在官方日期下**全部成立**。新清單只改數字
   167	（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
   168	外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。
   169	
   170	19 條已對線上 canonical 文章驗證，全部恰好命中一次。
   171	
   172	```bash
   173	# 主線程在 repo root 執行
   174	uv run python experiments/k528/build_article_correction.py            # 驗證（不寫任何檔）
   175	uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
   176	```
   177	
   178	**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
   179	`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
   180	自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
   181	合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。
   182	
   183	**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
   184	與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
   185	因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。
   186	
   187	## 防迴歸
   188	
   189	事件日期正確性的 owner 是 `tests/test_nfp_official_release_dates.py`（未另開新檔）：
   190	
   191	- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、237 筆在週五、
   192	  212 個日期共通、結果檔宣告 fail-closed
   193	- `test_no_off_cycle_revision_date_is_treated_as_an_event` — **直接釘住 v2 BLOCKER**：
   194	  對 artifact 斷言六個 off-cycle 日期不在事件集合、六個正式發布日在。對 artifact 而非
   195	  只對 accessor 斷言，因為「accessor 是對的」不能證明「出貨的結果用了它」
   196	- `TestControlGroupHasNoNfpDays` — 釘住控制組不含任何已映射 NFP session
   197	- `TestCalendarFailClosedCannotBeBypassed` — 逐條釘住三審找到的繞過路徑：較早的
   198	  off-cycle、選擇非最早、跨度內缺月、allowlist 濫用；外加一個**必須通過**的乾淨日曆
   199	  （只會拒絕的 guard 和永不拒絕的一樣沒用）
   200	- `TestFridayEstimandIsScopedHonestly` — 釘住 conditional estimand 有標示、
   201	  非中性排除有揭露、排除筆數與 weekday 分解一致（結果檔曾經散文寫 11、資料寫 16）
   202	- `TestProxyMutationIsCaught` — mutation test：proxy 日曆餵給 guard 必須被拒；
   203	  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆
   204	
   205	accessor 層的 owner 是 `tests/test_event_dates_release_selection.py` 與
   206	`tests/test_event_dates_real_raw_response.py`（未經編輯的 ALFRED 日期清單 + mutation 檢查）。
   207	後者的 scope 有明寫：它釘的是 `_fetch` 的**回傳值**（原樣、未去重），不是完整 HTTP
   208	response body，所以 `_fetch` 自身的 schema 破壞不在覆蓋範圍內。
   209	
   210	Mutation 已實測：把 `min()` 改回 `max()` 後 `test_regular_release_wins_in_every_duplicate_month`
   211	由綠轉紅（`2006-05-08 != 2006-05-05`），還原後 99 passed。沒被實際觸發過的 gate 不算 gate。
   212	
   213	## 主腳本的 fail-closed 面
   214	
   215	**日曆完整性**（`check_calendar_is_complete`）**同時驗證 raw feed 與 accessor 的選擇**。
   216	只驗證 accessor 的**輸出**是行不通的：accessor 在把資料交出來之前就已經把每個月收斂成一個
   217	日期，等到能檢查輸出的時候，同月歧義早就被（可能錯誤地）默默解決掉了。四道關卡：
   218	
   219	0. 選擇本身要 well-formed：同一個月被選了兩次 → raise；選出來的月份/日期不存在於 raw
   220	   feed → raise（否則後面用 `dict` 建 month→date 對照時，重複的月份會被靜默蓋掉，
   221	   剛好蓋掉我們要找的東西）
   222	1. 選到的不是該月最早一筆 → raise（這正是 v2 BLOCKER 的形狀）
   223	2. 任何同月多筆的月份**必須列在 `REVIEWED_MULTI_ENTRY_MONTHS`**，且選到的日期要與人工
   224	   核對過的答案一致 → 否則 raise（理由見下方「殘留限制」）
   225	3. 觀測跨度**沒有覆蓋到請求視窗**（頭尾任一端短少 > 70 天）→ raise。只檢查跨度「內部」
   226	   的缺口抓不到截斷：feed 提早結束的話，跨度會跟著縮短，於是看起來什麼都不缺
   227	4. 觀測跨度內缺月 → raise。錨定在實際觀測跨度而非 `[start, end]`，移除了舊版
   228	   「首尾月無條件豁免」的漏洞（完整的首月照樣可以無聲消失）
   229	5. `KNOWN_MISSING_MONTHS` 宣稱的缺口，會回頭去 raw feed **驗證它真的是缺口** → 有資料就
   230	   raise。沒有這一關，allowlist 就只是「讓失敗的檢查通過」的另一個名字
   231	
   232	**一個被自己的資料推翻的設計**（留著當紀錄）：這裡原本還有一關「同月兩筆間隔 < 3 天就
   233	視為無法辨識」，理由是「修訂都是報告後數週才報」。拿真實 feed 一跑就被推翻 —— 六個真實
   234	同月多筆月份裡有**三個**（2006-05、2013-05、2020-05）剛好間隔 **3 天**。真實資料橫跨在
   235	自己設的門檻上，那就不是安全檢查，是製造信心的旋鈕，因此整關移除。
   236	`tests/...::test_real_multi_entry_gaps_are_too_small_for_a_gap_rule` 把這個事實釘住，
   237	以免有人再發明一次同樣的規則。
   238	
   239	已知的真實缺口只有 2025-10（政府關門），每筆都要附理由字串。
   240	
   241	**殘留限制（明講，不假裝已完全關上）**：同月選擇用的「取最早一筆」是**啟發式**。它對目前
   242	查過的每一個案例都對，但它無法區分「比正式報告**更早**歸檔的 off-cycle 項目」與報告本身
   243	—— 單靠日期不可能分辨。因此規則照跑，但**額外**要求每個同月多筆的月份都出現在
   244	`REVIEWED_MULTI_ENTRY_MONTHS`（六個月份逐一對照 BLS news-release archive 驗證過）。
   245	新出現的同月多筆月份會**讓整個 run 失敗**，而不是被這支腳本自行假設掉。
   246	第 4、第 3 兩關是三審 round-2 進行期間自查補上的。
   247	
   248	**事件日→交易日對映**：一對一完整性斷言。樣本內發布日找不到三日內交易日 → raise；
   249	兩個發布日映射到同一個 session → raise（原本的 `set()` 去重會把這件事藏起來並靜默減少
   250	事件數）。窗口邊界排除改為明確記錄在 `sample.event_mapping_audit`，不再靜默 `continue`。
   251	
   252	**控制組不含任何 NFP session**：對照組排除**全部 254 個**已映射 NFP session，不只是通過
   253	事件窗篩選的 253 個。因窗口不足被排除的 `2005-01-07` 仍然是真實的 NFP 日，把它留在對照組
   254	就是本實驗存在的理由（「把真的事件日丟進對照組」）的 1/253 版本。三審 Codex 與本輪自查
   255	獨立發現同一件事。
   256	
   257	**原子寫入**：主結果與 audit 皆走 temp file + `fsync` + `os.replace`。
   258	
   259	## 參考
   260	

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab
for p in experiments/k528/k528_rerun_v3_summary.json experiments/k528/review_verdict_v3.json experiments/k528/review_verdict_v4.json experiments/k528/codex_review_v4.md; do git -C "$repo" cat-file -e "${commit}:$p" 2>/dev/null && echo "PRESENT $p" || echo "MISSING $p"; done

git -C "$repo" show "${commit}:experiments/k528/build_article_correction.py" | nl -ba | sed -n '"'175,210p'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_official_dates_results.json" | nl -ba | sed -n '"'100,180p'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_official_dates_results.json" | nl -ba | sed -n '"'430,465p'

git -C \""'$repo" show "${commit}:experiments/k528/review_verdict_v3.json" && git -C "$repo" show "${commit}:experiments/k528/review_verdict_v4.json"' in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
MISSING experiments/k528/k528_rerun_v3_summary.json
PRESENT experiments/k528/review_verdict_v3.json
PRESENT experiments/k528/review_verdict_v4.json
PRESENT experiments/k528/codex_review_v4.md
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
   100	    ],
   101	    "dates_in_common": 212,
   102	    "n_proxy": 254,
   103	    "n_official": 253,
   104	    "nfp_days_on_friday_official": 237
   105	  },
   106	  "win_rate_definition": "share of the sample exceeding the MEDIAN of its comparison group; 0.5 under the null",
   107	  "items": {
   108	    "vol_ratio_vs_all": {
   109	      "label": "NFP vs all non-NFP days (article: 1.10x)",
   110	      "before": {
   111	        "mean_ratio": 1.1035360772013734,
   112	        "nfp_mean": 0.008420922409653335,
   113	        "baseline_mean": 0.0076308537469923455,
   114	        "p_value": 0.1283682008960355,
   115	        "significant_5pct": false,
   116	        "n": 254,
   117	        "median_ratio": 1.1884376842166304,
   118	        "win_rate": 0.5551181102362205
   119	      },
   120	      "after": {
   121	        "mean_ratio": 1.1077777719197994,
   122	        "nfp_mean": 0.00845305173732809,
   123	        "baseline_mean": 0.0076306385193835365,
   124	        "p_value": 0.11206802266548598,
   125	        "significant_5pct": false,
   126	        "n": 253,
   127	        "median_ratio": 1.191581334504972,
   128	        "win_rate": 0.5612648221343873
   129	      },
   130	      "note": "proxy-side median_ratio / win_rate are reconstructed from the archived per-event data, not from the proxy run's own output (it only reported means).",
   131	      "verdict": "NUMERIC_ADJUSTMENT",
   132	      "verdict_reasons": []
   133	    },
   134	    "vol_ratio_vs_friday": {
   135	      "label": "NFP vs non-NFP Friday baseline (article: 1.17x)",
   136	      "before": {
   137	        "mean_ratio": 1.166705672588405,
   138	        "p_value": 0.04213984873387389,
   139	        "significant_5pct": true,
   140	        "n": 239,
   141	        "nfp_days_on_friday": 239,
   142	        "median_ratio": 1.1979193428374169,
   143	        "win_rate": 0.5564853556485355,
   144	        "n_control_friday": 832,
   145	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   146	        "as_published_mixed_weekday": {
   147	          "mean_ratio": 1.168212716801256,
   148	          "p_value": 0.03354366521379227,
   149	          "significant_5pct": true,
   150	          "n": 254,
   151	          "note": "what the proxy run actually published: all 254 events (239 Friday, 15 Monday) against non-NFP Fridays. This is the number the article quoted, so it is kept, but it is NOT the like-for-like comparison against the corrected column."
   152	        }
   153	      },
   154	      "after": {
   155	        "mean_ratio": 1.1889932285781484,
   156	        "p_value": 0.02085474364987024,
   157	        "significant_5pct": true,
   158	        "n": 237,
   159	        "nfp_days_on_friday": 237,
   160	        "median_ratio": 1.2185765501135915,
   161	        "win_rate": 0.569620253164557,
   162	        "estimand": "Friday NFP sessions vs Friday non-NFP sessions (weekday held fixed)",
   163	        "diagnostic_mixed_weekday": {
   164	          "mean_ratio": 1.1767600146677832,
   165	          "p_value": 0.025693120973358435,
   166	          "significant_5pct": true,
   167	          "n": 253,
   168	          "status": "DIAGNOSTIC ONLY - the pre-correction estimand, not quotable"
   169	        }
   170	      },
   171	      "note": "Two things changed here and they are separated rather than conflated. (1) The dates were corrected. (2) The ESTIMAND was corrected: the event group is a weekday mixture while the control group is pure Friday, so the test now restricts the event group to Friday releases. Defect (2) was NOT created by (1) -- the proxy run was already mixed (239/254 Friday, the other 15 being holiday-shifted Mondays), it was simply never noticed. Both columns above therefore use the SAME restricted estimand so the delta is attributable to the dates alone; `as_published_mixed_weekday` (before) and `diagnostic_mixed_weekday` (after) hold the old estimand on each side for reference.",
   172	      "verdict": "NUMERIC_ADJUSTMENT",
   173	      "verdict_reasons": []
   174	    },
   175	    "regime_ratio": {
   176	      "label": "High-VIX vs low-VIX NFP volatility (article: 2.17x)",
   177	      "before": {
   178	        "mean_ratio": 2.1670599373202153,
   179	        "high_mean": 0.011524027931522324,
   180	        "low_mean": 0.005317816887784345,
   430	        "hits": 1
   431	      },
   432	      {
   433	        "from": "高低體制差 2.17 倍，事前 VIX 對就業日波動的預測相關係數約 0.45。",
   434	        "to": "高低體制差 2.03 倍，事前 VIX 對就業日波動的預測相關係數約 0.44。",
   435	        "hits": 1
   436	      },
   437	      {
   438	        "from": "這跟 k528 在 254 場歷史樣本上得到的傾向一致",
   439	        "to": "這跟 k528 在 253 場歷史樣本上得到的傾向一致",
   440	        "hits": 1
   441	      },
   442	      {
   443	        "from": "254 場歷史樣本加上 7/2 這場實測",
   444	        "to": "253 場歷史樣本加上 7/2 這場實測",
   445	        "hits": 1
   446	      },
   447	      {
   448	        "from": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 254 次 NFP 公布日，資料源為 yfinance 的 SPY 與 VIX 日頻數據。",
   449	        "to": "樣本為 2005 年 2 月 4 日至 2026 年 3 月 6 日期間、共 253 次 NFP 公布日，NFP 發布日期取自美國勞工統計局官方發布日曆（透過 FRED release id 50 取得），資料源為 yfinance 的 SPY 與 VIX 日頻數據。\n\n**2026-07-19 更正說明**：本文初版的 NFP 日期是用「每月第一個週五」推算的。與 BLS 官方發布日曆比對後，約兩成對不上——參考週較晚時 BLS 會改在第二個週五發布，遇到假期則會提前，2025 年 10 月更因聯邦政府關門根本沒有發布（初版把這天算成了事件日，但那天並不存在）。改用官方日曆重跑後，樣本從 254 場變成 253 場。\n\n**方向性結論全部維持不變**：對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整（1.10→1.11 倍、1.17→1.19 倍、2.17→2.03 倍、相關係數 0.45→0.44）。\n\n另有一項口徑調整：週五基準的比較，事件組原本是全部樣本（星期別混合）、對照組卻只有週五，兩邊不對等。現改為只取在週五公布的 237 場，維持兩邊星期別一致，所以該數字講的是「在週五公布的 NFP」而非 NFP 一般而言。被排掉的 16 場本身比較平靜，因此限定週五會把倍數墊高一些（不限定為 1.18 倍、限定為 1.19 倍），兩個數字都列出以免只揭露比較好看的那個。\n\n**文中圖表與文末懶人包圖組仍是初版數據，正在重新產製**。逐項前後對照見 experiments/k528/k528_nfp_official_dates_results.json。",
   450	        "hits": 1
   451	      },
   452	      {
   453	        "from": "VIX 高低體制以歷史中位數 16.71 為切點，兩組樣本各 127 筆；",
   454	        "to": "VIX 高低體制以歷史中位數 16.69 為切點，兩組樣本分別為 128 與 125 筆；",
   455	        "hits": 1
   456	      }
   457	    ],
   458	    "apply_result": null,
   459	    "residual_gap": "The two inline charts (nfp_20260703_regime.png, nfp_20260703_baseline.png) and the two lazypack images still render proxy-era numbers. Text and images now disagree; the article carries a visible note saying so. Regenerating and re-uploading them is follow-up work outside this worktree's scope."
   460	  }
   461	}
{
  "kid": "k528",
  "verdict": "FAIL",
  "reviewer": "Codex gpt-5.6-sol / high",
  "reviewed_at": "2026-07-19T16:20:00+08:00",
  "reviewed_commit": "6fd281901",
  "review_artifact": "experiments/k528/codex_review_v3.md",
  "blocking_defects": [
    "controls still contained the real NFP session 2005-01-07, contaminating both headline statistics",
    "audit compared a mixed-weekday `before` against a Friday-restricted `after` while claiming apples-to-apples; the 'proxy was all-Friday' premise was false (239 Friday / 15 Monday)",
    "calendar completeness was still bypassable: validating only the accessor's post-selection output cannot see a same-month ambiguity"
  ],
  "reviewed_sha256": {
    "README.md": "c03d8d495a59544967a7142daa5ea38edd912aa49194729c4f292e08b1e5478d",
    "build_article_correction.py": "78c7f864e4441202722ce733353090d9c7b5b21df97ac1db1fcbd615b257a9d6",
    "k528_nfp_event_study.py": "cccc69b204f263dbb7dc787353e1e4398c44c73d4124c8cccefa79958825b7c6",
    "k528_nfp_event_study_results.json": "fbdcf427d522042fb701f88e0be3d67072ebab4dc0f90c6ed7c4999e577552d2",
    "k528_nfp_official_dates_results.json": "f8078c7a6b43ed09b8c2421922bc99b409065f880827110340164c43584e0dd2"
  },
  "note": "Historical record of one round of the third-review cycle. Superseded by the next round; retained because a verdict is only worth the snapshot it read, and deleting a FAIL teaches the wrong lesson."
}
{
  "kid": "k528",
  "verdict": "FAIL",
  "reviewer": "Codex gpt-5.6-sol / high",
  "reviewed_at": "2026-07-19T16:45:00+08:00",
  "reviewed_commit": "2abb3f68c",
  "review_artifact": "experiments/k528/codex_review_v4.md",
  "blocking_defects": [
    "proxy-side `before` control group still leaked the proxy's own window-dropped 2005-01-07 session",
    "calendar completeness accepted a fully truncated tail, a 3-day-equality gap, selected months absent from raw, and duplicate selected months",
    "TestControlGroupHasNoNfpDays was an algebraic identity and could not fail"
  ],
  "reviewed_sha256": {
    "README.md": "29e8781d3e1860ad041af2f0eecddf1177975daa89709efc16b7a88dfe0d3f8f",
    "build_article_correction.py": "c4e3cf99627faa7a60565e5e9df89d44f99de6bf7900716b59451e25637b2e31",
    "k528_nfp_event_study.py": "da6007e445d846268ea3216944c61b364fc6cd2aa7520d960412d0bf2f8c671e",
    "k528_nfp_event_study_results.json": "fb536843e3c98fe38d7bdd8efc9fca043e245cc004a8ff8b9439148f67ea2137",
    "k528_nfp_official_dates_results.json": "db7e35c3a9ada8e02661e1abcb636dfa07d8bf913ef05bc05af93441f760bdee"
  },
  "note": "Historical record of one round of the third-review cycle. Superseded by the next round; retained because a verdict is only worth the snapshot it read, and deleting a FAIL teaches the wrong lesson."
}

exec
/bin/zsh -lc 'uv run python experiments/k528/build_article_correction.py' in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 116ms:
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

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

git -C "$repo" show "${commit}:experiments/k528/k528_nfp_event_study_results.json" | jq '"'{sample:{total:.sample.total_nfp_events,valid:.sample.event_mapping_audit.n_valid_events,mapped:.sample.event_mapping_audit.n_mapped_to_sessions,controls:.sample.non_nfp_trading_days,total_days:.sample.total_trading_days,friday:.sample.nfp_days_on_friday},main:.main_results,friday_test:.statistical_tests.B_nfp_vs_friday,mann:.statistical_tests.C_mann_whitney,regime:.regime_analysis,predictive:.statistical_tests.E_vix_predictive}'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_event_study.py" | nl -ba | sed -n '"'450,590p'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_event_study.py" | nl -ba | sed -n '"'1280,1415p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
{
  "sample": {
    "total": 253,
    "valid": 253,
    "mapped": 254,
    "controls": 5086,
    "total_days": 5340,
    "friday": 237
  },
  "main": {
    "nfp_avg_abs_return": 0.00845305173732809,
    "nfp_avg_abs_return_pct": "0.845%",
    "non_nfp_avg_abs_return": 0.0076306385193835365,
    "non_nfp_avg_abs_return_pct": "0.763%",
    "friday_baseline_abs_return": 0.007183326788779879,
    "vol_ratio_vs_all": 1.1077777719197994,
    "vol_ratio_vs_friday": 1.1889932285781484
  },
  "friday_test": {
    "test": "Welch t-test, Friday NFP sessions vs Friday non-NFP sessions",
    "estimand": "CONDITIONAL ON FRIDAY. Weekday held fixed on both sides: the event group is restricted to NFP releases that trade on a Friday, and the 16 non-Friday events are excluded rather than compared against a pure-Friday control group.",
    "claim_scope": "This identifies the effect of an NFP release ON A FRIDAY. It does not license a statement about NFP releases in general -- the excluded non-Friday events are quieter, so the restriction raises the ratio relative to the mixed-weekday spec. Any prose quoting this number must say 'Friday NFP', not 'NFP'.",
    "restriction_is_not_neutral": {
      "excluded_mean_abs_return": 0.0071514007343742095,
      "friday_mean_abs_return": 0.008540926910523291,
      "excluded_are_quieter_by_pct": 16.2690325149258
    },
    "n_event": 237,
    "n_control": 834,
    "vol_ratio": 1.1889932285781484,
    "t_stat": 2.3205002846661813,
    "p_value": 0.02085474364987024,
    "significant_5pct": true,
    "excluded_non_friday_events": {
      "n": 16,
      "mean_abs_return": 0.0071514007343742095
    }
  },
  "mann": null,
  "regime": {
    "vix_median_split": 16.690000534057617,
    "high_vix_nfp_abs_return": 0.011276125213428842,
    "low_vix_nfp_abs_return": 0.005562224497800924,
    "n_high": 128,
    "n_low": 125,
    "t_stat": 6.168961645909586,
    "p_value": 4.554489029639581E-9
  },
  "predictive": {
    "test": "Pearson + Spearman correlation",
    "pearson_r": 0.4404312353143255,
    "pearson_p": 1.9831312019194168E-13,
    "spearman_rho": 0.3455048873701663,
    "spearman_p": 1.6699985504624933E-8,
    "slope": 0.0004256117035047841,
    "interpretation": "1pt VIX → 0.0426% more |return|"
  }
}
   450	    # Event day: T
   451	    event_day = spy.iloc[pos]
   452	    # Post-event: T+1 to T+5
   453	    post_window = spy.iloc[pos+1:pos+6]
   454	
   455	    # Unreachable given the window-buffer partition above. Kept as an assertion
   456	    # rather than a `continue`: if the partition ever stops holding, the run
   457	    # must stop, not quietly analyse a smaller sample than it reports.
   458	    if len(pre_window) < 5 or len(post_window) < 5:
   459	        raise RuntimeError(
   460	            f"event {nfp_date.date()} has an incomplete window "
   461	            f"(pre={len(pre_window)}, post={len(post_window)}) despite passing the "
   462	            "window-buffer filter -- the partition and the window logic disagree"
   463	        )
   464	
   465	    row = {
   466	        "date": nfp_date.strftime("%Y-%m-%d"),
   467	        "year": nfp_date.year,
   468	        "month": nfp_date.month,
   469	        "weekday": nfp_date.weekday(),  # should be 4 (Friday)
   470	        "event_return": float(event_day["Return"]),
   471	        "event_abs_return": float(event_day["AbsReturn"]),
   472	        "pre_avg_abs_return": float(pre_window["AbsReturn"].mean()),
   473	        "post_avg_abs_return": float(post_window["AbsReturn"].mean()),
   474	        "pre_vix": float(pre_window["VIX"].iloc[-1]) if pd.notna(pre_window["VIX"].iloc[-1]) else None,
   475	        "event_vix": float(event_day["VIX"]) if pd.notna(event_day["VIX"]) else None,
   476	        "post_vix_1d": float(post_window["VIX"].iloc[0]) if pd.notna(post_window["VIX"].iloc[0]) else None,
   477	        "vix_change_event": None,
   478	        "high_low_range": float((event_day["High"] - event_day["Low"]) / event_day["Close"]),
   479	        "volume_ratio": float(event_day["Volume"] / pre_window["Volume"].mean()) if pre_window["Volume"].mean() > 0 else None,
   480	    }
   481	
   482	    if row["pre_vix"] is not None and row["event_vix"] is not None:
   483	        row["vix_change_event"] = row["event_vix"] - row["pre_vix"]
   484	
   485	    results.append(row)
   486	
   487	df = pd.DataFrame(results)
   488	print(f"  Events with complete data: {len(df)}")
   489	print(f"  Date range: {df['date'].iloc[0]} to {df['date'].iloc[-1]}")
   490	
   491	# ============================================================
   492	# 5. Non-NFP baseline calculation
   493	# ============================================================
   494	print("\n[4/6] Computing non-NFP baseline...")
   495	
   496	# Exclude EVERY NFP session from the control group, not just the ones that
   497	# survived the event-window filter. An event dropped for lacking a pre-window
   498	# is still an NFP day; leaving it in the control group is the exact failure this
   499	# experiment exists to fix ("dump real event days into the control group"), just
   500	# at 1/253 scale instead of 46/254. Found by self-audit before Codex v3.
   501	nfp_set = set(nfp_trading_dates)
   502	non_nfp_mask = ~spy.index.isin(nfp_set)
   503	non_nfp = spy[non_nfp_mask]
   504	n_leaked = len(set(nfp_trading_dates) & set(spy.index[non_nfp_mask]))
   505	if n_leaked:
   506	    raise RuntimeError(f"{n_leaked} NFP session(s) remained in the control group")
   507	
   508	baseline_abs_return = float(non_nfp["AbsReturn"].mean())
   509	baseline_abs_return_std = float(non_nfp["AbsReturn"].std())
   510	baseline_abs_return_median = float(non_nfp["AbsReturn"].median())
   511	
   512	# Friday-only baseline. The event group is a weekday MIXTURE while the control
   513	# group is pure Friday, so any Friday-vs-other-weekday volatility difference
   514	# loads straight onto the estimate. The test below holds weekday fixed on BOTH
   515	# sides.
   516	#
   517	# Note against the obvious story: this defect is NOT introduced by the date
   518	# correction. The proxy calendar was all-Friday by construction, but mapping
   519	# holiday-closed Fridays to the next open put 15 of its 254 events on a Monday
   520	# -- 239/254 = 94.1% Friday, against 237/253 = 93.7% here. The mixture was
   521	# always there and is essentially unchanged; the old spec was already comparing
   522	# a mixed group against a pure-Friday control. Correcting the dates is what made
   523	# it visible, not what caused it.
   524	friday_mask = non_nfp.index.weekday == 4
   525	friday_baseline = float(non_nfp[friday_mask]["AbsReturn"].mean())
   526	friday_baseline_std = float(non_nfp[friday_mask]["AbsReturn"].std())
   527	
   528	print(f"  Non-NFP |return| mean: {baseline_abs_return:.6f} ({baseline_abs_return*100:.3f}%)")
   529	print(f"  Non-NFP |return| median: {baseline_abs_return_median:.6f}")
   530	print(f"  Friday-only baseline: {friday_baseline:.6f} ({friday_baseline*100:.3f}%)")
   531	
   532	# ============================================================
   533	# 6. Statistical tests
   534	# ============================================================
   535	print("\n[5/6] Running statistical tests...")
   536	
   537	nfp_abs_returns = df["event_abs_return"].values
   538	non_nfp_abs_returns = non_nfp["AbsReturn"].values
   539	friday_non_nfp_abs = non_nfp[friday_mask]["AbsReturn"].values
   540	
   541	# --- Test A: NFP vs all non-NFP days ---
   542	t_stat_all, p_val_all = stats.ttest_ind(nfp_abs_returns, non_nfp_abs_returns, equal_var=False)
   543	vol_ratio_all = float(nfp_abs_returns.mean() / non_nfp_abs_returns.mean())
   544	
   545	# --- Test B: NFP vs Friday-only baseline (weekday held fixed on both sides) ---
   546	#
   547	# Estimand choice (k528 Codex v2 finding 5). Two repairs were available:
   548	#   (i)  restrict the event group to Friday releases, or
   549	#   (ii) keep all events and use weekday-matched controls.
   550	# This run takes (i). The non-Friday events are a handful of thin weekday cells
   551	# out of 253 -- cells that thin make (ii) a weighted average dominated by a few
   552	# single-digit strata, with standard errors driven by the smallest of them.
   553	# That is a noisier estimator of a harder-to-state quantity. (i) answers one
   554	# clean question: on a Friday, does an NFP release raise volatility? It costs
   555	# the non-Friday events, which are reported below as a separate descriptive
   556	# line rather than dropped in silence.
   557	#
   558	# The exclusion is not neutral and should not be sold as such: the excluded
   559	# events are quieter than the Friday ones, so restricting RAISES the ratio
   560	# relative to the mixed spec. That is a property of the estimand, not evidence
   561	# of a stronger effect. Both numbers are reported.
   562	nfp_friday_mask = (df["weekday"] == 4).values
   563	nfp_friday_abs = nfp_abs_returns[nfp_friday_mask]
   564	nfp_nonfriday_abs = nfp_abs_returns[~nfp_friday_mask]
   565	
   566	t_stat_fri, p_val_fri = stats.ttest_ind(nfp_friday_abs, friday_non_nfp_abs, equal_var=False)
   567	vol_ratio_fri = float(nfp_friday_abs.mean() / friday_non_nfp_abs.mean())
   568	
   569	# Diagnostic ONLY -- the pre-correction specification, kept so the correction
   570	# audit can show what the contaminated estimand was worth. Not a headline
   571	# number and not eligible to be quoted: its p-value mixes in weekday
   572	# composition, which is exactly the defect being repaired.
   573	t_stat_fri_mixed, p_val_fri_mixed = stats.ttest_ind(
   574	    nfp_abs_returns, friday_non_nfp_abs, equal_var=False)
   575	vol_ratio_fri_mixed = float(nfp_abs_returns.mean() / friday_non_nfp_abs.mean())
   576	
   577	# --- Test C: Wilcoxon rank-sum (non-parametric) ---
   578	u_stat, p_val_wilcox = stats.mannwhitneyu(nfp_abs_returns, non_nfp_abs_returns, alternative='greater')
   579	
   580	# --- Test D: Vol crush pattern (post vs pre) ---
   581	vol_crush = df["post_avg_abs_return"] - df["pre_avg_abs_return"]
   582	t_crush, p_crush = stats.ttest_1samp(vol_crush.values, 0)
   583	
   584	# --- Test E: VIX predictive regression ---
   585	vix_valid = df.dropna(subset=["pre_vix"])
   586	if len(vix_valid) > 10:
   587	    from numpy.polynomial.polynomial import polyfit
   588	    X_vix = vix_valid["pre_vix"].values
   589	    Y_abs = vix_valid["event_abs_return"].values
   590	    slope, intercept = np.polyfit(X_vix, Y_abs, 1)
  1280	        },
  1281	        "F_vix_buildup": {
  1282	            "test": "One-sample t-test (T-5 to T-1 VIX change)",
  1283	            "mean_change": float(np.mean(vix_buildup)) if vix_buildup else None,
  1284	            "t_stat": float(t_buildup) if t_buildup else None,
  1285	            "p_value": float(p_buildup) if p_buildup else None,
  1286	            "anticipatory_buildup": bool(np.mean(vix_buildup) > 0 and p_buildup < 0.05) if t_buildup else None,
  1287	        },
  1288	    },
  1289	    "seasonal_analysis": monthly_stats,
  1290	    "regime_analysis": {
  1291	        "vix_median_split": float(vix_median),
  1292	        "high_vix_nfp_abs_return": float(high_vix.mean()),
  1293	        "low_vix_nfp_abs_return": float(low_vix.mean()),
  1294	        "n_high": int(len(high_vix)),
  1295	        "n_low": int(len(low_vix)),
  1296	        "t_stat": float(t_regime),
  1297	        "p_value": float(p_regime),
  1298	    },
  1299	    "time_trend": {
  1300	        "first_half_abs_return": float(first_half.mean()),
  1301	        "second_half_abs_return": float(second_half.mean()),
  1302	        "t_stat": float(t_trend),
  1303	        "p_value": float(p_trend),
  1304	    },
  1305	    "directional_bias": {
  1306	        "positive_count": int(pos_returns),
  1307	        "negative_count": int(neg_returns),
  1308	        "total": int(pos_returns + neg_returns),
  1309	        "positive_rate": float(pos_returns / (pos_returns + neg_returns)),
  1310	        "binomial_p": binom_p,
  1311	    },
  1312	    "intraday_range": {
  1313	        "nfp_avg_range": float(nfp_range),
  1314	        "non_nfp_avg_range": float(non_nfp_range),
  1315	        "range_ratio": float(range_ratio),
  1316	    },
  1317	    "volume": {
  1318	        "avg_volume_ratio": float(vol_ratio_data.mean()),
  1319	        "pct_above_avg": float((vol_ratio_data > 1).mean()),
  1320	    },
  1321	    "april_nfp": {
  1322	        "n": int(len(april_nfp)),
  1323	        "avg_abs_return": float(april_nfp["event_abs_return"].mean()),
  1324	        "avg_signed_return": float(april_nfp["event_return"].mean()),
  1325	        "positive_rate": float((april_nfp["event_return"] > 0).mean()),
  1326	        "vol_ratio": monthly_stats.get("4", {}).get("vol_ratio"),
  1327	    },
  1328	    "conclusions": conclusions,
  1329	    "practical_implication": (
  1330	        f"Entry VIX regime is the dominant and most reliably measured effect here: "
  1331	        f"{high_vix.mean()/low_vix.mean():.2f}x between high- and low-VIX NFP days "
  1332	        f"(p={p_regime:.4g}). The NFP-day effect itself is smaller and the tests do not "
  1333	        f"agree on it -- the Welch mean-difference test against all non-NFP days gives "
  1334	        f"{vol_ratio_all:.2f}x (p={p_val_all:.4f}) while the one-sided Mann-Whitney gives "
  1335	        f"p={p_val_wilcox:.5f}. Report both. A mean test that does not reject is not "
  1336	        "evidence that the effect is zero, and it does not license the claim that the "
  1337	        "event 'is not NFP itself'."
  1338	    ),
  1339	    "claim_scope_note": (
  1340	        "Every significance statement in this artifact is scoped to its own test. "
  1341	        "The superseded run summarised these as 'insignificant across all tests', "
  1342	        "which contradicted the one-sided Mann-Whitney result in the same file "
  1343	        "(k528 Codex v2 finding 6)."
  1344	    ),
  1345	    "references": [
  1346	        "K513: FOMC/NFP/CPI event study (2005-2025, 668 events)",
  1347	        "Savor & Wilson (2013) JFE — scheduled macro announcements and risk premium",
  1348	        "Lucca & Moench (2015) JFE — pre-FOMC announcement drift",
  1349	    ],
  1350	    "event_data": results,  # full per-event data
  1351	}
  1352	
  1353	out_path = Path(__file__).parent / "k528_nfp_event_study_results.json"
  1354	write_json_atomic(out_path, output)
  1355	
  1356	print(f"  Saved to: {out_path}")
  1357	
  1358	# The correction audit is written separately: it is the artifact the article
  1359	# correction is justified against, and it must stay readable without wading
  1360	# through 254 events of per-day data.
  1361	audit_out = {
  1362	    "experiment_id": "K528",
  1363	    "title": "NFP event-date correction: first-Friday proxy vs official BLS calendar",
  1364	    "generated_at": datetime.now(timezone.utc).isoformat(),
  1365	    "before_source": PROXY_PATH.name,
  1366	    "after_source": out_path.name,
  1367	    "event_date_source": output["event_date_source"],
  1368	    "calendar_diff": {
  1369	        "proxy_only_dates": sorted(proxy_dates - new_dates),
  1370	        "official_only_dates": sorted(new_dates - proxy_dates),
  1371	        "dates_in_common": len(proxy_dates & new_dates),
  1372	        "n_proxy": len(proxy_dates),
  1373	        "n_official": len(new_dates),
  1374	        "nfp_days_on_friday_official": int((df["weekday"] == 4).sum()),
  1375	    },
  1376	    "win_rate_definition": (
  1377	        "share of the sample exceeding the MEDIAN of its comparison group; "
  1378	        "0.5 under the null"
  1379	    ),
  1380	    "items": audit_items,
  1381	    "n_claims_flipped": n_flipped,
  1382	    "n_claims_audited": len(audit_items),
  1383	    "article_correction": {
  1384	        "article_id": "mile_35eef830",
  1385	        "status": "pending - filled in by the correction step",
  1386	        "replacements": None,
  1387	    },
  1388	}
  1389	audit_path = Path(__file__).parent / "k528_nfp_official_dates_results.json"
  1390	write_json_atomic(audit_path, audit_out)
  1391	print(f"  Saved to: {audit_path}")
  1392	print("\nDone!")

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab

git -C "$repo" show "${commit}:experiments/k528/k528_nfp_event_study_results.json" | jq '"'{conclusions,practical_implication,claim_scope_note}'

git -C \""'$repo" show "${commit}:experiments/k528/k528_nfp_event_study_results.json" | nl -ba | tail -n 80

git -C "$repo" show "${commit}:experiments/k528/k528_nfp_event_study.py" | nl -ba | sed -n '"'740,810p'

git -C \""'$repo" show "${commit}:tests/test_nfp_official_release_dates.py" | nl -ba | sed -n '"'1,180p'" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
{
  "conclusions": [
    "Welch mean-difference, NFP vs all non-NFP days: 1.11x, p=0.1121 (does not reject at 5%)",
    "Welch mean-difference, Friday NFP vs Friday non-NFP (CONDITIONAL ON FRIDAY, weekday held fixed): 1.19x, p=0.0209 (rejects at 5%; n=237 vs 834). Scoped to Friday releases; the 16 non-Friday events are quieter, so this is not a statement about NFP releases in general.",
    "Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: p=0.00194 (rejects at 5%)",
    "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, so a rank test can detect a location shift the Welch mean test cannot. Report both; do not summarise them as a single verdict.",
    "No significant vol crush pattern (p=0.7563)",
    "Pre-event VIX predicts event vol (r=0.440, p=0.0000)"
  ],
  "practical_implication": "Entry VIX regime is the dominant and most reliably measured effect here: 2.03x between high- and low-VIX NFP days (p=4.554e-09). The NFP-day effect itself is smaller and the tests do not agree on it -- the Welch mean-difference test against all non-NFP days gives 1.11x (p=0.1121) while the one-sided Mann-Whitney gives p=0.00194. Report both. A mean test that does not reject is not evidence that the effect is zero, and it does not license the claim that the event 'is not NFP itself'.",
  "claim_scope_note": "Every significance statement in this artifact is scoped to its own test. The superseded run summarised these as 'insignificant across all tests', which contradicted the one-sided Mann-Whitney result in the same file (k528 Codex v2 finding 6)."
}
  4251	      "year": 2025,
  4252	      "month": 11,
  4253	      "weekday": 3,
  4254	      "event_return": -0.015242227316648038,
  4255	      "event_abs_return": 0.015242227316648038,
  4256	      "pre_avg_abs_return": 0.00766696099419637,
  4257	      "post_avg_abs_return": 0.009289519546365855,
  4258	      "pre_vix": 23.65999984741211,
  4259	      "event_vix": 26.420000076293945,
  4260	      "post_vix_1d": 23.43000030517578,
  4261	      "vix_change_event": 2.760000228881836,
  4262	      "high_low_range": 0.036274166471176136,
  4263	      "volume_ratio": 1.653162805834644
  4264	    },
  4265	    {
  4266	      "date": "2025-12-16",
  4267	      "year": 2025,
  4268	      "month": 12,
  4269	      "weekday": 1,
  4270	      "event_return": -0.002732285145230273,
  4271	      "event_abs_return": 0.002732285145230273,
  4272	      "pre_avg_abs_return": 0.004417036700791121,
  4273	      "post_avg_abs_return": 0.007683731822900763,
  4274	      "pre_vix": 16.5,
  4275	      "event_vix": 16.479999542236328,
  4276	      "post_vix_1d": 17.6200008392334,
  4277	      "vix_change_event": -0.020000457763671875,
  4278	      "high_low_range": 0.008985574064207708,
  4279	      "volume_ratio": 1.405473152519635
  4280	    },
  4281	    {
  4282	      "date": "2026-01-09",
  4283	      "year": 2026,
  4284	      "month": 1,
  4285	      "weekday": 4,
  4286	      "event_return": 0.006613382996888628,
  4287	      "event_abs_return": 0.006613382996888628,
  4288	      "pre_avg_abs_return": 0.003553059621018151,
  4289	      "post_avg_abs_return": 0.002409279073266779,
  4290	      "pre_vix": 15.449999809265137,
  4291	      "event_vix": 14.489999771118164,
  4292	      "post_vix_1d": 15.119999885559082,
  4293	      "vix_change_event": -0.9600000381469727,
  4294	      "high_low_range": 0.008831969135858403,
  4295	      "volume_ratio": 1.082233862626244
  4296	    },
  4297	    {
  4298	      "date": "2026-02-11",
  4299	      "year": 2026,
  4300	      "month": 2,
  4301	      "weekday": 2,
  4302	      "event_return": -0.00023112214366449724,
  4303	      "event_abs_return": 0.00023112214366449724,
  4304	      "pre_avg_abs_return": 0.008795341750082874,
  4305	      "post_avg_abs_return": 0.0050883787388367185,
  4306	      "pre_vix": 17.790000915527344,
  4307	      "event_vix": 17.649999618530273,
  4308	      "post_vix_1d": 20.81999969482422,
  4309	      "vix_change_event": -0.1400012969970703,
  4310	      "high_low_range": 0.011503586507734424,
  4311	      "volume_ratio": 0.8540439122810275
  4312	    },
  4313	    {
  4314	      "date": "2026-03-06",
  4315	      "year": 2026,
  4316	      "month": 3,
  4317	      "weekday": 4,
  4318	      "event_return": -0.013107129910862048,
  4319	      "event_abs_return": 0.013107129910862048,
  4320	      "pre_avg_abs_return": 0.005363148241470039,
  4321	      "post_avg_abs_return": 0.006493442734216037,
  4322	      "pre_vix": 23.75,
  4323	      "event_vix": 29.489999771118164,
  4324	      "post_vix_1d": 25.5,
  4325	      "vix_change_event": 5.739999771118164,
  4326	      "high_low_range": 0.009444027989863117,
  4327	      "volume_ratio": 1.0906826345022151
  4328	    }
  4329	  ]
  4330	}   740	# ============================================================
   741	print(f"\n--- M. Historical April NFP (for 04/03/2026 article) ---")
   742	april_nfp = df[df["month"] == 4]
   743	print(f"  April NFP events:     {len(april_nfp)}")
   744	print(f"  Avg |return|:         {april_nfp['event_abs_return'].mean():.6f} ({april_nfp['event_abs_return'].mean()*100:.3f}%)")
   745	print(f"  Avg return (signed):  {april_nfp['event_return'].mean():.6f} ({april_nfp['event_return'].mean()*100:.3f}%)")
   746	print(f"  Positive rate:        {(april_nfp['event_return'] > 0).sum()}/{len(april_nfp)} ({(april_nfp['event_return'] > 0).mean()*100:.1f}%)")
   747	if "4" in monthly_stats:
   748	    ms4 = monthly_stats["4"]
   749	    print(f"  Vol ratio:            {ms4['vol_ratio']:.3f}x (p={ms4['p_val']:.4f})")
   750	
   751	# ============================================================
   752	# 9. Summary conclusion
   753	# ============================================================
   754	print(f"\n{'=' * 60}")
   755	print("SUMMARY CONCLUSION")
   756	print("=" * 60)
   757	
   758	sig_level = 0.05
   759	conclusions = []
   760	
   761	# Each conclusion names the test it came from. The previous run collapsed
   762	# several tests into "insignificant across all tests" while the one-sided
   763	# Mann-Whitney in the same artifact was significant at p<0.01 -- a summary that
   764	# contradicted its own numbers. A Welch test on |return| is a test of MEANS;
   765	# it not rejecting is not a finding that the distributions match, and it is
   766	# never evidence that the effect is zero.
   767	conclusions.append(
   768	    f"Welch mean-difference, NFP vs all non-NFP days: {vol_ratio_all:.2f}x, "
   769	    f"p={p_val_all:.4f} ({'rejects' if p_val_all < sig_level else 'does not reject'} at 5%)"
   770	)
   771	conclusions.append(
   772	    f"Welch mean-difference, Friday NFP vs Friday non-NFP (CONDITIONAL ON FRIDAY, "
   773	    f"weekday held fixed): {vol_ratio_fri:.2f}x, p={p_val_fri:.4f} "
   774	    f"({'rejects' if p_val_fri < sig_level else 'does not reject'} at 5%; "
   775	    f"n={len(nfp_friday_abs)} vs {len(friday_non_nfp_abs)}). Scoped to Friday "
   776	    f"releases; the {len(nfp_nonfriday_abs)} non-Friday events are quieter, so this "
   777	    f"is not a statement about NFP releases in general."
   778	)
   779	conclusions.append(
   780	    f"Mann-Whitney one-sided (stochastic dominance, not means), NFP vs all non-NFP: "
   781	    f"p={p_val_wilcox:.5f} ({'rejects' if p_val_wilcox < sig_level else 'does not reject'} at 5%)"
   782	)
   783	if (p_val_all >= sig_level) != (p_val_wilcox >= sig_level):
   784	    conclusions.append(
   785	        "NOTE: the mean-difference and rank tests disagree. |return| is heavy-tailed, "
   786	        "so a rank test can detect a location shift the Welch mean test cannot. "
   787	        "Report both; do not summarise them as a single verdict."
   788	    )
   789	
   790	if vol_crush.mean() < 0 and p_crush < sig_level:
   791	    conclusions.append(f"Vol crush pattern exists (post < pre, p={p_crush:.4f})")
   792	else:
   793	    conclusions.append(f"No significant vol crush pattern (p={p_crush:.4f})")
   794	
   795	if r_vix is not None and p_vix < sig_level:
   796	    conclusions.append(f"Pre-event VIX predicts event vol (r={r_vix:.3f}, p={p_vix:.4f})")
   797	else:
   798	    conclusions.append(f"Pre-event VIX does NOT predict event vol (r={r_vix:.3f}, p={p_vix:.4f})" if r_vix else "VIX regression: insufficient data")
   799	
   800	for c in conclusions:
   801	    print(f"  • {c}")
   802	
   803	print(f"\n  Practical implication:")
   804	print(f"    → Entry VIX regime is the larger and more reliably measured effect "
   805	      f"({high_vix.mean()/low_vix.mean():.2f}x, p={p_regime:.4g})")
   806	print(f"    → The NFP-day effect is smaller; mean and rank tests do not agree on it, "
   807	      f"so it is not established either way")
   808	print(f"    → Non-significance of a mean test is not evidence of no effect")
   809	
   810	# ============================================================
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

exec
/bin/zsh -lc "uv run python -c 'import runpy,json,pandas as pd; ns=runpy.run_path(\"tests/test_nfp_official_release_dates.py\"); m=ns[\"_k528_module\"](); raw=json.load(open(\"tests/fixtures/fred_release_50_nfp_raw_20260719.json\"))[\"release_dates\"]; raw=[d for d in raw if \"2005-01-01\"<=d<=\"2026-03-27\"]; by={}; [by.setdefault(d[:7],[]).append(d) for d in raw]; sel=sorted(min(v) for k,v in by.items() if k"'!="2026-03"); o=m.check_calendar_is_complete(pd.to_datetime(sel),raw,"2005-01-01","2026-03-27"); print("REAL_SHAPE_MISSING_MAR2026_ACCEPTED",o["window_coverage"],"raw_has_2026_03",by["2026-03"],"selected_last",sel[-1])'"'" in /Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
 succeeded in 1179ms:
REAL_SHAPE_MISSING_MAR2026_ACCEPTED {'requested': '2005-01-01..2026-03-27', 'observed': '2005-01-07..2026-02-11', 'head_shortfall_days': 6, 'tail_shortfall_days': 44, 'tolerance_days': 70} raw_has_2026_03 ['2026-03-06'] selected_last 2026-02-11

codex
production helper 的實測反例更直接：用 commit 內真實 fixture，raw 明明含 `2026-03-06`，只把 selected 的 2026-03 刪掉，對原樣本窗 `2005-01-01..2026-03-27` 仍被接受（尾端短少 44 天 < 70）。這不是抽象邊界，而是 cache 與另一次 live `_fetch` 不一致時可發生的同一形狀。固定三檔測試仍是 66/66 綠，代表現有 suite 未覆蓋此洞。
web search: 
web search: https://www.bls.gov/news.release/archives/empsit_05052006.htm
web search: 
web search: site:bls.gov/news.release/archives/empsit_05052006 Employment Situation May 5 2006 ...
exec
/bin/zsh -lc "uv run python -c 'import json,subprocess,pandas as pd; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; c=\"58853f3ab\"; p=json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",f\"{c}:experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json\"])); ev=pd.DatetimeIndex([x[\"date\"] for x in p[\"event_data\"]]); months={d.strftime(\"%Y-%m\") for d in ev}; sample={x.strftime(\"%Y-%m\") for x in pd.period_range(\"2005-01-01\",\"2026-03-27\",freq=\"M\")}; print(\"archive_events\",len(ev),\"unique\",len(set(ev)),\"missing_months\",sorted(sample-months),\"extra_months\",sorted(months-sample))'" in /Users/yhlai0911/volpred-research
 succeeded in 321ms:
archive_events 254 unique 254 missing_months ['2005-01'] extra_months []

exec
/bin/zsh -lc "uv run python -c 'import json,subprocess,pandas as pd,numpy as np; from scipy import stats; repo=\"/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp\"; c=\"58853f3ab\"; p=json.loads(subprocess.check_output([\"git\",\"-C\",repo,\"show\",f\"{c}:experiments/k528/k528_nfp_event_study_results_PROXY_SUPERSEDED.json\"])); ev=pd.DatetimeIndex([e[\"date\"] for e in p[\"event_data\"]]); x=np.array([e[\"event_abs_return\"] for e in p[\"event_data\"]]); d=pd.read_csv(\"paper/volatility-absorption/data/spy_gld_tlt_qqq_eem_vix_2005-2026.csv\",parse_dates=[\"date\"]).set_index(\"date\"); r=d.loc[(d.index>=\"2005-01-01\")&(d.index<\"2026-03-27\"),\"spy_adj_close\"].pct_change().abs().dropna();
for label,s in [(\"archive\",set(ev)),(\"leakfree\",set(ev)|{pd.Timestamp(\"2005-01-07\")})]:
 y=r[~r.index.isin(s)].values; t,pv=stats.ttest_ind(x,y,equal_var=False); print(label,\"n\",len(y),\"ratio\",x.mean()/y.mean(),\"p\",pv,\"median_ratio\",np.median(x)/np.median(y),\"win\",np.mean(x>np.median(y)))'" in /Users/yhlai0911/volpred-research
 succeeded in 952ms:
archive n 5086 ratio 1.1035350117907918 p 0.12837174909998902 median_ratio 1.189622511842395 win 0.5551181102362205
leakfree n 5085 ratio 1.1033587888286511 p 0.12896307111633815 median_ratio 1.1884717076716125 win 0.5551181102362205

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
commit=58853f3ab
for p in experiments/k528/k528_nfp_event_study_results.json experiments/k528/README.md experiments/k528/build_article_correction.py experiments/k528/k528_nfp_event_study.py tests/test_nfp_official_release_dates.py src/volpred/data/event_dates.py; do echo "$p"; git -C "$repo" show "${commit}:$p" | nl -ba | rg '"'dominant|真正拉開|MAX_WINDOW|head_short|tail_short|set\\(multi\\)|REVIEWED_MULTI|proxy_non_nfp_abs_archive|proxy_non_nfp_abs\\)|n_control_friday|k528_rerun_v3_summary|write_text\\(|selected calendar contains month|off_feed|test_proxy_side'; done" in /Users/yhlai0911/volpred-research
 succeeded in 0ms:
experiments/k528/k528_nfp_event_study_results.json
    55	        "head_shortfall_days": 6,
    56	        "tail_shortfall_days": 21,
    59	      "residual_limitation": "Same-month selection uses 'earliest wins', which is a heuristic. It cannot distinguish an off-cycle item filed BEFORE the report from the report itself, so every multi-entry month must additionally appear in REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A new multi-entry month fails the run rather than being assumed."
   273	  "practical_implication": "Entry VIX regime is the dominant and most reliably measured effect here: 2.03x between high- and low-VIX NFP days (p=4.554e-09). The NFP-day effect itself is smaller and the tests do not agree on it -- the Welch mean-difference test against all non-NFP days gives 1.11x (p=0.1121) while the one-sided Mann-Whitney gives p=0.00194. Report both. A mean test that does not reject is not evidence that the effect is zero, and it does not license the claim that the event 'is not NFP itself'.",
experiments/k528/README.md
   151	| `k528_rerun_v3_summary.json` | 本輪修正的機器可讀摘要 |
   165	文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、真正拉開
   223	2. 任何同月多筆的月份**必須列在 `REVIEWED_MULTI_ENTRY_MONTHS`**，且選到的日期要與人工
   244	`REVIEWED_MULTI_ENTRY_MONTHS`（六個月份逐一對照 BLS news-release archive 驗證過）。
experiments/k528/build_article_correction.py
   192	        "真正拉開差距的是進場 VIX 體制——這三點在官方日期下都成立，只有數值小幅調整"
experiments/k528/k528_nfp_event_study.py
   101	REVIEWED_MULTI_ENTRY_MONTHS: dict[str, str] = {
   113	MAX_WINDOW_SHORTFALL_DAYS = 70
   188	            f"selected calendar contains month(s) absent from the raw feed: {invented}. "
   191	    off_feed = sorted(str(d.date()) for d in sel if d not in raw_by_month.get(d.strftime("%Y-%m"), []))
   192	    if off_feed:
   194	            f"selected dates that do not appear in the raw feed at all: {off_feed}."
   216	    unreviewed = sorted(set(multi) - set(REVIEWED_MULTI_ENTRY_MONTHS))
   224	            "REVIEWED_MULTI_ENTRY_MONTHS."
   227	        m: {"selected": str(sel_by_month[m].date()), "reviewed": REVIEWED_MULTI_ENTRY_MONTHS[m]}
   229	        if m in sel_by_month and str(sel_by_month[m].date()) != REVIEWED_MULTI_ENTRY_MONTHS[m]
   242	    head_short = (min(sel) - want_start).days
   243	    tail_short = (want_end - max(sel)).days
   244	    if head_short > MAX_WINDOW_SHORTFALL_DAYS or tail_short > MAX_WINDOW_SHORTFALL_DAYS:
   247	            f"{start}..{end}: first release {min(sel).date()} ({head_short}d in), "
   248	            f"last release {max(sel).date()} ({tail_short}d short of the end). "
   249	            f"Tolerance is {MAX_WINDOW_SHORTFALL_DAYS}d. A truncated feed silently "
   282	        "reviewed_multi_entry_months": dict(sorted(REVIEWED_MULTI_ENTRY_MONTHS.items())),
   287	            "head_shortfall_days": int(head_short),
   288	            "tail_shortfall_days": int(tail_short),
   289	            "tolerance_days": MAX_WINDOW_SHORTFALL_DAYS,
   295	            "REVIEWED_MULTI_ENTRY_MONTHS with a date verified against the BLS archive. A "
   889	proxy_non_nfp_abs_archive = proxy_non_nfp_archive["AbsReturn"].values
   918	    ("baseline mean", proxy_non_nfp_abs_archive.mean(), proxy["main_results"]["non_nfp_avg_abs_return"]),
   949	        "median_ratio": float(np.median(proxy_nfp_abs) / np.median(proxy_non_nfp_abs)),
   950	        "win_rate": win_rate(proxy_nfp_abs, proxy_non_nfp_abs),
   978	        "n_control_friday": int(len(proxy_fri_abs)),
  1330	        f"Entry VIX regime is the dominant and most reliably measured effect here: "
tests/test_nfp_official_release_dates.py
   539	                     "REVIEWED_MULTI_ENTRY_MONTHS", "MAX_WINDOW_SHORTFALL_DAYS"):
   569	    def test_proxy_side_control_group_is_also_clean(self):
   574	        assert before["n_control_friday"] == 832, (
   677	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = "2024-02-06"
   690	        mod.REVIEWED_MULTI_ENTRY_MONTHS["2024-02"] = "2024-02-02"
   716	            mod.REVIEWED_MULTI_ENTRY_MONTHS
src/volpred/data/event_dates.py
   132	            cache.write_text(json.dumps(raw) + "\n")

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
for c in 6fd281901 2abb3f68c; do echo "$c"; for p in README.md build_article_correction.py k528_nfp_event_study.py k528_nfp_event_study_results.json k528_nfp_official_dates_results.json; do git -C "$repo" show "$c:experiments/k528/$p" | shasum -a 256 | awk -v p="$p" '"'{print p, "'$1}'"'; done; done" in /Users/yhlai0911/volpred-research
 succeeded in 128ms:
fatal: ambiguous argument 'xperiments/k528/k528_nfp_event_study_results.json': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
k528_nfp_event_study_results.json e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
fatal: ambiguous argument 'xperiments/k528/k528_nfp_official_dates_results.json': unknown revision or path not in the working tree.
Use '--' to separate paths from revisions, like this:
'git <command> [<revision>...] -- [<file>...]'
k528_nfp_official_dates_results.json e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

exec
/bin/zsh -lc 'repo=/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp
for c in 6fd281901 2abb3f68c; do echo "$c"; for p in README.md build_article_correction.py k528_nfp_event_study.py k528_nfp_event_study_results.json k528_nfp_official_dates_results.json; do git -C "$repo" show "${c}:experiments/k528/$p" | shasum -a 256 | awk -v p="$p" '"'{print p, "'$1}'"'; done; done" in /Users/yhlai0911/volpred-research
 succeeded in 123ms:
k528_nfp_event_study_results.json fb536843e3c98fe38d7bdd8efc9fca043e245cc004a8ff8b9439148f67ea2137
k528_nfp_official_dates_results.json db7e35c3a9ada8e02661e1abcb636dfa07d8bf913ef05bc05af93441f760bdee

codex
審查固定於 commit `58853f3ab`；未使用工作樹外的未提交內容。

## Findings

1. **BLOCKER — 70 天容忍度仍允許真實尾端事件整月消失。**  
   完整性檢查只測 `max(selected)` 到 `end` 是否超過 70 天，卻沒有要求 raw 中存在的月份也必須出現在 selected（[k528_nfp_event_study.py:185](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:185)、[k528_nfp_event_study.py:241](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:241)）。  
   我用 commit 內真實 fixture 實測：raw 含 `2026-03-06`，只從 selected 刪掉 2026-03，原樣本窗 `2005-01-01..2026-03-27` 仍被接受，回報 tail shortfall=44 天。這正好可能發生於 accessor 讀舊 cache、主腳本另做 live `_fetch` 的 production wiring（[k528_nfp_event_study.py:309](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:309)）。現有 truncation test 只測誇張的 9 個月尾段消失，因此未覆蓋這個實際邊界（[test_nfp_official_release_dates.py:657](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:657)）。

2. **BLOCKER — `REVIEWED_MULTI_ENTRY_MONTHS` 是按月份授權，不是按已審 raw 形狀授權；移除 gap gate 確實拆掉一道有效偵測。**  
   程式只檢查 multi-entry 的月份 key 是否已出現在 allowlist，以及 selected 是否等於單一 reviewed date（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)）。我對已審的 `2024-01` raw 加入距正式日一天的 `2024-01-06`，保留既有 `01-05`、`01-10`，production helper 仍接受。也就是已審月份的 feed 後續改形不會觸發重新人工核對；舊 `<3 days` gate 反而會抓到。  
   更根本地，真實資料最小 gap 是「恰好 3 天」（[test_nfp_official_release_dates.py:607](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:607)），並未推翻舊條件 `<3`；README 所稱資料「橫跨」門檻不成立（[README.md:232](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:232)）。應至少 pin 每個 reviewed month 的完整 raw date-set/count，而不只是月份與 selected date。

3. **HIGH — 兩個 proxy 控制組在 all-days audit 的同一個 `before` 物件內混用。**  
   archive 控制組只用來驗證 historical baseline mean（[k528_nfp_event_study.py:888](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:888)、[k528_nfp_event_study.py:916](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:916)）。但 `vol_ratio_vs_all.before` 的 mean ratio、baseline、p-value直接取歷史洩漏 artifact，median ratio、win rate 卻用 leak-free `proxy_non_nfp_abs`（[k528_nfp_event_study.py:939](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:939)）。因此 [official_dates_results.json:108](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:108) 的單一 before item 並非單一 estimand/control definition。應全數重算 leak-free，另巢狀保存 as-published；或全數維持 archive 定義。

4. **HIGH — 新 proxy 測試不是 vacuous identity，但仍只是複述 artifact scalar，沒有驗證「乾淨」性質。**  
   測試只斷言 `n_control_friday == 832`（[test_nfp_official_release_dates.py:569](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:569)）。若 `2005-01-07` 仍洩漏、同時錯排除另一個 Friday，832 照樣通過；程式回歸但未重跑 artifact 也會全綠。應驗證重建只新增 `2005-01-07`、該 session 不在 controls，或從 pinned SPY/session 集合獨立重建。固定三檔測試目前 66/66 通過，仍未抓到 findings 1–2。

5. **MEDIUM — README 殘留上一輪洩漏數字。**  
   artifact 的 proxy restricted before 已是 1.166706、p=0.042140、239 vs 832（[official_dates_results.json:134](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:134)），但 README 仍寫 1.168、p=0.0409（[README.md:93](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:93)、[README.md:110](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:110)）。

6. **MEDIUM — VIX overclaim 只修了一處，reader-facing correction 與 results 仍保留舊結論。**  
   README 新增的條件關聯／非因果／未做 2.03 vs 1.19 正式比較邊界是正確的（[README.md:120](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:120)），但同一 README 後段仍稱「真正拉開差距的是進場 VIX 體制」（[README.md:165](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:165)）。更重要的是，實際會送給讀者的 replacement 仍使用相同措辭（[build_article_correction.py:191](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:191)），results 也稱其為 “dominant … effect”（[results.json:273](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:273)）。三處敘述不一致，v4 MEDIUM 未完整驗收。

7. **MEDIUM — README 仍列出不存在的產物。**  
   `k528_rerun_v3_summary.json` 在 commit tree 中不存在，但仍列於產出表（[README.md:151](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:151)）。`review_verdict_v3.json`、`review_verdict_v4.json`、`codex_review_v4.md` 則已存在，且兩份 verdict 的 historical SHA-256 均與各自 reviewed commit 相符。

## 已驗收項目

- Proxy Friday restricted 統計已修正。我以獨立 SPY snapshot 重算得 1.166709、p=0.042135、239 vs 832，與 artifact 的 1.166706／0.042140 一致；archive 只缺 `2005-01`，重建未移動 254 個已分析事件。
- v4 的 selected 同月重複、selected 發明月份／日期、unreviewed 新月份等原始繞過已個別關閉；但 findings 1–2 顯示 completeness 尚未收斂。
- Official control test 已不再是代數恆等式：固定 5,340 total、254 mapped、5,086 controls，並會抓回歸到 5,087。
- 19 條替換仍各命中 canonical article 一次。抽查 253、0.845/0.763/1.11、237/16、1.19/p=0.021、mixed 1.18、16.69、128/125、1.13/0.56/2.03、Pearson/Spearman 0.44/0.35、0.043pp、0.10 點均與 results 對齊；Friday claim scope 也在讀者可見 replacement 中。
- `pre_vix` 使用 T−1，未見 same-day lookahead；本實驗無隨機程序，seed 不適用。主 results、audit 與 builder 寫入使用 tempfile、`fsync`、`os.replace`；builder dry-run 不寫。
- 共用 event-date cache 仍用非原子的 `write_text`（[event_dates.py:132](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:132)），但損壞通常會 fail on JSON parse，屬可用性風險，未列 blocking。

Blocking defects：完整性檢查仍接受 raw 已含、selected 卻漏掉的近端月份；reviewed multi-entry 月份的 raw 形狀可改變而不觸發重新核對，且移除 `<3 days` gate 使此類錯誤失去偵測。

VERDICT: FAIL
tokens used
162,290
審查固定於 commit `58853f3ab`；未使用工作樹外的未提交內容。

## Findings

1. **BLOCKER — 70 天容忍度仍允許真實尾端事件整月消失。**  
   完整性檢查只測 `max(selected)` 到 `end` 是否超過 70 天，卻沒有要求 raw 中存在的月份也必須出現在 selected（[k528_nfp_event_study.py:185](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:185)、[k528_nfp_event_study.py:241](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:241)）。  
   我用 commit 內真實 fixture 實測：raw 含 `2026-03-06`，只從 selected 刪掉 2026-03，原樣本窗 `2005-01-01..2026-03-27` 仍被接受，回報 tail shortfall=44 天。這正好可能發生於 accessor 讀舊 cache、主腳本另做 live `_fetch` 的 production wiring（[k528_nfp_event_study.py:309](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:309)）。現有 truncation test 只測誇張的 9 個月尾段消失，因此未覆蓋這個實際邊界（[test_nfp_official_release_dates.py:657](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:657)）。

2. **BLOCKER — `REVIEWED_MULTI_ENTRY_MONTHS` 是按月份授權，不是按已審 raw 形狀授權；移除 gap gate 確實拆掉一道有效偵測。**  
   程式只檢查 multi-entry 的月份 key 是否已出現在 allowlist，以及 selected 是否等於單一 reviewed date（[k528_nfp_event_study.py:212](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:212)）。我對已審的 `2024-01` raw 加入距正式日一天的 `2024-01-06`，保留既有 `01-05`、`01-10`，production helper 仍接受。也就是已審月份的 feed 後續改形不會觸發重新人工核對；舊 `<3 days` gate 反而會抓到。  
   更根本地，真實資料最小 gap 是「恰好 3 天」（[test_nfp_official_release_dates.py:607](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:607)），並未推翻舊條件 `<3`；README 所稱資料「橫跨」門檻不成立（[README.md:232](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:232)）。應至少 pin 每個 reviewed month 的完整 raw date-set/count，而不只是月份與 selected date。

3. **HIGH — 兩個 proxy 控制組在 all-days audit 的同一個 `before` 物件內混用。**  
   archive 控制組只用來驗證 historical baseline mean（[k528_nfp_event_study.py:888](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:888)、[k528_nfp_event_study.py:916](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:916)）。但 `vol_ratio_vs_all.before` 的 mean ratio、baseline、p-value直接取歷史洩漏 artifact，median ratio、win rate 卻用 leak-free `proxy_non_nfp_abs`（[k528_nfp_event_study.py:939](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study.py:939)）。因此 [official_dates_results.json:108](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:108) 的單一 before item 並非單一 estimand/control definition。應全數重算 leak-free，另巢狀保存 as-published；或全數維持 archive 定義。

4. **HIGH — 新 proxy 測試不是 vacuous identity，但仍只是複述 artifact scalar，沒有驗證「乾淨」性質。**  
   測試只斷言 `n_control_friday == 832`（[test_nfp_official_release_dates.py:569](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/tests/test_nfp_official_release_dates.py:569)）。若 `2005-01-07` 仍洩漏、同時錯排除另一個 Friday，832 照樣通過；程式回歸但未重跑 artifact 也會全綠。應驗證重建只新增 `2005-01-07`、該 session 不在 controls，或從 pinned SPY/session 集合獨立重建。固定三檔測試目前 66/66 通過，仍未抓到 findings 1–2。

5. **MEDIUM — README 殘留上一輪洩漏數字。**  
   artifact 的 proxy restricted before 已是 1.166706、p=0.042140、239 vs 832（[official_dates_results.json:134](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_official_dates_results.json:134)），但 README 仍寫 1.168、p=0.0409（[README.md:93](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:93)、[README.md:110](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:110)）。

6. **MEDIUM — VIX overclaim 只修了一處，reader-facing correction 與 results 仍保留舊結論。**  
   README 新增的條件關聯／非因果／未做 2.03 vs 1.19 正式比較邊界是正確的（[README.md:120](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:120)），但同一 README 後段仍稱「真正拉開差距的是進場 VIX 體制」（[README.md:165](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:165)）。更重要的是，實際會送給讀者的 replacement 仍使用相同措辭（[build_article_correction.py:191](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/build_article_correction.py:191)），results 也稱其為 “dominant … effect”（[results.json:273](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/k528_nfp_event_study_results.json:273)）。三處敘述不一致，v4 MEDIUM 未完整驗收。

7. **MEDIUM — README 仍列出不存在的產物。**  
   `k528_rerun_v3_summary.json` 在 commit tree 中不存在，但仍列於產出表（[README.md:151](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/experiments/k528/README.md:151)）。`review_verdict_v3.json`、`review_verdict_v4.json`、`codex_review_v4.md` 則已存在，且兩份 verdict 的 historical SHA-256 均與各自 reviewed commit 相符。

## 已驗收項目

- Proxy Friday restricted 統計已修正。我以獨立 SPY snapshot 重算得 1.166709、p=0.042135、239 vs 832，與 artifact 的 1.166706／0.042140 一致；archive 只缺 `2005-01`，重建未移動 254 個已分析事件。
- v4 的 selected 同月重複、selected 發明月份／日期、unreviewed 新月份等原始繞過已個別關閉；但 findings 1–2 顯示 completeness 尚未收斂。
- Official control test 已不再是代數恆等式：固定 5,340 total、254 mapped、5,086 controls，並會抓回歸到 5,087。
- 19 條替換仍各命中 canonical article 一次。抽查 253、0.845/0.763/1.11、237/16、1.19/p=0.021、mixed 1.18、16.69、128/125、1.13/0.56/2.03、Pearson/Spearman 0.44/0.35、0.043pp、0.10 點均與 results 對齊；Friday claim scope 也在讀者可見 replacement 中。
- `pre_vix` 使用 T−1，未見 same-day lookahead；本實驗無隨機程序，seed 不適用。主 results、audit 與 builder 寫入使用 tempfile、`fsync`、`os.replace`；builder dry-run 不寫。
- 共用 event-date cache 仍用非原子的 `write_text`（[event_dates.py:132](/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp/src/volpred/data/event_dates.py:132)），但損壞通常會 fail on JSON parse，屬可用性風險，未列 blocking。

Blocking defects：完整性檢查仍接受 raw 已含、selected 卻漏掉的近端月份；reviewed multi-entry 月份的 raw 形狀可改變而不觸發重新核對，且移除 `<3 days` gate 使此類錯誤失去偵測。

VERDICT: FAIL
EXIT=0
