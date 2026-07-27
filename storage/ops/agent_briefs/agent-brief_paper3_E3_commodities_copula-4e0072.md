# Paper 3 E3 — 商品臂 copula 正式重跑（Gold/Oil/Copper/Wheat × SPY/Bonds）

**Model**: claude-opus-4-8 / xhigh (per model_router)
**Source task**: `paper3_E3_commodities_copula_rerun_20260721`（P2 experiment）
**裁決來源**: `experiments/paper3_expansion_synthesis/README.md` §「E3 商品臂裁決」（assign_f3419501, 2026-07-21）
**你的工作目錄 (cwd)**: 這個 registered worktree。所有寫入只准在此 worktree 內，禁止碰 canonical checkout、禁止 push、禁止 knowledge.json（K1259：knowledge 只能主線程寫）。

---

## 為什麼要跑（不是為了湊三個資產類別）

Synthesis 最強的發現是：**唯一顯著的 scaling 關係，符號與預先登錄的 H3 相反，且不在 E1 複製，兩臂異質性顯著（Q=8.805, p=0.0030）**。只有兩個 equity 臂時，無法區分「H3 本身錯」與「E2 跨市場臂 arm-specific 結構」。第三個**非 equity** 資產類別在任一方向都有診斷價值：複製反號 → 真發現；不複製 → 坐實 arm-specific。放棄等於永久停在無法裁決狀態。

## 硬合約（違反任一條即不算完成）

1. **判準必須逐字沿用 E2**：`experiments/paper3_E2_cross_market_copula/paper3_E2.py:757-794` 的 `dm_test` + `hln_small_sample_factor`——HLN 小樣本修正 × `student_t.ppf(0.975, df)` 作為 critical value，`significant_harvey = abs(t_stat) > critical_value`。**嚴禁**重蹈 E1 `paper3_E1.py:717` 的硬編 `abs(t)>3.0`（已知在 E1 造成 108 檢定中 14 筆假陰性，見 `e1_rescored_unified_criterion.json`）。三臂共用同一把尺是本次裁決的前提。
2. **管線沿用 E2（跨市場臂）骨架**：直接以 `paper3_E2.py` 為模板改寫。保留 DCC-copula 估計、rolling refit、VaR/ES（compute_cf_rolling_var）、DM test 全部結構。只改 PAIRS / ASSET 註冊為商品臂。
3. **lag 慣例與 E1/E2 一致**：t-1 資訊集、rolling refit（比照 K1100b），baseline 同 lag。E2 的 WINDOW / REFIT_EVERY / OOS_START 直接沿用，除非商品資料歷史不足需調整——若調整必在 README 記錄理由。
4. **資料走既有 yfinance 路徑**（E2 的 `yf.download`, line ~1070）。商品臂建議 tickers（以流動性與 yfinance 歷史長度為準，最終選擇寫進 README，附各 series start date 與樣本數）：
   - Gold: `GC=F`（COMEX 黃金期貨）或 `GLD`（ETF, 2004-11 起，歷史穩定）
   - Oil: `CL=F`（WTI 原油期貨）或 `USO`
   - Copper: `HG=F`（COMEX 銅期貨）或 `CPER`
   - Wheat: `ZW=F`（CBOT 小麥期貨）或 `WEAT`
   - Bonds: `TLT`（20+yr Treasury ETF）
   - SPY: 沿用 E2
   Pairs = {Gold,Oil,Copper,Wheat} × {SPY, TLT/Bonds} = 8 對（若某商品 series 太短導致 OOS < 可用門檻，剔除該對並在 README 記錄）。
5. **交付三件套 + reproduce_spec**（放本 worktree）：
   - `experiments/paper3_E3_commodities_copula/README.md`
   - `experiments/paper3_E3_commodities_copula/paper3_E3.py`
   - `experiments/paper3_E3_commodities_copula/paper3_E3_results.json`
   - `experiments/paper3_E3_commodities_copula/reproduce_spec.json`
   - 圖表比照 E2（dm_vs_lambdaL、fz_heatmap、tail_dependence_by_pair）。
   完成後**必須跑** `uv run python scripts/check_experiment_artifacts.py`（或帶 experiment id 參數）確認三件套齊全且通過，把結果寫進 README。
6. **失敗必須把原因寫回**：若不收斂 / 資料抓不到 / 任何 blocker，**必須**在 `experiments/paper3_E3_commodities_copula/README.md` 明確記錄失敗原因 + 保留 partial 產物（部分 pair 的 results、log）。2026-05-29 那次失敗無原因、無 partial、7 週無人重試，正是本任務存在的原因，**不可重演**。禁止靜默放棄。

## 研究誠實（最高優先）

- 所有數字來自實際計算，禁止造假、禁止硬填。
- README 標明資料來源、期間、每 series 樣本數、OOS 窗口。
- 診斷解讀要誠實：E3 的角色是裁決「H3 反號是真發現 vs arm-specific」。**明確報告** scaling 關係（DM t vs tail dependence λ_L）在商品臂的符號，與 E2 反號是否複製。不要為了「好看」而 spin。
- Honesty note：若 E1/E2 的 OOS 管線本身有 lookahead，本 E3 沿用骨架也不會發現——如沿用請照實註記。

## 收尾（agent 職責到此，主線程後續收件）

- 跑完在 worktree commit（僅 commit 你新建的 `experiments/paper3_E3_commodities_copula/` 檔案；用 worktree 內的 git，不 push）。
- 在 README 末段寫一段「給收件主線程的驗證清單」：關鍵數字位置、check_experiment_artifacts 結果、待 Codex 審碼要點、待寫 knowledge 的結論摘要。
- `paper3_E3_results.json` 頂層放 aggregate（n_harvey_sig, pairs, criterion 描述），對齊 E2 的 results schema，便於逐項核實。

## 收件後主線程會做（followup，不是你的工作）

驗數字 → check_experiment_artifacts → Codex 審碼 → 通過才寫 knowledge → merge worktree → 解除「不得宣稱跨資產類別」邊界。
