---
name: materials-novelty-check
description: 材料科研想法查新副驾驶。当用户要查新、评估研究想法新颖性、找最接近工作、开题/立项前调研、或要一张「查新卡片」时使用；用户没有想法时也可先在指定材料领域检索归纳候选方向。需要 matscout MCP 服务器（或 CLI 兜底）。触发词：查新、新颖性、novelty check、最接近工作、开题、立项评估、想法评估。
---

# 材料想法查新 SOP（MatScout）

## 硬约束（违反即失败，详见仓库 AGENTS.md）
1. 禁止凭记忆补 DOI/作者/年份；一切引用先过 `verify_citation`，verified=false 不得进入结论。
2. 评估的每条差异点必须挂**已核验** paper_id；服务端硬门会拒绝，按报错补核验，不得绕过。
3. 卡片定稿前必须经用户明确确认（人工复核门）；保留 AI 披露文案。
4. 不得把预测/相似度当实测证据；不得宣称「已验证可行」。

## 流程
0. **澄清想法**（最多问 2 个问题）：材料体系 / 目标性能 / 方法手段 / 应用场景。
   用户没有想法时：先 `search_literature`（领域 + review，近 3 年），归纳 3 个候选方向供用户挑选，再进入查新。
1. `create_project(name, field, idea)` —— idea 存用户原文。
2. **构造检索式**：英文为主，2–4 组同义/上下位表达（如 `high-entropy chloride solid electrolyte`、`lithium metal interface stability halide electrolyte`）。逐组 `search_literature(project_id, query, limit=10, year_from=近5年)`。
3. `find_closest_work(project_id, idea_text=英文规范化想法, k=5)`：**必须传英文 idea_text**（中文原文会使词面得分失真）；审阅 matched_terms 判断相关性；明显不相关则换检索式补搜，不要硬凑 Top-5。
4. 对拟引用的每篇文献 `verify_citation(identifier=doi, project_id)`；需要摘要细节时 `get_paper`。
5. **撰写评估**并 `save_novelty_assessment`：
   - verdict ∈ {高度新颖, 增量创新, 已有近似工作, 高度重复}；confidence ∈ {low, medium, high}
   - summary：一句话结论依据
   - deltas：每篇 {claim: 重合点, paper_id, difference: 本想法的实质差异}
   - feasibility：{equipment, compute, precursors, timeline, other}，全部标注「待专家确认」
   - risks：关键风险列表；limitations：本次检索的覆盖局限
6. `render_novelty_card(project_id)` → 展示卡片 → **明确询问用户确认或修改**。未确认前状态为「待人工复核」，不得用于立项/投稿依据。

## 判断标准
- **高度新颖**：Top 工作中无「同体系+同方法+同目标」者，差异点是本质性的。
- **增量创新**：框架已有，但材料体系/关键参数/机理视角有实质差异。
- **已有近似工作**：核心要素已被覆盖，差异仅常规替换。
- **高度重复**：目标与方法均已被明确报道。
- 置信度降级条件：有效命中 <5 篇、摘要缺失多、想法表述含糊、仅词面匹配无语义确认。

## 兜底
- MCP 不可用 → 用 CLI（见 README）：create-project / search / verify / closest / assess / card。
- 网络失败 → 如实告知并建议稍后重试；**绝不降级为「凭模型知识查新」**。

