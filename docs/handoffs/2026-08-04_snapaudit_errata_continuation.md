# 接續：snapaudit 內容誠信更正鏈

更新：2026-08-04 12:22（台灣時間）
狀態：裁決完成、重跑已排、**erratum 尚未動筆**

## 一句話

兩篇已發佈文章的數字建立在含 10 筆重複列的樣本上，裁決已完成，正確數字要等
`assign_ce6097bf`（P1 experiment，已 fire_requested）跑完才拿得到，拿到之前**不准碰文章**。

## 現在該做什麼

1. 確認 `assign_ce6097bf` 是否已被派工 / 完成：
   `uv run python scripts/task_pool_claim.py list --status pending --limit 20`
2. 完成後，逐項核對它交出的 before/after 對照（**程式化從 results.json 取，不從 README 轉抄**）。
3. 依 `.claude/rules/publishing.md` 出 erratum。**不是偷改原文** —— 兩篇都是已發佈狀態。
4. k1396 只需加註，k1319 無需動作（依據見下）。

## 已確立的事實（不需重新推導）

### 裁決結果（`snapaudit_feed_articles_contaminated_numbers` 已 succeeded）

| K | 文章 | 裁決 | 關鍵依據 |
|---|---|---|---|
| k1308 | `mile_02c71e74` | **需更正** | 正文自陳「共 119 個交易日」；audit 釘 vintage 得 polluted n=119 完全對上 stored n、clean n=109 → 暴露 **9.17%**（本事件最大）。受影響 headline：平均比值 **1.574**、最近 30 天 **2.064**、前一版 **1.391** |
| k1399 | `mile_34157161` | **需更正（純數值）** | 36 欄位改變；正文列 DM t **−4.40 / −3.53 / +3.47 / −0.40 (p=0.69)**、IS n=**3,522**、OOS n=**1,865**。audit C 已確認 H1..H5 判定不翻 → 敘事成立、數字錯 |
| k1319 | `mile_d11e45ff` | **無需動作** | 該文引用的是 t=**+6.2929**，不是被重跑的 DM(HAR vs EWMA)。且重跑 t −3.0226 → −3.1021，**兩側都 \|t\|>3.0，門檻未跨** |
| k1396 | 4 篇 feed | **僅需加註** | audit C：frozen 產物未動、僅 legacy-rerun 受影響；K1379 已取代公開詮釋；其中 `mile_7825c8a2`、`mile_7fbc61c8` 本身就是更正文 |

### 兩個必須帶著走的更正

**一、原任務前提有誤。** 它把 k1319 列為「判定翻轉（DM t 跨 Harvey |t|>3.0）」，但兩側都超過 3.0，
沒有跨越。前置任務自己的摘要寫「顯著性翻轉」與它列的數字互相矛盾。**真正跨 5% 翻轉的是
k1592**（`dm_GammaRule_minus_GJR` p 0.038 → 0.137），而 k1592 不在原清單裡 —— 下一手要自行決定
k1592 是否有 reader-facing 曝露面。

**二、tombstone 會把「已完成任務裡記下的未竟事項」一起埋掉。**
`snapaudit_quantify_unmeasured_exposure` 的 result 末尾記著「重跑 brief 已寫好但 free_slots=0 未入列」，
該任務 3 天後被壓縮、result 欄位被剝除，於是那件事沉了 7 天沒人知道。正確數字必須從
`storage/next_tasks_archive/2026-07.jsonl` 撈全文才看得到。**這是一個尚未修的機制缺口**
（與 2026-08-04 修的 dreaming 假陽性同源：壓縮剝欄位）。值得單獨開單。

### 前置任務的真實數字（已從 archive 撈出）

- **k1319 原 vintage 重跑**：DM(HAR vs EWMA) t −3.0226 → −3.1021，p 0.0025 → 0.0020，n 4129 → 4119
- **k1592**：SPY `dm_GammaRule_minus_GJR` p 0.038 → **0.137（跨 5% 不再顯著）**；MCS GARCH 0.033 → 0.026；
  panel mean_losses GARCH 1.929 → 1.535（約 26% 膨脹）；headline NULL_OR_WEAK 不變且強化。已 commit `dd2e70b42`
- **暴露量級**：k1497/k1498/k1585/k1380/k1391 各恰好 +10 重複列（佔乾淨樣本 0.15%–0.88%）
- **k1308 裁決推翻 audit C**：從 UNVERIFIABLE_MISSING_INPUT 改判 **CONTAMINATED_VERIFIED** ——
  輸入從未缺失，是 results.json 內的 stale 絕對路徑誤導 audit C；用 repo-relative 路徑即可取得

## 邊界

- **不得改動已發佈文章**，更正走 erratum
- 不得用 07-19 vintage 的值
- 重跑後要過 `experiment_gates.py` 並取得 review verdict 才寫 `knowledge.json`
- 兩支腳本都在 HEAD 上：`experiments/k1308/k1308.py`、`experiments/k1399/k1399_vix_decomp.py`

## 接續提示詞

讀 `docs/handoffs/2026-08-04_snapaudit_errata_continuation.md`，先查 `assign_ce6097bf` 狀態。
若已完成 → 核對 before/after 對照後，為 `mile_02c71e74` 與 `mile_34157161` 出 erratum，
`mile_6e81bb0a` 等 k1396 系列加註，k1319 不動。
若未完成 → 確認它有被派工（P1、fire_requested），不要重複開單。
另外評估是否為「tombstone 埋掉未竟事項」這個機制缺口單獨開一張。
