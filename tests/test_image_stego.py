"""图片隐写分析测试：全部用程序化构造的 PNG/BMP 字节流，不依赖真实图片样本。"""

from __future__ import annotations

import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from secgo.runtime.image_stego import (
    analyze_image_stego,
    format_stego_summary,
    image_stego_lines,
)

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


# ── 字节流构造辅助 ─────────────────────────────────────────


def _chunk(typ: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)


def _make_png(ihdr: bytes, idat: bytes, extra: bytes = b"", trailing: bytes = b"") -> bytes:
    return _PNG_SIG + _chunk(b"IHDR", ihdr) + extra + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"") + trailing


def _ihdr(width: int, height: int, bit_depth: int = 8, color_type: int = 2, interlace: int = 0) -> bytes:
    return struct.pack(">IIBBBBB", width, height, bit_depth, color_type, 0, 0, interlace)


def _make_lsb_png(message: bytes, width: int = 16, height: int = 8) -> bytes:
    """把 message 的 bit 依序塞进 RGB 像素每个字节的最低位的 PNG。"""
    bits = "".join(f"{b:08b}" for b in message)
    pixels = bytearray(width * height * 3)
    for i, ch in enumerate(bits):
        if ch == "1":
            pixels[i] |= 1
    raw = b""
    for r in range(height):
        row = bytes(pixels[r * width * 3:(r + 1) * width * 3])
        raw += b"\x00" + row  # filter type 0
    return _make_png(_ihdr(width, height), zlib.compress(raw))


def _make_lsb_bmp(message: bytes, width: int = 16, height: int = 8, bpp: int = 24) -> bytes:
    """把 message 的 bit 塞进 BMP 像素字节最低位（含行 padding）。"""
    nbytes = bpp // 8
    row_size = width * nbytes
    stride = (row_size + 3) & ~3
    bits = "".join(f"{b:08b}" for b in message)
    pixels = bytearray(row_size * height)
    for i, ch in enumerate(bits):
        if ch == "1":
            pixels[i] |= 1
    file_size = 54 + stride * height
    fileheader = b"BM" + struct.pack("<IHHI", file_size, 0, 0, 54)
    infoheader = struct.pack("<IiiHHIIiiII", 40, width, height, 1, bpp, 0, stride * height, 2835, 2835, 0, 0)
    pixel_data = b""
    for r in range(height):
        row = bytes(pixels[r * row_size:(r + 1) * row_size])
        pixel_data += row + b"\x00" * (stride - row_size)
    return fileheader + infoheader + pixel_data


def _make_png_with_trailing(trailing: bytes) -> bytes:
    idat = zlib.compress(b"\x00" + b"\x00\x00\x00")  # 1x1 RGB
    return _make_png(_ihdr(1, 1), idat, trailing=trailing)


def _make_png_with_text(text: bytes) -> bytes:
    idat = zlib.compress(b"\x00" + b"\x00\x00\x00")
    tex = b"Comment\x00" + text
    return _make_png(_ihdr(1, 1), idat, extra=_chunk(b"tEXt", tex))


# ── 解析用例 ───────────────────────────────────────────────


class ImageStegoParseTests(unittest.TestCase):
    def test_png_lsb_flag(self):
        msg = b"flag{lsb_hidden_in_png}"
        result = analyze_image_stego(_make_lsb_png(msg))
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "png")
        self.assertIn(msg, result["lsb"])

    def test_bmp_lsb_flag(self):
        msg = b"flag{lsb_hidden_in_bmp}"
        result = analyze_image_stego(_make_lsb_bmp(msg))
        self.assertIsNotNone(result)
        self.assertEqual(result["kind"], "bmp")
        self.assertIn(msg, result["lsb"])

    def test_bmp_padding_skipped(self):
        # width=5 → row_size=15，stride=16（每行 1 字节 padding），跳过 padding 后 LSB 才对位
        msg = b"flag{bmp_padding_ok}"
        result = analyze_image_stego(_make_lsb_bmp(msg, width=5, height=16))
        self.assertIn(msg, result["lsb"])

    def test_png_trailing_detected(self):
        trailing = b"flag{hidden_after_iend}"
        result = analyze_image_stego(_make_png_with_trailing(trailing))
        self.assertEqual(result["trailing"], trailing)

    def test_png_text_chunk(self):
        # 精确相等断言：tEXt 的 text 部分必须等于原文本，不能混入 CRC 等尾随字节
        result = analyze_image_stego(_make_png_with_text(b"flag{in_comment_chunk}"))
        self.assertEqual(result["chunk_texts"], ["flag{in_comment_chunk}"])

    def test_png_interlaced_unsupported(self):
        result = analyze_image_stego(_make_png(_ihdr(8, 8, interlace=1), b"x"))
        self.assertIn("interlaced", result["lsb_note"])

    def test_png_palette_unsupported(self):
        result = analyze_image_stego(_make_png(_ihdr(8, 8, color_type=3), b"x"))
        self.assertIn("palette", result["lsb_note"])

    def test_png_huge_dimensions_rejected(self):
        # 声明超大 height（解压后约 4 亿字节），应在解压前被尺寸上限拦截，避免解压炸弹
        result = analyze_image_stego(_make_png(_ihdr(1, 100_000_000), zlib.compress(b"\x00\x00\x00\x00")))
        self.assertIsNotNone(result)
        self.assertIn("过大", result["lsb_note"])

    def test_unsupported_format_returns_none(self):
        self.assertIsNone(analyze_image_stego(b"\xff\xd8\xff\xe0" + b"\x00" * 20))  # JPEG
        self.assertIsNone(analyze_image_stego(b"GIF89a" + b"\x00" * 20))
        self.assertIsNone(analyze_image_stego(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 20))


class ImageStegoFormattingTests(unittest.TestCase):
    def test_format_lsb_flag(self):
        text = format_stego_summary(analyze_image_stego(_make_lsb_png(b"flag{fmt_check}")))
        self.assertIn("[图片隐写分析]", text)
        self.assertIn("flag{fmt_check}", text)

    def test_format_trailing(self):
        result = analyze_image_stego(_make_png_with_trailing(b"secret tail"))
        self.assertIn("尾随数据", format_stego_summary(result))


class ImageStegoIntegrationTests(unittest.TestCase):
    def test_image_stego_lines(self):
        data = _make_lsb_png(b"flag{via_lines}")
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
            handle.write(data)
            path = Path(handle.name)
        try:
            lines = image_stego_lines(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertTrue(lines)
        self.assertTrue(any("flag{via_lines}" in line for line in lines))

    def test_image_stego_lines_unsupported_returns_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as handle:
            handle.write(b"\xff\xd8\xff\xe0" + b"\x00" * 20)
            path = Path(handle.name)
        try:
            lines = image_stego_lines(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
