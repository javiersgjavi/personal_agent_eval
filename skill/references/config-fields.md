# Config Fields Reference

Full field-by-field documentation for all `personal_agent_eval` YAML config files. All files must declare `schema_version: 1`. The loader raises a hard `ConfigError` on any schema violation — there are no silent defaults for required fields.

---

## Test case (`configs/cases/<case_id>/test.yaml`)

Defines one atomic evaluation scenario. The same case can appear in multiple suites and run against multiple models.

### Canonical examples

Use the committed examples as templates instead of copying long snippets from this reference:

| Pattern | Example file | Notes |
|---|---|---|
| `llm_probe` with tools | `configs/cases/llm_probe_tool_example/test.yaml` | Shows `input.context.llm_probe.tools`, expectations, rubric, and file checks |
| `llm_probe` with web search | `configs/cases/llm_probe_browser_example/test.yaml` | Shows browser/search-style prompting and deterministic output checks |
| OpenClaw single-turn workspace output | `configs/cases/openclaw_tool_example/test.yaml` | Shows `input.context.openclaw.expected_artifact` and `openclaw_workspace_file_present` |
| OpenClaw browser/web task | `configs/cases/openclaw_browser_example/test.yaml` | Shows OpenClaw web use and workspace artifact validation |
| OpenClaw multiturn | `configs/cases/openclaw_multiturn_example/test.yaml` | Shows `input.turns` and same-session workspace continuity |
| Runnable suites/profiles | `configs/suites/*_examples.yaml`, `configs/run_profiles/*_examples.yaml`, `configs/evaluation_profiles/judge_gpt54_mini.yaml` | Shows complete campaign wiring |

### Top-level fields

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `case_id` | slug | yes | Unique identifier; used as directory name in `outputs/` |
| `title` | string | yes | Human-readable label |
| `runner` | `RunnerConfig` | yes | Runner type and optional case-level overrides |
| `input` | `TestInput` | yes | Messages, attachments, and runner context |
| `expectations` | `Expectations` | no | Hard/soft expectation list shown to the judge |
| `rubric` | `Rubric` | no | Scored anchors and criteria shown to the judge |
| `deterministic_checks` | list | no | Checks run against the `RunArtifact` without an LLM |
| `tags` | list of strings | no | Free tags; used by `case_selection.include_tags` / `exclude_tags` |
| `metadata` | mapping | no | Arbitrary key/value; not used by the framework |

### `runner`

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | `"llm_probe"` or `"openclaw"` | yes | Selects the runner implementation |

Any extra fields (e.g. `temperature: 0`) are case-level runner overrides — they take precedence over `run_profile.runner_defaults` but are overridden by `run_profile.model_overrides`.

### `input`

| Field | Type | Default | Description |
|---|---|---|---|
| `messages` | list of `Message` | `[]` | Ordered message sequence sent to the model; for OpenClaw multiturn cases, optional initial context |
| `turns` | list of `Message` | `[]` | OpenClaw-only user turns executed as separate agent invocations in one session |
| `attachments` | list of paths | `[]` | Local files injected as extra user messages before the first user message |
| `context` | mapping | `{}` | Runner-specific context: tools, openclaw hints, etc. |

All relative paths in `input` resolve relative to the `test.yaml` file.

#### Message

| Field | Type | Required | Description |
|---|---|---|---|
| `role` | `"system"` / `"user"` / `"assistant"` | yes | Message role |
| `content` | string | one of `content` / `source` | Inline message text |
| `source` | `MessageSource` | one of `content` / `source` | External file reference |

`content` and `source` are mutually exclusive.

#### MessageSource

```yaml
source:
  path: messages/user_prompt.yaml   # relative to test.yaml
  format: yaml                      # optional; auto-detected from extension
```

The referenced file may resolve to a single message object or a list of messages.

#### OpenClaw multiturn input

For `runner.type: openclaw`, `input.messages` preserves the existing single-turn behavior: the messages are rendered into one OpenClaw `--message` invocation. To test follow-up user messages, use `input.turns`. Each turn is sent through `openclaw agent --session-id <run-session>` using the same ephemeral workspace and `OPENCLAW_STATE_DIR`.

```yaml
input:
  messages:
    - role: system
      content: Keep context across user turns.
  turns:
    - role: user
      content: Create draft.md.
    - role: user
      content: Revise draft.md and create report.md.
  context:
    openclaw:
      expected_artifact: report.md
```

When `turns` is present, `messages` is treated as initial context and included with the first turn only. Final workspace checks run after the last successful turn, and the raw session trace records all turn payloads.

#### `input.context.llm_probe`

| Field | Type | Description |
|---|---|---|
| `tools` | list of strings | Tools exposed to the model: `exec_shell`, `write_file`, `read_file`, `web_search` |

#### `input.context.openclaw`

| Field | Type | Description |
|---|---|---|
| `expected_artifact` | string | Filename of the expected output file in the workspace (hint for the harness) |

### `expectations`

Shown to the judge as part of the evaluation target.

| Field | Type | Description |
|---|---|---|
| `hard_expectations` | list of `Expectation` | Critical requirements; judge treats failures as blocking |
| `soft_expectations` | list of `Expectation` | Scored with partial credit |

Each `Expectation`: `text` (required), `weight` (float, default `1.0`).

### `rubric`

Structured rubric shown to the judge to calibrate scoring.

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

### `deterministic_checks`

Each entry is a `DeterministicCheck`:

| Field | Type | Required | Description |
|---|---|---|---|
| `check_id` | slug | yes | Unique within the case |
| `dimensions` | list of dimension names | no | Which dimensions this check affects in aggregation |
| `declarative` | `DeclarativeCheck` | one of | Built-in check specification |
| `python_hook` | `PythonHook` | one of | Custom Python callable |

`declarative` and `python_hook` are mutually exclusive.

Valid dimension names: `task`, `process`, `autonomy`, `closeness`, `efficiency`, `spark`.

#### Declarative check kinds

| `kind` | Extra fields | Description |
|---|---|---|
| `final_response_present` | — | Non-empty final output in the trace |
| `tool_call_count` | `expected` (int) | Exact tool call count |
| `file_exists` | `path` | File exists on host filesystem |
| `file_contains` | `path`, `text` | File exists and contains substring |
| `path_exists` | `path` | Path exists (file or directory) |
| `status_is` | `expected` | Terminal run status matches (`success`, `failed`, `timed_out`, `invalid`, `provider_error`) |
| `output_artifact_present` | `artifact_type`? | Run artifact records a matching output artifact |
| `openclaw_workspace_file_present` | `relative_path`, `contains`? | Workspace diff contains the file (OpenClaw only) |

Paths in checks resolve relative to `test.yaml`.

#### PythonHook

```yaml
python_hook:
  path: hooks/my_check.py        # relative to test.yaml
  callable_name: check_output
  # or: import_path: mypackage.checks.output_check
```

Python hooks are **disabled by default**. Enable with `security_policy.allow_local_python_hooks: true` in the evaluation profile.

---

## Suite (`configs/suites/<suite_id>.yaml`)

Groups models with a case selection policy.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `suite_id` | slug | yes | Unique identifier |
| `title` | string | yes | Human-readable label |
| `models` | list of `ModelConfig` | no | Models to run against selected cases |
| `case_selection` | `CaseSelection` | no | Filters determining which cases are included |
| `metadata` | mapping | no | Arbitrary annotation bag |

### `models` — ModelConfig

| Field | Type | Required | Description |
|---|---|---|---|
| `model_id` | slug | yes | Local name used in artifact paths and reports |
| `label` | string | no | Human-readable display name |
| `requested_model` | string | no | OpenRouter model string (e.g. `openai/gpt-4o-mini`) |

### `case_selection`

| Field | Type | Description |
|---|---|---|
| `include_case_ids` | list of strings | Explicit case IDs to include |
| `exclude_case_ids` | list of strings | Explicit case IDs to exclude |
| `include_tags` | list of strings | Include cases that have at least one of these tags |
| `exclude_tags` | list of strings | Exclude cases that have at least one of these tags |

Precedence: `include_case_ids` > tag filters > `exclude_case_ids`. Unknown IDs in `include_case_ids` are a hard error.

---

## Run profile (`configs/run_profiles/<id>.yaml`)

Controls execution behavior. A SHA-256 fingerprint of effective settings scopes campaign storage directories.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `run_profile_id` | slug | yes | Unique identifier |
| `title` | string | yes | Human-readable label |
| `runner_defaults` | mapping | no | Default runner settings applied to every case |
| `model_overrides` | mapping | no | Per-model setting overrides (key = `model_id`) |
| `execution_policy` | `ExecutionPolicy` | no | Concurrency and error-handling controls |
| `openclaw` | `OpenClawRunProfile` | no | OpenClaw runtime block (agent, image, timeout) |

### `runner_defaults` / `model_overrides` — llm_probe fields

Merge order (later wins): `runner_defaults` → `model_overrides[model_id]` → case-level `runner:` fields.

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
| `fail_fast` | bool | `false` | Stop after first case failure |
| `stop_on_runner_error` | bool | `true` | Stop after first unrecoverable runner error |

### `openclaw` block

| Field | Type | Required | Description |
|---|---|---|---|
| `agent_id` | slug | yes | Resolves to `configs/agents/<agent_id>/` |
| `image` | string | yes | Pinned OCI image for the `openclaw` CLI |
| `timeout_seconds` | int | yes | Wall-clock timeout for the container run |
| `docker_cli` | string | no (default `docker`) | OCI runtime CLI (e.g. `podman`) |

---

## Evaluation profile (`configs/evaluation_profiles/<id>.yaml`)

Defines the judges, repetition plans, aggregation policies, and security controls.

| Field | Type | Required | Description |
|---|---|---|---|
| `schema_version` | `1` | yes | Must be `1` |
| `evaluation_profile_id` | slug | yes | Unique identifier |
| `title` | string | yes | Human-readable label |
| `judges` | list of `JudgeConfig` | no | Named judge definitions |
| `judge_runs` | list of `JudgeRunConfig` | no | Execution plans referencing a judge |
| `aggregation` | `JudgeAggregationConfig` | no | How to aggregate judge iterations |
| `anchors` | `AnchorsConfig` | no | Calibration anchors injected into the judge prompt |
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

### `aggregation`

| Field | Type | Default | Description |
|---|---|---|---|
| `method` | `"median"` / `"mean"` / `"majority_vote"` / `"all_pass"` | `"median"` | Aggregation across successful iterations |
| `pass_threshold` | float or null | null | Score threshold below which a dimension is considered failed |

### `anchors`

```yaml
anchors:
  enabled: true
  references:
    - anchor_id: perfect_example
      label: "Perfect tool-use chain"
      text: "Used all three tools in order, file contents exact, confirmation clear."
```

When `enabled: true`, anchor texts are injected into the judge prompt to calibrate scoring.

### `security_policy`

| Field | Type | Default | Description |
|---|---|---|---|
| `allow_local_python_hooks` | bool | `false` | Allow Python hook files in test cases to execute |
| `network_access` | `"deny"` / `"allow"` | `"deny"` | Network access for hook execution |
| `redact_secrets` | bool | `true` | Strip known secret patterns from artifact payloads |

---

## OpenClaw agent (`configs/agents/<agent_id>/`)

```
configs/agents/<agent_id>/
  agent.yaml
  workspace/
    AGENTS.md    ← workspace instructions (copied into every run)
    SOUL.md      ← agent identity/behavior
    ...          ← any additional template files
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
| `identity` | Not written to `openclaw.json`; keep persona in workspace files |
| `agents_defaults` | Merged into `agents.defaults` |
| `agent` | Used to build `agents.list[0]` (`id`, `prompt` → `systemPromptOverride`) |
| `model_defaults` | `aliases` mapped to model aliases; `fallbacks` are rejected |

`openclaw.agent.id` is passed to `openclaw agent --agent` and can differ from `agent_id`.

### Workspace contract

- `workspace/` must exist beside `agent.yaml`
- The harness copies it into an ephemeral temp directory before each run
- Missing standard files (`AGENTS.md`, `IDENTITY.md`, `SOUL.md`, `TOOLS.md`, `USER.md`) are filled with deterministic placeholder content
- The agent fingerprint covers the SHA-256 of every file in `workspace/` — changing any workspace file invalidates all stored runs for that agent
