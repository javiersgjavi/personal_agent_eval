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
- normalized token usage and raw provider usage payloads
- initial message traces, assistant responses, tool call traces, retry lifecycle events, and
  final output events
- explicit terminal errors for provider failures, timeouts, invalid provider output, and
  runner execution failures

The schema package only defines the artifact surface. It does not implement runner
execution, judge logic, fingerprinting, or artifact storage.

Deterministic evaluation in V1 consumes these canonical `RunArtifact` objects directly. The
deterministic evaluator records per-check pass/fail outcomes plus structured metadata and
outputs without depending on any judge orchestration.

Judge orchestration also consumes `RunArtifact` objects directly, but it produces a separate
judge result surface rather than mutating the run artifact schema. V1 judge orchestration
keeps two layers:

- raw judge attempt results, which preserve each provider call and any provider-facing
  failures
- normalized judge iteration results, which map one logical repetition onto a stable status
  and structured fields for `dimensions`, `summary`, `evidence`, `warnings`, and
  `raw_result_ref`

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
