"""Closed vocabularies used by the diagram domain contract."""

from __future__ import annotations

from enum import StrEnum


class Provider(StrEnum):
    """Supported cloud/provider scopes."""

    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"
    MIXED_CLOUD = "mixed_cloud"
    NEUTRAL = "neutral"


class GroupType(StrEnum):
    """Supported semantic containment groups across provider profiles."""

    CLOUD = "cloud"
    PROVIDER = "provider"
    REGION = "region"
    NETWORK = "network"
    VPC = "vpc"
    VIRTUAL_NETWORK = "virtual_network"
    VPC_NETWORK = "vpc_network"
    AVAILABILITY_ZONE = "availability_zone"
    ZONE = "zone"
    SUBNET = "subnet"
    RESOURCE_GROUP = "resource_group"
    PROJECT = "project"
    SERVICE_GROUP = "service_group"


class SemanticRole(StrEnum):
    """Provider-neutral roles used by normalization and ranking."""

    EXTERNAL_SOURCE = "external_source"
    ENTRYPOINT = "entrypoint"
    GATEWAY = "gateway"
    FRONTEND = "frontend"
    SERVICE = "service"
    COMPUTE = "compute"
    WORKER = "worker"
    ASYNCHRONOUS_BOUNDARY = "asynchronous_boundary"
    QUEUE = "queue"
    CACHE = "cache"
    DATASTORE = "datastore"
    ANALYTICS = "analytics"
    IDENTITY = "identity"
    OBSERVABILITY = "observability"
    EXTERNAL_SYSTEM = "external_system"
    EXTERNAL_SINK = "external_sink"


class EdgeKind(StrEnum):
    """Supported semantic edge kinds."""

    SYNCHRONOUS = "synchronous"
    ASYNCHRONOUS = "asynchronous"
    DATA = "data"
    DEPENDENCY = "dependency"
    BIDIRECTIONAL = "bidirectional"
    OBSERVABILITY = "observability"


class FlowDirection(StrEnum):
    """Compiler-owned flow direction. It is not a DiagramSpec field."""

    LEFT_TO_RIGHT = "left_to_right"


COMPILER_FLOW_DIRECTION = FlowDirection.LEFT_TO_RIGHT


class Criticality(StrEnum):
    """Operational importance of an edge."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class PortSide(StrEnum):
    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"


class AlignmentAxis(StrEnum):
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"


__all__ = [
    "AlignmentAxis",
    "COMPILER_FLOW_DIRECTION",
    "Criticality",
    "EdgeKind",
    "FlowDirection",
    "GroupType",
    "PortSide",
    "Provider",
    "SemanticRole",
]
