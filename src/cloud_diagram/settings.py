"""Deterministic application settings and project path discovery."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import ClassVar, Self

from dotenv import load_dotenv
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr, StrictInt, model_validator


def load_dotenv_file(start: str | Path | None = None) -> Path | None:
    """Load a ``.env`` file from the discovered project root into the process environment.

    Existing environment variables always win over ``.env`` values, so container
    or shell-exported configuration is never silently overridden. Returns the
    loaded path, or ``None`` when no ``.env`` file exists.
    """

    try:
        root = discover_project_root(start)
    except FileNotFoundError:
        return None
    env_path = root / ".env"
    if not env_path.is_file():
        return None
    load_dotenv(env_path, override=False)
    return env_path


def discover_project_root(start: str | Path | None = None) -> Path:
    """Find the nearest source checkout root without depending on the process CWD."""

    candidate = Path(start).expanduser() if start is not None else Path(__file__)
    candidate = candidate.resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for directory in (candidate, *candidate.parents):
        if (directory / "pyproject.toml").is_file() and (directory / "config" / "rules").is_dir():
            return directory
    raise FileNotFoundError(f"could not discover project root from {candidate}")


class Settings(BaseModel):
    """Immutable settings; optional LLM values are sourced by ``from_environment``."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)

    ENV_PREFIX: ClassVar[str] = "CLOUD_DIAGRAM_"

    project_root: Path = Field(default_factory=discover_project_root)
    rules_path: Path | None = None
    registry_path: Path | None = None
    llm_endpoint: AnyHttpUrl | None = None
    llm_model: str | None = Field(default=None, min_length=1)
    llm_api_key_name: str = Field(default="OPENAI_API_KEY", min_length=1)
    llm_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    planner_timeout_seconds: float = Field(default=30.0, ge=1.0, le=120.0)
    planner_max_tokens: StrictInt = Field(default=4096, ge=256, le=32768)

    @model_validator(mode="after")
    def resolve_paths(self) -> Self:
        root = self.project_root.expanduser().resolve()
        rules = self.rules_path or root / "config" / "rules" / "cloud-architecture.yaml"
        registry = self.registry_path or root / "assets" / "icons" / "registry.json"
        object.__setattr__(self, "project_root", root)
        object.__setattr__(self, "rules_path", self._absolute(rules, root))
        object.__setattr__(self, "registry_path", self._absolute(registry, root))
        return self

    @staticmethod
    def _absolute(path: Path, root: Path) -> Path:
        path = path.expanduser()
        return (root / path).resolve() if not path.is_absolute() else path.resolve()

    @classmethod
    def from_environment(
        cls,
        *,
        environ: Mapping[str, str] | None = None,
        validate_files: bool = False,
    ) -> Self:
        """Load supported settings from a ``.env`` file, then environment variables.

        Environment variables that are already set always take precedence over
        ``.env`` file contents. Pass an explicit ``environ`` mapping (e.g. in
        tests) to skip ``.env`` discovery entirely.
        """

        if environ is None:
            load_dotenv_file()
        env = os.environ if environ is None else environ
        prefix = cls.ENV_PREFIX
        values: dict[str, object] = {}
        project_root = env.get(f"{prefix}PROJECT_ROOT")
        if project_root:
            values["project_root"] = Path(project_root)
        rules_path = env.get(f"{prefix}RULES_PATH")
        if rules_path:
            values["rules_path"] = Path(rules_path)
        registry_path = env.get(f"{prefix}REGISTRY_PATH")
        if registry_path:
            values["registry_path"] = Path(registry_path)
        endpoint = env.get(f"{prefix}LLM_ENDPOINT")
        if endpoint:
            values["llm_endpoint"] = endpoint
        model = env.get(f"{prefix}LLM_MODEL")
        if model:
            values["llm_model"] = model
        key_name = env.get(f"{prefix}LLM_API_KEY_NAME", "OPENAI_API_KEY")
        values["llm_api_key_name"] = key_name
        key_value = env.get(key_name)
        if key_value:
            values["llm_api_key"] = SecretStr(key_value)
        timeout = env.get(f"{prefix}PLANNER_TIMEOUT_SECONDS")
        if timeout:
            try:
                values["planner_timeout_seconds"] = float(timeout)
            except ValueError as exc:
                raise ValueError(f"{prefix}PLANNER_TIMEOUT_SECONDS must be a number") from exc
        max_tokens = env.get(f"{prefix}PLANNER_MAX_TOKENS")
        if max_tokens:
            try:
                values["planner_max_tokens"] = int(max_tokens)
            except ValueError as exc:
                raise ValueError(f"{prefix}PLANNER_MAX_TOKENS must be an integer") from exc

        settings = cls.model_validate(values)
        if validate_files:
            settings.require_files()
        return settings

    def require_files(self, *, rules: bool = True, registry: bool = True) -> None:
        """Validate configured files when the caller needs them."""

        requested = (
            ("rules_path", self.rules_path, rules),
            ("registry_path", self.registry_path, registry),
        )
        for name, path, enabled in requested:
            if enabled and (path is None or not path.is_file()):
                raise FileNotFoundError(f"configured {name} does not exist: {path}")


__all__ = ["Settings", "discover_project_root", "load_dotenv_file"]
