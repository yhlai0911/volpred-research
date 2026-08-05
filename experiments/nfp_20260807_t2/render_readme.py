#!/usr/bin/env python3
"""Render this experiment's README from its results JSON.

Why a renderer and not a hand-written README: the reader-facing prose is part of
the claim surface, and a hand-typed number is a claim nobody re-derived.  K1709
shipped a README asserting a bound its code never established, which is exactly
the failure mode a transcribed digit produces.  Every number below is read out of
``nfp_20260807_t2_results.json`` at render time, so the README cannot drift away
from the archived result without the drift being a re-render away from visible.

Prose (framing, caveats, what the numbers mean) is authored here; digits are not.
Re-run after any change to the results file:

    uv run python experiments/nfp_20260807_t2/render_readme.py

``--check`` re-renders and exits non-zero if the committed README differs, so the
same command works as a drift test.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXPERIMENT_DIR = Path(__file__).resolve().parent
RESULTS_PATH = EXPERIMENT_DIR / "nfp_20260807_t2_results.json"
SPEC_PATH = EXPERIMENT_DIR / "reproduce_spec.json"
README_PATH = EXPERIMENT_DIR / "README.md"
FIGURE_NAME = "nfp_20260807_t2_window.png"


def pct(value: float, digits: int = 2) -> str:
    """Percent-valued statistic, sign preserved (results store percent units)."""
    return f"{value:+.{digits}f}%"


def pp(value: float, digits: int = 2) -> str:
    """Percentage-point effect size, sign preserved."""
    return f"{value:+.{digits}f} pp"


def num(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}"


def pval(value: float) -> str:
    return f"{value:.3f}"


def ci(low: float, high: float) -> str:
    return f"[{low:+.2f}, {high:+.2f}]"


def cn_count(n: int) -> str:
    """Small counts as Chinese numerals, so quantities stay derived, not typed.

    The review that gated this file caught `兩格` / `三個 lag` / `五個 output` typed
    as literals in the prose: correct on the day, silently wrong on the next
    re-render. Anything countable goes through here.
    """
    numerals = "零一二三四五六七八九十"
    # 兩, not 二 — but only as a standalone numeral before a measure word, which
    # is what every call site here is. Inside a compound numeral the digit stays
    # 二 (十二, not 十兩), so the substitution belongs on this branch alone.
    if n == 2:
        return "兩"
    if 0 <= n <= 10:
        return numerals[n]
    if 10 < n < 20:
        return f"十{numerals[n - 10]}"
    return str(n)


def render(results: dict[str, Any], spec: dict[str, Any]) -> str:
    data = results["data"]
    sample = results["sample"]
    ev = results["event_window"]
    ct = results["control_window"]
    pri = results["primary_inference"]
    lags = results["hac_lag_sensitivity"]
    clean = results["release_clean_control_sensitivity"]
    naive = results["naive_iid_reference"]
    dec = results["week_decomposition"]
    decay = results["event_day_and_decay"]
    wk = decay["weekday_controlled"]
    ev_day_reg = wk["event_day_vs_ordinary_days"]
    next_day_reg = wk["day_after_vs_ordinary_days"]
    regimes = results["regime_conditional"]
    target = results["target"]
    matched = target["matched_regime_stats"]
    sib = results["sibling_study"]
    trace = results["code_trace"]
    env = results["runtime_env"]

    lag_keys = sorted(lags, key=int)
    lag_rows = "\n".join(
        f"| {k} | {pp(lags[k]['effect_pct_points'])} | {num(lags[k]['hac_se'])} | "
        f"{num(lags[k]['hac_t'])} | {pval(lags[k]['p_two_sided'])} | "
        f"{ci(lags[k]['ci95_low'], lags[k]['ci95_high'])} |"
        for k in lag_keys
    )

    regime_rows = "\n".join(
        f"| {r['regime']} | {r['n_event']} | {pct(r['event_final2_mean_pct'])} | "
        f"{pct(r['control_final2_mean_pct'])} | {pp(r['hac_effect_pct_points'])} | "
        f"{ci(r['hac_ci95_low'], r['hac_ci95_high'])} | "
        f"{pval(r['hac_p_two_sided'])} | {pval(r['hac_p_holm'])} |"
        for r in regimes
    )

    dropped = data.get("vix_invalid_rows_dropped") or []
    dropped_txt = "、".join(dropped) if dropped else "無"

    limitations = "\n".join(f"{i}. {line}" for i, line in enumerate(results["limitations"], 1))

    n_regimes = len(regimes)
    min_holm = min(r["hac_p_holm"] for r in regimes)
    n_regime_nominal = sum(1 for r in regimes if r["hac_p_two_sided"] < 0.10)
    nominal_cells = [r for r in regimes if r["hac_p_two_sided"] < 0.10]
    nominal_all_cover_zero = all(
        r["hac_ci95_low"] <= 0 <= r["hac_ci95_high"] for r in nominal_cells
    )
    nominal_ci_clause = (
        "而它們的 95% CI 都涵蓋 0 ——" if nominal_all_cover_zero
        else "而其中至少一格的 95% CI 不涵蓋 0 ——"
    )
    matched_covers_zero = (
        matched["hac_ci95_low"] <= 0 <= matched["hac_ci95_high"]
    )
    matched_ci_clause = "（涵蓋 0）" if matched_covers_zero else "（不涵蓋 0）"
    n_inputs = len(spec.get("inputs") or [])
    n_outputs = len(spec.get("outputs") or [])

    return f"""# {results['experiment_id']} — 非農前最後兩個交易日的 VIX 路徑

狀態：**結論為 `{results['verdict']}`**；analysis class =
`{results['analysis_class']}`。這份 evidence package 服務事件內容槽
`{results['generated_for']}`。

姊妹研究 `{sib['experiment_id']}` 測的是整個事件前週，結論同為 `{sib['verdict']}`：

> window: {sib['window']}
> relation: {sib['relation']}

也就是說，本研究存在的理由是一個具體的可否證假說：六日平均把只發生在最後 48 小時的
移動稀釋掉了。把窗口縮到最後兩個交易日，如果稀釋說成立，效果應該浮現。

## 問題

> {results['question']}

窗口定義：

> {ev['definition']}

這不是非農當日反應研究，也不是交易策略；條件變數只使用 T-2 讀者在寫作當下
已經看得到的收盤。

## 資料與 information set

- VIX：{data['vix_source']}，requested start {data['vix_requested_start']}，
  as-of {data['vix_as_of']}，有效 {data['vix_observations']:,} 列；無有效收盤而移除的列：{dropped_txt}。
- 事件日曆：{data['release_source']}，選取規則 = {data['release_selected_rule']}；
  snapshot 取得時間 {data['release_snapshot_acquired_at']}。用官方 release 日期而非
  「每月第一個週五」proxy，是承接既有 knowledge：該 proxy 會錯配並翻轉方向性結論。
- 樣本：{sample['n_releases_matched']} 次可對上交易日的公布日，
  {sample['first_release']} 至 {sample['last_release']}。
- {cn_count(n_inputs)}個 input snapshot 位於 `data/`，由 `reproduce_spec.json` 逐檔綁 sha256，
  正常重跑 `network=deny`，不受來源後續回補或修訂影響。
- 隨機性：seeds = {env['seeds'] or '[]'}，無 bootstrap／Monte Carlo／抽樣。

## 方法

推論之前先處理兩件事。

**1. exact interval overlap。** 控制窗與排除算式：

> {ct['definition']}
> {ct['exclusion_math']}

逐段 interval 驗證而非整段近似，留下 {ct['n']:,} 個控制窗。

**2. overlapping outcomes 不是 iid。** 控制窗是 daily rolling 兩日變化，彼此大量重疊，
把它們當獨立樣本會低估標準誤。primary test 因此改為：

> method: {pri['method']}
> reason: {pri['reason']}

primary lag = {pri['lag']}。

## 結果

### 描述統計

mean／median／sd／mean abs 四欄的單位皆為「窗口內 VIX 百分比變化」，不是 VIX 指數點；
n 是窗口個數，share up 是窗口中變化為正的比例。

| | n | mean | median | sd | share up | mean abs |
|---|---|---|---|---|---|---|
| 事件窗（T-3→T-1） | {ev['n']} | {pct(ev['mean_pct'])} | {pct(ev['median_pct'])} | {num(ev['sd_pct'])}% | {num(ev['share_up_pct'],1)}% | {num(ev['mean_abs_pct'])}% |
| 控制窗 | {ct['n']:,} | {pct(ct['mean_pct'])} | {pct(ct['median_pct'])} | {num(ct['sd_pct'])}% | {num(ct['share_up_pct'],1)}% | {num(ct['mean_abs_pct'])}% |

### Primary inference

事件指標效果 {pp(pri['effect_pct_points'])}（HAC se {num(pri['hac_se'])}，
t = {num(pri['hac_t'])}，p = {pval(pri['p_two_sided'])}，
95% CI {ci(pri['ci95_low'], pri['ci95_high'])}；n = {pri['n']:,}，
其中事件 {pri['n_event']}、控制 {pri['n_control']:,}）。

**點估計是負的**：非農前最後兩個交易日的 VIX，平均比同長度的非事件窗**低**約
{num(abs(pri['effect_pct_points']))} 個百分點。但 CI 涵蓋 0，且上界達
{num(pri['ci95_high'])} pp —— 資料無法區分「小幅下滑」「無效果」與「小幅上升」。
稀釋假說沒有得到支持：把窗口縮短並沒有讓效果浮現。

### 穩健性

HAC lag sensitivity：

| lag | effect | HAC se | t | p | 95% CI |
|---|---|---|---|---|---|
{lag_rows}

{cn_count(len(lag_keys))}個 lag 的結論一致（p 介於 {pval(min(lags[k]['p_two_sided'] for k in lag_keys))} 與
{pval(max(lags[k]['p_two_sided'] for k in lag_keys))}），效果點估計不隨 lag 改變 ——
lag 只影響標準誤。

release-clean control（{clean['definition']}）：丟掉
{clean['n_control_dropped']} 個控制窗後效果 {pp(clean['effect_pct_points'])}，
p = {pval(clean['p_two_sided'])}，CI {ci(clean['ci95_low'], clean['ci95_high'])}。同樣不顯著。

naive iid 參照（{naive['note']}）：Welch p = {pval(naive['welch_p'])}，
Mann–Whitney p = {pval(naive['mannwhitney_p'])}。Mann–Whitney 的 {pval(naive['mannwhitney_p'])}
正是把重疊窗誤當獨立樣本會買到的「接近顯著」—— 保留它是為了顯示未修正檢定會宣稱什麼，
不承載任何結論。

### 週內分解

> {dec['note']}

| 半段 | n returns | mean | mean per return | share up |
|---|---|---|---|---|
| 前段 T-7→T-3 | {dec['early_T7_to_T3']['n_returns']} | {pct(dec['early_T7_to_T3']['mean_pct'])} | {pct(dec['early_T7_to_T3']['mean_per_return_pct'])} | {num(dec['early_T7_to_T3']['share_up_pct'],1)}% |
| 後段 T-3→T-1 | {dec['final_T3_to_T1']['n_returns']} | {pct(dec['final_T3_to_T1']['mean_pct'])} | {pct(dec['final_T3_to_T1']['mean_per_return_pct'])} | {num(dec['final_T3_to_T1']['share_up_pct'],1)}% |
| 全週 T-7→T-1 | {dec['full_T7_to_T1']['n_returns']} | {pct(dec['full_T7_to_T1']['mean_pct'])} | {pct(dec['full_T7_to_T1']['mean_per_return_pct'])} | {num(dec['full_T7_to_T1']['share_up_pct'],1)}% |

兩個半段的每 return 平均符號相反。**這是純描述性分解，前段從未被檢定過**：
本研究唯一經過 HAC 推論的窗口是後段（primary test），姊妹研究測的是全週
{sib['window']}，也不是前段。因此「前段有效果、後段沒有」不是本 package 能支持的說法 ——
符號差異在這裡只是待檢定的觀察，不是結果。

### 事件日與衰退

> {decay['definition']}

未修正的無條件平均：事件日
{pct(decay['event_day']['mean_pct'])}（share up {num(decay['event_day']['share_up_pct'],1)}%），
隔日 {pct(decay['next_day']['mean_pct'])}（share up {num(decay['next_day']['share_up_pct'],1)}%）。
這兩個數字本身不可讀作事件效果：

> {wk['note']}

加入 weekday 固定效果與 HAC 後：

- 事件日 vs 一般日：{pp(ev_day_reg['effect_pct_points'])}，
  p = {pval(ev_day_reg['p_two_sided'])}，CI {ci(ev_day_reg['ci95_low'], ev_day_reg['ci95_high'])} —— 不顯著。
- 隔日 vs 一般日：{pp(next_day_reg['effect_pct_points'])}，
  p = {pval(next_day_reg['p_two_sided'])}，CI {ci(next_day_reg['ci95_low'], next_day_reg['ci95_high'])}。

隔日那條是本研究**唯一**名目上跨過 0.05 的檢定，而且只是勉強跨過
（p = {pval(next_day_reg['p_two_sided'])}，CI 下界 {num(next_day_reg['ci95_low'])} pp 幾乎貼著 0）。
它沒有經過多重比較修正，也不是本研究的 primary question。**不應該被當成發現報導**；
它至多是一個值得另一個預先登記的研究去測的方向。

### regime 條件切分

| VIX regime | n event | 事件窗 mean | 控制窗 mean | HAC effect | 95% CI | p | p (Holm) |
|---|---|---|---|---|---|---|---|
{regime_rows}

{cn_count(n_regimes)}個 regime cell 全部在 Holm 修正後不顯著（最小 p_holm = {pval(min_holm)}）。
未修正的 p 有{cn_count(n_regime_nominal)}格落在 0.1 以下，{nominal_ci_clause}
這正是為什麼要修正，也是為什麼 CI 欄不能省。

### 圖：`{FIGURE_NAME}`

左 panel 是事件窗與控制窗的分佈疊圖；右 panel 是{cn_count(2)}段事件前 per-return 平均，
外加公佈當天。

**右 panel 第三根長條需要一個 README 層級的更正**：它標為「T-0 當天」，取自
{pct(decay['event_day']['mean_pct'])}，也就是上一節那個**未修正、混淆於星期效果**的
無條件平均。它有三個問題，圖上都沒有標示：(1) 它不屬於「公佈前」，而是公佈當天；
(2) 它是本圖最高的長條並因此決定 y 軸尺度，但同一個量在加入 weekday 固定效果後只剩
{pp(ev_day_reg['effect_pct_points'])}（p = {pval(ev_day_reg['p_two_sided'])}，不顯著）；
(3) 它沒有誤差線。**不要把這根長條讀成「非農當天 VIX 平均下跌
{num(abs(decay['event_day']['mean_pct']))}%」的發現** —— 本 package 的裁決是
`{results['verdict']}`，圖中沒有任何一根長條代表已被證實的效果：第一根從未被檢定
（見上節），另{cn_count(2)}根的檢定都不顯著。

## 對目標事件的意涵

目標：{target['release']} 公布，內容槽 `{target['publishing_slot']}`，
條件收盤 {target['conditioning_close']}（交易日標籤 {target['conditioning_trading_day_label']}），
VIX = {num(target['vix'],1)}，落在 regime `{target['regime']}`。

該 regime 的歷史 cell（n = {matched['n_event']}）給出 HAC 效果
{pp(matched['hac_effect_pct_points'])}，95% CI
{ci(matched['hac_ci95_low'], matched['hac_ci95_high'])}{matched_ci_clause}，
p = {pval(matched['hac_p_two_sided'])}，Holm 修正後 {pval(matched['hac_p_holm'])}。
**這是描述性條件比較，不是預測**：
可寫的結論是「歷史上這個波動水位下，非農前最後兩天沒有可辨識的系統性 VIX 上行」，
不是「這次會下跌 {num(abs(matched['hac_effect_pct_points']))} 個百分點」。

## 限制

{limitations}

## 重現

```bash
uv run python experiments/{results['experiment_id']}/{Path(trace['path']).name}
```

`reproduce_spec.json` 綁定 entrypoint sha256 `{trace['sha256'][:12]}…`
（{trace['size_bytes']:,} bytes）、{cn_count(n_inputs)}個 input snapshot 與{cn_count(n_outputs)}個 output；
`reproduce_commit.json` 記錄本次 generation identity。執行環境：
Python {env['python']}／numpy {env['numpy']}／pandas {env['pandas']}／scipy {env['scipy']}，
runtime {num(results['runtime_seconds'],3)} 秒。

本檔由 `render_readme.py` 從 `nfp_20260807_t2_results.json` 生成，數字未經人工轉抄。
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="re-render and fail if README.md on disk differs")
    args = ap.parse_args()

    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    rendered = render(results, spec)

    if args.check:
        current = README_PATH.read_text(encoding="utf-8") if README_PATH.exists() else ""
        if current != rendered:
            print(f"README drift: {README_PATH} differs from render_readme.py output",
                  file=sys.stderr)
            return 1
        print("README matches the rendered result JSON.")
        return 0

    README_PATH.write_text(rendered, encoding="utf-8")
    print(f"wrote {README_PATH} ({len(rendered):,} chars)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
