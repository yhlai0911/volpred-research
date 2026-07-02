# Mega-cap options-skew snapshot 2026-07-03 — 記錄但未發佈

**Fire**: hourly-07 2026-07-03. **Task**: `trending_repost_2026_07_03_ai巨頭`.
**處置**: 資料真實收集完成，但**判定 arc-covered + cluster 飽和，不發佈**（見下）。

## 資料（真實，可驗證）

Source: yfinance option chains, ~30D 到期（2026-07-31），2026-07-03 截面快照。
方法: skew proxy = IV(90% put) − IV(110% call)，與 mile_49616ac2 (2026-06-03) **完全相同**。
腳本: `collect_skew_data.py` → `skew_results.json`；圖: `fig1_skew.png` / `fig2_pc_ivrv.png`。

| Ticker | 2026-06-03 skew | 2026-07-03 skew | Δ | P/C OI (07-03) | IV−RV (07-03) |
|---|---|---|---|---|---|
| SPY  | +9.5 | +9.6 | ~0（指數不變）| 4.63 | −4.8% |
| QQQ  | (9.1, f5f4) | +11.1 | — | 1.72 | −9.5% |
| NVDA | −1.0 | **+4.5** | **+5.5 翻正** | 1.36 | −2.1% |
| AMZN | −0.6 | **+1.7** | **+2.3 翻正** | 0.49 | +4.1% |
| AAPL | (n/a) | +3.8 | — | 0.53 | −9.2% |
| META | −5.3 | −3.1 | +2.2 | 0.44 | −5.9% |
| MSFT | −0.7 | −1.8 | −1.1 | 0.63 | +4.2% |
| GOOGL| −1.5 | −1.7 | ~0 | 0.58 | +6.0% |
| TSLA | (n/a) | +0.4 | — | 0.57 | −16.0% |

## 潛在新發現（未達發佈門檻）

指數 skew 一個月不變（SPY +9.5→+9.6），但**個股 skew 從全負開始翻正**（NVDA −1.0→+4.5、
AMZN −0.6→+1.7）→ 下行保護似乎從指數層往個股層移動，idiosyncratic 尾部風險開始被定價。
這**反轉**了 mile_49616ac2「個股押上行不押下行」的結論。

## 為何不發佈

1. **Layer 4 arc-dup**：同資產（mega-cap）× 同 metric（90-110 skew）× 同軸（指數 vs 個股）。
   專案硬規則 `feedback_narrative_arc_dedup`「方向相反也算 dup」→ 反向變奏仍屬同 arc。
2. **Cluster 飽和**：近 5 週已 4 篇同 cluster（mile_49616ac2 06-02 / mile_f5f4cb43 06-30 /
   mile_8a5e80b0 digest 06-27 + 底層）。publishing.md「同 cluster ≥2 篇近 14 天 → 強制換」。
3. 2-point（06-03 vs 07-03）before/after 太薄，「migration」需 ≥3-4 個時點才站得住。

## 未來觸發條件（值得寫的門檻）

若後續 2-3 週再測 skew，個股 skew 持續往正走（下行保護持續 migrate 到個股），
且指數 skew 同步鬆動 → 屆時是「regime shift 已確認」的真新聞，可寫（屆時 cluster 也已冷卻）。
建議排一個輕量 compute job 每週抓一次 skew 存 series，累積時序。
