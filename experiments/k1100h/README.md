# K1100h — TAIFEX TX tick-level PRG (Phase 0 Scoping)

[提出: Claude 自主研究（K1100g_d6-d8 daily borderline 衍生假說）/ 執行: Claude worker / 2026-04-18]

**Status**: Phase 0 **Scoping only** — data readiness + experimental design.
**不**跑 estimation、**不** commit、**不**動 `knowledge.json` / `research_program.md`。
完成 criteria：本 README 7 節齊備、每項 Risk 配具體 mitigation、Phase 1 入口明確。

---

## 1. Problem — 為何要 tick-level？

K1100g 系列（d1 – d8）在 daily / overnight-vs-intraday 尺度上反覆驗證「TAIFEX gap² → 日盤 intraday r²」的預測訊號，
方向一致但 DM t-stat 卡在 Harvey (2016) `|t|>3` 之下：

| 實驗 | 測試對象 | N_OOS | DM (gap²) | Harvey 過關 |
|------|---------|------:|----------:|:-----------:|
| K1100g_d5 TAIFEX | gap² Student-t PRG | 464 | +1.49 | ✗ |
| K1100g_d6 TAIFEX 2017-2025 | 同左延伸 | 1385 | (borderline, regime-sensitive) | ✗ |
| K1100g_d7 SPY  | cross-market replication | 1508 | +0.66 | ✗ |
| K1100g_d7 N225 | cross-market replication | 1465 | +2.32 | ✗ |
| K1100g_d8 N225 | Hansen skewed-t innovation | 1465 | -1.33 (skew uninformative) | ✗ |

**假說 (K1100h agent-derived)**：**daily aggregation 把 intraday periodic structure 平均化掉**。
如果 TAIFEX 的 session / hourly pattern 是真正的 mechanism，只有 **tick → 5-min / 15-min grid** 才能直接量化：

1. **日盤開盤 08:45 附近的 variance spike**（information absorption + overnight carry-over）
2. **日盤收盤 13:30-13:45 的 closing auction variance 上揚**
3. **夜盤 15:00 開盤的 US overlap hour 變異 vs 凌晨 02:00-05:00 的 quiet hour**
4. **5-min RV 對下一段 5-min RV 的 HAR-style periodic forecasting gain**

這些在 daily 維度全部被 aggregate 掉；tick → 5-min 是保留 periodic structure 的最低代價解析度。

**K1100h 的貢獻**：首次在 TAIFEX tick data 上做 **intraday PRG**，並用同樣 Harvey |t|>3 規格對比 daily PRG。
若 tick 能過 Harvey 而 daily 不能，直接把 Paper 3 narrative 從 "daily direction-consistent borderline"
升級為 "intraday-periodic structural anchor"。

---

## 2. Motivation — K1100g_d6-d8 failure 摘要

完整 verdict ladder（K1100g 系列 daily-scale）：

| 實驗 | 加的 lever | 結論 |
|------|-----------|------|
| **K1100g_d5** | pure gap² PRG (TAIFEX) | N=464 DM=+1.49，direction OK, threshold fail |
| **K1100g_d6** | 2017-2025 延伸（期望 √N scale: 1.49 → ~3.5） | 擴大樣本後 DM 未線性 scale，signal 部分 regime-specific |
| **K1100g_d7** | SPY / N225 跨市場 replication | 3 markets 同向但全 borderline（TAIFEX +1.49、SPY +0.66、N225 +2.32） |
| **K1100g_d8** | Hansen (1994) skewed-t innovation on N225 | IS LRT=0 → PRG τ×g 已吸收 skew；OOS DM=-1.33 改善無效 |

**歸納 failure modes**（為什麼 daily 卡住）：

- **d6**：DM 沒 √N scale 暗示 effect 非 stationary i.i.d. signal；可能是 **regime / session-structured**
- **d7**：跨 3 市場全 positive 但 borderline，方向一致 ≠ 強度夠；**daily 平均化損失了 intraday cluster**
- **d8**：innovation family 升級無效；瓶頸不在 tail distribution，而在 **conditional variance kernel 的時間解析度**

三條線索共同指向：**要打 Harvey 必須放棄 daily，進 tick-level periodic structure**。

這是為什麼 K1100h agent derivation 明確把 tick level 當下一步 lever，而不是再換 innovation / 再加 market。

---

## 3. Data — path / schema / coverage / quality issues

### 3.1 資料位置（`external-data-sources` skill 規範）

```
~/Dropbox/TAIFEXDATA/TAIFEXDATA/python/
├── Daily_YYYY_MM_DDTX.csv    ← 全合約合併（首選，volume-based active contract picker）
├── Daily_YYYY_MM_DDTX1.csv   ← 近月 continuous（⚠️ settle day 仍是 expiring contract）
└── Daily_YYYY_MM_DDTX2.csv   ← 次月（流動性極低 ~1%，不用）
```

- 本機已同步 **10,467 檔**（3 個 suffix × ~3489 交易日，~33 GB，2012-01-02 起）
- 其他子目錄（`{year}/csv/`、`OPTIONDATA/`）是 Dropbox placeholder 0 bytes，不要讀

### 3.2 Schema（驗證 3 個樣本：2018-03-21、2020-06-15、2021-11-17，全部 TX1）

| # | 欄位（big5 encoding） | 型別 | 說明 |
|---|----------------------|------|------|
| 1 | `成交日期` | int (YYYYMMDD) | 實際成交日；夜盤段可能 = 檔名日期 - 1 |
| 2 | `商品代號` | str | `TX` / `MTX` / `TXO` 等 |
| 3 | `到期月份(週別)` | str (YYYYMM) | TX1 = near contract；settle day 仍是 expiring |
| 4 | `成交時間` | int (HHMMSS) | 6-digit；⚠️ min=0 / max=235959，**跨夜不可單獨用** |
| 5 | `成交價格` | float | 成交 tick 價格 |
| 6 | `成交數量(B+S)` | int / float-str | 買 + 賣合計（/2 = 真實成交口數） |
| 7 | `近月價格` / 8 `遠月價格` | mixed `'-'` / float | 常為 `'-'`，不可當數值直接轉型 |
| 9 | `開盤集合競價` | str `'*'` / NaN | 集合競價首筆 flag |
| 10 | `時間戳記` | str (`YYYY-MM-DD HH:MM:SS`) | **首選時間欄**，跨夜唯一可靠 |

驗證樣本 rowcounts：2018-03-21=51,291；2020-06-15=134,920；2021-11-17=44,281。
tick 頻率差異大（2020-06 是 COVID 高峰），全部走 `encoding='big5'` + `low_memory=False`。

### 3.3 Session 結構（必須理解的資料分布）

一個檔名日期 `Daily_YYYY_MM_DD` 的檔案**同時包含**三段：

```
(D-1) 15:00:00 ─────── 23:59:59      ← 夜盤上半段（前一日晚開）
(D)   00:00:00 ─────── 05:00:00      ← 夜盤下半段（當日凌晨結束）
(D)   08:45:00 ─────── 13:45:00      ← 日盤
```

- 檔名日期 = 日盤結束日；`時間戳記` 才能正確分段
- **日盤 5 小時；夜盤 14 小時**（2017-05-16 起穩定）；2017-05-15 前無夜盤
- **集合競價**在每段開頭一筆，price 不代表可成交價，bookkeeping 時要剔除或單獨標記

### 3.4 Coverage

- 2012-01-02 至最近交易日（2025 末）；~3489 個交易日
- ⚠️ Schema 斷點：
  - ~2011：格式不同，7-8 位成交時間（本專案忽略，不使用）
  - 2012-2013：9 欄（無「開盤集合競價」欄）
  - 2014 – 2017-05-15：10 欄，但**日盤 only**（無夜盤）
  - **2017-05-16 起**：10 欄、含夜盤、成交時間穩定 6 位 `150000`
- **K1100h 使用 2017-05-16 起的穩定 schema**（與 K1100g cache 完全重疊，可直接沿用 roll logic）

### 3.5 Re-aggregation 對照 K1100g daily（sanity check ✅）

隨機抽 **2020-06-15** 做 tick → day-session OHLC：

| Metric | Tick re-aggregate（K1100h） | K1100g cache | 差異 |
|--------|---------------------------:|-------------:|:----:|
| day_open  | 11356 | 11356 | **0** |
| day_high  | 11446 | 11446 | **0** |
| day_low   | 11216 | 11216 | **0** |
| day_close | 11229 | 11229 | **0** |
| day vol (B+S sum) | 271,016 | — | — |

**結論**：tick → daily OHLC 與 K1100g cache 完全一致，pipeline 可直接沿用 K1100g 的 roll / session / dow 規則。

### 3.6 Schema surprises（scoping 階段發現）

1. **K1100g `is_settlement` flag 不一致**：2021-11-17（第三週三）True、2018-03-21（亦第三週三）False — K1100g 用外部 `taiwan_calendars` 計算，可能在 2018 前後年度有 off-by-one bug。**K1100h 要自己算 settlement**（`date.weekday()==2 and 15<=date.day<=21`），不要 reuse K1100g 的 flag。
2. **TX1 在 settle day = expiring contract**：2018-03-21 檔的 `到期月份` 全部=201803（當日到期）。tick-level 分析需要在 settle day 之後 strict 切到下期；建議改用 `TX`（全合約）+ volume-based picker。
3. **成交數量型別不一**：早期年 `成交數量(B+S)` 為 float，近期為 int；`pd.to_numeric(..., errors='coerce')` 避免型別警告。
4. **集合競價 price outlier**：有些檔 tick 首筆集合競價價格偏離後續 tick 0.5-1%；RV / jump 計算前要剔除 `開盤集合競價=='*'` 的 tick（或單獨標記為 boundary jump）。

---

## 4. Method — Phase 1 PRG estimation plan on tick / 5-min grid

（本節只描述設計，不執行；Phase 1 獨立實驗做實估計）

### 4.1 三層 resolution 並列（Phase 1 做完整三層）

| Resolution | 每日 bars | 規格 | 定位 |
|-----------|----------:|------|------|
| **Daily** | 1 | K1100g_d5/d6 baseline | 對照組（證明 tick 有 incremental） |
| **15-min grid** | 20 (day) + 56 (night) = **76** | PRG with intraday periodic dummies | 穩定、雜訊低、首選 |
| **5-min grid** | 60 (day) + 168 (night) = **228** | PRG with tighter periodic dummies | 高解析，噪音高，robustness |

- Day session 08:45-13:45 (5h) / night session 15:00-05:00 (14h)
- 5-min / 15-min bar 建構：以 `時間戳記` resample，取 last tick price → log returns；volume sum
- 跨 session gap 專門處理：day→night（13:45 → 15:00）、night→next-day (05:00 → 08:45) 的 returns 分開記錄，**不跨 gap 算 return**

### 4.2 PRG 規格

延伸 K1100g_d5 的 Student-t PRG τ×g multiplicative kernel 到 intraday grid：

```
y_{t,k} = sigma_{t,k} · z_{t,k},   z ~ Student-t(df)
sigma²_{t,k} = tau_t · g_{t,k}
tau_t   = unconditional daily scale（HAR-RV 或 PRG daily backbone）
g_{t,k} = GJR(omega, alpha, gamma, beta) on y_{t,k}²    ← within-day volatility
        + sum_{s} phi_s · D_s(k)                         ← periodic dummies
        + xi · gap²_t   (optional, Phase 1.3 only)
```

**Periodic dummies `D_s(k)`**（3 組疊加）：

1. `session_dummy(day / night_early / night_late / pre-close)` — 4 coarse dummies
2. `hour_of_session_dummy` — k 所在 session 內第幾小時（day 5 dummies, night 14 dummies）
3. `end_of_day_dummy` — 日盤最後 15-min bin（13:30-13:45 closing auction）

`phi_s` 捕捉「U-shape / reverse-U / end-of-day」variance pattern，是 daily PRG 無法表達的新信息。

### 4.3 Phase 1 exog ladder

| Variant | 加的 exog | 測什麼 |
|---------|-----------|-------|
| M1 (baseline) | 無 | 純 PRG + GJR intraday |
| M2 | + periodic dummies | 純 periodic gain |
| M3 | M2 + gap²_t (contemp, open-time already realized) | 複製 K1100g_d5 signal on tick grid |
| M4 | M3 + HAR-RV lag(1d / 5d / 22d) | Corsi 2009 HAR 融合 |

每層做 M_i vs M_{i-1} 的 OOS DM (HLN-adjusted)，targets = 15-min / 5-min bar 的 `r²` 或 RV bin。

### 4.4 Train / Test / Refit

- Train：2017-05-16 至 2019-12-31（約 640 交易日 × 76 bars ≈ 48,640 obs / 15-min grid）
- Test：2020-01-01 至 2025-12-31（約 1385 交易日 × 76 ≈ 105,260 obs）
- Expanding-window refit，`refit_every` = 交易日 25 天（不是 bar 25，避免 K1100g_d8 過疏 artefact）
- `n_restarts=10` IS / `n_restarts=5` OOS（比 d8 更嚴格）

---

## 5. Expected Output — sample estimate / DM test / Harvey threshold

### 5.1 樣本量放大效應

與 K1100g_d6 (daily, N_OOS=1385) 比較，**15-min grid** 的 N_OOS 約 105,260；
若 signal variance 不隨 resolution 塌陷，期望 Harvey t-stat scale：

```
t(tick) ≈ t(daily) · √(N_tick / N_daily)
       ≈ +1.49 · √(105260 / 1385)
       ≈ +1.49 · √76.0 ≈ +13.0     (理論上界)
```

⚠️ 此為理論上界（假設訊號 i.i.d. 無 over-dispersion）。現實因 intraday autocorrelation（HAC bandwidth 放大）、
session noise、market-microstructure overlap，實際 t 通常打折 3-5 倍。**保守 expectation**：

| Scenario | 15-min grid DM t | 5-min grid DM t | Harvey 過關 |
|----------|-----------------:|----------------:|:-----------:|
| Optimistic (HAC 打 3 折) | +4.3 | +5.0 | ✓ |
| Realistic (HAC 打 5 折) | +2.6 | +3.0 | ~marginal ✓ |
| Pessimistic (over-dispersion) | +1.5 | +1.7 | ✗ |

**decision rule**：
- 若 M2 vs M1（純 periodic gain）**在 15-min + 5-min 都過 Harvey**（|t|>3）→ tick-level periodic structure **是**
  K1100g 系列缺的 anchor，直接升級 Paper 3 narrative 到 "intraday-periodic PRG"
- 若只有其中一個 grid 過，或都 borderline → Paper 3 保 d7 verdict 不動，但標記 "intraday strong at X-min"
- 若兩個 grid 都 NULL → 方向錯了，tick 不是 mechanism，要改找 jump / rollover / announcement-based exog

### 5.2 DM test 規格（嚴格對齊 K1100g_d5/d6）

- **Harvey-HLN adjusted** with 1/3 power bandwidth
- loss = QLIKE on `r²` bar target（非 MSE，與 K1100g 一致）
- NW / HAC lag = `ceil(N^{1/3})`（~47 for 105260 obs）
- p-value 雙邊；Harvey threshold |t|>3.0 主判準；|t|>1.96 僅作 secondary direction

### 5.3 Sanity expectations（實驗必通過才 accept results）

1. M2 IS LRT 對 M1 chi²(k) 顯著（k = periodic dummies 數）
2. `phi_s` 對 open / close / overlap 小時有明顯正值；quiet hour 為 0 或負
3. OOS QLIKE 改善 ≥ 2%（daily d5 為 6.62%，降解析度應介於 1-5%）
4. 殘差 ARCH-LM test 不顯著（periodic dummies 已吸收 diurnal heteroskedasticity）

---

## 6. Risks — 具體 mitigation（每項）

### R1. Tick data noise（microstructure + jump contamination）

- **風險**：tick level return 含 bid-ask bounce、集合競價異常、零成交量 flat tick
- **影響**：`r²` bar 上尾 tail 膨脹，PRG GJR 吸不了，`xi·gap²` 變 unreliable
- **Mitigation**：
  - （a）集合競價 tick (`開盤集合競價=='*'`) **剔除或另成 boundary bar**
  - （b）bid-ask bounce：用 tick **last price of bar**（而非 mean）+ 5-min bar 以上 resolution 避免
  - （c）jump：跟 K849 一樣做 BNS (2006) bi-power jump test，winsorize top 0.5% abs returns
  - （d）flat bar (0 volume)：forward-fill 最後 price、return=0，但在 realized volatility 計算時 **跳過**該 bar

### R2. Rollover bias（settle day 合約切換）

- **風險**：TX1 在 settle day 仍是 expiring contract，price decay 不是真實市場訊號
- **影響**：第三週三的 intraday variance 被結算 pricing 污染
- **Mitigation**：
  - （a）改用 **`Daily_*TX.csv`**（全合約），按 (date, contract_month) 每日挑成交量最高合約
  - （b）roll day detection：`contract_month_t != contract_month_{t-1}` → 當日 **close-to-open gap 設 NaN**
  - （c）K1100g 的 `is_settlement` flag 有 2018 bug → 自己重算（第三週三 `weekday==2 and 15<=day<=21`）
  - （d）settle day 日盤 intraday return 正常用，但要在 result JSON 另外分 settle / non-settle subgroup 檢查 parameter stability

### R3. Day boundary handling（day→night / night→next-day gap）

- **風險**：`13:45 → 15:00` (1.25h gap) 和 `05:00 → 08:45` (3.75h gap) 是 non-trading gap，return 裡有 information 但 intraday bar 是 closed
- **影響**：若 naive 把 gap period 當 bar，variance 被誤算為 intraday GJR shock
- **Mitigation**：
  - （a）bar construction 只在 session 內 resample，**跨 session 不產生 bar**
  - （b）`gap_day→night`（13:45 → 15:00 的 log-return）和 `gap_night→day`（05:00 → 08:45 log-return）作為 **separate exog 變數**，不進 intraday `y_{t,k}`
  - （c）Phase 1.3 的 M3 把這兩條 gap² 作為 exog 加入 `g_{t,k}` 在每個 bar 的 contemp effect
  - （d）**首個 bar（08:45-09:00）** 用 open price 而非前段 close → 避開 gap contamination

### R4. Seed-fix for bootstrap / MLE restarts

- **風險**：PRG likelihood surface 在 intraday 高維 (GJR 4 + periodic dummies ~20 + df + exog) 上有 local minima，重跑會飄
- **影響**：`phi_s` parameter 不穩定 → DM test t-stat 隨機抖動，結果不可重現
- **Mitigation**：
  - （a）固定 `np.random.seed(42)` + `rng = np.random.default_rng(42)` 於實驗 entrypoint
  - （b）`n_restarts=10` IS / `n_restarts=5` OOS，初始值從 Sobol sequence（`rng.standard_normal` seeded）產生
  - （c）每個 refit 的 `(phi_s, xi, df)` 存 parquet audit；**boundary detect**：若 phi_s 有 5%+ refits 卡在 ±3σ 邊界 → verdict 標 PRELIMINARY
  - （d）bootstrap DM CI：block bootstrap（block=22 trading days）with `rng.choice(seed=42)`；1000 resamples，報 95% CI
  - （e）重跑 audit：Phase 1 結束後用 `seed=43` 重跑 3 個 OOS refits 比對，差異 > 1e-3 視為 non-reproducible

### R5.（衍生）Computational cost

- **風險**：15-min grid 145k obs × 4 models × expanding OOS refit ≈ 數十小時
- **Mitigation**：
  - （a）PRG kernel 用 numba JIT（K1100g 已有 template）
  - （b）`refit_every=25` 交易日（日單位，不是 bar）
  - （c）M1/M2/M3/M4 四個 model 各自 multiprocess（M1 Max 10 核 / 保留 4 給主線程 = 6 worker）
  - （d）5-min grid 若 > 6h 則延後到 K1100h Phase 2（先完成 15-min 決策再決定 5-min 是否必要）

### R6.（衍生）Lookahead at tick level

- **風險**：intraday exog 容易不小心用到未來 bar 資訊（e.g. contemp bar RV 當預測 feature）
- **Mitigation**：
  - （a）`gap²_t` 在日盤開盤瞬間已實現，合法（Paper 6 K880 precedent），但要確保代碼中寫 `gap2 = (open[t] - close_night_last[t])**2` 而非用今日 close
  - （b）任何 HAR lag feature 用 `lag(1)` 最少一個 bar
  - （c）Codex code review：在 Phase 1 寫完代碼後、**執行前**必須走 `/codex:review` flow（K1100 系列累積 4 次 lookahead 錯，必跑）
  - （d）code 中必須有明顯的 `.shift(1)` 或 `.iloc[:-1]`；`signal.shift(0)` 一律禁止

---

## 7. References

### 已完成實驗（K1100 系列 Paper 3 脈絡）

- **K1100f** (`experiments/k1100f/`) — SPY-ES 4-model copula PRG NULL → Paper 3 reframe anchor
- **K1100g** (`experiments/k1100g/`) — TAIFEX vs SPY 4-dim microstructural quantification；overnight/intraday=1.59 是唯一 anchor
- **K1100g_d3/d4/d5** — TAIFEX daily PRG with gap² Student-t (N=464, t=+1.49 borderline)
- **K1100g_d6** — 2017-2025 sample extension (N=1385, DM 未 √N scale)
- **K1100g_d7** — SPY / N225 cross-market replication (3 markets direction-consistent, all borderline)
- **K1100g_d8** — Hansen (1994) skewed-t innovation on N225 (IS LRT=0, 無增益)

### K849 / K851 / K852b — TAIFEX tick pipeline precedent

- K849：HAR-RV vs GJR on TAIFEX 5-min (DM t=-11.14, QLIKE 0.18 vs 0.53) — **tick pipeline 技術基礎**
- K847：隔夜 gap 61% 可交易 (R²=0.83) — overnight information 量化
- K844：TAIFEX VT 空頭全勝，夜盤 return 73.7% — session 風險分布
- K848：74.9% 天有 jump，夜盤 vol 佔比 24%→57% (2017→2026) — jump contamination baseline

### 文獻

- **Engle & Rangel (2008)** *RFS* 21(3) — multiplicative τ×g PRG baseline
- **Corsi (2009)** *J. Fin. Econometrics* 7(2), 174-196 — HAR-RV model
- **Barndorff-Nielsen & Shephard (2006)** *JFE* 4, 1-30 — bi-power jump test
- **Andersen & Bollerslev (1997)** *JFE* 4, 115-158 — intraday periodic volatility foundation
- **Deo, Hurvich & Lu (2006)** *JoE* 131 — forecasting realized volatility using HAR
- **Patton (2011)** *J. Econometrics* 160, 246-256 — QLIKE loss function for variance forecasting
- **Harvey, Leybourne & Newbold (1997)** *IJF* 13(2) — HLN DM small-sample correction
- **Harvey (2016)** *JF* — `|t|>3` threshold
- **Lai (2024)** *APFM* 31(2) — PRS copula hedging TAIFEX（研究起點）

### Skill / infra

- `external-data-sources` — TAIFEX tick data path / schema / rollover 陷阱
- `autonomous-research` — 主研究流程 runtime
- `agent-result-verification` — Phase 1 agent 返回後必走
- `worktree-merge-verification` — Phase 1 若用 worktree 必走

---

## 附錄 A — Phase 1 proposed follow-up task

```
title: K1100h Phase 1 — TAIFEX tick PRG at 15-min / 5-min grid with periodic dummies
priority: P3
family: research
scope:
  - 實作 build_intraday_cache() 把 tick 檔 resample 到 15-min / 5-min bar（day + night session）
  - 實作 fit_prg_intraday_student(): τ×g + GJR + periodic dummies + (optional gap² / HAR exog)
  - 4-model ladder M1→M2→M3→M4 expanding OOS with refit_every=25 trading days
  - Codex code review 必跑（lookahead / rollover 兩關）
  - Sanity：殘差 ARCH-LM、periodic dummy significance、bootstrap DM CI
success:
  - 15-min grid M2 vs M1 DM |t| > 3.0 → PASS tick-level periodic anchor
  - 或 15-min + 5-min 均 borderline → REPORT d7 verdict 不動，tick not mechanism
preconditions:
  - K1100h README.md（本檔）核准
  - 磁碟 ≥ 10 GB（tick cache）
  - 執行前確認 `_hansen_sanity_check`-style unit test 通過
```

---

## Provenance

- 提出: Claude 主線程 + K1100g_d8 agent derivation
- 執行: claude-worker（task_4f9eb51458cf）
- 日期: 2026-04-18
- Seed: 42（Phase 1 執行時）
- 執行檔：本 Scoping README 不伴隨腳本；Phase 1 實驗腳本將命名 `experiments/k1100h/k1100h.py`
