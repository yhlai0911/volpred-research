---
name: experiment-rerun-economics
description: 決定一次實驗重跑要順手修掉哪些東西。當你已經確定某個 experiments/<kid> 非重跑不可（修 blocking defect、補檢定、解 blocker、修 bug）時使用，避免因為漏修而預約下一次同樣的重跑。不涵蓋要不要重跑本身，也不涵蓋審查流程。
---

# 實驗重跑的機會成本

## 什麼時候讀這份

**你已經確定要重跑某個實驗**——不是在考慮要不要重跑。觸發情境：

- 審查判 FAIL，缺陷要改程式
- 要補一個新檢定（等價檢定、DM、bootstrap⋯）
- 某個 blocker 解掉了，整支終於跑得完
- 發現 bug 要修

## 為什麼要有這份

**一次重跑的成本不是 CPU 時間，是「重跑 → 結果 JSON 全變 → README 全改 → sha 漂移 → 重審」
這條完整的鏈。** 跑一次 10 分鐘，但走完那條鏈是一整班。

**同一個坑本部門踩過兩次**（這就是它從 `memory/notes.md` 升級成程序的原因）：

- **2026-08-05 k892**（D38）：解掉 `^TWII` blocker 讓整支跑得完之後才發現，
  腳本收尾是裸 `json.dump`、**根本沒呼叫 `finalize_experiment`**，所以跑幾次都不會有
  `reproduce_spec.json`。當時的推論「A 卡住所以 B 做不了 → A 通了 B 就會好」是跳躍。
- **2026-08-05 signforecast**（D47-1）：修 rev2 三項缺陷要重跑，**同一個 `finalize_experiment`
  缺口又出現一次**，而且資料源是 yfinance 即時抓取——截止日隨執行日推進，等於不可復現。

第二次同形狀 = 不是意外是流程。

## 動手前的清單（重跑之前跑完，不是之後）

每一條都問「**不趁這次修，下次還要不要再跑一遍？**」答「要」就現在修。

### 1. 收尾是不是 `finalize_experiment`？

```bash
grep -n "json.dump\|write_text\|finalize_experiment" experiments/<kid>/<kid>.py
```

看到裸 `json.dump` / `write_text` 收尾 → **必改**。`reproduce_spec.json` 與
`reproduce_commit.json` 只能在 run 時由同一次 `trace_file()` 產生，**事後補是失效模式**
（K1708）。不改的話 merge 會被 `check_experiment_artifacts.py` 擋，而那時你要重跑。

```python
from volpred.research.reproduce_spec import finalize_experiment
out, spec = finalize_experiment(
    results=results, entrypoint=Path(__file__).resolve(),
    canonical_result="<kid>_results.json", exp_dir=HERE,
    inputs=[...],           # 釘住的資料檔
    outputs=["figures/x.png", ...],
    seeds=[("numpy", SEED), ...], started_at=started_at)
```

### 2. 資料是不是移動標的？

```bash
grep -n "yf.download\|requests.get\|fredapi\|read_html\|urlopen" experiments/<kid>/<kid>.py
```

命中 → **釘快照**。yfinance 尤其危險，它有**兩個**移動維度：截止日隨執行日推進，
且配息後歷史調整價會被整條重述。live fetch 的實驗**沒有可復現的數字**。

做法：`experiments/<kid>/data/pinned_*.csv`，快照存在就讀它、不存在才抓並立刻寫入，
另留一個明確的重新釘入口（環境變數），並在 README 寫明「重新釘會改動每一個數字，是刻意的」。

### 3. 結果 JSON 會不會有裸 NaN／Infinity？

Python 的 `json` 預設**發出也接受**裸 `NaN`，自家工具一路綠燈，但那不是 RFC 8259
合法字面值——嚴格 reader（`JSON.parse` / Go / serde / jq）**拒收整份檔案而不是該欄位**。

收尾前遞迴把非有限 float 轉 `None`（numpy scalar 先 `.item()`，否則 `np.float64('nan')` 漏網），
**並把替換筆數宣告在結果 JSON 裡**——替換要是宣告出來的，不是偷偷做的。

驗收：`json.loads(text, parse_constant=會拋錯的函式)` 通過才算數。

### 4. 有沒有 local 實作蓋掉 canonical？

```bash
grep -n "def dm_test\|def qlike\|def hln\|def clark_west" experiments/<kid>/<kid>.py
```

`.claude/rules/experiments.md` 禁止自寫 DM／QLIKE 蓋掉 canonical。要另寫必須以
`volpred.stats.model_evaluation` 為下限／對照。重跑是換掉它的唯一無痛時機。

### 5. 產物有沒有診斷面？

如果 README 有任何「無 silent fallback」「全部收斂」「已檢查 X」這類**宣稱**，
問：**讀者能從產物驗證嗎？** 不能就是缺陷（signforecast rev2 缺陷 1 就是這個）。
把逐項診斷寫進結果 JSON，不要只寫在 README。

## 重跑之後：數字不准手抄

結果 JSON 一變，README 每一格都要重生。**手打是抄錯的藏身處，而抄錯就是 claim surface
上的假數字。** 寫一支腳本把每一列從 JSON 重建，再回頭斷言 README 含有那個字串。

2026-08-05 signforecast 實測：這道檢查抓到一處殘留的舊資料截止日，
而前面五道 gate（`experiment_gates`、`check_experiment_artifacts`、嚴格 JSON、ratchet、
silent-fallback audit）**一道都沒抓到**——它們不看散文。

## 反向的陷阱：診斷顯示「全部正常」時

計數器回報 0 的時候，**先證明計數器是活的**再寫進 README。
`warning_tally = {}` 有兩種成因：真的零警告，或掛勾根本沒生效——而後者就是你剛聲稱修好的那個缺陷。

做法：另跑一支探針，故意觸發一個已知會發生的警告（例如 `LogisticRegression(max_iter=1)`
的 `ConvergenceWarning`），確認它進得了計數器。**沒驗過的空值不能當證據寫。**

## 不要順手做的事

- **不要批次修存量檔案**。被 `reproduce_commit.json` / `review_verdict.json` pin 住 sha256 的
  改了就要重審，一支 sed 會把一堆已認證實驗打回未認證。走 ratchet：
  **新實驗被 gate 擋一次就學會，舊實驗只在有人本來就要重跑它時順手修。**
- **不要手改 `review_verdict.json`**。裁決只值它當下審的快照；改它等於教 agent
  「把 review 檔改掉就過了」。sha 漂移導致 certify 擋下來**是預期行為，不是故障**。
- **不要為了讓 gate 變綠而縮小 scope**。`experiment_artifact_exclusions.json` 只放行
  artifact gate、不放行 certify，用它等於拿一個例外換一份看不見的研究。

## 收尾驗收（六道，全過才算可重審）

```bash
uv run --extra dev python scripts/experiment_gates.py run --path <dir>
uv run python scripts/check_experiment_artifacts.py check --path <dir>
uv run --extra dev python scripts/experiment_gates.py certify --path <dir>   # 預期 BLOCKED
```

加上：嚴格 JSON 解析、README 數字回頭核對、相關 ratchet 測試。
`certify` **BLOCKED 是對的**——它在等重審，不是在報錯。
