# K1717 / ASIA-1：India VIX 與美國 VIX 對 NIFTY 次日波動的資訊含量

## 動機與差異化

本實驗回答：印度本地選擇權市場的 India VIX，是否比美國 VIX 含有更多 NIFTY 次一交易日波動資訊？若答案通過嚴格的樣本外 gate，才進一步測試月頻 `c / IndiaVIX` 波動率目標策略。

與既有研究的接點：

- R12：台股上，美國 VIX 的資訊量高於 VXEEM（Spearman 0.595 vs 0.459），但沒有比較本地 India VIX。
- K397：做過印度市場描述、INDA 與美國 VIX 關聯，未做 India VIX vs US VIX 的同期間、同 target、正式 OOS QLIKE/DM 比較。
- Q1/R15：`8.63 / VIX` 的台股結果要求月頻再平衡、明確 lag 與成本；也提醒 `c` 主要校準風險，不應靠 Sharpe 搜尋。

因此 K1717 是重新建立的嚴格跨市場檢驗，不繼承 R12/K397 的有效性，也不是重跑 K397。

## Data & Methodology

- 方法類型：`empirical`。策略段若 gate 通過，仍只是 NIFTY 指數報酬模擬，不是可直接交易產品的回測。
- 資料來源：yfinance `^NSEI`、`^INDIAVIX`、`^VIX`；腳本拉取最長可得樣本並把實際資料快照寫入 `k1717_data.csv`，結果 JSON 記錄 SHA-256。印度資料截止 2026-07-15；執行時 2026-07-15 美國交易時段尚未完成，因此美國 VIX 僅使用截至 2026-07-14 的完整收盤值。
- 預測 target：NIFTY close-to-close 日對數報酬平方 `r²_t`；這是條件變異數的 noisy proxy，不等同日內 RV。
- Timing：India VIX 與 US VIX 都用「來源日期嚴格小於印度 target 日期」的 backward as-of join；另保留 India `signal.shift(1)` 作交易日曆診斷。若 Yahoo 漏掉一個有 India VIX 報價的 NIFTY 日期，下一筆 NIFTY close-to-close 報酬會跨多個 session，且最新 India VIX 落在該報酬窗內；這類 target 與相應 open-to-next-open holding interval一律排除，不以較舊訊號掩蓋資料缺口。
- Granger：使用同一份已排除 vendor-calendar gaps 的非重疊 daily log-r² 做三變量 VAR；只用 2020 前樣本以 AIC 在 1–5 lag 選單一 lag，再於完整樣本固定該 lag。India VIX、US VIX 同時進模型，Holm 校正兩個方向。這是預測性診斷，不是結構因果。
- OOS：2020–2026 每年年初用截至前一年末的 expanding sample 重估；2020 COVID 與 2022 空頭都在 OOS。2008 GFC 因 India VIX 才剛開始，僅作診斷/訓練，不冒充正式 OOS。
- 模型：zero-mean Gaussian-QMLE GJR-GARCH(1,1)、GJR-GARCH-X(India/US VIX)、低頻 HAR-style daily-r² proxy、HAR-X(India/US VIX)，另列 past-only scale-calibrated direct IV benchmark。GJR 約束為 `omega>0`、`alpha/gamma/beta>=0`、`alpha+gamma/2+beta<0.998`；X 係數預註冊為非負。前 50–252 筆（依樣本長度）只作 variance recursion burn-in、不計 likelihood；輸出 multistart objective、bound/constraint、gradient 與標準化殘差診斷。daily-r² 規格不冒充高頻 HAR-RV。
- 評估：Patton (2011) canonical QLIKE `actual / predicted`、MSE、Spearman；全部模型使用同一個「actual 與所有 forecast 皆有限且嚴格為正」的 OOS mask。India-vs-US 的兩個非巢狀 primary DM 一律呼叫 `volpred.stats.model_evaluation.dm_test`，h=1 仍使用 canonical HAC bandwidth，並報 loss differential ACF、lag sensitivity 與兩項 primary Holm 校正。X-vs-base 的 nested DM 只列診斷，另報 Clark-West MSE test；四個 Clark-West p-value 與 gate 後的策略 DM 都是未校正 exploratory diagnostics，不餵入 primary gate，也不支持 familywise 或部署宣稱。
- 隨機程序：固定 seed 42；若進策略段，drawdown circular-shift null 使用 1,000 reps。

## 預註冊決策 gate

India VIX 必須同時滿足：

1. 在 GJR-GARCH-X 與 HAR-style-X 兩個 family 的 OOS QLIKE 都低於 US VIX；
2. 兩個 local-vs-US canonical DM 都必須 `t < -3`，且兩項 primary non-nested comparison 的 Holm p 都 < 0.05；
3. 不可有反方向顯著勝出。

只有三項全過才跑 VT。若進 VT：`c` 只按 2020 前完整 holding periods 把策略年化波動校準到 12%，不按 Sharpe 選參數；月頻權重與 baseline 使用相同 lag；每次月頻目標權重實際改變時扣成本，月內讓持股權重隨報酬自然漂移，不假設免費的每日再平衡。遇到被排除的跨-gap holding interval 時，不虛構報酬：在上一個可觀測端點平倉並計 exit turnover/cost，下一個有效 interval 從現金重新建倉。前一收盤訊號在 target session 開盤前可得，月初於 `Open[t]` 調整後持有至 `Open[t+1]`，因此報酬包含持倉期間不可分割的隔夜段；`always-invested open-to-open` baseline 使用相同 holding interval 與成本口徑。這仍不是含股息的 buy-and-hold。由於 repo 沒有印度現金指數的 canonical 成本表，只報 0/10/25 bps per-dollar-turnover 的透明假設敏感度，不宣稱官方成本。

## 成功標準與異常條件

- 完成：`README.md`、`k1717.py`、`k1717_results.json`、資料快照與至少兩張真圖；OOS ≥252 日，包含至少一個空頭；跑 `experiment_gates.py`。
- 必須回報：任何 GARCH fit 未收斂、訊號來源日期未嚴格早於 target、DM loss differential 高自相關、結果在 2020/2022 反轉。
- Forecast gate 的 close-to-close `r²` 與策略的 open-to-next-open holding return 並非同一區間；前者只作資訊排序篩選，不能單獨證明策略持有區間的 timing relevance。
- 最終資料快照診斷出 16 個 vendor-calendar gap targets；從 forecast estimation/scoring 排除後，GARCH/HAR state 只能沿剩餘 clean observations 更新。本實驗不虛構缺失 session 的 NIFTY 日報酬，並把這個不規則間隔列為限制。策略另保留 gap target 當日的下一段有效 holding interval，只排除真正跨 gap 的前一段。
- 失敗但仍是結果：local gate 不過時忠實標 NULL/MIXED 並跳過 VT。
- 不可宣稱：Granger = 因果；30 日 IV = 真實次日波動；低曝險 raw MDD = timing skill；NIFTY 指數模擬 = 可上架策略。

## 文獻依據

1. Shaikh, I. & Padhi, P. (2014), *Economic Change and Restructuring*, DOI `10.1007/s10644-014-9149-z`。
2. Pati, P. C., Barai, P. & Rajib, P. (2018), *Applied Economics*, DOI `10.1080/00036846.2017.1403557`。
3. Patton, A. J. (2011), *Journal of Econometrics*, DOI `10.1016/j.jeconom.2010.03.034`。
4. Corsi, F. (2009), *Journal of Financial Econometrics*, DOI `10.1093/jjfinec/nbp001`。
5. Diebold, F. X. & Mariano, R. S. (1995), *JBES*, DOI `10.1080/07350015.1995.10524599`。
6. National Stock Exchange of India, India VIX official computation methodology / white paper。

## 執行

```bash
uv run python experiments/k1717/k1717.py
uv run python scripts/experiment_gates.py run --path experiments/k1717
```

## 結果

正式 OOS 結果為 **NULL/MIXED；預註冊資訊 gate 未通過**，因此依規則跳過整個 `c / IndiaVIX` VT 模擬，沒有交易結論。

- 實際資料：NIFTY 2007-09-17 至 2026-07-15，共 4,617 個 close；India VIX 2008-03-03 至 2026-07-15，共 4,498 筆；US VIX 最後完整收盤為 2026-07-14。共同模型樣本 4,484 筆，排除 16 個 vendor-calendar gap targets。資料快照 SHA-256 為 `c8eb6b30189bbe7d74b2139f2e7320be40b7ebdb9ce7b5ae7fcab664aff64fca`。
- 正式 OOS：2020-01-01 至 2026-07-15，共 1,616 筆；共同嚴格正值 mask 評估 1,615 筆，包含 2020 與 2022。
- GJR-GARCH-X：India VIX QLIKE `1.4330`，US VIX `1.4898`；India 較低，但 canonical HAC DM `t=-2.8680`、`p=0.00418`、Holm `p=0.00418`，未達預註冊的 Harvey `t<-3` 門檻。DM 對 HAC lag 敏感：lag 0/1/5 為 `-3.541/-3.180/-3.005`，canonical lag 12 為 `-2.868`。
- HAR-style-X：India VIX QLIKE `2.0242`，US VIX `2.2768`；canonical HAC DM `t=-14.7271`、Holm `p<0.001`，通過該 family 的門檻。
- 年度穩定性不是單向一致：India GARCH-X 在 2020 與 2026 的 QLIKE 略差於 US，其餘 OOS 年較佳；HAR-X 則每個 OOS 年皆是 India 較低。
- 所有 21 個年度 GARCH optimizer run 都回報成功；但 India GARCH-X 的 `alpha` 每年都落在下界（2020/2025/2026 的 `omega` 也在下界），相應 unconstrained finite-difference gradient 偏大。這是必須保留的邊界解限制，不能把 optimizer success 解讀成參數識別毫無疑慮。
- 條件 Granger 診斷在固定 lag 5 下，India 與 US VIX 都拒絕「無預測資訊」的虛無假設（兩項 Holm `p<0.001`）；這不代表因果，也不取代正式 OOS gate。

結論強度只到：India VIX 在此快照與規格下呈現較好的平均 OOS loss，HAR 證據強，但 GARCH-X 未跨過預註冊的保守效果量門檻；不能宣稱它已穩健勝過 US VIX，更不能據此啟動或上架 VT 策略。完整數值、年度結果、fit diagnostics 與文獻 provenance 見 `k1717_results.json`；圖表為 `k1717_oos_qlike.png` 與 `k1717_annual_stability.png`。
