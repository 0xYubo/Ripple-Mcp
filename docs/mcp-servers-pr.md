# PR 内容草稿 — modelcontextprotocol/servers

> 提交地址：https://github.com/modelcontextprotocol/servers
> 目标文件：README.md 的 Community Servers 列表

---

## PR 标题

```
Add Ripple-MCP: field-level semantic impact analysis server
```

## PR 描述

```markdown
## Summary

Adds **Ripple-MCP** to the community servers list.

Ripple-MCP is a field-level semantic impact analysis MCP server for Claude Code.
It answers the question: *"If I change this field/function/config, which parts of the codebase will be affected?"*

## What it does

Traditional code graph tools (like codegraph) only trace function call chains.
Ripple-MCP adds **field-level scanning** on top, covering blind spots that call graphs miss:

- Which files read `obj.field` / `obj['field']` / `obj.get('field')`?
- Which files use a specific string literal like `"success"` or `"/api/v1/users"`?
- Which files import a specific module?
- Which functions directly call a specific function?

## Tools provided

| Tool | Description |
|---|---|
| `scan_patterns` | Regex search across any language/file type |
| `analyze_python_ast` | AST-level precise analysis for Python (distinguishes access patterns, annotates confidence) |
| `trace_callers` | Find all direct callers of a function |
| `get_code_context` | Fetch surrounding lines for a hit to confirm real coupling |
| `generate_impact_report` | Aggregate scan results into structured Markdown report |

## Installation

Source install (PyPI release coming soon):

\`\`\`bash
git clone https://github.com/ybmyb/Ripple-Mcp.git
pip install -e Ripple-Mcp
claude mcp add ripple -s user \
  -e PYTHONPATH=/path/to/Ripple-Mcp/src \
  -- python3 -m field_impact_mcp
\`\`\`

## Links

- GitHub: https://github.com/ybmyb/Ripple-Mcp
- License: MIT
- Python 3.10+
```

---

## 需要插入到 README.md 的内容

在 `Community Servers` 列表中，按字母顺序找到 R 的位置，插入：

```markdown
- **[Ripple-MCP](https://github.com/ybmyb/Ripple-Mcp)** - Field-level semantic impact analysis. Answers "if I change this field/function, what breaks?" across Python/TypeScript/JavaScript codebases. Tools: scan_patterns, analyze_python_ast, trace_callers, generate_impact_report.
```

---

## 提交步骤

```bash
# 1. Fork modelcontextprotocol/servers 到自己账号
# 2. 克隆 fork
git clone https://github.com/<你的用户名>/servers.git
cd servers

# 3. 新建分支
git checkout -b add-ripple-mcp

# 4. 编辑 README.md，在 Community Servers 部分按字母序插入上方内容

# 5. 提交
git add README.md
git commit -m "Add Ripple-MCP: field-level semantic impact analysis server"

# 6. 推送并开 PR
git push -u origin add-ripple-mcp
# 然后在 GitHub 上打开 PR，粘贴上方 PR 描述
```
