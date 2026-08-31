"""JPEG 结构解析测试：程序化构造 JPEG 字节流，覆盖 EXIF/COM/尾随/尺寸/format/集成。"""

import os
import struct
import tempfile
import unittest
from pathlib import Path

from secgo.runtime.jpeg_analysis import (
    JPEG_TEXT_LIMIT,
    analyze_jpeg_bytes,
    format_jpeg_summary,
)
from secgo.runtime.image_stego import image_stego_lines


# ── 构造辅助 ──────────────────────────────────────────────


def _make_segment(marker: int, payload: bytes) -> bytes:
    """构造一个带 2 字节大端长度的段：FF <marker> <len> <payload>。"""
    return bytes([0xFF, marker]) + struct.pack(">H", 2 + len(payload)) + payload


def _make_exif_tiff(description: bytes) -> bytes:
    """小端 TIFF，含一个 ImageDescription(0x010E, ASCII) 条目（长值走 offset）。"""
    desc = description + b"\x00"
    data_offset = 22  # header(8) + count(2) + entry(12)
    tiff = bytearray()
    tiff += b"II" + struct.pack("<H", 0x002A) + struct.pack("<I", 8)
    tiff += struct.pack("<H", 1)  # IFD0 条目数
    tiff += struct.pack("<HHII", 0x010E, 2, len(desc), data_offset)
    tiff += desc
    return bytes(tiff)


def _make_exif_tiff_inline_short() -> bytes:
    """小端 TIFF，含一个 Orientation(0x0112, SHORT=1) 内联条目。"""
    tiff = bytearray()
    tiff += b"II" + struct.pack("<H", 0x002A) + struct.pack("<I", 8)
    tiff += struct.pack("<H", 1)
    tiff += struct.pack("<HHII", 0x0112, 3, 1, 1)  # value 内联为 1
    return bytes(tiff)


def _make_app1(tiff: bytes) -> bytes:
    body = b"Exif\x00\x00" + tiff
    return b"\xff\xe1" + struct.pack(">H", 2 + len(body)) + body


def _make_jpeg(trailing: bytes = b"", description: bytes = b"flag{test_jpeg_exif}") -> bytes:
    data = bytearray(b"\xff\xd8")  # SOI
    data += _make_app1(_make_exif_tiff(description))
    data += _make_segment(0xFE, b"hidden comment")  # COM
    # SOF0：precision=8, height=2, width=3
    sof = struct.pack(">BHH", 8, 2, 3) + b"\x03\x01\x22\x00\x02\x11\x01\x03\x11\x01"
    data += _make_segment(0xC0, sof)
    data += _make_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")  # SOS
    data += b"\x00\xff\x00\x00"  # 熵数据
    data += b"\xff\xd9"  # EOI
    data += trailing
    return bytes(data)


class ParseTests(unittest.TestCase):
    def test_dimensions(self):
        result = analyze_jpeg_bytes(_make_jpeg())
        self.assertEqual(result["dimensions"], {"width": 3, "height": 2})

    def test_exif_description(self):
        result = analyze_jpeg_bytes(_make_jpeg())
        names = [e["name"] for e in result["exif"]]
        self.assertIn("ImageDescription", names)
        entry = result["exif"][0]
        self.assertEqual(entry["name"], "ImageDescription")
        self.assertEqual(entry["value"], "flag{test_jpeg_exif}")

    def test_exif_inline_short(self):
        data = bytearray(b"\xff\xd8")
        data += _make_app1(_make_exif_tiff_inline_short())
        data += _make_segment(0xDA, b"\x01\x01\x00\x00\x3f\x00")
        data += b"\xff\xd9"
        result = analyze_jpeg_bytes(bytes(data))
        self.assertIn({"name": "Orientation", "value": "1"}, result["exif"])

    def test_comments(self):
        result = analyze_jpeg_bytes(_make_jpeg())
        self.assertEqual(result["comments"], ["hidden comment"])

    def test_trailing_zip(self):
        result = analyze_jpeg_bytes(_make_jpeg(trailing=b"PK\x03\x04\x00\x00extra"))
        self.assertEqual(result["trailing"]["size"], 11)
        self.assertEqual(result["trailing"]["kind"], "zip")

    def test_no_trailing(self):
        result = analyze_jpeg_bytes(_make_jpeg())
        self.assertIsNone(result["trailing"])

    def test_findings_flag(self):
        result = analyze_jpeg_bytes(_make_jpeg())
        self.assertTrue(any("ImageDescription" in f and "flag{test_jpeg_exif}" in f for f in result["findings"]))

    def test_non_jpeg_raises(self):
        with self.assertRaises(ValueError):
            analyze_jpeg_bytes(b"\x89PNG\r\n\x1a\n")


class FormattingTests(unittest.TestCase):
    def test_format_basic(self):
        text = format_jpeg_summary(analyze_jpeg_bytes(_make_jpeg()))
        self.assertIn("[JPEG 图片]", text)
        self.assertIn("flag{test_jpeg_exif}", text)
        self.assertIn("hidden comment", text)

    def test_format_truncated(self):
        result = {
            "kind": "jpeg",
            "segments": [],
            "dimensions": None,
            "exif": [{"name": "ImageDescription", "value": "A" * 9000}],
            "comments": [],
            "trailing": None,
            "findings": [],
        }
        text = format_jpeg_summary(result)
        self.assertIn("[JPEG 摘要已截断]", text)
        self.assertLessEqual(len(text), JPEG_TEXT_LIMIT + 40)


class IntegrationTests(unittest.TestCase):
    def test_image_stego_lines_jpeg(self):
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(_make_jpeg())
            path = f.name
        try:
            lines = image_stego_lines(Path(path))
            self.assertTrue(lines)
            self.assertIn("[JPEG 图片]", lines[0])
        finally:
            os.unlink(path)

    def test_image_stego_lines_non_jpeg_unchanged(self):
        # 非 JPEG（PNG）仍走原有隐写链路，不触发 JPEG 分支
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 20)
            path = f.name
        try:
            lines = image_stego_lines(Path(path))
            self.assertTrue(lines)
            self.assertTrue(any("[图片隐写分析]" in line for line in lines))
            self.assertFalse(any("[JPEG 图片]" in line for line in lines))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
