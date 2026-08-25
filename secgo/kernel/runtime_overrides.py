"""运行时模型/订阅覆盖表（供 /model 命令写入、get_agent 读取）。"""

from typing import Dict, Optional

_runtime_overrides: Dict[str, Dict[str, Optional[str]]] = {}


def get_runtime_override(agent_id: str) -> Optional[Dict[str, Optional[str]]]:
    return _runtime_overrides.get(agent_id)


def set_runtime_override(agent_id: str, override: Dict[str, Optional[str]]) -> None:
    _runtime_overrides[agent_id] = override


def get_all_runtime_overrides() -> Dict[str, Dict[str, Optional[str]]]:
    return dict(_runtime_overrides)
