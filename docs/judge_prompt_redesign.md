# Judge Prompt Redesign

## Problem

The current judge prompt embeds a large JSON payload with:

- `judge_name`
- `judge_model`
- `case_context`
- `deterministic_summary`
- a mostly raw `run_artifact`

This creates three issues:

1. The judge sees implementation and infrastructure details that are not the subject of the
   evaluation.
2. The prompt spends too many tokens on low-signal metadata.
3. The judge-facing view is not stored as a first-class artifact, even though it is the real
   evaluation input.

## Design Goals

- Make the subject of evaluation explicit.
- Remove irrelevant infrastructure noise.
- Preserve enough evidence for process scoring.
- Reduce prompt size and ambiguity.
- Persist exactly what the judge saw in `outputs`.
- Keep campaign-level reproducibility and fingerprint stability.

## Proposed Prompt Shape

The judge should still receive two messages:

1. `system`: scoring contract and output schema
2. `user`: a compact, evaluation-oriented JSON document

The `user` payload should be reshaped to this:

```json
{
  "schema_version": 2,
  "summary": "A concise overall assessment of the run.",
  "evaluation_target": {
    "task_messages": [
      {"content": "..."}
    ],
    "expectations": {
      "hard": ["..."],
      "soft": ["..."]
    },
    "dimensions": ["task", "process", "autonomy", "closeness", "efficiency", "spark"]
  },
  "subject_response": {
    "final_output": "...",
    "assistant_messages": ["..."],
    "tool_activity_summary": {
      "tool_call_count": 0,
      "tools_used": []
    }
  },
  "execution_evidence": {
    "deterministic_summary": {
      "passed_checks": 0,
      "failed_checks": 0,
      "error_checks": 0,
      "total_checks": 0
    },
    "key_trace_events": [
      {"kind": "message", "role": "assistant", "content": "..."},
      {"kind": "tool_call", "tool_name": "..."},
      {"kind": "tool_result", "tool_name": "...", "status": "success"}
    ],
    "artifacts": [
      {"artifact_type": "key_output", "basename": "report.md", "excerpt": "..."}
    ],
    "material_failures": [
      {"stage": "execution", "message": "..."}
    ]
  },
  "dimensions": {
    "task": {"evidence": ["..."], "score": 7.5},
    "process": {"evidence": ["..."], "score": 7.0},
    "autonomy": {"evidence": ["..."], "score": 6.5},
    "closeness": {"evidence": ["..."], "score": 7.0},
    "efficiency": {"evidence": ["..."], "score": 6.0},
    "spark": {"evidence": ["..."], "score": 5.5}
  }
}
```

## Explicit Removals

The judge prompt should not include these fields:

- `judge_name`
- `judge_model`
- `run_artifact.identity.run_id`
- `run_artifact.identity.run_profile_id`
- `run_artifact.identity.suite_id`
- `run_artifact.request.gateway`
- `run_artifact.request.execution_parameters`
- `run_artifact.request.metadata.requested_runner_config`
- `run_artifact.request.metadata.openclaw.container_image`
- `run_artifact.provider`
- `run_artifact.timing`
- `run_artifact.usage`
- raw `runner_metadata`
- low-level Docker/config/bootstrap logs by default
- local filesystem paths such as `source_path`, temp dirs, and `file://` refs

These fields are useful for debugging and storage, but not as primary evaluation input.

## What The Judge Should See Instead

### 1. Evaluation target

This section should contain only the task definition:

- user/system messages from the case input
- expectation text
- declared dimensions

### 2. Subject response

This section should contain only the outcome produced by the evaluated system:

- terminal run status
- final output if present
- assistant messages if relevant
- small tool-use summary

This makes the evaluated object obvious and separate from runner metadata.

### 3. Execution evidence

This section should contain only evidence needed for process scoring:

- deterministic summary
- filtered trace events
- key output excerpts
- material failures that prevented task completion

This preserves process visibility without drowning the judge in runner internals.

## Filtering Rules

### Keep

- user-visible assistant content
- final output content
- tool calls and tool results when they are semantically relevant
- key generated files and short excerpts
- task-blocking failures
- a compact summary of deterministic checks

### Drop by default

- config generation details
- container image names
- raw environment forwarding details
- workspace materialization events
- registry pull errors unless they directly explain why no answer exists
- repeated stderr noise
- null-heavy metadata blocks
- duplicate evidence already represented elsewhere

### OpenClaw-specific rule

Replace `openclaw_judge_context` with a normalized `execution_evidence` summary:

- `material_failures`
- `key_trace_events`
- `artifacts`

Do not pass raw excerpts like `generated_openclaw_config_excerpt` or large log chunks unless the
run failed before any model output and the failure itself is the only evaluable evidence.

## Prompt Storage

Persist what the judge saw as first-class artifacts next to `judge_N.json`.

Recommended files:

- `judge_1.prompt.debug.md`
- `raw_outputs/judge_1.prompt.user.json`

`raw_outputs/judge_1.json` should remain the raw provider result record.

The new prompt files should be derived from the exact sent payload, not rebuilt later.

## Reproducibility

The judge-facing `user` payload should be fingerprinted.

Recommended additions:

- store a hash of `judge_prompt_user.json` in the evaluation record
- optionally store a hash of `judge_prompt_system.txt`
- keep `judge_system_prompt` in the campaign manifest as today

This preserves the ability to answer two different questions:

- "What instructions governed this evaluation campaign?"
- "What exact evidence packet did this judge invocation see?"

## Migration Path

### Phase 1

- Keep current raw `raw_outputs/judge_1.json`
- Add persisted prompt files and a human-readable summary
- Introduce a builder that produces a normalized judge-facing subject view
- Keep old internal run artifact storage unchanged

### Phase 2

- Switch the judge prompt from raw `run_artifact` to the new normalized view
- Update tests to assert field inclusion/exclusion
- Add fixture coverage for successful runs and infrastructure failures

### Phase 3

- Optionally remove `judge_name` and `judge_model` from the prompt entirely
- Optionally make trace filtering runner-specific via adapters

## Recommended First Implementation

The first implementation should do four things only:

1. Stop embedding `judge_name` and `judge_model` in the `user` prompt payload.
2. Replace `run_artifact` in the prompt with a new `judge_subject_view`.
3. Filter OpenClaw evidence down to response, key outputs, relevant trace, and material failures.
4. Persist `judge_N.prompt.debug.md`, `raw_outputs/judge_N.prompt.user.json`, and an `evaluation_result_summary_N.md` under `outputs/evaluations/...`.

This gives a meaningful reduction in prompt noise without forcing a full storage redesign.
