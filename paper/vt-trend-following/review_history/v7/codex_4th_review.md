# Codex 4th-Model Adversarial Review — v7 README

**Timestamp**: 2026-06-30 13:12 台灣時間
**Codex version**: codex-cli 0.142.3
**Target**: paper/vt-trend-following/review_history/v7/README.md (+ K1458 README + body_v3.tex)
**Predecessor**: v6 codex_3rd_review.md (Verdict: FAIL, 5 findings)

---

## Verdict: CONDITIONAL_PASS

All numeric fixes requested by v6 are verifiable, and the paper body no longer makes the K1458 trough-window paragraph read like direct MDD-path proof. However, the K1458 experiment README still contains two uncaveated MDD-path attribution sentences, so v6 Finding 2 is only partially resolved at the documentation layer.

---

## Verification of v6 findings

### Finding 1 (CRITICAL) — RESOLVED

K1458 README now states the additive identity explicitly at `experiments/k1458_h1_trough_decomposition/README.md:26-42`:

```text
Daily:    PureVT_excess_t  =  VIX_timing_contrib_t  +  TSMOM_hedge_contrib_t
Window:   sum(PureVT_excess) =  sum(VIX_timing)     +  sum(TSMOM_hedge_full)
```

It also explicitly warns that `VIX_timing_contrib` is not equal to `PureVT_excess_vs_BH` except when `TSMOM_hedge_full = 0` (`README.md:35`). The SPY 2020-03 row is numerically correct against `k1458_results.json`:

```text
jq '.per_asset.SPY[1].headline' experiments/k1458_h1_trough_decomposition/k1458_results.json
pure_vt_excess_bh_total_arith = 0.037654210238158604
vix_timing_total_arith        = -0.08433252915648443
tsmom_hedge_total_arith       = 0.12198673939464298

sum = -0.08433252915648443 + 0.12198673939464298
    = 0.037654210238158556
diff vs pure = -4.85722573273506e-17
```

This matches the README table line `+0.0377 = -0.0843 + 0.1220` (`README.md:37-40`) up to rounding.

### Finding 2 (HIGH) — PARTIALLY

The body-level K1458 paragraph is now appropriately scoped. `paper/vt-trend-following/body_v3.tex:258` says the K1458 trough-window arithmetic is "descriptive evidence rather than a direct PureVT-versus-buy-and-hold drawdown-path attribution." That directly addresses the v6 concern that K1458 itself does not measure the PureVT-vs-BH MDD path.

But the K1458 README still retains uncaveated path-attribution language:

- `experiments/k1458_h1_trough_decomposition/README.md:80`: "its MDD retention comes from not falling as deeply at the BH trough, not from rebounding faster."
- `experiments/k1458_h1_trough_decomposition/README.md:86`: "MDD retention is about lower drawdown peak depth, not rebound-period profit."

Those two sentences are stronger than the JSON supports. K1458 observes trough-window arithmetic around BH troughs; it does not directly decompose the synchronized PureVT/BH MDD path. This is not a blocker for the body after line 258, but the experiment README should be tightened before treating the v7 package as fully clean.

### Finding 3 (HIGH) — RESOLVED

The old `NO (CLEARED)` / "no mechanical hedge" conclusion is gone from the body and from the active K1458 interpretation. The body now states the 2009 result with the required nuance: "three of five assets show zero hedge contribution and the remaining two are small and of mixed sign" and "neither can it be declared entirely absent in 2009" (`body_v3.tex:258`).

The K1458 README also reports the mixed 2009 evidence rather than clearing the concern: 3 clipped assets at zero and 2 nonzero assets, 50/50 SPY/GLD `+0.021` and QQQ `-0.035` (`experiments/k1458_h1_trough_decomposition/README.md:67-69`). I found no remaining `NO (CLEARED)` phrasing.

### Finding 4 (MEDIUM) — RESOLVED

The beta-clip claim is now conditional and tied to observable JSON evidence. The README correctly labels the evidence as indirect because the beta path is not stored (`experiments/k1458_h1_trough_decomposition/README.md:67`).

The requested jq verification confirms the 3/5 zero-hedge claim:

```text
jq -r '.per_asset | to_entries
  | map({asset:.key, hedge:.value[0].headline.tsmom_hedge_total_arith,
         neg:.value[0].tsmom_neg_partition.tsmom_hedge.sum_arith_return,
         nonneg:.value[0].tsmom_nonneg_partition.tsmom_hedge.sum_arith_return})
  | (map(select(.hedge==0)) | length) as $zero
  | "zero_count=\($zero)/\(length)", (.[] | "\(.asset): hedge=\(.hedge), neg=\(.neg), nonneg=\(.nonneg)")' \
  experiments/k1458_h1_trough_decomposition/k1458_results.json

zero_count=3/5
SPY: hedge=0, neg=0, nonneg=0
50/50: hedge=0.021107601066936293, neg=0.11914442745927381, nonneg=-0.09803682639233752
DIA: hedge=0, neg=0, nonneg=0
QQQ: hedge=-0.03500289511543407, neg=0.03262772268716604, nonneg=-0.0676306178026001
IWM: hedge=0, neg=0, nonneg=0
```

The narrower user-requested query on `per_asset.{SPY,DIA,IWM}[0].headline.tsmom_hedge_total_arith` returns `SPY 0`, `DIA 0`, `IWM 0`. Because the partition sums are also zero for those three assets, the README's "not merely sum-to-zero coincidence" caveat is reasonable, while still correctly conditional on not having the stored beta path.

### Finding 5 (MEDIUM) — RESOLVED

The body no longer contains the specific closure markers flagged in v6. Search hits for `CLOSURE`, `CLEARED`, `確實有貢獻`, and `proves` in `body_v3.tex` did not find the prior closure-style language. The remaining `proof` hits are negative qualifiers such as "not as proof" (`body_v3.tex:34`, `body_v3.tex:254`).

The K1458 paragraph at `body_v3.tex:258` is now descriptive/conditional for the trough-window evidence. The discussion paragraph at `body_v3.tex:528` still uses synthesis language ("Our decomposition shows", "This confirms"), but it is attached to K1376/K1192/K687 aggregate evidence rather than the K1458 H1 trough-window claim, and it includes the required caution that `>100%` estimates are not a license to claim standalone insurance.

---

## New findings (if any)

### New Finding A (LOW) — v7 self-audit overstates line 528's wording

`paper/vt-trend-following/review_history/v7/README.md:53` says body line 258 plus line 528 use "descriptive" and conditional language. Line 258 does; line 528 does not use "descriptive" language and instead says "Our decomposition shows" and "This confirms" (`body_v3.tex:528`). I do not treat this as a substantive HIGH issue because line 528 is not the K1458 trough-window attribution, but the self-audit should not overclaim what the line literally says.

### New Finding B (LOW) — stale "closure verdict" appears only inside historical run command

`experiments/k1458_h1_trough_decomposition/README.md:109` still contains "H1 closure verdict" inside a compute-queue follow-up command string. This is not active manuscript narrative, so I am not carrying it as v6 Finding 5 unresolved. It should still be removed opportunistically to avoid reintroducing closure framing in future generated tasks.

---

## Recommendation

hold for v8

Minimum v8 change: qualify `experiments/k1458_h1_trough_decomposition/README.md:80` and `:86` so they say the "not falling as deeply / lower drawdown peak depth" interpretation is an inference from trough-window arithmetic, not a direct MDD-path decomposition. After that, the package can advance to `ready_for_submission_candidate` from this review's perspective.
