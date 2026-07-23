# 審查任務：k741 / k904 NFP canonical 修正（merge 前 certification review）

你是本專案的第二意見審查者（read-only sandbox）。目標：判定 branch `k741-nfp-canonical`
上的 NFP 修正是否可以合併進 main。**這份審查會被寫成 `experiments/<kid>/review_verdict.json`
的依據，PASS 才能合併**，所以請把它當成 gatekeeping review，不是建議書。

## 待審程式碼位置（linked worktree，已凍結）

根目錄：`/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-1-5741c175-k741`
（tip commit `a713e41ce`，branch `k741-nfp-canonical`，工作區乾淨）

主要待審檔案：

- `experiments/k741/k741_nfp_event_study_canonical.py`（新增；本次修正的主體）
- `experiments/k741/k741_nfp_event_study_canonical_results.json`
- `experiments/k741/README.md`
- `experiments/k741/nfp_canonical_vs_proxy_comparison.md`
- `experiments/k904/k904_task_s4_nfp_canonical.py`（新增）
- `experiments/k904/k904_task_s4_nfp_canonical_results.json`
- `experiments/k904/README.md`
- `paper/volatility-absorption/main_v3.tex`（NFP 表 tab:nfp / abstract / 相關敘述）
- `paper/volatility-absorption/reproduce.py`（NFP bindings 與 tolerance 收緊）

本次 6 個 commit（`git log a713e41ce -6`）：

```
6193c146a fix(k741,k904): NFP event dates from official BLS calendar, not first-Friday proxy
83c01201c fix(k741,k904): correct the correction - 2x2 factorial, window leak, endpoint
f737cfb7d fix(paper): Elevated-regime p was rounded up, 0.254 -> 0.253
aef29afe4 test(paper): tighten three NFP gate tolerances 5% -> 3%
ce6e17236 fix(k741,paper): test the regime contrast the paper actually claims - it does not hold
a713e41ce fix(k741,paper): separate observed trend rho from its bootstrap mean
```

## 背景（已由主線程驗過的事實，請當作 context 而非結論）

1. 舊 k741/k904 用「每月第一個週五」proxy 當 NFP 發布日；canonical 改用
   `volpred.data.event_dates.nfp_release_dates`（官方 BLS 行事曆）。194 vs 195 個日期、
   33 個不一致、1 個幻影發布（2025-10-03，政府停擺取消）、1 個漏抓（2013-10-22 補發，週二）。
2. 主線程已在該 worktree 跑過 `paper/volatility-absorption/reproduce.py`：**123/123 match,
   gate pass**（manuscript 印出的數字與 JSON 來源逐位對得上）。
3. 另有一個**獨立實作**（另一個 worktree，互不知情）跑出完全相同的 regime cells 與歸因結論，
   已判 AGREE。該獨立實作的報告在
   `/Users/yhlai0911/volpred-research/.claude/worktrees/dispatch-slot-3-b5fbc1f4-nfpcal/experiments/k741/nfp_calendar_fix_summary.json`
   （可讀，供交叉參考）。
4. 該獨立報告提出**一個尚未處理的 gap**，請你特別裁決（見下方必答問題 Q3）。

## 你必須做的事

逐檔精讀程式碼，不要只讀 README 或 JSON。特別檢查：

- **Lookahead bias**：訊號 t-1 / 報酬 t 的對齊；事件日到交易日的 mapping 是否只往前
  （forward-only）；有沒有把發布前的 session 錯配成事件日。
- **樣本窗**：所有表都宣稱 2010-2026，程式是否真的從 2010-01-01 起算（獨立報告指出舊版
  有 window leak，把 2009-12 的 22 個交易日留在 non-NFP 控制組）。
- **統計口徑**：Welch vs Student's t 的選擇是否與 main_v3.tex 的敘述一致；
  n=194 vs 3890 的極度不均衡樣本下哪個才對；bootstrap seed 是否固定；
  regime interaction bootstrap 的設計是否合理。
- **敘事強度是否超過證據**：ratio 1.1631、p_vs_all Student 0.0506 / Welch 0.0394 就卡在
  5% 邊界上；paper 的用詞是否誠實反映「邊界顯著」而非宣稱穩健。
- **資料與可重現性**：pinned snapshot 使用是否一致、有沒有偷跑 live fetch。

## 必答問題（請在報告中逐條回答）

- **Q1**：這 6 個 commit 有沒有任何 blocking defect（會讓結論失真的錯誤）？逐一列出，
  標明檔案:行號。沒有就明講沒有。
- **Q2**：Welch 還是 Student's？請給出你的裁決與理由。目前 canonical 分支用 Student's
  且已從 main_v3.tex 移除 "Welch's t-tests" 字樣；獨立報告主張應改用 Welch 並揭露兩者差異。
  這件事會改變 overall test 是否跨過 5%（0.0506 vs 0.0394），請明確裁決。
- **Q3**：`tab:nfp` 四個 regime 檢定沒有任何 multiplicity 揭露或校正。修正後的敘事比修正前
  更依賴 regime-level 顯著性（Low 從 p=0.069 變 0.009）。這是否為 **blocking**（合併前必須修）
  還是 **should-fix-before-submission**（可合併，投稿前補）？請裁決並說明對審稿人的風險。
- **Q4**：最終裁決 `PASS` 或 `FAIL`。**PASS = 這份 bytes 可以合併進 main**；FAIL 請列出
  必須修的清單（每條要能被機械驗證：檔案、症狀、修法）。

## 輸出格式

輸出純 Markdown 報告（會被存成 review artifact），開頭第一行必須是：

```
VERDICT: PASS
```
或
```
VERDICT: FAIL
```

接著依序寫：Q1 / Q2 / Q3 / Q4 四節 + 一節「合併後建議追蹤事項」。不要輸出 JSON，
不要嘗試寫檔（sandbox 為唯讀）。
