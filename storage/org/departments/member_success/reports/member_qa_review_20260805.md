# 12 題真實會員提問逐題處理 + 註冊路徑實測 — 2026-08-05

- 部門：member_success（task_type: member_qa）
- 執行時間：2026-08-05 18:16–18:5x（台灣時間）
- 指派：manager `item_20260805T101556461354Z_0-payments-path-1-12-89-70-ai-i`

---

## A. 12 題真實提問：答案品質不是問題，資料完整性才是

先確認樣本：`questions` 89 題 → `source='user'` 19 題 → 扣掉 2026-03-17 的 6 題種子
（Ivan/Alice/Bob/Charlie/David/Eve）與 1 題 `testtewtrwqetwqtewqtqwet` → **真實提問 12 題**。

**12 題全部已回答，且答案有實質內容與可查證的數據。** 逐題檢查結果：

| # | 日期 | 提問者 | score | 答案長度 | 指向文章 | 問題 |
|---|---|---|---|---|---|---|
| 1 | 03-17 | yihao.lai | 75 | 195 字 | — | ⚠ `answered_at` = NULL |
| 2 | 03-18 | yhlai | 72 | 404 字 | — | ⚠ `answered_at` = NULL |
| 3 | 03-31 | yaoxk1431 | 4 | 48 字 | mile_42ee876c ✅200 | ⚠ 答案僅是指標 |
| 4 | 04-04 | ideahub.everything | 8 | 105 字 | — | — |
| 5 | 04-05 | yihao.lai | 9 | 98 字 | — | — |
| 6 | 04-10 | yaoxk1431 | 35 | 74 字 | mile_e4a1df06 ✅200 | ⚠ 答案僅是指標 |
| 7 | 04-21 | yaoxk1431 | 3 | 500 字 | — | — |
| 8 | 05-25 | yaoxk1431 | 6 | 194 字 | mile_ac709655 ✅200 | — |
| 9 | 06-11 | yaoxk1431 | 4 | 253 字 | — | — |
| 10 | 06-18 | yaoxk1431 | 18 | 229 字 | — | — |
| 11 | 07-11 | yaoxk1431 | None | 209 字 | — | ⚠ `score` = NULL |
| 12 | 07-18 | yaoxk1431 | 82 | 119 字 | — | — |

**答案指向的 3 篇文章全部存活（HTTP 200，實測 volpred.zeabur.app/reports/<id>）**，沒有死連結。
第 7 題（波浪理論 × GRI 205 反貪腐）的回答是本批品質最高的一則——它拒絕硬把三個
沒有共同方法論基礎的領域接起來，逐一說明各領域能說什麼、不能說什麼，並提供 reframe 建議。
這正是研究誠實原則在會員面的正確樣貌，值得當作 member_qa 的範本。

**所以會員問答的問題不在答得好不好，在三個資料完整性缺口**（5/12 命中）：

- **G7 `answered_at` = NULL 但 status='answered'（第 1、2 題）** → 這兩題的回應時間無法計算，
  而「會員提問 SLA」是本部門的 KPI 之一。KPI 現在建立在有洞的欄位上。
- **G8 `score` = NULL 但已回答（第 11 題）** → 評分與排名邏輯把它當作沒分數。
- **G9 答案欄僅是指標（第 3 題 48 字、第 6 題 74 字）** → 會員在站上讀到的是
  「已完成完整分析，見文章 mile_xxx」。文章是活的，但答案本身沒有攜帶任何結論，
  會員必須再點一次才知道答案是什麼。相比之下第 7、10、11 題把核心數字寫進答案裡。

### 評分與實際處理脫鉤（值得經理注意的訊號）

12 題裡有 6 題 score ≤ 9（3、4、4、6、8、9），評分機制判定為低價值／不可答，
**但這 6 題全部都被實際做成了研究並回答**，其中多題還產出了完整文章。
也就是說 score 這個欄位目前既不擋工作、也不引導會員，只是個沒有消費者的數字。
要嘛讓它真的影響處理順序，要嘛承認它不再是決策依據——現況兩頭落空。

## B. 站上「提問排名」正在展示一筆測試垃圾（reader-facing，已在線上）

實測 https://volpred.zeabur.app/questions ：「目前排名 (1)」區塊唯一的一列是

> 排名 2 ｜ `testtewtrwqetwqtewqtqwet` ｜ 提問者 yhlai ｜ 2026年3月20日 ｜ `archived`

這是新訪客進到問答頁看到的第一筆內容，也是全站「提問排名」功能唯一展示的東西。

**根因（已定位，屬流程不屬資料）**：
- 全表只有這一列的 `current_rank` 非 null（`current_rank=2, prev_rank=1, status='archived', score=1`）
- 排程正常在跑（`question_ops_maintain` 今天 18:00:22 執行，exit 0），但回報
  `{"skip": true, "pending_questions": 0}` → 沒有待排題目就整段 skip
- `src/volpred/ops/questions.py:1640` 的 rerank 只對 `final_active`（researching + ranked）
  重寫名次，**archived 的列不在迴圈裡，`current_rank` 不會被清掉**
- 所以這是 sticky field：一題被 archive 之後，它的名次會永遠留著；只要沒有新的
  active 題目蓋過去，它就是排行榜上唯一的內容

**正確修法是流程不是資料**：archive 一題時（或 rerank 時）必須把非 active 列的
`current_rank`/`prev_rank` 設為 NULL。單獨把這一列改成 null 只是止血，下次再 archive
一題還會重演。此檔在 `src/volpred/ops/**`（Codex 熱區），不在本部門 owned_paths，
已送 request 給平台工程部，未自行修改。

## C. 註冊路徑實測 = 硬故障（已另發 P1 incident）

見 `funnel_baseline_20260805.md` 的後續：實測真實 Chrome，`/questions` 的
「提出你的問題」卡片永久停在 skeleton，整頁沒有 textarea 也沒有任何按鈕；
而全前端唯一的 `signInWithOAuth` 就在該卡片內（`questions/page.tsx:277`），
首頁／nav／footer 皆無登入連結。**站上目前沒有任何可用的註冊或登入入口。**
瀏覽器當時是已登入 owner 狀態，所以不是「未登入才壞」。

這解釋了漏斗基線裡三組原本看似獨立的數字：註冊停流 111 天、匿名 session 成長、
登入活躍崩塌——是同一個故障。

已送 P1 incident 給平台工程部（`item_20260805T102018290520Z_incident-questions-skeleton-ren`）
與經理（`item_20260805T102042729498Z`）。

## D. 內容錯配：唯一活躍會員要的東西，我們沒在做

12 題裡 8 題來自 yaoxk1431，是平台目前唯一持續回訪的真實用戶（3–7 月每月不間斷，
每月用掉免費提問額度）。他的 8 題主題分布：

- 總經／產業敘事 → 個股推薦：6 題（營造業、進口車、酒店娛樂、台股 60000 點、台灣五年走向）
- 長期報酬框架：2 題（30 年年化 15%／7% 該問哪些問題）

而平台每月產出的是波動率預測與策略研究。**留存最強的訊號指向我們沒有在寫的題材。**

值得注意的是，這裡已經有一個成功案例可以複製：第 11、12 題（30 年年化 15%／7%）
我們用近百年美股 17,199 個 30 年滾動視窗回答「年化 15% 有 0 個視窗達標、中位數 10.79%」，
既是他要的長期投資框架，也完全落在平台的量化強項裡。第 12 題 score=82，是這批最高分。

**這是可複製的接法：拿會員的敘事型問題當題目，用平台的量化方法回答，而不是換題目。**
已送 request 給內容部，附三個具體選題建議。

## E. 本次新增的觀測／資料缺口（接續 G1–G6）

| # | 缺什麼 | 影響 | 位置 |
|---|---|---|---|
| G7 | `answered_at` 可為 NULL 而 status 已是 answered | 本部門 KPI「會員提問 SLA」算不出來 | questions 表 / 回答寫入端 |
| G8 | 已回答的題可留 `score` = NULL | 排名與優先序邏輯視為無分 | 同上 |
| G9 | 答案欄可只放文章指標不放結論 | 會員需再點一次才拿到答案 | member_qa 產出規範 |
| G10 | archive 不清 `current_rank`（sticky rank） | 排行榜長期展示已封存內容 | `src/volpred/ops/questions.py:1640` |
| G11 | `score` 不影響處理順序也不影響展示 | 評分機制目前無消費者 | 問答 lifecycle |

G10 已送平台工程部。G7–G9、G11 屬問答 lifecycle 規範，建議由本部門在下一班提出
具體修正方案後再請經理裁決要不要動 `src/volpred/ops/questions.py`（該檔非本部門轄區）。
