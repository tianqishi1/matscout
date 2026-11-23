# MatScout 技术实现方案
版本：v0.1 ｜ 日期：2026-11-23

## 1. 总体架构
```
用户 ── 宿主 Agent (Codex/Claude/Bohrium…)
          │  加载 SKILL.md（领域 SOP：HOW）
          ▼
      MCP stdio 客户端 ──JSON-RPC/stdio──► matscout MCP server（WHAT，确定性）
                                              │
                    ┌─────────────┬───────────┼──────────────┐
                    ▼             ▼           ▼              ▼
               OpenAlex API  Crossref API  SQLite 证据库   卡片渲染器
               (检索/摘要)   (DOI 核验)   (provenance)   (Markdown)
```
设计原则：
- **能力层宿主无关**：MCP server 零第三方依赖（Python 3.10+ 标准库），任何宿主可接。
- **硬门在服务端**：引用必须核验、差异点必须挂已核验文献——不依赖模型自觉。
- **重逻辑在代码，SOP 在 skill**：SKILL.md 只写流程与判断标准（渐进披露）。
- **一切可溯源**：检索原始响应、时间戳、来源全部入库。

## 2. 技术选型与理由
| 决策 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.10+，纯标准库 | 科研用户环境异构；零依赖=装完即用；urllib/sqlite3/json 足够 |
| MCP 实现 | 手写 stdio JSON-RPC（协议 2025-06-18，兼容 2024-11-05） | 避免 pip/网络安装风险；协议面小（initialize/tools/list/tools/call/ping），可单测 |
| 检索源 | OpenAlex（主）+ Crossref（核验） | 免费、无 key、覆盖材料领域好、有摘要（inverted index 可还原） |
| 存储 | SQLite 单文件（默认 ~/.matscout/matscout.db，可用 MATSCOUT_DB 覆盖） | 本地、可携带、课题组内可拷贝；P2 再换 Postgres |
| 相似度 | 词面 overlap coefficient + 匹配词展示（透明可解释） | MVP 够用且可审计；embedding 重排列 P1 |
| HTTP | urllib + 超时 20s + 429/5xx 指数退避重试 + 每主机最小请求间隔 + SQLite 响应缓存 | 遵守 API 礼仪（OpenAlex polite pool mailto、Crossref UA） |

## 3. 目录结构
```
matscout/
├── AGENTS.md                  # 业务约束（对在此仓库工作的 agent 强制生效）
├── README.md                  # 安装/接入/快速开始
├── docs/{PRD.md,TECH.md}
├── src/matscout/
│   ├── __init__.py
│   ├── db.py                  # schema + 连接 + CRUD
│   ├── http.py                # 限速/重试/缓存 GET JSON
│   ├── sources.py             # OpenAlex/Crossref 适配、摘要还原、归一化
│   ├── similarity.py          # 分词/停用词/overlap 打分
│   ├── core.py                # 业务逻辑（工具的实现体，CLI/MCP 共用）
│   ├── card.py                # 查新卡片 Markdown 渲染
│   ├── mcp_server.py          # stdio JSON-RPC 循环 + 工具 schema
│   └── cli.py                 # python -m matscout.cli …（无 MCP 宿主也能用）
├── skills/materials-novelty-check/SKILL.md
├── evals/{cases.jsonl,run_eval.py}
├── tests/test_matscout.py
└── examples/                  # 演示产出（卡片样例）
```

## 4. 数据模型（SQLite）
- projects(id, name, field, idea, created_at)
- papers(id, doi UNIQUE, title, abstract, year, venue, authors_json, url, source, raw_json, retrieved_at, verified, verified_via)
- searches(id, project_id, query, filters_json, created_at) / search_results(search_id, paper_id, rank)
- evidence(id, project_id, kind, content_json, paper_ids_json, actor, created_at)
- assessments(id, project_id, verdict, confidence, summary, deltas_json, feasibility_json, risks_json, limitations, created_at)
- http_cache(key PK, url, response_json, fetched_at)
约束：assessments.deltas_json 中每条 delta 的 paper_id 必须存在于 papers 且 verified=1（core 层强制）。

## 5. MCP 工具清单（8 个）
| 工具 | 输入（要点） | 输出 / 硬门 |
|---|---|---|
| create_project | name, field, idea | project_id |
| search_literature | query, project_id?, year_from?, year_to?, limit≤25 | 归一化论文列表（含 paper_id/doi/来源/时间）；原始响应入库 |
| verify_citation | doi 或 title | verified + 权威元数据；**查无此文→verified=false，绝不编造** |
| find_closest_work | project_id, idea_text?, k=5 | 透明打分排序 + 匹配词；结果存 evidence |
| save_novelty_assessment | project_id, verdict, confidence, summary, deltas[{claim,paper_id,overlap,difference}], feasibility, risks, limitations | **delta 引用未核验文献→拒绝** |
| render_novelty_card | project_id | Markdown 卡片（含证据附录+披露+复核状态） |
| list_evidence | project_id | 证据清单 |
| get_paper | paper_id 或 doi | 单篇详情（含核验状态） |

## 6. 关键算法
- 摘要还原：OpenAlex abstract_inverted_index → 按位置拼回原文。
- 去重：DOI 小写归一（去 https://doi.org/ 前缀）；无 DOI 用标题归一哈希。
- 相似度：idea 与 title+abstract 分词（小写、字母数字、停用词表含材料通用词），
  score = |I∩P| / |I|（overlap coefficient），title 命中加权 ×1.5；输出 matched_terms 供人工审计。
- 核验：Crossref /works/{doi}；失败回退 OpenAlex /works/doi:{doi}；标题核验用 Crossref query.bibliographic 取 top1 且标题相似度≥0.9 才认。

## 7. 错误处理与合规
- 网络失败：重试 3 次（1s/2s/4s），仍失败→工具返回结构化 error（不抛崩宿主），skill 指引降级话术。
- 限速：OpenAlex ≥0.35s/req，Crossref ≥1s/req；UA 带 mailto（polite pool）。
- 隐私：想法文本只发往开放书目 API 的检索词；**不上传全文/未发表数据**；证据库纯本地。
- 许可：不内置任何商业数据/软件；输出卡片含 AI 披露。

## 8. 测试与评测
- 单测（unittest，离线 mock HTTP）：DB 门、去重、摘要还原、相似度、卡片渲染、MCP 协议帧。
- 集成冒烟：真实 API 检索 + 核验 + 全链路生成演示卡片。
- 评测集 evals/cases.jsonl：真实材料想法 + 已知相关 DOI；run_eval.py 计算 recall@10（需联网）。

## 9. 宿主接入
- Codex：config.toml [mcp_servers.matscout] command=python args=["-m","matscout.mcp_server"] env PYTHONPATH=src。
- Claude Desktop：claude_desktop_config.json mcpServers 同构。
- Skill 安装：复制 skills/materials-novelty-check 到宿主 skills 目录（如 ~/.codex/skills）。
- 无 MCP 宿主：直接用 CLI（python -m matscout.cli …）。

## 10. 后续演进
P1：Semantic Scholar/arXiv 源、embedding 重排、XRD skill（pymatgen）、计算 MCP 桥接；
P2：多用户证据库（Postgres+权限）、硬审批门产品化、私有化部署 → 独立 agent 壳复用本能力层。
