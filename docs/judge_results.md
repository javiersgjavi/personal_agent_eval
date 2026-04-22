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

## Judge scoring semantics (dimensions + scale)

Judge outputs use a 0–10 scoring scale per dimension. Scores are meant to be comparable across
cases and runs; use the anchors below to calibrate.

### 0–10 score scale

- **10**: Fully satisfies the task intent and all hard constraints; no meaningful issues.
- **8–9**: Clear success with only minor issues (small omissions, minor style/clarity problems).
- **6–7**: Partial success; notable issues, missing pieces, or ambiguity, but some useful progress.
- **3–5**: Mostly unsuccessful; major gaps or multiple expectation failures.
- **1–2**: Near-total failure; little relevant progress.
- **0**: No attempt, empty output, or completely irrelevant output.

### Objective vs subjective signals

- **Deterministic checks are objective**: when the prompt includes a deterministic summary/check
  list, treat failed checks as strong evidence that relevant expectations were not met.
- **Hard vs soft expectations**:
  - **Hard** expectations are required. Failing any hard expectation should strongly cap the
    relevant dimension scores (typically \( \le 4 \) for the impacted dimensions).
  - **Soft** expectations are preferences. Missing them should reduce scores modestly.
- **Do not guess missing facts**: if the artifact does not show evidence, record uncertainty and
  avoid inventing completion.

### Dimension definitions

The six dimensions below are the canonical judge dimensions for V1:

- **task**: Quality and correctness of the final result relative to the requested task outcome.
  This is primarily about *what* was delivered.
- **process**: Compliance with required procedure and artifacts (e.g., required file outputs,
  required tool usage, required steps) and whether execution evidence supports completion.
  This is primarily about *how* the outcome was produced.
- **autonomy**: Ability to make progress without needing external intervention or unnecessary
  back-and-forth. Penalize stalls, avoidable clarification loops, or dependence on manual steps.
- **closeness**: Faithfulness to the request and evidence. Penalize hallucinations and claims not
  supported by the trace/artifacts, as well as going off-task.
- **efficiency**: Economy of steps and tool calls, and appropriately concise output. Penalize
  wasted actions, redundant tool use, or overly verbose irrelevant text.
- **spark**: Small helpful extras that improve usefulness or clarity *without* violating task
  constraints (e.g., a crisp justification, a robust cross-check, or a small UX touch). Do not
  reward fluff.

## Default system prompt

The judge **system** message (instructions to return JSON with `summary`, `dimensions`, and an
`overall` score, where each assessment carries `evidence` and `score`) is resolved in this order:

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
