"""
MCP Server：field-impact-mcp
暴露三个工具供 Claude Code / Codex 自动调用。
"""
from __future__ import annotations

import json
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from .ast_analyzer import analyze_project
from .reporter import build_report
from .scanner import build_patterns, get_context, scan

server = Server("field-impact-mcp")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="scan_field_usages",
            description=(
                "扫描代码库中所有访问指定字段的位置，支持 Python、TypeScript、JavaScript。"
                "使用 ripgrep 或 grep 进行全文搜索，返回文件路径、行号和代码片段。"
                "适合回答「哪些地方用到了 machine.x / machine['x']」这类问题。"
                "当用户询问某个字段/属性的影响范围，或想知道修改某个字段会波及哪些文件时，自动调用此工具。"
            ),
            inputSchema={
                "type": "object",
                "required": ["project_path", "field_names"],
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "项目根目录的绝对路径",
                    },
                    "field_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要搜索的字段名列表，如 ['x', 'y', 'l', 'w']",
                    },
                    "object_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "（可选）限定对象名，如 ['machine', 'eq', 'dataset_dict']，为空则搜索所有对象",
                        "default": [],
                    },
                    "extensions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "文件扩展名过滤，默认 ['.py', '.ts', '.tsx', '.js', '.jsx']",
                        "default": [".py", ".ts", ".tsx", ".js", ".jsx"],
                    },
                    "exclude_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "排除目录，默认排除 node_modules/.venv/__pycache__ 等",
                        "default": [],
                    },
                },
            },
        ),
        types.Tool(
            name="analyze_python_ast",
            description=(
                "对 Python 代码做 AST 级别的精确字段访问分析。"
                "比 grep 更精确：能区分 obj.field / obj['field'] / obj.get('field')，"
                "并标注每处访问所在的函数名。"
                "当需要精确分析 Python 代码中字段访问的上下文（哪个函数、什么访问方式）时，自动调用此工具。"
            ),
            inputSchema={
                "type": "object",
                "required": ["project_path", "field_names"],
                "properties": {
                    "project_path": {
                        "type": "string",
                        "description": "Python 项目根目录的绝对路径",
                    },
                    "field_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "要分析的字段名列表，如 ['x', 'y']",
                    },
                    "object_names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "（可选）限定对象名，为空则分析所有对象的字段访问",
                        "default": [],
                    },
                    "exclude_dirs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "排除目录",
                        "default": [],
                    },
                },
            },
        ),
        types.Tool(
            name="get_code_context",
            description=(
                "获取指定文件某一行的前后代码上下文，帮助理解命中位置的完整逻辑。"
                "当 scan_field_usages 或 analyze_python_ast 返回的代码片段不足以判断影响时，调用此工具获取更多上下文。"
            ),
            inputSchema={
                "type": "object",
                "required": ["file_path", "line_number"],
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "文件的绝对路径",
                    },
                    "line_number": {
                        "type": "integer",
                        "description": "目标行号（从 1 开始）",
                    },
                    "context_lines": {
                        "type": "integer",
                        "description": "前后各显示多少行，默认 6",
                        "default": 6,
                    },
                },
            },
        ),
        types.Tool(
            name="generate_impact_report",
            description=(
                "将 scan_field_usages 和 analyze_python_ast 的结果聚合成一份结构化 Markdown 影响分析报告。"
                "完成字段扫描后调用此工具生成最终报告。"
            ),
            inputSchema={
                "type": "object",
                "required": ["change_description", "project_path", "scan_results", "ast_results"],
                "properties": {
                    "change_description": {
                        "type": "string",
                        "description": "变更描述，如「将机台坐标 x/y 从左上角改为中心点」",
                    },
                    "project_path": {
                        "type": "string",
                        "description": "项目根目录绝对路径",
                    },
                    "scan_results": {
                        "type": "array",
                        "description": "scan_field_usages 返回的结果列表",
                        "items": {"type": "object"},
                    },
                    "ast_results": {
                        "type": "array",
                        "description": "analyze_python_ast 返回的结果列表",
                        "items": {"type": "object"},
                    },
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
    if name == "scan_field_usages":
        project_path = args["project_path"]
        field_names = args["field_names"]
        object_names = args.get("object_names") or []
        extensions = args.get("extensions") or None
        exclude_dirs = args.get("exclude_dirs") or None

        patterns = build_patterns(field_names, object_names)
        results = scan(project_path, patterns, extensions, exclude_dirs)
        return json.dumps(results, ensure_ascii=False, indent=2)

    elif name == "analyze_python_ast":
        project_path = args["project_path"]
        field_names = args["field_names"]
        object_names = args.get("object_names") or None
        exclude_dirs = args.get("exclude_dirs") or None

        results = analyze_project(project_path, field_names, object_names, exclude_dirs)
        return json.dumps(results, ensure_ascii=False, indent=2)

    elif name == "get_code_context":
        file_path = args["file_path"]
        line_number = args["line_number"]
        context_lines = args.get("context_lines", 6)
        return get_context(file_path, line_number, context_lines)

    elif name == "generate_impact_report":
        return build_report(
            change_description=args["change_description"],
            project_path=args["project_path"],
            scan_results=args["scan_results"],
            ast_results=args["ast_results"],
        )

    else:
        return f"未知工具: {name}"


async def run():
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
