"""FastMCP tools backed by the shared cloud-diagram services."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from cloud_diagram.compiler import (
    CloudDiagramCompiler,
    CompilationResult,
    parse_diagram_spec,
)
from cloud_diagram.planner import OpenAICompatiblePlanner
from cloud_diagram.settings import Settings

server = FastMCP(
    "cloud-diagram",
    instructions="Plan, compile, validate, explain, and search deterministic local cloud diagrams.",
)


@lru_cache(maxsize=1)
def _compiler() -> CloudDiagramCompiler:
    return CloudDiagramCompiler(Settings.from_environment(validate_files=True))


def _spec(spec_json: str):
    return parse_diagram_spec(spec_json, format="json", source="spec_json")


def _output_path(path: str | None) -> Path | None:
    if path is None:
        return None
    destination = Path(path).expanduser()
    if not destination.is_absolute():
        destination = Path.cwd() / destination
    destination = destination.resolve()
    if not destination.parent.is_dir():
        raise ValueError(f"output directory does not exist: {destination.parent}")
    if destination.exists() and destination.is_dir():
        raise ValueError(f"output path is a directory: {destination}")
    return destination


def _summary(result: CompilationResult, *, output_path: Path | None = None) -> dict[str, Any]:
    value = result.summary_dict()
    if output_path is not None:
        value["output_path"] = str(output_path)
    return value


@server.tool(name="compile_diagram_spec", structured_output=True)
def compile_diagram_spec(spec_json: str, output_path: str | None = None) -> dict[str, Any]:
    """Compile strict DiagramSpec JSON; optionally atomically write a draw.io file."""

    compiler = _compiler()
    spec = _spec(spec_json)
    destination = _output_path(output_path)
    result = compiler.write(spec, destination) if destination is not None else compiler.compile(spec)
    return _summary(result, output_path=destination)


@server.tool(name="render_diagram_spec", structured_output=True)
def render_diagram_spec(spec_json: str) -> dict[str, Any]:
    """Explicitly render strict DiagramSpec JSON and return its XML string."""

    result = _compiler().compile(_spec(spec_json))
    return {
        "diagram_id": result.spec.diagram_id,
        "drawio_xml": result.drawio_text(),
        "quality_score": result.diagnostics.quality_score,
    }


@server.tool(name="validate_cloud_diagram", structured_output=True)
def validate_cloud_diagram(
    spec_json: str,
    drawio_xml: str | None = None,
) -> dict[str, Any]:
    """Compile in memory and optionally validate supplied XML against fresh geometry/icons."""

    result = _compiler().validate(_spec(spec_json), drawio=drawio_xml)
    return {
        "diagram_id": result.spec.diagram_id,
        "diagnostics": result.diagnostics.model_dump(mode="json", exclude_none=True),
        "valid": result.diagnostics.hard_pass,
    }


@server.tool(name="search_local_icons", structured_output=True)
def search_local_icons(
    query: str,
    provider: str | None = None,
    kind: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """Search small, safe local icon metadata without returning SVG/base64 assets."""

    if not 0 <= limit <= 200:
        raise ValueError("limit must be between 0 and 200")
    if provider is not None and provider not in {"aws", "azure", "gcp"}:
        raise ValueError("provider must be one of: aws, azure, gcp")
    if kind is not None and kind not in {"service", "resource", "group", "category"}:
        raise ValueError("kind must be one of: service, resource, group, category")
    results = _compiler().search_icons(query, provider=provider, kind=kind, limit=limit)
    return {"count": len(results), "results": list(results)}


@server.tool(name="explain_diagram_layout", structured_output=True)
def explain_diagram_layout(spec_json: str) -> dict[str, Any]:
    """Return canonical structured diagnostics for a freshly compiled DiagramSpec."""

    result = _compiler().compile(_spec(spec_json))
    return result.diagnostics.model_dump(mode="json", exclude_none=True)


@server.tool(name="generate_cloud_diagram", structured_output=True)
async def generate_cloud_diagram(
    prompt: str,
    provider: str,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Plan through the configured OpenAI-compatible adapter, then compile and optionally write."""

    destination = _output_path(output_path)
    compiler = _compiler()
    planner = OpenAICompatiblePlanner(compiler.settings, compiler.registry)
    spec = await planner.plan(prompt, provider)
    result = compiler.write(spec, destination) if destination is not None else compiler.compile(spec)
    return _summary(result, output_path=destination)


def main() -> None:
    server.run(transport="stdio")


if __name__ == "__main__":
    main()


__all__ = ["main", "server"]
