"""工具注册表：内置工具 + 技能工具 + 脚本工具。"""

from typing import Any, Dict, List

from .local_script_loader import get_script_tool_definitions
from .types import ToolDefinition


def _obj_schema(properties: Dict[str, Any], required: List[str]) -> Dict[str, Any]:
    return {"type": "object", "properties": properties, "required": required}


HANDOFF_TO_AGENT_DEF = ToolDefinition(
    name="handoff_to_agent",
    description="将当前任务交接给另一个 Agent。当你确定需要另一个专业领域的 Agent 介入时才调用此工具。",
    input_schema=_obj_schema(
        {
            "target_agent_id": {"type": "string", "description": "目标 Agent 的 ID"},
            "reason": {"type": "string", "description": "交接原因"},
            "task": {"type": "string", "description": "要交接的具体任务描述"},
        },
        ["target_agent_id", "reason", "task"],
    ),
    allowed_agents=[],
)

EXECUTE_BASH_DEF = ToolDefinition(
    name="execute_bash",
    description="在本地执行 shell 命令（Windows 优先 Git Bash，否则 cmd；Linux/macOS 使用 /bin/sh）。仅在需要运行系统命令时使用。",
    input_schema=_obj_schema(
        {"command": {"type": "string", "description": "要执行的命令"}}, ["command"]
    ),
    allowed_agents=["operator"],
)

WRITE_TO_WORKSPACE_DEF = ToolDefinition(
    name="write_to_workspace",
    description="将内容写入当前会话的安全工作区文件。所有文件操作都限制在受控目录内，不允许路径穿越。",
    input_schema=_obj_schema(
        {
            "filename": {
                "type": "string",
                "description": "文件名（不含路径，如 exploit.py、script.sh）",
            },
            "content": {"type": "string", "description": "要写入的文件内容"},
        },
        ["filename", "content"],
    ),
    allowed_agents=["builder"],
)

EXECUTE_WORKSPACE_SCRIPT_DEF = ToolDefinition(
    name="execute_workspace_script",
    description="执行工作区内已存在的脚本文件。根据文件后缀自动选择解释器（.py→python, .js→node, .sh→bash, .ts→bun）。",
    input_schema=_obj_schema(
        {
            "filename": {"type": "string", "description": "工作区中的文件名（不含路径）"},
            "args": {
                "type": "array",
                "items": {"type": "string"},
                "description": "传递给脚本的参数",
            },
        },
        ["filename"],
    ),
    allowed_agents=["operator"],
)

WEB_SEARCH_DEF = ToolDefinition(
    name="web_search",
    description="在互联网上搜索信息。返回相关网页的标题、摘要和 URL。仅在需要获取实时信息或查找资料时使用。",
    input_schema=_obj_schema(
        {"query": {"type": "string", "description": "搜索关键词"}}, ["query"]
    ),
    allowed_agents=["research"],
)

TASK_COMPLETE_DEF = ToolDefinition(
    name="task_complete",
    description="标记当前任务已完成。当你确认任务目标已达成、结果已输出时调用此工具。调用后引擎将正常退出。",
    input_schema=_obj_schema(
        {"summary": {"type": "string", "description": "任务完成摘要，简述完成了什么"}},
        ["summary"],
    ),
    allowed_agents=["planner"],
)

SKILL_LIST_DEF = ToolDefinition(
    name="skill_list",
    description="列出 SEC-GO 内置安全技能库的全部启用技能（名称 + 一句话描述 + 所属分组）。任务开始后应优先调用，以查找与当前漏洞类型相关的技能。",
    input_schema={"type": "object", "properties": {}},
    allowed_agents=[],
)

SKILL_READ_DEF = ToolDefinition(
    name="skill_read",
    description="读取指定安全技能的全文工作流（攻击手法、命令参考、判定规则）。命中漏洞类型时调用，按其中工作流执行。技能是知识指导，不替代工具。",
    input_schema=_obj_schema(
        {"name": {"type": "string", "description": "技能名称（可用 skill_list 查询）"}},
        ["name"],
    ),
    allowed_agents=[],
)

BUILTIN_TOOL_DEFINITIONS: List[ToolDefinition] = [
    HANDOFF_TO_AGENT_DEF,
    EXECUTE_BASH_DEF,
    WRITE_TO_WORKSPACE_DEF,
    EXECUTE_WORKSPACE_SCRIPT_DEF,
    WEB_SEARCH_DEF,
    TASK_COMPLETE_DEF,
    SKILL_LIST_DEF,
    SKILL_READ_DEF,
]


def all_tool_definitions() -> List[ToolDefinition]:
    return BUILTIN_TOOL_DEFINITIONS + list(get_script_tool_definitions())


def get_tools_for_agent(agent_id: str) -> List[ToolDefinition]:
    return [
        d
        for d in all_tool_definitions()
        if len(d.allowed_agents) == 0 or agent_id in d.allowed_agents
    ]


def build_tool_set(defs: List[ToolDefinition]) -> List[Dict[str, Any]]:
    """统一工具集合（供 provider 转换为目标协议格式）。"""
    return [
        {"name": d.name, "description": d.description, "input_schema": d.input_schema}
        for d in defs
    ]
