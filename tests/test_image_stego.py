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


def _make_png_with_itxt(text: bytes, compressed: bool = False) -> bytes:
    idat = zlib.compress(b"\x00" + b"\x00\x00\x00")
    text_data = zlib.compress(text) if compressed else text
    comp_flag = 1 if compressed else 0
    itxt = b"Comment\x00" + bytes([comp_flag, 0]) + b"\x00\x00" + text_data
    return _make_png(_ihdr(1, 1), idat, extra=_chunk(b"iTXt", itxt))


_ADAM7 = ((0, 0, 8, 8), (0, 4, 8, 8), (4, 0, 8, 4), (0, 2, 4, 4), (2, 0, 4, 2), (0, 1, 2, 2), (1, 0, 2, 1))


def _make_palette_lsb_png(message: bytes, width: int = 32, height: int = 8, bit_depth: int = 1) -> bytes:
    """palette 索引图：索引值 bit0 藏 message bit。"""
    bits = "".join(f"{b:08b}" for b in message)
    indices = [1 if ch == "1" else 0 for ch in bits][:width * height]
    indices.extend([0] * (width * height - len(indices)))
    per_byte = 8 // bit_depth
    raw = b""
    for r in range(height):
        row_bytes = bytearray()
        for i in range(0, width, per_byte):
            byte = 0
            for j in range(per_byte):
                if i + j < width:
                    byte = (byte << bit_depth) | indices[r * width + i + j]
            row_bytes.append(byte)
        raw += b"\x00" + bytes(row_bytes)
    plte = b"\x00\x00\x00" * (1 << bit_depth)
    return _make_png(_ihdr(width, height, bit_depth=bit_depth, color_type=3), zlib.compress(raw), extra=_chunk(b"PLTE", plte))


def _make_interlaced_lsb_png(message: bytes, width: int = 8, height: int = 8) -> bytes:
    """Adam7 interlaced RGB 图：按 7 pass 顺序生成 raw，像素 LSB 藏 message。"""
    bits = "".join(f"{b:08b}" for b in message)
    full = bytearray(width * height * 3)
    for i, ch in enumerate(bits):
        if ch == "1":
            full[i] |= 1
    raw = b""
    for start_x, start_y, step_x, step_y in _ADAM7:
        if width <= start_x or height <= start_y:
            continue
        pass_w = (width - start_x + step_x - 1) // step_x
        pass_h = (height - start_y + step_y - 1) // step_y
        for py in range(pass_h):
            row = bytearray()
            for px in range(pass_w):
                tx = start_x + px * step_x
                ty = start_y + py * step_y
                src = (ty * width + tx) * 3
                row += full[src:src + 3]
            raw += b"\x00" + bytes(row)
    return _make_png(_ihdr(width, height, interlace=1), zlib.compress(raw))


def _make_lsb_png_16bit(message: bytes, width: int = 8, height: int = 8) -> bytes:
    """16 位深 RGB：每个 16-bit 样本的低字节 bit0 藏 message bit。"""
    bits = "".join(f"{b:08b}" for b in message)
    pixels = bytearray(width * height * 6)
    for i, ch in enumerate(bits):
        if ch == "1":
            pixels[i * 2 + 1] |= 1
    raw = b""
    for r in range(height):
        row = bytes(pixels[r * width * 6:(r + 1) * width * 6])
        raw += b"\x00" + row
    return _make_png(_ihdr(width, height, bit_depth=16), zlib.compress(raw))


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

    def test_png_interlaced_lsb(self):
        msg = b"flag{adam7_lsb}"
        result = analyze_image_stego(_make_interlaced_lsb_png(msg))
        self.assertIsNotNone(result)
        self.assertIn(msg, result["lsb"])

    def test_png_palette_lsb(self):
        msg = b"flag{palette_lsb}"
        result = analyze_image_stego(_make_palette_lsb_png(msg))
        self.assertIsNotNone(result)
        self.assertIn(msg, result["lsb"])

    def test_png_itxt_chunk(self):
        result = analyze_image_stego(_make_png_with_itxt(b"flag{in_itxt_chunk}"))
        self.assertIn("flag{in_itxt_chunk}", result["chunk_texts"])

    def test_png_itxt_compressed(self):
        result = analyze_image_stego(_make_png_with_itxt(b"flag{itxt_zlib}", compressed=True))
        self.assertIn("flag{itxt_zlib}", result["chunk_texts"])

    def test_png_16bit_lsb(self):
        msg = b"flag{16bit_lsb}"
        result = analyze_image_stego(_make_lsb_png_16bit(msg))
        self.assertIn(msg, result["lsb"])

    def test_png_interlaced_palette_still_gap(self):
        # interlaced + palette + bit_depth<8 组合仍标不支持
        result = analyze_image_stego(_make_png(_ihdr(8, 8, bit_depth=1, color_type=3, interlace=1), b"x"))
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
        # WEBP：classify 识别为 image，但本模块无结构解析/隐写覆盖，应返回空
        with tempfile.NamedTemporaryFile(suffix=".webp", delete=False) as handle:
            handle.write(b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"\x00" * 20)
            path = Path(handle.name)
        try:
            lines = image_stego_lines(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
