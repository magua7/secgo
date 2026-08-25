# SEC-GO 设置页与右侧执行面板定点修复设计

## 目标与边界

本轮只修复模型配置链路、Planner 开关、右侧执行面板显隐和历史执行回放。保留现有 React + Vite + TypeScript 架构、设置导航、中间会话视觉、主题与三栏布局。除模型配置读写契约外，不改动其他后端功能。

## 模型配置：`settings.json` 是唯一事实来源

- 默认模型与 Planner 都由用户填写的 `provider`、`base_url`、`model`、`api_key` 决定。
- Provider 是可编辑、可搜索的组合输入：可选择预设，也可填写任意供应商名称。
- Provider、Base URL、Model ID、API Key 是四个相互独立的字段；修改 Provider 不清空或推断其他字段。
- 保存成功后，四个字段直接写入 `settings.json`；再次读取设置时由后端原样返回 Provider，不使用浏览器本地覆盖值。
- 自定义 Provider 默认采用 OpenAI-compatible 调用协议；明确为 `anthropic` 时采用 Anthropic 协议；`ollama` 与 `lm-studio` 保留现有本地兼容处理。
- 后端不再把未知 Provider 强制改写为 `openai`。
- 默认模型仍使用引擎内部订阅槽 `coding`，但槽名不是固定供应商或模型；其内容完全来自设置。
- Planner 独立配置使用语义化订阅槽 `planner`，不再固定写入名为 `glm` 的订阅。关闭独立模型时 Planner 复用默认 `coding` 配置。
- 读取旧配置时兼容既有 `agents.planner.subscription = "glm"`，保存后迁移到 `planner` 槽；不影响其他 Agent。
- API Key 掩码状态与 API Key 标签同行展示。保存配置仍要求重新输入密钥，避免后端向浏览器返回明文。
- 最小请求校验按协议执行：OpenAI-compatible 请求 `/chat/completions`；Anthropic 使用其对应消息接口。关闭校验时只保存，不发外部验证请求。

## Planner 开关

- 使用标准 Toggle 视觉和语义。
- 只有开关控件本体响应点击；标题、说明及整行空白不切换状态。
- 关闭时折叠 Planner 表单并表示复用默认模型；开启时显示独立四字段配置。

## 右侧执行面板

- 首次无偏好时默认展开；状态继续存入现有 `secgo.rightPanel`。
- 只有右侧边缘把手能改变展开/折叠状态。
- 新建任务、发送消息、直接回复、Agent 启动或结束、切换历史会话都不得自动改变面板宽度。
- “查看执行轨迹”只选择对应轨迹和标签页，不自动展开隐藏面板。
- 新会话与直接回复显示统一空状态；实时 Agent 任务保持当前阶段、轨迹、证据与资源能力。

## 历史 Agent Task 回放

- 历史回放为只读，不伪造执行时间、Agent 身份、阶段或完成状态。
- 已保存文本按系统提示、Agent 文本、交接与工具输出形成摘要时间线。
- 工具输出优先解析可识别的 JSON 包装；仅对受控文本还原字面量 `\n`，始终按纯文本渲染。
- 原始输出放入可折叠容器，单项最大高度保持在 220–300px，内部滚动。
- 证据数量未知时省略统计，不显示 `0 Evidence`。
- 执行轨迹、证据和资源缺失状态统一使用 `PanelEmptyState`。

## 测试与验收

- 前端组件测试覆盖自定义 Provider、预设选择不重置其他字段、Planner Toggle 点击边界、API Key 状态位置。
- 后端测试覆盖任意 Provider 原样保存/读取、默认与 Planner 模型路由、旧 `glm` Planner 配置迁移、协议校验分支。
- Workspace 测试覆盖右栏默认值、持久化以及所有会话事件均不自动改变显隐。
- 历史适配器与 RightPanel 测试覆盖换行规范化、原始输出折叠、未知证据数省略和统一空状态。
- 最终运行前后端测试、TypeScript 类型检查和生产构建。
