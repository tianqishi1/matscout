# MatScout — 材料科研查新副驾驶（Skill + MCP 工具层）

把「想法 → 最接近工作 → 差异点 → 可行性」做成**可溯源、可核查、零引用幻觉**的查新卡片。
零第三方依赖，Python 3.10+ 即可运行。

## 快速开始（CLI，无需 MCP 宿主）
```powershell
$env:PYTHONPATH = "D:\codex\matscout\src"
python -m matscout.cli create-project --name "demo" --field "固态电解质" --idea "用高熵氯化物固态电解质提升锂金属电池界面稳定性"
python -m matscout.cli search --project 1 --query "high-entropy chloride solid electrolyte lithium" --limit 10
python -m matscout.cli verify --doi "10.1038/s41586-023-06735-9"
python -m matscout.cli closest --project 1 --k 5
# …由宿主 agent 按 SKILL.md 撰写评估后…
python -m matscout.cli card --project 1 --out card.md
```

## 接入 Codex（~/.codex/config.toml）
```toml
[mcp_servers.matscout]
command = "python"
args = ["-m", "matscout.mcp_server"]
env = { PYTHONPATH = "D:\\codex\\matscout\\src" }
```
Claude Desktop 的 claude_desktop_config.json 用同构 mcpServers 配置。

## 安装 Skill
复制 `skills/materials-novelty-check/` 到宿主 skills 目录（Codex: `~/.codex/skills/`）。

## 测试与评测
```powershell
python -m unittest discover -s tests -v     # 离线单测
python evals/run_eval.py                    # 联网 recall@10 评测
```

## 验证状态
10/10 单测通过；真实 API recall@10 = 83.3%（目标≥80%）；端到端演示卡片见 examples/demo_card.md。详见 docs/VALIDATION.md。

## 文档
- 产品设计：docs/PRD.md ｜ 技术方案：docs/TECH.md ｜ 业务约束：AGENTS.md
- 演示卡片：examples/

## 定位声明
MatScout 是科研辅助工具（co-scientist），不代写代发论文；所有交付物含 AI 使用披露，关键结论需人工复核。

