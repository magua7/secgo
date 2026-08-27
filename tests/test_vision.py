"""图片视觉（Vision）测试：显式 Target / 能力状态 / 分析 / 能力检测 / 降级。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from secgo.runtime.vision import (
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_UNCONFIGURED,
    STATUS_VERIFIED,
    VisionTarget,
    _make_test_png,
    _parse_vision_result,
    analyze_attachment_image,
    resolve_vision_target,
    test_vision_capability as run_vision_test,
    vision_effective_status,
)


def _run(coro):
    return asyncio.run(coro)


def _sub(**kw):
    base = {"baseURL": "https://x", "apiKey": "k", "modelId": "deepseek-chat", "provider": "openai"}
    base.update(kw)
    return SimpleNamespace(**base)


def _cfg(vision, subscriptions=None):
    return SimpleNamespace(llm=SimpleNamespace(
        vision=vision,
        defaultModel="gpt-4o",  # 即使默认模型名字像视觉模型，也不得被隐式复用
        subscriptions=subscriptions or {"coding": _sub(modelId="gpt-4o")},
    ))


def _target(model_id="gpt-4o", provider="openai", base_url="https://x", sub=None):
    return VisionTarget(
        subscription_name="vision", subscription=sub or _sub(), model_id=model_id,
        mode="custom", provider=provider, base_url=base_url, api_key="k",
    )


class VisionStatusTests(unittest.TestCase):
    def test_status_unconfigured_when_disabled_or_missing(self):
        self.assertEqual(vision_effective_status(None, _target()), STATUS_UNCONFIGURED)
        self.assertEqual(vision_effective_status(SimpleNamespace(enabled=False), _target()), STATUS_UNCONFIGURED)

    def test_status_unconfigured_when_incomplete(self):
        self.assertEqual(vision_effective_status(SimpleNamespace(enabled=True, mode="custom"), None), STATUS_UNCONFIGURED)

    def test_status_verified_only_for_matching_identity(self):
        target = _target(model_id="gpt-4o")
        v = SimpleNamespace(enabled=True, mode="custom", tested_identity=target.identity(), test_status="verified")
        self.assertEqual(vision_effective_status(v, target), STATUS_VERIFIED)

    def test_status_pending_when_model_changes(self):
        old = _target(model_id="gpt-4o")
        new = _target(model_id="qwen-vl-max")
        v = SimpleNamespace(enabled=True, mode="custom", tested_identity=old.identity(), test_status="verified")
        self.assertEqual(vision_effective_status(v, new), STATUS_PENDING)

    def test_status_pending_when_base_url_changes(self):
        old = _target(model_id="qwen-vl-max", base_url="https://a.example/v1")
        new = _target(model_id="qwen-vl-max", base_url="https://b.example/v1")
        v = SimpleNamespace(enabled=True, mode="custom", tested_identity=old.identity(), test_status="verified")
        self.assertEqual(vision_effective_status(v, new), STATUS_PENDING)

    def test_status_failed(self):
        target = _target(model_id="deepseek-chat")
        v = SimpleNamespace(enabled=True, mode="custom", tested_identity=target.identity(), test_status="failed", test_message="不支持图片")
        self.assertEqual(vision_effective_status(v, target), STATUS_FAILED)


class VisionTargetTests(unittest.TestCase):
    def test_disabled_returns_none_even_if_default_model_looks_vision_capable(self):
        cfg = _cfg(SimpleNamespace(enabled=False, subscription="coding", modelId="gpt-4o"))
        with patch("secgo.runtime.vision.get_config", return_value=cfg):
            self.assertIsNone(resolve_vision_target())

    def test_enabled_but_missing_subscription_returns_none(self):
        cfg = _cfg(SimpleNamespace(enabled=True, subscription="", modelId="gpt-4o"))
        with patch("secgo.runtime.vision.get_config", return_value=cfg):
            self.assertIsNone(resolve_vision_target())

    def test_enabled_but_missing_model_returns_none(self):
        cfg = _cfg(SimpleNamespace(enabled=True, subscription="coding", modelId=""))
        with patch("secgo.runtime.vision.get_config", return_value=cfg):
            self.assertIsNone(resolve_vision_target())

    def test_enabled_with_full_target_resolves(self):
        cfg = _cfg(SimpleNamespace(enabled=True, mode="reuse", subscription="vision", modelId="qwen-vl-max"),
                   subscriptions={"vision": _sub(baseURL="https://v", apiKey="k", modelId="qwen-vl-max", provider="openai")})
        with patch("secgo.runtime.vision.get_config", return_value=cfg):
            target = resolve_vision_target()
        self.assertIsNotNone(target)
        self.assertEqual(target.subscription_name, "vision")
        self.assertEqual(target.model_id, "qwen-vl-max")
        self.assertEqual(target.identity(), "openai::https://v::qwen-vl-max")

    def test_no_implicit_default_model_fallback(self):
        cfg = _cfg(None)
        with patch("secgo.runtime.vision.get_config", return_value=cfg):
            self.assertIsNone(resolve_vision_target())

    def test_missing_subscription_object_returns_none(self):
        cfg = _cfg(SimpleNamespace(enabled=True, subscription="ghost", modelId="gpt-4o"))
        with patch("secgo.runtime.vision.get_config", return_value=cfg):
            self.assertIsNone(resolve_vision_target())


class VisionParseTests(unittest.TestCase):
    def test_parse_structured_json(self):
        raw = json.dumps({
            "summary": "登录页面出现数据库错误回显",
            "observed_text": ["You have an error in your SQL syntax"],
            "security_findings": ["存在数据库错误信息泄露"],
            "scene_tags": ["web page", "login form"],
            "confidence": "high",
        }, ensure_ascii=False)
        result = _parse_vision_result(raw, "login.png", "fake-vision", "sub")
        self.assertEqual(result.status, "analyzed")
        self.assertIn("数据库错误", result.summary)
        self.assertEqual(result.observed_text, ["You have an error in your SQL syntax"])
        self.assertEqual(result.security_findings, ["存在数据库错误信息泄露"])
        self.assertEqual(result.model, "fake-vision")
        self.assertEqual(result.subscription, "sub")

    def test_parse_json_fenced(self):
        raw = "```json\n" + json.dumps({"summary": "后台管理页"}, ensure_ascii=False) + "\n```"
        result = _parse_vision_result(raw, "admin.png", "m")
        self.assertEqual(result.status, "analyzed")
        self.assertIn("后台管理页", result.summary)

    def test_parse_fallback_to_raw_text(self):
        result = _parse_vision_result("这不是 JSON，而是模型直接给出的描述。", "x.png", "m")
        self.assertEqual(result.status, "analyzed")
        self.assertIn("描述", result.summary)


class VisionAnalysisTests(unittest.TestCase):
    def _png_file(self):
        f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        f.write(b"\x89PNG\r\n\x1a\n" + b"fake")
        f.close()
        return Path(f.name)

    def test_success_analysis_records_target_identity(self):
        path = self._png_file()
        try:
            with (
                patch("secgo.runtime.vision.get_config", return_value=_cfg(SimpleNamespace(enabled=True))),
                patch("secgo.runtime.vision.resolve_vision_target", return_value=_target()),
                patch("secgo.runtime.vision._call_vision_model", new=AsyncMock(
                    return_value=json.dumps({"summary": "终端执行截图", "observed_text": ["id"], "security_findings": ["泄露 token"]}, ensure_ascii=False)
                )),
            ):
                result = _run(analyze_attachment_image(path, "term.png", "image/png"))
            self.assertEqual(result.status, "analyzed")
            self.assertEqual(result.subscription, "vision")
            self.assertEqual(result.model, "gpt-4o")
            self.assertEqual(result.provider, "openai")
            self.assertEqual(result.base_url, "https://x")
            self.assertIn("终端", result.summary)
        finally:
            path.unlink(missing_ok=True)

    def test_disabled_degrades_without_crash(self):
        path = self._png_file()
        try:
            with patch("secgo.runtime.vision.get_config", return_value=_cfg(SimpleNamespace(enabled=False))):
                result = _run(analyze_attachment_image(path, "a.png", "image/png"))
            self.assertEqual(result.status, "skipped_no_vision")
            self.assertIn("未启用", result.summary)
        finally:
            path.unlink(missing_ok=True)

    def test_enabled_but_incomplete_degrades_with_reason(self):
        path = self._png_file()
        try:
            with patch("secgo.runtime.vision.get_config", return_value=_cfg(SimpleNamespace(enabled=True, subscription="", modelId=""))):
                result = _run(analyze_attachment_image(path, "a.png", "image/png"))
            self.assertEqual(result.status, "skipped_no_vision")
            self.assertIn("未配置有效的视觉模型", result.summary)
        finally:
            path.unlink(missing_ok=True)

    def test_vision_call_failure_does_not_crash(self):
        path = self._png_file()
        try:
            with (
                patch("secgo.runtime.vision.get_config", return_value=_cfg(SimpleNamespace(enabled=True))),
                patch("secgo.runtime.vision.resolve_vision_target", return_value=_target()),
                patch("secgo.runtime.vision._call_vision_model", new=AsyncMock(side_effect=TimeoutError("provider timeout"))),
            ):
                result = _run(analyze_attachment_image(path, "a.png", "image/png"))
            self.assertEqual(result.status, "failed")
            self.assertIn("provider timeout", result.error)
        finally:
            path.unlink(missing_ok=True)


class VisionCapabilityTests(unittest.TestCase):
    def test_make_test_png_is_valid(self):
        png = _make_test_png()
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_capability_verified(self):
        with patch("secgo.runtime.vision._call_vision_model", new=AsyncMock(return_value="红色方块")):
            result = _run(run_vision_test(_target()))
        self.assertEqual(result["status"], STATUS_VERIFIED)

    def test_capability_failed_unsupported_image(self):
        class UnsupportedImage(Exception):
            def __str__(self):
                return "Error code 400 - The model does not support image input"

        with patch("secgo.runtime.vision._call_vision_model", new=AsyncMock(side_effect=UnsupportedImage())):
            result = _run(run_vision_test(_target()))
        self.assertEqual(result["status"], STATUS_FAILED)
        self.assertIn("不支持图片输入", result["message"])

    def test_capability_failed_empty(self):
        with patch("secgo.runtime.vision._call_vision_model", new=AsyncMock(return_value="")):
            result = _run(run_vision_test(_target()))
        self.assertEqual(result["status"], STATUS_FAILED)


if __name__ == "__main__":
    unittest.main()
