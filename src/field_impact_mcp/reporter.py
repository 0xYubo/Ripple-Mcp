"""
将扫描结果聚合成结构化 Markdown 报告。
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


def _relative(file_path: str, project_path: str) -> str:
    # Bug 6 修复：用 Path.relative_to() 替换 startswith，
    # 避免 "/foo" 错误命中 "/foobar/x.py"
    try:
        return str(Path(file_path).relative_to(project_path))
    except ValueError:
        return file_path


def build_report(
    change_description: str,
    project_path: str,
    scan_results: list[dict[str, Any]],
    ast_results: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append("# 字段影响分析报告\n")
    lines.append(f"**变更描述**：{change_description}\n")
    lines.append(f"**项目路径**：`{project_path}`\n")
    # 问题1：对 scan_results 和 ast_results 都排除 __truncated__ 哨兵再计数
    scan_count = sum(1 for h in scan_results if h.get("file") != "__truncated__")
    ast_count  = sum(1 for h in ast_results  if h.get("file") != "__truncated__")
    lines.append(f"**扫描命中**：{scan_count} 处（grep）｜{ast_count} 处（AST）\n")
    lines.append("---\n")

    # ── AST 结果（精确，按文件分组）──
    # 问题2：过滤哨兵，防止 __truncated__ 条目渲染成表格行
    real_ast = [h for h in ast_results if h.get("file") != "__truncated__"]
    if real_ast:
        lines.append("## Python AST 分析（精确）\n")
        by_file: dict[str, list] = defaultdict(list)
        for h in real_ast:
            by_file[h["file"]].append(h)

        for fpath, hits in sorted(by_file.items()):
            rel = _relative(fpath, project_path)
            lines.append(f"### `{rel}`\n")
            lines.append("| 行号 | 函数 | 访问方式 | 对象 | 字段 | 置信度 |")
            lines.append("|------|------|----------|------|------|--------|")
            for h in hits:
                # Bug 3：ast.unparse 对位运算会输出 a | b，需转义 | 防止破坏表格
                extra = h.get("extra", "").replace("|", "｜")
                value = h["value"].replace("|", "｜")
                lines.append(
                    f"| {h['line']} | `{h['function']}` | {h['kind']} "
                    f"| `{extra}` | `{value}` | {h.get('confidence', '-')} |"
                )
            lines.append("")

    # ── Grep 结果（多语言，AST 未覆盖部分）──
    ast_keys = {(h["file"], h["line"]) for h in ast_results}
    extra_scan = [
        h for h in scan_results
        if (h["file"], h["line"]) not in ast_keys and h.get("file") != "__truncated__"
    ]

    if extra_scan:
        lines.append("## Grep 扫描结果（非 AST 覆盖部分）\n")  # 设计7：改为中性标题，Python 文件也可能出现在此
        by_file2: dict[str, list] = defaultdict(list)
        for h in extra_scan:
            by_file2[h["file"]].append(h)

        for fpath, hits in sorted(by_file2.items()):
            rel = _relative(fpath, project_path)
            lines.append(f"### `{rel}`\n")
            lines.append("| 行号 | 命中 pattern | 代码片段 |")
            lines.append("|------|-------------|----------|")
            for h in hits:
                # Bug 3/4：转义 |（管道符）、\n（换行）和 `（反引号），防止 Markdown 表格错位
                code = (
                    h.get("code", "").strip()[:120]
                    .replace("|", "｜")
                    .replace("\n", " ").replace("\r", "")
                    .replace("`", "'")
                )
                pats = ", ".join(f"`{p}`" for p in h.get("patterns", []))
                lines.append(f"| {h['line']} | {pats} | `{code}` |")
            lines.append("")

    # 截断提示（问题2：同时检查 scan 和 ast 两侧的截断哨兵）
    # scan 哨兵用 "code" 字段，AST 哨兵用 "value" 字段，兼容两种
    for result_list in (scan_results, ast_results):
        sentinel = next((h for h in result_list if h.get("file") == "__truncated__"), None)
        if sentinel:
            msg = sentinel.get("value") or sentinel.get("code", "")
            lines.append(f"> ⚠️ {msg}\n")
            break

    # ── 摘要统计 ──
    all_files = {
        h["file"] for h in scan_results + ast_results
        if h.get("file") not in (None, "__truncated__")
    }
    lines.append("## 摘要\n")
    lines.append(f"- 受影响文件共 **{len(all_files)}** 个")
    lines.append(f"- AST 精确命中 **{ast_count}** 处")
    lines.append(f"- Grep 额外命中 **{len(extra_scan)}** 处")
    lines.append("")
    lines.append("> 以上结果为静态扫描，建议人工确认每处是否真正耦合到字段语义。")

    return "\n".join(lines)
