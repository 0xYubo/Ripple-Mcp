"""
通用代码扫描器 — 不假设任何结构，支持任意 pattern。
优先 ripgrep，降级到 grep。
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from ._utils import to_relative, validate_project_path

_DEFAULT_EXTENSIONS = [".py", ".ts", ".tsx", ".js", ".jsx"]
_DEFAULT_EXCLUDE = [
    "node_modules", ".venv", "venv", "__pycache__",
    ".git", "dist", "build", ".next", ".mypy_cache",
]
# 设计8：默认上限从 2000 降到 500，防止单次调用打爆 context window；需要更多时显式传 max_results
_MAX_RESULTS_DEFAULT = 500

# B5：模块级缓存，避免每次 scan() 都 fork 进程
_USE_RG: bool | None = None


def _has_ripgrep() -> bool:
    global _USE_RG
    if _USE_RG is None:
        try:
            subprocess.run(["rg", "--version"], capture_output=True, timeout=3)
            _USE_RG = True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            _USE_RG = False
    return _USE_RG




def _validate_patterns(patterns: list[str]) -> None:
    """B7：正则预检，防止无效 pattern"""
    for pat in patterns:
        try:
            re.compile(pat)
        except re.error as e:
            raise ValueError(f"无效正则表达式 {pat!r}: {e}") from e


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
                    "confidence": "low",
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
                "confidence": "low",
            })
        except ValueError:
            continue
    return hits


def scan(
    project_path: str,
    patterns: list[str],
    extensions: list[str] | None = None,
    exclude_dirs: list[str] | None = None,
    max_results: int = _MAX_RESULTS_DEFAULT,
) -> dict[str, Any]:
    """
    核心扫描函数：接受任意正则 pattern 列表，返回所有命中位置。
    B3：同一行匹配多个 pattern 时，合并到 patterns 列表而非丢弃。
    设计8：返回结构化 dict（替代旧的平铺 list + __truncated__ 哨兵）：
        {
          "engine": "rg" | "grep",
          "total_found": 总命中数,
          "returned": 实际返回数,
          "truncated": 是否被 max_results 截断,
          "files": [{"file": 相对路径, "hits": [{line, code, patterns, confidence}]}]
        }
    """
    validate_project_path(project_path)
    _validate_patterns(patterns)

    exts = extensions if extensions is not None else _DEFAULT_EXTENSIONS
    excl = exclude_dirs if exclude_dirs is not None else _DEFAULT_EXCLUDE
    use_rg = _has_ripgrep()
    searcher = _rg_search if use_rg else _grep_search

    # B3：key → hit，同一行多个 pattern 合并到 patterns 列表
    seen: dict[tuple, dict] = {}
    for pat in patterns:
        for hit in searcher(project_path, pat, exts, excl):
            key = (hit["file"], hit["line"])
            if key not in seen:
                entry = {**hit, "patterns": [hit["pattern"]]}
                del entry["pattern"]
                seen[key] = entry
            else:
                if pat not in seen[key]["patterns"]:
                    seen[key]["patterns"].append(pat)

    flat = sorted(seen.values(), key=lambda h: (h["file"], h["line"]))
    total_found = len(flat)
    truncated = total_found > max_results
    if truncated:
        flat = flat[:max_results]

    # 设计8：按文件聚合 + 相对路径，文件名只出现一次，省 token
    files: list[dict] = []
    for hit in flat:
        rel = to_relative(hit["file"], project_path)
        if not files or files[-1]["file"] != rel:
            files.append({"file": rel, "hits": []})
        files[-1]["hits"].append({
            "line": hit["line"],
            "code": hit["code"],
            "patterns": hit["patterns"],
            "confidence": hit["confidence"],
        })

    return {
        "engine": "rg" if use_rg else "grep",
        "total_found": total_found,
        "returned": len(flat),
        "truncated": truncated,
        "files": files,
    }


def get_context(
    file_path: str,
    line_number: int,
    context_lines: int = 6,
    project_path: str | None = None,
) -> str:
    """返回指定行前后 context_lines 行的代码。
    设计8：扫描结果改为相对路径后，支持传 project_path 解析相对 file_path。
    """
    if line_number < 1:
        return f"(行号必须 >= 1，收到: {line_number})"
    path = Path(file_path)
    if not path.is_absolute() and project_path:
        path = Path(project_path) / path
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if line_number > len(lines):
            return f"(行号 {line_number} 超出文件范围，文件共 {len(lines)} 行)"
        start = max(0, line_number - context_lines - 1)
        end = min(len(lines), line_number + context_lines)
        snippet = []
        for i, ln in enumerate(lines[start:end], start=start + 1):
            prefix = ">>>" if i == line_number else "   "
            snippet.append(f"{prefix} {i:4d} | {ln}")
        return "\n".join(snippet)
    except Exception as e:
        return f"(无法读取: {e})"
