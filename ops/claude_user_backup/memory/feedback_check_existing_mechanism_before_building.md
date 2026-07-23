---
name: feedback-check-existing-mechanism-before-building
description: 建新機制前先查同 concern 是否已有機制存在但未啟用（switched-off ≠ 不存在）
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 088b57da-f99e-4210-b03d-8f127c98bc2c
---

2026-07-14 token/ops 浪費重構日發現：計畫要「新建」的 5 個機制中有 3 個其實已存在 —
pregate 已建好只差 config 一行 flip（shadow→enforce）、dreaming 的 auto_dispatch 在
7/12 已預設 ON 且任務已排隊、next_tasks status 詞彙 gate 已有 TASK_STATUSES + CI
baseline。若直接動手建新的，就是三次 anti-stacking 違規。

**Why**：這個平台迭代快，機制常在「建好但 shadow/預設關/等觀察期」狀態；審計掃描看到的
「問題仍在發生」不等於「沒有機制」，可能是機制在等 gate 數據（pregate 案例裡 crosscheck
明示先修 attribution 再 flip — 裸 flip 反而危險）。

**How to apply**：任何「加 gate / 加監測 / 加詞彙表 / 加閉環」的計畫項，動手前先
grep 同 concern 的 script/config/CLI flag（`--apply`、`mode`、`shadow`、`baseline`、
`enforce` 是常見開關詞），並讀該機制自己的 verdict/log 判斷它為什麼還沒生效。
修「為什麼沒生效」永遠優先於再蓋一層。關聯 [[project-loop-engineering-layer]]、
anti-stacking（CLAUDE.md）。

**2026-07-20 同一錯誤的鏡像版**：對老闆宣稱「我沒有正式 CLI 可以開 burst window，
不想背著你動控制檔」——實際上 `scripts/dispatch_burst_cli.py`（open/status/close）
一直存在。老闆因此多等了一輪派工才回「開到今天下午四點」。**推論**：「宣稱某能力不存在」
和「動手建新機制」是同一個查證義務，前者甚至更貴，因為它把工作推回給老闆。
說「做不到 / 沒有工具 / 需要你授權」之前，先 `grep -rli <concern> scripts src config`。
