# Run Artifacts

`personal_agent_eval` defines a canonical JSON-serializable run artifact schema in V1 for
recording the result of one runner execution.

The V1 schema is provider-aware and runner-agnostic:

- It records canonical identity fields for the run, including `schema_version`, `run_id`,
  `case_id`, `suite_id`, `run_profile_id`, and `runner_type`.
- It separates requested execution metadata from provider-returned metadata.
- It stores normalized usage metrics plus raw provider usage when available.
- It represents the execution trace as an ordered event sequence.
- It stores output artifact references and metadata, not embedded file blobs.
- It includes an explicit structured error object for any non-success terminal status.
- It reserves `runner_metadata` for runner-specific extension fields without changing the
  canonical top-level structure.

### OpenClaw evidence (`runner_metadata.openclaw`)

OpenClaw runs attach a typed block at `runner_metadata.openclaw` (constant
`OPENCLAW_RUNNER_METADATA_KEY` in code). It validates as `OpenClawRunEvidence` and keeps
large assets as `OutputArtifactRef` entries (URIs to files outside `run_N.json`), for
example:

- generated OpenClaw config (`openclaw_generated_config`)
- raw session trace (`openclaw_raw_session_trace`)
- captured logs (`openclaw_logs`)
- workspace snapshot archive (`openclaw_workspace_snapshot`)
- workspace diff (`openclaw_workspace_diff`)
- optional key outputs (`openclaw_key_output`), as a list

Concrete `artifact_type` strings are defined on `OpenClawEvidenceArtifactTypes`. Use
`parse_openclaw_run_evidence(run_artifact.runner_metadata)` (or
`with_openclaw_run_evidence(...)`) so downstream code does not scrape ad hoc dict keys.

If the `openclaw` key is present, it must be a valid `OpenClawRunEvidence` payload or
`RunArtifact` validation fails.

V1 terminal statuses are:

- `success`
- `failed`
- `timed_out`
- `invalid`
- `provider_error`

For OpenRouter-backed runs, the schema can record:

- requested model and requested gateway in the request metadata
- gateway, provider name, provider model id, request id, response id, finish reason, and
  native finish reason in provider metadata
- normalized token usage, normalized cost, and raw provider usage payloads
- initial message traces, assistant responses, tool call traces, retry lifecycle events, and
  final output events
- explicit terminal errors for provider failures, timeouts, invalid provider output, and
  runner execution failures

The schema package only defines the artifact surface. It does not implement runner
execution, judge logic, fingerprinting, or artifact storage.

When the provider is OpenRouter, the stored usage payload may include:

- `input_tokens`
- `output_tokens`
- `total_tokens`
- `reasoning_tokens`
- `cached_input_tokens`
- `cache_write_tokens`
- `cost_usd`

The raw provider payload is still preserved as-is under `raw_provider_usage`, so OpenRouter
fields such as `cost_details` remain inspectable even if the normalized schema only promotes a
subset for reporting.

Deterministic evaluation in V1 consumes these canonical `RunArtifact` objects directly. The
deterministic evaluator records per-check pass/fail outcomes plus structured metadata and
outputs without depending on any judge orchestration.

Judge orchestration also consumes `RunArtifact` objects directly, but it produces a separate
judge result surface rather than mutating the run artifact schema. V1 judge orchestration
keeps two layers:

- raw judge attempt results, which preserve each provider call and any provider-facing
  failures
- normalized judge iteration results, which map one logical repetition onto a stable status
  and structured fields for `summary`, `dimensions` (with per-dimension `evidence` and
  `score`), `warnings`, and `raw_result_ref`

Aggregated judge results operate across repetitions for one judge. The default aggregation
method is the median across successful iterations only. Failed or excluded iterations remain
visible in the aggregated result and do not contribute scores.

Hybrid aggregation in V1 produces a separate final evaluation artifact rather than mutating
the run artifact or the judge result. That final result keeps:

- `deterministic_dimensions`
- `judge_dimensions`
- `final_dimensions`
- `final_score`
- `security`
- `warnings`

This makes it possible to inspect what deterministic evaluation produced, what the judge
produced, and what the final configured hybrid policy actually used.

## Storage Layout

V1 stores runs and evaluations in separate deterministic filesystem spaces. Storage does not
redefine fingerprint semantics; it consumes precomputed fingerprints and persists both a
small manifest and the normalized fingerprint input payload used to derive that fingerprint.

Run spaces are organized as suite-scoped campaigns keyed by the semantic run-profile
fingerprint:

```text
outputs/runs/suit_<suite_id>/run_profile_<run_profile_fingerprint_short6>/
  manifest.json
  <model_id>/
    <case_id>/
      manifest.json
      run_1.json
      run_1.artifacts/
      run_1.fingerprint_input.json
      run_2.json
      run_2.artifacts/
      run_2.fingerprint_input.json
      ...
```

Within one `<model_id>/<case_id>/` directory:

- `run_N.json` is the raw `RunArtifact` for repetition `N`
- `run_N.artifacts/` stores copied external files referenced by `run_N.json` (for example OpenClaw
  generated config, raw trace, logs, snapshots, diffs, and key outputs)
- `run_N.fingerprint_input.json` stores the full normalized input payload used to derive that
  repetition's `run_fingerprint`
- `manifest.json` maps repetition indices back to their full `run_fingerprint` values. The case-level
  run manifest may also record `runner_type` and, for OpenClaw runs, `openclaw_agent_id`, so stored
  campaigns remain inspectable without opening each `run_N.json`.

Evaluation spaces are organized similarly, but scoped by both the run-profile fingerprint and the
evaluation fingerprint:

```text
outputs/evaluations/suit_<suite_id>/evaluation_profile_<run_profile_fingerprint_short6>/eval_profile_<evaluation_profile_id>_<evaluation_fingerprint_short6>/
    manifest.json
    fingerprint_input.json
    <model_id>/
      <case_id>/
        manifest.json
        evaluation_result_summary_1.md
      judge_1.prompt.debug.md
      raw_outputs/
        judge_1.json
        judge_1.prompt.user.json
        final_result_1.json
      ...
```

Within one evaluation `<model_id>/<case_id>/` directory:

- `evaluation_result_summary_N.md` is the human-readable evaluation summary for repetition `N`
- `judge_N.prompt.debug.md` is the human-readable judge prompt debug view containing both the
  system prompt and the rendered user prompt
- `raw_outputs/judge_N.json` is the aggregated judge result for repetition `N`
- `raw_outputs/judge_N.prompt.user.json` is the structured subject-view payload used to render
  the judge user prompt
- `raw_outputs/final_result_N.json` is the final hybrid evaluation result for repetition `N`
- `manifest.json` maps repetition indices back to the full `run_fingerprint` and
  `evaluation_fingerprint`

The repository's public example campaigns use this exact layout. See
[Runnable examples](examples/runnable_examples.md) for concrete commands and the intended reading
order for these files.

When `execution_policy.run_repetitions` is greater than `1`, each repetition gets a distinct
`run_fingerprint` because the repetition index is included in the normalized execution settings
used for hashing. The workflow then aggregates repetitions back into one case-level workflow
result by taking the mean of available `final_score` values and per-dimension means of available
final dimensions.

This keeps execution artifacts and evaluation artifacts clearly separated, gives humans stable and
explicit path labels for both campaign layers, and still preserves enough normalized fingerprint
input to reproduce exact semantic identities later.
