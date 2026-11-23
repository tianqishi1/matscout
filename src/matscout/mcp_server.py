#!/usr/bin/env python3
"""MatScout MCP server: stdio JSON-RPC, zero third-party dependencies.

Protocol: MCP 2025-06-18 (negotiates down to 2024-11-05 / 2025-03-26).
Only protocol JSON goes to stdout; diagnostics go to stderr.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # allow `python src/matscout/mcp_server.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from matscout import db
from matscout.core import CoreError, MatScout

PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18"}
DEFAULT_VERSION = "2025-06-18"


def _schema(props: dict, required: list) -> dict:
    return {"type": "object", "properties": props, "required": required, "additionalProperties": False}


_S = {"type": "string"}
_I = {"type": "integer"}
_N = {"type": "number"}

TOOLS = [
    {"name": "create_project",
     "description": "创建查新项目（想法原文+领域）。返回 project_id，后续所有工具围绕它记录证据。",
     "inputSchema": _schema({"name": _S, "field": _S, "idea": _S}, ["name", "idea"])},
    {"name": "search_literature",
     "description": "OpenAlex 文献检索（开放元数据+摘要）。建议英文检索式；结果与原始响应入本地证据库。网络失败返回结构化错误，禁止凭记忆补文献。",
     "inputSchema": _schema({"query": _S, "project_id": _I, "year_from": _I, "year_to": _I,
                             "limit": {"type": "integer", "minimum": 1, "maximum": 25}}, ["query"])},
    {"name": "verify_citation",
     "description": "引用核验硬门(G1)：DOI 走 Crossref→OpenAlex；标题走 Crossref 高置信匹配。verified=false 的文献不得进入任何结论。",
     "inputSchema": _schema({"identifier": _S, "project_id": _I}, ["identifier"])},
    {"name": "find_closest_work",
     "description": "对项目已检索文献做透明词面相似度排序（score=overlap+0.5*title_overlap，附匹配词）。无检索记录时自动先检索。",
     "inputSchema": _schema({"project_id": _I, "idea_text": _S, "k": {"type": "integer", "minimum": 1, "maximum": 10}},
                            ["project_id"])},
    {"name": "save_novelty_assessment",
     "description": "提交查新评估。硬门(G2)：deltas 中每条必须引用已核验 paper_id，否则拒绝。verdict∈{高度新颖,增量创新,已有近似工作,高度重复}；confidence∈{low,medium,high}。",
     "inputSchema": _schema({
         "project_id": _I, "verdict": _S, "confidence": _S, "summary": _S,
         "deltas": {"type": "array", "items": _schema(
             {"claim": _S, "paper_id": _I, "overlap": _S, "difference": _S}, ["claim", "paper_id", "difference"])},
         "feasibility": {"type": "object"}, "risks": {"type": "array", "items": _S}, "limitations": _S},
         ["project_id", "verdict", "confidence", "summary", "deltas"])},
    {"name": "render_novelty_card",
     "description": "生成 Markdown 查新卡片（结论/Top工作/可行性/风险/证据附录/AI披露）。输出状态恒为 pending_human_review，需用户确认。",
     "inputSchema": _schema({"project_id": _I}, ["project_id"])},
    {"name": "list_evidence",
     "description": "列出项目证据链（检索/核验/排序/评估/渲染记录，含时间戳与 paper_ids）。",
     "inputSchema": _schema({"project_id": _I}, ["project_id"])},
    {"name": "get_paper",
     "description": "读取本地证据库中单篇文献详情（含完整摘要与核验状态），供撰写差异点分析。",
     "inputSchema": _schema({"paper_id": _I, "doi": _S}, [])},
]

TOOL_IMPL = {
    "create_project": lambda ms, a: ms.create_project(a["name"], a.get("field", ""), a["idea"]),
    "search_literature": lambda ms, a: ms.search_literature(
        a["query"], project_id=a.get("project_id"), year_from=a.get("year_from"),
        year_to=a.get("year_to"), limit=a.get("limit", 10)),
    "verify_citation": lambda ms, a: ms.verify_citation(a["identifier"], project_id=a.get("project_id")),
    "find_closest_work": lambda ms, a: ms.find_closest_work(a["project_id"], idea_text=a.get("idea_text"), k=a.get("k", 5)),
    "save_novelty_assessment": lambda ms, a: ms.save_novelty_assessment(
        a["project_id"], a["verdict"], a["confidence"], a["summary"], a["deltas"],
        feasibility=a.get("feasibility"), risks=a.get("risks"), limitations=a.get("limitations")),
    "render_novelty_card": lambda ms, a: ms.render_novelty_card(a["project_id"]),
    "list_evidence": lambda ms, a: ms.list_evidence(a["project_id"]),
    "get_paper": lambda ms, a: ms.get_paper(paper_id=a.get("paper_id"), doi=a.get("doi")),
}


def handle(ms: MatScout, msg: dict):
    method = msg.get("method")
    mid = msg.get("id")
    params = msg.get("params") or {}
    if mid is None:  # notification: no response
        return None
    if method == "initialize":
        ver = params.get("protocolVersion")
        result = {
            "protocolVersion": ver if ver in PROTOCOL_VERSIONS else DEFAULT_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "matscout", "version": "0.1.0"},
            "instructions": "材料查新工具层。硬门：引用必须先 verify_citation；评估差异点必须挂已核验 paper_id；卡片需人工复核。",
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        fn = TOOL_IMPL.get(name)
        if fn is None:
            return {"jsonrpc": "2.0", "id": mid,
                    "error": {"code": -32602, "message": f"Unknown tool: {name}"}}
        try:
            out = fn(ms, args)
            result = {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False, indent=2)}],
                      "isError": False}
        except CoreError as e:
            result = {"content": [{"type": "text", "text": str(e)}], "isError": True}
        except (KeyError, TypeError, ValueError) as e:
            result = {"content": [{"type": "text", "text": f"参数错误：{e}"}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"Method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def main() -> None:
    # MCP stdio transport mandates UTF-8 regardless of host locale (Windows GBK safe).
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    ms = MatScout(db.connect())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None,
                                         "error": {"code": -32700, "message": "Parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        try:
            resp = handle(ms, msg)
        except Exception as e:  # never crash the host session
            print(f"[matscout] internal error: {e}", file=sys.stderr)
            resp = {"jsonrpc": "2.0", "id": msg.get("id"),
                    "error": {"code": -32603, "message": str(e)}}
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()

