# K1692 — Codex primary-path review 記錄

**Reviewer**: Codex CLI 0.144.1, model `gpt-5.6-sol`, reasoning effort ultra, ChatGPT auth.
**Rounds**: 3（FAIL → PASS-with-minors → PASS confirm）。
**Final verdict**: **PASS**（blocking_defects = 0）。

## Round 1 — FAIL（4 blocking）
1. **[Critical] EWMA 初始化 lookahead**：seed 用前 21 筆報酬平方均值 → 早期 σₜ 含未來報酬。
2. **[Critical] NULL verdict 漏報二階 vol-of-vol Granger 顯著**：`granger_vov` 有 CL=F→SPY p=0.0002、USO→SPY p=0.0013 過 Bonferroni，但 verdict/README 未納入。
3. **[Critical] vov GFEVD 方向與 README 相反**：vov 系統油淨傳出（+0.07），README 概括宣稱油是接收方；且 bootstrap 只覆蓋 total、無 net-direction CI。
4. **[Critical] ADF 數字不可驗證**：README 引 ADF 但 K1692.py 未計算。

## 修正（全部落地並重跑，n=4985）
1. ewma_vol 改單點因果 seed（`prev=vals[first]`）+ 丟前 63 筆 burn-in；σₜ 嚴格只用 rₜ₋₁。
2. 加 `granger_vov` verdict 計數 + `controlled_identification_vov`（油報酬/VIX 控制）；README §4.3 揭露 vov 2/6 過 Bonferroni 但控制後 0/6（複製 K1665）。
3. README §4.4 同報一階 vol（油淨接收 −0.10）與二階 vov（油淨傳出 +0.07）兩系統 net，明說 proxy-dependent、量級小、無 net-direction CI。
4. `main()` 加 `adfuller` 計算，存 `stationarity_adf`；README ADF 數字與 JSON 對齊。

## Round 2 — PASS（4 minor）
4 個 blocking 全確認修好；僅剩 4 個 README 用詞/typo minor。

## Round 3 — 4 minor 已修 → PASS confirm
1. §4.1 標題改「一階 EWMA 條件波動」（非 realized-vol）。
2. §4.1 結論改「plain F 全部 nominally 顯著（4 對極顯著，USO→XOP 僅 nominal 5% p=0.011）」。
3. §4.2 blip (d) 改「OOS 未過嚴格門檻（CW t=1.66/p=0.049 僅 nominal）」。
4. §4.4 off-diagonal 算式改 ≈(total/100)·k ≈ 3。

Codex final: 「四個 minor 均已修妥，指定段落未見新問題或殘留過強敘述，維持 PASS。」

## Round 4 — pre-commit silent-fallback gate 合規（output-neutral）
pre-commit 的 silent-fallback-audit 抓到 `dy_bootstrap_ci` 的 `except Exception: continue`（bootstrap resample 失敗靜默跳過）。已改為：計數 `n_fail` + 迴圈後 `warn(...)` + `# silent-ok` 註記（跳過現在可觀察：n_fail 進 result、warn 上報）。**重跑證明數字完全不變**（n=4985、DY 61.5%/62.8%、CI [59.97,62.56]、nets −0.0996/+0.0703 全同，n_fail=0），只多 `n_fail` 欄。Codex round-4 確認此變更 output-neutral、維持 PASS。

## 開發過程自查（誠實留痕，非 Codex 抓到）
- `_residual_acf` pandas-Series index 對齊 bug（acf 恆 1.0）→ 改 `np.asarray` positional。
- verdict 判準 per-lag max|t| → joint Wald + Bonferroni。
- `experiment_gates.py` 抓到 nested-dm-misuse（OOS 用 raw DM 比較巢套模型）→ 改 canonical Clark-West；4 關全清。
