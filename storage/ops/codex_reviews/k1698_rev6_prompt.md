# Codex primary-path review — K1698 rev6 (README honesty re-certification)

You are a rigorous quantitative-finance code+manuscript reviewer. This is **round 6 (3-strike
active)**. In rev5 you judged FAIL with freeze integrity + code + data + lookahead + gate all
PASS; the ONLY four blockers were README over-claims / untraced numbers. rev6 changed **only**
`experiments/k1698/README.md` (all six other frozen files are byte-identical to rev5 — see the
freeze list below). Judge whether the four blockers are now genuinely resolved AND whether the
edit introduced any NEW over-claim / untraced number.

Frozen file set (rev6), review AGAINST these exact files (do not review any other checkout):
```
experiments/k1698/README.md              (CHANGED this round)
experiments/k1698/k1698.py               (unchanged)
experiments/k1698/k1698_results.json     (unchanged — the sole source of truth for numbers)
experiments/k1698/run_log.txt            (unchanged)
experiments/k1698/fig1_implied_scale_bootstrap.png / fig2_trinity_before_after.png / fig3_scale_factors.png (unchanged)
```
The rev6 freeze sha list is at `storage/ops/codex_reviews/k1698_rev6_freeze.txt`.

## The four rev5 blockers (must each be resolved, and NOT reintroduced elsewhere)
1. COMPLETE-REPLICATION-OVERCLAIM: README claimed 「完全復現 K1684/K854」 but
   k1698_results.json /k854_replication_bridge is n_matching=11, n_cells=14, match_rate=0.7857.
   → must now read as partial 11/14 (78.57%) everywhere; no 「完全復現」 anywhere.
2. UNTRACED-HISTORICAL-NUMERICS: headline t≈−5.6, K1684 −5.13, and 「倒置 154 個 CI」 did not
   exist in the JSON. → must be removed or re-sourced to real JSON values.
3. UNTRACED-SOURCE-FILE-COUNT: TAIFEX 「2,192 檔」 absent from JSON; /rv_construction/n_days=2191
   and /session_alignment_check/files_checked=40 are different quantities. → must cite the correct
   traced quantity (explicitly labeled) or drop.
4. UNRECEIPTED-FIRST-BUILD-RUNTIME: 「首建 +1 分鐘」 had no receipt (only /elapsed_sec=57.3, a
   cache-hit run). → must be dropped or receipted.

## What to do (be adversarial; this is a 3-strike final-stretch honesty gate)
- For EVERY headline/numeric claim remaining in README, confirm it traces to a real value/path in
  k1698_results.json. Flag ANY that does not (that is a CRITICAL, whether old or newly introduced).
- Confirm each of the 4 blockers is resolved, not merely reworded around.
- Watch for a NEW over-claim introduced by the softening edit.

## Output (write to the output file)
- Overall: PASS / FAIL
- Per-blocker (1-4): RESOLVED / NOT-RESOLVED, with the specific README line + JSON path evidence.
- CRITICAL findings (must be empty for PASS): each untraced/over-claimed number, or "none".
  Mark each as "reintroduction of blocker N" or "NEW distinct defect".
- One-line bottom line: is the README now fully traceable and honest, safe to certify?
