"""Semantic, geometry, and generated-output validation APIs."""

from .geometry import GeometryValidationError, GeometryValidationResult, validate_geometry
from .output import (
    OutputValidationError,
    OutputValidationResult,
    require_valid_drawio_output,
    validate_drawio_output,
)
from .semantic import SemanticValidationError, SemanticValidationResult, validate_semantics

__all__ = [
    "GeometryValidationError",
    "GeometryValidationResult",
    "OutputValidationError",
    "OutputValidationResult",
    "SemanticValidationError",
    "SemanticValidationResult",
    "require_valid_drawio_output",
    "validate_drawio_output",
    "validate_geometry",
    "validate_semantics",
]
