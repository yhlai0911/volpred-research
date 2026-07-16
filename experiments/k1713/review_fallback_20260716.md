# K1713 frozen-commit review

- Reviewed commit: `cd4e5c259f88c545825b1ee8ccb68e73df142fcb`
- Reviewer: fresh-context code-reviewer fallback
- Primary-path status: Codex CLI 0.144.1 / gpt-5.6-sol was attempted first but returned the account usage-limit error before producing a verdict.
- Verdict: `PASS`
- Blocking defects: none

## Evidence

- Primary inference calls canonical `volpred.stats.model_evaluation.dm_test(..., h=1)`.
- Bartlett-HAC lag is 15 for all assets; ACF(1) and fixed-lag sensitivity at 0, 1, 5, 10, 15, and 20 are reported.
- Canonical results remain `NULL`: SPY `t=0.4754, p=0.6345`; 0050.TW `t=0.7516, p=0.4524`; TWII `t=0.4727, p=0.6365`.
- K1661's lag-zero local DM-HLN is explicitly retained as a legacy byte-replay diagnostic, not primary inference.
- The independent `signal.shift(1)` ledger exactly matches all three source designs with zero numeric tolerance.
- QLIKE uses `actual / predicted`; all 30 stored-metric replay comparisons pass.
- K1661 source, result, and review bytes match pinned commit `cdb8759466e082aa5565f5df9796a2f85dc08221`.
- The result does not claim a second replication or a new knowledge finding.

## Commands

```bash
uv run python experiments/k1713/K1713.py
uv run python scripts/experiment_gates.py run --path experiments/k1713
```

Both returned zero; the integrity gate reported PASS.
