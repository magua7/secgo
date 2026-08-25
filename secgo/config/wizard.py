"""首次运行配置向导（CLI 版）：订阅 + 4 Agent 配置，默认 DeepSeek（OpenAI 兼容）。"""

import asyncio
import hashlib
import os
import secrets
import sys
from typing import Any, Dict, List, Optional

from rich.console import Console
from rich.panel import Panel

from .config import CLOUD_PROVIDER_PRESETS, CONFIG_DIR, LOCAL_PROVIDER_PRESETS, SETTINGS_FILE, reset_config
from .jsonc import stringify_jsonc

console: Optional[Console] = None

MODEL_FETCH_TIMEOUT_S = 8

AGENT_NAMES = ["planner", "research", "builder", "operator"]


def _input(prompt: str, default: Optional[str] = None, mask: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    raw = input(f"{prompt}{suffix}: ").strip()
    if mask and raw:
        return raw
    if not raw and default:
        return default
    return raw


def _choose(prompt: str, options: List[str], default_index: int = 0) -> int:
    console.print(prompt)
    for i, option in enumerate(options, start=1):
        mark = "  *" if i - 1 == default_index else "   "
        console.print(f"{mark}[{i}] {option}")
    while True:
        raw = input(f"输入编号 (回车={default_index + 1}): ").strip()
        if not raw:
            return default_index
        try:
            idx = int(raw) - 1
        except ValueError:
            continue
        if 0 <= idx < len(options):
            return idx
        console.print("编号超出范围，请重新输入", style="red")


async def _fetch_model_list(sub: Dict[str, str]) -> List[str]:
    import httpx

    base = sub["baseURL"].rstrip("/")
    headers: Dict[str, str] = {}
    if sub.get("apiKey"):
        headers["Authorization"] = f"Bearer {sub['apiKey']}"
    try:
        async with httpx.AsyncClient(timeout=MODEL_FETCH_TIMEOUT_S) as client:
            response = await client.get(f"{base}/models", headers=headers)
            if response.status_code != 200:
                return []
            data = response.json()
            raw = data.get("data") or data.get("models") or []
            return sorted(m.get("id", "") for m in raw if m.get("id"))
    except Exception:
        return []


def _write_config_files(
    subscriptions: Dict[str, Dict[str, str]],
    agents: Dict[str, Dict[str, str]],
    web_password: str = "secgo123",
    web_port: int = 8381,
) -> None:
    # 主配置：settings.json（单订阅场景，zhiyugo 风格）
    first_key = list(subscriptions.keys())[0]
    first_sub = subscriptions[first_key]

    # 每个订阅补上 modelId（取绑定到该订阅的第一个 Agent 的模型）。
    # 否则 _config_ready 会因订阅缺 modelId 把多订阅场景误判为"未配置"（403）。
    sub_model: Dict[str, str] = {}
    for agent in agents.values():
        sub_name = agent.get("subscription")
        if sub_name and sub_name not in sub_model and agent.get("modelId"):
            sub_model[sub_name] = agent["modelId"]
    for name, sub in subscriptions.items():
        sub.setdefault("modelId", sub_model.get(name, "deepseek-chat"))

    default_model = first_sub.get("modelId") or sub_model.get(first_key) or "deepseek-chat"

    settings = {
        "llm": {
            "enabled": True,
            "provider": first_sub["provider"],
            "base_url": first_sub["baseURL"],
            "api_key": first_sub.get("apiKey", ""),
            "model": default_model,
            "timeout_seconds": 60,
        },
        "web": {
            # Web 登录密码固定为 secgo123，不通过首次向导让用户修改。
            "admin_password_hash": hashlib.sha256("secgo123".encode()).hexdigest(),
            "admin_password": "",
            "secret_key": secrets.token_hex(32),
            "port": web_port,
        },
        "run_limits": {
            "max_steps": 50,
        },
    }
    SETTINGS_FILE.write_text(
        stringify_jsonc(settings, "SEC-GO 模型配置（含密钥，勿提交 git）"),
        encoding="utf-8",
    )

    # 多订阅/多 Agent 细化配置：写入 LLMconfig.jsonc（settings.json 优先，两者兼容并存）
    if len(subscriptions) > 1:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        llm_config = {"subscriptions": subscriptions, "agents": agents}
        (CONFIG_DIR / "LLMconfig.jsonc").write_text(
            stringify_jsonc(llm_config, "SEC-GO LLM 配置"), encoding="utf-8"
        )

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    mcp_path = CONFIG_DIR / "mcp.jsonc"
    if not mcp_path.exists():
        mcp_path.write_text(
            stringify_jsonc({"servers": [], "timeout": 15000}, "SEC-GO MCP 配置"),
            encoding="utf-8",
        )


async def run_first_run_wizard(force: bool = False) -> None:
    llm_path = CONFIG_DIR / "LLMconfig.jsonc"
    if (SETTINGS_FILE.exists() or llm_path.exists()) and not force:
        return

    console.print(
        Panel(
            "SEC-GO 首次运行配置向导\n\n"
            "按提示配置 LLM 订阅与四个 Agent 的模型。\n"
            "配置将写入 settings.json（含密钥，勿提交 git）。",
            title="SEC-GO Setup",
            border_style="cyan",
        )
    )

    subscriptions: Dict[str, Dict[str, str]] = {}

    # ── 阶段 A：订阅配置 ──
    while True:
        console.print("\n── 阶段 A：订阅配置 ──", style="bold cyan")
        sub_type = _input("订阅名称", default="coding")

        provider_labels = [
            CLOUD_PROVIDER_PRESETS[key]["label"] for key in CLOUD_PROVIDER_PRESETS
        ]
        provider_labels += [
            "OpenAI（自定义 baseURL）",
            "Anthropic（自定义 baseURL）",
            LOCAL_PROVIDER_PRESETS["ollama"]["label"],
            LOCAL_PROVIDER_PRESETS["lm-studio"]["label"],
        ]
        choice = _choose("选择 Provider（默认 DeepSeek OpenAI 兼容）:", provider_labels, 0)

        provider_keys = list(CLOUD_PROVIDER_PRESETS.keys())
        if choice < len(provider_keys):
            preset = CLOUD_PROVIDER_PRESETS[provider_keys[choice]]
            provider = preset["provider"]
            base_url = preset["baseURL"]
        else:
            custom_idx = choice - len(provider_keys)
            if custom_idx == 0:
                provider = "openai"
            elif custom_idx == 1:
                provider = "anthropic"
            elif custom_idx == 2:
                provider = "ollama"
                base_url = LOCAL_PROVIDER_PRESETS["ollama"]["baseURL"]
            else:
                provider = "lm-studio"
                base_url = LOCAL_PROVIDER_PRESETS["lm-studio"]["baseURL"]
            if custom_idx >= 2:
                pass
            else:
                base_url = _input("Base URL", default="https://api.openai.com/v1" if provider == "openai" else "https://api.anthropic.com")

        api_key = _input("API Key（可留空回车跳过，回退环境变量）", default="")

        subscriptions[sub_type] = {
            "provider": provider,
            "baseURL": base_url,
            "apiKey": api_key,
        }
        console.print(f"✓ 已保存订阅 [{sub_type}] ({provider})", style="green")

        more = _input("是否还有其他订阅? (y/N)", default="n").lower()
        if more not in ("y", "yes"):
            break

    # ── 阶段 B：Agent 配置 ──
    console.print("\n── 阶段 B：Agent 配置（4 个）──", style="bold cyan")
    sub_keys = list(subscriptions.keys())
    default_sub = sub_keys[0]

    agents: Dict[str, Dict[str, str]] = {}
    for index, agent_name in enumerate(AGENT_NAMES, start=1):
        console.print(f"\nAgent: {agent_name} ({index}/4)", style="bold yellow")
        if len(sub_keys) > 1:
            choice = _choose("选择订阅:", sub_keys, sub_keys.index(default_sub))
            sub_key = sub_keys[choice]
        else:
            sub_key = default_sub
            console.print(f"订阅: {sub_key}（唯一订阅，自动使用）")

        model_id = ""
        sub = subscriptions[sub_key]
        console.print(f"⏳ 正在获取可用模型列表（{sub['baseURL']}/models）...")
        models = await _fetch_model_list(sub)
        if models:
            shown = models[:20]
            choice = _choose("选择模型（输入 0 手动输入）:", shown + ["── 手动输入 ──"], 0)
            if choice == len(shown):
                model_id = _input("Model ID", default="deepseek-chat")
            else:
                model_id = shown[choice]
        else:
            console.print("⚠ 自动获取失败，请手动输入", style="yellow")
            model_id = _input("Model ID", default="deepseek-chat")

        think_choice = _choose("Thinking Level:", ["低 (low)", "中 (medium)", "高 (high)"], 1)
        thinking = ["low", "medium", "high"][think_choice]

        agents[agent_name] = {
            "subscription": sub_key,
            "modelId": model_id,
            "thinkingLevel": thinking,
        }

    # ── 阶段 C：固定 Web 访问密码 ──
    web_password = "secgo123"
    web_port = int(_input("Web 端口", default="8381") or 8381)

    # ── 阶段 D：预览与写入 ──
    console.print("\n── 配置预览 ──", style="bold cyan")
    for key, sub in subscriptions.items():
        console.print(f"  [{key}] provider={sub['provider']} baseURL={sub['baseURL']} apiKey={'****' if sub.get('apiKey') else '(未设置)'}")
    for name, agent in agents.items():
        console.print(f"  {name}: sub={agent['subscription']}, model={agent['modelId']}, thinking={agent['thinkingLevel']}")
    console.print(f"  web: 端口={web_port} 访问认证=已启用")

    confirm = _input("确认写入配置? (y/N)", default="y").lower()
    if confirm not in ("y", "yes"):
        console.print("已取消，未写入配置。", style="yellow")
        sys.exit(1)

    _write_config_files(subscriptions, agents, web_password, web_port)
    reset_config()
    console.print("✓ 配置文件写入成功！", style="bold green")
    console.print("  • settings.json")
    console.print("  • config/mcp.jsonc")


def main() -> None:
    global console
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    console = Console()
    asyncio.run(run_first_run_wizard(force="--setup" in sys.argv or "--force" in sys.argv))


if __name__ == "__main__":
    main()
