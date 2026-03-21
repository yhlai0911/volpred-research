---
description: "發佈研究成果到 Web 平台（本地 + Zeabur）。格式規範、API 端點、雙重發佈。用法: /publish"
---

# 研究成果發佈系統

## 發佈架構

```
Claude Code (研究引擎)
  ↓
Publisher / volpred ops (平台層入口)
  ├→ 寫入 storage/ (本地源頭)
  ├→ 依需求進入文章池（draft / scheduled）
  └→ 視設定 sync 到 Supabase / 遠端站

平台操作層
  ├→ /admin/content
  ├→ /api/admin/content
  └→ uv run python -m volpred.cli ops release-pool-by-settings
```

## 發佈方式

### 1. Python Publisher（主要方式）
```python
from volpred.publisher.publisher import Publisher
pub = Publisher()

# 里程碑
pub.publish_milestone(
    title='標題（繁體中文）',
    description='Markdown 內容（支援表格、LaTeX）',
    phase='research_phase',
    details={'key': 'value', 'weight': 0.77},
)

# 實驗結果
pub.publish_experiment(
    experiment_id='abc123',
    title='實驗標題',
    summary='一行摘要',
    metrics={'qlike': -9.034, 'sharpe': 0.59},
    tags=['SPY', '實驗'],
)

# 模型比較（帶排行榜）
pub.publish_comparison(
    experiment_ids=['id1', 'id2'],
    title='比較標題',
    ranking=[{'rank': 1, 'model': '...', 'qlike': -9.034}],
    analysis='Markdown 分析內容',
    tags=['比較'],
)
```

### 2. 平台層發佈（推薦）

```bash
uv run python -m volpred.cli ops publish-milestone --title "標題" --description "內容" --phase "Phase_X"
uv run python -m volpred.cli ops release-pool-by-settings --storage-dir storage
```

### 3. POST API（從外部發佈，如本地 → Zeabur）
```bash
curl -X POST https://volpred-research.zeabur.app/api/publications/publish \
  -H "Content-Type: application/json" \
  -d '{
    "title": "標題",
    "description": "內容",
    "phase": "daily_update",
    "details": {"weight": 0.77}
  }'
```

### 4. 雙重發佈（本地 + 遠端同時）
```bash
export VOLPRED_REMOTE_URL=https://volpred-research.zeabur.app
```
設定後，Publisher 每次寫入 storage/ 的同時，自動 POST 到遠端。

## 發佈模式

- `立即發布`：立即對外可見
- `draft`：先進文章池草稿
- `scheduled`：排程等待釋出
- `release-pool-by-settings`：依平台節奏設定釋出

若任務涉及文章池、排程、節奏控制、下架、清理，請優先參考 `admin-ops` skill，而不是只把它當成單次 publish 指令。

## 發佈格式規範

### 語言
所有發佈內容必須使用**繁體中文**。

### 數值格式
- 股價：`round(price, 2)`（如 $662.29）
- 波動率：`round(sigma*100, 1)`%（如 15.5%）
- 權重：`round(weight, 2)`（如 0.77）
- 報酬率：`.2f`%（如 +1.23%）

### 投資建議（daily_update phase）
前端 SignalCard 自動辨識 `phase === 'daily_update'` 的最新一則置頂。

details 必須包含：
```python
details={
    'date': '2026-03-15',
    'spy_close': 662.29,
    'gld_close': 460.84,
    'sigma_annual': 15.5,
    # 策略一
    'slow_vt_weight': 0.77,
    'slow_vt_cash': 0.23,
    # 策略二
    'rp_spy_weight': 0.55,
    'rp_gld_weight': 0.33,
    'rp_cash': 0.12,
}
```

### 策略專文
表現優秀的新策略需要專文，包含完整操作手冊（見 research skill Step 10）。

### description 格式
支援 Markdown + LaTeX：
- 表格 `| col1 | col2 |`
- 粗體 `**text**`
- LaTeX `$\sigma^2_t$`
- 程式碼 `` `code` ``

### 排行榜（comparison 類別）
ranking list 中的前 3 名自動顯示🥇🥈🥉。

## API 端點

| Method | Path | 說明 |
|--------|------|------|
| GET | /api/publications/feed | 取得所有發佈 |
| GET | /api/publications/feed/{id} | 取得單一發佈 |
| POST | /api/publications/publish | 從外部發佈新項目 |
| GET | /api/admin/content | 內容工作台資料 |
| GET | /api/admin/analytics/summary | 平台摘要 |
| GET | /api/admin/questions/summary | 問題排行摘要 |
| GET | /api/research/thinking | 思考日誌 |
| GET | /api/research/questions | 研究問題 |
| GET | /api/research/paper-trading | Paper trading 記錄 |
| GET | /api/research/summary | 研究摘要 |
| GET | /api/health | 健康檢查 |

## 部署更新流程
見 `/deploy` command。
