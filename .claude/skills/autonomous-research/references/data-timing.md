# 數據時間與跨市場對齊

## yfinance 時間語義

yfinance 日線 index 代表該**交易日**，但實際收盤時間因市場不同：

| 市場 | yfinance date | 實際收盤（台北 UTC+8）| 資料可用 |
|------|--------------|---------------------|---------|
| SPY/GLD/TLT | 美國交易日 | 隔天 04:00-05:00 | ~05:30 |
| ^VIX | 同美股 | 隔天 04:00-05:00 | ~05:30 |
| 0050.TW | 台灣交易日 | 當天 13:30 | ~14:00 |
| ^TWII | 同台股 | 當天 13:30 | ~14:00 |

**關鍵**：同一個 date index "2026-03-14"
- SPY 收盤：台北 3/15 04:00（美國 3/14 16:00 ET）
- 0050 收盤：台北 3/14 13:30
- **0050 比 SPY 早 ~14.5 小時**

## 跨市場策略的時間規則

### 台灣策略用美股信號（8.63/VIX、SPY 動量）

正確的 lagging：
```
VIX[date=t] 收盤 → 台北 t+1 日 04:00 才有
0050.TW[date=t+1] 開盤 → 台北 t+1 日 09:00
→ 中間有 5 小時準備，沒有前瞻偏誤 ✅
```

回測中的實作：
```python
# data_date = SPY trading day t (yfinance index)
# VIX[t] → 算台股權重
# 0050 return = next TW trading day AFTER date t
# 這是正確的，因為 VIX[t] 在 0050[t] 收盤後才出現
```

### 邊界情況
- 台灣交易日但美國休市 → VIX 沒更新，用前一天的 VIX（正確）
- 美國交易日但台灣休市 → 0050 沒交易，跳過（正確）
- 夏令/冬令時間差 → 不影響（收盤順序不變：TW 13:30 永遠早於 US 04:00+1）

## 數據收集排程

### 正確時程
```
13:30  台股收盤
14:00  收集 0050.TW 日線 + VIXTWN（台股數據確定）
21:30  美股開盤
04:00  美股收盤（隔天台北時間）
05:30  收集 SPY/GLD/VIX 日線 + 5-min data（美股數據確定）
06:03  daily_update（所有標的收盤價都已確定 → 計算 6 策略）
09:00  台股開盤（用戶已可看到建議）
```

### 系統 crontab
```
0 14 * * 1-5   collect_tw_data     # 台股收盤後
30 5 * * 2-6   collect_us_data     # 美股收盤後（週二至六=美股週一至五）
3 6 * * *      daily_update        # 所有數據就緒後
17 * * * *     supabase_sync       # 每小時同步
```

注意：美股收盤的 cron 是 `2-6`（週二至六），因為美股週五收盤是台北週六 04:00。

## 5-min 數據收集

5-min 數據（用於 HAR-RV / Realized GARCH）：
- **只收美股**（SPY）：必須在美股收盤後（05:30）
- yfinance 5-min 數據只保留 ~60 天
- 每天收集最近 5 天的 5-min data（確保覆蓋）
- 存入 `data/intraday/SPY_5min_YYYY-MM-DD.csv`

## Paper Trading 報酬計算

### 美股策略（slow_vt, risk_parity, 12/vix, 50/50）
```
date[t] 的 VIX/GARCH → 計算權重
date[t+1] 的 SPY/GLD return → actual_returns
portfolio_return = Σ(weight_i × return_i)
```
同市場，收盤時間一致，直接用 t → t+1。

### 台股策略（8.63/VIX, SPY 動量）
```
SPY date[t] 的 VIX/momentum → 計算權重（台北 t+1 04:00 才有）
0050 next TW trading day after date[t] → actual_returns
portfolio_return = weight × 0050_return
```
跨市場，用 `> date[t]` 的下一個台灣交易日，自動處理假日差異。
