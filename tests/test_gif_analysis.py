"""GIF 结构解析测试：程序化构造 GIF 字节流，覆盖 comment/调色板/application/尾随/集成。"""

import os
import struct
import tempfile
import unittest
from pathlib import Path

from secgo.runtime.gif_analysis import (
    GIF_TEXT_LIMIT,
    analyze_gif_bytes,
    format_gif_summary,
)
from secgo.runtime.image_stego import image_stego_lines


def _subblock(data: bytes) -> bytes:
    """单个子块 + 终止符（size + data + 0x00）。"""
    return bytes([len(data)]) + data + b"\x00"


def _make_gif(trailing: bytes = b"", comment: bytes = b"flag{gif_comment_test}") -> bytes:
    data = bytearray()
    data += b"GIF89a"
    # LSD: width=2 height=3, packed=0x80(GCT flag + size0 → 2 entries), bg=0, aspect=0
    data += struct.pack("<HHBBB", 2, 3, 0x80, 0, 0)
    # GCT: 2 entries × 3B = 6 字节，藏可打印串 "secret"
    data += b"secret"
    # Comment extension
    data += b"\x21\xfe" + _subblock(comment)
    # Plain Text extension（12 字节网格头 + 文本子块）
    data += b"\x21\x01" + bytes([12]) + b"\x00" * 12 + _subblock(b"pt text")
    # Application extension（NETSCAPE2.0 循环）
    data += b"\x21\xff" + bytes([11]) + b"NETSCAPE" + b"2.0" + _subblock(b"\x01\x00\x00")
    # Image Descriptor（无局部调色板）
    data += b"\x2c" + struct.pack("<HHHHB", 0, 0, 2, 3, 0) + b"\x02" + _subblock(b"\x4c\x01")
    # Trailer
    data += b"\x3b"
    data += trailing
    return bytes(data)


class ParseTests(unittest.TestCase):
    def test_dimensions(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertEqual(result["dimensions"], {"width": 2, "height": 3})

    def test_comment(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertEqual(result["comments"], ["flag{gif_comment_test}"])

    def test_plain_text(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertEqual(result["plain_texts"], ["pt text"])

    def test_application(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertEqual(len(result["applications"]), 1)
        self.assertEqual(result["applications"][0]["id"], "NETSCAPE")
        self.assertEqual(result["applications"][0]["auth"], "2.0")

    def test_palette_strings(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertIn("secret", result["palette_strings"])

    def test_frames(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertEqual(result["frames"], [{"left": 0, "top": 0, "width": 2, "height": 3}])

    def test_trailing_zip(self):
        result = analyze_gif_bytes(_make_gif(trailing=b"PK\x03\x04\x00\x00extra"))
        self.assertEqual(result["trailing"]["size"], 11)
        self.assertEqual(result["trailing"]["kind"], "zip")

    def test_no_trailing(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertIsNone(result["trailing"])

    def test_findings_flag(self):
        result = analyze_gif_bytes(_make_gif())
        self.assertTrue(any("Comment" in f and "flag{gif_comment_test}" in f for f in result["findings"]))

    def test_non_gif_raises(self):
        with self.assertRaises(ValueError):
            analyze_gif_bytes(b"\x89PNG\r\n\x1a\n")


class FormattingTests(unittest.TestCase):
    def test_format_basic(self):
        text = format_gif_summary(analyze_gif_bytes(_make_gif()))
        self.assertIn("[GIF 图片]", text)
        self.assertIn("flag{gif_comment_test}", text)
        self.assertIn("secret", text)

    def test_format_truncated(self):
        result = {
            "kind": "gif",
            "dimensions": None,
            "frames": [],
            "comments": ["A" * 9000],
            "plain_texts": [],
            "applications": [],
            "palette_strings": [],
            "trailing": None,
            "findings": [],
        }
        text = format_gif_summary(result)
        self.assertIn("[GIF 摘要已截断]", text)
        self.assertLessEqual(len(text), GIF_TEXT_LIMIT + 40)


class IntegrationTests(unittest.TestCase):
    def test_image_stego_lines_gif(self):
        with tempfile.NamedTemporaryFile(suffix=".gif", delete=False) as f:
            f.write(_make_gif())
            path = f.name
        try:
            lines = image_stego_lines(Path(path))
            self.assertTrue(lines)
            self.assertIn("[GIF 图片]", lines[0])
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
