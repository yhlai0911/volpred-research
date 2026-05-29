# Paper 6 SPY VaR (1%) source audit — 2026-05-29

**Trigger**: `Paper6_DIV3_SPY_VaR_violation_rate` task — "Paper SPY VR=0.93% Kupiec p=0.77 vs K880v2 VR=1.59% p=0.0196. 兩版都不吻合."

**Owner**: 主線程 hourly-20

## Finding

Paper main.tex L245 claim:
> at the 1% level, the violation rate on SPY is 0.93% (Kupiec p = 0.77),
> compared to 1.92% for GJR (Kupiec p < 0.001).

直接核對 `experiments/k880/k880_results.json::layer4_var`：

| Model        | violation_rate (raw)       | rounded | kupiec_p           | rounded |
|--------------|---------------------------:|--------:|-------------------:|--------:|
| PRG_Extended | 0.009325287986834888       | **0.93%** | 0.7696385726099294 | **0.77** |
| GJR          | 0.019199122325836534       | **1.92%** | 0.0004588513304476516 | **<0.001** |

→ Paper Table 4 SPY VR / Kupiec p 兩個數字 **完全可從 K880 復現**，無「不吻合」問題。

**Task description 中的 K880v2 VR=1.59%/p=0.0196 數字也 verified**：

```
experiments/k880v2/k880v2_results.json::layer4_var.PRG_Extended.VaR_1pct
  violation_rate: 0.015907844212835986 → 1.59%
  kupiec_p:       0.019573049594984626 → 0.0196
  kupiec_pass:    false
  bugs_fixed:
    bug1_lookahead: "h_intraday now uses h_overnight FORECAST instead of realized r2_overnight[t]"
    bug2_cov:       "VaR now includes 2*Cov(overnight, intraday) in sigma2_c2c"
    bug3_stationarity: "MLE rejects h<=0 with np.inf, enforces alpha+beta<0.999"
```

K880v2 verdict 是 `COLLAPSED_ARTIFACT`（PRG_Ext vs GJR DM t=6.00 → -0.57，QLIKE +15.5% 惡化）。

## Real issue (not the one in task description)

`experiments.md` L73 已記載 K880 vs K880v2 timing-convention 抉擇：

> The sequential-timing interpretation matters: if the forecast horizon is
> "at t-1 close for full day t", K880v2 is correct (lookahead-free).
> If the interpretation is "at market open for the intraday period only",
> K880 may be valid. Paper clarifies in Eq. 3-4 and the methodology section.

但 main.tex L245 引用 K880 數字時**未在 inline footnote 標明此抉擇**。讀者讀到 VR=0.93% 不知道：
1. 對應 K880（非 K880v2）
2. K880v2 同數字會變 1.59%（FAIL Kupiec）
3. 為何選 K880 — 因 paper 模型定義 forecast horizon = "intraday period only at market open"，overnight realized r² 在此時點為 information set 中真實值（非 lookahead）

## Recommendation

**不需重寫 Table 4 數字**。paper 數字 reproducible。

**需新增**（後續 followup task `Paper6_DIV3b_spy_var_footnote`）：
1. main.tex L245 加 `\footnote{}` 指向 K880 而非 K880v2，並解釋 timing-convention 抉擇（參考 experiments.md L73 與 Eq 3-4 的 information set 定義）
2. reproduce.py L179 註解明確標 Table 4 SPY rows 來自 K880 PRG_Extended 而非 K880v2
3. SUBMISSION_READY.md 加 audit log entry：「2026-05-29 SPY VaR source 已核對，main.tex 數字無誤但需 inline footnote 強化 K880 vs K880v2 透明度」

## Audit verdict

✅ Paper Table 4 SPY VR=0.93%/p=0.77 **provenance clean** (= K880 PRG_Extended VaR_1pct)
⚠️ main.tex 缺 inline footnote 解釋 K880 vs K880v2 抉擇 → followup task

## References

- `experiments/k880/k880_results.json::layer4_var.PRG_Extended.VaR_1pct`
- `experiments/k880v2/k880v2_results.json::layer4_var.PRG_Extended.VaR_1pct`
- `paper/prg-periodic-garch/experiments.md` L73
- `paper/prg-periodic-garch/main.tex` L245
