# PRG-Periodic-GARCH v6 — round summary

**Trigger**: Codex v5_independent verdict = REJECT (3 BLOCKING + 4 MAJOR + 3 MINOR).
**Scope of this round**: BLOCKING #1 partial (identification reframe — abstract / conclusion / Section 4.5 title / limitations) + BLOCKING #3 partial (open-tradability caveat added to limitations). BLOCKING #2 (truly aligned same-information GJR-type benchmark across all six markets) requires new experiment — split into follow-up task.

## Files

- `body_v5_pre_edit.tex` — snapshot of `main.tex` immediately before v6 edits (for diff)
- `agy_review.md`, `codex_review.md` — under `../v5_independent/`
- diff vs v5: `git diff --no-color v5_independent..HEAD -- paper/prg-periodic-garch/main.tex` after this commit lands

## Changes (this round)

1. **Abstract (line 41 family)**: dropped "significantly outperforms ... isolating the information bridge as the mechanism"; new framing explicitly states that the PRG full-day forecast is formed in two stages, that the headline DM statistics combine a structural innovation with a richer real-time information set at the intraday-forecast horizon, that a cleanly structural-only attribution would require a same-information benchmark, and that the SPY GJR-X uses a lagged overnight regressor rather than the current-day realization. The Separate-GARCH ablation is now described as "supporting the cross-session bridge as a substantive mechanism within models that share session-level access" rather than as isolating the mechanism in absolute terms.
2. **Section 4.5 subsection title**: `Fair-information benchmark: GJR-X` → `Lagged-overnight benchmark: GJR-X`. The body of Section 4.5 already disclosed the info-set asymmetry (line 312 in pre-edit) and required no further change.
3. **Limitations §5 (line 351)**: the third limitation was rewritten to acknowledge that the headline PRG-vs-GJR comparison combines structural and information-set effects and that the GJR-X benchmark in §4.5 does not strictly equalize information sets (lagged vs current-day overnight); a same-information cross-market replication is named as the next step. A fourth limitation was added covering the opening-auction tradability narrative (BLOCKING #3 partial), specifying the interpretive scope of the VT Sharpe/drawdown numbers under an opening-auction participation protocol or small-latency approximation.
4. **Conclusion (lines 361--363 family)**: softened "significantly outperforms ... is the mechanism behind PRG's advantage" → "produces lower QLIKE losses ... is a substantive contributor to PRG's advantage"; explicitly framed the headline result as a joint structural-plus-information advantage and limited the HAR/GJR target-mismatch claim to the TAIFEX sample examined here, presented as consistent with a broader concern rather than a general adjudication; replaced "first-order feature of return dynamics that standard volatility models fail to exploit" with "operationally informative for short-horizon volatility forecasting in the markets studied" + an explicit "natural next step" sentence naming the same-information cross-market benchmark and a formal microstructure treatment of opening-price tradability.

## Out of scope (split into follow-up tasks)

- **BLOCKING #2 full fix** — implement and estimate a same-information GJR-type benchmark (current-day overnight available at day-$d$ open) across all six markets; report DM vs PRG and update §4.5/§4.6 + Table 1 footnote.
- **MAJOR #4** — Harvey (2016) `|t|>3.0` citation provenance: replace with a defensible source (e.g., the explicit Bonferroni / FDR / MCS argument) and remove the "now standard in MCS literature" framing where unsupported.
- **MAJOR #5** — VaR / ES strong-claim retraction: scope Abstract / §4.3 to the markets actually shown in Table 3; replace "dominates" and "consistent ranking across all six markets" with what the data shows.
- **MAJOR #6 + #7** — ablation generalization scope-pull-in (SPY-only → SPY-only-evidence wording) and HAR-target-mismatch claim scope (TAIFEX-only → TAIFEX-only or replicate cross-market).
- **MINOR #8--#10** — Table 1 MCS row consistency (PRG only vs PRG Basic + Extended), discussion-mechanism citation gaps, economic-value formal test table (Sharpe difference test / bootstrap CI / transaction-cost sensitivity).

## Verification

- `xelatex main.tex` clean (19 pp, one overfull \hbox warning at line 351 — typesetting, not structural)
- Cross-references resolved on second pass
- No numbers, tables or figures changed in this round; data and `reproduce.py` unaffected
- Pre-edit snapshot retained at `body_v5_pre_edit.tex` for transparent diff
