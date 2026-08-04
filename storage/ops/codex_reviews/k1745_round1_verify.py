"""Independent verification of K1745 claim surface.

Recomputes the headline statistics from the frozen forecast sidecar
(K1745_forecasts.csv) and compares them against K1745_results.json, then
compares README.md's table against results.json. Read-only.
"""
import json
import re
import sys
import pathlib

import numpy as np
import pandas as pd

D = pathlib.Path(sys.argv[1])
res = json.loads((D / "K1745_results.json").read_text())
readme = (D / "README.md").read_text()
fc = pd.read_csv(D / "K1745_forecasts.csv")

print("forecasts.csv columns:", list(fc.columns))
print("forecasts.csv rows:", len(fc))
print()

fails = []


def chk(label, got, want, tol):
    ok = abs(got - want) <= tol
    print(f"{'OK ' if ok else 'FAIL'} {label}: recomputed={got!r} claimed={want!r} tol={tol}")
    if not ok:
        fails.append(label)


# ---------- README table vs results.json ----------
rows = re.findall(
    r"^\|\s*([A-Za-z0-9.]+)\s*\|\s*(\d+)\s*\|\s*([\d\-.]+\.\.[\d\-.]+)\s*\|\s*(-?[\d.]+)%\s*\|"
    r"\s*(-?[\d.]+)\s*\|\s*([\d.]+)\s*\|\s*([\d.]+)\s*\|",
    readme,
    re.M,
)
print(f"README table rows parsed: {len(rows)}")
assert rows, "could not parse README results table"
for tick, n, span, imp, t, holm, grholm in rows:
    m = res["markets"][tick]
    q = m["losses"]["qlike"]
    print(f"\n--- README vs results: {tick} ---")
    chk(f"{tick} oos n", m["oos"]["n"], int(n), 0)
    got_span = f"{m['oos']['start']}..{m['oos']['end']}"
    ok = got_span == span
    print(f"{'OK ' if ok else 'FAIL'} {tick} oos span: results={got_span} readme={span}")
    if not ok:
        fails.append(f"{tick} span")
    chk(f"{tick} improvement_pct", round(q["improvement_pct"], 3), float(imp), 1e-9)
    chk(f"{tick} hln_t", round(q["hln_t"], 3), float(t), 1e-9)
    chk(f"{tick} holm_p", round(q["holm_p"], 4), float(holm), 1e-9)
    chk(f"{tick} GR holm_p", round(q["fluctuation"]["holm_p"], 4), float(grholm), 1e-9)


# ---------- independent recompute from forecast sidecar ----------
print("\n\n########## independent recompute from K1745_forecasts.csv ##########")
tcol = [c for c in fc.columns if c.lower() in ("ticker", "market", "symbol")]
tcol = tcol[0] if tcol else None
print("market column:", tcol)

for tick, m in res["markets"].items():
    q = m["losses"]["qlike"]
    sub = fc[fc[tcol] == tick] if tcol else fc
    print(f"\n--- recompute {tick} (rows={len(sub)}) ---")
    chk(f"{tick} row count", len(sub), q["n"], 0)

    cols = {c.lower(): c for c in sub.columns}

    def find(*pats):
        for p in pats:
            for lc, c in cols.items():
                if re.fullmatch(p, lc):
                    return c
        return None

    c_act = find(r".*actual.*", r".*realized.*", r".*target.*")
    c_tvp = find(r".*tvp.*(pred|forecast|fcst).*", r".*(pred|forecast|fcst).*tvp.*", r"tvp")
    c_sta = find(r".*static.*(pred|forecast|fcst).*", r".*(pred|forecast|fcst).*static.*", r"static")
    print("cols ->", dict(actual=c_act, tvp=c_tvp, static=c_sta))
    if not (c_act and c_tvp and c_sta):
        print("SKIP recompute: could not identify columns")
        continue

    a = sub[c_act].to_numpy(float)
    p_t = sub[c_tvp].to_numpy(float)
    p_s = sub[c_sta].to_numpy(float)
    # canonical QLIKE: actual/predicted - log(actual/predicted) - 1
    ql_t = a / p_t - np.log(a / p_t) - 1.0
    ql_s = a / p_s - np.log(a / p_s) - 1.0
    chk(f"{tick} mean_tvp qlike", float(ql_t.mean()), q["mean_tvp"], 1e-9)
    chk(f"{tick} mean_static qlike", float(ql_s.mean()), q["mean_static"], 1e-9)
    d = ql_t - ql_s
    chk(f"{tick} mean_loss_diff", float(d.mean()), q["mean_loss_diff"], 1e-9)
    imp = (ql_s.mean() - ql_t.mean()) / ql_s.mean() * 100.0
    chk(f"{tick} improvement_pct", float(imp), q["improvement_pct"], 1e-9)

    # Newey-West HAC t on the loss differential at the declared bandwidth
    L = q["hac_lag"]
    n = len(d)
    dm = d - d.mean()
    g0 = float((dm * dm).mean())
    lrv = g0
    for k in range(1, L + 1):
        gk = float((dm[k:] * dm[:-k]).mean())
        lrv += 2.0 * (1.0 - k / (L + 1.0)) * gk
    dm_t = d.mean() / np.sqrt(lrv / n)
    chk(f"{tick} DM t (pre-HLN, NW lag {L})", float(dm_t), q["canonical_repo_t_before_hln"], 5e-3)
    hln = np.sqrt((n + 1 - 2 * 1 + 1 * (1 - 1) / n) / n)
    chk(f"{tick} hln_factor", float(hln), q["hln_factor"], 1e-9)
    chk(f"{tick} hln_t", float(dm_t * hln), q["hln_t"], 5e-3)

    # sign sanity: does the reported direction agree with the raw means?
    worse = ql_t.mean() > ql_s.mean()
    print(f"     direction: TVP mean QLIKE {'WORSE' if worse else 'BETTER'} than static; "
          f"improvement_pct={q['improvement_pct']:.4f} (negative = TVP worse)")

# ---------- Holm recomputation across the declared family ----------
print("\n\n########## Holm family recomputation ##########")
fam = []
for tick, m in res["markets"].items():
    for loss in ("qlike", "mse"):
        fam.append((f"{tick}/{loss}", m["losses"][loss]["p_value"], m["losses"][loss]["holm_p"]))
fam_sorted = sorted(fam, key=lambda x: x[1])
k = len(fam_sorted)
running = 0.0
for i, (name, p, claimed) in enumerate(fam_sorted):
    adj = min(1.0, (k - i) * p)
    running = max(running, adj)
    chk(f"Holm {name}", round(running, 12), round(claimed, 12), 1e-9)

print("\n\n==================== SUMMARY ====================")
print("FAILURES:", fails if fails else "none")
sys.exit(1 if fails else 0)
