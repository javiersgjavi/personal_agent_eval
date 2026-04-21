# Judge Results

Judge orchestration consumes an existing `RunArtifact` and produces a separate evaluation
surface. It does not mutate the run artifact.

When building the judge prompt, the framework no longer embeds a near-raw copy of the
`RunArtifact`. Instead it builds a normalized **subject view** with three sections:

- `evaluation_target`
- `subject_response`
- `execution_evidence`

This strips structured subject-model identity and noisy runner metadata, while preserving the
observable evidence the judge actually needs: task messages, final output, visible assistant
messages, tool calls/results, deterministic-check summaries, material failures, and relevant
artifacts. For OpenClaw runs, runner-specific evidence is summarized into the same normalized
shape instead of exposing raw `file://` references or large opaque blobs.

The judge still receives two messages:

1. a `system` prompt with the scoring contract
2. a `user` prompt rendered as human-readable text from the structured subject view

The structured subject view is persisted separately for reproducibility, but the provider-facing
`user` message is the rendered text form.

## Default system prompt

The judge **system** message (instructions to return JSON with `summary` first, then
`dimensions`, where each dimension carries `evidence` and `score`) is resolved in this order:

1. **`judge_system_prompt`** in the evaluation profile YAML (multiline string; lines joined with spaces), or
2. **`judge_system_prompt_path`** in the same YAML (path to a UTF-8 `.txt` file, relative to that YAML), or
3. Otherwise, if the profile is loaded from disk, the shared default file
   **`prompts/judge_system_default.txt` relative to that YAML**.

Recommended project layout:

- `configs/evaluation_profiles/<profile_id>.yaml`
- `configs/evaluation_profiles/prompts/judge_system_default.txt`

In this repository, profiles also set `judge_system_prompt_path: prompts/judge_system_default.txt`
explicitly so the source is visible to the user inside the YAML itself. The evaluation fingerprint
includes a hash of the resolved prompt text, so changing the prompt or the referenced file changes
the evaluation campaign identity.

The top-level evaluation `manifest.json` also stores the exact resolved `judge_system_prompt`
string that was sent to the judge, plus its source descriptor, so each evaluation campaign keeps a
human-readable record of the prompt that was actually used.

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
  "summary": "The answer completed the task cleanly.",
  "dimensions": {
    "task": {
      "evidence": ["Created the expected output."],
      "score": 8.0
    },
    "process": {
      "evidence": ["The trace completed without interruption."],
      "score": 7.0
    },
    "autonomy": {
      "evidence": [],
      "score": 7.5
    },
    "closeness": {
      "evidence": [],
      "score": 6.5
    },
    "efficiency": {
      "evidence": [],
      "score": 6.0
    },
    "spark": {
      "evidence": [],
      "score": 6.0
    }
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
