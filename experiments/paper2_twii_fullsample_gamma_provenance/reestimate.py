"""
Provenance re-estimation for Paper2 (taiwan-vt) Table 2 TWII gamma = 0.272, t = 3.18.

Motivation: telegram-312 / provenance-sweep-legacy-paper-numbers. The paper claims
TWII (TAIEX) full-sample 1997-2026 GJR-GARCH(1,1) gamma = 0.272, t = 3.18 (n=7148),
but K892 only estimates the 2008-2026 window (rolling max 0.236). No live experiment
JSON reproduces the full-sample 1997-2026 number -> flagged HIGH severity, source
unidentified. This script rebuilds the 1997-2026 series from the two canonical CSVs
already committed under paper/taiwan-vt/data/ and re-estimates the GJR gamma, creating
a reproducible source of record.

Data (offline, committed):
  - paper/taiwan-vt/data/_twii_1997_2007_snapshot.csv   (date, twii_close ; 1997-01..2008-01)
  - paper/taiwan-vt/data/0050_tw_twii_..._2008-2026.csv (twii_close ; 2008-01..2026)

Spec: GJR-GARCH(1,1), constant mean, normal errors, QMLE (Bollerslev-Wooldridge robust
SE). Matches the paper's stated 'full-sample MLE' convention for the index rows.
No random component -> no seed needed.
"""
import json
import numpy as np
import pandas as pd
from arch import arch_model

BASE = "paper/taiwan-vt/data"
SNAP = f"{BASE}/_twii_1997_2007_snapshot.csv"
MAIN = f"{BASE}/0050_tw_twii_2330_tw_2317_tw_2454_tw_0056_tw_spy_vix_2008-2026.csv"

# 1997-2007 snapshot: comment lines start with '#'
snap = pd.read_csv(SNAP, comment="#")
snap = snap[["date", "twii_close"]].rename(columns={"twii_close": "close"})

main = pd.read_csv(MAIN)[["date", "twii_close"]].rename(columns={"twii_close": "close"})

df = pd.concat([snap, main], ignore_index=True)
df["date"] = pd.to_datetime(df["date"])
df = df.dropna(subset=["close"]).drop_duplicates(subset=["date"]).sort_values("date")
df = df[df["close"] > 0].reset_index(drop=True)

# log returns in percent (arch convention: scale to ~1 for numerical stability)
ret = 100.0 * np.log(df["close"]).diff().dropna()
ret.index = df["date"].iloc[1:].values

am = arch_model(ret, mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="normal")
res = am.fit(disp="off", cov_type="robust")  # BW-robust QMLE SE

# arch names the asymmetry term 'gamma[1]'
gamma = float(res.params["gamma[1]"])
gamma_t = float(res.tvalues["gamma[1]"])
alpha = float(res.params["alpha[1]"])
beta = float(res.params["beta[1]"])
omega = float(res.params["omega"])
persistence = alpha + beta + gamma / 2.0

out = {
    "experiment_id": "paper2_twii_fullsample_gamma_provenance",
    "purpose": "Reproduce Paper2 Table2 TWII full-sample 1997-2026 GJR gamma (telegram-312 provenance gap)",
    "spec": "GJR-GARCH(1,1) constant-mean normal QMLE, BW-robust SE",
    "sample": {
        "start": str(df["date"].iloc[0].date()),
        "end": str(df["date"].iloc[-1].date()),
        "n_prices": int(len(df)),
        "n_returns": int(len(ret)),
    },
    "paper_claim": {"gamma": 0.272, "gamma_t": 3.18, "n_days": 7148},
    "reestimate": {
        "gamma": round(gamma, 4),
        "gamma_t": round(gamma_t, 3),
        "alpha": round(alpha, 4),
        "beta": round(beta, 4),
        "omega": round(omega, 6),
        "persistence": round(persistence, 4),
        "loglik": round(float(res.loglikelihood), 2),
    },
    "delta_gamma": round(gamma - 0.272, 4),
    "match_tol_0p02": bool(abs(gamma - 0.272) <= 0.02),
    "data_sources": [SNAP, MAIN],
}
with open("experiments/paper2_twii_fullsample_gamma_provenance/results.json", "w") as f:
    json.dump(out, f, indent=2, ensure_ascii=False)
print(json.dumps(out, indent=2, ensure_ascii=False))
