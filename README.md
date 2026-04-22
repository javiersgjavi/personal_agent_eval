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

For benchmark-owned OpenClaw runs, the effective model must stay exact: OpenClaw agent configs in
this repo do not support `fallbacks`. If a suite selects `minimax/minimax-m2.7`, the run must not
silently answer with a different provider/model.

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
- fingerprints and reuse rules
- filesystem storage
- workflow orchestration in `pae`
- reporting over structured workflow results

Still pending in V1:

- no remaining mandatory implementation steps in the current V1 plan

## Install

```bash
uv sync --group dev
```

## Running the CLI

If you're working inside this repository, prefer running the CLI via `uv` so the entrypoint is
resolved from the project environment:

```bash
uv run pae --help
```

If you have installed `personal_agent_eval` into an active virtualenv (or globally), you can
also run:

```bash
pae --help
```

## Package Layout

- source code: `src/personal_agent_eval/`
- tests: `tests/`
- configs: `configs/`
- generated artifacts: `outputs/`
- public docs: `docs/`

## Public Docs

- [Docs index](docs/index.md)
- [Getting started](docs/getting_started.md)
- [Config Model](docs/config_model.md)
- [Configuration](docs/configuration.md)
- [Run artifacts](docs/run_artifacts.md)
- [Judge results](docs/judge_results.md)
- [Hybrid evaluation](docs/hybrid_evaluation.md)
- [Reporting](docs/reporting.md)
- [Minimal llm_probe example](docs/examples/minimal_llm_probe.md)
- [Minimal OpenClaw example](docs/examples/minimal_openclaw.md)
- [Runnable examples](docs/examples/runnable_examples.md)

## CLI Commands

V1 currently exposes:

- `pae run`
- `pae eval`
- `pae run-eval`
- `pae report`

The CLI renders human-readable terminal reporting by default and also supports JSON output
with `--output json`.

The config flags accept either explicit YAML paths or ids discovered from the conventional
workspace directories. For example, these are equivalent:

```bash
uv run pae run-eval \
  --suite configs/suites/example_suite.yaml \
  --run-profile configs/run_profiles/default.yaml \
  --evaluation-profile configs/evaluation_profiles/default.yaml

uv run pae run-eval \
  --suite example_suite \
  --run-profile default \
  --evaluation-profile default
```

## Documentation Site

The repository now includes an `mkdocs` configuration. MkDocs lives in the optional `docs`
dependency group, so use:

```bash
uv sync --group docs
uv run --group docs mkdocs serve
```

(`uv run mkdocs serve` alone will fail if `mkdocs` is not installed in the default environment.)

## Notes

- historical benchmark material remains under `archive/` for reference only
- internal planning lives under `internal_docs/` and is not part of the public library docs
- use the shipped example campaigns if you want a small runnable benchmark:
  - `uv run pae run-eval --suite llm_probe_examples --run-profile llm_probe_examples --evaluation-profile judge_gpt54_mini`
  - `uv run pae run-eval --suite openclaw_examples --run-profile openclaw_examples --evaluation-profile judge_gpt54_mini`
- generated `outputs/` are local runtime artifacts and are not meant to be committed
