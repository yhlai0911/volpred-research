# Codex primary-path review — K1715 attempt 3 (fit-diagnostic honesty fix)

You are a rigorous quantitative-finance code reviewer. Review the diagnostic-reporting block of
`.claude/worktrees/k1715-204d556b/experiments/K1715/K1715.py` (an unmerged worktree branch,
resolvable from the repo root you are in), commit `c9d75cf1d`. **This is escalation attempt 3
(final rung).** The ONLY change under review is the fit-convergence diagnostic reporting; the
fit logic, the min-NLL guard, the seeds, and the scientific NULL conclusion are unchanged and
were verified in attempt 2. Do NOT ask for a rerun; judge the CODE.

## What the prior two Codex CRITICALs were (must be fully resolved now)
1. `bfgs_success` / `bfgs_status` / `bfgs_message` / `optimizer_success` were taken from the
   *accepted* best (when the guard kept Nelder-Mead they were NM's flags) yet labeled as BFGS
   diagnostics. The `convergence_note` claimed `optimizer_success_rate` reports scipy's strict
   BFGS gtol flag — false when NM was accepted.
2. `bfgs_nll` stored the *guarded accepted* NLL (min(NM,BFGS)), not the raw BFGS NLL, undisclosed.
3. `nm_to_bfgs_improve` is non-negative by construction; a 0 from a *failed* BFGS polish was
   readable as "NM already stationary", masking the polish failure as positive evidence.

## The fix under review
- Per-survivor: raw `res_bfgs` diagnostics (`bfgs_success/status/message/nll`, nll None if
  non-finite) are now stored verbatim alongside an `accepted_method` ("NM"|"BFGS"). `res` remains
  the guarded min-NLL choice.
- `convergence` dict now reports RAW BFGS in `bfgs_*`, adds `accepted_method`,
  `accepted_optimizer_success` (= accepted solver's own flag), `accepted_nll`, and renames the
  gain to `guarded_polish_gain` (documented >=0-by-construction).
- `_convergence_summary` keeps `bfgs_success_rate` (now the raw BFGS rate, documented), adds
  `accepted_optimizer_success_rate`, renames the summary gain key, and rewrites `note`.
- `convergence_note` rewritten to say `optimizer_success_rate` is the ACCEPTED solver's own flag
  (BFGS gtol if accepted_method=='BFGS', NM xatol/fatol if 'NM'), with the raw BFGS rate reported
  separately.

## What to judge (be adversarial, but bounded)
1. Are the three prior CRITICALs now genuinely resolved — i.e. can a reader distinguish RAW BFGS
   outcome from the ACCEPTED-solver outcome from every reported field and note?
2. Is any field STILL mislabeled, or any note text STILL claiming something the code does not do?
3. **Is there a THIRD, DISTINCT honesty/labeling defect** (not a restatement of 1-3)? If yes,
   name it precisely; if no, say so explicitly.
4. JSON-serialization safety of the new fields (None / str / float only; no inf/nan leaking).

## Output (write to the output file)
- Overall: PASS / FAIL
- CRITICAL findings (must be empty to merge): list each, or "none". For any CRITICAL, state
  whether it is a RESTATEMENT of prior issues 1-3 or a genuinely NEW distinct defect.
- MAJOR / MINOR findings.
- One-line bottom line: are the diagnostics now honest and safe to merge?
