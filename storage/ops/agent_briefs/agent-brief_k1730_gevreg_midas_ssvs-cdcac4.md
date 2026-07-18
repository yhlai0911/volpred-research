# K1730 — GEVReg-MIDAS-SSVS arm A：波動率**區間預測**（in-sample 估計 + rolling OOS）

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Task id**: `assign_8082bc79`（老闆指派 P1，來源 Telegram msg 946/947, 2026-07-18）
**Worktree（唯一可寫路徑）**: `.claude/worktrees/dispatch-slot-1-558d7893-k1730`
**K id**: `k1730`（已確認未被占用；experiments/k1730/ 全新建）

---

## 0. 開工前必讀（不要跳過）

1. `AGENTS.md`（尤其「Worktree / Agent 規則」§140-152、研究誠實條款）
2. `docs/error_log.md` — 找 lookahead / 前視偏誤 / MLE 不收斂 的既有教訓
3. 參考實作（**重用，不要從零寫**）：
   - MIDAS 加權與 MLE 骨架：`experiments/k526/k526_garch_midas.py`
   - SSVS 貝氏變數挑選：`experiments/k818/k818_ssvs_return_prediction.py`
4. 原論文：IEEE Access 2026, GEVReg-MIDAS-SSVS（IEEE 11603339 / arXiv）。**若無法取得全文就以本 brief 的規格為準，不要臆造論文細節去當引用。**

## 1. 研究問題

月頻總經變數 → 日頻 RV 的**區間預測**（interval / tail forecast），**非點預測**。
三塊組裝：**MIDAS**（混頻加權，重用 k526）+ **SSVS**（貝氏變數挑選，重用 k818）+ **GEV regression likelihood**（scipy.stats.genextreme + 自寫 MLE — **本次唯一真正新做的部分**）。

## 2. 資料

- 標的：SPY（日頻，yfinance）→ 由日內或日資料構造 RV proxy（若無日內資料，用既有 repo 的 RV 建構方式；不要臨時發明新 proxy 而不說明）。
- 月頻總經（FRED）：CPI、NFP（payrolls）、VIX 月均、TERM spread（10Y-3M），可再加 1-2 個但要說明理由。
- **樣本 ≥500 個 OOS 預測點；期間跨 ≥3 個 regime，OOS 必含至少一次空頭**（2008 或 2020 或 2022）。見 `feedback_research_rigor` / `feedback_long_sample_period`。
- FRED 系列**必須用 vintage-aware 或至少 release-lag 保守處理**：月頻變數在月底之後才可觀測，一律 `signal.shift(1)` 以上的 lag，**禁 same-day**。

## 3. 方法規格

- **GEV regression likelihood**：對 block maxima（或 exceedance）建 GEV(μ, σ, ξ)，令 μ（必要時 log σ）為 MIDAS-加權總經變數的線性函數。用 scipy 的 genextreme pdf/logpdf 組 negative log-likelihood，`scipy.optimize.minimize`（L-BFGS-B / Nelder-Mead 交叉驗證），**multistart ≥ 20 組隨機初值 + 固定 seed**，回報收斂診斷（收斂率、best/worst LL、Hessian 是否可逆）。
- **MIDAS 權重**：Beta 或 exponential Almon，K lag 明說；權重函數重用 k526。
- **SSVS**：Gibbs sampler 對 MIDAS 係數做 spike-and-slab；回報 posterior inclusion probability 表。burn-in / draws / seed 全部記錄。
- **in-sample 估計 vs rolling OOS 預測必須分離**：expanding 或 rolling window 重估，每個 OOS 點只用 t 以前資訊。**寫完程式先自行做一次 lookahead 自檢**（把未來資料打亂，若績效不變才合理）。

## 4. Baseline（同樣的 lag、同樣的 OOS 窗）

1. GARCH-MIDAS 的分位數版本（k526 延伸）
2. HAR-RV 分位數迴歸版本
3. 歷史經驗分位數（naive）

## 5. 評分

- 區間覆蓋率：**Kupiec UC + Christoffersen CC**（回報 LR 統計量與 p 值）
- QRMSE / pinball loss、ES（expected shortfall）誤差
- **Diebold-Mariano test** 對每組 baseline（雙尾，回報統計量 + p 值）
- 分期間（≥3 段）分別報，不要只報全期平均

## 6. 產出（experiments/k1730/ 三件套）

1. `k1730_gevreg_midas_ssvs.py` — 完整可重跑腳本（固定 seed）
2. `k1730_gevreg_midas_ssvs_results.json` — **本 job 的 result artifact**，必含：每模型每期間的 coverage / Kupiec / Christoffersen / pinball / ES / DM vs 各 baseline、SSVS PIP 表、MLE 收斂診斷、資料期間與樣本數、seed
3. `README.md` — 方法、資料、結果表、**誠實結論**（含 null / 不收斂 / 覆蓋率失準都要如實寫）

另外產 ≥2 張圖（覆蓋率時序、PIP bar、預測區間 vs 實現 RV 疊圖擇二）存 `experiments/k1730/`。

## 7. 紀律硬規（違反即作廢）

- **禁止修改共享狀態**：`storage/reports/feed.json`、`storage/memory/knowledge.json`、`storage/memory/thinking_journal.json`、`storage/memory/experiment_experiences.json`、Supabase / mirror。**knowledge.json 由主線程在 Codex review 後寫**（K1259 教訓）。
- 只寫 `experiments/k1730/` 內檔案（腳本可放同目錄）。
- **禁止假數字 / 禁止把「應該會是」寫成結果**。跑不動就報跑不動。研究誠實 > 一切。
- 「結果好得不像真的 = 90% 有 bug」— 若 GEV 版大勝 baseline，先回頭查 lookahead 與 baseline 是否被弱化。
- 完成後**在 worktree 內 commit**（`git add experiments/k1730 && git commit`），訊息寫 `k1730: GEVReg-MIDAS-SSVS arm A ...`。**不要 push、不要碰 main、不要 merge**（主線程用 `scripts/merge_worktree.sh` 合併）。
- **禁止** `git worktree remove --force`。

## 8. 完成判準

`experiments/k1730/k1730_gevreg_midas_ssvs_results.json` 存在、內容為真實跑出的數字、README 結論與 JSON 一致、worktree 已 commit。
