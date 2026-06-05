<div align="center">

# Ripple-MCP

**字段级语义变更影响分析 · Field-Level Semantic Change Impact Analysis**

[中文](#-中文) · [English](#-english)

</div>

---

## 🇨🇳 中文

### 为什么需要 Ripple-MCP？

当你想分析「修改 `machine.x/y` 语义」或「把某字段类型从 `INT` 改为 `VARCHAR`」会影响哪些代码时，传统工具无法回答：

| 问题 | 示例 |
|------|------|
| 哪些地方直接读取了这个字段？ | `obj.x` / `obj['x']` / `obj.get('x')` |
| 哪些地方用了这个字符串值？ | `"success"` / `"failed"` |
| 哪些地方调用了这个函数？ | `get_eq_partition()` |
| 哪些文件导入了这个模块？ | `from plogen_tools import ...` |
| TypeScript / JavaScript 里哪些地方用了这个变量？ | — |
| 改了函数 X，哪些函数直接调用了它？ | — |

**Ripple-MCP 把 Claude Code 的语义理解与 ripgrep / Python AST 的机械精确性结合，覆盖 codegraph 的所有盲区。**

---

### 核心工具

| 工具 | 说明 |
|------|------|
| `scan_patterns` | 通用正则扫描，支持任意语言 |
| `analyze_python_ast` | 精准 Python AST 分析，区分属性访问 / 下标 / `.get()` |
| `trace_callers` | 直接调用链追踪 |
| `generate_impact_report` | 语义变更影响的结构化 Markdown 报告 |
| `get_code_context` | 带上下文的代码片段提取 |

---

### 安装

**环境要求：** Python 3.10+

```bash
git clone https://github.com/0xYubo/Ripple-Mcp.git
cd Ripple-Mcp
pip install -e .
```

**Claude Code 集成（MCP 配置）：**

```bash
# 方式一：命令行一键添加（推荐，-s user 表示全局可用）
claude mcp add ripple -s user -- ripple-mcp
```

```json
// 方式二：手动编辑 MCP 配置文件
{
  "mcpServers": {
    "ripple": {
      "command": "ripple-mcp"
    }
  }
}
```

> `ripple-mcp` 是 `pip install -e .` 注册的命令行入口，等价于 `python -m field_impact_mcp`。

配置完成后重启 Claude Code 即可生效。

---

### 使用方式

无需手动调用任何工具——在 Claude Code 对话中**用自然语言描述变更意图**，Claude 会自动编排下面的工具完成分析。

**字段类型变更**
```
分析「把 all_check 表的 survey_status_today 字段从 INT 改为 VARCHAR」
对 /path/to/backend 的影响范围
```

**坐标语义变更**
```
如果把机台坐标 x/y 从左上角改为中心点，
/path/to/project 里哪些地方需要修改？
```

**函数重命名**
```
把 get_eq_partition 重命名为 get_machine_partition，
/path/to/backend 里有多少个调用点？
```

**API 路径变更**
```
/api/external/apiKey/refresh 改为 /api/external/api-keys，
哪些前端文件引用了旧路径？
```

**推荐工作流**（Claude 自动执行，也可手动指定）：

```
描述变更意图
  → scan_patterns + analyze_python_ast（并行扫描）
  → get_code_context（对可疑命中确认上下文）
  → generate_impact_report（生成结构化影响报告）
```

---

### MCP 工具参数说明

#### `scan_patterns` — 通用 pattern 扫描

接受任意正则表达式，支持所有语言和文件类型。

```json
{
  "project_path": "/path/to/project",
  "patterns": ["machine\\.x", "survey_status_today", "/api/external/"],
  "extensions": [".py", ".ts", ".tsx", ".sql"],
  "max_results": 500
}
```

返回（按文件聚合，`file` 为相对 `project_path` 的路径）：

```json
{
  "engine": "rg",
  "total_found": 12,
  "returned": 12,
  "truncated": false,
  "files": [{"file": "pkg/a.py", "hits": [{"line": 2, "code": "...", "patterns": ["..."], "confidence": "low"}]}]
}
```

`truncated: true` 时表示命中数超过 `max_results`，可增大后重试。
`analyze_python_ast` / `trace_callers` 返回相同的聚合结构（hits 内为 `{line, kind, value, extra, function, confidence}`）。

#### `analyze_python_ast` — Python AST 精确分析

比 grep 更精确，区分访问方式，标注所在函数。

```json
{
  "project_path": "/path/to/backend",
  "field_names":   ["x", "y", "survey_status_today"],
  "string_values": ["success", "failed"],
  "call_names":    ["get_eq_partition"],
  "import_names":  ["plogen_tools"]
}
```

`kind` 与置信度对应：

| kind | 说明 | confidence |
|---|---|---|
| `attr_access` | `obj.field` | high |
| `subscript_access` | `obj['field']` | high |
| `get_call` | `obj.get('field')` | high |
| `call` | 函数 / 方法调用 | medium |
| `import` / `import_from` | 导入 | medium |
| `type_annotation` | 类型注解 | low |

#### `trace_callers` — 调用链追踪

```json
{
  "project_path": "/path/to/backend",
  "function_name": "get_eq_partition"
}
```

#### `get_code_context` — 代码上下文

```json
{
  "file_path": "pkg/a.py",
  "line_number": 254,
  "context_lines": 8,
  "project_path": "/path/to/project"
}
```

`file_path` 可直接使用扫描结果中的相对路径（需同时传 `project_path`），也可传绝对路径。

#### `generate_impact_report` — 生成影响报告

先调用 `scan_patterns` / `analyze_python_ast`（结果自动缓存），再调用此工具只传 `change_description` 即可。

```json
{
  "change_description": "将 survey_status_today 字段从 INT 改为 VARCHAR(16)",
  "project_path": "/path/to/project"
}
```

---

### 与 codegraph 的关系

Ripple-MCP 不是 codegraph 的替代品，而是补充：

| 分析场景 | codegraph | Ripple-MCP |
|----------|:---------:|:----------:|
| 函数 / 类调用图 | ✅ | ✅ |
| 字段级读写追踪 | ❌ | ✅ |
| 字符串字面量匹配 | ❌ | ✅ |
| 枚举值引用追踪 | ❌ | ✅ |
| 类型注解分析 | ❌ | ✅ |
| 跨语言扫描（Python + TS/JS） | ❌ | ✅ |

---

## 🇺🇸 English

### Why Ripple-MCP?

When you want to analyze the impact of "changing `machine.x/y` semantics" or "converting a field type from `INT` to `VARCHAR`", traditional tools can't answer:

| Question | Example |
|----------|---------|
| Where is this field read directly? | `obj.x` / `obj['x']` / `obj.get('x')` |
| Where is this string value used? | `"success"` / `"failed"` |
| What functions call this function? | `get_eq_partition()` |
| Which files import this module? | `from plogen_tools import ...` |
| Where is this variable used in TypeScript / JavaScript? | — |
| If function X changes, which callers are affected? | — |

**Ripple-MCP combines Claude Code's semantic understanding with the mechanical precision of ripgrep / Python AST, covering all blind spots left by codegraph.**

---

### Core Tools

| Tool | Description |
|------|-------------|
| `scan_patterns` | Universal regex-based pattern matching across any language |
| `analyze_python_ast` | Precise Python AST analysis — distinguishes attribute access, subscript, and `.get()` |
| `trace_callers` | Direct function call chain tracking |
| `generate_impact_report` | Structured Markdown report of semantic change impact |
| `get_code_context` | Contextual code snippet retrieval with surrounding lines |

---

### Installation

**Requirements:** Python 3.10+

```bash
git clone https://github.com/0xYubo/Ripple-Mcp.git
cd Ripple-Mcp
pip install -e .
```

**Claude Code Integration:**

```bash
# Option 1: one-liner via CLI (recommended, -s user = available in all projects)
claude mcp add ripple -s user -- ripple-mcp
```

```json
// Option 2: edit the MCP config manually
{
  "mcpServers": {
    "ripple": {
      "command": "ripple-mcp"
    }
  }
}
```

> `ripple-mcp` is the console entry point registered by `pip install -e .`, equivalent to `python -m field_impact_mcp`.

Restart Claude Code after configuring.

---

### Usage

No manual tool calls needed — just **describe your change intent in natural language** inside Claude Code, and Claude orchestrates the tools below automatically.

**Field type change**
```
Analyze the impact of changing the survey_status_today column
of the all_check table from INT to VARCHAR on /path/to/backend
```

**Coordinate semantics change**
```
If machine coordinates x/y change from top-left to center,
which places in /path/to/project need updating?
```

**Function rename**
```
Rename get_eq_partition to get_machine_partition —
how many call sites exist in /path/to/backend?
```

**API path change**
```
/api/external/apiKey/refresh becomes /api/external/api-keys —
which frontend files reference the old path?
```

**Recommended workflow** (orchestrated by Claude automatically):

```
Describe the change intent
  → scan_patterns + analyze_python_ast  (parallel scan)
  → get_code_context                    (confirm suspicious hits)
  → generate_impact_report              (structured impact report)
```

---

### MCP Tool Reference

#### `scan_patterns` — universal pattern scan

Accepts any regex; works across all languages and file types.

```json
{
  "project_path": "/path/to/project",
  "patterns": ["machine\\.x", "survey_status_today", "/api/external/"],
  "extensions": [".py", ".ts", ".tsx", ".sql"],
  "max_results": 500
}
```

Returns (grouped by file; `file` is relative to `project_path`):

```json
{
  "engine": "rg",
  "total_found": 12,
  "returned": 12,
  "truncated": false,
  "files": [{"file": "pkg/a.py", "hits": [{"line": 2, "code": "...", "patterns": ["..."], "confidence": "low"}]}]
}
```

When `truncated: true`, hits exceeded `max_results` — retry with a larger value.
`analyze_python_ast` / `trace_callers` return the same grouped structure (hits contain `{line, kind, value, extra, function, confidence}`).

#### `analyze_python_ast` — precise Python AST analysis

More accurate than grep — distinguishes access kinds and annotates the enclosing function.

```json
{
  "project_path": "/path/to/backend",
  "field_names":   ["x", "y", "survey_status_today"],
  "string_values": ["success", "failed"],
  "call_names":    ["get_eq_partition"],
  "import_names":  ["plogen_tools"]
}
```

`kind` → confidence mapping:

| kind | Meaning | confidence |
|---|---|---|
| `attr_access` | `obj.field` | high |
| `subscript_access` | `obj['field']` | high |
| `get_call` | `obj.get('field')` | high |
| `call` | function / method call | medium |
| `import` / `import_from` | import | medium |
| `type_annotation` | type annotation | low |

#### `trace_callers` — call chain tracking

```json
{
  "project_path": "/path/to/backend",
  "function_name": "get_eq_partition"
}
```

#### `get_code_context` — code context

```json
{
  "file_path": "pkg/a.py",
  "line_number": 254,
  "context_lines": 8,
  "project_path": "/path/to/project"
}
```

`file_path` accepts the relative paths from scan results (pass `project_path` along), or an absolute path.

#### `generate_impact_report` — impact report

Call `scan_patterns` / `analyze_python_ast` first (results are cached server-side), then pass only `change_description`.

```json
{
  "change_description": "Change survey_status_today from INT to VARCHAR(16)",
  "project_path": "/path/to/project"
}
```

---

### Relationship with codegraph

Ripple-MCP is not a replacement for codegraph — it fills the gaps:

| Scenario | codegraph | Ripple-MCP |
|----------|:---------:|:----------:|
| Function / class call graph | ✅ | ✅ |
| Field-level read/write tracking | ❌ | ✅ |
| String literal matching | ❌ | ✅ |
| Enum value reference tracking | ❌ | ✅ |
| Type annotation analysis | ❌ | ✅ |
| Cross-language scan (Python + TS/JS) | ❌ | ✅ |

---

**License:** MIT
