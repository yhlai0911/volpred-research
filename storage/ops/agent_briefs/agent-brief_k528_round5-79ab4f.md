# K528 round-5 remediation — Codex FAIL 的四條 blocking defect

**Model**: opus / xhigh (per model_router)
**Worktree**: `.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`（你的 cwd 就是這裡）
**Task id**: `k528_round5_remediation`
**來源判決**: `storage/ops/codex_reviews/k528_round5_verdict.md`
**硬規則**: 此 worktree **禁止 merge / 禁止 certify**，直到 round 6 PASS。

## B1 — Friday estimand 與 README 宣稱不一致

證據：`k528_nfp_event_study.py:434-449,615-636`；`README.md:24,78-87,113,138`；`data/nfp_release_feed_fixture.json:41,77,101,139,212,236`

程式用**映射後的交易 session weekday** 篩 237 筆，不是官方**發布日** weekday。253 個有效發布日其實有 **243 個在週五**；6 個 Good Friday 發布日被映射到下週一因而被排除。所以 1.189× / p=0.0209 支持的是「NFP 消息在**週五交易 session** 被吸收」，**不是**「發布日在週五」。

最小修法：同時保存 `release_date` 與 `session_date`；若保留現行分析，全文改稱 **Friday trading-session estimand** 並揭露 6 個 Good Friday 案例。若要回答「發布日在週五」，須改用 release weekday 篩 243 筆 + 重新設計 weekday-matched controls + 重跑。**二選一，選了就全文一致，不要留兩種說法並存。**

## B2 — raw 與 selected 同步截短一個端點月仍會通過

證據：`k528_nfp_event_study.py:118-121,304-325`；`k528_completeness_gate_fix.json:140-145`

獨立重現：誠實 fixture 260 raw / 254 selected；同刪 `2005-01` → 259/253、head shortfall 34 天仍通過；同刪 `2026-03` → 259/253、tail shortfall 44 天仍通過。70 天容忍度容得下整個月消失，raw-selected / 缺月 / allowlist 三道檢查全看不到。

**裁決 = blocking**（不是可接受的設計取捨）：這是完全落後於執行日的固定歷史樣本，不是「當月可能尚未發布」的即時查詢。除非加入獨立 endpoint expectation，或至少**撤回 fail-closed 宣稱**並限制適用範圍。

最小修法：對這個固定歷史樣本**釘住預期首尾月份或預期發布數**；或用獨立 as-of/release-schedule 判斷應已發布的月份。**必須新增「同時刪 raw+selected 首/尾月」的對抗測試** —— 沒有這個測試就等於沒修（gate 的價值全在它會不會響）。

不推翻現有 archived 數字，但推翻 README 的 fail-closed 宣稱。

## B3 — 價格資料尾端截短也不 fail closed

證據：`k528_nfp_event_study.py:396-415,453-465`

`yf.download` 後沒有 SPY/^VIX 覆蓋範圍或 freshness gate。SPY 尾端少一個月 → 後續 NFP 被歸 `outside_price_sample` 但仍出結論；VIX 尾端短缺 → `ffill()` 沿用陳舊 VIX。當前結果檔確實零筆 outside，但流程未來重跑仍可合法縮樣。

最小修法：固定歷史樣本要求 SPY/^VIX 覆蓋至預期端點、`n_outside_price_sample == 0`、限制 VIX forward-fill 最大資料年齡。

## B4 — 未定義多重比較 family 卻以 5% 宣稱顯著

證據：`README.md:66-67,99,113,137-140`；`k528_nfp_event_study.py:611-710`；`k528_nfp_event_study_results.json:117-175,178-284`

腳本產生 A–J、12 個月份、兩種 VIX 相關等多個 p 值，無 multiplicity correction 也無 confirmatory/exploratory 分界。週五結果 p=0.0209 只能稱 **nominal significance**。若 family 限於 README 的六個主要檢定，Holm 後約 0.0417（結論可保留）；若涵蓋全部 22 個 inferential outputs，Holm 約 0.375。

最小修法：**指定 rerun 前既有的 confirmatory endpoints**、報告 Holm／Romano-Wolf 調整值、其餘明標 exploratory。**未完成前不得無限定地寫「顯著」。**

## 非阻擋觀察 —— 不必修，但別退步

- v6 allowlist 後門確已關閉（`:272-345`）；`test_k528_completeness_gate.py:175-216` 8 項測試獨立重跑 8 passed
- 事件級資料內部一致：253 筆日期唯一，平均報酬 / 237-16 分組 / VIX 中位數 / regime Welch / Pearson / Spearman 逐位吻合
- 無 event-window lookahead（`:434-449,480-545`）
- VIX regime 門檻用全樣本中位數 → 事後、樣本內分組，README:123-129 已誠實界定為條件關聯；**不可**當 OOS 預測證據
- `results.json:308` 的 "predicts" 建議改 "is associated with"
- **未發現造假、湊數字或 proxy fallback**（`:371-386` 無 fallback/except，`fallback: none`）

## 產出

`experiments/k528/k528_round5_remediation.json`，內含：
- `blockers`: B1–B4 各 `{id, decision, before, after, evidence: ["file:line", ...], tests_added: [...]}`
- `adversarial_tests`: B2 要求的同刪首/尾月測試 —— 給測試檔路徑 + 實際執行輸出（必須**看到它在未修版本會 fail**，才證明 gate 真的會響）
- `multiplicity`: 指定的 confirmatory family（含選定理由）+ Holm 調整後 p 值表
- `rerun`: `{command, exit_code, runtime_sec, output_json_path}`（若 B1 選了 release-weekday 路線則必須重跑）
- `unresolved`: 誠實列出沒修掉的

## 禁令

- ❌ 不要寫 `knowledge.json`（K1259：agent 禁自寫，由主線程寫）
- ❌ 不要 merge worktree、不要 certify、不要 `git push`
- ❌ 不要為了讓 gate 變綠而放寬 gate —— 修的是偵測能力，不是門檻
- ❌ 不要編造數字。任何數字都要能指回檔案:行號或重跑輸出
- ⚠️ 實驗代碼跑之前自檢：lag / signal.shift(1) 是否在代碼裡、baseline 是否同 lag、結果好得不像真的 = 90% 有 bug
