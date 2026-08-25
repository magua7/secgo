from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from secgo.web import server


class WebModelSettingsTests(unittest.TestCase):
    def _attempt_new_save(
        self,
        initial: dict,
        default: dict,
        agents: dict,
        validate_keys: bool = False,
    ) -> tuple[str | None, dict | None, dict]:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(initial), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "reset_config"),
            ):
                error, body = server._save_model_config(default, agents, validate_keys)
            saved = server.parse_jsonc(settings_file.read_text(encoding="utf-8"))
            return error, body, saved

    def test_default_omitted_key_reuses_persisted_key(self) -> None:
        initial = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "base_url": "https://old.example/v1",
                "model": "old-model",
                "api_key": "stored-default",
            },
            "subscriptions": {
                "coding": {
                    "provider": "openai",
                    "baseURL": "https://old.example/v1",
                    "modelId": "old-model",
                    "apiKey": "stored-default",
                }
            },
            "agents": {},
        }

        error, body, saved = self._attempt_new_save(
            initial,
            {
                "provider": "openai",
                "base_url": "https://new.example/v1",
                "model": "new-model",
            },
            {},
        )

        self.assertIsNone(error)
        self.assertTrue(body["saved"])
        self.assertEqual(saved["llm"]["api_key"], "stored-default")
        self.assertEqual(saved["subscriptions"]["coding"]["apiKey"], "stored-default")

    def test_masked_value_is_never_accepted_as_a_key(self) -> None:
        initial = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "base_url": "https://api.example/v1",
                "model": "working-model",
                "api_key": "working-default",
            }
        }

        error, body, saved = self._attempt_new_save(
            initial,
            {
                "provider": "openai",
                "base_url": "https://api.example/v1",
                "model": "replacement-model",
                "api_key": "sk-***9e",
            },
            {},
        )

        self.assertIn("掩码", error)
        self.assertFalse(body["saved"])
        self.assertIn("掩码", body["validation"]["default"]["error"])
        self.assertEqual(saved, initial)

    def _save(
        self,
        initial: dict,
        default: dict,
        planner: dict | None,
    ) -> dict:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(initial), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "reset_config"),
            ):
                error, body = server._save_model_config(default, planner, False)
            self.assertIsNone(error)
            self.assertTrue(body["ok"])
            self.assertTrue(body["saved"])
            self.assertEqual(body["next"], "/")
            return server.parse_jsonc(settings_file.read_text(encoding="utf-8"))

    def test_custom_provider_is_saved_verbatim(self) -> None:
        saved = self._save(
            {},
            {
                "provider": "SiliconFlow",
                "base_url": "https://api.siliconflow.cn/v1",
                "model": "Qwen/Qwen3-32B",
                "api_key": "secret",
            },
            None,
        )

        self.assertEqual(saved["llm"]["provider"], "SiliconFlow")
        self.assertEqual(saved["subscriptions"]["coding"]["provider"], "SiliconFlow")
        self.assertEqual(saved["subscriptions"]["coding"]["modelId"], "Qwen/Qwen3-32B")

    def test_planner_uses_its_configured_model_in_planner_subscription(self) -> None:
        saved = self._save(
            {},
            {
                "provider": "custom-default",
                "base_url": "https://default.example/v1",
                "model": "default-model",
                "api_key": "default-key",
            },
            {
                "provider": "custom-planner",
                "base_url": "https://planner.example/v1",
                "model": "planner-model",
                "api_key": "planner-key",
            },
        )

        self.assertEqual(saved["agents"]["planner"]["subscription"], "planner")
        self.assertEqual(saved["subscriptions"]["planner"]["provider"], "custom-planner")
        self.assertEqual(saved["subscriptions"]["planner"]["modelId"], "planner-model")
        self.assertNotIn("glm", saved["subscriptions"])

    def test_disabling_planner_removes_planner_override_and_reuses_default(self) -> None:
        saved = self._save(
            {
                "subscriptions": {
                    "glm": {
                        "provider": "glm",
                        "baseURL": "https://open.bigmodel.cn/api/paas/v4",
                        "modelId": "glm-5.2",
                        "apiKey": "old-key",
                    }
                },
                "agents": {
                    "planner": {
                        "subscription": "glm",
                        "modelId": "glm-5.2",
                        "thinkingLevel": "medium",
                    }
                },
            },
            {
                "provider": "custom-default",
                "base_url": "https://default.example/v1",
                "model": "default-model",
                "api_key": "default-key",
            },
            None,
        )

        self.assertNotIn("planner", saved["agents"])
        self.assertIn("glm", saved["subscriptions"])
        self.assertEqual(saved["subscriptions"]["coding"]["modelId"], "default-model")

    def test_status_does_not_report_invalid_legacy_planner_as_enabled(self) -> None:
        coding = SimpleNamespace(provider="custom", baseURL="https://default.example/v1", modelId="default-model", apiKey="default-key")
        legacy = SimpleNamespace(provider="openai", baseURL="https://planner.example/v1", modelId="glm-5.2", apiKey="default-key")
        cfg = SimpleNamespace(llm=SimpleNamespace(
            subscriptions={"coding": coding, "glm": legacy},
            agents={"planner": SimpleNamespace(subscription="coding", modelId="default-model")},
        ))
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps({
                "agents": {"planner": {"subscription": "glm", "modelId": "glm-5.2"}},
            }), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "get_config", return_value=cfg),
                patch.object(server, "_config_ready", return_value=True),
                patch.object(server, "_auth_enabled", return_value=True),
            ):
                response = asyncio.run(server.api_keys_status())

        body = json.loads(response.body)
        self.assertFalse(body["has_planner"])
        self.assertIsNone(body["planner"])


if __name__ == "__main__":
    unittest.main()
