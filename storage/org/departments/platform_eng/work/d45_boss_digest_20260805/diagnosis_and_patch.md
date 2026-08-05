# D45｜老闆日報為什麼「只剩雜訊」——經理的假說對了一半，另一半會導向錯的修法

- 日期：2026-08-05（台灣時間 19:2x）
- 部門：platform_eng
- 工作項：manager D45（`item_20260805T111959791797Z`）
- 狀態：**根因已定位並量化，程式未落地**——`scripts/org/` 正被**活躍** session f5153fb1
  持有（11:22:18Z 取得，正在寫 `inbox_archive.py`）。不硬搶，修法定稿在此交付。

## 1. 經理的三個症狀，逐項驗證

| 症狀 | 實測結果 |
|---|---|
| 1. Write 對經理子樹全 deny | **已在程式面修好**（不是仍然壞的） |
| 2. `send-alert` 對經理 Bash deny | 未驗（不在本輪範圍） |
| 3. digest 只剩 P3 cc | **部分成立，但機制與經理的推論不同** |

### 症狀 1：已由 commit `407a367e9`（19:02:27）修好

`org_attach.py::generate_dept_settings` 現在對 `dept == MANAGER` 給
`meta = {"owned_paths": ["storage/org/"]}`（:170-179），註解明寫這是為了讓協調者能寫
registry、bulletin 與自己的 outbox。
`storage/org/runtime/manager.settings.json` **確實存在**（19:04 生成，862 bytes）。

所以這條不需要再修，需要的是**重新 attach**——經理現在跑的 session 是在該 commit 之前
拿到設定的，記憶體裡那份仍是舊的。這與治理部提醒過的「a17aa310c 之前啟動的 session
拿不到新權限」是同一件事。

### 症狀 3：不是「digest 只吃 cc」，是「digest 什麼都吃、但完全不排序」

`boss_digest.py::render()`（:36-51）把 `manager/inbox` 底下**每一個**非 boss 項目
全部列出，**沒有 kind 過濾、沒有優先序排序、沒有數量上限、沒有截斷**，順序是
檔名（＝時間戳）遞增。

11:22Z 實測（`--dry-run` 全量解析，非目測）：

```
rendered lines: 1931        dept bullets: 122
bullets by priority:  P1=54   P2=24   P3=44
bullets containing 知會: 41
manager/inbox 全量: 129 項（P1=61 P2=24 P3=44；kind: report=75 cc=41 assignment=7 decision=6）
```

**54 則 P1 全都在信裡**，只是排在 41 則 cc 後面——因為 cc 到得早。
經理看到「26 則全是 P3 cc」，是讀了一份 1931 行輸出的**開頭**。

這件事重要，因為它換掉修法：如果照經理的假說去「補上被漏掉的 kind=report/decision」，
會發現沒有東西可補（它們本來就在），而信仍然一樣沒用。
**真正的缺陷是排序與體積，不是選取。**

### 症狀 3 的另一半：經理的下游推論成立

`manager/outbox/digest_pending.md` **不存在**、`manager/outbox/proposals/` **是空的**，
所以「## 經理彙報」與「## 待核准提案」兩個區塊整段沒有渲染。這確實是症狀 1 的下游。
但**修好症狀 1 不會讓症狀 3 自癒**——即使 outbox 有內容，54 則 P1 仍然埋在 41 則 cc 底下。

## 2. 三個缺陷（都在 `render()`，一次改完）

1. **不排序**：輸出是到達順序，於是「噪音因為來得早而結構性壓過決策」。
2. **不過濾 cc**：`kind` 欄位存在（cc/report/decision/assignment）卻完全沒被讀。
   部門之間往來會自動知會經理，那是組織內帳，老闆對它沒有任何動作。
3. **不截斷**：整段 `task` 原文 inline，122 則 → 1931 行。

## 3. 定稿修法（可直接套用，落點 `scripts/org/boss_digest.py::render`）

```python
    reports = sorted((root / "manager" / "inbox").glob("*.json"))
    dept_reports = []
    cc_count = 0
    corrupt: list[str] = []
    for path in reports:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            corrupt.append(path.name)
            continue  # silent-ok: corrupt items are surfaced in the ⚠️ section below
        if item.get("from") == "boss":
            continue
        # 部門之間往來會自動 cc 經理，那是組織內帳不是老闆要動作的事。
        # 2026-08-05 它們是 122 則裡的 41 則，而且到得最早，所以按時間排的
        # 輸出把它們全部放在決策上面。從老闆的清單移除但計數，不靜默。
        if item.get("kind") == "cc":
            cc_count += 1
            continue
        dept_reports.append(item)
    if dept_reports:
        # 依優先序而非到達順序。2026-08-05 的日報 1931 行、54 則 P1 埋在底下，
        # 經理讀了開頭就判斷這條通道只剩 cc。重要的一半在摺線以下的
        # 老闆信，即使每個 byte 都在，也已經失敗了。
        rank = {"P1": 0, "P2": 1, "P3": 2}
        dept_reports.sort(key=lambda i: rank.get(str(i.get("priority") or "P3"), 2))
        lines += ["## 部門上報", ""]
        for item in dept_reports:
            lines.append(
                f"- [{item.get('priority', 'P3')}] **{item.get('from')}**: "
                f"{_headline(item.get('task'))}"
            )
        lines.append("")
    if cc_count:
        lines += [f"_另有 {cc_count} 則部門間知會（kind=cc），未列入——完整內容在 manager/inbox_", ""]
```

搭配一個模組級小函式：

```python
HEADLINE_CHARS = 160


def _headline(task: object) -> str:
    """One scannable line per item; the full text already lives on disk.

    Inlining whole task bodies turned 122 items into 1931 lines, which is how
    54 P1 reports became invisible without a single one being dropped.
    """
    text = " ".join(str(task or "").split())
    return text if len(text) <= HEADLINE_CHARS else text[:HEADLINE_CHARS - 1] + "…"
```

## 4. 回歸驗證（經理要求回讀式，不接受「程式碼看起來對了」）

套用後必須跑 `uv run python scripts/org/boss_digest.py --dry-run` 並確認：

- 第一則 bullet 的優先序是 **P1**（現況是 P3）
- 輸出行數從 **1931** 降到約 **90–110**（122 − 41 則 cc，每則一行 ＋ 區塊標題）
- 出現 `另有 41 則部門間知會（kind=cc），未列入`
- 經理重新 attach 後寫入 `digest_pending.md`，該檔內容出現在「## 經理彙報」區塊

建議同時在 `tests/`（本部門轄區）立一條機械斷言：
**渲染結果中，任何 P1 bullet 都不得排在任一 P3 bullet 之後**，並斷言 cc 不進清單。
這條擋得住「日後又有人按時間排」的復發。

## 5. 誠實的邊界

- 症狀 2（`send-alert` 對經理 deny）**本輪未驗**，不宣稱。
- 20:30（台北）那班 digest：**這份修法沒有落地就趕不上**，因為檔案在別人手上。
  持有者的 claim 11:22:18Z 取得、TTL 約 45 分鐘（約 12:07Z ／台灣 20:07 到期）。
  若對方先收尾，仍來得及；若沒有，**明講趕不上**（D45 (d) 的要求）。
- 本部門**沒有**用 `VOLPRED_ALLOW_CONCURRENT_WRITE=1` 硬搶，也沒有 release 別人的活躍 claim
  ——對方 11:22:18Z 才取得、正在寫 `inbox_archive.py`，不符合「session 已停工」的釋放條件。
