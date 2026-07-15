# K1692 — 原油波動率 spillover 到股市（vol-of-vol 傳導）

**Model**: opus / xhigh (per model_router)
**Task type**: experiment（worktree topology；本 job 由 compute worker 執行）
**Task id**: K1692（starvation-released，aged >72h）

## 研究問題
CL=F / USO 的**波動率衝擊**是否傳導到 SPY 與能源股（XLE/XOP）的波動率？聚焦 **vol-of-vol 傳導**，明確區別於一般「油價漲跌 → 股市報酬」分析。核心：是油價的**波動**（不是油價水準）在動盪期外溢到股市波動。

## 開工前必讀（研究誠實，最高優先）
1. `AGENTS.md` §研究誠實原則（13 條，尤其 #6 觀察先於計算、#7 正式檢定、#11 lookahead、#12 固定 seed）。
2. `.claude/rules/experiments.md` §Methodology 硬規則（lag、DM-HAC、scale artifact）。
3. `docs/error_log.md` Class G（Lookahead / DM-HAC / MDD）。
4. knowledge.json 檢索既有 spillover / oil / VIX 相關 K，避免重工，並在 README 引用。

## 資料
- yfinance：`CL=F`（WTI 期貨）、`USO`（原油 ETF）、`SPY`、`XLE`（能源類股）、`XOP`（油氣探勘）。
- 期間：以資料可得最長樣本，OOS 切最後 3 年。標明來源、期間、樣本數（三件套要求）。
- 波動率量：日報酬的 realized vol（rolling 或 EWMA）或 GARCH 條件波動；vol-of-vol = 波動序列自身的波動。

## 方法（必含正式檢定，不可只看圖）
1. **觀察先於計算**：先做 vol 序列描述統計、相關結構、事件窗（如 2020 油價負值、2022 能源危機）。
2. **傳導方向**：Granger causality / VAR on vol series，或 vol spillover index（Diebold-Yilmaz）。**明確 lag**：來源 vol 在 t-1，目標 vol 在 t（`shift(1)` 或等效），嚴禁 same-day 訊號×same-day 目標。
3. **vol-of-vol 專屬**：檢定油價「波動的波動」對股市 vol 的邊際貢獻，控制油價報酬本身（避免把報酬效果誤當波動效果）。
4. **顯著性**：HAC 標準誤（DM-HAC lag 不可只用 h-1；先量 loss differential 的 acf 再決定 lag）；bootstrap 固定 seed。
5. **Null 如實報告**：若無顯著傳導，如實寫 NULL，不美化。

## 交付（三件套 + 圖表，缺一不可）
- `experiments/K1692/README.md`（研究設計、資料來源/期間/樣本數、方法、結論、局限）
- `experiments/K1692/K1692.py`（可重跑、固定 seed、含 lag 註記）
- `experiments/K1692/K1692_results.json`（所有統計量、檢定 p 值、樣本數）
- 圖表（vol 傳導 / event window / spillover index）
- 過 `uv run python scripts/experiment_gates.py run --path experiments/K1692`（PASS 才算完成）

## 誠實邊界
結論強度不得超過證據；區分實證/模擬；承認局限。若發現曝險或尺度假象（參 K1695 教訓），如實揭露不掩蓋。
