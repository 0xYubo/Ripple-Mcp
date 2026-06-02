# 我做了一个 MCP 工具，让 Claude Code 能回答「改了这个字段，哪些代码会炸」

## 起因

有一天我在改一张表的字段类型，从 `INT` 改成 `VARCHAR`。

改完之后我问自己：有多少地方用了这个字段？

我打开 codegraph 查了一下，它给我返回了函数调用链。但我真正想知道的是：**有没有代码直接读取了这个字段的值，然后拿去做了整数比较？**

codegraph 答不上来。grep 能找到，但误报太多，还要一条条看上下文。

于是我做了 Ripple-MCP。

---

## 它解决什么问题

传统代码图谱工具擅长追踪**函数调用链**：A 调用 B，B 调用 C。

但当你想分析语义级别的变更影响时，调用链不够用：

- 哪些地方直接读取了 `obj.survey_status_today`？
- 哪些地方用了字符串 `"success"` 做判断？
- 哪些地方导入了这个模块？
- TypeScript 前端里，哪些地方引用了这个 API 路径？

这些问题，靠调用图根本找不到。

Ripple-MCP 的思路是：**在调用链之上叠加字段级扫描，把 Claude 的语义理解和 grep/AST 的机械精确性结合起来。**

---

## 工具架构

一共 5 个 MCP 工具，形成一条完整的分析流水线：

```
用户描述变更（自然语言）
        ↓
  Claude 理解意图，自动决定搜索策略
        ↓
┌─────────────────────────────────────┐
│ scan_patterns      任意正则，全语言  │
│ analyze_python_ast Python AST 精析  │
│ trace_callers      直接调用链追踪   │
│ get_code_context   上下文确认       │
└─────────────────────────────────────┘
        ↓
  generate_impact_report → Markdown 报告
```

用户**不需要知道这 5 个工具的存在**，只需要用自然语言描述变更意图，Claude 自动编排调用。

---

## 核心工具详解

### scan_patterns — 通用正则扫描

最基础的工具，接受任意正则，支持所有语言和文件类型。

```json
{
  "project_path": "/path/to/project",
  "patterns": [
    "survey_status_today",
    "machine\\.x",
    "/api/external/"
  ],
  "extensions": [".py", ".ts", ".tsx", ".sql"]
}
```

同一行命中多个 pattern 时，自动合并，不会重复输出。

### analyze_python_ast — AST 精确分析

这是 Ripple-MCP 的核心差异点。

同样是找 `x` 字段，grep 会把所有包含 `x` 的行全找出来，误报率极高。AST 分析可以精确区分：

| 访问方式 | 示例 | confidence |
|---|---|---|
| 属性访问 | `machine.x` | high |
| 下标访问 | `machine['x']` | high |
| get 调用 | `machine.get('x')` | high |
| 函数调用 | `get_x()` | medium |
| 类型注解 | `def fn(x: float)` | low |

每个命中都标注**所在函数名**，让你一眼知道是哪个业务逻辑在用这个字段。

### generate_impact_report — 一键生成报告

scan 和 AST 分析的结果会自动缓存到服务端。最后只需要一句：

```json
{
  "change_description": "将 survey_status_today 字段从 INT 改为 VARCHAR(16)",
  "project_path": "/path/to/project"
}
```

输出一份按风险等级分类的 Markdown 报告，直接可以贴到 PR 描述里。

---

## 实际使用效果

在 Claude Code 里直接输入：

```
分析「把 machine 表的 x/y 坐标从左上角原点改为中心点」
对 /path/to/backend 的影响范围
```

Claude 会自动：
1. 用 `scan_patterns` 扫所有引用 `machine.x`、`machine.y` 的文件
2. 用 `analyze_python_ast` 精确定位 Python 里的字段访问
3. 对可疑命中用 `get_code_context` 确认上下文
4. 最终生成一份影响报告，列出哪些文件需要修改、风险等级如何

以前这个过程要花我 20-30 分钟手动 grep + 看代码，现在 1-2 分钟搞定。

---

## 与 codegraph 的关系

这两个工具不是竞争关系，是互补的：

| 能力 | codegraph | Ripple-MCP |
|---|---|---|
| 函数调用链 | ✅ 精确 | ✅ trace_callers |
| 字段级访问 | ❌ | ✅ |
| 字符串字面量 | ❌ | ✅ |
| 类型注解分析 | ❌ | ✅ |
| 跨语言扫描 | ❌ | ✅ |
| 语义变更分析 | ❌ | ✅ |

**推荐组合**：codegraph 做调用链，Ripple-MCP 做字段级语义影响分析。

---

## 安装方式

目前从源码安装（PyPI 版本即将发布）：

```bash
git clone https://github.com/ybmyb/Ripple-Mcp.git
cd Ripple-Mcp
pip install -e .

# 添加到 Claude Code 全局
claude mcp add ripple -s user \
  -e PYTHONPATH=/path/to/Ripple-Mcp/src \
  -- python3 -m field_impact_mcp
```

`-s user` 表示全局配置，所有项目打开 Claude Code 都可以用。

---

## 依赖

- Python 3.10+
- Claude Code（MCP 协议）
- ripgrep（可选，没有会自动降级到系统 grep）

---

## 后续计划

- [ ] 发布到 PyPI，支持 `uvx ripple-mcp` 零安装启动
- [ ] 支持 Go / Rust 的 AST 分析
- [ ] 增加跨文件影响链追踪（从字段到最终 API 的完整路径）
- [ ] 生成可交互的 HTML 报告

---

项目地址：**https://github.com/ybmyb/Ripple-Mcp**

如果你也有过「不知道改了这里会影响哪里」的焦虑，可以试试看。欢迎 Star 和提 Issue。
