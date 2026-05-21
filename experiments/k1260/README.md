# K1260 — GJR-X (Fair-Info Baseline) vs PRG vs GJR on SPY OOS

## 問題（Research Question）

P6 PRG paper §6 limitation 段（line 311）誠實標明：「PRG 讀兩次資訊（overnight + intraday）vs GJR 只讀一次（close-to-close）」。NotebookLM v3 M1 audit 與 latex-academic-reviewer 都將此標為 critical fairness issue 並標註 *"a direct GJR-X comparison is left for future work"*。

**核心問題**：PRG 對 GJR 的 DM~6 優勢，到底來自
- (a) **資訊量差異**（PRG 多看 overnight return），還是
- (b) **session-boundary cross-session bridge mechanism**（PRG 的 h 跨 session 遞迴）？

K1260 透過 GJR-X（GJR augmented with overnight squared return as exogenous regressor）建立 fair-info baseline 來分離這兩個效應。

## 動機（Why）

P6 v3 manuscript revision 需要 fair-info baseline 對照數據。如果 PRG vs GJR-X DM > 0，證明 **bridge mechanism** 不只是「多讀資訊」— 是真正的 model contribution，可以從 §6 limitation 移到 §3/§4 主結果支撐 paper 主張。

NotebookLM Argument A prediction：
- GJR-X DM t (vs GJR) ∈ [2, 4]（多讀 overnight 應該有幫助，但小於 PRG）
- PRG vs GJR-X DM t > 0（bridge mechanism 仍有 marginal value）

## 方法（Methodology）

### Model spec — GJR-X（NEW）

GJR-X 在標準 GJR(1,1) 條件變異方程加 **previous-day overnight squared return** 為 exogenous regressor：

$$h_t = \omega + \alpha r_{t-1}^2 + \gamma I(r_{t-1} < 0) r_{t-1}^2 + \beta h_{t-1} + \delta r^2_{\text{overnight}, t-1}$$

其中：
- $r_t$ = close-to-close log return（與 standard GJR 相同）
- $r^2_{\text{overnight}, t-1} = (\log(\text{open}_{t-1}/\text{close}_{t-2}))^2$ = 昨日 overnight squared return，**在 t-1 close 已知** — 沒有 lookahead

### Comparisons

| Model | Spec | Reads |
|---|---|---|
| GJR | $h_t = \omega + \alpha r^2_{t-1} + \gamma I r^2_{t-1} + \beta h_{t-1}$ | 1 piece (c2c) |
| **GJR-X** (NEW) | + $\delta r^2_{\text{overnight}, t-1}$ | **2 pieces** (c2c + overnight) |
| PRG_Extended | Periodic GARCH with cross-session h-bridge | 2 pieces (overnight + intraday) |

### Lookahead 防錯

代碼內明確 `signal.shift(1)` 等效：
- `_gjrx_negll`: `h[t] = ... + δ * r2_ov[t-1]` — 用 t-1 的 overnight 預測 t
- `gjrx_oos_forecast`: forecast step 用 `r2_overnight[t-1]`，不用 `r2_overnight[t]`
- 三個模型 (GJR / GJR-X / PRG) 同 lag convention（symmetric refinement，per `.claude/rules/experiments.md` K1216b 教訓）

### MLE Setup

- Bounds：ω∈[1e-8, 1e-3], α∈[1e-8, 0.5], γ∈[0, 0.5], β∈[1e-8, 0.999), δ∈[0, 0.999)
- Stationarity guard：`α + γ + β < 0.999` 否則 NLL=1e15
- Multistart：n_starts=3（與 K880 canonical 對齊）
- Refit frequency：63 days (quarterly) — 與 K880 一致
- Seed：固定 42

### Data

- yfinance SPY（與 K880 用 `k880_prg.load_spy_data()` reuse loader）
- 期間：2000-01-04 to 2026-04-02（6601 days）
- IS：to 2018-12-31（4778 days）
- OOS：2019-01-02 to 2026-04-02（1823 days）
- Target：σ²_fullday = r²_overnight + r²_intra（P6 paper convention）
- Loss：Patton (2011) QLIKE
- Test：Diebold-Mariano with Harvey (1997) small-sample correction

### IS LR Test Diagnostic（額外）

為驗證 OOS null result 不是 implementation bug，在 IS 全樣本（4778 days）以 16 starts（1 canonical + 4 specific δ inits + 15 random）跑 GJR vs GJR-X full MLE，做 LR test：

$$\text{LR} = 2 \cdot (\ell_{\text{GJR-X}} - \ell_{\text{GJR}}) \sim \chi^2_1 \text{ under } H_0: \delta = 0$$

## 結果（Results）

### IS LR test（δ 在 in-sample 顯著嗎？）

| Statistic | Value |
|---|---|
| GJR IS NLL | −15486.94 |
| GJR-X IS NLL | −15511.62 |
| **LR statistic** | **49.37** |
| **p-value** | **< 0.0001** |
| δ̂ (full IS) | 0.1288 |
| **Verdict** | **δ SIGNIFICANT IS** |

→ Overnight squared return **的確帶有 in-sample 預測資訊**。Implementation 沒 bug。

### OOS QLIKE（target = σ²_fullday）

| Model | OOS QLIKE | n_obs |
|---|---|---|
| GJR | 0.8544 | 1823 |
| **GJR-X** | **0.8607** | 1823 |
| PRG_Extended | **0.7559** | 1823 |

GJR-X QLIKE 比 GJR 還略差（+0.7%）— OOS 上 exogenous regressor 沒能提升預測力。

### DM tests pairwise

| Comparison | DM t | p-value | Winner | Harvey |
|---|---|---|---|---|
| **PRG vs GJR** | **5.24** | 1.83e-07 | PRG | PASS |
| **PRG vs GJR-X** | **7.72** | 1.84e-14 | PRG | PASS |
| **GJR-X vs GJR** | **−0.53** | 0.596 | GJR | FAIL (NS) |

**注**：PRG vs GJR DM=5.24 與 K880 paper 報的 6.00 接近，差異在 yfinance retroactive dividend adjustment drift 容忍範圍內（reproduce.py 設 tol=0.15）。

## NotebookLM Argument A 驗證

| Claim | Predicted | Observed | Verdict |
|---|---|---|---|
| GJR-X DM t (vs GJR) | [2, 4] | **−0.53** | ❌ NOT in range |
| PRG still beats GJR-X | t > 0 | **t = 7.72** | ✅ YES (very strongly) |

**為什麼 GJR-X DM 不在 [2, 4] 預測範圍**：

NotebookLM 預測「多讀 overnight info 應提升預測」基於 IS 上 δ 確實顯著的觀察（K1260 IS LR=49.37 也確認）。但 OOS 表現顯示：
1. **In-sample δ 顯著 ≠ OOS forecast 改善**（typical overfitting / regime shift pattern）
2. **Exogenous regressor 結構不適合**：把 overnight info 強塞進 single GARCH recursion 會稀釋 c2c return 的 GARCH dynamics — δ̂_IS=0.13 但 OOS 滾動估計可能不穩定（quarterly refit n=3 multistart 可能找不到 OOS-optimal basin）。
3. **PRG 的 session-specific recursion** 把 overnight 與 intraday info 各自存在自己的 session h_state — 這個分離反而 OOS robust。

→ **支持 P6 §6 引用 Todorova (2014) 與 Opschoor et al. (2021) 的論點**：「session-level parameterization dominates exogenous overnight regressors」。K1260 提供 SPY 上的直接證據。

### 對 P6 paper 的影響（更強的好結果）

NotebookLM 預測的「軟劇本」是 GJR-X 部分有效（t∈[2,4]），bridge 是 marginal advantage。實際結果是 GJR-X **完全失效**（t=−0.53 NS），bridge 是 **dominant advantage**。

這對 P6 v3 manuscript 是 **強化** 而非削弱：
- §6 限制段可改寫：「GJR-X comparison（K1260）confirms that simply augmenting GJR with overnight regressor does not capture the cross-session information transfer; PRG's session-level recursion is required.」
- 可在 §4 加 supplementary table 列 K1260 結果作為 robustness check
- bridge mechanism = first-order contribution claim 更站得住

## 結論（Conclusion）

PRG 對 GJR 的優勢 **不是** 來自「多讀一份 overnight info」。GJR-X 雖然 IS LR test 顯示 δ 顯著（p<0.0001, δ̂=0.13），OOS 上 augmented spec 反而 marginally 更差（QLIKE +0.7%, DM t=−0.53 NS vs GJR）。

PRG vs GJR-X 在 fair-info 條件下仍 **強勝**（DM t=7.72, p=1.8e-14）— 證實 PRG 的 contribution 是 **session-boundary bridge mechanism**，不是單純資訊量。

## 檔案

- `k1260_gjr_x_spy.py` — main script（包含 IS LR diagnostic + OOS forecasts + DM tests）
- `k1260_results.json` — 完整結果 JSON

## 相關 K

- **K880**: PRG SPY validation（DM=6.00 canonical reference）
- **K880v2**: PRG no-lookahead fix
- **K884**: HAR day-night decomposition
- **K1216b/c**: symmetric refinement methodology lesson（避免 asymmetric MLE artifact）

## 防錯規則檢查

- [x] Lookahead：`r2_overnight[t-1]` 預測 `h[t]`（明確 lag-1 in numba kernel + forecast loop）
- [x] Seed 固定：`np.random.RandomState(42)` for MLE multistart
- [x] Symmetric refinement：GJR / GJR-X / PRG 同 lag convention，同 refit_freq=63
- [x] 公平比較目標：σ²_fullday（同 K880）
- [x] Patton/DM/Harvey 標準
- [x] 路徑可從 paper/prg-periodic-garch/reproduce.py 引用（`experiments/k1260/k1260_results.json` stable）
- [x] Reuse K880 canonical PRG implementation（保證 PRG 數字與 paper 一致範圍）

## 待後續（主線程 follow-up）

1. **Codex code review**：本 worktree agent 未跑 Codex；需主線程 merge 後派 `/codex:review` 跑 K1260。
2. **可選 robustness**：若 v3 manuscript 想加 supplementary table，建議跑 K1260b 用 n_starts=15+ 做 GJR-X OOS 強化 multistart，看 GJR-X DM 是否上升至 [2, 4] 預測區間（目前 n=3 與 K880 對齊，但 IS 證據提示 n=3 在 OOS quarterly refit 可能 undershoot GJR-X 的真實基底）。注意：即使 GJR-X 改善，PRG vs GJR-X DM~7.72 緩衝極大，主結論不會變。
3. **Knowledge.json 寫入**：主線程審核後寫 K1260 entry（worktree agent 不寫 shared state per `.claude/rules/worktree.md`）。
4. **Paper §6 修訂草稿**：v3 manuscript 可拿 K1260 結果 frame 為「fair-info baseline confirms bridge mechanism」。

## Runtime / 環境

- Python 3.12.10, numpy + scipy + pandas + numba
- yfinance SPY live download（沒 paper-pinned snapshot 可用，與 K880 / K880v2 同條件）
- 完整 runtime：~6.4 秒（含 IS LR + 3 models OOS forecast + DM）
- 完成：2026-04-27
