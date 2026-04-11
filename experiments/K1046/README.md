# K1046: Monte Carlo VaR with A4f -- Simulated Path VaR

**[提出: 賴奕豪, 執行: Claude]**

## 動機

K1036 顯示 CF-Rolling 達到 6/6 Trinity PASS（最佳 VaR 方法），K1043 證實 FHS 12/12 = CF-Rolling 12/12。本實驗測試面向 B 最後一個未測的 VaR 方法：**Monte Carlo simulation**。

MC-VaR 使用 GARCH 模型模擬未來報酬路徑，從模擬分佈取 VaR 分位數。優勢：可精確捕捉 GARCH 動態、可做多步預測、可加入 jump/regime。

## 方法

### 實驗設計：2x4 因子設計

| 維度 | 水準 |
|------|------|
| **模型** | GJR-GARCH(1,1), A4f-VIX (multiplicative) |
| **VaR方法** | MC-Normal, MC-t(df=8), CF-Rolling(252d), FHS(252d) |

### MC-VaR 方法（1-day）

```
At time t, forecast VaR for t+1:
1. sigma^2_{t+1} = GARCH forecast (deterministic given info at t)
2. For s = 1,...,10000:
   epsilon ~ N(0,1) or t(8)*sqrt(6/8)
   r_sim = sqrt(sigma^2_{t+1}) * epsilon
3. VaR = percentile(r_sim, alpha*100)
4. ES = mean(r_sim[r_sim <= VaR])
```

### 技術規格

- 資產：SPY, QQQ
- 數據：2005-01-01 ~ 2026-04-10（yfinance）
- OOS：2019-01-01 起（1827 天）
- Window: 2000, refit_every: 63
- N_sim: 10,000 per day
- alpha levels: 1%, 2.5%
- Seed: 42

## 結果

### Trinity PASS Rate（2x4 交互表）

| Model\Method | MC-Normal | MC-t | CF-Rolling | FHS |
|:------------|:---------:|:----:|:----------:|:---:|
| **GJR** | 0/4 (0%) | 0/4 (0%) | **4/4 (100%)** | **4/4 (100%)** |
| **A4f** | 2/4 (50%) | **4/4 (100%)** | **4/4 (100%)** | **4/4 (100%)** |

### 核心發現

1. **MC-Normal 表現最差**：GJR+MC-Normal 0/4, A4f+MC-Normal 2/4。Normal 分配在 1% VaR 嚴重低估尾部風險（violation rate 1.8-2.4% vs 目標 1%）。
2. **MC-t 需要 A4f 配合**：GJR+MC-t 0/4 FAIL，但 A4f+MC-t 4/4 PASS。原因：GJR 低估波動率，即使用厚尾分配也不夠；A4f 通過 VIX 外生信息提高了 sigma 準確度。
3. **CF-Rolling 和 FHS 仍然最可靠**：8/8 (100%) Trinity PASS，不受模型影響。
4. **A4f 效應顯著**：A4f 14/16 (87.5%) vs GJR 8/16 (50.0%)。A4f 的 VIX 外生信息讓 MC 方法也能通過。

### 計算成本

| 方法 | 平均時間 |
|------|---------|
| FHS | 0.1s |
| MC-Normal | 0.3s |
| MC-t | 0.6s |
| CF-Rolling | 11.3s |

MC 方法反而比 CF-Rolling 快（因為 CF 需要逐日計算偏態/峰態），但 FHS 最快。

### 方法效應排名

1. CF-Rolling: 8/8 (100%)
2. FHS: 8/8 (100%)
3. MC-t: 4/8 (50%)
4. MC-Normal: 2/8 (25%)

## 結論

MC-VaR **無法匹配** CF-Rolling/FHS 的 100% Trinity PASS 率。MC 的核心問題是 1-day VaR 中，sigma 已由 GARCH 確定，MC 只增加了 innovation 分配的 sampling noise，反而引入不穩定性。CF-Rolling 和 FHS 通過直接使用歷史殘差分佈的高階動差（偏態、峰態）來校正 VaR，比 MC 模擬更精確。

**MC-VaR 的理論優勢（多步預測、jump/regime）在 1-day horizon 下無法發揮。** 對於 1-day VaR，CF-Rolling 或 FHS 是更好的選擇。MC 方法只有在多步（h>1）預測或需要整條路徑（如 option pricing）時才有價值。

### 局限性

- 僅測試 1-day horizon（MC 的真正優勢在 h>1）
- 僅 2 資產（SPY, QQQ）
- MC 使用固定 df=8，未最佳化
- N_sim=10000 可能引入 sampling noise（但標準誤小於 0.1%）

## 檔案

- `k1046.py`: 實驗腳本
- `k1046_results.json`: 完整結果
- `k1046_trinity_heatmap.png`: Trinity PASS 率熱圖
- `k1046_violation_rates.png`: 違約率比較
- `k1046_timing_comparison.png`: 計算成本比較

## 參考文獻

- Pritsker (2006). The Hidden Dangers of Historical Simulation. J Bank Finance.
- Glasserman (2003). Monte Carlo Methods in Financial Engineering. Springer.
- Barone-Adesi, Engle & Mancini (2008). RFS 21(3):1223-1258.
- K1036: A4f + CF-Rolling 6/6 Trinity PASS
- K1043: FHS 12/12 = CF-Rolling 12/12
