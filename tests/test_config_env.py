"""config._env_var 环境变量前缀测试：项目只支持 SECGO_*，旧 TIANGONG_* 前缀已废弃。"""

import os
import unittest
from unittest.mock import patch

from secgo.config import config


class EnvPrefixTests(unittest.TestCase):
    def test_secgo_prefix_is_read(self) -> None:
        with patch.dict(os.environ, {"SECGO_API_KEY": "secgo-secret"}, clear=True):
            self.assertEqual(config._env_var("API_KEY"), "secgo-secret")

    def test_legacy_tiangong_prefix_is_ignored(self) -> None:
        """旧前缀失效护栏：TIANGONG_* 已废弃，绝不再被读取。"""
        with patch.dict(os.environ, {"TIANGONG_API_KEY": "legacy-secret"}, clear=True):
            self.assertIsNone(config._env_var("API_KEY"))

    def test_legacy_prefix_does_not_override_secgo(self) -> None:
        with patch.dict(os.environ, {
            "SECGO_API_KEY": "secgo-secret",
            "TIANGONG_API_KEY": "legacy-secret",
        }, clear=True):
            self.assertEqual(config._env_var("API_KEY"), "secgo-secret")


if __name__ == "__main__":
    unittest.main()
