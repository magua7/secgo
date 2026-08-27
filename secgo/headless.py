"""SEC-GO Headless 模式：JSON Lines 输出（不在交付范围，保留供管道使用）。

用法:
  python -m secgo.headless "任务描述"
  echo "任务描述" | python -m secgo.headless
"""

import asyncio
import json
import os
import sys
import time
from typing import Any, Dict

from .kernel.handoff_engine import run_engine
from .runtime.eventbus import event_bus


def emit(event: str, data: Dict[str, Any]) -> None:
    line = json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "event": event, **data}, ensure_ascii=False)
    print(line, flush=True)


EVENT_MAP = {
    "engine:start": "engine:start",
    "agent:thinking": "agent:thinking",
    "agent:switch": "agent:switch",
    "tool:call": "tool:call",
    "tool:result": "tool:result",
    "engine:text": "engine:text",
    "engine:error": "engine:error",
    "engine:end": "engine:end",
    "llm:stream": "llm:stream",
    "tool:stream-start": "tool:stream-start",
    "tool:stream-end": "tool:stream-end",
    "budget:exceeded": "budget:exceeded",
}

_handlers = []


def _bind() -> None:
    for event, label in EVENT_MAP.items():
        def make_handler(label: str = label):
            def handler(data: Dict[str, Any]) -> None:
                emit(label, data)
            return handler

        handler = make_handler()
        _handlers.append((event, handler))
        event_bus.on(event, handler)


async def _main() -> None:
    _bind()
    args = sys.argv[1:]
    if args:
        user_input = " ".join(args)
        emit("headless:init", {"mode": "args", "input": user_input})
        await run_engine(user_input)
    else:
        emit("headless:init", {"mode": "stdin"})
        chunks = []
        for line in sys.stdin:
            chunks.append(line)
        user_input = "".join(chunks).strip()
        if user_input:
            await run_engine(user_input)
    emit("headless:exit", {})


def main() -> None:
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    # headless 自动继续
    os.environ.setdefault("SECGO_AUTO_CONTINUE", "1")
    try:
        asyncio.run(_main())
    except Exception as err:
        emit("headless:fatal", {"error": str(err)})
        sys.exit(1)


if __name__ == "__main__":
    main()
