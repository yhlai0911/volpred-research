# K1716 — 0DTE 時代的日內與隔夜波動結構（daily-proxy diagnostic）

## 動機與差異化

Cboe 在 2022 年第二季把 SPX Weeklys 的到期日由週一、週三、週五擴到每個交易日：週二契約於 2022-04-18 上市，週四契約於 2022-05-11 上市。這提供一個比單純切 2022-Q2 更有辨識力的日曆對照：若每日到期選擇權主要改變盤中價格形成，週二／週四相對既有到期日的日內波動代理應在擴張後改變，而隔夜代理不一定同向。

本庫既有 overnight/intraday 研究多半研究報酬、VRP 或預測力；K1716 的差異是固定制度日期、以 weekday DiD 檢查波動「發生時段」是否重分配。它不是選擇權成交資料研究，也不宣稱辨識 dealer gamma 或 0DTE 成交量的因果效果。

## 文獻與制度背景（檢索於 2026-07-16）

1. Cboe 官方產品通知記載週二 SPXW 於 2022-04-18 上市、週四 SPXW 於 2022-05-11 上市；首批到期日分別為 2022-04-26 與 2022-05-19。來源：<https://cdn.cboe.com/resources/product_update/2022/Cboe-Options-Exchanges-to-List-Tuesday-and-Thursday-Expiring-Weekly-Options-on-SPX-option-symbol-SPXW_OW-003-.pdf>
2. Brogaard、Han、Won（SSRN 4426358，2026 revision）用 weekly-option staggered introduction 的 IV 設計，報告 0DTE 活動與較高波動相關：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4426358>
3. Adams、Fontaine、Ornthanalai（SSRN 4881008，2025 revision）用 2019–2023 intraday option volume 與到期日外生變異，報告 liquidity-provider intermediation 平均降低指數波動：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4881008>
4. Dim、Eraker、Vilkov（SSRN 4692190，2025 revision）發現 market-maker net gamma 平均為正，且與後續盤中波動負相關：<https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190>

相反方向的研究結果正是本實驗預註冊「雙尾、方向不先押」的原因；daily OHLC 無法裁決其機制。

## 資料與可追溯性

- 來源：Yahoo Finance，透過 `yfinance` 下載 SPY 未調整日 OHLCV。
- 請求期：2018-01-01 至 2026-07-16（右端不含）；實際交易日、樣本數與 SHA-256 寫入 `K1716_results.json`。
- 凍結快照：`data/SPY_ohlcv.csv`。結果重跑預設讀此快照，不會靜默抓新資料；只有顯式 `--refresh` 才更新。
- SPY 在研究期沒有 split，但仍刻意使用 raw OHLC，避免 adjusted Close 與 raw Open 混搭。所有價格一致性檢查都在腳本內。

## 觀察先於估計

日內代理採 Parkinson range variance：

`(log(High/Low)^2) / (4 log 2)`

隔夜代理採 `log(Open_t / Close_{t-1})^2`，全日 close-to-close 代理採 `log(Close_t / Close_{t-1})^2`。另計 `Parkinson / (Parkinson + overnight)` 的日內占比。四個 proxy 的 pre/post × weekday group 描述統計先寫入結果 JSON，再執行回歸。

## 預註冊方法

- treatment weekdays：週二、週四；control weekdays：週一、週三、週五。
- transition：2022-04-18 至 2022-05-18 不進主回歸；post 自首個週四到期日 2022-05-19 起。
- 回歸：`outcome ~ post + post×TueThu + weekday FE + lagged controls + month seasonality`。
- outcomes：log Parkinson variance、log overnight variance、log close-to-close variance、logit intraday share。
- 推論：Newey–West HAC，lag=`ceil(n^(1/3))`；10 日 moving-block pairs bootstrap 1,000 次，seed=42；四 outcome 的 HAC p-value 做 Holm 校正；另做 2021-05-19 與 2023-05-19 placebo break。
- 主要成功標準：log Parkinson 與 logit intraday share 的 interaction 同方向，兩者均滿足 Harvey `|t|>=3` 且四 outcome family 的 Holm p<0.05。否則報 NULL，不改門檻或斷點。

## Lookahead policy

本題是 contemporaneous structural diagnostic，不是預測或交易策略。即使如此，控制變數仍嚴格 point-in-time：五日 proxy variance 均值與絕對報酬均明確 `.shift(1)`；當日 outcome 不被拿來建當日 signal。沒有任何報酬策略或 same-day signal × return。

## 執行

```bash
uv run python experiments/k1716/K1716.py --refresh
uv run pytest experiments/k1716/test_k1716.py -q
uv run python scripts/experiment_gates.py run --path experiments/k1716
```

## 結論邊界

這只能稱為 SPY daily-OHLC proxy break diagnostic。2022-Q2 同時包含升息、熊市與波動 regime 變化；weekday interaction 雖比 raw pre/post 更能隔離共同 regime，仍沒有 0DTE 成交、OPRA、dealer position 或高頻 realized variance，不能宣稱 0DTE 造成波動增加／下降。圖 `k1716_intraday_share.png` 只呈現 proxy 的時間路徑，不替代正式檢定。

## 實際結果

凍結快照涵蓋 2018-01-02 至 2026-07-15，共 2,144 個交易日；OHLC 一致性檢查未剔除任何列，SHA-256 為 `4c76aabed84a838e25a05950a710b0f420a044b23e0cabe730b06011d0a10335`。排除 transition 並完成 lag 後，主回歸有 2,115 列。

主要 interaction 全數未達門檻：

- log Parkinson variance：係數 +0.0407，HAC t=0.591，raw p=0.555，Holm p=1.000，block-bootstrap 95% CI [-0.0863, +0.1776]。
- logit intraday share：係數 -0.0363，HAC t=-0.190，raw p=0.850，Holm p=1.000，block-bootstrap 95% CI [-0.4054, +0.3296]。
- log overnight variance：係數 +0.0651，HAC t=0.326；log close-to-close variance：係數 +0.1325，HAC t=0.624；兩者 Holm p 也都是 1.000。
- 2021 與 2023 placebo 的兩個日內 outcome interaction 同樣都不顯著（|t|≤0.803）。

因此預註冊成功條件未成立，裁決為 `NULL_PROXY_DIAGNOSTIC`。描述均值雖顯示 post 期間兩組的日內占比都較高（Tue/Thu 0.7040→0.7240；Mon/Wed/Fri 0.6850→0.7060），差中之差幾乎沒有可辨識訊號；不能把共同的 regime 移動歸因於每日到期選擇權。這個 NULL 也與文獻中正負方向皆有的機制證據相容，但不裁決任何一方。
