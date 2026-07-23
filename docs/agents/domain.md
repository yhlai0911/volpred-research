# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- `CONTEXT.md` at the repo root.
- `CONTEXT-MAP.md` if it exists.
- Relevant ADRs under `docs/adr/`.

If these files don't exist, proceed silently. Domain-modeling skills create them lazily when terminology or architectural decisions are resolved.

## File structure

This is a single-context repo:

```text
/
├── CONTEXT.md
├── docs/adr/
└── src/
```

## Use the glossary's vocabulary

When output names a domain concept, use the term defined in `CONTEXT.md`. Avoid synonyms the glossary explicitly rejects.

If the required concept is missing, reconsider whether the term belongs to the project or record the gap for `/domain-modeling`.

## Flag ADR conflicts

If proposed work contradicts an existing ADR, surface the conflict explicitly instead of silently overriding the decision.
