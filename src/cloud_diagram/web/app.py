"""FastAPI backend exposing the deterministic compiler and optional LLM planner.

This module intentionally contains no diagram-compilation logic of its own.
Every endpoint delegates to :mod:`cloud_diagram.compiler` and
:mod:`cloud_diagram.planner`; this file only handles HTTP request/response
shaping, error mapping, and per-request credential scoping.

Run with:
    uvicorn cloud_diagram.web.app:app --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, SecretStr

from cloud_diagram.compiler import (
    CloudDiagramCompiler,
    CompilationError,
    SpecLoadError,
    validate_diagram_spec,
)
from cloud_diagram.domain import DiagramSpec, Provider
from cloud_diagram.planner import OpenAICompatiblePlanner, PlannerError
from cloud_diagram.settings import Settings

app = FastAPI(
    title="Cloud Diagram Compiler API",
    description=(
        "Deterministic, offline-icon, left-to-right cloud architecture diagram "
        "compiler. Accepts either a strict DiagramSpec or a natural-language "
        "prompt (with a caller-supplied LLM key) and returns a validated, "
        "editable draw.io file plus full diagnostics."
    ),
    version="0.1.0",
)

_cors_origins = [
    origin.strip()
    for origin in os.environ.get("WEB_CORS_ORIGINS", "http://localhost:5173").split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _shared_compiler() -> CloudDiagramCompiler:
    """Rules and the icon registry are static; load and verify them once."""

    return CloudDiagramCompiler(Settings.from_environment(validate_files=True))


class LlmOverride(BaseModel):
    """Optional per-request LLM credentials.

    A client-supplied key always wins over the server's own ``.env``/environment
    configuration, and is used only for the lifetime of this one request. It is
    never written to disk, logged, or echoed back in any response.
    """

    model_config = ConfigDict(extra="forbid")

    endpoint: AnyHttpUrl | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: SecretStr | None = None


class GenerateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=4000)
    provider: Provider
    llm: LlmOverride | None = None


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any]


class ValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spec: dict[str, Any]
    drawio_xml: str | None = None


class CompilationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagram_id: str
    drawio_xml: str
    diagnostics: dict[str, Any]
    quality_score: int
    resolved_icons: tuple[dict[str, Any], ...]


class DiagnosticsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diagram_id: str
    diagnostics: dict[str, Any]
    valid: bool


class IconResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    provider: str
    kind: str
    category: str
    display_name: str
    aliases: list[str]
    deprecated: bool


class IconSearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int
    results: tuple[IconResult, ...]


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]
    ruleset_id: str
    ruleset_version: str
    icon_count: int
    registry_valid: bool


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CompilationError):
        return HTTPException(status_code=422, detail={
            "message": str(exc),
            "diagnostics": exc.report.model_dump(mode="json", exclude_none=True),
        })
    if isinstance(exc, (SpecLoadError, PlannerError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail="internal server error")


def _scoped_settings(compiler: CloudDiagramCompiler, llm: LlmOverride | None) -> Settings:
    """Build request-scoped settings that layer an optional client key over defaults."""

    if llm is None:
        return compiler.settings
    updates: dict[str, Any] = {}
    if llm.endpoint is not None:
        updates["llm_endpoint"] = llm.endpoint
    if llm.model is not None:
        updates["llm_model"] = llm.model
    if llm.api_key is not None:
        updates["llm_api_key"] = llm.api_key
        updates["llm_api_key_name"] = "request-supplied"
    if not updates:
        return compiler.settings
    return compiler.settings.model_copy(update=updates)


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    compiler = _shared_compiler()
    return HealthResponse(
        status="ok",
        ruleset_id=compiler.rules.ruleset.id,
        ruleset_version=compiler.rules.ruleset.version,
        icon_count=compiler.registry_verification.checked,
        registry_valid=compiler.registry_verification.valid,
    )


@app.get("/api/icons/{icon_id}/asset", response_class=FileResponse)
def icon_asset(icon_id: str) -> FileResponse:
    """Serve one verified local SVG from the immutable icon registry."""

    registry = _shared_compiler().registry
    entry = registry.get(icon_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="icon not found")

    asset_path = (registry.assets_root / Path(entry.path)).resolve()
    try:
        asset_path.relative_to(registry.assets_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="icon not found") from exc
    if not asset_path.is_file():
        raise HTTPException(status_code=404, detail="icon asset not found")
    return FileResponse(asset_path, media_type="image/svg+xml")


@app.get("/api/icons/search", response_model=IconSearchResponse)
def icons_search(
    q: Annotated[str, Field(min_length=0, max_length=200)] = "",
    provider: Provider | None = None,
    kind: Literal["service", "resource", "group", "category"] | None = None,
    limit: Annotated[int, Field(ge=0, le=200)] = 20,
) -> IconSearchResponse:
    try:
        results = _shared_compiler().search_icons(
            q,
            provider=provider.value if provider else None,
            kind=kind,
            limit=limit,
        )
    except Exception as exc:  # noqa: BLE001 - mapped to a structured HTTP error below
        raise _http_error(exc) from exc
    return IconSearchResponse(
        count=len(results),
        results=tuple(IconResult.model_validate(item) for item in results),
    )


def _to_response(result: Any) -> CompilationResponse:
    return CompilationResponse(
        diagram_id=result.spec.diagram_id,
        drawio_xml=result.drawio_text(),
        diagnostics=result.diagnostics.model_dump(mode="json", exclude_none=True),
        quality_score=result.diagnostics.quality_score,
        resolved_icons=tuple(item.model_dump(mode="json") for item in result.resolved_icons),
    )


@app.post("/api/render", response_model=CompilationResponse)
def render(request: RenderRequest) -> CompilationResponse:
    compiler = _shared_compiler()
    try:
        spec = validate_diagram_spec(request.spec)
        result = compiler.compile(spec)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return _to_response(result)


@app.post("/api/validate", response_model=DiagnosticsResponse)
def validate(request: ValidateRequest) -> DiagnosticsResponse:
    compiler = _shared_compiler()
    try:
        spec = validate_diagram_spec(request.spec)
        result = compiler.validate(spec, drawio=request.drawio_xml)
    except CompilationError as exc:
        return DiagnosticsResponse(
            diagram_id=exc.report.diagram_id,
            diagnostics=exc.report.model_dump(mode="json", exclude_none=True),
            valid=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return DiagnosticsResponse(
        diagram_id=result.spec.diagram_id,
        diagnostics=result.diagnostics.model_dump(mode="json", exclude_none=True),
        valid=True,
    )


@app.post("/api/generate", response_model=CompilationResponse)
async def generate(request: GenerateRequest) -> CompilationResponse:
    compiler = _shared_compiler()
    scoped_settings = _scoped_settings(compiler, request.llm)
    try:
        planner = OpenAICompatiblePlanner(scoped_settings, compiler.registry)
        spec: DiagramSpec = await planner.plan(request.prompt, request.provider)
        result = compiler.compile(spec)
    except Exception as exc:  # noqa: BLE001
        raise _http_error(exc) from exc
    return _to_response(result)


__all__ = ["app"]
