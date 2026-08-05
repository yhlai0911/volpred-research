# nfp_20260807_t2 認證審查（read-only；Codex 額度鎖 → fallback）

你是 nfp_20260807_t2 收養落地的認證 reviewer。已發佈文章（2026-08-05 事件溫度計，feed mile_63e0e1ff）
引用本實驗 —— 你的裁決守的是已上線主張的復現誠實性。

## 對象（唯讀）：/Users/yhlai0911/volpred-research/.claude/worktrees/nfp-t2-adopt/experiments/nfp_20260807_t2/
nfp_20260807_t2.py（28302 bytes；自作者 session transcript 重放復原、sha 與 runtime spec 釘值逐位元吻合）、
README.md（收養時主線程補寫，數字程式化）、nfp_20260807_t2_results.json、events/controls csv、window.png、
reproduce_spec.json（runtime-born）、reproduce_commit.json、data/（BLS 行事曆 + VIX 收盤）。

## 已機械驗證（可挑戰不必重做）
- 8 個 quarantine 產物 sha256 對 reproduce_commit 逐一相符；entrypoint sha 97a21197 與復原檔逐位元相符
- 4 個 per-path integrity gates PASS；artifacts gate PASS

## 審查重點（file:line 證據）
1. Lookahead：事件窗 T-3 close→T-1 close 的日期對齊；BLS 行事曆日期 vs 交易日 mapping；控制窗建構
   （rolling two-return）有無滲入事件段
2. HAC 推論：overlap 控制樣本的 NW lag=22 是否合理；lag 敏感度表誠實性；n=3788/191/3597 的樣本會計
3. NULL 表述：README 與（更重要）已發佈文章的「這段沒有比平常多動」是否被 t=-1.06 p=0.288
   CI[-2.53,+0.75] 支撐、無過度宣稱（NULL=偵測不到，效果點估 -0.89pp 方向反而偏負）
4. 資料快照：VIX 截至 8/4 收盤、行事曆至 8/5 —— 對 8/7 事件的 T-2 視角是否成立（無未來資料）
5. seed/隨機性：本設計是否有隨機程序（bootstrap?）；spec randomness 宣告一致性

## 輸出（開頭四行先出，防截斷）
VERDICT: PASS 或 FAIL
REVIEWER: <真實身分> (fallback path)
BLOCKING_DEFECTS:（無則 none）
RESIDUAL_RISKS:
