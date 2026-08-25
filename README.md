# SEC-GO

**SEC-GO** 是一套面向网络安全任务的多智能体协同分析与执行平台。项目针对传统安全工具链分散、
复杂任务依赖人工编排、执行过程难以追踪、分析结果难以沉淀等问题，自主研发了从任务规划、专业研判、
工具执行到证据归档的完整技术链路，并提供 Web 与 CLI 两种交互形态。

平台以 Python 为核心实现，内置 **100+ 安全技能工作流**，支持本地安全工具与 MCP 工具统一接入，
能够在授权安全测试、代码审计、漏洞分析、CTF 训练和应急研判等场景中完成多阶段任务协作。

## 作品定位

SEC-GO 不是单一的对话机器人或扫描器封装，而是一套具备任务状态、角色分工、工具调度、过程追踪、
预算约束和会话恢复能力的安全智能体运行系统。平台将安全人员的分析方法结构化为可加载技能，
再由多个专业 Agent 根据任务上下文动态协作，使大模型从“给出建议”进一步走向“按流程执行并保留证据”。

## 自主创新

- **多智能体动态交接机制**：Planner 根据任务状态进行拆解和调度，Research、Builder、Operator 分别承担信息研判、方案构建和工具执行，通过显式 handoff 完成上下文可控的角色切换
- **安全技能工作流引擎**：将漏洞分析方法、验证步骤和质量约束沉淀为结构化技能，由 Agent 按任务信号检索和加载，降低通用模型在专业安全场景中的随机性
- **统一工具执行层**：以一致接口管理本地脚本、安全工具和 MCP 服务，使工具发现、参数调用、结果回传与执行记录能够进入同一任务链路
- **全过程可观测机制**：通过事件总线和 SSE 实时呈现 Agent 切换、思考进度、工具调用、TODO 状态和最终结果，避免复杂任务成为不可解释的黑盒
- **可持续任务状态管理**：使用 SQLite 保存会话、消息、任务状态与执行上下文，支持历史恢复、上下文压缩和多轮任务延续
- **面向安全场景的运行约束**：提供 Token 与步骤预算、命令白名单和黑名单、受控工作区、附件限制等机制，在执行能力与运行边界之间建立约束

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

## 系统架构

```text
用户任务
   │
   ▼
Planner 任务理解与规划
   │
   ├── Research  信息检索与安全研判
   ├── Builder   脚本、PoC 与方案构建
   └── Operator  本地工具与 MCP 工具执行
   │
   ▼
事件总线 → Web/SSE 与 CLI 实时呈现
   │
   ▼
会话状态、执行证据与任务结果持久化
```

## 应用价值

- **提升复杂安全任务的执行效率**：将任务拆解、技能选择、工具调用和结果整理纳入统一流程，减少重复操作
- **降低专业工作流使用门槛**：把安全专家的方法沉淀为可复用技能，使不同经验水平的使用者能够按规范执行任务
- **增强过程可信度**：完整展示任务进度、调用记录和执行结果，便于复核、演示和后续审计
- **支持持续扩展**：技能、模型和工具均采用可扩展设计，可根据比赛场景、实验环境或实际业务继续增加能力

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
2. 配置 `settings.json`（项目提供 DeepSeek 配置模板，API Key 需由使用者填写；也可删除配置后运行向导）：

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

3. 双击 `cli.bat`（或 `web.bat`）——脚本会自动安装依赖；`settings.json` 缺失时启动配置向导，Web 访问认证默认启用
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
  - `web` — Web 访问认证与端口：登录校验、`secret_key`（Cookie 签名）、`port`
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
`llm` / `subscriptions` / `agents` 节；退出登录不删除配置。赛事演示环境的访问凭据由项目方随交付材料单独提供。

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

## 作品说明

SEC-GO 由 SEC-GO 团队自主设计与研发，覆盖多智能体调度、安全技能引擎、工具执行、状态管理、
Web 交互和 CLI 交互等核心模块。项目将继续围绕安全任务评测、技能质量、执行可靠性和真实场景适配进行迭代。
