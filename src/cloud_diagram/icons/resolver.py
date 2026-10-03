"""Deterministic exact icon resolution with explicit ambiguity failures."""

from __future__ import annotations

from dataclasses import dataclass

from .registry import IconEntry, IconRegistry, load


class IconResolutionError(Exception):
    """Base exception for icon resolution failures."""


class IconNotFoundError(IconResolutionError):
    """Raised when no exact ID, alias, or display-name match exists."""

    def __init__(self, value: str, provider: str | None = None) -> None:
        self.value = value
        self.provider = provider
        scope = f" for provider {provider!r}" if provider else ""
        super().__init__(f"no exact icon match for {value!r}{scope}")


class AmbiguousIconError(IconResolutionError):
    """Raised instead of selecting arbitrarily from exact matches."""

    def __init__(self, value: str, candidates: tuple[str, ...]) -> None:
        self.value = value
        self.candidates = tuple(sorted(candidates))
        super().__init__(
            f"ambiguous icon name {value!r}; candidates: {', '.join(self.candidates)}"
        )


@dataclass(frozen=True, slots=True)
class Resolution:
    """Resolved entry and the exact deterministic rule that selected it."""

    entry: IconEntry
    reason: str

    @property
    def icon(self) -> IconEntry:
        return self.entry


def _select(value: str, candidates: tuple[IconEntry, ...], reason: str) -> Resolution | None:
    if not candidates:
        return None
    if len(candidates) > 1:
        raise AmbiguousIconError(value, tuple(entry.id for entry in candidates))
    return Resolution(candidates[0], reason)


def resolve_exact(
    value: str,
    *,
    registry: IconRegistry | None = None,
    provider: str | None = None,
) -> Resolution:
    """Resolve in strict order: exact ID, exact normalized alias, then display name."""

    selected_registry = registry or load()
    direct = selected_registry.get(value)
    if direct is not None and (provider is None or direct.provider == provider.casefold()):
        return Resolution(direct, "exact-id")

    alias_resolution = _select(
        value,
        selected_registry.alias_candidates(value, provider),
        "exact-provider-alias" if provider else "exact-alias",
    )
    if alias_resolution is not None:
        return alias_resolution

    display_resolution = _select(
        value,
        selected_registry.display_candidates(value, provider),
        "exact-provider-display" if provider else "exact-display",
    )
    if display_resolution is not None:
        return display_resolution

    raise IconNotFoundError(value, provider)


class IconResolver:
    """Bound exact resolver for application services."""

    def __init__(self, registry: IconRegistry) -> None:
        self.registry = registry

    def resolve_exact(self, value: str, *, provider: str | None = None) -> Resolution:
        return resolve_exact(value, registry=self.registry, provider=provider)

    def resolve(self, value: str, *, provider: str | None = None) -> Resolution:
        """Resolve exactly; fuzzy search is deliberately not a fallback."""

        return self.resolve_exact(value, provider=provider)
