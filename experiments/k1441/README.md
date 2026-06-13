# K1441: 新興市場 ex-台波動率景觀

- **K id**: K1441
- **Status**: completed
- **Created**: 2026-06-10
- **Task source**: `research_ex_eem_inda_ewz_ewy_eww_realized_vol_em_vol_fact`

## 問題

用 `EEM / INDA / EWZ / EWY / EWW` 五檔新興市場 ETF，
看 21 日 realized volatility 是否存在明顯的 **共同波動因子**，
以及在 **高相關 / 低相關 regime** 下，EM 波動率景觀如何變化。

## 動機

這題不是做單一市場預測，而是回答一個更基礎的結構問題：

1. 新興市場波動率是各自為政，還是其實有一個共同 factor？
2. 當 EM 波動率之間更同步時，是不是代表整體風險環境升級？

這對後續兩條線都有價值：

- **研究線**：若共同 factor 很強，跨 EM 建模不能假設各市場獨立
- **實務線**：若高相關 regime 同時伴隨高 basket RV，分散效果會在壓力期明顯下降

## 與既有 K 的差異

- **K1439**：看 USD regime 對跨資產 RV 的條件化差異
- **K1440**：看 yield-curve regime 對 SPY forward RV 的條件化差異
- **K1441**：改成 **EM ETF 內部** 的共同波動因子與相關性狀態

## 文獻前置

本題先對齊 3 類文獻脈絡：

1. **PCA / factor extraction**：
   Shlens (2014) 的 PCA tutorial 提供方法論基礎，適合把高度相關的波動率向量壓縮成少數共同因子。
2. **市場間波動共動 / spillover**：
   Otranto and Scaffidi Domianello (2026, arXiv) 強調 multivariate volatility 裡，co-movement 與 spillover 要分開看；即使 forecast gain 不大，網路結構與共同成分本身仍有研究價值。
3. **EM 對全球 shock 的共同敏感性**：
   Lastauskas and Nguyen (2024, arXiv) 顯示 EM 對外部金融 shock 的反應具有顯著異質性，但也存在共同受全球條件牽動的通道。

這三者合起來的可反駁假說是：
EM ETF 的 realized vol 之間應存在一個明顯共同成分，但相關 regime 的強弱未必對所有國家都一樣。

## 資料

- Source: `yfinance`
- Tickers: `EEM`, `INDA`, `EWZ`, `EWY`, `EWW`
- 單檔最早可追到 2010，但 **joint sample** 受 `INDA` 上市限制
- Joint sample: **2012-02-03 → 2026-06-09**
- Joint price observations: **3,607**
- RV observations after 21d rolling warm-up: **3,586**

## 方法

### RV 定義

- 每檔 ETF 都用：
- `21d rolling std(log return) * sqrt(252)`

這是 backward-looking realized vol，沒有 lookahead。

### PCA

- 對五檔 RV 先做 **standardization**
- 再對標準化後的 RV 矩陣做 PCA
- 關注：
  - PC1 解釋變異比例
  - PC1 loadings 是否全部同號且接近
  - PC1 score 與 equal-weight basket RV 的相關性

### Correlation regime

- 先算 RV 的 **rolling 63d correlation matrix**
- 每天取 10 組 pairwise correlation 的平均，得到 `avg_pairwise_corr_t`
- 以全樣本分位數切三段：
  - `low`: bottom 25%
  - `mid`: middle 50%
  - `high`: top 25%

### 統計檢定

- 因為 63d rolling correlation 高度重疊，不能用 iid t-test
- 用：
  - `OLS(y ~ regime_dummies)` + **HAC / Newey-West**
  - `maxlags = 63`

檢定對象：

- equal-weight basket RV
- 各資產 RV

資產層多重檢定：

- 5 assets
- Bonferroni `alpha = 0.05 / 5 = 0.01`

## 主要結果

## 1. 共同波動因子非常強

RV 相關矩陣全部是正而且偏高：

- EEM-INDA: **0.799**
- EEM-EWY: **0.812**
- EWZ-EWY: **0.574**
- 其餘多數在 **0.69–0.80**

PCA 結果：

- **PC1 explained variance ratio = 77.4%**
- 其餘 PC2–PC5 合計只有約 22.6%
- PC1 loadings 全為正，且很接近：
  - EEM 0.484
  - INDA 0.439
  - EWZ 0.434
  - EWY 0.421
  - EWW 0.455

PC1 score 與 equal-weight basket RV 的相關高到幾乎一樣：

- **corr(PC1, basket RV) = 0.998**

這代表五個 EM ETF 的 realized vol 幾乎可以視為
「一個共同 EM vol factor + 少量 idiosyncratic deviation」。

## 2. 高相關 regime 下，整體 EM 波動率明顯更高

63d average pairwise correlation：

- q25 = **0.273**
- q75 = **0.672**
- regime counts:
  - low: 881
  - mid: 1762
  - high: 881

equal-weight basket RV 均值：

- low: **0.1947**
- mid: **0.2136**
- high: **0.2745**

HAC regression（base = mid）：

- high vs mid: `+0.0610`, `p=0.052`
- low vs mid: `-0.0189`, `p=0.0071`

解讀：

- 高相關 regime 的 basket RV 明顯更高，但在 HAC 後只到 **borderline**
- 低相關 regime 的 basket RV 較低，這個結果比較穩

## 3. 資產層結果不完全同步

高相關 regime（vs mid）：

- EEM: `+0.0507`, `p=0.029`
- INDA: `+0.0567`, `p=0.095`
- EWZ: `+0.0797`, `p=0.088`
- EWY: `+0.0539`, `p=0.062`
- EWW: `+0.0639`, `p=0.040`

低相關 regime（vs mid）：

- EEM: `-0.0191`, `p=0.016`
- INDA: `-0.0363`, `p=0.0003`
- EWZ: `-0.0363`, `p=0.0051`
- EWY: `-0.0018`, `p=0.885`
- EWW: `-0.0011`, `p=0.928`

Bonferroni `alpha=0.01` 下：

- **low-regime** 的 `INDA`、`EWZ` 仍顯著
- **high-regime** 則沒有任何單一資產過 0.01

這表示：

- 「共同因子存在」非常強
- 但「高相關一定同步放大每個資產 RV」這件事，只能說 **mixed / suggestive**

## Verdict

**PASS**

理由：

1. **共同 EM vol factor 非常強**：
   PC1 解釋 **77.4%** 變異，五檔 loadings 全正且接近，這是非常乾淨的共同因子證據。
2. **correlation regime 不只是視覺現象**：
   在 Bonferroni `0.01` 下，low-corr regime 的 `INDA`、`EWZ` 仍顯著較安靜；
   這表示去同步化狀態確實對部分 EM 市場帶來可辨識的低波動環境。

但仍保留一個重要 caveat：

- **high-corr = 高風險** 的方向成立，但 basket 層 HAC `p=0.052` 只到 borderline，
  所以不能把它包裝成強預測規則。

最誠實的總結是：

- **EM ETF 的 realized vol 幾乎由單一共同因子主導**
- **低相關 regime 對部分市場確實意味著更低波動**
- **高相關 regime 的風險升級則屬中度證據，不是最強版本**

## 研究意涵

1. **跨 EM 分散不是看名目國家數量，而是看共同 vol factor 是否同時升溫**
2. 若建跨 EM vol model，先抽出 PC1 可能比逐國獨立建模更有效率
3. INDA / EWZ 在低相關 regime 下顯著更安靜，代表某些國家在「去同步化」時確實能提供額外分散

## 圖表

- `figures/rv_corr_heatmap.png`
- `figures/pc1_loadings.png`
- `figures/avg_corr_vs_basket_rv.png`

## 三件套

- `k1441.py`
- `k1441_results.json`
- `README.md`

## 重現

```bash
uv run python experiments/k1441/k1441.py
```

## 限制

- 這是 ETF proxy，不是當地現貨指數或高頻 realized measure
- `INDA` 上市較晚，使 joint sample 從 2012 開始
- correlation regime 是 **descriptive state variable**，不是交易訊號
- rolling 63d correlation 天生重疊，所以我們已用 HAC，但仍不把這題包裝成「可預測 future vol」的 claim

## Errata（2026-06-13，Codex 24h-rule review NEEDS_REVISION）

- 高同步 regime 的證據強度被高估：HAC high-vs-mid basket RV `p=0.052`（borderline，非顯著）；asset-level 高 regime 5 檔 0/5 通過 Bonferroni（low regime 1/5 INDA_low 存活 10-test Bonferroni）。
- 多重檢定 family 定義偏窄：原設定 `alpha=0.05/5=0.01`（k1441.py line 199）；若按 10 asset contrasts (5×{high, low}) 校正，`alpha=0.005`，僅 `INDA_low` 存活；`EWZ_low p=0.005118` 剛好不過。Holm/FDR 下 `INDA_low + EWZ_low` 仍存活。
- 主結論（PC1 = 77.4%、共同 EM vol factor、basket RV correlation 0.998）不受影響；需下修的是「高同步期分散效果通常會變差」的語氣，改為「樣本內平均較高、統計上屬中度證據（borderline）」。
- Review 紀錄：`storage/paper_reviews/k1441_mile_39b81aa5/codex_24h_review.md`
