"""Publish K1396 general-audience draft article."""
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
RESULTS_PATH = ROOT / "experiments" / "k1396" / "k1396_results.json"


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def make_chart(results: dict) -> str:
    labels = ["HAR-RV", "A4f", "HAR-RV-VIX"]
    values = [
        results["mean_qlike"]["HAR"],
        results["mean_qlike"]["A4f"],
        results["mean_qlike"]["HAR_VIX"],
    ]
    colors = ["#546E7A", "#1E88E5", "#43A047"]

    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5))

    ax = axes[0]
    bars = ax.bar(labels, values, color=colors, alpha=0.9)
    ax.set_ylabel("Average error (lower is better)", fontsize=10)
    ax.set_title("Small ranking gaps still look dramatic", fontsize=12, pad=10)
    ax.grid(axis="y", alpha=0.2)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 0.01,
            f"{value:.3f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    ax2 = axes[1]
    dm_labels = ["HAR-RV vs A4f", "HAR-RV-VIX vs A4f", "HAR-RV-VIX vs HAR-RV"]
    dm_values = [
        results["dm_tests"]["HAR_vs_A4f"]["t_stat"],
        results["dm_tests"]["HAR_VIX_vs_A4f"]["t_stat"],
        results["dm_tests"]["HAR_VIX_vs_HAR"]["t_stat"],
    ]
    dm_colors = ["#1E88E5" if v > 0 else "#E53935" for v in dm_values]
    bars2 = ax2.barh(dm_labels, dm_values, color=dm_colors, alpha=0.9)
    ax2.axvline(0, color="black", linewidth=0.9)
    ax2.axvline(3.0, color="#2E7D32", linestyle="--", linewidth=1.2)
    ax2.axvline(-3.0, color="#C62828", linestyle="--", linewidth=1.2)
    ax2.set_xlabel("Comparison score", fontsize=10)
    ax2.set_title("But none of them cleared the strict bar", fontsize=12, pad=10)
    ax2.grid(axis="x", alpha=0.2)
    ax2.set_xlim(-3.0, 3.2)
    for bar, value in zip(bars2, dm_values):
        ax2.text(
            value + (0.08 if value >= 0 else -0.08),
            bar.get_y() + bar.get_height() / 2,
            f"{value:.2f}",
            va="center",
            ha="left" if value >= 0 else "right",
            fontsize=9,
        )

    fig.suptitle(
        "K1396: when a model looks slightly better, does it really matter?",
        fontsize=13,
        y=1.02,
    )
    fig.tight_layout()

    out = ROOT / "experiments" / "k1396" / "k1396_general_article_chart.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(out)


def to_data_uri(path: str) -> str:
    payload = base64.b64encode(Path(path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def build_content(chart_uri: str) -> str:
    return f"""# 只贏一點點的模型，很多時候還不能算真的贏

做投資研究很容易被一種差距誘惑。

你跑完三個模型，發現其中一個的分數比較低，剛好多贏了 1% 到 2%。這時很自然會想把它翻譯成一句漂亮的話：新版模型比較強。

問題是，**看起來有領先，不代表已經贏到足以當成結論。**

這次我們把三種日頻波動率預測做法放在同一條跑道上比較：一個是經典老方法，一個是較新的版本，另一個則是在老方法上再加進市場恐慌指標。

結果表面上很有故事。

![small gap versus real edge]({chart_uri})

先看左圖。三個模型的平均誤差分別是：

- 經典老方法：1.561
- 較新的版本：1.539
- 加了恐慌指標的版本：1.523

如果你只看這張排名，很容易得出兩句很像樣的話。

第一句：較新的版本比老方法好，因為它的誤差少了大約 1.4%。

第二句：加了恐慌指標的版本更厲害，因為它三者裡最低。

這兩句話都不是完全錯，但都還少了最重要的一步：**這個差距有沒有大到足以排除只是剛好？**

右圖就是在回答這件事。

三組直接對打的分數分別是：

- 老方法 vs 較新版本：0.87
- 加指標版本 vs 較新版本：-0.88
- 加指標版本 vs 老方法：-2.60

這些分數看起來有方向，但都沒有跨過我們事先設好的嚴格門檻。白話一點講，就是：

**你可以說它們看起來有差，但還不能安心說那個差距已經大到值得你下重話。**

這件事聽起來很學術，其實跟日常判斷很像。

假設兩個基金經理人，一個年化多賺 1%，另一個少 1%。如果你只看一年，很可能只是市場剛好站在其中一邊。但如果你真的要說「這個人比較厲害」，你通常會希望那個差距更穩、更持久、更不容易被運氣解釋掉。

模型比較也是一樣。

研究裡最容易犯的錯誤，不是完全沒差的東西被吹成神話，而是**只有一點點優勢的東西，被過早包裝成新標準答案。**

這個實驗最有價值的地方，就是它逼你把這一步補上。

它沒有告訴你「三個模型都一樣」。它告訴你的是更細的一句話：

**目前看到的排名差距，還不足以讓你很有把握地說誰真的拉開了。**

這個提醒很重要，因為投資世界特別喜歡小幅領先的故事。多一點點 alpha、多一點點準度、多一點點風控分數，聽起來都很迷人。可是一旦你把時間拉長、把比較做嚴格，很多小優勢都會變得沒那麼篤定。

對一般投資人來說，這篇最實用的地方不是記住那些模型名字，而是記住這個判斷原則：

1. 排名比較好看，不等於真的比較強
2. 小幅領先，要先懷疑是不是運氣
3. 真正能站得住腳的優勢，通常不會只靠 1% 的差距撐場

所以，下次你看到一個新模型、新策略、新指標，只比舊方法多贏一點點，先別急著把它當成升級版。比較穩妥的態度是：

**先問它是真的贏，還是只是暫時排在前面。**

這往往比看排行榜本身更重要。

---

*本文基於 VolPred 內部對照實驗。資料期間：2005-01-01 至 2026-05-22；樣本外起點：2019-01-01；樣本外觀測值：1,866。比較對象為三種日頻波動率預測方法：老方法、較新版本，以及加入市場恐慌指標的延伸版。*
"""


def main() -> None:
    results = load_results()
    chart_path = make_chart(results)
    chart_uri = to_data_uri(chart_path)
    content = build_content(chart_uri)

    publisher_module._normalize_publish_assets = lambda description, details, *, root: (description, dict(details or {}))
    Publisher.REMOTE_URL = ""

    pub = Publisher()
    pub_id = pub.publish_milestone(
        title="只贏一點點，很多時候還不能算模型真的比較強",
        description=content,
        phase="research",
        category="milestone",
        audience="general",
        tags=[
            "波動率預測",
            "模型比較",
            "投資研究",
            "負面結果",
            "VIX",
        ],
        proposer="Codex",
        status="draft",
        details={
            "experiment_refs": ["K1396"],
            "charts": [chart_path],
            "data_source": "internal HAR-RV vs A4f comparison",
            "period": "2019-01-01 to 2026-05-22",
            "n_obs": 1866,
            "verdict": "ACKNOWLEDGED",
            "cluster_waiver": "pending daily_article task K1396; angle focuses on small-gap interpretation rather than repeating prior A4f or HAR-RV coverage",
        },
    )
    print(f"PUB_ID={pub_id}")


if __name__ == "__main__":
    main()
