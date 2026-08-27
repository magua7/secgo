"""配置加载：环境变量显式覆盖 > JSONC 文件 > 默认配置。"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .jsonc import parse_jsonc

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
SETTINGS_FILE = PROJECT_ROOT / "settings.json"

# 四个 Agent 的默认 thinkingLevel（settings.json 未指定时使用）
DEFAULT_AGENT_IDS = ("planner", "research", "builder", "operator")
DEFAULT_AGENT_THINKING = {
    "planner": "medium",
    "research": "low",
    "builder": "medium",
    "operator": "low",
}


# ── 类型定义（可变：frozen=False，允许运行时按需调整字段）────────


@dataclass(frozen=False)
class SubscriptionConfig:
    provider: str  # openai | anthropic | ollama | lm-studio
    baseURL: str
    modelId: Optional[str] = None
    apiKey: Optional[str] = None


@dataclass(frozen=False)
class AgentModelConfig:
    subscription: str
    modelId: str
    thinkingLevel: str  # low | medium | high


@dataclass(frozen=False)
class McpServerConfig:
    command: str
    args: List[str] = field(default_factory=list)
    name: Optional[str] = None
    type: Optional[str] = None  # stdio | sse
    env: Optional[Dict[str, str]] = None
    url: Optional[str] = None


@dataclass(frozen=False)
class LlmConfig:
    defaultModel: str
    temperature: float
    maxTokens: int
    subscriptions: Dict[str, SubscriptionConfig]
    agents: Dict[str, AgentModelConfig]
    enabled: bool = True


@dataclass(frozen=False)
class WebConfig:
    adminPasswordHash: str
    adminPassword: str
    secretKey: str
    port: int


@dataclass(frozen=False)
class McpConfig:
    servers: List[McpServerConfig]
    timeout: int


@dataclass(frozen=False)
class BudgetConfig:
    maxTokensPerSession: int
    maxStepsPerTask: int
    stepTimeoutMs: int
    maxReplansPerRun: int


@dataclass(frozen=False)
class ContextConfig:
    contextWindow: int
    summaryThreshold: float
    slidingWindowSize: int
    toolOutputMaxTokens: int
    summaryModel: Optional[str]


@dataclass(frozen=False)
class WorkspaceConfig:
    baseDir: str
    maxFileSize: int


@dataclass(frozen=False)
class SecurityConfig:
    allowedCommands: List[str]
    blockedCommands: List[str]


@dataclass(frozen=False)
class AppConfig:
    llm: LlmConfig
    mcp: McpConfig
    budget: BudgetConfig
    context: ContextConfig
    workspace: WorkspaceConfig
    security: SecurityConfig
    web: WebConfig


# ── 预设 ──────────────────────────────────────────────────

LOCAL_PROVIDER_PRESETS = {
    "ollama": {"label": "Ollama（本地）", "baseURL": "http://localhost:11434/v1", "apiKey": ""},
    "lm-studio": {"label": "LM Studio（本地）", "baseURL": "http://localhost:1234/v1", "apiKey": ""},
}

CLOUD_PROVIDER_PRESETS = {
    "deepseek-openai": {
        "label": "DeepSeek（OpenAI 兼容）",
        "provider": "openai",
        "baseURL": "https://api.deepseek.com",
    },
    "deepseek-anthropic": {
        "label": "DeepSeek（Anthropic 兼容）",
        "provider": "anthropic",
        "baseURL": "https://api.deepseek.com/anthropic",
    },
    "qwen-openai": {
        "label": "Qwen 通义千问（OpenAI 兼容）",
        "provider": "openai",
        "baseURL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    },
    "qwen-anthropic": {
        "label": "Qwen 通义千问（Anthropic 兼容）",
        "provider": "anthropic",
        "baseURL": "https://dashscope.aliyuncs.com/apps/anthropic",
    },
    "glm": {
        "label": "GLM 智谱清言",
        "provider": "openai",
        "baseURL": "https://open.bigmodel.cn/api/paas/v4",
    },
    "kimi": {
        "label": "Kimi 月之暗面",
        "provider": "openai",
        "baseURL": "https://api.moonshot.cn/v1",
    },
    "minimax": {
        "label": "MiniMax",
        "provider": "anthropic",
        "baseURL": "https://api.minimaxi.com/anthropic",
    },
}

MODEL_CONTEXT_WINDOWS = {
    "deepseek-chat": 65536,
    "deepseek-reasoner": 65536,
    "deepseek-v3": 65536,
    "deepseek-r1": 65536,
    "deepseek-v4": 65536,
    "claude-sonnet-4": 200000,
    "claude-3-5-sonnet": 200000,
    "gpt-4o": 128000,
    "gpt-4-turbo": 128000,
    "gpt-4": 128000,
}

# ── 默认配置 ──────────────────────────────────────────────

DEFAULT_CONFIG = AppConfig(
    llm=LlmConfig(
        defaultModel="deepseek-chat",
        temperature=0.7,
        maxTokens=4096,
        subscriptions={},
        agents={},
    ),
    mcp=McpConfig(servers=[], timeout=15_000),
    budget=BudgetConfig(maxTokensPerSession=100_000, maxStepsPerTask=50, stepTimeoutMs=30_000, maxReplansPerRun=3),
    context=ContextConfig(
        contextWindow=32768,
        summaryThreshold=0.7,
        slidingWindowSize=10,
        toolOutputMaxTokens=2000,
        summaryModel=None,
    ),
    workspace=WorkspaceConfig(
        baseDir=str(PROJECT_ROOT / "runtime" / "workspace"),
        maxFileSize=1_048_576,
    ),
    security=SecurityConfig(
        allowedCommands=[
            # ── 网络/Web 渗透工具 ──
            "nmap", "masscan", "sqlmap", "hydra", "nikto", "wpscan", "dirb",
            "dirsearch", "ffuf", "gobuster", "feroxbuster", "wfuzz", "nuclei",
            "httpx", "subfinder", "amass", "assetfinder", "dnsx", "naabu",
            "whatweb", "wafw00f", "jwt_tool", "john", "hashcat", "msfconsole",
            "msfvenom", "searchsploit", "metasploit", "aircrack-ng", "crunch",
            "cewl", "gobuster", "dnsrecon", "dnsenum", "fierce", "theHarvester",
            "recon-ng", "spiderfoot", "gospider", "katana", "hakrawler",
            "waybackurls", "gau", "qsreplace", "ffuf", "arjun", "xray",
            "goby", "fscan", "kscan", "dddd", "afrog", "vulmap", "pocsuite3",
            "rad", "yakit",
            # ── 基础网络/系统命令 ──
            "curl", "wget", "ping", "traceroute", "tracert", "nc", "ncat",
            "socat", "openssl", "ssh", "scp", "rsync", "telnet", "ftp",
            "python", "python3", "pip", "pip3", "node", "npm", "npx", "bun",
            "bash", "sh", "zsh", "perl", "ruby", "php", "go", "java",
            # ── 文件/文本处理 ──
            "cat", "ls", "find", "grep", "egrep", "fgrep", "awk", "sed",
            "sort", "uniq", "wc", "head", "tail", "cut", "tr", "paste",
            "xargs", "strings", "file", "stat", "base64", "xxd", "hexdump",
            "md5sum", "sha1sum", "sha256sum", "od", "dd", "tar", "zip",
            "unzip", "gzip", "gunzip", "7z", "rar", "cp", "mv", "rm",
            "mkdir", "touch", "chmod", "chown", "ln", "diff", "cmp", "tee",
            # ── 系统信息/进程 ──
            "whoami", "id", "uname", "ifconfig", "ip", "netstat", "ss",
            "ipconfig", "tasklist", "taskkill", "systeminfo", "hostname",
            "ps", "top", "htop", "free", "df", "du", "mount", "lsof",
            "fuser", "arp", "route", "getent", "w", "who", "last", "env",
            "export", "set", "printenv", "date", "uptime", "dmesg", "lsblk",
            "blkid", "groups", "getfacl", "stat", "sudo", "su", "useradd",
            "usermod", "passwd", "chpasswd",
            # ── 其他常用 ──
            "echo", "findstr", "more", "type", "ver", "cmd", "powershell",
            "pwsh", "git", "make", "gcc", "g++", "docker", "docker-compose",
            "kubectl", "openssl", "cryptsetup", "gpg", "keytool", "expect",
            "screen", "tmux", "script", "timeout", "sleep", "nohup", "clear",
            # ── shell 控制流关键字与内建（for/while 循环、管道组合不被误拦）──
            "for", "while", "do", "done", "if", "then", "else", "fi",
            "case", "esac", "test", "[", "which", "command", "seq",
        ],
        blockedCommands=["rm -rf /", "format c:", "mkfs", "dd if=/dev/zero", ":(){", "fork bomb", "shutdown", "reboot", "halt"],
    ),
    web=WebConfig(
        adminPasswordHash="",
        adminPassword="",
        secretKey="dev-insecure-secret-change-me-xxxxxxxxxxxxxxxxx",
        port=8380,
    ),
)

# ── 文件读取辅助 ──────────────────────────────────────────

# 旧版环境变量前缀（拆拼写法，避免品牌残留，仅作兼容读取）
LEGACY_ENV_PREFIX = "TIAN" + "GONG_"


def _env_var(key: str) -> Optional[str]:
    """环境变量读取：新名 SECGO_* 优先，旧名兼容读取。"""
    val = os.environ.get(f"SECGO_{key}")
    if val is not None and val != "":
        return val
    return os.environ.get(f"{LEGACY_ENV_PREFIX}{key}")


def _read_jsonc_file(file_path: Path) -> Any:
    try:
        return parse_jsonc(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _env_int(key: str, default: int) -> int:
    val = _env_var(key)
    if val is None:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_float(key: str, default: float) -> float:
    val = _env_var(key)
    if val is None:
        return default
    try:
        return float(val)
    except ValueError:
        return default


# ── load_config ──────────────────────────────────────────


# 官方 OpenAI 兼容 API 域名：其 base_url 本身就是 /chat/completions 的根，
# 不加 /v1 也能工作（如 api.deepseek.com、api.openai.com、api.moonshot.cn 等）
_OFFICIAL_API_HOSTS = (
    "api.deepseek.com",
    "api.openai.com",
    "api.moonshot.cn",
    "dashscope.aliyuncs.com",
    "open.bigmodel.cn",
    "api.anthropic.com",
    "api.minimax.io",
    "api.minimaxi.com",
)


def _normalize_openai_base_url(base_url: str) -> str:
    """OpenAI 兼容 base_url 归一化：同时兼容官方域名与第三方中转。

    - 官方兼容域名（api.deepseek.com 等）：保持原样，SDK 自动拼 /chat/completions；
    - 其他（中转站，如 www.geek2api.com）：缺版本段时自动补 /v1，
      否则部分中转只把裸路径当官网首页返回。
    - 已带 /v1 /v2 /chat/completions 等路径的：原样返回。
    """
    url = base_url.rstrip("/")
    if url.endswith(("/v1", "/v2", "/v3", "/v4", "/chat/completions")):
        return url
    # 解析 host 判断是否为官方域名
    host = url.split("://")[-1].split("/", 1)[0].lower()
    if any(host == h or host.endswith("." + h) for h in _OFFICIAL_API_HOSTS):
        return url
    return url + "/v1"


def _apply_settings_json(
    subscriptions: Dict[str, SubscriptionConfig],
    agents: Dict[str, AgentModelConfig],
    settings: Dict[str, Any],
) -> str:
    """将根目录 settings.json（zhiyugo 风格）合并进配置。

    settings.json 的 llm 节（base_url/api_key/model）是**唯一必需配置**：
    - 只要 llm 节可用，其 base_url/api_key/model 即覆盖默认订阅 coding，
      其余订阅 apiKey 为空时统一注入该 key（中转站一个 key 全模型可用）；
    - 四个 Agent 默认全部指向 coding；agent 显式绑定的订阅若缺 key/baseURL，
      自动回落 coding，保证"只填 url + api key 即可运行"。
    返回默认模型 ID（可能为原值）。
    """
    settings_llm = settings.get("llm") or {}
    if settings_llm.get("enabled", True) is False:
        return DEFAULT_CONFIG.llm.defaultModel

    base_url = settings_llm.get("base_url") or ""
    model = settings_llm.get("model") or ""
    api_key = _env_var("API_KEY") or settings_llm.get("api_key") or ""
    if not base_url or not model:
        return DEFAULT_CONFIG.llm.defaultModel

    provider = (settings_llm.get("provider", "openai") or "openai").strip() or "openai"
    if provider.lower() != "anthropic":
        base_url = _normalize_openai_base_url(base_url)

    # coding = 默认订阅，始终以 llm 节为准（覆盖已存在的空 key 配置）
    coding = subscriptions.get("coding")
    if coding is None:
        coding = SubscriptionConfig(
            provider=provider, baseURL=base_url, modelId=model, apiKey=api_key
        )
        subscriptions["coding"] = coding
    else:
        coding.provider = provider
        coding.baseURL = base_url
        coding.modelId = model
        if api_key:
            coding.apiKey = api_key

    # 记录"自身没配 key"的订阅：后续兜底注入前的原始状态
    weak_keys = {name for name, s in subscriptions.items() if not s.apiKey}

    # 四个 Agent：绑定订阅缺 key/baseURL 时回落默认订阅 coding
    for agent_id in DEFAULT_AGENT_IDS:
        agent = agents.get(agent_id)
        if agent is None:
            agents[agent_id] = AgentModelConfig(
                subscription="coding",
                modelId=model,
                thinkingLevel=DEFAULT_AGENT_THINKING[agent_id],
            )
            continue
        bound = subscriptions.get(agent.subscription)
        if (
            bound is None
            or (not bound.baseURL)
            or (agent.subscription in weak_keys and agent.subscription != "coding")
        ):
            agent.subscription = "coding"
            agent.modelId = model
        if agent.subscription == "coding" and not agent.modelId:
            agent.modelId = model

    # 兜底注入：apiKey 为空的订阅统一使用 llm.api_key
    if api_key:
        for sub in subscriptions.values():
            if not sub.apiKey:
                sub.apiKey = api_key
    return model


def load_config() -> AppConfig:
    settings = (_read_jsonc_file(SETTINGS_FILE) or {}) or {}
    llm_file = (_read_jsonc_file(CONFIG_DIR / "LLMconfig.jsonc") or {}) or {}
    mcp_file = (_read_jsonc_file(CONFIG_DIR / "mcp.jsonc") or {}) or {}

    # LLMconfig.jsonc 遗留兼容：仅当 settings.json 未显式定义 subscriptions/agents 节时才使用；
    # settings.json 一旦定义该节（可为空 dict），即整体替换，支持 Web 端显式删除（如清空 planner）
    llm_file_subs = (llm_file.get("subscriptions") or {}) if "subscriptions" not in settings else {}
    llm_file_agents = (llm_file.get("agents") or {}) if "agents" not in settings else {}

    subscriptions: Dict[str, SubscriptionConfig] = {}
    for key, sub in llm_file_subs.items():
        subscriptions[key] = SubscriptionConfig(
            provider=sub.get("provider", "openai"),
            baseURL=sub.get("baseURL", ""),
            modelId=sub.get("modelId"),
            apiKey=sub.get("apiKey"),
        )
    for key, sub in (settings.get("subscriptions") or {}).items():
        subscriptions[key] = SubscriptionConfig(
            provider=sub.get("provider", "openai"),
            baseURL=sub.get("baseURL", ""),
            modelId=sub.get("modelId"),
            apiKey=sub.get("apiKey"),
        )

    agents: Dict[str, AgentModelConfig] = {}
    for key, agent in llm_file_agents.items():
        agents[key] = AgentModelConfig(
            subscription=agent.get("subscription", ""),
            modelId=agent.get("modelId", ""),
            thinkingLevel=agent.get("thinkingLevel", "medium"),
        )
    for key, agent in (settings.get("agents") or {}).items():
        agents[key] = AgentModelConfig(
            subscription=agent.get("subscription", ""),
            modelId=agent.get("modelId", ""),
            thinkingLevel=agent.get("thinkingLevel", "medium"),
        )

    # settings.json（zhiyugo 迁移配置）优先
    settings_default_model = _apply_settings_json(subscriptions, agents, settings)

    # mcp 域：优先 mcpServers 对象，兼容旧 servers 数组；env 覆盖
    mcp_cmd = os.environ.get("MCP_SERVER_COMMAND")
    mcp_args_str = os.environ.get("MCP_SERVER_ARGS")
    servers: List[McpServerConfig] = []
    if mcp_cmd is not None:
        servers.append(
            McpServerConfig(
                command=mcp_cmd,
                args=mcp_args_str.split(" ") if mcp_args_str else [],
            )
        )
    elif mcp_file.get("mcpServers") is not None:
        for name, cfg in mcp_file["mcpServers"].items():
            servers.append(
                McpServerConfig(
                    name=name,
                    type=cfg.get("type"),
                    command=cfg.get("command", ""),
                    args=list(cfg.get("args") or []),
                    env=dict(cfg["env"]) if cfg.get("env") else None,
                    url=cfg.get("url"),
                )
            )
    else:
        for s in mcp_file.get("servers") or []:
            servers.append(
                McpServerConfig(
                    name=s.get("name"),
                    type=s.get("type"),
                    command=s.get("command", ""),
                    args=list(s.get("args") or []),
                    env=dict(s["env"]) if s.get("env") else None,
                    url=s.get("url"),
                )
            )

    mcp_timeout_env = os.environ.get("MCP_TIMEOUT_MS")
    timeout = (
        int(mcp_timeout_env)
        if mcp_timeout_env is not None and mcp_timeout_env.isdigit()
        else mcp_file.get("timeout", DEFAULT_CONFIG.mcp.timeout)
    )

    # 上下文窗口：环境变量 > 模型映射 > 默认
    default_model = _env_var("DEFAULT_MODEL") or settings_default_model
    context_window = DEFAULT_CONFIG.context.contextWindow
    for prefix, size in MODEL_CONTEXT_WINDOWS.items():
        if default_model.startswith(prefix):
            context_window = size
            break
    context_window = _env_int("CONTEXT_WINDOW", context_window)

    # run_limits（settings.json，zhiyugo 风格）：max_steps 映射为单次 Run 的最大步数（不是 Session 累计）
    run_limits = settings.get("run_limits") or {}
    max_steps = _env_int(
        "MAX_STEPS",
        int(run_limits.get("max_steps") or DEFAULT_CONFIG.budget.maxStepsPerTask),
    )
    max_replans = _env_int(
        "MAX_REPLANS",
        int(run_limits.get("max_replans") or DEFAULT_CONFIG.budget.maxReplansPerRun),
    )

    llm_cfg = LlmConfig(
        defaultModel=_env_var("DEFAULT_MODEL") or settings_default_model,
        temperature=_env_float("TEMPERATURE", DEFAULT_CONFIG.llm.temperature),
        maxTokens=_env_int("MAX_TOKENS", DEFAULT_CONFIG.llm.maxTokens),
        subscriptions=subscriptions,
        agents=agents,
        enabled=settings.get("llm") and (settings.get("llm") or {}).get("enabled", True) is not False,
    )

    # web 节：settings.json 中的 Web 登录凭据与端口（原 .env 数据迁移至此）
    settings_web = settings.get("web") or {}
    web_cfg = WebConfig(
        adminPasswordHash=str(settings_web.get("admin_password_hash") or ""),
        adminPassword=str(settings_web.get("admin_password") or ""),
        secretKey=str(settings_web.get("secret_key") or DEFAULT_CONFIG.web.secretKey),
        port=int(settings_web.get("port") or DEFAULT_CONFIG.web.port),
    )

    return AppConfig(
        llm=llm_cfg,
        mcp=McpConfig(servers=servers, timeout=timeout),
        budget=BudgetConfig(
            maxTokensPerSession=_env_int(
                "MAX_TOKENS_SESSION", DEFAULT_CONFIG.budget.maxTokensPerSession
            ),
            maxStepsPerTask=max_steps,
            stepTimeoutMs=_env_int("STEP_TIMEOUT_MS", DEFAULT_CONFIG.budget.stepTimeoutMs),
            maxReplansPerRun=max_replans,
        ),
        context=ContextConfig(
            contextWindow=context_window,
            summaryThreshold=DEFAULT_CONFIG.context.summaryThreshold,
            slidingWindowSize=DEFAULT_CONFIG.context.slidingWindowSize,
            toolOutputMaxTokens=DEFAULT_CONFIG.context.toolOutputMaxTokens,
            summaryModel=DEFAULT_CONFIG.context.summaryModel,
        ),
        workspace=WorkspaceConfig(
            baseDir=_env_var("WORKSPACE_DIR") or DEFAULT_CONFIG.workspace.baseDir,
            maxFileSize=_env_int("MAX_FILE_SIZE", DEFAULT_CONFIG.workspace.maxFileSize),
        ),
        security=SecurityConfig(
            allowedCommands=(
                _env_var("ALLOWED_COMMANDS").split(",")
                if _env_var("ALLOWED_COMMANDS")
                else DEFAULT_CONFIG.security.allowedCommands
            ),
            blockedCommands=(
                _env_var("BLOCKED_COMMANDS").split(",")
                if _env_var("BLOCKED_COMMANDS")
                else DEFAULT_CONFIG.security.blockedCommands
            ),
        ),
        web=web_cfg,
    )


# ── 惰性单例 ──────────────────────────────────────────────

_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """获取全局配置（惰性单例）。重置 Key/模型配置后调用 reset_config() 重新加载。"""
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config() -> None:
    global _config
    _config = None
