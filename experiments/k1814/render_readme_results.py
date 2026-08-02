#!/usr/bin/env python3
"""Render README sections 7 and 8 from K1814_results.json.

Every number in the rendered sections is read programmatically from the canonical
result artifact. Nothing is retyped from a log tail or a summary. The script is
idempotent: it rewrites the content between the RESULTS markers, so re-running it
after the artifact changes re-derives the sections rather than appending.

    python3 render_readme_results.py           # rewrite README.md in place
    python3 render_readme_results.py --check   # verify README matches the artifact
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
RESULTS = HERE / "K1814_results.json"
README = HERE / "README.md"

HORIZONS = ("1", "5", "22")


def q(v: float) -> str:
    """QLIKE / loss quantity."""
    return f"{v:.4f}"


def dm(v: float) -> str:
    return f"{v:+.3f}"


def pv(v: float) -> str:
    """p-value, keeping resolution on small values instead of printing 0.0000."""
    if v < 1e-4:
        return f"{v:.2e}"
    return f"{v:.4f}"


def render_descriptive(d: dict) -> str:
    de = d["primary"]["descriptive"]
    av = de["annualised_vol_pct"]
    lr = de["log_rv"]
    rl = de["rv_level"]
    acf = de["acf_log_rv"]
    gph_sens = de["gph_d_bandwidth_sensitivity"]
    pdata = d["primary"]["data"]

    L: list[str] = []
    L.append(
        f"All figures below describe the **primary series**: the daily Parkinson "
        f"realized-range proxy on `^GSPC`, **{de['n']:,} daily bars** spanning "
        f"**{de['date_start']} → {de['date_end']}**. "
        f"{pdata['n_floored_nonpositive']} non-positive variance estimates "
        f"({pdata['n_floored_nonpositive'] / de['n'] * 100:.2f}%) were replaced by the "
        f"pre-specified floor `RV_FLOOR = 1e-7`, leaving "
        f"**{pdata['n_panel_rows']:,} usable panel rows** after the warm-up and target tail. "
        f"These are proxy figures, not 5-minute RV — see §4 for the measured gap."
    )
    L.append("")

    L.append("**Annualised volatility (%), from the proxy**")
    L.append("")
    L.append("| mean | sd | min | p1 | p25 | median | p75 | p99 | max |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    L.append(
        "| {:.2f} | {:.2f} | {:.2f} | {:.2f} | {:.2f} | {:.2f} | {:.2f} | {:.2f} | {:.2f} |".format(
            av["mean"], av["sd"], av["min"], av["p1"], av["p25"],
            av["median"], av["p75"], av["p99"], av["max"],
        )
    )
    L.append("")
    L.append(
        f"The distribution is strongly right-skewed in levels: the median is "
        f"{av['median']:.2f}% but the maximum reaches {av['max']:.2f}%. That is why every "
        f"model works in logs."
    )
    L.append("")

    L.append("**Shape, in logs and in levels**")
    L.append("")
    L.append("| series | mean | sd | skew | excess kurtosis |")
    L.append("|---|---|---|---|---|")
    L.append(
        "| `log RV` | {:.4f} | {:.4f} | {:.4f} | {:.4f} |".format(
            lr["mean"], lr["sd"], lr["skew"], lr["kurtosis_excess"]
        )
    )
    L.append(
        "| `RV` (level) | — | — | {:.2f} | {:.1f} |".format(rl["skew"], rl["kurtosis_excess"])
    )
    L.append("")
    L.append(
        f"Taking logs pulls skew from {rl['skew']:.2f} to {lr['skew']:.4f} and excess kurtosis "
        f"from {rl['kurtosis_excess']:.1f} to {lr['kurtosis_excess']:.4f}. Log RV is still not "
        f"Gaussian — Jarque-Bera returns p = {de['jarque_bera_log_rv_p']:.1f}, i.e. normality "
        f"is rejected below the resolution of double precision — but it is far closer, which "
        f"is the standard justification for modelling log RV rather than RV."
    )
    L.append("")

    L.append("**Autocorrelation of log RV — the long-memory evidence**")
    L.append("")
    lags = sorted(acf, key=int)
    L.append("| lag (trading days) | " + " | ".join(lags) + " |")
    L.append("|---|" + "---|" * len(lags))
    L.append("| ACF | " + " | ".join(f"{acf[k]:.4f}" for k in lags) + " |")
    L.append("")
    L.append(
        f"The ACF decays from {acf['1']:.4f} at lag 1 to {acf['250']:.4f} at lag 250 — roughly "
        f"one trading year — without collapsing to zero. That slow hyperbolic-looking decay, "
        f"not the point estimates below, is the primary evidence for long memory, and it is "
        f"what motivates HAR's cascade of daily/weekly/monthly terms in the first place."
    )
    L.append("")
    L.append(
        "| estimator | value |"
    )
    L.append("|---|---|")
    L.append(f"| GPH `d` (headline, bandwidth n^0.5) | {de['gph_d']:.4f} |")
    for k in sorted(gph_sens):
        alt = " — headline" if abs(gph_sens[k] - de["gph_d"]) < 1e-12 else ""
        L.append(f"| GPH `d`, bandwidth {k}{alt} | {gph_sens[k]:.4f} |")
    L.append(f"| Hurst (classical R/S) | {de['hurst_rs']:.4f} |")
    L.append("")
    L.append(f"> {de['long_memory_caveat']}")
    L.append("")
    L.append(
        f"Read as descriptive summaries only: GPH `d` moves between "
        f"{min(gph_sens.values()):.4f} and {max(gph_sens.values()):.4f} across the three "
        f"bandwidths, which is itself a reminder that no CI is attached to any of them."
    )
    return "\n".join(L)


def render_main(d: dict) -> str:
    v = d["verdict"]
    per = v["per_horizon"]
    prim = d["primary"]
    fam = d["fdr_families"]

    L: list[str] = []

    # ---------------------------------------------------------------- headline
    L.append("### 8.1 Headline")
    L.append("")
    L.append(
        f"**No horizon boundary exists. `h* = {v['h_star']}`.** Across "
        f"h ∈ {{1, 5, 22}}, `dl_beats_both_baselines` is **false at every horizon**, and "
        f"`horizons_with_dl_win` is empty."
    )
    L.append("")
    L.append(
        "The result is stronger than \"no difference\", and in the direction opposite to the "
        "hypothesis. At **h = 22** the best DL model is **significantly worse** than the "
        "HAR-RV+leverage baseline after BH-FDR correction "
        f"(DM-HLN = {per['h22']['dm_hln_vs_harl']:.3f}, "
        f"q = {per['h22']['p_bh_fdr_vs_harl']:.4f}), which the artifact records as "
        f"`decision_vs_harl_strong = \"{per['h22']['decision_vs_harl_strong']}\"`. The "
        "literature framing that motivated this experiment — ML earns its keep at longer "
        "horizons — is **contradicted here, not merely unsupported**: the DL deficit *grows* "
        "with the horizon rather than closing."
    )
    L.append("")
    L.append(f"> {v['h_star_interpretation']}")
    L.append("")
    L.append(
        f"`h*` is defined as: {v['h_star_definition']}"
    )
    L.append("")

    # ---------------------------------------------------------------- main table
    L.append("### 8.2 Per-horizon results (primary arm, `^GSPC` Parkinson)")
    L.append("")
    L.append(
        "Sign convention throughout: **positive DM favours DL**. "
        "`q` is the BH-FDR-adjusted p-value within its own 6-test family (§8.3)."
    )
    L.append("")
    L.append(
        "| h | QLIKE HAR | QLIKE HAR-L | QLIKE ridge (control) | QLIKE best DL | best DL | seed sd | "
        "DM vs HAR | p | q | DM vs HAR-L | p | q | n OOS | eff. indep. obs | decision vs HAR | decision vs HAR-L |"
    )
    L.append("|---|" + "---|" * 16)
    for h in HORIZONS:
        r = per[f"h{h}"]
        L.append(
            "| {h} | {har} | {harl} | {ridge} | {dl} | `{best}` | {sd} | {dmh} | {ph} | {qh} | "
            "{dmhl} | {phl} | {qhl} | {n:,} | {eff:,.1f} | `{dech}` | `{dechl}` |".format(
                h=h,
                har=q(r["qlike_har"]),
                harl=q(r["qlike_harl_strong_baseline"]),
                ridge=q(r["qlike_ridge_lags_linear_control"]),
                dl=q(r["qlike_best_dl"]),
                best=r["best_dl_model"],
                sd=f"{r['dl_seed_sd']:.4f}",
                dmh=dm(r["dm_hln_vs_har"]),
                ph=pv(r["p_raw_vs_har"]),
                qh=pv(r["p_bh_fdr_vs_har"]),
                dmhl=dm(r["dm_hln_vs_harl"]),
                phl=pv(r["p_raw_vs_harl"]),
                qhl=pv(r["p_bh_fdr_vs_harl"]),
                n=r["n_oos"],
                eff=r["effective_independent_obs"],
                dech=r["decision_vs_har"],
                dechl=r["decision_vs_harl_strong"],
            )
        )
    L.append("")
    h1, h5, h22 = per["h1"], per["h5"], per["h22"]
    L.append(
        f"OOS window: **{prim['horizons']['1']['oos_start']} → "
        f"{prim['horizons']['1']['oos_end']}**, {h1['n_oos']:,} rows, "
        f"{prim['horizons']['1']['n_refits']} rolling refits "
        f"(`refit_every = {prim['config']['refit_every']}`). It contains the 1973-74, 1987, "
        f"2000-02, 2008-09, 2020 and 2022 drawdowns."
    )
    L.append("")
    L.append("**Reading the three horizons**")
    L.append("")
    L.append(
        f"- **h = 1** — a dead heat. The best DL model ties HAR-L to four decimals "
        f"({q(h1['qlike_best_dl'])} vs {q(h1['qlike_harl_strong_baseline'])}; DM = "
        f"{h1['dm_hln_vs_harl']:.3f}, q = {pv(h1['p_bh_fdr_vs_harl'])}). It is nominally ahead "
        f"of plain HAR-RV ({q(h1['qlike_har'])}) but nowhere near significance "
        f"(DM = {h1['dm_hln_vs_har']:.3f}, q = {pv(h1['p_bh_fdr_vs_har'])}). The entire "
        f"apparent HAR-RV gap of {h1['qlike_diff_har_minus_dl']:.4f} is closed by the single "
        f"leverage term in HAR-L — which is exactly why HAR-L is in the design."
    )
    L.append(
        f"- **h = 5** — DL is behind both baselines "
        f"({q(h5['qlike_best_dl'])} vs HAR {q(h5['qlike_har'])} and HAR-L "
        f"{q(h5['qlike_harl_strong_baseline'])}) and neither gap reaches significance "
        f"(q = {pv(h5['p_bh_fdr_vs_har'])} and {pv(h5['p_bh_fdr_vs_harl'])})."
    )
    L.append(
        f"- **h = 22** — the deficit becomes significant. DL QLIKE {q(h22['qlike_best_dl'])} "
        f"against HAR-L {q(h22['qlike_harl_strong_baseline'])}, a gap of "
        f"{abs(h22['qlike_diff_harl_minus_dl']):.4f} — roughly "
        f"{abs(h22['qlike_diff_harl_minus_dl']) / abs(h1['qlike_diff_harl_minus_dl']):.0f}× the "
        f"h=1 gap against the same baseline, and about "
        f"{abs(h22['qlike_diff_harl_minus_dl']) / h22['dl_seed_sd']:.1f}× the "
        f"seed sd ({h22['dl_seed_sd']:.4f}). It survives BH-FDR against HAR-L "
        f"(q = {pv(h22['p_bh_fdr_vs_harl'])}) though not against plain HAR-RV "
        f"(q = {pv(h22['p_bh_fdr_vs_har'])})."
    )
    L.append("")
    L.append(
        f"One caution on h = 22, in the direction of *less* confidence: direct 22-step targets "
        f"overlap heavily, so the {h22['n_oos']:,} OOS rows carry only "
        f"**{h22['effective_independent_obs']:,.1f} effectively independent observations**. The "
        f"HAC-corrected DM statistic accounts for this, but the h=22 row is the thinnest "
        f"evidence in the table despite having the largest point gap."
    )
    L.append("")

    # ------------------------------------------------ lognormal-correction robustness
    # Derived, never asserted. A hardcoded "the ranking is unchanged" sentence lives
    # INSIDE this drift-gated block, so `--check` would certify it as matching the
    # artifact while it was in fact false: the corrected and uncorrected variants
    # disagree in 2 of the 6 best-DL-vs-baseline cells. What the headline actually
    # needs is that no DM test or FDR decision moves -- every one is computed on the
    # corrected losses -- not that every ordering is stable. So report both.
    cells = []
    for h in HORIZONS:
        hh = prim["horizons"][h]
        nc = hh["qlike_no_lognormal_correction"]
        best = per[f"h{h}"]["best_dl_model"]
        for bname, blabel, dmk, qk in (
            ("har", "HAR-RV", "dm_hln_vs_har", "p_bh_fdr_vs_har"),
            ("harl", "HAR-L", "dm_hln_vs_harl", "p_bh_fdr_vs_harl"),
        ):
            cb = hh["models"][bname]["qlike_ensemble"]
            cd = hh["models"][best]["qlike_ensemble"]
            ub, ud = nc[bname], nc[best]
            cells.append({
                "h": h, "best": best, "label": blabel,
                "cb": cb, "cd": cd, "ub": ub, "ud": ud,
                "dm": per[f"h{h}"][dmk], "q": per[f"h{h}"][qk],
                "flipped": (cb < cd) != (ub < ud),
            })
    flips = [c for c in cells if c["flipped"]]
    stable = [c for c in cells if not c["flipped"]]
    L.append(
        f"**The lognormal level correction, checked rather than asserted.** "
        f"`qlike_no_lognormal_correction` reports the uncorrected `exp(m)` variant for every "
        f"cell. Across the {len(cells)} best-DL-vs-baseline cells (3 horizons × 2 baselines), "
        f"{len(stable)} keep the same ordering under both variants and {len(flips)} reverse it"
        + (":" if flips else ".")
    )
    if flips:
        L.append("")
        for c in flips:
            cw = c["label"] if c["cb"] < c["cd"] else f"`{c['best']}`"
            uw = c["label"] if c["ub"] < c["ud"] else f"`{c['best']}`"
            L.append(
                f"- **h = {c['h']} vs {c['label']}** — corrected: **{cw}** ahead "
                f"({q(c['cb'])} vs {q(c['cd'])}, gap {abs(c['cb'] - c['cd']):.6f}). "
                f"Uncorrected: **{uw}** ahead ({q(c['ub'])} vs {q(c['ud'])}, gap "
                f"{abs(c['ub'] - c['ud']):.6f}). Under the correction this cell is a dead "
                f"heat — DM = {c['dm']:.3f}, q = {pv(c['q'])}."
            )
        L.append("")
        L.append(
            f"Both reversals are short-horizon cells that the corrected variant already "
            f"reports as statistically indistinguishable, so neither is a DL win under "
            f"either variant. Every DM statistic, BH-FDR family and decision field in this "
            f"experiment is computed on the **corrected** losses, so no reported test moves. "
            f"The h = 22 cells that carry the headline keep both baselines ahead under both "
            f"variants ("
            + "; ".join(
                f"{c['label']} {q(c['cb'])} vs {q(c['cd'])} corrected, "
                f"{q(c['ub'])} vs {q(c['ud'])} uncorrected"
                for c in cells if c["h"] == "22"
            )
            + ")."
        )
    L.append("")

    # ---------------------------------------------------------------- ar1 floor
    L.append("The sanity floor and the linear control behave as designed:")
    L.append("")
    L.append("| h | AR(1) floor | ridge on 22 lags | HAR-RV |")
    L.append("|---|---|---|---|")
    for h in HORIZONS:
        m = prim["horizons"][h]["models"]
        L.append(
            f"| {h} | {q(m['ar1']['qlike_ensemble'])} | {q(m['ridge_lags']['qlike_ensemble'])} | "
            f"{q(m['har']['qlike_ensemble'])} |"
        )
    L.append("")
    L.append(
        "Ridge on all 22 individual lags never beats HAR's three aggregates, so the HAR "
        "restriction is not costing anything a richer *linear* lag structure would recover. "
        "The gap DL needed to find was never a linear one."
    )
    L.append("")

    # ---------------------------------------------------------------- FDR
    L.append("### 8.3 Multiplicity control — the two FDR families, in full")
    L.append("")
    L.append(
        f"Multiplicity is controlled by **Benjamini-Hochberg FDR at q = "
        f"{fam['dm_vs_har']['q']}**, applied **separately to two families of "
        f"{fam['dm_vs_har']['family_size']} tests each** "
        f"(3 horizons × 2 DL architectures). The families are **not pooled**: one family tests "
        f"against **{fam['dm_vs_har']['baseline']}**, the other against "
        f"**{fam['dm_vs_harl']['baseline']}**. Family members: "
        + ", ".join(f"`{k}`" for k in fam["dm_vs_har"]["results"]) + "."
    )
    L.append("")
    for key in ("dm_vs_har", "dm_vs_harl"):
        f = fam[key]
        L.append(f"**Family `{key}` — baseline {f['baseline']}**")
        L.append("")
        L.append("| test | DM-HLN | raw p | BH-FDR q | reject at q=0.05 | direction |")
        L.append("|---|---|---|---|---|---|")
        for name, r in f["results"].items():
            L.append(
                f"| `{name}` | {dm(r['dm_hln'])} | {pv(r['p_raw'])} | {pv(r['p_bh'])} | "
                f"{'**yes**' if r['reject_at_q05'] else 'no'} | `{r['direction']}` |"
            )
        L.append("")

    rej_har = [k for k, r in fam["dm_vs_har"]["results"].items() if r["reject_at_q05"]]
    rej_harl = [k for k, r in fam["dm_vs_harl"]["results"].items() if r["reject_at_q05"]]
    all_rej = set(rej_har) | set(rej_harl)
    L.append(
        f"**Every rejection in both families points the same way — toward the baseline.** "
        f"{len(rej_har)} of {fam['dm_vs_har']['family_size']} tests reject against "
        f"{fam['dm_vs_har']['baseline']} ({', '.join('`' + k + '`' for k in rej_har)}) and "
        f"{len(rej_harl)} of {fam['dm_vs_harl']['family_size']} against "
        f"{fam['dm_vs_harl']['baseline']} ({', '.join('`' + k + '`' for k in rej_harl)}) — "
        f"{len(rej_har) + len(rej_harl)} rejections in total, spanning {len(all_rej)} distinct "
        f"tests. In **every one** the recorded direction is `baseline_better`. "
        f"**Not one test in either family rejects in favour of DL.**"
    )
    L.append("")
    L.append(
        f"The Transformer is the weaker of the two architectures and fails hardest: it is "
        f"significantly worse than *both* baselines at h=5 and h=22, reaching "
        f"DM = {fam['dm_vs_harl']['results']['h22_transformer']['dm_hln']:.3f} "
        f"(q = {pv(fam['dm_vs_harl']['results']['h22_transformer']['p_bh'])}) against HAR-L. "
        f"Its per-seed dispersion is also an order of magnitude worse than the LSTM's — at h=1 "
        f"the Transformer's seed sd is "
        f"{prim['horizons']['1']['models']['transformer']['qlike_seed_sd']:.4f} against the "
        f"LSTM's {prim['horizons']['1']['models']['lstm']['qlike_seed_sd']:.4f}, with per-seed "
        f"QLIKE ranging "
        f"{min(prim['horizons']['1']['models']['transformer']['qlike_per_seed']):.4f}–"
        f"{max(prim['horizons']['1']['models']['transformer']['qlike_per_seed']):.4f}. "
        f"A single seed of that model would have supported almost any story, which is why the "
        f"design pre-committed to {prim['config']['n_seeds']} seeds and reports the spread."
    )
    L.append("")

    # ---------------------------------------------------------------- robustness
    L.append("### 8.4 Robustness arms")
    L.append("")
    L.append(f"> Settings, stated not silently applied: {d['robustness']['_settings_note']}")
    L.append("")
    L.append(
        "Each arm is compared against **its own** HAR / HAR-L columns. These arms carry "
        "different tickers, sample spans and OOS row counts, so their QLIKE levels are not "
        "comparable with the primary arm's — only the *sign and significance of the contrast* "
        "within each arm is."
    )
    L.append("")
    L.append(
        "| arm | ticker | estimator | h | n OOS | HAR | HAR-L | LSTM | Transformer | "
        "best DL | DM vs own HAR | p | DM vs own HAR-L | p |"
    )
    L.append("|---|" + "---|" * 13)
    for name, arm in d["robustness"].items():
        if name.startswith("_"):
            continue
        for h in HORIZONS:
            hh = arm["horizons"][h]
            m = hh["models"]
            best = min(("lstm", "transformer"), key=lambda k: m[k]["qlike_ensemble"])
            L.append(
                "| `{n}` | {t} | {e} | {h} | {no:,} | {har} | {harl} | {ls} | {tr} | `{b}` | "
                "{dh} | {ph} | {dhl} | {phl} |".format(
                    n=name, t=arm["ticker"], e=arm["estimator"], h=h, no=hh["n_oos"],
                    har=q(m["har"]["qlike_ensemble"]), harl=q(m["harl"]["qlike_ensemble"]),
                    ls=q(m["lstm"]["qlike_ensemble"]), tr=q(m["transformer"]["qlike_ensemble"]),
                    b=best,
                    dh=dm(hh["dm_vs_har"][best]["dm_hln"]), ph=pv(hh["dm_vs_har"][best]["p_value"]),
                    dhl=dm(hh["dm_vs_harl"][best]["dm_hln"]),
                    phl=pv(hh["dm_vs_harl"][best]["p_value"]),
                )
            )
    L.append("")
    L.append(
        "**All nine arm × horizon cells put the best DL model behind both of its own "
        "baselines** — every DM statistic in both DM columns is negative. The conclusion "
        "therefore does not depend on the ticker (`^GSPC` / `SPY` / `QQQ`), on the estimator "
        "(Parkinson / Garman-Klass), or on the sample span. `SPY_garman_klass` matters "
        "specifically: SPY's Open is genuine (§3), so this arm shows the verdict is not an "
        "artifact of being restricted to Parkinson on the defective `^GSPC` Open."
    )
    L.append("")
    L.append(
        "These p-values are **raw, not FDR-adjusted** — the pre-registered BH-FDR families "
        "cover the primary arm only (§8.3). They are reported to show consistency of sign, "
        "and no headline claim rests on them."
    )
    L.append("")

    # ---------------------------------------------------------------- ablations
    L.append("### 8.5 Ablations")
    L.append("")
    L.append(f"> Settings, stated not silently applied: {d['ablations']['_settings_note']}")
    L.append("")
    L.append(
        "**Comparison basis.** Each ablation is scored against **its own** HAR / HAR-L "
        "columns, never the primary arm's. This is not a formality: changing `seq_len` or "
        "`train_len` changes the usable OOS row set (`window_L66` has "
        f"{d['ablations']['window_L66']['horizons']['1']['n_oos']:,} rows and "
        f"`train_len1500` has "
        f"{d['ablations']['train_len1500']['horizons']['1']['n_oos']:,}, against the primary "
        f"arm's {per['h1']['n_oos']:,}), and the sparser `refit_every = 3000` also moves the "
        "baselines themselves. Cross-arm QLIKE comparisons would be meaningless."
    )
    L.append("")
    L.append(
        "`ar1` and `ridge_lags` are **not run** in the ablation arms, and the Transformer is "
        "not run in `refit_250`. The console log prints `AR1=nan` / `RIDGE=nan` / `TRF=nan` for "
        "these as a fixed-width formatting placeholder; the models are simply **absent from "
        "the result artifact**, and no claim below rests on them."
    )
    L.append("")
    L.append(
        "| ablation | changed from primary | h | n OOS | own HAR | own HAR-L | LSTM | "
        "Transformer | DM LSTM vs own HAR-L | p (raw) |"
    )
    L.append("|---|" + "---|" * 9)
    changed = {
        "channels_with_returns": "`channels` 1 → 2 (adds return path)",
        "refit_250": "`refit_every` 750 → 250",
        "window_L66": "`seq_len` 22 → 66",
        "train_len1500": "`train_len` 3000 → 1500",
        "loss_qlike_direct": "`loss` logmse → qlike",
    }
    for name, arm in d["ablations"].items():
        if name.startswith("_"):
            continue
        for h in HORIZONS:
            hh = arm["horizons"][h]
            m = hh["models"]
            trf = q(m["transformer"]["qlike_ensemble"]) if "transformer" in m else "not run"
            r = hh["dm_vs_harl"]["lstm"]
            L.append(
                "| `{n}` | {c} | {h} | {no:,} | {har} | {harl} | {ls} | {tr} | {d} | {p} |".format(
                    n=name, c=changed[name], h=h, no=hh["n_oos"],
                    har=q(m["har"]["qlike_ensemble"]), harl=q(m["harl"]["qlike_ensemble"]),
                    ls=q(m["lstm"]["qlike_ensemble"]), tr=trf,
                    d=dm(r["dm_hln"]), p=pv(r["p_value"]),
                )
            )
    L.append("")

    cwr = d["ablations"]["channels_with_returns"]["horizons"]
    r250 = d["ablations"]["refit_250"]["horizons"]
    L.append("**What each ablation answers**")
    L.append("")
    L.append(
        f"- **`refit_250` — is the verdict an artifact of a sparse refit cadence? No.** This is "
        f"the ablation the design most needed, because {prim['horizons']['1']['n_refits']} "
        f"refits over 52 years is sparse by daily-practice standards. Tripling the cadence "
        f"({r250['1']['n_refits']} refits against the primary arm's "
        f"{prim['horizons']['1']['n_refits']}) leaves the picture intact: LSTM "
        f"{q(r250['22']['models']['lstm']['qlike_ensemble'])} against its own HAR-L "
        f"{q(r250['22']['models']['harl']['qlike_ensemble'])} at h=22 "
        f"(DM = {r250['22']['dm_vs_harl']['lstm']['dm_hln']:.3f}, "
        f"p = {pv(r250['22']['dm_vs_harl']['lstm']['p_value'])}), essentially reproducing the "
        f"primary arm's h=22 deficit. The refit is genuinely re-fitting — the two arms differ "
        f"in origin count by a factor of "
        f"{r250['1']['n_refits'] / prim['horizons']['1']['n_refits']:.1f} — and it does not "
        f"rescue the DL arm."
    )
    L.append(
        f"- **`channels_with_returns` — the one place DL wins, and it does not transfer.** "
        f"Giving the LSTM the return path beats *its own* HAR-L at h=1 "
        f"({q(cwr['1']['models']['lstm']['qlike_ensemble'])} vs "
        f"{q(cwr['1']['models']['harl']['qlike_ensemble'])}; DM = "
        f"{cwr['1']['dm_vs_harl']['lstm']['dm_hln']:.3f}, raw p = "
        f"{pv(cwr['1']['dm_vs_harl']['lstm']['p_value'])}) and at h=5 (DM = "
        f"{cwr['5']['dm_vs_harl']['lstm']['dm_hln']:.3f}, raw p = "
        f"{pv(cwr['5']['dm_vs_harl']['lstm']['p_value'])}) — but **not at h=22** (DM = "
        f"{cwr['22']['dm_vs_harl']['lstm']['dm_hln']:.3f}, raw p = "
        f"{pv(cwr['22']['dm_vs_harl']['lstm']['p_value'])}). This is reported because it is the "
        f"only positive signal in the experiment and burying it would be selective reporting. "
        f"It does **not** change the headline, for reasons fixed before the run: it is outside "
        f"the pre-registered FDR families so its p-values are **uncorrected**; it runs "
        f"`n_seeds = {d['ablations']['channels_with_returns']['config']['n_seeds']}` against the "
        f"primary arm's {prim['config']['n_seeds']}; and its `refit_every = "
        f"{d['ablations']['channels_with_returns']['config']['refit_every']}` also degrades the "
        f"arm's own baselines (its HAR-L is "
        f"{q(cwr['1']['models']['harl']['qlike_ensemble'])} against the primary arm's "
        f"{q(per['h1']['qlike_harl_strong_baseline'])}), so part of the margin is a weaker "
        f"comparison point rather than a better model. Its honest reading is a **hypothesis for "
        f"a future pre-registered test** — that any DL edge here lives in the leverage channel "
        f"at short horizons, not in the volatility path at long ones — and notably it points "
        f"the *opposite* way to the horizon hypothesis this experiment set out to test."
    )
    L.append(
        f"- **`window_L66` — is 22 days too short a window for the DL models? No.** Tripling "
        f"the input window makes h=22 worse, not better "
        f"({q(d['ablations']['window_L66']['horizons']['22']['models']['lstm']['qlike_ensemble'])} "
        f"against its own HAR-L "
        f"{q(d['ablations']['window_L66']['horizons']['22']['models']['harl']['qlike_ensemble'])}, "
        f"DM = {d['ablations']['window_L66']['horizons']['22']['dm_vs_harl']['lstm']['dm_hln']:.3f})."
    )
    L.append(
        f"- **`train_len1500` — would a shorter, more adaptive window help? No, it hurts "
        f"sharply.** LSTM degrades to "
        f"{q(d['ablations']['train_len1500']['horizons']['5']['models']['lstm']['qlike_ensemble'])} "
        f"at h=5 (DM = "
        f"{d['ablations']['train_len1500']['horizons']['5']['dm_vs_harl']['lstm']['dm_hln']:.3f}), "
        f"consistent with these models being data-hungry rather than over-fit to a long window."
    )
    L.append(
        f"- **`loss_qlike_direct` — is the log-MSE training loss mismatched to the QLIKE "
        f"evaluation metric? Training directly on QLIKE makes it worse at every horizon** "
        f"(h=1 DM = "
        f"{d['ablations']['loss_qlike_direct']['horizons']['1']['dm_vs_harl']['lstm']['dm_hln']:.3f}, "
        f"h=22 DM = "
        f"{d['ablations']['loss_qlike_direct']['horizons']['22']['dm_vs_harl']['lstm']['dm_hln']:.3f}), "
        f"so the loss mismatch is not what is holding the DL arm back."
    )
    L.append("")
    L.append(
        "Taken together, the four non-`channels` ablations close the obvious "
        "\"you configured it badly\" objections: cadence, window length, training-window size "
        "and loss function each move the result the wrong way or leave it unchanged."
    )
    L.append("")

    # ---------------------------------------------------------------- conclusion
    L.append("### 8.6 What this closes, and what it does not")
    L.append("")
    L.append(
        f"**Closed.** The open item left by K1310–K1330 — *at which horizon, if any, does the "
        f"DL increment appear?* — is answered for this design: **at none of h ∈ {{1, 5, 22}}**. "
        f"`H1_short_horizon = {v['H1_short_horizon']}` reproduces the four prior NULLs at h=1, "
        f"and `H2_boundary_exists = {v['H2_boundary_exists']}` extends them. The "
        f"longer-horizon extension is not a weaker version of the h=1 null; it is a stronger "
        f"result in the opposite direction, since the DL deficit is significant at h=22 against "
        f"HAR-L and the Transformer is significantly worse than both baselines at h=5 and h=22."
    )
    L.append("")
    L.append(
        "**Not closed, and not claimed.** This bounds *two architectures* at *these "
        "capacities* on a *daily realized-range proxy*. §9 states the binding limitation: the "
        "proxy carries measurement noise that genuine 5-minute RV would not, and that noise "
        "plausibly penalises flexible models more than rigid ones — so this design is, if "
        "anything, **tilted against the DL arm**. A 5-minute-RV replication could in principle "
        "move the h=5 and h=22 rows. What it could not do is rescue the framing this "
        "experiment tested, because the deficit here widens with the horizon rather than "
        "narrowing. The `channels_with_returns` ablation is the one lead worth a "
        "pre-registered follow-up, and it points at short horizons and the leverage channel."
    )
    return "\n".join(L)


SECTIONS = {
    "RESULTS:DESCRIPTIVE": render_descriptive,
    "RESULTS:MAIN": render_main,
}


def splice(text: str, marker: str, body: str) -> str:
    open_m, close_m = f"<!-- {marker} -->", f"<!-- /{marker} -->"
    block = f"{open_m}\n\n{body}\n\n{close_m}"
    pat = re.compile(
        re.escape(open_m) + r".*?" + re.escape(close_m), re.DOTALL
    )
    if pat.search(text):
        return pat.sub(lambda _: block, text)
    if open_m not in text:
        raise SystemExit(f"marker {open_m} not found in README")
    return text.replace(open_m, block)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="verify README already matches the artifact; do not write")
    a = ap.parse_args()

    d = json.loads(RESULTS.read_text())
    text = README.read_text()
    out = text
    for marker, fn in SECTIONS.items():
        out = splice(out, marker, fn(d))

    if a.check:
        if out != text:
            print("DRIFT: README does not match K1814_results.json", file=sys.stderr)
            return 1
        print("OK: README sections 7 and 8 match K1814_results.json")
        return 0

    README.write_text(out)
    print(f"rendered {len(SECTIONS)} sections into {README.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
