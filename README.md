# SEC-GO

**SEC-GO** 是一款多 Agent 安全智能体引擎（Python 实现），内置 **100+ 安全技能库**，
支持 CLI 终端与 Web 浏览器两种交互形态。项目基于 TianGong 多 Agent 框架改造。

## 核心特性

- **四 Agent 协作架构**：Planner（任务规划）→ Research（信息检索）/ Builder（代码构建）/ Operator（系统执行），
  通过 `handoff_to_agent` 工具自动交接，纯函数引擎 + 事件总线输出
- **100+ 安全技能库**：覆盖 Web/API 渗透、AD/Kerberos、二进制利用、密码学、CTF、取证等 17 个分组
  （SQLi、XSS、SSRF、RCE、提权、免杀……），Planner 任务开始时自动 `skill_list`，命中漏洞类型时 `skill_read` 按工作流执行
- **MCP 扩展**：接入任意 MCP 服务器（stdio/SSE），工具以 `mcp_<server>_<tool>` 注入全体 Agent，Operator 全量可用
- **流式输出**：LLM 逐字流式显示，Agent 思考/工具调用/TODO 进度全程可见，无黑盒转圈
- **会话持久化**：SQLite 存储会话状态（旧版数据库自动改名迁移，不丢历史）
- **预算控制**：会话级 Token 上限、最大步数、上下文摘要压缩、滑动窗口折叠
- **安全工作区**：文件写入/脚本执行限制在受控目录，命令白名单 + 黑名单

## 两种启动方式

| 脚本 | 形态 | 说明 |
| ---- | ---- | ---- |
| `cli.bat` | CLI 终端（交互式 TUI） | rich + prompt_toolkit 渲染，支持 `/skill /mcp /model /session` 命令 |
| `web.bat` | Web 浏览器页面 | FastAPI + SSE 事件流，启动后自动打开 `http://localhost:8381` |

两个脚本均自动完成：检测 Python → 首次运行引导配置向导 → 安装依赖 → 启动。
端口可用环境变量 `SECGO_WEB_PORT` 覆盖。

也可以手动启动：

```bash
python -m secgo              # CLI 终端
python -m secgo.web          # Web 形态
python -m secgo.headless "任务"   # Headless（JSON Lines 输出，保留模式）
```

## 快速开始

1. 安装 [Python 3.10+](https://www.python.org/downloads/)（勾选 "Add python.exe to PATH"）
2. 配置 `settings.json`（已内置 DeepSeek 配置；如需更换模型，直接编辑或删除后走配置向导）：

```jsonc
{
  "llm": {
    "enabled": true,
    "provider": "openai-compatible",       // openai | anthropic | ollama | lm-studio
    "base_url": "https://api.deepseek.com/v1",
    "api_key": "sk-...",
    "model": "deepseek-v4-flash",
    "timeout_seconds": 60
  },
  "run_limits": {
    "max_steps": 50
  }
}
```

3. 双击 `cli.bat`（或 `web.bat`）——脚本会自动安装依赖；`settings.json` 缺失时才启动配置向导
4. 输入安全任务开始，如：

```
使用 skill_list 查看技能库，然后对 http://example.com 做 SQL 注入测试
```

> 四个 Agent 默认全部指向 `settings.json` 中的同一订阅与模型；
> 多订阅/细粒度 Agent 配置可继续使用 `config/LLMconfig.jsonc`（settings.json 优先）。

## CLI 内置命令

| 命令 | 说明 |
| ---- | ---- |
| `/skill list` | 列出全部启用技能（名称 + 一句话描述） |
| `/skill <name>` | 显示指定技能全文 |
| `/skill search <关键词>` | 按名称/描述模糊搜索（top10） |
| `/mcp status` | 查看 MCP 连接状态与工具数 |
| `/mcp tools` | 列出全部 MCP 工具 |
| `/model` | 查看/切换各 Agent 的模型与订阅 |
| `/session list` | 历史会话列表 |
| `/session status` | 当前会话 Token 用量与 TODO |
| `/clear` `/exit` | 清屏 / 退出 |

## 配置

主配置（含密钥，勿提交 git）：

- `settings.json` — 全部用户配置持久化于此（`settings.example.json` 为提交模板）：
  - `llm` — 默认模型（provider/base_url/api_key/model，zhiyugo 风格）
  - `subscriptions` / `agents` — 多订阅与四 Agent 精细模型绑定（覆盖 `config/LLMconfig.jsonc` 同名项）
  - `web` — Web 登录与端口：`admin_password_hash`（sha256，留空 = 不设密码）、`secret_key`（Cookie 签名）、`port`
  - `run_limits` — 运行限额（max_steps / max_replans / max_seconds）
- `config/LLMconfig.jsonc` — 可选的多订阅与四 Agent 精细模型绑定（遗留兼容，settings.json 优先）
- `config/mcp.jsonc` — MCP 服务器列表，例如：

```jsonc
{
  "mcpServers": {
    "playwright": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@playwright/mcp@latest"]
    }
  }
}
```

Web 端模型配置（API Key）通过「⚙ 设置」页写入 `settings.json` 的
`llm` / `subscriptions` / `agents` 节；退出登录不删除配置。访问密码与密钥也可直接编辑
`settings.json` 的 `web` 节（hash 生成：`python -c "import hashlib;print(hashlib.sha256(b'密码').hexdigest())"`）。

环境变量（`SECGO_*` 新名优先，旧版框架环境变量名兼容读取；`.env` 文件不再加载）：

| 变量 | 说明 |
| ---- | ---- |
| `SECGO_DEFAULT_MODEL` | 默认模型 ID |
| `SECGO_MAX_TOKENS_SESSION` | 会话级 token 上限 |
| `SECGO_MAX_STEPS` | 单任务最大步数 |
| `SECGO_WORKSPACE_DIR` | 工作区目录 |
| `SECGO_SKILLS_DIR` | 技能库根目录（默认项目 `skill/`） |
| `SECGO_WEB_PORT` | Web 端口（启动脚本默认 8381；可通过环境变量覆盖） |
| `SECGO_ALLOWED_COMMANDS` / `SECGO_BLOCKED_COMMANDS` | 命令白名单/黑名单（逗号分隔） |

## 项目结构

```
secgo/
├── secgo/                 # Python 包
│   ├── cli_app.py         # CLI TUI
│   ├── headless.py        # Headless JSONL 模式
│   ├── kernel/            # 交接引擎 / Agent / 技能加载 / 管线 / 命令
│   ├── model/             # LLM Provider（openai/anthropic 流式）
│   ├── runtime/           # 事件总线 / 预算 / 会话 / 工作区
│   ├── tools/             # 工具注册 / 执行 / MCP / 脚本工具
│   ├── config/            # 配置加载与向导
│   └── web/               # FastAPI + SSE + 静态前端
├── skill/                 # 100+ 安全技能库（SKILL.md + policy.json 分组）
├── settings.json          # 全部用户配置（模型/Web/限额，含密钥，gitignored）
├── settings.example.json  # 配置模板
├── config/                # 用户配置（LLMconfig.jsonc / mcp.jsonc）
├── runtime/               # 运行时数据（memory/ workspace/，自动创建）
├── cli.bat / web.bat      # 启动脚本
└── requirements.txt       # 依赖清单
```

## 安全约定

- 技能正文按**不可信文本**处理：只作知识注入，不自动执行其中的命令示例
- API Key 不入 git（`settings.json`、`config/LLMconfig.jsonc`、`config/mcp.jsonc` 已 gitignore）
- `execute_bash` 受白名单 + 黑名单约束；工作区文件禁止路径穿越
- 本项目仅用于授权测试与安全研究教育

## 依赖

```
fastapi  uvicorn  rich  prompt-toolkit  openai  anthropic  mcp  httpx
```

### 推荐安装的渗透工具

`execute_bash` 白名单覆盖以下工具，但本机未安装时 Agent 只能得到 `command not found`。
建议按需安装，避免 Agent 反复探测浪费步数：

- **Web 目录/指纹枚举**：`ffuf` `dirsearch` `gobuster` `feroxbuster` `whatweb`
- **漏洞扫描**：`nuclei` `nikto` `wpscan`
- **子域名/资产收集**：`subfinder` `httpx` `amass` `dnsx`
- **爆破**：`hydra` `hashcat` `john`

安装方式参考各自项目文档（如 `go install github.com/ffuf/ffuf/v2@latest`、
`pip install dirsearch`、`brew install whatweb` 等）。

## 致谢

本项目基于 TianGong 多 Agent 框架（Bun/TypeScript）改造，内核架构（纯函数引擎、事件总线、
local+MCP 工具统一抽象、配置分层覆盖）保持不变，整体由 Python 重新实现。
