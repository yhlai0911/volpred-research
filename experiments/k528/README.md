# k528 — NFP 事件研究（SPY 波動率）

- Experiment ID: `k528`
- Created At: 2026-04-16T09:39:52.904348+00:00
- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑；同日第二次修正見下）
- Status: 已重跑，**方向性結論全部不變**，僅數值微調 + 一項口徑澄清

## 問題描述

NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
事件本身」，還是「進場當下的市場狀態」？

## 兩次修正，不要混為一談

本實驗在 2026-07-19 被修正了**兩次**，第二次是修第一次修壞的地方。

### 修正 1：事件日期從 proxy 換成官方日曆

原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 錯得有結構、不是隨機噪音：

- BLS 在參考週較晚的月份會改到**第二個週五**發布
- 遇到聯邦假期會**提前**
- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
- proxy 把每一場都放在**週五**；官方日曆的 253 場有 243 場**發布日**在週五，
  其中 237 場**在週五的交易 session 被吸收**（差額是六個 Good Friday，見下）

錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
同時把真的事件日丟進對照組。這是修正存在的理由。

`get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
release id 50），且**取不到就 raise，不回退 proxy**。

### 修正 2（本輪）：accessor 的同月多筆選擇錯誤

第一次修正的 accessor 對「同月多筆 release 條目」取 `max()`。ALFRED 的 release id 50
在**六個月份**會回兩筆：前一筆是 Employment Situation 正式報告，後一筆是年度季節調整
因子／benchmark 修訂。`max()` 選到了後者 —— 也就是**把修訂當成了就業報告**：

| 月份 | 正確（正式發布） | `max()` 誤選（off-cycle 修訂） |
|---|---|---|
| 2006-05 | 2006-05-05 | 2006-05-08 |
| 2012-12 | 2012-12-07 | 2012-12-12 |
| 2013-05 | 2013-05-03 | 2013-05-06 |
| 2020-05 | 2020-05-08 | 2020-05-11 |
| 2024-01 | 2024-01-05 | 2024-01-10 |
| 2024-08 | 2024-08-02 | 2024-08-21 |

六個日期錯，聽起來只佔 253 場的 2%，但它剛好把 NFP-vs-週五 檢定推過 5% 分界線。
**第一次修正因此得出了一個錯誤的「顯著→不顯著」翻轉，並據此準備了 18 條文章更正 ——
那 18 條會把一個本來正確的結論撤回。** Codex 二審判 FAIL 擋下，未套用。

根修在 `src/volpred/data/event_dates.py`（改 per-month `min()` + 13–110 天 cadence
fail-closed 驗證，commit `305d118a3`）。

**為什麼原本 42 個測試全綠卻沒抓到**：fixture 是手寫的，同月第二筆事先就被刪掉了 ——
測試餵進去的輸入根本表達不出這個 bug。修法不是加更好的斷言，是餵真實輸入：
`tests/test_event_dates_real_raw_response.py` 直接釘住 ALFRED 的 264 筆原始回應
（fixture `tests/fixtures/fred_release_50_nfp_raw_20260719.json`，**禁止去重**，
那六對重複就是迴歸面），並附 mutation 檢查證明舊 `max()` 規則會在這份輸入上失敗。

## 方法

- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
- 檢定（**這六個就是 confirmatory family**，見下方「多重比較」）：Welch t（vs 全體非 NFP
  日 / vs 非 NFP 週五 session）、Mann-Whitney U、VIX 中位數分組 regime 檢定、
  Pearson / Spearman 相關
- 其餘一切（12 個月份格、vol crush、VIX buildup、時間趨勢、方向 binomial）一律
  **exploratory**，只作描述，**不得**當成 5% 發現引用

### 週五基準的口徑（estimand）調整

> **口徑更正（2026-07-20，Codex 五審 B1）**：本節此前寫的是「**在週五公布**的 NFP」。
> 程式篩的其實是**在週五交易 session 被吸收**的 NFP —— 兩者差六場。
> 253 場有效發布中，**243 場發布日在週五**，但只有 **237 場在週五開盤**：
> 2007-04-06、2010-04-02、2012-04-06、2015-04-03、2021-04-02、2023-04-07
> 全是 **Good Friday**，BLS 照常公布、市場休市，消息由**下週一**吸收。
>
> **1.189× / p=0.0209 識別的是「週五 session 是否因吸收 NFP 而波動更大」，
> 不是「發布日落在週五的 NFP」。** 全文已改用前者措辭。
>
> **為什麼是 session weekday 而不是 release weekday**（這不是圖方便，是唯一正確的那個）：
> 被比較的量是**一個 session 的報酬**，要被固定住的干擾是**那個 session 的星期效應**。
> 若改用發布日 weekday 篩 243 場，等於把六筆**週一報酬**放進一個對照組是純週五的比較裡
> —— 那正好把這個限制存在的理由（星期別污染）重新放回來。
> 審查給的另一條路（release weekday + weekday-matched controls）內部自洽，
> 但它回答的是另一個問題，且估計更吵（見下方薄格數的討論）。

事件組是**星期別混合**、對照組是**純週五**，週五本身的波動特性會直接混進 p 值。

**這個缺陷不是日期修正造成的 —— 修正只是讓它被看見。** proxy 的*日曆*確實每場都是週五，
但遇休市會映射到下一個 session，所以它實際的 254 場事件裡有 **15 場是週一**（239/254 =
94.1% 在週五）；官方日曆是 237/253 = 93.7%。混合程度幾乎沒變，舊版一直都在拿混合事件組
比純週五對照組，只是從來沒人注意到。

本輪把事件組**限定為在週五 session 交易的 237 場**，兩邊星期別一致。另一個選項是保留全部
253 場改用 weekday-matched controls，未採用的理由：被排除的 16 場按 **session** 星期別是
週一 6、週二 2、週三 1、週四 7，用這種格數做加權平均，標準誤會被 1 筆的週三格主導
—— 那是對一個更難陳述的量做更吵的估計。

（那 6 筆週一 session 就是上面的六個 Good Friday；其餘 10 筆是發布日本身就不在週五
—— 週二 2、週三 1、週四 7。兩種來源合起來 16 筆，與 253 − 237 一致。）

**限定週五不是中性的樣本刪除，這點必須明講**：被排除的 16 場平均 |ret| 是 0.715%，比週五
NFP 的 0.854% **低 16.3%**，所以限定之後 ratio 會被墊高（1.177× → 1.189×）。那是口徑的
性質，不是效果變強的證據。（六個 Good Friday 子集平均 |ret| = 0.715%，與 16 場整體幾乎
相同 —— 巧合，不是同一個數字，兩者都由 `sample.friday_estimand` 與 `event_data` 算得出。）

**因此這個檢定識別的是「在週五 session 被吸收的 NFP」**，既不是「NFP 一般而言」，
也不是「發布日在週五的 NFP」。引用這個數字的文字必須寫「在週五交易 session 的 NFP」。

兩種口徑在 audit 中**兩邊平行呈現**（修正前後各自都算了兩種），不拿不同口徑硬比：

| | 限定週五（主口徑） | 混合星期別（舊口徑） |
|---|---|---|
| 修正前（proxy） | 1.167× / p=0.0421 / n=239 | 1.168× / p=0.0335 / n=254（文章當初引用的） |
| 修正後（官方） | **1.189× / p=0.0209 / n=237** | 1.177× / p=0.0257 / n=253（DIAGNOSTIC ONLY） |

（proxy 側的兩格對照組定義不同：限定週五那格用的是**去洩漏**的對照組 832 筆，
「文章當初引用的」那格保留當年含洩漏的原值 —— 前者才是與修正後同口徑的比較。）

**兩種口徑、修正前後，四格全部達到 nominal 顯著** —— 「顯著→不顯著」的翻轉在任何一種
讀法下都不成立。（「nominal」不是修辭上的客氣：四格都沒有做多重比較校正，校正後的說法見
下方「多重比較」。翻轉與否的判斷不受影響 —— 前後兩欄用同一個口徑、同一組檢定。）

## 結果：逐項前後對照

每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
而中位數與勝率在底下已經移位。

兩欄使用**相同口徑**，所以差異可歸因於日期本身，不是口徑改動。

| 指標 | 修正前（proxy） | 修正後（官方，本輪） | 判定 |
|---|---|---|---|
| 樣本數 | 254 | 253（212 個日期共通） | 數值微調 |
| NFP vs 全體非 NFP（平均） | 1.103× (p=0.129, NS) | 1.108× (p=0.112, NS) | 數值微調 |
| ↳ 中位數比 / 勝率 | 1.188× / 0.555 | 1.192× / 0.561 | 數值微調 |
| 週五 session NFP vs 非 NFP 週五（平均） | 1.167× (p=0.0421, nominal 顯著, n=239) | 1.189× (p=0.0209, **仍 nominal 顯著**；Holm=0.0417, n=237) | 數值微調 |
| ↳ 中位數比 / 勝率 | 1.198× / 0.557 | 1.218× / 0.570 | 數值微調 |
| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.027× (p=4.6e-9) | 數值微調（仍極顯著） |
| ↳ 中位數比 / 勝率 | 2.265× / 0.717 | 2.073× / 0.695 | 數值微調 |
| 事前 VIX 相關（Pearson） | 0.451 | 0.440 | 數值微調 |
| ↳ Spearman | 0.377 | 0.346 | 數值微調 |
| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |

**6 項受稽核宣稱中，0 項結論翻轉。**

**方向性主結論不變**：以進場 VIX 中位數分組，兩組 NFP 日的波動差距（2.03 倍、p≈4.6e-9）
在數值上遠大於 NFP 對基準的差距（1.11 / 1.19 倍）。

**這句話的邊界（不要讀過頭）**：這是**條件關聯**，不是因果識別。本實驗**沒有**正式檢定
「2.03 倍顯著大於 1.19 倍」—— 兩者的樣本與對照組都不同，並排只是量級對照，不是統計比較。
也不能反推「所以不是 NFP 本身」：平均差檢定沒拒絕不是零效果的證據，而排序檢定其實拒絕了
（見上）。VIX 分組同時也是**事後**中位數分割，本身帶有樣本內成分。

### 關於「不顯著」的措辭

修正前的結果檔寫過 NFP 效果 "insignificant across all tests"，但同一份檔案裡單尾
Mann-Whitney 的 p=0.0088 明確顯著 —— 那句總結**與它自己的數字矛盾**。本輪起每個顯著性
陳述都綁定它自己的檢定：

- Welch 平均差（vs 全體非 NFP 日）：1.108×，p=0.112（Holm 0.112），**未拒絕**
- Welch 平均差（**在週五 session 交易的 NFP** 對非 NFP 週五）：1.189×，p=0.0209，
  **nominal 拒絕**；confirmatory family 內 Holm=0.0417，**仍拒絕**；對全部 22 個
  inferential outputs 校正則 Holm=0.375，**不拒絕**
  —— 條件於週五 session，不是關於 NFP 一般而言，也不是關於「發布日在週五」
- Mann-Whitney 單尾（隨機優勢，不是平均）：p=0.0019（Holm 0.0058），**拒絕**

平均差檢定沒拒絕，**不等於**分佈相同，更不是效果為零的證據。|return| 厚尾，
排序檢定抓得到平均檢定抓不到的位移。兩個都報，不合併成單一裁決。

## 多重比較（Codex 五審 B4）

這支腳本產出 **22 個 p 值**，先前卻在沒有宣告 family 的情況下，就對其中一個寫「顯著（5%）」。
那不是一個站得住的 5% 宣稱，只是一個 **nominal** 的。

**Confirmatory family（6 個）** = 上方「方法 § 檢定」那一行列出的六個檢定，也是線上文章唯一
據以做方向性判讀的那些。其餘全部標 **exploratory**。

| 檢定 | p (nominal) | Holm（family=6） | 5% 存活 |
|---|---|---|---|
| E VIX Pearson | 1.98e-13 | 1.19e-12 | ✓ |
| H VIX regime Welch | 4.55e-09 | 2.28e-08 | ✓ |
| E VIX Spearman | 1.67e-08 | 6.68e-08 | ✓ |
| C Mann-Whitney 單尾 | 0.00194 | 0.00582 | ✓ |
| **B 週五 session Welch** | **0.0209** | **0.0417** | **✓** |
| A vs 全體非 NFP Welch | 0.1121 | 0.1121 | ✗ |

**週五結果的三種讀法，全部照實報**：

| 口徑 | 值 | 判定 |
|---|---|---|
| Nominal | p=0.0209 | 拒絕 |
| Holm，confirmatory family（6） | p=0.0417 | 拒絕 |
| Holm，全部 inferential outputs（22） | p=0.375 | **不拒絕** |

**這個 family 不是預先登記的，必須講清楚。** 六個 endpoint 早於日期修正與本輪重跑就存在
（可由修正前的腳本版本查證），但**沒有**在看到資料之前被登記下來。所以：

- 兩種 family 的結果**並列呈現**，不挑對自己有利的那個講
- 可以寫的：「nominal 顯著；在六項 confirmatory family 內通過 Holm 校正（**該 family 非預先登記**，
  且對全部 22 個 inferential outputs 校正後不拒絕 —— 見上方三種讀法）」
- **不可以寫的**：不加限定的「顯著」、或宣稱它對任何 family 選擇都穩健

**為什麼用 Holm 不用 Romano-Wolf**：這個 family 混了 Welch t、Mann-Whitney U 與兩個相關檢定，
且樣本互相重疊；沒有單一 resampling 方案對四者同時有效。Holm 在**任意相依**下都控制 FWER。
Romano-Wolf 在存在合適聯合重抽方案時更有檢定力 —— 但為了換檢定力而自行發明一個方案，
在一份專門處理「過度宣稱」的更正裡是錯的取捨。

機器可讀版本在結果檔的 `multiplicity`，且每個檢定條目都被**機械蓋章**（`_stamp`）標上它所屬
的 family 與校正值；新增檢定卻沒歸入 family 會讓 run 失敗，避免「未宣告 family」被重新蓋回來。

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
| `test_k528_completeness_gate.py` | 日曆完整性 gate 的對抗測試（14 passed，含端點截斷與反空洞） |
| `test_k528_price_coverage_gate.py` | 價格覆蓋 / VIX 新鮮度 gate 的對抗測試（10 passed） |
| `k528_round5_remediation.json` | 五審四個 blocker 的處置紀錄（before/after、證據、測試、Holm 表） |

## 線上文章更正（`mile_35eef830`）

### ⚠️ 原 18 條更正清單已全數作廢

原清單是對著**被污染的 JSON** 建的，且包含一個**錯誤的方向翻轉**（把「達到顯著水準」
改寫成「p=0.057，差一點過線但沒過」）。文章原本寫的是對的；套用那 18 條等於發佈一則
撤回正確結論的更正。作廢原因已寫入 `k528_nfp_official_dates_results.json` 的
`article_correction.supersedes`。

### 新清單：19 條，全部是數值重述，0 條方向翻轉

文章原始的三個方向性判讀 —— 對全體交易日基準未達顯著、對週五基準達到顯著、進場 VIX
高低兩組的差距是本研究中最大的數字 —— 在官方日期下**全部成立**（第三點的邊界見上文
「這句話的邊界」：是量級並排，不是排名，也未做正式比較）。新清單只改數字
（1.10→1.11、1.17→1.19、2.17→2.03、0.45→0.44、254→253、16.71→16.69 等），
外加一段讀者可見的更正說明，內含週五基準的口徑調整揭露。

19 條已對線上 canonical 文章驗證，全部恰好命中一次。

```bash
# 主線程在 repo root 執行
uv run python experiments/k528/build_article_correction.py            # 驗證（不寫任何檔）
uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
```

**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。

**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
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

**這一節的宣稱範圍（2026-07-20 收緊）**：以下關卡對「**無聲的**資料短少」fail-closed
—— 取不到日曆、選錯同月條目、跨度內缺月、raw 與 selected 不一致、端點月被截掉、
價格序列覆蓋不足、VIX 陳舊。它們**不**涵蓋「有人寫下一則假的 `KNOWN_MISSING_MONTHS`
理由、同時把該月從 raw feed 移除」這種**有文件的假宣稱**。
先前這一節寫得像是後者也涵蓋在內；那是溢出的宣稱，已撤回。

**日曆完整性**（`check_calendar_is_complete`）**同時驗證 raw feed 與 accessor 的選擇**。
只驗證 accessor 的**輸出**是行不通的：accessor 在把資料交出來之前就已經把每個月收斂成一個
日期，等到能檢查輸出的時候，同月歧義早就被（可能錯誤地）默默解決掉了。四道關卡：

0. 選擇本身要 well-formed：同一個月被選了兩次 → raise；選出來的月份/日期不存在於 raw
   feed → raise（否則後面用 `dict` 建 month→date 對照時，重複的月份會被靜默蓋掉，
   剛好蓋掉我們要找的東西）
1. 選到的不是該月最早一筆 → raise（這正是 v2 BLOCKER 的形狀）
2. 任何同月多筆的月份**必須列在 `REVIEWED_MULTI_ENTRY_MONTHS`**，且選到的日期要與人工
   核對過的答案一致 → 否則 raise（理由見下方「殘留限制」）
3. 觀測跨度**沒有覆蓋到請求視窗**（頭尾任一端短少 > 70 天）→ raise。只檢查跨度「內部」
   的缺口抓不到截斷：feed 提早結束的話，跨度會跟著縮短，於是看起來什麼都不缺
4. 觀測跨度內缺月 → raise。錨定在實際觀測跨度而非 `[start, end]`，移除了舊版
   「首尾月無條件豁免」的漏洞（完整的首月照樣可以無聲消失）
5. `KNOWN_MISSING_MONTHS` 宣稱的缺口，會回頭去 raw feed **驗證它真的是缺口** → 有資料就
   raise。沒有這一關，allowlist 就只是「讓失敗的檢查通過」的另一個名字
6. **端點期望**（本輪新增，見下）：由**請求視窗**推導出「哪些月份非有不可」，
   raw 與 selected 同時被截掉一個端點月時仍會 raise

### 端點期望 —— 修掉「同刪首/尾月仍通過」（Codex 五審 B2）

**上面第 1–5 關全都是拿 feed 檢查 feed**：比對 raw 與 selected、或看觀測跨度內部。
把一個端點月**從 raw 和 selected 同時刪掉**，這些關卡全部依然自洽 —— raw 與 selected 仍然
一致、跨度仍然沒有內部缺口、70 天容忍度剛好容得下整整一個月。Codex 獨立重現：

| 攻擊 | raw/selected | head 短少 | tail 短少 | 舊版判定 |
|---|---|---|---|---|
| 刪 `2005-01` | 259 / 253 | 34d | 21d | **通過** |
| 刪 `2026-03` | 259 / 253 | 6d | 44d | **通過** |

修法是引進一個 feed 動不到的量尺：**請求視窗本身**。若視窗完整包含某月的可能發布區間
（該月 1 日 ~ `LATEST_OBSERVED_RELEASE_DAY_OF_MONTH`），該月就**必須**有一筆發布。
截短 feed 不會改變請求視窗，所以期望不會跟著縮水。

那個常數（=22，來自 2013-10-22，2013 年關門延後的最晚一筆）**會自我巡查**：
feed 裡若出現比它更晚的發布，代表這條規則的前提過期了，run 直接 raise 要求重新推導，
而不是默默地少要求幾個月。

**這一關是實測過會響的，不是宣稱**（`test_k528_completeness_gate.py`，14 passed）：

- `test_endpoint_month_deleted_from_raw_and_selected_is_rejected[head|tail]` —— 攻擊被擋
- `test_endpoint_truncation_is_invisible_without_the_new_check[head|tail]` —— **反空洞**：
  只把這一關關掉、其餘防線全留，同樣的攻擊就**被接受**。這是修復前的行為，
  它證明上面那條測試測的不是一個本來就已經work的東西
- `test_endpoint_expectation_is_derived_from_the_window_not_the_feed` —— 釘住「縮小請求視窗
  會改變要求、截短 feed 不會」這個性質本身
- `test_release_later_than_the_constant_invalidates_the_expectation` —— 釘住常數自我巡查

直接的前後對照（同一支攻擊分別餵給 HEAD `73dca01d0` 與修復後）：

```
--- PRE-FIX  (HEAD 73dca01d0) ---
  delete head month 2005-01: ACCEPTED  (259 raw / 253 selected, head_short=34d tail_short=21d)
  delete tail month 2026-03: ACCEPTED  (259 raw / 253 selected, head_short=6d  tail_short=44d)
--- POST-FIX (working tree) ---
  delete head month 2005-01: RAISED    the requested window ... fully contains the publication window of 1 month(s)...
  delete tail month 2026-03: RAISED    the requested window ... fully contains the publication window of 1 month(s)...
```

**殘留限制（明講）**：端點期望仍可被「把該月加進 `KNOWN_MISSING_MONTHS`」壓掉。
那是刻意的 —— 2025-10 確實被取消 —— 並且由第 5 關（回頭驗 raw feed）限制住。
沒被涵蓋的情形是：**同時把該月從 raw feed 刪掉、又書面宣告它不存在**。
那是一則**有文件的假宣稱**，不是無聲截斷。**本 gate 對後者 fail-closed，對前者不是。**

### 價格資料的覆蓋與新鮮度（Codex 五審 B3）

日曆有五道完整性關卡，被它 join 的**價格序列先前一道都沒有**。SPY 尾端少一個月不會拋錯、
也不會產生 NaN —— 超出範圍的發布會被靜靜歸類成 `outside_price_sample`，計數、然後跳過。
^VIX 尾端短缺更糟：`ffill()` 會把最後一筆真實報價蓋到之後每一個 session 上，
於是 regime 分組與相關檢定跑在一個看起來像資料的常數上。

本輪新增（`check_price_coverage` / `check_vix_forward_fill_age`，都寫成**函式**以便被測試
攻擊 —— 沒被實際觸發過的 guard 與不存在的 guard 失效方式相同）：

- SPY 與 ^VIX 都必須覆蓋到請求視窗兩端（容忍 10 天，涵蓋最長的假日連休）
- `n_outside_price_sample` 必須為 **0**。此固定歷史樣本的日曆與價格用同一個視窗請求、
  且兩端都已驗證，所以「發布落在價格樣本外」不再是設計邊界，而是下載短少
- forward-fill 的 VIX 最多只能連續攜帶 **3 個 session**（本樣本實測最大值 = 0）

`test_k528_price_coverage_gate.py`（10 passed）逐項攻擊：頭/尾各刪一個月、空下載、
VIX 尾端截短一個月、VIX 開頭缺值；外加正面控制（完整覆蓋要通過、單日假日缺口要允許
forward-fill）與一個反空洞測試（證明 `ffill` 自己**不會**抗議，所以擋下它的是這道 gate）。

**一次我自己搞砸又修回來的紀錄**（留著，因為它是這份文件最有用的部分）：

我一度宣稱「同月兩筆間隔 < 3 天視為無法辨識」這一關被真實資料推翻 —— 理由是六個真實
同月多筆月份裡有三個（2006-05、2013-05、2020-05）剛好間隔 **3 天**，看起來資料橫跨在
門檻上。**那是我讀錯了自己寫的條件**：判斷式是 `gap < 3`，而 3 天是**通過**的。真實資料
從頭到尾沒有推翻這一關；是我先把 `<` 改成 `<=`（於是它開始誤報三個合法月份），再拿這個
自己造成的誤報當證據，把整關刪掉。

Codex 第四輪指出這件事，該關已還原為 `< 3`（六個真實案例全部通過）。
`tests/...::test_real_multi_entry_gaps_are_too_small_for_a_gap_rule` 釘住「最小 gap = 3」
這個事實，讓下一個想動這個門檻的人先看到真實分佈。

教訓不是「別碰啟發式」，而是：**在拿資料推翻一條規則之前，先確認你測的是那條規則本身，
而不是你剛剛改壞的版本。**

已知的真實缺口只有 2025-10（政府關門），每筆都要附理由字串。

**殘留限制（明講，不假裝已完全關上）**：同月選擇用的「取最早一筆」是**啟發式**。它對目前
查過的每一個案例都對，但它無法區分「比正式報告**更早**歸檔的 off-cycle 項目」與報告本身
—— 單靠日期不可能分辨。因此規則照跑，但**額外**要求每個同月多筆的月份都出現在
`REVIEWED_MULTI_ENTRY_MONTHS`（六個月份逐一對照 BLS news-release archive 驗證過）。
新出現的同月多筆月份會**讓整個 run 失敗**，而不是被這支腳本自行假設掉。
第 4、第 3 兩關是三審 round-2 進行期間自查補上的。

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
