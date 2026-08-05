# 回讀驗證計畫 v2 — 含 fresh clone 情境（經理 D18 加驗要求）

- **產出部門**: resource_monitor
- **產出時間**: 2026-08-05
- **執行時機**: platform_eng 交付 fork root 修法、payload 完整性欄位、以及回填之後
- **執行者**: resource_monitor（本部門），用獨立管線 `tools/token_breakdown.py`
- **經理裁決**: D12 核准 6 項；D18 加第 7 項（fresh clone 情境）

---

## A. 原 6 項（D12 核准）

| # | 檢查項 | 期望值 | 讀哪裡 |
|---|--------|--------|--------|
| 1 | Codex billable（fork root 去重後） | **136,756,562** | `by_provider.codex.billable_total` |
| 2 | Codex 邏輯 session 數 | **131** | `by_provider.codex.sessions` |
| 3 | 平台 billable | **180,312,894** | `totals.billable_total` |
| 4 | `by_session` top-N 不再出現同 root 的分身 | root `019f8e4d` 單列 **106,410,266** | email drilldown 的 Session 段 |
| 5 | 日報不再出現「今日 0」 | 08-05 之後每日皆非 0 | `storage/notifications/` 新寄出的 body |
| 6 | ~~`weekly_2026-07-31.json` 非 0~~ | **已撤回**（期間未結束，0 與中間值都正常） | — |

第 6 項於 2026-08-05 撤回，理由見 `2026-08-05_period_semantics_ruling.md`。
以下 §B 的回填驗證取代它的位置。

## B. 回填驗證（D18 裁定該回填的三批）

期望值全部來自本部門獨立 telemetry 重算，**不經 `token_usage_report.py`**，
所以它們是真正的外部對照，不是自我驗證。

### B1. daily 2026-07-21 ～ 07-28（八天，目前全是 0）

| 日期 | 期望 billable |
|------|--------------|
| 2026-07-21 | 17,846,231 |
| 2026-07-22 | 11,107,846 |
| 2026-07-23 | 36,368,645 |
| 2026-07-24 | 10,083,983 |
| 2026-07-25 | 2,709,675 |
| 2026-07-26 | 47,196,080 |
| 2026-07-27 | 52,097,542 |
| 2026-07-28 | 44,786,864 |
| **合計** | **222,196,866** |

**交叉驗證已通過**：`weekly_2026-07-24`（238,499,898）− 已回填的 07-29＋07-30
（81,625,754）＝ 156,874,144，與上表 07-24..07-28 逐日加總**完全相同**。
兩條互不相干的路徑對得上，這組期望值可直接採用。

容差：0（同一 UTC 日界、同一 telemetry 來源，應完全一致）。
若不一致，先查是不是日界口徑差異，再查修法。

### B2. 五份永久凍結的 weekly（05-29 ～ 06-26）

這五份目前的值是 mid-period 部分期間值，**回填後必然上升**。
本部門**尚未**重算它們的真值（每個 7 日窗約 4–5 分鐘，五個約 25 分鐘），
所以這裡不給期望數字——**給不出來就不給，不用推估的數字冒充期望值**。

回填完成後由本部門重算並比對；platform_eng 回填時請通知我，我再跑。

先可做的一致性檢查（不需重算，立刻可驗）：

| 檢查 | 現況 | 回填後應該 |
|------|------|-----------|
| 相鄰週重疊區間的加總一致性 | `weekly_2026-07-19`（19.8M）與獨立重算的 07-21..07-25（78.1M）矛盾 | 所有相鄰週在重疊日上的隱含值不再互相矛盾 |
| `unique_sessions` 序列平滑度 | 07-19 = **63**，相鄰週 516／390／726／799 | 不再出現數量級跳水 |

### B3. F5 — `weekly_2026-07-19`

期望：**> 78,116,380**（這是下界，僅由 07-21～07-25 五天構成；
該週還含 07-19、07-20 兩天，本部門未重算）。
現值 19,844,277，低估至少 58,272,103（≥2.9 倍）。

**這是下界不是期望值**：回填後只要 ≤ 78,116,380 就一定還是錯的；
高於它不代表就對了，仍需與逐日重算對照。

## C. 第 7 項：fresh clone 情境（D18 新增）

經理原話：「修完要驗證一次 fresh clone 情境，不然這個 bug 會在下次移機時原地復活。」

### C1. 為什麼需要它

完整性判斷目前存在 `path.stat().st_mtime`（`summaries.py:513`）。
實測確認**所有報表 payload 都沒有自我描述欄位**：

```
weekly_2026-05-29.json  generated_at: False  period_end: False  period_complete: False
weekly_2026-07-31.json  generated_at: False  period_end: False  period_complete: False
daily_2026-08-04.json   generated_at: False  period_end: False  period_complete: False
```

而 git 的 tree object 不儲存 mtime，checkout 時以當下時間寫入工作區檔案——
所以 clone／移機後，**每一份報表的 mtime 都會晚於它的 period_end**，
`_report_covers_its_period()` 一律回 `True`，那些本該重產的空殼從此凍結。

### C2. 驗證方式：用 `os.utime` 模擬，不要真的 clone

真 clone 慢、依賴環境、且不適合放進 CI。用 `os.utime` 把 mtime 設成「現在」
就能精確重現 clone 後的狀態，而且是確定性的。建議直接落成 regression test
（`tests/` 底下，platform_eng 決定檔名），四個 case：

| case | payload | mtime | 期望 |
|------|---------|-------|------|
| 1. 新格式・期間未結束 | `generated_at` < `period_end` | **設成現在**（模擬 clone） | `covers == False` ← **這是防回歸的關鍵 case** |
| 2. 新格式・期間已結束 | `generated_at` ≥ `period_end` | 設成很久以前 | `covers == True`（payload 說了算，mtime 不影響） |
| 3. 舊格式（無欄位）・mtime 早於 period_end | — | 早於 | `covers == False`（fallback 相容） |
| 4. 舊格式（無欄位）・mtime 晚於 period_end | — | 晚於 | `covers == True`（fallback 相容） |

**case 1 是整條規則的核心**：它現在會失敗（回 `True`），修好後必須回 `False`。
沒有這個 case，這個 bug 會在下次移機時原地復活——而且是靜默復活。

### C3. 修法驗收條件

1. `token_usage_report.py` 產出的每份報表 payload 帶 `period_end`（exclusive, UTC ISO date）
   與 `generated_at`（UTC ISO datetime）
2. `_report_covers_its_period()` 優先讀 payload；**只有欄位缺失時**才 fallback 到 mtime
3. 上表四個 case 全綠
4. 既有 196 份無欄位的舊檔行為不變（case 3／4 保證）

---

## D. 誠實邊界

- **「git 不儲存 mtime、clone 以當下時間寫入」本部門未在此環境實測**：
  權限模式擋下 `git clone`、`git checkout-index`、`git ls-tree`。
  這條依據的是 git 的既定行為，以及原作者在 `_report_covers_its_period()` docstring
  中自己寫下的前提（"a fresh clone stamps every historical report with a time after
  its period"）——他描述的是同一個機制，只是看到正面。
- **「報表 payload 沒有自我描述欄位」是實測**（上方 C1 的輸出）。
- **B2 不給期望數字**：五份 weekly 的真值需要約 25 分鐘重算，本輪未做。
  給不出來就不給，不用推估值冒充期望值。
- **B3 的 78,116,380 是下界不是期望值**，已在該節標明。
