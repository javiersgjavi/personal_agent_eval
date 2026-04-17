# personal_agent_eval

`personal_agent_eval` is a reusable evaluation library for LLM and agent-style systems.

V1 focuses on `llm_probe` and provides:

- YAML-driven case, suite, run-profile, and evaluation-profile configuration
- canonical run artifacts
- deterministic evaluation
- judge orchestration
- hybrid aggregation
- a Python package under `src/personal_agent_eval/`
- a CLI entrypoint named `pae`

`openclaw` is part of the design, but it is a later runtime extension rather than a V1
execution target.

## Status

Implemented in the current V1 codebase:

- package bootstrap
- canonical config loading and validation
- case and suite discovery
- canonical run artifact models
- `llm_probe` runner
- deterministic evaluation
- judge orchestration
- hybrid aggregation

Still pending in V1:

- fingerprints and reuse rules
- storage layout
- full CLI orchestration
- reporting
- final quality gates

## Install

```bash
uv sync --group dev
```

## Package Layout

- source code: `src/personal_agent_eval/`
- tests: `tests/`
- public docs: `docs/`

## Public Docs

- [Docs index](docs/index.md)
- [Getting started](docs/getting_started.md)
- [Configuration](docs/configuration.md)
- [Run artifacts](docs/run_artifacts.md)
- [Judge results](docs/judge_results.md)
- [Hybrid evaluation](docs/hybrid_evaluation.md)
- [Minimal llm_probe example](docs/examples/minimal_llm_probe.md)

## Documentation Site

The repository now includes an `mkdocs` configuration:

```bash
mkdocs serve
```

or, with `uv`:

```bash
uv run mkdocs serve
```

## Notes

- historical benchmark material remains under `archive/` for reference only
- internal planning lives under `internal_docs/` and is not part of the public library docs
