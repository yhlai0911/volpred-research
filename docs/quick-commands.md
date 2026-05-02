# 快速指令

```bash
# 研究
uv run volpred summary                              # 研究摘要
uv run volpred analyze-data --asset SPY              # 資料特性
uv run volpred run-experiment --asset SPY --model gjr_arch --window 2000
uv run python scripts/build_knowledge_index.py auto  # 知識索引（增量，偵測變化才重建，省 API）

# 每日運營
uv run python scripts/daily_update.py                # 每日更新（策略計算 + 績效重算 + Supabase 同步）
uv run python scripts/recalc_metrics.py              # 手動重算績效指標
uv run python scripts/supabase_sync.py full          # 手動 incremental sync
uv run python scripts/supabase_sync.py force-full    # 強制全量同步（慎用，IO 大）
uv run volpred ops health                            # 本地營運健康檢查
uv run volpred ops queue-summary                     # 緊湊 queue 摘要（低 token 巡檢首選）
uv run volpred ops daily-planning-maintain --stub-if-no-work  # 每日規劃 gate；沒 gap 直接 tiny stub
uv run volpred ops continue-task-maintain --stub-if-no-work   # continuation gate；沒 runnable work 直接 tiny stub
uv run volpred ops scheduler-summary                 # 緊湊 scheduler / crontab 摘要
uv run volpred ops token-summary                     # 緊湊 token / cost 摘要（讀既有 daily reports）
uv run volpred ops token-usage-maintain --stub-if-no-work  # token 日報/週報 wrapper；已新鮮時直接 tiny stub
uv run volpred ops token-policy-summary              # token / context canonical 門檻摘要
uv run volpred ops log-summary                       # 緊湊 cron / hook log 摘要
uv run volpred ops git-sync-maintain --stub-if-no-work      # git sync preflight；clean branch 直接 tiny stub
uv run volpred ops ndc-indicator-maintain --stub-if-no-work # NDC 月度 freshness gate；CSV 已新鮮時直接 tiny stub
uv run volpred ops knowledge-index-summary           # 緊湊知識索引 freshness / drift 摘要（含 recommended_action）
uv run volpred ops knowledge-index-maintain --stub-if-no-work  # 知識索引維護 wrapper；沒事只回 tiny stub
uv run volpred ops publication-candidates-summary    # 緊湊 publication 候選摘要（寫文前先看）
uv run volpred ops platform-patrol-summary           # 緊湊平台巡檢摘要（先看 release / alerts / questions）
uv run volpred ops platform-patrol-maintain --stub-if-no-work  # 平台巡檢 wrapper；沒事只回 tiny stub
uv run volpred ops question-ops-summary              # 緊湊會員問題摘要（先看 pending，再決定是否開完整 workflow）
uv run volpred ops question-ops-maintain --stub-if-no-work     # 會員問題 gate；沒 pending 直接 tiny stub
uv run volpred ops memory-health-summary             # 緊湊記憶健康摘要（先看大小 / duplicates / orphan worktrees）
uv run volpred ops scheduler-preview                 # 預覽 shared scheduler 下一輪會做什麼
uv run volpred ops scheduler-tick                    # 手動跑一輪 shared scheduler
uv run volpred ops scheduler-smoke --cleanup         # 隔離 mock smoke，不碰真實 Claude/Codex CLI
uv run volpred ops scheduler-live-smoke --cleanup    # 隔離 live smoke，真打本機 Claude/Codex CLI
uv run volpred ops article-backups --repair          # 確保每篇已發布文章都有本地單篇 JSON，可用於 DB 災難復原
uv run volpred ops sync-all                          # 統一入口：手動 Supabase sync
uv run volpred ops daily-update                      # 統一入口：每日更新
uv run volpred ops recalc-metrics                    # 統一入口：重算績效指標
uv run volpred ops paper-list                        # 查看論文與 Storage 狀態
uv run volpred ops paper-upsert --paper-id xxx --title "..." --authors "..."
uv run volpred ops paper-upload-pdf --paper-id xxx --file paper/<name>/main.pdf
uv run volpred ops paper-migrate-storage --paper-id xxx

# 策略管理（只寫 DB，不需部署）
uv run python scripts/list_new_strategy.py --list-all                          # 查看所有策略上線狀態
uv run python scripts/list_new_strategy.py --key xxx --verify-only             # 驗證單一策略
uv run python scripts/list_new_strategy.py --key xxx --name "名稱" --howto "說明" --description "完整說明" --assets '{"SPY":50}' --order N  # 一鍵上架
uv run python scripts/add_strategy.py --id xxx --name "名稱" --howto "說明" --description "完整說明" --assets '{"SPY":50}' --order N
uv run volpred ops strategy-upsert --strategy-key xxx --strategy-name "名稱" --weights-json '{"SPY":0.5}'
uv run volpred ops strategy-set-active xxx --inactive

# Jobs 與 Worker（agent-first ops）
uv run volpred ops jobs --status queued              # 查看待處理任務
uv run volpred ops job-show <job_id>                 # 查看任務詳情及日誌
uv run volpred ops enqueue --action daily_update     # 手動入隊任務
uv run volpred ops worker --poll-interval 10         # 啟動本地 worker

# experiments/ 結構整理（新規先行 + touched-file migration）
uv run volpred ops experiments report                # 查看 experiments/ 根層散檔與遷移候選
uv run volpred ops experiments scaffold --experiment-id k1121 --title "..."   # 建立 experiments/k1121/ 標準骨架
uv run volpred ops experiments migrate --experiment-id k1121                  # 只看遷移計畫（dry-run）
uv run volpred ops experiments migrate --experiment-id k1121 --apply          # 實際搬移該實驗的根層散檔

# Zeabur CLI（部署 + 域名管理）
# Project ID: 69b5b264800a475a1f82b073
# Environment ID: 69b5b2646853f6f4f5f6a16d
# Services: volpred-web (69b5b279e0a0c18cef9d780d), volpred-v2 (69b8ed895a53b5901a3c8d25), volpred-v3 (69be521a1066986b9a1692be)
npx zeabur@latest auth status                    # 確認登入狀態
npx zeabur@latest service list --project-id 69b5b264800a475a1f82b073 --json  # 列出服務
npx zeabur@latest domain list --id <service_id> -i=false --json              # 列出域名
npx zeabur@latest domain create --id <service_id> --domain <subdomain> --env-id 69b5b2646853f6f4f5f6a16d -g -y -i=false  # 綁定 *.zeabur.app 域名（-g 時只寫子域名如 'volpred'，不要寫完整 'volpred.zeabur.app'）
npx zeabur@latest domain delete --id <domain_id> -i=false -y                 # 刪除域名
npx zeabur@latest service redeploy --id <service_id> -i=false -y             # 重新部署
# 安全部署前端代碼到 live service（volpred.zeabur.app -> volpred-v3 service）:
cd frontend-v2-fix && ./scripts/deploy-zeabur-safe.sh
# 文件：docs/zeabur-safe-deploy.md
# 注意：所有 CLI 命令加 -i=false 避免互動式 prompt

# 發佈
uv run python scripts/record_and_publish.py --title "標題" --thinking "推理" --knowledge "知識" --phase "Phase_X"
uv run volpred ops publish-milestone --title "標題" --description "Markdown 內容" --phase "Phase_X"
uv run volpred ops release-pool-by-settings --storage-dir storage
uv run volpred ops send-article-notification mile_xxxxxxxx
uv run volpred ops send-daily-digest --target-date 2026-03-21
uv run volpred ops unpublish mile_xxxxxxxx
uv run volpred ops cleanup-post mile_xxxxxxxx --hard-delete

# 會員問題排行
uv run volpred ops question-ops-summary
uv run volpred ops question-ranking-summary --limit 20
uv run volpred ops question-rerank --evaluations-json '[...]'
```
