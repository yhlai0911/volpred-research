# Release-layer 飽和：底層 root cause + 徹底解決計畫

**日期**：2026-06-18 09:25 台灣時間
**觸發**：老闆連續 4 封 reply (email-11770/11771/11772/11773) 全指「徹底解決底層問題」
**作者**：AI 平台運營經理（hourly-09）

---

## 1. 病灶（用戶看到的）

老闆 reply 對應 4 個 hourly 系統訊號（全部 2026-06-18 凌晨）：

| Email | 原始 alert | 表面現象 |
|-------|-----------|----------|
| 11770 | 04:07 hourly fire info | pool 4 連跑 journal_discovery（fallback chain） |
| 11771 | 05:01 boss report | 同樣 release-layer signal |
| 11772 | WARN release pool cron gap >4h | release_pool cron 04:07-08:07 沒 fire（09:07 恢復） |
| 11773 | 6h summary 00:05→06:05 | 18 commits 但只 1 published、活動分佈集中 other |

老闆直覺正確：**這 4 個訊號不是獨立 bug，是同一個底層問題的不同表面**。

## 2. 底層 root cause（不是 patch 的層級）

**Release-layer cluster 飽和** — 釋出端決定什麼可寫成文章，不是研究端缺方向。

具體機制：

1. `continue_task_dispatch._maybe_refill` 在 agentable < 4 時呼叫 `refill_task_pool.py`
2. `refill_task_pool` 從 `publication_candidates.json` 找 uncovered K
3. 對每個 candidate 跑 **narrative-arc dedup gate**（`check_arc_dedup.py`）
4. **gate 判斷邏輯**：candidate 主題（assets × 結論方向）若與既發文 arc 同構即 reject
5. 結果（2026-06-18 08:32 codex pool-dry diagnostic 證實）：K1506 / K1512 / K1339 / K1499 / K1513 / K1529 / K1530 / K1510 / K1347 / K1501 **全 reject**（10+ K）

**為什麼會飽和**：
- 過去 30 天 trending_repost cap = 2/day → 60 篇 trending 滿載
- 加上 daily_article / event_article → arc 覆蓋面快速擴大
- arc 定義 = (asset_set, direction)：SPY+VIX+vol 結論 已蓋；GOLD+USD 已蓋；NVDA+skew 已蓋
- 新研究方向產出（journal_discovery 178 條 backlog）多在已蓋 arc 上
- → 釋出端 funnel 越來越窄

**為什麼 fallback chain 連跑 journal_discovery**：
- pool 補不到 → fallback → `generate_research_backlog.py`
- 但這邏輯是「研究端 → 釋出端」單向 — 研究多了 release 不一定通

**Cron gap**：
- 釋出端飽和 → release_pool cron 多次「interval_not_due / no_due_articles」→ log 顯示「無事可做」
- 但同時段（04:07-08:07）host cron 確實有 4h gap（11772 alert source）— 這是獨立的 LaunchAgent 短暫卡住
- 09:07 cron 自然恢復，但與 release-layer 飽和的訊號疊加 → 老闆看到全是紅燈

## 3. 為什麼 patch 不夠（過去做過的不是底層）

| 過去 patch | 為什麼不是底層解 |
|-----------|-----------------|
| 加 `--target` 強迫多補幾個 | gate 還是擋住，補不到 |
| 改 arc-dedup tolerance | 鬆掉會誤放，K1449/K1091 dup incident 復發 |
| 加 fallback 到 journal_discovery | 把問題往上游推、變成「研究端跑很快但下不來」 |
| 改 cron interval | 飽和時 cron 跑多次也是 no-op |

## 4. 徹底解（3 層）

### Layer A — 底層邏輯：arc 定義升維

**問題**：arc = (asset, direction) 太粗，所有 SPY-vol 主題互相 dedup。

**徹底**：arc = (asset_basket, mechanism, time_horizon)
- mechanism = {jump_clustering, leverage_effect, vol_term_structure, cross-asset_spillover, regime_dependent, ...}
- time_horizon = {intraday, weekly, monthly}
- 新 K 即便同 asset，若 mechanism / horizon 不同 → 視為新 arc

**驗收**：當前被 reject 的 10 K，按新 arc 重 score，至少 5 個可重新進池（其他 5 確認真重複）。

### Layer B — 流程：研究與釋出 funnel 平衡偵測

**問題**：研究端 backlog 178 條成長，但釋出端 cluster 飽和不知道反向通知 → silent gap。

**徹底**：
- `scripts/release_funnel_health.py`（新檔） — 比較 (研究 backlog growth rate, 釋出 throughput) 兩個指標
- 釋出 throughput < 0.5 × 研究 growth 持續 7 天 → 自動 alert `release_layer_saturation`
- alert 觸發 → 強制暫停 journal_discovery 1 週，改派 cluster-broadening experiment（探索未覆蓋 arc 區塊）

**驗收**：funnel 指標每天 emit 到 `storage/ops/release_funnel.json`，dashboard section 加 release_funnel 顯示比值。

### Layer C — 程式架構：cluster topology 觀測面

**問題**：當前無 arc coverage 可視化，主線程憑感覺判斷「哪個方向已蓋」。

**徹底**：
- `scripts/build_arc_coverage_map.py`（新檔） — 掃 feed.json 所有 published mile，按 (asset, mechanism, horizon) 三軸 bin
- 輸出 `storage/ops/arc_coverage_map.json` + 簡 HTML 視覺化（熱圖）
- 補池 candidate score 加 `arc_coverage_density` 因子 — 密度低的方向加分

**驗收**：覆蓋熱圖在 admin observer 頁可看；新文章 publish 後熱圖自動更新。

## 5. 排序（什麼時候做）

| Phase | 範圍 | ETA | 誰做 |
|-------|------|-----|------|
| **A1 — arc 升維 schema** | 新增 mechanism / horizon 欄位 to `check_arc_dedup.py`；既有 mile 補 backfill metadata | 本週 | 主線程派 platform_ops task |
| **A2 — refill_task_pool 套新 dedup** | refill 時用新 arc 重 score | A1 完成後 +1 day | 同 |
| **B1 — funnel health monitor** | 新 script + cron daily 08:00 | 下週 | 同 |
| **C1 — arc coverage map** | 新 script + admin visualizer | 下週 | 同 |
| 觀察期 | 2 週收 data 看是否 oscillate | A 完成後 2 週 | hourly observer |

## 6. 老闆 sanity check（盈利對齊）

- Mission #1 文章品質：解後文章「主題密度」會降但「主題多樣性」會升 → 讀者 retention 應升
- Mission #2 研究：研究端不再 silent over-produce；資源更有效
- Mission #5 曝光：多樣 cluster → SEO long-tail 更廣
- **無 conflict 研究誠實原則**：arc 升維是更精細的去重，不是放鬆 quality gate

---

## 接續任務 → 派入 next_tasks

- `governance_release_layer_arc_upgrade_a1`（P1）— Phase A1 schema + dedup 改造
- 後續 A2/B1/C1 依 A1 完成順序派出
