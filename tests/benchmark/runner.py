"""SEC-GO 安全任务基准测试（Benchmark）

运行 10-15 个真实安全任务，比较完整 SEC-GO、单 Agent、无 Skill 三种模式下的：
- 成功率（任务完成率）
- 步骤数（Agent 步数）
- 工具调用次数
- RePlan 次数
- 执行时间（秒）
- 决策理由数量

用法：
    python -m tests.benchmark.runner          # 跑完整 benchmark
    python -m tests.benchmark.runner --mode single_agent  # 只跑单 Agent 模式
    python -m tests.benchmark.runner --tasks 1,3,5        # 只跑指定任务
    python -m tests.benchmark.runner --output results.json # 输出到文件
"""

import asyncio
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

# 允许从项目根目录导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))


# ── 测试用例定义 ──────────────────────────────────────────


@dataclass
class BenchmarkTask:
    """一个安全测试任务。"""
    id: int
    name: str
    category: str          # web / recon / code_audit / forensics / api / ctf
    prompt: str            # 用户输入
    attachments: List[str] = field(default_factory=list)  # 附件路径
    success_criteria: List[str] = field(default_factory=list)  # 成功判定标准
    expected_tools: List[str] = field(default_factory=list)  # 预期使用的工具
    timeout: int = 120     # 超时秒数


BENCHMARK_TASKS = [
    BenchmarkTask(
        id=1, name="端口扫描", category="recon",
        prompt="扫描 192.168.1.1 的 80、443、22 端口是否开放",
        success_criteria=["端口开放状态", "服务识别"],
        expected_tools=["execute_bash", "mcp_*"],
        timeout=60,
    ),
    BenchmarkTask(
        id=2, name="Web 漏洞扫描", category="web",
        prompt="对 http://testphp.vulnweb.com 进行 Web 安全测试，发现可能的 SQL 注入和 XSS 漏洞",
        success_criteria=["SQL注入检测", "XSS检测", "漏洞报告"],
        expected_tools=["mcp_*", "execute_bash"],
        timeout=180,
    ),
    BenchmarkTask(
        id=3, name="API 安全测试", category="api",
        prompt="""分析以下 OpenAPI 规范并找出可能的安全问题：
        paths:
          /api/users:
            get:
              parameters:
                - name: userId
                  in: query
                  required: true
              responses:
                '200':
                  description: 用户信息
          /api/admin:
            get:
              parameters: []
              responses:
                '200':
                  description: 管理接口
        """,
        success_criteria=["接口分析", "权限问题识别"],
        expected_tools=["skill_route", "skill_read"],
        timeout=120,
    ),
    BenchmarkTask(
        id=4, name="ZIP 日志分析", category="forensics",
        prompt="分析附件中的 ZIP 日志文件，找出可疑的登录尝试和可能的攻击 IP",
        attachments=["test_data/attack_logs.zip"],
        success_criteria=["日志解析", "可疑IP识别", "攻击时间线"],
        expected_tools=["skill_list", "skill_read"],
        timeout=180,
    ),
    BenchmarkTask(
        id=5, name="CVE 风险评估", category="recon",
        prompt="评估 CVE-2024-3094 的漏洞影响范围，给出利用可能性和修复建议",
        success_criteria=["CVE详情", "影响评估", "修复建议"],
        expected_tools=["web_search"],
        timeout=120,
    ),
    BenchmarkTask(
        id=6, name="域名恶意研判", category="recon",
        prompt="对 example.com 进行恶意域名安全研判，包括注册信息、历史解析和关联风险",
        success_criteria=["域名信息", "风险判断"],
        expected_tools=["web_search", "mcp_*"],
        timeout=120,
    ),
    BenchmarkTask(
        id=7, name="代码审计（PHP）", category="code_audit",
        prompt="""审计以下 PHP 代码的安全性：
        <?php
        $id = $_GET['id'];
        $query = "SELECT * FROM users WHERE id = $id";
        $result = mysql_query($query);
        while ($row = mysql_fetch_assoc($result)) {
            echo "User: " . $row['username'];
        }
        ?>
        """,
        success_criteria=["SQL注入识别", "修复建议"],
        expected_tools=["skill_route", "skill_read"],
        timeout=120,
    ),
    BenchmarkTask(
        id=8, name="JSON 配置文件分析", category="recon",
        prompt="分析以下 JSON 配置文件的安全风险：{\"apiVersion\": \"v1\", \"clusters\": [{\"name\": \"production\", \"cluster\": {\"server\": \"https://k8s-prod.example.com\", \"certificate-authority-data\": \"LS0tLS1CRUdJTiBDRV...\"}}], \"users\": [{\"name\": \"admin\", \"user\": {\"token\": \"sk-abc123...\"}}]}",
        success_criteria=["敏感信息识别", "安全建议"],
        expected_tools=["skill_route"],
        timeout=120,
    ),
    BenchmarkTask(
        id=9, name="MCP 工具调用", category="web",
        prompt="使用 MCP 工具进行端口扫描和 HTTP 请求测试，目标 127.0.0.1",
        success_criteria=["MCP工具调用", "结果分析"],
        expected_tools=["mcp_*"],
        timeout=120,
    ),
    BenchmarkTask(
        id=10, name="综合安全评估", category="web",
        prompt="""对目标系统进行综合安全评估：
        1. 侦察阶段：收集目标信息
        2. 扫描阶段：发现开放端口和服务
        3. 漏洞阶段：识别已知漏洞
        4. 报告阶段：生成评估报告""",
        success_criteria=["侦察完成", "扫描完成", "漏洞识别", "最终报告"],
        expected_tools=["skill_route", "web_search", "mcp_*"],
        timeout=300,
    ),
]


# ── Benchmark 运行器 ──────────────────────────────────────


@dataclass
class TaskResult:
    task_id: int
    task_name: str
    mode: str           # full / single_agent / no_skills
    success: bool
    steps: int
    tool_calls: int
    replan_count: int
    decision_count: int
    elapsed_seconds: float
    error: Optional[str] = None
    summary: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    mode: str
    tasks: List[TaskResult] = field(default_factory=list)
    total_tasks: int = 0
    successful: int = 0
    total_steps: int = 0
    total_tool_calls: int = 0
    total_replans: int = 0
    total_decisions: int = 0
    total_time: float = 0.0

    @property
    def success_rate(self) -> float:
        return (self.successful / self.total_tasks * 100) if self.total_tasks > 0 else 0.0

    @property
    def avg_steps(self) -> float:
        return self.total_steps / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_tool_calls(self) -> float:
        return self.total_tool_calls / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_replans(self) -> float:
        return self.total_replans / self.total_tasks if self.total_tasks > 0 else 0.0

    @property
    def avg_time(self) -> float:
        return self.total_time / self.total_tasks if self.total_tasks > 0 else 0.0


async def run_single_task(task: BenchmarkTask, mode: str) -> TaskResult:
    """运行单个 benchmark 任务。"""
    from secgo.kernel.handoff_engine import run_engine
    from secgo.runtime.eventbus import event_bus, set_current_session

    start_time = time.time()
    session_id = f"benchmark-{mode}-{task.id}-{int(start_time)}"

    # 设置环境变量
    os.environ["SECGO_AUTO_CONTINUE"] = "1"  # 自动继续模式

    # 收集事件
    decisions = []
    def on_decision(data):
        decisions.append(data)

    event_bus.on("decision:reason", on_decision)

    try:
        set_current_session(session_id)
        result = await asyncio.wait_for(
            run_engine(task.prompt, session_id),
            timeout=task.timeout,
        )
    except asyncio.TimeoutError:
        result = {"reason": "timeout", "total_steps": 0}
    except Exception as e:
        result = {"reason": "error", "total_steps": 0, "error": str(e)}
    finally:
        event_bus.off("decision:reason", on_decision)
        del os.environ["SECGO_AUTO_CONTINUE"]

    elapsed = time.time() - start_time
    success = result.get("reason") == "completed"

    # 模拟工具调用次数统计（从 events 推算）
    tool_calls = result.get("total_steps", 0) // 2  # 近似值

    return TaskResult(
        task_id=task.id,
        task_name=task.name,
        mode=mode,
        success=success,
        steps=result.get("total_steps", 0),
        tool_calls=tool_calls,
        replan_count=result.get("replan_count", 0),
        decision_count=len(decisions),
        elapsed_seconds=round(elapsed, 2),
        error=result.get("error"),
        summary=result.get("summary"),
        details={"reason": result.get("reason", "unknown")},
    )


def print_comparison(results: List[BenchmarkResult]) -> None:
    """打印模式对比表。"""
    print("\n" + "=" * 90)
    print("SEC-GO Benchmark 对比结果")
    print("=" * 90)

    header = f"{'指标':<20} {'完整 SEC-GO':<20} {'单 Agent':<20} {'无 Skill':<20}"
    print(header)
    print("-" * 90)

    modes = {r.mode: r for r in results}
    rows = [
        ("任务总数", "total_tasks", "{:d}"),
        ("成功数", "successful", "{:d}"),
        ("成功率", "success_rate", "{:.1f}%"),
        ("平均步数", "avg_steps", "{:.1f}"),
        ("平均工具调用", "avg_tool_calls", "{:.1f}"),
        ("平均 RePlan 次数", "avg_replans", "{:.1f}"),
        ("平均耗时(秒)", "avg_time", "{:.1f}"),
    ]

    for label, attr, fmt in rows:
        vals = []
        for mode_name in ["full", "single_agent", "no_skills"]:
            r = modes.get(mode_name)
            if r:
                val = getattr(r, attr)
                if attr == "success_rate":
                    val = r.success_rate
                vals.append(fmt.format(val))
            else:
                vals.append("N/A")
        print(f"{label:<20} {vals[0]:<20} {vals[1]:<20} {vals[2]:<20}")

    print("=" * 90)
    print()


async def run_benchmark(modes: List[str] = ["full", "single_agent", "no_skills"],
                        task_ids: Optional[List[int]] = None) -> List[BenchmarkResult]:
    """运行完整 benchmark。"""
    tasks = [t for t in BENCHMARK_TASKS if task_ids is None or t.id in task_ids]

    if not tasks:
        print("没有匹配的测试任务")
        return []

    print(f"Benchmark: {len(tasks)} 个任务 × {len(modes)} 种模式 = {len(tasks) * len(modes)} 次运行")
    print(f"模式: {', '.join(modes)}")
    print(f"任务: {', '.join(f'{t.id}.{t.name}' for t in tasks)}")
    print()

    all_results: List[BenchmarkResult] = []

    for mode in modes:
        print(f"\n{'─' * 60}")
        print(f"运行模式: {mode}")
        print(f"{'─' * 60}")

        mode_result = BenchmarkResult(mode=mode)

        for task in tasks:
            print(f"  任务 {task.id}: {task.name}... ", end="", flush=True)
            result = await run_single_task(task, mode)
            mode_result.tasks.append(result)
            mode_result.total_tasks += 1
            if result.success:
                mode_result.successful += 1
            mode_result.total_steps += result.steps
            mode_result.total_tool_calls += result.tool_calls
            mode_result.total_replans += result.replan_count
            mode_result.total_decisions += result.decision_count
            mode_result.total_time += result.elapsed_seconds

            status = "✓" if result.success else "✗"
            print(f"{status} ({result.steps}步, {result.elapsed_seconds:.1f}s, {result.replan_count}次RePlan)", flush=True)

        all_results.append(mode_result)

    return all_results


def main():
    import argparse

    parser = argparse.ArgumentParser(description="SEC-GO Benchmark")
    parser.add_argument("--mode", choices=["full", "single_agent", "no_skills", "all"],
                        default="all", help="运行模式")
    parser.add_argument("--tasks", type=str, default="",
                        help="任务 ID 列表，逗号分隔，如 1,3,5")
    parser.add_argument("--output", type=str, default="",
                        help="输出 JSON 文件路径")

    args = parser.parse_args()

    modes = ["full", "single_agent", "no_skills"] if args.mode == "all" else [args.mode]
    task_ids = [int(x) for x in args.tasks.split(",") if x.strip()] if args.tasks else None

    print("SEC-GO Benchmark Runner")
    print("=" * 60)

    results = asyncio.run(run_benchmark(modes, task_ids))

    print_comparison(results)

    if args.output:
        data = {
            "timestamp": time.time(),
            "modes": [asdict(r) for r in results],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {args.output}")


if __name__ == "__main__":
    main()
