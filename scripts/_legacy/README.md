# scripts/_legacy ï¿½€” å·²ï¿½€€å½¹ï¿½š„ï¿½€æ¬¡ï¿½€ï¿½/ï¿½­ï¿½ï¿½ï¿½ï¿½…ï¿½ï¿½œï¿½

ï¿½€™è£¡ï¿½”ï¿½**ç¢ºï¿½ï¿½„ï¿½ live ï¿½•ï¿½”ï¿½**ï¿½š„ï¿½­ï¿½ï¿½ï¿½ï¿½…ï¿½ï¿½œï¿½ï¿½ˆ2026-07-01 ï¿½–Šï¿½Šï¿½ï¿½ï¿½‹ç¨½æ ¸ + ä¸»ï¿½šï¿½‹ï¿½—ï¿½­‰ç§»ï¿½…ï¿½ï¿½‰ï¿½€‚
ï¿½ï¿½•™ï¿½€Œï¿½ï¿½ˆï¿½ï¿½™ï¿½ï¿½˜ï¿½ï¿½‚ï¿½ï¿½† provenance / ï¿½ï¿½è¿½æº¯ï¿½›ï¿½ï¿½‡‰è¢«ä»»ï¿½• cron / config / skill / pipeline ï¿½•ï¿½”ï¿½ï¿½€‚
canonical ï¿½–‡ç« ï¿½Šï¿½ï¿½è·¯ï¿½‘ï¿½˜ï¿½ `scripts/publish_draft.py`ï¿½ˆ+ feed-publisher skillï¿½‰ï¿½€‚

## 2026-07-20 WS-A1bï¼ˆrefactor_plan_ops_master_2026_07 Â§WS-Aï¼‰retirements

`docs/audit_next_tasks_writers.md`ï¼ˆA1a ç›¤é»ï¼‰åˆ¤å®š deleteã€è¤‡æ ¸é›¶å¼•ç”¨å¾Œç§»å…¥ï¼š

- `decompose_drone_series.py` â€” drone ç³»åˆ—ä¸€æ¬¡æ€§æ‹†è§£è…³æœ¬ï¼ˆå°æ‡‰ Â§1.2 P6 / WS-E E1 çš„
  `drone_ep*` æ­»ç¢¼ç¾¤ï¼‰ï¼›å¸¶ä¸€æ¢ç„¡ helper çš„ `next_tasks.json` æ‰‹æŠ„ serialize å¯«å…¥è·¯å¾‘ã€‚
- `graphify_codeonly_pilot.py` â€” graphify pilot ä¸€æ¬¡æ€§å¯¦é©—ï¼›`_ensure_followup_task`
  å¸¶ truncate-then-json.dump å¯«å…¥è·¯å¾‘ã€‚
- `backfill_task_types.py` â€” task_type ä¸€æ¬¡æ€§ backfillï¼ˆå·²åŸ·è¡Œå®Œç•¢ï¼‰ï¼›å”¯ä¸€å¼•ç”¨æ˜¯
  `tests/test_canonical_write_guard.py` çš„ ratchet æ¸…å–®ï¼ˆåŒ commit ç§»é™¤ï¼‰ã€‚

ä¸‰è€…çš„ `LOW_LEVEL_OWNERS` æ¢ç›®å·²è‡ª `scripts/audit_canonical_writers.py` ç§»é™¤ï¼›
`next_tasks.json` å¯«å…¥è‡ªæ­¤ç”± helper-routing gateï¼ˆåŒ audit çš„
`NEXT-TASKS-ROUTING` æª¢æŸ¥ï¼‰æ©Ÿæ¢°å°é–ï¼Œ`_legacy/` ç›®éŒ„ä¸åœ¨æƒæç¯„åœã€‚
