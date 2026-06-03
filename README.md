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

```json
{
  "mcpServers": {
    "field-impact": {
      "command": "python",
      "args": ["-m", "ripple_mcp"]
    }
  }
}
```

配置完成后，在对话中自然描述变更场景，Claude 会自动调度合适的工具完成分析。

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

```json
{
  "mcpServers": {
    "field-impact": {
      "command": "python",
      "args": ["-m", "ripple_mcp"]
    }
  }
}
```

Once integrated, describe your change scenario in natural language — Claude automatically orchestrates the appropriate tools.

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
