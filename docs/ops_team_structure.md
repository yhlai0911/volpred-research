# Ops Team Structure — VolPred Autonomous Operating Doc

**Author**: Main thread Claude (acting as platform ops manager)
**Status**: Living doc — updated each cycle as I learn / break / build
**First written**: 2026-05-19
**Authorization**: User delegated full autonomy 2026-05-19; receives reports only
**Accountability target**: Platform profitability (CLAUDE.md ultimate goal)

---

## How I operate

Every cycle starts with `scripts/ops_dashboard.py`. Read first, triage, act.
- `overall_status=ok` → dispatch from pool / start research
- `overall_status=warn` → fix the warned section first, then dispatch
- `overall_status=critical` → all-hands on critical section before any new work

Main thread role = **synthesis + decision**, not execution. Execution = agents (specialised by skill).

---

## Roles (existing skills mapped)

### Production Team
| Role | Skill | Responsibility |
|---|---|---|
| Topic selector | `publication-candidates` | Pick uncovered K / event |
| Research writer | `autonomous-research` | Run K experiment, write article |
| Daily writer | `feed-publisher` | Audience-general daily article |
| Trending writer | `trending-repost` | Hot topic re-write, cap 2/day |
| Member-Q&A handler | `member-questions` | 6h cron, top-ranked Q |
| Style editor | `anti-ai-style` | Mandatory pass before publish |

### Research Team
| Role | Skill | Responsibility |
|---|---|---|
| Experimenter | `autonomous-research` | GARCH/HAR/VT runs |
| Data fetcher | `external-data-sources` | yfinance / FRED / TAIFEX |
| Result verifier | `agent-result-verification` | Auto-check agent claims vs JSON |
| Codex review | `codex:review` / `codex:adversarial-review` | Code review of experiments |
| Worktree verifier | `worktree-merge-verification` | Post-merge file presence |

### Paper Team
| Role | Skill | Responsibility |
|---|---|---|
| Quality gate | `finance-paper-quality` | Claim-evidence match, Harvey rigor |
| Latex reviewer | `latex-academic-reviewer` | Structure + math + symbols |
| Citation auditor | `citation-verifier` | APA + DOI + quoted-content match |
| Cycle coordinator | `paper-review-cycle` | Parallel reviewers → history archive |
| Stage classifier | `paper-stage-classifier` | early/draft/review/ready/submitted |
| Revisor | `paper-update` | body.tex revision SOP |
| Peer reviewer | `academic-finance-reviewer` | Final pre-submission audit |
| External RAG | `notebooklm` | Cross-paper meta + lit review |
| Paper sourcing | `sci-hub` | DOI fetch when WebFetch fails |

### Ops Audit Team (standing, cron-triggered)
| Role | Script | Cadence | What it catches |
|---|---|---|---|
| Dashboard | `scripts/ops_dashboard.py` | hourly (read by main thread) | 7-section health snapshot |
| Publish-sync auditor | `scripts/audit_publish_sync.py` | hourly | local vs supabase vs live URL mismatch |
| FB pipeline auditor | `scripts/audit_fb_pipeline.py` | 6h | stale fb_post_status >24h |
| Cron health auditor | (in dashboard now) | hourly | jobs over max-age |
| Memory health | `memory-health` skill | weekly | knowledge.json bloat, dup, schema |
| Strategy lifecycle | `admin-ops` skill | weekly | MDD breach, sparkline gaps |
| K1259 provenance | `scripts/validate_knowledge_provenance.py` | weekly | knowledge entry provenance |

### Coordination (main thread)
- Dashboard read every cycle start
- Triage by Mission impact (Mission 1-5 priority)
- Dispatch parallel agents on bounded scope
- Maintain this doc as living artifact

---

## Mission KPIs (what defines success — to make platform profitable)

| Mission | KPI | Target | Current source |
|---|---|---|---|
| 1. 把文章寫好 | articles/day published | ≥6/day | feed.json published_at last 24h |
| 1. 把文章寫好 | retention proxy: clicks per article | TBD (need analytics) | needs build |
| 2. 把實驗做好 | experiments/week with verdict | ≥5/week | knowledge.json verdict count |
| 2. 把實驗做好 | NULL ratio honest | ~30-40% | reality check, no overclaim |
| 3. 把論文寫好 | papers in `ready_for_submission` | ≥2 alive | paper-stage-classifier |
| 4. 平台運營 | cron health | 0 stale | ops_dashboard health_cron |
| 4. 平台運營 | sync parity | 100% within 1h | audit_publish_sync |
| 5. 曝光流量 | FB Ivan Lai posts/day | ≥1 (when trending available) | trending_repost_log |
| 5. 曝光流量 | reader analytics | TBD | needs build |

**Gaps**:
- No analytics ingestion yet (reader retention / CTR) → blind on Mission 1 & 5 effectiveness
- No conversion funnel tracking (visitor → member → paid) → blind on monetization

---

## Learning loop (self-optimization)

Each incident / failure / new pattern:
1. Document in `docs/error_log.md` (root cause + lesson)
2. If pattern is reusable → write new `.claude/skills/<name>/SKILL.md`
3. Update this doc if role/process changes
4. Update CLAUDE.md if top-level rule changes

### Skills I should build (gaps from this session)
- `fb-browser-automation` — Playwright + Chrome cookie injection + verify-before-comment. (No MCP fallback when ext consent layer breaks.)
- `ops-cycle` — formalized "read dashboard → triage → dispatch → loop" pattern
- `post-publish-verification` — covered partially by `live_verify.py`, may need full skill doc

### Patterns NOT to repeat (from 2026-05-19 session)
- Retry-loop without verifying state = duplicate posts (3 Nikkei dups created)
- Diff-detection via "top of feed" = wrong post hit when FB doesn't refresh fast (use pfbid before/after set diff with explicit known set)
- "Publish complete" without verifying public URL + downstream propagation
- Solo execution without agent dispatch when scope is bounded
- Sending alert emails with "建議行動" instead of just doing the action

---

## Cron schedule (where audit runs)

To be wired in `config/runtime_schedules.json`:
- `audit_publish_sync` — hourly
- `audit_fb_pipeline` — every 6h
- `ops_dashboard` — hourly (writes snapshot to `storage/ops/dashboard_latest.json`)

---

## Next actions (rolling)

Continuously updated. Top priority always at top.

1. [pending] Wire audit + dashboard into runtime_schedules.json cron
2. [pending] Add `live_verify_failed` alerting on draft → published transition (done by agent a67763789e702d1da, commit needed)
3. [pending] Backfill `live_verify_failed=False` stamps for last 30 days of published articles
4. [pending] Build analytics ingestion (Mission 1/5 visibility gap)
5. [pending] Build monetization funnel tracking (Mission ultimate goal)

---

**This doc is living. I update it after each cycle.**
