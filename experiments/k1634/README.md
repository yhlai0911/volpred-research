# K1634 — Sell in May and go away 近 15 年還成立嗎？

**類型**：投資迷思驗證系列（老闆 TG msg154 directive）  
**主題**：驗證「Sell in May and go away」在近 15 年美股與台股是否仍可用。比較 SPY / ^TWII 的 11-4 月（Halloween / Nov-Apr）與 5-10 月（May-Oct）月報酬、Sharpe 與簡單空倉策略。

---

## 結論

**myth_verdict = `not_supported_recent_15y`**

近 15 年（2011-07 至 2026-06，180 個完整月）方向上仍看得到 Nov-Apr > May-Oct，但正式檢定不支持把它當成穩健規則：

| 市場 | Nov-Apr 年化均值 | May-Oct 年化均值 | 差距 | HAC p | BH-FDR q |
|---|---:|---:|---:|---:|---:|
| SPY | 15.34% | 13.48% | +1.86% | 0.776 | 0.776 |
| ^TWII | 18.91% | 6.32% | +12.59% | 0.169 | 0.339 |

台股點估計較大，但樣本變異也大；FDR 5% / 10% 都沒有任何 primary cell 存活。SPY 更弱：Nov-Apr 只多 +1.86% 年化，HAC p=0.776。

策略層面也不能直接喊「五月賣掉比較好」：

| 市場 | Buy & Hold CAGR | Sell-in-May after cost CAGR | Buy & Hold Sharpe | Strategy Sharpe | Strategy vs B&H HAC p |
|---|---:|---:|---:|---:|---:|
| SPY | 14.24% | 7.12% | 1.006 | 0.696 | 0.0005 |
| ^TWII | 11.80% | 8.75% | 0.745 | 0.702 | 0.320 |

SPY 的空倉策略明顯輸給買進持有；台股雖然降低回撤（MDD -19.1% vs -28.9%），但 CAGR 與 Sharpe 沒有勝出。

## 動機與文獻

這個迷思源自 Halloween indicator：股票在 11 月到隔年 4 月報酬較高，5 月到 10 月較弱。經典文獻與反方警告都必須同時看：

- Bouman and Jacobsen (2002), American Economic Review, DOI `10.1257/000282802762024683`：經典 Sell in May / Halloween indicator 證據。
- Sullivan, Timmermann, and White (2001), Journal of Econometrics, DOI `10.1016/S0304-4076(01)00077-X`：calendar effects 很容易是 data snooping 假陽性。
- Zhang and Jacobsen (2021), Journal of International Money and Finance, DOI `10.1016/j.jimonfin.2020.102268`：大型國際樣本再檢驗 Halloween indicator。

本專案相似但不同 scope：

- K80 / K736 是 VT 或 VIX 相關季節性與 calendar decomposition。
- 本實驗是讀者迷思驗證：只問 SPY / ^TWII 近 15 年的 calendar-month 股票報酬本身是否支持「五月賣掉」。

## 資料

- 來源：yfinance。
- SPY：adjusted close，股息與分割已反映。
- ^TWII：台灣加權指數 price index close，**不含股息**。
- 下載期間：2010-10-01 至 2026-07-05（end exclusive）。
- 分析期間：2011-07-31 至 2026-06-30，共 180 個完整月。
- 月頻價格：每月最後一個可交易日收盤。

## 方法

### 月報酬與季節定義

- 月報酬：`P_month_end / P_prev_month_end - 1`。
- Nov-Apr：11、12、1、2、3、4 月。
- May-Oct：5、6、7、8、9、10 月。
- 2011-07 至 2026-06 讓兩組各 90 個月，避免樣本窗偏向某一季。

### 主檢定

每個市場做月頻 HAC regression：

```text
ret_m = alpha + beta * I(month in Nov-Apr) + error_m
```

- `beta` = Nov-Apr 月均報酬 − May-Oct 月均報酬。
- HAC / Newey-West `maxlags=6`，對半年度季節叢集採保守處理。
- 兩個 primary tests（SPY、^TWII）做 BH-FDR 校正。

### 穩健性

- Calendar-year block bootstrap：5,000 次、固定 `SEED=1634`。
- Paired season test：同一 season year 內比較 `Nov(y-1)-Apr(y)` 與 `May(y)-Oct(y)`，只保留完整 6+6 月 season。
- 簡單策略：Nov-Apr 持有股票，May-Oct 現金，現金報酬設 0；成本穩健性用單邊 10 bps、每年約兩次切換。

## 主要結果細節

### SPY

- Nov-Apr 年化均值 15.34%，May-Oct 13.48%，差距 +1.86%。
- HAC t=0.284，p=0.776；year-block bootstrap 年化 CI = [-10.09%, +13.38%]。
- 完整 paired seasons 14 年，Nov-Apr 勝 10/14（71.4%），但 paired t p=0.816；bootstrap CI = [-5.03pp, +5.81pp]。
- Sell-in-May after-cost CAGR 7.12%，遠低於 buy-and-hold 14.24%；after-cost strategy minus B&H HAC p=0.0005。

### ^TWII

- Nov-Apr 年化均值 18.91%，May-Oct 6.32%，差距 +12.59%。
- HAC t=1.374，p=0.169；BH-FDR q=0.339。
- year-block bootstrap 年化 CI = [-5.97%, +28.38%]，跨 0。
- 完整 paired seasons 14 年，Nov-Apr 勝 10/14（71.4%），sign-test one-sided p=0.090，仍只是方向性。
- Sell-in-May after-cost CAGR 8.75%，低於 buy-and-hold 11.80%；Sharpe 0.702 vs 0.745。

## 圖表

- `fig1_season_summary.png`：Nov-Apr vs May-Oct 年化均值與 Sharpe。
- `fig2_paired_season_spreads.png`：每個完整 season year 的 Nov-Apr − May-Oct 報酬差。
- `fig3_strategy_growth.png`：買進持有 vs Sell-in-May 現金策略。

## 防錯對照

- **Lookahead**：calendar signal 是月初前已知的 deterministic calendar rule；月報酬用上月月末到當月月末，不用當月未來資訊決定持倉。
- **Baseline 同口徑**：策略比較用同一月報酬序列；B&H 與 Sell-in-May 都在相同 180 個月上計算。
- **重疊窗口**：主資料是非重疊月報酬，仍用 HAC maxlags=6 保守處理半年度 season autocorrelation。
- **多重檢定**：SPY / ^TWII 兩個 primary tests 做 BH-FDR；0/2 存活。
- **Seed / 復現**：bootstrap 固定 `SEED=1634`。
- **小樣本**：paired season 只有 14 個完整年份；台股方向性不可過度宣稱。
- **Null result**：如實報告為不支持近 15 年穩健迷思，而不是把台股較大的點估計包裝成顯著效果。

## 檔案

- `k1634.py`：完整可重跑實驗。
- `k1634_results.json`：統計結果、primary tests、策略指標與 verdict。
- `codex_review.md`：方法論自查與修正紀錄。
- `data/`：SPY / ^TWII close 快取。
- `fig1_season_summary.png`、`fig2_paired_season_spreads.png`、`fig3_strategy_growth.png`：圖表。

## 復現

```bash
uv run python experiments/k1634/k1634.py
```
