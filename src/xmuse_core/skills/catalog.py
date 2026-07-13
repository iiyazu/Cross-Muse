from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from yaml.nodes import MappingNode
from yaml.tokens import AliasToken, AnchorToken, TagToken

from xmuse_core.skills.models import RoomSkillActivation, SkillDecision, SkillDescriptor
from xmuse_core.skills.selector import normalize_selection_text, select_skill

MAX_SKILLS = 32
MAX_FILE_BYTES = 24 * 1024
MAX_BODY_BYTES = 16 * 1024
_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
_XMUSE_KEYS = {"roles", "triggers", "not_for", "priority"}


class SkillCatalogError(ValueError):
    def __init__(self, message: str, *, code: str = "room_skill_catalog_invalid"):
        super().__init__(message)
        self.code = code


class SkillCatalogDriftError(SkillCatalogError):
    def __init__(self, message: str):
        super().__init__(message, code="room_skill_catalog_drift")


class _StrictSafeLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _StrictSafeLoader,
    node: MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    if not isinstance(node, MappingNode):
        raise yaml.constructor.ConstructorError(None, None, "expected a mapping", node.start_mark)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        if key_node.value == "<<" or key_node.tag == "tag:yaml.org,2002:merge":
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "merge keys are not allowed",
                key_node.start_mark,
            )
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in result
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key!r}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_StrictSafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


class SkillCatalog:
    def __init__(
        self,
        *,
        root: Path,
        descriptors: tuple[SkillDescriptor, ...],
        catalog_sha256: str,
    ) -> None:
        self._root = root
        self._descriptors = descriptors
        self.catalog_sha256 = catalog_sha256
        self._by_id = {item.skill_id: item for item in descriptors}

    def __repr__(self) -> str:
        return (
            f"SkillCatalog(skills={tuple(self._by_id)!r}, catalog_sha256={self.catalog_sha256!r})"
        )

    @property
    def descriptors(self) -> tuple[SkillDescriptor, ...]:
        return self._descriptors

    @classmethod
    def load_bundled(cls) -> SkillCatalog:
        return cls.load(Path(__file__).parent / "bundled")

    @classmethod
    def load(cls, root: Path) -> SkillCatalog:
        root = Path(root)
        if root.is_symlink():
            raise SkillCatalogError("skill root must not be a symlink")
        try:
            resolved_root = root.resolve(strict=True)
        except OSError as exc:
            raise SkillCatalogError("skill root is not readable") from exc
        if not resolved_root.is_dir():
            raise SkillCatalogError("skill root must be a directory")

        skill_dirs: list[Path] = []
        try:
            entries = sorted(resolved_root.iterdir(), key=lambda path: path.name)
        except OSError as exc:
            raise SkillCatalogError("skill root is not readable") from exc
        for entry in entries:
            if entry.is_symlink():
                raise SkillCatalogError(f"symlink is not allowed in skill root: {entry.name}")
            if entry.is_dir():
                skill_path = entry / "SKILL.md"
                if skill_path.is_symlink():
                    raise SkillCatalogError("SKILL.md must not be a symlink")
                if skill_path.exists():
                    skill_dirs.append(entry)
        if len(skill_dirs) > MAX_SKILLS:
            raise SkillCatalogError(f"catalog exceeds {MAX_SKILLS} skills")

        descriptors = tuple(_load_descriptor(path, root=resolved_root) for path in skill_dirs)
        ids = [item.skill_id for item in descriptors]
        if len(ids) != len(set(ids)):
            raise SkillCatalogError("catalog contains duplicate skill names")
        canonical = json.dumps(
            [
                [item.skill_id, item.version, item.content_sha256]
                for item in sorted(descriptors, key=lambda item: item.skill_id)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        return cls(
            root=resolved_root,
            descriptors=tuple(sorted(descriptors, key=lambda item: item.skill_id)),
            catalog_sha256=_sha256(canonical),
        )

    def select(self, *, participant_role: str, source_text: str) -> SkillDecision:
        return select_skill(
            descriptors=self._descriptors,
            catalog_sha256=self.catalog_sha256,
            participant_role=participant_role,
            source_text=source_text,
        )

    def materialize(self, decision: SkillDecision) -> RoomSkillActivation | None:
        if decision.catalog_sha256 != self.catalog_sha256:
            raise SkillCatalogDriftError("decision catalog digest does not match loaded catalog")
        if decision.decision == "none":
            return None
        if decision.skill_id is None:
            raise SkillCatalogDriftError("selected decision is missing skill identity")
        descriptor = self._by_id.get(decision.skill_id)
        if descriptor is None or (
            decision.skill_version != descriptor.version
            or decision.skill_content_sha256 != descriptor.content_sha256
            or decision.skill_instructions_sha256 != descriptor.instructions_sha256
        ):
            raise SkillCatalogDriftError("selected decision no longer matches catalog descriptor")
        try:
            raw = _read_skill_raw(descriptor._path, root=self._root)
        except SkillCatalogError as exc:
            raise SkillCatalogDriftError("skill file changed after catalog load") from exc
        if _sha256(raw) != descriptor.content_sha256:
            raise SkillCatalogDriftError("skill content changed after catalog load")
        _, body = _split_frontmatter(raw.decode("utf-8"))
        if len(body.encode("utf-8")) > MAX_BODY_BYTES:
            raise SkillCatalogDriftError("skill instructions exceed the materialization bound")
        instructions_sha256 = _sha256(body.encode("utf-8"))
        if instructions_sha256 != descriptor.instructions_sha256:
            raise SkillCatalogDriftError("skill instructions changed after catalog load")
        return RoomSkillActivation(
            skill_id=descriptor.skill_id,
            version=descriptor.version,
            content_sha256=descriptor.content_sha256,
            instructions_sha256=descriptor.instructions_sha256,
            catalog_sha256=self.catalog_sha256,
            selection_reason=decision.selection_reason,
            matched_terms=decision.matched_terms,
            instructions=body,
        )


def _load_descriptor(directory: Path, *, root: Path) -> SkillDescriptor:
    if directory.is_symlink():
        raise SkillCatalogError(f"skill directory must not be a symlink: {directory.name}")
    if not _is_contained(directory, root):
        raise SkillCatalogError("skill directory escapes bundled root")
    if _NAME.fullmatch(directory.name) is None or len(directory.name) > 64:
        raise SkillCatalogError(f"invalid skill directory name: {directory.name}")
    path = directory / "SKILL.md"
    raw, body = _read_skill_file(path, root=root)
    text = raw.decode("utf-8")
    frontmatter, _ = _split_frontmatter(text)
    document = _load_yaml(frontmatter)
    if not isinstance(document, dict):
        raise SkillCatalogError("SKILL.md frontmatter must be a mapping")
    if not all(isinstance(key, str) for key in document):
        raise SkillCatalogError("SKILL.md frontmatter keys must be strings")
    allowed = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
    unknown = sorted(set(document) - allowed)
    if unknown:
        raise SkillCatalogError(f"unknown SKILL.md field: {unknown[0]}")
    name = _bounded_string(document.get("name"), "name", minimum=1, maximum=64)
    if _NAME.fullmatch(name) is None or name != directory.name:
        raise SkillCatalogError("skill name must be valid and equal its directory name")
    description = _bounded_string(
        document.get("description"), "description", minimum=1, maximum=1024
    )
    _validate_optional_string(document, "license", maximum=1024)
    _validate_optional_string(document, "compatibility", maximum=500)
    _validate_optional_string(document, "allowed-tools", maximum=4096)
    metadata = document.get("metadata")
    if not isinstance(metadata, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in metadata.items()
    ):
        raise SkillCatalogError("metadata must be a string-to-string mapping")
    version = _bounded_string(metadata.get("version"), "metadata.version", minimum=1, maximum=32)
    raw_xmuse = _bounded_string(
        metadata.get("xmuse"), "metadata.xmuse", minimum=2, maximum=MAX_FILE_BYTES
    )
    xmuse = _load_xmuse_metadata(raw_xmuse)
    return SkillDescriptor(
        skill_id=name,
        version=version,
        description=description,
        content_sha256=_sha256(raw),
        instructions_sha256=_sha256(body.encode("utf-8")),
        roles=xmuse["roles"],
        triggers=xmuse["triggers"],
        not_for=xmuse["not_for"],
        priority=xmuse["priority"],
        _path=path,
    )


def _read_skill_file(path: Path, *, root: Path) -> tuple[bytes, str]:
    raw = _read_skill_raw(path, root=root)
    text = raw.decode("utf-8")
    _, body = _split_frontmatter(text)
    if len(body.encode("utf-8")) > MAX_BODY_BYTES:
        raise SkillCatalogError(f"skill instructions exceed {MAX_BODY_BYTES} bytes")
    return raw, body


def _read_skill_raw(path: Path, *, root: Path) -> bytes:
    if path.is_symlink():
        raise SkillCatalogError("SKILL.md must not be a symlink")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise SkillCatalogError("SKILL.md is missing or unreadable") from exc
    if not _is_contained(resolved, root) or not resolved.is_file():
        raise SkillCatalogError("SKILL.md must be a file inside the bundled root")
    try:
        with resolved.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError as exc:
        raise SkillCatalogError("SKILL.md is unreadable") from exc
    if len(raw) > MAX_FILE_BYTES:
        raise SkillCatalogError(f"SKILL.md exceeds {MAX_FILE_BYTES} bytes")
    try:
        raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SkillCatalogError("SKILL.md must be strict UTF-8") from exc
    return raw


def _split_frontmatter(text: str) -> tuple[str, str]:
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise SkillCatalogError("SKILL.md must begin with an exact frontmatter delimiter")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing_index is None:
        raise SkillCatalogError("SKILL.md frontmatter is not closed")
    frontmatter = "".join(lines[1:closing_index])
    return frontmatter, "".join(lines[closing_index + 1 :])


def _load_yaml(frontmatter: str) -> Any:
    try:
        for token in yaml.scan(frontmatter):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                raise SkillCatalogError("YAML anchors, aliases, and explicit tags are not allowed")
        return yaml.load(frontmatter, Loader=_StrictSafeLoader)
    except SkillCatalogError:
        raise
    except yaml.YAMLError as exc:
        raise SkillCatalogError("invalid SKILL.md YAML frontmatter") from exc


def _load_xmuse_metadata(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SkillCatalogError("metadata.xmuse must be valid JSON") from exc
    if not isinstance(value, dict) or set(value) != _XMUSE_KEYS:
        raise SkillCatalogError("metadata.xmuse has invalid fields")
    roles = _normalized_string_list(value.get("roles"), "roles", minimum=1, maximum=8)
    triggers = _normalized_string_list(
        value.get("triggers"), "triggers", minimum=1, maximum=16, term=True
    )
    not_for = _normalized_string_list(
        value.get("not_for"), "not_for", minimum=1, maximum=16, term=True
    )
    priority = value.get("priority")
    if type(priority) is not int or not 0 <= priority <= 1000:
        raise SkillCatalogError("metadata.xmuse.priority must be an integer from 0 to 1000")
    return {"roles": roles, "triggers": triggers, "not_for": not_for, "priority": priority}


def _normalized_string_list(
    value: Any,
    field: str,
    *,
    minimum: int,
    maximum: int,
    term: bool = False,
) -> tuple[str, ...]:
    if not isinstance(value, list) or not minimum <= len(value) <= maximum:
        raise SkillCatalogError(f"metadata.xmuse.{field} must contain {minimum}..{maximum} strings")
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise SkillCatalogError(f"metadata.xmuse.{field} entries must be strings")
        result = normalize_selection_text(item)
        lower = 2 if term else 1
        if not lower <= len(result) <= 64:
            raise SkillCatalogError(f"metadata.xmuse.{field} entry has invalid length")
        normalized.append(result)
    if len(set(normalized)) != len(normalized):
        raise SkillCatalogError(f"metadata.xmuse.{field} has duplicate normalized entries")
    return tuple(sorted(normalized))


def _bounded_string(value: Any, field: str, *, minimum: int, maximum: int) -> str:
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise SkillCatalogError(f"{field} must be a string of length {minimum}..{maximum}")
    return value


def _validate_optional_string(document: dict[str, Any], field: str, *, maximum: int) -> None:
    if field not in document:
        return
    _bounded_string(document[field], field, minimum=1, maximum=maximum)


def _is_contained(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _sha256(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"
