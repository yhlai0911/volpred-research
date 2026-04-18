# K1225 — Paper 4 body_v4 Dual-Framing Edit Guide (CONFLICT-A4 resolver)

**Status**: COMPLETED — dual-framing edit guide produced, awaiting user pick.
**Date**: 2026-04-17
**Type**: `paper_edit_guide_markdown` (no `.tex`, no experiment script)
**Worktree**: `agent-a05ba53d`

## 1. Motivation

Paper 4 body_v4 rewrite gate was unlocked by:

- **K1203** 7/7 panorama verdict: `UNIVERSAL_NULL_7_OF_7 with TLT caveat`.
- **K1208** §5 Markdown draft ready (UNIVERSAL_NULL framing, 7-asset panorama).
- **K1218** Appendix A template available for reuse in Paper 4 (shared protocol
  for cross-paper replication appendices).

However, a framing conflict (CONFLICT-A4) blocked immediate `body_v4.tex`
writing:

- **User commit `7ecab636`** (2026-04-17) indicated a "channel-specific pivot"
  for Paper 4.
- **K1203 session gate** (same date) unlocks under `UNIVERSAL_NULL_7_OF_7`
  language, and the K1208 draft was authored in that framing.

Main thread needs user decision before `body_v4.tex` cherry-pick. K1225
unblocks the decision by pre-producing **both** candidate framings as
parallel `.md` edit guides, so the user can compare side-by-side and pick
one.

## 2. Differentiation

| Artefact | Purpose | Produced by |
|----------|---------|-------------|
| K1208 `k1208_draft.md` | §5 narrative in UNIVERSAL_NULL framing | K1208 (synthesis experiment) |
| K1218 `k1218_appendix_draft.md` | Paper 6 replication appendix template | K1218 (reused here for Appendix A structure) |
| K1203 README verdict statement | `UNIVERSAL_NULL_7_OF_7 with TLT caveat` | K1203 (EEM PIT closure) |
| **K1225 dual-framing guide** | **Both framings side-by-side + decision matrix** | **K1225 (this)** |

K1225 is not a new experiment; it is an **organisational resolver** that
consolidates K1203, K1208, and K1218 outputs into a user-facing A/B choice.

## 3. Related K

- **K1116c** (`64a9d569`) — SPY 6 PIT variants; alt-data NULL baseline.
- **K1116f** (`885d7b0b`) — GLD / TLT / BTC PIT; TLT +3.74 outlier.
- **K1201** (`87059567`) — QQQ / USO PIT; 6/7 panorama.
- **K1203** (`477c504a`) — EEM PIT closure; 7/7 panorama gate UNLOCKED.
- **K1208** — §5 synthesis draft (UNIVERSAL_NULL framing).
- **K1218** — Paper 6 appendix draft (template reuse for Paper 4 Appendix A).

## 4. Method

Pure documentation synthesis. No new computation; all numbers cited
verbatim from the source experiments above (sign convention preserved,
4-decimal t-stats, QLIKE percentages).

### 4.1 Framings produced

1. **Version A — Channel-Specific Framing**
   - Title: "Alt-Data Channels and Native IV Dominance Across Asset Classes"
   - Claim: "no alt-data channel delivers Harvey-threshold improvement over
     asset-class native IV under PIT alignment"
   - Matches user commit `7ecab636`
   - Extends existing `main_v3.tex` channel vocabulary (line 210
     "behavioral channels", line 226 "fear channel", line 806 "eleven signal
     families... represents one channel")
   - Claim scope is modest (channel-by-channel, asset-by-asset)

2. **Version B — UNIVERSAL_NULL Framing**
   - Title: "Cross-Asset Universality of Native IV Sufficiency"
   - Claim: "native implied-volatility proxies are sufficient for 1-step-ahead
     realised-volatility forecasting across seven asset classes"
   - Matches K1203 session gate `UNIVERSAL_NULL_7_OF_7 with TLT caveat`
   - K1208 draft verbatim (zero rewrite cost)
   - Strong negative-result methodology contribution in Harvey (2016) tradition

### 4.2 Shared elements across both framings

- 28-cell panorama table (7 assets × 4 specs; identical numbers)
- TLT finstress +3.74 disposal (three-independent-arguments regime-artefact
  characterisation)
- ^VXEEM dual-baseline caveat (^VIX primary + rv30 robustness)
- Statistical design: AR(1) + native IV; DM-HLN Harvey (1997); QLIKE
  Patton (2011); Harvey (2016) |t| > 3 gate; 5% Patton economic gate;
  seed 42
- Source commit traceability (K1116c / K1116f / K1201 / K1203)
- Appendix A shared structure (K1218 template reused for Paper 4)
- Integration steps (copy body_v3 → apply chosen §5 → integrate
  Appendix A → xelatex × 2 → paper-update → commit)

### 4.3 Decision matrix (for user)

See full matrix in `k1225_dual_framing_guide.md` §"Decision Matrix (for
user)". Recommendation: **Version B** is default if user declines to pick
within active session (K1208 already written in this framing; K1203 gate
explicitly unlocks under this language). Version A is available if
channel-specific pivot is preferred.

## 5. Files

- `k1225_dual_framing_guide.md` — main deliverable; ~2,000 words; both
  framings fully specified with §5 titles, narratives, cherry-pick
  locations, narrative commitment text, and positioning rationale.
- `k1225_dual_framing.json` — structured metadata; Version A and Version
  B specs as parallel objects for downstream tooling.
- `README.md` — this file.

## 6. Strict rules observed

- **No `.tex` output.** Only `.md` and `.json`. Main thread owns the
  eventual `body_v4.tex` cherry-pick per CLAUDE.md paper-workflow rule.
- **Verbatim panorama numbers.** All 28 cells match
  `experiments/k1208/k1208_panorama_table.csv` and K1203 README §3.2
  (4-decimal DM t-stats; QLIKE % to 2 decimals).
- **Both versions cite same source commits** (`64a9d569` K1116c,
  `885d7b0b` K1116f, `87059567` K1201, `477c504a` K1203).
- **Seed 42** fixed in all cited experiments (no new random operations
  in K1225).
- **Worktree-scoped output.** Only `experiments/k1225/` modified; no
  `storage/**`, `paper/**`, `research_program.md`, `knowledge.json`, or
  Supabase / Mirror sync touched. Main thread owns those writes after
  user decision.

## 7. Main-thread next actions (once user picks)

1. **User picks A or B.** CONFLICT-A4 resolved.
2. Main thread copies `paper/vix-sufficiency/body_v3.tex` →
   `body_v4.tex`.
3. Apply chosen version's §5 rewrite from `k1225_dual_framing_guide.md`
   (sections A.1-A.5 or B.1-B.5).
4. Integrate shared Appendix A (K1218 template adapted for Paper 4).
5. Update `main_v4.tex` include list; `xelatex main_v4.tex` twice.
6. Run `uv run volpred ops paper-update --paper-id vix-sufficiency`.
7. Commit with CONFLICT-A4 resolution marker (A or B) in message.
8. Update `research_program.md` + `knowledge.json` with body_v4 commit
   hash; set paper state to `decision_made_awaiting_body_rewrite` →
   `body_rewrite_completed`.

## 8. Limitations

1. **K1225 does not decide.** The user must pick A or B; K1225 only
   frames the choice.
2. **K1208 draft framing is Version B.** A user pick of Version A
   requires more main-thread rewrite than Version B (cost disclosed in
   decision matrix).
3. **Version A requires abstract + §1 updates** to de-universalise the
   paper's central claim. K1225 flags this but does not pre-draft
   abstract/§1 edits — those are main-thread writing decisions.
4. **No new empirical test.** K1225 does not add any new asset,
   specification, or lag variant. It is purely a documentation resolver.

## 9. References

- K1116c / K1116f / K1201 / K1203 experiment READMEs (source data)
- K1208 §5 Markdown draft (UNIVERSAL_NULL framing source)
- K1218 Appendix A template (shared structure)
- Harvey, Liu & Zhu (2016) RFS — multiple-testing |t|>3
- Patton (2011) J Econometrics — QLIKE proxy-robust
- Harvey, Leybourne & Newbold (1997) IJF — HLN DM correction
- Baker, Bloom & Davis (2016) QJE — EPU channel
- Brave & Butters (2011) Chicago Fed Letter — NFCI channel
- CBOE VIX methodology docs
- Croushore & Stark (2001) J Econometrics — vintage data
- User commit `7ecab636` (2026-04-17) — channel-specific pivot
  indication

## 10. Worktree discipline

- Outputs confined to `experiments/k1225/` (3 files: guide `.md`, meta
  `.json`, README).
- Zero shared-state modification.
- Main thread owns `paper/vix-sufficiency/body_v4.tex` write,
  `knowledge.json` update, `research_program.md` backlog edits, and
  Supabase / Mirror sync.
