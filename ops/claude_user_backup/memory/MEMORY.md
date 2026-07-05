# Memory Index

## User & References
- [user_profile.md](user_profile.md) — 賴奕豪，大葉大學財金系副教授，專長 copula-GARCH/hedging/高頻數據
- [reference_taifex_data.md](reference_taifex_data.md) — TAIFEX 數據位置/格式/欄位變動/夜盤時間
- [reference_lai_prs_paper.md](reference_lai_prs_paper.md) — PRS 論文 metadata（APFM 31(2), DOI, 延伸方向）
- [reference_anthropic_cache_ttl.md](reference_anthropic_cache_ttl.md) — Claude Code cache TTL 依 tier（Max=1h, Pro/API=5min）；continue_task cron */30 對齊邏輯
- [reference_notebooklm_rag_workflow.md](reference_notebooklm_rag_workflow.md) — NotebookLM 作為論文 / 文件 RAG 資料庫；cross-paper meta-eval / prior-art audit / reviewer R1 drafting 觸發時機
- [reference_publisher_strict_audit_tag_rules.md](reference_publisher_strict_audit_tag_rules.md) — feed-publisher 自動 strip K-id 到 details.experiment_refs metadata；tag ≤8 + 禁統計術語
- [reference_hourly_dispatch_via_os_cron.md](reference_hourly_dispatch_via_os_cron.md) — SUPERSEDED(7/4 cutover)：hourly dispatch 已改 com.volpred.dispatch-supervisor 常駐 daemon；in-flight 檢查=jq .current_job dispatch_state.json；OS-level trigger 原理仍成立
- [reference_compute_queue_token_split.md](reference_compute_queue_token_split.md) — Compute queue 把 heavy CPU work 分流；~75% K-experiment token 節省 (`*/15` worker cron + 2-phase hourly dispatch)
- [reference_dual_cli_availability.md](reference_dual_cli_availability.md) — Codex 0.130 ChatGPT auth + Gemini 0.42 `ideahub.everything` Pro 訂閱（2026-05-14 確認；Pro 可主力用 gemini-2.5-pro）
- [reference_knowledge_wiki_and_context_economy.md](reference_knowledge_wiki_and_context_economy.md) — Karpathy LLM-Wiki 編譯式知識庫(concept pages 互連) + context 經濟(CLAUDE.md 精簡=每 token 每回合付費；progressive disclosure；過門檻寫 handoff)
- [reference_strategy_card_metrics_window.md](reference_strategy_card_metrics_window.md) — 線上策略卡 metrics 是 2023-01 起 paper-trading 窗口；保守型 VT 低 MDD 是 VIX>20 清倉設計非 bug；canonical 全期在 K574
- [reference_zeabur_deploy_target.md](reference_zeabur_deploy_target.md) — 前端部署=CLI deploy-zeabur-safe.sh 到 volpred-v3（live domain）；搬機器只改 config.deploy 三 ID（新機器 project 6a15c5a8/env 6a15c5a85/v3 …117）；volpred-web 勿動
- [reference_antigravity_cli.md](reference_antigravity_cli.md) — Antigravity CLI (agy 1.0.0) 取代 gemini-cli；`~/.local/bin/agy`，預設模型 gemini-3.5-flash，OAuth 認證
- [reference_trending_blog_sources.md](reference_trending_blog_sources.md) — trending_repost 強制掃描清單（havingchien + Stratechery + 凱基/Ranger/元大 + 國外 forums）+ high-viral 3 類 (AI 發展/token maxxing/矽谷裁員)

## Projects
- [project_repo_moved_out_of_desktop.md](project_repo_moved_out_of_desktop.md) — 2026-07-02 repo 搬到 ~/volpred-research 根除 TCC；舊 Desktop 路徑=symlink
- [project_platform_vision_full.md](project_platform_vision_full.md) — 用戶 2026-05-29 完整願景：全自動不間斷自我運營（研究→論文/多元策略/文章→曝光→獲利），所有結果可復現，email 回報+回信指示
- [project_loop_engineering_layer.md](project_loop_engineering_layer.md) — 2026-06-29 上線 loop-engineering 閉環：loop-health 指標(fast loop)+dreaming 慢 loop(每日 propose-only)+內容巡檢補完；治理檔不自動改
- [project_refactor_safety_net.md](project_refactor_safety_net.md) — 2026-05-29 大改重構：volpred-refactor worktree + tag stable-pre-refactor-20260529；回滾指令在 docs/refactor_safety_net.md
- [project_prg_paper_framing.md](project_prg_paper_framing.md) — PRG 論文定位：PRS 簡化版+跨市場驗證
- [project_supabase_paid.md](project_supabase_paid.md) — Supabase 2026-03-24 付費升級
- [project_domain_migration.md](project_domain_migration.md) — 未來換網域的 SEO 遷移步驟
- [project_paper_portfolio_decisions_2026_04_27.md](project_paper_portfolio_decisions_2026_04_27.md) — Paper portfolio A/B/C/D tier（用戶 2026-04-27 授權自主決定）
- [project_platform_profitability_goal.md](project_platform_profitability_goal.md) — 平台 ultimate goal = 盈利；5-mission 是 means；task priority 加問「對 monetization 何貢獻」
- [project_fb_page_operation.md](project_fb_page_operation.md) — VolPred 粉專(id 61590464616031)由 AI 全權經營+優化+固定巡檢；Chrome 發文個人優先於粉專；headless API 卡 App Review
- [project_prepublish_content_gate.md](project_prepublish_content_gate.md) — 發佈前有 content-vs-source gate（prepublish_audit.py）；正確性驗證在 publish 之前；sync 改 hash-based
- [project_papers_awaiting_submit_decision.md](project_papers_awaiting_submit_decision.md) — 更正(7/4)：兩篇原 ready 論文均被誠實 re-review 撤回；M3 瓶頸=revision 收斂(prg=K1544 narrative、leverage=method-null rewrite)非投稿決策；停用「重提投稿」
- [project_strategy_lifecycle_standing_directive.md](project_strategy_lifecycle_standing_directive.md) — boss standing directive：策略持續增加，好的上架觀察壞的下架走既有 gate；3 檔高Sharpe inactive 的 lookahead audit 已完成(6/21 全 reject：c2c artifact)維持 inactive
- [project_cloud_agent_git_divergence.md](project_cloud_agent_git_divergence.md) — 雲端 Claude agent 每 6h push ops 報告到 origin/main 與本機研究線從 6/4 分岔；6/24 已同步(0/0)；待決定停掉或改 email-only；自動 push 待此決定後再建

## Feedback — Paper Submission
- [feedback_agent_markdown_not_tex.md](feedback_agent_markdown_not_tex.md) — Agent 寫 .md draft 不寫 .tex；2026-04-17 session 6 drafts ~20,000 words 高效 pattern
- [feedback_paper_multi_round_review.md](feedback_paper_multi_round_review.md) — Paper READY GREEN ≠ 可投稿；必須先跑多輪 paper-review-cycle（latex-academic-reviewer + citation-verifier）收斂
- [feedback_paper_cross_paper_meta_eval.md](feedback_paper_cross_paper_meta_eval.md) — 單篇 latex/citation review 看不到設計性結果 / 自我封閉研究生態；review cycle 必加 cross-paper meta-evaluation

## Feedback — Publishing & Content
- [feedback_report_content_sync.md](feedback_report_content_sync.md) — feed.json 和 reports/{id}.json content 必須同步
- [feedback_website_article_quality_4dim.md](feedback_website_article_quality_4dim.md) — 文章必有 4 維度（深度/可讀性/資訊性/參考性）才能持續吸引讀者回訪

## Feedback — Research & Methodology
- [feedback_research_rigor.md](feedback_research_rigor.md) — 樣本數要求（≥500）、跨 3 期間驗證、U-shape QLIKE 反面教材
- [feedback_execute_means_implement_plan.md](feedback_execute_means_implement_plan.md) — Plan 通過後「開始執行」= 實作計劃優化，不是切身份跑既有任務
- [feedback_hedging_vs_trading.md](feedback_hedging_vs_trading.md) — 避險用 HE/VaR/Utility，不跟交易策略比 Sharpe
- [feedback_session_close_assumption.md](feedback_session_close_assumption.md) — PRG/PRS 收盤價可交易假設；robustness 用收盤前 n 分鐘
- [feedback_session_boundary_forecast_timing.md](feedback_session_boundary_forecast_timing.md) — Session-boundary model 在 open 用已 realized overnight = legitimate timing（Paper 6 K880 判定原則）
- [feedback_long_sample_period.md](feedback_long_sample_period.md) — TAIFEX 日盤 2012 起 14 年；OOS 必含至少 1 次空頭

## Feedback — Tools & AI Collaboration
- [feedback_codex_cli_capability.md](feedback_codex_cli_capability.md) — Codex CLI 與 Claude Code 能力對等；不要誤說 Codex one-shot 或無法長任務
- [feedback_agent_output_extraction.md](feedback_agent_output_extraction.md) — Agent output JSONL 格式問題，用 JSON parser 不用 regex
- [feedback_3model_review_discipline.md](feedback_3model_review_discipline.md) — Production article 24h 內必走 Claude→Gemini→Codex 三模 review；Codex 中文 prompt 用 heredoc；Audit 走 3-pass grep variant framework
- [feedback_gemini_v042_skip_trust.md](feedback_gemini_v042_skip_trust.md) — Gemini v0.42+ headless 必加 `--skip-trust`，否則 `-y` 被 trust gate 覆寫成 default、stdout silent fail

## Feedback — Process Discipline
- [feedback_verify_before_restructure.md](feedback_verify_before_restructure.md) — 重構前必通盤查證所有相關文件和權威來源，不複製已有權威
- [feedback_dont_ask_do.md](feedback_dont_ask_do.md) — 判斷「建議做」之後立即執行，不問「要我直接做嗎？」型選擇題
- [feedback_dispatch_over_diversity.md](feedback_dispatch_over_diversity.md) — Type 多樣性不能造成 hold 空轉；沒 actionable 也要派一份工出去
- [feedback_no_user_policy_block.md](feedback_no_user_policy_block.md) — Paper narrative / 投稿 / 研究 pivot 等 policy task 一律自主執行，不寫「需用戶 policy direction」當 plateau 藉口
- [feedback_pool_fill_to_threshold.md](feedback_pool_fill_to_threshold.md) — Pool <4 時派 (4-current) 個 agent 並行補到滿，不是一次一個
- [feedback_gemini_cli_share_load.md](feedback_gemini_cli_share_load.md) — Gemini CLI 額度健康時主動分攤輕量任務（second-opinion review/大檔摘要/fact-check），prompt 必含 today date 降誤判
- [feedback_dedup_3_layers_mainthread.md](feedback_dedup_3_layers_mainthread.md) — 派寫作 agent 前主線程必做 3-layer 主題查重（candidates/grep/matrix），不僅靠 agent LanceDB
- [feedback_email_on_major_decisions.md](feedback_email_on_major_decisions.md) — 重要決策後主動 send_alert email 通知用戶（paper state 變、排程變、quota blocker 等）
- [feedback_decision_email_html_form.md](feedback_decision_email_html_form.md) — 需老闆做決策的 email 給可點選選項降摩擦，但 radio/textarea/<form> 在 email 裡破圖（html=False 逃逸+client strip）→ 改用每選項一個 mailto 連結（email-12487 2026-07-02 更正）
- [feedback_3spec_disambiguation.md](feedback_3spec_disambiguation.md) — Paper 內同 symbol 多 spec 數值差異的 footnote disambiguation + reproduce.py NOTE tier pattern（P1 K1256 + P2 γ 驗證）
- [feedback_agent_background_codex_polling_unreliable.md](feedback_agent_background_codex_polling_unreliable.md) — paper_review agent 用 background Codex + polling loop pattern 易留孤兒，改 foreground 同步

## Feedback — Operations & Deployment
- [feedback_test_before_deploy.md](feedback_test_before_deploy.md) — 前端修改只改一處、npm run build、測所有 tab
- [feedback_strategy_listing_quality.md](feedback_strategy_listing_quality.md) — 上架策略格式（weight 0.50、metrics 欄位、sparkline 90 點）
- [feedback_knowledge_index_update.md](feedback_knowledge_index_update.md) — 知識索引：mtime 新才更新、用 update 不用 build（避免炸 Gemini 額度）
- [feedback_notebooklm_skill_install.md](feedback_notebooklm_skill_install.md) — notebooklm-py 安裝必含 `notebooklm skill install` 註冊 SKILL.md，pip install 不會自動做

## Feedback — Skills & Structure
- [feedback_skill_structure.md](feedback_skill_structure.md) — SKILL.md 放方法論，研究結果放 research_program.md
- [feedback_skill_format.md](feedback_skill_format.md) — Skill frontmatter 格式：hyphen 不是 underscore
- [feedback_open_question_definition.md](feedback_open_question_definition.md) — Open Question 是大方向，小疑問放 thinking/knowledge
- [feedback_skill_autonomy.md](feedback_skill_autonomy.md) — Skill 可自主建立不需事先同意，但每月產出審查報告供用戶增刪
- [feedback_claudemd_keep_inline.md](feedback_claudemd_keep_inline.md) — CLAUDE.md 不拆分，參考資料保持 inline（Claude 常忘讀外部文件）
- [feedback_progressive_disclosure.md](feedback_progressive_disclosure.md) — CLAUDE.md 瘦身用 skill 漸進揭露，不是搬到 docs/xxx.md
- [feedback_keep_concise_mnemonics.md](feedback_keep_concise_mnemonics.md) — 精簡 CLAUDE.md 時保留一句話 mnemonic 摘要，別為省 200 tokens 丟掃讀價值

- [feedback_resume_ops_loop_after_user.md](feedback_resume_ops_loop_after_user.md) — 處理完用戶指令後必須流回 ops loop，不停在等下一句
- [feedback_finish_task_before_standby.md](feedback_finish_task_before_standby.md) — 任務不得做一半就排 wakeup/待機；完成=改完+build/test+部署+線上驗證+回報，才能待機
- [feedback_tasks_survive_session_close.md](feedback_tasks_survive_session_close.md) — 關 session/終端後下次開要能接續所有定時+非定時任務+巡檢；backbone(OS cron/LaunchAgent hourly-dispatch/ops_dashboard/check_alerts)須 session-independent；不可跑 install_host_crontab.sh(config drift 地雷)
- [feedback_content_quality_patrol_gap.md](feedback_content_quality_patrol_gap.md) — 自主運營缺「內容品質巡檢」層(節奏/主題多樣性/digest唯一/排版/前端render/內容完整)；今天4問題全靠人工發現；判準=只有用戶會發現的問題就是缺巡檢；設計在 docs/refactor_plan_content_quality_patrol.md
- [feedback_member_qa_evidence_based_prediction.md](feedback_member_qa_evidence_based_prediction.md) — member_qa 預測/估值/選股題要做不 decline；誠實的線是「方法（真數據+假設+不確定+可複現+免責）」不是「題目」
- [feedback_fb_dual_publish_precheck.md](feedback_fb_dual_publish_precheck.md) — FB 雙發佈 2026-06-19 恢復；發 FB 前必先用 Chrome 查老闆是否已手動發過同主題（已發→跳過只做 feed）
- [feedback_dont_deflect_act_on_repeated_complaints.md](feedback_dont_deflect_act_on_repeated_complaints.md) — 被反覆點名的問題要實做不要 deflect 成「正常/測量問題」；idle tick 要做真 M2/M3 closure（reviewed 實驗含 null 寫 knowledge）不空轉；knowledge_stale alert 已建

## Feedback — Governance Refactor
- [feedback_snapshot_before_refactor.md](feedback_snapshot_before_refactor.md) — 動 CLAUDE.md/rules/skills/memory 治理檔前先 commit snapshot + `snapshot:` prefix 留回滾點
- [feedback_path_narrowing_audit.md](feedback_path_narrowing_audit.md) — 改 rules paths frontmatter 前必填「workflow stage × paths」矩陣 6 欄，避免 silent skip
- [feedback_proactive_research_posture.md](feedback_proactive_research_posture.md) — 喚醒 = 主動生研究議題（文獻/R1/knowledge gap），不是 reactive 派既有 brief 就算交差
- [feedback_one_dispatch_per_hour.md](feedback_one_dispatch_per_hour.md) — hourly 派 1 agent（24 slot/day），任務 scope ≤50min cap，徹底完成才停止，heavy compute 走 compute_queue async
- [feedback_task_end_summary_format.md](feedback_task_end_summary_format.md) — 每次任務結束標準 4 項摘要（結束時間/總時間/完成項目/下次任務時間）
- [feedback_own_judgment_dont_credit_user.md](feedback_own_judgment_dont_credit_user.md) — 自主決策不歸因用戶；不寫「你說得對 / per your instruction」型開場 + 不等 ack
- [feedback_trending_repost_route.md](feedback_trending_repost_route.md) — 第 11 類 trending_repost：熱門文章 VolPred 角度改寫，無抄襲無引用，每日 ≤2 篇，雙發佈 feed + Ivan Lai FB
- [feedback_use_anti_ai_style.md](feedback_use_anti_ai_style.md) — 寫 zh-Hant reader-facing 文章必用 `.claude/skills/anti-ai-style/`：寫前讀 prompt-templates、寫後跑 editor-sop 9-checklist
- [feedback_reader_facing_3canon.md](feedback_reader_facing_3canon.md) — Reader-facing 文章（特別 trending_repost）開工前必讀 3 canonical（trending-repost SKILL + anti-ai-style SKILL + publishing rules）+ evidence package 先於 prose
- [feedback_digest_theme_first_whole_archive.md](feedback_digest_theme_first_whole_archive.md) — 精選導讀先由時事訂主題→從整庫找佐證回答主題（非本週 recap）；反覆糾正後升級 publishing.md rule + 機械 gate（archive-span，span<14天硬擋）
- [feedback_narrative_arc_dedup.md](feedback_narrative_arc_dedup.md) — Layer 4 dedup: 同邏輯 arc 不同外殼算 dup（N 換大、cut-point 變奏、proxy 換但同結論）
- [feedback_fb_opening_no_friend_asked.md](feedback_fb_opening_no_friend_asked.md) — FB Ivan Lai 貼文 anti-AI-style 完整規則（禁朋友問我 hook + 禁列表 + 禁解釋語氣 + 7 條 self-check）
- [feedback_autonomous_loop_email_summary.md](feedback_autonomous_loop_email_summary.md) — Autonomous ScheduleWakeup fire 結尾**必**寄 email summary 給老闆 + 排下次 wakeup（4-step protocol）
- [feedback_fb_personal_account_chrome_only.md](feedback_fb_personal_account_chrome_only.md) — FB 個人帳號只能走 Claude in Chrome，無 Graph API headless；trending 掃描用免費 agy
- [feedback_audit_no_passive_terminal.md](feedback_audit_no_passive_terminal.md) — Audit terminal set 不可含 awaiting_*/pending_* 被動狀態；否則 silent failure（2026-06-03 FB pipeline 4 天 100% 失敗 root cause）
- [reference_work_dashboard.md](reference_work_dashboard.md) — AI 工作監控 dashboard（常駐 LaunchAgent，http://127.0.0.1:8787）
- [feedback_cross_machine_file_links.md](feedback_cross_machine_file_links.md) — Mac Studio 遠端機；給用戶看的圖/檔/連結用 SendUserFile 或 Tailscale URL，不丟本機路徑
- [feedback_lazypack_infographic.md](feedback_lazypack_infographic.md) — 一般讀者文章文末附懶人包圖組；NotebookLM 能生圖、多圖 poster、餵 evidence package 寫文中生、禁付費 API
- [reference_frontend_nested_git_repo.md](reference_frontend_nested_git_repo.md) — frontend-v2-fix 是獨立巢狀 git repo（主 repo gitignore）；commit 前端要 cd 進去
- [feedback_no_cd_into_worktree_before_merge.md](feedback_no_cd_into_worktree_before_merge.md) — merge worktree 前勿 cd 進 worktree（持久 cwd 汙染使 merge_worktree.sh 誤刪未合併工作；K1032/K1618 root cause，merge 後必驗檔案存在）
- [feedback_worktree_stale_base_extract_by_path.md](feedback_worktree_stale_base_extract_by_path.md) — worktree 從 stale base 分出使 merge guard abort 時，用 `git checkout <branch> -- experiments/kXXXX/` path-scoped 抽取，勿硬 merge（K1619 實測零遺失）
- [feedback_proactively_complete_red_alerts.md](feedback_proactively_complete_red_alerts.md) — 看到紅色/critical 主動完成或排程完成並告訴老闆，不被動回報
- [feedback_continuous_work_and_read_mail.md](feedback_continuous_work_and_read_mail.md) — autonomous tick 要持續做實事不心跳空轉；mandate 直接讀 Gmail 最新信不靠 lagging task
- [feedback_refill_check_saturation_and_running_hourly.md](feedback_refill_check_saturation_and_running_hourly.md) — 補池/動 next_tasks 前必查 dispatch_state.json 的 current_job（cutover 後 pgrep 失效）+ 寫入走 flock；判斷 K 可寫要查 narrative-arc 飽和
- [feedback_journal_topic_discovery.md](feedback_journal_topic_discovery.md) — 研究方向自行從頂尖期刊(JBF/JFE/JPM/FAJ/CFA)挖不手寫;backlog 薄派 journal-discovery agent(週一/四 session_cron + prompt scripts/agent_prompts/journal_topic_scan.md)
- [feedback_recycling_is_release_layer_not_research.md](feedback_recycling_is_release_layer_not_research.md) — 文章「鬼打牆」根因在釋出端(draft 積壓+釋出偏 vix/spy+cluster 錯標)非研究端;生產前先掃 draft backlog、釋出挑 fresh cluster
- [reference_fb_chrome_browser_autoselect.md](reference_fb_chrome_browser_autoselect.md) — FB 發文固定自選 MAC STUDIO Chrome（deviceId bc09353b…）不問用戶；中文用 pbcopy+Cmd+V
- [feedback_boss_report_no_fb_handback.md](feedback_boss_report_no_fb_handback.md) — Boss report 禁列「還需要你做：FB awaiting」section（2026-06-08 email-11728 觸發；違反 AI 全自動運營 mission）
- [feedback_strategy_dev_over_audit.md](feedback_strategy_dev_over_audit.md) — 策略 effort 重發現/開發新策略 > audit 舊；舊策略是平台門面在沒更好的前先維持；audit 發現是 insight 不是 ops trigger

- [feedback_final_text_after_schedulewakeup.md](feedback_final_text_after_schedulewakeup.md) — 回用戶的文字必須是 turn 最終輸出;ScheduleWakeup 先叫、文字最後,否則用戶看不到
- [feedback_answer_first_then_act.md](feedback_answer_first_then_act.md) — 老闆問問題先答再動手；疑問句第一動作是文字回答不是跑指令；2026-07-02 三連糾正
- [feedback_telegram_emoji_formatting.md](feedback_telegram_emoji_formatting.md) — Telegram 訊息用 emoji 區隔段落/項目符號、加強重點
- [feedback_plain_language_boss_facing.md](feedback_plain_language_boss_facing.md) — 給老闆看的描述(alert/email/telegram/報告)用白話，不堆專有名詞；術語就地翻譯或替換
- [feedback_alerts_auto_act_not_suggest.md](feedback_alerts_auto_act_not_suggest.md) — 有 auto-remediation 的 alert body 寫「已自動修復+結果」不是「建議老闆行動」；發文脫班已 wire remediate_publish_drought.py（email-12559）
- [feedback_fix_silent_fallback_immediately.md](feedback_fix_silent_fallback_immediately.md) — git-push-backup 因 silent fallback hold push 時當場立刻修（warn/silent-ok + strict gate new=0 + 重跑 wrapper 解封），不丟給下一班 hourly（老闆 email-12564「以後自己立刻修」）
