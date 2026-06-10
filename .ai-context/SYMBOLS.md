cram/add_context.py: add_files, main
cram/audit.py: run_audit, main
cram/benchmark.py: run_benchmark, main
cram/cli.py: main
cram/context_dir.py: canonical_context_dir, legacy_context_dir, resolve_context_dir, has_context_dir, context_path, context_basename
cram/cost_model.py: CostInputs, orientation_tokens, budget_status, daily_costs
cram/decide.py: append_decision, main
cram/decisions.py: show_decisions, mine_decisions, main
cram/doctor.py: main
cram/find_context.py: find_relevant_files, populate_current_task, find_context, main
cram/gotcha.py: append_gotcha, main
cram/health.py: context_health
cram/hooks.py: install_global_claude_md, uninstall_global_claude_md, install_commit_msg_hook, install_hook, install_checkout_hook, main, install_claude_code_hooks, uninstall_hook
cram/init.py: scan_structure, generate_architecture_md, write_gitignore, write_ci_action, init_repo, main
cram/mcp_server.py: get_context, get_architecture, get_symbols, get_decisions, propose_decision, get_gotchas, get_health, add_file, run_benchmark, get_task_history, main
cram/session.py: save_session, set_last_slot, get_last_slot, archive_task, load_session, touch_session, session_age, session_within_grace, clear_session
cram/status.py: staleness_score, staleness_band, get_status_dict, show_status, main
cram/suggest.py: suggest_task
cram/symbols.py: extract_symbols, write_symbols_md
cram/sync_context.py: get_git_diff, update_architecture_md, reset_task, sync, main
cram/targets.py: load_custom_targets, get_effective_targets, get_effective_indicators, load_output_config, load_default_target, save_default_target, detect_targets, write_to_target, write_to_all_detected
cram/ui.py: main
cram/usage.py: measured_usage
cram/utils.py: load_settings, save_settings, discover_models, pick_context_model, pick_coding_model, cache_min_tokens, get_model_recommendations, call_context_model, call_model, find_git_root, strip_code_fence
scripts/generate_icns.py: main
tests/test_audit.py: TestAnalyzeTranscript, TestFindAllToolUse, TestAuditConstants
tests/test_context_dir.py: test_prefers_canonical_context_dir, test_falls_back_to_legacy_context_dir, test_context_path_uses_resolved_dir
tests/test_cost_model.py: test_orientation_caps_at_repo_tokens, test_orientation_zero_files, test_daily_saving_never_negative, test_nocram_scales_linearly_with_orient_files, test_daily_costs_returns_expected_keys, test_import_works, TestBudgetStatus
tests/test_decisions.py: repo, TestFilterCommits, TestParseModelOutput, TestAppendWithReason, TestShowDecisions, TestMineDecisions
tests/test_find_context.py: TestCleanPath, TestReadTruncated, TestFindRelevantFiles, TestPopulateCurrentTask, TestScoreFiles, TestContractFields, TestFindContext, TestChdirFreeExtraction, TestResolvePathDisambiguation
tests/test_hooks.py: TestInstallCommitMsgHook, TestInstallHookInstallsBoth, TestCommitMsgPatternDetection
tests/test_init.py: TestIsExcludedFile, TestScanStructure, TestWriteGitignore, TestInitRepo
tests/test_mcp_server.py: repo, TestGetArchitectureDeterminism, TestGetDecisionsDeterminism, TestGetSymbolsDeterminism, TestGetContextDeterminism, TestGetHealthDeterminism, TestTaskSlotNamespacing, TestUsageLog, TestProposeDecision, TestSlotCoherence, TestArchiveTask, TestInitGuard
tests/test_status.py: TestStalenessScore, TestStalenessBand, TestGetStatusDictBackCompat, git_repo, TestGetStatusDictIntegration
tests/test_symbols.py: TestByteStability
tests/test_sync.py: TestGetGitDiff, TestUpdateArchitectureMd, TestSync
tests/test_targets.py: TestSaveLoadDefaultTarget, TestDetectTargets, TestWriteToTarget, TestCustomTargets
tests/test_ui_smoke.py: empty_repo, TestUiSmoke
tests/test_usage.py: test_missing_dir_returns_none, test_sums_match_fixture, test_malformed_lines_skipped, test_old_files_excluded
tests/test_utils.py: TestStripCodeFence, TestCallModelRouting, TestCallViaLitellmMissing, TestProxyHeaders