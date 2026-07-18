# K1731 — GEVReg-MIDAS-SSVS arm B：報酬尾部區間預測

**Model**: opus / xhigh (per model_router)
**Task**: `assign_c55b0d66`（老闆 Telegram msg 946/947 指派，P1）
**Parent**: arm A = K1730（同引擎，被解釋變數換成報酬）
**Worktree（你唯一可寫的地方）**: `.claude/worktrees/dispatch-slot-1-bd00f90a-k1731`
**Result artifact（必須產出）**: `experiments/k1731/k1731_gevreg_midas_ssvs_returns_results.json`

---

## 0. 先讀：你已經繼承了 arm A 的完整引擎

本 worktree 從 arm A 的 branch 開出，`experiments/k1730/` 已經有可運作的全套代碼：

| 檔案 | 內容 | arm B 該怎麼用 |
|---|---|---|
| `k1730_data.py` | ALFRED first-release PIT 月頻總經（CPI/NFP/IP/UNRATE + FRED VIX/DGS10/DTB3）、SPY 日資料、Parkinson RV proxy、lookahead 檢查 | **直接 import 重用**，只換 target 建構 |
| `k1730_models.py` | GEV likelihood MLE（logpdf 誤差 4.5e-13、Gumbel 極限收斂已驗證）、MIDAS(12 lags) beta 權重、SSVS 貝氏變數挑選 | **直接 import 重用**，likelihood 不要重寫 |
| `k1730_scoring.py` | Kupiec UC / Christoffersen ind+cc / DQ、ES bootstrap、pinball | **直接 import 重用**，必要時補 arm B 專屬指標 |
| `k1730_gevreg_midas_ssvs.py` | 主流程：in-sample 估計 + rolling OOS（annual refit）+ 出圖出表 | 當作 arm B 主流程的樣板 |

**規則**：`experiments/k1730/` 的檔案 **一律不要修改**（arm A 有自己的 production 重跑在跑）。
需要調整就在 `experiments/k1731/` 裡 import + 子類化 / wrapper。若發現 arm A 引擎有 bug，
**不要就地改** — 寫進 results.json 的 `armA_engine_issues` 欄位並在最終摘要點名。

## 1. 研究設計（老闆已定的邊界，不要自行擴張）

**目標**：月頻總經變數 → 日/週頻**報酬**的**尾部區間預測**。

⚠️ **不要做報酬點預測**。報酬點預測的 OOS R² 天生接近 0，做出來必然是 null 且無資訊。
本 arm 要預測的是**報酬分配的尾部分位數 / 下檔風險**（左尾 VaR / ES）。

具體：沿用 arm A 的 weekly block 結構，target 改為**每週報酬的區塊極小值**（block minima；
等價於對 $-r_t$ 取 block maxima，直接餵進既有 GEV maxima likelihood，不要另外寫 minima 版）。
同時輸出對應的週頻 VaR / ES 預測。

**Baselines（必須全跑，且用同樣的 lag 與同樣的 OOS 切法）**：
1. 歷史分位數（rolling empirical quantile）
2. GARCH-t VaR（可重用 repo 既有 GARCH 代碼）
3. Quantile HAR（分位數迴歸版 HAR）

**評分**：
- VaR backtest：Kupiec UC + Christoffersen ind/cc + **DQ test**（Engle-Manganelli）
- Pinball loss（多個 tau）+ Expected Shortfall（bootstrap p-value，固定 seed）
- 模型間比較用 **DM test**（含 HAC）
- 經濟意義：**避險 / 部位規模口徑**（HE、VaR-based sizing、utility）—
  ⚠️ **不要比 Sharpe**（見 memory `feedback_hedging_vs_trading`）

## 2. 方法論硬規則（違反任一條 = 結果作廢）

1. **in-sample 估計 vs rolling OOS 嚴格分離**，annual refit，OOS 起點與 arm A 對齊（2008-01）
2. **lag 明確**：`signal.shift(1)`，禁 same-day；總經用 first-release vintage 的 availability date，
   禁用修正後數列。arm A 的 lookahead 檢查（`macro_released_before_origin` / `origin_before_block_start` /
   `blocks_non_overlapping`）**必須原樣跑過且 0 violations**，結果寫進 results.json
3. **固定 seed = 42**，所有 bootstrap / MCMC 都要可重現
4. 樣本 ≥500 blocks、跨 3 期間驗證、OOS 必含至少一次空頭（2008 / 2020 都在窗內）
5. **結果好得不像真的 = 90% 有 bug**。報酬尾部若出現「顯著優於所有 baseline」，
   先回頭查 lookahead 與 target 建構，再下結論
6. **Null result 如實報告**。報酬可預測性弱是既有共識，做出 null 是有效結論，
   不要為了「有結果」去挑 tau 或挑期間。禁止 p-hacking、禁止只報好看的那組

## 3. 交付物（三件套）

在 `experiments/k1731/` 產出：
1. **代碼**：`k1731_*.py`（資料 / 模型 wrapper / 主流程 / 評分）
2. **結果**：`k1731_gevreg_midas_ssvs_returns_results.json` — 必含
   `experiment_id`、`seed`、`config`、`data_sources`、`target`（明確寫死定義）、
   `lookahead_checks`、`sample`、`refits`、`oos.by_model`（每個 baseline 都要有）、
   `dm_tests`、`economic_value`、`limitations`、`armA_engine_issues`
3. **圖表**：至少 3 張（rolling 覆蓋率 / SSVS PIP / 預測區間 vs 實現報酬）

**先跑 `--quick` 確認 pipeline 全通**，再跑全量。若全量在 timeout 內跑不完，
把 quick 結果與 partial production log 都留下，並在 results.json 標明 `quick_mode`。

## 4. 完工前自檢

- [ ] lookahead 三項檢查 0 violations，數字寫進 JSON
- [ ] 3 個 baseline 全跑完，與主模型用**同樣 lag、同樣 OOS 切法**
- [ ] 每個宣稱都能在 JSON 裡找到對應數字（禁止摘要出現 JSON 沒有的數）
- [ ] 覆蓋率不足 / 檢定被拒 → 如實寫，不要粉飾
- [ ] `experiments/k1730/` 未被修改（`git status` 確認）
- [ ] commit 到本 worktree branch（`wt/dispatch-slot-1-bd00f90a-k1731`）

**不要寫 `knowledge.json`** — 那是主線程的事（K1259 教訓）。
你的最終回覆 = 給下一班 fire 的收件摘要：關鍵數字、通過/未通過的檢定、
與 arm A 的對照、你認為誠實的結論（含 null）、以及還沒做完的部分。
