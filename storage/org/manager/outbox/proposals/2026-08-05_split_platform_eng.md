# 提案：拆分 platform_eng，新設 platform_ops

- **id**: 2026-08-05_split_platform_eng
- **提出時間**: 2026-08-05T14:40Z（台灣 22:40）
- **提出者**: manager
- **需要老闆**: 建立新部門（重大變更，依 policy.md 決策權限邊界需核准）
- **回覆方式**: Telegram 回 `approve 2026-08-05_split_platform_eng`（或 `reject ...`）

## 現況（數字來自 resource_monitor 全量盤點，report:
`storage/org/departments/resource_monitor/reports/2026-08-05_platform_eng_inbox_triage.md`）

- 七個部門中六個收件匣 <5 件（多數 0），**platform_eng 現在 95 件**（盤點當時 82→83，
  持續在漲，非陳年堆積——82 件全部產生於當天 07:44–21:03，age 0.0–0.2 天）。
- canonical 任務池另有 59 件 `queue_dispatch --dry-run` 顯示 100% 屬 platform_eng
  task_type，經理連續 4 輪判斷「不 --apply」，因為灌入只加深同一個漏斗，不解決產能瓶頸。
- 82 件的四類分佈：still_actionable 52（63.4%）／superseded 16／already_done 5／obsolete 9。
  真實負載是 52，不是全部 82，但也不是「大部分已失效」——36.6% 才是雜訊。
- 真正卡在外部依賴（Zone A／等老闆）的只有 4 件（3 Zone A + 1 等核准）。
  **48/52（92%）現在就能動手，沒有任何外部依賴**——瓶頸是產能，不是可見度或阻塞。

## 已發生的代價

- D39（老闆層 P0，questions/AuthButton 修復）被排到第四次才輪到動手。
- K1482／K1485（研究知識條目 canonical 標記）卡了一整天，因為結案動作外包給
  同樣積壓的 platform_eng，兩邊都以為對方會做。
- 治理部 policy.md 逐字修正、論文部 PRG v8 交接件，都排在同一個窗口後面。

## 分工建議

- **platform_eng**（產品面，task_type=`code_review`）留 `frontend-v2-fix/` + `config/`。
  這條線的節奏是「線上對讀者可用」，需要能被 P0 立即插隊。
- **新設 platform_ops**（工具面，task_type=`platform_ops`）接手 `scripts/` + `tests/`。
  82 件收件匣裡壓倒性多數是 ops 工具維護、gate 修復、pattern 生成器這類「產能瓶頸」
  性質的工作，跟「讀者能不能看到頁面」是兩種節奏，綁在一起會讓工具面的量把產品面的
  急件往後排。

## 誠實邊界（不誇大）

- 拆部門**不會讓 52 件變少**，只是讓兩種節奏不互相排隊、不共用同一個收件匣深度。
- 產能上限目前是 token 週限額（resource_monitor 量到本週 89%），拆部門不解決這個。
  若老闆認為現在不宜再開一個會耗 token 的常駐部門，這是合理否決——直接 reject 即可，
  經理會改走「platform_eng 內部依 task_type 排序 + 讓閒置部門（六個中多數 inbox=0）
  承接可代勞的唯讀工作（分流盤點、triage、驗證）」這條路線，不再重送同一案。
- `org_admin.py` 目前沒有 `propose` 子命令，本提案是用手寫檔案 + email 完成的
  變通做法；核准與否都建議之後補上這個子命令，否則提案沒有機械保證會被看到。
