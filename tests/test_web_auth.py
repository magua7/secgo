import asyncio
import importlib
import unittest
from unittest.mock import patch

from secgo.web import server


class WebAuthenticationTests(unittest.TestCase):
    def test_fixed_web_password_is_enabled(self) -> None:
        self.assertTrue(server._auth_enabled())
        self.assertTrue(server._password_matches("secgo123"))
        self.assertFalse(server._password_matches("wrong-password"))

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
