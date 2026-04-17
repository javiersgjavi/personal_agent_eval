# benchmark-openclaw-llm

Repository for the `personal_agent_eval` evaluation library.

## Status

- Previous code and documentation are preserved under `archive/`
- Internal planning documents live under `internal_docs/`
- The new implementation has started with package bootstrap only
- The canonical configuration format is planned around YAML

## Current Direction

- reusable evaluation framework
- `llm_probe` as the V1 implementation target
- `openclaw` designed as a later extension
- complete execution and evaluation artifacts
- hybrid judging and incremental reuse

## Python Bootstrap

- Install the library in editable mode with `uv sync --group dev`
- The initial public CLI entry point is `pae`
- The package source layout lives under `src/personal_agent_eval/`
- The current bootstrap scope only provides package import, package metadata, and CLI wiring for future domains
