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
