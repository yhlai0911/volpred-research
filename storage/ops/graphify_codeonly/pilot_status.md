# Graphify Code-only Pilot

- Generated at: 2026-07-02T05:25:20.161863+00:00
- Package: graphifyy[mcp]
- Source check OK: True
- Scan scope: src/volpred + scripts only
- Mode: graphify update --no-cluster (AST-only, no LLM)
- Nodes: 4837
- Edges: 12129
- Source files: 357
- Benchmark reduction: 29.3x
- Token baseline: token_baseline.json uses platform_ops as proxy; current reports do not isolate hourly dispatch sessions.
- Follow-up task: platform_ops_graphify_codeonly_14d_verdict_20260716 blocked until 2026-07-16T00:00:00+00:00

Local MCP add command:

```bash
claude mcp add --scope local graphify-volpred-codeonly -- /Users/yhlai0911/.local/bin/graphify-mcp --graph /Users/yhlai0911/volpred-research/storage/ops/graphify_codeonly/graphify-out/graph.json
```
