from pathlib import Path

from scripts.gen_lazypack_codex import _build_prompt


def test_reader_facing_source_label_never_instructs_internal_k_id(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(
        '{"evidence":{"result":{"label":"報酬順序風險重跑結果"}}}',
        encoding="utf-8",
    )
    prompt = _build_prompt(
        "退休提款的順序風險",
        [
            {
                "name": "1_result",
                "info": "results",
                "style": "professional",
                "title": "大跌越早來，耗盡率越高",
                "alt": "退休初期與晚期大跌的差異",
                "sources": ["result"],
                "blocks": [],
            }
        ],
        [plan],
        tmp_path / "out",
        font="Heiti TC",
        evidence_labels={"result": "報酬順序風險重跑結果"},
    )

    assert "evidence.*.label" in prompt
    assert "result: 報酬順序風險重跑結果" in prompt
    assert "圖卡底部必須逐字使用" in prompt
    assert "禁止**從檔名或內容猜 K 編號" in prompt
    assert "資料來源：experiment K####" not in prompt
