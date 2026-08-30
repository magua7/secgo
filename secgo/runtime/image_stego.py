"""图片隐写字节级分析（纯 Python，无第三方依赖）。

定位：vision 模块「看画面」，本模块「看字节」——两者互补。视觉模型只能理解
像素内容，看不到藏在 LSB、PNG 附加 chunk、IEND 尾随数据里的信息；这类字节级
隐藏必须由本模块就地解析，再以文本注入 Agent 上下文。

覆盖范围（CTF 最高频的两种无损载体）：
- PNG：IEND 之后尾随数据检测、tEXt/zTXt 文本 chunk 提取、LSB 最低位提取
  （zlib 解 IDAT + 还原 filter；仅 non-interlaced、位深 8/16、非 palette）。
- BMP：未压缩 24/32 位图的 LSB 提取（跳过行 padding）。

不支持 interlaced(Adam7)、palette 索引图、压缩 BMP、JPEG/GIF/WEBP——返回明确的
「不支持」提示而非静默失败。所有输出带条数/字节上限，解析失败不抛异常（返回
None），由接入层兜底，绝不中断任务链。
"""

from __future__ import annotations

import re
import struct
import zlib
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

# ── 上限（防止大图拖垮上下文）──────────────────────────────
STEGO_LSB_SCAN = 4 * 1024      # LSB 字节流扫 flag/字符串的字节上限
STEGO_MAX_STRINGS = 40         # LSB 里保留的可打印字符串条数
STEGO_MIN_STR_LEN = 4          # 字符串最小长度
STEGO_TRAILING_MAX = 512       # 尾随数据展示上限
STEGO_TEXT_LIMIT = 4 * 1024    # 注入上下文文本上限
STEGO_MAX_PIXEL_BYTES = 64 * 1024 * 1024  # 解压/读取的像素字节上限（防解压炸弹）

_FLAG_RE = re.compile(rb"flag\{[^}\r\n]{1,80}\}", re.IGNORECASE)
_ASCII_STR_RE = re.compile(rb"[\x20-\x7e]{%d,}" % STEGO_MIN_STR_LEN)

_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_COLOR_CHANNELS = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}  # 灰度/RGB/palette/灰alpha/RGBA


# ── PNG 结构解析 ──────────────────────────────────────────


def _iter_png_chunks(data: bytes) -> Iterator[Tuple[bytes, bytes]]:
    """遍历 PNG chunk，yield (type, chunk_data)。签名校验失败抛 ValueError。"""
    if not data.startswith(_PNG_SIG):
        raise ValueError("不是有效的 PNG 文件")
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        ctype = data[offset + 4:offset + 8]
        data_end = offset + 8 + length
        chunk_end = offset + 12 + length
        if chunk_end > len(data):
            break  # 尾 chunk 截断，容忍
        yield ctype, data[offset + 8:data_end]
        offset = chunk_end
        if ctype == b"IEND":
            break


def _png_iend_end(data: bytes) -> Optional[int]:
    """返回 IEND chunk 结束后的字节偏移（即尾随数据起点）；无 IEND 返回 None。"""
    if not data.startswith(_PNG_SIG):
        return None
    offset = 8
    while offset + 12 <= len(data):
        length = struct.unpack(">I", data[offset:offset + 4])[0]
        ctype = data[offset + 4:offset + 8]
        end = offset + 12 + length
        if end > len(data):
            return None
        if ctype == b"IEND":
            return end
        offset = end
    return None


def _parse_png_ihdr(data: bytes) -> Optional[Dict[str, int]]:
    for ctype, cdata in _iter_png_chunks(data):
        if ctype == b"IHDR":
            if len(cdata) < 13:
                return None
            width, height = struct.unpack(">II", cdata[:8])
            bit_depth = cdata[8]
            color_type = cdata[9]
            interlace = cdata[12]
            return {
                "width": width, "height": height,
                "bit_depth": bit_depth, "color_type": color_type,
                "interlace": interlace,
            }
    return None


# ── PNG filter 还原 ───────────────────────────────────────


def _paeth(a: int, b: int, c: int) -> int:
    """PNG 规范的 Paeth 预测器。"""
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    if pb <= pc:
        return b
    return c


def _unfilter(scanline: bytes, prev: bytes, bpp: int) -> bytes:
    """还原单行滤波：scanline[0] 是 filter type，其余是滤波后字节。"""
    ftype = scanline[0]
    raw = bytearray(scanline[1:])
    for i in range(len(raw)):
        left = raw[i - bpp] if i >= bpp else 0
        up = prev[i] if prev else 0
        up_left = prev[i - bpp] if prev and i >= bpp else 0
        if ftype == 1:       # Sub
            raw[i] = (raw[i] + left) & 0xFF
        elif ftype == 2:     # Up
            raw[i] = (raw[i] + up) & 0xFF
        elif ftype == 3:     # Average
            raw[i] = (raw[i] + (left + up) // 2) & 0xFF
        elif ftype == 4:     # Paeth
            raw[i] = (raw[i] + _paeth(left, up, up_left)) & 0xFF
        # ftype == 0: None，原样
    return bytes(raw)


# ── LSB 提取 ──────────────────────────────────────────────


def _extract_lsb(pixel_bytes: bytes) -> bytes:
    """把每个字节的最低位按序拼成字节流（8 bit 一组）。"""
    out = bytearray()
    cur = 0
    nbits = 0
    for b in pixel_bytes:
        cur = (cur << 1) | (b & 1)
        nbits += 1
        if nbits == 8:
            out.append(cur)
            cur = 0
            nbits = 0
    return bytes(out)


def _lsb_scan(lsb: bytes) -> Dict[str, Any]:
    """扫 LSB 字节流里的 flag 与可打印字符串。"""
    scan = lsb[:STEGO_LSB_SCAN]
    flags: List[str] = []
    for m in _FLAG_RE.finditer(scan):
        flags.append(m.group(0).decode("ascii", "replace"))
    strings: List[str] = []
    for m in _ASCII_STR_RE.finditer(scan):
        s = m.group(0).decode("ascii", "replace")
        if s not in strings and len(strings) < STEGO_MAX_STRINGS:
            strings.append(s)
    return {"flags": flags, "strings": strings}


# ── PNG 分析 ──────────────────────────────────────────────


def _png_lsb(data: bytes, ihdr: Dict[str, int]) -> Tuple[Optional[bytes], Optional[str]]:
    """解 IDAT + 还原 filter + 取 LSB。返回 (lsb 字节, 不支持原因或 None)。"""
    color_type = ihdr["color_type"]
    if color_type == 3:
        return None, "palette 索引图不支持 LSB 提取"
    if ihdr["interlace"] != 0:
        return None, "interlaced(Adam7) 不支持 LSB 提取"
    bit_depth = ihdr["bit_depth"]
    if bit_depth not in (8, 16):
        return None, f"位深 {bit_depth} 不支持 LSB 提取"

    channels = _PNG_COLOR_CHANNELS.get(color_type)
    if channels is None:
        return None, f"color_type {color_type} 不支持"
    bpp = channels * (bit_depth // 8)
    row_bytes = ihdr["width"] * bpp
    stride = 1 + row_bytes
    expected = ihdr["height"] * stride

    # 防解压炸弹：按 IHDR 声明尺寸在解压前拦截超大图
    if expected <= 0:
        return None, "无效的图片尺寸"
    if expected > STEGO_MAX_PIXEL_BYTES:
        return None, f"图片尺寸过大（{expected} 字节），跳过 LSB 提取"

    # 拼接所有 IDAT 并解压（max_length 兜底，防畸形流解压出超声明尺寸的数据）
    idat_parts: List[bytes] = []
    for ctype, cdata in _iter_png_chunks(data):
        if ctype == b"IDAT":
            idat_parts.append(cdata)
    if not idat_parts:
        return None, "无 IDAT 数据"
    try:
        d = zlib.decompressobj()
        raw = d.decompress(b"".join(idat_parts), STEGO_MAX_PIXEL_BYTES + 1)
        if len(raw) > STEGO_MAX_PIXEL_BYTES:
            return None, "解压数据过大，跳过 LSB 提取"
    except zlib.error:
        return None, "IDAT 解压失败"

    if len(raw) < expected:
        return None, "解压数据不完整"

    # 逐行还原 filter，得到原始像素字节
    pixels = bytearray()
    prev = b""
    for r in range(ihdr["height"]):
        line = raw[r * stride:(r + 1) * stride]
        if len(line) < 1 + row_bytes:
            return None, "扫描线不完整"
        row = _unfilter(line, prev, bpp)
        pixels.extend(row)
        prev = row

    # LSB 扫描只用到前 STEGO_LSB_SCAN 字节，像素只需前 8 倍即可，避免全量位运算
    return _extract_lsb(bytes(pixels[: STEGO_LSB_SCAN * 8])), None


def _png_chunk_texts(data: bytes) -> List[str]:
    """提取 tEXt / zTXt 文本 chunk 内容（keyword\\0text，zTXt 解压）。"""
    texts: List[str] = []
    for ctype, cdata in _iter_png_chunks(data):
        if ctype == b"tEXt":
            if b"\x00" in cdata:
                text = cdata.split(b"\x00", 1)[1]
                texts.append(text.decode("latin-1", "replace")[:STEGO_TRAILING_MAX])
        elif ctype == b"zTXt":
            parts = cdata.split(b"\x00", 2)
            if len(parts) >= 3 and parts[1] == b"\x00":
                try:
                    text = zlib.decompress(parts[2])
                    texts.append(text.decode("latin-1", "replace")[:STEGO_TRAILING_MAX])
                except zlib.error:
                    continue
    return texts


def _analyze_png(data: bytes) -> Dict[str, Any]:
    result: Dict[str, Any] = {"kind": "png", "trailing": b"", "chunk_texts": [], "lsb": None, "lsb_note": None}

    iend_end = _png_iend_end(data)
    if iend_end is not None and iend_end < len(data):
        result["trailing"] = data[iend_end:]

    result["chunk_texts"] = _png_chunk_texts(data)

    ihdr = _parse_png_ihdr(data)
    if ihdr is None:
        result["lsb_note"] = "无 IHDR 头"
    else:
        lsb, note = _png_lsb(data, ihdr)
        result["lsb"] = lsb
        result["lsb_note"] = note
    return result


# ── BMP 分析 ──────────────────────────────────────────────


def _analyze_bmp(data: bytes) -> Dict[str, Any]:
    result: Dict[str, Any] = {"kind": "bmp", "lsb": None, "lsb_note": None}
    if len(data) < 54 or data[:2] != b"BM":
        result["lsb_note"] = "BMP 头不完整"
        return result
    dib_size = struct.unpack("<I", data[14:18])[0]
    if dib_size < 40:
        result["lsb_note"] = "不支持的 DIB 头"
        return result
    width = struct.unpack("<i", data[18:22])[0]
    height = struct.unpack("<i", data[22:26])[0]
    bpp = struct.unpack("<H", data[28:30])[0]
    compression = struct.unpack("<I", data[30:34])[0]
    bf_off_bits = struct.unpack("<I", data[10:14])[0]

    if compression != 0:
        result["lsb_note"] = f"压缩 BMP(compression={compression}) 不支持"
        return result
    if bpp not in (24, 32):
        result["lsb_note"] = f"位深 {bpp} 不支持"
        return result

    row_size = width * (bpp // 8)
    stride = (row_size + 3) & ~3  # 每行 4 字节对齐
    rows = abs(height)
    max_pixel_bytes = STEGO_LSB_SCAN * 8
    pixels = bytearray()
    for r in range(rows):
        start = bf_off_bits + r * stride
        end = start + row_size
        if end > len(data):
            break
        pixels.extend(data[start:end])
        if len(pixels) >= max_pixel_bytes:
            break  # LSB 扫描只用到前 STEGO_LSB_SCAN 字节，提前停止

    result["lsb"] = _extract_lsb(bytes(pixels[:max_pixel_bytes]))
    return result


# ── 汇总 ──────────────────────────────────────────────────


def analyze_image_stego(data: bytes) -> Optional[Dict[str, Any]]:
    """按魔数分派到 PNG/BMP 隐写分析；JPEG/GIF/WEBP 等不支持返回 None。"""
    if data.startswith(_PNG_SIG):
        return _analyze_png(data)
    if data.startswith(b"BM"):
        return _analyze_bmp(data)
    return None


# ── 文本格式化（注入 Agent 上下文）──────────────────────────


def _fmt_bytes_preview(raw: bytes) -> str:
    """尾随数据展示：优先当文本，否则给十六进制预览。"""
    sample = raw[:STEGO_TRAILING_MAX]
    if all(0x20 <= b <= 0x7E or b in (9, 10, 13) for b in sample):
        return sample.decode("ascii", "replace")
    return sample.hex()


def format_stego_summary(result: Dict[str, Any]) -> str:
    lines = [f"[图片隐写分析] 格式: {result['kind'].upper()}"]
    kind = result["kind"]

    if kind == "png":
        trailing = result.get("trailing") or b""
        if trailing:
            lines.append(f"- IEND 尾随数据: {len(trailing)} 字节 -> {_fmt_bytes_preview(trailing)}")
        for text in result.get("chunk_texts") or []:
            lines.append(f"- 文本 chunk: {text}")

    lsb = result.get("lsb")
    note = result.get("lsb_note")
    if note:
        lines.append(f"- LSB 提取: 不支持（{note}）")
    elif lsb:
        scan = _lsb_scan(lsb)
        flags = scan["flags"]
        strings = scan["strings"]
        if flags:
            lines.append(f"- LSB 提取命中 flag: {', '.join(flags)}")
        elif strings:
            lines.append(f"- LSB 提取文本: {' | '.join(strings[:10])}")
        else:
            lines.append(f"- LSB 提取: 无 flag/文本（{len(lsb)} 字节，预览 {lsb[:32].hex()}）")
    else:
        lines.append("- LSB 提取: 无数据")

    text = "\n".join(lines)
    if len(text) > STEGO_TEXT_LIMIT:
        text = text[:STEGO_TEXT_LIMIT] + "\n[隐写摘要已截断]"
    return text


def image_stego_lines(path: Path) -> List[str]:
    """读图片字节做隐写分析，返回注入上下文的行列表；不支持/失败返回空列表。

    这是给 attachment_context 的单行接入点：纯本地字节分析，同步、很快、失败即
    静默降级为 []，不影响视觉分析结果与整条任务链。
    """
    try:
        data = path.read_bytes()
    except OSError:
        return []
    result = analyze_image_stego(data)
    if result is None:
        return []
    return ["\n" + format_stego_summary(result)]
