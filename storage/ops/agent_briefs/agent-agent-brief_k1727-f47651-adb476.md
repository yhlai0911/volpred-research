# K1727 — 波動率目標（VT）的跨資產有效性再驗證：股/credit 有效、債/匯/商品近乎無效？

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: K1727（experiment；worktree topology）
**Worktree cwd**: `.claude/worktrees/dispatch-slot-4-6ba995a0-k1727`（你只在此 worktree 寫檔，禁碰 main checkout / feed.json / supabase）

## 開工前必讀
- `.claude/rules/experiments.md`（實驗工作流硬規則：README + code + results.json + lookahead + success criteria + Codex 審）
- `.claude/skills/agent-result-verification/SKILL.md`（回報數字前的自驗 checklist — K1016 教訓：禁報不符 JSON 的數字）
- 參考既有 VT 實作範式（**只讀不抄結論**，資產池與 spec 以本 brief 為準）：`experiments/multi_asset_hybrid_vt/`、`experiments/k1573_vt_3spec_audit/`

## 研究問題（來源：JPM "The Impact of Volatility Targeting" + Man Group 2025）
波動率目標（依前期已實現波動反向縮放曝險）長期被認為能改善風險調整後報酬。文獻主張：**這個增益主要來自「風險性資產」的波動叢聚（vol clustering）+ 波動-報酬負相關**；對債券、匯率、商品，波動叢聚較弱或 vol-報酬關係不同，VT 的 Sharpe 增益與左尾改善可能**近乎為零**。本實驗在**同一套 VT 機制**下跨資產 head-to-head 再驗證此不對稱。

## 資產池（yfinance，各自獨立跑 VT vs 固定 notional）
- **股（risk asset）**：SPY、QQQ
- **credit ETF**：HYG（高收益）、LQD（投資級）
- **債**：TLT（長天期美債）、IEF（7-10Y）
- **匯（USD）**：UUP（美元指數 ETF）；若 UUP 樣本太短，補 FXE 或以 DXY proxy 說明
- **商品**：DBC（廣義商品）、GLD（黃金）、USO 或 DBO（原油；注意 USO roll 污染，若用需在 README 註記限制）

樣本：各資產自身 yfinance 最長可得日資料（至 2026-07-24 為止的可得日）；每資產記 n、起訖日、資料抓取時戳寫進 results.json 的 provenance 區。缺資料的資產照實標「資料不足，排除」，不要硬湊。

## 方法（每資產一致）
1. 日 log return `r_t`。
2. 已實現波動估計：用**過去** window（例如 20 日 或 EWMA λ=0.94）算 `sigma_hat_t`，**只用到 t 為止的資訊**。
3. VT 曝險權重：`w_t = target_vol / sigma_hat_{t}`，並 `w_t = w_t.shift(1)`（**訊號落後一日，無前視**）；設 leverage cap（例如 [0, 3]）並在 README 說明。`target_vol` 對每資產用其**全期 realized vol** 或固定年化（例如 10%）——擇一，全資產一致，README 寫明。
4. VT 策略報酬：`r_vt_t = w_{t-1} * r_t`。基準：固定 notional（`w=1`）buy-and-hold 同資產。
5. **seed=42**；所有隨機性（若有 bootstrap）固定種子。

## 評估指標（每資產）
- **Sharpe 增益**：Sharpe(VT) − Sharpe(fixed)，年化；附兩者原始 Sharpe。
- **左尾極端頻率**：VT vs fixed 的 1% / 5% 日報酬 VaR 突破頻率、最差 1% 平均（ES proxy）、最大回撤（MDD）。
- **顯著性**：VT vs fixed 的報酬序列做 Sharpe 差異檢定（可用 block bootstrap 或 Ledoit-Wolf HAC t）；報 t/p，用 **Harvey (2016) |t|>3.0** 作嚴格門檻判定顯著與否（配對比較，需 pair specifier）。
- **跨資產彙總表**：一列一資產，欄位 = {資產類別, n, Sharpe_fixed, Sharpe_vt, ΔSharpe, t, 顯著?, ΔMDD, 1%VaR 突破 fixed/vt}。

## 成功判準（先寫進 README，再跑）
- **支持假說**：股 + credit 的 ΔSharpe 為正且達（或接近）|t|>3；債/匯/商品 ΔSharpe ≈ 0 或不顯著 → 確認 VT 有效性的跨資產不對稱。
- **NULL / 反例**：若債/匯/商品也顯著受益，或股/credit 也不顯著 → 照實記為 null / 反直覺，**禁止為了配合假說調參數**。
- 明確寫下「本設計不能識別的因果邊界」（例如無法分離 vol clustering 強度 vs vol-報酬相關 vs 尾部形態何者主導）。

## 交付物（全部寫在 worktree 內）
- `experiments/k1727/README.md`：motivation + 資產池 + method + lookahead policy（signal.shift(1)）+ success criteria + 結果表 + 誠實界線。數字**機械引自** results.json，不要手打。
- `experiments/k1727/K1727.py`：可重跑；`signal.shift(1)`、`seed=42`；抓 yfinance 真資料（不可造假、不可用 stub 數字）。
- `experiments/k1727/K1727_results.json`：byte-traceable，含每資產 metrics + provenance（各資產 n / 起訖 / 抓取時戳）+ summary.verdict（SUPPORT / NULL / MIXED）+ summary.causal_boundary。
- 圖（選配但建議）：跨資產 ΔSharpe 長條圖、VT vs fixed 累積淨值範例圖。

## 硬規則
- **真資料真數字**：yfinance 實抓；任何 yfinance 抓取失敗照實記，不要 fabricate。研究誠實 > 一切。
- **無前視**：曝險權重必 `.shift(1)`；README 明述 lookahead policy。
- 跑完照 `agent-result-verification` skill 自驗：results.json 的數字 == README 的數字 == 你回報的數字，三者一致才算完成。
- **Codex review 為主路徑**：完成後在 worktree 內請 Codex 審（`codex exec` 或審查 skill），把 verdict 存 `experiments/k1727/review_verdict.json`。若 Codex quota blocked，fallback 到 subagent 審或 audit，並在 verdict 註明 fallback 原因。
- knowledge.json **由主線程後續 fire 寫**（agent 禁寫 knowledge，K1259）；你只產出 experiment 交付物 + review verdict。

## 回傳（agent final output = 機器可讀摘要，非人類訊息）
回傳一段 JSON-ish 摘要：各資產 ΔSharpe + t + 顯著性、summary.verdict、results.json 相對路徑、review verdict 路徑、以及任何資料不足被排除的資產清單。
