---
name: feedback_recycling_is_release_layer_not_research
description: 文章「鬼打牆/回收舊主題」的根因在釋出端(draft 積壓+釋出偏老 cluster+cluster 錯標)，不是研究端；生產前先掃 draft backlog
metadata: 
  node_type: memory
  type: feedback
  originSessionId: df279cec-2a1a-4970-b0ae-111055444eb8
---

用戶 2026-06-15 強烈糾正「文章又鬼打牆、封閉在寫過的主題」。深查後根因**不在研究端**（新軸實驗其實一直在跑：K1487/1488/1492/1495/1498/1499…），而在**釋出/輸出端**：

1. **draft backlog 積壓**（2026-06-15 當下 123 篇 draft 未釋出），而釋出嚴重偏 vix/spy cluster（近期 vix 18 / spy 16）→ fresh-cluster 文章寫了卻卡著不出。
2. **cluster 錯標**：私募信貸文 `mile_1b511caa` 被標成 `spy` cluster（實為 credit）→ 灌大 spy 計數 → publish 端 `topic_cluster_cooldown_blocked`（spy 88/30d vs cap 10）又據此擋掉新 SPY 角度文，惡性循環。
3. **主線程自己在 FB 層拿舊 cluster 回收包**（VT/VIX 變奏）= 雪上加霜。

**Why**：只看「有沒有跑新實驗」會誤判成研究端問題，一直加 journal batch（已堆 6+ batch）卻無效，因為瓶頸在釋出與標註。

**How to apply**（生產前 checklist）：
- 派新實驗/寫新文章**前**，先掃 `jq '[.[]|select(.status=="draft")]|length' storage/reports/feed.json` 與既有 draft 標題 + grep 主題，**先消化 backlog 再生產**（K1499 教訓：我先派實驗才發現該題已是 draft mile_1b511caa）。
- 釋出優先序要主動挑 **fresh cluster** 出 backlog，不要讓 release 一直推 vix/spy。看 `jq '[.[]|select(.published_at>"<近30d>")]|group_by(.details.topic_cluster)' ` 確認分佈。
- 修 cluster 自動標註：credit/microstructure/retirement/crypto 等不該被吞進 spy/vix。
- FB 發文不用舊 cluster 回收包。
- 飽和判斷看 `topic_cluster` 30d 分佈：只有 spy/vix 爆，其餘全空 → 優先出非 spy/vix。

相關：[[feedback_journal_topic_discovery]]（挖新題）、[[feedback_narrative_arc_dedup]]（同 arc 換殼算 dup）、[[feedback_dispatch_over_diversity]]。
