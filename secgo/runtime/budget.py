"""Token 预算管理：估算 + Run 级额度控制。

BudgetManager 生命周期 = 一次 run_engine 执行窗口（Run）：实例在每次 run_engine
内创建，用量不跨 Run 累积；Session/任务累计 token 属于审计数据，由引擎持久化，
不在此处做硬限制。字段命名（maxTokensPerRun）必须与该真实语义一致。
"""

import json
import math
import re
from typing import Any, Dict, List

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文 ~1.5/字，英文 ~1.3/词，保底 len/6。"""
    if not text:
        return 0
    cjk = len(_CJK_RE.findall(text))
    rest = _CJK_RE.sub(" ", text)
    words = len([w for w in rest.split() if w])
    tokens = math.ceil(cjk * 1.5 + words * 1.3)
    return max(tokens, math.ceil(len(text) / 6))


def estimate_messages_tokens(messages: List[Dict[str, Any]]) -> int:
    total = 0
    for msg in messages:
        total += 4  # 每条消息的角色/格式开销
        content = msg.get("content") if isinstance(msg, dict) else ""
        if isinstance(content, str):
            total += estimate_tokens(content)
        else:
            try:
                total += estimate_tokens(json.dumps(content, ensure_ascii=False))
            except Exception:
                total += estimate_tokens(str(content))
    return total


class BudgetManager:
    def __init__(self, max_tokens: int) -> None:
        self.max_tokens = max_tokens
        self._usage: Dict[str, int] = {}

    def check_budget(self, session_id: str) -> Dict[str, Any]:
        usage = self.get_usage(session_id)
        return {"allowed": usage < self.max_tokens, "usage": usage}

    def add_usage(self, session_id: str, tokens: int) -> None:
        self._usage[session_id] = self.get_usage(session_id) + tokens

    def get_usage(self, session_id: str) -> int:
        """本次 Run 已消耗的估算 token 数（run_token_count 审计口径）。"""
        return self._usage.get(session_id, 0)
