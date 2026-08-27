"""Run Budget 配置加载测试：只验证新命名（max_steps_per_run / max_replans_per_run / max_tokens_per_run）。"""

import os
import unittest
from unittest.mock import patch

from secgo.config import config


class BudgetConfigLoadTests(unittest.TestCase):
    """验证 JSON 新字段 / ENV 新字段 / 默认值 / 旧字段已失效。"""

    def _load(self, settings, env=None):
        """在隔离环境中加载配置：第一个 jsonc 文件当 settings.json，其余当空。"""
        env = dict(env or {})
        calls = {"n": 0}

        def fake_read(_path):
            calls["n"] += 1
            return settings if calls["n"] == 1 else {}

        with (
            patch.object(config, "_read_jsonc_file", side_effect=fake_read),
            patch.dict(os.environ, env, clear=True),
        ):
            return config.load_config()

    def test_defaults_when_nothing_configured(self):
        cfg = self._load({})
        self.assertEqual(cfg.budget.maxStepsPerRun, 50)
        self.assertEqual(cfg.budget.maxReplansPerRun, 3)
        self.assertEqual(cfg.budget.maxTokensPerRun, 100_000)

    def test_new_json_keys_are_read(self):
        cfg = self._load({
            "run_limits": {
                "max_steps_per_run": 7,
                "max_replans_per_run": 5,
                "max_tokens_per_run": 12345,
            },
        })
        self.assertEqual(cfg.budget.maxStepsPerRun, 7)
        self.assertEqual(cfg.budget.maxReplansPerRun, 5)
        self.assertEqual(cfg.budget.maxTokensPerRun, 12345)

    def test_new_env_keys_override_json(self):
        cfg = self._load(
            {
                "run_limits": {
                    "max_steps_per_run": 7,
                    "max_replans_per_run": 5,
                    "max_tokens_per_run": 12345,
                },
            },
            env={
                "SECGO_MAX_STEPS_PER_RUN": "11",
                "SECGO_MAX_REPLANS_PER_RUN": "9",
                "SECGO_MAX_TOKENS_PER_RUN": "99999",
            },
        )
        self.assertEqual(cfg.budget.maxStepsPerRun, 11)
        self.assertEqual(cfg.budget.maxReplansPerRun, 9)
        self.assertEqual(cfg.budget.maxTokensPerRun, 99999)

    def test_old_keys_and_old_env_are_ignored(self):
        """旧 JSON 键 / 旧 ENV 名已被彻底删除，不再影响配置。"""
        cfg = self._load(
            {
                "run_limits": {
                    "max_steps": 1,
                    "max_replans": 2,
                    "max_tokens_session": 3,
                },
            },
            env={
                "SECGO_MAX_STEPS": "4",
                "SECGO_MAX_REPLANS": "5",
                "SECGO_MAX_TOKENS_SESSION": "6",
            },
        )
        # 旧名全部失效 → 回落到默认值
        self.assertEqual(cfg.budget.maxStepsPerRun, 50)
        self.assertEqual(cfg.budget.maxReplansPerRun, 3)
        self.assertEqual(cfg.budget.maxTokensPerRun, 100_000)


if __name__ == "__main__":
    unittest.main()
