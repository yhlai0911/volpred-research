# Indicator Arena 設計文件（Phase 1a）

> 任務來源：boss_request_2026-06-11（`indicator_arena_phase1_design_candidates_2026_06_11`）
> 撰寫日期：2026-06-11（台灣時間）
> 範圍：資料模型 + 生命週期狀態機 + 誠實機制 + 評分公式 + 首發指標候選（含 OOS 驗證數字）
> 不含：前端實作、Supabase 建表（Phase 1b）

---

## 1. 目的與定位

首頁「預警 / 預測指標測試專區」（Indicator Arena）：每日公開發布各指標的當日數值、預測內容與時效（horizon），到期後自動回顧對錯並累積績效排名。表現差的指標進觀察區、持續差就下架 — **下架紀錄永久公開保留**。

定位對齊平台五目標：
- 內容深度（每個指標背後是真實 K 實驗 + OOS 證據，不是看圖說故事）
- 信賴度（ex-ante 預測 + 不可改寫紀律 = 與 paper_trading 同級的 forward-tracking 公信力）
- 曝光（每日更新的可分享頁面；「哪個指標最近最準」天然有話題性）
- 商業（準確率排行 = 付費 premium 指標訂閱的 funnel 入口）

核心原則：**Arena 評的是「預測」不是「交易」**。指標的方向命中率與校準度是一級公民；可交易性（成本、時差、流動性）如實標註但不影響評分 — 例如 US→TW 隔夜訊號的 alpha 集中在不可交易的開盤 gap（K521 verdict），這在 Arena 是合法預測、在策略上架 gate 則不是。兩條線不混。

---

## 2. 資料模型（三表）

Phase 1b 落地 Supabase 前，本地 source of truth 放 `storage/indicator_arena/`：
`registry.json`（表 1）、`signals/YYYY-MM.jsonl`（表 2，append-only）、`reviews/YYYY-MM.jsonl`（表 3，append-only）。

### 2.1 `indicator_registry`（指標主檔）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `indicator_id` | text PK | slug，如 `us_tw_overnight_lead` |
| `name_zh` | text | 顯示名稱 |
| `league` | enum | `direction`（方向組）/ `calibration`（校準組，VaR/區間類） |
| `signal_rule` | text | 可程式化規則全文（含明確 lag 規定） |
| `target` | text | 預測標的（如 `0050.TW close-to-close return t`） |
| `horizon_days` | int | 預測時效（交易日） |
| `data_sources` | jsonb | ticker / URL / 更新頻率 / fallback 來源 |
| `k_refs` | text[] | 來源 K 編號（指向 `experiments/<id>/`） |
| `oos_evidence` | jsonb | OOS 期間、樣本數、關鍵統計量（抄自 results.json，附欄位路徑） |
| `caveats` | text | 已知限制（可交易性、regime 依賴等）— 公開顯示 |
| `status` | enum | `active` / `observation` / `delisted` |
| `status_since` | timestamptz | 當前狀態起始 |
| `listed_at` / `delisted_at` | timestamptz | 上架 / 下架時間（下架後 row 不刪） |
| `status_history` | jsonb[] | 全部狀態轉換紀錄（append-only） |

### 2.2 `daily_signals`（每日訊號，append-only）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `signal_id` | text PK | `<indicator_id>:<target_date>` |
| `indicator_id` | text FK | |
| `published_at` | timestamptz | **ex-ante 時間戳**（寫入當下取 `date`，不可臆造） |
| `target_date` | date | 預測對應的目標交易日 |
| `resolve_after` | timestamptz | 此時間前不得評分（target session close + horizon） |
| `indicator_value` | numeric | 當日指標原始值（如 log(VIX9D/VIX)=−0.034） |
| `prediction` | jsonb | 方向組：`{direction: up/down/flat}`；校準組：`{var_5pct: -0.0182}` 等 |
| `inputs_snapshot` | jsonb | 計算用的輸入值 + 各輸入的資料時間戳（可復現） |
| `code_version` | text | 產生訊號的 script git commit hash |

### 2.3 `outcome_reviews`（回顧評價，append-only）

| 欄位 | 型別 | 說明 |
|---|---|---|
| `review_id` | text PK | `<signal_id>:review` |
| `signal_id` | text FK | |
| `reviewed_at` | timestamptz | 自動回顧執行時間 |
| `realized` | jsonb | 實際結果（target 實際報酬 / 是否突破 VaR） |
| `hit` | boolean/null | 方向組：方向對錯；校準組：是否 violation（語意不同，league 區分） |
| `econ_value_bps` | numeric | 該筆訊號的單筆 expectancy（見 §5） |
| `data_source_asof` | timestamptz | 回顧用收盤數據的抓取時間 |
| `correction_of` | text/null | 若為更正單，指向原 review_id（原單不刪不改） |

---

## 3. 生命週期狀態機

```
            上架 gate（§3.1）
                 │
                 ▼
   ┌──────── active ────────┐
   │  降級條件 D1            │ 回升條件 U1
   ▼                        │
observation ────────────────┘
   │  下架條件 D2
   ▼
delisted（終態；歷史與頁面永久保留，標註下架日期與原因）
```

### 3.1 上架 gate
- 來源 K 實驗 verdict ≥ CONDITIONAL_PASS，且有 `experiments/<id>/results.json` 可驗證的 OOS 證據（knowledge.json 摘要不夠 — 本文件 §6 全部候選已逐一回 results.json 驗證）
- 訊號規則可程式化、有明確 lag（signal at t−1 → target at t 或等效）
- 資料源免費、可日更、已實測（§6 每候選附實測結果）

### 3.2 閾值規則（首發參數，運行 90 天後檢討）
- **D1（active → observation）**：方向組 — `hit_60 < 0.50` 連續 10 個交易日（且 n_resolved ≥ 20）；校準組 — rolling 250d Kupiec p < 0.05 連續 10 個交易日
- **U1（observation → active）**：方向組 — `hit_60 ≥ 0.55` 連續 10 個交易日；校準組 — rolling 250d Kupiec p ≥ 0.10 連續 10 個交易日
- **D2（observation → delisted）**：進入 observation 後 60 個交易日內未觸發 U1
- 所有轉換由 daily review job 自動判定 + 寫 `status_history`，不人工干預；轉換當日在 arena 頁面公告

---

## 4. 誠實機制（比照 paper_trading forward-tracking 紀律）

1. **Ex-ante timestamp**：`published_at` 取自實際系統時間；`resolve_after` 強制 — 任何在 target session 開始後才寫入的訊號標記 `late=true` 且不計入排名（只展示）。台股 target：訊號必須在台北 09:00 開盤前發布；美股 target：必須在 ET 09:30 前。
2. **Append-only**：`daily_signals` 與 `outcome_reviews` 只允許 append；錯誤用更正單（`correction_of`）沖正，原始紀錄永不改寫 — 同「永遠修流程，不修資料」。每筆帶 `code_version`（git hash），git 歷史即 tamper-evidence。
3. **回顧自動化**：對錯判定由 daily job 跑，不經人手；判定邏輯版本化（code_version），改判定規則必須公告且只 forward-apply，不回溯重算歷史 hit。
4. **Delisted 歷史保留**：下架指標的全部 signals/reviews/排名歷史永久公開 — 「我們也會錯，而且錯的紀錄找得到」是信賴度資產。survivorship bias 主動揭露：arena 頁面顯示「歷來上架 N 個、現存 M 個」。
5. **數據缺漏處理**：資料源當日抓不到（如 yfinance ^VIX9D 偶有 1-2 日延遲）→ 該指標當日記 `skipped`（公開可見），不得用 stale 值充當今日值。
6. **無 cherry-picking 上架**：上架 gate 走本文件 §3.1，候選落選原因公開（§7）— NULL 證據如實列出。

---

## 5. 評分公式（提案）

**主指標 — rolling 60d 方向命中率**（方向組）：
```
hit_60 = (# hit=true in last 60 resolved signals) / (# resolved in last 60)
入榜門檻：n_resolved ≥ 20（不足 20 顯示「累積中」，不參與排名）
```

**輔指標 — 經濟價值（命中時的平均報酬差）**：
```
econ_value_bps（單筆）= predicted_direction × realized_target_return × 10000
EV_60 = mean(econ_value_bps over last 60 resolved)
直覺：每次跟單的期望值（bps）；命中大行情 > 命中小雜訊
```
排名以 `hit_60` 為主鍵、`EV_60` 為次鍵（同命中率時 EV 高者前）；兩者並列顯示，EV 防止「只會猜小波動日」的指標虛胖。

**校準組另立排行**（VaR / 區間類不比方向）：
```
calib_score = |empirical_violation_rate_250d − α|（越小越好）
搭配 rolling Kupiec p-value 顯示；同樣 n ≥ 20 門檻
```

**顯著性標註**：hit_60 對 50% 的 binomial test p-value 上頁面（n=60 時命中 ≥60% 才 p<0.07）— 防止讀者把雜訊當實力，也防我們自己過度宣稱。

---

## 6. 首發指標候選（6 個，OOS 數字已逐一回 results.json 驗證）

### C1. 美股→台股隔夜領先（US→TW Overnight Lead）— 方向組
- **訊號規則**：SPY t−1 日（台北時間今晨 05:00 收盤）close-to-close 報酬 > 0 → 預測 0050.TW 今日（t）close-to-close 上漲；≤ 0 → 下跌。Lag 明確：訊號全部來自 t−1 完成值。
- **預測目標 / horizon**：0050.TW 當日報酬方向；1 個交易日。
- **K 來源 + OOS 證據**：
  - `experiments/k461/k461_ssvs_taiwan_results.json`：SSVS 變數選擇，`SPY_ret_L1` PIP=1.000（OLS t=10.81）— 全部候選變數中唯一必選；樣本 2009-01-13~2026-03-26，T=4204（IS 3429 / OOS 775）。誠實註記：K461 的 OOS QLIKE 是波動率口徑，外生變數未勝空模型 — 方向預測力證據來自 mean equation PIP 與下列兩項。
  - `experiments/k521/k521_2day_momentum_check_results.json`：corr(SPY_{t−1}, TW gap)=0.611，16/16 年皆正（最低年 Sharpe 3.486，gap-only 口徑）；同檔 verdict 明載 alpha 集中在開盤 gap、現貨不可交易。
  - 輔助（knowledge legacy，無三件套）：T5d 2018-2024 全期 Sharpe 1.82（t=8.07，Harvey PASS）。
- **日更資料源**：yfinance `SPY` + `0050.TW`（2026-06-11 實測 OK）。每日台北 07:30 計算（美股 05:00 收盤後、台股開盤前）。
- **Caveat（公開）**：預測力真實但 gap 不可交易（K521/T5e）；Arena 只評方向命中。

### C2. VIX 短端期限結構（log(VIX9D/VIX)）→ SPY 波動方向 — 方向組
- **訊號規則**：log(VIX9D_{t−1}/VIX_{t−1}) > rolling 60d 中位數 → 預測 SPY 未來 5 個交易日 RV 高於前 5 日 RV；反之預測下降。
- **預測目標 / horizon**：SPY 5d realized vol 升/降；5 個交易日。
- **K 來源 + OOS 證據**：`experiments/k1415/k1415_results.json` — HAR-RV + log(VIX9D/VIX)：OOS ΔQLIKE +6.56%，DM t=−7.698（p=1.38e-14），β_tr=+4.04；樣本 2014-02-05~2026-05-29，n_total=3097，OOS 2020-01-02 起 n_oos=1610。verdict=CONDITIONAL_PASS（Codex reviewed）。
- **日更資料源**：yfinance `^VIX9D`、`^VIX`（實測 OK；^VIX9D 偶有 1-2 日 lag → fallback CBOE 官方 CSV `https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX9D_History.csv`，免費日更）。
- **Caveat**：K1415 證據是 QLIKE 連續口徑；方向化（升/降二元）是 Arena 簡化，命中率由 Arena 本身檢驗。

### C3. A4f-VIX9D-t 明日 SPY 2.5% VaR — 校準組
- **訊號規則**：GARCH-X（A4f spec，VIX9D² driver，Student-t）每日 refit/filter 後輸出明日 2.5% VaR；訊號用 t−1 收盤前全部資訊。
- **預測目標 / horizon**：SPY 明日報酬是否跌破 VaR（期望 violation rate 2.5%）；1 個交易日。
- **K 來源 + OOS 證據**：`experiments/k1004/k1004_results.json` — SPY OOS 2019-01-02~2026-04-07（n_oos=1825）：A4f-VIX9D-t QLIKE −8.3947 vs A4f-VIX-t −8.3614（DM t=−4.588, p≈0）vs GJR-t −8.2720（DM t=−6.18）；2.5% VaR scorecard 6/6（violation 2.68%，Kupiec/Christoffersen/DQ/ES 全過，Basel GREEN）。
- **日更資料源**：yfinance `SPY` + `^VIX9D`（實測 OK；fallback 同 C2）。
- **Caveat**：QQQ 上 VIX9D 增益不顯著（DM t=−2.33）— 此指標 SPY-specific，不外推。

### C4. HAR-QR SPY 5% VaR — 校準組
- **訊號規則**：HAR-RV 預測變數上跑 quantile regression（τ=0.05），rolling refit，輸出明日 5% VaR。
- **預測目標 / horizon**：SPY 明日 5% VaR violation 校準；1 個交易日。
- **K 來源 + OOS 證據**：`experiments/K1313/K1313_results.json` — SPY 2010-2024，OOS 2018-01-01~2024-12-31（n_oos=1760，84 refits）：coverage 5.51%（target 5%，Kupiec p=0.3325）vs GARCH-Normal 6.14%（Kupiec p=0.0344）；pinball loss DM t=−2.954（p=0.0031，HAR-QR 勝）。verdict=CONDITIONAL_PASS。
- **日更資料源**：yfinance `SPY`（實測 OK）。
- **Caveat**：與 C3 同 target 不同方法 — 兩個 VaR 指標同台互比正是 Arena 的看點。

### C5. VIX 危機預警（台股風險燈號）— 方向組
- **訊號規則**：VIX_{t−1} 日變化 > +10% 或 VIX_{t−1} > 25 → 亮「風險」燈，預測 0050.TW 今日下跌；否則「正常」燈，預測不跌（≥0）。
- **預測目標 / horizon**：0050.TW 當日報酬方向（條件預警型）；1 個交易日。
- **K 來源 + OOS 證據**：
  - `experiments/k817/k817_vix_taiwan_spillover_results.json`（OTC 報酬口徑，2006-2026，n=4215）：OOS 2023-01-01~2024-12-31（n=481）VIX Spike Guard Sharpe 1.2116 vs BH 1.0271（MDD −7.40% vs −9.27%）；**全期誠實揭露**：spike guard 單獨全期 Sharpe 0.1107 輸 BH 0.1401，Combined guard（VIX>25 | SPY<−2%）全期 0.2434 + MDD −27.7% vs BH −52.9% 才穩定勝 — 故規則採 spike+level 複合而非 spike 單獨。
  - 輔助（knowledge legacy）：N162 — VIX 單日 spike>10% 後 TWII 次日平均 −0.77% vs 平日 +0.03%（334 events，2010-2026）。
- **日更資料源**：yfinance `^VIX` + `0050.TW`（實測 OK）。
- **Caveat**：預警型指標大多數日子預測「不跌」— EV_60 與條件命中率（風險燈亮時的命中率）將分開顯示，防 base-rate 虛胖。

### C6. HAR-RV 分位數區間（QQQ/GLD/TLT q95）— 校準組
- **訊號規則**：HAR-RV 分位數迴歸輸出明日 RV 的 q95 上界；違規 = 明日 realized vol 突破上界（期望 5%）。三資產各自獨立計。
- **預測目標 / horizon**：QQQ/GLD/TLT 明日 RV ≤ q95 上界；1 個交易日。
- **K 來源 + OOS 證據**：`experiments/k1403/k1403_results.json` — OOS 2021-01-04 起 n_oos=1355/資產：q95 empirical coverage QQQ 0.9542 / GLD 0.9506 / TLT（3/3 `tail_status=TIGHT`）；aggregate verdict `TAIL_CALIB_USABLE`（「point forecast 無法超 OLS 但 tail VaR upper bound 可用」）— Arena 只用其 tail 校準面，與原 verdict 完全一致。
- **日更資料源**：yfinance `QQQ`、`GLD`、`TLT`（實測 OK）。
- **Caveat**：point forecast 是 NULL（dm_status=SIG_NEG）— 不得宣稱此指標能預測 RV 水準，只能宣稱區間校準。

### 資料源實測紀錄（2026-06-11，yfinance）
SPY / ^VIX / ^VIX9D / 0050.TW / QQQ / GLD / TLT 全部抓取成功；注意（a）盤中抓取時最後一列可能為未完成 session 的 NaN — pipeline 必須只用已完成收盤列；（b）^VIX9D 偶爾延遲 1-2 日 — 觸發 §4.5 `skipped` 規則或走 CBOE CSV fallback。

---

## 7. 落選與觀察名單（誠實記錄）

| 候選方向 | 不入首發原因（證據） |
|---|---|
| HYG-LQD 信用利差 | K730：Granger 6/6 顯著（如 vmom5_TLT lag7 p=0.0059）但 OOS 經濟價值不顯著（vol composite DM t=−1.45 p=0.146 Harvey FAIL，策略 Sharpe 輸 50/50 與 12/VIX）；K651：credit spread IS t=−2.19 但 OOS 係數翻號；K807 NULL。統計領先 ≠ OOS 預測力 → 不過 §3.1 gate |
| GPR 地緣政治風險指數 | K446：GPR-VIX corr=0.065，控制 VIX 後 partial r 為負號、ΔR²=0.3%；K922：4 個 GPR proxy 合計增量 R² +0.93%，VT overlay +0.005 NS。NULL |
| 當沖比率（TWSE） | 知識庫無任何 K 證據 — 需先開實驗（candidate K：TWSE 當沖比率 → 0050 vol/方向，資料源 `https://www.twse.com.tw/exchangeReport/TWTB4U` 免費日更）再按 gate 審 |
| STLFSI2 金融壓力指數 | G9：唯一過 VIX 控制的總經變數（partial R²=16.5%，OOS R²=0.145）但 FRED 週更 — 不符日更要求；可開週頻副欄位再議 |
| K75 VIX 交通燈 | AUC=0.771 證據僅存 knowledge.json（早期實驗無三件套 results.json）→ 不過 §3.1「可驗證」要求；C5 已覆蓋同方向 |
| VIX term structure（VIX/VIX3M） | K429 NULL（DM 全 p>0.35）、K866 backwardation 1.91x 高 vol 屬 simultaneity 非 prediction — 短端 VIX9D/VIX（C2，K1415）才有 OOS 證據 |

---

## 8. Phase 1b 待辦（本文件不執行）

1. Supabase 三表 + RLS（read public / write service-role only）
2. `scripts/indicator_arena_daily.py`：每日 07:30 台北（compute queue）— 抓數據 → 算 6 指標 → append signals → resolve 到期 reviews → 狀態機判定 → sync
3. 前端 arena 頁（排行榜雙 league + 個別指標頁含全歷史 + delisted 區）
4. 90 天後第一次閾值檢討（§3.2 參數 + §5 公式）
