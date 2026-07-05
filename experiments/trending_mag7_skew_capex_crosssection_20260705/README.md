# Mag 7 資本支出強度 × 選擇權偏斜 Cross-Section 快照（2026-07-05）

**類型**：trending_repost 證據包（task_id `trending_repost_2026_07_05_ai基建`）
**發佈文章**：（見 publish 結果，發佈後回填 mile_id）

## 動機與角度差異化（arc-dedup 說明）

派工 brief 原始建議角度是「Mag 7 資本支出 → 波動率偏斜定價變現期延遲風險」。
但寫作前查核 `storage/reports/trending_repost_log.json` + `experiments/`
發現該 narrative arc 在過去 30 天內**已被覆蓋至少 3 次**：

| mile_id | 發佈日 | 標題 | 與本次提案的重疊 |
|---|---|---|---|
| `mile_d1609f75` | 2026-06-06 | 五家公司砸了四千四百億，波動率卻睡著了 | capex 總額 + VIX 總體水準對比 |
| `mile_b221e550` | 2026-06-24 | 法說季開打前，Mag 7 的期權市場悄悄在說一件事 | Mag7 RV30/60/90 + 財報前 option 訊號 |
| `mile_f5f4cb43` | 2026-06-30（僅 5 天前）| 科技巨頭資本支出爆表，AI 變現期的隱含波動率拐點 | **CapEx YoY vs Revenue YoY「變現缺口」+ QQQ 25-delta skew** — 與原提案幾乎同一 arc |
| `trending_2026_06_28_semis_skew` | 2026-06-28 | （半導體 skew）| 相鄰 skew 主題 |
| `trending_nvda_vol_skew_20260618` (`mile_0daa4bb2`) | 2026-06-18 | NVDA skew term structure | 單一標的 skew snapshot |

`mile_f5f4cb43` 尤其與原提案高度重疊（同樣是「capex 成長 vs 變現速度」+「隱含波動率」的組合），且僅 5 天前發佈。依 Layer 4 narrative-arc dedup 規則（同邏輯換外殼算 dup），**放棄原提案角度**。

## 差異化後的新角度

改採**跨資產截面（cross-section）排名 + 等級相關**，這是先前 6 篇都沒做過的分析層次：

- 先前文章都是「單一標的時間序列」（NVDA term structure）、「指數層級」（QQQ skew）、
  或「CapEx 成長率 vs 營收成長率」的**成長速度缺口**。
- 本次改成：**同一天、同一到期日**，橫向比較全部 7 檔 Mag 7 的
  (a) 資本支出強度（TTM CapEx / TTM 營收，存量比率非成長率）
  (b) 目前選擇權市場對其下檔保護的相對定價（±10% OTM put-call IV 差）
  (c) 兩者的截面等級相關（Spearman ρ）
- 這是一個「誰的下檔保費最貴、是否跟燒錢力度成正比」的**排名/相關性**問題，
  在方法論與資料維度上都與先前 6 篇不同（先前無人做過 7 檔同時同期的截面排名）。

## 資料來源

- **選擇權鏈**：yfinance 即時 `Ticker.option_chain()`，統一到期日 2026-08-07（DTE=33，7 檔全部使用同一到期日確保可比性）
- **歷史股價**：yfinance `Ticker.history(period="6mo")`，計算 30 日已實現波動率（年化）與 90 日動量報酬
- **財報數字**：yfinance `quarterly_cashflow`（Capital Expenditure）+ `quarterly_financials`（Total Revenue），取最近 4 季加總為 TTM
- **拉取時間**：2026-07-05（台灣時間），詳見 `results.json.run_timestamp_utc`

## 方法

1. 對每檔標的，找到 DTE 落在 30-45 天窗口內、且所有標的一致的到期日（本次全數落在 2026-08-07，33 天）
2. ATM IV = 最接近現價的 call + put IV 平均
3. **10% OTM skew**（brief 明訂的近似 25-delta 替代方案）= 最接近現價×0.90 的 put IV − 最接近現價×1.10 的 call IV
4. RV30 = 最近 30 個交易日 log-return 年化標準差
5. IV-RV gap = ATM IV − RV30
6. 資本支出強度 = TTM CapEx / TTM 營收 × 100
7. **Spearman 等級相關**（`scipy.stats.spearmanr`）：資本支出強度 vs skew；資本支出強度 vs IV-RV gap；90 日動量報酬 vs skew

## 關鍵數字（完整表見 `cross_section.csv` / `results.json`）

| Ticker | 資本支出強度 (%) | 10% OTM Skew (pp) | ATM IV (%) | RV30 (%) | IV-RV Gap (pp) | 90d 報酬 (%) |
|---|---|---|---|---|---|---|
| META | 35.2 | −3.1 | 48.1 | 48.7 | −0.6 | +1.6 |
| MSFT | 30.5 | −2.5 | 43.9 | 40.7 | +3.2 | +4.8 |
| GOOGL | 26.0 | +0.1 | 41.5 | 32.1 | +9.4 | +21.8 |
| AMZN | 20.3 | −1.8 | 44.6 | 35.0 | +9.5 | +15.7 |
| TSLA | 9.7 | −0.4 | 47.8 | 54.7 | −6.9 | +9.1 |
| NVDA | 2.6 | +3.8 | 41.5 | 40.6 | +0.9 | +10.0 |
| AAPL | 2.4 | +3.9 | 30.8 | 33.8 | −3.0 | +20.7 |

**Spearman ρ（資本支出強度 vs 10% OTM skew）= −0.893，p = 0.007，n = 7**
**Spearman ρ（資本支出強度 vs IV-RV gap）= +0.357，p = 0.432，n = 7**
**Spearman ρ（90 日動量報酬 vs 10% OTM skew）= +0.750，p = 0.052，n = 7**

## 解讀與限制（研究誠實）

- **這是描述性截面分析，不是具統計檢定力的正式假設檢定**。n=7 的 Spearman p-value
  即使數字上 <0.05，也不構成「證實」——樣本點就是全部母體（僅有的 7 家公司），
  沒有抽樣分佈可言，p-value 在此僅供參考排序強度，不可解讀為「有 99.3% 信心因果存在」。
- **單一快照，非時間序列**：僅反映 2026-07-05 這一天、單一到期日的市場定價。
  下週重跑可能得到不同結果（skew 每日隨供需、部位、財報倒數天數變動）。
- **相關不等於因果**：資本支出強度、skew、動量報酬三者兩兩都有相關（動量 vs skew 也達 +0.75），
  無法用本次截面數據拆解何者是驅動因子。文中會列出至少 2 種可能解讀，明確標示「無法用現有資料
  區分」，不做單一因果宣稱。
- **10% OTM 是近似值，非真正 25-delta**：brief 允許此近似（±10% OTM 作為 25-delta 替代）。
  不同標的的隱含波動率水準不同，10% OTM 對應的實際 delta 會有落差（高 IV 標的的 10% OTM
  對應 delta 較接近 ATM，即比 25-delta 更淺）；本文會在文中揭露此限制。
- **capex 期間對齊**：MSFT/GOOGL/AMZN/META/TSLA 為 2025Q3-2026Q1（自然季），NVDA 因財報年度
  offset 為 2025Q3-2026Q1 對應其自訂財年（結束月 1/4/7/10 月）。已在 `results.json` 逐筆記錄
  `capex_period_start/end` 供驗證。

## 檔案

- `collect_data.py` — 資料抓取 + 分析主程式（含 Spearman 相關計算）
- `make_charts.py` — 圖表生成（讀 `results.json`）
- `results.json` — 完整截面數據 + 相關係數
- `cross_section.csv` — 表格化原始數據
- `figures/chart1_capex_vs_skew_bars.png` — 資本支出強度 vs skew 雙軸長條圖
- `figures/chart2_scatter_rank_corr.png` — 截面散點圖 + 趨勢線 + Spearman ρ 標註
