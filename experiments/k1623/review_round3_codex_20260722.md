# K1623 round-3 — Codex primary-path review

**Verdict: FAIL**（3 個 blocking defects，merge 維持封鎖）

| 欄位 | 值 |
|---|---|
| Reviewer | Codex CLI 0.144.6 / gpt-5.x / `-s read-only`（primary path） |
| Reviewed at | 2026-07-22T10:06:11+08:00 |
| Reviewed commit | `2029296479e449fccb21804bba958570f346b218`（branch `worktree-dispatch-slot-2-c5cafe39-k1623`） |
| Reviewed bytes | 31/31 pinned sha256 逐檔重算，全數相符（`review_verdict.json.reviewed_sha256`） |
| Review mode | READ-ONLY，未修改、未重跑任何 MC |

## 為什麼還要這一輪

先前覆蓋只有 agy PASS + `feature-dev:code-reviewer` CONDITIONAL PASS，兩者皆 fallback path。
依 K1259 教訓（fallback PASS ≠ primary-path PASS），primary-path 是放行前置條件。
任務單原本以「Codex 額度耗盡至 2026-07-25」為由凍結約 3 天；該前提已於 2026-07-22 08:2x
被實測推翻，本班照真實可用狀態執行。

**結果證明這一輪不是形式主義**：primary path 找出 3 個 fallback 兩輪都沒抓到的 blocking defect，
其中第一個是 arm 設計本身的口徑錯誤，不是措辭問題。

## Codex 確認沒問題的部分

- **1.21–1.33x 這個 headline 數字成立**。五個資產的 `sd_A / SE`、表格、分解與四捨五入
  全部對得上 frozen artifact。
- **無 RNG / reordering / parallelism / lookahead 缺陷**。
- **Arm B−C 的口徑是對的** —— 它確實量到「估計 segment mean 相對於單一 global demeaning 的
  incremental 成本」，與 README 的說法一致。

## Blocking defects

### 1. A−B / `f3` 的名字與它實際量的東西不符（設計層，非措辭）

`k1623_rev3_armc_mc.py:170` — Arm A **重跑 BIC 選擇**，同時選斷點的**個數與位置**；
Arm B 則把整個 partition 固定。因此 A−B 與 `f3` 混合了 **break-count selection** 與
**break-location estimation** 兩個通道，並沒有隔離出它宣稱的 `break_location`。

要嘛改名（連同 README 與 artifact 的通道命名），要嘛重新設計 arm A 讓兩者真的分開。

### 2. 2/2/1 的 dominant-channel attribution 撐不起「已識別」的措辭

README §6.4 已經寫出 3.2% 的 MC 噪音，但下一句仍斷言精確的 2/2/1 勝出與 asset-dependent 主導。
- SPY 差距 0.31% —— 明顯未識別（噪音大一個數量級）。
- N225 3.45%、TW0050 4.08% —— 同樣貼著 crude single-SD error，沒有 paired covariance
  或 replication-level draws 就分不出來。
- 「每個 individual factor 都真的 > 1」對接近 1.01 的 factor 同樣沒有支撐。

只有**總量** 1.21–1.33x 與 MC 噪音充分分離。attribution 應降級為 descriptive point
estimates + 明寫「dominance not identified at 500 reps」。

注意這比 collector 自己記下的還嚴一級：collector 說「嚴格看只有 VIX 穩健」，
但 README 仍保留 asset-dependent 的分類；Codex 的裁決是那個分類本身就不該留。

### 3. README §1 line 77 與 Arm C 自相矛盾

line 77 仍寫「MC **只涵蓋斷點定位**、不涵蓋段均值估計」—— Arm C 的整個存在理由就是涵蓋了段均值估計，
§6.4 也已經這樣寫。同一份 README 兩處打架。

## 後續

- `review_verdict.json` 維持 fail-closed 擋 merge；branch `worktree-dispatch-slot-2-c5cafe39-k1623`
  **不得合併**。
- 三項 defect 進 rev4 remediation 單。修完 bytes 會變，31 個 pin 必須整份重簽，
  因此本輪不在 branch 上填模板 —— 填了也會立刻失效，反而製造「已簽過」的假象。
  本檔即為 round-3 的正式 review artifact 與 verdict 記錄。
