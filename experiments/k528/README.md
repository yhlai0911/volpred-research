# k528 — NFP 事件研究（SPY 波動率）

> ⚠️ **NFP 日期用 first-Friday proxy — 結論須重驗**
>
> 本實驗（NFP event study on SPY volatility）用 `get_first_friday()` 把 NFP 發布日推算成「每月第一個週五」。此 proxy 已知不可靠：對 13 個近期官方 BLS 日期驗證，錯了 7 個（含 2025-10 政府停擺期間 BLS 根本沒發布的幻影日）。歷史 NFP 日集合因此被污染程度未知，凡依賴 NFP 日期的分類數字（event-day mean/ratio、t、p、regime 細分）都須用 canonical `volpred.data.event_dates.nfp_release_dates`（fail-closed，官方 BLS/ALFRED 日曆）重跑後才可信。
> 根因/修正：`docs/error_log.md` 2026-07-12 CPI 條目、knowledge `390d9784`、K528 修正案。此為主 NFP 實驗，另有 feed 文章引用其數字，須一併回溯。
> （2026-07-19 first-Friday proxy 全庫 sweep 標記，assign_23b2a961）

- Experiment ID: `k528`
- Created At: 2026-04-16T09:39:52.904348+00:00
- Corrected At: 2026-07-19（事件日期來源修正，全樣本重跑）
- Status: 已重跑，結論方向不變、其中一項顯著性翻轉

## 問題描述

NFP（非農就業）公布日，SPY 的波動是否會系統性放大？如果會，放大的來源是「NFP 這個
事件本身」，還是「進場當下的市場狀態」？

## 2026-07-19 更正：事件日期從 proxy 換成官方日曆

原始版本用「每月第一個週五」推算 NFP 發布日。這個 proxy 在全樣本中約兩成是錯的，
而且**錯得有結構、不是隨機噪音**：

- BLS 在參考週較晚的月份會改到**第二個週五**發布（28 筆剛好早 7 天）
- 遇到聯邦假期會**提前**（12 筆晚 3–4 天）
- **2025-10 根本沒有發布**（政府關門取消），proxy 卻憑空生出一場
- proxy 把每一場都放在**週五**；官方日曆的 253 場只有 231 場在週五

錯的事件日期不會拋錯、不會出現 NaN，圖照樣畫得出來 —— 它只是把安靜的日子算成事件日、
同時把真的事件日丟進對照組。這是本次修正存在的理由。

修正後 `get_first_friday()` 已**整條移除**（不是標 deprecated），日期改由
`volpred.data.event_dates.nfp_release_dates` 取自 BLS 官方發布日曆（ALFRED，FRED
release id 50），且**取不到就 raise，不回退 proxy**。

**樣本數幾乎沒變，但樣本本身變了很多**：254 → 253 筆，其中**只有 207 個日期是共通的**，
46 場換成了不同的日子。只看筆數會誤以為沒事。

## 方法

- 資料：SPY / ^VIX 日頻（yfinance），2005-01 至 2026-03
- 事件日：BLS 官方發布日曆（ALFRED release id 50），fail-closed
- 事件窗：T-5 ~ T-1（前）、T（當日）、T+1 ~ T+5（後）
- 檢定：Welch t（vs 全體非 NFP 日 / vs 非 NFP 週五）、Mann-Whitney U、
  VIX 中位數分組 regime 檢定、Pearson / Spearman 相關

## 結果：逐項前後對照

每一項都同時看 **mean / median / 勝率 / 樣本數 / 顯著性** —— 平均值可能幾乎不動，
而中位數與勝率在底下已經移位。本次就抓到一例（regime 那列）。

| 指標 | 修正前（proxy） | 修正後（官方） | 判定 |
|---|---|---|---|
| 樣本數 | 254 | 253（僅 207 日期共通） | 數值微調，但**樣本換掉 46 場** |
| NFP vs 全體非 NFP（平均） | 1.104× (p=0.128, NS) | 1.083× (p=0.218, NS) | 數值微調 |
| ↳ 中位數比 / 勝率 | 1.190× / 0.555 | 1.136× / 0.549 | 數值微調 |
| NFP vs 非 NFP 週五（平均） | 1.168× (p=0.0335, **顯著**) | 1.150× (p=0.0571, **不顯著**) | **結論翻轉** |
| ↳ 中位數比 / 勝率 | 1.209× / 0.563 | 1.161× / 0.561 | 數值微調 |
| VIX 高低體制差（平均） | 2.167× (p=2.8e-10) | 2.039× (p=8.1e-9) | 數值微調（仍極顯著） |
| ↳ **中位數比** / 勝率 | **2.265×** / 0.717 | **2.023×** / 0.685 | **中位數移動 10.7%**（平均只動 5.9%） |
| 事前 VIX 相關（Pearson） | 0.451 (p=3.9e-14) | 0.438 (p=2.8e-13) | 數值微調 |
| ↳ Spearman | 0.377 | 0.337 | 數值微調 |
| VIX 中位數切點 | 16.71 | 16.69 | 數值微調 |

**唯一的結論翻轉**：NFP 對「非 NFP 週五」基準的差距，原本 p=0.0335 達 5% 顯著，
修正後 p=0.0571 **未達顯著**。這一項在線上文章 `mile_35eef830` 被明確寫成「達到顯著水準」，
必須更正。

翻轉的機制不只是數字抖動：proxy 下每一場 NFP 都是週五，這個檢定實際上是「週五 vs 週五」；
官方日曆下有 22 場不在週五，檢定的**含義本身也變了**，不只是值變了。

**方向性主結論不變**：決定 NFP 日波動的是**進場當下的 VIX 體制**（2.04 倍、p≈8e-9），
不是 NFP 這個日曆事件本身（1.08 倍、不顯著）。修正反而讓這個對比更乾淨 —— 現在兩個基準
都不顯著。

regime 那一列值得單獨看：**平均只移動 5.9%，中位數卻移動 10.7%**，只報平均會漏掉這件事。

## 產出檔案

| 檔案 | 內容 |
|---|---|
| `k528_nfp_event_study.py` | 主腳本（官方日曆版，含前後對照 audit 段） |
| `k528_nfp_event_study_results.json` | 修正後結果（現行 canonical） |
| `k528_nfp_event_study_results_PROXY_SUPERSEDED.json` | **修正前**結果存證，勿刪 —— 它是線上文章當初宣稱數字的唯一紀錄 |
| `k528_nfp_official_dates_results.json` | 逐項前後對照 + 46 個換掉的日期 + 文章更正替換清單 |
| `build_article_correction.py` | 文章更正計畫（預設 dry-run 驗證，`--apply` 才寫入） |

修正前的結果檔以 archive 形式保留，`k528_nfp_event_study.py` 的 audit 段直接讀它做對照。
proxy 當年只報平均、沒報中位數與勝率，因此 audit 段會從 archive 的逐事件資料**重建**
proxy 當時的分佈（日期取自 archive，不是重新生成一份 proxy 日曆），並先驗證重建出來的
平均能重現 archive 的平均 —— 對不上就 raise，因為對不上的重建算出來的中位數同樣不可信。

## 線上文章更正（`mile_35eef830`）

文章正文六個主要數字全部出自本實驗，全部需要更正，其中「1.17 倍達顯著」是**論述層級**的更正。

更正走 `volpred.publisher.article_correction.apply_article_correction`（唯一入口，
all-or-nothing，每個替換必須恰好命中一次），**不另發第二篇更正文**。18 個替換已對線上
canonical 文章驗證，全部恰好命中一次。

```bash
# 主線程在 repo root 執行
uv run python experiments/k528/build_article_correction.py            # 驗證
uv run python experiments/k528/build_article_correction.py --apply    # 寫入 + sync
```

**為什麼不在 worktree 內直接寫**：`storage/reports/feed.json` 是共享 canonical 狀態，
`.claude/rules/worktree.md` 明文禁止 worktree agent 觸碰。這不是形式規定 —— 本 worktree
自帶一份 15MB 的 feed.json 複本，在這裡寫等於寫進一份「其他文章一發佈就過期」的分支複本，
合併回去會把期間發佈的文章靜默蓋掉。因此拆成：worktree 負責解析與驗證，主線程負責寫入。

**未解決的缺口**：文中兩張圖表（`nfp_20260703_regime.png`、`nfp_20260703_baseline.png`）
與文末兩張懶人包圖仍是修正前的數據，圖片內容無法用文字替換修正。更正後正文與圖片會不一致，
因此更正說明中已明寫「圖表仍是初版數據，正在重新產製」。重新產圖 + 上傳 Supabase 屬後續工作。

## 防迴歸

`tests/test_nfp_official_release_dates.py`（既有檔案，NFP 事件日期正確性的單一 owner，
未另開新檔）新增兩組：

- `TestK528UsesOfficialCalendar` — 釘住 k528 用官方日曆、樣本 253 筆、231 筆在週五、
  46 個日期被換掉、結果檔宣告 fail-closed
- `TestProxyMutationIsCaught` — **mutation test**：把 proxy 日曆餵給同一個 guard 必須被拒；
  只塞回幻影的 2025-10-03 也必須被抓；同時驗證 guard 不會誤殺官方日曆

Mutation 已實測：把 `get_first_friday()` 塞回腳本 + 把結果檔換回 proxy 日期後，
4 個測試由綠轉紅（source guard 2 個、artifact guard 2 個），還原後 42 passed。
沒被實際觸發過的 gate 不算 gate。

## 參考

- K1442 事件日期稽核（發現本 bug）；`event_article_nfp_2026_07_03_t1` 修正報告 §7
- Savor & Wilson (2013, JFE)；Lucca & Moench (2015, JFE)
- K513：先前的 FOMC/NFP/CPI 事件研究
