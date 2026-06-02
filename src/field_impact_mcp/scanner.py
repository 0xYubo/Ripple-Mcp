"""
字段访问扫描器：支持 Python / TypeScript / JavaScript
优先使用 ripgrep（rg），降级到 grep。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx"]
_DEFAULT_EXCLUDE = ["node_modules", ".venv", "venv", "__pycache__", ".git", "dist", "build", ".next"]


def _has_ripgrep() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _rg_search(project_path: str, pattern: str, extensions: list[str], exclude: list[str]) -> list[dict]:
    ext_args = []
    for ext in extensions:
        ext_args += ["--glob", f"*{ext}"]
    excl_args = []
    for d in exclude:
        excl_args += ["--glob", f"!{d}/**"]

    cmd = ["rg", "--json", "--line-number", pattern] + ext_args + excl_args + [project_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return []

    hits = []
    for line in result.stdout.splitlines():
        try:
            obj = json.loads(line)
            if obj.get("type") == "match":
                data = obj["data"]
                hits.append({
                    "file": data["path"]["text"],
                    "line": data["line_number"],
                    "code": data["lines"]["text"].rstrip("\n"),
                    "pattern": pattern,
                })
        except (json.JSONDecodeError, KeyError):
            continue
    return hits


def _grep_search(project_path: str, pattern: str, extensions: list[str], exclude: list[str]) -> list[dict]:
    include_args = ["--include=" + f"*{ext}" for ext in extensions]
    excl_args = ["--exclude-dir=" + d for d in exclude]
    cmd = ["grep", "-rn", "-E", pattern] + include_args + excl_args + [project_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        return []

    hits = []
    for line in result.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        try:
            hits.append({
                "file": parts[0],
                "line": int(parts[1]),
                "code": parts[2].strip(),
                "pattern": pattern,
            })
        except ValueError:
            continue
    return hits


def build_patterns(field_names: list[str], object_names: list[str]) -> list[str]:
    """
    根据字段名和对象名生成多语言匹配模式。

    例如 field_names=["x","y"], object_names=["machine","eq"] 生成：
      machine\.x, machine\['x'\], machine\.get\('x'\), eq\.x, ...
    """
    patterns: list[str] = []
    escaped_fields = [re.escape(f) for f in field_names]
    field_alt = "|".join(escaped_fields)

    for obj in object_names:
        eo = re.escape(obj)
        # obj.field  (Python / JS)
        patterns.append(rf"{eo}\.({field_alt})\b")
        # obj['field'] or obj["field"]
        patterns.append(rf"""{eo}\[['"]({field_alt})['"]\]""")
        # obj.get('field') or obj.get("field")
        patterns.append(rf"""{eo}\.get\(['"]({field_alt})['"]""")

    # 裸变量名（如 eq_x, machine_x, center_x）
    for f in field_names:
        patterns.append(rf"\b\w+_{re.escape(f)}\b")
        patterns.append(rf"\b{re.escape(f)}_\w+\b")

    # Shapely Point(x, y) / Point(center_x, center_y)
    if set(field_names) & {"x", "y"}:
        patterns.append(r"Point\(.*\b[xy]\b")

    return list(dict.fromkeys(patterns))  # 去重保序


def scan(
    project_path: str,
    patterns: list[str],
    extensions: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    扫描项目中所有匹配 patterns 的代码位置。
    返回 [{file, line, code, pattern}]，按文件路径排序，去重。
    """
    exts = extensions or _DEFAULT_EXTENSIONS
    excl = exclude_dirs or _DEFAULT_EXCLUDE
    use_rg = _has_ripgrep()
    searcher = _rg_search if use_rg else _grep_search

    seen: set[tuple] = set()
    results: list[dict] = []

    for pat in patterns:
        for hit in searcher(project_path, pat, exts, excl):
            key = (hit["file"], hit["line"])
            if key not in seen:
                seen.add(key)
                results.append(hit)

    results.sort(key=lambda h: (h["file"], h["line"]))
    return results


def get_context(file_path: str, line_number: int, context_lines: int = 6) -> str:
    """返回指定行号前后 context_lines 行的代码上下文。"""
    try:
        path = Path(file_path)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        snippet = []
        for i, l in enumerate(lines[start:end], start=start + 1):
            prefix = ">>>" if i == line_number else "   "
            snippet.append(f"{prefix} {i:4d} | {l}")
        return "\n".join(snippet)
    except Exception as e:
        return f"(无法读取文件: {e})"
