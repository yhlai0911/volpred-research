# K1695：VT Trend-Following Table 5 國際 13 市場 canonical 重跑

> ## ⚠️ 2026-07-15 更正：招牌結論已撤回
>
> **舊結論（2026-07-12 版）**：「12/VIX overlay 在 13 個國際股市提供 drawdown protection，
> 平均 ΔMDD +27.50 pp（inception-aware）／+12.61 pp（common），13/13 市場為正，
> 通過預註冊 gate（`kill_triggered=false`）。」
>
> **這個結論是錯的。它衡量的是「少冒險」，不是「會擇時」。**
>
> 12/VIX 平均只放 ~73% 股票，實現波動只有 buy-and-hold 的 **0.52–0.68 倍**，13/13 市場全部
> 落在 `.claude/rules/experiments.md` 的 20% 門檻之外。Raw MDD **不是 scale-invariant**：
> 任何人只要把部位等比例縮小，回撤就機械性變淺。決定性證據是一個**完全不看 VIX、
> 只固定放同樣平均倉位的常數減碼策略** —— 它拿到 +10.68 pp（common）／+16.20 pp
> （inception）的 raw「保護」、13/13 市場為正，而它的同曝險 gap 是 **+0.01 / −0.06 pp**。
> 招牌數字的八成以上，一個對 VIX 一無所知的策略就能複製。
>
> | 口徑 | inception-aware | common (2012–2026) |
> |---|---:|---:|
> | raw ΔMDD（原報告） | +27.50 pp（13/13 正） | +12.61 pp（13/13 正） |
> | **同曝險 ΔMDD** | **+4.96 pp（12/13 正）** | **−0.87 pp（7/13 正）** |
> | 對照自身 circular-shift null | p = **0.212** | p = **0.559** |
> | Holm 存活市場數 | 0 / 13 | 0 / 13 |
>
> **新結論的強度邊界（不可超譯）**：
>
> - **成立**：raw 13/13 結果可完整重現，且它是 exposure artifact。
> - **成立**：common 樣本的同曝險 gap 與「無擇時 null」無法區分（−0.87 pp vs null 平均 −0.68 pp）。
> - **不成立**：不可宣稱「波動率擇時有害」。common 的點估計為負，但落在自己 null 的正中央 ——
>   那是**沒偵測到效果**，不是**偵測到負效果**。
> - **不成立、但也未被推翻**：長樣本上一個溫和的正效果。inception 同曝險 gap = +4.96 pp、
>   12/13 為正，但 p=0.212 不拒絕 null、Holm 0/13 存活。它主要來自 2008 一次危機窗口 ——
>   **一次危機不是一個檢定**。
>
> 原始 raw 數字**全部保留**（那是真實計算，且回溯更正必須能對照已發表的數字），
> 但任何一個都不得單獨作為結論。`decision.kill_triggered` 現為 `true`，
> `claim_status='retracted'`。詳見下方「更正後的推斷規格」與「結果」。
>
> **連帶影響**：paper `vt-trend-following` 的 Table 5 與第三項 contribution（international
> drawdown protection）、以及 feed 上引用此結果的已發佈文章，都需依同曝險口徑回溯更正。

## 動機與差異化

`paper/vt-trend-following` 的 Table 5 是 mixed-vintage chimera：13 個市場列仍是舊值，Average／相關係數卻換成 K1178，導致列平均與表尾不一致。K1178 也不是可直接沿用的 canonical pipeline：它 live fetch、`auto_adjust=True`、每日調整 12/VIX、固定 4% risk-free、零交易成本，最後用把 13 市場當 iid 的 one-sample t-test。

K1695 一次產出 Table 5、Figure 2 與 abstract 所需的全部數字，但不修改論文 `.tex`。本實驗與 K1178 的差異是：

- 資料先 pin，再運算；重跑預設不得連網。
- `auto_adjust=False`，用 Close + distributions 明示重建 total return。
- 前一個 calendar month-end VIX 決定下一整月權重，月初再平衡、月內持有。
- 10 bps 按實際 one-way turnover 扣除。
- Sharpe 使用 prior-day 每日 `^IRX` proxy，不用 flat 4%。
- 推斷只在 13 市場共同日期進行，BH／VT 共 26 欄使用同一組 date-block indices 同步重抽。

相關知識：K1178（舊 Table 5 canonical 嘗試）、K1192／K1376（MDD block-bootstrap precedents）。

## Data & Methodology

### 方法論類型

`empirical descriptive`，另以 dependence-preserving bootstrap 做平均 ΔMDD 的推斷。VIX sensitivity 與 ΔMDD 的相關是描述性關聯，不做因果或 pricing-mechanism 宣稱。

### 資料來源與固定期間

- Source：Yahoo Finance，透過 yfinance；僅第一次以 `--refresh-data` 取得。
- Requested range：2004-01-01（inclusive）至 2026-04-01（exclusive），paper sample 最後一天固定為 2026-03-31。
- Required series：13 檔美國掛牌 country/region ETFs、`^VIX`、`SHY`、`^IRX`。
- Snapshot：`data/yfinance_raw_snapshot.csv.gz`；manifest 固定 SHA256、fetch time、yfinance version、每檔 row/date/action counts。
- Fetch parameters：`auto_adjust=False, actions=True, repair=False`。

13 市場：

| Region | Tickers |
|---|---|
| Developed (7) | EFA, EWJ, EWG, EWU, EWA, EWC, VGK |
| Emerging (6) | EEM, FXI, EWZ, INDA, EWT, MCHI |

K901 的正確資產差異是移除 `SPY/EWH/EWY`、加入 `VGK/INDA/MCHI`；EWC 原本就存在，不能再寫成「K901 缺 EWC」。

### Total return 與 proxy

ETF／SHY total return：

```text
r_t = (Close_t + Dividends_t + CapitalGains_t) / Close_(t-1) - 1
```

Yahoo historical Close 已做 split normalization，因此 `Stock Splits` 只保留作 audit，不能再乘一次。`Adj Close` 不進模型，只作 hard cross-check：一般 price-only 日期最大誤差不得超過 1 bp；distribution 日期因 Yahoo actions 金額取整，門檻為 30 bps。

第一次正式 data gate（尚未計算任何策略結果）原先使用單一 5 bp 門檻，於 EFA 2012-06-21 的除息日以 5.96 bps 停止。全 14 檔 ETF/SHY 診斷顯示：非 distribution 日最大誤差 0.225 bps，所有較大差異都在除息日；標準公式 `D_t / Close_(t-1)` 的誤差也一致小於以 ex-date close 為分母的替代公式。故在看見任何策略結果前，把 provider reconciliation gate 修訂為上述雙門檻；action-day 最大診斷值為 22.58 bps，仍低於 30 bps。首次 fail 完整保留在 `run_preflight_failure.log`，不以放寬單一門檻掩蓋。

Proxy 限制：

- SHY 是可投資 cash sleeve，含 duration／tracking risk，不是 frictionless risk-free asset。
- `^IRX / 100 / 252` 是 13-week bank-discount yield 的日頻近似，只用於 Sharpe excess-return benchmark；先把過去 observation forward-fill 到 return-date calendar，再 `shift(1)`。
- Country ETFs 含 fund fee、tracking error、US trading-calendar effect，不能等同當地 cash index。

### 策略與時間對齊

```text
target_weight(month m) = min(12 / VIX_last_day(month m-1), 1)
VT = target × ETF + (1-target) × SHY
cost = 0.001 × |target_weight - pretrade_equity_weight|
```

- 程式以 `PeriodIndex('M')` 先算 month-end VIX，再明確 `signal.shift(1)` 映射到下一整月。
- 月內不 daily rebalance；資產與 SHY 權重隨報酬漂移，到下個月第一個共同交易日才恢復 target。
- 首次 allocation 不扣 turnover cost；之後每次實際權重變更均扣。
- BH 與 VT 每市場使用完全相同日期；首期 signal 不用 `fillna(1)`。
- Synthetic gate 驗證 December→January、January→整個 February，不接受 K1192 類 double-month lag。

### 兩套樣本

1. `inception-aware`：各 ETF 從 2007-01-01 後第一個有效 aligned return 起算；INDA／MCHI 不補不存在的歷史。
2. `common-period robustness`：從 2012-01-01 後找 13 市場第一個共同有效交易日，所有 BH／VT return vectors 必須同一日期。

兩套結果分欄回報；common-sample CI 不可掛到 inception-aware average 旁而不標樣本差異。

### 原始預註冊規格（已作廢，保留供稽核）

- Primary：joint circular stationary bootstrap，B=10,000、mean block=252 trading days、seed=42、90% percentile CI。
- Sensitivity：mean block = 63／126／504，每個 B=3,000，seed 在執行前固定。
- 每個 replication 同步重抽 13 個 BH + 13 個 VT return columns；不串 asset-day、不各市場獨立抽、不抽 price/VIX levels。
- 不再報 iid cross-sectional one-sample t-stat；per-market 13/13 count 只屬描述性。
- 舊 kill 標準：任一 observed sample 少於 13/13 ΔMDD > 0，或 common-sample average ΔMDD 的 primary 90% CI 含 0。

**為什麼作廢**：舊 kill 標準 gate 在 **raw ΔMDD** 上，而 raw ΔMDD **不是 scale-invariant**。
12/VIX 在 13/13 市場的實現波動都只有 BH 的 0.52–0.68 倍，兩個條件靠「單純減碼」就自動滿足 ——
連完全不看 VIX 的常數減碼策略都能 13/13 通過同一個 gate。**這個 gate 不可能 fail，所以它從來
沒有檢定過那個主張。** bootstrap 的抽樣設計本身沒問題（依然沿用），問題在於它抽的是錯的統計量。

### 更正後的推斷規格（2026-07-15）

所有 drawdown 比較一律經過 repo canonical `volpred.stats.drawdown.compare_max_drawdown`，
不在本檔重寫（自己重寫一份正是原本出事的方式）。

1. **統計量**：同曝險 ΔMDD = `MDD(VT) − MDD(λ · BH)`，λ = `vol(VT)/vol(BH)`，
   使 benchmark 帶著與 VT **完全相同的實現波動**。純減碼在此統計量上得分恰為 0
   （已由 `test_pure_delevering_earns_a_zero_exposure_matched_gap` 機械鎖住）。
2. **Primary null：circular-shift randomization（exact）**。把 12/VIX 的**月度權重路徑**
   在日曆月空間上循環位移，窮舉**所有相位**（common 170 個月、inception 231 個月），
   對每個相位重跑完整策略（含 SHY 現金腿與 10 bp 成本）重算同曝險 gap。
   循環位移**完全保留權重的數值與自相關**（它是時間的一個排列），**只破壞它與報酬的對齊**。
   **每個市場位移的是它自己實際交易過的月份**（不是全體 union span）—— 否則 INDA／MCHI
   （2012／2011 才成立）會被餵進它們從未經歷過的 2008 低權重，灌大權重離散度、灌高 null。
   位移量 s 在 13 個市場間**共用**，故日曆位移一致，跨市場相依性保留 ——
   這正是讓「13/13」看起來很厲害的那個相依性。
   位移群窮舉且含 identity（shift 0 = 觀察路徑），故 exact randomization p =
   `#{gap_s ≥ gap_obs} / n_shifts` → **不抽樣、不需 seed、完全確定性**。
   （另附 Monte-Carlo 慣例的 `/(n+1)` 版本，僅供與 K1265b 對照；那個慣例屬於**抽樣**的
   reference set，用在窮舉群上會讓 p 偏小約 0.6%，方向是 anti-conservative。）
3. **為什麼必須有 null，而不是跟 0 比**：正的同曝險 gap 是**必要但不充分**條件 ——
   匹配「無條件波動」並沒有匹配到「波動的路徑」。把策略設計成時機**完全相反**（動盪時加槓桿）
   一樣可以拿到正 gap。**唯一誠實的判準是 gap 對照它自己的相位隨機化 null。**
4. **多重比較**：13 個 per-market null p-value 走 Holm step-down，α=0.10。
5. **CI**：同一組 joint stationary bootstrap resample **同時**產出 raw 與同曝險兩個 CI
   （λ 在每個 replication 內重估，它是統計量的一部分而不是常數）→ 兩者差異純粹來自統計量本身。
6. **No-timing 參照策略**：固定權重 = 該市場 VT 自己的平均目標倉位，同現金腿、同再平衡、同成本，
   **完全不看 VIX**。它是把 null 假設具體化成一個可以真的跑出來的策略。

**更正後的 kill 標準**：主張要存活，必須 (a) 同曝險 joint-bootstrap CI 不含 0，**且**
(b) **兩個樣本**都在 10% 水準拒絕 circular-shift null，且至少 1 個市場通過 Holm。
否則 `decision.kill_triggered=true`、`claim_status='retracted'`。

實際結果：(a) 失敗（CI = [−7.02, +3.59] 含 0），(b) 兩個樣本都失敗（p=0.559 / 0.212，Holm 0/13）
→ **kill triggered，第三項 contribution 撤回**。

## 文獻

1. Moreira, A., & Muir, T. (2017). Volatility-Managed Portfolios. *Journal of Finance, 72*(4), 1611–1644. https://doi.org/10.1111/jofi.12513
2. Harvey, C. R., Hoyle, E., Korgaonkar, R., Rattray, S., Sargaison, M., & Van Hemert, O. (2018). The Impact of Volatility Targeting. *Journal of Portfolio Management, 45*(1), 14–33. https://doi.org/10.3905/jpm.2018.45.1.014
3. Cederburg, S., O'Doherty, M. S., Wang, F., & Yan, X. (2020). On the Performance of Volatility-Managed Portfolios. *Journal of Financial Economics, 138*(1), 95–117. https://doi.org/10.1016/j.jfineco.2020.04.015
4. Politis, D. N., & Romano, J. P. (1994). The Stationary Bootstrap. *JASA, 89*(428), 1303–1313. https://doi.org/10.1080/01621459.1994.10476870

## 執行

第一次 pin 資料並完整跑：

```bash
uv run python experiments/k1695/k1695.py --refresh-data | tee experiments/k1695/run.log
```

之後完全讀本地 snapshot 重現：

```bash
uv run python experiments/k1695/k1695.py | tee experiments/k1695/run.log
```

只有明確接受新 vintage 時才能覆蓋：

```bash
uv run python experiments/k1695/k1695.py --force-refresh-data
```

測試：

```bash
uv run --with pytest python -m pytest -q experiments/k1695/test_k1695.py
```

## 產物

| 檔案 | 用途 |
|---|---|
| `k1695.py` | 唯一 canonical 實驗腳本 |
| `k1695_results.json` | 完整 machine-readable 結果與 stable JSON paths |
| `table5_rows.csv` | inception-aware Table 5 rows |
| `common_sample_rows.csv` | 13 市場共同樣本 robustness rows |
| `figure2_data.csv` | Figure 2 唯一資料源 |
| `figure_cross_asset.png` | 由 `figure2_data.csv` 同次生成的真實圖 |
| `figure_exposure_matched.png` | **更正圖**：raw vs 常數減碼 vs 同曝險 ΔMDD，以及 170 個相位的 null 分佈 |
| `circular_shift_null_gaps.csv` | 全部 170 個 circular-shift 相位的 per-market 與 joint 同曝險 gap |
| `data/yfinance_raw_snapshot.csv.gz` | pinned raw/actions snapshot |
| `data/snapshot_manifest.json` | provenance + SHA256 |
| `data/paired_common_returns.csv.gz` | joint-bootstrap 的 26 欄 paired returns |
| `test_k1695.py` | timing／corporate-action／bootstrap／atomic-write gates |
| `run.log` | canonical run console receipt |
| `run_preflight_failure.log` | 首次 5 bp 單一門檻 fail receipt（策略結果尚未計算） |
| `run_runtime_failure_target_weight.log` | 第二次 run 的 Series schema naming fail receipt（bootstrap 前） |

## 結果

資料 snapshot 未動：SHA256 `38cb3a0bd286cbf27992caefda6b67fb558f460c125261366060e9c1ec7f7751`（2026-07-12 pin）。
2026-07-15 的更正**沒有重抓任何資料、沒有改動策略邏輯**，只換了「拿什麼統計量當結論」。
證據：raw joint-bootstrap 90% CI 重跑後仍是 **[+4.22, +19.30] pp**，與 2026-07-12 發表的數字逐位吻合
→ **差異來自口徑，不是 bug**。

### 曝險診斷（這是整份更正的地基）

| 樣本 | VT/BH 實現波動比 | 超過 20% 門檻的市場數 | VT 平均股票倉位 |
|---|---:|---:|---:|
| inception-aware | 0.52 – 0.66（平均 0.56） | **13 / 13** | ~73% |
| common (2012–2026) | 0.61 – 0.68（平均 0.65） | **13 / 13** | ~73% |

13/13 市場全部觸發 `exposure_mismatch=True`。依 `.claude/rules/experiments.md`，此時 raw MDD 差異
**不可單獨報告**，更不可當成風險管理有效的證據。

### Raw vs 同曝險：兩個口徑並列

| 指標 | inception-aware | common (2012–2026) |
|---|---:|---:|
| Markets with **raw** ΔMDD > 0 | 13 / 13 | 13 / 13 |
| **Raw** average ΔMDD（**不可單獨引用**） | +27.50 pp | +12.61 pp |
| Markets with **同曝險** ΔMDD > 0 | **12 / 13** | **7 / 13** |
| **同曝險** average ΔMDD | **+4.96 pp** | **−0.87 pp** |
| DM / EM 同曝險 average | +7.48 / +2.01 pp | −1.03 / −0.67 pp |
| Markets with ΔSharpe > 0 | 1 / 13（EWJ） | 0 / 13 |
| Average ΔSharpe | −0.044 | −0.091 |
| Average annual CAGR cost（VT−BH） | −1.17 pp/year | −2.18 pp/year |

**No-timing 參照策略**（固定倉位 = VT 自己的平均倉位，完全不看 VIX）：

| 指標 | inception-aware | common |
|---|---:|---:|
| raw ΔMDD | **+16.20 pp（13/13 正）** | **+10.68 pp（13/13 正）** |
| 同曝險 ΔMDD | **−0.06 pp** | **+0.01 pp** |

一個對 VIX 一無所知的策略，拿走了 raw「保護」的 59%（inception）／85%（common），
而它的同曝險 gap 是零。**這就是 artifact 的直接證明。**

### 正式推斷：joint bootstrap（共同樣本 2012-02-07 – 2026-03-31，N=3,557）

同一組 resample、同一個 seed=42、B=10,000，同時算兩個統計量：

| 統計量 | 90% joint-bootstrap CI | median | P(average ≤ 0) | P(all 13 > 0) |
|---|---:|---:|---:|---:|
| raw ΔMDD（audit trail） | [+4.22, +19.30] pp | +11.82 | 0.0006 | 0.843 |
| **同曝險 ΔMDD（結論用）** | **[−7.02, +3.59] pp** | −1.74 | 0.708 | 0.010 |

Block-length sensitivity（63 / 126 / 504 日）下，同曝險 CI **全部含 0**：
[−6.79, +4.59]、[−6.86, +4.10]、[−6.09, +3.02]。raw CI 的 lower bound 則全部為正 —— 兩個口徑
在 block 長度上都很穩定，它們只是**在衡量不同的東西**。

### Primary null：circular-shift randomization（窮舉所有相位，確定性）

每個市場循環位移**自己實際交易過的月份**（共用同一個位移量，故日曆位移在 13 市場間一致）。
p 是窮舉整個位移群的 **exact randomization p** = `#{gap_s ≥ gap_obs} / n_shifts`。

| 樣本 | 相位數 | 觀察值 | null 平均 | null p95 | **p（單尾）** | Holm 存活 |
|---|---:|---:|---:|---:|---:|---:|
| common | 170 | −0.87 pp | −0.68 pp | +2.45 pp | **0.559** | 0 / 13 |
| inception-aware | 231 | +4.96 pp | +0.59 pp | +8.55 pp | **0.212** | 0 / 13 |

per-market 最小的未校正 p 是 EWJ（inception, p≈0.095）與 EFA（common, p≈0.199）；
Holm 在 α=0.10、family=13 下的第一階門檻是 0.0077 → **0/13 存活**，兩個樣本皆然。

### 但 raw 統計量**確實**拒絕了這個 null —— 而這正好證明了問題所在

必須把這個數字正面講清楚，因為它是**唯一**能被拿來救回原結論的證據：

| 樣本 | raw 觀察值 | raw null 平均 | **raw p** |
|---|---:|---:|---:|
| common | +12.61 pp | +9.07 pp | 0.106（不拒絕） |
| **inception-aware** | **+27.50 pp** | **+15.22 pp** | **0.039（在 α=0.10 下拒絕）** |

**所以 12/VIX 不是什麼都沒做。** 但它做的是什麼，可以直接量出來 —— 看觀察到的那個相位，
在它自己權重路徑的**所有相位**當中，實現波動排第幾：

| 樣本 | 觀察相位的 VT/BH 波動比 | 相位 null 平均 | **排名** |
|---|---:|---:|---:|
| common | 0.651 | 0.742 | **2 / 170**（第 1.2 百分位） |
| inception-aware | 0.560 | 0.698 | **1 / 231**（最低的那一個） |

觀察到的相位，是它自己所有相位中**實現波動最低的那一個**。這是真的、也不意外：
**VIX 確實能預測波動**，所以 12/VIX 真的會在真正動盪的月份減碼。這是訊號的真實性質。

**但那是「降低風險」，而 raw MDD gap 獎勵的正是「降低風險」。**
降低風險 ≠ 在**同樣風險**下回撤更淺 —— 而被撤回的那項 contribution 主張的是後者。
把降風險的部分扣掉（= 同曝險口徑），什麼都不剩（p=0.212 / 0.559，Holm 0/13）。

換句話說：raw null 的拒絕，不是原結論的救生索，它是**同一個 artifact 在 null 內部再現一次**。

### 結論（強度邊界已標明）

1. **13/13 raw ΔMDD 改善是真的，但它是 exposure artifact** —— 衡量的是少冒險，不是會擇時。
2. **12/VIX 確實會降低風險，這一點成立且顯著**：觀察相位的實現波動在自己所有相位中排第
   1/231（inception）、2/170（common）；raw 統計量在長樣本上也確實拒絕相位 null（p=0.039）。
   **但 raw MDD gap 獎勵的就是降風險** —— 降風險 ≠ 同風險下回撤更淺，而後者才是被撤回的主張。
3. **common 樣本：同曝險下與無擇時 null 無法區分**（−0.87 pp，p=0.559）。
4. **不可宣稱擇時有害**：點估計為負但落在 null 正中央 = 沒偵測到效果，不是偵測到負效果。
5. **inception 樣本留下一個未解的可能**：同曝險 +4.96 pp、12/13 為正，但 p=0.212 不拒絕 null、
   Holm 0/13。它主要來自 2008 危機窗口。**這既不能拿來救回原結論，也不能被當成已被推翻。**
   要把它變成主張，需要的是**多次獨立危機**的樣本外證據，不是同一次危機的更多切法。
6. Sharpe／CAGR 成本結論不變（−0.044／−0.091 ΔSharpe；−1.17／−2.18 pp/year）。
7. 「VIX sensitivity 橫斷面預測保護幅度」仍只在 inception-aware 成立，common 不支持 ——
   而且它預測的是 **raw** ΔMDD（即曝險本身），所以這個關聯的解釋力也隨 artifact 一併降級。

## 驗證紀錄

### 2026-07-12 原始 run

- Fresh-context pre-run review：初始 FAIL（MDD 漏 initial NAV、snapshot coverage 不 fail closed）→ 修後 PASS。
- Synthetic tests：11/11 PASS；ruff PASS；`git diff --check` PASS。
- Results verification：artifact SHA256、Table 5 / common rows aggregation、paired-return MDD、kill flag 全部從 JSON/CSV 獨立重算 PASS。
- Primary B=10,000 bootstrap 從 pinned paired panel 以 seed=42 重算，CI／median／mean／tail probability 在 CSV round-trip tolerance `1e-12` 內一致。
- **這一輪 review 沒有檢查曝險。** 它驗證了每個數字算得對，沒有問「這個數字能不能支撐那個主張」。
  這正是這個 bug class 的特徵：**算術全對，結論全錯。**

### 2026-07-15 更正 run

- 主線程（hourly-02）以 repo canonical `compare_max_drawdown` 讀 pinned
  `data/paired_common_returns.csv.gz` **獨立重跑**，先確認 raw +12.61 pp 與 common −0.87 pp
  → 差異來自口徑不是 bug。證據：`storage/ops/k1695_exposure_artifact_verification.md`。
- **Fail-closed 等價性斷言**（跑在每次 run 裡，不是一次性檢查）：
  - 向量化的同曝險統計量必須與 canonical `compare_max_drawdown` 在 13/13 市場上逐一相符
    （`assert_vectorized_matches_canonical`，tol 1e-12）；
  - null 的 scenario simulator 在 shift=0 時必須逐點重現 canonical scalar simulator 的 VT 路徑
    （tol 1e-12）；
  - shift=0 的權重必須逐點等於觀察到的權重路徑。
  三者任一不符即 raise，不是 warn。
- 測試：**19/19 PASS**（新增 8 個，含「純減碼的同曝險 gap 必須為 0」的 property test、
  「results.json 不得在沒有 exposure 欄位的情況下報 raw MDD」的**規則** gate，以及與它分開的
  **本次結論 snapshot**。兩者刻意拆開：把結論寫進 gate 會擋住未來誠實的翻案）。
- `uv run python scripts/experiment_gates.py run --path experiments/k1695` → **PASS**。
- MDD scale-artifact ratchet：k1695 的 6 個 baseline 站點修好 4 個
  （`_summary`／`joint_mdd_bootstrap`／`run_experiment`／`main` 由 RAW_COMPARISON → NORMALIZED）；
  ratchet test 14 passed。剩 2 個（`compute_metrics` 單序列指標、一個舊 bootstrap 測試）仍在 baseline。
- 決策數字全部由 f-string 從當次 run 的實際值插值，**沒有任何硬編數字寫進敘述**
  —— 敘述不可能與自己的結果漂移。

#### 獨立審查（fresh-context reviewer，2026-07-15）→ CONDITIONAL_PASS → 兩個 blocking defect 已修

primary-path Codex review 因逾時未在本班內收斂，已 enqueue 到 compute_queue
（`compute-tmp-k1695-codex-review-job-sh-1784066358`，prompt 存於
`storage/ops/k1695_codex_review_prompt.txt`，輸出將落在 `codex_review_20260715.md`）。
依 `.claude/rules/experiments.md` 的 fallback path，本班先跑 fresh-context reviewer 取得同步裁決。
**注意：subagent PASS ≠ primary-path Codex PASS（K1259 教訓）；closure 仍須 Codex 二次驗證。**

reviewer 判 **CONDITIONAL_PASS**，兩個 blocking defect —— 而且**兩個都是我的敘述灌強了撤回方向**：

1. **B1（結論強度超過證據）**：原 README 寫「同一個 null 也吃掉了 raw 數字」，但同一句印出的
   inception raw **p=0.047 < 0.10** —— raw 統計量在長樣本上**確實拒絕**了相位 null。
   我的總結被自己的數字推翻，而這正是**唯一**能拿來救回原結論的數字。
   **修法**：不再閃避，把它正面寫成一整節（見上方「但 raw 統計量**確實**拒絕了這個 null」），
   並且**把機制量出來而不是斷言** —— 新增 `exposure_of_the_null`，測得觀察相位的實現波動
   在自己所有相位中排名 **1/231（inception）／2/170（common）**，即最低。
   結論：12/VIX 真的會降風險（VIX 確實預測波動），而 raw MDD gap 獎勵的正是降風險；
   降風險 ≠ 同風險下回撤更淺。這一節現在是整份更正**最強**的一段。
2. **B2（方法宣稱 ≠ 實作）**：inception 的位移群原本建在 union span（231 個月），但 INDA
   （2012 起）／MCHI（2011 起）只覆蓋其中一部分 → 位移會餵給它們**從未經歷過的月份**
   （含 2008 低權重）→ 對 2/13 市場，「循環位移完全保留該市場權重」的宣稱**不成立**，
   且會灌大權重離散度、灌高 null（方向同樣偏向撤回）。
   **修法**：改成每個市場位移**自己實際交易過的月份**、共用同一位移量 s；新增 runtime 斷言
   「位移不得引入該市場沒持有過的權重」，並補回歸測試。
   影響：inception p 0.216 → **0.212**（null 平均 +0.62 → +0.59），結論不變。

非阻斷建議亦已採納：exact randomization p 改為 `n_ge/n_shifts`（原用 Monte-Carlo 的
`/(n+1)` 慣例，在窮舉群上偏 anti-conservative ~0.6%；MC 版本仍保留供與 K1265b 對照）；
`np.allclose` 補 `rtol=0.0` 使宣稱的 1e-12 名副其實；硬編的 vol-ratio 區間改為插值；
結論 snapshot 從規則 gate 拆出。

**修正後全數重跑**：19/19 tests PASS、`experiment_gates.py run` PASS、MDD ratchet PASS。
**由於 code 已在審查後變動，sha 必然漂移 —— 依 §審查認證，這份更正需重審一輪才能認證合併。**
