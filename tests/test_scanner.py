import os
import sys
import tempfile
import textwrap

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from field_impact_mcp.scanner import build_patterns, scan, get_context
from field_impact_mcp.ast_analyzer import analyze_file


def _write(tmp, name, content):
    p = os.path.join(tmp, name)
    with open(p, "w") as f:
        f.write(textwrap.dedent(content))
    return p


def test_build_patterns():
    pats = build_patterns(["x", "y"], ["machine", "eq"])
    assert any("machine" in p for p in pats)
    assert any("x" in p for p in pats)


def test_scan_finds_field(tmp_path):
    f = tmp_path / "foo.py"
    f.write_text("x = machine['x']\ny = machine.y\n")
    pats = build_patterns(["x", "y"], ["machine"])
    results = scan(str(tmp_path), pats, [".py"], [])
    assert len(results) >= 1


def test_ast_analyzer_attribute(tmp_path):
    f = tmp_path / "bar.py"
    f.write_text("def fn(machine):\n    return machine.x + machine.y\n")
    hits = analyze_file(str(f), ["x", "y"], ["machine"])
    assert len(hits) == 2
    assert hits[0]["access_type"] == "attribute"
    assert hits[0]["function"] == "fn"


def test_ast_analyzer_subscript(tmp_path):
    f = tmp_path / "baz.py"
    f.write_text("def fn(d):\n    return d['x']\n")
    hits = analyze_file(str(f), ["x"], [])
    assert len(hits) == 1
    assert hits[0]["access_type"] == "subscript"


def test_ast_analyzer_get_call(tmp_path):
    f = tmp_path / "qux.py"
    f.write_text("def fn(d):\n    return d.get('x', 0)\n")
    hits = analyze_file(str(f), ["x"], [])
    assert len(hits) == 1
    assert hits[0]["access_type"] == "get_call"


def test_get_context(tmp_path):
    f = tmp_path / "ctx.py"
    f.write_text("\n".join(f"line {i}" for i in range(1, 21)))
    ctx = get_context(str(f), 10, 3)
    assert ">>>" in ctx
    assert "10" in ctx
