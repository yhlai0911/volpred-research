---
name: strategy-lifecycle
description: Evaluate, register, activate, deactivate, or roll out a VolPred strategy. Use for strategy registry changes, launch gates, metadata, sensitivity review, rollout, or forward-tracking decisions.
---

# Operate a strategy lifecycle

Read `docs/strategy-registry.md` and the current `STRATEGY_REGISTRY` implementation before acting.
Use `scripts/evaluate_new_strategy.py` for formal comparisons when applicable.

## Workflow

1. Resolve the strategy identity, active state, implementation owner, metrics source, and
   comparison period from canonical sources.
2. Verify same-period baseline comparison, cross-OOS evidence, Codex review, sensitivity, and
   maximum-drawdown gates.
3. Verify all strategy signals use lagged information and that baseline and candidate share the
   same lag convention.
4. Change metadata or active state only through the current `volpred ops strategy-*` command whose
   `--help` confirms the required operation.
5. Recalculate configured projections and read the registry, database, metrics target, and live UI
   back.
6. Start or verify forward tracking; do not backfill paper-trading history.

## Completion

Report each launch gate separately, including null or failed evidence. Activation is complete only
after canonical state and every configured projection agree.
