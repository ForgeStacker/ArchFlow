"""Public typed rule loading and precedence APIs."""

from .engine import (
    RuleEngine,
    RuleOverrideError,
    RuleResolution,
    RuleTraceRecord,
    resolve_rules,
)
from .loader import RulesLoadError, load_rules
from .models import EXPECTED_PRECEDENCE, MarginOverride, RuleOverrides, RuleSet

__all__ = [
    "EXPECTED_PRECEDENCE",
    "MarginOverride",
    "RuleEngine",
    "RuleOverrideError",
    "RuleOverrides",
    "RuleResolution",
    "RuleSet",
    "RuleTraceRecord",
    "RulesLoadError",
    "load_rules",
    "resolve_rules",
]
