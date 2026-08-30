"""二进制附件轻量解析（纯 Python，无第三方依赖）。

目的：把用户上传的 ELF/PE 二进制附件变成 Agent 可用的结构化上下文——文件头信息
（类别/字节序/类型/机器/入口/节区名）、可打印字符串（ASCII + UTF-16LE）、以及
flag/URL/路径形态的敏感线索。所有输出都有严格的条数/字节上限；解析失败抛 ValueError，
由上层转成失败提示，绝不挂死任务链。

定位是「让 Agent 知道这个二进制是什么、里面有哪些线索字符串」，不做反汇编/模拟执行。
对标 runtime/pcap_analysis.py 的模块结构与接口约定。
"""

from __future__ import annotations

import re
import struct
from typing import Any, Dict, List, Optional

# ── 上限（防止大二进制拖垮上下文）──────────────────────────
BIN_MAX_STRINGS = 100        # 最多保留的可打印字符串条数
BIN_MIN_STR_LEN = 4          # 字符串最小长度（ASCII 与 UTF-16LE 共用）
BIN_MAX_FINDINGS = 20        # flag/URL/路径 命中条数上限
BIN_MAX_SECTIONS = 50        # 节区名上限
BIN_STR_DISPLAY = 200        # 单条字符串展示截断长度
BIN_TEXT_LIMIT = 8 * 1024    # 注入上下文的文本上限

# ── 扫描正则 ──────────────────────────────────────────────
_ASCII_STR_RE = re.compile(rb"[\x20-\x7e]{%d,}" % BIN_MIN_STR_LEN)
_UTF16LE_STR_RE = re.compile(rb"(?:[\x20-\x7e]\x00){%d,}" % BIN_MIN_STR_LEN)
_FLAG_RE = re.compile(rb"flag\{[^}\r\n]{1,80}\}", re.IGNORECASE)
_URL_RE = re.compile(rb"https?://[^\s\x00\"'<>]{4,120}")
# Unix 路径：以 / 开头，负向后行排除前面是 ":" 或 "/" 的位置，
# 避免把 URL 里的 "://host/path" 的 path 部分重复当成路径命中
_UNIX_PATH_RE = re.compile(rb"(?<![A-Za-z0-9:/])/[A-Za-z0-9_./\-]{3,}")
_WIN_PATH_RE = re.compile(rb"[A-Za-z]:\\[A-Za-z0-9_ .\\\-]{2,}")

_ELF_MACHINES = {
    0x00: "No machine", 0x02: "SPARC", 0x03: "x86", 0x08: "MIPS",
    0x14: "PowerPC", 0x28: "ARM", 0x32: "IA-64", 0x3E: "x86-64",
    0xB7: "AArch64", 0xF3: "RISC-V",
}
_ELF_TYPES = {
    0: "NONE", 1: "REL(可重定位)", 2: "EXEC(可执行)", 3: "DYN(共享对象/PIE)", 4: "CORE",
}
_PE_MACHINES = {
    0x014C: "x86 (I386)", 0x8664: "x64 (AMD64)", 0x01C0: "ARM",
    0xAA64: "ARM64", 0x01F0: "PowerPC", 0x0200: "IA-64",
}


# ── 字符串提取 ────────────────────────────────────────────


def _extract_strings(data: bytes) -> List[str]:
    """提取可打印字符串（ASCII + UTF-16LE），去重后按首次出现顺序返回，带条数/长度上限。

    ASCII 与 UTF-16LE 两条正则天然互补：ASCII 正则 `[\\x20-\\x7e]{4,}` 不会匹配到含
    `\\x00` 的 UTF-16 序列，UTF-16LE 正则要求每个可打印 ASCII 后紧跟一个 `\\x00`，
    避免把二进制里零散的 `\\x00` 误当成宽字符字符串。
    """
    strings: List[str] = []
    seen: set = set()

    def _append(text: str) -> None:
        text = text.strip()
        if len(text) < BIN_MIN_STR_LEN:
            return
        key = text[:BIN_STR_DISPLAY]
        if key in seen:
            return
        seen.add(key)
        if len(strings) < BIN_MAX_STRINGS:
            strings.append(key)

    for match in _ASCII_STR_RE.finditer(data):
        _append(match.group(0).decode("ascii", "replace"))
    for match in _UTF16LE_STR_RE.finditer(data):
        _append(match.group(0).decode("utf-16-le", "replace"))
    return strings


# ── 敏感线索扫描 ──────────────────────────────────────────


def _scan_findings(data: bytes) -> List[str]:
    """扫描 flag / URL / 路径形态，去重 + 上限后返回带前缀的命中列表。"""
    findings: List[str] = []
    seen: set = set()

    def _add(prefix: str, raw: bytes) -> None:
        if len(findings) >= BIN_MAX_FINDINGS:
            return
        item = f"{prefix}{raw.decode('ascii', 'replace').strip()}"
        if item in seen:
            return
        seen.add(item)
        findings.append(item)

    for match in _FLAG_RE.finditer(data):
        _add("flag 形态: ", match.group(0))
    for match in _URL_RE.finditer(data):
        _add("URL: ", match.group(0))
    for match in _UNIX_PATH_RE.finditer(data):
        _add("路径形态: ", match.group(0))
    for match in _WIN_PATH_RE.finditer(data):
        _add("路径形态: ", match.group(0))
    return findings


# ── ELF 头解析 ────────────────────────────────────────────


def _elf_section_names(
    data: bytes, endian: str, is_64: bool,
    shoff: int, shentsize: int, shnum: int, shstrndx: int,
) -> List[str]:
    """从 section header table 读出节区名（经 shstrtab 字符串表），失败返回空列表。"""
    if shnum == 0 or shstrndx == 0 or shstrndx >= shnum:
        return []
    min_ent = 64 if is_64 else 40
    if shentsize < min_ent or shoff <= 0:
        return []
    if shoff + shentsize * shnum > len(data):
        return []

    # 先定位 shstrtab 节（第 shstrndx 项），拿它的 sh_offset / sh_size
    shstr_entry = shoff + shstrndx * shentsize
    if shstr_entry + shentsize > len(data):
        return []
    if is_64:
        shstr_off = struct.unpack_from(endian + "Q", data, shstr_entry + 24)[0]
        shstr_size = struct.unpack_from(endian + "Q", data, shstr_entry + 32)[0]
    else:
        shstr_off = struct.unpack_from(endian + "I", data, shstr_entry + 16)[0]
        shstr_size = struct.unpack_from(endian + "I", data, shstr_entry + 20)[0]
    if shstr_off <= 0 or shstr_off + shstr_size > len(data):
        return []
    shstrtab = data[shstr_off:shstr_off + shstr_size]

    names: List[str] = []
    for i in range(shnum):
        entry = shoff + i * shentsize
        sh_name = struct.unpack_from(endian + "I", data, entry)[0]  # 每项前 4 字节恒为 sh_name
        if sh_name >= len(shstrtab):
            continue
        end = shstrtab.find(b"\x00", sh_name)
        if end == -1:
            end = len(shstrtab)
        name = shstrtab[sh_name:end].decode("ascii", "replace")
        if name:
            names.append(name)
        if len(names) >= BIN_MAX_SECTIONS:
            break
    return names


def _parse_elf_header(data: bytes) -> Optional[Dict[str, Any]]:
    """解析 ELF 头（class/endian/type/machine/entry/节区名），失败返回 None。"""
    if len(data) < 52 or data[:4] != b"\x7fELF":
        return None
    ei_class = data[4]   # 1=32 位, 2=64 位
    ei_data = data[5]    # 1=小端, 2=大端
    if ei_class not in (1, 2) or ei_data not in (1, 2):
        return None
    endian = "<" if ei_data == 1 else ">"
    is_64 = ei_class == 2

    if is_64:
        if len(data) < 64:
            return None
        e_type = struct.unpack_from(endian + "H", data, 16)[0]
        e_machine = struct.unpack_from(endian + "H", data, 18)[0]
        e_entry = struct.unpack_from(endian + "Q", data, 24)[0]
        e_shoff = struct.unpack_from(endian + "Q", data, 40)[0]
        e_shentsize = struct.unpack_from(endian + "H", data, 58)[0]
        e_shnum = struct.unpack_from(endian + "H", data, 60)[0]
        e_shstrndx = struct.unpack_from(endian + "H", data, 62)[0]
    else:
        e_type = struct.unpack_from(endian + "H", data, 16)[0]
        e_machine = struct.unpack_from(endian + "H", data, 18)[0]
        e_entry = struct.unpack_from(endian + "I", data, 24)[0]
        e_shoff = struct.unpack_from(endian + "I", data, 32)[0]
        e_shentsize = struct.unpack_from(endian + "H", data, 46)[0]
        e_shnum = struct.unpack_from(endian + "H", data, 48)[0]
        e_shstrndx = struct.unpack_from(endian + "H", data, 50)[0]

    sections = _elf_section_names(data, endian, is_64, e_shoff, e_shentsize, e_shnum, e_shstrndx)

    return {
        "class": "ELF64" if is_64 else "ELF32",
        "endian": "小端" if ei_data == 1 else "大端",
        "type": _ELF_TYPES.get(e_type, f"type {e_type}"),
        "machine": _ELF_MACHINES.get(e_machine, f"0x{e_machine:x}"),
        "entry": e_entry,
        "sections": sections,
    }


# ── PE 头解析 ─────────────────────────────────────────────


def _parse_pe_header(data: bytes) -> Optional[Dict[str, Any]]:
    """解析 PE 头（machine/entry/节区名），失败返回 None。"""
    if len(data) < 0x40 or data[:2] != b"MZ":
        return None
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if e_lfanew < 0x40 or e_lfanew + 24 > len(data):
        return None
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return None

    coff = e_lfanew + 4
    machine = struct.unpack_from("<H", data, coff)[0]
    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    if opt_size < 2 or opt + opt_size > len(data):
        return None

    magic = struct.unpack_from("<H", data, opt)[0]
    # AddressOfEntryPoint 在 Optional header 偏移 16 处，PE32(0x10b)/PE32+(0x20b) 同偏移
    entry = struct.unpack_from("<I", data, opt + 16)[0] if magic in (0x10B, 0x20B) and opt_size >= 20 else 0

    sections: List[str] = []
    section_table = opt + opt_size
    for i in range(min(num_sections, BIN_MAX_SECTIONS)):
        ent = section_table + i * 40
        if ent + 40 > len(data):
            break
        name = data[ent:ent + 8].split(b"\x00", 1)[0].decode("ascii", "replace")
        if name:
            sections.append(name)

    return {
        "machine": _PE_MACHINES.get(machine, f"0x{machine:x}"),
        "entry": entry,
        "sections": sections,
    }


# ── 汇总 ──────────────────────────────────────────────────


def analyze_binary_bytes(data: bytes, kind: str) -> Dict[str, Any]:
    """解析二进制字节流，返回带上限的结构化摘要。kind 与魔数不符时抛 ValueError。"""
    if kind == "elf":
        if data[:4] != b"\x7fELF":
            raise ValueError("不是有效的 ELF 文件")
        header = _parse_elf_header(data)
    elif kind == "pe":
        if data[:2] != b"MZ":
            raise ValueError("不是有效的 PE 文件")
        header = _parse_pe_header(data)
    else:
        raise ValueError(f"不支持的二进制类型: {kind}")

    return {
        "kind": kind,
        "header": header,
        "strings": _extract_strings(data),
        "findings": _scan_findings(data),
    }


# ── 文本格式化（注入 Agent 上下文）──────────────────────────


def format_binary_summary(result: Dict[str, Any]) -> str:
    kind = result.get("kind", "")
    header = result.get("header") or {}
    lines: List[str] = []

    if kind == "elf" and header:
        lines.append(
            f"[二进制分析] 格式: {header['class']} {header['endian']} | "
            f"类型: {header['type']} | 机器: {header['machine']} | 入口: 0x{header['entry']:x}"
        )
    elif kind == "pe" and header:
        lines.append(
            f"[二进制分析] 格式: PE | 机器: {header['machine']} | 入口 RVA: 0x{header['entry']:x}"
        )
    else:
        lines.append(f"[二进制分析] 格式: {kind.upper()}（头解析失败或缺失）")

    sections = header.get("sections") or []
    if sections:
        lines.append(f"节区（前 {len(sections)} 个）: {', '.join(sections)}")

    strings = result.get("strings") or []
    if strings:
        lines.append(f"可打印字符串（前 {len(strings)} 条）:")
        for s in strings:
            lines.append(f"  - {s}")

    findings = result.get("findings") or []
    if findings:
        lines.append("敏感命中:")
        for finding in findings:
            lines.append(f"  - {finding}")

    text = "\n".join(lines)
    if len(text) > BIN_TEXT_LIMIT:
        text = text[:BIN_TEXT_LIMIT] + "\n[二进制摘要已截断]"
    return text
