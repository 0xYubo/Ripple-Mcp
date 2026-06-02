"""
MCP Server：field-impact-mcp  —  通用语义影响分析工具
支持任意变更场景，不限于字段坐标，不限于 Python。
"""
from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from .ast_analyzer import analyze_project, trace_callers
from .reporter import build_report
from .scanner import get_context, scan

server = Server("field-impact-mcp")

# A1：服务端会话缓存，key = project_path
# 新问题3修复：改用 OrderedDict 实现 LRU 驱逐（最近使用的留在末尾，超限淘汰头部），
#             替代之前简单 FIFO（next(iter(_cache))）
_CACHE_MAX = 20
_cache: OrderedDict[str, dict[str, list]] = OrderedDict()


def _cache_set(project_path: str, key: str, value: list) -> None:
    if project_path in _cache:
        _cache.move_to_end(project_path)   # LRU：刚写入的移到末尾（最近使用）
    else:
        if len(_cache) >= _CACHE_MAX:
            _cache.popitem(last=False)     # 淘汰最久未使用的（头部）
        _cache[project_path] = {"scan_results": [], "ast_results": []}
    _cache[project_path][key] = value


def _cache_get(project_path: str) -> dict[str, list]:
    if project_path in _cache:
        _cache.move_to_end(project_path)   # LRU：读取也更新位置
    return _cache.get(project_path, {"scan_results": [], "ast_results": []})


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [

        # ── 1. 通用 pattern 扫描 ─────────────────────────────────────
        types.Tool(
            name="scan_patterns",
            description=(
                "在代码库中搜索任意正则表达式 pattern，支持 Python/TypeScript/JavaScript/任意文本文件。"
                "这是最通用的搜索工具，适用于所有变更场景：字段访问、函数调用、字符串值、常量、"
                "配置项、API 路径、SQL 字段名、注释、枚举值等任何内容。"
                "当用户描述任何类型的代码变更并想知道影响范围时，调用此工具。"
                "由 Claude 根据变更描述决定要搜什么 pattern，此工具只负责机械执行搜索。"
            ),
            inputSchema={
                "type": "object",
                "required": ["project_path", "patterns"],
                "properties": {
                    "project_path": {"type": "string", "description": "项目根目录绝对路径"},
                    "patterns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "正则表达式列表，支持任意内容。例如："
                            "字段访问: [\"machine\\.x\", \"machine\\['x'\\]\"] | "
                            "函数调用: [\"calculate_distance\\(\"] | "
                            "字符串值: [\"'success'\", \"\\\"failed\\\"\"] | "
                            "常量: [\"STATUS_OK\", \"MAX_RETRY\"] | "
                            "API路径: [\"/api/external/\"] | "
                            "SQL字段: [\"survey_status_today\"] | "
                            "导入: [\"from plogen_tools import\"]"
                        ),
                    },
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "文件扩展名，默认 ['.py','.ts','.tsx','.js','.jsx']",
                        "default": [".py", ".ts", ".tsx", ".js", ".jsx"],
                    },
                    "exclude_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "排除目录，不传则使用默认排除列表（node_modules/.venv/dist 等），传 [] 则不排除任何目录",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "最大返回结果数，默认 2000",
                        "default": 2000,
                    },
                },
            },
        ),

        # ── 2. Python AST 精确分析 ────────────────────────────────────
        types.Tool(
            name="analyze_python_ast",
            description=(
                "对 Python 代码做 AST 级别精确分析，比 grep 更准确。"
                "支持多种搜索目标，可同时指定多类：\n"
                "- symbols: 任何标识符（变量名、类名、常量名）\n"
                "- field_names: 字段/属性名（捕获 obj.field / obj['field'] / obj.get('field')）\n"
                "- string_values: 字符串字面量值（捕获代码中的字符串常量）\n"
                "- call_names: 函数/方法调用名\n"
                "- import_names: 导入的模块或符号名\n"
                "每个命中都标注所在函数名、访问方式和置信度，适合需要精确上下文的场景。"
            ),
            inputSchema={
                "type": "object",
                "required": ["project_path"],
                "properties": {
                    "project_path": {"type": "string", "description": "Python 项目根目录绝对路径"},
                    "symbols":       {"type": "array", "items": {"type": "string"}, "description": "标识符名列表，如 ['AllEq', 'DEFAULT_TTL']"},
                    "field_names":   {"type": "array", "items": {"type": "string"}, "description": "字段/属性名列表，如 ['x', 'y', 'status']"},
                    "string_values": {"type": "array", "items": {"type": "string"}, "description": "字符串字面量值列表，如 ['success', 'failed']"},
                    "call_names":    {"type": "array", "items": {"type": "string"}, "description": "函数/方法调用名列表，如 ['get_eq_partition']"},
                    "import_names":  {"type": "array", "items": {"type": "string"}, "description": "导入符号/模块名列表，如 ['plogen_tools']"},
                    "exclude_dirs":  {"type": "array", "items": {"type": "string"}, "description": "排除目录，不传则使用默认排除列表，传 [] 则不排除任何目录"},
                    "max_results":   {"type": "integer", "description": "最大返回结果数，默认 2000", "default": 2000},
                },
            },
        ),

        # ── 3. 代码上下文查看 ─────────────────────────────────────────
        types.Tool(
            name="get_code_context",
            description=(
                "获取指定文件某一行前后的代码上下文，帮助判断命中处是否真正受变更影响。"
                "当 scan_patterns 或 analyze_python_ast 返回的代码片段不足以判断时，调用此工具。"
            ),
            inputSchema={
                "type": "object",
                "required": ["file_path", "line_number"],
                "properties": {
                    "file_path": {"type": "string", "description": "文件绝对路径"},
                    "line_number": {"type": "integer", "description": "目标行号（从 1 开始）"},
                    "context_lines": {"type": "integer", "description": "前后各显示行数，默认 6", "default": 6},
                },
            },
        ),

        # ── 4. 生成报告（A1：支持服务端缓存，scan_results/ast_results 可选）────
        types.Tool(
            name="generate_impact_report",
            description=(
                "将扫描结果聚合成结构化 Markdown 影响分析报告。"
                "若不传 scan_results/ast_results，自动使用该 project_path 的最近一次扫描缓存。"
                "推荐工作流：先调用 scan_patterns 和/或 analyze_python_ast，再调用此工具生成报告。"
            ),
            inputSchema={
                "type": "object",
                "required": ["change_description", "project_path"],
                "properties": {
                    "change_description": {
                        "type": "string",
                        "description": "变更描述，如「将 survey_status_today 字段类型从 INT 改为 VARCHAR」",
                    },
                    "project_path": {"type": "string"},
                    "scan_results": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "scan_patterns 返回的结果，不传则自动使用该 project_path 的缓存",
                    },
                    "ast_results": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "analyze_python_ast 返回的结果，不传则自动使用该 project_path 的缓存",
                    },
                },
            },
        ),

        # ── 5. 调用链追踪（A3）────────────────────────────────────────
        types.Tool(
            name="trace_callers",
            description=(
                "找出项目中所有直接调用指定函数的函数和文件。"
                "适合回答「改了函数 X，哪些地方会受影响？」"
                "返回结果包含调用位置的文件、行号、所在函数名和置信度。"
            ),
            inputSchema={
                "type": "object",
                "required": ["project_path", "function_name"],
                "properties": {
                    "project_path": {"type": "string", "description": "Python 项目根目录绝对路径"},
                    "function_name": {"type": "string", "description": "要追踪的函数名，如 'get_eq_partition'"},
                    "exclude_dirs": {"type": "array", "items": {"type": "string"}, "description": "排除目录，不传则使用默认排除列表，传 [] 则不排除任何目录"},
                },
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        result = await _dispatch(name, arguments)
        return [types.TextContent(type="text", text=result)]
    except Exception as e:
        return [types.TextContent(type="text", text=f"错误：{type(e).__name__}: {e}")]


async def _dispatch(name: str, args: dict[str, Any]) -> str:
    if name == "scan_patterns":
        project_path = args["project_path"]
        # B4：用 "key" in args 区分"未传"和"传了空列表"，避免 [] or None 静默覆盖
        extensions   = args["extensions"]   if "extensions"   in args else None
        exclude_dirs = args["exclude_dirs"] if "exclude_dirs" in args else None
        max_results  = args.get("max_results", 2000)

        results = scan(
            project_path=project_path,
            patterns=args["patterns"],
            extensions=extensions,
            exclude_dirs=exclude_dirs,
            max_results=max_results,
        )
        _cache_set(project_path, "scan_results", results)
        return json.dumps(results, ensure_ascii=False, indent=2)

    elif name == "analyze_python_ast":
        project_path = args["project_path"]
        exclude_dirs = args["exclude_dirs"] if "exclude_dirs" in args else None

        results = analyze_project(
            project_path=project_path,
            # 空列表与 None 对 analyze_file 语义相同（set([]) == set(None or [])），
            # 用 or None 简化，有意为之，不是 bug
            symbols=args.get("symbols") or None,
            field_names=args.get("field_names") or None,
            string_values=args.get("string_values") or None,
            call_names=args.get("call_names") or None,
            import_names=args.get("import_names") or None,
            exclude_dirs=exclude_dirs,
            max_results=args.get("max_results", 2000),   # 设计6：与 scan_patterns 对称
        )
        _cache_set(project_path, "ast_results", results)
        return json.dumps(results, ensure_ascii=False, indent=2)

    elif name == "get_code_context":
        return get_context(
            file_path=args["file_path"],
            line_number=args["line_number"],
            context_lines=args.get("context_lines", 6),
        )

    elif name == "generate_impact_report":
        project_path = args["project_path"]
        # 问题1修复：用 "key" in args 区分"未传"和"传了空列表"，避免 [] or cache 静默覆盖
        cached = _cache_get(project_path)
        scan_results = args["scan_results"] if "scan_results" in args else cached["scan_results"]
        ast_results  = args["ast_results"]  if "ast_results"  in args else cached["ast_results"]
        return build_report(
            change_description=args["change_description"],
            project_path=project_path,
            scan_results=scan_results,
            ast_results=ast_results,
        )

    elif name == "trace_callers":
        project_path  = args["project_path"]
        function_name = args["function_name"]
        exclude_dirs  = args["exclude_dirs"] if "exclude_dirs" in args else None

        results = trace_callers(
            project_path=project_path,
            function_name=function_name,
            exclude_dirs=exclude_dirs,
        )
        return json.dumps(results, ensure_ascii=False, indent=2)

    return f"未知工具: {name}"


async def run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())
