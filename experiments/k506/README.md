# k506

- Experiment ID: `k506`
- Status: hardened_2026_07_05 — Codex PASS（方法論硬化後 null/no-deploy 結論可作內部決策，見 `codex_review_20260705_methodology_hardening.md`）
- Last updated: 2026-07-05

## 問題描述

驗證 `EWT / 0050.TW` 21 日 realized volatility ratio，是否能作為台股 VT (`8.63 / VIX`) 的額外 overlay，在 5 段不重疊兩年期 cross-OOS 中穩定改善淨 Sharpe。

## 本輪修正目標（K506 methodology hardening）

1. 修正 rebalance timing：月初調倉日舊權重吃 close-to-open，開盤後新權重才吃 open-to-close。
2. 修正 calendar as-of：EWT/VIX 使用台股交易日前最近且嚴格早於該日期的美股 close，避免台股假日後 stale signal。
3. 修正成本口徑：K625 買進 4.275bp、賣出 14.275bp，依交易方向對 `abs(delta weight)` 拆開扣，不再每次 delta 扣完整 round-trip。
4. 修正 0050.TW split artifact：local cache 的 `Adj Close` 仍保留 2014-01-02 約 4-for-1 跳點，腳本現在偵測 split-like jump 並修補 OHLC。
5. 保留 DM + Bonferroni/BH 多重檢定；禁止混用 K505 的數字，K506 對外數字只能來自本實驗 `results.json`。

## 目前狀態（2026-07-05 hardened rerun）

- `results.json` 為 2026-07-05 fresh hardened 輸出；data range = 2010-02-04 to 2021-12-30，OOS pooled days = 2447。
- Data inputs：EWT 已固化到 `experiments/k506/data/EWT_2010_2021_yfinance.csv`；0050.TW 與 ^VIX 走 `data/cache/price_cache.db`。腳本會優先使用 repo-local cache / CSV fallback，再 fallback yfinance。
- Split audit：偵測並修補 `0050.TW` 2014-01-02 raw close ratio 0.249361（約 4-for-1），避免 2014 OOS 報酬與 realized vol 被假跳點污染。
- **結果 = NULL / NO DEPLOY**：VT+VS wins 2/5（未過 ≥4/5 門檻）；pooled DM t=-1.905, p=0.0569；Bonferroni p=0.3414；BH p=0.1818 — 多重校正後不顯著，方向反而偏 VT。
- Harvey threshold：VT-only t=2.903、VT+VS t=2.829，兩者皆未達 t > 3.0。
- **Codex re-review = PASS**：原 FAIL 的三項方法論 blocker 已修；另補上 split artifact 修補與 EWT 2010-2021 repo-local snapshot，結果可重現。
- **未寫 knowledge.json**：Codex 依治理規則不直接寫 knowledge；本輪只產生可審計 experiment artifact 與 re-review，後續由主線程/Claude 用正式 writer + gate 決定是否寫 null-result knowledge。

## 資料來源需求

- `0050.TW`: 本地 SQLite cache `data/cache/price_cache.db`
- `^VIX`: 本地 SQLite cache `data/cache/price_cache.db`
- `EWT`: `experiments/k506/data/EWT_2010_2021_yfinance.csv`（2010-01-04 至 2021-12-31；由 yfinance 取得後固化）。`experiments/k1090/data/EWT.csv` 僅作次級 fallback，仍不足時才 fallback yfinance。

## 下一步

1. 若要把 K506 作為正式 null-result knowledge，主線程用正式 writer + gate 寫入，不要手改 `knowledge.json`。
2. 若要發文，引用 hardened `results.json` 與 re-review；不要引用舊 3/5 MARGINAL 數字。
3. 不建議部署 VT+VolSpread overlay；hardened rerun 沒有通過 win-count、DM、多重檢定或 Harvey 門檻。
