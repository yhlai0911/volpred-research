VERDICT: PASS
REVIEWER: GPT-5 Codex / high effort
LOOKAHEAD_CHECK: pass — all d/w/m features use explicit `.shift(1)`; origin t trains only through t−1, with no same-day signal×return path.
DEFECT_1_EXANTE_LEDGER: verified — independently reproduced 2,545/2,550 ex-ante-determined OOS rows and 5 exceptions. Ex-ante t = −3.670723/−3.369646; excluding all 127 roll days gives −3.584221/−3.664805. All four calls are HAR_RV5_WINS. Machine verdict explicitly requires ex-ante concurrence.
DEFECT_2_RETRACTION: verified — §7 explicitly retracts “worth maintaining,” states costs/economic value were not measured, and limits the conclusion to non-zero predictive gain. No equivalent affirmative overclaim survives.
NESTED_DM_ADJUDICATION: sound — nonconstant predictors are distinct RV5 d/w/m versus daily-r² d/w/m sets; neither model is a parameter restriction of the other. Forecast gaps, correlations, and non-degenerate loss differences support the structural conclusion.
NUMBER_INTEGRITY: ok — hashes matched before and after review; independent in-memory rerun exactly reproduced the slice hash, row counts, QLIKE values, headline/full/no-roll DM statistics, p-values, and verdicts. Seed 42 is fixed; the calculation is otherwise deterministic.
BLOCKING_DEFECTS:
- none
NOTES: Frozen bytes are certified. Non-blocking reproducibility note: `_main_repo()` resolves a relative git path against process cwd, so execution currently needs to start from `experiments/K1729/`; this does not affect the reproduced result.
