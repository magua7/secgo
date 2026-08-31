"""JPEG 图片结构解析（纯 Python，无第三方依赖）。

目的：把用户上传的 JPEG 附件变成 Agent 可用的结构化上下文——段结构清单、图片尺寸、
EXIF 元数据（ImageDescription/Artist/UserComment 等常藏 flag 的字段）、COM 注释段、
EOI 之后的尾随数据（图种检测）。所有输出都带严格条数/字节上限；解析失败抛
ValueError，由上层转成失败提示，绝不挂死任务链。

定位是「看字节」：与 vision 模块「看画面」互补。DCT 系数 LSB 隐写（Jsteg/F5/OutGuess）
需要手写 Huffman + IDCT，明确不做，返回「不支持」提示。对标 runtime/binary_analysis.py
的模块结构与接口约定。
"""

from __future__ import annotations

import re
import struct
from typing import Any, Dict, List, Optional, Tuple

# ── 上限（防止大图拖垮上下文）──────────────────────────────
JPEG_MAX_SEGMENTS = 200        # 最多解析的段数
JPEG_MAX_EXIF_ENTRIES = 100    # EXIF 条目上限
JPEG_MAX_COMMENTS = 20         # COM 注释条数
JPEG_MAX_TRAILING = 512        # 尾随数据预览字节上限
JPEG_CELL_DISPLAY = 160        # 单个 EXIF 值展示截断长度
JPEG_MAX_FINDINGS = 20         # 敏感命中条数
JPEG_TEXT_LIMIT = 8 * 1024     # 注入上下文的文本上限

# ── 扫描正则 ──────────────────────────────────────────────
_FLAG_RE = re.compile(r"flag\{[^}\r\n]{1,80}\}", re.IGNORECASE)
_URL_RE = re.compile(r"https?://[^\s\x00\"'<>]{4,120}")

# ── JPEG 段 marker 命名 ───────────────────────────────────
_MARKER_NAMES = {
    0xC0: "SOF0(基线DCT)", 0xC1: "SOF1(扩展)", 0xC2: "SOF2(渐进)", 0xC3: "SOF3(无损)",
    0xC4: "DHT(Huffman表)", 0xCC: "DAC(算术表)",
    0xD8: "SOI", 0xD9: "EOI", 0xDA: "SOS(扫描开始)", 0xDD: "DRI(重启间隔)",
    0xDB: "DQT(量化表)", 0xDE: "DHP", 0xDF: "EXP",
    0xE0: "APP0(JFIF)", 0xE1: "APP1(EXIF)", 0xE2: "APP2(ICC)",
    0xEE: "APP14(Adobe)", 0xFE: "COM(注释)",
}

# 常见 EXIF tag 名（十进制 tag → 名称）
_EXIF_TAG_NAMES = {
    0x010E: "ImageDescription", 0x010F: "Make", 0x0110: "Model",
    0x0112: "Orientation", 0x011A: "XResolution", 0x011B: "YResolution",
    0x0128: "ResolutionUnit", 0x0131: "Software", 0x0132: "DateTime",
    0x013B: "Artist", 0x013E: "WhitePoint", 0x8298: "Copyright",
    0x8769: "ExifIFD", 0x8825: "GPSIFD", 0x9286: "UserComment",
    0x9C9B: "XPTitle", 0x9C9C: "XPComment", 0x9C9D: "XPAuthor",
    0x9C9E: "XPKeywords", 0x9C9F: "XPSubject",
}

# EXIF 类型字节宽
_EXIF_TYPE_SIZES = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


# ── 段遍历 ────────────────────────────────────────────────


def _find_eoi(data: bytes, start: int) -> int:
    """从 start 起找 EOI(FF D9) 的结束偏移；找不到返回文件尾。

    JPEG 熵编码数据里 FF 后只允许跟 00(转义) 或 RST 标记，裸的 FF D9 即真 EOI。
    """
    idx = data.find(b"\xff\xd9", start)
    return idx + 2 if idx != -1 else len(data)


def _scan_jpeg(data: bytes) -> Tuple[List[Dict[str, Any]], int]:
    """遍历 JPEG 段结构，返回 (segments, eoi_end)。SOS 后的熵数据直接跳到 EOI。"""
    if not data.startswith(b"\xff\xd8"):
        raise ValueError("不是有效的 JPEG 文件（缺 SOI）")
    n = len(data)
    pos = 2
    segments: List[Dict[str, Any]] = []
    eoi_end = n

    while pos + 1 < n:
        if len(segments) >= JPEG_MAX_SEGMENTS:
            break
        if data[pos] != 0xFF:
            pos += 1  # 段间杂散字节（含 SOS 熵数据），逐字节推进
            continue
        seg_start = pos
        while pos < n and data[pos] == 0xFF:
            pos += 1  # 跳过填充 FF
        if pos >= n:
            break
        marker = data[pos]
        pos += 1

        if marker == 0xD9:  # EOI
            eoi_end = pos
            break
        if marker == 0xD8 or marker == 0x01 or 0xD0 <= marker <= 0xD7:
            continue  # SOI / TEM / RSTn 无长度独立标记
        if marker == 0xDA:  # SOS：其后是熵编码数据，直接定位 EOI
            eoi_end = _find_eoi(data, pos)
            break
        if pos + 2 > n:
            break
        seg_len = int.from_bytes(data[pos:pos + 2], "big")
        if seg_len < 2 or pos + seg_len > n:
            break
        payload = data[pos + 2:pos + seg_len]
        segments.append({
            "marker": marker,
            "name": _MARKER_NAMES.get(marker, f"APP{marker - 0xE0}" if 0xE0 <= marker <= 0xEF else f"0x{marker:02X}"),
            "offset": seg_start,
            "size": seg_len,
            "payload": payload,
        })
        pos += seg_len

    return segments, eoi_end


# ── EXIF 解析 ─────────────────────────────────────────────


def _parse_exif(payload: bytes) -> List[Dict[str, str]]:
    """解析 APP1 段里的 EXIF(TIFF 结构)，返回 [{name, value}]，失败返回空列表。"""
    if not payload.startswith(b"Exif\x00\x00"):
        return []
    tiff = payload[6:]
    if len(tiff) < 8:
        return []
    if tiff[:2] == b"II":
        endian = "<"
    elif tiff[:2] == b"MM":
        endian = ">"
    else:
        return []
    if struct.unpack_from(endian + "H", tiff, 2)[0] != 0x002A:
        return []
    ifd0 = struct.unpack_from(endian + "I", tiff, 4)[0]
    return _parse_ifd(tiff, endian, ifd0)


def _parse_ifd(tiff: bytes, endian: str, offset: int) -> List[Dict[str, str]]:
    if offset + 2 > len(tiff):
        return []
    count = struct.unpack_from(endian + "H", tiff, offset)[0]
    entries: List[Dict[str, str]] = []
    for i in range(min(count, JPEG_MAX_EXIF_ENTRIES)):
        ent = offset + 2 + i * 12
        if ent + 12 > len(tiff):
            break
        tag, typ, cnt, val_field = struct.unpack_from(endian + "HHII", tiff, ent)
        value = _read_exif_value(tiff, endian, tag, typ, cnt, val_field)
        if value is None or value == "":
            continue
        name = _EXIF_TAG_NAMES.get(tag, f"0x{tag:04X}")
        entries.append({"name": name, "value": value})
    return entries


def _read_exif_value(tiff: bytes, endian: str, tag: int, typ: int, count: int, val_field: int) -> Optional[str]:
    size = _EXIF_TYPE_SIZES.get(typ, 1)
    total = size * count
    if total <= 4:
        raw = struct.pack(endian + "I", val_field)
        raw = raw[:total] if endian == "<" else raw[4 - total:]
    else:
        if val_field + total > len(tiff):
            return None
        raw = tiff[val_field:val_field + total]

    if typ == 2:  # ASCII
        return raw.split(b"\x00", 1)[0].decode("utf-8", "replace").strip()[:JPEG_CELL_DISPLAY]
    if typ in (1, 7):  # BYTE / UNDEFINED
        return raw[:16].hex()
    if typ == 3:  # SHORT
        vals = struct.unpack(endian + "H" * (len(raw) // 2), raw)
        return ", ".join(str(v) for v in vals[:8])
    if typ in (4, 9):  # LONG / SLONG
        vals = struct.unpack(endian + "I" * (len(raw) // 4), raw)
        return ", ".join(str(v) for v in vals[:8])
    if typ in (5, 10):  # RATIONAL / SRATIONAL
        pairs = []
        for j in range(0, len(raw) - 7, 8):
            num = struct.unpack_from(endian + "I", raw, j)[0]
            den = struct.unpack_from(endian + "I", raw, j + 4)[0]
            pairs.append(f"{num}/{den}" if den else str(num))
        return ", ".join(pairs[:8])
    return raw[:32].hex()


# ── 尾随数据 / 尺寸 / 注释 ─────────────────────────────────


def _detect_trailing_kind(data: bytes) -> str:
    """识别尾随数据疑似类型（图种），无法判断返回空串。"""
    if data.startswith(b"PK\x03\x04"):
        return "zip"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\x7fELF"):
        return "elf"
    if data.startswith(b"MZ"):
        return "pe"
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    return ""


def _extract_dimensions(segments: List[Dict[str, Any]]) -> Optional[Dict[str, int]]:
    for seg in segments:
        if seg["marker"] in (0xC0, 0xC1, 0xC2, 0xC3):
            payload = seg["payload"]
            if len(payload) >= 5:
                return {
                    "width": int.from_bytes(payload[3:5], "big"),
                    "height": int.from_bytes(payload[1:3], "big"),
                }
    return None


def _extract_comments(segments: List[Dict[str, Any]]) -> List[str]:
    comments: List[str] = []
    for seg in segments:
        if seg["marker"] == 0xFE:
            text = seg["payload"].decode("utf-8", "replace").strip()
            if text and len(comments) < JPEG_MAX_COMMENTS:
                comments.append(text[:JPEG_CELL_DISPLAY])
    return comments


# ── 汇总 ──────────────────────────────────────────────────


def analyze_jpeg_bytes(data: bytes) -> Dict[str, Any]:
    """解析 JPEG 字节流，返回带上限的结构化摘要。解析失败抛 ValueError。"""
    segments, eoi_end = _scan_jpeg(data)

    exif: List[Dict[str, str]] = []
    for seg in segments:
        if seg["marker"] == 0xE1:
            exif.extend(_parse_exif(seg["payload"]))

    comments = _extract_comments(segments)
    trailing = data[eoi_end:]
    dimensions = _extract_dimensions(segments)

    findings: List[str] = []
    finding_seen: set = set()

    def add_finding(text: str) -> None:
        if text not in finding_seen and len(findings) < JPEG_MAX_FINDINGS:
            finding_seen.add(text)
            findings.append(text)

    for entry in exif:
        for match in _FLAG_RE.finditer(entry["value"]):
            add_finding(f"EXIF {entry['name']} 命中 flag 形态: {match.group(0)}")
        for match in _URL_RE.finditer(entry["value"]):
            add_finding(f"EXIF {entry['name']} 命中 URL: {match.group(0)}")
    for comment in comments:
        for match in _FLAG_RE.finditer(comment):
            add_finding(f"COM 注释命中 flag 形态: {match.group(0)}")

    return {
        "kind": "jpeg",
        "segments": [{"name": s["name"], "offset": s["offset"], "size": s["size"]} for s in segments],
        "dimensions": dimensions,
        "exif": exif,
        "comments": comments,
        "trailing": {
            "size": len(trailing),
            "kind": _detect_trailing_kind(trailing),
            "preview": trailing[:JPEG_MAX_TRAILING],
        } if trailing else None,
        "findings": findings,
    }


# ── 文本格式化（注入 Agent 上下文）──────────────────────────


def _fmt_trailing_preview(data: bytes) -> str:
    if all(0x20 <= b <= 0x7E or b in (9, 10, 13) for b in data):
        return data.decode("ascii", "replace")
    return data.hex()


def format_jpeg_summary(result: Dict[str, Any]) -> str:
    dims = result.get("dimensions")
    dim_text = f"{dims['width']}x{dims['height']}" if dims else "未知"
    segments = result.get("segments") or []
    seg_text = " → ".join(s["name"] for s in segments) or "无"
    lines = [
        f"[JPEG 图片] 尺寸: {dim_text} | 段数: {len(segments)}",
        f"段结构: {seg_text}",
    ]

    exif = result.get("exif") or []
    if exif:
        lines.append(f"EXIF 元数据（前 {len(exif)} 项）:")
        for entry in exif:
            lines.append(f"  - {entry['name']}: {entry['value']}")

    comments = result.get("comments") or []
    if comments:
        lines.append("注释(COM):")
        for comment in comments:
            lines.append(f"  - {comment}")

    trailing = result.get("trailing")
    if trailing:
        kind_hint = f"（疑似 {trailing['kind']}）" if trailing["kind"] else ""
        lines.append(
            f"尾随数据(EOI 之后): {trailing['size']} 字节{kind_hint} -> {_fmt_trailing_preview(trailing['preview'])}"
        )

    findings = result.get("findings") or []
    if findings:
        lines.append("敏感命中:")
        for finding in findings:
            lines.append(f"  - {finding}")

    text = "\n".join(lines)
    if len(text) > JPEG_TEXT_LIMIT:
        text = text[:JPEG_TEXT_LIMIT] + "\n[JPEG 摘要已截断]"
    return text
