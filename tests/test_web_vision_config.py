"""Vision 配置（自定义模型 / 复用订阅）/ credential / 信任边界 / 安全测试。"""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from secgo.runtime.vision import STATUS_VERIFIED, VisionTarget
from secgo.web import server


def _cfg(subscriptions=None, vision=None):
    return SimpleNamespace(
        llm=SimpleNamespace(vision=vision, subscriptions=subscriptions or {}, agents={}, defaultModel="deepseek-chat", enabled=True),
        web=SimpleNamespace(secretKey="test-secret"),
    )


class WebVisionConfigTests(unittest.TestCase):
    def _call_config(self, settings: dict, req: server._VisionConfigReq):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(settings), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "reset_config"),
            ):
                response = asyncio.run(server.api_vision_config(req))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
            return response, saved

    # ── 信任边界：客户端不能声明 verified ──────────────────────

    def test_config_req_schema_does_not_accept_client_test_status(self):
        self.assertNotIn("test_status", server._VisionConfigReq.model_fields)
        self.assertNotIn("tested_identity", server._VisionConfigReq.model_fields)
        self.assertNotIn("tested_at", server._VisionConfigReq.model_fields)

    def test_save_resets_verification_to_pending(self):
        initial = {
            "subscriptions": {
                "__vision_custom__": {"provider": "openai", "baseURL": "https://x/v1", "modelId": "qwen-vl-max", "apiKey": "k"},
            },
            "vision": {
                "enabled": True, "mode": "custom", "subscription": "__vision_custom__", "modelId": "qwen-vl-max",
                "tested_identity": "openai::https://x/v1::qwen-vl-max", "test_status": "verified",
                "test_message": "", "tested_at": 123,
            },
        }
        req = server._VisionConfigReq(
            enabled=True, mode="custom", provider="openai", baseURL="https://x/v1",
            modelId="qwen-vl-max", apiKey="k",
        )
        response, saved = self._call_config(initial, req)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["vision"]["test_status"], "pending")
        self.assertEqual(saved["vision"]["tested_identity"], "")
        self.assertIsNone(saved["vision"].get("tested_at"))

    def test_real_backend_test_persists_verified(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://v.example/v1", modelId="qwen-vl-max", apiKey="k")
        target = VisionTarget("__vision_custom__", sub, "qwen-vl-max", mode="custom",
                              provider="openai", base_url="https://v.example/v1", api_key="k")
        vision_cfg = SimpleNamespace(enabled=True, mode="custom", subscription="__vision_custom__", modelId="qwen-vl-max")
        cfg = _cfg(subscriptions={"__vision_custom__": sub}, vision=vision_cfg)
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps({"subscriptions": {}, "vision": {}}), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "reset_config"),
                patch.object(server, "get_config", return_value=cfg),
                patch.object(server, "resolve_vision_target", return_value=target),
                patch.object(server, "test_vision_capability", new=AsyncMock(return_value={"status": STATUS_VERIFIED, "message": ""})),
            ):
                response = asyncio.run(server.api_vision_test(None))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
        body = json.loads(response.body)
        self.assertEqual(body["status"], STATUS_VERIFIED)
        self.assertEqual(saved["vision"]["test_status"], "verified")
        self.assertEqual(saved["vision"]["tested_identity"], "openai::https://v.example/v1::qwen-vl-max")

    # ── 内部保留订阅 ID ──────────────────────────────────────

    def test_custom_save_creates_reserved_subscription(self):
        req = server._VisionConfigReq(
            enabled=True, mode="custom", provider="openai",
            baseURL="https://api.example.com/v1", modelId="qwen-vl-max", apiKey="secret-custom-key",
        )
        response, saved = self._call_config({"subscriptions": {}}, req)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(json.loads(response.body)["saved"])
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "secret-custom-key")
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["baseURL"], "https://api.example.com/v1")
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["modelId"], "qwen-vl-max")
        self.assertEqual(saved["vision"]["mode"], "custom")
        self.assertEqual(saved["vision"]["subscription"], "__vision_custom__")
        self.assertEqual(saved["vision"]["modelId"], "qwen-vl-max")
        self.assertEqual(saved["vision"]["test_status"], "pending")

    def test_custom_save_does_not_overwrite_user_vision_subscription(self):
        initial = {
            "subscriptions": {
                "vision": {"provider": "openai", "baseURL": "https://user.example/v1", "modelId": "user-model", "apiKey": "user-key"},
            },
        }
        req = server._VisionConfigReq(
            enabled=True, mode="custom", provider="openai",
            baseURL="https://api.example.com/v1", modelId="qwen-vl-max", apiKey="custom-key",
        )
        response, saved = self._call_config(initial, req)
        self.assertEqual(response.status_code, 200)
        # 用户的普通 "vision" 订阅原样保留，未被覆盖
        self.assertEqual(saved["subscriptions"]["vision"]["apiKey"], "user-key")
        self.assertEqual(saved["subscriptions"]["vision"]["baseURL"], "https://user.example/v1")
        # 内部自定义订阅使用保留 ID
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "custom-key")

    def test_custom_save_missing_key_is_blocked(self):
        req = server._VisionConfigReq(
            enabled=True, mode="custom", provider="openai",
            baseURL="https://api.example.com/v1", modelId="qwen-vl-max", apiKey="",
        )
        response, saved = self._call_config({"subscriptions": {}}, req)
        self.assertEqual(response.status_code, 400)
        self.assertIn("请填写 API Key", json.loads(response.body)["error"])
        self.assertNotIn("__vision_custom__", saved.get("subscriptions", {}))

    def test_custom_save_blank_key_retains_existing(self):
        initial = {
            "subscriptions": {
                "__vision_custom__": {"provider": "openai", "baseURL": "https://api.example.com/v1", "modelId": "old-model", "apiKey": "old-custom-key"},
            },
        }
        req = server._VisionConfigReq(
            enabled=True, mode="custom", provider="openai",
            baseURL="https://api.example.com/v1", modelId="qwen-vl-max", apiKey="",
        )
        response, saved = self._call_config(initial, req)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "old-custom-key")
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["modelId"], "qwen-vl-max")

    def test_reuse_mode_save(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://coding.example/v1", modelId="deepseek-chat", apiKey="coding-key")
        req = server._VisionConfigReq(enabled=True, mode="reuse", subscription="coding", modelId="qwen-vl-max")
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps({"subscriptions": {}}), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "reset_config"),
                patch.object(server, "get_config", return_value=_cfg(subscriptions={"coding": sub})),
            ):
                response = asyncio.run(server.api_vision_config(req))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["vision"]["mode"], "reuse")
        self.assertEqual(saved["vision"]["subscription"], "coding")
        self.assertEqual(saved["vision"]["modelId"], "qwen-vl-max")
        self.assertEqual(saved["vision"]["test_status"], "pending")
        # 复用模式不得写 subscriptions
        self.assertNotIn("__vision_custom__", saved.get("subscriptions", {}))

    def test_switch_mode_does_not_delete_internal_subscription(self):
        initial = {
            "subscriptions": {
                "coding": {"provider": "openai", "baseURL": "https://coding.example/v1", "modelId": "deepseek-chat", "apiKey": "coding-key"},
                "__vision_custom__": {"provider": "openai", "baseURL": "https://v.example/v1", "modelId": "qwen-vl-max", "apiKey": "vision-key"},
            },
        }
        sub = SimpleNamespace(provider="openai", baseURL="https://coding.example/v1", modelId="deepseek-chat", apiKey="coding-key")
        req = server._VisionConfigReq(enabled=True, mode="reuse", subscription="coding", modelId="qwen-vl-max")
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(initial), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "reset_config"),
                patch.object(server, "get_config", return_value=_cfg(subscriptions={"coding": sub})),
            ):
                response = asyncio.run(server.api_vision_config(req))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "vision-key")

    # ── 临时测试 / 安全 ─────────────────────────────────────

    def test_temp_test_does_not_persist_key(self):
        initial = {"subscriptions": {}}
        req = server._VisionTestReq(
            mode="custom", provider="openai", baseURL="https://api.example.com/v1",
            modelId="qwen-vl-max", apiKey="temp-secret-123",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(initial), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "reset_config"),
                patch.object(server, "test_vision_capability", new=AsyncMock(return_value={"status": STATUS_VERIFIED, "message": ""})),
            ):
                response = asyncio.run(server.api_vision_test(req))
            saved_text = settings_file.read_text(encoding="utf-8")
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], STATUS_VERIFIED)
        self.assertNotIn("temp-secret-123", saved_text)

    def test_temp_test_blank_key_reuses_saved_custom_key(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://v.example/v1", modelId="qwen-vl-max", apiKey="saved-vision-key")
        req = server._VisionTestReq(
            mode="custom", provider="openai", baseURL="https://v.example/v1",
            modelId="qwen-vl-max", apiKey="",
        )
        test_mock = AsyncMock(return_value={"status": STATUS_VERIFIED, "message": ""})
        with patch.object(server, "get_config", return_value=_cfg(subscriptions={"__vision_custom__": sub})), \
             patch.object(server, "test_vision_capability", new=test_mock):
            response = asyncio.run(server.api_vision_test(req))
        body = json.loads(response.body)
        self.assertEqual(body["status"], STATUS_VERIFIED)
        target = test_mock.call_args[0][0]
        self.assertEqual(target.api_key, "saved-vision-key")
        self.assertEqual(target.model_id, "qwen-vl-max")

    def test_keys_status_does_not_leak_api_key(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://v.example/v1", modelId="qwen-vl-max", apiKey="super-secret-key")
        target = VisionTarget("__vision_custom__", sub, "qwen-vl-max", mode="custom", provider="openai",
                              base_url="https://v.example/v1", api_key="super-secret-key")
        vision_cfg = SimpleNamespace(enabled=True, mode="custom", subscription="__vision_custom__", modelId="qwen-vl-max",
                                     tested_identity="", test_status="pending", test_message="", tested_at=None)
        user_sub = SimpleNamespace(provider="openai", baseURL="https://user.example/v1", modelId="user-model", apiKey="user-key")
        cfg = _cfg(subscriptions={"coding": user_sub, "vision": user_sub, "__vision_custom__": sub}, vision=vision_cfg)
        with patch.object(server, "get_config", return_value=cfg), \
             patch.object(server, "resolve_vision_target", return_value=target):
            response = asyncio.run(server.api_keys_status())
        body = json.loads(response.body)
        self.assertNotIn("super-secret-key", json.dumps(body, ensure_ascii=False))
        self.assertEqual(body["vision"]["mode"], "custom")
        self.assertEqual(body["vision"]["base_url"], "https://v.example/v1")
        self.assertIs(body["vision"]["has_api_key"], True)
        # 内部 "__vision_custom__" 订阅不暴露在复用下拉里（用户自己的 "vision" 订阅则正常显示）
        names = [s["name"] for s in body["subscriptions"]]
        self.assertNotIn("__vision_custom__", names)
        self.assertIn("vision", names)


if __name__ == "__main__":
    unittest.main()
