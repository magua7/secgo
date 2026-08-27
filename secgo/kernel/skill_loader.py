"""技能库加载器（P0-2 核心）。

- 手写最小 YAML frontmatter 解析器（不引第三方库），支持 `description: >-`
  折行、引号值、普通标量；解析失败跳过该技能并计数。
- 读取 skill/policy.json 分组策略；enabled=false 的技能不进入默认列表，
  但仍可被显式读取。
- 技能根目录支持环境变量 SECGO_SKILLS_DIR 覆盖，默认项目 skill/。
- 单文件 <=200KB、总数 <=512，越界跳过并打印诊断。
- SKILL.md 正文按不可信文本处理：只做展示/注入知识，不自动执行其中命令。
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]

MAX_SKILLS = 512
MAX_FILE_BYTES = 200 * 1024
READ_TRUNCATE = 8000
SEARCH_LIMIT = 10

_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9._\-]+$")
_FIELD_RE = re.compile(r"^([A-Za-z0-9_\-]+):(.*)$")


# ── 最小 YAML frontmatter 解析 ───────────────────────────


def _parse_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] in ('"', "'") and value[-1] == value[0]:
        inner = value[1:-1]
        if value[0] == '"':
            inner = (
                inner.replace(r"\"", '"')
                .replace(r"\n", "\n")
                .replace(r"\t", "\t")
                .replace(r"\\", "\\")
            )
        return inner
    return value


def _parse_frontmatter_fields(fm_text: str) -> Dict[str, str]:
    """解析 frontmatter 内部的顶层 key: value 行。

    支持：
    - 普通标量 `name: foo`
    - 引号值 `description: 'x y'` / `"x y"`
    - 折行标量 `description: >-`（后续缩进行合并，>- 去尾部换行）
    - 字面量块 `key: |` / `|-`
    """
    lines = fm_text.split("\n")
    fields: Dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        match = _FIELD_RE.match(line)
        if match is None:
            i += 1
            continue
        key = match.group(1)
        rest = match.group(2).strip()

        if rest in (">-", ">", "|", "|-"):
            i += 1
            buf: List[str] = []
            while i < len(lines):
                cur = lines[i]
                if cur.strip() == "":
                    buf.append("")
                    i += 1
                    continue
                if cur.startswith((" ", "\t")):
                    buf.append(cur.strip())
                    i += 1
                else:
                    break
            value = " ".join(buf) if rest.startswith(">") else "\n".join(buf)
            if rest in (">-", "|-"):
                value = value.rstrip()
            fields[key] = value
            continue

        if rest == "":
            # 嵌套映射：仅收集缩进行（description 场景极少用，容错处理）
            i += 1
            buf = []
            while i < len(lines) and (lines[i].strip() == "" or lines[i].startswith((" ", "\t"))):
                if lines[i].strip():
                    buf.append(lines[i].strip())
                i += 1
            fields[key] = "\n".join(buf)
            continue

        fields[key] = _parse_scalar(rest)
        i += 1
    return fields


def _parse_frontmatter(text: str) -> tuple[Dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    match = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(\r?\n|$)", text, re.DOTALL)
    if match is None:
        return {}, text
    fields = _parse_frontmatter_fields(match.group(1))
    return fields, text[match.end():]


# ── policy.json 分组 ─────────────────────────────────────


def _load_policy() -> Dict[str, Dict[str, Any]]:
    """返回 {skill_name: {group, enabled, risk_class, task_types, role}}。"""
    result: Dict[str, Dict[str, Any]] = {}
    policy_path = _skills_dir() / "policy.json"
    if not policy_path.is_file():
        return result
    try:
        import json

        policy = json.loads(policy_path.read_text(encoding="utf-8"))
    except Exception:
        return result
    for group in policy.get("groups") or []:
        group_id = group.get("id", "ungrouped")
        enabled = group.get("enabled", True)
        info = {
            "group": group_id,
            "enabled": enabled,
            "risk_class": group.get("risk_class", ""),
            "task_types": list(group.get("task_types") or []),
            "role": group.get("role", ""),
        }
        for skill in group.get("skills") or []:
            result[skill] = dict(info)
    return result


# ── 技能根目录 ───────────────────────────────────────────


def _skills_dir() -> Path:
    env_dir = os.environ.get("SECGO_SKILLS_DIR")
    if env_dir:
        return Path(env_dir)
    return PROJECT_ROOT / "skill"


# ── 技能库 ───────────────────────────────────────────────


@dataclass(frozen=True)
class SkillMeta:
    name: str
    description: str
    enabled: bool
    group: str
    task_types: List[str] = field(default_factory=list)
    role: str = ""
    risk_class: str = ""


class SkillLibrary:
    def __init__(self) -> None:
        self._skills: Dict[str, Dict[str, Any]] = {}
        self._meta: Dict[str, SkillMeta] = {}
        self._policy: Dict[str, Dict[str, Any]] = {}
        self._loaded = False
        self._skipped = 0
        self._truncated = 0

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        root = _skills_dir()
        if not root.is_dir():
            print(f"[skill] 技能目录不存在，跳过加载: {root}")
            return

        self._policy = _load_policy()

        count = 0
        for subdir in sorted(root.iterdir()):
            if not subdir.is_dir():
                continue
            if count >= MAX_SKILLS:
                print(f"[skill] 技能数量超过上限 {MAX_SKILLS}，已停止加载")
                break
            skill_md = subdir / "SKILL.md"
            if not skill_md.is_file():
                continue
            try:
                size = skill_md.stat().st_size
            except OSError:
                continue
            if size > MAX_FILE_BYTES:
                self._skipped += 1
                print(f"[skill] 跳过 {subdir.name}: 文件超过 {MAX_FILE_BYTES} 字节上限")
                continue
            try:
                text = skill_md.read_text(encoding="utf-8", errors="replace")
            except OSError as err:
                self._skipped += 1
                print(f"[skill] 跳过 {subdir.name}: 读取失败 {err}")
                continue

            fields, _body = _parse_frontmatter(text)
            name = fields.get("name") or subdir.name
            description = fields.get("description") or ""
            if not name or not description or not _SKILL_NAME_RE.match(name):
                self._skipped += 1
                print(f"[skill] 跳过 {subdir.name}: frontmatter 缺少 name/description")
                continue

            policy_info = self._policy.get(name, {})
            self._skills[name] = {
                "name": name,
                "description": description,
                "path": str(skill_md),
                "file_size": size,
            }
            self._meta[name] = SkillMeta(
                name=name,
                description=description,
                enabled=bool(policy_info.get("enabled", True)),
                group=str(policy_info.get("group", "ungrouped")),
                task_types=list(policy_info.get("task_types") or []),
                role=str(policy_info.get("role", "")),
                risk_class=str(policy_info.get("risk_class", "")),
            )
            count += 1

        if self._skipped > 0:
            print(f"[skill] 已加载 {count} 个技能，跳过 {self._skipped} 个解析失败的技能")
        else:
            print(f"[skill] 已加载 {count} 个技能（目录: {root}）")

    def list_skills(self) -> List[Dict[str, Any]]:
        self._load()
        result: List[Dict[str, Any]] = []
        for name in sorted(self._meta):
            meta = self._meta[name]
            if not meta.enabled:
                continue
            result.append({
                "name": meta.name,
                "description": meta.description,
                "enabled": meta.enabled,
                "group": meta.group,
            })
        return result

    def read_skill(self, name: str) -> Optional[str]:
        """按需读取技能文件正文（不常驻内存），截断上限 8k 字符。"""
        self._load()
        skill = self._skills.get(name)
        if skill is None:
            return None
        try:
            text = Path(skill["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        _, body = _parse_frontmatter(text)
        if len(body) > READ_TRUNCATE:
            self._truncated += 1
            return body[:READ_TRUNCATE] + f"\n\n[... 内容过长，已截断至 {READ_TRUNCATE} 字符 ...]"
        return body

    def get_meta(self, name: str) -> Optional[SkillMeta]:
        self._load()
        return self._meta.get(name)

    def route_skills(self, task_types: List[str], role: Optional[str] = None,
                     risk_class: Optional[str] = None, limit: int = SEARCH_LIMIT) -> List[Dict[str, Any]]:
        """基于任务类型/角色/风险等级的安全策略感知技能路由。

        优先匹配 task_types，再按 role 过滤，再按 risk_class 过滤。
        返回按匹配度排序的技能列表。
        """
        self._load()
        task_type_set = {t.lower() for t in (task_types or [])}
        role_filter = role.lower() if role else None
        risk_filter = risk_class.lower() if risk_class else None

        scored: List[tuple] = []
        for name, meta in self._meta.items():
            if not meta.enabled:
                continue
            score = 0
            meta_types = {t.lower() for t in meta.task_types}
            # 任务类型匹配度（最高权重）
            if not task_type_set:
                score += 1  # 未指定任务类型时全部候选
            else:
                if task_type_set & meta_types:
                    score += 10
                elif not meta_types:
                    score += 1  # 未标注类型的技能作为兜底
            # 角色匹配
            if role_filter:
                if meta.role.lower() == role_filter:
                    score += 5
                elif meta.role == "router" and role_filter == "orchestrator":
                    score += 3  # router 可被 orchestrator 使用
            # 风险等级匹配
            if risk_filter:
                if meta.risk_class.lower() == risk_filter:
                    score += 3
                elif meta.risk_class == "lab_only" and risk_filter == "active":
                    score += 1
            if score > 0:
                scored.append((score, name, {
                    "name": meta.name,
                    "description": meta.description,
                    "enabled": meta.enabled,
                    "group": meta.group,
                    "task_types": list(meta.task_types),
                    "role": meta.role,
                    "risk_class": meta.risk_class,
                }))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [item[2] for item in scored[:limit]]

    def search_skills(self, keyword: str, limit: int = SEARCH_LIMIT) -> List[Dict[str, Any]]:
        self._load()
        kw = keyword.strip().lower()
        if not kw:
            return []
        scored: List[tuple[int, str, Dict[str, Any]]] = []
        for name in sorted(self._skills):
            meta = self._meta.get(name)
            if meta is None:
                continue
            name_l = name.lower()
            desc_l = meta.description.lower()
            score = 0
            if kw in name_l:
                score += 10
            elif kw in desc_l:
                score += 5
            for part in kw.split():
                if part and part in name_l:
                    score += 3
                elif part and part in desc_l:
                    score += 1
            if score > 0:
                scored.append((-score, name, {
                    "name": meta.name,
                    "description": meta.description,
                    "enabled": meta.enabled,
                    "group": meta.group,
                }))
        scored.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in scored[:limit]]

    def skill_exists(self, name: str) -> bool:
        self._load()
        return name in self._skills

    def stats(self) -> Dict[str, Any]:
        self._load()
        return {
            "total": len(self._skills),
            "enabled": sum(1 for m in self._meta.values() if m.enabled),
            "skipped": self._skipped,
        }


skill_library = SkillLibrary()


def list_skills() -> List[Dict[str, Any]]:
    return skill_library.list_skills()


def read_skill(name: str) -> Optional[str]:
    return skill_library.read_skill(name)


def search_skills(keyword: str, limit: int = SEARCH_LIMIT) -> List[Dict[str, Any]]:
    return skill_library.search_skills(keyword, limit)


def route_skills(task_types: List[str], role: Optional[str] = None,
                 risk_class: Optional[str] = None, limit: int = SEARCH_LIMIT) -> List[Dict[str, Any]]:
    return skill_library.route_skills(task_types, role, risk_class, limit)


def skill_exists(name: str) -> bool:
    return skill_library.skill_exists(name)