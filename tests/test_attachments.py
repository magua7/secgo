"""多格式附件解析测试。"""

import os
import tempfile
import unittest
from pathlib import Path

from secgo.runtime.attachments import (
    classify_basic_file,
    extract_limited_text,
    _try_parse_structured_text,
    _decode_text,
    _looks_like_text,
)


class ClassifyTests(unittest.TestCase):
    def test_classify_pdf(self):
        result = classify_basic_file(b"%PDF-1.4\n...")
        self.assertEqual(result, "pdf")

    def test_classify_zip(self):
        # ZIP 文件头 PK\x03\x04
        result = classify_basic_file(b"PK\x03\x04...")
        self.assertEqual(result, "zip")

    def test_classify_text(self):
        result = classify_basic_file(b"Hello, this is plain text.")
        self.assertEqual(result, "text")

    def test_classify_json(self):
        result = classify_basic_file(b'{"key": "value"}')
        self.assertEqual(result, "text")

    def test_classify_png(self):
        result = classify_basic_file(b"\x89PNG\r\n\x1a\n")
        self.assertEqual(result, "image")


class StructuredParseTests(unittest.TestCase):
    def test_parse_json(self):
        result = _try_parse_structured_text('{"name": "test", "version": 1}')
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "json")
        self.assertTrue(result["parsed"])

    def test_parse_openapi_json(self):
        result = _try_parse_structured_text(
            '{"openapi": "3.0.0", "info": {"title": "API"}, '
            '"paths": {"/users": {"get": {"summary": "List users"}}}}'
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "openapi")
        self.assertTrue(len(result["endpoints"]) > 0)
        self.assertEqual(result["endpoints"][0]["path"], "/users")

    def test_parse_swagger_json(self):
        result = _try_parse_structured_text(
            '{"swagger": "2.0", "info": {"title": "Legacy API"}, '
            '"paths": {"/api/v1": {"get": {"summary": "V1"}}}}'
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["type"], "openapi")

    def test_parse_plain_text_returns_none(self):
        result = _try_parse_structured_text("Just a normal sentence.")
        self.assertIsNone(result)


class TextExtractionTests(unittest.TestCase):
    def test_extract_text_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write("Hello, world!")
            path = f.name
        try:
            result = extract_limited_text(Path(path), "text")
            self.assertIsNotNone(result)
            self.assertIn("Hello", result)
        finally:
            os.unlink(path)

    def test_decode_utf8(self):
        result = _decode_text(b"hello")
        self.assertEqual(result, "hello")

    def test_decode_gb18030(self):
        result = _decode_text("你好".encode("gb18030"))
        self.assertEqual(result, "你好")

    def test_looks_like_text(self):
        self.assertTrue(_looks_like_text(b"hello world"))
        # 纯二进制数据（含大量控制字符和 unicode 解码失败标志）应判为非文本
        binary = bytes(range(256))  # 0x00-0xFF 全部字节
        self.assertFalse(_looks_like_text(binary))


if __name__ == "__main__":
    unittest.main()