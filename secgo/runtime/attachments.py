"""Web attachment storage, lightweight classification, and bounded text extraction."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from ..config.config import PROJECT_ROOT
from .workspace import get_workspace_base

UPLOADS_BASE = PROJECT_ROOT / "runtime" / "uploads"
ORIGINAL_FILENAME = "original.bin"
METADATA_FILENAME = "metadata.json"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MAX_ATTACHMENTS_PER_TASK = 8
MAX_TASK_ATTACHMENT_BYTES = 20 * 1024 * 1024
TEMP_ATTACHMENT_TTL_SECONDS = 2 * 60 * 60
TEXT_READ_LIMIT = 256 * 1024
TEXT_PROMPT_LIMIT = 16 * 1024


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


def extract_limited_text(path: Path) -> Optional[str]:
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
