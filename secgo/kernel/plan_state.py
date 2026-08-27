"""RePlan 决策状态机：结构化记录任务目标、失败尝试、候选策略、决策理由。

这是 SEC-GO 从「LLM 自主决定下一步」升级为「系统驱动自主决策」的核心。
每个引擎会话维护一个 PlanState 实例，在 handoff_engine 主循环中随每一步更新。
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


# ── 数据类型 ──────────────────────────────────────────────


@dataclass
class FailedAttempt:
    """一次失败的尝试记录。"""
    step: int
    agent_id: str
    tool_name: str
    error: str
    timestamp: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "error": self.error[:200],
            "timestamp": self.timestamp or time.time(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FailedAttempt":
        return cls(
            step=int(data.get("step", 0)),
            agent_id=str(data.get("agent_id", "")),
            tool_name=str(data.get("tool_name", "")),
            error=str(data.get("error", "")),
            timestamp=float(data.get("timestamp", 0.0)),
        )


@dataclass
class CandidateStrategy:
    """一个候选策略方案。"""
    id: str
    description: str           # 策略描述
    target_agent: str          # 建议由哪个 Agent 执行
    suggested_tools: List[str]  # 建议使用的工具
    risk: str                  # low / medium / high
    expected_outcome: str      # 预期产出

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "target_agent": self.target_agent,
            "suggested_tools": self.suggested_tools,
            "risk": self.risk,
            "expected_outcome": self.expected_outcome,
        }


@dataclass
class DecisionRecord:
    """一次决策的结构化记录（为什么选这个方向）。"""
    id: str
    timestamp: float
    trigger: str                # 触发原因：tool_failure / repeated_calls / no_progress / contradiction / manual
    trigger_detail: str         # 触发详情
    observation: str            # 当前观察到的状态
    candidates: List[CandidateStrategy]  # 候选策略列表
    selected: str               # 选中的策略 id
    reason: str                 # 选中理由
    rejected: List[str]         # 被拒绝的策略 id 及理由

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "trigger": self.trigger,
            "trigger_detail": self.trigger_detail,
            "observation": self.observation[:500],
            "candidates": [c.to_dict() for c in self.candidates],
            "selected": self.selected,
            "reason": self.reason,
            "rejected": self.rejected,
        }


# ── RePlan 触发条件检测 ──────────────────────────────────


REPLAN_TRIGGER_TOOL_CONSECUTIVE_FAILURES = 2   # 连续失败 N 次触发重规划
REPLAN_TRIGGER_SAME_TOOL_REPEAT = 3            # 同一工具重复调用 N 次触发
REPLAN_TRIGGER_NO_PROGRESS_STEPS = 15          # 连续 N 步无有效发现触发
REPLAN_TRIGGER_MAX_FAILURES = 5                # 累计失败 N 次触发

# failed_attempts 历史保留条数上限：只留最近 N 条（防无限增长），用于告诉 Planner「哪些路径已经失败过」
MAX_FAILED_ATTEMPTS = 50


class ReplanDetector:
    """检测是否需要触发 RePlan 的守卫。

    不直接修改 PlanState，只返回检测结果，由 handoff_engine 决定是否执行 RePlan。
    """

    def __init__(self) -> None:
        self._consecutive_failures = 0
        self._tool_call_history: List[Dict[str, Any]] = []  # [{tool_name, success, step}]
        self._last_finding_step = 0
        self._total_failures = 0

    def record_tool_call(self, tool_name: str, success: bool, step: int) -> None:
        """记录一次工具调用结果。"""
        self._tool_call_history.append({
            "tool_name": tool_name,
            "success": success,
            "step": step,
        })
        if success:
            self._consecutive_failures = 0
            self._last_finding_step = step
        else:
            self._consecutive_failures += 1
            self._total_failures += 1

    def record_handoff(self, step: int) -> None:
        """Agent 切换也算一次进展（重置无进展计数）。"""
        self._last_finding_step = step

    def last_failed_tool(self) -> Optional[str]:
        """最近一次失败的工具名（用于候选策略避开重复失败路径）。"""
        for entry in reversed(self._tool_call_history):
            if not entry.get("success"):
                return entry.get("tool_name")
        return None

    def reset_after_replan(self) -> None:
        """RePlan 后重置本轮触发状态，避免下一步因为旧 counter 再次无条件触发。

        历史失败统计保留在 PlanState.failed_attempts（审计用），此处只清触发计数器。
        """
        self._consecutive_failures = 0
        self._tool_call_history = []
        self._total_failures = 0
        self._last_finding_step = 0

    def reset_for_new_run(self) -> None:
        """新 Run 启动时清理「当前触发窗口」瞬态（与 RePlan 后重置同一语义）。

        连续失败计数、工具调用历史、无进展基准都属于触发窗口，不跨 Run 保留；
        否则上一 Run 尾部的 consecutive_failures=2 会让续跑的第一个循环瞬间再次 RePlan。
        跨 Run 的历史知识（failed_attempts / decision_history）由 PlanState 持有，不受影响。
        """
        self.reset_after_replan()

    def check(self, step: int, active_agent_id: str) -> Optional[Dict[str, Any]]:
        """检查是否需要触发 RePlan。返回触发原因字典或 None。

        优先级（高→低）：
        1. excessive_failures — 累计失败过多，全局性问题
        2. repeated_calls — 同一工具连续重复失败，工具选择问题
        3. no_progress — 长时间无进展（需 last_finding_step > 0）
        4. tool_failure — 连续失败但非重复/无进展
        """
        # 1. 累计失败过多（最高优先级）
        if self._total_failures >= REPLAN_TRIGGER_MAX_FAILURES:
            return {
                "trigger": "excessive_failures",
                "detail": (
                    f"累计工具调用失败已达 {self._total_failures} 次。"
                    "建议切换到更稳健的策略。"
                ),
            }

        # 2. 同一工具重复调用检测（优先级高于纯连续失败）
        if len(self._tool_call_history) >= REPLAN_TRIGGER_SAME_TOOL_REPEAT:
            recent = self._tool_call_history[-REPLAN_TRIGGER_SAME_TOOL_REPEAT:]
            names = [t["tool_name"] for t in recent]
            if len(set(names)) == 1 and not any(t["success"] for t in recent):
                return {
                    "trigger": "repeated_calls",
                    "detail": (
                        f"工具 '{names[0]}' 连续调用 {REPLAN_TRIGGER_SAME_TOOL_REPEAT} 次均未成功。"
                        "建议更换策略或工具。"
                    ),
                }

        # 3. 无进展检测（需有历史进展作为基准，避免刚启动就触发）
        if self._last_finding_step > 0:
            steps_since_finding = step - self._last_finding_step
            if steps_since_finding >= REPLAN_TRIGGER_NO_PROGRESS_STEPS:
                return {
                    "trigger": "no_progress",
                    "detail": (
                        f"已连续 {steps_since_finding} 步无有效发现（自第 {self._last_finding_step} 步起）。"
                        "建议重新规划搜索方向。"
                    ),
                }

        # 4. 连续失败检测（在其他触发条件之后）
        if self._consecutive_failures >= REPLAN_TRIGGER_TOOL_CONSECUTIVE_FAILURES:
            return {
                "trigger": "tool_failure",
                "detail": (
                    f"Agent '{active_agent_id}' 连续 {self._consecutive_failures} 次工具调用失败。"
                    f"累计失败 {self._total_failures} 次。"
                ),
            }

        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "consecutive_failures": self._consecutive_failures,
            "total_failures": self._total_failures,
            "last_finding_step": self._last_finding_step,
            "tool_call_history": self._tool_call_history[-10:],  # 只保留最近 10 条
        }


# ── PlanState 主类 ───────────────────────────────────────


class PlanState:
    """任务计划状态机：记录目标、当前计划、失败历史、决策链。

    RePlan 计数拆分两层（与 step 的 run/total 拆分同语义）：
    - run_replan_count：当前这一次 run_engine 已使用多少次 RePlan（每次 Run 从 0 开始，
      用于 maxReplansPerRun 安全额度，不因上一次 Run 耗尽而让新 Run 失去权限）；
    - total_replan_count：整个任务/Session 历史累计发生多少次 RePlan（审计 / Timeline /
      Benchmark 用，持久化；replan_count 属性保留为 total 的兼容别名）。

    用法：
        plan = PlanState(goal="渗透测试 target.com")
        plan.set_plan("1. 信息收集 2. 漏洞扫描 3. 漏洞利用")
        plan.add_failure("operator", "nmap", "Connection refused")
        decision = plan.trigger_replan("tool_failure", "...")
        # decision 包含候选策略和选择理由
    """

    def __init__(self, goal: str = "") -> None:
        self.goal = goal
        self.current_plan: str = ""
        self.success_criteria: List[str] = []
        self.failed_attempts: List[FailedAttempt] = []
        self.run_replan_count: int = 0
        self.total_replan_count: int = 0
        self.decision_history: List[DecisionRecord] = []
        self.detector = ReplanDetector()
        self._candidate_index = 0
        self._last_plan_update_step = 0
        # 达到 maxReplansPerRun 后的收尾指引只注入一次，避免长尾失败步骤反复追加重复提示。
        # 属于 Run 临时状态：每次新 Run 必须重置为 False，否则续跑后触发条件会被静默吞掉
        self.exhaustion_notice_injected: bool = False

    @property
    def replan_count(self) -> int:
        """兼容别名：历史上只有单一计数，现语义为「累计总次数」。"""
        return self.total_replan_count

    def set_plan(self, plan: str, criteria: Optional[List[str]] = None) -> None:
        """设置当前执行计划。"""
        self.current_plan = plan
        if criteria:
            self.success_criteria = criteria

    def add_failure(self, agent_id: str, tool_name: str, error: str, step: int = 0) -> None:
        """记录一次失败尝试。超过 MAX_FAILED_ATTEMPTS 时只保留最近 N 条。"""
        self.failed_attempts.append(FailedAttempt(
            step=step,
            agent_id=agent_id,
            tool_name=tool_name,
            error=error,
            timestamp=time.time(),
        ))
        if len(self.failed_attempts) > MAX_FAILED_ATTEMPTS:
            del self.failed_attempts[:-MAX_FAILED_ATTEMPTS]

    def reset_for_new_run(self) -> None:
        """新 Run 启动：重新获得 Run 级执行额度，但不丢失任务历史。

        - 重置：run_replan_count=0、exhaustion_notice_injected=False、detector 触发窗口；
        - 保留：goal、current_plan、success_criteria、failed_attempts、decision_history。
        """
        self.run_replan_count = 0
        self.exhaustion_notice_injected = False
        self.detector.reset_for_new_run()

    def generate_candidates(self, trigger: str, detail: str, active_agent_id: str) -> List[CandidateStrategy]:
        """根据触发原因生成候选策略。

        生成 2-3 个不同方向的候选策略，供后续选择。
        """
        self._candidate_index += 1
        candidates: List[CandidateStrategy] = []

        if trigger == "tool_failure":
            candidates = [
                CandidateStrategy(
                    id=f"c{self._candidate_index}-a",
                    description="更换替代工具：尝试使用功能相似的其他工具完成相同目标",
                    target_agent=active_agent_id,
                    suggested_tools=[],
                    risk="low",
                    expected_outcome="相同检测目标，不同工具路径",
                ),
                CandidateStrategy(
                    id=f"c{self._candidate_index}-b",
                    description="切换 Agent 重新规划：handoff 给 Planner 重新制定策略",
                    target_agent="planner",
                    suggested_tools=[],
                    risk="medium",
                    expected_outcome="重新规划执行路径",
                ),
            ]
        elif trigger == "repeated_calls":
            candidates = [
                CandidateStrategy(
                    id=f"c{self._candidate_index}-a",
                    description="更换目标方法：放弃当前无效工具，选择不同技术路线",
                    target_agent=active_agent_id,
                    suggested_tools=[],
                    risk="medium",
                    expected_outcome="新方法可能发现此前遗漏的面",
                ),
                CandidateStrategy(
                    id=f"c{self._candidate_index}-b",
                    description="扩大搜索范围：先做更广泛的信息收集，再聚焦",
                    target_agent="research",
                    suggested_tools=["web_search"],
                    risk="low",
                    expected_outcome="获取更多上下文信息",
                ),
            ]
        elif trigger == "no_progress":
            candidates = [
                CandidateStrategy(
                    id=f"c{self._candidate_index}-a",
                    description="回溯方案：回顾已有发现，重新评估攻击面",
                    target_agent="planner",
                    suggested_tools=[],
                    risk="low",
                    expected_outcome="从已有信息中挖掘新方向",
                ),
                CandidateStrategy(
                    id=f"c{self._candidate_index}-b",
                    description="外部情报搜索：通过 Research Agent 搜索相关漏洞情报",
                    target_agent="research",
                    suggested_tools=["web_search"],
                    risk="medium",
                    expected_outcome="获取外部情报指导下一步",
                ),
                CandidateStrategy(
                    id=f"c{self._candidate_index}-c",
                    description="更换攻击面：切换到此前未探索的入口点",
                    target_agent="operator",
                    suggested_tools=[],
                    risk="high",
                    expected_outcome="可能发现此前忽略的攻击面",
                ),
            ]
        else:  # excessive_failures / manual
            candidates = [
                CandidateStrategy(
                    id=f"c{self._candidate_index}-a",
                    description="回退到 Planner 重新评估整体策略",
                    target_agent="planner",
                    suggested_tools=[],
                    risk="medium",
                    expected_outcome="更稳健的策略调整",
                ),
                CandidateStrategy(
                    id=f"c{self._candidate_index}-b",
                    description="缩小目标范围，聚焦已验证可达的面",
                    target_agent=active_agent_id,
                    suggested_tools=[],
                    risk="low",
                    expected_outcome="在可控范围内持续推进",
                ),
            ]

        return candidates

    def select_strategy(self, candidates: List[CandidateStrategy], trigger: str,
                        active_agent_id: str = "", failed_tool: Optional[str] = None) -> Tuple[CandidateStrategy, List[str]]:
        """从候选策略中选择最佳方案。

        选择依据与触发原因真正相关（而非无条件 candidates[0]）：
        - 优先低风险；
        - 避开刚刚失败的同一工具；
        - 当前 Agent 已连续失败时倾向切换 Agent；
        - excessive_failures 时更倾向回退 Planner；
        - no_progress 时倾向换一个 Agent 获取信息增益。
        """
        if not candidates:
            raise ValueError("No candidates to select from")

        def score(candidate: CandidateStrategy) -> int:
            points = 0
            if candidate.risk == "low":
                points += 2
            elif candidate.risk == "medium":
                points += 1
            if failed_tool and failed_tool in candidate.suggested_tools:
                points -= 3
            if candidate.target_agent == active_agent_id and trigger in ("tool_failure", "repeated_calls", "excessive_failures"):
                points -= 1
            if trigger == "excessive_failures" and candidate.target_agent == "planner":
                points += 2
            if trigger == "no_progress" and candidate.target_agent != active_agent_id:
                points += 1
            return points

        # 原始下标作为稳定 tie-break：分数相同时保留候选声明顺序
        indexed = list(enumerate(candidates))
        ranked = sorted(indexed, key=lambda pair: (score(pair[1]), -pair[0]), reverse=True)
        selected = candidates[ranked[0][0]]
        rejected = [f"{c.id}: {c.description}" for c in candidates if c.id != selected.id]
        return selected, rejected

    def trigger_replan(self, trigger: str, trigger_detail: str, active_agent_id: str) -> DecisionRecord:
        """触发一次完整的 RePlan 流程：生成候选 → 选择 → 记录。"""
        self.run_replan_count += 1
        self.total_replan_count += 1
        previous_plan = self.current_plan  # 保存「原计划」，绝不在记录后再被新计划覆盖
        failed_tool = self.detector.last_failed_tool()
        candidates = self.generate_candidates(trigger, trigger_detail, active_agent_id)
        selected, rejected = self.select_strategy(candidates, trigger, active_agent_id, failed_tool)

        observation = (
            f"原计划: {previous_plan[:100] or '无'}\n"
            f"已失败尝试: {len(self.failed_attempts)} 次\n"
            f"已重规划次数: {self.total_replan_count - 1}"
        )

        decision = DecisionRecord(
            id=f"decision-{uuid.uuid4().hex[:8]}",
            timestamp=time.time(),
            trigger=trigger,
            trigger_detail=trigger_detail,
            observation=observation,
            candidates=candidates,
            selected=selected.id,
            reason=f"选择 '{selected.description}'（风险: {selected.risk}，预期: {selected.expected_outcome}）",
            rejected=rejected,
        )
        self.decision_history.append(decision)

        # 更新计划：current_plan 只保存「新计划」；原计划已保留在 decision.observation
        # 编号使用累计总次数，跨 Run 连续（Run 1: #1 #2，Run 2: #3 ...）
        self.current_plan = (
            f"[RePlan #{self.total_replan_count}] {selected.description}\n"
            f"触发: {trigger} - {trigger_detail[:80]}"
        )

        # 关键：RePlan 后重置本轮触发器状态，避免下一步因为旧 counter 再次无条件触发
        self.detector.reset_after_replan()

        return decision

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "current_plan": self.current_plan,
            "success_criteria": self.success_criteria,
            "failed_attempts": [f.to_dict() for f in self.failed_attempts[-10:]],
            "replan_count": self.total_replan_count,
            "run_replan_count": self.run_replan_count,
            "total_replan_count": self.total_replan_count,
            "decision_history": [d.to_dict() for d in self.decision_history[-20:]],
            "detector": self.detector.to_dict(),
            "exhaustion_notice_injected": self.exhaustion_notice_injected,
        }

    def to_serializable(self) -> Dict[str, Any]:
        """可序列化版本（存 session state）。

        持久化内容（Task State 层）：
        - goal / current_plan / success_criteria / decision_history / total_replan_count；
        - failed_attempts：跨 Run 保留的历史失败知识（Planner 据此避开旧路径），截断到最近 MAX 条；
        - replan_count：total 的兼容镜像（旧版本读取字段），非 Run 级额度。
        不持久化（Run 临时状态）：run_replan_count、exhaustion_notice_injected、detector 触发窗口。
        """
        return {
            "goal": self.goal,
            "current_plan": self.current_plan,
            "success_criteria": list(self.success_criteria),
            "failed_attempts": [
                f.to_dict() for f in self.failed_attempts[-MAX_FAILED_ATTEMPTS:]
            ],
            "run_replan_count": 0,  # Run 级计数不落库；写 0 防御性声明语义
            "total_replan_count": self.total_replan_count,
            "replan_count": self.total_replan_count,  # 兼容镜像：旧读者读 total
            "decision_history": [d.to_dict() for d in self.decision_history[-20:]],
            "exhaustion_notice_injected": False,  # Run 临时状态，新 Run 一律重新允许
        }

    @classmethod
    def from_serializable(cls, data: Dict[str, Any]) -> PlanState:
        """从 session state 恢复 PlanState。

        - total_replan_count / failed_attempts / decision_history / plan 恢复为 Task State；
        - run_replan_count 恒从 0 开始（旧数据中的 replan_count 亦视为累计值兜底）；
        - exhaustion_notice_injected 恒为 False（Run 临时状态，绝不跨 Run 继承）；
        - detector 触发窗口（连续失败等瞬态）不再恢复——新 Run 从干净窗口开始，
          避免「继续」后的第一个循环因上一 Run 尾部状态瞬间误触发 RePlan。
        """
        state = cls(goal=data.get("goal", ""))
        state.current_plan = data.get("current_plan", "")
        state.success_criteria = list(data.get("success_criteria", []))
        state.total_replan_count = int(
            data.get("total_replan_count", data.get("replan_count", 0)) or 0
        )
        state.run_replan_count = 0
        state.exhaustion_notice_injected = False
        # 恢复失败尝试历史（跨 Run 保留的「历史知识」；上限内取最新）
        restored_failures = []
        for f in data.get("failed_attempts") or []:
            if isinstance(f, dict):
                try:
                    restored_failures.append(FailedAttempt.from_dict(f))
                except Exception:
                    continue
        state.failed_attempts = restored_failures[-MAX_FAILED_ATTEMPTS:]
        # detector 保持全新实例：瞬态触发窗口不跨 Run 继承
        # 恢复决策历史（只保留摘要，不保留完整对象）
        for d in data.get("decision_history", []):
            state.decision_history.append(DecisionRecord(
                id=d.get("id", ""),
                timestamp=d.get("timestamp", 0),
                trigger=d.get("trigger", ""),
                trigger_detail=d.get("trigger_detail", ""),
                observation=d.get("observation", ""),
                candidates=[],
                selected=d.get("selected", ""),
                reason=d.get("reason", ""),
                rejected=list(d.get("rejected", [])),
            ))
        return state