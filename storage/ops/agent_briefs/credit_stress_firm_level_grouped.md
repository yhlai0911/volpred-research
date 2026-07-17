# 信用壓力 → 高槓桿 AI 股波動率：firm-level 分組檢定（控制 VIX 為硬門檻）

**Model**: claude-opus-4-8 / xhigh (per model_router experiment)
**Task**: assign_43a2ee48 (P2, experiment, starved)
**來源**：老闆 2026-07-16 Telegram msg877（財經捕手 SpaceX 破發文）
**Worktree cwd**: `.claude/worktrees/dispatch-slot-1-79726798-credit-firm`（只在此 worktree 寫檔；禁碰主 checkout 的 feed.json / supabase / knowledge.json）

## 必讀先前 NULL 教訓（aggregate 版已做過且全 NULL，不得重做）
- **K872**：FRED HY OAS 對 fwd vol raw r=0.55，但與 VIX corr=0.77，**控制 VIX 後 delta-R²=0**。
- **T14**：credit+yield 僅 +1.6% incremental R²（econ trivial）。
- **K1621**：EM sovereign credit vol proxies 不 lead EM equity vol。
- **K1529 / K1515 / K1538**：同軸皆弱。
開工前先 grep 這些 K 讀原文，README 記錄讀到什麼。

## 本題唯一差異化空間 = firm-level 分組對比
文章真正主張是 **issuer-specific**：高槓桿公司（ORCL、CRWV 等）自己的信用壓力 → 自己的 equity vol。

**設計**：
- **分組**：高槓桿 AI 標的（如 ORCL、CRWV 等，依實際可得資料選）vs 低槓桿 hyperscaler 對照組（MSFT / GOOGL）。
- **模型**：HAR-RV baseline vs HAR-RV-X（加 lagged credit spread Δ 為 exogenous）。
- **樣本**：2015–2026，須含兩次空頭。
- **Lookahead**：嚴格 `signal.shift(1)`，README 附 mechanical audit。
- **評估**：QLIKE + DM-HLN + Harvey |t|>3 + canonical HAC bandwidth。

## 硬性成功門檻（比一般更嚴）
1. 主檢定必須是「**控制 VIX 之後**」的增量：加 VIX 當第二 exogenous，或先對 VIX 正交化後再看 credit Δ 的增量。
2. **高槓桿組的增量必須顯著大於低槓桿對照組**（分組差異才是文章可檢定的含義）。
3. 單純 raw 相關顯著 = **直接 NULL 結論**（K872 已證那是 VIX 的影子）。

## 資料限制（如實揭露）
- 個股 CDS 需 Markit（付費）不可得 → 用 **HY / IG OAS + 個別公司債 ETF proxy**，限制如實揭露於 README。
- **SPCX n=22 天樣本不足**，只能當 case illustration，**不得入檢定**。
- 文章的具體數字（-40%、6/22 -16.5%、250 億美元、7.5% 殖利率）**未經查證，不得引用為事實**。

## 成功標準（三件套齊 + 誠實）
- `experiments/credit_stress_firm_level/`：README.md + .py + results.json（= result-artifact）+ 圖表 + 參考文獻。
- results.json 含：分組定義、每組 QLIKE、控制 VIX 後增量、DM/Harvey 統計量、樣本期間/n、資料來源與 proxy 限制。
- **null 如實報告**（很可能又是 NULL；那也是有價值的結果，明確寫「firm-level 亦無控制 VIX 後的增量」）。
- README 末段「COLLECTION NOTES」：一句話結論、關鍵數字 3 個、是否具 feed 文章價值（若 NULL 則建議不發文，記 knowledge）。

## 禁止事項
禁假數字、禁 same-day 訊號乘 same-day 報酬、禁把 raw 相關當結論、禁引用未查證文章數字、禁寫 knowledge.json、禁 git push / --no-verify。
