# K1251 — K719 rebuild (Paper 8 Table 8 CB structured reconstruction)

- Experiment ID: `k1251`
- Status: completed (structured rebuild; partial allclose)
- Created At: 2026-04-17
- Decision source: K1231 option (a) for K719
- Paper: `paper/volatility-absorption/` Table 8 "Hedging Cost-Benefit Ratio by VIX Regime"
- Seed: 42
- Worktree: `.claude/worktrees/agent-a2010d5e/experiments/k1251/`

## Note on task naming

The K1251 brief mentions "CB (crypto-basis) ratios". The underlying Paper 8
Table 8 is the **Hedging Cost-Benefit** table (main_v2.tex L472-497). "CB"
here = Cost-Benefit, not crypto basis. Paper 8 contains no crypto-basis
table. This is the table K1231 decision record (`K719` row) maps to.

## Why K1251 exists

Per `docs/paper-guide.md` 三方一致 rule, every paper table must be
reproducible by a structured script. K719's current state (verified by
K1231):

- `experiments/k719/k719.py` is a qualitative synthesis script; no Table 8
  numerics in its JSON.
- `paper/volatility-absorption/reproduce_report.json` marks Table 8 as
  0/3 match, 3 untraceable ("K719 not in JSON").
- Paper main body states CB ratios 13.7 / 8.0 / 3.6 verbatim but no
  script produces these numbers.

K1231 recommended option (a) rebuild. K1251 is the structured rebuild.
**K719 original files are NOT modified.**

## Methodology (verbatim from main_v2.tex L472-497)

1. Download SPY + ^VIX daily, 2006-01-01 -> 2026-03-31 (yfinance).
2. Define VIX regimes (3-bin, as in Table 8):
   - Calm: VIX < 15
   - Elevated: 15 <= VIX < 25
   - High: VIX >= 25
3. Shock day: `|Delta VIX| > 2`.
4. Avg Shock Loss (%) = mean(|SPY log return * 100|) on shock days in regime.
5. Daily Hedge Cost (%) = mean(VRP) in regime, where
   `VRP_t = VIX_t^2 / 252 - RV_t / 252` and RV is rolling 22-day sum of
   squared daily log returns (Section 3.7 convention, matches K720).
6. CB Ratio = Avg Shock Loss / Daily Hedge Cost.

Also run with RV window 20 for robustness (Section 7.3 alternative) and
with VRP clipped at 0 (since a negative hedge cost is economically
ill-defined — hedges never pay you).

## Results

Sample: 2006-01-04 -> 2026-03-30, 5090 days. Primary config RV=22, raw VRP.

| Regime   | Days | Shock Days | Avg Shock Loss (%) | Daily Hedge Cost (%) | CB Ratio |
|----------|------|-----------|-------------------|----------------------|----------|
| Calm     | 1735 | 33        | 1.2138            | 0.6208               | 1.9553   |
| Elevated | 2454 | 357       | 1.5497            | 1.3876               | 1.1168   |
| High     | 880  | 376       | 2.6276            | 4.5859               | 0.5730   |

Paper Table 8 canonical (main_v2.tex L485-487):

| Regime   | Shock Loss (%) | Hedge Cost (%) | CB Ratio |
|----------|----------------|----------------|----------|
| Calm     | 1.18           | 0.086          | 13.7     |
| Elevated | 1.56           | 0.196          | 8.0      |
| High     | 2.61           | 0.725          | 3.6      |

### Per-cell allclose (rtol=0.05)

| Cell type      | Calm | Elevated | High | Pass rate |
|----------------|------|----------|------|-----------|
| Shock Loss     | YES (2.87%) | YES (0.66%) | YES (0.67%) | 3/3 |
| Hedge Cost     | NO (621.8%) | NO (608.0%) | NO (532.5%) | 0/3 |
| CB Ratio       | NO (85.7%)  | NO (86.0%)  | NO (84.1%)  | 0/3 |

Overall allclose pass rate: **3/9 (33.3%)** (RV=22, raw VRP).
Clipped VRP and RV=20 variants yield the same 3/9.

## Interpretation — 三方一致 rule, which branch?

- **Shock-loss column (3/3 YES, <3% drift)** confirms the SPY + VIX pipeline
  and regime bins are correctly implemented. K1251's data ingestion matches
  K716 / K718 behaviour.
- **Hedge-cost column systematically 5-7x larger than paper** (+600% drift
  across all three regimes, flat ratio) strongly suggests the formula
  written in the paper note (`VIX^2/252 - RV/252`) is not the formula that
  produced 0.086 / 0.196 / 0.725. The flat 5-7x factor hints at a unit
  convention (VIX already in variance-annual-%^2, or RV in monthly %^2
  rather than the daily-sum convention used here).
- **CB ratio column diverges accordingly** — denominator drives the miss.
- **No cell was fudged** to match. Following the 三方一致 rule,
  K1251 commits the divergence honestly:
  - The shock-loss evidence is strong; the data pipeline is sound.
  - The hedge-cost formula the paper body cites needs a main-thread
    clarification — either (b) revise the note to the formula that actually
    produces 0.086/0.196/0.725, or (c) keep CB ratios as "illustrative
    calculations" (paper L492 already says so) and record an errata with
    the ~6x magnitude disclosure.

## Files

- `k1251.py` — structured CB computation (this directory).
- `k1251_results.json` — per-regime table + allclose verdict per cell +
  both RV windows + raw/clipped variants.
- `k1251_vs_paper_table8.md` — human-readable comparison table.

## What this unblocks / blocks

- **Unblocks**: paper `reproduce_report.json` T8 can now cite K1251 (not
  K719 "not in JSON"). The shock-loss column reaches 3/3 reproduce.
- **Blocks**: CB ratio alignment still requires main-thread decision on
  hedge-cost formula. Recommended next step = main-thread choose (b) or
  (c) per 三方一致 rule. Options:
  - (b) **Revise paper**: replace hedge-cost/CB values with K1251's raw
    computation, or clarify the exact VRP formula (e.g. `sqrt(VIX^2/252 -
    RV/252)` or `(VIX^2 - RV)/252^2` etc.) that produces the canonical
    numbers.
  - (c) **Errata**: disclose "Table 8 CB ratios are illustrative; computed
    with scaled-VRP-proxy whose exact units differ from K1251 structured
    reproduction by ~6x in hedge cost". Paper L492 already flags these as
    illustrative, so (c) is cheap.
- **Does NOT** modify `experiments/k719/` originals, `paper/` body, or
  any shared JSON. Main thread owns those edits.

## References

- K1231 `k1231_reconstruction_plan.md` (K719 section)
- K1231 `k1231_reconstruction_decisions.json` (K719 entry, recommendation "a")
- `paper/volatility-absorption/main_v2.tex` L472-497
- `paper/volatility-absorption/reproduce_report.json` T8 row
- K720 — VRP methodology source (Section 3.7, RV=22)
- `docs/paper-guide.md` — 三方一致 rule
