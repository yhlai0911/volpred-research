# K1734 claim surface 降級 — 可直接套用的修改規格

**狀態**：設計完成、**未套用**（研究部無 `.claude/worktrees/**` 寫入權，見文末）
**依據**：運營經理裁決 D17（`item_20260805T100313937777Z`）核准三步收尾之第一步
**目標檔案**：`.claude/worktrees/dispatch-slot-1-1e5922b4-k1734/experiments/K1734/`
**worktree HEAD**：`4f1f2749a`（本班實測工作目錄乾淨，bytes 穩定）

---

## 設計原則：拆開「檢定結果」與「假說裁決」

D17 的根因判定是：**pre-registration 的資訊在第一輪就洩漏，且洩漏不可逆**。因此在這份資料上
不存在任何 confirmatory 讀法。但**檢定本身是乾淨的**（rev3 已獨立驗證 lookahead / leakage /
statistics 三維全 PASS），數字不該被動。

所以降級的分界線是：

- **保留**：test-level 事實（某個 bootstrap CI 排除 0、某個 HAC p 值小於 0.05）。這些是資料。
- **降級**：hypothesis-level 裁決（`accept` / `CONFIRMED`）。這些是宣稱。

機械判準：**凡是名為 `accept` 的鍵都是裁決，一律改名**；改完 `grep -c '"accept"'` 應為 0，
只剩定義性散文。這條判準可被 grep 驗證，不依賴閱讀者的判斷力。

**不重跑數字，只重跑產出**：`_download()` 只要 CSV 存在就讀 `data/raw/` 快取、不打 yfinance
（k1734.py:148-155 實測），所以重跑是決定性的，不會抓到 2026-07-27 之後的新資料。
`runtime_seconds` 前次為 38.173 秒，5000 次 block bootstrap 固定 `SEED=42`。

---

## 六個修改點（行號基準 = worktree HEAD `4f1f2749a`）

### (1) 新增模組常數 `PREREGISTRATION_STATUS`

放在 `LITERATURE` 之後。這是整份降級的**機械錨點**：其他所有欄位都指回它。

```python
PREREGISTRATION_STATUS = {
    "confirmatory_claims_available": False,
    "reason": (
        "The pre-registration was informationally contaminated in review round 1: the "
        "hypothesis family was revised after its own results had been seen. Narrowing H2 "
        "afterwards is HARKing; adding the risk-off limb in rev4 folds an already-observed "
        "result into a confirmatory family. Neither is repairable on this dataset, because "
        "no revision can make an observed result ex-ante again."
    ),
    "what_survives": (
        "Every statistic below is a valid EXPLORATORY test outcome. Round 3 independently "
        "verified lookahead, leakage and statistics (all PASS), so the computation is sound; "
        "what cannot be recovered is the confirmatory status of any hypothesis."
    ),
    "adjudication": "manager ruling D17, 2026-08-05",
}
```

### (2) k1734.py:514-520 — H1 `verdict_primary`

| 舊鍵 | 新鍵 |
|---|---|
| `h1a_static_left_tail_accept` | `h1a_static_left_tail_exploratory_gate_passed` |
| `h1b_stress_amplification_accept` | `h1b_stress_amplification_exploratory_gate_passed` |
| `accept` | `compound_exploratory_gate_passed` |
| `accept_definition` | `exploratory_gate_definition` |

`exploratory_gate_definition` 的內文保留原有的口徑說明（複合 H1 = H1a AND H1b、同為
95% CI 排除 0 的 caliber），**末尾加一句**：
`"A passing gate is a TEST OUTCOME, not an accepted hypothesis: see results['preregistration_status']."`

### (3) k1734.py:708-716 — H2

| 舊鍵 | 新鍵 |
|---|---|
| `accept` | `exploratory_gate_passed` |
| `accept_definition` | `exploratory_gate_definition` |
| `h2a_yen_accept` | `h2a_yen_exploratory_gate_passed` |
| `h2b_riskoff_accept` | `h2b_riskoff_exploratory_gate_passed` |

局部變數 `h2a_accept` / `h2b_accept` / `accept`（643 / 672 / 673 行）維持原名不動——
它們是函式內部的中間值，不是對外的 claim surface。

### (4) k1734.py:941 — H3

`accept` → `exploratory_gate_passed`。924-926 行的計算式不動。

### (5) k1734.py:1217-1253 — 讀取端與 tag

讀取端同步改名：

```python
h1a_gate = h1["verdict_primary"]["h1a_static_left_tail_exploratory_gate_passed"]
h1b_gate = h1["verdict_primary"]["h1b_stress_amplification_exploratory_gate_passed"]
h1_gate  = h1["verdict_primary"]["compound_exploratory_gate_passed"]
h2a_gate = h2["h2a_yen_exploratory_gate_passed"]
h2b_gate = h2["h2b_riskoff_exploratory_gate_passed"]
h2_gate  = h2["exploratory_gate_passed"]
h3_gate  = (h3["exploratory_gate_passed"]
            and fdr["reject_null"].get("H3_oos_cw_mse", False)
            and fdr["reject_null"].get("H3_insample_hac_carry", False))
```

三個 tag 字串**必須拿掉 `CONFIRMED` 字樣**——它是 claim surface 抵達人類的最短路徑：

- `LEFT_TAIL_ASYMMETRY_CONFIRMED` → `EXPLORATORY_BOTH_LIMB_GATES_PASSED`
- `STATIC_LEFT_TAIL_ASYMMETRY_CONFIRMED_STRESS_AMPLIFICATION_NULL`
  → `EXPLORATORY_STATIC_GATE_PASSED_STRESS_AMPLIFICATION_GATE_FAILED`
- `YEN_TRIGGER_CONFIRMED_…` → `EXPLORATORY_YEN_GATE_PASSED_…`

`overall` 一律以 `NULL_NO_CONFIRMATORY_CLAIM__` 為前綴，後面接 exploratory tag 組合。
讀者掃第一個 token 就知道這份實驗的地位，不必讀完整串。

### (6) k1734.py:1282-1300 — `verdicts` 區塊

改名為 `exploratory_gates`，並把裁決欄位顯式寫成 `None`（JSON `null`）而不是刪除——
**刪掉會讓下游以為欄位還沒算，寫 null 才說得出「算過，但不可用」**：

```python
"preregistration_status": PREREGISTRATION_STATUS,
"verdicts": {
    "H1_accept": None,
    "H2_accept": None,
    "H3_accept": None,
    "note": ("Null by adjudication, not by absence of computation. "
             "See preregistration_status; exploratory gate outcomes are in "
             "results['exploratory_gates']."),
},
"exploratory_gates": { ...六個 gate 布林 + overall... },
```

頂層 `results` dict 內 `"verdicts"` 那行之前插入 `"preregistration_status"`。

---

## 套用後的驗收（缺一不可，全部可機械執行）

1. **重跑**：`uv run python experiments/K1734/k1734.py`（worktree 內），約 38 秒。
2. **只有 claim 層改變**——這是本規格最重要的一道驗收。逐鍵比對新舊
   `K1734_results.json`：除了改名的 claim 鍵、新增的 `preregistration_status`、
   以及 `finalize_experiment` 本來就宣告忽略的 `/generated_utc`、`/runtime_seconds`、
   `/runtime_env` 之外，**每一個統計量都必須 bit-for-bit 相同**。
   有任何數字動了 → 這次修改不只碰到 claim 層，**停下來查，不要放行**。
3. `grep -c '"accept"' k1734.py` → 0。
4. README 的 claim surface 同步降級（331 行中 35 行含 claim；集中在 §5 三個結果標題、
   §6 success criteria、§8 審查史）。README 也是 claim surface——
   **overclaim 是透過 README 抵達人類的**（`.claude/rules/experiments.md`）。
5. 重新產生裁決模板（**不可手抄**，schema 有三份副本必漂移的前科）：
   `uv run python scripts/experiment_gates.py verdict-template --path experiments/K1734 --out experiments/K1734/review_verdict.json`
6. 凍結後**不要再動 code**，再送終審——審完又改 code 會讓 sha 漂移，gate 會再擋一次。

---

## 為什麼這份規格停在這裡

`Edit` 寫入 `.claude/worktrees/dispatch-slot-1-1e5922b4-k1734/experiments/K1734/k1734.py`
在部門權限模式下被 deny。registry 宣告研究部 `owned_paths = ["experiments/"]`，
**但所有待修的實驗都住在 `.claude/worktrees/<name>/experiments/<kid>/`**，這個前綴不在轄區內。

本部門**不以 `git_writer_lock.py run -- git apply` 繞過**：那條路是平台工程部給的
「代 commit 既有檔案」入口，拿它去寫一份被 deny 的授權寫入，是用 git 權限換取沒有的寫入權，
不是走正規入口。（對照本班另一個發現：`git -C` 唯讀查詢確實一直在白名單裡，那個是誤判；
這個不是。）

**這不是 Codex 額度問題。** 額度（8/8 12:01）擋的是第二步終審；第一步從一開始就擋在寫入權。
