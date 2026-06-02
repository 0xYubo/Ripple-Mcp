"""
通用代码扫描器 — 不假设任何结构，支持任意 pattern。
优先 ripgrep，降级到 grep。
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx"]
_DEFAULT_EXCLUDE = [
    "node_modules", ".venv", "venv", "__pycache__",
    ".git", "dist", "build", ".next", ".mypy_cache",
]


def _has_ripgrep() -> bool:
    try:
        subprocess.run(["rg", "--version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _rg_search(project_path: str, pattern: str, extensions: list[str], exclude: list[str]) -> list[dict]:
    ext_args = [arg for ext in extensions for arg in ["--glob", f"*{ext}"]]
    excl_args = [arg for d in exclude for arg in ["--glob", f"!{d}/**"]]
    cmd = ["rg", "--json", "--line-number", pattern] + ext_args + excl_args + [project_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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
    include_args = [f"--include=*{ext}" for ext in extensions]
    excl_args = [f"--exclude-dir={d}" for d in exclude]
    cmd = ["grep", "-rn", "-E", pattern] + include_args + excl_args + [project_path]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
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


def scan(
    project_path: str,
    patterns: list[str],
    extensions: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    核心扫描函数：接受任意正则 pattern 列表，返回所有命中位置。
    结果按 (file, line) 去重排序。
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
    """返回指定行前后 context_lines 行的代码。"""
    try:
        lines = Path(file_path).read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        snippet = []
        for i, l in enumerate(lines[start:end], start=start + 1):
            prefix = ">>>" if i == line_number else "   "
            snippet.append(f"{prefix} {i:4d} | {l}")
        return "\n".join(snippet)
    except Exception as e:
        return f"(无法读取: {e})"
