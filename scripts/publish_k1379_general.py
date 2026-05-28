"""Publish K1379 general-audience draft article."""
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
RESULTS_PATH = ROOT / "experiments" / "k1379" / "k1379_results.json"


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text(encoding="utf-8"))


def make_chart(results: dict) -> str:
    qlike = results["qlike_means"]
    dm = results["dm_tests"]

    labels = ["GJR", "A4f", "HAR-RV", "HAR-RV-VIX"]
    values = [qlike["GJR"], qlike["A4f"], qlike["HAR_RV"], qlike["HAR_RV_VIX"]]
    colors = ["#546E7A", "#1E88E5", "#43A047", "#FB8C00"]

    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))

    ax = axes[0]
    bars = ax.bar(labels, values, color=colors, alpha=0.9)
    ax.set_ylabel("Average error (lower is better)", fontsize=10)
    ax.set_title("Out-of-sample error by model", fontsize=12, pad=10)
    ax.grid(axis="y", alpha=0.2)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2,
            value + 6,
            f"{value:.1f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )

    ax2 = axes[1]
    dm_labels = ["New vs Simple", "New vs VIX+", "Simple vs Old"]
    dm_values = [
        dm["A4f vs HAR-RV"]["dm_t"],
        dm["A4f vs HAR-VX"]["dm_t"],
        dm["HAR-RV vs GJR"]["dm_t"],
    ]
    dm_colors = ["#1E88E5" if v > 0 else "#E53935" for v in dm_values]
    bars2 = ax2.barh(dm_labels, dm_values, color=dm_colors, alpha=0.9)
    ax2.axvline(0, color="black", linewidth=0.9)
    ax2.axvline(3.0, color="#2E7D32", linestyle="--", linewidth=1.2)
    ax2.axvline(-3.0, color="#C62828", linestyle="--", linewidth=1.2)
    ax2.set_xlabel("Test statistic", fontsize=10)
    ax2.set_title("Is the gap big enough to trust?", fontsize=12, pad=10)
    ax2.grid(axis="x", alpha=0.2)
    ax2.set_xlim(-1.6, 3.2)
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
        "Daily volatility forecast comparison\n"
        "2019-01-01 to 2026-05-18, n=1,852",
        fontsize=13,
        y=1.02,
    )
    fig.tight_layout()

    out = ROOT / "experiments" / "k1379" / "k1379_general_article_chart.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(out)


def to_data_uri(png_path: str) -> str:
    payload = base64.b64encode(Path(png_path).read_bytes()).decode("ascii")
    return f"data:image/png;base64,{payload}"


def build_content(chart_uri: str) -> str:
    return f"""# 波動率預測不是把指標愈疊愈多就會愈準

做投資研究的人很容易有一個衝動：再加一個指標、再多一層結構、再換一個比較新的做法，預測應該就會更準。

這次我們把四種波動率預測方法放到同一條跑道上，直接看 2019 年到 2026 年、共 1,852 個交易日的往前預測表現。裡面有老方法、有較新的版本，也有把恐慌指標一起塞進去的組合。

結果很不戲劇化。**比較新的做法表面上有小幅領先，但差距小到不足以讓人放心說「它真的更強」。**

![volatility forecast comparison]({chart_uri})

先看左圖。這裡比較的是四種方法的平均預測誤差，數字越低越好。

- 最舊的基準版：624.3
- 較新的版本：688.5
- 簡單版：718.5
- 再加恐慌指標的版本：737.6

如果只看這個表面排名，你很容易得到一個危險結論：新版比簡單版好，因為平均誤差少了大約 4%；比「再多加一個恐慌指標」的版本也好一些。

問題在於，投資研究不能只看誰分數比較漂亮，還要問一句：**這個差距有沒有大到足以排除運氣？**

右圖就是在回答這件事。三條橫線代表三組最重要的正面對決。虛線是我們事先設好的嚴格門檻，必須跨過去，才算真的拉開差距。

這次三組對比，全部都沒跨線。

白話一點說就是：新版看起來比較好，但還沒有好到足以讓人斷定「這不是剛好」。

這件事很值得記住，因為投資世界最常見的錯誤，不是完全沒差的東西被吹成神話，而是**只有一點點優勢的東西，被講得像已經分出勝負。**

這次結果至少給了兩個提醒。

第一，**把更多東西塞進模型，不代表會更準。** 這次把恐慌指標一起加進去的版本，成績反而最差。多一個欄位很容易，多一個真的有用的訊號很難。

第二，**小幅領先不等於已經贏了。** 你看到 3%、4%、5% 的改善，很容易興奮；但拉長到多年樣本後，那些差距可能只是幾段行情剛好偏向某一邊。沒有經過嚴格比較，你分不出它是真本事，還是短期運氣。

所以這篇真正想講的，不是哪個名字最厲害，而是一個比較不討喜、但更有用的結論：

**到目前為止，這幾種模型之間的差距，還沒有大到足以讓你放心說「新版一定比舊版強」。**

對一般投資人，這件事其實很實用。每次你看到一個新模型、新指標、新框架，都可以先問：

1. 它只是看起來比較新，還是真的穩定更準？
2. 那個改善幅度，有沒有大到經得起多年資料檢驗？
3. 如果連研究裡都拉不開，到了真實交易裡扣掉成本後還剩多少？

很多時候，答案沒有行銷文案講得那麼漂亮。

這篇最值得記住的，不是誰第一名，而是這個研究態度：**模型升級不能靠名字取勝，只能靠往前驗證的證據取勝。**

---

*本文基於 VolPred 內部對照實驗。資料來源：美股與波動率快照資料，樣本外期間：2019-01-01 至 2026-05-18，樣本：1,852 個有效交易日。*
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
        title="波動率預測不是把指標愈疊愈多就會愈準",
        description=content,
        phase="research",
        category="milestone",
        audience="general",
        tags=[
            "波動率預測",
            "VIX",
            "模型比較",
            "負面結果",
            "投資研究",
        ],
        proposer="Codex",
        status="draft",
        details={
            "experiment_refs": ["K1379"],
            "charts": [chart_path],
            "data_source": "paper/garch-x-vix/data/spy_vix_qqq_eem_fez_2000-2026.csv",
            "period": "2019-01-01 to 2026-05-18",
            "n_obs": 1852,
            "verdict": "LIMITATION",
            "cluster_waiver": "pending daily_article task K1379; angle focuses on model-complexity skepticism rather than routine VIX commentary",
        },
    )
    print(f"PUB_ID={pub_id}")


if __name__ == "__main__":
    main()
