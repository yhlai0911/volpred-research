# K1582 — Codex 24h post-publish source-code review

| Item | Value |
|---|---|
| Reviewed article | `mile_55f3ef61`（published 2026-07-02 19:00） |
| Reviewer | Codex CLI (`codex exec`, gpt-5.4) |
| Review date | 2026-07-03 |
| Trigger | agent-delegation.md 2026-05-02 K1018 lesson（production article 24h 內 source-code review） |
| **VERDICT** | **CONDITIONAL_PASS** |

## Lookahead 判定：CLEAN
- `K1582.py:299-310` 先 `.shift(1)` 再 rolling，HAR daily/weekly/monthly 分量在 forecast origin t 只用 ≤ t-1 資訊。
- `K1582.py:390-399` OOS 每列只用 `features.iloc[:pos]` 訓練，訓練尾端不看預測日 realized。
- 無 in-sample→OOS 洩漏。

## 發現的問題（無 HIGH）
| 位置 | 級別 | 問題 |
|---|---|---|
| `K1582.py:439` | MED | DM 呼叫的 `dm_test` 未做 HLN finite-sample correction；TX n=1697 影響小，但 SPY(51)/0050(38) p-value 僅能當 diagnostic。文章已正確把短樣本降級為「流程檢查」，無 article-level overclaim。 |
| `K1582.py:174-195` | LOW | TX active contract 由同日完整日盤成交量決定；不污染 lagged predictors，但若未來宣稱實盤可交易 forecast，需改成事前 roll rule。 |
| `K1582.py:456` | LOW | MCS method 字串 `HLN2011` 易與 Harvey-Leybourne-Newbold 混淆；實為 Hansen-Lunde-Nason MCS（非 DM 的 HLN 修正）。純命名，不影響計算。 |

## 可放行的宣稱範圍（對照 DIRECTIONAL_ONLY）
- ✅ 可宣稱：TX_active 上 HARQ/SHARK-like 特徵有約 1.5–2.1% QLIKE **方向性**改善、lookahead clean、短樣本市場僅流程檢查。
- ❌ 不可宣稱：statistical/gate pass、跨資產有效、可上線替代 HAR baseline、已證明 SHARK/jump/downside 機制。

## Article 一致性驗證（主線程）
Published article `mile_55f3ef61` 內文明寫「方向性改善存在，但沒有通過嚴格 gate」「統計強度低於 project gate」「尚未解決完整夜盤假說」，並誠實列出 HARQ DM t=-2.60、SHARK_like t=-1.77 (p=0.0766) 未過線。**宣稱範圍與 CONDITIONAL_PASS + DIRECTIONAL_ONLY 完全一致，無需內容更正。**

## Follow-up（非阻塞，未來若把 K1582 推進論文再處理）
- 若進一步做 SPY/0050 顯著性宣稱 → 補 HLN 小樣本修正。
- MCS 字串 `HLN2011` → 未來重跑時改名 `HLN1997_MCS` 或 `Hansen_Lunde_Nason_MCS` 消歧義。
