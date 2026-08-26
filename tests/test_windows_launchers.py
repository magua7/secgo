"""Windows launcher static checks：batch 启动器必须 ASCII-only（防止 cmd.exe 乱码/误解析）。"""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WindowsLauncherAsciiTests(unittest.TestCase):
    def test_windows_launchers_are_ascii_only(self):
        for name in ("web.bat", "cli.bat"):
            data = (ROOT / name).read_bytes()
            self.assertFalse(
                data.startswith(b"\xef\xbb\xbf"),
                f"{name} must not have a UTF-8 BOM",
            )
            self.assertTrue(
                all(byte < 128 for byte in data),
                f"{name} contains non-ASCII bytes; batch launchers must be ASCII-only",
            )
            data.decode("ascii")  # raises UnicodeDecodeError if any byte >= 128


if __name__ == "__main__":
    unittest.main()
