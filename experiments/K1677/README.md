# K1677 — Fraud / enforcement contagion: peer-volatility spillover

## 研究問題
當某公司的詐欺 / 法律執法衝擊（SEC/DOJ 起訴、財報重編、觸發執法的做空報告）公開後，
該公司**同產業 peers（排除焦點公司本身）**在 t+1..t+10 窗口是否出現異常的
(a) 已實現波動率、(b) 左尾風險（下行 semivariance / worst-day）、(c) 流動性惡化
（Corwin-Schultz high-low spread、Amihud illiquidity），相對自身近期基準與市場？

## 資料與方法
- **事件集**：`events.csv` — **手工整理**的美國公開詐欺/執法**揭露**事件（**非**完整 SEC AAER 母體）。
  事件日 = 首次廣泛公開報導日（AAER 發布日不是好的市場事件日，Karpoff-Lee-Martin 2008）；t0 = 事件日當日/之後第一個交易日。
- **傳染標的**：同產業流動 peers **排除焦點公司**的等權籃子（用 sector ETF 會被焦點公司自身崩盤汙染）。焦點公司價格從不使用 → 下市 focal 也可處理。
- **控制**：(1) 對 SPY 市場調整；(2) 每籃子 200 個隨機非事件起點的 placebo（seed=42）→ 標準化異常 z。
- **聚合（K1355 合規）**：每事件一個數（籃子均值），再跨事件做 t-test / Wilcoxon / bootstrap。**不做同日跨資產 iid pooling。**
- **無 lookahead**：測量窗嚴格在 t0 之後（僅用 post-event realized data）。
- 資料源：yfinance 日 OHLCV（`auto_adjust=False`），快取於 `data/`。seed=42。

## 結果（n=28 事件）— **NULL**
| measure | n | t | p(t-test) | BH-FDR |
|---|---|---|---|---|
| rv_mktadj（主問題）| 28 | 0.77 | 0.450 | 0.622 |
| rv_placebo_z | 28 | 0.50 | 0.622 | 0.622 |
| rv_raw_logratio | 28 | -0.53 | 0.602 | 0.622 |
| semivar_mktadj | 28 | 1.78 | 0.086 | 0.229 |
| semivar_placebo_z | 28 | 1.21 | 0.237 | 0.474 |
| worstday_placebo_z | 28 | -2.48 | 0.020 | 0.078 |
| spread_cs_logratio | 28 | 2.86 | 0.008 | 0.065 |
| amihud_logratio | 28 | 0.71 | 0.482 | 0.622 |

**結論**：詐欺/執法揭露事件對同產業 peers 的**波動率無顯著傳染**（主問題 rv t=0.77, p=0.45, BH=0.62；placebo 亦 null）。
唯一邊際訊號是 peer 的 **bid-ask spread（Corwin-Schultz）上升**（t=2.86, p=0.008, BH=0.065），
但在 8 個檢定家族的多重檢定下（Bonferroni α≈0.006、BH-FDR min=0.065）**未穩健存活** → 只能視為值得後續追的線索，不可宣稱效應。

## 誠實聲明（honesty_caveats）
1. 手工整理的 salient 事件樣本，**非**完整 AAER 母體 → 選樣偏誤**傾向於**找到傳染。
2. Placebo 淨掉籃子波動叢集/基準，但**不**淨掉事件選樣偏誤。
3. 8 個 aggregate 檢定家族；單一 p 值需多重檢定 skepticism（Bonferroni α≈0.006）。
4. 10 日 post 窗口短；semivariance/worst-day 以外的尾部 quantile 不可估。
5. 少數事件時間叢集（2019-2021）；市場調整緩解共同衝擊但殘餘依賴可能。
6. 事件日手工從公開報導編製（±~1 交易日）。

## 復現
```
uv run python experiments/K1677/K1677.py
```

## 檔案
- `K1677.py` — 主腳本
- `K1677_results.json` — 結果（8 aggregate 家族 + by-event-type）
- `K1677_event_table.csv` — 逐事件明細
- `K1677_contagion_by_event.png` — 逐事件傳染圖
- `events.csv` — 手工整理事件集
- `data/` — yfinance 價格快取

## Verdict — Codex review = **FAIL**（2026-07-11，gpt-5.6-sol）
主指標 RV 的 NULL 可重現，但**現行 README 的次要敘事錯誤**，需 revision（→ K1677-rev）才能到 knowledge grade。**未寫 knowledge.json（provenance gate 守住）。**

Codex 具體發現（行號對 `K1677.py`）：
1. **方向錯置（最關鍵）**：程式全用**雙尾**檢定（:280），但 claim 是**方向性**（peer 波動/尾部**上升**）。按事前方向單尾重算並對同 8 項 BH：**spread q=.032、worst-day q=.039 兩者均過 5%** → 本 README「唯一 spread 邊際、皆未過多重檢定」**不成立**。方向性上，詐欺事件後 peer 的 **illiquidity 與 worst-day 尾部風險確有顯著傳染**；只有主指標 **RV 仍 NULL**（單尾 market-adj q=.321）。
2. **peer 非 point-in-time universe**：程式靜默忽略抓不到的 ticker（:135），128 個 peer occurrence 缺 9 個（含 Archegos 的 `CS`、RIDE 的 `NKLA/FSR`）→ 明顯**朝 NULL 偏**；且無 focal-firm filter/assert（:324）。
3. **placebo 不乾淨**：只排自身 t0 ±30 日（:248），未覆蓋 60 日前窗、未排其他事件；重建後 5,600 origins 有 42 個與自身實際 post window 重疊，且抽樣涵蓋事件後未來與不同 peer 組成 → placebo-normalized NULL 不可信。
4. **measure 定義**：downside semivariance 實為「負報酬日條件均方」非標準 semivariance（:209）；Amihud 切窗後才 `diff()` 漏 t+1（:187）。
5. 事件 iid bootstrap 未處理時間重疊/共同 SPY shock。

PASS 項：t+1..t+10 切窗無 lookahead（:57/:222）、seed=42（placebo+bootstrap，:318/:407，重算完全一致）、K1355 每事件一數再跨事件（:366/:403）、SPY log-RV market-adjust（:344）。

**Closure**：實驗已執行 + 獨立 review。結論**不成立於現行敘事**（方向性下有顯著 illiquidity/worst-day 傳染，RV NULL）→ 建 **K1677-rev**（5 修：單尾方向檢定 + point-in-time peer universe + placebo halo 覆蓋全前窗且排其他事件 + 標準 semivariance + Amihud t+1 修正）。修正後才可寫 knowledge。
