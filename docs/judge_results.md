# Judge Results

Judge orchestration consumes an existing `RunArtifact` and produces a separate evaluation
surface. It does not mutate the run artifact.

When building the judge prompt, the framework embeds a **copy** of the run artifact from which
**structured subject-model identity is omitted** (keys removed, not replaced with placeholders):
for example `request.requested_model`, `request.metadata.model_selection`, `provider.provider_model_id`,
`runner_metadata`, and provider-usage fields that echo a model id. The canonical artifact on disk
is unchanged. Free-form text inside assistant messages could still mention a model name; only
structured metadata is stripped.

## Two Layers

V1 keeps two judge result layers:

1. raw judge attempt results
2. normalized logical iteration results

This distinction matters because one logical repetition may require retries.

## Logical Repetitions And Retries

If a judge is configured for three repetitions, the system preserves those three logical
iterations even if one of them retries internally.

Example:

```json
{
  "configured_repetitions": 3,
  "iterations": [
    {"repetition_index": 0, "status": "success"},
    {"repetition_index": 1, "status": "success"},
    {"repetition_index": 2, "status": "failed"}
  ]
}
```

If repetition `2` retried three times before failing, the raw layer still keeps each attempt,
while the normalized layer still shows one logical iteration with status `failed`.

## Normalized Iteration Shape

```json
{
  "judge_name": "primary_judge",
  "judge_model": "minimax/minimax-m2.7",
  "repetition_index": 0,
  "status": "success",
  "dimensions": {
    "task": 8.0,
    "process": 7.0,
    "autonomy": 7.5,
    "closeness": 6.5,
    "efficiency": 6.0,
    "spark": 6.0
  },
  "summary": "The answer completed the task cleanly.",
  "evidence": {
    "task": ["Created the expected output."],
    "process": ["The trace completed without interruption."],
    "autonomy": [],
    "closeness": [],
    "efficiency": [],
    "spark": []
  },
  "warnings": [],
  "raw_result_ref": "raw_001"
}
```

## Iteration Statuses

V1 normalized judge iterations use:

- `success`
- `failed`
- `invalid_output`
- `provider_error`
- `timed_out`

If the output is structurally valid but evidence is incomplete, the iteration remains
`success` and records warnings.

## Aggregated Judge Result

Successful logical iterations are aggregated into one judge result.

V1 uses `median` as the default aggregation method across successful iterations.

Example:

```json
{
  "judge_name": "primary_judge",
  "judge_model": "minimax/minimax-m2.7",
  "aggregation_method": "median",
  "configured_repetitions": 3,
  "successful_iterations": 2,
  "failed_iterations": 1,
  "used_repetition_indices": [0, 1],
  "excluded_repetition_indices": [2],
  "dimensions": {
    "task": 7.5,
    "process": 7.0,
    "autonomy": 7.5,
    "closeness": 6.0,
    "efficiency": 6.5,
    "spark": 6.0
  },
  "warnings": [
    "Excluded non-successful repetitions from aggregation: 2."
  ]
}
```

This aggregated judge result is still not the final evaluation result. Hybrid aggregation is a
separate layer.

## Related Reading

- [Run artifacts](run_artifacts.md)
- [Hybrid evaluation](hybrid_evaluation.md)
