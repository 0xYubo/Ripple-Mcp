"""
将扫描结果聚合成结构化 Markdown 报告。
设计8：消费 scan/analyze_project 的结构化返回（{total_found, truncated, files}），
       不再有 __truncated__ 哨兵；兼容旧平铺 list 输入（Claude 手工构造参数时）。
"""
from __future__ import annotations

from typing import Any

from ._utils import to_relative


def _normalize(results: Any, project_path: str) -> dict[str, Any]:
    """把输入统一成 {total_found, truncated, files} 结构。
    - 新格式 dict：原样返回
    - 旧平铺 list：按文件分组（过滤遗留 __truncated__ 哨兵）
    - None / 空：空结构
    """
    if isinstance(results, dict) and "files" in results:
        return results
    empty = {"total_found": 0, "returned": 0, "truncated": False, "files": []}
    if not results:
        return empty
    if isinstance(results, list):
        truncated = any(h.get("file") == "__truncated__" for h in results)
        flat = sorted(
            (h for h in results if h.get("file") != "__truncated__"),
            key=lambda h: (h.get("file", ""), h.get("line", 0)),
        )
        files: list[dict] = []
        for h in flat:
            rel = to_relative(h.get("file", ""), project_path)
            if not files or files[-1]["file"] != rel:
                files.append({"file": rel, "hits": []})
            files[-1]["hits"].append(h)
        return {"total_found": len(flat), "returned": len(flat), "truncated": truncated, "files": files}
    return empty


def _md_escape(text: str) -> str:
    """Bug 3/4：转义 |、换行和反引号，防止 Markdown 表格错位。"""
    return (
        text.replace("|", "｜")
        .replace("\n", " ").replace("\r", "")
        .replace("`", "'")
    )


def build_report(
    change_description: str,
    project_path: str,
    scan_results: Any,
    ast_results: Any,
) -> str:
    scan = _normalize(scan_results, project_path)
    ast = _normalize(ast_results, project_path)

    lines: list[str] = []
    lines.append("# 字段影响分析报告\n")
    lines.append(f"**变更描述**：{change_description}\n")
    lines.append(f"**项目路径**：`{project_path}`\n")
    lines.append(f"**扫描命中**：{scan['total_found']} 处（grep）｜{ast['total_found']} 处（AST）\n")
    lines.append("---\n")

    # ── AST 结果（精确，按文件分组）──
    if ast["files"]:
        lines.append("## Python AST 分析（精确）\n")
        for f in ast["files"]:
            lines.append(f"### `{f['file']}`\n")
            lines.append("| 行号 | 函数 | 访问方式 | 对象 | 字段 | 置信度 |")
            lines.append("|------|------|----------|------|------|--------|")
            for h in f["hits"]:
                # Bug 3：ast.unparse 对位运算会输出 a | b，需转义 | 防止破坏表格
                extra = _md_escape(h.get("extra", ""))
                value = _md_escape(h.get("value", ""))
                lines.append(
                    f"| {h['line']} | `{h.get('function', '')}` | {h.get('kind', '')} "
                    f"| `{extra}` | `{value}` | {h.get('confidence', '-')} |"
                )
            lines.append("")

    # ── Grep 结果（多语言，AST 未覆盖部分）──
    ast_keys = {(f["file"], h["line"]) for f in ast["files"] for h in f["hits"]}
    extra_count = 0
    grep_sections: list[str] = []
    for f in scan["files"]:
        hits = [h for h in f["hits"] if (f["file"], h["line"]) not in ast_keys]
        if not hits:
            continue
        extra_count += len(hits)
        grep_sections.append(f"### `{f['file']}`\n")
        grep_sections.append("| 行号 | 命中 pattern | 代码片段 |")
        grep_sections.append("|------|-------------|----------|")
        for h in hits:
            code = _md_escape(h.get("code", "").strip()[:120])
            pats = ", ".join(f"`{p}`" for p in h.get("patterns", []))
            grep_sections.append(f"| {h['line']} | {pats} | `{code}` |")
        grep_sections.append("")

    if grep_sections:
        lines.append("## Grep 扫描结果（非 AST 覆盖部分）\n")  # 设计7：中性标题，Python 文件也可能出现在此
        lines.extend(grep_sections)

    # ── 截断提示 ──
    for label, r in (("grep", scan), ("AST", ast)):
        if r["truncated"]:
            lines.append(
                f"> ⚠️ {label} 结果已截断（共 {r['total_found']} 处，仅显示前 {r['returned']} 条）。"
                f"请缩小搜索范围或增大 max_results。\n"
            )

    # ── 摘要统计 ──
    all_files = {f["file"] for f in scan["files"]} | {f["file"] for f in ast["files"]}
    lines.append("## 摘要\n")
    lines.append(f"- 受影响文件共 **{len(all_files)}** 个")
    lines.append(f"- AST 精确命中 **{ast['total_found']}** 处")
    lines.append(f"- Grep 额外命中 **{extra_count}** 处")
    lines.append("")
    lines.append("> 以上结果为静态扫描，建议人工确认每处是否真正耦合到字段语义。")

    return "\n".join(lines)
