# btc-gas-negative 審查修正 log（2026-06-10，主線程 fable-5）

## HIGH（6/6 處置）

| # | Finding | 處置 |
|---|---------|------|
| 1 | §8/附錄捏造 robustness 數字（R0 CRITICAL 未修） | ✅ §8 全段重寫：區分「implemented safeguards（有 archive：shift(1) + Codex review 2026-04-17 + degenerate-regime filter）」vs「planned robustness（5 項，無數字宣稱）」；所有無來源點估計（shift-removal、96% dispersion、±60 天 −3.5/−4.9、L2 +2.4、LOO −3.91/−5.24、ETH/BNB）全部移除；明記 planned 跑完落 JSON 前不得轉 .tex |
| 2 | abstract/標題/結論「MS underperforms GJR-N」方向錯（JSON: MS 1.98699 < M1 1.99261 略勝 NS） | ✅ 標題改「Rescues to Parity, Not Superiority」；abstract/Contribution 3/§9 conclusion 三處改 parity 表述 + DM +0.28 NS 揭露 + 參數成本 |
| 3 | K1129 動機統計量錯誤歸屬（-4.67 是 K1133b P1 的，K1129 無 2017-2020 OOS） | ✅ Contribution 1 + Sec2 puzzle 兩處重 frame：K1133/K1133b 是 -4.67 的來源；K1129（OOS 2021+，≈-4.6）重新定位為 cross-asset anomaly 動機 |
| 4 | ν>30「effectively Normal」捏造（ms_fit_log max ν=15.48） | ✅ §6 改真實範圍（高 ν state 7.1–15.5、低 ν state 2.8–6.9）+「partial de-fattening」弱化版推論，刪 revealed-preference 強宣稱 |
| 5 | Period 3 日期錯 2 年（2024 → 實際 OOS 2026Q1） | ✅ 兩處改 2026-01-05→2026-04-14 + 重新詮釋為「spot-ETF 制度成熟 2 年後窗口」（750 天 warm-up 解釋） |
| 6 | §3.4 估計法描述與 hybrid Gray/Klaassen 實作不符 | ✅ 重寫為 hybrid 如實描述 + 近似條件不滿足的揭露（p00∈[0.42,0.85]）+ 引導 replication 跟 archived code；Gray (1996) 需補進 references（殘項） |

## 殘項（轉 .tex 前置）
1. **計量重跑**：§8 planned 5 項 robustness 真跑落 `k1133b_robustness_results.json`
2. Gray (1996) bibitem + 其他 R0 cleanup（Newbould typo、缺 bib 等 — 見 audit_findings MEDIUM/LOW）
3. data snapshot CSV 落地 + reproduce.py（§3.1 宣稱的 data/ 目錄不存在）
4. MEDIUM 7 項（HLZ threshold 統一、70/30→76/24、state duration 矛盾、kurtosis 來源、MCS、Period 2 描述等）

## 2026-06-11 Codex 收尾

- active paper surface 已同步到 parity 口徑：README、experiments、data_sources、drafts 全部改成「MS-GAS-t rescues to parity, not superiority」。
- K1129 / K1133 歸因已拆清：`-4.67` 改回 K1133 / K1133b 的 2017--2020 OOS 結果；K1129 只保留作 2021+ anomaly 動機，不再錯掛為該統計量來源。
- Period 3 日期與敘事已改成 `2026-01-05 -> 2026-04-14` 的 2026Q1 post-warm-up window；舊的 2024 日期已從 active draft 移除。
- 未落地的 robustness 一律降級為 planned work，不再在正文或 appendix 口徑中假裝已完成；ETH / BNB replication、leave-one-year-out、alternative loss/cutoff 均如此。
- 仍然存在的真正 blocker 也明寫保留：paper-local snapshot CSV 尚未落地，`reproduce.py` 尚未建立，所以這篇仍不應宣稱 submission-ready 或 reproducible end-to-end。
