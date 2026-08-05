# K1815 — Nested Clark-West increment test, vix-sufficiency Family 10 (overnight VIX gap)

**狀態**: COMPLETED — Verdict **NULL**: F10 nested Clark-West FAILS Harvey |t|>3.0
**日期**: 2026-08-05/06
**Task**: 運營經理 P2 派工（`item_20260805T200533864779Z`），承接論文部 vix-sufficiency F10
（論文部無 `experiments/` 寫入權，已轉交研究部）
**Adjudication**: `storage/org/departments/publications/adjudications/vix_sufficiency_f3_f9_f10_20260805.md`
**Predecessors**: k1116c（weekly F12/F13）→ k1116e（daily F2/F4）→ k1116g（daily F1/F8/F11）— 全部同一套
nested-CW harness

## 1. 動機 (WHY)

vix-sufficiency paper 的核心 claim 是 NULL：13 個 signal families 沒有一個對 VIX alone 有統計顯著
的樣本外改善。Table 3/4 對每個 daily family 報標準 DM |t|，k1116e/k1116g 已對其中 5 個 daily
families 做過**更 powerful 的 nested Clark-West (2007)** 檢定驗證這個 null 是否撐得住。剩下 F3/F9/
F10 原本被標「blocked on external data」延後——論文部 2026-08-05 的裁決推翻了這個標記：F10 定義
`|VIX_open,t − VIX_close,t−1|`（main_v5.tex:240）只需要每個其他 family 都已經在用的 daily `^VIX`
OHLC 的 Open 欄，不是 intraday tick 資料，沒有外部依賴、沒有 provisioning 決策。**F10 是三者中最
值得跑的一個**：它的主表 DM |t|=1.12 是三者最大，而且開盤原點確實在其他 family 共用的
close-of-t−1 資訊集之外——裁決文件明講「若 |CW t|>3.0，那是發現不是麻煩」，不能預先框住結果。

## 2. 方法 (HOW) — 與 k1116e/k1116g 同一 harness

- **Target**: SPY 22-day **FORWARD** realized vol（annualized ×100），over (t, t+H]，H=22。
- **Baseline (restricted M2)**: `fwd_rv22 ~ 1 + VIX_level`，VIX_level = VIX close-of-day-t，
  與 k1116e/k1116g 的 baseline **完全相同**（同一個 unlagged 序列的 Close 欄）。
- **Augmented (nests M2)**: `fwd_rv22 ~ 1 + VIX_level + sig_F10_overnight_vix`
- **sig_F10_overnight_vix[t] = |VIX_Open[t] − VIX_Close[t−1]|**：兩腿都來自**本實驗獨立下載的
  unlagged 每日 `^VIX` OHLC**（`auto_adjust=False`），刻意不共用這個複現包裡其他 family 用的
  lagged VIX pin——那份 pin 的存在理由（強制 no-lookahead）對 F10 反而是錯的：F10 的訊號本來就是
  「day-t 開盤那一刻」，套用日頻家族的 shift 會在看起來很嚴謹的同時毀掉這個訊號（裁決文件原話）。
- **Lookahead 檢查**：VIX_Open[t] 在 day-t 開盤即已知，早於 day-t 收盤（baseline 用的資訊）與
  target 的實現窗口 (t, t+H]（嚴格晚於 day-t 收盤才開始累積）。baseline 與 augmented 兩個模型
  用的資訊都嚴格早於 target 窗口 → 無 lookahead。
- **Clark-West**: `f_hat = e1² − e2² + (f1−f2)²`，one-sided H1: E[f_hat]>0，|t|>3.0 = Harvey pass。
  HAC nw_lag=21、HLN h=22（forward-overlap 校正）。
- **IS/OOS split**: IS ≤2018-12-31，OOS 2019-01-02 → 2026-05-28（n_oos=1861）——**與 k1116e/k1116g
  逐字相同的日期切分**（`END_DATE="2026-07-01"` 沿用預代碼），使 CW 欄可以直接橫向比較。

### 與其他 daily families 的資訊集差異（誠實揭露）

其他 daily families 的 baseline 與 signal 都用同一個 close-of-day-t 資訊集。F10 的 signal 用的是
**day-t 開盤**（早於 day-t 收盤），比 baseline 用的資訊更早一點點。這不是 bug——這正是論文自己
對 F10 的定義（唯一明確揭露的例外），也不構成 lookahead（兩者都早於 target 窗口）。

## 3. 結果 (WHAT)

| Family | n_IS | n_OOS | IS signal t | fixed-split DM \|t\| | **Clark-West t** | Harvey pass (>3.0) |
|---|---|---|---|---|---|---|
| **F10 隔夜 VIX gap** | 6505 | 1861 | -4.523 | 0.659 | **-0.428** | ❌ |

**F10 的 nested Clark-West 遠低於 Harvey 3.0（\|CW t\|=0.428）→ VIX sufficiency 對這個 family
robust。** 與 k1116e（F2/F4）、k1116g（F1/F8/F11）、k1116c（F12/F13）、論文整體 thesis 一致——
**這是主表 |t| 最大（1.12）的家族在最有力檢定下依然不顯著**，是這篇論文 null claim 目前收集到的
最強一組交叉驗證證據之一，而不是「順便補完」的邊角料。

CW 係數為負（-0.428），代表在這個切分上，加入 sig_F10 之後 augmented 模型的樣本外 MSPE 反而
（些微）比 baseline 差，方向與「無增量價值」一致，不是接近顯著卻被 HAC 壓下去的邊界情況。

IS signal t=-4.52 顯示**樣本內**這個訊號其實有相當強的統計顯著性（符號為負：隔夜 VIX gap 越大，
未來 22 日已實現波動反而越低——可能是均值回歸或 overreaction-then-reversal 的訊號），但這股
in-sample 訊號在樣本外**完全沒有轉化成任何預測增量**（CW |t|=0.428）——這正是本論文其他 12 個
family 反覆出現的模式（in-sample 顯著 ≠ out-of-sample 有用），也是這篇論文要傳達的核心方法論
訊息之一。

## 4. 對論文的意義

- Table 3/4 的 daily-family nested-CW 欄現已覆蓋 **6/8** nested-CW-applicable daily families
  （F2/F4 from k1116e + F1/F8/F11 from k1116g + **F10 from K1815**），全部 FAIL Harvey。
  剩 F3/F9 待各自的資料處置決策（F3 已於裁決文件判定可立即跑，另案；F9 建議撤回）。
- **main_v5.tex:519 的敘述需要更新**：目前寫「三個 family 延後到 data-provisioning follow-up」，
  F10 已完成，不再屬於延後清單。裁決文件建議的替代句式（僅 F3 延後、F9 方法論排除）現在可以
  進一步簡化成「F3 待處置決策、F9 方法論排除、F10 已完成且 null」。
- 這是一個**加分結果**：論文最擔心翻盤的候選家族（主表 |t| 最大且資訊集最特殊）在更嚴格的檢定下
  依然是 null，central claim 因此變強而不是變弱。

## 5. 檔案

- `K1815.py` — harness（獨立下載 unlagged VIX OHLC + F10 訊號建構 + nested OLS + DM + CW）
- `K1815_results.json` — F10 完整統計
- `data/spy_ohlc_raw.csv`、`data/vix_ohlc_raw_unlagged.csv` — 本實驗獨立下載並快取的原始資料
  （unlagged，刻意不與其他 family 共用的 lagged VIX pin 混用）
- `reproduce_spec.json` / `reproduce_commit.json` — run-time 產出的復現規格（entrypoint / inputs /
  seeds 的 sha256）

## 6. 待辦

- **Codex primary-path 審查**：額度用盡至 2026-08-08 12:01，在此之前無法產生
  `review_verdict.json`、無法用 canonical knowledge writer 建立 knowledge 條目、無法 merge。
  已排入本部門審查佇列（與 k1741/k1749/k1095_v3/K1750/K1739/k892/k1583 同一批）。
- 結果已回報論文部（`dept_send.py publications --kind reply`），供其接續 v9 round，把 F10 從
  「延後清單」移到「已完成」，並依上面 §4 的建議更新 `main_v5.tex:519` 附近的敘述與 Table 3/4。
- 論文部若需要把這份結果納入正式 Table，數字來源一律是 `K1815_results.json`，不要從這份 README
  或本回報轉抄。
