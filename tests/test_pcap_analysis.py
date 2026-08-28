"""PCAP 流量包解析测试：全部用程序化构造的字节流，不依赖真实抓包样本。"""

from __future__ import annotations

import base64
import struct
import tempfile
import unittest
from pathlib import Path

from secgo.runtime.attachments import extract_limited_text
from secgo.runtime.pcap_analysis import (
    PCAP_MAX_DNS_ITEMS,
    analyze_pcap_bytes,
    format_pcap_summary,
)


# ── 字节流构造辅助 ─────────────────────────────────────────


def _eth(payload: bytes, ethertype: int = 0x0800) -> bytes:
    return b"\x00\x11\x22\x33\x44\x55" + b"\x66\x77\x88\x99\xaa\xbb" + struct.pack("!H", ethertype) + payload


def _ipv4(src: str, dst: str, proto: int, payload: bytes) -> bytes:
    total = 20 + len(payload)
    header = struct.pack("!BBHHHBBH", 0x45, 0, total, 0x1234, 0, 64, proto, 0)
    header += bytes(int(x) for x in src.split("."))
    header += bytes(int(x) for x in dst.split("."))
    return header + payload


def _tcp(sport: int, dport: int, payload: bytes = b"", flags: int = 0x18) -> bytes:
    return struct.pack("!HHIIBBHHH", sport, dport, 1000, 2000, 5 << 4, flags, 8192, 0, 0) + payload


def _udp(sport: int, dport: int, payload: bytes = b"") -> bytes:
    return struct.pack("!HHHH", sport, dport, 8 + len(payload), 0) + payload


def _dns_query(name: str, qtype: int = 1) -> bytes:
    labels = b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\x00"
    return struct.pack("!HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0) + labels + struct.pack("!HH", qtype, 1)


def _tls_client_hello(sni: bytes) -> bytes:
    sn_entry = b"\x00" + struct.pack("!H", len(sni)) + sni
    sn_list = struct.pack("!H", len(sn_entry)) + sn_entry
    sn_ext = b"\x00\x00" + struct.pack("!H", len(sn_list)) + sn_list
    body = b"\x03\x03" + b"\x00" * 32 + b"\x00"
    body += struct.pack("!H", 2) + b"\x13\x01"
    body += b"\x01\x00"
    body += struct.pack("!H", len(sn_ext)) + sn_ext
    handshake = b"\x01" + len(body).to_bytes(3, "big") + body
    return b"\x16\x03\x01" + struct.pack("!H", len(handshake)) + handshake


_HTTP_REQUEST = (
    b"GET /admin HTTP/1.1\r\n"
    b"Host: example.com\r\n"
    b"Authorization: Basic " + base64.b64encode(b"admin:1234") + b"\r\n"
    b"Cookie: session=abc123\r\n"
    b"\r\n"
)


def _pcap_bytes(packets, linktype: int = 1, endian: str = "<", nsec: bool = False) -> bytes:
    magic = {
        ("<", False): b"\xd4\xc3\xb2\xa1", (">", False): b"\xa1\xb2\xc3\xd4",
        ("<", True): b"\x4d\x3c\xb2\xa1", (">", True): b"\xa1\xb2\x3c\x4d",
    }[(endian, nsec)]
    data = magic + struct.pack(endian + "HHiIII", 2, 4, 0, 0, 65535, linktype)
    for i, packet in enumerate(packets):
        ts_frac = (i * 1_000_000) if nsec else (i * 1000)
        data += struct.pack(endian + "IIII", 1_700_000_000 + i, ts_frac, len(packet), len(packet))
        data += packet
    return data


def _pcapng_bytes(packets, linktype: int = 1) -> bytes:
    shb = struct.pack("<III", 0x0A0D0D0A, 28, 0x1A2B3C4D)
    shb += struct.pack("<HHq", 1, 0, -1) + struct.pack("<I", 28)
    idb_body = struct.pack("<HHI", linktype, 0, 65535)
    idb = struct.pack("<II", 0x00000001, 20) + idb_body + struct.pack("<I", 20)
    blocks = shb + idb
    for i, packet in enumerate(packets):
        ts = (1_700_000_000 + i) * 1_000_000
        padded = packet + b"\x00" * ((-len(packet)) % 4)
        body = struct.pack("<IIIII", 0, ts >> 32, ts & 0xFFFFFFFF, len(packet), len(packet)) + padded
        total = 8 + len(body) + 4
        blocks += struct.pack("<II", 0x00000006, total) + body + struct.pack("<I", total)
    return blocks


def _http_get_packet() -> bytes:
    return _eth(_ipv4("10.0.0.1", "10.0.0.2", 6, _tcp(40000, 80, _HTTP_REQUEST)))


def _dns_packet(name: str = "example.com") -> bytes:
    return _eth(_ipv4("10.0.0.1", "10.0.0.2", 17, _udp(40001, 53, _dns_query(name))))


# ── 解析用例 ───────────────────────────────────────────────


class PcapParseTests(unittest.TestCase):
    def test_http_request_with_basic_credential_and_cookie(self):
        result = analyze_pcap_bytes(_pcap_bytes([_http_get_packet()]))
        self.assertEqual(len(result["http_requests"]), 1)
        req = result["http_requests"][0]
        self.assertEqual(req["method"], "GET")
        self.assertEqual(req["host"], "example.com")
        self.assertEqual(req["path"], "/admin")
        self.assertIn("admin:1234", req["basic"])
        self.assertTrue(req["cookie"])
        self.assertEqual(result["credentials"][0]["value"], "admin:1234")
        self.assertEqual(result["credentials"][0]["src"], "10.0.0.1")

    def test_dns_query_captured(self):
        result = analyze_pcap_bytes(_pcap_bytes([_dns_packet("internal.corp.local")]))
        self.assertIn("internal.corp.local", result["dns_queries"])
        self.assertEqual(result["protocols"].get("UDP"), 1)

    def test_tls_sni_extracted(self):
        tls = _eth(_ipv4("10.0.0.1", "93.184.216.34", 6, _tcp(40002, 443, _tls_client_hello(b"target.example.net"))))
        result = analyze_pcap_bytes(_pcap_bytes([tls]))
        self.assertIn("target.example.net", result["tls_sni"])

    def test_flag_finding_detected(self):
        payload = _tcp(40003, 8080, b"some data ... flag{p4ck3t_hunt3r} ... end")
        result = analyze_pcap_bytes(_pcap_bytes([_eth(_ipv4("10.0.0.9", "10.0.0.2", 6, payload))]))
        self.assertTrue(any("flag{p4ck3t_hunt3r}" in f for f in result["findings"]))

    def test_password_field_finding(self):
        body = b"POST /login HTTP/1.1\r\nHost: x.com\r\nContent-Length: 22\r\n\r\nuser=a&password=hunter2"
        packet = _eth(_ipv4("10.0.0.1", "10.0.0.2", 6, _tcp(40004, 80, body)))
        result = analyze_pcap_bytes(_pcap_bytes([packet]))
        self.assertTrue(any("password=hunter2" in f for f in result["findings"]))

    def test_protocol_counts_and_sessions(self):
        arp_frame = _eth(b"\x00" * 28, ethertype=0x0806)
        packets = [_http_get_packet(), _dns_packet(), arp_frame]
        result = analyze_pcap_bytes(_pcap_bytes(packets))
        self.assertEqual(result["protocols"].get("TCP"), 1)
        self.assertEqual(result["protocols"].get("UDP"), 1)
        self.assertEqual(result["protocols"].get("ARP"), 1)
        # 会话 key 规范化：两端按 (ip, port) 字典序排序
        self.assertTrue(any("10.0.0.1:40000 <=> 10.0.0.2:80" in s for s, _ in result["sessions_top"]))
        self.assertEqual(result["packets_seen"], 3)

    def test_http_response_status_counted(self):
        body = b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\nok"
        packet = _eth(_ipv4("10.0.0.2", "10.0.0.1", 6, _tcp(80, 40000, body)))
        result = analyze_pcap_bytes(_pcap_bytes([packet]))
        self.assertEqual(result["http_status"].get(200), 1)

    def test_big_endian_pcap(self):
        result = analyze_pcap_bytes(_pcap_bytes([_http_get_packet(), _dns_packet()], endian=">"))
        self.assertEqual(result["packets_seen"], 2)
        self.assertEqual(result["http_requests"][0]["host"], "example.com")

    def test_nanosecond_pcap(self):
        result = analyze_pcap_bytes(_pcap_bytes([_dns_packet()], nsec=True))
        self.assertEqual(result["packets_seen"], 1)

    def test_pcapng_epb(self):
        result = analyze_pcap_bytes(_pcapng_bytes([_http_get_packet(), _dns_packet()]))
        self.assertEqual(result["format"], "pcapng")
        self.assertEqual(result["packets_seen"], 2)
        self.assertEqual(result["http_requests"][0]["path"], "/admin")
        self.assertIn("example.com", result["dns_queries"])

    def test_vlan_tagged_frame(self):
        inner = _ipv4("10.0.0.1", "10.0.0.2", 17, _udp(40001, 53, _dns_query("vlan.local")))
        outer = (b"\x00\x11\x22\x33\x44\x55" + b"\x66\x77\x88\x99\xaa\xbb"
                 + b"\x81\x00" + b"\x00\x64" + b"\x08\x00" + inner)
        result = analyze_pcap_bytes(_pcap_bytes([outer]))
        self.assertIn("vlan.local", result["dns_queries"])

    def test_truncated_tail_tolerated(self):
        good = _pcap_bytes([_dns_packet()])
        # 追加一个声明长度超出剩余字节的记录头 → 尾包截断，不应崩溃
        bad_tail = struct.pack("<IIII", 1_700_000_099, 0, 500, 500) + b"\x00" * 10
        result = analyze_pcap_bytes(good + bad_tail)
        self.assertEqual(result["packets_seen"], 1)

    def test_invalid_magic_raises(self):
        with self.assertRaises(ValueError):
            analyze_pcap_bytes(b"\x00\x01\x02\x03not a pcap at all" * 4)

    def test_dns_queries_capped(self):
        packets = [_dns_packet(f"host{i}.example.com") for i in range(PCAP_MAX_DNS_ITEMS + 20)]
        result = analyze_pcap_bytes(_pcap_bytes(packets))
        self.assertEqual(len(result["dns_queries"]), PCAP_MAX_DNS_ITEMS)

    def test_unknown_linktype_counts_packets_without_l3(self):
        # linktype 0 (BSD loopback)：帧前 4 字节地址族，这里给无法识别的内容
        frame = struct.pack("<I", 2) + _ipv4("10.0.0.1", "10.0.0.2", 6, _tcp(1, 2))
        result = analyze_pcap_bytes(_pcap_bytes([frame], linktype=0))
        self.assertEqual(result["packets_seen"], 1)
        self.assertEqual(result["protocols"], {"other": 1})


class PcapFormattingTests(unittest.TestCase):
    def test_format_contains_key_sections(self):
        packets = [_http_get_packet(), _dns_packet()]
        packets.append(_eth(_ipv4("10.0.0.9", "10.0.0.2", 6, _tcp(40005, 8080, b"data flag{t3st_fl4g}"))))
        text = format_pcap_summary(analyze_pcap_bytes(_pcap_bytes(packets)))
        self.assertIn("[PCAP 流量包]", text)
        self.assertIn("协议分布", text)
        self.assertIn("HTTP 请求", text)
        self.assertIn("admin:1234", text)
        self.assertIn("DNS 查询", text)
        self.assertIn("flag{t3st_fl4g}", text)

    def test_format_truncated_when_huge(self):
        from secgo.runtime.pcap_analysis import PCAP_TEXT_LIMIT
        packets = [_dns_packet(f"h{i}.example.com") for i in range(60)]
        text = format_pcap_summary(analyze_pcap_bytes(_pcap_bytes(packets)))
        self.assertLessEqual(len(text), PCAP_TEXT_LIMIT + 100)


class PcapIntegrationTests(unittest.TestCase):
    def test_extract_limited_text_pcap_branch(self):
        data = _pcap_bytes([_http_get_packet(), _dns_packet()])
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as handle:
            handle.write(data)
            path = Path(handle.name)
        try:
            text = extract_limited_text(path, "pcap")
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNotNone(text)
        self.assertIn("[PCAP 流量包]", text)
        self.assertIn("/admin", text)

    def test_extract_limited_text_pcap_invalid_returns_failure_message(self):
        with tempfile.NamedTemporaryFile(suffix=".pcap", delete=False) as handle:
            handle.write(b"garbage garbage garbage")
            path = Path(handle.name)
        try:
            text = extract_limited_text(path, "pcap")
        finally:
            path.unlink(missing_ok=True)
        self.assertIsNotNone(text)
        self.assertIn("[PCAP 解析失败]", text)


if __name__ == "__main__":
    unittest.main()
