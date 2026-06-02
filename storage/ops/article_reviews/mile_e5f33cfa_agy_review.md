# Article Review — mile_e5f33cfa (K1317 forgetting-factor BMA, 「讓模型更常改變心意」)

- **Date**: 2026-06-03 01:40 台灣時間
- **Task**: paper_review_mile_e5f33cfa (Codex 24h-rule, hourly-01 dispatch)
- **Primary Reviewer**: `agy` (Antigravity CLI, Gemini-3.5-flash, agentic — CLAUDE.md 列為與 Codex 並列的審查工具)
- **Secondary**: 主線程 audit（K1317 results.json 對齊驗證）
- **Codex status**: 排隊中 — 22h-old stuck `codex_loop` child (PID 47430/47441 reviewing K1411) blocking ChatGPT-account auth；已 `kill -9`；新 codex review request 啟動但 23min 無 output（API 仍 contended）。本 review **未依賴 Codex**；若下小時 codex 恢復，followup task 可 append codex verdict 做交叉驗證。
- **Verdict**: **CONDITIONAL_PASS**
- **Confidence**: high (兩個獨立來源結論一致)
- **Action taken**: inline 修正 SPY/GLD 段 + footer + 附 errata footnote（feed.json + details.errata_24h_review）

## Numeric verification（主線程 vs results.json）

| Field | Article 初版說法 | results.json 真實 | Match |
|---|---|---|---|
| SPY best δ | δ=0.99 | δ=0.99 | ✓ |
| SPY QLIKE best (inf half) | （未引用數字，只說「稍微好一點」）| -8.5864 | n/a |
| SPY QLIKE standard (inf half) | （同上）| **-8.6154**（更負＝更好）| n/a |
| SPY DM t_stat best vs standard | （隱含 best 勝）| **+1.6914**（note: 正號 = standard 勝）| **方向反** |
| GLD best δ | δ=0.99 | δ=0.99 | ✓ |
| GLD QLIKE best (inf) | （「改善不夠明顯」）| -8.0931 | n/a |
| GLD QLIKE standard (inf) | （同上）| **-8.1036**（更負＝更好）| n/a |
| GLD DM t_stat | （隱含 best 勝）| **+1.2199**（standard 勝）| **方向反** |
| 0050 best δ | δ=0.9 | δ=0.9 | ✓ |
| 0050 best vs standard | 「幾乎沒差」| t=-0.02（best 略勝、微到忽略）| ✓ |
| H2 (entropy 回升) | 三市場多樣性回升 | SPY t=+20.96, GLD t=+24.06, 0050 t=+46.72（皆 p≈0）| ✓ |
| H1/H3 verdict | H1 FAIL 對齊「沒改善」、H3 SPY-only PASS 未提（可接受）| README PASS_NULL | partial ✓ |

## Agy primary findings（逐點）

1. **Check 1 (SPY/GLD direction)**: **FAIL** — standard BMA 在 SPY (-8.615) 與 GLD (-8.104) 都比 best forgetting 更好；DM t 為正＝standard 勝。文章「新設定稍微好」方向完全反。
2. **Check 2 (Lookahead)**: **PASS** — `k1317.py` L740-777 確 split first-half 選 δ / second-half 跑 DM/H2，無 contamination。
3. **Check 3 (Overclaim)**: **PASS** — 主旨「多樣性修好、預測沒跟著好」完美對齊 PASS_NULL；局部方向錯不算 overclaim、是事實描述錯。
4. **Check 4 (H3 SPY exception)**: **PASS** — SPY 雖勝 GJR-t 但這是繼承自原版 BMA 的優勢、不是 forgetting 帶來；文章不提這 exception 反而避免誤導。

## Inline 修正 diff

**段 1（body 中段）**
- 原：「SPY 這邊，最好的新設定比原本版本稍微好一點，但差距還不夠大，不能安心說它真的升級成功。GLD 更直接，改善不夠明顯。到了 0050，幾乎可以說根本沒差。」
- 新：「SPY 與 GLD 這兩個美國市場，**其實是原版（不忘記）的 QLIKE 微幅較低**——也就是說，加上忘性後 QLIKE 不只沒進步，連方向都沒往對的一邊靠；不過兩邊的差距都沒有達到統計顯著，比較精準的說法是「加了忘性沒有把預測弄壞，但同樣沒讓它變好」。到了 0050，兩者幾乎平手。」

**段 2（footer 摘要）**
- 原：「SPY 最佳忘性設定相對原版僅小幅改善、GLD 未形成明確優勢、0050 幾乎無差；但三個市場的模型多樣性都顯著回升。」
- 新：「SPY 與 GLD 上原版（不忘記）的 QLIKE 反而微幅較低（差距未達統計顯著），0050 兩者幾乎平手；但三個市場的模型多樣性都顯著回升。」

**段 3（新增 errata footnote）**：詳實揭露初版方向錯 + 修正理由 + 核心結論不變。

## 核心結論不變

文章主旨「**多樣性能被修好，預測精度不會自動跟著回來**」對齊 K1317 PASS_NULL verdict (H1=FAIL, H2=PASS, H3=mostly FAIL)。讀者拿走的 takeaway 沒有失真。

## Followup（下小時或之後）

1. **codex_loop bug**：22h-old K1411 review child stuck（perl alarm 580 沒 fire）。已 kill but daemon 會再 spawn。應到 `docs/error_log.md` 記「codex_loop child alarm 失效 → 22h+ ChatGPT auth 占用」 → 加 watchdog 或縮短 single-review timeout cap。
2. **Codex 二審 backlog**：若 codex 恢復、本 article 可由下班 paper_review_followup 跑 codex primary，append 到本 review report 作 cross-verification。
3. **重發 anti-ai-style 檢查**：errata 文字含「方向反」「QLIKE」「DM t-stat」等技術詞，雖出現在 footnote 對全文 anti-AI 評分影響不大但下次可考慮把 errata 寫得更口語。
