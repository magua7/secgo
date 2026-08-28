import asyncio
import hashlib
import importlib
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from secgo.web import server


def _cfg_with_password(hash_value: str = "", plain: str = "") -> SimpleNamespace:
    return SimpleNamespace(web=SimpleNamespace(
        secretKey="test-secret",
        adminPasswordHash=hash_value,
        adminPassword=plain,
    ))


class WebAuthenticationTests(unittest.TestCase):
    def test_fixed_password_used_only_when_nothing_configured(self) -> None:
        """settings.json 未配置任何密码时，回落固定演示密码（开发便利）。"""
        with patch.object(server, "get_config", return_value=_cfg_with_password()):
            self.assertTrue(server._auth_enabled())
            self.assertTrue(server._password_matches("secgo123"))
            self.assertFalse(server._password_matches("wrong-password"))

    def test_settings_hash_takes_priority_over_fixed_password(self) -> None:
        """settings.json 的 admin_password_hash 必须生效（修复死配置问题）。"""
        digest = hashlib.sha256(b"my-strong-pw").hexdigest()
        with patch.object(server, "get_config", return_value=_cfg_with_password(hash_value=digest)):
            self.assertTrue(server._auth_enabled())
            self.assertTrue(server._password_matches("my-strong-pw"))
            self.assertFalse(server._password_matches("secgo123"))

    def test_settings_plain_password_supported(self) -> None:
        with patch.object(server, "get_config", return_value=_cfg_with_password(plain="plain-pw")):
            self.assertTrue(server._password_matches("plain-pw"))
            self.assertFalse(server._password_matches("secgo123"))

    def test_root_requires_login_when_password_is_enabled(self) -> None:
        with patch.object(server, "_is_logged_in", return_value=False):
            response = asyncio.run(server.root(None))
        self.assertTrue(response.path.endswith("login.html"))

    def test_root_enters_application_with_valid_login(self) -> None:
        with patch.object(server, "_is_logged_in", return_value=True):
            response = asyncio.run(server.root("valid-token"))
        self.assertTrue(response.path.endswith("index.html"))

    def test_session_token_remains_valid_during_same_server_run(self) -> None:
        token = server._make_session_token()

        self.assertTrue(server._verify_session_token(token))

    def test_session_token_is_invalid_after_server_restart(self) -> None:
        token = server._make_session_token()

        restarted_server = importlib.reload(server)

        self.assertFalse(restarted_server._verify_session_token(token))


if __name__ == "__main__":
    unittest.main()
