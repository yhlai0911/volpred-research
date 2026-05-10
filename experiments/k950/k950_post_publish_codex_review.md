# K950 Post-Publish Review — mile_06d37aff

**Article**: 「VIX 看盤切換股債權重，能跨市場用嗎？我們在 5 個市場 0/5 PASS」
**Article id**: `mile_06d37aff`
**Published**: 2026-05-09T07:44:32+00:00
**Review date**: 2026-05-11
**Reviewer source**: **Main-thread structured audit (fallback)** — Codex CLI primary path attempted but blocked by daily usage limit (resets 2026-05-12 19:46 PT)
**Re-verify queued**: Yes — primary-path Codex review to re-run after 2026-05-13 per K1259 rule (subagent/fallback PASS ≠ primary Codex PASS)

---

## Verdict: **CONDITIONAL PASS (fallback)**

CONDITIONAL because the verdict comes from a fallback path. **No content-level issues found**; numerical claims byte-for-byte match `k950_results.json`, lookahead protection is correctly implemented, and methodology claims match the source code. The CONDITIONAL flag is purely workflow-bureaucratic (per K1259) and will lift once Codex primary path re-verifies.

---

## Reviewer-source diagnostic (why fallback)

```
$ codex --version  → codex-cli 0.121.0
$ codex login status  → Logged in using ChatGPT
$ cat ~/.codex/config.toml  → model = "gpt-5.4"
$ codex exec ... → "ERROR: You've hit your usage limit. ... try again at May 12th, 2026 7:46 PM."
```

CLI / auth / model config all healthy; only the per-account ChatGPT daily quota is exhausted. Brief explicitly authorised fallback in this scenario.

---

## Findings by checklist item

### 1. Byte-for-byte numerical accuracy — PASS

All five markets verified against `experiments/k950/k950_results.json`:

| Market    | Field            | Article | JSON   | Match |
|-----------|------------------|---------|--------|-------|
| SPY+GLD   | BH Sharpe        | 0.833   | 0.833  | ✓     |
| SPY+GLD   | VT net Sharpe    | 0.806   | 0.806  | ✓     |
| SPY+GLD   | ΔSharpe          | −0.027  | −0.027 | ✓     |
| SPY+GLD   | BH MDD           | −32.49% | −32.49 | ✓     |
| SPY+GLD   | VT MDD           | −30.94% | −30.94 | ✓     |
| SPY+GLD   | weight_changes   | 69      | 69     | ✓     |
| QQQ+GLD   | (all 6 fields)   | match   | match  | ✓     |
| 0050+GLD  | VT Sharpe        | 0.890   | 0.89   | ✓     |
| 0050+GLD  | weight_changes   | 66      | 66     | ✓     |
| EWJ+GLD   | (all 6 fields)   | match   | match  | ✓     |
| FEZ+GLD   | (all 6 fields)   | match   | match  | ✓     |
| (summary) | 0/5 VT wins      | 0/5     | 0/5    | ✓     |
| (summary) | best ΔSharpe     | SPY+GLD −0.027 | SPY+GLD −0.027 | ✓ |
| (summary) | worst ΔSharpe    | FEZ+GLD −0.111 | FEZ+GLD −0.111 | ✓ |

No numerical discrepancies.

### 2. Lookahead audit — PASS

`experiments/k950/k950.py` L138–L153:
```
for date in common_idx:
    valid_vix = vix_monthly.loc[:date]          # uses VIX up to & incl date
    ...
    weights[date] = regime_weight(valid_vix.iloc[-1])
weights = weights.shift(1)                      # CRITICAL: t-1 → t lag
```

- Without the shift, day-1-of-month would use that day's month-start VIX directly → 1-day leak.
- L152 `shift(1)` correctly pushes the signal series forward by one trading day, so weight applied to day-t return = signal computed on day-(t-1). **Lookahead correctly prevented.**
- Article footer also explicitly states `signal.shift(1)` 防前瞻 — claim matches code.

### 3. Regime VT methodology checks — PASS

- Thresholds VIX<15→80%, VIX≥25→30%, else 50%: code L51–L59 matches article description.
- Transaction cost: code L167 uses `|Δw| * (cost_bps/10000) * 2`. Article says "10bps single-side". The 2× factor models one buy + one sell (equity leg + safe leg), each charged 10bps. A 0.5 weight swing → 0.5 × 0.001 × 2 = 10bps drag on portfolio = correct under "single-side" framing. **Not overstated.**
- 0050.TW pre-2014 1:4 split correction (L82–L96) is a methodological choice but does not bias the cross-asset comparison since it's applied consistently to BH and VT for that market.

### 4. DM / Harvey overclaim check — PASS

Article uses words "0/5 PASS", "乾淨 NULL", "報酬輸 5/5" descriptively. **No claim of DM / Harvey / Patton statistical significance anywhere in the body.** The article explicitly relies on a heuristic argument ("運氣可以解釋一兩個負值，沒辦法解釋 5/5 都負") rather than formal multiple-testing-corrected inference. This is the **correct** level of claim given that `k950_results.json` has no DM block. **No overclaim.**

### 5. Multiple-testing / sample-period robustness — PASS

- Parameters (15/25/80/50/30) are inherited from K946 (pre-specified), not tuned per market. Article frames it as "把同一套規則搬到" (transplanting). MT concern is therefore mild.
- 0050+GLD sample is 14.9y (starts ~2010-12) vs 17.4y for others. Article Table 1 in Section 1 explicitly discloses "0050+GLD ... 約 2010-12 起 ... 約 14.9 年". **Properly disclosed.**

### 6. Cross-reference integrity — PASS

- **K949**: Article claims "4/5 個市場 PASS ... SPY、FEZ、EWG、EWJ". Verified against `experiments/k949/k949_results.json` → `n_significant_harvey3: 4` and the 4 significant markets list matches. ✓
- **K687 / K688**: Cited as context (~50% VT win rate; CRRA positive for γ≥5). Not independently re-verified in this review — but article does not cite specific numbers from these K's, only qualitative direction.

### 7. Other red flags — PASS

- ✓ `.shift(1)` present (see item 2)
- ✓ No future-derived sample boundaries (period hardcoded as 2008-01 to 2025-12, applied uniformly)
- ✓ BH 50/50 with annual rebalance baseline is the same comparator used in K946/K687 — consistent within the platform's VT research line, not cherry-picked for this article
- ✓ mile_06d37aff unique in feed.json (1 occurrence)

---

## Issues found

| Severity | Issue |
|----------|-------|
| BLOCKER  | (none) |
| MAJOR    | (none) |
| MINOR    | (none) |
| NIT      | Code comment at L165–L167 says "each weight change costs 2 * cost_bps (buy + sell)" — the comment is correct but a future reader may want a footnote because some industry conventions instead define round-trip cost as |Δw|*bps not 2*|Δw|*bps. Not material; documentation polish only. |

---

## Executive summary (for knowledge.json)

K950 mile_06d37aff post-publish review (main-thread fallback, Codex quota-blocked 2026-05-11): CONDITIONAL PASS. All 30+ numerical claims byte-for-byte match `k950_results.json`; lookahead protection via `weights.shift(1)` (k950.py L152) correctly prevents same-day VIX leakage; no DM/Harvey overclaim (descriptive NULL framing, no significance test cited); cross-reference to K949 4/5 PASS verified; transaction cost interpretation reasonable (2× factor = two-leg single-side 10bps). Zero BLOCKER/MAJOR/MINOR issues; one NIT on cost-convention documentation polish. Reviewer-source is **main-thread fallback** (not primary Codex) per K1259 rule — re-verify with primary-path Codex queued for post-2026-05-13 when quota resets.
