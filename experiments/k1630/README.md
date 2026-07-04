# K1630 — 「Sell in May and go away / Halloween 效應」迷思驗證（台股 × 美股，全樣本 vs 近 15 年）

投資迷思驗證系列（老闆 TG msg154 directive）之一。

## 動機
「Sell in May and go away」（萬聖節指標）是最著名的日曆季節異常之一：市場流傳
**11 月–4 月（冬半年，Nov-Apr）報酬顯著高於 5 月–10 月（夏半年，May-Oct）**，
因此「五月賣出、萬聖節（10/31）買回」。Bouman & Jacobsen (2002, AER) 在 37 個市場中
發現此效應普遍存在。核心問題：**這個 2002 年被學界公開後、且已被大量交易，近 15 年
（2011 起）在台股（TAIEX）與美股（S&P 500）是否還成立？** 若異常已被套利掉，符合
McLean & Pontiff (2016) 的「學術研究會消滅可預測性」。這正是「迷思驗證」有價值的測試點。

## 差異化（vs 專案既有 K）
本專案既有 seasonality K 全部是**VT 避險策略的季節性成本**，不是原始指數的 Halloween 報酬效應：
- **K80 / K35 / N153**：VT（12/VIX）保險費是否分季節 → NULL（Diff-in-Diff t=0.17）。測的是「VT 拖累幅度」不是「指數本身冬夏報酬差」。
- **K215**：把 seasonality 當模型 regressor → 傷害 OOS。
- 本 K1630 直接測**原始指數月報酬的冬/夏差**（Halloween 效應本體）+ 明確切近 15 年子樣本 + 台美對照 + 正式 HAC 檢定 + 可交易 timing 策略回測。與上述皆不重疊。

## 資料（來源 / 期間 / 樣本數）
| 標的 | 序列 | 來源 | 期間 | 月樣本數 N |
|---|---|---|---|---|
| 美股指數 | S&P 500 price index (`^GSPC`) 日 Close | snapshot of `experiments/k1410/data/GSPC.csv` → `data/GSPC_snapshot.csv` | 1928-01 – 2026-05 | 全 1181；近15y 185 |
| 台股指數 | TAIEX price index (`^TWII`) 日 Close | snapshot of `experiments/k1410/data/TWII.csv` → `data/TWII_snapshot.csv` | 1997-08 – 2026-06 | 全 347；近15y 186 |
| 美股 ETF（穩健性） | SPY 總報酬 (AdjClose) | `data/cache/price_cache.db` → `data/SPY_snapshot.csv` | 2016-02 – 2026-06（僅 ~10y） | robustness only |
| 台股 ETF（穩健性） | 0050.TW 總報酬 (AdjClose) | `data/cache/price_cache.db` → `data/0050TW_snapshot.csv` | 2009-02 – 2026-06 | robustness only |

- 主分析用**指數 price return**（Halloween 迷思講的是指數）；ETF 用 AdjClose（含息總報酬）作穩健性。SPY 快取僅 2016 起（~10y），只能覆蓋近 15 年窗口的後段，故僅列穩健性、不當主證據。
- 月樣本 N 誠實揭露：近 15 年每個市場僅 ~185 個月（Nov-Apr ~94、May-Oct ~91），**power 有限**，「不顯著」需謹慎解讀（見 verdict）。

## 方法
1. **月報酬**：日 Close 月底 resample → simple pct_change（明確口徑：simple calendar-month return）。
2. **分組**：冬半年 D=1 若 month ∈ {11,12,1,2,3,4}，否則 0（夏半年）。
3. **正式檢定**：OLS `r_m = α + β·D + ε`，**Newey-West HAC** 標準誤。lag 選擇：主用自動 `floor(4·(T/100)^(2/9))`，另報 L=12 穩健性。β = mean(Nov-Apr) − mean(May-Oct)；β>0 且 p<0.05 = Halloween 效應存在。另附 **Welch t-test**（不等變異）佐證。
4. **策略回測**：Halloween timing（Nov-Apr 持有指數、May-Oct 空手現金 0%）vs buy-and-hold；報年化 CAGR / 波動 / Sharpe / MDD。切換為 calendar ex-ante 已知（10 月底進、4 月底出），**無 lookahead**。
5. **穩健性**：circular **block bootstrap**（block=12 月，2000 reps，seed=1630）對 mean difference 給 95% CI（保留序列/年度季節相依）。指數 vs ETF、TW vs US、全樣本 vs 近15y 全對照。
6. 所有隨機程序固定 **seed=1630**。

## 結果表（核心）
月均報酬（%/月）與 HAC 檢定（自動 NW lag）；bootstrap 為 mean-diff 月報酬 95% CI（%/月）。

| 市場 / 樣本 | Nov-Apr | May-Oct | β=差(%/月) | HAC p | Welch p | boot 95% CI(%/月) | 顯著(5%)? |
|---|---|---|---|---|---|---|---|
| **US** 全樣本 1928-2026 (N=1181) | +0.859 | +0.455 | +0.404 | 0.141 | 0.194 | [−0.13, +0.90] | ✗ |
| **US** 近15y 2011-2026 (N=185) | +1.175 | +0.940 | +0.235 | 0.669 | 0.697 | [−0.82, +1.18] | ✗ |
| **TW** 全樣本 1997-2026 (N=347) | +1.682 | −0.407 | **+2.089** | **0.005** | **0.002** | **[+0.57, +3.67]** | **✓** |
| **TW** 近15y 2011-2026 (N=186) | +1.516 | +0.453 | +1.063 | 0.147 | 0.135 | [−0.44, +2.45] | ✗ |

策略回測（Halloween timing vs Buy-and-Hold）：

| 市場 / 樣本 | 策略 | CAGR | 年化波動 | Sharpe | MDD |
|---|---|---|---|---|---|
| US 全 | Halloween | 4.53% | 12.0% | 0.43 | −71.4% |
| US 全 | Buy&Hold | 6.35% | 18.5% | 0.43 | −86.0% |
| US 近15y | Halloween | 6.81% | 10.6% | 0.68 | −20.0% |
| US 近15y | Buy&Hold | 12.36% | 14.2% | **0.90** | −24.8% |
| TW 全 | Halloween | 9.25% | 16.1% | **0.63** | −24.0% |
| TW 全 | Buy&Hold | 5.34% | 22.3% | 0.34 | −63.1% |
| TW 近15y | Halloween | 8.69% | 13.1% | 0.70 | −19.1% |
| TW 近15y | Buy&Hold | 11.02% | 16.8% | 0.71 | −28.9% |

ETF 穩健性（AdjControl 含息，見 `k1630_results.json`）方向與指數一致，不改變結論。

## Verdict
- **美股（US）**：Halloween 效應**即使在近百年全樣本也未達 5% 顯著**（β=+0.40%/月，p=0.14，boot CI 含 0）——方向對但統計上站不住。**近 15 年幾乎完全消失**（β=+0.24%/月，p=0.67，冬夏兩半年皆 ~+1%/月）。近 15 年 Halloween timing 策略 **Sharpe 反輸** buy-and-hold（0.68 vs 0.90）、CAGR 大輸（6.8% vs 12.4%）；唯一好處是較低 MDD。→ **美股：近 15 年不成立（迷思破除）。**
- **台股（TW）**：Halloween 效應在**全樣本 1997-2026 強且高度顯著**（β=+2.09%/月，HAC p=0.005，Welch p=0.002，boot CI [+0.57,+3.67] 不含 0；夏半年月均為負 −0.41%）——與 Bouman-Jacobsen 把台灣列為強效應市場一致。**但近 15 年效應約減半且不再顯著**（β=+1.06%/月，p=0.15，boot CI [−0.44,+2.45] **含 0**）。方向仍為正（冬>夏），惟無法拒絕虛無。→ **台股：歷史強、近 15 年顯著減弱至統計不顯著（減弱中，非確定消失）。**
- **總結**：兩市場近 15 年皆**無法在 5% 拒絕「冬夏無差」**。效應消退的模式與 anomaly-decay 文獻（McLean & Pontiff 2016）一致——2002 年公開後被交易掉。**誠實區分**：近 15 年「不顯著」≠「效應不存在」；台股點估計仍為正、且 power 受限（N≈186）。可下的結論是「近 15 年證據不足以支撐可交易的 Halloween 邊際」，不是「效應已被證明為零」。

## 圖表
- `fig_a_monthly_bars.png`：US & TW 12 個月平均月報酬 bar（冬半年綠、夏半年橘），全樣本。
- `fig_b_cumulative.png`：Halloween timing vs buy-and-hold 累積財富（log 軸），US & TW 全樣本。
- `fig_c_full_vs_15y.png`：效應大小 β（Nov-Apr 減 May-Oct）+ block-bootstrap 95% CI，US/TW × 全樣本/近15y 對照。

## 防錯自查（研究誠實 §）
- **Lookahead**：月報酬於月底完全實現；季節標籤是 calendar month 的確定函數，ex-ante 已知，故 `r_m ~ D` 迴歸無前視。策略 `strat_ret[m] = idx[m]·winter[m]`——是否持有由日曆決定（10 月底進、4 月底出），不用任何未來資訊；代碼註明時序合法性（`k1630.py` docstring §Lookahead）。此題無 `signal.shift(1)` 需求，因分組非由估計信號驅動而是純日曆。
- **Seed**：所有隨機程序（block bootstrap 2000 reps）固定 seed=1630；`np.random.default_rng(1630)`。
- **樣本數誠實**：全樣本 N 大（US 1181、TW 347 月）；近 15 年僅 ~185-186 月（每半年 ~92-94），power 有限已明揭；「不顯著」不寫成「不存在」，台股點估計仍為正。ETF SPY 僅 2016 起（~10y）僅列穩健性。
- **HAC 為主**：不以裸 t-test 當唯一依據；主檢定為 Newey-West HAC（自動 lag + L=12 兩者），Welch 僅佐證；p_auto 與 p_l12 結論一致（robust to lag）。
- **口徑一致**：baseline（buy-and-hold）與策略用同一組月報酬、同一切換慣例；指數用 price return、ETF 用總報酬，分開報不混口徑。

## 文獻（≥3，均已 web 查證 metadata）
1. **Bouman, S., & Jacobsen, B. (2002).** The Halloween Indicator, "Sell in May and Go Away": Another Puzzle. *American Economic Review*, 92(5), 1618–1635. DOI: 10.1257/000282802762024683. — 原始 37 市場證據；台灣屬強效應市場。
2. **Andrade, S. C., Chhaochharia, V., & Fuerst, M. E. (2013).** "Sell in May and Go Away" Just Won't Go Away. *Financial Analysts Journal*, 69(4), 94–105. DOI: 10.2469/faj.v69.n4.4. — OOS（至 ~2012）宣稱效應仍在；本 K 延伸至 2026 檢驗其近 15 年是否仍撐得住。
3. **Jacobsen, B., & Zhang, C. Y. (2021).** The Halloween indicator, "Sell in May and Go Away": Everywhere and all the time. *Journal of International Money and Finance*, 110, 102268. DOI: 10.1016/j.jimonfin.2020.102268. — 長期 + 跨市場穩健性主張，作為本 K 對照的最強「效應存在」論點。
4. **Haggard, K. S., & Witte, H. D. (2010).** The Halloween effect: Trick or treat? *International Review of Financial Analysis*, 19(5), 379–387. DOI: 10.1016/j.irfa.2010.10.001. — 穩健性/data-mining 質疑（去 outlier 後效應仍在），方法論參照。
5. **McLean, R. D., & Pontiff, J. (2016).** Does Academic Research Destroy Stock Return Predictability? *Journal of Finance*, 71(1), 5–32. DOI: 10.1111/jofi.12365. — anomaly 公開後衰退框架，解釋本 K 近 15 年效應消退。

## 成功標準達成
- ✅ 三件套齊全（README + `k1630.py` + `k1630_results.json`）+ 3 張真圖表 + 5 篇查證文獻（>3）。
- ✅ 檢定用 HAC（自動 lag + L=12），非裸 t-test 當唯一依據；Welch 佐證；block bootstrap CI。
- ✅ 明確回答近 15 年 TW/US 各自是否仍顯著（皆否，台股歷史顯著、近15減弱）+ 效應方向（正，冬>夏）與幅度（US 近15 +0.24%/月、TW 近15 +1.06%/月）。
- ✅ `k1630_results.json` 與 README 數字自洽（同一 script 產出）。

## 復現
```bash
python3 experiments/k1630/k1630.py
```
讀 `data/*_snapshot.csv`，輸出 `k1630_results.json` + `fig_*.png`。seed=1630 固定。
