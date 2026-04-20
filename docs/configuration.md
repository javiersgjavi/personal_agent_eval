# Configuration Reference

`personal_agent_eval` uses four core YAML config file types plus one OpenClaw agent
directory contract. Each YAML file must declare `schema_version: 1` at the top and is
loaded through a typed, validated loader that raises an explicit `ConfigError` on any
schema violation.

---

## Quick overview

| Type | Default path | ID field | Loaded by |
|---|---|---|---|
| Test case | `configs/cases/<case_id>/test.yaml` | `case_id` | `load_test_config(path)` |
| Suite | `configs/suites/<suite_id>.yaml` | `suite_id` | `load_suite_config(path)` |
| Run profile | `configs/run_profiles/<profile_id>.yaml` | `run_profile_id` | `load_run_profile(path)` |
| Evaluation profile | `configs/evaluation_profiles/<profile_id>.yaml` | `evaluation_profile_id` | `load_evaluation_profile(path)` |
| OpenClaw agent | `configs/agents/<agent_id>/agent.yaml` + `workspace/` | `agent_id` | `load_openclaw_agent(path)` |

CLI flags (`--suite`, `--run-profile`, `--evaluation-profile`) accept either an
explicit YAML path **or** just the plain ID and will search the conventional directory
automatically.

---

## Test case (`test.yaml`)

Defines one atomic evaluation case: runner selection, input messages, attachments,
expectations for judge scoring, and deterministic checks.

### Top-level fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `schema_version` | `1` | yes | — | Must be `1` |
| `case_id` | string (slug) | yes | — | Unique case identifier, used as directory name |
| `title` | string | yes | — | Human-readable label |
| `runner` | `RunnerConfig` | yes | — | Runner selector and optional runner-level defaults |
| `input` | `TestInput` | yes | — | Messages, attachments, and context |
| `expectations` | `Expectations` | no | `{}` | Hard/soft expectation lists for the judge |
| `deterministic_checks` | list of `DeterministicCheck` | no | `[]` | Checks run directly against the `RunArtifact` |
| `tags` | list of strings | no | `[]` | Free tags; duplicates and whitespace are normalised |
| `metadata` | mapping | no | `{}` | Arbitrary key/value bag; not used by the framework |

### `runner`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `type` | `"llm_probe"` \| `"openclaw"` | yes | — | Selects the runner implementation |

Any extra fields (e.g. `temperature: 0`) are passed through to the runner as
case-level overrides; they take precedence over `run_profile.runner_defaults` but
are overridden by `run_profile.model_overrides`.

For `openclaw` cases, keep the same canonical shape:

- task prompt in `input.messages`
- optional case hints under `input.context.openclaw`
- success criteria in `expectations` and `deterministic_checks`

### `input`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `messages` | list of `Message` | no | `[]` | Ordered message sequence sent to the model |
| `attachments` | list of paths | no | `[]` | Local files injected as extra user messages (see below) |
| `context` | mapping | no | `{}` | Arbitrary context bag forwarded to the runner |

All relative paths inside `input` resolve relative to the `test.yaml` file.

#### `Message`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `role` | `"system"` \| `"user"` \| `"assistant"` \| `"tool"` | yes | — | Message role |
| `content` | string | one of `content`/`source` | — | Inline message text |
| `source` | `MessageSource` | one of `content`/`source` | — | External file reference |
| `name` | string | no | `null` | Optional name annotation |

`content` and `source` are mutually exclusive; exactly one must be provided.

#### `MessageSource`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | path | yes | — | Path to a YAML or JSON message file (relative to `test.yaml`) |
| `format` | `"yaml"` \| `"json"` \| `null` | no | `null` (auto-detected) | Force file format |

The referenced file may resolve to a single message object or a list of messages.

#### Attachments

Files listed under `input.attachments` are read at run time and injected into the
prompt as additional `user` messages that appear immediately after any `system`
message and before the first `user` message. Each injected message looks like:

```
Attached context file: <filename>

--- BEGIN ATTACHMENT <filename> ---
<decoded file content>
--- END ATTACHMENT <filename> ---
```

The original attachment paths are also recorded in the run artifact request
metadata and contribute to the `run_fingerprint`.

### `expectations`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `hard_expectations` | list of `Expectation` | no | `[]` | Requirements the judge must treat as critical |
| `soft_expectations` | list of `Expectation` | no | `[]` | Requirements scored with partial credit |

#### `Expectation`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `text` | string | yes | — | Natural-language expectation statement for the judge |
| `weight` | float | no | `1.0` | Relative weight within its group |
| `metadata` | mapping | no | `{}` | Arbitrary annotation bag |

### `deterministic_checks`

Each entry is a `DeterministicCheck`:

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `check_id` | string (slug) | yes | — | Unique within the case |
| `description` | string | no | `null` | Free-text description |
| `dimensions` | list of dimension names | no | `[]` | Dimensions this check affects during hybrid aggregation |
| `declarative` | `DeclarativeCheck` | one of | — | Built-in check specification |
| `python_hook` | `PythonHook` | one of | — | Custom Python callable |

`declarative` and `python_hook` are mutually exclusive; exactly one must be provided.

Valid dimension names: `task`, `process`, `autonomy`, `closeness`, `efficiency`, `spark`.

#### Declarative check kinds

| `kind` | Extra fields | Description |
|---|---|---|
| `final_response_present` | — | Passes when the run trace contains a non-empty final output; for `openclaw`, also accepts the last assistant message in the trace or text from a key workspace output artifact |
| `tool_call_count` | `count` (int ≥ 0) | Passes when the run recorded exactly `count` tool calls |
| `file_exists` | `path` | Passes when the given path exists and is a regular file |
| `file_contains` | `path`, `text` | Passes when the file exists and contains `text` |
| `path_exists` | `path` | Passes when the given filesystem path exists (file or directory) |
| `status_is` | `status` | Passes when the run's terminal status matches (`success`, `failed`, `timed_out`, `invalid`, `provider_error`) |
| `output_artifact_present` | `artifact_id`?, `artifact_type`?, `uri`? | Passes when the run artifact records a matching output artifact (at least one matcher field required) |
| `openclaw_workspace_file_present` | `relative_path`, `contains`? | For `runner.type: openclaw` only: passes when a recorded output artifact resolves to a workspace file whose path ends with `relative_path`; optional `contains` substring match on file text |

Paths in declarative checks resolve relative to `test.yaml`.

#### `PythonHook`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `import_path` | string | one of | — | Dotted import path to a Python module (e.g. `my_pkg.checks`) |
| `path` | path | one of | — | Local `.py` file path, relative to `test.yaml` |
| `callable_name` | string | yes | — | Name of the callable inside the module/file |

`import_path` and `path` are mutually exclusive.

### Minimal `test.yaml` example

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
    declarative:
      kind: final_response_present
```

### Full `test.yaml` example

```yaml
schema_version: 1
case_id: full_example
title: Full example case
runner:
  type: llm_probe
  temperature: 0
input:
  messages:
    - role: system
      content: You are a careful evaluator.
    - role: user
      source:
        path: messages.yaml
        format: yaml
  attachments:
    - artifacts/prompt.txt
  context:
    locale: en-US
expectations:
  hard_expectations:
    - text: Mentions the main point.
  soft_expectations:
    - text: Uses concise wording.
      weight: 0.5
deterministic_checks:
  - check_id: response-present
    dimensions:
      - process
    declarative:
      kind: final_response_present
  - check_id: custom-check
    dimensions:
      - task
    python_hook:
      path: hooks/custom_check.py
      callable_name: check_output
tags:
  - smoke
  - llm_probe
metadata:
  owner: qa
```

---

## Suite (`suite.yaml`)

Groups a set of models with a case selection policy.

### Top-level fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `schema_version` | `1` | yes | — | Must be `1` |
| `suite_id` | string (slug) | yes | — | Unique suite identifier |
| `title` | string | yes | — | Human-readable label |
| `models` | list of `ModelConfig` | no | `[]` | Models to run against the selected cases |
| `case_selection` | `CaseSelection` | no | see below | Filters that determine which cases are included |
| `metadata` | mapping | no | `{}` | Arbitrary annotation bag |

### `models` — `ModelConfig`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `model_id` | string (slug) | yes | — | Logical name used in artifact paths and reports |
| `label` | string | no | `null` | Human-readable display name |
| `requested_model` | string | no | — | OpenRouter model string (e.g. `openai/gpt-4o-mini`) |

Any extra fields under a model entry are passed through to the runner.

The `llm_probe` runner resolves the model to call in this priority order:
`requested_model` → `openrouter_model` → `provider` + `model_name` → `model_id`.

### `case_selection`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `include_case_ids` | list of strings | no | `[]` | Explicit case IDs to include; takes precedence over tag filters |
| `exclude_case_ids` | list of strings | no | `[]` | Explicit case IDs to exclude |
| `include_tags` | list of strings | no | `[]` | Include any case that has at least one of these tags |
| `exclude_tags` | list of strings | no | `[]` | Exclude any case that has at least one of these tags |

Precedence: `include_case_ids` > tag filters > `exclude_case_ids`.
Any unknown `case_id` in `include_case_ids` or `exclude_case_ids` is a hard error.

### Example `suite.yaml`

```yaml
schema_version: 1
suite_id: smoke_suite
title: Smoke test suite
models:
  - model_id: gpt4o_mini
    requested_model: openai/gpt-4o-mini
    label: GPT-4o mini
case_selection:
  include_tags:
    - smoke
  exclude_case_ids:
    - known_flaky_case
```

---

## Run profile (`run_profile.yaml`)

Defines execution-time defaults, per-model overrides, and concurrency/fail-fast
controls. Does not implement any runner logic itself.

### Top-level fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `schema_version` | `1` | yes | — | Must be `1` |
| `run_profile_id` | string (slug) | yes | — | Unique profile identifier |
| `title` | string | yes | — | Human-readable label |
| `runner_defaults` | mapping | no | `{}` | Default runner settings applied to every case |
| `model_overrides` | mapping of model_id → mapping | no | `{}` | Per-model setting overrides |
| `execution_policy` | `ExecutionPolicy` | no | see below | Concurrency and error-handling controls |
| `openclaw` | `OpenClawRunProfile \| null` | no | `null` | OpenClaw runtime selection (`agent_id`, `image`, `timeout_seconds`) |

### `runner_defaults` and `model_overrides`

Both accept the same free-form key/value pairs that are forwarded to the runner.
The `llm_probe` runner recognises these fields:

| Field | Type | Default (llm_probe) | Description |
|---|---|---|---|
| `temperature` | float 0–2 | `1.0` (provider default) | Sampling temperature |
| `top_p` | float 0–1 | provider default | Nucleus sampling |
| `max_tokens` | int | provider default | Maximum tokens to generate. Keep ≥ 256 for models that emit `reasoning` before `content` |
| `seed` | int | `null` | Reproducibility seed |
| `timeout_seconds` | int | `30` | Per-request wall-clock timeout |
| `retries` | int | `5` | Number of retry attempts on transient failures |
| `tool_choice` | string | provider default | Force tool choice (`"auto"`, `"none"`, or a specific tool name) |

Merge order (later wins): `runner_defaults` → `model_overrides[model_id]` → case-level `runner:` fields.

### `openclaw`

When present, the `openclaw` block selects the reusable agent directory and the base
runtime image for OpenClaw execution:

| Field | Type | Required | Description |
|---|---|---|---|
| `agent_id` | string (slug) | yes | Resolves `configs/agents/<agent_id>/` |
| `image` | string | yes | Container image used by the harness |
| `timeout_seconds` | int > 0 | yes | Wall-clock timeout for the OpenClaw run |

Example:

```yaml
schema_version: 1
run_profile_id: openclaw_smoke
title: OpenClaw smoke profile
openclaw:
  agent_id: support_agent
  image: ghcr.io/openclaw/openclaw-base:0.1.0
  timeout_seconds: 300
execution_policy:
  max_concurrency: 1
```

`runner_defaults` and `model_overrides` continue to apply to `llm_probe`. OpenClaw uses
the dedicated `openclaw` block instead of encoding runtime selection in free-form keys.

### Generated `openclaw.json`

The benchmark resolves one effective OpenClaw config per run and then renders a minimal,
deterministic `openclaw.json`.

Current merge and injection rules:

1. start from the benchmark-safe base shape
2. merge `agent.yaml` fragments:
   - `openclaw.identity` -> `identity`
   - `openclaw.agents_defaults` -> `agents.defaults`
   - `openclaw.agent` -> the single `agents.list[0]` entry
   - `openclaw.model_defaults` -> non-primary `models` settings such as `aliases` and `fallbacks`
3. inject the benchmark-selected primary model into:
   - `models.default`
   - `agents.list[0].model`
4. inject the ephemeral workspace path into `agents.defaults.workspace`

The generated config does **not** treat the OpenClaw state directory as part of the
workspace. The ephemeral `OPENCLAW_STATE_DIR` remains a separate runtime surface and is not
written into `agents.defaults.workspace`.

### OpenClaw Harness

The current benchmark harness runs OpenClaw in a minimal benchmark-owned flow:

1. resolve the effective config and materialize the ephemeral workspace
2. create a separate ephemeral `OPENCLAW_STATE_DIR`
3. write the generated `openclaw.json`
4. validate it with `openclaw config validate --json`
5. execute one local turn with `openclaw agent --local --json`

`timeout_seconds` is still enforced as a real wall-clock limit for execution, but it is
treated as runtime control metadata rather than semantic reuse identity.

**Upstream context:** OpenClaw is a self-hosted gateway and agent runtime; product documentation
(install, configuration surfaces, channels) lives at [docs.openclaw.ai](https://docs.openclaw.ai).
The benchmark only needs the `openclaw` CLI on `PATH` for real executions and uses the generated
per-run config described above, not the interactive onboarding defaults from upstream docs.

---

## OpenClaw agent (`configs/agents/<agent_id>/agent.yaml`)

OpenClaw agents are directory-based configs:

```text
configs/agents/<agent_id>/
  agent.yaml
  workspace/
    AGENTS.md
    SOUL.md
    ...
```

`agent.yaml` declares stable benchmark-owned fragments that are merged into the generated
`openclaw.json`. `workspace/` is the template copied into the ephemeral run workspace.

### Top-level fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `schema_version` | `1` | yes | — | Must be `1` |
| `agent_id` | string (slug) | yes | — | Must match the parent directory name |
| `title` | string | yes | — | Human-readable label |
| `description` | string | no | `null` | Optional summary |
| `tags` | list of strings | no | `[]` | Free tags; duplicates/whitespace are normalised |
| `metadata` | mapping | no | `{}` | Arbitrary JSON-serializable metadata |
| `openclaw` | `OpenClawFragments` | no | `{}` | Benchmark-owned fragments for generated `openclaw.json` |

### `openclaw`

Initial supported fragment keys:

| Field | Type | Description |
|---|---|---|
| `identity` | mapping | Optional identity fragment |
| `agents_defaults` | mapping | Partial object merged into `agents.defaults` |
| `agent` | mapping | Partial object used to build the single `agents.list[]` entry |
| `model_defaults` | mapping | Optional non-primary model defaults such as `aliases` and `fallbacks` |

The loader rejects primary-model override keys in these fragments; the effective benchmark
model must still come from suite or CLI model selection.

### Workspace contract

- `workspace/` must exist beside `agent.yaml`
- the directory is loaded as-is and validated as part of the agent contract
- the harness copies the template into an empty ephemeral run workspace before execution
- missing standard root files are filled with deterministic placeholder markdown files for:
  - `AGENTS.md`
  - `IDENTITY.md`
  - `SOUL.md`
  - `TOOLS.md`
  - `USER.md`
- the materialization step also produces a deterministic manifest of final workspace files for
  later fingerprinting and reuse decisions

Common OpenClaw workspace files include:

- `AGENTS.md`
- `SOUL.md`
- `USER.md`
- `TOOLS.md`
- `IDENTITY.md`

Optional workspace content commonly includes:

- `HEARTBEAT.md`
- `BOOT.md`
- `BOOTSTRAP.md`
- `memory/`
- `MEMORY.md`

### `execution_policy`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `max_concurrency` | int ≥ 1 | no | `1` | Maximum number of cases running in parallel |
| `run_repetitions` | int ≥ 1 | no | `1` | Number of executions per model/case pair; each repetition is stored separately and workflow reporting aggregates them back by mean score/dimensions |
| `fail_fast` | bool | no | `false` | Stop the run after the first case failure |
| `stop_on_runner_error` | bool | no | `true` | Stop the run after the first unrecoverable runner error |

`run_repetitions` affects run identity. When it is greater than `1`, each repetition gets a
distinct `run_fingerprint` because the repetition index is added to the normalized execution
settings that are hashed. Storage still groups those repetitions together under one visible
campaign path:

```text
outputs/runs/suit_<suite_id>/run_profile_<run_profile_fingerprint_short6>/<model_id>/<case_id>/run_1.json
outputs/runs/suit_<suite_id>/run_profile_<run_profile_fingerprint_short6>/<model_id>/<case_id>/run_2.json
```

### Example `run_profile.yaml`

```yaml
schema_version: 1
run_profile_id: standard_smoke
title: Standard smoke profile
runner_defaults:
  temperature: 0
  max_tokens: 512
  timeout_seconds: 60
  retries: 2
model_overrides:
  big_model:
    max_tokens: 1024
    timeout_seconds: 120
execution_policy:
  max_concurrency: 4
  run_repetitions: 3
  fail_fast: false
  stop_on_runner_error: true
```

---

## Evaluation profile (`evaluation_profile.yaml`)

Defines judges, judge execution plans, aggregation policies, hybrid final score
policy, calibration anchors, and security policy.

### Top-level fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `schema_version` | `1` | yes | — | Must be `1` |
| `evaluation_profile_id` | string (slug) | yes | — | Unique profile identifier |
| `title` | string | yes | — | Human-readable label |
| `judges` | list of `JudgeConfig` | no | `[]` | Named judge definitions |
| `judge_runs` | list of `JudgeRunConfig` | no | `[]` | Concrete execution plans that reference a judge |
| `aggregation` | `JudgeAggregationConfig` | no | see below | How to aggregate repeated judge iterations |
| `final_aggregation` | `FinalAggregationConfig` | no | see below | How to compute the hybrid final score |
| `anchors` | `AnchorsConfig` | no | see below | Calibration anchor examples for the judge prompt |
| `security_policy` | `SecurityPolicy` | no | see below | Execution security controls |
| `metadata` | mapping | no | `{}` | Arbitrary annotation bag |
| `judge_system_prompt` | string (multiline) | no | — | Optional judge **system** message. Non-empty lines are joined with spaces. Mutually exclusive with `judge_system_prompt_path`. |
| `judge_system_prompt_path` | string (path) | no | — | Optional path to a UTF-8 `.txt` file, **relative to this YAML file**. Same semantics as `judge_system_prompt`. Mutually exclusive with `judge_system_prompt`. Recommended shared location: `prompts/judge_system_default.txt`. |

### `judges` — `JudgeConfig`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `judge_id` | string (slug) | yes | — | Logical name referenced by `judge_runs` |
| `type` | string | yes | — | Judge backend type (e.g. `"llm_probe"`) |
| `model` | string | no | — | Model to call (e.g. `"openai/gpt-4o-mini"`) |

Any extra fields are passed through to the judge backend.

### `judge_runs` — `JudgeRunConfig`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `judge_run_id` | string (slug) | yes | — | Unique run identifier |
| `judge_id` | string (slug) | yes | — | Must match a declared `judge_id` |
| `repetitions` | int ≥ 1 | no | `1` | How many times to call the judge per case |
| `sample_size` | int ≥ 1 \| null | no | `null` (use all) | Subset of repetitions used for aggregation |

Each repetition is stored as a separate iteration result, even when it fails.

### `aggregation` — `JudgeAggregationConfig`

Controls how multiple judge iterations are collapsed into a single per-dimension score.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `method` | `"median"` \| `"mean"` \| `"majority_vote"` \| `"all_pass"` | no | `"median"` | Aggregation method over successful iterations |
| `pass_threshold` | float 0–1 \| null | no | `null` | Optional score threshold below which a dimension is considered failed |

### `final_aggregation` — `FinalAggregationConfig`

Defines how judge scores and deterministic check scores are combined into one final
score per dimension.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `default_policy` | `"judge_only"` | no | `"judge_only"` | Fallback policy for dimensions not explicitly overridden |
| `dimensions` | `FinalAggregationDimensions` | no | all `judge_only` | Per-dimension policy overrides |
| `final_score_weights` | `FinalScoreWeights` | no | all `1.0` | Relative weight of each dimension in the final score |

#### Per-dimension policy (`FinalDimensionAggregationConfig`)

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `policy` | `"judge_only"` \| `"deterministic_only"` \| `"weighted"` | no | `"judge_only"` | Scoring source for this dimension |
| `judge_weight` | float > 0 | required if `weighted` | `null` | Judge contribution (relative, unnormalised) |
| `deterministic_weight` | float > 0 | required if `weighted` | `null` | Deterministic contribution (relative, unnormalised) |

When `policy: weighted` and deterministic scoring is missing, the aggregator falls
back to the judge score and emits a warning.

#### `final_score_weights` (per dimension)

Six dimension weights control the final composite score. All default to `1.0`.
At least one must be > 0.

| Dimension | Default |
|---|---|
| `task` | `1.0` |
| `process` | `1.0` |
| `autonomy` | `1.0` |
| `closeness` | `1.0` |
| `efficiency` | `1.0` |
| `spark` | `1.0` |

### `anchors` — `AnchorsConfig`

Calibration examples that can be injected into the judge prompt to anchor scoring.

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `enabled` | bool | no | `false` | Whether to include anchors in the judge prompt |
| `references` | list of `Anchor` | no | `[]` | Anchor definitions |

#### `Anchor`

| Field | Type | Required | Description |
|---|---|---|---|
| `anchor_id` | string (slug) | yes | Unique anchor identifier |
| `label` | string | yes | Short human-readable label |
| `text` | string | yes | The example text shown to the judge |

### `security_policy` — `SecurityPolicy`

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `allow_local_python_hooks` | bool | no | `false` | Allow Python hook files declared in `test.yaml` to execute |
| `network_access` | `"deny"` \| `"allow"` | no | `"deny"` | Network access policy for hook execution |
| `redact_secrets` | bool | no | `true` | Redact known secret patterns from artifact payloads |

### Example `evaluation_profile.yaml`

```yaml
schema_version: 1
evaluation_profile_id: judge_gpt4o_mini
title: Judge with GPT-4o mini
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
  pass_threshold: 0.5
final_aggregation:
  default_policy: judge_only
  dimensions:
    process:
      policy: weighted
      judge_weight: 0.9
      deterministic_weight: 0.1
  final_score_weights:
    task: 0.3
    process: 0.15
    autonomy: 0.2
    closeness: 0.1
    efficiency: 0.15
    spark: 0.1
anchors:
  enabled: false
security_policy:
  allow_local_python_hooks: false
  network_access: deny
  redact_secrets: true
```

---

## Discovery and suite expansion

- Cases are discovered from `configs/cases/<case_id>/test.yaml` under the workspace root.
- Suites are discovered from `configs/suites/<suite_id>.yaml` under the workspace root.
- Duplicate `case_id` values across the workspace are a hard error.
- Any suite reference to an unknown `case_id` in `include_case_ids` or `exclude_case_ids`
  is a hard error.
- Expanded case lists are deterministic and sorted by `case_id`.

---

## Fingerprint semantics

Fingerprints are computed from normalised semantic payloads, not from raw YAML text.

- `run_fingerprint`: includes only inputs that affect the raw execution trace (messages,
  attachments content, runner settings). Excludes config IDs, titles, and absolute paths.
- `evaluation_fingerprint`: includes only inputs that affect judge behaviour and final
  aggregation. Excludes profile IDs and titles.

For OpenClaw runs, the reuse identity includes the resolved agent definition, the effective
workspace contents, and the runtime image. `timeout_seconds` is treated as runtime control
metadata and is excluded from the semantic reuse fingerprint.

Two equivalent configs produce the same fingerprint even if files move or IDs change.

---

## Related docs

- [Run Artifacts](run_artifacts.md): canonical JSON-serializable schema for recorded
  runner executions
- [Getting Started](getting_started.md): minimal workflow walkthrough
- [Minimal llm_probe example](examples/minimal_llm_probe.md): annotated end-to-end example
