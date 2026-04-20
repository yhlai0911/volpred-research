# Event Article Templates（事件驅動文章 populate playbook）

這檔是 `.claude/rules/control-plane.md` 的詳細補充，只在 `feed-publisher` / `publication-candidates` skill 觸發或主動 Read 時才載。

寫 FOMC / CPI / NFP / Earnings / 央行決議 / 地緣政治等事件驅動文章前必讀，規範每類 event 的 `event_jobs` populate schema、T-series slot 配額、ROI 優先序。

---

## Standard event pattern（CPI/NFP/FOMC/Earnings 共用，2026-04-20 canonical）

**原則**：每類 recurring macroeconomic event / 企業事件用相同 4-field id scheme + T-series slots 管理文章配額。複製對應 template 修 date/asset 即可 populate。

### 命名規則

- `id`: `<event-type>-<YYYY-MM-DD>-<slot>` e.g. `cpi-us-2026-05-13-t2`, `nfp-2026-05-02-t0`, `tsmc-earnings-2026-07-17-t7`
- `event_key`: `<TYPE>_<YYYY_MM_DD>` e.g. `CPI_US_2026_05_13`（允許同一事件多個 entries 聚類）
- `dedupe_key`: `<id>:one_shot`
- `trigger_mode`: `"one_shot"`（目前僅此型；未來 `recurring` 保留擴充）

### T-series slots（per 事件驅動配額）

| slot | `not_before` 建議 | `deadline` | priority | audience | 差異化主軸 |
|------|----------------|------------|----------|----------|-----------|
| T-7  | event_date - 7d 08:00 CST | T-7 + 24h | 30 | research/general | 歷史 baseline + regime 比較 |
| T-2  | event_date - 2d 00:00 CST | T-2 + 24h | 20 | general | scenario 具體數字 grid + position sizing |
| T+0  | event_date 當日 announce 後 | T+0 + 24h | 15 | general | 實際 vs 預期 + dot-plot / 數字 reconcile |
| T+1  | event_date + 1d 08:00 CST | T+1 + 24h | 25 | research | 市場消化 + 隔日 drift 統計（可選） |

### 配額 cap

同一 `event_key` 總 entries ≤ 4。T-7/T-2/T+0 為 core 三篇，T+1 選配。`payload_patch.event_series_slot` 必填以便 dedup audit。

---

## 事件類型檢查清單（populate 前每類必做）

### 1. FOMC
- 頻率：8 次/年
- 時間：US 下午公佈 UTC+21:00 → CST 隔日 02:00 早上
- 核心 data source：CME FedWatch implied prob / dot plot median
- 典型 prior_articles：VIX term structure、94.x% hold baseline
- Precondition：`US market hour awareness`（T+0 寫作需等 announce）

### 2. US CPI
- 頻率：每月 10-15 日
- 時間：08:30 ET = CST 當日晚 8:30
- 核心 data source：BLS CPI headline + core YoY/MoM，FRED CPILFESL
- Angle：inflation surprise → breakeven inflation / TIPS reaction
- T+0 `not_before`：announce 後 1h（收集實際數字）

### 3. US NFP
- 頻率：每月第一週五
- 時間：08:30 ET
- 核心：BLS Employment Situation headline NFP + unemployment + wage growth
- Angle：labor market tight/soft → Fed path / SPY/VIX reaction
- T+0 時差同 CPI

### 4. Earnings（TSMC / NVDA / AAPL / 0050 成份股）
- Schedule source：Nasdaq earnings calendar / 台股財報公告日.txt
- Angle：pre-earnings IV crush / post-earnings drift / K1107 foundry fabless type effect
- Precondition：earnings_date confirmed from primary source（公告變動常見）
- **特別小心**：單家公司 ≤ 3 篇（TSMC 2026-04-13 5-fold 過載教訓），連同 sector 同日報 ≤ 5 篇

### 5. 央行決議（ECB / BOJ / PBoC）
與 FOMC 同 pattern。

### 6. 地緣政治 / 能源（OPEC+、關鍵制裁）
無 T-series 結構因不可預期，改用 ad-hoc `payload_patch.urgency=breaking`。

---

## Populate workflow

```
1. 主線程確認事件日期（WebSearch 官方 schedule）
2. 複製對應 T-series template 到 config/runtime_schedules.json event_jobs.items
3. 修 id / event_key / dedupe_key / not_before / deadline / payload_patch
4. uv run python -c "from volpred.ops import preview_event_jobs; import json; print(json.dumps(preview_event_jobs(), ensure_ascii=False, indent=2))" 驗 status=pending
5. 對應 memo 寫到 storage/next_draft_candidate_<event>_<slot>.md（選題軸 + 3-layer dedup checklist）
6. Git commit 整組
```

---

## ROI 優先序（cycle 太多事件 overwhelm 時）

FOMC > US CPI ≥ US NFP > 台股旗艦財報（TSMC/Hon Hai/MediaTek）> 其他 mega-caps earnings > ECB/BOJ > 次要 macro。

---

## 已 populate 範例（2026-04-20）

- `fomc-2026-04-29-t2`
- `fomc-2026-04-29-t0`
（round 13 round-6 empty-canonical gap fix 之後補上的。）
