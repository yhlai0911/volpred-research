"""Publish K1314 GSP-HAR replication article (placebo-flagged marginal)."""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research")
sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research/src")

import volpred.publisher.publisher as publisher_module
from volpred.publisher.publisher import Publisher


ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
RESULTS_PATH = ROOT / "experiments" / "k1314" / "k1314_results.json"
PLACEBO_PATH = ROOT / "experiments" / "k1314" / "k1314_placebo_results.json"


def load_data() -> tuple[dict, dict]:
    main = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    placebo = json.loads(PLACEBO_PATH.read_text(encoding="utf-8"))
    return main, placebo


def make_chart(main: dict, placebo: dict) -> str:
    """Two-panel chart: per-asset DM t-stat (main vs placebo) + verdict bar."""
    assets = ["SPY", "QQQ", "GLD", "TLT", "IWM"]
    main_t = [main["per_asset"][a]["dm_hln"]["t_stat"] for a in assets]
    placebo_t = [placebo["per_asset"][a]["dm_hln"]["t_stat"] for a in assets]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    ax = axes[0]
    x = range(len(assets))
    width = 0.36
    bars_main = ax.bar([i - width / 2 for i in x], main_t, width,
                       label="Real graph (Pearson 2-NN)", color="#1E88E5", alpha=0.9)
    bars_pl = ax.bar([i + width / 2 for i in x], placebo_t, width,
                     label="Random-graph placebo", color="#FB8C00", alpha=0.85)
    ax.axhline(3.0, color="#2E7D32", linestyle="--", linewidth=1.1,
               label="Harvey |t|=3 bar")
    ax.axhline(-3.0, color="#2E7D32", linestyle="--", linewidth=1.1)
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(assets)
    ax.set_ylabel("DM-HLN t-stat (positive = GSP wins)", fontsize=10)
    ax.set_title("Real graph beats placebo only on SPY (and IWM placebo wins)",
                 fontsize=11, pad=10)
    ax.legend(loc="lower right", fontsize=8)
    ax.grid(axis="y", alpha=0.2)
    for bars in (bars_main, bars_pl):
        for bar in bars:
            v = bar.get_height()
            ax.text(bar.get_x() + bar.get_width() / 2,
                    v + (0.12 if v >= 0 else -0.18),
                    f"{v:+.2f}", ha="center",
                    va="bottom" if v >= 0 else "top",
                    fontsize=8)

    ax2 = axes[1]
    diff = [m - p for m, p in zip(main_t, placebo_t)]
    colors = ["#43A047" if (main_t[i] > 3.0 and diff[i] > 1.0) else "#C62828"
              for i in range(len(assets))]
    ax2.barh(assets, diff, color=colors, alpha=0.9)
    ax2.axvline(0, color="black", linewidth=0.8)
    ax2.axvline(1.0, color="#2E7D32", linestyle="--", linewidth=1.1,
                label="Robust margin (main − placebo > 1)")
    ax2.set_xlabel("main t − placebo t (positive = real signal)", fontsize=10)
    ax2.set_title("Robust real signal: 1 of 5 (SPY only)",
                  fontsize=11, pad=10)
    ax2.legend(loc="lower right", fontsize=8)
    ax2.grid(axis="x", alpha=0.2)
    for i, v in enumerate(diff):
        ax2.text(v + (0.1 if v >= 0 else -0.1),
                 i,
                 f"{v:+.2f}",
                 va="center",
                 ha="left" if v >= 0 else "right",
                 fontsize=9)

    fig.suptitle(
        "K1314 GSP-HAR replication: paper claims 'consistently outperforms', "
        "we find 1/5 robust",
        fontsize=12, y=1.02,
    )
    fig.tight_layout()

    out = ROOT / "experiments" / "k1314" / "k1314_general_article_chart.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(out)


def to_data_uri(path: str) -> str:
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def build_content(chart_uri: str, main: dict, placebo: dict) -> str:
    assets = ["SPY", "QQQ", "GLD", "TLT", "IWM"]

    def row(a: str) -> str:
        m = main["per_asset"][a]
        p = placebo["per_asset"][a]
        return (f"| {a} | "
                f"{m['qlike_improvement_pct']:+.2f}% | "
                f"{m['dm_hln']['t_stat']:+.2f} | "
                f"{p['dm_hln']['t_stat']:+.2f} | "
                f"{m['dm_hln']['t_stat'] - p['dm_hln']['t_stat']:+.2f} | "
                f"{'是' if m['dm_hln']['t_stat'] > 3.0 and (m['dm_hln']['t_stat'] - p['dm_hln']['t_stat']) > 1.0 else '否'} |")

    table = "\n".join(row(a) for a in assets)

    return f"""# 「consistently outperforms」這句話的代價：GSP-HAR 在 5 個美股 ETF 上的誠實複製

學界發表新方法時最常見的一句宣稱，是「我們的模型 **consistently outperforms** 既有 baseline」。Yan et al. (2024) 的 Graph Signal Processing HAR（GSP-HAR，arXiv:2410.22706）在 24 檔全球指數上提出了這樣的結論。聽起來很有說服力 — 跨 24 個市場、贏過 HAR-type benchmarks、還贏過 GNN-based HAR。

我們做了一件簡單的事：在 5 檔美股 ETF（SPY、QQQ、GLD、TLT、IWM）上，搭配 placebo 對照，做最簡化的複製。結果不支持「consistently」這個字。

## 為什麼挑「最簡化」版本

原 paper 的核心貢獻有四層：(1) 用 Diebold–Yilmaz 框架 + magnetic Laplacian 建 graph；(2) 在 GFT 頻域學 convex weight；(3) NN fusion；(4) 5-min realized variance。任何一層都可能各自帶來增益。

我們的 K1314 設計刻意把這四層全部簡化掉 — Pearson 相關 top-2 k-NN、固定 heat-kernel filter（τ=1.0，無 in-sample tuning）、純空間域、daily squared log return RV proxy。原因是：**如果連最簡化的 GSP idea 都能拉出 robust 的 DM 顯著，那 paper 的 architectural complexity 才有討論空間；如果連最簡化版都拉不出來，那 paper 的增益可能來自架構而非 GSP 本身**。

這是 K530／K782 教訓的延續：HAR 的 edge 經常完全取決於 RV proxy（5-min vs daily-squared），不是模型本身。我們需要先把 GSP 的 idea-level 貢獻分離出來。

## OOS 期間與評估方法

- 樣本期：2005-01-01 至 2024-12-31（20 年）
- 訓練期：2005-01-01 至 2019-12-31
- OOS 期：2020-01-01 至 2024-12-31（涵蓋 COVID、2022 熊市、2024 反彈），每資產 n_oos = 1,257
- Metric：Patton (2011) QLIKE（對 RV proxy noise robust）
- 顯著性：DM-HLN（Harvey-Leybourne-Newbold 1997 small-sample correction）+ HAC SE（Newey-West，bandwidth = floor(n^(1/3))）
- 隨機種子：42（OLS 為決定性）
- Lookahead 防線：所有 HAR feature 用 rv_{{t-1}} 起；graph correlation 用嚴格 expanding window < t 計算；每日 refit 只用 t-1 以前資料

## 主結果：表面看起來不差

| 資產 | QLIKE 改善 | 主 DM t-stat | Placebo DM t-stat | 主 − Placebo | 是否 robust real signal |
|---|---|---|---|---|---|
{table}

只看「主 DM t-stat」這一欄，會得到一個讓人想要相信「方法有效」的印象：SPY t=+5.41（p ≈ 7.6e-8）、IWM t=+1.49、TLT t=+1.47、QQQ t=+0.88、GLD t=−1.01。Pooled DM-HLN t-stat 也來到 +3.73。如果在這裡就停筆，文章可以寫成「GSP idea 在 4／5 美股 ETF 上呈現正向，SPY 達 Harvey 嚴格門檻 |t|>3」。

但是這樣寫不誠實。

## Placebo 測試把故事推翻了

我們跑了一個 random-graph placebo（`k1314_placebo.py`）：用同樣架構，但把 Pearson 相關矩陣換成 seed 固定的隨機稀疏對稱矩陣 — 攜帶**零 cross-asset 相關資訊**。任何 DM 顯著只能來自 extra regressor 帶來的 variance，不可能來自真實的 graph signal。

如果 GSP-HAR 的優勢真的來自 graph 結構，placebo 應該無顯著或顯著 worse；如果優勢來自單純多塞了三個 regressor 拉低 in-sample SSE，placebo 也會 spuriously 顯著。

![SPY only — robust signal 1/5]({chart_uri})

判定規則（事先在 `k1314.py` 編碼）：資產屬「robust real signal」需同時滿足 `main_t > 3.0` 且 `main_t > placebo_t + 1.0`。結果：

- **SPY**：main +5.41 vs placebo +2.69，差 +2.72 → 通過。SPY 的優勢確實有一部分來自真 graph signal。
- **QQQ / TLT**：main 雖正但 |t|<3，未達 Harvey 嚴格門檻。
- **GLD**：main 為負（QLIKE 反而變差），placebo 微正 — 差 −1.65。GSP 在 GLD 上是 net harm。
- **IWM**：**placebo t=+4.30 大於 main t=+1.49**，差 −2.81。這個資產上，random graph 表現比真實 graph 還好。這是 extra-regressor variance artifact 最赤裸的證據 — 「贏」根本不是來自 graph。

**Robust 真實訊號的資產數：1 / 5。** Pooled DM-HLN 看起來漂亮的 t=+3.73，其實是 SPY 一個資產撐起來的、加上 IWM 那種 placebo-can-do-the-same 的虛假貢獻拼湊出的結果。

## 「Consistently outperforms」這個字的含金量

把 placebo 結果還原到 paper 的宣稱結構，差異很明顯：

- Paper 24 個指數聲稱 consistent → 我們 5 個 ETF 中 1 個 robust（20%）
- Paper 用 5-min RV、學習過的 magnetic Laplacian filter、convex weight、NN fusion → 我們用 daily squared RV、固定 heat kernel、Pearson 2-NN
- Paper 拿到 monotone better in average → 我們 SPY 真贏、IWM 反向、GLD 反而輸

兩種可能解釋並存（且不互斥）：

1. **GSP idea 本身有效但脆弱**：在 SPY 這種 deep-liquid、cross-asset 連動明確的標的上能展現；換到 IWM 這種小型股、idiosyncratic 成分高的標的，cross-asset graph signal 訊號太弱、被 extra regressor 的 variance 吃掉。
2. **Paper 的增益主要來自架構而非 GSP**：當你拿掉 magnetic Laplacian、學習過的 filter、NN fusion 後，「graph」這件事在大部分 universe 上沒有 robust 邊際貢獻。

無論哪一個解釋成立，**「consistently outperforms」這個說法，在最低 spec 的簡化複製中找不到支持**。

## 對讀者實用的判讀規則

這次實驗最大的價值在於 placebo 思維本身 — 它把 vol forecasting 的閱讀清單再加上一條判讀規則。判 GSP-HAR 好壞反而是次要結果：

1. **任何 「加 N 個 regressor 就贏 baseline」的方法，第一個要問的是：random regressor 也會贏嗎？** 如果會（或贏更多），那「贏」不是來自方法的 idea。
2. **Pooled DM t-stat 看起來漂亮，常常是 1-2 個資產撐住的**。看 per-asset breakdown 才知道是否 robust。
3. **「Harvey |t|>3」是嚴格門檻，但不夠**。配上 placebo 對照才能排除 extra-regressor variance artifact。
4. **學界的 「consistently outperforms」要查 universe size 與 RV proxy**。24 個指數的結果 + 5-min RV，搬到 5 個 ETF + daily-squared RV 之後是否仍 robust，是兩件事。

K1314 的最終 verdict 是 **MARGINAL with placebo caveat** — 我們不否定 GSP-HAR 在原 paper 的 24 個指數上有 robust 增益（那是 paper 自己的 burden），但**在簡化複製、placebo 對照後，"consistently outperforms" 的宣稱在這 5 個美股 ETF 上不成立**。

---

*本文基於 K1314 自家實驗（`experiments/k1314/`）。資料來源：yfinance（auto_adjust=False）。樣本期：2005-01-01 至 2024-12-31。OOS 期：2020-01-01 至 2024-12-31，每資產 n_oos = 1,257。複製對象論文：Yan et al. (2024), "Graph Signal Processing HAR Model", arXiv:2410.22706。Placebo 設計：隨機稀疏對稱 adjacency（種子 42），其餘架構完全相同。完整 reproducibility：`experiments/k1314/k1314.py` 與 `k1314_placebo.py`。*
"""


def main() -> None:
    main_results, placebo_results = load_data()
    chart_path = make_chart(main_results, placebo_results)
    chart_uri = to_data_uri(chart_path)
    content = build_content(chart_uri, main_results, placebo_results)

    publisher_module._normalize_publish_assets = lambda description, details, *, root: (description, dict(details or {}))
    Publisher.REMOTE_URL = ""

    pub = Publisher()
    pub_id = pub.publish_milestone(
        title="「Consistently outperforms」這句話的代價：GSP-HAR 在 5 檔美股 ETF 上的誠實複製",
        description=content,
        phase="research",
        category="milestone",
        audience="research",
        tags=[
            "HAR-RV",
            "GSP-HAR",
            "graph-signal-processing",
            "placebo-test",
            "DM-test",
            "replication",
            "marginal-result",
        ],
        proposer="Claude",
        status="draft",
        details={
            "experiment_refs": ["K1314"],
            "charts": [chart_path],
            "data_source": "yfinance (SPY/QQQ/GLD/TLT/IWM); paper Yan et al. 2024 arXiv:2410.22706",
            "period": "2005-01-01 to 2024-12-31 (OOS 2020-01-01 to 2024-12-31)",
            "n_obs_per_asset": 1257,
            "verdict": "MARGINAL_WITH_PLACEBO_CAVEAT",
            "robust_assets": "1/5 (SPY only)",
            "cluster_waiver": "GSP-HAR replication 與 K530/K782 的 HAR-proxy lesson 是延伸而非變奏；首篇 placebo-test 框架文章",
        },
    )
    print(f"PUB_ID={pub_id}")


if __name__ == "__main__":
    main()
