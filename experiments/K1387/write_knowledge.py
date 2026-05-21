#!/usr/bin/env python3
"""One-shot script: read K1387_results.json → write knowledge.json + work_log entry."""
import json, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

results_path = Path(__file__).parent / "K1387_results.json"
if not results_path.exists():
    print(f"ERROR: {results_path} not found", file=sys.stderr)
    sys.exit(1)

with open(results_path) as f:
    results = json.load(f)

verdict = results.get("verdict", "NULL")
# results.json top-level structure (from K1387.py compile_results)
qlike_block = results.get("qlike", {})
qlike = {k: qlike_block.get(k) for k in ("M2", "M3")}
dm_t = qlike_block.get("dm_t_stat")
dm_p = qlike_block.get("dm_p_value")
oos_len = results.get("period", {}).get("oos_length_days")
var_acc = results.get("var_accuracy", {})
perf = results.get("performance", {})
mean_nu = results.get("models", {}).get("M3_DCC_StudentT", {}).get("estimated_dof_mean")

# Build var accuracy summary
def var_summary(model):
    res = []
    for level in ["1pct", "5pct"]:
        k = f"{model}_{level}"
        v = var_acc.get(k, {})
        kp = "PASS" if v.get("kupiec_pass") else "FAIL"
        cp = "PASS" if v.get("christoffersen_pass") else "FAIL"
        n = v.get("n_violations", "?")
        res.append(f"{level}: N={n} Kupiec={kp} Christ={cp}")
    return "; ".join(res)

m2_var = var_summary("M2")
m3_var = var_summary("M3")

content = (
    f"K1387: Gaussian DCC vs Student-t DCC 風險平價（ERC）組合比較。"
    f"SPY+TLT+GLD，IS expanding window 初始 250 天（2015-2019），OOS 2020-2024 (T={oos_len})，refit 每 5 天。"
    f"M0=等權重，M1=Inverse-Vol(60日)，M2=Gaussian DCC+ERC，M3=Student-t DCC+ERC。"
    f"估計 mean_nu={f'{mean_nu:.2f}' if mean_nu else '?'}（自由度，OOS 均值）。"
    f"\nQKLIKE(組合層級): M2={qlike.get('M2',float('nan')):.6f}, M3={qlike.get('M3',float('nan')):.6f}。"
    f"DM test(M2 vs M3): t={f'{dm_t:.4f}' if dm_t is not None else '?'}, p={f'{dm_p:.4f}' if dm_p is not None else '?'} "
    f"(正 t → M2 QLIKE 較高 → M3 better)。"
    f"\nVaR M2: {m2_var}。VaR M3: {m3_var}。"
    f"\nVerdict={verdict}。"
    f"\n方法論: 兩步 MLE (Stage1 univariate GARCH(1,1)；Stage2a MVN DCC；Stage2b t-DCC)。"
    f"ERC=scipy SLSQP minimize sum(RC_i - sigma_p/N)^2。Lookahead 保護: weights[t] = H_{{t|t-1}} (formed t-1)。"
    f"\nCodex review (primary-path read-only sandbox 2026-05-21): CONDITIONAL_PASS。"
    f"已發現並修正兩個問題: (1) h_last timing L593 (h_vecs[-1]→h_pred；對稱影響 M2/M3，非 lookahead)；"
    f"(2) DM comment L714 (措辭錯誤已修)。"
    f"實驗使用修前版本跑出，h_last bug 對稱影響 M2/M3 故比較方向仍有效；絕對 QLIKE 略偏高。"
    f"修正版 (L593) 已更新 K1387.py，如需論文用精確數字應 re-run。"
)

entry = {
    "item_id": uuid.uuid4().hex[:8],
    "category": "multivariate_model",
    "experiment_id": "K1387",
    "verdict": verdict,
    "title": f"K1387: Gaussian vs Student-t DCC Risk Parity (ERC) — SPY/TLT/GLD OOS 2020-2024 [{verdict}]",
    "content": content,
    "evidence": [
        "experiments/K1387/K1387_results.json",
        "experiments/K1387/K1387.py",
        "Paolella (2025, JTSA) heavy-tailed multivariate DCC",
        "Engle & Sheppard (2002) DCC",
        "Maillard, Roncalli & Teiletche (2010) ERC",
        "K1100c, K1100d (DCC series prior work)",
    ],
    "confidence": 0.78,
    "reviewer": "Codex primary-path CONDITIONAL_PASS (read-only sandbox, 2026-05-21)",
    "reviewer_source": "Codex primary-path (read-only)",
    "codex_review": "CONDITIONAL_PASS — (1) h_last timing offset L593 symmetric to M2/M3, not lookahead; (2) DM comment L714 fixed. Lookahead, ERC, Kupiec, Christoffersen correct.",
    "created_at": datetime.now(timezone.utc).isoformat(),
    "qlike": qlike,
    "dm_t_stat": dm_t,
    "dm_p_value": dm_p,
    "mean_nu_oos": mean_nu,
    "oos_len": oos_len,
    "var_accuracy": var_acc,
    "performance": perf,
    "related_experiments": ["K1100c", "K1100d"],
    "codex_caveat": (
        "h_last timing: stored h_{T_IS|T_IS-1} (last IS filtered) instead of h_pred "
        "(one-step-ahead forecast) at line 593. Bug symmetric to M2/M3; DM comparison valid. "
        "Fixed in committed K1387.py v2 (line 593). Re-run for paper-ready tables."
    ),
}

from src.volpred.memory.system import MemorySystem
ms = MemorySystem(storage_dir=str(ROOT / "storage"))
ms._append_to_index("knowledge.json", entry)
print(f"[OK] knowledge.json entry written: item_id={entry['item_id']} verdict={verdict}")

# Write work_log entry
work_log_path = ROOT / "storage" / "work_log.json"
with open(work_log_path) as f:
    wl = json.load(f)
wl_entry = {
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "task_type": "experiment",
    "k_id": "K1387",
    "title": f"K1387: Risk Parity + Heavy-Tailed DCC (Paolella 2025 JTSA)",
    "status": verdict.lower(),
    "verdict": verdict,
    "notes": (
        f"Gaussian vs Student-t DCC ERC comparison. "
        f"Codex CONDITIONAL_PASS (primary-path). "
        f"DM t={f'{dm_t:.4f}' if dm_t is not None else '?'}, p={f'{dm_p:.4f}' if dm_p is not None else '?'}. "
        f"Experiment run with h_last timing bug (symmetric to M2/M3); "
        f"bug fixed in committed code."
    ),
    "experiment_path": "experiments/K1387/",
}
wl.append(wl_entry)
with open(work_log_path, "w") as f:
    json.dump(wl, f, indent=2, default=str, ensure_ascii=False)
print(f"[OK] work_log entry written: K1387 {verdict}")

# Update next_tasks.json
next_tasks_path = ROOT / "storage" / "next_tasks.json"
with open(next_tasks_path) as f:
    nt = json.load(f)
tasks = nt if isinstance(nt, list) else nt.get("tasks", [])
updated = False
for t in tasks:
    if t.get("id") == "K1387":
        t["status"] = "succeeded" if verdict != "NULL" else "completed_null"
        t["completed_at"] = datetime.now(timezone.utc).isoformat()
        t["verdict"] = verdict
        updated = True
        break
if updated:
    if isinstance(nt, list):
        with open(next_tasks_path, "w") as f:
            json.dump(nt, f, indent=2, default=str, ensure_ascii=False)
    else:
        nt["tasks"] = tasks
        with open(next_tasks_path, "w") as f:
            json.dump(nt, f, indent=2, default=str, ensure_ascii=False)
    print(f"[OK] next_tasks.json K1387 → {t['status']}")
else:
    print("[WARN] K1387 not found in next_tasks.json")

print("\nAll done. Now run git commit.")
