"""Web 层图片视觉分析集成测试：注入上下文 / 多图并发 / 失败隔离 / 缓存一致性。"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from secgo.runtime import attachment_context, attachments
from secgo.runtime.vision import ANALYSIS_VERSION, ImageAnalysis, VisionTarget
from secgo.web import server


def _request(body: dict):
    from starlette.requests import Request
    payload = json.dumps(body).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/api/chat", "headers": []}, receive)


def _png(name: str = "shot.png") -> bytes:
    return b"\x89PNG\r\n\x1a\n" + name.encode() + b"\x00\x00\x00"


def _vision_target(model_id: str, base_url: str = "https://x", provider: str = "openai") -> VisionTarget:
    return VisionTarget(
        subscription_name="vision", subscription=SimpleNamespace(), model_id=model_id,
        mode="custom", provider=provider, base_url=base_url, api_key="k",
    )


class WebVisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.uploads = root / "uploads"
        self.workspace = root / "workspace"
        self.db_path = root / "sec-go.db"
        self.patchers = [
            patch.object(attachments, "UPLOADS_BASE", self.uploads),
            patch.object(attachments, "get_workspace_base", return_value=self.workspace),
            patch.object(server, "resolve_session_db_path", return_value=str(self.db_path)),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        server._awaiting_sessions.clear()
        server._channels.clear()
        server._tasks.clear()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def _upload(self, name: str, data: bytes):
        req = server._AttachmentUploadReq(
            name=name, mimeType="image/png", data=base64.b64encode(data).decode("ascii"),
        )
        response = asyncio.run(server.api_upload_attachment(req))
        return json.loads(response.body)["attachment"]["id"]

    def _move(self, attachment_id: str, session_id: str):
        return attachments.move_attachment_to_session(attachment_id, session_id)

    def test_image_summary_is_injected_into_planner_context(self) -> None:
        attachment_id = self._upload("login-error.png", _png("login-error.png"))
        session_id = str(uuid.uuid4())
        metadata = self._move(attachment_id, session_id)

        fake = ImageAnalysis(
            status="analyzed", filename="login-error.png",
            summary="登录页面出现数据库错误回显",
            observed_text=["You have an error in your SQL syntax"],
            security_findings=["存在数据库错误信息泄露", "疑似 SQL 注入测试入口"],
            scene_tags=["web page", "login form"], confidence="high", model="fake-vision",
        )
        with patch.object(attachment_context, "analyze_attachment_image", new=AsyncMock(return_value=fake)):
            prompt, analyses = asyncio.run(attachment_context.build_attachment_context(session_id, [metadata]))

        self.assertIn("[图片视觉分析]", prompt)
        self.assertIn("登录页面出现数据库错误回显", prompt)
        self.assertIn("存在数据库错误信息泄露", prompt)
        self.assertIn("疑似 SQL 注入测试入口", prompt)
        self.assertIn("You have an error in your SQL syntax", prompt)
        self.assertEqual(analyses[attachment_id]["status"], "analyzed")
        self.assertTrue((self.workspace / session_id / "attachments" / attachment_id / "analysis.json").is_file())

    def test_three_images_are_each_analyzed(self) -> None:
        session_id = str(uuid.uuid4())
        metas = []
        for name in ("a.png", "b.png", "c.png"):
            aid = self._upload(name, _png(name))
            metas.append(self._move(aid, session_id))

        def fake_result(path, filename, mime_type):
            return ImageAnalysis(
                status="analyzed", filename=filename,
                summary=f"{filename} 的视觉摘要", security_findings=[f"发现 {filename}"],
                confidence="medium", model="fake-vision",
            )

        with patch.object(attachment_context, "analyze_attachment_image", new=AsyncMock(side_effect=fake_result)):
            prompt, analyses = asyncio.run(attachment_context.build_attachment_context(session_id, metas))

        self.assertEqual(len(analyses), 3)
        self.assertIn("a.png 的视觉摘要", prompt)
        self.assertIn("b.png 的视觉摘要", prompt)
        self.assertIn("c.png 的视觉摘要", prompt)

    def test_one_image_failure_does_not_block_others(self) -> None:
        session_id = str(uuid.uuid4())
        metas = []
        for name in ("ok1.png", "bad.png", "ok2.png"):
            aid = self._upload(name, _png(name))
            metas.append(self._move(aid, session_id))

        def fake_result(path, filename, mime_type):
            if filename == "bad.png":
                raise RuntimeError("provider timeout")
            return ImageAnalysis(status="analyzed", filename=filename, summary=f"{filename} 摘要", model="m")

        with patch.object(attachment_context, "analyze_attachment_image", new=AsyncMock(side_effect=fake_result)):
            prompt, analyses = asyncio.run(attachment_context.build_attachment_context(session_id, metas))

        self.assertEqual(len(analyses), 3)
        self.assertIn("ok1.png 摘要", prompt)
        self.assertIn("ok2.png 摘要", prompt)
        self.assertIn("bad.png", prompt)  # 失败的那张也出现在上下文（带失败说明）
        self.assertEqual(analyses[metas[0].attachment_id]["status"], "analyzed")
        self.assertEqual(analyses[metas[2].attachment_id]["status"], "analyzed")
        self.assertEqual(analyses[metas[1].attachment_id]["status"], "failed")

    def test_no_vision_config_degrades_in_prompt(self) -> None:
        attachment_id = self._upload("shot.png", _png("shot.png"))
        session_id = str(uuid.uuid4())
        metadata = self._move(attachment_id, session_id)

        skip = ImageAnalysis(status="skipped_no_vision", filename="shot.png",
                             summary="Vision 已启用，但未配置有效的视觉模型（需选择订阅并填写模型 ID）。")
        with patch.object(attachment_context, "analyze_attachment_image", new=AsyncMock(return_value=skip)):
            prompt, analyses = asyncio.run(attachment_context.build_attachment_context(session_id, [metadata]))

        self.assertIn("未配置有效的视觉模型", prompt)
        self.assertEqual(analyses[attachment_id]["status"], "skipped_no_vision")
        self.assertFalse((self.workspace / session_id / "attachments" / attachment_id / "analysis.json").exists())

    def test_cache_reused_when_vision_target_unchanged(self) -> None:
        attachment_id = self._upload("shot.png", _png("shot.png"))
        session_id = str(uuid.uuid4())
        metadata = self._move(attachment_id, session_id)
        attachments.save_attachment_analysis(session_id, attachment_id, {
            "status": "analyzed", "filename": "shot.png", "summary": "缓存的摘要",
            "provider": "openai", "base_url": "https://x", "model": "gpt-4o", "analysis_version": ANALYSIS_VERSION,
            "security_findings": ["缓存发现"], "scene_tags": ["web page"], "confidence": "high",
        })

        target = _vision_target("gpt-4o")
        analyze_mock = AsyncMock(return_value=ImageAnalysis(status="analyzed", filename="shot.png", summary="不应出现"))
        with patch.object(attachment_context, "resolve_vision_target", return_value=target), \
             patch.object(attachment_context, "analyze_attachment_image", new=analyze_mock):
            data = asyncio.run(attachment_context.analyze_attachment_image_cached(session_id, metadata))

        self.assertEqual(data["summary"], "缓存的摘要")
        analyze_mock.assert_not_awaited()

    def test_cache_invalidated_when_model_changes(self) -> None:
        attachment_id = self._upload("shot.png", _png("shot.png"))
        session_id = str(uuid.uuid4())
        metadata = self._move(attachment_id, session_id)
        # 旧缓存是 gpt-4o 的结果
        attachments.save_attachment_analysis(session_id, attachment_id, {
            "status": "analyzed", "filename": "shot.png", "summary": "gpt-4o 的旧摘要",
            "provider": "openai", "base_url": "https://x", "model": "gpt-4o", "analysis_version": ANALYSIS_VERSION,
        })

        # 当前目标换成了 qwen-vl-max → 旧缓存不得复用
        target = _vision_target("qwen-vl-max")
        fresh = ImageAnalysis(status="analyzed", filename="shot.png", summary="qwen 的新摘要",
                              model="qwen-vl-max", subscription="vision", provider="openai", base_url="https://x")
        with patch.object(attachment_context, "resolve_vision_target", return_value=target), \
             patch.object(attachment_context, "analyze_attachment_image", new=AsyncMock(return_value=fresh)):
            data = asyncio.run(attachment_context.analyze_attachment_image_cached(session_id, metadata))

        self.assertEqual(data["summary"], "qwen 的新摘要")
        self.assertEqual(data["model"], "qwen-vl-max")

    def test_cache_invalidated_when_base_url_changes(self) -> None:
        attachment_id = self._upload("shot.png", _png("shot.png"))
        session_id = str(uuid.uuid4())
        metadata = self._move(attachment_id, session_id)
        # 旧缓存来自 endpoint A
        attachments.save_attachment_analysis(session_id, attachment_id, {
            "status": "analyzed", "filename": "shot.png", "summary": "endpoint A 的旧摘要",
            "provider": "openai", "base_url": "https://a.example/v1", "model": "qwen-vl-max", "analysis_version": ANALYSIS_VERSION,
        })

        # 同一 modelId 但换了 endpoint → 不得复用旧缓存
        target = _vision_target("qwen-vl-max", base_url="https://b.example/v1")
        fresh = ImageAnalysis(status="analyzed", filename="shot.png", summary="endpoint B 的新摘要",
                              model="qwen-vl-max", subscription="vision", provider="openai", base_url="https://b.example/v1")
        with patch.object(attachment_context, "resolve_vision_target", return_value=target), \
             patch.object(attachment_context, "analyze_attachment_image", new=AsyncMock(return_value=fresh)):
            data = asyncio.run(attachment_context.analyze_attachment_image_cached(session_id, metadata))

        self.assertEqual(data["summary"], "endpoint B 的新摘要")


if __name__ == "__main__":
    unittest.main()
