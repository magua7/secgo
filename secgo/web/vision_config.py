"""Vision 配置：请求模型、custom/reuse 保存、临时能力测试、验证状态、API Key 沿用、内部订阅。

这是 Web 层的 Vision 配置业务：server.py 只保留「请求参数 → 调用这里 → 返回结果」。
运行时目标解析（VisionTarget）与模型调用仍由 runtime.vision 负责。
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ..config.config import SETTINGS_FILE, SubscriptionConfig, get_config, reset_config
from ..config.jsonc import parse_jsonc
from ..config.persistence import write_settings_atomically
from ..runtime.vision import (
    VisionTarget,
    resolve_vision_target,
    test_vision_capability,
    vision_effective_status,
)

# Vision 自定义模式内部使用的专用订阅名（保留 ID，前缀 __ 避免与用户订阅冲突）：
# 不暴露给用户，也不出现在「复用已有订阅」下拉里。
VISION_SUBSCRIPTION_NAME = "__vision_custom__"

# 保存配置后强制回到「待验证」：verified 只能由后端 /api/vision-test 真实测试成功后写入，
# 客户端不能通过提交 test_status 等字段自行声明已验证。
VISION_TEST_RESET = {"tested_identity": "", "test_status": "pending", "test_message": "", "tested_at": None}


class VisionConfigRequest(BaseModel):
    # 只保存配置本身；不接受任何客户端声明的验证状态（verified/failed 只能由后端测试写入）。
    enabled: bool = True
    mode: str = "reuse"      # reuse | custom
    subscription: str = ""
    modelId: str = ""
    provider: str = "openai"
    baseURL: str = ""
    apiKey: str = ""


class VisionTestRequest(BaseModel):
    mode: str = "reuse"      # reuse | custom
    subscription: str = ""
    modelId: str = ""
    provider: str = "openai"
    baseURL: str = ""
    apiKey: str = ""


def _persist_vision_settings(existing: Dict[str, Any], updates: Dict[str, Any]) -> Optional[str]:
    """合并 vision 更新到 settings.json 顶层 vision 节并落盘，返回错误消息（成功为 None）。"""
    vision_raw = dict(existing.get("vision") or {})
    vision_raw.update(updates)
    updated = dict(existing)
    updated["vision"] = vision_raw
    try:
        write_settings_atomically(updated, SETTINGS_FILE)
    except OSError as exc:
        return f"写入失败：{exc}"
    reset_config()
    return None


def _write_subscriptions_and_vision(
    existing: Dict[str, Any], subs_update: Dict[str, Any], vision_update: Dict[str, Any]
) -> Optional[str]:
    """同时更新 subscriptions 与 vision 节并落盘（自定义模式需写入专用订阅）。"""
    subs = dict(existing.get("subscriptions") or {})
    subs.update(subs_update)
    vision_raw = dict(existing.get("vision") or {})
    vision_raw.update(vision_update)
    updated = dict(existing)
    updated["subscriptions"] = subs
    updated["vision"] = vision_raw
    try:
        write_settings_atomically(updated, SETTINGS_FILE)
    except OSError as exc:
        return f"写入失败：{exc}"
    reset_config()
    return None


def _build_temp_vision_target(req: VisionTestRequest) -> tuple[Optional[VisionTarget], Optional[str]]:
    """从测试请求构造一个临时 VisionTarget（仅用于本次测试，不落盘）。

    复用模式：subscription + modelId，Key 取自该订阅；自定义模式：provider + baseURL + modelId + apiKey，
    apiKey 留空时回落到已保存的自定义 Vision Key。
    """
    cfg = get_config()
    model_id = (req.modelId or "").strip()
    if not model_id:
        return None, "请填写视觉模型（Model ID）"

    if (req.mode or "reuse") == "reuse":
        sub_name = (req.subscription or "").strip()
        if not sub_name:
            return None, "请选择模型订阅"
        sub = cfg.llm.subscriptions.get(sub_name)
        if sub is None or not getattr(sub, "baseURL", None) or not getattr(sub, "apiKey", None):
            return None, f"订阅 {sub_name} 不存在或未配置完整"
        return VisionTarget(
            subscription_name=sub_name, subscription=sub, model_id=model_id, mode="reuse",
            provider=getattr(sub, "provider", "openai") or "openai",
            base_url=getattr(sub, "baseURL", "") or "", api_key=getattr(sub, "apiKey", "") or "",
        ), None

    # 自定义模式
    provider = (req.provider or "openai").strip() or "openai"
    base_url = (req.baseURL or "").strip()
    if not base_url:
        return None, "请填写 Base URL"
    api_key = (req.apiKey or "").strip()
    if not api_key:
        saved_custom = cfg.llm.subscriptions.get(VISION_SUBSCRIPTION_NAME)
        api_key = getattr(saved_custom, "apiKey", "") if saved_custom else ""
    if not api_key:
        return None, "请填写 API Key"
    sub = SubscriptionConfig(provider=provider, baseURL=base_url, modelId=model_id, apiKey=api_key)
    return VisionTarget(
        subscription_name=VISION_SUBSCRIPTION_NAME, subscription=sub, model_id=model_id, mode="custom",
        provider=provider, base_url=base_url, api_key=api_key,
    ), None


def save_vision_config(req: VisionConfigRequest) -> JSONResponse:
    """保存图片视觉（Vision）配置。

    - mode=reuse：复用已有订阅，仅记 enabled + subscription + modelId；
    - mode=custom：在 subscriptions 中创建/更新一条专用订阅（provider/baseURL/apiKey/modelId），
      vision 节只记 mode/subscription/modelId；apiKey 留空表示沿用已保存 Key。
    保存不做能力检测；能力检测由 /api/vision-test 独立触发。任何保存都回到「待验证」。
    """
    mode = (req.mode or "reuse").strip()
    model_id = (req.modelId or "").strip()

    try:
        existing = parse_jsonc(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except OSError:
        existing = {}

    if not req.enabled:
        err = _persist_vision_settings(existing, {
            "enabled": False, "mode": mode,
            "subscription": (req.subscription or "").strip(), "modelId": model_id,
            **VISION_TEST_RESET,
        })
        if err:
            return JSONResponse({"ok": False, "saved": False, "error": err}, status_code=500)
        return JSONResponse({"ok": True, "saved": True})

    if not model_id:
        return JSONResponse({"ok": False, "saved": False, "error": "请填写视觉模型（Model ID）"}, status_code=400)

    # 任何配置保存（含首次、修改、切换模式）都回到「待验证」。
    vision_update: Dict[str, Any] = {"enabled": True, "mode": mode, "modelId": model_id, **VISION_TEST_RESET}

    if mode == "custom":
        provider = (req.provider or "openai").strip() or "openai"
        base_url = (req.baseURL or "").strip()
        if not base_url:
            return JSONResponse({"ok": False, "saved": False, "error": "请填写 Base URL"}, status_code=400)
        api_key = (req.apiKey or "").strip()
        saved_custom = (existing.get("subscriptions") or {}).get(VISION_SUBSCRIPTION_NAME) or {}
        effective_key = api_key or str(saved_custom.get("apiKey") or "")
        if not effective_key:
            return JSONResponse({"ok": False, "saved": False, "error": "请填写 API Key"}, status_code=400)
        subs_update = {VISION_SUBSCRIPTION_NAME: {
            "provider": provider, "baseURL": base_url, "modelId": model_id, "apiKey": effective_key,
        }}
        vision_update["subscription"] = VISION_SUBSCRIPTION_NAME
        err = _write_subscriptions_and_vision(existing, subs_update, vision_update)
    else:
        sub_name = (req.subscription or "").strip()
        if not sub_name:
            return JSONResponse({"ok": False, "saved": False, "error": "请选择模型订阅"}, status_code=400)
        cfg = get_config()
        sub = cfg.llm.subscriptions.get(sub_name)
        if sub is None or not getattr(sub, "baseURL", None) or not getattr(sub, "apiKey", None):
            return JSONResponse(
                {"ok": False, "saved": False, "error": f"订阅 {sub_name} 不存在或未配置完整"},
                status_code=400,
            )
        vision_update["subscription"] = sub_name
        err = _persist_vision_settings(existing, vision_update)

    if err:
        return JSONResponse({"ok": False, "saved": False, "error": err}, status_code=500)
    return JSONResponse({"ok": True, "saved": True})


async def run_vision_test(req: Optional[VisionTestRequest]) -> JSONResponse:
    """用内置测试图做一次视觉能力检测。

    - req 非 None：测试表单当前值（临时），不落盘、不写 cache、不泄漏 Key；
    - req 为 None：测试已保存配置，并持久化测试结果（verified/failed）。
    """
    if req is not None:
        target, error = _build_temp_vision_target(req)
        if error:
            return JSONResponse({"ok": False, "status": "unconfigured", "error": error}, status_code=400)
        result = await test_vision_capability(target)
        return JSONResponse({"ok": True, "status": result["status"], "message": result.get("message", ""), "temporary": True})

    cfg = get_config()
    vision = getattr(cfg.llm, "vision", None)
    if vision is None or not getattr(vision, "enabled", False):
        return JSONResponse({"ok": False, "status": "unconfigured", "error": "Vision 未启用"}, status_code=400)
    target = resolve_vision_target()
    if target is None:
        return JSONResponse(
            {"ok": False, "status": "unconfigured",
             "error": "Vision 已启用，但未配置有效的视觉模型"},
            status_code=400,
        )

    result = await test_vision_capability(target)
    try:
        existing = parse_jsonc(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
    except OSError:
        existing = {}
    err = _persist_vision_settings(existing, {
        "tested_identity": target.identity(),
        "test_status": result["status"],
        "test_message": result.get("message", ""),
        "tested_at": int(time.time()),
    })
    if err:
        return JSONResponse({"ok": False, "status": result["status"], "error": err}, status_code=500)
    return JSONResponse({"ok": True, "status": result["status"], "message": result.get("message", "")})


def build_vision_status(cfg: Any, vision_target: Optional[VisionTarget]) -> Dict[str, Any]:
    """由配置 + 已解析的 VisionTarget 构建 keys-status 的 vision 状态（不含 API Key）。"""
    vision_cfg = getattr(cfg.llm, "vision", None)
    mode = (getattr(vision_cfg, "mode", "reuse") or "reuse") if vision_cfg is not None else "reuse"
    sub_name = (getattr(vision_cfg, "subscription", "") or "") if vision_cfg is not None else ""
    model_id = (getattr(vision_cfg, "modelId", "") or "") if vision_cfg is not None else ""
    vision_sub = cfg.llm.subscriptions.get(sub_name) if sub_name else None
    provider = vision_target.provider if vision_target else (vision_sub.provider if vision_sub else "openai")
    base_url = vision_target.base_url if vision_target else (vision_sub.baseURL if vision_sub else "")
    has_api_key = bool(vision_target.api_key if vision_target else (vision_sub.apiKey if vision_sub else None))

    return {
        "enabled": bool(getattr(vision_cfg, "enabled", False)),
        "mode": mode,
        "configured": vision_target is not None,
        # reuse 模式展示所选的订阅名；custom 模式不暴露内部 "__vision_custom__" 订阅名
        "subscription": sub_name if mode == "reuse" else "",
        "model_id": model_id,
        "provider": provider,
        "base_url": base_url,
        "has_api_key": has_api_key,
        "status": vision_effective_status(vision_cfg, vision_target),
        "test_message": getattr(vision_cfg, "test_message", "") or "",
        "tested_at": getattr(vision_cfg, "tested_at", None),
    }


def build_subscription_options(cfg: Any) -> list:
    """已有订阅列表（供 Vision 设置页下拉选择；不含 API Key，且隐藏内部专用订阅）。"""
    return [
        {
            "name": name,
            "provider": sub.provider,
            "model": sub.modelId or "",
            "base_url": sub.baseURL or "",
            "has_key": bool(sub.apiKey),
        }
        for name, sub in cfg.llm.subscriptions.items()
        if name != VISION_SUBSCRIPTION_NAME
    ]
