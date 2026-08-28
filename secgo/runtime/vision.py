"""图片视觉（Vision）附件预处理能力。

它不是第五个 Agent，而是附件预处理能力：把用户上传的图片真正交给视觉模型理解，
产出统一的结构化 Attachment Context（摘要 / 可提取文本 / 安全发现 / 场景标签 / 置信度），
再注入现有 Planner → Research / Operator / Builder 主流程。

关键设计约束：
- 复用现有 provider/subscription 体系，不另造独立配置系统；
- Vision Target 必须显式配置（subscription + modelId），不隐式复用默认模型、
  也不靠模型名称前缀猜测是否支持图片；
- 无可用视觉模型 / 配置不完整时明确降级而不崩溃；
- 视觉调用失败时记录失败但不中断整条任务链；
- 模型只做「理解 + 结构化总结」，不直接给定/推导攻击结论，交由下游 Agent 研判。
"""

from __future__ import annotations

import base64
import json
import re
import struct
import time
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.config import get_config

# analysis.json 缓存结构版本：结构变化时递增，旧缓存自动失效。
ANALYSIS_VERSION = 1

# 多图并发上限：避免线性逐个 await，也避免一次打爆 provider 限流。
VISION_CONCURRENCY = 3

# Vision 能力状态（未配置 / 待验证 / 验证通过 / 验证失败）
STATUS_UNCONFIGURED = "unconfigured"
STATUS_PENDING = "pending"
STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"


class VisionUnavailable(Exception):
    """当前运行环境没有可用的视觉模型。"""


@dataclass
class VisionTarget:
    """一个明确可用的视觉模型目标（无论「复用订阅」还是「自定义模型」都统一为此结构）。"""

    subscription_name: str
    subscription: Any
    model_id: str
    mode: str = "reuse"  # reuse | custom
    provider: str = "openai"
    base_url: str = ""
    api_key: str = ""

    def identity(self) -> str:
        """运行时连接身份：provider::baseURL::modelId（不含 API Key）。"""
        return f"{self.provider or ''}::{self.base_url or ''}::{self.model_id or ''}"


# 允许进入视觉分析的图片 MIME 类型（分类器已通过 magic bytes 判为 image，
# 这里再对 MIME 归一化，避免把非图片字节交给模型）。
_IMAGE_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


@dataclass
class ImageAnalysis:
    """单张图片的结构化分析结果。"""

    status: str  # analyzed | skipped_no_vision | failed
    filename: str
    summary: str
    observed_text: List[str] = field(default_factory=list)
    security_findings: List[str] = field(default_factory=list)
    scene_tags: List[str] = field(default_factory=list)
    confidence: str = "unknown"  # high | medium | low | unknown
    model: Optional[str] = None
    subscription: Optional[str] = None
    provider: Optional[str] = None
    base_url: Optional[str] = None
    error: Optional[str] = None
    analyzed_at: int = field(default_factory=lambda: int(time.time()))
    analysis_version: int = ANALYSIS_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ImageAnalysis":
        return cls(
            status=data.get("status", "failed"),
            filename=data.get("filename", ""),
            summary=data.get("summary", ""),
            observed_text=list(data.get("observed_text") or []),
            security_findings=list(data.get("security_findings") or []),
            scene_tags=list(data.get("scene_tags") or []),
            confidence=data.get("confidence", "unknown"),
            model=data.get("model"),
            subscription=data.get("subscription"),
            provider=data.get("provider"),
            base_url=data.get("base_url"),
            error=data.get("error"),
            analyzed_at=data.get("analyzed_at") or int(time.time()),
            analysis_version=data.get("analysis_version") or ANALYSIS_VERSION,
        )


_SYSTEM_PROMPT = (
    "你是一名资深安全分析助理。我会给你一张图片，可能是：Web 页面截图、报错截图、登录页截图、"
    "控制台/终端截图、网络拓扑图、漏洞验证结果图、二维码/文本图、抓包界面截图等。\n\n"
    "请基于安全任务视角分析图片，并严格只输出一个 JSON 对象（不要输出任何其它文本、注释或 markdown 代码块），"
    "结构如下：\n"
    "{\n"
    '  "summary": "对图片主要场景与内容的简要中文概括（20~80字，侧重安全相关）",\n'
    '  "observed_text": ["从图片中识别到的关键文本，如错误提示、接口路径、账号字段、IP、命令、返回结果等，没有则为空数组"],\n'
    '  "security_findings": ["与安全相关的可疑点，如数据库错误回显、疑似注入入口、敏感目录、已登录后台、暴露的配置等，没有则为空数组"],\n'
    '  "scene_tags": ["图片类型标签，如 web page / login form / error message / terminal / network topology / admin panel / qr code / packet capture 等"],\n'
    '  "confidence": "对该分析的可信度：high | medium | low"\n'
    "}\n\n"
    "要求：\n"
    "- observed_text 只放真正出现在画面中的文本，不要把推测写进去；\n"
    "- security_findings 只描述画面中可见的可疑线索，不要臆造不存在的信息；\n"
    "- 不要给出具体攻击步骤或结论，只做图像理解与线索提取——攻击研判交给后续智能体。"
)

_USER_PROMPT = "请分析这张图片，并输出符合要求的 JSON"

_TEST_PROMPT = "请用一句话描述这张图片的主要颜色。"


def _normalize_image_mime(filename: str, mime_type: str, head: bytes) -> str:
    """根据扩展名与 magic bytes 归一化出可靠的图片 MIME。"""
    ext = Path(filename).suffix.lower()
    if ext in _IMAGE_MIME_BY_EXT:
        return _IMAGE_MIME_BY_EXT[ext]
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head.startswith(b"RIFF") and head[8:12] == b"WEBP":
        return "image/webp"
    if mime_type and mime_type.startswith("image/"):
        return mime_type
    return "image/png"


def vision_effective_status(vision: Any, target: Optional[VisionTarget]) -> str:
    """推导 Vision 能力状态：未配置 / 待验证 / 验证通过 / 验证失败。

    状态对应「provider::baseURL::modelId」连接身份：身份变化后回到「待验证」。
    """
    if vision is None or not getattr(vision, "enabled", False):
        return STATUS_UNCONFIGURED
    if target is None:
        return STATUS_UNCONFIGURED
    tested = getattr(vision, "tested_identity", "") or ""
    if tested and tested == target.identity():
        status = getattr(vision, "test_status", STATUS_PENDING)
        return status if status in (STATUS_VERIFIED, STATUS_FAILED) else STATUS_PENDING
    return STATUS_PENDING


def resolve_vision_target() -> Optional[VisionTarget]:
    """解析当前可用的视觉模型目标；不可用/配置不完整返回 None。

    规则明确，无任何隐式 fallback：
    - Vision enabled 且 subscription + modelId 都明确、订阅（baseURL+apiKey）完整 → 返回 VisionTarget；
    - 否则返回 None（图片分析走降级）。
    两种模式（reuse/custom）最终都解析成同一个 VisionTarget。
    """
    config = get_config()
    vision = getattr(config.llm, "vision", None)
    if vision is None or not getattr(vision, "enabled", False):
        return None
    sub_name = (getattr(vision, "subscription", "") or "").strip()
    model_id = (getattr(vision, "modelId", "") or "").strip()
    if not sub_name or not model_id:
        return None
    sub = config.llm.subscriptions.get(sub_name)
    if sub is None or not getattr(sub, "baseURL", None) or not getattr(sub, "apiKey", None):
        return None
    return VisionTarget(
        subscription_name=sub_name,
        subscription=sub,
        model_id=model_id,
        mode=getattr(vision, "mode", "reuse") or "reuse",
        provider=getattr(sub, "provider", "openai") or "openai",
        base_url=getattr(sub, "baseURL", "") or "",
        api_key=getattr(sub, "apiKey", "") or "",
    )


async def _call_vision_model(
    subscription: Any, model_id: str, image_bytes: bytes, mime_type: str, prompt: Optional[str] = None
) -> str:
    """调用视觉模型，返回其原始文本输出。"""
    try:
        from ..model import provider as provider_mod
    except Exception as exc:  # pragma: no cover - 导入异常
        raise RuntimeError(f"模型层不可用: {exc}") from exc

    text_prompt = prompt or _USER_PROMPT
    data_url = f"data:{mime_type};base64," + base64.b64encode(image_bytes).decode("ascii")
    b64_payload = base64.b64encode(image_bytes).decode("ascii")

    is_anthropic = (subscription.provider or "").strip().lower() == "anthropic"

    if is_anthropic:
        client = provider_mod._get_anthropic_provider(subscription)
        response = await client.messages.create(
            model=model_id,
            system=_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": text_prompt},
                    {"type": "image", "source": {"type": "base64", "media_type": mime_type, "data": b64_payload}},
                ],
            }],
            max_tokens=2048,
        )
        return "".join(getattr(block, "text", "") for block in response.content if getattr(block, "type", "") == "text")

    client = provider_mod._get_openai_provider(subscription)
    response = await client.chat.completions.create(
        model=model_id,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text", "text": text_prompt},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]},
        ],
        temperature=0.2,
        max_tokens=2048,
    )
    return (response.choices[0].message.content or "") if response.choices else ""


def _strip_json_fence(text: str) -> str:
    """去掉模型可能包裹的 ```json ... ``` 围栏，尽量还原纯 JSON 文本。"""
    match = re.search(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text.strip()


def _parse_vision_result(raw_text: str, filename: str, model_id: str, subscription: Optional[str] = None) -> ImageAnalysis:
    """把模型返回文本解析为结构化 ImageAnalysis；解析失败则退化为纯文本摘要。"""
    cleaned = _strip_json_fence(raw_text)
    parsed: Optional[Dict[str, Any]] = None
    try:
        candidate = json.loads(cleaned)
        if isinstance(candidate, dict):
            parsed = candidate
        else:
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                candidate = json.loads(match.group(0))
                if isinstance(candidate, dict):
                    parsed = candidate
    except (json.JSONDecodeError, ValueError):
        parsed = None

    summary = ""
    observed: List[str] = []
    findings: List[str] = []
    tags: List[str] = []
    confidence = "unknown"

    if parsed is not None:
        summary = str(parsed.get("summary") or "").strip()
        observed = [str(x) for x in (parsed.get("observed_text") or []) if str(x).strip()]
        findings = [str(x) for x in (parsed.get("security_findings") or []) if str(x).strip()]
        tags = [str(x) for x in (parsed.get("scene_tags") or []) if str(x).strip()]
        confidence = _normalize_confidence(parsed.get("confidence"))

    if not summary:
        summary = (raw_text or "").strip()[:400] or "图片已上传，但未能从视觉模型获得结构化摘要。"
        if not observed and not findings and not tags:
            tags = ["unparsed"]

    return ImageAnalysis(
        status="analyzed",
        filename=filename,
        summary=summary,
        observed_text=observed,
        security_findings=findings,
        scene_tags=tags,
        confidence=confidence,
        model=model_id,
        subscription=subscription,
    )


def _normalize_confidence(value: Any) -> str:
    val = str(value or "").strip().lower()
    if val in ("high", "medium", "low"):
        return val
    return "unknown"


def _no_vision_result(filename: str, message: str) -> ImageAnalysis:
    return ImageAnalysis(
        status="skipped_no_vision",
        filename=filename,
        summary=message,
        error=message,
        scene_tags=["image"],
    )


def _failed_result(filename: str, error: str) -> ImageAnalysis:
    return ImageAnalysis(
        status="failed",
        filename=filename,
        summary=f"图片分析失败：{error[:120]}",
        error=error[:200],
        scene_tags=["image"],
    )


async def analyze_attachment_image(path: Path, filename: str, mime_type: str) -> ImageAnalysis:
    """对单张图片执行视觉分析，产出结构化结果。

    任何异常都不会向上抛出：Vision 关闭 / 配置不完整 / 模型调用失败 / 解析失败，
    都转成带状态的 ImageAnalysis，保证不中断整条任务链。
    """
    vision = getattr(get_config().llm, "vision", None)
    if vision is None or not getattr(vision, "enabled", False):
        return _no_vision_result(filename, "视觉分析未启用（Vision 已关闭），图片已安全保存，未执行视觉分析。")

    target = resolve_vision_target()
    if target is None:
        return _no_vision_result(filename, "Vision 已启用，但未配置有效的视觉模型（需选择订阅并填写模型 ID）。")

    image_bytes = path.read_bytes()
    image_mime = _normalize_image_mime(filename, mime_type, image_bytes[:16])
    try:
        raw_text = await _call_vision_model(target.subscription, target.model_id, image_bytes, image_mime)
        if not raw_text or not raw_text.strip():
            return _failed_result(filename, "视觉模型返回空结果")
        result = _parse_vision_result(raw_text, filename, target.model_id, target.subscription_name)
        result.provider = target.provider
        result.base_url = target.base_url
        return result
    except Exception as exc:
        return _failed_result(filename, str(exc))


# ── 能力检测（内置测试图，不依赖用户上传）────────────────────────


def _make_test_png(width: int = 64, height: int = 64, rgb: tuple = (220, 40, 40)) -> bytes:
    """生成一个纯色方块 PNG（内置测试图，默认 64x64 红色），用于验证 provider 是否接受图片输入。

    注意：必须足够大。部分视觉模型（如通义千问 qwen-vl 系列）对图片最小尺寸有硬限制
    （实测 qwen3.8-max 拒绝 8x8，16x16 起才通过）；8x8 会导致能力检测误报「不支持图片」。
    64x64 纯色 PNG 压缩后仅几百字节，既安全又极小。
    """
    def chunk(typ: bytes, data: bytes) -> bytes:
        payload = struct.pack(">I", len(data)) + typ + data
        payload += struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
        return payload

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolor RGB
    row = b"\x00" + bytes(rgb) * width
    idat = zlib.compress(row * height)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", idat)
        + chunk(b"IEND", b"")
    )


def _friendly_vision_error(exc: Exception) -> str:
    """把视觉模型调用异常映射为用户可理解的失败原因（不暴露底层堆栈与 Key）。"""
    msg = str(exc)
    low = msg.lower()
    if "image" in low and ("unsupported" in low or "invalid" in low or "not support" in low or "content type" in low or "content-type" in low):
        return "模型不支持图片输入"
    if "401" in low or "403" in low or "auth" in low or "api key" in low or "unauthorized" in low or "invalid api key" in low:
        return "API Key 无效或鉴权失败"
    if "404" in low or "not found" in low:
        if "model" in low:
            return "模型不存在（404），请检查 Model ID"
        return "端点错误（404），请检查 Base URL"
    if "timeout" in low or "timed out" in low:
        return "请求超时，请稍后重试"
    if any(k in low for k in ("connection", "network", "refused", "unreachable", "name or service", "getaddrinfo")):
        return "网络连接失败，请检查 Base URL 与网络"
    if any(k in low for k in ("json", "parse", "unexpected", "format")):
        return "返回格式异常"
    return f"视觉模型调用失败：{msg[:160]}"


async def test_vision_capability(target: VisionTarget) -> Dict[str, Any]:
    """用内置测试图验证视觉能力，返回 {"status": verified|failed, "message": ...}。

    只验证：provider 能接受 image input、model 能正常返回、无 unsupported image 类错误。
    复用/自定义两种模式最终都解析成同一个 VisionTarget，共用这一套测试。
    """
    image_bytes = _make_test_png()
    try:
        text = await _call_vision_model(target.subscription, target.model_id, image_bytes, "image/png", prompt=_TEST_PROMPT)
        if not text or not text.strip():
            return {"status": STATUS_FAILED, "message": "视觉模型返回空结果"}
        return {"status": STATUS_VERIFIED, "message": ""}
    except Exception as exc:
        return {"status": STATUS_FAILED, "message": _friendly_vision_error(exc)}
