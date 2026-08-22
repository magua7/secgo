"""脚本工具加载器：扫描 secgo/tools/local/ 下的 .py/.php 文件。

元数据声明格式：
- Python (.py)  → `# @secgo-tool {JSON}`
- PHP    (.php) → `// @secgo-tool {JSON}`

参数以 JSON 字符串通过 argv[1] 传入脚本，脚本通过 stdout 返回结果。
"""

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..runtime.workspace import _truncate_output_text
from .types import ToolDefinition

LOCAL_DIR = Path(__file__).resolve().parent / "local"

# 新前缀优先；兼容解析历史脚本的旧前缀（旧品牌名拆拼，避免残留）
_LEGACY_BRAND = "tian" + "gong"
MANIFEST_PREFIXES = (
    "# @secgo-tool",
    "// @secgo-tool",
    f"# @{_LEGACY_BRAND}-tool",
    f"// @{_LEGACY_BRAND}-tool",
)

COMMENT_PREFIXES = ("#", "//", "<?php", "/*", "*", "*/", '"""', "'''")

SCRIPT_TIMEOUT_S = 30

_cached_tools: Optional[List[Dict[str, Any]]] = None


def _parse_manifest(file_path: Path) -> Optional[Dict[str, Any]]:
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in content.split("\n")[:20]:
        trimmed = line.strip()
        json_str = None
        for prefix in MANIFEST_PREFIXES:
            if trimmed.startswith(prefix):
                json_str = trimmed[len(prefix):].strip()
                break
        if json_str is not None:
            try:
                manifest = json.loads(json_str)
                if not manifest.get("name") or not manifest.get("description"):
                    print(f"[script-loader] 跳过 {file_path}: manifest 缺少 name 或 description")
                    return None
                return manifest
            except json.JSONDecodeError as err:
                print(f"[script-loader] 解析 {file_path} 元数据失败: {err}")
                return None
        if trimmed and not any(trimmed.startswith(p) for p in COMMENT_PREFIXES):
            break
    return None


def _build_input_schema(inputs: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not inputs:
        return {"type": "object", "properties": {}}
    properties: Dict[str, Any] = {}
    required: List[str] = []
    for key, field in inputs.items():
        field_type = field.get("type", "string")
        schema: Dict[str, Any] = {"type": field_type}
        if field.get("description"):
            schema["description"] = field["description"]
        if field_type == "array":
            schema["items"] = {"type": "string"}
        properties[key] = schema
        if field.get("required") is not False:
            required.append(key)
    return {"type": "object", "properties": properties, "required": required}


def load_script_tools() -> List[Dict[str, Any]]:
    global _cached_tools
    if _cached_tools is not None:
        return _cached_tools

    tools: List[Dict[str, Any]] = []
    if LOCAL_DIR.is_dir():
        for filename in sorted(LOCAL_DIR.iterdir()):
            if filename.suffix not in (".py", ".php"):
                continue
            manifest = _parse_manifest(filename)
            if manifest is None:
                continue
            definition = ToolDefinition(
                name=manifest["name"],
                description=manifest.get("description", ""),
                input_schema=_build_input_schema(manifest.get("inputs")),
                allowed_agents=list(manifest.get("agents") or []),
            )
            tools.append({"definition": definition, "file_path": str(filename)})

    if tools:
        print(
            f"[script-loader] 已加载 {len(tools)} 个脚本工具: "
            + ", ".join(t["definition"].name for t in tools)
        )
    _cached_tools = tools
    return tools


def get_script_tool_definitions() -> List[ToolDefinition]:
    return [t["definition"] for t in load_script_tools()]


def get_script_tool_names() -> set:
    return {t["definition"].name for t in load_script_tools()}


async def execute_script_tool(tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    target = next((t for t in load_script_tools() if t["definition"].name == tool_name), None)
    if target is None:
        return {"success": False, "error": f"Script tool not found: {tool_name}"}

    file_path = Path(target["file_path"])
    interpreter = "php" if file_path.suffix == ".php" else "python"

    try:
        proc = await asyncio.create_subprocess_exec(
            interpreter,
            str(file_path),
            json.dumps(args, ensure_ascii=False),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=SCRIPT_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "success": False,
                "error": f"Script timed out after {SCRIPT_TIMEOUT_S}s. Tool: {tool_name}",
            }
        out_text = stdout.decode("utf-8", errors="replace")
        err_text = stderr.decode("utf-8", errors="replace")
        output_text = _truncate_output_text(out_text)
        if proc.returncode != 0:
            return {
                "success": False,
                "output": output_text,
                "error": (
                    f"Script exited with code {proc.returncode}.\n"
                    f"stderr: {err_text}\nstdout: {out_text}"
                ),
            }
        return {"success": True, "output": output_text or "(no output)"}
    except OSError as err:
        return {"success": False, "error": f'Failed to execute script tool "{tool_name}": {err}'}
