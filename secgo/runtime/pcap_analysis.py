"""PCAP/pcapng 流量包轻量解析（纯 Python，无第三方依赖）。

目的：把用户上传的流量包变成 Agent 可用的结构化上下文——协议分布、会话统计、
HTTP 请求与凭据线索、DNS 查询、TLS SNI、敏感串命中。所有输出都有严格的
条数/字节上限；解析失败抛 ValueError，由上层转成失败提示，绝不挂死任务链。

定位是「让 Agent 知道包里有什么、该往哪查」的第一层提取，不做深度 DPI。
"""

from __future__ import annotations

import base64
import ipaddress
import re
import struct
import time
from collections import Counter
from typing import Any, Dict, Iterator, List, Optional, Tuple

# ── 上限（防止大流量包拖垮上下文）──────────────────────────
PCAP_MAX_PACKETS = 20_000      # 最多解析的数据包数
PCAP_MAX_HTTP_ITEMS = 40       # 最多保留的 HTTP 请求条数
PCAP_MAX_DNS_ITEMS = 60        # 最多保留的 DNS 查询域名数
PCAP_MAX_SNI_ITEMS = 40        # 最多保留的 TLS SNI 域名数
PCAP_MAX_SESSIONS = 15         # 会话 TOP 榜条数
PCAP_MAX_FINDINGS = 20         # 敏感命中条数
PCAP_MAX_CREDENTIALS = 10      # 凭据线索条数
PCAP_PAYLOAD_SCAN = 4 * 1024   # 每包敏感串扫描的字节上限
PCAP_HTTP_HEADER_SCAN = 8 * 1024  # HTTP 头部扫描字节上限
PCAP_TEXT_LIMIT = 12 * 1024    # 注入上下文的文本上限

# ── 魔数识别（与 attachments.classify_basic_file 保持一致）────
_PCAP_MAGICS = {
    b"\xd4\xc3\xb2\xa1": ("<", False),   # pcap 小端 微秒
    b"\xa1\xb2\xc3\xd4": (">", False),   # pcap 大端 微秒
    b"\x4d\x3c\xb2\xa1": ("<", True),    # pcap 小端 纳秒
    b"\xa1\xb2\x3c\x4d": (">", True),    # pcap 大端 纳秒
}
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"

_LINK_TYPES = {1: "Ethernet", 101: "Raw IP", 113: "Linux SLL"}

_IP_PROTO_NAMES = {1: "ICMP", 6: "TCP", 17: "UDP", 47: "GRE", 58: "ICMPv6", 132: "SCTP"}

_HTTP_METHODS = (b"GET ", b"POST ", b"PUT ", b"DELETE ", b"PATCH ", b"HEAD ", b"OPTIONS ")

_FLAG_RE = re.compile(rb"flag\{[^}\r\n]{1,80}\}", re.IGNORECASE)
_SECRET_RE = re.compile(
    rb"(?i)(?:password|passwd|pwd|token|secret|api[_-]?key)\s*[=:]\s*([A-Za-z0-9_\-./+=]{4,64})"
)


# ── 容器层解析 ────────────────────────────────────────────


def _iter_pcap(data: bytes) -> Iterator[Tuple[int, bytes]]:
    """pcap 经典格式：yield (时间戳微秒, 帧字节)。容忍尾部截断。"""
    endian, is_nsec = _PCAP_MAGICS[data[:4]]
    if len(data) < 24:
        raise ValueError("pcap 全局头不完整")
    _major, _minor, _tz, _sig, _snap, network = struct.unpack(endian + "HHiIII", data[4:24])
    linktype = network & 0xFFFF
    offset = 24
    count = 0
    while offset + 16 <= len(data) and count < PCAP_MAX_PACKETS:
        ts_sec, ts_frac, incl_len, _orig = struct.unpack(endian + "IIII", data[offset:offset + 16])
        offset += 16
        if incl_len > len(data) - offset:
            break  # 尾包被截断，到此为止
        frame = data[offset:offset + incl_len]
        offset += incl_len
        count += 1
        ts_us = ts_sec * 1_000_000 + (ts_frac // 1000 if is_nsec else ts_frac)
        yield linktype, ts_us, frame


def _iter_pcapng(data: bytes) -> Iterator[Tuple[int, bytes]]:
    """pcapng 最小解析：只取 SHB 字节序 / IDB 链路层与时间精度 / EPB·SPB 数据包。"""
    if len(data) < 12:
        raise ValueError("pcapng 文件头不完整")
    bom = data[8:12]
    if bom == b"\x4d\x3c\x2b\x1a":
        endian = "<"
    elif bom == b"\x1a\x2b\x3c\x4d":
        endian = ">"
    else:
        raise ValueError("pcapng 字节序标识无效")

    linktype = 1
    ts_resol = 6  # if_tsresol 默认 6 → 单位微秒
    offset = 0
    count = 0
    while offset + 8 <= len(data) and count < PCAP_MAX_PACKETS:
        block_type, block_len = struct.unpack(endian + "II", data[offset:offset + 8])
        if block_len < 12 or offset + block_len > len(data):
            break
        body = data[offset + 8:offset + block_len - 4]
        if block_type == 0x00000001 and len(body) >= 8:  # IDB
            linktype = struct.unpack(endian + "H", body[:2])[0]
            p = 8
            while p + 4 <= len(body):
                code, olen = struct.unpack(endian + "HH", body[p:p + 4])
                if code == 0:  # opt_endofopt
                    break
                if code == 9 and olen >= 1 and p + 4 + olen <= len(body):
                    ts_resol = body[p + 4]
                p += 4 + olen + ((-olen) % 4)
        elif block_type == 0x00000006 and len(body) >= 20:  # EPB
            _iface, ts_high, ts_low, cap_len, _orig = struct.unpack(endian + "IIIII", body[:20])
            if cap_len <= len(body) - 20:
                raw_ts = (ts_high << 32) | ts_low
                ts_us = int(raw_ts * (10 ** -ts_resol) * 1_000_000) if ts_resol < 128 else 0
                count += 1
                yield linktype, ts_us, body[20:20 + cap_len]
        elif block_type == 0x00000003 and len(body) >= 4:  # SPB
            orig_len = struct.unpack(endian + "I", body[:4])[0]
            cap_len = min(orig_len, len(body) - 4)
            count += 1
            yield linktype, 0, body[4:4 + cap_len]
        offset += block_len


# ── 协议层解析 ────────────────────────────────────────────


def _parse_frame(frame: bytes, linktype: int) -> Tuple[str, Optional[bytes]]:
    """链路层分派：返回 (协议名, L3 载荷)；无法识别返回 ("other", None)。"""
    if linktype == 1:  # Ethernet
        if len(frame) < 14:
            return "other", None
        ethertype = int.from_bytes(frame[12:14], "big")
        off = 14
        if ethertype == 0x8100:  # VLAN tag
            if len(frame) < 18:
                return "other", None
            ethertype = int.from_bytes(frame[16:18], "big")
            off = 18
        if ethertype == 0x0806:
            return "ARP", None
        if ethertype == 0x0800:
            return "IPv4", frame[off:]
        if ethertype == 0x86DD:
            return "IPv6", frame[off:]
        return "other", None
    if linktype == 101:  # Raw IP
        if len(frame) >= 20 and (frame[0] >> 4) == 4:
            return "IPv4", frame
        return "other", None
    if linktype == 113:  # Linux SLL
        if len(frame) < 16:
            return "other", None
        proto = int.from_bytes(frame[14:16], "big")
        if proto == 0x0800:
            return "IPv4", frame[16:]
        if proto == 0x86DD:
            return "IPv6", frame[16:]
        return "other", None
    return "other", None


def _parse_ipv4(data: bytes) -> Optional[Tuple[str, str, int, bytes]]:
    if len(data) < 20 or (data[0] >> 4) != 4:
        return None
    ihl = (data[0] & 0x0F) * 4
    if ihl < 20 or len(data) < ihl:
        return None
    src = ".".join(str(b) for b in data[12:16])
    dst = ".".join(str(b) for b in data[16:20])
    return src, dst, data[9], data[ihl:]


def _parse_ipv6(data: bytes) -> Optional[Tuple[str, str, int, Optional[bytes]]]:
    if len(data) < 40 or (data[0] >> 4) != 6:
        return None
    src = str(ipaddress.IPv6Address(data[8:24]))
    dst = str(ipaddress.IPv6Address(data[24:40]))
    nxt = data[6]
    payload = data[40:] if nxt in (6, 17) else None  # 扩展头不深挖
    return src, dst, nxt, payload


def _parse_tcp(data: bytes) -> Optional[Tuple[int, int, bytes]]:
    if len(data) < 20:
        return None
    sport, dport = struct.unpack("!HH", data[:4])
    doff = (data[12] >> 4) * 4
    if doff < 20 or len(data) < doff:
        return None
    return sport, dport, data[doff:]


def _parse_udp(data: bytes) -> Optional[Tuple[int, int, bytes]]:
    if len(data) < 8:
        return None
    sport, dport, _ulen = struct.unpack("!HHH", data[:6])
    return sport, dport, data[8:]


# ── 应用层提取 ────────────────────────────────────────────


def _decode_basic(credential: str) -> Optional[str]:
    try:
        decoded = base64.b64decode(credential.strip(), validate=True).decode("utf-8", "replace")
        return decoded[:80]
    except Exception:
        return None


def _parse_http_head(head_text: str) -> Optional[Dict[str, Any]]:
    lines = head_text.split("\r\n")
    first = lines[0].split(" ")
    is_request = any(head_text.startswith(m.decode()) for m in _HTTP_METHODS)
    headers: Dict[str, str] = {}
    for line in lines[1:60]:
        if not line:
            break
        if ":" in line:
            k, v = line.split(":", 1)
            headers.setdefault(k.strip().lower(), v.strip())

    info: Dict[str, Any] = {"headers": headers}
    if is_request and len(first) >= 2:
        info.update({
            "kind": "request",
            "method": first[0],
            "path": first[1][:200],
            "host": headers.get("host", "")[:100],
        })
    elif first and first[0].startswith("HTTP/") and len(first) >= 2:
        try:
            info.update({"kind": "response", "status": int(first[1])})
        except ValueError:
            return None
    else:
        return None
    return info


def _parse_http_payload(payload: bytes) -> Optional[Dict[str, Any]]:
    if not payload:
        return None
    head = payload[:PCAP_HTTP_HEADER_SCAN]
    if not any(head.startswith(m) for m in _HTTP_METHODS) and not head.startswith(b"HTTP/"):
        return None
    text = head.decode("iso-8859-1", "replace")
    return _parse_http_head(text)


def _parse_dns_name(payload: bytes, offset: int) -> Tuple[str, int]:
    """解析 DNS QNAME（支持压缩指针），返回 (域名, 消费到的偏移)。"""
    labels: List[bytes] = []
    pos = offset
    end = offset
    jumps = 0
    while pos < len(payload):
        length = payload[pos]
        if length == 0:
            if end == offset:
                end = pos + 1
            break
        if length & 0xC0 == 0xC0:
            if pos + 2 > len(payload):
                break
            if end == offset:
                end = pos + 2
            pos = ((length & 0x3F) << 8) | payload[pos + 1]
            jumps += 1
            if jumps > 4:
                break
            continue
        if length > 63 or pos + 1 + length > len(payload) or len(labels) > 20:
            break
        labels.append(payload[pos + 1:pos + 1 + length])
        pos += 1 + length
    return ".".join(label.decode("ascii", "replace") for label in labels), end


def _parse_dns_queries(payload: bytes) -> List[str]:
    if len(payload) < 12:
        return []
    qdcount = struct.unpack("!H", payload[4:6])[0]
    names: List[str] = []
    pos = 12
    for _ in range(min(qdcount, 8)):
        name, pos = _parse_dns_name(payload, pos)
        if name:
            names.append(name[:200])
        pos += 4  # QTYPE + QCLASS
        if pos >= len(payload):
            break
    return names


def _parse_tls_sni(payload: bytes) -> Optional[str]:
    """从 TLS ClientHello 提取 SNI 域名。"""
    if len(payload) < 45 or payload[0] != 0x16 or payload[5] != 0x01:
        return None
    # record 头(0..4) + hs 类型(5) + hs 长度(6..8) + client_version(9..10) + random(11..42)
    p = 43  # session_id_len 所在字节
    sid_len = payload[p]
    p += 1 + sid_len
    if len(payload) < p + 2:
        return None
    cs_len = int.from_bytes(payload[p:p + 2], "big")
    p += 2 + cs_len
    if len(payload) < p + 1:
        return None
    p += 1 + payload[p]  # compression methods
    if len(payload) < p + 2:
        return None
    ext_total = int.from_bytes(payload[p:p + 2], "big")
    p += 2
    end = min(len(payload), p + ext_total)
    while p + 4 <= end:
        etype = int.from_bytes(payload[p:p + 2], "big")
        elen = int.from_bytes(payload[p + 2:p + 4], "big")
        body = payload[p + 4:p + 4 + elen]
        if etype == 0x0000 and len(body) >= 5 and body[2] == 0:
            nlen = int.from_bytes(body[3:5], "big")
            if 5 + nlen <= len(body):
                name = body[5:5 + nlen].decode("ascii", "replace")
                if name:
                    return name[:200]
        p += 4 + elen
    return None


# ── 汇总 ──────────────────────────────────────────────────


def analyze_pcap_bytes(data: bytes) -> Dict[str, Any]:
    """解析 pcap/pcapng 字节流，返回带上限的结构化摘要。解析失败抛 ValueError。"""
    if data.startswith(PCAPNG_MAGIC):
        fmt = "pcapng"
        packets = _iter_pcapng(data)
    elif data[:4] in _PCAP_MAGICS:
        fmt = "pcap"
        packets = _iter_pcap(data)
    else:
        raise ValueError("不是有效的 pcap/pcapng 文件")

    linktype = 1
    proto_counts: Counter = Counter()
    sessions: Counter = Counter()
    first_ts: Optional[int] = None
    last_ts: Optional[int] = None
    http_requests: List[Dict[str, Any]] = []
    http_status: Counter = Counter()
    dns_queries: List[str] = []
    sni_names: List[str] = []
    credentials: List[Dict[str, str]] = []
    findings: List[str] = []
    finding_seen: set = set()

    def add_finding(text: str) -> None:
        if text not in finding_seen and len(findings) < PCAP_MAX_FINDINGS:
            finding_seen.add(text)
            findings.append(text)

    packets_seen = 0
    for linktype, ts_us, frame in packets:
        packets_seen += 1
        if ts_us:
            if first_ts is None or ts_us < first_ts:
                first_ts = ts_us
            if last_ts is None or ts_us > last_ts:
                last_ts = ts_us

        l2_name, l3 = _parse_frame(frame, linktype)
        if l2_name == "other":
            proto_counts["other"] += 1
            continue
        if l2_name == "ARP":
            proto_counts["ARP"] += 1
            continue

        transport: Optional[Tuple[Any, ...]] = None
        payload = b""
        if l2_name == "IPv4" and l3 is not None:
            parsed = _parse_ipv4(l3)
            if parsed is None:
                proto_counts["other"] += 1
                continue
            src, dst, proto, l4 = parsed
        elif l2_name == "IPv6" and l3 is not None:
            parsed = _parse_ipv6(l3)
            if parsed is None:
                proto_counts["other"] += 1
                continue
            src, dst, proto, l4 = parsed
        else:
            proto_counts["other"] += 1
            continue

        if proto == 6:
            proto_counts["TCP"] += 1
            if l4 is None:
                continue
            tcp = _parse_tcp(l4)
            if tcp is None:
                continue
            sport, dport, payload = tcp
            transport = (src, sport, dst, dport)
        elif proto == 17:
            proto_counts["UDP"] += 1
            if l4 is None:
                continue
            udp = _parse_udp(l4)
            if udp is None:
                continue
            sport, dport, payload = udp
            transport = (src, sport, dst, dport)
        else:
            proto_counts[_IP_PROTO_NAMES.get(proto, f"IP({proto})")] += 1
            continue

        if transport is not None:
            a, b = (transport[0], transport[1]), (transport[2], transport[3])
            lo, hi = (a, b) if a <= b else (b, a)
            sessions[f"{lo[0]}:{lo[1]} <=> {hi[0]}:{hi[1]}"] += 1

        if not payload:
            continue
        scan = payload[:PCAP_PAYLOAD_SCAN]

        # HTTP
        # HTTP（前缀判断在 _parse_http_payload 内部，未命中即返回 None，开销极小）
        http = _parse_http_payload(payload)
        if http is not None:
            if http["kind"] == "request":
                if len(http_requests) < PCAP_MAX_HTTP_ITEMS:
                    entry = {k: http[k] for k in ("method", "host", "path")}
                    auth = http["headers"].get("authorization", "")
                    if auth.lower().startswith("basic "):
                        decoded = _decode_basic(auth[6:])
                        entry["basic"] = (decoded or auth[6:])[:80]
                        if len(credentials) < PCAP_MAX_CREDENTIALS:
                            credentials.append({
                                "kind": "Basic", "value": decoded or "(解码失败)",
                                "src": src,
                            })
                    if http["headers"].get("cookie"):
                        entry["cookie"] = True
                    http_requests.append(entry)
            else:
                http_status[http.get("status", 0)] += 1

        # DNS
        dns_ports = (53, 5353, 5355)
        if transport and (transport[1] in dns_ports or transport[3] in dns_ports):
            if len(dns_queries) < PCAP_MAX_DNS_ITEMS:
                for name in _parse_dns_queries(payload[:512]):
                    if name and name not in dns_queries and len(dns_queries) < PCAP_MAX_DNS_ITEMS:
                        dns_queries.append(name)

        # TLS SNI
        if transport and (transport[1] == 443 or transport[3] == 443):
            if len(sni_names) < PCAP_MAX_SNI_ITEMS:
                sni = _parse_tls_sni(payload[:PCAP_HTTP_HEADER_SCAN])
                if sni and sni not in sni_names:
                    sni_names.append(sni)

        # 敏感串
        for match in _FLAG_RE.finditer(scan):
            add_finding(f"命中 flag 形态数据: {match.group(0).decode('ascii', 'replace')}")
        for match in _SECRET_RE.finditer(scan):
            add_finding(f"疑似密码/令牌字段: {match.group(0).decode('ascii', 'replace')[:120]} (来自 {src})")

    duration_s = max(0, (last_ts or 0) - (first_ts or 0)) // 1_000_000
    return {
        "format": fmt,
        "link_type": _LINK_TYPES.get(linktype, f"type {linktype}"),
        "packets_seen": packets_seen,
        "first_ts": first_ts,
        "last_ts": last_ts,
        "duration_seconds": duration_s,
        "protocols": dict(proto_counts),
        "sessions_top": sessions.most_common(PCAP_MAX_SESSIONS),
        "http_requests": http_requests,
        "http_status": dict(http_status),
        "dns_queries": dns_queries,
        "tls_sni": sni_names,
        "credentials": credentials,
        "findings": findings,
    }


# ── 文本格式化（注入 Agent 上下文）──────────────────────────


def _fmt_ts(ts_us: Optional[int]) -> str:
    if not ts_us:
        return "?"
    return time.strftime("%m-%d %H:%M:%S", time.localtime(ts_us / 1_000_000))


def format_pcap_summary(result: Dict[str, Any]) -> str:
    protocols = result.get("protocols") or {}
    proto_text = ", ".join(f"{k} {v}" for k, v in protocols.items()) or "无"
    lines = [
        f"[PCAP 流量包] 格式: {result['format']} | 链路层: {result['link_type']} | "
        f"数据包: {result['packets_seen']} 个",
        f"时间范围: {_fmt_ts(result.get('first_ts'))} ~ {_fmt_ts(result.get('last_ts'))}"
        f"（约 {result.get('duration_seconds', 0)} 秒）",
        f"协议分布: {proto_text}",
    ]

    sessions = result.get("sessions_top") or []
    if sessions:
        lines.append(f"会话 TOP（共 {len(sessions)} 个，按包数排序）:")
        for i, (key, count) in enumerate(sessions, 1):
            lines.append(f"  {i}. {key} — {count} 包")

    requests = result.get("http_requests") or []
    if requests:
        lines.append(f"HTTP 请求（前 {len(requests)} 个）:")
        for req in requests:
            basic = f" [Basic: {req['basic']}]" if req.get("basic") else ""
            cookie = " [Cookie]" if req.get("cookie") else ""
            lines.append(f"  {req['method']} {req['host']}{req['path']}{basic}{cookie}")

    status = result.get("http_status") or {}
    if status:
        status_text = ", ".join(f"{code} x{n}" for code, n in sorted(status.items()))
        lines.append(f"HTTP 响应状态: {status_text}")

    dns = result.get("dns_queries") or []
    if dns:
        lines.append(f"DNS 查询（前 {len(dns)} 个）: {', '.join(dns)}")

    sni = result.get("tls_sni") or []
    if sni:
        lines.append(f"TLS SNI（前 {len(sni)} 个）: {', '.join(sni)}")

    credentials = result.get("credentials") or []
    if credentials:
        lines.append("凭据线索:")
        for cred in credentials:
            lines.append(f"  [{cred['kind']}] {cred['value']} (来自 {cred['src']})")

    findings = result.get("findings") or []
    if findings:
        lines.append("敏感命中:")
        for finding in findings:
            lines.append(f"  - {finding}")

    text = "\n".join(lines)
    if len(text) > PCAP_TEXT_LIMIT:
        text = text[:PCAP_TEXT_LIMIT] + "\n[PCAP 摘要已截断]"
    return text
