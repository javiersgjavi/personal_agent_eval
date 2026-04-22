# Deterministic Checks

Deterministic checks run directly against the stored `RunArtifact` — no LLM is involved. They are fast, stable, and free, and they produce hard pass/fail signals that the hybrid aggregator can use to ground the judge scores.

Each check declares one or more `dimensions`, telling the aggregator which scoring dimensions its result should influence.

---

## Built-in declarative checks

All declarative checks are defined with `declarative.kind` in the test case.

### `final_response_present`

Passes if the run produced a non-empty final response.

For `openclaw` runs, the check also passes if a readable key workspace output exists even when there is no explicit final output field.

```yaml
deterministic_checks:
  - check_id: response-exists
    dimensions: [task]
    declarative:
      kind: final_response_present
```

---

### `tool_call_count`

Passes if the run recorded exactly the expected number of tool calls.

```yaml
deterministic_checks:
  - check_id: used-three-tools
    dimensions: [process, efficiency]
    declarative:
      kind: tool_call_count
      expected: 3
```

---

### `file_exists`

Passes if a filesystem path exists and is a regular file.

```yaml
deterministic_checks:
  - check_id: output-created
    dimensions: [task]
    declarative:
      kind: file_exists
      path: /tmp/output.txt
```

---

### `file_contains`

Passes if a file exists and contains a required substring.

```yaml
deterministic_checks:
  - check_id: marker-present
    dimensions: [task]
    declarative:
      kind: file_contains
      path: /tmp/output.txt
      text: expected-marker-string
```

---

### `path_exists`

Passes if a filesystem path exists, whether it is a file or a directory.

```yaml
deterministic_checks:
  - check_id: dir-created
    dimensions: [task]
    declarative:
      kind: path_exists
      path: /tmp/my_output_dir
```

---

### `status_is`

Passes if the run's terminal status matches the expected value.

Valid status values: `success`, `failed`, `timed_out`, `invalid`, `provider_error`.

```yaml
deterministic_checks:
  - check_id: run-succeeded
    dimensions: [process]
    declarative:
      kind: status_is
      expected: success
```

---

### `output_artifact_present`

Passes if the run artifact records at least one output artifact reference matching the given `artifact_type`.

```yaml
deterministic_checks:
  - check_id: key-output-present
    dimensions: [task]
    declarative:
      kind: output_artifact_present
      artifact_type: openclaw_key_output
```

---

### `openclaw_workspace_file_present`

For `openclaw` runs only. Passes if a recorded output artifact resolves to a workspace file whose path ends with the given `relative_path`. Optionally also checks that the file contains a specific substring.

```yaml
deterministic_checks:
  - check_id: report-md-created
    dimensions: [task]
    declarative:
      kind: openclaw_workspace_file_present
      relative_path: report.md

  - check_id: report-md-has-marker
    dimensions: [process]
    declarative:
      kind: openclaw_workspace_file_present
      relative_path: report.md
      contains: openclaw-tool-example
```

---

## Summary table

| `kind` | Typical dimensions | Notes |
|---|---|---|
| `final_response_present` | `task`, `process` | Works for both `llm_probe` and `openclaw` |
| `tool_call_count` | `process`, `efficiency` | Exact count check |
| `file_exists` | `task` | Host filesystem path |
| `file_contains` | `task` | Host filesystem path + substring |
| `path_exists` | `task` | File or directory |
| `status_is` | `process` | Matches `RunStatus` values |
| `output_artifact_present` | `task` | Checks `RunArtifact.output_artifacts` |
| `openclaw_workspace_file_present` | `task`, `process` | OpenClaw runs only; checks workspace diff |

---

## Python hook checks

When a check cannot be expressed declaratively, you can implement it as a Python callable. This is the escape hatch for custom logic.

```yaml
deterministic_checks:
  - check_id: custom-check
    dimensions: [task]
    hook:
      path: checks/my_check.py       # relative to test.yaml
      callable_name: check_output
```

Or using an importable module:

```yaml
deterministic_checks:
  - check_id: custom-check
    dimensions: [task]
    hook:
      import_path: mypackage.checks.output_check
      callable_name: check_output
```

`import_path` and `path` are mutually exclusive.

!!! warning "Security policy"
    Python hook checks are disabled by default. To enable them, set `security_policy.allow_local_python_hooks: true` in the evaluation profile. This setting exists because hooks execute arbitrary code during evaluation.

---

## How dimensions feed aggregation

The `dimensions` list on each check tells the aggregator which dimension scores can be informed by that check outcome. For example:

- `final_response_present` mapped to `task` — a missing response caps the task score
- `tool_call_count` mapped to `process` and `efficiency` — wrong tool usage penalizes both
- `openclaw_workspace_file_present` mapped to `task` — a missing artifact is a task failure

The aggregator applies the configured policy for each dimension (`judge_only`, `deterministic_only`, or `weighted`) to combine deterministic and judge signals into the final dimension score.

→ [Hybrid evaluation](hybrid_evaluation.md)
