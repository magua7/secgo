"""settings.json 原子写入辅助（供默认/Agent 模型配置与 Vision 配置共用）。

path 由调用方显式传入：这样各调用方能在自己的模块命名空间里解析 SETTINGS_FILE，
便于测试用 patch.object 重定向到临时文件，避免写入真实配置。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from .jsonc import stringify_jsonc


def write_settings_atomically(updated: Dict[str, Any], path: Path) -> None:
    """Flush a same-directory temporary file before replacing the live settings file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as temp_file:
            temp_file.write(stringify_jsonc(updated))
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise
