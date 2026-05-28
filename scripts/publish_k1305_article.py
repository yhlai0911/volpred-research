"""Publish K1305 general-audience draft article."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

sys.path.insert(0, "/Users/yhlai0911/Desktop/volpred-research")

from volpred.publisher.publisher import Publisher


ROOT = Path("/Users/yhlai0911/Desktop/volpred-research")
RESULTS_PATH = ROOT / "experiments" / "k1305" / "k1305_results.json"


def load_results() -> dict:
    return json.loads(RESULTS_PATH.read_text())


def make_dm_chart(results: dict) -> str:
    rows: list[tuple[str, float]] = []
    order = [
        ("GLD", "M3_NFCI"),
        ("GLD", "M3_ANFCI"),
        ("GLD", "M3_USEPU"),
        ("GLD", "M3_WLEMU"),
        ("TLT", "M3_NFCI"),
        ("TLT", "M3_ANFCI"),
        ("TLT", "M3_USEPU"),
        ("TLT", "M3_WLEMU"),
        ("BTC", "M3_NFCI"),
        ("BTC", "M3_ANFCI"),
        ("BTC", "M3_USEPU"),
        ("BTC", "M3_WLEMU"),
    ]
    for asset, model in order:
        dm_t = results["results_by_asset"][asset][model]["dm_t"]
        rows.append((f"{asset} {model.replace('M3_', '')}", dm_t))

    labels = [r[0] for r in rows]
    values = [r[1] for r in rows]
    colors = []
    for v in values:
        if v >= 3:
            colors.append("#2E7D32")
        elif v <= -3:
            colors.append("#C62828")
        else:
            colors.append("#607D8B")

    fig, ax = plt.subplots(figsize=(10, 7))
    ypos = list(range(len(labels)))
    bars = ax.barh(ypos, values, color=colors, alpha=0.9)
    ax.axvline(0, color="black", linewidth=1)
    ax.axvline(3, color="#2E7D32", linestyle="--", linewidth=1.5)
    ax.axvline(-3, color="#C62828", linestyle="--", linewidth=1.5)
    ax.set_yticks(ypos)
    ax.set_yticklabels(labels, fontsize=10)
    ax.set_xlabel("DM t 統計量（正值 = 加入替代資料後較佳）", fontsize=11)
    ax.set_title(
        "K1305：GLD / TLT / BTC 加入 ALFRED vintage 替代資料後的 OOS DM t\n"
        "沒有任何一格跨過 +3.0 的 Harvey 門檻",
        fontsize=12,
        pad=12,
    )

    for bar, value in zip(bars, values):
        x = value + 0.18 if value >= 0 else value - 0.18
        ha = "left" if value >= 0 else "right"
        ax.text(
            x,
            bar.get_y() + bar.get_height() / 2,
            f"{value:.2f}",
            va="center",
            ha=ha,
            fontsize=9,
        )

    ax.text(
        3.05,
        -0.8,
        "Harvey +3.0",
        color="#2E7D32",
        fontsize=9,
        ha="left",
    )
    ax.text(
        -3.05,
        -0.8,
        "Harvey -3.0",
        color="#C62828",
        fontsize=9,
        ha="right",
    )
    ax.set_xlim(-10.2, 3.2)
    ax.invert_yaxis()
    fig.tight_layout()

    out = ROOT / "experiments" / "k1305" / "k1305_article_dm_t.png"
    fig.savefig(out, dpi=160, bbox_inches="tight")
    plt.close(fig)
    return str(out)


def build_content(results: dict, chart_path: str) -> str:
    return f"""# 把資料版本修到最乾淨，總體指標還是贏不了各資產自己的恐慌表

很多總體指標看起來都很厲害。金融壓力指數、政策不確定性指數、新聞情緒，名字一個比一個大。真正的問題不是它們有沒有故事，而是：**拿來預測黃金、美債、比特幣下週的波動，能不能比各資產自己的恐慌表更有用？**

這次我們把資料版本拉到最嚴格，改用 **ALFRED 的真實 vintage 資料**。意思是每一個週五，只准模型看到當時市場真的看得到的版本，不能偷吃後來修訂過的值。測三個資產：GLD、TLT、BTC。基準不是只看過去波動，而是已經先放進各自的恐慌表：黃金看 `^GVZ`，美債看 `^MOVE`，比特幣看 `DVOL`。接著再問一次：**總體替代資料加上去，還有沒有增量？**

答案很乾脆：**沒有。12 個有效的樣本外比較裡，0 個跨過我們預先設定的顯著門檻。**

![K1305 DM t 統計量圖]({chart_path})

圖上的每一條棒，都是「把某一個總體指標加進 native-IV 模型後」的樣本外 DM t 統計量。正值代表加了有幫助，負值代表反而更差。你會看到三件事。

第一，**GLD 沒有一格真的過關**。最接近的是 `ANFCI`，統計量只有 `+2.21`，還是沒到 `+3.0`。其他像 `NFCI`、`USEPU`、`WLEMU` 都只是零附近擺動。

第二，**TLT 的結論甚至更狠**。四個可用替代指標全部是負的，而且三個跌破 `-3.0`。`NFCI=-7.73`、`ANFCI=-9.03`、`USEPU=-4.60`、`WLEMU=-3.37`。這不是「沒幫助」而已，是明顯比只看 `^MOVE` 更差。

第三，**BTC 也沒有被總體資料救起來**。`NFCI=-7.90`、`ANFCI=-6.75`，`USEPU` 幾乎就是 `0`。這裡要誠實講一句細節：這次證明的是「替代資料加在 `DVOL` 之上沒有增量」，**不是**說 `DVOL` 單獨一定能打敗所有基準。對 BTC 而言，自己的恐慌表本身也不是萬能答案；但總體替代資料同樣不是救兵。

這件事的重要性，在於它補的是這條研究線裡**最後一格還沒關掉的漏洞**。前面幾輪實驗已經看過兩件事：一是標普 500 這邊，就算把資料發布延遲和版本修正考慮進去，替代資料還是贏不了 VIX；二是 GLD、TLT、BTC 這邊，粗略對齊下也看不到增量。這次做的，就是把「跨資產」和「真實 vintage」兩個條件交叉起來，再測一次。

換句話說，這篇不是又一次泛泛地說「VIX 很有用」。它更接近一句審稿人會問的話：**如果你把資料清理到對替代資料最有利的版本，結論會不會翻？** 這次的答案是：還是不翻。

這次樣本期間是 `2020-01-01` 到 `2026-04-30`，拿 `2023-01-01` 之後做真正的往前預測，每個資產大約有 `170` 多個週資料點。程式裡也把時間順序鎖得很死：各資產的恐慌表先往後退一期，ALFRED 只准讀到預測當週週五以前真的發布過的版本，避免把未來修訂偷偷混進去。

也有兩個限制要一起講。

一個是 **不是每個 series 都有完整 vintage**。`STLFSI4` 在 ALFRED 的早期段落缺資料，所以這次 `21` 個組合裡只有 `12` 個是有效比較；吃到缺口的多變數組合，大多沒有可用結果。這代表這次不是把所有排列組合重做一遍，而是把最關鍵、能真正對比的那一塊補完。

另一個是 **這不代表各資產自己的恐慌表在所有情況下都完美充分**。特別是 BTC，先前同一條研究線已經提醒過：就算換成 crypto-native 的 `DVOL`，也不保證一定能顯著打敗簡單基準。這次只是更嚴格地再確認一次：你把總體替代資料疊上去，也沒有變好。

所以，這篇真正的結論不是「巨觀資料沒價值」，而是更窄也更實用的一句話：

**如果你的目標是預測 GLD、TLT、BTC 的下週波動，先把各資產自己的恐慌表用好。把資料版本修得再乾淨，總體替代指標目前仍沒有證明自己能提供額外增量。**

*本文對應腳本：`experiments/k1305/k1305.py`；結果檔：`experiments/k1305/k1305_results.json`。資料來源：ALFRED PIT vintage API、yfinance、Deribit DVOL；期間：`2020-01-01` 至 `2026-04-30`。*
"""


def main() -> None:
    results = load_results()
    chart_path = make_dm_chart(results)
    content = build_content(results, chart_path)

    pub = Publisher()
    article_id = pub.publish_milestone(
        title="資料版本洗到最乾淨後，黃金美債比特幣的波動還是先看自己",
        description=content,
        phase="research",
        category="milestone",
        audience="general",
        tags=[
            "GLD",
            "TLT",
            "BTC",
            "ALFRED",
            "波動率預測",
            "總體資料",
            "native IV",
        ],
        proposer="Codex",
        status="draft",
        details={
            "experiment_refs": ["K1305", "K1116", "K1118", "K1119"],
            "charts": [chart_path],
        },
    )
    print(article_id)


if __name__ == "__main__":
    main()
