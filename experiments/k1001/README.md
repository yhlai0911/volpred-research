# K1001: Conrad & Loch (2015) Macro GARCH-X vs VIX GARCH-X

## 動機
K988 發現 A4f_VIX（τ = θ₀ + θ₁·VIX²_{t-1}）顯著勝過 GJR（DM t=+4.48）。本實驗比較 VIX GARCH-X 與宏觀變數 GARCH-X（Conrad & Loch 2015 框架），判斷 market-implied 資訊是否優於宏觀基本面。

## 方法
- **資產**: SPY, OOS 2019-2026, w=2000, refit/63d
- **宏觀數據**: FRED (GS10, TB3MS, UNRATE)，月頻 ffill 到日頻，lag 30 天避免 lookahead
- **評估**: QLIKE on r² (Patton 2011), pairwise DM test, Spearman ρ

### 模型
| 模型 | τ 規格 | 類型 |
|------|--------|------|
| GJR_N | 無（標準 GJR） | Benchmark |
| A4f_VIX | θ₀ + θ₁·VIX²_{t-1} | Market-implied |
| Macro_TermSpread | exp(θ₀ + θ₁·TermSpread) | 宏觀 |
| Macro_Unemployment | exp(θ₀ + θ₁·UnempRate) | 宏觀 |
| Macro_Combined | exp(θ₀ + θ₁·TS + θ₂·UR) | 宏觀（多因子） |
| VIX_Macro | θ₀ + θ₁·VIX² + θ₂·TS | 混合 |

所有模型均使用 GJR 短期分量 + free ω（公平比較）。

## 結果

### QLIKE 排名（越低越好）
| Rank | 模型 | QLIKE | vs GJR |
|------|------|-------|--------|
| 1 | **A4f_VIX** | 1.4026 | **-6.33%** |
| 2 | VIX_Macro | 1.4149 | -5.51% |
| 3 | Macro_Combined | 1.4746 | -1.53% |
| 4 | Macro_Unemployment | 1.4921 | -0.36% |
| 5 | GJR_N | 1.4974 | baseline |
| 6 | Macro_TermSpread | 1.5011 | +0.24% |

### DM Tests（Harvey t>3.0 門檻）
| 比較 | DM t | 顯著？ |
|------|------|--------|
| GJR vs A4f_VIX | +4.770 | *** PASS |
| GJR vs VIX_Macro | +4.258 | *** PASS |
| **A4f_VIX vs Macro_TermSpread** | -2.717 | NS (未達 3.0) |
| **A4f_VIX vs Macro_Unemployment** | -3.121 | *** PASS |
| **A4f_VIX vs Macro_Combined** | -3.284 | *** PASS |
| **A4f_VIX vs VIX_Macro** | -3.030 | *** PASS |

### Spearman ρ
| 模型 | ρ |
|------|---|
| A4f_VIX | 0.4276 (最高) |
| VIX_Macro | 0.4183 |
| Macro_Combined | 0.3997 |
| Macro_Unemployment | 0.3964 |
| Macro_TermSpread | 0.3874 |
| GJR_N | 0.3719 |

## 關鍵發現

1. **VIX 顯著勝過宏觀變數**: A4f_VIX 對 Macro_Combined DM t=-3.284（PASS Harvey），對 Macro_Unemployment DM t=-3.121（PASS）。QLIKE 差距 ~5%。

2. **宏觀模型幾乎無法勝過 GJR**: Macro_TermSpread 甚至略差於 GJR（+0.24%），Macro_Unemployment 僅微幅改善（-0.36%），Macro_Combined 改善 -1.53% 但 DM t=1.479（NS）。

3. **加入宏觀反而傷害 VIX**: VIX_Macro（VIX²+TermSpread）比純 VIX 差 0.82%，且 VIX-only 顯著勝 VIX_Macro（DM t=-3.030）。宏觀變數在混合模型中 is noise, not signal。

4. **Information hierarchy**: VIX² >> Unemployment > Combined > TermSpread ≈ GJR。市場隱含波動率已高效聚合宏觀資訊。

## 論文啟示
- VIX GARCH-X 的優勢不僅在於勝過 GJR，還在於勝過宏觀 GARCH-X
- 論文重點應放在 **market-implied vs macro fundamentals** 的對比
- Conrad & Loch (2015) 的宏觀 GARCH-MIDAS 在 OOS 2019-2026 幾乎無效
- 可能原因：(1) COVID/post-COVID 使宏觀變數失效 (2) VIX 已聚合宏觀資訊 (3) 月頻宏觀 vs 日頻 VIX 的頻率差異

## 局限性
- 僅 SPY，需跨資產驗證
- OOS 包含 COVID 異常期
- 宏觀數據只用 term spread 和 unemployment（未含 housing starts, corporate profits）
- 月頻宏觀數據 lag 30 天可能過於保守

## 檔案
- `k1001.py`: 實驗腳本
- `k1001_results.json`: 完整結果

## 參考文獻
- Conrad & Loch (2015). JAE 30(7):1090-1114.
- Engle, Ghysels & Sohn (2013). RES 95(3):776-797.
- Patton (2011). J Econometrics 160:246-256.
- K988: VIX GARCH-X A4f champion
