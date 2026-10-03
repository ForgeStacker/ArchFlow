"""Deterministic compiler for official AWS, Azure, and GCP SVG releases.

Canonical IDs are ``provider:kind:category:slug``. Runtime paths mirror those
fields as ``provider/kind/category/slug.svg``. A stable source-path hash is
appended only when official, distinct artwork would otherwise collide.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable, Mapping

from .registry import (
    DEFAULT_REGISTRY_PATH,
    IconEntry,
    IconRegistry,
    RegistryFormatError,
    normalize_name,
    normalize_svg_bytes,
    svg_geometry,
    validate_svg_bytes,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VENDOR_ROOT = PROJECT_ROOT / "assets" / "vendor"
DEFAULT_OUTPUT_ROOT = DEFAULT_REGISTRY_PATH.parent
_SUPPORTED_PROVIDERS = ("aws", "azure", "gcp")
_AWS_KNOWN_ALIASES: Mapping[str, tuple[str, ...]] = {
    "amazon simple storage service": ("Amazon S3", "S3", "Simple Storage Service"),
    "amazon elastic compute cloud": ("Amazon EC2", "EC2", "Elastic Compute Cloud"),
    "amazon relational database service": ("Amazon RDS", "RDS", "Relational Database Service"),
}


class IconCompilerError(Exception):
    """Base exception for icon compilation failures."""


class SourceLayoutError(IconCompilerError):
    """Raised when an official provider release layout is absent or invalid."""


class IconCollisionError(IconCompilerError):
    """Raised when stable source-derived IDs still collide."""


@dataclass(frozen=True, slots=True)
class _Candidate:
    provider: str
    kind: str
    category: str
    display_name: str
    aliases: tuple[str, ...]
    source_paths: tuple[Path, ...]
    canonical_source: Path
    deprecated: bool
    provenance: Mapping[str, Any]
    slug_hint: str | None = None


def _slug(value: str) -> str:
    slug = normalize_name(value).replace(" ", "-")
    return slug or "icon"


def _display_from_stem(stem: str, prefix: str, suffix: str = "") -> str:
    value = stem
    if prefix and value.startswith(prefix):
        value = value[len(prefix) :]
    if suffix and value.endswith(suffix):
        value = value[: -len(suffix)]
    return " ".join(value.replace("_", " ").replace("-", " ").split())


def _official_svg_paths(root: Path) -> tuple[Path, ...]:
    return tuple(
        sorted(
            (
                path
                for path in root.rglob("*.svg")
                if "__MACOSX" not in path.parts
                and not path.name.startswith("._")
                and path.name != ".DS_Store"
            ),
            key=lambda path: path.as_posix(),
        )
    )


def _load_provenance(release_root: Path, vendor_root: Path) -> dict[str, Any]:
    source_path = release_root / "SOURCE.json"
    try:
        source = json.loads(source_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceLayoutError(f"invalid provider provenance {source_path}: {exc}") from exc
    archives = [
        {
            "original_filename": archive.get("original_filename"),
            "sha256": archive.get("sha256"),
            "url": archive.get("url"),
        }
        for archive in source.get("archives", [])
    ]
    return {
        "archives": archives,
        "official_source_page": source.get("official_source_page"),
        "release_identifier": source.get("release_identifier"),
        "retrieval_date": source.get("retrieval_date"),
        "source_manifest": source_path.relative_to(vendor_root.parent.parent).as_posix(),
    }


def _release_root(provider_root: Path) -> Path:
    releases = sorted(path for path in provider_root.iterdir() if path.is_dir())
    if len(releases) != 1:
        raise SourceLayoutError(
            f"expected exactly one release under {provider_root}, found {len(releases)}"
        )
    return releases[0]


def _aliases(provider: str, display: str, extras: Iterable[str] = ()) -> tuple[str, ...]:
    values = {*extras}
    if provider == "aws":
        stripped = re.sub(r"^(?:AWS|Amazon)\s+", "", display, flags=re.IGNORECASE)
        values.add(stripped)
        values.add(f"AWS {stripped}")
        values.update(_AWS_KNOWN_ALIASES.get(normalize_name(display), ()))
    elif provider == "azure" and not normalize_name(display).startswith("azure "):
        values.add(f"Azure {display}")
    elif provider == "gcp":
        values.add(f"GCP {display}")
        values.add(f"Google Cloud {display}")
    values.discard(display)
    return tuple(sorted((value for value in values if value), key=lambda value: (normalize_name(value), value)))


def _aws_candidates(vendor_root: Path) -> tuple[_Candidate, ...]:
    release = _release_root(vendor_root / "aws")
    raw = release / "raw"
    provenance = _load_provenance(release, vendor_root)
    candidates: list[_Candidate] = []

    service_paths: list[Path] = []
    for service_root in sorted(raw.glob("Architecture-Service-Icons*")):
        service_paths.extend(sorted(service_root.glob("Arch_*/48/*.svg")))
    for path in service_paths:
        if path.name.startswith("._"):
            continue
        category = _slug(path.parent.parent.name.removeprefix("Arch_"))
        display = _display_from_stem(path.stem, "Arch_", "_48")
        candidates.append(
            _Candidate("aws", "service", category, display, _aliases("aws", display), (path,), path, False, provenance)
        )

    for category_root in sorted(raw.glob("Category-Icons*")):
        for path in sorted(category_root.glob("Arch-Category_48/*.svg")):
            if path.name.startswith("._"):
                continue
            display = _display_from_stem(path.stem, "Arch-Category_", "_48")
            candidates.append(
                _Candidate("aws", "category", "categories", display, _aliases("aws", display), (path,), path, False, provenance)
            )

    for group_root in sorted(raw.glob("Architecture-Group-Icons*")):
        for path in _official_svg_paths(group_root):
            display = _display_from_stem(path.stem, "", re.search(r"_(?:16|32|48|64)$", path.stem).group(0) if re.search(r"_(?:16|32|48|64)$", path.stem) else "")
            candidates.append(
                _Candidate("aws", "group", "groups", display, _aliases("aws", display), (path,), path, False, provenance)
            )

    for resource_root in sorted(raw.glob("Resource-Icons*")):
        for path in _official_svg_paths(resource_root):
            relative = path.relative_to(resource_root)
            top_category = relative.parts[0] if len(relative.parts) > 1 else "resources"
            category = _slug(top_category.removeprefix("Res_"))
            display = _display_from_stem(path.stem, "Res_", "_48")
            slug_hint = _slug(" ".join(relative.with_suffix("").parts))
            candidates.append(
                _Candidate("aws", "resource", category, display, _aliases("aws", display), (path,), path, False, provenance, slug_hint)
            )
    return tuple(sorted(candidates, key=lambda item: item.canonical_source.as_posix()))


def _azure_display(path: Path) -> str:
    stem = re.sub(r"^\d+-icon-service-", "", path.stem)
    return " ".join(stem.replace("_", " ").replace("-", " ").split())


def _azure_candidates(vendor_root: Path) -> tuple[_Candidate, ...]:
    release = _release_root(vendor_root / "azure")
    raw = release / "raw" / "Azure_Public_Service_Icons" / "Icons"
    provenance = _load_provenance(release, vendor_root)
    by_checksum: dict[str, list[Path]] = defaultdict(list)
    for path in _official_svg_paths(raw):
        by_checksum[sha256(path.read_bytes()).hexdigest()].append(path)
    candidates: list[_Candidate] = []
    for checksum in sorted(by_checksum):
        paths = tuple(sorted(by_checksum[checksum], key=lambda path: path.as_posix()))
        canonical = paths[0]
        displays = tuple(sorted({_azure_display(path) for path in paths}, key=lambda value: (normalize_name(value), value)))
        display = _azure_display(canonical)
        category = _slug(canonical.relative_to(raw).parts[0])
        aliases = _aliases("azure", display, displays)
        deprecated = any("deprecated" in normalize_name(value) for value in displays)
        candidates.append(
            _Candidate("azure", "service", category, display, aliases, paths, canonical, deprecated, provenance)
        )
    return tuple(sorted(candidates, key=lambda item: item.canonical_source.as_posix()))


def _gcp_candidates(vendor_root: Path) -> tuple[_Candidate, ...]:
    release = _release_root(vendor_root / "gcp")
    raw = release / "raw"
    provenance = _load_provenance(release, vendor_root)
    candidates: list[_Candidate] = []
    for path in _official_svg_paths(raw):
        relative = path.relative_to(raw)
        if relative.parts[0] == "Category Icons":
            kind = "category"
            category = "categories"
        elif relative.parts[0] == "Unique Icons":
            kind = "service"
            category = "products"
        else:
            raise SourceLayoutError(f"unrecognized GCP icon path: {path}")
        try:
            display = relative.parts[1]
        except IndexError as exc:
            raise SourceLayoutError(f"unrecognized GCP icon path: {path}") from exc
        candidates.append(
            _Candidate("gcp", kind, category, display, _aliases("gcp", display), (path,), path, False, provenance)
        )
    if len(candidates) != 45:
        raise SourceLayoutError(f"expected 45 accepted GCP SVGs, found {len(candidates)}")
    return tuple(sorted(candidates, key=lambda item: item.canonical_source.as_posix()))


def _stable_source_path(path: Path) -> str:
    """Return a checkout-independent official source path for IDs and metadata."""

    parts = path.parts
    try:
        assets_index = parts.index("assets")
    except ValueError as exc:
        raise SourceLayoutError(f"official source path has no assets root: {path}") from exc
    stable = Path(*parts[assets_index:]).as_posix()
    if not stable.startswith("assets/vendor/"):
        raise SourceLayoutError(f"official source is not below assets/vendor: {path}")
    return stable


def _assign_ids(candidates: Iterable[_Candidate]) -> tuple[tuple[_Candidate, str, str], ...]:
    used: dict[str, Path] = {}
    assigned: list[tuple[_Candidate, str, str]] = []
    for candidate in sorted(candidates, key=lambda item: (item.provider, item.kind, item.category, item.canonical_source.as_posix())):
        base_slug = candidate.slug_hint or _slug(candidate.display_name)
        icon_id = f"{candidate.provider}:{candidate.kind}:{candidate.category}:{base_slug}"
        slug = base_slug
        if icon_id in used:
            source_key = "\n".join(_stable_source_path(path) for path in candidate.source_paths)
            slug = f"{base_slug}-{sha256(source_key.encode('utf-8')).hexdigest()[:10]}"
            icon_id = f"{candidate.provider}:{candidate.kind}:{candidate.category}:{slug}"
        if icon_id in used:
            raise IconCollisionError(
                f"unresolved ID collision between {used[icon_id]} and {candidate.canonical_source}"
            )
        used[icon_id] = candidate.canonical_source
        assigned.append((candidate, icon_id, slug))
    return tuple(assigned)


def _source_relative(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError as exc:
        raise SourceLayoutError(f"official source is outside project root: {path}") from exc


def _compile_candidate(
    candidate: _Candidate,
    icon_id: str,
    slug: str,
    *,
    output_root: Path,
    project_root: Path,
) -> IconEntry:
    source = candidate.canonical_source
    raw_bytes = source.read_bytes()
    normalized = normalize_svg_bytes(raw_bytes, source=source.as_posix())
    root = validate_svg_bytes(normalized, source=source.as_posix())
    width, height, view_box = svg_geometry(root)
    relative_path = Path(candidate.provider) / candidate.kind / candidate.category / f"{slug}.svg"
    destination = output_root / relative_path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(normalized)
    return IconEntry(
        id=icon_id,
        provider=candidate.provider,
        kind=candidate.kind,
        category=candidate.category,
        slug=slug,
        display_name=candidate.display_name,
        aliases=candidate.aliases,
        path=relative_path.as_posix(),
        source_paths=tuple(_source_relative(path, project_root) for path in candidate.source_paths),
        width=float(width),
        height=float(height),
        view_box=view_box,
        checksum=sha256(normalized).hexdigest(),
        deprecated=candidate.deprecated,
        provenance=candidate.provenance,
    )


def compile_registry(
    vendor_root: str | Path = DEFAULT_VENDOR_ROOT,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    registry_path: str | Path | None = None,
) -> IconRegistry:
    """Compile official individual SVGs into a deterministic local registry.

    Only generated provider directories below ``output_root`` are replaced.
    Official vendor sources and legacy ``assets/cloud-icons`` are never modified.
    """

    vendor = Path(vendor_root).resolve()
    output = Path(output_root).resolve()
    if not vendor.is_dir():
        raise SourceLayoutError(f"vendor root does not exist: {vendor}")
    project_root = vendor.parent.parent
    output.mkdir(parents=True, exist_ok=True)
    for provider in _SUPPORTED_PROVIDERS:
        generated_provider = output / provider
        if generated_provider.exists():
            shutil.rmtree(generated_provider)

    candidates = (*_aws_candidates(vendor), *_azure_candidates(vendor), *_gcp_candidates(vendor))
    entries = [
        _compile_candidate(candidate, icon_id, slug, output_root=output, project_root=project_root)
        for candidate, icon_id, slug in _assign_ids(candidates)
    ]
    providers: dict[str, Any] = {}
    for provider in _SUPPORTED_PROVIDERS:
        provider_entries = [entry for entry in entries if entry.provider == provider]
        provenance = dict(provider_entries[0].provenance) if provider_entries else {}
        providers[provider] = {
            "entry_count": len(provider_entries),
            "kinds": {
                kind: sum(entry.kind == kind for entry in provider_entries)
                for kind in sorted({entry.kind for entry in provider_entries})
            },
            "provenance": provenance,
        }
    registry = IconRegistry(entries, assets_root=output, providers=providers)
    destination = Path(registry_path).resolve() if registry_path else output / "registry.json"
    if destination.parent != output:
        raise RegistryFormatError("registry_path must be directly within output_root")
    serialized = json.dumps(
        registry.to_dict(), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    destination.write_text(serialized, encoding="utf-8", newline="\n")
    return IconRegistry(
        registry.entries,
        assets_root=output,
        providers=providers,
        registry_path=destination,
    )
