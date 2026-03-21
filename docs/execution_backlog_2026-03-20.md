# Execution Backlog

Last updated: 2026-03-20

This file records the current cross-project execution backlog after the `frontend-v2` stabilization and admin/control-plane work. It is intended as an implementation backlog, not a replacement for `CLAUDE.md`, `research_program.md`, or skills.

## Completed Foundation

- `frontend-v2-fix` worktree created as the safe implementation branch.
- Build/runtime baseline aligned to Node 22 and Next 15.
- Feed/report/query path refactors shipped with remote Supabase migration applied.
- Strategy overview cache, risk forecast rendering split, and shared strategy performance logic shipped.
- Admin auth, admin bootstrap email, and initial admin surfaces shipped:
  - `/admin`
  - `/admin/ops`
  - `/admin/users`
  - `/admin/content`
  - `/admin/strategies`
  - `/admin/questions`
  - `/admin/analytics`
- Agent-first platform surfaces shipped:
  - admin jobs
  - audit
  - remote refresh actions
  - CLI ops entrypoints
- Reader interaction v1 shipped:
  - article impression
  - like
  - bookmark
  - share
- Lightweight member surfaces shipped:
  - `/me`
  - `/me/bookmarks`
  - `/me/questions`

## Active Tracks

### 1. Admin Platform

Goal: turn the current admin pages into a real platform operations layer for human + Claude use.

In progress:
- `/admin/content` from simple job launcher into editorial workflow surface
- `/admin/questions` from monitoring list into question operations console
- `/admin/analytics` from summary into real trend/research-feedback console

Next:
- expose article status, sync state, and recent workflow events
- add richer content filters, status chips, and action shortcuts

Recently shipped:
- `/admin/content` now reads from `/api/admin/content` rather than public feed
- content cards now show recent per-article workflow events when jobs can be matched
- content status filters now support all observed statuses, not only published/unpublished
- portfolio page now uses `/api/portfolio-overview` and lazy chart/trade-log rendering

### 2. Reader & Member Layer

Goal: move from “data exists” to actual member-facing product utility.

In progress:
- lightweight member home
- bookmarks and member question history

Next:
- add “my interactions” summary
- add quota / membership summary
- improve member question lifecycle visibility

### 3. Reader Analytics

Goal: make site behavior visible enough to feed research/editorial direction.

In progress:
- impressions, reactions, basic top articles
- 14-day reading trend
- 14-day question trend
- reaction mix

Next:
- better tag/topic hotness model
- member vs anonymous behavior by period
- question-to-article conversion views
- trend summaries readable by Claude

## P0 Next Implementation

### Content Workflow

- ship `/api/admin/content`
- show recent articles with:
  - status
  - audience
  - tags
  - publish date
  - basic interaction stats
- add status filters:
  - published
  - unpublished
  - all
- add editorial shortcuts:
  - load into unpublish
  - load into cleanup
  - open report

### Question Workflow

- make ranked user questions easier to scan
- show score breakdown and rank movement where data exists
- show recent answered member questions separately
- expose linked article coverage and answer coverage

### Analytics Quality

- improve top tag scoring
- add fallback paths when materialized stats are stale
- keep Claude-facing summary API stable

## P1 After That

### Question Ranking Formalization

- formalize 6-hour member question reprioritization as a platform-visible workflow
- expose:
  - score
  - previous rank
  - score breakdown
  - last ranking time
- make it observable in admin, not just implied by session cron + docs

### Content Publishing Flow

- article draft vs published workflow
- sync status visibility
- safer cleanup / unpublish trail
- article-level operation history

### Member Experience

- my interactions
- question quota summary
- more useful bookmark surface

## P2 Strategic Follow-Up

### Claude-Facing Platform Feedback

- keep `/api/admin/analytics/summary` stable
- add compact recommendation fields for:
  - what readers currently prefer
  - which topics are heating up
  - which member questions deserve priority

### End-to-End Verification

- run full loop:
  - research
  - publish
  - sync
  - front-end display
  - reader interaction
  - analytics reflection
  - cleanup / rollback

### Skills / Governance Alignment

Only after user approval for modifying existing guidance files:
- adjust `feed-publisher`
- adjust `member-questions`
- adjust `autonomous-research`
- add or expand admin/platform operation guidance

## Blockers / Caveats

- Current member center is still lightweight, not a full membership product.
- Analytics is now useful, but still young; some derived metrics are based on limited real data.
- Claude-facing platform guidance should eventually be aligned with the new website/admin surfaces, but existing governance files should only be changed with explicit user approval if modifying existing content.
