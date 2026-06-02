# field-impact-mcp

**字段级语义影响分析 MCP 工具**

codegraph 只能追踪函数调用链，无法回答「修改 `machine.x` 的语义会波及哪些地方」。
`field-impact-mcp` 在 codegraph 之上叠加字段级扫描，支持：

- **Python AST 精确分析**：区分 `obj.field` / `obj['field']` / `obj.get('field')`，标注所在函数
- **跨语言 grep 扫描**：TypeScript、JavaScript、Python 全覆盖
- **自动生成结构化报告**：按文件分组，标注行号、访问方式、所在函数

---

## 安装

```bash
# 推荐：通过 uvx 直接运行（无需手动安装）
uvx field-impact-mcp

# 或 pip 安装
pip install field-impact-mcp
```

## Claude Code 集成

在 `.claude/settings.json` 中添加：

```json
{
  "mcpServers": {
    "field-impact": {
      "command": "uvx",
      "args": ["field-impact-mcp"]
    }
  }
}
```

重启 Claude Code 后，Claude 会在以下情况自动调用该工具：
- 「分析修改 `x/y` 字段的影响范围」
- 「哪些地方用到了 `machine.x`」
- 「如果改变某个字段的语义，会影响哪些文件」

## Codex 集成

Codex 同样支持 MCP，配置方式相同，添加到对应的 settings 文件即可。

---

## 工具说明

### `scan_field_usages`

grep/ripgrep 扫描字段访问，支持多语言。

```
输入：project_path, field_names, object_names?, extensions?, exclude_dirs?
输出：[{file, line, code, pattern}]
```

### `analyze_python_ast`

Python AST 精确分析，区分访问方式，标注函数上下文。

```
输入：project_path, field_names, object_names?, exclude_dirs?
输出：[{file, line, function, access_type, object, field}]
```

### `get_code_context`

获取指定行前后的代码上下文。

```
输入：file_path, line_number, context_lines?
输出：带行号标注的代码片段
```

### `generate_impact_report`

将扫描结果聚合成 Markdown 报告。

```
输入：change_description, project_path, scan_results, ast_results
输出：Markdown 格式的影响分析报告
```

---

## 典型用法示例

在 Claude Code 中直接描述变更意图，Claude 会自动编排工具调用：

```
分析「将机台坐标 x/y 从左上角改为中心点」对 /path/to/project 的影响
```

Claude 会自动：
1. 提取字段名 `["x", "y"]` 和对象名 `["machine", "eq", "dataset_dict"]`
2. 调用 `scan_field_usages` 做跨语言扫描
3. 调用 `analyze_python_ast` 做 Python 精确分析
4. 调用 `generate_impact_report` 生成报告

---

## 开发

```bash
git clone https://github.com/your-org/field-impact-mcp
cd field-impact-mcp
pip install -e ".[dev]"
pytest tests/
```

## License

MIT
