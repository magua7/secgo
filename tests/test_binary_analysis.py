"""二进制附件解析测试：全部用程序化构造的 ELF/PE 字节流，不依赖真实样本。"""

from __future__ import annotations

import struct
import tempfile
import unittest
from pathlib import Path

from secgo.runtime.attachments import extract_limited_text
from secgo.runtime.binary_analysis import (
    BIN_TEXT_LIMIT,
    analyze_binary_bytes,
    format_binary_summary,
)


# ── 字节流构造辅助 ─────────────────────────────────────────


def _make_elf32(body: bytes = b"") -> bytes:
    """构造结构合法的 ELF32（小端 x86，含 .text/.shstrtab 两个节）。"""
    shstrtab = b"\x00.text\x00.shstrtab\x00"
    shnum = 3
    shstrndx = 2
    shoff = 52 + len(body) + len(shstrtab)
    header = (
        b"\x7fELF" + bytes([1, 1, 1]) + b"\x00" * 9
        + struct.pack(
            "<HHIIIIIHHHHHH",
            2,        # e_type = EXEC
            3,        # e_machine = x86
            1,        # e_version
            0x1000,   # e_entry
            0,        # e_phoff
            shoff,    # e_shoff
            0,        # e_flags
            52,       # e_ehsize
            0,        # e_phentsize
            0,        # e_phnum
            40,       # e_shentsize
            shnum,    # e_shnum
            shstrndx, # e_shstrndx
        )
    )
    null_ent = b"\x00" * 40
    text_ent = struct.pack("<IIIIIIIIII", 1, 1, 0, 0, 52, len(body), 0, 0, 0, 0)
    shstr_ent = struct.pack("<IIIIIIIIII", 7, 3, 0, 0, 52 + len(body), len(shstrtab), 0, 0, 1, 0)
    return header + body + shstrtab + null_ent + text_ent + shstr_ent


def _make_elf64(body: bytes = b"") -> bytes:
    """构造结构合法的 ELF64（小端 x86-64）。"""
    shstrtab = b"\x00.text\x00.shstrtab\x00"
    shnum = 3
    shstrndx = 2
    shoff = 64 + len(body) + len(shstrtab)
    header = (
        b"\x7fELF" + bytes([2, 1, 1]) + b"\x00" * 9
        + struct.pack(
            "<HHIQQQIHHHHHH",
            2,         # e_type = EXEC
            0x3E,      # e_machine = x86-64
            1,         # e_version
            0x400000,  # e_entry
            0,         # e_phoff
            shoff,     # e_shoff
            0,         # e_flags
            64,        # e_ehsize
            0,         # e_phentsize
            0,         # e_phnum
            64,        # e_shentsize
            shnum,     # e_shnum
            shstrndx,  # e_shstrndx
        )
    )
    null_ent = b"\x00" * 64
    text_ent = struct.pack("<IIQQQQIIQQ", 1, 1, 0, 0, 64, len(body), 0, 0, 0, 0)
    shstr_ent = struct.pack("<IIQQQQIIQQ", 7, 3, 0, 0, 64 + len(body), len(shstrtab), 0, 0, 1, 0)
    return header + body + shstrtab + null_ent + text_ent + shstr_ent


def _make_pe(body: bytes = b"", machine: int = 0x8664) -> bytes:
    """构造结构合法的 PE（PE32+，默认 x64，含 .text 节）。"""
    e_lfanew = 0x40
    opt_size = 224
    num_sections = 1
    dos = bytearray(0x40)
    dos[0:2] = b"MZ"
    dos[0x3C:0x40] = struct.pack("<I", e_lfanew)
    coff = struct.pack("<HHIIIHH", machine, num_sections, 0, 0, 0, opt_size, 0x0102)
    opt = bytearray(opt_size)
    opt[0:2] = struct.pack("<H", 0x20B)      # PE32+
    opt[16:20] = struct.pack("<I", 0x1000)    # AddressOfEntryPoint
    section = b".text\x00\x00\x00" + b"\x00" * 32
    return bytes(dos) + b"PE\x00\x00" + coff + bytes(opt) + section + body


_SAMPLE_BODY = (
    b"hello world\n"
    b"flag{demo_binary_flag}\n"
    b"https://example.com/secret\n"
    b"/etc/passwd\n"
    b"C:\\Windows\\System32\n"
    + b"\x00" * 8
)


# ── 解析用例 ───────────────────────────────────────────────


class BinaryParseTests(unittest.TestCase):
    def test_elf32_header(self):
        result = analyze_binary_bytes(_make_elf32(_SAMPLE_BODY), "elf")
        header = result["header"]
        self.assertEqual(header["class"], "ELF32")
        self.assertEqual(header["endian"], "小端")
        self.assertEqual(header["machine"], "x86")
        self.assertEqual(header["entry"], 0x1000)
        self.assertIn(".text", header["sections"])
        self.assertIn(".shstrtab", header["sections"])

    def test_elf64_header(self):
        result = analyze_binary_bytes(_make_elf64(_SAMPLE_BODY), "elf")
        header = result["header"]
        self.assertEqual(header["class"], "ELF64")
        self.assertEqual(header["machine"], "x86-64")
        self.assertEqual(header["entry"], 0x400000)
        self.assertIn(".text", header["sections"])

    def test_pe_header(self):
        result = analyze_binary_bytes(_make_pe(_SAMPLE_BODY), "pe")
        header = result["header"]
        self.assertEqual(header["machine"], "x64 (AMD64)")
        self.assertEqual(header["entry"], 0x1000)
        self.assertIn(".text", header["sections"])

    def test_ascii_and_utf16_strings_extracted(self):
        # 两个 \x00 分隔：避免 ASCII 串末尾字符与后续 \x00 误组 UTF-16 对
        body = b"hello_world\x00\x00" + "wide_string".encode("utf-16-le")
        result = analyze_binary_bytes(_make_elf64(body), "elf")
        strings = result["strings"]
        self.assertIn("hello_world", strings)
        self.assertIn("wide_string", strings)

    def test_flag_url_path_findings(self):
        result = analyze_binary_bytes(_make_elf64(_SAMPLE_BODY), "elf")
        findings = result["findings"]
        self.assertTrue(any("flag{demo_binary_flag}" in f for f in findings))
        self.assertTrue(any("https://example.com/secret" in f for f in findings))
        self.assertTrue(any("/etc/passwd" in f for f in findings))
        self.assertTrue(any("C:\\Windows\\System32" in f for f in findings))

    def test_kind_mismatch_raises(self):
        with self.assertRaises(ValueError):
            analyze_binary_bytes(b"\x7fELFnot an elf", "pe")
        with self.assertRaises(ValueError):
            analyze_binary_bytes(b"MZ not a pe", "elf")
        with self.assertRaises(ValueError):
            analyze_binary_bytes(b"whatever", "macho")


class BinaryFormattingTests(unittest.TestCase):
    def test_format_contains_key_sections(self):
        text = format_binary_summary(analyze_binary_bytes(_make_elf64(_SAMPLE_BODY), "elf"))
        self.assertIn("[二进制分析]", text)
        self.assertIn("ELF64", text)
        self.assertIn("节区", text)
        self.assertIn("flag{demo_binary_flag}", text)
        self.assertIn("敏感命中", text)

    def test_format_pe_contains_rva(self):
        text = format_binary_summary(analyze_binary_bytes(_make_pe(_SAMPLE_BODY), "pe"))
        self.assertIn("[二进制分析]", text)
        self.assertIn("PE", text)
        self.assertIn("入口 RVA", text)

    def test_format_truncated_when_huge(self):
        body = b"\n".join(f"s{i}_".encode() + b"A" * 150 for i in range(200))
        text = format_binary_summary(analyze_binary_bytes(_make_elf32(body), "elf"))
        self.assertLessEqual(len(text), BIN_TEXT_LIMIT + 100)


class BinaryIntegrationTests(unittest.TestCase):
    def _write(self, data: bytes, suffix: str) -> Path:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as handle:
            handle.write(data)
            return Path(handle.name)

    def test_extract_limited_text_elf_branch(self):
        path = self._write(_make_elf64(_SAMPLE_BODY), ".elf")
        try:
            text = extract_limited_text(path, "elf")
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNotNone(text)
        self.assertIn("[二进制分析]", text)
        self.assertIn("flag{demo_binary_flag}", text)

    def test_extract_limited_text_pe_branch(self):
        path = self._write(_make_pe(_SAMPLE_BODY), ".exe")
        try:
            text = extract_limited_text(path, "pe")
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNotNone(text)
        self.assertIn("[二进制分析]", text)

    def test_extract_limited_text_invalid_returns_failure_message(self):
        path = self._write(b"garbage garbage garbage", ".bin")
        try:
            text = extract_limited_text(path, "elf")
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNotNone(text)
        self.assertIn("[二进制解析失败]", text)


if __name__ == "__main__":
    unittest.main()
