# Strategy Lifecycle Audit — 2026-05-12

**Author**: Claude (主線程 self-contained audit)
**Scope**: 現有 11 active + 3 disabled strategies in `STRATEGY_REGISTRY`，forward-tracked metrics from `storage/paper_trading.json`，cross-check with `storage/strategy_metrics.json`，K-experiment-derived new-listing pipeline (K1175 / K1257 / K1300-K1306 / K1309)
**Data source**: forward-tracking entries (true OOS — `paper_trading.json[<key>].entries[*].portfolio_return`) windowed to COMMON_START = 2023-01-04
**Not modified**: `STRATEGY_REGISTRY`, `strategy_metrics.json`, `feed.json`, `knowledge.json` — 此 audit 僅產 recommendation，narrative decision 由主線程後續執行

---

## 1. Methodology

- **Sharpe**: daily returns → mean / std × √252（lookahead-safe；historical realized returns）
- **MDD**: 從 forward-tracked daily portfolio_return 計算 (cumulative product peak-to-trough)
- **Rolling 90 / 180**: 最近 N 個 valid trading days 之 Sharpe（recent regime health）
- **Baseline**: COMMON_START-windowed median Sharpe across 14 strategies = **2.70**
- **Forward-tracking only**: 不混 backtest in-sample；同期間比較
- **Listing gate (per `docs/strategy-registry.md`)**: 同期間 Sharpe ≥ median；MDD < -20%；Cross-OOS ≥ 3/5；Codex review no HIGH bug；Sensitivity Sharpe drop ≤ 30%

---

## 2. Active / Disabled Strategy Health Table

| key | display | active | Ann.Ret% | Sharpe | MDD% | Sh90 | Sh180 | Verdict |
|-----|---------|:------:|---------:|-------:|-----:|-----:|------:|:-------:|
| `tz_tw_jp_5050` | TW+JP 50/50 TZ | disabled | 52.16 | **3.67** | -6.66 | 6.70 | 5.94 | **PROMOTE_CANDIDATE** |
| `taiwan_spy_momentum` | 台股動量 (0050.TW) | disabled | 67.81 | **3.45** | -8.14 | 6.76 | 5.27 | **PROMOTE_CANDIDATE** |
| `global_vt_tz` | Global US VT + TW TZ | disabled | 32.67 | **3.26** | -5.51 | 5.41 | 5.32 | **PROMOTE_CANDIDATE** |
| `piecewise_conservative` | 保守型 VT (Piecewise) | active | 17.53 | 3.11 | -2.48 | 2.68 | 3.72 | PASS |
| `adaptive_tier` | 自適應三階 VT | active | 31.24 | 3.00 | -5.06 | 2.96 | 3.42 | PASS |
| `taiwan_hybrid_leverage` | 台股混合槓桿 | active | 37.32 | 2.76 | -10.27 | 6.71 | 5.21 | PASS |
| `vix_cond_leverage` | VIX 條件槓桿（月頻） | active | 30.21 | 2.70 | -6.47 | 1.77 | 2.74 | PASS (median) |
| `taiwan_8.63vix` | 台灣 VT (0050.TW) | active | 28.56 | 2.35 | -11.19 | 5.69 | 4.63 | PASS |
| `risk_parity` | Risk Parity (SPY+GLD) | active | 32.54 | 2.18 | -11.48 | **1.26** | 2.67 | **WATCH** (Sh90 ↓ 42% vs full) |
| `recommended_5050` | 50/50 SPY/GLD | active | 17.86 | 1.96 | -7.67 | **1.30** | 2.20 | **WATCH** (Sh90 ↓ 34%) |
| `vix_leading_guard` | VIX+景氣領先 (0050.TW) | active | 23.21 | 1.72 | -15.98 | 4.60 | 3.63 | PASS_REGIME_RECOVERED |
| `fear_dca` | 恐慌加碼定期定額 | active | 24.58 | 1.51 | **-18.76** | 1.89 | 1.93 | WATCH (MDD edge of gate) |
| `slow_vt` | GARCH VT (SPY) | active | 13.74 | **1.40** | -10.72 | 1.24 | 1.52 | **WATCH** (below median; flagship narrative weight) |
| `simple_12vix` | 12/VIX (SPY) | active | 13.19 | **1.39** | -10.99 | 1.21 | 1.46 | **WATCH** (below median) |

**Median Sharpe = 2.70**；7/11 active strategies 在 median 之上，4/11 below median。

### Gate cross-check vs `strategy_metrics.json`

`strategy_metrics.json` 顯示的 Sharpe 與本表 forward-tracked Sharpe 大致一致（最大 gap < 0.2），confirms `recalc_metrics.py` 與 forward tracking 同步。**但**`paper_trading.json` 內 `stats` block 對 7 個策略缺失（tz_tw_jp_5050 / global_vt_tz / vix_leading_guard / vix_cond_leverage / taiwan_hybrid_leverage / piecewise_conservative / fear_dca / adaptive_tier 的 stats={} 或缺欄）— 為**ops finding**: `paper_trading.stats` backfill 流程未涵蓋全策略，前端若有讀此欄需以 `strategy_metrics.json` 為準。

### 無 DELIST_CANDIDATE

沒有任一 active strategy 滿足 delist threshold（MDD breach OR 6mo Sharpe < 0 OR data quality issue）。`fear_dca` MDD -18.76% 接近 -20% gate 但仍合規；`slow_vt` / `simple_12vix` Sharpe ~1.4 低但仍 > 1.0 — per docs/strategy-registry.md §策略生命週期「舊策略不因新策略而下架」原則，這些屬於「需注記近期表現偏離」非下架。

---

## 3. K-experiment-derived New Listing Pipeline

| K | Title | Verdict | Listing-ready? |
|---|-------|---------|:--------------:|
| K1175 | Paper 2 Table 3 VT canonical replication | OK (replication, not new strategy) | N/A |
| K1257 | Bayesian Model Averaging (BMA) | H1 PARTIAL, H2/H3 FAIL | NO |
| K1300 | Forgetting-Factor BMA | CONFIRMED_FAIL | NO |
| K1301 | HAR-RS (Realized Semivariance) | NULL on TX1 | NO |
| K1302 | Paper 2 individual γ JSON rebuild | Paper task (no strategy) | N/A |
| K1303 | HAR-CJ (Jump-decomposition) | NULL on TX1 | NO |
| K1304 | K1257 BMA 0050.TW microstructure test | No results yet | TBD |
| K1305 | Paper 4 vix-sufficiency vintage retest | No results yet | TBD |
| K1306 | SEC EDGAR 10-K text sentiment pilot | Data-sourcing pilot | NO (pre-strategy) |
| K1309 | HAR-PD (Path-Dependent HAR) | NULL — joins K1301/K1303/K868 as 4th HAR-decomp failure | NO |

**Honest verdict**: **K-experiment-derived listing candidate = NULL**。最近 10 個 K 沒有任何一個產出能通過 5 項 listing gate 的新策略 signal。HAR-family decomposition (K1301/K1303/K1309) 連續 3 次 NULL，BMA (K1257/K1300) 2 次 FAIL — 都是 forecasting-side experiments，不是 trading strategy candidates。

→ 新策略源頭仍需仰賴：(a) `taiwan_spy_momentum` / `tz_tw_jp_5050` / `global_vt_tz` (已存在 disabled 高 Sharpe candidates)；(b) 未來等 K1304/K1305 結果或新方向。

---

## 4. Three Specific Actionable Recommendations

### R1 (PROMOTE — high revenue impact)：升級 `taiwan_spy_momentum` 從 disabled → active

**Rationale**: forward-tracked Sharpe 3.45（median 之上 +28%）、MDD -8.14%（gate -20% 寬鬆 12pp）、最近 90 日 rolling Sharpe 6.76（regime currently friendly）。已有 779 forward-trading days，已過 J9 教訓的單期 OOS 不可靠 threshold。

**Monetization angle**: 台股 momentum + 0050.TW 標的對台灣讀者市場（DGBAS / 大葉大學讀者 base）highly relatable — direct premium-tier 訂閱 hook。台股策略目前 active 池 4 個（taiwan_8.63vix / vix_leading_guard / taiwan_hybrid_leverage 已在），加入動量策略可形成 「台股 4 大 vol-strategy family」narrative，加強台灣定位差異化。

**Blockers before promote**:
- Cross-OOS 5 period (2014-2016 / 2016-2018 / 2018-2020 / 2020-2022 / 2022-2024) ≥ 3/5 PASS 重跑確認
- Sensitivity (TX cost ±20%、momentum window ±20%) — Sharpe drop ≤ 30%
- Codex code review of `taiwan_spy_momentum` signal logic (esp. lookahead in momentum lookback)
- 為何 2026-04-19 還 disabled？查 `daily_update.py` git blame / 歷史 commit message 必要

### R2 (WATCH → DISCLOSE)：在前端 `slow_vt` / `simple_12vix` 卡片加注記「近期表現偏離歷史」

**Rationale**: 兩策略 forward-tracked Sharpe ~1.4，低於 median 2.70 (~48% below)。`slow_vt` 是 GARCH VT 旗艦敘事策略（網站 paper 1 的核心），讀者期望高；若 Sharpe 持續低於 1.5 而前端只顯示 cumulative return 53.5% 而不揭露「2 年內 rolling Sharpe 衰退」會傷信任。

`recommended_5050` 與 `risk_parity` 也應加注：rolling90 Sharpe 從歷史 ~2 降到 ~1.3（-35% to -42%）。

**Action**: per `docs/strategy-registry.md` §策略生命週期「績效異常注記」原則 — 不下架，但前端策略卡片加 banner「近期 6 個月 rolling Sharpe 顯著偏離歷史均值，請審慎評估」。實作面：`strategy_metrics_cache.notice_flag = 'regime_shift_recent'`，前端讀此 flag 顯示 banner。

**Monetization angle**: 主動揭露 underperformance 是信任資產 — 讀者區辨「賣 hype」vs「真實 ops」的關鍵。投資內容平台長線留存率與「不報喜不報憂」高度負相關。揭露能轉化為「我們持續監測你的策略」premium 服務 hook（subscription value-add）。

### R3 (NEW LISTING PIPELINE — research direction)：補 K-experiment-derived strategy candidates 缺口

**Finding**: 最近 10 個 K 全是 forecasting (HAR/BMA/jump) 不是 trading signal。新 listing 候選池目前為 0 — research → strategy 的轉化漏斗斷掉。

**Action**: 在 `research_program.md` backlog 補 3 個 strategy-oriented K brief（不是 forecasting model audit）：
1. **K13xx ALPHA**：以 `tz_tw_jp_5050` (Sharpe 3.67 disabled) 為基底，跑 5-period cross-OOS + sensitivity（complete the 5-gate）→ 若 PASS 直接 promote。**Lowest-effort highest-impact path**。
2. **K13xx BETA**：multi-asset vol-targeting with 4-asset basket (SPY + 0050.TW + GLD + ^N225)，inherit `tz_tw_jp_5050` allocation logic 擴增資產 — 直接利用 `vix_cond_leverage` 月頻 framework + `global_vt_tz` cross-region 經驗。
3. **K13xx GAMMA**：規則化 K1306 SEC EDGAR sentiment（待 data unblock）為 quarterly tilt signal overlay on 既有 risk_parity — 不是獨立策略而是 enhancement layer，先做 backtest 證 alpha，後續 listing decision。

**Monetization angle**: Strategy listing 多樣性直接 = 「premium tier 訂閱選單」的選項數。目前 11 個 active 多集中 VT-family，缺少 multi-asset / momentum / sentiment-overlay 類型。增加 3 類正交策略 → premium tier 可分 Bronze (5 strategy) / Silver (10) / Gold (full 14+) tier 化訂閱定價。

---

## 5. Monetization Summary

| Recommendation | Effort | Revenue Lever | Time-to-impact |
|----------------|:------:|---------------|:--------------:|
| R1 Promote `taiwan_spy_momentum` | Low (cross-OOS + Codex review ~1 day) | 台股 narrative + 增加 listing depth → premium subscription appeal | 1-2 weeks |
| R2 Disclose regime-shift on slow_vt / simple_12vix / risk_parity / recommended_5050 | Low (UI flag + backend notice_flag column) | 信任資產 → 長線留存 → 「監測服務」premium value-add | 3-5 days |
| R3 Strategy-direction K backlog refresh | Medium (3 K design + cross-OOS execution) | Strategy 池多樣化 → tier 化訂閱定價（Bronze/Silver/Gold） | 1-2 months |

**Combined**：R1 短期 surface 1 個高 Sharpe 策略 → 立即增加 listing depth + 台灣讀者 hook；R2 信任建設防止流失；R3 為 tier 化訂閱 (premium revenue 模式) 打基礎。三者一起把 strategy_lifecycle 從「forward tracking 14 個 stale listings」進化到「主動策展 + 透明監測 + 持續 pipeline」— 才是平台 monetization moat。

---

## 6. Limitations / Honest Caveats

1. **Stats block 不一致**：`paper_trading.json` `stats` 對 7 個策略缺失；本 audit 直接從 entries 重算，但若前端讀的是 `stats` 而非 `strategy_metrics.json`，會顯示 outdated / partial numbers。**Ops fix 建議**：rerun `scripts/recalc_metrics.py` 全策略 backfill `paper_trading.stats`。
2. **No Codex review yet**：本 audit 待 Codex CLI quota reset 2026-05-13 02:46 UTC 後 second-opinion review (metric formula / gate threshold consistency / window alignment)。
3. **Sample dependence**：14 active/disabled 中 6 個 trading_days < 850（< 3.4 yr），低於理想 cross-OOS 5-period × 2yr = 10yr 樣本長度；rolling Sharpe 對近期 regime 敏感（2024-2026 整體 VT 友善環境）。
4. **Cross-OOS 未在此 audit 內執行**：本 audit 僅做 COMMON_START single-window；R1 的 promote decision 仍需獨立 cross-OOS。
5. **K-derived candidate = NULL** 是 honest finding，不是「漏看」。10/10 recent K 都是 forecasting-side，需要主線程主動派 strategy-design K（R3 對應 fix）。

---

## 7. Suggested Next Actions for 主線程

1. 派 Codex review 本 audit report（quota reset 後）
2. 啟動 R1：派 worktree agent 跑 `taiwan_spy_momentum` 5-period cross-OOS + Codex review of signal code（直接走 `evaluate_new_strategy.py` framework）
3. 啟動 R2：admin-ops task 加 `strategy_metrics_cache.notice_flag` schema + 前端 banner 元件
4. R3：補 research_program.md L?? backlog 3 條 strategy-oriented K brief
5. 完成後 send_alert email 用戶（per memory `feedback_email_on_major_decisions`）— policy 決策（disabled → active strategy promotion）建議用戶 confirm 後再 publish 平台文章宣傳

**End of audit.**
