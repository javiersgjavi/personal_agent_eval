# Configuration Reference

All YAML files must declare `schema_version: 1` at the top. The loader raises an explicit `ConfigError` on any schema violation — there are no silent defaults for required fields.

---

## Quick reference

| Config type | Default path | ID field |
|---|---|---|
| Test case | `configs/cases/<case_id>/test.yaml` | `case_id` |
| Suite | `configs/suites/<suite_id>.yaml` | `suite_id` |
| Run profile | `configs/run_profiles/<profile_id>.yaml` | `run_profile_id` |
| Evaluation profile | `configs/evaluation_profiles/<profile_id>.yaml` | `evaluation_profile_id` |
| OpenClaw agent | `configs/agents/<agent_id>/agent.yaml` + `workspace/` | `agent_id` |

CLI flags (`--suite`, `--run-profile`, `--evaluation-profile`) accept either an explicit YAML path or just the plain ID, which is resolved automatically under the conventional directory.

---

## Test case (`test.yaml`)

Defines one atomic evaluation scenario. The same case can be included in multiple suites and evaluated against multiple models without modification.

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `case_id` | slug | yes | Unique identifier; used as directory name in `outputs/` |
| `title` | string | yes | Human-readable label |
| `runner` | `RunnerConfig` | yes | Runner type and optional case-level overrides |
| `input` | `TestInput` | yes | Messages, attachments, and runner context |
| `expectations` | `Expectations` | no | Hard/soft expectation list for the judge |
| `rubric` | `Rubric` | no | Scored anchors and criteria shown to the judge |
| `deterministic_checks` | list | no | Checks run against the `RunArtifact` without an LLM |
| `tags` | list of strings | no | Free tags; used by `case_selection.include_tags` / `exclude_tags` |
| `metadata` | mapping | no | Arbitrary key/value; not used by the framework |

---

### `runner`

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `"llm_probe"` or `"openclaw"` | yes | Selects the runner implementation |

Any extra fields (e.g. `temperature: 0`) are treated as case-level runner overrides and take precedence over `run_profile.runner_defaults` but are overridden by `run_profile.model_overrides`.

---

### `input`

| Field | Type | Default | Description |
|---|---|---|---|
| `messages` | list of `Message` | `[]` | Ordered message sequence sent to the model |
| `attachments` | list of paths | `[]` | Local files injected as extra user messages |
| `context` | mapping | `{}` | Runner-specific context: tools, openclaw hints, etc. |

All relative paths in `input` resolve relative to the `test.yaml` file.

#### Message

| Field | Type | Required | Description |
|---|---|---|---|
| `role` | `"system"` / `"user"` / `"assistant"` / `"tool"` | yes | Message role |
| `content` | string | one of `content` / `source` | Inline message text |
| `source` | `MessageSource` | one of `content` / `source` | External file reference |
| `name` | string | no | Optional name annotation |

`content` and `source` are mutually exclusive.

#### MessageSource

```yaml
source:
  path: messages/user_prompt.yaml   # relative to test.yaml
  format: yaml                      # optional; auto-detected from extension
```

The referenced file may resolve to a single message object or a list of messages.

#### Attachments

Files in `input.attachments` are injected as additional `user` messages just before the first `user` message:

```
Attached context file: <filename>

--- BEGIN ATTACHMENT <filename> ---
<file content>
--- END ATTACHMENT <filename> ---
```

Attachments are content-addressed in the fingerprint (SHA-256 + byte size), not path-addressed.

#### `input.context.llm_probe`

| Field | Type | Description |
|---|---|---|
| `tools` | list of strings | Tools to expose to the model: `exec_shell`, `write_file`, `read_file`, `web_search`, etc. |

#### `input.context.openclaw`

| Field | Type | Description |
|---|---|---|
| `expected_artifact` | string | Hint for the harness: the filename of the expected output in the workspace |

---

### `expectations`

Shown to the judge as part of the evaluation target. Hard expectations are treated as critical requirements; soft ones are scored with partial credit.

| Field | Type | Description |
|---|---|---|
| `hard_expectations` | list of `Expectation` | Requirements the judge must treat as critical |
| `soft_expectations` | list of `Expectation` | Requirements scored with partial credit |

#### Expectation

| Field | Type | Required | Description |
|---|---|---|---|
| `text` | string | yes | Natural-language expectation statement |
| `weight` | float | no (default `1.0`) | Relative weight within the group |

---

### `rubric`

An optional structured rubric shown to the judge to calibrate scoring. It replaces free-form judge guessing with explicit anchors and criteria.

```yaml
rubric:
  version: 1
  scale:
    min: 0
    max: 10
    anchors:
      "10": All required steps completed correctly and concisely.
      "7": Mostly correct with minor clarity issues.
      "4": Partial completion; missing a required step.
      "0": No attempt, irrelevant output, or empty.
  criteria:
    - name: Tool-grounded correctness
      what_good_looks_like: Uses required tools and reports observed results.
      what_bad_looks_like: Invents results or skips required steps.
    - name: Concise confirmation
      what_good_looks_like: Confirms actions in 2–4 lines.
      what_bad_looks_like: Overly verbose or unclear.
  scoring_instructions: >
    Use this rubric to set overall.score. Cap at ≤ 4 if a hard
    expectation or deterministic check fails.
```

---

### `deterministic_checks`

Each entry is a `DeterministicCheck`:

| Field | Type | Required | Description |
|---|---|---|---|
| `check_id` | slug | yes | Unique within the case |
| `dimensions` | list of dimension names | no | Dimensions this check affects in aggregation |
| `declarative` | `DeclarativeCheck` | one of | Built-in check specification |
| `python_hook` | `PythonHook` | one of | Custom Python callable |

`declarative` and `python_hook` are mutually exclusive.

Valid dimension names: `task`, `process`, `autonomy`, `closeness`, `efficiency`, `spark`.

#### Declarative check kinds

| `kind` | Extra fields | Description |
|---|---|---|
| `final_response_present` | — | Non-empty final output in the trace (also checks last assistant message or workspace output for openclaw) |
| `tool_call_count` | `count` (int) | Exact tool call count |
| `file_exists` | `path` | File exists on host filesystem |
| `file_contains` | `path`, `text` | File exists and contains substring |
| `path_exists` | `path` | Path exists (file or directory) |
| `status_is` | `status` | Terminal run status matches |
| `output_artifact_present` | `artifact_type`? | Run artifact records a matching output artifact |
| `openclaw_workspace_file_present` | `relative_path`, `contains`? | Workspace diff contains the file (OpenClaw only) |

Paths resolve relative to `test.yaml`.

#### PythonHook

```yaml
python_hook:
  path: hooks/my_check.py        # relative to test.yaml (mutually exclusive with import_path)
  # import_path: my_pkg.checks   # dotted import path (mutually exclusive with path)
  callable_name: check_output
```

!!! warning
    Python hooks are disabled by default. Enable them with `security_policy.allow_local_python_hooks: true` in the evaluation profile.

---

### Minimal `test.yaml`

```yaml
schema_version: 1
case_id: my_case
title: My case
runner:
  type: llm_probe
input:
  messages:
    - role: user
      content: What is 2 + 2?
expectations:
  hard_expectations:
    - text: Answers with 4.
deterministic_checks:
  - check_id: response-present
    dimensions: [task]
    declarative:
      kind: final_response_present
```

---

## Suite (`suite.yaml`)

Groups models with a case selection policy to form a benchmark campaign.

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `suite_id` | slug | yes | Unique identifier |
| `title` | string | yes | Human-readable label |
| `models` | list of `ModelConfig` | no | Models to run against the selected cases |
| `case_selection` | `CaseSelection` | no | Filters determining which cases are included |
| `metadata` | mapping | no | Arbitrary annotation bag |

### `models` — ModelConfig

| Field | Type | Required | Description |
|---|---|---|---|
| `model_id` | slug | yes | Local name used in artifact paths and reports |
| `label` | string | no | Human-readable display name |
| `requested_model` | string | no | OpenRouter model string (e.g. `openai/gpt-4o-mini`) |

Any extra fields are passed through to the runner. The `llm_probe` runner resolves the model in this priority order: `requested_model` → `openrouter_model` → `provider` + `model_name` → `model_id`.

### `case_selection`

| Field | Type | Description |
|---|---|---|
| `include_case_ids` | list of strings | Explicit case IDs to include |
| `exclude_case_ids` | list of strings | Explicit case IDs to exclude |
| `include_tags` | list of strings | Include cases that have at least one of these tags |
| `exclude_tags` | list of strings | Exclude cases that have at least one of these tags |

Precedence: `include_case_ids` > tag filters > `exclude_case_ids`. Unknown case IDs in `include_case_ids` are a hard error.

### Example

```yaml
schema_version: 1
suite_id: my_suite
title: My benchmark suite
models:
  - model_id: gpt4o_mini
    requested_model: openai/gpt-4o-mini
    label: GPT-4o mini
  - model_id: minimax_m27
    requested_model: minimax/minimax-m2.7
case_selection:
  include_tags: [smoke]
  exclude_case_ids: [known_flaky_case]
```

---

## Run profile (`run_profile.yaml`)

Controls execution behavior. A SHA-256 fingerprint of the effective settings scopes campaign storage directories — changing any execution parameter produces a new fingerprint and a new directory.

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `run_profile_id` | slug | yes | Unique identifier |
| `title` | string | yes | Human-readable label |
| `runner_defaults` | mapping | no | Default runner settings applied to every case |
| `model_overrides` | mapping | no | Per-model setting overrides (key = `model_id`) |
| `execution_policy` | `ExecutionPolicy` | no | Concurrency and error-handling controls |
| `openclaw` | `OpenClawRunProfile` | no | OpenClaw runtime block (agent, image, timeout) |

### `runner_defaults` / `model_overrides`

Merge order (later wins): `runner_defaults` → `model_overrides[model_id]` → case-level `runner:` fields.

Recognized `llm_probe` fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `temperature` | float 0–2 | provider default | Sampling temperature |
| `top_p` | float 0–1 | provider default | Nucleus sampling |
| `max_tokens` | int | provider default | Max tokens to generate |
| `seed` | int | null | Reproducibility seed |
| `timeout_seconds` | int | `30` | Per-request wall-clock timeout |
| `retries` | int | `5` | Retry attempts on transient failures |
| `max_turns` | int | `8` | Max tool-use turns before forcing a final response |

### `execution_policy`

| Field | Type | Default | Description |
|---|---|---|---|
| `max_concurrency` | int ≥ 1 | `1` | Parallel case executions |
| `run_repetitions` | int ≥ 1 | `1` | Runs per `(model, case)`; each gets a distinct fingerprint |
| `fail_fast` | bool | `false` | Stop after the first case failure |
| `stop_on_runner_error` | bool | `true` | Stop after the first unrecoverable runner error |

### `openclaw` block

| Field | Type | Required | Description |
|---|---|---|---|
| `agent_id` | slug | yes | Resolves `configs/agents/<agent_id>/` |
| `image` | string | yes | Pinned OCI image for the `openclaw` CLI |
| `timeout_seconds` | int | yes | Wall-clock timeout for the container run |
| `docker_cli` | string | no (default `docker`) | OCI runtime CLI (e.g. `podman`) |

!!! note "OpenClaw model routing"
    The suite model is mapped to an OpenRouter ref (`openrouter/<provider>/<model>`) and injected as `agents.defaults.model.primary` in the generated `openclaw.json`. Fallbacks are rejected: a benchmark run must execute against exactly one model.

### Example

```yaml
schema_version: 1
run_profile_id: standard_run
title: Standard run profile
runner_defaults:
  temperature: 0
  max_tokens: 1024
  timeout_seconds: 60
  retries: 2
  max_turns: 8
model_overrides:
  big_model:
    max_tokens: 4096
    timeout_seconds: 120
execution_policy:
  max_concurrency: 2
  run_repetitions: 3
  fail_fast: false
  stop_on_runner_error: true
```

---

## Evaluation profile (`evaluation_profile.yaml`)

Defines the judges, their repetition plans, aggregation policies, and security controls.

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `evaluation_profile_id` | slug | yes | Unique identifier |
| `title` | string | yes | Human-readable label |
| `judges` | list of `JudgeConfig` | no | Named judge definitions |
| `judge_runs` | list of `JudgeRunConfig` | no | Execution plans referencing a judge |
| `aggregation` | `JudgeAggregationConfig` | no | How to aggregate judge iterations |
| `anchors` | `AnchorsConfig` | no | Calibration anchors for the judge prompt |
| `security_policy` | `SecurityPolicy` | no | Execution security controls |
| `judge_system_prompt_path` | path | no | Path to system prompt file, relative to this YAML |
| `judge_system_prompt` | string | no | Inline system prompt text |

`judge_system_prompt_path` and `judge_system_prompt` are mutually exclusive.

### `judges` — JudgeConfig

| Field | Type | Required | Description |
|---|---|---|---|
| `judge_id` | slug | yes | Logical name referenced by `judge_runs` |
| `type` | string | yes | Judge backend (`"llm_probe"`) |
| `model` | string | no | Model to call (e.g. `"openai/gpt-5.4-mini"`) |

### `judge_runs` — JudgeRunConfig

| Field | Type | Default | Description |
|---|---|---|---|
| `judge_run_id` | slug | — | Unique run identifier |
| `judge_id` | slug | — | Must match a declared judge |
| `repetitions` | int ≥ 1 | `1` | How many times to call the judge per case |
| `sample_size` | int or null | `null` | Subset of repetitions used for aggregation |

### `aggregation` — how iterations combine

| Field | Type | Default | Description |
|---|---|---|---|
| `method` | `"median"` / `"mean"` / `"majority_vote"` / `"all_pass"` | `"median"` | Aggregation across successful iterations |
| `pass_threshold` | float or null | null | Score threshold below which a dimension is considered failed |

!!! note "`final_score`"
    `final_score` comes from `judge_overall.score`. Deterministic checks are informative evidence for the judge and for debugging, but there is no separate weighting policy for the final score.

### `anchors` — calibration examples

```yaml
anchors:
  enabled: true
  references:
    - anchor_id: perfect_tool_use
      label: "Perfect tool-use chain"
      text: "Used all three tools in order, file contents exact, confirmation clear."
```

When `enabled: true`, anchor texts are injected into the judge prompt to help calibrate scoring.

### `security_policy`

| Field | Type | Default | Description |
|---|---|---|---|
| `allow_local_python_hooks` | bool | `false` | Allow Python hook files in test cases to execute |
| `network_access` | `"deny"` / `"allow"` | `"deny"` | Network access for hook execution |
| `redact_secrets` | bool | `true` | Strip known secret patterns from artifact payloads |

### Full example

```yaml
schema_version: 1
evaluation_profile_id: judge_gpt4o_mini
title: Judge with GPT-4o mini (3 repetitions)
judge_system_prompt_path: prompts/judge_system_default.md
judges:
  - judge_id: main_judge
    type: llm_probe
    model: openai/gpt-4o-mini
judge_runs:
  - judge_run_id: main_run
    judge_id: main_judge
    repetitions: 3
aggregation:
  method: median
anchors:
  enabled: false
security_policy:
  allow_local_python_hooks: false
  network_access: deny
  redact_secrets: true
```

---

## OpenClaw agent (`configs/agents/<agent_id>/`)

A directory-based config surface for OpenClaw benchmarks:

```text
configs/agents/<agent_id>/
  agent.yaml
  workspace/
    AGENTS.md
    SOUL.md
    ...           ← any workspace template files
```

### `agent.yaml` top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `agent_id` | slug | yes | Must match the directory name |
| `title` | string | yes | Human-readable label |
| `description` | string | no | Optional summary |
| `tags` | list | no | Free tags |
| `openclaw` | `OpenClawFragments` | no | Fragments merged into generated `openclaw.json` |

### `openclaw` fragments

| Field | Description |
|---|---|
| `identity` | Not written to `openclaw.json` (fails strict validation); keep persona in workspace files instead |
| `agents_defaults` | Merged into `agents.defaults` |
| `agent` | Used to build `agents.list[0]` (`id`, `prompt` → `systemPromptOverride`) |
| `model_defaults` | `aliases` mapped to `agents.defaults.models[<primary>].alias`; `fallbacks` are rejected |

`openclaw.agent.id` is used as the agent ID passed to `openclaw agent --agent`. It can differ from `agent_id` (e.g. `agent_id: support_agent` with `openclaw.agent.id: support-agent`).

### Workspace contract

- `workspace/` must exist beside `agent.yaml`
- The harness copies it into an ephemeral temp directory before each run
- Missing standard files (`AGENTS.md`, `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `USER.md`) are filled with deterministic placeholder content
- The agent fingerprint covers the SHA-256 of every file in `workspace/` — changing any workspace file invalidates all stored runs for that agent
