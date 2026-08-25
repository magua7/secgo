from __future__ import annotations

import json
import asyncio
import tempfile
import unittest
from contextlib import ExitStack
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
        validator=None,
    ) -> tuple[str | None, dict | None, dict]:
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(initial), encoding="utf-8")
            with ExitStack() as stack:
                stack.enter_context(patch.object(server, "SETTINGS_FILE", settings_file))
                stack.enter_context(patch.object(server, "reset_config"))
                if validator is not None:
                    stack.enter_context(patch.object(server, "_validate_subscription", side_effect=validator))
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

        self.assertIn("默认模型", error)
        self.assertFalse(body["saved"])
        self.assertIn("掩码", body["validation"]["default"]["error"])
        self.assertEqual(saved, initial)

    def test_all_agent_ids_use_semantic_subscriptions(self) -> None:
        default = {
            "provider": "openai",
            "base_url": "https://default.example/v1",
            "model": "default-model",
            "api_key": "default-key",
        }
        for agent_id in ("planner", "research", "builder", "operator"):
            with self.subTest(agent_id=agent_id):
                config = {
                    "provider": f"{agent_id}-provider",
                    "base_url": f"https://{agent_id}.example/v1",
                    "model": f"{agent_id}-model",
                    "api_key": f"{agent_id}-key",
                }
                error, body, saved = self._attempt_new_save(
                    {},
                    default,
                    {agent_id: {"enabled": True, "config": config}},
                    validator=lambda provider, url, key, model: (True, ""),
                )
                self.assertIsNone(error)
                self.assertTrue(body["saved"])
                self.assertEqual(saved["agents"][agent_id]["subscription"], agent_id)
                self.assertEqual(saved["subscriptions"][agent_id]["apiKey"], f"{agent_id}-key")

    def test_disabling_agent_preserves_subscription_and_key(self) -> None:
        initial = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "base_url": "https://default.example/v1",
                "model": "default-model",
                "api_key": "default-key",
            },
            "subscriptions": {
                "coding": {
                    "provider": "openai", "baseURL": "https://default.example/v1",
                    "modelId": "default-model", "apiKey": "default-key",
                },
                "research": {
                    "provider": "openai", "baseURL": "https://research.example/v1",
                    "modelId": "research-model", "apiKey": "research-key",
                },
            },
            "agents": {
                "research": {
                    "subscription": "research", "modelId": "research-model", "thinkingLevel": "medium",
                }
            },
        }
        error, body, saved = self._attempt_new_save(
            initial,
            {"provider": "openai", "base_url": "https://default.example/v1", "model": "default-model"},
            {"research": {"enabled": False, "config": {}}},
        )

        self.assertIsNone(error)
        self.assertTrue(body["saved"])
        self.assertNotIn("research", saved["agents"])
        self.assertEqual(saved["subscriptions"]["research"]["apiKey"], "research-key")

    def test_one_agent_validation_failure_aborts_every_change(self) -> None:
        initial = {
            "llm": {
                "enabled": True,
                "provider": "openai",
                "base_url": "https://old.example/v1",
                "model": "old-default",
                "api_key": "old-default-key",
            },
            "subscriptions": {
                "coding": {
                    "provider": "openai", "baseURL": "https://old.example/v1",
                    "modelId": "old-default", "apiKey": "old-default-key",
                }
            },
            "agents": {},
        }
        default = {
            "provider": "openai", "base_url": "https://new.example/v1",
            "model": "new-default", "api_key": "new-default-key",
        }
        agents = {
            agent_id: {
                "enabled": True,
                "config": {
                    "provider": "openai", "base_url": f"https://{agent_id}.example/v1",
                    "model": "bad-research" if agent_id == "research" else f"{agent_id}-model",
                    "api_key": f"{agent_id}-key",
                },
            }
            for agent_id in ("planner", "research", "builder", "operator")
        }

        error, body, saved = self._attempt_new_save(
            initial,
            default,
            agents,
            True,
            validator=lambda provider, url, key, model: (False, "HTTP 401") if model == "bad-research" else (True, ""),
        )

        self.assertIn("Research", error)
        self.assertFalse(body["saved"])
        self.assertTrue(body["validation"]["default"]["ok"])
        self.assertTrue(body["validation"]["planner"]["ok"])
        self.assertFalse(body["validation"]["research"]["ok"])
        self.assertTrue(body["validation"]["builder"]["ok"])
        self.assertTrue(body["validation"]["operator"]["ok"])
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
                patch.object(server, "_validate_subscription", return_value=(True, "")),
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

    def test_keys_status_returns_all_agent_masks_and_enabled_state(self) -> None:
        def sub(name: str, key: str):
            return SimpleNamespace(
                provider="openai",
                baseURL=f"https://{name}.example/v1",
                modelId=f"{name}-model",
                apiKey=key,
            )

        subscriptions = {
            "coding": sub("default", "default-secret-key"),
            "planner": sub("planner", "planner-secret-key"),
            "research": sub("research", "research-secret-key"),
            "builder": sub("builder", "builder-secret-key"),
            "operator": sub("operator", "operator-secret-key"),
        }
        loaded_agents = {
            "planner": SimpleNamespace(subscription="planner", modelId="planner-model"),
            "research": SimpleNamespace(subscription="research", modelId="research-model"),
            "builder": SimpleNamespace(subscription="coding", modelId="default-model"),
            "operator": SimpleNamespace(subscription="coding", modelId="default-model"),
        }
        cfg = SimpleNamespace(llm=SimpleNamespace(subscriptions=subscriptions, agents=loaded_agents))
        raw = {
            "subscriptions": {
                name: {
                    "provider": value.provider,
                    "baseURL": value.baseURL,
                    "modelId": value.modelId,
                    "apiKey": value.apiKey,
                }
                for name, value in subscriptions.items()
            },
            "agents": {
                "planner": {"subscription": "planner", "modelId": "planner-model"},
                "research": {"subscription": "research", "modelId": "research-model"},
            },
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(raw), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "get_config", return_value=cfg),
                patch.object(server, "_config_ready", return_value=True),
                patch.object(server, "_auth_enabled", return_value=True),
            ):
                response = asyncio.run(server.api_keys_status())

        body = json.loads(response.body)
        self.assertTrue(body["default"]["has_key"])
        self.assertEqual(body["default"]["api_key_masked"], "def***key")
        self.assertTrue(body["agents"]["planner"]["enabled"])
        self.assertTrue(body["agents"]["research"]["enabled"])
        self.assertFalse(body["agents"]["builder"]["enabled"])
        self.assertTrue(body["agents"]["builder"]["has_key"])
        self.assertFalse(body["agents"]["operator"]["enabled"])
        encoded = response.body.decode("utf-8")
        self.assertNotIn("builder-secret-key", encoded)
        self.assertNotIn("operator-secret-key", encoded)

    def test_keys_status_does_not_count_injected_default_key_as_agent_key(self) -> None:
        coding = SimpleNamespace(
            provider="openai", baseURL="https://default.example/v1",
            modelId="default-model", apiKey="default-key",
        )
        # The config loader injects the Default key into weak subscriptions for runtime fallback.
        research = SimpleNamespace(
            provider="openai", baseURL="https://research.example/v1",
            modelId="research-model", apiKey="default-key",
        )
        cfg = SimpleNamespace(llm=SimpleNamespace(
            subscriptions={"coding": coding, "research": research},
            agents={"research": SimpleNamespace(subscription="coding", modelId="default-model")},
        ))
        raw = {
            "subscriptions": {
                "coding": {
                    "provider": "openai", "baseURL": coding.baseURL,
                    "modelId": coding.modelId, "apiKey": coding.apiKey,
                },
                "research": {
                    "provider": "openai", "baseURL": research.baseURL,
                    "modelId": research.modelId, "apiKey": "",
                },
            },
            "agents": {},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            settings_file = Path(temp_dir) / "settings.json"
            settings_file.write_text(json.dumps(raw), encoding="utf-8")
            with (
                patch.object(server, "SETTINGS_FILE", settings_file),
                patch.object(server, "get_config", return_value=cfg),
                patch.object(server, "_config_ready", return_value=True),
                patch.object(server, "_auth_enabled", return_value=True),
            ):
                response = asyncio.run(server.api_keys_status())

        body = json.loads(response.body)
        self.assertFalse(body["agents"]["research"]["has_key"])
        self.assertEqual(body["agents"]["research"]["api_key_masked"], "")


if __name__ == "__main__":
    unittest.main()
