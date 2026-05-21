REJECT

BLOCKING 1. `§4.3`、`lines 150-155`；`§5.2`、`lines 212-233`
文稿將 quantile regression 明確寫成 `VIX_t` 對 `BTC RV_{t-1}` 的迴歸，且 `lines 89-91` 還宣稱「所有 forward-looking specification 都 lag 一天」；但你在文中自己標示的 source 並不支持這個敘述。對應實作 `experiments/k1025/k1025.py:283-312` 用的是同日 `VIX_t ~ BTC_RV_t`，且沒有文中宣稱的 `1,000` 次 bootstrap 標準誤。這不是小的實作偏差，而是直接改變識別意義：目前的「sign reversal / 8.5x tail amplification」至多是同日條件關聯，不是文稿聲稱的 spillover / predictability 證據。

BLOCKING 2. `§5.3`、`lines 238-256`；`§6.2`、`line 300`
文稿說 subperiod Granger 使用「AIC-selected lag length」，並據此建立「只有 2020 顯著」這個核心 regime-dependent 結論；但對應 source `experiments/k1025/k1025.py:714-717` 實際上是在 `lag=1..3` 中挑 `p-value` 最小者，不是 AIC。這是標準的 lag mining / specification search，且未做任何 multiple-testing 調整。既然 regime dependence 是本文三大主結論之一，這個問題足以單獨阻斷接受。

BLOCKING 3. `§4.5`、`lines 165-170`；`§7`、`lines 344-363`
文稿把 OOS 設定寫成「AIC 選 AR(p) + 1 個 lagged BTC RV、rolling re-estimation」；但 source `experiments/k1025/k1025.py:527-565` 實際跑的是固定 `VIX` lags `{1,2,3,5}`、加入兩個 BTC lags、而且是 expanding-window OLS。更糟的是 `2019-01-01` 同時落在 `is_data` 與 `oos_data`。因此本文拿來當第三個主貢獻的 forecastability null，並不是由文中所寫模型得到的結果。

MAJOR 1. `§4.1-4.2`、`lines 127-145`；`§5.1`、`lines 180-207`
Granger estimator 與 inference 的描述不準確。文稿聲稱使用 HAC/Newey-West/Andrews bandwidth，且把 asymmetric test 包裝為 Hatemi-J 框架；但 source `experiments/k1025/k1025.py:166-170, 246-267` 用的是 `statsmodels` 的 `ssr_ftest`，沒有文稿所述 HAC 設定；非對稱部分也不是 Hatemi-J 的 cumulative innovation decomposition，而是正負報酬各自滾動 RMS 再差分。`line 180` 把它稱為 “cumulative downside innovation” 亦與方法段不符。

MAJOR 2. `§4.4`、`lines 160-161`；`§5.3`、`lines 260-282`；`§6.1`、`lines 292-295`
Diebold-Yilmaz 與 DCC 的標示過度。source `experiments/k1025/k1025.py:331-367, 373-378, 447-449` 顯示你用的是 `statsmodels` `fevd()` 與明確寫出的 “EWMA correlation as DCC proxy”。前者不是文稿宣稱的 generalized FEVD，且結果依賴變數排序；後者不是 DCC。於是 `-76.9pp` 的 net receiver 數字與 Table `\ref{tab:dcc}` 的證據強度，都被文稿寫得比實際估計更強。

MAJOR 3. `§3.1-3.2`、`lines 85-91`
變數建構存在多重不一致：文稿寫的是 adjusted close、log return、`22` 日 rolling std、記號卻是 `RV^{(20)}`；source `experiments/k1025/k1025.py:58-74` 用的是 raw `Close`、simple return、`20` 日 rolling std。這不只是敘述瑕疵，而是直接影響估計量定義與可重現性。

MAJOR 4. `§1`、`lines 42-45, 47-51`；`§8.3`、`lines 390-404`
結論強度超過證據。即使暫時接受 reduced-form 結果，本文也沒有結構識別來支持 “retail-driven fear contagion”, “margin-cascade channel”, “stress-test calibration threshold”, “retail-investor protection externalities” 這類政策與機制語句。尤其在 OOS 完全無增益下，這些 policy claims 應大幅收斂。

MAJOR 5. `§2.2-2.3`、`lines 74, 78`；`§4.5`、`line 170`；`§7`、`lines 346, 363`
`Harvey et al. (2016)` 的 `|t|>3` 門檻被直接移植到 Diebold-Mariano forecast comparison，方法論上站不住腳。那篇文章處理的是 factor discovery / multiple testing in expected returns，不是 DM 檢定的有效臨界值。`line 363` 甚至寫成 “`p-value = 0.33 under the threshold`”，概念上就是錯的。

MINOR 1. `§5.3`、`lines 260-277`
Table `\ref{tab:dcc}` 的 Crisis regime 只有 `n=63`，但正文仍做了相當強的經濟詮釋；這裡至少需要更謹慎的語氣與不確定性說明。

MINOR 2. `§1`、`lines 51`；`§2.3`、`line 78`
“to our knowledge, the first such honest joint reporting” 這類 novelty claim 沒有系統性文獻比對表支撐，建議刪弱。

MINOR 3. `§3.2`、`line 91`；`§5.1`、`line 180`
術語前後不一致：方法段是「first-differenced directional RV series」，結果段卻寫成 “cumulative downside innovation”。對審稿人來說，這會加深對方法透明度的疑慮。
