# Paper 9 (garch-x-vix) — Codex Adversarial Review v7

**Date**: 2026-06-05  
**Reviewer**: Codex GPT-5 (adversarial mode)  
**Scope**: current `main.tex` + replication-facing metadata after v6 fixes

## Verdict

`revision_required`

The paper body is materially improved versus v2/v3: MCS caveat, HAR-RV benchmark, and leave-COVID-out robustness are now present. The remaining problems are narrower but still reviewer-visible because they concern claim precision and replication packet consistency.

## Findings

### 1. Replication-facing metadata is still stale and contradicts the current paper framing

**Severity**: high

`paper/garch-x-vix/README.md` still presents the old headline "`DM t=4.03` ... outperforming all GARCH-MIDAS variants" and lists K1085 as if it were the source of the GLD cross-asset claim, while the current body explicitly frames B1 as statistically indistinguishable and uses the paper-period GLD result `t=3.17` from K997. See [README.md](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/README.md:12), [README.md](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/README.md:37), [README.md](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/README.md:61), and [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:80). `reproduce_report.json` also still marks the core SPY number as a mismatch (`4.03` paper vs `4.148384` stored/live), so a reviewer reading the replication packet sees unresolved internal conflict rather than a controlled shelf erratum. See [reproduce_report.json](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/reproduce_report.json:1).

**Why it matters**: this is no longer just an internal ops note. For an R1 package, conflicting “canonical” numbers and claim wording in the README/reproduce files weaken credibility even if the body text is now more careful.

**Required fix**: align README/reproduce metadata to the current paper stance: distinguish paper-frozen values from snapshot reruns, and stop using “outperforming all GARCH-MIDAS variants” outside the qualified point-estimate sense.

### 2. “Statistically non-inferior” is too strong for the HAR-RV section as written

**Severity**: medium-high

The HAR section reports only ordinary DM non-rejections (`t=+0.29`, `t=+0.65`, `t=+0.87`, `t=-0.88`) but then concludes that A4f is “statistically non-inferior” to HAR-type benchmarks. See [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:806) and [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:813). The underlying experiments, [k1379_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1379/k1379_results.json:1) and [k1396_results.json](/Users/yhlai0911/Desktop/volpred-research/experiments/k1396/k1396_results.json:1), support only “no statistically significant difference under this protocol.” They do not implement a non-inferiority margin or equivalence design.

**Why it matters**: a referee can reasonably object that failure to reject equality is not evidence of non-inferiority. This is a terminology problem, not a computation problem.

**Required fix**: replace “statistically non-inferior” with “not statistically distinguishable under these comparisons” unless a formal non-inferiority setup is added.

### 3. The paper still conflates actual `g_t` with the `g`-proxy used for the 0.80 VRP correlation

**Severity**: medium-high

The abstract, introduction, and conclusion say that “the `g_t` component” tracks VRP at `rho≈0.80`; however, Section 6 later states that model-recursion `g_t` is approximately orthogonal to VRP (`rho≈0.06`) and that the high correlation comes from a separate “g-proxy method.” See [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:52), [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:82), [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:893), and [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:909).

**Why it matters**: this reads as a construct switch. A reviewer can say the paper advertises a property of latent `g_t` but later concedes the reported 0.80 belongs to a derived proxy, not the recursion state itself.

**Required fix**: make the object explicit everywhere. If the result is about a proxy, say “`g`-proxy derived from the multiplicative decomposition” in the abstract/introduction/conclusion, and reserve `g_t` for the latent recursion state.

### 4. The conclusion still overstates cross-asset generalization relative to the paper’s own stricter caveat

**Severity**: medium

The conclusion says the model is significant for “five of seven tested markets” and that VIX functions as a “global fear factor.” See [main.tex](/Users/yhlai0911/Desktop/volpred-research/paper/garch-x-vix/main.tex:911). But v6 already added the stricter Bonferroni note that GLD (`t=3.17`) falls marginally below the adjusted `|t|>3.22` threshold. The table caveat and the conclusion are not aligned.

**Why it matters**: even if the main table is technically correct under the paper’s baseline threshold, the conclusion currently ignores the paper’s own more conservative multiple-testing qualification.

**Required fix**: soften the conclusion to “four of seven under a conservative Bonferroni adjustment, five of seven under the baseline Harvey screen” or equivalent.

## Overall assessment

This is no longer a “core model invalid” paper-review situation. The remaining work is mostly claim discipline and packet consistency. But these are exactly the kinds of inconsistencies reviewers notice quickly because they require no rerun to detect.
