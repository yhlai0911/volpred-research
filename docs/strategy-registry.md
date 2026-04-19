# Strategy Registry

## 目前 STRATEGY_REGISTRY（14 筆，11 個 active / 3 個 disabled；verified 2026-04-19 18:48 UTC 對齊 `scripts/daily_update.py:29-48`）

| key | display_name | is_active | order |
|-----|-------------|-----------|-------|
| `slow_vt` | GARCH VT (SPY) | True | 0 |
| `risk_parity` | Risk Parity (SPY+GLD) | True | 1 |
| `simple_12vix` | 12/VIX (SPY) | True | 2 |
| `recommended_5050` | 50/50 SPY/GLD | True | 3 |
| `taiwan_8.63vix` | 台灣 VT (0050.TW) | True | 4 |
| `taiwan_spy_momentum` | 台股動量 (0050.TW) | False | 5 |
| `tz_tw_jp_5050` | TW+JP 50/50 TZ | False | 6 |
| `global_vt_tz` | Global US VT + TW TZ | False | 7 |
| `vix_leading_guard` | VIX+景氣領先 (0050.TW) | True | 8 |
| `vix_cond_leverage` | VIX 條件槓桿（月頻） | True | 9 |
| `taiwan_hybrid_leverage` | 台股混合槓桿 | True | 10 |
| `piecewise_conservative` | 保守型 VT（Piecewise） | True | 11 |
| `fear_dca` | 恐慌加碼定期定額 | True | 12 |
| `adaptive_tier` | 自適應三階 VT | True | 13 |

## 策略上架標準（統一、可量化、不可跳步）

**回測可以用任何期間探索，但上架決定基於以下統一標準：**

### 前端顯示期間
- **COMMON_START = 2023-01-04 ~ 今天**（約 3 年）
- 所有策略的績效數字、圖表、排名都基於這個期間
- 新策略必須在這個期間模擬 returns 來做公平比較

### 上架必須通過的 5 項檢驗（ALL PASS 才可上架）

| # | 檢驗 | 通過標準 | 工具 |
|---|------|---------|------|
| 1 | **同期間比較** | `evaluate_new_strategy.py` Sharpe **>= 已上架策略中位數**（不需要 #1，差不多就行） | `uv run python scripts/evaluate_new_strategy.py` |
| 2 | **Cross-OOS** | 5 個非重疊 2 年期間，勝 BH 50/50 **>= 3/5** | 回測腳本（可用 2006-2026） |
| 3 | **Codex 審查** | 無 HIGH severity bug（lag/lookahead/TX） | `/codex:rescue` 或 `codex exec -s read-only` |
| 4 | **Sensitivity** | 參數 +-20% 變動後 Sharpe 不降 > 30% | 回測腳本 |
| 5 | **MDD 可接受** | 同期間 MDD **< -20%** | `evaluate_new_strategy.py` 輸出 |

### 策略生命週期
- **舊策略不因新策略而下架**——持續 forward tracking，績效每天更新
- **新策略是「加入」不是「取代」**——門檻是「跟現有差不多」不是「打敗所有」
- **下架條件**：`is_active=False` 只在策略有結構性問題時（bug、資產停牌、邏輯錯誤），極少發生
- **績效異常注記**：若策略近 6 個月 Sharpe 顯著偏離歷史均值（如從 2.0 降到 0.5），在前端策略卡片加注記「近期表現顯著偏離歷史」，提醒投資人注意。不下架，但要透明揭露

### 上架後流程
1. 加入 `STRATEGY_REGISTRY`（daily_update.py）
2. 加入計算邏輯到 strat_list
3. 執行 `list_new_strategy.py`（寫 DB + 回填 paper_trading + recalc_metrics -> 自動 sync）
4. 發佈 Feed 文章
5. **不修改歷史數據**：新策略從加入日起 forward tracking

### 重要原則
- **回測期間 != 顯示期間**：回測用長期（2006-2026）探索，但排名用 COMMON_START 同期間
- **不修改歷史數據**：forward tracking 讓 metrics 自然收斂
- **Metrics 是數據衍生品**：`recalc_metrics.py` 是唯一寫入路徑，自動 sync Supabase

## 新策略上線標準程序（發現有效策略後執行）
**不要輕易上架——交易策略必須多次確認，上架後發現錯誤會損害信譽。**

**研究驗證階段（手動）：**
1. **Cross-OOS 驗證**：至少 5 個 OOS 期間（J9 教訓：單期 OOS 不可靠；K459/K474/K476 教訓：cross-OOS 抓到 53% false positive）
2. **3 年回測**：計算 Sharpe/MDD/Calmar/Sortino/Net Sharpe (after TX)
3. **Sensitivity 分析**：不同 TX cost、不同 rebalancing 頻率（K499）、不同起始日期
4. **Out-of-sample 最終確認**：在最近 6 個月的真實數據上確認（不是回測）
5. **加入 STRATEGY_REGISTRY**：`daily_update.py` 頂部加一行 (display_name, is_active, order)
6. **加入計算邏輯**：`daily_update.py` 的 strat_list 區塊

**平台上架階段（自動化腳本）：**
7. **執行 `list_new_strategy.py`**（一鍵完成 DB 寫入 + 指標計算 + Supabase 同步 + 驗證）：
```bash
uv run python scripts/list_new_strategy.py \
  --key strategy_key \
  --name "顯示名稱" \
  --howto "一行操作說明" \
  --description "完整操作說明" \
  --assets '{"SPY": 50, "GLD": 50}' \
  --order N
```
腳本自動執行：strategy_signals upsert -> display_order 設定 -> 回測資料檢查 -> strategy_metrics 重算 -> strategy_metrics_cache upsert（含 sparkline）-> paper_trades sync -> 全面驗證

8. **驗證已上線策略**：`uv run python scripts/list_new_strategy.py --key xxx --verify-only`
9. **查看所有策略狀態**：`uv run python scripts/list_new_strategy.py --list-all`
10. **更新 CLAUDE.md 策略表 + research_program.md**
11. **發佈 Feed 文章**：用 `feed-publisher` skill
- 詳細流程見 `.claude/skills/autonomous-research/references/add-strategy-guide.md`
