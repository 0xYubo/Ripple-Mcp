import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from field_impact_mcp.scanner import scan, get_context
from field_impact_mcp.ast_analyzer import analyze_file, analyze_project


# ── scanner (通用 pattern) ──────────────────────────────────────────────

def test_scan_field_access(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("x = machine['x']\ny = machine.y\n")
    results = scan(str(tmp_path), [r"machine\['x'\]", r"machine\.y"], [".py"], [])
    assert len(results) == 2


def test_scan_string_literal(tmp_path):
    f = tmp_path / "b.py"
    f.write_text("status = 'success'\nif status == 'failed':\n    pass\n")
    results = scan(str(tmp_path), [r"'success'", r"'failed'"], [".py"], [])
    assert len(results) == 2


def test_scan_function_call(tmp_path):
    f = tmp_path / "c.py"
    f.write_text("result = get_eq_partition(conn, x, y, map_id)\n")
    results = scan(str(tmp_path), [r"get_eq_partition\("], [".py"], [])
    assert len(results) == 1


def test_scan_typescript(tmp_path):
    f = tmp_path / "d.ts"
    f.write_text("const x = machine.x;\nconst y = machine.y;\n")
    results = scan(str(tmp_path), [r"machine\.(x|y)"], [".ts"], [])
    assert len(results) >= 1


def test_scan_api_path(tmp_path):
    f = tmp_path / "e.py"
    f.write_text('url = "/api/external/apiKey/refresh"\n')
    results = scan(str(tmp_path), [r"/api/external/"], [".py"], [])
    assert len(results) == 1


def test_get_context(tmp_path):
    f = tmp_path / "ctx.py"
    f.write_text("\n".join(f"line {i}" for i in range(1, 21)))
    ctx = get_context(str(f), 10, 3)
    assert ">>>" in ctx and "10" in ctx


def test_get_context_line_zero(tmp_path):
    f = tmp_path / "ctx.py"
    f.write_text("a\nb\nc\n")
    ctx = get_context(str(f), 0, 3)
    assert "行号必须" in ctx


def test_get_context_line_beyond_eof(tmp_path):
    f = tmp_path / "ctx.py"
    f.write_text("a\nb\nc\n")
    ctx = get_context(str(f), 999, 3)
    assert "超出文件范围" in ctx and "3 行" in ctx


# ── ast_analyzer (精确) ─────────────────────────────────────────────────

def test_ast_field_attr(tmp_path):
    f = tmp_path / "f.py"
    f.write_text("def fn(m):\n    return m.x + m.y\n")
    hits = analyze_file(str(f), field_names=["x", "y"])
    assert len(hits) == 2
    assert all(h["kind"] == "attr_access" for h in hits)
    assert all(h["function"] == "fn" for h in hits)


def test_ast_field_subscript(tmp_path):
    f = tmp_path / "g.py"
    f.write_text("def fn(d):\n    return d['x']\n")
    hits = analyze_file(str(f), field_names=["x"])
    assert len(hits) == 1
    assert hits[0]["kind"] == "subscript_access"


def test_ast_get_call(tmp_path):
    f = tmp_path / "h.py"
    f.write_text("def fn(d):\n    return d.get('x', 0)\n")
    hits = analyze_file(str(f), field_names=["x"])
    assert len(hits) == 1
    assert hits[0]["kind"] == "get_call"


def test_ast_string_value(tmp_path):
    f = tmp_path / "i.py"
    f.write_text("def fn():\n    return 'success'\n")
    hits = analyze_file(str(f), string_values=["success"])
    assert len(hits) == 1
    assert hits[0]["kind"] == "string_literal"


def test_ast_call_name(tmp_path):
    f = tmp_path / "j.py"
    f.write_text("def fn(conn):\n    return get_eq_partition(conn, 0, 0)\n")
    hits = analyze_file(str(f), call_names=["get_eq_partition"])
    assert any(h["kind"] == "call" for h in hits)


def test_ast_import(tmp_path):
    f = tmp_path / "k.py"
    f.write_text("from plogen_tools import match_pos_count\n")
    hits = analyze_file(str(f), import_names=["plogen_tools"])
    assert len(hits) == 1
    assert hits[0]["kind"] == "import_from"


def test_ast_symbol(tmp_path):
    f = tmp_path / "l.py"
    f.write_text("DEFAULT_TTL = 30\nexpiry = DEFAULT_TTL * 2\n")
    hits = analyze_file(str(f), symbols=["DEFAULT_TTL"])
    # Bug 5 修复：_suppressed 机制后精确为 2 条（assignment + name_ref），用 == 捕获未来回归
    assert len(hits) == 2
    kinds = {h["kind"] for h in hits}
    assert kinds == {"assignment", "name_ref"}


def test_ast_param_annotation(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def fn(x: float, y: float) -> bool:\n    return x > y\n")
    hits = analyze_file(str(f), symbols=["float"])
    type_hits = [h for h in hits if h["kind"] == "type_annotation" and "param" in h["extra"]]
    # 精确断言：x: float 和 y: float 各产生 1 条，共 2 条
    assert len(type_hits) == 2, f"期望 2 条参数注解命中，实际 {len(type_hits)} 条"


def test_ast_return_annotation(tmp_path):
    f = tmp_path / "n.py"
    f.write_text("def fn() -> MyClass:\n    pass\n")
    hits = analyze_file(str(f), symbols=["MyClass"])
    assert any(h["kind"] == "type_annotation" and h["extra"] == "return_type" for h in hits)


def test_ast_combined(tmp_path):
    """同一文件里同时命中字段访问、字符串、函数调用、导入。"""
    f = tmp_path / "o.py"
    f.write_text(
        "from plogen_tools import match_pos_count\n"
        "def update(m):\n"
        "    if m.status == 'success':\n"
        "        match_pos_count(m['x'], m['y'])\n"
    )
    hits = analyze_file(
        str(f),
        field_names=["status", "x", "y"],
        string_values=["success"],
        call_names=["match_pos_count"],
        import_names=["plogen_tools"],
    )
    kinds = {h["kind"] for h in hits}
    assert "attr_access" in kinds
    assert "string_literal" in kinds
    assert "call" in kinds
    assert "import_from" in kinds


# ── 集成测试：端到端流程（A6）──────────────────────────────────────────

from field_impact_mcp.reporter import build_report


def test_report_with_scan_only(tmp_path):
    """scan_patterns 结果传入 build_report，不应崩溃"""
    f = tmp_path / "a.ts"
    f.write_text("const x = machine.x;\nconst y = machine.y;\n")
    scan_results = scan(str(tmp_path), [r"machine\.(x|y)"], [".ts"], [])
    report = build_report(
        change_description="坐标从左上角改为中心点",
        project_path=str(tmp_path),
        scan_results=scan_results,
        ast_results=[],
    )
    assert "字段影响分析报告" in report
    assert "machine" in report


def test_report_with_ast_only(tmp_path):
    """analyze_file 结果传入 build_report，不应崩溃（修复 B1 验证）"""
    f = tmp_path / "b.py"
    f.write_text("def fn(m):\n    return m.x + m.y\n")
    ast_results = analyze_file(str(f), field_names=["x", "y"])
    assert len(ast_results) >= 2
    report = build_report(
        change_description="字段 x/y 类型变更",
        project_path=str(tmp_path),
        scan_results=[],
        ast_results=ast_results,
    )
    assert "字段影响分析报告" in report
    assert "attr_access" in report


def test_report_combined(tmp_path):
    """同时有 scan 和 AST 结果，报告正常生成"""
    py_f = tmp_path / "c.py"
    py_f.write_text("def fn(m):\n    return m.status\n")
    ts_f = tmp_path / "d.ts"
    ts_f.write_text("const s = obj.status;\n")

    scan_results = scan(str(tmp_path), [r"\.status"], [".ts"], [])
    ast_results = analyze_file(str(py_f), field_names=["status"])

    report = build_report(
        change_description="status 字段重命名",
        project_path=str(tmp_path),
        scan_results=scan_results,
        ast_results=ast_results,
    )
    assert "字段影响分析报告" in report
    assert "attr_access" in report
    assert "status" in report


def test_scan_multi_pattern_same_line(tmp_path):
    """B3：同一行命中多个 pattern，patterns 列表应包含所有命中 pattern"""
    f = tmp_path / "e.py"
    f.write_text("machine_x = float(machine['x'])\n")
    results = scan(str(tmp_path), [r"machine_x", r"machine\['x'\]"], [".py"], [])
    assert len(results) == 1
    assert len(results[0]["patterns"]) == 2


def test_scan_invalid_pattern(tmp_path):
    """B7：无效正则应抛出 ValueError"""
    import pytest
    with pytest.raises(ValueError, match="无效正则表达式"):
        scan(str(tmp_path), [r"(unclosed"], [".py"], [])


def test_scan_invalid_path():
    """B6：不存在的路径应抛出 ValueError"""
    import pytest
    with pytest.raises(ValueError, match="路径不存在"):
        scan("/nonexistent/path/xyz", [r"foo"], [".py"], [])


def test_trace_callers(tmp_path):
    """A3：trace_callers 找出调用指定函数的位置"""
    from field_impact_mcp.ast_analyzer import trace_callers
    f = tmp_path / "f.py"
    f.write_text(
        "def caller_a(conn):\n"
        "    return get_eq_partition(conn, 1, 2)\n"
        "def caller_b(conn):\n"
        "    return get_eq_partition(conn, 3, 4)\n"
    )
    results = trace_callers(str(tmp_path), "get_eq_partition")
    assert len(results) == 2
    assert all(r["kind"] == "call" for r in results)
    assert all(r["value"] == "get_eq_partition" for r in results)


def test_ast_no_duplicate_name_ref(tmp_path):
    """B2：machine.x 中 machine 作为 symbol，name_ref 不应重复"""
    f = tmp_path / "g.py"
    f.write_text("def fn(machine):\n    return machine.x\n")
    hits = analyze_file(str(f), symbols=["machine"], field_names=["x"])
    name_ref_hits = [h for h in hits if h["kind"] == "name_ref" and h["value"] == "machine"]
    assert len(name_ref_hits) == 1, f"期望 1 个 name_ref，实际 {len(name_ref_hits)} 个"


def test_ast_annotation_no_substring_false_positive(tmp_path):
    """B8：_check_annotation 不应把 'Matrix' 误报为搜索符号 'x'"""
    f = tmp_path / "h.py"
    f.write_text("def fn(m: Matrix) -> bool:\n    return True\n")
    hits = analyze_file(str(f), symbols=["x"])
    annotation_hits = [h for h in hits if h["kind"] == "type_annotation"]
    assert len(annotation_hits) == 0, "子串 'x' 不应命中 'Matrix' 类型注解"


# ── 第二轮 bug 修复回归测试 ────────────────────────────────────────────

def test_ast_assign_no_duplicate_name_ref(tmp_path):
    """Bug 1：赋值目标 name_ref 不应重复——assignment target 应被 _suppressed"""
    f = tmp_path / "a1.py"
    f.write_text("DEFAULT_TTL = 30\n")
    hits = analyze_file(str(f), symbols=["DEFAULT_TTL"])
    assert len(hits) == 1
    assert hits[0]["kind"] == "assignment"


def test_ast_ann_assign_no_duplicate_name_ref(tmp_path):
    """Bug 1：注解变量 x: MyClass 只产生 1 条 type_annotation，不附加 name_ref"""
    f = tmp_path / "a2.py"
    f.write_text("x: MyClass\n")
    hits = analyze_file(str(f), symbols=["MyClass"])
    assert len(hits) == 1
    assert hits[0]["kind"] == "type_annotation"


def test_ast_ann_assign_value_is_symbol_name(tmp_path):
    """Bug 3：visit_AnnAssign value 应为符号名（child.id），不应为整个注解字符串"""
    f = tmp_path / "a3.py"
    f.write_text("x: Optional[MyClass]\n")
    hits = analyze_file(str(f), symbols=["MyClass"])
    type_hits = [h for h in hits if h["kind"] == "type_annotation"]
    assert len(type_hits) == 1
    assert type_hits[0]["value"] == "MyClass", f"期望 'MyClass'，实际 {type_hits[0]['value']!r}"


def test_ast_subscript_no_double_string_hit(tmp_path):
    """Bug 2：d['status'] 搜索 string_values=['status']，只应产生 string_subscript，不产生 string_literal"""
    f = tmp_path / "a4.py"
    f.write_text("x = d['status']\n")
    hits = analyze_file(str(f), string_values=["status"])
    assert len(hits) == 1
    assert hits[0]["kind"] == "string_subscript"


def test_ast_subscript_triple_hit_prevented(tmp_path):
    """Bug 2：d['x'] 同时在 field_names 和 string_values，只产生 2 条（subscript_access + string_subscript），不产生第 3 条"""
    f = tmp_path / "a5.py"
    f.write_text("x = d['x']\n")
    hits = analyze_file(str(f), field_names=["x"], string_values=["x"])
    kinds = [h["kind"] for h in hits]
    assert "string_literal" not in kinds, f"不应出现 string_literal，实际 kinds={kinds}"
    assert "subscript_access" in kinds
    assert "string_subscript" in kinds
    assert len(hits) == 2


def test_ast_get_call_str_no_duplicate_string_literal(tmp_path):
    """Bug 2：d.get('x') 搜索 string_values=['x']，只应产生 get_call_str，不产生 string_literal"""
    f = tmp_path / "a6.py"
    f.write_text("v = d.get('x')\n")
    hits = analyze_file(str(f), string_values=["x"])
    kinds = [h["kind"] for h in hits]
    assert "string_literal" not in kinds, f"不应出现 string_literal，实际 kinds={kinds}"
    assert "get_call_str" in kinds


def test_ast_annotation_multi_symbol_union(tmp_path):
    """Bug 4：Union[A, B] 注解中 A 和 B 都在 symbols，两个都应被记录，不应因 break 丢掉一个"""
    f = tmp_path / "a7.py"
    f.write_text("from typing import Union\ndef fn(x: Union[A, B]) -> None:\n    pass\n")
    hits = analyze_file(str(f), symbols=["A", "B"])
    type_hits = [h for h in hits if h["kind"] == "type_annotation"]
    values = {h["value"] for h in type_hits}
    assert "A" in values and "B" in values, f"期望 A 和 B 都被记录，实际 values={values}"


def test_ast_import_from_no_substring_match(tmp_path):
    """Bug 5：import_names=['tools'] 不应子串匹配 plogen_tools 或 my_tools_helper"""
    f = tmp_path / "a8.py"
    f.write_text(
        "from plogen_tools import match_pos_count\n"
        "from my_tools_helper import foo\n"
    )
    hits = analyze_file(str(f), import_names=["tools"])
    import_hits = [h for h in hits if h["kind"] in ("import_from", "import_symbol")]
    assert len(import_hits) == 0, f"'tools' 不应命中子串，实际 hits={import_hits}"


def test_ast_import_from_exact_and_prefix_match(tmp_path):
    """Bug 5 修复后：精确匹配 'tools' 和前缀匹配 'tools.utils' 应正常命中"""
    f = tmp_path / "a9.py"
    f.write_text(
        "from tools import something\n"
        "from tools.utils import helper\n"
    )
    hits = analyze_file(str(f), import_names=["tools"])
    import_from_hits = [h for h in hits if h["kind"] == "import_from"]
    assert len(import_from_hits) == 2, f"期望 2 个 import_from，实际 {len(import_from_hits)} 个"


def test_reporter_relative_path_safe(tmp_path):
    """Bug 6：_relative 不应把 /foo 路径错误匹配到 /foobar/x.py"""
    from field_impact_mcp.reporter import _relative
    import os
    # 构造 project_path = tmp_path/foo，file_path = tmp_path/foobar/x.py
    project = str(tmp_path / "foo")
    unrelated = str(tmp_path / "foobar" / "x.py")
    result = _relative(unrelated, project)
    # 应返回原始路径（无法 relative_to），不应返回 "bar/x.py"
    assert result == unrelated


def test_reporter_scan_count_excludes_truncated_marker(tmp_path):
    """新问题2：报告头的扫描命中数不应包含 __truncated__ 哨兵条目"""
    from field_impact_mcp.reporter import build_report
    scan_results = [
        {"file": str(tmp_path / "a.py"), "line": 1, "code": "x = 1", "patterns": ["x"], "confidence": "low"},
        {"file": "__truncated__", "line": 0, "code": "结果已截断", "patterns": [], "confidence": "low"},
    ]
    report = build_report("test", str(tmp_path), scan_results, [])
    assert "**扫描命中**：1 处" in report, "截断哨兵不应计入命中数"


# ── 第四轮 bug 修复回归测试 ────────────────────────────────────────────

def test_ast_call_no_duplicate_name_ref_when_in_symbols(tmp_path):
    """Bug 1A：foo(a) 中 foo 同时在 call_names 和 symbols，只应产生 call，不应额外产生 name_ref"""
    f = tmp_path / "b1.py"
    f.write_text("def caller():\n    foo(1)\n")
    hits = analyze_file(str(f), call_names=["foo"], symbols=["foo"])
    call_hits     = [h for h in hits if h["kind"] == "call"     and h["value"] == "foo"]
    name_ref_hits = [h for h in hits if h["kind"] == "name_ref" and h["value"] == "foo"]
    assert len(call_hits) == 1, f"期望 1 个 call，实际 {len(call_hits)} 个"
    assert len(name_ref_hits) == 0, f"不应产生额外 name_ref，实际 {len(name_ref_hits)} 个"


def test_ast_call_method_no_false_attr_access(tmp_path):
    """Bug 1B：obj.status() 同时在 call_names 和 field_names，只应产生 call，不应产生误报 attr_access"""
    f = tmp_path / "b2.py"
    f.write_text("def fn(obj):\n    obj.status()\n")
    hits = analyze_file(str(f), call_names=["status"], field_names=["status"])
    call_hits       = [h for h in hits if h["kind"] == "call"        and h["value"] == "status"]
    attr_access_hits = [h for h in hits if h["kind"] == "attr_access" and h["value"] == "status"]
    assert len(call_hits) == 1, f"期望 1 个 call，实际 {len(call_hits)} 个"
    assert len(attr_access_hits) == 0, f"方法调用不应产生 attr_access，实际 {len(attr_access_hits)} 个"


def test_ast_ann_assign_target_recorded_as_assignment(tmp_path):
    """Bug 2：x: int = 30 中的 x 应记录为 assignment，而非 name_ref"""
    f = tmp_path / "b3.py"
    f.write_text("DEFAULT_TTL: int = 30\n")
    hits = analyze_file(str(f), symbols=["DEFAULT_TTL"])
    kinds = [h["kind"] for h in hits if h["value"] == "DEFAULT_TTL"]
    assert "assignment" in kinds, f"带注解赋值的目标应为 assignment，实际 kinds={kinds}"
    assert "name_ref" not in kinds, f"不应产生 name_ref，实际 kinds={kinds}"


def test_ast_tuple_unpack_all_targets_as_assignment(tmp_path):
    """Bug 4：a, b = fn() 中 a 和 b 都应记录为 assignment，而非 name_ref"""
    f = tmp_path / "b4.py"
    f.write_text("a, b = get_data()\n")
    hits = analyze_file(str(f), symbols=["a", "b"])
    kinds_a = [h["kind"] for h in hits if h["value"] == "a"]
    kinds_b = [h["kind"] for h in hits if h["value"] == "b"]
    assert kinds_a == ["assignment"], f"a 应为 assignment，实际 {kinds_a}"
    assert kinds_b == ["assignment"], f"b 应为 assignment，实际 {kinds_b}"


def test_ast_nested_tuple_unpack_as_assignment(tmp_path):
    """Bug 4：(a, (b, c)) = fn() 嵌套解包，所有变量都应记录为 assignment"""
    f = tmp_path / "b5.py"
    f.write_text("(a, (b, c)) = get_data()\n")
    hits = analyze_file(str(f), symbols=["a", "b", "c"])
    for name in ["a", "b", "c"]:
        kinds = [h["kind"] for h in hits if h["value"] == name]
        assert kinds == ["assignment"], f"{name} 应为 assignment，实际 {kinds}"


def test_ast_max_results_truncation(tmp_path):
    """设计6：analyze_project max_results 截断时返回上限条数 + 哨兵"""
    from field_impact_mcp.ast_analyzer import analyze_project
    # 写 3 个文件，每个含 2 个命中，共 6 条；限制 max_results=3
    for i in range(3):
        (tmp_path / f"f{i}.py").write_text(f"x_{i} = obj.status\ny_{i} = obj.status\n")
    results = analyze_project(str(tmp_path), field_names=["status"], max_results=3)
    # 应有 3 条真实结果 + 1 条哨兵
    assert results[-1]["file"] == "__truncated__", "最后一条应为截断哨兵"
    real = [r for r in results if r.get("file") != "__truncated__"]
    assert len(real) == 3, f"期望 3 条真实结果，实际 {len(real)} 条"


def test_reporter_ast_truncation_excluded_from_table(tmp_path):
    """问题2：AST 结果被截断时，哨兵条目不应出现在报告表格中"""
    from field_impact_mcp.reporter import build_report
    ast_results = [
        {"file": str(tmp_path / "a.py"), "line": 1, "kind": "attr_access",
         "value": "x", "extra": "obj", "function": "fn", "confidence": "high"},
        {"file": "__truncated__", "line": 0, "kind": "__truncated__",
         "value": "结果已截断", "extra": "", "function": "", "confidence": "low"},
    ]
    report = build_report("test", str(tmp_path), [], ast_results)
    assert "__truncated__" not in report, "哨兵的 kind 不应出现在报告正文中"
    assert "结果已截断" in report, "截断提示应出现在报告末尾"
    assert "**扫描命中**：0 处（grep）｜1 处（AST）" in report, "AST 命中数不应含哨兵"
