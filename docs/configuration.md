# Configuration Roles

`personal_agent_eval` uses four YAML config file types in V1. Each file must declare
`schema_version: 1` and is loaded through an explicit config loader that returns a validated,
normalized object.

## Test Configs

- Path: `configs/cases/<case_id>/test.yaml`
- Loader: `load_test_config(path)`
- Purpose: define one evaluation case, including the runner selection, input messages,
  expectations, deterministic checks, tags, and metadata

V1 test configs support explicit input sections, full message sequences, inline messages,
external message references, declarative deterministic checks, and Python hook references.
Any relative file references resolve relative to the `test.yaml` file.

### Attachments

V1 `test.yaml` inputs may include `input.attachments`, which is a list of file paths resolved
relative to the `test.yaml` file.

For `llm_probe` runs, attachments are treated as deterministic input context:

- The runner reads the attachment file bytes and injects the decoded text into the initial
  prompt as additional `user` messages.
- These injected messages appear in the run trace and contribute to the run fingerprint.
- The run artifact also records the original attachment paths in request metadata.

This means `attachments` are not "agent-chosen reads" in V1 `llm_probe`. If a case expects the
model to use an attachment, it should rely on this automatic injection rather than on a tool
read step.

Deterministic checks are independent from judge evaluation. `expectations.hard_expectations`
remain natural-language requirements for judge-based scoring, while `deterministic_checks`
run directly against the canonical `RunArtifact`.

V1 declarative deterministic checks:

- `final_response_present`
- `tool_call_count`
- `file_exists`
- `file_contains`
- `path_exists`
- `status_is`
- `output_artifact_present`

Deterministic checks may also declare `dimensions` when a case wants to say explicitly which
shared scoring dimensions a check should influence during hybrid aggregation. If omitted, the
aggregator uses framework defaults for supported declarative checks.

Python deterministic hooks can reference either an importable module path or a local file
path already supported by the config loader. Hooks execute against the `RunArtifact` and may
return either a boolean or a structured result payload with `passed`, `message`, `metadata`,
and `outputs`.

## Suite Configs

- Path: `configs/suites/<suite_id>.yaml`
- Loader: `load_suite_config(path)`
- Purpose: group models with a case selection policy and suite-level metadata

Suites declare which models participate in a run and which cases or tags should be included
or excluded.

## Discovery And Suite Expansion

- Cases are discovered from a supplied workspace root under `configs/cases/<case_id>/test.yaml`
- Suites are discovered from a supplied workspace root under `configs/suites/<suite_id>.yaml`
- Duplicate discovered `case_id` values are a hard error
- Any suite reference to a missing `case_id` in `include_case_ids` or `exclude_case_ids`
  is a hard error
- `include_case_ids` has priority over tag filters and exclude lists
- Tag-based selection matches when a case has any requested tag
- Expanded suite case lists are deterministic and sorted by `case_id`

## Run Profiles

- Path: `configs/run_profiles/<profile_id>.yaml`
- Loader: `load_run_profile(path)`
- Purpose: define execution-time defaults, model overrides, and execution policy settings

Run profiles are the canonical place for concurrency and fail-fast controls. They do not
implement runner logic themselves; they only define validated configuration.

For V1 `llm_probe` runs, the runner resolves execution settings by merging:

- `run_profile.runner_defaults`
- `run_profile.model_overrides[model_id]`
- case-level `runner:` fields from `configs/cases/<case_id>/test.yaml`

Later values override earlier ones. The Step 5 runner currently consumes fields such as
`temperature`, `top_p`, `max_tokens`, `seed`, `timeout_seconds`, `retries`, and
`tool_choice`. If `retries` is omitted, the `llm_probe` retry baseline defaults to `5`.

Model selection for the OpenRouter-backed runner is derived from the suite model entry. The
runner prefers `requested_model`, then `openrouter_model`, then `provider` + `model_name`,
and finally falls back to `model_id`.

## llm_probe Workflow

The V1 runtime target is `llm_probe` with OpenRouter as the real gateway.

- The runner accepts full initial message sequences from `input.messages`
- A message `source` file may resolve to a string, a single message object, or a full list
  of message objects
- The runner records the requested config snapshot, normalized provider usage, provider
  metadata, ordered trace events, and explicit terminal errors in the canonical
  `RunArtifact`
- Non-successful terminal statuses are surfaced as explicit artifact statuses such as
  `provider_error`, `timed_out`, `invalid`, or `failed`

For optional manual smoke probing, the default cheap OpenRouter model is
`minimax/minimax-m2.7`.

## Evaluation Profiles

- Path: `configs/evaluation_profiles/<profile_id>.yaml`
- Loader: `load_evaluation_profile(path)`
- Purpose: define judges, judge runs, aggregation rules, hybrid final aggregation policy,
  anchors, and security policy

Evaluation profiles describe how scoring should be configured without implementing judge
execution, fingerprinting, or artifact storage.

Judge orchestration in V1 consumes this configuration separately from deterministic checks.
Each logical repetition is preserved as a visible judge iteration result, even when retries
are enabled and an iteration does not succeed. The orchestration layer requests strict JSON
from the judge with:

- `dimensions`
- `summary`
- `evidence`

The judge input includes the case context, the canonical `RunArtifact`, the six shared
dimensions (`task`, `process`, `autonomy`, `closeness`, `efficiency`, `spark`), and an
optional deterministic summary when that data is already available.

Normalized iteration results use these statuses:

- `success`
- `failed`
- `invalid_output`
- `provider_error`
- `timed_out`

If the JSON is structurally valid but some evidence is incomplete, the iteration remains
`success` and records warnings. Aggregated judge output uses only successful iterations by
default and reports the configured repetition count, successful and failed iteration counts,
which repetitions were used or excluded, and any warnings collected during normalization or
retries.

Hybrid final aggregation is configured separately from repeated judge aggregation. V1
supports these per-dimension policies:

- `judge_only`
- `deterministic_only`
- `weighted`

The default policy is `judge_only`. This keeps the judge as the prevailing source unless a
dimension explicitly overrides the policy. Weighted dimensions must define both
`judge_weight` and `deterministic_weight`. If deterministic scoring is missing for a
dimension, the final aggregator falls back to the judge score and emits a warning.

## Fingerprint Semantics

Fingerprints are computed from normalized semantic payloads, not from raw YAML text.

- `run_fingerprint`
  - includes only inputs that affect the raw execution trace
  - excludes non-semantic noise such as config ids, titles, and accidental absolute paths
- `evaluation_fingerprint`
  - includes only inputs that affect judge behavior and final aggregation behavior
  - excludes non-semantic noise such as profile ids or titles

This means equivalent configurations can reproduce the same fingerprint even if files move
or ids change, as long as the semantic inputs remain the same.

## Related Docs

- [Run Artifacts](run_artifacts.md): canonical JSON-serializable schema for recorded runner
  executions
