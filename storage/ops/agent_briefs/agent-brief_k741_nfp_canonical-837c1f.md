# Brief — volatility-absorption 論文 NFP 表污染修復（task `assign_1238781f`, P1）

**Model**: opus / xhigh (per model_router, task_type=experiment)
**Worktree (你的 cwd)**: `.claude/worktrees/dispatch-slot-1-5741c175-k741`（branch `k741-nfp-canonical`，已從 main 建好）
**來源**: `docs/governance/2026-07/firstfriday_proxy_sweep_20260719.md` §3
**論文 stage**: revision — 這是**投稿前 blocker**

## 背景（已查證，不必重查）

`paper/volatility-absorption/main_v3.tex` 的 NFP 表數字，逐位對齊
`experiments/k741/k741_nfp_event_study_results.json` 的 `part_a_historical`
（main_v3.tex:391 有字面註解標明 source）。但 k741 的 NFP 日期用
**first-Friday proxy**（`k741_nfp_event_study.py:42-51`，
`days_until_friday=(4-d.weekday())%7`），該 proxy 已知有 **13 個錯誤日期、7 類缺陷**。
k904 是佐證 reproduction（n_nfp=196），`task_s4_nfp` 同樣用 proxy；
`task_s2_shock_types`（|ΔVIX|>2 分類）不碰 NFP 日期 → **S2/shock-type 數字乾淨，不要動**。

Canonical 日曆 accessor：`volpred.data.event_dates.nfp_release_dates`
（2026-07-19 已根修 `min()` + cadence gate，commit 305d118a3）。

### 目前 main_v3 的受污染數字（重跑後要逐一比對）
- Abstract L43 / L72；Results L368-396；Table `tab:nfp` L375-391
- Overall: 1.14× vs 全非 NFP (p=0.081)、1.16× vs 週五 (p=0.061)、N_NFP=195、2010–2026
- Regime: Low(<15) 1.24× (t=1.85, p=0.069, n=62)｜Medium(15-20) 1.30× (p=0.009)｜
  Elevated(20-25) 1.18× (p=0.279, n=27)｜High(≥25) 0.95× (p=0.777, n=28)｜Wilcoxon p=0.0037

## 要做的事

### 1. 重跑 k741 part_a（canonical 日曆）
- **不要就地改封存腳本**。新建 `experiments/k741/k741_nfp_event_study_canonical.py`
  （或 `k741r/`，你判斷；但要在 README 說清楚新舊關係），把日期來源換成
  `nfp_release_dates`，其餘方法學（event window、ratio 定義、t/Wilcoxon 檢定、
  VIX regime 切點 15/20/25、樣本期間 2010–2026）**逐項比對原腳本後 1:1 沿用**。
  方法學若被迫改動，必須在輸出 JSON 記 `methodology_deltas` 欄位並在報告點名。
- 輸出 `experiments/k741/k741_nfp_event_study_canonical_results.json`，
  結構含 `part_a_historical`（同 schema，便於逐位對照）+
  `provenance`（日期來源、n_nfp、日期集合 diff vs proxy：新增/移除各幾天、哪幾天）。

### 2. 重跑 k904 task_s4_nfp
- 同上，只換日期來源。輸出 `experiments/k904/k904_task_s4_nfp_canonical_results.json`。
- **`task_s2_shock_types` 不重跑、不改**。
- 注意 `paper/volatility-absorption/experiments/k904_paper8_shock_nfp_fix.py` 是副本，
  主檔在 `experiments/k904/`。副本要不要同步在報告裡建議，不要擅自改論文目錄下的檔。

### 3. 新舊對照表
產出 `experiments/k741/nfp_canonical_vs_proxy_comparison.md`：
每個受污染統計量一列（舊值 / 新值 / 絕對差 / 顯著性是否翻轉 / n 變化）。
**顯著性翻轉、方向翻轉、n 大幅變動要顯眼標出**。

### 4. main_v3.tex 更新 —— 分情況處置
- **數字位移但方向與顯著性結構不變** → 直接更新 abstract L43/L72、Results L368-396、
  `tab:nfp` 全部數字，並在 Results 加一句說明日期來源為官方 NFP release calendar。
- **方向翻轉或主要顯著性消失** → **不要硬撐敘事**。降級：把 NFP 段改成
  「proxy 修正後不再支持 / 僅弱支持」的誠實陳述，或在報告裡提出「移除 NFP 小節」選項
  交主線程裁決。論文已聲明 SAR headline 不依賴 NFP 單一結果（main_v3:398），有降級空間。
- 無論哪條路，`main.tex` / `main_v2.tex`（1.17× 舊 framing）**不動**，v3 是最新。
- 改完跑 `xelatex` 確認可編譯。

### 5. feed 回溯範圍（**只判定，不執行**）
k528（feed×7）/ k661（feed×2）同屬此 error class。依你的重跑結果判斷：
數字位移是否大到需要發更正（erratum）。在報告裡給明確建議 + 影響篇數清單，
**不要自己改 storage/ 或發文**。

## 硬規則

- 🚫 **禁止假數字**。所有數字必須來自你實跑的 JSON。研究誠實 > 一切。
- 🚫 不要寫 `storage/memory/knowledge.json`（主線程負責）。
- 🚫 不要 `git push`、不要 `--no-verify`、不要動 main。你在 worktree 裡 commit 即可。
- ✅ **知道自己不確定就說**。跑不出來、方法學對不上、資料缺口 → 在報告裡明講，
  不要用近似值糊過去。
- ✅ 收尾前在 worktree 內 `git add` + `git commit`（訊息說明 what + why）。
- ✅ 寫 `experiments/k741/README.md` 補一段：canonical 重跑的存在與結論。

## 成功判準

1. 兩個 canonical results JSON 存在且含真實跑出的統計量 + provenance 日期 diff
2. 對照表列齊所有受污染數字的新舊值，翻轉項有標記
3. main_v3.tex 已更新（或已明確提出降級/移除建議並說明為何不自行改）
4. xelatex 可編譯（若有改 tex）
5. feed 回溯建議清單（k528×7 / k661×2）已給
6. worktree 已 commit

## 你的最終回覆（= 回傳值，不是給人看的信）

一段結構化摘要：新舊關鍵數字對照、是否翻轉、main_v3 處置方式、
feed 回溯建議、以及**你不確定或沒做到的部分**。
