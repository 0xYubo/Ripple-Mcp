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
    assert len(hits) >= 2


def test_ast_param_annotation(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def fn(x: float, y: float) -> bool:\n    return x > y\n")
    hits = analyze_file(str(f), symbols=["float"])
    assert any(h["kind"] == "type_annotation" and "param" in h["extra"] for h in hits)


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
