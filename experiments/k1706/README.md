# K1706 — 美國 Tick Size Pilot 的 pre-spread 波動異質性

## 狀態

`FROZEN_BRIEF`（2026-07-16；任何門檻、窗口或主要檢定不得依結果改動）

### 結果前資料源修訂（保留稽核軌跡）

2026-07-16 在任何 outcome 估計前，原定 yfinance 批次請求遭 Yahoo 全站
rate-limit；仍上市股票也被錯報為 `no timezone`。程序於第 7 批中止，沒有寫出
價格 cache、沒有估計係數，也沒有看見 outcome。為排除當下 API 狀態與下市股
survivorship，價格源改成 `eliangcs/pystock-data` commit
`79fd5f4d805c8b45768225fe2a7c7eb1e5bd8cba`：這是每日開盤前保存的 Yahoo
Finance 全市場 OHLCV 快照，資料永久凍結於 2017-03-31，授權 CC BY-SA 4.0。
門檻、窗口、outcomes、treatment、RI、placebo 與 Holm family 完全不變。

首輪估計後的 code sanity check 發現 `rv5_bps2` 與 Amihud 報酬誤用 raw
close-to-close，會把拆股當成波動；首輪 JSON 隨即作廢，未進 review / knowledge。
修正版固定以 archive 的 `adj_close` 算 log return，raw OHLC 與 volume 仍分別
用於 range 及 dollar-volume。這是 corporate-action bug fix，不改 outcome family；
修正後完整重跑並覆蓋作廢結果。

第一次唯讀 Codex review（600 秒 timeout，未產生正式 verdict）進一步指出：這套
每日 archive 每次只保存兩日，逐日拼接的 `adj_close` adjustment factor 會在拆股
邊界跳變，不能視為同一時點回溯調整的連續序列。因此報酬程式再修成：一般日用
adjusted-close return；若 `log(adj_close/close)` 的日變化絕對值超過 0.2，則在
raw-return 與 adjusted-return 中取絕對值較小者，避免把 adjustment-factor 切換
機械地當成報酬。這仍是 outcome 計算 bug fix，門檻與檢定 family 不變。

同一次 review 也確認一次性 double demeaning 在少量 outcome missingness 下不等於
真正的 stock/date 兩向固定效果，並發現原 5 日 RV 會讓 10 月報酬滲入 11 月初。
最終版改用 alternating projections 將兩組固定效果吸收到 `1e-12` 收斂，且 5 日
rolling window 在 frozen pre/post 邊界各自重啟。審查者以替代重算驗證 range
方向與顯著性未被這兩項修正推翻；正式數字仍以修正後完整重跑為準。

第二次限時裁決給 `CONDITIONAL_PASS`（range-only），因當時版本雖已重啟 RV
rolling，單日 return 與 adjustment-factor change 仍在完整日期序列先算，11 月
第一筆因此跨越 October。最終修正把 return、adjustment-factor change、RV 三者
全部改在 `symbol × analysis_period` 內計算後重跑；本段保留該 blocking defect
與修復軌跡，不把舊 conditional verdict 冒充最終 PASS。

## 動機與差異化

美國 Tick Size Pilot 將約 1,200 檔小型股隨機分到三個測試組；控制組維持
1 美分報價與交易增量，三個測試組都改為 5 美分報價增量，其中 G2/G3
另受 5 美分交易增量約束，G3 再加 trade-at 規則。既有 SEC 研究發現平均
市場品質惡化，但 K1706 專門檢驗事前 spread 異質性：固定比較
`pre-spread < $0.10` 與 `pre-spread > $0.15`，中間區間一律排除，不可看結果
後改箱。

知識庫檢索（2026-07-16）未找到已完成、使用同一官方隨機分組及這兩個固定
spread 門檻的 VolPred 實驗；本題源自 `research_program.md` 的 K1706 backlog。

## 文獻先行

1. Hu, Hughes, Ritter, Vegella, and Zhang (2018), *Tick Size Pilot Plan and
   Market Quality*, SEC DERA. 其四個月 pre / 四個月 pilot DiD 是本實驗窗口的
   依據：<https://www.sec.gov/files/dera_wp_tick_size-market_quality.pdf>
2. SEC DERA (2019), *Tick Size Pilot Plan Threshold Analysis*. 該文以事前
   spread、規模、成交量、價格、depth 與波動配對，未找到可普遍改善品質的
   清楚門檻：<https://www.sec.gov/files/dera_wp_ticksize-thresholdanalysis.pdf>
3. Barardehi, Dixon, Liu, and Lohr (2022), *Tick Sizes and Market Quality:
   Revisiting the Tick Size Pilot*. 該文的「少於 2 個事前 ticks」與「超過 15
   個事前 ticks」結果直接 motivates 本實驗的 `<10¢` / `>15¢` 固定分層：
   <https://www.sec.gov/file/dera_wp_ticksize-pilot-revisitpdf>

制度與資料欄位另依 SEC Tick Size Pilot 官方頁、FINRA 官方 assignment file
及 Appendix B.I reporting specification。

## 凍結研究設計

### 樣本與資料

- 官方分組：FINRA `Tick_Pilot_Test_Group_Assignments.txt`；C、G1、G2、G3。
- 官方事前 spread：FINRA/CHX Appendix B.I 2016-09 月檔。依 SEC filter 保留
  `Order_Type <= 14`、非 special-handling、非 multiday 且 `WA_NBBO_Spd`
  與 order shares 有效的列；以 order shares 加權成每檔股票的 September
  平均 dollar NBBO spread。
- 價格／量：`eliangcs/pystock-data` 的未調整 OHLCV 日快照（上游為當時的
  Yahoo Finance），固定樣本窗 2016-06-01 至 2017-02-28。October 2016
  因分批上線而完全排除。逐日 archive、Git commit 與合併 SHA256 皆記錄。
- pre：2016-06-01 至 2016-09-30；post：2016-11-01 至 2017-02-28。
- 固定分層：`narrow = pre_spread < 0.10`；`wide = pre_spread > 0.15`；
  `0.10 <= pre_spread <= 0.15` 與缺值排除。

Appendix B.I 是官方市場品質表，但本研究公開歷史行情部分不是 TAQ/CRSP/MIDAS。
因此波動與流動性結論只對可由日 OHLCV 建立的代理量成立，不冒充 SEC 的
intraday MIDAS 指標。

### Treatment 與 outcomes

- 主要 treatment：G1/G2/G3 pooled（共同的 1¢→5¢ 報價增量）相對 C。
- 所有估計實際使用前一交易日可知的 assignment：程式必須明示
  `signal.shift(1)`；每檔第一筆因此剔除。這個 lag 不改變靜態隨機分組，
  但防止建立 same-day signal×outcome 路徑。
- 主要 outcomes（事前固定）：
  1. `rv5_bps2`：同一 frozen pre/post 期間內過去 5 交易日
     corporate-action-clean log return squared sum × 10,000；
  2. `range_bps`：`(High-Low)/Close × 10,000`；
  3. `log_dollar_volume`：`log(Close×Volume)`；
  4. `amihud_1e9`：`abs(corporate-action-clean log return)/(Close×Volume) × 1e9`。

`rv5_bps2` 是日線 realized-variance proxy，不宣稱等同高頻 RV。

### 推論

1. 每一 spread 層與 outcome 分別以 alternating projections 精確吸收 stock FE +
   date FE 的 DiD；標準誤按 stock cluster。
2. 主要 randomization inference：seed=42、999 次，在各固定 spread 層內
   保留實際 treated 數目後重新置換 assignment，以 stock-level post-minus-pre
   差計算雙尾 p-value。無法從公開 assignment file 還原全部官方選股 strata，
   故這是 spread-stratum-constrained RI，不宣稱完整重播官方抽樣程序。
3. 主要 family 為 2 spread 層 × 4 outcomes，共 8 個 RI p-values；以 Holm
   校正。
4. 另對每個 outcome 正式檢定 `DiD_narrow - DiD_wide = 0`；四個異質性
   RI p-values組成獨立 family 並做 Holm。這才是「兩層效果不同」的直接證據，
   不以一層顯著、另一層不顯著代替差異檢定。
5. Event study：以 September 2016 為 reference，估 June、July、August、
   November、December、January、February 的 treated×month 係數。
6. Placebo：僅用 pre 期，把 2016-08-01 設為假上線日，做同規格 DiD；8 個
   placebo p-values另做 Holm。

### 防錯規則

- seed 固定 42；不依結果改門檻、窗口、outcomes 或 multiple-testing family。
- October 全排除；rolling RV 只向後看，且在 pre/post 邊界重新暖機，不跨 10 月。
- `signal.shift(1)` 必須可由靜態檢查與執行 assertion 驗證。
- 先輸出描述統計、缺值與分組平衡，再估計；null result 如實保留。
- 原始大檔不提交 Git；提交聚合後的 spread 表、價格快照、來源 URL、SHA256、
  列數及取得時間，使 results 可逐 byte 追溯。

## 事前成功標準

- 最低可估樣本：每個 spread 層至少 40 檔 C 與 40 檔 pooled treatment，且
  每個股票 pre/post 各至少 20 個有效交易日。
- 結果層級：至少一個 outcome 的層內主要效果與對應窄減寬正式差異都在各自
  family 達 Holm-adjusted RI `p < 0.05`，且 placebo 不顯著，才稱為
  confirmatory heterogeneity evidence。
- 若只有未校正顯著、placebo 失敗、資料覆蓋不足或窄／寬層效果沒有正式差異，
  一律標為 exploratory / null，不做政策外推。

## 執行

```bash
uv run python experiments/k1706/K1706.py \
  --raw-bi /path/to/FINRA_CHX_MKTQUALITYSTATS_201609.dat.gzip \
  --price-repo /path/to/pystock-data
```

預期產物：

- `K1706_results.json`
- `data/pre_spread_official.csv`
- `data/ohlcv_daily.csv.gz`
- `data/source_manifest.json`
- `figures/k1706_did_forest.png`
- `figures/k1706_event_study.png`
