"""附件展示形态统一回归测试。

核心原则：用户消息只展示「用户实际发送的文字 + 附件本身 + 简短状态」，
系统对附件的分析结果（vision summary / 提取正文 / ZIP 列表 / OpenAPI 端点 /
JSON/YAML 解析摘要 / security findings）绝不进入展示 payload——
它们只进入 Planner 上下文（build_attachment_context）与执行轨迹事件。
"""

import unittest
from types import SimpleNamespace

from secgo.runtime.attachment_context import attachment_presentation


def _meta(kind):
    return SimpleNamespace(
        attachment_id="att-1",
        original_name="sample.bin",
        mime_type="application/octet-stream",
        detected_kind=kind,
        size=1234,
    )


# 全部已识别类型：展示层对每一种都只允许同一套字段
KINDS = ["image", "pdf", "zip", "text", "log", "code", "json", "yaml",
         "openapi", "pcap", "sqlite", "pe", "elf", "binary"]

ALLOWED_KEYS = {"id", "filename", "mimeType", "kind", "size", "analysis"}
ALLOWED_ANALYSIS_KEYS = {"status", "error"}
FORBIDDEN_MARKERS = (
    "summary", "securityFindings", "security_findings", "sceneTags", "scene_tags",
    "extracted", "endpoints", "sha256", "path",
)


class AttachmentPresentationTests(unittest.TestCase):
    def test_all_kinds_expose_only_attachment_itself_plus_short_status(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                payload = attachment_presentation(_meta(kind))
                self.assertEqual(set(payload.keys()), ALLOWED_KEYS - {"analysis"})

    def test_analysis_payload_carries_status_and_error_only(self):
        analysis = {
            "status": "analyzed",
            "summary": "登录页面出现数据库错误回显",
            "security_findings": ["存在数据库错误信息泄露"],
            "scene_tags": ["web"],
            "confidence": "high",
            "extracted_text": "PDF 正文机密内容",
            "zip_entries": ["secret.txt"],
            "openapi_endpoints": ["/admin"],
            "error": None,
        }
        payload = attachment_presentation(_meta("image"), analysis)
        self.assertEqual(set(payload.keys()), ALLOWED_KEYS)
        self.assertEqual(set(payload["analysis"].keys()), ALLOWED_ANALYSIS_KEYS)
        self.assertEqual(payload["analysis"]["status"], "analyzed")
        self.assertIsNone(payload["analysis"]["error"])
        # 任何分析内容不得出现在序列化后的展示 payload 中
        import json
        dumped = json.dumps(payload, ensure_ascii=False)
        for marker in FORBIDDEN_MARKERS:
            self.assertNotIn(marker, dumped)

    def test_no_analysis_argument_keeps_payload_clean(self):
        payload = attachment_presentation(_meta("pdf"))
        self.assertNotIn("analysis", payload)


if __name__ == "__main__":
    unittest.main()
