---
name: reference_nested_forecast_inference_gap
description: 巢狀模型 + pinball/QLIKE 等一般損失 + expanding window 的預測比較，文獻上沒有可用推論方法
metadata: 
  node_type: memory
  type: reference
  originSessionId: 0ced801b-c57e-4491-a65d-03113ec27ccf
  modified: 2026-07-21T07:08:08.728Z
---

比較「大模型 vs 同模型關掉某係數區塊」（nested）時，raw DM 統計量不是漸近常態 —— 虛無下兩者母體預測重合、loss differential 退化。這件事本身已知；**非顯而易見的是三個限制條件在文獻上只被兩兩解決，從未同時解決**（2026-07-21 K1731 F1 對原始文獻查證）：

| 方法 | nested | 一般/不可微損失 | recursive(expanding) |
|---|---|---|---|
| West (1996) Econometrica 64(5) | ✗ | ✗ | ✓ |
| **McCracken (2000) JoE 99(2)** | ✓ | ✓ | ✓ |
| Clark & McCracken (2001) JoE 105(1) | ✓ | ✗ | ✓ |
| Clark & West (2006/2007) JoE 135/138 | ✓ | ✗ | ✓ |
| **Giacomini & White (2006) Econometrica 74(6)** | ✓ | ✓ | ✗ |
| Giacomini & Komunjer (2005) JBES 23(4) | ✓ | ✓(tick) | 可能 ✗ |
| Pitarakis (2025) Econometric Theory 41(1) | ✓ | ✗ | ✓ |

實務結論：

- **Clark-West 不能用在 pinball/QLIKE**。它的修正是平方誤差的代數運算，沒有 general-loss 版本。引用它只能當「偏誤方向的機制說明」，不能當檢定依據。同理 Clark-McCracken、Pitarakis 全是 quadratic-only。
- **McCracken (2000) 是唯一三格全中的**，但兩個坑：nested 極限是非標準的（Brownian functionals），且要拿到 DGP-free 極限**必須「估計用的損失 = 評估用的損失」**。用 MLE/MCMC 配適、拿 pinball 評分的設計直接違反這條 —— 這是最容易漏看的一條。
- **唯一乾淨可用的路是 Giacomini & White (2006)**：允許 nested + 一般損失，但 Theorem 1 要求 `m < ∞`、Comment 2 明文排除 recursive。代價是換設計（改 fixed rolling window），而且**估計對象變了** —— 界的是「兩個預測程序在固定視窗下的期望損失差」，不是 macro 的母體預測內容。虛無為真時這個量是**正的**（大模型仍在估雜訊係數），所以區間落在 0 以上不等於「母體沒用」。
- **Calhoun 的條件方向常被記反**：他要求 `P²/T → 0`（P 相對小），而且大 P 會讓檢定 undersized、低檢定力、**偏向較簡單的基準模型**。不能拿來當「P 大所以常態近似沒問題」的依據。

Repo 端：想把 GW fixed-memory 當 primary claim，`scripts/audit_nested_dm_misuse.py` 要求
`primary_unconditional_gw_dm_fixed_memory` role —— manifest + runtime envelope + **外部 reviewer PASS receipt**（至今只有 K1709 過關）。沒 receipt 就只能標
`nested-dm: diagnostic-only`，數字不得進任何 claim sink。相關：[[feedback_research_rigor]]、[[feedback_paper_multi_round_review]]。
