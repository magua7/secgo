"""工具定义类型（独立模块，避免 registry ↔ script_loader 循环导入）。"""

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    input_schema: Dict[str, Any]
    allowed_agents: List[str] = field(default_factory=list)
