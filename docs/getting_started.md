# Getting Started

This page shows the minimal mental model for running V1 of `personal_agent_eval`.

## Core Files

V1 uses four YAML file types:

1. `cases/<case_id>/test.yaml`
2. `suites/<suite_id>.yaml`
3. `run_profiles/<profile_id>.yaml`
4. `evaluation_profiles/<profile_id>.yaml`

They answer four different questions:

- `test.yaml`: what is the case
- `suite.yaml`: which cases and models should be grouped together
- `run_profile.yaml`: how should execution run
- `evaluation_profile.yaml`: how should results be judged and aggregated

## Minimal Workflow

The intended V1 flow is:

1. define one or more cases
2. define a suite that selects those cases
3. define a run profile for execution behavior
4. define an evaluation profile for judges and hybrid aggregation
5. execute the workflow through `pae`

V1 now exposes these orchestration commands:

- `pae run`
- `pae eval`
- `pae run-eval`
- `pae report`

Minimal examples:

```bash
pae run \
  --suite suites/example_suite.yaml \
  --run-profile run_profiles/default.yaml

pae eval \
  --suite suites/example_suite.yaml \
  --run-profile run_profiles/default.yaml \
  --evaluation-profile evaluation_profiles/default.yaml

pae run-eval \
  --suite suites/example_suite.yaml \
  --run-profile run_profiles/default.yaml \
  --evaluation-profile evaluation_profiles/default.yaml

pae report \
  --suite suites/example_suite.yaml \
  --run-profile run_profiles/default.yaml \
  --evaluation-profile evaluation_profiles/default.yaml
```

The CLI now renders human-readable reporting by default and can also emit structured JSON
with `--output json`.

Example:

```bash
pae run-eval \
  --suite suites/example_suite.yaml \
  --run-profile run_profiles/default.yaml \
  --evaluation-profile evaluation_profiles/default.yaml \
  --output json
```

The reporting layer is a pure consumer of structured workflow results and can render:

- per-model per-case tables
- per-model summaries
- JSON report payloads
- basic ASCII charts

## Minimal Repository Shape

```text
cases/
  example_case/
    test.yaml
suites/
  example_suite.yaml
run_profiles/
  default.yaml
evaluation_profiles/
  default.yaml
```

## Minimal Output Mental Model

One run produces a canonical run artifact:

```json
{
  "run_id": "run_001",
  "case_id": "example_case",
  "runner_type": "llm_probe",
  "status": "success"
}
```

Deterministic evaluation produces structured check results:

```json
{
  "case_id": "example_case",
  "run_id": "run_001",
  "summary": {
    "passed_checks": 2,
    "failed_checks": 0
  }
}
```

Judge orchestration produces per-iteration and aggregated judge outputs:

```json
{
  "judge_name": "primary_judge",
  "configured_repetitions": 3,
  "successful_iterations": 3,
  "aggregation_method": "median"
}
```

Hybrid aggregation produces the final evaluation result:

```json
{
  "case_id": "example_case",
  "run_id": "run_001",
  "deterministic_dimensions": {
    "task": 10.0,
    "process": 10.0
  },
  "judge_dimensions": {
    "task": 8.0,
    "process": 7.0,
    "autonomy": 7.5,
    "closeness": 6.5,
    "efficiency": 6.0,
    "spark": 6.0
  },
  "final_dimensions": {
    "task": 8.6,
    "process": 8.2,
    "autonomy": 7.5,
    "closeness": 6.5,
    "efficiency": 6.0,
    "spark": 6.0
  },
  "final_score": 7.13
}
```

CLI orchestration already produces per-`model_id` and per-`case_id` workflow results, and the
CLI can present them either as terminal reporting or as structured JSON.

## Important V1 Rules

- `llm_probe` is the implemented runtime target
- automated tests should stay mocked wherever possible
- OpenRouter may be used for tiny, deliberate smoke tests only
- judge output and deterministic output stay separate from the final hybrid result
- the judge is the default prevailing source unless aggregation config says otherwise

## Next Reading

- [Configuration](configuration.md)
- [Judge results](judge_results.md)
- [Hybrid evaluation](hybrid_evaluation.md)
- [Reporting](reporting.md)
- [Minimal llm_probe example](examples/minimal_llm_probe.md)
