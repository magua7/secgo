from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient
from starlette.requests import Request

from secgo.runtime import attachments
from secgo.runtime.session import SessionManager
from secgo.web import server


def _request(body: dict) -> Request:
    payload = json.dumps(body).encode("utf-8")
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": payload, "more_body": False}

    return Request({"type": "http", "method": "POST", "path": "/api/chat", "headers": []}, receive)


class _DummyTask:
    def add_done_callback(self, _callback):
        return None


class _DummyLoop:
    def create_task(self, _awaitable):
        return _DummyTask()


class WebAttachmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.uploads = root / "uploads"
        self.workspace = root / "workspace"
        self.db_path = root / "sec-go.db"
        self.patchers = [
            patch.object(attachments, "UPLOADS_BASE", self.uploads),
            patch.object(attachments, "get_workspace_base", return_value=self.workspace),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        server._awaiting_sessions.clear()
        server._channels.clear()
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temp_dir.cleanup()

    def _upload(self, name: str, mime_type: str, data: bytes):
        request = server._AttachmentUploadReq(
            name=name,
            mimeType=mime_type,
            data=base64.b64encode(data).decode("ascii"),
        )
        response = asyncio.run(server.api_upload_attachment(request))
        return response, json.loads(response.body)

    def test_valid_text_upload_and_path_traversal_name_is_metadata_only(self) -> None:
        response, body = self._upload("../../test.txt", "text/plain", b"hello attachment")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["attachment"]["kind"], "text")
        attachment_id = body["attachment"]["id"]
        self.assertEqual(attachments.get_temporary_attachment(attachment_id).original_name, "../../test.txt")
        self.assertTrue((self.uploads / attachment_id / "original.bin").is_file())
        self.assertFalse((Path(self.temp_dir.name) / "test.txt").exists())

    def test_png_magic_overrides_submitted_mime_type(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"content"
        response, body = self._upload("image.txt", "text/plain", png)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["attachment"]["kind"], "image")

    def test_invalid_base64_is_rejected(self) -> None:
        request = server._AttachmentUploadReq(name="bad.txt", mimeType="text/plain", data="%%%")
        response = asyncio.run(server.api_upload_attachment(request))
        self.assertEqual(response.status_code, 400)

    def test_file_over_10mb_is_rejected(self) -> None:
        response, _ = self._upload("large.bin", "application/octet-stream", b"x" * (10 * 1024 * 1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_attachment_moves_into_session_workspace(self) -> None:
        _, body = self._upload("sample.txt", "text/plain", b"security evidence")
        attachment_id = body["attachment"]["id"]
        session_id = str(uuid.uuid4())
        metadata = attachments.move_attachment_to_session(attachment_id, session_id)
        self.assertEqual(metadata.session_id, session_id)
        self.assertTrue((self.workspace / session_id / "attachments" / attachment_id / "original.bin").is_file())
        self.assertFalse((self.uploads / attachment_id).exists())

    def test_text_prompt_is_bounded_and_database_has_no_base64(self) -> None:
        raw = ("BEGIN\n" + "security-log\n" * 10000 + "END").encode()
        encoded = base64.b64encode(raw).decode("ascii")
        _, body = self._upload("evidence.txt", "text/plain", raw)
        attachment_id = body["attachment"]["id"]
        session_id = str(uuid.uuid4())
        manager = SessionManager(self.db_path)
        manager.save_state(session_id, {"messages": [{"role": "user", "content": "old"}]})
        manager.close()
        captured = []

        async def call_chat():
            with (
                patch.object(server, "resolve_session_db_path", return_value=self.db_path),
                patch.object(server, "run_engine", new=lambda message, sid: captured.append((message, sid))),
                patch.object(server.asyncio, "get_running_loop", return_value=_DummyLoop()),
            ):
                return await server.api_chat(_request({
                    "message": "请分析风险",
                    "sessionId": session_id,
                    "attachments": [attachment_id],
                }))

        response = asyncio.run(call_chat())
        self.assertEqual(response.status_code, 200)
        prompt = captured[0][0]
        self.assertIn("[附件 1 提取内容开始]", prompt)
        self.assertIn("[附件文本已截断]", prompt)
        self.assertLess(len(prompt), 40000)
        manager = SessionManager(self.db_path)
        state = manager.load_state(session_id)
        manager.close()
        serialized = json.dumps(state, ensure_ascii=False)
        self.assertNotIn(encoded, serialized)
        self.assertIn("请分析风险", serialized)

    def test_missing_attachment_id_is_rejected(self) -> None:
        response = asyncio.run(server.api_chat(_request({
            "message": "分析",
            "attachments": [str(uuid.uuid4())],
        })))
        self.assertEqual(response.status_code, 400)

    def test_plain_text_chat_is_unchanged(self) -> None:
        session_id = str(uuid.uuid4())
        captured = []

        async def call_chat():
            with (
                patch.object(server, "run_engine", new=lambda message, sid: captured.append((message, sid))),
                patch.object(server.asyncio, "get_running_loop", return_value=_DummyLoop()),
            ):
                return await server.api_chat(_request({"message": "hello", "sessionId": session_id}))

        response = asyncio.run(call_chat())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(captured, [("hello", session_id)])

    def test_upload_requires_login(self) -> None:
        with patch.object(server, "_auth_enabled", return_value=True):
            response = TestClient(server.app).post("/api/attachments", json={
                "name": "a.txt",
                "mimeType": "text/plain",
                "data": base64.b64encode(b"a").decode("ascii"),
            })
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
