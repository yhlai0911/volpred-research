"""Publish K901 general-audience draft article."""
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
RESULTS_PATH = ROOT / "experiments" / "k901" / "k901_international_vt_13markets_results.json"


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def make_chart(results: dict) -> str:
    cross = results["cross_sectional"]
    table = results["table5_summary"]

    improved_counts = [
        cross["n_mdd_improved"],
        cross["n_sharpe_improved"],
        cross["n_dm_significant_harvey"],
    ]
    count_labels = [
        "Markets with\nsmaller drawdowns",
        "Markets with\nbetter Sharpe",
        "Markets with\nclear return evidence",
    ]
    count_colors = ["#2E7D32", "#C62828", "#546E7A"]

    tickers = [row["ticker"] for row in table]
    mdd_improvements = [row["mdd_improvement_pp"] for row in table]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))

    ax = axes[0]
    bars = ax.bar(count_labels, improved_counts, color=count_colors, alpha=0.92)
    ax.set_ylim(0, 14)
    ax.set_ylabel("Markets out of 13", fontsize=10)
    ax.set_title("What held up across countries?", fontsize=12, pad=10)
    ax.grid(axis="y", alpha=0.2)
    for bar, value in zip(bars, improved_counts):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.3,
            f"{value}/13",
            ha="center",
            va="bottom",
            fontsize=10,
            fontweight="bold",
        )

    ax2 = axes[1]
    bars2 = ax2.bar(tickers, mdd_improvements, color="#1E88E5", alpha=0.9)
    ax2.set_ylabel("Drawdown reduction (percentage points)", fontsize=10)
    ax2.set_title("Every market fell less, but by different amounts", fontsize=12, pad=10)
    ax2.grid(axis="y", alpha=0.2)
    ax2.tick_params(axis="x", labelrotation=45)
    for bar, value in zip(bars2, mdd_improvements):
        ax2.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.4,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=8,
        )

    fig.suptitle(
        "K901: one defensive rule traveled well, but only on the pain side",
        fontsize=13,
        y=1.02,
    )
    fig.tight_layout()

    out = ROOT / "experiments" / "k901" / "k901_general_article_chart.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(out)


def to_data_uri(path: str) -> str:
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def build_content(chart_uri: str) -> str:
    return f"""# 一套方法在 13 個市場都有效，卻不代表它會幫你賺更多

投資世界很容易把「有效」這兩個字講得太快。

一個方法只要跨很多國家都能用，聽起來就很像萬用答案。市場不同、投資人不同、政策不同，結果它居然在 13 個市場都成立，這很容易讓人直覺把它翻成一句更大聲的話：這方法是全球通用的贏家。

但這次的結果剛好提醒我們，**同一套方法可以在一種意義上很有效，卻在另一種意義上完全不是。**

![international defensive rule summary]({chart_uri})

先看左圖。

我們把同一套減碼規則放到 13 個股票市場上測，結果出現一個很整齊、也很容易被誤讀的畫面：

- 13 個市場裡，13 個都明顯比較不容易跌得那麼深
- 13 個市場裡，0 個能證明風險調整後報酬變得更好
- 13 個市場裡，0 個能給出夠強的證據，說它真的比單純抱住更會賺

這三句話要一起看，不能只挑第一句。

因為第一句講的是**受傷少一點**，後兩句講的是**賺錢本事有沒有真的升級**。兩者不是同一件事。

右圖把這件事再拉得更具體一點。13 個市場每一個都降低了最大回撤，但幅度差很多。有些市場少跌將近 30 個百分點，有些只少跌 5 個百分點左右。也就是說，這套方法的共同點很清楚：它比較像保護墊，而不是加速器。

這個結論其實比「全球都有效」更有用，因為它把方法的本質講清楚了。

很多投資人看到這種規則，會下意識期待兩件事同時發生：

1. 跌的時候幫我少虧一點
2. 漲的時候最好也不要少賺

現實往往沒那麼慷慨。

這次 13 市場一起看的答案比較像是：**第一件事很穩，第二件事不要先預設會一起來。**

你可以把它想成開車時的安全配備。安全帶和氣囊的價值，主要不是讓你開得比較快，而是出事時不要傷得那麼重。如果你硬把它當成加速套件，期待它順便讓車跑更快，那你一開始就把工具看錯了。

這也是這個實驗最值得留下來的地方。它不是在宣告某個神奇公式可以橫掃全球，而是在替這類策略重新命名：

**它更像跨市場通用的防守工具，不是跨市場通用的報酬放大器。**

這句話聽起來比較不熱血，但對一般投資人反而更實際。

如果你最在意的是大跌時別一次傷太重，這類方法有它的價值。因為在這次比較裡，13 個市場沒有一個例外，都在回撤這件事上比較好看。

但如果你想問的是「它能不能讓我在更多國家都賺得比原本多」，那這組資料給的答案就很保守，甚至可以說是否定的。至少到目前為止，我們看不到足夠強的證據支持這個更大的說法。

這件事值得特別講，因為投資研究最常見的誤會之一，就是把「比較能防守」直接翻成「整體比較強」。

其實很多策略真正提供的，是比較溫和的資產路徑，而不是比較高的終點。

這兩種價值都是真的，但不能混著賣。

所以，如果你看到一個方法被描述成「跨市場都有效」，先補問一句：

**它到底是讓你賺更多，還是讓你跌少一點？**

這一題先問清楚，常常比方法本身更重要。

---

*本文基於 VolPred 內部跨市場對照實驗。資料期間：2005-01-04 至 2026-04-02；比較 13 個以美元計價的股票 ETF 市場。核心結果是：13/13 市場最大回撤改善，但 0/13 市場出現明確的風險調整報酬提升證據。*
"""


def main() -> None:
    results = load_results()
    chart_path = make_chart(results)
    chart_uri = to_data_uri(chart_path)
    content = build_content(chart_uri)

    publisher_module._normalize_publish_assets = lambda description, details, *, root: (
        description,
        dict(details or {}),
    )
    Publisher.REMOTE_URL = ""

    pub = Publisher()
    pub_id = pub.publish_milestone(
        title="一套方法在 13 個市場都有效，卻不代表它會幫你賺更多",
        description=content,
        phase="research",
        category="milestone",
        audience="general",
        tags=[
            "投資研究",
            "跨市場",
            "風險管理",
            "回撤控制",
            "負面結果",
        ],
        proposer="Codex",
        status="draft",
        details={
            "experiment_refs": ["K901"],
            "charts": [chart_path],
            "data_source": "internal 13-market defensive-rule comparison",
            "period": "2005-01-04 to 2026-04-02",
            "n_markets": 13,
            "verdict": "PASS_WITH_QUALIFIER",
            "cluster_waiver": "pending daily_article task K901; angle focuses on universal drawdown protection versus missing return edge, not generic VT how-to content",
        },
    )
    print(f"PUB_ID={pub_id}")


if __name__ == "__main__":
    main()
