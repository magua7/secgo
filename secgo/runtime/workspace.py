"""安全工作区：受控目录内的文件写入与脚本执行。"""

import asyncio
import os
import platform
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.config import get_config

EXECUTE_TIMEOUT_S = 10
OUTPUT_TRUNCATE_LIMIT = 512 * 1024


def _truncate_output_text(text: str) -> str:
    """子进程输出截断：超过 512KB 时保留前 512KB 并追加截断标记。

    只影响返回的 output 文本；error 字段、stderr 处理保持原样。
    """
    if len(text) <= OUTPUT_TRUNCATE_LIMIT:
        return text
    n_bytes = len(text.encode("utf-8", errors="replace"))
    return text[:OUTPUT_TRUNCATE_LIMIT] + f"\n[输出已截断：实际 {n_bytes} 字节]"


def get_workspace_base() -> Path:
    return Path(get_config().workspace.baseDir).resolve()


def get_session_tmpdir(session_id: str) -> Path:
    """返回会话级临时目录 workspace/<session_id>/.tmp，自动创建。

    供 execute_bash 注入 $TMPDIR/$TMP/$TEMP 使用，使 Agent 的临时脚本/文件
    （如 cat > /tmp/xx）落到受控工作区而非系统临时目录。
    """
    tmp_dir = get_workspace_base() / session_id / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    return tmp_dir


def validate_path(filename: str) -> Dict[str, Any]:
    if ".." in filename or "/" in filename or "\\" in filename:
        return {
            "safe": False,
            "error": (
                f'Security: filename "{filename}" contains path traversal characters. '
                "Only plain filenames are allowed."
            ),
        }
    return {"safe": True, "path": filename}


def _resolve_session_path(session_id: str, filename: str) -> Dict[str, Any]:
    validation = validate_path(filename)
    if not validation["safe"]:
        return validation
    base_dir = get_workspace_base() / session_id
    full_path = (base_dir / filename).resolve()
    if str(full_path) != str(base_dir) and not str(full_path).startswith(str(base_dir) + os.sep):
        return {
            "safe": False,
            "error": "Security: path traversal detected. File operations are restricted to the workspace directory.",
        }
    return {"safe": True, "path": str(full_path)}


def write_file(session_id: str, filename: str, content: str) -> Dict[str, Any]:
    byte_size = len(content.encode("utf-8"))
    if byte_size > get_config().workspace.maxFileSize:
        return {
            "safe": False,
            "error": f'File "{filename}" exceeds maximum size of '
            f"{get_config().workspace.maxFileSize} bytes (actual: {byte_size} bytes).",
        }
    path_result = _resolve_session_path(session_id, filename)
    if not path_result["safe"]:
        return path_result
    try:
        Path(path_result["path"]).parent.mkdir(parents=True, exist_ok=True)
        Path(path_result["path"]).write_text(content, encoding="utf-8")
        return {"safe": True, "path": path_result["path"]}
    except OSError as err:
        return {"safe": False, "error": f"Failed to write file: {err}"}


def read_file(session_id: str, filename: str) -> Dict[str, Any]:
    path_result = _resolve_session_path(session_id, filename)
    if not path_result["safe"]:
        return {"ok": False, "error": path_result["error"]}
    try:
        content = Path(path_result["path"]).read_text(encoding="utf-8")
        if len(content.encode("utf-8")) > get_config().workspace.maxFileSize:
            return {
                "ok": False,
                "error": f'File "{filename}" exceeds maximum size of '
                f"{get_config().workspace.maxFileSize} bytes.",
            }
        return {"ok": True, "content": content}
    except OSError as err:
        return {"ok": False, "error": f"Failed to read file: {err}"}


def _get_interpreter(filename: str) -> Optional[str]:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "py": "python",
        "sh": "bash",
        "js": "node",
        "ts": "bun",
    }.get(ext)


def _resolve_windows_shell() -> str:
    env_shell = os.environ.get("SHELL")
    if env_shell and Path(env_shell).exists():
        return env_shell
    # 优先 Git Bash（显式候选路径），避免误用 WSL 的 System32\bash.exe
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
        / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "bin" / "bash.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    bash = shutil.which("bash")
    if bash:
        # 排除 WSL 的 bash.exe（System32），它不能在 -c 模式下直接执行命令
        try:
            resolved = str(Path(bash).resolve())
        except OSError:
            resolved = str(bash)
        if "System32" not in resolved and "Windows" not in resolved:
            return bash
    return "bash"


def get_shell() -> List[str]:
    """返回 [shell, flag]。Windows 优先 Git Bash，否则回退 cmd。"""
    if platform.system() == "Windows":
        shell = _resolve_windows_shell()
        if shell == "bash" and not shutil.which("bash"):
            return ["cmd.exe", "/c"]
        return [shell, "-c"]
    return ["/bin/sh", "-c"]


async def execute_script(
    session_id: str, script_path: str, args: Optional[List[str]] = None
) -> Dict[str, Any]:
    args = args or []
    path_result = _resolve_session_path(session_id, script_path)
    if not path_result["safe"]:
        return {"success": False, "error": path_result["error"]}
    interpreter = _get_interpreter(script_path)
    if interpreter is None:
        return {
            "success": False,
            "error": "No interpreter for file extension. Supported: .py, .sh, .js, .ts",
        }
    try:
        proc = await asyncio.create_subprocess_exec(
            interpreter,
            path_result["path"],
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=EXECUTE_TIMEOUT_S)
        except asyncio.TimeoutError:
            proc.kill()
            return {
                "success": False,
                "error": f"Script timed out after {EXECUTE_TIMEOUT_S}s. File: {script_path}",
            }
        out_text = stdout.decode("utf-8", errors="replace")
        err_text = stderr.decode("utf-8", errors="replace")
        output_text = _truncate_output_text(out_text)
        if proc.returncode != 0:
            return {
                "success": False,
                "output": output_text,
                "error": f"Script exited with code {proc.returncode}.\nstderr: {err_text}\nstdout: {out_text}",
            }
        return {"success": True, "output": output_text or "(no output)"}
    except OSError as err:
        return {"success": False, "error": f"Failed to execute script: {err}"}
