"""静态安全检查：settings.json / .env 不得进入版本控制，示例模板不得含真实密钥。"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class GitSecretSafetyTests(unittest.TestCase):
    def test_settings_and_env_are_gitignored(self):
        gitignore = REPO_ROOT / ".gitignore"
        self.assertTrue(gitignore.is_file(), ".gitignore 缺失")
        patterns = {line.strip() for line in gitignore.read_text(encoding="utf-8").splitlines()}
        self.assertIn("settings.json", patterns)
        self.assertIn(".env", patterns)

    def test_example_template_has_no_real_key(self):
        example = REPO_ROOT / "settings.example.json"
        if not example.is_file():
            self.skipTest("settings.example.json 不存在")
        text = example.read_text(encoding="utf-8")
        # 不得包含真实 API Key 形态（sk- 开头 + 长随机串）
        self.assertNotRegex(text, r"sk-[A-Za-z0-9_-]{16,}")
        # api_key / apiKey 字段应为空示例值
        self.assertNotIn('"api_key": "sk', text)
        self.assertNotIn('"apiKey": "sk', text)


if __name__ == "__main__":
    unittest.main()
