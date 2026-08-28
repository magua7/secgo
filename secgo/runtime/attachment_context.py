"""附件上下文构建：图片 analysis.json 缓存、多图并发分析、attachment → Planner 上下文拼装。

这是附件预处理层的纯逻辑，不依赖 Web / settings 持久化；图片视觉分析通过 vision 模块完成，
PDF/ZIP/JSON/YAML/OpenAPI 文本提取沿用 attachments 模块。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional

from .attachments import (
    extract_limited_text,
    get_attachment_analysis,
    get_session_attachment_path,
    save_attachment_analysis,
)
from .vision import (
    ANALYSIS_VERSION,
    VISION_CONCURRENCY,
    analyze_attachment_image,
    resolve_vision_target,
)


def attachment_presentation(metadata, analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """附件的展示形态（不含 SHA256/服务器路径等内部信息）。

    展示层只携带「附件本身 + 简短状态」：视觉摘要 / 安全发现 / 场景标签等分析内容
    只进入 Planner 上下文（build_attachment_context）与执行轨迹（attachment:analyzed
    事件），绝不进入用户消息，避免把系统分析结果伪装成用户输入。
    """
    payload = {
        "id": metadata.attachment_id,
        "filename": metadata.original_name,
        "mimeType": metadata.mime_type,
        "kind": metadata.detected_kind,
        "size": metadata.size,
    }
    if analysis is not None:
        payload["analysis"] = {
            "status": analysis.get("status"),
            "error": analysis.get("error"),
        }
    return payload


def cache_matches_vision_target(cached: Dict[str, Any], target) -> bool:
    """判断 analysis.json 缓存是否对应当前 Vision Target（provider+baseURL+modelId+version 一致才复用）。"""
    return (
        cached.get("status") == "analyzed"
        and cached.get("provider") == target.provider
        and cached.get("base_url") == target.base_url
        and cached.get("model") == target.model_id
        and cached.get("analysis_version") == ANALYSIS_VERSION
    )


async def analyze_attachment_image_cached(session_id: str, metadata) -> Dict[str, Any]:
    """对图片附件执行视觉分析（带缓存：仅当 Vision Target 未变化时复用 analysis.json）。"""
    target = resolve_vision_target()
    if target is not None:
        cached = get_attachment_analysis(session_id, metadata.attachment_id)
        if cached is not None and cache_matches_vision_target(cached, target):
            return cached
    path = get_session_attachment_path(session_id, metadata.attachment_id)
    result = await analyze_attachment_image(path, metadata.original_name, metadata.mime_type)
    data = result.to_dict()
    # 仅持久化「成功分析」；跳过/失败不落盘，下轮可重试（如用户后来补配了视觉模型）
    if data.get("status") == "analyzed":
        try:
            save_attachment_analysis(session_id, metadata.attachment_id, data)
        except (OSError, ValueError):
            pass
    return data


def image_analysis_lines(analysis: Dict[str, Any]) -> list:
    """把图片视觉分析结果格式化为注入 Agent 上下文的行。"""
    status = analysis.get("status")
    if status == "analyzed":
        lines = ["\n[图片视觉分析]"]
        summary = analysis.get("summary") or ""
        if summary:
            lines.append(f"- 摘要: {summary}")
        observed = analysis.get("observed_text") or []
        if observed:
            lines.append("- 画面文本: " + "；".join(str(t) for t in observed[:20]))
        findings = analysis.get("security_findings") or []
        if findings:
            lines.append("- 安全发现:")
            for finding in findings[:20]:
                lines.append(f"    - {finding}")
        tags = analysis.get("scene_tags") or []
        if tags:
            lines.append("- 场景标签: " + "、".join(str(t) for t in tags[:20]))
        confidence = analysis.get("confidence") or "unknown"
        lines.append(f"- 置信度: {confidence}")
        if analysis.get("model"):
            lines.append(f"- 分析模型: {analysis['model']}")
        return lines
    if status == "failed":
        return [f"- 状态: 图片分析失败：{analysis.get('error') or '未知错误'}"]
    return [f"- 状态: {analysis.get('summary') or '图片已上传，但未执行视觉分析。'}"]


async def build_attachment_context(session_id: str, attachments: list) -> tuple[str, Dict[str, Dict[str, Any]]]:
    """构建注入 Agent 的用户附件上下文，并返回各图片附件的视觉分析结果。

    - 多图用有上限的并发分析（Semaphore），避免线性逐个 await；
    - 等待所有图片分析（或降级）完成后，才按附件顺序拼装上下文 → 保证 Planner 拿到完整上下文；
    - 返回 (prompt_text, analyses)：analyses 映射 attachment_id -> 分析 dict。
    """
    # 先并发分析所有图片（有上限），失败隔离，不互相拖垮
    image_metas = [m for m in attachments if m.detected_kind == "image"]
    semaphore = asyncio.Semaphore(VISION_CONCURRENCY)

    async def _analyze_one(metadata) -> Dict[str, Any]:
        async with semaphore:
            try:
                return await analyze_attachment_image_cached(session_id, metadata)
            except Exception as exc:  # 防御：任何意外都不中断其它图片
                return {
                    "status": "failed",
                    "filename": metadata.original_name,
                    "summary": f"图片分析失败：{exc}",
                    "error": str(exc)[:200],
                    "scene_tags": ["image"],
                }

    image_results = await asyncio.gather(*(_analyze_one(m) for m in image_metas))
    image_map: Dict[str, Dict[str, Any]] = {
        m.attachment_id: r for m, r in zip(image_metas, image_results)
    }

    sections = ["[用户附件]"]
    analyses: Dict[str, Dict[str, Any]] = {}
    for index, metadata in enumerate(attachments, 1):
        lines = [
            f"附件 {index}：",
            f"- evidence_id: {metadata.attachment_id}",
            f"- 文件名: {json.dumps(metadata.original_name, ensure_ascii=False)}",
            f"- 类型: {metadata.detected_kind}",
            f"- 大小: {metadata.size} bytes",
            f"- SHA-256: {metadata.sha256}",
        ]
        if metadata.detected_kind in ("text", "pdf", "zip"):
            extracted = extract_limited_text(
                get_session_attachment_path(session_id, metadata.attachment_id),
                detected_kind=metadata.detected_kind,
            )
            if extracted is not None:
                lines.extend([
                    f"\n[附件 {index} 提取内容开始]",
                    extracted,
                    f"[附件 {index} 提取内容结束]",
                ])
            else:
                lines.append(f"- 状态: {metadata.detected_kind} 内容提取失败")
        elif metadata.detected_kind == "image":
            analysis = image_map.get(metadata.attachment_id) or {
                "status": "failed",
                "filename": metadata.original_name,
                "summary": "图片分析失败",
                "scene_tags": ["image"],
            }
            analyses[metadata.attachment_id] = analysis
            lines.extend(image_analysis_lines(analysis))
        else:
            lines.append("- 状态: 文件已安全保存，本阶段仅登记元数据")
        sections.append("\n".join(lines))
    return "\n\n".join(sections), analyses
