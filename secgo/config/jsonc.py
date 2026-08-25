"""轻量 JSONC 工具：支持注释的 JSON 解析与序列化，无外部依赖。"""

import json
from typing import Any, Optional


def strip_jsonc(text: str) -> str:
    """逐字符扫描，剥离行注释与块注释，跳过字符串字面量内部。"""
    result: list[str] = []
    i = 0
    n = len(text)

    while i < n:
        ch = text[i]

        if ch in ('"', "'"):
            quote = ch
            result.append(ch)
            i += 1
            while i < n:
                c = text[i]
                result.append(c)
                if c == "\\" and i + 1 < n:
                    result.append(text[i + 1])
                    i += 2
                    continue
                i += 1
                if c == quote:
                    break
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] != "\n":
                i += 1
            continue

        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i < n and not (text[i] == "*" and i + 1 < n and text[i + 1] == "/"):
                i += 1
            if i >= n:
                break
            i += 2
            continue

        result.append(ch)
        i += 1

    return "".join(result)


def parse_jsonc(text: str) -> Any:
    stripped = strip_jsonc(text)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as err:
        raise ValueError(f"JSONC parse failed: {err}") from err


def stringify_jsonc(obj: Any, header_comment: Optional[str] = None) -> str:
    body = json.dumps(obj, ensure_ascii=False, indent=2)
    if header_comment:
        lines = "\n".join(f"// {line}" for line in header_comment.split("\n"))
        return f"{lines}\n{body}"
    return body
