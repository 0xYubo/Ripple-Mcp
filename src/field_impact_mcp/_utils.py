"""
内部共享工具函数。
"""
from __future__ import annotations

from pathlib import Path


def validate_project_path(project_path: str) -> None:
    """校验 project_path 是否为合法存在的目录，不合法则抛 ValueError。"""
    p = Path(project_path)
    if not p.exists():
        raise ValueError(f"路径不存在: {project_path}")
    if not p.is_dir():
        raise ValueError(f"路径不是目录: {project_path}")


def to_relative(file_path: str, project_path: str) -> str:
    """把绝对路径转为相对 project_path 的路径；不在其下则原样返回。
    设计8：所有扫描结果统一返回相对路径，避免每条命中重复长前缀浪费 token。
    """
    try:
        return str(Path(file_path).relative_to(project_path))
    except ValueError:
        return file_path
