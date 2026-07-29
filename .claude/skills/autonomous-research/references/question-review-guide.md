# Question Workflow Compatibility Pointer

研究 open question 的會員 intake、claim、回答與發布由
`.claude/skills/member-questions/SKILL.md` 擁有。

`autonomous-research` 只在已 claim 的 question 需要新實驗時接受 bounded research brief，
並回傳 verified experiment artifacts。任何 follow-up task 都要先重新讀 task-pool mode，
再由主線程走 canonical writer。
