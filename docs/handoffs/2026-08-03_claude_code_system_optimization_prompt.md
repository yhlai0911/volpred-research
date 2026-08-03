# 可直接貼給 Claude Code 的接續提示詞

你現在接手 VolPred 系統優化。原則上用繁體中文回報，但不要先長篇解釋，直接執行。

先完整讀：

1. `AGENTS.md`
2. `docs/handoffs/2026-08-03_claude_code_system_optimization_handoff.md`
3. `storage/ops/handoff_latest.md` 第一條 `---` 前
4. `docs/error_log_archive/2026-Q3-article-continuity.md`
5. `docs/refactor_plan_ops_master_2026_07.md` §7 與第一張未阻塞 ticket 的 blocking edge

目前已落地 commit `f8da0b7a2`：release pool `eligible=0` 時，Operations Core 每分鐘用 model-free article-continuity actuator 批次提升 pending daily_article、精準 nominate 最老一張，並留下 durable `request_fire`；schedule receipt ledger 也已由 27.6MB 壓到約 6.9MB 且有界。交接當下 `K1706_article_general` 正等待唯一安全 slot，slot 內是 `ci-red-30736983439`。這些是時間點快照，先 live read-back，不可憑提示詞直接判定仍然成立。

你的任務不是再寫一份計畫，而是持續執行並完成：

1. 先追蹤目前 CI job settlement，驗證下一個 fire exact claim K1706（或 continuity successor），直到 canonical draft、release preview eligible、正式 release、feed/API/live URL acknowledgement 全鏈通過。不要殺 worker、不要 release 別人的 claim。
2. 驗證剛同步的 compute admission 在 Claude slot=1 時仍能充分使用 CPU；量測 queue wait、utilization、admission、token usage。model-free/程式運算不可因 agent slot 忙碌而停擺。
3. 找出所有「只通知、不修復」alert path，逐條接成 detector → repair actuator/task → request fire → regression → live read-back → success-only notification。blocked/contained 不得冒充成功。
4. 不可直接把 Claude slots 從 1 調高。先完成 shared-launchd per-fire isolation、custody、kill/reload safety 與 live canary；否則用 compute queue 擴吞吐並保留 safety cap。
5. Graphify query-first：先 `reflect --if-stale`、讀 LESSONS、檢查 freshness，再用 `scripts/graphify_integration.py query`。Graphify 是 map，不是 proof。補完 root/active-frontend 分離 freshness 與可重跑 token A/B；官網功能只用官方/GitHub primary source逐項核對。

執行規則：

- 問題宣稱完成前必過五步 Gate；只使用 `contained` / `root_cause_fixed_and_verified`。
- 工作樹很髒，保留所有其他人的變更；禁止 reset/checkout/廣域 stage。
- 不手改 canonical storage 收尾；使用正式 CLI/writer。
- shared main commit 只能 `uv run python scripts/git_writer_lock.py commit --actor claude-main --task-id <id> --message '<ASCII>' -- <exact paths>`；不 push。
- 修改既有 skill 必依 AGENTS.md 寄 Skill 修改通知並跑完整 architecture gate。
- 每完成一個底層閉環就立即跑 targeted regression、Graphify update、live read-back；不要累積到最後才驗證。
- owner 最後只要看到修復成功通知：發生的問題、根因、最終步驟/方法、驗證結果。不要寄只有告警沒有修復的「成功」通知。

起手先執行 handoff §6 的命令，然後從 §4.A 開始。只要還有安全、明確、在 scope 內的下一步，就繼續做，不要停在報告。
