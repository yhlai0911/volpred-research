# K528 — Codex round 5 primary-path review（NFP official-dates event study）

你是獨立審稿人。判斷這份實驗的**主結論是否站得住**，不是找 style issue。
讀寫權限為唯讀 —— 不要嘗試修任何東西，只出裁決。

## 標的

- worktree：`.claude/worktrees/dispatch-slot-3-30adeed7-k528nfp`
- branch：`k528-nfp-official-dates`，審這個 commit：`73dca01d0`
- 主腳本：`experiments/k528/k528_nfp_event_study.py`
- 結果：`experiments/k528/k528_results.json`、`experiments/k528/README.md`
- 前幾輪裁決：`experiments/k528/review_verdict_v*.json`（v6 是最近一輪，FAIL，唯一 blocking defect = completeness gate 的 allowlist 後門）

## 這一輪的前提（已由 stage 1 驗證，可直接採信但歡迎推翻）

1. v6 的 blocking defect 已由 commit `726a34fb0` 關閉，證據在
   `experiments/k528/k528_completeness_gate_fix.json`。
2. `experiments/k528/test_k528_completeness_gate.py` 是該後門的對抗性迴歸測試，
   8 tests 全綠，且內含 anti-vacuity（三道防線全關 → 攻擊成功；任一道在 → 攻擊被擋）。
   主線程已於 2026-07-20 03:09 獨立重跑確認 8 passed。
3. sample span 沒變（260 raw / 254 selected，2005-01-01..2026-03-27）；headline 數字未動。

## 要回答的問題（依序，每題都要給證據行號或檔名）

1. **主結論是否被資料支持**：README / results.json 宣稱的 event-study 效果，
   在給定的樣本、視窗、標準誤設定下是否成立？有無 lookahead、
   有無用未來資訊決定 event window、有無多重比較未校正卻宣稱顯著。
2. **completeness gate 現在是否真的守得住**：除了 stage 1 已關的 allowlist 後門，
   還有沒有別條路能讓樣本被悄悄截短而 gate 不叫。
   （stage 1 自己找到一條殘留：raw feed 本身短一個尾月時，44 天缺口 < 70 天
   `MAX_WINDOW_SHORTFALL_DAYS` 容忍度，三道檢查都看不到，因為 raw 與 selected 一起短。
   請判斷這條是否構成 blocking，還是可接受的設計取捨 + 誠實載明即可。）
3. **README 的宣稱是否超出證據範圍**：有無 causal 語言、有無把 mechanical 結果講成 empirical finding。
4. **有無任何造假 / 湊數字 / 靜默 fallback**。

## 輸出格式（Markdown，寫進指定的 out 檔）

```
# K528 round 5 verdict
verdict: PASS | FAIL
reviewed_commit: 73dca01d0

## Blocking defects
（每條：id / 檔名:行號 / 為什麼這會讓結論不成立 / 最小修法。沒有就寫 none）

## Non-blocking observations
## 對殘留 gap（single-month upstream truncation）的裁決
blocking | acceptable_with_disclosure —— 並說明理由
```

**PASS 的門檻**：主結論成立、gate 守得住、README 不超出證據。
不確定就給 FAIL 並寫清楚要補什麼 —— 放行一份有問題的實驗比擋下一份好的代價高得多。
