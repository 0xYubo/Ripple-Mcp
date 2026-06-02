# Ripple-Mcp

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
- TypeScript / JavaScript 里哪些地方用了这个变量？
- 改了函数 X，**哪些函数直接调用了它**？

`Ripple-Mcp` 在调用链之上叠加**字段级扫描**，把 Claude Code 的语义理解能力与 ripgrep / AST 的机械精确性结合起来，覆盖 codegraph 做不到的所有盲区。

---

## 支持的分析场景

| 场景 | 示例 |
|---|---|
| 字段 / 属性访问 | `machine.x` / `machine['x']` / `dataset.get('x')` |
| 字符串字面量 | `"success"` / `"X-API-Key"` / `"/api/external/"` |
| 常量 / 枚举值 | `DEFAULT_TTL = 30` / `STATUS_OK` |
| 函数 / 方法调用 | `get_eq_partition(...)` / `match_pos_count(...)` |
| 导入关系 | `from plogen_tools import ...` |
| 类型注解（参数 + 返回值 + 变量） | `def fn(x: float) -> MyClass` / `x: Optional[T]` |
| 调用链追踪 | 哪些函数直接调用了 `get_eq_partition`？ |
| 任意自定义 pattern | 任何正则表达式，支持 SQL / YAML / JSON 等任意文件 |
| 跨语言扫描 | Python / TypeScript / JavaScript / 任意文本文件 |

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
    （自动读取服务端缓存，无需重新传递扫描结果）
```

**用户无需关心工具细节**，只需描述变更意图，Claude Code 自动编排调用策略。

---

## 安装

### 方式一：uvx（推荐，需已安装 uv）

```bash
claude mcp add ripple -s user -- uvx ripple-mcp
```

### 方式二：从源码安装（当前推荐）

```bash
# 1. 克隆仓库
git clone https://github.com/ybmyb/Ripple-Mcp.git
cd Ripple-Mcp

# 2. 安装依赖
pip install -e .

# 3. 添加到 Claude Code 用户全局（所有项目可用）
claude mcp add ripple -s user \
  -e PYTHONPATH=/path/to/Ripple-Mcp/src \
  -- python3 -m field_impact_mcp
```

> `-s user` 表示用户全局配置，**不限于某个项目**，任何项目打开 Claude Code 均可使用。

---

## MCP 工具说明

### `scan_patterns` — 通用 pattern 扫描

接受任意正则表达式，支持所有语言和文件类型。同一行命中多个 pattern 时，自动合并到 `patterns` 列表。

```json
{
  "project_path": "/path/to/project",
  "patterns": [
    "machine\\.x",
    "machine\\['x'\\]",
    "survey_status_today",
    "/api/external/"
  ],
  "extensions": [".py", ".ts", ".tsx", ".sql"],
  "max_results": 2000
}
```

返回：`[{file, line, code, patterns, confidence}]`

- `patterns`：该行命中的所有 pattern 列表（不再因去重而丢失）
- `confidence`：始终为 `"low"`（grep 无语义分析）
- 结果超出 `max_results` 时，末尾附加截断提示条目

---

### `analyze_python_ast` — Python AST 精确分析

比 grep 更精确：区分访问方式，标注所在函数，支持六类搜索目标，可同时指定。

```json
{
  "project_path": "/path/to/backend",
  "field_names":   ["x", "y", "survey_status_today"],
  "string_values": ["success", "failed"],
  "symbols":       ["DEFAULT_TTL", "AllCheck"],
  "call_names":    ["get_eq_partition"],
  "import_names":  ["plogen_tools"],
  "max_results":   2000
}
```

返回：`[{file, line, col, function, kind, value, extra, confidence}]`

`kind` 与 `confidence` 对应关系：

| kind | 说明 | confidence |
|---|---|---|
| `attr_access` | `obj.field` | high |
| `subscript_access` | `obj['field']` | high |
| `get_call` | `obj.get('field')` | high |
| `call` | 函数 / 方法调用 | medium |
| `import` / `import_from` / `import_symbol` | 导入 | medium |
| `name_ref` | 标识符引用 | medium |
| `assignment` | 赋值目标 | medium |
| `string_literal` | 字符串常量 | medium |
| `string_subscript` | `obj['str_val']` 的字符串值 | medium |
| `function_def` / `class_def` | 定义 | medium |
| `type_annotation` | 类型注解（参数 / 返回值 / 变量） | low |

> `import_names` 支持精确匹配（`"tools"`）和包名前缀匹配（`"tools.utils"`），不做子串匹配（`"tools"` 不会命中 `"plogen_tools"`）。

---

### `trace_callers` — 调用链追踪

找出项目中所有**直接调用**指定函数的函数和文件。

```json
{
  "project_path": "/path/to/backend",
  "function_name": "get_eq_partition"
}
```

返回：`[{file, line, function, kind, value, confidence}]`，`kind` 均为 `"call"`。

---

### `get_code_context` — 代码上下文

获取命中行前后的代码，辅助判断是否真正耦合。行号必须 >= 1。

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

**推荐工作流**：先调用 `scan_patterns` 和 / 或 `analyze_python_ast`，结果会自动缓存到服务端；再调用 `generate_impact_report` 时只需传 `change_description` 和 `project_path`，**无需重新传回扫描结果**。

```json
{
  "change_description": "将 survey_status_today 字段从 INT 改为 VARCHAR(16)",
  "project_path": "/path/to/project"
}
```

也可以显式传入结果（用于覆盖缓存）：

```json
{
  "change_description": "...",
  "project_path": "...",
  "scan_results": [...],
  "ast_results":  [...]
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

**示例 3：函数重命名**
```
把 get_eq_partition 重命名为 get_machine_partition，
/path/to/backend 里有多少个调用点？用 trace_callers 追踪。
```

**示例 4：API 路径变更**
```
/api/external/apiKey/refresh 改为 /api/external/api-keys，
哪些前端文件引用了旧路径？
```

---

## 开发

```bash
git clone https://github.com/ybmyb/Ripple-Mcp.git
cd Ripple-Mcp
pip install -e .
pytest tests/ -v
```

### 依赖

- Python 3.10+
- `mcp >= 1.0.0, < 2.0.0`
- `anyio >= 4.0.0, < 5.0.0`
- （可选）`ripgrep`：扫描更快，自动降级到系统 `grep`

---

## 与 codegraph 对比

| 能力 | codegraph | Ripple-Mcp |
|---|---|---|
| 函数调用链 | ✅ 精确 | ✅ 通过 `trace_callers` |
| 字段级访问分析 | ❌ | ✅ |
| 字符串字面量搜索 | ❌ | ✅ |
| 常量 / 枚举引用 | ❌ | ✅ |
| 类型注解分析 | ❌ | ✅ |
| 跨语言搜索 | ❌ | ✅ |
| 语义变更影响分析 | ❌ | ✅（配合 Claude） |

**推荐组合使用**：codegraph 做调用链，Ripple-Mcp 做字段级语义影响分析，两者互补。

---

## License

MIT © [ybmyb](https://github.com/ybmyb)
