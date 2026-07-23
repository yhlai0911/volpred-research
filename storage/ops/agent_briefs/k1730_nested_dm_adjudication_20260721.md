# K1730 nested-DM exposure — 宣稱盤點與撤回/修正裁決

**Task id**: `k1730_nested_dm_detector_exposure`（P2，starved 54h）
**Model**: opus / xhigh (per model_router, task_type=experiment)
**工作目錄（唯一可寫）**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`

## 背景（已由主線程查證，不必重查）

K1731 rev7 為 `audit_nested_dm_misuse.py` 補上 coefficient-mask nesting 的 AST channel 後，
`experiments/k1730/k1730_gevreg_midas_ssvs.py:142-143` 由 PASS 翻 FAIL
（`test_role=review_required`，已 frozen 進 `nested_dm_misuse_baseline.json` 為 exposed）。

根因與 K1731 arm B 相同：restricted model 是用 macro coefficient mask 歸零建立的，
兩條舊 AST channel 都看不到，`scan_file` 在 raw-DM classifier 之前就 `return None`。

影響面：arm A 的 **DM t=+2.13** 被 K1731 README 與 primary artifact 當作 cross-arm 論據引用。
若該統計量同樣不具漸近常態極限，K1730 自身的宣稱層也要比照 K1731 撤回或加註。

**主線程 2026-07-21 另查到的事實（請一併納入判斷，但不要接手處理）**：
`experiments/k1730/k1730_gevreg_midas_ssvs_results.json` 與 `k1730_quickmode_results.json`
**md5 完全相同**（`af6167c936d435c5c9ce13cddefea3db`）、`quick_mode: true`，
且 `run_production.log` 只跑到 2019 就中斷 —— 即目前掛著「production」名字的檔其實是 quick-mode 複本。
真正的 production run 已由主線程另行 enqueue（job `k1730_armA_production_run_20260721`）。
**所以：任何依賴數值大小的結論，都要標明「待 production 落地後複核」，不要在 quick-mode 數字上下定論。**
你這張 task 要處理的是**推論效度**（nested DM 有沒有漸近常態極限），那與 quick/production 無關，可以現在定案。

## 要做（三項，缺一不可）

1. **盤點**：列出 K1730 的 README / artifact / 圖表 / knowledge 條目中，
   **所有**依賴那個 raw DM 統計量（含 t=+2.13 及任何同來源的 DM p-value）的宣稱。
   每條給出：檔案路徑 + 行號/section + 原文 + 依賴方式。找不到 K1730 README 就明說沒有，
   並改盤點 `storage/ops/agent_briefs/agent-brief_k1730_*.md`、results JSON 的宣稱欄位、
   以及 K1731 README 中引用 arm A 的位置（引用位置只列出，**修改權在 K1731 owner，不要動**）。

2. **裁決撤回 vs 修正**：與 K1731 arm B 的處理保持一致。
   - 若能用有效的檢定（如 Giacomini–White、或對 nested 情形正確的 CW / 條件性檢定）取代 → 標為「可修正」並寫出具體做法。
   - 若不能 → **撤回**該宣稱並標為診斷性（diagnostic-only），禁止硬撐、禁止改寫成模糊語氣蒙混。
   - 裁決要有理由，引用 `audit_nested_dm_misuse.py` 的判準與 K1731 arm B 的先例。

3. **對外更正清單**：若 K1730 已有線上文章（feed）或論文引用該統計量，列出待更正清單
   （mile_id / 論文檔名 + 段落 + 建議改法）。查法：`grep -ri "k1730" storage/feed.json papers/ docs/` 之類。
   **只列清單，不要自行改線上內容**。

## 邊界（硬規則）

- **不得塞回 K1731 scope**：本 task 的 owner 是 K1730。K1731 README 的修改由
  `k1731_F3_armA_production_recheck` 收件時處理，你只列出引用位置。
- 只在上述 worktree 內寫檔，不碰 main checkout，不做任何 git push / force。
- 禁止捏造數字。所有數字要能從 artifact 追出來；追不到就寫「追不到」。
- 產出寫成 `experiments/k1730/K1730_NESTED_DM_ADJUDICATION.md`，並在檔內留一節「未決/待 production」。

## 成功判準

`experiments/k1730/K1730_NESTED_DM_ADJUDICATION.md` 存在且包含：
(a) 完整宣稱盤點表（含檔案+行號），(b) 每條的撤回/修正裁決與理由，
(c) 對外更正清單（或明確寫「無對外引用」），(d) 未決事項一節。
