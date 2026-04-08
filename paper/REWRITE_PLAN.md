# 論文全面重寫計劃

**原則**：每篇論文都要 **找到支持性實驗 → 重跑驗證 → 在主對話中重寫 → 用 skill 審查**。
**禁止用 agent 寫論文。** 必須在主對話串中直接進行。

## 執行順序（短 → 長，FRL 先）

### Round 1: FRL 短文（< 2500 words，修正成本低）

#### 1. vt-insurance-cost (Paper 4, 13p, 15 citations)
- **支持實驗**: K811v2（保險費分解）、K846（再平衡溢酬）、K860（Prospect Theory）
- **審計結果**: 63/67 OK，1 MEDIUM（sensitivity threshold 不可追溯）
- **行動**:
  - [ ] 補跑 sensitivity threshold sweep（0.5, 1.0, 1.5）實驗
  - [ ] 重跑 K811v2 + K846 確認所有數字
  - [ ] 在主對話中修正論文（散文體、引用、sensitivity 數據）
  - [ ] `/latex-academic-reviewer` + `/citation-verifier`

#### 2. vt-crowding-abm (Paper 5, 14p, 11 citations)
- **支持實驗**: K827v3（固定流動性 ABM）、K864（異質 ABM）
- **審計結果**: 146/148 OK，**CRITICAL: t-test 來自錯誤實驗版本（K827v2 not v3）**
- **行動**:
  - [ ] 重跑 K827v3 確認所有數字
  - [ ] Section 3.3 整段重寫（用 K827v3 的 t-test 值）
  - [ ] 加入 K864（異質 ABM）結果
  - [ ] 在主對話中修正
  - [ ] `/latex-academic-reviewer` + `/citation-verifier`

#### 3. prg-periodic-garch (Paper 6, 12p, 15 citations)
- **支持實驗**: K874c/d/e（TAIFEX）、K880/881（SPY/QQQ/GLD/EEM）、K883（tick PRG）
- **審計結果**: 5 嚴重 + 3 引用錯誤（自引全錯、VaR 數據張冠李戴、stationarity 不對）
- **行動**:
  - [ ] **完全重寫**（不是修正，是從頭來）
  - [ ] 先做文獻搜尋（periodic GARCH、overnight vol、session decomposition 20+ 篇）
  - [ ] 理論推導 stationarity（companion matrix spectral radius）
  - [ ] 從 JSON 直接提取所有數字
  - [ ] 讀用戶 PRS 論文確認正確引用
  - [ ] 在主對話中寫作
  - [ ] `/latex-academic-reviewer` + `/citation-verifier`

### Round 2: 中型論文

#### 4. vt-trend-following (Paper 3, 33p, 18 citations)
- **支持實驗**: K46→K53→K79（VT alpha = trend following）、K687/K697/K688
- **審計結果**: review_v2 已有 5 HIGH 待修
- **行動**:
  - [ ] 盤點所有支持實驗，確認可追溯
  - [ ] 重跑核心實驗
  - [ ] 修正 5 HIGH issues
  - [ ] 在主對話中修正

### Round 3: 大型論文

#### 5. taiwan-vt (Paper 2, 60p, 34 citations)
- **支持實驗**: K844-K854 系列（TAIFEX 高頻）+ 早期台灣研究
- **行動**:
  - [ ] 盤點 60 頁論文的所有數字來源
  - [ ] Section 5（高頻）需要用正確的轉倉數據重跑
  - [ ] proxy ceiling 敘事需修正

#### 6. leverage-direction (Paper 1, 62p, 54 citations)
- **支持實驗**: 早期 K 系列（gamma、cross-sectional）
- **行動**:
  - [ ] 最大的論文，最多引用，盤點工作量最大
  - [ ] 需要完整的實驗連結

#### 7. vix-sufficiency (39p, 40 citations)
- **行動**: 盤點 29+ 次 VIX sufficiency 實驗

#### 8. volatility-absorption (38p, 37 citations)
- **行動**: 盤點支持實驗

## 找支持性實驗的來源（按優先順序）
1. **knowledge.json**（1678 筆）：`grep -i '關鍵詞' storage/memory/knowledge.json`
2. **experiment_experiences.json**：經驗庫，記錄為什麼成功/失敗
3. **feed.json**（已發表文章）：每篇文章都引用了實驗編號
4. **experiments/*.py + *_results.json**：腳本和結果
5. **research_program.md**：研究路線和已完成項目
6. **LanceDB 語義搜尋**：`uv run python scripts/build_knowledge_index.py search --query "主題"`

## 核心原則
1. **不用 agent 寫論文** — 在主對話中進行
2. **每個數字必須從 JSON 追溯** — 不從記憶抄
3. **重跑實驗確認** — 不信舊結果
4. **文獻搜尋先於寫作** — 至少 20 篇相關論文
5. **每篇論文必須有 reproduce.py**
6. **搜尋知識庫、經驗庫、已發表文章** — 找出所有相關實驗和發現
