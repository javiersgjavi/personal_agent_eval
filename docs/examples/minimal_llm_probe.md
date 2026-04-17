# Minimal llm_probe Example

This example shows the smallest realistic V1 shape for one `llm_probe` case.

## Case

`configs/cases/example_case/test.yaml`

```yaml
schema_version: 1
case_id: example_case
title: Example case
runner:
  type: llm_probe
input:
  messages:
    - role: user
      content: Say hello in one sentence.
  attachments:
    - artifacts/context.txt
expectations:
  hard_expectations:
    - text: The answer should contain a greeting.
  soft_expectations:
    - text: The answer should be concise.
deterministic_checks:
  - check_id: final-response-present
    dimensions:
      - process
    declarative:
      kind: final_response_present
tags:
  - smoke
  - llm_probe
metadata:
  owner: qa
```

## Suite

`configs/suites/example_suite.yaml`

```yaml
schema_version: 1
suite_id: example_suite
title: Example suite
models:
  - model_id: minimax_m27
    requested_model: minimax/minimax-m2.7
case_selection:
  include_case_ids:
    - example_case
```

## Run Profile

`configs/run_profiles/default.yaml`

```yaml
schema_version: 1
run_profile_id: default
title: Default run profile
runner_defaults:
  temperature: 0
  retries: 5
execution_policy:
  max_concurrency: 1
  fail_fast: true
```

## Evaluation Profile

`configs/evaluation_profiles/default.yaml`

```yaml
schema_version: 1
evaluation_profile_id: default
title: Default evaluation profile
judges:
  - judge_id: primary_judge
    type: llm_probe
    model: minimax/minimax-m2.7
judge_runs:
  - judge_run_id: primary_judge_default
    judge_id: primary_judge
    repetitions: 3
aggregation:
  method: median
final_aggregation:
  default_policy: judge_only
  dimensions:
    process:
      policy: weighted
      judge_weight: 0.6
      deterministic_weight: 0.4
  final_score_weights:
    task: 0.3
    process: 0.15
    autonomy: 0.2
    closeness: 0.1
    efficiency: 0.15
    spark: 0.1
```

## Output Mental Model

After execution and evaluation, the library should be able to express something like:

```json
{
  "run_artifact": {
    "run_id": "run_001",
    "case_id": "example_case",
    "runner_type": "llm_probe",
    "status": "success"
  },
  "deterministic_result": {
    "summary": {
      "passed_checks": 1,
      "failed_checks": 0
    }
  },
  "judge_result": {
    "aggregation_method": "median",
    "successful_iterations": 3,
    "failed_iterations": 0
  },
  "final_result": {
    "final_score": 7.1
  }
}
```

## Notes

- V1 runtime work is centered on `llm_probe`
- `input.attachments` are injected into the initial prompt for `llm_probe` runs as additional
  `user` messages (they are not tool-driven reads).
- final CLI orchestration is still a later V1 step
- this example is meant to explain the shape of the library, not a fully frozen CLI command
