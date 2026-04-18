# Session 2026-04-17 Execution Playbook (1-page)

**Session-End State**: ~80 K experiments / 30+ drafts / ~$4000+ estimated spend.
Distilled from K1236 final briefing, K1226 master index, K1219 dashboard, and recent K edit guides (K1223/K1224/K1225/K1228/K1231-K1234/K1243-K1247). Seed=42.

---

## IMMEDIATE (no decision, ~3 hr)

- **00:00-00:30 Paper 1** (K1224 guide, 7 items): body_v4.tex cherry-pick -> xelatex -> paper-update
- **00:30-01:45 Paper 6** (K1223 guide, 6 items): body_v2 + K1218 Appendix A + 3 warnings -> xelatex -> paper-update
- **01:45-02:00 Paper 5** (K1233 P5-1 script fix): 1 script edit -> commit
- **02:00-02:30 Paper 7** (K1233 P7-1/2/3/4): 3 fixes + decision -> xelatex -> paper-update
- **02:30-03:00 Paper 9 R2 footnote** (K1245 recommended variant): tablenotes \item insert -> xelatex -> paper-update

## QUICK DECISIONS (~10 min total user time)

- **Paper 4 A/B pick** (K1247 cheatsheet, default B) -> then K1225 Version B execution (2-3 hr)
- **Paper 2 §5 K1222b review** (15 min) -> then body_v4 §5 rewrite (2-3 hr)

## DEEP DECISIONS (~30 min user time, ~12 hr execute)

- **Paper 3 pivot a/b/c** (K1205 recommends b, K1217 drafted) -> if (b): initialize paper/prg-hybrid-null/ (~2 wk review cycle)
- **BTC GAS negative go/no-go** (K1214 draft + K1228 init guide) -> if go: initialize paper/btc-gas-negative/ (~2 hr init + 1-2 wk review)
- **Paper 8 a/b/c per-K** (K1231: 7 experiments × 4 rebuild + 1 revise + 2 errata) (~12 hr)

## PENDING / AUTONOMOUS (no user needed)

- **Paper 10 body_v1** (K1234/K1237-K1247 full drafts): awaits user "execute" command (3-6 hr)
- **K1100g_d9** cadence verification (P3 queued)
- **K1202b** primary-source hand-verify (P3 queued)

---

## DEPENDENCY GRAPH

```
Paper 1 (K1224)        -> independent
Paper 6 (K1223)        -> independent
Paper 5/7 (K1233)      -> independent
Paper 9 (K1245)        -> independent (after K1235b vindicate)
Paper 2 (K1222b)       -> blocked by 15-min review
Paper 4 (K1225)        -> blocked by CONFLICT-A4 pick
Paper 3 (K1217/K1227)  -> blocked by pivot a/b/c
BTC GAS (K1214/K1228)  -> blocked by go/no-go
Paper 8 (K1231)        -> blocked by per-K a/b/c
Paper 10 (K1243/K1246) -> blocked by execute command
```

---

## SINGLE-SHOT SESSION BLUEPRINT (5-6 hr high-impact execute)

1. Review K1247 Paper 4 cheatsheet -> pick B (1 min)
2. Execute IMMEDIATE items Paper 1/5/6/7/9 (3 hr)
3. Review K1222b Paper 2 §5 (15 min) -> execute body_v4 (2 hr)
4. Execute Paper 4 Version B (2 hr)
5. Push to remote (4h sync) + session close commit

## RECOMMENDED NEXT USER ACTION

Pick: **"Start IMMEDIATE pipeline Paper 1 -> 6 -> 5 -> 7 -> 9"** (3 hr execute block)
-> Then CHECK K1247 cheatsheet (2 min) -> Paper 4 B
-> Then REVIEW K1222b (15 min) -> Paper 2 §5
-> Then DEFER Paper 3 / 8 / BTC-GAS to dedicated decision session
