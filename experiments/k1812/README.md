# K1812 — Betting-Against-Beta 條件於前期已實現波動（beta anomaly 的波動之謎）

**Pool task**：K1726 · **Registry k_id**：k1812
**來源**：JFE (2025) *The volatility puzzle of the beta anomaly*；Frazzini & Pedersen (2014, JFE) *Betting against beta*
**產物**：`k1812.py` · `k1812_results.json` · `test_k1812.py` · `figures/` · `data/`

---

## 1. 研究問題與動機

Frazzini–Pedersen (2014) 的 **betting-against-beta（BAB）**：低 beta 股票的風險調整報酬高於
CAPM 預測（因槓桿受限投資人追逐高 beta，壓低其風險調整報酬）。JFE (2025)
*The volatility puzzle of the beta anomaly* 主張 **BAB 報酬條件於前期已實現波動 —— 平靜（低波動）
月之後 BAB 表現較好**。

本實驗**獨立以 yfinance 美股大型股月度資料重做 BAB**，並檢定核心命題：
**低波動月之後的 BAB Sharpe 是否較高**。

### 與既有知識庫的區別（新增了什麼）

知識庫既有 K47 / K71 / K77 只把 **Frazzini–Pedersen BAB 當作 VT（volatility targeting）策略
迴歸的一個控制因子**（"FF5+MOM+BAB 全控制後 VT alpha 仍正"），從未獨立重建 BAB 橫斷面組合、
也未檢定 vol-regime 條件。**K1812 是首次**在本平台：(a) 自建 rank-weighted、市場中性的 BAB
月度因子；(b) 檢定其報酬對**前期市場已實現波動 regime** 的條件性。這是 JFE 2025「波動之謎」的
獨立複現嘗試，不是舊 K 的重跑。

---

## 2. 資料

| 項目 | 內容 |
|---|---|
| 橫斷面 universe | 固定的 **83 檔**美股大型股清單（跨 9 大產業，皆 2004 前上市），寫死在 `k1812.py` 的 `UNIVERSE`。實際**納入 80 檔**；**排除 3 檔**（`BK / K / MRO`，yfinance 逾時/停牌，見 results `universe.excluded_tickers`）。 |
| 市場 | `^GSPC`（S&P 500 指數）日報酬 → 月度已實現波動 RV_market |
| 無風險利率 | yfinance `^IRX`（13 週美國國庫券殖利率，年化 %，與 FRED DGS3MO 3M T-bill 近乎等價）。**設計上原擬用 FRED DGS3MO，但本 compute 環境無法穩定連到 stlouisfed.org（讀取逾時），故改以 ^IRX 統一走 yfinance、更可重現。** |
| 樣本期 | 日資料 2004-01 起；BAB 月報酬 **2005-02 → 2026-06，共 257 個月**（首月受 full-12M warm-up 限制順延到 2005-02；未完成的 2026-07 被完成月 gate 排除） |
| 缺值處理 | beta 視窗要求**完整 12 個月**（`window_start ≥ 資料起點`）且 ≥200 交易日；報酬月要求 ≥15 交易日；每月要求 ≥20 檔股票才形成組合 |

資料檔快取於 `data/tickers/<TKR>.csv`（逐檔快取為唯一真相，re-run 只補缺檔），組合便利檔
`data/stock_prices.csv` / `market_price.csv` / `riskfree_irx.csv`。

### 資料誠實 caveat（最重要）

- **生存者偏誤（survivorship bias）**：yfinance 只回傳現存 ticker，universe 為固定的存活大型股
  清單 → **天生倖存者偏誤，不可完全消除**。存活的低 beta 股可能系統性有較高實現報酬，會同向
  膨脹 BAB 報酬；與 vol regime 的交互作用方向不確定。**結論強度須相應下修，視為 illustrative
  replication 而非 population estimate。**
- Universe 僅 80 檔大型股，遠小於 Frazzini–Pedersen 全 CRSP universe（含小型股，BAB 最強之處）。
  beta 離散度與 BAB 量級**不可與原文直接比較**。
- Beta = OLS rolling 12M + FP eq.15 收縮（0.6·β+0.4）；**未用** FP 原文兩段式（5yr 3-day 重疊相關
  估相關 + 1yr vol 估波動）。已註記差異。
- 月度已實現波動用月內日報酬 `sqrt(Σr²)`，未用日內高頻資料。
- rf 換算 `^IRX` 年化% → 日 (/252) / 月 (/12) 為近似（未精確處理 T-bill discount/quote convention）；
  對結果影響很小。

---

## 3. 方法

1. **Beta 估計**：每月月底，用**過去完整 12 個月**（要求 `window_start ≥ 資料起點`、≥200 交易日、
   嚴格 ≤ 月底）的日**超額**報酬對市場日超額報酬做 OLS 回歸（`cov/var`）估 `beta_i,t`。
2. **Beta 收縮（Frazzini–Pedersen eq.15，必要組成）**：`β_shrunk = 0.6·β_OLS + 0.4·1`。收縮朝 1，
   是 FP 方法的必要環節 —— 把腿 beta 遠離 0，避免 `1/β_L` 爆槓桿（見 §6 診斷）。收縮為 affine 單調，
   **不改排序**，只改腿 beta 量級。
3. **BAB 組合建構（Frazzini–Pedersen rank weighting）**：
   - universe 與**權重完全由形成期資訊**（有 valid beta）決定，**不看 t+1 報酬可得性**。持有月缺報酬
     一律 **fail-loud**（不靜默剔除 —— 靜默剔除會用未來資訊重塑權重）；survivor 樣本下從未觸發，
     `delisting_drops = 0`。真正下市須明訂 delisting-return 規則後才可納入。
   - 依收縮 beta 橫斷面排名 `z_i`，`z̄` = 平均排名，`k = 2/Σ|z_i − z̄|`。
   - 高 beta 腿 `w_H,i = k·max(z_i − z̄, 0)`；低 beta 腿 `w_L,i = k·max(z̄ − z_i, 0)`。兩腿各自加總為 1。
   - 腿 beta：`β_L = Σ w_L,i·β_i`、`β_H = Σ w_H,i·β_i`。
   - **各腿去/加槓桿到 beta=1** → `BAB_{t+1} = (r_L − r_f)/β_L − (r_H − r_f)/β_H`，
     ex-ante 市場中性（`(1/β_L)·β_L − (1/β_H)·β_H = 0`，程式驗證 max|.| = 1.1e-16）。
   - `r_f` 用**形成月底**可鎖定的 1 個月利率（非持有月底才知的利率），ex-ante 正確。
   - 逐月 rebalance，t 月底形成 → 持有到 t+1 月。
4. **Vol regime 分類**：`RV_market_t` = t 月市場日報酬 `sqrt(Σr²)`。**median split** 為主（低/高），
   另報 tercile 與 expanding-median（real-time）robustness。
5. **檢定**：
   - 全期無條件 BAB mean / annualized Sharpe / Newey-West HAC t（自動落後期 `floor(4·(n/100)^(2/9))`）。
   - 低 vol 月後 vs 高 vol 月後條件 Sharpe 差異的**顯著性主檢定 = circular block permutation**
     （見 §3.1，明確 impose H0，seed=42，10,000 reps）；效應量 95% CI 用 **stationary bootstrap**
     （Politis–Romano，同樣保留時間相依，非 null-imposed）。
   - 迴歸 `BAB_{t+1} ~ α + β·1{low_vol_t}`（HAC t）。

### 3.1 為什麼主檢定是 block permutation 而不是 i.i.d. permutation

條件 Sharpe 差的 H0 是「**regime label 過程**與 **BAB 報酬過程**獨立」。i.i.d. label permutation
在 impose 這個 H0 的同時，也把 label 自身的時間結構打散 —— 而 vol regime 是出了名地會**持續**：
本樣本 low-vol 指標 `acf(1) = 0.326`、平均連續段 2.95 個月、最長連續段 30 個月
（`conditional_median_split.serial_dependence_check.observed`）。用 i.i.d. 重排當 null，等於拿一個
「regime 不會持續」的世界來檢定，與資料生成過程不符。

**修法**：只重排 label、且以**整段連續區塊**搬動（`_circular_block_permute`：隨機環狀旋轉 → 切成
連續區塊 → 置換區塊順序），**報酬序列原地不動**。這保留 (a) 報酬自身的時間結構（完全不動）、
(b) regime 連續段（區塊內完整保留）、(c) 低/高月數（區塊置換不改 label multiset）。
Block 長度由**事前固定的規則**決定 —— `b = max(ceil(n^(1/3)), ceil(平均 regime 段長)) = max(7, 3) = 7`
個月，37 個區塊（`regime_block_length_rule`），**不是看 p 值挑的**；另在 `b ∈ {3,6,12,24}` 上報敏感度。

**這個修法確實有效，而且被量測留證**（`serial_dependence_check`，2,000 次抽樣的平均）：

| null 的產生方式 | label `acf(1)` | 平均連續段長 |
|---|---|---|
| 觀察值 | **0.326** | **2.95** |
| circular block permutation（**主檢定**，b=7） | 0.281 | 2.77 |
| 窮舉 circular shift（exact 對照） | 0.329 | 2.97 |
| i.i.d. label permutation（**僅對照**） | −0.005 | 1.99 |

i.i.d. 版把持續性歸零，block／shift 版留住了它。另附**窮舉 circular shift**（把整條 label 序列
環狀平移 k=1…n−1，共 256 個）作為**零調參、決定性**的 exact randomization 對照 —— 平移不改變
label 序列自身任何時間結構，是持續性保留最完整的 null，代價是 p 的解析度下限為 1/n。

程式對「月份索引必須逐月連續」做 fail-loud 檢查（`assert_contiguous_months`），因為 block／circular
重排的語意依賴這個前提。

## 4. Lookahead 政策（最高風險，已在代碼實現 + 自我驗證）

- **Beta 只用 ≤ 形成月底資料**，且要求完整 12M warm-up；報酬只用形成月**之後**的月份 → 兩者天然不重疊
  （測試 `test_no_same_month_lag`：panel 每列 `hold_month period = form_month period + 1`）。
- **universe 與權重完全由形成期資訊決定**（有 valid beta），不看 t+1 報酬可得性 → 無 future-availability
  lookahead；持有月缺報酬 fail-loud（不靜默剔除）。
- **regime 訊號 = 形成月（t）市場 RV，對齊到 t+1 月報酬**，代碼中以 `.shift(1)` 明確 lag：
  `low_vol_signal = regime.shift(1)`（以報酬月為索引，報酬月 m 的訊號 = 上一月 m−1 的 regime）。
- **程式內建 regime-alignment 交叉驗證**（fail-loud）：用 panel 的 `form_month` 逐月比對 shift(1) 訊號
  是否等於形成月 regime → results `invariants.regime_alignment_mismatches = 0`（257/257 月零 mismatch）。
  **此不變式只驗 regime 對齊**；beta 視窗上界、form/hold 不重疊、universe 選取、rf timing 由各自機制
  分別強制（見 §3）。
- **完成月 gate**：未涵蓋到 business month-end 的最後 partial 月（2026-07 只到 07-24）已排除，
  避免 partial-month 統計污染對外數字。
- baseline（無條件 BAB）與條件版**共用同一套 lag 與同一組合建構**，公平比較。
- 所有 bootstrap / permutation 固定 `seed=42`（窮舉 circular shift 為決定性，不需 seed）。
- full-sample median 分類使用了全樣本 vol 分佈（**非未來報酬**）；已另報 expanding-median real-time
  版做 robustness，結論一致。

## 5. 成功判準與結果

| 判準 | 結果 | 判定 |
|---|---|---|
| **baseline gate**：無條件 BAB 是否複製正的風險調整報酬 | mean ≈ **−0.11%/月**，Sharpe(ann) = **−0.074**，HAC t = −0.37 (p=0.711) | **弱／近乎為零**（略微為負但不顯著）—— 在此 80 檔倖存者大型股 universe，BAB premium 幾乎不存在，遠低於 Frazzini–Pedersen 在全 CRSP（含小型股）報告的水準；**本實驗未重建 FP 原文 universe，故不在此引用其數值做量化對比** |
| **主結論**：低 vol 月後 BAB Sharpe 是否顯著較高 | 低 vol 月後 Sharpe = **0.328**（n=125）vs 高 vol 月後 **−0.357**（n=132），差 = **+0.686**；**主檢定 block-permutation p = 0.114**；stationary-bootstrap effect-size 95% CI **[−0.135, 1.462]**（涵蓋 0）；regime 迴歸 β = 0.0099/月，HAC t = 1.59 (p=0.111) | **方向一致、marginally suggestive，但未達 5% 顯著（NULL on strict significance）** |
| 主檢定的穩健性（同一 median split） | 窮舉 circular shift（exact，零調參）p = **0.105**；block 長度 b ∈ {3,6,12,24} → p = 0.128 / 0.109 / 0.114 / 0.118；i.i.d. permutation（僅對照）p = 0.115 | p 對檢定形式與 block 長度**都不敏感**，全部落在 0.105–0.128，皆 > 0.05 |
| tercile robustness | 低 vol 0.260 → 中 0.003 → 高 −0.375（**單調遞減**） | 方向穩健、單調 |
| expanding-median (real-time) robustness | 差 = 0.627；block-permutation p = **0.164**（主）、circular shift p = 0.106、i.i.d. p = 0.158 | 與 full-sample median 一致，非 median-lookahead 產物；同樣不顯著 |

### 結論（誠實、不過度宣稱）

1. **方向與 JFE 2025 一致**：BAB 在**平靜月之後表現較好**（Sharpe 0.328 vs −0.357），且**跨 vol tercile
   單調遞減**。這與「beta anomaly 的波動之謎」預測相符。
2. **統計上 marginally suggestive 但未達 5% 顯著**：保留時間相依的主檢定 block-permutation p = 0.114、
   regime 迴歸 HAC t = 1.59 (p = 0.111)、expanding-median 版 p = 0.164；效應量 95% CI [−0.135, 1.462]
   涵蓋 0。在本樣本**無法在 5% 水準拒絕「BAB 條件 Sharpe 與前期 vol 無關」的虛無假設**，只能說有一致但
   不決定性的方向證據。
3. **「換成保留時間相依的檢定」在本樣本幾乎不改變 p（0.115 → 0.114），這是量測結果、不是事前假設。**
   原因可查：BAB 月報酬自身近乎無序列相關（`acf(1) = 0.070`），所以即使 regime label 高度持續，
   檢定統計量的 null 離散度也幾乎不變（block null sd 0.438 vs i.i.d. null sd 0.439）。
   **但這只能在做完正確檢定之後才知道** —— i.i.d. 版的 p 在此為「碰巧接近」，不是「本來就正確」。
4. **baseline 本身近乎為零**：在僅 80 檔倖存者大型股、2005–2026 期間，無條件 BAB premium 幾乎不存在
   （Sharpe −0.074，不顯著）。這與已知的「BAB 在大型股較弱、近十餘年減弱、且對建構方式敏感」相容。
   **因此本實驗是弱 baseline 下的條件性檢定**，主結論的強度受此與 survivorship caveat 雙重上限限制。
5. **不宣稱複現了 JFE 2025 的顯著性**；只報告：**點估計方向一致、tercile 單調、marginally suggestive
   (p ≈ 0.11) 但在本受限樣本未達 5% 顯著**。要有結論性證據，需全 CRSP（含小型股）+ 無倖存者偏誤資料
   + 更長樣本。

## 6. 開發與修正紀錄（供復現與審查）

> **紀錄規則**：本節只寫**當前 `k1812_results.json` 能程式化對上的數字**（括號內為 JSON 路徑），
> 被取代版本的中間數字**不留在此**（那些數字沒有任何現存 artifact 可核對，寫進來就是不可查證的
> 敘事）。`test_readme_numbers_match_results` 會逐條驗證本 README 的關鍵數字，對不上即測試失敗。

**A. beta 收縮是必要組成，不是選項**（`leverage_diagnostics`）

未收縮的低腿 ex-ante beta 會逼近 0：本樣本 `beta_L_raw` 最小值 **−0.0737**（2026-06，257 個月中有
**1 個月**為非正），而在 2026-05 的 `1/beta_L_raw` 高達 **11,367 倍**槓桿。根因是 rank-weighting 把低腿
權重集中到近零／負 beta 的防禦股，`1/β_L` 直接爆掉。**修法（非補丁，是 FP 的正確方法）**：加入
FP eq.15 收縮 `β_shrunk = 0.6·β + 0.4` → 收縮後 `β_L ∈ [0.356, 0.852]`、實際最大槓桿 **2.81 倍**、
最大單月 |BAB| = **17.85%**（2026-05），數字回歸合理。

**B. 完成月 gate**（`sample.last_complete_month` = 2026-06-30、`caveats`）

資料到 2026-07-24，7 月未走完。partial 月的月報酬與月 RV 都不可比，且會混進 regime 分組污染條件統計量。
**修法**：加完成月 gate（資料須達 business month-end 才算完整月），2026-07 被排除，樣本止於 2026-06。
判準用 pandas `BMonthEnd`（非交易所日曆），理論上月底逢交易所假日可能保守誤刪一個完整月；本樣本的
實際結果是正確排除 2026-07、保留 2026-06（`test_last_complete_month_drops_incomplete` 固定此行為）。

**C. 主顯著性檢定改為保留時間相依**（`conditional_median_split.primary_significance_test`）

原主檢定為 i.i.d. label permutation，它會把 regime 持續性打散（label `acf(1)` 0.326 → −0.005）。
**修法**：主判準改為 circular block permutation（b=7 月，10,000 reps，seed=42），並加窮舉 circular
shift 作 exact 對照、stationary bootstrap 作效應量 CI。完整說明與量測留證見 **§3.1**。
i.i.d. 版保留為對照組，在 results 內以 `"role": "COMPARISON ONLY"` 標記。
**本樣本的 p 幾乎不變（0.115 → 0.114），結論（不顯著）不變。**

**D. rf timing / warm-up / universe 選取**（`caveats`、`invariants`）

rf 用**形成月底**可鎖定的利率（缺值 fail-loud，不靜默填 0）；beta 要求完整 12M warm-up，首個 BAB 月
順延到 **2005-02**（`sample.bab_first_month`）；組合 universe 與權重**完全由形成期資訊決定**，持有月
缺報酬一律 fail-loud —— 靜默剔除等於用未來可得性重塑權重。survivor 樣本下從未觸發，
`sample.delisting_drops_total = 0`。

**E. provenance 由執行時產生**（`code_trace` / `reproduce_spec.json`）

results 由 canonical `finalize_experiment()` 寫出，同源產生 `reproduce_spec.json`
（schema `volpred.reproduce_spec.v1`）+ `results["code_trace"]`，pin entrypoint sha256 與輸入 hash。
spec 與 results 描述的是**同一份 bytes**（同一次 `trace_file()` 呼叫），因此「spec 事後手寫、
描述了另一個版本的程式」這個 bug class 在此不可能發生。

spec 的 `inputs` pin 的是**真正被讀取的來源** `data/tickers/<TKR>.csv`（逐檔快取）；三份 assembled
CSV（`stock_prices.csv` / `market_price.csv` / `riskfree_irx.csv`）是本次執行**寫出**的便利檔，
歸在 `outputs`。早期版本把寫出檔列為 inputs，等於把 provenance 的方向 pin 反了。

**F. Monte Carlo p 的下界**：所有 permutation p 用 `(exceedances+1)/(reps+1)`（Davison–Hinkley），避免 p=0。

**G. 資料快取**：逐檔快取（`data/tickers/<TKR>.csv`）為唯一真相 + 每檔下載即驗證（非空、非全 NaN），
每次重組合併檔。早期版本曾把整批下載（含失敗檔）存成 assembled cache，導致第二次執行讀到壞資料。

### 審查狀態（如實）

- **round-1 → FAIL**，2 條 blocking defect：(B) 主顯著性檢定未保留時間相依；
  (C) 本 README 當時宣稱經過多輪 Codex review、且引用了未留存於 results.json 的歷史數字 ——
  **該敘事不實，已刪除／改寫（即現在這一節）**。
- 修正 (B)：見 §3.1 與 §6C。修正 (C)：本節改寫，並加上 `test_readme_numbers_match_results`
  機械 gate（README 每個關鍵數字逐一對帳 results.json）與
  `test_readme_does_not_claim_unrecorded_review_rounds`（審查敘事須有 `review_verdict.json` 憑據）。
- **round-2 → FAIL**（報告：`codex_review_round2.md`）。(B) 判定為已正確落地；(C) 仍有兩處：
  README baseline 列引用了一個無法從 artifact 對帳的外部 benchmark 數字（已移除量化引用），
  以及 §8 把「檢核已通過」寫成既成事實（已改寫為「合併前必須成立的條件」）。
  同輪另記一條非阻斷觀察：reproduce_spec 的 `inputs` 當時列的是執行時**寫出**的 assembled CSV，
  而非真正的讀取來源 `data/tickers/*.csv` —— 已一併修正（見 §6E）。
- **當前結論一律以 `review_verdict.json` 為準**（由 `experiment_gates.py verdict-template` 產生，
  勿手抄）；各輪報告存於 `codex_review_round*.md`。

## 7. 檔案

- `k1812.py` — 可重現主腳本（含 `.shift(1)`、`seed=42`、FP 收縮、完成月 gate、regime-alignment 自我驗證、
  保留時間相依的 block-permutation 主檢定）。
- `k1812_results.json` — byte-traceable（`code_trace` pin entrypoint sha256）全部統計量、期間、n、regime
  切點、block-permutation／circular-shift／stationary-bootstrap／HAC 檢定、`serial_dependence_check`、
  `leverage_diagnostics`、caveats。
- `reproduce_spec.json` — canonical `volpred.reproduce_spec.v1` spec（entrypoint sha256 + 輸入 hash + canonical_result），由 `finalize_experiment()` 同源產生。
- `test_k1812.py` — 不變式測試（FP 權重、市場中性、收縮、bootstrap/permutation 決定性、block permutation
  保留持續性且對真效應有 power、月份連續性 fail-loud、完成月 gate、NW lag、results 不變式、
  no-same-month lag、regime shift 語意、**README 數字對帳**）。
- `figures/fig1_market_rv_regime.png` — 市場月 RV 時序 + median 切點。
- `figures/fig2_conditional_bab_cumret.png` — 無條件 vs regime 條件的 BAB 累積報酬。
- `figures/fig3_sharpe_by_regime.png` — BAB annualized Sharpe by prior-vol regime。
- `data/` — 逐檔價格快取 + BAB panel + regime joint（診斷用）。

## 8. 收工檢核（可重跑；以下是合併前**必須成立的條件**，不是對某次執行的事後轉述）

- `uv run --extra dev pytest experiments/k1812/test_k1812.py -q` → 必須全數通過。
  其中 `test_readme_does_not_claim_unrecorded_review_rounds` 以 `review_verdict.json` 是否存在
  作為「README 得以提到 review round」的憑據 —— 該檔案因此是本檢核的**前置條件**，
  在它寫入之前這條測試會紅，這是 gate 的設計行為而非缺陷。
- `uv run python scripts/experiment_gates.py run --path experiments/k1812` → 必須 PASS（4 methodology gates）。
- `uv run python scripts/check_experiment_artifacts.py check --path experiments/k1812` → reproduce_spec.json 須已滿足；
  knowledge entry 另計（**MAIN THREAD ONLY，K1259：worktree agent 禁寫 knowledge.json**，由收件 fire 寫）。
- Codex primary-path review 的**當前結論一律以 `review_verdict.json` 為準**（由 gate
  `verdict-template` 產生，勿手抄）；審查歷程見 §6「審查狀態」，各輪報告存於 `codex_review_round*.md`。
