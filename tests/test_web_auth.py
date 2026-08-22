import importlib
import unittest

from secgo.web import server


class WebAuthenticationTests(unittest.TestCase):
    def test_session_token_remains_valid_during_same_server_run(self) -> None:
        token = server._make_session_token()

        self.assertTrue(server._verify_session_token(token))

    def test_session_token_is_invalid_after_server_restart(self) -> None:
        token = server._make_session_token()

        restarted_server = importlib.reload(server)

        self.assertFalse(restarted_server._verify_session_token(token))


if __name__ == "__main__":
    unittest.main()
