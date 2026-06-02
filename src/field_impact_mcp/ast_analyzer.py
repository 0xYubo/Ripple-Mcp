"""
Python AST 分析器：精确定位字段访问，区分读/写，标注上下文函数名。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any


class _FieldVisitor(ast.NodeVisitor):
    def __init__(self, field_names: set[str], object_names: set[str]):
        self.field_names = field_names
        self.object_names = object_names
        self.hits: list[dict[str, Any]] = []
        self._func_stack: list[str] = []

    # 追踪当前所在函数名
    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _current_func(self) -> str:
        return self._func_stack[-1] if self._func_stack else "<module>"

    def _record(self, node: ast.AST, access_type: str, field: str, obj: str):
        self.hits.append({
            "line": getattr(node, "lineno", 0),
            "col": getattr(node, "col_offset", 0),
            "access_type": access_type,   # "attribute" | "subscript" | "get_call"
            "field": field,
            "object": obj,
            "function": self._current_func(),
        })

    def visit_Attribute(self, node: ast.Attribute):
        # obj.field
        if node.attr in self.field_names:
            obj_name = ast.unparse(node.value) if hasattr(ast, "unparse") else "?"
            if not self.object_names or any(n in obj_name for n in self.object_names):
                self._record(node, "attribute", node.attr, obj_name)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        # obj['field']
        slice_val = node.slice
        if isinstance(slice_val, ast.Constant) and slice_val.value in self.field_names:
            obj_name = ast.unparse(node.value) if hasattr(ast, "unparse") else "?"
            if not self.object_names or any(n in obj_name for n in self.object_names):
                self._record(node, "subscript", str(slice_val.value), obj_name)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # obj.get('field') / obj.get('field', default)
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value in self.field_names
        ):
            obj_name = ast.unparse(node.func.value) if hasattr(ast, "unparse") else "?"
            if not self.object_names or any(n in obj_name for n in self.object_names):
                self._record(node, "get_call", str(node.args[0].value), obj_name)
        self.generic_visit(node)


def analyze_file(
    file_path: str,
    field_names: list[str],
    object_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """分析单个 Python 文件，返回所有字段访问记录。"""
    try:
        source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=file_path)
    except SyntaxError:
        return []
    except Exception:
        return []

    visitor = _FieldVisitor(
        field_names=set(field_names),
        object_names=set(object_names) if object_names else set(),
    )
    visitor.visit(tree)

    for hit in visitor.hits:
        hit["file"] = file_path
    return visitor.hits


def analyze_project(
    project_path: str,
    field_names: list[str],
    object_names: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """递归分析项目中所有 .py 文件。"""
    excl = set(exclude_dirs or [".venv", "venv", "__pycache__", "node_modules", ".git"])
    all_hits: list[dict] = []

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in excl]
        for fname in files:
            if fname.endswith(".py"):
                fpath = os.path.join(root, fname)
                hits = analyze_file(fpath, field_names, object_names)
                all_hits.extend(hits)

    all_hits.sort(key=lambda h: (h["file"], h["line"]))
    return all_hits
