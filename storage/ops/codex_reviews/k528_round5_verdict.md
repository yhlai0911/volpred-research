唯讀環境且題目未提供 out 檔路徑，因此未寫檔；以下為完整裁決。

# K528 round 5 verdict
verdict: FAIL  
reviewed_commit: 73dca01d0

## Blocking defects

- **K528-R5-B1 — Friday estimand 與 README 宣稱不一致**
  - 證據：`experiments/k528/k528_nfp_event_study.py:434-449,615-636`；`experiments/k528/README.md:24,78-87,113,138`；`experiments/k528/data/nfp_release_feed_fixture.json:41,77,101,139,212,236`
  - 程式用映射後的交易 session weekday 篩選 237 筆，而非官方發布日 weekday。253 個有效發布日其實有 243 個在週五；六個 Good Friday 發布日映射至下一個週一，因此被排除。README 卻反覆宣稱結果識別「在週五公布的 NFP」。所以 1.189× / p=0.0209 支持的是「NFP 消息在週五交易 session 被吸收」，不是「發布日在週五」。
  - 最小修法：同時保存 `release_date`、`session_date`；若保留現行分析，全文改稱 Friday trading-session estimand 並揭露六個 Good Friday 案例。若要回答發布日週五，須以 release weekday 篩選 243 筆並重新設計 weekday-matched controls、重跑結果。

- **K528-R5-B2 — raw 與 selected 同步截短一個端點月仍會通過**
  - 證據：`experiments/k528/k528_nfp_event_study.py:118-121,304-325`；`experiments/k528/k528_completeness_gate_fix.json:140-145`
  - 獨立重現：誠實 fixture 為 260 raw / 254 selected；同刪 `2005-01` 後 259/253、head shortfall 34 天仍通過；同刪 `2026-03` 後 259/253、tail shortfall 44 天仍通過。70 天容忍度允許整個月消失，raw-selected、缺月與 allowlist 三道檢查都無法察覺。
  - 這不推翻目前 archived 數字，但推翻 README 的 fail-closed 宣稱，亦不符合本輪 PASS 所要求的「gate 守得住」。
  - 最小修法：對這個固定歷史樣本釘住預期首尾月份或預期發布數；或用獨立 as-of/release-schedule 判斷應已發布的月份。新增同時刪 raw 與 selected 首／尾月的對抗測試。

- **K528-R5-B3 — 價格資料尾端截短也不會 fail closed**
  - 證據：`experiments/k528/k528_nfp_event_study.py:396-415,453-465`
  - `yf.download` 後沒有 SPY/^VIX 覆蓋範圍或 freshness gate。若 SPY 尾端少一個月，後續 NFP 會被歸為 `outside_price_sample` 並繼續產生結論；若 VIX 尾端短缺，`ffill()` 可沿用陳舊 VIX。當前結果檔確實記錄零筆 outside，但流程仍可在未來重跑時合法縮樣。
  - 最小修法：固定歷史樣本要求 SPY/^VIX 覆蓋至預期端點、`n_outside_price_sample == 0`，並限制 VIX forward-fill 的最大資料年齡。

- **K528-R5-B4 — 未定義多重比較 family，卻以 5% 宣稱顯著**
  - 證據：`experiments/k528/README.md:66-67,99,113,137-140`；`experiments/k528/k528_nfp_event_study.py:611-710`；`experiments/k528/k528_nfp_event_study_results.json:117-175,178-284`
  - 腳本產生 A–J、12 個月份及兩種 VIX 相關等多個 p 值，但沒有 multiplicity correction 或 confirmatory/exploratory 分界。週五結果 p=0.0209 因此只能稱 nominal significance。
  - 若 family 限於 README 列出的六個主要檢定，Holm 後約為 0.0417，結論仍可保留；若涵蓋腳本全部 22 個 inferential outputs，示意 Holm 值約為 0.375。現在沒有預先定義 family，無法判斷哪個口徑合法。
  - 最小修法：指定 rerun 前既有的 confirmatory endpoints，報告 Holm／Romano-Wolf 調整值；其餘明標 exploratory。未完成前不得無限定地寫「顯著」。

## Non-blocking observations

- v6 的 allowlist 後門確實已關閉：`k528_nfp_event_study.py:272-345` 有 unconditional raw→selected、allowlist 不重疊及全 raw counter-check；`test_k528_completeness_gate.py:175-216` 的 8 項測試獨立重跑為 `8 passed`。
- 現有事件級資料內部一致：253 筆日期皆唯一；重算平均報酬、237/16 分組、VIX 中位數、regime Welch、Pearson、Spearman，均逐位吻合結果檔。
- 未發現 event-window lookahead：發布日只向下一交易日映射，T−5…T−1、T、T+1…T+5 切片明確，見 `k528_nfp_event_study.py:434-449,480-545`。
- VIX regime 的門檻使用全樣本中位數，屬事後、樣本內分組；`README.md:123-129` 已誠實界定為條件關聯而非因果。它不能作 OOS 預測證據。
- README 對 VIX/NFP 大小比較已有非因果與「未正式比較」限制；但結果檔 `k528_nfp_event_study_results.json:308` 的 “predicts” 最好改成 “is associated with”。
- 未見造假、湊數字或 proxy fallback。`k528_nfp_event_study.py:371-386` 沒有 fallback/except；結果檔也明載 `fallback: none`。上述 partial-feed 問題是 fail-open completeness defect，不是偽造證據。

## 對殘留 gap（single-month upstream truncation）的裁決

**blocking**

理由：這是固定、已完全落後於執行日的歷史樣本，不是「當月報告可能尚未發布」的即時查詢。70 天容忍允許完整首月或尾月消失，與 README 的 fail-closed 宣稱及本輪 PASS gate 直接衝突。僅在額外加入獨立 endpoint expectation，或至少撤回 fail-closed 宣稱並明確限制適用範圍後，才可能視為可接受設計取捨。
