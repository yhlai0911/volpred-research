#!/bin/bash

# Auto-injected: TCC bypass — bash has FDA (System Settings), self-redirect to Desktop log avoids launchd-process-level TCC denial
exec >> /Users/yhlai0911/volpred-research/storage/logs/cron/feed_sync.log 2>&1
# Canonical source for the host-cron wrapper.
# IMPORTANT: host cron does NOT exec this file — macOS TCC (FDA) blocks the
# cron daemon from exec'ing .sh files under Desktop/. The cron-exec target
# lives at ~/.volpred/bin/cron_feed_sync.sh. After editing this file, sync
# After editing: uv run python scripts/sync_cron_wrappers.py --render-manifest
# After commit/merge on main: uv run python scripts/sync_cron_wrappers.py --apply
#
# WS-C2 (refactor_plan_ops_master_2026_07 §3): hourly full reconcile of
# feed.json (canonical) -> Supabase articles (projection). This is the SAFETY
# NET, not the primary path: every publish/edit path is supposed to push to
# Supabase inline (WS-C1 收斂寫入端). Any path that writes feed.json without
# pushing — a manual edit, a batch content rewrite, a crashed publisher —
# leaves the projection stale until this job converges it.
#
# Safe upserts follow the publisher.article.supabase.reconcile family owner.
# The operations_core owner binds the canonical feed SHA and complete sorted
# article objects into one immutable batch, then executes it through the
# durable payload store, WorkItem, EffectRequest/outbox, primary lease, and
# typed read-back acknowledgement. Legacy ownership remains an exact rollback
# path and uses the existing per-article caller.
#
# Deliberately NOT --allow-delete: a slug missing from feed is a destructive
# signal that belongs to the single guarded delete owner
# (supabase_sync.reconcile_article_deletes with its floor/cap/dump
# invariants), never to an unattended hourly job.
#
# --quiet-when-clean: no drift => no output. An hourly job that logs a banner
# every run trains operators to ignore its log; the cron_lib start/exit
# markers below remain as the execution receipt for liveness monitoring.
cd /Users/yhlai0911/volpred-research || exit 1
source scripts/cron_lib.sh
_start=$SECONDS
cron_emit_start "feed_sync"
/opt/homebrew/bin/uv run volpred ops feed-sync --apply --no-delete --quiet-when-clean
_ec=$?
cron_emit_exit "feed_sync" "$_ec" "$_start"
exit "$_ec"
