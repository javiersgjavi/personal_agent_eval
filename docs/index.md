# personal_agent_eval

`personal_agent_eval` is a reusable evaluation framework for LLM and agent-style systems.

It is designed around:

- declarative YAML configuration
- canonical run artifacts
- deterministic evaluation
- judge-based semantic evaluation
- hybrid final aggregation
- incremental reuse through fingerprints and storage
- reporting from structured workflow results

V1 is centered on `llm_probe`. The architecture already reserves space for a later
`openclaw` runner.

## What Exists Today

The current implementation already includes:

- config loading and validation
- case and suite discovery
- `llm_probe` execution
- canonical run artifacts
- deterministic evaluation
- judge orchestration
- hybrid aggregation
- fingerprints and storage
- workflow orchestration in `pae`
- structured reporting (cost split, latency, optional score/cost chart PNG)

## Read This Next

- [Getting started](getting_started.md)
- [Config Model](config_model.md) — visual overview of how the four config types relate
- [Configuration](configuration.md)
- [Run artifacts](run_artifacts.md)
- [Judge results](judge_results.md)
- [Hybrid evaluation](hybrid_evaluation.md)
- [Reporting](reporting.md)
- [Minimal llm_probe example](examples/minimal_llm_probe.md)
