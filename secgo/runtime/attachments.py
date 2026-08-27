"""Web attachment storage, lightweight classification, and bounded text extraction."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config.config import PROJECT_ROOT
from .workspace import get_workspace_base

UPLOADS_BASE = PROJECT_ROOT / "runtime" / "uploads"
ORIGINAL_FILENAME = "original.bin"
METADATA_FILENAME = "metadata.json"
ANALYSIS_FILENAME = "analysis.json"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_TASK = 8
MAX_TASK_ATTACHMENT_BYTES = 20 * 1024 * 1024
TEMP_ATTACHMENT_TTL_SECONDS = 2 * 60 * 60
TEXT_READ_LIMIT = 256 * 1024
TEXT_PROMPT_LIMIT = 16 * 1024
ZIP_MAX_SIZE = 100 * 1024 * 1024  # 100MB 解压上限
ZIP_MAX_FILES = 200               # 最多 200 个文件
ZIP_MAX_SINGLE_FILE = 20 * 1024 * 1024  # 单个文件最大 20MB


@dataclass
class AttachmentMetadata:
    attachment_id: str
    original_name: str
    mime_type: str
    detected_kind: str
    size: int
    sha256: str
    created_at: int
    session_id: Optional[str] = None


def _is_within(path: Path, base: Path) -> bool:
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def _safe_child(base: Path, *parts: str) -> Path:
    resolved_base = base.resolve()
    path = resolved_base.joinpath(*parts).resolve()
    if not _is_within(path, resolved_base):
        raise ValueError("Attachment path escapes its storage boundary")
    return path


def _attachment_dir(base: Path, attachment_id: str) -> Path:
    try:
        normalized = str(uuid.UUID(attachment_id))
    except (ValueError, AttributeError, TypeError) as error:
        raise ValueError("Invalid attachment ID") from error
    if normalized != attachment_id:
        raise ValueError("Invalid attachment ID")
    return _safe_child(base, attachment_id)


def _metadata_from_file(path: Path) -> AttachmentMetadata:
    data = json.loads(path.read_text(encoding="utf-8"))
    return AttachmentMetadata(**data)


def _atomic_write(path: Path, data: bytes) -> None:
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp_path.open("xb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        temp_path.replace(path)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_write_metadata(path: Path, metadata: AttachmentMetadata) -> None:
    serialized = json.dumps(asdict(metadata), ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(path, serialized)


def _try_extract_pdf_text(path: Path) -> Optional[str]:
    """尝试用 PyMuPDF 提取 PDF 文本，失败则回退到 pdfminer 或 None。"""
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(str(path))
        parts = []
        for page in doc:
            text = page.get_text()
            if text:
                parts.append(text)
            if sum(len(p) for p in parts) > TEXT_PROMPT_LIMIT:
                parts.append("\n[PDF 内容过长，已截断]")
                break
        doc.close()
        if parts:
            result = "\n".join(parts)
            if len(result) > TEXT_PROMPT_LIMIT:
                result = result[:TEXT_PROMPT_LIMIT] + "\n\n[PDF 文本已截断]"
            return result
    except ImportError:
        pass
    except Exception:
        pass

    # 回退：pdfminer.six
    try:
        from pdfminer.high_level import extract_text
        text = extract_text(str(path))
        if text and text.strip():
            if len(text) > TEXT_PROMPT_LIMIT:
                text = text[:TEXT_PROMPT_LIMIT] + "\n\n[PDF 文本已截断]"
            return text
    except ImportError:
        pass
    except Exception:
        pass

    return None


def _try_extract_zip_content(path: Path) -> Optional[Dict[str, Any]]:
    """安全解压 ZIP 并枚举文件内容（防 Zip Slip + 解压炸弹）。"""
    try:
        result: Dict[str, Any] = {
            "type": "zip_archive",
            "file_count": 0,
            "total_size": 0,
            "files": [],
            "text_files": [],
        }
        total_size = 0
        with zipfile.ZipFile(path, 'r') as zf:
            names = zf.namelist()
            if len(names) > ZIP_MAX_FILES:
                result["truncated"] = True
                names = names[:ZIP_MAX_FILES]

            for name in names:
                info = zf.getinfo(name)
                # Zip Slip 防护
                resolved = Path("/") / name
                if ".." in name or resolved.resolve().name != Path(name).name:
                    continue
                if info.file_size > ZIP_MAX_SINGLE_FILE:
                    result["files"].append({"name": name, "size": info.file_size, "skipped": "too_large"})
                    continue
                total_size += info.file_size
                if total_size > ZIP_MAX_SIZE:
                    result["truncated"] = True
                    break

                entry = {"name": name, "size": info.file_size, "is_dir": info.is_dir()}
                if not info.is_dir():
                    try:
                        data = zf.read(name)
                        # 尝试文本提取
                        text = _decode_text(data[:TEXT_READ_LIMIT])
                        if text and _looks_like_text(data[:TEXT_READ_LIMIT]):
                            entry["text_preview"] = text[:2000]
                            result["text_files"].append({"name": name, "preview": text[:2000]})
                        # 递归检测嵌套 zip
                        if data[:4] == b"PK\x03\x04":
                            entry["nested_zip"] = True
                    except Exception:
                        entry["read_error"] = True
                result["files"].append(entry)

        result["file_count"] = len(result["files"])
        result["total_size"] = total_size
        return result
    except zipfile.BadZipFile:
        return {"type": "zip_archive", "error": "Bad ZIP file"}
    except Exception as e:
        return {"type": "zip_archive", "error": str(e)[:200]}


def _try_parse_structured_text(text: str) -> Optional[Dict[str, Any]]:
    """尝试解析 JSON/YAML/OpenAPI 结构化文本。"""
    stripped = text.strip()
    if not stripped:
        return None

    # JSON 检测
    if stripped.startswith("{") or stripped.startswith("["):
        try:
            parsed = json.loads(stripped)
            result: Dict[str, Any] = {"type": "json", "parsed": True}
            # 检测 OpenAPI/Swagger
            if isinstance(parsed, dict):
                if parsed.get("openapi") or parsed.get("swagger"):
                    result["type"] = "openapi"
                    result["openapi_version"] = parsed.get("openapi") or parsed.get("swagger", "")
                    result["endpoints"] = _extract_openapi_endpoints(parsed)
                    result["title"] = parsed.get("info", {}).get("title", "")
                else:
                    # 结构化摘要
                    result["summary"] = _structured_json_summary(parsed)
            return result
        except (json.JSONDecodeError, ValueError):
            pass

    # YAML 检测（有 yaml 库就用，没有就 fallback 到简单检测）
    try:
        import yaml
        if any(c in stripped[:200] for c in [": ", ":", "\n"]):
            parsed = yaml.safe_load(stripped)
            if isinstance(parsed, dict):
                result = {"type": "yaml", "parsed": True}
                if parsed.get("openapi") or parsed.get("swagger"):
                    result["type"] = "openapi"
                    result["openapi_version"] = parsed.get("openapi") or parsed.get("swagger", "")
                    result["endpoints"] = _extract_openapi_endpoints(parsed)
                    result["title"] = parsed.get("info", {}).get("title", "")
                else:
                    result["summary"] = _structured_json_summary(parsed)
                return result
    except ImportError:
        pass
    except Exception:
        pass

    return None


def _extract_openapi_endpoints(spec: Dict[str, Any]) -> List[Dict[str, str]]:
    """从 OpenAPI/Swagger 规范中提取 endpoints 摘要。"""
    endpoints = []
    paths = spec.get("paths", {})
    if not isinstance(paths, dict):
        return endpoints
    for path, methods in paths.items():
        if not isinstance(methods, dict):
            continue
        for method, detail in methods.items():
            if method.upper() not in ("GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"):
                continue
            info = detail or {}
            params = []
            for param in (info.get("parameters") or []):
                if isinstance(param, dict):
                    params.append(f"{param.get('name', '?')} ({param.get('in', '?')})")
            security = "yes" if info.get("security") else ("yes" if spec.get("security") else "no")
            endpoints.append({
                "path": path,
                "method": method.upper(),
                "summary": (info.get("summary") or info.get("description") or "")[:100],
                "params": ", ".join(params[:5]) or "none",
                "auth": security,
            })
    return endpoints


def _structured_json_summary(data: Any, max_depth: int = 3, _depth: int = 0) -> str:
    """生成结构化 JSON/YAML 的摘要（字段名 + 类型 + 示例值）。"""
    if _depth >= max_depth:
        return "..."
    if isinstance(data, dict):
        parts = []
        for k, v in list(data.items())[:15]:
            if isinstance(v, dict):
                parts.append(f"{k}: ({_structured_json_summary(v, max_depth, _depth + 1)})")
            elif isinstance(v, list):
                lens = f"[{len(v)} items]"
                if v and _depth < max_depth - 1:
                    lens += " e.g. " + _structured_json_summary(v[0], max_depth, _depth + 1)
                parts.append(f"{k}: {lens}")
            elif isinstance(v, str):
                parts.append(f"{k}: '{v[:60]}'")
            else:
                parts.append(f"{k}: {v}")
        if len(data) > 15:
            parts.append(f"... and {len(data) - 15} more fields")
        return "{" + ", ".join(parts) + "}"
    elif isinstance(data, list):
        if not data:
            return "[]"
        return f"[{_structured_json_summary(data[0], max_depth, _depth + 1)}]"
    else:
        return str(data)[:80]


def classify_basic_file(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image"
    if data.startswith(b"\xff\xd8\xff"):
        return "image"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image"
    if data.startswith(b"%PDF-"):
        return "pdf"
    if len(data) >= 4 and data[:2] == b"PK" and data[2:4] in (b"\x03\x04", b"\x05\x06", b"\x07\x08"):
        return "zip"
    if data.startswith(b"SQLite format 3\x00"):
        return "sqlite"
    if data.startswith((b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4", b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d", b"\x0a\x0d\x0d\x0a")):
        return "pcap"
    if data.startswith(b"MZ"):
        return "pe"
    if data.startswith(b"\x7fELF"):
        return "elf"
    if _looks_like_text(data[:TEXT_READ_LIMIT]):
        return "text"
    return "binary"


def _decode_text(data: bytes) -> Optional[str]:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        encodings = ("utf-16", "utf-8", "gb18030")
    elif b"\x00" in data[:512]:
        encodings = ("utf-16", "utf-8", "gb18030")
    else:
        encodings = ("utf-8", "gb18030", "utf-16")
    for encoding in encodings:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return None


def _looks_like_text(data: bytes) -> bool:
    if not data:
        return True
    text = _decode_text(data)
    if text is None or "\x00" in text:
        return False
    controls = sum(1 for char in text if ord(char) < 32 and char not in "\n\r\t\f\b")
    return controls / max(len(text), 1) <= 0.02


def extract_limited_text(path: Path, detected_kind: str = "text") -> Optional[str]:
    """根据文件类型提取文本内容。支持 PDF/ZIP/JSON/YAML/OpenAPI/纯文本。"""
    # PDF 专用解析
    if detected_kind == "pdf":
        return _try_extract_pdf_text(path)

    # ZIP 专用解析
    if detected_kind == "zip":
        zip_content = _try_extract_zip_content(path)
        if zip_content:
            # 格式化输出
            lines = [f"[ZIP 存档] 共 {zip_content.get('file_count', 0)} 个文件"]
            if zip_content.get("total_size"):
                lines.append(f"总大小: {zip_content['total_size'] / 1024:.1f} KB")
            for f in zip_content.get("files", []):
                if f.get("is_dir"):
                    lines.append(f"  📁 {f['name']}/")
                elif f.get("skipped"):
                    lines.append(f"  📄 {f['name']} ({f['size']} bytes, 跳过: {f['skipped']})")
                else:
                    lines.append(f"  📄 {f['name']} ({f['size']} bytes)")
            # 文本文件预览
            text_files = zip_content.get("text_files", [])
            if text_files:
                lines.append(f"\n[文本文件预览 ({len(text_files)} 个)]")
                for tf in text_files[:5]:
                    lines.append(f"\n--- {tf['name']} ---")
                    lines.append(tf['preview'][:2000])
            if zip_content.get("error"):
                lines.append(f"\n[错误] {zip_content['error']}")
            return "\n".join(lines)
        return f"[ZIP 解析失败]"

    # 通用文本读取
    with path.open("rb") as source:
        size = path.stat().st_size
        if size <= TEXT_READ_LIMIT:
            data = source.read(TEXT_READ_LIMIT)
            split_marker = b""
        else:
            half = TEXT_READ_LIMIT // 2
            head = source.read(half)
            source.seek(max(size - half, 0))
            tail = source.read(half)
            data = head + tail
            split_marker = b"\n\n[attachment bytes omitted]\n\n"
    if not _looks_like_text(data):
        return None
    if split_marker:
        head_text = _decode_text(data[:TEXT_READ_LIMIT // 2])
        tail_text = _decode_text(data[TEXT_READ_LIMIT // 2:])
        text = None if head_text is None or tail_text is None else f"{head_text}\n\n[附件中间内容已省略]\n\n{tail_text}"
    else:
        text = _decode_text(data)
    if text is None:
        return None

    # 结构化格式检测（JSON/YAML/OpenAPI）
    structured = _try_parse_structured_text(text)
    if structured:
        stype = structured.get("type", "structured")
        if stype == "openapi":
            endpoints = structured.get("endpoints", [])
            lines = [
                f"[OpenAPI/Swagger 规范] 版本: {structured.get('openapi_version', 'N/A')}",
                f"标题: {structured.get('title', 'N/A')}",
                f"\n端点 ({len(endpoints)} 个):",
            ]
            for ep in endpoints[:30]:
                lines.append(f"  {ep['method']:7s} {ep['path']}  {ep['summary']}")
            if len(endpoints) > 30:
                lines.append(f"  ... 还有 {len(endpoints) - 30} 个端点")
            return "\n".join(lines)
        elif stype == "json" or stype == "yaml":
            summary = structured.get("summary", "")
            return f"[{stype.upper()} 结构化数据]\n{summary}"
        else:
            return f"[{stype}]"

    if len(text) > TEXT_PROMPT_LIMIT:
        half = TEXT_PROMPT_LIMIT // 2
        text = f"{text[:half]}\n\n[附件文本已截断]\n\n{text[-half:]}"
    return text


def save_temporary_attachment(original_name: str, mime_type: str, data: bytes) -> AttachmentMetadata:
    if len(data) > MAX_ATTACHMENT_BYTES:
        raise ValueError("单文件不能超过 10MB")
    attachment_id = str(uuid.uuid4())
    uploads_base = UPLOADS_BASE.resolve()
    uploads_base.mkdir(parents=True, exist_ok=True)
    final_dir = _attachment_dir(uploads_base, attachment_id)
    staging_dir = _safe_child(uploads_base, f".{attachment_id}.tmp")
    metadata = AttachmentMetadata(
        attachment_id=attachment_id,
        original_name=original_name,
        mime_type=mime_type or "application/octet-stream",
        detected_kind=classify_basic_file(data),
        size=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        created_at=int(time.time()),
    )
    try:
        staging_dir.mkdir()
        _atomic_write(_safe_child(staging_dir, ORIGINAL_FILENAME), data)
        _atomic_write_metadata(_safe_child(staging_dir, METADATA_FILENAME), metadata)
        staging_dir.replace(final_dir)
        return metadata
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(final_dir, ignore_errors=True)
        raise


def get_temporary_attachment(attachment_id: str) -> Optional[AttachmentMetadata]:
    attachment_dir = _attachment_dir(UPLOADS_BASE.resolve(), attachment_id)
    metadata_path = _safe_child(attachment_dir, METADATA_FILENAME)
    original_path = _safe_child(attachment_dir, ORIGINAL_FILENAME)
    if not metadata_path.is_file() or not original_path.is_file():
        return None
    return _metadata_from_file(metadata_path)


def move_attachment_to_session(attachment_id: str, session_id: str) -> AttachmentMetadata:
    source_dir = _attachment_dir(UPLOADS_BASE.resolve(), attachment_id)
    metadata = get_temporary_attachment(attachment_id)
    if metadata is None:
        raise FileNotFoundError("Attachment not found")
    workspace_base = get_workspace_base().resolve()
    session_base = _safe_child(workspace_base, session_id)
    attachments_base = _safe_child(session_base, "attachments")
    attachments_base.mkdir(parents=True, exist_ok=True)
    destination_dir = _attachment_dir(attachments_base, attachment_id)
    if destination_dir.exists():
        raise FileExistsError("Attachment already belongs to this session")
    staging_dir = _safe_child(attachments_base, f".{attachment_id}.tmp")
    metadata.session_id = session_id
    try:
        staging_dir.mkdir()
        shutil.copyfile(_safe_child(source_dir, ORIGINAL_FILENAME), _safe_child(staging_dir, ORIGINAL_FILENAME))
        _atomic_write_metadata(_safe_child(staging_dir, METADATA_FILENAME), metadata)
        staging_dir.replace(destination_dir)
        shutil.rmtree(source_dir)
        return metadata
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise


def get_session_attachment(session_id: str, attachment_id: str) -> Optional[AttachmentMetadata]:
    session_base = _safe_child(get_workspace_base().resolve(), session_id)
    attachment_dir = _attachment_dir(_safe_child(session_base, "attachments"), attachment_id)
    metadata_path = _safe_child(attachment_dir, METADATA_FILENAME)
    original_path = _safe_child(attachment_dir, ORIGINAL_FILENAME)
    if not metadata_path.is_file() or not original_path.is_file():
        return None
    metadata = _metadata_from_file(metadata_path)
    return metadata if metadata.session_id == session_id else None


def get_session_attachment_path(session_id: str, attachment_id: str) -> Path:
    metadata = get_session_attachment(session_id, attachment_id)
    if metadata is None:
        raise FileNotFoundError("Attachment not found")
    session_base = _safe_child(get_workspace_base().resolve(), session_id)
    return _safe_child(_attachment_dir(_safe_child(session_base, "attachments"), attachment_id), ORIGINAL_FILENAME)


def save_attachment_analysis(session_id: str, attachment_id: str, analysis: Dict[str, Any]) -> None:
    """把附件预处理结果（如图片视觉分析）持久化为 attachment 目录下的 analysis.json。

    分析结果是派生的、可复用的：后续 Turn 重放时直接读取，避免重复调用视觉模型。
    """
    session_base = _safe_child(get_workspace_base().resolve(), session_id)
    attachment_dir = _attachment_dir(_safe_child(session_base, "attachments"), attachment_id)
    if not attachment_dir.is_dir():
        raise FileNotFoundError("Attachment not found")
    serialized = json.dumps(analysis, ensure_ascii=False, indent=2).encode("utf-8")
    _atomic_write(_safe_child(attachment_dir, ANALYSIS_FILENAME), serialized)


def get_attachment_analysis(session_id: str, attachment_id: str) -> Optional[Dict[str, Any]]:
    """读取已缓存的附件预处理结果；不存在或损坏时返回 None。"""
    metadata = get_session_attachment(session_id, attachment_id)
    if metadata is None:
        return None
    session_base = _safe_child(get_workspace_base().resolve(), session_id)
    attachment_dir = _attachment_dir(_safe_child(session_base, "attachments"), attachment_id)
    analysis_path = _safe_child(attachment_dir, ANALYSIS_FILENAME)
    if not analysis_path.is_file():
        return None
    try:
        data = json.loads(analysis_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def delete_temporary_attachment(attachment_id: str) -> None:
    shutil.rmtree(_attachment_dir(UPLOADS_BASE.resolve(), attachment_id), ignore_errors=True)


def cleanup_expired_temporary_attachments(now: Optional[int] = None) -> int:
    uploads_base = UPLOADS_BASE.resolve()
    if not uploads_base.exists():
        return 0
    cutoff = (now or int(time.time())) - TEMP_ATTACHMENT_TTL_SECONDS
    removed = 0
    for child in uploads_base.iterdir():
        if not child.is_dir():
            continue
        try:
            if child.name.startswith("."):
                if int(child.stat().st_mtime) < cutoff:
                    shutil.rmtree(child, ignore_errors=True)
                    removed += 1
                continue
            metadata = get_temporary_attachment(child.name)
            if metadata and metadata.created_at < cutoff:
                delete_temporary_attachment(child.name)
                removed += 1
        except (OSError, ValueError, json.JSONDecodeError, TypeError):
            continue
    return removed