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
from secgo.web import server, vision_config


def _cfg(subscriptions=None, vision=None):
    return SimpleNamespace(
        llm=SimpleNamespace(vision=vision, subscriptions=subscriptions or {}, agents={}, defaultModel="deepseek-chat", enabled=True),
        web=SimpleNamespace(secretKey="test-secret"),
    )


class WebVisionConfigTests(unittest.TestCase):
    def _call_config(self, settings: dict, req):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(settings), encoding="utf-8")
            with (
                patch.object(vision_config, "SETTINGS_FILE", settings_file),
                patch.object(vision_config, "reset_config"),
            ):
                response = asyncio.run(server.api_vision_config(req))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
            return response, saved

    # ── 信任边界：客户端不能声明 verified ──────────────────────

    def test_config_req_schema_does_not_accept_client_test_status(self):
        self.assertNotIn("test_status", vision_config.VisionConfigRequest.model_fields)
        self.assertNotIn("tested_identity", vision_config.VisionConfigRequest.model_fields)
        self.assertNotIn("tested_at", vision_config.VisionConfigRequest.model_fields)

    # ── verified 保留规则：配置实际变化才重置为 pending ──────────

    def _verified_custom_state(self) -> dict:
        return {
            "subscriptions": {
                "__vision_custom__": {"provider": "openai", "baseURL": "https://x/v1", "modelId": "qwen-vl-max", "apiKey": "k"},
            },
            "vision": {
                "enabled": True, "mode": "custom", "subscription": "__vision_custom__", "modelId": "qwen-vl-max",
                "tested_identity": "openai::https://x/v1::qwen-vl-max", "test_status": "verified",
                "test_message": "ok", "tested_at": 123,
            },
        }

    def _verified_reuse_state(self) -> dict:
        return {
            "subscriptions": {},
            "vision": {
                "enabled": True, "mode": "reuse", "subscription": "coding", "modelId": "qwen-vl-max",
                "tested_identity": "openai::https://coding.example/v1::qwen-vl-max", "test_status": "verified",
                "test_message": "", "tested_at": 456,
            },
        }

    def _assert_kept_verified(self, saved: dict) -> None:
        self.assertEqual(saved["vision"]["test_status"], "verified")
        self.assertEqual(saved["vision"]["tested_identity"], "openai::https://x/v1::qwen-vl-max"
                         if saved["vision"]["mode"] == "custom" else "openai::https://coding.example/v1::qwen-vl-max")
        self.assertEqual(saved["vision"]["tested_at"], 123 if saved["vision"]["mode"] == "custom" else 456)

    def _assert_reset_to_pending(self, saved: dict) -> None:
        self.assertEqual(saved["vision"]["test_status"], "pending")
        self.assertEqual(saved["vision"]["tested_identity"], "")
        self.assertIsNone(saved["vision"].get("tested_at"))

    def _call_config_with_subs(self, settings: dict, req, subscriptions):
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(settings), encoding="utf-8")
            with (
                patch.object(vision_config, "SETTINGS_FILE", settings_file),
                patch.object(vision_config, "reset_config"),
                patch.object(vision_config, "get_config", return_value=_cfg(subscriptions=subscriptions)),
            ):
                response = asyncio.run(server.api_vision_config(req))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
            return response, saved

    def test_save_identical_custom_config_keeps_verified(self):
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai", baseURL="https://x/v1",
            modelId="qwen-vl-max", apiKey="k",
        )
        response, saved = self._call_config(self._verified_custom_state(), req)
        self.assertEqual(response.status_code, 200)
        self._assert_kept_verified(saved)

    def test_save_blank_key_with_unchanged_config_keeps_verified(self):
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai", baseURL="https://x/v1",
            modelId="qwen-vl-max", apiKey="",
        )
        response, saved = self._call_config(self._verified_custom_state(), req)
        self.assertEqual(response.status_code, 200)
        self._assert_kept_verified(saved)
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "k")

    def test_save_changed_model_id_resets_to_pending(self):
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai", baseURL="https://x/v1",
            modelId="qwen-vl-max-2", apiKey="k",
        )
        response, saved = self._call_config(self._verified_custom_state(), req)
        self.assertEqual(response.status_code, 200)
        self._assert_reset_to_pending(saved)
        self.assertEqual(saved["vision"]["modelId"], "qwen-vl-max-2")

    def test_save_changed_base_url_resets_to_pending(self):
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai", baseURL="https://y/v1",
            modelId="qwen-vl-max", apiKey="k",
        )
        response, saved = self._call_config(self._verified_custom_state(), req)
        self.assertEqual(response.status_code, 200)
        self._assert_reset_to_pending(saved)
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["baseURL"], "https://y/v1")

    def test_save_changed_provider_resets_to_pending(self):
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="anthropic", baseURL="https://x/v1",
            modelId="qwen-vl-max", apiKey="k",
        )
        response, saved = self._call_config(self._verified_custom_state(), req)
        self.assertEqual(response.status_code, 200)
        self._assert_reset_to_pending(saved)

    def test_save_replaced_api_key_resets_to_pending(self):
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai", baseURL="https://x/v1",
            modelId="qwen-vl-max", apiKey="brand-new-key",
        )
        response, saved = self._call_config(self._verified_custom_state(), req)
        self.assertEqual(response.status_code, 200)
        self._assert_reset_to_pending(saved)
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "brand-new-key")

    def test_save_changed_mode_resets_to_pending(self):
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai", baseURL="https://z/v1",
            modelId="qwen-vl-max", apiKey="zk",
        )
        response, saved = self._call_config(self._verified_reuse_state(), req)
        self.assertEqual(response.status_code, 200)
        self._assert_reset_to_pending(saved)

    def test_reuse_save_identical_keeps_verified(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://coding.example/v1", modelId="deepseek-chat", apiKey="coding-key")
        req = vision_config.VisionConfigRequest(enabled=True, mode="reuse", subscription="coding", modelId="qwen-vl-max")
        response, saved = self._call_config_with_subs(self._verified_reuse_state(), req, {"coding": sub})
        self.assertEqual(response.status_code, 200)
        self._assert_kept_verified(saved)

    def test_reuse_save_changed_model_resets_to_pending(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://coding.example/v1", modelId="deepseek-chat", apiKey="coding-key")
        req = vision_config.VisionConfigRequest(enabled=True, mode="reuse", subscription="coding", modelId="other-vl-max")
        response, saved = self._call_config_with_subs(self._verified_reuse_state(), req, {"coding": sub})
        self.assertEqual(response.status_code, 200)
        self._assert_reset_to_pending(saved)

    def test_reuse_save_changed_subscription_resets_to_pending(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://other.example/v1", modelId="deepseek-chat", apiKey="other-key")
        req = vision_config.VisionConfigRequest(enabled=True, mode="reuse", subscription="coding2", modelId="qwen-vl-max")
        response, saved = self._call_config_with_subs(self._verified_reuse_state(), req, {"coding2": sub})
        self.assertEqual(response.status_code, 200)
        self._assert_reset_to_pending(saved)
        self.assertEqual(saved["vision"]["subscription"], "coding2")

    def test_disable_then_reenable_unchanged_keeps_verified(self):
        req_off = vision_config.VisionConfigRequest(enabled=False, mode="custom", subscription="", modelId="qwen-vl-max")
        response, saved = self._call_config(self._verified_custom_state(), req_off)
        self.assertEqual(response.status_code, 200)
        self.assertIs(saved["vision"]["enabled"], False)
        self._assert_kept_verified(saved)

        req_on = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai", baseURL="https://x/v1",
            modelId="qwen-vl-max", apiKey="",
        )
        response, saved = self._call_config(saved, req_on)
        self.assertEqual(response.status_code, 200)
        self.assertIs(saved["vision"]["enabled"], True)
        self._assert_kept_verified(saved)

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
                patch.object(vision_config, "SETTINGS_FILE", settings_file),
                patch.object(vision_config, "reset_config"),
                patch.object(vision_config, "get_config", return_value=cfg),
                patch.object(vision_config, "resolve_vision_target", return_value=target),
                patch.object(vision_config, "test_vision_capability", new=AsyncMock(return_value={"status": STATUS_VERIFIED, "message": ""})),
            ):
                response = asyncio.run(server.api_vision_test(None))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
        body = json.loads(response.body)
        self.assertEqual(body["status"], STATUS_VERIFIED)
        self.assertEqual(saved["vision"]["test_status"], "verified")
        self.assertEqual(saved["vision"]["tested_identity"], "openai::https://v.example/v1::qwen-vl-max")

    # ── 内部保留订阅 ID ──────────────────────────────────────

    def test_custom_save_creates_reserved_subscription(self):
        req = vision_config.VisionConfigRequest(
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
        req = vision_config.VisionConfigRequest(
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
        req = vision_config.VisionConfigRequest(
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
        req = vision_config.VisionConfigRequest(
            enabled=True, mode="custom", provider="openai",
            baseURL="https://api.example.com/v1", modelId="qwen-vl-max", apiKey="",
        )
        response, saved = self._call_config(initial, req)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "old-custom-key")
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["modelId"], "qwen-vl-max")

    def test_reuse_mode_save(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://coding.example/v1", modelId="deepseek-chat", apiKey="coding-key")
        req = vision_config.VisionConfigRequest(enabled=True, mode="reuse", subscription="coding", modelId="qwen-vl-max")
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps({"subscriptions": {}}), encoding="utf-8")
            with (
                patch.object(vision_config, "SETTINGS_FILE", settings_file),
                patch.object(vision_config, "reset_config"),
                patch.object(vision_config, "get_config", return_value=_cfg(subscriptions={"coding": sub})),
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
        req = vision_config.VisionConfigRequest(enabled=True, mode="reuse", subscription="coding", modelId="qwen-vl-max")
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(initial), encoding="utf-8")
            with (
                patch.object(vision_config, "SETTINGS_FILE", settings_file),
                patch.object(vision_config, "reset_config"),
                patch.object(vision_config, "get_config", return_value=_cfg(subscriptions={"coding": sub})),
            ):
                response = asyncio.run(server.api_vision_config(req))
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8")) or {}
        self.assertEqual(response.status_code, 200)
        self.assertEqual(saved["subscriptions"]["__vision_custom__"]["apiKey"], "vision-key")

    # ── 临时测试 / 安全 ─────────────────────────────────────

    def test_temp_test_does_not_persist_key(self):
        initial = {"subscriptions": {}}
        req = vision_config.VisionTestRequest(
            mode="custom", provider="openai", baseURL="https://api.example.com/v1",
            modelId="qwen-vl-max", apiKey="temp-secret-123",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(initial), encoding="utf-8")
            with (
                patch.object(vision_config, "SETTINGS_FILE", settings_file),
                patch.object(vision_config, "reset_config"),
                patch.object(vision_config, "test_vision_capability", new=AsyncMock(return_value={"status": STATUS_VERIFIED, "message": ""})),
            ):
                response = asyncio.run(server.api_vision_test(req))
            saved_text = settings_file.read_text(encoding="utf-8")
        body = json.loads(response.body)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["status"], STATUS_VERIFIED)
        self.assertNotIn("temp-secret-123", saved_text)

    def test_temp_test_blank_key_reuses_saved_custom_key(self):
        sub = SimpleNamespace(provider="openai", baseURL="https://v.example/v1", modelId="qwen-vl-max", apiKey="saved-vision-key")
        req = vision_config.VisionTestRequest(
            mode="custom", provider="openai", baseURL="https://v.example/v1",
            modelId="qwen-vl-max", apiKey="",
        )
        test_mock = AsyncMock(return_value={"status": STATUS_VERIFIED, "message": ""})
        with patch.object(vision_config, "get_config", return_value=_cfg(subscriptions={"__vision_custom__": sub})), \
             patch.object(vision_config, "test_vision_capability", new=test_mock):
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
