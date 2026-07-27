# Agent Brief — K1811 (pool task K1722): 極端天氣事件對保險/公用 ETF 波動的 event study + dose-response

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Experiment id**: `K1811`（已由 kid_reserve 正式預留，owner=hourly-slot-3-047f093b…；**不要**用 `k1722` 當實驗資料夾名 — 那只是 task-pool id，1722 未在 registry，用會被 kid-registry merge gate 擋）
**Pool task**: `K1722`（source_task_id）
**Worktree (你的唯一可寫工作區)**: `.claude/worktrees/dispatch-slot-3-047f093b-k1811`
**產出目錄**: `experiments/k1811/`

---

## 0. 開工前必讀（依 .claude/rules/experiments.md）
1. `docs/error_log.md` — 尤其 lookahead / seed / event-study 相關教訓。
2. `.claude/rules/experiments.md` — 完整實驗完整性 gate。
3. `.claude/rules/worktree.md` — worktree 產出/共享狀態禁忌與合併流程。
4. Knowledge search：跑 `uv run python -m volpred.memory.system search "climate weather event study volatility ETF"`（或等效）確認**沒有**既有 K 覆蓋此設計；若已有高度重疊 K，在 README 標明差異或回報 already-covered。
5. `.claude/skills/external-data-sources/SKILL.md` — 確認 NOAA / yfinance 取用方式與陷阱。

## 1. Motivation（文獻定錨）
- 來源：**PLOS One 2025** + **Journal of Investment & Financial Management (JIFM) 2025** climate-vol 文獻；2025 共識 = **physical risk > transition risk** 對資產波動的即時衝擊。
- 假說：極端天氣**物理事件**（颶風登陸、極端高溫 heat wave）發生後，**保險 ETF（KIE、KBWP）** 與 **公用事業 ETF（XLU）** 的 realized volatility 出現顯著正向 abnormal response，且呈 **dose-response**（事件強度越大 → abnormal vol 越大）。
- 對照組：`SPY`（大盤，理應無 / 較弱的 event-specific vol response），用來確認 abnormal vol 是 sector-specific 而非全市場。
- Under-explored angle：把 NOAA 物理事件強度當連續 dose 變數對 sector ETF vol 做 dose-response，公開文獻少見。

## 2. Data（全部免費、byte-traceable，來源與抓取碼寫進 README）
**事件（NOAA）**：
- **颶風**：NOAA / NHC 或 NOAA Storm Events Database — 取 **美國登陸颶風**的登陸日期 + **Saffir-Simpson 分級（category 1–5）作為 dose**。時間範圍建議 2010-01 至今（ETF 資料可得區間）。
- **極端高溫**：NOAA Storm Events Database 的 `Excessive Heat` / `Heat` event type — 取事件起始日 + 嚴重度代理（如 event 數 / 死傷 / 持續天數）作為 dose。
- ⚠️ 事件清單要能重現：記錄下載 URL / API query / 檔案 md5。若 NOAA API 抓取受阻，改用 NHC 官方 season summary（登陸日 + category 表）並在 README 註明 provenance。**禁止手捏事件日期或強度**。
- 為避免重疊污染，同 ETF 上 event window 相互重疊的事件要標記並在 robustness 中處理（或只取非重疊子集）。

**ETF 波動**：
- `yfinance` 日 OHLC：`KIE`（SPDR S&P Insurance）、`KBWP`（Invesco KBW Property & Casualty Insurance）、`XLU`（Utilities Select Sector）、對照 `SPY`。
- 日頻 vol proxy：以 **Garman–Klass 或 Parkinson range-based RV**（用 OHLC）或 `|log return|` / `return^2`；擇一為主、另一為 robustness。明確定義寫進 README。

## 3. Method（classic event study + dose-response）
1. **Estimation window**：事件日前 [-60, -11]（交易日）估計每支 ETF 的 baseline vol 水準與離散度（可用 log-vol 均值/標準差，或對 market vol 迴歸取殘差 vol 以控大盤）。
2. **Event window**：[-5, +10]。計算每日 **abnormal volatility (AV)** = 事件窗 vol 相對 estimation baseline 的標準化偏離（例如 (vol_t − μ_est)/σ_est，或 log-vol 殘差）。
3. **CAAV**：跨事件平均 abnormal vol、以及累積 CAAV over [0,+5]、[0,+10]。對 KIE/KBWP/XLU 分別算，SPY 作對照。
4. **統計檢定**：對 CAAV 是否顯著 > 0 做 **cross-sectional t-test** 且加 **bootstrap / permutation**（把事件日隨機 relocate 到非事件日，建 null 分布；`seed=42`）。回報雙邊 p 與效果大小。
5. **Dose-response**：把每事件的 cumulative abnormal vol 對 **dose（颶風 category；heat 嚴重度）** 迴歸（含 sector fixed effect / 或分 sector 跑），回報斜率、CI、R²。這是核心 novel 結果。

## 4. Lookahead / 誠實性（最高優先）
- 這是 **descriptive event study**，不是交易訊號；但只要出現任何「用事件預測次日 vol」的 framing，特徵必須 `signal.shift(1)`（事件指標 lag 一日），且 baseline 用相同 lag。
- Estimation window 嚴格在事件日**之前**；event window 不得洩漏進 estimation。
- 任何 forward-label（未來 H 日 RV）都要滿足 `target_end < forecast_origin`。
- **所有隨機程序 `seed=42`**（bootstrap / permutation / 任何 shuffle）。
- 程式碼裡要有**明確可 grep 的 lag/shift** 與 seed 設定。

## 5. Success criteria（CONDITIONAL_PASS 門檻，NULL 結果誠實可接受）
- (a) ≥ 15 個可重現的物理事件（颶風 + 熱浪合計），每個帶 dose。
- (b) event-study AV 以正確 estimation/event 窗算出，KIE/KBWP/XLU + SPY 對照齊全。
- (c) 至少一個顯著性檢定（t + bootstrap/permutation）對 CAAV > 0。
- (d) dose-response 迴歸係數 + CI 出爐。
- **NULL 結果（無顯著 abnormal vol / dose 無斜率）完全可接受**，照實寫。**結果好得不像真的 = 90% 有 bug**，回頭查 lookahead。

## 6. Deliverables（experiments/k1811/）
- `README.md`：motivation + 文獻 + method + **data provenance（URL/query/md5）** + lookahead policy + success criteria + 結果摘要 + 限制。
- `k1811.py`：可重跑、`seed=42`、明確 `signal.shift(1)`（如有預測 framing）、byte-traceable 輸出、印出關鍵數字。
- `k1811_results.json`：所有數字（CAAV、p、dose 係數、事件清單摘要、n_events），路徑相對 worktree = `experiments/k1811/k1811_results.json`（= result-artifact）。
- 圖表選配：event-window CAAV 曲線、dose-response 散點。

## 7. 收工（你只做到產出 + 自驗；不要自己寫 knowledge.json）
- 跑完自驗數字（agent-result-verification checklist）：JSON 內數字與 README/stdout 一致，無 QLIKE-style 反向誤報。
- **不要**自己寫 `storage/memory/knowledge.json`（K1259 禁令）。knowledge 由後續 fire 在 Codex review CONDITIONAL_PASS 後由主線程寫。
- 在 worktree 內 commit 你的產出（README + py + json + 圖）。**只碰 experiments/k1811/**，不要動 feed.json / knowledge.json / 其他實驗。
- followup（收件時）：主線程會做 Codex code review → 驗數字 → merge worktree → 寫 knowledge。

## 8. Mission sanity check
本實驗生成新 research direction（climate/physical-risk vol），grounded in research_program.md line 576 + 2025 文獻，且全免費資料可跑。誠實 > 一切；NULL 結果照實寫，禁止假數字、禁止 lookahead 美化。
