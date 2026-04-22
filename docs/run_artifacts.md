# Run Artifacts

A `RunArtifact` is the canonical JSON record of one runner execution. It is the single source of truth for everything that happened: the input, the trace, the output, the usage, and any errors.

Everything downstream — deterministic checks, the judge, hybrid aggregation — reads from this artifact. Nothing mutates it.

---

## Top-level structure

```json
{
  "schema_version": 1,
  "identity": {
    "run_id": "run_001",
    "case_id": "llm_probe_tool_example",
    "suite_id": "llm_probe_examples",
    "run_profile_id": "llm_probe_examples",
    "runner_type": "llm_probe",
    "run_fingerprint": "a3f8c2..."
  },
  "status": "success",
  "request": {
    "requested_model": "minimax/minimax-m2.7",
    "gateway": "openrouter",
    "execution_parameters": { "temperature": 0, "max_tokens": 768 }
  },
  "provider": {
    "provider_name": "Minimax",
    "provider_model_id": "minimax-m2.7",
    "finish_reason": "stop"
  },
  "timing": {
    "started_at": "2026-04-22T10:00:00Z",
    "completed_at": "2026-04-22T10:00:12Z",
    "duration_seconds": 12.3
  },
  "usage": {
    "input_tokens": 580,
    "output_tokens": 120,
    "total_tokens": 700,
    "cost_usd": 0.00018
  },
  "trace": [...],
  "output_artifacts": [],
  "runner_metadata": {}
}
```

---

## Terminal statuses

| Status | Meaning |
|---|---|
| `success` | The run completed and produced a final response |
| `failed` | The runner encountered an error after the model responded |
| `timed_out` | The run exceeded `timeout_seconds` |
| `invalid` | The provider returned an invalid or unparseable response |
| `provider_error` | The provider returned an error (HTTP 4xx/5xx, quota exceeded, etc.) |

---

## The trace

The `trace` field is an ordered list of events that records exactly what happened during the run. Event types:

| Kind | Description |
|---|---|
| `message` | A message sent to or received from the model (role + content) |
| `tool_call` | A tool call requested by the model (name + arguments) |
| `tool_result` | The result returned after executing the tool |
| `final_output` | The model's final response (the last assistant message before stopping) |
| `runner_trace` | Internal runner lifecycle events (retries, errors, etc.) |

Example trace (abbreviated):

```json
[
  {"kind": "message",      "role": "user",      "content": "Use real tools to..."},
  {"kind": "tool_call",    "tool_name": "exec_shell", "arguments": {"command": "printf 'marker\\n'"}},
  {"kind": "tool_result",  "tool_name": "exec_shell", "content": "marker\n", "status": "success"},
  {"kind": "tool_call",    "tool_name": "write_file", "arguments": {"path": "/tmp/out.txt", "content": "marker\n"}},
  {"kind": "tool_result",  "tool_name": "write_file", "content": "written", "status": "success"},
  {"kind": "final_output", "content": "Created /tmp/out.txt with the required content."}
]
```

---

## Usage fields

| Field | Description |
|---|---|
| `input_tokens` | Tokens in the prompt |
| `output_tokens` | Tokens in the completion |
| `total_tokens` | Sum of input + output |
| `reasoning_tokens` | Tokens used for chain-of-thought (if available) |
| `cached_input_tokens` | Cache-hit tokens (if available) |
| `cache_write_tokens` | Tokens written to cache (if available) |
| `cost_usd` | Estimated USD cost (from OpenRouter pricing) |

The raw provider usage payload is preserved separately under `raw_provider_usage` so OpenRouter-specific fields remain inspectable.

---

## OpenClaw evidence (`runner_metadata.openclaw`)

For OpenClaw runs, the `runner_metadata` field contains an `openclaw` block with all the evidence captured from the container execution:

```json
{
  "runner_metadata": {
    "openclaw": {
      "agent_id": "support_agent",
      "container_image": "ghcr.io/openclaw/openclaw:2026.4.15",
      "openclaw_generated_config": {
        "artifact_type": "openclaw_generated_config",
        "uri": "file://run_1.artifacts/openclaw.json"
      },
      "openclaw_workspace_snapshot": {
        "artifact_type": "openclaw_workspace_snapshot",
        "uri": "file://run_1.artifacts/workspace.tar.gz"
      },
      "openclaw_workspace_diff": {
        "artifact_type": "openclaw_workspace_diff",
        "uri": "file://run_1.artifacts/workspace.diff"
      },
      "openclaw_key_output": [
        {
          "artifact_type": "openclaw_key_output",
          "uri": "file://run_1.artifacts/report.md",
          "name": "report.md"
        }
      ],
      "openclaw_logs": {
        "artifact_type": "openclaw_logs",
        "uri": "file://run_1.artifacts/openclaw.log"
      }
    }
  }
}
```

| Evidence field | What it contains |
|---|---|
| `openclaw_generated_config` | The `openclaw.json` generated for this run |
| `openclaw_raw_session_trace` | The full JSON session trace from OpenClaw |
| `openclaw_logs` | Captured stdout/stderr logs from the container |
| `openclaw_workspace_snapshot` | Archive of the workspace at the end of the run |
| `openclaw_workspace_diff` | Diff between the template workspace and the final workspace |
| `openclaw_key_output` | Key output files identified by the runner (list) |

Artifact URIs use `file://` references to files stored in the `run_1.artifacts/` directory next to the artifact JSON.

---

## Storage layout

```text
outputs/runs/suit_{suite_id}/run_profile_{fp6}/
  manifest.json                          ← suite-level manifest
  {model_id}/
    {case_id}/
      manifest.json                      ← case-level manifest (maps repetitions → fingerprints)
      run_1.json                         ← RunArtifact for repetition 1
      run_1.artifacts/                   ← external files referenced by run_1.json
      run_1.fingerprint_input.json       ← normalized payload used to derive the fingerprint
      run_2.json                         ← RunArtifact for repetition 2 (if run_repetitions > 1)
      run_2.artifacts/
      run_2.fingerprint_input.json
```

The case-level `manifest.json` maps repetition indices to their full run fingerprints. It also records `runner_type` and, for OpenClaw runs, `openclaw_agent_id`, so stored campaigns are inspectable without opening each `run_N.json`.

---

## Evaluation output layout

Evaluation results live under a separate tree, scoped by both the run-profile fingerprint and the evaluation fingerprint:

```text
outputs/evaluations/suit_{suite_id}/
  evaluation_profile_{run_fp6}/
    eval_profile_{eval_id}_{eval_fp6}/
      manifest.json                      ← campaign-level manifest
      fingerprint_input.json             ← evaluation fingerprint input
      {model_id}/
        {case_id}/
          manifest.json
          evaluation_result_summary_1.md ← human-readable summary (start here)
          judge_1.prompt.debug.md        ← exact prompt shown to the judge
          raw_outputs/
            judge_1.json                 ← aggregated judge result
            judge_1.prompt.user.json     ← structured subject-view payload
            final_result_1.json          ← FinalEvaluationResult (hybrid score)
```

**Recommended reading order:**

1. `evaluation_result_summary_1.md` — the verdict
2. `judge_1.prompt.debug.md` — what the judge saw
3. `raw_outputs/final_result_1.json` — technical details and dimension resolution
