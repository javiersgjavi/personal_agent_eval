# Deterministic Checks

This page documents the deterministic checks currently implemented in
`personal_agent_eval`.

Deterministic checks run directly against the canonical `RunArtifact`. They are separate from
judge scoring and are intended to be stable, auditable signals for the hybrid aggregation step.

Each check can declare one or more `dimensions`, which tells the hybrid aggregator which score
dimensions the result should influence.

## Built-in Declarative Checks

| `kind` | What it checks | Typical dimensions |
|---|---|---|
| `final_response_present` | The run produced a non-empty final response. For `openclaw`, the evaluator also accepts the last assistant message or a readable key workspace output if there is no explicit final output. | `process` |
| `tool_call_count` | The run recorded exactly the expected number of tool calls. | `process`, `efficiency` |
| `file_exists` | A filesystem path exists and is a regular file. | `task` |
| `file_contains` | A file exists and contains a required substring. | `task` |
| `path_exists` | A filesystem path exists, whether file or directory. | `task` |
| `status_is` | The terminal run status matches the expected status. | `process` |
| `output_artifact_present` | The run artifact records a matching external output artifact reference. | `task` |
| `openclaw_workspace_file_present` | For `openclaw` runs only, a recorded output artifact resolves to a workspace file whose path ends with the given relative path; optionally checks file text contents too. | `task` |

## Python Hooks

Deterministic checks can also be implemented as custom Python hooks. That is the escape hatch
for checks that cannot be expressed declaratively.

Supported hook fields:

| Field | Meaning |
|---|---|
| `import_path` | Import a module by dotted path |
| `path` | Load a local Python file relative to `test.yaml` |
| `callable_name` | Callable to execute inside the module or file |

`import_path` and `path` are mutually exclusive.

## How They Feed Aggregation

The `dimensions` field on each deterministic check tells the hybrid aggregator which
dimension scores can be derived from that check outcome. For example:

- `final_response_present` maps to `process`
- `tool_call_count` maps to `process` and `efficiency`
- `file_exists` maps to `task`

If you want the exact mapping logic, see
[aggregation/aggregator.py](/home/javier/Projects/benchmark-openclaw-llm/src/personal_agent_eval/aggregation/aggregator.py)
and the deterministic evaluator in
[deterministic/evaluator.py](/home/javier/Projects/benchmark-openclaw-llm/src/personal_agent_eval/deterministic/evaluator.py).
