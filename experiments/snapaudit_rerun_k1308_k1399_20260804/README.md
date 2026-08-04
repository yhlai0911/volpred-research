# snapaudit_rerun_k1308_k1399_20260804 — K1308 / K1399 去重後統計量重跑

**任務**：`assign_ce6097bf`（P1）
**上游**：`experiments/snapaudit_unmeasured_20260728/`（釘 vintage、測列級暴露）
→ 其 result 末尾記的「未竟」項就是本單
**執行**：2026-08-04 hourly dispatch slot-1（job `2607def6`）

## 這一單在補什麼洞

`snapaudit_unmeasured_20260728` 測到的是**列級暴露**（多少重複列進了樣本），
明說「列級暴露只界定爆炸半徑，不等於統計量的變化」。統計量本身從未重算，
於是兩篇**已發佈**文章至今引用的是污染樣本上的數字 —— 其中一篇還把污染後的樣本數
直接寫進正文（「共 119 個交易日」）。本單只做一件事：**算出正確數字**，供 erratum 填空。

**不改任何已發佈文章**（任務硬規定）。更正走 erratum 流程。

## 根因與修法

事件本身（`scripts/refresh_paper_snapshots.py` 併發重複 append，9 個 canonical CSV
各含 10 個重複交易日，2026-05-04~05-15）早已修掉。留下的缺口是 **consumer 端沒有防呆**：

| 實驗 | 缺什麼 | 本單做的 |
|---|---|---|
| k1308 | `load_vix()` **完全沒有 dedup** —— VIXTWN 那側有，VIX 那側沒有，重複列直接穿過 inner merge。這就是 9.17% 暴露的全部來源 | 補上 dedup guard（`keep="last"`，與 k1399 既有慣例一致） |
| k1399 | dedup guard 已在（前一輪 snapaudit 補的） | 不動 |
| 兩者 | 取樣窗口**開放式**，輸入是 append-only → 無 pin 的重跑會悄悄擴大樣本，跟已發佈 vintage 不再可比 | 加 `K1308_PERIOD_END` / `K1399_OOS_END` 環境變數 pin，預設維持原行為 |
| k1308 | `data_sources` 記的是**絕對路徑** | 改寫 repo-relative（見下） |

最後一項不是美化。audit C（`audit_snapshot_dup_20260721`）當初把 k1308 判成
`UNVERIFIABLE_MISSING_INPUT`，就是因為它讀了 `k1308_results.json` 裡那串
`/Users/yhlai0911/Desktop/volpred-research/...`（2026-05 執行當下 repo 的位置，之後 repo 搬家），
發現路徑不存在就結案 —— 而 `k1308.py` 實際是 repo-relative 解析，檔案一直都在。
**stale provenance 字串害稽核誤判過一次，把它改成不會過期的形式才是根治。**

## 方法

`rerun_dedup_corrections.py` 重跑的是**原始實驗腳本本身**，不另寫一份平行算術。三個 pin：

1. **樣本端點**釘到各自已發佈的 period end（k1308: 2026-05-20；k1399 OOS: 2026-05-19）
2. **dedup guard 開啟**
3. **vintage 等價性在執行時檢查、不假設**：把工作區 CSV 與修復後 clean vintage
   `00b07f07f` 在該窗口內逐列比對，不一致就 **abort**（「拿另一份資料集去更正」不叫更正）。
   比對範圍限縮到該實驗**實際讀取的欄位** —— 這些 CSV 帶了許多無關 ticker，其後續修訂
   碰不到本次要更正的數字，要求整檔 byte 穩定會為了不相干的理由 fail。

原始（污染）數值不會被覆蓋掉：完整保存在各 results.json 的
`restatement.superseded_values`，before/after 永遠可回讀。**重跑是冪等的**：
一旦 restatement 存在，比較基準就取自它保存的紀錄，而不是當下磁碟上的內容 ——
否則第二次執行會拿更正值跟自己比、報「零欄位變動」，把 erratum 依賴的 before/after 對照抹掉。
（這個 bug 在本單開發過程中真的發生過一次，修法就是上述 `original_record()`。）

### `keep=` 的選擇是否帶任意性 —— 檢查過，不帶

k1592 那一案的重複列**帶偽造零報酬**（列數乾淨但值錯），那裡 `keep=` 是有實質後果的決定。
本案不能假設同一情況成立或不成立，所以程式化檢查（`dedup_keep_choice_is_immaterial`）：

- 兩個 CSV 上，10 組重複列的**值完全相同**（`duplicate_pairs_value_identical=true`）
- `keep="first"` 與 `keep="last"` **都**逐列重現 clean vintage（`dedup_keep_reproduces_clean_vintage` 兩者皆 true）

→ 本案的更正值不因 `keep=` 而異。**k1592 的教訓不能推廣過來，但也必須實際檢查過才能這樣說。**

> 沒有預測、沒有訊號、沒有新 lag 決策 —— IS/OOS 切分與 `shift` 慣例全部沿用原腳本未改動的部分。

## 結果 1：K1308（`mile_02c71e74`）—— 13 個欄位變動，敘事不翻

樣本 **n=119 → 109**（移除 10 個重複交易日，佔乾淨樣本 9.17%，本次事件最大）。

| 讀者可見數字 | 已發佈（污染） | 更正後 | 變動 |
|---|---|---|---|
| 正文「共 N 個交易日」 | **119** | **109** | −10 |
| 平均比值 | **1.5737** | **1.5237** | −0.050 |
| 最近 30 天均值 | **2.0643** | **1.8716** | −0.193 |
| CV | 0.204 | 0.1874 | −0.017 |
| 標準差 | 0.3211 | 0.2855 | −0.036 |
| 中位數 | 1.4639 | 1.4364 | −0.028 |
| 95% CI | [1.5154, 1.632] | [1.4695, 1.5779] | 整段左移 |
| vs K1181 基準 t | 6.2219 | 4.8669 | −1.355 |
| OLS 趨勢 β | 0.00733 | 0.006498 | −0.0008 |
| 中點均值位移 t | −7.9339 | −6.1435 | +1.79 |
| 前一版基準 1.3906 | 1.3906 | **1.3906** | **不變**（K1181 常數，非本次重算） |

**判定全部不翻**：`overall_stable=false`、`baseline_still_valid=false`、
`trend_significant=true`、`mean_shift_detected=true`、結論仍為 `UNSTABLE`。
文章標題論點（別把 VIX 乘 1.4 套台股）**在更正後更站得住**：
平均比值 1.52 距 1.4 仍遠，且與 K1181 基準 1.3906 的差異仍在 p<0.001 顯著。
9.17% 的暴露改變了每一個小數位，**沒有改變任何一個結論**。

> 注意「前一版基準 1.391」不是本次重算的量：它是 K1181 寫死的常數
> （`K1181_BASELINE["mean"]`），本來就不受污染影響。任務描述把它列為「受影響 headline」，
> 實際核對後判定**未受影響**，erratum 不應更動它。

## 結果 2：K1399（`mile_34157161`）—— 31 個欄位變動，H1..H5 全不翻

**IS n=3,522 不變**（污染日期落在 2026-05，遠在 IS 窗口 2018-12-31 之後），
**OOS n=1,865 → 1,855**。

| 讀者可見數字 | 已發佈（污染） | 更正後 |
|---|---|---|
| 水準 DM t | **−4.40** | **−4.90** |
| MA5 DM t | **−3.53** | **−3.97** |
| T vs L DM t | **+3.47** | **+3.67** |
| All vs L DM t (p) | **−0.40 (p=0.69)** | **−0.25 (p=0.80)** |
| IS n | **3,522** | **3,522**（不變） |
| OOS n | **1,865** | **1,855** |

`H1=PASS / H2=PARTIAL / H3=PARTIAL / H4=FAIL / H5=PASS` **逐條不變**，
六個模型的 QLIKE 排序不變，所有 `harvey_pass` 布林值不變 ——
與 audit C「判定不翻、屬數值更正」的預判一致。

方向上值得記一筆：去重後 **DM 統計量普遍變得更顯著**（水準 −4.40→−4.90），
因為重複列稀釋了損失差序列的變異估計。**污染是讓結果看起來更弱，不是更強** ——
這次沒有「拿掉污染就沒結論了」的風險。

## 三件套與後續

- `rerun_dedup_corrections.py` / `snapaudit_rerun_k1308_k1399_20260804_results.json` / 本 README
- `erratum_fill_ins` 區塊就是 erratum 的填空來源（逐篇、逐數字、published vs corrected）
- **後續（非本單範圍）**：兩篇文章的 erratum 撰寫與發佈；k1308 / k1399 的 knowledge 條目
  待 review verdict 後由主線程寫入（K1259：agent 不得寫 knowledge.json）

## 順帶發現（已另記，非本單修）

`snapaudit_correct_k1319_k1592_original_vintage` 的 result 宣稱
「k1319 results.json + README 加 before/after provenance」，但 `experiments/k1319/k1319_results.json`
在 HEAD 上仍是污染值（`n_total=4129`，DM t −3.0226），git log 只有原始那一筆 commit
`4545c887e`。k1592 那半確實已 committed（`dd2e70b42`）。**k1319 那半的重跑產物沒有落地。**
