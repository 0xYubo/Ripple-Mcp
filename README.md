# Ripple-MCP

**字段级语义变更影响分析 · MCP Server for Claude Code**

[![PyPI version](https://img.shields.io/pypi/v/ripple-mcp.svg)](https://pypi.org/project/ripple-mcp/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![MCP](https://img.shields.io/badge/MCP-compatible-green.svg)](https://modelcontextprotocol.io)

> 传统代码图谱只能追踪函数调用链。Ripple-MCP 在此之上叠加**字段级扫描**，让 Claude Code 能回答「改了这个字段，哪些代码会受影响」。

---

## 为什么需要这个工具？

当你想分析「修改 `machine.x/y` 语义」或「把某字段类型从 INT 改为 VARCHAR」会影响哪些代码时，传统工具无法回答：

- 哪些地方**直接读取了这个字段**？（`obj.x` / `obj['x']` / `obj.get('x')`）
- 哪些地方用了**这个字符串值**？（`"success"` / `"failed"`）
- 哪些地方**调用了这个函数**？（`get_eq_partition()`）
- 哪些文件**导入了这个模块**？（`from plogen_tools import ...`）
- TypeScript / JavaScript 里哪些地方用了这个变量？
- 改了函数 X，**哪些函数直接调用了它**？

Ripple-MCP 把 Claude Code 的语义理解与 ripgrep / Python AST 的机械精确性结合，覆盖 codegraph 的所有盲区。

---

## 快速开始

### 方式一：uvx（推荐，零安装）

```bash
claude mcp add ripple -s user -- uvx ripple-mcp
```

### 方式二：从源码安装

```bash
git clone https://github.com/ybmyb/Ripple-Mcp.git
cd Ripple-Mcp
pip install -e .
claude mcp add ripple -s user \
  -e PYTHONPATH=/path/to/Ripple-Mcp/src \
  -- python3 -m field_impact_mcp
```

> `-s user` 表示全局配置，所有项目打开 Claude Code 均可使用。

安装后重启 Claude Code，在对话中直接描述变更意图即可，**无需手动调用工具**。

---

## 使用示例

在 Claude Code 中直接用自然语言描述，Claude 自动编排工具：

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

---

## 支持的分析场景

| 场景 | 示例 |
|---|---|
| 字段 / 属性访问 | `obj.x` / `obj['x']` / `obj.get('x')` |
| 字符串字面量 | `"success"` / `"X-API-Key"` / `"/api/external/"` |
| 常量 / 枚举值 | `DEFAULT_TTL = 30` / `STATUS_OK` |
| 函数 / 方法调用 | `get_eq_partition(...)` |
| 导入关系 | `from plogen_tools import ...` |
| 类型注解 | `def fn(x: float) -> MyClass` / `x: Optional[T]` |
| 调用链追踪 | 哪些函数直接调用了 `get_eq_partition`？ |
| 自定义 pattern | 任意正则，支持 SQL / YAML / JSON 等任意文件 |
| 跨语言扫描 | Python / TypeScript / JavaScript / 任意文本 |

---

## 工作原理

```
用户描述变更意图（自然语言）
          ↓
    Claude Code 理解变更，自动决定搜索策略
          ↓
  ┌──────────────────────────────────────────┐
  │  scan_patterns       ripgrep/grep 任意正则 │
  │  analyze_python_ast  Python AST 精确分析   │
  │  trace_callers       直接调用链追踪        │
  │  get_code_context    上下文辅助判断        │
  └──────────────────────────────────────────┘
          ↓
    generate_impact_report → 结构化 Markdown 报告
```

---

## MCP 工具说明

### `scan_patterns` — 通用 pattern 扫描

接受任意正则表达式，支持所有语言和文件类型。

```json
{
  "project_path": "/path/to/project",
  "patterns": ["machine\\.x", "survey_status_today", "/api/external/"],
  "extensions": [".py", ".ts", ".tsx", ".sql"],
  "max_results": 2000
}
```

返回：`[{file, line, code, patterns, confidence}]`

---

### `analyze_python_ast` — Python AST 精确分析

比 grep 更精确，区分访问方式，标注所在函数，支持六类搜索目标。

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

---

### `trace_callers` — 调用链追踪

找出项目中所有直接调用指定函数的函数和文件。

```json
{
  "project_path": "/path/to/backend",
  "function_name": "get_eq_partition"
}
```

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

### `generate_impact_report` — 生成影响报告

**推荐工作流**：先调用 `scan_patterns` / `analyze_python_ast`（结果自动缓存），再调用此工具只传 `change_description` 即可。

```json
{
  "change_description": "将 survey_status_today 字段从 INT 改为 VARCHAR(16)",
  "project_path": "/path/to/project"
}
```

---

## 与 codegraph 对比

| 能力 | codegraph | Ripple-MCP |
|---|---|---|
| 函数调用链 | ✅ 精确 | ✅ `trace_callers` |
| 字段级访问分析 | ❌ | ✅ |
| 字符串字面量搜索 | ❌ | ✅ |
| 常量 / 枚举引用 | ❌ | ✅ |
| 类型注解分析 | ❌ | ✅ |
| 跨语言搜索 | ❌ | ✅ |
| 语义变更影响分析 | ❌ | ✅（配合 Claude） |

**推荐组合**：codegraph 做调用链，Ripple-MCP 做字段级语义影响分析，两者互补。

---

## 依赖

- Python 3.10+
- `mcp >= 1.0.0, < 2.0.0`
- `anyio >= 4.0.0, < 5.0.0`
- （可选）`ripgrep`：扫描更快，自动降级到系统 `grep`

## 开发

```bash
git clone https://github.com/ybmyb/Ripple-Mcp.git
cd Ripple-Mcp
pip install -e .
pytest tests/ -v
```

---

## License

MIT © [ybmyb](https://github.com/ybmyb)
