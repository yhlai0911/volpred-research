# K1658 — FOMC statement shock vs press-conference shock 的分布反應拆解

**Model**: opus / xhigh (per model_router)
**Task id**: K1658 (pool, P3, experiment, starvation 保底席)
**Worktree (你唯一可寫的 cwd)**: `.claude/worktrees/k1658-rerun-204d556b`
**來源**: research_program.md line 1492；文獻錨點 Fed FEDS 2026-029 "Coarse Statements and Predictive Pressers"
**Re-enqueue 註記**: 前一 job (agent-brief_k1658_39b53bf6-b574ac) 因 cwd 未建 (worktree 被清) exit 2 秒退、完全沒跑；本次已建全新 registered worktree，內容 100% 沿用原 brief。

## 研究問題（一句話）
同一個 FOMC 決策日內，**聲明（statement, 14:00 ET）衝擊**與**記者會（press conference, 14:30 ET）衝擊**是兩個時間上可分離的資訊事件；檢定二者對利率資產次日波動的**不同**影響是否統計顯著、方向與量級是否不同。

**正交聲明**：本題與 line 1425「聲明/紀要語言複雜度」正交 —— 那是文本可讀性 level，本題是**同日兩階段 market-reaction 分解**，不是文本特徵。README 要明文交代此區隔，避免被審為重複。

## 資產與資料
- **反應資產**：TLT（20Y+ Treasury ETF）、IEF（7-10Y Treasury ETF）、ZN=F（10Y T-Note future）。次日 realized volatility（RV）、rate-vol skew proxy、tail jump 指標為 outcome。
- **shock 分離的事件窗**：用 SOFR / Treasury futures 的 intraday（或可得的最細頻）event window 分離：
  - statement shock 窗：14:00 ET 前後（例如 13:55→14:15 ET）
  - presser shock 窗：14:30 ET 前後（例如 14:25→15:30 ET，涵蓋 Q&A）
- FOMC 日曆與 statement/presser 時間戳：用 Fed 官方 FOMC calendar + press-conference transcript 時間戳。**若 intraday Treasury-futures tick 不可得**，退而用日內可得的最細頻代理；若兩段差分無法分離 → 必須在 README 明確標示資料限制並降級 claim，不可假裝分離成功。
- **資料可得性是本實驗第一風險**：開工先做資料診斷（外部來源見 skill `external-data-sources`：yfinance / FRED / TAIFEX 無 US intraday，需確認 SOFR/Treasury-futures intraday 取得路徑）。**若無法真正分離兩個 shock 窗，如實回報 NULL / infeasible，不得強行輸出**。

## 方法論硬要求（AGENTS.md 研究誠實原則 + experiments.md）
1. **Lookahead policy 事前寫死在 README + code**：`signal from t-1, return at t`；明確 `signal.shift(1)` 或等效 lag；禁 same-day 訊號乘 same-day 報酬。event-window shock 是 t 日資訊，outcome 是 **t+1 日** RV/skew/tail。
2. **seed=42** 固定所有隨機程序（bootstrap / 抽樣 / split）。
3. **正式統計檢定 + 多重比較修正**：statement vs presser 的差異要有正式檢定（如 event-study 迴歸係數差的 Wald/HAC-robust、或 DM-type）；跨 3 資產 × 3 outcome 的 multiple-testing family **事前寫死在 code**（Holm / BH），不可事後挑。
4. **樣本量與期間透明**：FOMC 事件數有限（每年 8 次），report N（事件數）、期間、每資產有效樣本。**小樣本要誠實**：若事件數不足以支撐 tail-jump 檢定，降級為 descriptive 並標示 power 不足。
5. **觀察先於計算**：先 descriptive（兩窗 shock 分佈、相關性、是否共線）再估計。statement 與 presser shock 若高度共線，分離無意義 → 如實報告。
6. **NULL 完全可接受且同樣有價值**：本實驗很可能得到「兩 shock 無顯著差異」或「資料無法分離」的 NULL。**如實報告即完成，不得因為是 NULL 就 reactive 調參重跑**。

## 實驗三件套（experiments.md，缺一不可，寫在 worktree 內）
- `experiments/K1658/README.md`：motivation + method + **lookahead policy** + 資料來源/期間/樣本數 + success criteria + 資料限制與 claim 降級條件。
- `experiments/K1658/K1658.py`：可重跑，`signal.shift(1)`、`seed=42`、multiple-testing family 寫死。
- `experiments/K1658/K1658_results.json`：byte-traceable 輸出（係數、檢定統計量、p 值、修正後 p、N、event list）。
- 圖表（事件窗 shock 分佈、次日 RV 反應對比）如有則附。

## Success criteria
- CONDITIONAL_PASS 下限：三件套齊全、lookahead 乾淨、至少一個正式檢定 + 多重比較修正完成、結論強度不超過證據（含 NULL / infeasible 亦算完成，只要方法論誠實）。
- 只有達 CONDITIONAL_PASS 以上才寫 knowledge entry（禁 agent 直接寫 knowledge.json）。

## 收尾（followup fire 會做，你只需產出 artifact）
產出 `experiments/K1658/K1658_results.json` 後結束。Codex primary-path review 與 worktree merge 由後續 fire 的 PHASE A 依 followup-brief 處理。
