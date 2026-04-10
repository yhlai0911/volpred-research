# K1036: A4f + CF-Rolling VaR -- Best Model x Best VaR Method

## 動機
K1034 證明 CF-Rolling 是最佳 VaR 方法（GJR + CF-Rolling: 6/6 Trinity PASS），K1035 證明 A4f 是最佳波動率模型（A4f-t: 4/4 Trinity PASS）。本實驗用 2x3 factorial design 探討兩個改善是否可疊加，並分離模型效應與 VaR 方法效應。

## 問題
1. A4f + CF-Rolling 是否達成雙重改善？
2. 改善主要來自 A4f（模型精度）還是 CF-Rolling（尾部修正）？

## 方法
- **模型**：GJR-GARCH(1,1), A4f-VIX（tau_t = theta0 + theta1 * VIX^2_{t-1}）
- **VaR 方法**：Normal, Student-t(df=8), CF-Rolling(252d)
- **資產**：SPY, QQQ, GLD
- **OOS**: 2019-01-01 起，window=2000, refit/63d
- **alpha**: 2.5%, 1%
- **評估**：Kupiec LR, Christoffersen CC, Basel traffic light, Trinity, Acerbi-Szekely ES

## 結果

### 2x3 Interaction Table (Trinity PASS Rate)

| Model\Method | Normal | Student-t | CF-Rolling |
|:------------|:------:|:---------:|:----------:|
| **GJR**     | 0/6 (0%) | 1/6 (17%) | **6/6 (100%)** |
| **A4f**     | 1/6 (17%) | 5/6 (83%) | **6/6 (100%)** |

### 模型效應 vs 方法效應

| 效應 | Trinity PASS | Rate |
|:-----|:-----------:|:----:|
| **GJR** (avg over methods) | 7/18 | 38.9% |
| **A4f** (avg over methods) | 12/18 | 66.7% |
| **Normal** (avg over models) | 1/12 | 8.3% |
| **Student-t** (avg over models) | 6/12 | 50.0% |
| **CF-Rolling** (avg over models) | 12/12 | **100.0%** |

### 個別資產結果

**SPY:**
- GJR+Normal: FAIL (VR=3.72%)
- GJR+Student-t: FAIL (VR=3.50%)
- GJR+CF-Rolling: PASS (VR=2.19%) / PASS (VR=0.82%)
- A4f+Normal: PASS (2.5%) / FAIL (1%)
- A4f+Student-t: PASS (2.5%) / PASS (1%)
- A4f+CF-Rolling: PASS / PASS

**QQQ:**
- GJR+Normal: FAIL / FAIL
- GJR+Student-t: FAIL / FAIL
- GJR+CF-Rolling: PASS / PASS
- A4f+Normal: FAIL / FAIL
- A4f+Student-t: PASS / PASS
- A4f+CF-Rolling: PASS / PASS

**GLD:**
- GJR+Normal: FAIL / FAIL
- GJR+Student-t: FAIL (CC) / PASS
- GJR+CF-Rolling: PASS / PASS
- A4f+Normal: FAIL / FAIL
- A4f+Student-t: FAIL (CC) / PASS
- A4f+CF-Rolling: PASS / PASS

## 結論

1. **CF-Rolling 是 dominant factor**：無論用 GJR 或 A4f，CF-Rolling 都達 6/6 Trinity PASS (100%)。VaR 方法的效應（8.3% -> 50% -> 100%）遠大於模型效應（38.9% vs 66.7%）。

2. **A4f + CF-Rolling 確認 6/6 PASS**，但 GJR + CF-Rolling 也是 6/6 PASS，因此 CF-Rolling 足以解決問題，不需要更複雜的模型。

3. **A4f 的價值在 Student-t 層面**：A4f+Student-t 5/6 PASS vs GJR+Student-t 1/6 PASS，說明 A4f 改善了條件方差估計的精度，使得 Student-t 分配假設更合理。但 CF-Rolling 已經繞過了分配假設的限制。

4. **Normal VaR 無論搭配什麼模型都不可靠**：Normal 只有 1/12 PASS，因為忽略了標準化殘差的厚尾和負偏態。

5. **實務建議**：如果目的是 VaR/ES backtesting compliance，CF-Rolling + 任何合理的 GARCH 模型即可。如果目的是波動率預測本身（QLIKE），A4f 仍是最佳選擇。

## 局限
- OOS 期間固定為 2019-2026，包含 COVID-19 極端事件
- CF expansion 在極端峰態時可能不穩定（已 clip 至 [-2, 30]）
- Student-t df=8 是固定的，未做 joint MLE
- 只測了 3 個美股資產，未含台股

## 檔案
- `k1036.py`: 實驗腳本
- `k1036_results.json`: 完整結果
- `k1036_violation_rates.png`: 違約率比較 bar chart
- `k1036_trinity_heatmap.png`: Trinity PASS rate 熱力圖
- `k1036_detail_comparison.png`: 各資產詳細比較

## 參考文獻
- Cornish & Fisher (1938). Rev Inst Int Statist 5:307-320
- Kupiec (1995). J Derivatives 3:73-84
- Christoffersen (1998). Int Econ Rev 39(4):841-862
- Acerbi & Szekely (2014). Back-testing Expected Shortfall. Risk.
- Engle, Ghysels & Sohn (2013). RES 95(3):776-797
- K1034: CF-Rolling 6/6 Trinity PASS
- K1035: A4f 4/4 with Student-t

## 執行時間
~1100 秒（18.3 分鐘）
