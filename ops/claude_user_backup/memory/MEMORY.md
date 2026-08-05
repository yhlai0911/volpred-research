# Memory Index

## User & References
- [user_profile.md](user_profile.md) — 賴奕豪，大葉財金副教授；copula-GARCH/hedging/高頻
- [reference_taifex_data.md](reference_taifex_data.md) — TAIFEX 數據位置/格式/夜盤時間
- [reference_lai_prs_paper.md](reference_lai_prs_paper.md) — PRS 論文 metadata + 延伸方向
- 模型與 CLI 環境：[cache TTL 依 tier](reference_anthropic_cache_ttl.md)｜[advisor=fable 撞 CC #76199](reference_advisor_fable_bug.md)｜[Codex/Gemini 認證可用性](reference_dual_cli_availability.md)｜[agy CLI 取代 gemini-cli](reference_antigravity_cli.md)
- [reference_notebooklm_rag_workflow.md](reference_notebooklm_rag_workflow.md) — 外部文獻 RAG 走 NotebookLM 的觸發時機
- [reference_shell_utf8_locale_required.md](reference_shell_utf8_locale_required.md) — 非互動 shell 要 export LANG/LC_ALL，否則中文 argv 壞掉
- [reference_bsd_tr_multibyte_utf8.md](reference_bsd_tr_multibyte_utf8.md) — macOS BSD tr 拆散多位元組字元成亂碼，別誤判成字型缺字
- [reference_publisher_strict_audit_tag_rules.md](reference_publisher_strict_audit_tag_rules.md) — K-id 自動移到 metadata；tag ≤8 禁統計術語
- 派工與算力：[SUPERSEDED — 派工改 dispatch-supervisor daemon](reference_hourly_dispatch_via_os_cron.md)｜[heavy compute 進 queue，~75% token 節省](reference_compute_queue_token_split.md)｜[worktree 內 enqueue worker 看不到](reference_enqueue_from_worktree_is_invisible.md)
- [reference_knowledge_wiki_and_context_economy.md](reference_knowledge_wiki_and_context_economy.md) — 編譯式知識庫 + context 經濟
- [reference_strategy_card_metrics_window.md](reference_strategy_card_metrics_window.md) — 策略卡 metrics 窗口；低 MDD 是設計非 bug
- [reference_nested_forecast_inference_gap.md](reference_nested_forecast_inference_gap.md) — nested + pinball + expanding 無可用推論法；CW 不可用於 pinball
- [reference_zeabur_deploy_target.md](reference_zeabur_deploy_target.md) — 部署走 deploy-zeabur-safe.sh 到 volpred-v3
- [reference_trending_blog_sources.md](reference_trending_blog_sources.md) — trending 掃描來源清單 + high-viral 類型
- [reference_unified_memory_one_brain.md](reference_unified_memory_one_brain.md) — Telegram 與本機共用同一記憶，勿建 channel 專屬
- [reference_work_dashboard.md](reference_work_dashboard.md) — 監控 dashboard http://127.0.0.1:8787
- [reference_global_session_lock_hook.md](reference_global_session_lock_hook.md) — 全域主 checkout 互斥鎖已上線；volpred 在 optout，勿重建同類 gate
- repo 操作陷阱：[frontend-v2-fix 是巢狀 repo](reference_frontend_nested_git_repo.md)｜[worktree 內用 uv run --extra dev](reference_worktree_pytest_wrong_interpreter.md)
- Chrome/FB 環境：[發文自選 Chrome，中文用 pbcopy](reference_fb_chrome_browser_autoselect.md)｜[deviceId 身分對照，禁用裸 id 問老闆](reference_chrome_browser_identity_map.md)

## Projects
- 平台北極星：[終極目標=盈利，5-mission 是手段](project_platform_profitability_goal.md)｜[全自動不間斷自我運營的完整願景](project_platform_vision_full.md)
- 系列規格：[迷思實驗室｜](project_myth_lab_series.md)｜[事件溫度計｜](project_event_thermometer_series.md)
- [project_repo_moved_out_of_desktop.md](project_repo_moved_out_of_desktop.md) — repo 已搬 ~/volpred-research，單一 canonical
- [project_loop_engineering_layer.md](project_loop_engineering_layer.md) — loop-health + dreaming 閉環
- [project_refactor_safety_net.md](project_refactor_safety_net.md) — 大改的回滾 tag/worktree
- [project_prg_paper_framing.md](project_prg_paper_framing.md) — PRG 論文定位
- [project_supabase_paid.md](project_supabase_paid.md) — Supabase 已付費
- [project_domain_migration.md](project_domain_migration.md) — 換網域的 SEO 遷移步驟
- 論文組合：[A/B/C/D tier 分級](project_paper_portfolio_decisions_2026_04_27.md)｜[M3 瓶頸=revision 收斂非投稿決策](project_papers_awaiting_submit_decision.md)
- [project_codex_audit_20260710_disposition.md](project_codex_audit_20260710_disposition.md) — Codex 稽核裁決：做什麼、不做什麼
- [project_fb_page_operation.md](project_fb_page_operation.md) — VolPred 粉專由 AI 全權經營
- [project_reader_preference_feedback_loop.md](project_reader_preference_feedback_loop.md) — 讀者偏好自動分析=常態運營輸入（選題/圖文表）
- [project_prepublish_content_gate.md](project_prepublish_content_gate.md) — 發佈前 content-vs-source gate
- [project_strategy_lifecycle_standing_directive.md](project_strategy_lifecycle_standing_directive.md) — 策略持續增減走既有 gate
- [project_cloud_agent_git_divergence.md](project_cloud_agent_git_divergence.md) — 雲端 agent 與本機 git 分岔史
- [project_canonical_write_test_leak_gate.md](project_canonical_write_test_leak_gate.md) — 「測試寫 canonical storage」的 class gate
- [project_test_spawn_leak_sandbox_escape.md](project_test_spawn_leak_sandbox_escape.md) — 測試會 spawn 真 opus session；tree-clean gate 對 out-of-process 副作用失明

## Feedback — 研究與論文
- [feedback_research_rigor.md](feedback_research_rigor.md) — 樣本 ≥500、跨 3 期間驗證
- [feedback_hedging_vs_trading.md](feedback_hedging_vs_trading.md) — 避險用 HE/VaR/Utility，不比 Sharpe
- 交易時點假設：[收盤價可交易](feedback_session_close_assumption.md)｜[open 用已 realized overnight 是合法 timing](feedback_session_boundary_forecast_timing.md)
- [feedback_long_sample_period.md](feedback_long_sample_period.md) — OOS 必含至少一次空頭
- [feedback_agent_markdown_not_tex.md](feedback_agent_markdown_not_tex.md) — Agent 寫 .md 不寫 .tex
- 論文審查：[READY ≠ 可投稿，必多輪收斂](feedback_paper_multi_round_review.md)｜[必加 cross-paper meta-eval](feedback_paper_cross_paper_meta_eval.md)｜[方法/期刊/時機自主判斷](feedback_paper_autonomy_optimize_acceptance.md)
- [feedback_3spec_disambiguation.md](feedback_3spec_disambiguation.md) — 同 symbol 多 spec 的 footnote 消歧
- 選題來源：[從頂尖期刊挖不手寫](feedback_journal_topic_discovery.md)｜[台/日/印度/東南亞 quota，美股不可壟斷](feedback_market_diversification_asia.md)｜[喚醒=主動生議題](feedback_proactive_research_posture.md)
- [feedback_strategy_dev_over_audit.md](feedback_strategy_dev_over_audit.md) — 重開發新策略 > audit 舊策略
- [feedback_execute_means_implement_plan.md](feedback_execute_means_implement_plan.md) — 「開始執行」=實作計劃，非跑既有任務

## Feedback — 內容與發佈
- [feedback_website_article_quality_4dim.md](feedback_website_article_quality_4dim.md) — 文章 4 維度（深度/可讀/資訊/參考）
- 寫作前置：[reader-facing 必走 anti-ai-style](feedback_use_anti_ai_style.md)｜[必讀 3 canonical + evidence 先於 prose](feedback_reader_facing_3canon.md)
- 查重：[派 agent 前主線程做 3-layer 查重](feedback_dedup_3_layers_mainthread.md)｜[同邏輯 arc 換外殼也算重複](feedback_narrative_arc_dedup.md)｜[鬼打牆根因在釋出端非研究端](feedback_recycling_is_release_layer_not_research.md)
- [feedback_digest_theme_first_whole_archive.md](feedback_digest_theme_first_whole_archive.md) — 導讀先訂主題→撈整庫，非本週 recap
- [feedback_report_content_sync.md](feedback_report_content_sync.md) — feed.json 與 reports/{id}.json 必同步
- 圖：[文末附懶人包圖組](feedback_lazypack_infographic.md)｜[走 Codex primary path，NotebookLM 放後面](feedback_notebooklm_deprioritized_codex_figures.md)
- [feedback_trending_repost_route.md](feedback_trending_repost_route.md) — trending_repost 規格：≤2/日、雙發佈
- [feedback_member_qa_evidence_based_prediction.md](feedback_member_qa_evidence_based_prediction.md) — 預測題要做不 decline；誠實線在方法
- [feedback_content_quality_patrol_gap.md](feedback_content_quality_patrol_gap.md) — 只有老闆會發現的問題=缺巡檢
- [feedback_strategy_listing_quality.md](feedback_strategy_listing_quality.md) — 上架策略的格式規格

## Feedback — FB
- 發文前：[個人帳號走 CDP-attach Chrome](feedback_fb_personal_account_chrome_only.md)｜[先查老闆是否已手動發過](feedback_fb_dual_publish_precheck.md)｜[outward-facing 必須有冪等 guard](feedback_fb_post_idempotency_guard.md)
- 貼文本體：[anti-AI-style 開場規則](feedback_fb_opening_no_friend_asked.md)｜[正文不放連結，連結放第一則留言](feedback_fb_link_in_first_comment.md)
- [feedback_boss_report_no_fb_handback.md](feedback_boss_report_no_fb_handback.md) — 報告禁列「還需要你做 FB」

## Feedback — 自主運營與派工
- [feedback_proactive_result_level_operation.md](feedback_proactive_result_level_operation.md) — 運營要「主動 + result-level」非「反應式 + exit-code」
- [feedback_main_thread_executes_complex_work.md](feedback_main_thread_executes_complex_work.md) — 主線直接做複雜任務，「很大」不是派工理由
- [feedback_handoff_routine_maintenance.md](feedback_handoff_routine_maintenance.md) — handoff 平常持續維護，非 compact 才寫
- alert 處理：[預設自動變 task + starvation lockout](feedback_alert_is_a_task_not_a_chore.md)｜[body 寫「已自動修復」非「建議行動」](feedback_alerts_auto_act_not_suggest.md)｜[看到 critical 主動完成](feedback_proactively_complete_red_alerts.md)｜[重複開單根因=alert→task 無狀態，反覆修不好要重架](feedback_incident_not_alert_task_mapping.md)
- [feedback_dont_deflect_act_on_repeated_complaints.md](feedback_dont_deflect_act_on_repeated_complaints.md) — 反覆被點名的問題要實做，不 deflect
- [feedback_repeated_done_question_means_finish_now.md](feedback_repeated_done_question_means_finish_now.md) — 連問「都完成了嗎」=當回合做完
- [feedback_finish_task_before_standby.md](feedback_finish_task_before_standby.md) — 任務不得做一半待機；完成含部署+線上驗證
- [feedback_fix_verify_then_report.md](feedback_fix_verify_then_report.md) — 先修好+測過+驗證，才回報；不丟待辦給老闆（硬規則）
- [feedback_resume_ops_loop_after_user.md](feedback_resume_ops_loop_after_user.md) — 回完用戶要流回 ops loop
- [feedback_continuous_work_and_read_mail.md](feedback_continuous_work_and_read_mail.md) — tick 要做實事不空轉；直接讀 Gmail
- 派工節奏：[一班 batch-drain 多任務到預算用盡](feedback_batch_tasks_per_fire.md)｜[hourly 派 1 agent、scope ≤50min](feedback_one_dispatch_per_hour.md)｜[多樣性不能造成空轉](feedback_dispatch_over_diversity.md)｜[pool <4 一次補滿](feedback_pool_fill_to_threshold.md)｜[補池前查 current_job、寫入走 flock](feedback_refill_check_saturation_and_running_hourly.md)
- 自主界線：[policy task 一律自主](feedback_no_user_policy_block.md)｜[該做就直接做不問選擇題](feedback_dont_ask_do.md)｜[自主決策不歸因用戶、不等 ack](feedback_own_judgment_dont_credit_user.md)
- [feedback_urgent_work_bypass_queue.md](feedback_urgent_work_bypass_queue.md) — 急件不進排程，當場開工
- [feedback_urgent_bypasses_scheduler_by_design.md](feedback_urgent_bypasses_scheduler_by_design.md) — 架構硬指令：急件直達派工；request_fire 已存在但 Telegram 沒接線
- responder：[不能改 repo ≠ 可把 P1 變排隊](feedback_responder_cannot_be_a_queue_excuse.md)｜[先 telegram 回覆再 complete](feedback_responder_reply_before_complete.md)
- [feedback_time_sensitive_work_is_p1.md](feedback_time_sensitive_work_is_p1.md) — 時效性研究/發文 = P1，與 user-assigned 同級
- [feedback_tasks_survive_session_close.md](feedback_tasks_survive_session_close.md) — backbone 須 session-independent
- [feedback_task_end_summary_format.md](feedback_task_end_summary_format.md) — 任務結束 4 項摘要格式
- [feedback_refactor_independent_execution.md](feedback_refactor_independent_execution.md) — 重構走獨立軌（main_thread lane），不進一般派工
- [feedback_gates_smooth_no_deadlock.md](feedback_gates_smooth_no_deadlock.md) — gate 要流暢有出口，block 必附修復/寬限/裁決三選一，禁死局
- [feedback_verify_org_brief_against_canonical.md](feedback_verify_org_brief_against_canonical.md) — 經理 brief 的組織態可能整段是假的，開班先對帳 org_status.py

## Feedback — 工程紀律
- [feedback_five_step_closure_gate.md](feedback_five_step_closure_gate.md) — 結案五步鐵律；contained vs root_cause_fixed_and_verified 二態
- [feedback_declare_complete_requires_class_sweep.md](feedback_declare_complete_requires_class_sweep.md) — 宣告完成前對 bug class 全量掃描 + 留機械 gate
- [feedback_render_gate_static_prose_blindspot.md](feedback_render_gate_static_prose_blindspot.md) — render --check 會替寫死的假斷言背書，靜態句子要另外驗
- 壞掉就當場修：[關卡壞了立刻徹底修，同關卡 2 次換模型](feedback_gates_fix_immediately_two_strikes_switch_model.md)｜[silent fallback 不丟下一班](feedback_fix_silent_fallback_immediately.md)
- [feedback_refactor_over_patch_no_legacy.md](feedback_refactor_over_patch_no_legacy.md) — 重構優先於修補，不留遺留死碼；別把補丁說成治本
- [feedback_audit_no_passive_terminal.md](feedback_audit_no_passive_terminal.md) — audit terminal set 不可含 awaiting_*/pending_*
- 動手前先查：[重構前通盤查證權威來源](feedback_verify_before_restructure.md)｜[建新機制前查同 concern 是否已存在](feedback_check_existing_mechanism_before_building.md)
- [feedback_graphify_query_before_grep.md](feedback_graphify_query_before_grep.md) — 架構/caller/影響面先走 graphify query 再 grep；整合已由 Codex 建好勿重裝
- 前端：[改動要 build + 測所有 tab](feedback_test_before_deploy.md)｜[原版=數據 v3=呈現，不能脫鉤](feedback_v3_presentation_layer_only.md)｜[讀者頁瀏覽數等展示指標只能有唯一版本](feedback_single_source_displayed_metrics.md)
- git 紀律：[驅動 git 的測試須隔離](feedback_hermetic_git_in_tests.md)｜[git add -A 毀掉 before/after 對照](feedback_autocommit_poisons_before_after.md)
- worktree：[無 claim 致平行實作、liveness 用 lsof](feedback_parallel_impl_and_worktree_liveness.md)｜[merge 前勿 cd 進去](feedback_no_cd_into_worktree_before_merge.md)｜[stale base 走 path-scoped 抽取](feedback_worktree_stale_base_extract_by_path.md)｜[審查產物別寫進被審的樹，會撞自己的 clean-tree gate](feedback_review_artifacts_outside_worktree.md)
- [feedback_no_research_artifact_loss.md](feedback_no_research_artifact_loss.md) — 已完成研究產物一件都不能漏，復現靠它
- agent 操作：[background Codex + polling 易留孤兒，改 foreground](feedback_agent_background_codex_polling_unreliable.md)｜[output 用 JSON parser 不用 regex](feedback_agent_output_extraction.md)
- [feedback_knowledge_index_update.md](feedback_knowledge_index_update.md) — 知識索引用 update 不用 build

## Feedback — 工具與溝通
- 模型分工：[Codex 與 Claude Code 能力對等](feedback_codex_cli_capability.md)｜[production 文章走三模 review](feedback_3model_review_discipline.md)
- Gemini：[禁付費 API，headless 走免費 agy（硬指令）](feedback_no_paid_gemini_use_agy.md)｜[headless 必加 --skip-trust](feedback_gemini_v042_skip_trust.md)｜[額度健康時主動分攤輕量任務](feedback_gemini_cli_share_load.md)
- [feedback_notebooklm_skill_install.md](feedback_notebooklm_skill_install.md) — notebooklm 安裝要跑 `skill install`
- 對老闆說話：[用白話不堆術語](feedback_plain_language_boss_facing.md)｜[問問題先答再動手](feedback_answer_first_then_act.md)｜[給用戶的文字必須是 turn 最終輸出](feedback_final_text_after_schedulewakeup.md)
- email：[重要決策後主動通知](feedback_email_on_major_decisions.md)｜[用 mailto 連結不用 form](feedback_decision_email_html_form.md)｜[autonomous fire 結尾必寄 summary + 排下次](feedback_autonomous_loop_email_summary.md)
- 回報格式：[Telegram 用 emoji 區隔段落](feedback_telegram_emoji_formatting.md)｜[程序回報用結構化模板非散文](feedback_structured_stage_report_format.md)｜[給用戶的檔用 SendUserFile/Tailscale](feedback_cross_machine_file_links.md)

## Feedback — Skills 與治理
- [feedback_self_revise_operating_docs.md](feedback_self_revise_operating_docs.md) — 運作指示文件要主動自我修訂，非事故驅動
- skill 規格：[可自主建立，改既有的要寄信](feedback_skill_autonomy.md)｜[SKILL.md 放方法論，結果放 research_program](feedback_skill_structure.md)｜[frontmatter 用 hyphen](feedback_skill_format.md)
- 瘦身：[CLAUDE.md 不拆分保持 inline](feedback_claudemd_keep_inline.md)｜[用 skill 漸進揭露](feedback_progressive_disclosure.md)｜[保留一句話 mnemonic](feedback_keep_concise_mnemonics.md)
- [feedback_open_question_definition.md](feedback_open_question_definition.md) — Open Question 是大方向
- 治理檔改動：[先 commit snapshot](feedback_snapshot_before_refactor.md)｜[改 rules paths 前填 stage×paths 矩陣](feedback_path_narrowing_audit.md)
