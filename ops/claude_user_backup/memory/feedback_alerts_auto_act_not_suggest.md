---
name: feedback_alerts_auto_act_not_suggest
description: Boss-facing alert 有 auto-remediation 路徑時 body 必寫「已自動執行+結果」不是「建議老闆行動」；alert 要直接修不是丟 to-do 清單給老闆
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 411d9631-b9f2-4486-8971-7b1c84e88d71
---

2026-07-03 boss email-12559 對「發文脫班（publishing_freshness）CRITICAL alert」的糾正，原話：**「你應該不是建議行動 而是你應該要直接行動吧？」**

那封 alert body 寫了「## 建議行動（主線程 auto-remediation）1. 查 generator... 2. 立即釋出 `release-pool-by-settings`... 3. 派 daily_article...」—— 等於把一張待辦清單 email 給老闆要他做。

**Why**：VolPred 是 AI 全自動運營平台（老闆 = report-only）。outcome-level dead-man switch alert 的責任是**自己修復 breach**，不是把成因診斷 + CLI 指令列給老闆。alert email 給老闆的定位是「系統做了什麼、是否需人工介入」的 log，不是責任轉移。「建議行動」措辭讓老闆以為要親自下場，直接違反全自動 mission。

**How to apply**：
1. 凡有明確 auto-remediation 路徑的 alert（見 `.claude/rules/alert.md` auto-remediation 表左欄），body 行動段落一律寫「## 系統已自動修復 / 已自動執行 + 結果」，**禁**寫 imperative 的「## 建議行動（1. 跑 X 2. 派 Y）」給老闆。
2. 措辭誠實前提 = auto-remediation 必須**真的自動跑**。研究誠實延伸到 ops：不能只改措辭卻沒接 wire。發文脫班案 = 同 commit 把 `scripts/remediate_publish_drought.py`（force-release → refill fresh 主題供下班 hourly dispatch）接進 `scripts/check_alerts.py` 送信前，body 才敢寫「已自動修復」。
3. 只有真正需老闆 policy 判斷的 alert（投稿與否 / paid data 採購 / 研究 pivot）保留 boss-facing 決策段，且標「## 需老闆決策」不是「建議行動」。
4. 與 [[feedback_plain_language_boss_facing]]（白話化）、[[feedback_proactively_complete_red_alerts]]（看到紅色主動完成）、[[feedback_dont_deflect_act_on_repeated_complaints]] 同族 —— 都是「直接行動 result-level」而非「報告 / 建議 / deflect」。

發文脫班 wire 落地：`scripts/remediate_publish_drought.py`（單一 owner）+ `check_alerts._auto_remediate_publish_drought()` + `alerts._parse_publishing_freshness_state` body 重寫 + `tests/test_remediate_publish_drought.py`。對應 pending P1 `platform_ops_drought_auto_refresh_wiring`。
