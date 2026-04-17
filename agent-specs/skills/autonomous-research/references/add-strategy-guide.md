# 新增交易策略完整流程

## 架構
- 策略 metadata 全部存在 Supabase `strategy_signals` 表（strategy_key, strategy_name, description, howto, color, articles）
- **前端從 DB 讀取，不需改代碼、不需重新部署**
- 加新策略 = 寫 DB + 加計算邏輯到 daily_update.py + 跑回測

## 上架標準（5 項全部通過才可上架，見 {{GUIDE_FILE}}「策略上架標準」）

| # | 檢驗 | 通過標準 |
|---|------|---------|
| 1 | 同期間比較 | `evaluate_new_strategy.py` Sharpe **≥ 已上架策略中位數** |
| 2 | Cross-OOS | 5 個非重疊 2yr 期間，勝 BH 50/50 **≥ 3/5** |
| 3 | Codex 審查 | 無 HIGH severity bug |
| 4 | Sensitivity | 參數 ±20% Sharpe 不降 >30% |
| 5 | MDD | 同期間 **< -20%** |

**回測期間 ≠ 顯示期間**：回測可用 2006-2026 探索，但排名和上架決定用 COMMON_START（2023-01-04）~ today。

## ⚠️ 不修改歷史數據原則
- 新策略從加入 paper_trading.json 的日期起 forward tracking
- **不修改已上架策略的歷史 portfolio_return**——歷史數據反映當時追蹤的結果
- 如需比較，用 `evaluate_new_strategy.py` 在同期間模擬，不改原始數據
- `recalc_metrics.py` 每次執行自動 sync 到 Supabase（不需手動 PATCH）

## 完整步驟

### Step 0: 同期間比較（新增，不可跳過！）
```bash
uv run python scripts/evaluate_new_strategy.py --example  # 測試工具
# 或 import evaluate_new_strategy 寫自訂 weights_func
```
新策略必須在同期間（2023-01-04~today）排名前 3 才進入 Step 1。

### Step 1: 發 Feed 文章（必須先於上線）
```
Skill(skill="feed-publisher", args="策略名稱 + 回測結果 + 操作說明")
```

### Step 2: 3 年回測
用 Agent worktree 跑 2023-01-02 至今的回測。參考 `scripts/backtest_3yr_final.py` 的結構：

```python
# Agent prompt 範例：
Agent(isolation="worktree", prompt="""
回測 strategy_id 從 2023-01-02 到 2026-03-16。

資料：
  dm = DataManager()
  spy = dm.get_model_data("SPY", "2015-01-01", "2026-12-31")
  vix = dm.get_model_data("^VIX", "2022-01-01", "2026-12-31")

策略邏輯：（填入具體公式）
  w = min(12/VIX, 1.0)  # 範例

報酬計算：
  portfolio_return = Σ(weight_i × next_day_return_i)
  注意跨市場時間規則（參考 references/data-timing.md）

輸出到 storage/paper_trading_new.json
""")
```

回測完後：
1. 合併到 `storage/paper_trading.json`
2. 跑 `uv run python scripts/recalc_metrics.py` 更新績效指標
3. `recalc_metrics.py` 會自動同步到 active frontend 的 configured metrics target（由 `config/project_targets.json` 控制；目前是 `frontend-v2-fix/data/strategy_metrics.json`）

### Step 3: 寫入 DB（不需改前端代碼）
```bash
uv run python scripts/add_strategy.py \
  --id "strategy_id" \
  --name "顯示名稱" \
  --howto "一行操作說明" \
  --description "完整操作說明" \
  --color "#10B981" \
  --assets '{"SPY": 50}' \
  --order N \
  --articles '[{"id":"mile_xxx","title":"文章標題"}]'
```

這個腳本只寫 Supabase `strategy_signals` 表。**不碰前端檔案，不需重新部署**。

### Step 4: daily_update.py — 加計算邏輯 + 註冊策略

**⚠️ 策略 metadata 統一由 `STRATEGY_REGISTRY` 管理（檔案頂部）。**
新增策略需改兩處：

```python
# 1) 在 STRATEGY_REGISTRY 加一行（檔案頂部，唯一 metadata 來源）
STRATEGY_REGISTRY = {
    ...
    "strategy_id": ("顯示名稱", True, N),  # (display_name, is_active, supabase_order)
}

# 2) 在 strat_list 區塊加入計算邏輯
try:
    w_new = round(計算邏輯, 2)
    strat_list.append(("strategy_id", {"資產": w_new}))
    print(f"  新策略: {w_new*100:.0f}%")
except Exception as e:
    print(f"  新策略: error ({e})")
```

Registry 驅動三件事：
- **Feed 文章**：只列 `is_active=True` 的策略，用 `display_name`
- **Supabase signals**：全部同步（inactive 在面板隱藏），用 `display_name` + `display_order`
- **Paper trading**：全部記錄（不受 is_active 影響）

**不再需要手動維護 `all_signals` 列表或 `tz_biased_names` 集合。**

### Step 5: 同步數據到 Supabase
```python
# Paper trading 數據
from scripts.supabase_sync import _post
import json
pt = json.loads(open('storage/paper_trading.json').read())
_post('paper_trades', {'strategy': 'strategy_id', 'entry': pt['strategy_id'], 'trade_date': '2026-03-17'})
```

`strategy_metrics.json` 會自動同步到 active frontend configured target；不要手動複製到 `frontend-v2/data/`。

### Step 6: 驗證（不需部署）
刷新網站即可看到新策略：
- [ ] 投資建議面板顯示新策略（含 3yr 報酬/Sharpe/MDD）
- [ ] 面板卡片點擊跳到 Portfolio 對應策略
- [ ] Portfolio 顯示 12 項專業績效指標
- [ ] Portfolio 有操作說明 + 研究依據文章連結
- [ ] 價值圖從 $1,000,000 起始正確
- [ ] 交易紀錄可收合
- [ ] daily_update.py 隔天能正確計算新策略權重

## 上線後的自動化（全自動，不需手動介入）
- `daily_update.py`（每天 06:03）：
  1. 計算當日各策略權重
  2. 記錄 paper trading entry（含 portfolio_return）
  3. 同步 strategy_signals 權重到 Supabase
  4. **自動呼叫 `recalc_metrics.py` 重算所有績效指標**（Sharpe/MDD/Sortino 等）
- `supabase_sync.py`（每小時 :17）：全量同步 storage/ → Supabase
- 績效指標也可手動重算：`uv run python scripts/recalc_metrics.py`

## 命名規則
| 位置 | 用什麼 | 範例 |
|------|--------|------|
| `--id`（strategy_key） | snake_case 英文 | `tw_jp_5050_tz` |
| `--name`（strategy_name）| 中英混合 | `TW+JP 50/50 TZ` |
| 前端 anchor | strategy_key（自動） | `#tw_jp_5050_tz` |
| strategy_signals DB | strategy_name + strategy_key | 兩個都存 |
| paper_trades DB | strategy_key | `tw_jp_5050_tz` |
| daily_update strat_list | strategy_key | `tw_jp_5050_tz` |
| **STRATEGY_REGISTRY** | strategy_key → (display_name, is_active, order) | 唯一 metadata 來源 |

## 下架策略
```bash
uv run python scripts/add_strategy.py --deactivate "策略名稱"
uv run python scripts/add_strategy.py --activate "策略名稱"   # 恢復
```
`is_active=false` 的策略不會出現在面板，但 paper_trading 資料保留。

## 注意事項
- **不需重新部署前端**——所有策略資訊從 DB 讀取
- 所有策略必須有研究依據（feed 文章），不放未經驗證的策略
- 時間處理參考 `references/data-timing.md`
- 跨市場策略注意 VIX lag（台股用前一天 VIX）
- **⚠️ 跨時區策略必須驗證 open-to-open 報酬**（I8 教訓：c2c 含 timing bias，gap 吸收大部分 alpha）
- 回測用 `portfolio_return`（加權後組合報酬），不是單一資產 return
- 每個策略的 `--order` 不要重複
- `STRATEGY_REGISTRY` 是策略 metadata 唯一來源。display_name、is_active、order 只在那裡改

## 回測品質檢查（必做，歷史教訓）
回測完成後，合併前**必須**做以下檢查：

1. **假日檢查**：如果某資產價格跟前一天一樣 → 該日 return 必須 = 0（非交易日）
   ```python
   if curr_price == prev_price:
       actual_return = 0  # 假日，沒有交易
   ```

2. **價格完整性**：每筆 entry 的 spy_close、gld_close、tw50_close、nk225_close 都要有值。
   缺值用前一交易日 forward-fill，但 return 必須反映實際交易（非交易日 = 0）

3. **跨市場日期對齊**：不同市場的交易日不同。用各自市場的 return，不要混用日期。
   - 台灣假日但美股有交易 → 0050 return = 0，SPY return 正常
   - 美股假日但台灣有交易 → SPY return = 0，0050 return 正常

4. **數字精度**：VIX round(2)、sigma round(1)、price round(2)、return round(6)

5. **前瞻偏誤**：weight(T) 只能用 T 及之前的數據計算，return 用 T+1 的價格
