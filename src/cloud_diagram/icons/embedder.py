"""Checksum-verified offline SVG embedding for draw.io."""

from __future__ import annotations

import base64
from hashlib import sha256
from pathlib import Path
from typing import MutableMapping

from .registry import IconEntry, IconRegistry, SvgSafetyError, validate_svg_bytes
from .resolver import resolve_exact


class IconEmbeddingError(Exception):
    """Base exception for embedding failures."""


class IconChecksumError(IconEmbeddingError):
    """Raised when normalized artwork changed after registry compilation."""


class SvgEmbedder:
    """Embed verified local SVG bytes, deduplicated by registered checksum."""

    def __init__(self, registry: IconRegistry) -> None:
        self.registry = registry
        self._cache: MutableMapping[str, str] = {}

    def embed_entry(self, entry: IconEntry) -> str:
        relative = Path(entry.path)
        if relative.is_absolute() or ".." in relative.parts:
            raise IconEmbeddingError(f"unsafe icon asset path: {entry.path!r}")
        path = (self.registry.assets_root / relative).resolve()
        try:
            path.relative_to(self.registry.assets_root)
        except ValueError as exc:
            raise IconEmbeddingError(f"icon asset escapes catalog root: {entry.path!r}") from exc
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise IconEmbeddingError(f"unable to read icon asset {entry.path}: {exc}") from exc
        actual = sha256(data).hexdigest()
        if actual != entry.checksum:
            raise IconChecksumError(
                f"checksum drift for {entry.id}: expected {entry.checksum}, got {actual}"
            )
        try:
            validate_svg_bytes(data, source=entry.path)
        except SvgSafetyError as exc:
            raise IconEmbeddingError(str(exc)) from exc
        cached = self._cache.get(actual)
        if cached is not None:
            return cached
        uri = "data:image/svg+xml;base64," + base64.b64encode(data).decode("ascii")
        self._cache[actual] = uri
        return uri

    def embed(
        self,
        value: IconEntry | str,
        *,
        provider: str | None = None,
    ) -> str:
        entry = (
            value
            if isinstance(value, IconEntry)
            else resolve_exact(value, registry=self.registry, provider=provider).entry
        )
        return self.embed_entry(entry)


def embed_svg(entry: IconEntry, *, registry: IconRegistry) -> str:
    """Return a checksum-verified base64 SVG data URI suitable for draw.io."""

    return SvgEmbedder(registry).embed_entry(entry)


def embed_data_uri(
    value: IconEntry | str,
    *,
    registry: IconRegistry,
    provider: str | None = None,
) -> str:
    """Resolve if necessary and return an offline SVG data URI."""

    return SvgEmbedder(registry).embed(value, provider=provider)
