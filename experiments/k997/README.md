# K997: MF-GJR-X 用本地 Fear Index 改進跨市場預測

## 動機
K988 發現 A4f（τ=θ₀+θ₁VIX², free ω）在 SPY 顯著勝 GJR（DM t=+4.48）。
K994 跨資產驗證顯示 US VIX 對非美股市場效果有限：
- QQQ: DM t=-3.71 (PASS, VIX-r² corr=0.494)
- EEM: DM t=-2.47 (fail, corr=0.499)
- GLD: DM t=-1.08 (fail, corr=0.126)
- 0050.TW: DM t=-1.44 (fail, corr=0.275)

假說：用本地 fear index 替代 US VIX 可改善跨市場預測。

## 方法

### 測試的 Fear Index

| 資產 | Fear Index | 說明 |
|------|-----------|------|
| EEM | ^VXEEM | CBOE 新興市場 VIX |
| EEM | OwnRV_20 | EEM 自身 20 日 realized vol |
| EEM | VIX + VXEEM | 雙因子 τ = θ₀ + θ₁VIX² + θ₂VXEEM² |
| GLD | ^GVZ | CBOE Gold VIX |
| GLD | OwnRV_20 | GLD 自身 20 日 realized vol |
| GLD | VIX + GVZ | 雙因子 |
| 0050.TW | OwnRV_20 | 台股自身 20 日 realized vol |
| 0050.TW | VIX_lag2 | 前兩天美國 VIX（給更多反應時間）|
| 0050.TW | VIX + TW_RV | 雙因子 |

### A4f 模型規格
```
τ_t = max(θ₀ + θ₁ × X²_{t-1}, 1e-16)   where X = local fear index
g_t = ω + α × u²_{t-1} + γ × u²_{t-1} × 1_{u<0} + β × g_{t-1}
u_{t-1} = r_{t-1} / sqrt(τ_t)
ω: 自由估計（free omega）

多因子版：τ_t = max(θ₀ + θ₁X₁² + θ₂X₂², 1e-16)
```

### 評估
- OOS: 2019-2026, window=2000, refit/63d
- QLIKE on r² (Patton 2011), DM test vs GJR (Harvey t>3.0), Spearman ρ

## 結果

### 每個資產的最佳模型

| Asset | Best Model | QLIKE | DM t vs GJR | Harvey sig? |
|-------|-----------|-------|-------------|-------------|
| **GLD** | **A4f_VIX+GVZ** | — | **-3.39** | **YES** ✅ |
| GLD | A4f_GVZ (single) | — | -3.17 | YES ✅ |
| EEM | A4f_VIX+OwnRV | — | -2.60 | No |
| 0050.TW | A4f_VIX+TW_RV | 1.430 | -1.70 | No |

### 0050.TW 詳細

| Model | QLIKE | DM t | Sig? |
|-------|-------|------|------|
| A4f_VIX | 1.431 | -1.68 | No |
| A4f_OwnRV | 1.460 | +0.16 | No |
| A4f_VIX+RV | 1.430 | -1.70 | No |
| A4f_VIX_lag2 | 1.440 | -1.55 | No |

## 結論

1. **GLD + GVZ 成功**：Gold VIX 是黃金波動的正確 fear index，DM t=-3.39 通過 Harvey 門檻
2. **EEM 接近但未達**：VIX+OwnRV 雙因子 t=-2.60，VXEEM 可能數據量不足
3. **0050.TW 仍不顯著**：VIX 相關性太低（0.275），缺乏台灣本地 implied vol 指標
4. **乘法結構需要 asset-specific implied vol**：MF-GJR-X 目前通過的市場為 SPY/QQQ/GLD（三個有品質好的 implied vol）

### 局限性
- VXEEM 歷史可能不夠長
- 0050.TW 沒有本地 VIX 等價物
- OwnRV (20d) 是 backward-looking，缺乏 implied vol 的前瞻性

## 檔案
- `k997.py` — 實驗腳本
- `k997_results.json` — 完整結果
- `README.md` — 本文件
