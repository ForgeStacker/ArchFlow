# Professional Cloud Architecture Diagram Tool — Implementation Plan

## 1. Product objective

Build a deterministic Python tool that converts a natural-language cloud architecture request into a professional, editable draw.io diagram. Every architecture follows a mandatory left-to-right flow. The tool must use an offline, semantically indexed icon catalog and an enforceable layout ruleset so repeated inputs do not produce random icons, spacing, or connector paths.

The system is a diagram compiler, not an XML-generating chatbot:

```text
User request or DiagramSpec
  -> semantic planner
  -> validated DiagramSpec
  -> architecture rules
  -> icon resolution
  -> graph layout
  -> connector routing
  -> draw.io rendering
  -> quality validation
  -> .drawio output
```

## 2. Core principles

1. **Separate meaning from rendering.** The LLM identifies components, groups, relationships, and intent; it never selects files, calculates coordinates, routes edges, or writes draw.io XML.
2. **Deterministic by default.** The same specification, icon registry, and ruleset must produce the same canonical graph and layout.
3. **Offline assets.** Rendering resolves local SVGs by canonical service ID and embeds them into draw.io XML as data URIs. Generated diagrams must not depend on filesystem paths or remote image URLs.
4. **Rules over prompt folklore.** Spacing, containment, placement, ports, routing, labels, and arrow semantics are machine-readable configuration validated at startup.
5. **Provider-neutral domain model.** AWS, Azure, GCP, hybrid, and generic infrastructure use the same `DiagramSpec`; provider behavior is implemented through profiles.
6. **Explainable decisions.** The compiler records why an icon, group, rank, port, or route was selected.
7. **Safe LLM integration.** API keys come only from environment variables. A local-model adapter permits fully offline planning.

## 3. Initial technology choices

- Python 3.12 or later
- Pydantic v2 for domain models and strict validation
- FastMCP for the MCP interface
- Typer for the CLI
- lxml for SVG and draw.io XML processing
- NetworkX for graph analysis
- Graphviz as the initial deterministic hierarchical layout adapter
- Optional ELK adapter behind the same layout protocol
- httpx-based provider adapters for LLM APIs
- `platformdirs` for user-level configuration and cache locations
- YAML rules loaded into typed Pydantic models

Pin exact dependency versions when project packaging is created. Keep the compiler core independent of MCP, CLI, and any specific LLM provider.

## 4. Proposed project structure

```text
assets/
  cloud-icons/                 # downloaded source assets and provenance
  icons/                       # normalized runtime SVG catalog
    registry.json
    aws/<category>/*.svg
    azure/<category>/*.svg
    gcp/<category>/*.svg
config/
  rules/
    cloud-architecture.yaml
  providers/
    aws.yaml
    azure.yaml
    gcp.yaml
docs/
  implementation-plan.md
schemas/
  diagram-spec.schema.json
  icon-registry.schema.json
src/cloud_diagram/
  domain/
    models.py
    enums.py
  planner/
    base.py
    prompt.py
    structured_output.py
    providers/
  icons/
    compiler.py
    registry.py
    resolver.py
    embedder.py
  rules/
    models.py
    loader.py
    engine.py
  graph/
    builder.py
    ranking.py
    ordering.py
  layout/
    base.py
    graphviz.py
    elk.py
    geometry.py
  routing/
    orthogonal.py
    ports.py
    labels.py
  renderers/
    drawio.py
    styles.py
  validation/
    semantic.py
    geometry.py
    output.py
  diagnostics/
    report.py
  mcp/
    server.py
  cli.py
  settings.py
```

## 5. Domain contracts

### 5.1 DiagramSpec

The planner must return a strict, versioned `DiagramSpec` containing:

- diagram ID, title, type, and provider scope; flow direction is the compiler-owned constant `left_to_right`, not a planner-selectable field
- groups with stable IDs, types, parents, labels, and optional placement hints
- nodes with stable IDs, canonical service IDs, roles, labels, group membership, and availability metadata
- edges with source, target, semantic kind, direction, label, protocol, criticality, and optional routing hints
- user constraints and explicit overrides

Unknown fields are rejected. Node and group IDs must be unique and stable. All references must resolve before layout.

### 5.2 LayoutResult

Layout output contains integer pixel geometry only:

- canvas bounds
- group rectangles and hierarchy
- node rectangles
- selected source and target ports
- ordered orthogonal edge segments
- edge-label rectangles
- quality metrics and warnings

### 5.3 Precedence

Rules are resolved in this order:

```text
explicit user constraint
  > per-diagram override
  > selected template
  > provider profile
  > cloud-architecture base rules
```

An override must be recorded in diagnostics. No later stage may silently ignore it.

## 6. Implementation phases

### Phase 0 — Foundation and contracts

Deliverables:

- Python package skeleton and locked development environment
- Pydantic models for `DiagramSpec`, rules, icon metadata, geometry, routes, and diagnostics
- JSON Schema export for externally produced specifications
- configuration loader with rule precedence and actionable validation errors
- stable ID and canonical serialization utilities

Acceptance criteria:

- invalid references, duplicate IDs, unknown fields, and unsupported edge kinds fail before layout
- equivalent input objects produce identical canonical JSON
- ruleset startup errors include the exact field path and invalid value

### Phase 1 — Offline icon compiler and registry

Current asset reality:

- Azure assets are already individual categorized SVG files
- AWS and GCP assets are primarily draw.io stencil XML, not standalone SVGs
- sidebar JavaScript is source integration metadata and must not be used as the runtime registry

Deliverables:

- extract/render pipeline that creates normalized individual AWS and GCP SVGs
- Azure SVG normalization pipeline
- canonical paths: `<provider>/<category>/<service-id>.svg`
- registry entries containing stable ID, provider, category, display name, aliases, source, dimensions, deprecation state, and checksum
- collision detection and an alias review report
- SVG safety checks and deterministic normalization

Icon resolution order:

1. canonical service ID
2. provider-scoped exact alias
3. provider-scoped normalized display name
4. category-specific generic icon
5. provider generic-resource icon
6. neutral generic component

Acceptance criteria:

- no runtime dependency on sidebar JavaScript or remote icon URLs
- every registry path exists and every checksum verifies
- ambiguous aliases fail with candidates instead of choosing randomly
- embedded output renders without network access

### Phase 2 — Rules engine and architecture normalization

Deliverables:

- typed loader for `config/rules/cloud-architecture.yaml`
- provider profiles for AWS, Azure, and GCP terminology and containment
- semantic-role inference: entrypoint, gateway, compute, worker, queue, datastore, cache, identity, observability, external system
- normalization passes for implicit groups, shared gateways, availability zones, and repeated services
- explicit rule trace explaining each structural transformation

Acceptance criteria:

- transformations are ordered and deterministic
- user constraints always win over inferred provider conventions
- invalid containment cycles and illegal group membership fail before layout
- no rule mutates the specification without a diagnostic trace entry

### Phase 3 — LLM semantic planner

Deliverables:

- provider-neutral planner protocol
- adapters for OpenAI-compatible, Anthropic, Gemini, and local models as configured
- strict structured-output request using the exported DiagramSpec schema
- temperature zero, bounded retries, timeout, cancellation, and token controls
- one optional repair call only after schema failure
- prompt-injection-resistant separation between user content and compiler policy
- sensitive-data warning and optional redaction hooks

Acceptance criteria:

- the planner cannot emit coordinates, SVG paths, style strings, or draw.io XML
- API keys never appear in config, logs, diagnostics, or output
- invalid model responses produce actionable errors or a validated repair
- direct DiagramSpec input bypasses the LLM entirely

### Phase 4 — Graph construction, ranking, and ordering

Deliverables:

- graph builder with typed nodes, groups, edges, and boundary relationships
- cycle detection and feedback-edge classification
- deterministic layer/rank assignment based on semantic role and data flow
- crossing-minimizing node order with stable tie-breakers
- hub insertion for high fan-in/fan-out relationships when permitted by rules
- provider-aware group hierarchy construction

Acceptance criteria:

- stable input order does not affect final node ordering
- entrypoints, processing tiers, asynchronous boundaries, and datastores follow configured rank policy
- feedback edges are explicitly classified before routing
- synthetic hubs use predictable IDs and are included in diagnostics

### Phase 5 — Layout and spacing

Deliverables:

- `LayoutEngine` protocol
- Graphviz adapter with fixed configuration and deterministic seed/order
- optional ELK adapter without changes to domain or renderer contracts
- grid snapping, container sizing, label-aware node sizing, rank spacing, sibling spacing, and nested-group padding
- bounded compaction pass that never violates minimum clearances

Acceptance criteria:

- zero node-node overlaps
- zero node-container-title overlaps
- every child is inside its parent client area
- minimum gaps from the active ruleset are respected
- layout is identical for repeated runs with identical inputs and engine version

### Phase 6 — Ports, arrows, and orthogonal routing

Deliverables:

- deterministic port assignment based on direction and semantic relationship
- obstacle-aware Manhattan routing
- source/target stubs, minimum segment length, bend penalties, crossing penalties, and parallel-edge separation
- outer-perimeter routing for feedback edges
- fan-out/fan-in trunking where the rules permit it
- longest-segment edge-label placement
- residual-crossing jump style in draw.io output

Acceptance criteria:

- zero edge-node intersections except at assigned terminal ports
- zero edge-container-title intersections
- no label sits on a node, title, bend, arrowhead, or another label
- parallel edges remain visually distinct
- arrows consistently communicate synchronous, asynchronous, data, dependency, and bidirectional semantics
- route quality metrics are emitted for bends, crossings, and total length

### Phase 7 — Draw.io renderer

Deliverables:

- mxGraph XML renderer using lxml, not string concatenation
- embedded and deduplicated SVG data URIs
- stable cell IDs, parent-child containment, layers, metadata, and tags
- provider/group/node/edge style factories
- automatic canvas sizing and page settings
- `.drawio` output plus optional uncompressed XML for diagnostics

Acceptance criteria:

- XML is well formed and opens as an editable draw.io diagram
- every edge includes valid geometry and references existing terminals
- external files and remote URLs are absent from production output
- canonical render of identical LayoutResult has identical XML

### Phase 8 — Quality validator and repair loop

Deliverables:

- semantic validation: connectivity, unresolved services, invalid containment, isolated critical components
- geometry validation: overlaps, clipping, minimum spacing, segment intersections, labels, excessive bends
- visual quality score with hard failures and soft warnings
- deterministic local repair passes for spacing, ordering, ports, and routes
- human-readable JSON diagnostics

Repair order:

1. expand local spacing
2. reorder peers within rank
3. change eligible ports
4. reroute affected edges
5. expand parent containers/canvas
6. fail with diagnostics if hard constraints remain

The LLM is never used for geometric repair.

Acceptance criteria:

- all hard gates in the active ruleset pass before a diagram is reported successful
- repair terminates at a configured iteration limit
- failure reports identify exact objects and violated rules

### Phase 9 — CLI and MCP interfaces

CLI commands:

```text
cloud-diagram plan
cloud-diagram generate
cloud-diagram render
cloud-diagram validate
cloud-diagram icons search
cloud-diagram icons verify
cloud-diagram explain
```

MCP tools:

```text
generate_cloud_diagram
compile_diagram_spec
render_diagram_spec
validate_cloud_diagram
search_local_icons
explain_diagram_layout
```

Acceptance criteria:

- CLI and MCP invoke the same application services
- every command supports explicit input/output paths and machine-readable diagnostics
- cancellation and errors do not leave partial output files
- generation writes through a temporary file and atomically promotes valid output

### Phase 10 — Professional templates and release hardening

Initial templates:

- three-tier web application
- event-driven/serverless platform
- container/Kubernetes platform
- data ingestion and analytics pipeline
- multi-region high availability
- hybrid network connectivity
- CI/CD deployment platform
- observability and security overlay

Release gates:

- reference AWS, Azure, GCP, and mixed-cloud diagrams satisfy all hard quality gates
- generated files open in draw.io and remain editable
- offline rendering succeeds with network access blocked
- source/license metadata accompanies normalized icons
- installation, configuration, and API-key behavior are documented

## 7. Geometric quality contract

The base ruleset in `config/rules/cloud-architecture.yaml` is normative. At minimum, successful output must satisfy:

- node overlap count: `0`
- node/title intersection count: `0`
- edge/node intersection count excluding terminals: `0`
- edge/title intersection count: `0`
- label overlap count: `0`
- unsatisfied minimum spacing constraints: `0`
- unresolved icon count: `0` unless fallback is explicitly allowed
- maximum normal edge bends: `5`
- repeated-run geometry drift: `0 px`

Crossings are minimized rather than universally forbidden because some graphs are non-planar. Every residual crossing must use the configured jump style and be included in diagnostics.

## 8. Observability and diagnostics

Each generation should optionally emit a report containing:

- planner provider/model and schema version, excluding secrets
- ruleset ID/version and effective overrides
- selected icons and resolution reasons
- inferred groups/roles and transformation trace
- layout engine/version and deterministic settings
- per-edge ports, route, bends, length, and crossings
- hard-gate results, warnings, repairs, and final quality score

## 9. Definition of done

The first production-ready release is complete when a user can provide either natural language or a DiagramSpec and receive an editable `.drawio` file that:

1. uses deterministic, locally resolved cloud icons;
2. follows explicit provider and architecture structure rules;
3. has consistent spacing, containment, ports, arrows, and labels;
4. contains no unresolved remote resources;
5. passes the geometry and output quality gates;
6. can explain every significant semantic and geometric decision;
7. is reproducible from the same input, rules, assets, and engine versions.
