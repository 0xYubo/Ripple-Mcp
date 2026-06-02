# field-impact-mcp

**超越调用链的代码影响分析 MCP 工具**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

---

## 为什么需要这个工具？

当你想分析「修改 `machine.x/y` 语义」或「把某个字段类型从 INT 改为 VARCHAR」会影响哪些代码时，传统的代码图谱工具（如 codegraph）只能追踪**函数调用链**，无法回答：

- 哪些地方**直接读取了这个字段**？（`obj.x` / `obj['x']` / `obj.get('x')`）
- 哪些地方用了**这个字符串值**？（`"success"` / `"failed"`）
- 哪些地方**调用了这个函数**？（`get_eq_partition()`）
- 哪些文件**导入了这个模块**？（`from plogen_tools import ...`）
- 哪些地方有**这个类型注解**？（`def fn(x: float) -> MyClass`）
- TypeScript/JavaScript 里哪些地方用了这个变量？

`field-impact-mcp` 在调用链之上叠加**字段级扫描**，把 Claude Code 的语义理解能力与 ripgrep/AST 的机械精确性结合起来，覆盖 codegraph 做不到的所有盲区。

---

## 支持的分析场景

| 场景 | 示例 |
|---|---|
| 字段/属性访问 | `machine.x` / `machine['x']` / `dataset.get('x')` |
| 字符串字面量 | `"success"` / `"X-API-Key"` / `"/api/external/"` |
| 常量 / 枚举值 | `DEFAULT_TTL = 30` / `STATUS_OK` |
| 函数/方法调用 | `get_eq_partition(...)` / `match_pos_count(...)` |
| 导入关系 | `from plogen_tools import ...` |
| 类型注解（参数 + 返回值） | `def fn(x: float) -> MyClass` |
| 任意自定义 pattern | 任何正则表达式，支持 SQL / YAML / JSON 等任意文件 |
| 跨语言扫描 | Python / TypeScript / JavaScript / 任意文本文件 |

---

## 工作原理

```
用户描述变更意图（自然语言）
          ↓
    Claude Code 理解变更，自动决定搜索策略
          ↓
  ┌──────────────────────────────────────┐
  │  Layer 1: scan_patterns              │  ← ripgrep/grep 任意正则
  │  Layer 2: analyze_python_ast         │  ← Python AST 精确分析
  │  Layer 3: get_code_context           │  ← 上下文辅助判断
  └──────────────────────────────────────┘
          ↓
    generate_impact_report → 结构化 Markdown 报告
```

**用户无需关心工具细节**，只需描述变更意图，Claude Code 自动编排调用策略。

---

## 安装

### 方式一：uvx（推荐，无需手动安装）

```bash
# 添加到 Claude Code 用户全局（所有项目可用）
claude mcp add field-impact -s user -- uvx field-impact-mcp
```

> 发布 PyPI 后即可使用此方式。

### 方式二：本地开发安装

```bash
git clone https://github.com/ybmyb/field-impact-mcp.git
cd field-impact-mcp
pip install -e .

# 添加到 Claude Code
claude mcp add field-impact -s user -- python3 -m field_impact_mcp \
  --env PYTHONPATH=/path/to/field-impact-mcp/src
```

---

## Claude Code / Codex 集成

安装后重启 Claude Code，工具即可**自动调用**，无需手动触发。

Claude 会在以下情况自动使用此工具：
- 「分析修改 `xxx` 字段会影响哪些地方」
- 「如果把 `survey_status_today` 从 INT 改为 VARCHAR，哪些文件需要修改？」
- 「`get_eq_partition` 这个函数被哪些地方使用了？」
- 「哪些文件导入了 `plogen_tools`？」
- 「把状态值从字符串改为枚举，影响范围是什么？」

---

## MCP 工具说明

### `scan_patterns` — 通用 pattern 扫描

接受任意正则表达式，支持所有语言和文件类型。

```json
{
  "project_path": "/path/to/project",
  "patterns": [
    "machine\\.x",
    "machine\\['x'\\]",
    "dataset\\.get\\('x'",
    "survey_status_today",
    "\"success\"",
    "/api/external/"
  ],
  "extensions": [".py", ".ts", ".tsx", ".sql"],
  "exclude_dirs": ["node_modules", ".venv"]
}
```

返回：`[{file, line, code, pattern}]`

---

### `analyze_python_ast` — Python AST 精确分析

比 grep 更精确：区分访问方式，标注所在函数，支持六类搜索目标，可同时指定。

```json
{
  "project_path": "/path/to/backend",
  "field_names":   ["x", "y", "survey_status_today"],
  "string_values": ["success", "failed", "X-API-Key"],
  "symbols":       ["DEFAULT_TTL", "AllCheck", "ExternalApiClient"],
  "call_names":    ["get_eq_partition", "match_pos_count"],
  "import_names":  ["plogen_tools", "api_key_service"],
  "exclude_dirs":  [".venv", "__pycache__"]
}
```

返回：`[{file, line, function, kind, value, extra}]`

`kind` 可能值：

| kind | 说明 |
|---|---|
| `attr_access` | `obj.field` |
| `subscript_access` | `obj['field']` |
| `get_call` | `obj.get('field')` |
| `string_literal` | 字符串常量值 |
| `call` | 函数/方法调用 |
| `import` / `import_from` / `import_symbol` | 导入 |
| `name_ref` | 标识符引用 |
| `assignment` | 赋值目标 |
| `type_annotation` | 类型注解（参数 / 返回值 / 变量） |
| `function_def` / `class_def` | 定义 |

---

### `get_code_context` — 代码上下文

获取命中行前后的代码，辅助判断是否真正耦合。

```json
{
  "file_path": "/path/to/file.py",
  "line_number": 254,
  "context_lines": 8
}
```

---

### `generate_impact_report` — 生成报告

将所有扫描结果聚合成结构化 Markdown 影响报告。

```json
{
  "change_description": "将 survey_status_today 字段从 INT 改为 VARCHAR(16)",
  "project_path": "/path/to/project",
  "scan_results": [...],
  "ast_results": [...]
}
```

---

## 典型使用示例

在 Claude Code 中直接描述变更意图，Claude 会自动编排工具：

**示例 1：字段类型变更**
```
分析「把 all_check 表的 survey_status_today 字段从 INT 改为 VARCHAR」
对 /path/to/backend 的影响范围
```

**示例 2：坐标语义变更**
```
如果把机台坐标 x/y 从左上角改为中心点，
/path/to/project 里哪些地方需要修改？
```

**示例 3：API 路径变更**
```
/api/external/apiKey/refresh 改为 /api/external/api-keys，
哪些前端文件引用了旧路径？
```

**示例 4：函数重命名**
```
把 get_eq_partition 重命名为 get_machine_partition，
/path/to/backend 里有多少个调用点？
```

---

## 开发

```bash
git clone https://github.com/ybmyb/field-impact-mcp.git
cd field-impact-mcp
pip install -e .
pytest tests/ -v
```

### 依赖

- Python 3.10+
- `mcp >= 1.0.0`
- `anyio >= 4.0.0`
- （可选）`ripgrep`：扫描更快，降级到系统 `grep`

---

## 与 codegraph 对比

| 能力 | codegraph | field-impact-mcp |
|---|---|---|
| 函数调用链 | ✅ 精确 | ✅ 通过 call_names |
| 字段级访问分析 | ❌ | ✅ |
| 字符串字面量搜索 | ❌ | ✅ |
| 常量/枚举引用 | ❌ | ✅ |
| 类型注解分析 | ❌ | ✅ |
| 跨语言搜索 | ❌ | ✅ |
| 语义变更影响分析 | ❌ | ✅（配合 Claude） |

**推荐组合使用**：codegraph 做调用链，field-impact-mcp 做字段级语义影响分析，两者互补。

---

## License

MIT © [ybmyb](https://github.com/ybmyb)
