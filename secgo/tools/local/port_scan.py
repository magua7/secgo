#!/usr/bin/env python3
# @secgo-tool {"name":"port_scan","description":"对目标主机进行端口扫描（基于 Python socket）。适用于需要快速检测常用端口开放状态的场景。","agents":["operator"],"inputs":{"target":{"type":"string","description":"目标主机或 IP 地址","required":true},"ports":{"type":"string","description":"要扫描的端口列表，逗号分隔，默认扫描常用端口"}}}
import json
import socket
import sys

COMMON_PORTS = [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 993, 995, 1433, 1521, 3306, 3389, 5432, 6379, 7001, 8000, 8080, 8443, 8888, 9000, 9090, 9200, 27017]

def scan(target, ports):
    open_ports = []
    for port in ports:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        try:
            if sock.connect_ex((target, port)) == 0:
                open_ports.append(port)
        finally:
            sock.close()
    return open_ports

def main():
    try:
        args = json.loads(sys.argv[1] if len(sys.argv) > 1 else '{}')
    except json.JSONDecodeError:
        args = {}
    target = args.get('target', '')
    ports_raw = args.get('ports', '')
    if not target:
        print(json.dumps({'output': 'target is required', 'error': 'Missing target'}))
        return
    try:
        ports = [int(p) for p in ports_raw.split(',') if p.strip()] if ports_raw else COMMON_PORTS
    except ValueError:
        ports = COMMON_PORTS
    open_ports = scan(target, ports)
    result = {
        'target': target,
        'scanned': len(ports),
        'open': open_ports,
        'summary': f"{len(open_ports)} open port(s): {', '.join(map(str, open_ports)) or 'none'}",
    }
    print(json.dumps({'output': json.dumps(result)}))

if __name__ == '__main__':
    main()
