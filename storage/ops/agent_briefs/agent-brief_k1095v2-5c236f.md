# K1095-v2 — 用 known-in-advance schedule 重做台股事件切換 VT（修 lookahead + T+1 mapping）

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Pool task**: `k1095_v2_known_in_advance_schedule` (P3, starvation 保底席)
**Worktree（你唯一可寫的地方）**: `.claude/worktrees/dispatch-slot-1-f5a22a5f-k1095v2`
**Result artifact（成功後置條件）**: `experiments/k1095_v2/k1095_v2_results.json`

## 0. 你在哪裡工作

所有寫入都在上述 worktree 內（你的 cwd 就是它）。**不要**寫 canonical checkout、不要碰
`storage/knowledge.json`（K1259 教訓：agent 不得寫 knowledge），不要 push。commit 到本
worktree 的分支即可，合併由後續 followup 班走正式 `scripts/merge_worktree.sh`。

## 1. 背景與這次要修的兩個缺陷

K1095（2026-04-12，`experiments/k1095/`）做的是台股事件切換 VT：

- A = 純 8.63/VIX、B = 純 A4f-VT（target σ=15% ann）、C = 事件窗內用 B、窗外用 A
- 事件 = 0050.TW top-10 成分股財報公告日，窗 [T-5,+5]（另有 ±3 / ±10 敏感度）
- 原結論：**switching 破壞 A4f-VT 優勢**（C 沒贏 A 也沒贏 B）

Codex review（`mile_c11a2ced`）判 FAIL，兩個具體缺陷（見 `experiments/k1095/README.md`
末段 disclaimer，先讀完）：

1. **Lookahead**：事件窗用 `財報公告日.txt` 的**事後 actual announce date** 建構。
   pre-event branch（T-5..T-1）因此含 ex-post 資訊 → 只能算 descriptive regime
   partition，不能宣稱 tradable。
2. **Mapping 錯誤**：台股財報是**盤後揭露**，announce date 應映到 **T+1** 交易日，
   原版映到 T+0。

## 2. 任務（四步，順序不可跳）

### Step 1 — 找 known-in-advance schedule source（這步是成敗關鍵，先做完再往下）

需要的是**當時就已公布的預告/排程日**，不是事後實際公告日。候選：

- FinMind `TaiwanStockFinancialStatementsDate` / earnings announcement schedule 類 dataset
- TWSE 公開資訊觀測站的財報預告 / 申報期限公告
- 法規推導的 deadline（台股財報申報有法定期限；deadline 本身是 ex-ante known 的）

**硬性誠實要求**：若你**找不到**真正 ex-ante 的 schedule source，**不准**用 actual date
加個位移假裝成 schedule，也不准編數字。此時正確產出是：把已查過的來源、各自為什麼不合格
寫進 `k1095_v2_results.json`（`status: "blocked_no_exante_source"` + 證據），README 記錄，
然後**停在這裡**回報。這是合格交付，不是失敗。

若找到 source：把抓取腳本存成 `experiments/k1095_v2/fetch_schedule.py`，原始資料落地到
`experiments/k1095_v2/data/`，並在 README 記錄「這份 schedule 在哪一天就已可得」的證據
（這是整個 v2 的立論基礎，要能被審核者查證）。

外部資料源用法先讀 `.claude/skills/external-data-sources/SKILL.md`。

### Step 2 — 修 mapping
announce/schedule date → **第一個 ≥ date 的交易日的下一個交易日（T+1）**。把 T+0 與 T+1
兩種 mapping 都跑，作為 robustness 對照（讓「mapping 改變結論嗎」可被觀察，而不是只給一個數）。

### Step 3 — 重跑 K1095 流程
沿用 `experiments/k1095/k1095.py` 的策略定義與評估框架（**讀懂再改**，不要重寫一套）：
Sharpe / MDD / **HAC (Newey-West) t-test** / event-window decomposition（event vs non-event
日的貢獻拆解）/ 窗寬敏感度 ±3, ±5, ±10。seed 固定 42。

### Step 4 — 裁決
- v2 結論若**仍是** switch 輸給純 A4f → 這次是 ex-ante 資訊集下的結果，可升格為
  **tradable claim**（原本只能 descriptive）。
- 若結論**翻轉** → 明確寫出翻轉是由 (a) schedule source 還是 (b) T+1 mapping 造成的
  （這正是跑兩種 mapping 的用途），維持 descriptive 結論並說明為何不足以 tradable。

## 3. 交付物

1. `experiments/k1095_v2/k1095_v2_results.json` — **必須存在**，含 status、每策略每窗寬的
   Sharpe/MDD/t 統計、兩種 mapping 的結果、data provenance（source URL/dataset 名 + 抓取日）
2. `experiments/k1095_v2/k1095_v2.py`（+ `fetch_schedule.py`）
3. `experiments/k1095_v2/README.md` — 比照 K1095 README 格式：Motivation / Method /
   Results（表）/ 與 v1 逐項對比 / Limitations / 明確 verdict（PASS / NULL / blocked）
4. 圖：equity curves + event/non-event decomposition（PNG）

## 4. 硬規

- **禁止假數字**。每個進報告的數字都要能由 JSON + 腳本重跑得出。研究誠實 > 結論好看。
- NULL result 是合格結果。不要為了「有發現」去調參湊顯著（p-hacking = 直接判 FAIL）。
- 不要碰 `storage/knowledge.json`、不要 push、不要 `--no-verify`。
- 跑得動的最小可信版本優先於漂亮但沒跑完的版本；時間不夠時砍敏感度分析，不砍主結果與 HAC 檢定。
- 完成時 final text 回報：verdict、關鍵數字（含 v1 vs v2 對照）、data provenance 一句話、
  你**沒做到**的部分（誠實列出）。
