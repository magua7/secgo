<?php
// @secgo-tool {"name":"dns_lookup","description":"DNS 解析工具，查询域名对应的 A/AAAA/CNAME 记录。适用于需要获取目标 IP 地址或验证域名解析的场景。","agents":["research"],"inputs":{"domain":{"type":"string","description":"要查询的域名","required":true},"record_type":{"type":"string","description":"记录类型：A、AAAA、CNAME、MX、TXT（默认 A）"}}}
$args = json_decode($argv[1] ?? '{}', true);
$domain = $args['domain'] ?? '';
$type = strtoupper($args['record_type'] ?? 'A');
if ($domain === '') {
    echo json_encode(['output' => 'domain is required', 'error' => 'Missing domain']);
    exit;
}
$records = @dns_get_record($domain, $type === 'A' ? DNS_A : ($type === 'AAAA' ? DNS_AAAA : ($type === 'CNAME' ? DNS_CNAME : ($type === 'MX' ? DNS_MX : DNS_TXT))));
if ($records === false || empty($records)) {
    echo json_encode(['output' => "No $type records found for $domain"]);
    exit;
}
$out = [];
foreach ($records as $r) {
    $out[] = [
        'host' => $r['host'] ?? $domain,
        'type' => $r['type'] ?? $type,
        'value' => $r['ip'] ?? $r['target'] ?? $r['txt'] ?? '',
    ];
}
echo json_encode(['output' => json_encode(['domain' => $domain, 'records' => $out])]);
