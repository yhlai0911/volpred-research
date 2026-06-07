# K506 Codex 24h Review — 2026-06-07

**Article**: mile_d8e36bcb 「在 VT 策略上多加一個訊號，反而輸了？ — 五段歷史測試告訴你真相」
**Published**: 2026-06-07T10:01:13Z
**Retracted**: 2026-06-07T12:15:00Z (~2h after publish)
**Review trigger**: paper_review_mile_d8e36bcb (Codex 24h-rule per .claude/rules/agent-delegation.md K1018 lesson)
**Reviewer**: Codex CLI 0.135.0 (gpt-5.4) via main thread
**Verdict**: **FAIL**

## Issues

1. **Lookahead bias** [k506_ewt_volspread_cross_oos.py:236-255]
   `target_w` 用 `vix[i]` + `vol_ratio[i]` 決定當日權重，同迴圈立刻吃 `tw50_ret[i]`。t 日訊號決定 t 日報酬，未做 signal.shift(1)。

2. **Vol spread signal lag bug** [py:154-157, 238-244]
   `ewt_vol/tw50_vol` rolling window 預設含當日觀測。「t-1 only」聲明不成立。

3. **DM/Harvey overclaim** [py:289-310, 350-354, 426-429; results.json:133-135, 231-234]
   文章寫「五段 DM p=0.070」實為 pooled test。5 段+pooled=6 次檢定無 Bonferroni/BH 校正；校正後全部 not significant。

4. **Cost version inconsistency** [py:17, 67-69, 509; json:17-19]
   Code 已改 round-trip 0.001855 (0.1855%)，results.json 仍是 0.00585 (0.585%)。Results 不是 source 的可信輸出。

5. **Number provenance error** [json:148-149, 249, 223-234; py:6-7]
   文章 1.66% / 2.49% 不在 results.json，引自舊實驗 K505 註解。

## Action

- ✅ Feed status → retracted; retraction metadata 加入 feed.json entry
- ✅ Correction notice prepended to content + description (top of article)
- ✅ K506_retry_lookahead_fix P1 排入 next_tasks (task_type=experiment)
- ⏳ Codex review 通過 + new article 發布前禁引用此 K506 數字
- ⏳ knowledge.json provenance：retraction 記號待 K506_retry 完成後同步

## Codex full output

VERDICT: FAIL — 詳見 codex exec 完整輸出，存於 work_log 與本次 hourly fire 對話紀錄。
