# Memory Index

## User & References
- [user_profile.md](user_profile.md) — 賴奕豪，大葉財金副教授；copula-GARCH/hedging/高頻
- [reference_taifex_data.md](reference_taifex_data.md) — TAIFEX 數據位置/格式/夜盤時間
- [reference_lai_prs_paper.md](reference_lai_prs_paper.md) — PRS 論文 metadata + 延伸方向
- [reference_anthropic_cache_ttl.md](reference_anthropic_cache_ttl.md) — cache TTL 依 tier（Max=1h）
- [reference_notebooklm_rag_workflow.md](reference_notebooklm_rag_workflow.md) — 外部文獻 RAG 走 NotebookLM 的觸發時機
- [reference_publisher_strict_audit_tag_rules.md](reference_publisher_strict_audit_tag_rules.md) — K-id 自動移到 metadata；tag ≤8 禁統計術語
- [reference_hourly_dispatch_via_os_cron.md](reference_hourly_dispatch_via_os_cron.md) — SUPERSEDED：派工改 dispatch-supervisor daemon
- [reference_compute_queue_token_split.md](reference_compute_queue_token_split.md) — heavy compute 進 queue，~75% token 節省
- [reference_dual_cli_availability.md](reference_dual_cli_availability.md) — Codex/Gemini CLI 認證與可用性
- [reference_knowledge_wiki_and_context_economy.md](reference_knowledge_wiki_and_context_economy.md) — 編譯式知識庫 + context 經濟
- [reference_strategy_card_metrics_window.md](reference_strategy_card_metrics_window.md) — 策略卡 metrics 窗口；低 MDD 是設計非 bug
- [reference_zeabur_deploy_target.md](reference_zeabur_deploy_target.md) — 部署走 deploy-zeabur-safe.sh 到 volpred-v3
- [reference_antigravity_cli.md](reference_antigravity_cli.md) — agy CLI 取代 gemini-cli
- [reference_trending_blog_sources.md](reference_trending_blog_sources.md) — trending 掃描來源清單 + high-viral 類型
- [reference_unified_memory_one_brain.md](reference_unified_memory_one_brain.md) — Telegram 與本機共用同一記憶，勿建 channel 專屬
- [reference_work_dashboard.md](reference_work_dashboard.md) — 監控 dashboard http://127.0.0.1:8787
- [reference_frontend_nested_git_repo.md](reference_frontend_nested_git_repo.md) — frontend-v2-fix 是巢狀 repo，commit 要 cd 進去
- [reference_worktree_pytest_wrong_interpreter.md](reference_worktree_pytest_wrong_interpreter.md) — worktree 內用 `uv run --extra dev python -m pytest`
- [reference_fb_chrome_browser_autoselect.md](reference_fb_chrome_browser_autoselect.md) — FB 發文自選 Chrome，中文用 pbcopy 貼上
- [reference_chrome_browser_identity_map.md](reference_chrome_browser_identity_map.md) — Chrome deviceId 身分對照；禁止用裸 id 問老闆選瀏覽器

## Projects
- [project_platform_profitability_goal.md](project_platform_profitability_goal.md) — 終極目標=盈利；5-mission 是手段
- [project_platform_vision_full.md](project_platform_vision_full.md) — 全自動不間斷自我運營的完整願景
- [project_myth_lab_series.md](project_myth_lab_series.md) — 系列「迷思實驗室｜」規格
- [project_event_thermometer_series.md](project_event_thermometer_series.md) — 系列「事件溫度計｜」規格
- [project_repo_moved_out_of_desktop.md](project_repo_moved_out_of_desktop.md) — repo 已搬 ~/volpred-research，單一 canonical
- [project_loop_engineering_layer.md](project_loop_engineering_layer.md) — loop-health + dreaming 閉環
- [project_refactor_safety_net.md](project_refactor_safety_net.md) — 大改的回滾 tag/worktree
- [project_prg_paper_framing.md](project_prg_paper_framing.md) — PRG 論文定位
- [project_supabase_paid.md](project_supabase_paid.md) — Supabase 已付費
- [project_domain_migration.md](project_domain_migration.md) — 換網域的 SEO 遷移步驟
- [project_paper_portfolio_decisions_2026_04_27.md](project_paper_portfolio_decisions_2026_04_27.md) — 論文 A/B/C/D tier 分級
- [project_codex_audit_20260710_disposition.md](project_codex_audit_20260710_disposition.md) — Codex 稽核裁決：做什麼、不做什麼
- [project_fb_page_operation.md](project_fb_page_operation.md) — VolPred 粉專由 AI 全權經營
- [project_reader_preference_feedback_loop.md](project_reader_preference_feedback_loop.md) — 讀者偏好自動分析=常態運營輸入（選題/圖文表）
- [project_prepublish_content_gate.md](project_prepublish_content_gate.md) — 發佈前 content-vs-source gate
- [project_papers_awaiting_submit_decision.md](project_papers_awaiting_submit_decision.md) — M3 瓶頸=revision 收斂，非投稿決策
- [project_strategy_lifecycle_standing_directive.md](project_strategy_lifecycle_standing_directive.md) — 策略持續增減走既有 gate
- [project_cloud_agent_git_divergence.md](project_cloud_agent_git_divergence.md) — 雲端 agent 與本機 git 分岔史
- [project_canonical_write_test_leak_gate.md](project_canonical_write_test_leak_gate.md) — 「測試寫 canonical storage」的 class gate

## Feedback — 研究與論文
- [feedback_research_rigor.md](feedback_research_rigor.md) — 樣本 ≥500、跨 3 期間驗證
- [feedback_hedging_vs_trading.md](feedback_hedging_vs_trading.md) — 避險用 HE/VaR/Utility，不比 Sharpe
- [feedback_session_close_assumption.md](feedback_session_close_assumption.md) — 收盤價可交易假設
- [feedback_session_boundary_forecast_timing.md](feedback_session_boundary_forecast_timing.md) — open 用已 realized overnight 是合法 timing
- [feedback_long_sample_period.md](feedback_long_sample_period.md) — OOS 必含至少一次空頭
- [feedback_agent_markdown_not_tex.md](feedback_agent_markdown_not_tex.md) — Agent 寫 .md 不寫 .tex
- [feedback_paper_multi_round_review.md](feedback_paper_multi_round_review.md) — READY ≠ 可投稿，必多輪 review 收斂
- [feedback_paper_cross_paper_meta_eval.md](feedback_paper_cross_paper_meta_eval.md) — review 必加 cross-paper meta-eval
- [feedback_paper_autonomy_optimize_acceptance.md](feedback_paper_autonomy_optimize_acceptance.md) — 論文方法/期刊/投稿時機自主判斷
- [feedback_3spec_disambiguation.md](feedback_3spec_disambiguation.md) — 同 symbol 多 spec 的 footnote 消歧
- [feedback_journal_topic_discovery.md](feedback_journal_topic_discovery.md) — 研究方向從頂尖期刊挖，不手寫
- [feedback_proactive_research_posture.md](feedback_proactive_research_posture.md) — 喚醒=主動生議題，非 reactive 派舊 brief
- [feedback_strategy_dev_over_audit.md](feedback_strategy_dev_over_audit.md) — 重開發新策略 > audit 舊策略
- [feedback_execute_means_implement_plan.md](feedback_execute_means_implement_plan.md) — 「開始執行」=實作計劃，非跑既有任務

## Feedback — 內容與發佈
- [feedback_website_article_quality_4dim.md](feedback_website_article_quality_4dim.md) — 文章 4 維度（深度/可讀/資訊/參考）
- [feedback_use_anti_ai_style.md](feedback_use_anti_ai_style.md) — reader-facing 必走 anti-ai-style skill
- [feedback_reader_facing_3canon.md](feedback_reader_facing_3canon.md) — 開工前必讀 3 canonical + evidence 先於 prose
- [feedback_dedup_3_layers_mainthread.md](feedback_dedup_3_layers_mainthread.md) — 派寫作 agent 前主線程做 3-layer 查重
- [feedback_narrative_arc_dedup.md](feedback_narrative_arc_dedup.md) — 同邏輯 arc 換外殼也算重複
- [feedback_digest_theme_first_whole_archive.md](feedback_digest_theme_first_whole_archive.md) — 導讀先訂主題→撈整庫，非本週 recap
- [feedback_recycling_is_release_layer_not_research.md](feedback_recycling_is_release_layer_not_research.md) — 鬼打牆根因在釋出端非研究端
- [feedback_report_content_sync.md](feedback_report_content_sync.md) — feed.json 與 reports/{id}.json 必同步
- [feedback_lazypack_infographic.md](feedback_lazypack_infographic.md) — 一般讀者文章文末附懶人包圖組
- [feedback_trending_repost_route.md](feedback_trending_repost_route.md) — trending_repost 規格：≤2/日、雙發佈
- [feedback_member_qa_evidence_based_prediction.md](feedback_member_qa_evidence_based_prediction.md) — 預測題要做不 decline；誠實線在方法
- [feedback_content_quality_patrol_gap.md](feedback_content_quality_patrol_gap.md) — 只有老闆會發現的問題=缺巡檢
- [feedback_strategy_listing_quality.md](feedback_strategy_listing_quality.md) — 上架策略的格式規格

## Feedback — FB
- [feedback_fb_personal_account_chrome_only.md](feedback_fb_personal_account_chrome_only.md) — FB 個人帳號走 CDP-attach Chrome
- [feedback_fb_dual_publish_precheck.md](feedback_fb_dual_publish_precheck.md) — 發 FB 前查老闆是否已手動發過
- [feedback_fb_opening_no_friend_asked.md](feedback_fb_opening_no_friend_asked.md) — FB 貼文 anti-AI-style 規則
- [feedback_fb_post_idempotency_guard.md](feedback_fb_post_idempotency_guard.md) — outward-facing 動作必須有冪等 guard
- [feedback_boss_report_no_fb_handback.md](feedback_boss_report_no_fb_handback.md) — 報告禁列「還需要你做 FB」
- [feedback_fb_link_in_first_comment.md](feedback_fb_link_in_first_comment.md) — FB 正文不放連結（壓觸及），連結放第一則留言

## Feedback — 自主運營與派工
- [feedback_proactive_result_level_operation.md](feedback_proactive_result_level_operation.md) — 運營要「主動 + result-level」非「反應式 + exit-code」
- [feedback_handoff_routine_maintenance.md](feedback_handoff_routine_maintenance.md) — handoff 平常持續維護，非 compact 才寫
- [feedback_alert_is_a_task_not_a_chore.md](feedback_alert_is_a_task_not_a_chore.md) — alert 預設自動變 task + starvation lockout；只有老闆能處理的 alert = 設計失敗
- [feedback_alerts_auto_act_not_suggest.md](feedback_alerts_auto_act_not_suggest.md) — alert body 寫「已自動修復」非「建議老闆行動」
- [feedback_proactively_complete_red_alerts.md](feedback_proactively_complete_red_alerts.md) — 看到 critical 主動完成，不被動回報
- [feedback_dont_deflect_act_on_repeated_complaints.md](feedback_dont_deflect_act_on_repeated_complaints.md) — 反覆被點名的問題要實做，不 deflect
- [feedback_repeated_done_question_means_finish_now.md](feedback_repeated_done_question_means_finish_now.md) — 連問「都完成了嗎」=當回合做完
- [feedback_finish_task_before_standby.md](feedback_finish_task_before_standby.md) — 任務不得做一半待機；完成含部署+線上驗證
- [feedback_fix_verify_then_report.md](feedback_fix_verify_then_report.md) — 先修好+測過+驗證，才回報；不丟待辦給老闆
- [feedback_resume_ops_loop_after_user.md](feedback_resume_ops_loop_after_user.md) — 回完用戶要流回 ops loop
- [feedback_continuous_work_and_read_mail.md](feedback_continuous_work_and_read_mail.md) — tick 要做實事不空轉；直接讀 Gmail
- [feedback_one_dispatch_per_hour.md](feedback_one_dispatch_per_hour.md) — hourly 派 1 agent，scope ≤50min，heavy 走 queue
- [feedback_dispatch_over_diversity.md](feedback_dispatch_over_diversity.md) — 多樣性不能造成空轉
- [feedback_pool_fill_to_threshold.md](feedback_pool_fill_to_threshold.md) — pool <4 時一次補滿，非一次一個
- [feedback_refill_check_saturation_and_running_hourly.md](feedback_refill_check_saturation_and_running_hourly.md) — 補池前查 current_job；寫入走 flock
- [feedback_no_user_policy_block.md](feedback_no_user_policy_block.md) — policy task 一律自主，不當 plateau 藉口
- [feedback_dont_ask_do.md](feedback_dont_ask_do.md) — 判斷該做就直接做，不問選擇題
- [feedback_urgent_work_bypass_queue.md](feedback_urgent_work_bypass_queue.md) — 急件不進排程，當場開工
- [feedback_time_sensitive_work_is_p1.md](feedback_time_sensitive_work_is_p1.md) — 時效性研究/發文 = P1，與 user-assigned 同級
- [feedback_own_judgment_dont_credit_user.md](feedback_own_judgment_dont_credit_user.md) — 自主決策不歸因用戶、不等 ack
- [feedback_tasks_survive_session_close.md](feedback_tasks_survive_session_close.md) — backbone 須 session-independent
- [feedback_task_end_summary_format.md](feedback_task_end_summary_format.md) — 任務結束 4 項摘要格式

## Feedback — 工程紀律
- [feedback_declare_complete_requires_class_sweep.md](feedback_declare_complete_requires_class_sweep.md) — 宣告完成前對 bug class 全量掃描 + 留機械 gate
- [feedback_gates_fix_immediately_two_strikes_switch_model.md](feedback_gates_fix_immediately_two_strikes_switch_model.md) — 關卡壞了立刻徹底修；同關卡 2 次改換模型
- [feedback_fix_silent_fallback_immediately.md](feedback_fix_silent_fallback_immediately.md) — silent fallback 當場修，不丟下一班
- [feedback_audit_no_passive_terminal.md](feedback_audit_no_passive_terminal.md) — audit terminal set 不可含 awaiting_*/pending_*
- [feedback_verify_before_restructure.md](feedback_verify_before_restructure.md) — 重構前通盤查證權威來源
- [feedback_check_existing_mechanism_before_building.md](feedback_check_existing_mechanism_before_building.md) — 建新機制前先查同 concern 是否已存在但未啟用
- [feedback_test_before_deploy.md](feedback_test_before_deploy.md) — 前端改動要 build + 測所有 tab
- [feedback_hermetic_git_in_tests.md](feedback_hermetic_git_in_tests.md) — 驅動 git 的測試須隔離，否則誤操作真 repo
- [feedback_autocommit_poisons_before_after.md](feedback_autocommit_poisons_before_after.md) — `git add -A` 會捲進別人的檔，毀掉 before/after 對照
- [feedback_parallel_impl_and_worktree_liveness.md](feedback_parallel_impl_and_worktree_liveness.md) — 無 claim 致平行實作；liveness 用 lsof
- [feedback_no_cd_into_worktree_before_merge.md](feedback_no_cd_into_worktree_before_merge.md) — merge 前勿 cd 進 worktree（會誤刪）
- [feedback_worktree_stale_base_extract_by_path.md](feedback_worktree_stale_base_extract_by_path.md) — stale base 時 path-scoped 抽取，勿硬 merge
- [feedback_agent_background_codex_polling_unreliable.md](feedback_agent_background_codex_polling_unreliable.md) — background Codex + polling 易留孤兒，改 foreground
- [feedback_agent_output_extraction.md](feedback_agent_output_extraction.md) — Agent output 用 JSON parser 不用 regex
- [feedback_knowledge_index_update.md](feedback_knowledge_index_update.md) — 知識索引用 update 不用 build

## Feedback — 工具與溝通
- [feedback_codex_cli_capability.md](feedback_codex_cli_capability.md) — Codex 與 Claude Code 能力對等
- [feedback_3model_review_discipline.md](feedback_3model_review_discipline.md) — production 文章走三模 review
- [feedback_gemini_v042_skip_trust.md](feedback_gemini_v042_skip_trust.md) — Gemini headless 必加 `--skip-trust`
- [feedback_gemini_cli_share_load.md](feedback_gemini_cli_share_load.md) — 額度健康時主動分攤輕量任務
- [feedback_notebooklm_skill_install.md](feedback_notebooklm_skill_install.md) — notebooklm 安裝要跑 `skill install`
- [feedback_plain_language_boss_facing.md](feedback_plain_language_boss_facing.md) — 給老闆的描述用白話，不堆術語
- [feedback_answer_first_then_act.md](feedback_answer_first_then_act.md) — 老闆問問題先答再動手
- [feedback_final_text_after_schedulewakeup.md](feedback_final_text_after_schedulewakeup.md) — 給用戶的文字必須是 turn 最終輸出
- [feedback_email_on_major_decisions.md](feedback_email_on_major_decisions.md) — 重要決策後主動 email 通知
- [feedback_decision_email_html_form.md](feedback_decision_email_html_form.md) — 決策 email 用 mailto 連結，不用 form
- [feedback_autonomous_loop_email_summary.md](feedback_autonomous_loop_email_summary.md) — autonomous fire 結尾必寄 summary + 排下次
- [feedback_telegram_emoji_formatting.md](feedback_telegram_emoji_formatting.md) — Telegram 用 emoji 區隔段落
- [feedback_cross_machine_file_links.md](feedback_cross_machine_file_links.md) — 給用戶的檔用 SendUserFile/Tailscale，非本機路徑

## Feedback — Skills 與治理
- [feedback_self_revise_operating_docs.md](feedback_self_revise_operating_docs.md) — 運作指示文件要主動自我修訂，非事故驅動
- [feedback_skill_autonomy.md](feedback_skill_autonomy.md) — skill 可自主建立；改既有的要寄信
- [feedback_skill_structure.md](feedback_skill_structure.md) — SKILL.md 放方法論，結果放 research_program
- [feedback_skill_format.md](feedback_skill_format.md) — frontmatter 用 hyphen 非 underscore
- [feedback_claudemd_keep_inline.md](feedback_claudemd_keep_inline.md) — CLAUDE.md 不拆分，保持 inline
- [feedback_progressive_disclosure.md](feedback_progressive_disclosure.md) — 瘦身用 skill 漸進揭露
- [feedback_keep_concise_mnemonics.md](feedback_keep_concise_mnemonics.md) — 精簡時保留一句話 mnemonic
- [feedback_open_question_definition.md](feedback_open_question_definition.md) — Open Question 是大方向
- [feedback_snapshot_before_refactor.md](feedback_snapshot_before_refactor.md) — 動治理檔前先 commit snapshot
- [feedback_path_narrowing_audit.md](feedback_path_narrowing_audit.md) — 改 rules paths 前填 stage×paths 矩陣
