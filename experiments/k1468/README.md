# K1468 — CTA/Managed-Futures ETF vs SPY: drawdown 描述統計

- **Experiment ID**: K1468
- **Type**: Descriptive analysis (no model, no statistical test)
- **Verdict**: PARTIAL_CONFIRM — CTA proxies dd 較淺、較不頻繁，但 cost = 長時間困在 dd 中
- **Sample**: 2020-12-04 → 2026-06-10（5.52 yr，overlap window）；SPY baseline 2010-01 起
- **Data source**: yfinance Close (auto_adjust=True)
- **Tickers**: SPY, KMLM (KFA Mt Lucas MFI, 上市 2020-12), DBMF (iMGP DBi MF, 上市 2019-05)

## 研究問題

FAJ / Man Group / AlphaSimplex 2025 managed-futures literature 主張 trend-following / CTA 策略
drawdown「頻繁但淺」(frequent shallow drawdowns)。本實驗以**免費可得 ETF 代理**檢視此宣稱
在 2020-12 至今窗口是否成立，提供 hedge / diversifier 配置討論的實證 baseline。

## 方法

- **drawdown** = price / cummax − 1（每日，lookahead-safe）
- **episode** = dd 跌破 −5%（threshold）→ 回到 0（recovery to running max）
- 統計：n_episodes / episodes_per_year / mean & median depth / mean & median duration / mean & median recovery days / max_dd / pct_time_below_threshold / depth_bins
- 共同 overlap window 比較三檔；SPY full 2010-至今 為背景對照

## 結果（overlap 2020-12 → 2026-06）

| 指標 | SPY | KMLM | DBMF |
|---|---|---|---|
| 5.52 年 episodes 數 | 7 | 5 | 5 |
| 每年 episodes | 1.27 | 0.91 | 0.91 |
| 平均深度 | −10.9% | −8.4% | −9.1% |
| 中位深度 | −8.4% | −6.2% | −6.2% |
| 平均持續天數 | 93 | 53 | 199 |
| 平均 recovery 天數 | 62 | 41 | 176 |
| max DD | −24.5% | −31.0% | −20.4% |
| % 時間在 −5% 以下 | 34.6% | 77.0% | 51.5% |

**Depth bins（−5~−10% / −10~−20% / 更深）**：
- SPY: 5 / 1 / 1
- KMLM: 4 / 1 / 0
- DBMF: 4 / 0 / 1

## 解讀

**「頻繁但淺」claim 部分驗證**：
- ✓ **較淺**：CTA proxies 平均深度 −8 ~ −9% < SPY −10.9%；中位 −6.2% < SPY −8.4%。沒有 −20% 以下 ep（DBMF 一次 −20.4% 算 marginal），SPY 有 −24.5%。
- ✗ **不更頻繁**：episodes_per_year CTA 0.91 < SPY 1.27（CTA 反而少）。Literature 的「頻繁」可能指 1m 內 minor pullback；以 5% threshold 看 CTA 反而 fewer episodes。
- ⚠️ **代價**：CTA 大部分時間都在 dd（KMLM 77%、DBMF 51% vs SPY 35%）；DBMF 平均單次 199 天才 recover、KMLM 雖快（53 天）但 max_dd 反而 −31%（單筆深於 SPY）。

**對 vol-target / hedge 配置的 implication**：
- 想當 SPY 的 diversifier 不能只看「max_dd 較淺」就配，要同時看「return」（本實驗未做）+「recovery 速度」。
- DBMF 的 199 天平均 duration 暗示其 trend signal lag 讓 reversion 期拖很久；KMLM 41 天 recovery 較快但 max_dd 較深 → 兩支 CTA proxy 不可互換。
- 本實驗**未檢驗 Sharpe / 終值 / vol-scaled return** — 純 dd 形態描述。K-followup 可加 return + Sharpe + DM test。

## Lookahead / 防錯確認

- ✓ cummax 只用 ≤t 歷史，lookahead-safe
- ✓ 無 model fitting，無 seed 需求
- ✓ 無 train-test split
- ✓ 全 yfinance 免費 data，可復現
- ✓ overlap_window dd 從 overlap_start 起算（局部 max），公平比較

## 已知 caveat

1. **窗口短**：5.5 年只 covers 1 個 cycle（COVID + 2022 bear + 2023-24 bull）。長期 conclusion 弱。
2. **代理 ETF ≠ 真 CTA**：KMLM 跟蹤 Mt Lucas index 是被動 systematic；DBMF 是 sub-strategy replication；真實 BlueTrend / Man AHL 等 active CTA 表現可能不同。
3. **未做 return / Sharpe 比較**：純描述。下一輪可加 vol-scaled + Sharpe + DM。
4. **threshold 敏感**：−5% 是常用值；改 −10% / −3% 結果可能變。

## 檔案

- `k1468.py` — 實驗腳本
- `k1468_results.json` — 完整數值（episodes 樣本 + full stats）
- `k1468_drawdown_comparison.png` — 三條 drawdown time series 對照圖

## Related K

- K577 / K544 / K657 — vol-target / tail-hedge SPY 系列（不同 hedge 工具）
- K1467 — Tail-Hedging Overlay (VXX) on SPY（同期間 hedge benchmark）

## 後續

可發 article（reader-facing）— 切角：「CTA ETF 真的更穩嗎？看 KMLM/DBMF 5 年 drawdown vs SPY」。
研究 K-followup：加 vol-scaled return + Sharpe + DM test → 真實 diversification benefit 量化。
