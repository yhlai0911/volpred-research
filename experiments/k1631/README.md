# K1631 — 融資餘額創新高＝股市要見頂？台股日頻實證檢定

**Status**: completed  
**Task**: `newroute_margin_balance_top_signal_myth`  
**Seed**: 42  
**Verdict**: `NULL_NO_ROBUST_TOP_SIGNAL`

## 1. 動機

網路常見說法是：**「融資餘額創新高，代表散戶槓桿太滿，股市快見頂。」**

這句話可以拆成兩個可檢定問題：

1. 融資餘額創高後，台股後續報酬是否顯著變差？
2. 融資餘額創高後，台股後續波動是否顯著升高？

本實驗用 TWSE 市場融資餘額日資料與 0050.TW 作為台股大型股 proxy，做可復現檢定。

## 2. 相關知識與文獻

### 相鄰 K

- **K1511**：TWSE 月度融資餘額作為散戶 proxy，檢定「外資作空 × 散戶融資加碼」角色反轉月份；結果為 NULL 且樣本力不足。
- **K1530**：0050 retail-like proxy 對 RV 有 suggestive 但 OOS 不穩定訊息；不可宣稱公開散戶 proxy 有 robust 預測力。

### 文獻定位

- Zhang, Seyedian, and Li (2005), *Economics Letters*, "Margin borrowing, stock returns, and market volatility"：aggregate margin credit balance 與 prior returns / leverage dynamics 關係密切，margin 可能更像順勢或同時指標，而非乾淨的領先見頂訊號。<https://www.sciencedirect.com/science/article/abs/pii/S0165176505000480>
- Andrade, Chang, and Seasholes (2008), *Journal of Financial Economics*, "Trading imbalances, predictable reversals, and cross-stock price pressure"：使用 TWSE margin accounts 作為個股層級非資訊交易 imbalance proxy，證明台灣散戶 margin flow 與後續 reversal / excess volatility 有關。<https://www.sciencedirect.com/science/article/abs/pii/S0304405X08000214>
- Barber, Lee, Liu, and Odean (2009), *Review of Financial Studies*, "Just How Much Do Individual Investors Lose By Trading?"：台灣完整交易資料顯示個人投資人整體有經濟上很大的交易損失，支持把融資行為視為 retail heat proxy 的動機。<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=529062>
- Baker and Wurgler (2006), *Journal of Finance*, "Investor Sentiment and the Cross-Section of Stock Returns"：高情緒可影響後續報酬型態，但不等於所有市場層級高情緒指標都能機械式預測立即見頂。<https://pages.stern.nyu.edu/~jwurgler/papers/wurgler_baker_cross_section.pdf>

## 3. 資料

| 欄位 | 來源 | 說明 |
|---|---|---|
| 市場融資餘額 | TWSE `exchangeReport/MI_MARGN?selectType=MS` | 取「融資金額(仟元)」的「今日餘額」，另用「前日餘額」做嚴格 one-report-lag robustness |
| 0050.TW 價格 | `data/cache/price_cache.db :: price_data` | 使用 `adj_close`，並套用 `volpred.utils.clean_tw50_data` |

樣本：

- 分析起點：2014-01-01
- 實際 joined 日資料：2014-01-02 至 2026-07-03
- 有效 joined daily observations：**3,034**
- 另有 10 個 0050.TW 價格交易日未取得 TWSE `MI_MARGN` 市場融資回應，採 inner join 排除。
- 最新市場融資餘額：**0.6308 兆元新台幣**

0050.TW 是台股大型股 proxy，不是官方 TAIEX。結論限於此 proxy。

## 4. 方法

### 4.1 Lookahead 防錯

訊號在 day `t` 收盤後使用 TWSE 融資餘額。所有 target 都從 **t+1** 開始：

```python
fwd_ret_h = sum(ret_log.shift(-i) for i in range(1, h + 1))
```

也就是說，沒有把同一天報酬拿來配同一天訊號。

### 4.2 Event 定義

主定義：

- `today_all_time_high_cool20`
- `today_balance_kntwd > prior all-time max`
- 前 252 個交易日作 warmup
- 20 個交易日 cooldown，避免連續創高 cluster 被重複計算

輔助定義：

- `today_one_year_high_cool20`：創 252 交易日新高
- `strict_prev_all_time_high_cool20`：用 TWSE 「前日餘額」做 one-report-lag robustness

### 4.3 Target 與檢定

Horizons：5、20、60 個交易日。

每個 event 定義與 horizon 都比較：

- 後續 log return 均值：event days vs non-event days
- 後續下跌機率：Fisher exact test
- 後續 realized volatility：年化 `sqrt(mean(r^2) * 252)`
- OLS dummy regression with Newey-West HAC SE，`maxlags = horizon`
- 主結果再做 moving-block bootstrap，block=20、n_boot=2000、seed=42

## 5. 結果

### 5.1 主結果：全樣本新高，20 日後續報酬

| 指標 | Event days | Non-event days | 差異 / 檢定 |
|---|---:|---:|---:|
| n | 10 | 3,004 | |
| 平均後續 20 日報酬 | **+4.53%** | **+1.60%** | event - other = **+2.93pp** |
| HAC t | | | **+1.42**, p=0.155 |
| 下跌機率 | 40.0% | 35.5% | Fisher p=0.751 |
| Moving-block bootstrap 95% CI | | | **[-1.39pp, +7.37pp]** |

**解讀**：沒有看到「創高後 20 日報酬顯著變差」。點估反而是正的，但 n=10 很小、CI 橫跨 0，所以也不能反向宣稱「創高後會漲」。

### 5.2 主結果：波動

| 指標 | Event days | Non-event days | 差異 / 檢定 |
|---|---:|---:|---:|
| 平均後續 20 日年化波動 | **25.40%** | **17.19%** | +8.21pp |
| HAC t | | | **+3.31**, p=0.00094 |

**解讀**：融資餘額全樣本新高後，後續波動確實比較高。這支持「槓桿熱度升高時市場比較不安穩」，但不是「報酬必然見頂」。

### 5.3 較寬鬆定義：一年新高

| Horizon | n_event | Event 平均報酬 | Non-event 平均報酬 | 差異 | HAC t |
|---:|---:|---:|---:|---:|---:|
| 5 日 | 37 | +0.41% | +0.40% | +0.01pp | +0.02 |
| 20 日 | 36 | +2.53% | +1.60% | +0.93pp | +1.04 |
| 60 日 | 34 | +6.95% | +4.70% | +2.25pp | +1.26 |

一年新高也沒有顯示後續報酬顯著變差。

### 5.4 嚴格 one-report-lag robustness

用 TWSE 「前日餘額」做更保守的 one-report-lag signal，20 日結果仍同方向：

- 全樣本新高：後續 20 日報酬差 **+2.53pp**，HAC t=+1.10；波動差 **+8.85pp**，HAC t=+3.34。
- 一年新高：後續 20 日報酬差 **+0.63pp**，HAC t=+0.74；波動差 **+0.03pp**，HAC t=+0.02。

## 6. 結論

**「融資餘額創新高＝股市要見頂」沒有 robust 支持。**

更精確地說：

1. 創高後的後續報酬沒有顯著變差，主結果 20 日點估還是正的，但樣本少，不能過度解讀。
2. 全樣本新高後，後續波動顯著升高，代表槓桿熱度可視為風險升溫訊號。
3. 因此比較誠實的版本是：**融資餘額創高不是可靠見頂訊號，但可能是「後面更容易震」的風險提示。**

## 7. 限制

1. **0050.TW proxy 限制**：0050.TW 不是官方 TAIEX，且偏大型權值股。
2. **全樣本新高 n 小**：cooldown 後全樣本新高只有 10 個主事件，不能做強否定。
3. **今日餘額可能有修正**：TWSE note 建議以「前日餘額」為準；本實驗以今日餘額為讀者直覺主分析，另用前日餘額做嚴格 robustness。
4. **市場總融資不是全體散戶**：融資戶只是散戶的一部分，不含 ETF、現股、海外複委託、期權與法人槓桿。
5. **沒有個股 panel**：文獻中的 margin imbalance reversal 多在個股層級；市場總餘額可能稀釋個股訊號。

## 8. 檔案

| 檔案 | 內容 |
|---|---|
| `k1631.py` | 完整可復現腳本 |
| `k1631_results.json` | 所有統計量與 provenance |
| `k1631_panel.csv` | joined daily panel |
| `data/twse_market_margin_daily.csv` | TWSE 市場融資日資料 cache |
| `fig_margin_balance_high_events.png` | 市場融資餘額與全樣本創高事件 |
| `fig_forward_returns.png` | 創高後 5/20/60 日報酬比較 |
| `codex_review.md` | Codex 審查 |

復現：

```bash
uv run python experiments/k1631/k1631.py
```
