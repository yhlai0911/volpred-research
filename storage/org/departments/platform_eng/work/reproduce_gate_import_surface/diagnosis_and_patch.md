# reproduce gate 整檔 hash → 改採 import-surface 比對（診斷 + 定稿修正 + 實測）

- 來源：論文部 request `item_20260805T091934819770Z_reproduce-gate-hash-commit-unver`
- 部門：platform_eng ｜ 2026-08-05（台灣時間）
- 狀態：**設計已用真實 repo 實測驗證通過；程式碼未落地**（寫入被權限閘擋下，見 §6）

## 1. 論文部的證據：獨立重驗，全部成立

我沒有轉抄，逐項自己算過：

| 主張 | 我的重驗 | 結果 |
|---|---|---|
| spec 記錄的 hash 是 `9f868e41f^` 版本 | `git show 9f868e41f^:…` 的 sha256 = `29c6f80d1d39…` | ✅ 一致 |
| 唯一動過該檔的相關 commit 是 `9f868e41f` | `git log -- src/volpred/stats/model_evaluation.py` | ✅（8 筆歷史，最新一筆即它）|
| 改動只在 `strategy_dm_test` | AST 逐 top-level def 比對 `9f868e41f^` vs HEAD | ✅ 唯一變動者 = `strategy_dm_test` |
| 兩個實驗只用 `dm_test` / `qlike_pointwise` | grep 兩支 entrypoint 的 import | ✅ `k1699.py:75`、`K1710.py:88` |
| 這兩個符號沒變 | AST 比對 | ✅ 兩版完全相同 |

即：gate 目前把一個**與實驗完全無關**的改動判成 `INPUT_HASH_MISMATCH`，而且
`scripts/reproduce_check.py:1174-1183` 在判定後**直接 return，不執行重跑**——
所以連「跑跑看數字有沒有變」這條退路都被堵死。這不是誤報加噪音，是**gate 把唯一能
產生證據的路也一起關掉了**。

## 2. 根因層級

`audit_experiment()` 用 `spec["inputs"][].sha256` 做**整檔** sha256 比對
（`scripts/reproduce_check.py:1169-1173`）。整檔 hash 的語意是「這個**檔案**沒變」，
但實驗真正依賴的是「我 import 的那些**符號**沒變」。共用模組必然會因為別人的功能而
變動，所以在共用模組上，整檔 hash 與實驗的實際依賴面**永遠會發散**——
`model_evaluation.py`、metrics、scoring helper 全都是這個形狀。

後果不只兩支實驗：**任何共用模組被動一行，所有依賴它的實驗同時失去 reproduce 認證**，
而論文 `paper/prg-periodic-garch/main.tex:118` 的
「every number reproduces bit-identically」因此拿不到現行 receipt 背書。

## 3. 採用方案：論文部建議的 (a)，但比較單位是**傳遞閉包**不是單一函式

只 hash「被 import 的那個 def」是不夠的——它可能呼叫同模組的 helper、讀模組級常數，
那些變了它的行為就變了，但它自己的 bytes 一模一樣。**比較單位必須是：從被 import 的
符號出發、在模組層可達的所有名字的傳遞閉包。**

三個保守退路（任一成立就退回整檔比對，fail closed）：

1. 來源用 `import <module>` 或 `from <module> import *` → 整個模組都在作用面內；
2. 模組頂層有 def / import / 賦值以外的敘述（import 期副作用）→ 局部比對不成立；
3. spec 記錄的那個版本在 git 歷史裡找不到 → 沒有比對基準。

不需要改 spec schema：spec 只記了整檔 sha256，而**那個版本可以用內容 hash 反查 git
歷史**（`git log -- <path>` 逐 commit 比 blob hash）。實測在本例反查到 `42ec9aa70`，
與 `9f868e41f^` 內容同一份。舊 spec 全部相容，不用 migration。

receipt 誠實性：判定為無關時**照常執行重跑**，並在 report 記
`discovery.input_scope = {"basis": "import_surface", "whole_file_mismatch_waived": [...]}`，
每筆帶 `recorded_version_commit`、`imported_symbols`、`compared_symbol_closure`、
`closure_digest`。論文引用時說得出「bit-identical 的基準是什麼」，
而不是把一個放寬過的 gate 說成沒放寬。這同時滿足論文部建議的 (b)；(c) 的 `--force`
不需要——人工判定正是我們要消除的東西。

## 4. 已實測（不是紙上設計）

原型完整實作於
`/private/tmp/.../scratchpad/import_surface_prototype.py`（本 session 產出，非 repo 檔），
直接跑真實 repo：

```
=== k1699 / K1710
  WAIVED   src/volpred/stats/model_evaluation.py
           recorded version = 42ec9aa70
           imported symbols = ['dm_test', 'qlike_pointwise']
           closure compared = ['Tuple', 'dm_test', 'np', 'qlike_pointwise', 'stats']
           closure digest   = 50253b9d8cfbebde
```

閉包正確地把 `dm_test` 可達的模組層名字（`np`、`stats`、`Tuple`）一併納入。

負控制與突變測試（安全性主張的關鍵，全過）：

```
closure(strategy_dm_test) 跨該 commit 不同        -> fails closed (correct)
whole-module `import volpred.stats.model_evaluation` -> 退回整檔比對 (correct)
在 dm_test 函式體內插一行                          -> digests 改變，fails closed (correct)
把可達的 `from scipy import stats` 改成別的綁法     -> digests 改變，fails closed (correct)
只動閉包外的 top-level（strategy_dm_test / 新增未用函式）-> digests 相同，waivable (正是目的)
```

## 5. 待套用修正

### P1 — `scripts/reproduce_check.py` import 區

```python
import argparse
import ast          # <- 新增
import datetime as dt
```

### P2 — 在 `_git_file_sha256()` 之後新增五個 helper

（完整程式碼見同目錄 `import_surface_helpers.py`，逐字貼入即可，
函式名與本檔一致：`_module_name_for_path`、`_imported_symbols`、
`_module_symbol_digests`、`_historic_blob`、`_import_surface_waiver`。）

### P3 — `audit_experiment()` 的 `bad_inputs` 判定（約 1169-1183 行）

原本：

```python
    bad_inputs = [
        str(path.relative_to(root))
        for path, item in zip(input_paths, spec["inputs"])
        if path.is_file() and _sha256(path) != item["sha256"]
    ]
    if missing_inputs or bad_inputs:
        _set_outcome(
            report,
            status="unverified",
            reason_code="INPUT_MISSING" if missing_inputs else "INPUT_HASH_MISMATCH",
            severity="warn",
            reproducible=None,
            summary=f"missing={missing_inputs}; hash_mismatch={bad_inputs}",
        )
        return _finish_report(report, report_path, write_report)
```

改為：

```python
    changed_inputs = [
        (str(path.relative_to(root)), item["sha256"])
        for path, item in zip(input_paths, spec["inputs"])
        if path.is_file() and _sha256(path) != item["sha256"]
    ]
    # A whole-file hash answers "did this file change?", but what the experiment
    # depends on is "did the symbols it imports change?".  On a shared module the
    # two diverge by construction -- someone else's feature lands and every
    # experiment importing anything from that file loses its receipt, and the
    # gate then refuses to rerun, so not even "do the numbers still match?" can
    # be asked (2026-08-05: k1699/K1710 lost certification to a +3-line change
    # confined to strategy_dm_test, which neither experiment imports).  So a
    # changed input is only fatal when the change reaches this experiment's
    # import surface; every fallback path below keeps the old behaviour.
    surface_sources = [root / entry_rel, *_code_surface_files(exp_dir)]
    waived_inputs: list[dict[str, Any]] = []
    bad_inputs: list[str] = []
    for rel_path, recorded_sha in changed_inputs:
        waiver = _import_surface_waiver(root, rel_path, recorded_sha, surface_sources)
        if waiver is None:
            bad_inputs.append(rel_path)
        else:
            waived_inputs.append(waiver)
    report["discovery"]["input_scope"] = {
        "basis": "import_surface" if waived_inputs else "whole_file",
        "whole_file_mismatch_waived": waived_inputs,
    }
    if missing_inputs or bad_inputs:
        _set_outcome(
            report,
            status="unverified",
            reason_code="INPUT_MISSING" if missing_inputs else "INPUT_HASH_MISMATCH",
            severity="warn",
            reproducible=None,
            summary=f"missing={missing_inputs}; hash_mismatch={bad_inputs}",
        )
        return _finish_report(report, report_path, write_report)
```

### P4 — 回歸測試（新檔 `tests/test_reproduce_import_surface.py`）

至少覆蓋本檔 §4 的五個案例：閉包外改動可放行、閉包內改動 fail closed、
可達依賴改綁 fail closed、`import <module>` 退回整檔、歷史查不到版本退回整檔。
測試用臨時 git repo 自建，**不得**依賴 `model_evaluation.py` 當下的內容
（那會讓測試隨真實檔案漂移）。

### P5 — 驗證與結案

```bash
uv run --extra dev pytest tests/test_reproduce_import_surface.py -q
uv run python scripts/reproduce_check.py run --experiment k1699
uv run python scripts/reproduce_check.py run --experiment K1710
```

結案條件：兩支都真的**執行完重跑**並產出 receipt；receipt 內
`discovery.input_scope.basis == "import_surface"` 且列出被放行的檔案與符號閉包。
拿到 receipt 後回頭通知論文部，`main.tex:118` 的 MAJOR finding 才可解除，
且論文那句話應同步改成引用 receipt 的比對基準，不要停在「bit-identical」而不說基準。

## 6. 阻塞

修復面在 `scripts/reproduce_check.py` 與 `tests/`，platform_eng 的 `owned_paths`
只有 `frontend-v2-fix/`，`Edit` 被權限閘擋下（本輪第二次；前一次同因見
`work/alert_control_gate_source_health_20260802/`）。設計已實測、程式碼已定稿，
**但一行都沒有落地**。等經理對 owned_paths 的裁決
（`item_20260805T090132643067Z`）。
