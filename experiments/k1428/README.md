# K1428 — Financial Innovation 2025 review：realized volatility forecasting 綜述

## 動機

`research_program.md` backlog 明列「Financial Innovation 2025 review — realized volatility forecasting 綜述」。
這不是要再寫一篇空泛 survey，而是回答一個更窄、對 VolPred 有用的問題：

1. 2025 時點的 RV forecasting 文獻，到底支持先做哪一類 follow-up？
2. 哪些結果是可操作的研究方向，哪些只是 model-zoo 噪音？
3. 我們近期 K1301 / K1421 / K1422 已經踩到的公平比較與 formal-test 問題，在文獻裡是不是仍然是主問題？

這份 K1428 的目標是把 backlog 題目 materialize 成可執行的研究分流，而不是直接宣稱某個模型已經「贏」。

## 與既有 K 的關聯

- **K1301**：HAR-RS vs HAR-RV 在 TAIFEX TX1 上是 NULL，提醒「decomposition tweak」若沒有 formal significance，不能包裝成 improvement。
- **K1421 / K1422**：HAR-Quantile commodity line 暴露比較公平性與 bootstrap 寫法風險；K1428 把這件事上升為 literature-level filter。
- **research_program backlog**：已有 HAR-RV / Realized GARCH / high-frequency model 方向，但受限於 5-min 歷史深度。K1428 的工作是決定「先做哪條最值」。

## 文獻來源（primary sources）

1. **Leushuis & Petkov (2025)**, *Financial Innovation*  
   `Advances in forecasting realized volatility: a review of methodologies`  
   DOI: `10.1186/s40854-025-00809-5`

2. **Gunnarsson et al. (2024)**, *International Review of Financial Analysis*  
   `Prediction of realized volatility and implied volatility indices using AI and machine learning: A review`  
   DOI: `10.1016/j.irfa.2024.103221`

3. **Bucci (2018)**, *Journal of the Korean Statistical Society*  
   `Forecasting realized volatility: A review`  
   DOI: `10.1016/j.jkss.2018.08.002`

4. **Branco, Rubesam & Zevallos (2024)**, *Journal of Empirical Finance*  
   `Forecasting realized volatility: Does anything beat linear models?`  
   DOI: `10.1016/j.jempfin.2024.101524`

5. **Skintzi & Fameliti (2025)**, *Journal of Asset Management*  
   `Combining realized volatility estimators based on economic performance`  
   DOI: `10.1057/s41260-025-00415-1`

6. **Akgun & Gulay (2025)**, *Computational Economics*  
   `Dynamics in Realized Volatility Forecasting: Evaluating GARCH Models and Deep Learning Algorithms Across Parameter Variations`  
   DOI: `10.1007/s10614-024-10694-2`

## 方法

這是 **literature-review experiment**，不是市場資料實證。

- 只納入 **primary sources**
- 優先使用 publisher-hosted 頁面 / DOI / open-access full text
- 只收「明確以 realized volatility forecasting 為主題」或「直接 benchmark RV forecasting models」的文獻
- 不把 blog、二手摘要、citation aggregator 當證據

輸出不是 prose essay，而是結構化 JSON：

- 文獻清單
- 文獻共識與分歧
- 對 VolPred 的方法論風險提醒
- 下一步最值得做的 4 個 follow-up

## 核心發現

### 1. 2025 文獻**不支持**「DL 已普遍打敗 HAR / 線性 RV baseline」

最穩健的讀法不是「transformer 已經贏」，而是：

- 某些資料集、某些 horizon、某些 realized-measure 定義下，非線性模型可以贏
- 但 **一般性、統計上穩健** 的 dominance 仍未建立
- 近年的 benchmark paper 反而持續提醒：強線性 baseline 很難完全被打穿

對 VolPred 的意義：**先鎖公平 baseline，再談模型升級**。

### 2. 目前最大問題仍是 benchmark discipline，不是 model novelty

2025 review 最有價值的不是「列出更多模型」，而是暴露文獻仍存在：

- target mismatch
- loss-function 不一致
- formal significance 報告不足
- benchmark 選擇偏鬆

這和 K1421 / K1422 的教訓高度一致。換句話說，VolPred 近期踩到的坑不是個案，而是整個文獻帶仍常見的弱點。

### 3. economic value 比純 accuracy ranking 更值得追

`Does anything beat linear models?` 與 `Combining realized volatility estimators based on economic performance`
放在一起看，訊號很清楚：

- 小幅 average-loss 改善不等於更好的投資 / 風管決策
- 若要做下一個有發文價值的 experiment，**economic-value-aware combination** 比單純再跑一輪 MSE horse race 更有新意

### 4. realized-measure 選擇是第一級設計變數

不是只有「模型 class」重要；`5-min RV`、`MedRV`、range-based proxy 可能直接改變排序。
這意味著 VolPred 一旦有足夠 5-min depth，第一個高價值實驗不該是 transformer zoo，而是：

- 固定模型類
- 系統比較 realized-measure 定義
- 看 ranking 是否翻轉

## 結論

K1428 的結論不是「某個新模型可以直接上」；恰好相反。

**文獻真正支持的下一步順序**是：

1. **先做共享 target 的 HAR-RV / Realized GARCH / HEAVY baseline battle**
2. **再做 realized-measure ablation**
3. **再做 economic-value / combination**
4. **最後才考慮 restrained ML / transformer extension**

也就是說，最合理的主線不是「先追最炫模型」，而是「先把 high-frequency baseline 做到公平、可檢定、可解釋」。

## 成功標準達成情況

- `README.md`：完成
- `k1428.py`：完成（deterministic literature-review serializer）
- `k1428_results.json`：完成
- primary sources ≥ 3：完成（6 篇）
- 有明確 follow-up queue：完成（4 條）

## 限制

1. 這是 structured literature review，不是 market-data experiment。
2. 未對每篇文獻逐表重算或 code-audit；本實驗只抽取作者公開報告的主結果與方法論訊號。
3. 因本地 shell 無網路，來源驗證依賴本次 session 的 browser / web evidence，不在 `k1428.py` 內動態抓取。

## 推薦後續實驗

1. `har_rv_vs_realized_garch_vs_heavy_on_shared_rv_target`
2. `realized_measure_ablation_5min_rv_vs_medrv_vs_range_based_proxy`
3. `economic_value_of_rv_forecast_combinations`
4. `ml_or_transformer_extension_after_baseline_lock`

## 復現

```bash
uv run python experiments/k1428/k1428.py
```

## 三件套

- `README.md`
- `k1428.py`
- `k1428_results.json`
