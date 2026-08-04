---
name: owner-first
description: >
  在動手加任何 gate、watchdog、rotation、detector、清理程序或修復腳本之前，先定位它的
  enforcement owner。用於「這個問題需要一個機制」「某個機制沒在動」「要改 src/volpred/ops、
  supabase/migrations、dispatch_supervisor 等 Codex 熱區」；也用於其他 skill 需要判定
  某個 concern 是否已有 owner 時。
---

# Owner First

這個 repo 被 Codex 大量優化過。實務後果：**你想到的機制，多半已經存在，而且是靜默的。**

靜默不是壞掉。fail-open 元件在乾淨路徑上本來就無輸出，於是「沒在跑」與「跑了但沒事」
**觀測上同形**。你若用「我沒看到它」當作「它不存在」，就會蓋出第二套 —— 這正是
`CLAUDE.md` anti-stacking 要擋的事，代價是兩個 owner 對同一個 concern 各自漂移。

先指出 owner 的 `檔案:行號`，再決定要不要動手。

## 步驟

### 1. 找 owner

先問 code graph，再用 grep 落到原始碼確認：

```bash
uv run python scripts/graphify_integration.py query "<誰負責 X>" --budget 700
graphify explain "<node_id>" --graph graphify-out/graph.json   # 列 caller/callee
```

graph 是 map 不是 proof（`AGENTS.md` §graphify）；命中後一定要讀 `source_location` 的實際程式碼。

**完成條件**：你能寫出 `路徑:行號`；或已同時用 graphify 與 grep 兩種方式查過且都無命中，
才可宣告「真的沒有 owner」。

### 2. 讀它為什麼不動

owner 找到後，先讀它的拒絕路徑，不要先讀它的成功路徑。多數靜默來自刻意的 fail-closed
設計，而拒絕的**理由層級**決定你接下來能做什麼：

- **provenance 型拒絕**（「這不是我蓋的章，我無法證明持有者已死」）—— 它沒說沒問題，
  它說它沒有立場。缺的是一條不依賴自有標記的判定。
- **liveness 型拒絕**（「我實測過，條件仍在」）—— 它有立場，聽它的。

**完成條件**：你能用一句話說出它涵蓋什麼、拒絕什麼、拒絕屬於上述哪一型。

### 3. 判三態，每態都要 live 證據

| 狀態 | 證據長什麼樣 | 該做什麼 |
|---|---|---|
| **完好，只是你沒找到** | 跑它、讀它的 log、看它最近一次生效的紀錄 | 收手。不要動任何程式碼 |
| **正確拒絕** | 它回傳的 reason 字串 + 你對該 reason 的複驗 | 補它缺的那條判定，或依授權止血並記錄 |
| **涵蓋不足** | 算出涵蓋率：owner 認得幾種、實際存在幾種 | 補涵蓋，不要另建第二個 owner |

「涵蓋不足」最容易被誤判成「不存在」。算涵蓋率是唯一分辨方式 —— 註冊表有一筆、
現場有二十二筆，看起來就像完全沒做。

**完成條件**：三選一，且你手上有上表對應欄位的實際輸出，不是推論。

### 4. 動手前確認路徑歸屬

改 `src/volpred/ops/**`、`supabase/migrations/**`、`scripts/dispatch_supervisor/**`、
`tests/**` 之前：

```bash
git log -5 --oneline -- <path> && git status --porcelain -- <path>
```

最近 5 筆有 `[codex]` → 熱區，先協調。三區分工與協調方式的唯一 owner 是
`docs/agents/ownership.md`，本 skill 不重述。

**完成條件**：你能說出這條路徑屬哪一區，以及你採取的協調動作。

## 收手也是交付

判定為「完好」而收手，是這個 skill 的**成功結果**，不是空手而回。把查到的 owner
`路徑:行號` 與你跑過的驗證寫進回報 —— 下一個人就不必再查一次。

判定為「涵蓋不足」但該路徑屬 Codex 熱區時，交付物是**附完整重現指令的工單**，
不是你順手改一半。

## 這個 skill 存在的理由

同一個 session 內連續發生：提議加 log rotation（`scripts/cron_log_rotate.sh` 已存在、
每日 04:40 在跑、當天還輪替過檔案）；提議安裝 graphify（整合已完整，含
`scripts/graphify_integration.py`、config、hook、兩張註冊圖）；遇到孤兒 index.lock 時
差點自己刪（`reclaim_leaked_index_lock` 已存在，回 `not_ours` 是 provenance 型拒絕）。

四次裡三次是「機制在、我沒找到」。唯一沒踩的那次，是先查了才動手。
