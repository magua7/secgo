"""GIF 图片结构解析（纯 Python，无第三方依赖）。

目的：把用户上传的 GIF 附件变成 Agent 可用的结构化上下文——逻辑屏幕尺寸、多帧统计、
Comment/Plain Text/Application 扩展块文本、全局/局部调色板里埋的 ASCII 文本、Trailer 后
的尾随数据（图种检测）。所有输出带严格条数/字节上限；解析失败抛 ValueError，由上层转成
失败提示，绝不挂死任务链。

定位是「看字节」：与 vision 模块「看画面」互补。palette 索引 LSB 隐写需要 LZW 解码 +
调色板查表还原像素，明确不做，标注「不支持」。对标 runtime/jpeg_analysis.py 的模块结构
与接口约定。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

# ── 上限（防止大图拖垮上下文）──────────────────────────────
GIF_MAX_BLOCKS = 200            # 最多解析的块数
GIF_MAX_COMMENTS = 20           # Comment 注释条数
GIF_MAX_FRAMES = 50             # 记录帧数上限
GIF_MAX_PALETTE_STRINGS = 20    # 调色板里提取的可打印串条数
GIF_MAX_TRAILING = 512          # 尾随数据预览字节上限
GIF_CELL_DISPLAY = 160          # 单个块内容展示截断长度
GIF_MAX_FINDINGS = 20           # 敏感命中条数
GIF_TEXT_LIMIT = 8 * 1024       # 注入上下文的文本上限

# ── 扫描正则 ──────────────────────────────────────────────
_FLAG_RE = re.compile(rb"flag\{[^}\r\n]{1,80}\}", re.IGNORECASE)
_URL_RE = re.compile(rb"https?://[^\s\x00\"'<>]{4,120}")
_ASCII_STR_RE = re.compile(rb"[\x20-\x7e]{4,}")


# ── 子块读取 ──────────────────────────────────────────────


def _read_subblocks(data: bytes, pos: int) -> Tuple[bytes, int]:
    """读取 GIF 子块序列（size + data 重复，size=0 终止），返回 (拼接数据, 新位置)。"""
    parts: List[bytes] = []
    n = len(data)
    while pos < n:
        size = data[pos]
        pos += 1
        if size == 0:
            break
        if pos + size > n:
            break
        parts.append(data[pos:pos + size])
        pos += size
    return b"".join(parts), pos


def _skip_subblocks(data: bytes, pos: int) -> int:
    _, pos = _read_subblocks(data, pos)
    return pos


# ── 结构扫描 ──────────────────────────────────────────────


def _scan_gif(data: bytes) -> Dict[str, Any]:
    if not data.startswith((b"GIF87a", b"GIF89a")):
        raise ValueError("不是有效的 GIF 文件（缺 GIF 头）")
    n = len(data)
    pos = 6

    if pos + 7 > n:
        raise ValueError("GIF 逻辑屏幕描述符不完整")
    width = int.from_bytes(data[pos:pos + 2], "little")
    height = int.from_bytes(data[pos + 2:pos + 4], "little")
    packed = data[pos + 4]
    gct_flag = (packed >> 7) & 1
    gct_entries = (1 << ((packed & 0x07) + 1)) if gct_flag else 0
    pos += 7

    palettes: List[bytes] = []
    if gct_entries:
        gct = data[pos:pos + gct_entries * 3]
        palettes.append(gct)
        pos += gct_entries * 3

    comments: List[str] = []
    plain_texts: List[str] = []
    applications: List[Dict[str, Any]] = []
    frames: List[Dict[str, int]] = []
    block_count = 0
    trailer_end = n

    while pos < n:
        if block_count >= GIF_MAX_BLOCKS:
            break
        marker = data[pos]

        if marker == 0x3B:  # Trailer
            trailer_end = pos + 1
            break

        if marker == 0x2C:  # Image Descriptor
            if pos + 10 > n:
                break
            left = int.from_bytes(data[pos + 1:pos + 3], "little")
            top = int.from_bytes(data[pos + 3:pos + 5], "little")
            fw = int.from_bytes(data[pos + 5:pos + 7], "little")
            fh = int.from_bytes(data[pos + 7:pos + 9], "little")
            fpacked = data[pos + 9]
            pos += 10
            if len(frames) < GIF_MAX_FRAMES:
                frames.append({"left": left, "top": top, "width": fw, "height": fh})
            block_count += 1
            if fpacked >> 7:  # 局部调色板
                lct_entries = 1 << ((fpacked & 0x07) + 1)
                palettes.append(data[pos:pos + lct_entries * 3])
                pos += lct_entries * 3
            if pos < n:
                pos += 1  # LZW 最小码长
            pos = _skip_subblocks(data, pos)  # 图像数据子块
            continue

        if marker == 0x21:  # Extension
            if pos + 2 > n:
                break
            label = data[pos + 1]
            pos += 2
            block_count += 1

            if label == 0xFE:  # Comment
                raw, pos = _read_subblocks(data, pos)
                text = raw.decode("utf-8", "replace").strip()
                if text and len(comments) < GIF_MAX_COMMENTS:
                    comments.append(text[:GIF_CELL_DISPLAY])
            elif label == 0x01:  # Plain Text
                raw, pos = _read_subblocks(data, pos)
                text = raw[12:].decode("utf-8", "replace").strip()  # 跳过 12 字节网格头
                if text and len(plain_texts) < GIF_MAX_COMMENTS:
                    plain_texts.append(text[:GIF_CELL_DISPLAY])
            elif label == 0xFF:  # Application
                raw, pos = _read_subblocks(data, pos)
                if len(raw) >= 11 and len(applications) < GIF_MAX_COMMENTS:
                    applications.append({
                        "id": raw[:8].decode("ascii", "replace").strip("\x00 "),
                        "auth": raw[8:11].decode("ascii", "replace"),
                        "data": raw[11:],
                    })
            else:  # Graphic Control(0xF9) 等，跳过
                pos = _skip_subblocks(data, pos)
            continue

        # 未知字节，容错推进
        pos += 1

    palette_strings: List[str] = []
    for pal in palettes:
        for m in _ASCII_STR_RE.finditer(pal):
            s = m.group(0).decode("ascii", "replace")
            if s not in palette_strings and len(palette_strings) < GIF_MAX_PALETTE_STRINGS:
                palette_strings.append(s)

    return {
        "dimensions": {"width": width, "height": height},
        "frames": frames,
        "comments": comments,
        "plain_texts": plain_texts,
        "applications": applications,
        "palette_strings": palette_strings,
        "trailing": data[trailer_end:],
    }


# ── 尾随检测 ──────────────────────────────────────────────


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
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return ""


# ── 汇总 ──────────────────────────────────────────────────


def analyze_gif_bytes(data: bytes) -> Dict[str, Any]:
    """解析 GIF 字节流，返回带上限的结构化摘要。解析失败抛 ValueError。"""
    scan = _scan_gif(data)

    findings: List[str] = []
    finding_seen: set = set()

    def add_finding(text: str) -> None:
        if text not in finding_seen and len(findings) < GIF_MAX_FINDINGS:
            finding_seen.add(text)
            findings.append(text)

    def scan_text(haystack: bytes, source: str) -> None:
        for m in _FLAG_RE.finditer(haystack):
            add_finding(f"{source}命中 flag 形态: {m.group(0).decode('ascii', 'replace')}")
        for m in _URL_RE.finditer(haystack):
            add_finding(f"{source}命中 URL: {m.group(0).decode('ascii', 'replace')}")

    for text in scan["comments"]:
        scan_text(text.encode("utf-8", "replace"), "Comment 注释")
    for text in scan["plain_texts"]:
        scan_text(text.encode("utf-8", "replace"), "Plain Text")
    for app in scan["applications"]:
        scan_text(app["data"], f"Application({app['id']})")
    for text in scan["palette_strings"]:
        scan_text(text.encode("utf-8", "replace"), "调色板文本")

    trailing = scan["trailing"]
    return {
        "kind": "gif",
        "dimensions": scan["dimensions"],
        "frames": scan["frames"],
        "comments": scan["comments"],
        "plain_texts": scan["plain_texts"],
        "applications": scan["applications"],
        "palette_strings": scan["palette_strings"],
        "trailing": {
            "size": len(trailing),
            "kind": _detect_trailing_kind(trailing),
            "preview": trailing[:GIF_MAX_TRAILING],
        } if trailing else None,
        "findings": findings,
    }


# ── 文本格式化（注入 Agent 上下文）──────────────────────────


def _fmt_bytes_preview(data: bytes) -> str:
    if all(0x20 <= b <= 0x7E or b in (9, 10, 13) for b in data):
        return data.decode("ascii", "replace")
    return data.hex()


def format_gif_summary(result: Dict[str, Any]) -> str:
    dims = result.get("dimensions") or {}
    width, height = dims.get("width"), dims.get("height")
    dim_text = f"{width}x{height}" if width and height else "未知"
    frames = result.get("frames") or []
    lines = [
        f"[GIF 图片] 尺寸: {dim_text} | 帧数: {len(frames)}",
    ]

    palette_strings = result.get("palette_strings") or []
    if palette_strings:
        lines.append(f"调色板文本: {' | '.join(palette_strings)}")

    comments = result.get("comments") or []
    if comments:
        lines.append("注释(Comment):")
        for text in comments:
            lines.append(f"  - {text}")

    plain_texts = result.get("plain_texts") or []
    if plain_texts:
        lines.append("纯文本(Plain Text):")
        for text in plain_texts:
            lines.append(f"  - {text}")

    applications = result.get("applications") or []
    if applications:
        lines.append("应用扩展(Application):")
        for app in applications:
            lines.append(f"  - {app['id']} (auth={app['auth']}): {_fmt_bytes_preview(app['data'][:GIF_CELL_DISPLAY])}")

    trailing = result.get("trailing")
    if trailing:
        kind_hint = f"（疑似 {trailing['kind']}）" if trailing["kind"] else ""
        lines.append(
            f"尾随数据(Trailer 之后): {trailing['size']} 字节{kind_hint} -> {_fmt_bytes_preview(trailing['preview'])}"
        )

    findings = result.get("findings") or []
    if findings:
        lines.append("敏感命中:")
        for finding in findings:
            lines.append(f"  - {finding}")

    lines.append("不支持: palette 索引 LSB 隐写（需 LZW 解码 + 调色板查表）")

    text = "\n".join(lines)
    if len(text) > GIF_TEXT_LIMIT:
        text = text[:GIF_TEXT_LIMIT] + "\n[GIF 摘要已截断]"
    return text
