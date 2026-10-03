"""Typer command-line interface for deterministic cloud diagrams."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import tempfile
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from click import ClickException

from cloud_diagram.compiler import (
    CloudDiagramCompiler,
    CompilationError,
    load_diagram_spec,
    write_diagnostics,
    write_diagram_spec,
)
from cloud_diagram.icons import IconRegistry, compile_registry
from cloud_diagram.planner import OpenAICompatiblePlanner
from cloud_diagram.settings import Settings

app = typer.Typer(
    name="cloud-diagram",
    help="Compile strict semantic cloud specifications into validated draw.io files.",
    no_args_is_help=True,
)
icons_app = typer.Typer(help="Search, verify, or explicitly rebuild the local icon registry.")
app.add_typer(icons_app, name="icons")


class CloudProvider(StrEnum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class IconKind(StrEnum):
    SERVICE = "service"
    RESOURCE = "resource"
    GROUP = "group"
    CATEGORY = "category"


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _require_parent(path: Path) -> None:
    if not path.parent.is_dir():
        raise ClickException(f"output directory does not exist: {path.parent}")
    if path.exists() and path.is_dir():
        raise ClickException(f"output path is a directory: {path}")


def _compiler() -> CloudDiagramCompiler:
    return CloudDiagramCompiler(Settings.from_environment(validate_files=True))


def _planner(compiler: CloudDiagramCompiler) -> OpenAICompatiblePlanner:
    return OpenAICompatiblePlanner(compiler.settings, compiler.registry)


def _raise_cli_error(exc: Exception) -> None:
    if isinstance(exc, CompilationError):
        raise ClickException(
            f"{exc}; diagnostics={exc.report.canonical_json()}"
        ) from exc
    if isinstance(exc, ClickException):
        raise exc
    raise ClickException(str(exc)) from exc


@app.command()
def render(
    spec: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    output: Annotated[Path, typer.Option("--output", "-o")],
    diagnostics: Annotated[Path | None, typer.Option("--diagnostics")] = None,
) -> None:
    """Render a JSON/YAML DiagramSpec without invoking a planner."""

    try:
        _require_parent(output)
        if diagnostics is not None:
            _require_parent(diagnostics)
        compiler = _compiler()
        result = compiler.write(load_diagram_spec(spec), output)
        if diagnostics is not None:
            write_diagnostics(diagnostics, result.diagnostics)
        typer.echo(_json({
            "diagram_id": result.spec.diagram_id,
            "output": str(output),
            "quality_score": result.diagnostics.quality_score,
        }))
    except Exception as exc:
        _raise_cli_error(exc)


@app.command()
def generate(
    prompt: Annotated[str, typer.Argument()],
    provider: Annotated[CloudProvider, typer.Option("--provider")],
    output: Annotated[Path, typer.Option("--output", "-o")],
    diagnostics: Annotated[Path | None, typer.Option("--diagnostics")] = None,
) -> None:
    """Plan and render a cloud diagram through the configured planner."""

    try:
        _require_parent(output)
        if diagnostics is not None:
            _require_parent(diagnostics)
        compiler = _compiler()
        spec = asyncio.run(_planner(compiler).plan(prompt, provider.value))
        result = compiler.write(spec, output)
        if diagnostics is not None:
            write_diagnostics(diagnostics, result.diagnostics)
        typer.echo(_json({
            "diagram_id": result.spec.diagram_id,
            "output": str(output),
            "quality_score": result.diagnostics.quality_score,
        }))
    except Exception as exc:
        _raise_cli_error(exc)


@app.command()
def plan(
    prompt: Annotated[str, typer.Argument()],
    provider: Annotated[CloudProvider, typer.Option("--provider")],
    output: Annotated[Path, typer.Option("--output", "-o")],
) -> None:
    """Create a deterministic JSON DiagramSpec without rendering it."""

    try:
        _require_parent(output)
        compiler = _compiler()
        spec = asyncio.run(_planner(compiler).plan(prompt, provider.value))
        write_diagram_spec(output, spec)
        typer.echo(_json({"diagram_id": spec.diagram_id, "output": str(output)}))
    except Exception as exc:
        _raise_cli_error(exc)


@app.command()
def validate(
    spec: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    drawio: Annotated[Path | None, typer.Option("--drawio", exists=True, dir_okay=False, readable=True)] = None,
) -> None:
    """Compile in memory and optionally validate supplied draw.io XML against it."""

    try:
        compiler = _compiler()
        source = load_diagram_spec(spec)
        supplied = drawio.read_bytes() if drawio is not None else None
        result = compiler.validate(source, drawio=supplied)
        typer.echo(result.diagnostics.canonical_json())
    except Exception as exc:
        _raise_cli_error(exc)


@app.command()
def explain(
    spec: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
) -> None:
    """Print canonical compilation diagnostics JSON."""

    try:
        result = _compiler().compile(load_diagram_spec(spec))
        typer.echo(result.diagnostics.canonical_json())
    except Exception as exc:
        _raise_cli_error(exc)


@icons_app.command("search")
def icons_search(
    query: Annotated[str, typer.Argument()],
    provider: Annotated[CloudProvider | None, typer.Option("--provider")] = None,
    kind: Annotated[IconKind | None, typer.Option("--kind")] = None,
    limit: Annotated[int, typer.Option("--limit", min=0, max=200)] = 20,
) -> None:
    """Search deterministic local icon metadata."""

    try:
        results = _compiler().search_icons(
            query,
            provider=provider.value if provider else None,
            kind=kind.value if kind else None,
            limit=limit,
        )
        typer.echo(_json({"count": len(results), "results": results}))
    except Exception as exc:
        _raise_cli_error(exc)


@icons_app.command("verify")
def icons_verify() -> None:
    """Strictly verify local registry metadata and SVG assets."""

    try:
        report = _compiler().registry_verification
        typer.echo(_json({
            "ambiguous_aliases": report.ambiguous_aliases,
            "checked": report.checked,
            "counts": report.counts,
            "errors": report.errors,
            "valid": report.valid,
        }))
    except Exception as exc:
        _raise_cli_error(exc)


def _compile_icons_safely(settings: Settings) -> IconRegistry:
    """Compile in staging and promote generated catalog paths with rollback."""

    assert settings.registry_path is not None
    output_root = settings.registry_path.parent
    if not output_root.parent.is_dir():
        raise ValueError(f"icon output parent does not exist: {output_root.parent}")
    staging = Path(tempfile.mkdtemp(prefix=".cloud-diagram-icons-stage-", dir=output_root.parent))
    backup = Path(tempfile.mkdtemp(prefix=".cloud-diagram-icons-backup-", dir=output_root.parent))
    names = ("aws", "azure", "gcp", settings.registry_path.name)
    moved_old: list[str] = []
    promoted: list[str] = []
    try:
        compiled = compile_registry(
            vendor_root=settings.project_root / "assets" / "vendor",
            output_root=staging,
            registry_path=staging / settings.registry_path.name,
        )
        compiled.verify(strict=True)
        output_root.mkdir(exist_ok=True)
        for name in names:
            destination = output_root / name
            source = staging / name
            if destination.exists():
                os.replace(destination, backup / name)
                moved_old.append(name)
            os.replace(source, destination)
            promoted.append(name)
        result = IconRegistry.load(settings.registry_path)
        result.verify(strict=True)
        return result
    except BaseException:
        for name in reversed(promoted):
            destination = output_root / name
            if destination.is_dir():
                shutil.rmtree(destination)
            elif destination.exists():
                destination.unlink()
        for name in reversed(moved_old):
            os.replace(backup / name, output_root / name)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(backup, ignore_errors=True)


@icons_app.command("compile")
def icons_compile() -> None:
    """Explicitly regenerate the local icon catalog from official vendor assets."""

    try:
        settings = Settings.from_environment(validate_files=False)
        assert settings.registry_path is not None
        registry = _compile_icons_safely(settings)
        report = registry.verify(strict=True)
        typer.echo(_json({"checked": report.checked, "registry": str(settings.registry_path), "valid": report.valid}))
    except Exception as exc:
        _raise_cli_error(exc)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
