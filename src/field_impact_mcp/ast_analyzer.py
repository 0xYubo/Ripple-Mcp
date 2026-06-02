"""
Python AST 分析器 — 通用版。
支持：字段访问、函数调用、字符串字面量、导入、赋值目标、返回值、类型注解。
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import Any


class _UniversalVisitor(ast.NodeVisitor):
    """
    通用访问器：按需收集不同类型的节点。
    通过 targets 参数控制收集哪些类型。
    """

    def __init__(
        self,
        symbols: set[str],           # 任何名字（变量、函数、类、常量）
        field_names: set[str],        # 字段名（用于 obj.field / obj['field']）
        string_values: set[str],      # 字符串字面量值
        call_names: set[str],         # 函数调用名
        import_names: set[str],       # 导入模块/符号名
    ):
        self.symbols = symbols
        self.field_names = field_names
        self.string_values = string_values
        self.call_names = call_names
        self.import_names = import_names
        self.hits: list[dict[str, Any]] = []
        self._func_stack: list[str] = []

    def _func(self) -> str:
        return self._func_stack[-1] if self._func_stack else "<module>"

    def _add(self, node: ast.AST, kind: str, value: str, extra: str = ""):
        self.hits.append({
            "line": getattr(node, "lineno", 0),
            "col": getattr(node, "col_offset", 0),
            "kind": kind,
            "value": value,
            "extra": extra,
            "function": self._func(),
        })

    def _check_annotation(self, ann_node: ast.expr | None, context: str):
        """检查类型注解节点是否含有目标 symbol。"""
        if ann_node is None:
            return
        ann_str = ast.unparse(ann_node) if hasattr(ast, "unparse") else ""
        for sym in self.symbols:
            if sym in ann_str:
                self._add(ann_node, "type_annotation", ann_str, context)
                break

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._func_stack.append(node.name)
        # 函数名本身
        if node.name in self.symbols or node.name in self.call_names:
            self._add(node, "function_def", node.name)
        # 参数类型注解：def fn(x: float, y: SomeType)
        for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
            self._check_annotation(arg.annotation, f"param:{arg.arg}")
        if node.args.vararg:
            self._check_annotation(node.args.vararg.annotation, f"param:*{node.args.vararg.arg}")
        if node.args.kwarg:
            self._check_annotation(node.args.kwarg.annotation, f"param:**{node.args.kwarg.arg}")
        # 返回值类型注解：def fn() -> SomeType
        self._check_annotation(node.returns, "return_type")
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef):
        if node.name in self.symbols:
            self._add(node, "class_def", node.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        # 变量 / 常量引用
        if node.id in self.symbols:
            self._add(node, "name_ref", node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # obj.field
        if node.attr in self.field_names:
            obj = ast.unparse(node.value) if hasattr(ast, "unparse") else "?"
            self._add(node, "attr_access", node.attr, obj)
        # obj 本身也可能是 symbol
        if isinstance(node.value, ast.Name) and node.value.id in self.symbols:
            self._add(node.value, "name_ref", node.value.id, f"via .{node.attr}")
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript):
        # obj['field']
        sl = node.slice
        if isinstance(sl, ast.Constant) and sl.value in self.field_names:
            obj = ast.unparse(node.value) if hasattr(ast, "unparse") else "?"
            self._add(node, "subscript_access", str(sl.value), obj)
        # 字符串字面量匹配
        if isinstance(sl, ast.Constant) and isinstance(sl.value, str) and sl.value in self.string_values:
            self._add(node, "string_subscript", sl.value)
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        # 字符串常量
        if isinstance(node.value, str) and node.value in self.string_values:
            self._add(node, "string_literal", node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # 函数调用：fn(...) 或 obj.fn(...)
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
            # obj.get('field') 模式
            if name == "get" and node.args and isinstance(node.args[0], ast.Constant):
                val = node.args[0].value
                if val in self.field_names:
                    obj = ast.unparse(func.value) if hasattr(ast, "unparse") else "?"
                    self._add(node, "get_call", str(val), obj)
                if isinstance(val, str) and val in self.string_values:
                    self._add(node, "get_call_str", str(val))

        if name and (name in self.call_names or name in self.symbols):
            self._add(node, "call", name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            if alias.name in self.import_names or alias.asname in (self.import_names - {None}):
                self._add(node, "import", alias.name, alias.asname or "")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        if mod in self.import_names or any(p in mod for p in self.import_names):
            self._add(node, "import_from", mod)
        for alias in node.names:
            if alias.name in self.import_names or alias.name in self.symbols:
                self._add(node, "import_symbol", alias.name, mod)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        # 类型注解：x: SomeType = ...
        ann = ast.unparse(node.annotation) if hasattr(ast, "unparse") else ""
        for sym in self.symbols:
            if sym in ann:
                self._add(node, "type_annotation", ann)
                break
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign):
        # 赋值目标中的 symbol
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in self.symbols:
                self._add(target, "assignment", target.id)
        self.generic_visit(node)


def analyze_file(
    file_path: str,
    symbols: list[str] | None = None,
    field_names: list[str] | None = None,
    string_values: list[str] | None = None,
    call_names: list[str] | None = None,
    import_names: list[str] | None = None,
) -> list[dict[str, Any]]:
    """分析单个 Python 文件，返回所有命中记录。"""
    try:
        source = Path(file_path).read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source, filename=file_path)
    except (SyntaxError, Exception):
        return []

    visitor = _UniversalVisitor(
        symbols=set(symbols or []),
        field_names=set(field_names or []),
        string_values=set(string_values or []),
        call_names=set(call_names or []),
        import_names=set(import_names or []),
    )
    visitor.visit(tree)

    for hit in visitor.hits:
        hit["file"] = file_path
    return visitor.hits


def analyze_project(
    project_path: str,
    symbols: list[str] | None = None,
    field_names: list[str] | None = None,
    string_values: list[str] | None = None,
    call_names: list[str] | None = None,
    import_names: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """递归分析整个项目的所有 .py 文件。"""
    excl = set(exclude_dirs or [".venv", "venv", "__pycache__", "node_modules", ".git"])
    all_hits: list[dict] = []

    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in excl]
        for fname in files:
            if fname.endswith(".py"):
                hits = analyze_file(
                    os.path.join(root, fname),
                    symbols=symbols,
                    field_names=field_names,
                    string_values=string_values,
                    call_names=call_names,
                    import_names=import_names,
                )
                all_hits.extend(hits)

    all_hits.sort(key=lambda h: (h["file"], h["line"]))
    return all_hits
