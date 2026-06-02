"""
将扫描结果聚合成结构化 Markdown 报告。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _relative(file_path: str, project_path: str) -> str:
    if file_path.startswith(project_path):
        return file_path[len(project_path):].lstrip("/\\")
    return file_path


def build_report(
    change_description: str,
    project_path: str,
    scan_results: list[dict[str, Any]],
    ast_results: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    lines.append(f"# 字段影响分析报告\n")
    lines.append(f"**变更描述**：{change_description}\n")
    lines.append(f"**项目路径**：`{project_path}`\n")
    lines.append(f"**扫描命中**：{len(scan_results)} 处（grep）｜{len(ast_results)} 处（AST）\n")
    lines.append("---\n")

    # ── AST 结果（精确，按文件分组）──
    if ast_results:
        lines.append("## Python AST 分析（精确）\n")
        by_file: dict[str, list] = defaultdict(list)
        for h in ast_results:
            by_file[h["file"]].append(h)

        for fpath, hits in sorted(by_file.items()):
            rel = _relative(fpath, project_path)
            lines.append(f"### `{rel}`\n")
            lines.append("| 行号 | 函数 | 访问方式 | 对象 | 字段 |")
            lines.append("|------|------|----------|------|------|")
            for h in hits:
                lines.append(
                    f"| {h['line']} | `{h['function']}` | {h['access_type']} "
                    f"| `{h['object']}` | `{h['field']}` |"
                )
            lines.append("")

    # ── Grep 结果（多语言，AST 未覆盖部分）──
    ast_keys = {(h["file"], h["line"]) for h in ast_results}
    extra_scan = [h for h in scan_results if (h["file"], h["line"]) not in ast_keys]

    if extra_scan:
        lines.append("## 跨语言扫描（TS/JS/其他）\n")
        by_file2: dict[str, list] = defaultdict(list)
        for h in extra_scan:
            by_file2[h["file"]].append(h)

        for fpath, hits in sorted(by_file2.items()):
            rel = _relative(fpath, project_path)
            lines.append(f"### `{rel}`\n")
            lines.append("| 行号 | 代码片段 |")
            lines.append("|------|----------|")
            for h in hits:
                code = h["code"].strip()[:120].replace("|", "｜")
                lines.append(f"| {h['line']} | `{code}` |")
            lines.append("")

    # ── 摘要统计 ──
    all_files = {h["file"] for h in scan_results} | {h["file"] for h in ast_results}
    lines.append("## 摘要\n")
    lines.append(f"- 受影响文件共 **{len(all_files)}** 个")
    lines.append(f"- AST 精确命中 **{len(ast_results)}** 处")
    lines.append(f"- Grep 额外命中 **{len(extra_scan)}** 处（TS/JS 等）")
    lines.append("")
    lines.append("> 以上结果为静态扫描，建议人工确认每处是否真正耦合到字段语义。")

    return "\n".join(lines)
