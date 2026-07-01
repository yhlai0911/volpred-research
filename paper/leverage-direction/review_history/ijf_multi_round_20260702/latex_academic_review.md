# LaTeX Academic Review — IJF Version

**Verdict**: **FAIL_MAJOR_REVISION**  
**Scope**: `main_v_ijf.tex`, `body_v_ijf.tex`, `tables_main.tex`, replication notes, and compiled PDF.

## Severe Findings

### H1. Central sample-map claim still contradicts the VT evidence

The manuscript repeatedly says the design observes measurement-to-allocation pass-through on the same assets, same periods, and one protocol:

- `body_v_ijf.tex:130`: same assets, same periods, single evaluation protocol.
- `body_v_ijf.tex:153`: pass-through on the same assets, over the same periods, under one protocol.
- `body_v_ijf.tex:164`: same assets, same windows, single evaluation protocol.
- `body_v_ijf.tex:174`: every forecast-evaluation and allocation result is OOS only, with no in-sample/OOS mixing.

But the central VT table is explicitly native-window:

- `tables_main.tex:112`-`128`: SPY 2014-2026, GLD 2022-2026, TLT/EEM circa 2015-2026, BTC post-2019.
- `REPLICATION.md:103`-`115`: a uniform 2015-2026 check matched only 6/20 cells, and GLD/BTC headline magnitudes are window-specific.

This is not wording polish. The IJF lead contribution is the measurement-to-allocation wedge, and the allocation-level half of the wedge is still based on heterogeneous windows. A referee can reject the central causal comparison on this point alone.

**Required fix**: either rerun the VT table on one pre-declared common OOS panel, or explicitly relabel Table `tab:vt` as descriptive native-window evidence and remove "same windows / single protocol" language from the central claim.

### H2. `body_v_ijf.tex` prose is not fully covered by the reproduce gate

`reproduce.py` is green, but its own scope note says literal prose checks still bind to archived `body.tex` / `main.tex`, while `body_v_ijf.tex` was manually cross-checked during drafting:

- `reproduce.py:36`-`46`: IJF prose is a rewrite and does not repeat exact literal strings.
- `reproduce.py:461`-`468`: `6/6 OOS classification` and `rho=0.83 (N=14)` have no dedicated JSON source and are NOTE-tier.
- `reproduce.py:521`-`523`: `Table 7 (tab:vt)` is caption-documented and not re-gated.

That is acceptable as an internal drafting note, but not as an IJF/CASCaD-grade gate for a paper whose central contribution rests on the rewritten prose and VT result.

**Required fix**: extend `reproduce.py` or add a dedicated IJF reproduce checker that gates `body_v_ijf.tex` claims directly, including the N=14 MDD-volatility correlation, 6/6 OOS classification, VIX-lagged comparison, and VT native/common-window sensitivity.

### H3. Allocation timing notation remains under-specified

Forecast timing is clean for QLIKE:

- `body_v_ijf.tex:192`: estimates on `[t-w, t-1]`, forecast target `t`, no look-ahead.

But the allocation equation is still written as a contemporaneous weight:

- `body_v_ijf.tex:231`: `w_t = sigma_target / hat_sigma_t`.
- `body_v_ijf.tex:233`: says the same forecasts feed QLIKE and targeting weights, but does not define traded return timing.

The VIX subsection correctly warns about same-day bias:

- `body_v_ijf.tex:263`: VIX weights are lagged; same-day use inflates Sharpe.

The GARCH VT section should be equally explicit, e.g. `w_{t-1} r_t` or `w_t r_{t+1}` with forecast-origin notation.

**Required fix**: add the exact traded-return equation and align GARCH/VIX timing conventions in one place.

## Medium Findings

### M1. The compiled page count differs from the pipeline status

The task/status text said `main_v_ijf.tex` compiles to 26 pages. Recompilation now produces 35 pages under `elsarticle[review]`:

- `latexmk ... main_v_ijf.tex`: exit 0, PDF 35 pages.
- `pdfinfo main_v_ijf.pdf`: 35 pages.

This is not a journal-cap blocker for IJF, but the pipeline status was stale. It is now recorded in the review.

### M2. Figure window is ambiguous against the 504-day gamma method

Table `tab:gamma` and the model-selection discussion use 504-day windows:

- `tables_main.tex:24`.
- `body_v_ijf.tex:247`.

Figure caption says rolling 252-day gamma estimates:

- `body_v_ijf.tex:285`.

This may be intentionally illustrative, but the paper should say why the figure uses 252 days while the formal table/rule uses 504 days.

## Positive Checks

- `main_v_ijf.tex` compiles with no undefined refs/cites.
- Abstract is within IJF target length: 143 words.
- Contribution framing is materially improved: complexity ceiling leads; taxonomy is interpretive/supporting.

## Bottom Line

The manuscript is not ready to advance. The prose-level reframe is directionally right, but the allocation evidence and reproducibility gate still lag the claim.
