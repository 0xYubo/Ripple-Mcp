"""
Python AST 分析器 — 通用版。
支持：字段访问、函数调用、字符串字面量、导入、赋值目标、返回值、类型注解。
"""
from __future__ import annotations

import ast
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from ._utils import to_relative, validate_project_path

_DEFAULT_EXCLUDE = {
    ".venv", "venv", "__pycache__", "node_modules",
    ".git", "dist", "build", ".next", ".mypy_cache",
}

# A4：根据 kind 分配置信度
_CONFIDENCE: dict[str, str] = {
    "attr_access":      "high",
    "subscript_access": "high",
    "get_call":         "high",
    "call":             "medium",
    "function_def":     "medium",
    "class_def":        "medium",
    "import":           "medium",
    "import_from":      "medium",
    "import_symbol":    "medium",
    "name_ref":         "medium",
    "assignment":       "medium",
    "string_literal":   "medium",
    "string_subscript": "medium",
    "get_call_str":     "medium",
    "type_annotation":  "low",
}


class _UniversalVisitor(ast.NodeVisitor):
    """
    通用访问器：按需收集不同类型的节点。
    通过 targets 参数控制收集哪些类型。

    _suppressed：记录已被父节点处理过的 ast 节点 id()，visit_Name / visit_Constant
    开头检查该集合，避免 generic_visit 触发子节点时产生重复命中（Bug 1、Bug 2）。
    """

    def __init__(
        self,
        symbols: set[str],
        field_names: set[str],
        string_values: set[str],
        call_names: set[str],
        import_names: set[str],
    ):
        self.symbols = symbols
        self.field_names = field_names
        self.string_values = string_values
        self.call_names = call_names
        self.import_names = import_names
        self.hits: list[dict[str, Any]] = []
        self._func_stack: list[str] = []
        self._suppressed: set[int] = set()   # Bug 1/2：已处理节点 id，防止重复命中

    def _func(self) -> str:
        return self._func_stack[-1] if self._func_stack else "<module>"

    def _add(self, node: ast.AST, kind: str, value: str, extra: str = "") -> None:
        self.hits.append({
            "line":       getattr(node, "lineno", 0),
            "col":        getattr(node, "col_offset", 0),
            "kind":       kind,
            "value":      value,
            "extra":      extra,
            "function":   self._func(),
            "confidence": _CONFIDENCE.get(kind, "medium"),
        })

    def _check_annotation(self, ann_node: ast.expr | None, context: str) -> None:
        """ast.walk 精确匹配注解中的 symbol。
        Bug 4 修复：去掉 break，用 matched_ids 避免同一 symbol 重复记录，
                   但允许 Union[A, B] 中 A 和 B 各自独立记录。
        Bug 1 修复：把注解里所有 Name 节点压入 _suppressed，
                   防止 generic_visit 再触发 visit_Name 产生重复 name_ref。
        """
        if ann_node is None:
            return
        matched_ids: set[str] = set()
        for child in ast.walk(ann_node):
            if isinstance(child, ast.Name):
                self._suppressed.add(id(child))         # Bug 1
                if child.id in self.symbols and child.id not in matched_ids:
                    matched_ids.add(child.id)
                    self._add(ann_node, "type_annotation", child.id, context)  # Bug 4

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        try:  # Bug 3：保证异常时 _func_stack 不残留脏帧
            if node.name in self.symbols or node.name in self.call_names:
                self._add(node, "function_def", node.name)
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                self._check_annotation(arg.annotation, f"param:{arg.arg}")
            if node.args.vararg:
                self._check_annotation(node.args.vararg.annotation, f"param:*{node.args.vararg.arg}")
            if node.args.kwarg:
                self._check_annotation(node.args.kwarg.annotation, f"param:**{node.args.kwarg.arg}")
            self._check_annotation(node.returns, "return_type")
            self.generic_visit(node)
        finally:
            self._func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # type: ignore[override]
        self.visit_FunctionDef(node)  # type: ignore[arg-type]

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name in self.symbols:
            self._add(node, "class_def", node.name)
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:
        # Bug 1：跳过已被父节点处理的 Name 节点（assignment target、注解内 Name）
        if id(node) in self._suppressed:
            self.generic_visit(node)
            return
        if node.id in self.symbols:
            self._add(node, "name_ref", node.id)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        # Bug 1B：call 已被父节点记录时（func 被压制），跳过对该 Attribute 的 attr_access 记录
        if id(node) in self._suppressed:
            self.generic_visit(node)
            return
        if node.attr in self.field_names:
            obj = ast.unparse(node.value)
            self._add(node, "attr_access", node.attr, obj)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        sl = node.slice
        if isinstance(sl, ast.Constant):
            if sl.value in self.field_names:
                obj = ast.unparse(node.value)
                self._add(node, "subscript_access", str(sl.value), obj)
            if isinstance(sl.value, str) and sl.value in self.string_values:
                self._add(node, "string_subscript", sl.value)
                self._suppressed.add(id(sl))   # Bug 2：防止 visit_Constant 再记 string_literal
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        # Bug 2：跳过已被 visit_Subscript / visit_Call 处理的 Constant 节点
        if id(node) in self._suppressed:
            self.generic_visit(node)
            return
        if isinstance(node.value, str) and node.value in self.string_values:
            self._add(node, "string_literal", node.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
            if name == "get" and node.args and isinstance(node.args[0], ast.Constant):
                val = node.args[0].value
                if val in self.field_names:
                    obj = ast.unparse(func.value)
                    self._add(node, "get_call", str(val), obj)
                if isinstance(val, str) and val in self.string_values:
                    self._add(node, "get_call_str", str(val))
                    self._suppressed.add(id(node.args[0]))  # Bug 2：防止 visit_Constant 再记 string_literal
        if name and (name in self.call_names or name in self.symbols):
            self._add(node, "call", name)
            self._suppressed.add(id(func))  # Bug 1：压制 func 节点，阻止 visit_Name/visit_Attribute 重复记录
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name in self.import_names or (
                alias.asname is not None and alias.asname in self.import_names
            ):
                self._add(node, "import", alias.name, alias.asname or "")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        mod = node.module or ""
        # Bug 5 修复：精确匹配或包名前缀匹配，不做子串匹配
        # "tools" 不再命中 "plogen_tools"，但仍命中 "tools" 和 "tools.utils"
        if any(mod == p or mod.startswith(p + ".") for p in self.import_names):
            self._add(node, "import_from", mod)
        for alias in node.names:
            if alias.name in self.import_names or alias.name in self.symbols:
                self._add(node, "import_symbol", alias.name, mod)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        # 压制注解内所有 Name 节点，防止 generic_visit → visit_Name 重复记录
        matched_ids: set[str] = set()
        for child in ast.walk(node.annotation):
            if isinstance(child, ast.Name):
                self._suppressed.add(id(child))
                if child.id in self.symbols and child.id not in matched_ids:
                    matched_ids.add(child.id)
                    self._add(node, "type_annotation", child.id, "ann_assign")
        # Bug 2：带注解赋值的 target（如 `x: int = 30` 中的 x）应记录为 assignment，
        # 而非让 generic_visit → visit_Name 误记为 name_ref
        if isinstance(node.target, ast.Name) and node.target.id in self.symbols:
            self._suppressed.add(id(node.target))
            self._add(node.target, "assignment", node.target.id)
        self.generic_visit(node)

    def _collect_assign_targets(self, target: ast.expr) -> None:
        """Bug 4：递归处理赋值目标，支持元组/列表解包，如 a, b = fn()。"""
        if isinstance(target, ast.Name):
            if target.id in self.symbols:
                self._suppressed.add(id(target))
                self._add(target, "assignment", target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for elt in target.elts:
                self._collect_assign_targets(elt)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._collect_assign_targets(target)
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
    except Exception:
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
    max_results: int = 500,
) -> dict[str, Any]:
    """递归分析整个项目的所有 .py 文件（A2：ThreadPoolExecutor 并发）。
    设计6：max_results 上限与 scan_patterns 对称，防止大项目打爆 context window。
    设计8：返回结构化 dict（替代旧的平铺 list + __truncated__ 哨兵）：
        {
          "total_found": 总命中数,
          "returned": 实际返回数,
          "truncated": 是否被 max_results 截断,
          "files": [{"file": 相对路径, "hits": [{line, kind, value, extra, function, confidence}]}]
        }
    """
    validate_project_path(project_path)   # 问题3：复用共享校验，消除与 scanner.py 的重复

    excl = set(exclude_dirs) if exclude_dirs is not None else _DEFAULT_EXCLUDE

    py_files: list[str] = []
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if d not in excl]
        for fname in files:
            if fname.endswith(".py"):
                py_files.append(os.path.join(root, fname))

    all_hits: list[dict] = []

    with ThreadPoolExecutor(max_workers=min(8, len(py_files) or 1)) as pool:
        futures = {
            pool.submit(
                analyze_file, fp,
                symbols, field_names, string_values, call_names, import_names,
            ): fp
            for fp in py_files
        }
        for future in as_completed(futures):
            try:
                all_hits.extend(future.result())
            except Exception as e:
                print(f"[field-impact-mcp] 跳过 {futures[future]}: {e}", file=sys.stderr)

    all_hits.sort(key=lambda h: (h["file"], h["line"]))

    total_found = len(all_hits)
    truncated = total_found > max_results
    if truncated:
        all_hits = all_hits[:max_results]

    # 设计8：按文件聚合 + 相对路径；col 对影响分析无用，不再输出，省 token
    files: list[dict] = []
    for hit in all_hits:
        rel = to_relative(hit["file"], project_path)
        if not files or files[-1]["file"] != rel:
            files.append({"file": rel, "hits": []})
        files[-1]["hits"].append({
            "line":       hit["line"],
            "kind":       hit["kind"],
            "value":      hit["value"],
            "extra":      hit["extra"],
            "function":   hit["function"],
            "confidence": hit["confidence"],
        })

    return {
        "total_found": total_found,
        "returned": len(all_hits),
        "truncated": truncated,
        "files": files,
    }


def trace_callers(
    project_path: str,
    function_name: str,
    exclude_dirs: list[str] | None = None,
) -> dict[str, Any]:
    """A3：找出所有直接调用 function_name 的函数和文件。返回结构与 analyze_project 相同。"""
    result = analyze_project(
        project_path=project_path,
        call_names=[function_name],
        exclude_dirs=exclude_dirs,
    )
    files = []
    for f in result["files"]:
        hits = [h for h in f["hits"] if h["kind"] == "call"]
        if hits:
            files.append({"file": f["file"], "hits": hits})
    n = sum(len(f["hits"]) for f in files)
    return {"total_found": n, "returned": n, "truncated": result["truncated"], "files": files}
