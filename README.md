# Cloud Diagram Compiler

Turn a strict specification — or a plain-language sentence, via your own LLM
key — into a deterministic, professionally laid-out, fully editable draw.io
cloud architecture diagram. Every diagram uses official offline AWS/Azure/GCP
icons, left-to-right flow, and passes the same geometry/spacing/icon
validation gates whether you use the CLI, the MCP server, or the web UI.

## What's in this repo

```text
src/cloud_diagram/   Python compiler: rules, icons, layout, routing, renderer,
                      validation, diagnostics, CLI, MCP server, FastAPI backend
web/                  React + Framer Motion + GSAP frontend for the compiler
config/rules/         The deterministic architecture ruleset (spacing, ports,
                      routing, quality gates) the compiler enforces
assets/icons/         1,531 verified official AWS/Azure/GCP icons, offline
examples/             Generated AWS/Azure/GCP benchmark diagrams
```

## Quick start (CLI, no UI)

```bash
pip install -e .
cloud-diagram render examples/aws-benchmark.spec.json --output my-diagram.drawio
```

No LLM key is required for `render`, `validate`, `explain`, or `icons` —
those work on a hand-written or externally produced `DiagramSpec` JSON/YAML
file. Only `generate` and `plan` (natural-language input) need a planner.

## Configuring your own LLM key

Copy `.env.example` to `.env` and fill in your own values:

```bash
cp .env.example .env
```

```dotenv
CLOUD_DIAGRAM_LLM_ENDPOINT=https://api.openai.com/v1
CLOUD_DIAGRAM_LLM_MODEL=gpt-4o-mini
CLOUD_DIAGRAM_LLM_API_KEY_NAME=OPENAI_API_KEY
OPENAI_API_KEY=sk-your-own-key-here
```

`.env` is loaded automatically by the CLI, the MCP server, and the web
backend. It's already git-ignored — never commit a real key. Any
OpenAI-compatible endpoint works (OpenAI, Groq, OpenRouter, a local Ollama
server, etc.), not just OpenAI itself.

```bash
cloud-diagram generate "a serverless API with a queue-backed worker and a database" \
  --provider aws --output generated.drawio
```

## Running the web UI

The web UI is a thin layer over the same compiler — it calls the exact same
validated pipeline as the CLI, just over HTTP with an animated island-card
frontend.

**Backend** (FastAPI):

```bash
pip install -e ".[web]"
uvicorn cloud_diagram.web.app:app --host 127.0.0.1 --port 8000
```

**Frontend** (React + Vite):

```bash
cd web
npm install
npm run dev
```

Open `http://localhost:5173`. The dev server proxies `/api/*` to
`http://127.0.0.1:8000` by default (override with `VITE_API_PROXY_TARGET`).

Each visitor can paste their own API key directly into the UI — it is sent
only with that one generate request and is never stored server-side, logged,
or persisted anywhere. If you don't have a key, you can still browse the
offline icon registry and use the CLI's `render`/`validate` on a hand-written
spec.

## MCP server

```bash
cloud-diagram-mcp
```

Exposes `compile_diagram_spec`, `render_diagram_spec`, `validate_cloud_diagram`,
`search_local_icons`, `explain_diagram_layout`, and `generate_cloud_diagram`
as MCP tools over stdio.

## Determinism and quality guarantees

Every diagram — regardless of entry point — passes through the same
deterministic pipeline: strict schema validation → semantic icon resolution →
layered layout → orthogonal routing → draw.io rendering → independent
geometry/output validation. Identical input always produces byte-identical
output. See `config/rules/cloud-architecture.yaml` for the full ruleset and
`docs/implementation-plan.md` for the architecture rationale.

## License and icon attribution

This project's code is provided as-is. Bundled AWS, Azure, and GCP icons
remain subject to each provider's own icon usage terms (see
`assets/vendor/*/TERMS.txt`); those terms apply to any diagram you generate
and redistribute.
