<!-- AUTO-GENERATED FROM agent-specs/. Edit canonical sources instead. -->

# Publishing Guide

## ⚠️ 標準流程 vs Legacy（必讀）

**✅ 標準發文路徑（實驗完成後發草稿/文章）**
- **One-stop（推薦）**：`uv run python scripts/record_and_publish.py` — 同時寫 `thinking_journal` + `knowledge` + `feed`（格式保證正確）
- **CLI**：`uv run volpred ops publish-milestone --status draft --audience research --title '…' --description '…' --phase '…' --tags '…'`
- **Python**：`Publisher().publish_milestone(title, description, phase, details={}, status='draft')`

**❌ 不要用（legacy，已加 deprecation warning）**
- `uv run volpred publish --experiment-id KXXX` — 此命令 **狀態硬寫 `published`**，無 `--status` / `--audience` / `--tags` 選項。歷史 demo 用途，不是發文標準流程。
- `Publisher().publish_experiment(...)` — 同上，內部硬 coded `status='published'`（`publisher.py:161`），無 status 參數。若要用 experiment 專屬的 pub_id 格式，自行在 milestone 的 `details` 補 `experiment_id`。

**為何要區分**：2026-04-18 smoke test 發現 `volpred publish` 發出後會直接 published + auto-sync Supabase，污染線上 feed；且無法發草稿。`publish-milestone` 才是統一入口。

## Language
All publications: **繁體中文**. Technical terms in English.

## Number Formats
- Price: `round(x, 2)` → $662.29
- Volatility: `round(sigma*100, 1)`% → 15.5%
- Weight: `round(x, 2)` → 0.77
- Return: `.2f`% → +1.23%

## Publishing Methods（參考）

### Python Publisher
```python
from volpred.publisher.publisher import Publisher
pub = Publisher()
# ✅ 標準：含 status / details 完整控制
pub.publish_milestone(title, description, phase, details={}, status='draft')
# ⚠️ legacy：status 硬 coded 'published'，需求複雜時改走 publish_milestone
pub.publish_experiment(experiment_id, title, summary, metrics, tags)
pub.publish_comparison(experiment_ids, title, ranking, analysis, tags)
```

### Legacy POST API (已棄用)
舊版 Express server POST API 已不使用。現在改用 CLI + Supabase sync：
```bash
uv run volpred ops publish-milestone --title "..." --description "..." --phase "..."
```

## 新版平台層發佈

研究完成後，不一定要立即公開。新版流程支援：
- `draft`：先進文章池草稿
- `scheduled`：排程發布
- `release-pool-by-settings`：依節奏設定釋出

當工作涉及平台操作時，優先查看：
- `.claude/skills/admin-ops/references/surfaces.md`
- `.claude/skills/admin-ops/references/platform-api-manual.md`

常用入口：
```bash
uv run volpred ops publish-milestone ...
uv run volpred ops release-pool-by-settings --storage-dir storage
```

## 論文交付（非 feed 發佈）

論文寫作與修訂仍屬研究層，但論文頁 metadata / PDF 交付現在屬平台層：

- 讀論文清單：`uv run volpred ops paper-list`
- 更新 metadata：`uv run volpred ops paper-upsert ...`
- 上傳新版 PDF：`uv run volpred ops paper-upload-pdf --paper-id <id> --file paper/<name>/main.pdf`
- 舊靜態 PDF 搬遷：`uv run volpred ops paper-migrate-storage --paper-id <id>`

若只是論文 metadata / PDF 更新：

- **不需要 redeploy**
- 只有論文頁前端邏輯、樣式、欄位結構改動時才需要部署

## Signal Card (Investment Recommendations)

Front-end auto-detects `phase === 'daily_update'` as pinned signal.

Required `details` fields:
```python
details={
    'date': '2026-03-15',
    'spy_close': 662.29,
    'gld_close': 460.84,
    'sigma_annual': 15.5,
    'slow_vt_weight': 0.77,
    'slow_vt_cash': 0.23,
    'rp_spy_weight': 0.55,
    'rp_gld_weight': 0.33,
    'rp_cash': 0.12,
}
```

### 投資建議 description 必須在第一層完整呈現（不需要點進去）
1. **明確的操作指令**：「減碼至 77% SPY，23% 轉入現金或短期國債」
2. **剩餘部位說明**：weight < 100% →「現金或短期美國國債（如 SHV/BIL ETF）」; weight > 100% →「槓桿借入」
3. **策略說明段落**：解釋為什麼做出此建議（波動率高/低於目標）
4. **數值卡片**：SPY 持倉%、現金/國債%、預測波動率、SPY 收盤價、更新時間

### Weight-based display colors
- weight > 110% → green "加碼至 X% SPY（槓桿 Yx）"
- weight 90-110% → white "維持滿倉"
- weight 50-90% → amber "減碼至 X% SPY，Y% 轉入現金或短期國債"
- weight < 50% → red "大幅減碼...（避險模式）"

### 表現優秀的新策略專文
Sharpe > 0.7 → `publish_milestone` 專文，tags=['策略', '專文']

## Description Format
Supports Markdown + LaTeX (`$\sigma^2_t$`). Keep under 400 chars. Use tables for data.

## Feed Detail Page Rendering Blocks

Front-end renders the following blocks in order (provide as many as applicable):

1. **Hero Metrics** (核心指標卡片): Put top 3-5 numbers in `metrics` dict. Key = short name (e.g., `qlike`, `sharpe`, `var_1pct`), value = float.

2. **Ranking** (comparison category): Provide `ranking` list with `rank`, `model`, plus numeric fields. Top 3 auto-show medals.

3. **Analysis** (`description` or `analysis`): Concise markdown (200-400 chars). Tables, bold, LaTeX supported.

4. **VaR/ES Backtest Table**: If `metrics` contains `var_es`, front-end auto-renders a backtest table with Pass/Fail color badges. Format:
```python
metrics={'var_es': {
    'var_1pct': {'expected': 1.0, 'actual': 1.6, 'pass': True},
    'var_5pct': {'expected': 5.0, 'actual': 4.8, 'pass': True},
    'es_ratio': 0.92,
    'kupiec_pval': 0.34,
    'christoffersen_pval': 0.18,
}}
```

5. **Details** (`details` dict): Key-value supplementary info (strategy params, compute time, data range, etc.)

## Dollar Amounts
涉及策略報酬的發佈，除百分比外也要提供金額比較（假設初始 100 萬元），格式如「投入 100 萬，5 年後變成 151.6 萬」。

## Performance Metrics (categorized)
報酬面 + 風險面必須同時呈現：
- **報酬**: Total Return, Ann. Return
- **風險調整**: Sharpe, Sortino, Calmar
- **風險**: Ann. Vol, MaxDD, VaR 95%/99%, CVaR 95%/99%, Worst Day
- **交易品質**: Win Rate, Profit Factor, Tail Ratio

## Strategy Reports
Must include: logic, trade rules, frequency, turnover, pre/post-cost returns, full metrics (above), dollar amounts ($1M basis), annual breakdown.

## 研究長文（Research Reports）
累積足夠發現時，彙整寫出有深度的長文。類型包括：
- **研究報告**：Phase 完成後的完整實證分析
- **研究教學**：方法論解說（如 GARCH 為什麼需要 500+ 樣本、EMD 如何分解波動率）
- **研究心路歷程**：假說→矛盾→修正的推理過程，展示真實研究如何推進

網頁分頁是**分類系統**——一旦建立某個分頁，以後同類型的內容都要放在該分頁。**不要濫增分頁**，只在確實有必要且有足夠內容支撐時才新增。

## 風險預報頁面（Risk Forecast Dashboard）

在網頁上新增風險預報頁面，提供隔日、隔週、隔月的波動率與風險預測。呈現方式類似策略頁面——給出關鍵指標和簡短說明。

### 預報時間維度
1. **隔日（Next Day）**：GJR-GARCH 1-step ahead σ forecast
2. **隔週（Next Week）**：5-step ahead 累積波動率 σ_week = σ_daily × √5
3. **隔月（Next Month）**：22-step ahead σ_month = σ_daily × √22

### 關鍵指標（Hero Metrics 呈現）
- **預測波動率**（日/週/月，年化%）
- **VaR 1%**（最大可能日損失，金額 based on $1M）
- **ES 1%**（條件尾部損失）
- **波動率 regime**：低（<12%）/ 正常（12-20%）/ 高（20-30%）/ 極端（>30%）
- **Basel III Zone 狀態**：當年 YTD Green/Yellow/Red

### 說明區塊
- 簡短解釋當前市場狀態（2-3 句）
- 與歷史均值比較（如「當前波動率高於 5 年均值 1.2 個標準差」）
- 風險警示（如有 overnight gap >1.5% 或 jump frequency 升高）

### 數據來源
- 使用 GJR-GARCH(1,1) w=504 + Student-t(df≈5) 作為核心模型
- 每日更新（可整合進 daily_update.py 或獨立 API endpoint）
- 歷史波動率走勢圖（Recharts line chart）

### API Endpoint
```
GET /api/risk-forecast
Response: {
  date: "2026-03-15",
  asset: "SPY",
  current_price: 662.29,
  forecasts: {
    daily: { sigma_ann: 15.5, var_1pct: 2.05, es_1pct: 2.56 },
    weekly: { sigma_ann: 15.5, var_1pct: 4.59, es_1pct: 5.73 },
    monthly: { sigma_ann: 15.5, var_1pct: 9.55, es_1pct: 11.92 }
  },
  regime: "normal",
  basel_zone: { year: 2026, violations: 1, zone: "GREEN" },
  sigma_history: [{ date: "...", sigma: ... }, ...],  // 最近 60 天
  alerts: []
}
```

### 前端頁面路徑
`/frontend/src/app/risk-forecast/page.tsx`

### 顏色規則（與策略頁面一致）
- 低波動（<12%）→ green（安全）
- 正常（12-20%）→ white/neutral
- 高波動（20-30%）→ amber（警戒）
- 極端（>30%）→ red（危險）
