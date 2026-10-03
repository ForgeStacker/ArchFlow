"""Immutable icon registry models, deterministic search, and verification."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
import unicodedata

from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REGISTRY_PATH = PROJECT_ROOT / "assets" / "icons" / "registry.json"
SVG_NAMESPACE = "http://www.w3.org/2000/svg"
_FORBIDDEN_ELEMENTS = frozenset(
    {
        "script",
        "foreignObject",
        "iframe",
        "object",
        "embed",
        "audio",
        "video",
        "animate",
        "animateMotion",
        "animateTransform",
        "set",
    }
)
_SAFE_DATA_IMAGE_PREFIXES = (
    "data:image/png;",
    "data:image/jpeg;",
    "data:image/gif;",
    "data:image/webp;",
)
_EXTERNAL_SCHEMES = ("http:", "https:", "file:", "ftp:", "//")
_URL_RE = re.compile(r"url\s*\(\s*(['\"]?)(.*?)\1\s*\)", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")


class IconRegistryError(Exception):
    """Base exception for icon registry failures."""


class RegistryFormatError(IconRegistryError):
    """Raised when registry JSON is malformed or internally inconsistent."""


class SvgSafetyError(IconRegistryError):
    """Raised when an SVG is malformed or contains unsafe content."""


class RegistryVerificationError(IconRegistryError):
    """Raised when strict registry verification fails."""

    def __init__(self, report: "VerificationReport") -> None:
        self.report = report
        super().__init__("icon registry verification failed: " + "; ".join(report.errors))


def normalize_name(value: str) -> str:
    """Normalize a human icon name for deterministic exact matching."""

    text = unicodedata.normalize("NFKD", value).casefold()
    text = "".join(character for character in text if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", text))


def _path_is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _safe_href(value: str) -> bool:
    stripped = value.strip().casefold()
    return (
        not stripped
        or stripped.startswith("#")
        or stripped.startswith(_SAFE_DATA_IMAGE_PREFIXES)
    )


def validate_svg_bytes(data: bytes, *, source: str = "<memory>") -> etree._Element:
    """Parse an SVG without entity/network access and reject active or external content."""

    lowered = data.lower()
    if b"<!doctype" in lowered or b"<!entity" in lowered:
        raise SvgSafetyError(f"{source}: DTD/entity declarations are forbidden")
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        remove_comments=False,
        recover=False,
        huge_tree=False,
    )
    try:
        root = etree.fromstring(data, parser=parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        raise SvgSafetyError(f"{source}: invalid XML: {exc}") from exc
    if not isinstance(root.tag, str) or etree.QName(root).localname != "svg":
        raise SvgSafetyError(f"{source}: root element must be svg")
    for processing_instruction in root.xpath("//processing-instruction()"):
        raise SvgSafetyError(f"{source}: processing instructions are forbidden")
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        local_name = etree.QName(element).localname
        if local_name in _FORBIDDEN_ELEMENTS:
            raise SvgSafetyError(f"{source}: forbidden <{local_name}> element")
        for attribute_name, attribute_value in element.attrib.items():
            attribute_local_name = etree.QName(attribute_name).localname.casefold()
            value = attribute_value.strip()
            lowered_value = value.casefold()
            if attribute_local_name.startswith("on"):
                raise SvgSafetyError(f"{source}: event handler attribute {attribute_local_name} is forbidden")
            if attribute_local_name in {"href", "src"} and not _safe_href(value):
                raise SvgSafetyError(f"{source}: external reference {value!r} is forbidden")
            if "javascript:" in lowered_value or "vbscript:" in lowered_value:
                raise SvgSafetyError(f"{source}: active URI is forbidden")
            for match in _URL_RE.finditer(value):
                reference = match.group(2).strip().casefold()
                if reference and not reference.startswith("#") and not reference.startswith(_SAFE_DATA_IMAGE_PREFIXES):
                    raise SvgSafetyError(f"{source}: external CSS reference {reference!r} is forbidden")
        if local_name == "style" and element.text:
            css = element.text.casefold()
            if "@import" in css or "expression(" in css or "javascript:" in css:
                raise SvgSafetyError(f"{source}: unsafe CSS is forbidden")
            for match in _URL_RE.finditer(element.text):
                reference = match.group(2).strip().casefold()
                if reference and not reference.startswith("#") and not reference.startswith(_SAFE_DATA_IMAGE_PREFIXES):
                    raise SvgSafetyError(f"{source}: external CSS reference {reference!r} is forbidden")
    return root


def normalize_svg_bytes(data: bytes, *, source: str = "<memory>") -> bytes:
    """Return deterministic canonical SVG XML without changing artwork geometry or color."""

    root = validate_svg_bytes(data, source=source)
    canonical = etree.tostring(root, method="c14n", with_comments=False)
    return b'<?xml version="1.0" encoding="UTF-8"?>\n' + canonical + b"\n"


def _dimension_value(value: str | None) -> float | None:
    if value is None:
        return None
    match = _NUMBER_RE.match(value.strip())
    if not match:
        return None
    number = float(match.group(0))
    return number if math.isfinite(number) and number >= 0 else None


def svg_geometry(root: etree._Element) -> tuple[float | None, float | None, str | None]:
    """Extract numeric width/height and viewBox, deriving dimensions from viewBox if needed."""

    width = _dimension_value(root.get("width"))
    height = _dimension_value(root.get("height"))
    view_box = root.get("viewBox")
    if view_box:
        pieces = re.split(r"[\s,]+", view_box.strip())
        if len(pieces) == 4:
            try:
                values = [float(piece) for piece in pieces]
            except ValueError:
                values = []
            if len(values) == 4 and all(math.isfinite(value) for value in values):
                width = width if width is not None else values[2]
                height = height if height is not None else values[3]
            else:
                raise SvgSafetyError("invalid viewBox")
        else:
            raise SvgSafetyError("invalid viewBox")
    if width is None or height is None or width <= 0 or height <= 0:
        raise SvgSafetyError("SVG must provide positive dimensions or a valid viewBox")
    return width, height, view_box


@dataclass(frozen=True, slots=True)
class IconEntry:
    """One canonical, locally stored official SVG icon."""

    id: str
    provider: str
    kind: str
    category: str
    slug: str
    display_name: str
    aliases: tuple[str, ...]
    path: str
    source_paths: tuple[str, ...]
    width: float
    height: float
    view_box: str | None
    checksum: str
    deprecated: bool = False
    provenance: Mapping[str, Any] = field(default_factory=dict, compare=False, hash=False)

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IconEntry":
        dimensions = value.get("dimensions", {})
        return cls(
            id=str(value["id"]),
            provider=str(value["provider"]).casefold(),
            kind=str(value["kind"]),
            category=str(value["category"]),
            slug=str(value["slug"]),
            display_name=str(value["display_name"]),
            aliases=tuple(str(alias) for alias in value.get("aliases", ())),
            path=str(value["path"]),
            source_paths=tuple(str(path) for path in value.get("source_paths", ())),
            width=float(dimensions["width"]),
            height=float(dimensions["height"]),
            view_box=value.get("viewBox"),
            checksum=str(value["checksum"]),
            deprecated=bool(value.get("deprecated", False)),
            provenance=dict(value.get("provenance", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "aliases": list(self.aliases),
            "category": self.category,
            "checksum": self.checksum,
            "deprecated": self.deprecated,
            "dimensions": {"height": self.height, "width": self.width},
            "display_name": self.display_name,
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "provenance": dict(self.provenance),
            "provider": self.provider,
            "slug": self.slug,
            "source_paths": list(self.source_paths),
            "viewBox": self.view_box,
        }


@dataclass(frozen=True, slots=True)
class VerificationReport:
    """Deterministically ordered registry verification result."""

    checked: int
    errors: tuple[str, ...]
    counts: Mapping[str, Mapping[str, int]]
    ambiguous_aliases: Mapping[str, tuple[str, ...]]

    @property
    def valid(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise RegistryVerificationError(self)


class IconRegistry:
    """Immutable registry with stable indexes and deterministic search."""

    def __init__(
        self,
        entries: Iterable[IconEntry],
        *,
        assets_root: Path,
        schema_version: int = 1,
        providers: Mapping[str, Any] | None = None,
        registry_path: Path | None = None,
    ) -> None:
        ordered = tuple(sorted(entries, key=lambda entry: entry.id))
        by_id: dict[str, IconEntry] = {}
        for entry in ordered:
            if entry.id in by_id:
                raise RegistryFormatError(f"duplicate icon id: {entry.id}")
            if entry.provider not in {"aws", "azure", "gcp"}:
                raise RegistryFormatError(f"unsupported icon provider: {entry.provider}")
            if entry.kind not in {"service", "resource", "group", "category"}:
                raise RegistryFormatError(f"unsupported icon kind: {entry.kind}")
            if not entry.display_name or not entry.source_paths:
                raise RegistryFormatError(f"icon metadata is incomplete: {entry.id}")
            if not re.fullmatch(r"[0-9a-f]{64}", entry.checksum):
                raise RegistryFormatError(f"invalid checksum for {entry.id}")
            if not math.isfinite(entry.width) or not math.isfinite(entry.height) or entry.width <= 0 or entry.height <= 0:
                raise RegistryFormatError(f"invalid dimensions for {entry.id}")
            if len(entry.aliases) != len(set(entry.aliases)):
                raise RegistryFormatError(f"duplicate aliases for {entry.id}")
            expected_prefix = f"{entry.provider}:{entry.kind}:{entry.category}:"
            if not entry.id.startswith(expected_prefix) or entry.id != f"{expected_prefix}{entry.slug}":
                raise RegistryFormatError(f"icon id does not match fields: {entry.id}")
            expected_path = f"{entry.provider}/{entry.kind}/{entry.category}/{entry.slug}.svg"
            if entry.path != expected_path:
                raise RegistryFormatError(f"icon path does not match fields: {entry.id}")
            by_id[entry.id] = entry
        self.entries = ordered
        self.assets_root = assets_root.resolve()
        self.schema_version = schema_version
        self.providers = dict(providers or {})
        self.registry_path = registry_path
        self._by_id = by_id
        self._alias_index = self._build_name_index(include_display=False)
        self._display_index = self._build_name_index(include_display=True, aliases=False)

    def _build_name_index(
        self, *, include_display: bool, aliases: bool = True
    ) -> dict[tuple[str, str], tuple[IconEntry, ...]]:
        index: dict[tuple[str, str], list[IconEntry]] = {}
        for entry in self.entries:
            names: Sequence[str]
            if include_display:
                names = (entry.display_name,)
            elif aliases:
                names = entry.aliases
            else:
                names = ()
            for name in names:
                normalized = normalize_name(name)
                if normalized:
                    index.setdefault((entry.provider, normalized), []).append(entry)
        return {
            key: tuple(sorted({entry.id: entry for entry in values}.values(), key=lambda entry: entry.id))
            for key, values in index.items()
        }

    @classmethod
    def load(cls, path: str | Path = DEFAULT_REGISTRY_PATH, *, assets_root: str | Path | None = None) -> "IconRegistry":
        registry_path = Path(path).resolve()
        try:
            data = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RegistryFormatError(f"unable to load registry {registry_path}: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise RegistryFormatError("registry schema_version must be 1")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list):
            raise RegistryFormatError("registry entries must be an array")
        try:
            entries = [IconEntry.from_dict(entry) for entry in raw_entries]
        except (KeyError, TypeError, ValueError) as exc:
            raise RegistryFormatError(f"invalid registry entry: {exc}") from exc
        root = Path(assets_root).resolve() if assets_root else registry_path.parent
        return cls(
            entries,
            assets_root=root,
            schema_version=1,
            providers=data.get("providers", {}),
            registry_path=registry_path,
        )

    def get(self, icon_id: str) -> IconEntry | None:
        return self._by_id.get(icon_id)

    def require(self, icon_id: str) -> IconEntry:
        try:
            return self._by_id[icon_id]
        except KeyError as exc:
            raise RegistryFormatError(f"unknown icon id: {icon_id}") from exc

    def alias_candidates(self, name: str, provider: str | None = None) -> tuple[IconEntry, ...]:
        return self._name_candidates(self._alias_index, name, provider)

    def display_candidates(self, name: str, provider: str | None = None) -> tuple[IconEntry, ...]:
        return self._name_candidates(self._display_index, name, provider)

    @staticmethod
    def _name_candidates(
        index: Mapping[tuple[str, str], tuple[IconEntry, ...]], name: str, provider: str | None
    ) -> tuple[IconEntry, ...]:
        normalized = normalize_name(name)
        if provider:
            return index.get((provider.casefold(), normalized), ())
        candidates = {
            entry.id: entry
            for (candidate_provider, candidate_name), entries in index.items()
            if candidate_name == normalized
            for entry in entries
        }
        return tuple(sorted(candidates.values(), key=lambda entry: entry.id))

    def search(
        self,
        query: str = "",
        *,
        provider: str | None = None,
        kind: str | None = None,
        category: str | None = None,
        include_deprecated: bool = True,
        limit: int | None = None,
    ) -> tuple[IconEntry, ...]:
        """Return stable substring/token matches; search never implicitly resolves an icon."""

        normalized_query = normalize_name(query)
        query_tokens = tuple(normalized_query.split())
        matches: list[tuple[tuple[int, int, str], IconEntry]] = []
        for entry in self.entries:
            if provider and entry.provider != provider.casefold():
                continue
            if kind and entry.kind != kind:
                continue
            if category and entry.category != normalize_name(category).replace(" ", "-"):
                continue
            if not include_deprecated and entry.deprecated:
                continue
            names = [normalize_name(entry.display_name), *(normalize_name(alias) for alias in entry.aliases)]
            if query_tokens and not any(all(token in name for token in query_tokens) for name in names):
                continue
            exact = 0 if normalized_query and normalized_query in names else 1
            starts = 0 if normalized_query and any(name.startswith(normalized_query) for name in names) else 1
            matches.append(((exact, starts, entry.id), entry))
        ordered = tuple(entry for _, entry in sorted(matches, key=lambda item: item[0]))
        if limit is None:
            return ordered
        if limit < 0:
            raise ValueError("limit must be non-negative")
        return ordered[:limit]

    def verify(self, *, strict: bool = False) -> VerificationReport:
        errors: list[str] = []
        counts: dict[str, dict[str, int]] = {}
        seen_paths: dict[str, str] = {}
        for entry in self.entries:
            counts.setdefault(entry.provider, {}).setdefault(entry.kind, 0)
            counts[entry.provider][entry.kind] += 1
            for source_path in entry.source_paths:
                source_parts = Path(source_path).parts
                if (
                    not source_path.startswith("assets/vendor/")
                    or "__MACOSX" in source_parts
                    or any(part.startswith("._") for part in source_parts)
                ):
                    errors.append(f"{entry.id}: non-official or excluded source path {source_path!r}")
            relative = Path(entry.path)
            if relative.is_absolute() or ".." in relative.parts:
                errors.append(f"{entry.id}: unsafe asset path {entry.path!r}")
                continue
            asset_path = (self.assets_root / relative).resolve()
            if not _path_is_relative_to(asset_path, self.assets_root):
                errors.append(f"{entry.id}: asset path escapes catalog root")
                continue
            if entry.path in seen_paths and seen_paths[entry.path] != entry.id:
                errors.append(f"{entry.id}: asset path also used by {seen_paths[entry.path]}")
            seen_paths[entry.path] = entry.id
            try:
                data = asset_path.read_bytes()
            except OSError as exc:
                errors.append(f"{entry.id}: unable to read {entry.path}: {exc}")
                continue
            actual_checksum = sha256(data).hexdigest()
            if actual_checksum != entry.checksum:
                errors.append(
                    f"{entry.id}: checksum mismatch (expected {entry.checksum}, got {actual_checksum})"
                )
                continue
            try:
                root = validate_svg_bytes(data, source=entry.path)
                width, height, view_box = svg_geometry(root)
            except SvgSafetyError as exc:
                errors.append(f"{entry.id}: {exc}")
                continue
            if (width, height, view_box) != (entry.width, entry.height, entry.view_box):
                errors.append(f"{entry.id}: SVG geometry does not match registry metadata")
        ambiguous: dict[str, tuple[str, ...]] = {}
        for (provider, alias), candidates in sorted(self._alias_index.items()):
            if len(candidates) > 1:
                ambiguous[f"{provider}:{alias}"] = tuple(entry.id for entry in candidates)
        report = VerificationReport(
            checked=len(self.entries),
            errors=tuple(sorted(errors)),
            counts={
                provider: dict(sorted(kinds.items()))
                for provider, kinds in sorted(counts.items())
            },
            ambiguous_aliases=ambiguous,
        )
        if strict:
            report.raise_for_errors()
        return report

    def to_dict(self) -> dict[str, Any]:
        return {
            "entries": [entry.to_dict() for entry in self.entries],
            "providers": self.providers,
            "schema_version": self.schema_version,
        }


def load(path: str | Path = DEFAULT_REGISTRY_PATH, *, assets_root: str | Path | None = None) -> IconRegistry:
    """Load the canonical registry JSON."""

    return IconRegistry.load(path, assets_root=assets_root)


def load_registry(
    path: str | Path = DEFAULT_REGISTRY_PATH, *, assets_root: str | Path | None = None
) -> IconRegistry:
    """Compatibility alias for :func:`load`."""

    return load(path, assets_root=assets_root)


def search(
    query: str,
    *,
    registry: IconRegistry | None = None,
    provider: str | None = None,
    kind: str | None = None,
    category: str | None = None,
    include_deprecated: bool = True,
    limit: int | None = None,
) -> tuple[IconEntry, ...]:
    """Search a supplied or default registry deterministically."""

    selected = registry or load()
    return selected.search(
        query,
        provider=provider,
        kind=kind,
        category=category,
        include_deprecated=include_deprecated,
        limit=limit,
    )


def verify(
    registry: IconRegistry | str | Path | None = None,
    *,
    assets_root: str | Path | None = None,
    strict: bool = False,
) -> VerificationReport:
    """Verify registry structure, local checksums, SVG safety, and dimensions."""

    selected = registry if isinstance(registry, IconRegistry) else load(registry or DEFAULT_REGISTRY_PATH, assets_root=assets_root)
    return selected.verify(strict=strict)
