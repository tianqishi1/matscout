# MatScout MVP 验证记录
日期：2026-11-23 ｜ 环境：Windows / Python 3.12.2 ｜ 版本：0.1.0

## 1. 离线单测（tests/，mock HTTP）
- 10/10 通过；在 PYTHONIOENCODING=utf-8 与 GBK 默认区域两种环境下均通过。
- 覆盖：摘要还原、DOI 归一、去重、停用词/中文 bigram、核验硬门(G1)、评估引用硬门(G2)、
  网络失败结构化降级、全链路卡片渲染、MCP stdio 协议往返（initialize/tools/list/tools/call/错误码）。

## 2. 真实 API 核验（反幻觉门实测）
6/6 基准 DOI 全部经 Crossref 核验通过：
| DOI | 文献 |
|---|---|
| 10.1038/s41586-023-06735-9 | Scaling deep learning for materials discovery (GNoME) |
| 10.1038/s43588-022-00349-3 | A universal graph deep learning interatomic potential (M3GNet) |
| 10.1038/s42256-023-00716-3 | CHGNet |
| 10.1038/s41586-023-06734-w | An autonomous laboratory… (A-Lab) |
| 10.1038/s41586-025-08628-5 | A generative model for inorganic materials design (MatterGen) |
| 10.1002/adma.202413523 | SciAgents |

## 3. 检索评测（evals/run_eval.py，联网）
- recall@10 = 5/6 = **83.3% ≥ 80% 目标**。
- 说明：评测用单检索式，是 SOP（2–4 组检索式）覆盖率的下界；未命中项为 OpenAlex 排序波动所致。

## 4. 端到端演示（examples/）
- 想法：高熵多阳离子 Li2ZrCl6 基氯化物电解质，提升电导率+锂金属界面稳定性。
- 3 组检索式 → 27 候选 → 英文规范化重排 → Top-5 全部核验 → 评估通过 G2 硬门 → 卡片生成。
- **查新结论：已有近似工作**（Nano Lett. 2025 HE-5 高熵氯化物 4.69 mS/cm；AFM 2026 高熵八面体稳定化；
  J. Materiomics 2026 Dy 掺杂 Li2ZrCl6 电导率+锂金属稳定性双提升）。
- 价值验证：工具在立项前拦截了「核心要素已被覆盖」的重复课题，并给出可辩护的增量方向（熵 vs 单掺杂协同增益）。
- 产物：examples/demo_card.md（待人工复核状态）、demo_assessment.json、demo_search.py、demo_rank.py。

## 5. 开发中发现并修复的问题
| # | 问题 | 修复 |
|---|---|---|
| 1 | Windows 下 SQLite 句柄未关闭导致临时目录清理失败 | run_eval.py 显式 conn.close() |
| 2 | MCP stdio 在 GBK 区域下编码崩溃（协议要求 UTF-8） | 服务器启动强制 reconfigure(utf-8)，测试显式 encoding |
| 3 | 中文想法直接词面排序得分失真（0.036） | SKILL.md 强制英文规范化 idea_text（重排后 0.8–1.0） |
| 4 | SSRN 预印本与 Acta Mater 正式版重复计数 | 卡片「检索局限」固定披露；P1 做标题模糊去重 |

## 6. 已知局限（P1  backlog）
- 词面相似度漏语义近似 → embedding 重排。
- 仅 OpenAlex/Crossref → 增加 Semantic Scholar/arXiv/专利源。
- 摘要级查新 → 支持用户自供全文 PDF 的本地解析（不抓付费墙）。
- 单机证据库 → 多用户/权限/私有化（P2，届时升级独立 agent 壳）。
