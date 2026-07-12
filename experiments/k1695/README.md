# K1695：VT Trend-Following Table 5 國際 13 市場 canonical 重跑

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

### 預註冊推斷規格

- Primary：joint circular stationary bootstrap，B=10,000、mean block=252 trading days、seed=42、90% percentile CI。
- Sensitivity：mean block = 63／126／504，每個 B=3,000，seed 在執行前固定。
- 每個 replication 同步重抽 13 個 BH + 13 個 VT return columns；不串 asset-day、不各市場獨立抽、不抽 price/VIX levels。
- 不再報 iid cross-sectional one-sample t-stat；per-market 13/13 count 只屬描述性。

成功標準：inception-aware 與 common sample 均維持 13/13 ΔMDD > 0，且 common-sample average ΔMDD 的 primary 90% joint-bootstrap CI 不含 0。

Kill 標準：任一 observed sample 少於 13/13，或 primary CI 含 0，則 `decision.kill_triggered=true`，第三項 contribution 必須降級為 conditional；null result 仍完整保存。

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
| `data/yfinance_raw_snapshot.csv.gz` | pinned raw/actions snapshot |
| `data/snapshot_manifest.json` | provenance + SHA256 |
| `data/paired_common_returns.csv.gz` | joint-bootstrap 的 26 欄 paired returns |
| `test_k1695.py` | timing／corporate-action／bootstrap／atomic-write gates |
| `run.log` | canonical run console receipt |
| `run_preflight_failure.log` | 首次 5 bp 單一門檻 fail receipt（策略結果尚未計算） |
| `run_runtime_failure_target_weight.log` | 第二次 run 的 Series schema naming fail receipt（bootstrap 前） |

## 結果

Canonical run：2026-07-12；snapshot SHA256 `38cb3a0bd286cbf27992caefda6b67fb558f460c125261366060e9c1ec7f7751`。

### Inception-aware Table 5

| 指標 | 結果 |
|---|---:|
| Markets with ΔMDD > 0 | 13 / 13 |
| Average ΔMDD | +27.50 pp |
| Developed / Emerging average ΔMDD | +31.33 / +23.04 pp |
| Markets with ΔSharpe > 0 | 1 / 13（EWJ） |
| Average ΔSharpe | -0.044 |
| Average annual CAGR cost（VT−BH） | -1.17 pp/year |
| VIX sensitivity vs ΔMDD | Pearson r=-0.817 (p=0.00065); Spearman ρ=-0.775 (p=0.00187) |

各市場 sample end 均為 2026-03-31；INDA／MCHI 依實際 inception 進樣本，不補歷史。這組 cross-sectional correlation 是描述性，不能稱 causal pricing mechanism。

### 13 市場共同樣本與正式推斷

共同樣本為 2012-02-07 至 2026-03-31，N=3,557 個共同交易日。

| 指標 | 結果 |
|---|---:|
| Observed markets with ΔMDD > 0 | 13 / 13 |
| Observed average ΔMDD | +12.61 pp |
| Markets with ΔSharpe > 0 | 0 / 13 |
| Average ΔSharpe | -0.091 |
| Average annual CAGR cost（VT−BH） | -2.18 pp/year |
| Primary joint-bootstrap average ΔMDD 90% CI | **[+4.22, +19.30] pp** |
| Bootstrap median / P(average ≤ 0) | +11.82 pp / 0.0006 |
| P(all 13 bootstrap ΔMDD > 0) | 0.8429 |

Block sensitivity 的 90% lower bounds 仍為正：63 日 +4.58、126 日 +4.42、504 日 +4.33 pp。平均效果因此通過預註冊 gate，`decision.kill_triggered=false`。但 individual-market bootstrap 只有 12/13 的 90% lower bound >0（EWA 含 0），所以結論只能是「平均國際 drawdown protection 有 dependence-robust 支持」，不可說每一市場 individually significant。

共同樣本的 VIX-sensitivity 關聯不穩健：Pearson r=+0.305 (p=0.311)、Spearman ρ=+0.148 (p=0.629)。因此：

1. 13/13 observed MDD 改善與 average joint-bootstrap CI 支持 drawdown-protection 結論。
2. 改善伴隨 Sharpe／CAGR 成本；正確有單位的平均 return cost 是 1.17 pp/year（inception-aware）或 2.18 pp/year（common），不能再寫「4%/year Sharpe drag」。
3. 「VIX sensitivity 橫斷面預測保護幅度」只在 inception-aware 截面成立，common sample 不支持，必須降級為 sample-dependent descriptive pattern。

## 驗證紀錄

- Fresh-context pre-run review：初始 FAIL（MDD 漏 initial NAV、snapshot coverage 不 fail closed）→ 修後 PASS。
- Synthetic tests：11/11 PASS；ruff PASS；`git diff --check` PASS。
- Results verification：artifact SHA256、Table 5 / common rows aggregation、paired-return MDD、kill flag 全部從 JSON/CSV 獨立重算 PASS。
- Primary B=10,000 bootstrap 從 pinned paired panel 以 seed=42 重算，CI／median／mean／tail probability 在 CSV round-trip tolerance `1e-12` 內一致。
- `figure_cross_asset.png` 已視覺檢查：13 點、region legend、labels、mean/zero reference lines 均可讀。
