# 實驗 brief — K1812（pool task K1726）：BAB 異象條件於前期已實現波動

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Experiment id**: `k1812`（pool task 標籤為 `K1726`；registry 以 append-only 取號，正號 = k1812）
**Worktree（唯一可寫工作區）**: `.claude/worktrees/dispatch-slot-2-dc4437b8-k1812`
**產物合約**: `experiments/k1812/k1812_results.json`（runner 只驗存在，絕不寫入）
**來源**: research_program.md line 586 — 「BAB 報酬條件於前期已實現波動的『beta anomaly 波動之謎』」（來源：JFE 2025 *The volatility puzzle of the beta anomaly*）

---

## 0. 開工前（硬性順序）

1. 先讀 `docs/error_log.md`（§C worktree、lookahead 教訓）與 `.claude/rules/experiments.md`。
2. 查 `storage/memory/knowledge.json` 是否已有 BAB / betting-against-beta / beta anomaly / vol-regime 相似 K；若有，本實驗必須在 README 明確區分「新增了什麼」。
3. 讀 `.claude/rules/worktree.md`（共享狀態禁忌）。**只在本 worktree 內寫檔**，禁碰 main、禁寫 `storage/memory/*`、禁寫 `feed.json`。knowledge 由後續收件 fire 主線程寫（K1259 gate）。

## 1. 研究問題

Frazzini–Pedersen (2014) 的 betting-against-beta（BAB）：低 beta 股票的風險調整報酬高於 CAPM 預測。JFE 2025 論文主張 BAB 報酬**條件於前期已實現波動**。本實驗要**獨立以 yfinance 美股大樣本月度資料重做 BAB，檢定「低 vol 月之後的 BAB Sharpe 是否較高」**。

## 2. 資料

- **市場**：`^GSPC` 或 `SPY`（日報酬 → 月度已實現波動 RV_market）。
- **橫斷面 universe**：美股大樣本（liquid large-cap）。務實作法：取一組固定、流動性高的美股 ticker 清單（數十至上百檔，跨產業），下載日收盤 → 日報酬。**清單寫死在腳本內並在 README 列出**，可重現。
- **無風險利率**：FRED `DGS3MO` 或 `DTB3`（換算日/月）。
- **樣本期**：yfinance 可得最長共同期（建議 ~2005 至今，或視資料完整度）。README 標明實際期間、樣本數、每檔起訖。

### 資料誠實 caveat（必寫入 README + results.json）
- **Survivorship bias**：yfinance 只給現存 ticker → universe 天生倖存者偏誤。這是**已知且不可完全消除**的限制，必須誠實揭露，不可宣稱「無偏誤大樣本」。結論強度須相應下修。
- 缺值/停牌處理方式要寫明（如：要求每月最少交易日數才計 beta）。

## 3. 方法

1. **Beta 估計**：每月月底，用**過去** L 個月（如 12M）的日報酬對市場日報酬回歸估 beta_i,t。只用 ≤ 月底資料。
2. **BAB 組合建構**（Frazzini–Pedersen）：依 beta 排序，低 beta 半邊做多、高 beta 半邊做空；各腿以 1/beta 加權後**槓桿/去槓桿到 beta=1**，使組合市場中性。逐月 rebalance。
3. **月度 BAB 報酬**：以 t 月底形成的組合、持有到 t+1 月 → BAB_{t+1}。
4. **Vol regime 分類**：以 t 月的 RV_market 分高/低（median split 為主，另報 tercile robustness）。regime 來自 **t 月**，預測 **t+1 月** 的 BAB 報酬。
5. **檢定**：
   - 全期 BAB mean、Sharpe、Newey-West（HAC，lag 依 Andrews 或固定合理值）t-stat。
   - 低 vol 月後 vs 高 vol 月後的 BAB 條件 Sharpe / mean；**兩子樣本 Sharpe 差異檢定**（如 Ledoit-Wolf 2008 或 bootstrap，固定 seed=42）。
   - 迴歸：BAB_{t+1} ~ α + β·1{low_vol_t}（+ 控制項），報 HAC t。
   - Null result 如實報告。

## 4. Lookahead 政策（最高風險，代碼必含）

- Beta 只用 ≤ t 月底資料估計。
- Regime 訊號來自 t 月 RV，對應 t+1 月報酬 → 代碼裡以 `signal.shift(1)` 或等效 lag 明確實現：`bab_ret[t+1]` 對 `regime[t]`。
- 禁 same-month 訊號乘 same-month 報酬。
- baseline（無條件 BAB）與條件版**用同一套 lag 與同一組合建構**，公平比較。
- 固定 `seed=42`（bootstrap / 任何抽樣）。

## 5. 成功判準

- **baseline gate**：無條件 BAB 是否複製出正的風險調整報酬（方向與量級與文獻大致相容即可，不要求完全一致）。
- **主結論**：低 vol 月後 BAB Sharpe 是否顯著較高 — 有正式檢定與 p 值；**NULL 也算完成**，如實報告方向、量級、顯著性、與 survivorship caveat 下的強度上限。
- 不可過度宣稱（AGENTS.md 研究誠實原則第 10 條）。

## 6. 交付物（實驗三件套 + 認證）

- `experiments/k1812/README.md`：motivation + 資料來源/期間/樣本數 + method + lookahead policy + survivorship caveat + success criteria + 結果摘要。
- `experiments/k1812/k1812.py`：可重現，含 `signal.shift(1)` 與 `seed=42`。
- `experiments/k1812/k1812_results.json`：byte-traceable 輸出（含所有統計量、期間、n、regime 切點、檢定 p 值）。
- `experiments/k1812/test_k1812.py`：關鍵不變式測試（lag 正確、組合市場中性、regime 對齊）。
- 圖表（RV regime 時序、條件 BAB 累積報酬、Sharpe by regime）。
- **收工自檢**：`uv run python scripts/experiment_gates.py run --path experiments/k1812`（全綠才算方法論過關）。
- **審查**：Codex primary path code review（quota 掛則 fallback `feature-dev:code-reviewer` subagent）；產出 `experiments/k1812/review_verdict.json`（由 gate 產生，勿手抄）。CONDITIONAL_PASS 以上才可寫 knowledge（但 knowledge 由收件 fire 寫，本 agent 不碰）。

## 7. 收工

- 所有檔案留在本 worktree、**不 merge、不寫 main**。合併由後續收件 fire 走 `merge_worktree.sh`（過 certify gate）。
- 在 worktree 內完成後即結束；`k1812_results.json` 必須存在且真實。
