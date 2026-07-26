# K1715 — Score-driven (GAS/DCS) 動態參數模型直接估 VaR + ES

**Model**: opus / xhigh (per model_router)
**Task id**: K1715 (pool, P3, experiment)
**Worktree (你唯一可寫的 cwd)**: `.claude/worktrees/k1715-204d556b`（branch `worktree-k1715-204d556b`）
**來源**: research_program.md line 509（Score-driven GAS/DCS）。文獻錨點：J. Econometrics 2026 Catania 等；IJASEIT 2025 GAS-1F。
**定位**: 平台目前無 score-driven（GAS/DCS）類模型 —— 本實驗補這條方法論空白。

## 研究問題（一句話）
Score-driven（Generalized Autoregressive Score / Dynamic Conditional Score）動態參數波動模型，能否**直接聯合估計 VaR 與 ES** 並在標準風險回測（Kupiec / Christoffersen / e-backtest）下優於或不劣於平台既有 GARCH 家族？

## 方法
- **模型**：scipy MLE 估 Creal-Koopman-Lucas / Harvey 型 score-driven 波動遞迴（觀測驅動的 time-varying scale/shape）。以 Student-t 或 GAS-1F 這類 fat-tail 分佈驅動 score，直接推出條件分位（VaR）與尾部條件期望（ES）。
- **對照組（必要）**：至少一個平台既有 baseline（如 GARCH(1,1)-t 或 GJR-t）在同資料、同 lookahead policy 下的 VaR/ES + 同一套回測，作為 head-to-head。**只報自己模型的數字不算完成** —— 必須有比較框架。
- **回測**：Kupiec unconditional coverage、Christoffersen conditional coverage/independence、以及 ES 的 e-backtest（如 Nolde-Ziegel / exceedance-residual）。report exception 數、p 值、每個分位（如 1% / 2.5% / 5%）。
- **資產**：用平台既有可得日資料（如 SPY 或既有標的），期間與樣本數透明；out-of-sample 或 rolling 評估。

## 方法論硬要求（.claude/rules/experiments.md + AGENTS.md 研究誠實）
1. **Lookahead policy 事前寫死在 README + code**：`signal from t-1, return at t`，明確 `signal.shift(1)`；VaR/ES 是用 t-1 為止資訊對 t 日的預測，禁 in-sample 未來洩漏。
2. **seed=42** 固定所有隨機（MLE multistart 起點、任何 bootstrap/抽樣）。
3. **MLE 穩健性**：multistart 或合理初值 + 收斂診斷；不收斂/邊界解要如實報告，不得挑好看的 run。
4. **樣本量與期間透明**；rolling/OOS 視窗定義寫死。
5. **觀察先於計算**：先看資料/波動聚集、baseline exception 分佈，再估 score-driven。
6. **NULL 完全可接受**：若 score-driven 未勝過 baseline，如實報告即完成，不得 reactive 調參重跑。

## 實驗三件套（缺一不可，寫在 worktree 內）
- `experiments/K1715/README.md`：motivation + method + **lookahead policy** + 資料來源/期間/樣本 + success criteria + baseline 對照說明。
- `experiments/K1715/K1715.py`：可重跑，`signal.shift(1)`、`seed=42`、score-driven MLE + baseline + 三套回測寫死。
- `experiments/K1715/K1715_results.json`：byte-traceable 輸出（估計參數、log-lik、各分位 VaR/ES、exception 數、Kupiec/Christoffersen/e-backtest 統計量與 p 值、baseline 對照）。
- 圖表（波動路徑、VaR 穿越、QQ/PIT）如有則附。

## Success criteria
- CONDITIONAL_PASS 下限：三件套齊全、lookahead 乾淨、score-driven MLE 收斂並產出 VaR/ES、至少一個 baseline head-to-head、三套回測至少完成 Kupiec+Christoffersen 且 ES 有一個正式 e-backtest、結論強度不超過證據（含 NULL 亦算完成）。
- 只有達 CONDITIONAL_PASS 以上才寫 knowledge entry（禁 agent 直接寫 knowledge.json）。

## 收尾（followup fire 會做）
產出 `experiments/K1715/K1715_results.json` 後結束。Codex primary-path review（額度被擋則 fallback subagent/audit）與 worktree merge 由後續 fire 的 PHASE A 依 followup-brief 處理。
