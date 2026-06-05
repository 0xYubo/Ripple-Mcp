"""问题11：server dispatch 层与缓存的自动化测试（此前只有 scanner/ast/reporter 层覆盖）。"""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from field_impact_mcp import server as srv


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean_cache():
    """每个用例前清空服务端缓存，避免互相污染。"""
    srv._cache.clear()
    yield
    srv._cache.clear()


def _make_project(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def fn(m):\n    return m.status\n")
    return str(tmp_path)


def test_dispatch_scan_returns_compact_json_with_query(tmp_path):
    """scan_patterns 输出为紧凑 JSON，且附带 query 摘要（问题10）"""
    d = _make_project(tmp_path)
    out = _run(srv._dispatch("scan_patterns", {"project_path": d, "patterns": [r"\.status"]}))
    assert "\n" not in out, "应为紧凑 JSON，无缩进换行"
    obj = json.loads(out)
    assert obj["query"] == {"patterns": ["\\.status"]}
    assert obj["total_found"] == 1


def test_dispatch_report_uses_cache(tmp_path):
    """generate_impact_report 不传结果时使用缓存，并标注来源查询"""
    d = _make_project(tmp_path)
    _run(srv._dispatch("analyze_python_ast", {"project_path": d, "field_names": ["status"]}))
    report = _run(srv._dispatch("generate_impact_report", {"change_description": "测试", "project_path": d}))
    assert "attr_access" in report
    assert "结果来源查询" in report and "status" in report


def test_dispatch_report_explicit_param_overrides_cache(tmp_path):
    """显式传 scan_results（即使为空）应覆盖缓存，不被静默替换"""
    d = _make_project(tmp_path)
    _run(srv._dispatch("scan_patterns", {"project_path": d, "patterns": [r"\.status"]}))
    report = _run(srv._dispatch("generate_impact_report", {
        "change_description": "测试", "project_path": d,
        "scan_results": {"total_found": 0, "returned": 0, "truncated": False, "files": []},
        "ast_results": {"total_found": 0, "returned": 0, "truncated": False, "files": []},
    }))
    assert "**扫描命中**：0 处（grep）｜0 处（AST）" in report


def test_dispatch_get_context_single_relative(tmp_path):
    d = _make_project(tmp_path)
    out = _run(srv._dispatch("get_code_context", {
        "file_path": "m.py", "line_number": 2, "project_path": d,
    }))
    assert ">>>" in out and "status" in out


def test_dispatch_get_context_batch(tmp_path):
    """设计9：locations 批量模式一次返回多段上下文"""
    d = _make_project(tmp_path)
    (tmp_path / "n.py").write_text("x = 1\ny = 2\n")
    out = _run(srv._dispatch("get_code_context", {
        "locations": [
            {"file_path": "m.py", "line_number": 2},
            {"file_path": "n.py", "line_number": 1},
        ],
        "project_path": d,
    }))
    assert "── m.py:2 ──" in out and "── n.py:1 ──" in out
    assert "status" in out and "x = 1" in out


def test_dispatch_get_context_missing_params(tmp_path):
    out = _run(srv._dispatch("get_code_context", {"file_path": "m.py"}))
    assert "错误" in out


def test_dispatch_unknown_tool():
    out = _run(srv._dispatch("no_such_tool", {}))
    assert "未知工具" in out


def test_dispatch_invalid_path_raises():
    with pytest.raises(ValueError, match="路径不存在"):
        _run(srv._dispatch("scan_patterns", {"project_path": "/nonexistent/xyz", "patterns": ["a"]}))


def test_cache_lru_eviction():
    """LRU：超过 _CACHE_MAX 时淘汰最久未使用的项目"""
    for i in range(srv._CACHE_MAX + 1):
        srv._cache_set(f"/proj/{i}", "scan_results", {"total_found": i})
    assert "/proj/0" not in srv._cache, "最早写入且未再访问的应被淘汰"
    assert f"/proj/{srv._CACHE_MAX}" in srv._cache


def test_cache_lru_touch_on_get():
    """LRU：读取会刷新位置，被读过的不应先被淘汰"""
    for i in range(srv._CACHE_MAX):
        srv._cache_set(f"/proj/{i}", "scan_results", {})
    srv._cache_get("/proj/0")                       # 触摸最旧的
    srv._cache_set("/proj/new", "scan_results", {})  # 触发淘汰
    assert "/proj/0" in srv._cache, "刚被读取的不应被淘汰"
    assert "/proj/1" not in srv._cache, "应淘汰未被触摸的最旧项"


def test_list_tools_all_read_only():
    """设计11：6 个工具全部声明 readOnlyHint"""
    tools = _run(srv.list_tools())
    assert len(tools) == 6
    names = {t.name for t in tools}
    assert names == {
        "scan_patterns", "analyze_python_ast", "get_code_context",
        "generate_impact_report", "trace_callers", "find_definition",
    }
    for t in tools:
        assert t.annotations is not None and t.annotations.readOnlyHint is True, f"{t.name} 缺 readOnlyHint"
